# Symbolic Target Closure 与 Typed Function Binding 迭代计划

## Summary

本文档记录一条后续迭代路线：把当前针对参数求解 method 的局部补位，逐步收敛为声明式、可复用的符号目标闭包系统。

目标仍然只有一个：**减少 LLM 需要维护的符号身份、参数角色和中间代数表示，让确定性代码负责建立方程、补齐机械输入、验证唯一性、执行替换并记录 provenance。**

目标链路为：

```text
FunctionalPlan typed args
  -> FunctionalBindingContext
  -> SymbolicClosureSpec
  -> Equation / Representation Adapter
  -> TargetSymbolClosureSolver
  -> canonical method outputs
  -> PlannerStateContext / runtime provenance
```

本路线不要求 LLM 输出 canonical handle、runtime path、系数容器或内部残余符号，也不允许代码通过 method id、变量名、description 或错误文本猜测数学语义。

## Why This Iteration Exists

参数求解类 method 经常遇到以下情况：

```text
LLM 的目标参数身份：a
当前表达式内部残余符号：c
已知结构关系：a 可以由 c 唯一映射得到
```

如果 method 只检查“方程的唯一自由符号是否就是目标参数”，它会把一个可确定求解的问题误判为 identity mismatch。相反，如果代码看到任意残余符号就尝试全局求解、搜索其他 method 或猜测变量含义，又会把确定性补位变成新的启发式链路。

合理边界是：

- LLM 明确选择 capability、目标参数和数学证据；
- capability 声明如何由输入建立有限方程组；
- representation adapter 声明内部符号如何映射到目标身份；
- 共享 solver 只接受唯一、闭合且满足约束的目标值；
- 代码不自动发明新的数学步骤。

## Current Baseline

当前代码已经具备一个可复用原语：

```text
server/shuxueshuo_server/solver/runtime/symbolic_target_closure.py
```

`solve_target_symbol_closure(...)` 已支持：

- 目标符号直接出现在方程中时求解目标；
- 目标不直接出现，但存在确定性 `target_expression` 时，先求内部残余符号，再映射回目标；
- 区分 `unique / identity_unresolved / underdetermined / ambiguous / inconsistent`；
- 使用统一 `SympyKernel`；
- 返回实际 residual symbols、branch count 和 substitution。

首个接入 method 是：

```text
parameter_from_curve_point_on_quadratic
```

它已经能够处理“曲线表达式内部系数与 LLM 绑定目标参数不完全同名，但结构关系可唯一映射”的情况。

### 当前仍是兼容补丁的部分

以下部分尚未泛化：

1. FunctionalPlan 的 typed arg role 在投影成 `StepIntent.reads` 后丢失。
2. 编译器仍通过 `free_quadratic_parameter_if_read` 从无角色 reads 中恢复一个自由系数。
3. 二次函数系数到目标参数的映射仍由具体 method 组装。
4. 其他参数求解 method 尚未统一使用 target closure。
5. closure 的方程来源、约束来源、representation mapper 和 output substitution 尚未进入声明式 spec。
6. retry 和学生讲解只能看到最终错误，尚不能完整解释“目标参数如何由内部残余符号闭合”。

因此当前实现应视为迁移基线，而不是最终架构。

## Design Principles

### 1. Typed role 必须跨投影保留

FunctionalPlan 中：

```json
{
  "args": {
    "parameter": {"kind": "symbol", "ref": "a"},
    "known_parameter": {"kind": "symbol", "ref": "m"},
    "known_parameter_value": {"kind": "fact", "ref": "m_value"}
  }
}
```

不能在编译期退化成：

```text
reads = [symbol:a, symbol:m, fact:m_value]
```

然后再让 selector 猜哪个 Symbol 是 target、哪个是 known substitution。FunctionalPlan 已经提供了正确角色，代码应保留并消费它们。

### 2. StepIntent 是兼容投影，不是 typed binding 真相源

Phase 7 期间 runtime 仍消费 canonical `StepIntentDraft`，但 FunctionalPlan reconciliation 产生的 typed binding metadata 应作为 sidecar 与 projected step 一起进入 compiler。

```text
FunctionalPlan
  -> canonical StepIntentDraft
  -> FunctionalBindingContext sidecar
  -> existing compiler/runtime
```

StepIntent 原生输出模式没有 sidecar，继续使用 legacy binding rules。两条入口最终汇合到相同的 `MethodInvocation` 和 runtime method。

