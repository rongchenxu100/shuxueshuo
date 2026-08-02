# Functional Planner 后续演进路线

## Summary

本文档整理 Functional Planner 下一阶段的整体路线。目标仍然只有一个：

> 减少 LLM 承担的机械职责和表示自由度，将类型、身份、作用域、依赖、符号闭包、执行与验证交给确定性代码，从而提高端到端成功率。

后续工作分为四条有明确依赖关系的主线：

1. **产品协议 parity**：为五道代表题建立 FunctionalPlan 资产、真实网络稳定性基线和迁移 oracle。
2. **语义状态权威收敛**：让 `MathObject -> StateSlot -> StateVersion` 身份贯穿 allocation、call placement、finalizer、Context 和 retry。
3. **执行架构收敛**：先用独立 executable oracle 穷举 scope/version 状态机，
   再把整图静态状态预测改为 transactional call execution，随后把参数求解收敛成
   runtime-grounded 声明式符号闭包，最后删除 StepIntent 兼容桥。
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
| Track B typed identity authority | `IN PROGRESS` | B0-B4、B5a/B5b 已完成；typed consumer 的真实 execution-shadow smoke 为 `15/15`，identity fallback 为 0 | B5c 按既定顺序等待 C6 后删除 StepIntent/string projection |
| Track C transactional interpreter | `IN PROGRESS` | C0、C0.5、C1、C2、C3、C4 已完成；runtime-grounded closure 已在 `context_authoritative` 主链完成真实验收 | C5 迁移其余参数求解 method；随后由 C6 完成 closure provenance 消费与 strict cleanup |
| Functional Default Ready | `BLOCKED` | Functional 主链可 opt-in 执行 | Track A parity complete；Track B B0-B4；Track C production closure；direct compiler shadow；held-out；production observability 与回滚门禁 |
| Track D0 product routing gate retirement | `BLOCKED` | 唯一 problem-id gate 已登记 | Track A parity complete；Functional production routing 接管该 family；legacy deterministic planner 退场 |
| Track D default switch | `BLOCKED` | direct compiler 目标已定义 | Functional Default Ready 后才能切默认协议和删除 StepIntent 兼容链 |

上述状态有意将两个判断分开：

1. **Track A 是否完成**：回答五题 FunctionalPlan 是否形成稳定、可量化的迁移 oracle。
2. **是否可以切默认协议**：回答 typed identity、held-out、生产观测和回滚能力是否足以支撑产品切换。

### Immediate Next Gate

Track A 已完成，当前主线不再围绕五题概率样本做局部补丁：

1. C5 按 capability effect 逐个迁移其余参数求解 method，不按题目或变量名扩展；
2. 为每个迁移切片复用 C4 的 generated closure gate、事务回滚门禁和真实
   `context_authoritative + authoritative closure` smoke；
3. C6 完成 closure provenance 的 Context/retry/explanation 消费后，再由 B5c 删除
   StepIntent/string projection compatibility。

C0.5 的详细设计见：

- `docs/cross-scope-version-executable-oracle-design.md`

2026-07-31 的 C0.5 acceptance 证据：

- `8,000` bounded combinations + `2,000` fixed-seed expanded graphs +
  `128` semantic handoff graphs；
- bounded cohort 在四种 topology 间均衡分配，并强制覆盖
  `exact/latest/identity_only/call_result/none` 全部读取模式；
- `64` 个 dead-writer/liveness scenarios；
- adapter 按 stage reachability 做 fail-closed 比较：B1/B2/B3 始终审计；
  B3 接受后才比较 B4 retry restore、B5b state read 和 C0 graph edge/order；
  C0 dependent blocking 作为独立 lifecycle probe，即使 B3 拒绝也继续比较；
- production C0 lifecycle 精确比较 runtime root failure 的 blocked dependents，
  production liveness 精确比较 eliminated calls，B3 issue 双向比较；
- 当前 `276` 个 runtime root failure 中有 `68` 个形成 nonempty dependent
  blocking，其中 `17` 个与 B3 issue 交叉；清空 production blocked 集合时
  `68/68` 均被门禁捕获；
- parent/child `2,000` 个 bounded 场景中至少 `1,800` 个同时覆盖两层调用，
  至少 `200` 个具有显式跨 scope dependency；
- C0.5 v6 定向测试 `33 passed`，全量 solver
  `1543 passed, 17 skipped`；
- 不执行数学 method、不调用 LLM、不改变 FunctionalPlan 或 production authority。

Track E 的 held-out 基础设施和 ProblemExtractionContext schema 可以并行建设；默认协议
切换、StepIntent 删除和 transactional interpreter 主链切换仍保持阻塞。

