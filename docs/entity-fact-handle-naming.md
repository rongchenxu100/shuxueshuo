# Entity / Fact 与 Canonical Handle 命名规范

## Summary

本文定义 Method Solver 中题目对象、题设事实、推导结论和辅助构造的统一命名规范。目标是让 `ProblemIR`、`RuntimeContext`、LLM Planner、Resolver 和 Method 执行层使用同一套 canonical handle，避免 LLM 在 `reads` 中自造 `relation:right_angle_equal_length`、`condition:MN_length` 这类无法映射回题目结构的数据。

核心原则：

- 同一个数学对象只建一个 Entity。
- 对象的未知、含参、已求值状态都由 Fact 表达，不通过改名表达。
- 题设对象由 ProblemIR 建 Entity；解题辅助构造由 step `creates` 或 runtime declaration 建 derived Entity。
- LLM 只能引用系统提供过的 canonical Entity / Fact / answer handle，不能自由发明 handle。
- 解题过程本质上是事实图生长：每个 step 读取已有 Entity / Fact，产生新的 Fact，必要时创建新的 derived Entity。

## 两层模型

### Entity：数学对象

Entity 表示题目或推导中存在的数学对象，例如点、线、线段、函数、参数、图形对象。

Entity 的名字稳定，不随推导阶段变化。

示例：

```text
point:problem:D
point:ii:M
point:ii:N
function:problem:parabola
symbol:problem:m
line:ii:MN
segment:ii:DM
```

如果点 `N` 一开始未知，后续求出 `N=(m,1-m)`，再在某个小问中代入 `m=3` 得到 `N=(3,-2)`，它仍然是同一个 Entity：`point:ii:N`。变化的是关于 `N` 的 Fact。

### Fact：关于对象的事实

Fact 表示题设条件、约束、关系、坐标、参数值、函数解析式和推导结论。Fact 可以有 scope，说明在哪一问或哪些子问中有效。

示例：

```text
fact:problem:coefficient_relation
fact:ii:right_angle_equal_length_DMN
fact:ii:N_fourth_quadrant
fact:ii:segment_E_on_DM
fact:ii:segment_G_on_MN
fact:ii:segment_DE_eq_sqrt2_NG
fact:ii_1:MN_length_squared_eq_10
fact:ii_2:path_minimum_value_given
fact:ii:N_coordinate_expr
fact:ii_1:m_value
fact:ii_1:parabola_equation
```

Fact 引用 Entity，而不是替代 Entity。例如：

```json
{
  "handle": "fact:ii:right_angle_equal_length_DMN",
  "type": "right_angle_equal_length",
  "scope_id": "ii",
  "anchor": "point:problem:D",
  "reference": "point:ii:M",
  "target": "point:ii:N"
}
```

Fact 可以带 `value` 字段。例如：

```json
{
  "handle": "fact:ii_1:m_value",
  "type": "symbol_value",
  "scope_id": "ii_1",
  "subject": "symbol:problem:m",
  "value": "3",
  "valid_scope": "ii_1"
}
```

这意味着不再需要单独的 `value:*` 命名空间。LLM 的 `reads` 只需要引用 Entity / Fact / answer handle。

## Canonical Handle 规范

### Entity Handle

Entity handle 使用：

```text
<entity_type>:<introduced_scope>:<name>
```

常见类型：

```text
point
line
segment
ray
function
symbol
angle
circle
polygon
```

示例：

```text
point:problem:D
point:ii:N
line:ii:MN
segment:ii:DM
function:problem:parabola
symbol:problem:a
```

`introduced_scope` 表示对象第一次出现或被构造的 scope，不表示它只能在该 scope 使用。可见性由 RuntimeContext 的 scope 规则和 Fact 的 `valid_scope` 决定。

### Symbol Role

符号类 Entity 需要显式声明角色，避免 compiler 通过字母名猜测。二次函数题里 `a/b/c` 常常是系数、`x` 常常是自变量，但这只是当前题型约定，不应成为通用代码里的硬编码规则。

推荐在 ProblemIR 的 symbol metadata 中保存：

```json
{
  "handle": "symbol:problem:b",
  "entity_type": "symbol",
  "scope_id": "problem",
  "roles": ["quadratic_coefficient", "primary_parameter"],
  "description": "第（Ⅲ）问要求解的二次函数系数 b"
}
```

