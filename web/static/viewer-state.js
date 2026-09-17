// 共享状态 — 所有模块通过 state 对象共享可变数据

export const state = {
    totalPages: 0,
    currentPage: 1,

    // audio
    audioCtx: null,
    nextPlayTime: 0,
    audioQueue: [],
    generatedAudioChunks: [],       // 浏览器已收到的讲解音频；拖动仅重放这里的内容
    generatedAudioChunkKeys: new Set(),
    isProcessingQueue: false,
    currentPlayingPage: 0,
    resumePage: 1,
    currentAudioSource: null,
    currentAudioResolve: null,
    currentAudioEndTime: null,
    currentAudioIsQa: false,
    playbackEpoch: 0,
    playbackRate: 1,

    // stream
    currentEventSource: null,
    currentStreamAbort: null,
    isQaActive: false,
    sessionId: sessionStorage.getItem('pdfvox_session_id') ||
        (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`),

    // DVR Time Window
    playedTime: 0,
    liveWindowEnd: 0,              // 浏览器当前已收到的讲解音频总时长
    timelineCursor: 0,             // 新生成音频的时间轴写入位置
    pageTimeMap: [],
    playbackStartTime: 0,
    progressInterval: null,
    isSeeking: false,
    isDragging: false,
    isLoading: false,               // 队列空转时自动挂起，等待新 chunk
    isAutoScrolling: false,         // 程序化翻页滚动中，抑制 detectCurrentPage
    currentWordTimestamps: [],     // 当前句子的字级时间戳
    currentSentenceStartTime: null, // 当前句子在全局时间轴的起始秒数
    courseName: '',                 // 当前讲解使用的课程名称
};

sessionStorage.setItem('pdfvox_session_id', state.sessionId);

// DOM 引用 — 由 viewer.js 在 DOMContentLoaded 后设置
export const dom = {};

export function getQueryParam(name) {
    const params = new URLSearchParams(window.location.search);
    return params.get(name) || "";
}
