# Capability 创建规范

## 1. 目标

本文档规定如何为 Solver 新增或修改 capability，包括：

- 无状态数学 Method；
- 对外暴露的 FunctionSpec；
- 由多个 Method 组成的 Recipe / MacroSpec；
- CapabilityContract；
- Capability Pack 与 Family override；
- FunctionalPlan catalog、reconciliation、runtime 和 retry 所需的元数据。

唯一目标是：**让 LLM 只负责选择数学能力和连接语义证据，把类型、对象身份、
状态版本、作用域、输入绑定、结果闭合和错误定位交给确定性代码。**

新增 capability 不能只满足“某道题能跑通”。它必须同时回答：

1. LLM 在什么情况下应该选择它？
2. LLM 最少需要提供哪些语义输入？
3. 代码还会确定性补充哪些机械输入？
4. 它读取和写入哪些 StateSlot / Condition？
5. 输出属于哪个数学对象，代表创建、状态转移还是普通值？
6. 两次调用在什么条件下可以视为同一次计算？
7. 失败属于系统配置错误、确定性修复，还是应交给 LLM 的数学修复？

本文是新增 capability 的规范性入口。现有 legacy capability 可能尚未满足全部条款；
新增能力不得继续复制 legacy 缺口，修改旧能力时应按本文逐步收敛。

相关设计背景：

- `docs/family-capability-pack-upgrade-plan.md`
- `docs/functional-method-recipe-orchestration-design.md`
- `docs/llm-context-model-design.md`
- `docs/symbolic-target-closure-evolution-plan.md`

## 2. 单一真相源

Capability 的信息会被投影到多个层，但不能在多个层手工维护同一份定义。

```text
MethodSpecSource
  -> MethodSpec
  -> FunctionSpec
  -> Functional Capability Catalog
  -> Function adapter
  -> MethodInvocation

StepRecipeSpec + RecipeExecutionSpec + CapabilityContractSpec
  -> MacroSpec
  -> Functional Capability Catalog
  -> Macro adapter
  -> existing recipe compiler
```

权威来源如下：

| 信息 | 权威来源 |
| --- | --- |
| Method 输入、输出、纯度、结果形态 | `runtime/methods/<method>.py` 中的 `MethodSpecSource` |
| 通用 Method binding | `family/common_binding_rules.py`，再由 pack 引用 |
| Recipe 调用序列、输出角色、identity、write mode | `RecipeExecutionSpec` / `RecipeOutputAliasSpec` |
| StateSlot / Condition 读写契约 | `CapabilityContractSpec` |
| 通用能力归属 | Capability Pack |
| 题型路线偏好和真正的机制差异 | FamilySpec local override |
| FunctionSpec / MacroSpec | 从上述来源确定性投影，不手写第二份 |
| Functional catalog | 从 FunctionSpec / MacroSpec 投影，不手写 |
| `internal/method-specs/*.json` | 派生产物，不是源码真相源 |

禁止为了修一条测试，在 FunctionSpec、MacroSpec、catalog 或 compiler 中再复制一份
输入输出配置。

## 3. 先判断：Method 还是 Recipe

### 3.1 使用 Method / FunctionSpec

满足以下条件时使用 Method：

- 是一个可独立描述的原子数学运算；
- 输入和输出都有稳定 runtime type；
- 本身无状态，不读取全局变量；
- 不直接写 RuntimeContext；
- 相同 typed inputs 应得到相同结果；
- `InvocationExecutor` 可以作为唯一副作用边界。

示例：

- 两点距离；
- 中点坐标；
- 参数代入表达式；
- 根据已知约束求二次函数；
- 两直线交点。

### 3.2 使用 Recipe / MacroSpec

满足以下情况时使用 Recipe：

- 一个学生可理解的动作需要多个 Method；
- 中间结果不应该暴露给 LLM；
- 内部调用顺序和 wiring 是稳定机制；
- Recipe 整体具有明确的 StateSlot / Condition 读写语义。

示例：

- 生成直角等长候选点并按约束筛选；
- 生成折线拉直候选、选择方案并计算距离；
- 对曲线候选点逐一反求参数并筛选。

不要把“这道题需要连续调用三个能力”直接写成 Recipe。只有当这三个调用共同表达
一个可复用机制，而且内部结果不需要 LLM 决策时，才应封装。

## 4. Method 创建规范

### 4.1 Method 必须无状态

Method 只能消费传入的 typed inputs，返回 `StatelessMethodResult`。禁止：

- 在 Method 内扫描 RuntimeContext；
- 根据当前题号、Family 或 scope 改变算法；
- 解析 `strategy`、`reason` 或 description；
- 根据变量名猜对象身份；
- 直接写 answer、fact 或 point path。

Method 可以使用 SymPy，但必须显式检查：

- 分支数量；
- 自由符号；
- 定义域和约束；
- 输出类型；
- 唯一性。

### 4.2 MethodSpecSource 必填信息

一个 LLM 可见的 Method 至少应声明：

```python
MethodSpecSource(
    method_cls=SomeMethod,
    title="...",
    summary="...",
    solves=("...",),
    inputs={...},
    outputs={...},
    preconditions=(...),
    postconditions=(...),
)
```

`summary` 应回答“什么时候使用”，不能只是复述函数名。

当出现稳定误用时，增加泛化的 `do_not_use_when`：

```python
do_not_use_when=(
    "输入状态尚未建立时，不使用该能力直接猜测结果。",
    "该能力不负责生成其前置表达式。",
)
```

禁止出现：

- 题目来源和题号；
- 固定点名；
- expected answer；
- “下一步必须调用某个具体 capability”的固定链路。

### 4.3 输入设计

每个输入应能归入以下类别之一：

