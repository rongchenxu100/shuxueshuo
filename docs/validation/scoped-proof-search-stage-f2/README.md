# F2 验证记录

2026-09-28；F1 基线提交 `defc76fb6be232f2543dc3e8def683615d5c6d09`。测试环境：Darwin 25.5.0 / arm64，Python 3.11.13。未调用真实 LLM，未进行浏览器检查。

## 评审修订

下面的基准、tar.gz 和 `implementation-sha256.json` 对应评审前的 F2 实现，继续保留，不将它们冒称为修订后性能测量。修订改为 `.versions/<sha>.json`、跨角色物理去重和只读版本；平台 watcher 保留 JSON 字节，并在脱敏时重写整个引用链的哈希。修订代码指纹见 `review-implementation-sha256.json`，测试日志见 `review-tests.log`。本次不重录真实 LLM、不扩充大型归档、不宣称新的性能收益。

修订回归 **190 passed（92.64 秒）**：F2、orchestrator scoped debug、运行配置、scope retry、测试分组和 review service。平台测试用真实 ReviewStore 验证完整/紧凑模式的三阶段历史、原始字节兼容及脱敏后的全部版本引用和 SHA；另覆盖产品的实际脱敏函数，但未启用独立 PostgreSQL 产品实例。最后的复制兜底计数调整另跑 F2 专项，记录追加在同一日志，不将重叠测试数量相加。Ruff（写入器/F2 测试）及 `git diff --check` 通过。

回归命令（仓库根）：

```sh
server/.venv/bin/python -m pytest -q server/tests/solver/test_scoped_proof_search_stage_f2.py server/tests/solver/test_runtime_orchestrator_scoped_debug.py server/tests/solver/test_runtime_config.py server/tests/solver/test_functional_scope_retry.py server/tests/solver/test_solver_test_profiles.py server/tests/test_review_service.py
```

## 测量口径

同一台机器、冻结 q30 ProblemIR 与 authored Plan、显式 `scoped-facts/v2`。基线与最终两模式各三次串行重复，每轮新建 Runtime；每组内部同进程，进程级库缓存和 GC 会影响耗时。报告中位数及最小–最大值，不作为服务 SLA。完整输出模式保留旧视图，同时新增阶段历史；紧凑模式保留同一组 canonical 审计角色。

| 场景 / 秒（中位数及范围） | F1 基线，完整输出 | F2 完整诊断 | F2 紧凑审计 |
| --- | --- | --- | --- |
| 求解含产物 | 18.080（17.896–18.582） | 16.104（16.095–17.113） | 14.176（13.966–16.048） |
| 其中产物发布 | 未单独计时 | 4.471（4.117–4.712） | 2.725（2.009–2.795） |
| 新事实库冷回放 | 1.266（1.108–1.412） | 1.337（1.148–1.414） | 1.225（1.152–1.319） |
| Runtime Retry | 1.446（1.426–1.659） | 1.545（1.455–1.878） | 1.432（1.414–1.651） |

热校验仍为约 0.2 毫秒；序列化和冷回放的完整样本在 JSON 中。本阶段没有修改这些数学路径，不把这些波动解释为 F2 加速。冷回放、求解及 Retry 的提交重放次数全部为 5；热校验为 0。

| 产物计数（每轮完全相同） | F2 完整诊断 | F2 紧凑审计 |
| --- | ---: | ---: |
| 发布请求 | 195 | 87 |
| 内容不变，跳过转换/序列化/写出 | 137 | 54 |
| JSON 快照转换 | 55 | 32 |
| JSON 序列化 | 55 | 32 |
| 新内容文件物理写入 | 58 | 33 |
| 写入内容字节 | 105,072,926 | 27,619,455 |

计数位于 journal 边界，包含阶段索引/历史，不包含 source-provenance/result 等 harness 文件；`conversions` 指 JSON 快照转换，不把领域 `to_payload()` 计作零成本。重复内容仍有比较遍历。旧基线没有同口径计数，故不拿旧 cProfile 的调用数作直接倍数比较。每个内容版本只写一份，latest 名称是硬链接；`artifact_unique_bytes` 按 inode 去重，另包含 harness 文件。

所有样本均为答案 4、5 个提交。完整证明快照均为 3,848,202 字节，SHA-256 为 `20cb39a69736494a2916b8ebb8f973fc9caa8f47fb51a09af80b8bd1d7b804ac`。基准检查的是实际 emitted checkpoint 中的闭包与 Runtime 快照相等，并非仅比较内存结果。

## 存档与回放

- `q30-full-audit.tar.gz`、`q30-compact-audit.tar.gz`：最终模式各首轮的完整输出，含请求、响应、所有阶段索引/历史、checkpoint、事务、verified execution 及 provider 角色；archive 脚本检查不含本机路径，并统一清除时间和 owner 元数据。
- `cold_replay.py`：直接读取归档内 checkpoint 的 `restore_state.proof_facts`；先逐项校验历史索引与产物哈希，再用独立授权回放，禁用新旧搜索。每种模式三次独立进程，全部回放 5 个提交。结果及 archive SHA 见 `cold-process.json`。
- 授权来自 F1 单独冻结的 `q30-authority.json`，SHA 锁定为 `6f7a8bcab109ed0f1540ec3ab8930d5f4f443637adb50aed8168372ff45dcd5a`。不从证书自身构造调用权限或预期输出 hash。
- `implementation-sha256.json`、`inputs-sha256.json`：代码与固定输入指纹。

## 测试

先添加写入器测试，`red.log` 记录未实现 `DebugArtifactJournal` 时的收集失败。初轮相关回归 181 项通过；补充失败历史、标量兼容和缓存释放后，相关回归 186 项通过（`final-regression.log`）。最后移除按 completed/attempt 编号跳过的捷径，补充“返回值在已发布事件后发生变化”和返回后才提供的 authority 调试视图测试，最终产物、配置和测试分组专项 **80 passed**（`final-artifact-tests.log`）。这些集合有重叠，不相加宣称测试总数。

最终新写入器、证据投影文件与 F2 测试通过 Ruff，diff whitespace 检查通过。没有在此阶段执行 F3 的全量离线、默认切换或真实 Planner 观察门禁。

## 初期记录

`full.json`、`compact.json`、`*-initial-lifecycle-shortcut.json` 是初期测量，曾按 completed 编号跳过返回后发布；该捷径已移除，不能用作最终性能结论。`initial-mislabeled-full.json` 是一次输出文件名误称 compact、实际未传 compact 模式的完整诊断测量，JSON 中模式如实为 full，不计入紧凑模式。所有最终结论只使用 `baseline.json`、`full-final.json`、`compact-final.json`。

## 复现

从仓库根运行，输出目录须不存在：

```sh
server/.venv/bin/python docs/validation/scoped-proof-search-stage-f2/benchmark.py --output /tmp/f2-full.json --work /tmp/f2-full-new --repeats 3 --mode full_diagnostic
server/.venv/bin/python docs/validation/scoped-proof-search-stage-f2/benchmark.py --output /tmp/f2-compact.json --work /tmp/f2-compact-new --repeats 3 --mode compact_audit
server/.venv/bin/python -m pytest -q server/tests/solver/test_scoped_proof_search_stage_f2.py server/tests/solver/test_runtime_orchestrator_scoped_debug.py
```

基线使用上述 F1 提交及其 `docs/validation/scoped-proof-search-stage-f1/benchmark.py`，不能用当前代码冒充优化前。独立回放命令 `cold_replay.py --authority-sha256 <上面的授权哈希> --archive <本目录归档路径> --archive-sha256 <cold-process.json 中对应哈希>`。
