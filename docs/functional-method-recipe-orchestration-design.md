# 函数式 Method/Recipe 编排架构设计

## Summary

当前 Method Solver 已经具备一部分函数式基础：method 基本是无状态计算单元，`InvocationExecutor` 是统一副作用边界，`RuntimeContext` 负责保存事实、临时值和 promote 结果。

但 LLM 侧的策略输出仍偏命令式：`StepIntent` 用 `recipe_hint / reads / produces / creates` 描述一步解题意图，后续由 resolver、binding rules、prep invocation、TrialExecutor dry-run 将它翻译成真实 `MethodInvocation`。随着 method、recipe、family、capability pack 增多，这种"LLM 轻描述 + runtime 重猜测"的成本会继续上升。

**当前 binding/resolution 体系的代码规模：**

| 模块 | 行数 | 核心职责 |
|------|------|---------|
| `binding_rules.py` | 2487 | 93 个 binding selector + 6 个 expansion selector |
| `strategy_normalizer.py` | 1703 | 9 条 normalization rule |
| `strategy_validator.py` | 1568 | handle 校验 + recipe alignment |
| `handle_registry.py` | 1078 | handle 解析、alias 修正、scope 校验 |
| `strategy_resolver.py` | 1074 | capability 候选解析 |
| `entity_state_resolver.py` | 265 | entity typed state 补位 |
| `strategy_compiler.py` | 45 | 编译入口（实际编译逻辑分散在上述模块） |
| **合计** | **8220** | |

这 8220 行代码的根本原因是：**LLM 输出的 semantic handle 和 method 实际需要的 typed input slot 之间有巨大的语义鸿沟**，需要大量猜测逻辑来弥合。

函数式编排的目标不是让 LLM 写通用程序，而是让 LLM 输出一个受类型系统和能力菜单约束的函数调用图，**把当前分散的启发式猜测收敛为可测试的确定性引用解析、类型检查和编译流程**：

```text
LLM FunctionalPlan
  -> TypeChecker / Resolver
  -> Macro Expander
  -> Compiler
  -> StepPlan / MethodInvocation
  -> InvocationExecutor
```

核心原则：

- Method 暴露为 typed function。
- Recipe 暴露为 typed macro，内部可展开为多个 function 调用。
- LLM 只负责数学上有意义的参数连接，不负责 runtime scope、promote、临时路径等机械细节。
- Compiler 保留副作用边界，把函数式计划编译为当前 runtime 可执行的 `StepPlan`。
- Capability Pack 从"method/recipe 列表 + binding 配置"逐步升级为"typed functions + macros + semantic adapters"的能力模块。
- **渐进式迁移**：先简化 LLM reads 输出（semantic_reads），再引入 FunctionSpec，最后迁移到 FunctionalPlan IR。每一步都可以独立测试和回滚。

## Current Shape

当前链路大致是：

```text
ProblemIR
  -> FamilySpec
  -> prompt method_catalog / recipe_catalog
  -> LLM StepIntentDraft
  -> HandleResolver (alias/scope 修正)
  -> StepIntentNormalizer (9 条 rule)
  -> StepIntentCandidateResolver (capability 匹配)
  -> RecipeTrialExecutor (dry-run)
  -> MethodBindingRuleRegistry (93 个 selector)
  -> EntityStateResolver (typed state 补位)
  -> StepPlan
  -> InvocationExecutor
```

`StepIntent` 的优点是宽松、易迁移、兼容现有 fixtures；问题是它没有直接表达 method input slot 与 semantic argument 的映射。比如 LLM 写：

```json
{
  "recipe_hint": "quadratic_from_constraints",
  "reads": ["fact:i:axis_relation", "point:problem:A", "point:problem:B"],
  "produces": [{"handle": "fact:i:parabola", "valid_scope": "i"}]
}
```

runtime 需要再判断：

