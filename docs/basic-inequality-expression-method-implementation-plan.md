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

1. **数学表达式优先。** LLM 输出 `a+b≥2√(ab)`、`u=x²`、`x=±√u` 和完整等价式链，不输出内部 AST、Fact ID、`term1`、`term2` 或操作标签。
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
- 还没有统一的正性、分母符号、根式定义域和不等式方向证明器；
- M07、M08、M09、M11、M12、M13、M14 仍主要停留在设计协议，尚未形成完整 runtime 能力；
- M11 尚不能从完整不等式的左右表达式差异中恢复两个正项；
- 31 题尚未全部经过求解到 HTML 的确定性页面生成门禁；
- 代表性集成测试尚未冻结执行 artifact 和页面断言。

## 3. 目标协议

### 3.1 最小公共表达式协议

公开调用保留现有 `step_id`、`capability_id` 和 `args` 外壳。所有表达式型 Method 的 LLM-facing 候选只使用 `math` 或 `steps[].math`。题设条件、变量域、前提选择、目标角色和已验证中间事实由编译器从当前 Scope 绑定或从表达式链推导，不要求 LLM 填写语义角色字段。

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

因此，公共协议不再强行定义一个包含 `math`、`using`、`equality`、`restore` 的“大而全”对象，而是采用“必需的 `math` + 按 Method 增加的可选表达式字段”。

字段定义明确如下：

| 字段 | 层级 | 是否必填 | 定义 |
|---|---|---:|---|
| `step_id` | 调用外壳 | 是 | 本次公开步骤的稳定标识；不是数学事实。 |
| `capability_id` | 调用外壳 | 是 | LLM 选择的公开能力；不是内部 `method_id` 或 AST 类型。 |
| `args` | 调用外壳 | 是 | 当前 Scope 已绑定的输入，例如目标 Expression 和可见条件集合。 |
| `parameters` | 调用外壳 | 视 Method | 当前 Method 的数学候选；其中的值必须是直接数学表达式。 |
| `math` | Method 参数 | 单关系 Method 必填 | 一条完整等式或不等式；M11、M14 使用此字段。 |
| `steps` | Method 参数 | Method-specific | 有序数学表达式数组；每项只有 `math`。M01 使用它保留等价链。 |
| `using` | Runtime 内部 | 不输出 | 编译器从表达式差异和可见条件推导实际使用的前提。 |
| `definition` | Runtime 内部 | 不输出 | 从换元或和积表达式中识别出的定义关系。 |
| `transformed_target` | Runtime 内部 | 不输出 | 从输入目标和表达式链推导出的目标状态。 |
| `transformed_conditions` | Runtime 内部 | 不输出 | 从表达式链和原条件推导出的新可行域。 |
| `elimination` | Runtime 内部 | 不输出 | 从消元表达式中识别出的消元关系。 |
| `restore` | Runtime 内部 | 不输出 | 从还原表达式中识别出的分支和反向映射。 |
| `equality` / `equalities` | Runtime 内部 | 不输出 | 从不等式模板、平方项或闭合表达式生成的取等候选。 |
| `domain` | Runtime 内部 | 不输出 | 从当前 Scope 和表达式 free symbols 推导的变量域。 |

因此，典型调用是：

```json
{
  "step_id": "bound_1",
  "capability_id": "apply_two_term_amgm",
  "args": {"expression": "current_expression"},
  "parameters": {
    "math": "a+b+1≥2√(ab)+1"
  }
}
```

这里题设条件 `a>0`、`b>0` 通过 `current_expression` 所属 Scope 自动可见；`parameters.math` 是 LLM 提交的候选不等式。标准 AM-GM 不需要 `using` 或 `equality`。

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

每一行只有完整数学表达式。Method contract 根据输入对象、表达式关系和预期输出类型判断哪一行是定义、目标改写、前提改写或还原关系。M11/M14 只有一条关系时可使用 `math` 简写；M01 使用 `steps` 保留完整等价链。必要的前提绑定由代码尝试从当前 Scope 的可见条件中证明：先尝试单个条件，再尝试有界的条件组合；唯一成功时记录内部 provenance，多解时返回 `premise_ambiguous`，无解时返回 `premise_unresolved`。

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
| M11 `apply_two_term_amgm` | 一条完整 `math` 不等式 | 从 Scope 取得前提，完成正项识别、模板匹配、方向和目标对应 | `amgm_bound` Fact 与等号条件 |
| M12 `bound_univariate_quadratic` | `steps[].math`：配方式和下界关系 | 平方非负、参数域、界可达性 | `quadratic_bound` Fact |
| M13 `close_equality_and_restore` | `steps[].math`：取等、分支还原和原题代回 | 联立、分支、可达性和原题验算 | extremal witness 或完整可达性证据 |
| M14 `solve_univariate_inequality` | 一条完整 `math` 不等式；变量域从 Scope 读取 | 代码计算精确解集 | interval solution；LLM 不填根和区间答案 |

