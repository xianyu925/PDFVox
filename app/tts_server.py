"""
TTS Server - 独立的文本转语音服务

提供API端点来处理语音合成请求，支持批量处理和队列管理。
"""

import os
import time
import asyncio
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from config import settings
from services.tts_service import TTSService

# Create necessary directories
Path(settings.STORAGE_PATH).mkdir(parents=True, exist_ok=True)
Path("output").mkdir(parents=True, exist_ok=True)

# Create FastAPI application
app = FastAPI(title="TTS Server", description="独立的文本转语音服务", version="1.0.0")

# Create TTS service instance
tts_service = TTSService()

# Create thread pool for processing
executor = ThreadPoolExecutor(max_workers=4)


# Request and response models
class TTSRequest(BaseModel):
    """TTS request model"""

    text: str
    voice: Optional[str] = "fnlp/MOSS-TTSD-v0.5:alex"
    model: Optional[str] = "fnlp/MOSS-TTSD-v0.5"
    response_format: Optional[str] = "mp3"


class TTSBatchRequest(BaseModel):
    """Batch TTS request model"""

    items: List[TTSRequest]
    output_dir: Optional[str] = "output"


class TTSResponse(BaseModel):
    """TTS response model"""

    status: str
    audio_path: str
    message: Optional[str] = None


class TTSBatchResponse(BaseModel):
    """Batch TTS response model"""

    status: str
    processed: int
    total: int
    audio_paths: List[str]
    message: Optional[str] = None


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok", "service": "TTS Server", "version": "1.0.0"}


# Single TTS endpoint
@app.post("/tts", response_model=TTSResponse)
async def single_tts(request: TTSRequest):
    """Single text-to-speech conversion"""
    try:
        # Generate unique filename
        timestamp = int(time.time())
        audio_path = os.path.join("output", f"tts_{timestamp}.mp3")

        # Run TTS in a separate thread to avoid blocking
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            executor, tts_service.synthesize, request.text, audio_path
        )

        return TTSResponse(
            status="success",
            audio_path=audio_path,
            message="Text synthesized successfully",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Batch TTS endpoint
@app.post("/tts/batch", response_model=TTSBatchResponse)
async def batch_tts(request: TTSBatchRequest):
    """Batch text-to-speech conversion"""
    try:
        # Ensure output directory exists
        output_dir = request.output_dir
        os.makedirs(output_dir, exist_ok=True)

        # Process each item
        audio_paths = []
        total = len(request.items)
        processed = 0

        for i, item in enumerate(request.items):
            try:
                # Generate filename
                timestamp = int(time.time())
                audio_path = os.path.join(output_dir, f"tts_batch_{timestamp}_{i}.mp3")

                # Run TTS
                tts_service.synthesize(item.text, audio_path)
                audio_paths.append(audio_path)
                processed += 1
            except Exception as e:
                print(f"Error processing item {i}: {e}")
                continue

        return TTSBatchResponse(
            status="success" if processed > 0 else "partial",
            processed=processed,
            total=total,
            audio_paths=audio_paths,
            message=f"Processed {processed}/{total} items",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Status endpoint
@app.get("/status")
async def get_status():
    """Get server status"""
    return {
        "status": "running",
        "workers": executor._max_workers,
        "pending_tasks": (
            len(executor._work_queue.queue) if hasattr(executor, "_work_queue") else 0
        ),
    }


# Main function
if __name__ == "__main__":
    # Run the server
    uvicorn.run("tts_server:app", host="0.0.0.0", port=8001, reload=False)