- `slot_read`：读取一个已有状态值；
- `condition_read`：读取一个结构化数学条件；
- `point_ref` / `object_ref`：读取对象身份；
- `symbol`：读取明确的 Symbol identity；
- `auto`：由代码唯一、机械地补全。

输入设计遵守 read-closed：

> MethodInvocation 的数学输入只能来自当前 call 显式引用的状态、声明式 auto arg，
> 或 contract 允许的唯一 companion state。

不得从全局可见状态中选择“看起来能算”的表达式、点、参数值或条件。

如果 Method 为旧 StepIntent/runtime 保留了兼容输入别名，但该别名不应成为
FunctionalPlan 的语义参数，应在 Method input source 中声明：

```python
"p1": {
    "type": "Point",
    "required": False,
    "functional_exposed": False,
}
```

这样 runtime contract 仍完整，Functional Capability Catalog 则只展示更稳定的
公开参数，例如 `curve_point / curve_points`。不得在 catalog builder 中按 method id
维护隐藏名单。

### 4.4 输出设计

每个输出必须有稳定 runtime type。多个不同语义输出必须使用不同 output key，不能用
一个模糊的 `Point many` 代替两个角色不同的 Point。

集合类型 return（例如 `PointList`、`SymbolList`、`Coefficients`）不能直接绑定到单个
对象或单值答案。它必须先由后续 capability 完成筛选、拆解或唯一性证明。旧
StepIntent 的兼容行为不能扩散到 FunctionalPlan 边界。

如果声明输出只在运行结果满足条件时存在，Method 必须同时返回解释缺失原因的 failed
check，例如 `candidate_selection_unresolved` 或
`candidate_selection_ambiguous`。`InvocationExecutor` 会把“请求了但未产生的输出”
报告为 `method_output_unavailable`，不得让 compiler 最终暴露裸 `KeyError`。

如果标量输出可能是开放表达式，也可能是闭合数值，应声明
`ScalarResultFormSpec`：

```python
scalar_result_forms={
    "distance": ScalarResultFormSpec(
        possible_forms=("open_expression", "closed_value"),
        description=(
            "仍含未确定参数时为 open_expression；不存在自由参数时为 "
            "closed_value。"
        ),
    )
}
```

结果形态由 runtime 的自由符号决定，不通过字符串外观判断。

对象状态使用另一组形态：

```text
open_state   # 对象的当前状态仍含自由符号
closed_state # 对象的当前状态已完全确定
```

当前 `Point` 和 `Parabola` 由 `contracts.default_result_form_spec()` 按 runtime type
统一获得对象形态声明，不允许每个 method 再复制一份配置。新增同类 Point/Parabola
capability 不需要手工声明；FunctionSpec 和 MacroSpec projection 会自动携带
`possible_forms`。

`ParameterValue` 默认是闭合参数值，不自动声明双形态。只有 capability 明确允许
“一个 Symbol 的当前值仍依赖其他被保留 Symbol”时，才为该 return 显式声明
`open_state / closed_state`。例如统一的 `quadratic_from_constraints` 可在
`target_parameter=b, free_parameters=[c]` 时发布开放状态 `b=1-c`；其
`object_ref` 必须仍是 Symbol `b`，`free_symbol_refs` 必须记录 Symbol `c`。

如果某个 return 面向学生时最多允许保留固定数量的独立参数，在显式 result form 中声明：

```python
ScalarResultFormSpec(
    possible_forms=("open_state", "closed_state"),
    description="...",
    max_independent_free_parameters=1,
)
```

这里限制的是约束系统化简后的独立自由度，不是表达式文本中出现的符号数量。
`b=1-c` 的独立自由度为 1；`b,c` 没有关系时才是 2。runtime provenance 是最终
权威，`return_expectations` 不能覆盖该预算。

只有 runtime 能完整提取自由符号的输出才能声明双形态。当前不要给以下 dict/container
状态直接加 `possible_forms`：

- `Line`；
- `Coefficients`；
- `PathTransformation`；
- `PointList` 或其他嵌套容器。

这些类型要先实现统一、递归的 free-symbol extractor，并补 runtime verification 测试，
再扩展结果形态覆盖。不能只修改 catalog 文案。

### 4.5 Symbol 闭包与学生复杂度

运行时符号闭包和学生解法复杂度是两个不同约束，不能合并成一条“最多只能有一个
未知数”的全局规则。

- 对 `Point`、表达式等中间状态，允许按 Symbol identity 做局部代入。例如一个点的
  坐标含 `c, t`，读取到 `c` 对应的 `ParameterValue` 后，可以只消去 `c`，继续保留
  含 `t` 的新状态。
- `ParameterValue` 必须与被代入 Symbol 的 `object_ref` 一致；不得通过 `*_value`
  名称或 reads 顺序猜身份。
- 只有进入面向学生的“由表达式反求参数”能力时，才要求实际表达式已经化到至多一个
  独立自由度。多自由符号的中间状态本身是合法的。
- 复杂度判断必须读取 compiler/runtime 中的实际值。Context 的
  `free_symbol_refs` 是保守依赖上界，可能仍包含已由上游运算消去的符号，不能用它
  提前拒绝调用。

需要该门禁的 Method 应声明：

```python
plan_transformer="validate_student_single_degree_of_freedom"
```

不要在 compiler 中按 method id 增加分支。新增同类参数求解 Method 只应声明同一个
transformer。若未来支持用显式方程组先确定性消元，应扩展共享 Symbol closure 原语，
并在消元后对实际表达式执行同一门禁；不得在单个 Method 中偷偷扫描全局条件。

二次函数约束统一使用共享 quadratic constraint solver。面向 LLM 的建立曲线、追加
曲线点/系数关系、保留自由参数和求目标系数都投影为
`quadratic_from_constraints`；旧的曲线点反求参数 Method 只可作为 internal runtime
primitive。新增二次函数约束形态时应扩展共享 request/result 与 contract，不得再增加
一个近义 LLM-facing capability。

