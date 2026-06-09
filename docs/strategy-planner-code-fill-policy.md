# Strategy Planner 代码补位策略

## Summary

Strategy Planner 的 StepIntent 应尽量像解题老师一样表达“我在用哪些对象和条件”，而不是像程序员一样枚举所有 method 需要的底层 fact。LLM 可以在 `reads` 中写实体 handle，例如 `point:problem:B`、`function:problem:parabola`、`segment:ii:BC`；代码层负责在已知题设 fact 和前序 step 产物中，补齐当前 method 真正需要的坐标、表达式、长度、方程、角关系等 runtime fact。

补位的目标是降低 LLM 的查表负担，同时保持 Method Solver 的可验证边界：代码只能补“已经存在且唯一可见”的 fact，不能替 LLM 发明新的数学推导。

## Key Principles

- **LLM 读实体，代码找状态**：LLM 可以只读 `point:problem:B`，若当前 method 需要 `Point` 坐标，代码可查找唯一可见的 `fact:*:B_coordinate` 或已注册的 Point binding。
- **只补已存在事实**：补位来源必须是 canonical ProblemIR 题设 fact、前序 step 的 `produces`、或 runtime method 已注册 companion output。不能从 `strategy/reason/description` 中抽取数值。
- **scope 可见性优先**：补位 fact 必须对当前 step 的 `scope_id` 可见；允许父级到子级，不允许 sibling 互读。
- **唯一性是硬门槛**：同一实体、同一所需 runtime 类型若有多个可见候选，代码不得猜测，应返回结构化错误让 LLM repair。
- **capability-aware**：只为 selected recipe/method 实际 input slot 补位。LLM 在 `reads` 中多写但该 method 不需要的 fact，不应触发 `valid_scope` 或类型失败。
- **补位不等于补步骤**：如果缺少核心数学结论，例如还没有求出 B 坐标、还没有路径最小值表达式、还没有等角事实，代码不能自动增加推导 step，只能反馈缺失能力。
- **补位不等于模糊纠错**：LLM 写错 entity/fact handle 拼写时，代码只能做确定性的 canonicalization；不能按编辑距离、中文语义、点名相似度或题目上下文猜测它“可能想写谁”。

## Handle 拼写错误与 Canonicalization 策略

LLM 的 handle 错误分两类处理：

1. **确定性可修正**：可以由代码自动 rewrite，并记录 `HandleResolutionReport` 或 normalizer action。
2. **非确定性拼写错误**：必须失败并进入 repair loop，错误消息给出可用候选。

这里要区分“缩写”和“拼错”：

- **缩写** 是系统可枚举的 alias，例如 `facts:` 写成复数、`seg:` 表示 `segment:`、或未来由 ProblemIR / FamilySpec 显式登记的 `min_expr -> path_minimum_expression`。
- **拼错** 是开放式误写，例如 `minmum_expr`、`parbola_expr`、`point:problem:Bee`。这类不能靠编辑距离猜。

允许自动修正的范围很窄：

| 场景 | 是否自动修正 | 说明 |
| --- | --- | --- |
| namespace 缩写，例如 `facts:ii:path_minimum_expression -> fact:ii:path_minimum_expression`、`seg:ii:BC -> segment:ii:BC` | 可以 | 只在 reads 阶段试探；修正后必须命中已知 handle 或唯一可见父级 handle |
| 已登记的语义缩写 alias，例如 `fact:ii:min_expr -> fact:ii:path_minimum_expression` | 可以 | alias 必须来自 ProblemIR projection / FamilySpec / code-generated alias 表；同一个 alias 指向多个 canonical handle 时删除 alias 并报错 |
| `reads` 中把父级实体写成当前 scope，例如 `point:ii:D`，而唯一可见 canonical handle 是 `point:problem:D` | 可以 | 只允许修正到可见父级；不能跨 sibling；同名多候选时报错 |
| `reads` 中使用已注册 answer alias / projection alias | 可以 | 例如 projection 明确记录的 `answer:*` 别名；来源必须是代码生成的 alias 表 |
| 同一步同时 produced 真实 Parabola 和 `parabola_coefficients` 这类 utility alias | 可以 | 由 normalizer 把 utility fact rewrite 到真实 Parabola handle；不是按自然语言猜 |
| `reads` 中实体 handle 正确，但缺少实体状态 fact | 可以补位 | 这是 EntityStateResolver 的职责，例如 `point:problem:B` -> `fact:i:B_coordinate` |
| `reads` 中名字拼错，例如 `point:problem:Bee`、`fact:ii:minmum_expr` | 不修正 | 返回 `unknown_read_handle`，附近似候选只作为 LLM repair 提示；除非它命中显式 alias 表 |
| `creates` / `produces` / `answer` handle 写错 | 默认不修正 | 输出端会改变数据流，除非 normalizer 有明确的结构化规则，否则失败 |
| `answer:*` 写错或 scope 写错 | 不修正 | 最终答案目标必须原样来自 `question_goals[].handle` |
| sibling scope 错写，例如 `fact:i_1:*` 被 `i_2` 使用 | 不修正 | 即使名称相同，也不能跨 sibling 自动借用 |

