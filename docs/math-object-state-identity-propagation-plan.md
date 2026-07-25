# MathObject 身份贯穿 StateSlot、Placement 与 Finalizer 实现计划

## Summary

本文档定义如何把 `PlannerStateContext.MathObject` 提升为 planner 状态身份的权威根，
并让这份身份贯穿：

```text
ProblemIR / FunctionalPlan
  -> MathObject identity
  -> StateSlot allocation
  -> StateWriteVersion
  -> Functional call placement
  -> canonical StepIntent projection
  -> finalizer validation
  -> runtime destination
```

目标不是删除 scope，也不是把所有同名对象强行合并，而是明确区分四种身份：

1. 数学对象是谁；
2. 对象的哪一种语义状态；
3. 该状态的哪个作用域版本；
4. 最终写入哪个 runtime destination。

随后以结构化身份、可见性和 provenance 代替 handle 前缀、字符串拼接、语义名称关键字
和 runtime path 猜测。

本计划首先修复“第一问已经求出 D，后续小问重复求 D”这类跨 scope 重复写入，
再逐步迁移其他字符串身份逻辑。迁移过程必须保持 FunctionalPlan wire schema、
StepIntent runtime bridge 和现有五题 fixture 兼容。

## Roadmap Placement

本计划是 `docs/functional-planner-next-stage-roadmap.md` 中的 **Track B: MathObject
Identity and State Version Authority**，不是可以推迟到 StepIntent 退场后的独立清理。

实施时间固定为：

1. **五题 FunctionalPlan parity 进行中**：完成 Iteration 0-1，建立 typed
   identity shadow 和统一 allocation authority。
2. **五题 parity 退出前**：完成 Iteration 2-4，让 placement、finalizer、
   Context 和 retry 共享 StateVersion 身份。
3. **direct Functional graph compiler shadow 期间**：完成 Iteration 5，删除
   生产 Functional 主链的字符串 identity fallback。

依赖关系：

- 声明式 Symbolic Closure 的前两个建模阶段可与 Iteration 0-1 并行；
- Symbol/ParameterValue 大规模迁移必须消费本计划的 allocation/version 身份；
- StepIntent compatibility 主链删除以 Iteration 0-4 完成为 hard prerequisite；
- production best-of-N 启用前，stable graph 必须已保存 canonical StateVersion。

## Current Failure

南开样本中三个调用都在计算同一个数学对象 D 的坐标：

```text
i_axis_from_relation
  object_ref = point:problem:D
  state_slot = point:problem:D.coordinate@problem

ii1_axis
  object_ref = point:problem:D
  state_slot = point:problem:D.coordinate@ii

ii2_axis
  object_ref = point:problem:D
  state_slot = point:problem:D.coordinate@ii
```

当前行为是：

- `ii1_axis` 与 `ii2_axis` 的完整 `state_slot_id` 相同，因此能够合并；
- 第一问的 slot 使用 `@problem`，与第二问的 `@ii` 不同，因此不能合并；
- finalizer 也只按完整 `state_slot_id` 检查 single writer；
- runtime 最终把两者都投影到 `$problem.points.D`，此时才报
  `duplicate_point_coordinate_fact`。

这说明 Context 已经识别出同一个 `MathObject`，但 object identity 尚未成为 allocation、
placement 和 finalizer 的共同判定基础。

## Design Goals

### Required

- 同一个对象的祖先可见状态可以被后续 scope 复用。
- 同一个对象在兄弟 scope 中基于不同私有输入产生的状态不能被误合并。
- 开放状态到闭合状态、参数化坐标到数值坐标等合法 refinement 记录为 transition。
- answer binding、fact handle、semantic ref 和 runtime path 都只是同一状态的 projection。
- call placement 在 runtime 前消除可证明的重复纯计算。
- finalizer 同时检查 StateSlot writer 和 runtime destination writer。
- Context round-trip 后仍能恢复对象、状态、版本和写入决策。
- 新增同类 capability 只声明 identity/write semantics，不修改 placement/finalizer 分支。

### Non-goals

- 不按实际数值碰巧相等合并两个来源不同的调用。
- 不把所有同名 Point 或相同 semantic ref 当成同一对象。
- 不删除 scope visibility；scope-private state 仍必须隔离。
- 不自动替 LLM 选择数学路线。
- 不在本阶段删除 StepIntent 或 RuntimeContext。

