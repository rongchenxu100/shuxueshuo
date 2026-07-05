# LLM Context Model Design

## Summary

本文档沉淀一条通用设计原则：

> 凡是让 LLM 连续操作一个复杂对象，都应该有显式 Context Model。LLM 只负责提出或修改语义意图，系统负责维护上下文一致性、版本演进、验证和投影。

在 solver planner 中，这个模型表现为 `PlannerStateContext`；在题目解析、讲解生成、图形、动画等链路中，也应分别存在对应的 Context Model。Context 不是 prompt，也不是 runtime object；它是工作流节点的语义事实源。

后续实现的唯一目标是提高 LLM 稳定性、降低幻觉，并把更多机械职责交给代码。基于这个目标，`PlannerStateContext` 应成为 solver planner 的主线设计；未完全实现的 Capability Pack 和函数式 Method/Recipe 不再作为并行重构线推进，而应分别成为 Context 的能力声明层和确定性状态转移层。

## Core Ideas

### Context 是语义工作台

Context 对象描述某个 LLM 工作流节点当前“知道什么、做到哪里、哪里有问题、下一步该修什么”。

例如 `PlannerStateContext` 应包含：

- 题目对象：点、线、函数、参数、线段、角、路径。
- 题面条件：点在线上、长度关系、角度关系、参数范围、最值条件。
- 推导状态：点坐标、函数表达式、参数值、路径转化、最小值表达式。
- scope 可见性：全题、大问、小问之间哪些状态可读。
- step timeline：LLM 输出的步骤、系统解析后的步骤、稳定前缀、失败位置。
- diagnostics：semantic / validation / normalization / candidate / runtime / answer 层问题。
- alias/projection：semantic ref、canonical handle、runtime path 之间的映射。

LLM 输出 JSON 不是事实源，而是对 Context 的一次候选更新。系统通过 parser / validator / normalizer / reconciler 把候选更新合并成新的 Context version。

### PlannerStateContext.state Schema 草案

Phase 1 需要先把 `PlannerStateContext.state` 定义成可序列化、可 diff、可投影的权威快照。推荐把 context metadata 和 semantic state 分开：`manifest.json` 保存版本元信息，`state.json` 保存当前语义事实源。

顶层结构草案：

```python
@dataclass(frozen=True)
class PlannerStateContext:
    manifest: ContextManifest
    state: PlannerState


@dataclass(frozen=True)
class ContextManifest:
    context_id: str
    context_type: Literal["planner"]
    schema_version: str
    parent_context_id: str | None
    dependency_context_ids: tuple[str, ...]
    problem_id: str
    family_id: str
    family_spec_hash: str
    capability_pack_hash: str
    prompt_template_version: str | None
    model: str | None


@dataclass(frozen=True)
class PlannerState:
    problem_ir: dict[str, Any]
    expanded_family_spec: dict[str, Any]
    scope_graph: ScopeGraph
    math_objects: tuple[MathObject, ...]
    conditions: tuple[Condition, ...]
    state_slots: tuple[StateSlot, ...]
    alias_index: AliasIndex
    step_timeline: StepTimeline
    stable_prefix: tuple[StableStep, ...]
    issues: tuple[PlannerRetryIssue, ...]
    capability_contracts: tuple[CapabilityContractSnapshot, ...]
```

核心子结构草案：

```python
@dataclass(frozen=True)
class MathObject:
    object_id: str              # point:A, line:BD, function:parabola
    kind: str                   # point / line / segment / function / symbol / ...
    scope_id: str
    canonical_handle: str | None
    semantic_refs: tuple[str, ...]
    source: Literal["problem", "derived", "answer", "temporary"]


@dataclass(frozen=True)
class Condition:
    condition_id: str
    kind: str                   # point_on_curve / angle_sum / midpoint / ...
    scope_id: str
    canonical_handle: str | None
    subject_ids: tuple[str, ...]
    value_type: str | None
    source_step_id: str | None
    valid_scope: str | None


@dataclass(frozen=True)
class StateSlot:
    slot_id: str                # function:parabola.expression@ii
    object_ref: str | None      # MathObject id; StateSlot identity should not depend on handle
    state_kind: str             # coordinate / expression / coefficients / minimum_value / ...
    scope_id: str
    runtime_type: str           # Point / Parabola / Equation / Expression / ...
    canonical_handle: str | None  # projection handle, not slot identity
    aliases: tuple[str, ...]
    produced_by: str | None     # StepState id or external source id
    valid_scope: str | None
    runtime_path: str | None
    status: Literal["given", "planned", "validated", "runtime_verified", "invalid"]


@dataclass(frozen=True)
class StepState:
    step_id: str
    scope_id: str
    raw_payload: dict[str, Any]
    normalized_payload: dict[str, Any] | None
    slot_reads: tuple[str, ...]       # StateSlot ids; read a typed value
    condition_reads: tuple[str, ...]  # Condition ids; require a known fact/relation
    slot_writes: tuple[str, ...]      # StateSlot ids; produce/update a typed value
    condition_writes: tuple[str, ...] # Condition ids; produce/update a fact/relation
    capability_id: str | None
    status: Literal["raw", "semantic_resolved", "validated", "normalized", "runtime_verified", "failed"]


@dataclass(frozen=True)
class StepTimeline:
    steps: tuple[StepState, ...]
    repair_suffix_start: str | None


@dataclass(frozen=True)
class StableStep:
    step_id: str
    normalized_payload: dict[str, Any]
    verified_slot_writes: tuple[str, ...]
    verified_condition_writes: tuple[str, ...]


@dataclass(frozen=True)
class AliasIndex:
    by_handle: dict[str, str]   # canonical/legacy handle -> StateSlot/Condition/MathObject id
    by_semantic_ref: dict[str, tuple[str, ...]]
```

