# LLM Strategy Planner 设计方案

## Summary

新的 LLM Planner 不再让模型输出可执行程序。LLM 只负责像解题老师一样读题、理解题型策略、拆出解题步骤意图；代码层负责把这些意图转成可执行 `PlannerOutput / StepPlan`：

```text
Canonical ProblemIR -> RuntimeProjection LLM payload
  + FamilySpec + method_catalog + recipe_catalog + few-shot + previous_attempts
  -> DeepSeek / Fake StrategyPlanner
  -> scoped StepIntent[]
  -> StepIntentValidator + HandleResolver
  -> StepIntentCandidateResolver
  -> RecipeTrialExecutor
  -> PlannerOutput
  -> RuntimeOrchestrator / InvocationExecutor / ResultBuilder
```

核心原则：

- LLM 负责“下一步要做什么、为什么这么做”。
- 代码负责“recipe/method 是否可执行、参数怎么绑定、scope 是否可见、执行是否通过”。
- 不确定性通过代码并发试错和 check/rank 消化，而不是让 LLM 一次性写对 `ContextPath`、`promote_outputs` 和跨步骤数据流。
- 找不到 family/method/binding 时，不伪造成功；记录 gap，后续由 fallback/gap 系统兜底和离线补齐。
- `reads / creates / produces` 中的对象引用必须使用统一 canonical handle，命名规范见 [entity-fact-handle-naming.md](entity-fact-handle-naming.md)。
- StepIntent schema 直接使用 `reads / creates / produces`：解题过程被建模为读取已有 Entity/Fact、产生新 Fact、必要时创建 derived Entity 的事实图生长过程。

## 当前实现状态

截至 2026-06-05，Strategy Planner 已完成南开 25、河西 25 的 recorded
生产链路接入，并保留真实 DeepSeek opt-in 竖切验证：

- Prompt 输入已经收敛为 canonical ProblemIR 经 `RuntimeProjection` 生成的
  LLM payload + FamilySpec + method_catalog + recipe_catalog + few-shot +
  previous_attempts + StepIntent schema。
- Prompt 不再输入 `visible_paths / context_refs / slot_options / planning_signals / ContextPath`。
- LLM 输出使用按 question/subquestion scope 分组的 `StepIntent`，字段为 `recipe_hint / reads / creates / produces / valid_scope`。
- `RecipeTrialExecutor` 已能把固定 StepIntent fixture 和真实 DeepSeek loop 的最终输出编译为 `PlannerOutput`，再通过现有 runtime 算出南开、河西答案。
- `StrategyPlanner` 已接入 `RuntimeOrchestrator` / CLI；默认生产模式为
  `--planner strategy --llm-provider recorded`，deterministic 仅作为显式 debug/oracle。

最近一次真实联调结果：

```text
RUN_LLM_INTEGRATION=1 RUN_DEEPSEEK_STRATEGY_PLANNER=1 \
  uv run pytest tests/solver/test_deepseek_strategy_planner_nankai.py -q -s

7 passed
attempts=3/3
final_failures=[]
solved_result=internal/solver-runs/strategy-planner-deepseek-nankai/solved-result.json
```

## 为什么重做

旧 LLM planner 的问题不是 prompt 不够细，而是抽象层级错了。它要求 LLM 同时完成：

- 读题和拆步骤。
- 选择 method。
- 查 RuntimeContext path。
- 校验 scope 可见性。
- 管理 step output / promote / depends_on。
- 遵守复杂 JSON schema。

其中读题和拆步骤是 LLM 擅长的，后几项是代码擅长的。新方案把 LLM 输出空间压缩到 `StepIntent[]`，让执行细节全部回到确定性代码。

## 输入与输出边界

### LLM 输入

LLM StrategyPlanner 的 prompt 应包含：

- canonical ProblemIR 经 `RuntimeProjection.to_llm_problem_payload()` 生成的
  LLM payload：包含 `original_text / scopes / entities / facts / question_goals`，
  这是 LLM 读题和引用 handle 的唯一题目事实源。
- 题型策略：`SolverFamilySpec` 的 `common_goal_types / strategy_principles / method_ids / step_recipes`。
- Method Catalog：由当前 family 的 `method_ids` 全量生成的能力摘要，不给完整 slot 绑定表。
- Recipe Catalog：由当前 family 的 `step_recipes` 全量生成的标准解题动作菜单。
- Few-shot：同 family 的“老师式步骤意图”示例，不包含当前题完整答案式计划。
- previous errors：上一轮失败的结构化摘要，用于修正步骤意图。

LLM 输入不应包含：

