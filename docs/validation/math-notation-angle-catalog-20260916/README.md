# 角度简写兼容与数学表达目录示例

2026-09-16 完成代码修复与离线验证。本轮没有模型调用，原始真实批次成绩、响应、金标和验收政策均不改写。

## 已实现

- 支持 `angle(BDC)` → `angle(B,D,C)`，顶点仍为中间点 D。仅当三个单字母点已在当前作用域或祖先作用域可见、类型为点且不存在同名 `BDC` 对象或量词遮蔽时接受。不能从兄弟小问借点，不自动创建 BDC 或补齐不存在的端点。
- 支持 facts、definitions、目标表达式及 at 中的上述写法。保留原始数学字符串，不增加 LLM 输出字段，也不改变默认推荐的 `∠BDC`／`angle(B,D,C)`。
- 在[数学表达枚举 JSON](../../../internal/llm-prompts/problem-math-notation-expressions.json)的 `cut_ratio.few_shots` 增加三个独立示例，解释平分操作与取比操作的参数职责、两条线交换职责、第一参数端点反向及已有交点名。示例作为原有 `math_expression_catalog` 的一部分完整进入模型请求；没有复制到 Prompt 模板。
- [MN-001：构型声明遗漏](../../math-notation-known-issues.md)登记为已知问题。继续保留失败，不擅自补写或删除构型约束。

示例中的关键对应关系为：

```text
直线 UV 平分 PQ，求 UV 被交点截得两段的比：
bisects(UV,PQ)
cut_ratio(UV,PQ)=r ∨ cut_ratio(UV,PQ)=1/r
```

若把第二式写成 `cut_ratio(PQ,UV)`，取比对象就变成 PQ。代码不会自动交换参数来改写题意。新 few-shot 对真实模型表现的影响尚未实测。

## 验证

新增 20 项测试，覆盖角度等价形式、顶点不能改变、父问继承、兄弟隔离、对象歧义、类型冲突、量词遮蔽、原始响应保留、目录示例实际注入请求和截线比错误方向。DeepSeek K 题原始响应及金标、政策已按字节保存为带 SHA-256 的回归样本；解析通过但语义仍失败的预期已固定。测试已接入 affected 门禁。

相关离线回归：**358 passed，7 deselected**，Ruff 通过。

```sh
cd server
uv run pytest -q tests/solver/test_math_notation*.py tests/solver/test_solver_test_profiles.py tests/solver/test_deepseek_vision_empty_retry.py -m 'not live_llm'
```

| 保存响应的提供商 | 原始真实成绩 | 本轮原始响应离线回放 | K 题当前状态 |
| --- | --- | --- | --- |
| DeepSeek | 6/7 | 6/7 | 解析成功；图1平分／取比参数配错，图2四边形声明缺项 |
| Doubao | 4/7 | 6/7 | 解析成功；图1的 k≥1 逻辑范围差异，图2及（2）（3）四边形声明缺项 |

Doubao 的提升来自此前交点定义简写兼容修复，本轮未再增加通过题数。两家 K 题均正确报告图1～4缺失并保持后续阻断；缺图识别成功与其他语义验收失败分别记录。

Doubao 的 `k≥1` 问题仍须区分：既有政策接受指定小问独立条件的遗漏，但目前只处理独立字符串，不涵盖嵌入逻辑分支的局部约束，故本轮继续保留该差异，不扩展政策。

- [DeepSeek 离线回放](deepseek-replay/outputs.html)
- [Doubao 离线回放](doubao-replay/outputs.html)
- [编译与绑定代码](../../../server/shuxueshuo_server/problem_understanding/notation_compile.py)
- [新增回归测试](../../../server/tests/solver/test_math_notation_angle_catalog.py)
