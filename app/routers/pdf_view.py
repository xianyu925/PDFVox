import logging
from app.config import settings

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

# 确保数据库初始化
from app.models.db import init_db

init_db()
from app.models.db import get_upload
from app.models.schemas import PageInfo
from app.services.pdf_service import PDFService

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
service = PDFService()


@router.get("/{file_id}")
def get_pdf_info(file_id: str):
    upload = get_upload(file_id)
    if not upload:
        raise HTTPException(status_code=404, detail="File not found")

    pages = service.list_pages(upload.get("path"))
    return {
        "file_id": upload["file_id"],
        "filename": upload["filename"],
        "pages": pages,
    }


@router.get("/{file_id}/page/{page}", response_model=PageInfo)
def get_pdf_page(file_id: str, page: int):
    upload = get_upload(file_id)
    if not upload:
        raise HTTPException(status_code=404, detail="File not found")

    file_path = upload.get("path")
    if not file_path:
        raise HTTPException(status_code=400, detail="Invalid file path")

    try:
        text = service.get_page_text(file_path, page)
        image_base64 = service.get_page_image(file_path, page)
        image_url = f"data:image/png;base64,{image_base64}"
        return PageInfo(page=page, text=text, image_url=image_url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
