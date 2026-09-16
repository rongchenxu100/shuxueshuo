# 数学字符串抽取：实现与 DeepSeek 七题验证

日期：2026-09-16。第一步代码已实现；相关离线回归 **243 passed，7 个真实调用测试未在离线回归中执行**。另行执行的一轮七题 DeepSeek 真实批次为 **1/7 通过**，未达到 7/7。后续保存响应的离线回放仍为 **1/7**，不能算作新增真实通过。

- [七题实际简洁输出与解析问题](offline-replay/outputs.html)
- [真实批次总结果](../../../internal/solver-runs/math-notation-deepseek-20260916/batch-summary.json)
- [后续离线回放总结果](offline-replay/summary.json)
- [冻结金标](../../../server/tests/solver/fixtures/math-notation-v1/README.md)
- [Schema 与字符数统计](measurements.json)

## 实现边界

新增独立 `problem-math-notation/v1`，版本由请求选择，LLM 无需输出版本字段。`root/children` 保留分问，`definitions/facts` 为字符串，目标只有必要字段；数组可省略。Schema 的 `description` 随请求发送，说明基础数学记法、比例方向、量词、继承及 `at`。例子仅使用独立的两点与中点，不注入七题、答案或特定缺图预期。

代码分为[契约与提示词](../../../server/shuxueshuo_server/problem_understanding/notation_contract.py)、[受限解析](../../../server/shuxueshuo_server/problem_understanding/notation_parser.py)、[绑定与类型检查](../../../server/shuxueshuo_server/problem_understanding/notation_compile.py)、[保守语义比较](../../../server/shuxueshuo_server/problem_understanding/notation_semantics.py)、[候选与产物](../../../server/shuxueshuo_server/problem_understanding/notation_service.py)。[版本分派](../../../server/shuxueshuo_server/problem_understanding/wire.py) 显式选择新旧契约，不猜测 JSON 形状。

解析覆盖七题金标所需的代数、几何、函数引用、量词、区间、逻辑分支、最值和 `at`。父问可见、兄弟局部对象隔离；同名对象按作用域绑定。函数和量词绑定保留在内部表示中。默认实数域标为 `code_default`，不由含 `a*x^2` 的公式推断 `a≠0`；几何构造的非退化要求记录为待证明义务。最值变量缺省保持未指定，不解释为所有字母共同优化。K 定义原文只供审查，执行关系必须由基础关系展开。

数学字符串不执行 Python，不对模型文本调用 `eval`/`sympify`。分词、AST、作用域、数字、幂、逻辑及代数展开均有限制；精确数字复用已有受限代数入口。比较只做可证明的基础代数规范化、逻辑组织及有界别名映射，不做几何求解或随意自然语言改写。未支持表达式报告路径、原字符串和错误。

所有结果保持 `candidate_only`、`solver_ready=false`。本轮**没有修改 Planner 输入输出，没有接入 Solver 或讲解流程**。旧契约及历史金标保留，七題入口默认新契约，旧调用显式选择旧版。

## 真实批次

使用 `deepseek-flash`、thinking enabled / low、JSON object、非流式、300 秒超时、16,384 输出 token，并发上限 3。每题恰好一次语义调用、一次网络尝试，均以 `stop` 正常结束；未自动修复、复核、切换供应商或重跑付费批次。总用量 83,392 tokens，包含供应商记入 completion 的推理 token，不能用输出字符数代替。

七题均通过外层 JSON Schema，题型匹配声明也均正确：五道已有题型 matched，K 与函数量词题 unmatched。失败发生在数学字符串解析、绑定或题意保留层，不是网络失败。

| 题目 | 真实验收 | 秒 | 总 tokens | 主要问题 |
| --- | --- | ---: | ---: | --- |
| 和平一模 | 失败 | 51.677 | 14,520 | 曲线、交点、E 的定义使用混合中文；`at` 写成解释句；另对 O 的定义提出疑问 |
| 和平二模 | 失败 | 37.776 | 11,610 | 公式后拼接“为常数”；“A在B左侧”“G在x轴下方”未转换；使用未约定的 `symmetry_axis`、`intersection` |
| 河西一模 | 失败 | 43.361 | 12,348 | 曲线、顶点、坐标及范围混写自然语言；出现 `min_N`、`√2` 的解析器缺口 |
| 南开一模 | 失败 | 40.023 | 12,871 | 混合中文、`M(m,1)`、目标 object 写成整个定义；②只写 `EG+FG=给定数`，丢失最小值约束 |
| 西青一模 | 失败 | 44.629 | 12,696 | A、B、C、D、M 的定义混入“且…在…上”等文字，无法作为受控关系编译 |
| K 倍四边形 | 失败 | 35.394 | 12,115 | 明确指出图1～4缺失，但用“为k倍四边形”替代展开关系，比例方向与逻辑分支未保留 |
| 函数与量词 | **通过** | 19.262 | 7,232 | 函数引用、量词、区间、目标均等价；未填 variables，按设计接受 |

