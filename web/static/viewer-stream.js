import { state, dom, getQueryParam } from './viewer-state.js';
import { initAudioContext, queueAudioChunk, startProgressSync, formatTime } from './viewer-audio.js';

// ---- 按钮状态机 ----

const BTN_IDLE = 0;       // "一键生成沉浸式讲解"
const BTN_GENERATING = 1; // "终止讲解生成"
const BTN_PAUSED = 2;     // "继续生成讲解"

let _btnState = BTN_IDLE;
let _btnOriginalText = '';

function _setExplainButton(state, optText) {
    _btnState = state;
    const btn = dom.explainAllBtn;
    btn.disabled = false;
    switch (state) {
        case BTN_IDLE:
            btn.textContent = _btnOriginalText || '一键生成沉浸式讲解';
            btn.style.background = '';
            dom.explainStatus.textContent = '';
            break;
        case BTN_GENERATING:
            btn.textContent = '终止讲解生成';
            btn.style.background = '#ef4444';
            dom.explainStatus.textContent = optText || '连接中…';
            break;
        case BTN_PAUSED:
            btn.textContent = '继续生成讲解';
            btn.style.background = 'linear-gradient(135deg, var(--primary-color), #6366f1)';
            dom.explainStatus.textContent = '讲解已暂停，语音继续播放';
            break;
    }
}

// ---- 流式讲解核心 ----

function _startExplainStream(courseName, { skipReset = false } = {}) {
    const fileId = getQueryParam('file_id');
    if (!fileId) return;

    const fromPage = Math.min(state.resumePage || state.currentPage, state.totalPages || 1);

    state.courseName = courseName;

    if (!skipReset) {
        // DVR 窗口重置（每次启动新流都重置）
        state.playedTime = 0;
        state.liveWindowEnd = 0;
        state.pageTimeMap = [];
        state.sentenceStartTimes = [];
        dom.progressSlider.max = 0;
        dom.progressSlider.value = 0;
        dom.timeTotal.textContent = '00:00';
        dom.timeCurrent.textContent = '00:00';

        initAudioContext();
        startProgressSync();
        state.audioCtx.resume().catch(e => console.error(e));
    }

    _setExplainButton(BTN_GENERATING, '连接中…');

    if (state.currentEventSource) {
        try { state.currentEventSource.close(); } catch (e) { }
        state.currentEventSource = null;
    }

    let isCancelled = false;

    const streamUrl = `/explain/all-stream-v3/${fileId}?course_name=${encodeURIComponent(courseName)}&from_page=${fromPage}`;
    state.currentEventSource = new EventSource(streamUrl);
    const es = state.currentEventSource;

    es.onmessage = function (event) {
        if (isCancelled) return;

        if (event.data === '[DONE]') {
            if (state.pageTimeMap.length > 0) {
                state.pageTimeMap[state.pageTimeMap.length - 1].endTime = state.liveWindowEnd;
            }
            if (state.currentEventSource) { state.currentEventSource.close(); state.currentEventSource = null; }
            _setExplainButton(BTN_IDLE);
            return;
        }

        try {
            const payload = JSON.parse(event.data);
            switch (payload.type) {
                case 'page_start':
                    _setExplainButton(BTN_GENERATING, `AI 正在构思第 ${payload.page} 页…`);
                    break;
                case 'audio':
                    if (payload.data) {
                        _setExplainButton(BTN_GENERATING, `正在生成第 ${payload.page} 页语音…`);
                        queueAudioChunk(payload.data, payload.page, payload.sentence, payload.duration || 0, payload.word_timestamps || []);
                    }
                    break;
                case 'end':
                    state.resumePage = payload.page + 1;
                    break;
                case 'error':
                    dom.explainStatus.textContent = `发生错误: ${payload.message}`;
                    break;
                case 'cancelled':
                    if (state.currentEventSource) { state.currentEventSource.close(); state.currentEventSource = null; }
                    _setExplainButton(BTN_IDLE);
                    return;
            }
        } catch (e) {
            console.error('解析流数据异常:', e, event.data);
        }
    };

    es.onerror = function () {
        if (!isCancelled) {
            _setExplainButton(BTN_IDLE);
        }
        if (state.currentEventSource) { state.currentEventSource.close(); state.currentEventSource = null; }
    };

    // 返回取消函数
    return async () => {
        isCancelled = true;
        try { await fetch(`/explain/cancel/${fileId}`, { method: 'DELETE' }); } catch (e) { }
        if (es) es.close();
        if (state.currentEventSource) { state.currentEventSource.close(); state.currentEventSource = null; }
    };
}

