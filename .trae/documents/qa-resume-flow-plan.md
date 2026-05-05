# Plan: 问答服务完善 — 暂停讲解 → 提问回答 → 继续讲解

## 当前状态分析

### 已有功能

* **前端录音 + ASR**：录音自动静默检测，转 WAV 后 POST 到 `/qa/ask/stream`

* **后端 Q\&A**：[qa.py](file:///d:/project/PDFVox/app/routers/qa.py) — ASR → LLM 流式 → TTS 流式 → SSE 下发

* **后端 TTS**：已重构为每句一个独立 Session，`stream_tts_input` 内部自动按句分割

* **前端 Q\&A 播放**：接收 SSE audio 事件，通过 `queueAudioChunk` 入队播放

### 缺失环节

| 环节        | 现状                                          | 期望                  |
| --------- | ------------------------------------------- | ------------------- |
| 提问时暂停讲解   | 关闭 SSE + suspend AudioContext → **讲解流彻底终止** | 暂停讲解，**记住中断页码**     |
| Q\&A 回答播放 | ✅ 已有（音频入队 + 字幕）                             | 无变化                 |
| 继续讲解      | ❌ 不存在，按钮直接重置                                | 显示"继续讲解"按钮，点击后从断点续播 |

## 实施方案

### 步骤 1：后端 — all-stream-v3 支持 `from_page` 参数

**文件**：[ai\_explain.py:L183-L241](file:///d:/project/PDFVox/app/routers/ai_explain.py#L183-L241)

```python
@router.get("/all-stream-v3/{file_id}")
async def explain_all_pages_stream_v3(
    file_id: str,
    course_name: str = "机器学习导论",
    from_page: int = 1,          # ← 新增
):
    ...
    for page_num in range(from_page, total_pages + 1):  # ← 改这里
        ...
```

并在开始前调用 `service._reset_cancel(file_id)` 清除之前的取消令牌（否则新流一启动就被取消）。

### 步骤 2：前端 — 新增 `resumePage` 全局变量

**文件**：[viewer.js](file:///d:/project/PDFVox/web/static/viewer.js)

在 `currentPlayingPage` 旁新增：

```javascript
let resumePage = 1;  // 提问中断后恢复的页码
```

### 步骤 3：前端 — 修改「提问」按钮：暂停而非终止

**文件**：[viewer.js:L529-L694](file:///d:/project/PDFVox/web/static/viewer.js#L529-L694)

**修改前**：

```javascript
// 停止任何正在进行的全书流式 → 直接关闭
if (currentEventSource) { currentEventSource.close(); currentEventSource = null; }
```

**修改后**：

```javascript
// 记录中断页码 → 取消流 → 暂停播放
resumePage = currentPlayingPage || currentPage;
if (currentEventSource) { currentEventSource.close(); currentEventSource = null; }
if (audioCtx) await audioCtx.suspend();
audioQueue = [];  // 清空讲解音频队列（Q&A 音频将独立播放）
```

### 步骤 4：前端 — Q\&A 完成后显示「继续讲解」按钮

**文件**：[viewer.js:L660-L665](file:///d:/project/PDFVox/web/static/viewer.js#L660-L665)

Q\&A SSE 流收到 `[DONE]` 后，不直接移除 `progressContainer`，而是：

```javascript
// 替换按钮为"继续讲解"
progressContainer.innerHTML = `
    <div id="ask-info">回答播放完毕</div>
    <button id="resume-stream">继续讲解</button>
`;
askBtn.textContent = originalText;
askBtn.disabled = false;
```

### 步骤 5：前端 — 实现「继续讲解」逻辑

**文件**：[viewer.js](file:///d:/project/PDFVox/web/static/viewer.js)

```javascript
document.getElementById('resume-stream').addEventListener('click', async () => {
    progressContainer.remove();
    initAudioContext();
    await audioCtx.resume();
    
    const fileId = getQueryParam('file_id');
    const courseName = courseNameInput.value.trim();
    
    const streamUrl = `/explain/all-stream-v3/${fileId}?course_name=${encodeURIComponent(courseName)}&from_page=${resumePage}`;
    currentEventSource = new EventSource(streamUrl);
    
    // 复用现有的 onmessage 处理逻辑（与 explainAllBtn 一致）
    // ... 相同的 audio / page_start / error 处理
});
```

### 步骤 6：验证清单

* [ ] `from_page` 从第 N 页开始流式生成

* [ ] 提问时讲解暂停、不丢页码

* [ ] Q\&A 语音+字幕正确播放（逐句拆分）

* [ ] Q\&A 完成后「继续讲解」按钮出现

* [ ] 点击继续后从断点页码恢复讲解

* [ ] 继续讲解的语音+字幕正确播放

## 受影响文件

| 文件                                | 变更                                       |
| --------------------------------- | ---------------------------------------- |
| `app/routers/ai_explain.py`       | `all-stream-v3` 增加 `from_page` 参数        |
| `app/services/explain_service.py` | 新增 `_reset_cancel()` 公开调用（已有方法，无需改动）     |
| `web/static/viewer.js`            | 新增 `resumePage`，修改 ask 按钮流程，新增「继续讲解」按钮逻辑 |

## 风险评估

* **低**：`from_page` 仅改变循环起点，不影响现有逻辑

* `_reset_cancel` 已有但只在类内部使用（private），需确认在 api 层调用的一致性

* 前端改动集中在一处事件处理，不影响其他交互

