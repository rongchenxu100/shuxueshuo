# Functional Planner 后续演进路线

## Summary

本文档整理 Functional Planner 下一阶段的整体路线。目标仍然只有一个：

> 减少 LLM 承担的机械职责和表示自由度，将类型、身份、作用域、依赖、符号闭包、执行与验证交给确定性代码，从而提高端到端成功率。

后续工作分为四条有明确依赖关系的主线：

1. **产品协议 parity**：为五道代表题建立 FunctionalPlan 资产、真实网络稳定性基线和迁移 oracle。
2. **语义状态权威收敛**：让 `MathObject -> StateSlot -> StateVersion` 身份贯穿 allocation、call placement、finalizer、Context 和 retry。
3. **执行架构收敛**：先把整图静态状态预测改为 transactional call execution，
   再把参数求解收敛成 runtime-grounded 声明式符号闭包，最后删除 StepIntent 兼容桥。
4. **工作流 Context 扩展**：建立图片题目提取 Context，以及解题后 Explanation、Diagram、Animation Context。

四条主线不能同时无门禁地修改主链路。每一阶段都必须先形成可重放 oracle、分层指标和退出条件，再进入下一阶段。

FunctionalPlan parity 完成不等于可以立即切换默认协议。默认切换由独立的
**Functional Default Ready** 门禁控制，并在 Track D 中实施。

## Current Baseline

当前已经具备：

- `PlannerStateContext` 作为 semantic reads、retry memory 和 graph state 的主要来源；
- Capability Pack、CapabilityContract、FunctionSpec 和 MacroSpec；
- FunctionalPlan strict opt-in、deterministic elaboration、reconciliation、call placement 和 graph retry；
- FunctionalPlan 到 canonical `StepIntentDraft` 的兼容投影；
- 现有 `RecipeTrialExecutor -> StepPlan -> MethodInvocation -> InvocationExecutor` 执行链；
- symbolic target closure、scalar result closure、constraint analysis 等共享原语的初始实现；
- 五题 FunctionalPlan fixture、few-shot、真实 DeepSeek opt-in 和统一并发 batch runner。

语义身份收敛不再只是跨阶段备注，它是下文 **Track B** 的正式实施主线。详细方案见：

- `docs/math-object-state-identity-propagation-plan.md`

2026-07-26 的 Stage 2 acceptance batch
`stage2-acceptance-20260726-232252` 使用同一 solver source fingerprint、
`deepseek-v4-flash` 和各题兼容指纹，每题十个样本，最多三轮：

| Case | pass@1 | pass@3 | Configuration errors |
| --- | ---: | ---: | ---: |
| Nankai | 9/10 | 10/10 | 0 |
| Heping Ermo | 4/10 | 10/10 | 0 |
| Xiqing | 8/10 | 10/10 | 0 |
| Hexi | 7/10 | 10/10 | 0 |
| Heping | 6/10 | 9/10 | 0 |

本批共 `49/50` 在最多三轮内通过。五题分别满足 `samples >= 10`、
`pass@3 >= 90%`、configuration error 为 0、unclassified error 为 0、
successful-sample gate failure 为 0，并且各题只有一个 compatibility key。
因此 Track A Stage 2 和 `parity complete` 门禁已经完成。

该 acceptance cohort 的 solver source SHA-256 为
`882d8516b1e602a46a623f53c2fe84529a6a5ce403df74ed6963bb5bb94a7cb7`，
evaluation source SHA-256 为
`15ed49c5c094f956ae89396388a82ca0700fefe36323a886814260bb6917c2fa`。
后续 Track B/C 改动使用该 cohort 作为迁移基线；代码指纹改变后的日常回归不重新定义
Track A 是否完成，但主链切换前必须重新建立相应阶段自己的真实样本门禁。

## Roadmap Status Model

路线图使用以下状态，避免把“已有基础代码”“单批测试通过”和“产品可切换”混为一谈：

- `COMPLETE`：该里程碑的全部门禁和证据已经满足；
- `IN PROGRESS`：已有实现或证据，但仍有明确未完成项；
- `PENDING`：尚未进入主线实施；
- `BLOCKED`：必须等待其他里程碑完成。

| Milestone | Status | 已完成 | 未完成或阻塞项 |
| --- | --- | --- | --- |
| Track A assets | `COMPLETE` | 五题 fixture、离线 replay、真实 opt-in、strict-test few-shot、共享 batch 基座 | 无 |
| Track A Stage 1 | `COMPLETE` | 每题 3 个样本，`15/15` 在三轮内通过，configuration error 为 0 | 无 |
| Track A parity complete | `COMPLETE` | 五题各 10 个兼容样本，`pass@3 >= 90%`；structured provenance parity、typed failure boundary、跨 batch 聚合均已建立 | 无 |
| Track B typed identity authority | `IN PROGRESS` | B0 typed identity foundation、B1 allocation authority 与 B2 typed placement authority 已完成 | B3 finalizer、B4 retry authority 与 B5 string cleanup |
| Track C transactional interpreter | `PENDING` | 现有 partial replay、Working RuntimeContext、typed provenance 可复用 | Track B B1-B3；C0 shadow；逐 call execution parity |
| Functional Default Ready | `BLOCKED` | Functional 主链可 opt-in 执行 | Track A parity complete；Track B B0-B4；Track C production closure；direct compiler shadow；held-out；production observability 与回滚门禁 |
| Track D0 product routing gate retirement | `BLOCKED` | 唯一 problem-id gate 已登记 | Track A parity complete；Functional production routing 接管该 family；legacy deterministic planner 退场 |
| Track D default switch | `BLOCKED` | direct compiler 目标已定义 | Functional Default Ready 后才能切默认协议和删除 StepIntent 兼容链 |

上述状态有意将两个判断分开：

1. **Track A 是否完成**：回答五题 FunctionalPlan 是否形成稳定、可量化的迁移 oracle。
2. **是否可以切默认协议**：回答 typed identity、held-out、生产观测和回滚能力是否足以支撑产品切换。

