# VisualStepIR 设计方案

## Summary

`VisualStepIR` 是 ExplanationBuilder 的图形意图层。它不直接生成 React 代码、SVG、HTML、`geometry-spec.json` 或 `step-decorations.json`，而是生成一份可校验的声明式视觉状态：

```text
LessonIR
  -> VisualStepIR
  -> VisualStep Compiler
  -> geometry-spec.json + step-decorations.json + lesson-data local controls
  -> React/runtime components render
```

核心原则：

- `VisualStepIR` 依赖已生成的 `LessonIR`，一个 `LessonStep` 对应一个 `VisualStep`。
- `VisualStepIR` 是 method/recipe visual spec 结合当前题上下文后的渲染结果；visual spec 是领域模型源头。
- 数学事实来自 successful runtime artifacts 和 `ExplanationSnapshot`，不是 LLM 自造。
- `VisualStepIR` 更像 React component props 的数据模型，而不是低层渲染代码。
- 当前系统已经有静态图形、主参数 slider、local point controls、linked controls；`VisualStepIR` 应把这些现有组件抽象为统一的 declarative interaction model。
- 未来动画在同一模型中扩展为 `timeline.on_enter.frames[]` 和 step transition，不推翻静态/交互层。

### Design Principles (React-Inspired)

1. **Declarative over Imperative**
  `VisualStepIR` 声明“学生应该看到什么”，不描述“如何画”。就像 React 声明 `UI = f(state)`，不直接操作 DOM。
2. **Unidirectional Data Flow**
  数据流固定为 `method/recipe visual spec -> role binder -> VisualStepIR -> compiler -> JSON -> runtime`。runtime 事件，例如 slider drag，只改变 Visual State，不回溯修改 VisualStepIR 或 method spec。
3. **Composition over Inheritance**
  复杂视觉组件由简单组件组合而成，例如 `DistanceMarker = Segment + Label`，不通过继承扩展。
4. **Stable Keys for Reconciliation**
  每个 scene object 的 canonical `handle` 是稳定 reconciliation key。step 间转场时，handle 相同的对象做 diff，而不是重建。
5. **Props are Immutable, State is Local**
  Visual Props，也就是 spec + bindings，不可变；Visual State，也就是 slider 值、当前 frame、当前 candidate，只在 interaction 范围内可变；Derived Scene 由两者计算。
6. **Fallback for Gaps**
  角色缺失时展示 `VisualGap` 占位，不画假图，类似 React Error Boundary / Suspense fallback。

## React Data Model Mapping

`VisualStepIR` 借鉴 React 的数据模型，但不直接生成 React 组件代码。这里的对应关系用于约束 IR 设计。

### Visual Props / State / Derived Scene

- **Visual Props**：method/recipe visual spec、role bindings、scene diff、interaction schema。它们来自 verified runtime artifacts，不可由学生操作改变。
- **Visual State**：交互组件的当前状态，例如 slider 参数 `u=0.5`、当前选中的 candidate、timeline 当前 frame。
- **Derived Scene**：由 Visual Props + Visual State 计算得到的当前可见对象集合。

```text
resolved_scene = f(visual_props, visual_state)
```

LLM 和 spec 只能影响 Visual Props；Visual State 的初始值来自 `interaction.domain.default`、`geometry_context.moving_param_default` 或 renderer 默认值；Derived Scene 完全由 compiler/runtime 计算。

这个区分带来两个约束：

- Validator 检查 Props 是否只引用 verified handles，State 是否落在 interaction domain 内，Derived Scene 不能被 LLM 直接写入。
- 当同一 step 内只改变 slider 参数时，runtime 只重算受该参数影响的对象，不需要重新生成整张图。

### Step Transition Reconciliation

VisualStepIR 的 `resolved_scene` 应支持 step 间 reconciliation。学生从 step N 切换到 step N+1 时，runtime 可以比较两个 resolved scene：

```text
transition(step_N -> step_N+1)
  = objects_to_add     # N+1 有、N 没有
  + objects_to_remove  # N 有、N+1 没有
  + objects_to_update  # same handle, different state
  + objects_unchanged  # same handle, same state
```

首版不要求前端实现动画；reconciliation 的结果可以退化为直接替换，行为与现有全量重绘一致。后续可以渐进式引入：

- 新对象 fade in。
- 移除对象 fade out。
- `highlight -> muted` 等状态变化做过渡动画。
- 未变化对象保持不动。

这解释了为什么 scene object 必须使用 canonical `handle` 作为稳定 key，不能依赖自动生成 id。

### Component Composition

`ComponentTypeSpec` 支持两层落地：

- `compiles_to`：直接映射到现有 `step-decorations` 低层 type。
- `children`：组合已有 Visual component，形成组件树。

V1 可以先用 `compiles_to`；长期应优先用 `children` 表达可复用组合，例如 `DistanceMarker = Segment + Label`。

### Context Provider

`GeometryContext` 支持层级继承：

```text
global geometry context
  -> section geometry context
  -> step geometry context
  -> panel geometry context
```

大多数 step 只继承全局 context；局部放大、切换范围、多面板图形时才声明 override。现有 `grid.panels` 可以映射为 panel-level nested context。

### Timeline Lifecycle

`TimelineSpec` 类似 React effect lifecycle：

- `on_enter`：进入 step 时播放演示或设置初始视觉状态。
- `on_exit`：离开 step 时声明 cleanup 策略。
- reconciliation：从当前 step 过渡到下一 step 时计算最小视觉变化。

默认 cleanup 是 `keep_final_state`，即保留 timeline 最终帧状态进入下一步，再由下一步的 scene diff 或 reconciliation 接管。

### VisualGap As Fallback UI

当 role 绑定不完整时，不应画错图，也不应让页面空白。VisualStepIR 应生成 `VisualGap`，作为类似 React Error Boundary / Suspense fallback 的占位组件。

`VisualGap` 只提示“此处缺少可验证视觉对象”，不创造数学事实。

## VisualSpec As Source

`VisualStepIR` 不应该从零开始“想图怎么画”。它应由 method/recipe 的 visual spec 发起：

```text
MethodSpec / RecipeSpec
  ├─ execution spec：怎么算
  ├─ explanation spec：怎么讲
  └─ visual spec：怎么画、怎么交互、怎么演示
```

生成时：

