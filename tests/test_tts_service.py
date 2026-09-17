import unittest

from app.services.tts_service import TTSService


class TTSTimestampTests(unittest.TestCase):
    def test_parses_speech_2_subtitle_words(self):
        payload = {
            "text": "你好",
            "words": [
                {
                    "word": "你",
                    "startTime": 0.1954,
                    "endTime": 0.3254,
                    "confidence": 0.9,
                },
                {
                    "word": "好",
                    "startTime": 0.3254,
                    "endTime": 0.7054,
                    "confidence": 0.9,
                },
            ],
        }

        self.assertEqual(
            [
                {"char": "你", "start": 0.195, "end": 0.325},
                {"char": "好", "start": 0.325, "end": 0.705},
            ],
            TTSService._parse_word_timestamps(payload),
        )

    def test_keeps_legacy_word_boundary_compatibility(self):
        payload = {
            "word_boundary": [
                {"word": "A", "start_time": 0.1, "end_time": 0.2}
            ]
        }

        self.assertEqual(
            [{"char": "A", "start": 0.1, "end": 0.2}],
            TTSService._parse_word_timestamps(payload),
        )


class FakeWebSocket:
    async def send(self, data):
        return None

    async def close(self):
        return None


class TTSErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_sentence_failure_is_forwarded_as_an_error_event(self):
        service = TTSService.__new__(TTSService)

        async def connect():
            return FakeWebSocket()

        async def fail(*args, **kwargs):
            raise RuntimeError("upstream failed")

        service._connect = connect
        service._synthesize_sentence = fail
        service.voice_type = "voice"

        async def text_stream():
            yield {"type": "text", "data": "测试。"}
            yield {"type": "end"}

        events = [event async for event in service.stream_tts_input(text_stream())]

        self.assertEqual(1, len(events))
        self.assertEqual("error", events[0]["type"])
        self.assertIn("upstream failed", events[0]["message"])


if __name__ == "__main__":
    unittest.main()
