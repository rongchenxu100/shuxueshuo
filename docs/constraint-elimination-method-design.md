# M08 条件消元：阶段 5A

阶段 5A 以 q29 验收 M08，q25 留给阶段 5B 的 M07 换元。此模块验证调用方提交的消元路线，不搜索方程解。只在基本不等式 authoring Registry 中开放。

## 参数与来源

`eliminate_by_constraint` 接收原题 `target`，参数为 `eliminate`、`steps[].math`、`expression`。输出 `ConstraintElimination`，包含原目标身份、原条件、被消去的变量、唯一显式还原公式、剩余条件、目标等价关系、来源引用和证书。

待消去变量必须是原变量；还原式不能循环引用它，也不能引入新变量。目标代入后须减少变量。每条提交关系及原始 AST 定义域都要证明；已通过的关系才可供后续行使用。前提标记没有授权作用，不等式估计仍由 M11 处理。

回放逐项检查原目标、参数、关系和证书，不重新搜索。M08 保留原变量，M13 必须回到全部原变量验证取值与原题目标，不能只关闭消元后的式子。

## 正数倒数界传递

M11 新增可选 `elimination` 输入，和 `expression`、`previous_bound` 互斥。显式 `reciprocal: true` 只支持最大值目标并要求同目标 M08 证据：

1. 回放消元，证明原式与消元后表达式等价并严格为正。
2. 对消元后表达式的倒数验证一次局部双项 AM-GM。
3. 证明倒数的常数下界严格为正。
4. 用已有 `monotone` 正倒数分支的证书验证方向翻转，再传递回原目标。

下界按数学关系角色识别，允许后面继续提交正性关系。所有提交行都需要验证；复杂跳步若超出有界原语能力，仍返回明确失败。倒数内部证书与 M08 依赖均纳入最终界证据，修改任何依赖或跨目标绑定均不能通过回放。

本批为 M08 链设置固定序列预算：48 条前提、1024 次代数规约、2048 次尝试和 2048 个证明节点。多项式次数及等式数量限制继续沿用内核默认；调用方更紧预算不会被覆盖。对重复等式只去除冗余的工作前提，逐行证书与来源仍保留。

## 教学与展示

`elimination-teaching-evidence/v1` 是成功执行证据的公开投影，提供原条件、目标、还原关系、剩余条件及已验证推导，不暴露内部证明证书。

消元证据中的 `remaining_conditions` 保留全部代入结果；展示投影另给 `display_remaining_conditions`，只去除代入后恒成立的等式，图中不展示这些恒等式。

M08 使用共享结构图：原条件与目标 → 还原关系 → 代入后的条件 → 消元后的目标。详细推导保留在正文，不按行下标选择图示。M11 显式标示先求倒数正下界，再回到原式上界；M13 区分经过验证的联立推导与具体取值验证。只有前者可宣称“解得”，后者写“当……时，满足原条件且等号成立”，不宣称穷尽。

M11 在存在已验证倒数变换时，先生成独立的“取倒数并整理目标”教学单元，再生成“观察结构”“应用基本不等式”。`TeachingUnitSpec.activation_role` 引用代码绑定的布尔角色；缺失或类型错误明确失败，普通 AM-GM 的角色为 false，不生成额外单元。该单元仍属于 M11，求解计划不增加 Method。正性、倒数表达式和整理关系投影自已验证证据，VisualSpec 使用共享结构图组件。

倒数路径的应用稿按“倒数下界 → 正性与反向理由 → 原式上界”排列，只输出一次原式上界。参与项和推导使用已验证 AST 的 LaTeX 投影，正文在消费角色时添加数学定界符，不直接显示内核字符串。正倒数证明复用 `monotone`，不新增等价规则；旧证书不修改，从保存的 Planner 记录重新执行生成当前规则集的证书。

取等图的布局与求解证据分开：单次取等都显示方框/圆框配对。有联立推导时展示求解流程；只有已验证取值时使用 `solutionMode: witness`，从具体取值指向原条件与正项相等，再代回目标，不能将其画成“方程推出解”。多次取等与分支推导继续沿用既有展示。

## 输入与复现

q29 输入直接转录自原始题图，保存于 `server/tests/solver/fixtures/basic-inequality-stage5a/q29/`，包含图像、摘要、Notation、确定性 ProblemIR 和测试计划。来源记录不冒充真实 LLM 抽取或人工审核批准；真实 Planner 不读取测试答案或预定 Method 链。原有 20 份冻结样本与 10 题 ProblemIR 保持不变。

在 `server` 目录执行（输出路径必须不存在）：

```sh
uv run pytest -q tests/solver/test_basic_inequality_stage5a.py
uv run python tools/run_basic_inequality_stage5a.py --mode recorded --samples 2 --lesson deterministic --output ../internal/review-analysis/basic-inequality-stage5a/new-recorded-run
uv run python tools/run_basic_inequality_stage5a.py --mode deepseek --samples 2 --lesson deepseek --output ../internal/review-analysis/basic-inequality-stage5a/new-live-run
uv run python tools/build_basic_inequality_problem_ir.py --check
```

验收同时要求求解成功、M08 实际执行且被消费、证书离线回放、无回退的真实讲解和浏览器检查。历史失败保留在原目录，后续重跑单列统计。
