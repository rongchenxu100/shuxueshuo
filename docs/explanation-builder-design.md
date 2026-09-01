# Explanation Builder 设计

## 1. 目标

Explanation Builder 将已验证的执行事实组织成学生可理解的讲解。它不重新求解题目，也不从 runtime trace 猜数学结论。

```text
FunctionalPlan canonical graph
+ VerifiedFunctionalPlanExecution
+ ProblemIR public facts
→ ExplanationSnapshot v3
→ LessonIR
```

## 2. 输入边界

只消费：

-最终 Canonical Plan 的递归 Scope/Goal/step 树；
- `VerifiedFunctionalPlanExecution` 中与该树逐项对应的 `runtime_verified` step；
-实际物化的完整 public runtime results；
-经过 student-safe projector 审计的 public evidence/checks；
- Canonical Goal 的 `answer_from`；
- ProblemIR 对象、条件、目标与 revision/hash。

不得消费：

- alias、dead、failed、blocked call；
- 回滚事务的输出；
- 未提交 provisional branch；
- expected answer；
- runtime path 或内部 compiler id；
- LLM 原始 reason 作为数学事实；
- transactional replay、StateVersion write、method trace fragment 或 Planner insight；
- Macro kernel 的 synthetic identity、candidate 或 loser。

## 3. ExplanationSnapshot

Snapshot 是讲解阶段的唯一事实入口，包含：

- ProblemIR public projection；
- problem revision/semantic hash、Canonical Plan hash、verified execution hash；
-与 Canonical Plan owner/order 同构的递归 `root_scope → steps/goals/children`；
-内联在唯一 owner 容器中的 verified `TeachingSource`；
-每个 source 的原 authored step、完整 public results 与审计后 evidence/checks；
- Canonical `answer_from` 和已验证答案；
-内联在 consumer 参数上的精确 SourceRef/StepResultRef。

跨 Scope 消费在 Snapshot 构建时使用 `VerifiedFunctionalPlanExecution/v2` 的
`dependency_graph` 与 `public_result_dependencies` 解析，并写入 consumer 的 per-input ref。
Scope 树确定 owner/visibility，input ref 确定实际 producer/public return；不得通过字符串
channel、return 名、Scope depth 或 authored order 猜 producer，也不持久化第二份全局 edge
collection。

Snapshot 必须可独立序列化、校验和重放。Lesson/page 生成不应直接读取 SolverResult 的杂项 debug 字段。
Snapshot 不持久化 flat source/owner/dependency map；按 ID 或依赖查询的结构只允许从
`root_scope + input refs` 派生。F5-F5B 直接把协议升级为严格的
`explanation-snapshot/v3`，物理删除 `TeachingCrossScopeReference`、顶层
`cross_scope_references` 及其 builder/validator；不提供 v2 兼容读取或双写。hydrate 会拒绝
额外字段，并从嵌套 authored body 重新计算 Canonical Plan hash。

## 4. 调用到教学步骤

F5-F5A 中，一条 verified public call 只投影为一个原子的 `TeachingSource`。F5-F5B 可由统一
教学构建器把一个 source 展开为多个学生 substep，但只能依据已注册的 public evidence，且
所有 substep 继承 source 所在的 Scope/Goal owner。

LLM 可以在学生层自行调整粒度：同一 Scope/Goal 中 canonical-contiguous teaching materials
可以任意分开或合并，代码不维护“该不该合并”的 Method/Macro policy。代码只拒绝跨 Scope/Goal、
非连续分组、coverage 遗漏和 canonical order 逆转；数学详略由 LLM 判断。

跨 scope 复用时，presentation 显示“由前面结果可得”，不重复执行数学计算。

## 5. Teaching evidence

Method/Macro 可通过专用 projector 提供 student-safe public evidence，例如使用了哪些公开
条件、得到了什么公开中间结论、哪些 runtime checks 通过。Explanation Builder 负责排序、
去重和学生化表达，不得解析任意 method/debug trace 恢复结构，也不得查看 Macro 私有步骤。

F5-F5B 首先引入 `TeachingEvidenceProjector` registry。未知 evidence 继续 fail loud；
`PathMinimumWitness`、symbolic closure 和未来 evidence 分别注册 projector，并直接删除
`TeachingTraceEntry/trace_refs`；不得把真实 method invocation trace 或 Macro kernel 链重新
引入教学合同。

普通 Method 不再读取 `MethodExplanationSpec` 生成教学模板；它可以声明一个最小
`TeachingUnitSpec`，声明了就使用，未声明时由代码生成 default unit。单一学生推导的原子
Macro 隐藏多个公开认知动作时，在 Macro/Recipe spec 上声明有序 `TeachingUnitSpec[]`。
Spec 可保存建议的 title/nav_title/goal/derive/box templates，但不携带 calculation importance、
unit mapping、merge policy 或当前题数据；unit key/ID 只属于代码内部 authority，不进入 LLM
输入。

