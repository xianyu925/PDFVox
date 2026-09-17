"""Standalone HTTP wrapper around PDFVox's bidirectional TTS service."""

import uuid
from pathlib import Path
from typing import List, Literal, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.services.tts_service import TTSService


OUTPUT_DIR = Path(settings.STORAGE_PATH) / "tts_output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="PDFVox TTS Server", version="1.0.0")
tts_service = TTSService()


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    response_format: Literal["wav"] = "wav"


class TTSBatchRequest(BaseModel):
    items: List[TTSRequest] = Field(min_length=1, max_length=100)


class TTSResponse(BaseModel):
    status: str
    audio_path: str
    message: Optional[str] = None


class TTSBatchResponse(BaseModel):
    status: str
    processed: int
    total: int
    audio_paths: List[str]
    message: Optional[str] = None


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "PDFVox TTS Server", "version": "1.0.0"}


async def _synthesize(text: str, prefix: str) -> str:
    output_path = OUTPUT_DIR / f"{prefix}_{uuid.uuid4().hex}.wav"
    await tts_service.synthesize_to_wav(text, output_path)
    return str(output_path)


@app.post("/tts", response_model=TTSResponse)
async def single_tts(request: TTSRequest):
    try:
        audio_path = await _synthesize(request.text, "tts")
        return TTSResponse(
            status="success",
            audio_path=audio_path,
            message="Text synthesized successfully",
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/tts/batch", response_model=TTSBatchResponse)
async def batch_tts(request: TTSBatchRequest):
    audio_paths = []
    errors = []
    for index, item in enumerate(request.items):
        try:
            audio_paths.append(await _synthesize(item.text, f"tts_batch_{index}"))
        except Exception as exc:
            errors.append(f"item {index}: {exc}")

    processed = len(audio_paths)
    return TTSBatchResponse(
        status="success" if processed == len(request.items) else "partial",
        processed=processed,
        total=len(request.items),
        audio_paths=audio_paths,
        message="; ".join(errors) or f"Processed {processed} items",
    )


@app.get("/status")
async def get_status():
    return {"status": "running", "output_dir": str(OUTPUT_DIR)}


if __name__ == "__main__":
    uvicorn.run("app.tts_server:app", host="0.0.0.0", port=8001, reload=False)
