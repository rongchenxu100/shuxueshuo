#!/usr/bin/env node
/**
 * 将 internal/lesson-specs/<problem-id>/ 下的声明式 JSON 编译成题页 HTML。
 *
 * 输入目录应包含：
 * - geometry-spec.json
 * - step-decorations.json
 * - lesson-data.json
 *
 * 用法：
 *   node tools/build-lesson-page.mjs internal/lesson-specs/tj-2026-nankai-yimo-24/
 */
import fs from "fs";
import path from "path";

function die(msg) {
  console.error(msg);
  process.exit(1);
}

function readJson(p) {
  try {
    return JSON.parse(fs.readFileSync(p, "utf8"));
  } catch (e) {
    die("JSON 读取失败: " + p + "\n" + e.message);
  }
}

function replaceAll(template, map) {
  return Object.keys(map).reduce((s, key) => s.split(key).join(map[key]), template);
}

function ensureDirForFile(filePath) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
}

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/**
 * 把 problem.lines 数组编译成 HTML 字符串。
 * 支持四种行类型：普通文字行 / 带答案chip行 / 粗体小标题行 / 原题图形组。
 */
function buildProblemHtml(lines) {
  if (!Array.isArray(lines)) return "";
  return lines.map(line => {
    if (line.figures != null) {
      const ariaAttr = line.ariaLabel ? ` aria-label="${esc(line.ariaLabel)}"` : "";
      const figs = (line.figures ?? []).map(fig => {
        const figAria = fig.ariaLabel ? ` aria-label="${esc(fig.ariaLabel)}"` : "";
        const captionHtml = fig.caption
          ? `\n    <figcaption class="problem-figure-caption">${esc(fig.caption)}</figcaption>`
          : "";
        return `  <figure class="problem-figure">\n    <svg id="${fig.id}" viewBox="0 0 1080 760" role="img"${figAria}></svg>\n    <h3>${esc(fig.title)}</h3>${captionHtml}\n  </figure>`;
      }).join("\n");
      return `<div class="problem-original-figures"${ariaAttr}>\n${figs}\n</div>`;
    }
    if (line.heading != null) {
      return `<div class="problem-line"><strong>${esc(line.heading)}</strong></div>`;
    }
    if (line.answerId != null) {
      return `<div class="problem-line"><span>${esc(line.text)}</span><span class="answer-chip" id="${line.answerId}">${esc(line.answer)}</span></div>`;
    }
    return `<div class="problem-line"><span>${esc(line.text ?? "")}</span></div>`;
  }).join("\n");
}

/**
 * 把 ui.legend 数组编译成 legendHtml 字符串。
 * colorVar 映射到 CSS 变量 --{colorVar}，如 paper → var(--paper)。
 */
function buildLegendHtml(legend) {
  if (!Array.isArray(legend)) return "";
  return legend.map(item =>
    `<span><i class="sw" style="background:var(--${item.colorVar})"></i>${esc(item.label)}</span>`
  ).join("");
}

const inputDirArg = process.argv[2];
if (!inputDirArg) {
  die("用法: node tools/build-lesson-page.mjs internal/lesson-specs/<problem-id>/");
}

const repoRoot = path.resolve(process.cwd());
const inputDir = path.resolve(inputDirArg);
const geoPath = path.join(inputDir, "geometry-spec.json");
const decoPath = path.join(inputDir, "step-decorations.json");
const dataPath = path.join(inputDir, "lesson-data.json");

if (!fs.existsSync(geoPath)) die("缺少: " + geoPath);
if (!fs.existsSync(decoPath)) die("缺少: " + decoPath);
if (!fs.existsSync(dataPath)) die("缺少: " + dataPath);

const geometrySpec = readJson(geoPath);
const stepDecorations = readJson(decoPath);
const lessonData = readJson(dataPath);

const tmplPath = path.join(repoRoot, "internal/templates/interactive-problem-page.template.html");
if (!fs.existsSync(tmplPath)) die("缺少模板: " + tmplPath);
const template = fs.readFileSync(tmplPath, "utf8");

const meta = lessonData.meta || {};
const problem = lessonData.problem || {};
const ui = lessonData.ui || {};

