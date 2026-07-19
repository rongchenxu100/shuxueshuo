# Calculus Visualization Principles

## Visual Roles

Use the diagram to make dependency visible:

- the original function stays fixed unless the problem says otherwise;
- a parameterized comparison function changes only through ordered bindings;
- tangent lines and contact points move together;
- an auxiliary parameter graph shows how the requested coefficient changes with the generating parameter.

When two or more function curves share a panel, label each curve directly with the full curve notation, such as `y=f(x)=...` and `y=g(x)=...`. Color and legend swatches may reinforce identity, but must not be the only way a student can distinguish `f` from `g`.

Do not use animation as a substitute for algebraic justification.

## Panels

Use one panel for ordinary tangent or monotonicity problems. Use two synchronized panels when the problem moves between two mathematical spaces, for example:

- left: `f(x)`, `g(x)`, a common tangent, and two contact points;
- right: an auxiliary function such as `a=h(x1)`, its moving point, critical points, and the final value range.

Give each panel an explicit viewport and mathematical domain. A panel viewport is a normalized rectangle inside the shared `1080×760` SVG.

## Slider Semantics

Label the slider with the original generating variable and its meaning, such as `第一切点横坐标 x₁`. Avoid introducing an alias solely for the visualization. If the true domain is unbounded but the slider uses a finite observation window, say so in the derivation or control note.

Provide mini states for mathematically important values: given values, critical points, boundaries, and extrema. Do not add arbitrary snapshots.

Use continuous sliders only for genuine exploration. If a step exists to compare a finite set of critical or boundary states, hide the slider and keep the representative chips/cards clickable. Clicking must produce an obvious selected state in the main diagram.

## Step Relevance

- The first tangent-construction step should show the active function, first contact point, and only its tangent.
- The second tangent-construction step should show the second function, second contact point, and only its tangent.
- The coefficient-matching step may show both tangents together; use distinguishable solid/dashed styling so their exact overlap remains visible.
- Label a contact point with its symbolic coordinates when those coordinates drive the current derivation, such as `P(x1,f(x1))`. After substituting a fixed value, replace the symbolic label with the resulting numeric coordinates.
- Do not rely on legends alone for curve identity. Put `y=f(x)=...` and `y=g(x)=...` near the corresponding curves, and keep point labels close enough to their points without covering the curve.
- A derivative-sign step should emphasize critical points and sign intervals.
- A final range step may add a quiet range band, but should remove labels that do not support the conclusion.

For an auxiliary-function range proof, reveal the parameter panel in four stages:

1. Show the auxiliary curve and its moving point when defining the function.
2. Add exactly the named critical points when solving the derivative equation.
3. Add the derivative sign band when determining monotonicity.
4. Replace exploratory emphasis with the global extremum and final range band.

Once the derivation has moved completely into the auxiliary-function analysis, hide the original function/tangent panel and let the auxiliary panel use the available diagram width. Keep the original panel only while it still explains a dependency.

Do not show a free moving point beside a set of named critical points; it looks like an extra critical point. For a fixed critical-point step, let representative-state controls snap a single selection ring onto one of the named points. Representative states may remain clickable even when the continuous slider is hidden.

When the final derivation explicitly compares several critical values, label all compared values on the auxiliary graph, not only the global winner.

Hide legends whose entries belong only to hidden panels. A focused single-panel step should not retain labels for curves or tangents that are no longer visible.

Reserve final numeric labels for the step that derives them. Earlier diagrams should use symbolic labels or no coordinate labels.

## Discontinuities

Declare function domains explicitly for logarithmic, rational, radical, or piecewise expressions. The renderer splits sampled paths at non-finite values and large jumps, but the lesson must still state the domain and excluded points.
