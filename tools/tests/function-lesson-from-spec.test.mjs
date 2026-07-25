import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import test from "node:test";
import vm from "node:vm";

import { validateFunctionLesson } from "../validate-function-spec.mjs";
import { validateFunctionBatch } from "../validate-senior-high-function-batch.mjs";
import { renderInlineMathText } from "../lib/lesson-html.mjs";
import { repoRoot } from "./calculus-test-helpers.mjs";

function loadRuntime() {
  const sandbox = { window: {}, console, Math };
  vm.createContext(sandbox);
  for (const relativePath of [
    "site/assets/js/math-expression-engine.js",
    "site/assets/js/function-lesson-from-spec.js",
  ]) {
    vm.runInContext(fs.readFileSync(path.join(repoRoot, relativePath), "utf8"), sandbox);
  }
  return sandbox.window.FunctionLessonFromSpec;
}

function loadLessonPageRuntime() {
  const sandbox = { window: {}, console, Math };
  vm.createContext(sandbox);
  vm.runInContext(
    fs.readFileSync(path.join(repoRoot, "site/assets/js/lesson-page-runtime.js"), "utf8"),
    sandbox,
  );
  return sandbox.window.LessonPageRuntime;
}

function readLesson(problemId, fileName) {
  return JSON.parse(fs.readFileSync(path.join(
    repoRoot,
    "internal/senior-high/lesson-specs",
    problemId,
    fileName,
  ), "utf8"));
}

const runtime = loadRuntime();
const lessonPageRuntime = loadLessonPageRuntime();

test("lesson text renders inline subscripts and subset relations", () => {
  assert.equal(
    lessonPageRuntime.renderFormulaText("实际值域 \\(R_A=[0,2]\\subseteq B\\)"),
    '实际值域 <span class="inline-math">R<sub>A</sub>=[0,2]⊆ B</span>',
  );
  assert.equal(
    lessonPageRuntime.renderFormulaText("\\(R_C\\nsubseteq B\\)"),
    '<span class="inline-math">R<sub>C</sub>⊄ B</span>',
  );
  assert.equal(
    lessonPageRuntime.renderFormulaText("函数 e^(x)"),
    '函数 <span class="derive-inline-power">e<sup>x</sup></span>',
  );
  assert.equal(
    lessonPageRuntime.renderFormulaText("\\(f(x)=\\frac{\\sqrt{3x+11}}{x}\\)"),
    '<span class="inline-math">f(x)=<span class="math-fraction"><span class="math-numerator"><span class="math-radical"><span class="math-radical-symbol">√</span><span class="math-radicand">3x+11</span></span></span><span class="math-denominator">x</span></span></span>',
  );
  assert.equal(
    lessonPageRuntime.renderFormulaText("\\(y=\\frac{2x}{3}\\)"),
    '<span class="inline-math">y=<span class="math-fraction"><span class="math-numerator">2x</span><span class="math-denominator">3</span></span></span>',
  );
  assert.equal(
    lessonPageRuntime.renderFormulaText("\\(2x^3+x^2+(x+1)^{2}\\)"),
    '<span class="inline-math">2x<sup>3</sup>+x<sup>2</sup>+(x+1)<sup>2</sup></span>',
  );
  assert.equal(
    renderInlineMathText("\\(2x^3+x^2+(x+1)^{2}\\)"),
    '<span class="inline-math">2x<sup>3</sup>+x<sup>2</sup>+(x+1)<sup>2</sup></span>',
  );
});

test("validates all eleven high-school function lessons", () => {
  for (const questionNumber of Array.from({ length: 11 }, (_, index) => String(index + 1).padStart(2, "0"))) {
    const problemId = `function-concepts-20260722-q${questionNumber}`;
    assert.doesNotThrow(() => validateFunctionLesson(path.join(
      repoRoot,
      "internal/senior-high/lesson-specs",
      problemId,
    )));
  }
});

