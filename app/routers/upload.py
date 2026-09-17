import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.config import settings
from app.models.schemas import UploadResponse
from app.models.db import save_upload
from app.services.pdf_service import PDFService
from app.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()
pdf_service = PDFService()


@router.post("/", response_model=UploadResponse)
def upload_pdf(file: UploadFile = File(...)):
    filename = file.filename or ""
    file_ext = Path(filename).suffix.lower()
    if file_ext not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Invalid file type")

    file_id = str(uuid.uuid4())
    out_dir = Path(settings.STORAGE_PATH)
    out_dir.mkdir(parents=True, exist_ok=True)
    file_path = out_dir / f"{file_id}{file_ext}"

    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    written = 0
    try:
        with file_path.open("wb") as target:
            while chunk := file.file.read(1024 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"PDF must not exceed {settings.MAX_UPLOAD_SIZE_MB} MB",
                    )
                target.write(chunk)

        if written == 0:
            raise HTTPException(status_code=400, detail="PDF file is empty")

        total_pages = pdf_service.get_page_count(str(file_path))
        if total_pages < 1:
            raise ValueError("PDF contains no pages")
    except HTTPException:
        file_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        file_path.unlink(missing_ok=True)
        logger.warning("Invalid PDF upload %s: %s", filename, exc)
        raise HTTPException(status_code=400, detail="Invalid or unreadable PDF") from exc

    doc = {
        "file_id": file_id,
        "filename": filename,
        "path": str(file_path),
        "total_pages": total_pages,
    }
    save_upload(file_id, doc)

    return {
        "file_id": file_id,
        "filename": filename,
        "url": f"/pdf/{file_id}",
        "total_pages": total_pages,
    }