- 哪些 reads 是曲线点（binding selector: `curve_point_if_read`）；
- 哪个 relation 应进入 `coefficient_relation`（binding selector: `fact:coefficient_relation:Equation`）；
- 是否需要补 `quadratic / x / all_coefficients`（expansion selector: `known_coefficients_if_read`）；
- 输出是否需要连带保存 `coefficients`（expansion selector）；
- 当前 scope 里是否已有可读 `Parabola`（`EntityStateResolver`）；
- 失败后应 fallback 哪个 capability（`StepIntentCandidateResolver` top-k）。

这些逻辑目前分散在 binding rules、handle registry、context inventory、prep invocation、candidate resolver 和 prefix dry-run 中。

### 当前 LLM handle 错误分类

LLM 在 `reads` 字段中写 handle 时的常见错误：

| 错误类型 | 示例 | 当前修复 | 频率 |
|---------|------|---------|------|
| scope 前缀写错 | `fact:ii_1:xxx` 应为 `fact:ii:xxx` | `HandleResolver` ancestor scope 修正 | 高 |
| namespace 前缀写错 | `facts:` / `seg:` | `HandleResolver` namespace alias | 中 |
| entity 放进 creates | 题设点放进 `creates` | `HandleResolver` move to reads | 中 |
| 状态化点名 | `point:ii:OptimalG` | `HandleResolver` state point alias | 低 |
| 自造 handle | `relation:*` / `condition:*` | validator 直接拒绝 | 低 |
| produces scope 过宽 | `valid_scope: "problem"` 依赖子问条件 | `HandleResolver` narrow scope | 中 |

这些修复逻辑合计 ~700 行（`CanonicalHandleAliasResolver` + `HandleResolver` 中的修正方法）。如果 LLM 不再写完整 handle，这些代码的触发频率会显著下降；但只要旧 `reads`、历史 fixtures 或真实 LLM 输出仍被接受，这些 legacy 修正逻辑就不能在 Phase 1 直接删除。

## Rejected Alternative: Hint-Based Binding

在讨论函数式编排之前，曾考虑过一种更轻量的方案：让 LLM 写自然语言 hint，runtime 用关键词匹配做绑定。

```json
{
  "capability": "translated_point",
  "hint": "C 向右平移 2"
}
```

**结论：不可行。** 原因：

1. **泛化不可能**：同一语义有无穷种自然语言表述（"C 向右平移 2" / "将点 C 沿 x 轴正方向移动 2 个单位" / "C(0,-3) 平移得到 G(2,-3)"），关键词匹配无法覆盖。
2. **本质是二次 NLP**：用 hint 做 binding 等于在 runtime 中再做一次 NLP parsing，和直接让 LLM 写 handle 一样脆弱。
3. **多候选歧义**：一道题中可能有 8 个 Point、5 条 Line，hint 中的"点 C"需要从中消歧，关键词匹配无法可靠完成。

正确的消歧应依赖 **ProblemIR 的结构化关系**（见下面的 Disambiguation Mechanism），不依赖 NLP。

## Target Model

函数式计划把 LLM 输出从"步骤描述"改成"函数调用图"。设计分三个递进层次。

### 层次 1: Semantic Reads（渐进式中间态，最高 ROI）

不改变 StepIntent 整体结构，只把 `reads` 从精确 canonical handle 改为语义引用：

```json
{
  "step_id": "derive_E_coordinate",
  "recipe_hint": "line_parabola_second_intersection_point",
  "semantic_reads": [
    {"ref": "BD", "kind": "line"},
    {"ref": "parabola", "kind": "output", "value_type": "Parabola", "from_step": "solve_parabola"}
  ],
  "produces": [
    {"handle": "fact:ii:E_coordinate_value", "valid_scope": "ii", "output_type": "Point"}
  ]
}
```

LLM 不再写 `type:scope:name` 格式的完整 handle，而是写 **canonical label**（来自当前题的 canonical entity/fact/output catalog）。`SemanticReadResolver` 在 Phase 1 只负责把这些语义引用解析回 canonical handle；不负责 method input slot 绑定、目标反推或复杂候选筛选。

### 层次 2: Typed Function Call（完整函数式调用）