test("all eleven compiled function pages exist", () => {
  const expectedSources = [
    "2026 江苏苏州实验中学期中",
    "教材习题改编",
    "2026 江西抚州期中",
    "2026 河北沧州期末",
    "教材基础过关练",
    "2026 四川成都实验外月考",
    "2026 北京八一学校月考",
    "2026 四川成都双流立格实验学校月考",
    "2026 山东淄博实验中学月考",
    "2026 四川巴中第三中学期中",
    "2026 河南名校期中大联考",
  ];
  for (const questionNumber of Array.from({ length: 11 }, (_, index) => String(index + 1).padStart(2, "0"))) {
    const htmlPath = path.join(
      repoRoot,
      `site/problems/senior-high/functions/function-concepts-and-representation/function-concepts-20260722-q${questionNumber}.html`,
    );
    assert.equal(fs.existsSync(htmlPath), true);
    const html = fs.readFileSync(htmlPath, "utf8");
    assert.match(html, /FunctionLessonFromSpec\.createSpecRenderer/);
    assert.doesNotMatch(html, /"(?:NaN|Infinity|undefined)"/);
    assert.doesNotMatch(html, /problem-summary-text/);
    assert.match(
      html,
      new RegExp(`<span class="problem-source-inline">（${expectedSources[Number(questionNumber) - 1]}）</span>`),
    );
    assert.doesNotMatch(html, /class="problem-source"/);
    assert.match(
      html,
      /<button id="problemToggle"[\s\S]*?<div class="problem-full">[\s\S]*?<div class="problem-line"><span><span class="problem-source-inline">/,
    );
  }
});

test("context-domain lesson is finalized and keeps the function domain in its answer", () => {
  const lessonDir = path.join(
    repoRoot,
    "internal/senior-high/lesson-specs/function-concepts-20260722-q06",
  );
  const lessonData = JSON.parse(
    fs.readFileSync(path.join(lessonDir, "lesson-data.json"), "utf8"),
  );
  const answer = lessonData.problem.lines[0].answer;

  assert.doesNotMatch(lessonData.meta.pageDescription, /待复核|草稿/);
  assert.doesNotMatch(lessonData.meta.breadcrumbTitle, /待复核|草稿/);
  assert.doesNotMatch(answer, /待复核|草稿/);
  assert.match(answer, /S=−x²\+40x（0<x<40）/);
  assert.match(answer, /12≤x≤28/);
});

test("collapsed problem keeps the first problem line visible", () => {
  const stylesheet = fs.readFileSync(
    path.join(repoRoot, "site/assets/css/interactive-geometry-page.css"),
    "utf8",
  );

  assert.match(
    stylesheet,
    /\.problem\.collapsed \.problem-full > :not\(\.problem-line:first-child\) \{\s*display: none;\s*\}/,
  );
  assert.match(
    stylesheet,
    /\.problem\.collapsed \.problem-full > \.problem-line:first-child \{\s*display: flex;\s*\}/,
  );
  assert.doesNotMatch(
    stylesheet,
    /\.problem\.collapsed \.problem-full \{\s*display: none;\s*\}/,
  );
});

test("validator rejects overlapping domains and unknown decoration references", () => {
  const sourceDir = path.join(repoRoot, "internal/senior-high/lesson-specs/function-concepts-20260722-q11");
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "function-lesson-invalid-"));
  fs.cpSync(sourceDir, tempDir, { recursive: true });
  try {
    const specPath = path.join(tempDir, "function-spec.json");
    const spec = JSON.parse(fs.readFileSync(specPath, "utf8"));
    spec.panels[0].function.intervals.push({ min: 1, max: 2.2 });
    fs.writeFileSync(specPath, JSON.stringify(spec), "utf8");
    assert.throws(() => validateFunctionLesson(tempDir), /重叠区间/);

    spec.panels[0].function.intervals = [{ min: 0.5, max: 2 }];
    fs.writeFileSync(specPath, JSON.stringify(spec), "utf8");
    const decorationsPath = path.join(tempDir, "function-decorations.json");
    const decorations = JSON.parse(fs.readFileSync(decorationsPath, "utf8"));
    decorations.steps.s1.highlightElementIds = ["missing"];
    fs.writeFileSync(decorationsPath, JSON.stringify(decorations), "utf8");
    assert.throws(() => validateFunctionLesson(tempDir), /未知 element/);
  } finally {
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
});