- expected answers。
- `$problem.* / $question.*` 这类真实 ContextPath。
- `ctx_N` slot candidate。
- method invocation 的精确参数组合。
- 测试 oracle。

### LLM 输出

LLM 只输出按 scope 分组的 `StepIntent[]`：

```json
{
  "scopes": [
    {
      "scope_id": "i",
      "label": "第（Ⅰ）问",
      "steps": [
        {
          "step_id": "derive_axis_point",
          "recipe_hint": "quadratic_axis_from_relation",
          "goal_type": "derive_axis_point",
          "target": "answer:i.axis_point",
          "reads": ["fact:problem:coefficient_relation", "function:problem:parabola"],
          "strategy": "由二次函数对称轴公式求 D",
          "creates": [],
          "produces": [
            {
              "handle": "fact:problem:D_coordinate_value",
              "valid_scope": "problem",
              "description": "D 的坐标由整题系数关系确定，后续各问都可读取"
            },
            {
              "handle": "answer:i.axis_point",
              "valid_scope": "i",
              "description": "第（Ⅰ）问要求输出 D 点坐标"
            }
          ],
          "reason": "题目要求先求 D，且 D 由对称轴确定。"
        }
      ]
    }
  ]
}
```

字段说明：

- `step_id`：语义化 snake_case，禁止 `step_1` 这类编号式 ID。
- `scopes[].scope_id`：步骤所属题面 scope，必须来自 RuntimeProjection 生成的 LLM payload scope tree。
- `goal_type`：如 `derive_point / derive_parabola / derive_parameter / path_reduction / minimum_value / intersection`。
- `recipe_hint`：可选。优先从 `recipe_catalog[].recipe_id` 选择，其次从 `method_catalog[].method_id` 选择，不确定时为 `null`。
- `target`：自然语言目标，不是 ContextPath。
- `reads`：这一步读取的已有 Entity / Fact handle，只能来自 canonical handle 表或前序 step 的 `creates / produces`。
- `creates`：这一步新增的 derived Entity，例如辅助点、辅助线；不用于表达坐标或方程。
- `produces`：这一步新增的 Fact / answer Fact，例如坐标事实、参数值、函数解析式、最终作答目标。
- `strategy`：解题策略说明。
- `reason`：给 debug 和后续 ExplanationBuilder 用。

LLM 不允许输出：

- method invocation。
- ContextPath。
- 坐标、参数值、最终答案。
- `promote_outputs`。
- `depends_on`。
- step temp path。

## 核心组件

### 1. StrategyPayloadBuilder

职责：把 `PlannerInputs` 转成 LLM 可读 payload。

输入：

```text
PlannerInputs(
  problem_id,
  family_spec,
  question_goals,
  context_inventory,
  method_specs,
  original_text,
  previous_errors
)
```

输出：

```text
StrategyPayload
  problem_ir           # 来自 canonical ProblemIR projection
  family_spec          # 来自 SolverFamilySpec
  method_catalog       # 来自 FamilySpec.method_ids + MethodSpecRegistry 摘要
  recipe_catalog       # 来自 FamilySpec.step_recipes 摘要
  few_shot_examples
  previous_errors
  output_json_schema
```

设计要点：

- `problem_ir` 必须由 canonical ProblemIR projection 生成，不再从旁路 LLM fixture 读取。
- `method_catalog` 是能力摘要，不是完整 method schema。示例：

```text
quadratic_axis_from_relation: 由二次函数系数关系求对称轴与 x 轴交点
quadratic_from_constraints: 由已知系数、曲线点、参数值和额外方程求当前问最简抛物线；适合把 a,b,c 完全确定或化简到只剩一个上下文有用参数
midpoint_point: 由两端点求中点
```

首版可以直接用 family 的 `method_ids` 生成 catalog；后续可加入历史成功率、适用条件和反例。

### 2. StrategyPlanner

职责：调用 LLM，生成 `StepIntent[]`。

输入：`StrategyPayload`

输出：`StepIntentDraft`

首版实现：

- `FakeStrategyPlannerClient`：返回手写南开/河西 step intent，用于测试。
- `DeepSeekStrategyPlannerClient`：真实模型调用。
- `StrategyDraftValidator`：只校验 JSON 形状、字段类型、step_id 唯一、禁止裸 path/答案值。

注意：Validator 只做结构、安全和 canonical handle 校验；recipe/method 能否执行、参数如何绑定，交给 `StepIntentCandidateResolver + RecipeTrialExecutor`。

### 3. StepRecipe

很多学生视角的一步，并不等于一个底层 method。比如南开 25 中“求 N 的坐标”在教学上是一
个步骤，但 runtime 需要先列直角等腰候选点，再用第四象限和 `m>2` 筛选：

