# 阶段一人工审查修复

2026-09-17。范围为产品题意流程的锁、版本隔离、人工修订幂等性及状态提示。使用独立 PostgreSQL 和录制响应验证，付费模型调用为 **0**。不修改数学契约、Files API 配置或 Solver 准入。

## 审查结论与修改

| 问题 | 核实与处理 |
|---|---|
| 所有任务领取竞争题意容量锁 | 确认。`acquire_execution` 仅在 `problem_understanding` 内获取 `understanding.execution_slots` 锁并计数；旧课题流程不受该锁阻塞。锁仍位于题目/任务行锁之前，保留并发容量的原子性。 |
| 迟到、已作废运行写入候选历史 | 确认。`proposed` 现在与 `adopt` 一样，在写入事务中调用 `guard`，校验运行状态、代次、完整来源和执行租约。原始响应及调用审计仍保存；有效运行中的越界 repair 仍可记录为未采用候选。 |
| 候选提交与幂等回执存在两个提交窗口 | 该判断不成立。`transaction()` 通过 ContextVar 复用外层连接，`Application.request()` 中的业务写入与幂等行原本就是同一事务。故障注入验证了候选、当前指针、事件与回执一起回滚。进一步把人工候选 ID 改为按请求身份稳定派生，复用事务回滚前已落盘的不可变产物；编译仍在数据库写事务之外。 |
| 任务 succeeded 容易被误读为题意已确认 | 保留“任务已处理”的原有语义。详情顶部独立显示解析、当前来源复核和题型匹配，不再把历史运行的 confirmed 再显示为当前结论。缺图、uncertain、代码能力缺口、只做校验和自动处理未完成确认均给出文字提示。测试断言这些任务可以 succeeded，但 `source_reviewed=false`、没有页面，且仍为 candidate_only。 |
| 任意部署使复核过期 | 需缩小表述。参与比较的是提取/复核代码、模板、Schema、表达目录、注册表、供应商和预算配置，不是所有产品/前端文件或部署版本。新增 `review_stale_reason`，对配置变化、来源/候选变化、运行未结束分别说明；不自动调用模型。 |
| Files 与 base64 批次可比性 | 保留限制。此次不改变图片传输配置，也不增加模型批次。后续性能比较必须记录并控制传输方式差异。 |

没有清理过去已存在的历史候选，避免改写不可变审计；新的迟到响应不会再进入候选历史。最终工作流结果仍可作为审计产物留存，不能越过 guard 更新当前候选。

## 验证证据

独立实例为 `understanding-p1-test`，目录 `/private/tmp/shuxueshuo-understanding-p1-20260917`，PostgreSQL 端口 55437，迁移版本 `0003_problem_understanding`。测试使用应用受限账号，没有用 skip 代替数据库验证。

| 检查 | 结果 |
|---|---|
| 定向测试：题意流程、状态投影、worker 并发 | [59 passed，0 skipped](review-fixes-targeted.xml) |
| 产品完整回归 | [190 passed，4 deselected，0 skipped](review-fixes-product.xml) |
| 前端相关测试 | 50 passed：`npm run test -- lib/product app/_components/understanding-workspace.test.tsx` |
| 前端类型、修改文件 lint、生产构建 | 全部通过 |
| 修改的题意模块和测试 Ruff、补丁空白检查 | 全部通过 |

上表的定向测试包含在产品完整回归内，不重复累加。4 项有意排除为 1 项 live 模型测试及 3 项需独立真实 RabbitMQ 的发布确认丢失、代理重启和 worker 强制中断测试；此次未重新验收真实消息代理故障行为。

关键断言：

- 在另一个 PostgreSQL 连接实际持有题意容量 advisory lock 时，旧课题任务仍可完成领取。
- 四个不同题目同时领取抽取任务，恰好三个成功，一个返回 `execution.capacity`。
- 人工修订、补图、新运行和取消后返回的迟到响应均保留原始审计，不增加旧运行候选，也不能覆盖当前候选。
- 在写入幂等行之前注入异常，确认数据库业务状态整体回滚；同键重试使用相同产物路径，仅形成一个候选；并发重复请求返回同一结果，同键不同内容返回 409。
- 有效运行的未采用候选和越界 repair 仍保留，恢复测试继续证明调用不重复发送。
- 七题冻结响应均可入库、查询；六题原记录为 confirmed，K 题缺图阻断不变。此项是持久化回放验收，不是新的模型通过率。
- 缺图、uncertain、code_gap、预算耗尽与仅代码校验的“任务成功”，均不产生解析页，也不被作为来源复核通过。
- 修改提取/复核配置使当前复核 stale 并返回原因；仅改变无关部署版本不使确认失效。

复现产品回归：

```sh
cd server
PRODUCT_TEST_DATA_DIR=/private/tmp/shuxueshuo-understanding-p1-20260917 PRODUCT_TEST_INSTANCE=understanding-p1-test RUN_LLM_INTEGRATION=0 uv run pytest -q tests/product -m 'not live_llm' --deselect=tests/product/test_transport.py::test_confirm_loss_republishes_and_stale_token_is_fenced --deselect=tests/product/test_transport.py::test_durable_queue_survives_native_broker_restart --deselect=tests/product/test_transport.py::test_killed_worker_recovers_with_new_epoch_without_duplicate_execution
```

## 本地服务与页面

本机 `local` 实例于 15:32（Asia/Shanghai）完成 worker、publisher、API、前端重启；无需新迁移。首次启动曾遇到前端端口占用，确认监听进程已退出后重试成功。最终 `services-doctor` 返回正常，四个进程版本一致、两项心跳正常、待发布消息及过期租约均为 0，未发现孤立产物。

部署指纹：`d07c62437676e3dbfe08c2ddb426825bc42ae4f2aedd39a2aae24da73231ec6e`。

浏览器只读核验当前南开题与函数量词题：完整原题文字和候选正常显示，顶部将解析、来源复核、题型匹配、处理结束分开显示；原本有效的复核在此次产品代码更新后仍有效。失效提示、待确认和代码能力缺口的文案由上述组件渲染测试覆盖，未为页面核验新增或修改日常题目数据。
