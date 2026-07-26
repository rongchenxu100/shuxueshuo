#!/usr/bin/env node
/** Compile a senior-high function lesson spec into the shared lesson page shell. */
import fs from "fs";
import path from "path";
import { normalizeLessonSpec } from "./lib/lesson-normalizer.mjs";
import {
  buildKeyPointsHtml,
  renderInlineMathText,
  splitChoiceText,
} from "./lib/lesson-html.mjs";

function die(message) {
  console.error(message);
  process.exit(1);
}

function readJson(filePath) {
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch (error) {
    die("JSON 读取失败: " + filePath + "\n" + error.message);
  }
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
  const sourceHtml = source
    ? `<span class="problem-source-inline">（${esc(source)}）</span>`
    : "";
  if (line.figures != null) {
    const ariaAttr = line.ariaLabel ? ` aria-label="${esc(line.ariaLabel)}"` : "";
    const figures = (line.figures ?? []).map((figure) => {
      const figureAria = figure.ariaLabel
        ? ` aria-label="${esc(figure.ariaLabel)}"`
        : "";
      const titleHtml = figure.title
        ? `\n    <h3>${esc(figure.title)}</h3>`
        : "";
      const captionHtml = figure.caption
        ? `\n    <figcaption class="problem-figure-caption">${esc(figure.caption)}</figcaption>`
        : "";
      return `  <figure class="problem-figure">\n    <svg id="${esc(figure.id)}" viewBox="0 0 1080 760" role="img"${figureAria}></svg>${titleHtml}${captionHtml}\n  </figure>`;
    }).join("\n");
    return `<div class="problem-original-figures"${ariaAttr}>\n${figures}\n</div>`;
  }
  if (line.heading != null) {
    return `<div class="problem-line"><strong>${sourceHtml}${esc(line.heading)}</strong></div>`;
  }
  const choiceGroup = splitChoiceText(line.text);
  if (choiceGroup) {
    const answerHtml = line.answerId != null
      ? `<span class="answer-chip" id="${esc(line.answerId)}">${renderInlineMathText(line.answer)}</span>`
      : "";
    const optionsHtml = choiceGroup.options
      .map((option) =>
        `<div class="problem-option"><span class="problem-option-label">${option.label}.</span><span>${renderInlineMathText(option.text)}</span></div>`,
      )
      .join("");
    return [
      `<div class="problem-line"><span>${sourceHtml}${renderInlineMathText(choiceGroup.stem)}</span>${answerHtml}</div>`,
      `<div class="problem-options${choiceGroup.stacked ? " is-stacked" : ""}">${optionsHtml}</div>`,
    ].join("\n");
  }
  if (line.answerId != null) {
    return `<div class="problem-line"><span>${sourceHtml}${renderInlineMathText(line.text)}</span><span class="answer-chip" id="${esc(line.answerId)}">${renderInlineMathText(line.answer)}</span></div>`;
  }
  return `<div class="problem-line"><span>${sourceHtml}${renderInlineMathText(line.text ?? "")}</span></div>`;
}

function buildProblemHtml(lines, source) {
  if (!Array.isArray(lines)) return "";
  return lines
    .map((line, index) => buildProblemLineHtml(line, index === 0 ? source : undefined))
    .join("\n");
}

function buildProblemSummaryHtml(summary) {
  if (!summary) return "";
  return `<div class="problem-summary-text">${renderInlineMathText(summary)}</div>`;
}

function buildLegendHtml(legend) {
  if (!Array.isArray(legend)) return "";
  return legend.map((item) =>
    `<span><i class="sw" style="background:var(--${esc(item.colorVar)})"></i>${esc(item.label)}</span>`,
  ).join("");
}

function browserPath(filePath) {
  return filePath.split(path.sep).join("/");
}

function assetPrefixForOutput(repoRoot, outputPath) {
  const relative = path.relative(path.dirname(outputPath), path.join(repoRoot, "site", "assets"));
  const normalized = browserPath(relative || ".");
  return normalized.startsWith(".") ? normalized : "./" + normalized;
}

function hrefForOutput(repoRoot, outputPath, targetPath) {
  const relative = path.relative(path.dirname(outputPath), path.resolve(repoRoot, targetPath));
  const normalized = browserPath(relative || ".");
  return normalized.startsWith(".") ? normalized : "./" + normalized;
}

const inputArg = process.argv[2];
if (!inputArg) {
  die("用法: node tools/build-function-page.mjs internal/senior-high/lesson-specs/<problem-id>/");
}

const repoRoot = path.resolve(process.cwd());
const inputDir = path.resolve(inputArg);
const specPath = path.join(inputDir, "function-spec.json");
const decorationsPath = path.join(inputDir, "function-decorations.json");
const lessonPath = path.join(inputDir, "lesson-data.json");
const presetPath = path.join(repoRoot, "internal/config/style-presets.json");
for (const requiredPath of [specPath, decorationsPath, lessonPath, presetPath]) {
  if (!fs.existsSync(requiredPath)) die("缺少: " + requiredPath);
}

const rawSpec = readJson(specPath);
const rawDecorations = readJson(decorationsPath);
const rawLessonData = readJson(lessonPath);
const stylePresets = readJson(presetPath);
const normalized = normalizeLessonSpec({
  geometrySpec: rawSpec,
  stepDecorations: rawDecorations,
  lessonData: rawLessonData,
  stylePresets,
});
const functionSpec = normalized.geometrySpec;
const decorations = normalized.stepDecorations;
const lessonData = normalized.lessonData;

