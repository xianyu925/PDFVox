import importlib
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

# This is an orchestration unit test. Isolate the class under test from optional
# PDF, model-client, and WebSocket stacks that are replaced by fakes below.
dependencies = {}
for module_name, class_name in (
    ("app.services.pdf_service", "PDFService"),
    ("app.services.llm_service", "LLMService"),
    ("app.services.tts_service", "TTSService"),
):
    dependency = types.ModuleType(module_name)
    setattr(dependency, class_name, type(class_name, (), {}))
    dependencies[module_name] = dependency

with patch.dict(sys.modules, dependencies):
    explain_module = importlib.import_module("app.services.explain_service")
    ExplainService = explain_module.ExplainService

# Do not leave the dependency-isolated module in the global import cache.
sys.modules.pop("app.services.explain_service", None)


class FakePDFService:
    def get_page_image(self, pdf_path, page_num):
        return "encoded-page"


class FakeLLMService:
    async def stream_explanation(self, *args, **kwargs):
        yield {
            "type": "error",
            "data": {"error": "upstream unavailable", "stage": "llm"},
        }


class FakeTTSService:
    async def stream_tts_input(self, text_stream, page_num=1):
        async for item in text_stream:
            if item.get("type") == "end":
                break
        if False:
            yield None


class ExplainStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_llm_error_is_forwarded_to_the_client_stream(self):
        service = ExplainService.__new__(ExplainService)
        service.pdf_service = FakePDFService()
        service.llm_service = FakeLLMService()
        service.tts_service = FakeTTSService()
        service.summary_cache = {"document-1": {}}
        service.page_audio_cache = {}
        service._cancel_tokens = {}

        upload = {
            "file_id": "document-1",
            "path": "document.pdf",
            "total_pages": 1,
        }
        with patch.object(explain_module, "get_upload", return_value=upload):
            events = [
                event
                async for event in service.explain_page_realtime_stream(
                    "document-1", 1, total_pages=1
                )
            ]

        errors = [event for event in events if event.get("type") == "error"]
        self.assertEqual(1, len(errors))
        self.assertEqual("upstream unavailable", errors[0]["message"])

    async def test_tts_error_is_not_cached_as_an_empty_page(self):
        service = ExplainService.__new__(ExplainService)
        service.page_audio_cache = {}

        class ErrorTTS:
            async def stream_tts_input(self, *args, **kwargs):
                yield {"type": "error", "message": "tts unavailable"}

        service.tts_service = ErrorTTS()
        service._cache_get = AsyncMock(return_value=None)
        service._cache_set = AsyncMock()

        with self.assertRaisesRegex(RuntimeError, "tts unavailable"):
            await service.get_or_generate_page_sentences(
                "hello", "document-1", 1, "course"
            )
        service._cache_set.assert_not_awaited()

    async def test_cancellation_is_isolated_by_session(self):
        service = ExplainService.__new__(ExplainService)
        service._cancel_tokens = {}

        service.cancel_stream("document-1", "session-a")

        self.assertTrue(service._is_cancelled("document-1", "session-a"))
        self.assertFalse(service._is_cancelled("document-1", "session-b"))

    async def test_cancelled_partial_page_is_not_cached_as_complete(self):
        service = ExplainService.__new__(ExplainService)
        service.page_audio_cache = {}
        service._cancel_tokens = {("document-1", "session-a"): True}

        class OneSentenceTTS:
            async def stream_tts_input(self, *args, **kwargs):
                yield {
                    "type": "audio",
                    "data": "AA==",
                    "index": 1,
                    "sentence": "partial",
                    "duration": 1,
                    "word_timestamps": [],
                }

        service.tts_service = OneSentenceTTS()
        service._cache_get = AsyncMock(return_value=None)
        service._cache_set = AsyncMock()

        events = [
            event
            async for event in service.stream_page_sentences(
                "document-1",
                1,
                None,
                "course",
                use_cache=False,
                session_id="session-a",
            )
        ]

        self.assertEqual(1, len(events))
        service._cache_get.assert_not_awaited()
        service._cache_set.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
