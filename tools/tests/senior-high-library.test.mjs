import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";

import {
  validateCatalog,
  validateCollections,
  validateLearningTopics,
} from "../build-senior-high-library.mjs";
import { repoRoot } from "./calculus-test-helpers.mjs";

const chapterSource = JSON.parse(
  fs.readFileSync(path.join(repoRoot, "internal/senior-high/catalog/chapters.json"), "utf8"),
);
const problemSource = JSON.parse(
  fs.readFileSync(path.join(repoRoot, "internal/senior-high/catalog/problems.json"), "utf8"),
);
const collectionSource = JSON.parse(
  fs.readFileSync(path.join(repoRoot, "internal/senior-high/catalog/collections.json"), "utf8"),
);
const learningTopicSource = JSON.parse(
  fs.readFileSync(path.join(repoRoot, "internal/senior-high/catalog/learning-topics.json"), "utf8"),
);

function loadModel() {
  const sandbox = { URLSearchParams };
  vm.createContext(sandbox);
  vm.runInContext(
    fs.readFileSync(path.join(repoRoot, "site/assets/js/senior-high-library-model.js"), "utf8"),
    sandbox,
  );
  return sandbox.SeniorHighLibraryModel;
}

test("validates the real senior-high catalog and its published assets", () => {
  const catalog = validateCatalog(chapterSource, problemSource, repoRoot);
  assert.equal(catalog.problems.length, 2);
  assert.ok(catalog.problems.every((problem) => problem.chapterId === "derivative"));
  assert.deepEqual(
    catalog.problems.map((problem) => problem.sectionId).sort(),
    ["derivative-applications", "derivative-concepts-and-calculation"],
  );
  const derivative = catalog.chapters.find((chapter) => chapter.id === "derivative");
  assert.deepEqual(
    derivative.sections.map((section) => section.label),
    ["基本概念和运算", "导数应用"],
  );
  const functions = catalog.chapters.find((chapter) => chapter.id === "functions");
  assert.deepEqual(
    functions.sections.map((section) => section.label),
    ["函数的概念", "函数的表示法"],
  );
  assert.equal(functions.sections[0].presentation, "worksheet");
  assert.equal(functions.sections[0].defaultCollectionId, "function-concepts-foundation");
  assert.deepEqual(functions.sections[0].collectionIds, [
    "function-concepts-foundation",
    "function-concepts-advanced",
  ]);
  assert.equal(functions.sections[1].presentation, "worksheet");
  assert.equal(functions.sections[1].defaultCollectionId, "function-representation-foundation");
  assert.deepEqual(functions.sections[1].collectionIds, [
    "function-representation-foundation",
  ]);
  const sets = catalog.chapters.find((chapter) => chapter.id === "sets");
  assert.equal(sets.sections[0].presentation, "learning");
  assert.equal(sets.sections[0].topicId, "set-concepts-and-representation");
  assert.deepEqual(
    sets.sections.map((section) => [section.label, section.topicId]),
    [
      ["集合的概念和表示", "set-concepts-and-representation"],
      ["集合的关系和运算", "set-relations-and-operations"],
      ["常用逻辑用语", "common-logical-language"],
    ],
  );
});

