 

# PDFVox Windows 打包与发布

## 架构

桌面版继续复用 FastAPI 与现有前端，由 `desktop_main.py` 在随机回环端口启动本地服务，再使用 pywebview 展示。程序资源只读，运行数据写入：

```text
%LOCALAPPDATA%\PDFVox\
├── data\          # PDF、SQLite、生成缓存
├── logs\log.txt   # 运行日志
└── models\        # Hugging Face / ASR 模型缓存
```

两个 API Key 通过 Python keyring 保存到 Windows 凭据管理器。桌面服务器只监听 `127.0.0.1`，每次启动生成随机会话令牌并以 HttpOnly Cookie 保护接口。

## 构建环境

- Windows x64
- Python/Conda `PDFVox` 环境
- Inno Setup（`ISCC.exe` 需要在 PATH）

```powershell
conda activate PDFVox
pip install -r requirements-build.txt
python -m pytest -q
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

构建脚本会先生成独立运行目录，再启动其中的 `PDFVox.exe --smoke-test`，验证冻结后的后端、路由、前端资源以及 ONNX VAD 均可加载；通过后才生成安装包。

ASR 复用 faster-whisper 自带的 ONNX VAD，不捆绑 PyTorch。当前 Windows x64 构建的独立目录约 300 MiB，Inno Setup 压缩后的安装包约 90 MiB；具体大小会随依赖版本变化。

产物：

```text
dist\PDFVox\                 # PyInstaller onedir，用于冒烟测试
release\PDFVox-Setup-v1.1.0.exe
release\SHA256SUMS.txt
```

## 发布前验证

必须在没有 Python 和 Conda 的干净 Windows 用户环境中验证：

1. 普通用户权限安装、启动和卸载。
2. 首次启动只填写 LLM/TTS 两个 Key。
3. 关闭并重新启动后密钥仍可用。
4. PDF 上传、讲解、停止/继续、seek、倍速、字幕和 QA。
5. 首次语音问答时 ASR 模型下载目录和进度提示。
6. 中文用户名、带空格路径和无管理员权限场景。
7. 软件关闭后本地端口已释放。

## 版本升级

发布新版本时同步修改：

- `app/version.py`
- `README.md` 与 `READAI.md`

构建脚本会从 `app/version.py` 读取版本号并传给 Inno Setup。

`build/` 与 `dist/` 不要提交到 Git。对外发布的 `release/*.exe` 使用 Git LFS 管理，首次克隆或拉取发布产物前需安装 Git LFS；`SHA256SUMS.txt` 由构建脚本自动生成，并与安装包一起提交。

用户数据位于安装目录之外，覆盖安装和卸载默认不会删除用户 PDF、缓存或密钥。
