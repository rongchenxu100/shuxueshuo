# Quadratic Function Solving Principles

Use these principles when writing `02_solution.md`, planning `03_visual_steps.md`, and deciding what belongs in `step-decorations.json` versus `lesson-data.json` for **二次函数综合题**.

These rules complement, not replace, the general step-design and diagram-content principles in the geometry skill. Only quadratic-specific concerns are written here.

---

## Condition Analysis Before Modeling

- Always extract the axis of symmetry from the "coefficient constraint" before anything else.
  - `2a+b=0` → `b = −2a` → `x = −b/(2a) = 1` (fixed axis, D always at `(1,0)`)
  - `4a+2b+0` or similar — derive axis first, then anchor D.
- If the axis is fixed (does not depend on the moving parameter), put D in `fixedPoints`.
- If coefficients depend on the moving parameter `m`, derive them sequentially in `expressionEnv`: constants first, then expressions that reference `m`, then derived values.
- Never write `a = ...` in `expressionEnv` before all expressions it depends on are already defined.
- When a step only substitutes given coefficient relations or point coordinates to eliminate unknown coefficients and rewrite the parabola, name that step `化简函数表达式`. Use the same wording in `lesson-data.stepLabels` / directory labels, for example `1 化简函数表达式`.
- Do not add a main slider for an unknown coefficient that the problem asks students to solve, such as `a` in `y=ax²+bx+c`. The main slider is for genuine moving/exploration parameters from the problem statement (`m`, `t`, etc.). For coefficient-unknown pages, keep policies non-movable and use a representative solved or default value only to draw the diagram.
- When a fixed x-intercept is given (for example `A(-1,0)`) and another intercept is requested, first simplify/factor the parabola using the known root and coefficient constraints. Prefer `y=(x+1)(2x+c)` or `y=a(x+1)(x+c)` style expressions when they follow directly from the data. Do **not** introduce a fresh unknown such as `B(r,0)` unless the problem genuinely requires an independent parameter that cannot be eliminated from the given coefficients.
- If a later condition determines the coefficient value, keep earlier algebra in the symbolic state. For example, show `B(-c/2,0), C(0,c)` before solving `c=-5/2`; do not rename this as `B(r,0)` or draw the final `B(5/4,0), C(0,-5/2)` in the earlier step.

---

## Derivation Wording and State Discipline

Write `lesson-data.steps[].derive` as board-style mathematical reasoning:

- Prefer left labels `∵`, `∴`, and `作`.
- Avoid lecture-style labels such as `关键观察`, `计算`, `解析式`, `一般结论`, `由...`, or `又...` unless the line would be unclear without a construction verb.
- Split mixed lines into separate cause/effect rows. For example, use `["∵", "m＞2"]` then `["∴", "m＝3"]`, not `["∵ m＞2", "∴ m＝3"]`.
- If a sub-question gives a numerical value such as `m=3` or `n=6`, substitute it at the first step of that sub-question. Do not derive a fully symbolic result and only plug in the value at the end unless the exam explicitly asks for a general conclusion.
- Once a value is solved, later steps must use the solved state. If a step already has `m = 3`, use `N(2,−2)` rather than the earlier general form `N(2,1−m)`.
- Keep `02_solution.md`, `lesson-data.json`, and `step-decorations.json` in the same mathematical state. Do not let JSON fall back to a generic template after the markdown has specialized the problem.
- Do not answer what the problem did not ask. If Part I asks only for `D` and the equation, do not add `C` or vertex conclusions to the solution, box, or diagram.
- Keep diagram choices aligned with `diagram-drawing-principles.md`: show current-step constructions and used quantities, avoid premature reveals, and reserve segment labels for real mathematical information.
- When a step cites a prior derivation, add a declarative step reference in the derive row instead of repeating the whole proof or embedding HTML. Use the third derive item: `{ "refStep": "previousStepId", "refLabel": "回看..." }`.
- Remove definition-only or repeated derive rows once the fact is already active in the immediately preceding step. For example, do not start an angle-construction step with `BO=4CO` if the previous step has already converted that condition into `B` and `C` coordinates.
- Keep simple sub-questions compact. If a computation only substitutes given coefficients and takes a vertex formula, one well-named step is enough; do not split it merely to mirror every algebra line.

---

