# Geometry Solving Principles

Use these principles when writing `02_solution.md`, planning `03_visual_steps.md`, and deciding what belongs in `step-decorations.json` versus `lesson-data.json`.

This file is the compact teaching-quality reference. It should preserve the high-value rules from the old all-in-one skill without pulling renderer or HTML implementation details back into the skill.

## Step Design

- Keep cognitive load low: one step should do one main thing.
- Prefer `观察 -> 构造 -> 计算 -> 结论`.
- Restart step numbering inside each sub-question, such as `第（I）问 Step 1/2` and `第（II）①问 Step 1/2/3`.
- Use method-based titles in the form `方法 + 目标量`, such as `由直角三角形求 DG`, `由线段差求 CG`, `由边界位置判断范围`.
- Step titles must name the specific target object or quantity, such as `由边长判断 △G′F′H′ 为等边三角形` instead of `由边长判断等边三角形`.
- When two adjacent steps use the same method on different objects, the title must distinguish the objects, such as `判断 △G′F′H′` versus `判断 △G′MN`.
- Navigation labels may be shorter than full step titles, but they still need an action and object, such as `判等边△G′MN` or `求△G′MN面积`; avoid labels like `判G′MN` or `左侧范围` that require guessing.
- Use a title like `参数状态 + 方法 + 目标` only when the step is explicitly about a special parameter value, boundary state, or case split.
- Avoid weak titles such as `先求...`, `观察...`, or vague titles such as `由图形关系求...`.
- Step titles must match the visual step. Do not write `构建...` unless that step really introduces a new auxiliary construction.
- If a step mixes boundary-state judgment, boundary-value solving, and final interval writing, split it.

## Reasoning Style

- Use given conditions directly before introducing derived quantities.
- Before using similarity, trigonometric ratios, coordinates, or algebraic parameters, scan for a one-step geometric theorem triggered by the givens: perpendicular bisector, angle bisector, median to hypotenuse, isosceles triangle, parallel lines, or complementary angles.
- If a target is an angle, prefer angle chasing through equal angles and complementary/supplementary angles before setting up side ratios or formulas.
- When a point is the midpoint of a segment and another given line is perpendicular to that segment at the midpoint, immediately consider the perpendicular-bisector conclusion and the resulting isosceles triangle.
- Reuse named points from the problem statement instead of redefining them.
- Reuse conclusions from earlier sub-questions instead of re-deriving them.
- Prefer familiar middle-school geometry before analytic coordinates: right triangles, perpendiculars, equal segments, angle equality, rotations, folds, and similar triangles.
- Coordinates are acceptable when they are the clearest route, but they should not replace an easier geometric idea.
- Before finalizing a solution path, try two or three plausible routes and choose the one with the fewest new symbols, the most visible diagram relationship, and the least algebra for a Grade 9 student.
- Prefer a standard-shape route when available: equilateral triangles, isosceles right triangles, 30°-60°-90° triangles, rectangles, rhombi, parallel-line cuts, and similarity should be checked before coordinate-heavy derivations.
- If a line cuts a standard triangle parallel to one side, first ask whether the smaller triangle keeps the same standard shape; this often gives a friendlier height/area route than computing the cut segment directly.
- Use coordinates as supporting evidence for a familiar shape or simple distance, not as the default main narrative when the diagram already contains a recognizable geometric structure.
- When a coordinate-intersection route and a geometric-standard-shape route both solve the same target, prefer the geometric route for middle-school lessons if it can be seen on the diagram. For example, use `OM=1/2` and `△MO′N` as an isosceles right triangle to get `O′N`, instead of first solving the coordinates of `N`.
- A student-friendly route usually has this shape: identify one familiar local figure, derive one or two key lengths or angles, then finish with a short calculation. A less student-friendly route often introduces line equations, solves an intersection, and only afterward interprets the result geometrically.
- Use analytic coordinate work as the main route only when no visible standard shape, equal-angle relation, parallel cut, similarity, or simple length difference gives the target with less symbolic load.
- Split any sentence with multiple reasoning jumps.
- Avoid `显然`, `容易得到`, `同理可得`, and vague phrases such as `代入折叠关系`.
- Use mathematical notation for calculations and formulas, but use classroom language for boundary states and positional descriptions.
- Do not restate visually obvious collinearity or on-line facts unless they are a real logical bridge.
- Delete premise lines that merely repeat the problem statement or what the current diagram already labels, unless the line is needed as the immediate reason for the next conclusion.

