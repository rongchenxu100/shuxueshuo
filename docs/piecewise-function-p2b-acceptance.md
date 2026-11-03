# FR-T3 P2b：例10变式2分段不等式本地验收

日期：2026-11-02。范围为单层分段不等式与本地课程；自动裁框偏紧继续暂缓。

## 交付

- 新增 `function-representations-b10-v2`，页面 `/topics/function-representations/q10c/`，归入“分段函数常规问题 → 分段解不等式法”；专题累计29题。
- 人工核对归档图9第98页例10变式2：`x≥0` 时 `x²−4x+6`，`x<0` 时 `x+6`，目标 `f(x)>f(1)`，保留四个原区间选项。题源记录为 `internal/senior-high/authored-courses/piecewise-p2-20261102/b10-v2.json`，含原图 SHA-256，不读取书中解析作为条件。
- 新增组织方法 `method-piecewise-inequality`，复用化简、一次／二次求根与正负判断技能；没有新增计算技能或选法判断节点。原方程与原不等式分别走窄准入；数值求值仍沿用 P1。
- 先为输入1选段，计算 `f(1)=3`；第一段解不等式并与 `[0,+∞)` 取交，第二段再解并与 `(−∞,0)` 取交；最终合并为 `(−3,1)∪(3,+∞)`，原选项 A。0 属于第一段，合并后保留。
- 7个可折叠大步骤、11个独立确认动作；复用拆步数学卡、抛物线和数轴，完成态为简洁数学推导。抛物线明确标注 `y=x²−4x+3`，作答前不高亮正确区间，完成后显示正值部分及开端点。
- 最终文案为“原不等式的解集”，保留既有方程、参数范围和值域显示。

## 验证证据

最终记录：`internal/solver-runs/piecewise-p2-20261102/b10-v2-authored-verified`；运行 ID `74e9eb06361d4c6085df1765c50976f8`。数学求解与独立回验通过，完整解集为 `(−3,1)∪(3,+∞)`；原选项匹配 A，读题原文定位和课程投影完成。记录为 `source_admission=authored_topic`，不代表真实照片识别通过。

必要单元测试：21项 Python 测试通过（1.41秒），1项 JavaScript 文案定向测试通过。

```text
tests/solver/test_graph_piecewise_inequality.py
tests/solver/test_graph_piecewise_equation.py::test_native_contract_selection_and_frozen_modules
tests/solver/test_graph_piecewise_equation.py::test_all_branch_roots_are_filtered_and_independently_verified
tests/solver/test_graph_piecewise_evaluation.py::test_nested_numeric_value_reselects_branch_and_checks_source_evidence

node --test --test-name-pattern='piecewise equation completion' tools/tests/graph-stage-three-math-dom.test.mjs
```

覆盖严格／非严格符号、反写不等式、阈值输入在边界的选段、0的归属、常数段、空集、缺段和无理端点；拒绝比较值无定义、重叠、变量分母、三次式、复合调用、额外条件和不确定源条件；篡改比较值、分段表达式／段域／根／解集不能通过。另检查独立完整集验证、源文本符号不一致、原选项匹配、方法互斥准入、冻结文件、卡片评分、结果隐藏和图像参数。

修改的 Python 文件 Ruff 检查通过；课包、公共图谱构建及一致性检查、`git diff --check` 通过。浏览器完成11步回放，确认 A 与完整解集，以及数学公式、抛物线和段内交集数轴的显示。未运行全量测试或真实模型提取。

## 后续

下一批 P3 为 B11：分段函数值域，逐段求像集再取并，处理区间开闭、顶点和跨段端点补入。P1／P2真实照片提取／复核、私有上传和独立留出仍待验收；FR-T2 自动裁框偏紧继续暂缓。
