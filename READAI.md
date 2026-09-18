# PDFVox v1.1.0 — AI 编程助手项目指南

> 本文面向维护 PDFVox 的开发者与 AI 编程助手。内容以 `v1.1.0` 当前代码为准，描述真实功能、架构边界、关键状态和修改约束。

## 1. 项目定位与版本状态

PDFVox 是一个 FastAPI Web 应用，将 PDF 课件逐页转换为 AI 教授风格的流式语音讲解，并在浏览器中同步展示页面、完整句子字幕和字级朗读高亮。

- 当前开发版本：`v1.1.0`
- Python 版本号来源：`app/version.py`
- 主应用入口：`python run.py`
- 默认地址：`http://localhost:8000`
- 独立 TTS 服务：`python -m app.tts_server`，默认监听 `8001`
- 当前上传接口只接受 `.pdf`。PPT/PPTX 需要先导出为 PDF。

核心数据流：

```text
上传 PDF
  → pdfplumber 渲染页面图像
  → 火山引擎豆包多模态 LLM 生成讲稿
  → 火山引擎双向 WebSocket TTS 逐句合成 24 kHz PCM
  → SSE 推送到浏览器
  → Web Audio API 播放并同步字幕、进度和页面
```

## 2. v1.1.0 功能范围

### 2.1 文档与讲解

- 上传、校验并持久化 PDF；默认大小上限为 50 MB。
- 懒加载并渲染所有 PDF 页面，支持滚动页码识别和沉浸式全屏单页展示。
- 支持全书或单页流式讲解，LLM 输出和 TTS 输入并发执行。
- 讲解时使用相邻页摘要补充上下文，并提前预取后续页面摘要。
- 每句音频携带页面、句子、时长、句序号和字级时间戳。
- 生成任务记录到 SQLite，可通过任务 ID 查询状态。
- 取消按 `file_id + session_id` 隔离，不会误停其他浏览器会话。

### 2.2 播放器与时间轴

- 浏览器仅把已经收到的 PCM 音频计入总时长；未生成的未来音频不会扩展进度条。
- 总时长由 PCM 字节数计算，服务端提供的 `duration` 仅作为无音频数据时的后备值。
- 拖动进度条是浏览器本地 DVR 回放，不会因拖动触发尚未生成的音频。
- 左方向键回退 5 秒，不足 5 秒时回到开头。
- 右方向键快进 5 秒，不足 5 秒时跳到当前已生成音频结尾。
- 支持 `0.5x`、`0.75x`、`1x`、`1.25x`、`1.5x`、`2x`。
- `Shift + ←` 与 `Shift + →` 分别降低和提高一档倍速。
- 在输入框、文本域或可编辑区域中按方向键不会触发播放器快捷键。
- 双击已有音频的 PDF 页面会跳到该页音频起点；尚未生成时提示“音频还在生成中...”。

### 2.3 续接生成与字幕

- 终止生成只关闭当前 SSE 并发送取消请求，已经收到的音频、时间轴和播放队列不会清空。
- 继续生成从 `resumePage` 开始；若当前页只生成了一部分，则通过 `skip_sentences` 跳过已有句子。
- 音频使用 `page:index` 去重，避免恢复生成时重复追加已存在的句子。
- seek 后字幕仍展示完整句子，而不是只展示剩余片段。
- 字幕按 TTS 时间戳定位当前字；一个时间戳包含多个字符时会均分为逐字区间。

### 2.4 语音问答

- 支持文本问题或浏览器录音问题。
- 浏览器录音重采样为 16 kHz 单声道 WAV；服务端使用本地 faster-whisper 转写。
- 使用 faster-whisper 内置的 ONNX Silero VAD；初始化失败时退化到 RMS 能量检测，不额外引入 PyTorch。
- 问答会使用当前页图像、从第 1 页到当前页的已缓存讲稿和当前会话历史。
- 每个 `file_id + session_id` 最多保留最近 5 轮问答。
- LLM 回答文本和 TTS 回答音频通过 SSE 流式返回。

### 2.5 独立 TTS HTTP 服务

`app/tts_server.py` 是可运行的辅助服务，不属于主应用路由：

- `GET /health`：健康状态和版本。
- `GET /status`：运行状态和输出目录。
- `POST /tts`：将单段文本合成为 WAV。
- `POST /tts/batch`：顺序处理最多 100 段文本，允许部分成功。

