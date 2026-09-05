import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";

import { answerTextForSchema, validateTextLesson } from "../build-text-page.mjs";
import { examSourceLabel, renderInlineMathText } from "../lib/lesson-html.mjs";
import { repoRoot } from "./calculus-test-helpers.mjs";

const lessonIds = [
  "set-concept-example-q01",
  "set-concept-example-q02",
  "set-concept-example-q03",
  "set-concept-example-q04",
  "set-element-relation-example-q01",
  "set-element-relation-example-q02",
  "set-practice-q01",
  "set-practice-q02",
  "set-practice-q03",
  "set-practice-q04",
  "set-practice-q05",
  "set-practice-q06",
  ...fs.readdirSync(path.join(repoRoot, "internal/senior-high/lesson-specs"))
    .filter((id) => (
      id.startsWith("set-representation-")
      || id.startsWith("set-relations-")
      || id.startsWith("set-operations-")
      || id.startsWith("inequality-")
    ))
    .sort(),
];
function readLesson(id) {
  return JSON.parse(fs.readFileSync(
    path.join(repoRoot, "internal/senior-high/lesson-specs", id, "lesson-data.json"),
    "utf8",
  ));
}

test("all senior-high text lessons validate and compile to published HTML", () => {
  for (const id of lessonIds) {
    const lesson = validateTextLesson(readLesson(id), id);
    const outputPath = path.join(repoRoot, lesson.meta.outputPath);
    assert.ok(fs.existsSync(outputPath), `${id} should have a compiled page`);
    const html = fs.readFileSync(outputPath, "utf8");
    assert.ok(
      html.includes(`var STEPS      = ${JSON.stringify(lesson.steps)};`),
      `${id} published HTML should embed the latest lesson steps`,
    );
    assert.ok(
      html.includes(`var STEP_LABELS = ${JSON.stringify(lesson.stepLabels ?? {})};`),
      `${id} published HTML should embed the latest step labels`,
    );
    assert.match(html, /"showDiagram":false/);
    assert.doesNotMatch(html, /id="functionSpec"/);
    assert.doesNotMatch(html, /培训教材/);
    assert.match(html, /class="answer-chip"/, id + " should show its final answer");
    assert.match(html, /答案：/, id + " should label its final answer");
  }
});

test("set answer schemas reuse the existing answer chip convention", () => {
  assert.equal(
    answerTextForSchema({ type: "single-choice", expected: "C" }),
    "答案：C",
  );
  assert.equal(
    answerTextForSchema({
      type: "multipart-choice",
      expected: [
        { label: "（1）", expected: "命题" },
        { label: "（2）", expected: "不是命题" },
      ],
    }),
    "答案：（1）命题；（2）不是命题",
  );
  assert.match(
    answerTextForSchema({
      type: "multipart-exact",
      expected: [
        { aliases: ["16"] },
        { aliases: ["29"] },
      ],
    }),
    /（1）.*16.*（2）.*29/,
  );
  assert.equal(
    answerTextForSchema({
      type: "relation-sequence",
      expected: ["⊊", "∉", "⊋"],
    }),
    "答案：\\(\\subsetneq\\)，\\(\\notin\\)，\\(\\supsetneq\\)",
  );
});

test("natural numbers are used directly without local convention disclaimers", () => {
  const forbiddenConvention = /本题约定|本节约定|本专题约定|自然数包含\s*0|采用自然数.*约定/;
  for (const id of lessonIds) {
    assert.doesNotMatch(JSON.stringify(readLesson(id)), forbiddenConvention, id);
  }
  const learningTopics = fs.readFileSync(
    path.join(repoRoot, "internal/senior-high/catalog/learning-topics.json"),
    "utf8",
  );
  assert.doesNotMatch(learningTopics, forbiddenConvention);
});

test("set operation lessons do not use visible backslashes as condition separators", () => {
  const operationIds = lessonIds.filter((id) => id.startsWith("set-operations-"));
  for (const id of operationIds) {
    assert.doesNotMatch(JSON.stringify(readLesson(id)), /\\\\ /, id);
  }
});

test("operation exercise 9-2 excludes a=1 by element distinctness", () => {
  const lesson = readLesson("set-operations-intersection-q05");
  assert.match(JSON.stringify(lesson), /元素具有互异性/);
  assert.match(JSON.stringify(lesson.steps[0].table), /元素重复.*排除/);
  assert.match(JSON.stringify(lesson), /B（0 或 3）/);
});

test("operation exercises 9-3 and 9-4 use number lines for interval boundaries", () => {
  assert.equal(
    readLesson("set-operations-intersection-q06").steps[0].visual.kind,
    "number-line-intersection-nonempty",
  );
  assert.equal(
    readLesson("set-operations-intersection-q07").steps[0].visual.kind,
    "number-line-intersection-empty",
  );
});

test("operation exercise 10-1 separates empty and nonempty branches", () => {
  const lesson = readLesson("set-operations-intersection-q08");
  assert.deepEqual(lesson.steps.map((step) => step.id), ["s1", "s2", "s3"]);
  assert.match(JSON.stringify(lesson.steps[0].reasoning), /B=\\\\varnothing.*a>2/);
  assert.equal(lesson.steps[1].visual.kind, "number-line-subset-left-branch");
  assert.equal(lesson.steps[2].visual.kind, "number-line-subset-right-branch");
  assert.match(JSON.stringify(lesson.steps[2].reasoning), /参数集合要取并集/);
});

test("operation exercises 12-2 and 13-3 explain interval operations on number lines", () => {
  assert.equal(
    readLesson("set-operations-union-q03").steps[0].visual.kind,
    "number-line-union-open-intervals",
  );
  assert.deepEqual(
    readLesson("set-operations-complement-q03").steps.map((step) => step.visual.kind),
    ["number-line-complement-in-universe", "number-line-complement-intersection"],
  );
});

test("operation exercises 13-4 and 13-5 visualize every parameter interval step", () => {
  assert.deepEqual(
    readLesson("set-operations-complement-q04").steps.map((step) => step.visual.kind),
    [
      "number-line-parameter-union",
      "number-line-parameter-containment",
      "number-line-parameter-disjoint",
    ],
  );
  assert.deepEqual(
    readLesson("set-operations-complement-q05").steps.map((step) => step.visual.kind),
    ["number-line-cover-fixed-interval", "number-line-not-subset-cases"],
  );
});

test("relations and operations practice preserves all nine verified answers and visuals", () => {
  const prefix = "set-relations-operations-practice-q0";
  const lessons = Array.from({ length: 9 }, (_, index) => readLesson(`${prefix}${index + 1}`));
  assert.match(JSON.stringify(lessons[0]), /选择 D/);
  assert.match(JSON.stringify(lessons[1]), /选择 C/);
  assert.match(JSON.stringify(lessons[2]), /选择 D/);
  assert.match(JSON.stringify(lessons[3]), /选择 A/);
  assert.match(JSON.stringify(lessons[4]), /选择 B/);
  assert.match(JSON.stringify(lessons[5]), /选择 C/);
  assert.match(JSON.stringify(lessons[6]), /含有 2 个元素/);
  assert.match(JSON.stringify(lessons[7]), /a>1/);
  assert.ok(JSON.stringify(lessons[8]).includes("\\\\([-1,3]\\\\)"));
  assert.deepEqual(
    [lessons[3], lessons[4], lessons[7], lessons[8]].map((lesson) => lesson.steps[0].visual.kind),
    [
      "number-line-practice-union-overlap",
      "number-line-practice-complement-interval",
      "number-line-practice-finite-subset-ray",
      "number-line-practice-a-minus-b",
    ],
  );
  assert.equal(lessons[6].problem.lines[1].figure.shade, "B-only");
  assert.equal(lessons[8].problem.lines[1].figure.shade, "A-only");
});

test("only concrete exam or paper labels are displayed as problem sources", () => {
  assert.equal(examSourceLabel("2026 广东深圳期中"), "2026 广东深圳期中");
  assert.equal(examSourceLabel("2025 辽宁沈阳第一〇中学质量监测"), "2025 辽宁沈阳第一〇中学质量监测");
  assert.equal(examSourceLabel("培训教材 · 集合的概念"), "");
  assert.equal(examSourceLabel("教材习题改编"), "");
  assert.equal(examSourceLabel("集合的概念"), "");
});

test("set lesson answers preserve the independently checked mathematics", () => {
  const example2 = JSON.stringify(readLesson("set-concept-example-q02").steps);
  assert.match(example2, /x.*-1/);
  assert.match(example2, /frac14/);
  assert.match(example2, /frac23/);

  const example3 = JSON.stringify(readLesson("set-concept-example-q03").steps);
  assert.match(example3, /0,1,2/);

  const example4 = JSON.stringify(readLesson("set-concept-example-q04").steps);
  assert.match(example4, /最多有 2 个元素/);

  const relation1 = JSON.stringify(readLesson("set-element-relation-example-q01").steps);
  assert.match(relation1, /notin.*in.*notin.*in.*notin.*in.*in/);

  const relation2 = JSON.stringify(readLesson("set-element-relation-example-q02").steps);
  assert.match(relation2, /正确的是 ①、③，共 2 个，选择 C/);
  assert.match(relation2, /a=0/);

  const practice2 = JSON.stringify(readLesson("set-practice-q02").steps);
  assert.match(practice2, /共有 2 个错误关系/);

  const practice3 = JSON.stringify(readLesson("set-practice-q03").steps);
  assert.ok(practice3.includes("\\\\{2,1,2\\\\}"));
  assert.match(practice3, /元素 2 重复/);
  assert.match(practice3, /a=0.*a=2/);
  assert.match(practice3, /选择 D/);

  const practice4 = JSON.stringify(readLesson("set-practice-q04").steps);
  assert.ok(practice4.includes("-1,2,3,4"));

  const practice5 = JSON.stringify(readLesson("set-practice-q05").steps);
  assert.match(practice5, /a=0/);
  assert.match(practice5, /frac\{9\}\{8\}/);
  assert.doesNotMatch(practice5, /\\\\(?:cup|infty)/);

  const practice4Problem = JSON.stringify(readLesson("set-practice-q04").problem);
  assert.match(practice4Problem, /且a/);
  assert.doesNotMatch(practice4Problem, /\\\\ a/);

  const practice6 = JSON.stringify(readLesson("set-practice-q06").steps);
  assert.ok(practice6.includes("(2,-1"));

  const parameterMembership = JSON.stringify(
    readLesson("set-representation-enumeration-q05").steps,
  );
  assert.match(parameterMembership, /前两个元素重复/);
  assert.match(parameterMembership, /m=2.*m=3/);

  const finiteOrbit = JSON.stringify(
    readLesson("set-representation-description-q14").steps,
  );
  for (const value of ["-1", "-\\\\frac{1}{2}", "\\\\frac{1}{2}", "\\\\frac{2}{3}", "2,3"]) {
    assert.ok(finiteOrbit.includes(value));
  }
  assert.match(finiteOrbit, /p\+q\+r/);
  assert.match(finiteOrbit, /pq\+qr\+rp/);
  assert.match(finiteOrbit, /6t\^3-19t\^2\+t\+6/);
  assert.match(finiteOrbit, /\(t-3\)\(2t\+1\)\(3t-2\)/);

  const interval = JSON.stringify(readLesson("set-representation-interval-q01").steps);
  for (const answer of ["[-1,1]", "[2,+∞)", "(-∞,1]", "[0,+∞)"]) {
    assert.ok(interval.includes(answer));
  }

  const threeDayMinimum = JSON.stringify(readLesson("set-representation-venn-q04").steps);
  assert.match(threeDayMinimum, /29/);
});

test("practice assessment lessons use complete mathematical derivations and purposeful visuals", () => {
  const practiceIds = Array.from({ length: 6 }, (_, index) => (
    `set-practice-q0${index + 1}`
  ));
  const lessons = practiceIds.map(readLesson);
  assert.ok(lessons.every((lesson) => lesson.steps.every((step) => (
    Array.isArray(step.reasoning)
    && step.reasoning.some((line) => line.kind === "because")
    && step.reasoning.some((line) => line.kind === "therefore")
  ))));

  assert.ok(readLesson("set-practice-q01").steps[0].table.rows.length >= 4);
  assert.ok(readLesson("set-practice-q02").steps[0].table.rows.length >= 4);
  assert.ok(readLesson("set-practice-q03").steps[0].table.rows.length >= 2);
  assert.ok(readLesson("set-practice-q04").steps[1].table.headers.length >= 5);
  assert.equal(
    readLesson("set-practice-q05").steps[1].visual.kind,
    "number-line-practice-parameter",
  );
  assert.ok(readLesson("set-practice-q06").steps.every((step) => !step.visual));
});

test("generic lesson math renderer supports set notation without leaking TeX commands", () => {
  const html = renderInlineMathText(
    "\\(x\\in\\mathbb R\\)，\\(x\\notin\\varnothing\\)，"
      + "\\(\\sqrt[3]{a^3}=a\\)，\\(\\pi\\ne0\\)，"
      + "\\(|x|\\le1\\iff-1\\le x\\le1\\)，"
      + "\\(M=\\left\\{a\\middle|a\\ge\\frac98\\right\\}\\)，"
      + "\\(A\\subsetneq B\\supsetneq C\\)，"
      + "\\(Q\\setminus P\\)，\\(A\\cap B\\cup C\\)，"
      + "\\(p\\Rightarrow q\\)，\\(p\\nRightarrow q\\)，\\(p\\Leftrightarrow q\\)，"
      + "\\((-\\infty,1]\\)，\\(a<0\\text{或}a>2\\)",
  );
  assert.match(html, /x∈<span class="math-blackboard">ℝ<\/span>/);
  assert.match(html, /x<span class="math-notin"[^>]*><svg[^>]*>.*?<path[^>]*><\/svg><\/span>∅/);
  assert.match(html, /∛/);
  assert.match(html, /π≠0/);
  assert.match(html, /≤1⇔-1≤/);
  assert.match(html, /a≥/);
  assert.match(html, /A⊊\s*B⊋\s*C/);
  assert.match(html, /Q∖\s*P/);
  assert.match(html, /A∩\s*B∪\s*C/);
  assert.match(html, /p⇒\s*q/);
  assert.match(html, /p⇏\s*q/);
  assert.match(html, /p⇔\s*q/);
  assert.match(html, /∞,1/);
  assert.match(html, /a&lt;0或a&gt;2/);
  assert.match(html, /class="math-blackboard"/);
  assert.doesNotMatch(html, /\\(?:mathbb|in|notin|varnothing|sqrt|pi|iff|left|right|middle|setminus|cap|cup|infty|text|Rightarrow|nRightarrow|Leftrightarrow)/);

  const sandbox = { window: {} };
  vm.runInNewContext(
    fs.readFileSync(path.join(repoRoot, "site/assets/js/lesson-page-runtime.js"), "utf8"),
    sandbox,
  );
  const runtimeHtml = sandbox.window.LessonPageRuntime.renderFormulaText(
    "\\(A\\subsetneq B\\supsetneq C\\supseteq D\\)，\\(Q\\setminus P\\)，"
      + "\\(p\\Rightarrow q\\)，\\(p\\nRightarrow q\\)，\\(p\\Leftrightarrow q\\)",
  );
  assert.match(runtimeHtml, /A⊊ B⊋ C⊇ D/);
  assert.match(runtimeHtml, /Q∖ P/);
  assert.match(runtimeHtml, /p⇒ q/);
  assert.match(runtimeHtml, /p⇏ q/);
  assert.match(runtimeHtml, /p⇔ q/);
  assert.doesNotMatch(runtimeHtml, /\\(?:subsetneq|supsetneq|supseteq|setminus|Rightarrow|nRightarrow|Leftrightarrow)/);
});

