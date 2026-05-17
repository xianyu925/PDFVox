# PDFVox — AI 驱动的 PDF 沉浸式语音讲解

## 项目简介

PDFVox 将 PDF/PPT 课程讲义自动转化为第一人称 AI 教授的口语化讲解，前端以流式方式同步播放语音与字幕，支持时间轴拖动、字级字幕高亮、录音问答等交互。

**核心流程**：上传 PDF → 多模态 LLM 逐页生成讲稿 → TTS 逐句合成语音 → 浏览器实时播放

## 功能

- **流式讲解**：SSE 推送，LLM + TTS 并发，首字延迟 < 1s
- **DVR 时间轴**：仿直播播放器的进度条，句级精确拖动回退
- **字级字幕高亮**：逐字 `<span>` 渲染，当前朗读的字实时高亮
- **语音问答**：录音 → ASR 转写 → LLM 流式回答 → TTS 语音播放
- **多轮对话**：同一 PDF 内支持 5 轮追问
- **沉浸模式**：全屏 PPT + 字幕叠加，左右方向键 ±5s 跳转

## 项目结构

```
PDFVox/
├── run.py                        # 启动入口
├── app/
│   ├── config.py                 # 全局配置（从 .env 读取）
│   ├── main.py                   # FastAPI 应用
│   ├── models/
│   │   ├── db.py                 # SQLite 上传/任务记录
│   │   └── schemas.py            # Pydantic 数据模型
│   ├── routers/
│   │   ├── upload.py             # POST /upload/       PDF 上传
│   │   ├── pdf_view.py           # GET  /pdf/{id}      页面图像
│   │   ├── ai_explain.py         # GET  /explain/...   流式讲解 / seek / cancel
│   │   └── qa.py                 # POST /qa/ask/stream 流式问答
│   ├── services/
│   │   ├── explain_service.py    # 讲解编排：摘要缓存、LLM+TTS 双流
│   │   ├── qa_service.py         # 问答服务：多轮历史、prompt 构建
│   │   ├── llm_service.py        # 火山引擎 doubao 多模态 API
│   │   ├── tts_service.py        # 火山引擎双向 WebSocket TTS
│   │   ├── asr_service.py        # faster-whisper + Silero VAD 语音识别
│   │   ├── pdf_service.py        # pdfplumber 页面渲染 (150 DPI)
│   │   └── protocols.py          # 火山 TTS WebSocket 二进制协议
│   └── utils/
│       └── logging.py            # 统一日志配置（LOG_LEVEL 环境变量）
├── web/
│   ├── index.html                # 上传页面
│   ├── viewer.html               # 讲解播放页面
│   ├── status.html               # 任务状态页
│   └── static/
│       ├── viewer.js             # 入口：PDF 加载、全屏、模块组装
│       ├── viewer-state.js       # 共享状态 / DOM 引用
│       ├── viewer-audio.js       # Web Audio 播放、DVR 进度、seek、字级高亮
│       └── viewer-stream.js      # SSE 流处理、按钮状态机、录音问答
├── .env.example                  # 环境变量模板
└── requirements.txt
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`：

```env
API_KEY=your_volcengine_api_key
ACCESS_TOKEN=your_volcengine_access_token
API_APP_KEY=your_volcengine_app_key
TTS_VOICE=zh_female_yingyujiaoxue_uranus_bigtts
LOG_LEVEL=INFO
LOG_TO_CONSOLE=true
```

### 3. 启动

```bash
python run.py
```

浏览器访问 `http://localhost:8000`。

## 日志控制

通过 `LOG_LEVEL` 环境变量控制日志等级，支持 `DEBUG | INFO | WARNING | ERROR | CRITICAL`，默认 `INFO`。

```bash
# 开发调试
LOG_LEVEL=DEBUG python run.py

# 仅错误
LOG_LEVEL=ERROR python run.py
```

## 前端模块说明

| 模块 | 行数 | 职责 |
|------|------|------|
| `viewer.js` | ~180 | 入口：DOM 引用初始化、PDF 加载、全屏 |
| `viewer-state.js` | ~40 | 所有共享状态 + DOM 引用 |
| `viewer-audio.js` | ~350 | 音频播放、队列、DVR 时间轴、seek、字级字幕 |
| `viewer-stream.js` | ~400 | SSE 流（全页讲解、恢复讲解、录音提问）、按钮状态机 |

使用 ES 模块（`type="module"`），无需构建工具。

## SSE 音频事件格式

```json
{
  "type": "audio",
  "data": "<base64 PCM, 24kHz 16-bit mono>",
  "page": 3,
  "sentence": "监督学习需要标注数据，而无监督学习不需要。",
  "duration": 3.456,
  "word_timestamps": [
    { "char": "监", "start": 0.12, "end": 0.30 },
    { "char": "督", "start": 0.30, "end": 0.46 }
  ]
}
```

## 技术栈

| 层 | 技术 |
|----|------|
| 后端框架 | FastAPI + uvicorn |
| LLM | 火山引擎 doubao-seed (多模态) |
| TTS | 火山引擎双向 WebSocket TTS (24kHz PCM) |
| ASR | faster-whisper + Silero VAD |
| PDF | pdfplumber (150 DPI 渲染) |
| 前端 | 原生 ES 模块，Web Audio API，SSE |
| 存储 | SQLite (上传记录) |
