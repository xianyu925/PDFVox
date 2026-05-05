import logging
import asyncio
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from app.models.db import get_upload

from app.services.asr_service import ASRService
from app.services.explain_service import ExplainService
from app.services.llm_service import LLMService
import asyncio
from app.services.tts_service import TTSService
from fastapi.responses import StreamingResponse
import json
import time
from app.config import settings

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
    import logging as _logging

    _logging.basicConfig(level=_logging.CRITICAL)
    logger = _logging.getLogger(__name__)


router = APIRouter()
asr_service = ASRService()
explain_service = ExplainService()
llm_service = LLMService()
tts_service = TTSService()


@router.post("/ask")
async def ask_question(
    file: UploadFile = File(None),
    question: str = Form(None),
    file_id: str = Form(None),
    page_num: int = Form(1),
):
    """接收音频或文本问题，使用 ASR 转写（若上传音频），然后将问题和对应页的讲稿传给 LLM 并返回答案。"""
    try:
        transcript = ""
        # 如果提供了 file_id，提前在后台触发该页完整讲稿的生成（并发，不阻塞）
        background_script_task = None
        if file_id:
            try:
                background_script_task = asyncio.create_task(
                    explain_service.get_full_script(file_id, page_num)
                )
            except Exception:
                background_script_task = None

        if file is not None:
            data = await file.read()
            # 尝试剥离 wav header
            if len(data) >= 12 and data[0:4] == b"RIFF":
                idx = data.find(b"data")
                if idx != -1:
                    pcm = data[idx + 8 :]
                else:
                    pcm = data
            else:
                pcm = data

            transcript = await asr_service.transcribe_pcm_to_text(pcm)
            logger.info(f"ASR 转写得到: {transcript}")

        if not question and not transcript:
            raise HTTPException(status_code=400, detail="需要上传音频或提供问题文本")

        user_question = question if question else transcript

        # 获取 PPT 页面图片与当前已生成的讲稿（优先使用缓存）
        if not file_id:
            raise HTTPException(
                status_code=400, detail="需要提供 file_id 对应的 PDF 记录"
            )

        upload = get_upload(file_id)
        if not upload or not upload.get("path"):
            raise HTTPException(
                status_code=400, detail="无法找到 file_id 对应的 PDF 记录或路径"
            )

        pdf_path = upload.get("path")

        # 尝试从 ExplainService 缓存获取当前已生成的讲稿；若不存在则只使用 PPT（不触发生成）
        cache_key = f"script_{file_id}_{page_num}"
        current_script = explain_service.summary_cache.get(cache_key)

        # 获取页面图片（用于多模态上下文）
        try:
            image_base64 = await asyncio.to_thread(
                explain_service.pdf_service.get_page_image, pdf_path, page_num
            )
        except Exception:
            image_base64 = None

        if current_script:
            system_prompt = "你是一位大学教授，基于给定的PPT页面图像和当前已生成的讲稿回答学生的问题，回答要准确且尽量简洁。"
            user_prompt = []
            user_prompt.append(
                {"type": "text", "text": f"当前已生成讲稿：\n{current_script}"}
            )
            if image_base64:
                user_prompt.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image_base64}"},
                    }
                )
            user_prompt.append(
                {
                    "type": "text",
                    "text": f"学生提问：{user_question}\n请基于讲稿和PPT直接回答，必要时引用讲稿中的要点。",
                }
            )
        else:
            system_prompt = "你是一位大学教授，基于给定的PPT页面图像回答学生的问题，回答要准确且尽量简洁。"
            user_prompt = []
            if image_base64:
                user_prompt.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image_base64}"},
                    }
                )
            user_prompt.append(
                {
                    "type": "text",
                    "text": f"学生提问：{user_question}\n请基于PPT直接回答，必要时指出无法从讲稿得到信息。",
                }
            )

        # 不要等待后台生成任务完成——若已完成则使用它，否则继续无需阻塞
        answer = llm_service.generate_explanation(system_prompt, user_prompt)

        return {"question": user_question, "answer": answer}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"QA 处理失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ask/stream")
