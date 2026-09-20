# 提交前全量回归记录

本轮删除了 `runtime_binding._bind_notation` 中按正方形、射线、路径权重推断 capability 并据此阻断准入的整段逻辑。绑定层继续使用已匹配 family、数学对象绑定和既有来源/前置检查契约，方法由 Planner 选择。回归用例验证在其他分问加入辅助射线不会改变绑定准入。

最终共 **3,998 项通过**：Solver 3,385、其余后端 295、前端 156、页面工具 162；非 Solver 后端 7 项跳过，Solver 26 项真实模型测试排除。详细统计见同目录 `acceptance.json`。Solver 使用仓库规定的 `full` profile：运行全部离线 generated gate 与回放，自动分开并行和串行测试，移除模型开关和 API key；当前没有标记为 serial 的用例。没有发起新付费模型调用。

## 本轮完整执行范围

| 范围 | 命令（在注明的目录执行） |
|---|---|
| Solver 全量离线 | `server`: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/run_solver_tests.py full -- --tb=short -ra` |
| 其余后端，包含全部产品测试 | 仓库根目录：`env PRODUCT_TEST_DATA_DIR=/private/tmp/shuxueshuo-stage-two-submit-20260917 PRODUCT_TEST_INSTANCE=stage-two-submit RUN_LLM_INTEGRATION=0 server/.venv/bin/python -m pytest -q server/tests --ignore=server/tests/solver --tb=short -ra` |
| 前端全部测试 | `frontend`: `npm test` |
| 页面工具全部测试 | 仓库根目录：`node --test tools/tests/*.test.mjs` |
| 前端静态检查与构建 | `frontend`: `npm run typecheck`、变更文件 ESLint、`npm run build` |
| 新增 Python 文件 | Ruff 检查通过 |
| 数学题意回放 | 五题人工样例和五题冻结真实候选，共 10 组；生成命令见 `README.md` |

非 Solver 后端跳过 7 项：1 项真实来源复核模型测试、3 项需要显式启用的专用 broker 测试、3 项需要 Docker/nginx 的测试。Solver 的 `live_llm` 用例由离线 profile 排除，不能将其计为通过。

产品测试在新建独立 PostgreSQL 17.10 实例 `stage-two-submit` 中运行，端口 55439，数据目录 `/private/tmp/shuxueshuo-stage-two-submit-20260917`。从空库安装至 `0004_math_runtime_binding`；没有部署至日常或生产实例。旧测试库中的历史租约任务会干扰有批量上限的恢复测试，因此最终完整后端回归使用全新库，没有修改恢复逻辑或放宽断言。

## 全量回归发现并修复的既有问题

| 问题 | 修复与校验边界 |
|---|---|
| `recorded-gold` 默认输入仍被当成外部 F2 目录读取 | 接通现有 `recorded_gold_input`，使用仓库题图与冻结 OCR 记录；新增无需外部目录的授权构建回归。 |
| 四份协议快照缺少运行时已支持的 `parameters` 字段 | 仅同步 schema 快照；没有切换生产 Planner 输入输出协议。 |
| 身份/状态失败录制的旧请求大小预算失效 | 变化来自已有可选 `parameters` schema 及结构化错误字段；新增当前回放预算，保留原始请求统计，并继续严格核对原始 system prompt 哈希。 |
| 教学快照将证明来源哈希误作固定教学内容 | 比较全部证据正文、种类和数量；允许运行授权 ID 变化。教学审阅正文与历史 fixture 完全相同。 |
| C0 机器基线未同步内部方法和证明来源 | 更新注册表/产物哈希及已有内部 `organize_expressions` 记录。29 张公开能力卡、录制 occurrence、合成场景、annotated-plan 哈希和各题计数不变；历史 `human-review-summary.json` 未修改，未声明新人工页面审阅。 |
| 视觉注册表测试只识别几何组件 | 同时检查已有文本视觉 binder 注册表，保留两类组件各自的注册校验。 |
| 旧 Review 工作流误将独立题意模块归为未知依赖 | 明确该模块由产品题意流程自己冻结版本；补充归属回归，保留未知资源的保守回退。 |
| 已提交页面文案与旧测试断言不一致 | 更新错题本文案断言；没有修改页面。 |
| 抽取提示词字节预算落后于已有数学状态规则 | 将固定上限从 12,500 更新为 13,500 字节，当前实测 13,351；没有修改生产提示词。 |

回放证据仍与当前产品准入分开。历史 `confirmed` 没有转换成当前有效复核；新检查必须由当前候选、来源及复核版本重新取得准入结果。
