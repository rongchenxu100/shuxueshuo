#!/usr/bin/env node
/** Compile a diagram-optional senior-high algebra/text lesson into the shared lesson shell. */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  buildKeyPointsHtml,
  examSourceLabel,
  renderInlineMathText,
  renderSetFigure,
  splitChoiceText,
} from "./lib/lesson-html.mjs";

const currentFile = fileURLToPath(import.meta.url);
const repoRoot = path.resolve(path.dirname(currentFile), "..");

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function replaceAll(template, replacements) {
  return Object.entries(replacements).reduce(
    (content, [key, value]) => content.split(key).join(value),
    template,
  );
}

function buildProblemLineHtml(line, source) {
  if (line.figure) {
    return renderSetFigure(line.figure);
  }
  const sourceHtml = source
    ? `<span class="problem-source-inline">（${esc(source)}）</span>`
    : "";
  if (line.heading != null) {
    return `<div class="problem-line"><strong>${sourceHtml}${esc(line.heading)}</strong></div>`;
  }
  const choiceGroup = splitChoiceText(line.text);
  if (choiceGroup) {
    const answerHtml = line.answerId != null
      ? '<span class="answer-chip" id="' + esc(line.answerId) + '">'
        + renderInlineMathText(line.answer) + "</span>"
      : "";
    const optionsHtml = choiceGroup.options
      .map((option) => (
        `<div class="problem-option"><span class="problem-option-label">${option.label}.</span><span>${renderInlineMathText(option.text)}</span></div>`
      ))
      .join("");
    return [
      '<div class="problem-line"><span>' + sourceHtml
        + renderInlineMathText(choiceGroup.stem) + "</span>" + answerHtml + "</div>",
      `<div class="problem-options${choiceGroup.stacked ? " is-stacked" : ""}">${optionsHtml}</div>`,
    ].join("\n");
  }
  if (line.answerId != null) {
    return '<div class="problem-line"><span>' + sourceHtml
      + renderInlineMathText(line.text ?? "") + '</span><span class="answer-chip" id="'
      + esc(line.answerId) + '">' + renderInlineMathText(line.answer) + "</span></div>";
  }
  return `<div class="problem-line"><span>${sourceHtml}${renderInlineMathText(line.text ?? "")}</span></div>`;
}

function collectAnswerSchemas(value, index = new Map()) {
  if (Array.isArray(value)) {
    value.forEach((item) => collectAnswerSchemas(item, index));
  } else if (value && typeof value === "object") {
    if (value.lessonId && value.answerSchema) index.set(value.lessonId, value.answerSchema);
    Object.values(value).forEach((item) => collectAnswerSchemas(item, index));
  }
  return index;
}

function setMath(value) {
  const text = String(value ?? "").replace(/(?<!\\)([{}])/g, "\\$1");
  return "\\(" + text + "\\)";
}

function preferredAlias(item, preferNaturalLanguage = false) {
  const aliases = item?.aliases ?? [];
  if (preferNaturalLanguage) {
    const natural = aliases.find((alias) => /[\u3400-\u9fff]/.test(alias));
    if (natural) return natural;
  }
  return aliases[0] ?? "";
}

export function answerTextForSchema(schema) {
  if (!schema) return "";
  switch (schema.type) {
    case "single-choice":
    case "integer":
      return "答案：" + schema.expected;
    case "finite-set-values":
      return "答案：" + setMath("{" + schema.expected.join(",") + "}");
    case "relation-sequence":
      return "答案：" + schema.expected.join("，");
    case "variable-domain": {
      const excluded = schema.expected?.excludedValues ?? [];
      return "答案：" + setMath(
        schema.variable + "∈ℝ，且 " + schema.variable + "≠" + excluded.join(","),
      );
    }
    case "exact-expression": {
      const expected = Array.isArray(schema.expected) ? schema.expected[0] : schema.expected;
      return "答案：" + setMath(expected);
    }
    case "multipart-exact": {
      const preferNaturalLanguage = schema.input?.mode === "text";
      const parts = (schema.expected ?? []).map((item, index) => {
        const label = item.label ?? "（" + (index + 1) + "）";
        const value = preferredAlias(item, preferNaturalLanguage);
        return preferNaturalLanguage ? label + value : label + setMath(value);
      });
      return "答案：" + parts.join("；");
    }
    default:
      return "";
  }
}

