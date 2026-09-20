# Capability 数学参数契约草案（首选表达 / 兜底表达 / 基本条件）

2026-09-18。契约已接入生产 Planner 的数学参数投影与绑定适配层。

依据：

- [hexi-sample-01-review](hexi-sample-01-review/README.md)
- [hexi-sample-02-review](hexi-sample-02-review/README.md)
- [hexi-sample-03-review](hexi-sample-03-review/README.md)

范围：河西一模数学参数批次实际 Prompt 里的 **Functional Capability Catalog**（三组 sample 首轮 Catalog SHA 一致）。

## 数量

| 口径 | 数量 |
|---|---:|
| 本批次 Prompt Catalog 中的 capability | **16** |
| 上述 capability 的公开 args 合计 | **43** |
| 其中本三组 sample 实际调用过的 capability | 8（见下） |

三组真实失败直接打到的参数（契约优先）：

| 优先级 | 参数 | sample 证据 |
|---|---|---|
| P0 | `right_angle_equal_length_candidates` 的直角条件与等长条件 | 1/2/3 均把两个基本条件塞进自定义 Fact；2 还猜出 `∠CAD∈90°`；3 用集合式 |
| P0 | `quadratic_from_constraints.curve_points` / `curve_point` | 1/2/3 出现 `A=(-1,0)` |
| P1 | `quadratic_y_axis_intercept_point.quadratic` | sample1 S3 误写 `parabola`（Catalog 名已对，属防漂移） |
| P1 | `right_angle_equal_length_*` 条件内 reference 角色 | sample3：缺 C 坐标状态被逗号错误遮蔽 |
| P1 | `quadratic_vertex_point.parabola` 模板直读说明 | sample3 S3：按 role 省略建曲线后触发 `functional_arg_version_drift`（契约措辞与实现一致性，另题） |

其余 args 本批次未因表达绑死，仍一并列出，便于统一字段形状后逐条确认。

## 建议的 `math_argument` 字段形状

在数学表达模式下，`math_argument` 替代原先外层 `arg` 的参数描述。Prompt 不再同时发送两套契约；每个参数只保留参数名和一个完整的 `math_argument`：

```json
{
  "name": "curve_points",
  "math_argument": {
    "encoding": "math-expression/v1",
    "domain_type": "Point",
    "required": true,
    "cardinality": "many",
    "form": "object_reference",
    "preferred_examples": ["A"],
    "fallback_examples": ["A=(-1,0)"],
    "invalid_examples": ["D ∈ Γ"],
    "note": "优先写已有点身份；坐标只按唯一可见对象规则兜底。"
  }
}
```

外层 `arg` 不再重复发送 `domain_type`、`required`、`cardinality`、`role`、`fact_types`、`accepted_item_types` 或其他旧参数说明。`name` 只是参数键，不属于重复契约；Capability 的返回值和方法选择说明仍保留在 Capability 层。

`math_argument` 的字段形状如下：

| 字段 | 含义 |
|---|---|
| `form` | 表达形态标签：`object_reference` / `equation` / `membership` / `extremum` / `symbol` / `curve_or_expression` |
| `preferred_examples` | 首选表达（1–3 个，与 binder 真实可匹配拼写一致） |
| `fallback_examples` | 解析器可安全兜底的表达；不鼓励模型优先使用 |
| `invalid_examples` | 明确不属于该参数的写法，不能只靠提示词放宽 |
| `note` | 注意事项（短句；可与 `role` 互补，不重复长文） |

约定：

1. `preferred_examples` 必须来自 binder / 可见源拼写，不能发明新文法。
2. `fallback_examples` 必须有对应的受信证据、唯一匹配规则和单元测试；它们是代码容错，不是新的题设来源。
3. 数学参数不再暴露自定义复合 Fact。一个 Method 需要多个条件时，参数契约列出多个基本表达式，由绑定层分别解析。
4. Point 参数首选对象身份；坐标只能作为明确声明的兜底表达，不能生成新对象。
5. 参数名以 Catalog `name` 为准（如截距用 `quadratic` 不是 `parabola`）。
6. **本表是 Prompt 契约草案**；完整运行时校验、诊断改写、多错收集、模板物化版本账本另案，不在此表假装已解决。

### 公开数学表达与内部兼容边界