## Two-Sub-Question Pattern (Fixed Part I + Dynamic Part II)

Many problems give a specific `a` and `c` for Part I, then make `a`, `b`, `c` depend on `m` for Part II.

**Do not try to unify both under one parabola.** Instead:

1. Define `a1`, `b1`, `c1` (constants) at the top of `expressionEnv`.
2. Define `a`, `b`, `c` (m-dependent) after them.
3. Add two curves in `geometry-spec.curves`:
   - `parabolaPart1`: references `a1`, `b1`, `c1`
   - `parabolaMain`: references `a`, `b`, `c`
4. In `step-decorations.json`, use `stepStartsWith` to show each curve only in the relevant sub-question:
   - `partI` layer: `"stepStartsWith": ["i1"]` → shows `parabolaPart1`
   - `partII` layer: `"stepStartsWith": ["q0","q1","q2"]` → shows `parabolaMain`

---

## Geometric Constructions on the Parabola

### Prefer Geometric Segment Transformations

For quadratic comprehensive problems with moving-point distance sums, prefer a geometric segment transformation before coordinate or algebraic minimization. See `diagram-drawing-principles.md` for the diagram requirements and examples.

Before writing a coordinate parameterization or algebraic inequality solution for any weighted distance sum, add a route gate:

1. Identify every weight in the target expression, such as `2`, `1/2`, `√2`, or `√3`.
2. Try to absorb each weight with a visible middle-school construction first:
   - `√2·BH` suggests an isosceles right triangle using `BH` as a leg or converting another segment into `√2` times a leg.
   - `2AH` suggests factoring the whole expression, using a doubled segment, or constructing a proportional segment before optimizing.
   - A point constrained to a line segment, line, or ray suggests broken-line shortest path, reflection, rotation, or perpendicular-distance-to-a-line.
3. Sketch the intended auxiliary point(s), transformed segment(s), and shortest-state condition before committing to the solution route.
4. Only if the weights cannot be made into one coherent visible path may you switch to coordinate distances, square-root inequalities, or single-variable minimization.

If the final solution does not use a geometric segment transformation, say why in `02_solution.md` or `03_visual_steps.md` before the algebraic minimization step. Do not list `weighted-path-segment-transform`, `isosceles-right-triangle-transform`, or `horse-drinking` in `lesson-data.meta.classification.methods` unless the page actually contains that geometric transformation in the derivation and diagram.

For middle-school student-facing solutions, do **not** use vector projection, scalar projection, or "the projection of a segment onto a direction" to prove a distance lower bound. If a weighted expression such as `2DM + AM` appears, first factor the common coefficient and convert the fractional segment into a visible auxiliary segment, for example

`2DM + AM = 2(DM + 1/2 AM)`.

Then construct a right triangle (often a `30°-60°-90°` triangle) so the new segment is an actual side of the diagram. After that, use broken-line shortest path, reflection, rotation, or perpendicular-distance-to-a-line arguments that can be seen on the figure.

In the weight-conversion step, fill the triangle or quadrilateral that performs the conversion with a light translucent color. For example, fill `△BHR` when converting `√2BH` to `2HR`, or fill the special right triangle that turns `1/2 AM` into a real segment. Keep the fill quiet, but make the conversion object visually unmistakable.

When constructing a special right triangle, state the intended geometric constraints first, then derive the length relation. For example, if the goal is to make `1/2 AM` into a segment, construct `N` on the fixed ray from `A` that makes a `30°` angle with the axis, with `∠ANM=90°`; then conclude `MN=1/2 AM`. Do not present the derived side relation as if it were the construction condition unless the problem explicitly defines it that way.

Avoid redundant "definition-only" derive rows when the symbol is not yet needed. For example, do not introduce `h=b+3` in the triangle-construction step if that step only transforms `2DM+AM` into `2(DM+MN)`. Introduce `h`, `P`, or other calculation aids only in the later computation step where they are used.

Do not leak solved or later-stage values into earlier steps. If a later step will prove `b=2` and hence `D(4,-5)`, earlier construction and path-transformation steps should label the point only as `D`, or use the still-symbolic form only when it is actually part of the current derivation. Avoid graph labels such as `D(4,-5)`, `b=2`, or final numeric distances before the calculation step establishes them.

For a weighted path such as `2DM + AM`:

