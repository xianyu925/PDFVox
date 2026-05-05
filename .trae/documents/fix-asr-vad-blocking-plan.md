# Plan: QA 服务 ASR 转录失败修复

## 根因分析

通过完整代码链路追踪，确认问题在 **Silero VAD 假阴性拦截**。

### 故障链路

```
前端录音 → WAV 转换 ✅ → FormData 上传 ✅ → WAV 解包 ✅
    → asr_service.transcribe_pcm_to_text()
        → Silero VAD 检测 → 返回 speech_timestamps=[]
            → return ""   ← 直接返回空，跳过了远程 ASR！
    → transcript = ""
    → question = None（前端从不发送 question 字段）
    → not question and not transcript → 触发错误 ❌
```

### 关键证据

log.txt 中所有 `ASR 转写得到:` 日志都为空：

```
ASR 转写得到: 
ASR 转写得到: 
ASR 转写得到:     ← 连续 5 次都是空
```

VAD 模型加载成功（`Silero VAD model loaded`），但每次都将用户录音误判为静默，导致远程 ASR 从未被调用。

### 涉及的代码位置

[asr\_service.py:L266-L271](file:///d:/project/PDFVox/app/services/asr_service.py#L266-L271) — VAD 空结果直接 `return ""`：

```python
if not speech_timestamps:
    try:
        os.remove(tmp_path)
    except Exception:
        pass
    return ""  # ← 这里阻止了远程 ASR 调用
```

## 修复方案

### 步骤 1：移除 VAD 拦截，改为可选的静态检测

**文件**：[asr\_service.py:L250-L281](file:///d:/project/PDFVox/app/services/asr_service.py#L250-L281)

将 VAD 从"硬拦截"改为"软检测"：

```python
# 修改前：VAD 无语音 → return "" → 跳过远程 ASR
# 修改后：VAD 无语音 → 记录日志 → 继续走远程 ASR（让火山引擎决定）
```

具体改动：

1. 移除 `if not speech_timestamps: return ""` 的早期返回
2. 当 VAD 检测到无语音时，仅记录一条 INFO/WARNING 日志，**继续执行远程 ASR**
3. 简化 VAD 代码块，将临时文件清理提取到 `finally`

### 步骤 2：增强 ASR 日志

**文件**：[asr\_service.py](file:///d:/project/PDFVox/app/services/asr_service.py)

1. VAD 检测通过/不通过时，输出语音段数量和时间戳数
2. 远程 ASR 返回时，输出完整转录文本和长度
3. ASR 各阶段添加耗时统计（可选），便于后续诊断

### 步骤 3：qa.py 改进错误提示

**文件**：[qa.py:L197-L199](file:///d:/project/PDFVox/app/routers/qa.py#L197-L199)

将错误消息从：

```
需要上传音频或提供问题文本
```

改为更明确的诊断信息：

```
语音识别未能获取到文本，请确保麦克风正常并重试
```

使前端能在 ASR 失败时向用户提供更有意义的反馈。

### 步骤 4：验证

* [ ] 语法检查通过

* [ ] VAD 空结果不再拦截远程 ASR

* [ ] QA 流程能获取到转录文本

* [ ] 错误消息对用户有意义

## 受影响文件

| 文件                            | 变更              |
| ----------------------------- | --------------- |
| `app/services/asr_service.py` | 移除 VAD 硬拦截，增强日志 |
| `app/routers/qa.py`           | 改进错误消息          |

## 风险评估

* **极低**：仅删除 3 行 VAD 早期返回代码 + 添加日志

* VAD 本意是节省 API 调用成本，但当前导致 100% 失败——去掉拦截后每次问答都会调用远程 ASR（成本微增，体验剧增）

* 如果后续需要成本控制，可改为基于 PCM 能量值的简单阈值检测（比 Silero VAD 更可靠）