截至 2026-07-28，B4 已完成实现与离线 authoritative cutover。retry checkpoint
持久化 canonical producer、精确 StateVersion 链、scope、result form、自由符号和
runtime destination；只有 typed checkpoint 可以获得 hard-lock 权限。旧 Functional
retry payload 会降级为 provisional memory。全量 solver 回归为
`1344 passed, 17 skipped`。真实 smoke `batch-20260728-155141` 在前两个南开样本
通过后遭遇 DeepSeek `402 Insufficient Balance`，因此只保留为外部阻塞证据，不能
作为 B4 真实门禁通过记录。

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

`IN PROGRESS`。B0、B1、B2 与 B3 已完成离线 authoritative cutover；B4 已完成
实现与离线 authoritative 门禁：Functional
return allocation、call placement 和 finalizer 统一消费 typed identity/version，
Context/debug 保存 allocation、placement、logical writer、runtime destination 和
retry checkpoint audit。B4 加固后全量 solver 回归为 `1344 passed, 17 skipped`；
初始 B3 source fingerprint 下的五题真实 smoke `batch-20260727-175944` 为 `15/15`，
configuration error、unclassified error 和成功样本 gate failure 均为 0，
没有暴露 identity、placement 或 finalization configuration drift。后续 authority
加固增加 Context/in-flight version 白名单、reconciliation exact-dependency 门禁和
compiler 反向漂移校验。B4 真实 smoke 首次补跑因 DeepSeek 余额不足中止，待恢复后
重新执行。该批次不重新定义 Track A。B5 尚未完成，部分 legacy StepIntent 路径仍
保留兼容 ledger，不得据此切换默认协议。

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

- 状态：`COMPLETE`（authoritative，2026-07-27）。
- 使用 logical-state writer ledger 和 runtime-destination writer ledger 做双重校验；
- compiler 前验证 typed object/slot/version、read version、transition predecessor、
  source visibility、single writer 和 dependency refinement；
- compiler 后从声明 output 唯一映射 promoted runtime destination，验证 destination
  collision、transition chain 和 answer MathObject identity；
- object/answer/fact projection 是同一 StateVersion 的 destination alias，不形成
  第二 writer；value-only/call-local return 不进入跨调用 logical ledger；
- Functional semantic views、context closure resolver 和 projected dependency sidecar
  均保留 Context ordinal-0 与 in-flight StateVersion；
- independent-subgraph replay 同步裁剪 typed write/dependency sidecar；
- 五份 authored fixture、recorded provenance parity 和全量 solver 回归通过，
  finalizer direct tests覆盖 transition、future read、destination collision、
  optional unmaterialized return 和幂等；
- authority 加固后的离线门禁为 `1321 passed, 17 skipped`；
- 初始 B3 source fingerprint
  `931a6a2e5fffa65373dc2d488b90ecc1eecfea2a29586052582cba2f974912b7`
  下的真实五题 smoke `batch-20260727-175944` 为 `15/15`，
  configuration/unclassified error 与成功样本 gate failure 均为 0。

#### B4. Context and Retry Authority

- 状态：`IN PROGRESS`（实现与离线 authoritative 完成；真实 smoke 外部阻塞）。
- 新增 typed retry checkpoint，持久化 StateVersion、canonical producer、
  ComputationKey、StateEffectKey、previous/source chain、scope、actual form、
  free symbols 和 runtime destination；
- 每轮仍从 ProblemIR 建立新 RuntimeContext，checkpoint 只作为待重放版本期望，
  不复用上一轮 runtime 数值；
- restore 只恢复 goal-committed canonical call；runtime-verified/provisional call
  只进入紧凑结果记忆，可以被 LLM 修改或删除；
- B2 以 checkpoint call 作为 pinned canonical owner，重命名副本变成 alias；
- B3 后同时校验静态 version chain 与实际 runtime form/destination；
- repair cone 增加 previous/source StateVersion producer edge，不再只依赖 wire
  CallResultRef；
- 旧 Functional retry payload 无 checkpoint 时降级为 provisional memory，
  `locked_call_ids=[]`，不再调用 legacy semantic overlay；
- prompt 不暴露 StateVersionId、StateSlot、runtime path 或 checkpoint；
- Context snapshot 无论成功或失败都保存 canonical producer、version predecessor、
  state effect、scope、closure 和 destination；
- 离线门禁：B4 定向测试、五份 authored fixture、provenance parity 与全量 solver
  均通过，最终为 `1344 passed, 17 skipped`；
- 真实 smoke `batch-20260728-155141`：configuration error 为 0，未出现 typed
  drift；但大量样本因 DeepSeek `402 Insufficient Balance` 零 token 失败，需余额
  恢复后以新 batch 补跑，不能把本批记为通过。

#### B5a. Functional Typed Authority Cleanup

