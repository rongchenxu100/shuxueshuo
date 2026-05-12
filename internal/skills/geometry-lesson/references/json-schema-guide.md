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
- `basePolygon` / `movingPolygon`: fixed vs moving polygon vertex ids (**只对裁剪重叠题型必填；纯抛物线页可省略**)

Optional common fields:

- `expressionEnv`: ordered `{ "name": "a", "expr": "2" }[]`，逐项写入求解 env，便于点在表达式里引用系数（如 `["0","c"]`）。
- `curves`: 抛物线等，`[{ "id": "parabolaMain", "type": "parabola", "a": "a", "b": "b", "c": "c" }]`（系数也可用 `"params": { "a","b","c" }`）。
- `movingPolygons`: interval-specific moving polygon vertex ids. Use this when the folded or moving figure changes shape across parameter intervals, especially when a fold line cuts different original sides in different phases.
- `foldedPolygon`: vertical-fold shortcut. Use `{ "x": "t", "side": "left" }` to fold the portion of `basePolygon` left of `x=t`; the runtime clips the base polygon then reflects it. This is only for vertical folds that can be generated from `basePolygon`.
- `derivedIntersections`: declare intersections by two point-pair lines: `{ "name": "E", "a": ["A", "C"], "b": ["M", "N"] }`
- `originalFigures`: problem-card figures, each with an `id` that must match `lesson-data.problem.lines[].figures[].id`

Rules:

- Use expression strings such as `"3*S3"`, `"t/2"`, `"S3*(9-t)/4"`.
- `movingParam` names the slider-driven unknown (`t`、`m` 等)，表达式里用同名变量；`expressionEnv` 可再加入任意常量名（如系数）。
- Do not hand-write dynamic intersection formulas; use `derivedIntersections`.
- `fallback` may be used for original/static figure rendering.
- For pure geometry source figures, set `"showGrid": false` inside the `originalFigures[]` item. Coordinate grids/axes are not implicit source context.
- Use `rightAngles` inside an `originalFigures[]` item for printed right-angle marks, for example `{ "vertex": "C", "rayA": "A", "rayB": "B" }`.
- Do not force one `movingPolygon` through every phase when the real folded piece changes shape. If an unexpected sliver or small triangle appears in a folding trend diagram, first check whether the model is using a later-stage polygon outside its valid interval.
- Use `movingPolygons` for explicit phase models:

```json
"movingPolygons": [
  { "maxT": 2, "vertices": ["P", "Op", "R"] },
  { "minT": 2, "vertices": ["P", "Op", "Ap", "Q"] }
]
```

  Each entry describes the actual folded/moving region on that interval. The runtime uses the first entry whose `minT` / `maxT` contains the current parameter. Points in `vertices` must already be declared in `fixedPoints`, `movingPoints`, or `derivedIntersections`.
- 原题图点标识必须写成对象数组，不能写成字符串数组。正确格式：

```json
"fixedLabels": [
  { "at": "A", "label": "A", "dx": 10, "dy": 26 },
  { "at": "B", "label": "B", "dx": 10, "dy": -10 }
],
"movingLabels": [
  { "at": "Cp", "label": "C′", "color": "#0f766e", "dx": 12, "dy": -12 }
],
"intersectionLabels": [
  { "at": "D", "label": "D", "color": "#dc2626", "dx": 12, "dy": -12 }
]
```

  `at` 必须是 `fixedPoints`、`movingPoints` 或 `derivedIntersections[].name` 中已经声明的点；`label` 是图上显示的文字。若原点 O 已由坐标网格显示，通常不要再放进 `fixedLabels`，避免重复。

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

Rules:

- Put stable context in `layers`, not repeated step additions.
- Put only current-step helper/highlight elements in `steps[stepId].add`.
- Every `lesson-data.steps[].id` must have a matching `step-decorations.steps[id]`.
- When point `O` is also the coordinate origin, avoid duplicate `O` labels. Prefer `{ "type": "point", "at": "O", "showLabel": false }` if the grid already labels the origin.
- Decorations may use `minT` / `maxT` when a named point only exists in part of the folding process. For example, `Q` on an upper edge should not be labeled before the fold line reaches that edge. However, do not use decoration visibility to hide an incorrect folded polygon; fix `geometry-spec.movingPolygons` or `foldedPolygon` so the underlying overlap model is correct.

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

`ui.legend` supports only:

```json
{ "colorVar": "paper", "label": "固定图形" }
```

Step alignment:

- Each `steps[].id` must exist in `policies`.
- Each `steps[].id` must exist in `stepLabels`.
- Each `steps[].id` must exist in `step-decorations.steps`.

## Common Validation Errors

- HTML appears in JSON text: remove `<span>`, `<div>`, `style=`, or SVG strings.
- `meta.id` does not match `geometry-spec.id`.
- A step id is missing from `policies`, `stepLabels`, or `step-decorations.steps`.
- An original figure id appears in `lesson-data` but not in `geometry-spec.originalFigures`.
- A decoration `type` is misspelled.
- A point id in a segment or polygon is not declared in fixed, moving, or derived points.
- The grid labels the origin `O` and a separate point decoration or original-figure label also writes `O`, causing duplicate origin text.
- A folding page uses one static `movingPolygon` even though the fold line cuts different original sides in different intervals; replace it with `movingPolygons` or a valid `foldedPolygon`.
