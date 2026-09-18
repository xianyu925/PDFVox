"""Process-wide service instances shared by the HTTP routers."""

from threading import RLock

from app.services.asr_service import ASRService
from app.services.explain_service import ExplainService
from app.services.llm_service import LLMService
from app.services.qa_service import QAService
from app.services.tts_service import TTSService


explain_service = ExplainService()
asr_service = ASRService()
qa_service = QAService(
    explain_service.llm_service,
    explain_service.tts_service,
    explain_service,
)

_configuration_lock = RLock()


def reconfigure_api_clients() -> None:
    """Recreate API clients after credentials change, preserving caches."""
    with _configuration_lock:
        llm_service = LLMService()
        tts_service = TTSService()
        explain_service.llm_service = llm_service
        explain_service.tts_service = tts_service
        qa_service._llm = llm_service
        qa_service._tts = tts_service