## Canonical Identity Model

### 1. MathObjectId

`MathObjectId` 表示数学对象本身，不表示对象当前的值：

```python
@dataclass(frozen=True, order=True)
class MathObjectId:
    value: str
    kind: ObjectSemanticKind
    origin_scope_id: str
```

示例：

```text
point:problem:D
function:problem:parabola
symbol:problem:m
line:ii:E_locus
```

权威来源按优先级为：

1. ProblemIR entity identity；
2. answer goal 的 `target_handle`；
3. Function/Macro return 的 `identity_policy + identity_arg`；
4. `derived_role` 通过统一 factory 创建的新对象身份。

禁止通过 description、点名字母、handle substring 或 strategy/reason 推断对象等价性。

### 2. LogicalStateKey

`LogicalStateKey` 表示“某个对象的某一种 typed semantic state”，不包含存储 scope：

```python
@dataclass(frozen=True, order=True)
class LogicalStateKey:
    object_id: MathObjectId
    state_kind: str
    runtime_type: str
```

示例：

```text
(D, coordinate, Point)
(parabola, expression, Parabola)
(m, value, ParameterValue)
(D, candidate, PointList)
```

`runtime_type` 必须参与 key，因此 `Point` 与 `PointList` 永远不会因为都属于 point
对象而被合并。

### 3. StateSlotId

`StateSlotId` 表示 LogicalState 在某个 scope 中建立的可见存储槽：

```python
@dataclass(frozen=True, order=True)
class StateSlotId:
    logical_key: LogicalStateKey
    storage_scope_id: str
```

保留 scope 的原因是同一个对象可能在两个不可互见的 sibling scope 中拥有不同状态。
因此不能简单把 scope 从现有 `slot_id` 中删除。

字段语义统一为：

```text
origin_scope_id      MathObject 在 ProblemIR 中的归属
storage_scope_id     StateSlot 实际建立的位置
valid_scope_id       该状态可见的 scope 根
execution_scope_id   产生该状态的 call 实际执行位置
presentation_scope_id 学生讲解位置，不参与状态身份
```

### 4. StateVersionId

每次合法写入形成一个有序版本：

```python
@dataclass(frozen=True, order=True)
class StateVersionId:
    slot_id: StateSlotId
    ordinal: int
```

`StateWriteVersion` 增加：

```text
version_id
logical_state_key
computation_fingerprint
source_version_ids
valid_scope_id
free_symbol_refs
write_mode
transition_kind
```

### 5. RuntimeDestinationKey

`RuntimeDestinationKey` 是最后一道防线，表示 runtime 实际写入位置：

```python
@dataclass(frozen=True, order=True)
class RuntimeDestinationKey:
    object_id: MathObjectId | None
    state_kind: str
    runtime_type: str
    runtime_path: str
```

runtime path 只用于验证 projection 是否一致，不能反向成为 MathObject 身份来源。

## Shared Services

新增 `solver/state_identity.py`，作为身份模型和判定原语的单一来源。

### MathObjectRegistry

职责：

- canonical handle、answer target、semantic ref 到 `MathObjectId` 的映射；
- object kind 和 origin scope；
- alias 只映射到 object id，不直接决定 StateSlot；
- 解析失败、歧义和 object-kind mismatch 返回 typed result，不抛字符串错误。

### StateIdentityIndex

索引 Context 现有状态和当前 candidate 中已经 reconciled 的状态：

```python
class StateIdentityIndex:
    def slots_for(self, key: LogicalStateKey) -> tuple[StateSlot, ...]: ...

    def latest_visible(
        self,
        key: LogicalStateKey,
        *,
        consumer_scope_id: str,
        before_call_id: str | None,
    ) -> StateWriteVersion | None: ...

    def writes_for_destination(
        self,
        destination: RuntimeDestinationKey,
    ) -> tuple[StateWriteVersion, ...]: ...
```

### ScopeVisibilityResolver

统一以下判断：

- ancestor state 是否对 consumer 可见；
- sibling-private state 是否不可见；
- call 提升到 LCA 后所有输入是否仍可见；
- answer/object destination 所需 valid scope；
- transition 的 previous version 是否在时间点和 scope 上可见。

所有模块禁止再各自实现 parent-chain 或 scope 字符串判断。

