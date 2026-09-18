"""Application settings use cases, independent from the HTTP layer."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import settings
from app.credentials import (
    LLM_KEY_NAME,
    TTS_KEY_NAME,
    CredentialStore,
    SystemCredentialStore,
)


@dataclass(frozen=True)
class CredentialStatus:
    llm_configured: bool
    tts_configured: bool

    @property
    def configured(self) -> bool:
        return self.llm_configured and self.tts_configured


class SettingsService:
    def __init__(self, store: CredentialStore | None = None):
        self._store = store or SystemCredentialStore()

    def status(self) -> CredentialStatus:
        return CredentialStatus(
            llm_configured=bool(settings.LLM_API_KEY),
            tts_configured=bool(settings.TTS_API_KEY),
        )

    def save_api_keys(self, llm_api_key: str, tts_api_key: str) -> CredentialStatus:
        llm_key = llm_api_key.strip()
        tts_key = tts_api_key.strip()
        if not llm_key or not tts_key:
            raise ValueError("LLM API Key 和 TTS API Key 均不能为空")

        previous_llm = self._store.get(LLM_KEY_NAME)
        previous_tts = self._store.get(TTS_KEY_NAME)
        try:
            self._store.set(LLM_KEY_NAME, llm_key)
            self._store.set(TTS_KEY_NAME, tts_key)
        except Exception:
            self._restore(LLM_KEY_NAME, previous_llm)
            self._restore(TTS_KEY_NAME, previous_tts)
            raise

        settings.LLM_API_KEY = llm_key
        settings.TTS_API_KEY = tts_key
        return self.status()

    def clear_api_keys(self) -> CredentialStatus:
        self._store.delete(LLM_KEY_NAME)
        self._store.delete(TTS_KEY_NAME)
        settings.LLM_API_KEY = ""
        settings.TTS_API_KEY = ""
        return self.status()

    def _restore(self, name: str, value: str | None) -> None:
        try:
            if value:
                self._store.set(name, value)
            else:
                self._store.delete(name)
        except Exception:
            pass
