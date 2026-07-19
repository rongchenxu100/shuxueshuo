# Capability 创建规范

## 1. 目标

本文档规定如何为 Solver 新增或修改 capability，包括：

- 无状态数学 Method；
- 对外暴露的 FunctionSpec；
- 由多个 Method 组成的 Recipe / MacroSpec；
- CapabilityContract；
- Capability Pack 与 Family override；
- FunctionalPlan catalog、reconciliation、runtime 和 retry 所需的元数据。

唯一目标是：**让 LLM 只负责选择数学能力和连接语义证据，把类型、对象身份、
状态版本、作用域、输入绑定、结果闭合和错误定位交给确定性代码。**

新增 capability 不能只满足“某道题能跑通”。它必须同时回答：

1. LLM 在什么情况下应该选择它？
2. LLM 最少需要提供哪些语义输入？
3. 代码还会确定性补充哪些机械输入？
4. 它读取和写入哪些 StateSlot / Condition？
5. 输出属于哪个数学对象，代表创建、状态转移还是普通值？
6. 两次调用在什么条件下可以视为同一次计算？
7. 失败属于系统配置错误、确定性修复，还是应交给 LLM 的数学修复？

本文是新增 capability 的规范性入口。现有 legacy capability 可能尚未满足全部条款；
新增能力不得继续复制 legacy 缺口，修改旧能力时应按本文逐步收敛。

相关设计背景：

- `docs/family-capability-pack-upgrade-plan.md`
- `docs/functional-method-recipe-orchestration-design.md`
- `docs/llm-context-model-design.md`
- `docs/symbolic-target-closure-evolution-plan.md`

## 2. 单一真相源

Capability 的信息会被投影到多个层，但不能在多个层手工维护同一份定义。

```text
MethodSpecSource
  -> MethodSpec
  -> FunctionSpec
  -> Functional Capability Catalog
  -> Function adapter
  -> MethodInvocation

StepRecipeSpec + RecipeExecutionSpec + CapabilityContractSpec
  -> MacroSpec
  -> Functional Capability Catalog
  -> Macro adapter
  -> existing recipe compiler
```

权威来源如下：

| 信息 | 权威来源 |
| --- | --- |
| Method 输入、输出、纯度、结果形态 | `runtime/methods/<method>.py` 中的 `MethodSpecSource` |
| 通用 Method binding | `family/common_binding_rules.py`，再由 pack 引用 |
| Recipe 调用序列、输出角色、identity、write mode | `RecipeExecutionSpec` / `RecipeOutputAliasSpec` |
| StateSlot / Condition 读写契约 | `CapabilityContractSpec` |
| 通用能力归属 | Capability Pack |
| 题型路线偏好和真正的机制差异 | FamilySpec local override |
| FunctionSpec / MacroSpec | 从上述来源确定性投影，不手写第二份 |
| Functional catalog | 从 FunctionSpec / MacroSpec 投影，不手写 |
| `internal/method-specs/*.json` | 派生产物，不是源码真相源 |

禁止为了修一条测试，在 FunctionSpec、MacroSpec、catalog 或 compiler 中再复制一份
输入输出配置。

## 3. 先判断：Method 还是 Recipe

### 3.1 使用 Method / FunctionSpec

满足以下条件时使用 Method：

- 是一个可独立描述的原子数学运算；
- 输入和输出都有稳定 runtime type；
- 本身无状态，不读取全局变量；
- 不直接写 RuntimeContext；
- 相同 typed inputs 应得到相同结果；
- `InvocationExecutor` 可以作为唯一副作用边界。

示例：

- 两点距离；
- 中点坐标；
- 参数代入表达式；
- 根据已知约束求二次函数；
- 两直线交点。

### 3.2 使用 Recipe / MacroSpec

满足以下情况时使用 Recipe：

- 一个学生可理解的动作需要多个 Method；
- 中间结果不应该暴露给 LLM；
- 内部调用顺序和 wiring 是稳定机制；
- Recipe 整体具有明确的 StateSlot / Condition 读写语义。

示例：

- 生成直角等长候选点并按约束筛选；
- 生成折线拉直候选、选择方案并计算距离；
- 对曲线候选点逐一反求参数并筛选。

