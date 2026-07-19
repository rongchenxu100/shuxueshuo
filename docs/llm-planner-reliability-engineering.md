# LLM Planner 可靠性工程与迭代方法

## 1. 目标

Solver Planner 的唯一目标是提高端到端成功率：减少 LLM 幻觉，降低 LLM 需要承担的机械责任，并让代码尽可能确定性地维护类型、对象身份、状态依赖、作用域和执行正确性。

当前实践可以归纳为四类优化：

1. 优化 capability 的表达，减少 LLM 对能力含义和输入输出的误解。
2. 优化 capability 的实现，用确定性数学原语处理可机械推导的问题。
3. 使用 normalizer / reconciler 修复表示层偏差。
4. 将对话历史和 retry 记忆建模为 `PlannerStateContext`。

这四类优化主要提高“已覆盖能力范围内”的可靠性。系统能解决多少不同类型的题目，还取决于第五个维度：**能力覆盖**。

## 2. 成功率模型

可以把端到端成功率粗略拆成：

```text
P(success)
  = P(problem is representable)
  * P(required capabilities are covered)
  * P(LLM produces a valid plan | covered)
  * P(deterministic runtime executes correctly)
  * P(candidate selection chooses a correct result)
```

其中：

- ProblemIR 与题目解析质量决定题目能否被正确表示。
- Capability Pack、FunctionSpec 和 MacroSpec 决定能力覆盖上限。
- FunctionalPlan catalog、few-shot 和 prompt 影响 LLM 规划质量。
- elaborator、reconciler、normalizer、compiler 和 runtime 决定确定性执行质量。
- retry 或多候选选择决定概率输出能否收敛到可信结果。

不能用 prompt 优化弥补能力缺失，也不能用 normalizer 修复数学意图错误。每层必须承担边界清晰的职责。

## 3. 四类优化的价值与边界

### 3.1 Capability 表达优化

这是收益最广、最直接降低错误发生率的一类优化。

从 StepIntent 到 FunctionalPlan 的演进，本质上是压缩 LLM 的输出自由度。LLM 只需要：

- 选择 capability；
- 提供语义证据；
- 连接前序 call result；
- 绑定最终答案或已有对象；
- 说明策略和原因。

以下职责由代码承担：

- canonical handle 和 StateSlot 分配；
- runtime type 和 output type；
- scope、valid scope 和跨小问共享；
- creates / produces；
- object identity、write mode 和 provenance；
- Function/Macro runtime binding；
- 开放表达式与闭合数值的实际判定。

好的 capability 表达应包含：

- `use_when`：适用目标和前置状态；
- `do_not_use_when`：稳定出现的泛化误用；
- 必要的 arg / return 描述；
- 明确的 semantic role、cardinality、identity 和 result form；
- 不包含题名、固定点名、答案值或固定下一方法。

验收标准不是“模型看懂了这道题”，而是同类新题无需新增 prompt 特判即可正确选择能力。

### 3.2 Capability 实现优化

这类优化必须区分两种形态。

#### Per-method 补丁

例如在 compiler 或 reconciler 中按 method id 添加分支，或在某个 method 内根据特定变量名猜测输入。这类修复通常泛化性弱，会形成随题量增长的维护负担。

仅在语义确实属于该 capability 独有契约时才允许 method-local 实现，而且应通过 MethodSpec / CapabilityContract 声明触发，不应依靠散落的字符串 dispatch。

#### 共享确定性原语

例如：

- symbolic target closure；
- scalar result closure；
- constraint analysis；
- object/state identity resolution；
- parameter substitution；
- scope LCA 与 call placement；
- context closure；
- runtime type compatibility。

这些原语可以被多个 method、recipe 和 family 复用，是可积累的系统资产。

判断一项实现层修复是否健康的标准是：

> 新增同类 capability 时，是否只需声明 spec、contract 或 resolver id，而不需要修改共享 dispatch 代码。

满足该标准的修复具有可扩展性；不满足时应记录为迁移债务，而不是继续复制特判。

### 3.3 Normalizer / Reconciler

Normalizer 和 reconciler 适合修复表示层、数据流层和身份层的确定性偏差，例如：