test("function-concept lesson highlights the A-domain segment on the full curve", () => {
  const id = "function-concepts-20260722-q01";
  const spec = readLesson(id, "function-spec.json");
  const decorations = readLesson(id, "function-decorations.json");
  const lesson = readLesson(id, "lesson-data.json");
  const renderer = runtime.createSpecRenderer(spec, decorations, lesson.steps, lesson.policies);
  const invalid = renderer.diagramMarkupFor(2, 4, {});
  assert.match(invalid, /C　y=<tspan[^>]*>2x<\/tspan><tspan[^>]*>3<\/tspan>/);
  assert.match(invalid, /唯一交点/);
  assert.match(invalid, /stroke="#a1a1aa"/);
  assert.match(invalid, /stroke="#0f766e"/);
  assert.doesNotMatch(invalid, /实际值域 R 与集合 B 比较/);
  assert.doesNotMatch(invalid, /从 A 到 B 的函数必须同时满足/);
  assert.doesNotMatch(invalid, /R_C=\[0,8\/3\]/);
  const derivation = lesson.steps[2].derive.flat().join(" ");
  assert.match(derivation, /R_C=\[0,\\frac\{8\}\{3\}\]/);
  assert.match(lessonPageRuntime.renderFormulaText(derivation), /R<sub>C<\/sub>⊄ B/);
  assert.doesNotMatch(invalid, /NaN|Infinity|undefined/);
  const radical = renderer.diagramMarkupFor(3, 2, {});
  assert.match(radical, /√<tspan text-decoration="overline">x<\/tspan>/);
});

test("same-function lesson stays textual and uses correspondence terminology", () => {
  const lessonId = "function-concepts-20260722-q02";
  const lesson = readLesson(lessonId, "lesson-data.json");
  assert.equal(lesson.steps.every((step) => step.showDiagram === false), true);
  assert.doesNotMatch(JSON.stringify(lesson), /对应法则/);
  assert.match(JSON.stringify(lesson), /对应关系/);

  const html = fs.readFileSync(path.join(
    repoRoot,
    "site/problems/senior-high/functions/function-concepts-and-representation/function-concepts-20260722-q02.html",
  ), "utf8");
  assert.doesNotMatch(html, /step-card-diagram/);
});

test("radical-domain page compiles a vinculum over the full radicand", () => {
  const html = fs.readFileSync(path.join(
    repoRoot,
    "site/problems/senior-high/functions/function-concepts-and-representation/function-concepts-20260722-q05.html",
  ), "utf8");
  assert.match(html, /class="math-numerator"><span class="math-radical"/);
  assert.match(html, /class="math-radicand">3x\+11<\/span>/);
  assert.match(html, /class="math-denominator">x<\/span>/);
  assert.doesNotMatch(html, /f\(x\)=√\(3x\+11\)\/x/);
});

test("function-concept page places concise key points before the solution steps", () => {
  const html = fs.readFileSync(path.join(
    repoRoot,
    "site/problems/senior-high/functions/function-concepts-and-representation/function-concepts-20260722-q01.html",
  ), "utf8");
  const tipsIndex = html.indexOf('class="lesson-key-points"');
  const stepsIndex = html.indexOf('id="stepCards"');
  assert.ok(tipsIndex > 0 && tipsIndex < stepsIndex);
  assert.match(html, /对任意 x∈A，都有且只有一个确定的 y/);
  assert.match(html, /实际值域 <span class="inline-math">R<sub>f<\/sub>⊆ B<\/span>/);
});

