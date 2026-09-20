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

### 3.1 公共表达式字段

公开调用保留现有 `step_id`、`capability_id` 和 `args` 外壳。数学候选使用表达式字段：

```json
{
  "math": "a+b+R≥2√(ab)+R",
  "using": ["a>0", "b>0"],
  "equality": "a=b",
  "restore": ["x=±√u"]
}
```

不是所有字段都适用于每个 Method，但字段值必须是数学表达式或数学表达式列表。下列内容不进入 LLM-facing 协议：

- `term1`、`term2`、`operation`、`ast_kind`；
- `fact_id`、`state_version`、`source_ref`；
- `bound_fact_id`、`method_output_key`、`rule_id`；
- 由代码才能确定的根、区间、正项身份和 Canonical Fact。

### 3.2 八个 Method 的公开输入和输出

| Method | LLM 直接提供 | Runtime 负责 | 成功输出 |
|---|---|---|---|
| M01 `organize_expressions` | 完整等价式链 | 等价、条件代入、定义域和结构分类 | 等价 Expression 状态与 rewrite trace |
| M07 `introduce_semantic_substitution` | 换元定义、改写条件/目标、还原关系 | 映射、可行域、非一一分支和还原 | substitution Fact 与新表达式状态 |
| M08 `eliminate_by_constraint` | 消元关系、代入目标、剩余范围 | 除法前提、等价代入和范围 | elimination Fact 与降维状态 |
| M09 `reduce_symmetric_sum_product` | `s=x+y`、`p=xy`、转换和还原式 | 对称性、判别式、实根和正根条件 | sum-product Fact 与可行域 |
| M11 `apply_two_term_amgm` | 完整不等式、前提、可选取等式 | 正项识别、模板匹配、方向和目标对应 | `amgm_bound` Fact 与等号条件 |
| M12 `bound_univariate_quadratic` | 配方式、下界式、取等式 | 平方非负、参数域、界可达性 | `quadratic_bound` Fact |
| M13 `close_equality_and_restore` | 候选取等式、分支还原、原题代回式 | 联立、分支、可达性和原题验算 | extremal witness 或完整可达性证据 |
| M14 `solve_univariate_inequality` | 已验证一元不等式、变量域 | 代码计算精确解集 | interval solution；LLM 不填根和区间答案 |

M13 可以在公开能力层保持为 Family closure/Macro；如果内部保留 kernel，也不能要求 LLM 了解其内部 wiring。

## 4. 分阶段实施

### 阶段 0：冻结文档、目录和 fixture 契约

任务：

- 在基本不等式主设计中维护 8 个 Method 的表达式优先协议；
- 为每个 Method 建立公开 capability、参数 schema、输出 contract 和错误分类；
- 为 q01–q31 建立统一 ProblemIR、目标表达式、条件表达式和预期答案 fixture；
- 为每题保存允许路线、Method 链、页面步骤数量和必须出现的数学证据；
- 将 `angle(...)` 类内部记法排除在所有 Prompt 示例和 repair 建议之外。

完成标准：所有 fixture 都可以只用题面数学表达式描述，不依赖内部 Fact ID。

### 阶段 1：扩展表达式 Parser 和关系 AST

任务：

- 在现有安全 Parser 上增加 `√`、根式、有限函数、Unicode 比较符和直接分式的前端归一化；
- 支持 `=`、`≥`、`≤`、`>`、`<` 的单关系解析，并保留关系方向；
- 保留原始字符串、source span、节点 path、展示树和规范 AST；
- 建立受限函数白名单，首轮至少支持 `sqrt`、必要的幂和目标表达式函数；
- 继续拒绝 Python 语法、未知函数、未声明变量、无界展开和任意代码执行；
- 为同一表达式提供展示形式和计算形式，展示形式不被 SymPy 全局化简覆盖。

完成标准：`a+b≥2√(ab)`、`3x+4y≥2√(12xy)`、`u=x²`、`x=±√u`、`T=√(xy+4/(xy))` 可以解析、类型检查并保留来源定位。

### 阶段 2：建立数学证明内核

先实现可复用的证明原语：

- 等式等价和带等式前提的代入；
- 非零、正、非负、负的符号证明；
- 分母非零和分母正负；
- 根式存在、主值非负和有限单调对应；
- 乘法、除法、偶次幂和平方的符号传播；
- 取等条件的合取、分支和可达性检查；
- 精确有理数和代数数比较。

证明内核不做无界自动求解。每个证明结果保存 premises、规则 ID、输入节点和 proof tree；不能证明时返回明确的 `proof_missing`，不能返回“可能成立”。

### 阶段 3：扩展 M01 并实现 M11

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

### 阶段 4：实现 M07、M08、M09、M12、M14

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

### 阶段 5：实现 M13、Canonical Fact 和 Runtime binding

任务：

