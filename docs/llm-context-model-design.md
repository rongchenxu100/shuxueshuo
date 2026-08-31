# LLM Context 模型设计

## 1. 目标

Context 是跨阶段共享的语义状态，不是 prompt 文本、runtime 内存或某个 LLM 的私有草稿。

它解决三个问题：

1. 每个阶段只读取经过验证、与自己相关的事实；
2. retry、并行分支和下游生成能够追溯同一事实来源；
3. prompt、debug payload 和页面资产只是 Context 的 projection，不成为第二份权威。

## 2. 总体链路

```text
题目来源
→ ExtractionContext
→ PlannerStateContext
→ Runtime verified state
→ ExplanationContext
→ Diagram / Voiceover / Animation Context
→ LessonPageContext
```

各 Context 之间通过稳定的 identity、version、provenance 和 dependency 连接，而不是复制自然语言结论。

## 3. 核心模型

```text
Context
  context_id
  kind
  schema_version
  parent_context_ids[]
  manifest
  state
  events[]
  projections[]
  artifacts[]
```

### Manifest

描述输入来源和兼容边界：

- problem/source id；
- family 和 capability pack 指纹；
- prompt/model/config 指纹；
- 上游 Context ids；
- schema version。

### State

保存该阶段已验证的结构化事实。不同 Context 的 state 类型不同，但不能混入尚未验证的 candidate。

### Event

记录重要变化，例如：

- extraction evidence 被接受或拒绝；
- call verified/failed；
- StateVersion committed；
- answer commit 被撤销；
- asset invalidated。

Event 用于审计，不替代最终 state。

### Projection

从 Context 派生的有限视图，例如：

- LLM prompt payload；
- FunctionalPlan retry feedback；
- semantic read catalog；
- ExplanationSnapshot；
- debug summary。

Projection 不得反向写回身份事实。

### Artifact

保存可重建产物的引用、hash 和 dependency，例如 FunctionalPlan、LessonIR、VisualStepIR、音频和 HTML。

## 4. Context 类型

### 4.1 ExtractionContext

保存从图片、文本和布局中提取的题目语义：

- normalized text；
- evidence spans/regions；
- primitive objects；
- conditions、goals 和 scope tree；
- ambiguity 与置信信息；
- ProblemIR projection。

对象身份应在此阶段首次稳定建立。后续阶段不能仅凭名称重新创建对象。

### 4.2 PlannerStateContext

保存 Functional planner 的已验证状态：

- `MathObjectId / LogicalStateKey / StateVersionId`；
- canonical call 和 dependency graph；
- committed retry checkpoint；
- runtime provenance、binding 和 closure provenance；
- goal commit 与 provisional evidence；
- retry memory。

PlannerStateContext 不保存可直接复用的 RuntimeContext 数值。下一轮仍重放 committed call，并验证相同的 typed version chain。

### 4.3 ExplanationContext

只消费：

- canonical；
- runtime verified；
- goal reachable；
- provenance 完整的调用和状态。

它将执行事实组织成教学结构，但不能重新推导数学结论。

### 4.4 DiagramContext

保存对象、角色、几何关系、视图状态和视觉证据。它引用 ProblemIR/Explanation 中的对象身份，不根据 label 文本猜对象。

### 4.5 VoiceoverContext

保存 narration units、时间、语音资产和对应教学步骤。语音文本可以改写表达，不能改变数学事实。

### 4.6 AnimationContext

保存 beat timeline、可见性变化、交互和媒体依赖。它依赖 Explanation 与 Diagram 的稳定 ids。

### 4.7 LessonPageContext

聚合最终可发布资产及其 hash，不复制各阶段完整 state。

## 5. 身份与版本规则

- Context 内对象使用 typed id，而非显示名称作为主键；
- materialized state 必须有精确 StateVersion；
- 每个版本记录 producer、scope、predecessor、sources 和 provenance；
- runtime path 只描述物理落点；
- answer 是现有版本的 projection，不创建第二个 logical writer；
- 同名对象、相同实际值或相同 handle 不代表同一身份；
- retry checkpoint 是待重放期望，不是已物化 runtime value。

## 6. Scope 与依赖

Context 使用显式 scope tree：

