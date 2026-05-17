# READAI — PDFVox 项目技术文档

## 1. 项目定位

PDFVox 将 PDF/PPT 课程讲义自动转化为第一人称 AI 教授的口语化讲解，前端以流式方式同步播放语音与字幕，支持时间轴拖动、字级字幕高亮、录音问答等交互。

**核心流程**：上传 PDF → 多模态 LLM 逐页生成讲稿 → TTS 逐句合成语音 → 浏览器实时播放

## 2. 技术栈

| 层 | 技术 |
|----|------|
| 后端框架 | FastAPI + uvicorn |
| LLM | 火山引擎 doubao-seed (OpenAI 兼容协议), 多模态 vision |
| TTS | 火山引擎双向 WebSocket TTS (24kHz PCM, 自定义二进制协议) |
| ASR | faster-whisper base + Silero VAD |
| PDF | pdfplumber (150 DPI 渲染为 PNG) |
| 前端 | 原生 ES 模块 (无构建工具), Web Audio API, SSE, MediaRecorder |
| 存储 | SQLite (上传/任务记录), 文件系统 (output/) |

## 3. 项目结构

```
PDFVox/
├── run.py                          # 启动入口: uvicorn.run("app.main:app")
├── app/
│   ├── config.py                   # Settings 类, 从 .env / os.environ 读取所有配置
│   ├── main.py                     # FastAPI 应用工厂: 挂载路由、静态文件、Jinja2 模板
│   ├── models/
│   │   ├── db.py                   # SQLite CRUD: uploads + tasks 两张表
│   │   └── schemas.py              # Pydantic 模型: UploadResponse, PageInfo, ExplainRequest 等
│   ├── routers/
│   │   ├── upload.py               # POST /upload/         PDF 上传
│   │   ├── pdf_view.py             # GET  /pdf/{id}        页面信息/图像
│   │   ├── ai_explain.py           # GET  /explain/...     流式讲解 (SSE)
│   │   └── qa.py                   # POST /qa/ask/stream   流式问答 (SSE)
│   ├── services/
│   │   ├── explain_service.py      # 讲解编排核心: 摘要缓存、LLM+TTS 双流并发
│   │   ├── qa_service.py           # 问答编排: 多轮对话历史管理、prompt 构建
│   │   ├── llm_service.py          # LLM 调用: 同步(OpenAI responses) + 异步流式(chat.completions)
│   │   ├── tts_service.py          # TTS WebSocket 管理: 连接、分句、逐句合成
│   │   ├── asr_service.py          # 语音识别: Silero VAD + faster-whisper
│   │   ├── pdf_service.py          # PDF 渲染: pdfplumber 文本提取 + 150 DPI 图像
│   │   └── protocols.py            # 火山 TTS 二进制协议: Message 序列化/反序列化
│   └── utils/
│       └── logging.py              # 统一日志: 文件(log.txt) + 控制台, LOG_LEVEL 可控
├── web/
│   ├── index.html                  # 上传页
│   ├── viewer.html                 # 讲解播放页 (主界面)
│   ├── status.html                 # 任务状态页
│   └── static/
│       ├── viewer.js               # 入口 (~180行): DOM 初始化、PDF 加载、全屏控制
│       ├── viewer-state.js         # 全局状态 (~40行): state + dom 共享对象
│       ├── viewer-audio.js         # 音频引擎 (~350行): Web Audio 播放、DVR seek、字级高亮
│       └── viewer-stream.js        # SSE 流处理 (~400行): 按钮状态机、录音问答
├── .env.example                    # 环境变量模板
└── requirements.txt
```

## 4. 配置项 (.env)

| 变量 | 用途 | 默认值 |
|------|------|--------|
| `API_KEY` | 火山引擎 API Key (LLM) | — |
| `ACCESS_TOKEN` | 火山引擎 Access Token (TTS) | — |
| `API_APP_KEY` | 火山引擎 App Key (TTS) | — |
| `TTS_VOICE` | TTS 音色 ID | — |
| `MODEL_ENDPOINT` | LLM 自定义 endpoint (可选) | — |
| `STORAGE_PATH` | PDF 存储目录 | `output/` |
| `HOST` / `PORT` | 服务监听地址 | `0.0.0.0:8000` |
| `AUTO_RELOAD` | uvicorn 热重载 | false |
| `LOG_LEVEL` | 日志级别 | INFO |
| `LOG_TO_CONSOLE` | 是否输出到控制台 | true |

