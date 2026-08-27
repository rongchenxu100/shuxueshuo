# F5-F3 / F5-F4 三次本地提交实施总结

> 历史说明：本文记录 2026-08-19 的 v4 实现。该 Retry wire 已于 2026-08-27
> 被 `functional-annotated-plan/v1` → `functional-scope-repair/v1` 取代并物理删除。
> 当前实现见 [FunctionalPlan Scope-level Retry vNext](functional-scope-retry-vnext-design.md)。

日期：2026-08-19

上游基线：`7564eeb`（`origin/main`）

提交范围：`7564eeb..HEAD`

覆盖范围：当前领先 `origin/main` 的三个本地提交，包含 F5-F4 的完整设计演进，以及 F5-F3 的最终关闭工作。

## 1. 总体结果

这三个提交依次完成了三层工作：首先引入 family 级路径最值 Macro 和结构化 Method DSL；随后将 Planner 输入收口为只引用数学实体的 wire 协议，并建立 Method view 与有界 Macro 搜索；最后关闭 F5-F3 Goal 局部重试，同时补齐执行证据、关系权威和 scope-native 生成式门禁。

本轮还实现了 `equal_length_ray_path_reduction` 的唯一角色参考路径。三个提交累计涉及约 246 个文件，新增约 3.6 万行，删除约 4200 行。

当前生产链为：

```text
scope-native Problem authority
  -> FunctionalPlan content/v2
  -> typed reconciliation and dependency DAG
  -> provisional Goal execution
  -> Goal checkpoint v3
  -> functional-goal-repair/v4 when needed
  -> exact typed restore
  -> transaction, closure and answer gates
  -> VerifiedFunctionalPlanExecution
```

F5-F3 已完成。F5-F4 仍在进行中，因为通用的有界多候选 runtime search 和其余路径 Macro 重构尚未完成。

## 2. 按提交拆解

### 2.1 `c74bbda`：Family 路径 Macro 与结构化 Method DSL

提交标题：

```text
solver：落地 F5-F4 family 高层 path-minimum macro 与 method DSL 结构化升级
```

该提交把路径最值规划从零散的底层 Method 推向 family 管理的高层能力：

- 新增 `QuadraticSquareReflectionPathMinimumSolver` family，并扩展通用二次函数、带权路径和射线等长路径 family。
- 在 family capability pack 中注册高层路径最值能力，包括所需 source Fact、Goal contract、preflight 规则和禁用条件。
- 通过 `RecipeInputDerivationSpec`、显式 strategy input target、中间连线、output alias 和 companion output，建立更完整的 recipe lowering 契约。
- 新增 `MethodOutputActivationSpec`。Method 的 active return 由实际输入、输入类型或 runtime condition 决定，不再把静态返回全集暴露给 Planner 和答案解析器。
- 新增 `symbolic_basis_role` 与 `SymbolicInputView`。只有结构化方程证明两个表示等价时，runtime 值才能投影到允许的符号基底。
- 升级 compiler/executor 的 Macro lowering、selector 注入、符号状态投影、结果形态检查和 typed diagnostic。
- 按新的输入、输出、状态和 `use_when` 语义，扩展 12 份高风险 Method JSON spec 及其 Python contract。
- 新增符号表达等价表示和 family 级路径 lowering 的确定性测试。

代表性实现：

```text
server/shuxueshuo_server/solver/family/quadratic_square_reflection_path_minimum.py
server/shuxueshuo_server/solver/family/quadratic_weighted_path_minimum.py
server/shuxueshuo_server/solver/family/quadratic_path_minimum.py
server/shuxueshuo_server/solver/runtime/macro_specs.py
server/shuxueshuo_server/solver/runtime/symbolic_state_representation.py
server/shuxueshuo_server/solver/runtime/recipe_compiler.py
```

该提交记录的全量 Solver 门禁为 `1975 passed, 12 skipped`。

### 2.2 `30a5773`：Method View、Entity-only Planner 与 Macro Search

提交标题：

