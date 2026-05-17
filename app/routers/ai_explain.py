import json
import time
import asyncio
import pdfplumber
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from app.models.schemas import ExplainRequest, StatusResponse
from app.services.explain_service import ExplainService
from app.services.tts_service import TTSService
from app.utils.logging import get_logger

logger = get_logger(__name__)


router = APIRouter()
service = ExplainService()
tts_service = TTSService()


@router.get("/playback/seek/{file_id}/page/{page_num}")
async def playback_seek(
    file_id: str,
    page_num: int,
    time_offset: float = 0.0,
    ahead: int = 60,
):
    """用户拖动进度时：播放该页的讲解语音，支持 time_offset 秒的页内跳转。"""

    async def generate_stream():
        try:
            from app.models.db import get_upload

            upload = get_upload(file_id)
            if not upload or not upload.get("path"):
                yield f"data: {json.dumps({'type':'error','message':'无法找到 file_id 对应记录'})}\n\n"
                return

            total_pages = upload.get("total_pages", 1)

            # 尝试使用已缓存的完整讲稿
            cache_key = f"script_{file_id}_{page_num}"
            full_script = service.summary_cache.get(cache_key)

            if not full_script:
                try:
                    full_script = await service.get_full_script(file_id, page_num)
                except Exception:
                    full_script = "此页内容正在生成，请稍候。"

            play_text = full_script if full_script else "此页内容正在生成，请稍候。"

            # 后台预生成后续页
            async def background_generate():
                try:
                    for p in range(page_num + 1, min(total_pages + 1, page_num + 1 + ahead)):
                        await service.get_full_script(file_id, p)
                except Exception as e:
                    logger.error(f"后台生成异常: {e}")

            asyncio.create_task(background_generate())

            # 获取页内分句音频
            sentences, from_cache = await service.get_or_generate_page_sentences(
                play_text, file_id, page_num
            )

            # time_offset: 跳过前 N 句直到累计时长 >= offset
            skipped = 0.0
            start_idx = 0
            if time_offset > 0:
                for i, item in enumerate(sentences):
                    d = item.get("duration", 0)
                    if skipped + d >= time_offset:
                        start_idx = i
                        break
                    skipped += d

            for i in range(start_idx, len(sentences)):
                item = sentences[i]
                yield f"data: {json.dumps({'type': 'audio', 'data': item['audio'], 'sentence': item['sentence'], 'duration': item.get('duration', 0), 'page': page_num, 'index': i})}\n\n"

            yield "data: [DONE]\n\n"

        except Exception as e:
            logger.error(f"playback_seek 发生异常: {e}", exc_info=True)
            yield f"data: {json.dumps({'type':'error','message':str(e)})}\n\n"

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


@router.delete("/cancel/{file_id}")
async def cancel_explain(file_id: str):
    """终止指定文件的流式讲解生成（LLM + TTS 同时终止）"""
    service.cancel_stream(file_id)
    logger.info(f"[API] 收到取消请求，已设置 file_id={file_id} 的取消令牌")
    return {"status": "cancelled", "file_id": file_id}


@router.get("/status/{task_id}", response_model=StatusResponse)
def explain_status(task_id: str):
    from app.models.db import get_task

    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return StatusResponse(
        task_id=task_id, status=task.get("status", "unknown"), detail=task.get("detail")
    )


@router.get("/stream-v3/{file_id}/page/{page_num}")
async def explain_page_stream_v3(
    file_id: str, page_num: int, course_name: str = "机器学习导论"
):
    logger.info(
        f"开始极速流式生成讲解: file_id={file_id}, page={page_num}, course={course_name}"
    )

    async def generate_stream():
        try:
            if service._is_cancelled(file_id):
                yield f"data: {json.dumps({'type': 'cancelled', 'ts': time.time()})}\n\n"
                return
            async for event in service.explain_page_realtime_stream(
                file_id=file_id, page_num=int(page_num), course_name=course_name
            ):
                # 统一转为 SSE 标准格式下发
                yield f"data: {json.dumps(event)}\n\n"

            # 正常结束标记
            yield "data: [DONE]\n\n"

        except Exception as e:
            logger.error(f"极速流式生成失败: {str(e)}", exc_info=True)
            error_data = {
                "type": "error",
                "message": str(e),
                "page": page_num,
                "ts": time.time(),
            }
            yield f"data: {json.dumps(error_data)}\n\n"

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 Nginx 缓存，确保流式立即推送到前端
            "Access-Control-Allow-Origin": "*",
        },
    )


@router.get("/all-stream-v3/{file_id}")
async def explain_all_pages_stream_v3(
    file_id: str,
    course_name: str = "机器学习导论",
    from_page: int = 1,
):
    """
    【最新版】全书极速流式讲解生成（逐页并发摘要、推流文字和音频）
    """
    logger.info(
        f"开始全书极速流式生成讲解: file_id={file_id}, course={course_name}, from_page={from_page}"
    )

    async def generate_stream():
        try:
            from app.models.db import get_upload

            upload = get_upload(file_id)
            if not upload or not upload.get("path"):
                raise ValueError(f"无法找到文件记录或路径: {file_id}")

            pdf_path = upload.get("path")
            with pdfplumber.open(pdf_path) as pdf:
                total_pages = len(pdf.pages)

            service._reset_cancel(file_id)

            yield f"data: {json.dumps({'type': 'global_start', 'total_pages': total_pages, 'ts': time.time()})}\n\n"

            for page_num in range(from_page, total_pages + 1):
                if service._is_cancelled(file_id):
                    logger.info(f"[全书流] 检测到取消令牌，终止于第{page_num}页")
                    yield f"data: {json.dumps({'type': 'cancelled', 'ts': time.time()})}\n\n"
                    break

                yield f"data: {json.dumps({'type': 'page_start', 'page': page_num, 'ts': time.time()})}\n\n"

                # 当前页推流的同时，后台预热下一页所需的相邻摘要
                prefetch_page = page_num + 2
                if prefetch_page <= total_pages:
                    asyncio.create_task(
                        service.prefetch_summary(
                            file_id, prefetch_page, pdf_path, course_name
                        )
                    )

                async for event in service.explain_page_realtime_stream(
                    file_id, page_num, total_pages, course_name
                ):
                    yield f"data: {json.dumps(event)}\n\n"

                yield f"data: {json.dumps({'type': 'page_complete', 'page': page_num, 'total_pages': total_pages, 'ts': time.time()})}\n\n"

            # 发送全局结束标记
            yield f"data: {json.dumps({'type': 'global_end', 'ts': time.time()})}\n\n"
            yield "data: [DONE]\n\n"

        except Exception as e:
            logger.error(f"全书流式生成失败: {str(e)}", exc_info=True)
            error_data = {"type": "error", "message": str(e), "ts": time.time()}
            yield f"data: {json.dumps(error_data)}\n\n"

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