```text
right_angle_equal_length_candidates
  -> select_point_by_quadrant_constraint
```

因此 method 之上需要一层 `StepRecipe`。它不是新的计算黑盒，而是预注册的 method 编排模板：

```python
StepRecipe(
    recipe_id="construct_and_select_point",
    goal_types=("derive_point",),
    method_ids=(
        "right_angle_equal_length_candidates",
        "select_point_by_quadrant_constraint",
    ),
    internal_wiring=(
        RecipeWire(
            from_method="right_angle_equal_length_candidates",
            output="candidates",
            to_method="select_point_by_quadrant_constraint",
            input="candidates",
        ),
    ),
    description="直角等腰构造候选点，再由象限和参数约束筛选唯一点。",
)
```

边界：

- Recipe 必须预注册在 `SolverFamilySpec` 或独立 `StepRecipeRegistry` 中。
- LLM 不能输出 recipe 内部 method chain。
- Recipe 只编排 method，不做新数学计算。
- Recipe 内每个 method 仍独立经过 `PlanValidator / InvocationExecutor / checks`。
- Recipe 表达一个局部解题动作，不跨越多个大段 QuestionGoal。
- 首版 recipe method 数量建议不超过 4 个。

南开 family 首版可能需要：

- `construct_and_select_point`：构造候选点，再筛选唯一点。
- `path_reduction_and_straightening`：两动点路径降维、折线拉直、选择辅助点。

是否需要 `parameter_then_parabola` 可以后置讨论。它可能太长，容易把两个教学步骤揉在一起。

### 4. ExecutableCandidateResolver

职责：根据 `StepIntent` 混合检索 single method 和 step recipe top-k。

输入：

```text
StepIntent
SolverFamilySpec
MethodSpecRegistry
StepRecipeRegistry
previous committed outputs
```

输出：

```text
ExecutableCandidate[]
  kind: single_method | step_recipe
  method_id or recipe_id
  score
  matched_reasons
  required_inputs / exposed_inputs
  outputs / final_outputs
```

候选来源：

- `FamilySpec.method_ids` 限定首批候选池。
- `FamilySpec.recipe_ids` 或 `StepRecipeRegistry` 限定 recipe 候选池。
- `MethodSpec.solves / title / docstring / input-output types`。
- `StepRecipe.goal_types / description / method_ids / required_signals`。
- `StepIntent.goal_type / recipe_hint / strategy / target / reads / creates / produces`。
- Canonical Entity / Fact / answer handle，以及 family recipe/method 能力菜单。
- 历史成功率和失败记录。

首版排序规则：

1. `recipe_hint` 命中 recipe_id 或 method_id。
2. recipe 能覆盖完整 StepIntent 时，优先级高于只能产生中间结果的 single method。
3. candidate outputs 类型能覆盖 step target 或 question goal value_type。
4. required input 类型在当前 scope 可找到候选。
5. 当前 family 常用 candidate 优先。
6. 历史成功率高的 candidate 优先。

默认限制：

```text
executable_top_k <= 5
single_method_top_k <= 5
recipe_top_k <= 3
```

是否让 LLM 选择 method：

- 首版不让 LLM 做最终选择。
- LLM 的 `recipe_hint` 是强提示，但不是最终裁决；runtime 仍需通过 binding、checks 和答案收集验证。
- 若多个 executable trial 都成功且 rank 分完全相同，先返回 `ambiguous_executable_candidate` 结构化错误；后续再考虑受限 LLM tie-break。

找不到候选时：

1. 先把结构化错误传回下一轮 StrategyPlanner，让 LLM 尝试重新拆分 StepIntent。
2. 仍找不到，则记录 `MethodGapReport` 或 `RecipeGapReport`。
3. 若用户链路需要继续可用，交给 LLM fallback solution，返回 `status="fallback"`，不能伪装成 verified method solver 输出。

### 5. BindingCandidateResolver

职责：为某个 executable candidate 生成参数绑定候选。

输入：

```text
StepIntent
ExecutableCandidate
RuntimeContext
committed outputs
```

输出：

```text
BindingCandidate[]
  inputs: dict[input_name, ContextPath]
  output_targets: dict[output_key, target ContextPath or auto]
  internal_wiring: recipe 内部输出到输入的自动连接
  score
  matched_reasons
```

生成规则：