```text
solver：落地 F5-F4 Method 输入 view、Macro runtime search 与实体-only Planner 契约。
```

该提交建立了后续 authority 工作依赖的领域层与 runtime 层边界：

- 新增 `MethodInputViewSpec`。当时全部已注册 Method input 均显式声明 `identity`、`latest_state`、`immutable_value` 或 `exact_result`。
- 新增 `MethodInputViewResolver`，由 Method 定义决定同一个实体读取稳定身份还是当前 scope 可见的最新状态。
- 新增 Planner 公共领域类型投影，对 LLM 隐藏 `PointRef/Point`、`Symbol/ParameterValue` 和函数身份/状态等 runtime 区别。
- 重写 v2 fixture、prompt 规则和 capability catalog：具名对象统一使用实体 ref，匿名中间结果继续使用 `StepResultRef`。
- 新增 `MacroRuntimeSearchService`，支持有界候选、隔离执行、优先验证 LLM authored role、runtime 输出签名、等价 winner 的确定性选择，以及非等价候选歧义失败。
- 新增带签名的 `macro-runtime-search-report/v1` schema，并把角色纠正和搜索证据写入 retry 与 provenance 路径。
- 收紧 scope-local latest-state 选择、call placement、state finalization、source provenance、自由参数处理和 winner clean replay。
- 推进 F5-F3 diagnostic 与 repair projection，使 runtime 错误保留可供 LLM 修复的 prompt-safe 执行细节，同时不泄漏内部身份。
- 新增 `docs/llm-sample-failure-review-guide.md`，统一逐轮审查 prompt、reasoning、Plan、runtime 和 retry 的流程，并要求使用执行图描述问题。
- 新增 Method view、Planner 公共类型、实体 binding、Macro search、prompt 卫生和 live smoke 落盘的专项测试。

代表性实现：

```text
server/shuxueshuo_server/solver/runtime/method_input_views.py
server/shuxueshuo_server/solver/runtime/planner_public_types.py
server/shuxueshuo_server/solver/runtime/macro_runtime_search.py
server/shuxueshuo_server/solver/runtime/functional_call_placement.py
server/shuxueshuo_server/solver/runtime/functional_transaction_execution.py
docs/llm-sample-failure-review-guide.md
```

该提交包含统一诊断迁移后，阶段文档记录的全量 Solver 门禁为 `1912 passed, 12 skipped`。

### 2.3 第三个本地提交：关闭 F5-F3 并建立 F5-F4.1 执行权威

提交标题：

```text
solver：完成 F5-F3 Goal 重试并落地 F5-F4.1 执行权威
```

该提交完成并加固前两个提交建立的基础：

- 通过 Goal replacement retry、mixed-scope frozen/editable authority、exact typed checkpoint restore 和 solved Goal 零重执行，正式关闭 F5-F3。
- 统一具名 return、authored return role、答案发布和恢复后匿名结果的 authority。
- 为 point-on-curve 等 Method 前置关系增加精确 binding 和 prompt-safe 结构化诊断。
- 用 scope-native C0-C5、Goal retry 和 execution-to-closure generated gate 替换旧的扁平 C0-C5 adapter。
- 新增 `VerifiedFunctionalPlanExecution` 与 `PathMinimumWitness`，把通过验真的 Macro 证据接入 checkpoint、retry、Explanation 和 Visual。
- 实现射线等长路径的唯一角色参考搜索和 witness。
- 修复具名实体隐藏状态依赖：selector 刷新和执行顺序由 typed topological order 决定，不再由 authored JSON 顺序决定。
- 完成真实 DeepSeek Planner-only `5x3`，结果为 `15/15`。

以下章节描述三个提交叠加后的最终架构。

## 3. Goal 局部重试与执行权威