当输入已经是同一 Function 对象的 materialized Parabola 时，共享 solver 必须先从当前
多项式状态恢复 `a,b,c` 的实际映射，再叠加新的 ParameterValue、曲线点和方程；不得把
已经从表达式中消失的系数符号重新当成 fresh unknown。显式 known coefficients 和
ParameterValue 始终覆盖从当前多项式投影出的系数值。

### 4.6 输入状态闭包边界

当 capability 的算法确实依赖整个对象状态，而不是只读取一个局部投影时，可在
`StateSlotPattern` 声明：

```python
input_closure_policy="closed_or_single_free"
```

当前策略包括：

- `any`：不限制输入状态的独立自由度；
- `closed_only`：输入必须无未定参数；
- `closed_or_single_free`：允许闭合状态或只含一个独立参数的开放状态。

例如顶点、横轴交点和曲线交点依赖完整抛物线，应先把 Function 模板物化为 closed 或
single-free Parabola。若当前 scope 中每个系数都有唯一可见值，代码可以确定性物化；
若只剩一个独立参数，也可以物化为 open state；两个以上独立参数则返回 typed issue。

不要把这个规则机械套到局部投影能力。求 y 轴截点只计算 `f(0)`，原函数中的其它
系数可能根本不进入输出；这类 capability 可以接受更宽的输入，但应对实际 return
声明输出参数预算。

前序 call return 在 reconciliation 时只有保守的 Symbol 依赖上界。constraint analyzer
可能把表面上的多个符号归一化成一个自由基，因此代码应在 runtime provenance 产生后
执行权威输入闭包校验，不能用 pre-runtime 符号并集提前拒绝。

## 5. CapabilityContract 创建规范

Contract 描述 capability 对 PlannerStateContext 的状态变换：

```text
slot_reads
condition_reads
slot_writes
condition_writes
dependency_policy
execution_status
```

Contract 是 prompt preflight、Function/Macro 投影、scope 检查、output type 推导和
调用等价判断的声明依据，不是 runtime value store。

### 5.1 StateSlotPattern

StateSlotPattern 至少考虑：

- `state_kind`；
- `runtime_type`；
- `object_kind`；
- `semantic_role`；
- `scope_policy`；
- `cardinality`；
- `required`；
- 写入时的 `write_mode`；
- 必要时的 `provides_semantic_roles`。

`semantic_role` 面向数学含义，例如：

```text
path_transformation
moving_locus
selected_target_point
path_minimum_expression
parameter_value
```

不要使用 runtime 路径、临时变量名或题目点名作为 semantic role。

### 5.2 ConditionPattern

ConditionPattern 用于“条件存在本身就是前提”的输入，例如：

- 点在曲线上；
- 两线段等长；
- 点在线段上；
- 两角之和等于定角；
- 给定最小值。

如果一个 ProblemIR fact 同时携带可计算值和条件语义，Context 可以为它建立多个视图，
由 arg contract 决定读取 Condition 还是 StateSlot。不要要求 LLM重复构造两份 fact。

### 5.3 `provides_semantic_roles`

`provides_semantic_roles` 分为两层，不能混为一谈：

1. input pattern 声明某个 arg **允许**由上游结果封装另一个角色；
2. return spec 声明某个具体输出 **实际**包含该角色。

消费端 contract 先声明 provider arg：

```python
_slot(
    "transformation",
    "PathTransformation",
    semantic_role="path_transformation",
    provides_semantic_roles=("moving_locus",),
)
```

生产端只有在输出 payload 和 runtime 实现确实携带完整轨迹依据时，才在
`RecipeOutputAliasSpec` 或 method contract write 上声明同一个 role：

```python
recipe_output_alias(
    "path_reduction.path_transformation",
    "PathTransformation",
    "path_transformation",
    provides_semantic_roles=("moving_locus",),
)
```

不能因为 runtime type 都是 `PathTransformation`，就推断所有实例都携带轨迹。
输入侧声明表示“可由该 arg 提供”，输出侧声明才是当前 call result 的实际证明。

该机制不是模糊 fallback。只有 contract 显式声明 provider role 时才能使用。

### 5.4 条件性输入闭包

当一个 arg 在 wire 上可省略，但能否省略取决于另一个输入的实际内容时，使用
`CapabilityInputClosureRequirement`：

```python
CapabilityInputClosureRequirement(
    semantic_role="moving_locus",
    provider_arg_roles=("path_transformation",),
    description="路径变换必须包含对应运动轨迹，或显式提供该轨迹。",
)
```

Function/Macro catalog 会把它投影为 LLM 可见的 `input_requirements`。只展示数学要求，
不展示 StateSlot、runtime path 或 provenance：

```json
{
  "input_requirements": [
    {
      "role": "moving_locus",
      "requirement": "路径变换必须包含对应运动轨迹，或显式提供该轨迹。"
    }
  ]
}
```

Reconciler 按以下顺序闭合：

1. LLM 已显式提供该 semantic role：接受；
2. provider call result 的 return metadata 证明已内嵌该 role：接受；
3. provenance 能唯一关联到一个类型、scope 均兼容的状态：确定性补齐；
4. 零个候选：`functional.arg_dependency_missing`；
5. 多个候选：`functional.arg_dependency_ambiguous`。

禁止从全局可见状态中选“唯一看起来合适”的值。即使 Context 中只有一条 Line，
只要它和 provider 没有 StateSlot/object provenance 关系，也不能自动绑定。

## 6. `explicit_args` 与 `context_closure`

`CapabilityDependencyPolicy` 当前有两种：

```python
Literal["explicit_args", "context_closure"]
```

### 6.1 默认使用 `explicit_args`

