# Calculus JSON Schema Guide

The source directory contains `calculus-spec.json`, `calculus-decorations.json`, and `lesson-data.json`. Real schemas under `internal/senior-high/schemas/` are authoritative.

## Calculus Spec

Minimal shape:

```json
{
  "version": 1,
  "id": "problem-id",
  "parameter": { "name": "t", "initial": -1 },
  "bindings": [
    { "name": "m", "expr": "3*t^2-1" }
  ],
  "panels": [
    {
      "id": "curves",
      "title": "Curves and tangent",
      "xLabel": "x",
      "yLabel": "y",
      "viewport": { "x": 0.02, "y": 0.04, "width": 0.6, "height": 0.92 },
      "domain": { "minX": -2, "maxX": 2, "minY": -4, "maxY": 6 }
    }
  ],
  "functions": [
    {
      "id": "f",
      "panelId": "curves",
      "variable": "x",
      "expr": "x^3-x",
      "derivativeExpr": "3*x^2-1",
      "domain": [{ "min": -2, "max": 2 }]
    }
  ],
  "functionPoints": [
    { "id": "P", "functionId": "f", "xExpr": "t" }
  ],
  "tangentLines": [
    { "id": "tangentF", "functionId": "f", "atExpr": "t" }
  ]
}
```

Bindings are evaluated in order. A function's `variable` temporarily replaces the variable of the same name while sampling that function; use a separate symbol such as `u` for an auxiliary graph `h(u)` when `t` is the active slider parameter.

Supported expressions use `+ - * / ^`, parentheses, variables, `sqrt`, `abs`, `exp`, `ln`, `log`, `sin`, `cos`, `tan`, `pi`, and `e`.

## Calculus Decorations

Put stable context in layers and current-step emphasis in `steps[stepId].add`.

```json
{
  "layers": {
    "axes": {
      "elements": [{ "type": "grid", "panelId": "curves" }]
    },
    "function": {
      "elements": [{ "type": "functionCurve", "functionId": "f" }]
    }
  },
  "steps": {
    "q1s1": {
      "add": [
        { "type": "functionPoint", "pointId": "P", "label": "P" },
        { "type": "tangentLine", "tangentId": "tangentF" }
      ]
    }
  }
}
```

Use `panelDomains` for a step-specific mathematical domain. Use `visiblePanels` to remove panels that no longer support the current derivation, and `panelViewports` to expand the remaining panel into the available canvas:

```json
{
  "visiblePanels": ["parameter"],
  "panelViewports": {
    "parameter": { "x": 0.06, "y": 0.04, "width": 0.88, "height": 0.92 }
  }
}
```

Use `signBand` with a function containing `derivativeExpr` and declared roots. Use `rangeBand` only after the range is derived. Keep a moving point in a separate layer from the auxiliary curve so later steps can hide the point without duplicating the curve.

## Lesson Data

Reuse the shared lesson-data schema. Every step needs a matching policy, step label, and calculus decoration entry. A movable policy must declare its finite exploration range even when the mathematical variable ranges over all real numbers.

Set `hideLegend: true` when a focused step hides every panel represented by the shared legend. A step may keep `movable: false` while still declaring `minis`; the runtime lets those representative states update the diagram without exposing a continuous slider.

Classification uses IDs from `internal/senior-high/knowledge-points/calculus-methods.md`.
