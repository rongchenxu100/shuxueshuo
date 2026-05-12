# Original Figure Principles

Use this reference before writing or revising `geometry-spec.originalFigures`.

Original figures are source-context diagrams. They should help students recognize the exam picture, not teach a solution step.

## Match The Printed Figure

- Redraw only what appears in the printed source figure unless the problem text explicitly names a missing construction.
- For pure geometry figures, do not draw coordinate grids, axes, origin labels, or x/y labels. Set `showGrid:false` on the original figure.
- For coordinate-geometry figures, show the coordinate grid/axes only when the printed source figure uses them or when the problem statement depends on them.
- Keep point labels complete: every labeled point in the printed figure should appear in `fixedLabels`, `movingLabels`, or `intersectionLabels`.
- If `showMoving:false` is used to suppress a moving polygon or fill, explicit `movingLabels` may still be used for point labels, but make sure this is intentional and validated visually.
- Include printed right-angle marks with `rightAngles`; do not replace them with text labels.
- Do not add derived lengths, computed answers, formula labels, colored highlights, angle arcs, helper points, or auxiliary lines that belong only to the solution.

## Label And Layer Hygiene

- Labels in original figures should be black or neutral unless the printed source uses color.
- Avoid duplicate labels for the same point. If a point would also be labeled by a grid origin, suppress the origin label or omit the duplicate point label.
- Prefer labels outside the figure boundary with small offsets, matching the printed layout when possible.
- Do not hide printed labels just because a point is stored under `movingPoints`; storage location is a data detail, not a visual instruction.

## JSON Checklist

- `lesson-data.problem.lines[].figures[].id` matches an entry in `geometry-spec.originalFigures`.
- Pure geometry original figures include `"showGrid": false`.
- `segments` include every printed line segment that is not already adequately represented by `basePolygon` or the visible moving polygon.
- `rightAngles` include each printed right-angle marker.
- `fixedLabels`, `movingLabels`, and `intersectionLabels` together include all printed point labels.
