# FP-T5 实现与集成验证记录

日期：2026-11-12。基线：`976a7f82`。本轮为工作区实现，未提交、未 push、未重建公开课程。

## 1. 当前交付

设计依据为 [FP-T5 设计与实现方案](function-symmetry-problem-type-design.md)。注册 `type-function-symmetry`，共用 M5「对称关系法」；扩展 S1 一般反射域检查及 S2，新增 S4「函数平移关系的迭代」。保留三个知识节点，补入固定点与迭代知识条目。

| 层 | 落点与结果 |
| --- | --- |
| 来源 | 编译 `graph_symmetry(f,axis,a)`／`graph_symmetry(f,center,a,b)`；绑定原文函数、坐标、完整域和目标。量词等式保留局部范围；否定、待判断、其他函数／小问不得充当已知事实 |
| 准入 | `symmetry_relation_math.py` 的 `describe`／`owned` 在旧 T3 分支前处理 T5 来源，不能丢弃不支持条件后回退旧求值 |
| 数学 | `function_symmetry_iteration.py` 处理全域两反射的轨道、带常数的正逆向迭代及有限局部路径；`symmetry_linear.py` 共用精确线性核 |
| 验证 | 重建原关系、作用域、完整索引和目标矩阵，核验相容见证与行空间系数；不唯一目标须有两个不同取值的见证。禁用生产求解器后验证仍通过 |
| 课程 | 独立 T5 runtime／presentation 接入 M5；原题阅读、选法、配对数轴、两次反射输入链、求和分组与余项、答案、评分及回放均可生成 |
| 版本 | Stage One `frozen_files`、Stage Three `fingerprint`、执行合同 `revisions` 登记数学及来源依赖；实际变更字节使三个身份更新，旧工作流／checkpoint／清单被拒绝复用 |

全域两轴、两中心值漂移、轴与中心、同中心退化均有机制覆盖。局部关系同时检查正向源范围、逆向像范围及反向常数；未使用的范围也检查相容性。保留求和重复项、负索引、仿射步长和不完整组。任何原始函数调用，包括被消去或乘以零的项，都先检查输入是否合法。

### 本轮 review 修复与泛化

| 问题／范围 | 修复与验证 |
| --- | --- |
| 量词原式的定义条件丢失 | 化简前检查原分母、根号条件；约分、相消、零乘、函数实参中的限制均保留。量词范围本来已排除奇点时可执行，否则拒绝识别及课程生成；独立验证同样重放这些检查 |
| 否定与疑问被误认作已知 | 同时核验量词及所属陈述；覆盖“并非对任意”“不是对所有”、引号后否定、逗号后“不成立／对吗？”，并检查定义域及奇偶性陈述的性质 |
| 重复量词和并列图像措辞 | 等式绑定最近的所属量词，再核对范围和变量，不能借用上一条的匹配范围。支持共用量词、逐条量词、公式 `∀`、并列两轴／两中心、名词式“对称轴／中心为” |
| 一般有理仿射反射 | 支持 $f(qt+a)=\pm f(-qt+b)+c$，$q$ 为非零有理数；准确计算像范围，保留开闭和孔洞。零斜率、不等幅斜率及非仿射输入受控拒绝 |
| 求和与原式展示 | 被求和式的加减项统一加括号，覆盖阅读、选项、分组推导及多个求和块；同时修正负数乘法显示为减法、量词使用内部变量名的问题 |
| 旧证据恢复 | 来源校验文件也登记进执行合同，字节变更测试覆盖它与三个数学模块，旧工作流／checkpoint／执行清单均不能绕过新规则 |

这些修复没有增加 prompt 或记法目录内容。数学、来源校验和显示逻辑全部在代码中处理。

## 2. 原题与内部 staging

目录：[function-parity-t5-staged-20261112](../internal/senior-high/authored-courses/function-parity-t5-staged-20261112/pending-topic.json)。来源沿用两张原图的[已有清单](../internal/senior-high/source-images/function-parity-planning-20261110/manifest.json)，本轮录入按印刷题意人工核对；不把手写答案作为输入，也不将这些开发题称为独立留出。

| 题目 | 原目标 | 执行结果 |
| --- | --- | --- |
| A10① | $f(1)+f(2)+f(3)+f(4)$ | $0$ |
| A10② | $\sum_{k=1}^{54}f(k)$ | $1$；13 组四项加 $f(53)+f(54)$ |
| A14 | $f(1)+f(2)+f(3)+f(4)+f(5)$ | $0$；仅推出整数点为零，不能推出函数恒为零 |

