import { state } from './viewer-state.js';

export function switchToPage(
    pageNum,
    { updatePlayingPage = false, scrollDelay = 600 } = {},
) {
    if (updatePlayingPage) {
        state.currentPlayingPage = pageNum;
        if (
            state.pageTimeMap.length > 0 &&
            !state.pageTimeMap[state.pageTimeMap.length - 1].endTime
        ) {
            state.pageTimeMap[state.pageTimeMap.length - 1].endTime = state.playedTime;
        }
        if (
            state.pageTimeMap.length === 0 ||
            state.pageTimeMap[state.pageTimeMap.length - 1].page !== pageNum
        ) {
            state.pageTimeMap.push({ page: pageNum, startTime: state.playedTime });
        }
    }
    state.currentPage = pageNum;
    updatePageCounter();

    const pageElement = document.getElementById(`page-wrapper-${pageNum}`);
    if (!pageElement) return;

    if (document.fullscreenElement) {
        document.querySelectorAll('.pdf-page-wrapper').forEach(element => {
            element.style.display = 'none';
            element.classList.remove('active-page');
        });
        pageElement.style.display = 'block';
        pageElement.classList.add('active-page');
    } else {
        document.querySelectorAll('.pdf-page-wrapper').forEach(
            element => element.classList.remove('active-page'),
        );
        pageElement.classList.add('active-page');
        state.isAutoScrolling = true;
        pageElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
        if (state._scrollTimer) clearTimeout(state._scrollTimer);
        state._scrollTimer = setTimeout(() => {
            state.isAutoScrolling = false;
            state._scrollTimer = null;
        }, scrollDelay);
    }
}

export function updatePageCounter() {
    const counter = document.getElementById('page-counter');
    if (counter) {
        counter.textContent = `${state.currentPage} / ${state.totalPages}`;
    }
}
