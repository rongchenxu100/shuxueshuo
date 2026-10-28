# 函数定义域 Q01：零次幂与约分前限制验收

Q01 已纳入函数专题并接通共同拍题求解链。零次幂和约分前分母限制分别保留来源，答案排除 $-4$、$1$。本地验收范围见下文；题型其他能力以[T2 设计](function-domain-problem-type-design.md)为准。

## 共同能力与边界

- 新知识节点 `integer-power` 属于初中知识集合，包含 `positive-exponent` 与 `zero-exponent` 条目。T2、M1 与 S3 沿用已有节点，没有为本题硬编码一条新方法。
- Stage1 准入扩展到固定非负整数指数 0～12，嵌套幂预算为 64；正整数幂保留底式限制，零次幂增加底数非零条件。零次幂底数、分母和根式限制仍须满足现有仿射范围。
- 新条件 `zero_power_base_nonzero` 使用 `integer-power#zero-exponent` 依据，经 `domain_zero_power_conditions` 正式能力进入同一条件求解、求交集和原式独立验证链。
- Q01 的两个原式位置分别为 `[1,1,1]` 和 `[2]`，均来自 `/root/definitions/0`。条件、位置高亮、解集和端点检查持续保留零次幂／分母的各自来源。
- 读题允许原文 `y=...` 对应规范函数 `f(x)=...`，并允许乘法与分式的等结构分组。比较保留每个原始除数和幂，不允许约分、删掉零次幂或改变指数；`x^{1}2` 不会被误读成 `x^12`。
- 四个数学交互为找限制位置、列条件、解条件、取交集。两个禁取点都有具体原因；限制位置、条件和解集用并列项目展示，不用箭头误示两项之间的推导关系。
- 本题只验证零次幂、正整数幂及原分母限制；M6 求参和其他限制条件的开放范围见 T2 设计，不能由本题成功外推。

## 真实图片与求解证据

用户本轮上传的图片原样保存于[来源目录](../internal/senior-high/source-images/function-concepts-q01/manifest.json)，未重绘、裁切或注入 OCR 答案。图片 SHA-256：`d0882cf0c523a8f4773276d4e02e49d7fa03603fac6f604a284d690195a34405`。

[真实照片录制](../server/tests/search/fixtures/function-domain/q01-recorded-20261026/recording.json)完成 extract + review **两次语义调用、两次网络尝试**，总耗时 **15.378 秒**。结果通过 reviewed candidate 与特征校验，原文保留 `y=(x+4)^0\frac{x^2-1}{x-1}`，规范定义为 `f(x)=(x+4)^0*(x^2-1)/(x-1)`。

随后将该录制交给正式照片 API 与共享 PostgreSQL 执行链，结果为 **solved，4 个数学步骤、4 个数学交互**。最终导出运行 ID：`a0828f4cbe654cc9bcc5686e8c05d9bc`。后续自动化使用录制重验，不计作额外模型调用；本轮没有另做拍题浏览器上传验收。

冻结的[执行与教学证据](../site/data/graph-walk/function-concepts-q01.evidence.json)由正式课程导出器产生，生成[专题课包](../site/data/graph-walk/function-concepts-q01.json)、[AI 回放](../site/data/graph-walk/function-concepts-q01.replay.json)和[题目页面](../site/topics/function-concepts/q01/index.html)。专题与拍题共享同一数学步骤及交互协议。

版本记录：

- `bundleVersion`：`["stream","8f3a0463814094246c4b4d3a9b4becf23468bbe2de452444aa9fe8626d0de1b4","90682692a67de142b65331abeee3ba9ffac9bcfbfcde0cb4facea7b883105aaf","a0828f4cbe654cc9bcc5686e8c05d9bc","/root/goals/0"]`。
- Q01 native `contract_hash`：`a6247acf31a3c4e08e98c3dbabd2211e7b9ad7b1eb9b0997d1f9ff329a897847`。
- 公共 `content_version`：`32dd1d8a3c7f123ad379dda7ae2c0592480a34751761bc4c19085aec3fbab21f`。
- 当前公共图谱 **93 节点、288 条边**，公共内容 **41 道题、52 条路线、273 步**。函数专题仍为 5 个题型分组，其中定义域组有 Q15、Q01 两题，其余组未加入练习。


## 验收边界

本地覆盖真实原图提取／复核、正式照片 API 录制回放、数学与教学、自己做及 AI 各 7 步、模式进度隔离。登录保存、拒绝跳步、幂等和恢复由 API 集成测试验证；未据此声明浏览器登录、实体手机或生产部署。
