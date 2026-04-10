from fastapi import APIRouter, HTTPException
from app.models.schemas import ExplainRequest, ExplainResponse, StatusResponse
from app.services.explain_service import ExplainService
from app.services.tts_service import TTSService

router = APIRouter()
service = ExplainService()
tts_service = TTSService()


@router.post("/", response_model=ExplainResponse)
def explain(req: ExplainRequest):
    try:
        result = service.explain_page(
            req.file_id, req.page, req.auto_next, req.course_name
        )
        # 生成语音并附上结果
        audio_path = tts_service.generate_and_get_audio(
            req.file_id, req.page, result.combined_text or ""
        )
        result.audio_url = f"/audio/{req.file_id}/page/{req.page}"
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status/{task_id}", response_model=StatusResponse)
def explain_status(task_id: str):
    from app.models.db import get_task

    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return StatusResponse(
        task_id=task_id, status=task.get("status", "unknown"), detail=task.get("detail")
    )
