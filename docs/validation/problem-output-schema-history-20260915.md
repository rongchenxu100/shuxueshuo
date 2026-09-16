# 题目抽取输出 schema 变化历史

核查日期：2026-09-15。日期来自 Git 提交记录；未提交改动以实际请求审计和当前工作区为准，不能混作已部署版本。

## 1. 先区分两个名称

- **代码中的 Solver `ProblemIR`**：位于 [problem_models.py](../../server/shuxueshuo_server/solver/problem_models.py)，有 problem_id、pattern、problem_type、symbols、original_text、constraints、data 等字段。它是 Solver 的输入模型，不是 root/children 形式的抽取输出。
- **LLM 抽取输出 `problem-domain/v1`**：位于 [problem_domain.py](../../server/shuxueshuo_server/solver/extraction/problem_domain.py)，有 schema_version、problem_id、family_id、source、root；root 和 children 内含 source_text、entities、facts、goals。它通过 [problem_domain_projection.py](../../server/shuxueshuo_server/solver/extraction/problem_domain_projection.py) 转换为 Solver ProblemIR。

最近讨论中把后者也简称为“Problem IR”，造成了名称混用。最新简化设计应理解为“LLM 生成一份整题抽取 IR 与匹配结果，代码转换到 Solver ProblemIR”；不是要求 LLM 直接生成运行时路径、Solver data 或测试期望答案。

## 2. 可核实的时间线

| 时间／提交 | 输出或模型 | 发生了什么 |
| --- | --- | --- |
| 2026-05-25，759fd407 | Solver ProblemIR | 当前 problem_models.py 的最早 Git 记录，早于多模态抽取输出；不是本次模型请求 schema 的起点 |
| 2026-06-09，32bfcf77 | canonical authored fixture → Solver ProblemIR | 统一题目 fixture 的 canonical 输入；不能据此认为 LLM 此时已直接输出该运行时模型 |
| 2026-08-07，cbd94e52 | problem-extraction-candidate-patch/v1 | 较早的多模态请求输出 classification、transcription_lines、scope/entity/fact/goal candidates、ambiguities 和 evidence 引用；当时提示词明确不让模型输出 Solver ProblemIR |
| 2026-08-10，8d98800e | **problem-domain/v1** | 改为一份完整领域树，包含 root/children 和必填 family_id；引入正式 JSON Schema、定向 problem-repair/v1 及到 Solver 的投影 |
| 2026-08-12，36592efb | problem-domain/v1 | 调整小问编号的语义规范化；抽取输出 schema 未变 |
| 2026-09-13，bd365add | problem-domain/v1＋独立 source-review/v1 | OCR 从硬否决改为辅助差异，增加按需原图复核、预算与审计；领域输出 schema 未变，复核是另外一种请求 |
| 2026-09-14，c7874f2a；08:16 发布包 | problem-domain/v1 | 修复复核恢复等产品链问题；领域输出 schema 未变，已核对线上实际请求 |
| 2026-09-15，44cbe311 | problem-domain/v1，DeepSeek 视觉 | 模型由豆包切到 DeepSeek；接口从 json_schema 模式切为 json_object＋提示词内 schema；**业务输出 schema 没变** |
| 2026-09-15，2858a748 | problem-domain/v1 | 表达式拼写规范化、提示去样本化与独立测试；**输出 schema 仍没变** |
| 2026-09-15，当前未提交第二步 | **problem-understanding/v1** | 新增 transcription＋domain＋match 三子对象；domain/v2 去 family，增加通用 QuantityTerm、题内定义模板、逐条来源覆盖、独立转录修订及匹配绑定 |
| 同日作者提示修复实验 | problem-understanding/v1，authoring/v2 | 提取共享 schema 定义、压缩观察数据、自动反转来源覆盖表、补充命名及模板示例；没有消除三子对象和细粒度结构化的负担 |
| 当前已确认的新设计，尚未实现 | 整题抽取 IR＋匹配 | 回到 root/children 的单份整题结构，简洁 fact；取消模型命名空间、逐条来源关联及专用题内定义类型；OCR 保留但只传简洁辅助信息 |

