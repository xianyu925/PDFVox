import unittest
from unittest.mock import patch

from app.services.qa_service import QAService


class FakeExplainService:
    def __init__(self):
        self.scripts = {}

    async def get_cached_script(self, file_id, page_num, course_name="课程"):
        return self.scripts.get((file_id, page_num, course_name))


class QAServiceCacheTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.explain = FakeExplainService()
        self.service = QAService(None, None, self.explain)

    async def test_collects_scripts_for_the_selected_course(self):
        self.explain.scripts.update(
            {
                ("document-1", 1, "AI"): "第一页讲稿",
                ("document-1", 2, "AI"): "第二页讲稿",
                ("document-1", 1, "Math"): "different course",
            }
        )

        scripts = await self.service._get_all_scripts("document-1", 2, "AI")

        self.assertEqual({1: "第一页讲稿", 2: "第二页讲稿"}, scripts)

    async def test_history_is_isolated_and_keeps_latest_five_rounds(self):
        with patch(
            "app.services.qa_service.get_generated_cache", return_value=None
        ), patch("app.services.qa_service.save_generated_cache"):
            for index in range(7):
                await self.service.add_history(
                    "document-1", f"问题{index}", f"回答{index}", "session-a"
                )
            await self.service.add_history(
                "document-1", "other", "answer", "session-b"
            )

        session_a = await self.service._get_history("document-1", "session-a")
        session_b = await self.service._get_history("document-1", "session-b")
        self.assertEqual(5, len(session_a))
        self.assertEqual("问题2", session_a[0]["question"])
        self.assertEqual("问题6", session_a[-1]["question"])
        self.assertEqual("other", session_b[0]["question"])


if __name__ == "__main__":
    unittest.main()
