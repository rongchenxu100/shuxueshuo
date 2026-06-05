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

本计划同时作为本轮实现记录：Strategy recorded 已接入 Orchestrator/CLI，
南开、河西独立 `.llm.json` 事实源已删除，prompt payload 由 canonical
ProblemIR 投影生成。

## Key Changes

- **统一 ProblemIR 来源**
  - canonical ProblemIR 成为唯一题目事实源，显式包含 `problem_id / pattern / problem_type / original_text / scopes / entities / facts / question_goals / symbol roles`。
  - 删除南开、河西独立 `.llm.json` 事实源；Strategy prompt 和 RuntimeContext 都从同一份 ProblemIR 读取。
  - 新增 `RuntimeProjection`，作为 canonical ProblemIR 到 runtime/LLM 两个视图的统一投影层；它不在首版替代 `ContextBuilder`，而是在 `ContextBuilder` 之上/之前生成它可消费的 runtime view。
  - `RuntimeProjection` 输入固定为一份 canonical ProblemIR；输出固定为两类：
    - `RuntimeProjection.to_runtime_problem_ir()` 或等价接口：生成当前 `ContextBuilder.build()` 可消费的 runtime-compatible ProblemIR/view，用于构建 `RuntimeContext`，包含 function expression、coefficient relation、path_problem、segment conditions、question tree/goals 等旧 runtime 仍需要的结构。
    - `RuntimeProjection.to_llm_problem_payload()`：生成 Strategy prompt 使用的 handle-only LLM Problem payload，替代 `.llm.json`，只包含 `original_text / scopes / entities / facts / question_goals`，不包含 runtime ContextPath、expected、method chain 或 solver hints。
  - `ContextBuilder` 首版继续负责真正构建 `RuntimeContext`；`RuntimeProjection` 负责把 canonical Entity/Fact/QuestionGoal 转成 `ContextBuilder` 当前需要的兼容输入。等 runtime 完全改为直接读 canonical Entity/Fact 后，才考虑收窄或替换 `ContextBuilder`。
  - canonical handle 到 runtime `ContextPath` 的桥接仍由 `CanonicalRuntimeBindingIndex` 负责；LLM payload 不暴露 `ContextPath`，RuntimeProjection 只保证 LLM view 与 runtime view 来自同一批 canonical handles。
  - expected answers 和 executable StepIntent fixture 继续作为测试数据存在，但不作为题目事实源。

- **Strategy Planner 接入 Orchestrator**
  - 新增 `StrategyPlanner(GenericPlanner)`，内部执行 `StrategyPayloadBuilder -> LLM/recorded client -> StepIntentValidator -> StepIntentNormalizer -> StepIntentCandidateResolver -> RecipeTrialExecutor -> PlannerOutput`。
  - 保持 `GenericPlanner.plan(inputs: PlannerInputs) -> PlannerOutput` 接口不变，不在 `PlannerInputs` 中新增 LLM 专属 `problem_payload` 字段。
  - `StrategyPlanner.__init__` 接收 `RuntimeProjection` 或等价的 projection provider；`plan(inputs)` 内部从 `inputs` 中的 `ProblemIR` 引用/构造期注入的 canonical ProblemIR 调用 `projection.to_llm_problem_payload()`，再交给 `StrategyPayloadBuilder`。
  - Orchestrator/provider 构造 `StrategyPlanner` 时负责注入 canonical ProblemIR 或 projection provider；禁止 `StrategyPlanner` 在 `plan()` 中从旁路 `.llm.json` 文件读取题目事实。
  - `RuntimeOrchestrator` 继续负责 attempt loop、干净 `RuntimeContext` 重建、declaration validation、method execution、ResultBuilder 和结构化 retry error。
  - 保持当前 `PlannerProvider = Callable[[RuntimeContext], GenericPlanner]` 签名不变；Strategy provider 从传入的 `RuntimeContext.problem` 取得 canonical ProblemIR，并构造 `RuntimeProjection` 注入 `StrategyPlanner`。
  - 生产目标是单一 Strategy provider 作为默认 provider，而不是按 family 注册南开/河西专属 provider。Orchestrator 匹配到 family 后，若没有 family-specific provider，则 fallback 到默认 Strategy provider。
  - 临时 debug/oracle 模式可以保留 family-specific deterministic provider 映射，但生产默认 registry 不再注册 `Nankai25DeterministicPlannerAdapter` 或 `Hexi25WeightedPathPlannerV15`。

- **CLI / Runtime Config**
  - CLI 支持 `--planner strategy`。
  - `--llm-provider recorded|deepseek`：
    - `recorded` 使用固定 executable StepIntent fixture，供 CI 和本地无网络回归使用。
    - `deepseek` 调真实模型，并复用现有 attempt/debug/usage 输出。
  - `deterministic` 只作为临时 debug/oracle 模式保留；若保留，必须显式传参，不能作为生产默认路径。

