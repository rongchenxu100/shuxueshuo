# q08 真实 LLM 实验状态

2026-09-09：配置阻塞，**实际模型请求 0 次 / 计划 5 次**。

当前 worktree 没有 server/.env，环境也未提供 DEEPSEEK_API_KEY。默认 provider 为 recorded，按计划回退 DeepSeek 时现有配置层拒绝创建真实 client。未用模拟响应替代，未计算成功率。

| 批次 | 结果 |
|---|---|
| batch-20260909T023813697863Z | 首次配置预检失败，保留 prompt；没有模型响应 |
| batch-20260909T024126241200Z | 保存了结构化 blocked_configuration report；没有模型响应 |

给现有配置层提供可用 provider 后，运行 `python -m shuxueshuo_server.solver.expression_rewrite_experiment --live` 会创建新的时间戳批次，执行 5 次独立首轮请求。不要将密钥写入此报告或提交到仓库。

prompt 不含 q08 标准推导和极值答案。每次结果分别记录：协议解析、数学验证、通分显条件命中、前端生成，附原始响应、模型、耗时和 token usage。当前批次无这些数据，因此不能推断模型的自然输出方式或协议命中率。
