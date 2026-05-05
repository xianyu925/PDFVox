# Plan: 字幕与语音同步问题 — 根因确认与修复方案

## 排查结论：**后端问题，前端无缺陷**

### 前端验证 ✅

`processAudioQueue()` ([viewer.js:L124-L184](file:///d:/project/PDFVox/web/static/viewer.js#L124-L184)) 逻辑正确——每收到一个 audio chunk 就立即更新 `globalSubtitle.innerHTML` 并播放对应的 PCM 音频。只要后端正确拆分为多个 chunk，字幕就会同步更新。

### 后端根因 🔴

通过 log.txt 全量排查，发现两次截然不同的 TTS 服务器行为：

| 时间段 | TTS 服务器行为 | 结果 |
|---|---|---|
| 2026-04-29 **13:25-13:26** | 每句发送 `FullServerResponse + TTSSentenceEnd` | ✅ 正确拆分：13 句 → 10+33 个 audio chunk |
| 2026-04-29 **15:41+** | 所有音频流式推送，**仅在 Session 结束时发 1 次** `TTSSentenceEnd` | ❌ 全部合并：14 句 → 1 个 2MB chunk |

v3 修复后的 DEBUG 日志证实：当前服务器**每条 `AudioOnlyServer` 消息都是 `flag=WithEvent(4), event=TTSResponse(352)`**，从不发送 `TTSSentenceEnd(351)`。唯一的 `TTSSentenceEnd` 来自 `SessionFinished`。

```
AudioOnlyServer: flag=WithEvent(4), event=TTSResponse(352), payload=18000   ← 永远的 TTSResponse
AudioOnlyServer: flag=WithEvent(4), event=TTSResponse(352), payload=19222   ← 永远的 TTSResponse
...
(几百条 TTSResponse，PCM 不断累积)
...
句子完成(TTSSentenceEnd)，合并7057294字节PCM → 1个音频事件 (剩余待匹配句子: 45)  ← 仅此一次
```

**火山引擎 seed-tts-2.0 双向 TTS 已不再在单个 Session 内发送逐句的 `TTSSentenceEnd` 信号**。之前试图通过检测协议 flag 或 event 来被动分割句子，是基于服务器会主动发送边界信号的前提——但这个前提已经不再成立。

## 修复方案

既然服务器不提供句子边界，我们**主动管理句子边界**——将"一个 Session 内发送全部句子"改为"**每个句子一个独立 Session**"。

### 具体修改

仅修改 [tts_service.py](file:///d:/project/PDFVox/app/services/tts_service.py) 中的 `stream_tts_input()` 方法：

**步骤 1**：打开 WebSocket 连接并保持复用

**步骤 2**：将会话管理循环化——对每个句子（从 sender 消费 sentence_queue），执行：
```
StartSession → 发送一句 TaskRequest → 等待 finish_session → 
收集该句所有 AudioOnlyServer PCM → SessionFinished → yield {audio, sentence}
```

**步骤 3**：简化接收逻辑
- 移除所有关于 flag/event 的句子边界猜测代码（NegativeSeq、LastNoSeq、WithEvent/TTSSentenceEnd）
- 每个 Session 只处理一句话，SessionFinished 就是的句子结束信号
- 不再需要 `pending_sentences` 列表和 `make_flush()` 辅助函数
- 保留 `sender()` 的文本分割逻辑（按标点/60字符切句）

### 架构对比

| | 修改前（当前） | 修改后 |
|---|---|---|
| TTS 会话数 | 1 个 Session / 页 | N 个 Session / 页（每句一个） |
| 句子边界信号 | 依赖服务器 TTSSentenceEnd（不可靠） | SessionFinished = 确切的句子边界 |
| pending_sentences | 需要维护队列匹配 | **不需要**，每 Session 只处理一句 |
| flag/event 检测 | 多层 if-elif 猜测 | **不需要**，简化接收循环 |

### 风险

- **低**：每次 StartSession/TaskRequest/FinishSession 的延迟很小（火山引擎 WebSocket 会话建立很快）
- WebSocket 连接复用，无额外连接开销
- 如果单句 Session 仍有延迟问题，可改为批量预发送方案

## 受影响文件

- `app/services/tts_service.py` — 仅此一个文件
