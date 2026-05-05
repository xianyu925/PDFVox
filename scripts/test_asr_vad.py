"""
Test script: verify Silero VAD and Volcengine ASR services
Usage: python scripts/test_asr_vad.py
"""

import asyncio
import struct
import math
import wave
import os
import tempfile
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "app"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "app", "services"))

# Helper: safe print to avoid GBK encoding errors on Windows
def safe_print(*args, **kwargs):
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        text = " ".join(str(a) for a in args)
        print(text.encode("ascii", errors="replace").decode("ascii"))


def read_wav_safe(path, target_sr=16000):
    """Load a WAV file and return a torch tensor at target_sr.

    Bypasses torchaudio (which requires torchcodec on 2.11+).
    Tries soundfile first, then scipy, then wave+numpy.
    """
    import numpy as np

    data = None
    sr = None

    try:
        import soundfile as sf
        data, sr = sf.read(path, dtype="float32")
        if data.ndim > 1:
            data = data[:, 0]
    except Exception:
        pass

    if data is None:
        try:
            from scipy.io import wavfile
            sr, raw = wavfile.read(path)
            if raw.dtype == np.int16:
                data = raw.astype(np.float32) / 32768.0
            elif raw.dtype == np.int32:
                data = raw.astype(np.float32) / 2147483648.0
            else:
                data = raw.astype(np.float32)
            if data.ndim > 1:
                data = data[:, 0]
        except Exception:
            pass

    if data is None:
        import wave
        with wave.open(path, "rb") as wf:
            sr = wf.getframerate()
            n_frames = wf.getnframes()
            raw = wf.readframes(n_frames)
            dtype = np.int16 if wf.getsampwidth() == 2 else np.int32
            data = np.frombuffer(raw, dtype=dtype).astype(np.float32)
            if dtype == np.int16:
                data /= 32768.0
            elif dtype == np.int32:
                data /= 2147483648.0

    if sr != target_sr and sr is not None and len(data) > 0:
        resample_len = int(len(data) * target_sr / sr)
        indices = np.linspace(0, len(data) - 1, max(resample_len, 1))
        data = np.interp(indices, np.arange(len(data)), data)
        sr = target_sr

    import torch
    tensor = torch.from_numpy(data.astype(np.float32))
    if tensor.dim() == 0:
        tensor = tensor.unsqueeze(0)
    return tensor


def make_sine_wav(duration_sec=2.0, freq=440, sample_rate=16000, amplitude=0.8):
    """Generate a sine wave PCM (simulates speech audio)"""
    num_samples = int(duration_sec * sample_rate)
    pcm = bytearray()
    for i in range(num_samples):
        t = i / sample_rate
        sample = int(amplitude * 32767 * math.sin(2 * math.pi * freq * t))
        pcm.extend(struct.pack("<h", sample))
    return bytes(pcm)


def make_silence_wav(duration_sec=2.0, sample_rate=16000):
    """Generate silence PCM (simulates no-speech audio)"""
    num_samples = int(duration_sec * sample_rate)
    return bytes(num_samples * 2)


def make_wav_header(data_len, sample_rate=16000):
    """Build a standard 44-byte WAV header"""
    header = bytearray(44)
    header[0:4] = b'RIFF'
    struct.pack_into('<I', header, 4, 36 + data_len)
    header[8:12] = b'WAVE'
    header[12:16] = b'fmt '
    struct.pack_into('<I', header, 16, 16)           # chunk size
    struct.pack_into('<H', header, 20, 1)             # PCM
    struct.pack_into('<H', header, 22, 1)             # mono
    struct.pack_into('<I', header, 24, sample_rate)
    struct.pack_into('<I', header, 28, sample_rate * 2)
    struct.pack_into('<H', header, 32, 2)
    struct.pack_into('<H', header, 34, 16)
    header[36:40] = b'data'
    struct.pack_into('<I', header, 40, data_len)
    return bytes(header)


# ===== Test 1: Silero VAD =====