- parent state 对后代可见；
- child state 对 parent 和 sibling 不可见；
- 公共计算应发布到所有 consumer 的共同祖先；
- private input 阻止不安全提升；
- exact read 永远引用指定版本；
- latest read在 consumer scope 中选择唯一 maximal visible version；
- 仅由 hidden/version edge 连接的依赖同样进入图和 repair cone。

## 7. Candidate、Verified 与 Committed

必须区分：

- `candidate`：LLM 或 parser 提出的结构；
- `runtime_verified`：事务执行成功并通过 typed 校验；
- `goal_committed`：属于已通过 required goal 的完整依赖闭包；
- `provisional`：有真实运行证据，但尚未获得 retry hard-lock；
- `failed/blocked`：不能进入 Context state history。

只有 committed 版本进入 B4 checkpoint。失败事务不得留下 declaration、runtime promotion 或 StateVersion。

## 8. 不可变性与失效

Context snapshot 一经发布即不可原地修改。新结果创建新 Context，并引用 parent。

下游 artifact 的有效性由 dependency hash 决定：

```text
artifact_valid = all(recorded_dependency_hash == current_dependency_hash)
```

当 ProblemIR、verified state 或 Explanation 改变时，只重建受影响的下游资产。

## 9. Prompt projection

LLM 只看到完成任务所需的最小视图。

Functional planner prompt 可包含：

- ProblemIR 的稳定语义引用；
- 当前 scope 与 required goals；
- 可用 capability catalog；
- locked calls 的紧凑结果；
- repair call ids 和 typed issues。

不得暴露：

- StateVersionId；
- runtime path；
-内部 compiler/builder id；
- expected answer；
-无关历史 Context 全量内容。

System prompt 保存协议和不变量；user prompt 保存本题数据及本轮短反馈，避免重复规则。

## 10. Retry

Retry 使用 checkpoint 和真实运行证据：

- committed call 被删除或改写时恢复 canonical payload；
- provisional call 可修改或删除；
- repair cone 沿版本 source/predecessor 和 reverse consumers 计算；
- answer check 失败撤销 goal commit，但可保留 runtime result 作为 provisional evidence；
- wire 失败且没有新执行证据时保留上一轮 checkpoint；
- identity、version、binding 或 closure drift 必须 fail loud。

## 11. Runtime 边界

PlannerStateContext 与 RuntimeContext 分工不同：

- PlannerStateContext 保存语义身份、版本期望和 provenance；
- RuntimeContext 保存一次执行中的实际值和物理 path；
- 每个 call 在 fork 后的 RuntimeContext branch 中执行；
- 全部校验通过后再原子提交；
- Context 不直接复用上一轮 RuntimeContext。

## 12. 序列化

当前新 Context 使用 `planner-state-context/v2`。

序列化要求：

- 稳定字段顺序与 schema version；
- typed ids 可 round-trip；
- derived index 不重复持久化；
- prompt-only/debug-only 字段不得成为恢复权威；
- schema breaking change 必须更新 loader、fixture 和文档。

## 13. 可靠性要求

- 缺 typed identity 不得降级为字符串 lookup；
- provenance 缺失或不一致不得进入 committed state；
- Context hydrate 必须重复检查核心不变量；
- shadow report 不改变正式状态；
- configuration drift 不交给 LLM 修复；
- Context round-trip 后 query、checkpoint 和 explanation 语义不变。

## 14. 反模式

- 把 prompt 文本当长期记忆；
- 用 runtime path 反推数学对象；
- 将 candidate 直接写入 Context；
- 为 answer alias 创建第二个 state writer；
- 每个下游阶段复制整份上游 JSON；
- 通过实际值相等合并对象或 call；
- retry 时静默丢弃不兼容 checkpoint。

## 15. 当前后续

ExtractionContext、VerifiedProblem 与 Scope Retry 已接通。下一阶段先固化原子路径 Macro，
再让 Explanation、Diagram、Voiceover 和 Animation 统一消费 verified execution 与 Context
dependency。详见：

- `docs/problem-extraction-context-design.md`
- `docs/functional-planner-next-stage-roadmap.md`
- `docs/path-minimum-macro-redesign.md`