function answerSchemaForLesson(root, lessonId) {
  const topicPath = path.join(root, "internal/senior-high/catalog/learning-topics.json");
  if (!fs.existsSync(topicPath)) return null;
  return collectAnswerSchemas(readJson(topicPath)).get(lessonId) ?? null;
}

function buildProblemHtml(lines, source, answer) {
  const authoredLines = (lines ?? []).map((line) => ({ ...line }));
  if (answer && !authoredLines.some((line) => line.answerId != null)) {
    const choiceIndex = authoredLines.findLastIndex((line) => splitChoiceText(line.text));
    const fallbackIndex = authoredLines.findLastIndex((line) => !line.figure);
    const answerIndex = choiceIndex >= 0 ? choiceIndex : fallbackIndex;
    if (answerIndex >= 0) {
      authoredLines[answerIndex].answerId = "answerI";
      authoredLines[answerIndex].answer = answer;
    }
  }
  return authoredLines
    .map((line, index) => buildProblemLineHtml(line, index === 0 ? source : undefined))
    .join("\n");
}

function browserPath(filePath) {
  return filePath.split(path.sep).join("/");
}

function assetPrefixForOutput(root, outputPath) {
  const relative = path.relative(path.dirname(outputPath), path.join(root, "site", "assets"));
  const normalized = browserPath(relative || ".");
  return normalized.startsWith(".") ? normalized : `./${normalized}`;
}

function hrefForOutput(root, outputPath, targetPath) {
  const relative = path.relative(path.dirname(outputPath), path.resolve(root, targetPath));
  const normalized = browserPath(relative || ".");
  return normalized.startsWith(".") ? normalized : `./${normalized}`;
}

export function validateTextLesson(lesson, inputDir = "") {
  const meta = lesson?.meta;
  const problem = lesson?.problem;
  if (!meta?.id || !meta?.outputPath || !meta?.pageTitle) {
    throw new Error(`${inputDir || "text lesson"} 缺少 meta.id、meta.outputPath 或 meta.pageTitle`);
  }
  if (!Array.isArray(problem?.lines) || problem.lines.length === 0) {
    throw new Error(`${meta.id} 缺少 problem.lines`);
  }
  if (!Array.isArray(lesson.steps) || lesson.steps.length === 0) {
    throw new Error(`${meta.id} 缺少 steps`);
  }
  const ids = new Set();
  for (const step of lesson.steps) {
    if (!step.id || ids.has(step.id)) throw new Error(`${meta.id} 的 step.id 缺失或重复`);
    ids.add(step.id);
    if (!Array.isArray(step.derive) || step.derive.length === 0) {
      throw new Error(`${meta.id} 的步骤 ${step.id} 缺少 derive`);
    }
    if (step.reasoning != null) {
      if (!Array.isArray(step.reasoning) || step.reasoning.length < 2) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.reasoning 至少需要两行`);
      }
      for (const [index, line] of step.reasoning.entries()) {
        if (!line?.text || !new Set(["because", "therefore"]).has(line.kind)) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.reasoning[${index}] 无效`);
        }
      }
    }
    if (step.showDiagram !== false) {
      throw new Error(`${meta.id} 是文字题，步骤 ${step.id} 必须设置 showDiagram=false`);
    }
    if (step.table) {
      const { headers, rows } = step.table;
      if (!Array.isArray(headers) || headers.length < 2 || !Array.isArray(rows) || rows.length === 0) {
        throw new Error(`${meta.id} 的步骤 ${step.id} 表格必须包含 headers 和 rows`);
      }
      if (rows.some((row) => !Array.isArray(row) || row.length !== headers.length)) {
        throw new Error(`${meta.id} 的步骤 ${step.id} 表格列数不一致`);
      }
    }
  }
  return lesson;
}

