# 移除目标 at 后的对象树复审

结论：当前实现已将“取得最值时”等条件统一到作用域的 `facts`，没有仅删除限定信息。五题人工样例和五题真实提取候选均能解析，规范化对象与作用域均与旧题意对齐。本次未发现这一改动造成的状态条件遗漏或目标作用域串用。

**新旧完整条件树并非五题全部相同。** 对真实候选，河西通过自动审计等价检查，其余四题仍保留差异：两题新结构补全了旧结构未显式记录的最优状态，三题涉及尚未自动证明的几何或代数等价关系。下文给出原图核对和逐项解释。新输入接入生产运行时的验证仍未完成。

## 代码检查

- 六类目标的 Schema 均不允许 `at`；输入旧字段会在编译前被拒绝，没有兼容转换或静默忽略。
- 编译器只从目标读取所求及 `variables`、`in_terms_of`；状态关系在普通 `facts` 中解析、绑定并继承。
- 同一节点的目标共享可见条件；仅部分目标有状态条件时，放入独立子节点。测试覆盖状态被删除、提到父节点、移到兄弟节点，以及用“最小值等于某数”替换“当前取到最小值”的错误。
- 抽取、review、repair 的当前协议与示例均使用 facts 状态表达。南开Ⅱ②的两个目标共享一次状态条件，和平二模Ⅱ的坐标目标也保留状态条件。

例如南开Ⅱ②现在表达为：

```json
{
  "facts": [
    "min(EG+FG) = 5*sqrt(10)/2",
    "EG+FG = min(EG+FG)"
  ],
  "goals": [
    {"kind": "find_equation", "object": "Γ"},
    {"kind": "find_coordinates", "object": "G"}
  ]
}
```

第一条是最小值条件，第二条是当前配置达到最小值的状态；二者不能互换。`goals` 只说明在这些条件下求什么。

## 数据与核验

分别运行了[五题人工样例审计](authored/README.md)和[五题真实候选审计](recorded/README.md)。真实候选直接读取已完成批次 `math-notation-state-facts-seven-20260917-094219` 的 `workflow/candidate.json`，没有重跑模型、修改候选或改写上一版报告。

本次还用当前代码重验真实候选与其批次冻结金标、当前人工金标的语义比较：**两组均 5/5 通过现有比较器检查**。五份 review 均为 recorded `confirmed`，其 revision 与本次候选一致；候选字节、工作流结果、图片哈希均核对通过。原始 review 不是本次新增调用，金标比较也不等于旧运行时树等价。[逐项核验数据](recorded-source-checks.json)保留这些不同证据。

本次直接查看了五张冻结题图，核对表中差异对应的原句、目标和范围。只对有旧领域输入及旧 Solver fixture 的五题作新旧对照；未将该结果推广为原七题批次全部通过。

## 真实候选的逐题审阅

| 题目 | 规范化对象数（旧/新） | 作用域 | 自动新旧审计 | 差异判定 |
|---|---:|---|---|---|
| [南开一模](recorded/tj-2026-nankai-yimo-25/README.md) | 11 / 11 | 对齐 | `needs_review` | 仅新结构明确 `EG+FG=min(EG+FG)`。冻结题图Ⅱ②写明“取得最小值”及“此时”，且同时修饰曲线方程和 G 坐标。保留这条状态符合原题，旧结构未显式携带。 |
| [和平二模](recorded/tj-2026-heping-ermo-25/README.md) | 12 / 12 | 对齐 | `needs_review` | 新结构保留 `HF+FM+MG=min(HF+FM+MG)`，符合题图“取得最小值…时，求 E 坐标”。另有 H 的“对角线交点”与旧结构“两条对角线中点”的表示差异。 |
| [和平一模](recorded/tj-2026-heping-yimo-25/README.md) | 11 / 11 | 对齐 | `needs_review` | 旧结构显式 `A≠B`，新结构以完整横轴交点集合表达。由现有抛物线条件可以推出两交点不同；比较器尚未自动完成该证明。 |
| [河西一模](recorded/tj-2026-hexi-yimo-25/README.md) | 10 / 10 | 对齐 | `equivalent` | 本轮旧领域树与真实候选在当前审计范围内一致。真实输出额外写出 `y_M` 坐标符号，已有坐标绑定规范化消除表示差异。 |
| [西青一模](recorded/tj-2026-xiqing-yimo-25/README.md) | 8 / 8 | 对齐 | `needs_review` | 剩余差异也是旧结构显式 `A≠B`。旧命名顶点与新 `vertex(Γ)`、显式 `y_D` 坐标的表示差异已有规范化证据，不再构成对象差异。 |

