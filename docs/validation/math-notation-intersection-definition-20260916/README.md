# 交点定义简写兼容修复

已修复 Doubao 和平二模、南开一模中的 `M = axis(Γ) ∩ x_axis` / `D = axis(Γ) ∩ x_axis`。两份原始响应未经改写即可通过编译、对象绑定和严格语义比较。本轮不修改 Prompt、Schema、金标和原始模型响应，没有新增模型调用。

## 规则

- 等式一侧为点名、另一侧为交集时，按点定义建立本作用域对象身份；支持等式左右换位及父条件继承，不搜索兄弟分问。
- 编译 IR 保留独立的 `point_intersection_definition` 节点，原始数学字符串保留在规范化候选中。只有代码证明交点存在且唯一，比较投影才转换成点属于该唯一交集的关系，并记录证明依据。
- 复用已有几何证书：坐标轴交点、已确认非退化二次曲线的对称轴与 x 轴、平行四边形／正方形对角线、已知数字坐标下范围正确的直线／线段交点。不会因公式出现 `a*x^2` 自动推断 `a≠0`。
- 多交点、重合或平行、退化、交点在线段外、缺少证明前提等情况不会强制转换。无法证明时返回 `binding.intersection_not_proven_unique`，带原字符串和具体分问路径。射线等未覆盖情形继续保守报告。
- 普通点集仍是点集；参数不会被悄悄改成点，`at` 条件及逻辑分支仍保留。无需 LLM 增加任何字段或先做几何推导。

## 验证

新增 40 项正反例及保存响应测试，已接入 affected 门禁。全套相关离线回归 **338 passed，7 deselected**；Ruff 检查通过。[测试日志](offline-tests.log)

| 保存的真实批次 | 原始真实结果 | 修复后原始响应离线回放 |
| --- | --- | --- |
| Doubao 20260916-153340 | 4/7 | **6/7** |
| DeepSeek 20260916-153340 | 6/7 | **6/7** |

Doubao 的和平二模、南开一模已严格通过，K 题仍有其他数学条件差异，继续失败；四幅缺图阻断仍保留。两家原始真实成绩不改写，离线回放不是新一轮模型测试。

- [Doubao 原始输出与当前回放](doubao-replay/outputs.html)
- [Doubao 回放摘要](doubao-replay/summary.json)
- [DeepSeek 回放摘要](deepseek-replay/summary.json)
- [编译与对象绑定](../../../server/shuxueshuo_server/problem_understanding/notation_compile.py)
- [有证明前提的规范化](../../../server/shuxueshuo_server/problem_understanding/notation_normalization.py)
- [交点门禁](../../../server/tests/solver/test_math_notation_intersection_definition.py)

七题 Doubao 原始响应、冻结金标、验收政策的字节副本已纳入 `fixtures/math-notation-v1/recorded-doubao-20260916-153340`，用文件哈希校验，防止以后通过修改样本取得通过。