## Angles And Triangles

- When a given angle can be used directly in the current triangle, use that original angle statement instead of renaming it through extra intermediate angles.
- Avoid redundant re-proofs that only rename the same right angle or known angle with different letters.
- For 30°-60°-90° helper triangles, identify the right angle and 30° or 60° angle, then use the side-ratio relation directly.
- Avoid coordinate projection when a standard right triangle gives the needed length cleanly.
- For right-triangle area steps, state the exact base and height used.
- If a labeled segment is the hypotenuse of an isosceles right triangle, either derive the legs first or use a student-friendly formula such as `斜边为 c 的等腰直角三角形面积为 c²/4`.

## Rotation And Local Coordinates

- For rotation-generated moving triangles, do not introduce full coordinates for every moving vertex by default.
- If the target is a segment length, range, or overlap shape, first try rotation angles, right triangles, similar triangles, and line-segment differences.
- If a local coordinate calculation makes one helper length clearer, compute only the needed nearby point or segment, then return to geometric reasoning.
- Avoid setting up a full coordinate system for the whole moving figure when only one local segment such as `ME` is needed.

## Folding And Reflected Regions

- In folding problems, compute the real folded paper piece before deciding what to draw. Do not use visibility switches to hide a geometrically wrong folded figure.
- The folded figure may change shape when the fold line starts or stops cutting a different side. Treat those transition values as phase boundaries.
- Do not extend a later-stage folded polygon backward into an earlier phase. For example, if the fold line first cuts a slanted side at `R`, the folded piece may be a triangle such as `P-O′-R`; only after the fold line reaches the top edge should a quadrilateral such as `P-O′-A′-Q` appear.
- The trend step, thumbnails, main diagram, and overlap-area calculation must all use the same real folded polygon for the same parameter value.
- When the folded piece changes shape by interval, define the moving region with interval-specific polygons, such as `movingPolygons`, instead of one static `movingPolygon`.
- If an apparent extra small triangle appears in a trend diagram, first check whether the folded polygon is being over-extended past the actual fold intersection. Fix the model, not just the layer visibility.
- Distinguish the folded paper piece from the overlap region. Hiding the folded piece because it is awkward is acceptable only for a deliberately simplified snapshot; it is not a substitute for correct overlap computation.
- For each folding phase, name the fold-line intersection point with the original boundary, state which original subregion is being reflected, and then state its reflected image.

## Auxiliary Lines And Points

- Name every auxiliary point or foot explicitly, such as `过 A' 向 x 轴作垂线，垂足为 H`.
- Do not leave a construction implicit.
- Do not reuse the same auxiliary letter for different nearby constructions.
- If a horizontal or vertical helper segment is easier from an extended line, introduce the extension and named intersection first.
- Distinct perpendicular feet or helper intersections should use distinct names unless they are truly the same point.

## Boundary And Range Work

- If a range depends on a core expression, derive the expression before solving boundary values.
- First describe what figure appears at the left boundary and right boundary, then solve or state the interval.
- Prefer classroom wording such as `左边界：...`, `右边界：...`, `重叠部分变成三角形`.
- Keep endpoint inclusiveness exactly aligned across problem text, solution, visual steps, `policies.range`, minis, answer chips, and final answer.
- If a boundary is excluded, do not say the value is attained.
- If a boundary is included, show the attained value when it matters for the final range or extremum.
- If the diagram already reveals monotonic change or candidate extrema, use that trend to reduce unnecessary formulas.
- Once candidate values are known, end with one compact `合并最终答案` step.

## Area Reasoning

