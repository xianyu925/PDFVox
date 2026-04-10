from pathlib import Path
from app.models.db import get_upload
from pdfvox import PDFVox
from app.config import settings

# 负责调用 TTS 产生语音文件，并返回路径


class TTSService:
    def __init__(self):
        self.output_dir = Path("output")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.pdfvox = PDFVox(settings.API_KEY)

    def tts_page(self, file_id: str, page: int, text: str):
        # 直接调用现有 PDFVox.TTS 方法，生成单页音频
        output_path = self.output_dir
        content = [{"page": page, "explanation": text, "transition": ""}]
        audio_files = self.pdfvox.TTS(content, str(output_path))
        if audio_files:
            return audio_files[0]["audio_path"]
        return ""

    def get_audio_path(self, file_id: str, page: int) -> str:
        candidate = self.output_dir / f"page_{page}.mp3"
        return str(candidate) if candidate.exists() else ""

    def generate_and_get_audio(self, file_id: str, page: int, combined_text: str):
        if not combined_text:
            raise ValueError("No text provided for TTS")
        audio_path = self.tts_page(file_id, page, combined_text)
        return audio_path
