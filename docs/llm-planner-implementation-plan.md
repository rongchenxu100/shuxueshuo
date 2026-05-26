# LLM Planner 实现计划

## Summary

实现受控 LLM Planner，全链路从 `PlannerInputs` 生成 `ContextDeclaration[] + StepPlan[]`，不再通过 deterministic planner 编译 `MethodInvocation`。首版使用一次 LLM 调用输出完整 planner draft：declarations + steps + method_id + binding candidate ids；repair loop 再进行后续调用。默认真实 provider 为 DeepSeek OpenAI-compatible API；豆包 Ark provider 首版只做文本模式，多模态留给 ProblemIR 抽取或独立 `MultimodalPlannerClient`，不混入 Planner payload。

method/family 不足时的用户可用降级输出、gap 日志和离线补齐链路独立设计，见 [llm-fallback-and-gap-system.md](llm-fallback-and-gap-system.md)。本文档只覆盖受控 LLM Planner：`PlannerInputs -> ContextDeclaration[] + StepPlan[] -> Executor`。

## Key Changes

### Provider 与配置

- 新增 `SolverRuntimeConfig`，不写入 `SolverFamilySpec`。它负责根据 `planner_mode / llm_provider` 构造 planner providers，再传给 `RuntimeOrchestrator`，避免 Orchestrator 内部理解 DeepSeek、豆包或 LLM 细节。
- 默认真实 provider：`deepseek`，默认模型：`deepseek-v4-flash`，默认 base URL：`https://api.deepseek.com`。注意 base URL 不带 `/v1`，只在需要代理或私有网关时用环境变量覆盖。
- 配置统一放在 `server/.env`，代码通过 `python-dotenv` 加载；`server/.env.example` 只保存占位示例，不提交真实 key。读取优先级为：CLI 参数 > 环境变量/`.env` > 代码默认值。
- 环境变量：`DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL / DEEPSEEK_MODEL`，豆包为 `DOUBAO_API_KEY / DOUBAO_BASE_URL / DOUBAO_MODEL`。豆包不区分文本模型和多模态模型，后续多模态也使用同一个 `DOUBAO_MODEL`。
- CLI 增加 `--planner deterministic|llm`、`--llm-provider fake|deepseek|doubao`、`--llm-model`；缺 key 时返回清晰错误，例如 `--planner llm requires DEEPSEEK_API_KEY`。
- DeepSeek/Doubao 均用 OpenAI SDK + `base_url`；Doubao 首版只实现文本 planner 调用，多模态接口不进入 `LLMPlannerClient.complete(payload)`。
- 后端依赖新增 `openai>=1.0` 和 `jinja2>=3.1`；`server/.env.example` 增加 DeepSeek/豆包占位配置，真实 `server/.env` 继续由 `.gitignore` 排除。

### Planner 数据结构

- 新增 `PlannerOutput`：`context_declarations: list[ContextDeclaration]`、`step_plans: list[StepPlan]`。
- 新增 `ContextDeclaration`，首版只允许声明 `PointRef`，字段为 `path/type/definition_intent/scope_id/source`；禁止 `coordinate/value/answer`。
- `GenericPlanner.plan(inputs)` 返回值从 `list[StepPlan]` 升级为 `PlannerOutput`。迁移期 Orchestrator 可以兼容旧返回值并包装成 `PlannerOutput(context_declarations=[], step_plans=plans)`，但所有 planner 必须在本次实现结束前统一到新协议。
- deterministic planner 也要适配新协议：南开/河西当前直接写 `RuntimeContext` 的占位声明应迁移为 `ContextDeclaration`，不再在 `plan()` 内直接修改 context。
- 新增 `SolveSession`，归 Orchestrator 管理，记录 attempt 摘要、errors、耗时、token usage、最终状态；不参与确定性执行。
- 保留 `PlannerMemory`，归 Planner 管理，记录 LLM raw response、parsed draft、binding choices、repair history；不写 `RuntimeContext`。

### LLM Planner 流程

