"""Credential persistence abstraction for API keys.

The production backend uses the operating system keyring.  Tests and future
platform integrations can inject another implementation without changing the
HTTP or service layers.
"""

from __future__ import annotations

import os
from typing import Protocol


SERVICE_NAME = "PDFVox"
LLM_KEY_NAME = "LLM_API_KEY"
TTS_KEY_NAME = "TTS_API_KEY"


class CredentialStoreError(RuntimeError):
    pass


class CredentialStore(Protocol):
    def get(self, name: str) -> str | None: ...

    def set(self, name: str, value: str) -> None: ...

    def delete(self, name: str) -> None: ...


class SystemCredentialStore:
    """Store secrets in Windows Credential Manager through ``keyring``."""

    @staticmethod
    def _keyring():
        try:
            import keyring
        except ImportError as exc:
            raise CredentialStoreError(
                "系统凭据组件不可用，请重新安装 PDFVox"
            ) from exc
        return keyring

    def get(self, name: str) -> str | None:
        try:
            return self._keyring().get_password(SERVICE_NAME, name)
        except Exception as exc:
            raise CredentialStoreError("无法读取系统凭据") from exc

    def set(self, name: str, value: str) -> None:
        try:
            self._keyring().set_password(SERVICE_NAME, name, value)
        except Exception as exc:
            raise CredentialStoreError("无法写入系统凭据") from exc

    def delete(self, name: str) -> None:
        try:
            self._keyring().delete_password(SERVICE_NAME, name)
        except Exception as exc:
            # Missing credentials are already in the desired state.
            if exc.__class__.__name__ != "PasswordDeleteError":
                raise CredentialStoreError("无法删除系统凭据") from exc


def load_api_key(name: str, *legacy_environment_names: str) -> str:
    """Load an API key with environment variables taking precedence."""
    for environment_name in (name, *legacy_environment_names):
        value = os.getenv(environment_name, "").strip()
        if value:
            return value
    try:
        return (SystemCredentialStore().get(name) or "").strip()
    except CredentialStoreError:
        # Startup must remain possible so the setup page can explain/fix the
        # problem. Saving credentials will return the actionable error.
        return ""
