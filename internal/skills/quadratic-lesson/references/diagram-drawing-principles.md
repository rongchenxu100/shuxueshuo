# Diagram Drawing Principles

Use this reference before writing or revising `03_visual_steps.md` and `step-decorations.json` for quadratic-function lessons.

Diagrams are not decoration. Each step diagram should show the mathematical objects that the current derivation uses, has just constructed, or asks students to manipulate.

## Step Relevance

- Draw only what the current step needs. Do not introduce moving-point coordinates, helper points, or auxiliary segments before the derivation uses them.
- Keep each optimization step visually loyal to its immediate goal. If the step is only converting `AM` into `2MN`, do not show unrelated anchors such as a later foot point, vertical helper, or parameter point. If the step is only straightening a broken path, do not show coordinate-computation helpers.
- Do not introduce symbols, fixed points, or helper labels in a diagram before they do work in that step. A definition-only item such as `h=b+3` or a later calculation point `P` belongs in the calculation step, not in the geometric construction step.
- Keep prior constructions visible only when the current derivation still depends on them.
- For local transformation or optimization steps, narrow the active objects and, when helpful, the local `domain`; do not let the full parabola or unrelated context shrink the important construction.
- Do not reveal solved coordinates or values before the step's reasoning has established them.
- Step diagrams must match the current algebraic state, not the final answer. If a step has only established `B(-c/2,0), C(0,c)`, the diagram and coordinate labels must use those symbolic/current points. Locking the diagram to a later value such as `c=-5/2` before that value is derived is a premature reveal, even if the final curve is visually clearer.
- Split layers when a later solved construction would otherwise leak into an earlier step. Use separate `stepStartsWith` layers such as `q1Generic` and `q1Solved`, or move final-value points into only the step that derives them. Do not put final points in a broad section layer shared by earlier steps.
- Do not put final answers or solved special coordinates into a diagram that is meant to support derivation. Labels like `b=2`, `D(4,-5)`, `h=b+3=5`, or final numeric path lengths belong after the proof has reached them, and often do not belong in the diagram at all.
- For calculation diagrams after a path transformation, zoom into the local triangle/segment configuration and label only the quantities used in that calculation. If the derivation uses `DP`, `MP`, `AP`, `∠DMP`, `∠MAN`, and two right angles, omit other labels such as `DN`, coordinates, or repeated final values.
- In final computation diagrams, keep coordinate labels symbolic unless the step's purpose is explicitly to display the final coordinate. For example, prefer `M(b+1/2,−(2b+3)/4)` while solving for `b`; do not label `M(5/2,−7/4)` before or during the equation solving.
- Do not use diagram formula cards for conclusions already visible in the derivation/box area. A formula card is for a spatial relation that would be hard to read from the picture; repeated algebra such as `(6b+9)/4=21/4` or `b=2` usually belongs only in the derivation panel.
- If a diagram label repeats the exact formula already shown in `lesson-data.steps[].derive` or `box`, remove it unless it adds spatial meaning that cannot be read from the derivation text. Prefer point labels, segment lengths, equal marks, angle arcs, and distances over duplicated algebra cards.

## Mark Used Quantities

- If the derivation uses specific coordinates, side lengths, ratios, or angle equalities, mark the important ones in the step diagram when space allows.
- When there are too many values, prioritize in this order: values that unlock the current step, values needed for substitution, then supporting context.
- For equal angles, prefer matching angle-arc labels such as the same Greek letter over a detached text equation.
- Place angle labels visually near the middle of the angle arc. If the shared geometry-label layout pushes labels away from the arc in a crowded local figure, tune the step's `angleArc` fields such as `labelRadius`, `fontSize`, and `lockLabel` before changing shared renderer code.
- For equal segments, use matched visual marks when possible. If the renderer has no tick-mark primitive, use repeated segment labels such as `|` / `||` or concise equality labels, and keep colors consistent across matching segments.
- Mark angle types accurately. If the construction gives a right angle, use a right-angle marker instead of an angle arc labeled `45°`; reserve `45°` arcs for actual acute angles used to identify an isosceles-right triangle.

## Constructed Segments Must Be Visible