因此，如果“一周前”指 9 月上旬的图像抽取链，它已经使用 8 月 10 日引入的 problem-domain/v1。没有证据表明该 schema 是最近一周才创建，或最近一周不断扩大。真正显著改变首包结构的是今天未提交的第二步实现。

## 3. 不只比较版本号，也比较 schema 内容

逐一读取上述六个提交的 problem_domain.py，调用 problem_domain_provider_schema()，同时检查各提交当时 registry 的四个 family ID。六份结果不只是字符数相同，排序后的 schema JSON 哈希也完全相同：

| 提交 | Provider schema 字符数 |
| --- | ---: |
| 8d98800e | 18,599 |
| 36592efb | 18,599 |
| bd365add | 18,599 |
| c7874f2a | 18,599 |
| 44cbe311 | 18,599 |
| 2858a748 | 18,599 |

统一 SHA-256：`7d6b958d7632c67e60eca5fb783aeff101003bf5dcfbad415aff51f74c274d65`。

逐提交测量记录见 [JSON 结果](problem-schema-history-measurements-20260915.json)。

方法说明：在当前依赖环境加载各历史提交中的 schema 生成代码，分别核对当时 registry 成员和对应 family_id；这是 schema 内容重建，不是重跑整套历史服务。canonical schema 为递归表示，provider schema 展开有限层级以适配供应商，两者字符数不能混用。本表统一采用实际请求使用的 provider schema，紧凑 JSON、中文不转义，不是 token 数。

第二步首次实验的模型 schema 为 **32,838** 字符；作者修复后为 **21,389** 字符。它们覆盖的是新的复合契约，并非旧 v1 的同一 schema 单纯增加空白。最新设计还没有完整 schema 实现，不能给出已达到的压缩数字。详细测量口径见 [schema 字符数复核](schema-size-20260915.md)。

## 4. 哪些复杂性原来就有，哪些是今天新增

| 内容 | 原有 problem-domain/v1 | 今天的未提交第二步 |
| --- | --- | --- |
| 小问层级 | root/children 已有 | 额外出现转录 Part 树和领域 Scope 树及连接 |
| 对象与条件 | 专用 entity/fact/goal | 通用递归量表达和 relation 外层包装增加 |
| 题型 | family_id 必填 | 独立 matched/unmatched 与修订／registry 绑定 |
| 原文 | scope.source_text | 稳定 SourceUnit、逐实体／fact／goal 来源引用和覆盖表 |
| 定义 | 没有本次新增的通用定义模板契约 | 形参、polygon_vertex、局部 witness、definition_use、展开预算 |
| Solver 内部身份 | 代码分配 | 代码仍分配，但模型被要求填写更多前缀和交叉引用 |

8 月 7 日的更早 candidate 方案已经有 evidence 引用，不能说“来源追溯历史上从来没有过”；但今天的 source_unit_ids／转录—领域逐条覆盖，是区别于旧 v1 scope.source_text 的新增机制。

这解释了“模型为什么开始反复组织格式”：不仅新增了数学表达能力，也同时增加了模板、索引和复合产物编写要求。旧 v1 的稳定结构可作为简化基础，但不能原封不动恢复就认为满足当前目标：它仍需补齐角相等／比例、面积和正切等基础表达，并允许明确 unmatched。

## 5. 当前边界

用户已确认：以 8 月 10 日的 problem-domain/v1 输出结构作为简化实现基线，只补必要的几何表达和 unmatched 等能力；不是回滚整个代码版本。DeepSeek、独立视觉复核、预算、审计和恢复等后续改进保留。具体范围见[简化设计第 1.0 节](../geometry-authoring-simplification-review.md#10-以旧输出结构为基础不回滚整个版本)。

今天的独立 problem_understanding 包仍是未提交的阶段二实现，没有切换生产入口。近期讨论的简洁 fact、root/children 首包和简洁 OCR 仅完成设计更新，后续需要同步修改 schema、提示词、解析器、验证器与测试。历史请求文件和失败结果保持不变，不用修改旧审计制造“新版本已通过”。
