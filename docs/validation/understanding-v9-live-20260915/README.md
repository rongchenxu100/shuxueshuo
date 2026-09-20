# v9 单次真实 DeepSeek 抽取：按批准政策通过

2026-09-15，批次 `understanding-v9-definition-single-20260915`。本次由用户再次明确授权，使用冻结的v9提示词、同一原图与录制观察、已确认的参数范围遗漏政策。没有修改金标或沿用历史响应。

**验收通过，分类 accepted_with_omissions；严格语义比较仍未通过。** 唯一放行的是此前批准的图1、图2、（2）三个局部k≥1遗漏，其他条件仍按原金标比较。

## 结果

- 合法整题JSON，匹配结果unmatched、family_id=null。
- 图1完整展开AECD定义：外层两种对角线平分选择，各含两种截线比例方向，合计四种组合。采用嵌套OR，比较器正确接受；没有退到unstructured。
- 图2、（2）、（3）使用已给平分条件及两个cut_ratio方向，数学表达比较通过（除已批准遗漏）。
- 原题命名O保留，没有新增P/X等辅助点名；（3）直接代入常数2，未额外声明k=2。
- 图1～4全部标记missing_figure。continuation=needs_confirmation、blocked=true、error_code=extraction.missing_figure。保留候选，等待用户确认或补图，未执行求解、投影或独立视觉复核。

## 调用与耗时

配置：deepseek-flash，enabled/low，json_object，非流式，16,384 tokens，300秒，图片detail=high，SDK自动重试关闭。

|网络尝试|耗时|结束|completion / reasoning tokens|正式输出|
|---|---:|---|---:|---:|
|1|75.448秒|length|16,384 / 16,384|0字符|
|2|68.939秒|stop|15,835 / 13,856|6,464字符|

总耗时145.262秒，一次语义调用、两次受控网络尝试。第一轮空返回触发同请求重试，没有给第二轮注入金标、推理或修复反馈。累计用量49,859 tokens（prompt17,640，completion32,219）。没有第三次请求、自动修复或供应商回退。

此次结果改善了定义展开和缺图报告，但首轮仍推理耗尽；不能宣称速度或首轮成功率已经改善，单次通过也不证明稳定通过。

## 审计

- [批次摘要](../../../internal/solver-runs/understanding-v9-definition-single-20260915/summary.json)
- [冻结配置与代码哈希](../../../internal/solver-runs/understanding-v9-definition-single-20260915/frozen.json)
- [实际请求](../../../internal/solver-runs/understanding-v9-definition-single-20260915/request.json)
- [两次调用、原始响应和usage](../../../internal/solver-runs/understanding-v9-definition-single-20260915/call.json)
- [正式JSON](../../../internal/solver-runs/understanding-v9-definition-single-20260915/raw-response.txt)
- [严格差异](../../../internal/solver-runs/understanding-v9-definition-single-20260915/diff.json)
- [批准政策下的验收](../../../internal/solver-runs/understanding-v9-definition-single-20260915/acceptance.json)
- [候选页面](../../../internal/solver-runs/understanding-v9-definition-single-20260915/candidate.html)
- [简洁统计](results.json)

代码哈希与调用前冻结值一致。没有部署、切换生产入口或改变历史批次结论。

后续仅分析原始记录：[两次推理详细分析](reasoning-analysis.md)，无新模型调用或实现修改。