- `PlanningPayloadBuilder` 从 `PlannerInputs` 生成 prompt payload：`family_spec`、question goals、planning signals、relation graph、visible paths、method candidates、slot options、previous errors；不暴露 expected answers。
- `family_spec` 是 Planner 的必需输入。理论上每道题都应命中一个 `SolverFamilySpec`，它向 planner 提供题型策略原则、relation patterns、method capability hints 和 result collection policy。
- `SlotBinder` 按 method input type、scope 可见性、relation roles 生成稳定 `SlotCandidate(candidate_id, path, type, scope_id, description)`；candidate_id 使用短 ID（如 `c_0`、`c_1`），由 `(method_id, input_name)` 下按 scope、type、path 排序生成，保证同一道题多次构建稳定。
- 一次 LLM 调用输出完整 draft：declarations + ordered steps；每个 step 包含 `step_id/scope_id/step_goal(object)/method_id/bindings/promote_to/depends_on/reason`。
- LLM bindings 只能引用 `SlotBinder` 给出的 candidate id、`@step.<step_id>.<output_key>` 或 `@declaration.<scope_id>.<name>`；不能手写 `ContextPath` 或裸值。
- `@step` 只能引用前序 step 中已经通过 `promote_to` 暴露的 output。首版不允许跨 step 直接读取未 promote 的 step temp；如果后续需要复用大量临时量，再单独设计可校验的 temp 引用协议。
- `@declaration` 只能引用同一 draft 的 `ContextDeclaration`，用于把 planner 声明的 `PointRef` 占位绑定到 method 输入。
- LLM 不生成 `$step.<step_id>.temp.<key>` 中间路径。`PlanCompiler` 根据 `MethodSpec.outputs` 自动生成 step temp output path；LLM 只声明哪些 method output key 需要 promote 到最终目标，例如 `{"intersection": "$question.ii.points.G"}`。
- `PlanCompiler` 将 draft 编译为 `StepPlan/MethodInvocation`，校验 step 依赖顺序、合法依赖链、依赖环、未知 candidate id、裸值和 promote 目标。
- `depends_on` 只存在于 LLM draft 中，用于 `AbstractPlanValidator` 做 DAG 与顺序检查。首版不新增到 `StepPlan` 模型；编译后 executor 仍按 `step_plans` 顺序确定性执行。
- `AbstractPlanValidator` 在 `PlanValidator` 前执行：前者校验 LLM 输出 schema、candidate id、依赖 DAG、禁止裸答案；后者校验编译后的 `ContextPath`、scope、类型、写入权限和 locked fact。

LLM step draft 示例：

```json
{
  "step_id": "derive_G",
  "scope_id": "ii_2",
  "step_goal": {
    "type": "derive_line_intersection",
    "target_path": "$question.ii.points.G",
    "value_type": "Point"
  },
  "method_id": "line_intersection_point",
  "bindings": {
    "p1": "c_0",
    "p2": "c_1",
    "p3": "c_2",
    "p4": "c_3",
    "target": "c_4"
  },
  "promote_to": {
    "intersection": "$question.ii.points.G"
  },
  "depends_on": ["derive_q2_parabola"],
  "reason": "G 是两条已确定直线的交点"
}
```

上面的 draft 编译成 `StepPlan` 时，`PlanCompiler` 自动生成 method output path，并把
`promote_to` 展开为 `promote_outputs`：

```python
MethodInvocation(
    invocation_id="derive_G.line_intersection_point",
    method_id="line_intersection_point",
    scope="derive_G",
    inputs={
        "p1": "$question.ii.points.M",
        "p2": "$question.ii.points.N",
        "p3": "$question.ii.points.D_prime",
        "p4": "$question.ii.points.F",
        "target": "$question.ii.points.G",
    },
    outputs={"intersection": "$step.derive_G.temp.intersection"},
)

StepPlan(
    step_id="derive_G",
    scope="ii_2",
    expected_outputs=["$question.ii.points.G"],
    promote_outputs={
        "$step.derive_G.temp.intersection": "$question.ii.points.G"
    },
)
```

### Orchestrator 执行序列

LLM Planner 接入后，Orchestrator 的执行顺序固定为：

```text
output = planner.plan(inputs)
validate_declarations(output.context_declarations, context)
apply_declarations(output.context_declarations, context)
validate_steps(output.step_plans, context, specs)
execution = executor.execute_plan(context, output.step_plans)
answers = ResultBuilder().build(context, execution, question_goals)
```

`apply_declarations` 只写未锁定 `PointRef` 占位，不计算坐标。若 declaration 校验失败，进入 repair loop；若 step 校验或执行失败，也进入 repair loop。

首版 repair 采用“整体重生成 plan”，实现简单且边界清晰。传给 LLM 的 payload 会包含 `successful_prefix` 摘要，提示前若干步骤已经通过，鼓励它保持成功前缀并修复失败 step 及其后续步骤。后续可再做增量修复。

每次 repair attempt 都必须从干净状态重建：

```text
context = ContextBuilder.build(problem)
context_inventory = ContextInventoryBuilder.build(context, specs)
planner_inputs.previous_errors = structured_errors
```

不做 declaration rollback。这样可以避免上一轮已经 apply 的旧占位污染下一轮 plan，也避免新 declaration 与旧未锁定占位发生名字冲突。

`successful_prefix` 只包含 draft 层面的摘要，例如 `step_id / method_id / bindings / promote_to`。它不包含执行结果，也不作为下一轮的事实来源；执行失败时的实际输出、check 和错误 detail 放入 `previous_errors` 的结构化上下文中。

