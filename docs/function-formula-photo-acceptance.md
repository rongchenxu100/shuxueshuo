# FR-T1 原图拍题验收记录

日期：2026-11-01。已补齐 **20 道原图题的真实提取、复核、数学执行与课程导出**，连同 A0 的 B05-v2，共有 **21 道题、22 个原始目标**的照片证据。W07 原图缺“非零”条件，按原图保留冲突；用户批准的修订版课程已完成，两种来源分别记录。这批题均参与过开发，独立新题照片 S7 尚未完成，尚未部署。

## 范围与结果

| 默认方法 | 具有真实照片证据的题源 | 本轮结果 |
| --- | --- | --- |
| 换元法 | B05-v2、W09、B05-v1、W11 | B05-v2 沿用 A0 证据，另三题新增；完整保留根式半轴、分式禁取点 |
| 配凑法 | B05、W02、B05-v3、W04 | 四题新增；B05-v3 两问独立，先求 f(0)，再恢复解析式 |
| 待定系数法 | B04、W01、W12、B04-v、W10 | 五题新增；保留全部候选，W10 正确识别为二次函数并完成原不等式目标 |
| 构造方程组法 | B06、B06-v、W03、W05、W06、W14 | 六题新增；保留声明范围与指数右式。W07 原图冲突另记 |
| 赋值法 | B07、B07-v | 两题新增；完整保留两个变量的全称量词与实数范围 |

新完成的 20 道题含 21 个原始目标，所有已开放方法经共同执行器及独立数学验证通过，最终答案另与调用前冻结的规范题源核对，包括候选函数全集、原题所求数值／解集及确定范围。六道双方法题中，本轮新增五道的两条路线；B05-v2 沿用既有验收。没有修改静态专题的题量、分组、选法交互或前一专题。

## 原图与真实调用

从用户提供的原页选取题干区域，保存原页哈希、多边形、裁片哈希、旋转角度及送模 PNG。横向照片的 90° 旋转有记录，不重新排版为“照片”。所有输入通过实际产品的图片预处理和提取／复核工作流；规范题源及预期答案只用于事后核对，未传给模型。

- [首批 11 题的来源与冻结金标](../internal/senior-high/source-images/function-formula-photo-20261101/manifest.json)
- [第二批 10 题的来源与冻结金标](../internal/senior-high/source-images/function-formula-photo-extra-20261101/manifest.json)
- [W05、W12 完整重框记录](../internal/senior-high/source-images/function-formula-photo-recrop-20261101/manifest.json)
- [24 次工作流尝试及调用统计](../internal/solver-runs/function-formula-photo-call-summary-20261101.json)
- [20 题最终执行、课程文件及金标核对结果](../internal/solver-runs/function-formula-photo-acceptance-20261101.json)

本轮共 24 次真实工作流尝试、46 次语义调用、46 次网络尝试；结果为 20 次 `reviewed_candidate`、1 次 `workflow.oscillation`、3 次 `needs_confirmation`。首次 21 张裁片中 17 张通过，W01 重试一次、W05／W12 重新框选后通过，W07 保持待澄清。统计保留失败，不只统计成功请求。最初沙箱网络未通的尝试另存于 `function-formula-photo-20261101`，不计为真实提取成功。

| 遇到的问题 | 处理与证据边界 |
| --- | --- |
| W05、W12 的题干右端被选框截断 | 模型要求确认，未擅自补题。重新框入完整填空区域；其中保留原图手写答案并明确标记 `contains_handwritten_response`，识题结果没有把手写答案作为题设 |
| W01 首轮复核误报公共题面含题号 | 修复未产生有效变化，工作流以 `workflow.oscillation` 停止。使用同一照片重新识别一次后通过；保留原失败，不宣称已解决模型复核误报，也未修改自动重试策略 |
| W07 原图写“任意实数”，同时含 f(1/x) | 原图识别保留 R 并报告冲突，不能生成已审核题目身份。用户修订“任意非零实数”的题源仍绑定原图和批准记录；没有把修订文字冒充原图识别，也不再次要求用户批准 |
| W10 曾被人工误读为一次函数 | 本轮原图识别为二次函数，保留 f(0)=0、差分条件和 f(x)>0 的原目标；结果为 (0,7/3) |

W07 原照片的冲突记录只描述未经修订的图片，不将已经批准的 W07 课程重新列为冲突题。当前没有带修订文字的新照片，照片复核与人工修订课包不能合称为一次逐字照片识别通过。

## 原文对应修复

实际求解通过后，课程检查发现五道题的读题卡未能对应以下合法写法，已在共用 `stage_two/formula_surface.py` 修复：

- W01 的 `f[f(x)]`：只将已声明函数的调用方括号识别为函数括号，不改变区间、下标或其他函数名。
- B07、B07-v 的粗体 R：在实数集合和全称量词位置识别，仍核对两个变量及全称关系。
- W03 的普通 R：须有“定义在／定义域”语境，不把任意参数 R 当作实数集合。
- B06-v 末尾紧接等式的 `(x≠0)`：仅在规范题意明确保留非零范围时分出范围条件，不丢弃任意乘积、不等式或附加条件。

匹配保留原文字符位置，不改写学生看到的题面。五道受影响课程已从原照片的复核结果重新执行并导出，见最终汇总中的 `course_file`；其余数学执行不重复。所有 20 题的读题诊断为空、目标完整、已开放交互可用。

## 必要验证

新增 `tests/search/test_function_formula_photo_matrix.py`，冻结真实模型响应，日常测试禁止模型调用和数据库连接。录制保留原始响应文本、图像哈希及每次提取／复核／修复顺序，仅清理服务商请求标识等元数据。

本次定向命令在 `server/` 下运行，**64 项通过，3.54 秒**：

```sh
.venv/bin/python -m pytest -q \
  tests/search/test_function_formula_photo_matrix.py \
  tests/solver/test_graph_function_formula.py::test_source_binding_distinguishes_radical_and_unknown_function \
  tests/solver/test_graph_function_system.py::test_original_question_identity_domain_binding_and_independent_verification \
  tests/solver/test_graph_function_assignment.py::test_both_universal_variable_names_are_bound_to_source_not_inferred \
  tests/solver/test_graph_function_coefficients.py::test_source_binding_rejects_misread_type_or_unrecorded_initial_condition
```

覆盖原图像素及来源绑定、20 道真实响应回放、原目标与方法准入、四次未通过尝试的拒绝行为，以及错误函数名、嵌套调用、集合、量词、变量、非零条件、附加条件的拒绝。未跑全量单元或数据库集成测试套件。

课程构建使用独立 PostgreSQL 实例，结束后已停止。另对 B05-v3 做一次带归属的拍题 API 实际验收，复用真实照片录制，不新增模型调用：两问完成，六张交互卡、两个已验证路线交接可用；答题前的卡面不提前显示答案；再次启动返回同一快照，不重新执行。[API 验收结果](../internal/review-analysis/function-formula-photo-20261101/api/acceptance.json)。本轮没有新增拍题浏览器或实体手机验收证据。

本地拍题后台 `http://127.0.0.1:8779/` 已重载最新代码，专题页面返回 HTTP 200；`8793` 静态预览继续运行。这只确认服务已启动，不替代新照片或浏览器验收。语法、证据链接及空白检查通过。

## 后续门槛

这批已知原题的照片回归已覆盖五种方法，不能替代未参与开发的新题。仍需按设计补齐独立新照片，尤其 A0 要求的两张新题及其输入方向／变量结构变化，再完成相应端到端验收。失败复核样本已进入回归，不能重新充作留出材料。FR-T2 保持待建设，线上发布另行安排。
