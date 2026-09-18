"""Session-token protection for the loopback desktop HTTP server."""

from __future__ import annotations

import hmac
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse


COOKIE_NAME = "pdfvox_desktop_session"


def install_desktop_security(app: FastAPI) -> None:
    token = os.getenv("PDFVOX_DESKTOP_TOKEN", "")
    if not token:
        return

    @app.middleware("http")
    async def require_desktop_session(request: Request, call_next):
        path = request.url.path
        if path == "/api/health" or path.startswith("/desktop/bootstrap/"):
            return await call_next(request)
        supplied = request.cookies.get(COOKIE_NAME, "")
        if not hmac.compare_digest(supplied, token):
            return JSONResponse({"detail": "Invalid desktop session"}, status_code=403)
        return await call_next(request)

    @app.get("/desktop/bootstrap/{supplied_token}", include_in_schema=False)
    def desktop_bootstrap(supplied_token: str):
        if not hmac.compare_digest(supplied_token, token):
            return JSONResponse({"detail": "Invalid desktop session"}, status_code=403)
        response = RedirectResponse("/", status_code=302)
        response.set_cookie(
            COOKIE_NAME,
            token,
            httponly=True,
            samesite="strict",
            secure=False,
        )
        return response
