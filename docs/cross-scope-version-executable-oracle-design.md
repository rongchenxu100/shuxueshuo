# 跨 Scope / StateVersion 可执行 Oracle

## 目标

真实 LLM 会随机改变 call 顺序、scope、alias、版本链和 retry 图。基础语义不能依赖真实样本偶然发现，因此测试侧维护一个不导入生产 allocation/placement/read helper 的 reference model。

```text
CrossScopeVersionScenario
  -> ReferenceScopeVersionModel
  -> expected outcome

CrossScopeVersionScenario
  -> production stage adapters
  -> actual outcome
```

两者按第一个发生分歧的 authority stage 报错。

## 覆盖语义

- parent/child/sibling visibility；
- exact/latest/identity-only/CallResult read；
- create/reuse/transition/isolated/conflict；
- canonical call identity、LCA placement 与 unsafe split；
- previous/source StateVersion chain；
- logical writer 与 runtime destination ledger；
- committed restore、provisional replacement 与 repair cone；
- logical graph order、failed root 与 blocked dependent；
- closure checkpoint semantic signature。
- scope-native SemanticRef到唯一前序producer、显式CallResult和多producer歧义；
- scope-local answer规范化、Goal子图repair cone与pre-runtime reconciliation checkpoint。

## 独立性

Reference model 位于 `tests/solver/support`，禁止导入生产的 allocation、placement、visibility、state-read 或 retry helper。Adapter 只能把 scenario 转成生产 service 输入，不能复制 reference 判断或补齐缺失 typed identity。

## 场景生成

门禁使用固定 seed 和版本化生成配置：

- 至少 8,000 个 bounded combinations；
- 至少 2,000 个 expanded graphs；
- 历史缺陷的匿名最小 corpus；
- scope/call/object rename、wire reorder、dead branch 等 metamorphic 变换。

场景必须均衡覆盖多 scope topology 和全部 read mode。禁止通过前缀截断让某一维度空转。

## 比较规则

- B1：allocation action、selected/previous/source version、blocked/eliminated。
- B2：canonical owner、execution/return scope、materialized read。
- B3：writer/destination 集合与双向 issue category。
- B4：committed restore、provisional 不恢复、version/closure signature。
- B5：exact/latest typed read 与 visibility。
- C0：edge kind、canonical order、root failure 与 blocked set。
- F5-F adapter：PlanningContext visibility、F5-C source authority、pre-runtime/runtime-verified状态、冻结call集合、blocked suffix与Goal repair cone。

后续 stage 只在前序 authority 接受 scenario 时比较；dependent blocking 是独立 lifecycle probe，即使 B3 拒绝也必须验证。

## 失败报告

```text
scenario_id / seed / dimensions
minimal scope tree
calls and version edges
expected / actual
first mismatching authority
replay command
```

自动 reducer 只用于诊断；确认后的最小场景才进入版本化 corpus。

## 门禁

```bash
cd server
uv run pytest \
  tests/solver/test_cross_scope_version_oracle.py \
  tests/solver/test_cross_scope_version_generated_gate.py -q
```

新增 scope/version/retry 缺陷必须先匿名化进入该 oracle，再修生产实现。该模型是测试 oracle，不进入生产包。

C5 symbolic closure不是C0.5的替代品：C0.5负责scope、版本、依赖、增量lifecycle和retry authority，C5负责数学闭合与closure checkpoint。F5-F必须让两套门禁都经过v2 adapter。Reference model要区分`pre_runtime_verified / runtime_verified / failed / blocked`，并验证失败call只阻断其后代、独立Goal继续、补丁只使语义依赖后代失效以及最终commit前Context write为0。高层macro内部状态可以隐藏于Planner wire，但其closure、实际残余自由元与provenance仍需由C5观察。
