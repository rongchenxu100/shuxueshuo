---
name: senior-high-function-lesson
description: Turn non-calculus high-school function problems from textbook photos or clean text into classified lesson sources, reviewed interactive pages, worksheets, and published catalog entries. Use for function definitions, mappings, domains, values, ranges, monotonicity, finite domains, and contextual function models; route derivative-led problems to derivative-lesson instead.
---

# Senior High Function Lesson

Create or update a **高中函数** interactive lesson. Treat HTML as a compiled artifact: never hand-write final HTML, SVG paths, controls, or one-off runtime JavaScript for a problem.

## Routing

- Use this skill for non-calculus function concepts, mappings, domains, values, ranges, monotonicity, and contextual models.
- Use `derivative-lesson` when differentiation is the central method.
- Use `quadratic-lesson` for middle-school quadratic-function comprehensive problems.

## Photo Batch Workflow

1. Archive the original image under `internal/senior-high/source-images/<batch-id>/`.
2. Create or update `internal/senior-high/import-batches/<batch-id>/manifest.json`.
3. Transcribe printed content only. Record handwriting separately as a private validation hint.
4. Assign the stable draft ID before source metadata is complete.
5. Classify every item by `chapterId`, `sectionId`, curriculum path, group, and knowledge tags.
6. Mark uncertain text or diagrams `needs_review`; low-confidence items cannot become `published`.

## Lesson Workflow

1. Read the relevant files under `references/` plus `internal/senior-high/knowledge-points/function-methods.md`.
2. Create `01_problem.md`, `02_solution.md`, and `03_visual_steps.md`.
3. Create `function-spec.json`, `function-decorations.json`, and `lesson-data.json` only for an interactive lesson.
4. Choose the fewest teaching steps and interactions that expose the decisive mathematics. A direct enumeration, substitution, or algebraic deduction may need only one step; do not force a diagram or slider.
5. Validate and compile:

```bash
node tools/validate-function-spec.mjs internal/senior-high/lesson-specs/<problem-id>/
node tools/build-function-page.mjs internal/senior-high/lesson-specs/<problem-id>/
```

6. Open the output with `file://` and HTTP. Review every original figure in both the problem detail page and its worksheet aggregate page at 100% browser zoom. Measure rendered SVG text in CSS pixels; do not approve from the SVG `font-size` attribute or an enlarged teaching diagram alone.
7. Publish to the canonical chapter/section path only after manual review.

## Publishing Contract

- Draft is workflow metadata (`needs_review`, `ready`, or `published`), not a permanent public directory.
- Keep lesson sources under `internal/senior-high/lesson-specs/<problem-id>/`.
- Publish HTML to `site/problems/senior-high/<chapter-id>/<section-id>/<problem-id>.html`.
- Catalog and worksheet links must use `lesson-data.meta.outputPath`; never reconstruct a `/drafts/` URL in a builder.
- Existing draft URLs may remain temporarily for compatibility, but new catalog entries must point to the canonical path.

## Classification Contract

- `chapterId` is `functions`.
- V1 uses two sibling worksheet sections under `functions`: `function-concepts-and-representation` for 函数的概念, and `function-representation` for 函数的表示法.
- Curriculum path is metadata, not a replacement for chapter/section filtering.
- Group IDs are `function-concept`, `function-domain`, `function-value-and-range`, and, when a problem genuinely combines several strands, `function-comprehensive`.
- Concrete methods such as `mapping-validity`, `radical-domain`, and `interval-range` are knowledge tags.
- Difficulty tiers do not create new chapters or sections. Keep the shared curriculum classification and separate coherent exercise sets with worksheet collections such as `基础练习` and `能力提升`.
- A lesson belongs to one collection only. Collections store ordered lesson IDs and grouping metadata; `lesson-data.json` remains the sole source for the printed problem and source attribution.
- Prefer a separate advanced collection when the new batch is substantially harder and is intended for a second pass. Do not mix it into the foundation worksheet merely because the chapter and section are the same.

## Teaching Rules