因此，当前策略是：

- `HandleResolver` 只做 **reads 里的保守 scope canonicalization**，例如“当前 scope 误写为唯一可见父级 scope”。
- `HandleResolver` 可以做 **已登记缩写 alias canonicalization**，例如 namespace 缩写或 ProblemIR/FamilySpec 生成的唯一 alias。
- `StepIntentNormalizer` 只做 **结构化 alias rewrite**，例如 utility fact 合并到同 step 的真实 typed output。
- `EntityStateResolver` 只做 **实体状态补位**，前提是实体 handle 本身已可识别，且补位目标唯一可见。
- 其它拼写错误都进入 `previous_attempts`，让 LLM 按候选修正完整 StepIntent。

实现上，缩写修正也要遵守三条规则：

1. 只修正 `reads`，不修正 `answer:*` 目标，也不默认修正 `creates/produces`。
2. alias 来源必须是显式注册表，不允许运行时按 Levenshtein 距离或自然语言相似度生成。
3. alias 展开后仍要通过 canonical handle 存在性、scope 可见性和唯一性校验。

错误反馈应使用 handle 语言，例如：

```json
{
  "code": "unknown_read_handle",
  "step_id": "derive_minimum",
  "handle": "fact:ii:minmum_expr",
  "suggestions": ["fact:ii:path_minimum_expression", "fact:ii:path_minimum_target"],
  "instruction": "请从当前题 ProblemIR 或前序 produces 中原样复制 handle，不要自造或改写拼写。"
}
```

这条边界很重要：代码可以吸收 LLM 的“少写状态 fact”，但不能吸收“写错对象”。写错对象会改变数学语义，必须显式 repair。

## Entity 到 Fact 的补位类型

首版可以覆盖这些稳定映射：

| Entity / Handle | Method 需要 | 可补位 fact / binding |
| --- | --- | --- |
| `point:<scope>:P` | `Point` | `fact:*:P_coordinate*`，或已注册 Point binding |
| `point:<scope>:P` | `PointRef` | 原始 PointRef path；若已经是 Point，应报重复计算，不能当 target 重算 |
| `function:<scope>:parabola` | `Parabola` | `answer:*parabola`、`fact:*:parabola_expression*`、已注册 Parabola binding |
| `symbol:<scope>:m` | `ParameterValue` | `fact:*:m_value`、`answer:*` 且 value type 为 `ParameterValue` |
| `segment:<scope>:AB` | `Condition` / length relation | 可见的 segment membership / length / relation fact |
| angle/path semantic fact | Method-specific input | 已注册 `AngleEquality`、`MinimumExpression`、`PathTransformation` 等 typed fact |

补位匹配应优先使用结构化类型：`output_type`、ProblemIR `fact.type`、QuestionGoal `value_type`、runtime binding `value_type`。自然语言 description 只能作为低置信度 fallback，不能覆盖结构化命中。

## 其它代码补位策略

除了 handle canonicalization 和 EntityStateResolver，当前 Strategy Planner 还存在几层“代码吸收 LLM 结构偏差”的补位。它们都必须遵守同一条边界：只处理结构上可确定的缺口，不替 LLM 发明核心数学步骤。

### Draft 数据流修正

`HandleResolver` 负责 draft 级数据流维护：

- 前序 produced handle 被改名后，自动 rewrite 后续 `reads / target / produces`。
- LLM 把题设已有 entity 误放进 `creates[]` 时，移动到 `reads[]`，避免覆盖题设实体。
- produced fact 的 `valid_scope` 过宽时，根据实际 reads 收窄到安全 scope，防止子问条件产物被当成公共结论。

这些修正不改变数学内容，只修正 StepIntent 的数据流边界。

### StepIntent 结构归一化

`StepIntentNormalizer` 负责可确定的 step shape rewrite：

