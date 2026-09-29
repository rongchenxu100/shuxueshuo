# F3 评审修复验证（2026-09-29）

后续评审发现，本轮配对循环把配对私有预算耗尽误当成了调用方共享耗尽，原 mock 测试也有相同误判。该项已由 [配对预算归属修正](../pair-budget-review/README.md) 纠正；本目录的测试日志与源码 SHA 保留为此前记录。

范围：M11 预算错误传播、ground substitution 依赖闭包、共享片段候选重试、见证/配对循环的预算分类、不等式方向归一化、调试 JSON 非字符串键兼容。数学规则与额度不变，无 LLM 或浏览器调用。

`implementation-sha256.json` 固定本轮 9 个源码/测试文件；路径相对仓库，不依赖本机目录。此前完整回归日志和性能数据仍是历史记录，本轮不宣称重新测量了求解耗时。

在 `server/` 下执行：

```sh
.venv/bin/python -m pytest -q tests/solver/test_scoped_proof_search_stage_f3.py tests/solver/test_scoped_proof_search_stage_f2.py tests/solver/test_scoped_proof_search_stage_d.py tests/solver/test_scoped_proof_search_stage_e.py tests/solver/test_scoped_proof_facts_stage_c.py tests/solver/test_scoped_proof_facts_review.py tests/solver/test_math_proof_kernel.py tests/solver/test_basic_inequality_stage5c.py tests/solver/test_proof_capacity_reuse.py tests/solver/test_runtime_orchestrator_scoped_debug.py
```

结果：**420 passed，146.62 秒**，见 `regression.log`。包含 22 项新增参数化回归，和调整后的“片段无法导入返回无候选”测试。

新增测试刻意隔离策略与失败边界：

- 禁用通用代入等兜底后证明依赖链，独立回放，并拒绝缺失依赖、错误取值、循环依赖。
- 同端点传递只开放所需策略，覆盖两种书写方向与严格/非严格不等式；错误方向拒绝。
- 在模板/配对/见证边界注入规模、请求配额、共享预算错误，验证重试次数和保留的原始错误码；成功候选仍走真实证明与回放。
- 首份共享片段的递归依赖真实不可证，第二份合法片段成功并独立回放；失败候选节点、读取记录回滚。预算或损坏证据不被吞掉。
- 普通和嵌套元组/dataclass 键按历史 `str(key)` 语义编码；正常载荷不执行兼容转换，校验内容 SHA 与输入未被修改。

随后补上配对循环“显式证书回放不得跳过失败”的断言，并与换元兼容测试一起复验（见 `compatibility.log`）：

```sh
.venv/bin/python -m pytest -q tests/solver/test_basic_inequality_stage5a.py tests/solver/test_basic_inequality_stage5b.py tests/solver/test_proof_checker_stage_b.py tests/solver/test_scoped_proof_search_stage_f3.py -k 'not default_q30 and not frozen and not cold and not checked_handoff and not restore'
```

兼容复验结果：**141 passed，40 deselected，53.42 秒**。与前一组存在重叠，不累加为独立测试数。本轮没有重跑全部离线 Solver。

本轮小型生产模块与 F3 测试 Ruff 通过，`git diff --check` 通过。F2 测试文件原有 5 处导入排序问题未混入修复。
