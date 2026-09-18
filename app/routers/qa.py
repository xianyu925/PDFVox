import asyncio
import json
import time

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from app.config import settings
from app.models.db import get_upload
from app.services.runtime import asr_service, explain_service, qa_service
from app.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


def _extract_pcm(data: bytes) -> bytes:
    """Extract PCM data from a WAV payload, or return raw PCM unchanged."""
    if len(data) >= 12 and data[:4] == b"RIFF":
        index = data.find(b"data")
        if index != -1 and index + 8 <= len(data):
            return data[index + 8 :]
    return data


@router.post("/ask/stream")
async def ask_question_stream(
    file: UploadFile | None = File(None),
    question: str | None = Form(None, max_length=4_000),
    file_id: str = Form(..., min_length=1, max_length=128),
    page_num: int = Form(1, ge=1),
    session_id: str = Form(..., min_length=8, max_length=128),
    course_name: str = Form("课程", min_length=1, max_length=200),
):
    """Stream a text or voice question through ASR, LLM and TTS."""
    if not question and file is None:
        raise HTTPException(status_code=422, detail="question or audio file is required")

    upload = await asyncio.to_thread(get_upload, file_id)
    if not upload or not upload.get("path"):
        raise HTTPException(status_code=404, detail="PDF record not found")
    total_pages = await explain_service.resolve_total_pages(upload)
    if page_num > total_pages:
        raise HTTPException(status_code=422, detail="page_num exceeds PDF page count")

    logger.info(
        "[QA请求] file_id=%s page=%s session=%s input=%s",
        file_id,
        page_num,
        session_id[:8],
        "text" if question else "audio",
    )

    async def generate_stream():
        try:
            transcript = ""
            if not question and file is not None:
                limit = settings.MAX_AUDIO_SIZE_MB * 1024 * 1024
                data = await file.read(limit + 1)
                if len(data) > limit:
                    yield f"data: {json.dumps({'type': 'error', 'message': 'Audio file is too large'})}\n\n"
                    return
                pcm = _extract_pcm(data)
                if len(pcm) % 2:
                    pcm = pcm[:-1]
                transcript = await asr_service.transcribe_pcm_to_text(pcm)

            user_question = (question or transcript).strip()
            if not user_question:
                yield f"data: {json.dumps({'type': 'error', 'message': 'No speech was recognized'})}\n\n"
                return

            async def ensure_script():
                try:
                    await explain_service.get_full_script(
                        file_id, page_num, course_name
                    )
                except Exception as exc:
                    logger.warning("Background script generation failed: %s", exc)

            asyncio.create_task(ensure_script())

            async for event in qa_service.stream_qa_response(
                file_id,
                page_num,
                user_question,
                session_id,
                course_name,
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            yield "data: [DONE]\n\n"
        except Exception as exc:
            logger.error("Streaming QA failed: %s", exc, exc_info=True)
            payload = {"type": "error", "message": str(exc), "ts": time.time()}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
        },
    )