## 5. API 路由一览

### 5.1 上传
- `POST /upload/` — 上传 PDF 文件 (multipart), 返回 `{file_id, filename, url}`

### 5.2 PDF 查看
- `GET /pdf/{file_id}` — 获取 PDF 页数信息
- `GET /pdf/{file_id}/page/{page}` — 获取单页文本 + base64 PNG 图像

### 5.3 讲解 (SSE 流式)

- `GET /explain/all-stream-v3/{file_id}?course_name=&from_page=` — **全书流式讲解**。逐页推送 `page_start` → `audio`*N → `page_complete` → ... → `global_end`
- `GET /explain/stream-v3/{file_id}/page/{page_num}?course_name=` — **单页流式讲解**
- `GET /explain/playback/seek/{file_id}/page/{page_num}?time_offset=` — **DVR seek 回放**。从页内指定时间偏移开始推送该页的缓存音频
- `DELETE /explain/cancel/{file_id}` — 取消当前生成任务
- `GET /explain/status/{task_id}` — 查询任务状态

SSE 事件格式:
```json
// 全局开始
{"type": "global_start", "total_pages": 30, "ts": 1.234}

// 单页开始
{"type": "page_start", "page": 3, "ts": 1.234}

// 音频句子 (核心事件)
{
  "type": "audio",
  "data": "<base64 PCM, 24kHz 16-bit mono>",
  "page": 3,
  "sentence": "监督学习需要标注数据...",
  "duration": 3.456,
  "word_timestamps": [
    {"char": "监", "start": 0.12, "end": 0.30},
    {"char": "督", "start": 0.30, "end": 0.46}
  ]
}

// 单页完成
{"type": "page_complete", "page": 3, "total_pages": 30, "ts": 1.234}

// 全书完成
{"type": "global_end", "ts": 1.234}

// 错误/取消
{"type": "error", "message": "...", "ts": 1.234}
{"type": "cancelled", "ts": 1.234}

// 流结束哨兵
data: [DONE]
```

### 5.4 问答
- `POST /qa/ask/stream` — 流式问答。multipart: `file` (音频 WAV, 可选) + `question` (文本, 可选) + `file_id` + `page_num`。返回 SSE 流含 `audio` 事件

### 5.5 其他
- `GET /` → index.html (上传页)
- `GET /viewer.html?file_id=xxx` → viewer.html (讲解页)
- `GET /status.html` → status.html
- `GET /api/health` → `{"status": "ok"}`

## 6. 后端核心架构

### 6.1 讲解生成流水线 (ExplainService)

```
用户点击"一键生成" → GET /explain/all-stream-v3/{file_id}
  │
  ├─ 逐页循环:
  │   ├─ 并发获取: 页面图像 (pdfplumber 150DPI PNG) + 相邻页摘要 (带 3s 超时)
  │   ├─ LLM 流式生成讲稿 (doubao-seed-1-8-251228, vision)
  │   │   └─ system_prompt: 大学教授第一人称, 口语化, 逐层展开
  │   │   └─ user_prompt: 课程名 + 页码 + 前后页摘要 + 页面图像 base64
  │   └─ TTS 流式合成语音 (火山 WebSocket, 双向协议)
  │       ├─ 文本分句: 按中英文标点切句 (。！？，；\n!?,;), 最长 60 字符
  │       └─ 逐句: StartSession → TaskRequest → 接收 AudioOnlyServer + FullServerResponse
  │           └─ 提取 PCM (24kHz 16-bit mono) + word_boundary 时间戳
  │
  ├─ 缓存策略:
  │   ├─ summary_cache[file_id][page_num] → 单页摘要 (用于相邻页上下文)
  │   ├─ summary_cache[f"script_{file_id}_{page_num}"] → 完整讲稿
  │   └─ page_audio_cache[file_id][page_num] → 页内分句音频列表
  │
  └─ 取消机制: _cancel_tokens[file_id] = True, LLM/TTS 流中检查并中断
```

