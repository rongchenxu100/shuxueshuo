import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

import { validateTextLesson } from "../build-text-page.mjs";
import { validateCatalog, validateLearningTopics } from "../build-senior-high-library.mjs";
import { splitChoiceText } from "../lib/lesson-html.mjs";
import { repoRoot } from "./calculus-test-helpers.mjs";

const lessonRoot = path.join(repoRoot, "internal/senior-high/lesson-specs");
const lessonIds = fs.readdirSync(lessonRoot).filter((id) => id.startsWith("logic-")).sort();

function readLesson(id) {
  return JSON.parse(fs.readFileSync(path.join(lessonRoot, id, "lesson-data.json"), "utf8"));
}

test("all common logical language lessons validate and compile", () => {
  assert.equal(lessonIds.length, 28);
  for (const id of lessonIds) {
    const lesson = validateTextLesson(readLesson(id), id);
    const outputPath = path.join(repoRoot, lesson.meta.outputPath);
    assert.ok(fs.existsSync(outputPath), id + " should have a compiled page");
    const html = fs.readFileSync(outputPath, "utf8");
    assert.match(html, /class="answer-chip"/);
    assert.doesNotMatch(html, /培训教材/);
    const visibleProblem = html.match(/<div class="problem-full">([\s\S]*?)<\/section>/)?.[1] ?? "";
    assert.doesNotMatch(visibleProblem, /\\(?:Rightarrow|subseteq|frac|varnothing)/);
  }
});

test("quantifier and negation lessons preserve scope and strict boundaries", () => {
  const truthJudgments = readLesson("logic-quantifier-q01");
  const truthChoice = readLesson("logic-quantifier-q02");
  const parameter = readLesson("logic-quantifier-q03");
  const scopedNegation = readLesson("logic-negation-q03");
  const practiceParameter = readLesson("logic-practice-q08");
  const emptySetParameter = readLesson("logic-practice-q09");
  assert.match(JSON.stringify(parameter), /4-12a<0/);
  assert.match(truthJudgments.problem.lines[1].text, /\\\(\(a,b\)\\\)/);
  assert.match(truthChoice.problem.lines[1].text, /\\mathbb R/);
  assert.match(truthChoice.problem.lines[1].text, /\\frac\{1\}\{4\}/);
  assert.equal(splitChoiceText(truthChoice.problem.lines[1].text)?.options.length, 4);
  assert.match(JSON.stringify(parameter), /a>\\\\frac\{1\}\{3\}/);
  assert.match(JSON.stringify(scopedNegation), /∀x≤0/);
  assert.match(JSON.stringify(scopedNegation), /x\^2-2x\+a>0/);
  assert.match(JSON.stringify(practiceParameter), /m≥3/);
  assert.match(JSON.stringify(emptySetParameter), /1-4a<0/);
  assert.match(JSON.stringify(emptySetParameter), /a>\\\\frac\{1\}\{4\}/);
});

test("practice parameter condition combines set evidence, implication arrows, and number lines", () => {
  const lesson = readLesson("logic-practice-q08");
  const visualCase = lesson.steps[0].visual.cases[0];
  assert.equal(lesson.steps[0].visual.kind, "implication-condition-pairs");
  assert.deepEqual([visualCase.sufficient, visualCase.necessary], [false, true]);
  assert.equal(visualCase.setEvidence.kind, "complement-right-ray-parameter");
  assert.deepEqual(
    [visualCase.setEvidence.pRowLabel, visualCase.setEvidence.qRowLabel],
    ["CℝA", "B"],
  );
  assert.equal(visualCase.setEvidence.relation, "B⊊CℝA ⇔ m≥3");
  assert.equal(visualCase.setEvidence.parameterSet, "\\(m∈[3,+∞)\\)");
  assert.equal(visualCase.setEvidence.explanations.length, 3);
  assert.doesNotMatch(JSON.stringify(visualCase.setEvidence), /(?:^|[^A-Z])P(?:[^A-Z]|$)|(?:^|[^A-Z])Q(?:[^A-Z]|$)/);
  assert.equal(visualCase.pText, "\\(x∈C_{\\mathbb R}A\\)");
  assert.equal(visualCase.qText, "\\(x∈B\\)");
  assert.doesNotMatch(visualCase.pText, /^p：/);
  assert.doesNotMatch(visualCase.qText, /^q：/);

  const runtime = fs.readFileSync(
    path.join(repoRoot, "site/assets/js/lesson-page-runtime.js"),
    "utf8",
  );
  assert.match(runtime, /complement-right-ray-parameter/);
  assert.match(runtime, /lesson-implication-set-segment is-result/);
  assert.match(runtime, /baseline-shift="sub"/);
  assert.match(runtime, /renderFormulaText\(line\)/);

  const html = fs.readFileSync(
    path.join(repoRoot, lesson.meta.outputPath),
    "utf8",
  );
  assert.match(html, /complement-right-ray-parameter/);
  assert.match(html, /B⊊CℝA ⇔ m≥3/);
});