- 状态：`IMPLEMENTED / VERIFYING`。
- `ResolvedFunctionalValue`、semantic lineage、object-role binding 和
  `ProjectedFunctionArgBinding` 携带 MathObject/StateVersion typed sidecar；
- call resolution 后、allocation 前执行 typed identity completeness 门禁；
  materialized state、condition、identity-only object 与 call-local return 必须
  唯一落入一种身份类别；
- computation key、source-version closure、placement dependency graph 和 B3 exact
  dependency 只读取 typed version/condition/object/call-result identity；
- `StateIdentityIndex` 已删除 legacy slot 索引和 in-flight legacy lookup；
- `FunctionalLegacyProjectionAdapter` 只把已确定的 typed slot/version 投影成
  StepIntent/compiler 兼容字符串，不获得 allocation、scope 或 predecessor 权威；
- reconciliation/Context 记录 `typed_identity_completeness`、
  `legacy_projection_count` 和 `legacy_identity_fallback_count`；authoritative
  门禁要求 fallback count 为 0；
- 静态 guard 禁止 authoritative identity functions 重新调用 legacy slot lookup。

#### B5b. Context and Runtime Consumer Migration

- 状态：`IN PROGRESS`（实现与离线门禁完成，当前 revision 真实 smoke 待重跑）。
- 新增 `FunctionalStateReadIndex`，以 `StateVersionId + LogicalStateKey +
  MathObjectId + scope visibility` 选择状态，再将已选版本投影到物理 runtime path；
- `PlannerStateContext` 提供 typed query facade，并记录
  `runtime_consumer_decisions / runtime_consumer_mismatches /
  legacy_runtime_identity_fallback_count`；
- Functional `EntityStateResolver`、PathTransformation consumer 和 Context Point
  state resolver 已切换到 typed identity；StepIntent 分支继续保留旧 resolver；
- PathTransformation materialized role 精确读取 producer 声明的 source version，
  不扫描同名 Point、StateSlot 字符串或 reads 顺序；
- Functional AnswerGoalVerifier 通过 LogicalAnswerBinding 锚定 answer version，
  Point identity 比较 MathObjectId，状态 evidence 沿 previous/source version 回溯；
  value-only answer 继续使用 typed call-result lineage；
- runtime path 仅作为已确定 StateVersion 的物理绑定；同一路径映射到不同
  LogicalStateKey 时 fail loud；
- authoritative 门禁要求 runtime consumer mismatch 和 legacy runtime identity
  fallback 均为 0。
- consumer authority 收口补充：
  - ProblemIR 中已物化的 entity state 在 runtime load boundary 注册为 typed
    ordinal-0 version；
  - identity-only Entity read 不再因存在 direct handle binding 绕过 typed
    object lookup；
  - PathTransformation consumer 保留 role 声明的 exact version runtime path，
    不再通过 state handle 二次绑定；
  - latest-visible 先按 consumer scope specificity 选择，再比较同一 slot 的
    ordinal；同层不可比 slot fail loud；
  - semantic read resolution 携带 MathObjectId/StateVersionId sidecar；
  - AnswerGoalVerifier 不再从裸 runtime symbol 或 `answer:` handle 前缀恢复
    Functional identity；
  - object-role reprojection 缺 source 时产生配置错误，不静默删除 role。
- 2026-07-29 最新离线门禁：B5b 组合回归 `407 passed`，全量 solver
  `1476 passed, 17 skipped`，`git diff --check` 通过；新增 fallback 事件计数
  回归，证明 `legacy_runtime_identity_fallback_count` 不再是恒零门禁。
- 2026-07-29 历史真实 smoke：`batch-20260729-204621` 五题各 3 个兼容样本
  `15/15` 在三轮内通过，每题 `pass@3 = 100%`，configuration、
  unclassified 和 successful-sample gate failure 均为 0；此前暴露的
  value-only retry checkpoint free-symbol drift 已改为使用 runtime snapshot
  权威。该批早于本次 consumer 收口修改，只作为历史证据；B5b 标记
  `COMPLETE` 前须以当前 source fingerprint 重跑 5×3 smoke。

#### B5c. StepIntent and String Projection Retirement

- 状态：`PENDING AFTER C6`。
- direct compiler/transactional interpreter 成为主链后删除 StepIntent bridge；
- 删除 canonical handle、legacy StateSlot、semantic-name keyword 和 runtime-path
  identity compatibility；
- B5c 完成后，生产 Functional 主链不再依赖任何字符串身份恢复。

### Stage Gates and Dependencies

- **Track A 已完成**：B0-B1 已使用五题 fixture 完成 shadow 和 allocation 门禁。
- **Functional Default Ready 前**：必须完成 B2-B4，确保 placement、finalizer、retry 不再建立平行身份。
- **Track C 可并行的部分**：C0 logical graph/event shadow 可与 B0/B1 并行；
  C1 主链要求 B1-B3，C2 retry cutover 要求 B4。
