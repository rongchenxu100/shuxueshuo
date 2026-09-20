# 缺图阻断（2026-09-15）

作者策略 v6。没有干预模型推理区预写 JSON，没有新真实模型调用，也未接入生产前端/API。

- 提示词区分文字中的图号引用与实际图片。缺图必须在对应层标记，不想象图形性质。
- 独立候选服务返回并保存 continuation：needs_confirmation、blocked=true、extraction.missing_figure、supplement_image 和缺图列表。IR 合法与匹配成功均不能取消阻断。
- 候选 HTML 保留题意，展示补充图片提示。无缺图仍只是 candidate_only，不是允许求解的证明。
- smoke 的 passed 只表示抽取基准是否通过；汇总同时记录 continuation，不能将缺图样本的正确抽取解读成可以继续构建。
- 生产接入约束已写入主设计 §12：阻断所有后续模型调用和投影等阶段，前端展示缺图列表、已提取题意和补图入口，用户补图后重新抽取。

离线 **98 passed**，见 [测试日志](offline-tests.txt)。覆盖 matched/unmatched 均阻断、四个嵌套缺图完整返回、IR 与阻断产物保留、展示提示、无缺图不签发就绪证明。Ruff 和 git diff --check 通过。

[服务端阻断示例](continuation-example.json) · [候选展示](gold-candidate.html) · [系统提示词](system-prompt.txt) · [尺寸记录](measurements.json)