- 按 MethodSpec input type 过滤 canonical runtime binding index。
- 按 step scope 可见性过滤。
- 按点名、关系角色、QuestionGoal、canonical handle、StepIntent.reads 做语义匹配。
- 前序 committed outputs 可以作为输入。
- 对 `target: PointRef` 这类输入，优先匹配 StepIntent target 或 `creates / produces` 中提到的点。
- 对 optional input，先生成“缺省版本”，再生成带 optional input 的高分版本。
- 对 recipe，中间 method 的内部输入优先由 `RecipeWire` 自动连接，不暴露给 LLM，也不进入外部组合搜索。

组合剪枝：

```text
每个 input candidate <= 8
每个 executable binding combinations <= 20
每个 step total trials <= 50
```

输出路径策略：

- LLM 不生成 output path。
- BindingCandidateResolver 根据 step target、`creates` 和 `produces` 自动决定：
  - 最终答案：写到 `QuestionGoal.target_path`。
  - 已存在上下文对象：写到对应 ContextPath。
  - 中间结果：写到最近公共可见 scope 的 `outputs`。
  - 纯临时结果：只留在 step temp，不 promote。

### 6. TrialExecutor

职责：在 cloned RuntimeContext 上试跑候选 plan。

输入：

```text
StepIntent
ExecutableCandidate
BindingCandidate
current RuntimeContext
```

输出：

```text
TrialResult
  status: success | validation_failed | execution_failed | checks_failed
  step_plan
  produced_outputs
  checks
  trace_fragments
  errors
  score_features
```

执行规则：

- 每个 trial 必须使用 cloned RuntimeContext。
- trial 失败不能污染主 RuntimeContext。
- 先跑 `PlanValidator`，再跑 method。
- check failed 不是异常，但 trial 不能成为最佳候选，除非该 check 是 warning 级别。
- trial 成功后也不立即 commit，交给 ranker。
- single method trial 生成一个 invocation；recipe trial 生成一个包含多个 invocation 的 StepPlan，内部 wiring 由 recipe 决定。

并发策略：

- 同一个 step 内的 trials 可以并发。
- 不同 step 之间默认顺序执行，因为后一步依赖前一步 committed context。
- 每个 step 有总超时和 trial 数量上限。

### 7. TrialRanker

职责：从 `TrialResult[]` 中选最佳。

排序特征：

1. `PlanValidator` 通过。
2. method 执行成功。
3. required checks 全通过。
4. 输出类型匹配 StepIntent / QuestionGoal。
5. 输出 target 与 StepIntent target、`creates`、`produces` 匹配。
6. executable capability 与 StepIntent strategy 匹配。
7. 产生的 trace 与 step reason 语义接近。
8. 更少 optional assumption。
9. 更少新增 declaration。
10. 历史成功率更高。

输出：

```text
BestTrial | AmbiguousTrialError | NoValidTrialError
```

若没有可用 trial：

- 记录 `MethodGapReport` 或 `BindingGapReport`。
- 将结构化错误传回下一轮 StrategyPlanner。
- 若预算耗尽，交给 fallback/gap 系统。

### 8. CommitExecutor

职责：把最佳 trial 的结果写入主 RuntimeContext。

输入：`BestTrial`

输出：更新后的主 `RuntimeContext`

规则：

- 复用现有 `InvocationExecutor` 或新增 commit-only 路径。
- 不能直接复制 clone 中的任意状态，只能根据最佳 `StepPlan` 在主 context 上重新执行一次。
- 这样可以保证主链路仍然只经过 `PlanValidator + InvocationExecutor`。

## Orchestrator 流程

新的 LLM 模式下，`RuntimeOrchestrator` 仍然管外层 attempt：

```text
for attempt in max_attempts:
  context = ContextBuilder.build(problem)
  question_goals = extract_question_goals(problem)
  payload = StrategyPayloadBuilder.build(llm_problem_ir, family_spec, question_goals, previous_errors)
  step_intents = StrategyPlanner.plan(payload)

  for intent in step_intents:
    executable_candidates = ExecutableCandidateResolver.resolve(intent)
    planner_output = RecipeTrialExecutor.compile(intent, executable_candidates, context)
    execution = RuntimeOrchestrator.execute(context, planner_output)

  answers = ResultBuilder.build(context, execution, question_goals)
  if success: return ok
  previous_errors = structured_errors
```

注意：

- repair 是整体重新规划，不 patch 单个 step。
- 每轮 attempt 都从干净 RuntimeContext 开始。
- StepIntent 层错误用自然语言/语义字段反馈给 LLM。
- Method/binding/trial 层错误用结构化 gap 记录，尽量不把内部 ContextPath 暴露给 LLM。

## Repair Memory

下一轮 LLM 不应直接接收完整 chat history。完整历史里包含 system prompt、完整 payload、原始
LLM 输出和调试日志，token 成本高，也容易让模型被上一轮错误计划牵着走。

