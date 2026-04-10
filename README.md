# PDF自动讲解项目 (PDFVox)

## 项目简介

PDFVox 是一个将 PDF 解析、智能理解、自然讲解与语音合成一体化的工具，支持PPT课程讲解。
- 读取 PDF 并转为图像内容
- 调用多模态大模型（SiliconFlow/Qwen3-VL-32B-Thinking）生成逐页讲解
- 生成页间衔接段落并合并入 TTS 输入
- 输出 mp3 语音文件与单独 `explanations.txt` 文稿
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
   - 逐页查看与导航
   - 课程名称输入
   - 生成讲解与语音
   - 音频播放

## 项目结构

```
PDFVox/
├── main.py              # 主入口文件
├── config.py            # 配置文件
├── pdfvox/             # 核心功能模块
│   ├── __init__.py
│   └── pdf_vox.py       # PDFVox核心实现
├── app/                # Web应用模块
│   ├── main.py          # FastAPI应用入口
│   ├── config.py        # Web应用配置
│   ├── models/          # 数据模型
│   ├── routers/         # API路由
│   ├── services/        # 服务层
│   ├── static/          # 静态文件
│   └── templates/       # HTML模板
├── requirements.txt     # 依赖文件
├── .env                # 环境变量文件
└── output/             # 运行输出目录
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
   API_KEY=your_siliconflow_api_key_here
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
- 文稿输出到 `output/explanations.txt`

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

- 支持流式输出，主逻辑基于 `requests.post(..., stream=True)`
- `understand()` 生成 `explanation` 与 `transition` 字段
- `TTS()` 合并 `explanation + transition` 形成 `full_text` 提交语音接口
- 使用多线程处理，提高生成速度
- 包含重试机制，增强稳定性

## 注意事项

- 确保 `API_KEY` 有效且可用
- 若接口返回非200，请检查网络和调用频率限制
- 如出现乱码，请确认系统编码 UTF-8
- 对于较大的PDF文件，处理时间可能较长

## 技术栈

- **后端**：Python, FastAPI
- **前端**：HTML, JavaScript
- **PDF处理**：PyPDF2, pdfplumber
- **AI模型**：SiliconFlow Qwen3-VL-32B-Thinking (多模态)
- **语音合成**：SiliconFlow FunAudioLLM/CosyVoice2-0.5B
- **并发处理**：concurrent.futures

## 可能需要的依赖版本

请参考 `requirements.txt`。