```json
{
  "let": "parabola_i",
  "call": "quadratic_from_constraints",
  "args": {
    "curve_points": [
      {"ref": "A", "kind": "point"},
      {"ref": "B", "kind": "point"}
    ],
    "coefficient_relation": {"ref": "axis_relation", "kind": "fact"}
  },
  "returns": {
    "parabola": {"name": "parabola", "scope": "i"},
    "coefficients": {"name": "quadratic_coefficients", "scope": "i"}
  }
}
```

LLM 不需要写底层 ContextPath：

```json
{
  "quadratic": "$problem.symbols.quadratic",
  "x": "$problem.symbols.x",
  "all_coefficients": "$problem.symbols.coefficients"
}
```

这些由 function adapter 或 compiler 根据 method signature 和当前 scope 自动补齐。

### 层次 3: Macro Call（Recipe 作为高阶函数）

```json
{
  "let": "point_n",
  "call": "right_angle_equal_length_construct_and_select",
  "args": {
    "anchor": {"ref": "A", "kind": "point"},
    "reference": {"ref": "B", "kind": "point"},
    "target": {"ref": "N", "kind": "point_ref", "value_type": "PointRef"},
    "selection_constraint": {"ref": "N_on_parabola", "kind": "fact"}
  },
  "returns": {
    "point": {"name": "N_coordinate", "scope": "i"}
  }
}
```

Macro 内部再展开为：

```text
candidates = right_angle_equal_length_candidates(anchor, reference, target)
point = select_point_by_quadrant_constraint(candidates, selection_constraint)
```

## Disambiguation Mechanism

消歧分为两个阶段，不能混在 Phase 1 中一次性实现。

### Phase 1：精确语义引用解析

Phase 1 的 `SemanticReadResolver` 只做低风险解析：

- 从 canonical problem payload 构建可引用 catalog：entities、facts、question goals、前序 step outputs。
- 根据 `ref + kind + value_type? + from_step?` 精确查找 canonical handle。
- 如果存在多个候选，返回结构化 ambiguity error，不做启发式猜测。
- 如果找不到候选，返回 unknown semantic ref，不 fallback 到自然语言匹配。

这一步的目标是替代 LLM 手写 `type:scope:name`，不是替代 binding rules 或 TrialExecutor。

### 后续阶段：Typed disambiguation

当引入 FunctionSpec / MacroSpec 后，resolver 才能基于 capability signature 做更强的确定性消歧：

### 第一层：类型唯一性

满足 method 输入类型的 entity 只有一个时，直接绑定：

```text
method: solve_parabola
  input types: (SymmetryAxis, PassThroughPoints[])

ProblemIR 中:
  SymmetryAxis → 只有 1 个（x=1）→ 无歧义，直接绑定
```

### 第二层：目标反向推导

LLM 指定 `target` 或 `returns`，Runtime 从目标反向推导输入：

```json
{"call": "translated_point", "returns": {"point": {"name": "G_coordinate"}}}
```

ProblemIR 中有 `G 是 C 向右平移 2 个单位` 的结构化关系 → `source_point = C, vector = (2, 0)` 自动绑定。

### 第三层：Method 前置条件过滤

Method 自身声明的前置条件过滤多候选 entity：

```python
class LineParabolaIntersection(Method):
    input_types = {"line": Line, "curve": Parabola}
    preconditions = {
        "line": lambda line, ctx: line.passes_through(ctx.known_points),
    }
```

### 剩余情况：结构化引用

如果 typed disambiguation 仍无法消歧，LLM 使用 `from_step` 或 `kind + ref + value_type` 精确指定来源：

```json
{"ref": "parabola", "kind": "output", "value_type": "Parabola", "from_step": "solve_parabola"}
```

`from_step` 引用前序 step 产物，LLM 只需要知道数学概念层的命名，不需要知道 Runtime 内部结构。

**与当前方案的对比：**

| 维度 | 当前 canonical handle | Hint 语义 | Semantic Reads |
|------|---------------------|-----------|---------------|
| LLM 需要知道的 | Runtime 内部 scope 结构 | 无（但 Runtime 要做 NLP） | 题目中的点/线命名 |
| 泛化能力 | 差（handle 格式变了就错） | 极差（自然语言无穷变体） | 好（canonical label 来自 ProblemIR） |
| 消歧准确率 | 当前实测/回归统计 | 难以稳定评估 | 待 Phase 1 记录指标 |
| 新题目适配 | 需要 normalizer | 需要新匹配规则 | 低适配，依赖 canonical catalog 完整性 |

