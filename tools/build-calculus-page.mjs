#!/usr/bin/env node
/** Compile a senior-high calculus lesson spec into the shared lesson page shell. */
import fs from "fs";
import path from "path";
import { normalizeLessonSpec } from "./lib/lesson-normalizer.mjs";

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

function buildProblemHtml(lines) {
  if (!Array.isArray(lines)) return "";
  return lines.map((line) => {
    if (line.heading != null) {
      return `<div class="problem-line"><strong>${esc(line.heading)}</strong></div>`;
    }
    if (line.answerId != null) {
      return `<div class="problem-line"><span>${esc(line.text)}</span><span class="answer-chip" id="${esc(line.answerId)}">${esc(line.answer)}</span></div>`;
    }
    return `<div class="problem-line"><span>${esc(line.text ?? "")}</span></div>`;
  }).join("\n");
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
  die("用法: node tools/build-calculus-page.mjs internal/senior-high/lesson-specs/<problem-id>/");
}

const repoRoot = path.resolve(process.cwd());
const inputDir = path.resolve(inputArg);
const specPath = path.join(inputDir, "calculus-spec.json");
const decorationsPath = path.join(inputDir, "calculus-decorations.json");
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
const calculusSpec = normalized.geometrySpec;
const decorations = normalized.stepDecorations;
const lessonData = normalized.lessonData;

const templatePath = path.join(repoRoot, "internal/templates/interactive-problem-page.template.html");
if (!fs.existsSync(templatePath)) die("缺少模板: " + templatePath);
const template = fs.readFileSync(templatePath, "utf8");
const meta = lessonData.meta ?? {};
const problem = lessonData.problem ?? {};
const ui = lessonData.ui ?? {};
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
const calculusTag = `<script type="application/json" id="calculusSpec">${JSON.stringify(calculusSpec)}</script>`;
const injectedScript = [
  calculusTag,
  `<script src="${assetPrefix}/js/math-expression-engine.js"></script>`,
  `<script src="${assetPrefix}/js/calculus-lesson-from-spec.js"></script>`,
  "",
  "<script>",
  "  const __CALCULUS_SPEC__ = JSON.parse(document.getElementById('calculusSpec').textContent);",
  "  const __CALCULUS_DECORATIONS__ = " + JSON.stringify(decorations) + ";",
  "  const renderer = CalculusLessonFromSpec.createSpecRenderer(__CALCULUS_SPEC__, __CALCULUS_DECORATIONS__, STEPS, POLICIES);",
  "  function groupTitle(section) {",
  "    const map = " + JSON.stringify(ui.groupTitles ?? {}) + ";",
  "    return map[section] || section;",
  "  }",
  "  var diagramMarkupFor = renderer.diagramMarkupFor;",
  "  var diagramMarkupForFrame = renderer.diagramMarkupForFrame;",
  "  var drawMini = renderer.drawMini;",
  "  var __LESSON_LEGEND_HTML__ = " + JSON.stringify(buildLegendHtml(ui.legend ?? [])) + ";",
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
  "{{PROBLEM_SUMMARY}}": problem.summary ?? "",
  "{{PROBLEM_FULL_HTML}}": buildProblemHtml(problem.lines),
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
