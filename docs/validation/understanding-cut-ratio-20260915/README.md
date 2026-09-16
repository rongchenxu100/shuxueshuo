# v8：截线关系与单次 DeepSeek 验收

已实现 `cut_ratio`，由代码处理交点；同步更新定义、OR、局部参数、层级、首选操作及字段示例。不修改生产入口、五题金标或旧真实调用记录。

离线：207 passed，6 skipped（未启用的真实用例，不计为通过）。新增19项截线及整题等价回归。Ruff与diff检查通过，见 [离线记录](offline.json)。

尺寸见 [measurements.json](measurements.json)，新schema为15,583字符，完整文字提示22,397字符，OCR辅助955字符（不含图片字节）。新增字段使schema略增，目标是减少模型决策负担，不以字符最少为验收指标。

真实批次：`understanding-v8-cut-ratio-single-20260915`。**未通过，141.131秒**。一次语义调用使用了两次受控网络尝试。固定一次语义请求、最多两次受控网络尝试，不自动修复/复核/回退。`deepseek-flash`，enabled/low，json_object，非流式，16,384 tokens，300秒，图片detail=high。

缺图仍须保留完整IR并阻断后续处理；抽取金标通过不代表补图完成或Solver可求解。推理区重复编写行为只观察。

## 真实结果

|尝试|耗时|结束原因|completion / reasoning tokens|正式输出|
|---|---:|---|---:|---:|
|1|76.420秒|length|16,384 / 16,384|0字符|
|2|64.201秒|stop|12,590 / 11,405|3,249字符|

两次请求使用同一份图片、提示词与配置，第一次没有可见内容，Provider按原有受控策略重试；没有SDK重试、领域修复、视觉复核或供应商回退。累计usage为46,122 tokens（prompt 17,148；completion 28,974）。不能只计算第二次用量，也不能称作一次底层网络请求。

第二次IR和匹配契约合法，明确unmatched，但整体语义验收失败：

1. 图1将“AECD为k倍四边形”放入unstructured，未生成相应定义事实。这不是等价分支简化。
2. 图1、图2、（2）的局部k遗漏k≥1；根层原文保留了它，但原文不能替代结构化条件。
3. 四幅图全部漏标missing_figure。模型未给出该标记，因此现有缺图门禁没有触发（continuation.blocked=false）。隔离结果仍为candidate_only、solver_ready=false，未执行下游；不能宣称本次缺图拦截成功。

正确表现：图2、（2）、（3）实际使用cut_ratio，没有新增辅助点名；数字2直接代入；多图/单图层级及局部参数正确；没有默认interior=true。没有为了通过而删金标条件。

在独立诊断副本中仅补回缺图与k≥1后，图2、（2）、（3）与金标等价，图1仍不等价。这说明这些位置的两分支和cut_ratio本身不是失败原因。诊断副本没有被采用，原始返回与本次passed=false保持不变。见 [结构化诊断](live-analysis.json)。

## 推理行为观察

首次推理35,246字符，全部输出预算用于推理并以length结束。第二次推理22,283字符，仍反复在“未知分支能否表达”“是否要声明对象”“是否缺图”之间选择。第一轮曾识别缺图，第二轮则因无法确定而不填写缺图；没有理由把这种行为当作成功识图。

因此本轮只证实直接关系能被模型使用、能被代码校验和比较；未证实响应更快或缺图判断更稳定。重复构造JSON的行为仍只观察，未新增限制推理区指令。

## 产物

- [完整批次摘要](../../../internal/solver-runs/understanding-v8-cut-ratio-single-20260915/summary.json)
- [冻结实现、金标及图片哈希](../../../internal/solver-runs/understanding-v8-cut-ratio-single-20260915/frozen.json)
- [实际请求](../../../internal/solver-runs/understanding-v8-cut-ratio-single-20260915/request.json)
- [两次响应及usage审计](../../../internal/solver-runs/understanding-v8-cut-ratio-single-20260915/call.json)
- [原始正式返回](../../../internal/solver-runs/understanding-v8-cut-ratio-single-20260915/raw-response.txt)
- [原始语义差异](../../../internal/solver-runs/understanding-v8-cut-ratio-single-20260915/diff.json)
- [候选渲染](../../../internal/solver-runs/understanding-v8-cut-ratio-single-20260915/candidate.html)

本次测试后未修改冻结代码或金标，未再发起真实调用。生产入口、数据库、HTTP API和部署不在本轮范围。
