# 通用平分与比例冲突校验（2026-09-15）

本轮修复独立 `problem_understanding` 校验器，未修改提示词、模型 schema、金标或遗漏政策，未切换生产入口。没有新模型调用。

## 校验行为

`midpoint` 或 `diagonal_bisects` 确定同一中点两侧等长；`cut_ratio` 或 `length_ratio` 给出这两段的比例时，两系数必须相等。精确数字不相等，或参数约束排除了系数相等的可能，返回 `constraint.bisection_ratio_conflict`。

例如 QS 平分 PR，却把 PR 被 QS 截出的两段写成 2:1，会被拒绝。把比例写在 QS 被 PR 截出的两段上不构成该矛盾。算法只使用基础关系，不读取题名、family、OCR 或金标。

- 依据明确交点、共线及中点关系关联长度；不同交点不猜测合并。
- 先解析局部身份再继承父层条件，局部同名遮蔽父层，不跨兄弟节点取条件。
- 保留 OR；仅所有备选分支都出现此冲突时拒绝。有分支未被反驳不表示已证明题目可解。
- 参数可取 1 时，不把 `h:1` 自动判错；`h>1`、`h=2` 等可证明矛盾时才拒绝。
- 报告包含相关事实的内部单元 ID、分支、比例及定向修复说明；沿现有文件产物持久化。候选和原文保持不变。
- 有界展开：最多 4,096 个逻辑分支、50,000 个展开事实项，检查工作预算 50,000；超限明确失败。

这不是完整几何一致性证明，也不识别自然语言中所有漏写条件。提示词能够诱导模型读对题意；此检查负责拦住已经写入 IR 的这一类可确定矛盾。

## 验证

共 **258 passed，6 skipped**。6 项是未开启的真实模型测试，本轮未执行实时集成。

新增 24 个几何校验用例覆盖比例正反、精确数、未知及受限参数、命名/内部交点、不同交点、OR、父子与兄弟隔离、原文不变、失败报告落盘和授权 patch 修复。新增 1 个真实 Provider 代码的录制响应测试，覆盖“推理耗尽且正式内容为空 → 原请求重试成功”，并确认 SDK 重试关闭、enabled/low、两次审计与未知 usage。

其余回归包括原五题固定哈希/离线投影、简洁 IR、等价比较、允许遗漏政策、视觉复核和生产抽取重试。运行命令（server 目录）：

```sh
.venv/bin/pytest -q tests/solver/test_understanding_geometry_consistency.py tests/solver/test_deepseek_vision_empty_retry.py tests/solver/test_understanding_acceptance.py tests/solver/test_understanding_cut_ratio.py tests/solver/test_understanding_equivalence.py tests/solver/test_understanding_v2.py tests/solver/test_understanding_authoring.py tests/solver/test_problem_domain_recorded.py tests/solver/test_problem_source_review.py tests/solver/test_deepseek_vision.py tests/solver/test_problem_domain_retry.py --tb=short
```

离线读取 v9 已保存的第二次返回：仍为合法 IR，按已批准局部下界遗漏政策接受，严格语义仍不等价。只在内存副本反转第（3）问 `cut_ratio` 的 segment/by 后，新校验器直接拒绝，定位 `r.c2.facts3` 与 `r.c2.facts5`；不借助金标检测这一矛盾。结果见 [replay.json](replay.json)。没有改写历史请求或返回。

## 产品重试边界

产品当前仍由 `product/runner.py` 创建 `AuditedClient` 并调用旧 `ProblemDomainExtractionService`，`max_attempts=3`。新简洁 IR 及本轮校验尚未进入这条生产路径。

1. DeepSeek 正式内容为空（包括推理耗尽 `finish_reason=length`）：Provider 在本次调用内原样重发一次，最多两次网络尝试。第一次推理不作为第二次输入；两次均计入审计与预算。这对应 v9 的第一轮情况。
2. 已有草稿、校验发现可修复问题：产品服务可带校验反馈请求定向 patch，草稿生成/修复合计最多三次；没有合法草稿的传输/格式失败则可能再请求完整草稿。
3. 来源待确认、无进展或预算耗尽等条件会停止，不能承诺任何失败必定再调一次。独立复核另受三次预算限制，总语义/网络上限仍为 6/12。

本轮证明新校验报告可驱动本地授权 patch 并重新通过校验；将它交给 LLM 自动修复，仍需第三步接入新 IR 协调流程。本轮不部署、不增加调用次数。
