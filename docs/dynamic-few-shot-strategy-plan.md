# 动态 Few-shot Strategy Planner 方案

## Summary

本方案记录 Strategy Planner 的动态 few-shot 设计：从已验证的题库样例中选择相似题，把它们的 executable StepIntent 作为示例注入 prompt，帮助 LLM 学会 Method Solver 需要的最小可执行 step 粒度。

V1 先保持简单：

- few-shot JSON 不包含 `schema_version` 和 `source`。
- `example.scopes[].steps[]` 原样复制已验证 executable StepIntent 的 scope 分组和 steps，不新增字段、不改字段含义。
- 检索字段只保留 `retrieval.goal_types`。
- 顶层必须保留 `original_text`，作为未来向量搜索的核心文本。
- Prompt 首版只注入 1 个最相似 few-shot，避免完整 StepIntent 示例在多轮 retry 中放大 token 成本和注意力干扰。
- 生产链路允许命中当前题 `problem_id`；测试链路可使用固定虚构 few-shot 或显式排除当前题来验证泛化。

few-shot 不是新的题目事实源，也不是网页讲解稿。它是题库中“已验证可执行解题步骤”的 prompt 投影。

## ProblemIR 信息

当前 LLM ProblemIR 已经显式包含：

```text
problem_id
title
original_text
scopes
entities
facts
question_goals
```

这些信息在 few-shot 检索中的职责如下：

- `original_text`：未来向量搜索和文本相似度的主要输入，必须写入 few-shot 条目。
- `question_goals`：可辅助生成当前题的 `goal_types`，但不直接复制到 `retrieval` 之外。
- `entities / facts / scopes`：用于当前题 prompt 和后续结构特征检索；V1 不把它们拆成额外 retrieval 字段。
- `problem_id`：生产链路允许同题命中；测试链路可配置排除。
- `family_id`：从题库/FamilyRegistry 匹配结果写入 few-shot，用于第一层过滤。

V1 的 retrieval 只包含 `goal_types`，该字段由同步工具从 `example.scopes[].steps[].goal_type` 去重生成。如果未来需要更强检索，可以基于 `original_text` 做向量搜索，或由同步工具从 canonical ProblemIR 生成独立索引，而不是把大量检索元数据塞进 few-shot JSON。

## Key Changes

- **目录与数据定位**
  - 新增与 `internal/method-specs/` 同层的 few-shot 目录，建议路径为 `internal/few-shots/`。
  - few-shot 文件名与 solver fixture 命名保持一致，格式为 `<problem_id>.few-shot.json`，例如 `tj-2026-nankai-yimo-25.few-shot.json`。
  - `internal/few-shots/` 是题库的 Strategy Planner 投射层，不是人工临时 prompt 示例库。
  - 每新增一道经过验证的题目，题库中的 canonical ProblemIR 与 executable StepIntent 应同步投射到该目录。
  - 未来新增内部同步工具，例如 `tools/sync_strategy_few_shots.py`，从题库/solver golden 中生成 few-shot 条目。
  - Strategy prompt 只读取 `internal/few-shots/` 中已生成、已验证的条目；不要直接扫描 `internal/solver-fixtures/` 作为长期方案。

- **Few-shot 来源**
  - 首版生成来源只使用已验证的 `.llm.json + .executable-step-intents.json`。
  - 不使用网页讲解步骤、`expected-step-intents.json` 或未验证 DeepSeek 日志。
  - `example.scopes` 原样复制 executable StepIntent 中的 scope 分组；每个 scope 内的 `steps` 原样复制。
  - `retrieval.goal_types` 由同步工具从 `example.scopes[].steps[].goal_type` 去重生成，不手写维护。
  - 不新增 `student_method / strategy_note / avoid` 这类非 StepIntent 字段。
  - 不删除或改写原有 `strategy / reason / reads / creates / produces` 字段。

- **相似题选择**
  - 先按 `family_id` 过滤。
  - 再按 `retrieval.goal_types` 与当前题目标类型的重叠度排序。
  - 首版只注入 `top_k=1`，即一个最相似的完整 executable StepIntent 示例。
  - 即使 DeepSeek 支持长上下文，也不默认注入多个完整 few-shot；多轮 retry 时优先增加 `previous_attempts`，不要重复堆叠示例。
  - 后续只有在真实题型暴露“单例 few-shot 覆盖不足”时，再讨论是否扩展为 `top_k=2` 或按失败原因追加 targeted example。
  - 不使用 `recipe_hint / method_id` 做检索字段；它们只保留在 `example.scopes[].steps[]` 中，作为可执行步骤示例。
  - 不引入 BM25、embedding 或网络依赖；未来向量搜索优先使用 `original_text`。

- **生产与测试边界**
  - 生产链路不排除当前题 `problem_id`。如果题库中已有同题 verified few-shot，直接命中是合理的。
  - 测试链路可固定虚构 few-shot，或显式排除当前题，专门验证泛化能力。
  - 固定虚构 few-shot 只作为无同 family 样例时的兜底或测试工具，不作为生产默认入口。

- **与 ExplanationBuilder 的边界**
  - Strategy Planner few-shot 的 step 是 method/recipe 最小可执行颗粒度。
  - 学生最终看到的讲解步骤由后续 ExplanationBuilder 合并和改写。
  - few-shot 中的 `strategy / reason` 可以帮助 LLM 学习解题思路，但不替代最终讲解稿。

