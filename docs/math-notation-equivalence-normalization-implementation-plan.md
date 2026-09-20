# 数学表达式优先：等价归一化实施计划

- 状态：已确认，直接切换
- 日期：2026-09-19
- 关联设计：[数学语义等价约束归一化实现设计](math-notation-equivalence-normalization-design.md)

## 1. 实施目标与原则

本计划把“直接数学表达式承载语义”落实到题意抽取、repair、规则夹具、编译、runtime binding 和 retry。
题面出现直角时，LLM-facing 候选统一使用 `∠ABC = 90°`；不要求模型填写面向解析器的
`angle(A,B,C)` 构造语法。

`angle(...)` 只保留为解析器内部 AST 兼容形式。解析器可以继续读取历史候选中的该别名，但新抽取、repair、
Prompt 示例和规则夹具都使用直接数学表达。Runtime 将直接表达和垂直表达映射到同一个内部 `right_angle`
Canonical Fact，且不把内部 AST 回写到候选。

本次采用直接切换，不做生产影子运行；切换前完成离线规则测试、现有 runtime binding 回放和全量回归。

## 2. Prompt 与表达目录

### 2.1 抽取 Prompt

修改 `internal/llm-prompts/problem-math-notation-system.md` 和
`internal/llm-prompts/problem-math-notation-expressions.json`：

- 角度表达只展示 `∠ABC`、`∠BAC = 2*∠DAC`、`tan(∠ABC)` 等直接数学表达。
- “∠ABC 为直角”统一抽取为 `∠ABC = 90°`。
- 题面明确使用 `⊥` 或“两直线垂直”时，才抽取 `line(A,B) ⟂ line(B,C)`。
- 明确禁止为了适配执行器而构造函数式角度语法或补写等价关系。

### 2.2 Repair 与 review Prompt

- repair 新输出遵循直接角表达；已有未授权内容逐字保留。
- review 不把历史内部角度别名当作来源错误，但不再将其作为新候选推荐写法。
- Prompt 不暴露内部 AST、Canonical Fact 或 runtime fact 名称作为模型输出字段。

## 3. Parser、编译与归一化报告

### 3.1 兼容边界

保留现有 `notation_parser.py` 对 `∠ABC` 和历史 `angle(...)` 的解析支持。两者在内部绑定到同一种
`angle` AST；对外 Schema、候选 JSON 和原始 source expression 不做字符串回写。

### 3.2 统一报告接口

沿用 `problem_understanding/notation_normalization.py`，新增：

- `equivalence_rules.py`：规则注册表和规则优先级。
- `normalization_report.py`：`DerivedFact`、`NormalizationReport` 和结构化 blocked reason。

报告至少包含：规则集版本/hash、scope、原始事实、Canonical Facts、Derived Facts、premises、proof、
strength（`equivalent` 或 `entailed`）、assumptions、source path 和阻塞原因。

当前 `semantic_normalization` 字段保持兼容，并由统一报告提供已有的 coordinate/object/proof 投影。
规则 key 必须包含 scope、实体身份和规范化 AST；归一化必须幂等、固定点收敛且禁止循环。

## 4. 规则与 Runtime binding

### 4.1 第一批规则

按以下顺序迁移和实现：

1. 现有坐标拆分、坐标轴成员、别名绑定、交点证明、比例证明和最值状态证明。
2. `∠ABC = 90°` 与共享顶点的 `line(A,B) ⟂ line(B,C)` → 内部 `right_angle`。
3. `N=(n,0)` 与 `x(N)>0` → `n>0`，仅在独立参数和 scope 唯一时成立。
4. AST 级代数规范化：交换律、等式方向、零项和同类项合并。
5. 仅在有明确对称距离证明时处理路径表达式交换。

规则缺少共享顶点、坐标绑定或作用域前提时，保留原事实并返回 blocked reason，不能猜测。

### 4.2 Lowering 与 Binding

修改 `runtime_lowering.py`：

- 消费 `NormalizationReport` 的 Canonical/Derived Facts。
- 保留原始 `math_assertion` 和 source provenance。
- 将 `right_angle`、`symbol_constraint` 等派生事实映射到现有 `ProblemFact`。
- 收拢当前 `perpendicular_angle()` 和动点坐标条件提升逻辑，避免 Macro 内重复实现等价判断。

修改 `runtime_binding.py` 和 `NotationRuntimeBundle.artifacts()`：

- 写入 `normalization-report.json`、规则集 hash 和完整 provenance。
- 将规则集 hash 纳入 semantic identity，规则变化时旧 binding 不得复用。
- 不新增数据库表，复用现有候选/binding artifact 存储。

## 5. Retry 与错误分类

统一输出以下阶段：

- `understanding_invalid`
- `normalization_missing`
- `binding_missing`
- `plan_invalid`
- `verification_failed`

归一化错误至少携带 `phase`、`missing_fact_kind`、`source_facts`、`premises` 和 `suggested_action`。
只有题意理解错误或确实缺少语义转换时才要求 LLM 重写；binding 缺失优先由确定性代码修复。
连续 retry 没有新增事实时停止并返回结构化诊断。

## 6. 测试与验收

新增 `server/tests/solver/test_semantic_equivalence.py` 和
`server/tests/solver/fixtures/semantic_equivalence/`，覆盖：

- Prompt 中包含 `∠ABC = 90°`，且不推荐 `angle(A,B,C)`。
- `∠ABC=90°`、`∠BDC=2∠ABD`、`tan(∠ABC)` 的 parser/typecheck。
- 角表达与垂直表达进入同一 `right_angle`。
- 无共享顶点、缺前提、错误 scope、OR 分支和 sibling scope 的 fail-closed 行为。
- 原始表达、source path、premises、proof 和强度保留。
- 固定点、幂等性、无循环和 proof budget 耗尽。
- 直接角表达进入现有 Method replay；坐标约束和路径回放不回归。

扩展现有数学记法、归一化、geometry proof、state proof、runtime binding、repair/review 测试，并执行十组
受信计划回放和 Solver 离线全量测试。

## 7. 切换门槛

满足以下条件后直接切换：

1. 新抽取和 repair Prompt 不再指导模型生成 `angle(...)`。
2. 直接角表达完成抽取、repair、compile、binding 和 Method replay。
3. 历史 `angle(...)` fixture 仍可被代码读取。
4. semantic hash、provenance、错误分类和 retry feedback 通过回归。
5. 设计文档、Prompt 目录、实施计划和测试断言统一遵守直接数学表达式原则。