- 使用独立 repair prompt 和 `functional-goal-repair/v4` response contract 完成 Goal replacement retry。
- execution checkpoint 已收敛为 `functional-goal-execution-checkpoint/v3`，retry projection 使用 `planner-goal-retry-context/v4`；v4将执行状态与修复权限分离，并为每个不可编辑Goal、scope和step提供稳定原因。v2 checkpoint稳定拒绝，不再作为生产恢复协议。
- solved Goal 和 frozen producer 通过 exact typed checkpoint 恢复；failed Goal 的 provisional write 在 replay 前全部丢弃。
- 新增 mixed-scope repair authority。同一 scope 同时服务 solved 与 failed Goal 时，retry 明确区分 frozen step 和 editable step，代码确定性合并保留的 frozen producer。
- 新增受限的 `answer_binding_replacements`。editable scope 可以修改 blocked Goal 的答案 producer，但不能修改该 Goal 的 local steps。
- restore 校验拆成 source read、runtime write 和 answer/public binding 三部分。editable consumer 的变化不再误伤完全未变的 frozen producer。
- restore 使用三个独立 typed namespace：`StateVersionId`、匿名 `CallResultId` 和 `ConditionId`。
- 恢复匿名结果时重新注册 producer、return role、scope、runtime type、exact value 和 provenance，使开放 Goal 可以继续消费 frozen `MinimumExpression`、候选集和 witness。
- 最终 completion 只绑定最终 Plan 的 id/hash。Pass 1 早期 schema 或 draft 错误仍作为模型质量指标保存，但不能否决后来已通过的最终 Plan。
- live smoke runner 在每次 provider 返回后立即落盘 prompt、reasoning、response、Plan、checkpoint、transaction 和 retry 数据。

主要实现：

```text
server/shuxueshuo_server/solver/runtime/functional_goal_execution.py
server/shuxueshuo_server/solver/runtime/functional_goal_retry.py
server/shuxueshuo_server/solver/runtime/functional_transaction_execution.py
server/shuxueshuo_server/solver/runtime/scoped_functional_plan.py
server/shuxueshuo_server/solver/scoped_functional_plan_smoke.py
```

## 4. Plan Content、Return 与 Binding Authority

- 扩展 content/v2 assembler 和 normalizer，同时保持语义校验严格：
  - 确定性省略空的可选 map 和 array；
  - 只有跨容器重复 step 的内容完全相等时才自动去重；
  - 根据 consumer analysis 删除 dead step；
  - 可解析的 draft 进入 Goal repair，不再因为局部 authoring 错误重新生成整题 Plan。
- Pass 1 和 retry 都保留 LLM authored `answer_from`；仅当 typed authority 证明唯一合法 producer 时，代码才执行确定性规范化。
- 新增共享的 `ReturnObjectAuthorityResolver`，统一 public return 到具名 MathObject 的优先级规则。
- 新增 `ReturnRoleAuthorityResolver`。只有完整 typed 二分匹配存在唯一解时，才修复 LLM authored return role 名称。
- 在完整 Plan assembly 后统一解析 `PublishedGoalRef`、具名 `SourceRef` 和匿名 `StepResultRef`。具名结果规范化为实体 ref，同时 sidecar 继续 pin 精确 producer。
- `StepResultRef` 仅用于真正匿名的值或 exact-result 消费。具名 Point、Function 或 Symbol 使用实体 ref，由 Method view contract 选择身份或状态。
- 中间参数 return 与 Goal answer allocation 解耦。求 `b` 的 Goal 可以先求 `c`，而不会把中间结果错误绑定为 `b`。
- Problem binding 失败稳定归类为 configuration/authority diagnostic，不再落入 unclassified runtime error。

主要实现：

```text
server/shuxueshuo_server/solver/runtime/functional_plan_content.py
server/shuxueshuo_server/solver/runtime/return_object_authority.py
server/shuxueshuo_server/solver/extraction/problem_planning_binding.py
server/shuxueshuo_server/solver/runtime/functional_binding_context.py
server/shuxueshuo_server/solver/runtime/functional_typed_identity.py
```

## 5. Scope、State 与依赖语义

