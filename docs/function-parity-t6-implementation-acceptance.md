# FP-T6 实现与集成记录

日期：2026-11-12。复用基线：`10b87e95`。对应[设计方案](function-shifted-odd-problem-type-design.md)。本轮代码在工作区，未提交、未推送；未统一重建正式课程。

## 1. 本轮交付

增加 `type-shifted-odd-application`，复用 M5 对称关系法，独立结构版本为 `function-symmetry/shifted-odd-v1`。从原题来源识别辅助函数及偏移关系，或验证显式公式的对称和，再回答原目标。Stage One、Stage Two、Stage Three、冻结验证和课程导出均使用同一来源与版本。

没有修改 prompt。记法编译只增加两项通用支持：函数体内常规函数名的声明、最值符号与目标的绑定。未将题号、答案或 T6 解题步骤加入模型提示。

| 模块 | 实际职责 |
| --- | --- |
| `graph_lesson/shifted_odd_math.py` | 来源归属、辅助函数关系、局部范围、参数分支、带权目标、重复项、独立验证 |
| `graph_lesson/shifted_odd_identity.py` | 保留原分母的恒等验证、精确符号输入共同根证书及其验证 |
| `stage_two/shifted_odd_surface.py` | 原文中函数身份、奇性、公式、域和原目标的来源绑定 |
| `stage_three/shifted_odd_runtime.py` | M5 的 T6 域检查、关系改写、求值、确认与完成 |
| `stage_three/shifted_odd_presentation.py` | 源 AST 原式、奇函数身份、对称和值及中点高度、配对数轴和原目标选项 |

T6 优先处理明确属于辅助函数偏移来源的有限和，避免被 T5 当作单函数题接管。普通显式代入、T3 普通奇偶求值及 T5 一般对称关系仍走原路线。未准入的条件保留并报告缺口，不删除后强行完成。

## 2. 五道开发题

题源、规范题面及散列继续沿用[原图归档](../internal/senior-high/source-images/function-parity-t6-planning-20261112/manifest.json)。五份作者题源及待发布映射位于[隔离清单](../internal/senior-high/authored-courses/function-parity-t6-staged-20261112/pending-topic.json)。题面不含“例”“变式”等栏目标签。

| 题目 | 执行金标 | 重点证据 |
| --- | --- | --- |
| A16 | $f(-1)=-13$ | 奇函数是 $g=f+2$，原函数对称和为 $-4$ |
| B01 | $f(2)=-1$ | 原文未给完整域，保留符号域，只使用已知合法输入的反射闭合 |
| B02 | $f(2024)+f(-2024)=-4$ | 对所有实系数成立；包括 $b=0$ 时仍保留原式 $x\ne0$ |
| B03 | $f(-a)=-10$ | 所有已知等式具有同一合法实输入的精确根证书；不把 $a$ 当系数 |
| B04 | $M+m=2$ | 任意实系数下恒等式成立，原式在同一对称闭区间连续且无极点，最值实际取得 |

五题仅生成隔离课包，未向 `topics/function-parity.json` 添加可作答条目。公开路由预留 A16 的 q16、B01–B04 的 q21–q24，正式发布须按统一重建流程执行。

## 3. 泛化范围和拒绝边界

- 辅助函数支持正、负、零偏移及固定缩放；先分类零系数，再进行除法。非零常函数不可能全域为奇函数，零函数关系则不额外约束原函数。
- 局部关系只在所声明范围应用；不能覆盖一对相反输入时不推出全域对称和。
- 输入合法性在约分、抵消、合并零权项之前检查。固定域包括区间、有限集及孔洞；区间要求端点严格递增。
- 带权求和保留重数，允许完整对子消去未知值；不平衡部分通过线性证书判断是否唯一。条件不足时保留两个满足原事实、目标值不同的见证。
- 单个仿射参数支持唯一解、参数集合以及两个函数系数各自的零／非零分支，包括 $f=p g+c$ 中 $p=0$ 的情况；原目标若是函数值，逐分支还原原目标并检查结论一致性。函数形参不能冒充标量系数。
- 显式有理式限分子至多五次、分母至多四次且无系数参数；至多两个一次实系数参数，原分母义务不丢失。固定非有理式仍受已有 M1 能力限制。
- 显式符号输入限一个实符号及仿射输入，原已知值需有共同合法实根。恒成立的等式从所有合法输入原像的交集中选择精确见证，支持远离原点的区间、开区间和有限点集；非零共同多项式按合法范围收紧隔离区间。无共同实根与暂时不能证明合法根分别返回矛盾或能力缺口。
- 最值组合限同一非空对称闭有界区间上的连续无极点有理式，明确绑定最大值与最小值记号，不按端点位置猜最值。

以下边界尚未开放：一般多参数条件求解、含参定义域或分母、无限和、函数值非线性乘积、局部关系的参数分类、任意极值存在性证明。显式公式中的数值条件若进一步约束自由系数，会报告 `coefficient_conditions_unsupported`；目标仍依赖自由系数时报告 `target_parameter_not_eliminated`，不会误报矛盾或输出一个猜测值。

## 4. 验证

测试使用独立实例 `fm-review-20261109`，数据目录 `/private/tmp/shuxueshuo-fm-review-20261109`。未连接日常业务数据库。

必要回归包括：