- stale alias 和 canonical promotion；
- scope 提升与共享调用合并；
- 同一对象的状态 transition；
- legacy outputs 的分拣；
- 可唯一推导的 output type；
- 多余、无消费且无副作用的 pure call；
- 不受支持但无数学影响的 optional hint；
- 中间开放表达式被过早绑定为数值答案。

它们不应：

- 替 LLM 选择新的数学路线；
- 自动插入无限增长的 method 链；
- 根据 expected answer 改写计划；
- 把语义不明确的错误猜成一个可执行方案；
- 让“能运行”伪装成“数学正确”。

每个 deterministic repair 必须满足：

1. 有结构化前提，而不是匹配自然语言错误文本。
2. 结果唯一；存在多个合理修复时交回 LLM。
3. 幂等；重复运行不会继续改变候选。
4. 记录 repair event 和 provenance。
5. 不扩大 capability 的数学语义。

Normalizer 的天花板是意图错误。LLM 选错 capability、遗漏关键数学转换或采用错误证明路线时，应通过 typed repair ticket 反馈，而不是由代码猜路线。

### 3.4 PlannerStateContext 与 Retry

Context 建模不一定降低第一轮错误率，但会显著提高多轮收敛率和调试效率。

`PlannerStateContext` 应保存：

- ProblemIR 的语义投影；
- MathObject、Condition 和 StateSlot；
- Functional call graph 与 canonical projection；
- alias、scope、identity 和 provenance；
- stable call graph；
- issues、deterministic repairs 和 retry memory；
- raw、normalized、projected 和 effective candidate snapshots。

Retry 不是把历史错误文本重新塞给 LLM，而是从 Context 投影一份修复工单：

- 哪个 call 或状态最早失效；
- 期望的 semantic role、type、identity 和 result form；
- 当前实际绑定结果；
- 哪些独立调用已经验证并应保留；
- 哪些下游调用只是被根因阻塞；
- 代码已经执行了哪些确定性修复。

Context 的核心价值是防止 retry 漂移：每轮只修失败子图，已经验证的 canonical calls 不重新交给模型发明。

## 4. 第五维度：能力覆盖

前四类优化只能提高覆盖内可靠性。对于缺少必要数学机制的题目，prompt 再清晰也无法产生可执行且可信的结果。

能力覆盖不等于为每道题手写一个 method。推荐使用三层结构：

1. **稳定高层 capability**：对 LLM 暴露学生可理解、边界明确的数学动作。
2. **共享数学原语**：在 Function/Method 层提供求解、闭包、筛选、代入和几何计算能力。
3. **受控组合机制**：由 MacroSpec、contract 和 compiler 组合共享原语，不把内部机械步骤交给 LLM。

能力扩张应成为主动工作流：

```text
收集失败样本
  -> 按结构化 issue 聚类
  -> 判断 ProblemIR / capability / binding / runtime / prompt 缺口
  -> 优先补共享原语或 pack contract
  -> 必要时新增高层 capability
  -> 固化 fixture、recorded plan 和 held-out regression
```

新增能力应遵循 `docs/capability-authoring-guide.md`。目标是持续降低新增题型的边际成本，而不是让 capability 数量无限复制题目表面形态。

## 5. 用真实 LLM 概率输出驱动迭代

不断运行 DeepSeek、收集不同概率输出并迭代上述机制，这条路在有界题型域内是可行的。但必须把它从“逐题打补丁”升级为可量化实验。

### 5.1 分层记录错误

每个候选至少记录以下层级：

- `problem_extraction`
- `functional_validation`
- `functional_elaboration`
- `functional_reconciliation`
- `normalization`
- `function_binding`
- `macro_binding`
- `trial_execution`
- `goal_verification`
- `candidate_selection`

修复归因建议：

| 主要错误层 | 优先处理方向 |
| --- | --- |
| ProblemIR 缺事实、对象或关系 | 提取 schema、结构化事实建模、提取验证 |
| validation / elaboration | wire schema、catalog projection、auto/aggregate resolver |
| reconciliation / binding | contract、identity、scope、context closure |
| normalization | 仅增加唯一且幂等的表示层修复 |
| trial execution | method 算法、runtime type、constraint/closure primitive |
| goal verification | capability 选择、few-shot、答案 provenance、能力覆盖 |
| candidate selection | ranking、consensus、verification coverage |

不能只看最终测试是否通过。每个修复应证明它降低了某一类 issue，而没有把错误推迟到后续层。

