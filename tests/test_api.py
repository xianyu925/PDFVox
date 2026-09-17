import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.routers import ai_explain


class APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_health(self):
        response = self.client.get("/api/health")
        self.assertEqual(200, response.status_code)
        self.assertEqual("1.0.0", response.json()["version"])
        self.assertEqual("1.0.0", app.version)

    def test_viewer_exposes_all_playback_rates(self):
        response = self.client.get("/viewer.html")
        self.assertEqual(200, response.status_code)
        self.assertIn('id="playback-rate"', response.text)
        for rate in ("0.5", "0.75", "1", "1.25", "1.5", "2"):
            self.assertIn(f'value="{rate}"', response.text)

    def test_cancel_requires_a_session_id(self):
        response = self.client.delete("/explain/cancel/document-1")
        self.assertEqual(422, response.status_code)

    def test_qa_requires_document_and_session_identifiers(self):
        response = self.client.post("/qa/ask/stream", data={"question": "hello"})
        self.assertEqual(422, response.status_code)

    def test_resume_stream_forwards_sentence_offset_without_resetting_page(self):
        captured = {}

        async def fake_page_stream(
            file_id,
            page_num,
            total_pages,
            course_name,
            session_id,
            *,
            skip_sentences=0,
            force_regenerate=False,
        ):
            captured.update(
                page=page_num,
                skip_sentences=skip_sentences,
                force_regenerate=force_regenerate,
            )
            yield {"type": "end", "page": page_num}

        with (
            patch.object(
                ai_explain,
                "_validated_upload",
                new=AsyncMock(return_value=({"path": "document.pdf"}, 1)),
            ),
            patch.object(ai_explain, "save_task"),
            patch.object(ai_explain, "update_task_status"),
            patch.object(ai_explain.service, "_reset_cancel"),
            patch.object(ai_explain.service, "_is_cancelled", return_value=False),
            patch.object(
                ai_explain.service,
                "explain_page_realtime_stream",
                new=fake_page_stream,
            ),
        ):
            response = self.client.get(
                "/explain/all-stream-v3/document-1",
                params={
                    "course_name": "course",
                    "from_page": 1,
                    "skip_sentences": 3,
                    "resume_generation": "true",
                    "session_id": "session-123",
                },
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {"page": 1, "skip_sentences": 3, "force_regenerate": True},
            captured,
        )


if __name__ == "__main__":
    unittest.main()