常见 role：

| Role | 含义 |
| --- | --- |
| `function_variable` | 函数自变量，例如 `x` |
| `quadratic_coefficient` | 二次函数系数，例如 `a/b/c` 或其他命名的系数 |
| `primary_parameter` | 当前题问需要反求或输出的主参数 |
| `dynamic_parameter` / `moving_point_parameter` | 动点轨迹参数，例如 `N(n,0)` 中的 `n` |

同一个符号可以有多个 role。例如河西第（Ⅲ）问中 `b` 既是二次函数系数，也是题目最终要求解的主参数；`n` 是动点参数。Method binding 层应读取这些 role，而不是用“排除 `x/a/b/c` 后剩下的字母”来推断。

### Fact Handle

Fact handle 使用：

```text
fact:<scope_id>:<semantic_name>
```

`semantic_name` 应使用稳定、可读的 snake_case，尽量包含关系角色，避免只有泛化类型名。

推荐：

```text
fact:ii:segment_E_on_DM
fact:ii:segment_G_on_MN
fact:ii:segment_DE_eq_sqrt2_NG
fact:ii:right_angle_equal_length_DMN
fact:ii_1:MN_length_squared_eq_10
fact:i:a_value
fact:ii:a_value
fact:ii:N_coordinate_expr
fact:ii_1:N_coordinate_value
fact:ii_1:parabola_equation
```

不推荐：

```text
relation:right_angle_equal_length
condition:MN_length
constraint:quadrant_fourth
relation:point_on_parabola
```

这些名字缺少 scope 或缺少参与对象，容易和 ProblemIR 中的真实关系对不上。

#### Fact semantic_name 命名规范

Fact 的 `semantic_name` 不要求全部以 `_value` 结尾。`_value` 只用于参数、系数、标量这类“某个符号取值”的事实。其他事实应按类型使用稳定后缀或稳定关系模式。

推荐规则：

| Fact 类型 | 命名模式 | 示例 |
| --- | --- | --- |
| 符号/参数/系数取值 | `<symbol>_value` | `fact:i:a_value`、`fact:ii_1:m_value` |
| 点坐标含参表达式 | `<point>_coordinate_expr` | `fact:ii:N_coordinate_expr` |
| 点坐标具体值 | `<point>_coordinate_value` | `fact:ii_1:N_coordinate_value` |
| 函数/曲线解析式 | `<function>_equation` | `fact:ii_1:parabola_equation` |
| 系数关系方程 | `<subject>_relation` 或稳定专名 | `fact:problem:coefficient_relation` |
| 点在线段/直线/曲线上 | `<object>_<point>_on_<container>` 或 `<point>_on_<curve>` | `fact:ii:segment_E_on_DM`、`fact:ii:N_on_parabola` |
| 等长、垂直、直角等腰等几何关系 | `<relation_type>_<participants>` | `fact:ii:right_angle_equal_length_DMN` |
| 长度/距离条件 | `<object>_length_eq_<value>` 或 `<object>_length_squared_eq_<value>` | `fact:ii_1:MN_length_squared_eq_10` |
| 范围/象限/不等式约束 | `<subject>_<constraint>` | `fact:problem:m_gt_2`、`fact:ii:N_fourth_quadrant` |
| 最值条件或最值结论 | `<object>_minimum_value` 或 `<object>_minimum_value_given` | `fact:ii_2:path_minimum_value_given` |

同一个 Entity 在不同 scope 下可以有同名 `semantic_name`，因为完整 handle 包含 scope。例如第一问和第二问里的不同 `a` 值可以表示为：

```text
fact:i:a_value
fact:ii:a_value
```

它们都指向同一个 Entity：

```text
symbol:problem:a
```

但它们是两个不同 scope 下的 Fact，互不覆盖。

### Answer Handle

最终答案目标使用：

```text
answer:<QuestionGoal.id>
```

示例：

```text
answer:i.axis_point
answer:i.parabola
answer:ii_1.parabola
answer:ii_1.minimum_value
answer:ii_2.parabola
answer:ii_2.intersection
```

Prompt 中应直接列出所有可用 `answer:*` handle，LLM 只能复制这些 handle，不能自己创造最终答案 handle。

## 未知对象与推导 Fact