推荐做法：每轮重新发送当前题目的完整 prompt payload，同时附加结构化 `PlannerMemory` 摘要：

```json
{
  "previous_attempts": [
    {
      "attempt_index": 1,
      "step_count": 12,
      "previous_plan_summary": [
        {
          "step_id": "derive_axis_point",
          "goal_type": "derive_point",
          "target": "点 D",
          "status": "passed"
        },
        {
          "step_id": "derive_N",
          "goal_type": "derive_point",
          "target": "点 N",
          "status": "failed",
          "error_code": "no_valid_executable_candidate"
        }
      ],
      "failed_at": {
        "stage": "trial",
        "step_id": "derive_N",
        "message": "该步骤只表达了构造候选点，没有表达用第四象限和 m>2 筛选唯一点。"
      },
      "repair_hint": "请把 derive_N 改写成包含'列候选并筛选'的完整意图，或拆成两个连续 StepIntent。"
    }
  ]
}
```

规则：

- 不传完整 chat history。
- 不传完整 raw response，除非人工 debug。
- 可以传上一轮 `StepIntent[]` 的压缩摘要。
- 可以传 successful prefix，但只是摘要，不要求 LLM 做局部 patch。
- 每轮仍要求 LLM 重新输出完整 `StepIntent[]`。
- PlannerMemory 只用于 repair prompt，不写 `RuntimeContext`。

建议模型：

```python
PlannerAttemptMemory(
    attempt_index: int,
    raw_response: str,
    parsed_step_intents: list[StepIntent],
    accepted_steps: list[StepIntentSummary],
    failed_step: StepIntentSummary | None,
    structured_errors: list[StructuredPlannerError],
    trial_summary: list[TrialSummary],
    token_usage: dict | None,
)
```

`PlannerAttemptMemory.to_repair_payload()` 只输出安全摘要：step id、goal type、target、状态、错误码、
简短修复建议和 token usage；不输出 API key、traceback、完整 prompt 或 expected answer。

## StepIntent 示例：南开 25

下面只展示单步结构，真实 JSON 需要放在外层 `scopes[].steps[]` 中：

```json
{
  "steps": [
    {
      "step_id": "derive_axis_point",
      "goal_type": "derive_point",
      "target": "点 D",
      "reads": ["function:problem:parabola", "fact:problem:coefficient_relation"],
      "strategy": "由对称轴公式求 D",
      "recipe_hint": "quadratic_axis_from_relation",
      "creates": [],
      "produces": [
        {
          "handle": "fact:problem:D_coordinate_value",
          "valid_scope": "problem",
          "description": "由对称轴关系求出 D 的坐标"
        },
        {
          "handle": "answer:i.axis_point",
          "valid_scope": "i",
          "description": "第一问要求输出 D 点坐标"
        }
      ],
      "reason": "第（Ⅰ）问要求 D，且 D 由对称轴确定。"
    },
    {
      "step_id": "derive_part_i_parabola",
      "goal_type": "derive_parabola",
      "target": "第（Ⅰ）问抛物线",
      "reads": ["fact:i:a_value", "fact:i:c_value", "fact:problem:coefficient_relation"],
      "strategy": "代入已知系数和系数关系求解析式",
      "recipe_hint": "quadratic_from_constraints",
      "creates": [],
      "produces": [
        {
          "handle": "fact:i:parabola_equation",
          "valid_scope": "i",
          "description": "第（Ⅰ）问抛物线解析式"
        },
        {
          "handle": "answer:i.parabola",
          "valid_scope": "i",
          "description": "第一问要求输出抛物线解析式"
        }
      ],
      "reason": "第（Ⅰ）问给出 a 和 c，可以联立 2a+b=0 求完整解析式。"
    },
    {
      "step_id": "derive_N",
      "goal_type": "derive_point",
      "target": "点 N",
      "reads": [
        "point:problem:D",
        "point:ii:M",
        "point:ii:N",
        "fact:ii:right_angle_equal_length_DMN",
        "fact:ii:N_fourth_quadrant",
        "fact:problem:m_gt_2"
      ],
      "strategy": "先由直角等腰关系列候选，再用象限和参数约束筛选",
      "recipe_hint": "right_angle_equal_length_construct_and_select",
      "creates": [],
      "produces": [
        {
          "handle": "fact:ii:N_coordinate_expr",
          "valid_scope": "ii",
          "description": "点 N 的含参坐标表达式"
        }
      ],
      "reason": "N 由 D、M 的直角等腰构造确定，但有两个候选，需要筛选。"
    },
    {
      "step_id": "derive_q1_parameter",
      "goal_type": "derive_parameter",
      "target": "第（Ⅱ）①中的 m",
      "reads": ["fact:ii_1:MN_length_squared_eq_10", "point:ii:M", "fact:ii:N_coordinate_expr"],
      "strategy": "由 MN^2=10 求参数 m",
      "recipe_hint": "parameter_from_segment_length",
      "creates": [],
      "produces": [
        {
          "handle": "fact:ii_1:m_value",
          "valid_scope": "ii_1",
          "description": "第（Ⅱ）①由长度条件得到的 m 值"
        }
      ],
      "reason": "先确定 m，再代入求该小问抛物线和最小值。"
    }
  ]
}
```

