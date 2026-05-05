# Fix Subtitle Freeze After First Sentence

## Why
字幕在显示第一句后不再更新。根因是 TTS 接收方对火山引擎双向 TTS 协议中句子边界信号的解析方式有误——代码依赖 `FullServerResponse` + `TTSSentenceEnd` 事件来分割句子，但火山引擎实际通过 `AudioOnlyServer` 消息的 `NegativeSeq` flag（sequence ≤ 0）标记句子结束。由于当前代码从未检测到这个边界，所有句子的 PCM 音频被合并为一个 chunk，最终只与第一句字幕文本配对输出，导致字幕冻结。

## What Changes
- 在 `tts_service.py` 的接收循环中，新增对 `AudioOnlyServer` + `NegativeSeq` 的句子边界检测逻辑
- 保留原有的 `FullServerResponse` + `TTSSentenceEnd` 检测作为兼容回退
- 增强日志以便后续诊断句子分割行为

## Impact
- Affected specs: TTS 流式服务、字幕同步
- Affected code: `app/services/tts_service.py` (核心修改), 无需修改前端代码

## MODIFIED Requirements

### Requirement: TTS Sentence Boundary Detection
TTS 接收方 SHALL 正确识别火山引擎双向 TTS 协议中的句子结束信号，确保每句语音与其对应的字幕文本正确配对。

#### Scenario: AudioOnlyServer with NegativeSeq marks sentence end
- **WHEN** 接收方收到 `AudioOnlyServer` 类型的消息且 `flag == MsgTypeFlagBits.NegativeSeq`
- **THEN** 当前累积的 PCM 数据与 pending_sentences 队列中下一个等待的句子文本配对，作为一个完整的 `audio` 事件 yield 出去
- **AND** `current_sentence_pcm` 被重置为空 bytearray

#### Scenario: FullServerResponse with TTSSentenceEnd (兼容)
- **WHEN** 接收方收到 `FullServerResponse` 类型的消息且 `event == EventType.TTSSentenceEnd`
- **THEN** 行为同上，作为句子结束信号处理（保留兼容）

#### Scenario: AudioOnlyServer with PositiveSeq accumulates audio
- **WHEN** 接收方收到 `AudioOnlyServer` 类型的消息且 `flag == MsgTypeFlagBits.PositiveSeq`
- **THEN** 音频数据追加到 `current_sentence_pcm`，不触发句子分割
