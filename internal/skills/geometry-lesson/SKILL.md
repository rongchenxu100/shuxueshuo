---
name: geometry-lesson
description: Use this skill to turn a middle-school geometry problem into a compiled interactive lesson page. The agent writes teaching markdown and three declarative JSON specs; repository tools compile the HTML.
---

# Geometry Lesson

Use this skill when creating or updating a geometry comprehensive problem page in the `shuxueshuo` repository.

The core rule: HTML is a compiled artifact. Do not hand-write page HTML, SVG path logic, `toScreen`, `diagramMarkupFor`, `drawMini`, polygon clipping, step navigation, sliders, thumbnails, or page runtime JavaScript.

## Responsibility Split

`SKILL.md` says how to build the page; references say how to make it a good lesson. Use the complete loading rules in `Reference Files` below.

## Output Contract

Work in this order:

If the task is only to **iterate this skill**, update the skill/reference files themselves and do **not** update the knowledge base or `case-index.md`. The knowledge-base update rules below apply when creating or publishing a lesson page, not when refining skill instructions.

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
- Read `../../docs/interactive-lesson-components.md` (repo path: `internal/docs/interactive-lesson-components.md`) before adding or changing sliders, local point controls, draggable-point interactions, custom local grid panels, or step-specific hidden layers. It defines the relationship between the main parameter slider, step-local point controls, and shared `hideLayers` / `grid.panels` behavior.
- Read `references/nankai-24-fewshot.md` only as a fallback when `case-index.md` has no sufficiently similar published case, or when the selected cases do not demonstrate the JSON shape you need. Do not prefer this fixed few-shot over a closer indexed case.
- Read `references/piecewise-area-trends.md` only for overlap-area ranges, moving-figure phase analysis, boundary thumbnails, or representative interval minis.
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
- Reuse named points and earlier conclusions instead of re-deriving them.
- Keep endpoint inclusiveness identical across solution text, visual steps, JSON policies, answer chips, and final answers.
- Follow `Per-Problem Checklist` and `references/geometry-solving-principles.md`; detailed step title, navigation label, and boundary-parameter wording rules live in §Step Design.

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

Layering and `when` / section scoping rules live in `references/geometry-solving-principles.md` §Visual Layering.

## Per-Problem Checklist

Scan this checklist for every lesson; load the referenced files for the detailed teaching rules.

- Prefer visible geometry before coordinate-intersection algebra.
- Derive coordinate expressions, non-obvious formulas, and difference lengths from named constructions first.
- For piecewise overlap or area ranges, name phases and boundary values first; for clickable minis, align `policies[].movable` and ranges with all mini `t` values. See `references/piecewise-area-trends.md`.
- Match boundary/extremum area formulas to the visible shape and construction.
- For folds, draw the actual interval-specific folded paper piece.
- Use global, sub-question, phase, step, and derived-results layers; see `references/geometry-solving-principles.md` §Visual Layering.
- Use public decoration fields first, and make angle marks, auxiliary segments, and perpendiculars match the current derivation exactly.
- Diagram label, formula card, duplicate-label, and navigation-label rules live in `references/geometry-solving-principles.md` §Diagram Content / §Area Visuals / §Step Design.
- Extend shared renderer/schema for generally useful missing behavior in `site/assets/js/geometry-lesson-from-spec.js` and `internal/schemas/step-decorations.schema.json`; do not fake it with duplicated labels, extra text, or generated-HTML edits.
- If using `references/nankai-24-fewshot.md`, treat the real schema/runtime as authoritative for renderer behavior.

## Style Preset and Normalizer

The build pipeline runs a normalizer (`tools/lib/lesson-normalizer.mjs`) before compilation and validation. It reads `internal/config/style-presets.json` and fills in any missing style fields on decoration elements by type. It also auto-generates `range: [t, t]` for non-movable steps that lack a range.

What this means for writing JSON specs:

- **Omit default style fields** such as `color`, `width`, `dash`, `r`, `size`, `fontSize` when the preset value is acceptable. The normalizer will fill them in.
- **Only declare a style field** when you need a value different from the preset — for example, a lighter parabola for background context, or a custom point radius.
- **Always declare semantic fields** that the normalizer does not handle when you use them: decoration fields such as `at`, `from`, `to`, `label`, `labelText`, `text`, `curveId`, `xExpr`, `vertex`, `rayA`, `rayB`, `dx`, `dy`, `showLabel`, `offsetPx`, `labelRadius`, `lockLabel`; step-level fields such as `domain`, `pointOverrides`, `hideLayers`; and grid-element fields such as `panels`.
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
- The `Per-Problem Checklist` and referenced teaching rules are satisfied: no duplicate same-point labels, no unlabeled measured segments, no unnecessary boundary redraws, no phase helpers in trend-only snapshots, and no false folded polygon for the interval.
- Extremum reasoning compares every included endpoint candidate that the trend step identifies; do not discard a candidate endpoint without a comparison.
- Boundary inclusiveness matches everywhere.
- Validation and compilation both pass.
