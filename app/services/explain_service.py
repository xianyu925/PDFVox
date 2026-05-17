import time
import asyncio
from app.services.pdf_service import PDFService
from app.services.llm_service import LLMService
from app.services.tts_service import TTSService
from app.models.db import get_upload
from app.utils.logging import get_logger

logger = get_logger(__name__)


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
        if file_id not in self.summary_cache:
            self.summary_cache[file_id] = {}
        if page_num in self.summary_cache[file_id]:
            return self.summary_cache[file_id][page_num]

        try:
            image_base64 = await asyncio.to_thread(
                self.pdf_service.get_page_image, pdf_path, page_num
            )
            system_prompt = (
                "你是一位大学教授，擅长将PPT页面内容提炼为精炼的教学摘要。\n\n"
                "你的摘要将被用于连接前后页面的讲解，因此需要准确捕捉本页的教学要点。\n\n"
                "遵循以下规则：\n"
                "1. 先审视页面整体结构：标题是什么？属于概念讲解、案例分析、公式推导还是总结？\n"
                "2. 只提取页面上实际存在的内容，不要凭空推测或补充页面之外的信息\n"
                "3. 以教师的视角概括：「本页讲授了……核心要点是……关键结论是……」\n"
                "4. 若页面为纯标题/章节封面页，则描述本章将要覆盖的主题范围\n"
                "5. 若页面以图表/流程图为主，描述图表传达的核心关系或流程\n"
                "6. 不超过100字，信息密度优先，去掉所有语气词和冗余修饰"
            )
            user_prompt = [
                {
                    "type": "text",
                    "text": (
                        f"请为「{course_name}」第{page_num}页写一段教学摘要（≤100字）。\n"
                        "要求：用一段连贯的话概括本页的教学内容，包含「本页讲什么」和「学生应掌握什么」，"
                        "不要使用编号列表，直接写成叙述段。"
                    ),
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

            system_prompt = (
                "你是一位大学教授，正在课堂上为学生们讲课。你以「我」自称，用第一人称讲解。\n\n"
                "讲解风格：\n"
                "- 深入浅出：用生动的比喻、贴近生活的例子把复杂概念讲透\n"
                "- 口语自然：像站在讲台上即兴讲授，不要念PPT式的罗列，不要用书面语\n\n"
                "讲解节奏：\n"
                "1. 先快速判断本页的内容密度：是标题页/章节封面？还是密集的知识点？还是图表为主？\n"
                "2. 标题页/封面页/章节过渡页：简洁介绍，1-3句话讲清楚本章要学什么即可，不要展开\n"
                "3. 内容密集页：逐层展开，先说「是什么」再说「为什么」，适当设问引导思考\n"
                "4. 图表/流程图为主的页面：先描述图表传达的核心关系，再点明关键结论\n\n"
                "开场词规则：\n"
                "- 只有第1页（课程首页）可以使用「同学们好」「今天我们来学习……」等开场白\n"
                "- 中间页面和最后一页：禁止使用「好，同学们」「同学们注意」等开场寒暄，直接从内容切入\n"
                "- 如果上一页有摘要，用一两句话自然过渡后立即进入本页内容\n\n"
                "约束：\n"
                "- 只讲解页面上实际有的内容，不捏造信息\n"
                "- 不要出现任何Markdown符号\n"
                "- 不要描写你的动作、神态、表情"
            )
            prompt_text = (
                f"现在你正在讲授「{course_name}」，这是第{page_num}页（共{total_pages}页）。\n"
            )
            if page_num == 1:
                prompt_text += "这是课程首页，请用自然开场白后开始讲解。\n"
            elif page_num == total_pages:
                prompt_text += "这是课程最后一页，请简洁总结收尾。\n"
            else:
                prompt_text += "这是中间页，请勿使用开场寒暄，直接从上一页过渡或切入内容。\n"
            if prev_summary:
                prompt_text += f"上一页讲了：{prev_summary}\n"
            if next_summary:
                prompt_text += f"下一页将要讲：{next_summary}\n"

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

            page_duration = 0.0
            try:
                while True:
                    if self._is_cancelled(file_id):
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
        cache_key = f"script_{file_id}_{page_num}"
        if cache_key in self.summary_cache:
            return self.summary_cache[cache_key]

        upload = get_upload(file_id)
        if not upload or not upload.get("path"):
            raise ValueError("PDF记录或路径不存在")
        pdf_path = upload.get("path")

        # 图片与相邻页摘要并发
        summaries_task = asyncio.create_task(
            self._get_context_summaries(
                file_id, page_num, pdf_path,
                upload.get("total_pages", 1), course_name
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

        total_pages = upload.get("total_pages", 1)

        system_prompt = (
            "你是一位大学教授，正在课堂上为学生们讲课。你以「我」自称，用第一人称讲解。\n\n"
            "讲解风格：\n"
            "- 深入浅出：用生动的比喻、贴近生活的例子把复杂概念讲透\n"
            "- 口语自然：像站在讲台上即兴讲授，不要念PPT式的罗列，不要用书面语\n\n"
            "讲解节奏：\n"
            "1. 先快速判断本页的内容密度：是标题页/章节封面？还是密集的知识点？还是图表为主？\n"
            "2. 标题页/封面页/章节过渡页：简洁介绍，1-3句话讲清楚本章要学什么即可，不要展开\n"
            "3. 内容密集页：逐层展开，先说「是什么」再说「为什么」，适当设问引导思考\n"
            "4. 图表/流程图为主的页面：先描述图表传达的核心关系，再点明关键结论\n\n"
            "开场词规则：\n"
            "- 只有第1页可以使用「同学们好」「今天我们来学习……」等开场白\n"
            "- 中间页面和最后一页：禁止使用「好，同学们」等开场寒暄，直接从内容切入\n\n"
            "约束：只讲解页面上实际有的内容、不要出现Markdown符号、不要描写动作神态。"
        )
        prompt_text = (
            f"请为「{course_name}」第{page_num}页写一份完整的讲解稿（共{total_pages}页）。\n"
        )
        if page_num == 1:
            prompt_text += "这是课程首页，请用自然开场白后开始讲解。\n"
        elif page_num == total_pages:
            prompt_text += "这是课程最后一页，请简洁总结收尾。\n"
        else:
            prompt_text += "这是中间页，请勿使用开场寒暄，直接从上一页过渡或切入内容。\n"
        if prev_summary:
            prompt_text += f"上一页讲了：{prev_summary}\n"
        if next_summary:
            prompt_text += f"下一页将要讲：{next_summary}\n"

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
                    "duration": event.get("duration", 0),
                    "word_timestamps": event.get("word_timestamps", []),
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
                    "duration": item.get("duration", 0),
                    "word_timestamps": item.get("word_timestamps", []),
                    "page": page_num,
                }
            return

        sentences = []
        async for event in self.tts_service.stream_tts_input(tts_text_stream, page_num):
            if event.get("type") == "audio" and event.get("data"):
                sentences.append({
                    "sentence": event.get("sentence", ""),
                    "audio": event.get("data", ""),
                    "duration": event.get("duration", 0),
                    "word_timestamps": event.get("word_timestamps", []),
                })
            yield event

        if sentences:
            self.page_audio_cache[file_id][page_num] = sentences
            logger.info(
                f"[页音频流已缓存] 第{page_num}页，共 {len(sentences)} 个句子"
            )