```text
method/recipe visual spec
  + LessonStep source ids
  + ExplanationSnapshot facts / trace / answers
  + BaseRoleBinder shared handle bindings
  + VisualProjection
  -> VisualStepIR draft
  -> optional LLM polish
  -> VisualStepIR
```

### MethodVisualSpec

Method 是原子能力，`MethodVisualSpec` 描述“这个计算在一个 Lesson step 中如何被看见”。

示例：

```python
MethodVisualSpec(
    role_schema={
        "p1": "第一个点",
        "p2": "第二个点",
        "distance": "距离表达式"
    },
    scene_templates=(
        {"component": "Point", "role": "p1", "state": "highlight"},
        {"component": "Point", "role": "p2", "state": "highlight"},
        {"component": "Segment", "from_role": "p1", "to_role": "p2", "state": "emphasized"},
        {"component": "DistanceMarker", "from_role": "p1", "to_role": "p2"}
    ),
    annotation_templates=(
        {"type": "formula", "text": "{p1}{p2} = {distance}"},
    ),
    interaction_templates=(),
    timeline_templates=(),
    role_binder_id="distance_between_points_visual"
)
```

适合 method visual spec 的例子：

- `distance_between_points`：高亮两点，画线段，标距离。
- `quadratic_from_constraints`：显示抛物线约束点，强调这些点确定函数。
- `line_parabola_second_intersection_point`：显示直线、抛物线、已知交点和新交点。
- `parameter_from_expression_value`：图上固定当前表达式对应对象，annotation 展示代入求参。

Method visual spec 只写角色，不写当前题点名。

### RecipeVisualSpec And Teaching Substeps

Recipe 是复合教学动作，但学生实际看到的是 LessonIR 的认知子步骤，而不是 recipe 的整体执行块。

因此 recipe 的视觉模板必须和 `TeachingSubstepSpec` 对齐：

- `RecipeVisualSpec` 负责声明 recipe 级共享角色、视觉 binder、默认约束。
- `TeachingSubstepSpec` 负责声明当前认知子步骤自己的 visual scene / interaction / timeline templates。
- VisualStepBuilder 根据 `LessonStep.teaching_substep_id` 找到对应 substep spec，直接生成该 VisualStep。

这避免额外做“从 recipe 整体视觉模板拆回子步骤”的推断。

示例：

```python
RecipeVisualSpec(
    role_schema={
        "segment_moving_point": "线段上的动点",
        "ray_moving_point": "射线上的动点",
        "auxiliary_point": "构造出的辅助点",
        "original_path": "原路径",
        "reduced_path": "转化后的路径"
    },
    role_binder_id="equal_length_ray_path_reduction_visual",
    teaching_substep_specs=(
        TeachingSubstepSpec(
            substep_id="path_reduction",
            title="构造辅助点，把两动点路径转化为单动点路径",
            focus="construction_and_distance_replacement",
            preferred_method_ids=("equal_length_ray_point",),
            visual_scene_templates=(
                {"component": "Path", "role": "original_path", "state": "muted"},
                {"component": "AuxiliaryConstruction", "target_role": "auxiliary_point", "state": "constructed"},
                {"component": "DistanceMarker", "role": "original_replace_segment", "state": "highlight"},
                {"component": "DistanceMarker", "role": "replacement_segment", "state": "highlight"},
                {"component": "PathTransform", "from_role": "original_path", "to_role": "reduced_path"}
            ),
            visual_interaction_templates=(
                {
                    "component": "LocalSlider",
                    "controls_role": "segment_moving_point",
                    "linked_roles": ["ray_moving_point"],
                    "purpose": "拖动动点，观察等长约束和路径替换"
                },
            ),
            visual_timeline_templates=(
                {"id": "show_original_path", "actions": [{"type": "show", "targets_role": "original_path"}]},
                {"id": "construct_auxiliary_point", "actions": [{"type": "construct", "targets_role": "auxiliary_point"}]},
                {"id": "show_distance_replacement", "actions": [{"type": "highlight", "targets_role": "replacement_segment"}]}
            )
        ),
        TeachingSubstepSpec(
            substep_id="minimum_by_segment",
            title="利用两点之间线段最短，求路径最小值",
            focus="minimum_distance",
            preferred_method_ids=("distance_between_points",),
            visual_scene_templates=(
                {"component": "Path", "role": "reduced_path", "state": "muted"},
                {"component": "Segment", "role": "minimum_segment", "state": "emphasized"},
                {"component": "DistanceMarker", "role": "minimum_distance", "state": "result"}
            ),
            visual_interaction_templates=(),
            visual_timeline_templates=(
                {"id": "show_reduced_path", "actions": [{"type": "show", "targets_role": "reduced_path"}]},
                {"id": "show_minimum_segment", "actions": [{"type": "highlight", "targets_role": "minimum_segment"}]}
            )
        )
    )
)
```

`TeachingSubstepSpec` 的 visual templates 是 recipe 视觉表达的最小单元。一个 executable recipe 可以对应多个 Lesson steps；每个 Lesson step 只读取自己 substep 的 visual templates。

如果某个 substep 没有显式 visual templates，VisualStepBuilder 可以用 `preferred_method_ids` 组合对应 method visual spec 作为 fallback。

生成优先级：

```text
TeachingSubstepSpec.visual_*_templates
  > preferred MethodVisualSpec composition
  > generic fallback
```

`RecipeVisualSpec` 的优先级仍高于 method visual spec，但它通过具体 substep 生效，而不是生成一个 recipe 级大画面。

### Shared Role Binding

Visual spec 和 explanation spec 都只声明角色。角色到当前题 verified handles 的绑定必须共享同一套 base binder，避免讲解文字和图形高亮不一致。

```text
{segment_moving_point} -> point:ii:M
{ray_moving_point} -> point:ii:N
{auxiliary_point} -> point:ii:G 或 visual-only label
{original_path} -> OM+BN
{reduced_path} -> OM+MG
```

推荐结构：

```python
class BaseRoleBinder:
    def bind_handles(self, group, snapshot) -> dict[str, str]:
        """共享的 role -> canonical handle 映射。"""


class ExplanationProjection:
    def project(self, handle_bindings) -> dict[str, Any]:
        """把 role handles 投射为讲解文本角色、proof draft 和 box。"""


class VisualProjection:
    def project(self, handle_bindings) -> dict[str, Any]:
        """把 role handles 投射为 scene、interaction 和 timeline 模板实例。"""
```

