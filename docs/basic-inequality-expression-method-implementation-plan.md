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

1. **数学表达式优先。** LLM 输出 `a+b≥2√(ab)`、`u:=x²`、`x=±√u` 和完整等价式链；逻辑关系首轮只使用数学符号 `∵`、`∴`，不输出自然语言、内部 AST、Fact ID、`term1`、`term2` 或操作标签。
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

- Parser 还不能完整处理 `√`、一般函数、直接不等式关系和带 source span 的关系 AST；
- 设计文档已经确定唯一的 `basic_inequality` Family，但代码注册表尚未注册该 Family；
- 还没有统一的正性、分母符号、根式定义域和不等式方向证明器；
- M07、M08、M09、M11、M12、M13、M14 仍主要停留在设计协议，尚未形成完整 runtime 能力；
- M11 尚不能从完整不等式的左右表达式差异中恢复两个正项；
- 31 题尚未全部经过求解到 HTML 的确定性页面生成门禁；
- 代表性集成测试尚未冻结执行 artifact 和页面断言。

## 3. 目标协议

### 3.1 最小公共表达式协议

公开调用保留现有 `step_id`、`capability_id` 和 `args` 外壳。所有表达式型 Method 的 LLM-facing 候选只使用 `math` 或 `steps[].math`；M01 等多步 Method 使用 `steps[]`。题设条件、变量域、前提选择、目标角色和已验证中间事实由编译器从当前 Scope 绑定或从表达式链推导，不要求 LLM 填写语义角色字段。

例如，M11 可以只提交：

```json
{
  "math": "a+b+1≥2√(ab)+1"
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
    {"math": "∵ 5x²y²+y⁴=1"},
    {"math": "∴ 5uv+v²=1"},
    {"math": "∵ a>0，b>0"},
    {"math": "∴ a+b+1≥2√(ab)+1"}
  ]
}
```

换元不使用“设”字段；`u:=x²`、`u≔x²`表示定义，首选 `:=`。`=`保留为普通等式，`≡`表示恒等关系，不作为首轮换元定义符号。

Parser 只识别 `∵`、`∴`、`:=`、`≔` 和数学关系本身，生成内部的 premise/conclusion/definition 标记；这些标记不由 LLM 填写。`∵` 行只允许顶层逗号分隔的并列前提，逗号表示前提合取；`∴` 行只允许一个结论关系。前提行和结论行按相邻顺序配对，必要时由代码记录明确的步骤范围。若缺少 `∵` 或 `∴`，可以按单纯数学表达式处理；若符号前后的关系无法验证，返回步骤级诊断。首轮不引入“因为、所以、由、得、利用、应用基本不等式”等自然语言关键词。

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
    "math": "a+b+1≥2√(ab)+1"
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
      {"math": "5uv+v²=1"},
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

M13 可以在公开能力层保持为 Family closure/Macro；如果内部保留 kernel，也不能要求 LLM 了解其内部 wiring。M11 的前提和结论默认分两行，只有当全部前提都能从 Scope 唯一证明时，才允许用单行 `math` 简写。

## 4. 分阶段实施

### 阶段 0：冻结提取契约和代表性 DeepSeek 集成测试

任务：

- 只验证 `problem-math-notation/v1` 的“图片 → 数学记法候选”链路，不调用 Method、ProblemIR、Runtime binding 或网页生成；
- 使用 `server/shuxueshuo_server/problem_understanding/notation_family_catalog.py` 和 `internal/llm-prompts/problem-math-notation-families.json` 作为数学记法专用 Family catalog。它包含既有四个几何来源 Family 与 `basic_inequality`，不导入 `DEFAULT_FAMILY_REGISTRY`；
- 把 `basic_inequality` 的来源匹配限制为正项、等式/不等式、最大值、最小值、范围和参数目标；Family 只作为抽取上下文，不授予 Runtime 执行能力；
- Prompt 和表达式目录只要求直接数学表达式：`a > 0`、`a+b = 2`、`max(ab)`、`min(x+4/(x+1))`、`x+y`。不要求 `term1`、`using`、`transformed_target`、`right_angle` 或任何内部 AST；直角仍写 `∠ABC = 90°`；
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

### 阶段 2：扩展表达式 Parser 和关系 AST

任务：

