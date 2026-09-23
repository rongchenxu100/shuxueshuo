# 基本不等式表达式优先 Method 实施计划

> 状态：计划稿，待按阶段实施。更新：2026-09-20。
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

## 2. 当前基线与差距

当前已有：

- `organize_expressions` 的有界表达式解析、等价链验证、条件绑定和教学 trace；
- q08 整理前缀的事务、ExplanationSnapshot 和页面实验；
- FunctionalPlan 的参数绑定、状态版本、provenance 和 retry 基础设施；
- 31 题的 Method 路线设计和页面步骤布局设计。

当前差距：

- 阶段 2 Parser 已提供根式、单关系、定义、分支及带 source span 的 AST；新语法尚未接入 Runtime 证明，旧 M01 保持有理式限制；
- 设计文档已经确定唯一的 `basic_inequality` Family，但代码注册表尚未注册该 Family；
- 还没有统一的正性、分母符号、根式定义域和不等式方向证明器；
- M11、M13 已具备阶段 4A 的二元正项定和求积与单组取等见证验证能力，仅供显式 authoring Runtime 使用；M07、M08、M09、M12、M14 及更广的求界/还原能力仍待实现；
- M11 尚不能从完整不等式的左右表达式差异中恢复两个正项；
- 31 题尚未全部经过求解到 HTML 的确定性页面生成门禁；
- 代表性集成测试尚未冻结执行 artifact 和页面断言。

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

### 后续阶段 4 扩展：M01 迁移与 M11 模板扩展

#### M01

- 接入阶段 3 的 ProofContext、定义域证明与证书回放，在保留现有有理式行为的基础上迁移验证逻辑；
- 扩展现有等价链以支持根式、有限指数和带定义域前提的整理；
- 保持 `organize_expressions` 只验证候选路线，不负责寻找路线；
- 继续使用完整数学式链，不能增加 `operation` 字段作为 LLM 必填项；
- 输出每步关系、局部节点、条件卡、定义域 proof 和结构分类。

#### M11

M11 首轮只实现有界模板注册表：

```text
U+V≥2√(U*V),       U>0,V>0
k*U+V≥2√(k*U*V),     k>0,U>0,V>0
```

验证算法：

1. 解析完整前后式；
2. 对加法节点做保守展平；
3. 根据公共子树和局部差异找出未改变部分；
4. 恢复候选局部关系 `U+V` 与 `2√(U*V)`；
5. 用证明内核证明 `U>0`、`V>0` 和根式定义域；
6. 将候选局部关系与注册模板做交换律、结合律和正系数规范化匹配；
7. 验证不等式方向、目标对应和取等条件；
8. 生成 `amgm_bound`、proof、source path 和教学片段。

如果存在多个同样合理的局部匹配，返回 `inequality_ambiguous`。如果没有匹配，返回 `inequality_template_unmatched`。repair 只要求模型重写完整数学关系，不要求模型填写内部项身份。

完成标准：代表题 q01、q03、q07、q08 覆盖一次应用、加权项、连续应用、整理后应用和定积对应；q28 保留为后续页面泛化验证，不增加冻结抽取或阶段 1 fixture。

### 阶段 5：实现 M07、M08、M09、M12、M14

#### M07 换元

支持直接表达式：

```text
u=x²
0<u≤1
x=±√u
```

代码验证目标、条件、定义域和还原分支的一致性；非一一映射必须保留所有合法分支。

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
s=x+y
p=x*y
Δ=s²−4p
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

参数取等是否能与原条件同时成立交由 M13 闭合。

#### M14 一元不等式

LLM 只提交已验证的一元不等式和作用域，例如：

```text
(4−s²)/3≥0
s∈R
```

代码计算精确区间、开闭端点、单点、空集或全域。LLM 不能填写根、符号表或最终区间作为事实。

### 阶段 6：扩展 M13、Canonical Fact、Family Runtime 注册和 binding

任务：

- 完成 `basic_inequality.py` 的 Family 实际注册，并将其加入 `DEFAULT_FAMILY_REGISTRY`；
- 将已实现的 8 个 Method capability contract、binding rule 和 recipe 通过 capability pack 展开到该 Family；
- 在 Runtime preflight 中检查 Family 已注册、Method 属于 Family allowlist、输入 Scope 和 Goal contract 完整；
- 将 M11/M12/M14 的结果统一绑定为可消费的 Canonical Fact；
- 保存原始表达式、规范 AST、premises、proof、equality conditions 和 source path；
- 在 StateVersion 中区分等价更新和不等式下界，不把下界覆盖为原目标；
- 在阶段 4A 单组有限见证验证的基础上，扩展 M13，联立所有取等关系、原始定义域、换元/消元还原和题目条件；
- 保留正负分支、参数分支和范围题全区间可达性；
- 将 rule hash、semantic hash、provenance 写入 binding artifact；
- Runtime 只消费 Canonical Fact，不要求 LLM 暴露内部 AST。

完成标准：`basic_inequality` 能通过生产 `DEFAULT_FAMILY_REGISTRY` 唯一匹配；8 个 Method 的已实现子集能够通过 capability contract、binding、Canonical Fact 和 Runtime preflight；q12、q17、q18、q21、q25、q30、q31 的多阶段关系可以提交、回滚和重放。

### 阶段 7：讲解规则、LessonIR 和网页生成

任务：

- Method trace 产生表达式、局部节点、前提和教学片段；
- Family rule 按已验证结构组织学生步骤，不按题号或字符串相邻关系猜测；
- 固定数学步骤由代码锁定，Lesson LLM 只能编排开放文案；
- 视觉组件直接消费 verified trace，页面不重新解析或求解数学；
- 每个页面保存 ExplanationSnapshot、LessonIR、VisualStepIR、HTML 和审计 artifact；
- 页面公式保留直接数学表达式，不回写成 `angle(...)`、`amgm_bound(...)` 等内部表示。

完成标准：每道题都能从成功 Runtime artifact 生成可复现网页；失败时页面生成不会伪造成功结论。

### 阶段 8：31 题迁移、回归和切换

执行顺序：

1. 先运行代表性 DeepSeek 题意提取集成测试；
2. 冻结通过测试的抽取响应和规范表达式；
3. 根据冻结抽取结果建立代表 10 题的 ProblemIR、离线表达式 fixture 和预期 Canonical Fact；
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

每个 Method 至少有：

- 一个直接数学表达式成功样例；
- 一个等价但不同书写顺序的成功样例；
- 一个内部 AST/Fact 字段泄露的拒绝样例；
- 一个定义域或正性缺失的失败样例；
- 一个 source expression、proof 和 provenance 完整性断言。

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

- 题意表达式抽取；
- Method 编译和实际输入；
- Canonical Fact、StateVersion 和 provenance；
- ExplanationSnapshot、LessonIR、VisualStepIR；
- 最终 HTML 公式和步骤顺序；
- 取等解、范围或答案；
- 失败分类和 retry 证据。

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
