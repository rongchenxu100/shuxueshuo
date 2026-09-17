# 阶段二：数学题意运行时绑定与求解准入

2026-09-17。已实现并完成独立测试库验收。[五题审阅与十组回放报告](validation/math-runtime-binding-stage-two-20260917/README.md)包含代码生成的完整 JSON 和执行证据。

原则保持为：**JSON 组织结构，数学表达式承载语义，代码负责运行时绑定。** 不增加 `optimizations`。本阶段没有切换生产 Planner 请求或输出协议，没有实现新步骤 JSON 编译器，没有新增付费模型批次，也没有部署或迁移日常实例。

## 实现

`problem_understanding/runtime_binding.py::bind_notation()` 复用数学编译器、领域投影器、ContextBuilder 和状态绑定目录。适配器按四个已注册 family 取得绑定实现，将数学表达转换为运行时对象和引用。输入只来自当前候选；旧 fixture 不进入生产适配器。

`NotationRuntimeBundle` 与旧 `VerifiedSolverProblemBundle` 实现共同的 `SolverProblemBundle` 接口。新路径建立独立的候选、来源及准入授权，不创建旧 `VerifiedProblem`。单纯调用绑定函数不能得到可执行授权；产品内部的 `RuntimeBindings.authority(run_id)` 必须重新验证当前准入结果，随后才可交给已有 `RuntimeOrchestrator.solve_verified()`。检查按钮不会调用该求解入口。

来源映射保存候选版本、来源版本、原 JSON pointer、所属作用域、派生规则和成立前提。初始状态与派生条件另有 `initial-state-source-map.json`；运行后的 `execution-audit.json` 包含实际方法输入、提交状态版本、绑定账本和逐目标答案。河西Ⅲ的 `n` 来自轴上动点坐标，`y_M` 是坐标别名，`b` 保留为数学参数；`free_parameters` 仍由受信计划表达。

`min(S)=k` 与 `S=min(S)` 产生不同的运行时条件。坐标目标需要取等状态时，缺少后者会被阻断。不能绑定的额外坐标约束、独立使用的坐标别名、多运动变量或未知几何结构会返回诊断。交点排除已知根须有可见的非重根证明；正方形对角线交点的推导携带正方形前提。所有读取继续使用祖先作用域策略。

绑定层只转换数学表达、解析引用并验证既有契约。方法选择由 Planner 负责，Method 前提在约定的执行阶段检查。已删除按正方形、射线、权重猜测 capability 的整段启发式及其额外准入门禁；family 注册检查、源输入要求、来源授权与既有前置检查继续生效。

旧领域题意的来源记录在列表转换为映射前检查重复 `unit_id`，即使两条内容完全相同也拒绝；来源投影审计与 Planner 上下文共享该检查。Planner 继续返回 `planner.problem_planning_projection_drift`，不允许静默覆盖来源记录。

## 产品准入

迁移 `0004_math_runtime_binding` 新增独立 `runtime_binding_runs`、不可变输入/终态约束、同题复合外键、活动任务唯一索引及题目的最新检查指针。检查复用原有 build、worker、幂等请求、私有 artifacts、任务事件和执行代次保护，只有一个 `binding` 阶段。

接口统一位于 `/api/product/v1`：

| 接口 | 行为 |
|---|---|
| `POST /problems/{id}/runtime-binding-runs` | `Idempotency-Key` 请求头；JSON 包含 `candidate_id`、`source_version_id`；返回 202 和 run/build/job ID |
| `GET /problems/{id}/runtime-binding-runs` | 分页历史，支持 `limit`、`before` |
| `GET /runtime-binding-runs/{run_id}` | 冻结输入、配置、结果、诊断与私有产物引用 |
| `GET /problems/{id}/understanding` | 增加 `binding_status`、当前 `solver_ready`、`blocking_reasons`、`latest_binding_run` |

页面新增“检查求解条件／重新检查求解条件”和 JSON 产物入口，展示 `not_checked`、`checking`、`ready`、`blocked`、`stale`、`failed` 六种状态。检查失败可以重试；网络结果不明时沿用原请求及幂等键。

抽取与绑定允许同时活动，页面同时订阅两类任务的进度。“取消全部处理”对当前两类活动 build 都发起取消，某个请求失败也不会跳过另一个，并刷新显示剩余任务。两类任务各有独立的全局 3 个执行槽，使用数据库事务锁预留；取消或租约过期后释放槽位。绑定检查不占用抽取的槽位，正式页面任务也不受这两组锁阻塞。

