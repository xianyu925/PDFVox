import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from app.config import PROJECT_ROOT, settings


class ConfigPathTests(unittest.TestCase):
    def test_default_paths_are_absolute_and_project_relative(self):
        self.assertTrue(Path(settings.STORAGE_PATH).is_absolute())
        self.assertEqual(PROJECT_ROOT / "web", settings.WEB_PATH)

    def test_config_import_does_not_depend_on_current_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(PROJECT_ROOT)
            env.pop("STORAGE_PATH", None)
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "from app.config import settings; "
                        "from pathlib import Path; "
                        "print(Path(settings.STORAGE_PATH))"
                    ),
                ],
                cwd=temp_dir,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )

        self.assertEqual(PROJECT_ROOT / "output", Path(result.stdout.strip()))

    def test_file_logging_can_be_disabled_for_automated_tests(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(PROJECT_ROOT)
            env["LOG_TO_FILE"] = "false"
            env["LOG_TO_CONSOLE"] = "false"
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "from pathlib import Path; "
                        "from app.utils.logging import get_logger; "
                        "get_logger('test').warning('test-only'); "
                        "print(Path('log.txt').exists())"
                    ),
                ],
                cwd=temp_dir,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )

        self.assertEqual("False", result.stdout.strip())


if __name__ == "__main__":
    unittest.main()