### StateAllocationService

输入：

```text
Functional call
resolved args
return spec
identity policy
requested write mode
Context + in-flight StateIdentityIndex
scope graph
```

输出：

```python
StateAllocationDecision =
    ReuseExistingState
  | CreateNewState
  | TransitionExistingState
  | IsolatedScopedState
  | StateIdentityConflict
```

每个 decision 必须包含：

```text
logical_state_key
selected slot/version
previous version
runtime destination
reason code
deterministic rewrite
```

## Allocation Algorithm

对每个 Function/Macro return 按以下顺序执行。

### Step 1: Resolve MathObject

根据 `identity_policy` 决定 object：

```text
preserve_input_object -> identity_arg 的 MathObjectId
target_object         -> answer/object binding 的 MathObjectId
derived_role          -> CanonicalStateHandleFactory 创建的新 MathObjectId
value_only            -> 不建立 MathObject；使用 value state owner
```

identity 不能唯一解析时输出 typed issue：

```text
functional.return_identity_unresolved
functional.return_identity_ambiguous
functional.return_identity_mismatch
```

### Step 2: Build LogicalStateKey

`state_kind` 与 `object_kind` 只从 `state_semantics.py` 和 return contract 投影。
不允许调用方本地重写 runtime-type mapping。

### Step 3: Query Visible Versions

查询：

```text
Context 已验证历史
+ 当前 candidate 中拓扑上更早的 return allocations
+ stable graph 恢复的 canonical writes
```

只考虑对当前 call scope 可见的版本。

### Step 4: Classify the Write

#### ReuseExistingState

同时满足：

- capability 为纯函数或 shareable macro；
- resolved args 指向相同 StateVersion/Condition；
- return role、identity policy 和 runtime type 相同；
- computation fingerprint 相同；
- result form 不冲突；
- 已有状态对当前及所有 consumer scope 可见。

行为：

- 不创建新 StateSlot writer；
- duplicate call alias 到原 producer；
- downstream CallResultRef 重写到 canonical call；
- answer binding 转移到 canonical producer；
- Context 记录 `reuse_visible_object_state`。

#### TransitionExistingState

满足：

- LogicalStateKey 相同；
- contract 声明 transition，或 dependency refinement 可证明；
- 新 write 直接或传递依赖 previous version；
- 自由符号严格减少，或状态阶段按 contract 单调推进；
- previous version 对当前 call 可见。

行为：

- 复用同一个 StateSlot；
- 新增 StateWriteVersion；
- 写入 `previous_write_step_id/version_id`；
- downstream 读取调用时间点之前的最新版本。

#### IsolatedScopedState

LogicalStateKey 相同但已有版本不可见，且不同 scope 的输入来源合法不同。

行为：

- 在当前 storage scope 创建独立 StateSlot；
- 不合并；
- runtime destination 必须同样隔离，不能仍写入祖先对象的单一路径。

如果 runtime 无法表达两个隔离版本，应在 compiler preflight 报 configuration error。

#### StateIdentityConflict

对象相同但：

- 计算依赖不同且都试图写同一个可见版本；
- 两次都是 create；
- transition 没有依赖 previous version；
- runtime destination 相同但 StateSlot 被错误拆开；
- answer destinations 或 result forms 冲突。

必须在 projection 前失败，不能等到 runtime。

## Computation Fingerprint

调用等价性拆为两个结构化 key：

```python
@dataclass(frozen=True)
class ComputationKey:
    capability_id: str
    arg_versions: tuple[ArgVersionBinding, ...]
    condition_ids: tuple[str, ...]
    auto_arg_versions: tuple[ArgVersionBinding, ...]

@dataclass(frozen=True)
class StateEffectKey:
    returns: tuple[LogicalReturnEffect, ...]
```

必须包含：

- capability id；
- arg role，而不是 reads 顺序；
- StateVersionId / ConditionId；
- Symbol identity 和 ParameterValue version；
- return LogicalStateKey；
- identity policy、write mode 和 transition kind。

不得包含：

- call id；
- strategy/reason；
- display label；
- raw handle spelling；
- answer binding；
- presentation scope。

answer binding 是 state 的 projection destination，不是数学计算的一部分。

## Call Placement Integration

`FunctionalCallPlacementService` 改为消费 allocation decisions，而不是重新解释 handle。