- For overlap area, first identify the target region shape, then derive needed lengths/heights, then write the area formula.
- Prefer visible decompositions such as `大图形 - 小图形`, `矩形 - 三角形`, `大三角形 - 两个小三角形`, or another student-visible split.
- When an overlap region is a standard shape, say that shape before writing a formula.
- When the removed or retained region is a standard triangle, prefer deriving its height, side, or familiar area formula over deriving an intermediate base length that is not needed later.
- If a cut-off triangle is similar to or nested inside an equilateral triangle, consider using `面积 = 高²/√3 = √3·高²/3` after clearly proving the triangle is equilateral.
- For symmetric left/right cut-off regions, reuse the same student-friendly structure on both sides when possible: prove the cut-off triangle is standard, find its height from a coordinate distance, then compute area.
- For piecewise overlap-area problems, create one trend/classification step before formula steps. Use `references/piecewise-area-trends.md` for detailed phase and thumbnail rules.
- After the trend/classification step, use monotonicity to identify the only candidate values that can produce the maximum or minimum before doing detailed area calculations. Then calculate only those candidate values whenever possible, instead of deriving and evaluating every full interval formula.
- The trend step should explicitly state which endpoint or transition point gives the maximum candidate and which endpoint candidates need comparison for the minimum, such as `最大值看 t=2；最小值只需比较 t=5/4 与 t=9/4`.
- When both interval endpoints can be candidates, say that explicitly in the trend step and calculate both later. Do not write `最小值只需看右端点` unless the left endpoint has already been compared or ruled out.
- Candidate-value calculations still need a visible area derivation. Do not jump from a candidate `t` value to a coordinate shoelace formula or final number; show the decomposition that produces the area, such as `S=△OGO′-△MNO′` or `S=大三角形-两个小三角形`, then substitute the candidate value.
- Prefer triangle-add/subtract decompositions over polygon coordinate area formulas whenever the target overlap can be seen as a large triangle minus one or two standard triangles.
- Prefer decompositions that match the visible container and removed region. For example, if a right-end overlap is naturally `平行四边形 - 等边三角形`, use that instead of splitting the overlap into unrelated triangles.
- For a fixed candidate value such as `t=2`, make the diagram a fixed snapshot unless dragging the parameter is itself part of the reasoning. Do not show a slider on a step whose purpose is only to calculate one locked endpoint or transition value.
- If an area decomposition names vertices in its formula card, label those vertices on the diagram unless the point is already clearly labeled by a parent layer. Missing labels on formula vertices make the decomposition hard to inspect.
- When a cut length is obtained by an auxiliary perpendicular or projection, draw that auxiliary line in the step diagram and name the foot/intersection. For example, if `F′R` is found by `CK⊥E′F′`, show `CK`, `K`, and the small right triangle that gives `RK=CK`.
- Reuse earlier lengths in later area steps; later steps should feel like calling prior conclusions, not restarting the problem.
- When a later overlap shape sits near a known vertex and a previous segment is available, prefer decompositions that reuse known segments.
- Do not introduce helper area formulas such as `S△PHG=...` or a whole-stage expression such as `S=...` without deriving the needed base, height, included angle, or decomposition immediately before it. If a cut length such as `F′R` is used, show the short chain that obtains it before using it in an area formula.
- If the target area is `S`, keep `S` as the target throughout the problem. Helper shapes are calculation aids, not new target regions.
- Use candidate values and visual trends when they are enough; do not default to deriving every piecewise formula.

## Visual Layering

- Treat each step as a static teaching snapshot, not an animation frame.
- Use a layered display system:
  - global layer: fixed axes, base shape, original fixed vertices
  - sub-question layer: objects useful throughout one sub-question
  - phase layer: repeated local context across adjacent steps
  - step layer: one-step helper lines, angle marks, highlights, or temporary labels
  - derived-results layer: values shown in `lesson-data.steps[].box`
- Assign each object to the first layer where it becomes pedagogically meaningful.
- Do not repeat parent-layer objects in child layers unless the child adds a new role or presentation.
- Keep useful elements stable across consecutive steps by placing them in a phase or section layer.
- Hide helper elements after they no longer support the current inference.
- If a named point from the problem is reused across a sub-question, keep it in the sub-question layer unless a boundary case changes how it should display.
- Do not put calculation helpers into a trend/classification step. A trend step may show only the base figure, moving figure, overlap region, and representative minis; auxiliary points, small triangles, height lines, and formula-specific segments belong in the later calculation step that uses them.
- Make conditional layers tight. A layer with `section` must be intended only for that exact section, and any boundary-only label must use `when`/`eps` or a boundary-specific step. Avoid broad section layers for objects such as an intersection point if earlier steps in the same section do not need it.

## Diagram Content