test("domain lesson renders closed radical endpoint and excluded zero", () => {
  const id = "function-concepts-20260722-q05";
  const spec = readLesson(id, "function-spec.json");
  const decorations = readLesson(id, "function-decorations.json");
  const lesson = readLesson(id, "lesson-data.json");
  assert.equal(lesson.steps.length, 2);
  assert.equal(lessonPageRuntime.stepHasDiagram(lesson.steps[0]), false);
  assert.equal(lessonPageRuntime.stepHasDiagram(lesson.steps[1]), true);
  const renderer = runtime.createSpecRenderer(spec, decorations, lesson.steps, lesson.policies);
  const firstMarkup = renderer.diagramMarkupFor(0, 0, {});
  const finalMarkup = renderer.diagramMarkupFor(1, 0, {});
  assert.doesNotMatch(finalMarkup, /^<svg[\s>]/);
  assert.doesNotMatch(finalMarkup, /<\/svg>$/);
  assert.doesNotMatch(firstMarkup, /定义域约束|在数轴上合并约束/);
  assert.match(finalMarkup, /\[-<tspan/);
  assert.match(finalMarkup, /text-decoration="underline">11<\/tspan>/);
  assert.match(finalMarkup, />3<\/tspan>,0\)/);
  assert.match(finalMarkup, /0 不可取/);
  assert.match(finalMarkup, /fill="#fff" stroke="#dc2626"/);
  assert.match(finalMarkup, /l-14,-9 v18 z/);
  assert.doesNotMatch(finalMarkup, /NaN|Infinity|undefined/);
});

test("range lesson uses interval transforms and reserves the graph for verification", () => {
  const id = "function-concepts-20260722-q11";
  const spec = readLesson(id, "function-spec.json");
  const decorations = readLesson(id, "function-decorations.json");
  const lesson = readLesson(id, "lesson-data.json");
  assert.equal(runtime.resolveState(spec, 0.5, {}).env.fValue, -1 / 3);
  assert.equal(runtime.resolveState(spec, 2, {}).env.fValue, 1 / 3);
  assert.equal(lesson.problem.keyPoints.title, "方法技巧");
  assert.match(lesson.problem.keyPoints.lead, /\\frac\{ax\+b\}\{cx\+d\}/);
  assert.equal(lesson.steps[0].title, "第1步：分离常数，找出反比例结构");
  assert.match(lesson.steps[2].title, /确定 \\\(-\\frac\{2\}\{x\+1\}\\\) 的取值范围/);
  assert.match(lesson.stepLabels.s3, /\\frac\{2\}\{x\+1\}/);
  assert.equal(lesson.steps[3].title, "第4步：加上常数，确定函数值域");
  assert.equal(lesson.stepLabels.s4, "4 加上常数，确定函数值域");
  assert.equal(lesson.policies.s4.movable, true);
  assert.deepEqual(lesson.policies.s4.range, [0.5, 2]);
  assert.deepEqual(lesson.steps.map(lessonPageRuntime.stepHasDiagram), [false, false, false, true]);
  assert.match(lesson.steps[2].derive.flat().join(" "), /\\frac\{1\}\{3\}≤\\frac\{1\}\{x\+1\}≤\\frac\{2\}\{3\}/);
  assert.match(lesson.steps[2].derive.flat().join(" "), /-\\frac\{4\}\{3\}≤-\\frac\{2\}\{x\+1\}≤-\\frac\{2\}\{3\}/);
  const renderer = runtime.createSpecRenderer(spec, decorations, lesson.steps, lesson.policies);
  const finalMarkup = renderer.diagramMarkupFor(3, 1.25, {});
  assert.match(finalMarkup, /y=f\(x\)=<tspan[^>]*>x-1<\/tspan><tspan[^>]*>1\+x<\/tspan>/);
  assert.match(finalMarkup, /fill="#ede9fe" opacity="0\.35"/);
  assert.match(finalMarkup, /text-decoration="underline">1<\/tspan><tspan[^>]*>2<\/tspan>/);
  assert.match(finalMarkup, /stroke="#0f766e" stroke-width="1\.5" stroke-dasharray="6 5" opacity="0\.55"/);
  assert.match(finalMarkup, /stroke="#7c3aed" stroke-width="2" stroke-dasharray="6 5"/);
  assert.doesNotMatch(finalMarkup, /NaN|Infinity|undefined/);
});

