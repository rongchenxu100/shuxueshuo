# 基本不等式表达式优先 Method 实施计划

> 状态：阶段 1–4 已实施；阶段 5 按代表题与 Method 集成验收推进，尚未开始实现。更新：2026-09-25（重排阶段 5–7 职责与完成标准）。
> 设计入口：[基本不等式 Method 与讲解设计](basic-inequality-method-discussion.md)。

## 1. 目标与原则

本计划的产品目标是：让 `inequality-basic-q01` 至 `inequality-basic-q31` 全部通过同一条求解、讲解和网页生成链，形成一组可以泛化到其他基本不等式题目的通用 Method 能力。

统一链路为：

```text
题意抽取
→ 直接数学表达式
→ 表达式 Parser / Typecheck
→ FunctionalPlan / Method 编译
→ Runtime 验证或计算
→ Canonical Fact / ExplanationSnapshot
→ LessonIR / VisualStepIR
→ 基本不等式网页
```

必须遵守以下原则：

1. **数学表达式优先。** LLM 输出 `a+b≥2√(a*b)`、`u:=x²`、`x=±√u` 和完整等价式链；逻辑关系首轮只使用数学符号 `∵`、`∴`，不输出自然语言、内部 AST、Fact ID、`term1`、`term2` 或操作标签。
2. **8 个 Method 统一协议。** M01、M07、M08、M09、M11、M12、M13、M14 都接收直接数学表达式；有的验证候选，有的根据已验证表达式计算唯一结果。
3. **候选与事实分离。** LLM 输出在 Parser 和 Runtime 验证前只是候选，不能直接写入 StateVersion、Canonical Fact 或答案。
4. **来源表达式保留。** 保存原始数学字符串、source path、表达式树节点、规范 AST、前提、proof 和规则集 hash；规范化不能覆盖原文。
5. **有限规则、失败闭合。** 先支持可证明的数学模板；无法唯一解析、无法证明正性、定义域或可达性时，返回结构化诊断，不猜测、不静默降级为错误答案。
6. **按数学机制泛化。** 不能为 q01 至 q31 分别写求解分支；题号只允许出现在 fixture、页面产物和回归定位中。
7. **代表题驱动交付。** 每个新 Method 先有实际调用它的失败集成测试，再完成数学验证、Runtime 接入、原题闭合和学生页面；只有单元测试或答案正确，不能标记 Method 完成。

## 2. 当前基线与差距

当前已有（截至 2026-09-25）：

- 阶段 1 的 20 份冻结抽取样本、10 题 ProblemIR，以及离线回放和确定性构建检查；
- 阶段 2 安全 Parser 和阶段 3 有界、可回放证明内核；M01 已迁移到新解析与证明路径，旧有理式解析兼容入口保持不变；
- M11 局部双项 AM-GM、连续求界，以及 M13 最大/最小值、有限见证和经过验证的联立取等推导；
- q01、q03、q07、q08 的 authoring 求解闭环与学生网页，Method 教学投影、rule 编排和统一 VisualSpec 绑定；
- FunctionalPlan 的参数绑定、状态版本、provenance、事务回滚和 retry 基础设施；
- 版本化教学模板、Family 六类思路背景和本题实际路线注入；已有真实调用、录制响应、执行产物与页面回归记录。

当前差距：

- M07、M08、M09、M12、M14 尚待实现；其换元/消元还原、跨类型连续求界及范围闭合需要相应的 Runtime 与 M13 配套；
- `basic_inequality` 仍只在显式 authoring Registry 开放，尚未进入生产默认 Registry；
- 其余代表题尚未全部通过“新 Method 实际调用 → 原题闭合 → 教学页面”验收；31 题全面迁移仍在后续阶段。

## 3. 目标协议

### 3.1 最小公共表达式协议

公开调用保留现有 `step_id`、`capability_id` 和 `args` 外壳。所有表达式型 Method 的 LLM-facing 候选只使用 `math` 或 `steps[].math`；M01 等多步 Method 使用 `steps[]`。题设条件、变量域、前提选择、目标角色和已验证中间事实由编译器从当前 Scope 绑定或从表达式链推导，不要求 LLM 填写语义角色字段。

例如，M11 可以只提交：

```json
{
  "math": "a+b+1≥2√(a*b)+1"
}
```

这里必须使用当前题目的完整表达式；`R`、`U`、`V` 等未在 Scope 中声明的占位符不能进入生产 Prompt。代码从当前上下文取得 `a>0`、`b>0`，从前后式差异恢复局部关系，再由 AM-GM 规则自动生成 `a=b`。

编译器内部仍然可以产生 `condition_bindings`、`target_role`、`equality_conditions` 和 `restoration_branches`，但这些不是 LLM 输出字段。代码通过表达式前后关系、当前 Scope 的可见事实和 Method contract 推导它们；出现多个同样合法的推导时返回歧义诊断，不让 LLM 选择内部角色。

下列内容不进入 LLM-facing 协议：

- `term1`、`term2`、`operation`、`ast_kind`；
- `fact_id`、`state_version`、`source_ref`；
- `bound_fact_id`、`method_output_key`、`rule_id`；
- 由代码才能确定的根、区间、正项身份和 Canonical Fact。

因此，公共协议不再强行定义一个包含 `math`、`using`、`equality`、`restore` 的“大而全”对象，而是采用“直接数学表达式 `math` + 编译器推导内部关系”的形式。

### 3.1.1 受控逻辑符号

首轮只引入两个因果符号：

```text
∵ 前提表达式₁，前提表达式₂
∴ 结论表达式
```

例如：

```json
{
  "steps": [
    {"math": "u:=x²"},
    {"math": "v:=y²"},
    {"math": "∵ 5*x²*y²+y⁴=1"},
    {"math": "∴ 5*u*v+v²=1"},
    {"math": "∵ a>0，b>0"},
    {"math": "∴ a+b+1≥2√(a*b)+1"}
  ]
}
```

换元不使用“设”字段；`u:=x²`、`u≔x²`表示定义，首选 `:=`。`=`保留为普通等式，`≡`表示恒等关系，不作为首轮换元定义符号。

Parser 只识别 `∵`、`∴`、`:=`、`≔` 和数学关系本身，生成内部的 premise/conclusion/definition 标记；这些标记不由 LLM 填写。`∵` 行只允许顶层逗号分隔的并列前提，逗号表示前提合取；`∴` 行只允许一个结论关系。前提行和结论行按相邻顺序配对，必要时由代码记录明确的步骤范围。没有标记的行可以按单纯数学表达式处理；出现孤立或不相邻的标记时返回步骤级诊断。Parser 只建立句法关联，关系证明留给后续内核。首轮不引入“因为、所以、由、得、利用、应用基本不等式”等自然语言关键词。

字段定义明确如下：

| 字段 | 层级 | 是否必填 | 定义 |
|---|---|---:|---|
| `step_id` | 调用外壳 | 是 | 本次公开步骤的稳定标识；不是数学事实。 |
| `capability_id` | 调用外壳 | 是 | LLM 选择的公开能力；不是内部 `method_id` 或 AST 类型。 |
| `args` | Runtime 调用外壳 | 是（内部） | 当前 Scope 已绑定的输入，例如目标 Expression 和可见条件集合；LLM-facing 输出通常省略，由编译器注入。 |
| `parameters` | 调用外壳 | 视 Method | 当前 Method 的数学候选；其中的值必须是直接数学表达式。 |
| `math` | Method 参数 | 单关系 Method 必填 | 一条完整等式或不等式；M11、M14 使用此字段。 |
| `steps` | Method 参数 | Method-specific | 有序数学表达式数组；每项只有 `math`，可在表达式内部使用 `∵`、`∴` 或 `:=`。 |
| `using` | Runtime 内部 | 不输出 | 编译器从表达式差异和可见条件推导实际使用的前提。 |
| `definition` | Runtime 内部 | 不输出 | 从换元或和积表达式中识别出的定义关系。 |
| `transformed_target` | Runtime 内部 | 不输出 | 从输入目标和表达式链推导出的目标状态。 |
| `transformed_conditions` | Runtime 内部 | 不输出 | 从表达式链和原条件推导出的新可行域。 |
| `elimination` | Runtime 内部 | 不输出 | 从消元表达式中识别出的消元关系。 |
| `restore` | Runtime 内部 | 不输出 | 从还原表达式中识别出的分支和反向映射。 |
| `equality` / `equalities` | Runtime 内部 | 不输出 | 从不等式模板、平方项或闭合表达式生成的取等候选。 |
| `domain` | Runtime 内部 | 不输出 | 从当前 Scope 和表达式 free symbols 推导的变量域。 |

因此，LLM-facing 的典型输出是：

```json
{
  "capability_id": "apply_two_term_amgm",
  "parameters": {
    "math": "a+b+1≥2√(a*b)+1"
  }
}
```

这里 `parameters.math` 是 LLM 提交的候选不等式。当前表达式、题设条件和前一步 Method 输出由编译器从 Scope 自动绑定；`step_id`、内部 `args.expression` 和 StateVersion 由编译器/runtime 注入，不属于模型需要填写的数学内容。标准 AM-GM 不需要 `using` 或 `equality`。

`args.expression` 如果出现在内部 Method contract 中，表示“本次 Method 要读取的当前 Expression 状态”，不是字符串值 `current_expression`，也不是 LLM 要构造的字段。

