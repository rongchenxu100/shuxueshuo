# LLM Role Boundaries and Expansion Strategy

## Summary

网页生成链路中的 LLM 应该承担“规划、表达、编排、审美取舍”的职责，而不是创造数学事实。

一句话原则：LLM 的输出永远是对代码已验证产物的“选择、排列、润色”，而不是“创造、计算、断言”。

当前系统有三个 LLM 节点：

1. Strategy Planner LLM：生成可执行解题 StepIntent。
2. Explanation LLM：把成功执行产物组织成学生可读 LessonIR。
3. Visual Optimizer LLM：对代码生成的 VisualStepIR 做安全视觉优化。

随着题目数量增加，Explanation LLM 和 Visual LLM 很可能需要承担更多职责。但扩展方向应当是扩大“教学表达与视觉编排”的空间，而不是让 LLM 接管坐标、表达式、答案、几何对象存在性等事实生成。

## Current LLM Nodes

### Strategy Planner LLM

职责：

- 选择 method / recipe。
- 组织 StepIntent 顺序。
- 处理题型路线规划。
- 在 repair loop 中根据 accepted prefix、planner insights、blocker 继续规划。

输入：

- canonical ProblemIR 的 LLM 投影。
- family spec。
- method catalog / recipe catalog。
- naming conventions。
- few-shot。
- previous_attempts，包括 accepted prefix、repair_summary、planner insights、preflight warnings。

输出：

- StepIntent draft。
- 不直接输出最终答案。
- 只能引用 ProblemIR 中已声明的 entities / facts / answers handles，或通过 StepIntent creates / produces 声明新的合法 handle。
- 不能发明未知 handle、未知 entity name 或跨 scope 不可见 fact。

repair loop：

- 有。
- 失败后由 runtime diagnostic 和 RepairFeedbackBuilder 生成 previous_attempts。
- 下一轮 LLM 输出完整 StepIntent，系统保留已接受 prefix。

### Explanation LLM

职责：

- 根据 successful runtime artifacts 和 teaching draft 生成 LessonIR。
- 优化学生可读标题、导航标题、derive、box。
- 决定认知步骤的自然分组，但必须受 candidate group 和 source ids 约束。

输入：

- ExplanationSnapshot。
- code-generated candidate groups。
- method / recipe explanation spec。
- teaching_expansion_draft。
- explanation few-shot。
- previous_attempts。

输出：

- LessonIR draft。
- 不允许修改 source ids、capability ids、handles、facts、answers。

repair loop：

- 有。
- 每轮执行 parse -> normalize -> validate。
- 失败后写入 diagnostic 和 repair_summary，最多重试。

### Visual Optimizer LLM

职责：

- 对 code-generated VisualStepIR 做轻量视觉优化。
- 调整强调、隐藏、label 偏移、callout、局部视觉取舍。
- 不生成数学对象，不改变坐标和表达式。

输入：

- code-generated VisualStepIR。
- generated geometry spec。
- generated base layers。
- LessonIR。
- visible geometry refs。
- visual safety constraints。

输出：

- safe visual patch。

repair loop：

- 当前没有。
- sanitizer / validator 会拦截非法 patch，例如未知 geometry ref、非法 component、carry_forward 创建、timeline / interaction 修改。
- 单个 step patch 失败时，该 step 回退到 code-generated scene；其它合法 step patches 可以继续保留。
- 整体优化失败时，回退到代码生成的 VisualStepIR。

## Core Boundary

LLM 可以决定：

- 怎么讲。
- 怎么分组。
- 怎么排序。
- 强调什么。
- 隐藏什么。
- 用哪种视觉表达模式。
- 未来可以在受控模式下建议分几幕动画展示。
- 过渡句、动机说明、学生化表达。
- 冗余推导的删减，例如动画已经清楚展示的中间关系，文字里可以简化或省略。

LLM 不应该决定：

- 点在哪里。
- 线是哪条。
- 曲线表达式是多少。
- 参数值是多少。
- 最终答案是什么。
- 哪些数学对象真实存在。
- 某个结论是否成立。
- 动点参数化公式。
- 交互参数域，包括 domain min / max / step / default。
- carry-forward / persistence 策略，即一个图形对象是否应该自动延续到后续步骤。
- 动画 timeline 的 beat 结构、scene_patch 和时序。当前阶段动画由 deterministic builder 生成；LLM 不参与修改。

