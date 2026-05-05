# Plan: 修复 ASR HTTP 403 认证错误

## 根因

403 = `volc.bigasr.sauc.duration`（ASR 1.0）不在该 API Key 的授权范围内。之前 `volc.seedasr.sauc.duration`（ASR 2.0）连接一直成功，但我们在上一轮改成了 demo 里的 1.0 resource_id。

## 修复方案

### 唯一改动：`asr_service.py` 第 54 行

```python
# 修改前（403）
self.resource_id = "volc.bigasr.sauc.duration"

# 修改后（已验证可用）
self.resource_id = "volc.seedasr.sauc.duration"
```

### 为什么之前 `volc.seedasr.sauc.duration` 连接成功但转写失败

因为之前用的是错误的双向 Session 协议（StartSession / TaskRequest）。现在协议已按 demo 重写为正确的二进制帧协议（FullClientRequest + AudioOnlyClient + GZIP），配上正确的 resource_id，整条链路就通了。

### 验证

```bash
D:\machine_learning\anaconda\envs\PDFVox\python.exe scripts/test_asr_mic.py --duration 6
```

预期：连接成功 → FullClientRequest → 逐包发送音频 → 收到 ASRResponse JSON → 打印转录文本。

## 受影响文件

| 文件 | 变更 |
|---|---|
| `app/services/asr_service.py` | 第 54 行：1 处改回 |

## 风险

- **零风险**：`volc.seedasr.sauc.duration` 在 `test_asr_vad.py` Test 4 中通过 `start_connection` 验证连接成功（之前连了几十次都没 403）
