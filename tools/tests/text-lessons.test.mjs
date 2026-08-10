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

test("first basic inequality exercise maps problem variables into the formula template", () => {
  const lesson = readLesson("inequality-basic-q01");
  const visual = lesson.steps[0].visual;
  assert.equal(visual.kind, "basic-inequality-mapping");
  assert.deepEqual(
    visual.mappings.map((mapping) => [mapping.slot, mapping.value]),
    [["a", "m"], ["b", "n"]],
  );
  assert.match(visual.fixedCondition, /m\+n=2/);
  assert.match(visual.replaced, /\\frac\{2\}\{2\}/);
  assert.match(visual.conclusion, /mn\\le1/);
  assert.match(visual.equalityResult, /m=n=1/);
  assert.equal(visual.methodTag, "直接型｜定和求积");

  const html = fs.readFileSync(path.join(repoRoot, lesson.meta.outputPath), "utf8");
  assert.match(html, /basic-inequality-mapping/);
  const runtime = fs.readFileSync(
    path.join(repoRoot, "site/assets/js/lesson-page-runtime.js"),
    "utf8",
  );
  assert.match(runtime, /lesson-step-basic-inequality-map/);
  assert.match(runtime, /basic-map-source-grid/);
  assert.match(runtime, /basic-map-sum-target/);
});

test("second basic inequality exercise reuses the mapping component for the sum-product relation", () => {
  const lesson = readLesson("inequality-basic-q02");
  const visual = lesson.steps[0].visual;
  assert.equal(visual.kind, "basic-inequality-mapping");
  assert.deepEqual(
    visual.mappings.map((mapping) => [mapping.slot, mapping.value]),
    [["a", "x"], ["b", "y"]],
  );
  assert.match(visual.fixedCondition, /x\+y=xy/);
  assert.match(visual.replaced, /\\frac\{xy\}\{2\}/);
  assert.match(visual.substituted, /\\sqrt\{xy\}\\ge2/);
  assert.match(visual.conclusion, /xy\\ge4/);
  assert.match(visual.equalityResult, /x=y=2/);
  assert.equal(visual.methodTag, "转化型｜倒数和转和积关系");
  assert.equal(visual.stageLabel, "代入和积关系");
  assert.deepEqual(visual.conditionFlow, [
    "\\(\\frac{1}{x}+\\frac{1}{y}=1\\)",
    "\\(\\frac{x+y}{xy}=1\\)",
    "\\(x+y=xy\\)",
  ]);
});

test("third basic inequality exercise visualizes the fixed-product construction thought process", () => {
  const lesson = readLesson("inequality-basic-q03");
  const visual = lesson.steps[0].visual;
  assert.equal(visual.kind, "fixed-product-construction-flow");
  assert.equal(visual.methodTag, "构造型｜寻找固定乘积");
  assert.match(visual.initialCheck.product, /4xy/);
  assert.match(visual.clue.condition, /\\frac\{1\}\{x\}\+\\frac\{1\}\{y\}=1/);
  assert.deepEqual(
    visual.construction.cells.map((row) => row.map((cell) => cell.role)),
    [["constant", "constructed"], ["constructed", "constant"]],
  );
  assert.match(visual.construction.expanded, /=1\+.*=5\+/);
  assert.equal(visual.fixedPair.question, "观察展开后的式子，是否可以找到定积？");
  assert.match(visual.fixedPair.product, /\\frac\{x\}\{y\}.*\\frac\{4y\}\{x\}.*=4/);
  assert.equal(visual.application.template, "\\(a+b\\ge2\\sqrt{ab}\\)");
  assert.deepEqual(
    visual.application.mappings.map((mapping) => [mapping.slot, mapping.value]),
    [["\\(a\\)", "\\(\\frac{x}{y}\\)"], ["\\(b\\)", "\\(\\frac{4y}{x}\\)"]],
  );
  assert.match(visual.application.conclusion, /9/);
  assert.match(visual.equality.result, /x=3/);

  const runtime = fs.readFileSync(
    path.join(repoRoot, "site/assets/js/lesson-page-runtime.js"),
    "utf8",
  );
  assert.match(runtime, /lesson-step-fixed-product-flow/);
  assert.match(runtime, /fixed-flow-matrix-wrap/);
  assert.match(runtime, /fixed-flow-amgm-mappings/);
});

test("fourth basic inequality exercise constructs a fixed product from the fixed sum", () => {
  const lesson = readLesson("inequality-basic-q04");
  const visual = lesson.steps[0].visual;
  assert.equal(visual.kind, "fixed-product-construction-flow");
  assert.equal(visual.methodTag, "构造型｜乘入定和");
  assert.match(visual.initialCheck.product, /12.*ab/);
  assert.equal(visual.clue.condition, "\\(a+3b=2\\)");
  assert.match(visual.construction.expanded, /=3\+.*=15\+/);
  assert.deepEqual(
    visual.construction.cells.map((row) => row.map((cell) => cell.role)),
    [["constant", "constructed"], ["constructed", "constant"]],
  );
  assert.match(visual.fixedPair.product, /=36/);
  assert.deepEqual(
    visual.application.mappings.map((mapping) => [mapping.slot, mapping.value]),
    [["\\(u\\)", "\\(\\frac{9b}{a}\\)"], ["\\(v\\)", "\\(\\frac{4a}{b}\\)"]],
  );
  assert.match(visual.application.conclusion, /27.*2/);
  assert.match(visual.equality.result, /a=\\frac\{2\}\{3\}/);
});

test("fifth basic inequality exercise completes a matching term before optional substitution", () => {
  const lesson = readLesson("inequality-basic-q05");
  const visual = lesson.steps[0].visual;
  assert.equal(visual.kind, "fixed-product-construction-flow");
  assert.equal(visual.methodTag, "构造型｜补项凑定积");
  assert.match(visual.initialCheck.verdict, /x 未必为正/);
  assert.equal(visual.construction.kind, "completion");
  assert.equal(visual.construction.matchingTerm, "\\(x+1\\)");
  assert.match(visual.construction.identity, /x=\(x\+1\)-1/);
  assert.match(visual.construction.expanded, /x\+1.*\\frac\{4\}\{x\+1\}.*-1/);
  assert.match(visual.construction.simplification, /t=x\+1.*简写/);
  assert.match(visual.fixedPair.product, /\(x\+1\).*\\frac\{4\}\{x\+1\}=4/);
  assert.deepEqual(
    visual.application.mappings.map((mapping) => [mapping.slot, mapping.value]),
    [["\\(u\\)", "\\(x+1\\)"], ["\\(v\\)", "\\(\\frac{4}{x+1}\\)"]],
  );
  assert.match(visual.application.conclusion, /3/);
  assert.equal(visual.equality.result, "\\(x=1\\)");

  const runtime = fs.readFileSync(
    path.join(repoRoot, "site/assets/js/lesson-page-runtime.js"),
    "utf8",
  );
  assert.match(runtime, /fixed-flow-completion-board/);
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