Phase 1 可以把 `problem_ir` 和 `expanded_family_spec` 作为 JSON snapshot 存进 `state.json`，保证 context 自包含、可复现。后续如果存储成本变高，可以在 `manifest` 中记录 hash 和外部 artifact path，但读取时仍应把它们投影成同一个 `PlannerState`。

`StateSlot` 的设计必须为后续 FunctionSpec / MacroSpec 预留 functional interface。它的身份应来自语义状态，而不是 canonical handle：

```text
StateSlot identity = object_ref + state_kind + scope_id + runtime_type
```

其中：

- `object_ref` 指向 `MathObject`，例如点 A、函数 parabola、线 BD。
- `state_kind` 表示该对象的哪个状态，例如 coordinate、expression、coefficients、minimum_value。
- `runtime_type` 表示执行层值类型，例如 Point、Parabola、Equation、Expression。
- `canonical_handle`、`aliases`、`runtime_path` 都是 projection / compatibility metadata，不是 StateSlot 的身份。

这样 Phase 1 建出来的 State/Alias Graph 可以直接被后续 function/macro 读写：

```text
FunctionSpec(quadratic_from_constraints)
  slot_reads:      StateSlot(Point(A).coordinate), StateSlot(Point(B).coordinate)
  condition_reads: Condition(Function(parabola).coefficient_relation)?
  slot_writes:     StateSlot(Function(parabola).expression)
```

避免 Phase 4 再从 `handle -> path -> value` 反推语义 slot。

`StepState` 中必须区分 slot 与 condition：

- `slot_reads / slot_writes` 表示读取或写入一个有 runtime value 的状态，例如点坐标、函数表达式、参数值、最小值表达式。
- `condition_reads / condition_writes` 表示读取或写入一个事实/关系的存在性，例如中点关系、点在线上、角和关系、系数关系。

这为后续 FunctionSpec 提供稳定接口，避免把“读一个值”和“满足一个前提条件”混在同一个 `reads[]` / `writes[]` 字段里。

### Context、Projection、Artifact 分离

需要严格区分三类东西：

- **Context semantic state**：权威语义状态，例如对象、条件、状态槽、依赖、问题、稳定前缀。
- **Projection**：从 Context 生成的结构化视图，例如 prompt payload、StepIntent draft、retry state、semantic read catalog、runtime binding hints。
- **Artifact**：某次实际运行留下的文件，例如 rendered prompt、raw LLM response、validation report、debug JSON、solved result。

Prompt 是 Context 的 projection artifact，不是 Context 本体。保存 prompt 是为了复现“模型当时看到了什么”，但不能把 prompt 当事实源。

## Context Graph

整个任务链条不是单线，而是一个 Context Graph。

```text
ProblemExtractionContext
        |
        v
PlannerStateContext
        |
        v
LessonExplanationContext
      /       \
     v         v
DiagramContext  VoiceoverContext
      \       /
       v     v
     AnimationContext
```

每个 Context version 应有两类关系：

- `parent_context_id`：同一工作流节点的版本演进，例如 planner retry v1 -> v2 -> v3。
- `dependency_context_ids`：不同工作流节点的输入依赖，例如 DiagramContext 依赖 PlannerStateContext 和 LessonExplanationContext。

推荐使用不可变快照，而不是后续 context 持有前序 context 的可变对象引用。

```text
previous_context.state + deterministic merge = next_context.state
```

这样可以保证：

- 可复现：知道某轮 LLM 看到的 exact context。
- 可回放：可以用 parent + events 解释或辅助重建当前 state，但权威读取仍以 `state.json` 为准。
- 可分支：不同 retry / prompt / model 实验互不污染。
- 可诊断：能解释每个状态为什么出现、为什么被提升或合并。
- 可失效：上游 context 变化时，下游 context 可以显式 stale/rebase。

## Persistence Model

Context 应持久化为不可变 Context Version 文件，而不是只保存散落 debug 文件。

权威性约定：

- `state.json` 是该 Context Version 的权威事实源。
- `events.jsonl` 是解释性审计日志，记录本版本相对 parent 为什么发生变化。
- 如果 `state.json` 与 `events.jsonl` 冲突，以 `state.json` 为准。
- 不要求通过重放历史 events 来重新计算当前 state；normalizer、resolver、compiler 版本变化后，event replay 可能无法 bit-for-bit 复现。
- events 的价值是诊断、diff、debug 和 explainability，不是替代 state snapshot。

建议目录形态：

