---
name: quadratic-lesson
description: Use this skill to turn a middle-school quadratic-function comprehensive problem into a compiled interactive lesson page. The agent writes teaching markdown and three declarative JSON specs; repository tools compile the HTML. Parabolas use geometry-spec curves; CSS/JS/runtime are shared with geometry-lesson pages.
---

# Quadratic Lesson

Use this skill when creating or updating a **二次函数综合题** interactive page in the `shuxueshuo` repository.

The core rule is the same as `geometry-lesson`: **HTML is a compiled artifact.** Do not hand-write page HTML, SVG path logic, `diagramMarkupFor`, `drawMini`, step navigation, sliders, thumbnails, or page runtime JavaScript.

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
   - `geometry-spec.json` (may include `curves` for `y = ax²+bx+c` and optional `expressionEnv`)
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

- **Always begin** with the knowledge base: `../../knowledge-points/junior-math-methods.md` and `../../knowledge-points/case-index.md`. Use them to select the primary `pattern`, allowed middle-school `methods`, and similar published cases before writing the solution route.
- **Always read** `references/quadratic-solving-principles.md` — quadratic-specific modeling rules (coefficient constraints, N-derivation via rotation, expressionEnv ordering, EG+FG optimization pattern, two-curve pattern for Part I vs Part II).
- **Always read** `references/json-schema-guide.md` before writing any of the three JSON specs — covers field types, required vs optional, and how to align ids across files.
- **Always read** `references/diagram-drawing-principles.md` before writing or revising `03_visual_steps.md` or `step-decorations.json` — covers what to draw, how to mark used values/equalities, constructed segments, moving segments, and geometric transformations.
- **Always read** `references/original-figure-principles.md` before adding or changing `geometry-spec.originalFigures` or any `lesson-data.problem.lines[].figures` entry. If the source problem has no printed figure, do not invent one.
- **Read** `../../docs/interactive-lesson-components.md` (repo path: `internal/docs/interactive-lesson-components.md`) before adding or changing sliders, local point controls, or draggable-point interactions. It defines the relationship between the main parameter slider and step-local point controls.
- **Read** `references/nankai-25-fewshot.md` only as a fallback when `case-index.md` has no sufficiently similar published case, or when the selected cases do not demonstrate the JSON shape you need. Do not prefer this fixed few-shot over a closer indexed case.
- Read the real schema files before writing JSON (they override anything in the reference docs if there is a conflict):
  - `internal/schemas/geometry-spec.schema.json` (`expressionEnv`, `curves`, optional `basePolygon`/`movingPolygon`)
  - `internal/schemas/step-decorations.schema.json` (`parabola`, `axisOfSymmetry`, `vertex`, `curvePoint`, `dashedLine`)
  - `internal/schemas/lesson-data.schema.json`

Do not use skill references as JS/CSS sources.  
Do not read `geometry-solving-principles.md` or `nankai-24-fewshot.md` for quadratic problems — those are geometry-specific (polygon clipping, rotation angles, area decompositions).

### Style Preset and Normalizer

The build pipeline runs a normalizer (`tools/lib/lesson-normalizer.mjs`) before compilation and validation. It reads `internal/config/style-presets.json` and fills in any missing style fields on decoration elements by type. It also auto-generates `range: [t, t]` for non-movable steps that lack a range.

What this means for writing JSON specs:

- **Omit default style fields** such as `color`, `width`, `dash`, `r`, `size`, `fontSize` when the preset value is acceptable. The normalizer will fill them in.
- **Only declare a style field** when you need a value different from the preset — for example, a lighter parabola for background context, or a custom point radius.
- **Always declare semantic fields** that the normalizer does not handle: `at`, `from`, `to`, `label`, `labelText`, `text`, `curveId`, `xExpr`, `vertex`, `rayA`, `rayB`, `dx`, `dy`, `showLabel`, `offsetPx`, `labelRadius`, `lockLabel`, `domain`, `pointOverrides`.
- **Always declare `range`** for movable steps (`movable: true`). Non-movable steps may omit `range`.

See `internal/config/style-presets.json` for the full list of types and their defaults.

## Audience — quadratic-specific guidance

Default to middle-school students. Compared with pure folding/rotation geometry pages:

