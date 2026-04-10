import base64
from pathlib import Path
from typing import List
import pdfplumber


class PDFService:
    def __init__(self):
        pass

    def load_pdf(self, path: str):
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"PDF not found: {path}")
        with pdfplumber.open(str(p)) as pdf:
            return pdf

    def get_page_text(self, file_path: str, page: int) -> str:
        p = Path(file_path)
        if not p.exists():
            raise FileNotFoundError(f"PDF not found: {file_path}")

        with pdfplumber.open(str(p)) as pdf:
            if page < 1 or page > len(pdf.pages):
                raise IndexError("Page out of bounds")
            text = pdf.pages[page - 1].extract_text() or ""
            return text.strip()

    def get_page_image(self, file_path: str, page: int) -> str:
        p = Path(file_path)
        if not p.exists():
            raise FileNotFoundError(f"PDF not found: {file_path}")

        with pdfplumber.open(str(p)) as pdf:
            if page < 1 or page > len(pdf.pages):
                raise IndexError("Page out of bounds")
            image = pdf.pages[page - 1].to_image(resolution=200)
            import io

            img_bytes = io.BytesIO()
            image.save(img_bytes, format="PNG")
            img_bytes.seek(0)
            return base64.b64encode(img_bytes.getvalue()).decode("utf-8")

    def list_pages(self, file_path: str) -> List[int]:
        p = Path(file_path)
        if not p.exists():
            return []
        with pdfplumber.open(str(p)) as pdf:
            return list(range(1, len(pdf.pages) + 1))