### Immediate Next Gate

Track A 已完成，当前主线切换到 Track B，而不是继续围绕五题概率样本做局部补丁：

1. **B3 identity-aware finalizer**：建立 logical-state/runtime-destination 双 ledger，
   把 compiler 内部写入也映射到 typed destination；
2. **B4 Context/retry version authority**：让 retry graph 持久化并恢复精确
   `StateVersionId`，不再按 call/handle 猜状态；
3. 继续用五题 authored fixture、recorded provenance parity 和 Track A acceptance
   cohort 作为迁移 oracle；
4. B3 稳定后启动 C0 logical graph / Working Context shadow，但不切换
   production execution authority。

Track E 的 held-out 基础设施和 ProblemExtractionContext schema 可以并行建设；默认协议
切换、StepIntent 删除和 transactional interpreter 主链切换仍保持阻塞。

截至 2026-07-27，B2 已完成 authoritative cutover。下一项实际编码工作是
**B3 identity-aware finalizer**：placement 已不再通过 legacy resolved-call
signature、slot string、return binding 或 runtime path 决定调用等价性，但 finalizer
仍需把 compiler 内部写入统一映射到 typed logical-state/runtime-destination 双 ledger。

## Pack Contract Synchronization Discipline

Capability Pack 中的 `CapabilityContractSpec` 是 Function/Macro facade、Functional
Catalog、reconciliation preflight 和 Context state effect 的共同声明源。路线图每次
增加新的 planner 语义时，必须同步检查以下契约字段，而不能只修改其中一个 projection：

- 可用性：`execution_status / exposes_to_llm / complete / constraint_analyzer`；
- 读写类型：`slot_reads / condition_reads / slot_writes / condition_writes`；
- 状态语义：`state_kind / runtime_type / object_kind / semantic_role / output_key`；
- 可见性与数量：`scope_policy / cardinality / required`；
- 状态演进：`write_mode / result_form / input_closure_policy`；
- 身份与证据：`provides_semantic_roles / object_role_projections /
  lineage_closures / identity_constraints`；
- 依赖闭合：`dependency_policy / context_resolvers /
  input_closure_requirements`。

同步顺序固定为：

1. 在 pack/family contract 或 recipe execution alias 中声明语义；
2. 由 `FunctionSpec` / `MacroSpec` 投影并执行 consistency preflight；
3. Functional Capability Catalog 只暴露 LLM 需要理解的投影；
4. reconciliation、compiler 和 runtime provenance 消费同一字段；
5. `PlannerStateContext` 与 debug payload 保存结果，不重新解释字段；
6. 增加 source-to-projection、catalog、runtime drift 和 JSON round-trip 测试。

新增字段如果只在某一层出现，应视为迁移未完成。特别是 identity、write mode、result
form 和 closure policy，不允许在 method id 分支或 prompt 文案中维护平行真相源。

## Target Architecture

中期目标链路：

```text
ProblemIR
  -> PlannerStateContext
  -> MathObject / StateSlot / StateVersion identity ledger
  -> Functional prompt projection
  -> LLM FunctionalPlan candidate
  -> deterministic elaboration
  -> LogicalFunctionalGraph
  -> TransactionalFunctionalInterpreter
       -> resolve ready call from Working Context
       -> Function/Macro compiler
       -> ExecutionPlan / MethodInvocation
       -> InvocationExecutor
       -> validate and commit actual StateVersion
  -> CanonicalFunctionalGraph + PlannerStateContext vNext
  -> runtime provenance and verified answers
```

长期工作流：

```text
Problem image / source
  -> ProblemExtractionContext
  -> ProblemIR
  -> PlannerStateContext
  -> LessonExplanationContext
  -> DiagramContext
  -> AnimationContext
```

其中：

- FunctionalPlan 是 LLM 对 PlannerStateContext 的 candidate update，不是 runtime truth。
- CanonicalFunctionalGraph 是 reconciliation 后的权威调用图，其参数、返回值和依赖必须引用 typed MathObject/StateVersion 身份。
- RuntimeContext 保存当前执行值，不替代 PlannerStateContext 的语义状态和历史。
- Prompt、FunctionalPlan、ExecutionPlan、LessonIR 和 VisualStepIR 都是 Context 的 projection 或 candidate artifact。

## Track A: Five-Problem FunctionalPlan Parity

### Goal

为现有五道 StepIntent opt-in 题建立独立 FunctionalPlan fixture 和真实 DeepSeek opt-in，形成足够宽的迁移 oracle。

Track A 本身不切换默认协议，也不删除 StepIntent。它只负责建立 FunctionalPlan
parity 资产、稳定性证据和迁移 oracle。

五题为：

1. Nankai；
2. Heping Ermo；
3. Xiqing；
4. Hexi；
5. Heping。

### Recommended Order

1. **Heping Ermo**：覆盖 Symbol identity、Point transition 和复杂 Macro。
2. **Xiqing**：集中验证参数反求与 symbolic closure。
3. **Hexi**：验证加权路径和机制 Macro。
4. **Heping**：验证角度、直线和交点能力组合。

南开作为当前迁移基线持续运行。

### Current Status

截至 2026-07-27：

- `COMPLETE`：五份 authored FunctionalPlan fixture；
- `COMPLETE`：五题离线 validation、reconciliation、projection 和 runtime replay；
- `COMPLETE`：五个真实 DeepSeek Functional opt-in 薄入口和共享执行基座；
- `COMPLETE`：strict-test few-shot、隔离 debug 目录、per-sample result 和统一 batch report；
- `COMPLETE`：Stage 1，每题 `3/3` 在最多三轮内通过；
- `COMPLETE`：recorded StepIntent 与 authored FunctionalPlan 的 structured provenance
  parity oracle；
- `COMPLETE`：typed planner failure boundary 和 layer/code/root issue 统计；
- `COMPLETE`：按 source/model/prompt/catalog/fixture compatibility key 的跨 batch 聚合；
- `COMPLETE`：Stage 2 acceptance batch
  `stage2-acceptance-20260726-232252`，五题各十个兼容样本；Nankai、Heping Ermo、
  Xiqing、Hexi 为 `10/10`，Heping 为 `9/10`，configuration/unclassified error
  均为 0。

