import logging
from app.config import settings

from fastapi import APIRouter, UploadFile, File, HTTPException
from pathlib import Path
import uuid

from app.config import settings
from app.models.schemas import UploadResponse
from app.models.db import save_upload

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


@router.post("/", response_model=UploadResponse)
def upload_pdf(file: UploadFile = File(...)):
    # 验证文件扩展名，保存到存储目录
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Invalid file type")

    file_id = str(uuid.uuid4())
    out_dir = Path(settings.STORAGE_PATH)
    out_dir.mkdir(parents=True, exist_ok=True)
    file_path = out_dir / f"{file_id}{file_ext}"

    with file_path.open("wb") as f:
        f.write(file.file.read())

    doc = {
        "file_id": file_id,
        "filename": file.filename,
        "path": str(file_path),
    }
    save_upload(file_id, doc)

    return {"file_id": file_id, "filename": file.filename, "url": f"/pdf/{file_id}"}