### 2.6 Windows 桌面交付

- `desktop_main.py` 在随机回环端口启动 FastAPI，并由 pywebview 承载现有界面。
- 首次启动显示 `setup.html`，用户只需填写 LLM/TTS 两个 API Key。
- API Key 通过 keyring 保存到 Windows 凭据管理器，接口和日志不返回密钥正文。
- 保存密钥后原地重建 LLM/TTS 客户端，不要求用户手工重启应用。
- 数据库、上传文件、日志和模型缓存写入 `%LOCALAPPDATA%\PDFVox`，与只读安装目录分离。
- 桌面服务器只监听 `127.0.0.1`，使用每次启动生成的随机令牌和 HttpOnly Cookie 保护本地接口。
- PyInstaller 使用 onedir，Inno Setup 生成可安装和卸载的 Windows 安装程序。

## 3. 技术与 API 选型

| 能力 | 当前实现 |
|---|---|
| Web 框架 | FastAPI + uvicorn |
| LLM | OpenAI Python SDK，连接火山引擎 Ark 的 OpenAI 兼容地址 |
| LLM 同步调用 | `OpenAI.responses.create`，用于摘要和完整讲稿 |
| LLM 流式调用 | `AsyncOpenAI.chat.completions.create(stream=True)` |
| TTS | `websockets` 直接连接火山引擎双向 WebSocket 接口 |
| TTS 协议 | 项目内 `protocols.py` 实现的自定义二进制协议 |
| TTS 音频 | 24 kHz、16-bit、单声道 PCM，开启字幕时间戳 |
| ASR | faster-whisper base，CPU int8；内置 ONNX Silero VAD |
| PDF | pdfplumber，页面以 150 DPI PNG 渲染 |
| 前端 | 原生 ES Module、Web Audio API、EventSource、MediaRecorder |
| 数据 | SQLite + 文件系统 + 浏览器内存状态 |

注意：LLM 使用 OpenAI SDK 只是客户端协议选择，实际请求发送到 `LLM_BASE_URL` 指定的火山引擎 Ark；TTS 不使用 OpenAI SDK，也不是普通 REST 调用。

## 4. 目录与职责

```text
PDFVox/
├── run.py                         # 主 Web 服务启动入口
├── desktop_main.py                 # pywebview 桌面启动入口
├── PACKAGING.md                    # Windows 构建与发布说明
├── app/
│   ├── version.py                 # 唯一版本号来源
│   ├── paths.py                   # 源码/冻结资源与用户数据路径
│   ├── credentials.py             # 系统凭据存储抽象
│   ├── desktop_security.py        # 桌面会话令牌中间件
│   ├── config.py                  # 环境变量和项目路径
│   ├── main.py                    # 主 FastAPI 应用、页面和路由注册
│   ├── tts_server.py              # 可独立启动的 TTS HTTP 服务
│   ├── models/
│   │   ├── db.py                  # SQLite 表、上传/任务/持久缓存操作
│   │   └── schemas.py             # Pydantic 响应模型
│   ├── routers/
│   │   ├── upload.py              # PDF 上传与校验
│   │   ├── pdf_view.py            # PDF 信息、文本和页面图像
│   │   ├── ai_explain.py          # 讲解 SSE、回放、取消、状态
│   │   ├── qa.py                  # 文本/语音问答 SSE
│   │   └── app_settings.py        # 首次配置与凭据管理接口
│   ├── services/
│   │   ├── runtime.py             # 路由共享的进程级服务实例
│   │   ├── settings_service.py    # API Key 配置用例
│   │   ├── cache.py               # 线程安全 TTL/LRU 内存缓存
│   │   ├── explain_service.py     # 讲解编排、缓存、取消与恢复
│   │   ├── explain_audio.py       # 页面音频生成、完整性检查与缓存
│   │   ├── explain_prompts.py     # 摘要、实时讲解、完整讲稿提示词
│   │   ├── llm_service.py         # 火山 Ark/OpenAI 兼容 LLM 客户端
│   │   ├── tts_service.py         # 双向 WebSocket TTS 与 WAV 导出
│   │   ├── protocols.py           # TTS 二进制消息编解码
│   │   ├── asr_service.py         # 延迟加载的本地 ASR/VAD
│   │   ├── qa_service.py          # 多轮问答上下文和 LLM/TTS 编排
│   │   └── pdf_service.py         # PDF 读取、渲染与文件级锁
│   └── utils/logging.py           # 文件/控制台日志
├── web/
│   ├── index.html                 # 上传页
│   ├── setup.html                 # 首次启动 API Key 配置页
│   ├── viewer.html                # 阅读、讲解和问答页
│   ├── status.html                # 任务状态页
│   └── static/
│       ├── viewer.js              # 页面初始化、PDF 懒加载、双击与全屏
│       ├── viewer-state.js        # 共享状态和 DOM 引用
│       ├── viewer-stream.js       # SSE、生成按钮状态机、录音问答
│       ├── viewer-audio.js        # Web Audio 队列、seek、倍速和快捷键
│       ├── viewer-timeline.js     # PCM 时长、格式化和页面起点查询
│       ├── viewer-subtitles.js    # 完整句子渲染和字级高亮
│       └── viewer-pages.js        # 页面切换与页码同步
├── tests/                         # 自动化测试
├── requirements.txt              # 运行依赖
├── requirements-dev.txt          # 测试依赖
├── requirements-build.txt        # Windows 构建依赖
├── packaging/                     # PyInstaller、Inno Setup 与构建脚本
├── pytest.ini                    # 仅收集 tests/
└── .env.example                  # 配置模板
```

