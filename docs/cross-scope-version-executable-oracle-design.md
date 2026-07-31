# Cross-Scope / StateVersion Executable Oracle 与生成式门禁设计

## Summary

本文档定义 Functional Planner 的跨 scope / StateVersion 可执行参考模型与生成式测试门禁。

当前五题真实 DeepSeek 样本会随机产生不同的调用顺序、scope 分布、alias、隐藏依赖、
状态 refinement 和 retry overlay。它们事实上承担了调用图 fuzz tester 的职责，并持续
发现 allocation、placement、finalizer、retry 和 consumer 在同一语义不变量上的不同
实现缺口。

这类基础错误不应继续依赖真实 LLM 样本发现。目标是建立一套独立于生产实现的、
可穷举的小型 reference model：

```text
CrossScopeVersionScenario
  -> ReferenceScopeVersionModel
  -> ExpectedScopeVersionOutcome

CrossScopeVersionScenario
  -> Production B1-B5b adapters
  -> ActualScopeVersionOutcome

Expected <-> Actual
```

该工作在总路线图中命名为 **C0.5 Scope/Version Model Gate**，插入位置固定为：

```text
B5a typed producer authority
  -> C0 logical graph shadow
  -> B5b typed consumer authority
  -> C0.5 executable oracle and generated gate
  -> C1 transactional call execution
```

C0.5 不增加新的 production authority，不执行数学 method，也不修改 FunctionalPlan
wire schema。它验证 B1-B5b 和 C0 已经声明的 scope/version 语义是否在所有受控图形下
一致成立，为 C1 增加真正的逐 call 状态演进前提供 hard gate。

## Implementation Status

截至 2026-07-31，C0.5 为 `COMPLETE`。reference model、production stage
adapters 和生成式门禁已经满足退出条件，C1 hard prerequisite 已解除：

- `ReferenceScopeVersionModel` 仅依赖 Python 标准库，并由静态测试禁止导入
  production allocation/read authority；
- `B1AllocationAdapter`、`B2PlacementAdapter`、`B3FinalizationAdapter`、
  `B4RetryCheckpointAdapter`、`B5bStateReadAdapter` 和
  `C0LogicalGraphAdapter` 分阶段比较，不以最终 replay 状态代替中间门禁；
- 默认生成 `8,000` 个 topology-balanced bounded matrix scenario、`2,000`
  个固定 seed expanded graph、`128` 个跨阶段 semantic handoff scenario 和
  `5` 个 authority regression scenario，总计 `10,133` 个确定性场景；
- bounded cohort 对 `root/parent_child/siblings/branched` 各采样 `2,000`
  场景，并强制每种 topology 都覆盖
  `none/exact/latest/identity_only/call_result`，不再用笛卡尔积前缀截断；
- 另有 `64` 个 dead-writer/liveness scenario；它们先调用真实 B1 allocation，
  再从实际 previous/source version 构图，验证 provisional writer 不会仅因未证明的
  transition predecessor 边进入存活图；
- expanded graph 覆盖 `6-12` 个 call、多对象、跨 branch、长度 `3+` transition
  chain、wire reorder 和 retry checkpoint；
- handoff graph 覆盖 identity-only/bootstrap object、sibling producer、object/answer
  projection、B1 provisional allocation、B2 LCA publication、exact StateVersion
  reprojection，以及 B3/B5b/C0 对最终版本的共同解释；
- 历史匿名 corpus 已登记 sibling exact visibility、parent/child transition、answer projection、
  hidden dependency、destination chain、provisional retry、checkpoint drift、
  stale CallResultRef、exact role version、child-owned target、sibling-isolated
  state 和 checkpoint wire reorder 等缺陷；
- reference truth table、metamorphic、production mutation、scenario replay 和 reducer
  测试均已建立；
- C0.5 v6 定向测试为 `33 passed`，全量 solver 为
  `1543 passed, 17 skipped`；
- comparator 按 authority reachability fail closed：B1/B2 allocation 与 placement
  始终比较，B3 issue 双向比较；仅当 B3 接受 logical graph 后，才继续比较
  B4 checkpoint、B5b state read 和 C0 graph edge/order；
- C0 dependent-blocking lifecycle 是独立探针，即使 B3 同时拒绝 logical graph
  也必须比较，不受上述 stop boundary影响；
