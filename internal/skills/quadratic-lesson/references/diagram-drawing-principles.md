# Diagram Drawing Principles

Use this reference before writing or revising `03_visual_steps.md` and `step-decorations.json` for quadratic-function lessons.

Diagrams are not decoration. Each step diagram should show the mathematical objects that the current derivation uses, has just constructed, or asks students to manipulate.

## Step Relevance

- Draw only what the current step needs. Do not introduce moving-point coordinates, helper points, or auxiliary segments before the derivation uses them.
- Keep prior constructions visible only when the current derivation still depends on them.
- For local transformation or optimization steps, narrow the active objects and, when helpful, the local `domain`; do not let the full parabola or unrelated context shrink the important construction.
- Do not reveal solved coordinates or values before the step's reasoning has established them.

## Mark Used Quantities

- If the derivation uses specific coordinates, side lengths, ratios, or angle equalities, mark the important ones in the step diagram when space allows.
- When there are too many values, prioritize in this order: values that unlock the current step, values needed for substitution, then supporting context.
- For equal angles, prefer matching angle-arc labels such as the same Greek letter over a detached text equation.
- For equal segments, use matched visual marks when possible. If the renderer has no tick-mark primitive, use repeated segment labels such as `|` / `||` or concise equality labels, and keep colors consistent across matching segments.

## Constructed Segments Must Be Visible

- If the solution says a point is chosen so that a segment exists, draw that segment. For example, after taking `G` on ray `CD` with `CG=CB`, the diagram must visibly connect `C` and `G`.
- If a later computation uses a triangle, draw all sides needed to see that triangle. For example, a step using right triangle `OCG` must show `OC`, `CG`, and `OG`.
- Do not rely on a point label or a text card to imply a constructed line segment.

## Moving Segments And Controls

- When a step asks students to move a point and observe a distance sum, draw the moving segments themselves.
- Avoid replacing moving segments with endpoint-only text labels such as `OM` or `MG`; those labels add no information when the endpoints are already labeled.
- Reserve segment labels for new facts: length values, equalities, ratios, or transformed identities such as `BN=MG`.
- For constrained moving points, use linked local controls so the constraint remains true while students drag or slide. The diagram should make the constrained relation visible.

## Geometric Segment Transformation

- For moving-point distance sums, almost always try the geometric transformation first: use congruent triangles, symmetry, rotation, or an equal-length auxiliary point to convert double-moving-point expressions into single-moving-point path problems before resorting to coordinate distance expansion.
- If the target contains two moving points, look for a construction that converts one moving segment into a segment from the other moving point to a fixed auxiliary point.
- Example: if `M` lies on `BC`, `N` lies on ray `CD`, and `CN=CM`, take `G` on ray `CD` with `CG=CB`. Then `△CBN≌△GCM`, so `BN=MG`, and `OM+BN` becomes `OM+MG`.

## Quadratic-Specific Drawing

- Use `parabola`, `axisOfSymmetry`, `vertex`, and `curvePoint` only when those objects are part of the current visual reasoning.
- For fixed Part I and dynamic Part II parabolas, keep curve visibility separated by step prefixes or sections.
- A parabola can be a quiet background in geometry-heavy steps; constructions, equalities, and moving segments should carry the visual focus.
