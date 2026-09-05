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

test("third basic inequality exercise separates structure observation, AM-GM, and equality checking", () => {
  const lesson = readLesson("inequality-basic-q03");
  assert.equal(lesson.problem.keyPoints.lead, "");
  assert.deepEqual(
    lesson.steps.map((step) => [step.id, step.title]),
    [
      ["s1", "观察结构"],
      ["s2", "应用基本不等式"],
      ["s3", "验证取等"],
    ],
  );

  const visual = lesson.steps[0].visual;
  assert.equal(lesson.steps[0].section, "配齐次式");
  assert.equal(visual.kind, "basic-inequality-structure-scan");
  assert.match(visual.condition.expression, /\\frac\{1\}\{x\}\+\\frac\{1\}\{y\}=1/);
  assert.match(visual.target.expression, /x\+4y/);
  assert.match(visual.organization.steps.join(""), /x\+4y.*\\frac\{1\}\{x\}.*5\+\\frac\{x\}\{y\}\+\\frac\{4y\}\{x\}/);
  assert.equal(visual.pattern.condition.tag, "定积 4");
  assert.equal(visual.pattern.target.tag, "求最小值");
  assert.equal(visual.reading, "定积求和");

  const mapping = lesson.steps[1].visual;
  assert.equal(mapping.kind, "basic-inequality-mapping");
  assert.equal(mapping.methodTag, "配齐次式｜定积求和");
  assert.deepEqual(
    mapping.mappings.map((item) => [item.shape, item.value]),
    [["square", "\\(\\frac{x}{y}\\)"], ["circle", "\\(\\frac{4y}{x}\\)"]],
  );
  assert.match(mapping.fixedCondition, /=4/);
  assert.match(mapping.conclusion, /x\+4y\\ge9/);

  const equality = lesson.steps[2].visual;
  assert.equal(equality.kind, "basic-inequality-equality-check");
  assert.match(equality.solved, /x=3/);
  assert.match(equality.verification, /x\+4y=9/);

  const runtime = fs.readFileSync(
    path.join(repoRoot, "site/assets/js/lesson-page-runtime.js"),
    "utf8",
  );
  assert.match(runtime, /lesson-step-basic-structure-scan/);
  assert.match(runtime, /lesson-step-basic-inequality-map/);
  assert.match(runtime, /lesson-step-basic-equality-check/);
});

