# K 题数学等价证明与图景提取规则修复

本轮只修改编译／比较代码、Prompt、Schema 的说明及回归门禁，没有新的模型调用，没有修改金标或原始响应。LLM 输出字段不变，仍为数学字符串；所有证明发生在代码侧。

## 四项修改

1. **平分与单位截线比。** `cut_ratio(AC,BD)=1` 与 `bisects(BD,AC)` 在代码证明两条支撑直线有唯一交点、交点不落在四个端点上之后，归一化为同一关系。证明前提来自非退化四边形的对角线关系，或已知平行四边形／正方形下的精确仿射构造。第一参数反向取倒数，第二参数方向不影响结果；非单位比例仍严格检查方向。没有足够前提时不强行转换。
2. **完整定义的冗余分支。** 比较器将逻辑式转为有界析取范式，使用 SymPy 的精确多项式与线性理想约化，双向证明各分支的蕴含。只推导等式，不猜几何条件或放宽不等式；保留共同的非零分母等定义域义务。最多 64 个逻辑分支、16 个符号、32 条等式、4 次线性后果传播，复用总证明预算。没有任意 `eval`，不解析执行 SymPy 输出字符串，无法证明时仍报告差异。
3. **图1四边形构型。** 对 `parallelogram(A,B,C,D)` 建立仿射坐标架：A=(0,0)、B=(1,0)、C=(1,1)、D=(0,1)。两条对角线交于 O=(1/2,1/2)，E 为 OB 中点，所以 E=(3/4,1/4)。精确叉积证明 A→E→C→D 构成严格凸四边形，因而显式 `quadrilateral(A,E,C,D)` 是可证明冗余的关系。只在比较投影中消除，原始响应和编译 IR 保留。这是通用构造证明，没有 K 题名称或答案分支。改变中点、交点、顶点顺序或删除构型前提时，不会无条件忽略四边形声明。
4. **图景层次与缺图。** 原 Schema 已有简短的“同问独立图景再分层”，原 Prompt 也已有缺图规则；本轮将层次规则写成明确操作：同一编号内多个图景保留编号父节点，即使父节点没有独立条件。缺图规则强调逐图核对所有输入，一图存在不能代替另一图，文字完整不免除缺图标记。few-shot 第五例改成同一分问含图甲／图乙、仅提供图甲；分别演示正常提取和在对应子问报告 `missing_figure`。

Prompt 与 Schema：

- [系统 Prompt](../../../internal/llm-prompts/problem-math-notation-system.md)
- [Schema](../../../internal/schemas/problem-math-notation-v1.schema.json)

这些改动不增加 LLM 输出复杂度，没有加入专用 K 倍四边形操作。Prompt 仍要求保留原始逻辑分支、不解题，代码只证明不同抽取表达是否等价。缺图状态仍由模型实际提取结果提供，代码不会针对这道题硬补缺图。

## 验证结果与边界

离线回归命令（从 `server` 运行）：

```sh
uv run pytest -q tests/solver/test_math_notation*.py tests/solver/test_understanding*.py tests/solver/test_solver_test_profiles.py -m 'not live_llm'
```

共 **469 passed，10 deselected**，包括新增 35 项几何证明测试和对应门禁映射。覆盖正例、反向比例、退化／交叉构型、缺少证明前提、分支删除、不等式改变、目标改变、父条件继承／兄弟问隔离，以及证明预算耗尽。请求测试确认新说明和 few-shot 实际进入发送给模型的 system prompt，Schema 输出形状保持不变。[完整测试日志](offline-tests.log)

用原批次 `math-notation-seven-20260916-135634` 的完整响应离线回放：

| 用例 | 原批次真实结果 | 当前原始响应离线回放 |
| --- | --- | --- |
| 和平一模 | 未通过 | 通过 |
| 和平二模 | 通过 | 通过 |
| 河西一模 | 未通过 | 通过 |
| 南开一模 | 通过 | 通过 |
| 西青一模 | 通过 | 通过 |
| K 倍四边形 | 未通过 | 未通过 |
| 函数量词题 | 通过 | 通过 |

原批次真实成绩仍为 **4/7**，当前原始响应离线回放为 **6/7**。这是代码升级后的回放，不是新 Prompt 的模型通过率。六题通过状态没有改变，K 题旧响应仍缺层次且漏报四幅图，因此整体仍失败，仍没有触发缺图阻断。[回放结果](replay-final/summary.json) · [完整模型输出](replay-final/outputs.html)

K 题另做诊断副本，严格区分于原始模型输出：

| 诊断输入 | 结果 |
| --- | --- |
| 原始响应，不作修改 | 未通过 |
| 仅将头两个图景装回空的 `(1)` 父节点 | 数学关系已证明等价，仅剩四处 `/uncertainties` 差异 |
| 在上述诊断副本中再恢复四个缺图标记 | 严格比较通过 |

诊断没有改写任何 definitions、facts 或 goals，也没有添加缺失的四边形事实。它证明此次代码修复已覆盖数学关系差异；不能据此把旧模型响应记为成功。新 Prompt 是否能让 DeepSeek 正确保留层次并报告缺图，仍需未来真实调用检验。

[诊断脚本](diagnose_k.py) · [原始响应哈希、差异与证明记录](k-diagnostics.json)

## 代码位置

- [仿射几何证书](../../../server/shuxueshuo_server/problem_understanding/notation_geometry_proofs.py)
- [有界双向逻辑蕴含](../../../server/shuxueshuo_server/problem_understanding/notation_implication.py)
- [规范化与证明记录](../../../server/shuxueshuo_server/problem_understanding/notation_normalization.py)
- [比较与差异报告](../../../server/shuxueshuo_server/problem_understanding/notation_semantics.py)
- [几何与逻辑门禁](../../../server/tests/solver/test_math_notation_geometry_proofs.py)

这些规则是保守的充分条件，并不承诺任意几何表达都能判等。未知构型、不能在线性约化范围内证明的关系、超出预算的表达会继续保留为未证明差异；候选保持 `candidate_only`，未接入 Solver。
