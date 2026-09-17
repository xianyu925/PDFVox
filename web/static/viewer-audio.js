import { state, dom } from './viewer-state.js';
import { formatTime, pcmDuration } from './viewer-timeline.js';
import {
    expandWordTimestamps,
    highlightActiveWord,
    renderSentenceSubtitle,
} from './viewer-subtitles.js';
import { switchToPage } from './viewer-pages.js';

const PLAYBACK_RATES = [0.5, 0.75, 1, 1.25, 1.5, 2];

// ---- Playback state ----
export function getCurrentPlaybackTime() {
    let elapsed = state.playedTime;
    const isPlayingLecture = state.audioCtx &&
        state.audioCtx.state === 'running' &&
        state.currentAudioSource &&
        !state.currentAudioIsQa;
    if (isPlayingLecture) {
        const wallTime = Math.max(
            0,
            state.audioCtx.currentTime - state.playbackStartTime,
        );
        elapsed += wallTime * state.playbackRate;
    }
    if (state.currentAudioEndTime !== null) {
        elapsed = Math.min(elapsed, state.currentAudioEndTime);
    }
    return Math.max(0, Math.min(elapsed, state.liveWindowEnd || elapsed));
}

export function setPlaybackRate(rate) {
    const nextRate = Number(rate);
    if (!PLAYBACK_RATES.includes(nextRate)) return;

    const currentTime = getCurrentPlaybackTime();
    const now = state.audioCtx?.currentTime || 0;
    if (state.currentAudioSource && !state.currentAudioIsQa) {
        state.playedTime = currentTime;
        state.playbackStartTime = now;
    }

    state.playbackRate = nextRate;
    if (state.currentAudioSource) {
        state.currentAudioSource.playbackRate.setValueAtTime(nextRate, now);
        // The queue starts the next source only after this source ends.
        // Resetting the scheduler anchor prevents a stale pre-rate-change
        // end time from inserting a gap before the next sentence.
        state.nextPlayTime = now;
    }
    if (dom.playbackRate) dom.playbackRate.value = String(nextRate);
    updateProgressUI();
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

// ---- Loading indicator ----

function _showLoadingIndicator() {
    if (dom.loadingSpinner) dom.loadingSpinner.style.display = '';
}

function _hideLoadingIndicator() {
    if (dom.loadingSpinner) dom.loadingSpinner.style.display = 'none';
}

export function updateProgressUI() {
    if (state.isQaActive) return;
    const slider = dom.progressSlider;
    const label = dom.timeCurrent;
    if (!slider || !state.audioCtx || !state.liveWindowEnd) return;
    const elapsed = getCurrentPlaybackTime();
    const pct = Math.min(100, (elapsed / state.liveWindowEnd) * 100);
    // 拖拽中不覆盖 slider 值，只更新时间标签
    if (!state.isDragging) {
        slider.value = elapsed;
        if (label) label.textContent = formatTime(elapsed);
        slider.style.background =
            `linear-gradient(to right, #4f46e5 0%, #4f46e5 ${pct}%, #e2e8f0 ${pct}%, #e2e8f0 100%)`;
    }
    // 字级高亮
    highlightActiveWord(elapsed);
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

// ---- Audio context and queue ----
export function stopCurrentAudio() {
    state.playbackEpoch += 1;
    const source = state.currentAudioSource;
    const resolve = state.currentAudioResolve;
    state.currentAudioSource = null;
    state.currentAudioResolve = null;
    state.currentAudioEndTime = null;
    state.currentAudioIsQa = false;
    if (source) {
        source.onended = null;
        try { source.stop(); } catch (e) { }
        try { source.disconnect(); } catch (e) { }
    }
    if (resolve) resolve(false);
}

export function initAudioContext({ resume = true, stopCurrent = true } = {}) {
    if (stopCurrent) stopCurrentAudio();
    if (!state.audioCtx) {
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        state.audioCtx = new AudioContext();
    }
    if (resume && state.audioCtx.state === 'suspended') {
        state.audioCtx.resume().catch(e => console.error(e));
    }
    if (resume) try {
        const buffer = state.audioCtx.createBuffer(1, 1, 22050);
        const source = state.audioCtx.createBufferSource();
        source.buffer = buffer;
        source.connect(state.audioCtx.destination);
        source.start(0);
    } catch (e) { }

    state.nextPlayTime = state.audioCtx.currentTime + 0.1;
    state.playbackStartTime = state.nextPlayTime;
    state.currentAudioEndTime = null;
    state.currentAudioIsQa = false;
    state.audioQueue = [];
    state.isLoading = false;
    _hideLoadingIndicator();
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

export async function queueAudioChunk(
    base64Data,
    page,
    sentence,
    duration,
    wordTimestamps,
    { trackTimeline = true, playbackOffset = 0, chunkIndex = null } = {},
) {
    if (!state.audioCtx) return;
    // The PCM payload is the source of truth. This also prevents a string
    // duration from turning timelineCursor into a concatenated value.
    const offset = Number.isFinite(Number(playbackOffset))
        ? Math.max(0, Number(playbackOffset))
        : 0;
    const fullDuration = pcmDuration(base64Data, duration);
    const d = base64Data
        ? Math.max(0, fullDuration - offset)
        : fullDuration;
    if (!state.isQaActive && trackTimeline) {
        const normalizedIndex = Number(chunkIndex);
        const chunkKey = Number.isInteger(normalizedIndex) && normalizedIndex > 0
            ? `${page}:${normalizedIndex}`
            : null;
        if (chunkKey && state.generatedAudioChunkKeys.has(chunkKey)) return;
        const generatedChunk = {
            data: base64Data,
            page: page,
            start: state.timelineCursor,
            duration: d,
            sentence: sentence || '',
            wordTimestamps: wordTimestamps || [],
            index: chunkKey ? normalizedIndex : null,
        };
        state.generatedAudioChunks.push(generatedChunk);
        if (chunkKey) state.generatedAudioChunkKeys.add(chunkKey);
        state.timelineCursor += d;
        state.liveWindowEnd = Math.max(state.liveWindowEnd, state.timelineCursor);
        dom.progressSlider.max = state.liveWindowEnd;
        dom.timeTotal.textContent = formatTime(state.liveWindowEnd);
    }
    state.audioQueue.push({
        data: base64Data, page: page,
        sentence: sentence || '', duration: d,
        wordTimestamps: wordTimestamps || [],
        isQa: state.isQaActive,
        playbackOffset: offset,
    });
    if (!state.isProcessingQueue) {
        processAudioQueue();
    }
}

async function processAudioQueue() {
    if (state.isProcessingQueue || state.audioQueue.length === 0 || state.isSeeking) return;
    state.isProcessingQueue = true;
    const processingEpoch = state.playbackEpoch;

    // LOADING → PLAYING 自动恢复：新 chunk 已到达
    if (state.isLoading) {
        state.isLoading = false;
        _hideLoadingIndicator();
        if (state.audioCtx && state.audioCtx.state === 'suspended') {
            state.playbackStartTime = state.audioCtx.currentTime;
            await state.audioCtx.resume();
            if (processingEpoch !== state.playbackEpoch) return;
            startProgressSync();
            _syncPlayPauseIcon();
        }
    }

    while (state.audioQueue.length > 0) {
        const item = state.audioQueue.shift();

        if (!item.isQa && item.page !== state.currentPlayingPage) {
            switchToPage(item.page, { updatePlayingPage: true });
        }

        try {
            if (item.sentence) {
                // 逐字渲染字幕，用于字级高亮
                const wts = expandWordTimestamps(item.wordTimestamps);
                state.currentWordTimestamps = wts;
                state.currentSentenceStartTime = state.playedTime - (item.playbackOffset || 0);
                if (wts.length > 0) {
                    renderSentenceSubtitle(item.sentence, wts);
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
            source.playbackRate.value = state.playbackRate;
            source.connect(state.audioCtx.destination);
            const epoch = state.playbackEpoch;
            const contentDuration = item.duration || audioBuffer.duration;
            const itemEndTime = item.isQa
                ? null
                : state.playedTime + contentDuration;

            const now = state.audioCtx.currentTime;
            if (state.nextPlayTime < now) state.nextPlayTime = now;
            const startAt = state.nextPlayTime;
            if (!item.isQa) state.playbackStartTime = startAt;

            const completed = await new Promise((resolve) => {
                state.currentAudioSource = source;
                state.currentAudioResolve = resolve;
                state.currentAudioEndTime = itemEndTime;
                state.currentAudioIsQa = item.isQa;
                source.onended = () => {
                    if (state.currentAudioSource === source) {
                        state.currentAudioSource = null;
                        state.currentAudioResolve = null;
                        state.currentAudioEndTime = null;
                        state.currentAudioIsQa = false;
                    }
                    if (epoch === state.playbackEpoch && !item.isQa) {
                        state.playedTime = itemEndTime;
                        state.playbackStartTime = state.audioCtx.currentTime;
                    }
                    resolve(epoch === state.playbackEpoch);
                };
                source.start(startAt, item.playbackOffset || 0);
                state.nextPlayTime = startAt + contentDuration / state.playbackRate;
            });
            if (!completed || epoch !== state.playbackEpoch) break;
        } catch (err) {
            console.error('PCM 音频处理失败:', err);
            await new Promise(resolve => setTimeout(resolve, 100));
            if (processingEpoch !== state.playbackEpoch) return;
        }
    }

    // A seek starts a replacement processor. The obsolete processor must not
    // clear its running flag, subtitle, or loading state when it later unwinds.
    if (processingEpoch !== state.playbackEpoch) return;

    // 队列已空 → 进入 LOADING 状态，冻结 currentTime，避免空转
    if (!state.isQaActive && state.audioCtx && !state.isSeeking && state.audioCtx.state === 'running') {
        state.playedTime = getCurrentPlaybackTime();
        state.playbackStartTime = state.audioCtx.currentTime;
        await state.audioCtx.suspend();
        if (processingEpoch !== state.playbackEpoch) return;
        state.isLoading = true;
        _showLoadingIndicator();
        stopProgressSync();
        _syncPlayPauseIcon();
        updateProgressUI();
    }

    dom.globalSubtitle.classList.remove('active');
    state.isProcessingQueue = false;
    if (state.audioQueue.length > 0 && !state.isSeeking) {
        processAudioQueue();
    }
}

// ---- Seek ----

function _findGeneratedChunkIndex(targetSeconds) {
    const chunks = state.generatedAudioChunks;
    if (targetSeconds >= state.liveWindowEnd) return chunks.length;

    let lo = 0;
    let hi = chunks.length - 1;
    while (lo <= hi) {
        const mid = (lo + hi) >>> 1;
        const chunk = chunks[mid];
        const end = chunk.start + chunk.duration;
        if (targetSeconds < chunk.start) {
            hi = mid - 1;
        } else if (targetSeconds >= end) {
            lo = mid + 1;
        } else {
            return mid;
        }
    }
    return Math.min(lo, chunks.length);
}

export async function seekToTime(targetSeconds) {
    if (state.isSeeking || state.generatedAudioChunks.length === 0) return;
    targetSeconds = Math.max(0, Math.min(targetSeconds, state.liveWindowEnd));
    state.isSeeking = true;

    try {
        // Seeking is a local DVR operation. Keep the live EventSource open so
        // dragging cannot request or synthesize audio that has not arrived yet.
        stopCurrentAudio();
        state.audioQueue = [];
        state.currentWordTimestamps = [];
        state.currentSentenceStartTime = null;
        state.playedTime = targetSeconds;
        if (dom.progressSlider) dom.progressSlider.value = targetSeconds;
        if (dom.timeCurrent) dom.timeCurrent.textContent = formatTime(targetSeconds);

        initAudioContext({ resume: true, stopCurrent: false });
        if (state.audioCtx.state === 'suspended') await state.audioCtx.resume();
        // Audio may have arrived while resume() was pending. It is already in
        // generatedAudioChunks, so rebuild the queue from that canonical cache.
        state.audioQueue = [];
        const chunks = state.generatedAudioChunks;
        const targetIndex = _findGeneratedChunkIndex(targetSeconds);
        const targetChunk = chunks[targetIndex] || chunks[chunks.length - 1];
        state.nextPlayTime = state.audioCtx.currentTime + 0.1;
        state.playbackStartTime = state.nextPlayTime;

        if (targetChunk) {
            state.currentPlayingPage = targetChunk.page;
            switchToPage(targetChunk.page);
        }

        // processAudioQueue deliberately ignores work while isSeeking is true.
        // Release the flag before enqueuing the cached replay range.
        state.isSeeking = false;
        for (let i = targetIndex; i < chunks.length; i++) {
            const chunk = chunks[i];
            const offset = i === targetIndex
                ? Math.max(0, targetSeconds - chunk.start)
                : 0;
            const remainingDuration = Math.max(0, chunk.duration - offset);
            if (remainingDuration <= 0) continue;
            queueAudioChunk(
                chunk.data,
                chunk.page,
                chunk.sentence,
                remainingDuration,
                chunk.wordTimestamps,
                {
                    trackTimeline: false,
                    playbackOffset: offset,
                    chunkIndex: chunk.index,
                },
            );
        }
        startProgressSync();
        updateProgressUI();
    } finally {
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
            // LOADING 态：用户点击 → 转为 PAUSED，不恢复播放
            if (state.isLoading) {
                state.isLoading = false;
                _hideLoadingIndicator();
                dom.playIcon.style.display = 'block';
                dom.pauseIcon.style.display = 'none';
                return;
            }
            // PAUSED 态但队列为空 → 进入 LOADING
            if (state.audioQueue.length === 0 && !state.isSeeking) {
                state.isLoading = true;
                _showLoadingIndicator();
                return;
            }
            await state.audioCtx.resume();
            state.playbackStartTime = state.audioCtx.currentTime;
            dom.playIcon.style.display = 'none';
            dom.pauseIcon.style.display = 'block';
            startProgressSync();
        } else {
            state.playedTime = getCurrentPlaybackTime();
            state.playbackStartTime = state.audioCtx.currentTime;
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
        if (!isNaN(t)) {
            dom.timeCurrent.textContent = formatTime(t);
            const pct = state.liveWindowEnd > 0
                ? Math.min(100, Math.max(0, t / state.liveWindowEnd * 100))
                : 0;
            e.target.style.background =
                `linear-gradient(to right, #4f46e5 0%, #4f46e5 ${pct}%, #e2e8f0 ${pct}%, #e2e8f0 100%)`;
        }
    });

    dom.progressSlider.addEventListener('change', (e) => {
        state.isDragging = false;
        const t = parseFloat(e.target.value);
        if (!isNaN(t) && t >= 0) seekToTime(t);
    });

    if (dom.playbackRate) {
        dom.playbackRate.value = String(state.playbackRate);
        dom.playbackRate.addEventListener('change', (event) => {
            setPlaybackRate(event.target.value);
        });
    }

    document.addEventListener('keydown', (e) => {
        const target = e.target;
        const isPlayerControl = target === dom.playbackRate || target === dom.progressSlider;
        const isEditing = target instanceof HTMLElement && (
            target.isContentEditable ||
            ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)
        ) && !isPlayerControl;
        if (isEditing || !['ArrowLeft', 'ArrowRight'].includes(e.key)) return;

        if (e.shiftKey) {
            e.preventDefault();
            if (e.repeat) return;
            const currentIndex = PLAYBACK_RATES.indexOf(state.playbackRate);
            const direction = e.key === 'ArrowRight' ? 1 : -1;
            const nextIndex = Math.max(
                0,
                Math.min(PLAYBACK_RATES.length - 1, currentIndex + direction),
            );
            setPlaybackRate(PLAYBACK_RATES[nextIndex]);
            return;
        }

        if (
            state.generatedAudioChunks.length === 0 ||
            state.isSeeking
        ) return;
        e.preventDefault();
        const elapsed = getCurrentPlaybackTime();
        const seekDelta = e.key === 'ArrowRight' ? 5 : -5;
        const seekTarget = Math.max(
            0,
            Math.min(state.liveWindowEnd, elapsed + seekDelta),
        );
        seekToTime(seekTarget);
    });
}