let _cancelFn = null;

// ---- 一键生成讲解按钮 ----

export function setupExplainAllButton() {
    _btnOriginalText = dom.explainAllBtn.textContent;

    dom.explainAllBtn.addEventListener('click', async () => {
        const courseName = dom.courseNameInput.value.trim();

        switch (_btnState) {
            case BTN_IDLE: {
                if (!getQueryParam('file_id') || !courseName) return alert('请检查信息完整');
                _cancelFn = await _startExplainStream(courseName);
                break;
            }
            case BTN_GENERATING: {
                // 终止生成，但语音继续播放
                if (_cancelFn) { const fn = _cancelFn; _cancelFn = null; await fn(); }
                _setExplainButton(BTN_PAUSED);
                break;
            }
            case BTN_PAUSED: {
                // 继续生成
                _cancelFn = await _startExplainStream(courseName);
                break;
            }
        }
    });
}

// ---- 恢复讲解（从问答返回时调用） ----

export async function resumeExplanation(fileId, courseName) {
    state.isQaActive = false;
    dom.progressSlider.disabled = false;
    _cancelFn = await _startExplainStream(courseName);
}

export async function continueExplainStream(fromPage) {
    const name = state.courseName || dom.courseNameInput.value.trim();
    if (!name || !getQueryParam('file_id')) return;
    if (fromPage > state.totalPages) return;
    state.resumePage = fromPage;
    _cancelFn = await _startExplainStream(name, { skipReset: true });
}

// ---- 提问按钮 ----