- **Track D 主链切换前**：B0-B4 与 B5a 是 hard prerequisite；B5b 在 C0 后完成，
  B5c 与 StepIntent bridge 退场同步完成。
- **Track E production best-of-N 前**：stable graph 必须已使用 version identity，否则多候选比较会聚合不一致的语义状态。

### Exit Criteria

- StateSlot allocation 只有一个生产权威服务；
- placement 不使用 return-binding 或 handle 字符串判断数学计算等价性；
- finalizer 在 runtime 前捕获 logical-state 和 runtime-destination 冲突；
- Context/retry 保存并恢复 StateVersion，不重建已删除的 alias producer；
- 五题 fixture 无身份漂移，并且 finalizer 幂等；
- B5a 后 Functional authoritative core 不依赖对象名称、handle 前缀、slot 字符串或
  runtime path 判断身份；B5c 后兼容投影本身退出生产主链。

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
B5a typed producer authority
  -> C0 logical graph shadow
  -> B5b typed consumer authority
  -> C0.5 scope/version executable model gate
  -> C1-C4 transactional execution and runtime-grounded closure
  -> C5 parameter method migration
  -> C6 closure provenance consumption and strict cleanup
  -> B5c StepIntent/string projection retirement
  -> Track D direct compiler
```

迁移期 interpreter 仍可把单个 call 投影成 canonical StepIntent fragment，再复用现有
compiler/runtime。这样先解决状态权威问题，再单独替换编译桥，避免一次修改两个轴。

### Current Status

`IN PROGRESS`。C0 shadow、C0.5 executable model gate、C1 transactional
execution-shadow compatibility gate、C2 Context/retry authority、C3 Functional arg
role authority 和 C4 runtime-grounded closure authority 已完成。Functional opt-in 可使用
`context_authoritative + authoritative closure`；产品默认仍为 legacy。当前进入 C5
parameter method migration。

详细设计见：

- `docs/transactional-functional-interpreter-design.md`
- `docs/cross-scope-version-executable-oracle-design.md`
- `docs/symbolic-target-closure-evolution-plan.md`

### Iteration Sequence

#### C0. Logical Graph and Working Context Shadow

- 状态：`IMPLEMENTED`。
- 从现有 reconciliation 抽出不依赖 runtime result 的 `LogicalFunctionalGraph`；
- 定义 `pending / ready / verified / failed / blocked / eliminated / aliased` call 状态；
- 定义 attempt-local `WorkingPlannerState`；
- 现有主链不变，shadow interpreter 重放五题 fixture 并比较 call timeline；
- 一个 LLM attempt 仍只提交一个外部 PlannerStateContext version。

依赖：Track B B1 allocation authority。C0 shadow 可在 B0/B1 期间准备，但必须消费
typed allocation 结果；主链切换属于后续独立门禁。

#### C0.5. Cross-Scope / StateVersion Executable Oracle Gate

- 状态：`COMPLETE`（2026-07-31），C1 hard prerequisite 已解除；
- 建立独立 reference scope/version state machine，不复用 production
  allocation、placement、visibility 或 latest-state helper；
- 有界穷举 parent/child/sibling、create/reuse/transition/isolated/conflict、
  exact/latest read、hidden dependency、alias、answer projection 和 retry checkpoint；
- 覆盖 B1 provisional allocation 到 B2 LCA publication、exact StateVersion
  reprojection的跨阶段 semantic handoff；
- 独立验证 dead provisional writer 不会因未证明的 predecessor 边污染 liveness；
- 分别比较 B1 allocation、B2 placement、B3 finalizer、B4 retry、B5b consumer
  与 C0 logical graph，不只比较最终 replay；
- 将历史真实 LLM 暴露的 scope/version 问题缩减为无题名、无点名、无答案值的
  synthetic scenario corpus；
- 默认离线门禁至少执行 `10,000` 个确定性 scenario；bounded cohort 必须在
  `root/parent_child/siblings/branched` 四种 topology 间均衡，并完整覆盖
  `exact/latest/identity_only/call_result/none`，同时保存固定 seed 和可重放
  scenario id；
- 新增 scope/version 修复必须先增加 synthetic scenario，真实 LLM 只做后续行为确认。

当前证据：`8,000` topology-balanced bounded + `2,000` fixed-seed expanded +
`128` semantic handoff + `6` authority regression scenario，另加 `64` 个使用真实
B1 allocation 的 liveness scenario。C0.5 v7 新增 ProblemIR 初始
ParameterValue exact read 与跨分支发布状态的传递来源隔离门禁。production
dependent blocking、eliminated lifecycle、
B3 issue 双向比较和 parent/child 跨 scope 覆盖下限均已进入 hard gate。
第 6 个 authority regression 覆盖 committed 公共 producer 链从 sibling scope
恢复后向共同祖先 LCA 发布，并验证 retry restore 只删除自己移空的 scope。

依赖：B1-B5b typed authority 与 C0 logical graph。详细设计见
`docs/cross-scope-version-executable-oracle-design.md`。

#### C1. Transactional Call Execution

状态：`EXECUTION SHADOW COMPLETE`（2026-07-31）。
默认仍为 legacy；测试和显式 opt-in 可使用 `execution_shadow`。

- 按 DAG ready frontier 逐 call prepare/execute；
- 每个 call 读取调用时刻之前最新 verified StateVersion；
- actual output 决定 free symbols、result form 和 optional returns；
- 成功才写入 Working Context，失败 call 不产生部分 state；
- 失败 call 的 dependents 标记 blocked，无关分支继续执行；
- per-call bridge 先复用现有 StepIntent/StepPlan 编译产物。

当前实现：

- `RuntimeContext.fork()` 为每个 canonical public call 建立隔离 branch；
- `FunctionalCallPreparationService` 在执行前从 Working State 选择 exact 或
  call-time latest-visible `StateVersionId`，并投影到事务私有 runtime snapshot；
- `FunctionalCallBridgeCompiler` 从 legacy 已编译的 StepIntent/StepPlan 图中只提取
  当前 public call 的 fragment，不重放 dependency prefix；
- Function 或 Macro 的全部 fragment 在同一 branch 中执行，runtime check、actual
  return form/free symbols 和 B3 destination finalization 全部通过后才原子提交；
- 失败 branch 不保留 declaration、temp、promotion 或 StateVersion，其 dependents
  blocked，无关分支继续；
- `execution_shadow` 同时保留 C0 observer 和 C1 execution report。两份报告均不进入
  prompt、retry、B4 checkpoint、Explanation 或正式答案；
- 五份 authored Functional fixture 已实现 legacy/C1 双跑零 hard mismatch、零
  behavior delta；
- result form、free symbols、version predecessor/source chain 任一差异均为 hard
  mismatch，不再降级为 behavior delta；
- 唯一非阻断 behavior delta 是 legacy prefix blocker 之后 C1 继续验证成功的独立
  分支；未知 delta code 会使 compatibility gate 失败；
- 对 `batch-c1-execution-shadow-20260731` 的 15 份成功计划使用当前代码离线重放时，
  `15/15` 均有完整 legacy output，且 C1 零 mismatch、零 behavior delta；
- resolver/compiler-owned 的 materialized Context 参数在最终有效 call 顺序下重新
  选择 prior typed StateVersion，legacy projection 与 C1 call-time latest 不再
  因 mutable destination 产生半新半旧读取；
- legacy 已拒绝完整 output 时不运行 C1；legacy prefix blocker 后独立分支的 call
  与 writes 统一归入同一个非阻断 delta，不再被二次归类为 hard mismatch。

依赖：Track B B2 placement、B3 identity-aware finalizer、B5b typed consumer，
以及 C0.5 generated gate 完成。C1 已解除 C2 的前置阻塞。

#### C2. Context and Retry Cutover

状态：`COMPLETE`（2026-08-01）。failure-path、shadow authority parity 与真实
`context_authoritative` acceptance 均已通过；C3 已解除前置阻塞。

- 新增 `context_shadow / context_authoritative` 两种模式；前者比较 legacy 与
  transactional authority，后者让 Functional retry、Context、goal verification
  和成功 `PlannerOutput` 直接消费逐 call 实际结果；
- `FunctionalCallCompilerService` 精确编译当前已选 Function/Macro，不搜索替代
  capability、不执行 dependency prefix；legacy bridge 继续保留为迁移 oracle；
- `FunctionalTransactionalAttemptResult` 统一携带 verified/failed/blocked calls、
  actual runtime results、typed writes、goal closure 和 root issues；
- stable graph 只冻结 passed QuestionGoal 的完整 canonical dependency closure，
  checkpoint 保存其实际 `StateVersionId / ComputationKey / StateEffectKey`；
- runtime-verified 但未 goal-committed 的结果进入精简 retry feedback，不冻结；
  failed call 不提交 write，blocked dependent 不生成次生 root issue；
- 成功时只聚合 required-goal reachable fragments，并在 fresh RuntimeContext
  重新执行；alias、dead、failed、blocked 与无关分支不进入 output/Explanation；
- external answer check 失败会撤销 goal commit，但保留实际 runtime result 和
  version snapshot 作为 provisional retry evidence；
- `context_authoritative` 不再使用 legacy parity 决定成功；transactional 内部
  mismatch 会进入正式 root issue，事务入口异常产生非 retryable configuration
  failure，禁止静默回落 legacy；
- `context_shadow` 保留 legacy B4 checkpoint 预校验，并对账 goal、聚合 output、
  typed Context version、retry locked/repair 集合与 checkpoint；shadow mismatch
  只影响迁移门禁，不改变 legacy 正式结果；
- 初始已给坐标但没有独立 coordinate fact 的 Point 现在建立 ordinal-0 typed
  StateVersion；结构化 Macro 隐藏角色也必须进入 exact StateVersion dependency；
- 当前 revision 的 C2 定向门禁为 `428 passed`，全量 solver 为
  `1588 passed, 17 skipped`。C0.5 reference/generated gate 继续覆盖
  10,000+ 个确定性场景；
  五份 authored fixture 的 goal closure output 均已在全新 RuntimeContext 重放通过。
- 首次 authoritative smoke `batch-20260731-170901` 为 `11/15`。其中和平暴露
  “子 scope 精确输入借 MathObject origin 向父 scope 发布”的 B2 缺陷，河西暴露
  legacy checkpoint 在 transactional provenance 产生前校验 runtime destination
  的双 authority 缺陷；两项均已离线复现并修复。C0.5 新增“私有 source version
  不得跨 sibling 发布”的 oracle 规则。和平二模和西青各一份失败来自模型输出/
  provider 与测试协议，不属于 C2 configuration drift。
- 上述修复改变 source fingerprint，因此该 `11/15` batch 只作为缺陷发现证据，
  不作为 C2 acceptance cohort。
- 最终 acceptance batch 为 `c2-context-authoritative-20260801-112214`：五题各
  10 个兼容样本，总计 `49/50`，五题分别达到 `pass@3 >= 90%`，全部
  `stage2_gate_passed=true`；configuration error、unclassified error 和成功样本
  gate failure 均为 0。唯一失败是 provider 连续两次只返回 reasoning、无可见
  content，记录为 `provider.reasoning_only_empty_response`，未进入 solver 执行。
- acceptance 的 `solver_source_sha256` 为
  `899d9e3cac0399e5a235de374a6a5e847b03c0f0ff09438dcdc2b2b1d7fca532`，
  与标记 C2 COMPLETE 时的当前 solver source fingerprint 一致。

依赖：Track B B4 Context/retry authority。

#### C3. Preserve Functional Arg Roles

状态：`COMPLETE`。

- 已建立正式 `FunctionalBindingContext`，逐项保存 arg role、wire/resolver/compiler
  authority、typed source、exact/latest/identity-only selection policy、aggregate
  item index 和 runtime input targets；
- reconciliation 在 B2 placement/liveness 后生成最终 binding ledger；legacy
  Functional replay 与 C2 transactional preparation 使用同一个 projector，均从
  ledger 生成 `ProjectedFunctionArgBinding`。旧 StepIntent-only 路径保持原逻辑；
- B4 committed checkpoint 保存 per-call `binding_signature`。retry restore 后 role、
  authority、StateVersion/source identity 或 runtime target 漂移会 fail loud；
  provisional call 不获得 binding hard-lock；
- PlannerStateContext 记录由 ledger/sidecar 逐项比较得到的 binding
  decisions/mismatches 与 `legacy_binding_role_fallback_count`。负例删除 role/runtime
  target 后会产生非零 mismatch/fallback，五份 authored fixture 为 0/0；
- C3 新增 2,048 个匿名 role/authority 场景。每个场景构造生产
  `FunctionalPlan`、catalog 与 reconciliation 输入，并调用
  `FunctionalBindingContextBuilder`；declared scope、placement scope、StateVersion
  ordinal、aggregate item order 和 retry call rename 均进入断言；
- transactional compiler 另运行 post-compile consumption audit，直接比较 ledger 与实际
  `MethodInvocation.inputs`。每个 runtime target 必须被消费，exact value path 必须出现在
  声明的一组 method inputs 中；resolver evidence 与 compiler selector 按各自 authority
  独立审计。它不复用 reconciliation sidecar，因此能发现 compiler/runtime mapping 漂移；
- B4 checkpoint 在 partial graph 与 runtime verification 两个入口都要求本版本 committed
  call 携带 binding signature；新建 checkpoint 缺失时 fail loud。载入升级前旧 payload
  若缺 signature，则在 JSON boundary 将整组 hard-lock 降为 runtime-verified provisional
  evidence，并记录 compatibility event，不按旧 wire identity 恢复；
- 本轮 C3 主路径门禁为 `402 passed`，C3+C0.5 联合门禁为 `405 passed`；
  全量 solver 为 `1619 passed, 17 skipped`；
- C3 acceptance batch 为 `c2-context-authoritative-20260801-140724`：五题各
  10 个样本，总计 `48/50`，五题均满足 Stage 2 的 `pass@3 >= 90%`；
  configuration error、unclassified error 和成功样本 gate failure 均为 0。
  两个失败均不是 binding authority/configuration drift。
- acceptance 的 solver source SHA-256 为
  `03c7781fdf875f254a12e48eea09091d54e4855742602eb55041e1d6438e0726`。

真实验收命令必须显式携带 C2 authority：

```bash
cd server
RUN_LLM_INTEGRATION=1 \
RUN_DEEPSEEK_FUNCTIONAL_PLANNER=1 \
uv run python -m shuxueshuo_server.solver.deepseek_functional_batch \
  --case all \
  --samples-per-case 3 \
  --concurrency 3 \
  --max-attempts 3 \
  --functional-transaction-mode context_authoritative \
  --batch-id c3-context-authoritative-smoke
