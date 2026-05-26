# LLM Fallback 与 Gap 系统设计

## Summary

用户会用系统自助生成题目网页，因此 family/method 不足时不能直接让服务不可用。在线链路应优先使用 Method Solver 生成 verified solution；如果 family 未命中、method 缺失、binding 不足或执行失败，则降级到 LLM fallback，先产出可用于网页生成的未验证解题步骤，同时记录结构化 gap 日志，供离线补 FamilySpec、MethodSpec、PlanningSignal 或 ProblemIR 抽取。

Fallback Solver 与受控 LLM Planner 是两条独立链路：Planner 走 `SlotBinder -> PlanCompiler -> Executor`；Fallback 绕过 method executor，由 LLM 直接生成结构化答案和步骤。两者共享 provider/config/CLI 基础设施，但后续实现和验收应独立推进。

## Key Changes

### 输出状态与验证等级

- `status="ok"` 只表示 Method Solver 全部通过，所有 required `QuestionGoal` 都由 method/checks 验证。
- 新增 `status="fallback"`，表示 LLM fallback 成功产出了用户可见结果，但未全量 method 验证。
- `status="failed"` 表示 Method Solver 与 LLM fallback 都失败，或 ProblemIR 不足以支撑 fallback。
- `verification_level` 独立表达可信度：`verified | partial | unverified | none`。
- `solution_source` 表达来源：`method_solver | mixed | llm_fallback | none`。

推荐输出：

```json
{
  "status": "fallback",
  "verification_level": "partial",
  "solution_source": "mixed",
  "answers": {},
  "fallback_solution": {},
  "gap_reports": [],
  "warnings": [
    "部分解法由 LLM 兜底生成，尚未经过 Method Solver 全量验算"
  ]
}
```

HTML 生成器规则：

- `status="ok"`：优先使用 `answers` 和 method trace。
- `status="fallback"`：优先使用 `fallback_solution.solution_steps`，必须展示 warning。
- `status="failed"`：不生成正式题目网页，进入人工处理。

SolverResult 模型需要同步扩展：

- `status` 增加 `"fallback"`。
- 新增 `verification_level`，默认 `"verified"`。
- 新增 `solution_source`，默认 `"method_solver"`。
- 新增 `fallback_solution`，默认 `None`。
- 新增 `gap_reports`，默认空列表。
- 新增 `warnings`，默认空列表。

这些默认值用于保持现有 `status="ok"` 测试和调用方兼容。

### Fallback 触发分层


| Tier   | 触发条件                                             | 输出                             | verification_level | solution_source |
| ------ | ------------------------------------------------ | ------------------------------ | ------------------ | --------------- |
| Tier 1 | family 命中，method/binding/checks 全部通过             | Method Solver result           | `verified`         | `method_solver` |
| Tier 2 | family 命中，但缺 method、binding 不足、method 不合适或部分执行失败 | LLM fallback + 已验证前缀摘要         | `partial`          | `mixed`         |
| Tier 3 | family 未命中，说明可能是新题型                              | LLM fallback + FamilyGapReport | `unverified`       | `llm_fallback`  |
| Tier 4 | ProblemIR 不足以支撑 fallback，或 LLM fallback 失败       | failed                         | `none`             | `none`          |


Tier 2 中 Fallback 可以只读已经 verified 的运行结果，但不能写 `RuntimeContext`。进入 fallback 前，Orchestrator 从当前 `RuntimeContext` 抽取 `VerifiedOutputsSummary`：

```python
VerifiedOutputsSummary(
    promoted_outputs=[
        {"path": "$question.i.outputs.parabola", "type": "Parabola", "value": "..."},
        {"path": "$question.ii.points.D", "type": "Point", "value": ["sqrt(2)", "1"]},
    ],
    passed_checks=[...],
    completed_steps=[...],
)
```

`value` 使用现有答案序列化规则：点为 JSON 数组，SymPy 表达式/方程为字符串，参数值为字符串或 JSON scalar。也就是说，它应与 `SolverResult.answers` 的 JSON 友好格式一致。

