import asyncio
import copy
import json
import logging
import uuid
from pathlib import Path

import websockets

from app.config import settings
from protocols import (
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

# 配置日志
if settings.ENABLE_LOGGING:
    logging.basicConfig(
        level=logging.DEBUG,  # 设置为DEBUG以显示所有日志
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger = logging.getLogger(__name__)
else:
    # 只显示错误日志
    logging.basicConfig(level=logging.ERROR)
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.ERROR)


class TTSService:
    def __init__(self):
        self.output_dir = Path("output")
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.appid = settings.API_APP_KEY
        self.access_token = settings.ACCESS_TOKEN
        self.voice_type = settings.TTS_VOICE

        self.endpoint = "wss://openspeech.bytedance.com/api/v3/tts/bidirection"

    async def tts_page_async(self, file_id: str, page: int, text: str) -> str:
        output_path = self.output_dir / f"{file_id}_page_{page}.mp3"

        headers = {
            "X-Api-App-Key": self.appid,
            "X-Api-Access-Key": self.access_token,
            "X-Api-Resource-Id": "seed-tts-2.0",
            "X-Api-Connect-Id": str(uuid.uuid4()),
        }

        logger.info(f"Connecting to {self.endpoint}")

        try:
            websocket = await websockets.connect(
                self.endpoint,
                additional_headers=headers,
                max_size=10 * 1024 * 1024,
            )

            logger.info(
                f"Connected. Logid: {websocket.response.headers.get('x-tt-logid')}"
            )

            try:
                # ✅ 1. 启动连接（协议版本）
                await start_connection(websocket)
                await wait_for_event(
                    websocket,
                    MsgType.FullServerResponse,
                    EventType.ConnectionStarted,
                )

                sentences = text.split("。")
                audio_data = bytearray()

                for sentence in sentences:
                    if not sentence.strip():
                        continue

                    # ✅ 基础请求参数
                    base_request = {
                        "user": {"uid": str(uuid.uuid4())},
                        "namespace": "BidirectionalTTS",
                        "req_params": {
                            "speaker": self.voice_type,
                            "audio_params": {
                                "format": "mp3",
                                "sample_rate": 24000,
                                "enable_timestamp": True,
                            },
                            "additions": json.dumps({"disable_markdown_filter": False}),
                        },
                    }

                    session_id = str(uuid.uuid4())

                    # ✅ 2. 启动 session（协议）
                    start_req = copy.deepcopy(base_request)
                    start_req["event"] = EventType.StartSession

                    await start_session(
                        websocket,
                        json.dumps(start_req).encode(),
                        session_id,
                    )

                    await wait_for_event(
                        websocket,
                        MsgType.FullServerResponse,
                        EventType.SessionStarted,
                    )

                    # ✅ 3. 发送文本（逐字流式）
                    async def send_text():
                        for ch in sentence:
                            req = copy.deepcopy(base_request)
                            req["event"] = EventType.TaskRequest
                            req["req_params"]["text"] = ch

                            await task_request(
                                websocket,
                                json.dumps(req).encode(),
                                session_id,
                            )
                            await asyncio.sleep(0.005)

                        await finish_session(websocket, session_id)

                    send_task = asyncio.create_task(send_text())

                    # ✅ 4. 接收音频（二进制协议）
                    while True:
                        msg = await receive_message(websocket)

                        if msg.type == MsgType.FullServerResponse:
                            if msg.event == EventType.SessionFinished:
                                break

                        elif msg.type == MsgType.AudioOnlyServer:
                            audio_data.extend(msg.payload)

                        else:
                            raise RuntimeError(f"TTS failed: {msg}")

                    await send_task

                # ✅ 5. 保存音频
                if not audio_data:
                    raise RuntimeError("No audio received")

                with open(output_path, "wb") as f:
                    f.write(audio_data)

                logger.info(f"Saved audio: {output_path}")
                return str(output_path)

            finally:
                # ✅ 6. 关闭连接
                await finish_connection(websocket)
                await wait_for_event(
                    websocket,
                    MsgType.FullServerResponse,
                    EventType.ConnectionFinished,
                )
                await websocket.close()

        except Exception as e:
            logger.error(f"TTS error: {e}", exc_info=True)
            return ""

    def tts_page(self, file_id: str, page: int, text: str) -> str:
        return asyncio.run(self.tts_page_async(file_id, page, text))

    def generate_and_get_audio(self, file_id: str, page: int, text: str) -> str:
        if not text:
            raise ValueError("Empty text for TTS")

        return self.tts_page(file_id, page, text)

    def get_audio_path(self, file_id: str, page: int) -> str:
        path = self.output_dir / f"{file_id}_page_{page}.mp3"
        return str(path) if path.exists() else ""

    def merge_audio_files(self, file_id: str, page_count: int) -> str:
        """合并多个音频文件为一个

        Args:
            file_id: 文件ID
            page_count: 页面数量

        Returns:
            str: 合并后的音频文件路径
        """
        output_path = self.output_dir / f"{file_id}_merged.mp3"

        # 收集所有音频文件路径
        audio_files = []
        for page in range(1, page_count + 1):
            audio_path = self.output_dir / f"{file_id}_page_{page}.mp3"
            if audio_path.exists():
                audio_files.append(str(audio_path))

        if not audio_files:
            logger.error("No audio files found to merge")
            return ""

        try:
            # 尝试使用pydub库合并音频文件
            from pydub import AudioSegment

            # 加载第一个音频文件
            combined = AudioSegment.from_mp3(audio_files[0])

            # 逐个添加其他音频文件
            for audio_file in audio_files[1:]:
                sound = AudioSegment.from_mp3(audio_file)
                combined += sound

            # 导出合并后的音频
            combined.export(str(output_path), format="mp3")

            logger.info(f"Merged audio saved to: {output_path}")
            return str(output_path)
        except Exception as e:
            logger.error(f"Failed to merge audio files: {str(e)}", exc_info=True)
            return ""

    def get_audio_url(self, file_id: str, page: int) -> str:
        return f"/audio/{file_id}/page/{page}"

    def get_merged_audio_url(self, file_id: str) -> str:
        return f"/audio/{file_id}/merged"
