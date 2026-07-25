# 互动题目页模板说明

`interactive-problem-page.template.html` 是后续题目页生成的标准模板，目标是复用南开区一模 24 题已经验证过的页面形态。

## 页面形态

- 所有步骤直接竖直展开，学生通过下滑连续阅读。
- 桌面和平板端右侧显示 sticky 步骤目录。
- 手机端底部显示步骤 dock，点击后打开步骤目录抽屉。
- 每个步骤都是独立卡片，包含本步图形、本步推导、本步局部交互。
- 可移动参数只出现在对应步骤的图形下方，不使用全局滑块。
- 边界状态或分段状态用缩略图表示，桌面端显示 chip + 缩略图，手机端显示低矮横向缩略图。
- 模板不内联布局 CSS，统一引用 `site/assets/css/interactive-geometry-page.css`。

## 公共脚本（不要复制到题页）

模板和编译脚本负责按顺序引入公共脚本：

1. `site/assets/js/geometry-label-layout.js` — 点线标注避让。
2. `site/assets/js/interactive-lesson-ui.js` — 滑块策略小工具。
3. `site/assets/js/lesson-page-runtime.js` — 步骤导航、滑块、minis、题目折叠、IntersectionObserver。
4. `site/assets/js/geometry-engine.js` — 表达式求值、多边形裁剪、交点等无 DOM 工具。
5. `site/assets/js/geometry-lesson-from-spec.js` — 从 `geometry-spec.json` 和 `step-decorations.json` 创建 renderer。

新题不要内联复制 `renderStepNav`、`renderAllSteps`、`diagramMarkupFor`、`drawMini` 或任何确定性绘图逻辑。编译器会根据三份 JSON 自动生成 renderer glue，并调用 `LessonPageRuntime.init({ ... })`。

声明式几何规格示例见 `internal/lesson-specs/tj-2026-nankai-yimo-24/geometry-spec.json`，JSON Schema 见 `internal/schemas/geometry-spec.schema.json`。可用 `node tools/validate-geometry-spec.mjs <path>` 做结构 + 试算校验。

## 模板占位符

- `{{PAGE_TITLE}}`：浏览器标题。
- `{{PAGE_DESCRIPTION}}`：页面 meta 描述。
- `{{BREADCRUMB_TITLE}}`：顶部面包屑标题。
- `{{PROBLEM_SUMMARY}}`：折叠状态下的一行题目摘要。
- `{{PROBLEM_FULL_HTML}}`：完整题目 HTML，含必要答案 chip。
- `{{PROBLEM_KEY_POINTS_HTML}}`：可选的解题要点提示；没有数据时由编译器替换为空字符串。
- `{{STEPS_JSON}}`：步骤数组。
- `{{STEP_LABELS_JSON}}`：步骤短标签映射。
- `{{POLICIES_JSON}}`：每步交互策略映射。
- `{{GEOMETRY_SCRIPT}}`：由编译器生成的几何数据嵌入和 renderer glue。

## 样式边界

- 公共页面布局样式放在 `site/assets/css/interactive-geometry-page.css`。
- 新题页不要复制模板布局 CSS 到 HTML 内部。
- 只有当前题特有、无法公共化的极少数样式才允许写在题页内联 `<style>` 中。

## `STEPS_JSON` 约定

每个 step 至少包含：

```js
{
  id: "q2s3",
  section: "第（II）②问",
  title: "第3步：在 3＜t＜9/2 中由五边形面积求范围",
  t: 3.75,
  derive: [
    ["∵", "3＜t＜9/2 时，重叠部分为五边形"],
    ["∴", "..."]
  ],
  box: ["右上角结论框内容"],
  minis: [
    { "title": "t＝3", "caption": "重叠部分为三角形。", "t": 3 }
  ]
}
```

规则：

- `section` 使用题目小问，例如 `第（I）问`、`第（II）①问`、`第（II）②问`。
- `title` 的步号按每个小问重新编号，不按整题连续编号。
- `derive` 只写本步推导，不把下一个步骤的结论提前写入。
- `box` 只放当前步骤真正依赖的已得结论和本步结论。
- `minis` 用于边界状态、分段状态、代表状态，可点击联动本步滑块。

## `POLICIES_JSON` 约定

```js
{
  q2s3: {
    movable: true,
    range: [3.001, 4.499],
    step: 0.001,
    reason: "本步在五边形阶段观察最大值。"
  }
}
```

规则：

- 只有需要观察变化或公式适用区间的步骤才设为 `movable: true`。
- 范围必须与当前步骤的数学条件一致。
- 手机端会隐藏 `reason`，桌面端可显示简短说明。

## Renderer Glue 约定

题目数据只提供三份 JSON：

- `geometry-spec.json`
- `step-decorations.json`
- `lesson-data.json`

`tools/build-lesson-page.mjs` 会把它们编译进模板，并自动生成：

- `diagramMarkupFor(index, overrideT)`
- `drawMini(t)`
- `groupTitle(section)`
- `__AFTER_RENDER_ALL_STEPS__`

如果图形、缩略图、导航或滑块行为不正确，应修改 JSON、共享 renderer、runtime 或模板，不要手写题页级补丁。
