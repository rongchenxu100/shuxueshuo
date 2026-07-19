# Family Capability Pack 升级方案

新增或修改 Capability Pack、Function 或 Macro 时，请同时遵守
`docs/capability-authoring-guide.md`。

## Summary

当前 `SolverFamilySpec` 同时承担了两类职责：

- 描述题型的核心几何机制，例如加权路径转化、等长射线降维、正方形路径降维。
- 维护该题型可用的通用 method 列表，例如二次函数求解析式、顶点、截点、代入参数、距离、交点。

随着题库扩大，第二类通用 method 会在多个 family 中重复出现，导致 family spec 变厚、能力边界重复维护、resolver 候选空间难以控制。

下一阶段应将架构升级为：

```text
Global Method Registry
  -> Capability Packs
  -> FamilySpec = base packs + mechanism packs + preferred recipes + strategy principles
  -> StepIntent recipe_hint
  -> CandidateResolver top-k
  -> TrialExecutor 验证执行
```

Family 不再“拥有”所有 method，而是声明本题型需要暴露哪些能力包，以及本题型最关键的几何转化机制。

本方案仍以当前 StepIntent / CandidateResolver / TrialExecutor 链路为主，不直接迁移到函数式编排。若后续引入函数式 Method/Recipe 编排，Capability Pack 应自然演进为 typed capability module：

```text
method_ids -> functions
step_recipes -> macros
method_binding_rules -> adapters / argument_resolvers
```

因此 Pack 重构要避免把 binding rules 设计成永久中心。短期 Pack 先解决 family 瘦身和候选池治理；长期它也应能承载 FunctionSpec、MacroSpec 和语义参数 adapter。

## Current Problem

当前 4 个 family 的外壳都属于“二次函数 + 几何构造 + 路径最值 + 参数反求”：

- `QuadraticPathMinimumSolver`
- `QuadraticWeightedPathMinimumSolver`
- `QuadraticEqualLengthRayPathMinimumSolver`
- `QuadraticSquareReflectionPathMinimumSolver`

它们真正不同的不是“是否二次函数”或“是否路径最值”，而是最值转化的核心几何机制：

| Family | 核心机制 |
| --- | --- |
| `QuadraticPathMinimumSolver` | 直角等腰构造、两动点路径降维、折线拉直 |
| `QuadraticWeightedPathMinimumSolver` | 加权路径通过辅助三角形转化为普通路径 |
| `QuadraticEqualLengthRayPathMinimumSolver` | 等长射线关系将两动点路径转化为单距离最值 |
| `QuadraticSquareReflectionPathMinimumSolver` | 正方形结构降维、轨迹线、将军饮马拉直 |

但这些 family 都反复需要：

- `quadratic_from_constraints`
- `quadratic_vertex_point`
- `quadratic_x_axis_intercept_point`
- `quadratic_y_axis_intercept_point`
- `distance_between_points`
- `parameter_from_expression_value`
- `evaluate_expression_at_parameter`
- `evaluate_point_at_parameter`

这些 method 应是全局通用能力，而不是每个 family 手工维护一份。

## Target Design

### 1. Global Method Registry

Method 是全局可复用的原子数学能力。

Method spec 应回答：

- 给定什么输入；
- 在什么前置条件下；
- 可以推出什么输出；
- 不解决什么问题；
- 是否支持含参表达式。

Method 不应该写入题号、problem_id、固定点名或某一道题的操作步骤。

示例：

```text
quadratic_from_constraints
quadratic_vertex_point
quadratic_x_axis_intercept_point
point_candidates_from_curve_point_condition
parameter_from_expression_value
evaluate_point_at_parameter
distance_between_points
line_intersection_point
square_adjacent_vertex_from_side
```

### 2. Capability Pack

Capability Pack 是一组可复用 method / recipe 的能力集合。它用于减少 family 重复配置，也用于 prompt 和 resolver 的第一层过滤。