- 在现有安全 Parser 上增加 `√`、根式、有限函数、Unicode 比较符和直接分式的前端归一化；
- 支持 `=`、`≥`、`≤`、`>`、`<` 的单关系解析，并保留关系方向；
- 保留原始字符串、source span、节点 path、展示树和规范 AST；
- 建立受限函数白名单，首轮至少支持 `sqrt`、必要的幂和目标表达式函数；
- 继续拒绝 Python 语法、未知函数、未声明变量、无界展开和任意代码执行；
- 为同一表达式提供展示形式和计算形式，展示形式不被 SymPy 全局化简覆盖。

完成标准：`a+b≥2√(ab)`、`3x+4y≥2√(12xy)`、`u=x²`、`x=±√u`、`T=√(xy+4/(xy))` 可以解析、类型检查并保留来源定位。

### 阶段 3：建立数学证明内核

先实现可复用的证明原语：

- 等式等价和带等式前提的代入；
- 非零、正、非负、负的符号证明；
- 分母非零和分母正负；
- 根式存在、主值非负和有限单调对应；
- 乘法、除法、偶次幂和平方的符号传播；
- 取等条件的合取、分支和可达性检查；
- 精确有理数和代数数比较。

证明内核不做无界自动求解。每个证明结果保存 premises、规则 ID、输入节点和 proof tree；不能证明时返回明确的 `proof_missing`，不能返回“可能成立”。

### 阶段 4：扩展 M01 并实现 M11

#### M01

- 扩展现有等价链以支持根式、有限指数和带定义域前提的整理；
- 保持 `organize_expressions` 只验证候选路线，不负责寻找路线；
- 继续使用完整数学式链，不能增加 `operation` 字段作为 LLM 必填项；
- 输出每步关系、局部节点、条件卡、定义域 proof 和结构分类。

#### M11

M11 首轮只实现有界模板注册表：

```text
U+V≥2√(UV),       U>0,V>0
kU+V≥2√(kUV),     k>0,U>0,V>0
```

验证算法：

1. 解析完整前后式；
2. 对加法节点做保守展平；
3. 根据公共子树和局部差异找出未改变部分；
4. 恢复候选局部关系 `U+V` 与 `2√(UV)`；
5. 用证明内核证明 `U>0`、`V>0` 和根式定义域；
6. 将候选局部关系与注册模板做交换律、结合律和正系数规范化匹配；
7. 验证不等式方向、目标对应和取等条件；
8. 生成 `amgm_bound`、proof、source path 和教学片段。

如果存在多个同样合理的局部匹配，返回 `inequality_ambiguous`。如果没有匹配，返回 `inequality_template_unmatched`。repair 只要求模型重写完整数学关系，不要求模型填写内部项身份。

完成标准：q01、q03、q07、q08、q28 至少能够覆盖一次应用、加权项、连续应用、整理后应用和定积对应。

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
p=xy
Δ=s²−4p
x=(s+√Δ)/2
y=(s−√Δ)/2
```

代码验证对称表达式转换、判别式、正根条件和完整还原。

#### M12 二次式求界

代码验证：

```text
25c²−10ac+2a²+4/a²=(a−5c)²+a²+4/a²
(a−5c)²+a²+4/a²≥a²+4/a²
```

参数取等是否能与原条件同时成立交由 M13 闭合。

#### M14 一元不等式

LLM 只提交已验证的一元不等式和作用域，例如：

```text
(4−s²)/3≥0
s∈R
```

代码计算精确区间、开闭端点、单点、空集或全域。LLM 不能填写根、符号表或最终区间作为事实。

### 阶段 6：实现 M13、Canonical Fact、Family Runtime 注册和 binding

任务：

- 完成 `basic_inequality.py` 的 Family 实际注册，并将其加入 `DEFAULT_FAMILY_REGISTRY`；
- 将已实现的 8 个 Method capability contract、binding rule 和 recipe 通过 capability pack 展开到该 Family；
- 在 Runtime preflight 中检查 Family 已注册、Method 属于 Family allowlist、输入 Scope 和 Goal contract 完整；
- 将 M11/M12/M14 的结果统一绑定为可消费的 Canonical Fact；
- 保存原始表达式、规范 AST、premises、proof、equality conditions 和 source path；
- 在 StateVersion 中区分等价更新和不等式下界，不把下界覆盖为原目标；
- M13 联立所有取等关系、原始定义域、换元/消元还原和题目条件；
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
3x+4y+1≥2√(12xy)+1。
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

- `a+b≥2√(ab)`；
- `3x+4y≥2√(12xy)`；
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
