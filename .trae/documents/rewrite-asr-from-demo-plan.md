# Plan: 按官方 sauc demo 重写 ASR 服务

## Demo 与当前代码的关键差异

| 项目 | Demo (正确) | 当前代码 (错误) |
|---|---|---|
| FullClientRequest flag | `POS_SEQUENCE` + seq 序号 | `NoSeq` |
| Audio packet flag | `POS_SEQUENCE` (普通), `NEG_WITH_SEQUENCE` (最后一包，-seq) | `NoSeq` (普通), `LastNoSeq` (最后一包) |
| Payload 压缩 | **GZIP** | **无压缩** |
| audio config 中 format | `"wav"` | `"pcm"` |
| 响应解析 | GZIP 解压 → JSON `result.text` | 直接 JSON 解码（误） |
| 连接握手 | 无 StartConnection (纯二进制帧) | `start_connection` + 等 `ConnectionStarted` |
| 发送方式 | 自构造二进制帧 | `protocols.py` Message 层 |

## 实施步骤

### 步骤 1：修改 `_connect()`
- 去掉 `start_connection()` 调用和 `ConnectionStarted` 等待
- ASR 协议无需连接握手，连接后直接发送二进制帧
- 保留 `websockets` 库（和 TTS 统一），但跳过 `protocols.py` Message 层

### 步骤 2：新增 ASR 二进制帧构造方法（在 `ASRService` 类中）
- `_build_full_client_request(config_dict)` → POS_SEQUENCE flag + seq=1 + GZIP(json)
- `_build_audio_request(pcm_chunk, is_last)` → POS_SEQUENCE (普通) / NEG_WITH_SEQUENCE (最后一包) + seq + GZIP(pcm)

### 步骤 3：新增 ASR 响应解析方法
- `_parse_response(raw_bytes)` → 解析 header → 提出 seq/event → GZIP 解压 → JSON 解析 → 返回 dict(含 result.text, code, is_last_package)

### 步骤 4：重写 `transcribe_pcm_to_text`
- 用新 builder 和 parser 替换现有 `protocols.py` 调用
- 流程：connect → full_client_request → 逐包发送 audio_request（每次间隔 200ms） → 收响应直到 `is_last_package` → 返回 `result.text`

### 步骤 5：重写 `detect_speaking_from_pcm`
- 同样用新 builder/parser

### 步骤 6：修复 Seq 管理
- 每发送一包递增 seq
- 最后一包 flag 设为 `NEG_WITH_SEQUENCE` 且 seq 变负（`-seq`）

### 步骤 7：验证
- 语法检查
- 运行 test_asr_mic.py 验证转录

## 受影响文件

| 文件 | 变更 |
|---|---|
| `app/services/asr_service.py` | 核心重写：去掉 protocols.py 依赖，直接构造/解析二进制帧 |

## 风险

- 低：仅修改 `asr_service.py`，不影响 TTS/LLM 等其他服务
- `protocols.py` 不变（TTS 继续用）
- `websockets` 库不变（不需新增 `aiohttp` 依赖）