Pack 不只是 method id 列表。首版 `CapabilityPackSpec` 应显式包含：

```python
CapabilityPackSpec(
    pack_id="quadratic_core",
    kind="base",  # base / mechanism
    method_ids=(...),
    step_recipes=(...),
    method_binding_rules=(...),
    strategy_notes=(...),
)
```

首版字段沿用当前 runtime 语义，方便无风险迁移。为后续函数式编排预留的长期命名如下：

```python
CapabilityPackSpec(
    pack_id="quadratic_core",
    kind="base",
    functions=(...),  # method_ids 的 planner-facing 形态
    macros=(...),     # step_recipes 的 typed macro 形态
    adapters=(...),   # method_binding_rules 的语义参数解析形态
    strategy_notes=(...),
)
```

Phase 1-4 不要求实现这些长期字段；实现时可以继续使用 `method_ids / step_recipes / method_binding_rules`。但新增设计和命名应尽量让这组映射成立，避免未来从 pack 到 function/macro catalog 时再次重构。

其中：

- `method_ids`：该 pack 暴露的原子能力。
- `step_recipes`：该 pack 暴露的标准动作。
- `method_binding_rules`：该 pack 语境下的默认/补充绑定规则，包含 input selector、expansion selector、companion output、prep invocation 等完整配置。
- `strategy_notes`：可选，给 prompt 合并使用的 pack 级策略提示。

长期对应关系：

- `method_ids` 对应 typed function 暴露边界。
- `step_recipes` 对应 typed macro 暴露边界。
- `method_binding_rules` 对应 semantic adapter / argument resolver。它们仍负责把 planner 语义参数编译到 runtime slot，但不应承担数学路线选择。
- `strategy_notes` 继续作为 pack 级策略提示。

同一个 method 可以被多个 pack 引用，但展开 family 时只注册一次。

去重和冲突规则：

- `method_id` / `recipe_id` 重复出现时，catalog 自动去重。
- base pack 与 mechanism pack 同时包含同一 method 时，prompt 中只展示一次。
- pack 之间不允许对同一 `method_id + input_slot` 提供互相冲突的 binding selector。
- 若多个 pack 对同一 method 的同一 slot 给出不同 binding，family 构造阶段直接报错。
- family override 可以覆盖 pack binding；pack 之间不能互相覆盖。
- `always_emit_outputs / companion_outputs / prep_invocations / expansion_selectors` 也参与冲突检测；同一 method 在多个 pack 中给出不同配置时，必须显式提升到 family override 或拆分 pack。

建议首批 pack：

```text
quadratic_core
  - quadratic_from_constraints
  - quadratic_vertex_point
  - quadratic_x_axis_intercept_point
  - quadratic_y_axis_intercept_point
  - quadratic_axis_x_intercept_point
  - point_on_parabola_at_x

parameter_solving_core
  - parameter_from_expression_value
  - parameter_from_segment_length
  - parameter_from_minimum_value
  - evaluate_expression_at_parameter
  - evaluate_point_at_parameter

coordinate_geometry_core
  - distance_between_points
  - line_intersection_point
  - translated_point

broken_path_minimum_core
  - broken_path_straightening_candidates
  - select_straightening_candidate
  - distance_between_points
  - broken_path_straightening_minimum_expression
```

说明：`quadratic_axis_x_intercept_point` 是“对称轴与 x 轴交点”能力，不是 `quadratic_x_axis_intercept_point` 的笔误。`distance_between_points` 同时出现在 `coordinate_geometry_core` 和 `broken_path_minimum_core` 是允许的；它展开后只展示/注册一次，binding 若一致则合并，若不一致则按上面的冲突规则处理。

机制 pack 只放真正区分题型的几何能力：