### 3.2.1 统一的表达式链输入

为避免 Method-specific 语义字段被模型误用，首轮统一采用以下形式：

```json
{
  "parameters": {
    "steps": [
      {"math": "u=x²"},
      {"math": "5*u*v+v²=1"},
      {"math": "x²+y²=u+v"},
      {"math": "x=±√u"}
    ]
  }
}
```

每一行都是完整数学表达式，可在表达式内部使用 `∵`、`∴` 或 `:=`。Method contract 根据输入对象、表达式关系和预期输出类型判断哪一行是定义、目标改写、前提改写或还原关系。M11/M14 只有一条关系时可使用 `math` 简写；M01 使用 `steps` 保留完整等价链。必要的前提绑定由代码尝试从当前 Scope 的可见条件中证明：先尝试单个条件，再尝试有界的条件组合；唯一成功时记录内部 provenance，多解时返回 `premise_ambiguous`，无解时返回 `premise_unresolved`。

如果推断失败，Runtime 不要求 LLM 填写 `using`、`transformed_target` 或其他角色字段，而是返回可直接执行的数学诊断。诊断至少包含失败步骤号、原始表达式、前后表达式、期望关系类型、缺失的前提或证明、当前可见候选条件，以及建议补充的直接数学步骤。LLM 只需在原 Scope 内补充或改写数学表达式；补充内容仍须经过同一 Parser、证明内核和 Method contract 验证。

例如：

```json
{
  "code": "premise_unresolved",
  "step": 3,
  "message": "无法从当前条件证明分母 x+1 非零",
  "expected": "补充由已有条件推出 x+1>0 或 x+1≠0 的数学表达式步骤",
  "visible_conditions": ["x>-1"]
}
```

Repair Prompt 应要求模型补充 `x+1>0` 这样的直接数学表达式，不得要求模型选择内部前提 ID。若补充步骤仍无法证明，继续 fail closed；不能把模型的断言直接提升为事实，也不能扩大原 Scope 的可见条件和权限。

### 3.2 八个 Method 的公开输入和输出

| Method | LLM 直接提供 | Runtime 负责 | 成功输出 |
|---|---|---|---|
| M01 `organize_expressions` | 完整等价式链 | 等价、条件代入、定义域和结构分类 | 等价 Expression 状态与 rewrite trace |
| M07 `introduce_semantic_substitution` | `steps[].math`：换元、改写和还原表达式 | 映射、可行域、非一一分支和还原 | substitution Fact 与新表达式状态 |
| M08 `eliminate_by_constraint` | `steps[].math`：消元、代入和范围表达式 | 除法前提、等价代入和范围 | elimination Fact 与降维状态 |
| M09 `reduce_symmetric_sum_product` | `steps[].math`：和积定义、转换和还原式 | 对称性、判别式、实根和正根条件 | sum-product Fact 与可行域 |
| M11 `apply_two_term_amgm` | `steps[].math` 的 `∵` 前提行 + `∴` 结论行；前提已在 Scope 时可省略 | 完成正项识别、模板匹配、方向和目标对应 | `amgm_bound` Fact 与等号条件 |
| M12 `bound_univariate_quadratic` | `steps[].math`：配方式和下界关系 | 平方非负、参数域、界可达性 | `quadratic_bound` Fact |
| M13 `close_equality_and_restore` | `steps[].math`：取等、分支还原和原题代回 | 联立、分支、可达性和原题验算 | extremal witness 或完整可达性证据 |
| M14 `solve_univariate_inequality` | 一条完整 `math` 不等式；变量域从 Scope 读取 | 代码计算精确解集 | interval solution；LLM 不填根和区间答案 |

M13 可以在公开能力层保持为 Family closure/Macro；如果内部保留 kernel，也不能要求 LLM 了解其内部 wiring。M11、M13 接受有界的完整数学推导，不限定前提和结论只能写两行。`∵/∴` 为讲解标记，每条关系仍需验证；标记本身不授予前提权限。

## 4. 分阶段实施

### 阶段 0：冻结提取契约和代表性 DeepSeek 集成测试

任务：

- 只验证 `problem-math-notation/v1` 的“图片 → 数学记法候选”链路，不调用 Method、ProblemIR、Runtime binding 或网页生成；
- 使用 `server/shuxueshuo_server/problem_understanding/notation_family_catalog.py` 和 `internal/llm-prompts/problem-math-notation-families.json` 作为数学记法专用 Family catalog。它包含既有四个几何来源 Family 与 `basic_inequality`，不导入 `DEFAULT_FAMILY_REGISTRY`；
- 把 `basic_inequality` 的来源匹配限制为正项、等式/不等式、最大值、最小值、范围和参数目标；Family 只作为抽取上下文，不授予 Runtime 执行能力；
- Prompt 和表达式目录只要求直接数学表达式：`a > 0`、`a+b = 2`、目标表达式 `a*b`、`x+4/(x+1)`（最值由目标类型标记）、`x+y`。不要求 `term1`、`using`、`transformed_target`、`right_angle` 或任何内部 AST；直角仍写 `∠ABC = 90°`；
- 冻结 q01、q03、q07、q08、q12、q17、q20、q25、q30、q31 的单图 image-only fixture、图片 SHA-256/尺寸/来源、数学记法金标和原始题面；q25 的 condition/objective 已按题面顺序合成为一张 `source.png`；
- 使用 `server/shuxueshuo_server/problem_understanding/basic_inequality_smoke.py` 执行批次。每题必须运行两个独立样本；每个样本保存 request、raw response、parsed、normalized/canonical、comparison、call metadata 和 frozen metadata；
- 离线回放使用 `server/tests/solver/test_basic_inequality_math_notation.py`，校验 Schema、Parser/Typecheck、semantic canonicalization、Family、直接表达式禁门和图片 hash；live 门禁位于 `test_basic_inequality_math_notation_live.py`，默认跳过；
- 失败样本只保留诊断，不写入冻结金标。修复 Prompt、表达式目录或诊断协议后重新运行；不以 unmatched 或手工 ProblemIR 绕过门禁。

完成标准：离线 10 题金标全部可回放并通过 `NotationValidator` 和 canonicalization；设置 `RUN_LLM_INTEGRATION=1` 后，以下命令的 20/20 样本通过，并且每个样本可离线回放：

```bash
cd server
RUN_LLM_INTEGRATION=1 uv run pytest -q tests/solver/test_basic_inequality_math_notation_live.py -m live_llm
```

阶段 0 结束时冻结 `server/tests/solver/fixtures/math-notation-v1/basic-inequality/` 下的图片、金标和双样本抽取记录。阶段 1 只消费 q01、q03、q07、q08、q12、q17、q20、q25、q30、q31 的通过候选建立 ProblemIR；剩余 21 题在代表题完整集成测试通过后通过页面验证泛化性，不预建阶段 1 提取 gold 或 ProblemIR。

实现状态（2026-09-23）：新版显式乘号 Prompt 的同一真实批次 20/20 样本通过；完整记录已冻结到 samples/，可验证原图、gold、请求版本及独立调用身份并离线回放。阶段 1 的代表 10 题 ProblemIR 已据此重建并通过 authoring-only Family 匹配，生产求解注册仍关闭。

### 阶段 0.5：定义基本不等式 Family 契约和注册骨架

这一阶段专门定义 Family，不实现具体题目的求解路线。Family 是题型级能力边界，不能由 q01–q31 的题号或某一道题的答案反推。

任务：

- 新增 `basic_inequality` Family 规格，固定 `family_id`、`pattern`、`problem_type`、常见目标类型、来源要求和 `do_not_use_when`；
- 向 LLM 提供一个 `strategy_overview` 和六个规划方法定义：直接应用基本不等式、找对称结构、配齐次式、多次应用基本不等式、换元法、条件消元法；它们只用于生成 plan step 的数学路线，不是 `method_id`、`capability_id` 或代码路由；
- 在后续可执行 Family 规格中声明 8 个 Runtime Method：M01、M07、M08、M09、M11、M12、M13、M14；LLM 参考六种思路，从这些可执行 Method 中选择 plan 的能力；代码依据能力契约验证表达式并关联实现，不按思路名称 dispatch；
- 声明 Family 可引用的 capability pack、Method binding 规则、标准 recipe 和讲解 rule ID；
- 创建 Family 注册骨架，建议实现文件为 `server/shuxueshuo_server/solver/family/basic_inequality.py`；
- 此时只完成规格校验和 registry contract，不把尚未实现的 Method 宣称为可执行能力；
- Family 匹配只使用结构化 `pattern/problem_type`。LLM 提供的 family 标签只能作为候选，不能绕过 `FamilyRegistry` 的唯一匹配和 contract 校验。

LLM 规划输入的唯一总体路线字段是 `strategy_overview`，六个方法定义作为同一参考块提供。不要恢复 `strategy_principles` 数组，也不要把六个规划方法写入 Runtime capability catalog。六种思路可以嵌套、重复或对应多个步骤；LLM 参考它们后，从 Capability Catalog 中选择已有 `capability_id`，用直接数学表达式填写各 Method 契约允许的数学内容。若当前 plan 协议已有 `strategy`、`intent` 或方法说明字段，可以记录所采用的思路，但不能用思路名称替代 `capability_id`、`recipe_hint`，也不允许代码从自然语言推断方法调用。

