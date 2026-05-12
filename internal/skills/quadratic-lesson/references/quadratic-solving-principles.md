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

### Trigonometry In Middle-School Coordinate Problems

When a quadratic problem uses `tan` or an angle sum involving `45°`, keep the method inside right triangles.

- Use only the definition `tan A = opposite leg / adjacent leg` in a right triangle.
- Do not use tangent subtraction/addition formulas such as `tan(45°−A)`.
- Do not use the tangent formula for the angle between two slopes.
- If the condition is like `∠CBE + ∠ACO = 45°`, look for a known `45°` angle in the diagram, then construct an auxiliary point so the target angle equals a right-triangle angle. For example, if `BE` meets `OC` at `F` and `∠OBC=45°`, then `∠OBF=∠ACO`; compute `OF` from `tan∠OBF=OF/OB`.
- After the auxiliary point is found, use line equations and parabola intersections to locate the required point.

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

Preferred pattern:

1. If the sub-question gives `m` or another parameter value, substitute it immediately.
2. Draw the rotated segment endpoint `D`, then drop a perpendicular from `D` to the relevant axis or known line. For example, if `C` is on the `y` axis, draw `DG ⟂ OC` with `G` on `OC`.
3. Compare the original right triangle and the new right triangle, such as `△AOC` and `△CDG`.
4. Use rotation to state the equal hypotenuse/angle relation, then prove the two right triangles congruent.
5. Transfer leg lengths to obtain the coordinate of `D`.

For example, with `A(-3,0)` and `C(0,9)`, draw `DG ⟂ OC`. From `△AOC≌△CDG`, get `CG=3` and `DG=9`, so `G(0,6)` and `D(9,6)`.

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