多分支 Macro 只有在学生推导结构真正不同时才声明 `TeachingVariantSpec[]`。Runtime verified
evidence 提供 typed teaching case，Explanation Builder 必须唯一选择实际 Variant 后再生成
materials；内部候选搜索、等价实现路径、其他 Variant 和 variant key 不进入 LLM。Piecewise
public result 使用包含全部必讲分支的 composite Variant。

### Symbolic closure evidence

F5-F5B 为 closure 增加 public evidence projector 后，同一 closure signature 只生成一次参数
求解步骤：

1. 根据结构化来源建立方程；
2. 求 target 参数；
3. 必要时按范围条件筛选分支；
4. 代入 affected returns；
5. 说明最终对象状态和剩余自由参数。

ParameterValue、Parabola、Point 等 companion public results 共享同一学生步骤组；内部 state
write 不进入 Snapshot。

## 6. LessonIR 输出

LessonIR 使用与 Canonical Plan/ExplanationSnapshot 同构的递归
`root_scope → steps/goals/children`。Scope 和 Goal 容器都使用同一 `steps[]`
字段与同一 LessonStep Schema，owner 由所在容器唯一表达；当前
flat `sections + steps` 仅作为待迁移 compatibility view，不能继续作为目标合同或 hydrate
authority。需要按 ID 查询时，从树机械派生内存 index。

每个 Lesson step 至少保留：

- stable step id；
- 由代码注入的 source step、capability、内部 teaching-material authority 与 evidence refs；
- 由递归容器表达的 scope 与 goal 归属；
-教学标题和正文结构；
- LLM 基于 verified calculations 写出的 presentation math；
- validated `visual_id/mode` selections。

LessonIR 不保存 runtime path、typed id 的内部序列化或 compiler 临时输出。

## 7. LLM 的职责

LLM 可用于：

-参考绑定完成的 suggested `title/nav_title/goal/derive/box`，结合完整 student-safe
  inputs/outputs/calculations 写最终五类字段；
- 选择合理的讲解粒度；
-生成过渡句；
-根据教学目标调整强调顺序；
-从代码已绑定的 `available_visuals` 中选择 `visual_id/mode`。

LLM 不可：

-发明 verified calculations 中不存在的数值、公式、对象或证明；
-更换 answer producer；
-补造不存在的证明步骤；
-跳过未通过的 runtime check；
-从对象名称猜 identity；
-填写 source/evidence refs、visual role binding、geometry 参数、interaction 或 animation。

代码先用 verified runtime bindings 把模板填成学生数学语言 suggested
title/nav_title/goal/derive/box，再按顺序直接内联为 teaching materials。LLM 不看到或回显
unit ID；每个 Lesson Step 用 `material_count` 表示连续消费几个材料。source/evidence
provenance 由代码根据内部 authority 与该 count 注入。代码校验 Scope/材料覆盖/结构与安全
边界，但不宣称逐句证明自由 `derive` 的数学语义。完整合同见
[Lesson Scope LLM Authoring 与视觉选择 vNext](lesson-scope-llm-authoring-vnext-design.md)。

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
- LLM Scope body 结构或安全边界无效：单次调用后回退 deterministic Lesson body，不做
  semantic retry；
- 只有 visual selection 无效：保留合法正文，局部回退该步骤的 visual default。

## 10. 测试

- Scope/Goal/step owner、顺序和数量与 Canonical Plan 完全同构；
- failed、blocked、not-run、provisional 和 shadow 不进入 Snapshot；
-跨 scope 引用顺序；
-完整 materialized public results 无损投影；
-内部 identity/private Macro marker fail loud；
- answer producer 与 MathObject identity；
- source mapping 缺失 fail loud；
- Snapshot 严格 JSON round-trip 与 Canonical Plan hash 重算；
- LessonIR facts 全部可追溯；
-旧页面的关键教学覆盖不退化。

常用命令：

```bash
cd server
uv run pytest -n auto --dist=loadscope -q \
  tests/solver/test_explanation_builder_text_heping_yimo.py \
  tests/solver/test_visual_step_ir_vs1.py \
  tests/solver/test_visual_step_ir_heping_ermo.py \
  tests/solver/test_strategy_planner_functional_plan.py \
  tests/solver/test_functional_direct_compiler.py
```

## 11. 相关文档

- `docs/teaching-scope-student-visual-animation-design.md`
- `docs/lesson-scope-llm-authoring-vnext-design.md`
- `docs/llm-context-model-design.md`
- `docs/visual-step-ir-design.md`
- `docs/functional-planner-next-stage-roadmap.md`
