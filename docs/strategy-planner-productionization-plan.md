# Strategy Planner 生产化计划

## Summary

本计划记录下一阶段 Method Solver 主链路收口方案：把题目输入统一为一份 canonical ProblemIR，并让 Strategy Planner 接入 `RuntimeOrchestrator` / CLI，替代生产路径里的南开、河西 deterministic planner。

目标链路为：

```text
Canonical ProblemIR
-> FamilyRegistry.match
-> StrategyPlanner
-> StepIntent
-> StepIntentNormalizer / Validator
-> StepIntentCandidateResolver
-> RecipeTrialExecutor
-> PlannerOutput
-> InvocationExecutor
-> ResultBuilder
-> SolverResult
```

本计划只描述实现方案，不直接修改代码逻辑、测试或 fixture。

## Key Changes

- **统一 ProblemIR 来源**
  - canonical ProblemIR 成为唯一题目事实源，显式包含 `problem_id / pattern / problem_type / original_text / scopes / entities / facts / question_goals / symbol roles`。
  - 删除南开、河西独立 `.llm.json` 事实源；Strategy prompt 和 RuntimeContext 都从同一份 ProblemIR 读取。
  - 新增 `RuntimeProjection`，从 canonical Entity / Fact / QuestionGoal 派生当前 runtime 所需结构，例如 function expression、coefficient relation、path_problem、segment conditions、question goals。
  - expected answers 和 executable StepIntent fixture 继续作为测试数据存在，但不作为题目事实源。

- **Strategy Planner 接入 Orchestrator**
  - 新增 `StrategyPlanner(GenericPlanner)`，内部执行 `StrategyPayloadBuilder -> LLM/recorded client -> StepIntentValidator -> StepIntentNormalizer -> StepIntentCandidateResolver -> RecipeTrialExecutor -> PlannerOutput`。
  - `PlannerInputs` 或 planner 构造参数需要能接收 canonical problem payload；禁止从旁路 `.llm.json` 文件读取题目事实。
  - `RuntimeOrchestrator` 继续负责 attempt loop、干净 `RuntimeContext` 重建、declaration validation、method execution、ResultBuilder 和结构化 retry error。
  - 生产 provider registry 改为注册 Strategy provider，不再默认注册 `Nankai25DeterministicPlannerAdapter` 或 `Hexi25WeightedPathPlannerV15`。

- **CLI / Runtime Config**
  - CLI 支持 `--planner strategy`。
  - `--llm-provider recorded|deepseek`：
    - `recorded` 使用固定 executable StepIntent fixture，供 CI 和本地无网络回归使用。
    - `deepseek` 调真实模型，并复用现有 attempt/debug/usage 输出。
  - `deterministic` 只作为临时 debug/oracle 模式保留；若保留，必须显式传参，不能作为生产默认路径。

- **deterministic planner 退出**
  - Strategy recorded E2E 跑通南开、河西后，新增 no-call/no-import 测试，防止生产路径回退 deterministic template。
  - Strategy CLI 和真实 DeepSeek opt-in 稳定后，删除南开 frozen template、`hexi_weighted_path_planner.py`、deterministic provider 注册和 `enabled_problem_ids` 的 deterministic 门控语义。

## Test Plan

- **Canonical IR / Projection**
  - 南开、河西 canonical fixture 通过 schema 校验，且不包含旧 solver hints、expected、method chain。
  - `RuntimeProjection` 能从 canonical IR 派生 RuntimeContext 所需 function、constraints、conditions、questions/goals。
  - Strategy payload 与 RuntimeContext 使用同一份 canonical fixture；测试断言不再读取 `.llm.json`。

- **Strategy Recorded E2E**
  - recorded 南开 StepIntent 经 StrategyPlanner + Orchestrator 返回 expected answers。
  - recorded 河西 StepIntent 经 StrategyPlanner + Orchestrator 返回 expected answers。
  - 测试 monkeypatch deterministic planner `plan()` 抛错，确认 Strategy 路径仍通过。

- **CLI / DeepSeek**
  - `--planner strategy --llm-provider recorded` 跑南开、河西，退出码 0，输出 JSON 与 expected 对齐。
  - `--planner strategy --llm-provider deepseek` 继续 opt-in，完整 loop 成功才通过；失败写 attempt debug、validation、normalization、resolution、solver-result。
  - 全量回归：

    ```bash
    cd server && uv run pytest tests/solver -q
    ```

- **文档检查**
  - `git diff --check docs/strategy-planner-productionization-plan.md` 通过。
  - 文档包含 `Summary / Key Changes / Test Plan / Assumptions`。

## Assumptions

- canonical ProblemIR 是唯一题目事实源；projection 只是运行时视图，不允许人工维护第二份题目事实。
- recorded StepIntent 是 planner 输出黄金样例，不是 ProblemIR，也不算双事实源。
- Strategy Planner 的执行粒度仍是 method/recipe 最小颗粒度；网页讲解粒度由后续 ExplanationBuilder 负责。
- Family 选择本阶段仍由 `pattern/problem_type` 和 registry 完成，不引入 LLM family selector。
- 本计划先接入南开、河西两道 golden case；第二道 weighted family 题跑通后，再正式删除河西 deterministic planner 和相关门控。
