import asyncio
import json
import time

from fastapi import APIRouter, UploadFile, File, Form
from fastapi.responses import StreamingResponse

from app.services.asr_service import ASRService
from app.services.explain_service import ExplainService
from app.services.llm_service import LLMService
from app.services.tts_service import TTSService
from app.services.qa_service import QAService
from app.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()
asr_service = ASRService()
explain_service = ExplainService()
llm_service = LLMService()
tts_service = TTSService()
qa_service = QAService(llm_service, tts_service, explain_service)


def _extract_pcm(data: bytes) -> bytes:
    """从 WAV 或原始数据中提取 PCM。"""
    if len(data) >= 12 and data[0:4] == b"RIFF":
        idx = data.find(b"data")
        return data[idx + 8:] if idx != -1 else data
    return data


@router.post("/ask/stream")
async def ask_question_stream(
    file: UploadFile = File(None),
    question: str = Form(None),
    file_id: str = Form(None),
    page_num: int = Form(1),
):
    """流式问答：接收音频/文本问题 → ASR转写 → LLM流式 + TTS语音 → SSE下发。"""

    async def generate_stream():
        try:
            # 1. 解析用户问题（音频→ASR转写 或 直接使用文本）
            if file is not None:
                data = await file.read()
                pcm = _extract_pcm(data)
                transcript = await asr_service.transcribe_pcm_to_text(pcm)
                logger.info(f"ASR 转写得到: {transcript}")
            else:
                transcript = ""

            if not question and not transcript:
                yield f"data: {json.dumps({'type': 'error', 'message': '语音识别未能获取到文本，请确保麦克风正常并重试'})}\n\n"
                return

            user_question = question if question else transcript

            if not file_id:
                yield f"data: {json.dumps({'type': 'error', 'message': '需要提供 file_id'})}\n\n"
                return

            # 2. 后台触发该页完整讲稿的生成（不阻塞问答主流程）
            asyncio.create_task(
                explain_service.get_full_script(file_id, page_num)
            )

            # 3. 流式问答主流程
            async for event in qa_service.stream_qa_response(
                file_id, page_num, user_question
            ):
                yield f"data: {json.dumps(event)}\n\n"

            yield "data: [DONE]\n\n"

        except Exception as e:
            logger.error(f"流式QA发生异常: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e), 'ts': time.time()})}\n\n"

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
