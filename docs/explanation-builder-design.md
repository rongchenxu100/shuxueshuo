# Explanation Builder 设计

## 1. 目标

Explanation Builder 将已验证的执行事实组织成学生可理解的讲解。它不重新求解题目，也不从 runtime trace 猜数学结论。

```text
FunctionalPlan canonical graph
+ transactional runtime results
+ typed provenance
+ goal verification
→ ExplanationSnapshot
→ teaching traces
→ LessonIR
```

## 2. 输入边界

只消费：

- canonical call；
- runtime verified call；
- required goal reachable subgraph；
-实际 StateVersion writes；
- method trace fragments 和 runtime checks；
- symbolic closure provenance；
- ProblemIR 对象、条件和目标。

不得消费：

- alias、dead、failed、blocked call；
- 回滚事务的输出；
- 未提交 provisional branch；
- expected answer；
- runtime path 或内部 compiler id；
- LLM 原始 reason 作为数学事实。

## 3. ExplanationSnapshot

Snapshot 是讲解阶段的唯一事实入口，包含：

- problem/goals；
- canonical call order；
- presentation scope；
- verified values 与 forms；
- state transitions 和 provenance；
- answer producer；
- structured teaching traces；
-可展示的 planner insights。

Snapshot 必须可独立序列化、校验和重放。Lesson/page 生成不应直接读取 SolverResult 的杂项 debug 字段。

## 4. 调用到教学步骤

默认一条 public call 对应一个教学单元，但允许基于结构化关系合并：

- 同一次 symbolic closure 的多个 companion returns；
- 一个 Macro 内部的稳定教学机制；
- 只承担机械 substitution 的紧邻步骤。

不能合并：

- 不同 target 参数的求解；
- 不同 goal branch；
-需要学生看到的关键条件筛选；
- scope 不同且存在明确引用关系的步骤。

跨 scope 复用时，presentation 显示“由前面结果可得”，不重复执行数学计算。

## 5. Teaching trace

Method/Macro 提供结构化 trace fragments，例如：

- 使用了哪些条件；
- 建立了哪类方程；
- 得到了什么中间结论；
- 进行了何种代入或变换；
-哪些 runtime checks 通过。

Explanation Builder 负责排序、去重和学生化表达，不应解析任意 debug 文本恢复结构。

### Symbolic closure trace

同一 closure signature 只生成一次参数求解步骤：

1. 根据结构化来源建立方程；
2. 求 target 参数；
3. 必要时按范围条件筛选分支；
4. 代入 affected returns；
5. 说明最终对象状态和剩余自由参数。

ParameterValue、Parabola、Point 等 companion writes 共享同一 teaching trace。

## 6. LessonIR 输出

每个 Lesson step 至少保留：

- stable step id；
- source call/version refs；
- scope 与 goal 归属；
-教学标题和正文结构；
- math expressions；
- object roles；
- checks/evidence；
- visual intent hints。

LessonIR 不保存 runtime path、typed id 的内部序列化或 compiler 临时输出。

## 7. LLM 的职责

LLM 可用于：

- 改写学生友好的措辞；
- 选择合理的讲解粒度；
-生成过渡句；
-根据教学目标调整强调顺序。

LLM 不可：

- 修改数值和公式；
-更换 answer producer；
-补造不存在的证明步骤；
-跳过未通过的 runtime check；
-从对象名称猜 identity。

所有 LLM 输出必须回查 Snapshot 中的 source refs。

## 8. Context 集成

Track G 将 ExplanationSnapshot 作为 `ExplanationContext` 的 state：

- parent 指向 PlannerStateContext；
- artifact 记录 LessonIR hash；
- changed dependency 只失效受影响步骤；
- Diagram、Voiceover 和 Animation 分别消费有限 projection。

## 9. 失败与诊断

- verified call 无法映射到教学步骤：configuration error；
- goal answer 缺 provenance：拒绝生成；
- closure companion signature 不一致：拒绝生成；
- source step/call 映射缺失：记录明确 mismatch，不能静默丢弃；
- LLM 文案未引用有效 facts：重新生成或回退确定性模板。

## 10. 测试

- canonical/goal-reachable 筛选；
- alias、failed、blocked 不进入 Snapshot；
-跨 scope 引用顺序；
- closure teaching trace 去重；
- answer producer 与 MathObject identity；
- source mapping 缺失 fail loud；
- Snapshot JSON round-trip；
- LessonIR facts 全部可追溯；
-旧页面的关键教学覆盖不退化。

常用命令：

```bash
cd server
uv run pytest tests/solver/test_explanation_snapshot.py -q
uv run pytest tests/solver/test_explanation_snapshot_symbolic_closure.py -q
uv run pytest tests/solver -q
```

## 11. 相关文档

- `docs/llm-context-model-design.md`
- `docs/visual-step-ir-design.md`
- `docs/functional-planner-next-stage-roadmap.md`
