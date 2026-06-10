# Interactive Lesson Components

This document defines reusable interaction components for compiled lesson pages. It is the shared source of truth for geometry and quadratic lesson skills.

The HTML page is compiled from:

- `geometry-spec.json`
- `step-decorations.json`
- `lesson-data.json`

Do not hand-write generated HTML or one-off JavaScript for these components. Add declarative fields to the JSON specs and update the shared runtime/schema when a new behavior is generally useful.

## Main Parameter Slider

Use the main parameter slider when a step explores the problem's global moving parameter, such as `t`, `m`, or another exam parameter.

Declaration:

```json
"policies": {
  "q1s1": { "movable": true, "range": [3.001, 4.499], "step": 0.001 }
}
```

Runtime behavior:

- Rendered by `site/assets/js/lesson-page-runtime.js`.
- Uses `input[data-step-range]`.
- Calls `diagramMarkupFor(index, nextT, localVars)`.
- Updates `geometry-spec.movingParam` through `resolveClipOverlap(spec, nextT)`.
- Recomputes all points, expressions, curves, polygons, and derived quantities that depend on the main parameter.

Use it for:

- whole-step exploration of a moving point defined by the exam parameter;
- phase changes, endpoint behavior, area trends, or parameter-dependent parabolas;
- geometry 24-style pages where each step is about moving the primary figure.

Avoid it when:

- the exam parameter should remain fixed for the step;
- students only need to drag a local auxiliary point inside a proof or shortest-path construction.

## Clickable Mini Boundary Cards

`lesson-data.steps[].minis` renders both small boundary cards and jump buttons. The cards are clickable only when the owning step is movable through the main parameter.

Declaration pattern:

```json
{
  "id": "q2s5",
  "title": "第5步：合并答案",
  "t": 7,
  "minis": [
    { "title": "t＝4", "caption": "左端边界情况，S＝2√3，但取不到。", "t": 4 },
    { "title": "t＝7", "caption": "最大值，S＝15√3/4。", "t": 7 },
    { "title": "t＝10", "caption": "右端边界情况，S＝2√3，但取不到。", "t": 10 }
  ]
}
```

```json
"policies": {
  "q2s5": { "movable": true, "range": [4, 10], "step": 0.001 }
}
```

Runtime behavior:

- Rendered by `site/assets/js/lesson-page-runtime.js`.
- Uses elements with `data-mini-t`.
- Calls the same main-parameter update path as the slider.
- If `policies[stepId].movable` is false, mini clicks do not update the main diagram.
- If a mini `t` falls outside `policies[stepId].range`, the diagram is clamped to the nearest range endpoint.

Use it for:

- final answer steps that summarize a small number of extremal states;
- exact boundary snapshots, even when the original problem uses an open interval and the value is not attained;
- representative phase cards where clicking should update the main diagram.

Rules:

- Use exact boundary values in `minis[].t` when the point of the card is the boundary geometry; say in the caption whether the value is attained.
- If every mini should be clickable, set `movable: true` and make the policy range include all mini `t` values.
- If a step is purely a fixed calculation and mini clicks are not needed, keep `movable: false` and omit minis or treat them as non-interactive illustration only.

## Local Point Controls

Use local point controls when a step needs students to drag one or more points while the main exam parameter stays fixed.

This component has two parts:

1. `lesson-data.steps[].localControls` declares the visible slider controls.
2. `step-decorations.steps[stepId].pointOverrides` maps local variables to temporary point positions for that step.

Example: one local moving point `G` on `MN`.

```json
{
  "id": "q1s4",
  "t": 3,
  "localControls": {
    "values": { "u": 0.333333 },
    "note": "拖动 G 观察最短状态。",
    "controls": [
      { "var": "u", "label": "动点 G：NG/MN", "min": 0, "max": 1, "step": 0.01, "scale": 1, "precision": 2 }
    ]
  }
}
```

```json
{
  "steps": {
    "q1s4": {
      "pointOverrides": {
        "G": ["2+u", "-2+3*u"]
      },
      "add": []
    }
  }
}
```

Runtime behavior:

- Rendered by `site/assets/js/lesson-page-runtime.js`.
- Uses `input[data-local-control-step]`.
- Does not change `geometry-spec.movingParam`.
- Calls `diagramMarkupFor(index, currentT, localVars)`.
- `geometry-lesson-from-spec.js` applies `pointOverrides` after resolving the normal geometry state.
- Overrides only the named points for that step. Other steps and default moving-point formulas are unchanged.

Use it for:

- local proof diagrams where students drag an auxiliary point;
- shortest-path/reflection diagrams where one point moves on a line;
- constrained point pairs where two visual points move together by one mathematical degree of freedom.
- staged optimization diagrams where the active moving point changes between steps. If a proof first fixes `G` and varies `E,F`, then later varies `G`, use local controls for `E,F` in the fixed-`G` step and a separate local control for `G` in the moving-`G` step.

## Linked Controls For Constrained Points

When two points are constrained, do not give them independent variables. Use multiple controls backed by the same source variable, with `scale` if the displayed ratio differs.

Example: `E` on `DM` and `G` on `MN` constrained by `DE = sqrt(2) * NG`.

```json
"localControls": {
  "values": { "s": 0.666667 },
  "note": "拖动任一动点组件，另一个会按 DE＝√2·NG 自动联动。",
  "controls": [
    { "var": "s", "label": "动点 E：DE/DM", "min": 0, "max": 1, "step": 0.01, "scale": 1, "precision": 2 },
    { "var": "s", "label": "动点 G：NG/MN", "min": 0, "max": 0.5, "step": 0.005, "scale": 0.5, "precision": 2 }
  ]
}
```

