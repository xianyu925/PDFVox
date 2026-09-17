import { state } from './viewer-state.js';

export function formatTime(seconds) {
    if (!isFinite(seconds) || seconds < 0) return '00:00';
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = Math.floor(seconds % 60);
    return `${String(minutes).padStart(2, '0')}:${String(remainingSeconds).padStart(2, '0')}`;
}

export function pcmDuration(base64Data, reportedDuration) {
    const reported = Number(reportedDuration);
    if (typeof base64Data === 'string' && base64Data.length > 0) {
        const padding = base64Data.endsWith('==') ? 2
            : base64Data.endsWith('=') ? 1 : 0;
        const byteLength = Math.max(0, base64Data.length * 3 / 4 - padding);
        const duration = byteLength / 2 / 24000;
        if (Number.isFinite(duration) && duration > 0) return duration;
    }
    return Number.isFinite(reported) && reported > 0 ? reported : 0;
}

export function getPageAudioStart(pageNum) {
    const targetPage = Number(pageNum);
    if (!Number.isInteger(targetPage) || targetPage < 1) return null;
    const firstChunk = state.generatedAudioChunks.find(
        chunk => Number(chunk.page) === targetPage,
    );
    return firstChunk ? firstChunk.start : null;
}