test("builds the first set learning topic with three published knowledge modules", () => {
  const catalog = validateCatalog(chapterSource, problemSource, repoRoot);
  const topics = validateLearningTopics(catalog, learningTopicSource, repoRoot);
  assert.equal(topics.length, 4);
  const topic = topics[0];
  assert.equal(topic.title, "集合的概念和表示");
  assert.deepEqual(
    topic.modules.map((module) => [module.id, module.type, module.status]),
    [
      ["set-concept", "knowledge", "published"],
      ["element-set-relation", "knowledge", "published"],
      ["set-representation", "knowledge", "published"],
      ["practice", "assessment", "published"],
    ],
  );
  assert.equal(topic.modules[0].examples.length, 4);
  assert.equal(topic.modules[1].examples.length, 2);
  assert.equal(topic.modules[2].examples.length, 25);
  const ordinalChoice = topic.modules[2].examples.find(
    (example) => example.lesson.id === "set-representation-enumeration-q03",
  );
  assert.deepEqual(
    [ordinalChoice.answerSchema.type, ordinalChoice.answerSchema.choiceStyle, ordinalChoice.answerSchema.expected],
    ["single-choice", "ordinal", "③"],
  );
  assert.deepEqual(
    topic.modules[2].knowledgeGroups.map((group) => group.title),
    ["列举法", "描述法", "区间表示法", "Venn 图法"],
  );
  assert.ok(topic.modules[2].examples.every((example) => example.display === "featured"));
  assert.deepEqual(
    topic.modules[2].examples
      .filter((example) => example.answerSchema.type === "multipart-exact")
      .map((example) => example.lesson.id),
    [
      "set-representation-description-q01",
      "set-representation-description-q14",
      "set-representation-interval-q01",
      "set-representation-venn-q04",
    ],
  );
  const naturalLanguageMultipart = topic.modules[2].examples.find(
    (example) => example.lesson.id === "set-representation-description-q01",
  );
  assert.equal(naturalLanguageMultipart.answerSchema.layout, "per-part");
  const intervalMultipart = topic.modules[2].examples.find(
    (example) => example.lesson.id === "set-representation-interval-q01",
  );
  assert.equal(intervalMultipart.answerSchema.layout, "per-part");
  assert.equal(intervalMultipart.answerSchema.expected.length, 4);
  assert.ok(intervalMultipart.answerSchema.expected.every((part) => part.prompt));
  assert.equal(naturalLanguageMultipart.answerSchema.input.mode, "text");
  assert.equal(naturalLanguageMultipart.answerSchema.expected.length, 6);
  assert.ok(naturalLanguageMultipart.answerSchema.expected.every((part) => (
    part.label && part.promptHtml && part.aliases.length > 0
  )));
  assert.equal(naturalLanguageMultipart.answerSchema.expected[2].note, "ℕ 表示自然数集。");
  assert.deepEqual(
    topic.modules[1].knowledgeGroups.map((group) => group.title),
    ["属于与不属于", "数集及其符号"],
  );
  assert.deepEqual(
    topic.modules[1].examples.map((example) => example.answerSchema.type),
    ["relation-sequence", "single-choice"],
  );
  assert.match(
    topic.modules[1].knowledgeBlocks
      .flatMap((block) => block.bodyHtml)
      .join(""),
    /class="math-notin"/,
  );
  assert.deepEqual(
    topic.modules[0].knowledgeBlocks.map((block) => block.category),
    ["concept", "concept", "concept", "property", "property", "property"],
  );
  assert.deepEqual(
    topic.modules[0].examples.map((example) => example.answerSchema.type),
    ["single-choice", "variable-domain", "finite-set-values", "integer"],
  );
  assert.deepEqual(
    topic.modules[0].examples.map((example) => example.group),
    ["确定性", "互异性", "互异性", "互异性"],
  );
  assert.ok(topic.modules[0].examples.every(
    (example) => example.title && example.hints.length === 2,
  ));
  assert.ok(topic.modules[0].examples.slice(1).every(
    (example) => (
      example.answerSchema.input.mode === "math-expression"
      && example.answerSchema.input.keyboard.length > 0
    ),
  ));
  assert.deepEqual(
    topic.modules[0].examples[1].answerSchema.expected.excludedValues,
    ["-1", "1/4", "2/3"],
  );
  const model = loadModel();
  const conceptChoiceLine = topic.modules[0].examples[0].lesson.problem.lines[1].html;
  assert.deepEqual(
    Array.from(model.splitWorksheetOptions(conceptChoiceLine).options, (option) => option.label),
    ["A", "B", "C", "D"],
  );
  assert.deepEqual(
    topic.modules[3].items.map((item) => [item.number, item.status]),
    [[1, "published"], [2, "published"], [3, "published"], [4, "published"], [5, "published"], [6, "published"]],
  );
  assert.deepEqual(
    topic.modules[3].items.map((item) => item.answerSchema.type),
    ["single-choice", "single-choice", "single-choice", "single-choice", "exact-expression", "exact-expression"],
  );
  assert.equal(topic.modules[3].items[2].answerSchema.expected, "D");
  assert.ok(topic.modules[3].items.every((item) => item.hints.length >= 1));
  assert.equal(topic.modules[3].items[2].lesson.id, "set-practice-q03");
  assert.ok(topic.modules[0].examples.every(
    (example) => example.lesson.solutionPath.startsWith(
      "problems/senior-high/sets/set-concepts-and-representation/",
    ),
  ));
});

