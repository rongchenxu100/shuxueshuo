# 抽取 schema 字符数复核

复核日期：2026-09-15。只读取请求、生成 schema 并比较，没有发起模型调用或修改运行逻辑。

统一口径：`len(json.dumps(schema, ensure_ascii=False, separators=(",", ":")))`，计算 schema 对象的紧凑 JSON 字符数，不包含外围请求字段、排版缩进、OCR、示例、图片或其他提示词。字符数不是 token 数。

| 版本 | schema 字符数 | 证据 |
| --- | ---: | --- |
| 9 月 14 日 08:16 发布包，problem-domain/v1 | 18,599 | 发布包 source revision 为 c7874f2a2eb890e086227f8ae2e321ef80656cdf；从该提交生成 provider schema |
| 线上实际首轮请求，problem-domain/v1 | 18,599 | 构建 6de57b87-fcd6-4977-8e99-2d3c4d7db01b 的请求产物 931bab2e-2224-4f07-9f50-39b08c695848，与上述发布提交生成的 schema 对象完全相等 |
| 第二步首次真实实验，problem-understanding/v1 | 32,838 | internal/solver-runs/understanding-v2-single-20260915/request.json |
| 第二步作者提示修复实验，用户选中的文件 | 21,389 | internal/solver-runs/understanding-v2-authoring-fix-20260915/request.json |
| 当前工作区生成的紧凑作者 schema | 21,389 | compact_schema(response_schema())；尚未实施最新 IR 简化设计 |
| 最新“整题 Problem IR＋匹配结果”简化设计 | 尚无可测实现 | 目前只改设计文档；不能把文档示例大小当成完整 schema 大小 |

发布包位置：`/private/tmp/shuxueshuo-release-p2-app-202609140816-amd64/release.env`，release ID 为 `p2-app-202609140816`。线上任务开始于 2026-09-14 20:24（北京时间）；这里证明的是发布包代码与该线上请求的 schema 一致，不据此声称掌握服务器确切部署完成时间。

线上实际请求由构建产物 API 读取，原始文件 SHA-256 为 `e732c4f07ac3458b1ff6807b48c362541769601bad071a6e1b877ddc5ed61852`。调用审计确认 provider 为 Doubao、模型为 doubao-seed-2-1-turbo-260628，首轮 thinking disabled。

## 实际发送与审计副本

- 两次 DeepSeek 实验均在 messages 的文本中包含 response_schema；解析后与 request.json 顶层 contract_schema 对象完全一致。
- DeepSeek 使用 json_object，SDK 调用不发送顶层 contract_schema。该字段只用于审计，不应把它与提示词内 schema 重复计数。
- 线上 Doubao 请求通过 response_format.json_schema.schema 发送 schema，contract_schema 同样是审计副本。response_format 连同外围 name/type/strict 包装共 18,688 字符；表中只计算其中 schema 的 18,599 字符。

## 排版与整段输入的区别

用户选中文件中的 schema 若独立使用 indent=2 排版，为 44,760 字符；紧凑对象为 21,389 字符。原文件嵌套缩进另有开销，不能用选中行数估算模型输入。

首次实验的所有消息文本合计为 68,007 字符；作者提示修复实验为 39,368 字符。这包括系统提示、观察、schema、示例、registry 等，不是 schema 自身大小，也没有计入图像输入。

21,389 相比 32,838 减少约 34.9%，仍比线上旧版 18,599 多约 15.0%。两版包含的职责不同：第二步仍要求转录、通用领域与匹配等复合结构；已确认的进一步简化尚待实现后重新测量。
