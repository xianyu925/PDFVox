import base64
import unittest

from app.routers.ai_explain import _trim_pcm_sentence


class PlaybackSeekTests(unittest.TestCase):
    def test_trims_pcm_at_exact_offset_and_rebases_word_timestamps(self):
        pcm = bytes(24_000 * 2 * 2)  # two seconds of mono 24 kHz int16 PCM
        item = {
            "audio": base64.b64encode(pcm).decode("ascii"),
            "duration": 2.0,
            "sentence": "abc",
            "word_timestamps": [
                {"char": "a", "start": 0.0, "end": 0.4},
                {"char": "b", "start": 0.4, "end": 0.8},
                {"char": "c", "start": 1.0, "end": 1.4},
            ],
        }

        trimmed = _trim_pcm_sentence(item, 0.5)

        self.assertEqual(1.5, trimmed["duration"])
        self.assertEqual(72_000, len(base64.b64decode(trimmed["audio"])))
        self.assertEqual(
            [
                {"char": "b", "start": 0.0, "end": 0.3},
                {"char": "c", "start": 0.5, "end": 0.9},
            ],
            trimmed["word_timestamps"],
        )

    def test_offset_at_end_returns_no_playable_audio(self):
        pcm = bytes(24_000 * 2)
        item = {
            "audio": base64.b64encode(pcm).decode("ascii"),
            "duration": 1.0,
            "sentence": "a",
            "word_timestamps": [],
        }

        trimmed = _trim_pcm_sentence(item, 1.0)

        self.assertEqual("", trimmed["audio"])
        self.assertEqual(0.0, trimmed["duration"])


if __name__ == "__main__":
    unittest.main()