### 3. Equation building 与 symbolic solving 分离

Domain adapter 只负责建立有限、结构化的方程和表示映射：

- point lies on curve；
- expression equals value；
- segment length equals value；
- polynomial coefficient template；
- minimum expression equals given minimum。

共享 solver 负责：

- 方程标准化；
- residual symbol 分析；
- 分支求解；
- target expression 映射；
- 约束过滤；
- 唯一性判定。

method 不应重复实现 `sympy.solve`、分支去重和自由符号闭合逻辑。

### 4. Representation mapping 必须结构化

允许：

- `PolynomialCoefficientTemplate`；
- `PointOnCurveEquation`；
- `ExpressionValueEquation`；
- CapabilityContract 声明的 object/state identity；
- ProblemIR 中的结构字段。

禁止：

- 根据 `a_value / m_value / c_expr` 等名称猜身份；
- 解析 strategy/reason/description 文本；
- 从错误消息字符串反向推断缺失状态；
- 扫描全局可见状态并选择“看起来能算”的值。

### 5. Read-closed

符号求解只能使用：

- 当前 call 的显式 typed args；
- FunctionSpec 声明的 auto/mechanical args；
- capability contract 允许的唯一确定性 companion state；
- prior-call result 中被当前 call 显式引用的状态。

不得从 RuntimeContext 全局搜索未读取的表达式、参数值或条件。

### 6. 唯一目标结果才成功

成功条件不是“SymPy 返回了一个解”，而是：

- target identity 已确定；
- 所需 residual symbols 可闭合；
- 约束过滤后恰好一个 target value；
- target value 不含自由符号；
- 同一 substitution map 能一致更新所有 companion outputs。

## Target Models

### FunctionalBindingContext

`FunctionalBindingContext` 是 reconciliation 结果的不可变编译 sidecar，不是新的 runtime value store。

```python
@dataclass(frozen=True)
class ResolvedFunctionalValue:
    semantic_ref: dict[str, Any] | None
    runtime_type: str
    state_slot_id: str | None
    condition_id: str | None
    object_ref: str | None
    canonical_handle: str | None
    source_call_id: str | None
    source_return_role: str | None


@dataclass(frozen=True)
class FunctionalCallBinding:
    call_id: str
    capability_id: str
    projected_step_ids: tuple[str, ...]
    args: dict[str, tuple[ResolvedFunctionalValue, ...]]
    return_bindings: dict[str, ResolvedFunctionalValue]


@dataclass(frozen=True)
class FunctionalBindingContext:
    source_context_id: str
    by_call_id: dict[str, FunctionalCallBinding]
    by_step_id: dict[str, FunctionalCallBinding]
```

约束：

- 由 Functional reconciliation 确定性生成；
- 每次 canonical graph rewrite 后重新投影；
- stable graph/retry overlay 后必须重新生成，不复用过期 sidecar；
- 只保存身份和绑定来源，不保存可变 runtime value；
- 可序列化进入现有 reconciliation/context debug，不新增平行事实源。

### SymbolicClosureSpec

`SymbolicClosureSpec` 应进入 method source spec，成为 FunctionSpec/contract/runtime 的共同投影来源。

```python
@dataclass(frozen=True)
class SymbolicClosureSpec:
    target_arg: str
    equation_builder: str
    known_substitutions: tuple[tuple[str, str], ...] = ()
    representation_mapper: str | None = None
    constraint_args: tuple[str, ...] = ()
    substitution_outputs: tuple[str, ...] = ()
    require_unique_target: bool = True
```

示例：

```python
SymbolicClosureSpec(
    target_arg="parameter",
    equation_builder="point_on_curve",
    known_substitutions=(("known_parameter", "known_parameter_value"),),
    representation_mapper="polynomial_coefficient_template",
    constraint_args=("parameter_constraint",),
    substitution_outputs=("point", "parabola"),
)
```

声明必须来自 Python method spec，不在 JSON、binding rule 和 runtime method 中维护多份配置。

### Adapter Protocols

```python
class SymbolicEquationBuilder(Protocol):
    def build(
        self,
        *,
        args: Mapping[str, Any],
        known_substitutions: Mapping[sp.Symbol, sp.Expr],
    ) -> SymbolicEquationBuildResult: ...


class SymbolicRepresentationMapper(Protocol):
    def target_expression(
        self,
        *,
        target: sp.Symbol,
        args: Mapping[str, Any],
        equations: tuple[sp.Equality, ...],
    ) -> sp.Expr | None: ...
```