参考内容见[主设计 §1.1](basic-inequality-method-discussion.md#family-rules)与 [`basic-inequality-strategy.json`](../internal/llm-prompts/basic-inequality-strategy.json)。目前已提供仅在 `basic_inequality` 上下文启用的 planner/repair Prompt 注入入口；Family 尚未注册到生产 Runtime，不代表该题型的 plan 已可执行。题意抽取 Prompt 不接收这些求解参考。

建议的最小匹配声明为：

```python
SolverFamilySpec(
    family_id="basic_inequality",
    match=FamilyMatchRule(
        patterns=("basic-inequality",),
        problem_types=("basic_inequality",),
    ),
    method_ids=(
        "organize_expressions",
        "introduce_semantic_substitution",
        "eliminate_by_constraint",
        "reduce_symmetric_sum_product",
        "apply_two_term_amgm",
        "bound_univariate_quadratic",
        "close_equality_and_restore",
        "solve_univariate_inequality",
    ),
)
```

完成标准：FamilySpec 可以通过 authoring guidance、source requirement、Method allowlist 和唯一匹配校验；但在 capability 尚未实现前，不能进入生产 Runtime 的可执行 registry。

### 阶段 1：为代表 10 题建立可追溯的 ProblemIR，并验证 Family 匹配

任务：

- 唯一集成输入集为 q01、q03、q07、q08、q12、q17、q20、q25、q30、q31，manifest 固定 representative-10、每题两份独立样本及其余 21 题的 deferred 范围；
- 使用包含显式乘号规则的同版 Prompt/schema/catalog。每份通过样本冻结 request、raw response、parsed、normalized、canonical、comparison、call 与 frozen metadata；按字节 hash 校验图片、gold 和样本，保留真实 response ID，同题双样本通过严格语义回放；
- 复用现有 notation 绑定结构转换符号、条件、域、目标和 Scope，不以正则猜变量或关系类型，不因解题路线补写条件、子问或取等信息；
- entity、fact、goal 保留能定位 gold 原字段的 source path、原文、规范表达式和样本引用。表达式定义域要求作为未验证义务，不冒充已知事实；
- 将结构化路由字段固定为 `pattern="basic-inequality"`、`problem_type="basic_inequality"`，由 authoring-only `FamilyRegistry((BASIC_INEQUALITY_FAMILY,))` 验证唯一匹配，并检查符号、等式/约束和支持的目标；
- `basic-inequality-problem-ir/v1` 的 input 继续符合 canonical schema；family_match 和 provenance 为经过验证的投影，不构成执行授权，不修改生产 DEFAULT_FAMILY_REGISTRY；
- 每题保存 problem-ir.json、provenance.json、expected.json、route-metadata.json。允许路线、Method 链、教学步骤数、数学证据、答案和取等分支均为独立测试数据，不进入 Solver 输入；
- 来源不完整、过期、语义比较失败或存在 uncertainty 时拒绝生成 artifact。失败调用保留在独立目录，不覆盖记录或修改 gold 凑齐通过数。

完成标准：20/20 真实样本可离线回放，10/10 ProblemIR 可确定性重建并唯一匹配 Family，所有来源均可追溯；21 题没有被隐式读取或生成。不实现 Runtime Method、通用 Parser 扩展或网页生成。复现命令：在 server 下执行 `uv run python tools/build_basic_inequality_problem_ir.py --check`，测试资产及冻结方式见 `server/tests/solver/fixtures/basic-inequality-problem-ir/v1/README.md`。

### 阶段 2：扩展安全表达式 Parser 和关系 AST

已实现的接口位于 `server/shuxueshuo_server/solver/math_kernel/expression_parser.py`：

- `parse_math_expression(source, symbols)` 解析单值标量，`parse_math_relation(source, symbols)` 解析一个关系；`parse_math_steps(steps, symbols)` 接收 1–12 个 `{"math": ...}` 行；
- `ParsedMath` 同时保存 `source`、`normalized_source`、逐字符 `source_map`、不可变展示树 `tree`、规范树 `ast` 和 `obligations`。节点保存 path、原文 Unicode 字符偏移 `[start,end)` 和 operator_span；`to_sympy(symbols)` 只派生计算形式，不证明任何关系；
- 首轮函数白名单只有一元 `sqrt`，支持 `√(E)`、`√u`、`√2`、整数幂、Unicode 上标、比较符、直接 `/` 分式以及受限 `\frac{E}{E}`、`\sqrt{E}`。无括号根号只覆盖一个数字或标识符；
- 变量乘法使用显式 `*`。`xy` 是完整标识符，不能拆成 `x*y`；允许 `3x`、`2√(x*y)` 等数字系数简写，不接受 `x(y+1)`。关系方向保留，单关系入口不接收关系链；
- `u:=E` / `u≔E` 生成待绑定 Definition；右侧只使用已声明变量，解析不会注册 u，后续行使用 u 仍需调用方符号表已声明。`u=E` 保持普通等式；
- 等式右侧一个 `±` 可生成正、负两个候选分支（如 `x=(s±√d)/2`）；不计算根、不证明可达性，不支持多个 `±`、`∓` 或不等式分支；
- `∵` 行可有最多 8 个顶层逗号分隔的单关系，下一行必须是只有一个关系的 `∴`；只建立相邻步骤关联，不推导事实；
- 除法、负幂、根式产生带节点定位的未验证定义域义务，不写入已知条件。字面量除零、负数实根、未知变量/函数、Python 语法和不支持的 LaTeX 命令直接失败；
- 字符数上限 1024、节点数 256、深度 32、潜在展开规模 128、整数字面量绝对值 10^9、整数指数绝对值 12；语法糖和分支展开同样受限，先校验预算再构造 SymPy；
- 旧 `expression_rewrite.parse_expression/parse_relation` 通过受限兼容入口复用新 Parser，保持返回结构、展示节点 ID 和有理式限制；不会提前开启 M01 的根式、定义、分支或因果标记能力。

完成标准：`a+b≥2√(a*b)`、`3x+4y≥2√(12*x*y)`、`u=x²`、`u:=x²`、`x=±√u`、`T=√(x*y+4/(x*y))` 均能由相应入口解析、类型检查并保留来源定位。解析成功不代表数学关系成立。

验证：新增 `test_expression_parser.py` 检查语法、来源、预算、失败边界及指定 10 题 ProblemIR 与 bound notation AST 的一致性；同时运行现有 M01/事务、阶段 1 和 notation/prompt 回归及 `build_basic_inequality_problem_ir.py --check`。不修改抽取 Parser、冻结样本或 ProblemIR，不建立其余 21 题资产，不运行 live LLM，不变更生产 Family Registry。

### 阶段 3：建立有界、可回放的数学证明内核

独立入口位于 `server/shuxueshuo_server/solver/math_kernel/proof_kernel.py`，有界精确算术位于同目录的 `proof_algebra.py`。本阶段不接入 M01，生产 Family Registry 继续关闭。

- `ProofContext(symbols, premises, limits, scope_id)` 只接收调用方显式提供的已知单关系，记录作用域；内部重新建立实标量，不读取外部 Symbol 的 positive/negative 假设。Definition、∵/∴ 和目标不会自动变成前提；
- `prove_relation(candidate, context)`、`prove_domain(expression, context)` 返回 `ProofResult`，成功为 `proved`；失败为 `not_proved`，诊断区分 `proof_missing`、`proof_limit`、`inconsistent_premises`、`invalid_input` 和 `invalid_proof`；
- 证明包含稳定规则 ID、实际依赖的前提、原文 SHA-256、source path、节点 path/span、规则集版本/hash、作用域上下文 hash 和可确定性序列化的证书。产物携带 sources，内部来源指针可以实际定位；
- 等价证明先检查原始定义域，再使用有理式恒等、有界多项式约减或有界有理系数行消元，保存 `目标差 = Σ 乘子 × 前提差` 的证书。代入是同步 AST 替换，拒绝循环，不调用通用解方程或 Gröbner 搜索；
- 符号规则覆盖严格/非严格关系、正负乘除、方向翻转、整数幂、实数平方以及非零积的因子。给定有理端点区间上的仿射式/二次式使用精确端点与顶点比较；不求解未知可行区间；
- 根式先证明定义域，再使用主值非负、平方还原、有限单调性和非负两侧的平方等价。根式辅助量关联根内非负、主值非负、平方恒等式与原根式节点；不能仅凭平方相等丢弃符号分支；
- 常量使用精确有理数、代数数最小多项式及有理隔离区间证书，不使用浮点容差、采样或 evalf。不能完成隔离或超过预算时明确失败；
- `verify_witnesses(assignments, requirements, context)` 默认验证全部提交分支，逐个报告失败，不静默丢弃。`mode="exists", selected_branch=i` 仅证明指定存在性见证，不表示其余分支成立或已穷尽解集；
- 参数化见证使用 `Witness(assignments, parameter, interval)`。`require_parameterized=True` 要求明确的“目标=参数”关系，并在整个闭区间证明赋值域、原始条件和目标关系；端点或仅增加参数标签不能通过；
- 见证代入在已验证 AST 上同步组合，随后执行内核的节点、次数和系数预算。它可以产生嵌套幂（如 q17 将还原公式代入 x²），不扩大外部 Parser 的语法权限；
- `replay_proof(proof, context)` 逐条检查规则、证书和定义域依赖，不调用证明搜索。结论、来源、前提、系数、作用域、规则版本或依赖关系被篡改时拒绝；检测到矛盾不用于推出任意结论，未检测到矛盾也不表示条件可满足。

默认共享预算：16 个前提、4 个原变量、每个代数证书最多 4 个等式与 4 个根式辅助量；多项式次数 12、项数 128、系数位数 4096、约减/行消元步数 256；证明深度 32、节点 512、规则尝试 512、见证分支 8；常量代数次数上界 16、隔离细化 128 次。递归与分支共用计数，不重置预算。

区间端点统一使用有界的精确有理运算识别，覆盖负数、分数及其算术组合，保留原始 AST、定义域义务和来源。见证子证明构造时计费一次；挂载校验使用跨分支共享的独立校验预算，不重复消耗构造预算。公开证书回放仍对父节点和全部嵌套子证明统一计费。

前提一致性检查同时检查有界代数整理后的常值差式，不能因 `0*x`、`x-x` 等幽灵符号跳过常量矛盾。多项式构造和回放均拒绝非零常量等式除式；一致性检查中的消去不修改原始表达式，也不证明其定义域义务。

有理等式在成为多项式除式之前，先用有界的精确多项式 GCD 约去分子、分母的公因子，不能把 `1/x=2/x` 清分母后的 `-x` 当成可用等式。GCD 的系数 content 与伪余式计算共享约减步数、次数、项数和系数预算；超限明确失败。构造和回放均重新检查约化结果，原始分母非零义务仍须单独证明。

验证入口为 `server/tests/solver/test_math_proof_kernel.py`：包含等价/域/符号/根式、精确常量、证书回放与篡改、预算、q20 主值根式等价、q12 四分支见证和 q17 全区间还原。阶段 1 的 20 份冻结样本和 10 题 ProblemIR 仍通过原离线重建门禁；其余 21 题不新增资产，不运行 live LLM。

完成标准：支持的原语生成可独立回放的证明；无法证明和超限均失败闭合。证明结果仍是独立条件证明，不生成 Canonical Fact，不写 StateVersion，也不构成 Runtime 执行授权。

### 阶段 4A：M11 + M13 跑通 q01 的求解闭环

阶段 4 改为先完成一题的真实求解链。q01 使用阶段 1 的冻结输入：`m>0`、`n>0`、`m+n=2`，求 `m*n` 最大值。期望答案与路线仅保留在测试资产中，不进入 Solver 输入。

已实现的入口：

- `load_frozen_authoring_bundle` 重放两份真实抽取样本、验证 gold/图片/版本/hash，并对比确定性 ProblemIR；随后建立单作用域、单最大值目标的 authoring Runtime 投影。代码机械映射符号、完整原条件和目标，不按题号选路线；
- `BASIC_INEQUALITY_RUNTIME_FAMILY` 仅在显式注入的 `STAGE4A_FAMILY_REGISTRY` 中放行 M11、M13。原 `BASIC_INEQUALITY_FAMILY` 仍是 catalog-only 声明，生产 `DEFAULT_FAMILY_REGISTRY` 不变；
- M11 `apply_two_term_amgm` 接收题面目标及完整原条件、1–12 行完整推导：原条件、`U+V>=2*sqrt(U*V)`、显式代入定和、缩放与目标乘积上界。允许连续 `∴`、`∵`、逗号/分号及关系链；每条关系在原条件和已验证的前序关系下证明，整段共享证明预算，不能把候选前提直接当事实。首轮仍支持两个正项、有理常量定和，最终上界另由原条件独立校验；
- 关系链拆成相邻关系及方向明确的端点关系，逐项验证，保留原文 hash、行号、JSON source path 和原文片段映射。证书按顺序回放，校验来源及前序依赖。旧的单关系 Parser、M01 和成对标记 Parser 协议保持不变；
- M11 在通用证明搜索前检查最终有理常数上界是否符合原定和的 AM-GM 模板。不匹配时返回 `target_bound_mismatch`，提示核对定和代入、除法及平方，不以约减预算耗尽作为这类输入的主要 repair 信号。此检查只诊断 Method 模板适用性，不宣称其他机制无法证明该界；匹配后仍须通过全部证明与定义域验证。同行可用逗号或分号分隔；完整关系之后的 `∵/∴` 也直接作为新子句边界，允许省略分隔符。该兜底不修改原文或来源偏移，不跳过不完整关系，不改变逐项验证和预算限制；
- 模板及上界关联允许加项、乘积因子交换顺序，包括根式内部的乘积；只使用独立的交换律比较键，不改写原 AST、步骤文本、来源或定义域义务，也不交换减法、除法和关系方向。无 function entity 的输入不生成默认二次函数；
- M13 `close_equality_and_restore` 通过 exact CallResult 消费 M11 的 `AmgmBound`，重新验证并回放上界。1–12 行可写取等条件、具体赋值、原条件代回及目标值验算，支持 `x=y=常数`。每个原变量必须有明确取值；同步代入验证所有提交关系、全部原条件、定义域、取等条件及目标值。取等陈述仅在所提交见证下成立，不提升为全局事实。成功才输出 `MaximumExpression`；不搜索解、不宣称见证穷尽；
- 两个输出使用现有 `value_only` 事务写入，记录 canonical Fact、确切 CallResult 依赖与 lineage；不创建虚构 MathObject StateVersion。只有 M13 的 `MaximumExpression` 可关闭目标，M11 上界不能冒充最大值；
- 正式链路为冻结输入 → source-ref FunctionalPlan content/v2 → 严格 binding / compile → transaction → typed goal verification → RuntimeOrchestrator。证明证书保留在审计 trace，公开上界只含数学内容，避免将内部前提 ID 带入 Planner 重试上下文。

离线 authored 计划：`internal/functional-plan-fixtures/basic-inequality-q01.functional-plan.json`。真实 Planner 从外部 strategy reference 获取六种规划思路，能力目录只开放两个已实现 Method；无需题号特判或同题 few-shot。

复跑入口（output 必须是新目录，保留失败记录）：

```bash
cd server
uv run python tools/run_basic_inequality_stage4a.py --mode recorded --output ../internal/review-analysis/basic-inequality-stage4a/recorded-new
RUN_LLM_INTEGRATION=1 uv run python tools/run_basic_inequality_stage4a.py --mode deepseek --output ../internal/review-analysis/basic-inequality-stage4a/live-new
uv run pytest -q tests/solver/test_basic_inequality_runtime.py tests/solver/test_math_proof_kernel.py
RUN_LLM_INTEGRATION=1 uv run pytest -q tests/solver/test_basic_inequality_runtime_live.py -m live_llm
```

验收包含正确答案、完整取等见证、证书回放、错误上界/方向/缺少正性/错误或不完整见证拒绝、原条件不被遗漏、失败事务无答案写入，以及改题号/变量/常数的通用回归。20 份冻结抽取与 10 题 ProblemIR 继续离线重建；其余 21 题不新增资产。

本阶段不迁移 M01，不扩展加权/连续 AM-GM，不生成教学网页。阶段 4B 再从已验证 Runtime artifacts 接入 ExplanationSnapshot → LessonIR → VisualStepIR → HTML；页面不能自行补答案或证明。完整生产注册仍留待能力与 preflight 完成后进行。

### 阶段 4B：q01 学生步骤与声明式视觉闭环（已实现，2026-09-24）

详细契约见[学生步骤、VisualSpec 与前端组件声明式绑定](student-step-visual-binding-design.md)。从 4A 成功执行的公开证据出发，不从手写网页或答案 fixture 构造教学输入。

任务：

- M11 解释代码产生“观察结构”“应用基本不等式”两个单元，M13 产生“验证取等”单元；q01 两个 Runtime Method 对应三个学生步骤，不增加观察 Runtime Method；
- 已接通 `TeachingRuleRegistry` 注册与调度入口；q01 默认无业务规则，原样传递三个 Method 单元。仅测试规则新增概览，校验覆盖与来源；Method 与 rule 的步骤内 `visuals` 共用 VisualSpec 和绑定入口，不引入独立 VisualRequest；
- Lesson LLM 润色并在声明边界内提出合并；代码保持数学内容、来源与必要独立步骤，LLM 后统一校验、处理展示组合、绑定组件，再确定最终步骤及导航；
- 数学对象图形沿用 scene/object identity 与 Frame 继承；自定义教学图持久化为 `diagram_blocks`，默认不继承，可与场景并存。本阶段实现并存和独立边界检查，覆盖与组合留待真实业务规则；
- 实现 q01 的结构对照、推导链、取等验证展示，通过公共编译链生成 HTML；组件不重新求解；
- q07 多次应用识别、总观察合成、覆盖/组合业务规则移至连续 AM-GM 求解能力完成后；M07/08/09 的观察投影随后续 Method 实现补齐。本阶段不实现这些业务规则。

验收：q01 三个步骤及组件绑定正确；所有内容可追溯；LLM 非法合并局部回退；缺组件/角色产生明确 gap；二次函数场景继承回归保持；保存 Snapshot、编排草稿、LessonIR、展示绑定审计、VisualStepIR 和编译 HTML。生产 Family 注册保持关闭，冻结样本与其余 21 题资产范围不变。

构建入口（输出目录必须不存在，失败记录不覆盖）：

```bash
cd server
uv run python tools/run_basic_inequality_stage4b.py --mode deterministic --output ../internal/review-analysis/basic-inequality-stage4b/new-draft
uv run python tools/run_basic_inequality_stage4b.py --mode recorded --content tests/solver/fixtures/lesson_scope_authoring_vnext/basic_inequality_q01/scope-content.json --output ../internal/review-analysis/basic-inequality-stage4b/new-replay
uv run python tools/run_basic_inequality_stage4b.py --mode deepseek --output ../internal/review-analysis/basic-inequality-stage4b/new-live
```

入口固定重放经过验证的 `basic-inequality-q01-stage4b.functional-plan.json`，含定和代入的完整数学链；不读取手写页面或 expected answer。版本清单、调用统计及视觉绑定审计随产物保存。最终两次真实 Lesson LLM 验收记录见 `internal/review-analysis/basic-inequality-stage4b/live-final-01` 与 `live-final-02`；二者均直接接受三步讲解，无修复、无回退。

最终两次调用合计 5,489 tokens，模型调用时间 3.809 秒；含早期验证调用的总账及浏览器记录见该目录的 `acceptance.json`。使用保存的真实响应重放生成最新样式页面 `page-final-01/lesson.html`、`page-final-02/lesson.html`，桌面 1280×960 与窄屏 390×844 检查通过。新增 18 项教学回归、既有 Method/事务/教学/视觉回归及 51 项文本组件测试通过；20/20 冻结样本、10/10 ProblemIR `--check` 通过。离线真实讲解 fixture 位于 `server/tests/solver/fixtures/lesson_scope_authoring_vnext/basic_inequality_q01`，保留响应、调用统计与 hash 来源。

### 后续阶段 4 扩展：M01 迁移与 M11 模板扩展（已实现，2026-09-24）

实现范围：q01、q03、q07、q08 求解闭环；显式 authoring Registry 开放 M01/M11/M13，生产默认 Registry 保持关闭。新题页面与 q07 总观察 rule 的后续实现见本节末尾。

#### M01：等价链与定义域

`parameters.steps[].math` 保留完整表达式，`using` 只能填写已绑定等式的数学原文，不能填写引用 ID 或正性条件。内部使用安全 Parser、ProofContext 和共享证明预算，逐行验证原始 AST 定义域及相邻等价关系，并即时回放证书。正性来自显式绑定条件，不来自 Symbol 附加假设。旧有理式解析接口和展示节点 ID 保持兼容，根式显示普通等式链时不虚构结构分类。

输入和输出保持同一 Expression 对象；一次调用只提交最终新版本，失败回滚。目标来源保留原数学文本，用于检查约分前的定义域。

#### M11：局部双项估计和连续界

首轮有界模板为 `U+V>=2*sqrt(U*V)`；`k*U` 可作为完整参与项。代码枚举最多八个加项中的候选正项对，证明正性、未变部分、正比例外层与根式简化；不唯一时失败，不能由 LLM 的操作名称授权。

- `target` 必填；可选 `expression` 与 `previous_bound` 互斥。
- `expression` 使用目标对象的 SourceRef，事务层固定 M01 已提交的准确版本，并核验 owner、Scope 与生产者。遵循现有具名对象协议，不使用 StepResultRef。
- `previous_bound` 使用上次 M11 的 StepResultRef；同 Scope/Goal，先回放前序证据再传递界。
- 一次调用只引入一个 AM-GM 配对。q07 第一轮得到 `T>=2/b+b`，第二轮得到 `T>=2*sqrt(2)`，累计保留两条取等条件。
- 新输出为 `amgm-bound/v2`，包含方向、当前界、参与项、累计取等条件、前序依赖及 `certificate_bundle`。该 bundle 仅供后端回放，重试 prompt 和教学投影不暴露证书。旧 v1 常数上界仍可由 M13 验证。

证明内核增加局部 AM-GM、等式搬运界和有理恒等下的传递校验。根式辅助方程复用有理等式的 content/gcd 约化，保留全部原始定义域义务；不扩大预算，不搜索一般不等式解。同一次请求内共享纯代数 gcd/content 缓存，避免逐行重复约化消耗预算；缓存不保存证明授权。

#### M13：常数界与有限见证

根据目标仅输出 `maximum: MaximumExpression` 或 `minimum: MinimumExpression`。使用现有可选输出机制，编译时不请求未被消费的条件输出。

单见证继续使用 `steps`；多见证使用与其互斥的 `branches[].steps`，最多八个分支。逐分支验证原条件、域、全部累计取等条件和原目标达到常数界；任一提交分支失败则整体失败，不声明穷尽。含变量的中间界不能关闭最值目标。

多个分支共享构造预算和回放预算。重复出现的同一断言共用证明，并保存每个原始 source document 的覆盖映射；不同断言和错误分支仍逐项检查，不因去重省略。

#### 集成测试与真实门禁

| 题目 | 确定性路线 | 答案 |
|---|---|---|
| q01 | M11 → M13 | 最大值 1 |
| q03 | M01 → M11 → M13 | 最小值 9 |
| q07 | M11 → M11 → M13 | 最小值 2√2 |
| q08 | M01 → M11 → M13 | 最小值 4，验证两个互换见证 |

`server/tools/run_basic_inequality_stage4.py` 支持 recorded/deepseek、四题与双样本；每次输出到新目录，保留失败与修复记录。真实 Planner 不读取答案或既定路线。验收要求四题各两次成功，并保留首轮/修复通过率、耗时、token 和离线重放结果。

测试覆盖 M01 事务与来源、局部估计/交换/正缩放、连续界与证书篡改、错误常数/见证、q01 页面兼容。20 份冻结样本回放及 10 题 ProblemIR `--check` 保持通过，其余 21 题不新增资产。不运行真实 Lesson LLM，不新增页面或组件。

验收记录：

- 离线大组回归 1,666 项通过；最后修复后受影响的证明、M01/M11/M13、q01 教学、编译与 spec 回归 381 项通过。
- 最终真实 Planner：四题各两次，首轮 7/8（87.5%），最多三次尝试内 8/8（100%）；其中一次 q03 经一次修复通过。八次响应均可原样离线重放。
- 最终验收使用 `live-04` 的 q01/q07 和 `live-05-q03`、`live-05-q08`，共 9 次模型调用、105,022 tokens，八次完整求解的耗时之和 249.104 秒（并发运行，此值不是总墙钟时间）。
- 开发调试及失败运行均保留：总计 36 次运行、63 次模型调用、754,538 tokens。没有覆盖失败响应或向 Planner 提供答案/规定 Method 链。
- 完整调用账本、响应 hash、离线回放索引及代码 hash 见 `internal/review-analysis/basic-inequality-stage4/acceptance.json`；回归报告为同目录 `regression.xml`、`final-regression.xml`，最终回放为 `replay-final/`。

可重复入口（使用新的输出目录）：

```bash
cd server
uv run python tools/run_basic_inequality_stage4.py --mode recorded --output ../internal/review-analysis/basic-inequality-stage4/new-offline
RUN_LLM_INTEGRATION=1 uv run python tools/run_basic_inequality_stage4.py --mode deepseek --output ../internal/review-analysis/basic-inequality-stage4/new-live
uv run python tools/run_basic_inequality_stage4.py --case q03 --replay-from ../internal/review-analysis/basic-inequality-stage4/live-05-q03 --output ../internal/review-analysis/basic-inequality-stage4/new-replay
```

#### 网页扩展：q03、q07、q08（2026-09-24）

复用上述冻结输入和确定性求解计划，经过公开教学证据、Method 教学单元、显式 rule、真实 Lesson LLM、来源校验与统一视觉绑定生成网页。未读取手写页面的答案或图形数据。

- q03、q08 为“整理目标式 → 观察结构 → 应用基本不等式 → 验证取等”四步。M01 新增 `expression-rewrite-teaching-evidence/v1` 公开投影，复用原整理组件；M11 下界图使用真实参与项和局部证明，定和条件不再是必填角色；M13 展示全部提交并验证成功的见证。
- q07 为“总观察 → 第一次估计 → 第二次估计 → 验证取等”四步。`amgm_sequence_overview` 仅合并同一 Scope/Goal、同一目标且前序界依赖完整的观察单元，保留两轮应用。总次数来自成功应用链，不由变量个数推测。
- rule 产出的总观察声明 `basic_inequality.amgm_sequence_overview`，通过统一 VisualSpec 注册绑定现有结构观察组件。两次原调用及证据引用随 LessonIR、VisualStepIR 持久化，不伪造新 Runtime capability。
- 下界文案增加方向一致性检查；发现“上界／不超过”等与已验证方向冲突时拒绝并回退。它是有限文案检查，不代表对任意 LLM 新推理做了完整证明。数学图示及结论始终由代码从证据绑定。
- 新增三题页面、来源回放、合并边界和上下界文案回归。保留 q01、二次函数场景与 20 份冻结样本、10 题 ProblemIR 回归。

构建入口：`server/tools/run_basic_inequality_stage4b.py --case q03|q07|q08 --mode deterministic|recorded|deepseek --output <新目录>`。`recorded` 需提供 `--content`，仅回放讲解响应；`deepseek` 只调用 Lesson LLM，求解仍采用离线已验证计划。

网页及调用审计位于 `internal/review-analysis/basic-inequality-stage4-pages/`。q08 首次联网响应存在上下界误述，已保留失败证据；补充检查后独立重跑通过。最终三题均为四步且无需讲解回退。仍不部署网站、不启用生产 Family、不重新抽取或扩充题集。

#### q07 / q08 教学组件重建（2026-09-24）

2026-09-25 路线标签修复：增加代码声明的 `section_label`，从讲解编排路线生成“直接应用基本不等式／多次应用基本不等式”等分组名称，保留数学作用域。q07 的导航补全为“应用基本不等式消元”和“再次应用基本不等式取极值”。重放已有真实响应生成 `q07-route-label-01/lesson.html`、`q01-route-label-01/lesson.html`，均无回退、无新增 LLM 调用。113 项相关回归通过；另有原二次函数人工审定 prompt hash 与当前 prompt 不一致的单项检查未通过，本次未改写该人工基线。桌面、390px 手机导航和底栏均已核对。

2026-09-25 分组优先级补充：有真实小问时仅展示小问；无小问时展示代码声明的解法标签，未声明则为“解题过程”；跨小问公共步骤为“公共推导”。依据来源 Scope 层级与原题标记识别小问，内部求解分支继承所属小问，卡片、导航与移动底栏统一消费页面分组。

取等规划卡片补记：按确认的教学形式恢复“变量数 − 已有取等条件数 = 待补取等关系数”，q07 显示 `2 − 0 = 2`，下接“消元 → 求解”目的卡片。由 rule/公开证据计算，复用 `relationCountHint`，保留实际应用次数与关系数量的分别统计。只在本路线提供对应数量的不同取等关系时展示，重复或恒等关系不计入；此为教学规划，不新增独立性证明或求解授权。

本轮页面：`internal/review-analysis/basic-inequality-stage4-pages/q07-relation-planning-live-01/lesson.html`。真实 Lesson LLM 一次通过、无回退，4388 tokens，调用耗时约 4.02 秒；94 项 Python、58 项前端回归通过，桌面/390px 窄屏卡片无横向溢出，浏览器错误日志为空。

q07 目的导向总览补记：rule 已按每轮成功求界前后的变量集合识别“消元 → 求最值”，声明大卡片显示实际的 `2 → 1 → 定值`、参与项乘积及所得下界，并固定应用步骤标题与导航中的“消元／求最值”。匹配要求准确前序结果引用及同目标连续应用证据，不由变量数推断应用次数。卡片把目的与工具分开声明，后续平方非负等能力可复用展示契约；当前仍只接通 AM-GM 编排。

本轮最终预览：`internal/review-analysis/basic-inequality-stage4-pages/q07-purpose-live-03/lesson.html`。真实 Lesson LLM 无回退；`live-01` 的文案问题与 `live-02` 的 JSON 转义失败记录保留。131 项相关 Python 测试及 58 项前端测试通过，桌面与 390px 窄屏无页面/卡片横向溢出，消元导航正确，浏览器无错误日志。未新增数学 Method、生产注册或题目资产。

M13 的可选 `equality_derivation` 现支持公共推导加分支推导。多分支的 `branches[].when` 与 `branches[].equality_derivation` 必须成对提交；每个局部符号条件仅在自己的分支中可见，见证仍须满足该条件。公共及分支推导共享构造预算，证书逐条回放；每个分支都须推出全部赋值，不宣称穷尽全部解。未提供求解证据时继续使用真实的见证验证表述。

- q07：由两次基本不等式取等条件分别推出 `a=b` 与 `b=√2`，复用多条件取等组件展示联立求解。
- q08：先证明 `a+b=4` 与 `(a-2)²=3`，再展示两个局部符号分支和两组互换取值。分支图仅绑定已验证数学证据。
- AM-GM 参与项和定积公式保留分组，避免将 `(a+b)/2` 的乘积投影为缺少括号的和式；公式幂不再显示多余花括号。

最终页面为 `internal/review-analysis/basic-inequality-stage4-pages/q07-equations-final-01/lesson.html` 与 `q08-equations-final-01/lesson.html`，分别重放 `q07-equations-live-03`、`q08-equations-live-02` 的原始真实讲解响应，无回退。此前失败调用保留。398 项相关 Python 回归（含修正历史 prompt hash 断言后的单项复验）与 62 项前端组件回归通过。两题桌面和 390px 窄屏检查无横向页面溢出；未重新运行 Planner 或题面抽取。

#### q08 通分观察合并（2026-09-24）

已实现 `basic_inequality.fraction_observation`：M01 的“通分显条件并实际代入”与直接消费其结果的 M11 观察材料合并，形成“观察结构 → 应用基本不等式 → 验证取等”三步。匹配依据是实际来源、目标 owner、连续结构 trace 及完整两项定积结构，不按题号或推导行号判断；不满足条件时仍显示四步。q03 的齐次式规则与 q07 连续应用规则保持原行为。

组合 VisualSpec 为 `expression_rewrite.fraction_observation`，复用结构观察组件。通分提示接收参数化分式，图内连接通分、条件代入、整理结果及定积求和。真实 Lesson LLM 首次无回退生成三步，产物位于 `internal/review-analysis/basic-inequality-stage4-pages/q08-fraction-observation-live-01/`。114 项教学/M01 回归与 63 项前端组件回归通过，覆盖换变量、系数、条件常数及拒绝不合法合并的行为。

### 阶段 5：以代表题集成测试驱动 M08、M07、M12、M09、M14（计划，待实施）

不再先孤立完成五个 Method、再等待阶段 6 接 Runtime、阶段 7 做教学。每批先确定代表题和数学能力边界，编写实际使用新 Method 的失败整题测试，再交付该题从已冻结输入到学生网页的完整链路。实现顺序按依赖安排，不按 Method 编号。

#### 实施批次与首选代表题

| 批次 | 核心能力 | 首选代表题 | 主要验收 |
|---|---|---|---|
| 5A | M08 条件消元 | q25 | 条件变形、分母合法性、代入目标、原变量还原与取等 |
| 5B | M07 换元，复用 M08 | q12 | 平方换元、非负域、新变量绑定、正负还原与提交分支验证 |
| 5C | M12 平方非负求界，与 M11 衔接 | q30 | 参数配方、跨 Method 连续求界、累计取等条件同时成立 |
| 5D | M09 和积换元 + M14 一元不等式 | q17 | 判别式、精确区间、原变量全区间还原与可达性 |
| 综合验收 | 已实现能力组合 | q20、q31 | 根式、定义域及多阶段关系的整题闭合与教学 |

这是能力与测试题的拟定配对，不代表已验证了所有路线。各批详细设计先检查确定性数学路线、依赖和缺失原语，再冻结该批输入输出契约。q30 若需要 M11 当前范围外的能力，必须明确列入该批范围、补充 spec 与对应测试；不能为单题静默增加求解兜底。若某批需要尚未实现的依赖，显式调整批次或作为联合交付，不伪造中间产物让整题通过。

M09、M14 分别完成原语与 Runtime 测试，再共同通过 q17 的整题验收；不要求一题只能使用一个新 Method。下一步先细化 **5A：M08 + q25** 的实施计划。

#### 每个 Method 同步交付的接入范围

- 公开 Method spec、Family authoring capability contract、参数编译、输入输出类型、准确状态版本与来源绑定；失败保持原子回滚。
- 新变量只能由成功验证的换元事务注册，明确所属 Scope、定义域和与原变量的关系；候选 Definition 本身不能获得事实权限。
- 换元或消元同时携带目标、条件与还原关系。M13 消费这些证据回到原题，验证原始定义域、全部累计取等条件及目标值；不能只关闭变换后的问题。
- M11/M12 连续界传递所需的共同证据与绑定适配随 5C 完成。界的方向、原目标身份、前序依赖、定义域及取等条件不得丢失，不能把不等式界当成原表达式的等价 StateVersion。
- q17 的范围闭合随 5D 完成：M14 的区间结果与原变量全区间可达性分别验证，仅有必要条件或两个端点见证不算原题范围已求出。
- 公开教学投影、Method 学生单元与 VisualSpec 随 Method 交付；从成功执行证据生成 Snapshot、LessonIR、VisualStepIR 和 HTML。能复用的组件直接复用，必要新角色或组件在本批补齐；缺失必需展示时不能标记网页验收成功。
- rule 仅在该批存在实际编排需要时增加，依据已验证结构与依赖工作。复杂通用编排、其余页面扩展及生产默认注册留到后续阶段。

#### 测试驱动流程与完成门禁

1. **先写失败整题测试。** 使用现有冻结 ProblemIR 编写明确调用待实现 Method 的确定性 FunctionalPlan；期望答案只在测试断言中。检查实际 Method 执行记录、输入绑定、输出被后续步骤消费，而非只检查计划里出现了 capability 名称。
2. **完成原题闭合。** 真实编译器、Runtime、M13/范围闭合均通过；逐条证书可离线回放。覆盖来源、状态身份、作用域和失败回滚，不能 mock 掉缺失的数学验证或后续消费。
3. **补泛化与拒绝案例。** 至少一个变更变量、合法系数或表达式顺序的成功案例；按该 Method 的主要风险覆盖漏定义域、错误还原、丢分支、跨作用域、错误方向或证书篡改。所有失败须有明确诊断。
4. **真实 Planner 验收。** 每批代表题独立运行两次，每次最多三次尝试；只提供题意、可用能力及正常 Family 思路，不提供答案、指定 Method 链或测试路线。逐次保存首轮通过、修复通过、实际 Method 覆盖及失败记录。
5. **教学与网页验收。** 从上述成功执行证据生成确定性教学草稿和可回放页面；至少一次真实 Lesson LLM 无回退地通过该代表题的教学验收。浏览器检查数学正文、公式、步骤/小问导航，以及新组件的桌面和窄屏布局。展示不能补造求解缺失的事实。
6. **既有回归。** q01/q03/q07/q08、受影响的数学内核与事务、二次函数/几何教学契约及展示继续通过；20/20 冻结样本回放和 10/10 ProblemIR 构建 `--check` 继续通过。

整题成功与 Method 覆盖分开统计。真实 Planner 若走其他合法路线，记录为“整题成功、待验收 Method 未覆盖”，不能作为该 Method 的真实调用验收证据；也不能因此判其数学答案错误。未覆盖时分析 spec、题目配对和支持范围，明确记录缺口，不通过隐藏能力、泄露预定路线或丢弃运行记录制造覆盖。

真实验收至少包含代表题两次独立运行成功，以及本批每个新 Method 至少一次被真实 Planner 成功调用并参与原题闭合；二者缺一不可。5D 须分别记录 M09 与 M14 的覆盖。若两次均走其他路线，当前批次的 Method 真实覆盖仍未完成，后续补验使用新目录并保留此前统计。

每批保留新输出目录：输入来源、确定性计划、实际执行及证明、Planner 请求/响应/诊断/修复、离线回放、教学草稿与编排、Lesson LLM 请求/响应/回退、最终教学与视觉 IR、绑定审计及 HTML。耗时与 token 按实际调用记录汇总，区分并行墙钟时间与调用耗时之和。Method 未通过整题与教学门禁时只能标记部分完成。

本阶段复用冻结资产，不重新进行真实题意抽取，不新增其余 21 题的阶段 1 资产；仍使用显式 authoring Registry，不启用生产默认 Family，不部署网站。

以下是各 Method 的数学边界摘要；具体参数协议、可证明子集和预算在对应批次详细计划中确定。

#### M07 换元

支持直接表达式：

```text
u:=x²
u≥0
x=±√u
```

代码验证目标、条件、定义域和还原分支的一致性；更强的 `u>0` 或 `u≤1` 必须有原条件依据。非一一映射不能擅自丢弃分支；有限见证验证与分支穷尽性必须区分，不把提交的正负分支直接声明为所有解。

#### M08 条件消元

支持直接表达式：

```text
y=(1+1/x−x)/2
T=(3x+1/x+1)/2
```

代码验证这是已绑定条件的合法变形，记录除法非零、剩余范围和原变量还原，不把模型给出的解式直接当成事实。

#### M09 和积换元

支持直接表达式：

```text
s:=x+y
p:=x*y
Δ:=s²−4p
x=(s+√Δ)/2
y=(s−√Δ)/2
```

代码验证对称表达式转换、判别式、正根条件和完整还原。

#### M12 二次式求界

代码验证：

```text
25*c²−10*a*c+2*a²+4/a²=(a−5*c)²+a²+4/a²
(a−5*c)²+a²+4/a²≥a²+4/a²
```

参数取等是否能与原条件同时成立交由 M13 闭合。输出须能与 M11 的前后界衔接；平方非负关系、其取等条件及原始定义域均进入可回放证据。

#### M14 一元不等式

LLM 只提交已验证的一元不等式和作用域，例如：

```text
(4−s²)/3≥0
s∈R
```

代码计算精确区间、开闭端点、单点、空集或全域。LLM 不能填写根、符号表或最终区间作为事实。计算出换元量的必要区间，不等于原题全区间可达；q17 的参数化还原必须另外覆盖整个候选区间。

### 阶段 6：统一证据契约与生产 Family 注册

进入本阶段前，阶段 5 所需的 Method 编译、binding、M13 还原、范围闭合和教学接入须已随各批完成。本阶段负责跨能力契约收敛与生产准入，不再作为代表题能否运行的前置等待阶段。

任务：

- 完成 `basic_inequality.py` 的 Family 实际注册，并将其加入 `DEFAULT_FAMILY_REGISTRY`；
- 将已实现的 8 个 Method capability contract、binding rule 和 recipe 通过 capability pack 展开到该 Family；
- 在 Runtime preflight 中检查 Family 已注册、Method 属于 Family allowlist、输入 Scope 和 Goal contract 完整；
- 收敛阶段 5 已接通的 M11/M12/M14 结果与 Canonical Fact 适配，检验跨 Method 消费与旧产物兼容；
- 保存原始表达式、规范 AST、premises、proof、equality conditions 和 source path；
- 在 StateVersion 中区分等价更新和不等式下界，不把下界覆盖为原目标；
- 统一阶段 4/5 已支持的 M13 有限见证、联立推导、换元/消元还原和范围闭合契约；新增范围另列集成测试，不回退既有能力；
- 回归正负分支、参数分支、原始定义域、全部取等关系及全区间可达性，保持验证见证与证明穷尽的区别；
- 将 rule hash、semantic hash、provenance 写入 binding artifact；
- Runtime 只消费 Canonical Fact，不要求 LLM 暴露内部 AST。

完成标准：阶段 5 各 Method 的实际调用、代表题闭合与教学门禁通过后，`basic_inequality` 才进入生产 `DEFAULT_FAMILY_REGISTRY` 并唯一匹配；8 个 Method 的已声明支持范围通过 capability contract、binding、Canonical Fact 和 Runtime preflight。既有 10 题代表集的多阶段关系可以提交、回滚和重放。q18、q21 等其余题目留在后续页面泛化验证，不为生产注册额外建立阶段 1 资产。

### 阶段 7：扩展讲解编排与网页覆盖

进入本阶段前，阶段 5 每个 Method 须已交付最小教学投影、VisualSpec 与代表题网页。本阶段扩展多种 Method 组合的教学规则、复用组件和其余路线覆盖，不延后 Method 的基础讲解验收。

任务：

- Method trace 产生表达式、局部节点、前提和教学片段；
- Family rule 按已验证结构组织学生步骤，不按题号或字符串相邻关系猜测；
- 沿用阶段 4B 的学生步骤与展示声明契约，扩展到后续 Method 和完整路线；代码保持数学内容、来源与必要边界，Lesson LLM 可润色并提出合法合并；
- Method 和 rule 声明 VisualSpec，LLM 后由统一层完成展示组合与组件绑定；组件消费公开的已验证教学数据，页面不重新解析或求解数学；
- 每个页面保存 ExplanationSnapshot、LessonIR、VisualStepIR、HTML 和审计 artifact；
- 页面公式保留直接数学表达式，不回写成 `angle(...)`、`amgm_bound(...)` 等内部表示。

完成标准：每道题都能从成功 Runtime artifact 生成可复现网页；失败时页面生成不会伪造成功结论。

### 阶段 8：31 题迁移、回归和切换

执行顺序：

1. 复用阶段 1 已完成的代表性抽取结果，先离线回放 20 份冻结样本；确需修改抽取协议时另立迁移验收，不隐式重跑真实抽取；
2. 检查冻结响应和规范表达式的来源完整性；
3. 对已有 10 题 ProblemIR 执行构建 `--check`，复用阶段 4/5 的计划与执行回放，补齐剩余覆盖；
4. 用代表题的确定性候选跑完整求解链；
5. 生成代表题的 ExplanationSnapshot、LessonIR、VisualStepIR 和网页；
6. 对 10 道代表性题执行完整求解与网页集成测试并通过门禁；
7. 对其余 21 题直接使用已有 lesson spec / 页面题面，经输入适配、同一 Family/Method 求解链及教学 IR 进入页面泛化测试，不要求先建立独立提取 gold 或阶段 1 ProblemIR fixture；
8. 比较 semantic hash、provenance、页面公式和答案；
9. 只有所有门禁通过后，才切换新的表达式优先协议。

## 5. 错误分类和 repair

错误必须区分：

| 类别 | 示例 | repair 行为 |
|---|---|---|
| 抽取错误 | 题面条件或目标表达式缺失 | 修复题意抽取，不修改 Method 事实 |
| 表达式解析错误 | 未知变量、语法、函数或关系方向 | 要求重写直接数学表达式 |
| 归一化错误 | 找不到唯一局部正项或模板 | 提供步骤号、前后表达式和期望关系，要求补充/重写完整数学表达式 |
| 前提推断错误 | 找不到唯一使用的条件或证明路径 | 列出可见条件和缺失关系，要求补充由已有条件推出的数学步骤 |
| 证明缺失 | 无法证明正性、非零或根式定义域 | 要求补充题面已有数学前提或中间推导，不允许猜测 |
| binding 错误 | SourceRef 不可见、类型不符、作用域错误 | 只修复绑定，不扩大权限 |
| Method 验证失败 | 等价、方向、取等或还原不成立 | 指出表达式行和失败证据 |
| closure 失败 | 取等条件不能同时满足或不可达 | 保留中间事实，要求重新选择合法路线 |
| 页面组装失败 | LessonIR、VisualStepIR 或 HTML 非法 | 不回退为未经验证的文字结论 |

repair prompt 只能使用直接数学表达式示例，例如：

```text
第 2 行无法从当前条件证明分母 x+1 非零。请补充由已有条件推出的数学步骤，或重新输出完整不等式关系，例如：
3x+4y+1≥2√(12*x*y)+1。
不要填写 using、transformed_target、term1、term2、operation 或内部 Fact 名称。
```

## 6. 测试计划

### 6.1 DeepSeek 题意提取集成测试

提取集成测试先于 ProblemIR fixture 和 Method 集成测试。代表性样例应覆盖：

- 直接定和/定积的二元题；
- 需要整理后才能应用基本不等式的分式题；
- 多次应用基本不等式的题；
- 换元、消元和和积换元题；
- 范围题、根式题、指数题和带参数题；
- 多子问、复杂条件和容易混淆的变量域。

每个 DeepSeek 集成样例检查：

- 题面目标是否抽取为直接数学表达式；
- 所有条件、正性、非零和变量域是否保留；
- 子问边界和问题类型是否正确；
- 是否把题意改写成内部 AST 或猜测答案；
- 失败时是否返回结构化抽取诊断并触发受限 retry；
- 冻结响应是否包含原始模型输出、规范表达式、source path 和版本信息。

提取测试通过后，才允许将该题写入 ProblemIR。抽取测试失败的题目不得用手工 ProblemIR 绕过提取门禁。

### 6.2 Parser 与证明内核

- 直接数学表达式和 ASCII 兼容表达式的双向解析；
- `√`、整数幂、分式、比较符和等式方向；
- source span、展示树和规范 AST 保留；
- 正性、非零、根式定义域、等式代入和 proof tree；
- 无法证明时 fail closed；
- 未知变量、未知函数、超大表达式和矛盾条件诊断。

### 6.3 八个 Method

每个 Method 的基础测试至少有：

- 一个直接数学表达式成功样例；
- 一个等价但不同书写顺序的成功样例；
- 一个内部 AST/Fact 字段泄露的拒绝样例；
- 一个定义域或正性缺失的失败样例；
- 一个 source expression、proof 和 provenance 完整性断言。

这些基础测试不替代阶段 5 的整题门禁。新增 Method 必须有实际执行并消费其输出的确定性整题计划、真实 Planner 覆盖，以及基于成功执行的教学与页面验收。录制计划用于测试指定路线；真实 Planner 请求中不得注入该计划或期望答案。

M11 额外覆盖：

- `a+b≥2√(a*b)`；
- `3x+4y≥2√(12*x*y)`；
- 带未变化上下文项；
- 两个可能匹配项导致歧义；
- 不满足正性的项；
- 多次 M11 的中间下界绑定。

### 6.4 代表性求解与网页集成测试

第一版代表性求解与网页集成测试为：

```text
q01, q03, q07, q08, q12,
q17, q20, q25, q30, q31
```

它们分别覆盖直接应用、整理、连续应用、平方换元、和积换元、范围、根式、倒数定义域、参数配方、复杂多阶段路线和完整网页组装。

每个求解与网页集成样例检查：

- 冻结题意表达式及 ProblemIR 的来源完整性；
- Method 编译、实际输入与成功执行记录；新 Method 的输出确实被后续步骤消费，不能只断言最终答案或 capability 名称出现；
- Canonical Fact、StateVersion 和 provenance；
- 证明证书离线回放、原题定义域、换元/消元还原与取等闭合；范围题包含整个候选区间的可达性；
- ExplanationSnapshot、LessonIR、VisualStepIR；
- 最终 HTML 公式和步骤顺序；
- 取等解、范围或答案；
- 失败分类和 retry 证据。

真实调用单独记录整题首轮通过率、修复后通过率和 Method 实际覆盖，避免合法替代路线掩盖待验收能力缺口。Lesson LLM 的接受、修复和回退独立统计；不能用确定性回退冒充真实讲解验收成功。各阶段均保存失败记录，不以更换输出目录删除历史分母。

其余 q02、q04–q06、q09–q11、q13–q16、q18–q19、q21–q24、q26–q29 在代表集完整集成测试通过后直接做页面泛化验证，不预建独立提取 gold、答案或阶段 1 ProblemIR fixture。页面必须消费原题条件和目标、经过同一已注册数学能力边界；不按题号新增求解分支，未实现能力须明确报告，失败时不生成伪造答案或教学步骤。

## 7. 验收门禁

切换前必须同时满足：

- 8 个 Method 的 LLM-facing Prompt 都只使用直接数学表达式；
- Parser、证明内核和 Method 不把未验证候选当作事实；
- M11 能在代表性样例中从完整不等式恢复局部两个正项；
- 代表性 DeepSeek 题意提取集成测试全部通过，并冻结抽取产物；
- 代表 10 题的 ProblemIR 全部可追溯到同版基线下的 20 份通过抽取产物；
- q01–q31 全部成功生成可审计网页，或有明确结构化失败且不伪造结果；
- 10 道代表性求解与网页集成测试全部通过；
- 其余 21 题通过页面输入适配、同一求解链及页面泛化回归，不以阶段 1 预建 fixture 作为前置条件；
- 历史 `angle(...)` 等内部兼容输入仍可被代码读取，但新 Prompt 和 repair 不再生成；
- semantic hash、ruleset hash、provenance、source expression 和错误分类全量稳定；
- 页面公式全部来自 verified trace，不能出现内部 AST 记法；
- 全量非集成 Solver 测试、Method 测试、页面生成测试通过。

## 8. 暂不支持的范围

首轮不追求任意不等式自动求解，也不支持：

- 任意高阶 AM-GM 自动搜索；
- 无界符号推理和任意单调函数推理；
- 通过数值抽样替代符号证明；
- 让 LLM 直接填写根、区间、Fact ID 或内部 AST；
- 为单道题新增专用 Method 或题号分支。

扩展能力必须先进入表达式模板注册、证明规则和可复现 fixture，再进入新的 Method 或 Macro。


2026-09-24 页面修复补记：M01 已验证的配齐次变形可生成次数观察和专门整理图；跨 Method 观察合并检查实际状态来源并保留覆盖。M11 下界与 q01 上界统一使用完整基本不等式映射组件，不再因方向切换到简化图。q03、q07、q08 新预览见 `internal/review-analysis/basic-inequality-stage4-pages/visual-fix-acceptance.json`。本次不改变数学求解参数、证明规则或生产注册范围。


### 教学上下文与开发门禁调整（2026-09-25）

共享教学 prompt 与示例提取为 `server/shuxueshuo_server/solver/explanation/prompts/` 下的版本化模板。基本不等式 Family 声明可选教学模板与原策略目录引用，向教学 LLM 提供六类思路及编排完成后的本题实际路线；未接入的 Family 保持共享协议。路线引用当前 Scope/Goal 的局部材料，不能提供额外数学执行授权。

模板已迁移为 Jinja2：`system-v1.jinja`、`user-v1.jinja` 管理完整请求，使用 include、条件和循环组合共享协议、Family 指引及材料边界。Python 只准备与校验数据并调用渲染，不再拼接段落文案；缺失变量严格报错，结构化数据统一 JSON 序列化。审计记录实际加载的模板与策略资源，模板作为包数据发布。q01、q03、q07、q08 和二次函数五个代表请求与迁移前逐字一致，相关回归 218 项通过；本次模板迁移没有重新调用真实 LLM。

修正公开执行投影中把最小值目标写为最大值、把 AM-GM 下界统一写为上界的问题，目标类型与方向来自已验证产物。共享输出协议明确五个可写字段和 LaTeX 的 JSON 转义示例。

B2/B3/B4 不再要求当前 prompt 文案与历史审核 hash 相等，继续检查数学材料、Schema、独立边界、录制响应兼容性和当前请求审计一致性。历史审核记录未改写；显式精确请求 pin 保留。C0 四份机器清单重新生成，29 项公开能力覆盖完整，本次仅全局 Registry 指纹改变；公开契约与覆盖数据保持一致。不再排除历史 prompt 测试，而是分别检验历史记录完整性和当前行为契约。

四题真实教学验收资产位于 `internal/review-analysis/lesson-template-context-20260925/`。每次生成使用新目录，保留原始响应、校验与回退、模板审计、耗时和 token；不重新调用真实 Planner 或抽取，不修改冻结样本和 ProblemIR。

验收完成：最终 `q01/q03/q07/q08-live-03` 均一次通过，无修复或回退，分别生成 3/4/4/3 步。首轮 q07 的 JSON 失败及第二轮文案检查记录保留；最终四次调用合计 22,775 token，全部十二次调用合计 67,230 token。B2/B3/B4、C0、Family/Runtime、教学/展示相关回归通过，冻结回放 20/20、ProblemIR `--check` 10/10。逐次耗时、差异和预览链接见 [验收记录](../internal/review-analysis/lesson-template-context-20260925/acceptance.md)。本次浏览器核对正文、公式与导航，未重新扩大窄屏布局验收范围。
