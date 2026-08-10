#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { examSourceLabel, renderInlineMathText, renderSetFigure } from "./lib/lesson-html.mjs";

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
      if (!new Set(["cards", "worksheet", "learning"]).has(presentation)) {
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
      if (presentation === "learning") {
        requireText(section.topicId, `section ${section.id}.topicId`);
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
    if (line.figure != null) {
      const figureHtml = renderSetFigure(line.figure);
      if (!figureHtml) throw new Error(`lesson ${lessonId} 的集合图形类型无效`);
      return {
        figureHtml,
        ariaLabel: line.figure.ariaLabel ?? "",
      };
    }
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
      kind: panel.kind,
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
    source: examSourceLabel(lesson.problem?.source) || undefined,
    problem: { lines },
    originalFigures,
    figureSpec,
    solutionPath,
    groupId: group.id,
    groupLabel: group.label,
  };
}

function buildLearningLesson(root, lessonId, context) {
  requireText(lessonId, `${context}.lessonId`);
  const lessonPath = path.join(
    root,
    "internal/senior-high/lesson-specs",
    lessonId,
    "lesson-data.json",
  );
  if (!fs.existsSync(lessonPath)) {
    throw new Error(`${context} 缺少 lesson-data: ${lessonId}`);
  }
  const lesson = readJson(lessonPath);
  if (lesson.meta?.id !== lessonId) {
    throw new Error(`${context} lesson ID 不匹配: ${lesson.meta?.id ?? "missing"} != ${lessonId}`);
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
  return {
    id: lessonId,
    title: lesson.meta?.pageTitle || lessonId,
    source: examSourceLabel(lesson.problem?.source) || undefined,
    problem: {
      lines: sanitizeProblemLines(lesson.problem?.lines, lessonId),
    },
    solutionPath,
  };
}

function validateLearningAnswerSchema(schema, context) {
  if (!schema || typeof schema !== "object" || Array.isArray(schema)) {
    throw new Error(`${context}.answerSchema 必须是对象`);
  }
  const supportedTypes = new Set([
    "single-choice",
    "variable-domain",
    "finite-set-values",
    "integer",
    "relation-sequence",
    "multipart-choice",
    "exact-expression",
    "multipart-exact",
  ]);
  if (!supportedTypes.has(schema.type)) {
    throw new Error(`${context}.answerSchema.type 无效`);
  }
  if (schema.choiceStyle != null) {
    if (schema.type !== "single-choice" || schema.choiceStyle !== "ordinal") {
      throw new Error(`${context}.answerSchema.choiceStyle 无效`);
    }
  }
  if (schema.type === "single-choice" || schema.type === "integer") {
    requireText(schema.expected, `${context}.answerSchema.expected`);
  } else if (
    schema.type === "finite-set-values"
    || schema.type === "relation-sequence"
    || schema.type === "exact-expression"
  ) {
    if (!Array.isArray(schema.expected) || schema.expected.length === 0) {
      throw new Error(`${context}.answerSchema.expected 必须是非空数组`);
    }
    schema.expected.forEach((value, index) => {
      requireText(value, `${context}.answerSchema.expected[${index}]`);
    });
    if (
      schema.type === "relation-sequence"
      && schema.expected.some((value) => !new Set([
        "∈", "∉", "=", "≠", "⊆", "⊄", "⊊", "⊋", "⊇",
      ]).has(value))
    ) {
      throw new Error(`${context}.answerSchema.expected 包含不支持的关系符号`);
    }
    if (schema.type === "relation-sequence" && schema.input?.relations != null) {
      if (!Array.isArray(schema.input.relations) || schema.input.relations.length < 2) {
        throw new Error(`${context}.answerSchema.input.relations 至少需要两个符号`);
      }
      const supportedRelations = new Set(["∈", "∉", "=", "≠", "⊆", "⊄", "⊊", "⊋", "⊇"]);
      if (schema.input.relations.some((value) => !supportedRelations.has(value))) {
        throw new Error(`${context}.answerSchema.input.relations 包含不支持的关系符号`);
      }
      if (schema.expected.some((value) => !schema.input.relations.includes(value))) {
        throw new Error(`${context}.answerSchema.input.relations 未覆盖标准答案`);
      }
    }
  } else if (schema.type === "multipart-choice") {
    if (!Array.isArray(schema.choices) || schema.choices.length < 2) {
      throw new Error(`${context}.answerSchema.choices 至少需要两个选项`);
    }
    schema.choices.forEach((choice, index) => {
      requireText(choice, `${context}.answerSchema.choices[${index}]`);
    });
    if (!Array.isArray(schema.expected) || schema.expected.length < 2) {
      throw new Error(`${context}.answerSchema.expected 必须包含至少两个小题答案`);
    }
    schema.expected.forEach((part, index) => {
      requireText(part.label, `${context}.answerSchema.expected[${index}].label`);
      requireText(part.prompt, `${context}.answerSchema.expected[${index}].prompt`);
      requireText(part.expected, `${context}.answerSchema.expected[${index}].expected`);
      if (!schema.choices.includes(part.expected)) {
        throw new Error(`${context}.answerSchema.expected[${index}].expected 不在选项中`);
      }
    });
  } else if (schema.type === "multipart-exact") {
    if (!Array.isArray(schema.expected) || schema.expected.length < 2) {
      throw new Error(`${context}.answerSchema.expected 必须包含至少两个小题答案`);
    }
    schema.expected.forEach((part, index) => {
      if (!Array.isArray(part.aliases) || part.aliases.length === 0) {
        throw new Error(`${context}.answerSchema.expected[${index}].aliases 必须是非空数组`);
      }
      part.aliases.forEach((value, aliasIndex) => {
        requireText(value, `${context}.answerSchema.expected[${index}].aliases[${aliasIndex}]`);
      });
      if (schema.layout === "per-part") {
        requireText(part.label, `${context}.answerSchema.expected[${index}].label`);
        requireText(part.prompt, `${context}.answerSchema.expected[${index}].prompt`);
        if (part.note != null) {
          requireText(part.note, `${context}.answerSchema.expected[${index}].note`);
        }
      }
    });
    if (schema.layout != null && schema.layout !== "per-part") {
      throw new Error(`${context}.answerSchema.layout 无效`);
    }
  } else {
    requireText(schema.variable, `${context}.answerSchema.variable`);
    requireText(schema.domain, `${context}.answerSchema.domain`);
    if (!Array.isArray(schema.expected?.excludedValues) || schema.expected.excludedValues.length === 0) {
      throw new Error(`${context}.answerSchema.expected.excludedValues 必须是非空数组`);
    }
    schema.expected.excludedValues.forEach((value, index) => {
      requireText(value, `${context}.answerSchema.expected.excludedValues[${index}]`);
    });
  }
  if (schema.type !== "single-choice" && schema.type !== "multipart-choice") {
    const supportsTextInput = schema.type === "multipart-exact" && schema.layout === "per-part";
    if (schema.input?.mode !== "math-expression" && !(supportsTextInput && schema.input?.mode === "text")) {
      throw new Error(`${context}.answerSchema.input.mode 必须是 math-expression`);
    }
    if (
      schema.input.mode === "math-expression"
      && schema.type !== "relation-sequence"
      && (!Array.isArray(schema.input.keyboard) || schema.input.keyboard.length === 0)
    ) {
      throw new Error(`${context}.answerSchema.input.keyboard 必须是非空数组`);
    }
  }
  const normalized = structuredClone(schema);
  if (normalized.type === "multipart-exact" && normalized.layout === "per-part") {
    normalized.expected = normalized.expected.map((part) => ({
      ...part,
      promptHtml: renderInlineMathText(part.prompt),
    }));
  }
  if (normalized.type === "multipart-choice") {
    normalized.expected = normalized.expected.map((part) => ({
      ...part,
      promptHtml: renderInlineMathText(part.prompt),
    }));
  }
  return normalized;
}

export function validateLearningTopics(catalog, topicSource, root = repoRoot) {
  const topics = topicSource?.learningTopics;
  if (!Array.isArray(topics)) {
    throw new Error("学习专题源文件必须包含 learningTopics 数组");
  }
  requireUnique(topics, (item) => item.id, "learningTopic");
  const usedLessons = new Set();

  return topics.map((topic) => {
    requireText(topic.title, `learningTopic ${topic.id}.title`);
    const chapter = catalog.chapters.find((item) => item.id === topic.chapterId);
    const section = chapter?.sections.find((item) => item.id === topic.sectionId);
    if (!chapter || !section || section.presentation !== "learning") {
      throw new Error(`learningTopic ${topic.id} 引用未知 learning section`);
    }
    if (section.topicId !== topic.id) {
      throw new Error(`learningTopic ${topic.id} 未与 section.topicId 正确绑定`);
    }
    if (!Array.isArray(topic.introduction) || topic.introduction.length === 0) {
      throw new Error(`learningTopic ${topic.id} 缺少 introduction`);
    }
    if (!Array.isArray(topic.mapNodes) || topic.mapNodes.length === 0) {
      throw new Error(`learningTopic ${topic.id} 缺少 mapNodes`);
    }
    if (!Array.isArray(topic.modules) || topic.modules.length === 0) {
      throw new Error(`learningTopic ${topic.id} 缺少 modules`);
    }
    const moduleIds = requireUnique(
      topic.modules,
      (item) => item.id,
      `learningTopic ${topic.id} module`,
    );
    requireUnique(topic.mapNodes, (item) => item.id, `learningTopic ${topic.id} mapNode`);
    for (const node of topic.mapNodes) {
      requireText(node.label, `learningTopic ${topic.id} mapNode ${node.id}.label`);
      if (!moduleIds.has(node.moduleId)) {
        throw new Error(`mapNode ${node.id} 引用未知 module: ${node.moduleId}`);
      }
      if (!Array.isArray(node.children) || node.children.length === 0) {
        throw new Error(`mapNode ${node.id} 缺少 children`);
      }
      node.children.forEach((child, index) => {
        const childContext = `mapNode ${node.id}.children[${index}]`;
        if (typeof child === "string") {
          requireText(child, childContext);
          return;
        }
        if (!child || typeof child !== "object" || Array.isArray(child)) {
          throw new Error(`${childContext} 必须是字符串或知识节点`);
        }
        requireText(child.label, `${childContext}.label`);
        if (child.children != null) {
          if (!Array.isArray(child.children) || child.children.length === 0) {
            throw new Error(`${childContext}.children 必须是非空数组`);
          }
          child.children.forEach((leaf, leafIndex) => {
            requireText(leaf, `${childContext}.children[${leafIndex}]`);
          });
        }
      });
    }

    const modules = topic.modules.map((module) => {
      requireText(module.label, `learningTopic ${topic.id} module ${module.id}.label`);
      if (!new Set(["knowledge", "assessment"]).has(module.type)) {
        throw new Error(`learningTopic ${topic.id} module ${module.id}.type 无效`);
      }
      if (!new Set(["published", "pending"]).has(module.status)) {
        throw new Error(`learningTopic ${topic.id} module ${module.id}.status 无效`);
      }
      const base = {
        id: module.id,
        label: module.label,
        type: module.type,
        status: module.status,
        description: module.description || "",
      };
      if (module.status === "pending") {
        return {
          ...base,
          knownPoints: module.knownPoints || [],
        };
      }
      if (module.type === "knowledge") {
        if (!Array.isArray(module.knowledgeBlocks) || module.knowledgeBlocks.length === 0) {
          throw new Error(`module ${module.id} 缺少 knowledgeBlocks`);
        }
        if (!Array.isArray(module.examples) || module.examples.length === 0) {
          throw new Error(`module ${module.id} 缺少 examples`);
        }
        const examples = module.examples.map((example) => {
          if (usedLessons.has(example.lessonId)) {
            throw new Error(`learning lesson 重复: ${example.lessonId}`);
          }
          usedLessons.add(example.lessonId);
          const context = `module ${module.id} example ${example.lessonId}`;
          requireText(example.group, `${context}.group`);
          requireText(example.title, `${context}.title`);
          if (!Array.isArray(example.hints) || example.hints.length === 0) {
            throw new Error(`${context}.hints 必须是非空数组`);
          }
          example.hints.forEach((hint, index) => {
            requireText(hint, `${context}.hints[${index}]`);
          });
          if (example.knowledgeCategory != null && !new Set([
            "concept",
            "property",
            "enumeration",
            "description",
            "interval",
            "venn",
            "intersection",
            "union",
            "complement",
          ]).has(example.knowledgeCategory)) {
            throw new Error(`${context}.knowledgeCategory 无效`);
          }
          return {
            group: example.group,
            knowledgeCategory: example.knowledgeCategory || "",
            title: example.title,
            numberLabel: example.numberLabel || "",
            display: "featured",
            hints: [...example.hints],
            answerSchema: validateLearningAnswerSchema(example.answerSchema, context),
            lesson: buildLearningLesson(root, example.lessonId, `module ${module.id}`),
          };
        });
        return {
          ...base,
          knowledgeGroups: (module.knowledgeGroups || [
            {
              category: "concept",
              number: "01",
              eyebrow: "基本概念",
              title: "集合的概念",
            },
            {
              category: "property",
              number: "02",
              eyebrow: "元素性质",
              title: "集合中元素的性质",
            },
          ]).map((group, index) => {
            const context = `module ${module.id} knowledgeGroups[${index}]`;
            if (!new Set([
              "concept",
              "property",
              "enumeration",
              "description",
              "interval",
              "venn",
              "intersection",
              "union",
              "complement",
            ]).has(group.category)) {
              throw new Error(`${context}.category 无效`);
            }
            requireText(group.number, `${context}.number`);
            requireText(group.eyebrow, `${context}.eyebrow`);
            requireText(group.title, `${context}.title`);
            return structuredClone(group);
          }),
          knowledgeBlocks: module.knowledgeBlocks.map((block, index) => {
            const context = `module ${module.id} knowledgeBlocks[${index}]`;
            if (!new Set([
              "concept",
              "property",
              "enumeration",
              "description",
              "interval",
              "venn",
              "intersection",
              "union",
              "complement",
            ]).has(block.category)) {
              throw new Error(`${context}.category 无效`);
            }
            requireText(block.title, `${context}.title`);
            if (!Array.isArray(block.body) || block.body.length === 0) {
              throw new Error(`${context}.body 必须是非空数组`);
            }
            block.body.forEach((line, lineIndex) => {
              requireText(line, `${context}.body[${lineIndex}]`);
            });
            if (block.ordered !== undefined && typeof block.ordered !== "boolean") {
              throw new Error(`${context}.ordered 必须是布尔值`);
            }
            for (const flag of ["basicInequalityVisual", "basicInequalityConditions", "fixedProductConditionVisual", "fixedProductCompletionVisual"]) {
              if (block[flag] !== undefined && block[flag] !== true) {
                throw new Error(`${context}.${flag} 只能设为 true`);
              }
            }
            if (block.groupId !== undefined) {
              requireText(block.groupId, `${context}.groupId`);
              if (!module.knowledgeGroups.some((group) => group.id === block.groupId)) {
                throw new Error(`${context}.groupId 未对应 knowledgeGroups`);
              }
            }
            let table;
            if (block.table !== undefined) {
              if (!block.table || !Array.isArray(block.table.rows) || block.table.rows.length === 0) {
                throw new Error(`${context}.table.rows 必须是非空二维数组`);
              }
              const columnCount = block.table.rows[0]?.length;
              if (!columnCount || block.table.rows.some((row) => (
                !Array.isArray(row) || row.length !== columnCount
                || row.some((cell) => typeof cell !== "string" || !cell.trim())
              ))) {
                throw new Error(`${context}.table.rows 必须是等宽的非空字符串二维数组`);
              }
              table = {
                rows: block.table.rows,
                rowsHtml: block.table.rows.map((row) => row.map((cell) => renderInlineMathText(cell))),
              };
            }
            let quadraticInequalityTables;
            if (block.quadraticInequalityTables !== undefined) {
              if (!Array.isArray(block.quadraticInequalityTables)
                || block.quadraticInequalityTables.length !== 2) {
                throw new Error(`${context}.quadraticInequalityTables 必须包含 a>0 与 a<0 两张表`);
              }
              const expectedOpenings = ["up", "down"];
              quadraticInequalityTables = block.quadraticInequalityTables.map((quadraticTable, tableIndex) => {
                const tableContext = `${context}.quadraticInequalityTables[${tableIndex}]`;
                requireText(quadraticTable.title, `${tableContext}.title`);
                if (quadraticTable.opening !== expectedOpenings[tableIndex]) {
                  throw new Error(`${tableContext}.opening 必须是 ${expectedOpenings[tableIndex]}`);
                }
                if (!Array.isArray(quadraticTable.cases) || quadraticTable.cases.length !== 3) {
                  throw new Error(`${tableContext}.cases 必须包含 Δ>0、Δ=0、Δ<0 三种情况`);
                }
                const expectedCases = ["positive", "zero", "negative"];
                const cases = quadraticTable.cases.map((quadraticCase, caseIndex) => {
                  const caseContext = `${tableContext}.cases[${caseIndex}]`;
                  if (quadraticCase.discriminant !== expectedCases[caseIndex]) {
                    throw new Error(`${caseContext}.discriminant 必须是 ${expectedCases[caseIndex]}`);
                  }
                  ["root", "positiveSolution", "negativeSolution"].forEach((field) => {
                    requireText(quadraticCase[field], `${caseContext}.${field}`);
                  });
                  return {
                    discriminant: quadraticCase.discriminant,
                    root: quadraticCase.root,
                    rootHtml: renderInlineMathText(quadraticCase.root),
                    positiveSolution: quadraticCase.positiveSolution,
                    positiveSolutionHtml: renderInlineMathText(quadraticCase.positiveSolution),
                    negativeSolution: quadraticCase.negativeSolution,
                    negativeSolutionHtml: renderInlineMathText(quadraticCase.negativeSolution),
                  };
                });
                return {
                  title: quadraticTable.title,
                  titleHtml: renderInlineMathText(quadraticTable.title),
                  opening: quadraticTable.opening,
                  cases,
                };
              });
            }
            let threadingLineTable;
            if (block.threadingLineTable !== undefined) {
              const rows = block.threadingLineTable?.rows;
              if (!Array.isArray(rows) || rows.length !== 3) {
                throw new Error(`${context}.threadingLineTable.rows 必须包含三个示例`);
              }
              const expectedKinds = ["simple-strict", "simple-inclusive", "mixed-multiplicity"];
              threadingLineTable = {
                rows: rows.map((row, rowIndex) => {
                  const rowContext = `${context}.threadingLineTable.rows[${rowIndex}]`;
                  if (row.kind !== expectedKinds[rowIndex]) {
                    throw new Error(`${rowContext}.kind 必须是 ${expectedKinds[rowIndex]}`);
                  }
                  requireText(row.inequality, `${rowContext}.inequality`);
                  requireText(row.solution, `${rowContext}.solution`);
                  if (!Array.isArray(row.principles) || row.principles.length !== 2) {
                    throw new Error(`${rowContext}.principles 必须包含两条原则`);
                  }
                  row.principles.forEach((principle, principleIndex) => {
                    requireText(principle, `${rowContext}.principles[${principleIndex}]`);
                  });
                  return {
                    kind: row.kind,
                    inequality: row.inequality,
                    inequalityHtml: renderInlineMathText(row.inequality),
                    solution: row.solution,
                    solutionHtml: renderInlineMathText(row.solution),
                    principles: row.principles,
                    principlesHtml: row.principles.map((principle) => renderInlineMathText(principle)),
                  };
                }),
              };
            }
            let rationalThreadingTable;
            if (block.rationalThreadingTable !== undefined) {
              const rows = block.rationalThreadingTable?.rows;
              if (!Array.isArray(rows) || rows.length !== 3) {
                throw new Error(`${context}.rationalThreadingTable.rows 必须包含三个示例`);
              }
              const expectedKinds = ["direct-strict", "inclusive-endpoints", "move-to-zero"];
              rationalThreadingTable = {
                rows: rows.map((row, rowIndex) => {
                  const rowContext = `${context}.rationalThreadingTable.rows[${rowIndex}]`;
                  if (row.kind !== expectedKinds[rowIndex]) {
                    throw new Error(`${rowContext}.kind 必须是 ${expectedKinds[rowIndex]}`);
                  }
                  ["inequality", "equivalent", "solution"].forEach((field) => {
                    requireText(row[field], `${rowContext}.${field}`);
                  });
                  if (!Array.isArray(row.principles) || row.principles.length !== 2) {
                    throw new Error(`${rowContext}.principles 必须包含两条原则`);
                  }
                  row.principles.forEach((principle, principleIndex) => {
                    requireText(principle, `${rowContext}.principles[${principleIndex}]`);
                  });
                  return {
                    kind: row.kind,
                    inequality: row.inequality,
                    inequalityHtml: renderInlineMathText(row.inequality),
                    equivalent: row.equivalent,
                    equivalentHtml: renderInlineMathText(row.equivalent),
                    solution: row.solution,
                    solutionHtml: renderInlineMathText(row.solution),
                    principles: row.principles,
                    principlesHtml: row.principles.map((principle) => renderInlineMathText(principle)),
                  };
                }),
              };
            }
            let absoluteInequalityTable;
            if (block.absoluteInequalityTable !== undefined) {
              const rows = block.absoluteInequalityTable?.rows;
              if (!Array.isArray(rows) || rows.length !== 3) {
                throw new Error(`${context}.absoluteInequalityTable.rows 必须包含三个示例`);
              }
              const expectedKinds = ["direct", "squaring", "classification"];
              absoluteInequalityTable = {
                rows: rows.map((row, rowIndex) => {
                  const rowContext = `${context}.absoluteInequalityTable.rows[${rowIndex}]`;
                  if (row.kind !== expectedKinds[rowIndex]) {
                    throw new Error(`${rowContext}.kind 必须是 ${expectedKinds[rowIndex]}`);
                  }
                  requireText(row.inequality, `${rowContext}.inequality`);
                  requireText(row.solution, `${rowContext}.solution`);
                  if (!Array.isArray(row.transformations) || row.transformations.length < 2) {
                    throw new Error(`${rowContext}.transformations 至少包含两步`);
                  }
                  row.transformations.forEach((transformation, transformationIndex) => {
                    requireText(transformation, `${rowContext}.transformations[${transformationIndex}]`);
                  });
                  if (!Array.isArray(row.principles) || row.principles.length !== 2) {
                    throw new Error(`${rowContext}.principles 必须包含两条原则`);
                  }
                  row.principles.forEach((principle, principleIndex) => {
                    requireText(principle, `${rowContext}.principles[${principleIndex}]`);
                  });
                  return {
                    kind: row.kind,
                    inequality: row.inequality,
                    inequalityHtml: renderInlineMathText(row.inequality),
                    transformations: row.transformations,
                    transformationsHtml: row.transformations.map((transformation) => renderInlineMathText(transformation)),
                    solution: row.solution,
                    solutionHtml: renderInlineMathText(row.solution),
                    principles: row.principles,
                    principlesHtml: row.principles.map((principle) => renderInlineMathText(principle)),
                  };
                }),
              };
            }
            return {
              ...(block.groupId ? { groupId: block.groupId } : {}),
              category: block.category,
              title: block.title,
              ordered: block.ordered === true,
              body: block.body,
              bodyHtml: block.body.map((line) => renderInlineMathText(line)),
              ...(table ? { table } : {}),
              ...(quadraticInequalityTables ? { quadraticInequalityTables } : {}),
              ...(threadingLineTable ? { threadingLineTable } : {}),
              ...(rationalThreadingTable ? { rationalThreadingTable } : {}),
              ...(absoluteInequalityTable ? { absoluteInequalityTable } : {}),
              ...(block.basicInequalityVisual ? { basicInequalityVisual: true } : {}),
              ...(block.basicInequalityConditions ? { basicInequalityConditions: true } : {}),
              ...(block.fixedProductConditionVisual ? { fixedProductConditionVisual: true } : {}),
              ...(block.fixedProductCompletionVisual ? { fixedProductCompletionVisual: true } : {}),
            };
          }),
          examples,
          summary: module.summary || "",
          summaryHtml: renderInlineMathText(module.summary || ""),
        };
      }

      const items = (module.items || []).map((item) => {
        if (item.status === "pending") {
          return {
            number: item.number,
            status: "pending",
            title: item.title,
            note: item.note,
          };
        }
        if (usedLessons.has(item.lessonId)) {
          throw new Error(`learning lesson 重复: ${item.lessonId}`);
        }
        usedLessons.add(item.lessonId);
        const context = `module ${module.id} item ${item.lessonId}`;
        if (!Array.isArray(item.hints) || item.hints.length === 0) {
          throw new Error(`${context}.hints 必须是非空数组`);
        }
        item.hints.forEach((hint, index) => {
          requireText(hint, `${context}.hints[${index}]`);
        });
        return {
          number: item.number,
          status: "published",
          numberLabel: item.numberLabel || `第 ${item.number} 题`,
          hints: [...item.hints],
          answerSchema: validateLearningAnswerSchema(item.answerSchema, context),
          lesson: buildLearningLesson(root, item.lessonId, `module ${module.id}`),
        };
      });
      return { ...base, items };
    });

    return {
      id: topic.id,
      chapterId: topic.chapterId,
      sectionId: topic.sectionId,
      title: topic.title,
      mapRootLabel: topic.mapRootLabel || topic.title,
      eyebrow: topic.eyebrow || "",
      introduction: topic.introduction,
      introductionHtml: topic.introduction.map((line) => renderInlineMathText(line)),
      mapNodes: topic.mapNodes,
      modules,
    };
  });
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
    if (collection.id === "function-representation-foundation") {
      const sizes = groups.map((group) => group.problems.length).join("/");
      if (number !== 13 || sizes !== "3/4/6") {
        throw new Error(`function-representation-foundation 必须包含 13 题并按 3/4/6 分组`);
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
    learningTopics: validateLearningTopics(
      baseCatalog,
      readJson(path.join(catalogDir, "learning-topics.json")),
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
