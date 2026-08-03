# Track F：ProblemExtractionContext 实现计划

## 1. 目标

把题目来源转换为可追溯、可校验的 `ProblemIR`：

```text
图片 / PDF / OCR / 网页
→ source observations
→ typed extraction candidates
→ deterministic normalization
→ ProblemExtractionContext
→ validated ProblemIR
```

Extractor 只报告题面事实，不选择 capability、不构造 FunctionalPlan、不推断隐藏解法，也不使用 expected answer 补事实。

F 初期以 authored ProblemIR 为 gold 运行 shadow。G 在此期间继续消费 authored ProblemIR；两条线最终通过 validated ProblemIR 和 immutable Context dependency 汇合。

## 2. 范围

实现：

- entity、fact、scope、goal 的 source evidence；
- OCR/layout 与数学语义歧义的分离；
- label normalization 和稳定对象 identity；
- primitive-first relation extraction；
- blocking issue 与 extraction retry；
-干净 ProblemIR projection；
- authored/extracted ProblemIR 的统一 solver API。

不实现：

- capability 或数学路线选择；
-方程求解、答案验证；
-根据常见图形补猜未声明关系；
- Lesson、Diagram、Animation 生成；
- Best-of-N 选择。

## 3. Context 模型

内部 schema：`problem-extraction-context/v1`。

| 区域 | 核心字段 |
|---|---|
| manifest | context/parent/source id、hash、extractor version |
| evidence | page、bbox/text span、observed text、confidence、kind |
| entity candidates | candidate id、kind、label、scope hint、evidence、status |
| fact candidates | kind、subjects、value、scope hint、evidence、status |
| goal candidates | kind、targets、scope、required、evidence、status |
| decisions | accept/reject/link/merge/split 的确定性记录 |
| issues | code、candidate/evidence refs、blocking、retryable |

Candidate status 使用：`proposed | accepted | rejected | ambiguous`。Context 保存候选和证据；ProblemIR 只保存 accepted semantic facts。

具体 dataclass 与 JSON 字段应在实现时由同一 schema 事实源生成，不在文档维护第二份完整定义。

## 4. Source 与 evidence

Source ingestion 只生成观察：

-原始文件或稳定引用、source hash；
-页码、尺寸、方向；
- OCR span、置信度和 layout block；
-图中 label、line、curve 和 region；
- extractor/version 信息。

每个语义候选必须引用 evidence。图像坐标使用 source-relative 表示，避免渲染尺寸改变 Context。

确定性 normalization 可以连接或规范 evidence，但不能制造题面未给出的事实。

## 5. Primitive-first

应提取：

```text
point M
point D
angle(M, D, N) = 90°
length(D, M) = length(D, N)
point P lies on parabola f
symbol m has domain m > 0
```

不应提取 planner-specific 概念，例如某个 recipe 已就绪或某条 capability 路线应该被采用。复合 Condition、object role 和 capability admission 由 solver contract 投影。

## 6. Identity 与 scope

- label 是 identity evidence，不是 identity 本身；
-同名多个 region 在证据唯一前保持歧义；
-坐标、长度或表达式相等不合并对象；
- Symbol 先注册 typed identity，表达式写法不创建新身份；
- scope 先由题号/layout 候选产生，再经确定性 tree validator；
- fact 放在 evidence 能证明的最窄 scope；
-所有小问前明确给出的公共事实可进入父 scope；
-不得因 sibling 后续需要而提升 child-private fact。

## 7. 实施阶段

### F0：Gold corpus 与 semantic diff

使用五道现有题图和 authored ProblemIR，补 source region manifest。比较：

- entity/fact/goal precision 与 recall；
- subject、value、scope 和 symbol/domain；
- evidence coverage；
- blocking ambiguity；
- ProblemIR semantic equivalence。

### F1：Context 与持久化

实现 immutable Context、schema round-trip、manifest、events、source 和 ProblemIR/quality projections。`state` 是权威；event 只解释决策。

### F2：Candidate extractor