### Loop 与记忆模块

在线求解包含三层 loop，每层只能读写自己的记忆对象。LLM 的规划记忆不能直接污染数学执行黑板。


| Loop                    | 负责人                   | 职责                                      | 记忆模块             | 是否参与确定性执行             |
| ----------------------- | --------------------- | --------------------------------------- | ---------------- | --------------------- |
| Orchestrator Solve Loop | `RuntimeOrchestrator` | 控制一次题目求解的生命周期、预算、失败状态                   | `SolveSession`   | 否，用于审计和回放             |
| Planner Repair Loop     | `LLMPlanner`          | 调 LLM 生成/修复 plan，保存 draft 与错误历史         | `PlannerMemory`  | 否，只有编译并校验后的 plan 才能执行 |
| Executor Step Loop      | `InvocationExecutor`  | 顺序执行 StepPlan 和 method，写入 typed outputs | `RuntimeContext` | 是，唯一数学黑板              |


`SolveSession` 记录一次求解的运行审计信息：

```python
SolveSession(
    problem_id="...",
    family_id="...",
    planner_mode="llm",
    llm_provider="deepseek",
    model="deepseek-v4-flash",
    attempts=[
        SolveAttempt(
            attempt_index=1,
            planner_input_summary={...},
            planner_output_summary={...},
            validation_errors=[],
            execution_errors=[],
            result_errors=[],
            token_usage={"prompt_tokens": 0, "completion_tokens": 0},
            duration_ms=0,
        )
    ],
    final_status="ok",
)
```

`PlannerMemory` 记录 LLM 规划过程：

```text
attempts[]
  - prompt_payload
  - raw_response
  - parsed_draft
  - selected_methods
  - selected_bindings
  - declarations
  - compile_errors
  - repair_reason
```

`RuntimeContext` 保存真正参与执行的 facts、constraints、Point/PointRef、step temp 和 promoted outputs。写入规则仍然是：step temp 默认不泄露；只有 `promote_outputs` 能写上层；locked fact 不能覆盖；sibling scope 不能互读。

**离线学习 loop 不在一次求解内。** 它读取 `SolveSession`、失败 drafts、failed checks、unsupported fixtures 和 human review notes，用于新增 method、补 MethodSpec、补 PlanningSignal、调整 FamilySpec 或增加 regression fixture。

### Prompt 模板与 Few-shot 检索

- Prompt 使用 Jinja 模板，不使用纯 `.md` 拼接。新增 `internal/llm-prompts/planner-system.jinja` 和 `internal/llm-prompts/planner-user.jinja`，分别保存 system 约束和用户侧 planner payload 渲染逻辑。
- JSON schema 由代码中的 draft schema / dataclass / pydantic model 生成，作为完整 schema 注入 Jinja 模板；不要在 prompt 中只给片段，避免 LLM 对字段、类型和禁止项理解不完整。
- 模板必须包含：完整 output JSON schema、`ContextPath` 格式说明、candidate id 绑定规则、`promote_to` 规则、禁止裸答案、禁止编造 path、repair 输出要求。
- Few-shot 不写死在 prompt 模板里。新增 plan example corpus，例如 `internal/llm-prompts/planner-examples/`，每个 example 带 metadata：`family_id`、`problem_type`、`question_goal_types`、`relation_patterns`、`method_sequence`、`gap_tags`。
- 首版不引入 BM25/embedding。规划时注入同 family 的全部 examples，最多 2-3 个；当 corpus 达到 10+ 个后，再引入规则/BM25 或 embedding 检索。
- few-shot example 必须去题号化、去 expected answer，只保留结构模式、候选绑定方式、declaration 方式和 method 组合方式。它是 planner 参考，不是答案 oracle。

### 迁移现有 LLM Slice

- `FakeLLMPlannerClient` 保留，但输出格式升级为完整 planner draft。
- `LLMStepDecompositionPlanner`、`AbstractStepPlanCompiler` 标记 deprecated；新 planner 稳定后删除。
- `nankai25_abstract_steps()` 可转为 Fake draft 的测试来源；few-shot 示例则进入动态检索 corpus，不直接写死进 prompt。
- 南开/河西 deterministic planners 保留为 golden oracle 和显式测试 fallback，不再作为 LLM compiler 内部实现。

### Repair Loop

- 首版预算简化为 `max_attempts=3`，表示一次求解最多 3 次 LLM 调用，总数包含初始规划和 repair。后续如果把 decompose / bind / repair 拆成多阶段调用，再恢复两级预算：`max_planner_attempts=3`、`max_repair_attempts_per_plan=2`。
- validation/execution/result errors 结构化传回 LLM payload，不传 Python traceback。
- error 内容包含 `step_id`、`invocation_id`、slot/input 名、错误码、可读 detail、相关 candidate/path。
- 真实 LLM API 调用失败时，LLM Planner 本身返回 structured planner error；用户可用 fallback 与 gap 记录由 [llm-fallback-and-gap-system.md](llm-fallback-and-gap-system.md) 定义。
- deterministic fallback 只用于已知 fixture 或测试场景，且必须显式 `allow_deterministic_fallback=true`。

