---
name: senior-high-set-lesson
description: Build or revise high-school set learning topics, interactive exercise aggregates, and compiled solution pages from textbook photos or clean text. Use for set concepts, element membership, common number sets, enumeration, descriptive notation, intervals, Venn diagrams, set parameters, ordered pairs, and comprehensive set practice.
---

# Senior High Set Lesson

Create a structured learning topic rather than a static question bank. Treat generated HTML and catalog data as compiled artifacts; author declarative lesson and topic sources.

## Required Reading

Before editing, read:

- `references/set-solving-and-visualization-principles.md`
- `internal/senior-high/knowledge-points/learning-topic-page-contract.md`

Use these repository sources as the current schema examples:

- `internal/senior-high/catalog/learning-topics.json`
- `tools/build-senior-high-library.mjs`
- `internal/senior-high/lesson-specs/set-concept-example-q01/lesson-data.json`
- `internal/senior-high/lesson-specs/set-representation-interval-q01/lesson-data.json`

## Workflow

1. Inspect every supplied page at readable resolution. Transcribe printed content, order, headings, options, and printed diagrams only; treat handwriting as a private checking hint, never as answer authority.
2. Independently solve every problem and record a checked answer/type matrix before authoring pages. Resolve missing, duplicated, or mathematically incomplete choices before publishing.
3. Classify content into an overview, knowledge modules, and an assessment module following the shared learning-topic contract. Keep the textbook hierarchy and wording; do not invent progress notices, map branches, or exercise-group headings.
4. Write each published detail page as `internal/senior-high/lesson-specs/<lesson-id>/lesson-data.json`.
5. Give every aggregate-page exercise a typed `answerSchema`, nonempty hints, and a canonical lesson link. A pending item must not expose an answer control or fake solution.
6. Author explicit mathematical reasoning with `because` and `therefore`; use `derive` only as a recap. Make every classification exhaustive, preserve parent-child branch structure, and explicitly union the parameter sets from disjoint cases.
7. Select a table, number line, or Venn diagram only when required by the mathematics. Make the visual mirror the proof: when one overlaid number line mixes inputs and conclusions, use separate rows for each set and a final result or parameter row.
8. Treat browser comments as regression evidence. Edit declarative sources, add or strengthen a targeted test, rebuild generated artifacts, and recheck the commented region rather than patching compiled HTML.
9. Compile and test:

```bash
node tools/build-text-page.mjs internal/senior-high/lesson-specs/<lesson-id>/
node tools/build-senior-high-library.mjs
node --test tools/tests/text-lessons.test.mjs tools/tests/senior-high-library.test.mjs
```

10. Review the aggregate page and every detail page at desktop and phone widths. Check formula rendering, answer interaction, long options, diagrams, links, horizontal overflow, clipped SVG labels, and cache-version updates for changed shared assets.

## Source and Publishing Rules

- Show a source only when it names a concrete exam, paper, school assessment, or similarly specific provenance. Hide generic labels such as `培训教材`, `教材习题`, and module names.
- Publish detail pages to `site/problems/senior-high/sets/<section-id>/<lesson-id>.html` through `lesson-data.meta.outputPath`.
- Register topic structure only in `internal/senior-high/catalog/learning-topics.json`; do not hand-edit generated catalog files.
- Keep `chapter=sets`, the correct learning section, and stable `module` routes.
- Rebuild both the detail page and the senior-high catalog after source changes.
- Keep the overview map faithful to the supplied textbook map. Assessment modules may exist without adding an unsupported map branch.

## Mathematical Quality Gate

- Distinguish elements from sets and ordered pairs from two separate elements.
- Enforce certainty, distinctness, and order-independence whenever they affect the result.
- Use `\mathbb N` for natural numbers including zero and `\mathbb N^*` for positive integers; do not add local convention disclaimers.
- Render `\in`, `\notin`, `\setminus`, braces, intervals, radicals, exponents, and fractions structurally.
- Always brace fraction arguments, for example `\frac{3}{2}`; reject shorthand such as `\frac32`.
- If supplied multiple-choice options omit the complete verified answer, convert the aggregate and detail page to a written-response problem and explain the correction without exposing it before submission.

## Final Review

- The topic hierarchy and knowledge map point to the same modules.
- Knowledge and element-property categories are not flattened into one undifferentiated grid.
- Exercises look recognizably different from knowledge blocks and preserve the printed wording.
- Choice problems and typed-answer problems both support online submission.
- Multi-part prompts provide one response field per subquestion.
- Long choices switch to one column on narrow screens.
- Tables enumerate finite cases; number lines prove interval conclusions; Venn diagrams explain regions, overlap, or counting. Pure algebra stays text-only.
- Classification tables distinguish top-level cases from nested subcases; do not flatten “empty set” and the left/right branches of a nonempty interval into one apparent level.
- Multi-row number lines label each input set and the final set or parameter range separately when those objects play different logical roles.
- Every detail step has a valid premise-to-conclusion chain and no raw TeX command leaks into the page.
- Aggregate and detail pages agree on stem, answer, notation, and source.