if (!meta.outputPath) die("lesson-data.json 缺少 meta.outputPath");
if (!meta.pageTitle)   die("lesson-data.json 缺少 meta.pageTitle");
if (!problem.lines && !problem.fullHtml) die("lesson-data.json 缺少 problem.lines（或旧版 problem.fullHtml）");

const problemFullHtml = problem.fullHtml ?? buildProblemHtml(problem.lines);
const legendHtmlStr   = ui.legendHtml    ?? buildLegendHtml(ui.legend ?? []);

// 将 JSON 数据转为模板所需 JS 常量
const stepsJson = JSON.stringify(lessonData.steps ?? []);
const policiesJson = JSON.stringify(lessonData.policies ?? {});
const stepLabelsJson = JSON.stringify(lessonData.stepLabels ?? {});

// 将 geometry-spec 放入 application/json，decorations 直接内联为 JS 常量（避免双层 JSON.parse 丢失精度/转义）。
const geometrySpecTag = `<script type="application/json" id="geometrySpec">${JSON.stringify(
  geometrySpec
)}</script>`;

const geometryScript = [
  geometrySpecTag,
  `<script src="../../../assets/js/geometry-engine.js"></script>`,
  `<script src="../../../assets/js/geometry-lesson-from-spec.js"></script>`,
  "",
  "<script>",
  "  const __GEOMETRY_SPEC__ = JSON.parse(document.getElementById('geometrySpec').textContent);",
  "  const __STEP_DECORATIONS__ = " + JSON.stringify(stepDecorations) + ";",
  "  const renderer = GeometryLessonFromSpec.createSpecRenderer(__GEOMETRY_SPEC__, __STEP_DECORATIONS__, STEPS, POLICIES);",
  "  function groupTitle(section) {",
  "    const map = " + JSON.stringify(ui.groupTitles ?? {}) + ";",
  "    return map[section] || section;",
  "  }",
  "  var diagramMarkupFor = renderer.diagramMarkupFor;",
  "  var drawMini = renderer.drawMini;",
  "  var __LESSON_LEGEND_HTML__ = " + JSON.stringify(legendHtmlStr) + ";",
  "  // 原题图形渲染：由 renderer 负责（可选）",
  "  var __AFTER_RENDER_ALL_STEPS__ = renderer.renderOriginalFigures;",
  "</script>"
].join("\n");

// 注意：模板自己已加载 geometry-label-layout/interactive-lesson-ui/lesson-page-runtime
// 我们只把几何相关脚本和 renderer glue 注入 {{GEOMETRY_SCRIPT}}。
const html = replaceAll(template, {
  "{{PAGE_TITLE}}": meta.pageTitle,
  "{{PAGE_DESCRIPTION}}": meta.pageDescription ?? "",
  "{{BREADCRUMB_TITLE}}": meta.breadcrumbTitle ?? meta.pageTitle,
  "{{PROBLEM_SUMMARY}}": problem.summary ?? "",
  "{{PROBLEM_FULL_HTML}}": problemFullHtml,
  "{{STEPS_JSON}}": stepsJson,
  "{{POLICIES_JSON}}": policiesJson,
  "{{STEP_LABELS_JSON}}": stepLabelsJson,
  "{{GEOMETRY_SCRIPT}}": geometryScript,
  // slider/label 等 UI 字段来自 lesson-data.ui（覆盖模板默认值）
  'sliderLabel: "P 点 · t＝OP"':       `sliderLabel: ${JSON.stringify(ui.sliderLabel ?? "P 点 · t＝OP")}`,
  'paramLabelPrefix: "t="':            `paramLabelPrefix: ${JSON.stringify(ui.paramLabelPrefix ?? "t=")}`,
  'goToProblemMode: "doubleScroll"':   `goToProblemMode: ${JSON.stringify(ui.goToProblemMode ?? "doubleScroll")}`,
});

const outPath = path.resolve(repoRoot, meta.outputPath);
ensureDirForFile(outPath);
fs.writeFileSync(outPath, html, "utf8");
console.log("Wrote:", outPath);