`doc/`、`.pytest_cache/`、`.env`、运行数据库和用户上传内容不应提交到 Git。

## 5. 运行时架构

### 5.1 共享服务

`app/services/runtime.py` 创建一个进程级 `ExplainService`，并把其中的 LLM/TTS 实例传给 `QAService`。讲解和问答因此共享：

- 摘要、完整讲稿和页面音频缓存；
- LLM/TTS 配置；
- 对同一 PDF 的上下文视图。

不要在路由模块中重新实例化 `ExplainService`，否则取消令牌和缓存会分裂。

首次保存或更换 API Key 后，`runtime.reconfigure_api_clients()` 只替换外部 API 客户端并保留讲稿、音频缓存和 QA 历史。

### 5.2 讲解双流

每页讲解包含两个异步任务：

```text
LLM task ──文本片段──> text_queue ──> TTS task ──音频事件──> out_queue ──> SSE
```

- LLM 生成文本时，TTS 已预连接 WebSocket。
- TTS 根据 `。！？，；\n!?,;` 分句，超过 60 字时强制切分。
- `<END>` 表示 LLM 文本结束，`<DONE>` 表示 TTS 输出结束。
- 任一服务错误都转换为 `error` 事件，不应缓存不完整页面。
- 客户端断开或主动取消时，后台任务应被取消并清理。

### 5.3 缓存层

缓存分为两层：

1. `TTLCache`：进程内、线程安全、TTL + LRU，用于低延迟读取。
2. SQLite `generated_cache`：JSON 持久缓存，带到期时间和最大条目数。

缓存内容包括：

- 页面摘要 `summary`；
- 完整讲稿 `script`；
- 完整页面音频 `audio`；
- 会话问答历史 `qa_history`。

讲解缓存键包含内容类型、文件 ID、页码、课程名和 LLM 模型；音频键还包含 TTS 音色与资源 ID。修改模型、音色或课程名不会错误复用旧内容。

### 5.4 数据库

SQLite 位于 `${STORAGE_PATH}/pdfvox.db`，导入 `app.models.db` 时自动初始化：

| 表 | 用途 |
|---|---|
| `uploads` | 文件 ID、原文件名、磁盘路径、总页数 |
| `tasks` | 生成任务、页码、状态、错误详情和更新时间 |
| `generated_cache` | 带 TTL 的讲稿、音频和问答历史 JSON |

每个数据库函数自行打开和关闭连接。旧数据库缺失 `uploads.total_pages` 时会自动迁移。

## 6. 主应用 HTTP 接口

### 6.1 页面与健康检查

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 上传页 |
| GET | `/viewer.html?file_id=...` | 阅读与讲解页 |
| GET | `/status.html` | 任务状态页 |
| GET | `/api/health` | 返回状态、消息和 `1.1.0` 版本 |
| GET | `/setup.html` | 首次启动和 API Key 更新页 |
| GET | `/settings/status` | 返回两个 API Key 的配置状态，不返回密钥 |
| POST | `/settings/configure` | 仅限本机，保存两个 API Key 并重建客户端 |
| DELETE | `/settings/credentials` | 仅限本机，清除系统凭据 |

