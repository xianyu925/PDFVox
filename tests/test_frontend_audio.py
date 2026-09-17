import shutil
import subprocess
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "Node.js is required for frontend module tests")
class FrontendAudioTimelineTests(unittest.TestCase):
    def test_cached_replay_does_not_extend_generated_duration(self):
        script = """
globalThis.sessionStorage = { getItem: () => null, setItem: () => {} };
const { state, dom } = await import('./web/static/viewer-state.js');
const {
    queueAudioChunk,
    seekToTime,
    stopCurrentAudio,
    stopProgressSync,
} = await import('./web/static/viewer-audio.js');
const {
    buildSubtitleSegments,
    expandWordTimestamps,
} = await import('./web/static/viewer-subtitles.js');
const { getPageAudioStart } = await import('./web/static/viewer-timeline.js');

dom.progressSlider = { max: 0, value: 0, style: {} };
dom.timeTotal = { textContent: '' };
state.audioCtx = {};
state.isProcessingQueue = true;

const oneSecondPcm = Buffer.alloc(48000).toString('base64');
await queueAudioChunk(oneSecondPcm, 1, 'first', '99', [], { chunkIndex: 1 });
await queueAudioChunk(oneSecondPcm, 1, 'second', '99', [], { chunkIndex: 2 });
await queueAudioChunk(oneSecondPcm, 1, 'duplicate', '99', [], { chunkIndex: 2 });
await queueAudioChunk(oneSecondPcm, 1, 'replay', 1, [], {
    trackTimeline: false,
    playbackOffset: 0.5,
});

if (state.liveWindowEnd !== 2 || state.timelineCursor !== 2) {
    throw new Error('cached replay changed the generated duration');
}
if (dom.timeTotal.textContent !== '00:02') {
    throw new Error('the displayed total no longer matches generated audio');
}
if (state.generatedAudioChunks.length !== 2) {
    throw new Error('cached replay was recorded as newly generated audio');
}
if (getPageAudioStart(1) !== 0 || getPageAudioStart(2) !== null) {
    throw new Error('page audio start lookup returned the wrong result');
}
const expandedTimestamps = expandWordTimestamps(
    [
        { char: '你', start: 0, end: 0.2 },
        { char: '好', start: 0.2, end: 0.4 },
        { char: '世界', start: 0.5, end: 0.9 },
    ],
);
const subtitleSegments = buildSubtitleSegments(
    '你好，世界。',
    expandedTimestamps,
);
if (subtitleSegments.map(segment => segment.text).join('') !== '你好，世界。') {
    throw new Error('timed subtitle rendering dropped part of the sentence');
}
if (expandedTimestamps.length !== 4 || expandedTimestamps[2].end !== 0.7) {
    throw new Error('word timestamps were not expanded to character highlights');
}
const seekSource = seekToTime.toString();
if (seekSource.includes('fetch(') || seekSource.includes('currentEventSource.close')) {
    throw new Error('seeking still performs network generation work');
}

// Reproduce seeking while the previous playback processor is still unwinding.
// The obsolete processor must not clear the replacement processor's state.
globalThis.document = { getElementById: () => null };
globalThis.window = {
    atob: value => Buffer.from(value, 'base64').toString('binary'),
};
const classList = { add: () => {}, remove: () => {} };
dom.globalSubtitle = {
    classList,
    innerHTML: '',
    textContent: '',
    querySelectorAll: () => [],
    replaceChildren: () => {},
};
dom.timeCurrent = { textContent: '' };
dom.loadingSpinner = { style: {} };

const sources = [];
state.audioCtx = {
    state: 'running',
    currentTime: 0,
    destination: {},
    createBuffer: (_channels, length, sampleRate) => ({
        duration: length / sampleRate,
        getChannelData: () => new Float32Array(length),
    }),
    createBufferSource: () => {
        const source = {
            playbackRate: { value: 1, setValueAtTime: () => {} },
            connect: () => {},
            disconnect: () => {},
            start: () => {},
            stop: () => {},
            onended: null,
        };
        sources.push(source);
        return source;
    },
    resume: async () => {},
    suspend: async () => {},
};
state.audioQueue = [];
state.generatedAudioChunks = [];
state.isProcessingQueue = false;
state.currentPlayingPage = 1;
state.playedTime = 0;
state.liveWindowEnd = 0;
state.timelineCursor = 0;
state.playbackEpoch = 0;

await queueAudioChunk(oneSecondPcm, 1, '', 1, []);
await seekToTime(0.5);
await Promise.resolve();
if (!state.isProcessingQueue || !state.currentAudioSource || sources.length < 2) {
    throw new Error('the old playback processor disrupted seek playback');
}
stopCurrentAudio();
stopProgressSync();
"""
        subprocess.run(
            [
                NODE,
                "--experimental-default-type=module",
                "--input-type=module",
                "-e",
                script,
            ],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )


if __name__ == "__main__":
    unittest.main()