不能将所有失败简单归咎于模型：`definitions` 的说明允许题内定义原文，但对普通对象定义只能采用受控记法的边界强调不足。本轮提示词未在看到返回后更改。下一轮需明确该边界，并用独立例子说明定义应用的展开；本轮未启动下一轮。

南开②和 K 题还存在独立于语法的语义遗漏。南开将“最小值为 `5*sqrt(10)/2`”变成普通等式，不能由代码补回；K 没有输出截线比例及“或”分支，不能内置专用 K 概念补齐。这两项不能通过兼容更多拼写解决。

K 的缺图是用户故意设置，**无需补图**。模型在根节点一条 `missing_figure` 中明确列出图1～4，识别本身成功；冻结代码先因数学非法而给出 `invalid_candidate` 阻断，未保留具体缺图码。后续离线修正后同时保留 `extraction.missing_figure` 和数学错误。完整用例仍失败，不能把“检测到缺图”当成完整提取通过。其余六题没有误报缺图。

## 离线修正与回放

仅针对已保存响应中的明确解析器缺口，增加 `√34` / `√(...)`、数字系数的省略乘号（如 `2a`、`2∠ABD`）、`min_N` 和带名称前缀的定义原文。不会把任意中文解释句当成可执行数学，也不会猜测 `AB` 是直线还是长度。

另补充代数展开前的资源限制；解析不完整时也保存规范化候选、标记 `complete=false` 的部分内部表示、校验报告与缺图阻断。解析失败仍不会暴露可用 IR。修改前涉及的实现保存在 [frozen-source](frozen-source/) 中，与真实批次记录的源码哈希对应；其余调用前实现未更改。金标、Schema、提示词及验收政策未更改。

[offline-replay](offline-replay/) 独立保存新解析结果、比较结果、产物与实现哈希。六题仍失败、一题通过。部分语法问题解决后会暴露原先被挡住的绑定问题，因此错误数量不等于剩余题意错误数。真实目录保持原样，离线结果不覆盖真实结果。

## 离线覆盖

七题金标在调用前全部通过 Schema、解析、绑定及自身语义比较。新旧抽取相关回归在最终代码上为 **243 passed，7 deselected**，包括：

- 可选字段、默认实数域、无下标最值、函数引用、量词局部绑定、父子继承和兄弟隔离。
- 条件顺序、等价符号、基础代数及一致别名变化。
- 反向比例、射线改直线、量词/区间/严格不等式改变、误加或删除 `at`、删除逻辑分支、不可见对象和非法表达式的拒绝/差异。
- K 题缺图与原有局部 `k≥1` 遗漏政策；严格等价和按政策接受分开记录。
- 实际请求的 Schema 注释、仅选定图片且 OCR 为空、无金标/答案/专属缺图提示，以及旧契约七题回放。

## 简化幅度

按 Unicode 字符、紧凑 JSON 计数，图片字节不计；新旧提示词采用相同 image-only 前提。详细数据见 [measurements.json](measurements.json)。

| 项目 | 旧版 | 新版 | 减少 |
| --- | ---: | ---: | ---: |
| 模型 Schema | 17,011 | 5,343 | 68.59% |
| 完整提示文字 | 23,487 | 8,658 | 63.14% |
| 七题金标总输出 | 23,063 | 5,694 | 75.31% |

单题金标缩短约 70.5%～78.9%。这衡量契约体积，不代表真实模型成功率提高；图片与 OCR 输入也较历史批次变化，不能直接归因于 prompt 改进。

## 复现与证据

真实批次目录下每题保存 `frozen.json`、`request.json`、`input-fixture/`、`preflight/`、`raw-response.txt`、`provider-response.json`、`call.json`、`parsed.json`、`diff.json`、`summary.json` 和内容寻址产物。冻结项包括代码、Schema、Prompt、图像哈希、gold、registry、policy 及请求预算。

保存响应离线复现（在 server 目录执行，输出目录须为新目录）：

```sh
uv run python -m shuxueshuo_server.problem_understanding.notation_replay \
  --batch ../internal/solver-runs/math-notation-deepseek-20260916 \
  --output /tmp/math-notation-review-replay
```

该入口不创建 provider、不联网。真实批次已经完成，本次不再发起模型请求。
