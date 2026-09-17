# 原题文字保存与展示

2026-09-17。按用户纠正，列表展示原题中文叙述和公式，不用数学候选或 IR 拼接题目摘要。本轮无付费模型调用，没有改写已有候选或七题冻结响应。

## 实现

- `problem-math-notation/v1` 顶层新增 `original_text` 字符串，保存完整题干转录。新抽取模板及六个独立示例要求同次输出原文和 `root`；历史候选可缺省，数学节点不恢复 `source_text`。
- 原文随不可变候选 JSON、来源版本、内容哈希及原始响应保存；规范化保留原文，但数学编译及语义比较不把转录当成条件。没有新增数据库迁移。
- 原图复核同时检查转录；独立 `wrong_transcription` 诊断仅授权修改 `/original_text`，缺失字段的空 JSON Pointer 不扩大到整题。未授权时不能以数学等价为由改写原文，修复后重新复核。
- 列表只截取原文开头。题意页将原题文字和数学候选分别展示，保留换行并转义 HTML；历史候选无原文时显示原图与明确提示，等待用户重提或复核，不自动付费补全。
- 补图产生新来源后不能沿用旧候选的原文；人工修订原文改变候选哈希并撤销当前复核。

## OCR 边界

新 `problem_understanding/v1` 仅运行 `source`、`extraction` 两个阶段，直接把全部所选图片给视觉模型，不调用独立 OCR，也不将旧 OCR 结果注入请求。此次原文转录由同一次视觉抽取完成。

旧完整生成入口仍运行 `observation`。其题干来自 `ProblemDomain` 节点的 `source_text`，通过 `graph.original_text_lines` 和运行时投影传至网页的 `original_text`。共享 OCR 组件没有被删除，新流程仍未接入生成解析页。

## 验证

- 相关后端全量运行：633 passed、1 failed、7 live 用例排除；唯一失败是旧 Schema 形状快照尚未列入新增顶层字段。保留冻结快照不变，更新测试明确断言仅增加 `original_text`，随后该测试文件 **27 passed**，无待处理失败。
- 真实 PostgreSQL 门禁包含七题历史响应保存与查询，以及新增原文入库、完整内容回读、修订后哈希变化与复核失效、新来源清空当前文字、数学解析失败仍保留转录；全部实际执行，没有跳过数据库测试。
- 录制 review/repair 测试包含缺失原文补写、错误原文纠正、数学内容越界拒绝、非授权等价改写拒绝、修订后再次 review。录制验证不代表真实模型转录准确率。
- 前端 **46 passed**；类型检查、相关 ESLint、生产构建通过。相关后端 Ruff、`git diff --check` 通过。
- 现有七题冻结响应没有原文字段，测试仍按原响应回放，未为通过测试伪造题干。数学语义验收口径未变化。

后端测试使用独立 PostgreSQL 实例 `understanding-p1-test`，目录 `/private/tmp/shuxueshuo-understanding-p1-20260917`。全部模型供应商替换为录制响应，测试中确认新请求图片集合、空 OCR 文本，以及 review 收到的是当前候选中的原文。

实现说明见[阶段一实现文档](../../math-notation-stage-one-implementation.md#原题文字与-ocr)，可审阅[抽取模板](../../../internal/llm-prompts/problem-math-notation-system.md)和[Schema](../../../internal/schemas/problem-math-notation-v1.schema.json)。

## 本地生效

15:03 重启本机整套应用。`services-doctor` 正常：API、前端、Worker、Publisher 部署指纹均为 `5c9c22b648cc92939b6a8ec89f35480f1362baa6643121d857d3875de226e1d9`，数据库仍为 `0003_problem_understanding`，965 个产物完整，心跳正常、无待发布消息或过期租约。

浏览器检查题意页已分别显示“原题文字”和“数学候选”；缺失原文的历史记录明确提示可通过重新提取或复核补充。工作台旧流程题目继续显示原题叙述，新流程尚无转录的历史候选显示原图缩略图及“原题文字待提取”，不再展示拼接的数学 IR。新增转录展示与保存使用录制/人工测试验证，没有新模型响应可宣称原文准确率。
