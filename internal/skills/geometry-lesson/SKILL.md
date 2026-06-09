---
name: geometry-lesson
description: Use this skill to turn a middle-school geometry problem into a compiled interactive lesson page. The agent writes teaching markdown and three declarative JSON specs; repository tools compile the HTML.
---

# Geometry Lesson

Use this skill when creating or updating a geometry comprehensive problem page in the `shuxueshuo` repository.

The core rule: HTML is a compiled artifact. Do not hand-write page HTML, SVG path logic, `toScreen`, `diagramMarkupFor`, `drawMini`, polygon clipping, step navigation, sliders, thumbnails, or page runtime JavaScript.

## Output Contract

Work in this order:

0. Select knowledge-base references before solving:
   - Read `internal/knowledge-points/junior-math-methods.md`.
   - Read `internal/knowledge-points/case-index.md`.
   - Choose one primary `pattern`, the `methods` actually needed by the solution, and 1-3 similar published cases.
   - Read the selected cases' `02_solution.md`; read their `03_visual_steps.md` and `lesson-data.json` only when the visual flow or JSON structure is directly relevant.
   - If a selected case already demonstrates the JSON shape and id alignment you need, skip the skill's built-in few-shot entirely.
1. Create or update `internal/lesson-specs/<problem-id>/01_problem.md`.
2. Create or update `internal/lesson-specs/<problem-id>/02_solution.md`.
3. Create or update `internal/lesson-specs/<problem-id>/03_visual_steps.md`.
4. Create or update the compiled-page input JSON files:
  - `geometry-spec.json`
  - `step-decorations.json`
  - `lesson-data.json` (including `meta.classification`)
5. Before compiling a publish page, update the knowledge-base metadata:
   - Check whether `lesson-data.json.meta.classification` is missing, stale, or inconsistent with the final solution; update it before building.
   - If this is a complete JSON-spec page being compiled for publication, add or update the case in `internal/knowledge-points/case-index.md`.
   - Add one Part 1 row under the chosen `pattern`, and one Part 2 row under each listed `method`.
   - Draft pages may include `meta.classification`, but do not enter `case-index.md` until the publish compile.
6. Run validation and compilation:

```bash
node tools/validate-geometry-spec.mjs internal/lesson-specs/<problem-id>/
node tools/build-lesson-page.mjs internal/lesson-specs/<problem-id>/
```

The final HTML path is controlled by `lesson-data.json.meta.outputPath`.

## Reference Files

Load only the references needed for the current task:

- Always begin with the knowledge base: `../../knowledge-points/junior-math-methods.md` and `../../knowledge-points/case-index.md`. Use them to select the primary `pattern`, allowed middle-school `methods`, and similar published cases before writing the solution route.
- Read `references/geometry-solving-principles.md` before writing `02_solution.md` or revising reasoning quality.
- Read `references/json-schema-guide.md` before writing any of the three JSON specs.
- Read `references/original-figure-principles.md` before writing or revising `geometry-spec.originalFigures`.
- Read `../../docs/interactive-lesson-components.md` (repo path: `internal/docs/interactive-lesson-components.md`) before adding or changing sliders, local point controls, or draggable-point interactions. It defines the relationship between the main parameter slider and step-local point controls.
- Read `references/nankai-24-fewshot.md` only as a fallback when `case-index.md` has no sufficiently similar published case, or when the selected cases do not demonstrate the JSON shape you need. Do not prefer this fixed few-shot over a closer indexed case.
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
- For boundary or extremum steps, include the exact parameter value in the step title or conclusion box when it is the reason the snapshot matters, such as `由左端三角形求 S（t=√3/2）`.
- Reuse named points and earlier conclusions instead of re-deriving them.
- Keep endpoint inclusiveness identical across solution text, visual steps, JSON policies, answer chips, and final answers.
- Follow the unified reasoning and visual principles below when choosing the route and diagram contents.

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

## Reasoning And Visual Principles

Keep these principles together when revising a lesson. Do not solve one local visual problem by adding ad hoc labels or duplicate elements that contradict the overall model.

### Reasoning Route

