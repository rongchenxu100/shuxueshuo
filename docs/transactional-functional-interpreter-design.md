# Transactional Functional Interpreter 设计

## Summary

本文档定义 Functional Planner 从“整图静态 reconciliation 后一次性 replay”迁移到
“保留整图结构分析、按拓扑顺序执行 call、用真实结果更新 Working Context”的目标架构。

目标链路为：

```text
Raw FunctionalPlan
  -> whole-plan wire validation
  -> LogicalFunctionalGraph
  -> static graph analysis
  -> TransactionalFunctionalInterpreter
       -> resolve one ready call from Working Context
       -> elaborate deterministic args
       -> allocate typed returns
       -> compile and execute
       -> validate actual provenance
       -> commit verified state
  -> one PlannerStateContext version per LLM attempt
  -> stable graph / repair graph / effective canonical plan
```

这次迁移的主要目的不是更换 runtime，而是删除运行前对运行结果的过度预测：

- 不再提前猜测 Parabola、Point、Expression 的精确自由符号集合；
- 不再根据输入符号并集推断 return 一定是 open 或 closed；
- optional return 是否存在由实际执行结果决定；
- 同一 call 内求出的 substitution 如何影响其它 return，由 runtime 结果和声明式
  effect contract 共同验证；
- `PlannerStateContext` 只提交已验证的状态版本，不把 projected candidate 当成 verified
  runtime fact。

本阶段仍可把单个 call 投影到现有 canonical StepIntent/StepPlan 编译链。删除 StepIntent
兼容桥属于后续 direct compiler 阶段，不与 interpreter 切换同时进行。

## Why

当前 Functional reconciliation 在任何 method 执行前，需要为整个计划预先生成：

- return allocation；
- StateSlot 和 valid scope；
- free symbol refs；
- result form；
- transition/refinement；
- downstream semantic view；
- stable candidate projection。

这会迫使静态代码预测数学执行结果。例如：

```text
derive_parabola:
  target_parameter = a
  free_parameters = [m]

solve_m:
  returns m_value

evaluate_parabola:
  consumes parabola + m_value
```

runtime solver 成功后实际状态是：

```text
a = f(m)
Parabola.free_symbol_refs = [m]
```

但整图静态 projection 只能从输入看到 `[a, m]`。如果它不知道“本 call 会求出 a 并代回
Parabola”，下游就会错误地认为代入 `m` 后仍剩 `a`。

继续扩展静态预测会带来三类问题：

1. 每种数学对象都需要一套 projected closure 规则；
2. FunctionSpec、reconciliation、runtime method 和 Context 容易形成多份 effect 真相源；
3. 一旦 projection 在 runtime 前失败，真实 solver 永远没有机会纠正预测状态。

逐 call 执行后，后续 call 读取的是前序 call 的真实 typed result 和 verified
provenance，而不是运行前估计。

## Architecture Impact

这个迁移会在过渡期增加一个 interpreter 和 shadow comparison，但目标态会显著简化当前
架构：

- 删除 reconciliation 中针对每种 runtime object 的结果预测；
- 删除 projection、compiler、runtime 之间用于纠正 free symbols 和 result form 的补丁；
- 将 partial replay、stable graph 和 retry 统一到同一份 call execution state；
- `SymbolicClosureSpec` 只描述 capability effect，不重复实现 method 的数学结果；
- direct compiler 后可删除 per-call StepIntent bridge 和对应兼容 sidecar。

它不会把所有阶段合并成一个大循环。whole-plan wire validation、DAG、liveness 和
configuration preflight 仍应在执行前完成；只有依赖实际数学结果的状态物化被移动到逐
call transaction。这样减少的是“静态预测 runtime”的复杂度，不是类型和图约束。

## Design Principles

### 1. Whole-plan structure, incremental state

整份 FunctionalPlan 仍先做结构检查，只有对象状态和值随执行逐步物化。

静态阶段负责：

- schema 和 capability 合法性；
- call id 唯一性；
- prior-call reference 和循环检查；
- logical dependency DAG；
- required answer 的结构覆盖；
- dead call pruning；
- preliminary placement；
- capability configuration preflight。

执行阶段负责：

- 从当前 Working Context 解析 SemanticRef；
- 选择调用时刻之前最新可见 StateVersion；
- 生成 auto/mechanical args；
- 执行 Function/Macro；
- 根据实际输出确定 free symbols、result form 和 optional return；
- 创建 verified StateWriteVersion；
- 将真实状态提供给下游。

### 2. Runtime result is value authority

权威关系固定为：