Track A 的真实样本资产继续作为回归 oracle 保留，但后续优化指标归属相应 Track：
Track B 关注 identity drift 和 writer authority，Track C 关注 transactional execution
与 runtime-grounded closure，Track E 关注 pass@1、best-of-N 和生产 winner selection。

### Required Assets Per Problem

每道题必须有：

- authored、可执行的完整 `functional_plan/v1` fixture；
- 离线 FunctionalPlan validation、reconciliation、projection 和 runtime test；
- 与现有 recorded StepIntent 相同的 answer/provenance oracle；
- 独立真实 DeepSeek Functional opt-in；
- strict-test few-shot 策略；
- 并发采样报告，包括 `pass@1`、`pass@3`、错误层、平均轮次、token 和延迟。

完整 FunctionalPlan fixture 必须是调用图真相源。不得通过不可靠的自动 StepIntent 反向转换生成，也不得把 expected answer 用于生成或修复计划。

### Repair Rules During Parity

迁移期间允许：

- 修正 capability `use_when / do_not_use_when`；
- 补充声明式 arg/return role、identity、write mode 和 result form；
- 增加跨 capability 可复用的 deterministic primitive；
- 增加唯一、幂等、可解释的 elaboration/reconciliation repair；
- 修复 runtime/configuration defect。

迁移期间不允许：

- 题名、固定点名或答案值特判；
- 在 prompt 中加入固定 method 链；
- 仅为某题增加 method-id dispatch；
- normalizer 根据 expected answer 改写计划；
- 把 LLM 的数学路线错误强行修成可运行计划。

### Track A Parity Complete Criteria

- 五题离线 fixture 100% 稳定通过；
- 同一 `revision + model + prompt/catalog/fixture hash` 下，每题至少十个真实样本；
- 五题各自 `pass@3 >= 90%`，并记录 `pass@1`、平均轮次、token 和延迟；
- `planner_configuration_error` 为零，且配置错误在发起 LLM 请求前暴露；
- 每轮 candidate 保持 `candidate_format="functional_plan"`，不回退 StepIntent 协议；
- 五题最终 answer 与 recorded oracle 一致；
- 建立 structured provenance parity oracle，比较关键对象身份、状态写入、answer producer
  和跨 scope 复用，而不只比较最终答案；
- batch report 将失败稳定归入 validation、elaboration、reconciliation、binding、
  runtime、goal verification 或 strategy error，不再只聚合为 `planner_failed`；
- compatibility key 不一致的样本不得混入同一 parity 统计。

Track B B0-B4、held-out 门禁、production observability 和默认协议切换不属于 Track A
完成条件；它们属于下文的 Functional Default Ready 门禁。

## Functional Default Readiness Gate

### Purpose

这是跨 Track 的产品切换门禁，用来回答“是否可以把 FunctionalPlan 设为默认协议”，
而不是再次衡量五题 parity。

### Current Status

`BLOCKED`。Track A parity 已完成，但 typed identity authority、transactional
execution、held-out 证据和生产切换能力尚未达到门禁。

### Criteria

- Track A 达到 `parity complete`；
- Track B B0-B4 完成，allocation、placement、finalizer、Context 和 retry 使用同一
  typed MathObject/StateVersion identity；
- Track C 对生产暴露的参数能力完成声明式 closure 和 provenance 接线；
- Track C transactional interpreter 已用真实 runtime result 更新 Working Context，
  stable graph 不再依赖整图 projected result state；
- 同一 MathObject 的重复 writer 在 runtime 前被合并或拒绝，不再以正常
  `duplicate_*` retry 暴露；
- Function/Macro/identity/provenance 主链没有 compatibility fallback；
- 至少一组不参与日常修复决策的 held-out 题无显著退化；
- 生产监控可以按 layer/code、模型、prompt/catalog hash 和 answer signature 观测失败；
- 默认切换具备 canary、回滚和 StepIntent 迁移观察窗口；
- Track D direct compiler shadow 达到其切换门槛。

满足该门禁后，才在 Track D 中切换默认协议。StepIntent 删除仍需经过独立观察窗口，
不会与默认切换在同一个提交中完成。

## Track B: MathObject Identity and State Version Authority

### Goal

将 `PlannerStateContext` 中已经存在的 MathObject 身份真正提升为 allocation、placement、finalizer、retry 和 explanation 的共享权威源，逐步删除 handle 字符串、scope 前缀和 runtime path 对象身份猜测。

### Current Status

`IN PROGRESS`。B0、B1 与 B2 已完成离线 authoritative cutover：Functional return
allocation 与 call placement 统一消费 typed identity/version，Context/debug 保存
allocation 与 placement audit。B2 hardening 后全量 solver 回归为
`1299 passed, 17 skipped`；
五题真实 smoke `batch-20260727-162705` 为 `14/15`，configuration error、
unclassified error、成功样本 gate failure、placement drift 与 identity drift 均为 0。
唯一失败属于概率性的证据闭包/结果形态未收敛，不是 placement 配置故障。该批次不重新定义
Track A。B3-B5 尚未完成，因此 compiler/finalizer 和 retry 仍保留兼容 ledger，
不得据此切换默认协议。

B1 完成后的加固还包括：

- 同一纯 capability 重新计算同一 MathObject 时，只有当前输入 StateVersion
  与前一计算相同或为其后代，才能判定为 dependency refinement；
- open/closed 等结果形态本身不再足以证明 transition，缺少版本依赖时产生
  `functional.state_transition_dependency_unproven`；
- transition issue 会携带前后 producer，retry 可以同时放开造成错误状态链的上游；
- placement 已使用聚合 `ComputationKey + StateEffectKey` 作为唯一调用身份，
  answer/object destination 不再进入数学计算键；