export function setupAskButton() {
    if (!dom.askBtn) return;

    dom.askBtn.addEventListener('click', async () => {
        const fileId = getQueryParam('file_id');
        const courseName = dom.courseNameInput.value.trim();
        if (!fileId) return alert('缺少 file_id');

        state.resumePage = state.currentPlayingPage || state.currentPage;
        state.isQaActive = true;

        if (state.currentEventSource) { try { state.currentEventSource.close(); } catch (e) { } state.currentEventSource = null; }
        if (state.audioCtx) try { await state.audioCtx.suspend(); } catch (e) { }
        if (dom.playIcon && dom.pauseIcon) {
            dom.playIcon.style.display = 'block';
            dom.pauseIcon.style.display = 'none';
        }
        state.audioQueue = [];
        state.isProcessingQueue = false;

        initAudioContext();
        dom.progressSlider.disabled = true;

        const originalText = dom.askBtn.textContent;
        dom.askBtn.textContent = '🎤 录音中...';
        dom.askBtn.disabled = true;

        const progressContainer = document.createElement('div');
        progressContainer.style.cssText = 'position: fixed; top: 20px; right: 80px; background: rgba(255,255,255,0.95); border-radius: 12px; padding: 16px; z-index: 1000; min-width: 260px; border:1px solid #e2e8f0';
        progressContainer.innerHTML = `
            <div id="ask-info" style="font-size:14px; font-weight:600; color:#0f172a; margin-bottom:10px;">正在聆听...（说完请点击「提问结束」）</div>
            <div style="display:flex; gap:8px;">
                <button id="ask-finish" style="flex:1; padding:8px 12px; background:#4f46e5; color:white; border:none; border-radius:6px; cursor:pointer; font-size:13px;">提问结束</button>
                <button id="ask-cancel" style="flex:1; padding:8px 12px; background:#e2e8f0; color:#334155; border:none; border-radius:6px; cursor:pointer; font-size:13px;">取消</button>
            </div>
        `;
        document.body.appendChild(progressContainer);

        let mediaStream = null, recorder = null, chunks = [];
        let silenceTimer = null, startedSpeaking = false, isCancelledRecording = false;

        const stopAll = async () => {
            try { if (recorder && recorder.state !== 'inactive') recorder.stop(); } catch (e) { }
            try { if (mediaStream) mediaStream.getTracks().forEach(t => t.stop()); } catch (e) { }
        };

        document.getElementById('ask-finish').addEventListener('click', async () => {
            document.getElementById('ask-info').textContent = '正在处理...';
            await stopAll();
        });

        document.getElementById('ask-cancel').addEventListener('click', async () => {
            isCancelledRecording = true;
            await stopAll();
            progressContainer.remove();
            dom.askBtn.textContent = originalText;
            dom.askBtn.disabled = false;
            state.isQaActive = false;
            dom.progressSlider.disabled = false;
        });

        try {
            mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        } catch (e) {
            alert('无法访问麦克风，请检查权限');
            progressContainer.remove();
            dom.askBtn.textContent = originalText;
            dom.askBtn.disabled = false;
            return;
        }

        const monitorCtx = new (window.AudioContext || window.webkitAudioContext)();
        const source = monitorCtx.createMediaStreamSource(mediaStream);
        const analyser = monitorCtx.createAnalyser();
        analyser.fftSize = 2048;
        source.connect(analyser);
        const dataArr = new Uint8Array(analyser.fftSize);

        recorder = new MediaRecorder(mediaStream);
        recorder.ondataavailable = (e) => { if (e.data && e.data.size > 0) chunks.push(e.data); };
        recorder.start(1000);

        const maxRecordMs = 10000, silenceThreshold = 0.02, silenceTimeout = 800;
        const startTime = Date.now();

        const checkSilence = () => {
            analyser.getByteTimeDomainData(dataArr);
            let sum = 0;
            for (let i = 0; i < dataArr.length; i++) {
                const v = (dataArr[i] - 128) / 128;
                sum += v * v;
            }
            const rms = Math.sqrt(sum / dataArr.length);
            if (rms > silenceThreshold) {
                startedSpeaking = true;
                if (silenceTimer) { clearTimeout(silenceTimer); silenceTimer = null; }
            } else if (startedSpeaking && !silenceTimer) {
                silenceTimer = setTimeout(async () => { await stopAll(); }, silenceTimeout);
            }
            if (Date.now() - startTime > maxRecordMs) stopAll();
            if (recorder && recorder.state !== 'inactive') requestAnimationFrame(checkSilence);
        };
        requestAnimationFrame(checkSilence);

        recorder.onstop = async () => {
            try { monitorCtx.close(); } catch (e) { }
            if (isCancelledRecording) return;
            const blob = new Blob(chunks, { type: 'audio/webm' });
            const wavBlob = await _convertBlobTo16kWav(blob);

            const form = new FormData();
            form.append('file', wavBlob, 'question.wav');
            form.append('file_id', fileId);
            form.append('page_num', String(state.currentPage || 1));

            const ac = new AbortController();
            state.currentStreamAbort = ac;

            try {
                const resp = await fetch('/qa/ask/stream', { method: 'POST', body: form, signal: ac.signal });
                if (!resp.ok) throw new Error('后端返回错误: ' + resp.status);

                const reader = resp.body.getReader();
                const decoder = new TextDecoder('utf-8');
                let buf = '';

                initAudioContext();
                if (state.audioCtx.state === 'suspended') await state.audioCtx.resume();

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    buf += decoder.decode(value, { stream: true });
                    let parts = buf.split('\n\n');
                    buf = parts.pop();
                    for (const part of parts) {
                        const line = part.split('\n').map(l => l.replace(/^data:\s*/, '')).join('\n');
                        if (!line) continue;
                        if (line === '[DONE]') {
                            progressContainer.innerHTML = `
                                <div id="ask-info" style="font-size:14px; font-weight:600; color:#0f172a; margin-bottom:8px;">回答播放完毕</div>
                                <button id="resume-stream" style="width:100%; padding:8px 12px; background:#4f46e5; color:white; border:none; border-radius:6px; cursor:pointer; margin-bottom:6px;">▶ 继续讲解</button>
                                <button id="qa-done-close" style="width:100%; padding:8px 12px; background:#e2e8f0; color:#334155; border:none; border-radius:6px; cursor:pointer;">关闭</button>
                            `;
                            document.getElementById('resume-stream').addEventListener('click', () => {
                                progressContainer.remove();
                                resumeExplanation(fileId, courseName, progressContainer);
                            });
                            document.getElementById('qa-done-close').addEventListener('click', () => {
                                progressContainer.remove();
                                state.isQaActive = false;
                                dom.progressSlider.disabled = false;
                            });
                            dom.askBtn.textContent = originalText;
                            dom.askBtn.disabled = false;
                            state.isQaActive = false;
                            dom.progressSlider.disabled = false;
                            break;
                        }
                        try {
                            const payload = JSON.parse(line);
                            if (payload.type === 'audio' && payload.data) {
                                queueAudioChunk(payload.data, payload.page || state.currentPage, payload.sentence, payload.duration || 0, payload.word_timestamps || []);
                            } else if (payload.type === 'error') {
                                document.getElementById('ask-info').textContent = '错误: ' + (payload.message || payload.data || '未知错误');
                            }
                        } catch (e) {
                            console.error('解析流数据出错', e, line);
                        }
                    }
                }
            } catch (e) {
                if (e.name === 'AbortError') return;
                console.error('流式请求出错', e);
                progressContainer.remove();
                dom.askBtn.textContent = originalText;
                dom.askBtn.disabled = false;
                state.isQaActive = false;
                dom.progressSlider.disabled = false;
            }
        };
    });
}

