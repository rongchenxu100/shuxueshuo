---
name: senior-high-logic-language-lesson
description: Build or revise high-school common-logical-language learning topics, interactive exercises, and compiled solution pages from textbook photos or clean text. Use for propositions and truth values, sufficient and necessary conditions, implication and equivalence, parameter ranges expressed as condition sets, universal and existential quantifiers, and negations of quantified propositions.
---

# Senior High Logic Language Lesson

Create a structured learning topic rather than a static question bank. Treat catalog JSON and lesson-data JSON as authoritative sources and generated HTML as compiled output.

## Required Reading

Before editing, read:

- `references/logic-solving-and-visualization-principles.md`
- `internal/senior-high/knowledge-points/learning-topic-page-contract.md`

Use these repository sources as current schema examples:

- `internal/senior-high/catalog/learning-topics.json`
- `tools/build-senior-high-library.mjs`
- `internal/senior-high/lesson-specs/logic-proposition-q01/lesson-data.json`
- `internal/senior-high/lesson-specs/logic-condition-q10/lesson-data.json`

## Workflow

1. Inspect every supplied page at readable resolution. Transcribe printed headings, exercises, options, order, and diagrams exactly; treat handwriting only as a checking hint. Before publishing, compare every aggregate stem and option against the source image instead of silently repairing or replacing a distractor.
2. Independently classify and solve every item. Record whether each sentence is a proposition, its truth value when relevant, both implication directions, and all boundary or counterexample checks.
3. Preserve the textbook knowledge-map hierarchy. Publish only modules supported by supplied material; keep confirmed but incomplete modules `pending` with concise `knownPoints`.
4. Write each detail page as `internal/senior-high/lesson-specs/<lesson-id>/lesson-data.json` and register it in `internal/senior-high/catalog/learning-topics.json` with a typed `answerSchema` and nonempty hints.
5. For “若 p，则 q”, test `p⇒q` and `q⇒p` separately before naming the condition. For inequality predicates, solve each predicate to a set and compare the sets.
6. Use counterexamples to disprove implications. Name the exact failed direction and show a counterexample that satisfies its premise but not its conclusion.
7. Use tables for finite truth classification, nested conditions, and two-direction implication audits. Use aligned number lines only when interval containment or parameter endpoints materially explain the result. Label evidence axes with the actual named sets from the problem; use abstract `P` and `Q` only after introducing that mapping once.
   Use a two-row comparison table for parallel lexical negations such as “是/不是”“大于/小于或等于” and quantifier phrases; do not scatter these pairs across prose bullets.
8. Match the interaction to the cognitive action: multipart proposition or truth judgments use per-item quick-choice buttons, not text areas. Preserve one selection per row, show missing rows before grading, and return row-level feedback after submission.
   Condition-classification items use the four named condition relations as choices; “筛选哪些命题成立” items use one binary choice per statement instead of asking students to type a sequence of item numbers.
9. Compile and test:

```bash
node tools/build-text-page.mjs internal/senior-high/lesson-specs/<lesson-id>/
node tools/build-senior-high-library.mjs
node --test tools/tests/logic-lessons.test.mjs tools/tests/senior-high-library.test.mjs
```

10. Review overview, modules, assessment exercises, and every detail page at desktop and phone widths. Check formula rendering, answer controls, long options, tables, number lines, links, overflow, raw TeX leakage, and mixed text/formula rows. A two-column row must have exactly two direct layout children: its label/index and one wrapper containing the complete formula-rich body.

## Publishing Rules

- Publish under `site/problems/senior-high/sets/common-logical-language/` while this textbook chapter remains grouped with the opening sets unit.
- Use `chapter=sets`, `section=common-logical-language`, and the correct module route.
- Do not reproduce a long copyrighted story introduction; summarize its mathematical purpose in original wording.
- Do not invent exercise-group headings or module content absent from the supplied pages.
- Keep core knowledge faithful to the textbook's definition order and named distinctions. Web copy may be tightened, but it must not collapse separate definitions, omit symbol meanings, or remove any of the textbook's four implication cases.
- Present parallel definitions and classification cases as separately wrapped, numbered knowledge lines. Do not compress multiple textbook cases into one paragraph.
- Preserve textbook stems, option wording, option order, and exercise numbering across aggregate and detail pages. If the printed mathematics is genuinely invalid, report the conflict rather than replacing it without notice.
- Show a knowledge block's “对应练习” anchor only when that block category has at least one exercise; never display “对应练习 0 题”.
- Keep a sentence's proposition status separate from its truth value: a false declarative sentence can still be a proposition.
- Hide generic sources such as `培训教材` and show only concrete exams or papers.

## Final Review

- Every proposition judgment answers both “is its truth value determined?” and, when relevant, “true or false?”.
- A free variable without a quantifier is not silently treated as universally quantified.
- `p⇒q` means p is sufficient for q and q is necessary for p; do not reverse the language.
- Four-way classifications are supported by two explicit implication checks.
- Set inclusion uses the same direction as implication: if `P⊆Q`, then membership in P sufficiently implies membership in Q.
- In set-based condition visuals, use the problem's set names on number lines (for example `C_{\mathbb R}A` and `B`), keep abstract `p` and `q` only in the implication arrows, and define each mapping exactly once. Component data fields that the renderer labels as `p:` or `q:` must contain bare predicates, not repeated prefixes.
- Strict/non-strict endpoints are justified, especially when an open ray must contain a closed interval.
- Parameter answers distinguish sufficient-but-not-necessary from sufficient-and-necessary by checking whether the reverse implication also holds.
- Negating a quantified proposition switches `∀/∃` and negates the predicate while preserving the domain. Negating “at least one holds” yields “all fail”, not “at least one fails”.
- Aggregate and detail pages agree on stems, answers, notation, and ordering.
- Multipart binary judgments use quick choices with clear selected, missing, correct, and incorrect states.
- No visible backslashes or unsupported TeX commands leak into rendered text.
- Render implication and equivalence as stable mathematical symbols (`⇒`, `⇏`, `⇔`); never expose raw commands such as `\\Rightarrow`.