```text
internal/contexts/
  planner/
    ctx_planner_<problem_id>_v003/
      manifest.json
      state.json
      events.jsonl
      projections/
        prompt-payload.json
        step-intent-draft.json
        retry-state.json
        semantic-read-catalog.json
      llm/
        prompt.system.md
        prompt.user.md
        raw-response.txt
        llm-call.json
      diagnostics/
        validation-report.json
        normalization-report.json
        candidate-resolution-report.json
        runtime-diagnostic.json
```

各文件职责：

- `manifest.json`：context id、type、schema version、parent/dependency ids、template/model/hash 信息。
- `state.json`：Context 的语义状态，是该版本的权威快照。
- `events.jsonl`：本版本相对 parent 的解释性增量事件。
- `projections/`：从 Context 生成的结构化视图。
- `llm/`：真实调用 LLM 的输入输出。
- `diagnostics/`：验证、归一化、执行诊断结果。

当前 `internal/solver-runs/.../attempt-*` 里的 debug 文件可以逐步升级为 ContextVersion 的 `projections / llm / diagnostics`。

## ProblemExtraction 到 Planner 的交接

`ProblemExtractionContext` 会包含大量过程数据，例如 OCR evidence、图片区域、低置信 span、候选实体、解析冲突、被丢弃的解释、normalization decision。

这些过程数据不应全部传给 solver planner。下游应读取干净 projection：

```text
ProblemExtractionContext.to_problem_ir()
ProblemExtractionContext.to_llm_problem_payload()
ProblemExtractionContext.to_quality_summary()
```

其中：

- `ProblemIR` 是题面事实源。
- `llm_problem_payload` 是给 LLM 的题面视图。
- `quality_summary` 只保留必要风险，例如某个标签低置信、某条条件来自 OCR 修正。

### ProblemIR 的来源边界

`ProblemIR` 是 planner 依赖的稳定接口，不强制绑定到 `ProblemExtractionContext`。

允许两种来源：

- **extracted ProblemIR**：由 `ProblemExtractionContext.to_problem_ir()` 投影生成，适合从图片、OCR、PDF、网页题面进入系统。
- **authored ProblemIR**：由人工、fixture、skill 或 lesson-data 直接编写，作为 ground truth 输入 planner。

Planner 只依赖 `ProblemIR` 接口，不关心其来源。没有 extraction context 的手工题目必须可以直接进入：

```text
Authored ProblemIR
  -> PlannerStateContext.initial(problem_ir, family_spec, method_catalog)
```

当 `ProblemIR` 来自 extraction 时，`PlannerStateContext.manifest.dependency_context_ids` 应记录对应的 `ProblemExtractionContext` id；当 `ProblemIR` 是 authored ground truth 时，manifest 记录 `problem_source="authored"` 和 source artifact path/hash 即可。

这保证 Context 架构不会强迫所有现有 fixture 和人工题库先迁移到 extraction pipeline。

Planner 链路不应直接由 `ProblemIR` 拼 prompt。推荐流程是：

```text
ProblemExtractionContext
  -> ProblemIR projection
  -> PlannerStateContext.initial(problem_ir, family_spec, method_catalog)
  -> PlannerStateContext.to_prompt_payload()
  -> prompt renderer
  -> LLM
```

原因是 PlannerStateContext 会加入题目数据之外的 planner 语义：

- family / capability catalog；
- semantic read catalog；
- question goals；
- scope graph；
- known objects / states / conditions；
- previous attempts；
- stable prefix；
- issues；
- repair target；
- alias / runtime projection。

这些不是 ProblemIR 的职责。

## PlannerStateContext 与 RuntimeContext 的关系

两者是同一链路的两个层级。

`PlannerStateContext` 是语义层对象模型，回答：

> 解题过程中我们知道了什么？这些知识属于哪个数学对象？在哪个 scope 有效？有哪些别名和依赖？

`RuntimeContext` 是执行层黑板，回答：

> method 执行时从哪里取值？算完写到哪里？值的 runtime type 是什么？

关系如下：

```text
PlannerStateContext
  MathObject / StateSlot / Condition
          |
          | projection / compile
          v
BindingIndex + RuntimeContext
  handle -> ContextPath -> TypedValue
```

示例：

```text
StateSlot(Function(parabola).parametric_expression@ii)
  canonical_handle = fact:ii:parametric_parabola
  aliases = [
    fact:ii:c_expr_in_a_m,
    fact:ii_1:parametric_parabola
  ]
  runtime_type = Parabola
  runtime_path = $question.ii.outputs.parametric_parabola
```

PlannerStateContext 不直接持有已执行的 SymPy 值，也不假装 method 已经运行；它只知道某个状态会由哪个 step 产生、类型是什么、依赖是什么、在哪个 scope 可见。

## Prompt 作为 Projection

Prompt 应由 Context 统一投影：

```text
PlannerStateContext.state
  -> to_prompt_payload()
  -> render with prompt_template_version
  -> prompt.system.md / prompt.user.md
```

Rendered prompt 需要随 ContextVersion 持久化，记录：

```json
{
  "context_id": "ctx_planner_nankai_v003",
  "projection_type": "planner_prompt",
  "template_version": "...",
  "schema_version": "...",
  "model": "deepseek-v4-flash",
  "hash": "..."
}
```