```text
Function/Macro contract
  = 输入、输出、身份和状态效果的规则权威

Runtime method result
  = 本次具体值、substitution、分支和自由符号的权威

PlannerStateContext verified StateVersion
  = 已执行结果的序列化语义快照
```

contract 不能伪造结果，runtime 也不能绕过 contract 改变对象身份或 write mode。

### 3. One attempt, one committed Context version

interpreter 内部维护可变的 `WorkingPlannerState` 和隔离的 `RuntimeContext`，但不为每个
call 持久化一个外部 Context version。

```text
PlannerStateContext parent
  -> WorkingPlannerState
       call A committed internally
       call B committed internally
       call C failed
       independent call D committed internally
  -> PlannerStateContext vNext
```

attempt 结束时一次提交：

- verified calls；
- actual StateVersions；
- root failures；
- blocked dependents；
- stable graph；
- repair graph；
- execution timeline。

这样既能保存 partial verified subgraph，又不会产生大量权威快照。

### 4. No external side effects during trial

interpreter 只执行可回滚的 solver 计算：

- RuntimeContext 使用 attempt-local clone；
- Function/Macro 必须声明 purity 和 write effects；
- trial 不写外部数据库、文件或用户状态；
- 只有 winner/accepted attempt 的 Context snapshot 被正式提交。

### 5. Actual equality does not imply semantic equivalence

两个 call 只有在以下 key 一致时才能复用：

```text
capability id
+ resolved arg StateVersion ids
+ Condition identities
+ object identity and write mode
+ relevant strategy configuration
```

两个输入不同但碰巧算出相同坐标，不自动合并。数值相等不能替代 provenance 相等。

## Target Models

### LogicalFunctionalGraph

```python
@dataclass(frozen=True)
class LogicalFunctionalGraph:
    calls: tuple[LogicalFunctionalCall, ...]
    dependencies: tuple[FunctionalDependencyEdge, ...]
    answer_bindings: tuple[LogicalAnswerBinding, ...]
    scopes: ScopeGraph
    dead_call_ids: tuple[str, ...]
```

logical graph 不包含 runtime path、具体 StateSlot allocation 或 projected free symbols。

### FunctionalCallExecutionState

```python
FunctionalCallStatus = Literal[
    "pending",
    "ready",
    "running",
    "verified",
    "failed",
    "blocked_by_dependency",
    "eliminated",
    "aliased",
]

@dataclass(frozen=True)
class FunctionalCallExecutionState:
    call_id: str
    status: FunctionalCallStatus
    dependency_call_ids: tuple[str, ...]
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]]
    return_versions: tuple[StateVersionId, ...]
    root_issues: tuple[PlannerRetryIssue, ...]
```

### WorkingPlannerState

```python
@dataclass
class WorkingPlannerState:
    parent_context_id: str
    identity_index: StateIdentityIndex
    state_versions: dict[StateVersionId, StateWriteVersion]
    latest_visible_versions: dict[LogicalStateKey, StateVersionId]
    call_states: dict[str, FunctionalCallExecutionState]
    runtime_context: RuntimeContext
    events: list[ContextEvent]
```

该对象只存在于一次 attempt 内，不直接序列化为权威 Context。

### FunctionalCallExecutionResult

```python
@dataclass(frozen=True)
class FunctionalCallExecutionResult:
    call_id: str
    projected_step_ids: tuple[str, ...]
    runtime_outputs: tuple[TypedRuntimeOutput, ...]
    state_writes: tuple[StateWriteProvenance, ...]
    checks: tuple[RuntimeCheck, ...]
    trace: tuple[TraceFragment, ...]
```

`state_writes` 必须来自实际 runtime output。free symbols 由实际 SymPy value 或 typed
domain result 计算，不从输入并集复制。

## Execution Lifecycle

### Stage 1: Wire and graph validation

一次收集：

- schema errors；
- unknown capability/arg/return；
- forward refs；
- cycles；
- illegal answer bindings；
- configuration errors。

这些问题在执行前失败，不消耗数学 runtime。

### Stage 2: Logical liveness and placement

在不知道具体数值时，仍可以确定：

- 哪些 call 不在任何 answer-reachable 子图中；
- 哪些 consumer 共享同一个 logical producer；
- declared scope 和 consumer scope；
- preliminary execution scope；
- 哪些调用因显式 answer destination 不能合并。

placement 不分配最终 StateVersion。实际输入版本解析后若发现 scope 不可见，可拆分共享组
或产生 typed scope issue，不能改绑其它对象。

### Stage 3: Ready frontier execution

ready frontier 定义为：

