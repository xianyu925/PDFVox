# Plan: Fix ASR endpoint - bigmodel_async is not streaming

## 根因诊断

测试结果揭示了真正的问题，跟 VAD 无关：

```
ASR receive error (connection closed): no close frame received or sent
Transcript (0.8s): ''   ← 0.8秒就结束了，根本没等到识别结果
```

### 关键证据链

| 证据 | 含义 |
|---|---|
| WebSocket 连接成功 (Test 4) | API Key/网络正常 |
| `no close frame received or sent` | 服务器主动断开 TCP，不发 close frame |
| 0.8s 就结束 | 服务器收到音频后立即关闭连接 |
| 从未收到 `ASRResponse` | 服务器不走流式响应路径 |
| **端点名为 `bigmodel_async`** | **这是异步端点，不是流式端点** |

### `bigmodel_async` vs `bigmodel`

Volcengine ASR 有两类端点：

| 端点 | 模式 | 工作方式 |
|---|---|---|
| `.../bigmodel_async` | **异步** | 提交音频 → 服务器关闭连接 → 结果通过回调/轮询获取 |
| `.../bigmodel` | **流式同步** | 提交音频 → 同一条 WebSocket 上实时返回 `ASRResponse` |

当前代码用的是 `bigmodel_async`，但接收逻辑却是按流式同步写的（发完音频后等在同一个 WebSocket 上收 `ASRResponse`）。服务器收到音频后启动了异步任务就关闭了连接——客户端永远等不到结果。

## 修复方案

### 唯一改动：`asr_service.py:L48`

```python
# 修改前
self.endpoint = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"

# 修改后
self.endpoint = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"
```

`resource_id` 保持不变（`volc.seedasr.sauc.duration`），因为模型和计费方式不变。

### 验证

用 `test_asr_mic.py` 重新测试：
```bash
D:\machine_learning\anaconda\envs\PDFVox\python.exe scripts/test_asr_mic.py --duration 5
```

预期结果：
- 不再出现 `no close frame received or sent`
- `ASRResponse` 正常返回
- 转录文本非空

## 受影响文件

| 文件 | 变更 |
|---|---|
| `app/services/asr_service.py` | 第 48 行：去掉 `_async` 后缀 |

## 风险

- **极低**：仅删除 6 个字符
- 如果流式端点需要不同的 `resource_id`，运行时会报错，按错误提示调整即可
