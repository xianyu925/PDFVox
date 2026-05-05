import asyncio
import logging
from fastapi import APIRouter, UploadFile, File, HTTPException

from app.config import settings
from app.services.asr_service import ASRService

if settings.ENABLE_LOGGING:
    file_handler = logging.FileHandler("log.txt", encoding="utf-8")
    file_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    file_handler.setFormatter(file_formatter)

    console_handler = logging.StreamHandler()
    console_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    console_handler.setFormatter(console_formatter)

    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
else:
    import logging as _logging

    _logging.basicConfig(level=_logging.CRITICAL)
    logger = _logging.getLogger(__name__)


router = APIRouter()
service = ASRService()


@router.post("/detect")
async def detect_speaking(file: UploadFile = File(...)):
    """上传 PCM 原始音频（例如 16k 16-bit little-endian），返回是否检测到语音。"""
    try:
        data = await file.read()
        # 如果是 wav 文件，尝试简单剥离 wav header（如果以 RIFF 开头）
        if len(data) >= 12 and data[0:4] == b"RIFF":
            # 查找 "data" chunk
            idx = data.find(b"data")
            if idx != -1:
                pcm = data[idx + 8 :]
            else:
                pcm = data
        else:
            pcm = data

        speaking = await service.detect_speaking_from_pcm(pcm)
        return {"speaking": bool(speaking)}
    except Exception as e:
        logger.error(f"ASR detect error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