## Core Concepts

### Typed Function

Method 作为 typed function 暴露给 planner：

```python
FunctionSpec(
    function_id="quadratic_from_constraints",
    input_schema={
        "curve_points": "list[Point]",
        "coefficient_relation": "Equation?",
        "known_coefficients": "Coefficients?",
        "free_parameters": "list[Symbol]?",
    },
    output_schema={
        "parabola": "Parabola",
        "coefficients": "Coefficients",
    },
    adapters=(...),
)
```

FunctionSpec 不一定等同于底层 MethodSpec。它可以是给 LLM 和 compiler 看的语义门面，底层仍编译到现有 method input slots。

### Typed Macro

Recipe 作为 typed macro：

```python
MacroSpec(
    macro_id="broken_path_straightening_minimum_expression",
    input_schema={
        "path": "PathExpression",
        "moving_point": "PointRef|Point",
        "straightening_preference": "StraighteningPreference?",
    },
    output_schema={
        "minimum_expression": "MinimumExpression",
        "straightening_candidate": "StraighteningCandidate",
    },
    graph=(...),
)
```

Macro 适合封装 2 到 4 个稳定 method 的标准动作，不覆盖完整题目路线。

### Semantic Adapter

Adapter 负责把 LLM 的语义参数解析成 runtime 参数：

```text
{"ref": "A", "kind": "point"} -> current visible Point path ($problem.points.A)
{"ref": "N", "kind": "point_ref", "value_type": "PointRef"} -> current visible PointRef path ($question.ii.pointrefs.N)
{"ref": "axis_relation", "kind": "fact"} -> Equation path
curve_points=[{"ref": "A"}, {"ref": "B"}] -> p1/p2 或 curve_points slot
```

它替代一部分现有 binding rules，但不取消 typecheck、scope visibility、locked fact 保护。

**当前 binding selector 与 adapter 的映射关系：**

| 当前 binding selector | 对应 adapter 逻辑 | 是否可废弃 |
|---------------------|-----------------|----------|
| `fact:coefficient_relation:Equation` | `SemanticReadResolver` 按 kind=fact 精确匹配 | 是 |
| `symbol:a/b/c/x` | compiler 自动补齐 | 是 |
| `function:parabola` / produced `Parabola` | `SemanticReadResolver` 按 `kind=function` 或 `kind=output + value_type=Parabola` 匹配 | 部分替代 |
| `right_angle:anchor/reference/target` | FunctionSpec input_schema 显式映射 | 是 |
| `read_type:Point/Parabola/...` | TypeChecker 类型推导 | 是 |
| `curve_point_if_read` | compiler expansion 保留 | 保留 |
| `parameter_value_if_read` | compiler expansion 保留 | 保留 |

**预计**：93 个 binding selector 中约 70 个可以被 FunctionSpec + adapter 替代；剩余 ~23 个 expansion selector 和条件补位逻辑需要保留在 compiler 中。

### FunctionalPlan

FunctionalPlan 是 LLM 与 runtime 之间的新 IR：

```python
FunctionalPlan(
    calls=(
        FunctionCall(
            call_id="derive_parabola_i",
            capability_id="quadratic_from_constraints",
            args={...},
            returns={...},
            goal_type="derive_parabola",
        ),
    ),
)
```

它可以先作为 `StepIntentDraft` 之后、`StepPlan` 之前的中间层，也可以长期替代部分 StepIntent 字段。

### SemanticRef

`SemanticRef` 是所有层次共享的参数引用格式：

```python
@dataclass(frozen=True)
class SemanticRef:
    ref: str              # canonical name，不含 type:scope: 前缀
    kind: str             # point / point_ref / line / segment / function / fact / output / answer
    value_type: str | None = None  # Point / PointRef / Parabola / Equation 等 runtime 类型
    from_step: str | None = None  # 引用前序 step 产物时填 step_id
```

设计要点：

