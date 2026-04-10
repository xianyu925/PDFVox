from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from app.services.tts_service import TTSService
from app.models.db import get_upload

router = APIRouter()
service = TTSService()


@router.get("/{file_id}/page/{page}")
def get_audio(file_id: str, page: int):
    upload = get_upload(file_id)
    if not upload:
        raise HTTPException(status_code=404, detail="File not found")

    audio_path = service.get_audio_path(file_id, page)
    if not audio_path:
        raise HTTPException(status_code=404, detail="Audio not found")

    return FileResponse(audio_path, media_type="audio/mpeg")


@router.post("/{file_id}/page/{page}")
def generate_audio(file_id: str, page: int, combined_text: str):
    try:
        audio_path = service.generate_and_get_audio(file_id, page, combined_text)
        return {"audio_url": f"/audio/{file_id}/page/{page}", "path": audio_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
