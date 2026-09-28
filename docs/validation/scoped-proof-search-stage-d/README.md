# 阶段 D 验证记录

日期：2026-09-28。各组测试重叠，不相加。代码边界与配置见 [D 实施记录](../../scoped-proof-search-stage-d.md)。

| 验证 | 结果 | 日志 |
| --- | --- | --- |
| 完整离线 Solver | 4663 passed、3 xfailed；324.19 秒 | [offline-solver.log](offline-solver.log) |
| 最终相关回归 | 358 passed、3 xfailed；39.13 秒 | [focused-final.log](focused-final.log) |
| 最终 D 专项（含两组冻结推导的完整授权会话） | 36 passed；3.74 秒 | [stage-d-final.log](stage-d-final.log) |
| 冻结数学请求 | 166/166 搜索及回放成功 | [shadow-summary.json](shadow-summary.json) |
| 禁止新旧搜索后的存档回放 | 166/166 成功 | [replay-summary.json](replay-summary.json) |

三个 xfail 是阶段 A 留待 E 的严格契约用例。全量回归启动后补充了精确算术操作计量和两个预算/缓存边界测试；相关回归覆盖这 34 项 D 测试及 A/B/C、证明内核、测试分组。随后仅增加两组冻结推导完整运行于单一授权搜索会话的测试，最终 D 专项 36 项通过；此时未再改变核心实现。生产默认入口未切换，既有搜索未修改。

冻结比较先执行旧 Runtime 以恢复准确局部前提和实际有效 limits，再对每个数学请求独立运行新搜索；禁止调用旧 `_Search.core` 作为回退。两个外层 M13 见证调度请求明确标记 `witness_driver_stage_e`，不计入 166 项；其内部数学验证请求已覆盖。此比较不等于正式 Method 已迁移到新会话。

| 样本 | 成功数学请求 | 新搜索及回放等总耗时（秒） | attempts | reductions | 算术操作 |
| --- | ---: | ---: | ---: | ---: | ---: |
| live14-1 | 53 | 3.188 | 891 | 22 | 32120 |
| live14-3 | 72 | 4.497 | 1765 | 159 | 48998 |
| live12-m11-2 | 18 | 0.912 | 363 | 2 | 8829 |
| live12-m11-3 | 23 | 1.114 | 387 | 2 | 10468 |

计数是样本中所有独立请求的累计搜索费用，不是一个 Proof Session 的费用；旧基线还包含其他辅助校验，不能直接比较总计数断言性能改善。耗时包括独立回放和产物保存，测量期间也在运行其他离线测试，仅作观察值。

四个 `live*.json.gz` 文件保存完整局部上下文、请求、证书、回放结果、policy、有效限额及受限轨迹。[implementation-sha256.json](implementation-sha256.json) 记录本轮核心实现指纹。Runtime 事实发布的权限/producer 独立重放由 C/D 集成测试保护；这些局部存档不是新的原题授权来源。

初次比较出现两条根式等式的局部配额失败，已通过将无前提恒等证明和根式符号规则放入相应阶段修复；另外两条是误将外层见证构造入口计作通用证明请求，已明确移交 E。保存了 [初次结果](shadow-initial-failures.json) 和 `initial-failed-requests.json.gz`，未覆盖失败证据。`focused-initial.log` 保留一次测试断言诊断文本不匹配：源码变更已被正确拒绝，实际错误是 `committed manifest changed`；最终测试修正了预期文本。

仓库根目录复现：

```sh
# 输出目录必须不存在；不调用真实 LLM
server/.venv/bin/python server/tools/proof_search_stage_d.py --output /private/tmp/proof-search-d-new-run

# 只用 checker 回放随仓库存档，禁止新旧搜索
server/.venv/bin/python server/tools/proof_search_stage_d.py --replay-saved docs/validation/scoped-proof-search-stage-d

# D 专项与全量离线
server/.venv/bin/python -m pytest -q server/tests/solver/test_scoped_proof_search_stage_d.py
server/.venv/bin/python server/tools/run_solver_tests.py full --workers 6
```

新增模块 Ruff 和 `git diff --check` 通过。未调用真实 LLM，未打开浏览器，未部署。

## 审查修订后的验证

审查修订新增 6 项测试，D 专项共 42 项。D + C + C 审查回归为 **71 passed**，见 [review-focused.log](review-focused.log)。完整离线回归 **4673 passed、3 xfailed，293.85 秒**，见 [review-offline-solver.log](review-offline-solver.log)。最终格式化后再次运行 D 专项，**42 passed，5.52 秒**，见 [review-stage-d-final.log](review-stage-d-final.log)。该全量运行开始后仅补充了注册表更换时 fork 缓存失效的保护及其断言，随后重跑上述 71 项相关测试；没有改变数学构造策略。

[review-rerun](review-rerun/) 保存修订后的四组完整请求、证书及轨迹，166 个数学请求全部通过新搜索和独立回放，两个外层见证驱动仍归阶段 E。包含单独的 summary、回放结果和实现 hash；根目录原存档保持原样。运行时同时有其他离线测试，耗时不用于宣称算法加速。

```sh
server/.venv/bin/python server/tools/proof_search_stage_d.py --replay-saved docs/validation/scoped-proof-search-stage-d/review-rerun
```

新增测试覆盖：AST 符号检索隔离、去重后容量、局部候选有效性、注册表更换/同名闭包及 fork 缓存、惰性策略匹配、候选超限后的上下文扩大。Ruff 检查通过。
