# 整理式子 Method：q08 首轮实现

状态：阶段 4 证明内核迁移与 q08 求解闭环已实现，代表四题的真实 Planner 双样本验收通过。现有 q08 整题页未切换，本次不新增页面。

## 阶段 4 迁移补充

M01 内部已迁移到安全表达式 Parser 与有界证明内核：支持 sqrt 和有界整数幂，保留旧有理式 API、参数协议、展示节点和同对象提交语义。每行验证原始定义域、选定 `using` 等式下的等价关系并回放证书；证书只进入后端审计。正性条件须来自绑定输入，不能用 SymPy Symbol 假设替代。`using` 填数学等式，不填目录引用名称。

完整 q08 现在通过冻结 ProblemIR → M01 → M11 → M13 验证最小值 4，以及两个互换根式见证。后续 M11 使用原目标对象 SourceRef 读取 M01 提交的准确版本。新题教学页和合并 rule 不在本次迁移内，旧 q08 整理展示回归保留。

下文为首轮有理式实现的历史设计；其中旧验证器与只支持有理式的限制由本节及实施计划阶段 4 扩展替代。

## 1. 职责与对象边界

`organize_expressions`（整理式子）不寻找解法。LLM 写候选完整式链，代码验证、识别相邻结构变化、生成讲解。它不是把 LLM 的标签当作数学证明，也不要求 LLM 编写 HTML、reason 或教学节拍。

**规范地位：** 本 Method 是新增能力的优先范式。增加 Method 时须先按 `docs/functional-method-dsl-authoring-guide.md` §3 判断能否做成「LLM 填候选、代码验事实」；公开 capability 侧见 `docs/capability-authoring-guide.md` §1.1。

| 层 | 职责 | 不负责 |
|---|---|---|
| LLM | 选择整理路线，输出 `parameters.steps`，标出使用的已有条件 | 运算类型、证明通过标志、结构节点、状态版本、学生文案 |
| Method | 限定语法解析、逐步等价验证、定义域检查、操作分类、最终 Expression | 选择两个正项、算定积、AM-GM、取等闭合 |
| Functional runtime | 参数校验、条件身份绑定、准确读版本、提交一个同对象新版本、失败回滚 | 将中间推导伪装成事实 |
| Explanation / text visual builder | 从成功 trace 生成 LessonIR、局部公式、四个节拍及结构定位 | 再求解数学问题 |
| 页面组件 | 显示 spec、上一步/下一步/重播/查看全部 | 运行 SymPy、猜测数学变化 |

复用现有 `MathObjectId`、`StateVersionId` 和事务解释器，没有增加中间数学对象类型。输入表达式的状态从 v0 更新到 v1，三个候选式不是三个状态。前端的 `t0`、`n.0.1` 只是该图示内的节点 ID。

`Expression` 原先没有全局固定的 MathObject kind。因此不能把所有 Expression 都改为函数或点。新增的保留身份规则只允许：返回显式声明 `preserve_input_object`，输入有准确的已绑定 Expression 版本，且输入输出的 state_kind 相同；所属对象直接取该版本的 owner。不会从式中出现的 a、b 推断 owner。

## 2. 输入与调用协议

题面上下文：`a>0`、`b>0`、`a*b=1`，目标 `1/(2*a)+1/(2*b)+8/(a+b)`。运行时保留真实 Symbol 身份，不重新创造变量。

```json
{
  "step_id": "rewrite_1",
  "capability_id": "organize_expressions",
  "args": {
    "expression": "target_expression",
    "conditions": ["positive_a", "positive_b", "product_condition"]
  },
  "parameters": {
    "steps": [
      {"math": "1/(2*a)+1/(2*b)+8/(a+b)"},
      {"math": "(a+b)/(2*a*b)+8/(a+b)"},
      {"math": "(a+b)/2+8/(a+b)", "using": ["a*b=1"]}
    ]
  }
}
```

这段是确定性 fixture，不会放入真实测试 prompt。真实 prompt 只给题目、绑定目录、JSON 形状、参数 schema 和输出规则。