本草案改变的是 `math-expression/v1` 的公开参数表达，不兼容旧的数学 Prompt catalog 形状，也不保留旧外层 `arg` 描述。已保存的 `source-ref` 规范计划、Method 执行输入、Scope、Goal、状态与事务仍按原路径处理。新 Planner 对需要多个条件的 Method 输出多个基本参数；编译适配层负责把基本 Fact 引用接入现有角色解析。

讨论状态：`待讨论` → `已定` / `暂缓` / `不改`。

---

## 1. `quadratic_from_constraints` — 待讨论

### 1.1 `known_coefficients`（Fact / many）

| | 现状 | 修改后草案 |
|---|---|---|
| `math_argument` | `Fact` + `symbol_value` | + `form=equation`，`preferred_examples=["a=1","b=2"]`，`invalid_examples=["a","1"]` |
| `note` | （无） | 写系数等式；多个系数都放本参数，不要塞进 `parameter_value` |
| 证据 | sample 多数写对 | 低风险补齐 |

### 1.2 `coefficient_relation` / `extra_equation`（Fact / one）

| | 现状 | 修改后草案 |
|---|---|---|
| `math_argument` | `Fact` + 关系类 fact_types | + `form=equation`，`preferred_examples=["a=b"]` 类题面关系 |
| `invalid_examples` | （无） | `b>0`（范围应走别处）、逗号拼多式 |
| `note` | role 已区分 | 保持：范围/不等式不进这两个参数 |

### 1.3 `curve_point` / `curve_points`（Point）— **P0**

| | 现状 | 修改后草案 |
|---|---|---|
| `role` | 「已知**坐标**的曲线点」易误导 | 「引用已有点对象；坐标已在题设 facts」 |
| `math_argument` | 仅 `domain_type: Point` | 见下 |

**现状：**

```json
{"encoding":"math-expression/v1","domain_type":"Point"}
```

**修改后：**

```json
{
  "encoding": "math-expression/v1",
  "domain_type": "Point",
  "required": true,
  "cardinality": "many",
  "form": "object_reference",
  "preferred_examples": ["A"],
  "fallback_examples": ["A=(-1,0)"],
  "invalid_examples": ["D ∈ Γ"],
  "note": "优先写已有点身份。若收到 A=(-1,0)，仅在当前 Scope/祖先 Scope 的受信坐标证据中唯一反查到 A 时转换为 A；不创建 Point。many 用数组，单点可用 curve_point 或 curve_points:[A]。"
}
```

兜底第一版只接受“点名=坐标”的明确形式，例如 `A=(-1,0)`；裸坐标 `(-1,0)` 暂不自动猜对象。0 个匹配返回 unresolved，多于 1 个匹配返回 ambiguous。坐标比较只做受限规范化，不求解、不创建对象、不跨兄弟 Scope。

证据：sample1 S1；sample2 S3；sample3 S2（含单字符串 `curve_points:"A=(-1,0)"`）。

### 1.4 `free_parameters`（Symbol / many）

| | 现状 | 修改后草案 |
|---|---|---|
| `math_argument` | 仅 Symbol | `form=symbol`，`preferred_examples=["b"]` / `["c"]`，`invalid_examples=["b>0"]` |
| `note` | role 已较长 | 开放态非空基底；闭合可用 `[]`；勿用下游 Goal 收窄 |

### 1.5 `parameter_value` / `target_parameter`（Symbol / one）

| | 现状 | 修改后草案 |
|---|---|---|
| `preferred_examples` | （无） | `["b"]` |
| `invalid_examples` | （无） | `["a=1","b=2"]`（多系数应进 `known_coefficients`） |

---

## 2. `quadratic_y_axis_intercept_point` — 已定

### 2.1 `quadratic`（Expression / latest state）— **P1**

| | 已落地 | 约定 |
|---|---|---|
| 参数名 | `quadratic` | **保持**；勿写成 `parabola` |
| slot | `Expression` + `latest_state`，**不是** `_parabola_read` | 保留「只取 x=0、可含未定系数」 |
| Prompt role | 须读 Method 产生的表达式状态；禁止题面 Function 模板直读 | 与 vertex/x 截距禁令对齐 |

证据：河西 sample1 S3 误写 `parabola`；和平二模 live 中止在 **x 轴**截距（`_parabola_read`），y 轴为契约一致性修补。

---

## 3. `parameter_from_expression_value` — 待讨论