这样既能复现 LLM 输入，又不会把 prompt 文本当成事实源。

## Retry 作为 Context Enrichment

Retry 不应是“拼接上一轮错误文本再让 LLM 重新推理”，而应是不断丰富 Context：

```text
PlannerStateContext v1
  raw draft
  semantic resolution
  normalized draft
  trial issue

PlannerStateContext v2
  parent = v1
  events:
    - alias_promoted
    - read_rewritten
    - stable_prefix_updated
    - issue_reclassified
  projection:
    - baseline_draft
    - repair_suffix
    - latest_retry_state
```

LLM 下一轮看到的是 v2 的 prompt projection，而不是需要自己从 v1 的失败历史里恢复状态。

### Retry Context Retention Policy

每次 retry 都可以产生新的 Context Version，但持久化策略不能无限制保留完整快照。推荐把“语义可复现”和“磁盘成本”分层处理。

默认策略：

- `v_initial`：保留完整 `state.json`、`projections/`、`llm/`、`diagnostics/`。
- `v_final`：保留完整 `state.json`、`projections/`、`llm/`、`diagnostics/`。
- 中间 retry version：默认保留 `manifest.json`、`events.jsonl`、关键 `issues`、`raw-response.txt`、`retry-state.json`；完整 `state.json` 可按配置关闭。
- 失败 version：如果该轮引入新的 issue code、resolver/normalizer crash、answer mismatch 或人工标记为 interesting，应提升为 full snapshot。
- CI / opt-in integration：可配置为 full retention，用于回归分析和模型行为研究。

示例策略：

```text
retention:
  full_snapshots: initial, final, interesting_failures
  middle_versions: compact
  compact_keeps:
    - manifest.json
    - events.jsonl
    - projections/retry-state.json
    - llm/raw-response.txt
    - diagnostics/issue-summary.json
```

压缩后的中间版本不再承担权威读取职责；它们用于解释 retry 轨迹。若需要完整复现某个中间版本，可以在开启 full retention 的调试运行中重跑。

## Generalized Domain Contexts

同一模式可以推广到所有 LLM pipeline。

### ProblemExtractionContext

用于题目解析：

- source text / source image；
- detected entities / facts / goals；
- evidence spans / image regions；
- unresolved spans；
- confidence；
- conflicts；
- canonical ProblemIR projection。

### PlannerStateContext

用于解题步骤规划：

- problem objects；
- conditions；
- state slots；
- steps；
- stable prefix；
- issues；
- retry repair targets；
- StepIntent / runtime projection。

### LessonExplanationContext

用于学生友好讲解：

- solution steps；
- known facts by step；
- student level；
- pedagogical goal；
- misconception risks；
- formula introductions；
- step dependencies；
- language style。

### DiagramContext

用于图形生成：

- geometry objects；
- roles: given / derived / auxiliary / highlighted；
- coordinates / constraints；
- visibility by step；
- labels；
- style state；
- dependency on solution step。

### AnimationContext

用于动画生成：

- scene states；
- object visibility；
- motion paths；
- highlight events；
- narration alignment；
- camera / framing；
- step-to-animation mapping。

这些 Context 不必共用同一个类，但应共享同一种架构思想：

```text
DomainContext
  -> prompt projection
  -> LLM proposes candidate update
  -> parser maps output back to DomainContext
  -> deterministic validator / normalizer / reconciler updates context
  -> retry enriches context, not just appends error text
  -> final artifact projection
```

## Design Decisions

- Context 是事实源；prompt、StepIntent、Diagram JSON、Animation timeline 都是 projection。
- Context version 是不可变快照；后续版本通过 parent + events 表达演进。
- 下游 Context 通过 dependency context id 依赖上游，不直接修改上游 Context。
- Prompt 是 Context 管理和持久化的 artifact，但不是 Context semantic state。
- ProblemExtractionContext 向 Planner 暴露干净 ProblemIR projection，而不是完整过程数据。
- PlannerStateContext 是 RuntimeContext 的上游语义模型，最终投影为 canonical handle / ContextPath / TypedValue binding。

## Unified Solver Implementation Direction

`PlannerStateContext`、Capability Pack、函数式 Method/Recipe 应合并成一条实现主线：

```text
ProblemIR
  -> PlannerStateContext
  -> prompt projection
  -> LLM candidate update
  -> Context Reconciler
  -> PlannerStateContext vNext
  -> StepIntent / FunctionalPlan / StepPlan projection
  -> Runtime
```

三者职责划分：

| 模块 | 主职责 | 稳定性收益 |
|------|--------|------------|
| `PlannerStateContext` | 维护题目对象、状态槽、条件、别名、稳定前缀、问题和修复目标 | LLM 不再负责记住上下文、scope、promotion 和 retry 状态 |
| Capability Pack | 声明当前 family 可用的能力、能力契约和 prompt 暴露边界 | LLM 不会看到不可执行能力，family 复制规则逐步减少 |
| FunctionSpec / MacroSpec | 把 method / recipe 表达为读写 `StateSlot` 的 typed transformer | LLM 不再手写 runtime slot、binding 细节和 recipe 内部链 |

