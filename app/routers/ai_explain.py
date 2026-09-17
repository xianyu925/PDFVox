import asyncio
import base64
import json
import time
import uuid

from fastapi import APIRouter, HTTPException, Path, Query
from fastapi.responses import StreamingResponse

from app.models.db import (
    get_task,
    get_upload,
    save_task,
    update_task_status,
)
from app.models.schemas import StatusResponse
from app.services.runtime import explain_service as service
from app.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()

PCM_SAMPLE_RATE = 24_000
PCM_SAMPLE_WIDTH = 2


def _sse(payload) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _stream_headers(task_id: str | None = None) -> dict[str, str]:
    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
        "Access-Control-Allow-Origin": "*",
    }
    if task_id:
        headers["X-Task-Id"] = task_id
    return headers


def _trim_pcm_sentence(item: dict, offset_seconds: float) -> dict:
    """Trim a cached mono 16-bit PCM sentence and rebase its word timestamps."""
    if offset_seconds <= 0:
        return item

    raw_audio = base64.b64decode(item.get("audio", ""))
    byte_offset = int(offset_seconds * PCM_SAMPLE_RATE) * PCM_SAMPLE_WIDTH
    byte_offset = min(len(raw_audio), byte_offset - (byte_offset % PCM_SAMPLE_WIDTH))
    actual_offset = byte_offset / (PCM_SAMPLE_RATE * PCM_SAMPLE_WIDTH)
    trimmed_audio = raw_audio[byte_offset:]

    timestamps = []
    for word in item.get("word_timestamps", []):
        start = float(word.get("start", 0))
        end = float(word.get("end", 0))
        if end <= actual_offset:
            continue
        timestamps.append(
            {
                **word,
                "start": round(max(0.0, start - actual_offset), 3),
                "end": round(max(0.0, end - actual_offset), 3),
            }
        )

    return {
        **item,
        "audio": base64.b64encode(trimmed_audio).decode("utf-8"),
        "duration": round(
            len(trimmed_audio) / PCM_SAMPLE_WIDTH / PCM_SAMPLE_RATE, 3
        ),
        "word_timestamps": timestamps,
    }


async def _validated_upload(file_id: str, page_num: int | None = None):
    upload = await asyncio.to_thread(get_upload, file_id)
    if not upload or not upload.get("path"):
        raise HTTPException(status_code=404, detail="PDF record not found")
    total_pages = await service.resolve_total_pages(upload)
    if page_num is not None and page_num > total_pages:
        raise HTTPException(status_code=422, detail="page_num exceeds PDF page count")
    return upload, total_pages


@router.get("/playback/seek/{file_id}/page/{page_num}")
async def playback_seek(
    file_id: str = Path(min_length=1, max_length=128),
    page_num: int = Path(ge=1),
    time_offset: float = Query(0.0, ge=0),
    ahead: int = Query(3, ge=0, le=10),
    course_name: str = Query("课程", min_length=1, max_length=200),
):
    """Replay cached/generated page audio starting at a page-local offset."""
    _, total_pages = await _validated_upload(file_id, page_num)

    async def generate_stream():
        try:
            full_script = await service.get_cached_script(
                file_id, page_num, course_name
            )
            if not full_script:
                full_script = await service.get_full_script(
                    file_id, page_num, course_name
                )

            async def background_generate():
                try:
                    last_page = min(total_pages + 1, page_num + 1 + ahead)
                    for page in range(page_num + 1, last_page):
                        await service.get_full_script(
                            file_id, page, course_name
                        )
                except Exception as exc:
                    logger.error("Background script generation failed: %s", exc)

            if ahead:
                asyncio.create_task(background_generate())

            sentences, _ = await service.get_or_generate_page_sentences(
                full_script, file_id, page_num, course_name
            )

            skipped = 0.0
            start_idx = len(sentences)
            first_sentence_offset = 0.0
            for index, item in enumerate(sentences):
                duration = max(float(item.get("duration", 0)), 0.0)
                if skipped + duration >= time_offset:
                    start_idx = index
                    first_sentence_offset = max(0.0, time_offset - skipped)
                    break
                skipped += duration

            for index in range(start_idx, len(sentences)):
                item = sentences[index]
                if index == start_idx and first_sentence_offset > 0:
                    item = _trim_pcm_sentence(item, first_sentence_offset)
                if not item.get("audio") or item.get("duration", 0) <= 0:
                    continue
                yield _sse(
                    {
                        "type": "audio",
                        "data": item["audio"],
                        "sentence": item["sentence"],
                        "duration": item.get("duration", 0),
                        "word_timestamps": item.get("word_timestamps", []),
                        "page": page_num,
                        "index": index,
                    }
                )
            yield "data: [DONE]\n\n"
        except Exception as exc:
            logger.error("playback_seek failed: %s", exc, exc_info=True)
            yield _sse({"type": "error", "message": str(exc)})

    return StreamingResponse(
        generate_stream(), media_type="text/event-stream", headers=_stream_headers()
    )


@router.delete("/cancel/{file_id}")
async def cancel_explain(
    file_id: str = Path(min_length=1, max_length=128),
    session_id: str = Query(..., min_length=8, max_length=128),
):
    service.cancel_stream(file_id, session_id)
    return {"status": "cancelled", "file_id": file_id, "session_id": session_id}


