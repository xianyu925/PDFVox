import asyncio
import os
import tempfile
import wave
from typing import Optional

from app.utils.logging import get_logger

logger = get_logger(__name__)

try:
    from silero_vad import load_silero_vad, get_speech_timestamps
except Exception:
    load_silero_vad = None
    get_speech_timestamps = None

DEFAULT_SAMPLE_RATE = 16000


class ASRService:

    def __init__(self):
        self.whisper_model = None
        self.vad_model = None
        if load_silero_vad:
            try:
                self.vad_model = load_silero_vad()
                logger.info("Silero VAD model loaded")
            except Exception as e:
                logger.warning(f"Failed to load Silero VAD model: {e}")

    def _get_whisper(self):
        if self.whisper_model is None:
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

    @staticmethod
    def _read_wav_for_vad(path: str):
        import numpy as np
        import torch

        with wave.open(path, "rb") as wf:
            sr = wf.getframerate()
            nf = wf.getnframes()
            raw = wf.readframes(nf)
        arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if arr.ndim == 0:
            arr = np.array([0.0], dtype=np.float32)
        t = torch.from_numpy(arr)
        if t.dim() == 0:
            t = t.unsqueeze(0)
        return t

    def _vad_check(self, pcm_bytes: bytes, sample_rate: int) -> Optional[bool]:
        if not (self.vad_model and get_speech_timestamps):
            return None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
                tmp_path = tf.name
            try:
                with wave.open(tmp_path, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(sample_rate)
                    wf.writeframes(pcm_bytes)
                wav = self._read_wav_for_vad(tmp_path)
                stamps = get_speech_timestamps(
                    wav, self.vad_model, return_seconds=True
                )
                return len(stamps) > 0
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
        except Exception as e:
            logger.warning(f"VAD check failed: {e}")
            return None

    async def detect_speaking_from_pcm(
        self, pcm_bytes: bytes, sample_rate: int = DEFAULT_SAMPLE_RATE
    ) -> bool:
        vad = self._vad_check(pcm_bytes, sample_rate)
        if vad is not None:
            return vad

        import numpy as np
        arr = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
        return bool((np.mean(arr ** 2)) ** 0.5 > 100)

    async def transcribe_pcm_to_text(
        self, pcm_bytes: bytes, sample_rate: int = DEFAULT_SAMPLE_RATE
    ) -> str:
        self._vad_check(pcm_bytes, sample_rate)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            wav_path = tf.name
        try:
            with wave.open(wav_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(pcm_bytes)

            model = self._get_whisper()
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