不要把“这道题需要连续调用三个能力”直接写成 Recipe。只有当这三个调用共同表达
一个可复用机制，而且内部结果不需要 LLM 决策时，才应封装。

## 4. Method 创建规范

### 4.1 Method 必须无状态

Method 只能消费传入的 typed inputs，返回 `StatelessMethodResult`。禁止：

- 在 Method 内扫描 RuntimeContext；
- 根据当前题号、Family 或 scope 改变算法；
- 解析 `strategy`、`reason` 或 description；
- 根据变量名猜对象身份；
- 直接写 answer、fact 或 point path。

Method 可以使用 SymPy，但必须显式检查：

- 分支数量；
- 自由符号；
- 定义域和约束；
- 输出类型；
- 唯一性。

### 4.2 MethodSpecSource 必填信息

一个 LLM 可见的 Method 至少应声明：

```python
MethodSpecSource(
    method_cls=SomeMethod,
    title="...",
    summary="...",
    solves=("...",),
    inputs={...},
    outputs={...},
    preconditions=(...),
    postconditions=(...),
)
```

`summary` 应回答“什么时候使用”，不能只是复述函数名。

当出现稳定误用时，增加泛化的 `do_not_use_when`：

```python
do_not_use_when=(
    "输入状态尚未建立时，不使用该能力直接猜测结果。",
    "该能力不负责生成其前置表达式。",
)
```

禁止出现：

- 题目来源和题号；
- 固定点名；
- expected answer；
- “下一步必须调用某个具体 capability”的固定链路。

### 4.3 输入设计

每个输入应能归入以下类别之一：

- `slot_read`：读取一个已有状态值；
- `condition_read`：读取一个结构化数学条件；
- `point_ref` / `object_ref`：读取对象身份；
- `symbol`：读取明确的 Symbol identity；
- `auto`：由代码唯一、机械地补全。

输入设计遵守 read-closed：

> MethodInvocation 的数学输入只能来自当前 call 显式引用的状态、声明式 auto arg，
> 或 contract 允许的唯一 companion state。

不得从全局可见状态中选择“看起来能算”的表达式、点、参数值或条件。

### 4.4 输出设计

每个输出必须有稳定 runtime type。多个不同语义输出必须使用不同 output key，不能用
一个模糊的 `Point many` 代替两个角色不同的 Point。

如果输出可能是开放表达式，也可能是闭合数值，应声明 `ScalarResultFormSpec`：

```python
scalar_result_forms={
    "distance": ScalarResultFormSpec(
        possible_forms=("open_expression", "closed_value"),
        description=(
            "仍含未确定参数时为 open_expression；不存在自由参数时为 "
            "closed_value。"
        ),
    )
}
```

结果形态由 runtime 的自由符号决定，不通过字符串外观判断。

## 5. CapabilityContract 创建规范

Contract 描述 capability 对 PlannerStateContext 的状态变换：

```text
slot_reads
condition_reads
slot_writes
condition_writes
dependency_policy
execution_status
```

Contract 是 prompt preflight、Function/Macro 投影、scope 检查、output type 推导和
调用等价判断的声明依据，不是 runtime value store。

### 5.1 StateSlotPattern

StateSlotPattern 至少考虑：

- `state_kind`；
- `runtime_type`；
- `object_kind`；
- `semantic_role`；
- `scope_policy`；
- `cardinality`；
- `required`；
- 写入时的 `write_mode`；
- 必要时的 `provides_semantic_roles`。

`semantic_role` 面向数学含义，例如：

```text
path_transformation
moving_locus
selected_target_point
path_minimum_expression
parameter_value
```

不要使用 runtime 路径、临时变量名或题目点名作为 semantic role。

### 5.2 ConditionPattern

ConditionPattern 用于“条件存在本身就是前提”的输入，例如：

- 点在曲线上；
- 两线段等长；
- 点在线段上；
- 两角之和等于定角；
- 给定最小值。

如果一个 ProblemIR fact 同时携带可计算值和条件语义，Context 可以为它建立多个视图，
由 arg contract 决定读取 Condition 还是 StateSlot。不要要求 LLM重复构造两份 fact。

### 5.3 `provides_semantic_roles`

当一个结构化输入已经封装了另一个可选角色时，用该字段声明：

