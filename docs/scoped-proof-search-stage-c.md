# 阶段 C：共享事实与事务

本阶段实现 [架构设计](scoped-proof-search-architecture.md) 的 C，采用内部显式接入。默认 Runtime 的 `proof_facts` 为 `None`，既有 Method 证明、Planner 参数和教学路径保持原协议。搜索调度属于 D，正式 Method 消费共享事实及教学迁移属于 E。

## 模块与权限边界

| 模块 | 职责 |
| --- | --- |
| `math_kernel/proof_facts.py` | 冻结的 `VerifiedMathFact`、`FactValidity`、`ConditionalRequirement`、`AttainmentRequirement` 与事实类型注册表 |
| `runtime/proof_evidence_adapters.py` | 逐项对应阶段 A 的 16 个局部前提构造点；按生产证书分类、重放并投影可发布结论 |
| `runtime/scoped_proof_facts.py` | 执行前缀快照、只读视图、私有 overlay、证书导入、独立重放及发布 |
| `runtime/proof_fact_transactions.py` | 接入既有 Functional 分支事务、准确输入指纹、输出绑定、辅助依赖与 Retry |
| `runtime/proof_fact_evidence.py` | 执行证据及辅助依赖闭包；序列化结构校验不代替数学重放 |

事实源由宿主的可信输入绑定或 authored 测试环境提供。`source_context`、符号身份、调用授权和 canonical 顺序不能从待验证 bundle 或 Planner 字符串自举。当前内部接入须显式构造 `ScopedProofFacts`；自动从正式 Method 的原题绑定建立会话属于 E。

`ProofCallAuthority` 固定 Method、发布 Scope、符号身份、定义/版本依赖、准确调用输入指纹、可发布类型及目标。事务桥核对已编译调用的输入读取权限、支持性读取权限和顺序；执行器另将目标授权与实际解析的 `target` 输入对照。事实共享不替代表达式 StateVersion 或 previous_bound 的绑定。

## 事实导入与发布

- 可见性复用 `RuntimeContext.is_visible`。只读取 canonical 前驱中已提交、Scope 可见、符号身份一致且满足有效性引用的事实。子 Scope、兄弟 Scope、未来调用及未提交 overlay 均不能供给前提。
- 事实只记录关系中实际出现的符号；无关符号不影响可见性或 statement key。相同公式保留不同来源和证书身份；不通过代数约分合并事实。`semantic_kind` 必须注册，而且生产 Method 和当前调用均须明确允许发布该类型。扩展类型不继承其他类型的权限。
- M01 局部证书适配要求把**每一个**局部前提绑定到可见事实，校验调用有效性包含全部导入事实的定义/版本要求，再按证书原始 Scope、源位置和有效预算重放。不会把提交的 `∵` 自动视为真。
- M07 重放定义、定义域和关系证书后，分配带生产调用/输入指纹的新符号身份及 definition refs。M08 与界链的嵌入历史证书必须与指定的已提交生产调用完全匹配，同时校验目标和可见事实身份。
- 投影只选已接受根及其依赖中必要的正性、非负、非零关系，不遍历嵌套见证内部，也不发布搜索遗留节点。原始证书及节点路径仍保留。
- M11/M12 的取等关系存入独立 `AttainmentRequirement`，不进入事实视图。`attainment:reference`、`solution_case` 和取等联立分支拒绝作为共享事实发布。M13 无全局发布适配器。

每次建立新视图前重放生产证书；提交前再次从冻结记录重建候选事实、需求及依赖，逐项对照后发布。修改 overlay 候选列表不能绕过检查。重放调用 checker 或既有 Method 的证书重放入口，不调用搜索。

## 事务、依赖与恢复

1. `RuntimeContext.fork()` 共享不可变快照，当前调用获得私有 overlay。Method 的内部 kernel facade 只暴露会话/视图，不暴露 RuntimeContext。
2. 输出及写入检查通过后，事实提交到该私有分支，记录输出 hash 与提交前的完整 manifest。输出 hash 绑定数学值、版本、写入位置和不可变来源；Runtime Retry 另行校验后重绑的 goal_unit_ids / call_binding_signature 不参与此 hash，避免合法重绑被误判为数学输出变化。只有调用成功才用该分支替换当前状态；证明或 Method 失败均丢弃分支。
3. `proof_reads` 保存实际导入局部证书上下文的事实，包括被纳入上下文但未被最终根使用的前提，因为旧证书 hash 绑定完整前提集。overlay 内部依赖在提交时映射为正式 fact ID。
4. 读取已提交事实形成 `proof_read` 调用边，加入执行图、WorkingPlannerState、Goal 可达闭包和执行证据。新增边须来自已验证 canonical 前驱；证据投影拒绝自环、环、未知节点及错误 step 身份。
5. checkpoint 保存事实 bundle、manifest 和输出绑定。恢复使用外部原题/调用授权、现有 typed runtime seed 中的输出与写入重新检查，不能仅靠 bundle 自带的 hash 获得权限。

