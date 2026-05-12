---
name: quadratic-lesson
description: Use this skill to turn a middle-school quadratic-function comprehensive problem into a compiled interactive lesson page. The agent writes teaching markdown and three declarative JSON specs; repository tools compile the HTML. Parabolas use geometry-spec curves; CSS/JS/runtime are shared with geometry-lesson pages.
---

# Quadratic Lesson

Use this skill when creating or updating a **二次函数综合题** interactive page in the `shuxueshuo` repository.

The core rule is the same as `geometry-lesson`: **HTML is a compiled artifact.** Do not hand-write page HTML, SVG path logic, `diagramMarkupFor`, `drawMini`, step navigation, sliders, thumbnails, or page runtime JavaScript.

## Output Contract

Work in this order:

1. Create or update `internal/lesson-specs/<problem-id>/01_problem.md`.
2. Create or update `internal/lesson-specs/<problem-id>/02_solution.md`.
3. Create or update `internal/lesson-specs/<problem-id>/03_visual_steps.md`.
4. Create or update the compiled-page input JSON files:
   - `geometry-spec.json` (may include `curves` for `y = ax²+bx+c` and optional `expressionEnv`)
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

- **Always read** `references/quadratic-solving-principles.md` — quadratic-specific modeling rules (coefficient constraints, N-derivation via rotation, expressionEnv ordering, EG+FG optimization pattern, two-curve pattern for Part I vs Part II).
- **Always read** `references/json-schema-guide.md` before writing any of the three JSON specs — covers field types, required vs optional, and how to align ids across files.
- **Always read** `references/diagram-drawing-principles.md` before writing or revising `03_visual_steps.md` or `step-decorations.json` — covers what to draw, how to mark used values/equalities, constructed segments, moving segments, and geometric transformations.
- **Always read** `references/original-figure-principles.md` before adding or changing `geometry-spec.originalFigures` or any `lesson-data.problem.lines[].figures` entry. If the source problem has no printed figure, do not invent one.
- **Read** `../../docs/interactive-lesson-components.md` (repo path: `internal/docs/interactive-lesson-components.md`) before adding or changing sliders, local point controls, or draggable-point interactions. It defines the relationship between the main parameter slider and step-local point controls.
- **Read** `references/nankai-25-fewshot.md` to match the exact JSON shape, layer naming convention, and `stepStartsWith` pattern for a parabola problem with Part I (fixed coefficients) and Part II (m-dependent coefficients).
- Read the real schema files before writing JSON (they override anything in the reference docs if there is a conflict):
  - `internal/schemas/geometry-spec.schema.json` (`expressionEnv`, `curves`, optional `basePolygon`/`movingPolygon`)
  - `internal/schemas/step-decorations.schema.json` (`parabola`, `axisOfSymmetry`, `vertex`, `curvePoint`, `dashedLine`)
  - `internal/schemas/lesson-data.schema.json`

Do not use skill references as JS/CSS sources.  
Do not read `geometry-solving-principles.md` or `nankai-24-fewshot.md` for quadratic problems — those are geometry-specific (polygon clipping, rotation angles, area decompositions).

## Audience — quadratic-specific guidance

Default to middle-school students. Compared with pure folding/rotation geometry pages:

- Balance **代数推导**（解析式、配方、判别式、根与系数）with **坐标图示**（抛物线、对称轴、与坐标轴交点）。
- Many steps justify coefficients before drawing conclusions about symmetric axis / vertices / intersections with axes.
- For middle-school trigonometry, use only the definition of `tan` in a right triangle. Do not use tangent subtraction/addition formulas, slope-angle tangent formulas, or other high-school trigonometric identities. If an angle condition involves \(45^\circ\), prefer constructing an auxiliary point/line that creates a right triangle where the target tangent can be read as opposite leg divided by adjacent leg.
- Follow `references/diagram-drawing-principles.md` for step diagrams, including how to mark used quantities, equalities, constructed segments, moving segments, and geometric transformations.
- If part II introduces constructions (`直角`、`等腰`、`中点`、`线段比例`), treat those steps like geometry: draw only what the derivation truly uses.
- Dynamic controls usually correspond to a **parameter letter shown on the exam** (`m`, `t`, etc.). Align `geometry-spec.movingParam`, expressions that reference this letter, `lesson-data.ui.sliderLabel`, and `lesson-data.policies[].range`.
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
- `构造直角三角形求线段`

Avoid dumping lengthy algebraic manipulation without naming intermediate meanings each step.

## Step 3: `03_visual_steps.md`

Same layering mindset as geometry-lesson (whole-problem / section / phase / step). For quadratic pages additionally specify:

- which subset of the curve domain should remain visible for readability (`geometry-spec.domain`).
- when `expressionEnv` should expose coefficients (`a`, `b`, `c`) separately so fixed-point formulas (`["0","c"]`) stay declarative.
- when to use decorations `parabola`, `axisOfSymmetry`, `vertex`, `curvePoint` versus ordinary `point`, following `references/diagram-drawing-principles.md`.

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

## Validation And Compilation

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
- Every lesson step has diagram intent documented in `03_visual_steps.md`.
- JSON contains zero HTML fragments.
- Step ids stay synchronized across all artifacts.
- Validation + compilation succeed without patching generated HTML.
