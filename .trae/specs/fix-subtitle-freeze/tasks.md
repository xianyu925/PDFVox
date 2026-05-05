# Tasks

- [x] Task 1: 修复 tts_service.py 中的句子边界检测逻辑
  - [x] SubTask 1.1: 在 AudioOnlyServer 分支中增加 NegativeSeq 检测，当 flag 为 NegativeSeq 时执行句子配对与 yield
  - [x] SubTask 1.2: 保留 FullServerResponse + TTSSentenceEnd 作为兼容回退路径
  - [x] SubTask 1.3: 增加日志输出，记录每次句子分割时的 pending_sentences 队列长度和 PCM 字节数
  - [x] SubTask 1.4: 处理边界情况——当 NegativeSeq 到达但 pending_sentences 为空时，记录警告日志并丢弃 PCM

- [x] Task 2: 验证修复效果
  - [x] SubTask 2.1: 检查代码语法和导入是否正确
  - [x] SubTask 2.2: 确认前端无需修改（字幕更新逻辑已正确，修复后自动生效）

# Task Dependencies
- Task 2 depends on Task 1
