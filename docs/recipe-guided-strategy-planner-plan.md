# Recipe-Guided Strategy Planner 实现计划

## Summary

增强当前 Strategy Planner probe，让 LLM 不只是输出合法 `StepIntent`，还尽量输出符合 family 期望的 **recipe/method 对齐步骤**。当前南开 25 已经进入“DeepSeek StepIntent -> RecipeTrialExecutor -> PlannerOutput -> runtime 求解”的竖切：命名继续使用 canonical handle，`strategy/description` 中出现中间答案值不判失败，但执行层只信任 `reads / creates / produces`、recipe/method spec 和 runtime checks。

核心约定：

- `goal_type` 表示“这一步要解决什么数学目标”，属于 family 级常见目标词表。
- `step_id` 表示“这一步在本次计划中的语义唯一标识”，只服务 debug、repair 和教学展示，不承担 recipe/method 匹配职责。
- `recipe_hint` 表示“这一步推荐用什么标准动作/能力解决”，优先从 `recipe_id` 中选择，其次从 `method_id` 中选择；如果都没有合适项，可以为 `null`。
- `recipe_hint` 在 StepIntent JSON Schema 中是可选字段，类型为 `string | null`。LLM 不确定时应留空，不要硬填一个不匹配的 method/recipe。
- `common_goal_types` 保留，暂不建设全局 goal type registry；等题型和样本积累后再从多个 family 中归纳全局词表。
- `strategy_principles` 保留，它是这类题的解题策略说明，是 LLM 规划步骤时必须看到的核心上下文。
- Prompt 阶段展示 family 全量能力菜单，不对当前题做 top-k 筛选；resolver/trial 阶段再基于 StepIntent 动态搜索、排序和尝试。

## 当前状态

- `StepRecipeSpec`、`method_ids`、`step_recipes`、`method_binding_rules` 已进入 `SolverFamilySpec`。
- `method_catalog` 由 family `method_ids` 全量生成；`recipe_catalog` 由 family `step_recipes` 全量生成。
- `RecipeExecutionSpecRegistry.from_family_spec()` 已替代南开专用 default；recipe 执行序列来自 family spec。
- `MethodBindingRuleRegistry.from_family_spec()` 已承接南开 path family 的 method input 绑定规则。
- `RecipeTrialExecutor` 已能读取固定 StepIntent fixture 和真实 DeepSeek 最终输出，编译为 `PlannerOutput` 并求出南开答案。
- 真实 DeepSeek probe 已跑通南开 canonical；该链路仍是 opt-in 测试，不是默认 `solve_problem()`。

## Key Changes

- 增强 `SolverFamilySpec`，新增 recipe 上下文：
  - 新增 prompt-facing `StepRecipeSpec`，字段固定为 `recipe_id / goal_type / title / description / method_ids / priority`。
  - `SolverFamilySpec` 增加 `step_recipes: tuple[StepRecipeSpec, ...]`。
  - `common_goal_types` 保留，作为当前 family 的高层目标词表；`goal_type` 优先从这里选择。
  - `strategy_principles` 保留，作为题型级解题策略，继续进入 prompt。
  - `method_capability_hints` 删除；method 能力摘要由 `method_ids -> MethodSpecRegistry` 生成。
  - 不新增 `recipe_capability_hints`；recipe 能力摘要由 `step_recipes` 生成。
  - `result_collection_policy` 删除；最终答案收集由 `ProblemIR.question_goals + ResultBuilder` 决定。
  - `relation_patterns` 不再进入 Strategy prompt；若后续 family matcher 需要，可作为内部匹配信号保留，不作为 LLM 读题材料。
  - 南开 path family 首批 recipe 只抽真正需要 recipe 的动作：`right_angle_equal_length_construct_and_select`、`two_moving_points_path_reduction`、`broken_path_straightening_and_select`、`path_minimum_by_straightened_distance`。
  - 单 method 足够清楚的步骤不抽 recipe，例如 `quadratic_axis_from_relation`、`quadratic_from_constraints`、`midpoint_point`、`parameter_from_segment_length`、`parameter_from_minimum_value`、`line_intersection_point`；LLM 可直接在 `recipe_hint` 中填对应 method_id。
  - `two_moving_points_path_reduction` 虽然当前只对应一个 method，但保留为 recipe，因为它是路径最值题的关键标准用法，承担“引导 LLM 选择几何降维范式”的作用。
  - 对路径最值 recipe 使用正面引导：将几何转化、折线拉直、两点距离最值标记为 `priority="preferred"`，并在 description 中展示首选解法范式。
  - `priority` 首版为可选 string，只允许 `preferred` 或缺省；prompt 中只对 `preferred` recipe 做明显标记，其他 recipe 不标记。
  - 不在 prompt-facing `StepRecipeSpec` 中放 `expected_reads / expected_creates / expected_produces`。这些字段容易被误解成跨题硬约束；后续若 resolver 需要输入输出匹配信号，单独设计内部 `RecipeMatcherSpec`，不进入 prompt。
  - 不把 `avoid_strategies` 放进 prompt-facing `StepRecipeSpec`。负面指令容易强化被禁止路线；首版只在 alignment check 中检测参数化求导等路线并记 warning。

