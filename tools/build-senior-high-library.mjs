#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const currentFile = fileURLToPath(import.meta.url);
const repoRoot = path.resolve(path.dirname(currentFile), "..");

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function requireText(value, field) {
  if (typeof value !== "string" || value.trim() === "") {
    throw new Error(`${field} 必须是非空字符串`);
  }
}

function requireUnique(items, getId, label) {
  const ids = new Set();
  for (const item of items) {
    const id = getId(item);
    requireText(id, `${label}.id`);
    if (ids.has(id)) {
      throw new Error(`${label} ID 重复: ${id}`);
    }
    ids.add(id);
  }
  return ids;
}

export function validateCatalog(chapterSource, problemSource, root = repoRoot) {
  const chapters = chapterSource?.chapters;
  const problems = problemSource?.problems;
  if (!Array.isArray(chapters) || !Array.isArray(problems)) {
    throw new Error("目录源文件必须包含 chapters 和 problems 数组");
  }

  const chapterIds = requireUnique(chapters, (item) => item.id, "chapter");
  const sectionIds = new Set();
  const sectionsByChapter = new Map();

  for (const chapter of chapters) {
    requireText(chapter.label, `chapter ${chapter.id}.label`);
    if (!Number.isFinite(chapter.order) || !Array.isArray(chapter.sections)) {
      throw new Error(`chapter ${chapter.id} 缺少有效 order 或 sections`);
    }
    const localSections = requireUnique(
      chapter.sections,
      (item) => item.id,
      `chapter ${chapter.id} section`,
    );
    for (const section of chapter.sections) {
      requireText(section.label, `section ${section.id}.label`);
      if (!Number.isFinite(section.order)) {
        throw new Error(`section ${section.id}.order 必须是数字`);
      }
      if (sectionIds.has(section.id)) {
        throw new Error(`section ID 跨章节重复: ${section.id}`);
      }
      sectionIds.add(section.id);
    }
    sectionsByChapter.set(chapter.id, localSections);
  }

  requireUnique(problems, (item) => item.id, "problem");
  const paths = new Set();
  for (const problem of problems) {
    requireText(problem.title, `problem ${problem.id}.title`);
    requireText(problem.path, `problem ${problem.id}.path`);
    requireText(problem.thumbnail, `problem ${problem.id}.thumbnail`);
    if (!chapterIds.has(problem.chapterId)) {
      throw new Error(`problem ${problem.id} 引用未知 chapter: ${problem.chapterId}`);
    }
    if (!sectionsByChapter.get(problem.chapterId)?.has(problem.sectionId)) {
      throw new Error(`problem ${problem.id} 引用未知 section: ${problem.sectionId}`);
    }
    if (!Array.isArray(problem.knowledgePointIds) || !Array.isArray(problem.tags)) {
      throw new Error(`problem ${problem.id} 缺少知识点或标签数组`);
    }
    if (!Number.isInteger(problem.difficulty) || problem.difficulty < 1 || problem.difficulty > 5) {
      throw new Error(`problem ${problem.id}.difficulty 必须为 1 到 5 的整数`);
    }
    if (!problem.source || !Number.isInteger(problem.source.year)) {
      throw new Error(`problem ${problem.id} 缺少有效 source`);
    }
    for (const field of ["region", "examLabel", "questionNumber"]) {
      requireText(problem.source[field], `problem ${problem.id}.source.${field}`);
    }
    if (!Number.isFinite(Date.parse(problem.updatedAt))) {
      throw new Error(`problem ${problem.id}.updatedAt 不是有效日期`);
    }
    if (!new Set(["draft", "published"]).has(problem.status)) {
      throw new Error(`problem ${problem.id}.status 无效`);
    }
    if (paths.has(problem.path)) {
      throw new Error(`problem path 重复: ${problem.path}`);
    }
    paths.add(problem.path);

    if (problem.status === "published") {
      for (const relativePath of [problem.path, problem.thumbnail]) {
        const publicPath = path.join(root, "site", relativePath);
        if (!fs.existsSync(publicPath)) {
          throw new Error(`problem ${problem.id} 缺少已发布文件: site/${relativePath}`);
        }
      }
    }
  }

  return {
    version: Math.max(chapterSource.version ?? 1, problemSource.version ?? 1),
    chapters: [...chapters].sort((left, right) => left.order - right.order),
    problems: [...problems],
  };
}

export function buildCatalog(root = repoRoot) {
  const catalogDir = path.join(root, "internal/senior-high/catalog");
  const catalog = validateCatalog(
    readJson(path.join(catalogDir, "chapters.json")),
    readJson(path.join(catalogDir, "problems.json")),
    root,
  );
  const json = `${JSON.stringify(catalog, null, 2)}\n`;
  const dataPath = path.join(root, "site/data/senior-high-catalog.json");
  const fallbackPath = path.join(root, "site/assets/js/senior-high-catalog-data.js");
  fs.mkdirSync(path.dirname(dataPath), { recursive: true });
  fs.mkdirSync(path.dirname(fallbackPath), { recursive: true });
  fs.writeFileSync(dataPath, json, "utf8");
  fs.writeFileSync(
    fallbackPath,
    `window.__SENIOR_HIGH_CATALOG__ = ${JSON.stringify(catalog, null, 2)};\n`,
    "utf8",
  );
  return { catalog, dataPath, fallbackPath };
}

if (process.argv[1] && path.resolve(process.argv[1]) === currentFile) {
  try {
    const result = buildCatalog();
    console.log(`Wrote: ${result.dataPath}`);
    console.log(`Wrote: ${result.fallbackPath}`);
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