test("set representation fractions use braced arguments and compile both parts", () => {
  const representationIds = lessonIds.filter((id) => id.startsWith("set-representation-"));
  for (const id of representationIds) {
    const lesson = readLesson(id);
    assert.doesNotMatch(JSON.stringify(lesson), /\\frac(?!\{)/, `${id} has TeX fraction shorthand`);
    assert.doesNotMatch(JSON.stringify(lesson), /\\\\times/, `${id} leaks an unsupported times command`);

    const html = fs.readFileSync(path.join(repoRoot, lesson.meta.outputPath), "utf8");
    assert.doesNotMatch(html, /math-numerator">\s*<\/span>/, `${id} has an empty numerator`);
    assert.doesNotMatch(html, /math-denominator">\s*<\/span>/, `${id} has an empty denominator`);
  }
});

test("set representation Venn questions compile semantic vector figures", () => {
  for (const id of ["set-representation-venn-q01", "set-representation-venn-q02"]) {
    const html = fs.readFileSync(path.join(repoRoot, readLesson(id).meta.outputPath), "utf8");
    assert.match(html, /class="set-figure"/);
    assert.match(html, /role="img"/);
    assert.match(html, /set-figure-shade/);
    assert.match(html, /<mask id="venn-[ab]-minus-[ab]-mask"/);
    assert.match(html, /mask="url\(#venn-[ab]-minus-[ab]-mask\)"/);
    assert.doesNotMatch(html, /M(?:213|267) 58a76/);
  }
});

test("exercises 9 through 11 use explicit mathematical derivations", () => {
  const ids = [
    "set-representation-interval-q01",
    "set-representation-venn-q01",
    "set-representation-venn-q02",
    "set-representation-venn-q03",
    "set-representation-venn-q04",
  ];
  for (const id of ids) {
    const lesson = readLesson(id);
    assert.ok(lesson.steps.every((step) => (
      Array.isArray(step.reasoning)
      && step.reasoning.some((line) => line.kind === "because")
      && step.reasoning.some((line) => line.kind === "therefore")
    )), `${id} should provide a complete mathematical reasoning chain`);
  }
  const vennOne = JSON.stringify(readLesson("set-representation-venn-q01").steps);
  assert.match(vennOne, /B∖A/);
  assert.match(vennOne, /\(0,1\]/);
  const vennFour = JSON.stringify(readLesson("set-representation-venn-q04").steps);
  assert.match(vennFour, /完全包含.*恰好取到 16/);
  assert.match(vennFour, /13\+16=29/);
});

test("exercises 9 through 11 carry the requested explanatory visuals", () => {
  const interval = readLesson("set-representation-interval-q01");
  assert.equal(interval.steps[0].table.headers[0], "原集合");
  assert.deepEqual(
    interval.steps[0].table.rows.map((row) => row[0]),
    [
      "\\(\\{x\\mid |x|\\le1\\}\\)",
      "\\(\\{y\\mid y=\\sqrt{x}+2\\}\\)",
      "\\(\\{y\\mid y=-x^2+2x\\}\\)",
      "\\(\\{y\\mid y=x^2-2x+1,x>0\\}\\)",
    ],
  );

  const vennOne = readLesson("set-representation-venn-q01");
  assert.equal(vennOne.steps[0].visual.kind, "number-line-difference");

  const vennTwo = readLesson("set-representation-venn-q02");
  assert.equal(vennTwo.steps[0].table.rows.length, 5);
  assert.deepEqual(vennTwo.steps[0].table.rows[0], ["0", "否", "保留"]);

  const vennThree = readLesson("set-representation-venn-q03");
  assert.equal(vennThree.steps[0].visual.kind, "venn-two-counts");

  const vennFour = readLesson("set-representation-venn-q04");
  assert.equal(vennFour.steps[0].visual.kind, "venn-day-one-two-counts");
  assert.equal(vennFour.steps[1].visual.kind, "venn-min-union");
  assert.match(JSON.stringify(vennFour.steps[1].reasoning), /分成两块/);
  assert.match(JSON.stringify(vennFour.steps[1].reasoning), /完全包含.*恰好取到 16/);

  const runtime = fs.readFileSync(
    path.join(repoRoot, "site/assets/js/lesson-page-runtime.js"),
    "utf8",
  );
  for (const kind of [
    "number-line-difference",
    "venn-two-counts",
    "venn-day-one-two-counts",
    "venn-min-union",
    "number-line-practice-parameter",
    "number-line-subset-left-branch",
    "number-line-subset-right-branch",
    "number-line-union-open-intervals",
    "number-line-complement-in-universe",
    "number-line-complement-intersection",
    "number-line-parameter-union",
    "number-line-parameter-containment",
    "number-line-parameter-disjoint",
    "number-line-cover-fixed-interval",
    "number-line-not-subset-cases",
    "number-line-practice-union-overlap",
    "number-line-practice-complement-interval",
    "number-line-practice-finite-subset-ray",
    "number-line-practice-a-minus-b",
  ]) {
    assert.match(runtime, new RegExp(kind));
  }
});

test("text lessons carry structured classification tables into the shared runtime", () => {
  const example3 = readLesson("set-concept-example-q03");
  assert.deepEqual(example3.steps[1].table.headers, ["参数条件", "实根情况", "根集元素个数"]);
  assert.equal(example3.steps[1].table.rows.length, 3);

  const runtime = fs.readFileSync(
    path.join(repoRoot, "site/assets/js/lesson-page-runtime.js"),
    "utf8",
  );
  assert.match(runtime, /<table class="lesson-reasoning-table">/);
  assert.match(runtime, /scope="col"/);
  assert.match(runtime, /scope="row"/);
});

test("both columns of a derivation line render inline mathematics", () => {
  const runtime = fs.readFileSync(
    path.join(repoRoot, "site/assets/js/lesson-page-runtime.js"),
    "utf8",
  );
  assert.match(
    runtime,
    /<div class="derive-line"><strong>' \+\s*renderFormulaText\(pair\[0\]\)/,
  );
  assert.doesNotMatch(
    runtime,
    /<div class="derive-line"><strong>' \+\s*esc\(String\(pair\[0\]/,
  );
});

test("authored logical chains use explicit because and therefore lines", () => {
  const enumerationIds = Array.from({ length: 6 }, (_, index) => (
    `set-representation-enumeration-q0${index + 1}`
  ));
  const lessons = enumerationIds.map(readLesson);
  assert.ok(lessons.every((lesson) => lesson.steps.every((step) => (
    Array.isArray(step.reasoning)
    && step.reasoning.some((line) => line.kind === "because")
    && step.reasoning.some((line) => line.kind === "therefore")
  ))));

  const q02 = readLesson("set-representation-enumeration-q02");
  assert.deepEqual(q02.steps[0].reasoning.map((line) => line.kind), [
    "because",
    "therefore",
    "therefore",
    "therefore",
  ]);
  assert.match(q02.steps[0].reasoning[2].text, /有序数对/);
  assert.match(q02.steps[0].reasoning[3].text, /解集为/);

  const descriptionIds = Array.from({ length: 6 }, (_, index) => (
    `set-representation-description-q0${index + 1}`
  ));
  const descriptionLessons = descriptionIds.map(readLesson);
  assert.ok(descriptionLessons.every((lesson) => lesson.steps.every((step) => (
    Array.isArray(step.reasoning)
    && step.reasoning.some((line) => line.kind === "because")
    && step.reasoning.some((line) => line.kind === "therefore")
  ))));

  const descriptionQ05 = readLesson("set-representation-description-q05");
  assert.match(descriptionQ05.problem.lines[0].text, /\\frac\{a\}\{b\}/);
  assert.doesNotMatch(JSON.stringify(descriptionQ05), /\\\\frac(?:\s*[a-zA-Z0-9]|\d)/);

  const advancedDescriptionIds = Array.from({ length: 8 }, (_, index) => (
    `set-representation-description-q${String(index + 7).padStart(2, "0")}`
  ));
  const advancedDescriptionLessons = advancedDescriptionIds.map(readLesson);
  assert.ok(advancedDescriptionLessons.every((lesson) => lesson.steps.every((step) => (
    Array.isArray(step.reasoning)
    && step.reasoning.some((line) => line.kind === "because")
    && step.reasoning.some((line) => line.kind === "therefore")
  ))));
  assert.doesNotMatch(
    JSON.stringify(readLesson("set-representation-description-q14")),
    /轨道/,
  );
  const descriptionQ09 = readLesson("set-representation-description-q09");
  assert.equal(descriptionQ09.steps[0].title, "枚举所有符合条件的有序数对");
  assert.match(
    JSON.stringify(descriptionQ09.problem.keyPoints),
    /集合不大时枚举所有情况.*集合较大时先枚举部分情况.*发现规律后再计数/,
  );
  const exerciseEightIds = Array.from({ length: 6 }, (_, index) => (
    `set-representation-description-q${String(index + 9).padStart(2, "0")}`
  ));
  assert.ok(exerciseEightIds.every((id) => (
    readLesson(id).steps.every((step) => step.table?.rows?.length > 0)
  )));
  const descriptionQ12 = readLesson("set-representation-description-q12");
  assert.match(descriptionQ12.steps[0].table.caption, /从小到大重新编号/);
  assert.match(
    JSON.stringify(descriptionQ12.steps[0].reasoning),
    /0<a_1<a_2<\\\\cdots<a_\{20\}/,
  );
  assert.match(
    JSON.stringify(descriptionQ12.steps[0].reasoning),
    /前面恰有.*i-1.*个较小元素/,
  );

  const runtime = fs.readFileSync(
    path.join(repoRoot, "site/assets/js/lesson-page-runtime.js"),
    "utf8",
  );
  assert.match(runtime, /renderReasoningLine/);
  assert.match(runtime, /isBecause \? "因为" : "所以"/);
  assert.match(runtime, /isBecause \? "∵" : "∴"/);
});

test("set relation lessons preserve the verified answers and full reasoning chains", () => {
  const relationIds = lessonIds.filter((id) => (
    id.startsWith("set-relations-")
    && !id.startsWith("set-relations-operations-practice-")
  ));
  assert.equal(relationIds.length, 19);
  for (const id of relationIds) {
    const lesson = readLesson(id);
    assert.ok(lesson.steps.every((step) => (
      Array.isArray(step.reasoning)
      && step.reasoning.some((line) => line.kind === "because")
      && step.reasoning.some((line) => line.kind === "therefore")
    )), `${id} should provide a complete mathematical reasoning chain`);
  }
  assert.match(JSON.stringify(readLesson("set-relations-count-q02")), /2\^4-2=14/);
  assert.ok(JSON.stringify(readLesson("set-relations-count-q04")).includes("\\\\{2,8\\\\}"));
  assert.ok(JSON.stringify(readLesson("set-relations-interval-q01")).includes("m\\\\le3"));
});

test("inequality property lesson cites named properties and gives counterexamples", () => {
  const lesson = readLesson("inequality-property-q01");
  const keyPoints = JSON.stringify(lesson.problem.keyPoints);
  const step = JSON.stringify(lesson.steps[0]);
  const table = lesson.steps[0].table;
  assert.match(keyPoints, /基本性质·可乘性/);
  assert.match(keyPoints, /运算性质·可加法则/);
  assert.deepEqual(table.headers, ["选项", "关键判断", "反例代入计算", "结论"]);
  assert.match(step, /a=1，b=-1/);
  assert.match(step, /a=-2，b=-1/);
  assert.match(step, /a=2，b=1，c=2，d=1/);
  assert.ok(table.rows[0][2].includes("\\frac{1}{1}=1"));
  assert.ok(table.rows[0][2].includes("\\frac{1}{-1}=-1"));
  assert.match(table.rows[1][2], /\(-2\)\^2=4/);
  assert.match(table.rows[1][2], /\(-2\)×\(-1\)=2/);
  assert.doesNotMatch(step, /\\\\times/);
  assert.match(table.rows[3][2], /a-c=2-2=0/);
  assert.match(table.rows[3][2], /b-d=1-1=0/);
  assert.match(step, /同乘正数.*方向不变/);
  assert.deepEqual(lesson.steps[0].derive[0], ["使用性质", "基本性质·可乘性"]);
});

test("second inequality property lesson follows the same property-and-counterexample template", () => {
  const lesson = readLesson("inequality-property-q02");
  const table = lesson.steps[0].table;
  const step = JSON.stringify(lesson.steps[0]);
  assert.deepEqual(table.headers, ["选项", "关键判断", "反例代入计算", "结论"]);
  assert.match(JSON.stringify(lesson.problem.keyPoints), /实数的符号法则.*基本性质·可乘性/);
  assert.ok(table.rows[0][2].includes("\\frac{1}{1}=1"));
  assert.match(table.rows[0][2], /原结论变为.*1<-1/);
  assert.match(table.rows[1][2], /ab\^2=1×0\^2=0/);
  assert.match(table.rows[1][2], /a\^2b=1\^2×0=0/);
  assert.ok(table.rows[1][2].includes("\\frac{1}{0}"));
  assert.match(table.rows[3][2], /a\\?\|c\\?\|=1×0=0/);
  assert.match(table.rows[3][2], /b\\?\|c\\?\|=0×0=0/);
  assert.match(step, /c\^2\+1.*同除正数.*方向不变/);
  assert.doesNotMatch(step, /\\\\times/);
  assert.deepEqual(
    lesson.steps[0].derive[0],
    ["使用性质", "实数的符号法则；基本性质·可乘性"],
  );
});

test("all inequality comparison exercises explicitly teach the difference method", () => {
  const lessonIds = [
    "inequality-compare-q01",
    "inequality-compare-q02",
    "inequality-compare-q03",
    "inequality-compare-q04",
    "inequality-compare-q05",
  ];
  for (const lessonId of lessonIds) {
    const lesson = readLesson(lessonId);
    assert.match(lesson.problem.keyPoints.lead, /作差法/);
    assert.match(lesson.steps[0].title, /^作差法：/);
    assert.match(JSON.stringify(lesson.steps[0].reasoning), /使用作差法/);
    assert.deepEqual(lesson.steps[0].derive[0], ["使用方法", "作差法"]);
  }

  const fractionLesson = readLesson("inequality-compare-q05");
  assert.ok(fractionLesson.problem.lines[0].text.includes("\\frac{b}{a}"));
  assert.doesNotMatch(JSON.stringify(fractionLesson), /\\\\frac ba/);
  assert.match(JSON.stringify(fractionLesson.steps[0]), /右式减左式/);
  assert.match(JSON.stringify(fractionLesson.steps[0]), /\(a-b\)\(a\+b\+m\)/);
  assert.doesNotMatch(JSON.stringify(fractionLesson), /中间量/);
});

test("inequality range lesson teaches the regroup-bound-add workflow", () => {
  const lesson = readLesson("inequality-range-q01");
  assert.equal(lesson.problem.keyPoints.kind, "linear-combination-range-flow");
  assert.deepEqual(lesson.problem.keyPoints.stages.map((stage) => stage.label), ["重组", "求界", "相加"]);
  assert.deepEqual(lesson.problem.keyPoints.stages.map((stage) => stage.visual), ["regroup", "bound", "add"]);
  assert.match(JSON.stringify(lesson.problem.keyPoints), /T=pU\+qV/);
  assert.doesNotMatch(JSON.stringify(lesson.problem.keyPoints), /3a\+2b|\[2,11\]|\\frac52/);
  assert.deepEqual(lesson.steps.map((step) => step.title), [
    "重组：用待定系数法表示目标式",
    "求界：分别求两部分的新范围",
    "相加：对应端点相加得到目标范围",
  ]);
  assert.ok(lesson.steps[0].reasoning[1].text.includes("λ+μ=3"));
  assert.doesNotMatch(JSON.stringify(lesson), /\\\\lambda|\\\\mu/);
  assert.equal(lesson.steps[0].visual, undefined);
  assert.match(JSON.stringify(lesson.steps[1]), /基本性质·可乘性/);
  assert.match(JSON.stringify(lesson.steps[2]), /运算性质·可加法则/);
  assert.match(JSON.stringify(lesson.steps[2]), /端点能同时取到/);
  assert.deepEqual(lesson.steps[2].derive[0], ["取值范围", "[2,11]"]);

  const htmlHelpers = fs.readFileSync(
    path.join(repoRoot, "tools/lib/lesson-html.mjs"),
    "utf8",
  );
  assert.match(htmlHelpers, /linear-combination-range-flow/);
  assert.match(htmlHelpers, /lesson-method-map/);
  assert.match(htmlHelpers, /lesson-range-flow-visual/);
});

test("second inequality range lesson reuses the same three-step map and full derivation", () => {
  const lesson = readLesson("inequality-range-q02");
  assert.equal(lesson.problem.keyPoints.kind, "linear-combination-range-flow");
  assert.deepEqual(lesson.problem.keyPoints.stages.map((stage) => stage.label), ["重组", "求界", "相加"]);
  assert.deepEqual(lesson.steps.map((step) => step.title), [
    "重组：用待定系数法表示目标式",
    "求界：分别求两部分的新范围",
    "相加：对应端点相加得到目标范围",
  ]);
  assert.match(JSON.stringify(lesson.steps[0]), /2p\+q=10/);
  assert.match(JSON.stringify(lesson.steps[1]), /基本性质·可乘性/);
  assert.match(JSON.stringify(lesson.steps[2]), /运算性质·可加法则/);
  assert.match(JSON.stringify(lesson.steps[2]), /端点能同时取到/);
  assert.deepEqual(lesson.steps[2].derive[0], ["取值范围", "[-1,20]"]);
});

test("first basic inequality exercise splits observe / apply / equality steps", () => {
  const lesson = readLesson("inequality-basic-q01");
  assert.equal(lesson.problem.keyPoints.lead, "");
  assert.match(lesson.problem.keyPoints.items[1], /代入基本不等式公式与定和/);
  assert.doesNotMatch(lesson.problem.keyPoints.items[1], /代入槽位/);
  assert.deepEqual(
    lesson.steps.map((step) => [step.id, step.title]),
    [
      ["s1", "观察结构"],
      ["s2", "应用基本不等式"],
      ["s3", "验证取等"],
    ],
  );
  assert.equal(lesson.steps[0].visual.kind, "basic-inequality-structure-scan");
  assert.match(lesson.steps[0].visual.condition.expression, /m\+n=2/);
  assert.match(lesson.steps[0].visual.target.expression, /mn/);
  assert.equal(lesson.steps[0].visual.condition.tag, "定和");
  assert.equal(lesson.steps[0].visual.target.tag, "积");
  assert.deepEqual(lesson.steps[0].visual.pattern, {
    first: { value: "m", shape: "square" },
    second: { value: "n", shape: "circle" },
    condition: { operator: "+", tag: "定和" },
    target: { operator: "·", tag: "求最大值" },
    ariaLabel: "同一组正项 m、n：和固定，求积的最大值",
  });
  assert.equal(lesson.steps[0].visual.reading, "定和求积");
  assert.equal(lesson.steps[0].visual.route, "直接应用基本不等式");
  assert.equal(lesson.steps[0].visual.title, undefined);
  assert.equal(lesson.steps[0].visual.caption, undefined);
  assert.deepEqual(lesson.steps[0].derive[0], ["结构判断", "定和求积｜直接应用"]);

  const visual = lesson.steps[1].visual;
  assert.equal(visual.kind, "basic-inequality-mapping");
  assert.deepEqual(
    visual.mappings.map((mapping) => [mapping.slot, mapping.shape, mapping.value]),
    [["第一个正项", "square", "m"], ["第二个正项", "circle", "n"]],
  );
  assert.match(visual.fixedCondition, /m\+n=2/);
  assert.match(visual.replaced, /2\\ge2\\sqrt\{mn\}/);
  assert.match(visual.conclusion, /mn\\le1/);
  assert.equal(visual.templateLabel, "代入基本不等式");
  assert.equal(visual.formulaStyle, "sum-geometric");
  assert.equal(visual.showPositiveStep, true);
  assert.equal(visual.title, undefined);
  assert.equal(visual.caption, undefined);
  assert.equal(visual.equalityResult, undefined);
  assert.equal(visual.methodTag, "直接应用｜定和求积");
  assert.deepEqual(lesson.steps[1].reasoning.map((item) => item.kind), ["because", "therefore", "because", "therefore", "therefore"]);
  for (const item of lesson.steps.flatMap((step) => step.reasoning)) {
    assert.doesNotMatch(item.text, /\\Rightarrow|因为|所以|。$/);
  }
  assert.equal(lesson.steps[2].visual.kind, "basic-inequality-equality-check");
  assert.match(lesson.steps[2].visual.condition, /m\+n=2/);
  assert.match(lesson.steps[2].visual.conclusion, /最大值为/);
  assert.match(lesson.steps[2].reasoning[0].text, /两个正项相等/);
  assert.doesNotMatch(lesson.steps[2].reasoning[0].text, /槽位/);
  assert.deepEqual(lesson.steps[2].derive, [["最大值", "1"], ["等号条件", "m=n=1"]]);

  const html = fs.readFileSync(path.join(repoRoot, lesson.meta.outputPath), "utf8");
  assert.match(html, /basic-inequality-structure-scan/);
  assert.match(html, /basic-inequality-mapping/);
  assert.match(html, /basic-inequality-equality-check/);
  assert.match(html, /观察结构/);
  assert.match(html, /应用基本不等式/);
  assert.match(html, /验证取等/);
  const runtime = fs.readFileSync(
    path.join(repoRoot, "site/assets/js/lesson-page-runtime.js"),
    "utf8",
  );
  assert.match(runtime, /lesson-step-basic-structure-scan/);
  assert.match(runtime, /basic-structure-focus/);
  assert.match(runtime, /basic-structure-pattern/);
  assert.match(runtime, /lesson-step-basic-inequality-map/);
  assert.match(runtime, /basic-map-source-grid/);
  assert.match(runtime, /basic-map-positive-board/);
  assert.match(runtime, /basic-map-formula-slot-stack/);
  assert.match(runtime, /is-sum-geometric/);
  assert.match(runtime, /lesson-step-basic-equality-check/);
  assert.match(runtime, /basic-map-sum-target/);
  assert.match(runtime, /basic-map-product-target/);
  assert.match(runtime, /has-product-fixed-source/);
  assert.match(runtime, /has-fixed-source/);
  assert.match(runtime, /mapping\.shape === "square" \|\| mapping\.shape === "circle"/);
  assert.match(runtime, /" is-shape is-slot-" \+ shape/);
});

test("second basic inequality exercise reuses observe / apply / equality steps for reciprocal terms", () => {
  const lesson = readLesson("inequality-basic-q02");
  assert.equal(lesson.problem.keyPoints.lead, "");
  assert.match(lesson.problem.keyPoints.items[1], /代入基本不等式公式与定和/);
  assert.doesNotMatch(lesson.problem.keyPoints.items[1], /方框|圆框|槽位/);
  assert.deepEqual(
    lesson.steps.map((step) => [step.id, step.title]),
    [
      ["s1", "观察结构"],
      ["s2", "应用基本不等式"],
      ["s3", "验证取等"],
    ],
  );
  assert.equal(lesson.steps[0].visual.kind, "basic-inequality-structure-scan");
  assert.match(lesson.steps[0].visual.condition.expression, /\\frac\{1\}\{x\}\+\\frac\{1\}\{y\}=1/);
  assert.match(lesson.steps[0].visual.target.expression, /xy/);
  assert.equal(lesson.steps[0].visual.pattern.condition.tag, "定和");
  assert.equal(lesson.steps[0].visual.pattern.target.tag, "先求最大值");

  const visual = lesson.steps[1].visual;
  assert.equal(visual.kind, "basic-inequality-mapping");
  assert.deepEqual(
    visual.mappings.map((mapping) => [mapping.slot, mapping.shape, mapping.value]),
    [
      ["第一个正项", "square", "\\(\\frac{1}{x}\\)"],
      ["第二个正项", "circle", "\\(\\frac{1}{y}\\)"],
    ],
  );
  assert.match(visual.fixedCondition, /\\frac\{1\}\{x\}\+\\frac\{1\}\{y\}=1/);
  assert.match(visual.mappedProduct, /\\frac\{1\}\{xy\}/);
  assert.match(visual.replaced, /1\\ge\\frac\{2\}\{\\sqrt\{xy\}\}/);
  assert.match(visual.substituted, /\\sqrt\{xy\}\\ge2/);
  assert.match(visual.conclusion, /xy\\ge4/);
  assert.equal(visual.methodTag, "直接应用｜定和求积");
  assert.equal(visual.stageLabel, "代入定和");
  assert.equal(visual.formulaStyle, "sum-geometric");
  assert.equal(visual.showPositiveStep, true);
  assert.equal(visual.conditionFlow, undefined);
  assert.match(visual.simplifyLabel, /取倒数，方向反转/);
  assert.equal(lesson.steps[2].visual.kind, "basic-inequality-equality-check");
  assert.match(lesson.steps[2].visual.solved, /x=y=2/);
  assert.match(lesson.steps[2].visual.verification, /xy=4/);
  for (const item of lesson.steps.flatMap((step) => step.reasoning)) {
    assert.doesNotMatch(item.text, /\\Rightarrow|因为|所以|。$/);
  }
});

test("third basic inequality exercise separates observation, homogenization, AM-GM, and equality checking", () => {
  const lesson = readLesson("inequality-basic-q03");
  assert.equal(lesson.problem.keyPoints.lead, "");
  assert.deepEqual(
    lesson.steps.map((step) => [step.id, step.title]),
    [
      ["s1", "观察结构"],
      ["s2", "配齐次式"],
      ["s3", "应用基本不等式"],
      ["s4", "验证取等"],
    ],
  );

  const observation = lesson.steps[0].visual;
  assert.equal(lesson.steps[0].section, "配齐次式");
  assert.equal(observation.kind, "basic-inequality-structure-scan");
  assert.match(observation.condition.expression, /\\frac\{1\}\{x\}\+\\frac\{1\}\{y\}=1/);
  assert.match(observation.target.expression, /x\+4y/);
  assert.equal(observation.reading, "次数配成 0");
  assert.equal(observation.route, "配齐次式");
  const homogenizationHint = observation.organization.homogenizationHint;
  assert.deepEqual(
    [homogenizationHint.originalDegree, homogenizationHint.conditionDegree, homogenizationHint.resultDegree],
    ["+1", "−1", "0"],
  );
  assert.match(homogenizationHint.result, /5\+\\frac\{x\}\{y\}\+\\frac\{4y\}\{x\}/);
  assert.equal(homogenizationHint.balance, "\\((+1)+(-1)=0\\)");

  const construction = lesson.steps[1].visual;
  assert.equal(construction.kind, "basic-inequality-structure-scan");
  assert.equal(construction.showFocus, false);
  assert.equal(construction.organization.label, "配齐次式：乘入条件并展开");
  assert.match(construction.organization.steps.join(""), /x\+4y.*\\frac\{1\}\{x\}.*5\+\\frac\{x\}\{y\}\+\\frac\{4y\}\{x\}/);
  assert.deepEqual(
    [construction.pattern.first, construction.pattern.second].map((item) => [item.shape, item.value]),
    [["square", "\\(\\frac{x}{y}\\)"], ["circle", "\\(\\frac{4y}{x}\\)"]],
  );
  assert.equal(construction.pattern.condition.tag, "定积 4");

  const mapping = lesson.steps[2].visual;
  assert.equal(mapping.kind, "basic-inequality-mapping");
  assert.equal(mapping.methodTag, "配齐次式｜定积求和");
  assert.deepEqual(
    mapping.mappings.map((item) => [item.shape, item.value]),
    [["square", "\\(\\frac{x}{y}\\)"], ["circle", "\\(\\frac{4y}{x}\\)"]],
  );
  assert.match(mapping.fixedCondition, /=4/);
  assert.match(mapping.conclusion, /x\+4y\\ge9/);

  const equality = lesson.steps[3].visual;
  assert.equal(equality.kind, "basic-inequality-equality-check");
  assert.match(equality.solved, /x=3/);
  assert.match(equality.verification, /x\+4y=9/);

  const runtime = fs.readFileSync(
    path.join(repoRoot, "site/assets/js/lesson-page-runtime.js"),
    "utf8",
  );
  assert.match(runtime, /basic-structure-homogenization-hint/);
  assert.match(runtime, /homogeneous-slot-equation/);
  assert.match(runtime, /lesson-step-basic-inequality-map/);
  assert.match(runtime, /lesson-step-basic-equality-check/);
});

test("fourth basic inequality exercise constructs a fixed product from the fixed sum", () => {
  const lesson = readLesson("inequality-basic-q04");
  assert.equal(lesson.problem.keyPoints.lead, "");
  assert.deepEqual(
    lesson.steps.map((step) => [step.id, step.title]),
    [
      ["s1", "观察结构"],
      ["s2", "配齐次式"],
      ["s3", "应用基本不等式"],
      ["s4", "验证取等"],
    ],
  );

  const observation = lesson.steps[0].visual;
  assert.equal(lesson.steps[0].section, "配齐次式");
  assert.equal(observation.kind, "basic-inequality-structure-scan");
  assert.equal(observation.condition.tag, "正一次");
  assert.equal(observation.target.tag, "负一次");
  const homogenizationHint = observation.organization.homogenizationHint;
  assert.deepEqual(
    [homogenizationHint.originalDegree, homogenizationHint.conditionDegree, homogenizationHint.resultDegree],
    ["−1", "+1", "0"],
  );
  assert.match(homogenizationHint.result, /15\+\\frac\{9b\}\{a\}\+\\frac\{4a\}\{b\}/);

  const construction = lesson.steps[1].visual;
  assert.equal(construction.kind, "basic-inequality-structure-scan");
  assert.equal(construction.showFocus, false);
  assert.match(construction.organization.steps.join(""), /2.*\\frac\{3\}\{a\}.*a\+3b.*15/);
  assert.equal(construction.pattern.condition.tag, "定积 36");

  const application = lesson.steps[2].visual;
  assert.equal(application.kind, "basic-inequality-mapping");
  assert.deepEqual(
    application.mappings.map((mapping) => [mapping.shape, mapping.value]),
    [["square", "\\(\\frac{9b}{a}\\)"], ["circle", "\\(\\frac{4a}{b}\\)"]],
  );
  assert.match(application.fixedCondition, /=36/);
  assert.match(application.conclusion, /27.*2/);

  const equality = lesson.steps[3].visual;
  assert.equal(equality.kind, "basic-inequality-equality-check");
  assert.match(equality.solved, /a=\\frac\{2\}\{3\}/);
  assert.match(equality.verification, /27.*2/);
});

test("fourteenth basic inequality exercise follows the four-step homogenization lesson", () => {
  const wholeTarget = readLesson("inequality-basic-q14");
  assert.equal(wholeTarget.problem.keyPoints.lead, "");
  assert.deepEqual(
    wholeTarget.steps.map((step) => [step.id, step.title]),
    [
      ["s1", "观察结构"],
      ["s2", "配齐次式"],
      ["s3", "应用基本不等式"],
      ["s4", "验证取等"],
    ],
  );

  const wholeVisual = wholeTarget.steps[0].visual;
  assert.equal(wholeTarget.steps[0].section, "配齐次式");
  assert.equal(wholeVisual.kind, "basic-inequality-structure-scan");
  assert.equal(wholeVisual.condition.tag, "正一次");
  assert.equal(wholeVisual.target.tag, "负一次");
  assert.equal(wholeVisual.reading, "次数配成 0");
  assert.equal(wholeVisual.route, "配齐次式");
  const homogenizationHint = wholeVisual.organization.homogenizationHint;
  assert.deepEqual(
    [homogenizationHint.originalDegree, homogenizationHint.conditionDegree, homogenizationHint.resultDegree],
    ["−1", "+1", "0"],
  );
  assert.equal(homogenizationHint.balance, "\\((-1)+(+1)=0\\)");
  assert.match(homogenizationHint.result, /3\+\\frac\{a\}\{b\}\+\\frac\{2b\}\{a\}/);

  const construction = wholeTarget.steps[1].visual;
  assert.equal(construction.kind, "basic-inequality-structure-scan");
  assert.equal(construction.showFocus, false);
  assert.equal(construction.organization.label, "配齐次式：乘入条件并展开");
  assert.match(construction.organization.steps.join(""), /a\+b.*3\+\\frac\{a\}\{b\}\+\\frac\{2b\}\{a\}/);
  assert.deepEqual(
    [construction.pattern.first, construction.pattern.second].map((item) => [item.shape, item.value]),
    [["square", "\\(\\frac{a}{b}\\)"], ["circle", "\\(\\frac{2b}{a}\\)"]],
  );
  assert.equal(construction.pattern.condition.tag, "定积 2");

  const application = wholeTarget.steps[2].visual;
  assert.equal(application.kind, "basic-inequality-mapping");
  assert.equal(application.methodTag, "配齐次式｜定积求和");
  assert.deepEqual(
    application.mappings.map((item) => [item.shape, item.value]),
    [["square", "\\(\\frac{a}{b}\\)"], ["circle", "\\(\\frac{2b}{a}\\)"]],
  );
  assert.match(application.fixedCondition, /=2/);
  assert.match(application.conclusion, /3\+2\\sqrt2/);

  const equality = wholeTarget.steps[3].visual;
  assert.equal(equality.kind, "basic-inequality-equality-check");
  assert.match(equality.solved, /2-\\sqrt2/);
  assert.match(equality.verification, /3\+2\\sqrt2/);
});

test("later homogeneous exercises distinguish whole-target multiplication from low-degree completion", () => {
  const completedTerm = readLesson("inequality-basic-q15");
  assert.deepEqual(
    completedTerm.steps.map((step) => [step.id, step.title]),
    [
      ["s1", "观察结构"],
      ["s2", "局部配齐次式"],
      ["s3", "应用基本不等式"],
      ["s4", "验证取等"],
    ],
  );
  const completedVisual = completedTerm.steps[0].visual;
  assert.equal(completedTerm.steps[0].section, "配齐次式");
  assert.equal(completedVisual.kind, "basic-inequality-structure-scan");
  assert.equal(completedVisual.reading, "局部次数不齐");
  assert.equal(completedVisual.route, "局部配齐次式");
  assert.equal(completedVisual.organization.label, "局部配齐次：先圈待配项，再局部配齐");
  assert.equal(completedVisual.organization.steps, undefined);
  assert.equal(completedVisual.organization.motive, undefined);
  assert.equal(completedVisual.organization.note, undefined);
  const completedSpot = completedVisual.organization.termSpot;
  assert.deepEqual(
    completedSpot.factors[0].terms.map((term) => [term.value, term.role, term.mark]),
    [
      ["\\(\\frac{a^2}{ab}\\)", "keep", "0 次不动"],
      ["\\(\\frac{2b}{ab}\\)", "spot", "−1 次待配齐"],
    ],
  );
  const completedCore = completedVisual.organization.localHomogenizationHint;
  assert.equal(completedCore.method, "局部乘入定值");
  assert.deepEqual(
    [completedCore.originalDegree, completedCore.conditionDegree, completedCore.resultDegree],
    ["−1", "+1", "0"],
  );
  assert.equal(completedCore.original, "\\(\\frac{2}{a}\\)");
  assert.equal(completedCore.condition, "\\(\\frac{a+b}{2}=1\\)");
  assert.equal(completedCore.result, "\\(\\frac{a+b}{a}\\)");
  assert.equal(completedCore.balance, "\\((-1)+(+1)=0\\)");
  assert.equal(completedCore.scopes[0].expression, "\\(\\frac{2b}{ab}=\\frac{2}{a}\\)");
  assert.equal(completedCore.scopeNote, "只配这一项");

  const completion = completedTerm.steps[1].visual;
  assert.equal(completion.kind, "basic-inequality-structure-scan");
  assert.equal(completion.organization.label, "局部配齐：只配负一次项");
  assert.match(completion.organization.steps[0].expression, /\\frac\{2\}\{a\}=\\frac\{2\}\{a\}\\cdot\\frac\{a\+b\}\{2\}/);
  assert.match(completion.organization.steps[2].expression, /=1\+\\frac\{a\}\{b\}\+\\frac\{b\}\{a\}/);
  assert.equal(completion.pattern.condition.tag, "定积 1");

  const completedMapping = completedTerm.steps[2].visual;
  assert.equal(completedMapping.kind, "basic-inequality-mapping");
  assert.equal(completedMapping.methodTag, "局部配齐｜定积求和");
  assert.equal(completedMapping.mappedProduct, "\\(1\\)");
  assert.match(completedMapping.conclusion, /\\ge3/);

  const completedEquality = completedTerm.steps[3].visual;
  assert.equal(completedEquality.kind, "basic-inequality-equality-check");
  assert.match(completedEquality.solved, /a=b=1/);
  assert.doesNotMatch(JSON.stringify(completedTerm), /fixed-product-construction-flow|t=\\frac\{a\}\{b\}/);

  const bracketCompletion = readLesson("inequality-basic-q16");
  assert.deepEqual(
    bracketCompletion.steps.map((step) => [step.id, step.title]),
    [
      ["s1", "观察结构"],
      ["s2", "局部配齐次式"],
      ["s3", "应用基本不等式"],
      ["s4", "验证取等"],
    ],
  );
  const bracketVisual = bracketCompletion.steps[0].visual;
  assert.equal(bracketCompletion.steps[0].section, "配齐次式");
  assert.equal(bracketVisual.kind, "basic-inequality-structure-scan");
  assert.equal(bracketVisual.reading, "局部次数不齐");
  assert.equal(bracketVisual.route, "局部配齐次式");
  assert.match(bracketVisual.target.tag, /括号内次数混合/);
  assert.equal(bracketVisual.organization.label, "局部配齐次：先圈待配项，再局部配齐");
  assert.equal(bracketVisual.organization.steps, undefined);
  assert.equal(bracketVisual.organization.motive, undefined);
  assert.equal(bracketVisual.organization.homogenizationHint, undefined);
  assert.equal(bracketVisual.organization.note, undefined);
  const bracketSpot = bracketVisual.organization.termSpot;
  assert.equal(bracketSpot.label, undefined);
  assert.deepEqual(
    bracketSpot.factors.map((factor) => factor.terms.map((term) => [term.value, term.role, term.mark])),
    [
      [["\\(\\frac{1}{x}\\)", "spot", "负一次待配齐"], ["\\(1\\)", "keep", "零次不动"]],
      [["\\(\\frac{1}{y}\\)", "spot", "负一次待配齐"], ["\\(1\\)", "keep", "零次不动"]],
    ],
  );
  const bracketCore = bracketVisual.organization.localHomogenizationHint;
  assert.equal(bracketCore.method, "局部乘入定值");
  assert.deepEqual(
    [bracketCore.originalDegree, bracketCore.conditionDegree, bracketCore.resultDegree],
    ["−1", "+1", "0"],
  );
  assert.equal(bracketCore.original, "\\(\\frac{1}{x}\\)");
  assert.equal(bracketCore.condition, "\\(x+y=1\\)");
  assert.equal(bracketCore.result, "\\(\\frac{x+y}{x}\\)");
  assert.equal(bracketCore.balance, "\\((-1)+(+1)=0\\)");
  assert.deepEqual(
    bracketCore.scopes.map((item) => item.label),
    ["左括号", "右括号"],
  );
  assert.equal(bracketCore.scopeNote, "各配一次");
  const runtime = fs.readFileSync(path.join(repoRoot, "site/assets/js/lesson-page-runtime.js"), "utf8");
  assert.match(runtime, /basic-structure-term-spot/);
  assert.match(runtime, /basic-structure-local-homo-hint/);
  assert.match(runtime, /localHomogenizationHint/);
  assert.match(runtime, /basic-structure-homogenization-hint/);

  const bracketConstruction = bracketCompletion.steps[1].visual;
  assert.equal(bracketConstruction.kind, "basic-inequality-structure-scan");
  assert.equal(bracketConstruction.showFocus, false);
  assert.equal(bracketConstruction.organization.label, "局部配齐：只配负一次项，零次不动");
  assert.match(bracketConstruction.organization.steps.join(""), /5\+\\frac\{2x\}\{y\}\+\\frac\{2y\}\{x\}/);
  assert.match(bracketConstruction.organization.steps.join(""), /\\frac\{1\}\{x\}\\cdot\(x\+y\)/);
  assert.equal(bracketConstruction.pattern.condition.tag, "定积 4");

  const bracketMapping = bracketCompletion.steps[2].visual;
  assert.equal(bracketMapping.kind, "basic-inequality-mapping");
  assert.equal(bracketMapping.methodTag, "局部配齐｜定积求和");
  assert.equal(bracketMapping.mappedProduct, "\\(4\\)");
  assert.match(bracketMapping.conclusion, /\\ge9/);

  const bracketEquality = bracketCompletion.steps[3].visual;
  assert.equal(bracketEquality.kind, "basic-inequality-equality-check");
  assert.match(bracketEquality.solved, /x=y=\\frac\{1\}\{2\}/);
  assert.match(bracketEquality.verification, /=9/);
  assert.doesNotMatch(JSON.stringify(bracketCompletion), /fixed-product-construction-flow|另一条可行路线|取倒数传界/);
});

test("seventeenth basic inequality exercise closes the symmetric range in both directions", () => {
  const lesson = readLesson("inequality-basic-q17");
  assert.equal(lesson.problem.source, "2022 新高考Ⅱ卷");
  assert.deepEqual(
    lesson.steps.map((step) => [step.id, step.title]),
    [
      ["s1", "观察结构"],
      ["s2", "和积换元"],
      ["s3", "应用基本不等式消元"],
      ["s4", "验证取等"],
    ],
  );

  const observation = lesson.steps[0].visual;
  assert.equal(lesson.steps[0].section, "找对称结构");
  assert.equal(observation.kind, "basic-inequality-structure-scan");
  assert.equal(observation.reading, "对称结构");
  assert.equal(observation.route, "和积换元");
  assert.equal(observation.organization.label, "校验对称结构：分别交换 x、y");
  assert.deepEqual(
    observation.organization.symmetryHint.checks.map((item) => [item.label, item.verdict]),
    [["目标整式", "交换后不变"], ["条件整式", "交换后不变"]],
  );
  assert.match(observation.organization.symmetryHint.conclusion, /可以用和与积/);

  const substitution = lesson.steps[1].visual;
  assert.equal(substitution.kind, "basic-inequality-structure-scan");
  assert.equal(substitution.showFocus, false);
  assert.deepEqual(
    substitution.organization.steps.map((item) => item.label),
    ["定义", "恒等变形", "代入条件", "解出 p"],
  );
  assert.match(substitution.organization.steps[2].expression, /s\^2-3p=1/);
  assert.match(substitution.organization.steps[3].expression, /p=\\frac\{s\^2-1\}\{3\}/);

  const application = lesson.steps[2].visual;
  assert.equal(application.kind, "basic-inequality-mapping");
  assert.equal(application.formulaStyle, "square-sum");
  assert.equal(application.template, "\\(u^2+v^2\\ge2uv\\)");
  assert.deepEqual(
    application.mappings.map((item) => [item.value, item.condition]),
    [
      ["\\(x\\)", "\\(x\\in\\mathbb R\\)"],
      ["\\(y\\)", "\\(y\\in\\mathbb R\\)"],
    ],
  );
  assert.equal(application.mapped, "\\(x^2+y^2\\ge2xy\\)");
  assert.equal(application.replaced, "\\((x+y)^2\\ge4xy\\)");
  assert.equal(application.substituted, "\\(s^2\\ge4p\\)");
  assert.equal(application.conclusion, "\\(s^2\\ge\\frac{4(s^2-1)}{3}\\)");

  const equality = lesson.steps[3].visual;
  assert.equal(equality.kind, "basic-inequality-equality-check");
  assert.match(equality.condition, /s=x\+y=2.*s=x\+y=-2/);
  assert.match(equality.solved, /x=y=1.*x=y=-1/);
  assert.deepEqual(lesson.steps[3].derive[0], ["取值范围", "[-2,2]"]);
  assert.doesNotMatch(JSON.stringify(lesson), /symmetric-reduction-flow|t\^2|\\\\Delta|判别式|d=x-y/);

  const runtime = fs.readFileSync(
    path.join(repoRoot, "site/assets/js/lesson-page-runtime.js"),
    "utf8",
  );
  assert.match(runtime, /basic-structure-symmetry-hint/);
  assert.match(runtime, /organizationSymmetryHintMarkup/);
  assert.match(runtime, /usesSquareSumFormula/);
});

test("eighteenth basic inequality variant normalizes coefficients before checking symmetry", () => {
  const lesson = readLesson("inequality-basic-q18");
  assert.deepEqual(
    lesson.steps.map((step) => [step.id, step.title]),
    [
      ["s1", "观察结构"],
      ["s2", "和积换元"],
      ["s3", "应用基本不等式消元"],
      ["s4", "验证取等"],
    ],
  );

  const observation = lesson.steps[0].visual;
  assert.equal(observation.kind, "basic-inequality-structure-scan");
  assert.equal(observation.organization.label, "先缩放变量，再校验对称结构");
  assert.equal(observation.organization.stepGroupLabel, "缩放变量：同步改写目标与条件");
  assert.deepEqual(
    observation.organization.steps.map((item) => item.label),
    ["定义新变量", "改写目标", "改写条件"],
  );
  assert.match(observation.organization.steps[0].expression, /u=\\frac\{x\}\{2\}\\iff x=2u/);
  assert.deepEqual(
    observation.organization.symmetryHint.checks.map((item) => [item.original, item.swapped]),
    [["\\(u+y\\)", "\\(y+u\\)"], ["\\(u^2+y^2-uy\\)", "\\(y^2+u^2-yu\\)"]],
  );

  const substitution = lesson.steps[1].visual;
  assert.equal(substitution.kind, "basic-inequality-structure-scan");
  assert.deepEqual(
    substitution.organization.steps.map((item) => item.label),
    ["定义", "恒等变形", "代入条件", "解出 p"],
  );
  assert.equal(substitution.organization.steps[3].expression, "\\(p=\\frac{4s^2-1}{12}\\)");

  const application = lesson.steps[2].visual;
  assert.equal(application.kind, "basic-inequality-mapping");
  assert.equal(application.formulaStyle, "square-sum");
  assert.deepEqual(application.mappings.map((item) => item.value), ["\\(u\\)", "\\(y\\)"]);
  assert.equal(application.mapped, "\\(u^2+y^2\\ge2uy\\)");
  assert.equal(application.substituted, "\\(s^2\\ge4p\\)");
  assert.equal(application.conclusion, "\\(s^2\\ge\\frac{4s^2-1}{3}\\)");

  const equality = lesson.steps[3].visual;
  assert.equal(equality.kind, "basic-inequality-equality-check");
  assert.match(equality.solved, /u=y=\\frac\{1\}\{2\}.*u=y=-\\frac\{1\}\{2\}/);
  assert.match(equality.verification, /x,y.*1.*-1/);
  assert.deepEqual(lesson.steps[3].derive[0], ["取值范围", "[-1,1]"]);
});

test("nineteenth basic inequality variant groups repeated expressions before checking symmetry", () => {
  const lesson = readLesson("inequality-basic-q19");
  assert.deepEqual(
    lesson.steps.map((step) => [step.id, step.title]),
    [
      ["s1", "观察结构"],
      ["s2", "和积换元"],
      ["s3", "应用基本不等式消元"],
      ["s4", "验证取等"],
    ],
  );

  const observation = lesson.steps[0].visual;
  assert.equal(observation.kind, "basic-inequality-structure-scan");
  assert.equal(observation.organization.stepGroupLabel, "缩放变量：同步改写目标与条件");
  assert.deepEqual(
    observation.organization.steps.map((item) => item.expression),
    ["\\(u=a，v=2b\\)", "\\(a+2b=u+v\\)", "\\(uv=u+v+3\\)"],
  );
  assert.deepEqual(
    observation.organization.symmetryHint.checks.map((item) => [item.original, item.swapped]),
    [["\\(u+v\\)", "\\(v+u\\)"], ["\\(uv=u+v+3\\)", "\\(vu=v+u+3\\)"]],
  );

  const substitution = lesson.steps[1].visual;
  assert.equal(substitution.kind, "basic-inequality-structure-scan");
  assert.equal(substitution.organization.steps.at(-1).expression, "\\(p=s+3\\)");

  const application = lesson.steps[2].visual;
  assert.equal(application.kind, "basic-inequality-mapping");
  assert.equal(application.formulaStyle, "square-sum");
  assert.deepEqual(application.mappings.map((item) => item.value), ["\\(u\\)", "\\(v\\)"]);
  assert.equal(application.substituted, "\\(s^2\\ge4p\\)");
  assert.equal(application.conclusion, "\\(s^2\\ge4(s+3)\\)");

  const equality = lesson.steps[3].visual;
  assert.equal(equality.kind, "basic-inequality-equality-check");
  assert.equal(equality.solved, "\\(u=v=3\\)");
  assert.match(equality.verification, /a=3，b=\\frac\{3\}\{2\}/);
  assert.deepEqual(lesson.steps[3].derive[0], ["最小值", "6"]);
});

test("twentieth basic inequality variant squares the target before direct AM-GM", () => {
  const lesson = readLesson("inequality-basic-q20");
  assert.equal(lesson.problem.keyPoints.lead, "");
  assert.deepEqual(
    lesson.steps.map((step) => [step.id, step.title]),
    [
      ["s1", "观察结构"],
      ["s2", "应用基本不等式"],
      ["s3", "验证取等"],
    ],
  );

  const structure = lesson.steps[0].visual;
  assert.equal(lesson.steps[0].section, "基本不等式");
  assert.equal(structure.kind, "basic-inequality-structure-scan");
  assert.equal(structure.organization.label, "整理目标整式：配次显条件");
  assert.deepEqual(structure.organization.squareHint, {
    source: "目标与条件次数不齐",
    action: "平方配次",
    result: "条件量显形",
    note: "再代入条件消元",
    ariaLabel: "目标与条件次数不齐时，先平方配次，再代入条件消元",
  });
  assert.deepEqual(
    structure.organization.steps.map((item) => item.label),
    ["平方配次", "恒等变形", "代入消元"],
  );
  assert.match(structure.organization.steps[1].expression, /\(x\+y\)\^2=\(x-y\)\^2\+4xy/);
  assert.match(structure.organization.steps[2].expression, /xy\+\\frac\{4\}\{xy\}/);
  assert.equal(structure.organization.steps[2].marks.bracket, "只剩 xy");
  assert.equal(structure.pattern.condition.tag, "定积 4");
  assert.deepEqual(lesson.steps[0].derive[0], ["结构判断", "配次显条件｜定积求和"]);

  const mapping = lesson.steps[1].visual;
  assert.equal(mapping.kind, "basic-inequality-mapping");
  assert.equal(mapping.methodTag, "直接应用｜定积求和");
  assert.deepEqual(mapping.mappings.map((item) => item.value), ["\\(xy\\)", "\\(\\frac{4}{xy}\\)"]);
  assert.equal(mapping.mappedProduct, "\\(4\\)");
  assert.equal(mapping.fixedCondition, "\\(xy\\cdot\\frac{4}{xy}=4\\)");
  assert.equal(mapping.conclusion, "\\(\\frac{1}{x}+\\frac{1}{y}\\ge2\\)");

  const equality = lesson.steps[2].visual;
  assert.equal(equality.kind, "basic-inequality-equality-check");
  assert.match(equality.solved, /2\+\\sqrt2.*2-\\sqrt2/);
  assert.match(equality.verification, /\\frac\{x\+y\}\{xy\}=2/);
  assert.deepEqual(lesson.steps[2].derive[0], ["最小值", "2"]);
  assert.doesNotMatch(JSON.stringify(lesson), /t=xy|\\\(t\\\)/);
  assert.doesNotMatch(JSON.stringify(lesson), /E(?:=|\^|&gt;|\\ge)/);

  const runtime = fs.readFileSync(path.join(repoRoot, "site/assets/js/lesson-page-runtime.js"), "utf8");
  assert.match(runtime, /basic-structure-square-hint/);
  assert.match(runtime, /basic-structure-square-rule/);
});

test("twenty-first basic inequality exercise eliminates separate variables before product substitution", () => {
  const lesson = readLesson("inequality-basic-q21");
  assert.deepEqual(
    lesson.steps.map((step) => [step.id, step.title]),
    [
      ["s1", "观察结构"],
      ["s2", "应用基本不等式消元"],
      ["s3", "积换元求一元二次式范围"],
      ["s4", "验证取等"],
    ],
  );

  const observation = lesson.steps[0].visual;
  assert.equal(lesson.steps[0].section, "找对称结构");
  assert.equal(observation.kind, "basic-inequality-structure-scan");
  assert.equal(observation.reading, "同归于 ab");
  assert.equal(observation.route, "应用基本不等式消元");
  assert.deepEqual(
    observation.organization.steps.map((item) => item.label),
    ["配对", "配对结果", "剩余项"],
  );
  assert.match(observation.organization.note, /都只含 ab.*积换元/);

  const elimination = lesson.steps[1].visual;
  assert.equal(elimination.kind, "basic-inequality-mapping");
  assert.equal(elimination.methodTag, "找对称结构｜基本不等式消元");
  assert.deepEqual(
    elimination.mappings.map((item) => item.value),
    ["\\(a^4\\)", "\\(b^4\\)"],
  );
  assert.equal(elimination.mappedProduct, "\\((ab)^4\\)");
  assert.equal(elimination.replaced, "\\(a^4+b^4\\ge2(ab)^2\\)");
  assert.match(elimination.conclusion, /2\(ab\)\^2-8ab/);

  const substitution = lesson.steps[2].visual;
  assert.equal(substitution.kind, "basic-inequality-structure-scan");
  assert.equal(substitution.showFocus, false);
  assert.deepEqual(
    substitution.organization.steps.map((item) => item.label),
    ["积换元", "化为一元式", "配方", "取值范围"],
  );
  assert.match(substitution.organization.steps[0].expression, /p=ab>0/);
  assert.match(substitution.organization.steps[2].expression, /2\(p-2\)\^2-8/);
  assert.match(substitution.organization.steps[3].expression, /-8.*\\infty/);

  const equality = lesson.steps[3].visual;
  assert.equal(equality.kind, "basic-inequality-equality-check");
  assert.equal(equality.condition, "\\(p=ab=2\\)");
  assert.equal(equality.solved, "\\(a=b=\\sqrt2\\)");
  assert.match(equality.verification, /=-8/);
  assert.deepEqual(lesson.steps[3].derive[0], ["最小值", "-8"]);
  assert.doesNotMatch(JSON.stringify(lesson), /symmetryCheck|交换后不变|symmetric-objective-reduction/);
});

test("twenty-second through twenty-sixth basic inequality variants use substitution as the entry method", () => {
  const first = readLesson("inequality-basic-q22");
  const second = readLesson("inequality-basic-q23");
  const third = readLesson("inequality-basic-q24");
  const fourth = readLesson("inequality-basic-q25");
  const fifth = readLesson("inequality-basic-q26");

  assert.deepEqual([first.steps[0].section, second.steps[0].section, third.steps[0].section, fourth.steps[0].section, fifth.steps[0].section], ["换元法", "换元法", "换元法", "换元法", "换元法"]);

  assert.deepEqual(first.steps.map((item) => item.title), [
    "观察原式结构",
    "整体换元",
    "观察换元后的结构",
    "配齐次式",
    "应用基本不等式",
    "验证取等并还原",
  ]);
  const firstObservation = first.steps[0].visual;
  assert.equal(firstObservation.kind, "basic-inequality-structure-scan");
  assert.equal(firstObservation.reading, "完整分母");
  assert.equal(firstObservation.route, "整体换元");
  assert.deepEqual(
    firstObservation.organization.substitutionHint.mappings.map((item) => [item.numerator, item.denominator, item.variable, item.assignment]),
    [
      ["1", "\\(x+1\\)", "\\(u\\)", "\\(x+1>0\\)"],
      ["1", "\\(y+2\\)", "\\(v\\)", "\\(y+2>0\\)"],
    ],
  );
  assert.doesNotMatch(JSON.stringify(first.steps[0]), /反复出现/);

  const firstSubstitution = first.steps[1].visual;
  assert.equal(firstSubstitution.kind, "basic-inequality-structure-scan");
  assert.equal(firstSubstitution.showFocus, false);
  assert.deepEqual(firstSubstitution.organization.steps.map((item) => item.label), ["定义", "逆关系", "改写条件", "改写目标"]);
  assert.match(firstSubstitution.organization.steps[2].expression, /u\+v=5/);
  assert.match(firstSubstitution.organization.steps[3].expression, /\\frac\{1\}\{u\}.*\\frac\{1\}\{v\}/);

  const firstHomogeneousObservation = first.steps[2].visual;
  assert.equal(firstHomogeneousObservation.kind, "basic-inequality-structure-scan");
  const firstHomogenizationHint = firstHomogeneousObservation.organization.homogenizationHint;
  assert.deepEqual(
    [firstHomogenizationHint.originalDegree, firstHomogenizationHint.conditionDegree, firstHomogenizationHint.resultDegree],
    ["−1", "+1", "0"],
  );
  assert.equal(firstHomogenizationHint.balance, "\\((-1)+(+1)=0\\)");
  assert.match(firstHomogenizationHint.result, /2\+\\frac\{u\}\{v\}\+\\frac\{v\}\{u\}/);

  const firstHomogeneous = first.steps[3].visual;
  assert.equal(firstHomogeneous.kind, "basic-inequality-structure-scan");
  assert.equal(firstHomogeneous.showFocus, false);
  assert.deepEqual(firstHomogeneous.organization.steps, [
    "\\(5(\\frac{1}{u}+\\frac{1}{v})=(u+v)(\\frac{1}{u}+\\frac{1}{v})\\)",
    "\\(5(\\frac{1}{u}+\\frac{1}{v})=2+\\frac{u}{v}+\\frac{v}{u}\\)",
  ]);
  assert.equal(firstHomogeneous.pattern.condition.tag, "定积 1");
  assert.equal(firstHomogeneous.pattern.target.tag, "求最小值");

  const firstInequality = first.steps[4].visual;
  assert.equal(firstInequality.kind, "basic-inequality-mapping");
  assert.equal(firstInequality.methodTag, "配齐次式｜定积求和");
  assert.equal(firstInequality.fixedCondition, "\\(\\frac{u}{v}\\cdot\\frac{v}{u}=1\\)");
  assert.equal(firstInequality.conclusion, "\\(\\frac{1}{u}+\\frac{1}{v}\\ge\\frac{4}{5}\\)");

  const firstEquality = first.steps[5].visual;
  assert.equal(firstEquality.kind, "basic-inequality-equality-check");
  assert.match(firstEquality.solved, /u=v=\\frac\{5\}\{2\}.*x=\\frac\{3\}\{2\}.*y=\\frac\{1\}\{2\}/);
  assert.deepEqual(first.steps[5].derive[0], ["最小值", "4/5"]);

  assert.deepEqual(second.steps.map((item) => item.title), first.steps.map((item) => item.title));
  const secondObservation = second.steps[0].visual;
  assert.equal(secondObservation.kind, "basic-inequality-structure-scan");
  assert.deepEqual(
    secondObservation.organization.substitutionHint.mappings.map((item) => [item.denominator, item.variable, item.assignment]),
    [
      ["\\(x+1\\)", "\\(u\\)", "\\(x+1>0\\)"],
      ["\\(2y+1\\)", "\\(v\\)", "\\(2y+1>0\\)"],
    ],
  );
  assert.deepEqual(second.steps[1].visual.organization.steps.map((item) => item.label), ["定义", "逆关系", "改写条件", "改写目标"]);
  assert.match(second.steps[1].visual.organization.steps[2].expression, /2u\+v=7/);
  const secondHomogenizationHint = second.steps[2].visual.organization.homogenizationHint;
  assert.deepEqual(
    [secondHomogenizationHint.originalDegree, secondHomogenizationHint.conditionDegree, secondHomogenizationHint.resultDegree],
    ["−1", "+1", "0"],
  );
  assert.match(secondHomogenizationHint.result, /3\+\\frac\{2u\}\{v\}\+\\frac\{v\}\{u\}/);
  assert.equal(second.steps[3].visual.pattern.condition.tag, "定积 2");
  assert.equal(second.steps[4].visual.fixedCondition, "\\(\\frac{2u}{v}\\cdot\\frac{v}{u}=2\\)");
  assert.equal(second.steps[4].visual.conclusion, "\\(\\frac{1}{u}+\\frac{1}{v}\\ge\\frac{3+2\\sqrt2}{7}\\)");
  assert.match(second.steps[5].visual.solved, /v=\\sqrt2u.*x=6-\\frac\{7\\sqrt2\}\{2\}.*y=\\frac\{7\\sqrt2-8\}\{2\}/);
  assert.deepEqual(second.steps[5].derive[0], ["最小值", "(3+2√2)/7"]);

  assert.deepEqual(third.steps.map((item) => item.title), first.steps.map((item) => item.title));
  const thirdObservation = third.steps[0].visual;
  assert.equal(thirdObservation.kind, "basic-inequality-structure-scan");
  assert.deepEqual(
    thirdObservation.organization.substitutionHint.mappings.map((item) => [item.numerator, item.denominator, item.variable, item.assignment]),
    [
      ["\\(a^2\\)", "\\(a+1\\)", "\\(u\\)", "\\(a+1>1\\)"],
      ["\\(b^2\\)", "\\(b+1\\)", "\\(v\\)", "\\(b+1>1\\)"],
    ],
  );
  assert.deepEqual(third.steps[1].visual.organization.steps.map((item) => item.label), ["定义与逆关系", "改写条件", "整理两项", "改写目标"]);
  assert.match(third.steps[1].visual.organization.steps[2].expression, /\\frac\{\(u-1\)\^2\}\{u\}=u-2\+\\frac\{1\}\{u\}/);
  assert.equal(third.steps[1].visual.organization.steps[3].expression, "\\(-1+\\frac{1}{u}+\\frac{1}{v}\\)");
  assert.equal(third.steps[2].visual.target.tag, "负一次｜常数 −1 不动");
  const thirdHomogenizationHint = third.steps[2].visual.organization.homogenizationHint;
  assert.equal(thirdHomogenizationHint.original, "\\(\\frac{1}{u}+\\frac{1}{v}\\)");
  assert.equal(thirdHomogenizationHint.balance, "\\((-1)+(+1)=0\\)");
  assert.equal(third.steps[3].visual.pattern.condition.tag, "定积 1");
  assert.match(third.steps[3].visual.organization.note, /常数 −1 不动/);
  assert.equal(third.steps[4].visual.fixedCondition, "\\(\\frac{u}{v}\\cdot\\frac{v}{u}=1\\)");
  assert.equal(third.steps[4].visual.conclusion, "\\(\\frac{a^2}{a+1}+\\frac{b^2}{b+1}\\ge\\frac{1}{3}\\)");
  assert.equal(third.steps[5].visual.solved, "\\(u=v=\\frac{3}{2}\\Rightarrow a=b=\\frac{1}{2}\\)");
  assert.deepEqual(third.steps[5].derive[0], ["最小值", "1/3"]);

  assert.deepEqual(fourth.steps.map((item) => item.title), [
    "观察原式结构",
    "整体换元",
    "观察换元后的结构",
    "应用基本不等式",
    "验证取等并还原",
  ]);
  const fourthObservation = fourth.steps[0].visual;
  assert.equal(fourthObservation.kind, "basic-inequality-structure-scan");
  assert.deepEqual(
    fourthObservation.organization.substitutionHint.mappings.map((item) => [item.numerator, item.denominator, item.variable, item.assignment]),
    [
      ["\\(4a\\)", "\\(a-1\\)", "\\(x\\)", "\\(a-1>0\\)"],
      ["\\(9b\\)", "\\(b-1\\)", "\\(y\\)", "\\(b-1>0\\)"],
    ],
  );
  assert.deepEqual(fourth.steps[1].visual.organization.steps.map((item) => item.label), ["定义与逆关系", "改写条件", "整理两项", "改写目标"]);
  assert.match(fourth.steps[1].visual.organization.steps[1].expression, /xy=1/);
  assert.equal(fourth.steps[2].visual.kind, "basic-inequality-structure-scan");
  assert.equal(fourth.steps[2].visual.reading, "定积求和");
  assert.equal(fourth.steps[2].visual.pattern.condition.tag, "定积 36");
  assert.equal(fourth.steps[3].visual.kind, "basic-inequality-mapping");
  assert.equal(fourth.steps[3].visual.methodTag, "直接应用｜定积求和");
  assert.equal(fourth.steps[3].visual.fixedCondition, "\\(\\frac{4}{x}\\cdot\\frac{9}{y}=36\\)");
  assert.equal(fourth.steps[3].visual.conclusion, "\\(\\frac{4a}{a-1}+\\frac{9b}{b-1}\\ge25\\)");
  assert.match(fourth.steps[4].visual.solved, /x=\\frac\{2\}\{3\}.*y=\\frac\{3\}\{2\}.*a=\\frac\{5\}\{3\}.*b=\\frac\{5\}\{2\}/);
  assert.deepEqual(fourth.steps[4].derive[0], ["最小值", "25"]);
  assert.doesNotMatch(JSON.stringify(fourth), /配齐次式|外层|内层|闭环|T=/);

  assert.deepEqual(fifth.steps.map((item) => item.title), fourth.steps.map((item) => item.title));
  const fifthObservation = fifth.steps[0].visual;
  assert.equal(fifthObservation.kind, "basic-inequality-structure-scan");
  assert.deepEqual(
    fifthObservation.organization.substitutionHint.mappings.map((item) => [item.kind, item.source, item.variable, item.assignment]),
    [["radical", "\\(\\sqrt{2+y^2}\\)", "\\(t\\)", "\\(\\sqrt{2+y^2}>\\sqrt2\\)"]],
  );
  assert.deepEqual(fifth.steps[1].visual.organization.steps.map((item) => item.label), ["定义", "逆关系", "改写条件", "改写目标"]);
  assert.match(fifth.steps[1].visual.organization.steps[2].expression, /\(4x\)\^2\+t\^2=18/);
  assert.equal(fifth.steps[2].visual.kind, "basic-inequality-structure-scan");
  assert.equal(fifth.steps[2].visual.reading, "定和求积");
  assert.equal(fifth.steps[2].visual.pattern.condition.tag, "定和 18");
  assert.equal(fifth.steps[2].visual.pattern.target.tag, "求最大值");
  assert.equal(fifth.steps[3].visual.kind, "basic-inequality-mapping");
  assert.equal(fifth.steps[3].visual.methodTag, "直接应用｜定和求积");
  assert.equal(fifth.steps[3].visual.fixedCondition, "\\((4x)^2+t^2=18\\)");
  assert.equal(fifth.steps[3].visual.conclusion, "\\(x\\sqrt{2+y^2}\\le\\frac{9}{4}\\)");
  assert.match(fifth.steps[4].visual.solved, /4x=t.*x=\\frac\{3\}\{4\}.*t=3.*y=\\sqrt7/);
  assert.deepEqual(fifth.steps[4].derive[0], ["最大值", "9/4"]);
  assert.doesNotMatch(JSON.stringify(fifth), /配齐次式|外层|内层|闭环|T=/);

  assert.doesNotMatch(JSON.stringify([second, third]), /反复出现|T=|5T|7T|外层|内层|闭环/);

  const runtime = fs.readFileSync(path.join(repoRoot, "site/assets/js/lesson-page-runtime.js"), "utf8");
  const styles = fs.readFileSync(path.join(repoRoot, "site/assets/css/interactive-geometry-page.css"), "utf8");
  assert.match(runtime, /lesson-step-substitution-lifecycle/);
  assert.match(runtime, /organizationSubstitutionHintMarkup/);
  assert.match(runtime, /basic-structure-substitution-hint/);
  assert.match(runtime, /01 换元/);
  assert.match(runtime, /02 配齐次式/);
  assert.match(runtime, /03 .*还原等号/);
  assert.match(runtime, /把复杂分母进行换元/);
  assert.match(runtime, /配齐次式用定和求最值/);
  assert.match(runtime, /求解等号成立条件/);
  assert.match(runtime, /rearrangementBlock.*整理换元后的目标.*substitution-lifecycle-rearrangement-result/s);
  assert.match(runtime, /substitution-basic-inequality-lifecycle.*02 基本不等式.*应用基本不等式求最值/s);
  assert.match(runtime, /substitution-lifecycle-condition-flow/);
  assert.doesNotMatch(runtime.match(/if \(visual\.kind === "substitution-homogeneous-lifecycle"\)[\s\S]*?if \(visual\.kind === "basic-inequality-mapping"\)/)?.[0] || "", /外层方法|内层求解|内层方法|外层闭环|进入新变量世界|交给内层方法/);
  assert.match(styles, /\.substitution-lifecycle-shell/);
  assert.match(styles, /\.basic-structure-substitution-hint/);
  assert.match(styles, /\.substitution-lifecycle-inner/);
  assert.match(styles, /\.substitution-lifecycle-rearrangement/);
  assert.match(styles, /\.substitution-lifecycle-condition-flow/);
  assert.match(styles, /\.substitution-lifecycle-inner\.is-basic-inequality/);
  assert.match(styles, /@media \(max-width: 720px\)[\s\S]*\.substitution-lifecycle-mappings,[\s\S]*\.substitution-lifecycle-restore-chain/);
});

test("twenty-seventh basic inequality variant uses denominator substitution before homogenization", () => {
  const lesson = readLesson("inequality-basic-q27");
  assert.deepEqual(lesson.steps.map((step) => step.title), [
    "观察原式结构",
    "整体换元",
    "观察换元后的结构",
    "配齐次式",
    "应用基本不等式",
    "验证取等并还原",
  ]);
  assert.ok(lesson.steps.every((step) => step.section === "换元法"));
  assert.match(lesson.meta.breadcrumbSearch, /method=substitution-method/);

  const [observeOriginal, substitute, observeSubstituted, homogenize, apply, equality] = lesson.steps;
  assert.deepEqual(observeOriginal.visual.organization.substitutionHint.mappings, [
    { numerator: "1", denominator: "\\(x+1\\)", variable: "\\(u\\)", assignment: "\\(x+1>0\\)" },
    { numerator: "1", denominator: "\\(x+2y\\)", variable: "\\(v\\)", assignment: "\\(x+2y>0\\)" },
  ]);
  assert.equal(observeOriginal.visual.route, "整体换元");

  assert.deepEqual(substitute.visual.organization.steps.map((item) => item.label), ["定义", "逆关系", "改写条件", "改写目标"]);
  assert.equal(substitute.visual.organization.steps.at(-1).expression, "\\(2x+y=\\frac{3u+v-3}{2}\\)");

  assert.equal(observeSubstituted.visual.organization.homogenizationHint.original, "\\(3u+v\\)");
  assert.equal(observeSubstituted.visual.organization.homogenizationHint.condition, "\\(\\frac{1}{u}+\\frac{1}{v}=1\\)");
  assert.equal(observeSubstituted.visual.route, "配齐次式");
  assert.equal(homogenize.visual.pattern.condition.tag, "定积 3");
  assert.equal(homogenize.visual.pattern.target.tag, "求最小值");

  assert.equal(apply.visual.kind, "basic-inequality-mapping");
  assert.equal(apply.visual.mappedProduct, "\\(3\\)");
  assert.equal(apply.visual.conclusion, "\\(2x+y\\ge\\sqrt{3}+\\frac{1}{2}\\)");
  assert.equal(equality.visual.kind, "basic-inequality-equality-check");
  assert.match(equality.visual.solved, /u=1\+.*v=1\+.*x=.*y=/);
  assert.deepEqual(equality.derive[0], ["最小值", "√3+1/2"]);
  assert.doesNotMatch(JSON.stringify(lesson), /条件消元|elimination-basic-inequality-lifecycle|外层|内层|闭环|T=/);
});

test("twenty-ninth basic inequality variant eliminates b before minimizing the reciprocal", () => {
  const lesson = readLesson("inequality-basic-q29");
  assert.deepEqual(lesson.steps.map((step) => step.title), [
    "观察结构与筛选方法",
    "条件消元",
    "取倒数并整理一元目标",
    "观察整理后的结构",
    "应用基本不等式",
    "验证取等并回代",
  ]);
  assert.ok(lesson.steps.every((step) => step.section === "条件消元法"));

  const [screen, eliminate, arrange, observe, apply, equality] = lesson.steps;
  assert.deepEqual(screen.visual.organization.steps.map((item) => item.label), ["直接应用", "找对称", "配齐次式", "整体换元"]);
  assert.equal(screen.visual.route, "条件消元法");
  assert.match(screen.visual.organization.note, /b=1-a.*条件消元法/);

  assert.deepEqual(eliminate.visual.organization.eliminationHint, {
    variable: "\\(b\\)",
    isolated: "\\(1-a\\)",
    independentVariable: "\\(a\\)",
    targetBefore: "\\(\\frac{2a}{a^2+b}+\\frac{b}{a+b^2}\\)",
    targetAfter: "\\(\\frac{a+1}{a^2-a+1}\\)",
    ariaLabel: "由条件用 a 表示 b，代入目标后两个分母统一，二元目标降为只含 a 的一元目标",
  });
  assert.equal(eliminate.visual.caption, undefined);
  assert.deepEqual(arrange.visual.organization.steps.map((item) => item.label), ["目标转换", "整理倒数"]);
  assert.match(arrange.visual.organization.steps[0].expression, /原式最大 ⇔/);
  assert.doesNotMatch(arrange.visual.organization.steps[0].expression, /Longleftrightarrow/);
  assert.equal(arrange.visual.route, "重新观察结构");
  assert.equal(observe.visual.pattern.condition.tag, "定积 3");
  assert.equal(observe.visual.pattern.target.tag, "求最小值");

  assert.equal(apply.visual.kind, "basic-inequality-mapping");
  assert.equal(apply.visual.mappedProduct, "\\(3\\)");
  assert.match(apply.visual.conclusion, /原式.*3\+2\\sqrt\{3\}/);
  assert.equal(equality.visual.kind, "basic-inequality-equality-check");
  assert.equal(equality.visual.solved, "\\(a=\\sqrt{3}-1，b=2-\\sqrt{3}\\)");
  assert.deepEqual(equality.derive[0], ["最大值", "(3+2√3)/3"]);
  assert.doesNotMatch(JSON.stringify(lesson), /\bE\b|elimination-basic-inequality-lifecycle|换元法|外层|内层|闭环|T=/);

  const runtime = fs.readFileSync(path.join(repoRoot, "site/assets/js/lesson-page-runtime.js"), "utf8");
  const styles = fs.readFileSync(path.join(repoRoot, "site/assets/css/interactive-geometry-page.css"), "utf8");
  assert.match(runtime, /organizationEliminationHintMarkup/);
  assert.doesNotMatch(runtime, /elimination-zero-meaning|二元目标降成一元目标/);
  assert.doesNotMatch(styles, /elimination-zero-meaning/);
  assert.match(styles, /\.basic-structure-elimination-hint\.elimination-core-template/);
});

test("thirtieth basic inequality variant reveals each reduction only after the previous estimate", () => {
  const lesson = readLesson("inequality-basic-q30");
  assert.deepEqual(lesson.steps.map((step) => step.title), [
    "观察结构",
    "应用基本不等式消元",
    "平方消元",
    "再次应用基本不等式取极值",
    "验证取等",
  ]);
  assert.deepEqual(lesson.steps.map((step) => step.visual.kind), [
    "basic-inequality-structure-scan",
    "basic-inequality-mapping",
    "basic-inequality-structure-scan",
    "basic-inequality-mapping",
    "basic-inequality-equality-check",
  ]);
  const countHint = lesson.steps[0].visual.organization.relationCountHint;
  assert.deepEqual([countHint.variable.value, countHint.condition.value, countHint.result.value], ["3", "0", "3"]);
  assert.equal(lesson.steps[0].visual.route, "后续逐步建立 3 条取等关系");
  assert.deepEqual(lesson.steps[1].visual.conditionFlow, [
    "目标含 \\(a、b、c\\)",
    "\\(\\frac{1}{ab}+\\frac{1}{a(a-b)}=\\frac{1}{b(a-b)}\\)",
    "先消去 \\(b\\)",
  ]);
  assert.deepEqual(
    lesson.steps[1].visual.mappings.map((item) => item.value),
    ["\\(b\\)", "\\(a-b\\)"],
  );
  assert.equal(lesson.steps[1].visual.replaced, "\\(\\frac{1}{b(a-b)}\\ge\\frac{4}{a^2}\\)");
  assert.equal(lesson.steps[1].visual.equalityTemplate, undefined);
  assert.equal(lesson.steps[1].visual.equalityMapped, undefined);
  assert.equal(lesson.steps[1].visual.equalityContextLabel, undefined);
  assert.equal(lesson.steps[1].visual.equalityResult, undefined);
  assert.equal(lesson.steps[2].visual.organization.label, "整理目标整式：平方消元");
  assert.deepEqual(lesson.steps[2].visual.organization.steps.map((item) => item.label), ["拆项", "配出平方", "整理"]);
  assert.match(lesson.steps[2].visual.organization.note, /平方取零消去.*c.*只含.*a/);
  assert.deepEqual(
    lesson.steps[3].visual.mappings.map((item) => item.value),
    ["\\(a^2\\)", "\\(\\frac{4}{a^2}\\)"],
  );
  assert.equal(lesson.steps[3].visual.substituted, "原式\\(\\ge4+(a-5c)^2\\ge4\\)");
  assert.deepEqual(lesson.steps[4].visual.equalities.map((item) => item.result), [
    "\\(b=\\frac{a}{2}\\)",
    "\\(a=5c\\)",
    "\\(a=\\sqrt{2}\\)",
  ]);
  assert.equal(lesson.steps[4].visual.solved, "\\(a=\\sqrt{2}，b=\\frac{\\sqrt{2}}{2}，c=\\frac{\\sqrt{2}}{5}\\)");
  const equalityRuntime = fs.readFileSync(path.join(repoRoot, "site/assets/js/lesson-page-runtime.js"), "utf8");
  const equalityStyles = fs.readFileSync(path.join(repoRoot, "site/assets/css/interactive-geometry-page.css"), "utf8");
  assert.match(equalityRuntime, /equalityItems\.length === 3.*is-three/);
  assert.match(equalityStyles, /\.basic-equality-system\.is-three > div/);
  assert.deepEqual(lesson.steps.at(-1).derive[0], ["最小值", "4"]);
  assert.doesNotMatch(JSON.stringify(lesson), /E=|E\\\\ge/);
});

test("thirty-first basic inequality variant separates elimination choice, homogenization observation, local homogenization, and two AM-GM rounds", () => {
  const lesson = readLesson("inequality-basic-q31");
  assert.deepEqual(lesson.steps.map((step) => step.title), [
    "观察结构",
    "观察消元结构",
    "观察配齐次结构",
    "局部配齐次式",
    "应用基本不等式消元",
    "再次应用基本不等式取极值",
    "验证取等",
  ]);
  assert.deepEqual(lesson.steps.map((step) => step.visual.kind), [
    "basic-inequality-structure-scan",
    "basic-inequality-structure-scan",
    "basic-inequality-structure-scan",
    "basic-inequality-structure-scan",
    "basic-inequality-mapping",
    "basic-inequality-mapping",
    "basic-inequality-equality-check",
  ]);
  const countHint = lesson.steps[0].visual.organization.relationCountHint;
  assert.deepEqual([countHint.variable.value, countHint.condition.value, countHint.result.value], ["3", "1", "2"]);
  assert.equal(lesson.steps[1].visual.organization.label, "观察消元结构：提取共同整体");
  assert.deepEqual(lesson.steps[1].visual.organization.steps.map((item) => item.label), [
    "提取分母",
    "提取分母",
    "重写目标",
  ]);
  assert.equal(lesson.steps[1].visual.route, "先消去 a、b");
  assert.equal(lesson.steps[2].visual.organization.label, "局部配齐次：先圈待配项，再局部配齐");
  assert.deepEqual(lesson.steps[2].visual.organization.termSpot.factors[0].terms.map((item) => [item.role, item.mark]), [
    ["keep", "0 次不动"],
    ["spot", "−2 次待配齐"],
  ]);
  assert.equal(lesson.steps[2].visual.organization.localHomogenizationHint.balance, "\\((-2)+(+2)=0\\)");
  assert.equal(lesson.steps[2].visual.route, "局部配齐次式");
  assert.equal(lesson.steps[3].visual.organization.label, "局部配齐：只配括号内的负二次项");
  assert.deepEqual(lesson.steps[3].visual.organization.steps.map((item) => item.label), [
    "乘入定值",
    "配成零次",
    "拼回括号",
  ]);
  assert.equal(lesson.steps[3].visual.route, "应用基本不等式消元");
  assert.deepEqual(lesson.steps[4].visual.conditionFlow, [
    "目标含 \\(a、b、c\\)",
    "\\(\\frac{4a}{b}\\cdot\\frac{b}{a}=4\\)",
    "先消去 \\(a、b\\)",
  ]);
  assert.deepEqual(
    lesson.steps[4].visual.mappings.map((item) => item.value),
    ["\\(\\frac{4a}{b}\\)", "\\(\\frac{b}{a}\\)"],
  );
  assert.equal(lesson.steps[4].visual.substituted, "原式\\(\\ge\\frac{6}{1+c^2}+2c^2\\)");
  assert.deepEqual(lesson.steps[5].visual.conditionFlow, [
    "只剩 \\(\\frac{6}{1+c^2}+2c^2\\)",
    "\\(2c^2=2(1+c^2)-2\\)",
    "配出同一整体 \\(1+c^2\\)",
  ]);
  assert.deepEqual(
    lesson.steps[5].visual.mappings.map((item) => item.value),
    ["\\(2(1+c^2)\\)", "\\(\\frac{6}{1+c^2}\\)"],
  );
  assert.deepEqual(lesson.steps[6].visual.equalities.map((item) => item.result), [
    "\\(b=2a\\)",
    "\\(c^2=\\sqrt3-1\\)",
  ]);
  assert.equal(lesson.steps[6].visual.condition, "\\(a+b=1\\)");
  assert.equal(lesson.steps[6].visual.solved, "\\(a=\\frac{1}{3}，b=\\frac{2}{3}，c=\\pm\\sqrt{\\sqrt3-1}\\)");
  assert.deepEqual(lesson.steps.at(-1).derive[0], ["最小值", "4√3−2"]);
  assert.doesNotMatch(JSON.stringify(lesson), /E=|E\\\\ge/);
});

test("basic inequality lessons use fully braced fractions and math-delimited key points", () => {
  const basicLessonIds = lessonIds.filter((id) => id.startsWith("inequality-basic-q"));
  for (const id of basicLessonIds) {
    const lesson = readLesson(id);
    assert.doesNotMatch(JSON.stringify(lesson), /\\\\frac(?!\{)/, `${id} has an ambiguous fraction`);
  }

  for (const id of ["inequality-basic-q03", "inequality-basic-q04", "inequality-basic-q14", "inequality-basic-q15", "inequality-basic-q16", "inequality-basic-q17", "inequality-basic-q18", "inequality-basic-q19", "inequality-basic-q20", "inequality-basic-q22", "inequality-basic-q23", "inequality-basic-q24", "inequality-basic-q25", "inequality-basic-q26", "inequality-basic-q27", "inequality-basic-q29", "inequality-basic-q30", "inequality-basic-q31"]) {
    const lesson = readLesson(id);
    const keyPointText = [lesson.problem.keyPoints.lead, ...lesson.problem.keyPoints.items].join(" ");
    assert.match(keyPointText, /\\\(/, `${id} key points should mark formulas as math`);
    assert.match(renderInlineMathText(keyPointText), /class="math-fraction"/, `${id} key points should render stacked fractions`);
  }
});

test("direct applications organize the target before mapping positive terms", () => {
  const lesson = readLesson("inequality-basic-q05");
  assert.equal(lesson.problem.keyPoints.lead, "");
  assert.deepEqual(
    lesson.steps.map((step) => [step.id, step.title]),
    [
      ["s1", "观察结构"],
      ["s2", "应用基本不等式"],
      ["s3", "验证取等"],
    ],
  );

  const structure = lesson.steps[0].visual;
  assert.equal(lesson.steps[0].section, "基本不等式");
  assert.equal(structure.kind, "basic-inequality-structure-scan");
  assert.match(structure.target.expression, /x\+\\frac\{4\}\{x\+1\}/);
  assert.equal(structure.organization.label, "整理目标整式：补出与分母配对的正项");
  assert.match(structure.organization.motive, /看分母.*□=x\+1/);
  assert.deepEqual(structure.organization.slotHint, {
    numerator: "常数",
    action: "补出",
    value: "\\(x+1\\)",
    rewrite: {
      source: "x",
    },
    ariaLabel: "看到常数除以方框，就补出与分母配对的正项；本题方框表示 x 加 1，x 等于方框减 1",
  });
  assert.deepEqual(structure.organization.steps, [
    "\\(x=(x+1)-1\\)",
    "\\(x+\\frac{4}{x+1}=\\left[(x+1)+\\frac{4}{x+1}\\right]-1\\)",
  ]);
  assert.equal(structure.organization.note, "括号内出现定积");
  assert.equal(structure.pattern.condition.tag, "定积 4");
  assert.equal(structure.pattern.target.tag, "求最小值");
  assert.equal(structure.reading, "定积求和");
  assert.equal(structure.route, "直接应用基本不等式");
  assert.deepEqual(lesson.steps[0].derive[0], ["结构判断", "补出分母配对正项｜定积求和"]);

  const html = fs.readFileSync(path.join(repoRoot, lesson.meta.outputPath), "utf8");
  assert.match(html, /整理目标整式：补出与分母配对的正项/);
  assert.match(html, /□=x\+1/);
  assert.doesNotMatch(html, /对旁边的一次项动手|待装槽|旁路/);
  assert.match(html, /括号内出现定积/);
  const runtime = fs.readFileSync(path.join(repoRoot, "site/assets/js/lesson-page-runtime.js"), "utf8");
  assert.match(runtime, /basic-structure-organization-motive/);
  assert.match(runtime, /basic-structure-slot-hint/);
  assert.match(runtime, /basic-structure-slot-rewrite/);
  assert.match(runtime, /basic-structure-org-step/);
  assert.match(runtime, /basic-structure-slot-box/);

  const visual = lesson.steps[1].visual;
  assert.equal(visual.kind, "basic-inequality-mapping");
  assert.equal(visual.methodTag, "直接应用｜定积求和");
  assert.equal(visual.fixedSourceTarget, "product");
  assert.equal(visual.conditionFlow, undefined);
  assert.match(visual.fixedCondition, /\(x\+1\).*\\frac\{4\}\{x\+1\}=4/);
  assert.deepEqual(
    visual.mappings.map((mapping) => [mapping.value, mapping.shape]),
    [["\\(x+1\\)", "square"], ["\\(\\frac{4}{x+1}\\)", "circle"]],
  );
  assert.match(visual.conclusion, /3/);
  assert.equal(visual.templateLabel, "代入基本不等式");
  assert.equal(visual.formulaStyle, "sum-geometric");
  assert.equal(visual.showPositiveStep, true);
  assert.equal(visual.equalityResult, undefined);
  assert.equal(lesson.steps[2].visual.kind, "basic-inequality-equality-check");
  assert.equal(lesson.steps[2].visual.solved, "\\(x=1\\)");
  assert.match(lesson.steps[2].visual.verification, /x\+\\frac\{4\}\{x\+1\}=3/);
  for (const item of lesson.steps.flatMap((step) => step.reasoning)) {
    assert.doesNotMatch(item.text, /\\Rightarrow|因为|所以|。$/);
  }

  const eighth = readLesson("inequality-basic-q06");
  assert.equal(eighth.problem.keyPoints.lead, "");
  assert.deepEqual(
    eighth.steps.map((step) => [step.id, step.title]),
    [
      ["s1", "观察结构"],
      ["s2", "应用基本不等式"],
      ["s3", "验证取等"],
    ],
  );
  const eighthStructure = eighth.steps[0].visual;
  assert.equal(eighth.steps[0].section, "基本不等式");
  assert.equal(eighthStructure.kind, "basic-inequality-structure-scan");
  assert.equal(eighthStructure.organization.label, "整理目标整式：补出与分母配对的正项");
  assert.match(eighthStructure.organization.motive, /看分母.*x\+3/);
  assert.deepEqual(eighthStructure.organization.slotHint, {
    numerator: "常数",
    action: "补出",
    actionCoefficient: "2",
    value: "\\(x+3\\)",
    rewrite: {
      source: "2x",
      coefficient: "2",
      remainder: "− 6",
    },
    ariaLabel: "看到常数除以方框，先令方框等于分母 x 加 3；按一次项系数补出两个方框，并把 2x 改写成两个方框减 6",
  });
  assert.deepEqual(eighthStructure.organization.steps, [
    "\\(2x=2(x+3)-6\\)",
    "\\(2x+\\frac{1}{x+3}=\\left[2(x+3)+\\frac{1}{x+3}\\right]-6\\)",
  ]);
  assert.equal(eighthStructure.organization.note, "括号内出现定积");
  assert.equal(eighthStructure.pattern.condition.tag, "定积 2");
  assert.deepEqual(eighth.steps[0].derive[0], ["结构判断", "补出分母配对正项｜定积求和"]);

  const eighthVisual = eighth.steps[1].visual;
  assert.equal(eighthVisual.kind, "basic-inequality-mapping");
  assert.equal(eighthVisual.fixedSourceTarget, "product");
  assert.deepEqual(
    eighthVisual.mappings.map((mapping) => [mapping.value, mapping.shape]),
    [["\\(2(x+3)\\)", "square"], ["\\(\\frac{1}{x+3}\\)", "circle"]],
  );
  assert.match(eighthVisual.fixedCondition, /=2/);
  assert.match(eighthVisual.conclusion, /2\\sqrt2-6/);
  assert.equal(eighth.steps[2].visual.kind, "basic-inequality-equality-check");
  assert.equal(eighth.steps[2].visual.solved, "\\(x=\\frac{\\sqrt2}{2}-3\\)");
  assert.match(eighth.steps[2].visual.conclusion, /2\\sqrt2-6.*B/);
  assert.match(runtime, /slotHint\.rewrite\.remainder/);
  assert.match(runtime, /slotHint\.rewrite\.coefficient/);
  assert.match(runtime, /slotHint\.actionCoefficient/);
  const pageStyles = fs.readFileSync(
    path.join(repoRoot, "site/assets/css/interactive-geometry-page.css"),
    "utf8",
  );
  assert.match(pageStyles, /\.basic-structure-pattern-term\s*\{[^}]*min-width:\s*50px;/s);
  assert.match(pageStyles, /\.basic-structure-pattern-link\s*\{[^}]*grid-column:\s*2;[^}]*grid-row:\s*2;/s);
  assert.doesNotMatch(pageStyles, /\.basic-structure-pattern-link\s*\{[^}]*transform:/s);
  assert.match(pageStyles, /\.basic-map-source\.is-slot-circle strong/);
  assert.match(pageStyles, /\.basic-equality-term\s*\{[^}]*min-width:\s*58px;/s);

  const tianjin2020 = readLesson("inequality-basic-q08");
  assert.equal(tianjin2020.problem.keyPoints.lead, "");
  assert.deepEqual(
    tianjin2020.steps.map((step) => [step.id, step.title]),
    [
      ["s1", "观察结构"],
      ["s2", "应用基本不等式"],
      ["s3", "验证取等"],
    ],
  );
  const tianjinStructure = tianjin2020.steps[0].visual;
  assert.equal(tianjinStructure.kind, "basic-inequality-structure-scan");
  assert.equal(tianjinStructure.organization.label, "整理目标整式：通分显条件");
  assert.match(tianjinStructure.organization.motive, /前两项分母分别含/);
  assert.equal(tianjinStructure.organization.combineHint.action, "通分后分母出现条件量");
  assert.equal(tianjinStructure.organization.method, undefined);
  assert.deepEqual(
    tianjinStructure.organization.steps.map((item) => item.label),
    ["通分", "代入", "消元剩（a+b）"],
  );
  assert.match(tianjinStructure.organization.steps[0].expression, /\\frac\{1\}\{2a\}.*\\frac\{a\+b\}\{2ab\}/);
  assert.match(tianjinStructure.organization.steps[1].expression, /ab=1.*\\frac\{a\+b\}\{2\}/);
  assert.equal(tianjinStructure.organization.steps[2].marks, undefined);
  assert.equal(tianjinStructure.pattern.condition.tag, "定积 4");
  assert.deepEqual(tianjin2020.steps[0].derive[0], ["结构判断", "通分显条件｜定积求和"]);

  const tianjinMapping = tianjin2020.steps[1].visual;
  assert.equal(tianjinMapping.kind, "basic-inequality-mapping");
  assert.deepEqual(
    tianjinMapping.mappings.map((mapping) => [mapping.value, mapping.shape]),
    [["\\(\\frac{a+b}{2}\\)", "square"], ["\\(\\frac{8}{a+b}\\)", "circle"]],
  );
  assert.equal(tianjinMapping.fixedCondition, "\\(\\frac{a+b}{2}\\cdot\\frac{8}{a+b}=4\\)");
  assert.equal(tianjin2020.steps[2].visual.kind, "basic-inequality-equality-check");
  assert.equal(tianjin2020.steps[2].visual.solved, "\\(\\{a,b\\}=\\{2-\\sqrt3，2+\\sqrt3\\}\\)");

  const eleventh = readLesson("inequality-basic-q10");
  assert.equal(eleventh.problem.keyPoints.lead, "");
  assert.deepEqual(
    eleventh.steps.map((step) => [step.id, step.title]),
    [
      ["s1", "观察结构"],
      ["s2", "应用基本不等式"],
      ["s3", "验证取等"],
    ],
  );
  const eleventhStructure = eleventh.steps[0].visual;
  assert.equal(eleventh.steps[0].section, "基本不等式");
  assert.equal(eleventhStructure.kind, "basic-inequality-structure-scan");
  assert.equal(eleventhStructure.organization.label, "整理目标整式：统一底数显条件");
  assert.match(eleventhStructure.organization.motive, /看底数.*8=2\^3/);
  assert.deepEqual(eleventhStructure.organization.baseHint, {
    kind: "common-base",
    sourceLabel: "底数不同",
    source: "\\(A^u+B^v\\)",
    relationLabel: "寻找共同底数",
    relations: ["\\(A=c^m\\)", "\\(B=c^n\\)"],
    resultLabel: "统一底数",
    result: "\\(c^{mu}+c^{nv}\\)",
    productLabel: "乘积指数",
    productExponent: "\\(mu+nv\\)",
    targetLabel: "对照条件量",
    ariaLabel: "统一底数的一般方法：把底数 A 和 B 都表示为共同底数 c 的幂，目标改写为 c 的 mu 次方加 c 的 nv 次方，乘积指数 mu 加 nv 再与条件量对照",
  });
  assert.doesNotMatch(
    [
      eleventhStructure.organization.baseHint.source,
      ...eleventhStructure.organization.baseHint.relations,
      eleventhStructure.organization.baseHint.result,
      eleventhStructure.organization.baseHint.productExponent,
    ].join(""),
    /2|8|-3b/,
  );
  assert.deepEqual(
    eleventhStructure.organization.steps.map((item) => item.label),
    ["化倒数", "统一底数", "重写目标"],
  );
  assert.equal(eleventhStructure.organization.steps[1].marks.bracket, "指数 −3b");
  assert.match(eleventhStructure.organization.note, /乘积指数出现条件量.*a-3b/);
  assert.equal(eleventhStructure.pattern.condition.tag, "定积 1/64");
  assert.deepEqual(eleventh.steps[0].derive[0], ["结构判断", "统一底数显条件｜定积求和"]);

  const eleventhVisual = eleventh.steps[1].visual;
  assert.equal(eleventhVisual.methodTag, "直接应用｜定积求和");
  assert.equal(eleventhVisual.fixedSourceTarget, "product");
  assert.deepEqual(
    eleventhVisual.mappings.map((mapping) => [mapping.value, mapping.shape]),
    [["\\(2^a\\)", "square"], ["\\(2^{-3b}\\)", "circle"]],
  );
  assert.equal(eleventhVisual.conditionFlow, undefined);
  assert.match(eleventhVisual.fixedCondition, /2\^\{a-3b\}=2\^\{-6\}=\\frac\{1\}\{64\}/);
  assert.equal(eleventh.steps[2].visual.kind, "basic-inequality-equality-check");
  assert.equal(eleventh.steps[2].visual.solved, "\\(a=-3，b=1\\)");
  assert.match(eleventh.steps[2].visual.verification, /2\^a\+\\frac\{1\}\{8\^b\}=\\frac\{1\}\{4\}/);
  assert.doesNotMatch(JSON.stringify(eleventh), /t=8\^b|换元/);
  assert.match(runtime, /organization\.baseHint/);
  assert.match(runtime, /basic-structure-base-hint/);
  assert.match(runtime, /baseHint\.kind === "common-base"/);
  assert.match(runtime, /basic-structure-base-insight/);
  assert.match(pageStyles, /\.basic-structure-base-hint/);

  const thirteenth = readLesson("inequality-basic-q13");
  assert.equal(thirteenth.problem.keyPoints.lead, "");
  assert.deepEqual(
    thirteenth.steps.map((step) => [step.id, step.title]),
    [
      ["s1", "观察结构"],
      ["s2", "应用基本不等式"],
      ["s3", "验证取等"],
    ],
  );
  const thirteenthStructure = thirteenth.steps[0].visual;
  assert.equal(thirteenth.steps[0].section, "基本不等式");
  assert.equal(thirteenthStructure.kind, "basic-inequality-structure-scan");
  assert.equal(thirteenthStructure.organization.label, "整理条件与目标：对照条件配凑正项");
  assert.match(thirteenthStructure.organization.motive, /条件提取两个完整正项.*目标对齐同一组正项/);
  const sharedAlignmentHint = {
    kind: "condition-positive-term-alignment",
    method: "对照条件配凑正项",
    conditionLabel: "条件中提取完整正项",
    condition: {
      first: { value: "\\(P\\)", shape: "square" },
      second: { value: "\\(Q\\)", shape: "circle" },
      fixed: "\\(K\\)",
    },
    linkLabel: "沿用同一组完整正项",
    targetLabel: "目标配凑",
    target: {
      first: { coefficient: "\\(r\\)", value: "\\(P\\)", shape: "square" },
      second: { coefficient: "\\(s\\)", value: "\\(Q\\)", shape: "circle" },
      constant: "\\(C\\)",
      constantLabel: "常数旁置",
    },
    productLabel: "检查新定积",
    product: "\\((rP)(sQ)=rsK\\)",
    ariaLabel: "对照条件配凑正项的一般方法：P、Q、r、s 均为正数，条件给出 P 与 Q 的乘积为 K；目标对齐为 rP 加 sQ 加常数 C，其中常数旁置；两个参与基本不等式的新正项乘积为 rsK",
  };
  assert.deepEqual(thirteenthStructure.organization.alignmentHint, sharedAlignmentHint);
  assert.equal(thirteenthStructure.organization.shiftHint, undefined);
  assert.doesNotMatch(JSON.stringify(thirteenthStructure.organization.alignmentHint), /a\+1|b\+2|16|x\+y|3x/);
  assert.deepEqual(
    thirteenthStructure.organization.steps.map((item) => [item.label, item.expression]),
    [
      ["逐项补齐", "\\(a=(a+1)-1，b=(b+2)-2\\)"],
      ["重写目标", "\\(a+b=\\left[(a+1)+(b+2)\\right]-3\\)"],
    ],
  );
  assert.equal(thirteenthStructure.organization.note, "括号内出现定积两项之和");
  assert.equal(thirteenthStructure.pattern.condition.tag, "定积 16");
  assert.deepEqual(thirteenth.steps[0].derive[0], ["结构判断", "对照条件配凑正项｜定积求和"]);

  const thirteenthVisual = thirteenth.steps[1].visual;
  assert.equal(thirteenthVisual.methodTag, "直接应用｜定积求和");
  assert.equal(thirteenthVisual.fixedSourceTarget, "product");
  assert.deepEqual(
    thirteenthVisual.mappings.map((mapping) => [mapping.value, mapping.shape]),
    [["\\(a+1\\)", "square"], ["\\(b+2\\)", "circle"]],
  );
  assert.equal(thirteenthVisual.conditionFlow, undefined);
  assert.equal(thirteenthVisual.fixedCondition, "\\((a+1)(b+2)=16\\)");
  assert.match(thirteenthVisual.conclusion, /5/);
  assert.equal(thirteenthVisual.equalityResult, undefined);
  assert.equal(thirteenth.steps[2].visual.kind, "basic-inequality-equality-check");
  assert.equal(thirteenth.steps[2].visual.solved, "\\(a=3，b=2\\)");
  assert.match(thirteenth.steps[2].visual.verification, /a\+b=5/);
  assert.match(runtime, /organization\.alignmentHint/);
  assert.match(runtime, /basic-structure-alignment-hint/);
  assert.doesNotMatch(runtime, /alignmentHint\.assumption|alignmentHint\.principle/);
  assert.match(pageStyles, /\.basic-structure-alignment-hint/);
  assert.doesNotMatch(pageStyles, /\.basic-structure-alignment-hint\s*>\s*footer/);

  const paired = readLesson("inequality-basic-q28");
  assert.equal(paired.problem.keyPoints.lead, "");
  assert.deepEqual(
    paired.steps.map((step) => [step.id, step.title]),
    [
      ["s1", "观察结构"],
      ["s2", "应用基本不等式"],
      ["s3", "验证取等"],
    ],
  );
  const pairedStructure = paired.steps[0].visual;
  assert.equal(paired.steps[0].section, "基本不等式");
  assert.equal(pairedStructure.kind, "basic-inequality-structure-scan");
  assert.equal(pairedStructure.organization.label, "整理条件与目标：对照条件配凑正项");
  assert.match(pairedStructure.organization.motive, /条件提取两个完整正项.*目标对齐同一组正项/);
  assert.deepEqual(pairedStructure.organization.alignmentHint, sharedAlignmentHint);
  assert.equal(pairedStructure.organization.pairHint, undefined);
  assert.deepEqual(
    pairedStructure.organization.steps.map((item) => item.label),
    ["提取整块", "对齐目标", "确定新定积"],
  );
  assert.equal(pairedStructure.organization.steps[0].marks.bracket, "定积整块 x 与 x+y");
  assert.equal(pairedStructure.organization.steps[1].marks.bracket, "同一组整块");
  assert.equal(pairedStructure.organization.note, "条件确定乘积，目标使用同一组整块");
  assert.equal(pairedStructure.pattern.condition.tag, "定积 9");
  assert.deepEqual(paired.steps[0].derive[0], ["结构判断", "对照条件配凑正项｜定积求和"]);

  const pairedVisual = paired.steps[1].visual;
  assert.equal(pairedVisual.kind, "basic-inequality-mapping");
  assert.equal(pairedVisual.methodTag, "直接应用｜定积求和");
  assert.equal(pairedVisual.conditionFlow, undefined);
  assert.deepEqual(
    pairedVisual.mappings.map((mapping) => [mapping.value, mapping.shape]),
    [["\\(3x\\)", "square"], ["\\(x+y\\)", "circle"]],
  );
  assert.equal(pairedVisual.fixedCondition, "\\((3x)(x+y)=3x(x+y)=9\\)");
  assert.equal(pairedVisual.substituted, "\\(4x+y\\ge6\\)");
  assert.equal(pairedVisual.equalityResult, undefined);
  assert.equal(paired.steps[2].visual.kind, "basic-inequality-equality-check");
  assert.equal(paired.steps[2].visual.solved, "\\(x=1，y=2\\)");
  assert.equal(paired.steps[2].visual.verification, "\\(4x+y=6\\)");
  assert.equal(
    JSON.stringify(thirteenthStructure.organization.alignmentHint),
    JSON.stringify(pairedStructure.organization.alignmentHint),
  );
  assert.doesNotMatch(JSON.stringify(paired), /换元法|条件消元法|配齐次式|T=/);
});

test("checked Gaokao basic-inequality exercises keep their source order and exact equality cases", () => {
  const lessons = [
    readLesson("inequality-basic-q07"),
    readLesson("inequality-basic-q08"),
    readLesson("inequality-basic-q09"),
    readLesson("inequality-basic-q10"),
    readLesson("inequality-basic-q11"),
    readLesson("inequality-basic-q12"),
  ];
  assert.deepEqual(
    lessons.map((lesson) => lesson.problem.source),
    [
      "2021 天津高考",
      "2020 天津高考",
      "2019 天津高考（文科）",
      "2018 天津高考（理科）",
      "2017 天津高考（理科、文科）",
      "2020 江苏高考",
    ],
  );
  assert.deepEqual(
    lessons.map((lesson) => lesson.steps.at(-1).derive[0]),
    [
      ["最小值", "2√2"],
      ["最小值", "4"],
      ["最小值", "9/2"],
      ["最小值", "1/4"],
      ["最小值", "4"],
      ["最小值", "4/5"],
    ],
  );
  assert.deepEqual(lessons.map((lesson) => lesson.steps.length), [4, 3, 3, 3, 4, 1]);
  assert.deepEqual(
    lessons.map((lesson) => lesson.steps.map((item) => item.visual?.kind)),
    [
      [
        "basic-inequality-structure-scan",
        "basic-inequality-mapping",
        "basic-inequality-mapping",
        "basic-inequality-equality-check",
      ],
      ["basic-inequality-structure-scan", "basic-inequality-mapping", "basic-inequality-equality-check"],
      ["basic-inequality-structure-scan", "basic-inequality-mapping", "basic-inequality-equality-check"],
      ["basic-inequality-structure-scan", "basic-inequality-mapping", "basic-inequality-equality-check"],
      [
        "basic-inequality-structure-scan",
        "basic-inequality-mapping",
        "basic-inequality-mapping",
        "basic-inequality-equality-check",
      ],
      ["basic-inequality-mapping"],
    ],
  );
  assert.deepEqual(
    lessons[0].steps.map((item) => [item.id, item.title]),
    [
      ["s1", "观察结构"],
      ["s2", "应用基本不等式消元"],
      ["s3", "再次应用基本不等式取极值"],
      ["s4", "验证取等"],
    ],
  );
  const q07CountHint = lessons[0].steps[0].visual.organization.relationCountHint;
  assert.equal(lessons[0].steps[0].visual.condition.tag, "已有取等条件数 0");
  assert.equal(lessons[0].steps[0].visual.target.tag, "含 a、b 两个变量");
  assert.deepEqual(
    [q07CountHint.variable.value, q07CountHint.condition.value, q07CountHint.result.value],
    ["2", "0", "2"],
  );
  assert.equal(q07CountHint.variable.symbol, undefined);
  assert.equal(q07CountHint.condition.symbol, undefined);
  assert.equal(q07CountHint.result.symbol, undefined);
  assert.equal(q07CountHint.substitution, undefined);
  assert.equal(lessons[0].steps[0].visual.caption, undefined);
  assert.equal(q07CountHint.conclusion, undefined);
  assert.equal(lessons[0].steps[0].visual.organization.motive, undefined);
  const q07Runtime = fs.readFileSync(path.join(repoRoot, "site/assets/js/lesson-page-runtime.js"), "utf8");
  const q07Styles = fs.readFileSync(path.join(repoRoot, "site/assets/css/interactive-geometry-page.css"), "utf8");
  assert.match(q07Runtime, /basic-structure-relation-count/);
  assert.match(q07Styles, /\.basic-structure-relation-equation/);
  assert.equal(lessons[0].steps[1].visual.kind, "basic-inequality-mapping");
  assert.equal(lessons[0].steps[1].visual.conditionFlowLabel, "判断消去谁");
  assert.deepEqual(lessons[0].steps[1].visual.conditionFlow, [
    "目标含 \\(a、b\\)",
    "\\(\\frac{1}{a}\\cdot\\frac{a}{b^2}=\\frac{1}{b^2}\\)",
    "先消去 \\(a\\)",
  ]);
  assert.deepEqual(
    lessons[0].steps[1].visual.mappings.map((mapping) => mapping.value),
    ["\\(\\frac{1}{a}\\)", "\\(\\frac{a}{b^2}\\)"],
  );
  assert.match(lessons[0].steps[1].visual.substituted, /\\frac\{2\}\{b\}\+b/);
  assert.equal(lessons[0].steps[1].visual.equalityResult, "\\(a=b\\)");
  assert.equal(lessons[0].steps[2].visual.fixedCondition, "\\(\\frac{2}{b}\\cdot b=2\\)");
  assert.match(lessons[0].steps[2].visual.conclusion, /2\\sqrt2/);
  assert.deepEqual(
    lessons[0].steps[3].visual.equalities.map((item) => [item.label, item.first.shape, item.second.shape, item.result]),
    [
      ["第 1 次取等", "square", "circle", "\\(a=b\\)"],
      ["第 2 次取等", "square", "circle", "\\(b=\\sqrt2\\)"],
    ],
  );
  assert.deepEqual(
    lessons[0].steps[3].visual.equalities.map((item) => [item.first.value, item.second.value]),
    [
      ["\\(\\frac{1}{a}\\)", "\\(\\frac{a}{b^2}\\)"],
      ["\\(\\frac{2}{b}\\)", "\\(b\\)"],
    ],
  );
  assert.equal(lessons[0].steps[3].visual.solved, "\\(a=b=\\sqrt2\\)");
  assert.match(q07Runtime, /basic-equality-system-solve/);
  assert.match(q07Styles, /\.basic-equality-system/);
  assert.deepEqual(
    lessons[0].steps[3].derive[0],
    ["最小值", "2√2"],
  );
  assert.equal(lessons[1].steps[0].section, "基本不等式");
  assert.equal(lessons[1].steps[0].visual.kind, "basic-inequality-structure-scan");
  assert.equal(lessons[1].steps[1].visual.methodTag, "直接应用｜定积求和");
  assert.equal(lessons[1].steps[1].visual.fixedSourceTarget, "product");
  assert.deepEqual(
    lessons[1].steps[1].visual.mappings.map((mapping) => [mapping.value, mapping.shape]),
    [["\\(\\frac{a+b}{2}\\)", "square"], ["\\(\\frac{8}{a+b}\\)", "circle"]],
  );
  assert.match(lessons[1].steps[0].visual.organization.steps[0].expression, /\\frac\{1\}\{2a\}.*\\frac\{a\+b\}\{2ab\}/);
  assert.equal(lessons[1].steps[0].visual.organization.label, "整理目标整式：通分显条件");
  assert.equal(lessons[1].steps[0].visual.organization.combineHint.action, "通分后分母出现条件量");
  assert.equal(lessons[1].steps[0].visual.organization.combineHint.mark, "ab");
  assert.deepEqual(
    lessons[1].steps[0].visual.organization.steps.map((item) => item.label),
    ["通分", "代入", "消元剩（a+b）"],
  );
  assert.equal(lessons[1].steps[0].visual.organization.steps[0].marks.bracket, "显出 ab");
  assert.equal(lessons[1].steps[0].visual.organization.steps[2].marks, undefined);
  assert.equal(lessons[1].steps[0].visual.organization.note, "消元只剩 \\((a+b)\\)，目标显形");
  assert.deepEqual(lessons[1].steps[0].derive[0], ["结构判断", "通分显条件｜定积求和"]);
  assert.match(lessons[1].steps[1].visual.fixedCondition, /=4/);
  const q08Runtime = fs.readFileSync(path.join(repoRoot, "site/assets/js/lesson-page-runtime.js"), "utf8");
  assert.match(q08Runtime, /basic-structure-combine-hint/);
  assert.match(q08Runtime, /basic-structure-combine-sum/);
  assert.doesNotMatch(JSON.stringify(lessons[1]), /s=a\+b/);
  assert.doesNotMatch(JSON.stringify(lessons[1]), /练习 8-4/);
  assert.match(JSON.stringify(lessons[1]), /a\+b=4.*ab=1/);
  assert.match(JSON.stringify(lessons[2]), /xy\\\\le2.*\\\\frac\{9\}\{2\}/);
  assert.equal(lessons[2].steps[0].section, "基本不等式");
  assert.equal(lessons[2].steps[0].visual.kind, "basic-inequality-structure-scan");
  assert.equal(lessons[2].steps[0].visual.organization.label, "整理目标整式：展开显条件");
  assert.equal(lessons[2].steps[0].visual.organization.expandHint.action, "展开后出现条件量");
  assert.deepEqual(
    lessons[2].steps[0].visual.organization.steps.map((item) => item.label),
    ["展开", "代入", "消元只剩 xy"],
  );
  assert.equal(lessons[2].steps[0].visual.organization.steps[0].marks.bracket, "条件量 x+2y");
  assert.equal(lessons[2].steps[0].visual.organization.steps[2].marks.bracket, "只剩 xy");
  assert.match(lessons[2].steps[0].visual.organization.note, /消元只剩.*xy.*显形/);
  assert.match(lessons[2].steps[0].visual.organization.steps[0].expression, /2xy\+\(x\+2y\)\+1/);
  assert.match(lessons[2].steps[0].visual.organization.steps[1].expression, /x\+2y=4.*2xy\+5/);
  assert.deepEqual(lessons[2].steps[0].derive[0], ["结构判断", "展开显条件｜定和求积"]);
  const q09Runtime = fs.readFileSync(path.join(repoRoot, "site/assets/js/lesson-page-runtime.js"), "utf8");
  assert.match(q09Runtime, /basic-structure-expand-hint/);
  assert.match(q09Runtime, /basic-structure-expand-product/);
  assert.equal(lessons[2].steps[1].visual.methodTag, "直接应用｜定和求积");
  assert.deepEqual(
    lessons[2].steps[1].visual.mappings.map((mapping) => [mapping.value, mapping.shape]),
    [["\\(x\\)", "square"], ["\\(2y\\)", "circle"]],
  );
  assert.equal(lessons[2].steps[1].visual.fixedCondition, "\\(x+2y=4\\)");
  assert.equal(lessons[2].steps[2].visual.solved, "\\(x=2，y=1\\)");
  assert.doesNotMatch(JSON.stringify(lessons[2]), /u=x|v=2y/);
  assert.match(JSON.stringify(lessons[3]), /a=-3，b=1/);
  assert.equal(lessons[3].steps[0].section, "基本不等式");
  assert.equal(lessons[3].steps[0].visual.organization.label, "整理目标整式：统一底数显条件");
  assert.equal(lessons[3].steps[0].visual.organization.baseHint.kind, "common-base");
  assert.equal(lessons[3].steps[0].visual.organization.baseHint.result, "\\(c^{mu}+c^{nv}\\)");
  assert.deepEqual(
    lessons[3].steps[0].visual.organization.steps.map((item) => item.label),
    ["化倒数", "统一底数", "重写目标"],
  );
  assert.deepEqual(
    lessons[3].steps[1].visual.mappings.map((mapping) => [mapping.value, mapping.shape]),
    [["\\(2^a\\)", "square"], ["\\(2^{-3b}\\)", "circle"]],
  );
  assert.equal(lessons[3].steps[2].visual.solved, "\\(a=-3，b=1\\)");
  assert.match(JSON.stringify(lessons[4]), /a\^2=2b\^2/);
  assert.match(JSON.stringify(lessons[4]), /ab=\\\\frac\{1\}\{2\}/);
  const q11CountHint = lessons[4].steps[0].visual.organization.relationCountHint;
  assert.deepEqual(
    [q11CountHint.variable.value, q11CountHint.condition.value, q11CountHint.result.value],
    ["2", "0", "2"],
  );
  assert.deepEqual(lessons[4].steps.slice(1, 3).map((step) => step.visual.mappings.map((item) => item.value)), [
    ["\\(a^4\\)", "\\(4b^4\\)"],
    ["\\(4ab\\)", "\\(\\frac{1}{ab}\\)"],
  ]);
  assert.equal(lessons[4].steps[1].title, "应用基本不等式消元");
  assert.equal(lessons[4].steps[1].visual.methodTag, "第 1 次｜合并变量消元");
  assert.deepEqual(lessons[4].steps[1].visual.conditionFlow, [
    "目标分别含 \\(a、b\\)",
    "\\(a^4\\cdot4b^4=4(ab)^4\\)",
    "合并变量，消元只剩整体 \\(ab\\)",
  ]);
  assert.match(lessons[4].steps[1].visual.conclusion, /只剩整体.*ab/);
  assert.deepEqual(lessons[4].steps[3].visual.equalities.map((item) => item.result), [
    "\\(a^2=2b^2\\)",
    "\\(ab=\\frac{1}{2}\\)",
  ]);
  assert.match(
    lessons[4].steps.slice(1, 3).flatMap((step) => step.reasoning.map((item) => item.text)).join(" "),
    /a\^4\+4b\^4.*4\(ab\)\^2.*4ab\+\\frac\{1\}\{ab\}.*4ab.*\\frac\{1\}\{ab\}.*4/,
  );
  assert.doesNotMatch(JSON.stringify(lessons[4]), /p=ab|4p|\\\\frac\{1\}\{p\}/);
  assert.match(JSON.stringify(lessons[5]), /0<v\\\\le1/);
  assert.match(JSON.stringify(lessons[5]), /x\^2=\\\\frac\{3\}\{10\}，y\^2=\\\\frac\{1\}\{2\}/);
  assert.ok(lessons.every((lesson) => fs.existsSync(path.join(repoRoot, lesson.meta.outputPath))));
});

test("quadratic inequality exercises read their solution sets from function graphs", () => {
  const lessons = [
    readLesson("inequality-solving-quadratic-q01"),
    readLesson("inequality-solving-quadratic-q02"),
    readLesson("inequality-solving-quadratic-q03"),
  ];
  assert.deepEqual(
    lessons.map((lesson) => lesson.steps[0].visual.kind),
    [
      "quadratic-function-sign-graphs",
      "quadratic-function-sign-graphs",
      "quadratic-function-sign-graphs",
    ],
  );
  assert.deepEqual(
    lessons.map((lesson) => lesson.steps[0].visual.graphs.length),
    [1, 1, 4],
  );
  assert.deepEqual(
    lessons[2].steps[0].visual.graphs.map((graph) => graph.solutionMode),
    ["middle-closed", "outside-closed", "except-root", "all"],
  );
  assert.match(JSON.stringify(lessons[0].problem.keyPoints), /先看 a.*再看 Δ/);
  assert.deepEqual(lessons[0].steps[0].derive[0], ["答案", "B"]);
  assert.match(JSON.stringify(lessons[0].steps[0].reasoning), /subsetneq.*必要不充分/);

  const catalog = fs.readFileSync(
    path.join(repoRoot, "internal/senior-high/catalog/learning-topics.json"),
    "utf8",
  );
  assert.match(
    catalog,
    /"lessonId":"inequality-solving-quadratic-q01"[^\n]+"expected":"B"/,
  );

  const runtime = fs.readFileSync(
    path.join(repoRoot, "site/assets/js/lesson-page-runtime.js"),
    "utf8",
  );
  assert.match(runtime, /quadratic-function-sign-graphs/);
  assert.match(runtime, /lesson-quadratic-root.*is-included/);
});

test("polynomial inequality exercises reuse the threading-line knowledge graphic", () => {
  const first = readLesson("inequality-solving-polynomial-q01");
  const second = readLesson("inequality-solving-polynomial-q02");
  const third = readLesson("inequality-solving-polynomial-q03");
  assert.deepEqual(
    first.steps.map((step) => step.visual.kind),
    [
      "polynomial-threading-graph",
      "polynomial-threading-graph",
      "polynomial-threading-graph",
    ],
  );
  assert.equal(second.steps[0].visual.kind, "polynomial-threading-graph");
  assert.equal(third.steps[0].visual.kind, "polynomial-threading-graph");
  assert.deepEqual(
    first.steps[2].visual.roots.map((root) => root.multiplicity),
    [1, 2, 1],
  );
  assert.deepEqual(third.steps[0].visual.signs, ["+", "-", "-", "+"]);
  assert.equal(third.steps[0].visual.selectSign, "-");
  assert.match(JSON.stringify(first.problem.keyPoints), /正首项.*定根.*右起.*奇穿偶不穿.*读阴影/);
  assert.match(JSON.stringify(second.steps[0].reasoning), /穿针引线法.*最右侧正号/);
  assert.match(JSON.stringify(third.steps[0].reasoning), /偶数重根 2 处接触后返回/);

  const runtime = fs.readFileSync(
    path.join(repoRoot, "site/assets/js/lesson-page-runtime.js"),
    "utf8",
  );
  assert.match(runtime, /polynomial-threading-graph/);
  assert.match(runtime, /从最右侧开始穿/);
  assert.match(runtime, /lesson-threading-even-ring/);
  assert.match(runtime, /lesson-threading-shades/);
});

test("rational inequality exercises distinguish numerator zeros from denominator forbidden points", () => {
  const lessons = Array.from({ length: 4 }, (_, index) => (
    readLesson(`inequality-solving-rational-q0${index + 1}`)
  ));
  assert.ok(lessons.every((lesson) => (
    lesson.steps[0].visual.kind === "rational-threading-graph"
  )));
  assert.deepEqual(
    lessons[0].steps[0].visual.roots.map((root) => [root.kind, root.included]),
    [["numerator", true], ["denominator", false]],
  );
  assert.deepEqual(
    lessons[1].steps[0].visual.roots.map((root) => [root.kind, root.included]),
    [["numerator", true], ["denominator", false]],
  );
  assert.ok(lessons[2].steps[0].visual.denominatorEvidence);
  assert.match(
    JSON.stringify(lessons[2].steps[0].visual.denominatorEvidence),
    /a=1>0.*Delta=-3<0.*恒在 x 轴上方/,
  );
  assert.deepEqual(
    lessons[3].steps[0].visual.roots.map((root) => root.kind),
    ["denominator", "numerator"],
  );
  assert.match(JSON.stringify(lessons[0].problem.keyPoints), /分式不等式知识点.*禁值条件/);
  assert.match(JSON.stringify(lessons[2].problem.keyPoints), /分式穿针/);
  assert.match(JSON.stringify(lessons[2].problem.keyPoints), /二次函数图像/);

  const runtime = fs.readFileSync(
    path.join(repoRoot, "site/assets/js/lesson-page-runtime.js"),
    "utf8",
  );
  assert.match(runtime, /rational-threading-graph/);
  assert.match(runtime, /lesson-rational-forbidden-mark/);
  assert.match(runtime, /lesson-rational-denominator-evidence/);
});

test("absolute inequality exercises cite the matching method and visualize each solution structure", () => {
  const lessons = [
    readLesson("inequality-solving-absolute-q01"),
    readLesson("inequality-solving-absolute-q02"),
    readLesson("inequality-solving-absolute-q03"),
  ];
  assert.ok(lessons.every((lesson) => (
    lesson.steps[0].visual.kind === "absolute-inequality-visual"
  )));
  assert.deepEqual(
    lessons.map((lesson) => lesson.steps[0].visual.mode),
    ["direct-inclusion", "rhs-sign-classification", "piecewise-sum"],
  );
  assert.match(JSON.stringify(lessons[0].problem.keyPoints), /直接法.*小于取中间.*真包含/);
  assert.ok(lessons[0].steps[0].visual.solution.includes("\\subsetneq"));
  assert.match(lessons[0].steps[0].visual.facts.join(" "), /x=4/);
  assert.match(JSON.stringify(lessons[1].problem.keyPoints), /不能直接平方.*2x 的正负分类/);
  assert.equal(lessons[1].steps[0].visual.branches.length, 2);
  assert.deepEqual(lessons[1].steps[0].visual.tickLabels, ["0", "1", "3"]);
  assert.deepEqual(lessons[2].steps[0].visual.breakpoints, ["−1", "2"]);
  assert.deepEqual(lessons[2].steps[0].visual.intersections, ["−9/2", "11/2"]);
  assert.match(JSON.stringify(lessons[2].problem.keyPoints), /分类讨论法.*分段函数.*折线/);

  const runtime = fs.readFileSync(
    path.join(repoRoot, "site/assets/js/lesson-page-runtime.js"),
    "utf8",
  );
  assert.match(runtime, /absolute-inequality-visual/);
  assert.match(runtime, /lesson-absolute-direct-graph/);
  assert.match(runtime, /lesson-absolute-classification-graph/);
  assert.match(runtime, /lesson-absolute-piecewise-graph/);
});

test("all inequality practice exercises carry a reasoning-specific visualization", () => {
  const lessons = Array.from({ length: 13 }, (_, index) => (
    readLesson(`inequality-practice-q${String(index + 1).padStart(2, "0")}`)
  ));
  const kinds = lessons.map((lesson) => lesson.steps.map((step) => step.visual?.kind));
  assert.deepEqual(kinds.slice(0, 6), [
    ["option-counterexample-review"],
    ["option-counterexample-review"],
    ["number-line-reasoning"],
    ["quadratic-symmetric-integer-window"],
    ["difference-factor-sign"],
    ["positive-interval-product-chain"],
  ]);
  assert.ok(kinds.slice(6, 11).every((stepKinds) => stepKinds[0] === "rational-threading-graph"));
  assert.deepEqual(kinds[11], ["absolute-direct-rule-map", "absolute-direct-rule-map"]);
  assert.deepEqual(kinds[12], ["absolute-case-analysis", "absolute-case-analysis"]);

  const optionOne = lessons[0].steps[0].visual;
  assert.equal(optionOne.rows.length, 4);
  assert.match(optionOne.rows[0].calculation, /0\^2=0<1/);
  assert.equal(optionOne.rows.filter((row) => row.correct).length, 1);

  const implicationCheck = lessons[2].steps[0].visual.implicationCheck;
  assert.equal(implicationCheck.directions.length, 2);
  assert.deepEqual(
    implicationCheck.directions.map(({ from, to, holds }) => [from, to, holds]),
    [["P", "Q", false], ["Q", "P", true]],
  );
  assert.match(implicationCheck.conclusion, /必要而不充分/);

  const symmetricWindow = lessons[3].steps[0].visual;
  assert.deepEqual(symmetricWindow.included, ["2", "3", "4"]);
  assert.deepEqual(symmetricWindow.excluded, ["1", "5"]);
  assert.deepEqual(symmetricWindow.checks.map(({ condition, result }) => [condition, result]), [
    ["\\(f(2)\\le0\\)", "\\(a\\le8\\)"],
    ["\\(f(1)>0\\)", "\\(a>5\\)"],
  ]);
  assert.match(symmetricWindow.integerValues, /6,7,8/);

  const intervalProduct = lessons[5].steps[0].visual;
  assert.equal(intervalProduct.normalize.result, "\\(1<-a<2\\)");
  assert.deepEqual(intervalProduct.multiply.rows, ["\\(1<-a<2\\)", "\\(1<b<3\\)"]);
  assert.equal(intervalProduct.multiply.result, "\\(1<-ab<6\\)");
  assert.equal(intervalProduct.restore.result, "\\(-6<ab<-1\\)");

  const rationalThreePoint = lessons[9].steps[0].visual;
  assert.equal(rationalThreePoint.roots.length, 3);
  assert.deepEqual(rationalThreePoint.roots.map((root) => root.kind), ["denominator", "numerator", "numerator"]);
  assert.deepEqual(rationalThreePoint.signs, ["-", "+", "-", "+"]);

  const absoluteDirectSingle = lessons[11].steps[0].visual;
  assert.equal(absoluteDirectSingle.mode, "single");
  assert.equal(absoluteDirectSingle.rules.length, 1);
  assert.deepEqual(absoluteDirectSingle.rules[0].mappings, ["\\(u←5x-2\\)", "\\(a←8\\)"]);
  assert.match(absoluteDirectSingle.rules[0].solved, /x\\le-\\frac\{6\}\{5\}/);

  const absoluteDirectIntersection = lessons[11].steps[1].visual;
  assert.equal(absoluteDirectIntersection.mode, "intersection");
  assert.equal(absoluteDirectIntersection.rules.length, 2);
  assert.deepEqual(absoluteDirectIntersection.rules.map((rule) => rule.name), ["大于取两边", "小于取中间"]);
  assert.match(absoluteDirectIntersection.intersection.result, /\[-2,0\].*\[4,6\]/);
  assert.doesNotMatch(JSON.stringify(absoluteDirectIntersection), /\\\\begin\{cases\}|\\\\bigl|\\\\bigr/);
  const absoluteCases = lessons[12].steps.map((step) => step.visual);
  assert.deepEqual(absoluteCases.map((visual) => visual.cases.length), [3, 3]);
  assert.match(absoluteCases[0].merge.result, /-\\frac\{3\}\{2\}.*\\frac\{3\}\{2\}/);
  assert.match(absoluteCases[1].merge.result, /\\frac\{1\}\{2\}.*\\infty/);
  const graphIntersections = (graph) => graph.pieces.flatMap((piece) => {
    if (Math.abs(piece.slope) < 1e-9) return [];
    const value = (graph.threshold.value - piece.intercept) / piece.slope;
    return value >= piece.from - 1e-9 && value <= piece.to + 1e-9 ? [value] : [];
  }).filter((value, index, values) => values.findIndex((candidate) => Math.abs(candidate - value) < 1e-9) === index);
  assert.deepEqual(graphIntersections(absoluteCases[0].graph), [-1.5, 1.5]);
  assert.deepEqual(graphIntersections(absoluteCases[1].graph), [0.5]);
  for (const visual of absoluteCases) {
    visual.graph.pieces.slice(0, -1).forEach((piece, index) => {
      const next = visual.graph.pieces[index + 1];
      assert.equal(piece.to, next.from);
      assert.equal(piece.slope * piece.to + piece.intercept, next.slope * next.from + next.intercept);
    });
  }
  assert.doesNotMatch(JSON.stringify(lessons), /\\\\frac(?!\{)/);
  assert.doesNotMatch(JSON.stringify(lessons), /\\\\times/);

  const runtime = fs.readFileSync(
    path.join(repoRoot, "site/assets/js/lesson-page-runtime.js"),
    "utf8",
  );
  for (const kind of [
    "option-counterexample-review",
    "number-line-reasoning",
    "quadratic-symmetric-integer-window",
    "difference-factor-sign",
    "positive-interval-product-chain",
    "absolute-direct-rule-map",
    "absolute-case-analysis",
  ]) {
    assert.match(runtime, new RegExp(kind));
  }
  assert.match(runtime, /lesson-implication-check/);
  assert.match(runtime, /lesson-implication-map/);
  assert.match(runtime, /lesson-implication-curve/);
  assert.match(runtime, /lesson-implication-mark/);
  assert.match(runtime, /lesson-implication-direction/);
  assert.match(runtime, /lesson-step-absolute-direct-map/);
  assert.match(runtime, /lesson-absolute-direct-rule-card/);
  assert.match(runtime, /lesson-absolute-direct-intersection/);
  assert.match(runtime, /lesson-step-absolute-case-analysis/);
  assert.match(runtime, /lesson-absolute-case-table/);
  assert.match(runtime, /lesson-absolute-case-graph/);
  assert.match(runtime, /thresholdIntersections/);
  assert.match(runtime, /\["\\\\leftarrow", "←"\]/);
  assert.match(runtime, /index === 0 \? "M142 132 C220 38 420 38 498 132" : "M498 148 C420 242 220 242 142 148"/);
  assert.doesNotMatch(runtime, /lesson-implication-directions/);
});