- `quadratic_from_constraints` 同时产出 `parabola_coefficients / coefficients_expr` 这类 utility fact 时，归一化到真实 `Parabola` output。
- 同一步多个候选点坐标 fact 可合并成一个 `PointList` 候选 fact。
- 泛化点坐标 fact 如果同 step 有明确 Point answer，可归一到真实目标点。
- 已知点坐标 utility step 可删除，并把后续 reads 改为直接读已有 point handle。
- 冗余的“最后再求参数 answer step”可合并到前序已能产出参数的 recipe。

Normalizer 处理的是“LLM 输出形状不适合执行，但结构语义唯一”的情况；不能把缺失的核心推导 step 自动补出来。

### Capability 选择兜底

`StepIntentCandidateResolver` 在 LLM `recipe_hint=null` 或 hint 不完整时，可以用结构化信号选择能力：

- `ParameterValue + length_squared reads` 可匹配参数由长度条件求值的 method。
- `ParameterValue + MinimumExpression + 给定最小值 reads` 可匹配参数由表达式取值求值的 method。
- 通过 `goal_type / produced output_type / reads signature` 查找唯一 recipe/method 候选。
- `valid_scope` 校验应 capability-aware：selected capability 不使用的 child-only reads 只记 warning，不阻断。
- 宽泛 `Point` output 不能单独触发点类 method，必须满足对应 method 的最小 reads signature。

这个兜底只是选择可试执行能力；最终仍要经过 binding 和 dry-run 验证。

### Binding 语义角色推断

`MethodBindingRuleRegistry` 负责把 StepIntent 的 semantic handles 转成 method input slots：

- 角和、等角、直线交抛物线、等长射线、路径转化等 method，通过 canonical fact payload、reads、target、creates 推断角色。
- `read_type:*` selector 可从显式 reads、local outputs、可见 runtime bindings 中读取指定类型。
- expansion selector 可补可选输入，例如已知系数、参数值、曲线点、交点参数等。

这层不决定数学路线，只服务 selected capability 的参数绑定。

### Recipe / Method 编译补位

`RecipeTrialExecutor`、`PrepInvocationBuilder` 和 recipe compiler 可以补执行层结构：

- 根据 FamilySpec 的 prep rule 自动插入前置 invocation，例如缺少可读 Parabola/Coefficients 时先准备。
- recipe 自动创建必要 declaration / auxiliary point，不要求 LLM 写 runtime path。
- 多 method recipe 自动 wiring 中间输出，例如候选生成到筛选、几何转化到最值计算。
- method companion outputs 自动 promote/register，供后续 step 读取。

这类补位必须来自 FamilySpec / MethodSpec / RecipeExecutionSpec 的声明，不允许按题号、problem_id 或固定点名特判。

### Runtime BindingIndex 桥接

`CanonicalRuntimeBindingIndex` 负责 canonical handle 到 runtime path 的桥接：

- canonical ProblemIR 的 entities/facts 自动注册到 runtime path。
- `answer:*` 自动映射到 QuestionGoal target path。
- method 执行后的 produced fact / answer 注册为后续可读 binding。
- Point answer 可注册对应 point handle，方便后续按实体读。

这层只建立可读索引，不做候选搜索或数学推导。

## Resolver Flow

建议把补位放在 `StepIntentCandidateResolver -> RecipeTrialExecutor` 之间的 binding 阶段，而不是 prompt 或 validator 阶段：

1. `StepIntentValidator` 只检查 handle 是否规范、scope 是否存在、旧字段是否禁用。
2. `StepIntentNormalizer` 做确定性 handle rewrite 和无害 utility step 合并/删除。
3. `StepIntentCandidateResolver` 选出 recipe/method capability。
4. `MethodBindingRuleRegistry` 根据 selected capability 的 input slots 做补位：
   - 先查 step 显式 reads。
   - 再查当前 BindingIndex 中同实体、同类型、唯一可见的 produced fact。
   - 再查 method companion output 或 local prep output。
   - 若仍缺失，返回短错误码，例如 `missing_required_runtime_fact: point_coordinate:B`。
5. `RecipeTrialExecutor` 用 dry-run 验证补位是否真的可执行。

## Safe Fill Examples

### 点坐标补位

LLM 输出：

```json
{
  "step_id": "derive_E_point",
  "recipe_hint": "line_parabola_second_intersection_point",
  "reads": ["fact:i:parabola_expression", "point:problem:B", "point:i_2:F"]
}
```

若前序已经 produced `fact:i:B_coordinate`，且它对 `i_2` 唯一可见，代码可把 `point:problem:B` 绑定为 `fact:i:B_coordinate` 的 Point path。

### 抛物线表达式补位

LLM 输出：