当 FunctionalPlan args 和它们引用的 CallResultRef 已足以确定所有数学输入时，使用
默认值 `explicit_args`。

典型情况：

- 两点距离显式读取两个 Point state；
- 参数代入显式读取表达式和 ParameterValue；
- Recipe 显式读取一个具有确定版本的 PathTransformation；
- 调用读取前序 call 的明确 return role。

### 6.2 何时使用 `context_closure`

只有同时满足以下条件时才使用 `context_closure`：

1. Wire args 只是概括性关系、目标 Condition 或对象引用；
2. adapter/compiler 必须从 Context 继续展开隐藏角色；
3. 隐藏角色会影响数学结果；
4. 相同 wire JSON 在不同调用时刻可能读取不同 StateSlot 版本；
5. reconciliation 后能够用 StateSlot、Condition、object identity 和 provenance
   完整描述这些依赖。

当前示例是 `two_moving_points_path_reduction`：LLM 只提交路径目标关系，但执行时还要
解析动点当前坐标、固定端点、长度关系和参数 provenance。求参数前后的相同 call 文本
可能分别消费参数化点和已求值点，因此不能在 wire 阶段合并。

```python
_recipe_contract(
    "two_moving_points_path_reduction",
    condition_reads=(_condition("path_minimum_target"),),
    slot_writes=(_slot("transformation", "PathTransformation"),),
    dependency_policy="context_closure",
)
```

### 6.3 不应使用 `context_closure` 的情况

不要因为以下原因使用它：

- capability 是 Macro；
- 输入数量多；
- output type 是 Point 或 Expression；
- binding 实现困难；
- 希望 compiler 可以随意扫描 Context；
- 想绕过缺失 arg 校验。

`context_closure` 只改变**调用等价判断的时机**，不放宽 read-closed，不允许全局猜测。

## 7. Recipe / Macro 创建规范

### 7.1 RecipeExecutionSpec 是内部调用图真相源

Recipe 必须通过 `RecipeExecutionSpec` 声明：

- `method_sequence`；
- `execution_strategy`；
- `intermediate_wiring`；
- `creates`；
- `output_aliases`。

MacroSpec 从 execution 和 contract 投影，不另写一份 returns。

### 7.2 RecipeOutputAliasSpec

每个对外 return 必须声明：

```text
output_key
runtime_type
semantic_role
state_kind
required / cardinality
identity_policy / identity_arg
write_mode
description（必要时）
```

内部辅助点、候选端点和题面目标点必须使用不同 semantic role。LLM 不得把内部 Point
return 绑定成任意 Point answer。

### 7.3 Macro 的纯度与共享

Macro 的 `is_pure/shareable` 应从以下事实派生：

- 所有内部 Function 都是 pure；
- 不创建外部实体；
- 不写 Condition；
- 不产生不可共享副作用；
- transition 的对象身份和源版本明确。

不要维护“可共享 recipe id 白名单”。

### 7.4 Internal Macro 与 LLM 暴露

当一个 Macro 只是另一个公开 Macro 的稳定内部阶段时，保留其
`execution_status="executable"`，并在 `CapabilityContractSpec` 中声明
`exposes_to_llm=False`。这样 MacroSpec、compiler、旧 recorded fixture 和 runtime
仍可复用它，但 Functional Capability Catalog 不会让 LLM 在两个职责重叠的 Macro
之间做无意义选择。

公开 Macro 应提供下游真正需要的 return 超集；内部阶段的同义 return 通过
`equivalent_to` 声明兼容 alias，不得要求 LLM 记忆两套端点或状态角色名称。

## 8. 对象身份与状态写入

类型相同不代表对象相同。每个可见 return 都必须选择合适的 identity policy。

### 8.1 StateIdentityPolicy

| Policy | 用途 |
| --- | --- |
| `preserve_input_object` | 输出是输入对象的新状态，例如参数代入后的同一点坐标 |
| `target_object` | 输出写入显式目标对象，例如求题面点坐标 |
| `derived_role` | 输出是 capability 派生的内部角色，例如拉直线段端点 |
| `value_only` | 输出没有独立对象身份，例如普通表达式或距离值 |

禁止仅根据 produced handle 名称推断 identity。

### 8.2 StateWriteMode

| Mode | 用途 |
| --- | --- |
| `create` | 创建对象的第一个派生状态 |
| `transition` | 推进同一对象已有 StateSlot 的版本 |
| `value` | 写入非对象值 |

合法 transition 必须证明：

- object_ref 相同；
- return 声明 `transition`；
- 新调用依赖旧 producer；
- scope 可见；
- 时间顺序正确。

同名 Point 不构成 transition 证明。

### 8.3 Semantic Lineage

`PlannerStateContext` 不只记录当前 handle，还要保存状态的语义来源：

```text
StateSemanticLineage
  semantic_roles
  evidence_tags
  object_roles
  source_state_slot_ids
```

这四类信息的职责不同：

- `semantic_roles` 表示当前状态自身扮演的角色，例如
  `path_minimum_point_1`；
- `evidence_tags` 表示该状态可用于哪些确定性验证；
- `object_roles` 表示状态内部提到的对象角色，例如
  `moving_object -> point:scope:P`；
- `source_state_slot_ids` 记录该状态由哪些精确版本派生。

`provides_semantic_roles` 只描述“该值内部可提供哪些输入角色”，不能替代
`semantic_roles`。两者不得混用。

传播规则必须由 return 声明决定：

- `preserve_input_object + transition` 继承 `identity_arg` 对应输入的全部 lineage；
- `derived_role` 默认只创建当前 return 的 semantic role；
- `target_object` 保留目标对象身份，但不继承无关输入角色；
- 初始 lineage 只能从 ProblemIR 的结构化 entity/fact 字段建立，不能解析
  `description`、strategy 或 reason 文本。

