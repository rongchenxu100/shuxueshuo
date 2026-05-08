---
name: geometry-lesson
description: Use this skill to turn a middle-school geometry problem into a compiled interactive lesson page. The agent writes teaching markdown and three declarative JSON specs; repository tools compile the HTML.
---

# Geometry Lesson

Use this skill when creating or updating a geometry comprehensive problem page in the `shuxueshuo` repository.

The core rule: HTML is a compiled artifact. Do not hand-write page HTML, SVG path logic, `toScreen`, `diagramMarkupFor`, `drawMini`, polygon clipping, step navigation, sliders, thumbnails, or page runtime JavaScript.

## Output Contract

Work in this order:

1. Create or update `internal/lesson-specs/<problem-id>/01_problem.md`.
2. Create or update `internal/lesson-specs/<problem-id>/02_solution.md`.
3. Create or update `internal/lesson-specs/<problem-id>/03_visual_steps.md`.
4. Create or update the compiled-page input JSON files:
  - `geometry-spec.json`
  - `step-decorations.json`
  - `lesson-data.json`
5. Run validation and compilation:

```bash
node tools/validate-geometry-spec.mjs internal/lesson-specs/<problem-id>/
node tools/build-lesson-page.mjs internal/lesson-specs/<problem-id>/
```

The final HTML path is controlled by `lesson-data.json.meta.outputPath`.

## Reference Files

Load only the references needed for the current task:

- Read `references/geometry-solving-principles.md` before writing `02_solution.md` or revising reasoning quality.
- Read `references/json-schema-guide.md` before writing any of the three JSON specs.
- Read `references/nankai-24-fewshot.md` when you need a compact example of the JSON shape and id alignment.
- Read `references/piecewise-area-trends.md` for area ranges, overlap-area extrema, moving-figure phase analysis, boundary thumbnails, or representative interval minis.
- Read the real schema files before finalizing JSON:
  - `internal/schemas/geometry-spec.schema.json`
  - `internal/schemas/step-decorations.schema.json`
  - `internal/schemas/lesson-data.schema.json`

Do not use skill references as JS/CSS implementation sources. Rendering behavior belongs to repository runtime files and the compiler.

## Step 1: `01_problem.md`

Extract and normalize:

- source metadata: year, district, exam name, question number, problem id
- full original problem text, preserving the exam wording
- known conditions
- geometric objects, fixed points, moving points, and parameters
- parameter ranges and endpoint inclusiveness
- sub-questions
- standard answers, if available

Use this shape:

```md
# 题目标准化

## 基本信息
- 题号：
- 来源：
- 题型：

## 题目原文

## 已知条件

## 几何对象

## 动态参数

## 小问列表

## 标准答案
```

## Step 2: `02_solution.md`

Write a student-friendly solution script for middle-school students.

Every step should include:

- title
- goal
- derivation lines using `∵` / `∴`
- current conclusion

Use this shape:

```md
# 解题过程

## 第（I）问

### Step 1
- 标题：
- 目标：
- 推导：
  - ∵ ...
  - ∴ ...
- 当前结论：
```

Quality requirements:

- Restart step numbering inside each sub-question.
- Each step should do one main thing.
- Step titles should use `方法 + 目标量`, such as `由直角三角形求 DG`.
- Reuse named points and earlier conclusions instead of re-deriving them.
- Keep endpoint inclusiveness identical across solution text, visual steps, JSON policies, answer chips, and final answers.

For detailed reasoning rules, use `references/geometry-solving-principles.md`.

## Step 3: `03_visual_steps.md`

Map every solution step to a diagram snapshot. The markdown is a planning layer for the JSON specs.

Prefer this shape:

```md
# 图形快照脚本

## 整题层
- 常驻：
- 统一规则：

## 第（I）问

### 子题层
- 常驻：
- 已得结论层：

### 阶段 A
- 阶段常驻：

#### Step 1
- 对应解题步骤：
- 推荐参数值：
- 当前高亮：
- 新出现辅助元素：
- 退场元素：
- 结论框：
- 缩略图：
```

Layering rules:

- Put whole-problem context in the global layer.
- Put sub-question context in a section layer.
- Put repeated local context in a phase layer.
- Put one-step helpers and highlights in the step layer.
- Put previously derived values in `lesson-data.steps[].box`, not as extra diagram text unless the value has spatial meaning in the current inference.