### 5.2 使用 pass@k 和分层指标

单次真实网络测试受采样随机性影响。至少应统计：

- `pass@1`、`pass@3`；
- 每题每层 issue 频率；
- deterministic repair 触发率和成功率；
- stable graph 保留率；
- 平均 retry 次数；
- prompt token、响应 token、延迟和成本；
- capability 误选率；
- 可执行但 goal verification 不充分的候选比例。

测试集应分为：

- development fixtures：允许用于诊断和设计迭代；
- regression fixtures：防止旧能力退化；
- held-out problems：不参与具体修复决策，用于检测过拟合。

真实 LLM 输出应保留 raw response、Context、reconciliation report、effective plan 和结构化 issue，便于重放，而不是只保存最终 pass/fail。

## 6. Best-of-N：概率生成，确定性过滤

多候选采样是下一阶段高收益方向，但需要准确理解其边界。

如果单个候选正确概率为 `p`，并行采样 `k` 个候选时：

```text
P(at least one correct candidate) = 1 - (1 - p)^k
```

这只是“正确候选出现在集合中”的概率，不等于系统最终选择正确答案的概率。生产环境通常没有 expected answer，TrialExecutor 和 GoalVerifier 也不是完整数学正确性 oracle。

它们能够确定性淘汰：

- schema、scope、type 和 binding 错误；
- unresolved symbol；
- identity / provenance 错误；
- capability contract 不满足；
- runtime exception；
- answer 未覆盖；
- 明确违反题面条件的结果。

但多个候选仍可能全部可执行，并给出不同答案。因此最终成功率还取决于候选选择：

```text
P(final success)
  = P(at least one correct candidate)
  * P(selector chooses a correct candidate | candidates)
```

### 6.1 推荐候选管线

```text
同一个 parent PlannerStateContext
  -> 并行生成 k 个 FunctionalPlan branches
  -> validation / elaboration / reconciliation
  -> canonical projection / trial execution
  -> hard validation filter
  -> canonical answer signature 分组
  -> deterministic ranking / consensus
  -> 只提交 winner Context
```

非 winner Context 作为实验 artifact 保存，不能污染正式 retry memory 或 stable graph。

### 6.2 Hard Filter

以下问题直接淘汰候选：

- 任一 required answer 未绑定；
- unresolved symbol；
- Function/Macro typed error；
- identity、scope 或 provenance mismatch；
- runtime failure；
- 违反 QuestionGoal 或题面结构化约束；
- candidate projection/finalizer 非幂等。

### 6.3 排名与共识

剩余候选可按以下证据排序：

- required goals 覆盖完整度；
- checks 和结构化条件满足度；
- provenance 完整度；
- 未验证假设数量；
- canonical graph 简洁度和 dead call 数量；
- capability applicability 匹配度；
- 多候选 canonical answer signature 共识。

不得简单使用“步骤更长”“LLM 自报置信度”或文本更流畅作为正确性依据。

如果多个高质量候选给出冲突答案，系统应进入 targeted retry、增加独立候选或标记不确定，不能任意选择一个。

### 6.4 初始上线策略

建议从条件式 `best-of-3` 开始：

1. 第一候选通过且验证证据充分时直接使用。
2. 第一候选失败或置信证据不足时，再并行补两个候选。
3. 三个候选统一进入相同 Context/replay/runtime 管线。
4. 只有 selector 产生唯一可信 winner 时提交。

这比固定每题采样很多次更容易控制成本和延迟。

## 7. Few-shot、Prompt 与模型的作用

### Few-shot

Few-shot 适合展示：

- call 粒度；
- 数据依赖；
- capability 正确使用边界；
- 中间结果如何继续被消费；
- answer binding 和开放/闭合结果形态。

Few-shot 不应复制完整原题答案，也不应代替 capability contract。检索应优先使用 family、mechanism pack、fact type、goal type 和 capability overlap，并保留 held-out 测试纪律。

### Prompt

Prompt 只应解释稳定协议和决策原则。某题暴露的问题若能通过 schema、catalog、contract 或 deterministic code 解决，不应继续向 prompt 添加题型专用链路。

### 模型升级与微调

