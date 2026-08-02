import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

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
    .filter((id) => id.startsWith("set-representation-"))
    .sort(),
];
function readLesson(id) {
  return JSON.parse(fs.readFileSync(
    path.join(repoRoot, "internal/senior-high/lesson-specs", id, "lesson-data.json"),
    "utf8",
  ));
}

test("all set text lessons validate and compile to published HTML", () => {
  for (const id of lessonIds) {
    const lesson = validateTextLesson(readLesson(id), id);
    const outputPath = path.join(repoRoot, lesson.meta.outputPath);
    assert.ok(fs.existsSync(outputPath), `${id} should have a compiled page`);
    const html = fs.readFileSync(outputPath, "utf8");
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
      + "\\(M=\\left\\{a\\middle|a\\ge\\frac98\\right\\}\\)",
  );
  assert.match(html, /x∈<span class="math-blackboard">ℝ<\/span>/);
  assert.match(html, /x<span class="math-notin"[^>]*><svg[^>]*>.*?<path[^>]*><\/svg><\/span>∅/);
  assert.match(html, /∛/);
  assert.match(html, /π≠0/);
  assert.match(html, /≤1⇔-1≤/);
  assert.match(html, /a≥/);
  assert.match(html, /class="math-blackboard"/);
  assert.doesNotMatch(html, /\\(?:mathbb|in|notin|varnothing|sqrt|pi|iff|left|right|middle)/);
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
