# Method Solver 当前架构

## 1. 总览

Method Solver 将 authenticated Bundle 转换为经过验证的 `SolverResult`。LLM 首轮使用
`functional-plan-content/v2`，需要修复时使用 `functional-scope-repair/v1`；代码组装的
canonical 执行计划是 `functional_plan/v2`：

```text
VerifiedSolverProblemBundle
→ ProblemPlanningContext + structural FamilyRegistry match
→ FunctionalPlan content provider
→ authority-bound canonical Plan assembly
→ typed reconciliation / binding
→ direct Function/Macro compiler
→ transactional execution
→ StateVersion commit
→ typed Goal verification / Scope Retry
→ goal-reachable PlannerOutput
→ InvocationExecutor
→ SolverResult
```

`StepPlan`、`MethodInvocation`、`PlannerOutput` 和 `InvocationExecutor` 是内部执行结构，不是 LLM 协议。

## 2. 事实源

- `internal/solver-fixtures/<problem_id>.json`：结构化题意，不包含答案或固定 method 链。
- `server/tests/solver/expected/*.expected.json`：测试答案 oracle。
- `internal/functional-plan-fixtures/*.functional-plan.json`：recorded FunctionalPlan。
- `internal/functional-few-shot-manifests/`：few-shot 抽取规则。
- `internal/functional-few-shots/`：prompt-safe mechanism examples。
- Python Method `SPEC`：method contract 事实源。
- `FunctionSpec / MacroSpec`：direct compiler contract。

生成 JSON、prompt catalog 和 batch payload 都是派生产物。

## 3. Family 与 Planner

生产 family admission 只使用结构化 `pattern/problem_type`。多 family 匹配必须 fail loud；精确 problem-id 路由只用于 deterministic debug provider。

- recorded provider 加载 authored FunctionalPlan，并走完整生产链；
- DeepSeek provider 输出 `functional-plan-content/v2`；Retry 输出完整 Scope replacement；
- planner 失败不回落其他 LLM 协议。

## 4. Typed reconciliation

每个公开参数必须解析为唯一身份类别：

- materialized state：精确 `StateVersionId`；
- condition：Condition identity；
- identity-only：`MathObjectId`；
- call-local：canonical producer + public return。

B1 负责 allocation，B2 负责 canonicalization/placement，B3 负责 logical/runtime destination finalization，B4 负责 retry version restore，B5b 负责 typed state read，C3 binding ledger 负责参数角色与 authority。

handle、StateSlot 字符串和 runtime path 不参与数学身份。

## 5. Direct compiler

Direct compiler 只消费 prepared typed call：

- Function 通过 `FunctionSpec.adapter` 映射 method inputs；
- Macro 以一个 canonical step 进入 compiler，内部执行图与 public returns 由 Registry 和 typed preparation 持有；
- exact/latest state 在编译前选定；
- return allocation 决定 output promotion；
-不搜索替代 capability，不按 reads 顺序或名称重选输入。

输出仍是 `StepPlan / MethodInvocation`，作为稳定 runtime 边界。

## 6. Transactional execution

canonical calls 按 typed DAG 执行。每个 call fork 当前 RuntimeContext：

1. 准备 binding 和 runtime snapshot；
2. 编译单个 Function/Macro；
3. 在 branch 中执行；
4. 校验 returns、closure、B1/B3 和 goal evidence；
5. 全部通过后原子提交。

失败 call 不留下 declaration、promotion 或 StateVersion；dependents 被 blocked，独立分支可以继续。

最终只聚合 required goal closure 中 verified calls，交给 Orchestrator 再执行得到公开 SolverResult。

## 7. Symbolic closure

参数求解 capability 使用 `SymbolicClosureSpec`。共享 runtime executor 负责 target identity、equations、branches、constraints、substitution、residual symbols 和 companion output validation。

只有 `unique` 且 runtime validated 的结果可提交。closure provenance 进入 Context、checkpoint、retry 和 Explanation。

## 8. Context 与 Retry

`planner-state-context/v2` 保存 typed runtime observations 和 committed checkpoints，不复用上一轮 RuntimeContext 数值。

Retry 输入使用 `functional-annotated-plan/v1`，在原 Plan 树上就地展示三态执行结果、完整
实际 runtime outputs、根诊断和 Scope 编辑权。LLM 对每个开放 Scope 返回完整
`scope_steps + direct Goals + answer_from`。Runtime 只恢复开放 Scope 外签名仍兼容的
verified calls，并验证：

- computation/state-effect identity；
- binding signature；
- StateVersion chain 与 scope；
- runtime destination；
- symbolic closure signature。

实际结果可作为 prompt-safe evidence，但不暴露 typed ids、runtime path 或 expected answer。

## 9. Explanation 与页面

Explanation 只消费 canonical、runtime verified、goal reachable calls 和 writes：

```text
transaction artifacts
→ ExplanationSnapshot
→ LessonIR
→ VisualStepIR
→ lesson page
```

presentation scope 可与 execution scope 不同；跨 scope 复用展示引用，不重复计算。

## 10. 新增 capability

1. 定义 Method 和 Python `SPEC`。
2. 增加 FunctionSpec 或 MacroSpec。
3. 声明 role、authority、cardinality、runtime target 和 returns。
4. 参数求解能力声明 closure contract。
5. 增加 method/direct compiler/transaction/retry/explanation 测试。
6. 更新 capability pack 和必要的 mechanism few-shot。

不得在通用 runtime 代码中按 problem id、考试名称、答案值或具体点名分支。

## 11. 验证

```bash
cd server
uv run pytest tests/solver/test_strategy_planner_functional_plan.py -q
uv run pytest tests/solver -q
```

真实 batch：

```bash
RUN_LLM_INTEGRATION=1 RUN_DEEPSEEK_STRATEGY_PLANNER=1 \
uv run python -m shuxueshuo_server.solver.deepseek_functional_batch \
  --case all --samples-per-case 3 --concurrency 3 --max-attempts 3
```

summary 必须按 semantic attempt 报告 Pass 1/Scope Retry 协议、transactional Context
authority、authoritative closure、direct compiler、耗时和 token。