注册表按 adapter id 调度：

```text
SYMBOLIC_EQUATION_BUILDERS
SYMBOLIC_REPRESENTATION_MAPPERS
```

不得按 method id 写 dispatch 分支。

### Provenance

closure 应产生结构化 provenance：

```python
@dataclass(frozen=True)
class SymbolicClosureProvenance:
    capability_id: str
    call_id: str | None
    target_object_ref: str
    target_symbol: str
    equation_builder: str
    representation_mapper: str | None
    source_state_slot_ids: tuple[str, ...]
    known_substitutions: tuple[tuple[str, str], ...]
    residual_symbols: tuple[str, ...]
    solved_substitutions: tuple[tuple[str, str], ...]
    branch_count: int
    status: str
```

它进入现有 Function binding event、StateWriteProvenance 和 PlannerStateContext，不新建独立 debug 文件。

## Iteration 1: Preserve Functional Arg Roles

### Goal

实现 `FunctionalBindingContext`，让 FunctionalPlan typed args 在 canonical StepIntent projection 后仍可被 Function adapter 精确读取。

### Changes

- reconciliation result 生成 call-level typed bindings；
- projection map 增加 `call_id -> projected_step_ids` 的 sidecar 关联；
- replay/compiler 接受可选 `FunctionalBindingContext`；
- Function adapter 优先读取 typed arg role；
- FunctionalPlan 模式缺少 required typed binding 时产生 `functional.binding_context_missing`，不回退无角色全局搜索；
- StepIntent 模式保持现有 binding rules；
- Context/retry 保存 canonical candidate 后重新生成 sidecar。

### First migration

先迁移 `parameter_from_curve_point_on_quadratic`：

- `parameter` 直接取 Functional arg；
- `known_parameter` 与 `known_parameter_value` 按声明配对；
- curve/point/constraint 都按 arg role 读取；
- Functional 模式不再依赖 `free_quadratic_parameter_if_read`。

### Acceptance

- FunctionalPlan 中两个以上 Symbol 仍能稳定区分 target 与 known parameter；
- call placement/alias merge 后 binding context 指向 canonical call；
- retry stable graph 恢复后 sidecar 与 baseline candidate 一致；
- StepIntent recorded fixtures 行为不变；
- Functional 模式不再通过 reads 顺序或唯一 Symbol 猜 target。

## Iteration 2: Declarative Closure Specs

### Goal

把首个 method 中的 equation building、representation mapping 和 output substitution 配置上提到 `SymbolicClosureSpec`。

### Changes

- 扩展 `MethodSpecSource`、`MethodSpec` 和 FunctionSpec projection；
- 新增 equation builder 与 representation mapper registry；
- 新增共享 `execute_symbolic_closure(...)`；
- method 只负责准备 domain typed value 和组装最终 MethodResult；
- capability preflight 校验 adapter id、target arg、constraint arg 和 output key 均存在；
- 删除 method-local 的分支 solve/identity mismatch 拼装逻辑。

### Initial adapters

```text
point_on_curve
expression_equals_value
minimum_expression_equals_value
segment_length_equals_value
polynomial_coefficient_template
```

### Acceptance

- `parameter_from_curve_point_on_quadratic` 的 closure 行为完全由 spec 驱动；
- method source、FunctionSpec、prompt catalog 和 runtime 使用同一 spec；
- 未注册 adapter 在调用 LLM 前报 `planner_configuration_error`；
- adapter 不读取 method id，不读取文本字段。

## Iteration 3: Migrate Parameter Methods

### Goal

将同类标量参数求解 method 迁移到共享闭包执行器。

### Migration order

1. `parameter_from_expression_value`
2. `parameter_from_minimum_value`
3. `parameter_from_segment_length`
4. 后续斜率、交点、面积等参数反求 method

每迁移一个 method，必须先回答：

- target arg 是谁；
- equation builder 是什么；
- 哪些输入是 known substitutions；
- 是否需要 representation mapper；
- 哪些约束用于 branch filtering；
- 哪些 outputs 必须应用同一 substitution；
- target identity 如何写入 ParameterValue provenance。

### Acceptance

- 迁移 method 不再自行调用 `solve_equations`；
- 同类错误使用统一 typed codes；
- direct method strict mode 与 Functional adapter mode 的差异被显式声明；
- 五题 recorded fixtures 的参数答案与 provenance 不变；
- 新增 method 只注册 spec/adapter，不修改共享 dispatch 代码。