- `parent_child` cohort 的 `2,000` 个场景中，至少 `1,800` 个同时包含
  `problem` 与 `ii` 调用，并要求至少 `200` 个场景具有显式跨父子 scope
  dependency；
- 主门禁当前确定性注入 `276` 个 runtime root failure，其中 `68` 个形成
  nonempty dependent-blocking 集合，`17` 个同时具有 B3 issue；全部 `68`
  个场景均使用 production `FunctionalTransactionShadowObserver` 精确比较
  `blocked_by_dependency`，门禁下限分别为 `60` 和 `15`；
- eliminated call 由 production liveness analyzer 独立校验；B1 仍只负责
  provisional allocation，不被迫提前承担生命周期语义；
- B3 issue 采用 finalizer-local category 双向比较；expected issue 缺失或
  production issue 被静默删除都会使门禁失败；
- semantic latest 以 scope specificity 和依赖偏序中的唯一 maximal writer 为准，
  跨 sibling 发布必须证明完整 source-version chain 可安全提升。

以上门禁只证明 C1 可以开始实现，不改变现有 production replay authority。

生成失败可通过报告中的 `scenario_id` 重放：

```bash
cd server
CROSS_SCOPE_SCENARIO_ID=<scenario-id> \
  uv run pytest tests/solver/test_cross_scope_version_generated_gate.py -q
```

Reference model 仍只存在于 `server/tests/solver/support`，不进入 production 包、
PlannerStateContext、prompt、retry 或 runtime execution。

### 2026-07-30 Iteration

最近真实批次暴露了两个原 10,000 场景矩阵没有覆盖的阶段交接问题：

1. 一个 sibling scope 先为全题 MathObject 物化状态，另一个 sibling 随后通过
   `SemanticRef` 使用它。B1 的 provisional version 可以位于 producer scope，但 B2
   必须将 return 发布到 LCA，并把 consumer 重投影到最终精确 `StateVersionId`。
2. 同一对象存在旧 provisional writer 和独立 final writer 时，旧 writer 不能仅因为
   allocation 暂时生成的 predecessor 边而保持存活；只有被真实读取或被证明为合法
   transition predecessor 时才可进入最终图。

C0.5 v2 因此新增 `ModelStateRead`（`exact/latest/identity_only/call_result`）、
semantic handoff generator 和独立 liveness adapter。Production 修复也先由匿名
scenario 复现，再落到 placement 与 liveness authority，没有引入题名、点名或
capability 链特判。

C0.5 v3 进一步修复了生成与比较门禁本身：

- bounded 生成器改为 topology 分层采样，避免前 `8,000` 条全部落在 root；
- read mode 进入主矩阵和 coverage assertion，不再只由少量 handoff 补充；
- B1-B5b/C0 adapter 改为精确集合和字段比较，缺失 authority 输出立即失败；
- Functional placement 按 typed dependency 拓扑投影，consumer-before-producer
  不再受 scope 序列化顺序影响；
- semantic latest hidden edge 添加 cycle preflight，唯一候选也不得制造反向依赖；
- historical corpus 记录并断言实际 dimensions，名称不能再指向 root 塌缩场景。

C0.5 v7 继续将真实批次暴露的 authority handoff 缺口匿名化后加入 corpus：

- ancestor-declared call 首次物化 child-owned target 时，execution/return scope
  必须服从 typed object origin，不能让 identity-only runtime binding 漂移；
- sibling 中同一 LogicalStateKey 的独立状态必须保持 `isolated` storage scope，
  parent consumer 不能把它扩散为共同 writer；
- retry 恢复的 committed return scope 是 B4 已验证事实；即使新 wire scope 顺序
  改变，SemanticRef consumer 也必须重新绑定到 checkpoint 对应的精确
  StateVersion，而不能退化为 identity-only object read。
- ProblemIR 初始 ParameterValue 是 ordinal-0 typed state；下游求值必须按精确
  StateVersion 读取，不能要求它先由 runtime call 再写一次。
- 跨分支发布的派生状态只携带 consumer 明确读取的 typed version；其生产过程的
  私有传递来源仍属于 provenance，不得重新展开为 sibling consumer 的 runtime
  read。

## Problem

当前系统已经分别建立：

- B1 `StateAllocationService`；
- B2 typed canonicalization 和 placement；
- B3 logical/runtime destination finalizer；
- B4 retry version checkpoint；
- B5a typed identity producer authority；
- B5b typed Context/runtime consumer；
- C0 `LogicalFunctionalGraph` 和 Working Context shadow。

