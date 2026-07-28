#!/usr/bin/env node
/** Validate a senior-high function lesson and representative renderer states. */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const currentFile = fileURLToPath(import.meta.url);
const repoRoot = path.resolve(path.dirname(currentFile), "..");
const PANEL_KINDS = new Set([
  "mapping", "relationPlot", "numberLine", "functionGraph",
  "valueTable", "constraintList", "contextGeometry",
]);
const GROUP_IDS = new Set([
  "function-concept",
  "function-domain",
  "function-value-and-range",
  "function-comprehensive",
]);
const FUNCTION_SECTION_PATTERNS = new Set([
  "function-concepts-and-representation",
  "function-representation",
]);

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function collectStrings(value, output = []) {
  if (typeof value === "string") output.push(value);
  else if (Array.isArray(value)) value.forEach((item) => collectStrings(item, output));
  else if (value && typeof value === "object") Object.values(value).forEach((item) => collectStrings(item, output));
  return output;
}

function loadRuntime(root) {
  const sandbox = { window: {}, console, Math };
  vm.createContext(sandbox);
  for (const relativePath of [
    "site/assets/js/math-expression-engine.js",
    "site/assets/js/function-lesson-from-spec.js",
  ]) {
    vm.runInContext(fs.readFileSync(path.join(root, relativePath), "utf8"), sandbox);
  }
  return sandbox.window.FunctionLessonFromSpec;
}

function requireUnique(items, label, errors) {
  const ids = new Set();
  for (const item of items ?? []) {
    if (!item?.id) errors.push(`${label} 缺少 id`);
    else if (ids.has(item.id)) errors.push(`${label} ID 重复: ${item.id}`);
    else ids.add(item.id);
  }
  return ids;
}

function validateInterval(interval, label, errors) {
  if (!Number.isFinite(interval?.min) || !Number.isFinite(interval?.max) || interval.min >= interval.max) {
    errors.push(`${label} 必须是递增有限区间`);
  }
}

function validateNonOverlappingIntervals(intervals, label, errors) {
  const sorted = [...(intervals ?? [])].sort((left, right) => left.min - right.min);
  sorted.forEach((interval, index) => {
    validateInterval(interval, `${label}[${index}]`, errors);
    if (index > 0 && interval.min < sorted[index - 1].max) {
      errors.push(`${label} 存在重叠区间`);
    }
  });
}

function trialValues(lesson, spec) {
  const values = [Number(spec.parameter?.initial ?? 0)];
  for (const step of lesson.steps ?? []) {
    values.push(Number(step.t));
    const range = lesson.policies?.[step.id]?.range;
    if (Array.isArray(range)) values.push(Number(range[0]), Number(range[1]));
    for (const mini of step.minis ?? []) values.push(Number(mini.t));
  }
  return [...new Set(values.filter(Number.isFinite))];
}