`ExplanationRoleBinder` 和 `VisualRoleBinder` 不应各自重新猜角色；它们应共享 `BaseRoleBinder.bind_handles()` 的结果，再分别投射到自己的输出格式。

这样可以保证：

- LessonIR 里讲的是 `point:ii:M`，VisualStepIR 也高亮 `point:ii:M`。
- recipe substep 的角色缺失会同时变成 explanation gap 和 visual gap。
- 如果某个角色只能生成 `explanation_only_label`，视觉层必须知道它不是 verified geometry object，不能画成真实点。

边界：

- 不从自然语言答案里读数值。
- 不创建未验证点、线、坐标或关系。
- 缺角色时输出 explanation/visual gap，不生成假话或假图。

## Design Model

`VisualStepIR` 拆成四层：

```text
VisualStepIR
  = GeometryContext
  + SceneState
  + InteractionSpec
  + TimelineSpec
```

### GeometryContext

`GeometryContext` 描述当前 VisualStep 继承哪个坐标系、绘图区间和全局参数环境。它对应现有 `geometry-spec.json` 顶层字段以及 step 级 `domain` override。

示例：

```json
{
  "geometry_context": {
    "coordinate_system": "cartesian_2d",
    "domain": {
      "minX": -1.6,
      "maxX": 6.0,
      "minY": -4.2,
      "maxY": 2.2
    },
    "domain_override": null,
    "moving_param": "a",
    "expression_env_handles": [
      "symbol:problem:a",
      "symbol:problem:b"
    ],
    "panels": []
  }
}
```

字段语义：

- `coordinate_system`：首版固定为 `cartesian_2d`。
- `domain`：默认可视范围，来自全局 `geometry-spec` 或 section-level projection。
- `domain_override`：当前 step 需要局部放大/裁切时使用，对应现有 step 级 domain。
- `moving_param`：当前页面全局 slider 使用的参数；没有全局动参时为 `null`。
- `expression_env_handles`：当前图形表达式可用的符号环境，必须来自 ProblemIR 或 runtime facts。
- `panels`：多面板场景的嵌套 context，每个 panel 可以拥有自己的 origin、axes、domain 和 visible layers。

`geometry_context` 支持层级继承：`global -> section -> step -> panel`。普通 VisualStep 继承全局 context；只有需要局部放大、换范围、切换动参表达式环境或多面板展示时才写 override。

### SceneState

`SceneState` 描述当前讲解步骤在已有图形状态上的增量变化：新增什么、强调什么、弱化什么、隐藏什么。

它不是完整 scene snapshot。现有前端管线已经是增量式的：

- `step-decorations.layers` 表示全局或分段共享对象。
- `step-decorations.steps[stepId].add` 表示当前步骤新增对象。
- `hideLayers` 表示当前步骤隐藏哪些共享层。
- 点控件、局部 override 等也是在当前步骤上叠加。

所以 VisualStepIR 的 `scene` 应表达 diff，而不是重复写出所有可见对象。最终可见图形由 compiler 派生：

```text
resolved_scene(step)
  = global layers
  + inherited section layers
  + scene.add
  + scene.state_overrides
  - scene.hide
```

推荐结构：

```json
{
  "id": "visual_step_6",
  "lesson_step_id": "step_6",
  "scope_id": "i_2",
  "scene": {
    "inherits_from": "section:i",
    "add": [
      { "handle": "answer:i_2.E", "component": "Point", "state": "result" },
      { "handle": "segment:i_2:BE", "component": "Segment", "state": "constructed" }
    ],
    "state_overrides": [
      { "handle": "point:problem:B", "state": "highlight" },
      { "handle": "fact:i:parabola_expression", "state": "muted" }
    ],
    "hide": [
      "fact:i:unused_auxiliary_line"
    ],
    "focus": {
      "primary": ["answer:i_2.E"],
      "dim": ["point:problem:A", "point:problem:C"]
    },
    "annotations": [
      {
        "type": "label",
        "target": "answer:i_2.E",
        "text_source": "lesson_step.box",
        "index": 0
      },
      {
        "type": "formula",
        "target": "segment:i_2:BE",
        "text": "BE"
      }
    ]
  }
}
```

字段语义：

- `inherits_from`：引用可复用基础状态，例如 `global`、`section:i`、`section:ii`。这是语义 layer ref，compiler 通过 layer registry 映射到现有 `step-decorations.layers` key，例如 `partI`、`partII`。
- `add`：当前步骤新增的可渲染对象。对应现有 `steps[stepId].add`。
- `state_overrides`：已存在对象在当前步骤切换教学状态，例如从 `visible` 变成 `highlight` 或 `muted`。
- `hide`：当前步骤隐藏的对象或层。对应现有 `hideLayers` 以及未来更细粒度的对象隐藏。
- `focus`：教学注意力语义，compiler 可把它翻译成强调、弱化、镜头裁切或标签优先级。
- `annotations`：当前步骤新增的标签、角标、距离标注、公式角标等。

Annotation 文案来源必须显式声明：

- `text_source="lesson_step.box"`：从对应 LessonStep 的 `box` 中提取文本，保证图上结果标签和讲解结论一致。
- `text_source="lesson_step.derive"`：从讲解推导行提取文本，适合复用公式过程。
- `text`：显式视觉文本，只用于 `box/derive` 中没有但图上需要的短标注，例如等长标记、路径名、辅助线名。

LLM 可以建议 annotation 文案，但 validator 必须拒绝与 `lesson_step.box` 冲突的结果标签。

这种设计更接近 React 的 derived state：每个 VisualStep 只声明相对 base scene 的 props/diff，完整画面由 renderer 根据继承链计算。

`component` 不是另起一套渲染类型。VisualStepIR 的 component 必须来自 `ComponentTypeSpec` registry，并且能编译到现有 `step-decorations` 的低层 type。

### ComponentTypeSpec

现有 `step-decorations.json` 已有一组稳定低层 type，例如：

- `point`
- `segment`
- `coloredLine`
- `dashedLine`
- `coordinateLabel`
- `parabola`
- `angleArc`
- `grid`
- `polygon`
- `ray`

VisualStepIR 可以使用更语义化的 component，但每个 component 都必须声明落地方式：

```python
@dataclass(frozen=True)
class ComponentTypeSpec:
    visual_type: str
    compiles_to: tuple[str, ...]
    required_roles: tuple[str, ...]
    optional_roles: tuple[str, ...] = ()
    children: tuple[dict[str, Any], ...] = ()
```

示例：