数学事实必须来自：

- successful runtime artifacts。
- verified method / recipe outputs。
- canonical ProblemIR。
- method / recipe visual / explanation spec 的角色绑定结果。

## Future Expansion: Explanation LLM

### Cross-Method Merge and Split

当前拆分边界主要由 recipe / method spec 与 deterministic skeleton 控制。

未来题目变多后，会出现两类情况：

- 多个 method 都很短，适合合成一个学生步骤。
- 一个 method 计算很长，适合拆成多个讲解段。

Explanation LLM 可以根据 teaching draft 和题目上下文做更自然的认知分组，但代码仍应提供 hard boundary：

- required candidate group 不能遗漏。
- forbidden merge 不能合并。
- source ids 不能伪造。
- 数学事实不能新增。

### Teaching Strategy Selection

同一个事实可以有多种讲法：

- 代数推导。
- 几何直观。
- 先结论后解释。
- 先构造后证明。
- 错因驱动。

未来 method / recipe spec 可以提供多个 explanation pattern，由 LLM 选择最适合当前步骤的表达策略。

### Motivation and Transition Text

LLM 适合补全：

- 为什么想到作辅助点。
- 为什么要转化成将军饮马。
- 为什么这个参数这样设。
- 前后步骤如何衔接。

这些属于教学表达，不是新增数学事实。

### Derive Orchestration

LLM 不只负责“加文字”，也应该逐步承担“减文字”的职责。

当步骤有对应动画或视觉强化时，某些 derive 行可能已经被图形表达清楚。例如：

- 共线关系已经通过辅助线展示。
- 等长关系已经通过等长构造动画展示。
- 路径替换已经通过高亮线段展示。

未来 Explanation LLM 可以判断哪些 derive 行应省略、压缩或移到动画推导区。代码提供的边界是：

- Lesson step 的 derive 不能与 animation beat 的 derive 矛盾。
- 不能省略最终关键结论。
- 不能删除 validator 要求出现的 answer / box 结论。

### Student-Level Adaptation

同一 LessonIR 可以生成不同版本：

- 简洁版。
- 详细版。
- 中考冲刺版。
- 易错点版。
- 对话讲解版。

LLM 可以调整语言密度和推导颗粒度，但结论仍必须受 Snapshot 约束。

### Misconception and Checkpoint Generation

未来每步可以生成：

- 易错提醒。
- 自检问题。
- 为什么不能这样做。
- 可替代思路。

这类内容应从 method spec 的 common_mistakes / check_templates 出发，再由 LLM 结合上下文表达。

## Future Expansion: Visual LLM

### Visual Clutter Control

题目复杂后，主要问题往往不是画不出来，而是画太多。

Visual LLM 可以参与：

- 哪些 label 应隐藏。
- 哪些点只显示点名不显示坐标。
- 哪些线应 muted。
- 哪些结论应放入 box 而不是图上。
- 是否需要拆成多个图。

### Layout Review

部分布局可以算法化，但 LLM 可以作为高层 reviewer：

- 标签是否拥挤。
- callout 是否遮挡关键对象。
- 是否需要局部放大。
- 是否需要多 panel。
- 当前 step 的视觉焦点是否清晰。

LLM 输出仍应是受限 patch，而不是直接改 geometry。

### Visual Pattern Selection

同一个事实可以有不同视觉表达：

- 角弧。
- 透明三角形。
- 等长 tick。
- 辅助虚线。
- 路径高亮。
- 局部放大。
- 分镜展示。

未来 MethodVisualSpec / RecipeVisualSpec 可以提供候选 visual patterns，LLM 根据 LessonStep 的教学目标选择一种。

### Animation Storyboard Review

当前动画由 code + spec deterministic 生成。

未来复杂动画中，LLM 可以参与 review：

- beat 顺序是否符合教学叙事。
- 是否应先显示构造，再显示全等，再显示替换。
- 哪些推导文本应累计出现。
- 哪些元素应该 step-only，哪些应该 carry-forward。

