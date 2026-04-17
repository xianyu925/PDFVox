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
    logging.basicConfig(
        level=logging.DEBUG,  # 设置为DEBUG以显示所有日志
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger = logging.getLogger(__name__)
else:
    # 只显示错误日志
    logging.basicConfig(level=logging.ERROR)
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.ERROR)

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