test("fourth basic inequality exercise constructs a fixed product from the fixed sum", () => {
  const lesson = readLesson("inequality-basic-q04");
  const visual = lesson.steps[0].visual;
  assert.equal(lesson.steps[0].section, "配齐次式");
  assert.equal(visual.methodTag, "配齐次式｜负一次 × 正一次");
  assert.match(lesson.problem.keyPoints.lead, /负一次式.*正一次式.*0 次齐次式/);
  assert.equal(visual.kind, "fixed-product-construction-flow");
  assert.equal(visual.variant, "homogeneous-reduction");
  assert.match(visual.initialCheck.product, /12.*ab/);
  assert.equal(visual.clue.condition, "\\(a+3b=2\\)");
  assert.deepEqual(
    [visual.degreeBalance.target.degree, visual.degreeBalance.condition.degree, visual.degreeBalance.result.degree],
    ["−1", "+1", "0"],
  );
  assert.equal(visual.construction.kind, "homogeneous");
  assert.equal(visual.construction.cells, undefined);
  assert.doesNotMatch(visual.construction.identity, /2E/);
  assert.match(visual.construction.identity, /=2\(/);
  assert.match(visual.construction.expanded, /=15\+/);
  assert.match(visual.fixedPair.product, /=36/);
  assert.deepEqual(
    visual.application.mappings.map((mapping) => [mapping.shape, mapping.value]),
    [["square", "\\(\\frac{9b}{a}\\)"], ["circle", "\\(\\frac{4a}{b}\\)"]],
  );
  assert.match(visual.application.conclusion, /27.*2/);
  assert.match(visual.equality.result, /a=\\frac\{2\}\{3\}/);
});

test("new homogeneous exercises distinguish whole-target multiplication from low-degree completion", () => {
  const wholeTarget = readLesson("inequality-basic-q14");
  const wholeVisual = wholeTarget.steps[0].visual;
  assert.equal(wholeTarget.steps[0].section, "配齐次式");
  assert.equal(wholeVisual.variant, "homogeneous-reduction");
  assert.deepEqual(
    [wholeVisual.degreeBalance.target.degree, wholeVisual.degreeBalance.condition.degree, wholeVisual.degreeBalance.result.degree],
    ["−1", "+1", "0"],
  );
  assert.match(wholeVisual.initialCheck.product, /2.*ab/);
  assert.match(wholeVisual.construction.identity, /a\+b/);
  assert.deepEqual(
    wholeVisual.construction.positiveTerms.map((item) => [item.shape, item.value]),
    [["square", "\\(\\frac{a}{b}\\)"], ["circle", "\\(\\frac{2b}{a}\\)"]],
  );
  assert.match(wholeVisual.application.conclusion, /3\+2\\sqrt2/);
  assert.match(wholeVisual.equality.result, /2-\\sqrt2/);

  const completedTerm = readLesson("inequality-basic-q15");
  const completedVisual = completedTerm.steps[0].visual;
  assert.equal(completedTerm.steps[0].section, "配齐次式");
  assert.equal(completedVisual.variant, "homogeneous-reduction");
  assert.deepEqual(completedVisual.degreeBalance.connectors, ["→", "→"]);
  assert.equal(completedVisual.degreeBalance.target.degreeText, "二次项 ＋ 一次项");
  assert.match(completedVisual.construction.identity, /2b=b\(a\+b\)=ab\+b\^2/);
  assert.match(completedVisual.construction.identityNote, /不是把整个目标乘条件/);
  assert.match(completedVisual.construction.expanded, /=1\+\\frac\{a\}\{b\}\+\\frac\{b\}\{a\}/);
  assert.match(completedVisual.fixedPair.product, /=1/);
  assert.match(completedVisual.application.conclusion, /3/);
  assert.match(completedVisual.equality.result, /a=b=1/);

  const bracketCompletion = readLesson("inequality-basic-q16");
  const bracketVisual = bracketCompletion.steps[0].visual;
  assert.equal(bracketCompletion.steps[0].section, "配齐次式");
  assert.equal(bracketVisual.variant, "homogeneous-reduction");
  assert.equal(bracketVisual.methodTag, "配齐次式｜局部配齐");
  assert.equal(bracketVisual.initialCheck.status, "viable");
  assert.equal(bracketVisual.initialCheck.label, "02 另一条可行路线");
  assert.equal(bracketVisual.initialCheck.operator, "=");
  assert.match(bracketVisual.initialCheck.terms.join(""), /\\frac\{1\}\{x\}\+\\frac\{1\}\{y\}\+\\frac\{1\}\{xy\}.*1\+\\frac\{2\}\{xy\}/);
  assert.match(bracketVisual.initialCheck.product, /xy\\le\\frac\{1\}\{4\}.*\\frac\{1\}\{x\}\+1.*\\ge9/);
  assert.match(bracketVisual.initialCheck.verdict, /直接展开.*取倒数传界/);
  assert.equal(bracketVisual.degreeBalance.target.degree, "混合");
  assert.equal(bracketVisual.degreeBalance.result.degree, "0");
  assert.match(bracketVisual.construction.identity, /2x\+y.*x\+2y/);
  assert.match(bracketVisual.construction.expanded, /5\+\\frac\{2x\}\{y\}\+\\frac\{2y\}\{x\}/);
  assert.match(bracketVisual.fixedPair.product, /=4/);
  assert.match(bracketVisual.application.conclusion, /9/);
  assert.match(bracketVisual.equality.result, /\\frac\{1\}\{2\}/);
});

test("seventeenth basic inequality exercise closes the symmetric range in both directions", () => {
  const lesson = readLesson("inequality-basic-q17");
  const visual = lesson.steps[0].visual;
  assert.equal(lesson.steps[0].section, "找对称结构");
  assert.equal(lesson.steps[0].title, "用和与积替换变量，再用基本不等式消元（消去和或积）");
  assert.equal(lesson.problem.source, "2022 新高考Ⅱ卷");
  assert.equal(visual.kind, "symmetric-reduction-flow");
  assert.equal(visual.title, "对称校验后，用 \\(x+y\\)、\\(xy\\) 替换原有变量");
  assert.equal(visual.methodTag, "找对称结构｜基本不等式消元");
  assert.deepEqual(
    visual.symmetryChecks.map((item) => [item.label, item.verdict]),
    [["目标表达式", "交换后不变"], ["条件表达式", "交换后不变"]],
  );
  assert.deepEqual(visual.substitution.definitions, ["\\(s=x+y\\)", "\\(p=xy\\)"]);
  assert.match(visual.substitution.condition, /s\^2-2p-p=1/);
  assert.equal(visual.elimination.relation, "\\(s^2\\ge4p\\)");
  assert.match(visual.elimination.basis, /基本不等式的变式.*s\^2-4p=\(x-y\)\^2.*\\ge0/);
  assert.match(visual.elimination.substitutionLabel, /上一步求出的.*p=\\frac\{s\^2-1\}\{3\}/);
  assert.equal(visual.elimination.expanded, "\\(3s^2\\ge4s^2-4\\)");
  assert.equal(visual.elimination.range, "\\(-2\\le s\\le2\\)");
  assert.equal(visual.closure.equalityLabel, "基本不等式取等");
  assert.match(visual.closure.equalityCondition, /s\^2=4p\\iff\(x-y\)\^2=0\\iff x=y/);
  assert.deepEqual(
    visual.closure.endpoints.map((item) => item.witness),
    ["\\(x=y=1\\)", "\\(x=y=-1\\)"],
  );
  assert.deepEqual(
    visual.closure.endpoints.map((item) => item.boundaryCondition),
    ["\\(x+y=2，x=y\\)", "\\(x+y=-2，x=y\\)"],
  );
  assert.deepEqual(lesson.steps[0].derive[0], ["取值范围", "[-2,2]"]);
  assert.ok(lesson.steps[0].reasoning.every((line) => /\\\(/.test(line.text)), "q17 reasoning should retain mathematical derivations");
  assert.ok(lesson.steps[0].reasoning.some((line) => !line.text.startsWith("\\(")), "q17 reasoning should include short natural-language guidance");
  assert.match(lesson.steps[0].reasoning.map((line) => line.text).join(" "), /因为.*所以.*基本不等式取等.*两个边界都能取到/);
  assert.doesNotMatch(JSON.stringify(lesson.steps[0]), /t\^2|\\\\Delta|判别式|d=x-y|\\\\sqrt/);
  assert.doesNotMatch(JSON.stringify(lesson.steps[0].reasoning), /\\\\(?:forall|leftrightarrow)/);

  const runtime = fs.readFileSync(
    path.join(repoRoot, "site/assets/js/lesson-page-runtime.js"),
    "utf8",
  );
  assert.match(runtime, /lesson-step-symmetric-reduction/);
  assert.match(runtime, /symmetric-reduction-relation/);
  assert.match(runtime, /symmetric-reduction-substitute/);
  assert.match(runtime, /symmetric-reduction-equality-condition/);
  assert.match(runtime, /renderFormulaText\(closure\.question/);
});

test("eighteenth basic inequality variant normalizes coefficients before checking symmetry", () => {
  const lesson = readLesson("inequality-basic-q18");
  const step = lesson.steps[0];
  const visual = step.visual;
  assert.equal(step.section, "找对称结构");
  assert.equal(step.title, "先观察并变形，再校验对称结构");
  assert.equal(visual.kind, "symmetric-reduction-flow");
  assert.equal(visual.variant, "normalize-before-symmetry");
  assert.match(visual.preparation.observation, /目标中的.*\\frac\{x\}\{2\}.*缩放/);
  assert.match(visual.preparation.substitution, /u=\\frac\{x\}\{2\}\\iff x=2u/);
  assert.deepEqual(visual.preparation.conditionFlow, [
    "\\(x^2+4y^2-2xy=1\\)",
    "\\(4u^2+4y^2-4uy=1\\)",
    "\\(u^2+y^2-uy=\\frac{1}{4}\\)",
  ]);
  assert.deepEqual(
    visual.symmetryChecks.map((item) => [item.original, item.swapped]),
    [["\\(u+y\\)", "\\(y+u\\)"], ["\\(u^2+y^2-uy\\)", "\\(y^2+u^2-yu\\)"]],
  );
  assert.deepEqual(visual.substitution.definitions, ["\\(s=u+y\\)", "\\(p=uy\\)"]);
  assert.equal(visual.substitution.solved, "\\(p=\\frac{4s^2-1}{12}\\)");
  assert.equal(visual.elimination.range, "\\(-1\\le s\\le1\\)");
  assert.match(visual.closure.equalityCondition, /u-y.*u=y/);
  assert.deepEqual(
    visual.closure.endpoints.map((item) => item.witness),
    ["\\(u=y=\\frac{1}{2}\\Rightarrow x=1\\)", "\\(u=y=-\\frac{1}{2}\\Rightarrow x=-1\\)"],
  );
  assert.deepEqual(step.derive[0], ["取值范围", "[-1,1]"]);
  assert.match(step.reasoning.map((line) => line.text).join(" "), /不能直接用和与积.*令.*u=.*此时成为对称结构/);
});

test("nineteenth basic inequality variant groups repeated expressions before checking symmetry", () => {
  const lesson = readLesson("inequality-basic-q19");
  const step = lesson.steps[0];
  const visual = step.visual;
  assert.equal(step.section, "找对称结构");
  assert.equal(step.title, "先观察整体并变形，再校验对称结构");
  assert.equal(visual.variant, "normalize-before-symmetry");
  assert.equal(visual.symmetryVariables, "u、v");
  assert.match(visual.preparation.observation, /两个整体.*a.*2b/);
  assert.equal(visual.preparation.substitution, "\\(u=a，v=2b\\)");
  assert.deepEqual(visual.preparation.conditionFlow, ["\\(2ab=a+2b+3\\)", "\\(uv=u+v+3\\)"]);
  assert.deepEqual(
    visual.symmetryChecks.map((item) => [item.original, item.swapped]),
    [["\\(u+v\\)", "\\(v+u\\)"], ["\\(uv=u+v+3\\)", "\\(vu=v+u+3\\)"]],
  );
  assert.deepEqual(visual.substitution.definitions, ["\\(s=u+v\\)", "\\(p=uv\\)"]);
  assert.equal(visual.substitution.solved, "\\(p=s+3\\)");
  assert.equal(visual.elimination.simplified, "\\((s-6)(s+2)\\ge0\\)");
  assert.equal(visual.elimination.range, "\\(s\\ge6\\)");
  assert.equal(visual.closure.label, "验取等");
  assert.equal(visual.closure.endpoints.length, 1);
  assert.match(visual.closure.endpoints[0].witness, /a=3，b=\\frac\{3\}\{2\}/);
  assert.deepEqual(step.derive[0], ["最小值", "6"]);
  assert.match(step.reasoning.map((line) => line.text).join(" "), /两个整体.*此时成为对称结构.*最小值为.*6/);
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

test("twenty-first basic inequality variant reduces a symmetric quartic through p=ab", () => {
  const lesson = readLesson("inequality-basic-q21");
  const step = lesson.steps[0];
  const visual = step.visual;
  assert.equal(step.section, "找对称结构");
  assert.equal(visual.kind, "symmetric-objective-reduction");
  assert.equal(visual.methodTag, "找对称结构｜对称配对降维");
  assert.match(visual.symmetryCheck.original, /a\^4\+b\^4-8ab/);
  assert.match(visual.symmetryCheck.swapped, /b\^4\+a\^4-8ba/);
  assert.deepEqual(visual.pairing.terms, ["\\(a^4\\)", "\\(b^4\\)"]);
  assert.match(visual.pairing.inequality, /a\^4\+b\^4\\ge2\\sqrt\{a\^4b\^4\}=2a\^2b\^2/);
  assert.equal(visual.pairing.productVariable, "\\(p=ab>0\\)");
  assert.equal(visual.reduction.lowerBound, "\\(\\ge2p^2-8p\\)");
  assert.equal(visual.reduction.completion, "\\(=2(p-2)^2-8\\)");
  assert.match(visual.equality.pairingCondition, /a\^4=b\^4.*a=b/);
  assert.equal(visual.equality.completionCondition, "\\(p=ab=2\\)");
  assert.equal(visual.equality.result, "\\(a=b=\\sqrt{2}\\)");
  assert.deepEqual(step.derive[0], ["最小值", "-8"]);
  assert.match(step.reasoning.map((line) => line.text).join(" "), /具有对称结构.*p=ab>0.*配方取等.*最小值为.*-8/);

  const runtime = fs.readFileSync(path.join(repoRoot, "site/assets/js/lesson-page-runtime.js"), "utf8");
  assert.match(runtime, /lesson-step-symmetric-objective/);
  assert.match(runtime, /symmetric-objective-pairing/);
  assert.match(runtime, /symmetric-objective-equality/);
  assert.match(runtime, /symmetric-objective-term-plus.*相加/);
  assert.match(runtime, /symmetric-objective-logical-and.*且/);
});

test("twenty-second through twenty-sixth basic inequality variants use substitution as the entry method", () => {
  const first = readLesson("inequality-basic-q22");
  const second = readLesson("inequality-basic-q23");
  const third = readLesson("inequality-basic-q24");
  const fourth = readLesson("inequality-basic-q25");
  const fifth = readLesson("inequality-basic-q26");

  assert.deepEqual([first.steps[0].section, second.steps[0].section, third.steps[0].section, fourth.steps[0].section, fifth.steps[0].section], ["换元法", "换元法", "换元法", "换元法", "换元法"]);
  assert.deepEqual(
    [first.steps[0].visual.methodTag, second.steps[0].visual.methodTag, third.steps[0].visual.methodTag, fourth.steps[0].visual.methodTag, fifth.steps[0].visual.methodTag],
    ["换元法｜复杂分母换元", "换元法｜复杂分母换元", "换元法｜复杂分母换元", "换元法｜复杂分母换元", "换元法｜根号整体换元"],
  );
  assert.deepEqual(
    [first.steps[0].visual.kind, second.steps[0].visual.kind, third.steps[0].visual.kind, fourth.steps[0].visual.kind, fifth.steps[0].visual.kind],
    ["substitution-homogeneous-lifecycle", "substitution-homogeneous-lifecycle", "substitution-homogeneous-lifecycle", "substitution-basic-inequality-lifecycle", "substitution-basic-inequality-lifecycle"],
  );

  const firstVisual = first.steps[0].visual;
  assert.deepEqual(
    firstVisual.substitution.mappings.map((item) => [item.source, item.target, item.reverse]),
    [
      ["\\(x+1\\)", "\\(u=x+1>0\\)", "\\(x=u-1\\)"],
      ["\\(y+2\\)", "\\(v=y+2>0\\)", "\\(y=v-2\\)"],
    ],
  );
  assert.equal(firstVisual.substitution.condition, "\\(u+v=5\\)");
  assert.equal(firstVisual.substitution.target, "\\(\\frac{1}{u}+\\frac{1}{v}\\)");
  assert.equal(firstVisual.homogeneous.methodTag, "发现结构｜可以配齐次式");
  assert.deepEqual(firstVisual.homogeneous.degrees.map((item) => item.degree), ["+1", "−1", "0"]);
  assert.equal(firstVisual.homogeneous.product, "\\(\\frac{u}{v}\\cdot\\frac{v}{u}=1\\)");
  assert.match(firstVisual.homogeneous.identity, /5\\left.*u\+v.*\\frac\{1\}\{u\}.*\\frac\{1\}\{v\}.*\\frac\{u\}\{v\}.*\\frac\{v\}\{u\}/);
  assert.equal(firstVisual.homogeneous.bound, "\\(\\frac{1}{u}+\\frac{1}{v}\\ge\\frac{4}{5}\\)");
  assert.equal(firstVisual.restoration.transformedEquality, "\\(u=v\\)");
  assert.match(firstVisual.restoration.result, /x=\\frac\{3\}\{2\}.*y=\\frac\{1\}\{2\}/);
  assert.deepEqual(first.steps[0].derive[0], ["最小值", "4/5"]);

  const secondVisual = second.steps[0].visual;
  assert.deepEqual(
    secondVisual.substitution.mappings.map((item) => [item.source, item.target, item.reverse]),
    [
      ["\\(x+1\\)", "\\(u=x+1>0\\)", "\\(x=u-1\\)"],
      ["\\(2y+1\\)", "\\(v=2y+1>0\\)", "\\(y=\\frac{v-1}{2}\\)"],
    ],
  );
  assert.equal(secondVisual.substitution.condition, "\\(2u+v=7\\)");
  assert.equal(secondVisual.homogeneous.product, "\\(\\frac{2u}{v}\\cdot\\frac{v}{u}=2\\)");
  assert.match(secondVisual.homogeneous.identity, /7\\left.*2u\+v.*3\+\\frac\{2u\}\{v\}.*\\frac\{v\}\{u\}/);
  assert.equal(secondVisual.homogeneous.bound, "\\(\\frac{1}{u}+\\frac{1}{v}\\ge\\frac{3+2\\sqrt2}{7}\\)");
  assert.match(secondVisual.homogeneous.equality, /v=\\sqrt2u/);
  assert.match(secondVisual.restoration.reverse, /x=u-1.*y=\\frac\{v-1\}\{2\}/);
  assert.match(secondVisual.restoration.result, /x=6-\\frac\{7\\sqrt2\}\{2\}.*y=\\frac\{7\\sqrt2-8\}\{2\}/);
  assert.deepEqual(second.steps[0].derive[0], ["最小值", "(3+2√2)/7"]);

  const thirdVisual = third.steps[0].visual;
  assert.deepEqual(
    thirdVisual.substitution.mappings.map((item) => [item.source, item.target, item.reverse]),
    [
      ["\\(a+1\\)", "\\(u=a+1>1\\)", "\\(a=u-1\\)"],
      ["\\(b+1\\)", "\\(v=b+1>1\\)", "\\(b=v-1\\)"],
    ],
  );
  assert.equal(thirdVisual.substitution.condition, "\\(u+v=3\\)");
  assert.equal(thirdVisual.substitution.rearrangement.before, "\\(\\frac{(u-1)^2}{u}+\\frac{(v-1)^2}{v}\\)");
  assert.deepEqual(thirdVisual.substitution.rearrangement.identities, [
    "\\(\\frac{(u-1)^2}{u}=u-2+\\frac{1}{u}\\)",
    "\\(\\frac{(v-1)^2}{v}=v-2+\\frac{1}{v}\\)",
  ]);
  assert.equal(thirdVisual.substitution.rearrangement.result, "\\(-1+\\frac{1}{u}+\\frac{1}{v}\\)");
  assert.equal(thirdVisual.substitution.target, "\\(-1+\\frac{1}{u}+\\frac{1}{v}\\)");
  assert.equal(thirdVisual.homogeneous.product, "\\(\\frac{u}{v}\\cdot\\frac{v}{u}=1\\)");
  assert.equal(thirdVisual.homogeneous.bound, "\\(\\frac{1}{u}+\\frac{1}{v}\\ge\\frac{4}{3}\\Rightarrow -1+\\frac{1}{u}+\\frac{1}{v}\\ge\\frac{1}{3}\\)");
  assert.equal(thirdVisual.restoration.variableLabel, "a、b");
  assert.equal(thirdVisual.restoration.result, "\\(a=b=\\frac{1}{2}\\)");
  assert.deepEqual(third.steps[0].derive[0], ["最小值", "1/3"]);

  const fourthVisual = fourth.steps[0].visual;
  assert.deepEqual(
    fourthVisual.substitution.mappings.map((item) => [item.source, item.target, item.reverse]),
    [
      ["\\(a-1\\)", "\\(x=a-1>0\\)", "\\(a=x+1\\)"],
      ["\\(b-1\\)", "\\(y=b-1>0\\)", "\\(b=y+1\\)"],
    ],
  );
  assert.deepEqual(fourthVisual.substitution.rearrangement.conditionFlow, [
    "\\(\\frac{1}{x+1}+\\frac{1}{y+1}=1\\)",
    "\\(x+y+2=xy+x+y+1\\)",
    "\\(xy=1\\)",
  ]);
  assert.equal(fourthVisual.substitution.condition, "\\(xy=1\\)");
  assert.equal(fourthVisual.substitution.target, "\\(13+\\frac{4}{x}+\\frac{9}{y}\\)");
  assert.equal(fourthVisual.basicInequality.product, "\\(\\frac{4}{x}\\cdot\\frac{9}{y}=\\frac{36}{xy}=36\\)");
  assert.equal(fourthVisual.basicInequality.bound, "\\(13+\\frac{4}{x}+\\frac{9}{y}\\ge25\\)");
  assert.equal(fourthVisual.restoration.result, "\\(a=\\frac{5}{3}，b=\\frac{5}{2}\\)");
  assert.deepEqual(fourth.steps[0].derive[0], ["最小值", "25"]);
  assert.match(fourth.steps[0].visual.caption, /三步.*换元.*基本不等式.*还原/);
  assert.doesNotMatch(JSON.stringify(fourth), /配齐次式|外层|内层|闭环|T=/);

  const fifthVisual = fifth.steps[0].visual;
  assert.deepEqual(
    fifthVisual.substitution.mappings.map((item) => [item.source, item.target, item.reverse]),
    [["\\(\\sqrt{2+y^2}\\)", "\\(t=\\sqrt{2+y^2}>\\sqrt2\\)", "\\(t^2=2+y^2\\)"]],
  );
  assert.equal(fifthVisual.substitution.mappingActionLabel, "把根号整体换成新变量");
  assert.deepEqual(fifthVisual.substitution.rearrangement.conditionFlow, [
    "\\(x^2+\\frac{t^2-2}{16}=1\\)",
    "\\(16x^2+t^2=18\\)",
    "\\((4x)^2+t^2=18\\)",
  ]);
  assert.equal(fifthVisual.substitution.target, "\\(xt\\)");
  assert.equal(fifthVisual.basicInequality.relationLabel, "根积对应目标");
  assert.equal(fifthVisual.basicInequality.inequality, "\\((4x)^2+t^2\\ge2\\cdot4x\\cdot t=8xt\\)");
  assert.equal(fifthVisual.basicInequality.bound, "\\(18\\ge8xt\\Rightarrow xt\\le\\frac{9}{4}\\)");
  assert.equal(fifthVisual.restoration.result, "\\(x=\\frac{3}{4}，y=\\sqrt7\\)");
  assert.deepEqual(fifth.steps[0].derive[0], ["最大值", "9/4"]);
  assert.match(fifth.steps[0].visual.caption, /三步.*根号整体换元.*基本不等式.*还原/);
  assert.doesNotMatch(JSON.stringify(fifth), /配齐次式|外层|内层|闭环|T=/);

  for (const lesson of [first, second, third]) {
    const reasoning = lesson.steps[0].reasoning.map((line) => line.text).join(" ");
    assert.match(reasoning, /令.*u=.*v=.*同步改写|等价于/);
    assert.match(reasoning, /负一次式.*一次式.*0 次齐次式/);
    assert.match(lesson.steps[0].visual.caption, /三步.*换元.*配齐次式.*还原/);
    assert.doesNotMatch(JSON.stringify(lesson), /T=|5T|7T|外层|内层|闭环/);
  }

  const runtime = fs.readFileSync(path.join(repoRoot, "site/assets/js/lesson-page-runtime.js"), "utf8");
  const styles = fs.readFileSync(path.join(repoRoot, "site/assets/css/interactive-geometry-page.css"), "utf8");
  assert.match(runtime, /lesson-step-substitution-lifecycle/);
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
  assert.match(styles, /\.substitution-lifecycle-inner/);
  assert.match(styles, /\.substitution-lifecycle-rearrangement/);
  assert.match(styles, /\.substitution-lifecycle-condition-flow/);
  assert.match(styles, /\.substitution-lifecycle-inner\.is-basic-inequality/);
  assert.match(styles, /@media \(max-width: 720px\)[\s\S]*\.substitution-lifecycle-mappings,[\s\S]*\.substitution-lifecycle-restore-chain/);
});

test("twenty-seventh basic inequality variant uses conditional elimination before AM-GM", () => {
  const lesson = readLesson("inequality-basic-q27");
  const step = lesson.steps[0];
  const visual = step.visual;

  assert.equal(step.section, "条件消元法");
  assert.equal(visual.kind, "elimination-basic-inequality-lifecycle");
  assert.equal(visual.methodTag, "条件消元法｜利用条件消去一个变量");
  assert.deepEqual(visual.elimination.conditionFlow, [
    "\\(\\frac{1}{x+1}+\\frac{1}{x+2y}=1\\)",
    "\\((x+2y)+(x+1)=(x+1)(x+2y)\\)",
    "\\(x(x+2y-1)=1\\)",
  ]);
  assert.deepEqual(visual.elimination.isolateFlow, [
    "\\(x+2y-1=\\frac{1}{x}\\)",
    "\\(y=\\frac{1}{2}(1+\\frac{1}{x}-x)\\)",
  ]);
  assert.equal(visual.elimination.target, "\\(\\frac{1}{2}(3x+\\frac{1}{x}+1)\\)");
  assert.equal(visual.basicInequality.product, "\\(3x\\cdot\\frac{1}{x}=3\\)");
  assert.equal(visual.basicInequality.bound, "\\(2x+y\\ge\\frac{1}{2}(2\\sqrt{3}+1)=\\sqrt{3}+\\frac{1}{2}\\)");
  assert.equal(visual.restoration.result, "\\(x=\\frac{1}{\\sqrt{3}}，y=\\frac{1}{2}+\\frac{1}{\\sqrt{3}}\\)");
  assert.deepEqual(step.derive[0], ["最小值", "√3+1/2"]);
  assert.match(visual.caption, /整理条件.*表示.*变量.*代入目标.*一元目标.*基本不等式.*回代/);
  assert.doesNotMatch(JSON.stringify(lesson), /换元法|配齐次式|外层|内层|闭环|T=/);

  const runtime = fs.readFileSync(path.join(repoRoot, "site/assets/js/lesson-page-runtime.js"), "utf8");
  const styles = fs.readFileSync(path.join(repoRoot, "site/assets/css/interactive-geometry-page.css"), "utf8");
  assert.match(runtime, /elimination-basic-inequality-lifecycle/);
  assert.match(runtime, /01 消元.*整理条件.*表示变量.*代入目标/s);
  assert.match(runtime, /03 .*回代等号/);
  assert.match(styles, /\.elimination-lifecycle-stages/);
  assert.match(styles, /@media \(max-width: 720px\)[\s\S]*\.elimination-lifecycle-stages/);
});

test("twenty-ninth basic inequality variant eliminates b before minimizing the reciprocal", () => {
  const lesson = readLesson("inequality-basic-q29");
  const step = lesson.steps[0];
  const visual = step.visual;

  assert.equal(step.section, "条件消元法");
  assert.equal(visual.kind, "elimination-basic-inequality-lifecycle");
  assert.equal(visual.methodTag, "条件消元法｜用定和消去一个变量");
  assert.deepEqual(visual.elimination.conditionFlow, [
    "\\(a+b=1\\)",
    "\\(b=1-a\\)",
    "\\(0<a<1\\)",
  ]);
  assert.deepEqual(visual.elimination.isolateFlow, [
    "\\(a^2+b=a^2-a+1\\)",
    "\\(a+b^2=a^2-a+1\\)",
  ]);
  assert.deepEqual(visual.elimination.targetFlow, [
    "\\(E=\\frac{2a}{a^2+b}+\\frac{b}{a+b^2}\\)",
    "\\(E=\\frac{2a+1-a}{a^2-a+1}\\)",
    "\\(E=\\frac{a+1}{a^2-a+1}>0\\)",
  ]);
  assert.equal(visual.elimination.target, "\\(\\frac{1}{E}=(a+1)+\\frac{3}{a+1}-3\\)");
  assert.deepEqual(
    visual.basicInequality.positiveTerms.map((term) => term.value),
    ["\\(a+1\\)", "\\(\\frac{3}{a+1}\\)"],
  );
  assert.equal(visual.basicInequality.product, "\\((a+1)\\cdot\\frac{3}{a+1}=3\\)");
  assert.match(visual.basicInequality.bound, /1\}\{E\}.*2\\sqrt3-3.*E.*3\+2\\sqrt3/);
  assert.equal(visual.restoration.result, "\\(a=\\sqrt3-1，b=2-\\sqrt3\\)");
  assert.deepEqual(step.derive[0], ["最大值", "(3+2√3)/3"]);
  assert.match(visual.caption, /定和条件.*表示 b.*代入目标.*取倒数.*基本不等式.*回代/);
  assert.doesNotMatch(JSON.stringify(lesson), /换元法|配齐次式|外层|内层|闭环|T=/);
});

test("thirtieth basic inequality variant reveals each reduction only after the previous estimate", () => {
  const lesson = readLesson("inequality-basic-q30");
  const step = lesson.steps[0];
  const visual = step.visual;

  assert.equal(step.section, "多次应用基本不等式");
  assert.equal(visual.kind, "repeated-basic-inequality-flow");
  assert.equal(visual.methodTag, "多次应用基本不等式｜逐层消元");
  assert.equal(visual.count.estimatedRelations, 3);
  assert.equal(visual.count.estimatedRounds, 2);
  assert.deepEqual(visual.count.relationSources, ["基本不等式 ×2", "平方非负 ×1"]);
  assert.deepEqual(visual.preparation.flow, [
    "\\(\\frac{1}{ab}+\\frac{1}{a(a-b)}=\\frac{a-b+b}{ab(a-b)}\\)",
    "\\(\\frac{a}{ab(a-b)}=\\frac{1}{b(a-b)}\\)",
  ]);
  assert.doesNotMatch(JSON.stringify(visual.preparation), /a-5c/);
  assert.deepEqual(visual.rounds[0].terms, ["\\(b\\)", "\\(a-b\\)"]);
  assert.match(visual.rounds[0].inequality, /b\(a-b\).*\\frac\{a\^2\}\{4\}.*\\frac\{1\}\{b\(a-b\)\}.*\\frac\{4\}\{a\^2\}/);
  assert.match(visual.rounds[0].result, /2a\^2-10ac\+25c\^2\+\\frac\{4\}\{a\^2\}/);
  assert.match(visual.rounds[0].afterward.observation, /25c²−10ac.*负项.*补给它一个 a².*完全平方/);
  assert.deepEqual(visual.rounds[0].afterward.flow, [
    "\\(2a^2=a^2+a^2\\)",
    "\\(a^2-10ac+25c^2=(a-5c)^2\\ge0\\)",
  ]);
  assert.equal(visual.rounds[0].afterward.equality, "\\(a=5c\\)");
  assert.deepEqual(visual.rounds[1].terms, ["\\(a^2\\)", "\\(\\frac{4}{a^2}\\)"]);
  assert.equal(visual.rounds[1].result, "原式不小于 \\(4\\)");
  assert.deepEqual(visual.equality.conditions.map((item) => item.expression), [
    "\\(b=a-b\\)",
    "\\(a=5c\\)",
    "\\(a^2=\\frac{4}{a^2}\\)",
  ]);
  assert.equal(visual.equality.solved, "\\(a=\\sqrt{2}，b=\\frac{\\sqrt{2}}{2}，c=\\frac{\\sqrt{2}}{5}\\)");
  assert.deepEqual(step.derive[0], ["最小值", "4"]);
  assert.doesNotMatch(JSON.stringify(lesson), /2a\^2\+\\frac\{4\}\{a\^2\}\\ge/);
  assert.doesNotMatch(JSON.stringify(lesson), /E=|E\\\\ge/);

  const runtime = fs.readFileSync(path.join(repoRoot, "site/assets/js/lesson-page-runtime.js"), "utf8");
  const styles = fs.readFileSync(path.join(repoRoot, "site/assets/css/interactive-geometry-page.css"), "utf8");
  assert.match(runtime, /repeated-basic-preparation/);
  assert.match(runtime, /repeated-basic-restructure/);
  assert.match(runtime, /待补取等关系/);
  assert.match(styles, /\.repeated-basic-preparation-flow/);
  assert.match(styles, /\.repeated-basic-restructure-observation/);
});

test("thirty-first basic inequality variant separates homogenization from two AM-GM rounds", () => {
  const lesson = readLesson("inequality-basic-q31");
  const step = lesson.steps[0];
  const visual = step.visual;

  assert.equal(step.section, "多次应用基本不等式");
  assert.equal(visual.kind, "repeated-basic-inequality-flow");
  assert.equal(visual.methodTag, "多次应用基本不等式｜配齐次后逐层消元");
  assert.equal(visual.count.variableLabel, "正量");
  assert.deepEqual(visual.count.variables, ["\\(a\\)", "\\(b\\)", "\\(1+c^2\\)"]);
  assert.deepEqual(visual.count.conditions, ["\\(a+b=1\\)"]);
  assert.equal(visual.count.estimatedRelations, 2);
  assert.equal(visual.count.estimatedRounds, 2);
  assert.deepEqual(visual.preparations.map((item) => item.stageLabel), ["整理目标", "配齐次式"]);
  assert.deepEqual(visual.preparations[0].flow, [
    "\\(bc^2+b=b(1+c^2)\\)",
    "\\(abc^2+ab=ab(1+c^2)\\)",
  ]);
  assert.deepEqual(visual.preparations[1].flow, [
    "\\(a+b=1\\Rightarrow1=(a+b)^2\\)",
    "\\(\\frac{1}{ab}=\\frac{(a+b)^2}{ab}\\)",
    "\\(\\frac{3a}{b}+\\frac{1}{ab}=\\frac{4a}{b}+\\frac{b}{a}+2\\)",
  ]);
  assert.deepEqual(visual.rounds[0].terms, ["\\(\\frac{4a}{b}\\)", "\\(\\frac{b}{a}\\)"]);
  assert.equal(visual.rounds[0].result, "原式不小于 \\(\\frac{6}{1+c^2}+2c^2\\)");
  assert.equal(visual.rounds[0].afterward.equality, undefined);
  assert.match(visual.rounds[0].afterward.result, /2\(1\+c\^2\).*\\frac\{6\}\{1\+c\^2\}-2/);
  assert.deepEqual(visual.rounds[1].terms, ["\\(2(1+c^2)\\)", "\\(\\frac{6}{1+c^2}\\)"]);
  assert.equal(visual.rounds[1].result, "原式不小于 \\(4\\sqrt3-2\\)");
  assert.deepEqual(visual.equality.conditions.map((item) => item.expression), [
    "\\(b=2a\\)",
    "\\(c^2=\\sqrt3-1\\)",
  ]);
  assert.equal(visual.equality.solved, "\\(a=\\frac{1}{3}，b=\\frac{2}{3}，c=\\pm\\sqrt{\\sqrt3-1}\\)");
  assert.deepEqual(step.derive[0], ["最小值", "4√3−2"]);
  assert.doesNotMatch(JSON.stringify(lesson), /E=|E\\\\ge/);

  const runtime = fs.readFileSync(path.join(repoRoot, "site/assets/js/lesson-page-runtime.js"), "utf8");
  assert.match(runtime, /visual\.preparations/);
  assert.match(runtime, /preparation\.stageLabel/);
  assert.match(runtime, /count\.variableLabel/);
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
  assert.deepEqual(lessons.map((lesson) => lesson.steps.length), [1, 3, 3, 3, 1, 1]);
  assert.deepEqual(
    lessons.map((lesson) => lesson.steps.map((item) => item.visual?.kind)),
    [
      ["repeated-basic-inequality-flow"],
      ["basic-inequality-structure-scan", "basic-inequality-mapping", "basic-inequality-equality-check"],
      ["basic-inequality-structure-scan", "basic-inequality-mapping", "basic-inequality-equality-check"],
      ["basic-inequality-structure-scan", "basic-inequality-mapping", "basic-inequality-equality-check"],
      ["repeated-basic-inequality-flow"],
      ["basic-inequality-mapping"],
    ],
  );
  assert.match(JSON.stringify(lessons[0]), /a=b=\\\\sqrt\{2\}/);
  assert.equal(lessons[0].steps[0].visual.count.estimatedRounds, 2);
  assert.deepEqual(lessons[0].steps[0].visual.rounds.map((round) => round.terms), [
    ["\\(\\frac{1}{a}\\)", "\\(\\frac{a}{b^2}\\)"],
    ["\\(\\frac{2}{b}\\)", "\\(b\\)"],
  ]);
  assert.match(
    lessons[0].steps[0].reasoning.map((item) => item.text).join(" "),
    /\\frac\{1\}\{a\}\+\\frac\{a\}\{b\^2\}.*\\frac\{2\}\{b\}\+b.*2\\sqrt\{2\}/,
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
  assert.equal(lessons[4].steps[0].visual.count.estimatedRounds, 2);
  assert.deepEqual(lessons[4].steps[0].visual.rounds.map((round) => round.terms), [
    ["\\(a^4\\)", "\\(4b^4\\)"],
    ["\\(4ab\\)", "\\(\\frac{1}{ab}\\)"],
  ]);
  assert.match(
    lessons[4].steps[0].reasoning.map((item) => item.text).join(" "),
    /a\^4\+4b\^4.*4a\^2b\^2.*4ab\+\\frac\{1\}\{ab\}.*2\\sqrt\{4\}=4/,
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
