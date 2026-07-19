import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";

import { validateCatalog } from "../build-senior-high-library.mjs";
import { repoRoot } from "./calculus-test-helpers.mjs";

const chapterSource = JSON.parse(
  fs.readFileSync(path.join(repoRoot, "internal/senior-high/catalog/chapters.json"), "utf8"),
);
const problemSource = JSON.parse(
  fs.readFileSync(path.join(repoRoot, "internal/senior-high/catalog/problems.json"), "utf8"),
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
  assert.equal(catalog.problems.length, 1);
  assert.equal(catalog.problems[0].chapterId, "derivative");
  assert.equal(catalog.problems[0].sectionId, "derivative-concepts-and-calculation");
  const derivative = catalog.chapters.find((chapter) => chapter.id === "derivative");
  assert.deepEqual(
    derivative.sections.map((section) => section.label),
    ["基本概念和运算", "导数应用"],
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
  assert.equal(tagAsSection.length, 1, "invalid section falls back to all sections");
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
