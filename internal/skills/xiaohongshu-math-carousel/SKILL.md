---
name: xiaohongshu-math-carousel
description: Create or revise a Xiaohongshu math-learning post from textbook photos, a lesson page, lesson JSON, or an existing carousel. Use when Codex needs traffic-oriented Chinese titles and body copy, a coherent knowledge-point, solving-method, or problem-type carousel, precise SVG-rendered mathematical diagrams, optional ImageGen illustration layers, a concrete final self-test, and a direct shuxueshuo.com call to action for high-school or middle-school mathematics content.
---

# Xiaohongshu Math Carousel

Turn one lesson into a compact teaching story that earns a swipe, demonstrates real instructional value, and gives the reader a reason to visit the interactive page.

## Required Reading

Read `references/editorial-and-visual-playbook.md` before planning the post. When any slide contains a graph, geometric construction, number line, interval shading, logical arrow, table, or formula-heavy diagram, also read `references/svg-math-graphics.md`. Use `assets/post-copy-template.md` for the saved publication copy.

When generating or editing raster slides, also use the `imagegen` skill. Inspect every reference and generated image before editing or approving it.

## Workflow

1. Inspect the source lesson, textbook images, page route, and any existing carousel at full readable resolution. Identify the exact audience, one recurring student error, one visual teaching mechanism, and one concrete exercise that can remain unanswered on the final slide.
2. Verify all mathematics independently. Write both implication directions for condition problems, preserve strict endpoints, and distinguish a proposition, its truth value, and its negation. Do not promote a visually attractive but mathematically ambiguous example.
3. Classify the post before planning slides:

   - `知识点型`: explain what a concept is, why it is true, its conditions, representations, and one transfer question.
   - `解题方法型`: teach when to use a method, its decision signals, procedure, verification, common errors, and one transfer question.
   - `题型型`: expose a problem family's invariant structure, key transformation, worked application, variation, and one parallel problem.

4. Choose one acquisition promise. Prefer a specific student pain point and observable payoff over a generic course label. Draft three titles, then choose the one that can be understood at a glance.
5. Plan a five-to-seven-slide swipe narrative using the matching content-type pattern in the playbook. Give every slide one cognitive job. Do not force a proof into a self-test/reveal sequence or force every topic into seven slides.
6. Route each slide to exactly one rendering mode and record it in `source/slide-manifest.json`; start from `assets/slide-manifest-template.json` and resize its slide list to the actual carousel:

   - `svg`: use for precise mathematics and formula-heavy teaching layouts.
   - `hybrid`: use ImageGen only for a decorative raster layer, then place all mathematics and instructional text in SVG.
   - `imagegen`: use only when the slide contains no spatially exact mathematical relationship.

   Any graph, geometric construction, number line, interval, table, logical arrow, intersection, shaded solution set, or mathematical label requires `svg` or `hybrid`. SVG geometry must be derived from mathematical parameters, not eyeballed coordinates.
7. Write the publication copy using `assets/post-copy-template.md`. Lead with the student problem, not a product announcement. Keep the explanation useful on its own, but reserve the worked interactive judgment for the website. Use a small, relevant tag set; omit internal-production tags such as `#codex` unless the post is explicitly about tooling.
8. Build SVG or hybrid slides first, validate their mathematical invariants, then rasterize them with `scripts/render_svg_slides.cjs`. Generate raster-only layers one image per ImageGen call and save prompt summaries in `generation-prompts.md` when substantial. Never ask ImageGen to typeset final formulas or place exact graph points.
9. Store the deliverables under:

   ```text
   site/assets/xiaohongshu/<post-slug>/
   ├── 01-cover.png
   ├── 02-self-test.png
   ├── 03-<topic>.png
   ├── 04-answer-reveal.png
   ├── 05-<method>.png
   ├── 06-<transfer>.png
   ├── 07-interactive-cta.png
   ├── source/
   │   ├── slide-manifest.json
   │   ├── 01-cover.svg
   │   └── <every svg or hybrid slide source>.svg
   └── post-copy.md
   ```

10. Validate the folder, then inspect all slides sequentially:

   ```bash
   python3 internal/skills/xiaohongshu-math-carousel/scripts/validate_carousel.py \
     site/assets/xiaohongshu/<post-slug> --require-manifest
   ```

11. Report the post type, rendering mode of every slide, saved title/copy path, SVG source paths, PNG paths, dimensions, and which exercise slides intentionally withhold the answer.

## Image Rules

- Produce portrait `1080×1440` PNG images unless the user specifies another ratio.
- Keep the cover's background, palette, typography hierarchy, borders, node shapes, and diagram language consistent across the set.
- Give each slide one cognitive job. Avoid page screenshots, dense paragraphs, tiny formulas, and generic browser mockups as primary content.
- Render stable Unicode mathematics or clean typeset notation. Never expose raw TeX such as `\\Rightarrow`, `\\frac`, `\\mathbb`, or delimiter backslashes.
- Treat the SVG as the source of truth for every precise diagram. Preserve the SVG alongside the exported PNG. Derive function intersections, roots, geometric centers, lengths, endpoint states, and shaded regions from the same underlying parameters.
- Keep instructional text and mathematical labels as deterministic SVG text or paths even in hybrid mode. ImageGen may supply atmosphere or illustration, never the mathematical layer.
- For the logic double-arrow component, use exactly one `p` node and one `q` node per component. Use `p→q` for “充分” and `q→p` for “必要”. Put `✓` or `✕` directly on its arrow line.
- When comparing four condition relations, repeat the complete component in all four cells rather than showing one component plus a detached legend.
- On the final slide, use a real stem and real choices. Do not reveal the answer, highlight a choice, or replace the question with an abstract “continue learning” panel.
- Put `访问 shuxueshuo.com` in the final image. Do not write “从主页入口进入”.

## Copy Rules

- Make the title searchable and specific: audience/topic + pain point or payoff. Avoid self-referential openings such as “可视化某某同学课程”.
- Use the first two body lines as the hook. Explain why the mistake occurs and what the carousel helps the student decide.
- Include two or three compact takeaways that mirror the slides.
- End with one action: answer the final question, then visit `shuxueshuo.com` for the interactive judgment and full explanation.
- Do not promise downloads, worksheets, or features that the destination page does not provide.

## Final Review

- The cover communicates a specific problem in one glance.
- Slide 02 starts the learning story with suspense; slide 04 resolves it.
- The same visual component retains the same arrow direction, colors, labels, and node count on every slide.
- Every condition label agrees with the two implication checks.
- Counterexamples satisfy the failed implication's premise and violate its conclusion.
- Every mathematical graph is derived from its formula; every marked point lies on its curve; every geometric point satisfies its authored constraints.
- Number-line endpoints, excluded points, rays, and shading agree with strictness and domain restrictions.
- Labels do not collide with lines, roots, fraction bars, radicals, points, or one another at phone size.
- Set names and number-line labels come from the actual problem; mappings to `p` and `q` are introduced once without repeated prefixes.
- The last slide contains a concrete unanswered question, readable choices, `shuxueshuo.com`, and a precise reason to visit.
- All Chinese characters, mathematical symbols, answer choices, and page numbers render correctly at phone size.
- All files are `1080×1440`, sequentially named, and present in the repository; every `svg` or `hybrid` slide has a matching source entry in the manifest.