test("builds the complete inequality topic with four published modules", () => {
  const catalog = validateCatalog(chapterSource, problemSource, repoRoot);
  const topics = validateLearningTopics(catalog, learningTopicSource, repoRoot);
  const topic = topics.find((item) => item.id === "inequality-relations");
  assert.ok(topic);
  assert.equal(topic.mapRootLabel, "不等关系");
  assert.deepEqual(
    topic.modules.map((module) => [module.id, module.status]),
    [
      ["inequality-relations", "published"],
      ["solving-inequalities", "published"],
      ["basic-inequalities", "published"],
      ["inequality-practice", "published"],
    ],
  );
  assert.equal(topic.modules[0].examples.length, 9);
  assert.equal(topic.modules[1].examples.length, 13);
  assert.equal(topic.modules[2].examples.length, 6);
  assert.equal(topic.modules[3].items.length, 13);
  const basicVisualKnowledge = topic.modules[2].knowledgeBlocks.find(
    (block) => block.basicInequalityVisual,
  );
  const basicConditionsKnowledge = topic.modules[2].knowledgeBlocks.find(
    (block) => block.basicInequalityConditions,
  );
  assert.equal(basicVisualKnowledge?.groupId, "basic-theorem");
  assert.equal(basicConditionsKnowledge?.groupId, "basic-theorem");
  assert.deepEqual(
    topic.modules[2].knowledgeGroups.map((group) => group.title),
    ["基本不等式与等号条件", "乘入条件，展开找定积", "围绕分母补项凑定积"],
  );
  const conditionConstructionKnowledge = topic.modules[2].knowledgeBlocks.find(
    (block) => block.fixedProductConditionVisual,
  );
  const completionConstructionKnowledge = topic.modules[2].knowledgeBlocks.find(
    (block) => block.fixedProductCompletionVisual,
  );
  assert.equal(conditionConstructionKnowledge?.groupId, "fixed-transform");
  assert.equal(completionConstructionKnowledge?.groupId, "substitution");
  assert.match(conditionConstructionKnowledge.body.join(""), /交叉正项.*乘积/);
  assert.match(completionConstructionKnowledge.body.join(""), /换元.*简化书写/);
  assert.deepEqual(
    topic.modules[1].knowledgeGroups.map((group) => group.lessonCount),
    [3, 3, 4, 3],
  );
  const quadraticKnowledge = topic.modules[1].knowledgeBlocks.find(
    (block) => block.groupId === "quadratic-inequalities",
  );
  assert.ok(quadraticKnowledge);
  assert.deepEqual(
    quadraticKnowledge.quadraticInequalityTables.map((table) => table.opening),
    ["up", "down"],
  );
  assert.ok(quadraticKnowledge.quadraticInequalityTables.every(
    (table) => table.cases.map((quadraticCase) => quadraticCase.discriminant).join(",")
      === "positive,zero,negative",
  ));
  assert.deepEqual(
    quadraticKnowledge.quadraticInequalityTables[0].cases.map(
      (quadraticCase) => [quadraticCase.positiveSolution, quadraticCase.negativeSolution],
    ),
    [
      ["\\((-\\infty,x_1)\\cup(x_2,+\\infty)\\)", "\\((x_1,x_2)\\)"],
      ["\\(\\mathbb{R}\\setminus\\{x_0\\}\\)", "\\(\\varnothing\\)"],
      ["\\(\\mathbb{R}\\)", "\\(\\varnothing\\)"],
    ],
  );
  assert.deepEqual(
    quadraticKnowledge.quadraticInequalityTables[1].cases.map(
      (quadraticCase) => [quadraticCase.positiveSolution, quadraticCase.negativeSolution],
    ),
    [
      ["\\((x_1,x_2)\\)", "\\((-\\infty,x_1)\\cup(x_2,+\\infty)\\)"],
      ["\\(\\varnothing\\)", "\\(\\mathbb{R}\\setminus\\{x_0\\}\\)"],
      ["\\(\\varnothing\\)", "\\(\\mathbb{R}\\)"],
    ],
  );
  const learningClient = fs.readFileSync(
    path.join(repoRoot, "site/assets/js/senior-high-library.js"),
    "utf8",
  );
  assert.match(learningClient, /quadratic-inequality-table/);
  assert.match(learningClient, /quadratic-graph-curve/);
  assert.match(learningClient, /knowledgeBlocksForGroup/);
  assert.match(learningClient, /basic-inequality-proof-table/);
  assert.match(learningClient, /renderBasicInequalitySemicircleFigure/);
  assert.match(learningClient, /renderFixedProductConditionVisual/);
  assert.match(learningClient, /renderFixedProductCompletionVisual/);
  const polynomialKnowledge = topic.modules[1].knowledgeBlocks.find(
    (block) => block.groupId === "polynomial-inequalities",
  );
  assert.ok(polynomialKnowledge);
  assert.deepEqual(
    polynomialKnowledge.threadingLineTable.rows.map((row) => row.kind),
    ["simple-strict", "simple-inclusive", "mixed-multiplicity"],
  );
  assert.match(
    polynomialKnowledge.threadingLineTable.rows[1].principles.join(""),
    /空心点.*实心点/,
  );
  assert.match(
    polynomialKnowledge.threadingLineTable.rows[2].principles.join(""),
    /奇数重根.*偶数重根/,
  );
  assert.match(
    polynomialKnowledge.threadingLineTable.rows[2].inequality,
    /x\^5.*\(x-1\)\^2.*\(x-2\)\^3.*\(x\+1\)\^4/,
  );
  assert.equal(
    polynomialKnowledge.threadingLineTable.rows[2].solution,
    "\\(x∈(0,1)\\cup(1,2)\\)",
  );
  assert.ok(polynomialKnowledge.threadingLineTable.rows.every(
    (row) => !row.inequality.includes("\\frac") && !row.inequality.includes("/"),
  ));
  assert.match(learningClient, /threading-line-table/);
  assert.match(learningClient, /threading-line-shade/);
  assert.match(learningClient, /threading-line-even-ring/);
  assert.match(learningClient, /4次·偶.*5次·奇.*2次·偶.*3次·奇/s);
  assert.match(learningClient, /threading-line-direction/);
  assert.match(learningClient, /从最右侧开始/);
  const rationalKnowledge = topic.modules[1].knowledgeBlocks.find(
    (block) => block.groupId === "rational-inequalities",
  );
  assert.ok(rationalKnowledge);
  assert.deepEqual(
    rationalKnowledge.rationalThreadingTable.rows.map((row) => row.kind),
    ["direct-strict", "inclusive-endpoints", "move-to-zero"],
  );
  assert.match(
    rationalKnowledge.rationalThreadingTable.rows[0].principles.join(""),
    /\\frac\{a\}\{b\}>0\\iff ab>0/,
  );
  assert.match(
    rationalKnowledge.rationalThreadingTable.rows[1].principles.join(""),
    /\\frac\{a\}\{b\}\\ge0\\iff ab\\ge0.*分母零点.*空心禁值点/,
  );
  assert.match(
    rationalKnowledge.rationalThreadingTable.rows[2].principles.join(""),
    /F\(x\)>G\(x\)\\iff F\(x\)-G\(x\)>0.*\\frac\{-2x-1\}\{x\+3\}>0/,
  );
  assert.equal(
    rationalKnowledge.rationalThreadingTable.rows[2].solution,
    "\\(x∈(-3,-\\frac12)\\)",
  );
  assert.match(learningClient, /rational-threading-table/);
  assert.match(learningClient, /rational-critical-point is-forbidden/);
  assert.match(learningClient, /分母·禁值/);
  const absoluteKnowledge = topic.modules[1].knowledgeBlocks.find(
    (block) => block.groupId === "absolute-inequalities",
  );
  assert.ok(absoluteKnowledge);
  assert.deepEqual(
    absoluteKnowledge.absoluteInequalityTable.rows.map((row) => row.kind),
    ["direct", "squaring", "classification"],
  );
  assert.match(
    absoluteKnowledge.absoluteInequalityTable.rows[0].principles.join(""),
    /\|x\|<a\\iff-a<x<a.*\|x\|>a\\iff x<-a/,
  );
  assert.match(
    absoluteKnowledge.absoluteInequalityTable.rows[1].principles.join(""),
    /\|f\(x\)\|>\|g\(x\)\|\\iff f\(x\)\^2>g\(x\)\^2/,
  );
  assert.equal(absoluteKnowledge.absoluteInequalityTable.rows[2].transformations.length, 4);
  assert.equal(
    absoluteKnowledge.absoluteInequalityTable.rows[2].solution,
    "\\(x∈(-\\infty,-3]\\cup[2,+\\infty)\\)",
  );
  assert.match(absoluteKnowledge.body.join(""), /平方法是高效的特殊技巧.*分类讨论法最通用/);
  assert.match(learningClient, /absolute-inequality-table/);
  assert.match(learningClient, /absolute-piecewise-curve/);
  assert.deepEqual(
    topic.modules[0].knowledgeBlocks.map((block) => block.title),
    [
      "实数的符号与运算结果",
      "不等式的基本性质",
      "不等式的运算性质",
      "作差法",
      "作商法",
      "中间量法",
    ],
  );
  assert.match(topic.modules[0].knowledgeBlocks[2].body.join(""), /可加法则.*可乘法则.*可乘方性/);
  assert.match(topic.modules[0].knowledgeBlocks[3].body.join(""), /a-b>0.*a-b<0.*a-b=0/);
  assert.match(topic.modules[0].knowledgeBlocks[4].body.join(""), /a\/b>1.*a\/b<1.*a\/b=1/);
  assert.match(topic.modules[0].knowledgeBlocks[5].body.join(""), /中间量.*0 或 1/);
  assert.ok(topic.modules[1].examples.every(
    (example) => example.lesson.solutionPath.startsWith(
      "problems/senior-high/inequalities/inequality-relations/",
    ),
  ));
  assert.deepEqual(
    topic.modules[2].knowledgeGroups.map((group) => group.lessonCount),
    [2, 2, 2],
  );
  assert.deepEqual(
    topic.modules[3].items.map((item) => item.answerSchema.type),
    [
      "single-choice",
      "single-choice",
      "single-choice",
      "single-choice",
      "single-choice",
      "exact-expression",
      "exact-expression",
      "exact-expression",
      "exact-expression",
      "exact-expression",
      "exact-expression",
      "multipart-exact",
      "multipart-exact",
    ],
  );
  assert.ok(topic.modules[2].examples.every(
    (example) => example.lesson.solutionPath.startsWith(
      "problems/senior-high/inequalities/inequality-relations/",
    ),
  ));
  assert.ok(topic.modules[3].items.every(
    (item) => item.lesson.solutionPath.startsWith(
      "problems/senior-high/inequalities/inequality-relations/",
    ),
  ));
  assert.deepEqual(
    topic.modules[2].examples.slice(0, 4).map((example) => example.answerSchema.expected[0]),
    ["1", "4", "9", "27/2"],
  );
  assert.deepEqual(
    topic.modules[3].items.slice(0, 5).map((item) => item.answerSchema.expected),
    ["D", "C", "B", "C", "D"],
  );
  assert.deepEqual(
    topic.modules[3].items.slice(5, 11).map((item) => item.answerSchema.expected[0]),
    [
      "(-6,-1)",
      "(2,5]",
      "[-3,2)",
      "[-2,1/2)",
      "(-∞,-4)∪[-1,2]",
      "[23/5,5)",
    ],
  );
  assert.deepEqual(
    topic.modules[3].items[11].answerSchema.expected.map((part) => part.aliases[0]),
    ["(-∞,-6/5]∪[2,+∞)", "[-2,0]∪[4,6]"],
  );
  assert.deepEqual(
    topic.modules[3].items[12].answerSchema.expected.map((part) => part.aliases[0]),
    ["(-∞,-3/2]∪[3/2,+∞)", "(1/2,+∞)"],
  );
});