例如，一个拉直端点经过一次或多次参数代入后，仍应保留原来的 endpoint role；新构造
的 Point 则不能因为读取了该端点就继承 endpoint role。

当普通 Function return 只有在输入证据闭合时才能获得更强的语义角色，使用
`StateLineageClosureSpec`，不要按 method id 在 verifier 中补标签。例如两点距离只有
在输入分别承担两个拉直端点角色、携带同一 witness，并来自同一已验证 producer 时，
才能提升为 `path_minimum_expression`；普通两点距离仍只是 `distance`。

### 8.4 Object Role Projection 与 Identity Constraint

当一个状态内部声明“它属于哪个数学对象”时，使用
`StateObjectRoleProjectionSpec`：

```python
StateObjectRoleProjectionSpec(
    role="moving_object",
    source_arg="path_transformation",
    source_object_role="moving_object",
)
```

当 capability 的多个输入或输出必须属于同一对象时，使用
`StateIdentityConstraintSpec`：

```python
StateIdentityConstraintSpec(
    left="arg:moving_locus.object_role:subject",
    right="arg:minimum_point_1.object_role:moving_object",
    relation="same_object",
    description="轨迹与路径端点必须属于同一个动点对象。",
)
```

selector 只允许引用声明式 arg/return 对象身份。`left` 是本次调用中待校验的实际绑定，
`right` 是 capability 的权威身份锚点；graph retry 只回退 left 的错误 producer 及其下游，
不清除已经验证的 right 侧子图。

对象约束的执行边界：

1. catalog preflight 校验 selector 和公开 arg/return 是否存在；
2. reconciliation 在 projection 前使用 resolved StateSlot lineage 校验；
3. compiler/runtime 对结构化 payload 的 canonical object ref 再次校验；
4. contract 与 runtime 漂移属于 `planner_configuration_error`，不能交给 LLM retry。

禁止因为当前 scope 中只有一个 Line 或 Point 就自动重绑。身份无法唯一证明时，应返回
typed issue，让 LLM修改数学路线或语义输入。

当 `target_object` return 未显式绑定，而 `same_object` constraint 的另一侧能从
resolved arg lineage 唯一得到对象时，reconciliation 可以反向补全 return binding。
该补全必须同时满足：约束直接引用该 return、arg selector 唯一解析、所有适用约束得到
同一 object_ref。不得用类型唯一、名称相似或全局搜索代替这份证明。

### 8.5 Analyzer 修复必须回写 Candidate

需要读取真实 RuntimeContext 数值后才能完成的确定性修复，应放在声明的
`constraint_analyzer`，不要在 reconciler 复制数学求解。例如 analyzer 把 LLM 选择的
自由参数基从多个候选收敛为空或唯一 Symbol 时，必须同时返回
`FunctionArgBindingRepair`：

- runtime invocation 使用 analyzer 归一化后的输入；
- replay 按 canonical source handle 把同一修复写回 FunctionalPlan；
- Context、stable graph、retry baseline 和最终学生计划只保存修正后的 candidate；
- 无法把 analyzer 输出唯一映射回原 Functional arg 时，不得静默改写。

新增 analyzer 应复用这一 sidecar 协议。只修改 MethodInvocation 而不回写 candidate，
会造成“执行正确、计划和 retry 仍保留错误参数”的双重真相源。

若自由参数基需要参考下游约束，reconciliation 只能读取结构化调用图：上游公开的
`free_parameters` SymbolList、下游直接消费关系，以及 Condition 中唯一的 Symbol
identity。所有直接消费者指向同一 Symbol 时可以确定性重基并记录 repair；零个或多个
候选时必须交给 retry，不能从变量名、strategy 或题目文本猜测。

## 9. 调用等价、合并与跨 Scope 共享

调用合并依赖语义证据，不依赖文本相似度或运行结果相等。

最终 resolved signature 至少考虑：

- capability id；
- resolved arg role；
- StateSlot id 和 source StateSlot versions；
- Condition id；
- object identity；
- Symbol / ParameterValue provenance；
- prior-call return identity；
- return identity policy 和 write mode；
- 显式 answer/object binding。

### 9.1 禁止用实际结果相等判断调用等价

两个调用偶然算出相同坐标或数值，不代表它们是同一个数学状态：

- 不同参数分支可能在一个样本值上相等；
- 不同对象可能具有相同坐标；
- 不同推导来源对讲解和 retry 有不同意义；
- symbolic equality 可能忽略定义域或分支条件。

Runtime 结果用于验证，不用于猜测 canonical call identity。

### 9.2 Placement

确认调用等价后，placement service 才能：

- 选择 canonical owner；
- 计算 execution scope；
- 计算每个 return 的 valid scope；
- 重写 alias CallResultRef；
- 让 Context、retry 和 explanation 使用 canonical call。

LLM 不负责把公共调用手工移动到父 scope。

## 10. 结果形态与 `return_expectations`

当 return 声明 `possible_forms` 时，FunctionalPlan 可以提供可选
`return_expectations`。它是 LLM 的意图和数据流记忆标记，不是 runtime 事实。

```json
{
  "return_expectations": {
    "path_minimum_expression": "closed_value"
  }
}
```

对象状态示例：

```json
{
  "return_expectations": {
    "axis_point": "closed_state"
  }
}
```

### 10.1 当前声明覆盖

显式标量声明的权威来源是 MethodSpec：

| Function capability | Return | Forms |
| --- | --- | --- |
| `distance_between_points` | `distance`、`evaluated_distance` | `open_expression / closed_value` |
| `evaluate_expression_at_parameter` | `evaluated_expression`、`evaluated_minimum_expression` | `open_expression / closed_value` |
| `linked_broken_path_minimum_expression` | `minimum_expression`、`dynamic_parameter_expression` | `open_expression / closed_value` |