### 6.2 上传与 PDF

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/upload/` | multipart 字段 `file`；仅 PDF；返回 `file_id` 和总页数 |
| GET | `/pdf/{file_id}` | 返回文件名和页码数组 |
| GET | `/pdf/{file_id}/page/{page}` | 返回页面文本和 base64 PNG data URL |

上传过程按 1 MB 分块写入，超限、空文件、损坏文件都会删除临时目标文件并返回 4xx。

### 6.3 讲解

| 方法 | 路径 | 关键参数 |
|---|---|---|
| GET | `/explain/all-stream-v3/{file_id}` | `course_name`、`from_page`、`skip_sentences`、`resume_generation`、`session_id` |
| GET | `/explain/stream-v3/{file_id}/page/{page_num}` | `course_name`、`session_id` |
| GET | `/explain/playback/seek/{file_id}/page/{page_num}` | `time_offset`、`ahead`、`course_name` |
| DELETE | `/explain/cancel/{file_id}` | 必填 `session_id` |
| GET | `/explain/status/{task_id}` | 查询任务状态 |

`all-stream-v3` 和 `stream-v3` 响应头包含 `X-Task-Id`。`playback/seek` 是服务端缓存回放接口；当前 Web 播放器的常规拖动优先使用浏览器已经保存的音频，不依赖该接口。

### 6.4 问答

`POST /qa/ask/stream` 使用 multipart/form-data：

| 字段 | 要求 |
|---|---|
| `file_id` | 必填 |
| `page_num` | 必填，默认 1，不能超出文档页数 |
| `session_id` | 必填，至少 8 个字符 |
| `course_name` | 可选，默认“课程” |
| `question` | 文本问题；与 `file` 至少提供一个 |
| `file` | WAV 或原始 PCM；默认最大 10 MB |

## 7. SSE 协议

每条消息格式为：

```text
data: {JSON}\n\n
```

流结束哨兵为：

```text
data: [DONE]\n\n
```

主要事件：

| `type` | 重要字段 | 含义 |
|---|---|---|
| `global_start` | `task_id`, `total_pages` | 全书生成开始 |
| `page_start` | `page` | 当前页开始 |
| `start` | `page` | 单页流水线开始 |
| `text` | `data`, `page` | LLM 文本片段；问答会向客户端发送 |
| `audio` | `data`, `page`, `index`, `sentence`, `duration`, `word_timestamps` | 一句 PCM 音频 |
| `end` | `page` | 单页流水线结束 |
| `page_complete` | `page`, `total_pages` | 全书流中的页面完成 |
| `global_end` | `task_id` | 全书完成 |
| `cancelled` | `ts` | 当前会话已取消 |
| `error` | `message`, `page?` | 可展示错误 |

音频事件示例：

```json
{
  "type": "audio",
  "data": "<base64 PCM>",
  "page": 3,
  "index": 2,
  "sentence": "监督学习需要标注数据。",
  "duration": 2.48,
  "word_timestamps": [
    {"char": "监", "start": 0.08, "end": 0.23}
  ]
}
```

## 8. 前端关键状态与不变量

`viewer-state.js` 的 `state` 是各 ES 模块共享的唯一可变状态。修改播放器时必须保持以下不变量：

1. `generatedAudioChunks` 是已经到达浏览器的讲解音频真源；seek 只能从这里重建队列。
2. `timelineCursor` 是下一条新音频的写入位置，只在 `trackTimeline=true` 的首次接收时增长。
3. `liveWindowEnd` 是当前已生成音频的总时长，进度条 `max` 和总时长标签必须使用它。
4. 回放旧音频时必须传 `trackTimeline=false`，否则总时长会重复增长。
5. `playedTime` 使用音频内容时间；播放倍速只改变墙上时间，不改变时间轴总长度。
6. `playbackEpoch` 用于废弃旧播放器循环，seek/停止后旧 `onended` 不得覆盖新状态。
7. `currentSentenceStartTime` 与完整句子的时间戳共同决定字级高亮。
8. QA 音频不计入讲解时间轴。
9. 新生成流程可以重置时间轴；“继续生成”必须使用 `skipReset=true` 保留已有音频。
10. `sessionId` 保存在 `sessionStorage`，用于取消与问答历史隔离，但它不是身份认证凭据。

## 9. 配置

复制 `.env.example` 为 `.env`：

```env
LLM_API_KEY=your_llm_api_key_here
LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
LLM_MODEL=doubao-seed-2-0-mini-260428
TTS_API_KEY=your_tts_api_key_here
TTS_API_RESOURCE_ID=seed-tts-2.0
TTS_VOICE=zh_female_yingyujiaoxue_uranus_bigtts
STORAGE_PATH=output
MAX_UPLOAD_SIZE_MB=50
MAX_AUDIO_SIZE_MB=10
CACHE_TTL_SECONDS=21600
SUMMARY_CACHE_MAX_ENTRIES=256
AUDIO_CACHE_MAX_ENTRIES=32
GENERATED_CACHE_MAX_ENTRIES=128
QA_HISTORY_MAX_DOCUMENTS=100
LOG_TO_FILE=true
```

此外可配置 `HOST`、`PORT`、`AUTO_RELOAD`、`LOG_LEVEL` 和 `LOG_TO_CONSOLE`。`LOG_TO_FILE=false` 可关闭 `log.txt`；自动化测试通过 `tests/conftest.py` 使用该设置，避免测试数据混入运行日志。相对路径统一相对于仓库根目录解析，因此可以从其他工作目录启动。

不要提交真实 `.env`、API 密钥、上传文档、SQLite 数据库、生成音频或日志。

## 10. 启动与测试

推荐使用名为 `PDFVox` 的 Conda 环境：

```powershell
conda activate PDFVox
pip install -r requirements.txt
pip install -r requirements-dev.txt
python run.py
```

测试：

```powershell
python -m pytest -q
```

`pytest.ini` 只收集 `tests/`，避免把依赖真实麦克风、模型或外部 API 的脚本误当成自动化测试。当前测试基线为 37 项，覆盖：

- API 参数与恢复生成；
- 路径配置和 SQLite 持久缓存；
- TTL/LRU 缓存淘汰；
- 会话级取消隔离和部分页面不缓存；
- PCM 精确裁剪及字时间戳重定位；
- 前端回放不重复扩展总时长；
- LLM 响应兼容；
- TTS 字幕协议和错误事件；
- ASR/VAD 延迟加载与无 PyTorch 推理路径；
- QA 历史隔离和五轮上限；
- 主应用与独立 TTS 服务版本元数据。

## 11. 已知边界

- 主应用没有用户认证或授权，不应直接暴露到不受信任的公网。
- 浏览器刷新会丢失客户端的播放位置和本地音频时间轴；服务端生成缓存仍可能可用。
- SQLite 和进程内共享实例面向单机部署；多进程/多节点需要共享数据库、分布式缓存和任务协调。
- 首次语音识别可能下载并加载较大的 ASR/VAD 模型，启动后第一次识别延迟较高。
- 讲解和 TTS 依赖外部火山引擎服务、有效密钥、模型权限和网络连接。
- 当前前端没有构建步骤，也没有浏览器端 E2E 测试；前端行为主要由 Python 静态检查测试和人工浏览器验证保障。
- `doc/` 被 `.gitignore` 忽略；其中资料不属于发布内容。

## 12. 维护规则

- 修改版本时只编辑 `app/version.py`，再同步本文与 README 的展示文本，并创建同名 Git 标签。
- 修改 SSE 字段时，同时检查路由、`viewer-stream.js`、`viewer-audio.js` 和测试。
- 修改音频时间轴时，优先验证“新音频追加”和“旧音频回放”不会同时增长 `liveWindowEnd`。
- 修改续接生成时，必须验证停止后已有音频不消失、恢复页不重复、部分页能继续生成。
- 修改字幕时，必须验证普通播放、页内 seek、倍速和无时间戳降级路径。
- 不要在事件循环中直接执行 PDF、SQLite、同步 LLM 或 WAV 写入等阻塞操作；使用 `asyncio.to_thread`。
- 新功能至少补充对应自动化测试，并保持 `python -m pytest -q` 全部通过。