- scope placement 后从干净 Context index 重放 typed allocation，并统一重写
  selected/previous/source version 与 downstream resolved value；
- 最新离线回归为 `1299 passed, 17 skipped`，`git diff --check` 通过。

详细设计、数据模型和迁移清单见：

- `docs/math-object-state-identity-propagation-plan.md`

### Why This Is a Mainline Stage

当前 Context 虽然已记录 MathObject 和 StateSlot，但 Functional return allocation、call placement 和 finalizer 仍可以各自根据 handle、scope 和 return binding 重新推断身份。因此会出现“Context 认为是同一个 D，placement 却保留多个 producer，runtime 最后才报 duplicate writer”的分层漂移。

该 Track 不是一次独立重构，而是 Functional 主路必须经过的语义权威迁移。它同时是：

- 五题 parity 正确处理跨 scope 重复生产和 stable graph overlay 的必要条件；
- 声明式 Symbolic Closure 稳定绑定 Symbol/ParameterValue 身份的基础；
- direct Functional graph compiler 删除 StepIntent 桥之前的前置条件；
- Explanation 保留对象状态演进和跨小问引用的语义基础。

### Iteration Sequence

#### B0. Typed Identity Foundation

- 状态：`COMPLETE`（2026-07-27）。
- 引入 `MathObjectId / LogicalStateKey / StateSlotId / StateVersionId / RuntimeDestinationKey / ComputationKey`；
- 在现有模型中增加 typed identity sidecar，与旧 string id 做 shadow comparison；
- 五份 authored FunctionalPlan fixture 的 object/slot/scope shadow mismatch 为零；
- typed identity JSON round-trip 与旧 Context 缺省 sidecar 重建已覆盖。

#### B1. Allocation Authority

- 状态：`COMPLETE`（authoritative，2026-07-27）。
- 实现 `StateIdentityIndex + StateAllocationService`；
- Context 状态和 in-flight Functional return 共用同一 allocation 索引；
- 区分 reuse、transition、isolated state 和 identity conflict；
- 南开 D 在 `i / ii_1 / ii_2` 中只有一个 canonical writer；
- 相同 capability 但输入 StateVersion 不同不复用，answer binding 不进入计算键；
- legacy state refiner 只补充 previous-step metadata，改变 typed allocation 分类时
  产生 `planner.state_projection_drift`；
- compiler 按 `previous_version_id` 解析跨 scope transition predecessor，legacy
  finalizer 同时校验 typed version chain 与原 StateSlot ledger；
- 五题 authored fixture 的 typed shadow mismatch 为 0，全量 solver 回归为
  `1292 passed, 17 skipped`；
- 真实行为证据：focused 和平 `3/3`；五题 smoke `12/15`，系统配置/未分类错误为 0。

#### B2. Placement Uses Identity Decisions

- 状态：`COMPLETE`（authoritative，2026-07-27）。
- placement 使用 `ComputationKey + StateEffectKey`，不再将 answer/object return binding 差异当成两次数学计算；
- answer alias 可以在等价 producer 合并时转移；
- LCA 只决定 execution/valid scope，不重新创建对象状态身份；
- downstream refs、projection map 和 provenance 统一指向 canonical call/version。

实施顺序：

1. 定义 placement 输入快照，只接受 B1 已分配的 call、return、typed slot/version、
   `ComputationKey` 和 `StateEffectKey`；placement 不再自行 materialize return。
2. 用 typed computation/effect key 建立 canonical call group，统一转移 answer alias、
   `CallResultRef`、return allocation、dependency edge 和 provenance。
3. 将 LCA 固定点限制为 execution/valid scope 计算；scope 提升后重定位 storage scope，
   但保持 MathObject、LogicalStateKey、version predecessor 和 computation identity。
4. 对 value-only/call-local return 保留隔离路径；对象状态不得回退到
   `_resolved_call_signature`、handle prefix 或 runtime path 猜测。
5. shadow 比较 legacy 与 typed placement；五份 authored fixture 达到零 alias、
   scope、writer 和 visibility drift 后切换 authoritative，并删除 legacy writer 恢复。

B2 完成门禁：

- 同一计算因 answer/object binding 不同仍只有一个 canonical call；
- 相同 capability 但输入 StateVersion 不同绝不合并；
- sibling 调用提升到父 scope 后，所有 exact dependency 和 return version 均可见；
- placement 连续运行两次结果不变，且不会恢复 B1 已消除的 writer；
- 五题 authored fixture、recorded provenance parity、全量 solver 回归通过；
- 以新 source fingerprint 跑五题各三个真实样本，configuration/identity drift 为零。

完成证据：

- authoritative 主链删除 preliminary wire placement、resolved-call/object-state
  字符串签名和 `_reallocate_calls`；
- 五份 authored fixture 的 placement mismatch 为 0，typed placement decision
  写入 reconciliation report 与 PlannerStateContext；
- 初次定向门禁 `301 passed`；binding/effect identity hardening 后全量 solver
  `1299 passed, 17 skipped`；
- 真实 smoke `batch-20260727-162705` 为 `14/15`，configuration、unclassified、
  placement/identity drift 均为 0。

#### B3. Identity-aware Finalizer

- 使用 logical-state writer ledger 和 runtime-destination writer ledger 做双重校验；
- 在 projection/runtime 之前验证 read version、transition chain、single writer 和 answer object identity；
- finalizer 保持幂等；
- `duplicate_point_coordinate_fact` 类冲突不再成为正常 LLM retry issue。

#### B4. Context and Retry Authority

- Context snapshot 持久化 StateVersion 和 canonical producer；
- stable graph 保存 version id，overlay 后基于 Context 重新 reconciliation；
- retry 只恢复 canonical call，不恢复已消除 alias call；
- explanation 使用 canonical call 和 student presentation placement，学生步骤不出现重复计算。

#### B5. String Logic Removal

- 依次迁移 reconciliation、placement、finalizer、Context、answer verifier、normalizer 和 recipe compiler；
- 删除 handle prefix、StateSlot 字符串拼接、semantic-name keyword 和 runtime-path identity fallback；
- 最后与 StepIntent compatibility 退场同步删除 legacy 字符串猜测。

