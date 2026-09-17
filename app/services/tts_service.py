import asyncio
import base64
import copy
import json
import socket
import time
import uuid
import wave
from pathlib import Path

import websockets

from app.config import settings
from app.utils.logging import get_logger
from app.services.protocols import (
    EventType,
    MsgType,
    start_connection,
    start_session,
    finish_session,
    finish_connection,
    task_request,
    receive_message,
    wait_for_event,
)

logger = get_logger(__name__)


class TTSService:
    def __init__(self):
        self.apikey = settings.TTS_API_KEY
        self.voice_type = settings.TTS_VOICE
        self.api_resource_id = settings.TTS_API_RESOURCE_ID
        self.endpoint = "wss://openspeech.bytedance.com/api/v3/tts/bidirection"

    @staticmethod
    def _parse_word_timestamps(payload):
        """Normalize both legacy and Speech 2.0 timestamp payloads."""
        words = payload.get("words") or payload.get("word_boundary") or []
        timestamps = []
        for word in words:
            char = word.get("word") or word.get("text") or ""
            start = word.get("startTime", word.get("start_time"))
            end = word.get("endTime", word.get("end_time"))
            if not char or start is None or end is None:
                continue
            timestamps.append(
                {
                    "char": char,
                    "start": round(float(start), 3),
                    "end": round(float(end), 3),
                }
            )
        return timestamps

    async def _connect(self):
        import ssl

        headers = {
            "X-Api-Key": self.apikey,
            "X-Api-Resource-Id": self.api_resource_id,
            "X-Api-Connect-Id": str(uuid.uuid4()),
        }

        ssl_context = ssl.create_default_context()

        try:
            ws = await websockets.connect(
                self.endpoint,
                additional_headers=headers,
                open_timeout=30,
                ping_interval=15,
                ping_timeout=15,
                ssl=ssl_context,
                family=socket.AF_INET,
            )
        except Exception as e:
            logger.error(f"WebSocket连接失败: {e}")
            raise

        await start_connection(ws)
        await asyncio.wait_for(
            wait_for_event(ws, MsgType.FullServerResponse, EventType.ConnectionStarted),
            timeout=10.0,
        )
        return ws

    async def _synthesize_sentence(self, ws, base_request, sentence, page_num, idx):
        session_id = str(uuid.uuid4())

        start_req = copy.deepcopy(base_request)
        start_req["event"] = EventType.StartSession

        await start_session(ws, json.dumps(start_req).encode(), session_id)
        await asyncio.wait_for(
            wait_for_event(ws, MsgType.FullServerResponse, EventType.SessionStarted),
            timeout=10.0,
        )

        req = copy.deepcopy(base_request)
        req["event"] = EventType.TaskRequest
        req["req_params"]["text"] = sentence
        await task_request(ws, json.dumps(req).encode(), session_id)

        pcm = bytearray()
        word_boundary = []
        await finish_session(ws, session_id)

        while True:
            msg = await asyncio.wait_for(receive_message(ws), timeout=15.0)
            if msg.type == MsgType.AudioOnlyServer:
                pcm.extend(msg.payload)
            elif msg.type == MsgType.FullServerResponse:
                if msg.event == EventType.SessionFinished:
                    break
                elif msg.event in (
                    EventType.TTSResponse,
                    EventType.TTSSubtitle,
                    EventType.TTSSentenceEnd,
                ):
                    payload = json.loads(msg.payload.decode("utf-8"))
                    parsed_timestamps = self._parse_word_timestamps(payload)
                    if parsed_timestamps:
                        word_boundary = parsed_timestamps

        if pcm:
            b64 = base64.b64encode(bytes(pcm)).decode("utf-8")
            duration = round(len(pcm) / 2 / 24000, 3)
            logger.info(
                f"[TTS] 第{idx}句完成: {len(pcm)}字节PCM, {duration}s,"
                f" text='{sentence[:40]}...'"
            )
            return {
                "type": "audio",
                "data": b64,
                "page": page_num,
                "index": idx,
                "sentence": sentence,
                "duration": duration,
                "word_timestamps": word_boundary,
                "ts": time.time(),
            }
        else:
            logger.warning(f"[TTS] 第{idx}句PCM为空: '{sentence[:40]}...'")
            return None

    async def stream_tts_input(self, text_stream, page_num=1):
        logger.info(
            f"[TTS服务] 准备处理页面 {page_num}，预连接 WebSocket 同时等待首字..."
        )

        # 预建 WebSocket 连接，与 LLM 首字等待并发
        connect_task = asyncio.create_task(self._connect())

        first_text = ""
        is_end = False

        try:
            async for chunk in text_stream:
                if chunk.get("type") == "text":
                    first_text += chunk.get("data", "")
                    if first_text.strip():
                        break
                elif chunk.get("type") == "end":
                    is_end = True
                    break
        except Exception as e:
            logger.error(f"[TTS服务] 等待首字异常: {e}")
            connect_task.cancel()
            await asyncio.gather(connect_task, return_exceptions=True)
            yield {
                "type": "error",
                "message": f"TTS input failed: {e}",
                "page": page_num,
            }
            return

        if not first_text.strip() and is_end:
            logger.info(f"[TTS服务] 页面 {page_num} 文本为空，无需生成语音")
            connect_task.cancel()
            await asyncio.gather(connect_task, return_exceptions=True)
            return

        logger.info("[TTS服务] 首字就绪，等待 WebSocket 连接就绪...")

        ws = None
        splitter_task = None
        try:
            ws = await connect_task

            base_request = {
                "user": {"uid": str(uuid.uuid4())},
                "namespace": "BidirectionalTTS",
                "req_params": {
                    "speaker": self.voice_type,
                    "audio_params": {
                        "format": "pcm",
                        "sample_rate": 24000,
                        "enable_timestamp": True,
                        "enable_subtitle": True,
                    },
                },
            }

            sentence_queue = asyncio.Queue()

            async def text_splitter():
                try:
                    buffer = first_text
                    delimiters = set("。！？，；\n!?,;")
                    sentence_count = 0

                    async def extract(buffer_in, force_flush=False):
                        nonlocal sentence_count
                        while len(buffer_in) > 0:
                            last_delim_idx = -1
                            for i in range(len(buffer_in) - 1, -1, -1):
                                if buffer_in[i] in delimiters:
                                    last_delim_idx = i
                                    break

                            if last_delim_idx != -1:
                                sent = buffer_in[: last_delim_idx + 1].strip()
                                buffer_in = buffer_in[last_delim_idx + 1 :]
                            elif force_flush or len(buffer_in) >= 60:
                                sent = (
                                    buffer_in[:60].strip()
                                    if len(buffer_in) >= 60 and not force_flush
                                    else buffer_in.strip()
                                )
                                buffer_in = buffer_in[len(sent) :]
                            else:
                                break

                            if sent:
                                sentence_count += 1
                                await sentence_queue.put(sent)

                        return buffer_in

                    buffer = await extract(buffer)

                    if not is_end:
                        async for text_chunk in text_stream:
                            if text_chunk.get("type") == "text":
                                buffer += text_chunk.get("data", "")
                                buffer = await extract(buffer)
                            elif text_chunk.get("type") == "end":
                                break

                    await extract(buffer, force_flush=True)

                    logger.info(f"[TTS分句] 第{page_num}页共 {sentence_count} 个句子")
                except Exception as e:
                    logger.error(f"[TTS分句] 异常: {e}", exc_info=True)
                    await sentence_queue.put(e)
                finally:
                    await sentence_queue.put(None)

            splitter_task = asyncio.create_task(text_splitter())

            idx = 0
            while True:
                try:
                    sentence = await asyncio.wait_for(
                        sentence_queue.get(), timeout=120.0
                    )
                except asyncio.TimeoutError:
                    logger.error("[TTS] 等待句子超时，强制终止")
                    break

                if sentence is None:
                    break

                if isinstance(sentence, Exception):
                    yield {
                        "type": "error",
                        "message": f"TTS text splitting failed: {sentence}",
                        "page": page_num,
                    }
                    break

                idx += 1
                try:
                    result = await self._synthesize_sentence(
                        ws, base_request, sentence, page_num, idx
                    )
                    if result:
                        yield result
                    else:
                        yield {
                            "type": "error",
                            "message": "TTS returned empty audio",
                            "page": page_num,
                        }
                        break
                except Exception as e:
                    logger.error(f"[TTS] 第{idx}句合成失败: {e}", exc_info=True)
                    yield {
                        "type": "error",
                        "message": f"TTS synthesis failed: {e}",
                        "page": page_num,
                    }
                    break

            logger.info(f"[TTS] 页面{page_num}完成，共同成 {idx} 句语音")

        except Exception as e:
            logger.error(f"流式TTS生成发生异常: {str(e)}", exc_info=True)
            yield {
                "type": "error",
                "message": f"TTS error: {str(e)}",
                "page": page_num,
            }
        finally:
            if splitter_task is not None and not splitter_task.done():
                splitter_task.cancel()
                await asyncio.gather(splitter_task, return_exceptions=True)
            if not connect_task.done():
                connect_task.cancel()
                await asyncio.gather(connect_task, return_exceptions=True)
            if ws is not None:
                try:
                    await finish_connection(ws)
                except Exception:
                    pass
                try:
                    await ws.close()
                except Exception:
                    pass

    async def synthesize_to_wav(self, text: str, output_path):
        """Synthesize text into a mono 24 kHz, 16-bit PCM WAV file."""
        if not text or not text.strip():
            raise ValueError("text must not be empty")

        async def text_stream():
            yield {"type": "text", "data": text}
            yield {"type": "end"}

        pcm = bytearray()
        async for event in self.stream_tts_input(text_stream()):
            if event.get("type") == "error":
                raise RuntimeError(event.get("message", "TTS synthesis failed"))
            if event.get("type") == "audio":
                pcm.extend(base64.b64decode(event["data"]))

        if not pcm:
            raise RuntimeError("TTS returned no audio")

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        def write_wav():
            with wave.open(str(path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(24000)
                wav_file.writeframes(bytes(pcm))

        await asyncio.to_thread(write_wav)
        return path
