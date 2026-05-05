import logging
from app.config import settings
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from app.services.tts_service import TTSService
from app.models.db import get_upload

# 配置日志
if settings.ENABLE_LOGGING:
    # 创建文件处理器，将日志写入log.txt文件
    file_handler = logging.FileHandler("log.txt", encoding="utf-8")
    file_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    file_handler.setFormatter(file_formatter)

    # 创建控制台处理器
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
    # 只显示错误日志
    # 创建文件处理器，将错误日志写入log.txt文件
    file_handler = logging.FileHandler("log.txt", encoding="utf-8")
    file_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    file_handler.setFormatter(file_formatter)

    logger = logging.getLogger(__name__)
    logger.setLevel(logging.ERROR)
    logger.addHandler(file_handler)


router = APIRouter()
service = TTSService()


@router.get("/{file_id}/page/{page}")
def get_audio(file_id: str, page: int):
    logger.info(f"请求音频: file_id={file_id}, page={page}")
    upload = get_upload(file_id)
    if not upload:
        logger.error(f"文件未找到: {file_id}")
        raise HTTPException(status_code=404, detail="File not found")

    audio_path = service.get_audio_path(file_id, page)
    logger.info(f"音频路径: {audio_path}")
    if not audio_path:
        logger.error(f"音频未找到: file_id={file_id}, page={page}")
        raise HTTPException(status_code=404, detail="Audio not found")

    logger.info(f"返回音频文件: {audio_path}")
    return FileResponse(audio_path, media_type="audio/mpeg")


@router.post("/{file_id}/page/{page}")
def generate_audio(file_id: str, page: int, combined_text: str):
    logger.info(f"生成音频: file_id={file_id}, page={page}")
    logger.info(f"文本长度: {len(combined_text)}")
    try:
        audio_path = service.generate_and_get_audio(file_id, page, combined_text)
        logger.info(f"音频生成成功，路径: {audio_path}")
        return {"audio_url": f"/audio/{file_id}/page/{page}", "path": audio_path}
    except Exception as e:
        logger.error(f"音频生成失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{file_id}/merged")
def get_merged_audio(file_id: str):
    logger.info(f"请求合并音频: file_id={file_id}")
    upload = get_upload(file_id)
    if not upload:
        logger.error(f"文件未找到: {file_id}")
        raise HTTPException(status_code=404, detail="File not found")

    # 构建合并音频路径
    merged_audio_path = f"output/{file_id}_merged.mp3"
    from pathlib import Path

    audio_path = Path(merged_audio_path)

    logger.info(f"合并音频路径: {audio_path}")
    if not audio_path.exists():
        logger.error(f"合并音频未找到: {file_id}")
        raise HTTPException(status_code=404, detail="Merged audio not found")

    logger.info(f"返回合并音频文件: {audio_path}")
    return FileResponse(audio_path, media_type="audio/mpeg")
