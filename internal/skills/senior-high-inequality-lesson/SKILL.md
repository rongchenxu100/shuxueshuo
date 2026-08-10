---
name: senior-high-inequality-lesson
description: Build or revise high-school inequality learning topics, interactive exercises, and compiled solution pages from textbook photos or clean text. Use for inequality properties, sign rules, comparing algebraic expressions, range calculations, solving linear, polynomial, rational, or absolute-value inequalities, and basic-inequality lessons.
---

# Senior High Inequality Lesson

Create a structured learning topic rather than a static question bank. Treat catalog JSON and lesson-data JSON as authoritative sources and generated HTML as compiled output.

## Required Reading

Before editing, read:

- `references/inequality-solving-and-visualization-principles.md`
- `internal/senior-high/knowledge-points/learning-topic-page-contract.md`

Use these repository sources as current schema examples:

- `internal/senior-high/catalog/chapters.json`
- `internal/senior-high/catalog/learning-topics.json`
- `tools/build-senior-high-library.mjs`
- `internal/senior-high/lesson-specs/set-operations-intersection-q08/lesson-data.json`
- `internal/senior-high/lesson-specs/inequality-property-q01/lesson-data.json`
- `internal/senior-high/lesson-specs/inequality-property-q02/lesson-data.json`

## Workflow

1. Inspect every supplied textbook page at readable resolution. Transcribe printed headings, formulas, options, order, and diagrams exactly. Treat handwriting only as a checking hint and independently solve every item.
2. Archive source images with stable page names and record their source order. Keep the textbook knowledge-map hierarchy. Publish only modules supported by the supplied pages; keep confirmed but incomplete modules `pending` with concise `knownPoints`.
3. Separate domain conditions from algebraic manipulation. Before taking reciprocals, multiplying, dividing, squaring, or applying powers, state the required sign and nonzero assumptions.
4. For a property-judgment item that asks which statement is correct, always true, or follows from the hypotheses, use a named-property option audit:
   - cite the exact knowledge-point property in the key points and derivation;
   - prove the correct option from its conditions and the named property;
   - disprove a false option with a counterexample only when that makes the failure concrete;
   - make every counterexample satisfy the option's premises, substitute the values into the original expressions, and evaluate both sides to explicit numbers or an explicit undefined expression;
   - when several options are audited, keep `选项 | 关键判断 | 反例代入计算 | 结论` as separate columns.
5. Choose the comparison method before calculating:
   - use difference comparison for unrestricted expressions;
   - use quotient comparison only after proving both compared quantities have the required sign;
   - use a middle quantity such as `0` or `1` when it makes both comparisons immediate;
   - use a positive-factor decomposition when the sign of every factor is controlled.
6. For bounded linear combinations, rewrite the target as a linear combination of the independently bounded expressions. Track coefficient signs before selecting endpoints, and verify whether the extrema can be attained simultaneously.
7. Write each detail page as `internal/senior-high/lesson-specs/<lesson-id>/lesson-data.json` and register it in `internal/senior-high/catalog/learning-topics.json` with a typed `answerSchema` and nonempty hints.
8. Match the interaction to the cognitive action: multiple-choice source questions stay multiple choice; one-symbol comparisons use a compact exact-expression control; interval or range answers use math-expression input with interval keys.
9. Use tables for sign cases, operation rules, option audits, and linear-combination bounds. Use aligned number lines only when solution sets or endpoints materially explain the result. Use a factor-sign strip or difference decomposition when it is more direct than a number line.
10. Compile and test:

```bash
node tools/build-text-page.mjs internal/senior-high/lesson-specs/<lesson-id>/
node tools/build-senior-high-library.mjs
node --test tools/tests/senior-high-library.test.mjs
```

11. Review overview, modules, and every detail page at desktop and phone widths. Check formula rendering, answer controls, long options, tables, number lines, links, overflow, raw TeX leakage, and agreement between aggregate and detail pages.

## Publishing Rules

- Create an independent top-level chapter when the textbook treats inequalities as a chapter parallel to sets or functions.
- Preserve the textbook's definition order, named methods, exercise numbering, option wording, and option order. If the printed mathematics is genuinely invalid, report the conflict rather than silently replacing it.
- Do not invent examples, exercise groups, or downstream module content absent from supplied pages.
- Explanatory counterexamples are permitted for auditing a printed claim, but they must be minimal, satisfy every printed premise, and must not be presented as new source exercises.
- Do not mechanically add counterexamples to routine calculations, direct proofs, or single-path solution questions. Use the option-audit pattern only when the learning goal is to decide whether a statement follows from given conditions; omit it when a direct derivation is clearer.
- A statement such as `a>b` never licenses reciprocal or multiplication conclusions without checking domains and signs.
- When a result depends on equality, explicitly state whether the equality case is included and why.
- Use stable Unicode mathematical symbols or delimited inline math. Never expose raw commands such as `\\frac`, `\\mathbb`, or `\\Rightarrow` as page text.
- Hide generic sources such as `培训教材` and show only concrete exams or papers.

## Final Review

- Every algebraic transformation cites the exact inequality property that authorizes it.
- In a property-judgment option audit, every false-option counterexample satisfies the premise and computes the original left and right sides to explicit values; the correct option is proved from a named property rather than supported by one example.
- Counterexamples occupy a separate table column when the page compares several options.
- Multiplication or division by a negative quantity reverses the relation; multiplication by zero yields equality.
- Reciprocal comparison checks nonzero and sign conditions.
- Difference comparison reduces the conclusion to the sign of a fully controlled expression.
- Range calculations account for coefficient signs and simultaneous attainability of endpoints.
- Strict and non-strict endpoints remain consistent from derivation to final interval.
- Aggregate and detail pages agree on stems, answers, notation, numbering, and ordering.
- No visible backslashes, unsupported TeX commands such as `\\times`, or flattened fractions remain; use the Unicode multiplication sign `×` in short arithmetic substitutions.