```text
weighted_path_transform_core
  - weighted_axis_path_triangle_transform
  - linked_broken_path_minimum_expression

equal_length_ray_reduction_core
  - equal_length_ray_point
  - equal_length_ray_path_reduction

square_path_reduction_core
  - square_path_dimension_reduction
  - quadratic_axis_parameterized_point
  - square_adjacent_vertex_from_side
  - point_candidates_from_curve_point_condition
  - parameterized_point_locus_line
  - line_locus_minimum_point

right_angle_equal_length_core
  - right_angle_equal_length_candidates
  - select_point_by_quadrant_constraint
  - right_angle_equal_length_construct_and_select
```

### 3. FamilySpec

FamilySpec 只表达题型层信息：

- 匹配规则：`pattern / problem_type`。
- base packs：通用二次函数、坐标几何、参数求解等基础能力。
- mechanism packs：该题型独有或优先的几何机制。
- preferred recipes：LLM 应优先选择的标准动作。
- strategy principles：中学生可理解的题型解题策略。
- pack strategy notes：从 base/mechanism pack 合并来的局部策略提示。
- binding overrides：当通用 binding 不足时的 family 局部补充。

目标形态示例：

```python
SolverFamilySpec(
    family_id="QuadraticWeightedPathMinimumSolver",
    match=FamilyMatchRule(
        patterns=("weighted-path-minimum",),
        problem_types=("quadratic_weighted_path_minimum",),
    ),
    base_packs=(
        "quadratic_core",
        "coordinate_geometry_core",
        "parameter_solving_core",
    ),
    mechanism_packs=(
        "weighted_path_transform_core",
        "broken_path_minimum_core",
    ),
    preferred_recipes=(
        "weighted_axis_path_triangle_transform",
        "linked_broken_path_minimum_expression",
    ),
    strategy_principles=(...),
)
```

`enabled_problem_ids` 这类准入门控仍属于 family 层。它表达的是“这个 family 目前允许哪些题进入生产/测试链路”，不是 pack 能力边界。

## Naming Rules

### goal_type

`goal_type` 是高层数学意图，不等于 method 或 recipe。

示例：

```text
derive_parabola
derive_vertex_point
derive_curve_intersection_point
derive_path_minimum_expression
derive_parameter
reduce_path_expression
```

### method_id

Method 是原子可执行能力。命名应表达“输出对象 + 来源条件”。

推荐格式：

```text
<domain>_<output_object>_<from/by>_<input_condition>
```

或：

```text
<action>_<object>_<at/from/by>_<condition>
```

示例：

```text
quadratic_from_constraints
quadratic_vertex_point
quadratic_x_axis_intercept_point
point_candidates_from_curve_point_condition
parameter_from_expression_value
evaluate_point_at_parameter
square_adjacent_vertex_from_side
```

禁止：

- 写题号或 problem_id；
- 写固定点名；
- 用 `solve_xxx_problem` 这类大而空的名字；
- 把多个阶段塞进一个 method。

### recipe_id

Recipe 是标准解题动作，可以由多个 method 组成。命名应表达“核心机制 + 动作目标”。

推荐格式：

```text
<mechanism>_<action>_<goal>
```

示例：

```text
equal_length_ray_path_reduction
broken_path_straightening_minimum_expression
curve_candidate_parameter_solve
right_angle_equal_length_construct_and_select
```

Recipe 不应覆盖完整题目路线；它只封装 2 到 4 个稳定可复用 method 的标准动作。

### recipe_hint

当前 StepIntent schema 中字段仍叫 `recipe_hint`。虽然它语义上既可能指向 recipe，也可能指向单个 method，但 Phase 1-2 不改字段名。

原因：

- 改名会影响南开、河西、西青、和平等现有 executable fixtures。
- 改名会影响 prompt、validator、normalizer、resolver 和真实 DeepSeek 输出稳定性。
- 现阶段更重要的是先把 pack / binding / metadata 结构理顺。

长期如果要改成 `capability_hint`，应作为独立迁移：

