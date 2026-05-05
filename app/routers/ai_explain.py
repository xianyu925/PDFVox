import logging
import json
import time
import asyncio
import pdfplumber
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from app.models.schemas import ExplainRequest, StatusResponse
from app.services.explain_service import ExplainService
from app.services.tts_service import TTSService
from app.config import settings

# 配置日志
if settings.ENABLE_LOGGING:
    file_handler = logging.FileHandler("log.txt", encoding="utf-8")
    file_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    file_handler.setFormatter(file_formatter)

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
    file_handler = logging.FileHandler("log.txt", encoding="utf-8")
    file_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    file_handler.setFormatter(file_formatter)

    logger = logging.getLogger(__name__)
    logger.setLevel(logging.ERROR)
    logger.addHandler(file_handler)


router = APIRouter()
service = ExplainService()
tts_service = TTSService()


@router.get("/playback/seek/{file_id}/page/{page_num}")
async def playback_seek(
    file_id: str, page_num: int, current_page: int = None, ahead: int = 60
):
    """用户拖动进度时：播放该页的完整讲解语音，同时后台并发预生成后续 `ahead` 页的讲稿（不阻塞）。"""

    async def generate_stream():
        try:
            from app.models.db import get_upload

            upload = get_upload(file_id)
            if not upload or not upload.get("path"):
                yield f"data: {json.dumps({'type':'error','message':'无法找到 file_id 对应记录'})}\n\n"
                return

            total_pages = upload.get("total_pages", 1)

            # 如果给定了 current_page，拒绝向前跳转（只能回退到更早的位置）
            if current_page is not None and page_num > current_page:
                yield f"data: {json.dumps({'type':'error','message':'只允许回退到更早的位置，禁止向前跳转'})}\n\n"
                return

            # 尝试使用已缓存的完整讲稿
            cache_key = f"script_{file_id}_{page_num}"
            full_script = service.summary_cache.get(cache_key)

            # 如果没有完整讲稿，同步生成完整讲稿后再播放
            if not full_script:
                try:
                    full_script = await service.get_full_script(file_id, page_num)
                except Exception:
                    full_script = "此页内容正在生成，请稍候。"

            play_text = full_script if full_script else "此页内容正在生成，请稍候。"

            # 后台并发：预先为后续若干页生成完整讲稿
            async def background_generate():
                try:
                    for p in range(page_num + 1, min(total_pages + 1, page_num + 1 + ahead)):
                        await service.get_full_script(file_id, p)
                except Exception as e:
                    logger.error(f"后台生成异常: {e}")

            asyncio.create_task(background_generate())

            # 使用按句拆分的音频缓存（每句 = 完整语音 + 字幕，一一对应）
            sentences, from_cache = await service.get_or_generate_page_sentences(
                play_text, file_id, page_num
            )

            for i, item in enumerate(sentences):
                yield f"data: {json.dumps({'type': 'audio', 'data': item['audio'], 'sentence': item['sentence'], 'page': page_num, 'index': i})}\n\n"

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
                # 发送页面开始事件
                yield f"data: {json.dumps({'type': 'page_start', 'page': page_num, 'ts': time.time()})}\n\n"

                # 消费当前页的双流事件
                async for event in service.explain_page_realtime_stream(
                    file_id, page_num, total_pages, course_name
                ):
                    yield f"data: {json.dumps(event)}\n\n"

                # 发送页面进度事件
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
