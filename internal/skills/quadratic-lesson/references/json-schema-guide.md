# JSON Schema Guide

The compiled geometry lesson page is driven by three JSON files in `internal/lesson-specs/<problem-id>/`.

This guide explains how to fill them. The exact field and type constraints are defined by the real schema files:

- `internal/schemas/geometry-spec.schema.json`
- `internal/schemas/step-decorations.schema.json`
- `internal/schemas/lesson-data.schema.json`

Run this after editing them:

```bash
node tools/validate-geometry-spec.mjs internal/lesson-specs/<problem-id>/
```

## `geometry-spec.json`

Required top-level fields:

- `version`: integer, currently `1`
- `id`: must match `lesson-data.json.meta.id`
- `domain`: `{ "minX", "maxX", "minY", "maxY" }`
- `fixedPoints`: point coordinates as expression strings
- `movingParam`: usually `"t"`
- `movingPoints`: moving point coordinates as expression strings
- `basePolygon` / `movingPolygon`: fixed vs moving polygon vertex ids (**只对裁剪重叠题型必填；纯抛物线页可省略**）

Optional common fields:

- `expressionEnv`: ordered `{ "name": "a", "expr": "2" }[]`，逐项写入求解 env，便于点在表达式里引用系数（如 `["0","c"]`）。
- `curves`: 抛物线等，`[{ "id": "parabolaMain", "type": "parabola", "a": "a", "b": "b", "c": "c" }]`（系数也可用 `"params": { "a","b","c" }`）。
- `derivedIntersections`: declare intersections by two point-pair lines: `{ "name": "E", "a": ["A", "C"], "b": ["M", "N"] }`
- `originalFigures`: problem-card figures, each with an `id` that must match `lesson-data.problem.lines[].figures[].id`

Rules:

- Use expression strings such as `"3*S3"`, `"t/2"`, `"S3*(9-t)/4"`.
- `movingParam` names the slider-driven unknown (`t`、`m` 等)，表达式里用同名变量；`expressionEnv` 可再加入任意常量名（如系数）。
- Do not hand-write dynamic intersection formulas; use `derivedIntersections`.
- `fallback` may be used for original/static figure rendering.

## `step-decorations.json`

Required top-level fields:

- `layers`: named context layers
- `steps`: step-id keyed additions

Layer shape:

```json
{
  "layers": {
    "global": {
      "elements": [
        { "type": "grid" },
        { "type": "basePoly" }
      ]
    },
    "II": {
      "sectionNot": "第（I）问",
      "elements": [
        { "type": "movingPoly" },
        { "type": "overlap" }
      ]
    }
  }
}
```

Step shape:

```json
{
  "steps": {
    "q1s1": {
      "domain": { "minX": 0, "maxX": 5, "minY": -3, "maxY": 2 },
      "pointOverrides": {
        "G": ["2+u", "-2+3*u"]
      },
      "add": [
        { "type": "segment", "from": "D", "to": "P", "label": "DP=t-3" }
      ]
    }
  }
}
```

Supported decoration types include:

- `grid`, `basePoly`, `movingPoly`, `overlap`
- `point`, `derivedPoint`
- `segment`, `dashedLine`, `dottedLine`, `coloredLine`
- `rightAngle`, `angleArc`
- `coordinateLabel`, `coincidentLabel`
- `cutRegion`, `outlineRegion`
- `areaLabel`, `areaFormulaCard`
- **抛物线 / 坐标示意：** `parabola`, `axisOfSymmetry`, `vertex`, `curvePoint`（需对应 `geometry-spec.curves[].id`，常用字段 `curveId`、`xExpr`）

### Style fields: omit vs declare

The normalizer fills default style values from `internal/config/style-presets.json` by decoration `type`. You should **omit** style fields when the preset default is acceptable, and **only declare** them when overriding.

Fields that can be omitted (normalizer fills from preset):

| field | applies to |
|-------|-----------|
| `color` | all types with a color |
| `width` | line types (`coloredLine`, `dashedLine`, `dottedLine`, `segment`, `parabola`, `axisOfSymmetry`, `circle`, `circleArc`, `outlineRegion`) |
| `dash` | `dashedLine`, `dottedLine`, `axisOfSymmetry`, `outlineRegion` |
| `r` | `point`, `derivedPoint`, `curvePoint`, `vertex` |
| `size` | `rightAngle`, `areaLabel` |
| `fontSize` | `angleArc`, `coordinateLabel` |
| `radius` | `angleArc` |
| `fill` | `circle`, `outlineRegion` |

Fields that must always be declared (semantic, not defaulted):

`type`, `at`, `from`, `to`, `label`, `labelText`, `text`, `curveId`, `xExpr`, `vertex`, `rayA`, `rayB`, `dx`, `dy`, `showLabel`, `offsetPx`, `labelRadius`, `lockLabel`.

Example — a point that uses all defaults:

```json
{ "type": "point", "at": "A", "dx": 12, "dy": -18 }
```

Example — a point that overrides the default color:

```json
{ "type": "point", "at": "A", "color": "#dc2626", "dx": 12, "dy": -18 }
```

Rules:

- Put stable context in `layers`, not repeated step additions.
- Put only current-step helper/highlight elements in `steps[stepId].add`.
- Every `lesson-data.steps[].id` must have a matching `step-decorations.steps[id]`.
- `segment` renders a dimension/measurement label; it is not a substitute for the visible mathematical line. For any segment that must appear as a side, path, or constructed line, add `coloredLine`/`dashedLine`/`dottedLine` for the actual geometry and then add `segment` for the label if needed.
- When point `O` is also the coordinate origin, avoid duplicate `O` labels. Prefer `{ "type": "point", "at": "O", "showLabel": false }` if the grid already labels the origin.
- Avoid duplicate point labeling. If a context layer already draws a point, use `showLabel: false` there and add either a point-name label or a coordinate label in the current step, not both.
- Use `coordinateLabel` only in coordinate-computation steps. In transformation or shortest-path steps, prefer plain point names and key segments.
- In coefficient-solving steps, coordinate labels should match the current algebraic state. Use symbolic labels such as `N((2b−1)/4,0)` while solving; avoid final numeric labels such as `N(3/4,0)` until after `b=2` is derived and only if the coordinate itself is needed.
- Use `areaFormulaCard` sparingly. Do not add formula cards that duplicate `lesson-data.steps[].derive` or `box` text; prefer putting algebra in the derivation panel and using the diagram for points, segments, angle marks, and essential length labels.
- Use `steps[stepId].domain` to locally zoom a single diagram when the derivation only depends on a small construction. This is especially useful for line-sum transformation and reflection/将军饮马 steps; avoid a large mostly-empty coordinate plane when students only need the local auxiliary figure.
- Use `steps[stepId].pointOverrides` with `lesson-data.steps[].localControls` when a step needs local draggable points. The override expressions can reference the local control variables and replace only the named points for that step; the underlying `geometry-spec.movingPoints` remains the default/static state.
- Keep step diagrams aligned with the derivation focus:
  - proving `EG = DG`: draw `DG`, helper perpendiculars, and label helper feet such as `H`/`K`;
  - applying reflection/将军饮马: draw `D'`, `MD'`, `ND'`, `DG`, and `D'F`; remove distracting `EG` if it is no longer the target segment.
- If a step uses a point, the point must be declared in `fixedPoints`, `movingPoints`, or `derivedIntersections`. For auxiliary points that are explicit formulas, add them to `movingPoints` or `fixedPoints` rather than using ad hoc SVG.

Local point controls in `lesson-data.json`:

```json
{
  "localControls": {
    "values": { "u": 0.333333 },
    "note": "拖动 G 观察最短状态。",
    "controls": [
      { "var": "u", "label": "动点 G：NG/MN", "min": 0, "max": 1, "step": 0.01, "scale": 1, "precision": 2 }
    ]
  }
}
```

For constrained two-point motion, use multiple controls backed by the same source variable and different `scale` values. This gives students two point components while preserving the mathematical constraint.

Main slider hygiene:

- Do not set `policies[stepId].movable: true` for an unknown coefficient that the problem asks students to solve.
- If a diagram needs a concrete drawing state for a coefficient-solving step, keep the policy non-movable and use the step's `t` value as a representative render state.
- Use `localControls` only for step-local moving points such as `N` in a 将军饮马 construction; local controls should not change the problem's coefficient state.

## `lesson-data.json`

Required top-level fields:

- `meta`
- `problem`
- `steps`
- `policies`
- `stepLabels`

`problem.lines` supports only these data shapes:

```json
{ "text": "普通题目行" }
{ "text": "带答案行", "answerId": "answerI", "answer": "答案：..." }
{ "heading": "原题图形" }
{ "ariaLabel": "原题图 1 和图 2", "figures": [{ "id": "originalFigure1", "title": "图 1" }] }
```

If a sub-question asks students to "直接写出" or the lesson is meant to reveal final answers in the problem card, add `answerId` and `answer` for every answered sub-question, including Part I. Do not only add answer badges for later sub-questions.

`ui.legend` supports only:

```json
{ "colorVar": "paper", "label": "固定图形" }
```

Step alignment:

- Each `steps[].id` must exist in `policies`.
- Each `steps[].id` must exist in `stepLabels`.
- Each `steps[].id` must exist in `step-decorations.steps`.
- `stepLabels` should be compact but meaningful, usually "method + target". Prefer labels such as `等角作C′定BM`, `铅垂面积求b`, or `构造等腰求a`; avoid vague labels such as `确定 BM`, `求 b`, or labels that omit the key method.

Derivation text rules:

- Use `∵`, `∴`, and `作` as the left-hand labels in `derive` whenever possible.
- A derive row may include a third declarative reference object, e.g. `["∵", "由上一步全等直角三角形思路", { "refStep": "q1s2", "refLabel": "回看第（II）①第2步" }]`. The runtime renders this as a small jump button; do not write HTML links in JSON.
- Keep derived state synchronized. If an earlier row solved `m=3`, subsequent rows should use `M(3,1)` and `N(2,−2)` rather than generic expressions.
- Do not include unasked extras in `box` or `derive`; if the problem does not ask for a vertex, do not add it.
- Avoid HTML and avoid long prose inside derive rows; split a dense argument into short mathematical rows.

## Common Validation Errors

- HTML appears in JSON text: remove `<span>`, `<div>`, `style=`, or SVG strings.
- `meta.id` does not match `geometry-spec.id`.
- A step id is missing from `policies`, `stepLabels`, or `step-decorations.steps`.
- An original figure id appears in `lesson-data` but not in `geometry-spec.originalFigures`.
- A decoration `type` is misspelled.
- A point id in a segment or polygon is not declared in fixed, moving, or derived points.
- The grid labels the origin `O` and a separate point decoration or original-figure label also writes `O`, causing duplicate origin text.