```

验收前先断言 `batch-summary.functional_transaction_mode ==
context_authoritative`，并要求 configuration/unclassified error、binding mismatch 和
legacy binding role fallback 全部为 0。

#### C4. Runtime-grounded Closure Specs

状态：`COMPLETE`。

- `SymbolicClosureSpec` 已声明 target、known substitutions、known mapping inputs、
  representation mapper、constraint filter、preserved Symbol basis、substitution outputs
  和集合级 output validator；
- equation builder、representation mapper、constraint filter 与按 runtime type 分派的
  output substitution adapter 已注册表化；
- C2 单 call 事务在 method 执行前运行共享 `execute_symbolic_closure(...)`，在 method
  返回后统一校验/应用 substitution，再按实际 runtime value 计算 free symbols 与 form；
- target、known substitution 与 preserved Symbol 全部按 C3 binding ledger 的
  `MathObjectId` 校验；runtime path、符号裸名和 canonical ref 不参与身份判断；
- catalog preflight 在调用 LLM 前验证 adapter、arg、类型、output 和唯一目标策略；
  配置缺失 fail loud，不消耗 retry；
- 首个真实切片为 `quadratic_from_constraints`。它与共享 closure executor 使用同一个
  normalized quadratic constraint system builder，不按 method id dispatch；
- `disabled / shadow / authoritative` 三种内部模式已接入 C2、planner provider、batch
  CLI、fingerprint 和 summary；事务报告记录 execution/drift count；
- unique closure 的 provenance 在 authoritative output rewrite、集合级校验和
  commit-payload 校验通过后、B3 destination finalizer 之前写入受影响的
  `StateWriteProvenance`，因此 B3 可以审计 closure 证据；只有 B3 和原子 version commit
  随后均成功，这些 writes 才进入 verified result。shadow 只记录 closure result/drift，
  commit-payload 失败诊断中的 provisional writes 也不携带 closure provenance。非唯一
  closure 产生 typed retry issue 并回滚整个 call，不提交幽灵 StateVersion；
- target 已由 `known_coefficients` 或 typed known substitution 给出时，shared executor
  仍建立完整方程并检查一致性；preclosed 只避免重复求解，不会把冲突约束误判为
  `unique`，也不会把合法 determined call 改判为 `identity_unresolved`；
- method 与 shared closure 通过同一个 quadratic target-expression projector 消费 template
  representation；target 即使不在 `all_coefficients` 中，也能得到相同 target value 和
  coefficients output，不再出现 closure unique、method unconstrained 的 dual path；
- 已物化开放状态中的确定性 target expression 只要其自由符号完全属于 preserved basis，
  即作为 unique open closure；空 equation set 不再把 `b=1-c` 误判为 underdetermined；
- materialized coefficient relation 与 explicit known/ParameterValue 同时进入一致性方程；
  可由非 preserved unknown 调和时继续求解，否则 method 在 disabled/shadow 路径也直接
  inconsistent。preclosed target 的残余方程只含 preserved basis 时不能被忽略或反向求解
  preserved Symbols，统一判 inconsistent；含非 preserved unknown 且唯一可解时将该解
  合并进 closure substitution。target value 依赖未声明 preserved Symbol 时统一
  underdetermined；
- typed ParameterValue 与 `known_mapping_args` 对同一 Symbol 给出不同值时统一判
  inconsistent，不按参数收集顺序覆盖；实际 runtime mapping 的每个 Symbol key 都与
  C3 per-symbol `MathObjectId` 核对。单 fact lowering 与多 fact aggregate 使用同一规则，
  并且只为本次 invocation 实际存在的 runtime arg 建立 cardinality/identity expectation；
- constraint filter 缺少任一声明输入时 fail loud；`curve_points` 会进入 equation source
  provenance；只有 `unique` 且 runtime-validated 的 closure 才能改写 outputs 或写入
  closure provenance；
- output substitution 后会按 contract validator 重新验证每个 companion return、returns
  之间的一致性及完整 quadratic constraint system。错误常数和错误开放表达式即使
  `.subs` 为 no-op 或得到 closed form，也会产生 runtime symbol drift 并回滚整个事务；
- preclosed result 的 residual basis 包含 preserved Symbols；集合级 validator failure 直接
  分类为 `planner.contract_runtime_symbol_drift`，不再降级为普通 transactional failure；
- reconciliation 不再执行静态 symbolic substitution。它只保留 contract 与保守
  free-symbol 状态；actual residual Symbol basis 在 runtime substitution 后按
  `MathObjectId` 生成；
- 2,048 个确定性场景直接运行生产 `quadratic_constraints`、representation mapper 和
  constraint filter；显式 target 的 transactional test 保证 execution count 非零。
  五份 authored fixture 没有 `target_parameter`，只验证 `not_applicable` 不误触发，
  不作为 active closure 覆盖；真实 smoke 在 authoritative 且有效计划声明 target 时，
  额外要求单样本 symbolic closure execution count 大于 0；batch summary 还要求全批
  execution count 大于 0，否则直接令 active gate 失败，避免 LLM 全部省略 target 后
  drift=0 空转绿。本轮 C4、
  C3 binding、C0.5 scope/version 与 FunctionalPlan 联合门禁为 `504 passed`。
- 全量 solver 回归为 `1665 passed, 17 skipped`；recorded StepIntent 中没有 B5
  sidecar 的派生 Symbol 只允许在 legacy runtime migration 边界依据 producer
  provenance 补建身份，不允许按裸符号名补位。

2026-08-02 的真实 acceptance 证据：

- batch：`c2-c4-smoke-20260802-104230`；配置为五题各 5 个样本，
  `functional_transaction_mode=context_authoritative`、
  `functional_symbolic_closure_mode=authoritative`；
- 总计 `24/25` 通过。唯一失败为 `heping-ermo/sample-03` 的
  `provider.reasoning_only_empty_response`：两次 provider 请求均消耗 reasoning token
  但没有可见 JSON，未进入 FunctionalPlan、事务执行或 symbolic closure，不属于 C4
  solver/configuration 缺陷；
- symbolic closure 实际执行 `8` 次，覆盖 `b=1-c`、`c=b+1` 和 `b=a-3` 等开放
  target closure；所有执行均为 runtime-validated `unique`，drift 为 `0`，batch activity
  gate 通过；
- configuration error、unclassified error、成功样本 gate failure、transaction
  compatibility mismatch 和 behavior delta 均为 `0`；所有成功样本通过 answer、runtime、
  provenance 与 protocol gate；
- acceptance solver source SHA-256 为
  `ae2001b7887dcfd52c887ca0bf41944e2737e1e0f9f98c95b4636967f65f1714`，
  evaluation source SHA-256 为
  `2ec3a3f56f3c79b21271623eb636b71dc1fda3632277dbecb33f701c221863c8`。

当前仍未完成：

- 其余参数求解 method 的迁移，属于 C5；
- closure provenance 的完整 Context/retry/explanation 消费，属于 C6。

后续复验命令：

```bash
cd server
RUN_LLM_INTEGRATION=1 \
RUN_DEEPSEEK_FUNCTIONAL_PLANNER=1 \
uv run python -m shuxueshuo_server.solver.deepseek_functional_batch \
  --case all \
  --samples-per-case 3 \
  --concurrency 3 \
  --max-attempts 3 \
  --functional-transaction-mode context_authoritative \
  --functional-symbolic-closure-mode authoritative \
  --batch-id c4-context-authoritative-smoke
```

复验时必须断言 summary 中 transaction/closure mode 均为 authoritative，且
configuration/unclassified error、symbolic closure drift 和 failed transaction ghost
write 均为 0；任何有效计划声明 symbolic target 的样本还必须实际执行至少一次 closure。

设计边界保持不变：

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
- C0.5 在 B5b 后、C1 前实施；其 synthetic gate 是 C1 的 hard prerequisite；
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
- `COMPLETE`：B3 identity-aware finalizer authority；
- `IN PROGRESS`：B4 实现与离线 authoritative 已完成，真实 smoke 因 DeepSeek
  余额不足待补跑；
- allocation、placement、finalizer、Context 和 retry 共享 typed identity 及 StateVersion；
- 同一 MathObject 的等价 producer 在 runtime 前合并，answer alias 和 downstream refs 转移到 canonical producer；
- 与 Track A parity、held-out 和生产门禁共同组成 Functional Default Ready。

### Milestone 3: Transactional Functional Execution

**Status: `IN PROGRESS`**

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
