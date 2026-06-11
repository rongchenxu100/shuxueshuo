# Method Solver 当前架构

## Summary

Method Solver 的目标是把一道 canonical ProblemIR 求解为 verified `SolverResult`。
当前生产默认路径是 Strategy Planner：

```text
canonical ProblemIR
  -> RuntimeProjection
  -> RuntimeContext
  -> FamilyRegistry.match
  -> StrategyPlanner(recorded/deepseek)
  -> RecipeTrialExecutor
  -> PlannerOutput
  -> InvocationExecutor
  -> ResultBuilder
  -> SolverResult
```

deterministic planner 只保留为显式 debug/oracle，不是生产默认 provider。

## Single Source Of Truth

题目事实只来自 canonical solver fixture：

```text
internal/solver-fixtures/<problem_id>.json
```

canonical fixture 的 authored `input` 只应包含：

- `problem_id`
- `pattern`
- `problem_type`
- `original_text`
- `scopes`
- `entities`
- `facts`
- `question_goals`

它不应包含：

- expected answers；
- raw DeepSeek response；
- executable StepIntent；
- runtime `ContextPath`；
- derived coordinates/equations/parameters；
- auxiliary solution-only points；
- old runtime compatibility fields such as `data.entities.points`, `data.relations`, `path_problem`, `questions[].goals.target_path`。

Expected answers、recorded executable StepIntent 和 few-shot 都是测试或 prompt 投影，不是题目事实源。

## RuntimeProjection

`RuntimeProjection` 从同一份 canonical ProblemIR 派生两个 view：

1. **Runtime view**：给 `ContextBuilder` 构建 `RuntimeContext` 使用，包含当前 executor 仍需要的 function、relations、conditions、question tree、goal target paths 等兼容结构。
2. **LLM payload view**：给 Strategy prompt 使用，只包含 canonical handles 和题面语义，不暴露 runtime path。

`problem_to_llm_payload(problem)` 是当前 LLM payload 入口。旧 `.llm.json` 旁路事实源已删除。

## RuntimeContext

`RuntimeContext` 是 method executor 的运行状态：

- 存储题设对象、题设 fact、question/subquestion containers；
- 保存 declarations 创建的 derived entities；
- 保存 method invocation outputs；
- 维护 promoted outputs；
- 提供 `ContextPath` 读写和 scope 可见性；
- 供 `InvocationExecutor`、`DeclarationValidator`、`ResultBuilder` 使用。

LLM 不应看到 `RuntimeContext` 或 `ContextPath`。canonical handle 到 runtime path 的桥接由
`CanonicalRuntimeBindingIndex` 完成。

## RuntimeOrchestrator

`RuntimeOrchestrator.solve(problem)` 负责求解生命周期：

1. 匹配 family。
2. 构建 fresh `RuntimeContext`。
3. 创建 planner provider。
4. 调用 planner 生成 `PlannerOutput`。
5. 校验 declarations。
6. 执行 method invocations。
7. 收集 method checks。
8. 通过 `ResultBuilder` 汇总 answers。
9. 若 Strategy Planner 失败，生成结构化 repair attempt 并进入下一轮。

生产默认 provider 是 Strategy provider fallback。Family-specific deterministic provider 只有显式 debug/oracle 模式才应传入。

## StrategyPlanner

`StrategyPlanner` 实现 `GenericPlanner.plan(inputs) -> PlannerOutput`，模式有两种：

- `recorded`：读取 `<problem_id>.executable-step-intents.json`，跳过真实 LLM，但仍走 validator、normalizer、resolver、RecipeTrialExecutor 和 method execution。
- `deepseek`：调用真实 DeepSeek，解析 raw response，再走同一条后半段链路。

Recorded 模式不是 mock `PlannerOutput`，它覆盖 LLM 输出之后到答案的完整 runtime 链路。

## PlannerOutput

`PlannerOutput` 是 executor 能执行的计划：

- `context_declarations`：derived entity declarations。
- `step_plans`：每个 StepPlan 包含 goal、method invocations、expected/promoted outputs。
- `metadata`：planner debug 信息。

`StepIntent` 不是 executable plan。只有经过 `RecipeTrialExecutor` 编译、dry-run 通过后才成为 `PlannerOutput`。

## Method Layer

Method 是全局可复用的原子数学能力。

每个 method Python 文件同时包含：

- runtime implementation；
- `SPEC`；
- input/output types；
- preconditions/postconditions；
- optional `repair_hints`。

Python `SPEC` 是事实源，`internal/method-specs/*.json` 由同步命令生成，不手写维护。

Method 不写题号、problem_id 或固定点名。它描述：

```text
Given semantic inputs, derive semantic output under preconditions.
```

## Family Layer