## Iteration 4: Context, Retry, and Explanation

### Goal

让 closure 结果成为 PlannerStateContext 可解释的状态转移，并让 retry 精确指出缺失角色，而不是要求 LLM理解内部 residual symbol。

### Changes

- `StateWriteProvenance` 关联 closure provenance；
- ParameterValue 的 `object_ref` 必须等于 target Symbol identity；
- substitution outputs 使用相同 substitution map 形成 transition history；
- retry issue 使用统一 code：
  - `function.target_identity_unresolved`
  - `function.target_underdetermined`
  - `function.target_ambiguous`
  - `function.constraint_system_inconsistent`
  - `function.known_substitution_missing`
  - `function.representation_mapping_unresolved`
- repair ticket 只展示 call、arg role、缺失 state 和可见兼容 refs；
- 不把内部 residual symbol 当作 LLM 必须手动绑定的新参数；
- explanation 可从 provenance 生成“代入已知参数、建立方程、解得目标参数、同步更新对象状态”的确定性骨架。

### Acceptance

- runtime blocker 能映射回 Functional call 和 target arg；
- stable graph 在 closure 失败时止于最早无效 producer；
- retry 不推荐固定 method 链；
- student explanation 使用 target identity，不泄露内部 runtime path；
- Context snapshot 可以解释每个 substituted output 的来源。

## Iteration 5: Strict Mode and Cleanup

### Goal

在 FunctionalPlan 链路稳定后删除兼容猜测，收敛为单一 typed path。

### Cleanup candidates

- Functional 模式下删除 `free_quadratic_parameter_if_read`；
- 删除 migrated method 的重复 closure helpers；
- 删除基于参数名的 identity fallback；
- 删除同一 symbolic error 的多份 message parser；
- preflight 强制所有声明 symbolic closure 的 capability 具备完整 adapter；
- legacy selector 只服务 StepIntent 模式，待 StepIntent 链路退场后再删除。

### Acceptance

- FunctionalPlan 参数求解不依赖 legacy reads 猜测；
- shared closure registry 是 adapter 调度的唯一来源；
- method spec 是 closure declaration 的唯一配置源；
- 代码扫描不再出现 migrated method 自行 `sp.solve`/`solve_equations`；
- 全量 Functional opt-in 无 compatibility fallback event。

## Method Authoring Rules

后续新增可能涉及参数闭包的 method，必须遵守以下规则。

### Required

1. **显式目标身份**
   - 输入必须有 target Symbol arg；
   - ParameterValue return 使用 `preserve_input_object`；
   - 不从 output handle 名称反推参数。

2. **声明 equation builder**
   - method 说明“由哪些 typed inputs 建立什么方程”；
   - 不在 method 中扫描 Context 寻找额外条件。

3. **声明 known substitutions**
   - Symbol 与 ParameterValue 必须成对绑定；
   - value provenance 必须属于对应 Symbol。

4. **声明 representation mapper**
   - 只有目标不直接出现在方程、但结构上可唯一映射时才需要；
   - mapper 必须基于 typed representation，不基于名称。

5. **声明 branch constraints**
   - 范围、象限、正负性等约束用于过滤分支；
   - 过滤后仍多解必须失败。

6. **统一 substitutions**
   - target value、Point、Parabola、Expression 等 companion outputs 必须使用同一 substitution map；
   - 不允许一个 output 使用求解前状态，另一个使用求解后状态。

7. **声明 state transition**
   - 更新已有 Point/Parabola 时使用 transition；
   - 新对象才使用 create；
   - provenance 指向 previous write。

8. **结构化错误**
   - 返回 typed code 和字段；
   - 不要求上层解析自然语言错误消息。

### Prohibited

- 在 method 中硬编码题目点名、参数名或 problem id；
- 因一个参数 method 失败而自动搜索另一条 method 链；
- 从 expected answer 反推参数；
- 通过调用结果碰撞判断两个输入状态等价；
- 从全局 RuntimeContext 偷选未声明输入；
- 为通过单题测试放宽多解或欠定判断。

## Test Matrix

每个 `SymbolicClosureSpec` 至少覆盖：