```python
_slot(
    "transformation",
    "PathTransformation",
    semantic_role="path_transformation",
    provides_semantic_roles=("moving_locus",),
)
```

这表示 `PathTransformation` 已经能够提供 `moving_locus` 视图。若 LLM 同时提交一个
类型不兼容的 optional `moving_locus`，elaborator 可以确定性删除该冗余输入；如果
显式输入类型兼容，则继续保留，不覆盖 LLM 的有效选择。

该机制不是模糊 fallback。只有 contract 显式声明 provider role 时才能使用。

## 6. `explicit_args` 与 `context_closure`

`CapabilityDependencyPolicy` 当前有两种：

```python
Literal["explicit_args", "context_closure"]
```

### 6.1 默认使用 `explicit_args`

当 FunctionalPlan args 和它们引用的 CallResultRef 已足以确定所有数学输入时，使用
默认值 `explicit_args`。

典型情况：

- 两点距离显式读取两个 Point state；
- 参数代入显式读取表达式和 ParameterValue；
- Recipe 显式读取一个具有确定版本的 PathTransformation；
- 调用读取前序 call 的明确 return role。

### 6.2 何时使用 `context_closure`

只有同时满足以下条件时才使用 `context_closure`：

1. Wire args 只是概括性关系、目标 Condition 或对象引用；
2. adapter/compiler 必须从 Context 继续展开隐藏角色；
3. 隐藏角色会影响数学结果；
4. 相同 wire JSON 在不同调用时刻可能读取不同 StateSlot 版本；
5. reconciliation 后能够用 StateSlot、Condition、object identity 和 provenance
   完整描述这些依赖。

当前示例是 `two_moving_points_path_reduction`：LLM 只提交路径目标关系，但执行时还要
解析动点当前坐标、固定端点、长度关系和参数 provenance。求参数前后的相同 call 文本
可能分别消费参数化点和已求值点，因此不能在 wire 阶段合并。

```python
_recipe_contract(
    "two_moving_points_path_reduction",
    condition_reads=(_condition("path_minimum_target"),),
    slot_writes=(_slot("transformation", "PathTransformation"),),
    dependency_policy="context_closure",
)
```

### 6.3 不应使用 `context_closure` 的情况

不要因为以下原因使用它：

- capability 是 Macro；
- 输入数量多；
- output type 是 Point 或 Expression；
- binding 实现困难；
- 希望 compiler 可以随意扫描 Context；
- 想绕过缺失 arg 校验。

`context_closure` 只改变**调用等价判断的时机**，不放宽 read-closed，不允许全局猜测。

## 7. Recipe / Macro 创建规范

### 7.1 RecipeExecutionSpec 是内部调用图真相源

Recipe 必须通过 `RecipeExecutionSpec` 声明：

- `method_sequence`；
- `execution_strategy`；
- `intermediate_wiring`；
- `creates`；
- `output_aliases`。

MacroSpec 从 execution 和 contract 投影，不另写一份 returns。

### 7.2 RecipeOutputAliasSpec

每个对外 return 必须声明：

```text
output_key
runtime_type
semantic_role
state_kind
required / cardinality
identity_policy / identity_arg
write_mode
description（必要时）
```

内部辅助点、候选端点和题面目标点必须使用不同 semantic role。LLM 不得把内部 Point
return 绑定成任意 Point answer。

### 7.3 Macro 的纯度与共享

Macro 的 `is_pure/shareable` 应从以下事实派生：

- 所有内部 Function 都是 pure；
- 不创建外部实体；
- 不写 Condition；
- 不产生不可共享副作用；
- transition 的对象身份和源版本明确。

不要维护“可共享 recipe id 白名单”。

## 8. 对象身份与状态写入

类型相同不代表对象相同。每个可见 return 都必须选择合适的 identity policy。

### 8.1 StateIdentityPolicy

| Policy | 用途 |
| --- | --- |
| `preserve_input_object` | 输出是输入对象的新状态，例如参数代入后的同一点坐标 |
| `target_object` | 输出写入显式目标对象，例如求题面点坐标 |
| `derived_role` | 输出是 capability 派生的内部角色，例如拉直线段端点 |
| `value_only` | 输出没有独立对象身份，例如普通表达式或距离值 |