但“同一个 MathObject 跨 scope 如何读写”仍由多个阶段共同实现。一个阶段的局部测试
通过，不代表后续阶段不会重新破坏同一不变量。

典型重复症状包括：

```text
child scope 已产生 closed version，consumer 仍读取 parent open version
两个 sibling 的等价 call 被合并，但 canonical owner 留在不可见 sibling
open -> closed 本应 transition，却因隐藏 predecessor 缺失被判 isolated
retry checkpoint 的 call payload 与 ComputationKey 来自不同规范化阶段
typed resolver 与 compiler 使用同一错误状态，因此 shadow mismatch 仍为 0
```

这些问题有三个共同原因：

1. 真实 LLM 才覆盖非标准调用图；
2. 离线 fixture 主要覆盖 authored happy path；
3. 现有 shadow 多数比较两套生产投影，缺少独立语义 oracle。

## Goals

### Required

- 使用一个不依赖生产 allocation/placement/read 实现的参考状态机定义预期行为。
- 有界穷举 scope tree、StateVersion DAG、call order、alias、hidden dependency 和 retry
  组合。
- 对 B1-B5b 每个 authority 阶段分别比较，而不是只比较最终 replay 是否成功。
- 失败时输出可直接进入 synthetic regression 的最小 scenario。
- 每次真实 LLM 暴露 scope/version 缺陷时，必须先增加匿名最小 scenario，再修生产代码。
- C1 开始前，生成式门禁必须进入默认离线回归。

### Non-goals

- 不验证具体数学值或中学解题路线。
- 不生成自然语言 prompt，也不调用 LLM。
- 不通过 expected answer 修复 FunctionalPlan。
- 不模拟 SymPy、FunctionSpec 或 MacroSpec 的数学行为。
- 不取代五题 authored fixture、真实 DeepSeek smoke 或 held-out 测试。
- 不让 reference model 调用生产版 `StateAllocationService`、
  `ScopeVisibilityResolver`、`FunctionalStateReadIndex` 或 placement helper。

## Stage Placement

### Why After B5b

生成式门禁需要观察完整 typed consumer 决策，包括：

- exact StateVersion read；
- latest-visible selection；
- PathTransformation role version；
- answer version/evidence lookup；
- runtime path projection。

这些接口在 B5b 前尚未收口，因此更早建立 oracle 只能覆盖 producer 侧，无法验证一次
完整的跨 scope 状态生命周期。

### Why Before C1

C1 会把当前整图 replay 改为逐 call commit：

```text
ready call
  -> read latest verified version
  -> execute
  -> allocate and commit next version
  -> unblock downstream
```

如果 scope/version 规则仍靠真实样本发现，C1 会把同一缺陷扩展到事件顺序、partial
commit 和失败隔离。C0.5 必须先证明静态 authority 和 typed consumer 对同一参考模型
一致，再允许 C1 增加新的执行轴。

### Why Not Part of Track A

Track A 的职责是五题 FunctionalPlan parity。C0.5 验证的是 planner 的通用状态机，
其 scenario 不包含题名、具体点名、答案值或固定 capability 链，因此属于架构迁移门禁，
不是五题 parity 扩展。

## Reference Model

Reference model 放在测试支持模块，不进入 production runtime：

```text
server/tests/solver/support/cross_scope_version_oracle.py
```

它只能依赖 Python 标准库和自身 dataclass。生产 adapter 可以导入 production model，
reference model 不能反向导入 production service。

### Scenario

```python
@dataclass(frozen=True)
class ModelScope:
    scope_id: str
    parent_scope_id: str | None


@dataclass(frozen=True)
class ModelObject:
    object_id: str
    kind: str
    origin_scope_id: str


@dataclass(frozen=True)
class ModelStateKey:
    object_id: str
    state_kind: str
    runtime_type: str


@dataclass(frozen=True)
class ModelCall:
    call_id: str
    declared_scope_id: str
    capability_key: str
    input_version_ids: tuple[str, ...]
    input_condition_ids: tuple[str, ...]
    output_state_key: ModelStateKey | None
    requested_write_mode: str
    free_symbols: tuple[str, ...]
    is_pure: bool
    is_shareable: bool
    answer_scope_ids: tuple[str, ...]
    explicit_consumer_scope_ids: tuple[str, ...]


@dataclass(frozen=True)
class CrossScopeVersionScenario:
    scopes: tuple[ModelScope, ...]
    objects: tuple[ModelObject, ...]
    initial_versions: tuple["ModelVersion", ...]
    calls: tuple[ModelCall, ...]
    wire_order: tuple[str, ...]
    dependency_edges: tuple["ModelDependency", ...]
    retry_checkpoint: "ModelRetryCheckpoint | None"
```