这不是可执行计划。代码层会把 `derive_N` 匹配到预注册 recipe，例如：

```text
construct_and_select_point:
  right_angle_equal_length_candidates
  -> select_point_by_quadrant_constraint
```

Recipe 是 family 级可执行候选，不是 LLM 输出。Resolver 可以同时尝试 single method 与 recipe，
但不会动态拼接任意 method 组合。

## 首版实现范围

### 当前 DeepSeek Probe：StepIntent 到答案闭环

当前 probe 已经不只是“输出校验”。南开 25 的真实 DeepSeek 测试会进入完整受控闭环：

```text
Nankai .llm ProblemIR
  -> StrategyPayloadBuilder
  -> Jinja prompt
  -> DeepSeekStrategyPlannerClient
  -> raw JSON
  -> StepIntentValidator
  -> HandleResolver
  -> StepIntentCandidateResolver
  -> RecipeTrialExecutor.compile()
  -> PlannerOutput
  -> RuntimeOrchestrator / InvocationExecutor
  -> ResultBuilder + expected answer gate
```

输入只使用真实南开 canonical ProblemIR projection、真实 family spec、method/recipe catalog 和 previous attempts。
expected answer 只作为测试 gate，不进入 prompt，不进入普通 payload。

#### 当前已实现组件

- `StepIntent` / `StepIntentDraft` 数据模型，输出按 `scopes[].steps[]` 分组。
- `STEP_INTENT_JSON_SCHEMA`，作为完整 schema 注入 prompt。
- `StrategyPayloadBuilder`，只读取 RuntimeProjection 生成的 LLM payload，不再从旁路 fixture fallback。
- `StrategyPromptRenderer`，使用 Jinja 模板。
- `DeepSeekStrategyPlannerClient`，复用 OpenAI-compatible provider。
- `FakeStrategyPlannerClient`，用于非网络单测和固定 fixture。
- `StepIntentValidator`，校验 schema、canonical handle、`valid_scope` 和重复语义 fact。
- `HandleResolver`，只修正“同名父级可见 handle 被误写成当前 scope”的确定错误。
- `StepIntentCandidateResolver`，根据 `recipe_hint / goal_type / produces` 给出 recipe/method 候选。
- `RecipeTrialExecutor`，根据 family 中的 `RecipeExecutionSpec` 和 `MethodBindingRuleSpec` 编译为 `PlannerOutput`。

#### Prompt Payload 分源

为了便于 review、debug 和 fake，payload 必须按来源拆分，不做一个巨大混合 JSON：

```text
payload/
  problem_ir            # 来自 canonical ProblemIR projection
  family_spec           # 来自 SolverFamilySpec
  method_catalog        # 来自 FamilySpec.method_ids + MethodSpecRegistry
  recipe_catalog        # 来自 FamilySpec.step_recipes
  few_shot_examples      # 来自 examples corpus，首版可用 fake/static
  previous_attempts      # 来自 PlannerMemory.to_repair_payload()
  output_json_schema     # 来自 STEP_INTENT_JSON_SCHEMA
```

每个来源都应能单独 fake：

- fake `problem_ir`：用于测试 prompt 渲染不依赖真实 fixture。
- fake `family_spec`：用于测试 family strategy 能进入 prompt。
- fake `method_catalog / recipe_catalog`：用于测试能力摘要能进入 prompt。
- fake `few_shot_examples`：用于测试示例注入。
- fake `previous_attempts`：用于测试 repair 指令。

真实 DeepSeek opt-in 测试使用真实南开 payload；普通单测使用 fake payload，避免网络和私有 key。

#### Prompt 内容

System prompt 只放硬规则：

- 只能输出 JSON。
- 必须遵守完整 schema。
- 只输出 `steps`。
- 不输出答案值、坐标、ContextPath、method invocation、promote、depends_on。
- 每个 step 必须有 `reason`。
- 如果 `previous_attempts` 非空，必须重新输出完整 `StepIntent[]`，不能只输出 patch。

