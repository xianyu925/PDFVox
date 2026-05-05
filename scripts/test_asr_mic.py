"""
Test script: verify Volcengine ASR can transcribe real human speech.
Exact replica of the frontend-to-backend pipeline:
  Browser recording -> 16kHz mono WAV -> strip header -> transcribe_pcm_to_text

Usage:
  # Record from microphone (requires sounddevice)
  python scripts/test_asr_mic.py

  # Transcribe an existing WAV file
  python scripts/test_asr_mic.py --file path/to/recording.wav

Record a short sentence (e.g. "Hello, today is a sunny day") and save as:
  - 16kHz, mono, 16-bit PCM WAV (frontend format)
  - Or any WAV/MP3/WebM - will be auto-converted
"""

import asyncio
import struct
import sys
import os
import time
import argparse
import subprocess
import tempfile
import wave
import shutil

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "app"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "app", "services"))


def safe_print(*args, **kwargs):
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        text = " ".join(str(a) for a in args)
        print(text.encode("ascii", errors="replace").decode("ascii"))


def encode_wav(samples, sample_rate=16000):
    """Exact replica of frontend encodeWAV() in viewer.js.
    16-bit mono PCM, little-endian, 44-byte RIFF/WAVE header.
    """
    num_samples = len(samples)
    buf = bytearray(44 + num_samples * 2)

    buf[0:4] = b"RIFF"
    struct.pack_into("<I", buf, 4, 36 + num_samples * 2)
    buf[8:12] = b"WAVE"
    buf[12:16] = b"fmt "
    struct.pack_into("<I", buf, 16, 16)
    struct.pack_into("<H", buf, 20, 1)           # PCM
    struct.pack_into("<H", buf, 22, 1)           # mono
    struct.pack_into("<I", buf, 24, sample_rate)
    struct.pack_into("<I", buf, 28, sample_rate * 2)
    struct.pack_into("<H", buf, 32, 2)
    struct.pack_into("<H", buf, 34, 16)
    buf[36:40] = b"data"
    struct.pack_into("<I", buf, 40, num_samples * 2)

    for i, s in enumerate(samples):
        s = max(-1.0, min(1.0, float(s)))
        int_val = int(s * 32767) if s >= 0 else int(s * 32768)
        int_val = max(-32768, min(32767, int_val))
        struct.pack_into("<h", buf, 44 + i * 2, int_val)

    return bytes(buf)


def strip_wav_header(data: bytes) -> bytes:
    """Exact replica of qa.py WAV stripping logic."""
    if len(data) >= 12 and data[0:4] == b"RIFF":
        idx = data.find(b"data")
        if idx != -1:
            return data[idx + 8:]
        else:
            return data
    else:
        return data


