import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";

import {
  validateCatalog,
  validateCollections,
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
    ["函数的概念及其表示"],
  );
  assert.equal(functions.sections[0].presentation, "worksheet");
  assert.equal(functions.sections[0].defaultCollectionId, "function-concepts-foundation");
  assert.deepEqual(functions.sections[0].collectionIds, [
    "function-concepts-foundation",
    "function-concepts-advanced",
  ]);
});

test("builds foundation and advanced worksheets without answers", () => {
  const catalog = validateCatalog(chapterSource, problemSource, repoRoot);
  const collections = validateCollections(catalog, collectionSource, repoRoot);
  assert.equal(collections.length, 2);
  const foundation = collections.find((collection) => collection.id === "function-concepts-foundation");
  const advanced = collections.find((collection) => collection.id === "function-concepts-advanced");

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

  for (const collection of collections) {
    const serialized = JSON.stringify(collection);
    assert.doesNotMatch(serialized, /"answer"/);
    assert.doesNotMatch(serialized, /keyPoints/);
    assert.ok(collection.groups.flatMap((group) => group.problems).every(
      (problem) => problem.solutionPath.endsWith(`${problem.id}.html`),
    ));
    assert.equal(collection.status, "published");
    assert.ok(collection.groups.flatMap((group) => group.problems).every(
      (problem) => problem.solutionPath.startsWith(
        "problems/senior-high/functions/function-concepts-and-representation/",
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