```json
{
  "step_id": "derive_B_coordinate",
  "recipe_hint": "quadratic_x_axis_intercept_point",
  "reads": ["function:problem:parabola", "point:problem:B"]
}
```

若当前/父级已经有唯一可见 `answer:i_1_parabola` 或 `fact:i:parabola_expression`，代码可绑定该 Parabola。若没有，才允许 PrepInvocationBuilder 根据可见约束临时准备；若约束不足，应失败。

## Unsafe Fill Examples

- 只有 `point:problem:B`，但没有任何 `B_coordinate` 或可求 B 的 accepted 前序 step，不能自动求 B。
- 当前 scope 为 `i_2`，只存在 sibling `i_1` 的 `fact:i_1:B_coordinate`，不能跨 sibling 补位。
- 同时存在 `fact:i:B_coordinate` 和 `fact:ii:B_coordinate_expr` 且都可见/语义冲突，不能猜哪一个，必须让 LLM 显式 reads。
- LLM 在 `reason` 中写了 “B=(3,0)”，但没有 produced fact，代码不能读取该数值。

## Error Feedback

补位失败时，错误消息应使用 handle 语言，而不是 runtime path：

```json
{
  "code": "missing_required_runtime_fact",
  "step_id": "derive_E_point",
  "input_name": "line_p1",
  "entity_handle": "point:problem:B",
  "required_type": "Point",
  "suggestion": "请先产生 fact:<visible_scope>:B_coordinate，或在 reads 中引用已有 B_coordinate fact。"
}
```

若是歧义：

```json
{
  "code": "ambiguous_runtime_fact",
  "entity_handle": "point:problem:B",
  "required_type": "Point",
  "candidates": ["fact:i:B_coordinate", "fact:ii:B_coordinate_expr"]
}
```

## Implementation Refactor Direction

当前代码已经按职责拆成多个模块，但补位逻辑仍可继续抽象成更稳定的接口：

- `CanonicalHandleAliasResolver`：统一 handle alias / scope canonicalization；禁止 fuzzy matching。
- `EntityStateResolver`：统一 `entity handle + required runtime type -> unique visible state`。
- `NormalizationRule`：保留 rule list 调度，后续新增结构归一化只加 rule，不改主流程。
- `CapabilityApplicabilityRule`：把 `StepIntentCandidateResolver` 中的 reads signature 判断抽成可注册规则，避免继续堆 method/recipe 分支。
- `BindingSelectorRegistry`：已承担 method input selector 分发；后续新增 selector 只注册 callable。
- `PrepInvocationBuilder`：继续从 FamilySpec 读 prep rule，避免在 recipe compiler 中写 method_id 特判。
- `RecipeCompilerStrategy`：recipe execution strategy 继续通过注册表分发，避免 `_compile_recipe` 继续增长。

不建议把所有补位合并成一个“大 resolver”。原因是每层输入/输出和安全边界不同：

| 层 | 输入 | 输出 | 可以做 | 不能做 |
| --- | --- | --- | --- | --- |
| AliasResolver | handle 字符串 | canonical handle | 缩写、alias、父级 scope 修正 | 状态补位、数学推导 |
| Normalizer | StepIntentDraft | 改写后的 draft | 结构化 utility rewrite | 猜 method 参数 |
| CandidateResolver | StepIntent + capabilities | 候选能力 | null hint 兜底、适用性检查 | 绕过 dry-run |
| BindingRules / EntityStateResolver | selected capability + reads | runtime input paths | 唯一可见 fact/binding 补位 | 跨 sibling、补核心 step |
| RecipeCompiler | accepted step | PlannerOutput fragment | prep invocation、declaration、wiring | 改变 LLM 数学路线 |

重构目标应是“各层接口更清楚、规则可注册”，不是把所有容错都集中到一个地方。

## Test Plan

- 单元测试覆盖：显式 reads、唯一可见补位、父级可见、sibling 不可见、多候选歧义、结构化类型优先、description fallback 不覆盖结构化类型。
- 固定 attempt 测试覆盖：LLM 漏读 `B_coordinate` 时，line-parabola / angle-equality method 都能补位。
- recorded E2E 覆盖：补位发生后仍由 RuntimeOrchestrator 执行并通过 expected answers。
- 真实 DeepSeek opt-in：观察 retry 数是否减少，但不把 attempt 数作为硬门槛。

## Assumptions

- canonical Entity/Fact handle 命名规范是补位的基础。
- 补位逻辑属于执行层确定性增强，不改变 StepIntent schema。
- 随着题型扩展，应优先新增结构化 fact type 和 method binding selector，而不是依赖自然语言关键词。