### Placement Sequence

```text
logical reconciliation
  -> provisional object identities
  -> StateAllocationService
  -> computation/state-effect grouping
  -> visibility-safe merge
  -> execution-scope LCA
  -> final return valid scopes
  -> canonical handles and StateSlot ids
```

当前 placement 的 `_resolved_call_signature` 与
`_resolved_object_state_signature` 应逐步替换为 `ComputationKey + StateEffectKey`。

### Answer Binding Transfer

若同一 canonical state 同时需要：

```text
answer:i.axis_point
point:problem:D
```

只保留一个 StateWriteVersion，并保存多个 projection destination。FunctionalPlan v1
仍只展示原 answer binding；内部 Context 可以表示 answer alias 与 object projection。

不同 answer goal 只有在目标 MathObject 和 LogicalStateKey 相同、且题目确实声明同一答案
状态时才能共享。不能只因 runtime value 相等而合并。

### Nankai Expected Result

```text
i_axis_from_relation
  canonical call: i_axis_from_relation
  logical state: (D, coordinate, Point)
  execution scope: problem
  presentation scope: i
  projections:
    - answer:i.axis_point
    - point:problem:D

ii1_axis -> alias i_axis_from_relation
ii2_axis -> alias i_axis_from_relation
```

第二问通过 object/state ref 读取 D，不产生第二个 writer。

## Finalizer Integration

Finalizer 是身份不变量的最后门禁，不负责第一次猜测或补数学路线。

### Required Ledgers

```text
writers_by_state_slot_id
writers_by_logical_state_key
writers_by_runtime_destination
latest_version_by_logical_state_and_scope
```

### Validation Order

1. 所有 produced handle 都能解析到 allocation decision。
2. `object_ref` 与 LogicalStateKey 一致。
3. 相同 StateSlot 的 writes 满足 create/transition 顺序。
4. visibility 重叠的相同 LogicalStateKey 不存在两个无关 create。
5. 相同 RuntimeDestinationKey 不存在两个未合并 writer。
6. downstream read 解析到其调用时间点之前的最新可见版本。
7. answer target 的 MathObjectId 与 provenance object identity 一致。
8. finalizer 再运行一次结果不变。

新增 typed errors：

```text
state.logical_duplicate_writer
state.runtime_destination_collision
state.transition_source_invisible
state.read_version_unresolved
state.object_slot_identity_mismatch
planner.state_projection_drift
```

`state.runtime_destination_collision` 属于 planner/compiler configuration error；它说明上游
allocation 或 placement 漏掉了冲突，不应交给 LLM retry。

## PlannerStateContext Changes

### MathObject

扩展：

```text
state_slot_ids[]
answer_refs[]
runtime_destinations[]
```

这些字段是索引 projection，不改变 `object_id` 权威性。

### StateSlot

扩展：

```text
logical_state_key
storage_scope_id
valid_scope_id
runtime_destination_key
latest_version_id
```

旧字段 `scope_id` 暂时作为 `storage_scope_id` 的兼容镜像。

### StateWriteVersion

扩展：

```text
version_id
source_call_id
computation_key
source_version_ids
free_symbol_refs
valid_scope_id
```

### Context Indexes

`PlannerState` 增加可派生索引：

```text
object_by_id
slots_by_object_id
slots_by_logical_state_key
versions_by_runtime_destination
latest_visible_version
```

持久化 snapshot 保存规范数据；索引可在 load 时重建，避免 JSON 重复成为第二真相源。

## Retry and Stable Graph

- stable call 必须指向 canonical call 和 verified StateVersionId。
- overlay 后重新执行 allocation、placement 和 finalizer。
- 如果 stable call 的 destination 与新 call 冲突，先尝试结构化复用；无法证明时取消冲突
  call 的 stable 状态，而不是覆盖 LLM 的新 candidate。
- repair root 按 StateVersion provenance 回溯，不按 step id substring 或 accepted prefix 猜测。
- 被 alias 消除的 call 不进入 stable graph、retry baseline 或学生 explanation source steps。

## Migration Away From String Logic

迁移遵循“先建立 typed API，再 shadow compare，最后删除旧逻辑”，不进行一次性重写。

### Category A: Handle Prefix Checks

逐步替换：

```text
handle.startswith("point:")
handle.startswith("answer:")
handle.split(":")
```

