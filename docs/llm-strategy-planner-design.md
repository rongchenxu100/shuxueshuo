# LLM Strategy Planner 当前架构

## Summary

Strategy Planner 是 Method Solver 的 LLM 编排层。LLM 不输出 runtime path、
method 参数或可执行程序；它只输出按 scope 分组的 `StepIntent`。代码层负责校验
canonical handle、选择 recipe/method、绑定输入、试执行、收集答案和生成 repair
feedback。

当前真实链路：

```text
Canonical ProblemIR
  -> RuntimeProjection.to_llm_problem_payload()
  -> StrategyPayloadBuilder
       ProblemIR + FamilySpec + method_catalog + recipe_catalog
       + naming_conventions + few-shot + previous_attempts + schema
  -> StrategyPlanner(recorded/deepseek)
  -> StepIntentValidator
  -> HandleResolver
  -> StepIntentNormalizer
  -> StepIntentCandidateResolver
  -> RecipeTrialExecutor
  -> PlannerOutput
  -> RuntimeOrchestrator / InvocationExecutor / ResultBuilder
  -> SolverResult
```

## Prompt 输入

Strategy prompt 只包含 LLM 可安全读取的语义信息：

- canonical ProblemIR projection：`problem_id / title / original_text / scopes /
  entities / facts / question_goals`。
- `family_spec`：`family_id / common_goal_types / strategy_principles / method_ids`。
- `method_catalog`：family 暴露的 method 能力摘要。
- `recipe_catalog`：family 暴露的标准 executable action。
- `naming_conventions`：StepIntent handle 命名规则卡片。
- `few_shot_examples`：从 `internal/few-shots/` 选择的 verified executable StepIntent 示例，或 family fallback mock 示例。
- `previous_attempts`：上一轮 effective draft、accepted prefix、diagnostic、planner insights、repair summary。
- StepIntent JSON schema。

Prompt 不包含：

- runtime `ContextPath`、`ctx_N`、`visible_paths`、`planning_signals`；
- expected answers；
- method input slot schema；
- raw DeepSeek response；
- deterministic planner template。

## StepIntent 契约

LLM 输出：

```json
{
  "scopes": [
    {
      "scope_id": "ii",
      "label": "第（Ⅱ）问",
      "steps": [
        {
          "step_id": "derive_example",
          "goal_type": "derive_parameter",
          "target": "answer:ii.b",
          "strategy": "说明为什么做这一步",
          "reads": ["fact:ii:path_minimum_expression"],
          "creates": [],
          "produces": [
            {
              "handle": "answer:ii.b",
              "valid_scope": "ii",
              "description": "参数 b 的值",
              "output_type": "ParameterValue"
            }
          ],
          "reason": "简短推导理由",
          "recipe_hint": "parameter_from_expression_value"
        }
      ]
    }
  ]
}
```

关键规则：

- `reads` 必须复制当前题 ProblemIR、前序 `creates/produces` 或 answer handles。
- `creates` 只用于解题中新建的 derived entity。
- `produces` 是 StepIntent 数据流输出，必须能被 selected recipe/method contract 支撑。
- `recipe_hint` 仍是字段名，但可以指向 recipe id 或 method id。LLM 应优先填 recipe id，其次 method id；无匹配时才可为 `null`。
- 每个 step 应是 Method Solver 可执行最小颗粒度，不是网页讲解粒度。
- `valid_scope` 表示结论本身成立范围，不是当前 step 所在范围。

## 校验与归一化

`StepIntentValidator` 负责结构和安全：

- schema；
- forbidden legacy fields；
- canonical handle 存在性和可见性；
- answer goal 覆盖；
- `output_type` 与 answer value type 一致性；
- 重复 fact / invalid valid_scope / utility symbolic coefficients 等策略边界。

`HandleResolver` 只做保守 canonicalization：

- namespace alias，例如 `facts:` -> `fact:`；
- 已登记 handle alias；
- 唯一可见父级 scope 修正；
- exact-name fact-as-entity 修正。

`StepIntentNormalizer` 只做结构上确定的 rewrite：

- utility fact alias 合并到真实 typed output；
- candidate point facts 合并；
- duplicate exact `creates` 删除并改为 reads；
- recipe 内部 method 序列折叠；
- output type alias 修正；
- safe handle rewrites 传播到后续 reads。

Normalizer 不补核心数学步骤。

## 候选解析与执行

`StepIntentCandidateResolver` 使用以下信号选择 candidate capability：