- schema 同时接受 `recipe_hint` 和 `capability_hint`。
- validator 将 `capability_hint` 归一化为内部 `recipe_hint`。
- 所有 fixtures 迁移后再移除旧字段。

语义：

```text
LLM 建议使用哪个 recipe/method。
代码将其作为强 hint，但不是最终裁决。
```

### semantic_reads

`semantic_reads` 是函数式编排路线中可提前插入的兼容实验：LLM 不写完整 `type:scope:name` canonical handle，而写 prompt catalog 中展示的 `ref + kind + value_type? + from_step?`，再由 resolver 精确还原成当前 `reads`。

它和 Capability Pack 的关系：

- Pack 决定当前 family 暴露哪些能力和哪些 canonical semantic catalog 项应进入 prompt。
- `semantic_reads` 只替代 LLM 手写 canonical handle，不改变 pack 展开、method binding、CandidateResolver 或 TrialExecutor。
- `semantic_reads` 不应混入 Pack Phase 1a/1b 的完成条件；它可以在 Pack 1a 后作为独立实验插入。
- 旧 `reads` 格式必须继续兼容，直到 recorded fixtures 和真实 LLM 输出稳定迁移。

## Candidate Resolution

未来 method 变多后，不能让 LLM 在全局 method 池里精确选择，也不能完全不给 LLM 能力菜单。

推荐三层过滤：

```text
全局 Method Registry
  -> Family / Capability Pack 粗过滤
  -> StepIntent 局部 top-k
  -> Trial Executor 试执行
```

候选排序优先级：

1. `recipe_hint` 精确命中 recipe/method。
2. `goal_type` 与 capability `solves` 匹配。
3. `produces[].output_type` 与 capability 输出类型匹配。
4. `reads` 中的 Entity / Fact 类型能绑定到 method input。
5. family preferred recipe 优先。
6. strategy / target 文本只作为低置信度补充信号。

若启用 `semantic_reads`，CandidateResolver 仍消费归一化后的 canonical `reads`；`semantic_reads -> reads` 是进入 validator/resolver 前的兼容解析步骤，不改变候选排序语义。

限制：

- 单 step top-k 控制在 3 到 5。
- recipe 优先于内部裸 method。
- 明确 hint 冲突时不能无限 fallback。
- prefix dry-run 成功才接受。
- 失败必须生成结构化 feedback 给 LLM。

Prompt 影响：

- Phase 1 保持当前 prompt 形态：`method_catalog` 和 `recipe_catalog` 仍展开为扁平列表，避免一次性改变 DeepSeek 输出分布。
- 若单独试验 `semantic_reads`，prompt 可以额外展示当前题可引用的 semantic catalog；这属于兼容实验，不改变 pack catalog 的扁平/分组策略。
- Phase 3 开始可以按 pack 分组展示 catalog，例如“通用二次函数能力”“正方形路径降维能力”“加权路径转化能力”。
- 分组展示时，mechanism pack 应排在 base pack 前面，帮助 LLM 优先注意本题型最关键的几何机制。
- 即使 prompt 分组，resolver 的候选池仍来自 pack 展开后的结构化 capability，不靠 prompt 文本分组做执行判断。
- Pack 数量增加后需要重新评估 token 预算；V1 仍只暴露当前 family 展开后的能力菜单，不展示全局 method 宇宙。

## Metadata Requirements

命名是给人和 LLM 看，代码不应主要靠字符串拆词判断能力。

Method / recipe spec 应显式声明结构化 metadata：

```python
solves = ("derive_x_axis_intercept_point",)
output_types = ("Point",)
input_fact_types = ("Parabola",)
domain_tags = ("quadratic", "intercept")
preferred_for = (...)
```

Recipe spec 应声明：

```python
method_sequence = (...)
output_aliases = (...)
goal_type = "derive_path_minimum_expression"
priority = "preferred"
```

