from __future__ import annotations

import asyncio
import hashlib
from typing import TYPE_CHECKING

from app.config import settings
from app.models.db import get_generated_cache, get_upload, save_generated_cache
from app.services.cache import TTLCache
from app.utils.logging import get_logger

if TYPE_CHECKING:
    from app.services.explain_service import ExplainService
    from app.services.llm_service import LLMService
    from app.services.tts_service import TTSService

logger = get_logger(__name__)

_QA_SYSTEM_WITH_SCRIPT = (
    "你是一位大学教授，正在课后为学生答疑。你以「我」自称，用第一人称回答。\n\n"
    "回答原则：\n"
    "1. 你同时拥有：①当前PPT页面图像；②本节课从第1页到当前页之间已生成的全部讲稿；③之前的对话历史\n"
    "2. 如果对话历史中已有相关讨论，请自然地衔接上下文，不要重复已讲过的内容\n"
    "3. 如果学生的问题涉及前面已讲过的内容，请结合对应的讲稿进行解答，建立知识之间的联系\n"
    "4. 先判断问题是否与本页或已讲过内容相关：若相关则深入解答；若不相关则礼貌引导回本页主题\n"
    "5. 回答要有教学深度：不仅给出结论，还要解释「为什么」，适当举例或类比\n"
    "6. 语言口语化、适合语音朗读，不要出现Markdown符号\n"
    "7. 用「同学们」称呼学生"
)

_QA_SYSTEM_WITHOUT_SCRIPT = (
    "你是一位大学教授，正在课后为学生答疑。你以「我」自称，用第一人称回答。\n\n"
    "回答原则：\n"
    "1. 你只能看到当前PPT页面图像（尚无讲稿）和之前的对话历史\n"
    "2. 如果对话历史中已有相关讨论，请自然地衔接上下文，不要重复已讲过的内容\n"
    "3. 先判断问题是否与本页教学内容相关：若相关则深入解答；若不相关则礼貌引导回本页主题\n"
    "4. 回答要有教学深度：不仅给出结论，还要解释「为什么」，适当举例或类比\n"
    "5. 语言口语化、适合语音朗读，不要出现Markdown符号\n"
    "6. 用「同学们」称呼学生\n"
    "7. 若页面信息不足以回答该问题，坦率说明并从页面上能确定的内容出发给出部分解答"
)


