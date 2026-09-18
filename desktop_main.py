"""Windows desktop entry point for the packaged PDFVox application."""

from __future__ import annotations

import multiprocessing
import os
import secrets
import socket
import sys
import threading
import time
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

from app.paths import user_data_root


LOOPBACK_HOST = "127.0.0.1"


def find_available_port(host: str = LOOPBACK_HOST) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def configure_desktop_environment() -> tuple[Path, str]:
    data_root = user_data_root()
    storage_path = data_root / "data"
    log_path = data_root / "logs" / "log.txt"
    model_cache = data_root / "models"
    for path in (storage_path, log_path.parent, model_cache):
        path.mkdir(parents=True, exist_ok=True)

    token = secrets.token_urlsafe(32)
    os.environ["PDFVOX_DESKTOP"] = "1"
    os.environ["PDFVOX_DESKTOP_TOKEN"] = token
    os.environ["PDFVOX_DATA_DIR"] = str(data_root)
    os.environ["STORAGE_PATH"] = str(storage_path)
    os.environ["LOG_FILE"] = str(log_path)
    os.environ["HF_HOME"] = str(model_cache)
    os.environ["HOST"] = LOOPBACK_HOST
    os.environ["AUTO_RELOAD"] = "false"
    os.environ["LOG_TO_CONSOLE"] = "false"
    return data_root, token


def wait_until_ready(port: int, timeout_seconds: float = 20.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    health_url = f"http://{LOOPBACK_HOST}:{port}/api/health"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=0.5) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("PDFVox local server did not start in time")


def smoke_test_packaged_app(port: int, desktop_token: str) -> None:
    """Exercise the frozen HTTP stack and bundled web resources without a GUI."""
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(CookieJar())
    )
    bootstrap_url = (
        f"http://{LOOPBACK_HOST}:{port}/desktop/bootstrap/{desktop_token}"
    )
    with opener.open(bootstrap_url, timeout=5) as response:
        status = response.status
        body = response.read().decode("utf-8")
    if status != 200 or "PDFVox" not in body:
        raise RuntimeError("PDFVox packaged application smoke test failed")

    # Exercise the native ONNX runtime and the bundled VAD model. These are
    # easy to omit accidentally because ASR is lazily imported at runtime.
    from app.services.asr_service import ASRService

    silence = bytes(16_000 * 2)
    if ASRService()._vad_check(silence, 16_000) is not False:
        raise RuntimeError("PDFVox packaged VAD smoke test failed")


def main() -> None:
    multiprocessing.freeze_support()
    _, desktop_token = configure_desktop_environment()
    port = find_available_port()

    # Imports must occur after desktop environment variables are set because
    # application configuration is intentionally created once at import time.
    import uvicorn
    from app.main import app as web_app

    config = uvicorn.Config(
        web_app,
        host=LOOPBACK_HOST,
        port=port,
        reload=False,
        access_log=False,
        log_config=None,
    )
    server = uvicorn.Server(config)
    server_thread = threading.Thread(
        target=server.run,
        name="pdfvox-local-server",
        daemon=True,
    )
    server_thread.start()

    try:
        wait_until_ready(port)
        if "--smoke-test" in sys.argv:
            smoke_test_packaged_app(port, desktop_token)
            return

        import webview

        url = (
            f"http://{LOOPBACK_HOST}:{port}/desktop/bootstrap/"
            f"{desktop_token}"
        )
        webview.create_window(
            "PDFVox",
            url,
            width=1280,
            height=820,
            min_size=(960, 640),
        )
        webview.start(debug=False)
    finally:
        server.should_exit = True
        server_thread.join(timeout=5)


if __name__ == "__main__":
    main()