// ---- WAV helpers ----

async function _convertBlobTo16kWav(blob) {
    const ab = await blob.arrayBuffer();
    const decodeCtx = new (window.AudioContext || window.webkitAudioContext)();
    const audioBuffer = await decodeCtx.decodeAudioData(ab);
    const targetRate = 16000;
    const offlineCtx = new OfflineAudioContext(1, Math.ceil(audioBuffer.duration * targetRate), targetRate);
    const src = offlineCtx.createBufferSource();
    const mono = offlineCtx.createBuffer(1, audioBuffer.length, audioBuffer.sampleRate);
    const channelData = audioBuffer.numberOfChannels > 1 ? audioBuffer.getChannelData(0) : audioBuffer.getChannelData(0);
    mono.copyToChannel(channelData, 0);
    src.buffer = mono;
    src.connect(offlineCtx.destination);
    src.start(0);
    const rendered = await offlineCtx.startRendering();
    return new Blob([_encodeWAV(rendered.getChannelData(0), targetRate)], { type: 'audio/wav' });
}

function _encodeWAV(samples, sampleRate) {
    const buffer = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buffer);
    const _ws = (v, o, s) => { for (let i = 0; i < s.length; i++) view.setUint8(o + i, s.charCodeAt(i)); };
    _ws(view, 0, 'RIFF');
    view.setUint32(4, 36 + samples.length * 2, true);
    _ws(view, 8, 'WAVE');
    _ws(view, 12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    _ws(view, 36, 'data');
    view.setUint32(40, samples.length * 2, true);
    for (let i = 0, offset = 44; i < samples.length; i++, offset += 2) {
        const s = Math.max(-1, Math.min(1, samples[i]));
        view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
    }
    return view;
}
