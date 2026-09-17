import { state, dom } from './viewer-state.js';

export function highlightActiveWord(elapsed) {
    const timestamps = state.currentWordTimestamps;
    if (!timestamps.length || state.currentSentenceStartTime === null) return;
    const offset = Math.max(0, elapsed - state.currentSentenceStartTime);
    let activeIndex = -1;
    for (let index = 0; index < timestamps.length; index++) {
        if (offset >= timestamps[index].start && offset < timestamps[index].end) {
            activeIndex = index;
            break;
        }
    }
    if (
        activeIndex === -1 &&
        offset >= (timestamps[timestamps.length - 1]?.end || Infinity)
    ) {
        activeIndex = timestamps.length;
    }
    const characters = dom.globalSubtitle.querySelectorAll('.sc');
    for (const character of characters) {
        character.style.color = Number(character.dataset.idx) === activeIndex
            ? '#fbbf24'
            : '';
    }
}

export function buildSubtitleSegments(sentence, wordTimestamps) {
    const text = String(sentence || '');
    const segments = [];
    let cursor = 0;

    (wordTimestamps || []).forEach((word, timestampIndex) => {
        const token = String(word.char || '');
        if (!token) return;
        const position = text.indexOf(token, cursor);
        if (position < 0) return;
        if (position > cursor) {
            segments.push({ text: text.slice(cursor, position), timestampIndex: null });
        }
        segments.push({ text: token, timestampIndex });
        cursor = position + token.length;
    });

    if (cursor < text.length) {
        segments.push({ text: text.slice(cursor), timestampIndex: null });
    }
    if (segments.length === 0 && text) {
        segments.push({ text, timestampIndex: null });
    }
    return segments;
}

export function expandWordTimestamps(wordTimestamps) {
    const expanded = [];
    for (const word of wordTimestamps || []) {
        const characters = Array.from(String(word.char || ''));
        const start = Number(word.start);
        const end = Number(word.end);
        if (!characters.length || !Number.isFinite(start) || !Number.isFinite(end)) {
            continue;
        }
        const step = Math.max(0, end - start) / characters.length;
        characters.forEach((char, index) => {
            expanded.push({
                ...word,
                char,
                start: start + step * index,
                end: index === characters.length - 1
                    ? end
                    : start + step * (index + 1),
            });
        });
    }
    return expanded;
}

export function renderSentenceSubtitle(sentence, wordTimestamps) {
    const fragment = document.createDocumentFragment();
    for (const segment of buildSubtitleSegments(sentence, wordTimestamps)) {
        if (segment.timestampIndex === null) {
            fragment.appendChild(document.createTextNode(segment.text));
            continue;
        }
        const span = document.createElement('span');
        span.className = 'sc';
        span.dataset.idx = String(segment.timestampIndex);
        span.style.transition = 'color 0.1s';
        span.textContent = segment.text;
        fragment.appendChild(span);
    }
    dom.globalSubtitle.replaceChildren(fragment);
}
