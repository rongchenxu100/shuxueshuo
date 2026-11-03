# FR-T3 P2a：例10变式1分段方程本地验收

日期：2026-11-02。范围为单层分段方程与本地课程；自动裁框偏紧继续暂缓。

## 交付

- 新增 `function-representations-b10-v1`，页面 `/topics/function-representations/q10b/`，位于“分段函数常规问题 → 分段解方程法”；专题累计28题。
- 人工核对题源：归档图9第98页例10变式1。记录为 `internal/senior-high/authored-courses/piecewise-p2-20261102/b10-v1.json`，保留原图 SHA-256、两段范围和四个选项，不把解析写入数学条件。
- 新增组织方法 `method-piecewise-equation`，复用 `skill-solve-quadratic`；不新增技能或选法判断节点。`type-piecewise-function` 仅开放单层方程的窄准入，P1 求值仍复用代入法。
- 学生先解第一段方程，再依据 `x>0` 舍去 −2；随后解第二段、核对 `x≤0`；合并为 `{-3/2,2}`，对应原选项 C。每个动作独立确认，完成态保留原条件与简洁数学推导。
- 原选项支持此类输入方程的裸常数／逗号分隔数列，匹配完整解集；保留原标签与文字，选项重排后重新匹配。括号区间不改读成两个根。
- 读题明确“求全部 x”；最终标为“原方程的解集”，避免沿用“参数范围”。

## 验证证据

最终运行目录：`internal/solver-runs/piecewise-p2-20261102/b10-v1-authored-final`；运行 ID `c28d234265bf4fad947ccf2c4f1ba9fd`。数学求解及独立回验通过，完整解集为 `{-3/2,2}`；原选项匹配 C；D1 来源完整且生成读题行，交互课包构建通过。该记录是 `source_admission=authored_topic`，不代表真实照片识别通过。

必要单元测试：19项 Python 测试通过（1.29秒），1项 JavaScript 定向测试通过。

```text
tests/solver/test_graph_piecewise_equation.py
tests/solver/test_graph_piecewise_evaluation.py::test_nested_numeric_value_reselects_branch_and_checks_source_evidence
tests/solver/test_graph_piecewise_evaluation.py::test_piecewise_uses_existing_skill_pipeline_and_stepwise_cards
tests/solver/test_graph_original_set_choice.py::test_transcription_only_unspecified_mode_does_not_become_single_from_one_label

node --test --test-name-pattern='piecewise equation completion' tools/tests/graph-stage-three-math-dom.test.mjs
```

覆盖全部候选根、按原段域筛选、0的开闭、缺段、常数段、无解、无理根；拒绝重叠、变量分母、三次式、复合调用、额外条件和题源不确定；篡改段域／候选／结果不能通过；读题原文匹配与课程投影；交互评分和结果隐藏；原选项完整性、换序与区间歧义。定向回归覆盖旧 P1 内外层重新选段、原集合选项语义及最终文案不影响参数／值域答案。

修改的 Python 文件 Ruff 检查通过；本地课包及图谱构建、`git diff --check` 通过。未运行全量测试或真实模型提取。浏览器已检查原题分段公式、逐段卡片、完整数学推导、合并结果和选项 C；AI 回放9个动作完成，最终文案显示“原方程的解集”。

## 后续

下一批 P2b 为 B10-v2：先求 `f(1)`，再逐段解 `f(x)>f(1)`，与本段范围取交后合并。分段不等式、值域、参数和建模不计入本批完成。P1／P2a 真实照片提取／复核、私有上传和独立留出仍待验收；FR-T2 自动裁框偏紧暂缓。
