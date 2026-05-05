# Plan: Add TaskRequest to ASR protocol flow

## 根因

对比 TTS 的双向协议流程，发现 ASR **少了关键一步**：

| 步骤 | TTS (正常工作) | ASR (当前，失败) |
|---|---|---|
| 1 | `_connect()` | `_connect()` ✅ |
| 2 | `StartSession` → `SessionStarted` | `StartSession` → `SessionStarted` ✅ |
| 3 | **`TaskRequest`** (发送文本+参数) | **缺失！** ❌ |
| 4 | 接收 `AudioOnlyServer` | 发送 `AudioOnlyClient` |
| 5 | `finish_session` → `SessionFinished` | 空等 → `ConnectionClosed` |

没有 `TaskRequest`，服务器不知道客户端要做 ASR 转写——收到 `StartSession` 后直接收到 `AudioOnlyClient` 音频流，服务器不理解意图，直接关闭连接。

### 证据

```
2026-05-05 14:37:09,826 - protocols - ERROR - Failed to receive message: no close frame received or sent
ASR receive error (connection closed): no close frame received or sent
Transcript (0.8s): ''
```

0.8 秒就断开——服务器收到 `SessionStarted` 后立刻收到音频数据，没有 `TaskRequest` 指明任务，协议错误 → 断开。

## 修复方案

### 唯一改动：`asr_service.py`

在 `StartSession` / `SessionStarted` 之后、发送音频之前，插入 `TaskRequest`。

**修改位置**：[asr_service.py:L311-L313](file:///d:/project/PDFVox/app/services/asr_service.py#L311-L313)（`transcribe_pcm_to_text` 方法）

```python
# 会话启动后
await asyncio.wait_for(
    wait_for_event(ws, MsgType.FullServerResponse, EventType.SessionStarted),
    timeout=10.0,
)

# === 新增: TaskRequest ===
task_req = dict(base_request)
task_req["event"] = EventType.TaskRequest
await task_request(ws, json.dumps(task_req).encode(), session_id)
# === 新增结束 ===

# 发送音频分块
chunk_size = 3200
...
```

**同步修改** [asr_service.py:L174-L176](file:///d:/project/PDFVox/app/services/asr_service.py#L174-L176)（`detect_speaking_from_pcm` 方法），同样在 `SessionStarted` 后插入 `TaskRequest`。

### 验证

```bash
D:\machine_learning\anaconda\envs\PDFVox\python.exe scripts/test_asr_mic.py --duration 5
```

预期：
- 不再出现 `no close frame received or sent`
- `ASRResponse` 正常返回含转录文本的 payload
- 转录结束于 `SessionFinished`

## 受影响文件

| 文件 | 变更 |
|---|---|
| `app/services/asr_service.py` | 两处（transcribe + detect_speaking），各增加 TaskRequest 调用 |