| 参数 | 现状 | 修改后草案 |
|---|---|---|
| `expression` | Expression | `form=curve_or_expression`；通常 StepResultRef；若写数学串则跟前序 min 表达式一致 |
| `minimum_value` | Fact + `minimum_value` | `form=equation`，`preferred_examples=["min(sqrt(2)*MN+AN)=21/4"]`，`invalid_examples=["21/4"]`（缺左边极值） |
| `parameter` | Symbol | `preferred_examples=["b"]` |

本批次写法基本正确；补样例防省略。

---

## 4. `evaluate_expression_at_parameter` — 待讨论

| 参数 | 现状 | 修改后草案 |
|---|---|---|
| `expression` | Expression + 长 role | `note` 强调：题面 Function 模板 ≠ 已求得的 Parabola 状态（与 sample3 模板直读问题同族） |
| `parameter` / `parameter_value` | Symbol | `preferred_examples=["b"]` / 对应已求值拼写 |

本批次未调用；字段形状对齐即可。

---

## 5. `evaluate_point_at_parameter` — 待讨论

| 参数 | 现状 | 修改后草案 |
|---|---|---|
| `point` | Point | `form=object_reference`，`preferred_examples=["M"]`，`fallback_examples=["M=(b+1/2,y_M)"]` |
| `parameter_value` | Symbol | 同 4 |

---

## 6. `distance_between_points` — 待讨论

| 参数 | 现状 | 修改后草案 |
|---|---|---|
| `p1` / `p2` | Point | `object_reference`，`preferred_examples=["M","N"]`，坐标式仅在唯一反查时兜底 |
| `parameter_value` | Symbol optional | `preferred_examples=["b"]` |

---

## 7. `line_intersection_point` — 待讨论

| 参数 | 现状 | 修改后草案 |
|---|---|---|
| `line1_p1`…`line2_p2` | Point | 首选对象引用；坐标式按统一 Point 兜底规则处理 |
| `parameter_value` | optional | 同上 |

---

## 8. `translated_point` — 待讨论

| 参数 | 现状 | 修改后草案 |
|---|---|---|
| `source` | Point，role 空 | `preferred_examples=["A"]`；`note`：位移量若由能力隐式绑定，勿把向量塞进 source |

（若公开还有其它 args，以 Catalog 为准补行。）

---

## 9. `right_angle_equal_length_candidates` — 待讨论（**P0**）

### 9.1 `target`（Point）

| | 现状 | 修改后草案 |
|---|---|---|
| `math_argument` | 仅 Point | `form=object_reference`，`preferred_examples=["D"]`，坐标式按统一 Point 兜底规则处理 |

### 9.2 直角条件与等长条件（两个基本表达式）— **P0 核心**

| | 现状 | 修改后草案 |
|---|---|---|
| `angle` | 没有独立公开参数；藏在 `right_angle_equal_length` Fact 中 | `Fact[angle_equality]`，`form=equation`，`preferred_examples=["∠CAD=90°"]` |
| `equal_length` | 没有独立公开参数；藏在 `right_angle_equal_length` Fact 中 | `Fact[segment_length_relation]`，`form=equation`，`preferred_examples=["AC=AD"]` |
| 条件内点 | 未说明要有坐标状态 | 继续执行该 Method 原有的可见性和状态前置条件；数学绑定层不创建或补充状态 |

**现状：**

```json
{
  "args": {
    "target": "D",
    "right_angle_equal_length": "∠CAD=90° ∧ AC=AD"
  }
}
```

**修改后：**

```json
{
  "args": {
    "target": "D",
    "angle": "∠CAD=90°",
    "equal_length": "AC=AD"
  }
}
```

`angle` 和 `equal_length` 分别绑定到已有的基本 Fact（如 `angle_equality` 与 `segment_length_relation`）。Method 的现有执行输入、Scope、Goal、依赖、状态与事务不变；编译适配层只把这两个基本 Fact 引用接入原有的角色解析和 Method 调用。`right_angle_equal_length` 不再作为数学模式的公开参数名，也不再由数学解析器把两个表达式重新拼成一个自定义 Fact；旧数学表达录制不作为本轮兼容目标，需要复现时使用原始 `source-ref` 计划或重新生成数学表达计划。

模型不再需要学习 `∧` 来填一个复合参数：

```text
angle:        ∠CAD=90°
equal_length: AC=AD
```

以下写法属于参数拆分错误或错误表达，应分别诊断，不做隐式修复：

