from pathlib import Path
import uuid
from app.models.schemas import ExplainResponse
from app.services.pdf_service import PDFService
from pdfvox import PDFVox
from app.models.db import get_upload, save_task, update_task_status
from app.config import settings


class ExplainService:
    def __init__(self):
        self.pdf_service = PDFService()
        self.pdfvox = PDFVox(settings.API_KEY)

    def explain_page(
        self,
        file_id: str,
        page: int,
        auto_next: bool,
        course_name: str = "机器学习导论",
    ) -> ExplainResponse:
        upload = get_upload(file_id)
        if not upload:
            raise FileNotFoundError(f"Upload record not found: {file_id}")

        task_id = str(uuid.uuid4())
        save_task(
            task_id,
            {
                "task_id": task_id,
                "file_id": file_id,
                "page": page,
                "status": "started",
                "detail": "开始生成讲解",
            },
        )

        pdf_path = upload.get("path")
        if not pdf_path:
            raise ValueError("Upload path is missing")

        try:
            curr_text = self.pdf_service.get_page_text(pdf_path, page)
            prev_text = (
                self.pdf_service.get_page_text(pdf_path, page - 1) if page > 1 else ""
            )
            next_text = (
                self.pdf_service.get_page_text(pdf_path, page + 1)
                if page < len(self.pdf_service.list_pages(pdf_path))
                else ""
            )

            system_prompt = (
                "你是一位大学教授，正在给学生讲解课程。请以专业、清晰、有条理的方式讲解PDF内容，语气像在课堂上讲课一样。"
                "重点讲解核心概念、理论框架和关键知识点，避免冗余内容和对无关元素的过多讲解。"
                "讲解要逻辑连贯，层次分明，适合大学学生的理解水平。"
                "请在结尾给出自然过渡句，连接前后章节内容，并在最后补充一段简短衔接段落（不超过两句话）。"
            )
            user_prompt = (
                f"当前页面内容：\n{curr_text}\n"
                f"上一页内容：\n{prev_text}\n"
                f"下一页内容：\n{next_text}\n"
                f"请基于以上内容为{course_name}课程生成讲解。"
            )

            explanation = self.pdfvox._stream_chat_response(
                system_prompt, user_prompt, image_base64=None, max_tokens=800
            )
            transition = self.pdfvox.generate_transition_paragraph(
                page, prev_text, explanation, next_text
            )
            combined_text = (
                f"{explanation}\n\n{transition}" if transition else explanation
            )

            update_task_status(task_id, "completed", "讲解生成成功")

            return ExplainResponse(
                task_id=task_id,
                file_id=file_id,
                page=page,
                explanation=explanation,
                transition=transition,
                combined_text=combined_text,
                audio_url=None,
            )
        except Exception as e:
            update_task_status(task_id, "failed", str(e))
            raise