核心原则：

- LLM 不编排 runtime，只提出语义解题意图。
- LLM 输出 JSON 是对 Context 的候选更新，不是事实源。
- Capability Pack 不只是 method/recipe 列表，而是可执行能力契约。
- Function/Macro 不以增加 LLM 编程负担为目标，而是让代码可以确定性补全、校验、展开和编译。
- `StepIntent`、`semantic_reads`、`FunctionalPlan` 都应被视为 Context projection 或 candidate update，不应各自维护一套事实源。

### Responsibility Boundary

LLM 负责：

- 选择数学路线；
- 选择当前题可见的能力；
- 指定目标对象或目标状态；
- 用 prompt catalog 中的 semantic ref 连接必要参数；
- 给出必要的解题 reason，供教学层复用。

代码负责：

- 维护状态槽、别名、scope 可见性和 stable prefix；
- 判断 capability 是否可执行；
- 推导 canonical handle、runtime path、binding slot；
- 推导 produces 的 authoritative output type；
- 将 LLM 的统一输出意图分拣为 MathObject / Condition / StateSlot；
- 自动补全 method 的机械参数；
- 展开 macro 内部步骤；
- 收集所有 validation / candidate / runtime / answer 问题；
- 生成下一轮 retry baseline 和 repair suffix。

### Non-Goals

- 不把 LLM 变成通用程序员。
- 不要求 LLM 手写 `ContextPath`、promote 规则或 recipe 内部 method 链。
- 不把 FunctionalPlan 当作新的 runtime 真相。
- 不为了短期通过某道题，在 prompt 中写具体题目、具体 family 或具体 recipe 链的教练文本。

## Anti-Patterns

### Anti-pattern 1: 把 prompt 文本当 Context state

Prompt 是 Context 的 projection artifact，不是事实源。不能因为某个 few-shot、repair hint 或 prompt 示例里出现了某个 handle，就把它当成当前题的可读状态。

风险：

- prompt 中的示例 handle 与当前 runtime handle 语义不一致；
- few-shot 里的 recipe 链被模型误套到不适用 family；
- retry 依赖自然语言历史，而不是结构化 issue / state。

正确做法：

- prompt 只渲染 `PlannerStateContext.to_prompt_payload()` 的 projection；
- 示例只能说明格式，不能引入当前题 catalog 没有的具体 method/recipe/handle；
- LLM 输出必须通过 Context Reconciler 合并回 state，不能直接修改 state。

### Anti-pattern 2: Context 持有可变 runtime 对象引用

Context version 应是不可变快照，不能持有会被后续 normalizer、executor 或 registry 修改的 mutable object。

风险：

- 某轮 retry 的 state 被后续 retry 隐式改变，无法复现；
- debug artifact 与真实运行时状态不一致；
- Context version 之间出现共享 mutable list/dict。

典型危险形态：

```text
Context.state.previous_steps -> NormalizationRuleContext.previous_steps mutable list
Context.state.runtime_context -> live RuntimeContext object
```

正确做法：

- Context state 只保存 JSON-serializable snapshot 或 frozen dataclass；
- runtime object 只能作为 diagnostics/projection 来源，不能被 Context 引用为状态本体；
- 进入 Context 前做 snapshot / normalize / hash。

### Anti-pattern 3: 下游 Context 直接修改上游 state

下游 Context 可以依赖上游 Context version，但不能直接修改上游 state。

风险：

- `DiagramContext` 为了画图改动 `PlannerStateContext.step_timeline`；
- `LessonExplanationContext` 为了讲解重命名 planner 的 StateSlot；
- 上游 solver 结果被下游 artifact 生成过程污染。

正确做法：

- 下游 Context 通过 `dependency_context_ids` 引用上游；
- 下游需要的补充信息写在自己的 state/events 中；
- 如果发现上游确实错了，创建新的上游 Context version，然后让下游显式 rebase。

### Anti-pattern 4: Context 只是 PlannerInputs 的浅包装

如果 Context 只是把 `ProblemIR / family_spec / previous_errors` 换一个字段名保存，就只增加了间接层，没有降低 LLM 幻觉。

正确做法：

- Phase 1 必须完成 alias continuity、stable prefix granularity 或 scope visibility model 中至少一个闭环；
- 没有闭环收益前，不把 `StrategyPayloadBuilder` 主路径切到 Context；
- 每个 Context event 都应能解释一个现有系统无法稳定表达的状态变化。

### Anti-pattern 5: 要求 LLM 手写 runtime 输出形状

`produces.output_type`、`creates` vs `produces`、answer/fact/entity 的内部分类都属于 runtime projection 细节，不应长期要求 LLM 精确维护。

风险：

- LLM 把 `Point` 写成 `Expression`，导致本可确定的 step 在 validator/runtime 前失败；
- LLM 把已有题设对象写进 `creates`，或者把新 fact 写进 `creates` 而不是 `produces`；
- prompt 为了解释这些差异变长，反而增加幻觉面。

正确做法：