class QAService:

    def __init__(
        self,
        llm_service: LLMService,
        tts_service: TTSService,
        explain_service: ExplainService,
    ):
        self._llm = llm_service
        self._tts = tts_service
        self._explain = explain_service
        self._history = TTLCache(
            settings.QA_HISTORY_MAX_DOCUMENTS, settings.CACHE_TTL_SECONDS
        )

    # ---- 对话历史 ----

    @staticmethod
    def _history_key(file_id: str, session_id: str) -> str:
        digest = hashlib.sha256(f"{file_id}\0{session_id}".encode()).hexdigest()
        return f"qa_history:{digest}"

    async def _get_history(self, file_id: str, session_id: str) -> list:
        key = self._history_key(file_id, session_id)
        rounds = self._history.get(key)
        if rounds is None:
            rounds = await asyncio.to_thread(get_generated_cache, key) or []
            self._history[key] = rounds
        return list(rounds)

    async def add_history(
        self, file_id: str, question: str, answer: str,
        session_id: str = "default"
    ) -> None:
        key = self._history_key(file_id, session_id)
        rounds = await self._get_history(file_id, session_id)
        rounds.append({"question": question, "answer": answer})
        rounds = rounds[-5:]
        self._history[key] = rounds
        await asyncio.to_thread(
            save_generated_cache,
            key,
            "qa_history",
            rounds,
            settings.CACHE_TTL_SECONDS,
            settings.GENERATED_CACHE_MAX_ENTRIES,
        )
        logger.info(
            f"[QA多轮] 已保存第 {len(rounds)} 轮对话 | "
            f"Q: {question[:50]}... → A: {answer[:50]}..."
        )

    async def _history_text(self, file_id: str, session_id: str) -> tuple[str, int]:
        rounds = await self._get_history(file_id, session_id)
        if not rounds:
            return "", 0
        lines = ["以下是之前的对话历史："]
        for r in rounds:
            lines.append(f"学生问：{r['question']}")
            lines.append(f"老师答：{r['answer']}")
        lines.append("---")
        return "\n".join(lines), len(rounds)

    # ---- 页面图片 ----

    async def _get_page_image(
        self, pdf_path: str, page_num: int
    ) -> str | None:
        try:
            return await asyncio.to_thread(
                self._explain.pdf_service.get_page_image, pdf_path, page_num
            )
        except Exception:
            return None

    # ---- 讲稿缓存收集 ----

    async def _get_all_scripts(
        self, file_id: str, current_page: int, course_name: str = "课程"
    ) -> dict[int, str]:
        """收集第1页到当前页之间所有已缓存的完整讲稿，按页码排序返回。"""
        scripts: dict[int, str] = {}
        for page in range(1, current_page + 1):
            script = await self._explain.get_cached_script(
                file_id, page, course_name
            )
            if script:
                scripts[page] = script
        if scripts:
            logger.info(
                f"[QA讲稿收集] file_id={file_id} 共找到 {len(scripts)} 页已缓存讲稿: "
                f"{sorted(scripts.keys())}"
            )
        return scripts

    # ---- 提示词构建 ----

    async def _build_prompt(
        self,
        file_id: str,
        page_num: int,
        user_question: str,
        session_id: str,
        course_name: str,
    ) -> tuple[str, list[dict]]:
        """返回 (system_prompt, user_prompt)，自动处理讲稿缓存与QA历史。"""
        scripts = await self._get_all_scripts(file_id, page_num, course_name)
        history, history_rounds = await self._history_text(file_id, session_id)

        if history_rounds:
            logger.info(
                f"[QA多轮] file_id={file_id} 已有 {history_rounds} 轮对话历史，注入prompt"
            )
        else:
            logger.info(f"[QA多轮] file_id={file_id} 首轮对话，无历史")

        if scripts:
            system_prompt = _QA_SYSTEM_WITH_SCRIPT
            user_prompt = []
            if history:
                user_prompt.append({"type": "text", "text": history})

            if len(scripts) == 1 and page_num in scripts:
                script_text = f"本页讲稿：\n{scripts[page_num]}"
            else:
                lines = ["以下是本节课已讲授过的全部讲稿："]
                for p, s in sorted(scripts.items()):
                    lines.append(f"--- 第{p}页讲稿 ---")
                    lines.append(s)
                script_text = "\n".join(lines)

            user_prompt.append({"type": "text", "text": script_text})
            user_prompt.append(
                {
                    "type": "text",
                    "text": f"学生提问：{user_question}\n请结合对话历史和讲稿内容，以第一人称直接回答。",
                }
            )
        else:
            system_prompt = _QA_SYSTEM_WITHOUT_SCRIPT
            user_prompt = []
            if history:
                user_prompt.append({"type": "text", "text": history})
            user_prompt.append(
                {
                    "type": "text",
                    "text": f"学生提问：{user_question}\n请结合对话历史，以第一人称直接回答。",
                }
            )

        return system_prompt, user_prompt

    # ---- 流式问答主流程 ----

    async def stream_qa_response(
        self, file_id: str, page_num: int, user_question: str,
        session_id: str = "default", course_name: str = "课程"
    ):
        """编排完整的流式问答：上下文→LLM→TTS，yield 统一事件。"""
        upload = await asyncio.to_thread(get_upload, file_id)
        if not upload or not upload.get("path"):
            yield {"type": "error", "message": "无法找到 file_id 对应记录"}
            return

        image_base64 = await self._get_page_image(
            upload.get("path"), page_num
        )

        system_prompt, user_prompt = await self._build_prompt(
            file_id, page_num, user_question, session_id, course_name
        )

        # 在多模态 prompt 中插入页面图像（放在讲稿之前、问题之后）
        if image_base64:
            image_block = {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{image_base64}"},
            }
            # 插入到倒数第二个位置（问题之前）
            user_prompt.insert(-1, image_block)

        text_queue: asyncio.Queue[str] = asyncio.Queue()
        out_queue: asyncio.Queue = asyncio.Queue()

        async def run_llm():
            try:
                async for event in self._llm.stream_explanation(
                    system_prompt, user_prompt, page_num
                ):
                    await out_queue.put(event)
                    if event.get("type") == "text":
                        await text_queue.put(event.get("data"))
            except Exception as e:
                logger.error(f"LLM 流式任务异常: {e}", exc_info=True)
                await out_queue.put({"type": "error", "message": str(e)})
            finally:
                await text_queue.put("<END>")

        async def run_tts():
            try:

                async def tts_input_stream():
                    while True:
                        chunk = await text_queue.get()
                        if chunk == "<END>":
                            yield {"type": "end"}
                            break
                        yield {"type": "text", "data": chunk}

                async for audio_event in self._tts.stream_tts_input(
                    tts_input_stream(), page_num
                ):
                    await out_queue.put(audio_event)
            except Exception as e:
                logger.error(f"TTS 流式任务异常: {e}", exc_info=True)
                await out_queue.put({"type": "error", "message": str(e)})
            finally:
                await out_queue.put("<DONE>")

        llm_task = asyncio.create_task(run_llm())
        await asyncio.sleep(0.05)
        tts_task = asyncio.create_task(run_tts())

        try:
            full_answer = ""
            while True:
                event = await out_queue.get()
                if event == "<DONE>":
                    break
                if isinstance(event, dict) and event.get("type") == "text":
                    full_answer += event.get("data", "")
                yield event
        finally:
            if llm_task and not llm_task.done():
                llm_task.cancel()
            if tts_task and not tts_task.done():
                tts_task.cancel()

        if full_answer:
            await self.add_history(
                file_id, user_question, full_answer, session_id
            )