准入同时要求解析有效、当前原图复核有效、无缺图等阻断、family 与适配器已注册、源输入与状态绑定完整、既有源输入前置检查通过。需要前序计算结果的 Method 前提仍由执行器检查。所有题图都经过完整性校验。

候选、来源、有效复核或绑定配置变化立即使旧结果过期。迟到执行只能进入历史，不能覆盖当前准入。检查不改变候选、抽取代次、原图复核记录或已有正式页面；历史抽取产物内的 `solver_ready` 不回写。`matched`、`confirmed` 均不能单独放行。

## 简洁输入与证据

`compact_planner_input.py` 生成全题与局部视图。首轮 `known_results: []`；局部视图保留目标分问、祖先条件，并只接受同版本的 `VerifiedFunctionalPlanExecution` 所提交的可见结果。坐标集保留全部分支。原文转录继续存于候选与来源复核，不重复进入数学题目段。

方法名、数学参数、可选性与返回值由执行能力注册表生成；`capability_math_signatures.py` 按能力 ID 提供数学前提说明，隐藏内部句柄、绑定指令和状态形式。这些签名是审阅产物，不是新步骤语言的执行规范。

五题每题都有旧输入、新输入、方法目录、逐条覆盖、状态和执行审计。覆盖链为原候选 → 编译对象/关系 → canonical input 与状态来源 → 简洁输入。新旧 JSON 使用相同序列化口径统计 Unicode 字符，题目段减少 **81.7%–84.2%**；该比例不代表整个请求。没有匹配 tokenizer 的测量结果，token 保持未测。

十份测试候选冻结在 `server/tests/solver/fixtures/math-runtime-binding-stage-two/`，附原始路径和内容哈希，测试不依赖被忽略的本地审阅目录。真实候选与原录制响应逐份核对相同。

## 验收

- 五题人工样例、五题冻结真实候选共 **10/10** 受信计划回放通过。逐目标比较标准答案及全部合法分支，核对方法输入、状态版本和来源作用域。
- **3,385 项 Solver 全量离线测试通过**，覆盖绑定、取等状态、比例错误、射线改直线、条件错问、不可见引用、变量歧义、交点不同性、改名、等价表达、辅助射线不干预方法选择与重复来源 ID，并回归旧领域题意、受信计划和全部 generated gate。26 项真实模型用例按离线 profile 排除。
- **其余后端 295 项通过、7 项跳过**，其中产品测试为 215 项通过、4 项跳过。覆盖检查幂等、并发请求、双任务取消、独立并发容量与槽位释放、修订/复核/来源变化、配置过期、迟到任务、跨工作空间、不可变历史及失败/检查点恢复。跳过项依赖真实模型、专用 broker 或 Docker/nginx。
- **前端 156 项、页面工具 162 项测试通过**，包含双任务取消与部分请求失败；前端类型检查、定向 ESLint 和生产构建通过。新增 Python 文件 Ruff 通过。
- 最终后端全量测试在新建独立 PostgreSQL 17.10 实例 `stage-two-submit` 从空库安装到 `0004_math_runtime_binding` 后运行。测试目录为 `/private/tmp/shuxueshuo-stage-two-submit-20260917`，端口 55439；日常实例与生产实例没有部署变更。

四组完整套件共 **3,998 项通过**。[全量回归记录](validation/math-runtime-binding-stage-two-20260917/full-suite-review.md)列明测试命令、跳过范围及本轮发现并修复的既有回归问题；[机器验收统计](validation/math-runtime-binding-stage-two-20260917/acceptance.json)保存精确计数。历史人工审阅和原始模型请求统计均保留。

冻结回放使用合成的测试授权，**不等同于当前产品准入**。产品测试重新建立受控的录制复核记录并运行真正的持久化检查；没有把历史 `confirmed` 提升成当前真实原图复核。K 题保留缺图及既有诊断，函数量词题仍可查询和审阅，保持 unmatched。

复现回放及生成审阅材料：

```bash
cd server
PYTHONPATH=. .venv/bin/python tools/replay_math_runtime_binding.py \
  --output ../docs/validation/math-runtime-binding-stage-two-20260917
```

阶段三继续负责新数学步骤协议、生产 Planner 切换、模型表现测量以及完整讲解/页面链路。