- raw LLM payload 可以保留这些字段作为兼容 hint；
- authoritative output type 由 recipe/method/contract + handle/semantic target 确定性推导；
- 长期 raw schema 应允许统一 `outputs[]`，再由 Context Reconciler 分拣为 `MathObject / Condition / StateSlot`。

## Roadmap

### Phase 1: PlannerStateContext Shadow Mode

目标是在不改变现有 StepIntent 输出格式的前提下，把 planner 的语义状态建模出来。

Phase 1 不能只是把 `PlannerInputs` 包成一层 shallow wrapper。引入 Context 的最低验收标准是：它必须解决至少一个现有 `PlannerInputs -> StrategyPayloadBuilder` 不能稳定解决的问题，然后才允许进入“Context as Prompt Source”。

- 建立 `MathObject / StateSlot / Condition / Alias / Issue` 的内部模型。
- `StateSlot` 身份使用 `object_ref + state_kind + scope_id + runtime_type`，不绑定 canonical handle，为后续 FunctionSpec / MacroSpec 读写 StateSlot 预留接口。
- 从 `ProblemIR + SolverFamilySpec + expanded Capability Pack` 初始化 context。
- 将 semantic resolve、handle resolve、normalizer、candidate resolve、trial diagnose 的结果同步为 context events。
- 建立 state alias / promotion ledger，解决 handle promotion / alias merge 后后续 reads 不同步的问题。
- 输出 `planner-state-context.json`、`state-rewrite-ledger.json`、`context-events.jsonl` debug artifact。
- 现有 runtime 仍消费 canonical `StepIntent.reads`；Context 先作为 shadow truth 和 debug truth。

写侧卸载 pilot：

- `produces[].output_type` 在 raw LLM payload 中降级为 optional hint。
- Normalizer / validator 从 `recipe_hint`、method spec、recipe spec、现有 binding metadata 和 handle semantic name 推导 authoritative output type。
- 如果 LLM 写了 `output_type` 且代码能唯一推导，代码推导结果覆盖 LLM hint，并在 validation / normalization report 中记录。
- 如果无法唯一推导，才报 validation error；不能用宽泛字符串猜测静默通过。
- 内部 `StepIntent` 和 runtime contract 仍保持 canonical `produces.output_type`，避免本阶段改动 executor。

该 pilot 放在 Phase 1，而不是等 FunctionSpec，是因为现有 method/recipe metadata 已经可以覆盖一批高频错误；后续 Phase 2 的 CapabilityContract 会成为更权威的推导来源。

成功信号：

- 已知 DeepSeek 失败中的 stale read / promoted handle 问题可由 context rewrite ledger 定位并修复。
- retry baseline 不再从散落 previous attempts 反推，而能从 context projection 生成。
- Semantic layer 通过后，runtime layer 不应再因为同一状态的旧 alias 失败。
- LLM 漏写或写错 `produces.output_type` 时，若代码可唯一推导，raw payload 仍能进入 canonical StepIntent。

最小闭环验收：

- **Alias continuity**：当 normalizer / resolver 把 `fact:ii_1:parametric_parabola` promotion 到 `fact:ii:parametric_parabola` 时，Context 记录二者指向同一 `StateSlot`，并能把后续 stale read rewrite 到当前 canonical projection。
- **Stable prefix granularity**：稳定前缀不只是 step_id set，而是 `StableStep`，包含 normalized payload、verified slot/condition writes、slot/condition reads；retry merge 以这个结构为准。
- **Scope visibility model**：Context 显式保存 scope graph 和 StateSlot `valid_scope`，semantic reads、normalizer 和 retry projection 读取同一套可见性判断。
- **Debug proof**：每个自动 rewrite 必须落 `state-rewrite-ledger.json`，包含 old_ref、new_ref、state_slot_id、reason、source_layer。

如果 Phase 1 只产出 `planner-state-context.json`，但不能完成上述至少一个闭环，就不应继续把 `StrategyPayloadBuilder` 切到 Context。

### Migration Strategy for Phase 1

Phase 1 采用 adapter / shadow mode，不替换现有 planner 主路径。

现有路径保持：

```text
PlannerInputs
  -> StrategyPayloadBuilder
  -> LLM StepIntentDraft
  -> SemanticReadResolver / HandleResolver / Validator / Normalizer
  -> CandidateResolver / TrialExecutor
```

Phase 1 新增旁路：

```text
PlannerInputs
  -> PlannerStateContext.initial_from_inputs(...)
  -> observe semantic/handle/validation/normalization/runtime reports
  -> PlannerStateContext vNext
  -> debug artifacts + optional rewrite ledger
```

共存策略：

- `PlannerInputs` 仍是调用入口，避免一次性重写 planner API。
- `CanonicalHandleRegistry` 仍是 canonical handle 权威来源；Context Phase 1 通过 adapter 读取 registry snapshot，不直接替代 registry。
- `StepIntentDraft` 测试继续保留；新增 Context tests 只验证 Context projection / rewrite ledger / stable prefix，不要求所有旧测试迁移。
- `StrategyPayloadBuilder` 暂不从 Context 读取；只有当 Phase 1 最小闭环通过后，才进入 Context as Prompt Source。
- `PlannerRetryState` 暂时继续存在；Context 先生成兼容 projection，后续再把 retry state 降级为 Context projection。