Macro 不维护第二份配置，而是从内部 Function output 投影。当前包括但不限于：

- `broken_path_straightening_minimum_expression`；
- `path_minimum_by_straightened_distance`；
- `equal_length_ray_path_reduction`。

对象状态声明按 runtime type 自动覆盖：

- 所有 Function/Macro 的 `Point` return：`open_state / closed_state`；
- 所有 Function/Macro 的 `Parabola` return：`open_state / closed_state`。

截至五题 FunctionalPlan parity catalog，本规则覆盖 28 个 capability 的 42 个唯一
return：12 个标量 return、26 个 Point return、4 个 Parabola return。这个数字是审计
快照，不是手工白名单；当前 catalog 中没有遗漏未声明形态的 `Expression`、
`MinimumExpression`、`Point` 或 `Parabola` return。新增 capability 后应通过 catalog
测试重新计算。

### 10.2 确定性处理链

所有声明了 `possible_forms` 的 return 共用同一处理链：

1. wire validator 只接受四个枚举值：`open_expression / closed_value /
   open_state / closed_state`；
2. elaborator 删除不兼容 form domain 或固定形态 return 上无意义的 expectation，并记录
   deterministic repair，不把机械错误交给 LLM；
3. reconciler 校验 return role、answer binding、调用合并冲突，并把 expectation 保存到
   canonical call；
4. projection sidecar、stable graph、retry baseline 和 preserve policy 必须保留 expectation；
5. scalar `closed_value` 可以使用当前 call 已读的 ParameterValue 做确定性 closure；
6. object `closed_state` 不自动插入求参或代入调用，只验证 LLM 所声明的预期；
7. runtime 从实际输出提取自由符号，决定真实 result form；
8. 期望 closed、实际 open 时生成 `functional.return_form_mismatch`；
9. 期望 open、实际 closed 时记录 `result_form_closed`，并把实际 closed form 回写到
   canonical FunctionalPlan、stable graph 和 retry baseline，不阻断成功结果；
10. 未填写 expectation 时保持兼容，代码不会仅因缺少标记而失败。

若 result form 还声明 `max_independent_free_parameters`，runtime 无论 LLM 是否填写
expectation 都必须执行该预算门禁。预算超限是 capability 适用性问题，不允许通过
改写 `open_state` 或 `open_expression` 静默放行。

代码只能自动推断能够证明的 `open_state`。显式 projected free symbols 为空不等于已经
closed，因为 method 或上游对象可能携带尚未投影的 companion Symbol。`closed_state`
最终必须以 runtime provenance 为准。

### 10.3 同一对象的状态收敛

`return_expectations` 本身不授权覆盖已有对象。第二次写同一 StateSlot 只有满足以下
条件，才能由代码提升为 `dependency_refinement` transition：

- object identity、runtime type 和 StateSlot 相同；
- 新调用的 source StateSlots 覆盖旧调用来源；
- dependency object refs 覆盖旧依赖；
- projected free symbols 是旧版本的严格子集；
- runtime 执行后，实际 free symbols 仍是旧版本的严格子集。

因此 `M(c) -> M(c0)` 可以成为合法状态推进；若重新计算后仍含同一自由符号，则不能
借助 `closed_state` 标记强行覆盖，必须保留为 retry 问题。

### 10.4 标量闭合约束

确定性闭合遵守：

1. expectation 随 Functional projection sidecar 进入 compiler；
2. 只消费当前 call 明确读取的 ParameterValue；
3. ParameterValue 必须通过 provenance 映射到 Symbol identity；
4. closure function 从 FunctionSpec typed signature 中唯一发现；
5. 不按 method id、参数名或题目文本 dispatch；
6. runtime 最终用剩余自由符号验证实际形态。

如果没有唯一闭合函数或出现同一 Symbol 的冲突值，属于配置或 typed binding 错误，
不能静默选择。如果没有足够参数值，则保留开放结果并形成 call-level retry issue。

## 11. Binding 与编译边界

### 11.1 通用 binding 下沉到 Pack

跨 Family 重复、语义相同的 Method binding 应放入 capability pack。Family local rule
只保留真正的 override。

如果 Family local rule 与 pack rule 完全一致，应删除本地副本，避免它遮蔽后续 pack 更新。

### 11.2 Adapter primitive 应按语义注册

推荐：

```text
read_type:Point
condition role resolver
parameter value by Symbol identity
coefficients_by_symbol aggregation
point_list aggregation
```

Functional public aggregate arg 若要降低为 runtime 的固定输入槽，必须在
`MethodBindingRuleSpec.aggregate_input_bindings` 声明，例如把 `curve_points` 依次降低
为 `p1 / p2`。Compiler 必须消费 reconciliation sidecar 中已经选定的 StateSlot 版本，
不能再从扁平 `reads` 按顺序猜测；容量不足或类型漂移属于配置错误。

Recipe 已声明的 `input_aliases` 同时是 direct Function 的参数别名来源。例如
`endpoint_1 -> distance_between_points.p1` 会由 catalog 确定性投影，elaborator 只做
wire 名称归一化并记录 repair。不得在 prompt、normalizer 或 method-id 分支再维护一份
别名表。

避免：

```text
if method_id == "..."
if point_name == "F"
if "missing parabola" in error_message
```

若一个新能力需要 compiler 特殊分支，先判断能否抽成：

- FunctionSpec metadata；
- CapabilityContract；
- typed adapter primitive；
- plan transformer hook；
- Macro execution strategy。

只有无法声明化且确实属于稳定数学机制时，才增加专用 recipe compiler strategy。

## 12. Catalog 与 Prompt 规范

Functional catalog 只展示 LLM 做数学选择需要的信息：