```text
所有 required dependency 已 verified
且所有 SemanticRef 可在 Working Context 唯一解析
```

frontier 内互不依赖的 pure call 可以并发。每个 call 使用独立 runtime branch；成功后按
稳定拓扑顺序提交，避免并发完成顺序改变 Context。

### Stage 4: Resolve and elaborate one call

对 ready call：

1. 从 identity index 解析 object/condition；
2. 从 latest visible versions 选择精确 StateVersion；
3. 聚合 container args；
4. 补 auto/mechanical args；
5. 验证 cardinality、identity、scope 和 closure prerequisites；
6. 生成 typed call binding。

此阶段不扫描全局同类型值，不按名字猜参数或 Point。

### Stage 5: Compile and execute

迁移期：

```text
one reconciled Functional call
  -> canonical StepIntent fragment + typed sidecar
  -> existing Function/Macro compiler
  -> StepPlan
  -> InvocationExecutor
```

目标期：

```text
one reconciled Functional call
  -> direct Function/Macro graph compiler
  -> ExecutionPlan
  -> InvocationExecutor
```

interpreter API 不依赖其中哪一个 compiler，便于后续 shadow 切换。

### Stage 6: Validate and commit actual writes

提交前验证：

- output runtime type；
- MathObject identity；
- write mode 和 transition predecessor；
- required/optional return；
- actual free symbols 和 result form；
- object roles、lineage 和 evidence；
- single writer 和 runtime destination；
- answer provenance。

全部通过才更新 Working Context。失败 call 不产生部分 state write。

### Stage 7: Continue independent subgraphs

一个 call 失败后：

- 其 dependents 标记 `blocked_by_dependency`；
- 不重复生成次生 unknown/type/answer-unbound issue；
- 其它不依赖它的 ready call 继续执行；
- attempt 结束时稳定保存 verified independent subgraph。

## Symbolic State Effects

transactional execution 不再要求 reconciliation 精确预测数学 closure。

声明式 symbolic spec 仍可存在，但职责缩小为：

- target arg 是哪个 Symbol；
- equation builder 和约束来源；
- 成功时哪些 return 必须应用同一个 substitution；
- runtime result 与 contract 是否漂移。

它不负责提前写死：

```text
Parabola.free_symbol_refs = [m]
```

runtime 应返回：

```python
SymbolicClosureResult(
    target_object_ref="symbol:a",
    target_value=f_of_m,
    substitution={a: f_of_m},
    affected_outputs=("parabola", "coefficients"),
)
```

actual return value 决定：

```text
ParameterValue(a).free_symbol_refs = [m]
Parabola.free_symbol_refs = [m]
```

若 contract 声明 substitution 应作用于 `parabola`，但 runtime parabola 仍含 target
Symbol，报告 `planner.contract_runtime_symbol_drift`。

## Retry and Stable Graph

稳定 call 的定义：

```text
call 自身 verified
且全部 dependency StateVersions verified
且其 actual writes 通过 runtime/goal/provenance checks
```

retry state 保存：

- stable canonical calls；
-对应 StateVersion ids；
- failed root call ids；
- blocked dependents；
- actual issues；
- canonical candidate after elimination/aliasing。

下一轮 LLM 仍输出完整 FunctionalPlan。overlay 后重新构建 logical graph，并用
ComputationKey 判断 stable call 是否仍可复用。依赖版本变化时，旧 call 自动失效，不按
call id 强行冻结。

## Explanation and Student Plan

学生步骤只来自 verified canonical calls：

- failed、blocked、eliminated 和 alias call 不进入 ExplanationSnapshot；
- runtime execution scope 与 presentation scope 继续分离；
-跨小问复用生成引用，不重复展示计算；
- symbolic substitution、状态转移和 closure 说明从 actual provenance 生成。

## Migration Plan

本节的 interpreter-local 编号与总路线图对应如下：

| 本文 | Roadmap | 含义 |
| --- | --- | --- |
| T0 | Track C C0 | logical graph 与 Working Context shadow |
| T0.5 | Track C C0.5 | cross-scope / StateVersion executable oracle 与生成式门禁 |
| T1 | Track C C1 | transactional call execution |
| T2 | Track C C2 | Context / retry authority cutover |
| T3 | Track C C4-C6 | runtime-grounded closure 与静态预测清理 |
| T4 | Track D | direct compiler 与 StepIntent bridge 退场 |

### T0. Shadow event model

- 定义 logical graph、call status 和 attempt-local Working Context；
- 现有整图 replay 继续执行；
- shadow interpreter 只重放 recorded fixtures，比较 call timeline 和 writes；
- 不改变 production。

