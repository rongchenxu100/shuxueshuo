# Functional Planner 后续演进路线

## Summary

本文档整理 Functional Planner 下一阶段的整体路线。目标仍然只有一个：

> 减少 LLM 承担的机械职责和表示自由度，将类型、身份、作用域、依赖、符号闭包、执行与验证交给确定性代码，从而提高端到端成功率。

后续工作分为四条有明确依赖关系的主线：

1. **产品协议迁移**：为五道代表题建立 FunctionalPlan parity，并将 FunctionalPlan 切换为默认 planner 协议。
2. **语义状态权威收敛**：让 `MathObject -> StateSlot -> StateVersion` 身份贯穿 allocation、call placement、finalizer、Context 和 retry。
3. **执行架构收敛**：把参数求解补位收敛成声明式符号目标闭包，随后删除 StepIntent 兼容桥。
4. **工作流 Context 扩展**：建立图片题目提取 Context，以及解题后 Explanation、Diagram、Animation Context。

四条主线不能同时无门禁地修改主链路。每一阶段都必须先形成可重放 oracle、分层指标和退出条件，再进入下一阶段。

## Current Baseline

当前已经具备：

- `PlannerStateContext` 作为 semantic reads、retry memory 和 graph state 的主要来源；
- Capability Pack、CapabilityContract、FunctionSpec 和 MacroSpec；
- FunctionalPlan strict opt-in、deterministic elaboration、reconciliation、call placement 和 graph retry；
- FunctionalPlan 到 canonical `StepIntentDraft` 的兼容投影；
- 现有 `RecipeTrialExecutor -> StepPlan -> MethodInvocation -> InvocationExecutor` 执行链；
- symbolic target closure、scalar result closure、constraint analysis 等共享原语的初始实现；
- 南开 FunctionalPlan fixture、few-shot 和真实 DeepSeek opt-in。

语义身份收敛不再只是跨阶段备注，它是下文 **Track B** 的正式实施主线。详细方案见：

- `docs/math-object-state-identity-propagation-plan.md`

2026-07-20 的南开并发三样本结果：

```text
pass@1 = 1/3
pass@3 = 3/3
```

三个样本最终答案和 runtime checks 一致。这证明 FunctionalPlan 路线已经可用，也说明第一轮稳定性、configuration preflight 和部分 capability/runtime 契约仍需继续收敛。

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
  -> Context reconciliation
  -> CanonicalFunctionalGraph
  -> Function/Macro graph compiler
  -> ExecutionPlan / MethodInvocation
  -> InvocationExecutor
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

### Exit Criteria

- 五题离线 fixture 100% 稳定通过；
- 五题真实 opt-in 在最多三轮内达到约定的 `pass@3` 门槛；
- `planner_configuration_error` 不消耗 LLM retry，并在发起请求前暴露；
- FunctionalPlan 不回退 legacy StepIntent binding；
- Function/Macro/identity/provenance 无 compatibility fallback；
- Track B Iteration 0-4 完成：allocation、placement、finalizer、Context 和 retry 共用同一 typed identity；
- 同一 MathObject 的重复 writer 不再延迟到 runtime 以 `duplicate_*` 报错；
- held-out 题没有显著退化；
- 每个失败可归入 extraction、validation、elaboration、reconciliation、binding、runtime、goal verification 或 strategy error。

## Track B: MathObject Identity and State Version Authority

### Goal

将 `PlannerStateContext` 中已经存在的 MathObject 身份真正提升为 allocation、placement、finalizer、retry 和 explanation 的共享权威源，逐步删除 handle 字符串、scope 前缀和 runtime path 对象身份猜测。

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

- 引入 `MathObjectId / LogicalStateKey / StateSlotId / StateVersionId / RuntimeDestinationKey / ComputationKey`；
- 在现有模型中增加 typed identity sidecar，与旧 string id 做 shadow comparison；
- 不改变 runtime 行为，先用五题 fixture 验证 projection 一致性。

#### B1. Allocation Authority

- 实现 `StateIdentityIndex + StateAllocationService`；
- Context 状态和 in-flight Functional return 共用同一 allocation 索引；
- 区分 reuse、transition、isolated state 和 identity conflict；
- 首个门禁是南开 D 在 `i / ii_1 / ii_2` 中只有一个 canonical writer。

#### B2. Placement Uses Identity Decisions

- placement 使用 `ComputationKey + StateEffectKey`，不再将 answer/object return binding 差异当成两次数学计算；
- answer alias 可以在等价 producer 合并时转移；
- LCA 只决定 execution/valid scope，不重新创建对象状态身份；
- downstream refs、projection map 和 provenance 统一指向 canonical call/version。

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

- **Track A 进行中**：立即实施 B0-B1，对现有五题 fixture 做 shadow 和 allocation 门禁。
- **Track A 退出前**：必须完成 B2-B4，确保 placement、finalizer、retry 不再建立平行身份。
- **Track C 可并行的部分**：C1/C2 可与 B0/B1 并行；C3 开始前要求 B1 完成，C4/C5 要求 B4 完成。
- **Track D 主链切换前**：B0-B4 是 hard prerequisite；B5 在 direct compiler shadow 期间完成。
- **Track E production best-of-N 前**：stable graph 必须已使用 version identity，否则多候选比较会聚合不一致的语义状态。

### Exit Criteria

- StateSlot allocation 只有一个生产权威服务；
- placement 不使用 return-binding 或 handle 字符串判断数学计算等价性；
- finalizer 在 runtime 前捕获 logical-state 和 runtime-destination 冲突；
- Context/retry 保存并恢复 StateVersion，不重建已删除的 alias producer；
- 五题 fixture 无身份漂移，并且 finalizer 幂等；
- B5 结束后，生产 Functional 主链不依赖对象名称、handle 前缀或 runtime path 判断身份。