- `capability_id`；
- `title`；
- `use_when`；
- 可选 `do_not_use_when`；
- explicit args 的短名称、接受类型、cardinality；
- public returns 的角色、类型、binding mode；
- 必要的 args/returns `desc`；
- 支持双形态的 return 的 `possible_forms` 与必要说明。

不得展示：

- canonical handle；
- RuntimeContext path；
- binding selector；
- StateSlot id；
- internal-only return；
- family id、problem id 或题目来源；
- StepIntent 字段。

`desc` 只在名字和类型不足以消除歧义时添加。不要把完整实现说明复制进 prompt。

参数类型和 cardinality 不能代替数学角色说明。出现以下任一情况时，必须提供参数级
`desc`：

- 同一 capability 同时存在单值与多值入口，例如 `curve_point / curve_points`；
- 两个参数接受相同 runtime type，但承担不同职责，例如多个已知系数与单个待代入参数；
- 参数要求已计算状态而非仅有对象引用，例如“已知交点”不能只是 `PointRef`；
- `optional` 只在可证明条件下才能省略，例如 provider state 已携带所需轨迹；
- `Equation`、`Condition`、参数范围等在数学上不可互换。

跨参数约束必须声明在 typed spec 中，并由 catalog 自动投影为
`input_requirements`。例如 `distinct_arg_groups` 应同时驱动 reconciler 校验和 LLM-facing
说明；不要只在 validator 中实现一份、再手写一份 prompt 文案。

`use_when` 只回答“何时选择该能力”，参数级 `desc` 回答“每个输入在数学上是什么”，
`do_not_use_when` 记录稳定出现的意图级误用。三者不能互相替代。新增说明不得改变
semantic role、identity policy、write mode 或 output key；文案优化与执行契约修改应分别
评审。

## 13. 错误、确定性修复与 Retry

### 13.1 Planner configuration error

以下问题应在调用 LLM 前失败：

- exposed capability 没有 executable contract；
- Function 缺 adapter；
- Macro output alias 与内部 output 不一致；
- required auto arg 没有 resolver；
- aggregate arg 没有 aggregator；
- dual-form output 没有唯一 closure function；
- generic recipe 有 catalog 但没有 binding/compile path。

这些不是 LLM 能修复的问题。

### 13.2 确定性修复

只有在结果唯一且不改变数学路线时才自动修复，例如：

- 删除固定形态 return 上无意义的 expectation；
- 删除由 contract provider 已覆盖、且类型不兼容的冗余 optional arg；
- 补充唯一 auto arg；
- 规范化单值/数组；
- 重写 alias call；
- 合并已经由 StateSlot/provenance 证明等价的纯调用。

确定性修复必须记录 repair event，并保持幂等。

### 13.3 交给 LLM 的修复

只有数学选择或证据不足时才反馈 LLM，例如：

- capability 不适用；
- required semantic state 缺失；
- 多个合法候选无法唯一选择；
- 目标结果仍含未解决自由参数；
- answer return identity 不匹配；
- 当前调用图缺少必要数学步骤。

Repair ticket 应描述缺失的 state role/type/object identity 和被阻塞的 calls。只有 contract
preflight 得到唯一可执行 producer 时，才附带候选 capability guidance。

## 14. Anti-patterns

### Anti-pattern 1：为一张试卷新增点名判断

错误：

```python
if handle.endswith(":F"):
    ...
```

正确：从 fact type、object role、StateSlot identity 或 contract 读取。

### Anti-pattern 2：根据自然语言错误消息驱动逻辑

错误：

```python
if "parabola" in message and "missing" in message:
    ...
```

正确：diagnostic 直接输出结构化 `code / missing_state_types / object_ref`。

### Anti-pattern 3：扫描全局状态替 LLM 选择数学证据

即使全局只有一个 Expression，也不能在当前 call 未读取它时偷偷绑定。

### Anti-pattern 4：同类型即同对象

两个 Point 可能坐标相同但身份不同；两个 ParameterValue 可能属于不同 Symbol。

### Anti-pattern 5：相同结果即相同调用

调用等价必须由输入状态版本和 provenance 证明。

### Anti-pattern 6：Method、Contract、Adapter 三处复制配置

应建立投影或 adapter primitive，而不是靠人工同步。

### Anti-pattern 7：用 `context_closure` 掩盖缺失输入

`context_closure` 不是全局搜索开关，也不替代 required arg。

### Anti-pattern 8：Prompt 写固定 method 链

Prompt 应描述能力契约和修复工单，不应绑定某一题的黄金路径。

## 15. 新增 Capability 的推荐流程

### Step 1：定义数学边界

- 写清楚输入、输出、前置条件和不负责的内容；
- 判断是 Method 还是 Recipe；
- 判断是否已有更通用能力可以扩展。

### Step 2：实现 Method 或 RecipeExecutionSpec

- Method 保持无状态；
- Recipe 声明内部调用图和 output aliases；
- 不先写 prompt 或 normalizer 补丁。

### Step 3：声明 CapabilityContract

- 声明 slot/condition reads 和 writes；
- 指定 semantic roles；
- 指定 identity policy 和 write mode；
- 判断 dependency policy；
- 必要时声明 provider roles。

### Step 4：接入 Pack

- 通用能力进入 base pack；
- 机制能力进入 mechanism pack；
- Family 只保留路线偏好或真正 override。

### Step 5：完成 Function/Macro 投影 preflight

- FunctionSpec / MacroSpec 完整；
- adapter 可编译；
- catalog 只暴露 executable + complete capability；
- prompt-safe payload 不泄漏内部路径。

### Step 6：编写 typed tests

先写 synthetic、无题目字母依赖的单元测试，再跑 recorded fixture 和真实 opt-in。

### Step 7：检查 retry 和 explanation

- typed issue 能定位到 call/arg/return；
- stable graph 不包含 alias call；
- explanation 使用 canonical call graph；
- 学生步骤不会重复展示共享计算。