- `ref` 使用 canonical catalog 中展示给 LLM 的名称（如 `A`、`BD`、`angle_sum`、`parabola`），不含 `type:scope:` 前缀。
- `kind` 表达引用来源类别：题设 entity、题设 fact、前序 output、answer 等，不直接等同于 runtime value type。
- `value_type` 表达 runtime 类型，用于区分 `Point` / `PointRef`、`function` entity / `Parabola` output 等容易混淆的情况。
- `from_step` 用于前序产物消歧（当多个 scope 或多个 step 可能有同名 output 时）。

`SemanticReadResolver` 的输入不应直接依赖 Python `ProblemIR` dataclass 字段；当前 canonical authored fixture 会被投影进 `problem.data`。实现时应优先读取 runtime/projection 提供的 canonical payload（例如 `canonical_problem_payload(problem)` 或等价 helper），再构建 semantic catalog。

## Architecture

### Planner Layer

LLM 负责：

- 选择数学路线；
- 选择 function 或 macro；
- 连接数学上有意义的输入参数（使用 prompt 中显式展示的 semantic catalog 名称）；
- 指定期望输出的语义 name 和 scope；
- 保留必要的自然语言 reason，供教学层使用。

LLM 不负责：

- 写 `type:scope:name` 格式的完整 handle（由 resolver 自动拼接）；
- 写真实 ContextPath（由 compiler 编译）；
- 写 method invocation id；
- 写 step temp/output 路径；
- 写 promote 规则；
- 决定是否覆盖 locked fact；
- 构造底层 runtime scope。

### TypeChecker / Resolver

TypeChecker 负责：

- 检查 `call` 是否存在于当前 family 展开的 capability catalog；
- 检查 args 是否符合 function/macro input schema；
- 用三层消歧解析 semantic ref 到 canonical handle；
- 检查输出类型是否满足 `goal_type` 或 QuestionGoal；
- 检查 macro 是否优先于内部裸 method；
- 给 LLM 生成结构化、可操作的类型错误反馈。

Resolver 从"top-k 猜 capability"逐步转为"函数调用合法性检查 + 小范围修正"。对于缺失 call 或明显错误 call，仍可保留 top-k fallback。

**错误反馈质量提升示例：**

```text
# 当前
recipe_trial_step_failed: step=derive_E, stage=binding, code=binding_not_found

# 函数式
quadratic_from_constraints.curve_points expected list[Point], got PointRef: ref="N"
  hint: N is a PointRef; use a method that accepts PointRef, or resolve N's coordinate first
```

### Macro Expander

Macro Expander 负责把 recipe macro 展开成 function call subgraph：

```text
macro call
  -> internal function calls
  -> internal local values
  -> exposed returns
```

Macro 的内部 graph 由代码维护，不由 LLM 每次手写。这样可以避免把稳定套路的细节压力转嫁给 LLM。

### Compiler

Compiler 负责：

- 将 semantic ref 解析为 ContextPath；
- 补齐底层 method 所需的机械输入（`quadratic`、`x`、`all_coefficients` 等）；
- 生成 `MethodInvocation`；
- 生成 `StepPlan`；
- 生成 promote outputs；
- 注册 companion outputs；
- 保留 provenance，用于 explanation 和 visual。

首版 compiler 可以完全复用现有 `InvocationExecutor`，只新增 `FunctionalPlan -> StepPlan` 或 `SemanticReads -> canonical handles` 这一层。

### Runtime

Runtime 继续保持当前职责：

- method 无状态计算；
- executor 统一读写 context；
- validator 防止越权读写；
- checks 和 trace fragments 回流给结果层。

函数式编排不要求立即重写 executor。

## Capability Pack Impact

现有 Capability Pack 设计可以继续推进，但建议为函数式编排预留更稳定的抽象：

```python
CapabilityPackSpec(
    pack_id="quadratic_core",
    kind="base",
    functions=(...),
    macros=(...),
    adapters=(...),
    strategy_notes=(...),
)
```

映射关系：

```text
method_ids -> functions
step_recipes -> macros
method_binding_rules -> adapters / argument_resolvers
strategy_notes -> strategy_notes
```