## Step 4: JSON Specs

Write the three JSON files in `internal/lesson-specs/<problem-id>/`.

### `geometry-spec.json`

Use this for geometric data only:

- `version`, `id`, `domain`
- `fixedPoints` and `movingPoints` as expression strings, such as `"3*S3"` or `"t/2"`
- `movingParam`
- `basePolygon`, `movingPolygon`
- `movingPolygons` when the folded piece changes shape by interval, such as a fold line first cutting a side and later cutting the top edge. Each entry must use the actual clipped folded piece for that interval, not a reflected extension of a later-stage polygon.
- `derivedIntersections` as two-line declarations, such as `{ "name": "E", "a": ["A", "C"], "b": ["M", "N"] }`
- `originalFigures` for problem-card source figures

Do not hand-derive intersection coordinates except optional `fallback` values for static original figures.

### `step-decorations.json`

Use this for visual decorations only:

- `layers.global.elements` for always-visible context.
- Conditional layers with `section`, `sectionNot`, or `stepStartsWith`.
- `steps[stepId].add` for only the current step's extra/highlighted elements.

Do not repeat parent-layer elements in child layers unless the child changes their role or presentation.

### `lesson-data.json`

Use this for page data only:

- `meta`: `id`, `outputPath`, `pageTitle`, `pageDescription`, `breadcrumbTitle`
- `problem.summary`
- `problem.lines`
- `ui.legend`, `sliderLabel`, `paramLabelPrefix`, `goToProblemMode`, `groupTitles`
- `steps`
- `policies`
- `stepLabels`

Hard constraints:

- `problem.lines` must be plain data: text lines, answer chip lines, heading lines, or original-figure groups.
- `ui.legend` must be `{ "colorVar": "...", "label": "..." }` items.
- Do not put HTML tags or style strings in any JSON text field.
- Every `lesson-data.steps[].id` must exist in `lesson-data.policies`, `lesson-data.stepLabels`, and `step-decorations.steps`.
- Every `problem.lines[].figures[].id` must match an id in `geometry-spec.originalFigures`.
- `lesson-data.meta.id` and `geometry-spec.id` must match.

For field details and common validation errors, use `references/json-schema-guide.md`. For exact allowed fields and types, use the real schema files in `internal/schemas/`.

## Validation And Compilation

Always run:

```bash
node tools/validate-geometry-spec.mjs internal/lesson-specs/<problem-id>/
```

Then compile:

```bash
node tools/build-lesson-page.mjs internal/lesson-specs/<problem-id>/
```

If validation or rendering fails, fix the JSON spec or the shared compiler/runtime. Do not patch a generated HTML page by hand.

## Final Review Checklist

- Original problem text is complete and source metadata is correct.
- Every solution step has a matching visual step.
- The three JSON files contain pure data and no HTML strings.
- Coordinates use one mathematical scale through the shared renderer.
- Intersections are declared through `derivedIntersections`.
- Step ids are aligned across `steps`, `policies`, `stepLabels`, and `step-decorations`.
- Original figure ids align between `lesson-data.problem.lines` and `geometry-spec.originalFigures`.
- Original figure point labels use object entries such as `{ "at": "A", "label": "A", "dx": 10, "dy": 26 }`; never use string arrays such as `["A", "B"]`.
- Same-point coordinate labels and point-name labels are not both shown in one snapshot; avoid duplicate labels such as two `B` or two `C` near the same vertex.
- Section layers and `when` labels are scoped tightly: no section layer leaks objects into unrelated steps, and no boundary-only label appears at a non-boundary parameter value.
- Trend/classification steps for area ranges contain no formula-specific helpers such as small triangles, heights, cut regions, or candidate-only points; those appear only in the later calculation step that uses them.
- Folding trend/classification steps use the true folded polygon for the current interval. If the fold line cuts different original sides in different intervals, use interval-specific moving polygons and verify thumbnails share that model.
- Extremum reasoning compares every included endpoint candidate that the trend step identifies; do not discard a candidate endpoint without a comparison.
- Boundary inclusiveness matches everywhere.
- Validation and compilation both pass.