测试迁移策略：

- 保留现有 planner tests 作为行为回归。
- 新增 narrow Context unit tests：scope graph、StateSlot identity、alias index、rewrite ledger、stable prefix。
- 新增 write-side unloading tests：output_type missing / wrong 时可由 recipe/method metadata 推导并覆盖；歧义时失败。
- 给现有 DeepSeek failure fixture 增加 Context regression：stale read 被记录并 rewrite，且不改变旧 runtime 输出。
- 当某个 projection 完全由 Context 接管后，再迁移对应旧测试，而不是一次性迁移全部 StepIntentDraft 测试。

### Phase 2: Capability Pack Contracts

目标是把 Capability Pack 从能力列表升级成代码可验证的能力契约。

新增概念：

```text
CapabilityContract
  capability_id
  kind: method | recipe | macro
  slot_reads: StateSlotPattern[]
  condition_reads: ConditionPattern[]
  slot_writes: StateSlotPattern[]
  condition_writes: ConditionPattern[]
  exposes_to_llm: bool
  execution_status: executable | catalog_only | internal
```

Pattern 草案：

```python
@dataclass(frozen=True)
class StateSlotPattern:
    object_kind: str | None       # point / function / segment / ...
    object_ref: str | None        # optional exact MathObject id, usually None in pack contracts
    state_kind: str               # coordinate / expression / coefficients / minimum_value / ...
    runtime_type: str | None      # Point / Parabola / Expression / ...
    scope_policy: Literal["current", "ancestor_visible", "problem", "same_as_target"]
    cardinality: Literal["one", "optional", "many"]


@dataclass(frozen=True)
class ConditionPattern:
    condition_kind: str           # point_on_curve / midpoint / angle_sum / coefficient_relation / ...
    subject_kinds: tuple[str, ...]
    value_type: str | None
    scope_policy: Literal["current", "ancestor_visible", "problem", "same_as_target"]
    cardinality: Literal["one", "optional", "many"]
```

示例：

```text
CapabilityContract(quadratic_from_constraints)
  slot_reads:
    - StateSlotPattern(object_kind="point", state_kind="coordinate", runtime_type="Point", cardinality="many")
  condition_reads:
    - ConditionPattern(condition_kind="coefficient_relation", subject_kinds=("function",), value_type="Equation", cardinality="optional")
  slot_writes:
    - StateSlotPattern(object_kind="function", state_kind="expression", runtime_type="Parabola", cardinality="one")
    - StateSlotPattern(object_kind="function", state_kind="coefficients", runtime_type="Coefficients", cardinality="optional")
  condition_writes: []
```

Pattern 默认是类型/状态模式匹配，不要求绑定具体 `object_ref`；只有 family override、target-specific recipe 或 retry repair 需要精确 object ref。这样 pack contract 可以泛化复用，Context Reconciler 再结合当前题的 `MathObject / StateSlot / Condition` 做确定性匹配。

实现内容：

- Pack 保留 `method_ids / step_recipes` 兼容字段，但新增 contract projection。
- Prompt 只暴露 `execution_status=executable` 且 contract 完整的 direct capability。
- Preflight 测试保证：凡是 prompt 暴露给 LLM 的 direct method，必须可由 binding/contract 编译，或明确标记为 `catalog_only`。
- 通用 binding rule 逐步下沉到 pack contract；family 只保留题型路线偏好和少量 override。
- `method_binding_rules` 暂不强制迁移，但新增规则优先写成 pack-level contract。

成功信号：

- Pack 扩大 catalog 不再导致 LLM 看到不可执行 direct method。
- family 之间复制的 evaluate / curve point / midpoint / parameter solving 规则开始收敛。
- Capability exposure 可以通过代码测试，而不是靠 prompt 文案约束。

### Phase 3: Context-Driven Semantic Reads

目标是让 `semantic_reads` 成为 `PlannerStateContext.StateSlot` 的 projection，而不是独立 alias 系统。

- `semantic_read_catalog` 从 Context 的 objects / conditions / state slots / previous step outputs 投影。
- `SemanticReadResolver` 复用 Context 的 alias、scope、valid_scope、source_step 规则。
- `from_step` 缺失推断、scope 前缀消歧、value_type alias 都迁入 Context Reconciler。
- `StrategyPayloadBuilder` 改为从 `PlannerStateContext.to_prompt_payload()` 读取。
- `semantic_read_catalog / previous_attempt_state / retry_state` 统一变成 Context projection。
- prompt 模板只渲染 projection，不直接拼接散落数据源。

同一阶段引入 Context-driven outputs：

- raw LLM payload 可以使用统一 `outputs[]` 表达本 step 打算产出的对象/事实/状态。
- 旧 `creates[] / produces[]` 继续兼容；若 `outputs[]` 非空，以 `outputs[]` 为主，旧字段作为 compatibility mirror。
- `outputs[]` 分拣复用 Phase 1 的 authoritative output type inference，不另起一套类型推断逻辑。
- Context Reconciler 根据 `ProblemIR` 现有对象、handle namespace、semantic target、CapabilityContract 和 StateSlot schema，把 `outputs[]` 分拣为：
  - `MathObject`：新辅助点、线、圆等对象，投影到 internal `creates[]`。
  - `Condition`：新事实、关系、约束，投影到 internal `produces[]` 或 condition state。
  - `StateSlot`：坐标、函数表达式、参数值、最值表达式、答案等状态，投影到 internal `produces[]`。