短期可以继续保留 `method_ids / step_recipes / method_binding_rules` 字段；但文档和代码命名上应避免把 binding rules 设计成永久中心。长期中心应是 typed function/macro signature。

## Migration Strategy

### Phase 1: Semantic Reads（最高 ROI，目标是显著减少 handle 格式错误）

**目标**：LLM 的 `reads` 从写完整 handle 改为写 `semantic_reads`。

**边界**：Phase 1 只做 `semantic_reads -> canonical reads`，不改变 method binding，不替代 CandidateResolver，不做目标反推，不删除 legacy resolver。旧 `reads` 和新 `semantic_reads` 并存时，以新字段为主；旧字段继续走当前校验和修正路径。

**新增代码**：

1. `SemanticRef` dataclass（~40 行）
2. `SemanticReadResolver`（~200-300 行）：从 canonical payload 和 accepted prefix outputs 构建 semantic catalog，按 `ref + kind + value_type? + from_step?` 精确匹配，scope 可见性收窄，歧义时失败
3. StepIntent JSON schema 同时接受 `reads`（旧）和 `semantic_reads`（新），validator 自动解析
4. prompt 更新：显式展示当前题可引用的 semantic catalog，而不是要求 LLM 从题面自由发明 ref 名称
5. debug artifact：记录每个 semantic ref 解析出的 canonical handle、候选数量、失败原因

**暂不做**：

- 不简化 `produces`。`produces` 继续要求 canonical handle / valid_scope / output_type，避免把 scope、answer handle、created entity、companion output 的问题混进 Phase 1。
- 不删除 `CanonicalHandleAliasResolver`、NormalizationRule 或 `HandleResolver` 修正逻辑。只统计它们在 semantic_reads 模式下的触发下降情况。
- 不做目标反向推导和 method precondition filtering；这些等 FunctionSpec / MacroSpec 后再做。

**未来可废弃候选**：

| 模块 | 可废弃/收缩部分 | 前提 |
|------|--------------|------|
| `CanonicalHandleAliasResolver` | 大部分 alias 修正 | 所有 LLM 输出和 fixtures 迁移到 semantic_reads |
| `HandleResolver._narrow_overbroad_produced_facts` | produces scope 修正 | produces 简化方案单独完成并验证 |
| `_KnownPointCoordinateUtilityRule` | utility handle 归一化 | FunctionSpec/adapter 能稳定表达点坐标产物 |
| `_PointAnswerCoordinateRule` | answer/point fact 修正 | returns / answer output role 显式化 |
| `_AxisPointAliasRule` | 轴点 alias 归一化 | canonical catalog 明确暴露轴点 entity/output |

**验证**：用已有 recorded 南开、河西、西青、和平一模、和平二模数据做回归测试。先手动或脚本化把旧 reads 转成 semantic_reads，验证解析出的 canonical handle 完全一致；再记录 `unknown_read_handle`、alias 修正、repair loop 次数是否下降。

**预计工作量**：2-3 天

### Phase 2: FunctionSpec Facade

**目标**：从 MethodSpec 派生 FunctionSpec，给重点 method 增加语义 input schema。

- 保留现有 MethodSpec input slot。
- 新增 FunctionSpec payload 给 prompt 试验。
- 对比 function catalog vs method catalog 的 LLM 输出质量。
- 用 recorded fixtures 原型验证 args → binding selector 映射。

**预计工作量**：1 周

### Phase 3: FunctionalPlan IR + MacroSpec

**目标**：新增 FunctionalPlan IR 和 MacroSpec，实现完整的函数式编排。

- FunctionalPlan dataclass 和 JSON schema。
- 支持核心 function：二次函数、顶点、截点、距离、参数求解。
- 选择 1-2 个稳定 recipe 改成 macro graph：
  - `right_angle_equal_length_construct_and_select`
  - `broken_path_straightening_minimum_expression`
- `FunctionalPlan -> StepPlan` 编译器。
- MacroExpander 输出 function calls。
- CandidateResolver 从 top-k trial 逐步转为 typecheck-first。

**预计工作量**：2-3 周