- Put the verified source in full-width parentheses immediately before the printed problem text. Do not render it as a separate row.
- Routine exercises should start with the printed problem itself. Do not invent a summary row such as “待复核” or “草稿”; reserve summaries for genuinely long, multi-part problems.
- Preserve every printed diagram that is part of the problem. Reconstruct it declaratively in the problem card before adding a separate teaching diagram, and keep its axes, labels, endpoints, and relative proportions faithful to the source. Give original figures separate detail-page and aggregate-page render profiles; verify labels and numbers at each actual embedded size, not only in an enlarged step diagram.
- Use navigation groups only for actual numbered subquestions in the printed problem. A single question with several solution steps must remain one ungrouped step sequence; methods and phases are not question groups.
- Keep the collapse/expand control in the problem card's top-right corner so it does not create a separate content row.
- Collapsing the problem must retain its first printed line instead of leaving an empty card.
- State the definition being tested before applying it.
- For a function from `A` to `B`, display and verify unique correspondence and `actual range ⊆ B` as separate requirements.
- Separate each domain constraint, then intersect the resulting sets.
- Distinguish a function's rule from its domain; identical formulas with different domains are not the same function.
- For ranges, show how each admissible input produces an output before concluding the full set.
- Graphs explain; algebra, monotonicity, finite enumeration, or endpoint comparison proves.
- Keep one mathematical action per step, but do not split a short argument merely to increase the step count. For multiple-choice questions, prefer one consistently structured step per option when each option needs independent checking.
- Use concise explanatory phrases to define symbols and identify the purpose of a calculation, then use standard mathematical notation for the derivation. Avoid both prose-heavy derivations and unexplained chains of symbols.
- Typeset mathematical expressions structurally: fractions, radicals, exponents, subscripts, intervals, set relations, and units must align as mathematics rather than appear as flattened text.
- Add a concise `problem.keyPoints` block when a problem has a reusable decision framework, multiple easy-to-miss conditions, or a method students should retain. Do not add it mechanically to direct-substitution or one-step exercises, and never reveal the answer in it.
- Define all temporary symbols locally and retain the symbols used in the problem.
- Keep JSON declarative and free of HTML.

## V1 Panels

- `mapping`: source set, target set, mapping arrows, invalid outputs.
- `relationPlot`: discrete points/segments and vertical-line validity.
- `numberLine`: interval unions, open/closed endpoints, exclusions.
- `functionGraph`: curve, moving input, projections, domain/range emphasis.
- `valueTable`: finite inputs, substitution, outputs.
- `constraintList`: individual constraints and their intersection.
- `contextGeometry`: static application geometry using shared primitives.

## Final Review

- Printed text is separated from handwriting hints.
- Classification matches the curriculum and the actual method.
- The solution has been independently verified.
- Every control changes visible mathematical state.
- Every diagram has independent teaching value. Pure algebraic steps use `showDiagram: false`; do not add a graph merely to make the page look interactive.
- Candidate graphs use a shared coordinate window unless a documented mathematical reason requires otherwise.
- Full curves stay inside each function's natural domain; emphasized segments use the intersection with the problem's input set.
- Open/closed endpoints, exclusions, finite values, and answer notation agree everywhere.
- SVG contains no `NaN`, `Infinity`, or `undefined`.
- Original-problem figures pass the hard legibility gate in `references/function-visualization-principles.md` at both aggregate-page and problem-card sizes. Axes, tick labels, variables, dimensions, and option numbers must not depend on browser zoom.
- Mobile layout has no page-level horizontal overflow.
- Published catalog links resolve to canonical non-`drafts` paths; unreviewed lessons are absent from the public catalog.

## 基于审校反馈的执行规则

- Start from the governing mathematical definition. For function judgments, state uniqueness of output first; for `A -> B`, also verify that the actual range is a subset of `B`.
- Use the fewest steps that match distinct cognitive actions. A one-idea problem stays one step, and navigation groups represent actual subquestions rather than editorial categories.
- Step titles describe the action directly and do not repeat `第 1 步` or similar numbering already supplied by the runtime.
- Add a diagram only when it supplies mathematical evidence. Do not emit blank diagram shells, repeated unchanged diagrams, or decorative graphs for a purely algebraic step.
- Graph variables, axes, highlighted intervals, endpoints, and labels must match the derivation. Original-problem figures preserve topology, option numbering, dimensions, ticks, and readable text.
- Visible formulas use the structured math formatter. Raw TeX delimiters or commands such as `\(`, `\Rightarrow`, `\cap`, and `\mid` must never reach the compiled page.
- Sources appear inline before the printed stem. Published pages contain no `draft`, `待复核`, or internal-review wording.
- Collapsing a problem keeps its first printed line visible. Worksheet pages hide answers and solution content; choices start on a separate line, and long choices use one row each.

Apply the detailed rules in:

- `references/function-solving-principles.md`
- `references/function-visualization-principles.md`
- `references/function-json-schema-guide.md`
