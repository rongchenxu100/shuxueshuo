# 第二步作者提示修复验收

本次修复针对前一轮模型在定义形式化、作用域/ID和覆盖表编写上反复组织，
最终只有 reasoning、没有业务 JSON 的问题。前一轮失败审计保持原样。

## 实现

- 新增 `problem-understanding-authoring/v2` 作者策略。持久化的五个领域/转录/匹配
  契约没有改动；作者输入支持显式 `domain.coverage="from_source_unit_ids"`。
  服务端先从实体、事实、目标、定义的 `source_unit_ids` 反向生成覆盖表，再封存
  精确领域修订。缺失关联不补写，未知引用、目标缺失及图/缺口冲突交原校验器拒绝。
  模型仍负责每条语义关联，代码不猜测题设。
- 提供固定、与题目无关的 Part/实体命名规则，减少模型设计 ID 体系的工作。
  本次没有隐式重命名模型的语义引用；错误 ID 仍按原规则拒绝。
- 从同一权威 Schema 自动提取重复结构为 `$defs`，未删除原语、字段约束或资源限制。
  测试将紧凑 Schema 完整还原，与原作者 Schema 逐项比较，保证约束未放松。
- 观察输入只提供语义视图：保留全部文字/公式/版面、坐标、置信度、来源状态、
  遮挡和未解决问题。未知、混合和手写内容即使不覆盖印刷块也不删除。完整原始
  观察与 ID 别名映射另行保存到产物库；不改变原始观察或其哈希。
- 明确 bbox 为 `[x0,y0,x1,y1]`、来源必须属于对应 Part、定义在根层、coverage 不可
  指向 Scope、缺图与领域未编码内容的区别。点角色 given 不自动等于 fixed。
- 去掉“四个独立图景”的样本数量。加入与本题无关的参数化几何定义和两个作用域
  示例，演示 all/any、私有 witness 与 definition_use。示例经完整领域校验。
- 引导模型直接在最终通道输出紧凑 JSON，避免在 reasoning 中预写整包或重复定义。
  这只是作者指引，不声称能够强制控制模型内部推理长度。

## 输入规模

以下为紧凑 JSON 字符数，不是 tokens；没有通过删图或丢失未知文字缩减输入。

| 部分 | 原请求 | 本次 |
| --- | ---: | ---: |
| 完整观察 / 语义观察视图 | 29,629 | 8,926 |
| 作者 Schema | 32,838 | 21,389 |
| 独立合法示例 | 1,751 | 4,450 |

示例稍长，用于减少实际请求中反复设计定义和作用域的工作。所有问题使用同一示例，
未按 case_id 选择提示或注入金标。

## 离线测试

```sh
cd server
.venv/bin/pytest -q tests/solver/test_understanding_authoring.py \
  tests/solver/test_understanding_v2.py tests/solver/test_problem_domain_recorded.py \
  tests/solver/test_problem_source_review.py tests/solver/test_deepseek_vision.py --tb=short
```

真实调用前：152 passed，6 skipped。最终新增scalar形参转换负例后，
155 passed，6 skipped，见 [完整测试输出](offline-tests.txt)。新增作者策略测试全部执行；6 个 skip 是原测试入口
未启用的真实模型用例，不计为真实验收。Ruff 检查通过。

## 新一轮真实验证

用户确认修复后新建独立实验目录：
`internal/solver-runs/understanding-v2-authoring-fix-20260915/`。

保留 DeepSeek `deepseek-flash`、enabled/low、json_object、非流式、16,384 tokens、
每次网络尝试300秒、SDK retries=0。仍是一次语义调用、最多两次受控网络尝试，
没有额外修复调用、独立视觉复核或供应商回退。原失败目录不覆盖。

结果：**仍未通过真实验收**。本次只发生一次网络尝试，耗时61.95秒。
输入降为13,779 tokens（较原请求25,844减少46.7%）；模型输出了6,897字符的
最终业务内容，但在第二个图景的domain部分截断，`finish_reason=length`。
本次实际13,882 tokens用于推理，2,501 tokens用于最终输出；二者仍共享既定输出预算。
完整JSON解析失败，因此未采用任何子对象，也没有通过题意金标或Solver就绪检查。
未追加调用、提高token上限、拆分请求或改用其他provider。

[调用摘要](live-summary.json)、[冻结记录](frozen.json)、[完整审计](live-audit.zip)
已保存。完整原图、原始观察、观察别名映射及视图审计manifest都在产物库内。
相较前次最终内容为空，重复组织有所减少并开始正式输出；这不等于已解决整包输出。

本次返回还在scalar形参位置使用了ID字符串。作者Schema允许ID或QuantityTerm，
因此补上基于定义形参类型的确定性转换：scalar ID转为scalar节点，polygon ID保留。
这只消除表示差异，不补实体，实际类型和作用域继续由原校验器检查；点ID或跨图
参数仍拒绝。此补充通过离线负例，未触发第二轮真实调用。

下一步需要明确选择保留一次调用并调整输出预算，或拆分转录与领域形式化。
这些都会修改此前的固定验收条件，本次没有擅自执行。