## Track C: Declarative Symbolic Target Closure

### Goal

把针对参数求解 method 的局部补位收敛成声明式、可复用的符号目标闭包系统。

详细设计见：

- `docs/symbolic-target-closure-evolution-plan.md`

### Iteration Sequence

#### C1. Preserve Functional Arg Roles

- 建立正式 `FunctionalBindingContext`；
- 保留 call arg role 到 compiler/runtime；
- graph rewrite、placement、retry overlay 后重新投影 sidecar；
- Functional 模式不再从无角色 reads 顺序猜 target Symbol。

#### C2. Declarative Closure Specs

- 在 MethodSpec 中声明 `SymbolicClosureSpec`；
- 将 equation builder、representation mapper 和 constraint filter 注册表化；
- 建立共享 `execute_symbolic_closure(...)`；
- preflight 在 LLM 调用前验证 adapter、arg 和 output 配置完整性。

#### C3. Migrate Parameter Methods

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

#### C4. Context, Retry, and Explanation

- closure provenance 写入 PlannerStateContext；
- ParameterValue 绑定目标 Symbol identity；
- retry 定位 target arg、缺失 semantic state 和约束来源；
- 不把内部 residual symbols 作为 LLM 必须绑定的新参数；
- explanation 从 provenance 生成确定性的代入、列方程、闭包和状态更新骨架。

#### C5. Strict Cleanup

- 删除 Functional 模式下的 `free_quadratic_parameter_if_read`；
- 删除 method-local solve 和重复 closure helper；
- 删除基于参数名、output handle 或错误文本的 identity 猜测；
- legacy selector 只在 StepIntent 兼容路径存在期间保留。

### Sequencing With Five-Problem Parity

五题迁移和 symbolic closure 可以部分交叠：

- Heping Ermo、Xiqing 用于暴露 typed Symbol 和 closure 需求；
- C1/C2 可以在五题 parity 期间实现，但必须消费 Track B 的 typed identity；
- C3 以后的 Symbol/ParameterValue 写入必须通过 `StateAllocationService`；
- 在五题 oracle 完整前不删除兼容路径；
- 五题 parity 后完成 C3-C5 strict cleanup。

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

### Migration Steps

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

旧 fixtures 可保留为只读 migration oracle 一段时间，但不再进入生产执行链。

### Exit Criteria

- 五题 Functional graph direct compile 与旧桥生成等价 PlannerOutput；
- Functional retry/context 不再保存或读取 StepIntent baseline；
- Function/Macro compiler 不从 reads 顺序猜 typed role；
- production 默认协议为 FunctionalPlan；
- 经过观察窗口后无 StepIntent fallback 调用；
- 删除旧桥后全量 solver 和真实 Functional opt-in 通过。

## Track E: Best-of-N and Candidate Selection

当前南开 `pass@1=1/3`、`pass@3=3/3` 说明并发候选具有明显价值，但生产环境不能依靠 expected answer 选择 winner。

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

- 建立 Heping Ermo、Xiqing、Hexi、Heping FunctionalPlan fixture 和 opt-in；
- 建立统一并发采样基座和分层报告；
- 在 parity 迭代中同步完成 Track B 的 B0/B1，不再为 duplicate writer 增加局部字符串补丁；
- 固化五题 regression 与 held-out 门禁。

### Milestone 2: MathObject and State Identity Authority

- 完成 Track B 的 B2-B4；
- allocation、placement、finalizer、Context 和 retry 共享 typed identity 及 StateVersion；
- 同一 MathObject 的等价 producer 在 runtime 前合并，answer alias 和 downstream refs 转移到 canonical producer；
- 五题 parity 达标后才能退出本里程碑。

### Milestone 3: Symbolic Closure

- 完成 FunctionalBindingContext；
- 完成 SymbolicClosureSpec 和 adapter registries；
- 迁移参数求解 methods，所有 Symbol/ParameterValue 读写通过 Track B identity service；
- 将 provenance、retry 和 explanation 接入 closure。

### Milestone 4: Functional-Only Planner

- 定义引用 typed StateVersion 的 CanonicalFunctionalGraph；
- 建立 direct graph compiler；
- 双编译 shadow；
- 完成 Track B B5 字符串 identity 逻辑清理；
- 切换 FunctionalPlan 为默认协议；
- 删除 StepIntent LLM 与兼容链路。

### Milestone 5: Production Reliability

- 条件式 best-of-3；
- hard filter、answer consensus 和 candidate ranking；
- 能力 gap 聚类与 Capability Pack 扩张工作流。

### Milestone 6: Cross-Domain Contexts

- ProblemExtractionContext shadow mode；
- LessonExplanationContext；
- DiagramContext；
- AnimationContext；
- context dependency、stale 和 rebase 管理。

## What Can Run in Parallel

可以并行：

- 五题 Functional fixture/opt-in 的资产建设；
- MathObject identity B0/B1 的 typed model、shadow comparison 和 allocation service；
- ProblemExtractionContext schema 和 gold dataset；
- reliability metrics、batch runner 和 held-out 基础设施；
- symbolic closure C1/C2 的模型与 preflight。

不应并行切换：

- StepIntent bridge 删除与五题 parity 建设；
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
five-problem Functional parity
  -> MathObject / StateSlot / StateVersion identity authority
  -> declarative symbolic closure
  -> direct Functional graph compiler
  -> string-based identity removal
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
- `docs/symbolic-target-closure-evolution-plan.md`
- `docs/llm-context-model-design.md`
- `docs/functional-method-recipe-orchestration-design.md`
- `docs/family-capability-pack-upgrade-plan.md`
- `docs/capability-authoring-guide.md`
