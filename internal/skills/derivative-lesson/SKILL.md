---
name: derivative-lesson
description: Turn high-school derivative and calculus application problems into compiled interactive lesson pages in the shuxueshuo repository. Use for tangent or common-tangent problems, monotonicity and extrema analysis, and parameter-range problems solved with derivatives. The agent writes teaching markdown plus declarative calculus JSON; repository tools validate and compile the final HTML.
---

# Derivative Lesson

Create or update a **高中导数及其应用** interactive page. Treat HTML as a compiled artifact: never hand-write final HTML, SVG paths, chart sampling, slider wiring, or page runtime JavaScript for one problem.

## Output Contract

Work in this order:

1. Read `internal/senior-high/knowledge-points/calculus-methods.md` and `calculus-case-index.md`.
2. Select one primary pattern, the methods actually used by the solution, and up to three similar published cases.
3. Create or update `internal/senior-high/lesson-specs/<problem-id>/01_problem.md`.
4. Create or update `02_solution.md` and `03_visual_steps.md`.
5. Create or update:
   - `calculus-spec.json`
   - `calculus-decorations.json`
   - `lesson-data.json`
6. Keep `lesson-data.meta.classification` synchronized with the final solution.
7. For a publish-ready page, add or update the case in `calculus-case-index.md`.
8. Validate and compile:

```bash
node tools/validate-calculus-spec.mjs internal/senior-high/lesson-specs/<problem-id>/
node tools/build-calculus-page.mjs internal/senior-high/lesson-specs/<problem-id>/
```

9. Open the compiled HTML directly and inspect every interactive step. Start a local static server only when the browser or an asset-loading requirement makes `file://` insufficient.

## Required References

- Always read `references/calculus-solving-principles.md` before writing the solution.
- Always read `references/calculus-json-schema-guide.md` before writing JSON.
- Always read `references/calculus-visualization-principles.md` before planning diagrams or interactions.
- Read the real schemas when fields are uncertain; schemas override prose documentation.

## Core Rules

- Use the genuine generating variable named by the problem, such as a contact-point abscissa, as the main slider.
- Reuse the problem's original symbol; do not rename an existing `x1` to `t` without a real conflict.
- Do not make the unknown coefficient being solved (`a`, `b`, or `c`) the slider when it is determined by another variable.
- Define auxiliary notation locally. Prefer a familiar name such as `h(x1)` or `phi(x1)` and explicitly state `a=h(x1)`; do not present a temporary symbol as though it were universal notation.
- Declare each derivative in `functions[].derivativeExpr`; the runtime does not perform symbolic differentiation.
- Use ordered `bindings` for dependent values such as slopes, second contact points, and coefficients.
- Use multiple synchronized panels only when they explain different mathematical spaces, such as the original curves and an auxiliary function `a=h(t)`.
- Remove an earlier panel once later steps no longer use its mathematical information; let the active panel expand instead of carrying decorative context forward.
- Treat graphs as observation and explanation. Complete range and monotonicity proofs with derivative signs, domain boundaries, endpoints, or behavior at infinity.
- Keep one mathematical idea per lesson step. Do not reveal a solved parameter, critical point, or final range before the matching derivation.
- Split an auxiliary-function range proof into four stages: define the function, find critical points, determine monotonicity, then compare global values and conclude the range.
- Use formal full titles on lesson cards and shorter matching labels in step navigation; preserve the same mathematical action in both.
- Every interactive control must change visible mathematical state. Keep representative values clickable even when continuous dragging has no teaching value.
- Keep all JSON declarative and free of HTML fragments.

## Supported V1 Scope

- Tangent lines at a point.
- Common tangents and two contact points.
- Monotonicity and local/global extrema.
- Parameter ranges derived from a one-variable auxiliary function.
- Polynomial, exponential, logarithmic, and basic trigonometric expressions supported by the expression engine.

Do not use this skill for symbolic integration, multivariable calculus, complex double-parameter classifications, or a full LLM solver pipeline.

## Final Review

- The problem source, title, answers, and output path are correct.
- Function domains are stated before differentiation when needed.
- Every derivative expression is algebraically correct and passes numerical validation.
- Tangent points, slopes, and intercepts remain synchronized while dragging.
- Function names, values, and curves use `f`, `f(x)`, and `y=f(x)` consistently; multi-curve panels label every curve directly.
- Every temporary function or point name is defined before use and cannot be mistaken for a standard symbol.
- Slider range is explicitly described as an exploration window when the mathematical variable ranges over all real numbers.
- Critical values and interval endpoints agree across markdown, JSON, chips, and diagrams.
- Auxiliary-function range lessons reveal critical points, derivative signs, and the final range in separate steps.
- A critical-point step shows exactly the named critical positions; it does not add an unrelated free moving point.
- A final comparison step labels every function value used in the comparison, not only the winning extremum.
- Parallel tangent steps use matching derivation structures and `∵ / ∴` connectors; contact-point coordinates appear in the relevant diagram.
- No panel, legend, control, or label remains after it stops supporting the current mathematical action.
- The final range is proved rather than inferred only from the visible chart.
- Step IDs align across lesson data and calculus decorations.
- Validation and compilation succeed without patching generated HTML.