1. Factor the target: `2DM + AM = 2(DM + 1/2 AM)`.
2. Construct a `30°-60°-90°` right triangle with `AM` as the hypotenuse so the side ending at `M` equals `1/2 AM`.
3. Convert the target to a broken-line path such as `2(DM + MN)`.
4. Find the shortest state by straightening the broken line: the key visual condition is often `D, M, N` collinear, not an abstract inequality.
5. If the straightened endpoint is constrained to a fixed line or ray, add the required shortest-to-line condition, such as `DN⊥AN`, before computing. The shortest state may require both collinearity and perpendicularity.
6. Only after the shortest state is identified, compute the length from the resulting triangles. Prefer right-triangle similarity, `30°-60°-90°` ratios, and segment equations (for example `DP = DM + MP` or `DP = AM + MP` when the collinearity/order supports it) over coordinate line equations.

Keep the geometry and calculation phases separate. A step whose purpose is to discover the shortest path should show the straightened path and collinearity condition. A later step may compute the final length; do not overload the discovery step with coordinate equations or extra helper points if the straight-line condition already explains why the path is shortest.

In horse-drinking or broken-line-shortest steps, fill the path-comparison triangle or quadrilateral with a light translucent color. For example, fill `△AHR` when comparing `AH+HR` with `AR`. Remove routine side-name labels if the fill and endpoints already communicate the path; keep only labels that add new mathematical information.

For interactive pages, split the optimization into two states when possible: an observation state with local controls for the moving point, and a calculation state locked to the optimal configuration. The observation state should support the inequality or collinearity idea; the calculation state may mark final lengths, special triangles, and final coordinates.

### Hidden Circle Minimum

When a moving point satisfies a right-angle condition such as `∠OHB=90°`, first test for a hidden circle: the moving point may lie on the circle with the fixed segment as diameter.

Preferred middle-school route:

1. Identify the fixed diameter and write the circle center and radius.
2. State the actual arc or quadrant where the moving point lives.
3. Convert the minimum distance from a fixed point to the circle into `center distance − radius`.
4. Check side/axis cases before solving the coefficient; for example, if `OB=OC` and `C` is only said to be on the `y` axis, consider both `C(0,m)` and `C(0,−m)`.

Diagram requirements:

- Draw the full hidden circle with a light fill, then emphasize the permitted arc.
- Add a local control for the point moving on the circle, defaulting to the shortest position.
- Show the center, radius, fixed point, center-to-fixed-point segment, and shortest segment.
- Do not list this as `horse-drinking`; use `hidden-circle-minimum` because the model is circle distance, not broken-line straightening.

Keep moving-point names continuous through the optimization. If `N` is the constructed moving point, the shortest state should still be described as `D, M, N` collinear. Do not rename the limiting/optimal position as a new point such as `H` unless a genuinely new object is needed for a separate construction. Extra names make students track a point switch instead of the path idea.

For exploratory "将军饮马" steps, add a local control for the moving point whenever the construction is dynamic. Let students drag the point and see the path become straight. Keep formulas in the derivation panel; the diagram should mostly use points, segments, angles, and possibly short point labels.

When introducing a computation foot point, describe the geometric construction before any coordinate form. Prefer `作 DP⊥x轴，垂足为 P` over `P(b+2,0)` when the perpendicular relationship is what the calculation uses.

When a shortest-path transformation creates a 45° fixed ray, compute the final minimum with visible isosceles-right triangles when possible instead of using the point-to-line distance formula. For example, after turning `√2 MN + AN` into `√2(MN + QN)` by constructing an isosceles right triangle `AQN`, and after the shortest state gives `Q、N、M` collinear with `MQ ⟂ AQ`, draw only the foot actually needed, such as `MH ⟂ x轴`. Use the 45° isosceles right triangle to read `MN`, then use the already-established relation `AN=√2·QN` to compute `QN` directly. Avoid extra feet such as `QR` when `QN` can be found from `AN`.

### Trigonometry In Middle-School Coordinate Problems

When a quadratic problem uses `tan` or an angle sum involving `45°`, keep the method inside right triangles.

