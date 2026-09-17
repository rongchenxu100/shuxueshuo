# 阶段一产品持久化验收

2026-09-17。验收对象为题意保存、查询、补图与人工修订。只使用已冻结响应；付费模型调用为 **0**。

- [七题候选与完整运行记录](outputs.html)
- [机器可读结果](results.json)
- [代码、模板、注册表与配置冻结](freeze.json)
- [实现说明与 API](../../math-notation-stage-one-implementation.md)
- [人工审查修复与真实数据库回归](review-fixes.md)
- [空路径 repair 授权漏洞修复](repair-authority.md)

## 七题结果

输入来自 `internal/solver-runs/math-notation-state-facts-seven-20260917-094219` 的原图与 `workflow/calls/*/response.json`。通过产品 StageRunner、两阶段任务和独立 PostgreSQL 保存，再由产品查询接口读取。模型供应商在入口替换为无 SDK 的录制供应商，不存在自动回退。

| 题目 | 完整记录入库 | 来源复核 | 题型匹配 | 处理结果 |
|---|---|---|---|---|
| 和平一模 25 | 是 | confirmed | matched | 候选已复核 |
| 和平二模 25 | 是 | confirmed | matched | 候选已复核 |
| 河西一模 25 | 是 | confirmed | matched | 候选已复核 |
| 南开一模 25 | 是 | confirmed | matched | 候选已复核 |
| 西青一模 25 | 是 | confirmed | matched | 候选已复核 |
| K 倍四边形 | 是 | 缺图提前阻断 | unmatched | 待补图，完整候选保留 |
| 函数量词题 | 是 | confirmed | unmatched | 候选已复核，题型仍未支持 |

**持久化验收为 7/7，不能表述为七题数学语义全部通过。** 原真实批次仍为 6/7；K 题原有 k 的作用域及四边形声明差异保留。此次产品闭环不接收金标、答案或验收政策，不借入库流程修改这些差异。

共回放 13 个响应（7 extract、6 review）。报告中的 token 来自原冻结响应，产品账本中的耗时是本地回放耗时，不作为新的模型性能成绩。

七题产品回归所需的 13 份响应原文另存为受版本控制的 `server/tests/product/fixtures/math-notation-state-facts-seven-20260917/`，清单记录响应及图片哈希；图片复用既有七题 fixture。运行这些回归不依赖被 Git 忽略的原始批次目录。完整批次与本页链接的 `outputs.html`、`results.json` 和逐题 JSON 作为本地生成产物保留；提交范围为实现、测试 fixture、冻结清单和验收摘要及其 JUnit 证据。

切换到受版本控制的 fixture 后，已在同一独立 PostgreSQL 实例重新执行七题产品测试：[7 passed，34 deselected，0 skipped](portable-recordings.xml)。本次只更换离线数据读取位置，响应原文和图片均与原冻结批次一致。

## 数据库与回归

独立实例：`understanding-p1-test`，目录 `/private/tmp/shuxueshuo-understanding-p1-20260917`，端口 55437，PostgreSQL 17.10。从新实例实际执行迁移至 `0003_problem_understanding`，使用受限应用账号执行测试；没有跳过数据库测试。

| 验证 | 结果 | 证据 |
|---|---|---|
| 产品完整回归 | 160 passed；4 项有意未运行 | [JUnit](product-tests.xml) |
| 最终题意与数学记法回归 | 620 passed，7 个 live 用例排除；含 32 个 PostgreSQL 题意测试和 588 个数学/文件工作流测试 | [JUnit](understanding-and-notation-tests.xml) |
| 新候选不影响已有正式题意和页面 | 单独验证先生成旧页面，再保存、校验新候选；旧页面继续可读 | [JUnit](legacy-isolation-tests.xml) |
| 前端相关测试 | 41 passed | `npm run test -- lib/product app/_components/understanding-workspace.test.tsx` |
| 前端类型、修改文件 lint、构建 | 通过 | `npm run typecheck`、ESLint、`npm run build` |
| 新增后端文件静态检查、补丁检查 | 通过 | Ruff、`git diff --check` |

表中测试集合存在重叠，不累加为总数。产品完整回归未运行的 4 项是 1 个需真实付费模型的测试，以及 3 个需单独 RabbitMQ 测试环境授权的测试；不是 PostgreSQL 跳过。本轮任务/事务/重复投递/恢复门禁已在真实 PostgreSQL 上执行，未宣称重新验收实际消息代理。

覆盖的失败与恢复路径：

- 非法 JSON、Schema 错误、数学编译错误、review uncertain/非法响应、供应商失败、越界 repair、预算耗尽与无进展。
- 合法但未采用的候选和截断标记返回留存；人工解析失败仍保存，Schema 错误返回可定位路径。
- 人工修订、补图、图片顺序变化、复核配置变化撤销当前复核；兄弟运行与迟到响应不能覆盖新候选。
- 预留后中断、回执已写但数据库未登记、已登记未处理、阶段已完成但任务收尾未提交，均验证恢复行为；没有可靠回执时不重新发送。
- 并发预留只发送一次；每题内容/review/总调用预算及全局 3 个活动任务上限。
- 不可变触发器、应用账号权限、跨工作空间/题目访问、幂等写和版本冲突。
- 新旧入口隔离、全部有序图片绑定、请求无旧 OCR/金标/答案/特定缺图预期。

## 浏览器操作验收

在独立端口的前端构建和录制 API 上实际操作，未改动日常运行的开发服务器：

1. 原图与按分问组织的候选可读，六题复核状态和 K 题缺图状态正确显示。
2. 保存人工修订后刷新，候选和历史仍在，顶部变为“尚未复核”。
3. 切换历史候选，显示该版本原图并禁用直接改写历史内容。
4. 保存带 `t+` 的结构合法候选，页面显示解析失败而不是空白；点击 `/root/facts/6` 准确选中对应公式。
5. 上传独立空白测试补图，保存新来源，当前候选清空、历史保留；重新提取后当前结果自动更新，使用完整的两张图片。
6. 独立上传入口不自动启动旧完整生成。录制供应商故障时无有效候选，仍可展开完整失败响应与调用记录。

空白补图和供应商故障仅用于界面/存储操作验收，不参与七题语义评价。七题报告已重新绑定到各自冻结的单张原图；界面操作历史继续留在测试数据库中。

## 复现

需先按产品管理工具安装独立测试实例。下面命令均在 `server` 目录执行；不得改成日常或生产实例。

```sh
PRODUCT_TEST_DATA_DIR=/private/tmp/shuxueshuo-understanding-p1-20260917 PRODUCT_TEST_INSTANCE=understanding-p1-test RUN_LLM_INTEGRATION=0 uv run pytest -q tests/product/test_understanding.py

uv run python tools/replay_understanding_product.py --data-dir /private/tmp/shuxueshuo-understanding-p1-20260917 --instance understanding-p1-test --batch-dir ../internal/solver-runs/math-notation-state-facts-seven-20260917-094219 --report-dir ../docs/validation/math-notation-product-stage-one-20260917
```

本阶段未接入 Planner/Solver，未迁移或部署日常/生产实例。下一阶段按总计划完成运行时绑定与求解准入。