未知对象不需要换名。

例如 `point:ii:N`：

1. 题设阶段：只知道它是待求点，可能有第四象限约束。
2. 中间阶段：由直角等腰关系得到两个候选坐标。
3. 筛选阶段：结合第四象限和 `m>2` 得到含参坐标。
4. 小问阶段：代入 `m=3` 得到具体坐标。

整个过程仍然引用同一个 Entity：

```text
point:ii:N
```

新增的是 Fact：

```text
fact:ii:N_fourth_quadrant
fact:ii:N_coordinate_expr
fact:ii_1:N_coordinate_value
```

这样可以避免 `point:N_expr`、`point:N_final`、`point:N_ii_1` 这类名字污染。

## 辅助点与辅助线

推导过程中允许新增 Entity，但必须明确来源和定义。

辅助点、辅助线、辅助圆等不是 ProblemIR 的题设 Entity，而是由某个 StepIntent 的 `creates` 或 runtime declaration 创建的 derived Entity。

示例：将军饮马中构造 `D'`。

```json
{
  "handle": "point:ii:D_prime",
  "type": "Point",
  "scope_id": "ii",
  "source": "derived",
  "created_by_step": "construct_straightening_candidate",
  "definition": {
    "type": "reflected_point",
    "source_point": "point:problem:D",
    "mirror_line": "line:ii:MN"
  },
  "valid_scope": "ii"
}
```

示例：构造辅助线。

```json
{
  "handle": "line:ii:l_aux",
  "type": "Line",
  "scope_id": "ii",
  "source": "derived",
  "created_by_step": "construct_parallel_line",
  "definition": {
    "type": "parallel_line_through_point",
    "parallel_to": "line:problem:AB",
    "through": "point:ii:N"
  },
  "valid_scope": "ii"
}
```

约束：

- LLM 不能在 `reads` 中直接使用未声明过的辅助 Entity。
- 新辅助 Entity 必须由某个 step 的 `creates` 或 runtime declaration 创建。
- 代码层校验该 step 的 method/recipe 是否允许创建对应类型的 derived Entity。
- 不允许覆盖题设 Entity。
- derived Entity 的 `valid_scope` 不能超过它依赖对象和推导条件的有效范围。

## 推导过程：事实图生长

Method Solver 的 runtime 可以理解为一个带 scope 的事实图。

初始状态来自 ProblemIR：

```text
ProblemIR
  -> 题设 Entity: 点、线、函数、参数
  -> 题设 Fact: 已知关系、约束、条件、目标
```

每个解题 step 做三件事中的一部分：

```text
Step
  reads:    读取已有 Entity / Fact
  creates:  必要时创建 derived Entity
  produces: 产生新的 Fact / answer Fact
```

例如南开 25：

```text
derive_D
  reads:
    function:problem:parabola
    fact:problem:coefficient_relation
  produces:
    fact:problem:D_coordinate_value
    answer:i.axis_point

derive_N
  reads:
    point:problem:D
    point:ii:M
    point:ii:N
    fact:ii:right_angle_equal_length_DMN
    fact:ii:N_fourth_quadrant
    fact:problem:m_gt_2
  produces:
    fact:ii:N_coordinate_expr

construct_D_prime
  reads:
    point:problem:D
    line:ii:MN
  creates:
    point:ii:D_prime
  produces:
    fact:ii:D_prime_reflected_from_D
    fact:ii:path_equivalent_to_D_prime_F
```

这比“先求一个变量，再把变量塞到答案里”的模型更稳，因为它明确区分：

- 新事实是常态：坐标、参数、函数解析式、等价路径、最值表达式都属于 Fact。
- 新对象是少数：辅助点、辅助线、辅助圆等才是 derived Entity。
- 同一个 Entity 不因为 Fact 变化而改名。

### StepIntent 推荐字段

长期推荐让 Strategy Planner 输出更贴近事实图的字段：

```json
{
  "step_id": "derive_D",
  "reads": [
    "function:problem:parabola",
    "fact:problem:coefficient_relation"
  ],
  "creates": [],
  "produces": [
    {
      "handle": "fact:problem:D_coordinate_value",
      "valid_scope": "problem",
      "description": "由对称轴关系求出 D 的坐标"
    },
    {
      "handle": "answer:i.axis_point",
      "valid_scope": "i",
      "description": "第一问要求输出 D 点坐标"
    }
  ]
}
```