def convert_to_16k_wav(input_path: str) -> bytes:
    """Convert any audio file to 16kHz mono 16-bit PCM WAV using ffmpeg,
    then return raw WAV bytes and PCM bytes.
    Returns (wav_bytes, pcm_bytes) or (None, None).
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    out_path = tmp.name

    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", input_path,
                "-ar", "16000", "-ac", "1",
                "-sample_fmt", "s16",
                "-f", "wav", out_path,
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
    except FileNotFoundError:
        safe_print("  [ERROR] ffmpeg not found. Install ffmpeg or use a 16kHz mono WAV file.")
        safe_print("  Download: https://ffmpeg.org/download.html")
        if os.path.exists(out_path):
            os.remove(out_path)
        return None, None
    except subprocess.TimeoutExpired:
        safe_print("  [ERROR] ffmpeg timed out.")
        if os.path.exists(out_path):
            os.remove(out_path)
        return None, None
    except subprocess.CalledProcessError as e:
        safe_print(f"  [ERROR] ffmpeg failed: {e.stderr.decode()[:200] if e.stderr else e}")
        if os.path.exists(out_path):
            os.remove(out_path)
        return None, None

    raw = open(out_path, "rb").read()
    pcm = strip_wav_header(raw)
    os.remove(out_path)
    return raw, pcm


def load_wav_direct(filepath: str):
    """Load a WAV file directly using Python wave module.
    Returns (samples_float32_list, wav_bytes, pcm_bytes) or (None, None, None).
    """
    import numpy as np

    try:
        raw = open(filepath, "rb").read()
        wf = wave.open(filepath, "rb")
        sr = wf.getframerate()
        nch = wf.getnchannels()
        sw = wf.getsampwidth()
        nf = wf.getnframes()
        raw_frames = wf.readframes(nf)
        wf.close()

        if sw == 2:
            arr = np.frombuffer(raw_frames, dtype=np.int16).astype(np.float32) / 32768.0
        elif sw == 4:
            arr = np.frombuffer(raw_frames, dtype=np.int32).astype(np.float32) / 2147483648.0
        elif sw == 1:
            arr = (np.frombuffer(raw_frames, dtype=np.uint8).astype(np.float32) - 128) / 128.0
        else:
            safe_print(f"  [ERROR] Unsupported sample width: {sw}")
            return None, None, None

        if nch > 1:
            arr = arr.reshape(-1, nch).mean(axis=1)

        samples = arr.tolist()

        if sr != 16000 and len(samples) > 0:
            import numpy as np
            target_len = int(len(samples) * 16000 / sr)
            indices = np.linspace(0, len(samples) - 1, max(target_len, 1))
            samples = np.interp(indices, np.arange(len(samples)), np.array(samples)).tolist()

        wav_bytes = encode_wav(samples, 16000)
        pcm_bytes = strip_wav_header(wav_bytes)

        safe_print(f"  -> Source: {sr}Hz, {nch}ch, {sw*8}bit, {len(samples)} frames (resampled to 16kHz)")
        return samples, wav_bytes, pcm_bytes

    except Exception as e:
        safe_print(f"  [ERROR] Failed to load WAV: {e}")
        return None, None, None


def record_from_mic(duration_sec: float = 5.0, sample_rate: int = 16000):
    """Record audio from the default microphone."""
    try:
        import sounddevice as sd
    except ImportError:
        safe_print("  [INFO] sounddevice not installed. Use --file instead.")
        safe_print("  Or install: pip install sounddevice")
        return None

    safe_print(f"\n  Recording for {duration_sec}s at {sample_rate}Hz mono...")
    safe_print("  Speak now! (e.g. 'Hello, today is a sunny day')")
    safe_print("  " + "-" * 40)

    try:
        recording = sd.rec(
            int(duration_sec * sample_rate),
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
        )
        sd.wait()
        sd.stop()
    except Exception as e:
        safe_print(f"  [ERROR] Recording failed: {e}")
        return None

    samples = recording.flatten().tolist()
    wav_bytes = encode_wav(samples, sample_rate)
    pcm_bytes = strip_wav_header(wav_bytes)
    return samples, wav_bytes, pcm_bytes


async def run_transcription(pcm_bytes: bytes, samples: list, wav_path: str):
    """Core: send PCM to ASR and print result."""
    from app.services.asr_service import ASRService

    svc = ASRService()
    safe_print(f"  -> VAD loaded:  {svc.vad_model is not None}")

    rms = (sum(s * s for s in samples) / max(len(samples), 1)) ** 0.5
    safe_print(f"  -> RMS energy:  {rms:.6f} ({'OK' if rms > 0.001 else 'LOW - may be silence'})")
    safe_print(f"  -> PCM size:    {len(pcm_bytes)} bytes ({len(pcm_bytes)/32000:.2f}s)")

    safe_print("\n  Transcribing with local Whisper model...")

    try:
        start = time.time()
        transcript = await asyncio.wait_for(
            svc.transcribe_pcm_to_text(pcm_bytes, sample_rate=16000),
            timeout=40.0,
        )
        elapsed = time.time() - start

        safe_print(f"\n  {'=' * 50}")
        safe_print(f"  Transcript ({elapsed:.1f}s): '{transcript}'")
        safe_print(f"  {'=' * 50}")

        if transcript.strip():
            safe_print(f"\n  [SUCCESS] ASR correctly transcribed human speech!")
            return True
        else:
            safe_print(f"\n  [FAIL] ASR returned empty transcript.")
            safe_print(f"  Diagnostics:")
            safe_print(f"    - PCM size: {len(pcm_bytes)} bytes")
            safe_print(f"    - RMS energy: {rms:.6f}")
            safe_print(f"    - First 10 samples: {[round(s,4) for s in samples[:10]]}")
            safe_print(f"    - First 40 PCM bytes (hex): {pcm_bytes[:40].hex()}")
            safe_print(f"  Check the WAV manually: {wav_path}")
            return False

    except asyncio.TimeoutError:
        safe_print(f"\n  [FAIL] ASR timed out after 40s")
        return False
    except Exception as e:
        safe_print(f"\n  [FAIL] ASR exception: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    parser = argparse.ArgumentParser(description="ASR Real Voice Transcription Test")
    parser.add_argument("--file", "-f", help="Path to a WAV/audio file to transcribe")
    parser.add_argument("--duration", "-d", type=float, default=5.0, help="Recording duration in seconds (default: 5)")
    args = parser.parse_args()

    safe_print("=" * 60)
    safe_print("  ASR Real Voice Transcription Test")
    safe_print("=" * 60)

    samples = None
    wav_bytes = None
    pcm_bytes = None

    if args.file:
        filepath = args.file
        if not os.path.exists(filepath):
            safe_print(f"\n  [ERROR] File not found: {filepath}")
            return

        safe_print(f"\n  Input file: {filepath} ({os.path.getsize(filepath)} bytes)")

        raw = open(filepath, "rb").read()
        if raw[:4] == b"RIFF":
            safe_print("  -> Detected WAV format, loading directly...")
            samples, wav_bytes, pcm_bytes = load_wav_direct(filepath)
        else:
            safe_print("  -> Converting via ffmpeg to 16kHz mono PCM...")
            wav_bytes, pcm_bytes = convert_to_16k_wav(filepath)
            if wav_bytes:
                import numpy as np
                import io
                bio = io.BytesIO(wav_bytes)
                wf = wave.open(bio, "rb")
                nf = wf.getnframes()
                raw_frames = wf.readframes(nf)
                wf.close()
                arr = np.frombuffer(raw_frames, dtype=np.int16).astype(np.float32) / 32768.0
                samples = arr.tolist()
    else:
        result = record_from_mic(duration_sec=args.duration, sample_rate=16000)
        if result is None:
            safe_print("\n  Usage alternatives:")
            safe_print("    pip install sounddevice          # then run again without --file")
            safe_print("    python test_asr_mic.py --file recording.wav")
            safe_print("\n  Record a WAV manually (Audacity / Voice Recorder / etc)")
            safe_print("  and pass it with --file. Any format accepted.")
            return
        samples, wav_bytes, pcm_bytes = result

    if not samples or not pcm_bytes:
        safe_print("  [ERROR] Failed to obtain audio data.")
        return

    safe_print(f"  -> {len(samples)} samples, {len(pcm_bytes)} bytes PCM")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
        wav_path = tf.name
        tf.write(wav_bytes)
    safe_print(f"  -> Saved WAV:   {wav_path}")

    try:
        await run_transcription(pcm_bytes, samples, wav_path)
    finally:
        safe_print(f"\n  WAV file kept for inspection: {wav_path}")


if __name__ == "__main__":
    asyncio.run(main())
