from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.desktop_security import install_desktop_security
from app.services.settings_service import SettingsService
from app.version import __version__

from app.routers import ai_explain, app_settings, pdf_view, qa, upload

app = FastAPI(title="PDFVox Web", version=__version__)

app.include_router(upload.router, prefix="/upload", tags=["upload"])
app.include_router(pdf_view.router, prefix="/pdf", tags=["pdf"])
app.include_router(ai_explain.router, prefix="/explain", tags=["explain"])
app.include_router(qa.router, prefix="/qa", tags=["qa"])
app.include_router(app_settings.router, prefix="/settings", tags=["settings"])

install_desktop_security(app)

app.mount(
    "/static",
    StaticFiles(directory=str(settings.WEB_PATH / "static")),
    name="static",
)

templates = Jinja2Templates(directory=str(settings.WEB_PATH))
settings_service = SettingsService()


@app.get("/")
def index(request: Request):
    if not settings_service.status().configured:
        return templates.TemplateResponse(request, "setup.html", {"request": request})
    return templates.TemplateResponse(request, "index.html", {"request": request})


@app.get("/setup.html")
def setup(request: Request):
    return templates.TemplateResponse(request, "setup.html", {"request": request})

@app.get("/viewer.html")
def viewer(request: Request):
    if not settings_service.status().configured:
        return RedirectResponse("/setup.html", status_code=302)
    return templates.TemplateResponse(request, "viewer.html", {"request": request})

@app.get("/status.html")
def status(request: Request):
    return templates.TemplateResponse(request, "status.html", {"request": request})


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "message": "PDFVox web server is running",
        "version": __version__,
    }
