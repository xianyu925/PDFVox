# PDF自动讲解项目 (PDFVox)

## 项目简介

PDFVox 是一个将 PDF 解析、智能理解、自然讲解与语音合成一体化的工具，支持PPT课程讲解。
- 读取 PDF 并转为图像内容
- 调用多模态大模型（火山引擎 doubao-seed-1-8）生成逐页讲解
- 生成页间衔接段落并合并入 TTS 输入
- 使用火山引擎 seed-tts-2.0 进行语音合成
- 输出 mp3 语音文件
- 提供Web界面，支持课程名称输入和交互式操作

## 当前功能

1. **核心功能**：
   - `PDFVox.analysis(pdf_path)`：解析 PDF，导出每页图像base64
   - `PDFVox.understand(content, course_name)`：流式理解每页并生成讲解，自动生成过渡段落
   - `PDFVox.save_explanations_to_txt(explanations, output_dir)`：写入 `output/explanations.txt`，每页讲解 + 对应衔接段
   - `PDFVox.TTS(explanations, output_dir)`：将每页讲解+衔接合并后调用TTS生成音频
   - `PDFVox.process(pdf_path, output_dir, course_name)`：完成全流程处理

2. **Web界面功能**：
   - PDF上传与预览
   - 左右布局界面
   - 课程名称输入（必填）
   - 一键生成所有页面讲解
   - 完整课程音频合并播放
   - 分页音频播放
   - 滚动检测当前页面

## 项目结构

```
PDFVox/
├── main.py              # 主入口文件
├── config.py            # 配置文件
├── app/                # Web应用模块
│   ├── main.py          # FastAPI应用入口
│   ├── config.py        # Web应用配置
│   ├── models/          # 数据模型
│   │   ├── __init__.py
│   │   ├── db.py        # 数据库操作
│   │   └── schemas.py   # 数据模式定义
│   ├── routers/         # API路由
│   │   ├── __init__.py
│   │   ├── ai_explain.py # AI讲解相关路由
│   │   ├── audio.py     # 音频相关路由
│   │   ├── pdf_view.py  # PDF浏览相关路由
│   │   └── upload.py    # 上传相关路由
│   ├── services/        # 服务层
│   │   ├── __init__.py
│   │   ├── explain_service.py # 讲解服务
│   │   ├── llm_service.py     # LLM服务
│   │   ├── pdf_service.py     # PDF服务
│   │   ├── protocols.py       # 通信协议
│   │   └── tts_service.py     # TTS服务
│   └── tts_server.py    # TTS服务器
├── web/                # 前端网页文件
│   ├── index.html       # 上传页面
│   ├── viewer.html      # 讲解查看页面
│   └── static/          # 静态资源
├── requirements.txt     # 依赖文件
├── .env                # 环境变量文件
├── output/             # 运行输出目录
└── README.md           # 项目说明
```

## 运行环境

- Python 3.8+
- Windows/macOS/Linux 均可

## 依赖安装

```bash
pip install -r requirements.txt
```

## 配置

1. **环境变量配置**：
   创建 `.env` 文件并设置以下内容：
   ```
   API_KEY=your_volcengine_doubao_api_key_here
   API_APP_KEY=your_volcengine_app_key_here
   ACCESS_TOKEN=your_volcengine_access_token_here
   TTS_VOICE=zh_female_yingyujiaoxue_uranus_bigtts
   ENABLE_LOGGING=true
   ```

2. **默认配置**：
   编辑 `config.py`：
   - `DEFAULT_PDF_PATH`：默认输入 PDF 文件路径
   - `DEFAULT_OUTPUT_DIR`：输出目录（音频 + 文稿）

## 使用方法

### 1. 命令行模式

```bash
python main.py --mode legacy
```

执行后：
- 音频输出到 `output/page_{n}.mp3`

### 2. Web界面模式（推荐）

```bash
python main.py --mode web
```

然后在浏览器中访问：`http://localhost:8000`

**Web界面使用流程**：
1. 上传PDF文件
2. 进入讲解页面
3. 输入课程名称（如"机器学习导论"）
4. 点击"生成讲解"按钮
5. 查看讲解内容并播放音频

## 细节说明

- 支持批量处理所有PDF页面
- 使用摘要缓存机制，避免重复生成消耗token
- 生成讲解时考虑前后页面摘要，使讲解更流畅
- 提供生成时间统计，显示各阶段耗时
- 支持音频合并功能，生成完整课程音频
- 左右布局界面设计，用户体验更佳
- 实现WebSocket协议与TTS服务通信
- 集成SQLite3数据库存储上传和任务信息

## 注意事项

- 确保火山引擎API密钥、APP KEY和访问令牌有效且可用
- 需要安装FFmpeg以支持音频合并功能
- 若接口返回非200，请检查网络和调用频率限制
- 如出现乱码，请确认系统编码 UTF-8
- 对于较大的PDF文件，处理时间可能较长
- 生成讲解时需要输入课程名称

## 技术栈

- **后端**：Python, FastAPI
- **前端**：HTML, CSS, JavaScript
- **PDF处理**：PyPDF2, pdfplumber
- **AI模型**：火山引擎 doubao-seed-1-8 (多模态)
- **语音合成**：火山引擎 seed-tts-2.0
- **音频处理**：pydub
- **WebSocket通信**：websockets
- **数据库**：SQLite3

## 可能需要的依赖版本

请参考 `requirements.txt`。