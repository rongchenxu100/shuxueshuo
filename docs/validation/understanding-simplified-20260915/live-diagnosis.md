# 单次真实门槛未通过

本次实际向 DeepSeek 发送一次语义请求、一次网络请求；没有自动修复、独立复核、供应商回退或第二批实验。耗时 75.477 秒。

|项目|实际值|
|---|---:|
|模型|deepseek-flash|
|thinking / reasoning_effort|enabled / low|
|输入 tokens|7,601|
|completion tokens|16,384|
|其中 reasoning tokens|14,399|
|非 reasoning 部分（按差值）|1,985|
|总 tokens|23,985|
|finish_reason|length|
|最终业务文本|5,628 字符，包含排版空白|
|JSON 结果|未闭合字符串；第（3）问 source_text 开头截断|

输入 schema 已压至 15,039 字符，完整文字提示 20,036 字符，但此次 enabled/low 仍消耗大量推理输出预算。结果不是 OCR 网络故障，也不是代码将合法 IR 错判为 Solver 不支持：模型已经写出 unmatched，随后最终 JSON 因输出上限被截断，独立解析器正确阻断。

没有从截断 JSON 抽取片段并保存成“合法 IR”，没有执行金标语义比较，更没有 Solver 投影。原始业务文本和模型完整返回保存在审计包中，候选采用状态为 false。

可见业务输出另有两个需后续处理的问题：

1. 将图1不确定的 □ABCD 写成 parallelogram；人工金标保留该符号歧义。
2. 在缺少四幅图的情况下写入 `interior=true`；人工金标不默认该空间条件。

这些只能作为对可见输出的诊断，不能声称完成了整题语义对比。即使手工补齐 JSON，也不能据此宣称验收通过。冻结后未修改 prompt、schema、编译器或金标迎合输出。

本步代码、离线回归和压缩产物已交付；“单次真实抽取通过”的完成条件未满足。后续若要改变输出预算、思考策略、进一步压缩操作目录或增加实验次数，应作为新的明确实验方案处理，不计入此次结果。

可核查：[live-summary.json](live-summary.json)、[live-metrics.json](live-metrics.json)、[live-parsed.json](live-parsed.json)、[live-frozen.json](live-frozen.json)、[完整审计 ZIP](live-audit.zip)、[冻结核验](freeze-verification.json)。