### 6.2 LLM 调用 (LLMService)

**两条路径**:
- **同步**: `generate_explanation()` — 使用 `OpenAI().responses.create()` (火山 responses API), 模型 `doubao-seed-2-0-pro-260215`, 用于摘要/完整讲稿生成
- **异步流式**: `stream_explanation()` — 使用 `AsyncOpenAI().chat.completions.create(stream=True)`, 模型 `doubao-seed-1-8-251228`, 逐 chunk yield `{"type": "text", "data": "..."}`

**Prompt 格式转换**: 用户代码中 `type: "text"` → 火山格式 `type: "input_text"`, `type: "image_url"` → 火山格式 `type: "input_image"`

### 6.3 TTS 二进制协议 (protocols.py)

火山引擎双向 WebSocket TTS 使用自定义二进制协议，消息格式:

```
| Version(4b) | HeaderSize(4b) | MsgType(4b) | Flags(4b) |
| Serialization(4b) | Compression(4b) | Reserved(8b) |
| Optional Extensions (if HeaderSize > 1) |
| Payload (variable, 4-byte size prefix) |
```

关键 MsgType:
- `FullClientRequest (0b0001)` — 客户端请求 (JSON payload)
- `FullServerResponse (0b1001)` — 服务端响应 (含 event + session_id)
- `AudioOnlyServer (0b1011)` — 纯音频数据 (PCM)

关键 EventType:
- `StartConnection(1)` / `ConnectionStarted(50)` — 建连握手
- `StartSession(100)` / `SessionStarted(150)` — 开始合成会话
- `TaskRequest(200)` — 提交合成文本
- `TTSResponse(352)` — 服务端返回 word_boundary
- `SessionFinished(152)` — 会话结束

TTS 每次 WS 连接建立后，逐句创建 session → 提交文本 → 接收 PCM + word_boundary → 关闭 session。音频参数: 24kHz, 16-bit, mono, PCM。

### 6.4 ASR (ASRService)

- 模型: faster-whisper base (CPU, int8 量化), Silero VAD
- 流程: 前端录音 → WebM → 前端转 16kHz WAV → POST /qa/ask/stream → ASRService 转写 → 文本
- 懒加载: WhisperModel 首次调用时初始化, 从 HuggingFace 下载模型文件

### 6.5 问答流程 (QAService)

```
POST /qa/ask/stream
  ├─ 1. ASR 转写 (如果传了音频)
  ├─ 2. 后台触发讲稿生成 (asyncio.create_task, 不阻塞)
  ├─ 3. 构建 prompt:
  │   ├─ 有讲稿缓存 → _QA_SYSTEM_WITH_SCRIPT (讲稿 + 历史 + 页面图像)
  │   └─ 无讲稿缓存 → _QA_SYSTEM_WITHOUT_SCRIPT (历史 + 页面图像)
  ├─ 4. LLM 流式 + TTS 流式并发 (与讲解相同的双流模式)
  └─ 5. 保存对话历史 (最多 5 轮)
```

## 7. 前端架构

### 7.1 模块划分