- When a transformation or fixed shape (fold, rotation, translation, equilateral triangle, rhombus) gives 30°、45°、60° right triangles, isosceles triangles, perpendiculars, or visible parallel distances, prefer those constructions and line-segment differences before coordinate-intersection algebra. For example, derive `CG` and `HB` from local `30°` right triangles, then use `GH=BC-CG-HB`, instead of solving coordinates for `G` and `H` directly.
- When a coordinate expression is still needed, derive it from a visible geometric construction first when possible. For example, use an isosceles triangle plus a perpendicular foot to get a moving point, then record the coordinate expression for later reuse.
- Every non-obvious length or distance formula in the derivation must cite its immediate source: the named right triangle, a previous coordinate expression, a transformation-preserved length/angle, or a visible segment difference. Avoid lines that introduce `OD=...`, `DG=...`, or a point-to-line distance without the preceding reason.
- When a target length is obtained by subtracting visible pieces, first derive and display the intermediate pieces actually used, then take the difference. For example, show `AN` and `AG` before `GN=AN-AG`, or construct `K` and show `DK` before `E′D=E′K-DK`.
- For piecewise overlap or area problems, first name every phase and boundary value, then choose the simplest phase that can produce the requested value. Use interval thumbnails only for phase comparison; put formula-specific helper lines in the later calculation step that actually uses them.
- For area ranges, first decide the shape, monotonic trend, and degenerate boundary states of each phase. Compute exact area formulas only for phases that can contain an interior extremum; for simple monotone phases, compare boundary candidates directly.
- For boundary/extremum area calculations, match the formula to the actual visible boundary shape: use a small triangle as a triangle, a 60° rhombus as a rhombus, and add the construction point or perpendicular that reveals the needed side/height before computing the area.
- For open-domain area ranges, calculate excluded endpoints as exact boundary snapshots when they determine a strict bound, but state clearly that the value is not attained. Keep left boundary calculation, interior extremum calculation, right boundary calculation, and final merge as separate steps when each has its own geometry.
- For quadrilateral overlap areas, check whether the quadrilateral is naturally a large triangle minus a small triangle before splitting it by a diagonal. Prefer the subtraction model when it matches the visible containment, such as `S=△EHF-△EDG`.
- At folding boundary states, prefer fold facts and local standard triangles over coordinates. For example, use the perpendicular-bisector relation to get `A′D=AA′/2`, then use a visible `30°` right triangle for the other area leg, instead of computing the intersection point coordinates.
- For folds, the displayed folded polygon must be the actual image of the current paper piece for that interval. If the fold line cuts different original sides in different intervals, use interval-specific `movingPolygons` instead of extending a later-stage polygon backward.

### Layer And When Scoping

- Section layers must not leak objects into unrelated steps. Use `section`, `sectionNot`, or `stepStartsWith` conditions that exactly match the intended scope.
- A boundary-only label (e.g. a `when`-gated annotation for a phase boundary) must not appear at non-boundary parameter values; verify every `when` condition covers exactly the intended parameter range.

### Public Renderer First

- Use existing public decoration fields first, such as `originLabel` / `showOriginLabel` on `grid`, `labelRadius` / `lockLabel` on `angleArc`, `offsetPx` / `rotateWithLine` on `segment`, and `showLabel:false` on `point`.
- Keep diagram labels sparse and step-local. Show only the angles, lengths, point names, and regions used in the current inference; put derived coordinates and reusable algebraic conclusions in `lesson-data.steps[].box` or the derivation text unless they have spatial meaning.
- Anchor every length or distance label to a real visible segment or constructed perpendicular. Do not place standalone words such as `高=...` or `距离=...` in the diagram unless the corresponding segment is drawn and connected to its endpoints; prefer labelling the segment itself with just the length when context is clear.
- If two named points coincide, prefer one merged label such as `O(D)` through grid/origin-label configuration or a single point label. Do not show both the coordinate grid's `O` and a separate nearby `D` label.
- Place angle text with the angle arc: use `angleArc` label controls such as `labelRadius` and `lockLabel` before adding separate text. The numeric angle label should sit near the middle of the arc, slightly outside it.
- Angle arcs must correspond to the exact triangle used in the current derivation. If the text uses `Rt△ODE` and `∠DEO=30°`, mark that angle, not merely a related parallel angle elsewhere.
- For subtraction regions, prefer mathematical symbols such as `-` in the diagram and formula card text such as `S=△EHF-△EDG`; keep explanatory words like "减去" in the derivation text.
- Use `coloredLine`, `dashedLine`, or `dottedLine` for actual auxiliary segments that must be visibly connected, especially perpendiculars and construction lines. Use `segment` for measured/labelled line segments; do not rely on an unlabeled `segment` as a visible helper line.
- Do not redraw or label a boundary such as `CB` when it is already an edge of `basePoly`, unless that exact boundary length is the current object being calculated.
- Keep formula cards at the model level, such as `S=S△BPQ` or `60°菱形`; put the detailed algebra in the derivation text or conclusion box so the diagram does not duplicate the proof.
- Use navigation labels that state the target quantity and action, such as `边界面积最小值`, `四边形面积最大值`, or `合并面积范围`, instead of terse method-only labels like `三角形差`.
- If the required behavior is generally useful but not available declaratively, update the shared renderer/schema in `site/assets/js/geometry-lesson-from-spec.js` and `internal/schemas/step-decorations.schema.json`, then use the new JSON field. Do not fake it with duplicated labels, extra text, or generated-HTML edits.
- If `minis` are meant to be clickable boundary/extremum cards, the owning step must have `policies[stepId].movable: true`, and the policy range must include every mini `t` value, including exact excluded-boundary snapshots used for teaching.
- If no closer indexed case exists and you use `references/nankai-24-fewshot.md` as a fallback for id alignment and layer shape, do not rely on few-shots alone for renderer behavior; the real public runtime and schema are authoritative.