export function buildTextPage(inputDir, root = repoRoot) {
  const inputPath = path.resolve(inputDir);
  const lessonPath = path.join(inputPath, "lesson-data.json");
  if (!fs.existsSync(lessonPath)) throw new Error(`缺少: ${lessonPath}`);
  const lesson = validateTextLesson(readJson(lessonPath), inputDir);
  const meta = lesson.meta;
  const outputPath = path.resolve(root, meta.outputPath);
  const siteRoot = path.join(root, "site");
  const relativeOutput = path.relative(siteRoot, outputPath);
  if (relativeOutput.startsWith("..") || path.extname(outputPath) !== ".html") {
    throw new Error(`${meta.id}.outputPath 必须指向 site 下的 HTML`);
  }

  const templatePath = path.join(root, "internal/templates/interactive-problem-page.template.html");
  const template = fs.readFileSync(templatePath, "utf8");
  const assetPrefix = assetPrefixForOutput(root, outputPath);
  const homeHref = hrefForOutput(root, outputPath, "site/index.html");
  const libraryBase = hrefForOutput(
    root,
    outputPath,
    meta.breadcrumbPath ?? "site/senior-high/index.html",
  );
  const libraryHref = `${libraryBase}${meta.breadcrumbSearch ?? ""}`;
  const textRendererScript = [
    "<script>",
    "  function diagramMarkupFor() { return ''; }",
    "  function diagramMarkupForFrame() { return ''; }",
    "  function drawMini() { return ''; }",
    "  function groupTitle(section) { return section; }",
    "</script>",
  ].join("\n");

  const html = replaceAll(template, {
    "{{PAGE_TITLE}}": esc(meta.pageTitle),
    "{{PAGE_DESCRIPTION}}": esc(meta.pageDescription ?? ""),
    "{{BREADCRUMB_TITLE}}": esc(meta.breadcrumbTitle ?? meta.pageTitle),
    "{{HOME_HREF}}": homeHref,
    "{{LIBRARY_HREF}}": libraryHref,
    "{{LIBRARY_LABEL}}": esc(meta.breadcrumbLabel ?? "高中知识章节"),
    "{{ASSET_PREFIX}}": assetPrefix,
    "{{PROBLEM_SUMMARY_HTML}}": "",
    "{{PROBLEM_FULL_HTML}}": buildProblemHtml(
      lesson.problem.lines,
      examSourceLabel(lesson.problem.source),
      answerTextForSchema(answerSchemaForLesson(root, meta.id)),
    ),
    "{{PROBLEM_KEY_POINTS_HTML}}": buildKeyPointsHtml(lesson.problem.keyPoints),
    "{{STEPS_JSON}}": JSON.stringify(lesson.steps),
    "{{POLICIES_JSON}}": JSON.stringify(lesson.policies ?? {}),
    "{{STEP_LABELS_JSON}}": JSON.stringify(lesson.stepLabels ?? {}),
    "{{GEOMETRY_SCRIPT}}": textRendererScript,
    'sliderLabel: "P 点 · t＝OP"': 'sliderLabel: "参数"',
    'paramLabelPrefix: "t="': 'paramLabelPrefix: ""',
    'goToProblemMode: "doubleScroll"': 'goToProblemMode: "doubleScroll"',
  });

  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, html, "utf8");
  return outputPath;
}

if (process.argv[1] && path.resolve(process.argv[1]) === currentFile) {
  const inputArg = process.argv[2];
  if (!inputArg) {
    console.error("用法: node tools/build-text-page.mjs internal/senior-high/lesson-specs/<problem-id>/");
    process.exitCode = 1;
  } else {
    try {
      console.log(`Wrote: ${buildTextPage(inputArg)}`);
    } catch (error) {
      console.error(error.message);
      process.exitCode = 1;
    }
  }
}