- If the solution says a point is chosen so that a segment exists, draw that segment. For example, after taking `G` on ray `CD` with `CG=CB`, the diagram must visibly connect `C` and `G`.
- If a later computation uses a triangle, draw all sides needed to see that triangle. For example, a step using right triangle `OCG` must show `OC`, `CG`, and `OG`.
- Do not rely on a point label or a text card to imply a constructed line segment.
- Draw construction causes before derived facts. For a `30°-60°-90°` auxiliary triangle, show the fixed `30°` ray and right angle as the construction; then label the derived side relation such as `MN=1/2 AM`.
- If an equal-angle condition is converted by an auxiliary point on an axis, draw the auxiliary point, the constructed line, the equal angle arcs, and the equality it creates. For example, if `BM` meets the y-axis at `C'`, show `B-C'`, `B-M`, the matching angles at `B`, and the vertical equality `C'O=CO`.

## Moving Segments And Controls

- When a step asks students to move a point and observe a distance sum, draw the moving segments themselves.
- Avoid replacing moving segments with endpoint-only text labels such as `OM` or `MG`; those labels add no information when the endpoints are already labeled.
- Reserve segment labels for new facts: length values, equalities, ratios, or transformed identities such as `BN=MG`.
- For constrained moving points, use linked local controls so the constraint remains true while students drag or slide. The diagram should make the constrained relation visible.
- In exploratory shortest-path steps, prefer local point controls over a locked "answer" picture. The student should be able to move the point and see why the straightened/collinear state is special.

## Geometric Segment Transformation

- For moving-point distance sums, almost always try the geometric transformation first: use congruent triangles, symmetry, rotation, or an equal-length auxiliary point to convert double-moving-point expressions into single-moving-point path problems before resorting to coordinate distance expansion.
- If the target contains two moving points, look for a construction that converts one moving segment into a segment from the other moving point to a fixed auxiliary point.
- Do not draw or explain vector/scalar projections for middle-school pages. When a proof idea starts from a projection inequality, replace it with a visible auxiliary right triangle, a broken-line path, and a "two points determine the shortest segment" or "垂线段最短" argument.
- For weighted sums, factor first and build the weight into the diagram. Example: turn `2DM+AM` into `2(DM+1/2 AM)`, then construct a `30°-60°-90°` right triangle so `1/2 AM` becomes a real side with endpoint `M`; this gives a path expression that can be straightened geometrically.
- In the straightening step, emphasize the shortest-state condition directly, such as `D, M, N` collinear. Avoid adding perpendicular-foot constructions in that same step unless the proof of shortest path truly depends on the foot. Length-computation helpers belong in the later calculation step.
- Preserve the constructed moving point's name in the shortest state. If the path is `D-M-N`, label the straightened endpoint as `N`, not a new point such as `H`, unless the new point is mathematically distinct and necessary.
- Avoid prose-like formula labels inside the diagram during path-discovery steps. A shortest-path diagram should communicate with geometry: point names, segments, angle marks, and motion. Put statements like `DM+MN≥DN` or `最小值=2DN` in the derivation/box area, or omit the box when it visually crowds the diagram.
- When the endpoint is constrained to a fixed ray/line, the shortest-state diagram or derivation must include the perpendicular condition, for example `DN⊥AN`, in addition to collinearity.
- When the final length can be computed from the straightened configuration, prefer visible triangle relations and segment sums over line equations. The diagram should support equations students can read from the figure.
- Draw only the auxiliary foot points needed for the final computation. If `AN=√2·QN` already determines `QN`, do not add a second perpendicular foot just to recompute `QN`; extra feet make the figure look more advanced and less direct.
- Example: if `M` lies on `BC`, `N` lies on ray `CD`, and `CN=CM`, take `G` on ray `CD` with `CG=CB`. Then `△CBN≌△GCM`, so `BN=MG`, and `OM+BN` becomes `OM+MG`.

## Quadratic-Specific Drawing

- Use `parabola`, `axisOfSymmetry`, `vertex`, and `curvePoint` only when those objects are part of the current visual reasoning.
- For fixed Part I and dynamic Part II parabolas, keep curve visibility separated by step prefixes or sections.
- A parabola can be a quiet background in geometry-heavy steps; constructions, equalities, and moving segments should carry the visual focus.
- For coefficient or angle-solving steps with a small auxiliary construction, use a local `steps[stepId].domain` that frames the construction. Avoid leaving a mostly empty coordinate plane around a tiny triangle or angle marker.
- For coordinate-area steps, draw the actual base and distances used in the formula. In an "铅垂面积" step, show the vertical base such as `CC'` and the horizontal distances from the other vertices to that vertical line; the visual labels should match the area expression in the derivation.