- Balance **代数推导**（解析式、配方、判别式、根与系数）with **坐标图示**（抛物线、对称轴、与坐标轴交点）。
- Many steps justify coefficients before drawing conclusions about symmetric axis / vertices / intersections with axes.
- For middle-school trigonometry, use only the definition of `tan` in a right triangle. Do not use tangent subtraction/addition formulas, slope-angle tangent formulas, or other high-school trigonometric identities. If an angle condition involves \(45^\circ\), prefer constructing an auxiliary point/line that creates a right triangle where the target tangent can be read as opposite leg divided by adjacent leg.
- Follow `references/diagram-drawing-principles.md` for step diagrams, including how to mark used quantities, equalities, constructed segments, moving segments, and geometric transformations.
- If part II introduces constructions (`直角`、`等腰`、`中点`、`线段比例`), treat those steps like geometry: draw only what the derivation truly uses.
- Dynamic controls usually correspond to a **parameter letter shown on the exam** (`m`, `t`, etc.). Align `geometry-spec.movingParam`, expressions that reference this letter, `lesson-data.ui.sliderLabel`, and `lesson-data.policies[].range`.
- Do **not** add a main slider for a coefficient or unknown that the problem asks students to solve (`a`、`b`、`c`). Keep those steps non-movable and use a representative symbolic/solved drawing state only for the diagram. Use local controls only for genuine moving points inside a construction or shortest-path observation.
- Keep numeric endpoints consistent everywhere (`≤`, `<`) across markdown, JSON chips, and slider ranges.

## Step 1: `01_problem.md`

Same structural headings as `geometry-lesson` (`基本信息`、`题目原文`、`已知条件`、`小问列表`、`标准答案`). Highlight:

- the quadratic relation \(y = ax^2 + bx + c\) and constraints among coefficients (e.g. \(2a + b = 0\)).
- axis of symmetry wording (“抛物线的对称轴与 x 轴交于点 D”).
- moving-point wording (“点 E、G …”，“线段”“比例”“最小值”).

## Step 2: `02_solution.md`

Use short derivation lines with `∵` / `∴`. Prefer titles such as:

- `由已知系数关系消参`
- `由对称轴求交点坐标`
- `配方或代入定点写解析式`
- `化简函数表达式并求点坐标`
- `构造直角三角形求线段`
- `构造等腰直角三角形转化线段`
- `将军饮马，折线三点共线时最短`

Avoid dumping lengthy algebraic manipulation without naming intermediate meanings each step.

When a coordinate-geometry condition contains `90°` or equal lengths, prefer a middle-school geometry route before coefficient solving: draw the needed perpendicular foot, prove right-triangle congruence or an isosceles-right relation, obtain the target point coordinate, then substitute into the parabola.

When an angle condition determines a line through an axis point, first look for a middle-school construction before using slope language. Useful patterns include reflecting a point across an axis, building an isosceles triangle, or letting the target line meet an axis at an auxiliary point \(C'\) so equal angles become equal vertical segments such as \(C'O=CO\). Use slope only after the construction has produced two points on the line, and phrase it as "由两点确定直线" when possible.

When computing a coordinate triangle area, first check whether a vertical or horizontal auxiliary segment can split the triangle into two readable pieces. Prefer an "铅垂面积" expression such as `1/2·vertical base·left horizontal distance + 1/2·vertical base·right horizontal distance` over determinant-style coordinate area in student-facing text.

## Step 3: `03_visual_steps.md`

Same layering mindset as geometry-lesson (whole-problem / section / phase / step). For quadratic pages additionally specify:

- which subset of the curve domain should remain visible for readability (`geometry-spec.domain`).
- when `expressionEnv` should expose coefficients (`a`, `b`, `c`) separately so fixed-point formulas (`["0","c"]`) stay declarative.
- when to use decorations `parabola`, `axisOfSymmetry`, `vertex`, `curvePoint` versus ordinary `point`, following `references/diagram-drawing-principles.md`.
- which labels are allowed at each stage: use symbolic coordinates before a parameter is solved; reserve final numeric coordinates and final answer labels for the step that derives them.
- where local zoom domains are needed. Geometry-heavy congruence or shortest-path computation steps should often use `steps[stepId].domain` so the construction, angle marks, and used lengths are readable.
- which diagram labels are new visual information. Do not add formula cards or labels that merely repeat the derivation panel or the step `box`.
- how `stepLabels` name each step. Prefer compact "method + target" labels such as `等角作C′定BM`, `铅垂面积求b`, or `构造等腰求a` instead of vague result labels such as `确定 BM` or `求 b`.