Fallback 只消费 `ProblemIR`、`QuestionGoal`、`VerifiedOutputsSummary`、gap reports 和已知 constraints。它不能把生成结果写回 `RuntimeContext`，不能生成 fake method checks，也不能覆盖 verified outputs。

### Orchestrator 决策流程

Fallback 的入口固定在 Orchestrator，而不是 Planner 内部。决策流程：

```text
family = FamilyRegistry.match(problem)
if family is None:
  -> Tier 3
  -> FamilyGapReport
  -> FallbackSolution

planner_result = planner.plan(...) with max_attempts
if planner_result failed after max_attempts:
  -> Tier 2
  -> MethodGapReport or planner_gap
  -> FallbackSolution

execution = executor.execute_plan(...)
answers = ResultBuilder.build(...)
if execution failed or required answers incomplete:
  -> Tier 2
  -> VerifiedOutputsSummary + MethodGapReport
  -> FallbackSolution

if fallback also failed:
  -> Tier 4
  -> status="failed"
```

其中 family miss 最早发生，不会进入受控 LLM Planner；planner/executor/result 失败则在已有 context 的基础上抽取 `VerifiedOutputsSummary` 后进入 fallback。

### Gap Report

Family 未命中时生成 `FamilyGapReport`，表示可能是新题型或 FamilySpec 缺失。

```python
FamilyGapReport(
    problem_id="...",
    pattern="...",
    problem_type="...",
    question_goal_types=["derive_point", "derive_minimum"],
    relation_patterns=["right_angle_equal_length", "weighted_path"],
    blocking_reason="no SolverFamilySpec matched pattern/problem_type",
)
```

Method/Planner 缺口生成 `MethodGapReport`：

```text
missing_method      # 没有 MethodSpec 能解决该 step goal / capability
missing_binding     # 有 method，但缺可见输入或 scope 不满足
method_not_suitable # 有 method，但前置条件不满足或语义不合适
execution_gap       # method 执行失败、多解/无解/check failed
```

Method gap 记录应包含：`family_id`、`question_id`、`step_goal_type`、`intent`、`missing_capability`、`method_candidates_considered`、`visible_type_counts`、`relation_refs`、`planner_attempt_id`、`validator/executor error`。

### FallbackSolution

Fallback 输出结构用于网页生成，不用于 Method Solver 验算：

```python
FallbackSolution(
    source="llm_fallback",
    verification_level="unverified",
    answers={...},
    solution_steps=[
        FallbackSolutionStep(
            id="s1",
            section="ii",
            title="构造辅助点",
            reasoning="...",
            calculation="...",
            conclusion="...",
            confidence="medium",
        )
    ],
    warnings=[
        "该解法由 LLM 兜底生成，尚未经过 Method Solver 全量验算"
    ],
    gap_reports=[...],
)
```

`FallbackSolution.answers` 必须与 `SolverResult.answers` 使用同一层级和序列化格式，即 `question_id -> answer_key -> JSON-friendly value`。这样 HTML 生成器可以统一处理 method result 与 fallback result。

Fallback prompt 使用独立 Jinja 模板，例如：

```text
internal/llm-prompts/fallback-system.jinja
internal/llm-prompts/fallback-user.jinja
```

这些模板与 Planner prompt 放在同一 `internal/llm-prompts/` 目录下，便于统一 review 和版本管理。

Fallback prompt 必须要求 LLM 输出结构化 `answers + solution_steps + assumptions + confidence`，并明确说明：不能声称 method/checks 已通过。

## Gap 日志与离线闭环

Gap 日志是运行时产物，不放在 git-tracked `internal/` 下。

本地开发推荐：

```text
server/logs/solver-gaps/YYYY-MM-DD.gaps.jsonl
```

实现时需要把 `server/logs/` 加入 `.gitignore`。线上环境优先写 stdout structured logging 或数据库/事件日志，由部署系统决定落盘。

