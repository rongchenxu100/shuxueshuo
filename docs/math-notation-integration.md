# 数学题意、运行时绑定与 Method 参数

本文适用于内部产品工作台的 `problem_understanding` 与 FunctionalPlan 路径。学生拍题的 `graph_lesson` 契约见[图谱课程架构](graph-guided-interactive-lesson-design.md)。两条入口共享数学基础能力，但不能互换准入或来源复核证据。

## 候选与来源

`problem-math-notation/v1` 用 JSON 表达层次，用数学字符串表达条件与目标。`facts` 保存条件，`children` 限定局部作用域，目标不接受旧 `at` 字段。`original_text` 是原图转录，不从数学 IR 反向生成。

`problem_understanding/v1` 只处理来源和候选，不把抽取成功当作 Solver 就绪。保存修订执行结构和数学校验；复核才调用模型。补图建立新的完整有序来源版本，旧候选和旧复核不能冒充当前结果。

- `problem_source_versions`：不可变有序图片与哈希。
- `problem_candidates`：完整候选、来源、父候选及内容哈希。
- `extraction_runs`：冻结配置、运行代次与采用结果。
- `extraction_call_reservations`：调用预算预留、响应与用量回执。

产品入口为 `/api/product/v1` 下的 `source-versions`、`candidates`、`extraction-runs`；具体接口见 `server/shuxueshuo_server/product/understanding.py`。写操作使用幂等键和基准版本；迟到响应可以留作审计，不能覆盖新来源或候选。

## 校验、复核与修复

代码检查结构、数学语义和支持范围；原图复核检查转录和数学候选是否忠实。只有诊断授权的范围可以修订，完整返回不等于整份候选都可改写。复核不确定、缺图、能力缺口和技术失败分开保存，不能用任务 `succeeded` 替代题意确认。

流程、预算、停止与恢复契约见[数学记法修复](math-notation-repair-design.md)。CLI 文件存储和产品数据库存储共用 `run_workflow()`；调用期间不持有长数据库事务，结果未知时不能静默重发付费调用。

## 运行时绑定与求解准入

实现入口为 `problem_understanding/runtime_binding.py`、`runtime_lowering.py` 与 `compact_planner_input.py`。绑定在不改变原题的前提下生成 Solver 输入和状态来源；不可见、歧义或无法可靠绑定的输入阻断求解。

准入同时要求当前候选解析有效、当前来源复核有效、无缺图阻断、family 和适配器已注册、来源和状态绑定完整、源输入前提通过。`confirmed` 或 `matched` 不能单独放行。候选、来源、复核或绑定配置变化使旧检查失效；需要前序计算结果的 Method 前提仍在执行时检查。

| 接口 | 用途 |
| --- | --- |
| `POST /api/product/v1/problems/{id}/runtime-binding-runs` | 携带候选、来源版本和幂等键创建绑定检查 |
| `GET /api/product/v1/problems/{id}/runtime-binding-runs` | 分页历史 |
| `GET /api/product/v1/runtime-binding-runs/{run_id}` | 冻结输入、诊断与结果 |
| `GET /api/product/v1/problems/{id}/understanding` | 当前绑定状态、阻断原因和 `solver_ready` |

简洁 Planner 视图保留目标分问及祖先条件，`known_results` 只能使用同版本、已验证、当前可见的执行结果。首轮没有执行结果。题目视图、能力签名和内部 SourceRef 各自承担不同职责。

## Method 数学参数

首轮协议仍为 `functional-plan-content/v2`，修复协议仍为 `functional-scope-repair/v1`。数学表达式先绑定为既有内部引用，再沿用类型、Scope/Goal、依赖、状态、前提、返回和闭包校验；不另建执行语言。

`{step_id, return}` 保留确切前序结果身份。参数编码由调用配置明确选择 `source-ref` 或 `math-expression/v1`，不能按字符串内容猜测，也不能用表达式等价绕过 exact-result、归属或版本约束。等价归一化见[实现设计](math-notation-equivalence-normalization-design.md)。

## 维护与验证

Schema 位于 `internal/schemas/`，运行实现位于 `server/shuxueshuo_server/problem_understanding/`，产品接线位于 `server/shuxueshuo_server/product/`。接口和默认值以这些源文件为准。

冻结绑定输入位于 `server/tests/solver/fixtures/math-runtime-binding-stage-two/`。回归必须区分录制回放、当前产品准入和真实原图复核，不能把历史录制的 confirmed 提升为当前授权。测试分级见[Solver 测试策略](solver-test-strategy.md)。