| 输入 | 声明 | 规则 |
|---|---|---|
| expression | Expression，`latest_state`，state_kind=`expression` | 绑定目录中的对象/状态；准备阶段选择并固定准确版本 |
| conditions | ConditionList，`immutable_value` | 沿用现有集合输入机制，每个条件有独立 Fact read authority |
| parameters.steps | 候选字面量，不是事实输入 | 2–12 行，math 1–1024 字符，禁额外字段；using 最多 8 项 |

这里 `latest_state` 是现有读取视图名，并非执行时随意读可变值。生产事务先解析为具体 StateVersion，再为本次调用生成快照。`exact_result` 在现有体系中偏向已执行调用的结果，不适合题面给定的首个状态。

每行必须是完整表达式，第一行不允许 using，且应与绑定输入无条件等价。非首行的 using 必须唯一匹配本次绑定条件。允许整数、显式 `*`、`/`、括号、`^`/`**` 整数幂；不接受 LaTeX、函数调用、属性访问、下标或自然语言。

### 参数在调用链中的位置

ScopedFunctionalStep → FunctionalCall → FunctionalCallReconciliation → FunctionalDirectCompiler → MethodInvocation.parameters → Method。

Method 在 SPEC 声明 `parameters_schema`。规划 schema、编译、执行均保留参数；`ComputationKey.parameters_hash`、编译签名、重放 authority payload 保留参数影响。不同推导不能复用同一调用指纹；pinned reconciliation 也检查参数一致。旧 Method 没有 schema 时只接受空 parameters，旧空参数指纹的序列化形状保持不变。

`rational_expression_rewrite` Capability Pack 注册显式同对象更新 contract 和输入绑定规则。没有新增完整基本不等式 Family，也没有改写原有题型路由。

## 3. 数学验证与分类

### 双表示

Python AST 经白名单遍历转换成两个关联结果：

1. 有序展示树：保存分式、加项顺序、有意义的括号分组与节点路径；不全局 simplify。冗余括号和空格保存在原始调用字符串中，不单独作为图示节点。
2. 使用已有符号的 SymPy 值：用于精确有理运算。

不使用 eval，也不直接对候选字符串调用 sympify。每式最多 256 AST 节点、32 层；整数绝对值不超过 10^9，整数字面量指数绝对值不超过 12；拒绝嵌套幂，潜在展开规模超过 128 的式子保守拒绝。条件最多 16 项；条件等价证明最多 4 个变量、4 个等式，多项式总次数不超过 12、项数不超过 128。超过限制是“尚不能验证”，不是判数学错误。

### q08 的两次变化

| 转换 | 数学验证 | 结构证据 | 输出 |
|---|---|---|---|
| 前两项合并成 `(a+b)/(2*a*b)` | `cancel(before-after)==0`，局部也等价 | 移除未变的 `8/(a+b)`；两个 div 节点变一个 div；公分母除以各原分母是多项式 | combine_fractions；公分母、乘数、局部节点、未变部分 |
| `2*a*b` 变为 `2` | 所选等式下差的分子属于等式生成的多项式理想 | 对原值执行已绑定等式代入能得到后值 | substitute_condition；conditionCardId、替换块和值 |

无 using 时只按恒等检查。有 using 时采用有理差分子及 Groebner 理想余式的充分证据，不用随机抽样代替证明。所选等式矛盾时拒绝。

所有候选行的显式除法和负整数幂都检查分母非零。正负性证据来自绑定不等式，借助 SymPy assumptions 和乘积/幂分解；不默默新增排除点。定义域推理是保守的，例如仅知道 `ab=1` 时不能保证 `a+b≠0`，会拒绝本题链。

“通分显条件”是两次操作的组合效果，不是单独 Method：代码先检测新分母为已知条件块的常数倍，再确认后续确实使用该条件代入。仅有一次通分或单纯代数等价，不足以贴这个教学标签。

### 拒绝和降级