const templatePath = path.join(repoRoot, "internal/templates/interactive-problem-page.template.html");
if (!fs.existsSync(templatePath)) die("缺少模板: " + templatePath);
const template = fs.readFileSync(templatePath, "utf8");
const meta = lessonData.meta ?? {};
const problem = lessonData.problem ?? {};
const ui = lessonData.ui ?? {};
const linkedParameter = ui.linkedParameter;
if (!meta.outputPath) die("lesson-data.json 缺少 meta.outputPath");
if (!meta.pageTitle) die("lesson-data.json 缺少 meta.pageTitle");
if (!Array.isArray(problem.lines)) die("lesson-data.json 缺少 problem.lines");

const outputPath = path.resolve(repoRoot, meta.outputPath);
const assetPrefix = assetPrefixForOutput(repoRoot, outputPath);
const homeHref = hrefForOutput(repoRoot, outputPath, "site/index.html");
const libraryHref = hrefForOutput(
  repoRoot,
  outputPath,
  meta.breadcrumbPath ?? "site/nav/index.html",
);
const functionTag = `<script type="application/json" id="functionSpec">${JSON.stringify(functionSpec)}</script>`;
const injectedScript = [
  functionTag,
  `<script src="${assetPrefix}/js/math-expression-engine.js"></script>`,
  `<script src="${assetPrefix}/js/function-lesson-from-spec.js?v=2"></script>`,
  "",
  "<script>",
  "  const __FUNCTION_SPEC__ = JSON.parse(document.getElementById('functionSpec').textContent);",
  "  const __FUNCTION_DECORATIONS__ = " + JSON.stringify(decorations) + ";",
  "  const renderer = FunctionLessonFromSpec.createSpecRenderer(__FUNCTION_SPEC__, __FUNCTION_DECORATIONS__, STEPS, POLICIES);",
  "  function groupTitle(section) {",
  "    const map = " + JSON.stringify(ui.groupTitles ?? {}) + ";",
  "    return Object.prototype.hasOwnProperty.call(map, section) ? map[section] : section;",
  "  }",
  "  var diagramMarkupFor = renderer.diagramMarkupFor;",
  "  var diagramMarkupForFrame = renderer.diagramMarkupForFrame;",
  "  var drawMini = renderer.drawMini;",
  "  var __LESSON_LEGEND_HTML__ = " + JSON.stringify(buildLegendHtml(ui.legend ?? [])) + ";",
  linkedParameter
    ? "  __LESSON_PARAM_LABEL_FORMATTER__ = function (_index, value, localVars, baseLabel) {\n" +
      "    const state = renderer.resolveStateFor(value, localVars);\n" +
      "    const linkedValue = state.env[" + JSON.stringify(linkedParameter.name) + "];\n" +
      "    if (!Number.isFinite(linkedValue)) return baseLabel;\n" +
      "    const rounded = Number(linkedValue.toFixed(" + Number(linkedParameter.precision ?? 2) + "));\n" +
      "    return baseLabel + '　' + " + JSON.stringify(linkedParameter.label) + " + rounded;\n" +
      "  };"
    : "",
  "  var __AFTER_RENDER_ALL_STEPS__ = renderer.renderOriginalFigures;",
  "</script>",
].join("\n");

const html = replaceAll(template, {
  "{{PAGE_TITLE}}": meta.pageTitle,
  "{{PAGE_DESCRIPTION}}": meta.pageDescription ?? "",
  "{{BREADCRUMB_TITLE}}": meta.breadcrumbTitle ?? meta.pageTitle,
  "{{HOME_HREF}}": homeHref,
  "{{LIBRARY_HREF}}": libraryHref,
  "{{LIBRARY_LABEL}}": meta.breadcrumbLabel ?? "题库导航",
  "{{ASSET_PREFIX}}": assetPrefix,
  "{{PROBLEM_SUMMARY_HTML}}": buildProblemSummaryHtml(problem.summary),
  "{{PROBLEM_FULL_HTML}}": buildProblemHtml(problem.lines, problem.source),
  "{{PROBLEM_KEY_POINTS_HTML}}": buildKeyPointsHtml(problem.keyPoints),
  "{{STEPS_JSON}}": JSON.stringify(lessonData.steps ?? []),
  "{{POLICIES_JSON}}": JSON.stringify(lessonData.policies ?? {}),
  "{{STEP_LABELS_JSON}}": JSON.stringify(lessonData.stepLabels ?? {}),
  "{{GEOMETRY_SCRIPT}}": injectedScript,
  'sliderLabel: "P 点 · t＝OP"': `sliderLabel: ${JSON.stringify(ui.sliderLabel ?? "参数 t")}`,
  'paramLabelPrefix: "t="': `paramLabelPrefix: ${JSON.stringify(ui.paramLabelPrefix ?? "t=")}`,
  'goToProblemMode: "doubleScroll"': `goToProblemMode: ${JSON.stringify(ui.goToProblemMode ?? "doubleScroll")}`,
});

fs.mkdirSync(path.dirname(outputPath), { recursive: true });
fs.writeFileSync(outputPath, html, "utf8");
console.log("Wrote:", outputPath);