```text
right_angle_equal_length: "∠CAD=90°, AC=AD"
angle: "∠CAD∈90°"
angle: "D ∈ {X | ∠CAX=90°, AX=AC}"
```

证据：三组 sample 首轮均把两个基本条件塞进自定义 Fact；sample2 S3 将等式误写成 `∈`；sample1 S3 使用不受支持的集合式；sample3 另有 C 状态前置条件问题。

---

## 10. `right_angle_equal_length_construct_and_select` — 待讨论

与 §9.2 **同一组基本条件契约**（`angle` + `equal_length`）。本批次未直接调用，但 Catalog 并列存在，必须同步，避免一处继续暴露自定义 Fact。

`capability_math_signatures` 已经按 `angle=90°` / `OA=OB` 分条，契约草案与它保持一致；不再改成合取一体。

### 10.1 基本 Fact 的投影迁移

当前问题域投影会把同一 Scope 中的一条 `right_angle` 和一条 `equal_length` 配对，生成 `right_angle_equal_length`，并把两条原始事实标记为已配对。这个组合逻辑正是自定义 Fact 的来源。改造时应改为：

1. 分别投影直角基本事实与等长基本事实，保留各自的 source unit、Scope、valid_scope 和对象引用；
2. Capability Catalog 对外暴露两个基本参数，分别校验 `angle` 与 `equal_length`；
3. 条件角色解析器从两个基本 Fact 引用中得到同一组 anchor/reference/target 角色，再进入原有 Method 调用；
4. 新投影不再生成 `right_angle_equal_length` handle。已经落盘的 `source-ref` 规范计划属于既有内部结果，不经过新的数学表达绑定，也不需要由本契约重新解释。

这一步不是让数学绑定层重新组合两个字符串，而是让事实投影、Capability 契约和条件角色解析共同使用两个基本事实。执行函数仍收到原有的对象和状态输入；Scope、依赖、前置条件、retry、事务和结果身份不改变。

---

## 11. `weighted_axis_path_minimum` — 待讨论

| 参数 | 现状 | 修改后草案 |
|---|---|---|
| `path_minimum_target` | Fact + type | `domain_type=Expression`，`form=path_sum`，`preferred_examples=["sqrt(2)*MN+AN"]`，`invalid_examples=["min(sqrt(2)*MN+AN)"]`；直接写目标表达式，最小化由 Method 语义提供 |

本批次写法正确；机制示例已覆盖。仍补正反例以防省略 `min(...)`。

### 11.1 路径最小值 Method 的共同参数契约

`coupled_segment_endpoint_replacement_path_minimum`、
`weighted_axis_path_minimum` 以及同类路径最小值 Method 的
`path_minimum_target` 都使用同一套数学参数形状：

```json
{
  "domain_type": "Expression",
  "form": "path_sum",
  "preferred_examples": ["EG+FG"],
  "invalid_examples": ["min(EG+FG)", ["EG", "FG"]]
}
```

表达式直接写要最小化的路径（加权项可写成 `sqrt(2)*MN+AN`）；`min(...)`
由 Method 本身提供，不能作为参数外壳，也不能拆成数组。绑定层只把该表达式
匹配到当前 Scope 可见的既有 `path_minimum_target` 来源，再交给原有 Method
和执行器。它不创建路径 Fact、不计算最小值，也不把子 Goal 中不可见的路径表达式
提升到父 Scope；匹配不到唯一受信来源时继续走既有诊断和 retry 路由。

---

## 12. `quadratic_vertex_point` — 待讨论（**P1 措辞/实现一致性**）

### 12.1 `parabola`（QuadraticFunction）

| | 现状 | 修改后草案 |
|---|---|---|
| `role` | 允许「可见系数可确定性物化时直接引用题面 Function 模板」 | **两选一，需讨论定稿** |
| A | 收紧 role：开放计划中应先 `quadratic_from_constraints` 再引用返回的抛物线状态；模板直读留给实现修好版本账本之后 | |
| B | 保留 role，但 `note` 标明：当前若直接写 `Γ` 可能触发配置错误，推荐显式建曲线 step | |

**现状 `math_argument`：** 仅类型。

**修改后（数学拼写层，与策略分流）：**

```json
{
  "encoding": "math-expression/v1",
  "domain_type": "QuadraticFunction",
  "form": "object_reference",
  "preferred_examples": ["Γ"],
  "invalid_examples": ["y=a*x^2-b*x+c"],
  "note": "写函数对象名。是否允许无建曲线 step 直读模板，见 role；与 math 拼写无关的版本账本问题另修。"
}
```