Scenario 不包含：

- production handle；
- StateSlot 字符串；
- runtime path；
- 题目点名；
- strategy/reason；
- 具体数学值。

### Expected Outcome

```python
@dataclass(frozen=True)
class ExpectedCallDecision:
    call_id: str
    canonical_call_id: str
    allocation_action: str
    execution_scope_id: str
    return_scope_id: str | None
    selected_version_id: str | None
    previous_version_id: str | None
    source_version_ids: tuple[str, ...]
    visible_read_version_ids: tuple[str, ...]
    issue_code: str | None


@dataclass(frozen=True)
class ExpectedScopeVersionOutcome:
    canonical_order: tuple[str, ...]
    call_decisions: tuple[ExpectedCallDecision, ...]
    final_visible_versions: tuple[tuple[str, str, str], ...]
    committed_version_ids: tuple[str, ...]
    blocked_call_ids: tuple[str, ...]
```

Reference version id 使用 scenario-local 稳定 token，例如：

```text
M.coordinate@ii#0
M.coordinate@ii_1#1
```

它只用于 oracle 内部，不与 production `StateVersionId.to_payload()` 做字符串等价。
Production adapter 负责将 typed payload 规范化为同一比较结构。

## Reference Rules

### 1. Scope Visibility

```text
state.valid_scope is ancestor-or-self of consumer scope
```

- parent state 对 descendants 可见；
- sibling-private state 不可见；
- child state 不向 parent 自动泄漏；
- MathObject `origin_scope` 不等于 StateVersion `valid_scope`。

### 2. Latest Visible

对同一 logical state：

1. 过滤不可见版本；
2. 优先 consumer 最近的可见 scope；
3. 同一 slot 内选择最大 ordinal；
4. 多个 slot 候选只在 version ancestry 可比较时选择唯一 maximal；
5. 多个不可比较 maximal version 同时可见时产生 ambiguity，不按插入顺序选择。

### 3. Allocation

- `reuse`：pure/shareable，计算键、输入 version/condition 和 state effect 完全一致。
- `create`：此前不存在可见或不可见的同 logical state。
- `transition`：输出与 predecessor 为同 logical state，并显式消费该 predecessor 或其
  合法 dependency refinement，且自由符号不增加。
- `isolated`：同 logical state 只存在于不可见 sibling，当前 call 可在独立 destination
  建立状态。
- `conflict`：可见状态已存在，新写既不 reuse，也不形成可证明 transition。
- `call_local_value`：无 MathObject 的 value-only return。

### 4. Sibling Branches

对于父状态：

```text
M@ii#0
├── M@ii_1#1
└── M@ii_2#1
```

两个 child transition 可以独立存在，并分别以 parent version 为 predecessor。
`ii_2` 不得自动读取 `ii_1` 的版本。

只有存在显式 dependency，且 producer closure 可安全放置到共同 ancestor 时，才允许
跨 sibling 共享。

### 5. Canonicalization and Placement

- call identity 只使用 capability、exact input versions/conditions 和 state effect；
- call id、wire order、strategy/reason 和 answer/object projection 不进入身份键；
- 等价 sibling call 可合并时，canonical execution/return scope 必须对所有 consumer
  可见；
- 输入无法在 LCA 可见时必须拆分，不能保留不可见 alias；
- pinned answer/committed call 不得被非 pinned call 改写。

### 6. Finalization

- create/isolated 是 writer；
- transition 是具有唯一 direct predecessor 的 writer；
- reuse 只是 read/alias，不形成第二 writer；
- exact dependency 必须指向已知且拓扑更早的 version；
- 同一 runtime destination 的多个写必须形成完整 transition chain；
- 不同 logical state 不得写同一 physical destination。

### 7. Retry

- 只有 goal-committed canonical call 获得 hard lock；
- checkpoint payload、ComputationKey 和 version chain 必须描述同一 normalized call；
- provisional version可进入结果记忆，但不恢复 producer；
- 修改 committed dependency version 必须产生 drift；
- 删除 provisional branch 后不得由 call id 或字符串 destination 恢复。