单条 JSONL：

```json
{
  "event_type": "family_gap | method_gap | fallback_used",
  "run_id": "...",
  "problem_id": "...",
  "family_id": "...",
  "gap_type": "missing_method",
  "question_id": "iii",
  "step_goal_type": "weighted_path_triangle_transform",
  "intent": "construct auxiliary triangle for weighted path",
  "missing_capability": "weighted_path_triangle_transform_30_60",
  "method_candidates_considered": [],
  "visible_type_counts": {"Point": 8, "Line": 2, "Constraint": 4},
  "relation_refs": ["ProblemIR.data.relations[3]"],
  "planner_attempt_id": "attempt_2",
  "llm_provider": "deepseek",
  "model": "deepseek-v4-flash",
  "fallback_used": true,
  "user_visible_result": true,
  "verification_level": "unverified"
}
```

离线闭环：

```text
1. 收集 gaps.jsonl / SolveSession / fallback outputs
2. 按 family_id、gap_type、missing_capability、relation pattern 聚类
3. 判断是新增 FamilySpec、补 MethodSpec、补 PlanningSignal、扩展 method 输入，还是 ProblemIR 抽取缺失
4. 新增 method/spec/test 或 family spec
5. 将失败题加入 fixture + expected
6. 回归跑 solver，减少下一轮 fallback
```

## Implementation Phases

- Phase FB1：扩展 `SolverResult`，添加 `status="fallback"`、`verification_level`、`solution_source`、`fallback_solution`、`gap_reports`、`warnings`，默认值保持向后兼容；同时实现 `FamilyGapReport`、`MethodGapReport`、`VerifiedOutputsSummary`、`FallbackSolution` 数据模型。
- Phase FB2：实现 fallback prompt Jinja 模板、`FakeFallbackClient` 和 fallback JSON schema validation。`FakeFallbackClient` 独立于 `FakeLLMPlannerClient`，输出预设的 `FallbackSolution` JSON。
- Phase FB3：Orchestrator 在 family miss / method gap / execution gap 时调用 fallback；返回 `status="fallback"`。
- Phase FB4：实现 JSONL/stdout gap logging，本地日志写 `server/logs/solver-gaps/`。
- Phase FB5：接 DeepSeek 真实 fallback 联调；豆包复用同一 provider 配置。

这些阶段依赖 LLM provider/config 基础设施，但不依赖 `SlotBinder`、`PlanCompiler` 或受控 LLM Planner E2E，可以与受控 Planner 的 Phase C/D 并行推进。

## Test Plan

- Family miss：未知题型生成 `FamilyGapReport`，返回 `status="fallback"`，不直接 failed。
- Method gap：隐藏某个 required method，生成 `MethodGapReport` 和 fallback solution。
- Partial fallback：前缀 method steps 成功后失败，fallback 输入包含 `VerifiedOutputsSummary`，输出 `verification_level="partial"`。
- Fallback 不写 `RuntimeContext`，不生成 method checks，不覆盖 verified outputs。
- HTML 消费契约：`status="fallback"` 时可读取 `fallback_solution.solution_steps` 和 warnings。
- Gap logging：本地 JSONL 路径在 `server/logs/solver-gaps/`，stdout logging 可配置，日志不写入 git-tracked `internal/`。
- Fake fallback client 覆盖 schema 错误、低置信输出、LLM 调用失败。

## Assumptions

- `status="fallback"` 是新增状态，不复用 `status="ok"` 表达未验证输出。
- Fallback 目标是产品可用，不是数学验算；所有 fallback 输出都必须显式标记未验证或部分验证。
- Fallback 与受控 LLM Planner 共用 provider/config，但 prompt、schema、日志和验收独立。
- 多模态图片输入仍先进入 ProblemIR/DiagramIR 抽取，不直接进入 Fallback Solver。
- 实现 `status="fallback"` 与 fallback 元字段时，需要同步更新 `docs/method-solver-architecture.md` 的执行/结果语义。

