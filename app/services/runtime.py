"""Process-wide service instances shared by the HTTP routers."""

from app.services.asr_service import ASRService
from app.services.explain_service import ExplainService
from app.services.qa_service import QAService


explain_service = ExplainService()
asr_service = ASRService()
qa_service = QAService(
    explain_service.llm_service,
    explain_service.tts_service,
    explain_service,
)