### Stage Gates and Dependencies

- **Track A 已完成**：B0-B1 已使用五题 fixture 完成 shadow 和 allocation 门禁。
- **Functional Default Ready 前**：必须完成 B2-B4，确保 placement、finalizer、retry 不再建立平行身份。
- **Track C 可并行的部分**：C0 logical graph/event shadow 可与 B0/B1 并行；
  C1 主链要求 B1-B3，C2 retry cutover 要求 B4。
- **Track D 主链切换前**：B0-B4 是 hard prerequisite；B5 在 direct compiler shadow 期间完成。
- **Track E production best-of-N 前**：stable graph 必须已使用 version identity，否则多候选比较会聚合不一致的语义状态。

### Exit Criteria

- StateSlot allocation 只有一个生产权威服务；
- placement 不使用 return-binding 或 handle 字符串判断数学计算等价性；
- finalizer 在 runtime 前捕获 logical-state 和 runtime-destination 冲突；
- Context/retry 保存并恢复 StateVersion，不重建已删除的 alias producer；
- 五题 fixture 无身份漂移，并且 finalizer 幂等；
- B5 结束后，生产 Functional 主链不依赖对象名称、handle 前缀或 runtime path 判断身份。

## Track C: Transactional Functional Execution and Symbolic Closure

### Goal

保留整份 FunctionalPlan 的静态 graph validation，但将对象状态物化改为按拓扑顺序
逐 call 执行：

```text
LogicalFunctionalGraph
  -> resolve ready call
  -> execute
  -> validate actual outputs
  -> update Working Context
  -> continue downstream
```

在此基础上，把参数求解 method 的局部补位收敛成 runtime-grounded、声明式、可复用的
符号目标闭包系统。静态 spec 负责 effect contract，实际 runtime result 负责具体值、
substitution 和 free symbols。

### Architectural Decision

本 Track 不放到 direct compiler 之后，原因是当前最复杂的技术债不是 StepIntent 类名，
而是整图 reconciliation 必须在 runtime 前预测 return state。

顺序固定为：

```text
Track B typed identity/allocation/placement/finalizer
  -> Track C transactional interpreter
  -> Track C runtime-grounded symbolic closure
  -> Track D direct compiler
```

迁移期 interpreter 仍可把单个 call 投影成 canonical StepIntent fragment，再复用现有
compiler/runtime。这样先解决状态权威问题，再单独替换编译桥，避免一次修改两个轴。

### Current Status

`PENDING` for mainline cutover。现有 partial replay、RuntimeContext dry-run、typed
provenance、stable graph 和 symbolic target closure 是实现基础，但 production 仍采用
“整图 reconciliation/projection 后一次性 replay”。

详细设计见：

- `docs/transactional-functional-interpreter-design.md`
- `docs/symbolic-target-closure-evolution-plan.md`

### Iteration Sequence

#### C0. Logical Graph and Working Context Shadow

- 从现有 reconciliation 抽出不依赖 runtime result 的 `LogicalFunctionalGraph`；
- 定义 `pending / ready / verified / failed / blocked / eliminated / aliased` call 状态；
- 定义 attempt-local `WorkingPlannerState`；
- 现有主链不变，shadow interpreter 重放五题 fixture 并比较 call timeline；
- 一个 LLM attempt 仍只提交一个外部 PlannerStateContext version。

依赖：Track B B1 allocation authority。C0 shadow 可在 B0/B1 期间准备，但必须消费
typed allocation 结果；主链切换属于后续独立门禁。

#### C1. Transactional Call Execution

- 按 DAG ready frontier 逐 call resolve/elaborate/compile/execute；
- 每个 call 读取调用时刻之前最新 verified StateVersion；
- actual output 决定 free symbols、result form 和 optional returns；
- 成功才写入 Working Context，失败 call 不产生部分 state；
- 失败 call 的 dependents 标记 blocked，无关分支继续执行；
- per-call compiler 先复用现有 StepIntent/StepPlan bridge。

依赖：Track B B2 placement 和 B3 identity-aware finalizer。

#### C2. Context and Retry Cutover

- stable graph 直接使用 interpreter 的 verified call + StateVersion ids；
- retry graph 使用 failed roots 和 blocked dependents；
- overlay 后按 ComputationKey 和 dependency versions 判断能否复用；
- 删除整图 projected result form 对 stable graph 的权威性；
- explanation 只消费 verified canonical calls。

依赖：Track B B4 Context/retry authority。

#### C3. Preserve Functional Arg Roles

- 建立正式 `FunctionalBindingContext`；
- 保留 call arg role 到 compiler/runtime；
- graph rewrite、placement、retry overlay 后重新投影 sidecar；
- Functional 模式不再从无角色 reads 顺序猜 target Symbol。

#### C4. Runtime-grounded Closure Specs

- 在 MethodSpec 中声明 `SymbolicClosureSpec`；
- 将 equation builder、representation mapper 和 constraint filter 注册表化；
- 建立共享 `execute_symbolic_closure(...)`；
- preflight 在 LLM 调用前验证 adapter、arg 和 output 配置完整性。
- spec 只声明 target、equation source、substitution effect 和 affected returns；
- actual `SymbolicClosureResult` 决定 target value、branches、substitution 和 free symbols；
- spec/runtime 漂移产生 `planner.contract_runtime_symbol_drift`；
- 不再要求 static reconciliation 精确预测执行后的 free-symbol closure。

#### C5. Migrate Parameter Methods

建议迁移顺序：

1. `parameter_from_curve_point_on_quadratic`；
2. `parameter_from_expression_value`；
3. `parameter_from_minimum_value`；
4. `parameter_from_segment_length`；
5. 后续斜率、交点、面积等参数反求能力。

每个 method 只声明：

```text
target_arg
equation_builder
known_substitutions
representation_mapper
constraint_args
substitution_outputs
```

新增同类 capability 不得要求修改共享 dispatch。