User prompt 放分源 payload：

- canonical ProblemIR projection。
- FamilySpec 题型思路。
- Method Catalog。
- Recipe Catalog。
- few-shot StepIntent 示例。
- previous attempts summary。

#### 输出校验

`StrategyDraftValidator` 首版只校验：

- JSON 可解析。
- 顶层只有 `steps`。
- `steps` 非空。
- `step_id` 唯一，snake_case，不能是 `step_1`。
- 必填字段齐全：`step_id / goal_type / target / strategy / reason`。
- `reads` 必须是字符串数组，只能引用 canonical Entity / Fact / answer handle。
- `creates / produces` 必须是对象数组，每一项必须包含 `handle / valid_scope / description`。
- `creates` 只能声明 derived Entity；`produces` 只能声明 Fact / answer Fact。
- 不含 `$problem`、`$question`、`ContextPath`、`ctx_`、坐标数组、明显答案值。
- 至少覆盖全部 required `QuestionGoal` 的语义目标：可用关键词/answer handle 粗校验，不要求可执行。

注意：Validator 仍不做 method 参数绑定；绑定和执行由 `RecipeTrialExecutor` 和现有 runtime 验证。
真实 DeepSeek probe 的成功条件是：StepIntent 合法、能编译为 `PlannerOutput`、runtime 求解成功、答案与 expected JSON 等价。

#### Debug 输出

真实 DeepSeek 测试必须输出并保存：

```text
internal/solver-runs/strategy-planner-deepseek-nankai/
  prompt.system.md
  prompt.user.md
  payload.problem_ir.json
  payload.family_spec.json
  payload.method_catalog.json
  payload.recipe_catalog.json
  payload.few_shot_examples.json
  payload.previous_attempts.json
  output.schema.json
  raw-response.txt
  parsed-step-intents.json
  validation-report.json
```

这些文件用于人工 review，不进入 solver 执行链。

#### 当前 Probe 测试

- `test_strategy_payload_builder.py`
  - 各来源 payload 能独立构建。
  - fake payload 能渲染 prompt。
  - prompt 不包含 expected answer、裸 ContextPath、`ctx_N`。

- `test_strategy_draft_validator.py`
  - 合法 step intent 通过。
  - 非 JSON、缺字段、重复 step_id、编号式 step_id、裸 ContextPath、坐标/答案值失败。

- `test_strategy_prompt_renderer.py`
  - prompt 包含完整 JSON schema。
  - prompt 包含原题、FamilySpec、QuestionGoal、few-shot。

- `test_deepseek_strategy_planner_nankai.py`
  - 默认 skip。
  - 需要 `RUN_LLM_INTEGRATION=1 RUN_DEEPSEEK_STRATEGY_PLANNER=1`。
  - 调用真实 DeepSeek。
  - 保存 debug artifacts。
  - 断言输出 JSON 通过 StepIntent 校验。
  - 断言 StepIntent 可以通过 `RecipeTrialExecutor` 编译并由 runtime 求出南开 expected answers。
  - 失败时将 validator/candidate/execution/result 错误压缩进 `previous_attempts`，下一轮要求 LLM 重新输出完整 `StepIntent[]`。

推荐命令：

```bash
cd server && RUN_LLM_INTEGRATION=1 RUN_DEEPSEEK_STRATEGY_PLANNER=1 \
  uv run pytest tests/solver/test_deepseek_strategy_planner_nankai.py -q -s
```

### 完整 Method Solver 接入

### 必须做

- `StepIntent` / `StepIntentDraft` 数据模型。
- `StrategyPayloadBuilder`。
- `StrategyDraftValidator`。
- `FakeStrategyPlannerClient`，覆盖南开 canonical、河西。
- `StepRecipe` / `StepRecipeRegistry`，首版注册南开和河西所需短 recipe。
- `ExecutableCandidateResolver`，混合检索 single method / step recipe top-k。
- `BindingCandidateResolver`，按类型、scope、语义关系生成候选。
- `TrialExecutor`，clone context 试执行。
- `TrialRanker`，选择最佳 trial。
- `CommitExecutor`，在主 context 重新执行 best trial。
- `StrategyPlannerProvider` 接入 `SolverRuntimeConfig(planner_mode="strategy", llm_provider="recorded")`。
- 南开、河西 recorded E2E 通过。

其中南开 canonical 的“StepIntent -> PlannerOutput -> runtime 答案”竖切已经跑通；剩余接入重点是把这条链路从测试 helper 接入正式 Orchestrator/provider，并扩展到河西、alt-label 和更多 family。

### 可以后置

