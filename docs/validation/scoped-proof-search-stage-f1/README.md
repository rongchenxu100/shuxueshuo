# F1 验证与重复基准

日期：2026-09-28。实现说明见 [F1 实施记录](../../scoped-proof-search-stage-f1.md)。

## 计时口径

同机顺序运行；优化前、最终优化后各三次，每次新建 Runtime，均保留完整 debug 输出，不调用 LLM。使用冻结 q30 的 M01 → M11 → M12 → M11 → M13。普通冷回放是新事实库、空校验 memo，但与求解处于同一进程；另列独立进程冷回放。表中为秒，包含 Runtime 和调试输出成本，不能当作数学规则的单步耗时或 p95/SLA。

| 场景 | 基线中位数 | 最终中位数 | 基线范围 | 最终范围 |
|---|---:|---:|---|---|
| 整题（完整调试输出） | 33.092637 | 18.625681 | 32.962480–34.781527 | 18.335070–19.142250 |
| 新事实库冷回放 | 2.874651 | 1.201790 | 2.783996–2.924361 | 1.105269–1.566926 |
| 热校验 | 0.139321 | 0.000177 | 0.138784–0.247955 | 0.000168–0.000314 |
| Runtime Retry | 8.439422 | 1.460571 | 8.245832–9.744752 | 1.400717–1.868635 |
| 快照序列化 | 0.322871 | 0.029759 | 0.212259–0.512744 | 0.028081–0.029931 |

`baseline.json` 与 `optimized.json` 保存逐轮原值；`optimized-before-final-guard.json` 保留补充拒绝未验证元数据子类之前的首次优化测量。最终基准使用最终生产代码，未挑选单次最快结果。

三轮前后快照 hash 相同、大小均为 3,848,202 字节；没有修改数学结果、证书格式或删减调试产物。确定性重放次数：正常求解 25→5，Retry 15→5，普通冷回放始终 5，热校验始终 0。断言放在真实 q30 链路测试中；不可变元数据与热校验也有禁止重复解析、序列化的测试。

`cold-process.json` 是另开三个 Python 进程的检查时间，均禁用旧、新搜索，仍重放全部五个提交；不是前后对照实验，且不包含进程启动、模块导入与授权 fixture 构造时间。`q30-authority.json` 是从认证 Runtime 单独导出的受信测试授权（源前提、调用绑定、Scope），输出 hash 已从本次事务的 runtime_results/state_writes 独立重算核对；它是测试输入，绝不是生产回放从证书自建授权的新入口。待回放证书复用 E 的 `q30-review-proof-snapshot.json.gz`，所有 fixture 身份在指纹文件中记录。

## 测试

- `red.log`：首批性能/不可变性断言在原实现上 6 failed、2 passed。
- `regressions.log`：F1/E/D/A/C/C-review/B/5C/测试分组共 257 passed，202.61 秒。
- `final-boundaries.log`：最后增加拒绝可变叶子及未验证值类型子类后，F1 共 18 passed。
- `final-core.log`：最终 F1/D/C 共 82 passed，11.41 秒。
- `frozen-replay.log`：166 个已保存数学请求全部回放通过；原存档的 2 个 witness driver 独立列出，并非把它们算作本次失败或跳过实际见证（q30 M13 在 E 回归覆盖）。
- 修改的事实模型、事实库与 F1/E 专项测试 Ruff 通过，`git diff --check` 通过。

测试数有重叠，不相加。完整离线 Solver 回归和 F2/F3 不在本次完成范围。测试扩展期间一条 checker 更换的断言最初期待内核异常，但 Runtime 实际按契约包装为 ValueError；修正测试预期后通过，未改弱拒绝行为。

## 复现

仓库根目录运行；输出工作目录需换成未使用的路径：

```sh
server/.venv/bin/python docs/validation/scoped-proof-search-stage-f1/benchmark.py --output /tmp/f1-measurements.json --work /tmp/f1-benchmark-new --repeats 3
server/.venv/bin/python -m pytest -q server/tests/solver/test_scoped_proof_search_stage_f1.py server/tests/solver/test_scoped_proof_search_stage_d.py server/tests/solver/test_scoped_proof_facts_stage_c.py
server/.venv/bin/python server/tools/proof_search_stage_d.py --replay-saved docs/validation/scoped-proof-search-stage-d
```

独立进程回放（每次启动新进程）：

```sh
server/.venv/bin/python docs/validation/scoped-proof-search-stage-f1/cold_replay.py --authority-sha256 6f7a8bcab109ed0f1540ec3ab8930d5f4f443637adb50aed8168372ff45dcd5a
```

前后实现指纹分别记录于 `implementation-baseline-sha256.json`、`implementation-final-sha256.json`；基线提交为 `3e18b0610fae70d59defa20cac4f809f9e038c35`。使用同一 benchmark 脚本在该版本上运行可复现基线口径。输入与脚本的指纹见 `input-sha256.json`。历史性能剖析文件不覆盖为新结果。

## 授权边界审查修订

- `grant-review-red.log`：新增 13 项授权边界断言在修复前均失败。
- `grant-review-regressions.log`：修复后 F1（31 项）、C、C-review、D 及真实 q30 链共 **103 passed，44.74 秒**。
- 覆盖重复符号名/身份、Scope 不一致/不存在、未来依赖/自依赖在注册及 begin 时拒绝；错误格式为 `proof_facts`，并禁止触发快照校验与提交重放。合法注册不破坏生产证书 memo，重复调用 ID 注册不改变调用列表。
- 真实 q30 断言仍为求解、独立冷回放、Runtime Retry 各重放 5 个提交；本轮未重跑三轮计时，不把此前的耗时标成新版本测量。
- 本次代码指纹为 `implementation-grant-review-sha256.json`；保留此前 `implementation-final-sha256.json` 与其性能测量对应关系。
- 三个修改文件 Ruff 检查与 `git diff --check` 通过。短前缀 restore 仍从头重放，未来原地截短优化需另补测试。

复现命令（server 目录）：

```sh
.venv/bin/python -m pytest -q tests/solver/test_scoped_proof_search_stage_f1.py tests/solver/test_scoped_proof_facts_stage_c.py tests/solver/test_scoped_proof_facts_review.py tests/solver/test_scoped_proof_search_stage_d.py tests/solver/test_scoped_proof_search_stage_e.py::test_q30_real_method_chain_with_scoped_search
```