- 调整 Strategy payload 和 prompt：
  - `StrategyPayloadBuilder` 将 `family_spec.step_recipes` 输出为 `recipe_catalog`，能力摘要中区分 `method_catalog` 与 `recipe_catalog`。
  - `method_catalog` 由 `FamilySpec.method_ids` 全量生成；不根据当前题目再筛 top-k。
  - `recipe_catalog` 由当前 family 的全部 `step_recipes` 全量生成；不根据当前题目再筛 top-k。
  - Prompt 中这两个 catalog 是“能力菜单”，让 LLM 选择 `recipe_hint`；真正的候选搜索、排序和 trial 留给后续 resolver/trial。
  - Prompt 明确：LLM 输出的 `StepIntent.goal_type` 应优先来自 `common_goal_types`。
  - Prompt 明确：LLM 输出的 `StepIntent.step_id` 应为语义化 snake_case，且在本次 plan 内唯一，例如 `derive_axis_point`、`derive_parabola_part_i`、`construct_and_select_N`。
  - Prompt 明确：LLM 输出的 `StepIntent.recipe_hint` 选择优先级为 `recipe_catalog[].recipe_id -> method_catalog[].method_id -> null`。
  - Prompt 明确：如果某个 method 出现在 recipe 的 `method_ids` 中，且当前 step 想完成的是完整解题动作，优先选择对应 `recipe_id`，不要只选择 recipe 内部的某个 method_id。
  - 如果 `recipe_hint` 命中 recipe，后续 resolver 优先按 recipe 展开；如果命中 method，按 single method 尝试；如果为空或未知，记录为能力缺口候选并按 `goal_type / reads / produces / strategy` 搜索。
  - 使用 canonical ProblemIR projection 作为题目事实源；不恢复 `visible_paths / planning_signals / ContextPath`。
  - 不增加“答案泄露强校验”；只在 debug report 中可选记录 `strategy/description` 是否包含 value-like 文本。

- Few-shot 改成 recipe 级示例：
  - 新增/调整 few-shot 示例为“同 family 的 StepIntent sequence”，展示 `reads / creates / produces` 和 recipe 风格步骤，不展示 method slot。
  - 首版不用 BM25/embedding；策略为“同 family 示例全部注入，最多 2 个”。
  - 当前只有南开可用时，不从南开本题抽完整步骤片段；改用抽象化、不同点名/不同条件的虚构简化场景，展示 recipe 模式而不是当前题答案。
  - 虚构 few-shot 可以使用语义占位 handle 或 clearly-fake handle，但必须遵守 `reads / creates / produces / recipe_hint` 结构，避免模型学习旧字段。
  - 示例重点用正面方式覆盖路径最值正确范式：`two_moving_points_path_reduction -> broken_path_straightening -> distance_minimum`。
  - 路径最值 few-shot 只展示模式，例如“双动点路径先降维为单动点折线路径，再折线拉直求最短距离”；不要复用南开 `D/M/N/E/G/F`、`DE=sqrt(2)*NG` 或南开最终问的完整步骤。

