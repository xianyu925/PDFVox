// 共享状态 — 所有模块通过 state 对象共享可变数据

export const state = {
    totalPages: 0,
    currentPage: 1,

    // audio
    audioCtx: null,
    nextPlayTime: 0,
    audioQueue: [],
    isProcessingQueue: false,
    currentPlayingPage: 0,
    resumePage: 1,

    // stream
    currentEventSource: null,
    currentStreamAbort: null,
    isQaActive: false,

    // DVR Time Window
    playedTime: 0,
    liveWindowEnd: 0,
    pageTimeMap: [],
    sentenceStartTimes: [],      // [{ page, start, duration }] 逐句累积，start 为全局时间
    playbackStartTime: 0,
    progressInterval: null,
    seekAbortController: null,
    isSeeking: false,
    isDragging: false,
    isLoading: false,               // 队列空转时自动挂起，等待新 chunk
    isAutoScrolling: false,         // 程序化翻页滚动中，抑制 detectCurrentPage
    currentWordTimestamps: [],     // 当前句子的字级时间戳
    currentSentenceStartTime: 0,   // 当前句子在全局时间轴的起始秒数
    courseName: '',                 // 课程名称，供 seek 后恢复 SSE 流使用
};

// DOM 引用 — 由 viewer.js 在 DOMContentLoaded 后设置
export const dom = {};

export function getQueryParam(name) {
    const params = new URLSearchParams(window.location.search);
    return params.get(name) || "";
}