### Phase 4: Legacy Cleanup

当所有题目 few-shot 迁移到新格式后：

- 从 prompt 中移除旧 `reads` 格式的说明。
- 废弃 `CanonicalHandleAliasResolver`、多条 NormalizationRule。
- 减少 family/pack binding rules 中的猜测逻辑。
- 逐步减少 binding selector 数量（目标：从 93 降到 ~25）。

**预计工作量**：1 周

## Advantages

### 更少隐式猜测

LLM 显式说明一个能力调用哪些语义参数，runtime 不必从 `reads` 和自然语言里大量推断 slot 绑定。

### LLM 输出更简单（不是更复杂）

当前 LLM 需要写：

```json
"reads": ["point:problem:A", "fact:problem:coefficient_relation", "function:problem:parabola"]
```

semantic_reads 只需要写：

```json
"semantic_reads": [
  {"ref": "A", "kind": "point"},
  {"ref": "coefficient_relation", "kind": "fact"},
{"ref": "parabola", "kind": "output", "value_type": "Parabola", "from_step": "solve_parabola"}
]
```

LLM 不需要知道 scope 前缀、namespace 规则或 handle 拼接格式。字段更多但心智负担更低。

前提是 prompt 明确展示可引用的 semantic catalog；否则 `ref` 名称仍可能漂移。

### 错误反馈更可操作

错误可以从：

```text
recipe_trial_step_failed
```

变成：

```text
quadratic_from_constraints.curve_points expected list[Point], got PointRef: ref="N"
```

这类反馈更适合自动修复和 prompt repair。

### Recipe 更可复用

Recipe macro 有明确输入、输出和内部 graph，不再主要依赖 `execution_strategy` 分支。新增题型时可以复用 macro，而不是复制 family binding 规则。

### Explanation / Visual 更稳定

函数调用图天然记录依赖关系：

```text
parabola -> vertex -> axis_point -> path_transform -> minimum_expression
```

教学层可以按 dependency graph 合并或展开步骤，减少重新猜角色的压力。

### 更容易做优化

FunctionalPlan 支持：

- 公共子表达式缓存；
- 局部重跑；
- 静态类型预检；
- 并行执行无依赖调用；
- 更清晰的 provenance。

### Pack 边界更清楚

Capability Pack 可以成为 typed capability module，而不只是 method list 和 prompt 分组。

## Disadvantages

### 需要维护双层 spec

MethodSpec 面向 runtime，FunctionSpec 面向 planner/compiler。两者需要保持一致，否则会出现"LLM 看到的能力"和"runtime 实际能力"漂移。

缓解方式：FunctionSpec 从 MethodSpec 自动派生，手动部分只有语义 input name 映射。CI 检查两者一致性。

### Macro graph 需要工程维护

Recipe 从 execution strategy 升级为 macro graph 后，结构更清晰，但也需要更多测试和版本管理。

### 初期迁移成本

需要新增 IR、schema、compiler、typechecker、prompt payload、debug artifact 和测试。Phase 1（semantic_reads）范围较小，预计新增 ~200-300 行代码，目标是先减少 handle 格式错误并收集可验证指标。

### 过度函数式化可能损害教学策略

数学解题不是纯计算流水线。有些步骤包含选择、观察、构造动机和教学表达。如果只追求函数调用图，可能丢失"为什么这样想"的策略信息。

缓解方式：FunctionCall 保留 `reason` 和 `strategy` 字段，供 ExplanationBuilder 使用。函数式编排管计算流，教学表达继续走 explanation pipeline。

### 仍然需要 dry-run

类型正确不等于数学正确。含参、候选点、范围约束、象限筛选、最值条件仍需要 runtime checks 和 prefix dry-run 验证。

## Design Risks

### 抽象层级过低

如果让 LLM 直接填底层 method input slot，职责会过重，输出也更脆。

缓解方式：LLM 只写 prompt catalog 中的语义参数（`ref + kind + value_type? + from_step?`），adapter 负责编译到底层 slot。

### 抽象层级过高

如果 function 过大，变成 `solve_problem` 级别的大能力，会失去可组合性和可验证性。