禁止仅根据 produced handle 名称推断 identity。

### 8.2 StateWriteMode

| Mode | 用途 |
| --- | --- |
| `create` | 创建对象的第一个派生状态 |
| `transition` | 推进同一对象已有 StateSlot 的版本 |
| `value` | 写入非对象值 |

合法 transition 必须证明：

- object_ref 相同；
- return 声明 `transition`；
- 新调用依赖旧 producer；
- scope 可见；
- 时间顺序正确。

同名 Point 不构成 transition 证明。

## 9. 调用等价、合并与跨 Scope 共享

调用合并依赖语义证据，不依赖文本相似度或运行结果相等。

最终 resolved signature 至少考虑：

- capability id；
- resolved arg role；
- StateSlot id 和 source StateSlot versions；
- Condition id；
- object identity；
- Symbol / ParameterValue provenance；
- prior-call return identity；
- return identity policy 和 write mode；
- 显式 answer/object binding。

### 9.1 禁止用实际结果相等判断调用等价

两个调用偶然算出相同坐标或数值，不代表它们是同一个数学状态：

- 不同参数分支可能在一个样本值上相等；
- 不同对象可能具有相同坐标；
- 不同推导来源对讲解和 retry 有不同意义；
- symbolic equality 可能忽略定义域或分支条件。

Runtime 结果用于验证，不用于猜测 canonical call identity。

### 9.2 Placement

确认调用等价后，placement service 才能：

- 选择 canonical owner；
- 计算 execution scope；
- 计算每个 return 的 valid scope；
- 重写 alias CallResultRef；
- 让 Context、retry 和 explanation 使用 canonical call。

LLM 不负责把公共调用手工移动到父 scope。

## 10. 标量结果闭合

当 return 声明支持 `open_expression / closed_value` 时，FunctionalPlan 可以提供
`return_expectations`。它是 LLM 的意图标记，不是 runtime 事实。

```json
{
  "return_expectations": {
    "path_minimum_expression": "closed_value"
  }
}
```

确定性闭合遵守：

1. expectation 随 Functional projection sidecar 进入 compiler；
2. 只消费当前 call 明确读取的 ParameterValue；
3. ParameterValue 必须通过 provenance 映射到 Symbol identity；
4. closure function 从 FunctionSpec typed signature 中唯一发现；
5. 不按 method id、参数名或题目文本 dispatch；
6. runtime 最终用剩余自由符号验证实际形态。

如果没有唯一闭合函数或出现同一 Symbol 的冲突值，属于配置或 typed binding 错误，
不能静默选择。如果没有足够参数值，则保留开放结果并形成 call-level retry issue。

## 11. Binding 与编译边界

### 11.1 通用 binding 下沉到 Pack

跨 Family 重复、语义相同的 Method binding 应放入 capability pack。Family local rule
只保留真正的 override。

如果 Family local rule 与 pack rule 完全一致，应删除本地副本，避免它遮蔽后续 pack 更新。

### 11.2 Adapter primitive 应按语义注册

推荐：

```text
read_type:Point
condition role resolver
parameter value by Symbol identity
coefficients_by_symbol aggregation
point_list aggregation
```

避免：

```text
if method_id == "..."
if point_name == "F"
if "missing parabola" in error_message
```

若一个新能力需要 compiler 特殊分支，先判断能否抽成：

- FunctionSpec metadata；
- CapabilityContract；
- typed adapter primitive；
- plan transformer hook；
- Macro execution strategy。

只有无法声明化且确实属于稳定数学机制时，才增加专用 recipe compiler strategy。

## 12. Catalog 与 Prompt 规范

Functional catalog 只展示 LLM 做数学选择需要的信息：

- `capability_id`；
- `title`；
- `use_when`；
- 可选 `do_not_use_when`；
- explicit args 的短名称、接受类型、cardinality；
- public returns 的角色、类型、binding mode；
- 必要的 args/returns `desc`；
- 双形态标量的 `possible_forms`。

不得展示：

- canonical handle；
- RuntimeContext path；
- binding selector；
- StateSlot id；
- internal-only return；
- family id、problem id 或题目来源；
- StepIntent 字段。

`desc` 只在名字和类型不足以消除歧义时添加。不要把完整实现说明复制进 prompt。