- DeepSeek 正式 provider 接入默认 solver。
- alt-label E2E。
- method embedding 检索。
- LLM tie-break。
- 局部 repair。
- Fallback/gap 系统接入。
- ExplanationBuilder 学生化推导。

## 模块建议

当前为了快速竖切，payload、validator、HandleResolver、candidate resolver、binding rule 和
RecipeTrialExecutor 仍主要集中在 `runtime/strategy_planner.py`。后续当河西、alt-label 和更多
family 接入后，再按职责拆分为下列模块：

```text
server/shuxueshuo_server/solver/runtime/
  strategy_planner.py          # StrategyPlanner 接口与 StepIntent 模型
  strategy_payload.py          # PlannerInputs -> LLM payload
  strategy_fakes.py            # FakeStrategyPlannerClient
  step_recipes.py              # family 级 StepRecipeRegistry
  executable_resolver.py       # StepIntent -> SingleMethod/Recipe candidate top-k
  binding_resolver.py          # ExecutableCandidate -> BindingCandidate[]
  trial_executor.py            # cloned context trial execution
  trial_ranker.py              # TrialResult ranking
  strategy_executor.py         # StepIntent[] -> committed RuntimeContext
```

命名可以后续再收敛；首版更重要的是把边界切清楚。

## 测试计划

### 单元测试

- `test_strategy_payload.py`
  - payload 包含 canonical ProblemIR projection 原题、FamilySpec、QuestionGoal、method catalog、recipe catalog。
  - payload 不包含 expected answers、裸 ContextPath、ctx_N。

- `test_step_intent_validator.py`
  - 合法 StepIntent 通过。
  - 编号式 step_id、裸 ContextPath、答案值、未知字段失败。

- `test_executable_candidate_resolver.py`
  - “求中点” intent 找到 `midpoint_point`。
  - “直角等腰构造点” intent 找到 `construct_and_select_point` recipe。
  - single method / recipe 混合 top-k 稳定。
  - 找不到候选时生成 retryable structured error。

- `test_binding_candidate_resolver.py`
  - 按 type/scope 过滤。
  - sibling subquestion 不可见。
  - relation roles 能帮助绑定 D/M/N、E/G、MN 等。
  - recipe 内部 wiring 自动连接，不参与外部候选组合。

- `test_trial_executor.py`
  - trial 失败不污染主 context。
  - validation failed / execution failed / checks failed 分类正确。

- `test_trial_ranker.py`
  - checks 全通过的 trial 优先。
  - 输出类型和目标匹配优先。
  - 并列时返回 ambiguous，而不是随机选。

### E2E 测试

- fake Strategy Planner 跑南开 canonical，答案与 expected 一致。
- fake Strategy Planner 跑河西，答案与 expected 一致。
- default deterministic 南开、河西保持通过。
- `--planner strategy --llm-provider recorded` 返回 ok。
- 找不到 executable candidate 时生成结构化 gap，不直接伪造 success。

## Open Questions

1. 一个 StepIntent 是否允许对应多个 method？
   - 允许，但只能通过预注册 StepRecipe。Recipe 是 family 级可执行候选，不允许开放式 method 组合搜索。

2. ExecutableCandidateResolver 是否需要 LLM tie-break？
   - 首版不需要。只有 trial 全部成功且 rank 完全并列时，先返回 ambiguous error。

3. StepIntent 是否应该带 step 级 `scope_hint`？
   - 当前不需要。真实输出按 `scopes[].steps[]` 分组，scope 已由外层承载；后续若需要跨 scope 辅助说明，可以加只读 debug 字段，但不参与执行。

4. Trial 是否并发？
   - 同一 step 内可以并发；不同 step 顺序执行。

5. 中间结果如何命名？
   - 由代码根据 `step_id + output_key` 自动生成，LLM 不命名中间 path。

6. 如果 LLM 少拆了一步怎么办？
   - Trial 失败或 ResultBuilder 缺答案后，把结构化错误传回下一轮，让 LLM 重新生成完整 StepIntent[]。

7. 如果题目命中新 family 但没有 method 或 recipe 怎么办？
   - 先进入 repair，让 LLM 尝试重新拆 StepIntent；仍失败则记录 MethodGap / RecipeGap，进入 fallback/gap 系统，不阻塞用户网页生成。

## 验收标准

首版完成时，应满足：

- 旧 LLM planner 不再恢复。
- LLM 输出没有 method invocation / ContextPath / promote / depends_on。
- Method 和 binding 的选择由代码 trial 决定。
- fake Strategy Planner 能跑通南开、河西。
- deterministic 默认路径不受影响。
- 全量测试通过：

```bash
cd server && uv run pytest tests/solver -q
```