#### C6. Strict Cleanup

- closure actual provenance 写入 PlannerStateContext；
- ParameterValue 绑定目标 Symbol identity；
- retry 定位 target arg、缺失 semantic state 和约束来源；
- explanation 从 actual provenance 生成代入、列方程、闭包和状态更新骨架；
- 删除 return free-symbol union 作为 verified state；
- 删除 speculative open/closed blocker 和重复 functional state refinement；
- 删除 Functional 模式下的 `free_quadratic_parameter_if_read`；
- 删除 method-local solve 和重复 closure helper；
- 删除基于参数名、output handle 或错误文本的 identity 猜测；
- legacy selector 只在 StepIntent 兼容路径存在期间保留。

### Sequencing With Five-Problem Parity

五题迁移和 symbolic closure 可以部分交叠：

- Heping Ermo、Xiqing 用于暴露 typed Symbol 和 closure 需求；
- C0 shadow 可以在五题 parity 期间实现，但必须消费 Track B 的 typed identity；
- C1 主链切换后必须重新建立真实样本 compatibility fingerprint；
- C4/C5 的 Symbol/ParameterValue 写入必须通过 `StateAllocationService`；
- 在五题 oracle 完整前不删除兼容路径；
- 五题 parity 后完成 transactional cutover、参数能力迁移和 C6 strict cleanup。

## Track D: Retire StepIntent Compatibility

### Terminology

必须区分：

- **StepIntentDraft**：当前 FunctionalPlan 到 runtime 之间的兼容语义桥；
- **StepPlan**：`MethodInvocation` 执行前的内部执行计划。

短中期应删除的是 LLM-facing StepIntent 入口及其兼容推断层。`StepPlan` 本身是较薄的 runtime boundary，不是当前最大技术债。

### Target

将：

```text
FunctionalPlan
  -> StepIntentDraft
  -> normalizer/resolver/recipe compiler
  -> StepPlan
```

替换为：

```text
FunctionalPlan
  -> CanonicalFunctionalGraph
  -> Function/Macro graph compiler
  -> ExecutionPlan / MethodInvocation
```

`ExecutionPlan` 可以继续复用简化后的 `StepPlan`，也可以在迁移完成后重命名。不能为了删除类名而重新制造一个语义相同的容器。

Track D 的主链切换以 Track B 的 B0-B4 完成为前置。direct compiler 必须直接消费 typed MathObject/StateVersion，不得将已删除的 handle 字符串猜测复制进新编译器。B5 在本 Track 的 shadow 和删除旧桥阶段完成。

### Current Status

`BLOCKED`。当前仍由 FunctionalPlan 投影 canonical `StepIntentDraft`，direct graph compiler
尚未成为可 shadow 对比的完整执行路径。启动默认切换前必须先满足 Functional Default
Ready 门禁。

### Migration Steps

#### D0. Product Routing Gate Retirement

`QuadraticPathMinimumSolver.enabled_problem_ids` 是当前唯一的产品级 problem-id
allowlist。它保护的是 legacy deterministic planner，不影响显式 Functional opt-in。
Track A parity complete 后启动该清理项，但只有同时满足以下条件才删除：

1. 该 family 的生产请求已由 Functional routing 接管，未知同 family 题不会再进入
   canonical 南开 deterministic planner；
2. legacy `quadratic_path_planner` 不再是该 family 的生产 fallback；
3. 任意 problem id、任意点名和等价 scope label 的同 family synthetic/E2E 用例通过；
4. 相邻 family 的负向路由测试通过；
5. 删除 `enabled_problem_ids` 配置值后，再删除 `SolverFamilySpec` 上的字段与硬门控测试，
   避免留下失效的产品开关。

不得在 Track A 数字达标后直接清空 tuple；那会扩大 legacy planner 的输入范围，而不是
完成 Functional 迁移。

#### D1. Direct Compiler and Default Cutover

1. 定义 CanonicalFunctionalGraph 的稳定 schema。
2. 让 graph compiler 直接消费 resolved calls、typed args、return allocations、placement 和 provenance。
3. 将仍有价值的 normalizer 逻辑迁入 elaborator、reconciler、placement 或 graph finalizer。
4. 建立双编译 shadow：

```text
FunctionalPlan
  -> old StepIntent bridge -> PlannerOutput A
  -> direct graph compiler -> PlannerOutput B
```

5. 对比 invocation、runtime input path、output、scope、promotion、provenance 和 answer。
6. 新 compiler 连续稳定后切换 FunctionalPlan 主链。
7. 经过观察窗口后删除旧 StepIntent 入口和兼容模块。

### Cleanup Candidates

- StepIntent LLM schema、system/user prompt 和 provider parsing；
- legacy semantic reads catalog/resolver；
- StepIntent candidate resolver；
- 依赖无角色 reads 猜输入的 binding selectors；
- StepIntent draft merge、prefix repair 和 compatibility mirrors；
- 只用于修复 LLM StepIntent 输出形态的 normalizer rules；
- `FunctionalPlan -> StepIntentDraft` projector；
- StepIntent-only recorded opt-in tests。

已登记的 legacy 专项债务：

- `strategy_repair_feedback.py` 中按
  `broken_path_straightening_minimum_expression` 字面量判断 blocker 的旧
  StepIntent repair 分支，迁入声明式 `RepairHintSpec` 后删除；
- `strategy_resolver.py` 中按 capability id 路由和按最小值 fact 名称推断输入的旧
  StepIntent resolver；
- `recipe_compiler.py` / `strategy_validator.py` 中 `m_value` 等参数名启发式，待
  FunctionalBindingContext 与 Symbol identity 成为权威后删除；
- `hexi_weighted_path_planner.py` 及 orchestrator 中的河西 deterministic planner
  接线，待 Functional default 与回滚观察窗口完成后退役。

这些代码目前位于 legacy 旁路，不能在 Track A 尾声无门禁删除；但也不得被复制到
Functional reconciler、direct compiler 或新的 capability spec。