```json
"pointOverrides": {
  "E": ["1+2*s", "s"],
  "G": ["2+s/2", "-2+3*s/2"],
  "H": ["2-s/2", "-2+s"],
  "K": ["1+s", "s/2"]
}
```

The two sliders look like two point components to the student, but both update `s`, so the constraint is never broken.

## Main Slider Versus Local Controls

These components are intentionally separate.

| Component | JSON source | DOM marker | Changes | Scope |
|---|---|---|---|---|
| Main parameter slider | `policies[stepId].movable` | `data-step-range` | `geometry-spec.movingParam` | whole step geometry |
| Local point controls | `steps[].localControls` + `pointOverrides` | `data-local-control-step` | local variables only | selected points in one step |

They can coexist in one step, but only do that when the math meaning is clear. In most teaching pages, prefer one of these:

- main slider for broad parameter exploration;
- local point controls for focused auxiliary construction or shortest-path observation.

## Local Diagram Panels And Hidden Layers

Use local diagram panels when a single step must show separate coordinate planes or separated comparison snapshots inside one SVG.

This component has two parts:

1. `step-decorations.steps[stepId].hideLayers` can suppress named context layers for that step.
2. A `grid` decoration can declare `panels`, each with its own bounds, origin, axis labels, and origin label.

Example: two isolated coordinate panels in one step.

```json
{
  "layers": {
    "global": {
      "elements": [
        { "type": "grid" },
        { "type": "point", "at": "O", "showLabel": false }
      ]
    },
    "twoCasesGrid": {
      "stepStartsWith": ["q2s2"],
      "elements": [
        {
          "type": "grid",
          "panels": [
            {
              "minX": -1.5,
              "maxX": 1.2,
              "minY": -1.4,
              "maxY": 1.7,
              "originX": 0,
              "originY": 0,
              "xLabel": "x_L",
              "yLabel": "y_L",
              "originLabel": "O_L"
            },
            {
              "minX": 3.8,
              "maxX": 9.8,
              "minY": -1.4,
              "maxY": 1.7,
              "originX": 4.2,
              "originY": 0,
              "xLabel": "x_R",
              "yLabel": "y_R",
              "originLabel": "O_R"
            }
          ]
        }
      ]
    }
  },
  "steps": {
    "q2s2": {
      "domain": { "minX": -1.8, "maxX": 10, "minY": -1.6, "maxY": 2 },
      "hideLayers": ["global"],
      "add": []
    }
  }
}
```

Runtime behavior:

- Rendered by `site/assets/js/geometry-lesson-from-spec.js`.
- `hideLayers` applies only while rendering that step; it does not mutate the shared layer definitions.
- `grid.panels` draws local grid lines and local x/y axes only inside each panel's rectangular math bounds.
- Each panel defaults to the current render domain and origin `(0,0)` when optional fields are omitted.
- Panel labels should stay ASCII when they appear inside SVG, for example `x_L`, `y_R`, `O_L`.

Use it for:

- side-by-side algebraic cases where each case needs its own coordinate axes;
- comparing two solved states whose y-axes or origins should not be visually merged;
- preventing a global grid/axis layer from drawing through a deliberate blank gap between panels.

Rules:

- Use `hideLayers: ["global"]` when the global grid would create a misleading continuous coordinate plane.
- Keep panel bounds tight enough that the blank gap is visible but not so tight that labels or curves are clipped.
- Do not use panels just for ordinary zooming. Use `steps[stepId].domain` for a single local zoom.
- If panel origins differ from the global origin, add explicit panel labels such as `O_L` and `O_R`; avoid duplicate `O`.

## Derivation Step References

Use derivation step references when a later step cites a previous proof or result and students may need to jump back briefly.

Declaration:

```json
["∵", "由上一步全等直角三角形思路", { "refStep": "q1s2", "refLabel": "回看第（II）①第2步" }]
```

Runtime behavior:

- Rendered by `site/assets/js/lesson-page-runtime.js`.
- Uses `button[data-step-ref]`.
- Calls the same step navigation path as the sidebar step dots.
- Does not change the diagram math state by itself; it only jumps to the referenced step.

Use it for:

- citing a prior construction or congruence proof;
- reusing an earlier algebraic conclusion such as `a=-3/n`;
- keeping a later step concise without hiding where a result came from.

Avoid it when:

- the cited fact is only one short line away;
- the later step needs the full reasoning repeated for clarity;
- the target step id is not stable across `steps`, `policies`, `stepLabels`, and `step-decorations`.

## Design Principles

- Keep controls faithful to the math constraint. Do not let students move constrained points independently.
- Label controls by geometric meaning, not implementation variables. Use labels like `动点 G：NG/MN`.
- Use local point controls with a local step `domain` when the proof depends on a small auxiliary figure.
- Keep local controls out of algebra-only steps.
- If a local control changes a helper foot or dependent point, override those dependent points too.
- If dependent points are no longer the focus of the current observation, hide or de-emphasize them instead of adding controls for them. The control should match the mathematical degree of freedom students are meant to notice.
- Do not use visible instructional paragraphs to explain the UI. A short `note` is acceptable when it names the invariant or observation.
- Use derivation step references instead of embedding HTML links in JSON.

## Validation

After adding or changing components:

```bash
node tools/validate-geometry-spec.mjs internal/lesson-specs/<problem-id>/
node tools/build-lesson-page.mjs internal/lesson-specs/<problem-id>/
node --check site/assets/js/lesson-page-runtime.js
node --check site/assets/js/geometry-lesson-from-spec.js
```

For regression confidence, validate existing lessons that use the main parameter slider.