```python
ComponentTypeSpec(
    visual_type="Point",
    compiles_to=("point",),
    required_roles=("point",)
)

# V1 flat fallback. V1 registry uses this form when recursive children
# compilation has not been implemented yet.
ComponentTypeSpec(
    visual_type="DistanceMarker",
    compiles_to=("segment", "coordinateLabel"),
    required_roles=("from", "to"),
    optional_roles=("label",)
)

ComponentTypeSpec(
    visual_type="AuxiliaryConstruction",
    compiles_to=("point", "dashedLine"),
    required_roles=("target",),
    optional_roles=("from", "to", "label")
)

ComponentTypeSpec(
    visual_type="PathTransform",
    compiles_to=("coloredLine", "segment", "coordinateLabel"),
    required_roles=("from_path", "to_path"),
    optional_roles=("replacement_segment", "label")
)

# Future composition form. Do not register this together with the V1 flat
# fallback above; the registry must contain exactly one spec per visual_type.
ComponentTypeSpec(
    visual_type="DistanceMarker",
    compiles_to=(),
    required_roles=("from", "to"),
    optional_roles=("label",),
    children=(
        {
            "component": "Segment",
            "role_mapping": {"from": "from", "to": "to"},
            "state": "inherit"
        },
        {
            "component": "Label",
            "role_mapping": {"target": "midpoint(from, to)"},
            "text_role": "label"
        }
    )
)

ComponentTypeSpec(
    visual_type="VisualGap",
    compiles_to=("dashedLine", "coordinateLabel"),
    required_roles=("expected_role",),
    optional_roles=("reason",)
)
```

设计约束：

- `visual_type` 可以比低层 type 更接近教学语义。
- `compiles_to` 必须只引用已存在或明确新增的 `step-decorations` type。
- `children` 用于组合已有 visual component；如果存在 children，compiler 递归展开组件树。
- 新增抽象 component 时，必须同时补 `ComponentTypeSpec` 和 compiler 映射。
- 同一个 `visual_type` 在 registry 中只能注册一个 spec。`DistanceMarker` 的 flat fallback 和 composition form 是阶段性替代关系，不是并存关系。
- validator 根据 `ComponentTypeSpec.required_roles` 检查 role 是否绑定完整。
- LLM 不能发明 component；只能使用 payload 中暴露的 component registry。
- `VisualGap` 是验证失败时的 fallback UI，只能展示缺失提示，不能代替真实几何对象。

`state` 使用教学状态，而不是颜色：

- `visible`
- `muted`
- `highlight`
- `emphasized`
- `constructed`
- `result`
- `moving`
- `hidden`

具体颜色、线宽、透明度由前端 design system 和 compiler 决定。

### InteractionSpec

当前页面已经支持交互组件，`VisualStepIR` 不重新发明 slider，而是把现有能力抽象成统一的 interaction spec。

现有组件：

- main parameter slider：来自 `lesson-data.policies[stepId].movable/range/step`，控制 `geometry-spec.movingParam`。
- local point controls：来自 `lesson-data.steps[].localControls` + `step-decorations.steps[stepId].pointOverrides`。
- linked controls：多个可见控件共享同一个变量，保持动点约束。

`VisualStepIR` 中可表达为：

```json
{
  "interactions": [
    {
      "id": "move_M_on_BC",
      "component": "LocalSlider",
      "parameter": "u",
      "domain": {
        "type": "unit_interval",
        "min": 0,
        "max": 1,
        "step": 0.01
      },
      "parameterized_points": {
        "point:ii:M": {
          "source": "method_output",
          "producer_step_id": "reduce_ii_equal_length_ray_path",
          "method_id": "equal_length_ray_point",
          "output_role": "segment_moving_point"
        },
        "point:ii:N": {
          "source": "constraint",
          "constraint_handle": "fact:ii:equal_length_condition",
          "producer_step_id": "reduce_ii_equal_length_ray_path",
          "method_id": "equal_length_ray_point",
          "output_role": "ray_moving_point"
        }
      },
      "linked_objects": [
        "point:ii:N",
        "segment:ii:OM",
        "segment:ii:BN"
      ],
      "display": {
        "label": "拖动 M，观察 N 和路径 OM+BN 的变化"
      }
    }
  ]
}
```

`domain` 只描述 slider 变量的取值范围，不负责生成点坐标公式。前端 `pointOverrides` 需要的参数化表达式必须由 compiler 从 successful runtime artifacts 中读取，例如 method 输出中的 `M(u)`、`N(u)` 坐标表达式。

`parameterized_points` 声明“这个参数控制哪些点，以及这些点的参数化坐标从哪里来”：

- `source="method_output"`：从某个 accepted method/recipe invocation 的输出 payload 读取参数化坐标。
- `source="constraint"`：从已验证约束和对应 invocation 的结构化输出读取联动点坐标。
- `source="runtime_fact"`：从 `fact:*:<point>_parametric_coordinate` 这类 runtime fact 读取。

Visual spec 和 LLM 都不能手写 `["4*u", "3*u-3"]` 这类公式；公式只来自 method 执行结果、runtime fact 或受验证的约束输出。这样 slider 看到的动点轨迹一定和 solver 的计算一致。

#### ParametricExpressionResolver

`InteractionSpec` 到现有 `pointOverrides` 的核心转换由 `ParametricExpressionResolver` 完成：

```text
parameterized_points["point:ii:M"]
  -> locate source invocation / runtime fact / constraint output
  -> extract SymPy point coordinate expressions
  -> normalize parameter symbol to interaction.parameter
  -> print JavaScript-safe expression strings
  -> pointOverrides["M"] = ["4*u", "3*u-3"]
```

Resolver 输入：

- `parameterized_points` 的 source 描述。
- `RuntimeSuccessArtifacts.execution` 中的 invocation trace / method outputs。
- `ExplanationSnapshot.fact_index` 中的 typed facts。
- `interaction.parameter` 和 `domain`。

Resolver 输出：

- `pointOverrides` 需要的二维 JS 表达式字符串。
- 每个 point override 的 source provenance，用于 debug。

实现要求：

- SymPy 表达式必须通过统一 printer 转换为前端可求值字符串，例如 `sympy.printing.javascript` 或仓库已有 JS expression printer。
- 参数名必须和 `interaction.parameter` 一致；如果 method 输出使用内部参数，需要显式重命名。
- 多参数表达式不能静默降级成单 slider；必须报 validation error 或要求更明确的 interaction spec。
- resolver 不能从自然语言 `reason/strategy` 中解析公式。