## Implementation Phases

- Phase A：实现 `SolverRuntimeConfig`、DeepSeek/Doubao/Fake client 协议、CLI 参数和 provider 构造；Orchestrator 仍可走旧 planner 输出。
- Phase B：实现 `PlannerOutput`、`ContextDeclaration`、declaration validation/apply，并把 deterministic planner 占位逻辑迁移到 declaration 模式。
- Phase C：实现 `PlanningPayloadBuilder`、Jinja prompt 模板、完整 JSON schema 注入、同 family few-shot 注入、`SlotBinder`、`PlanCompiler`、`AbstractPlanValidator`。
- Phase D1：升级 Fake LLM 完整 draft，先跑通南开 E2E，不依赖真实 API。
- Phase D2：已跑通河西 controlled fake 与南开 alt-label fake E2E，验证 weighted path 与非 canonical 点名；alt-label 只在 fake LLM registry 中放开。
- Phase E：接 DeepSeek 真实联调、repair loop、structured error payload 和 token usage 记录。
- Phase F：接豆包 Ark 文本模式 provider 和 smoke test；多模态仍不进入 Planner。

## Test Plan

### Provider 与配置

- mock OpenAI SDK 验证 DeepSeek/Doubao base_url、model、api key、JSON parse、API error；配置从 `.env`/环境变量读取，CLI 参数可覆盖。
- CLI 缺 key、provider 不存在、fake provider 成功路径。
- token/cost tracking 写入 `SolveSession`，Fake 可返回固定 usage。

### Planner 核心

- `ContextDeclaration`：允许未锁定 `PointRef`，占位写入正确 scope；拒绝坐标、答案、覆盖 locked fact。
- `PlanningPayloadBuilder`：不含 expected answers；previous errors 是结构化对象，不含 traceback。
- `PlanningPayloadBuilder`：payload 必须包含 `family_spec`；若 family 未命中，则不进入受控 LLM Planner，交由 fallback/gap 系统处理。
- `SlotBinder`：候选按 type/scope 过滤；candidate_id 稳定；跨 sibling scope 不可见。
- `PlanCompiler`：未知 candidate id、裸路径、裸数值、依赖环失败；合法 step A 输出给 step B 输入时顺序保留。
- `PlanCompiler`：自动生成 `$step.<step_id>.temp.<output_key>`，LLM 只提供 `promote_to`。
- `PlannerMemory` 不写 `RuntimeContext`；`SolveSession` 只记录运行元信息。
- prompt 模板测试：Jinja 渲染后的 system/user prompt 包含完整 JSON schema、candidate id 绑定规则、禁止裸答案、禁止编造 ContextPath。
- few-shot 注入测试：同 family examples 会进入 prompt；超过数量上限时截断；examples 不包含 expected answer。

### E2E

- Fake LLM 完整 draft 跑通南开，答案与 expected JSON 一致，不调用 deterministic compiler。
- Fake LLM 完整 draft 跑通河西，答案与 expected JSON 一致，使用 weighted path 几何 methods，不再经 legacy step decomposition。
- Fake LLM 完整 draft 跑通 `tj-2026-nankai-yimo-25-alt-labels.json`，验证不依赖 canonical 点名；默认 deterministic 仍保持 unsupported。
- repair 测试：第一轮错误 binding，第二轮根据 structured error 修复后通过。
- `cd server && uv run pytest tests/solver -q` 全通过。
- 人工联调：`--planner llm --llm-provider deepseek` 跑南开、河西并输出 result JSON；豆包文本 provider 做 smoke test。

## Assumptions

- 首版 LLM Planner 使用一次调用生成完整 draft；如果 prompt 过长或质量不稳，后续再拆成 decompose/bind 两次调用。
- DeepSeek JSON 输出不假设强 schema 能力，依靠 JSON-only prompt、严格 validation 和 repair retry。
- 豆包多模态不进入本次 Planner payload；图片题面应先由 `ProblemIRExtractor` 转成结构化 `ProblemIR`。
- 默认 `solve_problem()` 仍 deterministic；LLM 通过 config/CLI 显式启用。
- 面向用户生成网页时的 LLM fallback 默认启用策略见 [llm-fallback-and-gap-system.md](llm-fallback-and-gap-system.md)；本文档不实现 fallback solver。
- 本次不实现学生版 `ExplanationBuilder`，也不移除 `enabled_problem_ids`。