辅助构造示例：

```json
{
  "step_id": "construct_D_prime",
  "reads": [
    "point:problem:D",
    "line:ii:MN"
  ],
  "creates": [
    {
      "handle": "point:ii:D_prime",
      "entity_type": "Point",
      "valid_scope": "ii",
      "description": "D 关于 MN 的对称点"
    }
  ],
  "produces": [
    {
      "handle": "fact:ii:D_prime_reflected_from_D",
      "valid_scope": "ii",
      "description": "D_prime 是 D 关于 MN 的对称点"
    }
  ]
}
```

## 跨 step 复用规则

跨 step 复用只通过 Entity / Fact 完成。

如果某个 step 的结果会被后续教学步骤使用，它必须：

- 用 `produces` 写成 Fact；或
- 用 `creates` 创建 derived Entity，并用 `produces` 补充该 Entity 的定义 Fact。

后续 step 直接在 `reads` 中引用这些 Entity / Fact。

不推荐让 LLM 引用前序 step 的临时输出。临时输出只属于 recipe/method runtime 内部，例如：

```text
right_angle_equal_length_candidates
  -> select_point_by_quadrant_constraint
```

这里第一个 method 产生的候选点列表只是第二个 method 的临时输入，不进入事实图，也不暴露成 LLM handle。只有最终筛选出的点坐标需要成为 Fact：

```text
fact:ii:N_coordinate_expr
```

一句话边界：

```text
跨教学 step 复用：读 Entity / Fact
recipe 内部串联：runtime 自己处理临时输出
```

## valid_scope

`valid_scope` 表示 `creates / produces` 生成的对象或事实在哪个 scope 中有效。

示例：

```json
{
  "handle": "point:problem:D",
  "valid_scope": "problem",
  "description": "D 的坐标由整题系数关系确定，全题可用"
}
```

```json
{
  "handle": "fact:ii_1:m_value",
  "valid_scope": "ii_1",
  "description": "由 MN^2=10 得到的 m 值只用于第 ii_1 小问"
}
```

选择原则：

- 由整题题设和整题推导得到的结论，可以是 `problem`。
- 依赖某一大问条件的结论，最多到该大问 scope。
- 依赖某一小问额外条件的结论，只能在该小问 scope。
- derived Entity 的有效范围不能超过其构造依赖的有效范围。

`valid_scope` 表示“结论本身成立的范围”，不是“当前 step 所在范围”。因此代码层会做两类校验：

- 如果某个 `produces` 声明 `valid_scope=ii`，但它的 `reads` 依赖 `fact:ii_1:*` 这类子问专属事实，则失败并反馈 `invalid_valid_scope`。
- 如果某个公共结论先在窄 scope 产生，后面又在父级 scope 重复产生，则失败并反馈 `common_fact_after_narrow_fact`。正确做法是首次产生时就声明合理的公共 `valid_scope`，后续小问直接在 `reads` 中复用。

### 可复用公共事实与最终答案事实

最终答案事实不一定适合作为后续推导的公共输入。典型例子是路径最值：

```text
fact:ii:path_minimum_expression      # 公共最小值表达式，ii_1 和 ii_2 都可读取
answer:ii_1.minimum_value            # 第 ii_1 小问最终答案，只在 ii_1 有效
fact:ii_2:path_minimum_value_given   # 第 ii_2 小问题设给出的最小值条件
fact:ii_2:m_value                    # 第 ii_2 小问由最小值条件反求的参数
```

`parameter_from_minimum_value` 这类 step 必须读取可见的公共 `MinimumExpression` fact，例如
`fact:ii:path_minimum_expression`，不能跨 sibling 读取 `answer:ii_1.minimum_value`。如果 LLM 只在
`ii_1` 产出了最终最小值答案，`ii_2` 反求参数时会收到
`missing_required_runtime_fact: minimum_expression`，提示它需要先产生或读取一个父级公共最小值表达式 fact。

### 重复事实的语义签名

Resolver 会给 `produces` 生成语义签名，用来提前发现重复推导和 scope 错位。常见签名：

```text
point_coordinate:<point_name>
parameter:<symbol_name>
parabola:<valid_scope>
minimum_expr:<valid_scope>
path_transformation:<valid_scope>
```

