from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.routers import upload, pdf_view, ai_explain, audio

app = FastAPI(title="PDFVox Web")

app.include_router(upload.router, prefix="/upload", tags=["upload"])
app.include_router(pdf_view.router, prefix="/pdf", tags=["pdf"])
app.include_router(ai_explain.router, prefix="/explain", tags=["explain"])
app.include_router(audio.router, prefix="/audio", tags=["audio"])

Path(settings.STORAGE_PATH).mkdir(parents=True, exist_ok=True)
Path("output").mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

templates = Jinja2Templates(directory="app/templates")


@app.get("/")
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/viewer.html")
def viewer(request: Request):
    return templates.TemplateResponse("viewer.html", {"request": request})


@app.get("/status.html")
def status(request: Request):
    return templates.TemplateResponse("status.html", {"request": request})


@app.get("/api/health")
def health():
    return {"status": "ok", "message": "PDFVox web server is running"}