- 将 M11/M12/M14 的结果统一绑定为可消费的 Canonical Fact；
- 保存原始表达式、规范 AST、premises、proof、equality conditions 和 source path；
- 在 StateVersion 中区分等价更新和不等式下界，不把下界覆盖为原目标；
- M13 联立所有取等关系、原始定义域、换元/消元还原和题目条件；
- 保留正负分支、参数分支和范围题全区间可达性；
- 将 rule hash、semantic hash、provenance 写入 binding artifact；
- Runtime 只消费 Canonical Fact，不要求 LLM 暴露内部 AST。

完成标准：q12、q17、q18、q21、q25、q30、q31 的多阶段关系可以提交、回滚和重放。

### 阶段 6：讲解规则、LessonIR 和网页生成

任务：

- Method trace 产生表达式、局部节点、前提和教学片段；
- Family rule 按已验证结构组织学生步骤，不按题号或字符串相邻关系猜测；
- 固定数学步骤由代码锁定，Lesson LLM 只能编排开放文案；
- 视觉组件直接消费 verified trace，页面不重新解析或求解数学；
- 每个页面保存 ExplanationSnapshot、LessonIR、VisualStepIR、HTML 和审计 artifact；
- 页面公式保留直接数学表达式，不回写成 `angle(...)`、`amgm_bound(...)` 等内部表示。

完成标准：每道题都能从成功 Runtime artifact 生成可复现网页；失败时页面生成不会伪造成功结论。

### 阶段 7：31 题迁移、回归和切换

执行顺序：

1. 先生成 q01–q31 的离线表达式 fixture 和预期 Canonical Fact；
2. 用确定性候选跑完整求解链；
3. 生成 31 个 ExplanationSnapshot、LessonIR、VisualStepIR 和网页；
4. 对 10 道代表性题执行完整集成测试；
5. 对其余 21 题执行离线 fixture、编译、Runtime 和页面回归；
6. 比较 semantic hash、provenance、页面公式和答案；
7. 只有所有门禁通过后，才切换新的表达式优先协议。

## 5. 错误分类和 repair

错误必须区分：

| 类别 | 示例 | repair 行为 |
|---|---|---|
| 抽取错误 | 题面条件或目标表达式缺失 | 修复题意抽取，不修改 Method 事实 |
| 表达式解析错误 | 未知变量、语法、函数或关系方向 | 要求重写直接数学表达式 |
| 归一化错误 | 找不到唯一局部正项或模板 | 提供结构化诊断，要求重写完整不等式 |
| 证明缺失 | 无法证明正性、非零或根式定义域 | 要求补充题面已有数学前提，不允许猜测 |
| binding 错误 | SourceRef 不可见、类型不符、作用域错误 | 只修复绑定，不扩大权限 |
| Method 验证失败 | 等价、方向、取等或还原不成立 | 指出表达式行和失败证据 |
| closure 失败 | 取等条件不能同时满足或不可达 | 保留中间事实，要求重新选择合法路线 |
| 页面组装失败 | LessonIR、VisualStepIR 或 HTML 非法 | 不回退为未经验证的文字结论 |

repair prompt 只能使用直接数学表达式示例，例如：

```text
请重新输出完整不等式关系，例如：3x+4y+R≥2√(12xy)+R。
不要填写 term1、term2、operation 或内部 Fact 名称。
```

## 6. 测试计划

### 6.1 Parser 与证明内核

- 直接数学表达式和 ASCII 兼容表达式的双向解析；
- `√`、整数幂、分式、比较符和等式方向；
- source span、展示树和规范 AST 保留；
- 正性、非零、根式定义域、等式代入和 proof tree；
- 无法证明时 fail closed；
- 未知变量、未知函数、超大表达式和矛盾条件诊断。

### 6.2 八个 Method

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

### 6.3 代表性集成测试

第一版代表性集成测试为：

```text
q01, q03, q07, q08, q12,
q17, q20, q25, q30, q31
```

它们分别覆盖直接应用、整理、连续应用、平方换元、和积换元、范围、根式、倒数定义域、参数配方、复杂多阶段路线和完整网页组装。

每个集成样例检查：

- 题意表达式抽取；
- Method 编译和实际输入；
- Canonical Fact、StateVersion 和 provenance；
- ExplanationSnapshot、LessonIR、VisualStepIR；
- 最终 HTML 公式和步骤顺序；
- 取等解、范围或答案；
- 失败分类和 retry 证据。

其余 q02、q04–q06、q09–q11、q13–q16、q18–q19、q21–q24、q26–q29 先作为全量离线 fixture 和网页回归；如果代表集出现机制覆盖空洞，再补入集成集。

## 7. 验收门禁

切换前必须同时满足：

- 8 个 Method 的 LLM-facing Prompt 都只使用直接数学表达式；
- Parser、证明内核和 Method 不把未验证候选当作事实；
- M11 能在代表性样例中从完整不等式恢复局部两个正项；
- q01–q31 全部成功生成可审计网页，或有明确结构化失败且不伪造结果；
- 10 道代表性集成测试全部通过；
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