这里的计数是规范化后的命名数学对象，不是初始运行时匿名对象、条件或状态槽总数。逐题报告保留原始计数、原始树、规范化树以及两份旧运行时快照。

原图依据：[南开](../../../internal/solver-runs/math-notation-state-facts-seven-20260917-094219/tj-2026-nankai-yimo-25/input-fixture/source.png)、[和平二模](../../../internal/solver-runs/math-notation-state-facts-seven-20260917-094219/tj-2026-heping-ermo-25/input-fixture/source.png)、[和平一模](../../../internal/solver-runs/math-notation-state-facts-seven-20260917-094219/tj-2026-heping-yimo-25/input-fixture/source.png)、[河西](../../../internal/solver-runs/math-notation-state-facts-seven-20260917-094219/tj-2026-hexi-yimo-25/input-fixture/source.png)、[西青](../../../internal/solver-runs/math-notation-state-facts-seven-20260917-094219/tj-2026-xiqing-yimo-25/input-fixture/source.png)。

几何与代数差异可以作如下人工解释，尚未将这些解释加入自动比较器：

- 和平二模：正方形的两条对角线互相平分，所以交点同时是两条对角线的中点。此结论依赖正方形条件，不能无条件用于一般四边形。
- 和平一模：`A=(-1,0)` 在曲线上给出 `b=a−3`，于是 `ax²+bx−3=(x+1)(ax−3)`。另一个根为 `3/a>0`，与 `−1` 不同。
- 西青：同理由 A 得 `c=b+1`，于是 `−x²+bx+c=−(x+1)(x−b−1)`。另一个根为 `b+1>1`，与 `−1` 不同。

## 人工样例与真实输出的区别

人工金标仍显式填写部分最值变量，例如南开的 `E,G`、河西的 `n`；本轮真实提取省略了这些可选提示，符合当前契约。旧结构同样没有对应字段，因此真实候选相对旧结构不再出现这组限定项差异。不能将这个变化解释为解析器自动删除了变量：原始输入与审计树都保留供检查。

人工金标的五题自动审计仍均为 `needs_review`，其中四题有变量显式性差异。后续 Plan 输入不能把“未填写 variables”解释为“没有优化变量”；仍须使用目标表达式和可见题设约束确定方法绑定。

## 本次补强的审计检查

新契约下发现一个审计盲点：现有 `parameter_state_extremum_witness` 可以证明某些状态条件不改变参数答案，并在**答案比较投影**中省略该状态。这种证明不等于原始条件树或点配置相同。

审计新增内部 `state_conditions` 视图，在答案投影之前记录取到极值的关系、所在作用域及逻辑上下文。即使参数答案等价，源条件不同时仍返回 `needs_review`。这只是审计字段，没有新增 LLM 输出字段，也没有改变生产表达式解析器或等价证明政策。

新增反例覆盖参数答案等价但状态不同、状态遗漏/越界/兄弟串用、最值与状态混淆、析取分支，以及等号反向但数学相同的正例。报告清单还纳入当前 Schema、提示词与表达目录的哈希，避免只记录 Python 版本而遗漏本次契约变更。

验证结果：**120 passed in 2.65s**；本次涉及的审计文件通过 server 项目配置下的 Ruff。两个审计运行及随后金标复验的源码/契约摘要稳定；本次新增真实 LLM 调用为 **0**。

## 复现与后续边界

从 `server` 目录运行，输出目录需全新：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python tools/compare_problem_math_trees.py --output ../docs/validation/math-object-tree-state-facts-new/authored
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python tools/compare_problem_math_trees.py --workflow-batch ../internal/solver-runs/math-notation-state-facts-seven-20260917-094219 --output ../docs/validation/math-object-tree-state-facts-new/recorded
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q tests/solver/test_math_tree_audit.py tests/solver/test_math_notation_state_scope.py tests/solver/test_math_notation_state_proofs.py
```

报告中的 `equivalent` 只表示本次语义树审计通过。新 JSON 到生产 `StateSlot/StateVersion` 及 Method 参数绑定的适配仍未实现，不能据此声称完整 Solver 迁移通过。此前需要追加真实提取数据的待办已在这五题完成；下一项生产兼容性验收应聚焦运行时绑定，而不应再恢复目标 `at` 字段。