- T6 五道原题的数学结果、冻结序列化、来源识别、完整执行、导出及恢复。
- 零系数、局部范围、原域孔洞、带权与重复项、参数分支、精确根式数值、显式已知值相容性。
- 禁用生产求解入口后独立验证仍通过；篡改目标值、共同根范围或来源等式时拒绝。
- 五份隔离课包逐步提交正确／错误选项，校验回退、录制回放、KaTeX 公式与数轴 SVG。
- 受影响的 T1、T3、T5、记法及显式求值回归；新增图谱节点及 M5 关联校验。
- 分别修改新增数学模块和来源绑定模块的真实字节，核查三个依赖摘要及旧工作流／checkpoint 的失效；恢复字节后摘要恢复。

首轮交付回归（本次 review 修复前）：**480 项定向 Python 测试通过**，其中主回归 479 项（142.50 秒），真实依赖字节／恢复回归 1 项（8.13 秒）。这 480 项包含 65 项 T6 测试及 415 项受影响的旧能力测试。

图谱源码校验通过：170 个节点、28 个题型，T6 正确关联 M5。新增 Python 模块的 Ruff 检查及 `git diff --check` 通过。依赖恢复测试结束后，被临时修改的文件已恢复原字节。

在 `server/` 中复现主回归（环境变量使用上述独立实例）：

```sh
uv run pytest -q \
  tests/solver/test_graph_shifted_odd.py \
  tests/solver/test_graph_symmetry_value.py \
  tests/solver/test_graph_symmetry_relation.py \
  tests/solver/test_graph_stage_three_symmetry_relation.py \
  tests/solver/test_graph_function_parity.py \
  tests/solver/test_graph_function_parity_recognition.py \
  tests/solver/test_math_notation.py \
  tests/solver/test_graph_function_evaluation_math.py \
  tests/solver/test_graph_shifted_odd_staging.py
```

`test_graph_shifted_odd_revisions.py` 单独串行运行，避免它对真实依赖文件的短暂修改影响其他回归。运行这些集成测试期间也不要编辑执行依赖，否则全局指纹会正确拒绝跨版本继续执行。

### 4.1 Review 修复与泛化回归（2026-11-12）

本轮修复四项 review 问题：

1. 来源绑定同时核对公式及奇偶性文字声明。额外的奇／偶条件、否定声明、主体错配和多个函数共用的性质，不能因模型漏提取而被普通函数介绍放行。支持“奇函数 $g(x)$”这一常见前置写法。
2. 在所有函数值系数中排除函数形参，$g(x)=xf(x)+2$ 返回明确准入缺口，不再把 $x$ 当参数给出错误的“信息不足”。
3. 对 $A(p)f+B(p)g+C(p)=0$ 分别划分 $A=0$、$B=0$ 的情况，保留各分支的已知值检查；覆盖 $f=p g+c$、零系数、负系数、两个系数同时为零，以及原目标跨分支不唯一的情况。
4. 原值等式恒成立时，复用精确仿射原像能力取得所有输入限制的交集，再选合法见证；支持远离原点的区间、开区间、有限集、二次代数孤立点。非零共同多项式可在较窄合法范围内继续隔离，验证器独立核查证书。

新增文件 `server/tests/solver/test_graph_shifted_odd_generalization.py` 含 **39 项**测试。本轮定向回归 **316 项通过**：T6 数学、来源识别、课程导出／恢复、隔离课包及相邻 T3／T5 回归 315 项（156.71 秒）；单独串行的真实依赖字节／恢复回归 1 项（8.44 秒）。本批包含 104 项 T6 测试及 212 项相邻能力测试，不与首轮 480 项重复累加。

新增使用的 `stage_three/abstract_function_domain.py` 已登记提取绑定与执行清单摘要，runner 原有目录收集也覆盖该文件；真实字节回归已验证三个入口均失效并可恢复。独立验证测试禁用生产求解与共同根构造后仍通过，篡改参数分支或合法输入见证会被拒绝。Ruff 和 `git diff --check` 通过。

主回归可用上一节独立实例执行：

```sh
uv run pytest -q \
  tests/solver/test_graph_shifted_odd.py \
  tests/solver/test_graph_shifted_odd_generalization.py \
  tests/solver/test_graph_shifted_odd_staging.py \
  tests/solver/test_graph_symmetry_value.py \
  tests/solver/test_graph_symmetry_relation.py \
  tests/solver/test_graph_stage_three_symmetry_relation.py
```

再单独运行 `test_graph_shifted_odd_revisions.py`。本轮仍未修改 prompt，未统一重建正式课程，未提交或推送。

## 5. 实现轮边界与后续照片验收

上述实现轮使用归档题图的人工核对转录，没有调用真实 OCR、提取／复核模型。后续照片轮已重新上传原图，完成 A16、B01–B04 的真实 OCR、提取／复核与课程集成，修复、全部调用及本轮 293 项回归另见[照片验收记录](function-parity-t6-photo-acceptance.md)，不与本页历史测试重复累加。没有独立来源的新照片留出测试；自动渲染校验不等于浏览器正式页面人工验收。

两轮均未重建公开课程。全局依赖指纹仍然生效，发布前需要统一刷新课程证据、全量构建并运行 `--check`，再做正式页面及发布环境验收。
