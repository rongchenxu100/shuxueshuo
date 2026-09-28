# Scope 证明搜索：阶段 A 基线与契约测试

日期：2026-09-28。阶段 A 已完成；B–F 尚未实现。本阶段没有改变生产证明规则、搜索顺序、Method 协议或发布权限，也未调用真实 LLM。

## 交付与复现

- `server/tools/proof_search_baseline.py`：运行冻结输入，真实执行 Runtime / 证明器 / checker；记录各预算实例、请求目标轨迹、缓存命中、耗时及结果。失败先保存诊断再报错，拒绝覆盖已有运行目录。
- `server/tests/solver/fixtures/scoped-proof-search/manifest.json`：引用已有原始响应与题目文件，固定 SHA-256；不重新生成模型响应。
- `premise-sites.json`：16 项现有前提构造点分类，包含函数、源位置、语义、有效条件、生产证书位置及未来发布策略。分类来自构造点和依赖，不能单凭名称前缀放行。未知构造点默认不可发布。
- `budget-profiles.json`：默认、消元、换元以及两种嵌套顺序的有效限额。
- `legacy-m01-context.json`：从真实 `expression_rewrite.verify_chain` 输出中冻结的旧关系证书及其准确前提集。
- `test_scoped_proof_search_stage_a.py`：现状保护测试、真实离线集成与三个严格预期失败契约。已接入 affected 测试选取。

在 `server/` 下运行：

```sh
.venv/bin/python -m pytest -q tests/solver/test_scoped_proof_search_stage_a.py
.venv/bin/python tools/proof_search_baseline.py --output ../internal/review-analysis/scoped-proof-search-stage-a/new-run
```

`new-run` 必须不存在。原始运行目录保留，不覆盖失败记录。生产代码基线为 `0a8d3585`，测量时 HEAD 为 `7e80f517`（后者仅增加设计文档）。运行摘要另保存输入 hash、测量工具 hash 与 Python 版本。

## 当前测量结果

产物：`internal/review-analysis/scoped-proof-search-stage-a/baseline-02/summary.json`；每个子目录保存 `measurement.json`，完整计划样本另有 Runtime 证据，局部样本保存 `bound.json`。

| 冻结样本 | 原失败归因 | 当前结果 | 秒 | attempts | reductions | nodes |
|---|---|---|---:|---:|---:|---:|
| live14-1 | M11 搜索路径/归约预算 | 成功，最小值 4；不是完整五段链 | 5.956 | 421 | 75 | 2615 |
| live14-3 | M13 取等分隔句式 | 成功，最小值 4；完整五段链 | 5.335 | 554 | 161 | 2791 |
| live12-m11-2 | M11 局部界传递/归约预算 | 求界与重放通过 | 0.311 | 159 | 2 | 516 |
| live12-m11-3 | M11 局部界传递/归约预算 | 求界与重放通过 | 0.442 | 168 | 2 | 570 |

这些历史失败在此前修复后已经通过，**不是本阶段修好了四个问题**。原输入继续作为新旧架构对照基线；句法样本仅作为兼容性对照，不能归功于搜索架构。完整五段链独立记录，不把其他合法路线算作方法覆盖。

表中 attempts 是证明器的搜索尝试计数，不是 Planner 重试次数；nodes、reductions 是所有预算实例的累计收费，包含辅助检查和重放，不能与单个 ProofLimits 上限直接比较。相同数学节点可能在不同上下文中被再次检查。耗时仅供参考，确定性操作数优先。

当前没有检索器或 SearchPolicy，因此本阶段不伪造“策略命中”“事实检索数”“跨 committed manifest 缓存命中”指标。旧证明器的前 200 个目标请求及上下文 hash、局部/同上下文缓存命中均已记录；完整预算计数不截断。B/D 阶段再分离搜索、检索和 checker 的成本。

## 预算与前提分类发现

| 入口 | premises | variables / equations | reductions | attempts / nodes |
|---|---:|---:|---:|---:|
| 默认 | 16 | 4 / 4 | 256 | 512 / 512 |
| 消元 | 48 | 4 / 4 | 1024 | 2048 / 2048 |
| 换元 | 64 | 8 / 8 | 2048 | 4096 / 4096 |
| 先换元后消元 | 48 | 8 / 8 | 1024 | 2048 / 2048 |
| 先消元后换元 | 64 | 8 / 8 | 2048 | 4096 / 4096 |