| 情况 | 行为 |
|---|---|
| 语法不合法、未知变量、链首不匹配、using 未绑定 | 拒绝，给出行号/诊断；不提交 |
| 逐步等价或分母非零未证明 | 保守拒绝；不提交 |
| 数学通过、结构规则不覆盖 | 提交最终式，equivalent_rewrite 普通链；记录 classificationGap |
| 多次变化压成一步 | 不强行拆解 LLM 没给的中间过程；不编造“通分显条件” |

首轮不支持条件自身的等价改写、非整数幂、根式、指数统一底数、引入新变量。SymPy 值虽可进一步简化，最终展示仍使用最后一行的树。

## 4. 输出、事务及证据

`StatelessMethodResult.outputs` 只有 `organized_expression: Expression`。q08 计算值可能以 SymPy 展开加项顺序存储，但 trace.result 保存 `(a+b)/2+8/(a+b)` 的展示树。

checks 覆盖输入绑定、定义域、逐步等价、条件来源。trace_fragments 中的 `verified_expression_rewrite` 保存 source、result、transitions、conditionCards、teachingEffect；转换中有完整前后式、localBefore/localAfter、unchanged、highlights、evidence 和替换记录。

生产事务实验用现有 `FunctionalPlanReconciler → FunctionalTransactionalInterpreter → InvocationExecutor`，不是直接调用 Method 后自行宣称提交。已覆盖：v0→v1、相同 owner、一个公开写入、第二次变化错误时零提交、逐项条件 authority、编译后的推导参数不丢失。生产输出中的 `allocation_action=transition` 是更新动作权威字段。

当前实验只执行整理前缀，不向极值答案槽发布数据，不把目标标记成已解答。T 的容器身份使用现有 function MathObject vocabulary，state 类型是一般 Expression；不是把本题谎称为二次函数。

## 5. 学生步骤和前端 spec

