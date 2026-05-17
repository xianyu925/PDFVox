import { state, dom, getQueryParam } from './viewer-state.js';
import { continueExplainStream } from './viewer-stream.js';

// ---- Time formatting ----

export function formatTime(seconds) {
    if (!isFinite(seconds) || seconds < 0) return '00:00';
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

// ---- Progress UI ----

function _syncPlayPauseIcon() {
    if (!state.audioCtx || !dom.playIcon || !dom.pauseIcon) return;
    if (state.audioCtx.state === 'running') {
        dom.playIcon.style.display = 'none';
        dom.pauseIcon.style.display = 'block';
    } else {
        dom.playIcon.style.display = 'block';
        dom.pauseIcon.style.display = 'none';
    }
}

export function updateProgressUI() {
    if (state.isQaActive) return;
    const slider = dom.progressSlider;
    const label = dom.timeCurrent;
    if (!slider || !state.audioCtx || !state.liveWindowEnd) return;
    const now = state.audioCtx.currentTime;
    const elapsed = state.playedTime + Math.max(0, now - state.playbackStartTime);
    const pct = Math.min(100, (elapsed / state.liveWindowEnd) * 100);
    // 拖拽中不覆盖 slider 值，只更新时间标签
    if (!state.isDragging) {
        slider.value = elapsed;
        if (label) label.textContent = formatTime(elapsed);
        slider.style.background =
            `linear-gradient(to right, #4f46e5 0%, #4f46e5 ${pct}%, #e2e8f0 ${pct}%, #e2e8f0 100%)`;
    }
    // 字级高亮
    _highlightActiveWord(elapsed);
}

function _highlightActiveWord(elapsed) {
    const wts = state.currentWordTimestamps;
    if (!wts.length || !state.currentSentenceStartTime) return;
    const offset = Math.max(0, elapsed - state.currentSentenceStartTime);
    let activeIdx = -1;
    for (let i = 0; i < wts.length; i++) {
        if (offset >= wts[i].start && offset < wts[i].end) {
            activeIdx = i; break;
        }
    }
    // 已越界：全部取消高亮
    if (activeIdx === -1 && offset >= (wts[wts.length - 1]?.end || Infinity)) {
        activeIdx = wts.length;
    }
    const chars = dom.globalSubtitle.querySelectorAll('.sc');
    for (let i = 0; i < chars.length; i++) {
        chars[i].style.color = i === activeIdx ? '#fbbf24' : '';
    }
}

export function startProgressSync() {
    if (state.progressInterval) return;
    updateProgressUI();
    state.progressInterval = setInterval(updateProgressUI, 100);
}

export function stopProgressSync() {
    if (state.progressInterval) {
        clearInterval(state.progressInterval);
        state.progressInterval = null;
    }
}

// ---- Audio playback ----

export function initAudioContext() {
    if (!state.audioCtx) {
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        state.audioCtx = new AudioContext();
    }
    if (state.audioCtx.state === 'suspended') {
        state.audioCtx.resume().catch(e => console.error(e));
    }
    try {
        const buffer = state.audioCtx.createBuffer(1, 1, 22050);
        const source = state.audioCtx.createBufferSource();
        source.buffer = buffer;
        source.connect(state.audioCtx.destination);
        source.start(0);
    } catch (e) { }

    state.nextPlayTime = state.audioCtx.currentTime + 0.1;
    state.playbackStartTime = state.nextPlayTime;
    state.audioQueue = [];
    dom.globalSubtitle.innerHTML = "";
    dom.globalSubtitle.classList.remove('active');
    state.isProcessingQueue = false;
    _syncPlayPauseIcon();
}

function base64ToArrayBuffer(base64) {
    const binaryString = window.atob(base64);
    const len = binaryString.length;
    const bytes = new Uint8Array(len);
    for (let i = 0; i < len; i++) {
        bytes[i] = binaryString.charCodeAt(i);
    }
    return bytes.buffer;
}

export async function queueAudioChunk(base64Data, page, sentence, duration, wordTimestamps) {
    if (!state.audioCtx) return;
    const d = duration || 0;
    if (!state.isQaActive) {
        state.sentenceStartTimes.push({
            page: page,
            start: state.liveWindowEnd,
            duration: d,
            wordTimestamps: wordTimestamps || [],
        });
        state.liveWindowEnd += d;
        dom.progressSlider.max = state.liveWindowEnd;
        dom.timeTotal.textContent = formatTime(state.liveWindowEnd);
    }
    state.audioQueue.push({
        data: base64Data, page: page,
        sentence: sentence || '', duration: d,
        wordTimestamps: wordTimestamps || [],
    });
    if (!state.isProcessingQueue) {
        processAudioQueue();
    }
}

async function processAudioQueue() {
    if (state.isProcessingQueue || state.audioQueue.length === 0) return;
    state.isProcessingQueue = true;

    while (state.audioQueue.length > 0) {
        const item = state.audioQueue.shift();
        if (state.isSeeking) break;

        if (!state.isQaActive && item.page !== state.currentPlayingPage) {
            state.currentPlayingPage = item.page;
            state.currentPage = item.page;

            if (state.pageTimeMap.length > 0 && !state.pageTimeMap[state.pageTimeMap.length - 1].endTime) {
                state.pageTimeMap[state.pageTimeMap.length - 1].endTime = state.playedTime;
            }
            if (state.pageTimeMap.length === 0 || state.pageTimeMap[state.pageTimeMap.length - 1].page !== item.page) {
                state.pageTimeMap.push({ page: item.page, startTime: state.playedTime });
            }

            const pageEl = document.getElementById(`page-wrapper-${state.currentPlayingPage}`);
            if (pageEl) {
                document.querySelectorAll('.pdf-page-wrapper').forEach(el => el.classList.remove('active-page'));
                pageEl.classList.add('active-page');
                pageEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
        }

        try {
            if (item.sentence) {
                // 逐字渲染字幕，用于字级高亮
                const wts = item.wordTimestamps || [];
                state.currentWordTimestamps = wts;
                state.currentSentenceStartTime = state.playedTime;
                if (wts.length > 0) {
                    const spans = wts.map((w, i) =>
                        `<span class="sc" data-idx="${i}" style="transition:color 0.1s;">${w.char}</span>`
                    ).join('');
                    dom.globalSubtitle.innerHTML = spans;
                } else {
                    dom.globalSubtitle.textContent = item.sentence;
                }
                dom.globalSubtitle.classList.add('active');
            }

            const arrayBuffer = base64ToArrayBuffer(item.data);
            const int16Data = new Int16Array(arrayBuffer);
            const audioBuffer = state.audioCtx.createBuffer(1, int16Data.length, 24000);
            const channelData = audioBuffer.getChannelData(0);
            for (let i = 0; i < int16Data.length; i++) {
                channelData[i] = int16Data[i] / 32768.0;
            }

            const source = state.audioCtx.createBufferSource();
            source.buffer = audioBuffer;
            if (state.audioCtx._masterGain) {
                source.connect(state.audioCtx._masterGain);
            } else {
                source.connect(state.audioCtx.destination);
            }

            const now = state.audioCtx.currentTime;
            if (state.nextPlayTime < now) state.nextPlayTime = now;

            await new Promise((resolve) => {
                source.onended = () => {
                    if (!state.isQaActive) {
                        state.playedTime += item.duration || audioBuffer.duration;
                        state.playbackStartTime = state.audioCtx.currentTime;
                    }
                    resolve();
                };
                source.start(state.nextPlayTime);
                state.nextPlayTime += audioBuffer.duration;
            });
        } catch (err) {
            console.error('PCM 音频处理失败:', err);
            await new Promise(resolve => setTimeout(resolve, 100));
        }
    }

    dom.globalSubtitle.classList.remove('active');
    state.isProcessingQueue = false;
}

// ---- Seek ----

export async function seekToTime(targetSeconds) {
    if (state.isSeeking || state.sentenceStartTimes.length === 0) return;
    targetSeconds = Math.max(0, Math.min(targetSeconds, state.liveWindowEnd));
    state.isSeeking = true;

    // 在 sentenceStartTimes 中二分查找目标时间所属的句子
    let targetPage = 1;
    let pageOffset = 0;  // 目标页内，目标句之前的句子累计时长

    const arr = state.sentenceStartTimes;
    let lo = 0, hi = arr.length - 1, found = -1;
    while (lo <= hi) {
        const mid = (lo + hi) >>> 1;
        const s = arr[mid].start;
        const e = s + arr[mid].duration;
        if (targetSeconds >= s && targetSeconds < e) { found = mid; break; }
        if (targetSeconds < s) hi = mid - 1;
        else lo = mid + 1;
    }
    if (found === -1) found = Math.min(lo, arr.length - 1);

    targetPage = arr[found].page;
    // 计算该页内此句之前的累计偏移
    for (let i = found - 1; i >= 0 && arr[i].page === targetPage; i--) {
        pageOffset += arr[i].duration;
    }

    if (state.seekAbortController) {
        state.seekAbortController.abort();
    }
    if (state.currentEventSource) {
        try { state.currentEventSource.close(); } catch (e) { }
        state.currentEventSource = null;
    }

    state.audioQueue = [];
    dom.globalSubtitle.classList.remove('active');
    dom.globalSubtitle.innerHTML = '';
    state.currentWordTimestamps = [];
    state.currentSentenceStartTime = 0;
    initAudioContext();
    state.isSeeking = false;  // 旧队列已清空，允许新的 processAudioQueue 运行
    if (state.audioCtx.state === 'suspended') {
        await state.audioCtx.resume();
    }
    state.nextPlayTime = state.audioCtx.currentTime + 0.1;
    state.playbackStartTime = state.nextPlayTime;
    stopProgressSync();

    const fileId = getQueryParam('file_id');
    if (!fileId) { state.isSeeking = false; return; }

    state.currentPage = targetPage;
    state.currentPlayingPage = targetPage;

    const pageEl = document.getElementById(`page-wrapper-${targetPage}`);
    if (pageEl) {
        document.querySelectorAll('.pdf-page-wrapper').forEach(el => el.classList.remove('active-page'));
        pageEl.classList.add('active-page');
        pageEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    state.seekAbortController = new AbortController();

    try {
        const url = `/explain/playback/seek/${fileId}/page/${targetPage}?time_offset=${encodeURIComponent(pageOffset.toFixed(2))}`;
        const resp = await fetch(url, { signal: state.seekAbortController.signal });
        if (!resp.ok) {
            console.error('seek 请求失败:', resp.status);
            state.isSeeking = false;
            return;
        }

        const reader = resp.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buf = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buf += decoder.decode(value, { stream: true });
            const parts = buf.split('\n\n');
            buf = parts.pop();
            for (const part of parts) {
                const line = part.split('\n').map(l => l.replace(/^data:\s*/, '')).join('\n');
                if (!line || line === '[DONE]') continue;
                try {
                    const payload = JSON.parse(line);
                    if (payload.type === 'audio' && payload.data) {
                        queueAudioChunk(payload.data, payload.page || targetPage, payload.sentence, payload.duration || 0, payload.word_timestamps || []);
                    } else if (payload.type === 'error') {
                        console.error('seek error:', payload.message);
                    }
                } catch (e) {
                    console.error('解析 seek 流数据出错', e, line);
                }
            }
        }

        // 从目标句的开始时间恢复 playedTime
        state.playedTime = arr[found].start;
        state.playbackStartTime = state.nextPlayTime;
        startProgressSync();

        // 启动后续页面的 SSE 讲解流，确保 seek 后讲解持续生成
        continueExplainStream(targetPage + 1);
    } catch (e) {
        if (e.name === 'AbortError') return;
        console.error('seek 请求异常:', e);
    } finally {
        state.seekAbortController = null;
        state.isSeeking = false;
    }
}

// ---- Controls wiring ----

export function setupPlayerControls() {
    dom.playPauseBtn.addEventListener('click', async () => {
        if (!state.audioCtx) {
            initAudioContext();
            startProgressSync();
        }
        if (state.audioCtx.state === 'suspended') {
            await state.audioCtx.resume();
            state.playbackStartTime = state.audioCtx.currentTime;
            dom.playIcon.style.display = 'none';
            dom.pauseIcon.style.display = 'block';
            startProgressSync();
        } else {
            state.playedTime += Math.max(0, state.audioCtx.currentTime - state.playbackStartTime);
            await state.audioCtx.suspend();
            dom.playIcon.style.display = 'block';
            dom.pauseIcon.style.display = 'none';
            stopProgressSync();
            updateProgressUI();
        }
    });

    dom.progressSlider.addEventListener('input', (e) => {
        state.isDragging = true;
        const t = parseFloat(e.target.value);
        if (!isNaN(t)) dom.timeCurrent.textContent = formatTime(t);
    });

    dom.progressSlider.addEventListener('change', (e) => {
        state.isDragging = false;
        const t = parseFloat(e.target.value);
        if (!isNaN(t) && t >= 0) seekToTime(t);
    });

    dom.volumeSlider.addEventListener('input', (e) => {
        const v = parseFloat(e.target.value);
        if (!state.audioCtx) return;
        if (!state.audioCtx._masterGain) {
            const gain = state.audioCtx.createGain();
            gain.gain.value = v;
            gain.connect(state.audioCtx.destination);
            state.audioCtx._masterGain = gain;
        } else {
            state.audioCtx._masterGain.gain.value = v;
        }
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowRight') {
            if (state.sentenceStartTimes.length === 0) return;
            e.preventDefault();
            const now = state.audioCtx ? state.audioCtx.currentTime : 0;
            const elapsed = state.playedTime + Math.max(0, now - state.playbackStartTime);
            const target = Math.min(elapsed + 5, state.liveWindowEnd);
            console.log(`ArrowRight: elapsed=${elapsed.toFixed(1)} target=${target.toFixed(1)} window=${state.liveWindowEnd.toFixed(1)}`);
            seekToTime(target);
        } else if (e.key === 'ArrowLeft') {
            if (state.sentenceStartTimes.length === 0) return;
            e.preventDefault();
            const now = state.audioCtx ? state.audioCtx.currentTime : 0;
            const elapsed = state.playedTime + Math.max(0, now - state.playbackStartTime);
            const target = Math.max(0, elapsed - 5);
            console.log(`ArrowLeft: elapsed=${elapsed.toFixed(1)} target=${target.toFixed(1)}`);
            seekToTime(target);
        }
    });
}
