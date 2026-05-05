# Plan: 字幕冻结问题修复 v2

## 根因再分析

通过 log.txt 全量排查发现：

| 日志条目                                                | 说明                                                        |
| --------------------------------------------------- | --------------------------------------------------------- |
| `句子完成(TTSSentenceEnd)，合并1873986字节PCM → (剩余待匹配: 13)` | **仅1条**：TTSSentenceEnd 在一次 Session 结束时触发，13 句全合并为一个 chunk |
| `句子完成(NegativeSeq)...`                              | **0条**：AudioOnlyServer + NegativeSeq 从未触发过                |
| 旧日志 `句子完成，合并75656字节...` (13:25-13:26)               | 旧代码偶尔能拆分（可能依赖其他机制），但15:41后又失效                             |

**结论：火山引擎 seed-tts-2.0 双向 TTS 不使用** **`NegativeSeq`(0b11=3) 标记句子边界，实际使用的是** **`LastNoSeq`(0b10=2)**（"Last packet with no sequence"——最后一个音频包且无序号字段）。当前代码只检测 `NegativeSeq`，漏掉了 `LastNoSeq`，因此所有句子的 PCM 在 `AudioOnlyServer` 分支不断累积，直到 Session 结束时 `TTSSentenceEnd` 才一次性配对输出。

## 实施方案

### 步骤 1：在 tts\_service.py 的 AudioOnlyServer 分支中增加 LastNoSeq 检测

将 [tts\_service.py:L266](file:///d:/project/PDFVox/app/services/tts_service.py#L266) 的条件从：

```python
if msg.flag == MsgTypeFlagBits.NegativeSeq:
```

扩展为同时检测 `LastNoSeq`：

```python
if msg.flag in (MsgTypeFlagBits.NegativeSeq, MsgTypeFlagBits.LastNoSeq):
```

### 步骤 2：增加调试日志以确认协议实际行为

在 `AudioOnlyServer` 分支开头增加一条 DEBUG 级别日志，记录每条消息的 type、flag、payload 大小，用于验证服务器实际使用什么 flag 标记句子边界。格式：

```
[TTS接收方-DEBUG] AudioOnlyServer消息: flag={msg.flag.name}, payload_size={len(msg.payload)}
```

### 步骤 3：验证

* 语法检查

* 确认导入无误（`MsgTypeFlagBits` 已导入，`LastNoSeq` 是其成员）

## 风险评估

* 极低风险：仅在条件中增加一个 flag 值比较，不改变任何其他逻辑

* 如果 `LastNoSeq` 也不是正确边界，调试日志将暴露服务端实际使用的 flag 值，便于进一步定位