test("builds the second set topic with published relations and operations", () => {
  const catalog = validateCatalog(chapterSource, problemSource, repoRoot);
  const topic = validateLearningTopics(catalog, learningTopicSource, repoRoot)
    .find((item) => item.id === "set-relations-and-operations");
  assert.equal(topic.title, "集合的关系和运算");
  assert.equal(topic.introduction.length, 1);
  assert.deepEqual(
    topic.mapNodes.map((node) => node.label),
    ["集合的关系", "集合的运算"],
  );
  assert.deepEqual(topic.mapNodes[0].children, [
    { label: "子集", children: ["空集是任何集合的子集"] },
    { label: "集合相等" },
    { label: "真子集", children: ["空集是任何非空集合的真子集"] },
  ]);
  assert.deepEqual(
    topic.modules.map((module) => [module.id, module.type, module.status]),
    [
      ["set-relations", "knowledge", "published"],
      ["set-operations", "knowledge", "published"],
      ["practice", "assessment", "published"],
    ],
  );
  assert.equal(topic.modules[0].examples.length, 19);
  assert.equal(topic.modules[1].examples.length, 21);
  assert.equal(topic.modules[2].items.length, 9);
  assert.equal(topic.modules[2].items[8].lesson.id, "set-relations-operations-practice-q09");
  assert.deepEqual(
    topic.modules[1].knowledgeGroups.map((group) => group.title),
    ["交集", "并集", "补集"],
  );
  const operationKnowledgeHtml = topic.modules[1].knowledgeBlocks
    .flatMap((block) => block.bodyHtml)
    .join("");
  assert.match(operationKnowledgeHtml, /x∈ A 且 x∈ B/);
  assert.match(operationKnowledgeHtml, /x∈ U 且 x.*aria-label="不属于".* A/s);
  assert.doesNotMatch(operationKnowledgeHtml, /\\ /);
  assert.deepEqual(
    [...new Set(topic.modules[1].examples.map((example) => example.group))],
    ["交集", "并集", "补集"],
  );
  assert.deepEqual(
    topic.modules[0].knowledgeGroups.map((group) => group.title),
    ["子集和集合相等", "真子集与符号辨析", "子集个数和区间包含"],
  );
  assert.equal(topic.modules[0].knowledgeGroups[0].visual, "venn-subset");
  assert.deepEqual(
    [...new Set(topic.modules[0].examples.map((example) => example.group))],
    ["子集", "集合相等", "真子集", "子集个数"],
  );
  assert.deepEqual(
    topic.modules[0].examples
      .filter((example) => example.answerSchema.type === "relation-sequence")
      .map((example) => example.answerSchema.expected),
    [["=", "=", "="], ["⊊", "∉", "∉", "⊊", "⊋"], ["⊋", "⊊", "⊊"]],
  );
});

