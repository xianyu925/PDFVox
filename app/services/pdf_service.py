import base64
import io
import threading
from pathlib import Path
from typing import List

import pdfplumber

from app.config import settings


def _resolve_path(file_path: str) -> Path:
    """将存储的路径解析为绝对路径。若为相对路径则基于 STORAGE_PATH。"""
    p = Path(file_path)
    if p.is_absolute():
        return p
    return Path(settings.STORAGE_PATH).resolve() / p.name


class PDFService:
    def __init__(self):
        self._locks: dict[str, threading.Lock] = {}

    def _get_lock(self, file_path: str) -> threading.Lock:
        path = str(_resolve_path(file_path))
        if path not in self._locks:
            self._locks[path] = threading.Lock()
        return self._locks[path]

    def get_page_text(self, file_path: str, page: int) -> str:
        p = _resolve_path(file_path)
        if not p.exists():
            raise FileNotFoundError(f"PDF not found: {p}")

        lock = self._get_lock(str(p))
        with lock:
            with pdfplumber.open(str(p)) as pdf:
                if page < 1 or page > len(pdf.pages):
                    raise IndexError("Page out of bounds")
                text = pdf.pages[page - 1].extract_text() or ""
                return text.strip()

    def get_page_image(self, file_path: str, page: int) -> str:
        p = _resolve_path(file_path)
        if not p.exists():
            raise FileNotFoundError(f"PDF not found: {p}")

        lock = self._get_lock(str(p))
        with lock:
            with pdfplumber.open(str(p)) as pdf:
                if page < 1 or page > len(pdf.pages):
                    raise IndexError("Page out of bounds")
                image = pdf.pages[page - 1].to_image(resolution=150)

                img_bytes = io.BytesIO()
                image.save(img_bytes, format="PNG")
                img_bytes.seek(0)
                return base64.b64encode(img_bytes.getvalue()).decode("utf-8")

    def list_pages(self, file_path: str) -> List[int]:
        p = _resolve_path(file_path)
        if not p.exists():
            raise FileNotFoundError(f"PDF not found: {p}")
        lock = self._get_lock(str(p))
        with lock:
            with pdfplumber.open(str(p)) as pdf:
                return list(range(1, len(pdf.pages) + 1))
