#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { renderInlineMathText } from "./lib/lesson-html.mjs";

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
      const presentation = section.presentation ?? "cards";
      if (!new Set(["cards", "worksheet"]).has(presentation)) {
        throw new Error(`section ${section.id}.presentation 无效`);
      }
      if (presentation === "worksheet") {
        requireText(section.defaultCollectionId, `section ${section.id}.defaultCollectionId`);
        if (!Array.isArray(section.collectionIds) || section.collectionIds.length === 0) {
          throw new Error(`section ${section.id}.collectionIds 必须是非空数组`);
        }
        requireUnique(section.collectionIds, (item) => item, `section ${section.id} collection`);
        if (!section.collectionIds.includes(section.defaultCollectionId)) {
          throw new Error(`section ${section.id}.defaultCollectionId 不在 collectionIds 中`);
        }
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
    if (problem.curriculum != null) {
      const curriculum = problem.curriculum;
      for (const field of [
        "chapterLabel",
        "sectionLabel",
        "subsectionLabel",
        "groupId",
        "groupLabel",
      ]) {
        requireText(curriculum[field], `problem ${problem.id}.curriculum.${field}`);
      }
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

function sanitizeProblemLines(lines, lessonId) {
  if (!Array.isArray(lines) || lines.length === 0) {
    throw new Error(`lesson ${lessonId} 缺少原题 lines`);
  }
  return lines.map((line) => {
    if (line.figures != null) {
      if (!Array.isArray(line.figures) || line.figures.length === 0) {
        throw new Error(`lesson ${lessonId} 原题图形为空`);
      }
      return {
        ariaLabel: line.ariaLabel ?? "",
        figures: line.figures.map((figure) => ({
          id: figure.id,
          title: figure.title ?? "",
          ariaLabel: figure.ariaLabel ?? "",
          caption: figure.caption ?? "",
        })),
      };
    }
    const text = String(line.text ?? line.heading ?? "");
    return {
      text,
      html: renderInlineMathText(text),
    };
  });
}

function buildCollectionProblem(root, lessonId, number, group) {
  requireText(lessonId, `collection ${group.id}.lessonId`);
  const lessonDir = path.join(root, "internal/senior-high/lesson-specs", lessonId);
  const lessonPath = path.join(lessonDir, "lesson-data.json");
  const specPath = path.join(lessonDir, "function-spec.json");
  for (const requiredPath of [lessonPath, specPath]) {
    if (!fs.existsSync(requiredPath)) {
      throw new Error(`collection lesson 缺少文件: ${path.relative(root, requiredPath)}`);
    }
  }

  const lesson = readJson(lessonPath);
  const spec = readJson(specPath);
  const curriculum = lesson.meta?.curriculum ?? lesson.curriculum;
  if (curriculum?.groupId !== group.id) {
    throw new Error(
      `lesson ${lessonId} 题组不匹配: ${curriculum?.groupId ?? "missing"} != ${group.id}`,
    );
  }

  const outputPath = lesson.meta?.outputPath;
  requireText(outputPath, `lesson ${lessonId}.meta.outputPath`);
  const siteRoot = path.join(root, "site");
  const absoluteOutputPath = path.resolve(root, outputPath);
  const relativeOutputPath = path.relative(siteRoot, absoluteOutputPath);
  if (
    relativeOutputPath.startsWith("..")
    || path.isAbsolute(relativeOutputPath)
    || path.extname(relativeOutputPath) !== ".html"
  ) {
    throw new Error(`lesson ${lessonId} 的 outputPath 必须指向 site 下的 HTML`);
  }
  const solutionPath = relativeOutputPath.split(path.sep).join("/");
  if (!fs.existsSync(path.join(root, "site", solutionPath))) {
    throw new Error(`lesson ${lessonId} 缺少解析页面: site/${solutionPath}`);
  }

  const lines = sanitizeProblemLines(lesson.problem?.lines, lessonId);
  const referencedFigures = lines.flatMap((line) => line.figures ?? []);
  const panelsById = new Map((spec.panels ?? []).map((panel) => [panel.id, panel]));
  const originalFigures = referencedFigures.map((figure) => {
    const panel = panelsById.get(figure.id);
    if (!panel) {
      throw new Error(`lesson ${lessonId} 原题图形引用未知 panel: ${figure.id}`);
    }
    return {
      id: figure.id,
      renderId: `${lessonId}--${figure.id}`,
    };
  });
  const figureSpec = originalFigures.length === 0
    ? null
    : {
        ...spec,
        panels: originalFigures.map(({ id, renderId }) => ({
          ...structuredClone(panelsById.get(id)),
          id: renderId,
        })),
      };

  return {
    id: lessonId,
    number,
    source: lesson.problem?.source || undefined,
    problem: { lines },
    originalFigures,
    figureSpec,
    solutionPath,
    groupId: group.id,
    groupLabel: group.label,
  };
}

export function validateCollections(catalog, collectionSource, root = repoRoot) {
  const collections = collectionSource?.collections;
  if (!Array.isArray(collections)) {
    throw new Error("聚合题单源文件必须包含 collections 数组");
  }
  requireUnique(collections, (item) => item.id, "collection");
  const lessons = new Set();

  return collections.map((collection) => {
    requireText(collection.title, `collection ${collection.id}.title`);
    if (!new Set(["draft", "published"]).has(collection.status)) {
      throw new Error(`collection ${collection.id}.status 无效`);
    }
    const chapter = catalog.chapters.find((item) => item.id === collection.chapterId);
    const section = chapter?.sections.find((item) => item.id === collection.sectionId);
    if (!chapter || !section) {
      throw new Error(`collection ${collection.id} 引用未知章节`);
    }
    if (
      section.presentation !== "worksheet"
      || !section.collectionIds?.includes(collection.id)
    ) {
      throw new Error(`collection ${collection.id} 未与 worksheet section 正确绑定`);
    }
    if (!Array.isArray(collection.groups) || collection.groups.length === 0) {
      throw new Error(`collection ${collection.id} 缺少 groups`);
    }
    requireUnique(collection.groups, (item) => item.id, `collection ${collection.id} group`);

    let number = 0;
    const groups = collection.groups.map((group) => {
      requireText(group.label, `collection ${collection.id} group ${group.id}.label`);
      if (!Array.isArray(group.lessonIds) || group.lessonIds.length === 0) {
        throw new Error(`collection ${collection.id} group ${group.id} 缺少 lessonIds`);
      }
      const problems = group.lessonIds.map((lessonId) => {
        if (lessons.has(lessonId)) {
          throw new Error(`collection lesson 重复: ${lessonId}`);
        }
        lessons.add(lessonId);
        number += 1;
        return buildCollectionProblem(root, lessonId, number, group);
      });
      return { id: group.id, label: group.label, problems };
    });

    if (collection.id === "function-concepts-foundation") {
      const sizes = groups.map((group) => group.problems.length).join("/");
      if (number !== 11 || sizes !== "3/3/5") {
        throw new Error(`function-concepts-foundation 必须包含 11 题并按 3/3/5 分组`);
      }
    }
    if (collection.id === "function-concepts-advanced") {
      const sizes = groups.map((group) => group.problems.length).join("/");
      if (number !== 13 || sizes !== "2/4/6/1") {
        throw new Error(`function-concepts-advanced 必须包含 13 题并按 2/4/6/1 分组`);
      }
    }

    return {
      id: collection.id,
      chapterId: collection.chapterId,
      sectionId: collection.sectionId,
      title: collection.title,
      label: collection.label || collection.title,
      status: collection.status,
      problemCount: number,
      groups,
    };
  });
}

export function buildCatalog(root = repoRoot) {
  const catalogDir = path.join(root, "internal/senior-high/catalog");
  const baseCatalog = validateCatalog(
    readJson(path.join(catalogDir, "chapters.json")),
    readJson(path.join(catalogDir, "problems.json")),
    root,
  );
  const catalog = {
    ...baseCatalog,
    collections: validateCollections(
      baseCatalog,
      readJson(path.join(catalogDir, "collections.json")),
      root,
    ),
  };
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