- The diagram should show conditions that support the current inference, not the answer currently being solved.
- Do not place the answer currently being solved directly into the main diagram.
- Prefer condition labels over result labels during the solving step.
- Before writing a visual step, rank the quantities used in that derivation by teaching importance: target-adjacent helper points, lengths/angles that make the next equality true, and boundary-defining positions are high priority; repeated givens, already-visible collinearity, and values not used in the current step are lower priority.
- Put the highest-priority derivation quantities directly on the diagram when they have spatial meaning, such as `BH=3/2`, `H(3/2,3/2)`, a cut height, or a decisive angle. If the diagram is crowded, remove lower-priority labels first instead of omitting the key quantity.
- Distinguish input quantities from the current step's output: mark the quantities that drive the inference on the diagram, but keep the quantity being concluded in `lesson-data.steps[].box` unless it is needed as an input for a later step. For example, while proving `OM=1/2`, mark `OD=1/2` and the `45°` angle, not `OM=1/2`; while proving `O′M=t-1/2`, mark `OO′=t` and prior `OM=1/2`, not `O′M=t-1/2`.
- Prefer moving secondary conclusions to `lesson-data.steps[].box` or the derivation panel before making the diagram dense. Do not rely on conclusion boxes to carry the one visual quantity students must inspect.
- If a geometry vertex `O` is also the coordinate origin and the grid already shows origin label `O`, do not label the same point twice. Use `showLabel:false` for the point decoration or omit `O` from original-figure `fixedLabels`.
- Put current-step conclusions in `lesson-data.steps[].box`.
- Choose box contents by dependency, not recency: show prior conclusions the current derivation actually uses plus the new conclusion.
- If a reused conclusion has strong spatial meaning, such as a segment length actively used in the step, it may also appear on the diagram.
- Avoid showing both a point-name label and a coordinate label for the same point in the same snapshot. If the coordinate is needed, put the coordinate in the conclusion box or let the coordinate label suppress the ordinary point label; do not create duplicate `B`/`C` text near the same vertex.
- If a fixed point label is hidden by moving/overlap layers, redraw only that point label in the current step after the covering layer, or move the relevant point into a later layer. Do not add a duplicate coordinate label unless the coordinate itself is needed for the inference.
- Do not redraw a named line when it is already exactly an edge of the moving/fixed polygon, such as drawing `l` again on top of `PQ`. Label the existing edge only when the label is essential and does not obscure the construction.
- Distinguish a segment-name label from a length label. Use `BC=2` when the length is the input; avoid showing just `BC` if the step needs the length relation rather than the segment name.
- Do not show live values for quantities outside the current sub-question.
- Keep diagram text minimal; use the derivation panel for explanations.
- When a local diagram area is crowded, keep only the label that directly supports the current calculation; move secondary facts such as parallel relations into the derivation panel or conclusion box.
- Keep labels exact. A wrong segment name, coordinate, or length label is a teaching bug.

## Area Visuals

- Keep the target overlap region `S` in one consistent color across all steps of the same problem.
- Do not recolor the target region just because helper regions are introduced.
- Draw helper containers with subtle outlines or pale fills.
- Draw subtracted/cut regions with a distinct secondary style.
- Make the visual hierarchy match formulas such as `S = large area - small triangle - small triangle`.
- When an area formula uses a triangle, expose the exact base/height or included-angle data used by that formula.
- Avoid putting low-value helper-shape names inside crowded diagram regions; prefer formula cards or the derivation panel.

## Original Problem Figures

- If the problem references `图①`, `图②`, include an `原题图形` block in the problem card.
- Original figures are source-context diagrams, not teaching-step diagrams.
- Redraw original figures cleanly when possible instead of embedding blurry worksheet photos.
- Do not add derived answers, conclusion boxes, live values, extra length annotations, or instructional highlights to original figures.
- If an original figure does not show a later construction, do not include it there just because a later solution step uses it.
- When the printed figure labels the coordinate origin and a shape vertex as the same `O`, show only one `O` label in the redrawn figure.
- Original figures may use larger point markers and labels than teaching-step diagrams, but should still use the same geometry system and color semantics when possible.

## Wording Checklist

- Does each step title name both the method and target?
- Does each step do only one main thing?
- Are given conditions used directly?
- Are auxiliary points explicitly named?
- Are boundary judgment, boundary solving, and interval writing separated when needed?
- Are angle statements used directly instead of repeatedly renamed?
- Are previous conclusions reused instead of re-derived?
- Does the visual step show why the result is true, rather than duplicating the algebra panel?
- Would a middle-school student know exactly what to inspect or draw from the text alone?