- 明确 recipe 抽取原则：
  - Recipe 不是普通步骤名字，而是稳定复用的解题动作单元。
  - 应抽 recipe 的场景：一个教学步骤天然包含多个 method；LLM 容易走偏但 family 有明确标准解法；有稳定输入关系模式；内部 method wiring 稳定；执行后能产出清楚的 Entity/Fact。
  - 不应抽 recipe 的场景：单个 method 已足够清楚；只是为了给 prompt 起好听名字；只在一道题中孤立出现；内部逻辑需要大量 case-by-case 判断。
  - 首版不在 prompt 中展示 recipe 状态分级。当前样本太少，`candidate / verified / core / deprecated` 没有足够区分度；首批进入 family 的 recipe 默认视为可展示菜单。
  - 等同 family 至少积累 3 道题后，再考虑内部引入 recipe 状态分级；`deprecated` recipe 应从 prompt 移除，而不是展示给 LLM。
  - 南开首批 recipe 判断：`right_angle_equal_length_construct_and_select` 与 `broken_path_straightening_and_select` 优先抽取，因为它们封装多个 method；`path_minimum_by_straightened_distance` 抽取，因为它连接拉直方案与距离最值；`two_moving_points_path_reduction` 虽是单 method，但作为关键标准用法保留，用于引导 LLM 不走参数化求导路线。
  - Recipe 的“通常读取什么、产出什么”若需要给 LLM 理解，写进自然语言 `description`；不要结构化成看似硬约束的 expected 字段。

- Validator 增加 recipe 质量检查：
  - 继续强校验 canonical handle。
  - 新增 `RecipeAlignmentReport`，不作为默认 fatal：统计 unknown `goal_type`、`recipe_hint` 命中类型、空 hint、unknown hint、命中 internal avoid pattern 的 step、缺失关键 recipe 的情况。
  - `step_id` 只校验语义化 snake_case 和 plan 内唯一性；同一个 `recipe_hint` 或 `method_id` 可以在不同 step 中重复出现。
  - `recipe_hint` 分类规则固定为：`recipe`、`method`、`null`、`unknown`。
  - `null/unknown` 不在 StepIntent schema 校验阶段阻断，但必须写入 debug report；若后续 candidate/resolver/trial 找不到可执行能力，再进入 repair 或 gap。
  - 对南开 probe 的测试可将关键 recipe 缺失设为失败，例如必须出现路径转化、折线拉直、最小值计算，而不能只出现参数化建函数求最值。
  - `strategy/description/reason` 中的数值只做 warning，不阻断。

- Debug artifact 增强：
  - `validation-report.json` 增加 recipe alignment 摘要。
  - DeepSeek probe 打印：step_count、covered goals、matched recipes、matched methods、null hints、unknown hints、unknown goal_types、avoid_pattern_hits。
  - 保留 raw response 和 parsed step intents，方便人工评估 prompt。

- Runtime 执行反馈增强：
  - candidate / recipe / execution / result errors 会压缩成 `previous_attempts`，下一轮要求 LLM 重新输出完整 plan。
  - 对代码可确定的错误，优先在 resolver 层修复或给出短错误码，例如 `missing_required_runtime_fact: minimum_expression`、`invalid_valid_scope`、`duplicate_point_coordinate_fact`。
  - `parameter_from_minimum_value` 必须读取可见的公共 `MinimumExpression` fact，不能跨 sibling 读取 `ii_1` 的最终最小值答案。
  - 参数 fact 命名如 `fact:ii_2:m_value`、`fact:ii_2:parameter_m_value` 都按 `ParameterValue` 处理；但 prompt 仍优先推荐简洁的 `<symbol>_value`。

## Test Plan