旧 fixtures 可保留为只读 migration oracle 一段时间，但不再进入生产执行链。

### Exit Criteria

- 五题 Functional graph direct compile 与旧桥生成等价 PlannerOutput；
- Functional retry/context 不再保存或读取 StepIntent baseline；
- Function/Macro compiler 不从 reads 顺序猜 typed role；
- production 默认协议为 FunctionalPlan；
- 经过观察窗口后无 StepIntent fallback 调用；
- 删除旧桥后全量 solver 和真实 Functional opt-in 通过。

## Track E: Best-of-N and Candidate Selection

### Current Status

`IN PROGRESS`。并发样本隔离、batch runner、pass@k 和兼容指纹报告已经具备；
production winner selection、Context branch commit 和无 expected-answer 排序尚未实现。

Stage 2 acceptance 中，Nankai、Heping Ermo、Xiqing、Hexi、Heping 的 `pass@1`
分别为 `90% / 40% / 80% / 70% / 60%`，而 `pass@3` 分别为
`100% / 100% / 100% / 100% / 90%`。这说明 graph retry 具有明显价值，也说明
Heping Ermo 等复杂题仍适合后续条件式 best-of-N；生产环境不能依靠 expected answer
选择 winner。

推荐先实现条件式 best-of-3：

1. 第一候选验证充分时直接提交；
2. 第一候选失败或证据不足时再并行补两个候选；
3. 每个候选从同一个 parent PlannerStateContext 分支；
4. validation/reconciliation/runtime hard filter 淘汰确定错误；
5. 对 canonical answer signature 分组；
6. 使用 provenance 完整度、题面条件覆盖和候选共识排序；
7. 不能产生唯一可信 winner 时 retry 或安全失败。

只有 winner Context 可以提交到正式 retry memory。其他分支只作为实验 artifact 保存。

Best-of-N 是可靠性放大器，不替代五题 parity、能力覆盖和 deterministic verification。

## Track F: Problem Image Extraction Context

### Goal

把图片、OCR、PDF 或网页题面解析成可追溯、可校验的 ProblemIR，同时避免 extractor 学习 planner 的 capability-specific 组合概念。

### Current Status

`PENDING`。已有 authored ProblemIR 和设计原则，尚未建立正式
`ProblemExtractionContext` shadow benchmark 与 gold extraction metrics。

### Primitive-First Extraction

图片解析应优先产生原子事实：

- object/entity；
- angle equality、right angle；
- segment length equality；
- point on line/curve/segment；
- coordinate、quadrant、range；
- symbol、parameter domain；
- source text span 和 image region evidence；
- confidence、alternative interpretation 和 unresolved ambiguity。

例如 extractor 应输出：

```text
angle(M, D, N) = 90 degrees
length(D, M) = length(D, N)
```

而不是要求它直接发明 capability-specific 的复合事实名。复合 Condition 和 object roles 由确定性 ConditionRoleResolver、fact normalizer 或 pack contract 投影。

### Context Boundary

```text
Image/OCR
  -> extraction candidates and evidence
  -> ProblemExtractionContext
  -> deterministic normalization
  -> ProblemIR
  -> PlannerStateContext
```

`ProblemIR` 仍是 planner 的稳定输入接口，可以来自：

- authored ground truth；
- `ProblemExtractionContext.to_problem_ir()` projection。

Planner 不读取 OCR 过程数据，也不通过 description 文本补猜缺失事实。

### Initial Rollout

- 用现有五题图片和 authored ProblemIR 建立 gold dataset；
- ProblemExtractionContext 先以 shadow mode 运行；
- 单独统计 entity/fact/role/scope/symbol/geometry relation precision 和 recall；
- 低置信或多义关系在 extraction 层 retry，不污染 planner retry；
- 达到门槛后再让 extracted ProblemIR 进入 Functional planner。

## Track G: Context Modeling After Planning

### Current Status

`IN PROGRESS`。现有 ExplanationSnapshot、LessonIR 和 VisualStepIR 已能消费 solver
artifact；独立不可变的 Lesson/Diagram/Animation Context、dependency version 和
stale/rebase 机制尚未完成。

### Context Graph

解题后的 LLM 工作不应共享一个不断膨胀的万能 Context。推荐使用领域 Context：

```text
PlannerStateContext
  -> LessonExplanationContext
  -> DiagramContext
  -> AnimationContext
```

其中 DiagramContext 也可以同时依赖 ProblemExtractionContext/ProblemIR，AnimationContext 可以同时依赖 Explanation 和 Diagram。

### Shared Rules

- 每个 Context version 是不可变快照；
- 下游通过 `dependency_context_ids` 引用上游 version；
- 上游改变时，下游显式标记 stale/rebase；
- prompt 是 Context projection artifact，不是 semantic state；
- 下游不能修改上游 Context；
- runtime trace/provenance 进入 Context 前先 snapshot；
- 每个 Context 只保存本领域事实、候选、issues、stable state 和 projection metadata。

### LessonExplanationContext

输入：

- verified canonical Functional call graph；
- runtime trace 和 StateWriteProvenance；
- student narrative placement；
- QuestionGoal 和 answer provenance。

职责：

- 生成学生可理解的步骤组织；
- 保留跨小问“由前问已得”的引用；
- 区分执行位置与学生呈现位置；
- 不重新计算答案或改变 planner state。

### DiagramContext

输入：

- ProblemIR 几何对象；
- Planner state transitions；
- LessonExplanationContext 的讲解焦点。

职责：

- 保存对象到视觉实体的映射；
- 保存每一步需要显示、隐藏、强调和变换的状态；
- 记录图形约束、布局冲突和视觉验证结果；
- 不修改数学对象身份。

### AnimationContext

输入：

- Diagram state transitions；
- Lesson explanation timeline；
- voiceover/beat metadata。

职责：

- 组织动画事件和时间关系；
- 确保视觉状态与讲解步骤对齐；
- 不重新解释题目或改写解题计划。

## Recommended Delivery Order

### Milestone 1: Functional Parity Baseline

