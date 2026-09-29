# F3 验证记录

实施边界见 [F3 实施记录](../../scoped-proof-search-stage-f3.md)。最终结果见实施记录；原始真实调用与修订后的冻结回放分别记录。

- `offline-initial.log`、`offline-second.log`：迁移早期失败，保留原归因；不代表最终版本。
- `offline-interrupted.log`：工作进程加载后节点计数实现发生变化，主动中断，不作验收结论。
- `offline-before-assertion-update.log`：4763 passed、2 failed；生产执行通过，旧测试假设要求简单数值代入消耗归约额度、要求可直接证明的 q12 必须产生额外共享读取。最终测试改为真实需要归约的恒等关系，并继续用 C 专项验证必须复用的情形。
- `offline-before-live-fixes.log`：首次完整迁移回归 4765 passed；此后真实观察发现的问题继续修复。
- `offline-final.log`：包含真实观察修复的最终完整离线 Solver：4772 passed，417.98 秒；serial 分组无选中用例。
- `exact-frozen-search.json`、`proofs/`：对 D 阶段原始归档中的准确上下文、请求和限额重新证明，166 个新搜索请求全部通过。`reprove_frozen.py` 可复现。两个外层 witness driver 由 Runtime 集成覆盖，不混入 166。
- `frozen-shadow-summary.json` 为真实修订前的 Method 重新捕获记录；`runtime-shadow-summary.json` / `frozen-shadow-final.log` 为修订后的重新捕获记录。M13 不再为能直接归约的等式生成平方辅助，请求数量相应变化，所以不用重新捕获代替上述准确 166 项验证。
- `new-replay.json`、`legacy-replay.json`：分别在禁止新旧搜索的条件下回放当前与 D 阶段归档，各 166 个请求成功。
- `cold-replay.json`：单独冻结授权下，旧 F2 q30 compact 归档在新进程恢复五次提交，禁止搜索；耗时仅作该次观察。
- `problem-ir-check.log`：20/20 冻结样本回放，10/10 ProblemIR 一致。

从仓库根目录复现（使用新的输出目录）：

```sh
server/.venv/bin/python server/tools/run_solver_tests.py full --workers 8
server/.venv/bin/python server/tools/proof_search_stage_d.py --output /tmp/f3-shadow-new
server/.venv/bin/python server/tools/proof_search_stage_d.py --replay-saved docs/validation/scoped-proof-search-stage-f3/proofs
server/.venv/bin/python server/tools/proof_search_stage_d.py --replay-saved docs/validation/scoped-proof-search-stage-d
server/.venv/bin/python server/tools/build_basic_inequality_problem_ir.py --check
```

历史搜索仅用于重建离线基线的精确上下文，使用当前 checker/计数实现。不能把其重新测得的计数当作阶段 A/D 当时的原始性能；原始记录保持不变。节点预算现在按实际前提依赖去重，相关计数也不能与旧口径直接作加速比。

未打开浏览器、未部署、未开放生产 Family。真实 Planner 观察与本地成本另表报告。

## 本轮真实观察与修复

- `live-original-summary.json`、`live-original-diagnostics.json`：原始 3 组各 3 attempts，全失败，合计 192,588 token。
- `live-requests-responses.json.gz`：全部请求、原始响应、供应方元数据及推理记录；不需要再次访问模型即可查验。
- `live-responses.json.gz`：测试使用的原始响应文本，未改写。修订后的三个回放测试均闭合；不得记作新的真实调用成功率。
- `live-artifact-manifest.json`：原始 849 个文件的相对路径、大小和 SHA；完整运行目录包含失败检查点及证明。该目录是本机忽略产物，轻量请求响应和确定性证明另随仓库保存。
- `live-kernel-failures.json`：原始 M12 上下文及平方非负失败请求，用于直接拒绝/接受回归。
- `live-fixes-tests.log`、`live-fixes-final-tests.log`、`fragment-fixes-tests.log`：修订中的失败记录，保留，不作最终通过凭据。
- `fragment-fixes-final-tests.log`：17 项通过，包含三个冻结真实响应集、来源缺失拒绝、历史取等与片段循环边界。
- `full-before-live-fixes.json`、`compact-before-live-fixes.json`：真实观察修订前的本地成本；最终数字使用 `full-benchmark.json`、`compact-benchmark.json`。
- `lesson-summary.json`：最终 authored 五调用准确消费链、回放与确定性 7 步 Lesson 编译通过，0 模型调用，无回退。耗时含并发干扰，不作为性能基准。
- `lint.json`：新增代码无 lint 问题；两个仅修改默认参数的既有文件仍有六条原有告警。

`live-snapshot-replay-tests.log` 另补三个冻结响应集的完整事实快照恢复，明确禁止搜索；实现和输入 hash 见 `implementation-sha256.json` / `exact-frozen-search.json`。
