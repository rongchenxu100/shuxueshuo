# VisualStepIR 设计

## 1. 目标

VisualStepIR 将 LessonIR 中的教学步骤转换为可验证的视觉场景与交互，而不是让 LLM 直接生成 HTML、CSS 或动画代码。

```text
ProblemIR + ExplanationSnapshot + LessonIR
→ visual role binding
→ VisualStepIR
→ validators
→ scene/animation compiler
→ lesson page
```

## 2. 设计原则

- 数学事实来自上游 Context，不由视觉层重新计算；
-对象使用稳定 identity/role，不按 label 文本猜测；
-每个视觉变化可追溯到教学步骤和 source fact；
-静态场景、交互和动画共享同一对象模型；
-LLM 声明视觉意图，代码负责几何计算、布局和 runtime safety；
-无法表达的视觉需求产生结构化 gap，不拼接任意前端代码。

## 3. 核心结构

```text
VisualStepIR
  lesson_step_id
  scene_id
  source_refs[]
  objects[]
  role_bindings[]
  camera
  visibility[]
  annotations[]
  interactions[]
  beats[]
```

### Scene object

每个对象包含：

- visual id；
- semantic object id 或 derived role；
- object kind；
- geometry/style 参数；
- source refs；
-初始 visibility。

visual id 仅在页面场景内使用，不能替代 MathObject identity。

### Role binding

role 描述教学用途，例如：

- target point；
- reference point；
- moving object；
- source curve；
- result locus；
- comparison segment。

同类型对象靠 role 和 source identity 区分。编译器不能根据对象名称或出现顺序选择角色。

### Beat

Beat 描述一个可观察的教学变化：

-显示/隐藏对象；
-强调条件；
-移动或构造对象；
-绘制轨迹；
-更新公式或结论；
-等待交互或旁白时间点。

Beat 只引用已声明对象和动作类型。

## 4. 事实来源

合法 source 包括：

- ProblemIR primitive、condition 和 goal；
- ExplanationSnapshot 中 verified call/write；
- LessonIR teaching step；
-前一 visual step 的显式 retained state。

禁止来源：

- LLM 自造坐标；
- expected answer；
- runtime path；
-无 provenance 的 debug 文本；
-根据 handle 前缀猜测的对象。

## 5. 场景状态

Visual state 分为：

- persistent：跨多个步骤保留的基础图形；
- step-local：只服务当前讲解步骤；
- derived：由 compiler 根据 typed facts 生成；
- interaction-local：拖拽或播放时的临时状态。

步骤切换时必须显式声明 retain、update 或 remove。不能依赖 DOM 残留。

## 6. 几何与坐标

-坐标和曲线参数来自 typed facts；
-数学坐标到屏幕坐标由统一 viewport transform 处理；
-label layout 使用确定性碰撞处理；
-关键对象必须处于可视范围；
-动态轨迹应声明 domain、sampling 和 clipping；
-同一对象的多个视觉实例必须共享 semantic source。

## 7. 交互

交互声明包含：

- trigger；
- manipulated role/object；
-约束；
-派生更新；
-验证目标；
- reset 行为。

交互 runtime 只操作可视状态，不回写 solver Context。若交互需要数学求值，应调用确定性 evaluator，而不是 LLM。

## 8. 动画与旁白

AnimationContext 将 beat 与 voiceover units 对齐：

-每个 beat 有稳定 id；
-可选 earliest/latest time；
-旁白可覆盖一个或多个 beat；
-手动交互可暂停 timeline；
-音频缺失时仍能独立播放视觉步骤。

动画时间不是数学事实，不进入 LessonIR。

## 9. Gap 机制

若当前 compiler 无法表达视觉意图，生成 `VisualGap`：

- source step；
-需要的 object/role/action；
-现有能力缺口；
-是否可确定性实现；
-最小复现 fixture。

优先扩展通用 visual capability；禁止为单题直接注入脚本。

## 10. 验证器

至少检查：

-所有 source ref 存在；
-role binding 唯一且类型兼容；
-所有 beat 引用已声明对象；
-无不可见对象上的交互；
-坐标、domain 和 viewport 有效；
-步骤 retain/remove 闭合；
-LessonIR 关键结论有对应视觉表达；
-移动对象、轨迹对象与教学语义一致；
-无未经声明的 HTML/JS/CSS。

## 11. LLM 边界

LLM 可决定：

-采用哪类视觉机制；
-哪些对象需要强调；
-步骤如何分镜；
-讲解与交互的顺序。

代码决定：

-对象 identity 和角色绑定；
-精确坐标/曲线计算；
-布局、碰撞和 viewport；
-动作参数合法性；
-最终 DOM/canvas/runtime 实现。

## 12. Context 集成

Track G 中：

- VisualStepIR 作为 DiagramContext artifact；
-依赖 LessonIR step ids 和 source fact hashes；
-上游局部变化只重建受影响场景；
-AnimationContext 引用 scene/beat ids；
-LessonPageContext 只聚合编译后资产。

## 13. 测试与验收

- schema 与 source-ref validation；
-同名不同对象 role 绑定；
-跨步骤 persistent state；
- label collision 与 viewport；
-interaction reset 和 constraint；
- beat/voiceover 对齐；
-故意缺 role/source 时 fail loud；
-页面截图和交互回归；
- authored fixture 的关键教学覆盖。

## 14. 相关文档

- `docs/explanation-builder-design.md`
- `docs/llm-context-model-design.md`
- `docs/frontend-parallel-development-with-mock-api-plan.md`
