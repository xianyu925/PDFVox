import unittest
from types import SimpleNamespace

from app.config import settings
from app.services.llm_service import LLMService


class FakeResponses:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


class LLMServiceTests(unittest.TestCase):
    def test_sync_response_uses_output_text_and_forwards_token_limit(self):
        responses = FakeResponses(SimpleNamespace(output_text="answer", output=[]))
        service = LLMService.__new__(LLMService)
        service.client = SimpleNamespace(responses=responses)

        result = service.generate_explanation("system", "question", max_tokens=123)

        self.assertEqual("answer", result)
        self.assertEqual(settings.LLM_MODEL, responses.kwargs["model"])
        self.assertEqual(123, responses.kwargs["max_output_tokens"])

    def test_extraction_does_not_require_a_second_output_item(self):
        response = SimpleNamespace(
            output_text=None,
            output=[SimpleNamespace(content=[SimpleNamespace(text="only item")])],
        )
        self.assertEqual("only item", LLMService._extract_response_text(response))


if __name__ == "__main__":
    unittest.main()