更强的基础模型会直接提高 pass@1，但不能替代结构化边界。长期积累的 `(ProblemIR, verified FunctionalPlan, runtime provenance)` 是高质量训练数据，可用于专用模型微调或 reranker 训练。

微调前应先保证数据是 runtime verified、无 normalizer 过度修复、且 provenance 完整，否则会把历史补丁和错误路线固化进模型。

## 8. ProblemIR 是上游上限

题面对象、条件、作用域或目标提取错误时，下游计划无法可靠恢复。因此 ProblemIR 提取应单独度量：

- entity / fact / answer recall；
- fact role 和 subject identity；
- scope / valid scope；
- Symbol 和自由参数；
- 图片几何关系的结构化准确率；
- 低置信证据和人工 ground truth 差异。

Planner 不应通过 description 文本重新猜测 ProblemIR 未结构化的事实。缺失应作为 extraction gap 返回上游修复。

## 9. 修复决策准则

遇到一个新的真实 LLM 失败时，按以下顺序判断：

1. **ProblemIR 是否表达了必要事实？** 没有则修提取或事实 schema。
2. **Catalog 是否准确表达 capability？** 模型稳定误用则修 `use_when/do_not_use_when`、arg/return role。
3. **所需能力是否存在？** 不存在则补共享原语、Macro 或 capability pack。
4. **代码能否唯一机械修复？** 能则进入 elaborator/reconciler/normalizer，并保证幂等和 event。
5. **是否属于 capability 实现缺口？** 优先抽共享 primitive，通过声明式 spec 接线。
6. **是否是数学路线选择错误？** 生成 typed repair ticket，必要时改善 few-shot，不由 normalizer 猜路线。
7. **是否只有概率波动？** 用 pass@k 和 held-out 样本判断，不根据单次通过或失败下结论。

任何修复都应回答：

- 它阻止错误发生，还是只在事后修复？
- 它服务一种数学语义，还是一个具体题面输出？
- 新增同类 capability 是否还要改共享代码？
- 代码没有 expected answer 时是否仍成立？
- 是否可能把错误计划修成“可运行但不正确”？

## 10. 推荐迭代路线

### 阶段 A：建立可靠性基线

- 为五题 FunctionalPlan opt-in 建立多次采样报告。
- 统计 pass@1、pass@3 和分层 issue。
- 建立 held-out 题集，不参与当前修复决策。
- 区分 representation error、capability gap、strategy error 和 runtime defect。

### 阶段 B：条件式 Best-of-3

- 从同一 Context 创建候选分支。
- 复用现有 validation/reconciliation/runtime hard filter。
- 建立 canonical answer signature 和候选 ranking report。
- 冲突时 retry，不依赖 expected answer选择。

### 阶段 C：能力覆盖工作流

- 对 gap 按 fact pattern、goal type 和缺失 state role 聚类。
- 先扩共享 primitive 和 pack contract。
- 为重复出现且边界稳定的机制新增 Macro/capability。
- 每项能力补 authoring preflight、fixture 和 held-out regression。

### 阶段 D：数据与模型

- 沉淀 verified FunctionalPlan 数据集。
- 训练 capability selector 或候选 reranker。
- 数据规模和质量足够后再评估 planner 微调。

## 11. 结论

通过真实 DeepSeek 概率输出持续迭代 capability 表达、确定性原语、normalizer/reconciler 和 Context retry，这条路线是可行的，而且当前架构已经具备形成正反馈的基础。

但需要守住三个原则：

1. 用共享声明和确定性原语替代 per-method 补丁。
2. 用分层指标、pass@k 和 held-out 题判断改动，避免对单题、单次采样过拟合。
3. 明确验证边界：runtime 可执行不等于数学答案必然正确；多候选必须经过可信选择，能力覆盖必须独立扩张。

最终目标不是让 LLM 从不犯错，而是让它只在适合概率模型的狭窄决策空间中犯错，并让代码能够尽早发现、准确定位、确定性修复或安全拒绝这些错误。

## Related Documents

- `docs/llm-context-model-design.md`
- `docs/capability-authoring-guide.md`
- `docs/functional-method-recipe-orchestration-design.md`
- `docs/family-capability-pack-upgrade-plan.md`
- `docs/symbolic-target-closure-evolution-plan.md`
- `docs/llm-fallback-and-gap-system.md`
- `docs/llm-role-boundaries-and-expansion-strategy.md`