改为：

```text
MathObjectRegistry.resolve_handle(...)
CanonicalHandleRegistry.typed_ref(...)
QuestionGoalIndex.answer_destination(...)
```

### Category B: StateSlot String Construction

逐步删除各模块中的：

```text
f"{object_ref}.{state_kind}@{scope_id}"
slot_id.split("@")
```

统一使用：

```text
StateIdentityFactory.logical_key(...)
StateIdentityFactory.slot_id(...)
```

### Category C: Semantic-name Keywords

逐步替换：

```text
"parabola" in semantic_name
"minimum" in handle
"straightened" in ref
```

改为：

- runtime type；
- state kind；
- semantic lineage role；
- evidence tag；
- contract object-role projection。

### Category D: Runtime Path as Identity

runtime path 只作为 `RuntimeDestinationKey` 的验证字段。禁止：

- 从 path 反推 MathObject；
- 仅按 path 相同证明数学计算等价；
- 通过 path 尾部名称猜 return role。

### Category E: Method-id Dispatch

与身份、transition、closure 相关的 method-id 分支迁移到：

- Function/Macro identity policy；
- StateIdentityConstraintSpec；
- transition/closure spec；
- resolver registry id。

共享服务只按声明执行，不新增题目或 method 字面量。

## Iteration Plan

### Iteration 0: Typed Identity Foundation

新增 `state_identity.py`：

- `MathObjectId`；
- `LogicalStateKey`；
- `StateSlotId`；
- `StateVersionId`；
- `RuntimeDestinationKey`；
- `ComputationKey`；
- factory、JSON payload 和 backward parser。

在现有模型中增加可选 typed identity 字段，保留旧 string id。写 debug mismatch event，
暂不改变主行为。

验收：五题 fixture 中 typed key 与旧 id projection 全部一致；不新增 runtime 行为变化。

### Iteration 1: Allocation Authority

实现 `StateIdentityIndex + StateAllocationService`，接管 Functional return allocation。

- Context 状态和 in-flight return 使用同一个索引；
- ancestor-visible state 可复用；
- transition 使用 previous version；
- allocation decision 写入现有 reconciliation report 和 Context；
- legacy allocator 保留 shadow comparison 一轮。

首个验收场景：南开 D 在 `i / ii_1 / ii_2` 只产生一个 canonical writer。

### Iteration 2: Placement Uses Identity Decisions

- 用 `ComputationKey + StateEffectKey` 替换 placement 本地 tuple signature；
- return binding 从计算等价签名移除；
- answer alias 可转移；
- LCA 只决定 execution/valid scope，不重新创建 object state identity；
- downstream refs 和 projection map 全部指向 canonical call/version。

删除 placement 中已被 typed service 覆盖的 handle/object string helper。

### Iteration 3: Identity-aware Finalizer

- 增加 logical state 和 runtime destination 双重 writer ledger；
- 校验 read version、transition chain 和 answer object identity；
- collision 作为 configuration error；
- finalizer 保持幂等。

此阶段后，`duplicate_point_coordinate_fact` 不应再成为 planner 正常 retry issue；同类冲突
必须在 projection/finalizer 前被复用或结构化拒绝。

### Iteration 4: Context and Retry Authority

- Context snapshot 持久化 StateVersion；
- retry stable graph 保存 version id；
- overlay 后基于 Context 重新 reconcile；
- explanation 使用 canonical call + presentation placement；
- alias call 从学生步骤中彻底消失。

### Iteration 5: String Logic Removal

按模块迁移：

1. `functional_plan_reconciliation.py`；
2. `functional_call_placement.py`；
3. `canonical_draft_finalizer.py`；
4. `planner_state_context.py`；
5. `answer_goal_verifier.py`；
6. normalizer 与 recipe compiler；
7. legacy StepIntent compatibility。

每删除一类 fallback，都增加静态 `rg` 门禁或 focused test，避免重新引入。

## Test Plan

### Identity Unit Tests

- canonical handle、answer target 和 semantic ref 解析到同一 MathObjectId。
- `Point` 与 `PointList` 在同一对象下拥有不同 LogicalStateKey。
- ancestor state 对 child scope 可见。
- sibling-private state 不可见。
- Context JSON round-trip 保留 object/slot/version identity。

### Allocation Tests

