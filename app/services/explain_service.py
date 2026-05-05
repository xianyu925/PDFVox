import logging
import time
import asyncio
from app.services.pdf_service import PDFService
from app.services.llm_service import LLMService
from app.services.tts_service import TTSService
from app.models.db import get_upload
from app.config import settings

# 配置日志
if settings.ENABLE_LOGGING:
    # 创建文件处理器，将日志写入log.txt文件
    file_handler = logging.FileHandler("log.txt", encoding="utf-8")
    file_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    file_handler.setFormatter(file_formatter)

    # 创建控制台处理器
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
    # 禁用日志
    logging.basicConfig(level=logging.CRITICAL)
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.CRITICAL)


class ExplainService:
    def __init__(self):
        self.pdf_service = PDFService()
        self.llm_service = LLMService()
        self.tts_service = TTSService()
        self.summary_cache = {}
        self.page_audio_cache = {}
        self._cancel_tokens: dict[str, bool] = {}

    def cancel_stream(self, file_id: str):
        self._cancel_tokens[file_id] = True
        logger.info(f"[取消令牌] file_id={file_id} 的流式生成已被标记取消")

    def _is_cancelled(self, file_id: str) -> bool:
        return self._cancel_tokens.get(file_id, False)

    def _reset_cancel(self, file_id: str):
        self._cancel_tokens.pop(file_id, None)

    async def _ensure_single_summary(
        self, file_id: str, page_num: int, pdf_path: str, course_name: str
    ) -> str:
        if file_id not in self.summary_cache:
            self.summary_cache[file_id] = {}
        if page_num in self.summary_cache[file_id]:
            return self.summary_cache[file_id][page_num]

        try:
            image_base64 = await asyncio.to_thread(
                self.pdf_service.get_page_image, pdf_path, page_num
            )
            system_prompt = (
                "你是一位大学教授，请为PPT页面生成不超过100字的核心概念摘要。"
            )
            user_prompt = [
                {
                    "type": "text",
                    "text": f"请为{course_name}第{page_num}页生成摘要：1.突出核心 2.不超过100字 3.无冗余",
                },
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{image_base64}"},
                },
            ]
            summary = await asyncio.to_thread(
                self.llm_service.generate_explanation,
                system_prompt,
                user_prompt,
                max_tokens=200,
            )
            self.summary_cache[file_id][page_num] = summary
            return summary
        except Exception as e:
            logger.error(f"第{page_num}页摘要生成失败: {e}")
            return ""

    async def _get_context_summaries(
        self, file_id, page_num, pdf_path, total_pages, course_name
    ):
        tasks = {}
        if page_num > 1:
            tasks[page_num - 1] = self._ensure_single_summary(
                file_id, page_num - 1, pdf_path, course_name
            )
        if page_num < total_pages:
            tasks[page_num + 1] = self._ensure_single_summary(
                file_id, page_num + 1, pdf_path, course_name
            )

        if tasks:
            results = await asyncio.gather(*tasks.values())
            res_dict = dict(zip(tasks.keys(), results))
        else:
            res_dict = {}

        return res_dict.get(page_num - 1, ""), res_dict.get(page_num + 1, "")

    async def explain_page_realtime_stream(
        self,
        file_id: str,
        page_num: int,
        total_pages: int = 0,
        course_name: str = "机器学习导论",
    ):
        logger.info(f"开始流式生成讲解 - 页面 {page_num}")
        yield {"type": "start", "page": page_num, "ts": time.time()}

        llm_task = None
        tts_task = None

        try:
            upload = get_upload(file_id)
            if not upload or not upload.get("path"):
                raise ValueError("PDF记录或路径不存在")
            pdf_path = upload.get("path")

            if not total_pages:
                total_pages = upload.get("total_pages", 1)

            prev_summary, next_summary = await self._get_context_summaries(
                file_id, page_num, pdf_path, total_pages, course_name
            )
            image_base64 = await asyncio.to_thread(
                self.pdf_service.get_page_image, pdf_path, page_num
            )

            system_prompt = "你是一位大学教授。请以专业、口语化、清晰的方式讲解PPT。讲解要连贯，适合大学生理解。"
            prompt_text = f"请为{course_name}第{page_num}页生成讲解稿：\n要求：口语化、讲透核心概念、不要出现任何Markdown符号(如**)、不要描写动作神态。\n"
            if prev_summary:
                prompt_text += f"【承上】上一页内容是: {prev_summary}\n"
            if next_summary:
                prompt_text += f"【启下】下一页内容是: {next_summary}\n"

            user_prompt = [
                {"type": "text", "text": prompt_text},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{image_base64}"},
                },
            ]

            text_queue = asyncio.Queue()
            out_queue = asyncio.Queue()

            async def run_llm():
                try:
                    async for event in self.llm_service.stream_explanation(
                        system_prompt, user_prompt, page_num
                    ):
                        if self._is_cancelled(file_id):
                            logger.info(f"[LLM] 检测到取消令牌，终止第{page_num}页生成")
                            break
                        if event.get("type") == "text":
                            await text_queue.put(event["data"])

                except Exception as e:
                    logger.error(f"LLM 任务异常: {e}", exc_info=True)
                finally:
                    await text_queue.put("<END>")

            async def run_tts():
                try:

                    async def tts_input_stream():
                        while True:
                            if self._is_cancelled(file_id):
                                logger.info(f"[TTS输入] 检测到取消令牌，终止第{page_num}页传输")
                                yield {"type": "end"}
                                break
                            try:
                                chunk = await asyncio.wait_for(
                                    text_queue.get(), timeout=120.0
                                )
                                if chunk == "<END>":
                                    yield {"type": "end"}
                                    break
                                yield {"type": "text", "data": chunk}
                            except asyncio.TimeoutError:
                                logger.error(
                                    "[TTS输入流] 等待文本长达 120s 依然为空，大模型可能已宕机，强制切断"
                                )
                                yield {"type": "end"}
                                break

                    async for audio_event in self.stream_page_sentences(
                        file_id, page_num, tts_input_stream()
                    ):
                        await out_queue.put(audio_event)

                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.error(f"TTS 任务异常: {e}", exc_info=True)
                finally:
                    await out_queue.put("<DONE>")

            # 并发启动
            llm_task = asyncio.create_task(run_llm())
            await asyncio.sleep(0.1)
            tts_task = asyncio.create_task(run_tts())

            try:
                while True:
                    if self._is_cancelled(file_id):
                        logger.info(f"[主循环] 检测到取消令牌，终止第{page_num}页推流")
                        break
                    # 【极度关键】：主通信队列排队也延长到 120 秒，避免被大模型延迟连累
                    event = await asyncio.wait_for(out_queue.get(), timeout=120.0)
                    if event == "<DONE>":
                        break
                    yield event
            except asyncio.TimeoutError:
                logger.error("前台下发队列超时 120 秒，强制重置")
                yield {"type": "error", "message": "大模型响应严重超时，请重试"}
            except asyncio.CancelledError:
                logger.warning("客户端断开了SSE连接，关闭生成")
                raise
            finally:
                if llm_task and not llm_task.done():
                    llm_task.cancel()
                if tts_task and not tts_task.done():
                    tts_task.cancel()

            yield {"type": "end", "page": page_num, "ts": time.time()}

        except Exception as e:
            logger.error(f"流式调度彻底失败: {e}", exc_info=True)
            yield {"type": "error", "message": str(e), "page": page_num}

    async def get_full_script(
        self, file_id: str, page_num: int, course_name: str = "课程"
    ) -> str:
        """生成并返回该页的完整讲解稿（非流式），并做简单缓存。"""
        cache_key = f"script_{file_id}_{page_num}"
        if cache_key in self.summary_cache:
            return self.summary_cache[cache_key]

        upload = get_upload(file_id)
        if not upload or not upload.get("path"):
            raise ValueError("PDF记录或路径不存在")
        pdf_path = upload.get("path")

        # 获取上下文摘要
        prev_summary, next_summary = await self._get_context_summaries(
            file_id, page_num, pdf_path, upload.get("total_pages", 1), course_name
        )

        image_base64 = await asyncio.to_thread(
            self.pdf_service.get_page_image, pdf_path, page_num
        )

        system_prompt = "你是一位大学教授。请以专业、口语化、清晰的方式讲解PPT。讲解要连贯，适合大学生理解。"
        prompt_text = f"请为{course_name}第{page_num}页生成完整讲解稿：要求：口语化、讲透核心概念、不要出现任何Markdown符号。"
        if prev_summary:
            prompt_text += f"\n【承上】上一页内容是: {prev_summary}"
        if next_summary:
            prompt_text += f"\n【启下】下一页内容是: {next_summary}"

        user_prompt = [
            {"type": "text", "text": prompt_text},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{image_base64}"},
            },
        ]

        try:
            script = await asyncio.to_thread(
                self.llm_service.generate_explanation, system_prompt, user_prompt
            )
        except Exception as e:
            logger.error(f"生成讲解稿失败: {e}")
            script = ""

        # 缓存并返回
        self.summary_cache[cache_key] = script
        return script

    async def get_or_generate_page_sentences(
        self, text: str, file_id: str, page_num: int
    ):
        if file_id not in self.page_audio_cache:
            self.page_audio_cache[file_id] = {}

        if page_num in self.page_audio_cache[file_id]:
            logger.info(f"[页音频缓存命中] 第{page_num}页，直接返回缓存")
            return self.page_audio_cache[file_id][page_num], True

        logger.info(f"[页音频缓存未命中] 第{page_num}页，调用 TTS 逐句生成并缓存")

        sentences = []

        async def text_stream():
            yield {"type": "text", "data": text}
            yield {"type": "end"}

        async for event in self.tts_service.stream_tts_input(text_stream(), page_num):
            if event.get("type") == "audio" and event.get("data"):
                sentences.append({
                    "sentence": event.get("sentence", ""),
                    "audio": event.get("data", ""),
                })

        self.page_audio_cache[file_id][page_num] = sentences
        logger.info(
            f"[页音频缓存已存储] 第{page_num}页，共 {len(sentences)} 个句子"
        )
        return sentences, False

    async def stream_page_sentences(
        self, file_id: str, page_num: int, tts_text_stream
    ):
        if file_id not in self.page_audio_cache:
            self.page_audio_cache[file_id] = {}

        if page_num in self.page_audio_cache[file_id]:
            logger.info(f"[页音频流缓存命中] 第{page_num}页，直接推流缓存")
            for item in self.page_audio_cache[file_id][page_num]:
                yield {
                    "type": "audio",
                    "data": item["audio"],
                    "sentence": item["sentence"],
                    "page": page_num,
                }
            return

        sentences = []
        async for event in self.tts_service.stream_tts_input(tts_text_stream, page_num):
            if event.get("type") == "audio" and event.get("data"):
                sentences.append({
                    "sentence": event.get("sentence", ""),
                    "audio": event.get("data", ""),
                })
            yield event

        if sentences:
            self.page_audio_cache[file_id][page_num] = sentences
            logger.info(
                f"[页音频流已缓存] 第{page_num}页，共 {len(sentences)} 个句子"
            )
