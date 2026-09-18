import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.desktop_security import install_desktop_security
from desktop_main import (
    configure_desktop_environment,
    find_available_port,
    smoke_test_packaged_app,
)


class DesktopRuntimeTests(unittest.TestCase):
    def test_desktop_environment_uses_writable_user_directories(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"PDFVOX_DATA_DIR": temp_dir},
            clear=False,
        ):
            root, token = configure_desktop_environment()

            self.assertEqual(Path(temp_dir).resolve(), root)
            self.assertTrue(token)
            self.assertEqual(str(root / "data"), os.environ["STORAGE_PATH"])
            self.assertEqual(str(root / "logs" / "log.txt"), os.environ["LOG_FILE"])
            self.assertTrue((root / "models").is_dir())

    def test_available_port_is_a_valid_tcp_port(self):
        port = find_available_port()
        self.assertGreater(port, 0)
        self.assertLessEqual(port, 65_535)

    def test_packaged_smoke_test_follows_bootstrap_redirect(self):
        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            @staticmethod
            def read():
                return b"<title>PDFVox</title>"

        class FakeOpener:
            @staticmethod
            def open(url, timeout):
                self.assertEqual(
                    "http://127.0.0.1:12345/desktop/bootstrap/token",
                    url,
                )
                self.assertEqual(5, timeout)
                return FakeResponse()

        with patch("desktop_main.urllib.request.build_opener", return_value=FakeOpener()):
            smoke_test_packaged_app(12345, "token")

    def test_desktop_session_rejects_requests_without_bootstrap_cookie(self):
        api = FastAPI()

        @api.get("/private")
        def private_route():
            return {"ok": True}

        with patch.dict(os.environ, {"PDFVOX_DESKTOP_TOKEN": "secret-token"}):
            install_desktop_security(api)

        with TestClient(api) as client:
            self.assertEqual(403, client.get("/private").status_code)
            response = client.get(
                "/desktop/bootstrap/secret-token",
                follow_redirects=False,
            )
            self.assertEqual(302, response.status_code)
            self.assertEqual(200, client.get("/private").status_code)


if __name__ == "__main__":
    unittest.main()