compiler 负责把它落到现有 JSON：

```text
InteractionSpec(component=MainSlider)
  -> lesson-data.policies[stepId].movable/range/step

InteractionSpec(component=LocalSlider)
  -> lesson-data.steps[].localControls
  -> step-decorations.steps[stepId].pointOverrides

InteractionSpec(component=LinkedControls)
  -> localControls.controls[] 使用同一个 var，不同 label/scale
```

未来交互组件可扩展：

- `DragPoint`
- `Toggle`
- `StepPlayer`
- `ParameterStepper`
- `CandidateSelector`
- `RevealButton`
- `CompareMode`

它们都遵循同一原则：组件只控制已验证对象或局部变量，不新增数学事实。

### TimelineSpec

动画和交互分开：

- `interactions[]` 是学生控制。
- `timeline.on_enter.frames[]` 是系统演示。
- `timeline.mode` 定义两者的触发关系。

V1 可以不实现动画，但 schema 预留：

```json
{
  "timeline": {
    "mode": "auto_then_interactive",
    "on_enter": {
      "frames": [
        {
          "id": "show_original_path",
          "actions": [
            { "type": "show", "targets": ["segment:ii:OM", "segment:ii:BN"] }
          ]
        },
        {
          "id": "construct_auxiliary_point",
          "actions": [
            { "type": "construct", "targets": ["point:ii:G", "segment:ii:MG"] }
          ]
        },
        {
          "id": "show_distance_replacement",
          "actions": [
            { "type": "highlight", "targets": ["segment:ii:BN", "segment:ii:MG"] },
            { "type": "annotate", "text": "BN = MG" }
          ]
        }
      ]
    },
    "on_complete": {
      "enable_interactions": ["move_M_on_BC"]
    },
    "on_exit": {
      "cleanup": "keep_final_state"
    }
  }
}
```

前端可以把 frames 渲染成自动播放、逐帧按钮，或绑定到讲解 step 的滚动进度。

Timeline 与 interaction 的首版互斥语义：

- `mode="none"`：没有演示，interactions 可立即启用。
- `mode="auto_then_interactive"`：进入 step 后先播放 timeline，播放完成后按 `on_complete.enable_interactions` 启用交互。
- `mode="manual_then_interactive"`：学生逐帧点击演示，完成后启用交互。
- timeline 播放期间，相关 interactions 默认 disabled，避免 slider 与系统演示同时改同一对象。
- 如果某个 interaction 不影响 timeline targets，可以通过 `available_during_timeline=true` 显式放行；默认不放行。

这保证教学顺序稳定：先看构造/变换演示，再让学生拖动观察。

`on_exit.cleanup` 首版支持：

- `keep_final_state`：离开 step 时保留 timeline 最终帧状态，默认值。
- `revert_to_base`：离开 step 时恢复为 scene base state。
- `transition_to_next`：离开 step 时交给 step transition reconciliation 生成平滑过渡。

### Step Transition Model

每个 VisualStep 都可以解析成 `resolved_scene`。相邻步骤切换时，renderer 可以用 canonical handle 做 reconciliation key：

```text
objects_to_add     = handles(next) - handles(current)
objects_to_remove  = handles(current) - handles(next)
objects_to_update  = same handle, changed state/component props
objects_unchanged  = same handle, same state/component props
```

V1 可以直接全量替换 SVG；该模型不要求立即实现动画。但 schema 从一开始就要求 stable handle，未来才能把全量替换升级为最小 diff transition。

## Relationship With LessonIR

V1 强制一一对应：

```text
LessonStep.id == VisualStep.lesson_step_id
LessonStep.teaching_substep_id == VisualStep.teaching_substep_id  # 当 Lesson step 来自 recipe substep 时
```

对于普通 method step，VisualStep 直接使用对应 `MethodVisualSpec`。对于 recipe 拆分出的 Lesson step，VisualStep 使用对应 `TeachingSubstepSpec.visual_*_templates`，而不是 recipe 整体模板。

好处：

- 页面左右同步简单。
- validator 简单。
- LLM 不重新做讲解分组。
- debug 明确：某个讲解 step 画错，只看对应 visual step 和 substep spec。

如果一个 Lesson step 需要多个画面变化，不新增多个 VisualStep，而是在该 VisualStep 内部使用 `timeline.on_enter.frames[]`。

## LLM Role

LLM 不直接生成低层 `geometry-spec` / `step-decorations`。

推荐流程：

1. 代码根据 `LessonIR + ExplanationSnapshot + method/recipe visual spec + BaseRoleBinder + VisualProjection` 生成 `VisualStepIR draft`。
2. LLM 只优化：
  - `intent`
  - `focus.primary/dim`
  - annotation 文案
  - 是否需要 frames
  - 已有交互组件的教学说明
3. validator 校验：

- `lesson_step_id` 必须存在。
- 所有 handles 必须来自 ProblemIR、StepIntent、runtime facts 或 LessonIR source。
- `geometry_context` 只能引用已投影出的坐标系、domain 和符号环境。
- component 必须支持 handle 对应对象类型。
- interaction 只能控制已验证的动点或局部 override 变量。
- timeline 与 interaction 的 targets 冲突时，必须声明互斥或完成后启用关系。
- LLM 不得新增点、线、坐标、答案或未验证关系。

## Existing Slider Components

当前已有三类交互需要被 VisualStepIR 正式承接。

### Main Parameter Slider

适用于题目本身的全局动参，例如 `t / m`。

现有落点：

- `lesson-data.policies[stepId].movable`
- `lesson-data.policies[stepId].range`
- `lesson-data.policies[stepId].step`
- `geometry-spec.movingParam`

VisualStepIR 对应：

```json
{
  "component": "MainSlider",
  "parameter": "m",
  "range": [-1, 0],
  "controls": ["point:i_2:E"],
  "purpose": "观察 E 在抛物线上移动时的几何关系"
}
```

规则：

- 用于题设真实动点/动参。
- 不用于要求求解的系数未知量，例如最终要求 `a`、`b`、`c` 时，不把它们做成 main slider。

### Local Point Controls

适用于某一步内部的局部观察，例如拖动辅助点、最短路径动点。

现有落点：

- `lesson-data.steps[].localControls`
- `step-decorations.steps[stepId].pointOverrides`

VisualStepIR 对应：