**Status: `COMPLETE`**

- `COMPLETE`：五题 FunctionalPlan fixture、离线 replay 和真实 opt-in；
- `COMPLETE`：统一并发采样基座和 Stage 1；
- `COMPLETE`：structured provenance parity、typed failure boundary 和跨 batch 聚合；
- `COMPLETE`：每题十样本 Stage 2，五题 `pass@3 >= 90%`；
- 本里程碑已完成，表示 Track A parity complete，不表示可以切默认协议。

### Milestone 2: MathObject and State Identity Authority

**Status: `IN PROGRESS`**

- `COMPLETE`：B0 typed identity foundation；
- `COMPLETE`：B1 authoritative allocation 与版本依赖 refinement；
- `COMPLETE`：B2 typed placement authority；
- `IN PROGRESS`：B3 finalizer authority，下一执行项；
- 后续完成 B4 Context/retry version authority；
- allocation、placement、finalizer、Context 和 retry 共享 typed identity 及 StateVersion；
- 同一 MathObject 的等价 producer 在 runtime 前合并，answer alias 和 downstream refs 转移到 canonical producer；
- 与 Track A parity、held-out 和生产门禁共同组成 Functional Default Ready。

### Milestone 3: Transactional Functional Execution

**Status: `PENDING`**

- 完成 LogicalFunctionalGraph 与 Working Context shadow；
- 按 ready frontier 逐 call 执行，actual output 更新 verified StateVersion；
- 一个 call 失败时保留其它独立 verified subgraph；
- stable graph 和 retry 改用 actual call state，不再依赖整图 projected result state；
- 完成 FunctionalBindingContext；
- 将 SymbolicClosureSpec 收缩为 runtime effect contract；
- 迁移参数求解 methods，所有 Symbol/ParameterValue 读写通过 Track B identity service；
- 将 actual closure provenance、retry 和 explanation 接入 Context。

### Milestone 4: Functional-Only Planner

**Status: `BLOCKED`**

- Transactional Functional Interpreter 已成为 Functional execution authority；
- 定义引用 typed StateVersion 的 CanonicalFunctionalGraph；
- 建立 direct graph compiler；
- 双编译 shadow；
- 完成 Track B B5 字符串 identity 逻辑清理；
- 切换 FunctionalPlan 为默认协议；
- 删除 StepIntent LLM 与兼容链路。

### Milestone 5: Production Reliability

**Status: `IN PROGRESS`**

- 条件式 best-of-3；
- hard filter、answer consensus 和 candidate ranking；
- 能力 gap 聚类与 Capability Pack 扩张工作流。

### Milestone 6: Cross-Domain Contexts

**Status: `PENDING`**

- ProblemExtractionContext shadow mode；
- LessonExplanationContext；
- DiagramContext；
- AnimationContext；
- context dependency、stale 和 rebase 管理。

## What Can Run in Parallel

可以并行：

- 五题 Functional fixture/opt-in 的 oracle 维护与回归；
- Track B B2/B3 的 typed placement shadow 与 finalizer 双 ledger；
- Transactional interpreter C0 的 logical graph/event shadow；
- ProblemExtractionContext schema 和 gold dataset；
- reliability metrics、batch runner 和 held-out 基础设施；
- runtime-grounded symbolic closure C3/C4 的模型与 preflight。

不应并行切换：

- StepIntent bridge 删除与五题 parity 建设；
- transactional interpreter 主链切换与 direct compiler 主链切换；
- placement/finalizer 身份权威切换与 direct compiler 主链切换；
- direct compiler 主链切换与 runtime 大规模重构；
- extracted ProblemIR 主链切换与 planner protocol 切换；
- Lesson/Diagram Context 主链切换与 canonical Functional graph schema 变化。

## Decision Rules

遇到新的真实 LLM 失败时依次判断：

1. ProblemIR 是否缺少必要原子事实？
2. Functional catalog 是否准确表达 capability？
3. 所需 capability 是否存在？
4. elaborator/reconciler 是否能唯一、幂等修复？
5. capability 实现缺口是否可以抽成共享 primitive？
6. 是否属于符号 closure、identity、scope 或 provenance 的声明缺口？
7. 是否是真正的数学路线错误，应交给 LLM retry？
8. 是否只是概率波动，应通过 pass@k 而非单次结果判断？

任何代码修复都必须回答：

- 没有 expected answer 时是否仍成立；
- 是否依赖题名、点名、变量名或错误文本；
- 新增同类 capability 是否只需声明 spec；
- 是否可能把错误数学计划修成“可运行但不正确”；
- 是否有幂等测试、provenance 和 held-out regression。

## Final Position

推荐的总体顺序是：

```text
five-problem Functional parity complete
  + MathObject / StateSlot / StateVersion identity authority
  + held-out and production readiness
  -> transactional Functional interpreter
  -> runtime-grounded declarative symbolic closure
  -> direct Functional graph compiler
  -> string-based identity removal
  -> Functional Default Ready
  -> FunctionalPlan default
  -> StepIntent compatibility removal
  -> production best-of-N
  -> ProblemExtraction and downstream Context graph
```

图片提取的数据模型和 benchmark 可以提前并行建设，但不应在 Functional planner 和 canonical graph 尚未稳定时同时切换生产主链。

最终目标不是删除所有中间计划对象，而是删除重复事实源、字符串猜测和兼容推断。Runtime 仍需要一个最小、typed、可验证的 execution boundary；这个边界可以由简化后的 StepPlan 承担，也可以在 direct compiler 阶段重命名为 ExecutionPlan。

## Related Documents

- `docs/llm-planner-reliability-engineering.md`
- `docs/math-object-state-identity-propagation-plan.md`
- `docs/transactional-functional-interpreter-design.md`
- `docs/symbolic-target-closure-evolution-plan.md`
- `docs/llm-context-model-design.md`
- `docs/functional-method-recipe-orchestration-design.md`
- `docs/family-capability-pack-upgrade-plan.md`
- `docs/capability-authoring-guide.md`