- 第一问得到 D，第二问重复纯调用复用已有版本。
- 只有 `ii_1` 与 `ii_2` 重复调用时提升到 `ii` 并共享。
- 同名 Point 但不同 MathObjectId 不合并。
- 同一对象使用不同 source StateVersion 不合并。
- open Point 经参数代入成为 closed Point 时记录 transition。
- 两个 create 写同一可见逻辑状态时提前失败。
- 不可见 sibling 输入导致调用拆分，不错误提升到父 scope。

### Placement Tests

- answer-bound producer 与 object-bound duplicate 合并并转移 answer projection。
- call id、strategy/reason 和 declared scope 不影响数学等价性。
- result form 冲突不静默合并。
- explicit answer destinations 不同且目标对象不同不得合并。
- canonical graph 拓扑顺序保持 producer before consumer。

### Finalizer Tests

- 不同 StateSlotId 写入同一 RuntimeDestinationKey 时被捕获。
- 合法 transition chain 通过。
- previous version 不可见时失败。
- downstream read 解析到调用时间点之前的最新版本。
- finalizer 连续运行两次 payload 和 issue 完全一致。

### Retry and Regression

- stable graph 不保存 alias call。
- retry overlay 后重复调用再次被合并。
- LLM 正确修复不能被旧 stable writer 覆盖。
- 南开、河西、西青、和平、和平二模 authored FunctionalPlan fixture 全部通过。
- 五题真实 opt-in 不再出现晚期 duplicate runtime error。

建议命令：

```bash
cd server
uv run pytest \
  tests/solver/test_planner_state_context.py \
  tests/solver/test_strategy_planner_functional_plan.py \
  tests/solver/test_canonical_draft_finalizer.py \
  tests/solver/test_strategy_planner_retry_state.py -q
uv run pytest tests/solver -q
git diff --check
```

## Observability

不新增大量独立 debug 文件。以下内容进入现有
`functional-reconciliation-report.json` 和 `planner-state-context.json`：

```text
state_identity_decisions[]
  call_id
  return_name
  logical_state_key
  selected_slot_id
  selected_version_id
  action
  reason
  runtime_destination

identity_mismatches[]
  legacy_slot_id
  typed_slot_id
  legacy_merge_decision
  typed_merge_decision
```

核心指标：

- `late_runtime_destination_collision_count`，目标为 0；
- `legacy_vs_typed_identity_mismatch_count`，完成迁移后为 0；
- `reused_visible_state_count`；
- `state_transition_count`；
- `identity_conflict_retry_count`；
- 因字符串 fallback 产生的 resolution 次数。

## Capability Authoring Requirements

新增或修改 capability 必须声明：

- 每个 return 的 identity policy；
- identity arg；
- state kind 和 runtime type；
- create / transition / value；
- transition 的 previous-state arg；
- 是否纯函数、是否 shareable；
- semantic roles、object roles 和 evidence tags；
- 同一对象多版本时的 closure/refinement policy；
- runtime destination 是否支持 scoped version。

验收标准：新增同类 capability 只需声明这些 contract，不修改
`StateAllocationService`、placement 或 finalizer 的 dispatch。

## Rollout and Safety

每一轮遵循：

```text
typed model
  -> shadow projection
  -> mismatch report
  -> focused fixture gate
  -> typed path becomes authoritative
  -> remove legacy string fallback
```

不得在同一个提交中同时：

- 改身份模型；
- 删除全部旧 fallback；
- 改数学 method；
- 更新 expected answer。

真实 DeepSeek 样本只用于暴露概率输出，不作为身份规则的题目特定输入。每个修复必须有
无题名、无固定点名、无答案值的 synthetic test。

## Exit Criteria

- MathObjectId 是 object identity 的唯一来源。
- StateSlot allocation 不再从 handle spelling 推断对象。
- placement 不再把 answer binding 或 scope-qualified slot string 当作计算身份。
- finalizer 同时验证 logical state 与 runtime destination。
- Context、retry、runtime provenance 和 explanation 使用同一 StateVersion chain。
- `duplicate_point_coordinate_fact` 等晚期身份冲突在 planner/runtime 正常链路中归零。
- 相关模块中的 handle prefix、slot string parsing 和 semantic-name keyword fallback 已有明确
  删除清单，新增代码不能继续扩散。