- Use only the definition `tan A = opposite leg / adjacent leg` in a right triangle.
- Do not use tangent subtraction/addition formulas such as `tan(45°−A)`.
- Do not use the tangent formula for the angle between two slopes.
- If the condition is like `∠CBE + ∠ACO = 45°`, look for a known `45°` angle in the diagram, then construct an auxiliary point so the target angle equals a right-triangle angle. For example, if `BE` meets `OC` at `F` and `∠OBC=45°`, then `∠OBF=∠ACO`; compute `OF` from `tan∠OBF=OF/OB`.
- After the auxiliary point is found, use line equations and parabola intersections to locate the required point.

### Equal-Angle Line Through An Axis Intercept

When a condition such as `∠ABM=∠ABC` determines a line through an x-axis point `B`, avoid presenting the first move as "the slope is ...". Prefer this middle-school construction:

1. Let the unknown line meet the y-axis at an auxiliary point, often `C'`.
2. Use the equal angle and quadrant/side condition to decide whether `C'` lies above or below the x-axis.
3. Read a vertical equality from the reflected/equal-angle right triangles, such as `C'O=CO`.
4. Write the coordinate of `C'`, then use the two known points `B` and `C'` to get the line expression.

This keeps the derivation visible on the diagram and avoids making slope the conceptual reason for the line. It is fine to compute the line from two points after the construction has located `C'`.

### Coordinate Triangle Area

Before using a determinant-style area formula, check whether the triangle can be split by a vertical or horizontal auxiliary segment.

- If a vertex or constructed point lies on the y-axis, try using a vertical base such as `CC'`.
- If the opposite vertices are on different sides of that vertical line, write the area as the sum of two triangles:
  `1/2·vertical base·left horizontal distance + 1/2·vertical base·right horizontal distance`.
- Mark the vertical base and the two horizontal distances in the diagram. The equation in the derivation should mirror those labels.
- Use determinant area only when no simple vertical/horizontal split is readable or when the problem source explicitly expects it.

### Axis-Parallel Segment Conditions To Coordinates

When a problem gives horizontal or vertical segment relations in a coordinate-parabola setting, prefer converting the segment relation into a point coordinate before substituting into the parabola.

- Keep public/common-conclusion steps minimal. Record only values later reused, such as `NI=7a`; do not compute a complete intersection expression such as `MH=√(16+2/a)-4` if the later solution never uses it.
- If a later condition determines an axis-parallel segment, read the coordinate directly. For example, from `15NI−7MH=7` and `NI=7a`, get `MH=15a−1`; with `M(3,5)` and `H` to the right on the horizontal line, write `H(15a+2,5)`.
- Substitute that point directly into the parabola. Prefer a line such as `5=a(15a+2)^2+2a(15a+2)+3−15a` and then factor by observing `−15a−2=−(15a+2)`.
- Avoid introducing an unnecessary variable such as `x_H` when the coordinate can be written immediately.
- Avoid solving square-root equations or high-degree equations created only by expanding an unused intersection formula.

Diagram and step-label discipline:

- In the common step, show only the reused point/segment, such as `I(2,3−7a)` and `NI=7a`.
- In the solving step, introduce and label the newly determined coordinate, such as `MH=15a−1` and `H(15a+2,5)`.
- Update `stepLabels`, step titles, and reference buttons to the same knowledge grain: `表示NI` should not remain `表示NI与MH` after the `MH` expression is removed.
- Do not draw or label unused root expressions in the diagram.

### ∠MDN = 90°, DM = DN Pattern

The most common construction: M is on the parabola, D is fixed (often the axis–x-axis intersection), N is in a specified quadrant with ∠MDN = 90° and DM = DN.

**Preferred middle-school derivation path (right-triangle congruence):**

1. Drop perpendiculars from the known point and the unknown point to a convenient axis or fixed line through `D`.
2. Name the feet clearly, so students can read two right triangles from the diagram.
3. Use `∠MDN = 90°` and `DM = DN` to prove the two right triangles are congruent (or isosceles-right related).
4. Transfer the two leg lengths from the known triangle to the unknown triangle.
5. Use the required quadrant/side condition to decide the signs and final coordinates of `N`.
6. Then verify `N` is on the parabola using the coefficient expressions.

This is preferred over vector rotation in student-facing solution text because it stays on the original diagram and uses familiar congruent-triangle reasoning.

### Segment Rotation Around a Coordinate-Axis Point

