# 数学记法抽取已知问题

## MN-001：题面构型声明遗漏与完整性校验盲区

状态：已知问题，尚未解决（2026-09-16）。本项记录不构成验收豁免。

在 `20260916-153340` 两家真实批次的 K 题中，题面明确声明的一般四边形没有完整保留：DeepSeek 的（1）图2、Doubao 的（1）图2及（2）（3）缺少 `quadrilateral(A,B,C,D)`。虽然输出保留了部分对角线、平分、角度等条件，现有几何证明尚不能证明这些条件足以替代该构型声明。

这包含两个不同层面：

- **抽取完整性**：有人工金标的回归测试可以发现缺项；实际使用时没有金标，仅检查输出的语法、类型和自洽性，不能可靠发现原图中被遗漏的条件。解析成功不代表题面信息完整。
- **语义等价证明覆盖**：某些构型在足够的非退化等前提下可能从其他条件推出；未证明等价不能一概视为数学错误，也不能自动当成冗余条件删除。当前比较器继续报告 `not_proven_equivalent`。

当前处理：保留原始模型响应、冻结金标和失败差异；不补写模型未提取的构型，不放宽 K 题验收，不追加模型复核调用。已有明确仿射构造的冗余证明继续有效，例如图1的 AECD 构型；该能力不代表所有四边形均可省略。

后续若扩展，应选择可说明前提的通用几何规则，并用退化、交叉、错误顶点顺序等反例验证；不能靠针对题号补条件。若要解决无金标的抽取完整性，则需要独立核对题面证据的机制，普通表达式校验不足以保证。

证据与回归：

- [本轮离线验证报告](validation/math-notation-angle-catalog-20260916/README.md)
- [DeepSeek K 题原始响应](../internal/solver-runs/math-notation-provider-comparison-20260916-153340/deepseek/k-quad/raw-response.txt)
- [Doubao K 题原始响应](../internal/solver-runs/math-notation-provider-comparison-20260916-153340/doubao/k-quad/raw-response.txt)
- [DeepSeek 当前比较差异](validation/math-notation-angle-catalog-20260916/deepseek-replay/k-quad/comparison.json)
- [Doubao 当前比较差异](validation/math-notation-angle-catalog-20260916/doubao-replay/k-quad/comparison.json)
