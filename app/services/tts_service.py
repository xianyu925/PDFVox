import asyncio
import json
import logging
import uuid
import re
import copy
from pathlib import Path
from typing import List
import base64
import socket
import time

import websockets

from app.config import settings
from protocols import (
    EventType,
    MsgType,
    MsgTypeFlagBits,
    start_connection,
    start_session,
    finish_session,
    finish_connection,
    task_request,
    receive_message,
    wait_for_event,
)

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
    logging.basicConfig(level=logging.CRITICAL)
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.CRITICAL)


class TTSService:
    def __init__(self):
        self.output_dir = Path("output")
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.appid = settings.API_APP_KEY
        self.access_token = settings.ACCESS_TOKEN
        self.voice_type = settings.TTS_VOICE
        self.endpoint = "wss://openspeech.bytedance.com/api/v3/tts/bidirection"

    async def _connect(self):
        import os
        import ssl

        proxy_vars = [
            "http_proxy",
            "https_proxy",
            "all_proxy",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
        ]
        for var in proxy_vars:
            if var in os.environ:
                del os.environ[var]

        os.environ["no_proxy"] = "openspeech.bytedance.com"

        headers = {
            "X-Api-App-Key": self.appid,
            "X-Api-Access-Key": self.access_token,
            "X-Api-Resource-Id": "seed-tts-2.0",
            "X-Api-Connect-Id": str(uuid.uuid4()),
        }

        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

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
        await finish_session(ws, session_id)

        while True:
            msg = await asyncio.wait_for(receive_message(ws), timeout=15.0)
            if msg.type == MsgType.AudioOnlyServer:
                pcm.extend(msg.payload)
            elif msg.type == MsgType.FullServerResponse:
                if msg.event == EventType.SessionFinished:
                    break

        if pcm:
            b64 = base64.b64encode(bytes(pcm)).decode("utf-8")
            logger.info(
                f"[TTS] 第{idx}句完成: {len(pcm)}字节PCM, text='{sentence[:40]}...'"
            )
            return {
                "type": "audio",
                "data": b64,
                "page": page_num,
                "sentence": sentence,
                "ts": time.time(),
            }
        else:
            logger.warning(f"[TTS] 第{idx}句PCM为空: '{sentence[:40]}...'")
            return None

    async def stream_tts_input(self, text_stream, page_num=1):
        import websockets.exceptions

        logger.info(
            f"[TTS服务] 准备处理页面 {page_num}，等待大模型首字..."
        )

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
            return

        if not first_text.strip() and is_end:
            logger.info(f"[TTS服务] 页面 {page_num} 文本为空，无需生成语音")
            return

        logger.info("[TTS服务] 首字就绪，建立 WebSocket 连接...")

        try:
            ws = await self._connect()

            base_request = {
                "user": {"uid": str(uuid.uuid4())},
                "namespace": "BidirectionalTTS",
                "req_params": {
                    "speaker": self.voice_type,
                    "audio_params": {
                        "format": "pcm",
                        "sample_rate": 24000,
                        "enable_timestamp": True,
                    },
                },
            }

            sentence_queue = asyncio.Queue()

            async def text_splitter():
                try:
                    buffer = first_text
                    delimiters = set("。！？，；\n.!?,;")
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
                                sent = buffer_in[:last_delim_idx + 1].strip()
                                buffer_in = buffer_in[last_delim_idx + 1:]
                            elif force_flush or len(buffer_in) >= 60:
                                sent = (
                                    buffer_in[:60].strip()
                                    if len(buffer_in) >= 60 and not force_flush
                                    else buffer_in.strip()
                                )
                                buffer_in = buffer_in[len(sent):]
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

                    logger.info(
                        f"[TTS分句] 第{page_num}页共 {sentence_count} 个句子"
                    )
                except Exception as e:
                    logger.error(f"[TTS分句] 异常: {e}", exc_info=True)
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

                idx += 1
                try:
                    result = await self._synthesize_sentence(
                        ws, base_request, sentence, page_num, idx
                    )
                    if result:
                        yield result
                except Exception as e:
                    logger.error(
                        f"[TTS] 第{idx}句合成失败: {e}", exc_info=True
                    )

            logger.info(f"[TTS] 页面{page_num}完成，共同成 {idx} 句语音")

            try:
                await asyncio.wait_for(splitter_task, timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
            try:
                await finish_connection(ws)
            except Exception:
                pass
            try:
                await ws.close()
            except Exception:
                pass

        except Exception as e:
            logger.error(f"流式TTS生成发生异常: {str(e)}", exc_info=True)
            yield {"type": "error", "message": f"TTS报错: {str(e)}"}
