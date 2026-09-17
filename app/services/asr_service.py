import asyncio
import os
import tempfile
import threading
import wave
from typing import Optional

from app.utils.logging import get_logger

logger = get_logger(__name__)

load_silero_vad = None
get_speech_timestamps = None

DEFAULT_SAMPLE_RATE = 16000


class ASRService:

    def __init__(self):
        self.whisper_model = None
        self.vad_model = None
        self._vad_load_attempted = False
        self._vad_lock = threading.Lock()
        self._whisper_lock = threading.Lock()

    def _get_vad(self):
        global load_silero_vad, get_speech_timestamps
        if self._vad_load_attempted:
            return self.vad_model
        with self._vad_lock:
            if self._vad_load_attempted:
                return self.vad_model
            self._vad_load_attempted = True
            if load_silero_vad is None:
                try:
                    from silero_vad import (
                        get_speech_timestamps as speech_timestamps,
                        load_silero_vad as load_vad,
                    )

                    load_silero_vad = load_vad
                    get_speech_timestamps = speech_timestamps
                except Exception as e:
                    logger.warning(f"Silero VAD is unavailable: {e}")
            if load_silero_vad:
                try:
                    self.vad_model = load_silero_vad()
                    logger.info("Silero VAD model loaded")
                except Exception as e:
                    logger.warning(f"Failed to load Silero VAD model: {e}")
        return self.vad_model

    def _get_whisper(self):
        if self.whisper_model is not None:
            return self.whisper_model
        with self._whisper_lock:
            if self.whisper_model is not None:
                return self.whisper_model
            import faster_whisper

            try:
                self.whisper_model = faster_whisper.WhisperModel(
                    "base", device="cpu", compute_type="int8",
                )
            except OSError:
                import huggingface_hub
                logger.info("Symlink failed, downloading model files directly...")
                model_dir = os.path.join(
                    os.path.expanduser("~"), ".cache", "huggingface",
                    "faster-whisper-base"
                )
                os.makedirs(model_dir, exist_ok=True)
                for f in ["config.json", "model.bin", "tokenizer.json"]:
                    huggingface_hub.hf_hub_download(
                        "Systran/faster-whisper-base", f, local_dir=model_dir,
                    )
                self.whisper_model = faster_whisper.WhisperModel(
                    model_dir, device="cpu", compute_type="int8",
                    local_files_only=True,
                )
            logger.info("Whisper base model loaded")
        return self.whisper_model

    def _vad_check(self, pcm_bytes: bytes, sample_rate: int) -> Optional[bool]:
        vad_model = self._get_vad()
        if not (vad_model and get_speech_timestamps):
            return None
        try:
            import numpy as np
            import torch

            samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
            samples /= 32768.0
            waveform = torch.from_numpy(samples)
            stamps = get_speech_timestamps(
                waveform,
                vad_model,
                sampling_rate=sample_rate,
                return_seconds=True,
            )
            return bool(stamps)
        except Exception as e:
            logger.warning(f"VAD check failed: {e}")
            return None

    async def detect_speaking_from_pcm(
        self, pcm_bytes: bytes, sample_rate: int = DEFAULT_SAMPLE_RATE
    ) -> bool:
        if not pcm_bytes:
            return False
        vad = await asyncio.to_thread(self._vad_check, pcm_bytes, sample_rate)
        if vad is not None:
            return vad

        import numpy as np
        arr = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
        if arr.size == 0:
            return False
        return bool((np.mean(arr ** 2)) ** 0.5 > 100)

    async def transcribe_pcm_to_text(
        self, pcm_bytes: bytes, sample_rate: int = DEFAULT_SAMPLE_RATE
    ) -> str:
        if not pcm_bytes:
            return ""
        vad = await asyncio.to_thread(self._vad_check, pcm_bytes, sample_rate)
        if vad is False:
            logger.info("VAD found no speech; skipping Whisper transcription")
            return ""

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            wav_path = tf.name
        try:
            with wave.open(wav_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(pcm_bytes)

            model = await asyncio.to_thread(self._get_whisper)
            segments, _ = await asyncio.to_thread(
                model.transcribe, wav_path, language="zh", beam_size=5
            )
            text = " ".join(s.text.strip() for s in segments)
            if text:
                logger.info(
                    f"Whisper transcript: '{text[:80]}...' ({len(text)} chars)"
                )
            else:
                logger.info("Whisper returned empty transcript")
            return text
        finally:
            if os.path.exists(wav_path):
                os.remove(wav_path)
