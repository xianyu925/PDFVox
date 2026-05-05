# Plan: 字幕与语音不同步修复 v3

## 根因分析

DEBUG 日志暴露了真相——火山引擎 seed-tts-2.0 双向 TTS 发送的 **所有** `AudioOnlyServer` 消息 flag 都是 `WithEvent(4)`：

```
flag=WithEvent(4), payload_size=19198, 累积中=5933314
flag=WithEvent(4), payload_size=19196, 累积中=5952510
flag=WithEvent(4), payload_size=19204, 累积中=5971714
...
```

**没有一条消息使用 `NegativeSeq(3)` 或 `LastNoSeq(2)` 或 `NoSeq(0)`。**

### 为什么之前的两个修复都无效

| 修复版本 | 检测条件 | 实际 flag | 结果 |
|---|---|---|---|
| v1 | `msg.flag == NegativeSeq` (3) | `WithEvent` (4) | ❌ 永远不触发 |
| v2 | `msg.flag in (NegativeSeq, LastNoSeq)` (3, 2) | `WithEvent` (4) | ❌ 永远不触发 |

### `WithEvent` 的含义

`WithEvent` flag 意味着消息中包含 event 字段。火山引擎在 `AudioOnlyServer` 消息中嵌入 TTS 事件来标记句子边界：

- `TTSSentenceStart(350)` — 句子第一个音频包
- `TTSSentenceEnd(351)` — 句子最后一个音频包

但当前代码 **仅在 `FullServerResponse` 分支检查 `msg.event`**，而在 `AudioOnlyServer` 分支只检查 flag（且检查的是错误的 flag 值），因此成千上万个带 `TTSSentenceEnd` 事件的 `AudioOnlyServer` 消息全被忽略，PCM 持续累积成一个巨型 chunk。

### 最终现象

```
几十条 AudioOnlyServer+WithEvent+TTSSentenceEnd 消息 → 全部忽略
  → 1 条 FullServerResponse+TTSSentenceEnd(最后一条) → 7MB PCM 一次性配对第一句字幕
```

## 实施方案

### 步骤 1：在 AudioOnlyServer 分支中增加 WithEvent + TTSSentenceEnd 检测

在 [tts_service.py](file:///d:/project/PDFVox/app/services/tts_service.py) 的 `AudioOnlyServer` 分支（第 262 行），当前只检查 `NegativeSeq`/`LastNoSeq`。需要增加：

```python
elif msg.flag == MsgTypeFlagBits.WithEvent and msg.event == EventType.TTSSentenceEnd:
    # 句子边界：WithEvent + TTSSentenceEnd
    flag_name = "WithEvent/TTSSentenceEnd"
    # 执行句子配对与 yield（与 NegativeSeq/LastNoSeq 分支相同逻辑）
```

### 步骤 2：重构句子配对逻辑为独立辅助函数

当前相同的配对+ yield 代码重复出现在 3 个位置（AudioOnlyServer+flag 分支、FullServerResponse+TTSSentenceEnd 分支、final drain 分支），维护困难且易出错。提取为内部函数：

```python
def _flush_sentence(label: str):
    nonlocal current_sentence_pcm, audio_count
    if pending_sentences and current_sentence_pcm:
        current_sentence_text = pending_sentences.pop(0)
        audio_base64 = base64.b64encode(
            bytes(current_sentence_pcm)
        ).decode("utf-8")
        audio_count += 1
        logger.info(
            f"[TTS接收方] 句子完成({label})，"
            f"合并{len(current_sentence_pcm)}字节PCM → 1个音频事件 "
            f"(剩余待匹配句子: {len(pending_sentences)})"
        )
        yield_result = {
            "type": "audio",
            "data": audio_base64,
            "page": page_num,
            "sentence": current_sentence_text,
            "ts": time.time(),
        }
        current_sentence_pcm = bytearray()
        return yield_result
    elif current_sentence_pcm:
        logger.warning(
            f"[TTS接收方] {label} 到达但 pending_sentences 为空，"
            f"丢弃 {len(current_sentence_pcm)} 字节 PCM"
        )
        current_sentence_pcm = bytearray()
    return None
```

三个调用点统一使用此函数，减少重复并确保一致性。

### 步骤 3：增强 DEBUG 日志输出 event 字段

将 DEBUG 日志从仅输出 flag 扩展为同时输出 event 名称，确认服务器实际发送的事件类型：

```
[TTS接收方-DEBUG] AudioOnlyServer: flag=WithEvent(4), event=TTSSentenceEnd(351), payload=19198, 累积=xxx
```

### 步骤 4：验证

- 语法检查
- 确认 `MsgTypeFlagBits` 和 `EventType` 导入无误

## 受影响文件

- `app/services/tts_service.py` — 仅此一个文件

## 风险评估

- **极低**：仅增加一个新的 flag+event 组合检测，不改变现有逻辑
- 如果 `WithEvent + TTSSentenceEnd` 仍不是正确边界（概率极低），DEBUG 日志将暴露实际事件类型
