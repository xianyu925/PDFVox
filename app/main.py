from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings

# 确保数据库初始化
from app.models.db import init_db

init_db()
from app.routers import upload, pdf_view, ai_explain, qa

app = FastAPI(title="PDFVox Web")

app.include_router(upload.router, prefix="/upload", tags=["upload"])
app.include_router(pdf_view.router, prefix="/pdf", tags=["pdf"])
app.include_router(ai_explain.router, prefix="/explain", tags=["explain"])
app.include_router(qa.router, prefix="/qa", tags=["qa"])

Path(settings.STORAGE_PATH).mkdir(parents=True, exist_ok=True)
Path("output").mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory="web/static"), name="static")

templates = Jinja2Templates(directory="web")


@app.get("/")
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {"request": request})

@app.get("/viewer.html")
def viewer(request: Request):
    return templates.TemplateResponse(request, "viewer.html", {"request": request})

@app.get("/status.html")
def status(request: Request):
    return templates.TemplateResponse(request, "status.html", {"request": request})


@app.get("/api/health")
def health():
    return {"status": "ok", "message": "PDFVox web server is running"}