- **Prompt 区分当前题与示例题**
  - 当前待求解题目的 ProblemIR 必须单独放在 prompt 的“当前题目”区域。
  - few-shot 条目的 `original_text` 和 `example.scopes[].steps[]` 必须放在“示例题目”区域。
  - Prompt 文案必须明确：示例题的 `original_text` 只用于理解示例 steps 的背景，不是当前题条件，不能把示例题中的点名、事实或答案迁移到当前题。
  - 当前题的输出只能引用当前题 ProblemIR 中的 canonical handles，以及当前题 step 自己 `creates/produces` 的 handles。

## Few-shot JSON V1

```json
{
  "problem_id": "tj-2026-nankai-yimo-25",
  "family_id": "QuadraticPathMinimumSolver",
  "title": "南开 2026 一模第 25 题",
  "original_text": [
    "题目原文第 1 段",
    "题目原文第 2 段"
  ],
  "retrieval": {
    "goal_types": [
      "derive_axis_point",
      "derive_parabola",
      "derive_constructed_point",
      "reduce_path_expression",
      "straighten_broken_path",
      "derive_minimum_value",
      "derive_parameter",
      "derive_intersection"
    ]
  },
  "example": {
    "scopes": [
      {
        "scope_id": "i",
        "steps": [
          {
            "scope_id": "i",
            "step_id": "derive_axis_point",
            "recipe_hint": "quadratic_axis_from_relation",
            "goal_type": "derive_axis_point",
            "target": "求对称轴与 x 轴交点",
            "strategy": "利用二次函数系数关系先确定对称轴交点。",
            "reads": [
              "function:problem:parabola",
              "fact:problem:coefficient_relation"
            ],
            "creates": [],
            "produces": [
              {
                "handle": "fact:problem:D_coordinate_value",
                "valid_scope": "problem",
                "description": "点 D 的坐标，后续小问可复用。",
                "output_type": "Point"
              },
              {
                "handle": "answer:i.axis_point",
                "valid_scope": "i",
                "description": "第（Ⅰ）问点 D 的坐标答案。",
                "output_type": "Point"
              }
            ],
            "reason": "由 2a+b=0 可确定抛物线对称轴，因此可求出它与 x 轴的交点。"
          }
        ]
      }
    ]
  }
}
```

上例中的 step 只展示结构。实际 `example.scopes` 应从对应的 `.executable-step-intents.json` 原样复制，不做 flatten 或字段加工。

## 实体关联

- `family_id` 连接 FamilySpec，用于第一层检索过滤。
- `retrieval.goal_types` 连接当前题的 step 目标类型，用于相似题排序。
- `example.scopes[].steps[].scope_id` 保留原始分问层级，帮助 LLM 理解 step 所属问题、`valid_scope` 和跨 scope 复用。
- `example.scopes[].steps[].recipe_hint` 连接 recipe 或 method catalog，但不参与 V1 检索。
- `example.scopes[].steps[].reads / creates / produces` 使用 canonical Entity/Fact/Answer handle，帮助 LLM 学习规范引用。
- `original_text` 连接未来文本检索和向量检索。

## Test Plan

- **同步目录测试**
  - `internal/few-shots/` 中的条目能被轻量 validator 校验。
  - 每个 few-shot 条目都包含 `problem_id / family_id / original_text / retrieval.goal_types / example.scopes`。
  - `retrieval.goal_types` 必须等于 `example.scopes[].steps[].goal_type` 去重后的结果。
  - 条目不包含 `schema_version / source / expected / ContextPath / raw DeepSeek response`。

- **Selector 测试**
  - 同 family 样例优先于不同 family。
  - `retrieval.goal_types` 重叠分数排序稳定。
  - 生产配置允许当前 `problem_id` 命中。
  - 测试配置可显式排除当前 `problem_id`。
  - 无同 family 样例时回退固定虚构 few-shot。

- **Prompt 回归**
  - prompt 中注入的 `example.scopes[].steps[]` 与 few-shot JSON 原字段一致。
  - prompt 必须明确区分“当前待求解题目”和“few-shot 示例题目”；few-shot 的 `original_text` 只能作为示例背景，不能被当作当前题条件。
  - prompt 不额外插入非 StepIntent 字段。
  - prompt 保留 `strategy / reason`，但最终网页讲解仍由 ExplanationBuilder 处理。
  - 全量回归：

    ```bash
    cd server && uv run pytest tests/solver -q
    ```

## Assumptions

- 已验证 executable StepIntent fixture 是 few-shot 的唯一可信步骤来源。
- `internal/few-shots/` 是题库投射结果，不是新的题目事实源；题目事实仍来自 canonical ProblemIR。
- 动态 few-shot V1 只用 `family_id + goal_types` 做结构检索。
- 动态 few-shot V1 每次 prompt 只注入 1 个最相似样例。
- 生产链路允许命中同题 few-shot；测试链路可用虚构样例或排除同题来验证泛化。
- 后续如果引入向量搜索，优先使用 `original_text`，不要把向量检索所需元数据手工混入 few-shot JSON。
