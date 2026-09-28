# Scope 证明搜索：阶段 B 检查器分离

日期：2026-09-28。阶段 B 已完成，C–F 待实施。生产代码基线：`c5fb4003`。本阶段抽离局部 checker、公共类型和规则包注册；没有改变搜索顺序、数学规则、Method 协议或前提授权，没有调用真实 LLM。

## 模块与依赖

- `math_kernel/proof_types.py`：原 ProofContext、ProofLimits、ProofNode、ProofResult、Witness 和预算类型，保持原语义。
- `math_kernel/proof_checker.py`：局部规则验证、来源与上下文核对、证书根验证、嵌套见证重放。不导入搜索模块。
- `math_kernel/proof_rule_registry.py`：不可变的受信规则包注册表，按包身份和准确版本 hash 分派；先检查节点规则归属，再交给对应 checker 完整数学验证。
- `math_kernel/proof_kernel.py`：保留原搜索以及公开兼容入口，重新导出原类型、常量和回放函数。搜索依赖 checker，反向依赖被禁止。
- Solver 和 Runtime 的包入口改为按需解析公开导出对象，避免导入 checker 或 Runtime 模型时隐式初始化整个求解器。公开类和函数仍为原定义模块中的对象，不包装、不复制。

拆分前后对 `_Search`、`_run_request`、`prove_relation`、`verify_relation_sequence`、`prove_domain`、`verify_witnesses` 做 AST 比较，六者均未改变。阶段 D 才调整策略调度；本阶段的兼容门禁不能用来声称已经解决搜索效率问题。

## 规则包边界

完整保留 `bounded-real-proof/v1` 的 26 条规则，规则 hash 为：

```text
8d9a1f9ccc4061513641ce0f15f70f821e4f1e19598c4d149d3191e32167bb16
```

v1 以现有 `schema_version` 和 `ruleset_hash` 选择准确规则包，旧证书不新增字段。注册由受信 Python 应用代码完成；证书只能选择已经注册的身份，不能注册、加载或替换代码。默认注册表只有旧包；添加测试扩展包会返回新表，不修改默认表。

不同包不得声明同一 rule ID；同一包的新版本可与旧版本并存，准确 hash 决定检查器。未知版本、跨包规则冒用和额外的伪注册字段均拒绝。注册表要求所有包遵守共同证书外层：`schema_version`、`ruleset_hash` 和 `nodes` 列表，每个节点必须是含 `rule_id` 的对象；注册表先检查准确包身份、规则归属和节点数上限。显式提供预算时，上限来自 `budget.limits`，否则来自 `context.limits`，与旧 checker 一致。扩展 checker 负责共同外层之外的格式、来源、前提授权、资源计量和数学检查，注册表不把任意 callback 的成功变成可信数学。

旧见证直接调用 `_replay_legacy` 并核对 v1 版本及 hash，不经过注册表分派，也不传递注册表参数，不能通过扩展注册表切换包来改变历史证书含义。跨包共享证明的外层 bundle、生产者验证和统一 DAG 回放预算属于后续阶段，本阶段未引入。

## 冻结证书与测试

`server/tests/solver/fixtures/scoped-proof-search/checker-legacy-corpus.json` 在抽离生产代码前生成，保存 18 份完整证书、准确局部上下文、Scope、符号和有效限额，覆盖全部 26 条旧规则。主体来自现有数学内核、5B、5C 测试的实际成功证书；另补 interval/substitution/guard 的真实构造并使用旧 checker 验证。捕获时相关测试为 **276 passed**。

冻结文件 SHA-256：

```text
9ca2128f0c7b4fbef1f4ffab87d11454c61100d610ef5a089034cae59548dd60
```

测试直接读取旧证书，不调用新搜索重新生成来替代旧回放。`test_proof_checker_stage_b.py` 覆盖：

- 全部旧证书独立重放；禁用搜索入口后仍成功。
- 新 Python 进程阻止导入 proof_kernel / proof_search，然后直接导入 checker 并重放全部证书，包括嵌套见证。
- 修改规则、规则包、hash、源文档、Scope、前提或嵌套证书后拒绝。
- 独立的有理数等式测试包执行实际 Fraction 等式检查；正确关系通过，错误数学拒绝。扩展包不改变旧包 hash、规则所有权或默认注册表。
- 多版本准确选择、重复注册拒绝、规则归属在 callback 前校验、旧嵌套见证不能切换扩展包。
- Solver/Runtime 原公开类与函数对象兼容，Family、抽取、Runtime 配置与编排入口可冷启动导入。

新增文件及兼容入口已接入 affected 测试选取，关联数学内核、容量复用、阶段 A、5B 和 5C 测试。

## 验证记录

在 `server/` 下运行：

```sh
.venv/bin/python -m pytest -q tests/solver/test_proof_checker_stage_b.py tests/solver/test_question_goals.py tests/solver/test_review_human_revision.py tests/solver/test_solver_test_profiles.py
uv run python tools/run_solver_tests.py full
```

针对性验证为 **89 passed**（3.95 秒）。最终完整离线 Solver 回归为 **4596 passed、3 xfailed**（329.02 秒）；串行分组选中 0 项，4623 项 deselected。两组验证有重叠，不相加。补充测试 ownership 后分组工具复核为 **39 passed**（0.19 秒）。Ruff 和 `git diff --check` 通过。

首次完整回归为 4587 passed、3 xfailed、1 failed。失败发生在人工题意校验子进程：独立导入暴露了原来被 Solver 提前初始化掩盖的 Runtime/Family 循环依赖。修复 Runtime 包入口后，这条测试及独立冷启动测试均通过，全量复测结果见上文；复现使用本节命令，不依赖本机临时日志。

阶段 A 的三个严格预期失败继续保留，分别对应 M11 应用身份、教学投影和 M01 条件提示协议。阶段 B 不实现这些能力，也不以跳过或修改数学契约来使其通过。

## 审查修复复核

阶段 B 审查后删除了旧 checker 与嵌套见证之间无效的 `registry` 参数；注册表只在顶层分派使用。共同证书外层和节点预算来源已写入注册表契约。`proof_kernel.py` 的 F401 豁免仅保留在具体兼容导入行，不再关闭整个文件的检查。本文只记录验证结论和复现命令，不引用本机临时日志。

新增 6 个参数化用例，覆盖非法共同外层在分派前拒绝，以及显式预算比上下文限额更宽、更严时与旧 checker 一致。复核命令：

```sh
.venv/bin/python -m pytest -q tests/solver/test_proof_checker_stage_b.py tests/solver/test_math_proof_kernel.py tests/solver/test_proof_capacity_reuse.py tests/solver/test_scoped_proof_search_stage_a.py tests/solver/test_basic_inequality_stage5b.py tests/solver/test_basic_inequality_stage5c.py
```

结果：**350 passed、3 xfailed**（75.14 秒），Ruff 与 `git diff --check` 通过。上文 4596 项全量通过是审查前的结果；本次修复后重跑的是上述相关回归。

## 后续边界

下一步为 C：事实模型、权限适配器、执行前缀快照与原子发布。分层搜索调度在 D；Method 应用识别和教学接入在 E。共享事实库、proof_reads、条件协议迁移、共享 bundle 和真实 Planner 稳定性均未在本阶段宣告完成，5C 的最终门禁仍须另行验收。