- 单元测试：
  - `StepRecipeSpec` 能序列化进 payload，且不包含 method input slot schema 或 `expected_reads / expected_creates / expected_produces`。
  - 南开 family 的 `recipe_catalog` 包含路径转化、折线拉直、最小值相关 recipe。
  - Recipe spec 不包含状态字段，也不在 prompt 中展示 `candidate / verified / core / deprecated`。
  - 路径最值相关 recipe 在 payload 中带 `priority="preferred"`。
  - 南开首批 recipe 中，直角等腰构造筛选、两动点路径降维、折线拉直并选择、拉直后距离最值必须出现；单 method 步骤不应被重复包装成 recipe。
  - Payload 中 `method_catalog` 等于 family `method_ids` 全量摘要，`recipe_catalog` 等于 family recipe 全量摘要，不做题内 top-k。
  - Payload 中保留 `strategy_principles`，并在 prompt 中可见。
  - FamilySpec payload 保留 `common_goal_types`，不再包含 `method_capability_hints / result_collection_policy`；`relation_patterns` 不进入 prompt。
  - Prompt 包含 recipe catalog、few-shot recipe 示例、preferred priority；不包含 ContextPath、ctx_N、visible_paths，也不包含 avoid strategies。
  - Prompt 渲染后能看到 recipe catalog 的 `recipe_id / title / description / method_ids / priority`，但看不到 method input slot schema。
  - Few-shot 路径最值示例使用虚构点名/条件，不包含南开本题完整 14 步，也不复用南开具体路径条件。
  - Prompt 和 schema 包含可选 `recipe_hint`，并说明它可取 recipe_id、method_id 或 null。
  - Validator 允许同一个 `recipe_hint` 多次出现，但要求 `step_id` 在同一 plan 内唯一。
  - Validator 接受自然语言中出现 `m=3` 这类 value-like 文本，但在 report 中记录 warning。
  - Recipe alignment 能识别：`recipe_hint` 命中 recipe、命中 method、null、unknown 四种情况；unknown `goal_type` 只记录 gap。
  - Recipe alignment 能识别：合法路径转化 step 命中 recipe；参数化求导路线命中 internal avoid pattern warning；缺失折线拉直 recipe 时报告失败。

- DeepSeek opt-in 测试：
  - 运行南开真实 probe，要求输出仍通过 canonical handle 校验。
  - 要求关键 recipe 覆盖：直角等腰构造/筛选、路径转化、折线拉直、最小值、反求参数、交点。
  - 要求 LLM 实际使用 recipe/method 菜单：至少 50% 的 steps 的 `recipe_hint` 非空，且至少 3 个 `recipe_hint` 命中 recipe 或 method。
  - 若 DeepSeek 仍输出 `parameterize_moving_points / formulate_path_expression / derive_minimum_expression` 这类路线，测试失败并写入 recipe alignment report。

- 回归：
  - 删除 `method_capability_hints / result_collection_policy` 后，现有 deterministic 南开、河西 E2E 仍通过，证明执行链路没有依赖这些 prompt-only 字段。
  - 默认 `cd server && uv run pytest tests/solver -q` 不访问网络且保持通过。
  - 可选真实联调命令保持：
    `cd server && RUN_LLM_INTEGRATION=1 RUN_DEEPSEEK_STRATEGY_PLANNER=1 uv run pytest tests/solver/test_deepseek_strategy_planner_nankai.py -q -s`

## Assumptions

- `strategy/description/reason` 是 LLM 草稿文本，后续 resolver/executor 不读取其中的数值作为事实值。
- Recipe 是 family 级“常用解题动作”；LLM 通过 `recipe_hint` 选择 recipe/method，也可以在没有匹配项时留空。
- `goal_type / step_id / recipe_hint` 三者不合并：`goal_type` 是高层数学目标，`step_id` 是语义唯一标识，`recipe_hint` 是标准动作/能力锚点。
- Prompt catalog 是 family 级菜单，不是当前题 top-k 检索结果；当前题动态筛选由后续 resolver/trial 完成。
- 当前阶段已经实现南开 canonical 的 Strategy Planner 到 runtime 答案竖切；下一步是扩展到河西/alt-label，并把 probe helper 收敛为正式 LLM provider，而不是继续增强旧 deterministic template。
- Few-shot 首版不做动态检索；等同 family 样例积累到 10 道以上再引入相似度检索。