def test_vad_sine():
    """Test VAD with a synthetic sine wave"""
    safe_print("\n" + "=" * 60)
    safe_print("Test 1: Silero VAD - sine wave detection")
    safe_print("=" * 60)

    try:
        from silero_vad import load_silero_vad, get_speech_timestamps
    except ImportError as e:
        safe_print(f"  [SKIP] silero_vad not installed: {e}")
        safe_print("  Install: pip install silero-vad")
        return None

    try:
        model = load_silero_vad()
        safe_print("  [OK] VAD model loaded")
    except Exception as e:
        safe_print(f"  [FAIL] VAD model load failed: {e}")
        return None

    pcm = make_sine_wav(duration_sec=2.0, freq=440, amplitude=0.8)
    safe_print(f"  -> Generated {len(pcm)} bytes of 440Hz sine PCM ({2.0}s, 16kHz)")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
        tmp_path = tf.name

    try:
        header = make_wav_header(len(pcm))
        with open(tmp_path, "wb") as f:
            f.write(header + pcm)

        safe_print(f"  -> Temp WAV: {tmp_path} ({os.path.getsize(tmp_path)} bytes)")

        wav = read_wav_safe(tmp_path)
        speech_timestamps = get_speech_timestamps(wav, model, return_seconds=True)

        if speech_timestamps:
            safe_print(f"  [OK] VAD detected speech: {len(speech_timestamps)} segment(s)")
            for i, ts in enumerate(speech_timestamps):
                safe_print(f"      segment {i+1}: {ts['start']:.2f}s -> {ts['end']:.2f}s")
        else:
            safe_print(f"  [WARN] VAD returned no speech segments (false negative)")

        return speech_timestamps

    except Exception as e:
        safe_print(f"  [FAIL] VAD exception: {e}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def test_vad_silence():
    """Test VAD with pure silence"""
    safe_print("\n" + "=" * 60)
    safe_print("Test 2: Silero VAD - silence detection")
    safe_print("=" * 60)

    try:
        from silero_vad import load_silero_vad, get_speech_timestamps
        model = load_silero_vad()
    except Exception as e:
        safe_print(f"  [SKIP] VAD not available: {e}")
        return None

    pcm = make_silence_wav(duration_sec=2.0)
    safe_print(f"  -> Generated {len(pcm)} bytes silence PCM")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
        tmp_path = tf.name

    try:
        header = make_wav_header(len(pcm))
        with open(tmp_path, "wb") as f:
            f.write(header + pcm)

        wav = read_wav_safe(tmp_path)
        speech_timestamps = get_speech_timestamps(wav, model, return_seconds=True)

        if not speech_timestamps:
            safe_print(f"  [OK] VAD correctly classified as silence")
        else:
            safe_print(f"  [WARN] VAD flagged silence as speech: {len(speech_timestamps)} segments")

        return speech_timestamps

    except Exception as e:
        safe_print(f"  [FAIL] VAD exception: {e}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def test_vad_with_real_like_audio():
    """Test VAD with intermittent sweeping tones (simulates human speech pattern)"""
    safe_print("\n" + "=" * 60)
    safe_print("Test 3: Silero VAD - simulated speech (sweep + gaps)")
    safe_print("=" * 60)

    try:
        from silero_vad import load_silero_vad, get_speech_timestamps
        model = load_silero_vad()
    except Exception as e:
        safe_print(f"  [SKIP] VAD not available: {e}")
        return None

    sample_rate = 16000
    duration = 3.0
    num_samples = int(duration * sample_rate)
    pcm = bytearray()

    for i in range(num_samples):
        t = i / sample_rate
        freq = 200 + 600 * (t / duration)  # sweep 200-800 Hz
        amp = 0.6 if (int(t * 4) % 2 == 0) else 0.0  # alternating on/off
        sample = int(amp * 32767 * math.sin(2 * math.pi * freq * t))
        pcm.extend(struct.pack("<h", sample))

    safe_print(f"  -> Generated {len(pcm)} bytes sweep/gap PCM")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
        tmp_path = tf.name

    try:
        header = make_wav_header(len(pcm))
        with open(tmp_path, "wb") as f:
            f.write(header + bytes(pcm))

        wav = read_wav_safe(tmp_path)
        speech_timestamps = get_speech_timestamps(wav, model, return_seconds=True)

        safe_print(f"  -> VAD detected {len(speech_timestamps)} speech segment(s)")
        for i, ts in enumerate(speech_timestamps):
            safe_print(f"      segment {i+1}: {ts['start']:.2f}s -> {ts['end']:.2f}s "
                       f"(dur={ts['end']-ts['start']:.2f}s)")
        return speech_timestamps

    except Exception as e:
        safe_print(f"  [FAIL] VAD exception: {e}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


# ===== Test 2: Remote ASR =====

async def test_asr_connection():
    """Test WebSocket connection to Volcengine ASR"""
    safe_print("\n" + "=" * 60)
    safe_print("Test 4: Remote ASR WebSocket connection")
    safe_print("=" * 60)

    try:
        from app.services.asr_service import ASRService
    except Exception as e:
        safe_print(f"  [FAIL] Cannot import ASRService: {e}")
        return False

    svc = ASRService()
    safe_print(f"  -> Endpoint: {svc.endpoint}")
    safe_print(f"  -> Resource: {svc.resource_id}")

    try:
        ws = await asyncio.wait_for(svc._connect(), timeout=15.0)
        safe_print(f"  [OK] WebSocket connected successfully")
        try:
            await ws.close()
        except Exception:
            pass
        return True

    except asyncio.TimeoutError:
        safe_print(f"  [FAIL] Connection timeout (15s)")
        return False
    except Exception as e:
        safe_print(f"  [FAIL] Connection failed: {e}")
        return False


async def test_asr_detect_speaking():
    """Test ASR speech detection with sine wave"""
    safe_print("\n" + "=" * 60)
    safe_print("Test 5: Remote ASR detect_speaking_from_pcm")
    safe_print("=" * 60)

    try:
        from app.services.asr_service import ASRService
    except Exception as e:
        safe_print(f"  [FAIL] Cannot import: {e}")
        return None

    svc = ASRService()
    pcm = make_sine_wav(duration_sec=2.0, freq=440, amplitude=0.8)
    safe_print(f"  -> Sending {len(pcm)} bytes sine wave to ASR...")

    try:
        result = await asyncio.wait_for(
            svc.detect_speaking_from_pcm(pcm),
            timeout=30.0,
        )
        safe_print(f"  -> detect_speaking_from_pcm returned: {result}")
        if result:
            safe_print(f"  [OK] ASR detected speech")
        else:
            safe_print(f"  [INFO] ASR returned no speech (sine wave is not natural speech, this is normal)")
        return result
    except asyncio.TimeoutError:
        safe_print(f"  [FAIL] Timeout (30s)")
        return None
    except Exception as e:
        safe_print(f"  [FAIL] Exception: {e}")
        import traceback
        traceback.print_exc()
        return None


async def test_asr_transcribe_sine():
    """Test ASR transcription with sine wave (may be blocked by VAD)"""
    safe_print("\n" + "=" * 60)
    safe_print("Test 6: Remote ASR transcribe_pcm_to_text (with VAD)")
    safe_print("=" * 60)

    try:
        from app.services.asr_service import ASRService
    except Exception as e:
        safe_print(f"  [FAIL] Cannot import: {e}")
        return None

    svc = ASRService()

    if svc.vad_model:
        safe_print(f"  [INFO] VAD is loaded -> will check VAD first")
        safe_print(f"         If VAD returns empty, remote ASR will be SKIPPED")
        safe_print(f"         <= This is the current bug!")
    else:
        safe_print(f"  [INFO] VAD not loaded -> will call remote ASR directly")

    pcm = make_sine_wav(duration_sec=2.0, freq=440, amplitude=0.8)
    safe_print(f"  -> Sending {len(pcm)} bytes sine wave for transcription...")

    try:
        result = await asyncio.wait_for(
            svc.transcribe_pcm_to_text(pcm),
            timeout=30.0,
        )
        safe_print(f"  -> Transcript: '{result}'")
        if result.strip():
            safe_print(f"  [OK] ASR returned text")
        else:
            safe_print(f"  [INFO] Empty transcript (sine wave is not natural speech)")
        return result
    except asyncio.TimeoutError:
        safe_print(f"  [FAIL] Timeout (30s)")
        return None
    except Exception as e:
        safe_print(f"  [FAIL] Exception: {e}")
        import traceback
        traceback.print_exc()
        return None


async def test_asr_transcribe_raw(bypass_vad=True):
    """Test ASR transcription bypassing VAD"""
    safe_print("\n" + "=" * 60)
    safe_print(f"Test 7: Remote ASR transcription {'(VAD BYPASSED)' if bypass_vad else '(with VAD)'}")
    safe_print("=" * 60)

    try:
        from app.services.asr_service import ASRService
    except Exception as e:
        safe_print(f"  [FAIL] Cannot import: {e}")
        return None

    svc = ASRService()

    saved = None
    if bypass_vad and svc.vad_model:
        safe_print(f"  [INFO] Temporarily disabling VAD model...")
        saved = svc.vad_model
        svc.vad_model = None

    try:
        pcm = make_sine_wav(duration_sec=2.0, freq=440, amplitude=0.8)
        safe_print(f"  -> Sending {len(pcm)} bytes sine wave...")

        result = await asyncio.wait_for(
            svc.transcribe_pcm_to_text(pcm),
            timeout=30.0,
        )
        safe_print(f"  -> Transcript: '{result}'")
        if result.strip():
            safe_print(f"  [OK] Transcript has content")
        else:
            safe_print(f"  [INFO] Empty transcript")
        return result

    finally:
        if saved is not None:
            svc.vad_model = saved
            safe_print(f"  [INFO] VAD model restored")


# ===== Main =====

async def main():
    safe_print("=" * 60)
    safe_print("  Silero VAD + Volcengine ASR Diagnostic Tool")
    safe_print("=" * 60)

    # --- Local VAD tests ---
    test_vad_sine()
    test_vad_silence()
    test_vad_with_real_like_audio()

    # --- Remote ASR tests ---
    connected = await test_asr_connection()
    if not connected:
        safe_print("\n[WARN] Remote ASR connection failed, skipping remote tests")
        safe_print("  Check: API Key / network / firewall")
    else:
        await test_asr_detect_speaking()
        await test_asr_transcribe_sine()
        await test_asr_transcribe_raw(bypass_vad=True)

    # --- Summary ---
    safe_print("\n" + "=" * 60)
    safe_print("Diagnosis Summary")
    safe_print("=" * 60)
    safe_print("""
If Test 1 PASSED (sine detected by VAD) but QA still fails:
  -> VAD itself works. The problem may be frontend recording format/sample rate/PCM data.

If Test 1 FAILED (sine wave NOT detected by VAD):
  -> VAD model is broken or silero-vad library version is incompatible.

If remote ASR transcription returns text but QA still shows error:
  -> VAD is blocking the call (current bug). Remove the VAD early return.

If remote ASR transcription returns empty even with VAD bypassed:
  -> The sine wave is not recognized as speech by Volcengine ASR. This is expected.
  -> Try recording a real voice sentence and sending the WAV file instead.
""")


if __name__ == "__main__":
    asyncio.run(main())
