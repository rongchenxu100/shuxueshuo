# Editorial and Visual Playbook

## Contents

1. Acquisition premise
2. Title and body patterns
3. Story types
4. Visual system
5. Mathematics QA
6. Reference implementation

## 1. Acquisition premise

Brand line (fixed; all 图文 / 视频):

> 美好皆配得，科学练习就能学好数学。

Use this exact sentence on the CTA or closing surface. Do not rotate synonyms. Practical teaching still leads; the brand line closes belief + practice. Method posts may also keep the operating footer `先判断题型与方法，再动手做题`.

The post must provide a useful miniature lesson while making the website's interactive explanation the natural next step. Optimize for four successive decisions:

1. Stop: the cover names a familiar error.
2. Swipe: slide 02 asks a question the reader wants resolved.
3. Trust: slides 03–06 demonstrate a repeatable method, not decorative notes.
4. Visit: slide 07 presents a fresh question, promises the matching interactive explanation, and lands the brand line.

Do not lead with the product name, a page screenshot, or “here are my notes”. Lead with what the student repeatedly gets wrong.

## 2. Title and body patterns

### Title formulas

- `<年级><知识点>总写反？一张图看懂<方法>`
- `<知识点>别再死记：用<视觉机制>一次分清`
- `高一数学｜<易错点>到底怎么判断？`

Example: `高一充分必要条件总写反？看懂两条箭头就会判`

Avoid vague titles such as `可视化高一数学预习` or titles that try to cover an entire chapter.

### Body structure

1. Hook: describe the specific confusion in one or two lines.
2. Payoff: state the visual method the reader will learn.
3. Takeaways: two or three brief points that correspond to carousel slides.
4. Challenge: ask the reader to answer the final slide before revealing anything.
5. CTA: `访问 shuxueshuo.com，查看<与题目对应的互动判断与完整解析>。`
6. Brand: `美好皆配得，科学练习就能学好数学。`
7. Tags: use five to eight topic and audience tags, for example `#高一数学 #高中数学 #充分条件 #必要条件 #数学可视化 #数学学习`.

## 3. Story types

Choose one type before outlining slides. Use five to seven slides; add a slide only when it has a distinct cognitive job.

### 知识点型

Use when the reader needs to understand a definition, theorem, relationship, or proof.

1. Cover: ask the core conceptual question and promise one clear understanding.
2. Anchor: show the definition, phenomenon, or representative question.
3. Structure: expose the concept's parts, conditions, or relationship map.
4. Explanation: give the primary visual proof or derivation.
5. Connection: show another representation, proof, or conceptual consequence.
6. Summary: state the reusable conclusion and equality/domain conditions.
7. Transfer: present one concrete unanswered question and the website handoff.

### 解题方法型

Use when the reader needs to recognize and execute a reusable method.

1. Cover: name the recurring mistake and the method's payoff.
2. Trigger: show a real problem and the signal that should activate the method.
3. Decision: distinguish when the method applies and when it does not.
4. Procedure: visualize the smallest reusable sequence of operations.
5. Application: apply the sequence to the problem from slide 02.
6. Check: verify conditions, endpoints, equality, or a counterexample.
7. Transfer: give a parallel unanswered problem and the website handoff.

### 题型型

Use when several questions share an invariant structure even though their surface expressions differ.

1. Cover: name the problem family in student language and promise recognition.
2. Representative problem: show one clean example without revealing the answer.
3. Structure: mark the invariant roles, known quantities, target, and obstacle.
4. Key transformation: show how the surface form becomes the standard structure.
5. Worked solution: execute the matching method with the current values.
6. Variation: change one condition and show what remains invariant or what changes.
7. Parallel problem: withhold the answer and hand off to the interactive page.

### 专题门厅型（打法 1）

Use for a teaching-topic entry that pairs with method deep-dives. Destination is the topic page (`/topics/<id>/`), not a single worked interactive stem.

Typical 8–10 slide arc:

1. Cover: `<专题>，典型题型有哪些？` + teal button `收藏这一篇就够了` + one feature line per type (**exact topic-page names**).
2. Typical stems: one mini example per type (do not repeat the cover feature list as a signal table).
3. Type pages: one cognitive job each—entry judgment, half-page tip, or bridge concept. Skip full algorithms already covered elsewhere.
4. Optional mix-signals slide when two types are easy to confuse.
5. Self-test: classify a stem; withhold the answer.
6. CTA: topic practice + `shuxueshuo.com` + brand line; phone shows the matching topic page edge-to-edge.

Half-page typical judgment: one key ask + one mini contrast or checklist. Do not expand into a method guide. Point readers to the existing method carousel when needed.

Paired publishing: ship the concepts (or representations) gateway first; follow with the sibling topic gateway or method posts on later days.

### Shared cover and handoff rules

Use one bold contrast and one reusable diagram on the cover. A strong cover can be understood without reading the body copy. On the final slide use a fresh question, not a generic website window. Example:

```text
设 p：x＞3，q：x＞4。
p 是 q 的什么条件？

A 充分不必要条件
B 必要不充分条件
C 充要条件
D 既不充分也不必要条件
```

Do not reveal the correct choice. End with `访问 shuxueshuo.com` and describe the exact interactive explanation.

For sufficient/necessary conditions specifically, use four complete components in the classification slide:

| Sufficient | Necessary | Relation |
|---|---|---|
| ✓ | ✓ | 充要条件 |
| ✓ | ✕ | 充分不必要条件 |
| ✕ | ✓ | 必要不充分条件 |
| ✕ | ✕ | 既不充分也不必要条件 |

Each cell contains exactly one `p`, one `q`, the sufficient arrow, the necessary arrow, and both results. Do not use one central diagram with detached symbol chips.

## 4. Visual system

Default reference style:

- Canvas: 1080×1440, portrait 3:4.
- Background: warm ivory with a faint graph-paper grid.
- Primary: dark teal.
- Success: bright teal.
- Failure/emphasis: coral red.
- Accent: amber.
- Cards: pale mint or ivory, rounded borders, generous internal spacing.
- Typography: large Chinese sans-serif hierarchy; italic serif only for mathematical variables such as `p` and `q`.

Use a previous approved cover as the style reference for all later ImageGen calls. Generate one slide per call to reduce drift and make targeted revisions possible.

## 5. Mathematics QA

- Solve the example before designing it.
- Check `p⇒q` and `q⇒p` independently.
- Verify that each check or cross sits on the correct arrow.
- Preserve strict versus non-strict inequalities.
- Confirm every counterexample belongs to the starting set and not the destination set.
- Keep the same predicates and option order across the image, post copy, lesson page, and detail page.
- Inspect for raw commands, missing superscripts, ambiguous fraction bars, and incorrect Unicode membership symbols.

## 6. Reference implementation

Visual language and condition diagrams:

```text
site/assets/xiaohongshu/common-logical-language-carousel/
```

- `01-cover.png` defines the visual language.
- `03-four-cases.png` demonstrates four complete repeated components.

Topic gateway (打法 1) and CTA phone composite:

```text
site/assets/xiaohongshu/function-concepts-topic-guide-v1/
```

- Cover features + `收藏这一篇就够了`; slide 02 typical stems; self-test then CTA.
- `source/composite-cta.cjs` + mobile topic screenshot for edge-to-edge phone fill.
- Method deep-dives: `function-formula-method-guide-v1`, `function-range-method-guide-v1`.

Treat these as examples, not immutable templates. Change the teaching mechanism when another topic needs a number line, geometry diagram, graph, or table.