export function validateFunctionLesson(inputDirectory, root = repoRoot) {
  const inputDir = path.resolve(inputDirectory);
  const required = ["function-spec.json", "function-decorations.json", "lesson-data.json"];
  for (const fileName of required) {
    if (!fs.existsSync(path.join(inputDir, fileName))) throw new Error(`缺少: ${path.join(inputDir, fileName)}`);
  }
  const spec = readJson(path.join(inputDir, "function-spec.json"));
  const decorations = readJson(path.join(inputDir, "function-decorations.json"));
  const lesson = readJson(path.join(inputDir, "lesson-data.json"));
  const errors = [];

  if (spec.version !== 1) errors.push("function-spec.version 当前必须为 1");
  if (!spec.id || spec.id !== lesson.meta?.id) errors.push("function-spec.id 与 lesson-data.meta.id 不一致");
  if (!Array.isArray(spec.panels) || spec.panels.length === 0) errors.push("function-spec.panels 不能为空");
  if (collectStrings([spec, decorations, lesson]).some((text) => /<\s*\/?[a-zA-Z][^>]*>|style\s*=/.test(text))) {
    errors.push("声明式 JSON 中不允许 HTML");
  }

  const panelIds = requireUnique(spec.panels, "panel", errors);
  for (const panel of spec.panels ?? []) {
    if (!PANEL_KINDS.has(panel.kind)) errors.push(`panel ${panel.id} kind 无效: ${panel.kind}`);
    const viewport = panel.viewport;
    if (!viewport || viewport.x < 0 || viewport.y < 0 || viewport.width <= 0 || viewport.height <= 0 || viewport.x + viewport.width > 1 || viewport.y + viewport.height > 1) {
      errors.push(`panel ${panel.id} viewport 越界`);
    }
    if (panel.domain && (panel.domain.minX >= panel.domain.maxX || panel.domain.minY >= panel.domain.maxY)) {
      errors.push(`panel ${panel.id} domain 必须递增`);
    }
    for (const interval of panel.intervals ?? []) validateInterval(interval, `panel ${panel.id} interval`, errors);
    validateNonOverlappingIntervals(panel.function?.intervals, `panel ${panel.id} function intervals`, errors);
    for (const definition of panel.functions ?? []) {
      validateNonOverlappingIntervals(definition.intervals, `panel ${panel.id} function ${definition.id} intervals`, errors);
      validateNonOverlappingIntervals(definition.range, `panel ${panel.id} function ${definition.id} range`, errors);
    }
    validateNonOverlappingIntervals(panel.studyIntervals, `panel ${panel.id} studyIntervals`, errors);
    validateNonOverlappingIntervals(panel.range, `panel ${panel.id} range`, errors);
    if (panel.function?.finiteValues) {
      const values = panel.function.finiteValues;
      if (values.some((value) => !Number.isFinite(value)) || new Set(values).size !== values.length) {
        errors.push(`panel ${panel.id} finiteValues 必须是互不重复的有限数`);
      }
    }
    if (panel.kind === "mapping" && (!panel.sourceSet || !panel.targetSet || !panel.candidates?.length)) errors.push(`mapping panel ${panel.id} 缺少集合或候选`);
    if (panel.kind === "numberLine" && (!panel.axis || panel.axis.min >= panel.axis.max)) errors.push(`numberLine panel ${panel.id} 缺少有效 axis`);
    if (panel.kind === "functionGraph" && ((!panel.function && !panel.functions?.length) || !panel.domain)) errors.push(`functionGraph panel ${panel.id} 缺少 function/functions 或 domain`);
    if (panel.kind === "valueTable" && (!panel.columns?.length || !panel.rows?.length)) errors.push(`valueTable panel ${panel.id} 缺少表格数据`);
    if (panel.kind === "constraintList" && !panel.constraints?.length) errors.push(`constraintList panel ${panel.id} 缺少 constraints`);
  }

  const lessonStepIds = requireUnique(lesson.steps, "lesson step", errors);
  for (const stepId of lessonStepIds) {
    if (!decorations.steps?.[stepId]) errors.push(`function-decorations.steps 缺少: ${stepId}`);
    if (!lesson.policies?.[stepId]) errors.push(`lesson-data.policies 缺少: ${stepId}`);
    if (!lesson.stepLabels?.[stepId]) errors.push(`lesson-data.stepLabels 缺少: ${stepId}`);
  }
  for (const [stepId, decoration] of Object.entries(decorations.steps ?? {})) {
    if (!lessonStepIds.has(stepId)) errors.push(`function-decorations 包含未知 step: ${stepId}`);
    for (const panelId of decoration.visiblePanels ?? []) {
      if (!panelIds.has(panelId)) errors.push(`step ${stepId} 引用未知 panel: ${panelId}`);
    }
    const elementIds = new Set();
    for (const panel of spec.panels ?? []) {
      for (const key of ["candidates", "functions", "points", "segments", "intervals", "excludedPoints", "rows", "constraints"]) {
        for (const item of panel[key] ?? []) if (item.id) elementIds.add(item.id);
      }
    }
    for (const elementId of [...(decoration.visibleElementIds ?? []), ...(decoration.highlightElementIds ?? [])]) {
      if (!elementIds.has(elementId)) errors.push(`step ${stepId} 引用未知 element: ${elementId}`);
    }
    if (decoration.activeCandidateId && !elementIds.has(decoration.activeCandidateId)) {
      errors.push(`step ${stepId} 引用未知 candidate: ${decoration.activeCandidateId}`);
    }
  }

  const classification = lesson.meta?.classification;
  if (!FUNCTION_SECTION_PATTERNS.has(classification?.pattern)) {
    errors.push("classification.pattern 必须是已登记的函数子目录");
  } else if (!lesson.meta?.outputPath?.includes(`/functions/${classification.pattern}/`)) {
    errors.push("lesson-data.meta.outputPath 与 classification.pattern 不一致");
  }
  for (const method of classification?.methods ?? []) {
    if (typeof method !== "string" || method.length === 0) errors.push("classification.methods 存在空值");
  }
  const curriculum = lesson.meta?.curriculum;
  if (!curriculum || !GROUP_IDS.has(curriculum.groupId)) errors.push("lesson-data.meta.curriculum.groupId 无效或缺失");
  const keyPoints = lesson.problem?.keyPoints;
  if (keyPoints && (!Array.isArray(keyPoints.items) || keyPoints.items.length < 1 || keyPoints.items.length > 4)) {
    errors.push("lesson-data.problem.keyPoints.items 必须包含 1 至 4 条要点");
  }

  const runtime = loadRuntime(root);
  for (const value of trialValues(lesson, spec)) {
    let state;
    try {
      state = runtime.resolveState(spec, value, {});
    } catch (error) {
      errors.push(`parameter=${value} binding 计算失败: ${error.message}`);
      continue;
    }
    for (const [name, result] of Object.entries(state.env)) {
      if (typeof result === "number" && !Number.isFinite(result)) errors.push(`parameter=${value} binding ${name} 不是有限数`);
    }
    for (const panel of spec.panels ?? []) {
      if (panel.kind === "functionGraph") {
        const definitions = panel.functions?.length ? panel.functions : [panel.function];
        for (const definition of definitions) {
        try {
          const result = runtime.functionValue(definition, value, state.env);
          if (!Number.isFinite(result)) errors.push(`panel ${panel.id} 在 parameter=${value} 的函数值不是有限数`);
        } catch (error) {
          errors.push(`panel ${panel.id} 表达式失败: ${error.message}`);
        }
        }
      }
      for (const candidate of panel.candidates ?? []) {
        try {
          const result = runtime.evaluate(candidate.expr, { ...state.env, x: 0 });
          if (!Number.isFinite(result)) errors.push(`candidate ${candidate.id} 表达式不是有限数`);
        } catch (error) {
          errors.push(`candidate ${candidate.id} 表达式失败: ${error.message}`);
        }
      }
    }
  }

  if (errors.length) throw new Error(errors.join("\n"));
  return { spec, decorations, lesson };
}

if (process.argv[1] && path.resolve(process.argv[1]) === currentFile) {
  const input = process.argv[2];
  if (!input) {
    console.error("用法: node tools/validate-function-spec.mjs internal/senior-high/lesson-specs/<problem-id>/");
    process.exitCode = 1;
  } else {
    try {
      validateFunctionLesson(input);
      console.log(`OK: ${path.resolve(input)}`);
    } catch (error) {
      console.error(error.message);
      process.exitCode = 1;
    }
  }
}
