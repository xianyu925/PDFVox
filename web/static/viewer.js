document.addEventListener('DOMContentLoaded', () => {
    const courseNameInput = document.getElementById('course-name');
    const explainAllBtn = document.getElementById('explain-all-btn');
    const pdfPreview = document.getElementById('pdf-preview');
    const rightPanel = document.getElementById('right-panel');
    const fullscreenBtn = document.getElementById('fullscreen-btn');
    const globalSubtitle = document.getElementById('global-subtitle');

    let totalPages = 0;
    let currentPage = 1;

    function getQueryParam(name) {
        const params = new URLSearchParams(window.location.search);
        return params.get(name) || "";
    }

    function updatePageCounter() {
        const counter = document.getElementById('page-counter');
        if (counter) {
            counter.textContent = `${currentPage} / ${totalPages}`;
        }
        try {
            if (pageSlider) pageSlider.value = currentPage;
        } catch (e) { }
    }

    function detectCurrentPage() {
        const container = document.getElementById('pdf-container');
        const pageElements = document.querySelectorAll('.pdf-page-wrapper');
        if (pageElements.length === 0) return;

        const containerTop = container.scrollTop;
        const containerHeight = container.clientHeight;

        for (let i = 0; i < pageElements.length; i++) {
            const page = pageElements[i];
            const pageTop = page.offsetTop;
            const pageHeight = page.offsetHeight;

            if (pageTop <= containerTop + containerHeight / 2 && pageTop + pageHeight > containerTop + containerHeight / 2) {
                currentPage = i + 1;
                updatePageCounter();
                break;
            }
        }
    }

    fullscreenBtn.addEventListener('click', () => {
        if (!document.fullscreenElement) {
            rightPanel.requestFullscreen().catch(err => console.error(err));
        } else {
            document.exitFullscreen();
        }
    });

    document.addEventListener('fullscreenchange', () => {
        if (document.fullscreenElement) {
            fullscreenBtn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 3v3a2 2 0 0 1-2 2H3m18 0h-3a2 2 0 0 1-2-2V3m0 18v-3a2 2 0 0 1 2-2h3M3 16h3a2 2 0 0 1 2 2v3"></path></svg> 退出全屏';
            document.getElementById('left-panel').style.display = 'none';
            const curEl = document.getElementById(`page-wrapper-${currentPage}`);
            if (curEl) {
                document.querySelectorAll('.pdf-page-wrapper').forEach(el => el.style.display = 'none');
                curEl.style.display = 'block';
                curEl.classList.add('active-page');
            }
        } else {
            fullscreenBtn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"></path></svg> 沉浸模式';
            document.getElementById('left-panel').style.display = 'flex';
            document.querySelectorAll('.pdf-page-wrapper').forEach(el => el.style.display = 'flex');
        }
    });

    let audioCtx = null;
    let nextPlayTime = 0;
    let audioQueue = [];
    let isProcessingQueue = false;

    let currentPlayingPage = 0;
    let resumePage = 1;
    let currentEventSource = null;
    let currentStreamAbort = null;

    function initAudioContext() {
        if (!audioCtx) {
            const AudioContext = window.AudioContext || window.webkitAudioContext;
            audioCtx = new AudioContext();
        }
        if (audioCtx.state === 'suspended') {
            audioCtx.resume().catch(e => console.error(e));
        }

        try {
            const buffer = audioCtx.createBuffer(1, 1, 22050);
            const source = audioCtx.createBufferSource();
            source.buffer = buffer;
            source.connect(audioCtx.destination);
            source.start(0);
        } catch (e) { }

        nextPlayTime = audioCtx.currentTime + 0.1;
        audioQueue = [];
        globalSubtitle.innerHTML = "";
        globalSubtitle.classList.remove('active');
        isProcessingQueue = false;
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

    async function queueAudioChunk(base64Data, page, sentence) {
        if (!audioCtx) return;
        audioQueue.push({ data: base64Data, page: page, sentence: sentence || '' });
        if (!isProcessingQueue) {
            processAudioQueue();
        }
    }

    async function processAudioQueue() {
        if (isProcessingQueue || audioQueue.length === 0) return;
        isProcessingQueue = true;

        while (audioQueue.length > 0) {
            const item = audioQueue.shift();

            if (item.page !== currentPlayingPage) {
                currentPlayingPage = item.page;
                currentPage = item.page;

                const pageEl = document.getElementById(`page-wrapper-${currentPlayingPage}`);
                if (pageEl) {
                    document.querySelectorAll('.pdf-page-wrapper').forEach(el => el.classList.remove('active-page'));
                    pageEl.classList.add('active-page');
                    pageEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }

                updatePageCounter();
            }
            try {
                if (item.sentence) {
                    globalSubtitle.innerHTML = item.sentence.replace(/\n/g, '<br>');
                    globalSubtitle.classList.add('active');
                }

                const arrayBuffer = base64ToArrayBuffer(item.data);
                const int16Data = new Int16Array(arrayBuffer);
                const audioBuffer = audioCtx.createBuffer(1, int16Data.length, 24000);
                const channelData = audioBuffer.getChannelData(0);

                for (let i = 0; i < int16Data.length; i++) {
                    channelData[i] = int16Data[i] / 32768.0;
                }

                const source = audioCtx.createBufferSource();
                source.buffer = audioBuffer;
                if (audioCtx._masterGain) {
                    source.connect(audioCtx._masterGain);
                } else {
                    source.connect(audioCtx.destination);
                }

                const now = audioCtx.currentTime;
                if (nextPlayTime < now) nextPlayTime = now;

                await new Promise((resolve) => {
                    source.onended = () => resolve();
                    source.start(nextPlayTime);
                    nextPlayTime += audioBuffer.duration;
                });

            } catch (err) {
                console.error(`PCM 音频处理失败:`, err);
                await new Promise(resolve => setTimeout(resolve, 100));
            }
        }

        globalSubtitle.classList.remove('active');
        isProcessingQueue = false;
    }

    async function loadEntirePDF() {
        const fileId = getQueryParam('file_id');
        if (!fileId) return alert('File ID 未找到');

        try {
            const infoResp = await fetch(`/pdf/${fileId}`);
            if (!infoResp.ok) throw new Error(`后端接口报错，状态码: ${infoResp.status}`);

            const infoData = await infoResp.json();

            if (typeof infoData.pages === 'number') {
                totalPages = infoData.pages;
            } else if (Array.isArray(infoData.pages)) {
                totalPages = infoData.pages.length;
            } else {
                throw new Error("无法解析后端返回的 pages 字段");
            }

            if (totalPages === 0) throw new Error("PDF 文档为空 (0 页)");

            let skeletonHtml = '';
            for (let page = 1; page <= totalPages; page++) {
                skeletonHtml += `
                    <div class="pdf-page-wrapper" id="page-wrapper-${page}" style="min-height: 400px; display: flex; align-items: center; justify-content: center; background: #f8fafc;">
                        <div class="loading-spinner" id="spinner-${page}" style="color: #94a3b8; font-size: 14px; font-weight: 500;">
                            <svg style="animation: spin 1s linear infinite; width: 24px; height: 24px; margin: 0 auto 8px auto; display: block;" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                            </svg>
                            正在加载第 ${page} 页...
                        </div>
                        <img id="img-${page}" src="" alt="第 ${page} 页" style="display: none; width: 100%; height: auto;" />
                    </div>
                `;
            }

            pdfPreview.innerHTML = skeletonHtml;
            currentPage = 1;
            updatePageCounter();
            explainAllBtn.disabled = false;

            if (!document.getElementById('spin-style')) {
                const style = document.createElement('style');
                style.id = 'spin-style';
                style.innerHTML = `@keyframes spin { to { transform: rotate(360deg); } }`;
                document.head.appendChild(style);
            }

            document.getElementById('pdf-container').addEventListener('scroll', detectCurrentPage);

            const loadSinglePage = async (pageNum) => {
                try {
                    const pageResp = await fetch(`/pdf/${fileId}/page/${pageNum}`);
                    if (!pageResp.ok) throw new Error('网络请求异常');

                    const pageData = await pageResp.json();
                    const imgEl = document.getElementById(`img-${pageNum}`);
                    const spinnerEl = document.getElementById(`spinner-${pageNum}`);
                    const wrapperEl = document.getElementById(`page-wrapper-${pageNum}`);

                    if (imgEl && spinnerEl && pageData.image_url) {
                        const tempImg = new Image();
                        tempImg.src = pageData.image_url;
                        tempImg.onload = () => {
                            imgEl.src = pageData.image_url;
                            imgEl.style.display = 'block';
                            spinnerEl.style.display = 'none';
                            wrapperEl.style.minHeight = 'auto';
                        };
                    } else {
                        throw new Error("缺少图片数据");
                    }
                } catch (err) {
                    const spinnerEl = document.getElementById(`spinner-${pageNum}`);
                    if (spinnerEl) spinnerEl.innerHTML = `<span style="color:#ef4444;">第 ${pageNum} 页加载失败</span>`;
                }
            };

            await loadSinglePage(1);

            for (let page = 2; page <= totalPages; page++) {
                loadSinglePage(page);
            }

            // 初始化滑块最大值
            pageSlider.max = totalPages;
            pageSlider.value = 1;

        } catch (error) {
            pdfPreview.innerHTML = `<div style="color: #ef4444; margin-top: 100px;">加载失败: ${error.message}</div>`;
        }
    }

    if (getQueryParam('file_id')) {
        loadEntirePDF();
    }

    const playPauseBtn = document.getElementById('play-pause-btn');
    const pageSlider = document.getElementById('page-slider');
    const volumeSlider = document.getElementById('volume-slider');

    playPauseBtn.addEventListener('click', async () => {
        if (!audioCtx) {
            initAudioContext();
        }
        if (audioCtx.state === 'suspended') {
            await audioCtx.resume();
            playPauseBtn.textContent = '暂停';
        } else {
            await audioCtx.suspend();
            playPauseBtn.textContent = '播放';
        }
    });

    pageSlider.addEventListener('change', (e) => {
        const p = parseInt(e.target.value, 10);
        if (!isNaN(p)) jumpToPage(p);
    });

    volumeSlider.addEventListener('input', (e) => {
        const v = parseFloat(e.target.value);
        if (!audioCtx) return;
        if (!audioCtx._masterGain) {
            const gain = audioCtx.createGain();
            gain.gain.value = v;
            gain.connect(audioCtx.destination);
            audioCtx._masterGain = gain;
        } else {
            audioCtx._masterGain.gain.value = v;
        }
    });

    let seekAbortController = null;

    async function jumpToPage(pageNum) {
        if (pageNum < 1) pageNum = 1;
        if (pageNum > totalPages) pageNum = totalPages;

        if (pageNum === currentPlayingPage) return;

        currentPage = pageNum;
        currentPlayingPage = pageNum;
        const pageEl = document.getElementById(`page-wrapper-${currentPlayingPage}`);
        if (pageEl) {
            document.querySelectorAll('.pdf-page-wrapper').forEach(el => el.classList.remove('active-page'));
            pageEl.classList.add('active-page');
            pageEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
        updatePageCounter();

        if (seekAbortController) {
            seekAbortController.abort();
        }
        if (currentEventSource) {
            try { currentEventSource.close(); } catch (e) { }
            currentEventSource = null;
        }

        audioQueue = [];
        globalSubtitle.classList.remove('active');

        initAudioContext();
        if (audioCtx.state === 'suspended') {
            await audioCtx.resume();
        }
        nextPlayTime = audioCtx.currentTime + 0.1;

        const fileId = getQueryParam('file_id');
        if (!fileId) return;

        seekAbortController = new AbortController();

        try {
            const resp = await fetch(
                `/explain/playback/seek/${fileId}/page/${pageNum}`,
                { signal: seekAbortController.signal }
            );
            if (!resp.ok) {
                console.error('seek 请求失败:', resp.status);
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
                            queueAudioChunk(payload.data, payload.page || pageNum, payload.sentence);
                        } else if (payload.type === 'error') {
                            console.error('seek error:', payload.message);
                        }
                    } catch (e) {
                        console.error('解析 seek 流数据出错', e, line);
                    }
                }
            }
        } catch (e) {
            if (e.name === 'AbortError') {
                return;
            }
            console.error('seek 请求异常:', e);
        } finally {
            seekAbortController = null;
        }
    }

    document.addEventListener('keydown', (e) => {
        if (!document.fullscreenElement) return;
        if (e.key === 'ArrowRight') {
            jumpToPage(Math.min(totalPages, currentPage + 1));
        } else if (e.key === 'ArrowLeft') {
            jumpToPage(Math.max(1, currentPage - 1));
        }
    });

    // SSE handling and event wiring
    explainAllBtn.addEventListener('click', async () => {
        const fileId = getQueryParam('file_id');
        const courseName = courseNameInput.value.trim();

        if (!fileId || !courseName) return alert('请检查信息完整');

        initAudioContext();

        const originalText = explainAllBtn.textContent;
        explainAllBtn.textContent = '🔊 沉浸讲解中...';
        explainAllBtn.disabled = true;

        const progressContainer = document.createElement('div');
        progressContainer.style.cssText = `
            position: fixed; top: 20px; right: 80px; background: rgba(255,255,255,0.9); backdrop-filter: blur(8px);
            border-radius: 12px; padding: 20px; box-shadow: 0 10px 25px rgba(0,0,0,0.1);
            z-index: 1000; min-width: 250px; border: 1px solid #e2e8f0;
        `;
        progressContainer.innerHTML = `
            <div id="progress-info" style="font-size: 14px; font-weight: 600; color: #4f46e5; margin-bottom: 8px;">连接中...</div>
            <button id="cancel-stream" style="width: 100%; padding: 8px 16px; background: #ef4444; color: white; border: none; border-radius: 6px; font-size: 13px; cursor: pointer;">终止讲解</button>
        `;
        document.body.appendChild(progressContainer);

        if (currentEventSource) {
            try { currentEventSource.close(); } catch (e) { }
            currentEventSource = null;
        }
        let isCancelled = false;

        document.getElementById('cancel-stream').addEventListener('click', async () => {
            isCancelled = true;

            try {
                await fetch(`/explain/cancel/${fileId}`, { method: 'DELETE' });
            } catch (e) {
                console.error('取消请求失败:', e);
            }

            if (eventSource) eventSource.close();
            if (audioCtx) audioCtx.suspend();
            progressContainer.remove();
            globalSubtitle.classList.remove('active');
            explainAllBtn.textContent = originalText;
            explainAllBtn.disabled = false;
        });

        try {
            const streamUrl = `/explain/all-stream-v3/${fileId}?course_name=${encodeURIComponent(courseName)}`;
            currentEventSource = new EventSource(streamUrl);

            const eventSource = currentEventSource;

            eventSource.onmessage = function (event) {
                if (isCancelled) return;

                if (event.data === '[DONE]') {
                    if (currentEventSource) { currentEventSource.close(); currentEventSource = null; }
                    progressContainer.remove();
                    explainAllBtn.textContent = originalText;
                    explainAllBtn.disabled = false;
                    return;
                }

                try {
                    const payload = JSON.parse(event.data);

                    switch (payload.type) {
                        case 'page_start':
                            document.getElementById('progress-info').textContent = `AI 正在构思第 ${payload.page} 页...`;
                            break;

                        case 'audio':
                            if (payload.data) {
                                document.getElementById('progress-info').textContent = `正在生成第 ${payload.page} 页语音...`;
                                queueAudioChunk(payload.data, payload.page, payload.sentence);
                            }
                            break;

                        case 'error':
                            document.getElementById('progress-info').textContent = `发生错误: ${payload.message}`;
                            document.getElementById('progress-info').style.color = '#ef4444';
                            break;

                        case 'cancelled':
                            if (currentEventSource) { currentEventSource.close(); currentEventSource = null; }
                            progressContainer.remove();
                            explainAllBtn.textContent = originalText;
                            explainAllBtn.disabled = false;
                            return;
                    }

                } catch (e) {
                    console.error('解析流数据异常:', e, event.data);
                }
            };

            eventSource.onerror = function () {
                if (!isCancelled) {
                    progressContainer.remove();
                    explainAllBtn.textContent = originalText;
                    explainAllBtn.disabled = false;
                }
                if (currentEventSource) { currentEventSource.close(); currentEventSource = null; }
            };

        } catch (error) {
            progressContainer.remove();
            explainAllBtn.textContent = originalText;
            explainAllBtn.disabled = false;
        }
    });

    // Ask button - 录音并提交到 /qa/ask/stream，然后解析流式响应（SSE 风格）并播放
    async function resumeExplanation(fileId, courseName, oldContainer) {
        oldContainer.remove();

        initAudioContext();
        await audioCtx.resume();

        const progressContainer = document.createElement('div');
        progressContainer.style.cssText = `
            position: fixed; top: 20px; right: 80px; background: rgba(255,255,255,0.9); backdrop-filter: blur(8px);
            border-radius: 12px; padding: 20px; box-shadow: 0 10px 25px rgba(0,0,0,0.1);
            z-index: 1000; min-width: 250px; border: 1px solid #e2e8f0;
        `;
        progressContainer.innerHTML = `
            <div id="progress-info" style="font-size: 14px; font-weight: 600; color: #4f46e5; margin-bottom: 8px;">正在恢复讲解...</div>
            <button id="cancel-stream" style="width: 100%; padding: 8px 16px; background: #ef4444; color: white; border: none; border-radius: 6px; font-size: 13px; cursor: pointer;">终止讲解</button>
        `;
        document.body.appendChild(progressContainer);

        let isCancelled = false;

        document.getElementById('cancel-stream').addEventListener('click', async () => {
            isCancelled = true;
            try { await fetch(`/explain/cancel/${fileId}`, { method: 'DELETE' }); } catch (e) { }
            if (currentEventSource) { currentEventSource.close(); currentEventSource = null; }
            if (audioCtx) audioCtx.suspend();
            progressContainer.remove();
            globalSubtitle.classList.remove('active');
        });

        const fromPage = Math.min(resumePage, totalPages);
        const streamUrl = `/explain/all-stream-v3/${fileId}?course_name=${encodeURIComponent(courseName)}&from_page=${fromPage}`;
        currentEventSource = new EventSource(streamUrl);

        const eventSource = currentEventSource;

        eventSource.onmessage = function (event) {
            if (isCancelled) return;

            if (event.data === '[DONE]') {
                if (currentEventSource) { currentEventSource.close(); currentEventSource = null; }
                progressContainer.remove();
                return;
            }

            try {
                const payload = JSON.parse(event.data);

                switch (payload.type) {
                    case 'page_start':
                        document.getElementById('progress-info').textContent = `AI 正在构思第 ${payload.page} 页...`;
                        break;

                    case 'audio':
                        if (payload.data) {
                            document.getElementById('progress-info').textContent = `正在生成第 ${payload.page} 页语音...`;
                            queueAudioChunk(payload.data, payload.page, payload.sentence);
                        }
                        break;

                    case 'error':
                        document.getElementById('progress-info').textContent = `发生错误: ${payload.message}`;
                        document.getElementById('progress-info').style.color = '#ef4444';
                        break;

                    case 'cancelled':
                        if (currentEventSource) { currentEventSource.close(); currentEventSource = null; }
                        progressContainer.remove();
                        return;
                }
            } catch (e) {
                console.error('解析流数据异常:', e, event.data);
            }
        };

        eventSource.onerror = function () {
            if (!isCancelled) {
                progressContainer.remove();
            }
            if (currentEventSource) { currentEventSource.close(); currentEventSource = null; }
        };
    }

    // Ask button - 录音并提交到 /qa/ask/stream，然后解析流式响应（SSE 风格）并播放
    const askBtn = document.getElementById('ask-btn');
    if (askBtn) {
        askBtn.addEventListener('click', async () => {
            const fileId = getQueryParam('file_id');
            const courseName = courseNameInput.value.trim();
            if (!fileId) return alert('缺少 file_id');

            resumePage = currentPlayingPage || currentPage;

            if (currentEventSource) { try { currentEventSource.close(); } catch (e) { } currentEventSource = null; }
            if (audioCtx) try { await audioCtx.suspend(); } catch (e) { }
            audioQueue = [];
            isProcessingQueue = false;

            initAudioContext();

            const originalText = askBtn.textContent;
            askBtn.textContent = '🎤 录音中...';
            askBtn.disabled = true;

            const progressContainer = document.createElement('div');
            progressContainer.style.cssText = `position: fixed; top: 20px; right: 80px; background: rgba(255,255,255,0.95); border-radius: 12px; padding: 16px; z-index: 1000; min-width: 260px; border:1px solid #e2e8f0`;
            progressContainer.innerHTML = `
                <div id="ask-info" style="font-size:14px; font-weight:600; color:#0f172a; margin-bottom:10px;">正在聆听...（说完请点击「提问结束」）</div>
                <div style="display:flex; gap:8px;">
                    <button id="ask-finish" style="flex:1; padding:8px 12px; background:#4f46e5; color:white; border:none; border-radius:6px; cursor:pointer; font-size:13px;">提问结束</button>
                    <button id="ask-cancel" style="flex:1; padding:8px 12px; background:#e2e8f0; color:#334155; border:none; border-radius:6px; cursor:pointer; font-size:13px;">取消</button>
                </div>
            `;
            document.body.appendChild(progressContainer);

            let mediaStream = null;
            let recorder = null;
            let chunks = [];
            let silenceTimer = null;
            let startedSpeaking = false;
            let isCancelledRecording = false;

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
                askBtn.textContent = originalText;
                askBtn.disabled = false;
            });

            try {
                mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
            } catch (e) {
                alert('无法访问麦克风，请检查权限');
                progressContainer.remove();
                askBtn.textContent = originalText;
                askBtn.disabled = false;
                return;
            }

            // 监测能量来自动停止录音
            const monitorCtx = new (window.AudioContext || window.webkitAudioContext)();
            const source = monitorCtx.createMediaStreamSource(mediaStream);
            const analyser = monitorCtx.createAnalyser();
            analyser.fftSize = 2048;
            source.connect(analyser);
            const dataArr = new Uint8Array(analyser.fftSize);

            recorder = new MediaRecorder(mediaStream);
            recorder.ondataavailable = (e) => { if (e.data && e.data.size > 0) chunks.push(e.data); };
            recorder.start(1000);

            const maxRecordMs = 10000; // 最长 10s
            const silenceThreshold = 0.02; // 能量阈值
            const silenceTimeout = 800; // 静默持续 800ms 视为结束

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
                } else {
                    if (startedSpeaking && !silenceTimer) {
                        silenceTimer = setTimeout(async () => {
                            await stopAll();
                        }, silenceTimeout);
                    }
                }
                if (Date.now() - startTime > maxRecordMs) {
                    stopAll();
                }
                if (recorder && recorder.state !== 'inactive') requestAnimationFrame(checkSilence);
            };
            requestAnimationFrame(checkSilence);

            recorder.onstop = async () => {
                try { monitorCtx.close(); } catch (e) { }
                if (isCancelledRecording) return;
                const blob = new Blob(chunks, { type: 'audio/webm' });
                // 将录音转为 16k WAV
                const wavBlob = await convertBlobTo16kWav(blob);

                // 准备上传并打开流式响应
                const form = new FormData();
                form.append('file', wavBlob, 'question.wav');
                form.append('file_id', fileId);
                form.append('page_num', String(currentPage || pageSlider.value || 1));

                // AbortController 用于取消请求
                const ac = new AbortController();
                currentStreamAbort = ac;

                // 开始 fetch 并读取流
                try {
                    const resp = await fetch('/qa/ask/stream', { method: 'POST', body: form, signal: ac.signal });
                    if (!resp.ok) {
                        throw new Error('后端返回错误: ' + resp.status);
                    }

                    // 读取流并解析 SSE 风格的 data: ...\n\n
                    const reader = resp.body.getReader();
                    const decoder = new TextDecoder('utf-8');
                    let buf = '';

                    initAudioContext();
                    if (audioCtx.state === 'suspended') await audioCtx.resume();

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
                                    resumeExplanation(fileId, courseName, progressContainer);
                                });

                                document.getElementById('qa-done-close').addEventListener('click', () => {
                                    progressContainer.remove();
                                });

                                askBtn.textContent = originalText;
                                askBtn.disabled = false;
                                break;
                            }
                            try {
                                const payload = JSON.parse(line);
                                if (payload.type === 'audio' && payload.data) {
                                    queueAudioChunk(payload.data, payload.page || currentPage, payload.sentence);
                                } else if (payload.type === 'start') {
                                    // ignore or show status
                                } else if (payload.type === 'error') {
                                    document.getElementById('ask-info').textContent = '错误: ' + (payload.message || payload.data || '未知错误');
                                }
                            } catch (e) {
                                console.error('解析流数据出错', e, line);
                            }
                        }
                    }

                } catch (e) {
                    if (e.name === 'AbortError') {
                        return;
                    }
                    console.error('流式请求出错', e);
                    progressContainer.remove();
                    askBtn.textContent = originalText;
                    askBtn.disabled = false;
                }
            };

            // convert helper functions
            async function convertBlobTo16kWav(blob) {
                const ab = await blob.arrayBuffer();
                const decodeCtx = new (window.AudioContext || window.webkitAudioContext)();
                const audioBuffer = await decodeCtx.decodeAudioData(ab);
                // resample via OfflineAudioContext
                const targetRate = 16000;
                const offlineCtx = new OfflineAudioContext(1, Math.ceil(audioBuffer.duration * targetRate), targetRate);
                const src = offlineCtx.createBufferSource();
                // create mono buffer
                const mono = offlineCtx.createBuffer(1, audioBuffer.length, audioBuffer.sampleRate);
                const channelData = audioBuffer.numberOfChannels > 1 ? audioBuffer.getChannelData(0) : audioBuffer.getChannelData(0);
                mono.copyToChannel(channelData, 0);
                src.buffer = mono;
                src.connect(offlineCtx.destination);
                src.start(0);
                const rendered = await offlineCtx.startRendering();
                const renderedData = rendered.getChannelData(0);
                const wavBuffer = encodeWAV(renderedData, targetRate);
                return new Blob([wavBuffer], { type: 'audio/wav' });
            }

            function encodeWAV(samples, sampleRate) {
                const buffer = new ArrayBuffer(44 + samples.length * 2);
                const view = new DataView(buffer);

                /* RIFF identifier */ writeString(view, 0, 'RIFF');
                /* file length */ view.setUint32(4, 36 + samples.length * 2, true);
                /* RIFF type */ writeString(view, 8, 'WAVE');
                /* format chunk identifier */ writeString(view, 12, 'fmt ');
                /* format chunk length */ view.setUint32(16, 16, true);
                /* sample format (raw) */ view.setUint16(20, 1, true);
                /* channel count */ view.setUint16(22, 1, true);
                /* sample rate */ view.setUint32(24, sampleRate, true);
                /* byte rate (sampleRate * blockAlign) */ view.setUint32(28, sampleRate * 2, true);
                /* block align (channel count * bytes per sample) */ view.setUint16(32, 2, true);
                /* bits per sample */ view.setUint16(34, 16, true);
                /* data chunk identifier */ writeString(view, 36, 'data');
                /* data chunk length */ view.setUint32(40, samples.length * 2, true);

                // Write the PCM samples
                let offset = 44;
                for (let i = 0; i < samples.length; i++, offset += 2) {
                    let s = Math.max(-1, Math.min(1, samples[i]));
                    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
                }

                return view;
            }

            function writeString(view, offset, string) {
                for (let i = 0; i < string.length; i++) {
                    view.setUint8(offset + i, string.charCodeAt(i));
                }
            }

        });
    }

});