When a segment such as `AC` is rotated 90° around a point on an axis, do not use vectors in the student-facing solution. Middle-school pages should construct a right triangle and prove congruence.

For a condition like `∠CBD=90°` and `BC=BD` with `B` on the x-axis and `C` on the y-axis, prefer drawing the foot `DQ ⟂ x轴` and proving `Rt△CBO≌Rt△BDQ` to read the coordinates of `D`. Do not present vector rotation as the main derivation.

Preferred pattern:

1. If the sub-question gives `m` or another parameter value, substitute it immediately.
2. Draw the rotated segment endpoint `D`, then drop a perpendicular from `D` to the relevant axis or known line. For example, if `C` is on the `y` axis, draw `DG ⟂ OC` with `G` on `OC`.
3. Compare the original right triangle and the new right triangle, such as `△AOC` and `△CDG`.
4. Use rotation to state the equal hypotenuse/angle relation, then prove the two right triangles congruent.
5. Transfer leg lengths to obtain the coordinate of `D`.

For example, with `A(-3,0)` and `C(0,9)`, draw `DG ⟂ OC`. From `△AOC≌△CDG`, get `CG=3` and `DG=9`, so `G(0,6)` and `D(9,6)`.

For a coefficient-dependent coordinate example, if `a=2`, `A(-1,0)` lies on `y=2x²-bx+c`, `C` is the y-axis intercept, and `∠CAD=90°`, `AC=AD`, first use `A` to get `c=-b-2` and `C(0,-b-2)`. Then draw `DH ⟂ x轴`, prove `Rt△AOC≌Rt△DHA`, transfer `AH=OC=b+2` and `DH=AO=1`, so `D(b+1,1)`. Only after this geometric coordinate step, substitute `D` into the parabola to solve the coefficient and final coordinate. This is preferred over listing coordinate-rotation candidates such as `D(b+1,1)` and `D(-b-3,-1)` without the triangle argument.

**Optional agent-side check (not the main student explanation):**

- You may use coordinate rotation or vectors internally to verify coordinates quickly.
- Do not present the vector method as the primary solution for a middle-school page unless the source problem or user explicitly asks for coordinate-vector reasoning.
- Never guess `N`'s coordinates; always show either the congruent-triangle leg transfer or another visible geometric justification.

### M on Parabola → Coefficient from m

After establishing N's coordinates, substitute both M and N into `y = ax² + bx + c` to derive the coefficient(s) as rational functions of m. Typical chain:

1. Substitute N → derive c in terms of m.
2. Substitute M → derive an equation in a and m (using b = f(a)), solve for a.
3. Then b and c follow.

Show each substitution step separately. Do not skip from "N on parabola" to "a = 1/(m−2)" in one line.

### Axis Symmetry + Difference Maximum Pattern

When `P` lies on the parabola's axis of symmetry and the target is a difference such as `PB - PM`, first check whether `A` and `B` are symmetric about that axis.

Preferred middle-school path:

1. Use roots `A` and `B` to state the axis is the perpendicular bisector of `AB`.
2. Since `P` lies on the axis, convert `PB` to `PA`.
3. Then `PB - PM = PA - PM`.
4. Apply the triangle inequality in `△APM`: `PA - PM ≤ AM`.
5. The maximum occurs when `A, P, M` are collinear and `P` lies on the correct side so that `PA = PM + AM`.
6. Compute `AM` from the coordinates, then use the given maximum to solve the parameter.

Do not expand both distances into nested radicals unless the symmetry route is unavailable. The symmetry route is shorter, more visual, and closer to a 将军饮马 transformation.

Diagram style for this pattern:

- Fill the target triangle, usually `△APM`, with `outlineRegion` and `style: "horseTriangle"`.
- Draw the comparison segments `PA`, `PB`, `PM`, and the bound segment `AM`, but do not label them with endpoint-only names.
- Keep necessary source context, such as parallelogram `MFDB` when it determines `M`, in a quieter color than the target triangle.

---

## Path Optimization (EG + FG Type)

### Setup

- E is on segment DM, G is on segment MN, F is a fixed or derived point (often midpoint of DN).
- A constraint links E and G: e.g., `DE = √2 · NG`.
- These are middle-school problems: do **not** use calculus, derivatives, or "critical point" language. Prefer geometric transformations on the original diagram.

### Key Observation — Turn EG into DG First