test("negation exercises match the textbook options and render not-in robustly", () => {
  const q01 = readLesson("logic-negation-q01");
  const q02 = readLesson("logic-negation-q02");
  const q03 = readLesson("logic-negation-q03");
  const q04 = readLesson("logic-negation-q04");

  assert.match(q01.problem.lines[1].text, /∀x\\notin\\mathbb R/);
  assert.match(q01.problem.lines[1].text, /∃x\\notin\\mathbb R/);
  assert.match(q02.problem.lines[1].text, /A\. \\\(∀x\\notin\\mathbb Z/);
  assert.match(q02.problem.lines[1].text, /C\. \\\(∃x\\notin\\mathbb Z/);
  assert.match(q02.problem.lines[1].text, /D\. \\\(∃x∈\\mathbb Z，\|x-1\|\\notin\\mathbb N\^\*/);
  assert.equal(q02.steps[0].derive[0][1], "D");
  assert.match(q03.problem.lines[1].text, /A\. \\\(∀x>0/);
  assert.match(q03.problem.lines[1].text, /C\. \\\(∀x≤0，x\^2-2x\+a>0/);
  assert.ok(q04.problem.lines[1].text.includes("A. \\(∀a,b>0\\)"));
  assert.ok(q04.problem.lines[1].text.includes("至少有一个成立"));
  assert.ok(q04.problem.lines[1].text.includes("D. \\(∃a,b>0\\)"));
  assert.ok(q04.problem.lines[1].text.includes("都不成立"));
  assert.equal(q04.steps[0].table.rows.length, 2);
  assert.match(JSON.stringify(q04.steps[0].table), /两个不等式都不成立，即/);
  assert.match(JSON.stringify(q04.steps[0].derive), /a\+\\\\frac\{1\}\{b\}<2/);
  assert.match(JSON.stringify(q04.steps[0].derive), /b\+\\\\frac\{1\}\{a\}<2/);
  assert.equal(q04.steps[0].derive.at(-1)[1], "D");
});

test("quantifier, negation, and practice pages do not leak malformed math text", () => {
  const catalogData = fs.readFileSync(
    path.join(repoRoot, "site/assets/js/senior-high-catalog-data.js"),
    "utf8",
  );
  const targetIds = [
    "logic-quantifier-q01", "logic-quantifier-q02", "logic-quantifier-q03",
    "logic-negation-q01", "logic-negation-q02", "logic-negation-q03", "logic-negation-q04",
    "logic-practice-q01", "logic-practice-q02", "logic-practice-q03",
    "logic-practice-q04", "logic-practice-q05", "logic-practice-q06",
    "logic-practice-q07", "logic-practice-q08", "logic-practice-q09",
  ];
  for (const id of targetIds) {
    const html = fs.readFileSync(
      path.join(repoRoot, `site/problems/senior-high/sets/common-logical-language/${id}.html`),
      "utf8",
    );
    const visibleHtml = html.slice(0, html.indexOf("<script"));
    assert.doesNotMatch(
      visibleHtml,
      /mathbb|rac(?:12|13|14)|x_0|\\(?:frac|Delta)/,
      id,
    );
  }
  for (const id of ["logic-negation-q01", "logic-negation-q02", "logic-negation-q03", "logic-negation-q04"]) {
    const lesson = readLesson(id);
    assert.equal(splitChoiceText(lesson.problem.lines[1].text)?.options.length, 4, id);
  }
  const quantifierSlice = catalogData.slice(
    catalogData.indexOf('"id": "logic-quantifier-q01"'),
    catalogData.indexOf('"id": "logic-practice-q09"') + 2000,
  );
  assert.doesNotMatch(
    quantifierSlice,
    /\\\\frac(?:12|13|14)|\f| rac(?:12|13|14)/,
  );
  assert.match(quantifierSlice, /\\\\mathbb R/);
  assert.match(quantifierSlice, /\\\\frac\{1\}\{4\}/);
});

test("practice implication visuals render formula text instead of exposing delimiters", () => {
  const runtime = fs.readFileSync(
    path.join(repoRoot, "site/assets/js/lesson-page-runtime.js"),
    "utf8",
  );
  assert.match(runtime, /renderFormulaText\(item\.pText \|\| ""\)/);
  assert.match(runtime, /renderFormulaText\(item\.qText \|\| ""\)/);
  assert.match(runtime, /renderFormulaText\(item\.counterexample\)/);
  assert.doesNotMatch(runtime, /esc\(item\.(?:pText|qText|counterexample)/);

  for (const id of ["logic-practice-q01", "logic-practice-q02", "logic-practice-q03"]) {
    const lesson = readLesson(id);
    const visualCase = lesson.steps[0].visual.cases[0];
    assert.equal(visualCase.evidenceLabel, "判断依据", id);
    assert.match(visualCase.pText, /^\\\(.+\\\)$/s, id);
    assert.match(visualCase.qText, /^\\\(.+\\\)$/s, id);
  }
});

test("practice negation details reproduce all textbook choices", () => {
  const expectedAnswers = {
    "logic-practice-q04": "D",
    "logic-practice-q05": "A",
    "logic-practice-q06": "A",
    "logic-practice-q07": "B",
  };
  for (const [id, expected] of Object.entries(expectedAnswers)) {
    const lesson = readLesson(id);
    assert.equal(splitChoiceText(lesson.problem.lines[1].text)?.options.length, 4, id);
    assert.equal(lesson.steps[0].derive.at(-1)[1], expected, id);
    assert.doesNotMatch(lesson.problem.lines[1].text, /从教材所给/, id);
  }
  const q04 = readLesson("logic-practice-q04");
  assert.match(q04.problem.lines[1].text, /A\. \\\(∀n\\notin\\mathbb N/);
  assert.match(q04.problem.lines[1].text, /C\. \\\(∀n\\notin\\mathbb N/);
});

test("false declarative sentences remain propositions", () => {
  const lesson = readLesson("logic-proposition-q01");
  const rows = lesson.steps[0].table.rows;
  assert.deepEqual(rows.slice(0, 4).map((row) => row[3]), ["命题", "命题", "命题", "命题"]);
  assert.match(rows[2][2], /假/);
  assert.match(rows[3][2], /假/);
  assert.deepEqual(rows.slice(4).map((row) => row[3]), ["不是命题", "不是命题"]);
});

test("proposition judgments use per-item quick choices", () => {
  const chapters = JSON.parse(fs.readFileSync(
    path.join(repoRoot, "internal/senior-high/catalog/chapters.json"),
    "utf8",
  ));
  const problems = JSON.parse(fs.readFileSync(
    path.join(repoRoot, "internal/senior-high/catalog/problems.json"),
    "utf8",
  ));
  const topics = JSON.parse(fs.readFileSync(
    path.join(repoRoot, "internal/senior-high/catalog/learning-topics.json"),
    "utf8",
  ));
  const catalog = validateCatalog(chapters, problems, repoRoot);
  const topic = validateLearningTopics(catalog, topics, repoRoot)
    .find((item) => item.id === "common-logical-language");
  const examples = topic.modules.find((module) => module.id === "propositions").examples;
  assert.deepEqual(examples.map((example) => example.answerSchema.type), [
    "multipart-choice",
    "multipart-choice",
  ]);
  assert.ok(examples.every((example) => (
    example.answerSchema.choices.join("|") === "命题|不是命题"
  )));
  assert.deepEqual(
    examples[0].answerSchema.expected.map((part) => part.expected),
    ["命题", "命题", "命题", "命题", "不是命题", "不是命题"],
  );
});

test("condition judgments use per-item choices instead of typed answers", () => {
  const chapters = JSON.parse(fs.readFileSync(
    path.join(repoRoot, "internal/senior-high/catalog/chapters.json"),
    "utf8",
  ));
  const problems = JSON.parse(fs.readFileSync(
    path.join(repoRoot, "internal/senior-high/catalog/problems.json"),
    "utf8",
  ));
  const topics = JSON.parse(fs.readFileSync(
    path.join(repoRoot, "internal/senior-high/catalog/learning-topics.json"),
    "utf8",
  ));
  const catalog = validateCatalog(chapters, problems, repoRoot);
  const topic = validateLearningTopics(catalog, topics, repoRoot)
    .find((item) => item.id === "common-logical-language");
  const examples = topic.modules
    .find((module) => module.id === "sufficient-necessary-conditions")
    .examples.slice(0, 2);
  assert.deepEqual(examples.map((example) => example.answerSchema.type), [
    "multipart-choice",
    "multipart-choice",
  ]);
  assert.deepEqual(examples[0].answerSchema.choices, [
    "充分不必要条件",
    "必要不充分条件",
    "充要条件",
    "既不充分也不必要条件",
  ]);
  assert.deepEqual(
    examples[0].answerSchema.expected.map((part) => part.expected),
    ["充要条件", "充要条件", "充分不必要条件"],
  );
  assert.deepEqual(examples[1].answerSchema.choices, ["是充分条件", "不是充分条件"]);
  assert.deepEqual(
    examples[1].answerSchema.expected.map((part) => part.expected),
    ["是充分条件", "是充分条件", "是充分条件", "不是充分条件", "是充分条件", "是充分条件"],
  );
  assert.ok(examples.every((example) => example.answerSchema.input === undefined));
});

test("every condition classification audits sufficient and necessary relations", () => {
  const lesson = readLesson("logic-condition-q01");
  const classification = lesson.steps[0].table;
  assert.deepEqual(classification.headers.slice(1, 3), ["充分", "必要"]);
  assert.deepEqual(classification.rows.map((row) => row[3]), [
    "充要条件",
    "充要条件",
    "充分不必要条件",
  ]);
  assert.equal(lesson.steps[0].visual.kind, "implication-condition-pairs");
  assert.deepEqual(
    lesson.steps[0].visual.cases.map((item) => [item.sufficient, item.necessary]),
    [[true, true], [true, true], [true, false]],
  );
  assert.doesNotMatch(JSON.stringify(lesson.steps[0].visual), /正向|反向/);
  assert.doesNotMatch(JSON.stringify(lesson.problem.keyPoints), /正向|反向/);
  assert.match(lesson.steps[0].visual.cases[2].counterexample, /不一定有四个直角/);
  const visualCases = ["logic-condition-q03", "logic-condition-q04", "logic-condition-q05"]
    .map((id) => readLesson(id).steps[0].visual.cases[0]);
  assert.deepEqual(
    visualCases.map((item) => [item.sufficient, item.necessary]),
    [[true, false], [false, true], [false, true]],
  );
  assert.match(visualCases[0].counterexample, /a=2，b=0/);
  assert.match(visualCases[1].counterexample, /a=1，b=2/);
  assert.deepEqual(visualCases[2].setEvidence, {
    kind: "nested-open-intervals",
    pSet: "P=(0,4)",
    qSet: "Q=(0,1)",
    sharedLeft: "0",
    qRight: "1",
    pRight: "4",
    relation: "Q⊊P",
    explanations: [
      "P 中的元素不一定在 Q 中，所以 p 成立时 q 不一定成立——充分不成立。",
      "Q 中的每个元素都在 P 中，所以 q 成立时 p 一定成立——必要成立。",
    ],
  });
  assert.doesNotMatch(JSON.stringify(visualCases), /正向|反向/);
});

test("interval condition lesson renders aligned set evidence before implication arrows", () => {
  const html = fs.readFileSync(
    path.join(repoRoot, "site/problems/senior-high/sets/common-logical-language/logic-condition-q05.html"),
    "utf8",
  );
  const runtime = fs.readFileSync(path.join(repoRoot, "site/assets/js/lesson-page-runtime.js"), "utf8");
  const stylesheet = fs.readFileSync(
    path.join(repoRoot, "site/assets/css/interactive-geometry-page.css"),
    "utf8",
  );
  assert.match(html, /nested-open-intervals/);
  assert.match(html, /Q⊊P/);
  assert.match(runtime, /lesson-implication-set-evidence/);
  assert.match(runtime, /lesson-implication-set-explanations/);
  assert.match(runtime, /lesson-implication-set-explanation-index/);
  assert.match(runtime, /lesson-implication-set-explanation-text/);
  assert.match(runtime, /lesson-implication-grid is-/);
  assert.match(stylesheet, /\.lesson-implication-set-explanation-index\s*\{/);
  assert.match(stylesheet, /\.lesson-implication-set-explanation-text\s*\{/);
  assert.doesNotMatch(stylesheet, /\.lesson-implication-set-explanations span\s*\{/);
});

test("parameter endpoint problems use strict containment", () => {
  const setMembership = readLesson("logic-condition-q08");
  const necessary = readLesson("logic-condition-q09");
  const sufficient = readLesson("logic-condition-q10");
  assert.deepEqual(
    [setMembership, necessary, sufficient].map((lesson) => {
      const item = lesson.steps[0].visual.cases[0];
      return [item.sufficient, item.necessary];
    }),
    [[true, false], [true, false], [true, false]],
  );
  assert.equal(necessary.steps[0].visual.cases[0].setEvidence.layout, "fixed-inside-right-ray");
  assert.equal(sufficient.steps[0].visual.cases[0].setEvidence.layout, "nested-left-rays");
  assert.match(necessary.steps[0].visual.cases[0].setEvidence.relation, /a<−1/);
  assert.match(sufficient.steps[0].visual.cases[0].setEvidence.relation, /a>0/);
  assert.match(JSON.stringify(necessary), /a<-1/);
  assert.match(JSON.stringify(necessary), /不含端点 a/);
  assert.match(JSON.stringify(sufficient), /a=0.*充要条件/);
  assert.match(JSON.stringify(sufficient), /a>0/);
});