Extractor 输入 source observations，输出 typed candidates。LLM prompt 只包含 primitive schema，不包含 Functional catalog、解法 few-shot 或 expected answer。

### F3：Deterministic normalization

负责：

- OCR 空白、标点和跨 span 合并；
-分数、根式、坐标和方程解析；
-题号与 scope tree；
- evidence 唯一时的 label linking；
- duplicate evidence 与 primitive fact canonicalization；
- value/type validation。

不得推断未声明的几何关系，也不得在多个对象候选中猜测。

### F4：Validation 与 retry

首批错误码：

```text
extraction.entity_identity_ambiguous
extraction.fact_subject_unresolved
extraction.fact_value_unparsed
extraction.scope_unresolved
extraction.goal_target_unresolved
extraction.evidence_missing
extraction.source_conflict
extraction.problem_ir_incomplete
```

Retry 只接收 immutable Context、未解决候选、相关 evidence 和紧凑 issue。Planner failure 只有确定性归因为 extraction gap 后才能回到 F。

### F5：ProblemIR projection

-存在 blocking issue 时禁止 projection；
- ProblemIR source manifest 只记录 Context id、source hash 和 schema/version；
-不复制 OCR 内部数据；
- extracted 与 authored ProblemIR 进入同一 family/planner/solver API。

## 8. 与 Track G 的接口

F 只输出：

```text
ProblemIR
ProblemSourceManifest
SourceVisualReferenceProjection（可选）
```

PlannerStateContext 只消费 ProblemIR。Planner prompt 不接收 OCR alternatives、bbox、被拒候选或内部 confidence。

DiagramContext 可读取 accepted label regions 和近似视觉位置，但不能新增或覆盖数学事实。

新的 accepted extraction version 会使依赖旧 ProblemIR 的 PlannerStateContext stale，并向 G 下游传播。Authored ProblemIR 不要求 extraction dependency。

## 9. Shadow

1. Authored ProblemIR 保持 solver authority。
2. F 从真实 source 生成 candidate ProblemIR。
3. Semantic diff 比较两者。
4. 必要时运行 deterministic solver preflight。
5. mismatch 归因到 extraction、normalization 或 authored gold。
6. Shadow 结果不修改正式 lesson artifact。

## 10. 测试

Unit：

- Context round-trip 和 immutable version；
- evidence normalization；
-同名不同对象与 text/diagram linking；
- primitive parsing；
- parent/child/sibling scope；
- ambiguity fail closed；
- prompt 不含 capability 或 expected answer。

Generated/metamorphic：

-重命名 label、OCR span 重排、无关文本和标点扰动；
-新增同名 region 必须产生 ambiguity；
-删除 evidence 后 dependent fact unresolved；
-改变题号后 scope 确定变化。

Integration：

-五题 source 与 authored ProblemIR semantic diff；
- extracted ProblemIR 通过 family admission；
- answer signature/provenance 与 authored 路径一致；
-至少一题进入 Track G 并编译 HTML；
- planner retry 不得用 prose 猜 extraction gap。

建议测试模块：

```text
test_problem_extraction_context.py
test_problem_extraction_normalization.py
test_problem_extraction_generated_gate.py
test_problem_extraction_to_problem_ir.py
test_problem_extraction_solver_integration.py
```

## 11. 完成条件

-五题保留全部 solver-required entity、fact、scope、symbol 和 QuestionGoal；
- blocking ambiguity 不被静默解决；
- extracted/authored ProblemIR 产生相同 required answer signature；
- extraction configuration/unclassified error 为零；
- planner payload 不包含 extraction internals；
- Context dependency 与 stale propagation 通过测试；
-至少一题通过图片到 HTML 门禁；
- solver 和 lesson-page 全量回归通过。

## 12. 顺序

```text
F0 gold corpus
→ F1 Context schema
→ F2 candidate extractor
→ F3 normalizer
→ F4 validator/retry
→ F5 ProblemIR projection
→ F/G image-to-lesson gate
```

F/G 产生完整质量、失败、延迟与 token 指标后，再启动 Track E。