约束：

- 同一实体的坐标事实不要在父子 scope 中重复推导；后续步骤应直接 `reads` 已有 fact。
- 同一参数值可以在不同 sibling 小问分别产生，例如 `fact:ii_1:m_value` 与 `fact:ii_2:m_value` 是不同条件下的不同事实。
- 如果某结论本来对整个大问有效，例如 `fact:ii:N_coordinate_expr` 或 `fact:ii:path_minimum_expression`，不要先产出 `fact:ii_1:*` 再在 `ii_2` 重算。
- 已经求成 `Point` 的点不能再次作为需要 `PointRef` target 的 method 输入；这种情况会被转成 `duplicate_point_coordinate_fact`，提示后续步骤读取已有坐标 fact。

## Resolver 校验规则

Resolver / Validator 应执行以下检查：

1. `reads` 中所有 handle 必须来自 canonical handle 表或前序 `creates / produces`。
2. LLM 输出中不允许出现 step 临时输出引用；跨 step 复用必须通过 Entity / Fact。
3. `creates.handle / produces.handle` 必须符合命名规范。
4. 新 derived Entity 必须有 `source=derived`、`created_by_step` 和可解释的 `definition`。
5. 不能覆盖 locked 题设 Entity / Fact。
6. `valid_scope` 必须存在，且不能超过依赖对象和条件的可见范围。
7. 同一个 Entity 不能因为求出新值而重新命名。
8. scope 内同名 Fact 冲突时失败，不做模糊合并。
9. `produces` 只能新增 Fact / answer Fact；`creates` 只能新增 derived Entity，二者不能混用。

错误反馈给 LLM 时应使用 handle 语言，而不是内部 ContextPath：

```json
{
  "code": "unknown_read_handle",
  "step_id": "select_N_by_quadrant",
  "handle": "constraint:quadrant_fourth",
  "message": "reads 中引用了不存在的 handle",
  "available_handles": [
    "fact:ii:N_fourth_quadrant",
    "fact:ii:right_angle_equal_length_DMN",
    "point:ii:N"
  ],
  "suggestion": "如果要使用 N 在第四象限的条件，请引用 fact:ii:N_fourth_quadrant"
}
```

## 是否解决 reads 自造 handle 问题

这套设计可以解决“LLM reads 与 ProblemIR 对不上”的核心问题，但前提是实现上坚持三条边界：

1. **canonical handle 表由代码生成。**  
   LLM 只能从 prompt 中列出的 Entity / Fact / answer handle 中复制，不能创造新的题设 handle。

2. **StepIntentValidator 拒绝未知 handle。**  
   例如 `relation:right_angle_equal_length`、`constraint:quadrant_fourth` 这类不在 canonical handle 表中的写法应直接失败，并进入 repair loop。

3. **辅助对象只能通过 `creates` 或 runtime declaration 创建。**  
   如果 LLM 需要 `point:ii:D_prime`，它必须先在某个 step 的 `creates` 或 runtime declaration 中声明这个 derived Entity；后续才能在 `reads` 中引用。

换句话说：这不是让 Resolver 做更多模糊匹配，而是把“可引用对象集合”前置成一个受控词表。LLM 做解题步骤规划，代码负责维护词表、校验引用和映射到 RuntimeContext。

## 与 ProblemIR 的关系

Canonical ProblemIR schema 直接显式保存以下内容：

- `entities[]`：Entity 一等表，保存点、线、线段、函数、参数等 canonical Entity。
- `facts[]`：Fact 一等表，保存题设关系、约束、点在线上、点在曲线上、等长、垂直、长度条件、题设给定值等 canonical Fact。
- QuestionGoal：最终作答目标。
- Scope tree：整题、大问、小问的层级。

RuntimeProjection 从这份 canonical ProblemIR 派生两类视图：

- runtime-compatible view：供 `ContextBuilder` 构建 `RuntimeContext`；
- LLM payload view：供 Strategy prompt 使用，只包含 canonical handles。

fixture 不再手写旧 runtime 兼容字段，也不维护单独 `.llm.json`。若 canonical ProblemIR 与 runtime/LLM projection 表达冲突，应视为 ProblemIR 抽取或 projection 错误，而不是让 Resolver 做模糊猜测。
