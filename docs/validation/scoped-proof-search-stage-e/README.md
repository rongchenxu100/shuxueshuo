# 阶段 E 验证记录

日期：2026-09-28。对应 [E 实施记录](../../scoped-proof-search-stage-e.md)。各组测试重叠，不相加。

| 验证 | 结果 | 记录 |
| --- | --- | --- |
| 完整离线 Solver | 4688 passed；429.90 秒；serial 组无选中项 | [offline-solver.log](offline-solver.log) |
| 最终 E 专项 | 17 passed；134.12 秒 | [stage-e-final.log](stage-e-final.log) |
| A/D/E 联合回归 | 74 passed；224.83 秒 | [focused-a-d-e.log](focused-a-d-e.log) |
| C 阶段兼容 | 29 passed；18.53 秒 | [stage-c-compat.log](stage-c-compat.log) |
| 冻结旧证书独立回放 | 166/166 | [legacy-replay-summary.json](legacy-replay-summary.json) |
| 冻结样本 / ProblemIR | 20/20 回放，10/10 一致 | [problem-ir-check.log](problem-ir-check.log) |

完整离线启动时 E 专项有 11 项，三个阶段 A 严格 xfail 已转成普通通过用例，并增加空条件绑定用例。之后补充变量改名与系数变化、应用记录篡改/旧界拒绝、根式界等价传递等四项测试，联合回归覆盖这些用例。随后仅补充常数缓存独立检查与全局耗尽诊断两项测试；最后一次 E 专项见 stage-e-final.log。最后的兼容收口为：只有显式 scoped-facts/v2 才安装新 Method 会话，已有默认 v1 的内部 proof_facts 入口保持原执行行为；C 兼容组及最终 E 专项在此修改后执行。

q30 使用冻结 ProblemIR 与 authored plan，真实执行五次 Method，检查准确消费边、最终答案 4、三条累计取等要求、实际共享读取及 checkpoint 恢复。测试禁止旧搜索；随后禁止所有搜索，独立回放事实快照和恢复完整执行。压缩的 [q30 事实与执行快照](q30-verified-proof-snapshot.json.gz) 保存调用权限绑定、完整生产证书、实际读取、取等要求和执行依赖图；它不是新的题面授权来源。原始权限仍须从冻结 ProblemIR 与已编译调用重建。

q12/q25 走新会话验证换元；q12 的 M07→M08 记录检查实际 producer 依赖，且共享依赖不含 AM-GM。q30/q29/q01 通过真实执行证据构建教学、VisualStepIR 与 HTML，检查无视觉绑定缺口，q30 维持七个学生步骤。不调用真实 Lesson/Planner LLM，不启动浏览器。

旧存档中的两个外层 witness driver 仍由 D 回放工具标作 deferred，未谎报为旧存档工具已覆盖；E 的 q30/q12/q25/q29/q01 真正执行 M13，并独立恢复 q30 的完整结果，覆盖了新会话见证入口。

首次回归暴露了误将新应用契约用于新生成的 v1 证据的问题，已限制为显式 v2；[初次日志](initial-offline-failures.log.gz) 保留拒绝及教学兼容失败。q29 根式写法不一致造成的无关归约搜索另保留在 [初次 q29 日志](initial-q29-failure.log.gz)，以独立恒等证书传递界后通过。本轮不把这些失败抹去，也不以扩大全局额度作为修复。

复现（仓库根目录；不产生付费调用）：

```sh
server/.venv/bin/python -m pytest -q server/tests/solver/test_scoped_proof_search_stage_e.py
server/.venv/bin/python -m pytest -q server/tests/solver/test_scoped_proof_search_stage_a.py server/tests/solver/test_scoped_proof_search_stage_d.py
server/.venv/bin/python -m pytest -q server/tests/solver/test_scoped_proof_facts_stage_c.py server/tests/solver/test_scoped_proof_facts_review.py
server/.venv/bin/python server/tools/proof_search_stage_d.py --replay-saved docs/validation/scoped-proof-search-stage-d
server/.venv/bin/python server/tools/build_basic_inequality_problem_ir.py --check
cd server
.venv/bin/python tools/run_solver_tests.py full --workers 4
```

新代码的静态检查通过；既有文件全量 Ruff 存在 59 条原有告警，本次差异行没有新增告警，未顺手修改这些无关代码。运行过程中机器还在执行其他离线测试，耗时仅作观察，不与旧样本宣称性能提升。


## Code review 修订验证

- [相关回归](review-regressions.log)：238 passed，295.04 秒，覆盖 E（26 项）、A、D、C、5C、B 及测试分组。
- [新增边界回归](review-boundaries.log)：9 passed，17 deselected，覆盖空检查点/协议不匹配、未注册及复合调用、缺 overlay 的实际执行拒绝、符号身份与稳定选择、来源定位及篡改拒绝。
- [最后补充的旧应用记录兼容断言](review-origin-compat.log)：1 passed，25 deselected。没有 local_rule_origin 的既有 application/v1 记录仍可独立回放，新增字段被改写则拒绝。
- 原先的 4688 项全量离线记录属于审查前；本次没有把旧日志标成重新跑过的全量结果。

q30 实际恢复断言为 5 次 restore，前缀长度依次为 1、2、3、4、5；取消第 6 次完整恢复，共重放 15 个提交，仍未实现增量追加。reuse 记录按本调用的 fact ID 去重：first 从 11 条变为 4 条，last 从 7 条变为 4 条；不能据此宣称依赖集合已是最终应用的最小集合。

[审查后的 q30 快照](q30-review-proof-snapshot.json.gz) 与原快照并存。新来源字段记录参与项所在具体行，规则本身仍由 Method 显式构造并经 checker 检查。原记录不含此可选字段时继续兼容。

初次边界回归有一条测试断言查错了日志位置：RecordedClient 在重试时重复初始计划，最终 result 只显示第三次修复协议错误；实际缺 overlay 的拒绝已经写在第一轮 blockers 中。测试改为检查第一轮 blockers，保留 [初次断言失败日志](review-initial-assertion-failure.log)，没有放宽拒绝行为。

`implementation-sha256.json` 对应前一轮审查修订代码；原指纹保存在 `implementation-pre-review-sha256.json`。复现命令沿用上文，并加入 `test_basic_inequality_stage5c.py`、`test_proof_checker_stage_b.py`、`test_solver_test_profiles.py` 可覆盖本次 238 项。


## 补充审查：后端登记与来源必填

- 本轮实现指纹单独保存为 `implementation-backend-origin-sha256.json`，历史版本指纹不覆盖。
- 验证命令（`server` 目录）：`.venv/bin/python -m pytest -q tests/solver/test_scoped_proof_search_stage_e.py tests/solver/test_invocation_executor.py --disable-warnings`。日志见 `backend-origin-review.log`：**38 passed，134.99 秒**。
- 覆盖 v2 下真实几何双 invocation、二次函数执行、未知后端拒绝、混合后端复合调用拒绝、缺 overlay 拒绝、M11 新发布必填来源、旧应用记录独立回放兼容，以及原 E 链路回归。
- 初次运行在测试更新前已收集旧断言，未知后端的新诊断与旧的“single-Method proof adapter”文案断言不匹配（21 passed，1 failed）。将未知后端与复合调用分开测试后重新运行；未为通过断言放宽运行时检查。
- C/D/E 历史日志（含压缩的初次失败日志）与性能 profile 仅规范化本机路径，测试结果、计时和调用数不变；数学证书未改写。
