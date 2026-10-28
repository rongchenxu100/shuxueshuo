# 基本不等式自动求解：能力边界与后续工作

适用于 FunctionalPlan authoring 链；题目编号指 `internal/senior-high/lesson-specs/inequality-basic-q01` 至 `q31`。静态 `/1/` 练习页与自动求解验收分开。

## 当前能力

Parser、有限证明内核、M01 完整等价整理、M08 条件消元、M07 换元、M11 局部求界、M12 二次式求界、M13 原条件与取等闭合已有实现。Scope 共享事实和分层证明搜索采用当前 v2 协议，见[证明搜索](scoped-proof-search-architecture.md)。

Method 具体契约与 31 题数学路线见[Method 设计](basic-inequality-method-discussion.md)。M01、M07、M08 的来源、定义域、还原与证据分别见[整理](organize-expressions-q08-design.md)、[换元](substitution-method-design.md)、[条件消元](constraint-elimination-method-design.md)。教学采用 Method/rule 声明、已验证证据投影与确定性组件绑定。

## 后续工作与完成条件

- M09 和积换元与 M14 一元不等式：完成原语、Runtime、精确区间、原变量还原及可达性验证，以 q17 整题链验收；不能将数学设计表当作已开放能力。
- 综合题 q20、q31：补齐根式、定义域和多阶段目标闭合，验证各 Method 的真实依赖。
- 统一生产 Family 注册与证据合同：通过完整准入、来源、Scope Retry、恢复、解释和页面门禁后再开放，不按题号路由。
- 完成 31 题全量迁移和网页覆盖。确定性计划、真实 Planner、真实 Lesson 和浏览器分别验收；真实失败保留，不能只选成功样本报告。

每批先冻结来源和完整数学目标，再交付求解、公开证据、讲解与页面。expected answer、手写页面解答及教师答案不得进入求解输入。尚不支持的证明或结构明确返回能力缺口，不增加猜测兜底。

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

除 5A 单独纳入的 q29 外，其余 q02、q04–q06、q09–q11、q13–q16、q18–q19、q21–q24、q26–q28 在代表集完整集成测试通过后直接做页面泛化验证，不预建独立提取 gold、答案或阶段 1 ProblemIR fixture。页面必须消费原题条件和目标、经过同一已注册数学能力边界；不按题号新增求解分支，未实现能力须明确报告，失败时不生成伪造答案或教学步骤。

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