## Oracle Self-validation

Reference model 独立于 production，并不表示它天然正确。它自身使用两层门禁：

1. 手写 truth table 固定 parent/child/sibling、create/transition/reuse、exact/latest
   read 和 retry restore 的基础语义；
2. metamorphic tests 验证不应改变语义的场景变换。

必须覆盖的 metamorphic invariants：

- 只重命名 call、scope 和 object token，不改变 expected outcome；
- 在依赖 DAG 不变时调整 wire order，不改变 canonical order 和 version chain；
- 添加无 answer consumer 的独立 dead branch，不改变原有分支；
- object projection 改为 object+answer projection，不改变 computation identity；
- exact read 之后新增更晚 version，不得把该 read 升级；
- 对 scope tree 做同构重命名，visibility 和 placement 决策保持一致。

Production adapter 还必须有 mutation tests：故意交换 predecessor、选择 sibling latest、
遗漏 hidden dependency 或恢复 provisional call 时，generated gate 必须在对应 authority
阶段失败。这样既检查 production，也检查 oracle 是否真正具有区分能力。

## Generated Scenario Space

生成器使用标准库 `itertools` 和固定 seed，不在 C0.5 初版引入 Hypothesis 依赖。

### Bounded Exhaustive Dimensions

```text
scope topology:
  problem
  problem -> ii
  problem -> ii -> ii_1, ii_2
  problem -> i, ii -> ii_1, ii_2

object origin:
  problem | parent | child

state location:
  parent | one child | both siblings

write mode:
  create | transition | value

call relationship:
  independent | exact duplicate | dependency refinement | conflicting write

dependency kind:
  call result | state version | condition | hidden semantic role

wire order:
  producer-first | consumer-first | sibling interleaved

projection:
  object | answer | object+answer | call-local

retry:
  none | committed restore | provisional replacement | dependency version drift
```

初始 exhaustive gate 限制：

- scope depth `<= 3`；
- calls `<= 5`；
- logical states `<= 3`；
- versions per logical state `<= 4`。

在此边界内生成至少 `10,000` 个确定性 scenario。CI 输出 scenario 数量和维度覆盖，
不能只输出 pytest case 数量。

### Seeded Expansion

有界穷举之外，使用固定 seed 生成更长图：

- calls `6-12`；
- 多个 MathObject；
- 多 return；
- alias chain；
- transition chain 长度 `3+`；
- wire failure 后 checkpoint restore；
- 一条失败 branch 与一条独立成功 branch。

Seed 列表进入版本控制。CI 不使用时间 seed，避免不可重放失败。

### Mutation Corpus

每个真实失败先缩减为匿名 scenario，例如：

```text
parent open Point
child-1 closed transition
consumer in child-1
latest-visible incorrectly selects parent
```

Corpus 保存到：

```text
server/tests/solver/fixtures/cross_scope_version_failures/
```

fixture 只保存模型结构和 expected issue，不保存题目文本、点名、答案值或完整 LLM
response。

## Production Adapters

每个 adapter 只负责运行一个 production authority 并规范化结果：

```text
B1AllocationAdapter
B2PlacementAdapter
B3FinalizationAdapter
B4RetryCheckpointAdapter
B5bStateReadAdapter
C0LogicalGraphAdapter
```

比较按阶段进行：

```text
reference allocation   <-> B1
reference placement    <-> B2
reference ledger       <-> B3
reference restore      <-> B4
reference read         <-> B5b
reference graph order  <-> C0
```

不能只比较最终结果。否则 allocation 选错、consumer 也跟着选错时仍可能整体自洽。

## Invariant Gates

每个 scenario 必须验证：

### Identity

- 同名不同 MathObject 不合并；
- 同 MathObject 的不同 runtime type 不共享 LogicalStateKey；
- answer alias 不创建第二个 MathObject 或 writer。

### Scope

- ancestor visible；
- sibling private；
- child 不向 parent 泄漏；
- canonical producer 对所有 consumer 可见；
- unsafe hoist 必须拆分或失败。

### Version

- exact read不升级到 latest；
- latest-visible选择唯一 maximal version；
- sibling transitions共享 parent predecessor而非互相串接；
- transition chain 连续；
- 未来、悬空和不可见 version 失败。

### Graph