缓解方式：macro 只封装 2 到 4 个稳定 method，不覆盖完整题目路线。

### Pack adapter 冲突

同一个 function 在多个 pack 中可能有不同语境下的默认参数解析。

缓解方式：沿用 pack binding conflict policy；adapter 冲突在 family catalog 构造阶段 eager fail。

### Prompt token 上升

Function/macro signature 比 method_id 列表更长。

缓解方式：只展示 family 展开后的能力；base pack 简写，mechanism macro 详细展示。

### Semantic Reads 歧义率评估

以现有题目结构观察到的歧义风险示例：

| semantic_ref | kind | 歧义？ | 消歧方式 |
|--------------|------|--------|---------|
| `A` | point | 无 | 每题 `point:problem:A` 唯一 |
| `parabola` | output | 可能 | `from_step` + `value_type=Parabola` 消歧 |
| `angle_sum` | fact | 无 | 每题最多一条 |
| `N_coordinate_value` | fact | 无 | name 唯一 |
| `parabola` (多 scope) | fact | 可能 | `from_step` 消歧 |

实际歧义主要发生在同一 name 在不同 scope、不同 step 或不同 runtime 类型下有不同含义（如题设函数 entity、含参抛物线 output、定值抛物线 output）。`from_step` 和 `value_type` 可以解决大部分此类歧义；不能解决时应失败并反馈候选列表，而不是猜测。

## Design Decisions

以下问题在设计讨论中已有明确结论：

| 问题 | 结论 | 理由 |
|------|------|------|
| LLM 的 args 使用什么格式？ | Prompt catalog 中的 semantic ref：`ref + kind + value_type? + from_step?` | 降低 scope/namespace 格式错误；准确率需要 Phase 1 回归统计验证 |
| FunctionalPlan 替代还是扩展 StepIntent？ | 先作为 StepIntent 的可选字段（兼容层） | 允许新旧格式并存，渐进迁移 |
| FunctionSpec 从 MethodSpec 派生还是手写？ | 自动派生 + 手写语义 input name 映射 | 减少漂移风险 |
| goal_type 是否保留？ | 保留在 call 上 | Explanation/Visual 层需要 |
| recipe_hint 长期是否改名？ | 可改为 `capability_call`，但非优先事项 | Phase 1 使用 semantic_reads 不需要改名 |
| 为什么不用 hint 语义做 binding？ | 不可行 | 关键词匹配无法泛化，本质是二次 NLP |

## Open Questions

- Macro graph 用 Python dataclass、JSON DSL，还是直接用小型 builder API？
- ExplanationBuilder 应消费 FunctionalPlan graph，还是继续消费执行后的 trace/provenance？
- 多个 family 共享同一 FunctionSpec 时，adapter 冲突如何 eager fail？
- Phase 3 的 TypeChecker 是否应该作为独立模块，还是集成到现有 Validator 中？
- 未来是否需要支持条件分支（如 `if candidates.count > 1 then select else ...`），还是分支逻辑始终由 macro 内部 graph 固定？

## Recommendation

短期不应把函数式编排并入 Capability Pack Phase 1-4 的主线，以免同时改配置组织、prompt schema 和执行 IR。

建议路线：

1. **立即可做**：Phase 1（semantic_reads），~200-300 行新代码，2-3 天，目标是显著减少 handle 格式错误，并用 debug artifact 量化效果。
2. 继续完成 Capability Pack，把 family 瘦身。
3. 在 pack 设计中预留 `functions / macros / adapters` 术语。
4. Phase 2（FunctionSpec facade），用 recorded fixtures 原型验证。
5. Phase 3（FunctionalPlan IR），先在一个 family 上完整验证。

判断标准：

- 如果 Phase 1 能显著减少 `unknown_read_handle` 错误和 repair loop 次数；
- 如果 FunctionalPlan 能显著减少 binding fallback 和 recipe trial 失败；
- 如果错误反馈更容易让 LLM 自动修复；
- 如果 explanation/visual 的 role binding 更稳定；
- 如果新增 family 时更少复制 binding rule；

则值得逐步把 StepIntent 主链路迁移到函数式编排。