When `∠MDN = 90°` and `DM = DN`, `△DMN` is an isosceles right triangle and `MN = √2·DM`.

For a point `G` on `MN`, prove `EG = DG` before minimizing:

1. Through `G`, draw `GH ⟂ DN`, with `H` on `DN`.
2. Since `∠DNM = 45°`, `△GNH` is isosceles right, so `GH = NH = NG/√2`.
3. Draw `GK ⟂ DM`, with `K` on `DM`. Because `DM ⟂ DN`, `D-K-G-H` is a rectangle, so `DK = GH` and `GK = DH`.
4. From `DE = √2·NG = 2GH`, get `EK = DE - DK = GH = DK`.
5. Since `GK ⟂ DM` and `D、E、K` are collinear on `DM`, `GK` is the perpendicular bisector of `DE`.
6. Therefore `△DGE` is isosceles, so `EG = DG`.

This keeps the reasoning on the original diagram and avoids abstract projection language.

**Diagram requirements for this transformation:**

- The diagram must show `DG` when claiming `EG = DG`.
- The diagram must also show `EG` during the proof step, because the equality compares `EG` and `DG`.
- The auxiliary feet used in the proof, such as `H` and `K`, must be drawn and labeled.
- Mark the right angles at `H` and `K` when using `GH ⟂ DN` and `GK ⟂ DM`.
- In this transformation step, remove distracting coordinate labels; point names plus the critical helper lines are enough.
- Avoid showing `EG` as the visual focus after the goal becomes `EG + FG = DG + FG`.
- Use a local step `domain` for transformation/proof diagrams when only the auxiliary construction matters. Do not let a far-away later point or the whole parabola shrink the important local shape.
- If a transformation proof depends on movable points, add local point controls so students can drag the construction and observe the invariant. When the points are constrained, expose linked controls instead of independent sliders. For example, if `DE = √2·NG` in an isosceles-right setup, `E` and `G` share one source variable; moving either control should keep the constraint true.

### General's Horse-Drinking / Reflection Step

After `EG = DG`, minimize:

`EG + FG = DG + FG`

Complete the square on sides `DM` and `DN`: let `D' = M + N - D`. Then `DMD'N` is a square, and diagonal `MN` is the perpendicular bisector of `DD'`, so for any `G` on `MN`:

`DG = D'G`

Thus:

`EG + FG = D'G + FG ≥ D'F`

The minimum occurs when `D'、G、F` are collinear.

**Diagram requirements for the reflection step:**

- Construct `D'` as the fourth vertex of the square on sides `DM` and `DN`.
- Draw `MD'` and `ND'` to make the square visible.
- Draw `D'F` as the shortest straight segment.
- Keep `DG` visible as the bridge from `DG + FG` to `D'G + FG`.
- Do not label every coordinate in this step; the visual priority is the shortest-path transformation.
- Check the global `geometry-spec.domain` includes `D'` at every locked parameter value used by the lesson. For example, if a later sub-question locks at `m=8`, then `D'=(9,−6)` must be inside the visible domain or the square will silently disappear/crop.
- For the reflection step itself, prefer a local step `domain` that frames the square and shortest segment closely. Students should see the relation `DG = D'G` and `D'G + FG ≥ D'F`, not a large mostly-empty coordinate plane.
- For the reflection step, add a single local control for `G` on the mirror line when the minimum is about one moving point. Students should be able to drag `G` and see that the shortest state occurs when `D'、G、F` are collinear.

### Finding the Final G Coordinate

When the shortest state gives `D'、G、F` collinear and `G` lies on another segment such as `MN`, avoid presenting vector section formulas as the main student-facing method.

Preferred middle-school path:

1. State that `G` is the intersection of `MN` and `D'F`.
2. Use the two endpoint coordinates on `MN` to write the line expression.
3. Use the two endpoint coordinates on `D'F` to write the line expression.
4. Solve the two linear equations simultaneously to get the intersection point `G`.

This keeps the reasoning inside line expressions / slope ratios, which is easier for middle-school students than `G = N + k(M-N)`.

### Closed-Form Minimum

Because `F` is the midpoint of `DN`, in the square with side length `DM`, compute the final distance from side lengths rather than introducing `D'` coordinates:

`D'F = (√5/2)·DM`

