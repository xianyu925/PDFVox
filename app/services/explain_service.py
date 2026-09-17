import time
import asyncio
import hashlib
import json
from app.config import settings
from app.services.pdf_service import PDFService
from app.services.llm_service import LLMService
from app.services.tts_service import TTSService
from app.services.cache import TTLCache
from app.services.explain_audio import (
    get_or_generate_page_sentences as generate_cached_page_audio,
    stream_page_sentences as stream_cached_page_audio,
)
from app.services.explain_prompts import (
    build_full_lecture_prompt,
    build_realtime_lecture_prompt,
    build_summary_prompt,
)
from app.models.db import (
    get_generated_cache,
    get_upload,
    save_generated_cache,
    update_upload_total_pages,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)


class ExplainService:
    def __init__(self):
        self.pdf_service = PDFService()
        self.llm_service = LLMService()
        self.tts_service = TTSService()
        self.summary_cache = TTLCache(
            settings.SUMMARY_CACHE_MAX_ENTRIES, settings.CACHE_TTL_SECONDS
        )
        self.page_audio_cache = TTLCache(
            settings.AUDIO_CACHE_MAX_ENTRIES, settings.CACHE_TTL_SECONDS
        )
        self._cancel_tokens: dict[tuple[str, str], bool] = {}

    @staticmethod
    def _cache_key(kind: str, file_id: str, page_num: int, course_name: str) -> str:
        identity = json.dumps(
            {
                "kind": kind,
                "file_id": file_id,
                "page": page_num,
                "course": course_name,
                "llm_model": settings.LLM_MODEL,
                "tts_voice": settings.TTS_VOICE if kind == "audio" else "",
                "tts_resource": settings.TTS_API_RESOURCE_ID if kind == "audio" else "",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return f"{kind}:{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"

    async def _cache_get(self, cache, cache_key):
        value = cache.get(cache_key)
        if value is not None:
            return value
        value = await asyncio.to_thread(get_generated_cache, cache_key)
        if value is not None:
            cache[cache_key] = value
        return value

    async def _cache_set(self, cache, cache_key, kind, value):
        cache[cache_key] = value
        await asyncio.to_thread(
            save_generated_cache,
            cache_key,
            kind,
            value,
            settings.CACHE_TTL_SECONDS,
            settings.GENERATED_CACHE_MAX_ENTRIES,
        )

    def cancel_stream(self, file_id: str, session_id: str = "default"):
        self._cancel_tokens[(file_id, session_id)] = True
        logger.info(f"[取消令牌] file_id={file_id} 的流式生成已被标记取消")

    def _is_cancelled(self, file_id: str, session_id: str = "default") -> bool:
        return self._cancel_tokens.get((file_id, session_id), False)

    def _reset_cancel(self, file_id: str, session_id: str = "default"):
        self._cancel_tokens.pop((file_id, session_id), None)

    async def resolve_total_pages(self, upload: dict) -> int:
        """Return persisted page count, backfilling records created by older versions."""
        total_pages = upload.get("total_pages")
        if total_pages:
            return int(total_pages)

        pdf_path = upload.get("path")
        if not pdf_path:
            raise ValueError("PDF记录或路径不存在")
        total_pages = await asyncio.to_thread(
            self.pdf_service.get_page_count, pdf_path
        )
        if upload.get("file_id"):
            await asyncio.to_thread(
                update_upload_total_pages, upload["file_id"], total_pages
            )
        return total_pages

    async def prefetch_summary(
        self, file_id: str, page_num: int, pdf_path: str, course_name: str
    ) -> None:
        """后台预取单页摘要到缓存，供相邻页讲解使用。"""
        await self._ensure_single_summary(
            file_id, page_num, pdf_path, course_name
        )

    async def _ensure_single_summary(
        self, file_id: str, page_num: int, pdf_path: str, course_name: str
    ) -> str:
        cache_key = self._cache_key("summary", file_id, page_num, course_name)
        cached = await self._cache_get(self.summary_cache, cache_key)
        if cached is not None:
            return cached

        try:
            image_base64 = await asyncio.to_thread(
                self.pdf_service.get_page_image, pdf_path, page_num
            )
            system_prompt, user_prompt = build_summary_prompt(
                course_name, page_num, image_base64
            )
            summary = await asyncio.to_thread(
                self.llm_service.generate_explanation,
                system_prompt,
                user_prompt,
                max_tokens=200,
            )
            if summary:
                await self._cache_set(
                    self.summary_cache, cache_key, "summary", summary
                )
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
        session_id: str = "default",
        skip_sentences: int = 0,
        force_regenerate: bool = False,
    ):
        logger.info(f"开始流式生成讲解 - 页面 {page_num}")
        yield {"type": "start", "page": page_num, "ts": time.time()}

        llm_task = None
        tts_task = None

        try:
            upload = await asyncio.to_thread(get_upload, file_id)
            if not upload or not upload.get("path"):
                raise ValueError("PDF记录或路径不存在")
            pdf_path = upload.get("path")

            if not total_pages:
                total_pages = await self.resolve_total_pages(upload)

            # 图片与相邻页摘要并发，图片必须等，摘要用超时兜底（不阻塞主流程）
            summaries_task = asyncio.create_task(
                self._get_context_summaries(
                    file_id, page_num, pdf_path, total_pages, course_name
                )
            )
            image_task = asyncio.create_task(
                asyncio.to_thread(
                    self.pdf_service.get_page_image, pdf_path, page_num
                )
            )
            image_base64 = await image_task
            try:
                prev_summary, next_summary = await asyncio.wait_for(
                    summaries_task, timeout=3.0
                )
            except asyncio.TimeoutError:
                logger.info(
                    f"第{page_num}页相邻摘要未在 3s 内完成，跳过上下文直接开始讲解"
                )
                prev_summary, next_summary = "", ""

            system_prompt, user_prompt = build_realtime_lecture_prompt(
                course_name,
                page_num,
                total_pages,
                image_base64,
                prev_summary,
                next_summary,
            )

            text_queue = asyncio.Queue()
            out_queue = asyncio.Queue()

            async def run_llm():
                try:
                    async for event in self.llm_service.stream_explanation(
                        system_prompt, user_prompt, page_num
                    ):
                        if self._is_cancelled(file_id, session_id):
                            logger.info(f"[LLM] 检测到取消令牌，终止第{page_num}页生成")
                            break
                        if event.get("type") == "text":
                            await text_queue.put(event["data"])
                        elif event.get("type") == "error":
                            error_data = event.get("data") or {}
                            message = (
                                error_data.get("error")
                                if isinstance(error_data, dict)
                                else str(error_data)
                            )
                            await out_queue.put(
                                {
                                    "type": "error",
                                    "message": message or "讲解生成失败，请稍后重试",
                                    "page": page_num,
                                }
                            )

                except Exception as e:
                    logger.error(f"LLM 任务异常: {e}", exc_info=True)
                    await out_queue.put(
                        {
                            "type": "error",
                            "message": "讲解生成失败，请稍后重试",
                            "page": page_num,
                        }
                    )
                finally:
                    await text_queue.put("<END>")

            async def run_tts():
                try:

                    async def tts_input_stream():
                        while True:
                            if self._is_cancelled(file_id, session_id):
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

                    audio_index = 0
                    async for audio_event in self.stream_page_sentences(
                        file_id,
                        page_num,
                        tts_input_stream(),
                        course_name,
                        use_cache=not force_regenerate,
                        session_id=session_id,
                    ):
                        if audio_event.get("type") == "audio":
                            audio_index += 1
                            audio_event = {
                                **audio_event,
                                "index": audio_event.get("index", audio_index),
                            }
                            if audio_index <= skip_sentences:
                                continue
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

            page_duration = 0.0
            try:
                while True:
                    if self._is_cancelled(file_id, session_id):
                        logger.info(f"[主循环] 检测到取消令牌，终止第{page_num}页推流")
                        break
                    event = await asyncio.wait_for(out_queue.get(), timeout=120.0)
                    if event == "<DONE>":
                        break
                    if isinstance(event, dict) and event.get("type") == "audio":
                        page_duration += event.get("duration", 0)
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

            yield {
                "type": "end",
                "page": page_num,
                "page_duration": round(page_duration, 3),
                "ts": time.time(),
            }

        except Exception as e:
            logger.error(f"流式调度彻底失败: {e}", exc_info=True)
            yield {"type": "error", "message": str(e), "page": page_num}

    async def get_full_script(
        self, file_id: str, page_num: int, course_name: str = "课程"
    ) -> str:
        """生成并返回该页的完整讲解稿（非流式），并做简单缓存。"""
        cache_key = self._cache_key("script", file_id, page_num, course_name)
        cached = await self._cache_get(self.summary_cache, cache_key)
        if cached is not None:
            return cached

        upload = await asyncio.to_thread(get_upload, file_id)
        if not upload or not upload.get("path"):
            raise ValueError("PDF记录或路径不存在")
        pdf_path = upload.get("path")
        total_pages = await self.resolve_total_pages(upload)

        # 图片与相邻页摘要并发
        summaries_task = asyncio.create_task(
            self._get_context_summaries(
                file_id, page_num, pdf_path,
                total_pages, course_name
            )
        )
        image_task = asyncio.create_task(
            asyncio.to_thread(
                self.pdf_service.get_page_image, pdf_path, page_num
            )
        )
        image_base64 = await image_task
        try:
            prev_summary, next_summary = await asyncio.wait_for(
                summaries_task, timeout=3.0
            )
        except asyncio.TimeoutError:
            logger.info(f"第{page_num}页相邻摘要未在 3s 内完成，跳过")
            prev_summary, next_summary = "", ""

        system_prompt, user_prompt = build_full_lecture_prompt(
            course_name,
            page_num,
            total_pages,
            image_base64,
            prev_summary,
            next_summary,
        )

        try:
            script = await asyncio.to_thread(
                self.llm_service.generate_explanation, system_prompt, user_prompt
            )
        except Exception as e:
            logger.error(f"生成讲解稿失败: {e}")
            raise

        if not script:
            raise RuntimeError("LLM returned an empty explanation")
        await self._cache_set(self.summary_cache, cache_key, "script", script)
        return script

    async def get_cached_script(
        self, file_id: str, page_num: int, course_name: str = "课程"
    ):
        cache_key = self._cache_key("script", file_id, page_num, course_name)
        return await self._cache_get(self.summary_cache, cache_key)

    async def get_or_generate_page_sentences(
        self, text: str, file_id: str, page_num: int, course_name: str = "课程"
    ):
        cache_key = self._cache_key("audio", file_id, page_num, course_name)
        return await generate_cached_page_audio(
            text=text,
            file_id=file_id,
            page_num=page_num,
            course_name=course_name,
            tts_service=self.tts_service,
            cache=self.page_audio_cache,
            cache_key=cache_key,
            cache_get=self._cache_get,
            cache_set=self._cache_set,
        )

    async def stream_page_sentences(
        self,
        file_id: str,
        page_num: int,
        tts_text_stream,
        course_name: str = "课程",
        *,
        use_cache: bool = True,
        session_id: str | None = None,
    ):
        cache_key = self._cache_key("audio", file_id, page_num, course_name)
        async for event in stream_cached_page_audio(
            file_id=file_id,
            page_num=page_num,
            tts_text_stream=tts_text_stream,
            course_name=course_name,
            tts_service=self.tts_service,
            cache=self.page_audio_cache,
            cache_key=cache_key,
            cache_get=self._cache_get,
            cache_set=self._cache_set,
            is_cancelled=self._is_cancelled,
            use_cache=use_cache,
            session_id=session_id,
        ):
            yield event