## 13. 错误、确定性修复与 Retry

### 13.1 Planner configuration error

以下问题应在调用 LLM 前失败：

- exposed capability 没有 executable contract；
- Function 缺 adapter；
- Macro output alias 与内部 output 不一致；
- required auto arg 没有 resolver；
- aggregate arg 没有 aggregator；
- dual-form output 没有唯一 closure function；
- generic recipe 有 catalog 但没有 binding/compile path。

这些不是 LLM 能修复的问题。

### 13.2 确定性修复

只有在结果唯一且不改变数学路线时才自动修复，例如：

- 删除固定形态 return 上无意义的 expectation；
- 删除由 contract provider 已覆盖、且类型不兼容的冗余 optional arg；
- 补充唯一 auto arg；
- 规范化单值/数组；
- 重写 alias call；
- 合并已经由 StateSlot/provenance 证明等价的纯调用。

确定性修复必须记录 repair event，并保持幂等。

### 13.3 交给 LLM 的修复

只有数学选择或证据不足时才反馈 LLM，例如：

- capability 不适用；
- required semantic state 缺失；
- 多个合法候选无法唯一选择；
- 目标结果仍含未解决自由参数；
- answer return identity 不匹配；
- 当前调用图缺少必要数学步骤。

Repair ticket 应描述缺失的 state role/type/object identity 和被阻塞的 calls。只有 contract
preflight 得到唯一可执行 producer 时，才附带候选 capability guidance。

## 14. Anti-patterns

### Anti-pattern 1：为一张试卷新增点名判断

错误：

```python
if handle.endswith(":F"):
    ...
```

正确：从 fact type、object role、StateSlot identity 或 contract 读取。

### Anti-pattern 2：根据自然语言错误消息驱动逻辑

错误：

```python
if "parabola" in message and "missing" in message:
    ...
```

正确：diagnostic 直接输出结构化 `code / missing_state_types / object_ref`。

### Anti-pattern 3：扫描全局状态替 LLM 选择数学证据

即使全局只有一个 Expression，也不能在当前 call 未读取它时偷偷绑定。

### Anti-pattern 4：同类型即同对象

两个 Point 可能坐标相同但身份不同；两个 ParameterValue 可能属于不同 Symbol。

### Anti-pattern 5：相同结果即相同调用

调用等价必须由输入状态版本和 provenance 证明。

### Anti-pattern 6：Method、Contract、Adapter 三处复制配置

应建立投影或 adapter primitive，而不是靠人工同步。

### Anti-pattern 7：用 `context_closure` 掩盖缺失输入

`context_closure` 不是全局搜索开关，也不替代 required arg。

### Anti-pattern 8：Prompt 写固定 method 链

Prompt 应描述能力契约和修复工单，不应绑定某一题的黄金路径。

## 15. 新增 Capability 的推荐流程

### Step 1：定义数学边界

- 写清楚输入、输出、前置条件和不负责的内容；
- 判断是 Method 还是 Recipe；
- 判断是否已有更通用能力可以扩展。

### Step 2：实现 Method 或 RecipeExecutionSpec

- Method 保持无状态；
- Recipe 声明内部调用图和 output aliases；
- 不先写 prompt 或 normalizer 补丁。

### Step 3：声明 CapabilityContract

- 声明 slot/condition reads 和 writes；
- 指定 semantic roles；
- 指定 identity policy 和 write mode；
- 判断 dependency policy；
- 必要时声明 provider roles。

### Step 4：接入 Pack

- 通用能力进入 base pack；
- 机制能力进入 mechanism pack；
- Family 只保留路线偏好或真正 override。

### Step 5：完成 Function/Macro 投影 preflight

- FunctionSpec / MacroSpec 完整；
- adapter 可编译；
- catalog 只暴露 executable + complete capability；
- prompt-safe payload 不泄漏内部路径。

### Step 6：编写 typed tests

先写 synthetic、无题目字母依赖的单元测试，再跑 recorded fixture 和真实 opt-in。

### Step 7：检查 retry 和 explanation

- typed issue 能定位到 call/arg/return；
- stable graph 不包含 alias call；
- explanation 使用 canonical call graph；
- 学生步骤不会重复展示共享计算。