本节描述已实现的 q08 独立整理前缀，不是所有 Method 必须对应一个学生步骤的限制。2026-09-10 已确认的后续设计是：Method 声明多个讲解片段及各自组件，代码同步组合学生步骤与前端展示；q08 可将 M11 的结构识别片段并入“观察结构”，q03 则将“观察次数”和“配齐次式”拆为两个学生步骤。2026-09-24 已补齐 M01 的保守次数识别：仅对成功证明的乘入定值 1、且次数互补的实际变形生成配齐次展示。讲解编排新增次数观察，并仅在 M11 的绑定输入确实来自该次 M01 时合并其配对观察；q08 继续保留通分展示。详见 [基本不等式讲解规则](basic-inequality-method-discussion.md#lesson-layouts)。

2026-09-15 补充共识：Method 提供片段与依赖，学生步骤的拆分/合并由单一基本不等式 Family 所引用的注册讲解 rule 决定。rule 组织的步骤先完整锁定，Lesson LLM 只编排剩余开放材料，代码校验边界并注入固定步骤；这不同于本首轮实验中只负责提交整理式链的求解 LLM。该协作设计及锁定协议均尚未实现，详见 [Family 与 rule](basic-inequality-method-discussion.md#family-rules) 和 [Lesson LLM 协调](basic-inequality-method-discussion.md#lesson-llm)。

一个教学步骤“整理目标式：通分显条件”，内部四拍：

| 节拍 | 局部内容 | 完整目标的处理 |
|---|---|---|
| 观察 | 突出前两个分母，显示已知条件卡 | 显示原目标 |
| 通分 | `1/(2a)+1/(2b)=(a+b)/(2ab)` | 明示第三项保持不变，累计显示完整链 |
| 代入 | `ab→1`，`(a+b)/(2ab)=(a+b)/2` | 关联使用的条件卡，累计完整链 |
| 汇总 | 最终完整表达式 | 只总结，不新增数学断言 |

没有“定积 4”“最小值 4”或取等条件。

执行成功记录 → ExplanationSnapshot → MethodExplanationSpec 的已注册 role binder → LessonIR → MethodVisualSpec 的 text visual binder → `expression-rewrite` → 文字课件编译器。

通用文字组件在 `visual/text_builder.py` 注册，与几何 VisualStepIR 的点线组件分开；它不是把有理式包装为几何对象。讲解和视觉均从同一 trace 取值。

| spec 字段 | 含义 |
|---|---|
| source/result | `latex` + 有序 tree |
| conditionCards | 局部展示 ID 和代码生成的 LaTeX；学生 spec 不含后台路径 |
| transitions | id、operation、before/after、localBefore/localAfter、unchanged、highlights、conditionCardIds、evidence |
| localBefore/localAfter.nodeIds | 在对应完整式树中的局部节点集合 |
| highlights | side + nodeId + role；不做字符串替换 |
| replacements | 被条件替换的 block、value 和 conditionCardId |
| beats | focus / transform / result，引用 transitionId |

目前条件块高亮定位至包含它的分母节点，并另显示条件块；例如框住 `2ab`、条件卡显示 `ab=1`，没有声称已经支持任意跨树子块的精细着色。

页面提供上一步、下一步、重播、查看全部。公式可局部横向滚动，有窄屏 CSS；按钮逻辑经过 DOM mock 测试。渲染器转义界面和树节点文本，编译器校验节点引用，并对新组件内联 JSON 的 `<` 编码，防止脚本闭合注入。

自动浏览器打开 file URL 被浏览器安全策略拒绝；没有绕过策略。桌面/窄屏的实际像素布局和点击实测仍待人工或获准浏览器环境验收。

## 6. 产物与复现

| 产物 | 路径（相对仓库） |
|---|---|
| Method / schema / prompt | `server/shuxueshuo_server/solver/runtime/methods/organize_expressions.py` |
| 安全解析、证明、结构分类 | `server/shuxueshuo_server/solver/math_kernel/expression_rewrite.py` |
| 固定上下文和候选调用 | `server/tests/solver/fixtures/expression_rewrite/q08.json` |
| 原生事务实验 | `server/shuxueshuo_server/solver/expression_rewrite_transaction.py` |
| 执行与页面生成入口 | `server/shuxueshuo_server/solver/expression_rewrite_experiment.py` |
| 已生成执行记录、Snapshot、LessonIR、学生步骤、视觉 spec | `internal/experiments/organize-expressions-q08/deterministic/` |
| 独立页面 | `site/previews/inequality-basic-q08-organize.html` |
| 真实测试状态 | `internal/experiments/organize-expressions-q08/live/REPORT.md` |

在 server 目录运行：

```sh
.venv/bin/python -m shuxueshuo_server.solver.expression_rewrite_experiment
.venv/bin/python -m pytest tests/solver/test_organize_expressions.py tests/solver/test_organize_expressions_transaction.py -q
```

在仓库根目录运行：

```sh
node --test tools/tests/expression-rewrite.test.mjs tools/tests/text-lessons.test.mjs
```

配置现有 provider 后，在 server 目录运行真实批次：

```sh
.venv/bin/python -m shuxueshuo_server.solver.expression_rewrite_experiment --live
```

每批独立目录，不覆盖旧批次。请求 5 次，每次新 client、同一 prompt，无解法修复重试；保存 rawResponse、actualModel、耗时、usage、providerAttempts、协议/数学/分类/前端四层结果。现有 provider client 若触发 reasoning-only 空响应重试，会在 providerAttempts 单列，不隐瞒其实际请求数。

## 7. 当前验收结论

本次相关 Python 回归批次通过 214 项（覆盖新 Method、生产事务、参数/状态协议及旧编译器）；文字页和新组件 Node 测试通过 57 项。另有补充安全与绑定回归。测试命令保存在上节，实际浏览器视觉验收和真实模型成功率不包含在这些数字中。

确定性主链已证明这条分工可行：LLM 不填 operation，代码能从完整式链生成本例的局部教学展示。安全边界和保守降级也有测试覆盖。

尚不能据此宣称 LLM 协议稳定或通用于全题库：5 次真实请求尚未发出，且分类只保证有理式通分、显式等式代入及其组合。下一轮可在真实输出中统计“数学正确但分类缺口”的比例，再决定增加哪些结构规则，而不是提前增加 Method 数量。