- consumer-before-producer wire顺序可被 typed DAG重排；
- hidden dependency、previous/source version 均形成 graph edge；
- alias 不形成执行节点；
- failed root 不提交 write，其 dependents blocked，独立分支继续。

### Retry

- committed graph 恢复相同计算与 version chain；
- provisional graph 可替换；
- checkpoint normalized payload 与 identity key 一致；
- repair cone 沿 version producer/consumer 边闭合。

## Failure Reporting and Reduction

失败信息必须包含：

```text
scenario_id
seed
dimensions
minimal scope tree
calls and version edges
expected decision
actual production decision
first mismatching authority stage
```

生成器提供确定性 reducer，按以下顺序缩减：

1. 删除无关 call；
2. 删除无关 object/state；
3. 缩短 scope tree；
4. 删除非必要 projection；
5. 简化 retry checkpoint。

reducer 只用于生成可读诊断；正式 regression fixture 由开发者确认后提交。

## Test Layout

```text
server/tests/solver/support/cross_scope_version_oracle.py
server/tests/solver/support/cross_scope_version_generator.py
server/tests/solver/test_cross_scope_version_oracle.py
server/tests/solver/test_cross_scope_version_generated_gate.py
server/tests/solver/fixtures/cross_scope_version_failures/*.json
```

定向测试覆盖 reference model 自身。Generated gate 通过 production adapters 比较 B1-B5b
与 C0。

建议命令：

```bash
cd server
uv run pytest \
  tests/solver/test_cross_scope_version_oracle.py \
  tests/solver/test_cross_scope_version_generated_gate.py -q
```

## Implementation Iterations

### C0.5-A: Reference Semantics

- 定义 scenario/outcome；
- 实现独立 scope visibility、latest-visible、allocation 和 transition reference rules；
- 用手写 truth table 测试 reference model；
- 禁止导入 production runtime identity service。

### C0.5-B: Production Stage Adapters

- 依次接入 B1、B2、B3、B5b；
- 每层独立比较；
- 接入 B4 checkpoint 和 C0 logical graph；
- 任何缺 typed sidecar 均按 mismatch 暴露，不在 adapter 补全。

### C0.5-C: Bounded Generation

- 实现 bounded exhaustive matrix；
- 加入固定 seed expansion；
- 输出 scenario/dimension coverage；
- 控制定向门禁在本地和 CI 可接受时间内完成。

### C0.5-D: Failure Corpus and Policy

- 将已知跨 scope/version 历史缺陷转成匿名最小 fixture；
- 在可靠性工程文档中固定“LLM failure 先最小化、后修代码”的流程；
- generated gate 进入 `tests/solver` 默认回归。

## Exit Criteria

C0.5 标记 `COMPLETE` 必须同时满足：

- reference model truth table全部通过；
- metamorphic 和 adapter mutation tests 全部通过；
- 至少 `10,000` 个确定性 generated scenario 零 mismatch；
- B1/B2/B3/B4/B5b/C0 均有独立 adapter 断言；
- adapter 断言遵循 authoritative stop boundary：B3 拒绝后不解释 B4/B5b 或
  C0 graph edge/order，但 C0 dependent blocking 仍独立审计；
- 历史跨 scope/version failure corpus 全部通过；
- generated failure 可由 scenario id 和 seed 稳定重放；
- 新增 scope/version production 修复必须先增加 synthetic scenario；
- 五份 authored Functional fixture和全量 solver通过；
- `git diff --check` 通过。

只有 C0.5 完成后，C1 才能切入逐 call execution shadow。真实 DeepSeek smoke 留在
C0.5 离线门禁之后运行，用于验证模型行为和 capability上下文，不再作为发现基础
scope/version错误的主要工具。

以上退出条件已于 2026-07-31 满足。后续任何 scope/version production 修复必须先增加
或确认一个匿名 scenario/corpus regression，再运行该门禁；不得用减少生成数量规避性能
或正确性失败。

## Assumptions

- B1-B5b 的 typed models和 C0 logical graph继续作为 production实现基础。
- Reference model是测试 oracle，不成为第六套 production authority。
- 初版生成器不新增第三方依赖；未来若引入 property-testing库，仍必须保留固定 seed和
  JSON corpus重放。
- Runtime path不参与 reference identity，只在 B3 destination adapter中验证。
- FunctionalPlan wire schema继续为 `functional_plan/v1`。
- C0.5 不执行真实数学 method；C1 才建立隔离 RuntimeContext并逐 call执行。