- 收窄 B2 placement：带状态的 call 固定在 semantic owner scope。runtime-equivalent write 可以复用，但等价性不能扩大 StateVersion 可见性，也不能把局部状态移动到祖先 scope。
- 禁止不可见 sibling producer 进入 dependency DAG 或 repair cone。
- restored call 保留 checkpoint pin 的输入版本；祖先出现新 write 后，不再重新选择 `latest`。
- 对重复 writer 增加 runtime-result equivalence 校验。等价判断基于实际 typed runtime value、对象身份、自由符号身份和 provenance，而不是 step 名称或序列化输入。
- 为实体组合增加 relation authority。以下 Method 必须绑定精确且在当前 scope 可见的 `point_on_curve` Condition，不能因为 Point 与曲线实体分别可见就推断它们存在关系：
  - `quadratic_from_constraints`；
  - `parameter_from_curve_point_on_quadratic`；
  - `point_candidates_from_curve_point_condition`。
- 对 Method relation 缺失、不可见、歧义和结构错误增加稳定的结构化诊断。
- 修复 producer 在 authored JSON 中位于 consumer 之后的具名实体隐藏状态依赖。reconciliation 现在按以下顺序工作：
  1. 在 typed dependency graph 中证明恰好存在一个可见 producer；
  2. 计算 call 的拓扑顺序；
  3. 按该顺序刷新 wire selector 与 Context-owned selector。
  序列化 Plan 顺序不再被视为执行权威。
- Condition 不再被误认为实体已经具有 materialized state。

主要实现：

```text
server/shuxueshuo_server/solver/runtime/functional_call_placement.py
server/shuxueshuo_server/solver/runtime/functional_plan_reconciliation.py
server/shuxueshuo_server/solver/runtime/method_input_relations.py
server/shuxueshuo_server/solver/runtime/planner_state_context.py
```

## 6. Method DSL 与诊断

- Method spec 增加显式实体关系要求，并保留 F5-F4 input view contract：`identity`、`latest_state`、`immutable_value`、`exact_result`。
- 明确 Method view 与是否允许匿名结果是两份正交契约：一个 input 可以读取具名实体的 latest state，同时在 Method 明确声明时额外接受匿名 exact result。
- 迁移相关 Method spec 和生成的 JSON snapshot。
- typed diagnostic 统一覆盖 authoring、reconciliation、compiler、Method runtime、result check 和 Macro projection。
- prompt diagnostic 保留实体角色、参数名、expected/observed state、候选和 repair action；内部 MathObject id、version、source unit 和 runtime path 仅进入 debug。
- configuration 与 Method contract 错误不再消耗 semantic retry，直接 fail loud。
- 更新 `free_parameters` 语义：
  - 开放状态要求 LLM 填写符号基底；
  - 闭合状态允许填写 `[]` 或省略字段；
  - runtime 验证基底，并可在证明等价时执行基底转换；
  - visible symbol constraint 根据残余符号自动选择，存在歧义时明确报错而不是猜测。

详细规范见 `docs/functional-method-dsl-authoring-guide.md`。

## 7. Macro 执行证据与射线等长路径

- 新增不可变 `VerifiedFunctionalPlanExecution`，将 canonical Plan 与最终 scope-shaped execution tree、checkpoint、planning context、problem revision、semantic hash 和 execution signature 绑定。
- step 增加 typed evidence。checkpoint 与 verified execution 复用同一棵 execution tree，不再维护两份可能漂移的拷贝。
- 新增 `PathMinimumWitness` 及其 schema snapshot，记录原目标、降维目标、角色解析、构造、等价证明、合法定义域、最值策略、最值表达式、取值点、可达性检查、search report 和 provenance。
- 将 verified execution evidence 接入 runtime success artifact、Explanation snapshot、explanation role binder 和 Visual role binder。
- 从结构化 Fact 推导射线等长路径角色，生成稳定 search report、witness、prompt-safe retry evidence，并校验 clean replay。
- public 路径返回统一为 `minimum_expression: MinimumExpression`，迁移旧 `path_minimum_expression` fixture 和 few-shot 引用。
- LLM authored role 只作为候选提示。由 Fact 唯一确定的参考路径可以记录 authored/chosen role，但不能让未经验证的 authored hint 成为 source authority。