| Case | Expected |
|---|---|
| target 直接是唯一 residual symbol | `unique` |
| 内部 residual 可唯一映射到 target | `unique` |
| known substitution 后 target 唯一 | `unique` |
| 缺少 known substitution | typed missing issue |
| 两个及以上未闭合 residual symbols | `underdetermined` |
| 多个合法 target branches | `ambiguous` |
| 方程矛盾 | `inconsistent` |
| target 不在方程且无 mapper | `identity_unresolved` |
| mapper 依赖方程外未知符号 | `underdetermined` |
| constraint 筛选到唯一分支 | `unique` |
| target value 仍含自由符号 | failure |
| Point/Parabola companion output | 与 target 使用同一 substitution |
| repeated execution | 无全局状态泄漏 |
| Functional retry overlay | typed args 与 canonical call 对齐 |

针对 polynomial mapper 还必须覆盖：

- `a*x**2 + b*x + c`；
- 符号化等价形式；
- 正负号和项顺序变化；
- 缺项；
- 非二次表达式拒绝；
- 多个 coefficient template 候选时拒绝猜测。

## Compatibility and Migration

过渡期采用明确双轨：

```text
FunctionalPlan
  -> FunctionalBindingContext
  -> Function adapter

StepIntent
  -> legacy MethodBindingRuleRegistry

both
  -> SymbolicClosureSpec executor
  -> MethodInvocation / RuntimeContext
```

规则：

- FunctionalPlan 有 typed binding 时不得降级到 legacy selector；
- StepIntent fixtures 不要求立即迁移；
- adapter/spec 迁移完成前保留现有行为作为 oracle；
- 每次删除 fallback 前，先用五套 recorded fixtures 和 Functional opt-in 验证；
- debug 中明确记录 binding source：`functional_typed | legacy_rule | auto_mechanical`。

## File-Level Plan

建议的文件边界：

```text
runtime/functional_binding_context.py
  FunctionalBindingContext models and projection

runtime/symbolic_target_closure.py
  shared bounded solver; keep domain-neutral

runtime/symbolic_closure_specs.py
  SymbolicClosureSpec and registries

runtime/symbolic_equation_builders.py
  reusable equation builders

runtime/symbolic_representation_mappers.py
  typed representation adapters

runtime/function_specs.py
  project closure metadata into FunctionSpec/catalog

runtime/functional_plan_reconciliation.py
  produce typed binding context

runtime/recipe_compiler.py
  consume sidecar; do not infer arg roles

runtime/planner_state_context.py
  persist closure provenance and state transitions
```

若实现初期 adapter 数量很少，可先将 equation builder 和 representation mapper 放在同一模块；当注册项超过约五个或出现跨 domain 依赖时再拆分，避免先制造空抽象。

## Non-goals

本路线不处理：

- 自动选择数学 capability；
- 自动拆解新的 method chain；
- 路径降维、折线拉直等 macro 内部图重写；
- 候选点构造与几何筛选；
- 用数值试跑结果替代语义身份判断；
- FunctionalPlan 直编 `MethodInvocation`；
- 立即删除 StepIntent 兼容链路。

## Completion Criteria

本迭代路线完成时，应满足：

1. FunctionalPlan typed arg role 从 reconciliation 一直保留到 method compile。
2. 所有参数闭包 method 通过声明式 `SymbolicClosureSpec` 使用同一 solver。
3. method 不自行猜 target、不扫描全局状态、不重复实现分支求解。
4. Context 能解释目标身份、方程来源、残余符号、表示映射和 substitution outputs。
5. retry 只要求 LLM 修数学意图或补语义证据，不要求它理解 runtime 内部符号。
6. 新增同类 method 只需声明 spec 并复用/注册 domain adapter，不修改公共 dispatch。
7. StepIntent 兼容路径与 FunctionalPlan typed 路径在相同输入上得到一致 runtime output。

## Relationship to Existing Designs

本计划是以下文档的专项落地补充：

- `llm-context-model-design.md`：`FunctionalBindingContext` 和 closure provenance 是 PlannerStateContext 的 projection/event 来源，不是新的权威 runtime state。
- `functional-method-recipe-orchestration-design.md`：它把 typed FunctionSpec 的参数连接进一步落实到符号闭包执行边界。
- `method-solver-architecture.md`：`RuntimeContext`、`MethodInvocation` 和 `InvocationExecutor` 的职责不变。
- `family-capability-pack-upgrade-plan.md`：Capability Pack 负责暴露/组合能力；符号 closure spec 归属于 method capability，不归属于 family 路线偏好。

本文档应在 FunctionalPlan 五题 parity 稳定后启动 Iteration 1；在此之前，当前 target closure 实现保留为验证设计边界的兼容基线。