但动画中的点、线、坐标、参数化公式仍不能由 LLM 发明。

分阶段路线：

1. 当前 VS3：完全 deterministic。spec 声明 timeline templates，代码生成 beats，LLM 不参与 timeline。
2. 中期：代码生成 draft beats，LLM 作为 reviewer 输出 reorder / skip / merge 建议，validator 校验后采用。
3. 远期：LLM 从 recipe visual spec 的 candidate beat patterns 中选择和编排；beat 内的 scene_patch 仍由 code 填充。

### Multi-Panel Composition

复杂步骤可能需要：

- 左右对照图。
- 构造图 + 结果图。
- 局部放大图。
- 动态图 + 静态结论图。

LLM 可以帮助决定是否分 panel、每个 panel 的教学任务是什么；实际对象和位置仍由 code resolver 与 geometry context 决定。

## Recommended Architecture

长期结构建议：

0. ProblemIR canonical source 提供所有数学事实的唯一真相源。
1. method / recipe spec 提供 explanation / visual / animation pattern candidates。
2. code 做 role binding，生成 verified drafts。
3. LLM 选择、排序、压缩、润色、取舍。
4. validator 检查 LLM 没有越过边界。
5. 失败时进入 repair loop。
6. 若 LLM 仍失败，回退 deterministic draft 或 VisualGap。

关键不变式：步骤 3 的 LLM 输出不能引入步骤 0-2 中不存在的数学对象、数值、表达式或结论。

## Repair Loop Direction

Strategy 和 Explanation 已有 repair loop。

Visual 当前是单轮安全 patch。未来如果 Visual LLM 职责扩大，应考虑引入 visual-specific repair loop：

- unknown geometry ref。
- illegal scene patch。
- label collision unresolved。
- too many visible objects。
- missing required visual focus。
- forbidden timeline / interaction modification。

但在此之前，Visual LLM 应保持窄职责，避免过早引入复杂 repair。

## Error Budget

每个 LLM 节点都应有明确的 error budget。

- Strategy Planner：允许较多轮 repair，因为失败会影响整个解题流程；当前默认最多 N 次，由 runtime config 控制。
- Explanation LLM：允许少量 repair，超过后使用 deterministic teaching draft。
- Visual LLM：当前无 repair loop，单轮失败直接回退。未来即使引入 repair，也建议最多 1-2 轮。

原则：LLM 节点越靠近前端渲染，允许的 repair 轮数越少。

Strategy Planner 的输出是求解路线，值得多轮修复；Visual Optimizer 的输出只是视觉增强，失败时应快速回退到代码生成的安全基线。

## Boundary Violation Examples

| 违规类型 | 实例 | 检测方式 | 修复 |
| --- | --- | --- | --- |
| LLM 发明 handle | `unknown_read_handle: runtime:ii:outputs:G_expr` | StepIntent validator | 进入 strategy repair loop |
| LLM 泄露内部表达式到学生 box | `i_1.parabola = x**2 - 2*x - 3` | `_assert_student_readable_box` | 进入 explanation repair loop，要求学生可读表达 |
| LLM 创建 carry_forward 对象 | patch 中新增 `persistence: "carry_forward"` | Visual patch sanitizer | 拒绝该 patch，回退对应 step |
| LLM 引用未来步骤的点 | 等角步骤中引用尚未出现的 `F` | visual ref / visibility validation | 拒绝 patch 或要求改用当前可见对象 |
| LLM 修改参数化公式 | patch 写入 `pointOverrides` / `parameterized_points` | forbidden key check | 拒绝 patch |
| LLM 修改 timeline | patch 写入 `timeline` / `animation.beats` | forbidden key check | 拒绝 patch |
| LLM 修改参数域 | patch 修改 localControls domain default / min / max | forbidden key check | 拒绝 patch |

## Design Principle

LLM 的输出永远是对代码已验证产物的“选择、排列、润色”，而不是“创造、计算、断言”。

LLM 是教学编排者，不是数学事实源。

代码负责：

- 事实。
- 角色绑定。
- 可执行性。
- schema。
- 安全边界。
- fallback。

LLM 负责：

- 教学语言。
- 认知节奏。
- 视觉取舍。
- 表达风格。
- 高层 storyboard。