```json
{
  "component": "LocalSlider",
  "parameter": "u",
  "domain": { "type": "unit_interval", "min": 0, "max": 1 },
  "parameterized_points": {
    "point:ii:M": {
      "source": "runtime_fact",
      "fact_handle": "fact:ii:M_parametric_coordinate"
    },
    "point:ii:N": {
      "source": "method_output",
      "producer_step_id": "reduce_ii_equal_length_ray_path",
      "method_id": "equal_length_ray_point",
      "output_role": "ray_moving_point"
    }
  },
  "linked_objects": ["point:ii:N", "segment:ii:OM", "segment:ii:BN"]
}
```

规则：

- 只影响当前 visual step。
- 不改变 `geometry-spec.movingParam`。
- `parameterized_points` 必须能回溯到 runtime fact、method output 或已验证约束；不能由 LLM 手写坐标表达式。
- 适合局部证明、构造辅助点、观察最短状态。

### Linked Controls

适用于多个点受同一个数学变量约束。

VisualStepIR 对应：

```json
{
  "component": "LinkedControls",
  "parameter": "s",
  "domain": { "type": "unit_interval", "min": 0, "max": 1 },
  "parameterized_points": {
    "point:ii:E": {
      "source": "runtime_fact",
      "fact_handle": "fact:ii:E_parametric_coordinate",
      "label": "动点 E"
    },
    "point:ii:G": {
      "source": "runtime_fact",
      "fact_handle": "fact:ii:G_parametric_coordinate",
      "label": "动点 G"
    }
  },
  "constraint_note": "两个控件共享同一个变量，保持题设约束不变"
}
```

compiler 落到现有 `localControls.controls[]` 中共享同一个 `var`，再把每个点的参数化坐标编译到 `pointOverrides`。

## Implementation Phases

### Phase Boundaries

- **VS0 验证表达能力**：`reverse_compile -> VisualStepIR -> forward_compile` 只用于证明 schema 能表达现有手写产物。VS0 的 `forward_compile` 是 round-trip 验证工具，不是产品生成路径。
- **VS1 验证生成能力**：产品路径从这里开始，即 `LessonIR + ExplanationSnapshot + visual specs -> VisualStepIR -> forward_compile -> lesson page compile`。
- **VS2/VS3/VS4 是 schema 扩展**：interaction、timeline 和更多组件都必须保持向后兼容。老 VisualStepIR 不含新字段时仍应通过 validator。

跨阶段回归策略：

- VS1 引入后，VS0 golden test 必须继续通过。
- VS2 引入后，VS0/VS1 的所有测试必须继续通过；interaction 是 optional 字段。
- VS3 引入后，VS0/VS1/VS2 的所有测试必须继续通过；timeline 是 optional 字段。
- 每个阶段的 golden test 加入 CI，后续阶段不允许破坏。
- 新阶段引入 schema 扩展时，必须补一个“旧 IR 仍通过 validator”的兼容测试。

### Error Handling Principles

1. **Validation-first**
  每个 builder/compiler 在生成前做 pre-check，避免生成 invalid IR 后才靠 validator 兜底。
2. **Fail with context**
  validation error 必须包含具体的 `visual_step_id`、`lesson_step_id`、`handle`、`role name` 或 `component`，便于定位是哪个 method/recipe visual spec 出了问题。
3. **Graceful degradation**
  非关键缺失，例如 optional annotation、optional label，可以生成 warning 或 `VisualGap`；关键缺失，例如 `lesson_step_id` 不存在、required role 缺失且不能 fallback、component 未注册，必须 hard fail。
4. **Every error path has a test**
  builder、compiler、resolver、validator 的每种稳定 error code 至少有一个测试触发。
5. **No silent visual facts**
  任何 fallback 都不能新增点、线、坐标、答案或未验证关系。`VisualGap` 只能展示缺失提示。

### VS0：Schema / Validator / Reverse Compile

目标：先证明 VisualStepIR 能覆盖现有手写页面，而不是先写正向生成器。

输入：

- 现有和平一模 lesson 页面产物。
- `geometry-spec.json`
- `step-decorations.json`
- `lesson-data.json` 中已有 slider、local controls、policies。

产出：

- `VisualStepIR` schema。
- `VisualStepIRValidator`。
- `reverse_compile(geometry_spec, step_decorations, lesson_data) -> VisualStepIR`。
- `forward_compile(VisualStepIR) -> geometry-spec.json + step-decorations.json + lesson-data interaction subset`。
- layer registry：定义 `global / section:i / section:ii` 等 semantic layer ref 到现有 `step-decorations.layers` key 的映射，例如 `section:i -> partI`。

VS0 重点验证：

- `SceneState` 的 `inherits_from / add / state_overrides / hide` 能表达现有 layers、step add、hideLayers。
- `inherits_from` 的 semantic layer ref 能稳定映射到现有 `partI / partII / global` 等 layer key。
- `ComponentTypeSpec` 能覆盖现有低层 type：`point / segment / coloredLine / dashedLine / coordinateLabel / parabola / angleArc / grid / polygon / ray`。
- `ComponentTypeSpec.children` 能表达至少一个组合组件，例如 `DistanceMarker = Segment + Label`。
- `GeometryContext` 能表达现有全局 domain、step domain override、movingParam。
- `InteractionSpec` 能表达现有 main slider、local controls、pointOverrides。
- 低层布局参数不能丢，例如 `coordinateLabel` 的 `dx/dy`、segment 的 `offsetPx`、`angleArc` 的 `radius/labelRadius`。

测试计划：

**单元测试**

- VisualStepIR schema：
  - 合法 IR 通过 validator。
  - 缺少 `lesson_step_id` 拒绝。
  - `scene.add` 引用不存在的 `ComponentTypeSpec` 拒绝。
  - `state_overrides` 使用不在枚举中的 state 拒绝。
  - `annotations.text_source="lesson_step.box"` 引用不存在的 box index 拒绝。
  - `VisualGap` 只能携带 `expected_role / reason`，不能携带真实坐标或伪造 handle。
- `ComponentTypeSpec` registry：
  - 每个现有低层 type，例如 `point / segment / coloredLine / dashedLine / coordinateLabel / parabola / angleArc / grid / polygon / ray`，都有可达 component spec。
  - `DistanceMarker` V1 flat fallback 能编译到 `segment + coordinateLabel`。
  - future composition 版本展开后产出 `Segment + Label`。
  - `required_roles` 缺失时报 validation error，并指明缺哪个 role。
  - 重复注册同一 `visual_type` 报错，特别是不能同时注册两个 `DistanceMarker`。
