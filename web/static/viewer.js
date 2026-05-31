import { state, dom, getQueryParam } from './viewer-state.js';
import { setupPlayerControls, updateProgressUI, stopProgressSync, switchToPage, updatePageCounter } from './viewer-audio.js';
import { setupExplainAllButton, setupAskButton } from './viewer-stream.js';

// ---- DOM 引用初始化 ----

const pdfPreview = document.getElementById('pdf-preview');
const rightPanel = document.getElementById('right-panel');
const fullscreenBtn = document.getElementById('fullscreen-btn');

dom.courseNameInput = document.getElementById('course-name');
dom.explainAllBtn = document.getElementById('explain-all-btn');
dom.explainStatus = document.getElementById('explain-status');
dom.askBtn = document.getElementById('ask-btn');
dom.globalSubtitle = document.getElementById('global-subtitle');
dom.progressSlider = document.getElementById('progress-slider');
dom.playPauseBtn = document.getElementById('play-pause-btn');
dom.playIcon = document.getElementById('play-icon');
dom.pauseIcon = document.getElementById('pause-icon');
dom.timeCurrent = document.getElementById('time-current');
dom.timeTotal = document.getElementById('time-total');
dom.loadingSpinner = document.getElementById('loading-spinner');

// ---- 左侧面板宽度调节 ----

(function setupResizePanel() {
    const leftPanel = document.getElementById('left-panel');
    const handle = document.getElementById('resize-handle');
    if (!leftPanel || !handle) return;

    const MIN_WIDTH = 220;
    const MAX_WIDTH_RATIO = 0.5;
    const LS_KEY = 'pdfvox_left_panel_width';

    // 恢复上次保存的宽度
    const saved = localStorage.getItem(LS_KEY);
    if (saved) {
        const w = parseInt(saved, 10);
        if (w >= MIN_WIDTH) leftPanel.style.width = w + 'px';
    }

    let isResizing = false;

    handle.addEventListener('mousedown', (e) => {
        isResizing = true;
        handle.classList.add('active');
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
        e.preventDefault();
    });

    document.addEventListener('mousemove', (e) => {
        if (!isResizing) return;
        const maxW = window.innerWidth * MAX_WIDTH_RATIO;
        let newW = e.clientX - leftPanel.getBoundingClientRect().left;
        newW = Math.max(MIN_WIDTH, Math.min(maxW, newW));
        leftPanel.style.width = newW + 'px';
    });

    document.addEventListener('mouseup', () => {
        if (!isResizing) return;
        isResizing = false;
        handle.classList.remove('active');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        localStorage.setItem(LS_KEY, leftPanel.style.width);
    });
})();

// ---- 滚动检测当前页（仅手动滚动，自动翻页时跳过） ----

function detectCurrentPage() {
    // 全屏模式或程序化滚动中，不检测
    if (document.fullscreenElement || state.isAutoScrolling) return;
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
            if (state.currentPage !== i + 1) {
                state.currentPage = i + 1;
                // 手动滚动时也同步 active-page 高亮
                document.querySelectorAll('.pdf-page-wrapper').forEach(el => el.classList.remove('active-page'));
                page.classList.add('active-page');
                const counter = document.getElementById('page-counter');
                if (counter) counter.textContent = `${state.currentPage} / ${state.totalPages}`;
            }
            break;
        }
    }
}

// ---- 全屏 ----

fullscreenBtn.addEventListener('click', () => {
    if (!document.fullscreenElement) {
        rightPanel.requestFullscreen().catch(err => console.error(err));
    } else {
        document.exitFullscreen();
    }
});

document.addEventListener('fullscreenchange', () => {
    if (document.fullscreenElement) {
        fullscreenBtn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 3v3a2 2 0 0 1-2 2H3m18 0h-3a2 2 0 0 1-2-2V3m0 18v-3a2 2 0 0 1 2-2h3M3 16v3a2 2 0 0 0 2 2h3"></path></svg> 退出全屏';
        document.getElementById('left-panel').style.display = 'none';
        // 切换到全屏单页视图
        switchToPage(state.currentPage);
    } else {
        fullscreenBtn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"></path></svg> 沉浸模式';
        document.getElementById('left-panel').style.display = 'flex';
        // 恢复所有页显示
        document.querySelectorAll('.pdf-page-wrapper').forEach(el => { el.style.display = 'flex'; });
        // 高亮当前页
        const curEl = document.getElementById(`page-wrapper-${state.currentPage}`);
        if (curEl) curEl.classList.add('active-page');
    }
});

// ---- PDF 加载 ----

async function loadEntirePDF() {
    const fileId = getQueryParam('file_id');
    if (!fileId) return alert('File ID 未找到');

    try {
        const infoResp = await fetch(`/pdf/${fileId}`);
        if (!infoResp.ok) throw new Error(`后端接口报错，状态码: ${infoResp.status}`);
        const infoData = await infoResp.json();

        if (typeof infoData.pages === 'number') {
            state.totalPages = infoData.pages;
        } else if (Array.isArray(infoData.pages)) {
            state.totalPages = infoData.pages.length;
        } else {
            throw new Error("无法解析后端返回的 pages 字段");
        }
        if (state.totalPages === 0) throw new Error("PDF 文档为空 (0 页)");

        let skeletonHtml = '';
        for (let page = 1; page <= state.totalPages; page++) {
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
        state.currentPage = 1;
        updatePageCounter();
        dom.explainAllBtn.disabled = false;

        if (!document.getElementById('spin-style')) {
            const style = document.createElement('style');
            style.id = 'spin-style';
            style.innerHTML = '@keyframes spin { to { transform: rotate(360deg); } }';
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
        for (let page = 2; page <= state.totalPages; page++) {
            loadSinglePage(page);
        }

        dom.progressSlider.max = 100;
        dom.progressSlider.value = 0;
        dom.timeTotal.textContent = '--:--';

    } catch (error) {
        pdfPreview.innerHTML = `<div style="color: #ef4444; margin-top: 100px;">加载失败: ${error.message}</div>`;
    }
}

// ---- 启动 ----

setupPlayerControls();
setupExplainAllButton();
setupAskButton();

if (getQueryParam('file_id')) {
    loadEntirePDF();
}
