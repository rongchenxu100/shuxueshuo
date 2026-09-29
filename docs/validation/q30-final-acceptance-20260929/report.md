# 5C 最终验收进展（2026-09-29）

本轮使用既有真实 Planner 记录离线执行，不新增 Planner 请求；真实 Lesson 调用一次。最终三行静态页面已获用户确认“页面没有问题了”，本轮 5C 验收关闭。按用户要求未操作浏览器，没有新增最终版本 390px 实测记录。未开放生产 Family、未部署。

## 完整失败计划的修复

来源：`q30-acceptance-20260929-02/planner-03/attempt-1.canonical-plan.json`。完整内容冻结在 `server/tests/solver/fixtures/basic-inequality-stage5c/original-expression-plan.json`，没有改写模型的数学推导。

- M01 的引用修复已经通过；后续 M11 的「原式」解析及教学投影此前仍不支持。本轮在最小值 M11 中将其绑定到 `target.target_math`。它始终指原始目标，不是 `previous_bound`。展开后的公式继续验证，原始文字和来源位置保留。
- 第二次 M11 随后暴露归约预算耗尽：已有 `F≥R+U`、`U≥V` 时，没有直接利用共同余项，而是在完整 F 中重新找局部 AM-GM 配对。扩展现有 `known_transitivity` 策略，先以精确代数确认两关系的差相同，再用现有 `weaken`、定义域 `guard` 和 `transitive` 规则构造证书。未增加预算或 checker 规则；SearchPolicy 更新为 v4。
- 共同余项可以为负，不要求额外正性；不会把 `F≥R+U` 当成等式、不会丢掉 R，也不会把两个非严格关系升级为严格关系。归一化方向同时用于策略适用性判断。
- 完整原计划在首轮通过，答案为 4；保存响应重放也通过。实际路线是 M01 → M11 → M11 → M12 → M13，所有消费边均在测试中检查。该合法替代路线还成功生成 7 步确定性页面。

## Lesson 与页面

采用上一批第一组成功 Planner 记录（M01 → M11 → M12 → M11 → M13），生成真实 Lesson：

| 指标 | 结果 |
| --- | --- |
| 语义 / 传输调用 | 1 / 1 |
| 修复 / 回退 | 均无 |
| LLM 耗时 | 6.115 秒 |
| 含离线 solver、教学与 HTML 编译总耗时 | 13.328 秒 |
| prompt / completion / total tokens | 9,834 / 1,723 / 11,557 |
| 教学步骤 | 7 |
| 视觉缺口 | 0 |

7 步对应：观察结构、整理目标、取倒数转换局部求界方向、第一次 AM-GM、配方平方非负、第二次 AM-GM、联立验证取等。七步沿用用户后来要求的拆分，替代最初六步口径。

请求、原始响应、接受内容和统计保存在本目录。最终代码使用原始响应重新编译，直接接受、无修复无回退；不额外调用 LLM。

- [最终真实 Lesson 页面](http://127.0.0.1:8767/internal/review-analysis/basic-inequality-stage5c/q30-final-acceptance-20260929/lesson-final-02/lesson.html)
- [原失败计划修复后的替代路线页面](http://127.0.0.1:8767/internal/review-analysis/basic-inequality-stage5c/q30-final-acceptance-20260929/lesson-original-reference/lesson.html)

## 验证记录

- 完整离线 profile 的并行部分：4853 passed、1 failed（488.60 秒）。进程在反向匹配修复前启动，失败是新增的 `r+v<=x` 用例；修复后的最终 331 项专项包含此用例且全部通过。保留初次失败，不宣称全量首次全绿。串行部分无入选用例（4878 deselected，包含 24 项 live 排除项）。
- 新增回归 9 项：一般共同余项、反向书写、严格性、错误余项/界拒绝、完整冻结计划和响应重放。
- 最终搜索内核、阶段 D/F3、新增验收和测试分组回归：331 passed（105.01 秒）。
- 页面组件 Node 测试：63 passed。
- 冻结样本 20/20；ProblemIR `--check` 10/10；notation 相关 25 项通过。
- 新增测试 Ruff、`git diff --check` 通过。

本地全量运行材料：`internal/review-analysis/basic-inequality-stage5c/q30-final-acceptance-20260929/`。本目录的 `implementation-sha256.json` 记录关键代码与冻结计划哈希。

## 保留的失败记录

初次完整计划回放先因 M11 指代失败；接入数学解析后，教学证据解析仍失败；教学接入后，第二次 M11 暴露预算问题。通用界传递初版遗漏中间关系的 guard，专项测试拒绝；补齐后，反向书写适用性测试暴露旧方向判断，随后修复。没有放宽 checker 或调高额度。

第一次 Lesson 离线复编译错误地把投影后的 `scope-content.json` 当作原始模型响应，触发回退；保留该目录。改用真实 `lesson-response.txt` 后直接通过，最终页面为 `lesson-final-02`。这次失败属于验收脚本输入选择错误，不是真实 Lesson 模型失败。

## 页面评审后的简化

M01 新生成图使用 `presentation: compact`：完整表达式按有效变化静态排列，局部节点加框，不再嵌套观察卡、条件标签、重复推导和播放器。仅在教学投影中移除前后 LaTeX 完全相同的显示行，执行证据不变。原有未指定 compact 的历史展示继续可渲染。

M12 从已验证输入的加法项中识别与证书平方项、余项分别恒等的已有平方；不对展开输入因式分解来强行判为“已经配方”。已有平方时展示两行整体下界，调整标题和推导为“利用平方非负”；展开输入仍展示配方。变量改名、系数变化、平方等价写法及余项不匹配均有测试。不按题号、变量名或固定答案分支。

Python 教学相关回归 144 项、Node 组件测试 70 项通过。初次编译发现共享视觉校验器未登记 compact 模式，已补充对应组件契约及验证测试。离线重编译通过，没有调用 DeepSeek，也未打开浏览器。

[简化后的页面](http://127.0.0.1:8767/internal/review-analysis/basic-inequality-stage5c/q30-compact-20260929-02/lesson.html)。这次页面使用成功 Planner 记录重建后的确定性教学投影，不将此前真实 Lesson 的一次成功统计冒充为新页面的真实调用。


最终展示修订：三行完整表达式、两个向下箭头，连续变化项合成一个框，其余项弱化，无内部翻页控件。编译器为组件资源增加版本，避免旧播放器缓存。Node 组件/文本页 71 项通过，生成页面渲染结构核验为 3 行、3 个整体框、2 个箭头；未操作浏览器。用户已确认页面通过。