## 16. PR Checklist

### Architecture

- [ ] 已明确选择 Method 或 Recipe，并说明原因。
- [ ] 没有新增平行的 FunctionSpec/MacroSpec 手写配置。
- [ ] 通用 binding 位于 pack/common rule，而不是复制到多个 Family。
- [ ] 没有题号、problem id、固定点名或 expected answer 硬编码。
- [ ] 没有通过 strategy/reason/description 或错误文本驱动执行逻辑。

### Inputs

- [ ] 每个输入都有稳定 semantic role 和 runtime type。
- [ ] required / optional / auto 边界明确。
- [ ] auto arg 有唯一 deterministic resolver。
- [ ] aggregate arg 有注册 aggregator。
- [ ] binding 满足 read-closed，没有全局状态偷读。
- [ ] `context_closure` 的使用满足第 6 节全部标准；否则保持 `explicit_args`。
- [ ] provider role 只通过 `provides_semantic_roles` 声明，不靠名字猜测。
- [ ] input pattern 的潜在 provider 与具体 return 的实际 provider 分开声明。
- [ ] 条件性必需输入使用 `CapabilityInputClosureRequirement`，没有在 compiler 中按 capability id 特判。
- [ ] 自动闭合只接受 provenance-linked unique candidate，不扫描全局唯一值。

### Outputs

- [ ] 每个 public return 有唯一 semantic role。
- [ ] output type 可由 Method/Recipe spec 唯一确定。
- [ ] identity policy 正确。
- [ ] write mode 正确。
- [ ] transition 有来源版本和依赖证明。
- [ ] 状态转移需要继承语义时，已声明并测试 semantic lineage。
- [ ] `semantic_roles` 与 `provides_semantic_roles` 没有混用。
- [ ] 结构化状态承载的 object roles 已通过 projection 声明。
- [ ] 必须同一对象的 args/returns 已声明 identity constraints。
- [ ] identity constraint 的 left 是待修复绑定，right 是权威身份锚点。
- [ ] internal Point 不会被绑定成题面 Point answer。
- [ ] 双形态标量声明了 possible forms 和说明。
- [ ] Point/Parabola 使用 type-level result form，不复制 per-method 配置。
- [ ] 依赖完整对象状态的 arg 声明了合适的 input closure policy；局部投影没有被过度限制。
- [ ] 面向学生的开放 return 如有独立参数预算，已声明并由 runtime provenance 验证。
- [ ] 新增其他双形态 runtime type 前，已实现完整 free-symbol extractor。
- [ ] 期望 closed/实际 open、期望 open/实际 closed 均有测试。
- [ ] 同一 StateSlot 的 refinement 同时验证 projected 与 runtime 自由符号严格减少。

### Sharing and Scope

- [ ] 纯度由 Method/Recipe 结构派生，不是 capability id 白名单。
- [ ] 等价签名包含 StateSlot versions、identity 和 provenance。
- [ ] 不通过 runtime 结果相等合并调用。
- [ ] sibling scope 的共享经过 LCA 和输入可见性检查。
- [ ] alias calls 不进入 stable graph、retry 或学生步骤。

### Catalog and Retry

- [ ] `use_when` 非空且描述数学目标。
- [ ] 稳定误用已用泛化 `do_not_use_when` 说明。
- [ ] catalog 不暴露 handle、runtime path、selector 或内部 return。
- [ ] 配置错误在调用 LLM 前失败。
- [ ] deterministic repair 有事件记录且幂等。
- [ ] LLM retry ticket 不包含 fixed method chain。

### Tests

- [ ] Method runtime 正常、边界和多解/欠定测试。
- [ ] FunctionSpec / MacroSpec JSON serializable。
- [ ] Contract 与 execution outputs 一致。
- [ ] Adapter 成功与 typed failure 测试。
- [ ] scope visibility 和 identity 测试。
- [ ] 多次 transition 后 semantic roles、object roles 和 source slots 不丢失。
- [ ] 不同对象的类型兼容状态会产生 typed identity issue，且不会自动重绑。
- [ ] runtime payload 与 projected object role 漂移时产生 configuration error。
- [ ] 应合并与不应合并的调用测试。
- [ ] `context_closure` 至少覆盖两个不同 StateSlot 版本。
- [ ] open/closed result form 测试。
- [ ] finalizer / elaborator 幂等。
- [ ] recorded fixtures 回归。
- [ ] 真实 opt-in 不出现 configuration error。

## 17. 推荐验证命令

根据改动范围选择测试，最低建议：

```bash
cd server
uv run pytest \
  tests/solver/test_family_spec.py \
  tests/solver/test_strategy_planner_function_specs.py \
  tests/solver/test_strategy_planner_macro_specs.py \
  tests/solver/test_strategy_planner_functional_plan.py -q

uv run pytest tests/solver -q
git diff --check
```

真实 DeepSeek opt-in 用于检验 prompt 和真实输出分布，不替代 synthetic contract tests。

## 18. 当前迁移状态

- FunctionalPlan 仍通过 canonical StepIntent projection 接入现有 runtime。
- FunctionSpec 和 MacroSpec 是 typed facade，runtime 最终仍执行 MethodInvocation。
- Legacy StepIntent binding/normalizer 仍保留兼容，但新增 Functional capability 不应依赖
  新的文本启发式补丁。
- 当前只有 `two_moving_points_path_reduction` 使用 `context_closure`。新增声明应经过
  本文第 6 节和 PR Checklist 审核。
- Runtime 结果用于执行验证、自由符号检查和 answer verification，不用于调用等价判断。

随着 FunctionalPlan 成为唯一链路，可以逐步删除 legacy binding fallback；但在删除前，
Function/Macro contract、adapter、recorded fixture 和真实 opt-in 必须先达到行为等价。
