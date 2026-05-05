# Plan: ASR 实人声转录测试

## 背景

诊断脚本全部使用合成正弦波，未测试真实人声。QA 仍报错，需要录音 → ASR 端到端验证。

## 实施方案

### 步骤 1：新建录音 + ASR 测试脚本 `scripts/test_asr_mic.py`

模拟前端完整链路：

```
Python 录音 (sounddevice, 16kHz mono float32)
  → 转 int16 → 写入 WAV (含 44-byte header，完全复刻前端 encodeWAV)
  → 剥离 header 得纯 PCM
  → 调用 asr_service.transcribe_pcm_to_text(pcm, 16000)
  → 打印转录文本
```

**依赖**：`sounddevice`（pip install sounddevice）。若未安装则提示。

**关键对齐点**（与前端/%qa.py 完全一致）：
- 采样率 16000
- 单声道
- 16-bit signed int（int16），小端序
- WAV header 剥离逻辑：`data[0:4] == b"RIFF"` → `data.find(b"data")` → `data[idx+8:]`
- 调用 `transcribe_pcm_to_text(pcm, 16000)`

### 步骤 2：运行并观察

运行脚本时对着麦克风说话（如"今天天气怎么样"），观察：
1. VAD pre-check 日志（是否仍因 torchcodec 失败但降级继续）
2. 远程 ASR 是否返回非空转录文本
3. 若转录仍为空，打印 PCM 数据摘要（长度、前几个字节、RMS 能量）辅助诊断

### 步骤 3：若转录成功但仍报错

说明问题在前端录音格式或网络传输，需要：
- 对比前端 WAV 与 Python WAV 的二进制差异
- 检查 FormData 上传是否完整
- 检查 `file.read()` 是否完整

## 受影响文件

| 文件 | 变更 |
|---|---|
| `scripts/test_asr_mic.py` | 新文件 |

## 风险

- `sounddevice` 可能需要 PortAudio 系统库（Windows 下通常自带或 pip 自动安装 wheels）
- 脚本仅测试后端 ASR 链，不涉及前端