证据：sample3 S3 按现 role 省略 I 问建曲线 → 离线暴露 `planner.functional_arg_version_drift`。

---

## 13. `quadratic_x_axis_intercept_point` — 待讨论

| 参数 | 现状 | 修改后草案 |
|---|---|---|
| `parabola` | 同 vertex 的模板物化 role | 与 §12 同一决策 |
| `known_point` | Point optional | `object_reference`；`invalid_examples`：正在求的目标点自身 |

---

## 14. `point_on_parabola_at_x` — 待讨论

| 参数 | 现状 | 修改后草案 |
|---|---|---|
| `parabola` | 同 §12 role | 与 §12 同一决策；本批次多用 Step 产物或 `Γ` 字符串 |

横坐标来自结构化题设时由 binding 隐式读取——若属实，`note` 写清「不要把 `M=(b+1/2,y_M)` 塞进 parabola 参数」。

---

## 15. `line_parabola_second_intersection_point` — 待讨论

| 参数 | 现状 | 修改后草案 |
|---|---|---|
| `parabola` | 同 §12 | 同决策 |
| `line_p1` / `line_p2` / `known_point` | Point + 长 role | 对象引用；`known_point` 通常复用线上已知交点 |

本批次未调用。

---

## 16. `curve_candidate_parameter_solve` — 待讨论

| 参数 | 现状 | 修改后草案 |
|---|---|---|
| `candidates` | Point many；role 强调须为前序构造结果 | `note`：必须 StepResultRef 列表语义；勿填目标点名充数 |
| `parabola` | QuadraticFunction | 对象名或前序返回 |
| `target_point` | Point | `preferred_examples=["D"]`；不是 candidates 替代 |
| `point_on_curve` | Fact | `form=membership`，`preferred_examples=["D∈Γ"]`，`invalid_examples=["D=Γ"]` |
| `symbol_constraint` | Fact | `form=equation`（不等式），`preferred_examples=["b>0"]`；多约束才需手填消歧 |

本批次 `D∈Γ` / `b>0` 基本正确。

---

## 总表（便于打勾）

| # | capability | 本批次是否调用 | 契约优先级 | 讨论状态 |
|---:|---|---|---|---|
| 1 | `quadratic_from_constraints` | 是 | P0（curve_point*） | 待讨论 |
| 2 | `quadratic_y_axis_intercept_point` | 是 | P1 | 已定 |
| 3 | `parameter_from_expression_value` | 是 | P2 | 待讨论 |
| 4 | `evaluate_expression_at_parameter` | 否 | P2 | 待讨论 |
| 5 | `evaluate_point_at_parameter` | 否 | P2 | 待讨论 |
| 6 | `distance_between_points` | 否 | P2 | 待讨论 |
| 7 | `line_intersection_point` | 否 | P2 | 待讨论 |
| 8 | `translated_point` | 否 | P2 | 待讨论 |
| 9 | `right_angle_equal_length_candidates` | 是 | P0 | 待讨论 |
| 10 | `right_angle_equal_length_construct_and_select` | 否 | P0（与 9 同步） | 待讨论 |
| 11 | `weighted_axis_path_minimum` | 是 | P2 | 待讨论 |
| 12 | `quadratic_vertex_point` | 是 | P1（role/实现） | 待讨论 |
| 13 | `quadratic_x_axis_intercept_point` | 否 | P1（随 12） | 待讨论 |
| 14 | `point_on_parabola_at_x` | 是 | P1（随 12） | 待讨论 |
| 15 | `line_parabola_second_intersection_point` | 否 | P2 | 待讨论 |
| 16 | `curve_candidate_parameter_solve` | 是 | P2 | 待讨论 |

## 建议讨论顺序

1. **统一字段形状**（`form` / `preferred_examples` / `fallback_examples` / `invalid_examples` / `note`）是否采纳。
2. **P0**：§1.3 Point、§9.2 / §10 基本条件拆分。
3. **P1**：§2 参数名防漂移；§9 条件点须有状态；§12 模板直读 role 选 A 还是 B（实现另修）。
4. **P2**：其余 capability 按表补正反例，避免只修「坏过的两个参数」。

从 **§1 `quadratic_from_constraints`** 或 **§9 直角等长** 开始逐条改状态即可。
