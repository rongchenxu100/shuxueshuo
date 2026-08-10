# Precise SVG Mathematics

Use this reference whenever a slide contains a graph, geometry, number line, interval, table, logical arrow, shaded solution set, or formula-heavy teaching diagram.

## Contents

1. Rendering decision
2. Source model
3. Diagram rules
4. Layout and typography
5. Export workflow
6. Mathematical review

## 1. Rendering decision

Assign every slide one mode in `source/slide-manifest.json`:

- `svg`: all visible content is deterministic SVG.
- `hybrid`: a raster illustration may appear below the SVG, but all mathematics, labels, arrows, and instructional text remain SVG.
- `imagegen`: no spatially exact mathematical relationship appears on the slide.

Never ask ImageGen to draw a function graph, locate a point, construct a circle, typeset a proof, place interval endpoints, or reproduce a table.
Embed a hybrid slide's approved raster layer as a local `data:` URI inside the SVG so export does not depend on an external path or network request.

Example manifest:

```json
{
  "postType": "知识点型",
  "slides": [
    { "png": "01-cover.png", "mode": "svg", "source": "01-cover.svg" },
    { "png": "02-question.png", "mode": "svg", "source": "02-question.svg" },
    { "png": "03-metaphor.png", "mode": "imagegen" },
    { "png": "04-proof.png", "mode": "hybrid", "source": "04-proof.svg" }
  ]
}
```

## 2. Source model

Treat coordinates as output, not authored truth. Start from semantic parameters:

```text
formula / points / constraints / intervals
                    ↓
derived roots, intersections, lengths, centers, endpoint states
                    ↓
SVG coordinates through one scale function
```

Keep the source SVG at `1080×1440` with `viewBox="0 0 1080 1440"`. Put reusable color, spacing, stroke, and type tokens in a top-level `<style>` block. Give important objects stable IDs such as `axis-x`, `root-x1`, `point-D`, and `solution-interval`.

Before writing SVG, independently solve the mathematics and list the invariants the drawing must satisfy. Encode fragile invariants as assertions in the generating script whenever possible.

## 3. Diagram rules

### Function graphs

- Define the mathematical function and domain first.
- Use one coordinate transform for curves, axes, ticks, roots, intersections, and shading.
- Compute roots and threshold intersections from the formulas. Never hand-place the visible marker separately from the curve.
- For piecewise functions, compute both adjacent values at each breakpoint and assert continuity when continuity is expected.
- Shade the solution only after evaluating the requested relation; preserve strict and non-strict endpoints.
- Use a polyline generated from samples or exact line/curve commands whose parameters come from the function. Do not sketch a decorative Bézier curve by eye.

### Geometry

- Define named points numerically or from constraints.
- Derive midpoints, feet, centers, radii, intersections, and lengths from those points.
- Assert required relationships: collinearity, perpendicularity, equal lengths, point-on-circle, point-on-curve, similarity ratios, or area identities.
- Use visible right-angle, equal-length, parallel, and congruence marks only when the corresponding assertion passes.
- Place labels with offsets from their referenced object, then inspect for collisions. A label must not cover a vertex, line, radical bar, fraction bar, or another label.

### Number lines and intervals

- Map all values through one linear scale.
- Derive open/closed endpoint style from `<`, `>`, `≤`, `≥`, exclusions, and domain restrictions.
- Derive rays and shaded segments from the final interval data.
- Put forbidden denominator points above the number line with a visually distinct style.

### Logic arrows and mappings

- Derive arrow direction from the implication being tested.
- Place `✓` or `✕` on the arrow itself.
- Keep node names, arrow colors, direction, and result labels consistent across slides.

### Tables and formula layouts

- Use SVG text and explicit fraction/radical groups, or convert trusted typeset output to paths.
- Do not place raw TeX in visible text.
- Align comparable expressions to a shared baseline and keep fraction bars and radical overbars clear of neighboring labels.

## 4. Layout and typography

- Reserve at least 72 px on every outer edge and a larger bottom safety area when platform UI may cover the image.
- Keep the slide title readable before the diagram; make one formula or visual relation dominant.
- Prefer a small number of large labels over dense prose.
- Keep mathematical strokes at least 3 px at source size and endpoint markers at least 14 px across.
- Preview at approximately 360×480 CSS pixels. If a label or endpoint cannot be read there, revise the layout rather than relying on zoom.
- Preserve the approved palette and diagram grammar across the carousel, but do not distort geometry to fill space.

## 5. Export workflow

1. Save SVG or hybrid sources under `<post-folder>/source/`.
2. Record every slide in `source/slide-manifest.json`.
3. Render SVG entries deterministically:

   ```bash
   NODE_PATH=<workspace-node-modules> <workspace-node> \
     internal/skills/xiaohongshu-math-carousel/scripts/render_svg_slides.cjs \
     site/assets/xiaohongshu/<post-slug>
   ```

   Use `codex_app.load_workspace_dependencies` to locate the bundled Node executable and modules. The renderer requires `sharp`.

4. Run the carousel validator with `--require-manifest`.
5. Inspect every PNG at full size and phone size. Compare the PNG against the SVG source, not against memory.

For a single-slide check:

```bash
NODE_PATH=<workspace-node-modules> <workspace-node> \
  internal/skills/xiaohongshu-math-carousel/scripts/render_svg_slides.cjs \
  path/to/slide.svg path/to/slide.png
```

## 6. Mathematical review

Before approving a slide, answer all applicable questions:

- Does every marked point satisfy its equation or geometric constraint?
- Are roots, intersections, centers, and lengths calculated from the same source data as the drawing?
- Do strictness, endpoint fill, excluded points, arrows, and shading agree with the mathematics?
- Are all similarity, congruence, equality, and area claims visibly supported?
- Does the figure remain correct when parameters are changed within the intended family?
- Is the SVG source preserved and linked from the manifest?
- Did the exported PNG retain all radicals, fraction bars, Chinese characters, and thin strokes?

SVG guarantees reproducibility, not correctness. Mathematical parameters, assertions, and visual inspection are all required.
