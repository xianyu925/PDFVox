# PDFVox Windows 安装指南

本文面向直接使用 PDFVox 的 Windows 用户。无需安装 Python、Conda 或开发工具。

## 1. 使用条件

- Windows 10 或 Windows 11，64 位系统。
- 可访问火山引擎 API 的网络。
- 一个可调用豆包大模型的 `LLM API Key`。
- 一个可调用 Seed TTS 2.0 的 `TTS API Key`。
- 使用语音问答时，需要允许应用访问麦克风；首次识别还会下载 faster-whisper base 模型。

## 2. 下载并校验

下载 [PDFVox-Setup-v1.1.0.exe](release/PDFVox-Setup-v1.1.0.exe)，不要单独下载 `dist` 目录中的文件。

当前安装包信息：

- 版本：`1.1.0`
- 大小：约 `87.6 MiB`
- SHA-256：`1EC0CDEE2B26ACE7B9433E9141DB56E1E1DFFDAF34CC53C46ED69B6D86704F09`

可以在安装包所在目录打开 PowerShell 并执行：

```powershell
Get-FileHash .\PDFVox-Setup-v1.1.0.exe -Algorithm SHA256
```

输出应与仓库中的 [SHA256SUMS.txt](release/SHA256SUMS.txt) 一致。若不一致，请不要运行该文件。

## 3. 安装

1. 双击 `PDFVox-Setup-v1.1.0.exe`。
2. 按安装向导继续，可选择是否创建桌面快捷方式。
3. PDFVox 默认安装到当前用户目录，不需要管理员权限。
4. 安装完成后勾选“启动 PDFVox”，或使用开始菜单/桌面快捷方式启动。

当前安装包尚未进行商业代码签名，Windows SmartScreen 可能显示“Windows 已保护你的电脑”。请先确认下载来源和上面的 SHA-256；确认无误后，可选择“更多信息”查看发布者和继续运行。来源或校验值不明时不要绕过提示。

## 4. 首次配置

首次启动会出现配置页，只需填写：

- `LLM API Key`：火山引擎 Ark/豆包大模型密钥。
- `TTS API Key`：火山引擎语音合成密钥。

点击“保存并进入 PDFVox”。模型、接口地址、TTS 资源和默认音色已内置，无需填写。密钥保存在当前 Windows 用户的凭据管理器中，不会写入 PDF、数据库或日志。

进入首页后即可上传 PDF。PPT/PPTX 文件需要先在演示软件中导出为 PDF。

## 5. 数据位置与升级

用户数据位于：

```text
%LOCALAPPDATA%\PDFVox\
├── data\          # PDF、数据库和生成缓存
├── logs\log.txt   # 运行日志
└── models\        # 本地语音识别模型
```

安装新版本时直接运行新版安装包即可。安装器使用稳定的应用标识执行覆盖升级，上述用户数据和 Windows 凭据不会被覆盖。

## 6. 卸载与彻底清理

在 Windows“设置 → 应用 → 已安装的应用”中找到 PDFVox 并卸载。常规卸载会保留用户 PDF、模型和凭据，方便以后重新安装。

如需彻底清理，请在确认不再需要历史数据后手动删除 `%LOCALAPPDATA%\PDFVox`，并在 Windows“凭据管理器”中删除名为 `PDFVox` 的相关凭据。

## 7. 常见问题

- 启动后仍停留在配置页：确认两个 Key 均非空，并检查 Windows 凭据管理器是否可用。
- 讲解生成失败：检查网络、Key 是否有效，以及账号是否拥有对应模型和 TTS 资源权限。
- 第一次语音问答较慢：应用需要下载并加载本地 ASR 模型，之后会复用缓存。
- 页面或生成状态异常：关闭应用后重新启动；问题仍存在时查看 `%LOCALAPPDATA%\PDFVox\logs\log.txt`。
- 被安全软件阻止：先核对 SHA-256，不要直接关闭安全软件；可将日志与拦截信息提交给维护者排查。