依赖：Track B B1 typed allocation foundation。

### T0.5. Scope/version executable model gate

- 使用独立 reference model 定义 scope visibility、latest-visible、allocation、
  placement、finalization、retry 和 typed consumer 的预期行为；
- 有界穷举 parent/child/sibling StateVersion 图、hidden dependency、alias 和
  retry checkpoint；
- 分阶段比较 B1-B5b 与 C0，而不是用一套 production projection验证另一套；
- 历史真实 LLM 暴露的状态错误先缩减成匿名 synthetic scenario；
- generated gate 进入默认离线回归并成为 T1 的 hard prerequisite。

详细设计见 `docs/cross-scope-version-executable-oracle-design.md`。

依赖：Track B B1-B5b 与 T0 logical graph。

### T1. Incremental execution behind opt-in

- 逐 call 使用现有 StepIntent fragment compiler；
- 实际 output 写入 Working Context；
- 下游只读取 verified state；
- partial subgraph 继续执行；
- 五题 authored Functional fixture 双路径对比。

实现状态：`EXECUTION SHADOW COMPLETE`（2026-07-31）。

当前 migration bridge 将 legacy 已编译的 `PlannerOutput` 按 Functional projection
切成单个 public call fragment。Interpreter 只执行当前 fragment，不执行 dependency
prefix；每个 fragment 在 `RuntimeContext.fork()` 上运行并在 actual output、runtime
checks、typed version chain 与 B3 destination finalization 全部通过后原子提交。
每个 materialized input 在 call 执行前从 Working State 选择 exact 或
latest-visible `StateVersionId`，再写入事务私有 snapshot path；旧 StepPlan fragment
只读取该 snapshot，不能从 mutable object path 重新猜版本。
该 bridge 保留 StepIntent/StepPlan 兼容边界，后续 direct compiler 可以替换 bridge
而不改变 interpreter transaction API。

`execution_shadow` 只生成并持久化审计报告。正式答案、retry、B4 checkpoint、
ExplanationSnapshot 与外部 PlannerStateContext 数学事实仍由 legacy replay 产生，
其 authority cutover 属于 T2/C2。

Compatibility comparator 对 result form、free symbols、selected/previous/source
version chain 做精确比较；legacy 缺字段或 closure 不同也会形成 hard mismatch。
只有 legacy prefix blocker 之后 C1 独立分支继续 verified 属于显式允许的
non-blocking behavior delta；未知 delta code 同样阻断 compatibility gate。
独立分支的 call 和 writes 作为同一个 delta 分类；legacy 已拒绝完整 compiled
output 时不运行 C1，也不复用较早的 compiled snapshot。

五份 authored fixture 已零 mismatch、零 behavior delta。历史
`batch-c1-execution-shadow-20260731` 的 15 份成功计划当前离线重放同样达到
`15/15` 完整 legacy output、C1 零 mismatch、零 behavior delta。最终有效 call
顺序下会重新解析 resolver/compiler-owned 的 materialized Context 参数，使 legacy
projection 与 call-time latest resolver 消费同一 typed StateVersion。T2/C2 前置
门禁已解除，但 production authority 仍由 legacy replay 持有，直到 T2/C2 切换。

依赖：Track B B2 placement、B3 finalizer、B5b typed consumer，以及 T0.5
generated gate 完成。

### T2. Context and retry cutover

实现状态：`COMPLETE`（2026-08-01）。exact execution、goal closure、
Context/retry projection、failure-path 与 shadow authority parity 均已收口，
C3 已解除前置阻塞。

- `context_shadow` 保留 legacy 正式结果，同时比较 transactional goal、Context、
  checkpoint、repair cone 与聚合 output；
- `context_authoritative` 由逐 call actual provenance 生成正式 Functional Context、
  call memory、B4 checkpoint、retry state 和 goal-reachable `PlannerOutput`；
- stable graph 只保存 passed required-goal closure 的 canonical call 与精确
  StateVersion chain；provisional runtime result 只进入反馈，不获得恢复权；
- failed transaction 不提交 write；blocked dependent 进入 repair cone但不产生
  次生 root issue；无关分支失败不阻断已完整证明的 required goals；
- aggregate output 在 B3 destination finalizer 后交给现有 Orchestrator重新执行，
  不复用 transaction branch 的 RuntimeContext 数值；
- hidden materialized role 必须由 capability Context resolver投影 exact version
  dependency，确保 goal closure裁剪不会漏掉 runtime producer；