```
viewer.js (入口, ~180行)
  ├── 初始化 DOM 引用 → dom 对象
  ├── loadEntirePDF(): 先获取总页数, 渲染骨架屏, 逐页懒加载图像
  ├── detectCurrentPage(): 滚动检测当前页
  ├── 全屏控制: requestFullscreen / exitFullscreen
  └── 启动: setupPlayerControls() + setupExplainAllButton() + setupAskButton()

viewer-state.js (共享状态, ~40行)
  └── state: { totalPages, currentPage, audioCtx, nextPlayTime, audioQueue,
               playedTime, liveWindowEnd, pageTimeMap, sentenceStartTimes,
               currentWordTimestamps, currentSentenceStartTime, ... }
  └── dom: {} (由 viewer.js 填充)
  └── getQueryParam()

viewer-audio.js (音频引擎, ~350行)
  ├── initAudioContext(): 创建 AudioContext + GainNode
  ├── queueAudioChunk(base64, page, sentence, duration, wordTimestamps)
  │   └── base64 → ArrayBuffer → Int16Array → AudioBuffer → BufferSource → schedule
  ├── processAudioQueue(): 队列消费循环, 逐句播放
  │   └── 播放时: 切换 active-page, 滚动到当前页, 渲染逐字字幕
  ├── seekToTime(targetSeconds): DVR 跳转
  │   └── 二分查找 sentenceStartTimes → fetch /explain/playback/seek → 重建音频队列
  ├── updateProgressUI(): 100ms 定时更新进度条 + 字级高亮
  └── setupPlayerControls(): 播放/暂停, seek slider, 音量, 左右方向键 ±5s

viewer-stream.js (SSE 流处理, ~400行)
  ├── 按钮状态机: IDLE ↔ GENERATING ↔ PAUSED
  ├── _startExplainStream(): EventSource → onmessage 分发 audio/page_start/end/cancelled
  └── setupAskButton(): 录音 → VAD 静音检测 → WebM→16kHz WAV → POST /qa/ask/stream
      └── 录音后显示浮动面板: 播放回答 → "继续讲解" / "关闭"
```

### 7.2 音频数据流

```
SSE (base64 PCM) → queueAudioChunk()
  → base64ToArrayBuffer() → Int16Array → AudioBuffer (24kHz)
  → BufferSourceNode → GainNode → destination
  → schedule at nextPlayTime (无缝拼接)
  → onended: 更新 playedTime, 触发下一句
```

### 7.3 DVR 时间轴机制

- `sentenceStartTimes[]`: 每句的全局起始时间 (累积 duration)
- `liveWindowEnd`: 已生成的总时长
- `playedTime`: 已播放时长
- `playbackStartTime`: 当前播放段在 AudioContext 时间轴上的起始点
- Seek 时: 二分查找目标句 → fetch seek API → 从目标句偏移开始重新推送音频 → 重建队列

### 7.4 字级字幕高亮

- TTS 返回 `word_boundary` (每个字的 start/end 时间)
- 前端将字幕渲染为 `<span class="sc" data-idx="i">字</span>`
- `updateProgressUI()` 每 100ms 计算当前播放位置在句子内的偏移，匹配对应字的索引，设置 `color: #fbbf24`

## 8. 数据存储

- **SQLite** (`output/pdfvox.db`):
  - `uploads`: file_id, filename, path, created_at
  - `tasks`: task_id, file_id, page, status, detail, created_at, updated_at
- **文件系统** (`output/`):
  - 上传的 PDF: `{file_id}.pdf`
  - 日志: `log.txt` (项目根目录)

## 9. 日志系统

- `app/utils/logging.py` 提供 `get_logger(name)` 工厂函数
- 全局配置一次: FileHandler(log.txt) + 可选 StreamHandler
- 通过 `LOG_LEVEL` 环境变量控制: DEBUG | INFO | WARNING | ERROR | CRITICAL
- 格式: `时间 - 模块名 - 级别 - 消息`

## 10. 关键设计决策

1. **LLM+TTS 双流并发**: 不等待 LLM 生成完整讲稿再 TTS。LLM 边生成边通过 `asyncio.Queue` 传递给 TTS, TTS 按标点分句后逐句合成, 首字延迟 < 1s
2. **摘要预取**: 生成当前页讲解时, 后台 asyncio.create_task 预热后续页摘要, 使相邻页上下文能在 3s 超时内就绪
3. **页级音频缓存**: 每页的分句音频生成后存入 `page_audio_cache`, seek 和二次访问直接命中缓存, 不重复调用 TTS
4. **TTS WebSocket 逐句 session**: 每句创建一个 session (StartSession → TaskRequest → 接收 PCM → SessionFinished), 而非一个长 session 流式推送, 简化错误恢复
5. **前端无构建工具**: 原生 ES 模块 + import/export, 适合快速迭代
6. **取消令牌**: `_cancel_tokens` 字典在 LLM 流、TTS 流、主循环三个位置检查, 确保取消信号即时生效
7. **两套 LLM 模型**: 非流式用 `doubao-seed-2-0-pro` (质量优先), 流式用 `doubao-seed-1-8-251228` (速度优先)
