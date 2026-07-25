---
name: senior-high-function-lesson
description: Turn non-calculus high-school function problems from textbook photos or clean text into classified drafts and compiled interactive lesson pages. Use for function definitions, mappings, domains, values, ranges, monotonicity, finite domains, and contextual function models; route derivative-led problems to derivative-lesson instead.
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

1. Read all three files under `references/` plus `internal/senior-high/knowledge-points/function-methods.md`.
2. Create `01_problem.md`, `02_solution.md`, and `03_visual_steps.md`.
3. Create `function-spec.json`, `function-decorations.json`, and `lesson-data.json` only for an interactive lesson.
4. Choose an interaction that serves the mathematics: candidate switching, constraint reveal, finite value table, or moving input. Do not force a slider.
5. Validate and compile:

```bash
node tools/validate-function-spec.mjs internal/senior-high/lesson-specs/<problem-id>/
node tools/build-function-page.mjs internal/senior-high/lesson-specs/<problem-id>/
```

6. Open the output with `file://` and HTTP. Publish to the catalog only after manual review.

## Classification Contract

- `chapterId` is `functions`.
- V1 `sectionId` is `function-concepts-and-representation`.
- Curriculum path is metadata, not a replacement for chapter/section filtering.
- Group IDs are `function-concept`, `function-domain`, and `function-value-and-range`.
- Concrete methods such as `mapping-validity`, `radical-domain`, and `interval-range` are knowledge tags.

## Teaching Rules

- Put the verified source in full-width parentheses immediately before the printed problem text. Do not render it as a separate row.
- Preserve every printed diagram that is part of the problem. Reconstruct it declaratively in the problem card before adding a separate teaching diagram, and keep its axes, labels, endpoints, and relative proportions faithful to the source.
- Use navigation groups only for actual numbered subquestions in the printed problem. A single question with several solution steps must remain one ungrouped step sequence; methods and phases are not question groups.
- Keep the collapse/expand control in the problem card's top-right corner so it does not create a separate content row.
- State the definition being tested before applying it.
- For a function from `A` to `B`, display and verify unique correspondence and `actual range ⊆ B` as separate requirements.
- Separate each domain constraint, then intersect the resulting sets.
- Distinguish a function's rule from its domain; identical formulas with different domains are not the same function.
- For ranges, show how each admissible input produces an output before concluding the full set.
- Graphs explain; algebra, monotonicity, finite enumeration, or endpoint comparison proves.
- Keep one mathematical action per step and reveal the final answer only after the decisive condition.
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
- Candidate graphs use a shared coordinate window unless a documented mathematical reason requires otherwise.
- Full curves stay inside each function's natural domain; emphasized segments use the intersection with the problem's input set.
- Open/closed endpoints, exclusions, finite values, and answer notation agree everywhere.
- SVG contains no `NaN`, `Infinity`, or `undefined`.
- Mobile layout has no page-level horizontal overflow.
- Drafts are absent from the public catalog until reviewed.
