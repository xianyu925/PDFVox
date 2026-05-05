# Plan: 用本地 Whisper 替换火山引擎 ASR

## 使用方分析

`ASRService` 被以下 3 处调用，**公开 API 签名不变**：

| 调用方                                           | 方法                              | 用途               |
| --------------------------------------------- | ------------------------------- | ---------------- |
| `app/routers/qa.py:L194`                      | `transcribe_pcm_to_text(pcm)`   | Q\&A 流式：将用户录音转文本 |
| `app/routers/asr.py:L56`                      | `detect_speaking_from_pcm(pcm)` | 独立端点：检测录音是否有语音   |
| `scripts/test_asr_vad.py` / `test_asr_mic.py` | 两者                              | 测试脚本             |

## 实施方案

### 步骤 1：安装 Whisper

推荐 `faster-whisper`（CTranslate2 加速，CPU 友好，内存 \~3GB）：

```bash
pip install faster-whisper
```

模型首次运行时自动下载 `base` 模型（\~145MB）。

### 步骤 2：重写 `ASRService.__init__()`

删除所有火山引擎相关配置，改为加载 Whisper 模型：

```python
class ASRService:
    def __init__(self):
        self.whisper_model = None  # lazy load
        self.vad_model = None      # Silero VAD，不变
        if load_silero_vad:
            try:
                self.vad_model = load_silero_vad()
            except Exception as e:
                logger.warning(f"VAD load failed: {e}")

    def _get_whisper(self):
        if self.whisper_model is None:
            from faster_whisper import WhisperModel
            self.whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
        return self.whisper_model
```

### 步骤 3：删除所有火山引擎代码

移除以下全部：

* 常量：`MSG_FULL_CLIENT`, `MSG_AUDIO_ONLY`, `FLAG_POS_SEQ` 等

* 方法：`_make_header`, `_build_full_client_request`, `_build_audio_request`, `_parse_response`, `_connect`

* imports：`gzip`, `struct`, `ssl`, `socket`, `websockets`

### 步骤 4：重写 `transcribe_pcm_to_text()`

```python
async def transcribe_pcm_to_text(self, pcm_bytes, sample_rate=16000):
    self._vad_check(pcm_bytes, sample_rate)

    # 写临时 WAV
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
        return text
    finally:
        if os.path.exists(wav_path):
            os.remove(wav_path)
```

### 步骤 5：重写 `detect_speaking_from_pcm()`

```python
async def detect_speaking_from_pcm(self, pcm_bytes, sample_rate=16000):
    vad = self._vad_check(pcm_bytes, sample_rate)
    if vad is not None:
        return vad
    # VAD 不可用时，用 RMS 能量作为保底检测
    import numpy as np
    arr = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
    rms = (np.mean(arr ** 2)) ** 0.5
    return rms > 100  # int16 下能量阈值
```

### 步骤 6：保留不变的代码

* `_vad_check()` 方法 — **完全不变**

* Silero VAD 导入和加载 — **完全不变**

* `DEFAULT_SAMPLE_RATE` — **保留**

### 步骤 7：更新 `test_asr_mic.py`（可选）

将日志中的 "Volcengine ASR" 改为 "Local Whisper ASR"。

## 受影响文件

| 文件                            | 变更性质                                   |
| ----------------------------- | -------------------------------------- |
| `app/services/asr_service.py` | 核心重写：删 WebSocket 协议层，改用 faster-whisper |
| `app/routers/qa.py`           | **不变** — 公开 API 签名兼容                   |
| `app/routers/asr.py`          | **不变**                                 |
| `scripts/test_asr_vad.py`     | 微量：Test 4-7 的远程测试跳过（本地化后不再需要）          |
| `scripts/test_asr_mic.py`     | 微量：日志文案                                |

## 安全注意事项

* **Whisper 模型文件写入临时目录时需隔离** — `tempfile.NamedTemporaryFile` 已满足

* **VAD 处理用户上传的 PCM 同理** — 已有 tmp file + cleanup

## 风险

* **中等（性能）**：`base` 模型在 CPU 上每 5 秒音频约需 2-4 秒推理。可后续升级 `small` 或 GPU。

* **低（兼容性）**：公开 API 签名不变，所有调用方无需修改。