### Style Preset and Normalizer

The build pipeline runs a normalizer (`tools/lib/lesson-normalizer.mjs`) before compilation and validation. It reads `internal/config/style-presets.json` and fills in any missing style fields on decoration elements by type. It also auto-generates `range: [t, t]` for non-movable steps that lack a range.

What this means for writing JSON specs:

- **Omit default style fields** such as `color`, `width`, `dash`, `r`, `size`, `fontSize` when the preset value is acceptable. The normalizer will fill them in.
- **Only declare a style field** when you need a value different from the preset — for example, a lighter parabola for background context, or a custom point radius.
- **Always declare semantic fields** that the normalizer does not handle: `at`, `from`, `to`, `label`, `labelText`, `text`, `curveId`, `xExpr`, `vertex`, `rayA`, `rayB`, `dx`, `dy`, `showLabel`, `offsetPx`, `labelRadius`, `lockLabel`, `domain`, `pointOverrides`.
- **Always declare `range`** for movable steps (`movable: true`). Non-movable steps may omit `range`.

See `internal/config/style-presets.json` for the full list of types and their defaults.

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
- `meta.classification`: `pattern` plus ordered `methods` from `internal/knowledge-points/junior-math-methods.md`
- `problem.summary`
- `problem.lines`
- `ui.legend`, `sliderLabel`, `paramLabelPrefix`, `goToProblemMode`, `groupTitles`
- `steps`
- `policies`
- `stepLabels`

Hard constraints:

- `meta.classification.pattern` must be one primary pattern ID defined in `junior-math-methods.md`.
- `meta.classification.methods` must list only method IDs from `junior-math-methods.md`, ordered by first use in the solution.
- Classification must match both the final `02_solution.md` and any `case-index.md` rows added during publish compilation.
- `problem.lines` must be plain data: text lines, answer chip lines, heading lines, or original-figure groups.
- `ui.legend` must be `{ "colorVar": "...", "label": "..." }` items.
- Do not put HTML tags or style strings in any JSON text field.
- Every `lesson-data.steps[].id` must exist in `lesson-data.policies`, `lesson-data.stepLabels`, and `step-decorations.steps`.
- Every `problem.lines[].figures[].id` must match an id in `geometry-spec.originalFigures`.
- `lesson-data.meta.id` and `geometry-spec.id` must match.

For field details and common validation errors, use `references/json-schema-guide.md`. For exact allowed fields and types, use the real schema files in `internal/schemas/`.

## Validation And Compilation

Before compiling a page for publication:

- Re-read `lesson-data.json.meta.classification` and confirm the `pattern` / `methods` still match the final solution.
- Re-read `internal/knowledge-points/case-index.md`; if the current complete JSON-spec page is being published and is missing from the index, add or update its Part 1 and Part 2 rows before building.
- Do not add draft or unreviewed pages to `case-index.md`.

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
- The knowledge base was used first: `junior-math-methods.md` for allowed methods and `case-index.md` for similar cases.
- Every solution step has a matching visual step.
- The three JSON files contain pure data and no HTML strings.
- Coordinates use one mathematical scale through the shared renderer.
- Intersections are declared through `derivedIntersections`.
- Step ids are aligned across `steps`, `policies`, `stepLabels`, and `step-decorations`.
- Original figure ids align between `lesson-data.problem.lines` and `geometry-spec.originalFigures`.
- `lesson-data.meta.classification.pattern` and every listed method ID exist in `junior-math-methods.md`.
- For publish compilation, `case-index.md` contains the current page under its pattern and every listed method.
- Pure geometry original figures set `showGrid:false`, include all printed point labels, and reproduce printed right-angle marks without adding solution-only highlights.
- Original figure point labels use object entries such as `{ "at": "A", "label": "A", "dx": 10, "dy": 26 }`; never use string arrays such as `["A", "B"]`.
- The unified reasoning and visual principles above are satisfied: no duplicate same-point labels, no unlabeled measured segments, no unnecessary boundary redraws, no phase helpers in trend-only snapshots, and no false folded polygon for the interval.
- Extremum reasoning compares every included endpoint candidate that the trend step identifies; do not discard a candidate endpoint without a comparison.
- Boundary inclusiveness matches everywhere.
- Validation and compilation both pass.