test("renderer supports relation plots, finite tables and context geometry", () => {
  const spec = {
    version: 1,
    id: "synthetic",
    panels: [
      { id: "r", kind: "relationPlot", title: "关系图", viewport: { x: 0, y: 0, width: 0.33, height: 1 }, domain: { minX: 0, maxX: 2, minY: 0, maxY: 2 }, points: [{ id: "p", x: 1, y: 1 }] },
      { id: "t", kind: "valueTable", title: "值表", viewport: { x: 0.34, y: 0, width: 0.32, height: 1 }, columns: ["n", "G(n)"], rows: [{ id: "row", cells: ["1", "3"] }] },
      { id: "g", kind: "contextGeometry", title: "情境", viewport: { x: 0.67, y: 0, width: 0.33, height: 1 }, geometry: { points: [{ id: "a", x: 0, y: 1 }, { id: "b", x: 0.5, y: 0 }, { id: "c", x: 1, y: 1 }], polygons: [{ id: "triangle", pointIds: ["a", "b", "c"] }] } },
    ],
  };
  const steps = [{ id: "s", title: "综合面板" }];
  const renderer = runtime.createSpecRenderer(spec, { steps: { s: {} } }, steps, {});
  const markup = renderer.diagramMarkupFor(0, 1, {});
  assert.match(markup, /关系图/);
  assert.match(markup, /G\(n\)/);
  assert.match(markup, /<polygon/);
  assert.doesNotMatch(markup, /NaN|Infinity|undefined/);
});

test("relation plots expose vertical-test intersections", () => {
  const spec = {
    version: 1,
    id: "relation-test",
    parameter: { name: "x", initial: 1 },
    panels: [{
      id: "relation",
      kind: "relationPlot",
      title: "竖线检验",
      viewport: { x: 0, y: 0, width: 1, height: 1 },
      domain: { minX: 0, maxX: 2, minY: 0, maxY: 2 },
      segments: [
        { id: "upper", x1: 0, y1: 1, x2: 2, y2: 2 },
        { id: "lower", x1: 0, y1: 1, x2: 2, y2: 0 },
      ],
    }],
  };
  const steps = [{ id: "s", title: "检查" }];
  const renderer = runtime.createSpecRenderer(spec, { steps: { s: { showVerticalTest: true } } }, steps, {});
  const markup = renderer.diagramMarkupFor(0, 1, {});
  assert.match(markup, /2 个交点/);
  assert.match(markup, /stroke="#f59e0b" stroke-width="3" stroke-dasharray="8 6"/);
});