- layer registry：
  - `section:i -> partI`、`section:ii -> partII` 可配置，不硬编码在 compiler 分支里。
  - 引用不存在的 semantic layer ref 报 validation error。
  - `global` 是默认层，所有 step 可继承。

**集成测试**

- `reverse_compile`：
  - 输入和平一模真实 `geometry-spec.json + step-decorations.json + lesson-data.json`。
  - 输出 VisualStepIR 通过 validator。
  - VisualStep 数量等于 `step-decorations.steps` 数量。
  - 每个 VisualStep 的 `scene.add` 对象数不少于对应 `step-decorations.steps[stepId].add` 的对象数，除非对象被合并为明确的 composite component。
  - interaction 数量等于 `lesson-data` 中 localControls 加 policies movable 的数量。
- `forward_compile`：
  - 输入 `reverse_compile` 的 VisualStepIR。
  - 输出三个 JSON 文件。
  - `step-decorations` 与原始版本在关键结构上等价。

**验收条件**

- `reverse_compile(heping_yimo) -> VisualStepIR` 通过 validator。
- `forward_compile(reverse_compile(heping_yimo))` 生成的 `step-decorations.json` 与原始手写版本在语义上等价。
- round-trip golden test 允许字段顺序、默认值展开、稳定 id 命名差异，但不允许丢对象、丢 label、丢 interaction 或改变可见性。
- 对无法抽象的低层字段，必须新增 `ComponentTypeSpec` metadata 或明确标记为 renderer-only escape hatch。

**边界测试**

- `coordinateLabel.dx/dy`、`segment.offsetPx`、`angleArc.radius/labelRadius` 等低层布局参数通过 component metadata 或 renderer-only escape hatch 保留，round-trip 后不丢失。

### VS1：静态 VisualStepIR

目标：跑通 `LessonIR -> VisualStepIR`。

- 基于 VS0 验证过的 schema 和 validator。
- 一个 Lesson step 生成一个 Visual step。
- 支持 `geometry_context` 继承全局坐标系、domain、moving param 和 expression env。
- 支持 `scene.inherits_from / add / state_overrides / hide / focus / annotations`。
- 支持首批 `ComponentTypeSpec`：点、线段、直线、射线、抛物线、角标、等长标记、结果点。
- 编译出完整 `geometry-spec.json / step-decorations.json / lesson-data.json`，并进一步编译成页面。

测试计划：

**单元测试**

- `MethodVisualSpec -> VisualStep`：
  - 输入 `distance_between_points` 的 visual spec 与 role bindings：`p1=point:i:A`、`p2=point:i:B`。
  - 生成的 `scene.add` 包含两个 `Point(highlight)`、一个 `Segment(emphasized)`、一个 `DistanceMarker`。
  - 所有 handle 都来自 bindings。
- `TeachingSubstepSpec -> VisualStep`：
  - 输入 `equal_length_ray_path_reduction.path_reduction` substep 与完整 bindings。
  - 生成的 VisualStep 只包含 `path_reduction` 的 visual templates，不包含 `minimum_by_segment` 的对象。
- `VisualGap` fallback：
  - Method visual spec 需要 `p1/p2`，bindings 只给 `p1`。
  - `scene.add` 为缺失的 `p2` 生成 `VisualGap`，reason 指明 `p2`。
- `BaseRoleBinder` 共享一致性：
  - 同一组 bindings 分别走 `ExplanationProjection` 和 `VisualProjection`。
  - 二者引用的 canonical handles 完全一致。
- annotation text source：
  - `text_source="lesson_step.box"` 自动从 `LessonStep.box[index]` 提取文本。
  - text source 与 box 结果冲突时 validator 拒绝。
  - 显式 `text` 只允许用于 box/derive 中没有的短视觉标注。
- `GeometryContext`：
  - 普通 step 继承全局 context，不写 `domain_override` 时与 global 一致。
  - step 写 `domain_override` 时只覆盖 domain，其他字段继续继承。
  - `expression_env_handles` 引用不存在 symbol 时 validator 拒绝。

**集成测试**

- 输入和平一模 `LessonIR + ExplanationSnapshot + visual specs`，生成完整 VisualStepIR。
- VisualStep 数量等于 LessonStep 数量。
- `forward_compile` 输出的 `step-decorations` 通过现有 validator。
- `forward_compile` 输出完整三个 JSON 文件：`geometry-spec.json`、`step-decorations.json`、`lesson-data.json`。
- 使用现有页面编译工具把 `LessonIR + VisualStepIR compiled JSON` 编译成 lesson 页面。
- 页面编译产物通过现有 HTML/lesson renderer validator；如有 headless render 测试，至少验证页面不白屏且每个 Lesson step 可定位到对应 VisualStep。
- 与 VS0 `reverse_compile` 的 golden VisualStepIR 结构对齐：相同 LessonStep 的关键 add/focus handle 集合一致。
- scope 继承：
  - `section:i` 的 step 默认只能 add 当前 scope 或全局可见对象。
  - `section:ii` 的 step 不能引用 `section:i` 独有对象，除非通过显式跨 scope fact 或 valid scope 暴露。

**验收条件**

- VisualStepIR 所有 handle 都存在。
- VisualStepIR 的 `geometry_context` 可映射到现有 `geometry-spec` 顶层字段或 step 级 domain override。
- VisualStepIR 所有 component 都在 `ComponentTypeSpec` registry 中，且可编译到现有 `step-decorations` type。
- 每个 Lesson step 都有对应 Visual step。
- role 缺失时生成 `VisualGap`，不生成假对象。
- 编译后的三个 JSON 文件通过现有 validator，并能编译成页面。

### VS2：接入现有 Slider / Local Controls

目标：VisualStepIR 能表达已有交互组件。

- `MainSlider` 编译到 `lesson-data.policies`。
- `LocalSlider` 编译到 `localControls + pointOverrides`。
- `LinkedControls` 编译到共享变量的 local controls。
- `ParametricExpressionResolver` 从 runtime artifacts / runtime facts 提取 SymPy 参数化坐标，并转换为 `pointOverrides` 所需 JS 表达式字符串。

测试计划：

**ParametricExpressionResolver 单元测试**

