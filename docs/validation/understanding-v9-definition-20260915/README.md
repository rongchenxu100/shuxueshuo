# v9：定义分支与不确定图形提示修复

离线 **218 passed，6 skipped**（6项真实用例未启用，不计为通过）。没有新模型请求，不能宣称实际模型遵循度已提升。Ruff通过。

## 提示词

新增简短规则：可表达的未定选择使用any_of，不能以unstructured替代；直接代入列出分支，无需先选分支或求解；unmatched不免除完整IR。

修改已有合邻三角形few-shot，未另加本题专用示例：

- 定义第一支：邻边相等 **且** 夹角60°。
- 定义第二支：按顶点顺序邻边比2:1 **且** 夹角90°。
- 另给夹角60°；输出完整两支，不要求先推导排除第二支。
- 返回unmatched仍保留基础条件，uncertainties为空。

每支都是两个合法基础fact，由同一操作目录构造并经过真实解析器验证；独立定义变体测试继续保留。数学等价简化仍可接受。

图形未提供或无法确认是否提供，都报告missing_figure，在文字中说明是哪一种；用户负责确认/补图。候选提示改为“请确认或补充题目图片”。仍依赖模型填写标记，本次没有引入强制逐图检查字段或第二次视觉判断。

## 参数范围遗漏的处理

当前隔离IR校验不检查原文条件是否全部编码，单次smoke也没有模型修复循环。代码能解析不等式，但不能仅凭通用文字规则可靠确定定义参数的各问归属、等价范围及遗漏；本轮不新增硬编码检查。

用户明确接受本题三个局部k≥1遗漏，配置在 [acceptance-policy.json](../../../server/tests/solver/fixtures/understanding-v2/k-quad/acceptance-policy.json)。政策绑定金标修订并随新调用冻结，只控制测试验收，不发给模型、不修改金标、不改变通用语义比较。没有全局忽略下界。

仅此遗漏时：strict_semantics_passed=false，acceptance为accepted_with_omissions，验收可通过。错误下界、其他条件/定义遗漏、比例改变、缺图漏标和非法对象仍拒绝；过期政策在调用前拒绝。候选仍不是Solver就绪证明。

v8历史真实返回按此政策离线回放仍未通过：图1未展开和四幅缺图漏标仍存在。见 [回放摘要](v8-offline-reassessment.json)，旧调用产物未修改。

## 尺寸与产物

Schema 15,583字符不变，定义示例691字符（此前555），完整文字提示22,918字符（此前22,397）；图片字节不计。见 [测量](measurements.json)、[示例](example.json)、[离线记录](offline.json)。

源码：[prompt.py](../../../server/shuxueshuo_server/problem_understanding/prompt.py)、[acceptance.py](../../../server/shuxueshuo_server/problem_understanding/acceptance.py)。未部署，未切换生产入口。


## 后续真实验证

以上为修改完成时的离线记录。用户随后再次授权真实运行，新批次按批准遗漏政策通过，仍因四幅缺图阻断下游。见 [独立真实报告](../understanding-v9-live-20260915/README.md)。