test("relation plots reuse the textbook figure for the problem and teaching step", () => {
  const relationId = "function-concepts-20260722-q03";
  const spec = readLesson(relationId, "function-spec.json");
  const lesson = readLesson(relationId, "lesson-data.json");
  const renderer = runtime.createSpecRenderer(
    spec,
    readLesson(relationId, "function-decorations.json"),
    lesson.steps,
    lesson.policies,
  );
  const originalMarkup = renderer.originalFigureMarkupFor("relation-1");
  const stepMarkup = renderer.diagramMarkupFor(0, 1.5, {});
  assert.match(originalMarkup, /stroke="#334155" stroke-width="4"/);
  assert.match(originalMarkup, /stroke-dasharray="8 7"/);
  assert.match(originalMarkup, /font-size="34" fill="#475569">1<\/text>/);
  assert.match(originalMarkup, /font-size="34" fill="#475569">2<\/text>/);
  assert.doesNotMatch(originalMarkup, /个交点|#f59e0b/);
  assert.match(stepMarkup, /stroke="#334155" stroke-width="4"/);
  assert.match(stepMarkup, /0 个交点/);
  assert.equal(lesson.problem.lines[1].figures.length, 4);
  assert.match(lesson.problem.keyPoints.items[0], /都有且只有一个确定的 y/);
  assert.match(lesson.problem.keyPoints.items[1], /R_f\\subseteq N/);
  assert.match(lesson.steps[0].derive[2][1], /R_\{①\}=\[0,2\]\\subseteq N/);
  assert.match(lesson.steps[3].derive[2][1], /R_\{④\}=\[0,2\]\\subseteq N/);
  assert.deepEqual(lesson.stepLabels, {
    s1: "1 检查图①",
    s2: "2 检查图②",
    s3: "3 检查图③",
    s4: "4 检查图④并作答",
  });
});

test("remaining draft lessons expose their intended visual interaction", () => {
  const relationId = "function-concepts-20260722-q03";
  const relationRenderer = runtime.createSpecRenderer(
    readLesson(relationId, "function-spec.json"),
    readLesson(relationId, "function-decorations.json"),
    readLesson(relationId, "lesson-data.json").steps,
    readLesson(relationId, "lesson-data.json").policies,
  );
  assert.match(relationRenderer.diagramMarkupFor(3, 1, {}), /2 个交点/);

  const contextId = "function-concepts-20260722-q06";
  const contextSpec = readLesson(contextId, "function-spec.json");
  const contextLesson = readLesson(contextId, "lesson-data.json");
  assert.equal(contextLesson.steps.length, 2);
  assert.equal(contextLesson.policies.s1.movable, true);
  assert.equal(contextLesson.policies.s2.movable, false);
  assert.deepEqual(contextLesson.ui.groupTitles, { 求解: "" });
  assert.equal(contextLesson.steps.every((step) => step.section === "求解"), true);
  assert.equal(contextLesson.problem.lines[1].figures[0].id, "original-context");
  assert.doesNotMatch(JSON.stringify(contextLesson), /FE=HK/);
  assert.equal(runtime.resolveState(contextSpec, 12, {}).env.otherSide, 28);
  assert.equal(runtime.resolveState(contextSpec, 12, {}).env.area, 336);
  assert.equal(runtime.resolveState(contextSpec, 28, {}).env.area, 336);
  const contextRenderer = runtime.createSpecRenderer(
    contextSpec,
    readLesson(contextId, "function-decorations.json"),
    contextLesson.steps,
    contextLesson.policies,
  );
  const originalContextMarkup = contextRenderer.originalFigureMarkupFor("original-context");
  assert.match(originalContextMarkup, /x m/);
  assert.match(originalContextMarkup, /40 m/);
  assert.match(originalContextMarkup, /font-size="44"/);
  assert.match(originalContextMarkup, /stroke-width="4"/);
  assert.doesNotMatch(originalContextMarkup, /原题示意图/);
  const contextHtml = fs.readFileSync(path.join(
    repoRoot,
    "site/problems/senior-high/functions/function-concepts-and-representation/function-concepts-20260722-q06.html",
  ), "utf8");
  assert.match(contextHtml, /id="original-context"/);
  assert.doesNotMatch(contextHtml, /（1）求草坪面积|（2）面积不小于|step-group-title">求解/);
  const narrowLawnMarkup = contextRenderer.diagramMarkupFor(0, 10, {});
  const wideLawnMarkup = contextRenderer.diagramMarkupFor(0, 30, {});
  assert.match(narrowLawnMarkup, /GF=x/);
  assert.match(narrowLawnMarkup, /CH=h/);
  assert.match(narrowLawnMarkup, /HK=40−x/);
  assert.notEqual(narrowLawnMarkup, wideLawnMarkup);
  assert.match(wideLawnMarkup, /data-geometry-polygon="lawn"/);
  assert.match(wideLawnMarkup, /data-geometry-dimension="upper-height"/);
  assert.match(wideLawnMarkup, /data-geometry-dimension="lower-height"/);
  assert.match(contextRenderer.diagramMarkupFor(1, 20, {}), /fill="#ede9fe" opacity="0\.35"/);
  assert.deepEqual(contextSpec.panels.find((panel) => panel.id === "area-graph").domain, {
    minX: -5,
    maxX: 45,
    minY: -50,
    maxY: 450,
  });

  const quadraticId = "function-concepts-20260722-q10";
  const quadraticSpec = readLesson(quadraticId, "function-spec.json");
  const quadraticLesson = readLesson(quadraticId, "lesson-data.json");
  assert.equal(quadraticLesson.steps.length, 1);
  assert.deepEqual(Object.keys(quadraticLesson.stepLabels), ["s1"]);
  assert.deepEqual(quadraticSpec.panels[0].domain, {
    minX: -3,
    maxX: 2.5,
    minY: -13,
    maxY: 6,
  });
  assert.deepEqual(quadraticLesson.policies.s1.range, [0, 2.5]);
  assert.equal(runtime.resolveState(quadraticSpec, 0, {}).env.gValue, 4);
  const quadraticRenderer = runtime.createSpecRenderer(
    quadraticSpec,
    readLesson(quadraticId, "function-decorations.json"),
    quadraticLesson.steps,
    quadraticLesson.policies,
  );
  const quadraticMarkup = quadraticRenderer.diagramMarkupFor(0, 2, {});
  assert.match(quadraticMarkup, />\+∞<\/text>/);
  assert.match(quadraticMarkup, /l-14,-9 v18 z/);
  assert.match(quadraticMarkup, /data-reference-line="symmetry-axis"/);
  assert.match(quadraticMarkup, /stroke-dasharray="7 6"/);
  assert.match(quadraticMarkup, /对称轴/);
  assert.match(
    quadraticMarkup,
    /font-style="italic" fill="#64748b">t<\/text>/,
  );
  assert.doesNotMatch(quadraticMarkup, /NaN|Infinity|undefined/);
});

test("SVG labels render nested radical fractions and excluded-point fractions", () => {
  const q07Id = "function-concepts-20260722-q07";
  const q07Lesson = readLesson(q07Id, "lesson-data.json");
  assert.match(q07Lesson.steps[0].title, /基本不等式/);
  assert.match(q07Lesson.steps[0].derive.flat().join(" "), /a\+b≥2\\sqrt\{ab\}/);
  assert.match(q07Lesson.steps[0].derive.flat().join(" "), /ab=x·\\frac\{1\}\{x\}=1/);
  assert.match(q07Lesson.steps[0].derive.flat().join(" "), /2\\sqrt\{1\}=2/);
  assert.match(q07Lesson.steps[0].derive.flat().join(" "), /x=1/);
  assert.match(q07Lesson.steps[0].derive.flat().join(" "), /x=-1/);
  assert.match(q07Lesson.steps[1].title, /配方法/);
  assert.match(q07Lesson.steps[2].title, /分母范围/);
  assert.match(q07Lesson.steps[3].derive.flat().join(" "), /x=\\frac\{1\}\{y_0\^2\}/);
  const q07Renderer = runtime.createSpecRenderer(
    readLesson(q07Id, "function-spec.json"),
    readLesson(q07Id, "function-decorations.json"),
    q07Lesson.steps,
    q07Lesson.policies,
  );
  const q07Markup = q07Renderer.diagramMarkupFor(3, 1, {});
  assert.doesNotMatch(q07Markup, /\\\\frac|\\\\sqrt/);
  assert.match(q07Markup, /text-decoration="overline">x<\/tspan>/);

  const q07PowerMarkup = q07Renderer.diagramMarkupFor(1, 1, {});
  assert.doesNotMatch(q07PowerMarkup, /x\^2/);
  assert.match(q07PowerMarkup, /baseline-shift="super" font-size="0\.72em">2<\/tspan>/);

  const q04Id = "function-concepts-20260722-q04";
  const q04Renderer = runtime.createSpecRenderer(
    readLesson(q04Id, "function-spec.json"),
    readLesson(q04Id, "function-decorations.json"),
    readLesson(q04Id, "lesson-data.json").steps,
    readLesson(q04Id, "lesson-data.json").policies,
  );
  const q04Markup = q04Renderer.diagramMarkupFor(1, 0, {});
  assert.doesNotMatch(q04Markup, /\\\\frac/);
  assert.match(q04Markup, /text-decoration="underline">1<\/tspan>/);
});

test("finite-domain enumeration stays in one concise teaching step", () => {
  const q08Lesson = readLesson(
    "function-concepts-20260722-q08",
    "lesson-data.json",
  );
  assert.equal(q08Lesson.steps.length, 1);
  assert.match(q08Lesson.problem.keyPoints.lead, /定义域是有限集合/);
  assert.match(q08Lesson.problem.keyPoints.lead, /逐一列出/);
  assert.match(q08Lesson.steps[0].derive.flat().join(" "), /G\(1\).*G\(2\).*G\(3\)/);
  assert.deepEqual(Object.keys(q08Lesson.stepLabels), ["s1"]);
});

test("abstract-function substitution uses one targeted assignment step", () => {
  const q09Lesson = readLesson(
    "function-concepts-20260722-q09",
    "lesson-data.json",
  );
  assert.equal(q09Lesson.steps.length, 1);
  assert.match(q09Lesson.problem.keyPoints.lead, /抽象函数赋值法/);
  assert.match(q09Lesson.problem.keyPoints.items.join(" "), /0、1、相等或互为相反数/);
  assert.match(q09Lesson.steps[0].derive.flat().join(" "), /x=1，y=0/);
  assert.match(q09Lesson.steps[0].derive.flat().join(" "), /f\(1\)=-1≠0/);
  assert.deepEqual(Object.keys(q09Lesson.stepLabels), ["s1"]);
});

test("batch validator enforces all 11 questions and low-confidence review gates", () => {
  const manifestPath = path.join(repoRoot, "internal/senior-high/import-batches/function-concepts-20260722-page-01/manifest.json");
  const manifest = validateFunctionBatch(manifestPath);
  assert.equal(manifest.items.length, 11);
  assert.deepEqual(
    manifest.items.filter((item) => item.status === "published").map((item) => item.questionNumber),
    [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
  );

  const temporary = structuredClone(manifest);
  temporary.items[5].confidence = 0.84;
  const tempPath = path.join(repoRoot, "internal/senior-high/import-batches/function-concepts-20260722-page-01/invalid-manifest.test.json");
  fs.writeFileSync(tempPath, JSON.stringify(temporary), "utf8");
  try {
    assert.throws(() => validateFunctionBatch(tempPath), /低置信度/);
  } finally {
    fs.unlinkSync(tempPath);
  }
});

test("compiled golden pages load only the function runtime", () => {
  for (const problemId of [
    "function-concepts-20260722-q01",
    "function-concepts-20260722-q05",
    "function-concepts-20260722-q11",
  ]) {
    const html = fs.readFileSync(path.join(
      repoRoot,
      "site/problems/senior-high/functions/function-concepts-and-representation",
      `${problemId}.html`,
    ), "utf8");
    assert.match(html, /function-lesson-from-spec\.js/);
    assert.doesNotMatch(html, /calculus-lesson-from-spec\.js/);
  }
});
