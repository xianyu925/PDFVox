# PDF自动讲解项目 (PDFVox)

## 项目简介

PDFVox 是一个将 PDF 解析、智能理解、自然讲解与语音合成一体化的工具。
- 读取 PDF 并转为图像内容
- 调用多模态大模型（SiliconFlow/Qwen）生成逐页讲解
- 生成页间衔接段落并合并入 TTS 输入
- 输出 mp3 语音文件与单独 `explanations.txt` 文稿

## 当前功能

1. `PDFVox.analysis(pdf_path)`：解析 PDF，导出每页图像base64
2. `PDFVox.understand(content)`：流式理解每页并生成讲解，自动生成过渡段落
3. `PDFVox.save_explanations_to_txt(explanations, output_dir)`：写入 `output/explanations.txt`，每页讲解 + 对应衔接段
4. `PDFVox.TTS(explanations, output_dir)`：将每页讲解+衔接合并后调用TTS生成音频
5. `main.py`：启动入口，调用 `process(pdf_path, output_dir)` 完成全流程

## 项目结构

- `main.py`
- `config.py`
- `pdfvox/__init__.py`
- `pdfvox/pdf_vox.py`
- `requirements.txt`
- `output/`（运行输出目录）

## 运行环境

- Python 3.8+
- Windows/macOS/Linux 均可

## 依赖安装

```bash
pip install -r requirements.txt
```

## 配置

编辑 `config.py`：
- `API_KEY`：SiliconFlow API Key 或等效模型 Key
- `DEFAULT_PDF_PATH`：默认输入 PDF 文件路径
- `DEFAULT_OUTPUT_DIR`：输出目录（音频 + 文稿）

## 使用方法

```bash
python main.py
```

执行后：
- 音频输出到 `output/page_{n}.mp3`
- 文稿输出到 `output/explanations.txt`

## 细节说明

- 支持流式输出，主逻辑基于 `requests.post(..., stream=True)`
- `understand()` 生成 `explanation` 与 `transition` 字段
- `TTS()` 合并 `explanation + transition` 形成 `full_text` 提交语音接口

## 注意事项

- 确保 `API_KEY` 有效且可用
- 若接口返回非200，请检查网络和调用频率限制
- 如出现乱码，请确认系统编码 UTF-8

## 可能需要的依赖版本

请参考 `requirements.txt`。
