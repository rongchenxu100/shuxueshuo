# Inequality Solving and Visualization Principles

## 1. Mathematical audit order

For every authored or transcribed item, audit in this order:

1. research domain and denominator restrictions;
2. signs of all factors and divisors;
3. the property used to transform the inequality;
4. equality and boundary cases;
5. whether all cases have been exhausted;
6. whether the final set notation matches the endpoint logic.

Do not infer a sign from visual familiarity. Write the controlling factorization or bound explicitly.

## 2. Core property model

Keep the textbook distinction between basic and operational properties.

Basic properties:

- symmetry: `a>b` iff `b<a`;
- transitivity: `a>b` and `b>c` imply `a>c`;
- addition: adding the same real number preserves direction;
- multiplication: a positive multiplier preserves direction, a negative multiplier reverses it, and a zero multiplier gives equality.

Operational properties require all stated hypotheses. In particular, product and power comparisons need positivity assumptions; they are not unconditional algebraic templates.

## 3. Comparison methods

### Difference method

Compute `A-B`, factor or complete the square, then determine its sign. Prefer a compact factor-sign display when every factor has a known sign.

### Quotient method

Use `A/B` versus `1` only when the quotient is defined and the sign assumptions needed for the conclusion have been established.

### Middle-quantity method

Compare both expressions with a common benchmark, usually `0` or `1`. Show both inequalities; do not merely name the benchmark.

## 4. Range calculations

When the source gives independent bounds on expressions `u` and `v`:

1. solve for constants `α,β` such that the target equals `αu+βv`;
2. create a table with each source range, coefficient, and endpoint contribution;
3. select lower or upper endpoints according to the sign of each coefficient;
4. confirm the selected endpoint values can occur simultaneously;
5. state the final closed or open interval.

When one reusable summary should expose the whole method, use `problem.keyPoints.kind: "linear-combination-range-flow"` to replace the ordinary text key-points block. It belongs after the problem and before every explanatory step. Keep the detailed, problem-specific derivation below it; the method map summarizes rather than replaces the proof.

## 5. Visual routing

- Use a sign-case table for addition, multiplication, division, and reciprocal rules.
- Use a three-state direction strip for positive, zero, and negative multipliers.
- Use a difference/factor strip for expression comparisons.
- Use aligned number lines only for actual intervals, rays, solution sets, or parameter endpoints.
- Use a `linear-combination-range-flow` for a one-glance “重组 → 求界 → 相加” summary, and a small coefficient-contribution table for the detailed bounds.
- Do not add a diagram when a one-line factorization communicates the entire reason.

## 6. Property-judgment option audit

Use this contract for multiple-choice or judgment items whose task is to decide which claim is correct, always true, or logically follows from the stated conditions. It is especially useful when distractors fail because of a missing domain restriction, an uncontrolled sign, a reversed inequality direction, or misuse of an operational property.

Do not apply it mechanically to routine calculations, direct proofs without distractors, or problems where a single derivation already exposes the decisive idea. Counterexamples are explanatory evidence for claims already present in the source, not permission to invent new exercise groups.

For the page-level key points and derivation:

1. name the exact knowledge-point rule, distinguishing `基本性质·可乘性` from `运算性质·可加法则` and similar rules;
2. check domain, nonzero, and sign conditions before invoking that rule;
3. prove the correct option through `conditions → named property → transformation → conclusion`;
4. for each false option, choose a small counterexample satisfying every premise, substitute into the original statement, calculate both sides to explicit values, and state exactly why the conclusion fails;
5. if the failure is undefinedness, calculate the offending denominator or expression to zero and explicitly say that the resulting expression is undefined;
6. keep aggregate hints and detail-page key points synchronized.

When several options are compared, prefer this four-column structure:

| 选项 | 关键判断 | 反例代入计算 | 结论 |
| --- | --- | --- | --- |
| false option | missing or misused condition, with the named property | concrete values substituted and fully evaluated | 错误 |
| correct option | conditions and named-property proof | `—（正确项，由性质直接证明）` | 正确 |

A counterexample is incomplete if it stops after choosing `a=1, b=-1` or merely rewrites the symbolic claim. Continue to concrete arithmetic, for example `1/a=1/1=1` and `1/b=1/(-1)=-1`, then compare `1` and `-1`. Likewise, write `ab=(-2)×(-1)=2`, not an unsupported raw command such as `ab=(-2)\\times(-1)=2`.

## 7. Serialization

- Put inline formulas inside `\\(...\\)` in JSON strings.
- Escape JSON backslashes exactly once at the source level.
- Prefer stable Unicode relation symbols in user-facing short answers.
- After compilation, scan rendered pages for literal `\\frac`, `\\mathbb`, `\\left`, `\\right`, or unmatched delimiters.

## 8. Source fidelity checklist

- Printed stem copied exactly.
- Printed options and order copied exactly.
- Exercise number preserved.
- Handwritten answer used only to cross-check.
- Answer independently verified.
- Overview knowledge map mirrors supplied material.
- Unsupported later modules remain pending rather than invented.

## 9. Reusable sign-chart contract

Use `visual.kind: "inequality-sign-chart"` when the decisive information is the sign on intervals cut by roots, forbidden points, or piecewise breakpoints. The visual accepts:

- `columns`: interval and boundary labels in number-line order;
- `rows`: one or more labeled sign/result rows;
- `selectedIndices`: cells belonging to the final solution;
- `solution`: the final set or relation;
- `notes`: boundary, multiplicity, or domain reminders;
- `caption`: one sentence explaining what the table proves.

Route the main families as follows:

- quadratic inequalities: compare discriminant, opening direction, roots, and solution in one table;
- polynomial inequalities: order every real root, start from the far-right leading-term sign, and reverse only across odd-multiplicity roots;
- rational inequalities: put numerator zeros and denominator zeros in the same ordered chart, label denominator zeros as forbidden, and never select them;
- absolute-value inequalities: use a piecewise case table with each interval condition, simplified inequality, and intersection result.

Before publishing, verify that strict endpoints are open, allowed numerator zeros are included only for non-strict inequalities, even-multiplicity roots do not change sign, and every piecewise conclusion has been intersected with its own case interval.

## 10. Reusable linear-combination range flow contract

Use `problem.keyPoints.kind: "linear-combination-range-flow"` for range problems where a target expression is rewritten as a linear combination of independently bounded expressions. This abstract method map replaces the ordinary `解题要点` block and appears above all steps. It accepts:

- `inputs`: at least two known bounded expressions;
- `stages`: exactly three cards named `重组`, `求界`, and `相加`, each with a `method`, one or more `content` lines, and the corresponding `visual` value `regroup`, `bound`, or `add`;
- `result`: the final target range;
- `title`, `caption`, and `ariaLabel`: concise framing and an accessible explanation.

The three cards must expose the mathematical authority for each transition: `重组` names the coefficient method and shows the target becoming `p×①+q×②`; `求界` names multiplication, checks coefficient signs, and shows two colored interval segments; `相加` names same-direction addition and shows those segments merging into one target interval. Use only abstract symbols such as `U,V,T,p,q` in this map; keep all exercise-specific expressions and numbers in the steps below. Use stable Unicode Greek letters such as `λ` and `μ` when the local renderer does not support the corresponding TeX commands.
