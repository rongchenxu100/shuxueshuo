# Original Figure Principles

Use this reference before writing or revising `geometry-spec.originalFigures` for quadratic-function lessons.

Original figures are source-context diagrams. They should help students recognize the exam picture, not teach a solution step.

## Match The Printed Figure

- If the source problem does not include a printed figure, do not invent an original figure, coordinate sketch, parabola preview, or schematic diagram in `problem.lines`.
- Redraw only what appears in the printed source figure unless the problem text explicitly names a missing construction.
- For quadratic coordinate figures, show coordinate axes, grid marks, curve sketches, and labeled points only when they appear in the printed source figure or are clearly part of the source diagram.
- If the printed source has no grid but does show coordinate axes, use a plain coordinate-axis style rather than a full teaching grid when the renderer supports that distinction.
- Keep point labels complete: every labeled point in the printed figure should appear in `fixedLabels`, `movingLabels`, or `intersectionLabels`.
- Include printed right-angle marks, dashed auxiliary lines, or arrows only when they are present in the source figure.
- Do not add derived coordinates, computed answers, formula labels, colored highlights, angle arcs, helper points, tangent lines, symmetry axes, or auxiliary constructions that belong only to the solution.

## Quadratic-Specific Hygiene

- A printed parabola sketch is not proof of a curve's exact shape. Use it as source context only; put teaching-accurate parabolas in step decorations.
- Do not reveal later results in the original figure, such as the solved second root, vertex, symmetry axis, or final moving-point position, unless the printed figure already labels them.
- If Part I and Part II use different parabolas, do not combine them in one original figure unless the printed source shows both.
- If a problem includes only text, keep `lesson-data.problem.lines` text-only and omit `geometry-spec.originalFigures` entirely.

## Label And Layer Hygiene

- Labels in original figures should be black or neutral unless the printed source uses color.
- Avoid duplicate labels for the same point. If a point would also be labeled by a grid origin, suppress the origin label or omit the duplicate point label.
- Prefer label offsets that match the printed layout when possible.
- Do not hide printed labels just because a point is stored under `movingPoints`; storage location is a data detail, not a visual instruction.

## JSON Checklist

- If `lesson-data.problem.lines[].figures[]` exists, every figure id matches an entry in `geometry-spec.originalFigures`.
- If there is no printed source figure, `lesson-data.problem.lines` contains no `figures` block and `geometry-spec.originalFigures` is omitted or empty.
- `segments` include every printed line segment that is not already adequately represented by visible source geometry.
- `rightAngles` include each printed right-angle marker.
- `fixedLabels`, `movingLabels`, and `intersectionLabels` together include all printed point labels.