@router.get("/status/{task_id}", response_model=StatusResponse)
def explain_status(task_id: str = Path(min_length=1, max_length=128)):
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return StatusResponse(
        task_id=task_id,
        status=task.get("status", "unknown"),
        detail=task.get("detail"),
    )


@router.get("/stream-v3/{file_id}/page/{page_num}")
async def explain_page_stream_v3(
    file_id: str = Path(min_length=1, max_length=128),
    page_num: int = Path(ge=1),
    course_name: str = Query("机器学习导论", min_length=1, max_length=200),
    session_id: str = Query(..., min_length=8, max_length=128),
):
    _, total_pages = await _validated_upload(file_id, page_num)
    task_id = uuid.uuid4().hex
    await asyncio.to_thread(
        save_task,
        task_id,
        {"file_id": file_id, "page": page_num, "status": "queued", "detail": None},
    )
    service._reset_cancel(file_id, session_id)

    async def generate_stream():
        failed = False
        try:
            await asyncio.to_thread(update_task_status, task_id, "running", None)
            yield _sse(
                {"type": "task_start", "task_id": task_id, "page": page_num}
            )
            async for event in service.explain_page_realtime_stream(
                file_id=file_id,
                page_num=page_num,
                total_pages=total_pages,
                course_name=course_name,
                session_id=session_id,
            ):
                if event.get("type") == "error":
                    failed = True
                yield _sse(event)

            status = "cancelled" if service._is_cancelled(file_id, session_id) else (
                "failed" if failed else "completed"
            )
            await asyncio.to_thread(update_task_status, task_id, status, None)
            yield "data: [DONE]\n\n"
        except asyncio.CancelledError:
            await asyncio.to_thread(
                update_task_status, task_id, "cancelled", "Client disconnected"
            )
            raise
        except Exception as exc:
            logger.error("Page stream failed: %s", exc, exc_info=True)
            await asyncio.to_thread(update_task_status, task_id, "failed", str(exc))
            yield _sse(
                {"type": "error", "message": str(exc), "page": page_num, "ts": time.time()}
            )
        finally:
            service._reset_cancel(file_id, session_id)

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers=_stream_headers(task_id),
    )


@router.get("/all-stream-v3/{file_id}")
async def explain_all_pages_stream_v3(
    file_id: str = Path(min_length=1, max_length=128),
    course_name: str = Query("机器学习导论", min_length=1, max_length=200),
    from_page: int = Query(1, ge=1),
    skip_sentences: int = Query(0, ge=0),
    resume_generation: bool = Query(False),
    session_id: str = Query(..., min_length=8, max_length=128),
):
    upload, total_pages = await _validated_upload(file_id)
    if from_page > total_pages:
        raise HTTPException(status_code=422, detail="from_page exceeds PDF page count")

    task_id = uuid.uuid4().hex
    await asyncio.to_thread(
        save_task,
        task_id,
        {"file_id": file_id, "page": from_page, "status": "queued", "detail": None},
    )
    service._reset_cancel(file_id, session_id)

    async def generate_stream():
        try:
            await asyncio.to_thread(update_task_status, task_id, "running", None)
            yield _sse(
                {
                    "type": "global_start",
                    "task_id": task_id,
                    "total_pages": total_pages,
                    "ts": time.time(),
                }
            )

            for page_num in range(from_page, total_pages + 1):
                if service._is_cancelled(file_id, session_id):
                    await asyncio.to_thread(
                        update_task_status, task_id, "cancelled", None
                    )
                    yield _sse({"type": "cancelled", "ts": time.time()})
                    return

                yield _sse({"type": "page_start", "page": page_num, "ts": time.time()})
                prefetch_page = page_num + 2
                if prefetch_page <= total_pages:
                    asyncio.create_task(
                        service.prefetch_summary(
                            file_id,
                            prefetch_page,
                            upload["path"],
                            course_name,
                        )
                    )

                async for event in service.explain_page_realtime_stream(
                    file_id,
                    page_num,
                    total_pages,
                    course_name,
                    session_id,
                    skip_sentences=skip_sentences if page_num == from_page else 0,
                    force_regenerate=resume_generation and page_num == from_page,
                ):
                    yield _sse(event)
                    if event.get("type") == "error":
                        await asyncio.to_thread(
                            update_task_status,
                            task_id,
                            "failed",
                            event.get("message"),
                        )
                        yield "data: [DONE]\n\n"
                        return

                yield _sse(
                    {
                        "type": "page_complete",
                        "page": page_num,
                        "total_pages": total_pages,
                        "ts": time.time(),
                    }
                )

            await asyncio.to_thread(update_task_status, task_id, "completed", None)
            yield _sse({"type": "global_end", "task_id": task_id, "ts": time.time()})
            yield "data: [DONE]\n\n"
        except asyncio.CancelledError:
            await asyncio.to_thread(
                update_task_status, task_id, "cancelled", "Client disconnected"
            )
            raise
        except Exception as exc:
            logger.error("All-pages stream failed: %s", exc, exc_info=True)
            await asyncio.to_thread(update_task_status, task_id, "failed", str(exc))
            yield _sse({"type": "error", "message": str(exc), "ts": time.time()})
            yield "data: [DONE]\n\n"
        finally:
            service._reset_cancel(file_id, session_id)

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers=_stream_headers(task_id),
    )