test("builds common logical language with a textbook-faithful map and all modules published", () => {
  const catalog = validateCatalog(chapterSource, problemSource, repoRoot);
  const topic = validateLearningTopics(catalog, learningTopicSource, repoRoot)
    .find((item) => item.id === "common-logical-language");
  assert.equal(topic.title, "常用逻辑用语");
  assert.equal(topic.mapRootLabel, "命题");
  assert.deepEqual(topic.mapNodes.map((node) => node.label), [
    "充分条件与必要条件",
    "全称量词与存在量词",
  ]);
  assert.deepEqual(
    topic.modules.map((module) => [module.id, module.status]),
    [
      ["propositions", "published"],
      ["sufficient-necessary-conditions", "published"],
      ["quantifiers", "published"],
      ["quantifier-negations", "published"],
      ["logic-practice", "published"],
    ],
  );
  assert.equal(topic.modules[0].examples.length, 2);
  assert.equal(topic.modules[1].examples.length, 10);
  assert.equal(topic.modules[2].examples.length, 3);
  assert.equal(topic.modules[3].examples.length, 4);
  assert.equal(topic.modules[4].items.length, 9);
  const negationBlocks = topic.modules[3].knowledgeBlocks;
  const negationTable = negationBlocks.find((block) => block.title === "常见否定形式")?.table;
  assert.deepEqual(negationTable?.rows, [
    ["原语句", "是", "都是", "大于", "至少有一个", "至多有一个", "对任意 \\(x∈A\\)，\\(p(x)\\) 为真"],
    ["否定", "不是", "不都是", "小于或等于", "一个也没有", "至少有两个", "存在 \\(x∈A\\)，\\(p(x)\\) 为假"],
  ]);
  assert.deepEqual(
    topic.modules[1].knowledgeGroups.map((group) => group.title),
    ["条件和结论", "充分条件与必要条件", "充分、必要与充要条件的判断"],
  );
  assert.deepEqual(
    topic.modules[1].knowledgeBlocks.map((block) => block.title),
    [
      "条件和结论",
      "符号 p⇒q 与 p⇏q 的含义",
      "充分条件、必要条件与充要条件",
      "从逻辑推理关系看",
      "从集合与集合间的关系看",
    ],
  );
  const conditionKnowledge = JSON.stringify(topic.modules[1].knowledgeBlocks);
  assert.deepEqual(
    topic.modules[1].knowledgeBlocks.map((block) => block.ordered),
    [false, true, true, true, true],
  );
  assert.deepEqual(
    topic.modules[1].knowledgeBlocks.map((block) => block.body.length),
    [1, 2, 2, 4, 4],
  );
  assert.match(conditionKnowledge, /p⇒q/);
  assert.match(conditionKnowledge, /p⇏q/);
  assert.match(conditionKnowledge, /p⇔q/);
  assert.match(conditionKnowledge, /A⊆B/);
  assert.doesNotMatch(conditionKnowledge, /\\\\(?:Rightarrow|nRightarrow|Leftrightarrow)/);
  const learningClient = fs.readFileSync(
    path.join(repoRoot, "site/assets/js/senior-high-library.js"),
    "utf8",
  );
  assert.match(learningClient, /class="senior-learning-knowledge-lines"/);
  assert.match(learningClient, /\["①", "②", "③", "④"/);
  assert.deepEqual(topic.modules[2].knowledgeGroups.map((group) => group.title), [
    "全称量词和全称量词命题",
    "存在量词和存在量词命题",
  ]);
  assert.deepEqual(topic.modules[3].knowledgeGroups.map((group) => group.title), [
    "命题的否定",
    "全称量词命题与存在量词命题的否定",
  ]);
});

test("wraps long mind-map labels at a logical conjunction", () => {
  const clientSource = fs.readFileSync(
    path.join(repoRoot, "site/assets/js/senior-high-library.js"),
    "utf8",
  );
  const helperStart = clientSource.indexOf("  function mindMapLabelLines");
  const helperEnd = clientSource.indexOf("\n  function renderSetMindMap", helperStart);
  assert.ok(helperStart >= 0 && helperEnd > helperStart);

  const sandbox = {};
  vm.runInNewContext(
    `${clientSource.slice(helperStart, helperEnd)}\nresult = mindMapLabelLines("全称量词命题的否定与存在量词命题的否定");`,
    sandbox,
  );
  assert.deepEqual(Array.from(sandbox.result), [
    "全称量词命题的否定",
    "与存在量词命题的否定",
  ]);
  assert.match(clientSource, /<tspan x=/);
});

test("rejects an unsupported learning answer schema", () => {
  const catalog = validateCatalog(chapterSource, problemSource, repoRoot);
  const invalidTopics = structuredClone(learningTopicSource);
  invalidTopics.learningTopics[0].modules[0].examples[0].answerSchema.type = "free-text";
  assert.throws(
    () => validateLearningTopics(catalog, invalidTopics, repoRoot),
    /answerSchema\.type 无效/,
  );
});

test("builds concept and representation worksheets without answers", () => {
  const catalog = validateCatalog(chapterSource, problemSource, repoRoot);
  const collections = validateCollections(catalog, collectionSource, repoRoot);
  assert.equal(collections.length, 3);
  const foundation = collections.find((collection) => collection.id === "function-concepts-foundation");
  const advanced = collections.find((collection) => collection.id === "function-concepts-advanced");
  const representation = collections.find((collection) => collection.id === "function-representation-foundation");

  assert.equal(foundation.title, "函数的概念 · 基础练习");
  assert.equal(foundation.problemCount, 11);
  assert.deepEqual(
    foundation.groups.map((group) => [group.label, group.problems.length]),
    [["函数概念", 3], ["函数定义域", 3], ["函数值域", 5]],
  );
  assert.deepEqual(
    foundation.groups.flatMap((group) => group.problems.map((problem) => problem.number)),
    Array.from({ length: 11 }, (_, index) => index + 1),
  );

  assert.equal(advanced.title, "函数的概念 · 能力提升");
  assert.equal(advanced.problemCount, 13);
  assert.deepEqual(
    advanced.groups.map((group) => [group.label, group.problems.length]),
    [["函数概念", 2], ["函数定义域", 4], ["函数值域", 6], ["函数综合应用", 1]],
  );
  assert.deepEqual(
    advanced.groups.flatMap((group) => group.problems.map((problem) => problem.number)),
    Array.from({ length: 13 }, (_, index) => index + 1),
  );

  assert.equal(representation.title, "函数的表示法 · 基础练习");
  assert.equal(representation.problemCount, 13);
  assert.deepEqual(
    representation.groups.map((group) => [group.label, group.problems.length]),
    [["图象法和列表法", 3], ["函数的解析式", 4], ["分段函数与综合应用", 6]],
  );
  assert.deepEqual(
    representation.groups.flatMap((group) => group.problems.map((problem) => problem.number)),
    Array.from({ length: 13 }, (_, index) => index + 1),
  );

  for (const collection of collections) {
    const serialized = JSON.stringify(collection);
    assert.doesNotMatch(serialized, /"answer"/);
    assert.doesNotMatch(serialized, /keyPoints/);
    assert.ok(collection.groups.flatMap((group) => group.problems).every(
      (problem) => problem.solutionPath.endsWith(`${problem.id}.html`),
    ));
    assert.equal(collection.status, "published");
    const expectedSectionPath = collection.id === "function-representation-foundation"
      ? "function-representation"
      : "function-concepts-and-representation";
    assert.ok(collection.groups.flatMap((group) => group.problems).every(
      (problem) => problem.solutionPath.startsWith(
        `problems/senior-high/functions/${expectedSectionPath}/`,
      ),
    ));
  }
});

test("worksheet carries the two textbook figures through namespaced specs", () => {
  const catalog = validateCatalog(chapterSource, problemSource, repoRoot);
  const collection = validateCollections(catalog, collectionSource, repoRoot)
    .find((item) => item.id === "function-concepts-foundation");
  const problems = collection.groups.flatMap((group) => group.problems);
  const q03 = problems.find((problem) => problem.number === 3);
  const q06 = problems.find((problem) => problem.number === 6);

  assert.equal(q03.originalFigures.length, 4);
  assert.equal(q06.originalFigures.length, 1);
  for (const problem of [q03, q06]) {
    assert.deepEqual(
      problem.figureSpec.panels.map((panel) => panel.id),
      problem.originalFigures.map((figure) => figure.renderId),
    );
    assert.ok(problem.originalFigures.every(
      (figure) => figure.renderId.startsWith(`${problem.id}--`),
    ));
  }
  assert.equal(
    validateCollections(catalog, collectionSource, repoRoot)
      .find((item) => item.id === "function-representation-foundation")
      .groups[0].problems[0].originalFigures[0].kind,
    "valueTable",
  );
});

test("rejects unknown sections, duplicate IDs and missing published files", () => {
  const unknownSection = structuredClone(problemSource);
  unknownSection.problems[0].sectionId = "missing";
  assert.throws(() => validateCatalog(chapterSource, unknownSection, repoRoot), /未知 section/);

  const duplicate = structuredClone(problemSource);
  duplicate.problems.push(structuredClone(duplicate.problems[0]));
  assert.throws(() => validateCatalog(chapterSource, duplicate, repoRoot), /ID 重复/);

  const missingFile = structuredClone(problemSource);
  missingFile.problems[0].thumbnail = "assets/images/problem-thumbnails/missing.svg";
  assert.throws(() => validateCatalog(chapterSource, missingFile, repoRoot), /缺少已发布文件/);
});

test("filters the derivative type without treating tags as classifications", () => {
  const model = loadModel();
  const catalog = validateCatalog(chapterSource, problemSource, repoRoot);
  const matched = model.filterProblems(catalog, {
    chapter: "derivative",
    section: "derivative-concepts-and-calculation",
  });
  assert.equal(matched.length, 1);

  const tagAsSection = model.filterProblems(catalog, {
    chapter: "derivative",
    section: "common-tangent",
  });
  assert.equal(tagAsSection.length, 2, "invalid section falls back to all sections");

  const applications = model.filterProblems(catalog, {
    chapter: "derivative",
    section: "derivative-applications",
  });
  assert.deepEqual(
    Array.from(applications, (problem) => problem.id),
    ["cn-2022-new-gaokao-i-15"],
  );
});

test("normalizes URL state and paginates eight items per page", () => {
  const model = loadModel();
  const catalog = validateCatalog(chapterSource, problemSource, repoRoot);
  const state = model.parseSearch(
    catalog,
    "?chapter=unknown&section=unknown&difficulty=9&sort=unknown&page=-2",
  );
  assert.equal(JSON.stringify(state), JSON.stringify(model.DEFAULT_STATE));

  const page = model.paginate(Array.from({ length: 17 }, (_, index) => index), 3);
  assert.equal(page.items.length, 1);
  assert.equal(page.pageCount, 3);
  assert.equal(page.page, 3);
});

test("resolves worksheet state without changing the card catalog filters", () => {
  const model = loadModel();
  const base = validateCatalog(chapterSource, problemSource, repoRoot);
  const catalog = {
    ...base,
    collections: validateCollections(base, collectionSource, repoRoot),
  };
  const worksheetState = model.parseSearch(
    catalog,
    "?chapter=functions&section=function-concepts-and-representation",
  );
  const collection = model.collectionForState(catalog, worksheetState);
  assert.equal(collection.id, "function-concepts-foundation");
  assert.equal(model.collectionProblemCount(collection), 11);
  assert.equal(model.filterProblems(catalog, worksheetState).length, 0);
  assert.equal(model.collectionForState(catalog, { chapter: "derivative" }), null);

  const advancedState = model.parseSearch(
    catalog,
    "?chapter=functions&section=function-concepts-and-representation&collection=function-concepts-advanced",
  );
  const advanced = model.collectionForState(catalog, advancedState);
  assert.equal(advanced.id, "function-concepts-advanced");
  assert.equal(model.collectionProblemCount(advanced), 13);
  assert.match(model.stateToSearch(advancedState), /collection=function-concepts-advanced/);

  const representationState = model.parseSearch(
    catalog,
    "?chapter=functions&section=function-representation",
  );
  const representation = model.collectionForState(catalog, representationState);
  assert.equal(representation.id, "function-representation-foundation");
  assert.equal(model.collectionProblemCount(representation), 13);
  assert.match(
    model.stateToSearch(representationState),
    /section=function-representation/,
  );
  assert.match(
    model.stateToSearch(representationState),
    /collection=function-representation-foundation/,
  );

  const misplacedRepresentation = model.parseSearch(
    catalog,
    "?chapter=functions&section=function-concepts-and-representation&collection=function-representation-foundation",
  );
  assert.equal(
    misplacedRepresentation.collection,
    "function-concepts-foundation",
    "函数表示法集合不能再落入函数概念子目录",
  );
});

test("normalizes direct learning-topic URLs and preserves worksheet URLs", () => {
  const model = loadModel();
  const base = validateCatalog(chapterSource, problemSource, repoRoot);
  const catalog = {
    ...base,
    collections: validateCollections(base, collectionSource, repoRoot),
    learningTopics: validateLearningTopics(base, learningTopicSource, repoRoot),
  };
  const conceptState = model.parseSearch(
    catalog,
    "?chapter=sets&section=set-concepts-and-representation&module=set-concept",
  );
  assert.equal(conceptState.module, "set-concept");
  assert.equal(model.learningTopicForState(catalog, conceptState).id, "set-concepts-and-representation");
  assert.equal(model.collectionForState(catalog, conceptState), null);

  const invalidModule = model.parseSearch(
    catalog,
    "?chapter=sets&section=set-concepts-and-representation&module=missing",
  );
  assert.equal(invalidModule.module, "overview");

  const worksheetState = model.parseSearch(
    catalog,
    "?chapter=functions&section=function-representation&collection=function-representation-foundation",
  );
  assert.equal(worksheetState.module, "all");
  assert.equal(model.collectionForState(catalog, worksheetState).id, "function-representation-foundation");
});

test("splits worksheet choices away from the question stem and stacks long choices", () => {
  const model = loadModel();
  const shortChoices = model.splitWorksheetOptions(
    "交点个数为（　）　A. 0　B. 1　C. 2　D. 不确定",
  );
  assert.equal(shortChoices.stemHtml, "交点个数为（　）");
  assert.equal(
    JSON.stringify(shortChoices.options.map((option) => option.label)),
    JSON.stringify(["A", "B", "C", "D"]),
  );
  assert.equal(shortChoices.stacked, false);

  const longChoices = model.splitWorksheetOptions(
    '下列等式成立的是（　）　A. <span>f(x<sup>2</sup>)=x<sup>3</sup></span>　B. <span>f(x<sup>2</sup>+1)=|x+1|</span>　C. <span>f(x<sup>2</sup>+x)=|x|</span>　D. <span>f(|x|)=x<sup>2</sup>+1</span>',
  );
  assert.equal(longChoices.options.length, 4);
  assert.equal(longChoices.stacked, true);
  assert.match(longChoices.options[1].html, /<sup>2<\/sup>/);
});

test("splits circled-number choices into an ordinal single-choice group", () => {
  const model = loadModel();
  const choices = model.splitOrdinalOptions(
    '方程组的解集是：① <span>{2,1}</span>；② <span>{x=2,y=1}</span>；③ <span>{(2,1)}</span>；④ <span>{(1,2)}</span>。',
  );
  assert.equal(choices.stemHtml, "方程组的解集是：");
  assert.deepEqual(
    Array.from(choices.options, (option) => option.label),
    ["①", "②", "③", "④"],
  );
  assert.equal(choices.options[2].html, "<span>{(2,1)}</span>");
});

test("normalizes integer and fractional learning answers before comparison", () => {
  const model = loadModel();
  assert.equal(model.canonicalRational(" 2/4 "), "1/2");
  assert.equal(model.canonicalRational("−2/-4"), "1/2");
  assert.equal(model.canonicalRational("6/3"), "2");
  assert.equal(model.canonicalRational("1/0"), null);
  assert.equal(model.canonicalRational("sqrt(2)"), null);
  assert.equal(
    model.normalizeExactMathExpression("(-∞,4)；{0,1,2,3};ℝ"),
    "(-∞,4);{0,1,2,3};ℝ",
  );
});

test("mobile learning choices switch to a single column before phone widths", () => {
  const css = fs.readFileSync(
    path.join(repoRoot, "site/assets/css/senior-high-library.css"),
    "utf8",
  );
  assert.match(
    css,
    /@media \(max-width: 720px\)[\s\S]*?\.senior-learning-choice-grid\s*\{\s*grid-template-columns:\s*minmax\(0, 1fr\)/,
  );
});

test("parses equivalent set conditions without relying on a fixed field count", () => {
  const model = loadModel();
  assert.deepEqual(
    Array.from(model.parseVariableDomainExclusions("x≠-1，x≠1/4，x≠2/3")),
    ["-1", "1/4", "2/3"],
  );
  assert.deepEqual(
    Array.from(model.parseVariableDomainExclusions("x∈ℝ∖{-1,2/3,1/4}")),
    ["-1", "2/3", "1/4"],
  );
  assert.deepEqual(
    Array.from(model.parseVariableDomainExclusions("x∉{-1,1/4,2/3}")),
    ["-1", "1/4", "2/3"],
  );
  assert.equal(model.parseVariableDomainExclusions("x=-1"), null);
  assert.deepEqual(
    Array.from(model.parseFiniteSetValues("{2,0,1}")),
    ["2", "0", "1"],
  );
  assert.deepEqual(
    Array.from(model.parseFiniteSetValues("0，1，2")),
    ["0", "1", "2"],
  );
  assert.deepEqual(
    Array.from(model.parseRelationSequence("∉，∈，∉，∈，∉，∈，∈")),
    ["∉", "∈", "∉", "∈", "∉", "∈", "∈"],
  );
  assert.deepEqual(
    Array.from(model.parseRelationSequence("\\notin,\\in,\\notin")),
    ["∉", "∈", "∉"],
  );
  assert.deepEqual(
    Array.from(model.parseRelationSequence("\\subsetneq,\\notin,\\supsetneq,=")),
    ["⊊", "∉", "⊋", "="],
  );
  assert.equal(model.parseRelationSequence("∈，不属于"), null);
});

test("relation-sequence exercises render answer slots inside the problem text", () => {
  const runtime = fs.readFileSync(
    path.join(repoRoot, "site/assets/js/senior-high-library.js"),
    "utf8",
  );
  assert.match(runtime, /data-relation-slot/);
  assert.match(runtime, /data-relation-key="\$\{escapeHtml\(relation\)\}"/);
  assert.match(runtime, /"∈": "属于"/);
  assert.match(runtime, /"⊊": "真子集"/);
  assert.match(runtime, /expected\.length.*个关系符号及顺序都正确/);
  assert.doesNotMatch(runtime, /七个关系符号/);
  assert.doesNotMatch(
    runtime,
    /schema\.type === "relation-sequence"[\s\S]{0,300}<textarea/,
  );
});

test("multipart natural-language exercises render one field per subquestion", () => {
  const runtime = fs.readFileSync(
    path.join(repoRoot, "site/assets/js/senior-high-library.js"),
    "utf8",
  );
  assert.match(runtime, /schema\.type === "multipart-exact" && schema\.layout === "per-part"/);
  assert.match(runtime, /class="senior-learning-multipart-row"/);
  assert.match(runtime, /data-answer-index="\$\{index\}"/);
  assert.match(runtime, /提交全部答案/);
  assert.match(runtime, /还有（\$\{missing\.join\("）（"\)\}）未作答/);
  assert.match(runtime, /class="senior-learning-symbol-note-button"/);
  assert.match(runtime, /aria-describedby="learning-symbol-note-/);
  assert.match(runtime, /schema\.input\.mode === "math-expression"/);
  assert.match(runtime, /partResults\.length.*个小题全部回答正确/);
});

test("multipart judgments render two quick choices for every subquestion", () => {
  const runtime = fs.readFileSync(
    path.join(repoRoot, "site/assets/js/senior-high-library.js"),
    "utf8",
  );
  assert.match(runtime, /schema\.type === "multipart-choice"/);
  assert.match(runtime, /data-part-choice=/);
  assert.match(runtime, /data-answer-type="multipart-choice"/);
  assert.match(runtime, /还有（\$\{missing\.join\("）（"\)\}）未选择/);
  assert.match(runtime, /results\.length.*个判断全部正确/);
});

test("learning page keeps compact exercise anchors and the shared back-to-top control", () => {
  const runtime = fs.readFileSync(
    path.join(repoRoot, "site/assets/js/senior-high-library.js"),
    "utf8",
  );
  const page = fs.readFileSync(
    path.join(repoRoot, "site/senior-high/index.html"),
    "utf8",
  );
  assert.match(runtime, /<span>对应练习<\/span>/);
  assert.match(runtime, /examplesForKnowledgeGroup\(group\)\.length \? `<a class="senior-learning-exercise-anchor"/);
  assert.match(runtime, /group\.lessonCount \|\| examplesForKnowledgeGroup\(group\)\.length/);
  assert.match(runtime, /senior-learning-knowledge-table/);
  assert.doesNotMatch(runtime, /去做对应练习/);
  assert.match(page, /class="back-to-top"/);
  assert.match(page, /assets\/js\/home\.js/);
});

test("sorts and filters future catalog entries without changing classification", () => {
  const model = loadModel();
  const base = validateCatalog(chapterSource, problemSource, repoRoot);
  const catalog = structuredClone(base);
  catalog.problems.push({
    ...structuredClone(catalog.problems[0]),
    id: "future-derivative-problem",
    difficulty: 2,
    updatedAt: "2025-01-01T00:00:00+08:00",
    source: {
      ...catalog.problems[0].source,
      year: 2025,
      region: "天津",
    },
  });

  const difficultFirst = model.filterProblems(catalog, {
    chapter: "derivative",
    difficulty: "all",
    source: "all",
    sort: "difficulty-desc",
  });
  assert.equal(difficultFirst[0].id, "cn-2022-gaokao-jia-wen-20");

  const tianjin = model.filterProblems(catalog, {
    chapter: "derivative",
    section: "derivative-concepts-and-calculation",
    source: "天津",
  });
  assert.deepEqual(Array.from(tianjin, (item) => item.id), ["future-derivative-problem"]);
});

test("generated JSON and file fallback expose the same catalog", () => {
  const jsonCatalog = JSON.parse(
    fs.readFileSync(path.join(repoRoot, "site/data/senior-high-catalog.json"), "utf8"),
  );
  const sandbox = { window: {} };
  vm.createContext(sandbox);
  vm.runInContext(
    fs.readFileSync(path.join(repoRoot, "site/assets/js/senior-high-catalog-data.js"), "utf8"),
    sandbox,
  );
  assert.equal(
    JSON.stringify(sandbox.window.__SENIOR_HIGH_CATALOG__),
    JSON.stringify(jsonCatalog),
  );
});
