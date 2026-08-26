# 路径最值 Macro 重构

状态：F5-F4.1、F5-F4.2、F5-F4.2R、F5-F4.3A、F5-F4.3B与
F5-F4.3C已完成；当前下一阶段是F5-F4.3D正方形路径迁移。

统一运行时权威链记录在
[F5-F4.2运行时权威收敛](problem-extraction-context-implementation-plan.md#f5-f4-2-runtime-authority-convergence)。
本文聚焦 Planner 可见的路径最值 Macro 契约、内部数学搜索，以及 F5-F4.3
的迁移顺序。

## 1. 目标边界

Family识别只发生一次，并生成不可变的`FamilyCapabilityBundle`。该bundle以唯一的
`capabilities[]`保存`kind=function|macro`的公共能力；Macro Capability额外挂接semantic
blueprint及展开依赖。Macro失败后的Goal retry继续使用同一bundle和同一signature，不再执行
第二次“按Goal筛选Capability”。如果为控制prompt长度而分阶段展示Function Capability
schema，那只是同一bundle的projection，不是新的能力选择。

### 1.1 统一Capability术语

`Capability`是LLM-facing catalog entry的公共外壳，不是Function、Macro之外的第三种执行
对象。公共分类固定为：

```text
FunctionalCapability
  kind = function
    source = FunctionSpec
    implementation = MethodSpec / runtime Method

  kind = macro
    source = MacroSpec
    implementation = 1..N FunctionalPlanFragment candidates
```

- `Function Capability`表示一个可被LLM显式组合的确定性语义动作，当前通常由一个
  `FunctionSpec.method_id`lower为底层Method；
- `Macro Capability`表示成熟解法入口，可以通过blueprint和candidate provider展开为多个
  Function step组成的fragment候选；
- `Method`只属于runtime primitive层，不是Planner Capability kind，不直接进入prompt；
- “可组合语义Function”统一改称“可组合Function Capability”。它是
  `FunctionalCapability(kind=function)`的用途描述，不是第二份catalog或新的模型；
- 历史`CapabilityContractSpec.kind=method|recipe`只反映旧实现来源，与公共
  `FunctionalCapabilityKind=function|macro`重名冲突。F4.3B必须原子迁移为同一公共分类；
  若代码仍需记录实现来源，使用独立的内部字段，不得继续占用`kind`。

Planner默认优先选择高层数学能力，并引用题面中的Entity与Fact。已知Macro可以把成熟
解法压缩成一个step；LLM也可以使用同一份`FunctionalPlan content/v3`和同一bundle中的
Function显式组合解法。不存在第二套路径策略DSL，也不存在只供Macro理解的路径类型系统。

LLM 不负责：

- 组装带 runtime view、隐藏 target 或物理 path 的内部 Method 调用；
- 区分 Entity identity、latest state 或 exact result；
- 选择运行时状态版本；
- 传递内部 `PathTransformation`、runtime辅助端点或Method wiring；
- 重现 shadow、F5-C、checkpoint、winner clean replay 等执行机制。

改变数学思路的选择仍属于 LLM；同一思路内部有限、机械且可验证的角色排列、
直达、反射和端点变化属于 Macro/runtime；对象视图、状态版本和执行地址属于
compiler/runtime。

目标链路为：

```mermaid
flowchart TD
  F["FamilyCapabilityBundle<br/>一次选择并固定signature"]
  L["LLM每个provider attempt<br/>只输出一个普通Plan"]
  D{"当前Goal的authoring选择"}
  M["一个Macro step<br/>附可选角色hint"]
  P["Macro candidate provider<br/>生成1..N个Fragment候选"]
  S["隔离shadow runtime<br/>逐个验证Macro候选"]
  W["一个winner"]
  X["winner物化为普通Function steps"]
  A["LLM显式Function steps"]
  G["现有TypedExecutionGraph与F5-C"]
  R["现有step execution / checkpoint / repair cone"]
  O["标准输出与普通step evidence"]

  F --> L --> D
  D --> M --> P --> S --> W --> X --> G
  D --> A --> G
  G --> R --> O
```

`FunctionalPlanFragment`只存在于Macro候选生成和shadow选择阶段。LLM每个provider attempt
只author一个普通Plan，不声明fragment；Macro winner选中后也不保留第二套fragment执行协议，
而是确定性转换为普通Function steps。二者从普通step进入TypedExecutionGraph时汇合。

Macro候选中的LLM角色hint只是优先尝试的数学假设，不是source authority。若存在唯一的
runtime-valid替代项，代码可以纠正；若存在多个非等价的有效候选，则必须以prompt-safe
诊断要求LLM消歧，不能静默猜测。显式Function step若数学验证失败，则进入下一次Goal
semantic retry，由LLM返回新的Goal steps；runtime不会在同一provider response中
替LLM创造第二套开放解法。

## 2. 已完成的基础

### 2.1 F5-F4.1：参考 Macro

`equal_length_ray_path_reduction` 在F4.1曾作为第一条完整竖切：

```text
四个结构化 Fact
  -> 有界角色搜索
  -> shadow runtime 验证
  -> winner clean replay
  -> minimum_expression + PathMinimumWitness
```

这里的`PathMinimumWitness`只描述F4.1退出时的历史形状，不是当前production。F4.3B已将
其表达内容迁到普通step evidence与Macro expansion provenance中的标准Entity、Condition、
Expression、Scalar、verification outcome和provenance记录，并物理删除旧类、schema和同步
入口；Explanation/Visual直接从这些标准证据投影教学字段，不再保留同名兼容模型。

它证明了以下边界可行：

- 角色唯一时不向 LLM 暴露角色字段；
- 角色有歧义时只暴露候选受限的数学实体；
- 错误 hint 不进入最终 F5-C binding 或 provenance；
- 一步Macro调用不要求LLM author辅助构造、SAS等价证明、合法域和最值点；它们进入
  witness。F4.3B后，同一数学链也必须能由LLM使用公开Function Capability显式展开为Plan fragment；
- Explanation 与 Visual 从 verified witness 读取证据，不解析 trace 文本。

### 2.2 F5-F4.2：运行时权威收敛

Macro 搜索已经移动到 per-call F5-C finalization 之前：

```text
TypedExecutionGraph
  -> Macro pre-binding search
  -> MacroPreparationAuthority
  -> finalized FunctionalProblemCallBinding
  -> MethodInputReadAuthority
  -> derived v1 execution IR
  -> transaction / checkpoint v4 / VerifiedExecution v2
```

shadow 候选彼此隔离，winner 必须从干净分支重放；恢复时复用 checkpoint 中的
winner、exact input version 和 write signature，不重新搜索候选，也不重新选择
latest state。

### 2.3 F5-F4.2R：Method input selector 退役

生产 Method input 已不再通过字符串 selector 扫描 Context。当前单向链为：

```text
MethodInputBindingSpec(source | derivation)
  -> FunctionalProblemCallBinding
  -> MethodInputReadAuthority
  -> compiler 机械投影 runtime path
  -> MethodInputViewResolver
  -> Method
```

Entity、StateVersion、Condition、CallResult 和 Macro prepared role 均在 F5-C
阶段确定。compiler 与 runtime 缺少 typed authority 时 fail loud，不得回退到
`FunctionAdapterRegistry._select()`。

F4.3A已经删除四条companion字符串selector和standalone debug角色provider。后续仍需处理：

- Path family 中仍存在的几何helper与公开内部Path类型；
- F4.1参考实现中的路径专用candidate/witness兼容模型必须迁入F4.3B通用外壳；
- 尚未迁移的Macro当前必须保持`direct`，不能提前宣称`runtime_search`。

## 3. 当前能力清单

现有七个 `StepRecipeSpec` Macro：

1. `right_angle_equal_length_construct_and_select`
2. `curve_candidate_parameter_solve`
3. `two_moving_points_path_reduction`
4. `broken_path_straightening_and_select`
5. `path_minimum_by_straightened_distance`
6. `broken_path_straightening_minimum_expression`
7. `equal_length_ray_path_reduction`

另外三个 Method 实际承担了 Macro 级策略，也必须在同一阶段迁移：

1. `square_path_dimension_reduction`
2. `weighted_axis_path_triangle_transform`
3. `linked_broken_path_minimum_expression`

若只迁移七个已注册 Macro，而保留后三个 Planner-facing Method，
`PathWitness`、辅助点和内部连线仍会从另一入口泄漏到 Plan。

### 3.1 五题端到端使用矩阵

以当前五份recorded FunctionalPlan及其compile manifest为权威基线，路径相关调用图为：

| 题目 | 当前公开调用链 | 实际内部Method链 | F4.3目标 |
|---|---|---|---|
| 南开一模 | `right_angle_equal_length_construct_and_select` -> `two_moving_points_path_reduction` -> `broken_path_straightening_minimum_expression` | 候选构造/筛选；两动点降维；拉直候选/选择/距离 | 保留构造Macro；后两段替换为`coupled_segment_endpoint_replacement_path_minimum`，并提供通用`single_moving_point_path_minimum` |
| 河西一模 | `curve_candidate_parameter_solve` -> `weighted_axis_path_triangle_transform` -> `linked_broken_path_minimum_expression` | 曲线筛选/参数求解；加权三角形构造；联动折线最值 | 保留曲线筛选Macro；后两段合并为`weighted_axis_path_minimum` |
| 西青一模 | `weighted_axis_path_triangle_transform` -> `linked_broken_path_minimum_expression` | 与河西相同的两段加权路径链 | 合并为`weighted_axis_path_minimum` |
| 和平一模 | `equal_length_ray_path_reduction` | 等长辅助点构造 -> 距离计算，并由pre-binding search确定角色 | 保留公开capability ID，迁入F4.3B通用fragment与witness协议 |
| 和平二模 | `square_path_dimension_reduction` -> `broken_path_straightening_minimum_expression` | 正方形三段降维；拉直候选/选择/距离 | 合并为`square_relation_path_minimum` |

这五题证明了三种不同情况，不能统一按“名称相近”删除：

1. **真正的调用图重复**：拆分入口与合并入口表达同一串Method；
2. **公共边界过细**：两个不同数学阶段有先后依赖，但不应要求LLM传递内部Path结果；
3. **独立数学机制**：虽然也使用候选或距离，但适用结构和证明义务不同，应保留为独立Macro。

### 3.2 去重与退役矩阵

当前三条拉直能力存在严格的调用图包含关系：

```mermaid
flowchart LR
  C["broken_path_straightening_candidates"]
  S["select_straightening_candidate"]
  D["distance_between_points"]
  A["broken_path_straightening_and_select"]
  B["path_minimum_by_straightened_distance"]
  M["broken_path_straightening_minimum_expression"]

  A --> C --> S
  B --> D
  M --> C
  S --> D
```

即：

```text
broken_path_straightening_and_select
  = candidates + select

path_minimum_by_straightened_distance
  = distance_between_points

broken_path_straightening_minimum_expression
  = candidates + select + distance_between_points
```

因此退役分类固定为：

| 分类 | 旧能力 | 处理 |
|---|---|---|
| F4.3B可直接删除 | `broken_path_straightening_and_select` | 五题和few-shot均不消费，且已不向LLM公开；删除独立Recipe/compiler分支，底层通用Function按需保留 |
| F4.3B可直接删除 | `path_minimum_by_straightened_distance` | 只是`distance_between_points`的一层Macro别名；显式Plan直接调用Function Capability |
| F4.3C迁移后删除 | `two_moving_points_path_reduction` | 删除同名一Method Macro与策略Method；其数学证明拆为普通Function/predicate并由`coupled_segment_endpoint_replacement_path_minimum`展开 |
| F4.3D迁移后删除 | `broken_path_straightening_minimum_expression` | C完成后只允许作为和平二模迁移期临时依赖；D完成后由`single_moving_point_path_minimum`/`square_relation_path_minimum`取代 |
| F4.3D迁移后删除 | `square_path_dimension_reduction` | 删除Planner-facing策略Method；正方形关系证明进入透明Macro fragment |
| F4.3E迁移后删除 | `weighted_axis_path_triangle_transform` | 与下一项共同被`weighted_axis_path_minimum`取代 |
| F4.3E迁移后删除 | `linked_broken_path_minimum_expression` | 删除策略Method边界；投影、距离和约束验证拆为通用Function/predicate |
| 保留并接入通用内核 | `right_angle_equal_length_construct_and_select` | 独立的候选构造与方向筛选机制，不属于路径拉直重复 |
| 保留并接入通用内核 | `curve_candidate_parameter_solve` | 独立的曲线候选筛选与参数闭合机制，不属于加权路径重复 |
| 保留公开ID | `equal_length_ray_path_reduction` | 当前完整pre-binding runtime-search参考实现；只替换内部专用模型，不删除语义入口 |

“删除”指删除旧Capability/Method契约和专用lowering，不是丢弃数学算法。中点、中位线、
直角三角形、距离等价、投影垂足和距离计算必须先提取为LLM与Macro都能使用的普通Function
Capability或predicate，再物理删除策略Method。禁止把旧Method改名后继续作为Macro黑箱。

除语义能力去重外，F4.3B还必须关闭声明层重复：同一`capability_id`只能有一个
`MacroDefinition`事实源。Capability pack与family-local不得各保存一份完整
`StepRecipeSpec`再依赖覆盖顺序合并；family差异只能通过蓝图参数、适用条件或bundle投影表达。

## 4. 中间类型边界

### 4.1 从 Planner wire 删除

以下题型专用类型和物理执行细节只属于 Macro 内部执行证据：

- `PathTransformation` / `PathWitness`；
- `PathCandidate`；
- `straightened_endpoint_1` / `straightened_endpoint_2`；
- 仅用于连接两个内部 Method 的运动轨迹；
- 内部 Method 的 call id、input name 与 return name。

它们不得出现在 Planner prompt、response schema、`FunctionalPlan` 或 repair wire。
没有题面身份并不意味着数学对象必须隐藏。LLM显式展开解法时，反射点、构造点、交点、
辅助直线和验证成功后发布的Condition可以使用普通基础数学类型，作为scope-local派生绑定
进入`FunctionalPlan`；被禁止的是路径题专用包装和内部Method连线，而不是中间数学对象本身。

### 4.2 公开结果只使用基础数学类型

最值表达式可以被下游参数求解消费，因此仍允许使用`StepResultRef`。现有wire暂时保留
`minimum_expression: MinimumExpression`，但`MinimumExpression`只是一层兼容的语义
角色标记，其runtime基础值仍是`Expression`或`Scalar`，不能据此继续增加
`PathObjective`、`PathEquivalence`、`AttainmentEvidence`等题型专用公共类型。

所有高层路径Macro当前统一公开：

```text
minimum_expression: MinimumExpression
```

结果是 `open_expression` 还是 `closed_value` 由 runtime result form 决定，不再用
`path_minimum_expression`、`evaluated_path_minimum_expression` 等多个名字表达同一语义。
新Function优先返回`Entity`、`Condition`、`Expression`、`Scalar`及其标准集合；题目中的
“最小值”“最大值”“轨迹”等含义由Function output role与Goal binding表达，不建立一套
对应每类题型的Python/JSON结果模型。

### 4.3 Scope-local派生数学对象

一个Function step产生的普通数学对象若会被后续step、retry、Explanation或Visual再次使用，
LLM应当为该return声明一个可读的scope-local变量名，而不是在每个消费者中重复书写
`StepResultRef`。这不是新的解题DSL，而是现有`return_bindings`增加一个通用的派生绑定
variant。目标wire形状为：

```json
{
  "call_id": "construct_G",
  "capability_id": "construct_point_on_ray_at_reference_distance",
  "args": {
    "anchor": {"ref": "C", "kind": "point"},
    "ray_point": {"ref": "D", "kind": "point"},
    "reference_point": {"ref": "B", "kind": "point"}
  },
  "return_bindings": {
    "point": {
      "ref": "G",
      "kind": "derived",
      "domain_type": "Point"
    },
    "distance_equality": {
      "ref": "CG_eq_CB",
      "kind": "derived",
      "domain_type": "Condition"
    }
  }
}
```

该声明在scope authority中形成通用`ScopedDerivedBinding`：

```text
ScopedDerivedBinding
  semantic_ref
  domain_type
  owner_scope
  origin = step_output
  producer_step_id / return_name
  problem_owned = false
  exact_result_authority
```

固定语义如下：

- `Point`、`Line`、`Function`、`Symbol`等Entity在Plan装配时获得scope-local
  `MathObject`身份，producer成功后才写入首个StateVersion；失败候选或失败transaction
  不得留下可见对象或ghost write；
- 谓词Function的Condition别名可以预先声明，但只有底层Method返回true且runtime按exact
  input authority验证成功后才注册Condition；Plan声明本身不能冒充数学事实；
- 下游step使用普通SemanticRef，例如`G`或`CG_eq_CB`。TypedExecutionGraph仍根据
  `producer_step_id + return_name`建立精确依赖，F5-C和checkpoint在sidecar中pin
  `CallResultId`、`StateVersionId`或`ConditionId`；名字只负责可读性，不拥有source authority；
- 派生绑定只在owner scope中producer之后及其后代可见，不向祖先或sibling泄漏。需要被多个
  sibling Goal共享的中间对象必须由LLM或Macro模板直接声明在它们的LCA scope，代码不得提升；
- 派生名不得与同scope或可见祖先中的ProblemIR Entity、Fact及其他派生绑定冲突。同名对象在
  不同sibling scope可以存在，但必须拥有不同的fully-qualified SemanticRef；
- retry保留frozen producer的派生身份和exact result；editable producer被替换时，其派生绑定
  随repair cone重新建立。checkpoint restore不得重新命名、重新找producer或重新选择latest；
- Macro模板使用的`aux_1`与LLM写出的`G`可以在canonicalization中做alpha-renaming。fragment
  等价比较依据scope、producer、return role、类型、Condition和runtime结果，不依据局部变量拼写；
- 真正一次性且不需要在数学叙述中出现的匿名值仍可使用`StepResultRef`。需要重复消费、进入
  retry诊断或进入Explanation/Visual的中间Entity/Condition应优先声明派生名。

和平一模显式fragment因此可以写成：

```text
construct_G.point             -> derived Point G
construct_G.distance_equality -> derived Condition CG_eq_CB
prove_congruence.condition    -> derived Condition CBN_congruent_CGM
derive_equal_side.condition   -> derived Condition BN_eq_MG
rewrite_objective.expression  -> derived Expression reduced_objective
intersect_OG_BC.point         -> derived Point P
verify_attainment.condition   -> derived Condition minimum_attained_at_P
```

后续Function直接引用`G`、`BN_eq_MG`、`reduced_objective`和`P`。Macro展开与LLM显式展开
都必须生成同一种派生绑定；它们的可读名字可以不同，但canonical authority和运行证据必须等价。

### 4.4 搜索证据与普通step证据

F4.1历史实现曾为路径Macro生成非Planner-facing的`PathMinimumWitness`。当前实现已经改为
通用候选搜索记录和标准step execution evidence。只有Macro/runtime candidate provider使用
搜索外壳：

```text
VerificationOutcome
  passed
  predicate
  expected / observed
  diagnostic

SearchCandidate[TFragment]
CandidateEvaluation[TResult]
CandidateSearchReport[TResult]

MacroExpansionRecord
  winner candidate
  generated step ids
  export map
  search / expansion signature
```

`TFragment`固定为普通`FunctionalPlanFragment`，`TResult`只由标准基础数学值和引用组成。
不得为路径最值、正方形、加权路径或后续特殊题型再定义新的candidate或evaluation外壳。
Macro内部的角色选择、机械解法变化和达到方式都只是不同fragment payload，统一由同一候选
协议执行。LLM普通steps不进入候选集合；Macro winner物化后也只产生普通step evidence。

`FunctionalPlan` 只保存求解意图。实际输出与证据进入：

```text
VerifiedFunctionalPlanExecution
  canonical_plan
  plan / planning-context / revision authority
  checkpoint_id
  scope-shaped execution tree
    step status
    actual outputs
    typed evidence
```

retry只接收普通step diagnostic及Macro search report的prompt-safe摘要；Explanation与Visual
从生成step的标准输出、Condition、provenance和`MacroExpansionRecord`生成领域展示，不把
搜索或教学投影重新塞回Plan。现有`PathMinimumPromptWitness`作为兼容projector逐步退役，
不再向其他family复制。

## 5. 各 Macro 的目标输入输出

### 5.1 `right_angle_equal_length_construct_and_select`

当前：

```text
input:  right_angle_equal_length Fact
output: selected_target_point
```

目标：

```text
input:
  right_angle_equal_length Fact
  target Point（仅 Goal 无法唯一确定目标身份时）
  optional direction / quadrant / symbol constraint Facts

output:
  selected_point

internal:
  普通step evidence + MacroExpansionRecord（标准Point与Condition输出）
```

候选构造与分支验证由 runtime search 完成，LLM 不选择象限实现路径。

### 5.2 `curve_candidate_parameter_solve`

当前：

```text
input:
  candidates: PointList
  parabola
  target_point
  point_on_curve Fact?
  symbol_constraint Fact?

output:
  selected_curve_point
  parameter_value?
  solved_parabola?
```

目标仍允许真正可复用的匿名 `PointList`，但常见的“构造候选再筛选”应封装为
family composite Macro：

```text
input:
  candidate-producing Fact 或 authenticated anonymous candidate result
  parabola Entity
  target Point
  point_on_curve Fact
  optional symbol constraint Fact

output:
  selected_curve_point
  parameter_value?
  solved_parabola?

internal:
  普通step evidence + MacroExpansionRecord（标准Entity、Condition与Scalar输出）
```

### 5.3 耦合线段端点替换路径

当前公开 `two_moving_points_path_reduction -> PathWitness`，目标替换为：

```text
coupled_segment_endpoint_replacement_path_minimum

input:
  path_minimum_target Fact
  moving-point membership Facts
  length/proportion binding Fact
  optional moving-point role hint

output:
  minimum_expression
  minimizing_configuration?（仅 Goal 明确询问时）

internal:
  path reduction
  locus recovery
  straightening
  endpoint construction
  distance / attainment proof
  普通step evidence + MacroExpansionRecord
```

`two_moving_points_path_reduction` 不再作为 Planner 可见的独立阶段。

公共Macro ID按数学机制命名，不按动点数量命名。该Macro只覆盖“两个动点分别位于
具有公共端点的线段上，长度或比例绑定能够证明两动点线段等于已有固定端点到剩余动点
线段”的结构；它不宣称覆盖所有双动点路径题。`coupled_moving_points`、
`dimension_reduction`、`fixed_endpoint_replacement`和`path_minimum`只作为检索与
Family匹配标签。等长射线、正方形和加权辅助点虽然也可能把双动点降为单动点，仍分别由
对应数学机制的Macro处理，最终共享普通轨迹、反射、距离和达到性Function。

### 5.4 拉直与距离

`broken_path_straightening_and_select` 目标是内部共享搜索引擎，不再有
Planner-facing 契约。

`path_minimum_by_straightened_distance` 目标是内部距离原语。只有当两个端点本身就是
题面数学输入时，才允许保留直接距离能力；公开返回统一为 `minimum_expression`。

### 5.5 单动点路径

当前 `broken_path_straightening_minimum_expression` 同时公开 scheme、辅助点、端点和
表达式。目标替换为：

```text
single_moving_point_path_minimum

input:
  path_minimum_target Fact
  moving-locus Fact
  optional moving-point role hint
  optional parameter Entity

output:
  minimum_expression
  minimizing_point?（仅 Goal 明确询问时）

internal:
  straightening candidates
  selected construction
  endpoints
  attainment proof
  普通step evidence + MacroExpansionRecord
```

### 5.6 正方形路径

当前 `square_path_dimension_reduction -> PathWitness`，目标替换为：

```text
square_relation_path_minimum

input:
  path target Fact
  square Fact
  midpoint Fact
  center Fact
  relevant locus Facts
  optional moving-point role hint

output:
  minimum_expression
  minimizing_configuration?（仅 Goal 明确询问时）

internal:
  square reduction
  locus derivation
  straightening
  distance / attainment proof
  普通step evidence + MacroExpansionRecord
```

### 5.7 加权路径

当前公开两步链：

```text
weighted_axis_path_triangle_transform
  -> auxiliary_point / path_transformation / auxiliary_locus

linked_broken_path_minimum_expression
  -> minimum_expression
```

目标合并为：

```text
weighted_axis_path_minimum

input:
  path_minimum_target Fact
  weight/binding Fact
  axis-membership Fact
  dynamic-constraint Fact
  optional moving/fixed role hints

output:
  minimum_expression

internal:
  weighted triangle construction
  auxiliary point / locus
  path equivalence
  linked minimum calculation
  普通step evidence + MacroExpansionRecord
```

题目给出的最小值仍应作为后续参数求解输入，不能冒充路径结构 Fact。

### 5.8 等长射线路径参考实现

`equal_length_ray_path_reduction` 保持公开 capability ID，输入固定为：

```text
path_minimum_target
equal_length_condition
point_on_segment
point_on_ray
```

四个 Fact 无法唯一确定结构时，才动态暴露：

```text
anchor
reference_point
ray_point
fixed_point
```

公开返回：

```text
minimum_expression
segment_minimizing_point / ray_minimizing_point（仅 Goal 需要时）
```

内部搜索角色、等长辅助点、SAS与路径恒等式、直达/反射/端点候选、合法域与可达性，
并将标准Point、Condition、Expression与验证结果保存在生成step的普通执行证据中，
`MacroExpansionRecord`只补充winner与step来源。Explanation/Visual从二者生成展示projection，
不再消费路径专用witness类型。

### 5.9 Macro 透明性与开放组合

Macro 是成熟解法的可复用快捷方式，不是系统唯一掌握该解法的黑箱。每个生产
Macro 必须满足 `Macro Transparency Contract`：

```text
MacroDefinition
  public_contract
  semantic_blueprint
  functional_plan_fragment_templates[]
  candidate_provider
  acceptance_contract
```

Family在进入Planner前只构造一次：

```text
FamilyCapabilityBundle
  family_id / bundle_signature
  capabilities[]                       # kind=function|macro的唯一事实源
  macro_blueprints_by_capability_id    # 只允许Macro Capability拥有
  expansion_dependency_closure

  derived indexes
    function_capability_ids
    macro_capability_ids
```

- `semantic_blueprint`向 LLM 公开适用结构、数学角色、构造步骤、保持量、证明义务、
  目标改写、最值达到策略、限制条件及可展开的Function Capability；
- `functional_plan_fragment_templates`使用现有 `FunctionalPlan content/v3` 的 step、
  arg、return 与 dependency 语义，不建立第二套 LLM DSL；
- Macro candidate fragment只用于shadow搜索；winner物化为普通Function steps后，与LLM直接
  生成的steps进入同一个typed graph、F5-C、step executor、checkpoint与repair cone；
- Macro 可在普通 prompt 中表现为一个 step，但不能把数学证明只藏在专用 lowerer、
  post-hoc witness builder 或 transaction 分支中；
- runtime authority、StateVersion、candidate hash、物理 path、shadow Context 与
  checkpoint signature 继续只属于代码，不进入 prompt。

适用结构必须按角色不变量描述，不能把参考题中的字母当作契约。例如等长射线路径的
结构是：

```text
segment_moving ∈ Segment(anchor, reference_point)
ray_moving ∈ Ray(anchor, ray_direction_point)
distance(anchor, ray_moving) = distance(anchor, segment_moving)
objective = distance(fixed_point, segment_moving)
          + distance(reference_point, ray_moving)
```

其中 `fixed_point` 是任意满足 scope 与状态权威的定点；和平一模中的 `O` 只是该角色
的一次绑定，不属于适用条件。线段端点交换、等式两边交换、目标项交换、图形旋转翻转
及点名变化由同一结构匹配器覆盖，不逐题声明变式。数学拓扑真正不同才建立不同的已知
候选provider。

已知结构与策略Registry只负责提供低成本候选，不构成可解题目的封闭白名单。若没有已知
候选，或已知候选全部以数学原因失败，Goal retry仍使用最初固定的
`FamilyCapabilityBundle`，让LLM改用其中的Function Capability组合新解法；不得再次运行Family、
Function或Macro Capability筛选。configuration、authority或checkpoint错误不得伪装成这一
fallback。

Function和Method也不能为路径题创造一套专用结果语言。公开证明链只使用基础数学对象：

```text
Entity
Fact / Condition
Expression / Scalar
standard collection
```

纯Method返回`bool`或基础数学值。例如距离等价验证Method返回`true/false`；只有返回
`true`时，runtime才根据已钉住的调用输入确定性发布标准
`Condition(Equality(Distance(...), Distance(...)))`，并记录scope与provenance。下游LLM
步骤消费该`ConditionRef`，而不是消费`DistanceEquality`或`PathEquivalence`专用对象。
构造步骤产生普通Entity及约束Condition；表达式改写产生普通Expression，并由等价性验证
发布标准Equality Condition。

因此参考Macro的完整展开仍能表示“构造辅助对象 -> 验证距离等价 -> 改写目标 -> 验证
结果与合法域”；LLM也可以改用参数化、旋转、反射或其他受runtime支持的Function形成新
fragment。若缺少可表达或验证某一步的通用原语，应报
`functional.proof_obligation_unsupported`，后续补通用能力，而不是增加题号或点名特判。

## 6. F5-F4.3 分段实施计划

F4.3 不一次性完成。每一段必须形成独立可回滚提交；未完成 Registry、lowerer、
postcondition 与 evidence builder 的 Macro 保持 `direct`，不能提前改为
`runtime_search`。

```mermaid
flowchart LR
  A["F4.3A<br/>伴随输出权威"]
  B["F4.3B<br/>通用可验证子图内核<br/>与透明Macro展开"]
  C["F4.3C<br/>标准路径与耦合线段端点替换"]
  D["F4.3D<br/>正方形路径"]
  E["F4.3E<br/>加权路径"]
  F["F4.3F<br/>Planner协议清理"]

  A --> B --> C --> D --> E --> F
```

### 6.1 F4.3A：伴随输出权威（COMPLETE）

目标：先移除输出侧剩余的字符串分发协议，避免新 Macro 继续复制 input selector
已经退役的旧模式。

已完成：

- 四个固有伴随输出改由MethodSpec声明`emission=always`与
  `authority=return_allocation`，FunctionSpec只投影内部materialization policy；
- `MethodOutputWriteAuthority`按Function return key与唯一
  `FunctionalReturnAllocation`生成state或exact call-result destination，compiler只做机械lowering；
- transaction在执行前、运行结果产生后与commit后分别审计allocation、promote路径、
  runtime type、MathObject、scope和exact StateVersion；checkpoint v4保存authority payload与签名；
- family层重复companion声明、字符串target/registration selector、专用handle推断和
  standalone debug角色provider已物理删除；结构化等长射线候选只允许通过
  `macro_preparation`模块的owner入口构建。
- 等长射线角色上下文保留完整的`point label -> visible handles[]`权威；legacy路径文本
  真正引用重名点时稳定报`planner.macro_point_name_ambiguous`，不会把重名对象静默移出
  候选集。使用精确Point handle的结构化Fact不受展示标签重名影响。

`FunctionalOutputTargetSelectorSpec`继续保留：它负责Planner公开return的题面Entity消歧，
与已经删除的Method companion target/registration字符串分发不是同一层协议。

测试与提交：

```text
L0 affected
L2 contract
不运行付费 live
commit: refactor(solver): type companion output authority
```

### 6.2 F4.3B：通用可验证子图内核与透明 Macro 展开（COMPLETE）

目标：先关闭“Macro拥有一套隐藏数学逻辑、LLM显式Plan只能调用不完备Method”的断层，
同时避免为路径最值、正方形、加权路径或未来题型创建专用candidate、result与witness
体系。Macro与LLM必须生成同一种可验证FunctionalPlan子图；Registry是成熟候选库，
不是未来题型与解法的封闭全集。

新增或收敛的通用契约：

```text
FamilyCapabilityBundle
MacroSemanticBlueprint
FunctionalPlanFragment
ScopedDerivedBinding
FunctionalCapabilityKind = function | macro
VerificationOutcome
SearchCandidate[TFragment]
CandidateEvaluation[TResult]
CandidateSearchReport[TResult]
MacroExpansionRecord
```

`FunctionalPlanFragment`复用现有Plan step语义，只是一个Goal局部、可嵌入的代码侧模型，
不形成新的LLM wire。`SearchCandidate`只包装Macro/runtime generator产生的fragment、
dependency envelope与稳定signature；
`CandidateEvaluation`只记录通用验证结果和标准输出；`MacroExpansionRecord`只记录winner、
生成step、export mapping与search/expansion signature，不复制数学运行结果。泛型参数不能由
新的题型专用Python/JSON模型填充。

`ScopedDerivedBinding`是普通Plan return在scope树中的通用语义别名，不是路径题专用结果类型。
Entity输出获得scope-local MathObject身份，Condition输出在谓词验证成功后发布，Expression与
Scalar保留exact result authority。LLM后续使用SemanticRef读取这些变量；StepResultRef只作为
未命名值的wire形式以及F5-C/checkpoint中的精确producer证据。局部变量名不进入数学等价签名。

角色选择通过Macro公开参数或普通Entity binding表达；构造、变换、参数化、直达、反射、
端点等不同方案通过不同`FunctionalPlanFragment`表达。它们不再分别建立
`MacroRoleAssignmentCandidate`、`PathReductionCandidate`、`StraighteningResult`或
`PathAttainmentCandidate`。候选来源只能是Macro模板或声明式runtime generator，并全部进入
同一个搜索外壳。LLM显式步骤每个provider attempt只形成一个普通authored Plan，不包装为
fragment或Planner可见的候选数组，也不产生search authority、search report、tie-break或
“自动尝试其他思路”的语义。

实施内容：

- 统一Capability命名与单一事实源：`FamilyCapabilityBundle.capabilities[]`保存全部
  Function/Macro Capability，`function_capability_ids`与`macro_capability_ids`只能从该数组
  派生；不得再维护独立`macros[]`、`semantic_functions[]`或第二份能力定义；
- `FunctionalCapability.to_prompt_payload()`显式输出必填`kind=function|macro`。Function与
  Macro共用`capability_id/title/use_when/args/returns`公共字段；只有Macro投影
  `semantic_blueprint`和候选展开说明，Function不得伪造Macro search元数据；
- 将历史`CapabilityContractSpec.kind=method|recipe`迁为
  `capability_kind=function|macro`，并让method contract projection产生`function`、recipe
  contract projection产生`macro`。若调试或lowering确实需要实现来源，使用内部
  `implementation_source=method|recipe`，该字段不得进入prompt、Plan wire或Capability签名；
- `FunctionalCapabilityKind`下沉到共享contracts并由family contract、FunctionSpec、
  MacroSpec、catalog、schema与prompt共用。旧`method|recipe` Capability kind直接拒绝，
  不保留alias；`FunctionSpec.method_id`和内部`RecipeSpec`名称继续表示实现引用，不改变
  已有`capability_id`或FunctionalPlan step；
- Family识别一次性建立`FamilyCapabilityBundle`，同时固定Function/Macro Capability、
  Macro blueprint、expansion closure与bundle signature；Pass 1和Goal retry不得重新筛选
  Capability，retry只允许改变同一bundle的prompt projection；
- 增加 `MacroSemanticBlueprint` 的catalog投影，完整公开适用结构、角色语义、构造、
  保持量、证明义务、目标改写、达到策略、限制条件和可展开Function Capability；描述按角色
  不变量生成，禁止把和平一模的`O/B/C/D/M/N`等示例字母固化为适用条件；
- 增加Macro expansion contract：已知Macro的每个候选必须展开为普通
  `FunctionalPlanFragment`，然后才进入统一typed compile、shadow、F5-C、clean replay、
  checkpoint与witness流程；禁止数学结论只存在于Macro ID专用lowerer或post-hoc adapter；
- 建立Macro单一事实源并删除pack/family-local的同ID完整声明副本；bundle只能投影
  `MacroDefinition`，不得依赖“family local覆盖pack recipe”的顺序产生最终契约；
- 物理删除五题和few-shot均未使用的`broken_path_straightening_and_select`与
  `path_minimum_by_straightened_distance` Recipe、专用compiler入口和catalog测试；前者的
  候选/选择逻辑进入通用fragment provider，后者由`distance_between_points` Function
  Capability取代；
- 增加scope-local派生绑定：Function return可声明`kind=derived`的Entity、Condition、
  Expression或Scalar变量。scope树记录其owner、producer与非ProblemIR来源，下游使用普通
  SemanticRef，typed sidecar继续pin exact result；禁止把未知Entity名称或拼写错误自动当成
  派生声明；
- 建立通用predicate执行协议：Method只返回`bool`或基础数学值；验证为true时由runtime根据
  exact input authority发布标准Condition，false时不发布Condition并返回结构化
  `VerificationOutcome`。禁止Function返回`DistanceEquality`、`PathEquivalence`、
  `ConstructionEvidence`等题型专用结果；
- Macro的1..N个候选继续共享隔离shadow执行、非等价歧义与等价tie-break；但候选一旦选出，
  winner必须确定性物化为当前scope树中的普通Function steps，随后只经过现有typed graph、
  per-step F5-C、普通执行、checkpoint和repair cone。LLM-authored Function本来就是普通step，
  不建立额外fragment边界、selection信封或原子transaction；
- Macro candidate的shadow branch仍由搜索层隔离，失败候选不得产生write。winner clean阶段不得
  再执行历史Recipe或独立fragment runner，而是将选中fragment的Function steps写入代码派生的
  当前Plan revision，再由现有step executor重放。公开`minimum_expression`只能来自展开step的
  export，最值搜索或达到性证明只能作为普通验证Function，不能在展开图之外重算并覆盖结论；
- Macro search report只记录候选选择过程；实际Entity、Condition、Expression、StateVersion、
  provenance与step状态全部以普通step执行结果为权威。LLM Function不再事后聚合或伪造
  `VerifiedSubplanExecution`。历史`PathMinimumWitness`继续保持物理删除；Explanation与Visual
  从Macro expansion provenance及普通step evidence确定性投影教学字段；
- Macro无已知结构或全部候选以数学原因失败时，Goal retry直接在原
  `FamilyCapabilityBundle`中改用Function Capability显式组合，不得再次运行能力筛选；
- 收敛companion物理destination的机械派生：数学权威继续只来自return allocation，最终让
  promote path直接由allocation/projected write通用规则生成；不得把物理path升级为数学
  权威；
- Registry继续拥有candidate provider与验收contract，但prompt blueprint、fragment展开和
  runtime证据必须来自同一`MacroDefinition`可执行事实源；family不再保存同ID的本地
  `StepRecipeSpec`覆盖。迁移期仍保留三层非执行投影：pack recipe提供Planner-facing参数和
  return，`MacroSpec`提供typed catalog facade，presentation Recipe提供Explanation/Visual
  元数据。runtime-search Macro的`MacroSpec.search`必须直接引用Definition-owned contract并
  携带Definition signature，内部calls必须为空；这些投影壳不得拥有candidate builder、
  validator、fragment图或Method wiring。物理合并投影模型留到F4.3F，文档中的“单一事实源”
  只指单一可执行语义owner。transaction不得按Macro ID分支。

参考等价门禁：和平一模分别通过“一步调用`equal_length_ray_path_reduction`”与“显式展开
构造等长点、证明SAS距离等价、改写路径、证明折线路径最值”两条Plan完成。Macro winner
物化后的普通step图与LLM显式step图经过alpha-normalization后，其最终输出、发布Condition、
对象authority、exact version及provenance必须runtime等价。临时从catalog移除该Macro后，
recorded显式Function Plan仍须通过。

测试与提交：

```text
capability taxonomy / generic candidate / predicate publication / Macro blueprint / expansion equivalence专项
L0 affected + L2 contract
现有未迁移 family 仍保持 direct
不运行全题 live
commit: refactor(solver): add generic verified subplan kernel
```

验收状态：B主体的专项门禁验证了clean Macro无Recipe plan、fragment export为标准输出权威、
公共Capability kind仅为
`function|macro`、`MacroDefinition`与catalog签名一致，以及历史Path witness builder和
等长射线专用runtime recipe入口为0。旧`equal_length_ray_point`已从生产family、Capability
bundle、contract和typed binding中删除，只保留为显式v1 debug Method；presentation
RecipeSpec的`method_sequence`为空，不再构成第二份执行图。B阶段初次验收的L3 full为
`2427 passed`；复审收口后定向回归为`75 passed`、L0 affected为
`1576 passed, 57 deselected`、L2 contract为`2366 passed`。随后确认“Macro/LLM共享
VerifiedSubplan信封”不是需要保留的
执行架构，而是B-R必须删除的迁移态：LLM保持普通steps，Macro winner物化后加入同一普通Plan。
复审后已物理删除无生产消费者的`PathMinimumWitness`、其schema/sync入口及测试专用
`search_segment_path_minimum`，lineage标签改为`verified_path_minimum_subplan`。进一步审查
确认不应为LLM普通step新增fragment事务：现有step状态、producer DAG、失败传播、frozen/editable、
repair cone与checkpoint已经拥有失败影响范围权威。B-R已将Macro生命周期收窄为“只在winner
选择前特殊”；winner选中后展开为普通Plan steps并复用现有执行协议。最终L2 contract为
`2368 passed`，L3 full为`2422 passed`，未运行付费LLM冒烟，F4.3B据此关闭。

### 6.2.1 F4.3B-R：Macro Winner普通Plan化（COMPLETE）

#### 问题与原则

B-R不再引入LLM fragment边界、统一subplan transaction、原子commit或checkpoint v5。现有
Goal execution已经能够按普通step记录`passed / failed / blocked`，并通过producer DAG、
frozen/editable authority、repair cone、provisional write和checkpoint判断失败影响范围。
重复建立fragment事务只会产生第二套owner。

唯一需要收口的双路径是：Macro winner当前仍可能由专用Recipe或fragment runner clean执行，
而LLM Function始终作为普通Plan step执行。目标改为：

```mermaid
flowchart LR
  M["LLM authored Macro step"]
  C["Macro展开1..N个候选fragment"]
  S["隔离shadow验证"]
  W["选择唯一或等价winner"]
  X["winner物化为普通Function steps"]
  P["当前ScopedFunctionalPlan revision"]
  G["现有TypedExecutionGraph与per-step F5-C"]
  E["现有step executor"]
  K["现有checkpoint v4与repair cone"]

  M --> C --> S --> W --> X --> P --> G --> E --> K
```

LLM直接编写Function时从`ScopedFunctionalPlan revision`进入同一条链，不生成候选数组，也不
包装成fragment。核心不变量是：

> Macro候选只在winner选择前特殊；winner一旦选出，就只是代码生成的一组普通Plan steps。

#### 1. 最小Macro展开记录

保留`FunctionalPlanFragment`作为Macro candidate builder的临时数据，不把它升级为LLM DSL、
transaction边界、checkpoint owner或restore单位。新增或收敛为一个轻量不可变sidecar：

```text
MacroExpansionRecord
  authored_plan_id / materialized_plan_id
  macro_step_id / macro_id
  implementation_id / preparation_signature
  winner_candidate_id / search_signature
  generated_step_ids[]
  export_map{}
  expansion_signature

MacroGeneratedStepOrigin
  macro_step_id
  winner_candidate_id
  generated_ordinal
```

- `MacroExpansionRecord`只证明“哪些普通step来自哪个已验证winner”，不决定step能否提交、
  冻结、恢复或编辑；
- `generated_step_ids`使用Macro step identity、Function capability和稳定ordinal确定性生成，
  禁止runtime随机后缀；
- `export_map`将Macro公开return映射到某个生成step的精确return，不能按类型或名称重新猜测；
- authored hint和失败候选只进入search report，不能进入winner step的F5-C、source units或
  provenance；
- record与生成step进入debug、checkpoint和Explanation provenance，但不进入LLM response schema。

不新增`FunctionalPlanFragmentBoundaryIndex`、`PreparedFunctionalSubplan`、
`FunctionalSubplanTransactionCoordinator`、`FunctionalSubplanCommitBundle`或新的
fragment restore authority。

#### 2. Winner确定性物化

Macro candidate search继续在独立`RuntimeContext.fork()`与`WorkingPlannerState.fork()`
中验证候选：

1. configuration、contract或authority异常立即fail loud，不能降为数学候选失败；
2. predicate为false、合法域不满足或数学postcondition失败只淘汰当前候选；
3. 唯一有效候选直接采用；多个runtime等价候选使用现有确定性tie-break；多个非等价候选
   报`functional.macro_search_ambiguous`；
4. shadow branch只用于选择，任何Entity、StateVersion、CallResult、Condition或checkpoint
   write都不得复制到正式执行；
5. winner确定后，将其`FunctionalPlanFragment.steps`转换为普通
   `ScopedFunctionalPlanStep`，替换当前代码派生Plan revision中的Macro执行槽；
6. 生成step保留Macro原scope与semantic owner。任何跨scope读写、sibling依赖或代码自动提升
   都按现有scope authority拒绝；
7. Macro return consumer、`answer_from`及下游依赖通过`export_map`改写为生成step的标准
   return binding；
8. 物化后的完整Plan重新经过现有tree、owner、dependency、return、F5-C和compile审计；
9. winner clean执行从第一个生成step开始走普通step executor，不再调用Macro Recipe clean
   lowerer或独立fragment runner；
10. clean结果与shadow winner的公开输出、Condition和chosen-role signature漂移时报
    `planner.macro_winner_replay_drift`，但正式状态只来自clean普通step执行。

Macro authored Plan仍作为source provenance保存；执行、retry与checkpoint使用
`materialized_plan_id`对应的当前Plan revision，避免同一个plan identity同时代表“一个Macro
step”和“若干生成Function steps”。

#### 3. 复用现有失败影响范围

生成step不获得特殊的原子语义。假设winner展开为：

```text
construct_G
→ verify_G_on_ray
→ verify_CG_equals_CB
→ rewrite_path
→ build_minimum_expression
```

若第三步失败，现有执行结果应直接是：

```text
construct_G                 passed
verify_G_on_ray             passed
verify_CG_equals_CB         failed
rewrite_path                blocked_by_upstream
build_minimum_expression    blocked_by_upstream
```

后续完全复用现有规则：

- 已通过且位于solved closure中的生成step可以冻结；
- 直接失败step进入editable集合；
- 下游blocked step是否开放由现有repair cone、Goal状态和owner authority决定；
- 一个失败Goal不得扩大到sibling scope或删除其他solved Goal的frozen producer；
- retry可以保留生成step、替换失败Goal的普通Function steps，或重新输出Macro step触发新搜索；
- 若重新调用Macro，旧`MacroExpansionRecord`与其未冻结provisional结果必须丢弃；
- 不因“这些step来自同一个Macro”而整体rollback、整体冻结或整体开放。

候选shadow失败仍然整体丢弃，因为它尚未进入正式Plan；winner进入正式Plan后不再拥有这项特殊
生命周期。

#### 4. Checkpoint与Restore保持v4

本阶段不升级checkpoint或retry协议，继续使用：

```text
functional-goal-execution-checkpoint/v4
functional-execution-restore-state/v1
functional-goal-repair/v5
planner-goal-retry-context/v4
```

- checkpoint按现有普通step保存exact StateVersion、CallResult、Condition、compiled authority和
  execution status；
- 额外保存`MacroExpansionRecord`，用于证明生成step集合、winner、implementation和export
  mapping没有漂移；
- solved/frozen生成step按现有exact authority恢复，不重新运行candidate builder、不重新选择
  latest state；
- editable生成step按当前materialized Plan正常重编译和执行；
- retry重新选择Macro时才丢弃旧record并重新搜索；
- expansion signature、winner、generated step、export、exact read或write漂移继续使用现有
  configuration error路径，semantic retry增量为0；
- 不引入fragment级restore，不禁止现有step级frozen/editable合并。

#### 5. 证据、Explanation与等价门禁

普通step execution result是唯一数学执行证据：

- Entity、Condition、Expression、Scalar、StateVersion和provenance从生成step的标准执行结果读取；
- Macro search report只说明尝试了哪些候选以及为何选中winner；
- `MacroExpansionRecord`只连接search provenance与生成step，不复制运行结果；
- LLM Function不再构造`SingleFragmentSelection`或事后聚合
  `VerifiedSubplanExecution`；
- 若`VerifiedSubplanExecution`在迁移后没有独立消费者，则物理删除model、schema与checkpoint
  分支；Explanation/Visual从expansion record和普通step evidence投影；
- Predicate Condition无论来自Macro展开还是LLM显式step，都只由同一个publication逻辑在
  Method返回true后发布。

Macro与LLM等价比较发生在普通Plan层：

```text
materialized Macro winner steps
vs
LLM authored Function steps
→ alpha-normalized typed graph
→ outputs / Conditions / exact versions / provenance比较
```

比较忽略step拼写、派生变量名、candidate id和search report；必须比较Function capability图、
公开及被消费的derived binding、chosen对象、exact input version、最终结果、Condition publication
和semantic provenance。不能只比较`minimum_expression`。

#### 6. 删除双执行路径

物理删除或禁止生产引用：

- Macro winner的legacy Recipe clean执行；
- `FunctionalPlanFragmentTransactionalRunner`的winner clean路径；
- LLM Function的fragment boundary推断与事后`VerifiedSubplanExecution`聚合；
- 任何以Macro ID分支重新计算minimum、Condition或standard output的post-hoc adapter；
- “先执行Macro结果，再执行fragment只作校验”的并行权威；
- 为B-R规划但尚未实现的fragment transaction、commit bundle和checkpoint v5契约。

允许保留：

- Macro candidate shadow evaluator及其fork隔离；
- `FunctionalPlanFragment`候选生成模型；
- 通用candidate search、预算、等价tie-break和prompt-safe diagnostic；
- 当前普通step executor、Goal checkpoint、repair cone和transaction审计。

#### 7. 分段提交与测试

建议拆成两个独立提交：

1. `refactor(solver): materialize macro winners as plan steps`
   - 增加expansion record、稳定step id、export rewrite及materialized Plan审计；
   - winner clean改走现有普通step执行器；
2. `refactor(solver): remove parallel macro fragment execution`
   - 删除Recipe/fragment clean旁路、LLM fragment聚合及冗余VerifiedSubplan authority；
   - checkpoint v4保存expansion record并开启静态零引用门禁。

新增或重构：

```text
test_macro_winner_plan_materialization.py
test_macro_generated_step_retry.py
test_macro_explicit_plan_equivalence.py
test_functional_goal_checkpoint_v4.py
test_verified_functional_plan_execution.py
```

必须覆盖：

- wrong hint经shadow search选择唯一winner，正式F5-C只记录chosen对象；
- loser candidate ghost write为0；
- winner生成step的scope、owner、依赖、return binding和export map稳定；
- winner clean调用普通step executor，Recipe/fragment clean runner调用数为0；
- 第1步、第k步和末步失败时，step状态、blocked传播、frozen/editable与现有repair cone完全一致；
- 成功前缀不会仅因Macro来源被回滚，sibling和solved Goal不会被错误开放；
- solved生成step restore不搜索candidate、不重选latest、不重执行；
- retry重新输出Macro时旧winner provisional authority被丢弃；
- Macro物化step图与LLM显式Function Plan的标准结果、Condition、exact version及provenance等价；
- 五份recorded Plan的答案、Goal状态、checkpoint、Explanation和Visual输入不漂移。

验收：

```bash
cd server
uv run pytest \
  tests/solver/test_macro_winner_plan_materialization.py \
  tests/solver/test_macro_generated_step_retry.py \
  tests/solver/test_macro_explicit_plan_equivalence.py \
  tests/solver/test_functional_goal_checkpoint_v4.py \
  tests/solver/test_verified_functional_plan_execution.py -q

uv run python tools/run_solver_tests.py affected
uv run python tools/run_solver_tests.py contract --workers 4
uv run python tools/run_solver_tests.py full --workers 4
git diff --check
```

本阶段不运行付费LLM冒烟；B-R只删除Macro winner的第二套执行路径，不改变Family能力选择、
LLM Plan语义或现有失败影响范围。完成门禁：

```text
Macro winner物化为普通step覆盖率 == 100%
Macro Recipe/fragment clean执行次数 == 0
LLM fragment边界与事后聚合引用 == 0
新增subplan transaction/checkpoint协议数量 == 0
candidate shadow ghost write == 0
生成step failure/repair与普通step语义差异 == 0
restore重新搜索或选择latest次数 == 0
Macro物化Plan与LLM显式Plan等价mismatch == 0
configuration/unclassified error == 0
L3 full通过
```

实施结果：Macro winner会以稳定step ID替换原Macro step，`export_map`重写下游consumer和
`answer_from`；正式执行只经过普通typed graph、per-step F5-C、transaction与checkpoint v4。
`MacroExpansionRecord`额外保存generated return的实例级semantic role，Explanation/Visual据此
投影辅助点和交点，不参与执行决策。旧VerifiedSubplan执行对象、schema、Macro clean envelope与
`__verified_subplan_*`调用均已删除。L2为`2368 passed`，L3为`2422 passed`，完整generated gate
无mismatch。

复审后补强了三项字面门禁：`test_macro_explicit_plan_equivalence.py`不再回放Macro生成的
`canonical_plan`，而是读取独立静态fixture，其中十个`llm_*` Function step、派生名`G/P`及
Condition名称均由测试作者显式声明。它与Macro物化图分别通过完整assembly、F5-C和transaction，
随后比较alpha-normalized普通step图、逐input exact typed authority、source provenance、发布
Condition及最终标准输出。Goal execution与Scoped replay现在共用同一个clean-output verifier，
两条入口都会将普通Function export与shadow winner signature对账。Macro选择结束后不再调用
`finalize_macro()`再抛出物化控制信号；旧Macro F5-C行保持pending并随Macro step一同消失，只有
新生成的普通Function step建立最终per-call F5-C binding。复审补强后的L2 contract为
`2370 passed`，schema snapshot与`git diff --check`均通过；未重复运行付费LLM冒烟。

### 6.3 F4.3C：标准路径与耦合线段端点替换（COMPLETE）

目标：迁移 `quadratic_path_minimum` family，并优先解决南开题中 Planner 需要拼装
PathTransformation、端点和拉直步骤导致的超长输出。

进入条件：先完成F4.3B-R Macro Winner普通Plan化。Macro winner必须先物化为普通Function
steps，再与LLM显式Plan共用现有typed graph、F5-C、step executor、checkpoint和repair cone；
不得保留Recipe或fragment clean执行旁路。等价门禁比较alpha-normalized普通step图、标准输出、
Condition、exact version和provenance，而不是只比较最终表达式或额外执行信封。

#### 6.3.1 C1：显式Function解法闭环（COMPLETE）

C1没有新增Macro，也没有切换生产南开fixture。它先证明LLM只使用普通Function steps就能完成
同一条数学证明链：

```text
结构化Fact
-> 证明EG=DG
-> 反射D得到D'
-> 求D'F与MN的交点G
-> 将EG+FG改写为DG+GF
-> 验证D'F可达且为全局最小值
-> 发布minimum_expression
```

新增公开Function：

- `prove_coupled_segment_endpoint_distance_equality`消费两个`point_on_segment`、一个
  `segment_length_relation`以及明确的Point角色，runtime Method只返回Boolean；为true时由统一
  Predicate门禁发布`distance_equality` Condition；
- `rewrite_path_target_by_distance_equality`消费精确`path_minimum_target`与上一步Condition，验证
  对象角色后输出标准`Expression`，不按点名、description或Context顺序猜测；
- `certify_minimum_expression`的标准return现在显式携带`path_minimum_expression`语义角色。最终
  answer closure接受两种完整证明族：旧Macro的verified witness，或标准
  `path_minimum_attained` Condition；两者都必须保留可见path target与最小值表达式。Predicate
  Condition同时钉住`candidate`精确结果角色与规范化运行值签名，认证步骤必须消费同一候选值，
  不能再用任意Expression借用另一个attainment Condition过门。

Capability assembly新增`path_verification_core`与
`coupled_segment_endpoint_replacement_core`。前者由等长射线与南开family复用，并拥有通用
`rewrite_path_target_by_distance_equality`；后者只加入耦合结构专用的
`prove_coupled_segment_endpoint_distance_equality`和策略说明，不注册Macro。旧
`two_moving_points_path_reduction`与新Function暂时共用`coupled_segment_endpoint_residuals`纯数学
helper，避免迁移期维护两份公式。

Condition authority从ProblemIR结构化字段生成`point_on_segment`、
`segment_length_relation`与`path_minimum_target`对象角色；Method不解析handle名称。闭线段达到性
先证明统一仿射参数`point=start+lambda(end-start)`及`0<=lambda<=1`，单符号范围推理支持任意
结构化边界，不硬编码`m>2`。直达交点位于路径延长线但不在线段上时稳定淘汰，不再误作可达候选。

独立fixture`nankai_coupled_segment.json`替换测试副本中的旧路径两步，并把`ii_2.G`改为对共享
`G`执行`evaluate_point_at_parameter`。完整assembly、typed graph、F5-C、transaction、六个Goal、
Predicate publication与checkpoint均通过；测试禁止调用路径Macro preparation，并验证：

```text
D' = (m+1, 2-m)
G  = ((m+4)/3, (3-2m)/3)
minimum = sqrt(5*m^2-10*m+10)/2
ii_2.G = (4, -13/3)
```

生产五题recorded Plan仍走原路径，结果没有切换。C1定向组合为`205 passed`，L0 affected为
`683 passed, 9 deselected`，补齐静态契约后L2 contract为`2377 passed`；未运行L3或付费LLM冒烟。

#### 6.3.2 C2：透明Macro展开（COMPLETE）

C2新增公开能力：

```text
coupled_segment_endpoint_replacement_path_minimum
```

实现结果：

- 已知路线下Planner只传path target、运动约束/绑定Fact、题面Entity与可选角色hint；
- Macro blueprint同时向LLM公开降维、轨迹恢复、拉直、端点构造、距离与最值证明的完整
  数学思路及可展开Function Capability，不把这些语义只藏进实现；
- Macro模板与LLM显式组合的耦合线段端点替换fragment复用F4.3B的通用candidate、Condition
  publication与普通Function执行协议；
- `PathTransformation`、内部端点和 Method 连线不进入 prompt；
- 新Macro在family Registry中注册为`runtime_search`，角色上下文只从结构化Condition与可见
  Entity authority投影；
- 输出 `minimum_expression`，仅在 Goal 需要时公开 minimizing point/configuration；
- `coupled_segment_endpoint_replacement_path_minimum`展开为C1已经验证的七个普通Function steps，
  不调用旧`two_moving_points_path_reduction`或隐藏Path Method；
- candidate search只选择结构角色与合法展开，不拥有第二套几何公式；winner物化后仍走普通Plan；
- Macro物化step图与独立C1 fixture做alpha-normalized graph、Condition、F5-C、exact version、
  provenance和标准输出等价比较，并验证checkpoint恢复不会重新搜索Macro；
- shadow Condition publication与正式执行统一使用直接对象角色和exact Condition authority；
- C2定向Macro/C1/checkpoint组合为`39 passed`，L2 contract为`2379 passed`；没有切换生产
  fixture，没有删除旧Macro，也没有运行付费live。这些动作仍属于C3。

#### 6.3.3 C3：生产切换与物理删除（COMPLETE）

C3已将南开三份recorded Plan切换到
`coupled_segment_endpoint_replacement_path_minimum`。共享Macro位于两个子问的最近公共父
scope，一次发布匿名`minimum_expression`和可选`attainment_point`；两个子问分别通过
StepResultRef或题面Point状态消费，不重复构造Path链。南开不再依赖
`broken_path_straightening_minimum_expression`。

旧`two_moving_points_path_reduction`公开Macro、Method、MethodSpec、family recipe/rule与固定
planner调用已物理删除；新Macro的普通公开返回中不再存在`PathTransformation`。和平二模仍使用
`broken_path_straightening_minimum_expression`，其迁移和全局Path壳删除按D/F阶段边界处理。
prompt角色投影与runtime candidate search现在统一以path target的valid scope解析结构角色，Macro
在后代scope执行时不会被后代local/shadow Fact改变候选集；可见性与写入仍以execution scope为
权威。prompt上下文分派按Macro ID显式注册，新增第三种Macro而未提供builder会配置级fail-loud，
不会静默复用coupled builder。新Macro专项门禁已覆盖错误hint由唯一runtime winner纠正、不可比较
的非等价候选报歧义、shadow写入零泄漏、clean replay、显式Function等价与checkpoint恢复。

最值Goal closure暂时仍接受`verified_path_minimum_subplan ∨ path_minimum_attained`：前者只为D前仍在
生产使用的和平二模旧拉直链保留。D迁移该链时必须将相应family收敛到predicate witness；C3不提前
全局删除这条兼容分支。

最终L0 affected为`1153 passed, 9 deselected`，L2 contract为`2330 passed`。真实DeepSeek批次
`f5-f4.3c3-nankai-live-1x3-20260826-r3`为`3/3`：compile、transaction、六个Goal、
Plan authority与completion全部通过；三个样本均只有一次semantic attempt和一次provider
sub-attempt，provider `finish_reason`全部为`stop`，`length`数量为`0`。configuration error、
unclassified error、repair authority drift、failed transaction ghost write、prompt identity leak与
solved Goal重执行均为`0`。首次真实批次暴露的兄弟scope重复Macro调用已通过公开Capability契约
和采样结果消除；最终验收批次无需Goal retry。debug authority表明该`1×3`实际统一选中的few-shot
是`quadratic_constraints_vertex`（三份同ID、同hash），不是现已正名的
`coupled_segment_endpoint_replacement`。后者是使用占位角色的可复用机制示例，但不能用于归因本次live
改善，更不是为南开题点名定制的测试片段。

测试与提交：

```text
C1: L0 affected + L2 contract
C2: L0 affected + L2 contract
C3: L0 affected + L2 contract + 南开定向live 1x3
C3 live目标: single provider attempt，finish_reason=length数量 == 0
```

### 6.4 F4.3D：正方形路径

目标：将 `quadratic_square_reflection_path_minimum` family 收敛为
`square_relation_path_minimum`。

实施内容：

- Macro 消费 square、midpoint、center、locus 与 path target Facts；
- blueprint公开正方形降维、动点轨迹恢复、反射/拉直、端点与最值计算的证明链，Macro
  模板只负责复用成熟fragment；LLM可用相同Function Capability显式改写；
- LLM 的 moving-point hint 只影响候选顺序，唯一 runtime winner 可以纠正；
- 通用witness保存标准square Condition、Expression等价Condition、结果与minimizing
  configuration，不新增SquarePathWitness；
- 删除公开`square_path_dimension_reduction`、`broken_path_straightening_minimum_expression`
  及内部Path witness连线；D完成后旧拉直三步Macro的生产引用必须为0。

测试与提交：

```text
L0 affected + L2 contract
和平二模定向 live 1x3
错误动点 hint 自动纠正且 source binding drift == 0
commit: refactor(solver): migrate square path minimum macro
```

### 6.5 F4.3E：加权路径

目标：将两步公开链合并为 `weighted_axis_path_minimum`。

实施内容：

- 合并 `weighted_axis_path_triangle_transform` 与
  `linked_broken_path_minimum_expression`；
- 辅助点使用普通Entity，辅助轨迹与三角形约束使用标准Condition，转换前后目标使用
  Expression及Equality Condition，并进入通用witness；其数学构造和证明义务同时进入
  Macro blueprint，内部runtime对象与物理path不进入prompt；
- public input 只保留 path target、weight/binding、axis membership、dynamic
  constraint Facts 与必要角色 hint；
- runtime 验证权重变换恒等式、合法域、候选可达性和最终表达式；
- 删除 compiler 中按点名、`aux` 子串或 Context 顺序寻找辅助对象的 helper；
- 河西、西青recorded Plan迁移后物理删除`weighted_axis_path_triangle_transform`与
  `linked_broken_path_minimum_expression`的Planner-facing Method/Capability契约；可复用数学
  逻辑必须已拆入普通Function/predicate，不保留仅供新Macro调用的同构黑箱Method。

测试与提交：

```text
L0 affected + L2 contract
河西或对应 weighted family 定向 live 1x3
内部辅助对象 identity 泄漏 == 0
commit: refactor(solver): migrate weighted path minimum macro
```

### 6.6 F4.3F：Planner 协议清理

目标：所有 family 迁移完成后，一次性删除 Planner wire 中的内部 Path 实现细节。

实施内容：

- 从 prompt、dynamic schema、catalog 与 repair wire 删除
  `PathTransformation`、`PathWitness`、`PathCandidate`、内部端点和 Method wiring；
- 删除旧公开 recipe、return alias、few-shot 旧写法和 debug bypass；
- 重写五份 fixture、few-shot 与 compile manifest；
- 静态门禁禁止生产 internal Path type、companion 字符串 selector、standalone role
  inference 和 Macro ID transaction 分支；
- Explanation / Visual 全部从`VerifiedFunctionalPlanExecution`中的普通step evidence及
  `MacroExpansionRecord`读取标准Entity、Condition、Expression与provenance，不依赖题型
  专用witness类型。

测试与提交：

```text
L0 affected
L2 contract
L3 full
Planner-only live 5x3 --concurrency 15
commit: refactor(solver): retire planner path implementation wire
```

## 7. 分段原则与提交边界

每段都遵守以下规则：

1. 一个提交只改变一个权威边界或一个family，不把通用candidate/winner物化内核与family
   迁移混在一起。
2. Macro 只有在 candidate builder、validation policy、lowerer、postcondition、evidence
   builder 与 restore 全部接通后，才可声明 `runtime_search`。
3. shadow 候选只能读取 dependency envelope 内的 Entity、Fact 与 exact state；任意
   configuration/contract 异常必须 fail loud，不能伪装成“候选不通过”。
4. winner 确定后才生成最终 F5-C binding；authored hint 只能进入 search report。
5. clean replay 必须从干净 Context 重新执行，禁止复制 shadow write 或 result。
6. 每个 family 定向 live 通过后再迁下一个；只有 F4.3F 运行全量 L3 与 5x3。
7. 中间提交不得通过兼容 alias 让新旧公开 Path 契约同时长期存在。
8. 每个Macro必须有结构化semantic blueprint和普通FunctionalPlan fragment候选展开；winner
   选中后必须物化为普通Function steps并进入现有typed执行协议。LLM直接author普通steps，
   不建立fragment边界，也不进入Macro候选搜索。
9. Macro适用条件必须使用数学角色与关系不变量；示例题的点名、题号、朝向或坐标不得
   成为结构匹配条件。
10. Family只选择一次`FamilyCapabilityBundle`。Registry只提供已知候选；无已知数学候选
    时LLM在同一bundle中改用Function Capability显式组合，不得进行第二次Capability筛选。任何
    configuration、authority或restore错误不得借此消耗LLM retry。
11. Method只返回bool或基础数学值；成功谓词由runtime发布标准Condition。禁止新增
    `DistanceEquality`、`PathEquivalence`等题型专用公共结果。
12. candidate、evaluation和search report只能使用F4.3B的通用外壳；family只能提供普通
    FunctionalPlan fragment候选与标准数学值，不得定义题型专用执行或witness模型。
13. 可复用中间Entity、Condition、Expression和Scalar使用显式scope-local派生绑定。局部名
    只用于Plan可读性，不能参与对象选择；Macro物化step图与LLM显式step图的等价比较必须支持
    局部变量alpha-renaming，并以producer、return role、scope、类型和exact authority为准。
14. 旧能力只能按3.2退役矩阵删除：先有runtime等价的新fragment与recorded Plan，再删除旧
    Capability/Method。已判定为直接重复的两个Recipe不得被后续family重新引用。
15. 同一`capability_id`只能由一个`MacroDefinition`拥有；pack、family、catalog与runtime
    registry中的其他结构均为派生projection，不得以覆盖顺序维护第二份完整契约。

## 8. 最终门禁

```text
Planner prompt internal Path types == 0
Planner-authored internal Method arguments == 0
production input selector == 0
production companion-output string selector == 0
standalone production role inference == 0
transaction Macro ID branch == 0
runtime_search Macro缺失Registry实现数量 == 0
wrong role hint唯一纠正成功率 == 100%
non-equivalent runtime ambiguity全部fail loud
shadow candidate ghost write == 0
winner clean replay drift == 0
restore重新搜索/重新选择latest次数 == 0
Family capability bundle每次规划选择次数 == 1
Pass 1与Goal retry的bundle signature漂移 == 0
prompt Capability缺失kind数量 == 0
prompt Capability kind非function/macro数量 == 0
公开method/recipe Capability kind数量 == 0
Family bundle独立macros/semantic_functions事实源数量 == 0
Macro blueprint挂载到Function Capability数量 == 0
题型专用candidate/evaluation/search-report/witness新增数量 == 0
Method题型专用evidence result新增数量 == 0
验证成功谓词的标准Condition publication覆盖率 == 100%
标准输出与普通step provenance覆盖率 == 100%
生产Macro semantic blueprint覆盖率 == 100%
生产Macro FunctionalPlan fragment展开覆盖率 == 100%
Macro物化step图与显式Function Plan runtime等价漂移 == 0
LLM每个provider attempt的authored Plan数量 == 1
LLM普通Plan产生search authority/report/tie-break次数 == 0
可复用中间对象的scope-local派生绑定覆盖率 == 100%
派生对象sibling泄漏、名称碰撞与restore producer漂移 == 0
Macro物化Plan与LLM显式Plan局部变量alpha-renaming等价漂移 == 0
示例点名进入Macro适用结构契约数量 == 0
移除参考Macro后recorded显式fragment仍可执行
broken_path_straightening_and_select生产引用 == 0
path_minimum_by_straightened_distance生产引用 == 0
two_moving_points_path_reduction旧Macro/Method生产引用 == 0
broken_path_straightening_minimum_expression生产引用 == 0
square_path_dimension_reduction生产引用 == 0
weighted_axis_path_triangle_transform生产引用 == 0
linked_broken_path_minimum_expression生产引用 == 0
同一capability_id的完整Macro定义数量 <= 1
right_angle_equal_length_construct_and_select保留且透明展开覆盖率 == 100%
curve_candidate_parameter_solve保留且透明展开覆盖率 == 100%
equal_length_ray_path_reduction公开ID保留且通用内核覆盖率 == 100%
Explanation无需解析LLM prose即可还原路径证明
定向family live全部通过
Planner-only 5x3在三轮内15/15通过
configuration / unclassified error == 0
```

## 9. 当前下一步

下一项实现是 **F4.3D 正方形路径迁移**。F4.3C已经完成南开生产切换、旧耦合Path链物理删除、
Macro/显式Function等价门禁和定向live`1x3`。D阶段迁移和平二模时仍应复用F4.3B通用内核，
不得重新引入PathTransformation输出、output selector、专用handle推断或题型专用witness体系。
