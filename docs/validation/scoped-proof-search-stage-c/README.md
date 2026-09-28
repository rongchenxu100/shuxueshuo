# 阶段 C 验证记录

运行日期：2026-09-28。日志随仓库提交，不依赖本机临时目录。各组测试存在重叠，数量不能相加。

| 阶段 | 日志 | 结果 | 耗时 |
| --- | --- | --- | --- |
| 审查前完整离线 | [offline-solver-before-review.log](offline-solver-before-review.log) | 4622 passed、3 xfailed | 297.96 秒 |
| 审查前最终相关回归 | [focused-before-review.log](focused-before-review.log) | 215 passed | 116.08 秒 |
| 审查修复相关回归 | [review-focused.log](review-focused.log) | 94 passed | 63.43 秒 |
| 审查后完整离线 | [offline-solver-review.log](offline-solver-review.log) | 4631 passed、3 xfailed；串行组无选中测试 | 306.97 秒 |
| 最终阶段 C 与分组检查 | [review-final.log](review-final.log) | 68 passed | 32.54 秒 |

阶段 C 专项共 29 项（原实现 22 项、审查修复 7 项）。三个严格预期失败是阶段 A 冻结、留待 E 处理的既有样本。全量回归启动后，Retry 测试进一步加强为实际交换中间调用的线段端点；最终 68 项覆盖这一加强版本，期间未再修改 Runtime 实现。

仓库根目录复现命令：

```sh
# 完整离线 Solver（包括独立串行组）
server/.venv/bin/python server/tools/run_solver_tests.py full --workers 6

# 最终阶段 C 与分组检查
server/.venv/bin/python -m pytest -q server/tests/solver/test_scoped_proof_facts_stage_c.py server/tests/solver/test_scoped_proof_facts_review.py server/tests/solver/test_solver_test_profiles.py
```

相关回归另覆盖 Scope Retry、教学证据投影和教学快照。教学测试使用实际录制计划执行结果，分别启用空事实提交和有事实提交，验证快照与原路径一致；不 mock 数学证明。

新增模块 Ruff 检查和 `git diff --check` 通过。既有大型模块仍有存量 lint 告警，不宣称全仓 lint 清零。本阶段未调用真实 LLM、未进行浏览器检查或部署。
