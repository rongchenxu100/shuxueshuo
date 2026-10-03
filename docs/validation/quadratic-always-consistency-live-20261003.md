# 恒成立题库同步骤统一后的真实 LLM 验证（Q01、Q06、Q08、Q09，2026-10-03）

## 最终结果与范围

第 4 批 **7 passed, 29 deselected in 114.08s**：Q01 两条路线、Q06 两条路线、Q08、Q09 两段，共 7 项真实对话测试、98 轮。离线全量 `tests/tutor_demo` **276 passed, 53 skipped**。最终 98 轮回复逐条阅读，核对了计算、证据、动作和步骤推进。

使用项目配置的 DeepSeekTutor，经 Session.handle 重放学生文字和 UI 操作，非 mock。不包含浏览器 HTTP 对话传输、生产限流、超时重试或部署验收。

## 为什么要重新验证

“同一步骤跨题统一”修改了这四题的教师 JSON：

- Q01：`e_condition` 选项去掉“：说明”后缀。
- Q06：`e_extremum` 改为“区间与最低点的位置”（左侧／右侧／两侧都有），答案由 `inside` 改为 `around`，判定标准随之改写。
- Q08：`v_extremum` 改为与 Q09 共用的“看斜率判断最值”，选项值 `left`／`right`／`ends`，答案由 `f3` 改为 `right`；新增“说较大的一个不授 maximum_value”。
- Q09：`v_basis` 次数说明、结论与 `v_extremum` 选项顺序。

## 新增对话轮次

- Q08：斜率恒正之后说“最大值取 f(1)、f(3) 中较大的一个”（同时在界面选 `ends`），应不授 maximum_value 并追问哪一端。
- Q06：说“(-∞,0) 在最低点左侧，h(x) 一直下降”（界面选 `left`），应不授证据；再说“-√2 在 (-∞,0) 内，区间在最低点两侧都有，先降后升”，授 lowest_inside。

## 修复内容

- Q01 `e_basis`：教师曾把行标题“参数能否单独放到一边”当作学生所选项，说“你选的这一项是对的”（实际选的是错误的“移项后可以分离”）。判定标准补充：选“移项后可以分离”不对；点评时用选项原文。
- Q06 `e_basis`：学生只说“移项就可以分离 a”时，教师在回复中指出缺少“除以 x、符号确定”却仍授证据。判定标准开头加优先拒绝规则与这个例子。
- Q09 `v_basis`：学生只谈次数时被一并授了 main_variable；补充对称规则（只谈次数只授 linear_in_main_variable）。回复中“至多一次”曾误写为“至少”，补充措辞约束。
- 均为题目教师 JSON 的判定标准，未改通用 system prompt。

## 批次记录

| 批次 | 自动结果 | 人工复核 |
| --- | --- | --- |
| 1 | 7 passed，115.99s | 新增的 Q08“较大的一个”、Q06“左侧／两侧都有”判定正确；发现 Q01 把行标题当选项、Q09“至少一次”笔误，修复。 |
| 2 | 1 failed，6 passed | Q06 第 1 轮只说“移项就可以分离”被授证据（该步本次未改，模型波动）；加优先拒绝规则。 |
| 3 | 1 failed，6 passed | Q06 通过；Q09 只谈次数被一并授 main_variable；补对称规则。 |
| 4 | 7 passed，114.08s | 状态、证据、计算正确；Q01 用选项原文点评；无内部选项值外露。推进时学生看到的是完成语，模型原文中“请改选后提交”这类过时句不会显示。 |

[第 4 批 98 条完整真实回复](quadratic-always-consistency-live-20261003.jsonl)。固定样本通过不代表任意问法均可靠；第 2、3 批的失败说明证据判定仍有随机波动，靠题目判定标准中的优先规则收紧。

## 复测

```sh
cd server
RUN_TUTOR_LIVE=1 .venv/bin/python -m pytest tests/tutor_demo/test_quadratic_always_q01.py tests/tutor_demo/test_quadratic_always_q06.py tests/tutor_demo/test_quadratic_always_q08.py tests/tutor_demo/test_quadratic_always_q09.py -q -s -m live_llm
```
