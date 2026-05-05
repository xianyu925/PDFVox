* [x] AudioOnlyServer + NegativeSeq 消息触发句子配对与 yield

* [x] AudioOnlyServer + PositiveSeq 消息仅累积 PCM，不触发配对

* [x] FullServerResponse + TTSSentenceEnd 保留作为兼容回退路径

* [x] pending\_sentences 为空时 NegativeSeq 到达，不会崩溃，仅记录警告

* [x] 代码无语法错误，导入完整

* [x] 字幕在前端能随每句语音正常切换更新
