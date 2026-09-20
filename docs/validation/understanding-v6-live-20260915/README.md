# 简洁 IR v6：本题真实 DeepSeek 集成结果

2026-09-15，一次新的独立真实调用。**严格金标验收未通过；完整 JSON、契约校验和缺图阻断已通过此次真实验证。**

## 配置与证据

deepseek-flash，enabled/low，json_object，非流式，16,384 输出上限，300 秒超时，SDK 自动重试关闭。使用原始 1308×675 题图与匹配的录制 OCR，不调用业务数据库或实时 OCR。

一次语义调用、一次网络尝试，耗时 **71.779 秒**，finish_reason=stop。输入 8,338 tokens，输出总计 14,977 tokens，其中 reasoning_tokens=12,737；两者相减的非推理输出为 2,240 tokens。最终 JSON 为 7,496 字符，未截断。

代码、schema、提示词、金标、图片均与调用前冻结哈希一致，见 [指标](metrics.json) 和 [冻结记录](frozen.json)。没有修改测试后再补跑，也没有修改金标使本次结果通过。

## 已通过的行为

- 完整 JSON 可解析，独立 IR 和匹配契约均合法，明确 unmatched。
- 按第一问下两个图景、其余两问组织，四个目标均有输出；原文未再整题跨层重复。
- LLM 自行在四个对应节点标记图1～4缺失，没有把“如图”当成实际提供图形。
- 服务端返回 needs_confirmation、blocked=true、extraction.missing_figure、supplement_image 和完整缺图列表，保留候选 IR。没有求解、复核或后续生成调用。
- 本次没有 interior 字段，不再擅自填入 interior=true。

## 金标验收未通过的原因

1. 定义分支数量为 **4 / 2 / 2 / 2**，金标按当前“代入展开，不借其他条件消去分支”规则要求每图四分支。后面三图仍按已知被平分对角线收窄。此项属于抽取规则未遵守，不能直接称其数学结论必错。
2. 图1将未确认的“□ABCD”输出为 parallelogram，且未保留 ambiguous_symbol。与人工金标保留符号歧义的要求不符；缺图标记本身不能保证其余条件均可靠。
3. 比较器另有表示规范化差异：模型使用 diagonal_bisects，金标使用已知交点的 midpoint；模型没有另列独立 polygon fact；第（3）问另声明 k=2，而金标直接代入常数2。这些不能统称为模型漏条件或算错。当前比较器不是完整几何逻辑等价判定器，原始结构差异条数不等于独立错误数。

缺图阻断是正确预期行为，不是此次基准 passed=false 的原因；passed=false 来自严格金标比较。契约合法、金标一致、允许后续处理是不同结论。

## 产物

真实输出未编辑，保存在仓库内：

- [完整原始 JSON](../../../internal/solver-runs/understanding-v6-single-20260915/raw-response.txt)
- [候选展示与补图提示](../../../internal/solver-runs/understanding-v6-single-20260915/candidate.html)
- [实际请求](../../../internal/solver-runs/understanding-v6-single-20260915/request.json)
- [完整响应审计](../../../internal/solver-runs/understanding-v6-single-20260915/provider-response.json)
- [解析结果与阻断决策](../../../internal/solver-runs/understanding-v6-single-20260915/parsed.json)
- [结果汇总](summary.json)、[严格语义差异](diff.json)

本次只验证独立抽取入口，生产前端/API 未接入，不能宣称线上补图交互已经生效。推理区重复生成仍按用户要求观察，本轮没有为该问题追加指令或修改调用参数。
