# 数学记法抽取金标 v1

七题 JSON 从已确认的 `docs/seven-problem-math-notation-review.md` 前七个题目示例整理，真实调用前冻结；使用 `understanding-v2/integration-images-20260916` 的选定图片复核。不是模型返回，不随模型表现修改。

线上的模型输出没有 `schema_version`；请求以 `problem-math-notation/v1` 显式选择 Schema、解析与比较。`definitions/facts` 为字符串，省略数组视为空，`variables` 和最值下标可省略，代码默认实数域不属于强制输出。

K 题有意缺少图1～4；必须在对应分问报告缺图并触发后续阻断。其 `k≥1` 局部遗漏政策沿用此前用户确认，仅将允许项转换成数学字符串并绑定本版金标哈希；严格等价与政策接受仍分开记录。

默认七题入口现在使用本契约。旧版可显式传入 `--contract problem-domain/v2` 回放，不做自动格式猜测。现阶段仅覆盖抽取、受限解析、内部对象绑定与保守语义比较，不代表 Planner/Solver 接入。