M13 可以在公开能力层保持为 Family closure/Macro；如果内部保留 kernel，也不能要求 LLM 了解其内部 wiring。

## 4. 分阶段实施

### 阶段 0：冻结提取契约和代表性 DeepSeek 集成测试

任务：

- 在基本不等式主设计中维护 8 个 Method 的表达式优先协议；
- 为每个 Method 建立公开 capability、参数 schema、输出 contract 和错误分类；
- 从 31 道题中挑选覆盖不同题意结构的代表性例题，建立 DeepSeek 题意提取集成测试；
- 测试真实的图片/题面输入、抽取 Prompt、直接数学表达式输出、条件、目标、问题类型和子问边界；
- 为每个代表性测试保存原始输入、模型响应、规范化表达式、抽取诊断和人工确认的 expected extraction；
- 先验证抽取结果，再冻结通过测试的抽取产物；
- 将 `angle(...)` 类内部记法排除在所有 Prompt 示例和 repair 建议之外。

完成标准：代表性 DeepSeek 提取集成测试稳定通过，输出只使用直接数学表达式；未通过的样例先修复抽取 Prompt、表达式目录或诊断协议，不进入 ProblemIR 建设。

### 阶段 1：根据通过的提取结果建立 ProblemIR

任务：

- 只使用阶段 0 已通过并冻结的抽取结果建立 ProblemIR；
- 为 q01–q31 建立目标表达式、条件表达式、变量域、问题类型、子问边界和预期答案 fixture；
- 保留每道题的原始抽取、规范表达式、source path、抽取版本和人工确认记录；
- 为每题保存允许路线、Method 链、页面步骤数量和必须出现的数学证据；
- 抽取结果无法唯一确定时，不猜测 ProblemIR，先回到 DeepSeek 提取测试修复。

完成标准：每道题的 ProblemIR 都能追溯到已通过的提取测试产物，不依赖手工隐式补充或内部 Fact ID。

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

### 阶段 6：实现 M13、Canonical Fact 和 Runtime binding

任务：

- 将 M11/M12/M14 的结果统一绑定为可消费的 Canonical Fact；
- 保存原始表达式、规范 AST、premises、proof、equality conditions 和 source path；
- 在 StateVersion 中区分等价更新和不等式下界，不把下界覆盖为原目标；
- M13 联立所有取等关系、原始定义域、换元/消元还原和题目条件；
- 保留正负分支、参数分支和范围题全区间可达性；
- 将 rule hash、semantic hash、provenance 写入 binding artifact；
- Runtime 只消费 Canonical Fact，不要求 LLM 暴露内部 AST。

完成标准：q12、q17、q18、q21、q25、q30、q31 的多阶段关系可以提交、回滚和重放。

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
3. 根据冻结抽取结果建立 q01–q31 的 ProblemIR、离线表达式 fixture 和预期 Canonical Fact；
4. 用确定性候选跑完整求解链；
5. 生成 31 个 ExplanationSnapshot、LessonIR、VisualStepIR 和网页；
6. 对 10 道代表性题执行完整求解与网页集成测试；
7. 对其余 21 题执行离线 fixture、编译、Runtime 和页面回归；
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

其余 q02、q04–q06、q09–q11、q13–q16、q18–q19、q21–q24、q26–q29 先作为通过提取测试后的全量离线 fixture 和网页回归；如果代表集出现机制覆盖空洞，再补入求解集成集。

## 7. 验收门禁

切换前必须同时满足：

- 8 个 Method 的 LLM-facing Prompt 都只使用直接数学表达式；
- Parser、证明内核和 Method 不把未验证候选当作事实；
- M11 能在代表性样例中从完整不等式恢复局部两个正项；
- 代表性 DeepSeek 题意提取集成测试全部通过，并冻结抽取产物；
- q01–q31 的 ProblemIR 全部可追溯到通过的提取产物；
- q01–q31 全部成功生成可审计网页，或有明确结构化失败且不伪造结果；
- 10 道代表性求解与网页集成测试全部通过；
- 其余 21 题的离线 fixture、Runtime 和页面回归通过；
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