Resolver 应优先使用 metadata 做候选扩展，而不是靠 method_id 文本匹配。

## Binding Rules

Method 是全局的，但 binding 可能有三层：

1. method default binding：通用输入绑定规则。
2. capability pack binding override：某个能力包中的通用补充。
3. family binding override：某个题型的特殊绑定。

解析优先级：

```text
family override
  -> pack override
  -> method default binding
```

例如 `quadratic_from_constraints` 是通用 method，但不同题里主参数可能叫 `a / b / c / m / t`。这个不应写死在 method 中，应由 canonical ProblemIR 的 symbol role 或 family/pack override 决定。

### Binding Conflict Policy

Pack binding 不是自由叠加。构造 family capability catalog 时必须做 eager validation：

- 同一 `method_id + input_slot` 在多个 pack 中只能有一个有效 binding selector。
- 若两个 pack 给出的 selector 完全相同，可以视为重复声明并合并。
- 若两个 pack 给出的 selector 不同，直接报配置错误。
- `expansion_selectors` 允许合并，但必须保持顺序稳定；同名 selector 去重。
- `always_emit_outputs` 允许合并，但同一 output key 的类型/target 必须一致。
- `companion_outputs` 对同一 output key 的 target 不一致时视为冲突。
- `prep_invocations` 对同一 trigger selector 给出不同 prep method 时视为冲突。
- family override 可以显式替换 pack binding，但必须在 debug/config report 中记录覆盖来源。

这条规则优先保证可解释性。不要让两个 pack 隐式竞争同一个 method slot。

### Strategy Principles

`strategy_principles` 仍以 family 层为主，因为完整解题策略来自题型结构，而不是单个 method。

但 pack 可以提供 `strategy_notes`：

- base pack notes：例如“每个 StepIntent 是可执行最小颗粒度”这类全局或基础能力提示。
- mechanism pack notes：例如“加权路径优先做辅助三角形转化，不要直接参数化求导”。

Prompt 构造时按顺序合并：

```text
global strategy rules
  -> base pack strategy_notes
  -> mechanism pack strategy_notes
  -> family strategy_principles
```

若内容重复，family 层保留最终表述。

### EntityStateResolver

Phase 1 不改 `EntityStateResolver`。

原因是它当前负责的是通用补位：从 entity handle 和 required runtime type 找唯一可见 fact/binding，例如 `point:* -> Point`、`function:* -> Parabola`、`symbol:* -> ParameterValue`。这类逻辑仍应保持全局。

如果未来某个 mechanism pack 需要特殊补位策略，再引入 pack-aware extension point；本轮不提前复杂化。

## Migration Plan

### Phase 1a: CapabilityPackSpec 骨架，不搬 binding

- 新增 `CapabilityPackSpec` 数据结构。
- 先只迁移 `method_ids / step_recipes / strategy_notes`。
- 将现有 family 的 method/recipe 机械拆成 base packs 和 mechanism packs。
- `StrategyPayloadBuilder` 仍展开成当前 `method_catalog / recipe_catalog`，不改变 prompt 形态。
- Family 展开后的 catalog 与当前 family 直接声明的 catalog 必须一致。
- 现有测试必须全部通过。

### Optional Interlude: semantic_reads 兼容实验

该步骤来自函数式编排路线，可在 Phase 1a 后插入，也可推迟到 Phase 2 后。它不是 Capability Pack 重构的硬前置条件。

- 新增 `SemanticRef` / `SemanticReadResolver`，将 LLM 的 `semantic_reads` 精确解析为当前 canonical `reads`。
- Prompt 额外展示当前题的 semantic catalog，但 `method_catalog / recipe_catalog` 保持现状。
- 不改变 produces schema，不删除 legacy handle resolver，不替代 binding rules。
- 用 recorded 南开、河西、西青、和平一模、和平二模验证解析结果与旧 `reads` 等价，并记录 `unknown_read_handle`、alias 修正和 repair loop 是否下降。

