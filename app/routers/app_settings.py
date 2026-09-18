"""Local settings endpoints used by the desktop first-run experience."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.credentials import CredentialStoreError
from app.services.runtime import reconfigure_api_clients
from app.services.settings_service import SettingsService


router = APIRouter()
service = SettingsService()


class ApiKeyUpdate(BaseModel):
    llm_api_key: str = Field(min_length=1, max_length=1_024)
    tts_api_key: str = Field(min_length=1, max_length=1_024)


def _require_local_request(request: Request) -> None:
    host = request.client.host if request.client else ""
    if host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(status_code=403, detail="Settings are local-only")


@router.get("/status")
def settings_status():
    status = service.status()
    return {
        "configured": status.configured,
        "llm_configured": status.llm_configured,
        "tts_configured": status.tts_configured,
    }


@router.post("/configure")
def configure_api_keys(payload: ApiKeyUpdate, request: Request):
    _require_local_request(request)
    try:
        status = service.save_api_keys(
            payload.llm_api_key,
            payload.tts_api_key,
        )
        reconfigure_api_clients()
    except (CredentialStoreError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"configured": status.configured}


@router.delete("/credentials")
def clear_api_keys(request: Request):
    _require_local_request(request)
    try:
        status = service.clear_api_keys()
        reconfigure_api_clients()
    except CredentialStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"configured": status.configured}