A10 的两个目标保留各自的 `target_ref`，课包包含两问且分别评分。测试使用临时目录中的执行证据，在内存中编译课包，未改公开专题目录、日常学习库或正式课包。展示不为抽象函数伪造精确曲线，周期称“一个周期”，不声称最小正周期。

后续已完成这两题的[原照片真实 OCR、模型与课程 API 集成验收](function-parity-t5-photo-acceptance.md)：新上传两页，4 次真实模型调用，三个目标全部完成；实际课包的 20 个答题步骤、206 个数学字段及数轴渲染通过。原照片已参与开发，不作为独立留出。

## 3. 必要测试

最终定向回归 **419 项通过**（144.30 秒）：T5 **156 项**，既有相关能力 **263 项**。本轮涉及的 Python 文件 Ruff 检查通过。

T5 的 156 项包括数学与来源／展示单元 134 项、真实 Stage Three 识别至课程导出及恢复 18 项、原题 staging 与渲染 3 项、实际依赖字节变更 1 项。一般有理仿射关系与复合被求和式另外经过课程编译、KaTeX、数轴 SVG、评分和回放检查。原式无定义、否定量词、后置疑问及引用后否定四类反例均不能进入已求解课程。

T5 命令（在 `server/` 运行，连接隔离测试实例）：

```sh
env PRODUCT_TEST_DATA_DIR=/private/tmp/shuxueshuo-fm-review-20261109 PRODUCT_TEST_INSTANCE=fm-review-20261109 .venv/bin/python -m pytest -q \
  tests/solver/test_graph_symmetry_relation.py \
  tests/solver/test_graph_stage_three_symmetry_relation.py \
  tests/solver/test_graph_symmetry_t5_staging.py \
  tests/solver/test_graph_symmetry_revisions.py --maxfail=1 --tb=short
```

旧能力定向回归文件为 `test_graph_symmetry_value.py`、`test_graph_function_evaluation_math.py`、`test_graph_function_system.py`、`test_graph_function_evaluation_recognition.py`、`test_math_notation.py`、`test_graph_stage_three_function_symmetry.py`，覆盖 T3 对称求值、显式求值、方程组、记法和旧 M5 完整执行。

课包测试调用实际课程编译、作答、回放和后退状态机，错误选项不能推进；对多目标验证目标身份、答案和恢复。公式逐条用 KaTeX 解析，数轴经过生产 `domainNumberLineGraph`、`PracticeComponents.graph` 生成 SVG，拒绝无效坐标。它属于渲染及状态集成，**不等同于浏览器账号操作或截图视觉验收**。

版本测试改动三个数学模块及来源校验模块的真实文件字节，在 `finally` 中恢复；三个实际收集器均须感知变更。旧冻结记录不可被部分改写，恢复相同字节后旧合法执行可继续。测试没有通过替换指纹函数来冒充依赖登记。

## 4. 模型输入改动

prompt 正文未修改。[记法目录](../internal/llm-prompts/problem-math-notation-expressions.json)只新增一个六行 `function_graph_symmetry` 条目，给出原图像事实语法、坐标含义和局部范围约束。该目录会进入模型请求，属于模型输入合同改动；没有加入特定题型解法、轴／中心转换公式、迭代或求和规则。推导由代码处理。

## 5. 当前边界和待验收

- 单函数、至多两条独立生成反射、固定有理坐标及完整声明域；量词反射支持非零有理斜率的一般仿射输入。至多 8 个区间／16 个孤立点，保留开闭及孔洞。
- 有限和最多 4096 项、索引绝对值不超过 10000，轨道化简后至多 32 个基础值；局部精确分区最多 32 轮／128 个切点，数值路径最多 32 步。不能完成闭合分区时报告能力缺口。
- 不执行符号中心、只有平移等式而无反射生成关系、一般非线性函数值条件、无限和、最小正周期或任意函数解析式。对称位置当前是求值／有限和的中间证据，没有独立求位置目标入口。
- **A10 两问和 A14 已通过真实 OCR／模型及课程 API 验收**，新增照片回归 3 项通过；未做账号浏览器流程、独立一般中心／两中心／局部关系新材料验收。R1／R3 的完整退出条件仍待这些验收，原题通过不能代替独立泛化验收。
- 公开课程按既定计划，待 T2–T5 完成后统一刷新证据、重建和 `--check`；本轮未执行。