`SolverFamilySpec` 描述一个题型 family：

- `family_id`
- match rule：`pattern / problem_type`
- `common_goal_types`
- student-friendly `strategy_principles`
- visible `method_ids`
- visible `step_recipes`
- `method_binding_rules`

Family 的核心差异应是几何机制，而不是二次函数公共能力。例如：

- `QuadraticPathMinimumSolver`：直角等腰构造、两动点路径降维、折线拉直。
- `QuadraticWeightedPathMinimumSolver`：加权路径通过辅助三角形转化。
- `QuadraticEqualLengthRayPathMinimumSolver`：等长射线关系转单距离最值。
- `QuadraticSquareReflectionPathMinimumSolver`：正方形结构降维、轨迹线、将军饮马。

随着题库扩大，通用二次函数/坐标/参数能力应上提到 Capability Pack，family 只声明 base packs + mechanism packs。

## Binding And Code Fill

`MethodBindingRuleRegistry` 把 StepIntent semantic handles 绑定到 method input slots。

绑定顺序：

1. explicit reads；
2. local prep outputs；
3. visible runtime bindings；
4. `EntityStateResolver` 的唯一可见 state；
5. companion outputs；
6. failure with structured repair hint。

代码可以补：

- entity -> unique typed state；
- explicit alias / parent-scope handle；
- companion output registration；
- declarative prep invocation；
- recipe-internal wiring；
- structured output-key mapping。

代码不能补：

- missing mathematical conclusion；
- sibling scope data；
- fuzzy spelling；
- value from free-text reason；
- unsupported geometry strategy。

详见 [strategy-planner-code-fill-policy.md](strategy-planner-code-fill-policy.md)。

## RecipeTrialExecutor

`RecipeTrialExecutor` 是 StepIntent 到 PlannerOutput 的执行边界：

```text
StepIntentDraft
  -> normalize
  -> candidate resolver
  -> compile capability
  -> bind inputs
  -> add declarations / prep / companion outputs
  -> dry-run prefix
  -> accepted prefix or blocker
```

它按 step 顺序推进。后续 step 失败不会丢掉前面已验证 prefix。

执行诊断包含：

- `accepted_prefix`
- `applied_fills`
- `planner_insights`
- `preflight_issues`
- `blockers`
- `skipped_steps`
- `candidate_errors`

## Repair Feedback

Strategy repair loop 不带真实 chat history。每轮 prompt 都携带结构化 `previous_attempts`。

`RepairFeedbackBuilder` 输出 LLM-facing `repair_summary`：

- frozen prefix；
- planner state；
- current blocker；
- already handled code fills；
- next actions；
- do-not rules；
- warnings。

具体修复建议归属 capability：

- method `SPEC.repair_hints`
- recipe metadata
- binding selector hints
- generic fallback hints

Builder 只聚合和安全过滤，不承载 family-specific 修复逻辑。

## Few-shot Layer

`internal/few-shots/<problem_id>.few-shot.json` 是题库的 Strategy prompt 投影。

来源：

- canonical ProblemIR projection；
- verified `.executable-step-intents.json`。

选择：

- same family；
- `retrieval.goal_types` overlap；
- `top_k=1`；
- production allows same problem；
- tests can exclude same problem；
- fallback mock example if no entry.

## Current Golden Coverage

Recorded and real DeepSeek Strategy tests currently cover:

- 南开一模 25；
- 河西一模 25；
- 西青一模 25；
- 和平一模 25；
- 和平二模 25。

Recorded tests are the stable regression surface. Real DeepSeek tests are opt-in and write debug artifacts under:

```text
internal/solver-runs/strategy-planner-deepseek-<case>/
```

## CLI

Recorded:

```bash
cd server && uv run python -m shuxueshuo_server.solver.solve_problem \
  --fixture ../internal/solver-fixtures/<problem_id>.json \
  --planner strategy --llm-provider recorded
```

DeepSeek:

```bash
cd server && RUN_LLM_INTEGRATION=1 RUN_DEEPSEEK_STRATEGY_PLANNER=1 \
  RUN_DEEPSEEK_<CASE>_STRATEGY_PLANNER=1 \
  uv run pytest tests/solver/test_deepseek_strategy_planner_<case>.py -q -s
```

Regression:

```bash
cd server && uv run pytest tests/solver -q
git diff --check
```

## Future Design

- Capability Packs：减少 family 中重复的 base method / binding rules。
- Gap/Fallback：当 family/method/binding 不足时，输出 unverified fallback 和结构化 gap。
- ExplanationBuilder：把 verified method trace 转成学生讲解步骤、图形意图和动画。
- RuntimeContext 收敛：未来可让 executor 直接读取 canonical Entity/Fact，而不是依赖 runtime-compatible projection。