## Step 4: JSON Specs

### `geometry-spec.json`

- Always define `domain`, `fixedPoints`, `movingPoints`, `movingParam`.
- Optional `basePolygon` / `movingPolygon` for folding/overlap-style problems (omit entirely on pure coordinate-parabola pages).
- Use `expressionEnv` as an ordered list `{ "name": "c", "expr": "-5" }` so downstream expressions can reference coefficients symbolically.
- Declare parabolas:

```json
"curves": [
  { "id": "parabolaMain", "type": "parabola", "a": "a", "b": "b", "c": "c" }
]
```

  (`a`/`b`/`c` may also live under `"params"` — both shapes are supported.)

- Intersections still use `derivedIntersections` whenever possible (same rule as geometry specs).

### `step-decorations.json`

Besides geometry decorators, you may use:

| type | purpose |
|------|---------|
| `parabola` | draws sampled curve from `state.curves[curveId]` |
| `axisOfSymmetry` | vertical line \(x = -b/(2a)\) |
| `vertex` | vertex marker from coefficients |
| `curvePoint` | `(xExpr, y)` from curve via `xExpr` evaluated with `state.env` |

### `lesson-data.json`

Same constraints as `geometry-lesson`: no HTML strings; legend rows remain declarative; step ids must align across `steps`, `policies`, `stepLabels`, and `step-decorations`.

Hard constraints:

- `meta.classification.pattern` must be one primary pattern ID defined in `junior-math-methods.md`.
- `meta.classification.methods` must list only method IDs from `junior-math-methods.md`, ordered by first use in the solution.
- Classification must match both the final `02_solution.md` and any `case-index.md` rows added during publish compilation.

## Validation And Compilation

Before compiling a page for publication:

- Re-read `lesson-data.json.meta.classification` and confirm the `pattern` / `methods` still match the final solution.
- Re-read `internal/knowledge-points/case-index.md`; if the current complete JSON-spec page is being published and is missing from the index, add or update its Part 1 and Part 2 rows before building.
- Do not add draft or unreviewed pages to `case-index.md`.

Always run:

```bash
node tools/validate-geometry-spec.mjs internal/lesson-specs/<problem-id>/
node tools/build-lesson-page.mjs internal/lesson-specs/<problem-id>/
```

Then spot-check the HTML locally.

## Final Review Checklist

- Problem metadata matches the exam reference (`problem-id`, title).
- `expressionEnv` order reflects algebraic dependency (`b` after `a`, etc.).
- Slider labels explain what moves (`sliderLabel`, `paramLabelPrefix`).
- No main slider is used for coefficients that are being solved.
- Every lesson step has diagram intent documented in `03_visual_steps.md`.
- Earlier diagrams do not contain later conclusions: no solved coordinates, final coefficient values, helper points, or final curve state before the matching derivation step.
- Known roots/intercepts are used to simplify/factor the parabola directly before introducing any new unknown point parameter.
- Geometry conditions are solved geometrically when possible: perpendicular feet, right-triangle congruence, isosceles-right triangles, and 将军饮马 before coordinate/vector formulas.
- Angle conditions are converted with visible auxiliary geometry when possible: symmetry points, isosceles triangles, or axis-intersection points before slope/tangent formulas.
- Coordinate-area steps use vertical/horizontal split areas when the diagram provides a natural base, before determinant formulas.
- Diagram labels are not duplicating the derivation panel: no repeated formula cards when the same result is already in `derive` or `box`.
- Step navigation labels are short but meaningful, usually "method + target".
- JSON contains zero HTML fragments.
- Step ids stay synchronized across all artifacts.
- `lesson-data.meta.classification.pattern` and every listed method ID exist in `junior-math-methods.md`.
- Similar cases from `case-index.md` were considered before using a fixed few-shot.
- For publish compilation, `case-index.md` contains the current page under its pattern and every listed method.
- Validation + compilation succeed without patching generated HTML.