- 如果 LLM 在 `outputs[]` 中引用已存在题设对象，代码应改为 read/reference 或忽略重复 create，并记录 normalization event。
- 内部 StepIntent / runtime 仍消费 `creates[] / produces[]` projection，本阶段不改 executor。

成功信号：

- Semantic Reads 和 legacy HandleResolver 不再各自维护一套 scope/name alias 逻辑。
- LLM 可以继续混用 semantic ref 和 canonical handle，但最终都通过 Context Reconciler 合并到同一 StateSlot。
- semantic read 错误能一次性收集并映射到具体 StateSlot / StepState。
- LLM 不再需要稳定区分 `creates` 与 `produces`；统一 `outputs[]` 可被确定性投影为现有 runtime schema。

### Phase 4: Context as Retry Memory

- 每轮 LLM 输出合并为 Context events。
- `baseline_draft / stable_prefix / repair_suffix / issues` 从 Context 生成。
- retry 不再依赖 raw previous attempts 的文本历史。
- `PlannerRetryState` 成为 Context projection，而不是单独维护的失败摘要。
- preserve policy 作用在 Context step/state 上，再投影成 raw payload merge。

成功信号：

- 任意一层失败后，下一轮仍保留最新稳定 Context，不因 semantic / runtime / answer 层切换而丢失增量更新。
- 真实 opt-in 测试中的 retry prompt 可以从 `planner-state-context.json` 复现。

### Phase 5: FunctionSpec Facade

目标是把 method 暴露成读写 StateSlot 的 typed function facade，但不立刻要求 LLM 输出 FunctionalPlan。

示例：

```text
FunctionSpec(quadratic_from_constraints)
  slot_reads:
    - Point.coordinate[]
  condition_reads:
    - Function.coefficient_relation?
  slot_writes:
    - Function(parabola).expression
    - Function(parabola).coefficients
```

实现内容：

- 从 MethodSpec + CapabilityContract 派生 FunctionSpec。
- resolver 内部优先用 FunctionSpec 做参数类型检查和 slot matching。
- 旧 StepIntent 仍可作为输入；代码把 `recipe_hint + semantic_reads + produces` reconcile 成 function call candidate。
- binding selector 逐步从“猜 reads 里哪个 handle 是哪个 slot”迁移为“按 function schema 编译”。

成功信号：

- 错误反馈从 `binding_not_found` 变成 `function.arg expected X, got Y`。
- LLM 不需要知道 runtime slot 名，但代码可以给出稳定、类型化的修复目标。

### Phase 6: MacroSpec / Recipe as State Transformer

目标是把 recipe 表达为代码拥有的 typed macro，减少 LLM 手写 internal method 链。

实现内容：

- 给高频稳定 recipe 增加 MacroSpec：input StateSlot、output StateSlot、internal graph、prerequisites。
- normalizer / recipe compiler 中的 hidden backfill 逐步迁移到 macro prerequisites。
- MacroExpander 负责展开内部 function graph，并保留 provenance。
- repair feedback 只暴露缺少的 semantic state，不暴露题目特定 recipe 链。

优先候选：

- `broken_path_straightening_minimum_expression`
- `right_angle_equal_length_construct_and_select`
- `square_path_dimension_reduction`
- `line_parabola_second_intersection_point` 相关交点链

成功信号：

- LLM 选择 macro 后，不需要输出 midpoint / locus / endpoint selection 等内部 utility step。
- compiler 不再静默插入大量 family-specific backfill；这些动作有 macro contract 和 debug provenance。

### Phase 7: FunctionalPlan Opt-In

目标是在 Context / Pack Contract / FunctionSpec / MacroSpec 成熟后，让 LLM 可选输出 FunctionalPlan。

定位：

```text
FunctionalPlan = LLM 对 PlannerStateContext 的 candidate update IR
```

而不是：

```text
FunctionalPlan = 新 runtime truth
```

实现内容：

- 新增 FunctionalPlan schema，但仍允许 StepIntent。
- FunctionalPlan call 的 args / returns 都引用 Context StateSlot / SemanticRef。
- Context Reconciler 先验证 FunctionalPlan，再合并成 `PlannerStateContext vNext`。
- Runtime 继续消费 Context projection 出来的 StepPlan / MethodInvocation。

成功信号：

- Function/Macro 输出相比 StepIntent 更短、更稳定。
- retry 修改的是 suffix candidate update，不会覆盖 stable prefix。
- FunctionalPlan 失败能回落到 StepIntent projection 或给出同构 retry issue。

### Phase 8: Cross-Domain Context Graph

- 引入 ProblemExtractionContext、LessonExplanationContext、DiagramContext、AnimationContext 的统一版本/依赖规范。
- 下游 artifact 可以声明依赖的 context version，并在上游改变时显式 stale/rebase。