and in the `D=(1,0), M=(m,1)` setting:

`DM = √(m² − 2m + 2)`

so:

`min(EG + FG) = (√5/2) · √(m² − 2m + 2)`

in the `D=(1,0), M=(m,1)` setting. This closed form is the key result for Part ②. Equate it to the given value and solve for m.

### Showing E and G on the Diagram

At the minimum, `D'、G、F` are collinear and `G` divides `MN` from `N` to `M` in the ratio `1:2`, so:

```json
"E": ["(2*m+1)/3", "2/3"],
"G": ["(m+4)/3",   "(3-2*m)/3"],
"Dprime": ["m+1",  "2-m"]
```

This lets the diagram show E and G at the optimum position for each slider value of m.

---

## expressionEnv Ordering Rules

`expressionEnv` is evaluated top-to-bottom, each entry updating the shared `env` object. Violating order causes "unknown ident" errors.

Correct order for the two-curve pattern:

```json
"expressionEnv": [
  { "name": "a1", "expr": "2"          },
  { "name": "b1", "expr": "-4"         },
  { "name": "c1", "expr": "-5"         },
  { "name": "a",  "expr": "1/(m-2)"    },
  { "name": "b",  "expr": "-2/(m-2)"   },
  { "name": "c",  "expr": "1-m"        }
]
```

- Constants first.
- Never reference `a` before `a` is defined.
- If `c` depends on `a`, define `a` first.

---

## Slider and Policy Design

- Part I steps are usually computed at a specific numerical value of `a`. Lock them with `"movable": false, "range": [x, x]` where `x` is any safe value (e.g., `3.5`) in the valid domain (`m > 2` strictly).
- Do not lock at a value that causes division by zero in `expressionEnv` (e.g., `m=2`). Use `m ≥ 2.5` as the minimum safe value.
- For Part II steps that have a specific answer (e.g., `m=3` or `m=8`), lock the slider at that value to show the exact state.
- For exploratory steps, use `"movable": true` with a range covering the valid domain.

---

## Step Design for Quadratic Problems

- **Part I algebra** (finding D, writing the equation): one or two locked steps, diagram shows only requested objects and the fixed parabola.
- **Part I algebra** should only include requested results. If the problem does not ask for the y-intercept point or vertex, do not add them.
- **Do not create a separate “Part II setup” section by default.** Put preparatory work inside the sub-question that needs it.
- **Part II sub-question with a specific condition** can use this sequence: determine `N` geometrically → solve the parameter and equation → transform the line-sum → apply shortest-path/reflection and merge the final answer.
- **Coordinate steps** may show exact coordinates. **Optimization/transformation steps** should show point names, helper feet, and key segments rather than coordinate labels.
- **Optimization/transformation diagrams may use a local step domain.** If the proof only uses a local auxiliary figure, zoom to that region so helper feet, equal segments, and reflection lines are legible.

Use method-based titles: `用全等三角形确定 N 的坐标`, `求 m、M、N 与抛物线解析式`, `把两动点问题转化为单动点问题（EG+FG→DG+FG）`, `用将军饮马求最小值并合并答案`, `由最小值反推 m 值`.

---

## Wording Checklist (Quadratic)

- Is the axis of symmetry derived before any conclusion about D?
- Is b derived from a using the constraint before substituting M into the parabola?
- Is the rotation direction (clockwise/counter-clockwise) explicitly stated?
- Is N's quadrant verified after computing N?
- Is `EG = DG` proved with an auxiliary-line argument before applying the shortest-path idea?
- Is `D'` constructed as the fourth vertex of the square on `DM` and `DN`, so `D` and `D'` are symmetric about diagonal `MN`?
- Is the minimum explained as `D'G + FG ≥ D'F`, without calculus?
- Are helper feet such as `H` and `K` drawn and labeled when they are used in the proof?
- Are optimization diagrams free of unnecessary coordinate labels and distracting segments?
- After solving a value like `m = 3`, do all later equations and labels use the specialized coordinates?
- Are E and G expressed as `movingPoints` (functions of m only)?
- Are Part I and Part II using separate curve ids in `geometry-spec.curves`?
- Do layer `stepStartsWith` arrays correctly isolate Part I vs Part II curves?
- Is the minimum EG+FG formula verified at the specific m value from the sub-question?
