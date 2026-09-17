# Review 提示词与请求上下文调整

日期：2026-09-17。实现及离线验证完成；本轮没有模型调用，没有改写历史候选、金标、图片、复核响应或冻结成绩。仍为 `candidate_only=true`、`solver_ready=false`。

后续用户授权两题真实 review 已完成，详见[和平一模／南开一模 thinking 对照](../math-notation-review-two-20260917-065500/README.md)：和平总 token 降 40.00%，南开总 token 升 3.68%；思考重复与视觉确认风险尚未完全解决。下文保留提示词调整阶段的离线记录。

## 根据真实日志修什么

上一批六次 review 输出共 41,798 token，其中 reasoning 41,732、可见 JSON 66；reasoning 占输出约 99.84%。累计 review 调用时间为 205.625 秒。日志反复讨论实数域、常数、连接声明和目标枚举；南开还以题型常识消除持续的视觉疑问。详见[原始审查](../math-notation-review-repair-20260916-222053/review-thinking-audit.md)。这些发现支持改进输入和规则，不足以量化能省下多少 token。

| 问题 | 本次改动 |
| --- | --- |
| 候选没有完整字段说明，复核猜测目标 kind 是否合法 | 从当前候选 Schema 自动生成 `candidate_contract`：六类目标、必填/可选字段、at、variables、in_terms_of、继承规则及匹配含义；共 1,417 字符，避免发送重复的大 Schema |
| 不知道代码已检查什么 | `code_validation` 来自实际解析报告，核对候选修订、契约、图片来源、注册表和成功状态；修复后随新修订更新，失败或过期数据不能声称通过 |
| 反复怀疑允许省略的内容 | 明确默认实数域、常数说明、最值下标与变量提示、字段混写、冗余连接声明；注册表 primitive 名称不是候选要补的字段 |
| 已对应条件被反复推敲 | 一次双向覆盖八类来源差异；疑点局部回看，没有新证据不重复检查已确认项，不求解来消除疑问 |
| 用常见题型代替看清模糊符号 | 回看后仍无法确认必须 uncertain；摘录只保留可辨认部分，不把推测写成原文；新增模糊/清晰关系对照例 |

候选仍是当前采用的模型原始 JSON，经严格解析再序列化。没有将内部 IR 或规范化候选交给 review。代码合法不等于来源正确：摘要明确原图一致性与题型语义适配尚未检查，数学等价仅有有限能力。全部八类来源检查、完整原图、表达目录和完整注册表继续保留。

## 可直接审阅的文件

- [Review 模板](../../../internal/llm-prompts/problem-math-notation-review.md)
- [八个独立 few-shot](../../../internal/llm-prompts/problem-math-notation-review-few-shots.json)
- [实际构建的契约与代码检查摘要示例](review-context-example.json)
- [请求构建代码](../../../server/shuxueshuo_server/problem_understanding/review_contract.py)
- [完整设计](../../math-notation-repair-design.md)

两个新增 few-shot 用文字模拟“看不清/看得清”的情境，不是图像训练样本，也不是模型真实识别能力的评价。它们只进入 review；抽取和 repair 不带这组行为例。没有把七题内容、金标、答案、OCR 或首轮 thinking 放进请求。

## 大小与成本

离线使用六次既有 review 的同一候选、图片和注册表构建新请求，测量 messages 内文字字符数，不含图像编码；不是 tokenizer 计数。数据与模板、实现哈希见[机器记录](request-size-comparison.json)。

| 题目 | 原请求文字字符 | 新请求文字字符 | 增幅 |
| --- | ---: | ---: | ---: |
| 和平一模 | 13,063 | 16,131 | 23.49% |
| 和平二模 | 13,164 | 16,232 | 23.31% |
| 河西一模 | 13,103 | 16,171 | 23.41% |
| 南开一模 | 13,303 | 16,371 | 23.06% |
| 西青一模 | 13,035 | 16,103 | 23.54% |
| 函数量词 | 12,768 | 15,836 | 24.03% |

每次增加 3,068 字符，来自补充说明、契约摘要、校验摘要及两个示例。K 题已在 review 前缺图阻断，没有实际旧 review 请求可供比较。

这次调整是用明确上下文减少无效思考，**没有实测证明总 token 或耗时下降**，也不能把输入字符增加量当成 token 增量。现有 provider 已使用 thinking enabled、reasoning_effort=low；未调整该配置、16,384 输出 token 上限、300 秒超时或调用预算。后续若对照测试没有降低重复思考，应根据检出率与成本继续调整，不能把更长提示词本身当作改善证据。

## 离线门禁与尚未验证的部分

相关回归 **512 passed、7 deselected（9.18 秒）**，静态检查及 diff 空白检查通过。在既有 502 项基础上新增 10 项：Schema 摘要的枚举/字段含义一致性，八种缺失/错误/过期校验上下文拒绝，以及模糊/清晰例的录制停止与通过行为。既有测试补强修复后摘要修订更新、原始候选不变、例子实际注入与三类请求隔离。

```sh
uv run pytest -q tests/solver/test_math_notation*.py tests/solver/test_solver_test_profiles.py tests/solver/test_deepseek_vision_empty_retry.py -m 'not live_llm'
```

录制中的 uncertain 能阻断流程，不代表模型一定能看出模糊符号；因此 [MN-003](../../math-notation-known-issues.md#mn-003原图复核用题型常识消除了持续的视觉疑问) 仍开放。六个原始 review 候选已通过当前金标，不能用它们测错误检出率。后续实际评价需同时覆盖正确候选、单点篡改但仍可解析的错误候选，以及真实可读/模糊图片，记录误报、漏检、不确定处理、reasoning token 和耗时。本轮没有启动新付费批次或 24 例真实模型评价。
