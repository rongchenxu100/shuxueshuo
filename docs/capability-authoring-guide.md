# Capability 编写指南

本文说明如何为 FunctionalPlan 增加可复用的数学能力。它描述当前约束，不记录历史迁移过程。

本文重点是公开 Function/Macro、binding 与 return contract。底层 Python Method 作为 DSL runtime primitive 的实现规范，统一见 `docs/functional-method-dsl-authoring-guide.md`。

## 1. 基本原则

FunctionalPlan 中，LLM 只负责：

- 选择合适的 capability；
- 引用题目中的数学实体和 Fact；
- 表达调用之间的数学依赖；
- 将公开 return 绑定到对象或答案。

代码负责：

- 参数角色、隐藏参数和编译映射；
- 按 Method input view 选择实体身份、最新状态、不可变值或匿名精确结果；
- `MathObjectId`、`StateVersionId` 和 scope 可见性；
- method/Macro 编译与事务执行；
- output contract、symbolic closure、状态提交和 provenance。

不要让 LLM 猜 method 名、runtime path、StateSlot、内部临时输出或编译顺序。

## 2. 权威链

```text
MethodSpecSource
→ MethodSpec
→ FunctionSpec / MacroSpec
→ capability catalog
→ FunctionalPlan call
→ typed reconciliation
→ FunctionalBindingContext
→ direct compiler
→ MethodInvocation
→ transactional execution
```

事实源应尽量靠前。生成的 JSON、prompt catalog 和测试快照都不是手工维护的第二份权威。

## 3. 选择 Function 还是 Macro

使用 Function：

- 一个公开能力对应一次 method invocation；
- 输入和输出可以直接映射；
- 不需要隐藏的中间计算。

使用 Macro：

- 一个公开能力由多个 invocation 组成；
- 内部步骤必须作为同一事务提交或回滚；
- 中间输出不应暴露给 LLM；
- public return 需要从内部 `output_key` 映射。

每个 Macro 必须声明 `execution_mode=direct|runtime_search`。`runtime_search`还必须
声明 `searchable_roles`、`candidate_builder_id`、`validation_policy_id`和不超过32的
候选预算。Method 永远不能搜索；Macro 的每个候选必须在 disposable branch 中
compile/run/check，winner 再从干净 Context 重放后提交。

不要用 Macro 固定某一道题的完整路线。Macro 应表达稳定的数学机制。

## 4. 参数契约

内部 Function/Macro contract 的每个参数必须明确：

| 字段 | 含义 |
|---|---|
| `name` | FunctionalPlan 中的参数名 |
| `semantic_role` | 参数在数学关系中的角色 |
| `binding_authority` | `wire`、`resolver` 或 `compiler` |
| `runtime_type` | method 实际接收的类型 |
| `cardinality` | 单值、可选值或有序集合 |
| `selection_policy` | `exact`、`latest`、`identity_only` 或 `compiler` |
| `runtime_input_targets` | 对应的 method/Macro 输入 |

同类型参数必须靠 `semantic_role` 区分。例如：

- `primary_parameter` 与 `dynamic_parameter`；
- `fixed_point` 与 `reference_point`；
- `free_parameter` 与 `target_parameter`。

不得根据 `reads` 顺序、handle 名称、scope 字符串或实际值猜角色。

LLM-facing catalog 只投影：

```text
name / domain_type / required / cardinality / role
```

不得投影 `PointRef`、`ParameterValue`、`Parabola`、`PathTransformation`、
`semantic_ref_role`、state kind、version 或 runtime path。Point、Function、Line、
Symbol 等具名对象始终使用数学实体 ref。只有没有题面身份的候选集、路径见证和
中间表达式才使用 `StepResultRef`。

### 策略角色权威

动点、映射点、反射对象、候选分支和拉直方向属于数学策略。LLM 提供数学实体
作为首选提示；resolver 可以恢复证明所需的中点、固定端点、所属关系和 canonical
identity，但不能用 `vertex_4`、数组位置或点名规则直接创造策略权威。

`runtime_search` Macro 可以在声明的有限候选集合上隔离试跑：先验证 LLM 提示，
提示失败时验证剩余候选。唯一 runtime-valid 替代项可以自动纠正；多个成功结果
只有 runtime 输出等价时才能确定性选取；非等价歧义必须反馈给 Planner。最终
authority 同时记录 authored ref、chosen ref、candidate checks 和选择原因。

### Binding authority

- `wire`：题目或上游调用明确提供，LLM 可绑定。
- `resolver`：由 Context 和 typed state 确定，LLM 不应覆盖。
- `compiler`：纯机械输入，例如内部 selector、固定 adapter 参数。

一个参数只能有一种 authority。冲突应在执行前 fail loud。

## 5. Return 与状态写入

每个公开 return 应声明：

- return role；
- runtime type；
- identity policy；
- write mode；
- optional/required；
- 可能的 result form；
- public `output_key`。

常见 identity policy：

- 新对象；
- 与某个输入对象相同；
- call-local value；
- answer/object projection 共享同一个 StateVersion。

常见 write mode：

