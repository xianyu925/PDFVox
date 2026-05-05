# Plan: 录音手动结束 + 回答字幕实时播放

## 1. 新增「提问结束」按钮

当前录音只有两种结束方式：静默 800ms 自动停止，或"取消"按钮（丢弃录音）。缺少手动结束选项。

### 修改 `viewer.js:L630-L652`

将录音面板 HTML 从"取消"一个按钮改为"提问结束"+"取消"两个按钮：

```html
<div id="ask-info">请开始提问...</div>
<button id="ask-finish">提问结束</button>     <!-- 新增：结束录音，提交ASR -->
<button id="ask-cancel">取消</button>         <!-- 保留：放弃录音 -->
```

`#ask-finish` click handler 调用 `stopAll()`（停止录音，触发 `recorder.onstop` → 转 WAV → POST → LLM+TTS 流式回答）。

### 同时更新状态文案

录音过程中 `#ask-info` 显示："正在聆听...（说完请点击「提问结束」）"

## 2. Q&A 回答字幕实时播放

检查现有代码，`queueAudioChunk` → `processAudioQueue` 已经会在每个 audio chunk 播放前更新 `globalSubtitle`。Q&A 音频流通过同一路径，**字幕已天然同步**。

需确认一点：Q&A 播放期间不应被讲解的 `processAudioQueue` 状态干扰。当前 `askBtn click` 已调用 `initAudioContext()` 重置 `audioQueue` 和 `isProcessingQueue`，Q&A 音频独立入队播放，字幕同步正确。无需额外代码修改。

### 验证清单

- [ ] 点击"提问" → 面板显示"提问结束 | 取消"两个按钮
- [ ] 点击"提问结束" → 停止录音 → ASR → LLM → TTS → 回答音频+字幕播放
- [ ] 回答播放时，`globalSubtitle` 逐句更新
- [ ] 点击"取消" → 放弃录音，恢复原状

## 受影响文件

| 文件 | 变更 |
|---|---|
| `web/static/viewer.js` | 录音面板增加「提问结束」按钮，状态文案调整 |
