# Scope-native C0-C5 可执行门禁

## 目标

Planner 的 scope、typed state、Goal replacement 与 symbolic closure 不能依赖真实 LLM 样本偶然发现。测试侧因此维护三层确定性门禁：

```text
10,000+ C0-C3 authority scenarios
512 Goal replacement scenarios
2,048 closure scenarios + 256 execution-to-retry scenarios
```

Reference model 只描述期望语义，不导入生产 placement、binding、retry 或 closure helper。Production adapter 使用当前协议和生产 service；LLM 由 scripted client 替代，不调用网络、OCR、提取模型或完整 Solver。

## 版本契约

```text
scope-native-c0-c5/v1
scope-native-goal-retry/v1
scope-native-gate-regressions/v1
```

旧 scenario ID、扁平 FunctionalPlan adapter 和 call 级 retry 维度不提供兼容。

## 阶段

- `C0`：Problem、Plan、Retry scope 树对齐，step 与 Goal owner 唯一。
- `C1`：词法可见性、producer DAG、sibling 隔离和 answer target。
- `C2`：前缀增量执行、失败传播和 runtime 结果等价。
- `C3`：F5-C typed binding、exact StateVersion 和 destination authority。
- `C4`：Goal 状态、frozen/editable step、checkpoint 和 repair 原子应用。
- `C5`：symbolic closure、provenance、answer gate 和最终 commit。

当前 wire probe 从 authenticated Bundle fixture 建立 `ProblemPlanningContext` 和 F5-C `ProblemPlanningBindingCatalog`，再编译 `functional-plan-content/v2` 并生成 Goal checkpoint。Goal repair gate 使用真实 `functional-goal-repair/v4`、restore 与 transaction。

## 生成维度

快速 authority 矩阵覆盖：

- root、parent-child、siblings、branched 和同 scope 多 Goal；
- initial、latest entity state、exact result、CallResult 和 sibling-invalid read；
- create、refinement、runtime-equivalent alias、conflict 和后续 transition；
- call result、state version、condition 和隐藏语义依赖；
- locked restore、provisional discard、version drift 和 closure checkpoint drift。

Goal repair 矩阵覆盖 valid、stale Plan、stale Context、缺少 editable Goal、越界 Goal、越界 scope、无效 answer producer 与 no-progress。C5 集成矩阵覆盖四种非唯一 closure、残余自由元、equation sources、stale repair 和 wire reorder。

## 历史回归

匿名 regression corpus 位于：

```text
server/tests/solver/fixtures/scope_native_gate_regressions/v1.json
```

它只保存最小语义维度和稳定 scenario ID，不保存真实 LLM response。新增 scope/version/retry 缺陷应先缩减为一个可重放场景，再修生产代码。

## 失败报告

失败输出至少包含：

```text
scenario_id / dimensions
minimal scope tree or minimized retry dimensions
calls and version edges
expected / actual
first mismatching authority
single-scenario replay command
```

重放入口：

```text
SCOPE_NATIVE_SCENARIO_ID
SCOPE_NATIVE_RETRY_SCENARIO_ID
SCOPE_NATIVE_C5_SCENARIO_ID
```

## 门禁命令

```bash
cd server
uv run pytest \
  tests/solver/test_scope_native_c0_c5_oracle.py \
  tests/solver/test_scope_native_c0_c5_generated_gate.py \
  tests/solver/test_scope_native_goal_retry_generated_gate.py \
  tests/solver/test_symbolic_closure_generated_gate.py -q
```

完成条件：C0-C3 mismatch、Goal repair mismatch、scope tree drift、solved Goal reexecution、ghost write 和未分类错误均为零；stale revision/source/destination mutation 必须 fail loud。
