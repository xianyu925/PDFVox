import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.models import db


class DatabaseTests(unittest.TestCase):
    def test_generated_cache_and_task_status_are_persisted(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            db, "DB_FILE", Path(temp_dir) / "test.db"
        ):
            db.init_db()
            db.save_generated_cache("key", "script", {"value": 1}, 60, 10)
            self.assertEqual({"value": 1}, db.get_generated_cache("key"))

            db.save_task(
                "task-1",
                {"file_id": "document-1", "page": 1, "status": "queued"},
            )
            db.update_task_status("task-1", "completed", None)
            self.assertEqual("completed", db.get_task("task-1")["status"])


if __name__ == "__main__":
    unittest.main()