- legacy replay继续作为 shadow oracle，产品默认尚未切换。
- authoritative 不使用 legacy parity 阻断 transactional success；transactional
  内部 mismatch 必须形成正式 retry/fail，入口异常必须 fail-closed，不允许回落
  legacy；
- context shadow 保留 legacy checkpoint 预校验，并比较 goal、聚合 output、typed
  Context version、retry locked/repair 集合和 checkpoint。shadow mismatch 不改变
  legacy 正式输出，但阻断 C2 acceptance；
- 首次 smoke `batch-20260731-170901` 为 `11/15`，并暴露两项 authority 缺陷：
  精确 child-scope source 被错误发布到父 scope，以及 legacy checkpoint 抢在
  transactional provenance 前校验 destination。两项均已离线修复，前者已进入
  C0.5 的跨 sibling publication oracle；该 batch 因 source fingerprint 已变化，
  仅保留为缺陷发现证据。
- 当前 revision 的离线证据为 C2 定向集 `427 passed`、C0.5
  reference/generated gate `34 passed`（10,000+ deterministic scenarios）、
  全量 solver `1587 passed, 17 skipped`。
- 最终 acceptance batch `c2-context-authoritative-20260801-112214` 在当前
  solver fingerprint 上运行五题各 10 个兼容样本，结果 `49/50`；五题全部满足
  `pass@3 >= 90%`、configuration/unclassified error 为 0、成功样本 gate failure
  为 0。唯一失败为 provider 连续两次 reasoning-only 空响应，不属于
  transactional Context/retry authority 漂移。T2/C2 因此完成，下一阶段进入
  T3/C3。

依赖：Track B B4 Context/retry authority。

### T3. Static prediction cleanup

逐步删除：

- return free-symbol union 作为最终状态；
- speculative closed/open blocker；
- duplicated functional state refinement；
- optional return 的静态存在性猜测；
- projection/runtime symbol correction 分支。

保留：

- capability type/effect contract；
- preflight；
- runtime drift validator；
- prompt-facing possible forms。

### T4. Direct compiler integration

interpreter 的 per-call compiler 接口切到 direct Function/Macro graph compiler。旧
StepIntent bridge 进入 shadow，达到 parity 后删除。

## Test Plan

### Unit

- call A 的实际 Symbol substitution 被 call B 读取；
- actual free symbols 覆盖 projected estimate；
- failed call 不提交任何 write；
-独立 call 在另一分支失败时仍执行；
- blocked dependents 只保留根因；
- optional return 只在 runtime 实际产生时 allocation；
-同一 ComputationKey 复用，输入版本不同不复用；
-并发 frontier 的提交顺序稳定。

### Context

- attempt 内多个 call 只产生一个外部 Context version；
- verified StateVersions、failed roots 和 blocked dependents 可 round-trip；
- retry overlay 只复用依赖版本未变化的 stable call；
- runtime value 不作为 mutable object 泄漏进 Context snapshot。

### Compatibility

- 五份 Functional fixture 通过旧整图 replay和 transactional interpreter；
- answer、runtime checks、provenance 和 presentation plan 等价；
- recorded StepIntent 继续作为迁移 oracle；
- direct compiler 未切换前，InvocationExecutor 行为不变。

### Real

- 五题 Functional opt-in 在 transactional mode 下建立独立 compatibility fingerprint；
-每题 Stage 1 `3/3`；
-同 fingerprint 下再执行 Stage 2；
-错误统计不新增 unclassified/configuration drift。

## Non-goals

- 不让 LLM 输出 patch-only plan；
- 不允许 forward reference 或循环图；
- 不自动选择数学 capability；
- 不根据 expected answer 修改 state；
- 不在本阶段删除 StepPlan/InvocationExecutor；
- 不把 RuntimeContext 变成 PlannerStateContext；
- 不通过实际值相等合并不同 provenance 的调用。

## Roadmap Placement

本设计属于 Functional Planner 路线的执行架构收敛阶段：

```text
Track A parity oracle
  -> Track B typed MathObject/StateVersion authority
  -> Track C transactional Functional execution
  -> Track C runtime-grounded symbolic closure cleanup
  -> Track D direct Functional compiler / StepIntent retirement
```

可在 Track A Stage 2 期间开发 T0 shadow，但任何主链切换都会改变 compatibility
fingerprint，必须在切换后重新建立真实样本门禁。

## Related Documents

- `docs/functional-planner-next-stage-roadmap.md`
- `docs/math-object-state-identity-propagation-plan.md`
- `docs/symbolic-target-closure-evolution-plan.md`
- `docs/llm-context-model-design.md`
- `docs/capability-authoring-guide.md`