- **Recorded 模式注入层级**
  - `recorded` 不 mock 成 `PlannerOutput`，也不直接绕过 Strategy 后半段。
  - `recorded` 从 `<problem_id>.executable-step-intents.json` 构造 `StepIntentDraft`，注入到 LLM 输出之后、normalizer 之前。
  - `recorded` 仍必须走 `StepIntentValidator`（可选结构校验）、`StepIntentNormalizer`、`StepIntentCandidateResolver`、`RecipeTrialExecutor`、declaration validation、method execution 和 `ResultBuilder`。
  - 这样 recorded 覆盖“LLM 输出之后到答案”的完整运行时链路；它唯一跳过的是真实 LLM 调用和 raw JSON parse。
  - DeepSeek 模式则从 raw response 文本进入 `StepIntentValidator.validate_json_with_report()`，再走同一条后半段链路。

- **deterministic planner 退出**
  - Strategy recorded E2E 跑通南开、河西后，新增 no-call/no-import 测试，防止生产路径回退 deterministic template。
  - 退出条件固定为：`--planner strategy --llm-provider recorded` 跑通南开与河西两道 golden E2E，且 no-call 测试证明未调用 deterministic planner。满足后即可删除南开/河西 deterministic planner 和 `enabled_problem_ids` 的 deterministic 门控语义。
  - 不等待第三道题，也不要求新增第二道 weighted family 题；后续新题型覆盖不足由 Strategy/fallback/gap 系统处理。

- **`.llm.json` 迁移与删除**
  - 新增 `problem_to_llm_payload(problem: ProblemIR) -> dict`，作为 `RuntimeProjection.to_llm_problem_payload()` 的实现入口；它从 canonical ProblemIR 的 `original_text / data.entities.items / data.facts / data.questions[].goals` 生成 handle-only prompt payload。
  - `StrategyPayloadBuilder.build()` 不再要求外部 `problem_payload` 参数；StrategyPlanner 通过 projection 传入 canonical ProblemIR 生成的 payload，测试仍可显式注入 payload 以便构造边界用例。
  - `build_strategy_probe_inputs()` 不再负责 `.llm.json` 旁路输入；测试和 DeepSeek probe 统一通过 projection 生成 payload。
  - `test_deepseek_strategy_planner_nankai.py`、`test_deepseek_strategy_planner_hexi.py`、`test_strategy_planner_phase1.py` 中所有 `_json_fixture("*.llm.json")` 调用改为 `problem_to_llm_payload(load_problem_ir(...))`。
  - `tools/sync_strategy_few_shots.py` 不再读取 `.llm.json`；改为读取 canonical ProblemIR，经 projection 生成 `original_text` 和 prompt payload，再与 `.executable-step-intents.json` 生成 few-shot。
  - `strategy_few_shots.build_few_shot_entry()` 的输入从 `problem_payload` 调整为 projection 生成的 LLM payload；函数自身不读取 `.llm.json`。
  - 上述迁移已完成，南开、河西 `.llm.json` 文件已删除。

## Test Plan

- **Canonical IR / Projection**
  - 南开、河西 canonical fixture 通过 schema 校验，且不包含旧 solver hints、expected、method chain。
  - `RuntimeProjection.to_runtime_problem_ir()` 能从 canonical IR 派生 `ContextBuilder` 所需 function、constraints、conditions、questions/goals，并成功构建 `RuntimeContext`。
  - `RuntimeProjection.to_llm_problem_payload()` 能从同一份 canonical IR 生成 prompt payload，且只包含 canonical Entity/Fact/answer handles，不包含 `$problem/$question` 等 runtime ContextPath。
  - 迁移期曾用现有南开、河西 `.llm.json` 做一次性 golden 对照，确认 projection 生成同一批 canonical handles/question goals；最终测试不再依赖已删除文件。
  - Strategy payload 与 RuntimeContext 使用同一份 canonical fixture；测试断言不再读取 `.llm.json`，且 projection 输出能构建 canonical handle registry。
  - 搜索断言生产代码和 solver 测试中不再出现 `.llm.json` fixture 读取；few-shot 同步工具也不依赖 `.llm.json`。

- **Strategy Recorded E2E**
  - recorded 南开 StepIntent 经 StrategyPlanner + Orchestrator 返回 expected answers。
  - recorded 河西 StepIntent 经 StrategyPlanner + Orchestrator 返回 expected answers。
  - recorded 测试断言输入是 `StepIntentDraft`/executable StepIntent fixture，而不是直接返回 `PlannerOutput`。
  - recorded 测试断言 normalizer、candidate resolver、RecipeTrialExecutor 和 method executor 都被执行。
  - 测试断言 `PlannerInputs` 接口未新增 `problem_payload`；StrategyPlanner 通过构造期 projection 注入获得 LLM payload。
  - 测试断言生产 provider registry 使用单一默认 Strategy provider fallback，不需要为南开/河西分别注册 Strategy provider。
  - 测试 monkeypatch deterministic planner `plan()` 抛错，确认 Strategy 路径仍通过。
  - recorded 南开/河西全部通过后，测试断言 deterministic provider 不在生产默认 registry 中；`enabled_problem_ids` 仅保留 family 支持范围语义，不再表示 deterministic planner 白名单。

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
- 本计划以南开、河西两道 golden case 作为 deterministic 退出门槛；recorded Strategy E2E 全部通过且 no-call 测试通过后，即可删除南开/河西 deterministic planner 和相关门控。