- `create`：首次建立 logical state；
- `reuse`：引用已有版本，不形成新 writer；
- `transition`：从显式 predecessor 产生新版本；
- `isolated`：合法但不能与其他分支共享的状态。

公开 return 的 identity 与状态版本由 typed allocation 决定。handle 和 runtime destination 只是兼容显示或物理落点。

### Optional return

- 未物化且无人引用：不创建 StateVersion，call 可成功；
- 被 consumer 或 answer 引用但未物化：整个 call 失败并回滚；
- compiler 不得为缺失 optional return 创建幽灵 destination。

## 6. 对象与版本身份

Functional authoritative 路径只使用：

- `MathObjectId`：数学对象身份；
- `LogicalStateKey`：对象的某类 logical state；
- `StateVersionId`：该 state 的精确版本；
- `ConditionId`：条件身份；
- canonical call-result identity。

以下字段不能参与调用等价、版本选择或 predecessor 判断：

- 对象名称；
- handle 前缀；
- legacy StateSlot 字符串；
- runtime path；
- call id；
- 运行值相等。

materialized 输入必须绑定精确版本或显式 `latest` 策略。identity-only 输入只绑定对象，不读取状态。

## 7. Scope 规则

- 写入只对本 scope 及其后代可见；
- sibling scope 不能互相读取私有状态；
- 多个小问共享的对象或计算应放在共同祖先 scope；
- placement 可把 pure/shareable call 提升到安全的 LCA；
- 私有输入不可见时必须拆分调用，不能制造跨 sibling alias；
- scope 变化不能改变已锁定的数学计算身份或版本链。

能力本身不要写死题号或特定 scope id。

## 8. Symbolic closure

反求参数的能力应声明 `SymbolicClosureSpec`，而不是在 method 中维护另一套分支选择逻辑。至少声明：

- target 参数；
- equation builder；
- known substitutions；
- preserved symbols；
- constraint filter；
- substitution outputs；
- output validator。

共享 closure authority 统一处理：

- 唯一解；
- 欠定；
- 多分支；
- 不一致；
- target 身份无法确定；
- substitution 后 companion outputs 的一致性。

普通非参数 method 不需要 closure contract，但仍必须遵守 typed binding、output contract、实际 free-symbol/form 校验和事务回滚规则。

## 9. Catalog 文案

Catalog 面向“选哪个能力”，不解释内部实现。

应写：

- `use_when`：可观察的数学前提；
- `do_not_use_when`：容易混淆的相邻机制；
- args/returns 的语义角色和类型；
- return cardinality 与 identity policy。

不要写：

- 固定题号或固定解题路线；
- method id、builder id、runtime path；
- “先调用 A 再调用 B”式题目特判；
- 依赖具体对象名称的描述。

## 10. 错误分类

非 retryable configuration error：

- capability contract 不完整；
- binding role/authority 漂移；
- typed identity、版本或 destination 漂移；
- compiler input/output mapping 缺失；
- runtime output 违反声明式 contract。

可交给 LLM retry 的数学计划错误：

- 选错 capability；
- 漏参数或传错公开角色；
- return cardinality/expectation 错误；
- closure 欠定、多解或条件冲突；
- answer evidence 不完整。

不要通过换一个 recipe 掩盖配置错误。

## 11. 实现步骤

1. 在事实源中定义或扩展 MethodSpec。
2. 声明 FunctionSpec 或 MacroSpec。
3. 补齐 args、returns、binding role 和 output mapping。
4. 若反求参数，注册 closure builder/filter/validator。
5. 重新生成并校验 catalog/spec 资产。
6. 添加 method、direct compiler、transaction 和 provenance 测试。
7. 增加相邻能力负例，确认 LLM 可区分机制。
8. 运行 solver 全量回归和真实 Functional smoke。

## 12. 最小测试清单

- 直接 method 输入输出正确；
- direct compiler 只消费 typed binding；
- 同类型参数交换会失败；
- exact/latest 和 scope 可见性正确；
- optional return 三种状态正确；
- failed call 无 runtime 或 StateVersion 残留；
- answer/object projection 不形成第二 writer；
- checkpoint round-trip 保持 binding/version/closure signature；
- Explanation 只消费 canonical、verified、goal-reachable writes；
- catalog 文案不泄露内部机制。

常用命令：

```bash
cd server
uv run pytest tests/solver/test_runtime_stateless_methods.py -q
uv run pytest tests/solver/test_functional_direct_compiler.py -q
uv run pytest tests/solver/test_functional_transaction_execution.py -q
uv run pytest tests/solver -q
git diff --check
```

## 13. Review checklist

- [ ] 能力表达通用数学机制，而非单题路线。
- [ ] 每个 arg 有唯一 role、authority 和 runtime target。
- [ ] 每个 materialized input 有 typed version policy。
- [ ] 每个 public return 有 identity/write/output contract。
- [ ] Macro 中间输出保持 call-local。
- [ ] compiler 不使用字符串身份 fallback。
- [ ] 参数求解复用 shared closure。
- [ ] 配置错误 fail loud，数学错误可结构化 retry。
- [ ] 失败事务无幽灵写入。
- [ ] method、compiler、transaction、retry、explanation 均有覆盖。