嵌套顺序会覆盖部分限额；这只是现状快照，不是认可未来按 Method 重新发放总预算。

`bound:previous` 必须追溯前序已验证界；换元定义带定义依赖；`derivation:*` / `elimination:row:*` 等只在其前缀与依赖有效时可用。`attainment:*`、`solution_case`、`shared_solution:*`、`equality_derivation:*` 属于取等或见证分支，不能作为无条件全局事实发布。映射表是阶段 C 适配器的输入规范，本阶段没有假装已实现发布器。

## 三个严格红测试

1. **M11 应用身份**：对 `x+4/x≥4` 的证书加入真实证明且经过 checker 验证的辅助 `y+4/y≥4` 片段。当前 M11 把辅助片段当成本次应用，报 `amgm_remainder_changed`。未来应仅识别本次提交关系的应用。另有绿测试保证只引用已知旧界不能冒充新的应用。
2. **教学投影**：同一有效局部证书使教学层同时产出 x、y 两条 AM-GM 关系，并把它们归到同一提交行。未来只能投影本次应用证据。
3. **M01 条件提示**：q30 显式仅绑定 `c>0`，首次失败为 `input_domain_unverified` / `bind_domain_conditions`。未来新协议仍应读取目标所属 Scope 的原始条件。旧协议证书则继续按准确旧前提集重放。

这些测试用 `xfail(strict=True)` 加专用异常标识特定缺口；意外异常会失败，功能实现后 XPASS 也会失败，要求移除标记。不是跳过测试，也没有 mock 数学证明成功。

P1 的现状复现使用 v1 合法的辅助内联节点，并不声称已经实现共享 DAG / 引用式证书。阶段 E 仍须补真实已发布依赖的引用式与内联式等价测试。

## 回归与后续边界

相关回归覆盖旧证书禁用搜索重放、前提增减/Scope/证书篡改拒绝、分支假设缓存不泄漏、失败事务无状态提交，以及现有 Scope 权限、Retry、证明内核、容量缓存和测试分组。相关回归为 **353 passed / 3 xfailed**（66.67 秒）；补充旧界拒绝、测试选取检查并更新真实 M01 冻结证书后，阶段 A 与测试分组复核为 **50 passed / 3 xfailed**（17.15 秒）。两次有重叠，不相加。日志分别为 `/private/tmp/proof-stage-a-tests.log`、`/private/tmp/proof-stage-a-final-tests.log`。

A 的权限与回滚测试保护现有 Runtime/局部缓存行为；新事实库的未提交事实、过期版本、执行前缀、`proof_reads` 闭包和 committed manifest 缓存隔离，必须在 C/D 的真实接口上补测试。不能把现有绿测试当作这些能力已经完成。

下一步为 B：分离 checker 并保护规则包身份与旧回放；随后 C/D/E 按设计接入。架构和 5C 的最终完成门禁均未在本阶段宣告通过。


## 新版设计复核：跨题型扩展点

阶段 A 补充 `q12-subchain.json` authored 对照并固定 hash：M07 换元 → M08 消元，执行期间禁止生成 AM-GM 类规则节点，随后禁用搜索独立重放 M08 及其 M07 依赖。当前证据确实消费 M07 的已验证换元等式；新变量非负关系虽已在上下文中，但旧搜索仍可从定义重新证明。因此这不是“共享事实发布与定义域检索已完成”，实际共享读取及 `proof_reads` 验收保留在 C/E。

审查后明确了后续实施调整：

- B 保留完整旧规则包/hash，并增加规则包注册与跨包身份隔离；不能靠删掉 AM-GM 规则来运行禁用测试。
- C 注册事实类型与发布政策；公共条件性要求需要 `requirement_kind`，保留取等专属 payload 和分支身份。
- D 声明策略所需规则包，并将允许规则集合写入 SearchPolicy；搜索开关不改变旧证书的回放规则。
- E 通过公共 Method 应用接口接入 M11，并加入非 AM-GM 子链的实际共享复用门禁。

阶段 A 既有实现无需重写；补充的非 AM-GM 对照负责保护新增泛化要求，后续接口隔离测试在真实接口出现时落地。

新增跨题型对照后的复核：**51 passed / 3 xfailed**，17.61 秒；Ruff 与 `git diff --check` 通过。日志：`/private/tmp/proof-stage-a-review-tests.log`。