async def ask_question_stream(
    file: UploadFile = File(None),
    question: str = Form(None),
    file_id: str = Form(None),
    page_num: int = Form(1),
):
    """流式问答：LLM 流式返回文本，同时将文本流送入 TTS，音频与文本事件以 SSE 下发。"""

    async def generate_stream():
        try:
            transcript = ""
            # 并发触发后台讲稿生成（不阻塞流式问答主流程）
            background_script_task = None
            if file_id:
                try:
                    background_script_task = asyncio.create_task(
                        explain_service.get_full_script(file_id, page_num)
                    )
                except Exception:
                    background_script_task = None

            if file is not None:
                data = await file.read()
                if len(data) >= 12 and data[0:4] == b"RIFF":
                    idx = data.find(b"data")
                    if idx != -1:
                        pcm = data[idx + 8 :]
                    else:
                        pcm = data
                else:
                    pcm = data

                transcript = await asr_service.transcribe_pcm_to_text(pcm)
                logger.info(f"ASR 转写得到: {transcript}")

            if not question and not transcript:
                yield f"data: {json.dumps({'type':'error','message':'语音识别未能获取到文本，请确保麦克风正常并重试'})}\n\n"
                return

            user_question = question if question else transcript

            if not file_id:
                yield f"data: {json.dumps({'type':'error','message':'需要提供 file_id'})}\n\n"
                return

            # 获取 upload 记录并优先使用缓存讲稿；若无缓存则仅使用 PPT 图片作为上下文（不触发生成）
            upload = get_upload(file_id)
            if not upload or not upload.get("path"):
                yield f"data: {json.dumps({'type':'error','message':'无法找到 file_id 对应记录'})}\n\n"
                return
            cache_key = f"script_{file_id}_{page_num}"
            current_script = explain_service.summary_cache.get(cache_key)

            # 获取页面图片
            try:
                image_base64 = await asyncio.to_thread(
                    explain_service.pdf_service.get_page_image,
                    upload.get("path"),
                    page_num,
                )
            except Exception:
                image_base64 = None

            if current_script:
                system_prompt = "你是一位大学教授，基于以下讲稿回答学生的问题，回答要准确且尽量简洁。"
                user_prompt = []
                user_prompt.append(
                    {"type": "text", "text": f"讲稿内容:\n{current_script}"}
                )
                if image_base64:
                    user_prompt.append(
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{image_base64}"
                            },
                        }
                    )
                user_prompt.append(
                    {
                        "type": "text",
                        "text": f"学生提问：{user_question}\n请基于讲稿直接回答，必要时引用讲稿中的要点。",
                    }
                )
            else:
                system_prompt = "你是一位大学教授，基于给定的PPT页面图像回答学生的问题，回答要准确且尽量简洁。"
                user_prompt = []
                if image_base64:
                    user_prompt.append(
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{image_base64}"
                            },
                        }
                    )
                user_prompt.append(
                    {
                        "type": "text",
                        "text": f"学生提问：{user_question}\n请基于PPT直接回答，必要时指出无法从讲稿得到信息。",
                    }
                )

            text_queue = asyncio.Queue()
            out_queue = asyncio.Queue()

            async def run_llm():
                try:
                    async for event in llm_service.stream_explanation(
                        system_prompt, user_prompt, page_num
                    ):
                        # 将 LLM 事件推送到前端
                        await out_queue.put(event)
                        # 将文本送入 TTS 队列
                        if event.get("type") == "text":
                            await text_queue.put(event.get("data"))
                    # LLM 完成后，通知 TTS 输入流结束
                    await text_queue.put("<END>")
                except Exception as e:
                    logger.error(f"LLM 流式任务异常: {e}", exc_info=True)
                    await out_queue.put({"type": "error", "message": str(e)})

            async def run_tts():
                try:

                    async def tts_input_stream():
                        while True:
                            chunk = await text_queue.get()
                            if chunk == "<END>":
                                yield {"type": "end"}
                                break
                            yield {"type": "text", "data": chunk}

                    async for audio_event in tts_service.stream_tts_input(
                        tts_input_stream(), page_num
                    ):
                        await out_queue.put(audio_event)
                except Exception as e:
                    logger.error(f"TTS 流式任务异常: {e}", exc_info=True)
                    await out_queue.put({"type": "error", "message": str(e)})
                finally:
                    await out_queue.put("<DONE>")

            llm_task = asyncio.create_task(run_llm())
            # 稍微等待 LLM 启动以降低冷启动抖动
            await asyncio.sleep(0.05)
            tts_task = asyncio.create_task(run_tts())

            try:
                while True:
                    event = await out_queue.get()
                    if event == "<DONE>":
                        break
                    yield f"data: {json.dumps(event)}\n\n"
            finally:
                if llm_task and not llm_task.done():
                    llm_task.cancel()
                if tts_task and not tts_task.done():
                    tts_task.cancel()

            yield "data: [DONE]\n\n"

        except Exception as e:
            logger.error(f"流式QA发生异常: {e}", exc_info=True)
            yield f"data: {json.dumps({'type':'error','message':str(e),'ts':time.time()})}\n\n"

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