- `recipe_hint`；
- `goal_type`；
- `produces[].output_type`；
- target / answer value type；
- reads signature；
- recipe priority；
- capability applicability rules。

`RecipeTrialExecutor` 按 step 顺序编译和 dry-run：

1. selected capability -> method/recipe compiler；
2. `MethodBindingRuleRegistry` 绑定 input slots；
3. `EntityStateResolver` 补唯一可见 entity state；
4. `PrepInvocationBuilder` 执行声明式 prep；
5. recipe compiler 创建 declarations、wiring、promote outputs；
6. fresh `RuntimeContext` dry-run prefix；
7. checks 全通过才加入 accepted prefix。

如果某步失败，diagnostic 保留：

- accepted prefix；
- applied fills；
- planner insights；
- preflight issues；
- first blocker；
- skipped steps；
- candidate errors。

## 代码补位边界

代码可以吸收确定性结构偏差：

- entity handle -> 唯一可见 typed state；
- registered alias / parent-scope canonicalization；
- companion outputs 注册；
- method prep invocation；
- recipe internal sequence folding；
- structured output-key mapping。

代码不能吸收：

- 未产生的核心数学结论；
- sibling scope 偷读；
- 拼写错误或开放式 fuzzy match；
- 从 `strategy/reason/description` 抽数值；
- 不属于 selected capability 的数学路线替换。

更详细规则见 [strategy-planner-code-fill-policy.md](strategy-planner-code-fill-policy.md)。

## Repair Loop

DeepSeek loop 是无真实 chat history 的 fresh prompt。状态全部通过
`previous_attempts` 传递。

失败后写入：

- `raw_draft` / `effective_draft`；
- `execution_diagnostic`；
- `repair_summary`；
- `accepted_prefix`；
- `planner_state`；
- `current_blocker`；
- `already_handled`；
- `next_actions`；
- `do_not`；
- `warnings`。

LLM 下一轮仍输出完整 StepIntent JSON。系统会用上一轮 accepted prefix patch
覆盖新 draft 的已验证前缀，避免后续 retry 漂移破坏前面已通过步骤。

Repair guidance 的归属：

- method 级提示写在 method Python `SPEC.repair_hints`；
- recipe 级提示写在 recipe execution metadata；
- binding selector 提示跟 selector/binding rule；
- `RepairFeedbackBuilder` 只负责收集、排序、去重、安全过滤。

## Planner Insights

某些 method/recipe 执行后会揭示 LLM 不应预猜的结构角色，例如：

- `PathTransformation` 的 moving point / fixed points / transformed path；
- 将军饮马 recipe 的最短线段端点；
- candidate selection 的 selected point；
- 参数求解的可复用 parameter value。

这些信息通过 planner-visible insight 放入 `previous_attempts`，帮助下一轮继续规划。
Insight 只使用 canonical handle 和 output type，不包含 runtime path、traceback 或 expected answer。

## Few-shot

Dynamic few-shot 从 `internal/few-shots/*.few-shot.json` 读取 verified executable
StepIntent 示例。

当前 V1：

- 同 family 过滤；
- 按 `retrieval.goal_types` 重叠度排序；
- `top_k=1`；
- 生产允许同题命中；
- 测试可排除当前题；
- 无同 family 示例时使用 family fallback mock 示例。

详见 [dynamic-few-shot-strategy-plan.md](dynamic-few-shot-strategy-plan.md)。

## 当前 Golden Coverage

当前 Strategy Planner recorded/DeepSeek 链路已覆盖：

- 南开一模 25：`QuadraticPathMinimumSolver`
- 河西一模 25：`QuadraticWeightedPathMinimumSolver`
- 西青一模 25：`QuadraticWeightedPathMinimumSolver`
- 和平一模 25：`QuadraticEqualLengthRayPathMinimumSolver`
- 和平二模 25：`QuadraticSquareReflectionPathMinimumSolver`

真实 DeepSeek opt-in 测试默认不在普通回归中访问网络；recorded Strategy E2E
用于 CI 和本地稳定回归。

## Future Design

- Capability Pack：把通用 quadratic/coordinate/parameter method 从 family 中上提到 base packs，把几何机制保留为 mechanism packs。
- Gap/Fallback：family 未命中或 method/binding 缺失时，生成 unverified fallback 与结构化 gap report。
- ExplanationBuilder：把 method/recipe 粒度 execution trace 合并成学生可理解讲解步骤和图形/动画意图。
- Better retrieval：few-shot V1 只用 goal types；后续可基于 `original_text` 加向量检索，但不能把 expected answer 或 runtime path 混入 prompt。