- 基本转换：
  - `4*u -> "4*u"`。
  - `3*u - 3 -> "3*u-3"` 或等价 JS 表达式。
  - `u**2 -> "Math.pow(u, 2)"` 或项目约定的幂表达式。
  - `sqrt(2)*u -> "Math.sqrt(2)*u"`。
  - `Rational(1, 3)*u -> "u/3"` 或等价 JS 表达式。
- 参数名统一：
  - method 输出使用内部参数 `t`，interaction parameter 是 `u` 时，输出表达式必须统一为 `u`。
  - method 输出含多个自由参数时报 validation error。
- source 查找：
  - `source="method_output"` 从 invocation trace 中找到对应 method 输出。
  - `source="runtime_fact"` 从 fact index 找到 `parametric_coordinate` fact。
  - `source="constraint"` 从已验证约束输出提取联动坐标。
  - `producer_step_id` 不存在时报明确错误。
  - method output 中没有坐标表达式时报明确错误。
- provenance：
  - 每个 pointOverride 都携带 source provenance。
  - provenance 包含 source type、step_id、method_id、原始 SymPy 表达式。

**Interaction compiler 集成测试**

- `MainSlider -> lesson-data.policies`：
  - 输入 `parameter="m"`、`range=[-1, 0]`。
  - 输出 `policies[stepId].movable=true`，range 与 step 正确。
- `LocalSlider -> localControls + pointOverrides`：
  - 输入一个参数 `u` 和两个 `parameterized_points`。
  - 输出一个 local control，`var="u"`。
  - 输出两个 point override，表达式来自 resolver。
- `LinkedControls -> shared var`：
  - 输入参数 `s` 和两个点。
  - 输出的 controls 共享同一个 `var="s"`。
- 和平一模 local slider golden：
  - `forward_compile` 的 localControls 与 pointOverrides 与手写版本行为等价。
  - 表达式允许字符串不同但符号等价。
- 页面闭环：
  - `VisualStepIR -> forward_compile -> geometry-spec/step-decorations/lesson-data -> lesson page compile`。
  - 页面中 main slider、local controls、linked controls 可被 renderer 识别。
  - headless render 或现有页面 validator 至少确认 slider 控件存在、pointOverrides 生效、切换 step 不报错。

**验收条件**

- 不手写 HTML/JS。
- 和现有 `interactive-lesson-components.md` 行为一致。
- 和平一模双动点路径观察能表达为 local/linked interaction。
- `pointOverrides` 的公式来源有 provenance，且公式与 method 执行结果一致。
- 多参数、缺 source、参数名无法统一时 validator 明确失败，不生成错误 slider。

### VS3：Timeline / Animation

目标：在 VisualStep 内表达演示顺序。

- 支持 `timeline.on_enter.frames[]`。
- 支持 `timeline.mode` 和 `on_complete.enable_interactions`。
- 支持 `timeline.on_exit.cleanup`。
- 每个 frame 是对象状态 diff 或教学动作。
- 前端可以选择自动播放或逐帧播放。

测试计划：

- timeline mode：
  - `mode="none"` 时 interactions 立即可用，无 frames 播放。
  - `mode="auto_then_interactive"` 时 frames 播放完成后启用 interactions。
  - `mode="manual_then_interactive"` 时需要逐帧确认后启用 interactions。
- `on_complete.enable_interactions`：
  - 引用不存在的 interaction id 时 validator 拒绝。
  - timeline targets 与 interaction targets 重叠但无 enable/互斥关系时 validator 警告。
- `on_exit.cleanup`：
  - `keep_final_state`：下一步 inherits 可以看到 timeline 最终帧状态。
  - `revert_to_base`：下一步看到 timeline 之前的 base scene。
  - `transition_to_next`：产出 transition diff，包括对象增删改集合。
- Timeline 与 SceneState 一致性：
  - frame targets 必须都在 `scene.add` 或 inherited scene 中。
  - `construct` action 产出的对象必须在 `scene.add` 中有声明。
  - timeline 不能引入 scene 中未声明的新对象。
- timeline-free compatibility：
  - `timeline=null` 或 `{"mode": "none"}` 时，VS1/VS2 golden 仍通过。
- 页面闭环：
  - `VisualStepIR(timeline) -> forward_compile -> compiled JSON -> lesson page compile`。
  - timeline-free 页面和 timeline-enabled 页面都能通过现有 renderer validator。
  - 如果前端暂未实现 timeline UI，compiler 必须降级为静态最终态或 no-op timeline，不影响页面生成。

**验收条件**

- 无 timeline 的 VisualStep 仍可静态渲染。
- timeline 不改变数学事实，只改变显示状态。
- timeline 播放时默认暂停会改动同一对象的 interactions；播放完成后再启用指定交互。
- 相邻 VisualStep 的 `resolved_scene` 可以用 stable handle 计算 transition diff；V1 可退化为全量替换。
- 编译后的三个 JSON 文件可以生成页面；timeline 支持缺失时必须可安全降级，不阻断页面。

### VS4：更多交互组件

按真实题目需求逐步增加：

- `CandidateSelector`
- `ToggleConstruction`
- `DragPoint`
- `ComparePaths`
- `ParameterStepper`
- `RevealButton`

每个组件都必须先有 declarative schema 和 validator，再接前端渲染。

测试原则：

- `ComponentTypeSpec` 注册测试：
  - `visual_type` 唯一。
  - `required_roles / optional_roles` 完整。
  - `compiles_to` 或 `children` 的目标 component/type 存在。
- Schema validation 测试：
  - 合法 spec 通过。
  - 缺少 required field 拒绝。
  - 引用不存在 handle 拒绝。
- 真实题目 golden test：
  - 至少用一道真实 solver run 数据生成包含该组件的 VisualStepIR。
  - `forward_compile` 输出可以被现有前端 renderer 消费。
- 兼容性测试：
  - 新组件不能破坏 VS0-VS3 已有 golden test。
  - 新组件 schema 扩展必须证明旧 IR 仍可通过 validator。

## Assumptions

- `VisualStepIR` 不直接生成 React 组件代码；它只生成组件 props-like 数据。
- 前端 renderer/React components 是 VisualStepIR 的消费者，不是 IR 的一部分。
- 现有 slider、local controls、linked controls 是当前能力，不是未来假设。
- V1 不做复杂动画；动画通过 `timeline.on_enter.frames[]` 和 transition model 预留。
- VisualStepIR 的分组跟随 LessonIR，不重新决策讲解粒度。