## 16. PR Checklist

### Architecture

- [ ] 已明确选择 Method 或 Recipe，并说明原因。
- [ ] 没有新增平行的 FunctionSpec/MacroSpec 手写配置。
- [ ] 通用 binding 位于 pack/common rule，而不是复制到多个 Family。
- [ ] 没有题号、problem id、固定点名或 expected answer 硬编码。
- [ ] 没有通过 strategy/reason/description 或错误文本驱动执行逻辑。

### Inputs

- [ ] 每个输入都有稳定 semantic role 和 runtime type。
- [ ] required / optional / auto 边界明确。
- [ ] auto arg 有唯一 deterministic resolver。
- [ ] aggregate arg 有注册 aggregator。
- [ ] binding 满足 read-closed，没有全局状态偷读。
- [ ] `context_closure` 的使用满足第 6 节全部标准；否则保持 `explicit_args`。
- [ ] provider role 只通过 `provides_semantic_roles` 声明，不靠名字猜测。

### Outputs

- [ ] 每个 public return 有唯一 semantic role。
- [ ] output type 可由 Method/Recipe spec 唯一确定。
- [ ] identity policy 正确。
- [ ] write mode 正确。
- [ ] transition 有来源版本和依赖证明。
- [ ] internal Point 不会被绑定成题面 Point answer。
- [ ] 双形态标量声明了 possible forms 和说明。

### Sharing and Scope

- [ ] 纯度由 Method/Recipe 结构派生，不是 capability id 白名单。
- [ ] 等价签名包含 StateSlot versions、identity 和 provenance。
- [ ] 不通过 runtime 结果相等合并调用。
- [ ] sibling scope 的共享经过 LCA 和输入可见性检查。
- [ ] alias calls 不进入 stable graph、retry 或学生步骤。

### Catalog and Retry

- [ ] `use_when` 非空且描述数学目标。
- [ ] 稳定误用已用泛化 `do_not_use_when` 说明。
- [ ] catalog 不暴露 handle、runtime path、selector 或内部 return。
- [ ] 配置错误在调用 LLM 前失败。
- [ ] deterministic repair 有事件记录且幂等。
- [ ] LLM retry ticket 不包含 fixed method chain。

### Tests

- [ ] Method runtime 正常、边界和多解/欠定测试。
- [ ] FunctionSpec / MacroSpec JSON serializable。
- [ ] Contract 与 execution outputs 一致。
- [ ] Adapter 成功与 typed failure 测试。
- [ ] scope visibility 和 identity 测试。
- [ ] 应合并与不应合并的调用测试。
- [ ] `context_closure` 至少覆盖两个不同 StateSlot 版本。
- [ ] open/closed result form 测试。
- [ ] finalizer / elaborator 幂等。
- [ ] recorded fixtures 回归。
- [ ] 真实 opt-in 不出现 configuration error。

## 17. 推荐验证命令

根据改动范围选择测试，最低建议：

```bash
cd server
uv run pytest \
  tests/solver/test_family_spec.py \
  tests/solver/test_strategy_planner_function_specs.py \
  tests/solver/test_strategy_planner_macro_specs.py \
  tests/solver/test_strategy_planner_functional_plan.py -q

uv run pytest tests/solver -q
git diff --check
```

真实 DeepSeek opt-in 用于检验 prompt 和真实输出分布，不替代 synthetic contract tests。

## 18. 当前迁移状态

- FunctionalPlan 仍通过 canonical StepIntent projection 接入现有 runtime。
- FunctionSpec 和 MacroSpec 是 typed facade，runtime 最终仍执行 MethodInvocation。
- Legacy StepIntent binding/normalizer 仍保留兼容，但新增 Functional capability 不应依赖
  新的文本启发式补丁。
- 当前只有 `two_moving_points_path_reduction` 使用 `context_closure`。新增声明应经过
  本文第 6 节和 PR Checklist 审核。
- Runtime 结果用于执行验证、自由符号检查和 answer verification，不用于调用等价判断。

随着 FunctionalPlan 成为唯一链路，可以逐步删除 legacy binding fallback；但在删除前，
Function/Macro contract、adapter、recorded fixture 和真实 opt-in 必须先达到行为等价。