### Phase 1b: Binding rules 迁入 pack

- 将通用 method binding 迁到 method default binding 或 base pack。
- 将机制相关 binding 迁到 mechanism pack。
- family 只保留真正特殊的 override。
- 实现 pack binding 冲突检测。
- 实现 family override debug report。
- 仍不改变 StepIntent schema 和 prompt 字段。

### Phase 2: Method / Recipe metadata 补齐

- 给 MethodSpec 增加 `solves / output_types / input_fact_types / domain_tags`。
- 给 RecipeExecutionSpec 增加或补齐 output type metadata。
- 删除 resolver 中平行维护的 hard-coded output type override。
- 为后续 FunctionSpec facade 预留 metadata 来源；Phase 2 仍不要求 LLM 输出 typed function call。

### Phase 3: CandidateResolver 改为 pack-aware

- family 先展开 packs 得到候选池。
- step 内按 hint / goal_type / output_type / reads signature 做 top-k。
- TrialExecutor 负责最终选择。

### Phase 4: FamilySpec 瘦身

- family 中不再重复列通用 method。
- family 只保留 base packs、mechanism packs、preferred recipes、strategy principles、少量 binding override。
- 新题接入时优先判断是否只是新增 mechanism pack / recipe，而不是新增完整 family。
- 若需要把 `recipe_hint` 改名为 `capability_hint`，放到 Phase 4 之后作为独立 schema migration，不和 pack 重构混在一起。
- 若函数式编排验证通过，Phase 4 之后再单独推进 FunctionSpec / MacroSpec / FunctionalPlan，不与 pack 重构混在同一迁移批次。

## Test Plan

- Pack 展开测试：每个 family 展开后的 method/recipe catalog 与当前行为一致。
- Pack 去重测试：同一 method 出现在多个 pack 中时，catalog 只出现一次。
- Pack binding 冲突测试：两个 pack 对同一 `method_id + input_slot` 给出不同 selector 时构造失败。
- Family override 测试：family override 可以覆盖 pack binding，并在 debug/config report 中记录。
- Prompt 测试：catalog 内容不丢失，且 family strategy 仍进入 prompt。
- Prompt 分组测试：Phase 3 若启用 pack 分组展示，mechanism pack 排在 base pack 前；Phase 1 保持当前扁平 prompt 不变。
- semantic_reads 兼容测试（若启用）：semantic ref 解析出的 canonical reads 与 recorded 旧 reads 完全一致；歧义时返回候选列表，不做启发式猜测。
- Resolver 测试：hint 命中、hint 为空、hint 错误、top-k fallback 都能稳定工作。
- Binding override 测试：family override 优先于 pack override，pack override 优先于 method default。
- EntityStateResolver 回归测试：pack 化后实体状态补位行为不变。
- Gate 回归测试：`enabled_problem_ids` 仍只在 family 层生效，不进入 pack。
- Regression：
  - recorded 南开、河西、西青、和平一模、和平二模继续通过。
  - 真实 DeepSeek 测试不作为硬门槛，但用于观察 prompt 和候选召回质量。
  - `cd server && uv run pytest tests/solver -q`
  - `git diff --check`

## Assumptions

- Family 仍是第一层题型过滤，不引入 LLM family selector。
- LLM 继续看到 family 限定后的能力菜单，而不是全局 method 宇宙。
- `recipe_hint` 字段短期保留；长期若迁移为 `capability_hint`，必须独立完成 schema alias 兼容与 fixture 迁移。
- Method / recipe 的真实可执行边界仍由 TrialExecutor 和 runtime checks 验证。
- 能力包是配置组织方式，不改变 canonical ProblemIR、StepIntent schema 或 runtime execution semantics。
- 函数式编排是后续上层表达方式；Pack 重构只为它预留 `functions / macros / adapters` 的自然落点，不把 FunctionalPlan 作为本方案交付物。