本阶段采用保守的 **完整前缀失效**：输入/来源/定义/版本改变，或前驱失效，会使相关旧证据不可重放；显式 invalidate 从最早失效提交截断后缀。Scope Retry 使用包含 proof_read 的图计算失效闭包，并将保留集合截断到最长安全调用前缀；后续调用连同输出一起重新执行。低层 bundle 校验仍拒绝非前缀，不能只删除中间生产调用再重贴旧证书。更细的跨快照复用交给 D/E，不静默降级成旧搜索。

## 接入限制

- C 的正向验收包括真实 Functional 事务中的两个 Method、隐藏辅助依赖、失败回滚及恢复；另有 M07 → M08 内部会话读取 `q≥0`、完整 Method 证书导入，并禁止产生任何 AM-GM 规则节点。
- 上述内部测试不宣称正式 M08 搜索已改用新事实索引。M11/教学仍扫描旧证明节点，按设计在 E 一起迁移；M01 原条件自动可用协议也尚未切换。
- 当前视图按权限过滤已有快照，尚未实现 D 的分阶段检索、搜索配额及缓存。规则包 hash 不变。
- 带 proof overlay 的 Runtime 等价调用别名和跨 Scope lineage 提交当前明确拒绝，需显式重绑定证据后才能支持，不自动修改发布 Scope。
- 事实 bundle 可通过 JSON 独立重放。整个 Functional checkpoint 的恢复仍沿用已有 **进程内 typed runtime seed** 契约，未新增通用磁盘 checkpoint 到 Runtime 对象的反序列化器。
- 为使事务模块可独立冷启动，将 explanation 包公开导出改为延迟加载，消除 Method 导入教学模块引起的循环；公开名称不变，有独立子进程测试。

## 审查前验证与产物

新增测试：`server/tests/solver/test_scoped_proof_facts_stage_c.py`。覆盖真实证明、来源/证书/输出/Scope/版本篡改、定义身份、条件性要求、扩展类型、事务回滚、独立恢复、执行闭包及 cold import；不 mock 数学验证。

复现命令（仓库根目录）：

```sh
server/.venv/bin/python -m pytest -q server/tests/solver/test_scoped_proof_facts_stage_c.py server/tests/solver/test_solver_test_profiles.py
server/.venv/bin/python server/tools/run_solver_tests.py full --workers 6
```

结果与运行日志保存在 [可提交验证目录](validation/scoped-proof-search-stage-c/)：

- 完整离线 Solver：**4622 passed、3 xfailed**，297.96 秒；串行组选中 0 项。日志 `offline-solver-before-review.log`。阶段 A 的三个严格预期失败仍留待 E。
- 全量运行期间及之后补充两项扩展/冷启动测试、bound 分类和证据 step 身份检查后，最终相关回归：**215 passed**，116.08 秒。日志 `focused-before-review.log`。其中 C 新增 **22 项**；两组结果有重叠，不能相加。
- 新增模块的 Ruff 检查及 `git diff --check` 通过。既有大型 Runtime 模块仍有存量 Ruff 告警，本阶段仅修正涉及新增代码的导入，不宣称全仓 lint 清零。

最终相关回归覆盖本阶段测试、Functional transaction / Goal / verified execution、阶段 B checker 和测试分组配置。两份执行/checkpoint JSON schema 已同步；测试 ownership 已登记。本阶段没有真实 LLM 调用、浏览器检查或部署。

C 已按内部接入范围完成；D/E/F 与 q30 的最终验收仍未完成。

## 阶段 C 审查修复

两个 P2 已修复，并增加实际集成覆盖：

- 使用真实南开几何录制计划，选取 A、B、C 三个已提交调用；替换中间 B 的真实输入（交换线段两端，数学结果相同），保留前缀 A，丢弃并重新执行 B 和独立的后续 C。覆盖 Scope Retry 选择、来源重绑、事实重放、原生 Method 再执行和最终 verified execution。
- 另一条测试以真实证书构造仅通过 `proof_read` 相连的 B→C，验证失效计算在截断前已排除 C。
- 教学注册表为 `ProofFactsExecutionEvidence` 注册明确的空投影器；Snapshot 遇到这个已注册的空投影只跳过辅助证据。未知证据仍报错。空提交、有事实提交两种配置均真实执行录制 Solver 并构建 ExplanationSnapshot；教学来源、计算/检查、证据和答案与未启用时一致。

另修复实际符号绑定和证书导入有效性检查。测试验证无关变量不影响共享；版本/来源/输出数学值变化仍不能利用 Retry 重绑绕过校验。审查修复测试位于 `test_scoped_proof_facts_review.py`。

**留待 D 的优化**：提交内去重、常数事实过滤及按已验证快照缓存重放结果。它们影响候选规模/运行成本，不影响本次修复的权限正确性；去重时还须保持消费引用到所选证书的映射，缓存须绑定快照及验证授权。当前仍保留完整来源并重放，未以未验证缓存代替 checker。

旧日志已从忽略目录迁移到上述可提交目录，不再引用别人无法取得的本机临时产物。审查后验证结果另列于该目录 README。
