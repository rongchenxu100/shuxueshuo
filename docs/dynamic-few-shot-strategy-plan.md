# FunctionalPlan 动态 Few-shot

## 目标

Few-shot 只教学可复用数学机制和 call dependency，不复制整题答案，也不是第二份题面事实源。唯一 wire schema 是 `functional_plan/v1`。

```text
authored FunctionalPlan fixture
  + mechanism extraction manifest
  + human annotation
  -> deterministic anonymous example
  -> validated selection index
  -> planner prompt
```

## 资产

- Source plan：`internal/functional-plan-fixtures/*.functional-plan.json`
- Extraction manifest：`internal/functional-few-shot-manifests/*.manifest.json`
- Prompt asset：`internal/functional-few-shots/*.functional-few-shot.json`
- Runtime：`server/shuxueshuo_server/solver/runtime/functional_few_shots.py`
- Synchronizer：`tools/sync_strategy_few_shots.py`

Manifest 选择 2–5 个 call 的依赖闭包，并声明 capability、goal value type、family/pack retrieval metadata、匿名化规则和 prompt-safe condition。

## 安全规则

- 不暴露 source problem id、原对象名、答案或 canonical typed ID。
- 匿名化后必须重新通过 FunctionalPlan parser 与 validator。
- 示例不能新增 source plan 中不存在的 fact 或 dependency。
- Prompt annotation 只说明用途、适用条件、关键思路和不适用情况。
- Retry 沿用同一 example selection，不因失败随机更换机制。

## 选择

优先级依次为：

1. same family + mechanism overlap；
2. capability/goal/fact overlap；
3. 显式 fallback mechanism。

选择不得读取 expected answer。没有安全匹配时允许不提供 few-shot。

## 同步与测试

```bash
cd server
uv run python ../tools/sync_strategy_few_shots.py
uv run pytest tests/solver/test_functional_few_shots.py -q
```

新增资产必须可确定性再生成，且 prompt safety、依赖闭包和 strict fixture 测试通过。