新增实现与 schema：

```text
server/shuxueshuo_server/solver/runtime/functional_execution_authority.py
server/shuxueshuo_server/solver/runtime/equal_length_ray_path_search.py
server/shuxueshuo_server/solver/runtime/equal_length_ray_roles.py
internal/schemas/verified-functional-plan-execution.schema.json
internal/schemas/path-minimum-witness.schema.json
```

完整 Macro 清单和剩余重构见 `docs/path-minimum-macro-redesign.md`。

## 8. Planner Prompt、Fixture 与 Schema

- 更新 Pass 1 和 Goal repair system prompt，明确 scope step 与 Goal step、实体 ref 与匿名结果、开放/闭合参数基底、return publication 和 retry 编辑边界。
- Pass 1 与 retry 继续使用独立 prompt 和独立 schema。
- 更新 v2 few-shot、生产仍在使用的 legacy mechanism example、scope-native fixture、v2 fixture、compile manifest 和相关 solver gold data。
- 重新生成或更新 diagnostic、Problem binding、Goal repair、retry context、checkpoint、verified execution 和 path witness schema snapshot。
- live debug 持久化 provider reasoning、transport sub-attempt、normalized content、authority、checkpoint、repair、transaction 和最终 completion 数据。

## 9. Scope-native Generated Gate

旧的扁平/call-oriented C0-C5 reference model 已删除，替换为 scope-native oracle 和 production adapter：

```text
C0-C3 authority matrix       >= 10,000 scenarios
Goal repair lifecycle               512 scenarios
symbolic closure                    2,048 scenarios
execution -> closure -> retry         256 scenarios
```

门禁覆盖 scope topology、Goal state、initial/latest/exact read、StateVersion destination、sibling isolation、runtime equivalence、mixed-scope repair、stale authority、answer producer 变化、closure、provenance 和 ghost-write rollback。每个 scenario 都有稳定 id 和环境变量单场景重放入口。

迁移后删除：

```text
旧版跨作用域版本 support 模块
旧版 Functional binding 生成器
旧版跨作用域版本 generated tests
server/tests/solver/test_functional_binding_generated_gate.py
旧版跨作用域版本 failure fixtures
旧版跨作用域版本 executable-oracle 设计文档
```

新门禁设计见 `docs/scope-native-c0-c5-executable-gate.md`。

## 10. 验证证据

typed dependency order 修复后的最新完整离线回归：

```text
2138 passed, 12 skipped
git diff --check: passed
```

最新真实 DeepSeek Planner-only 批次：

```text
batch: f5f41-typed-dag-order-fix-5x3-20260819
model: deepseek-v4-flash
samples: 15/15 completed
Pass 1 wire schema: 15/15
final Plan contract: 15/15
reconciliation / compile / transaction: 15/15
semantic attempts: 18
Goal repairs: 3
solved call restores: 13
solved Goal reexecution: 0
repair authority drift: 0
failed transaction ghost writes: 0
configuration / unclassified errors: 0
prompt identity leaks: 0
```

三次 repair 分别发生在和平一模 sample-03、和平二模 sample-02 和 sample-03。南开三份样本全部在第一次 semantic attempt 通过，包括此前失败的 consumer 位于 producer 之前的 Plan 形态。

## 11. 剩余边界

F5-F4 尚未完成。以下工作有意留在本次三个提交之外：

- 为全部已注册 Macro 实现通用的 pre-binding、有界多候选 shadow runtime search。
- 将其余路径 family 迁移为高层 `minimum_expression` contract。
- 从其余 family 的 Planner prompt 中移除内部 Path witness、辅助端点和 Method wiring。
- 在所有 Macro family 上证明唯一候选、歧义候选和 winner clean replay 的正确性。
- 完成规划中的 path-Macro live gate，包括超长 thinking 和 prompt 内部 Path 类型为零的检查。

因此，当前实现的射线等长路径 Macro 应描述为“唯一角色参考路径已完成”，不能视为整个 F5-F4 track 已完成。
