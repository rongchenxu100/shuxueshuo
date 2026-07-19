#!/usr/bin/env node
/** Validate senior-high calculus lesson JSON and representative numerical states. */
import fs from "fs";
import path from "path";
import vm from "vm";
import { normalizeLessonSpec } from "./lib/lesson-normalizer.mjs";

const input = process.argv[2];
if (!input) {
  console.error("用法: node tools/validate-calculus-spec.mjs internal/senior-high/lesson-specs/<problem-id>/");
  process.exit(1);
}

const repoRoot = path.resolve(process.cwd());
const inputDir = path.resolve(input);
const errors = [];

function need(condition, message) {
  if (!condition) errors.push(message);
}

function readJson(filePath, label = filePath) {
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch (error) {
    errors.push(label + " JSON 解析失败: " + error.message);
    return null;
  }
}

function schemaTypeMatches(value, type) {
  if (type === "array") return Array.isArray(value);
  if (type === "object") return value !== null && typeof value === "object" && !Array.isArray(value);
  if (type === "integer") return Number.isInteger(value);
  return typeof value === type;
}

function resolveRef(rootSchema, ref) {
  if (!ref.startsWith("#/")) throw new Error("Only local schema refs are supported: " + ref);
  return ref.slice(2).split("/").reduce((value, part) => value?.[part], rootSchema);
}

function validateAgainstSchema(value, schema, rootSchema, label) {
  if (!schema) return;
  if (schema.$ref) {
    validateAgainstSchema(value, resolveRef(rootSchema, schema.$ref), rootSchema, label);
    return;
  }
  if (schema.oneOf) {
    let matches = 0;
    const before = errors.length;
    for (const branch of schema.oneOf) {
      const snapshot = errors.length;
      validateAgainstSchema(value, branch, rootSchema, label);
      if (errors.length === snapshot) matches += 1;
      errors.length = snapshot;
    }
    errors.length = before;
    if (matches !== 1) errors.push(label + " 不匹配 oneOf 结构");
    return;
  }
  if (schema.type && !schemaTypeMatches(value, schema.type)) {
    errors.push(label + " 类型应为 " + schema.type);
    return;
  }
  if (schema.enum && !schema.enum.includes(value)) errors.push(label + " 值不在允许列表: " + value);
  if (typeof value === "number") {
    if (schema.minimum != null && value < schema.minimum) errors.push(label + " 应 >= " + schema.minimum);
    if (schema.maximum != null && value > schema.maximum) errors.push(label + " 应 <= " + schema.maximum);
    if (schema.exclusiveMinimum != null && value <= schema.exclusiveMinimum) errors.push(label + " 应 > " + schema.exclusiveMinimum);
  }
  if (typeof value === "string") {
    if (schema.minLength != null && value.length < schema.minLength) errors.push(label + " 长度应 >= " + schema.minLength);
    if (schema.pattern && !(new RegExp(schema.pattern)).test(value)) errors.push(label + " 不匹配格式 " + schema.pattern);
  }
  if (Array.isArray(value)) {
    if (schema.minItems != null && value.length < schema.minItems) errors.push(label + " 数组长度应 >= " + schema.minItems);
    if (schema.maxItems != null && value.length > schema.maxItems) errors.push(label + " 数组长度应 <= " + schema.maxItems);
    if (schema.items) value.forEach((item, index) => validateAgainstSchema(item, schema.items, rootSchema, label + "[" + index + "]"));
  }
  if (value && typeof value === "object" && !Array.isArray(value)) {
    for (const key of schema.required ?? []) {
      if (!(key in value)) errors.push(label + " 缺少必填字段: " + key);
    }
    const properties = schema.properties ?? {};
    for (const [key, child] of Object.entries(value)) {
      if (properties[key]) validateAgainstSchema(child, properties[key], rootSchema, label + "." + key);
      else if (schema.additionalProperties === false) errors.push(label + " 不允许额外字段: " + key);
      else if (schema.additionalProperties && typeof schema.additionalProperties === "object") {
        validateAgainstSchema(child, schema.additionalProperties, rootSchema, label + "." + key);
      }
    }
  }
}

function validateSchema(value, schemaPath, label) {
  const schema = readJson(schemaPath, path.basename(schemaPath));
  if (value && schema) validateAgainstSchema(value, schema, schema, label);
}

function collectStrings(value, output = []) {
  if (typeof value === "string") output.push(value);
  else if (Array.isArray(value)) value.forEach((item) => collectStrings(item, output));
  else if (value && typeof value === "object") Object.values(value).forEach((item) => collectStrings(item, output));
  return output;
}

function hasHtml(value) {
  return collectStrings(value).some((text) => /<\s*\/?[a-zA-Z][^>]*>|style\s*=/.test(text));
}

function uniqueIds(items, label) {
  const seen = new Set();
  for (const item of items ?? []) {
    if (!item?.id) continue;
    need(!seen.has(item.id), label + " 存在重复 id: " + item.id);
    seen.add(item.id);
  }
  return seen;
}

function trialValues(lessonData, initial) {
  const values = [Number(initial)];
  for (const step of lessonData.steps ?? []) {
    values.push(Number(step.t));
    const range = lessonData.policies?.[step.id]?.range;
    if (Array.isArray(range) && range.length >= 2) {
      const lo = Number(range[0]);
      const hi = Number(range[1]);
      values.push(lo, hi, (lo + hi) / 2);
    }
    for (const mini of step.minis ?? []) values.push(Number(mini.t));
  }
  return [...new Set(values.filter(Number.isFinite))];
}

function loadRuntime() {
  const sandbox = { window: {}, console, Math };
  vm.createContext(sandbox);
  vm.runInNewContext(fs.readFileSync(path.join(repoRoot, "site/assets/js/math-expression-engine.js"), "utf8"), sandbox);
  vm.runInNewContext(fs.readFileSync(path.join(repoRoot, "site/assets/js/calculus-lesson-from-spec.js"), "utf8"), sandbox);
  return {
    expression: sandbox.window.MathExpressionEngine,
    calculus: sandbox.window.CalculusLessonFromSpec,
  };
}

function validateClassification(lessonData) {
  const knowledgePath = path.join(repoRoot, "internal/senior-high/knowledge-points/calculus-methods.md");
  if (!fs.existsSync(knowledgePath)) {
    errors.push("缺少高中导数知识库: " + knowledgePath);
    return;
  }
  const markdown = fs.readFileSync(knowledgePath, "utf8");
  const patterns = new Set([...markdown.matchAll(/^\| `([a-z0-9-]+)` \|/gm)].map((match) => match[1]));
  const methods = new Set([...markdown.matchAll(/^### method: ([a-z0-9-]+)/gm)].map((match) => match[1]));
  const classification = lessonData.meta?.classification;
  need(Boolean(classification), "lesson-data.meta.classification 缺失");
  if (!classification) return;
  need(patterns.has(classification.pattern), "未知 calculus pattern: " + classification.pattern);
  for (const method of classification.methods ?? []) {
    need(methods.has(method), "未知 calculus method: " + method);
  }
}

const specPath = path.join(inputDir, "calculus-spec.json");
const decorationsPath = path.join(inputDir, "calculus-decorations.json");
const lessonPath = path.join(inputDir, "lesson-data.json");
const presetPath = path.join(repoRoot, "internal/config/style-presets.json");
for (const requiredPath of [specPath, decorationsPath, lessonPath]) {
  need(fs.existsSync(requiredPath), "缺少: " + requiredPath);
}

let spec = readJson(specPath, "calculus-spec.json");
let decorations = readJson(decorationsPath, "calculus-decorations.json");
let lessonData = readJson(lessonPath, "lesson-data.json");
validateSchema(spec, path.join(repoRoot, "internal/senior-high/schemas/calculus-spec.schema.json"), "calculus-spec.json");
validateSchema(decorations, path.join(repoRoot, "internal/senior-high/schemas/calculus-decorations.schema.json"), "calculus-decorations.json");
validateSchema(lessonData, path.join(repoRoot, "internal/schemas/lesson-data.schema.json"), "lesson-data.json");

if (spec && decorations && lessonData) {
  const normalized = normalizeLessonSpec({
    geometrySpec: spec,
    stepDecorations: decorations,
    lessonData,
    stylePresets: readJson(presetPath, "style-presets.json") ?? {},
  });
  spec = normalized.geometrySpec;
  decorations = normalized.stepDecorations;
  lessonData = normalized.lessonData;

  need(!hasHtml(spec) && !hasHtml(decorations) && !hasHtml(lessonData), "JSON 规格中不允许 HTML 片段");
  need(spec.id === lessonData.meta?.id, "calculus-spec.id 与 lesson-data.meta.id 不一致");
  validateClassification(lessonData);

  const panelIds = uniqueIds(spec.panels, "panels");
  const functionIds = uniqueIds(spec.functions, "functions");
  const pointIds = uniqueIds(spec.functionPoints, "functionPoints");
  const tangentIds = uniqueIds(spec.tangentLines, "tangentLines");
  const lineIds = uniqueIds(spec.lines, "lines");
  for (const panel of spec.panels ?? []) {
    need(panel.domain.minX < panel.domain.maxX && panel.domain.minY < panel.domain.maxY, "panel " + panel.id + " domain 应递增");
    need(panel.viewport.x + panel.viewport.width <= 1 + 1e-9, "panel " + panel.id + " viewport 横向越界");
    need(panel.viewport.y + panel.viewport.height <= 1 + 1e-9, "panel " + panel.id + " viewport 纵向越界");
  }
  for (const fn of spec.functions ?? []) {
    need(panelIds.has(fn.panelId), "function " + fn.id + " 引用未知 panel: " + fn.panelId);
    for (const interval of fn.domain ?? []) need(interval.min < interval.max, "function " + fn.id + " domain 应递增");
  }
  for (const point of spec.functionPoints ?? []) {
    need(functionIds.has(point.functionId), "functionPoint " + point.id + " 引用未知 function: " + point.functionId);
    if (point.panelId) need(panelIds.has(point.panelId), "functionPoint " + point.id + " 引用未知 panel: " + point.panelId);
  }
  for (const tangent of spec.tangentLines ?? []) {
    need(functionIds.has(tangent.functionId), "tangentLine " + tangent.id + " 引用未知 function: " + tangent.functionId);
    if (tangent.panelId) need(panelIds.has(tangent.panelId), "tangentLine " + tangent.id + " 引用未知 panel: " + tangent.panelId);
  }
  for (const line of spec.lines ?? []) need(panelIds.has(line.panelId), "line " + line.id + " 引用未知 panel: " + line.panelId);

  const checkDecoration = (element, label) => {
    if (element.panelId) need(panelIds.has(element.panelId), label + " 引用未知 panel: " + element.panelId);
    if (element.functionId) need(functionIds.has(element.functionId), label + " 引用未知 function: " + element.functionId);
    if (element.pointId) need(pointIds.has(element.pointId), label + " 引用未知 point: " + element.pointId);
    if (element.tangentId) need(tangentIds.has(element.tangentId), label + " 引用未知 tangent: " + element.tangentId);
    if (element.lineId) need(lineIds.has(element.lineId), label + " 引用未知 line: " + element.lineId);
  };
  for (const [name, layer] of Object.entries(decorations.layers ?? {})) {
    (layer.elements ?? []).forEach((element, index) => checkDecoration(element, "layers." + name + ".elements[" + index + "]"));
  }
  for (const [stepId, step] of Object.entries(decorations.steps ?? {})) {
    for (const panelId of step.visiblePanels ?? []) need(panelIds.has(panelId), "steps." + stepId + " 引用未知 visible panel: " + panelId);
    for (const [panelId, viewport] of Object.entries(step.panelViewports ?? {})) {
      need(panelIds.has(panelId), "steps." + stepId + " 引用未知 panel viewport: " + panelId);
      need(viewport.x + viewport.width <= 1 + 1e-9, "steps." + stepId + ".panelViewports." + panelId + " 横向越界");
      need(viewport.y + viewport.height <= 1 + 1e-9, "steps." + stepId + ".panelViewports." + panelId + " 纵向越界");
    }
    for (const panelId of Object.keys(step.panelDomains ?? {})) need(panelIds.has(panelId), "steps." + stepId + " 引用未知 panel: " + panelId);
    (step.add ?? []).forEach((element, index) => checkDecoration(element, "steps." + stepId + ".add[" + index + "]"));
  }

  const lessonStepIds = new Set((lessonData.steps ?? []).map((step) => step.id));
  for (const stepId of lessonStepIds) {
    need(Boolean(decorations.steps?.[stepId]), "calculus-decorations.steps 缺少: " + stepId);
    need(Boolean(lessonData.policies?.[stepId]), "lesson-data.policies 缺少: " + stepId);
    need(Boolean(lessonData.stepLabels?.[stepId]), "lesson-data.stepLabels 缺少: " + stepId);
  }

  const { calculus } = loadRuntime();
  for (const parameterValue of trialValues(lessonData, spec.parameter.initial)) {
    let state;
    try {
      state = calculus.resolveState(spec, parameterValue, {});
    } catch (error) {
      errors.push("parameter=" + parameterValue + " 状态计算失败: " + error.message);
      continue;
    }
    for (const binding of spec.bindings ?? []) {
      need(Number.isFinite(state.env[binding.name]), "binding " + binding.name + " 在 parameter=" + parameterValue + " 时不是有限数");
    }
    for (const point of Object.values(state.points)) {
      need(Number.isFinite(point.x) && Number.isFinite(point.y), "point " + point.id + " 在 parameter=" + parameterValue + " 时不是有限点");
    }
    for (const tangent of Object.values(state.tangents)) {
      need(Number.isFinite(tangent.slope) && Number.isFinite(tangent.intercept), "tangent " + tangent.id + " 在 parameter=" + parameterValue + " 时不是有限直线");
    }

    for (const fn of spec.functions ?? []) {
      if (!fn.derivativeExpr) continue;
      const panel = state.panels[fn.panelId];
      const intervals = fn.domain?.length ? fn.domain : [{ min: panel.domain.minX, max: panel.domain.maxX }];
      for (const interval of intervals) {
        for (const ratio of [0.25, 0.5, 0.75]) {
          const x = interval.min + (interval.max - interval.min) * ratio;
          const h = Math.max(1e-6, Math.abs(x) * 1e-6);
          let left;
          let right;
          let analytic;
          try {
            left = calculus.evaluateFunction(fn, x - h, state.env);
            right = calculus.evaluateFunction(fn, x + h, state.env);
            analytic = calculus.evaluateDerivative(fn, x, state.env);
          } catch (_error) {
            continue;
          }
          if (![left, right, analytic].every(Number.isFinite)) continue;
          const numeric = (right - left) / (2 * h);
          const tolerance = 2e-4 * Math.max(1, Math.abs(numeric), Math.abs(analytic));
          need(Math.abs(numeric - analytic) <= tolerance, "function " + fn.id + " derivativeExpr 在 x=" + x + " 与数值导数不一致");
        }
      }
    }
  }

  try {
    const renderer = calculus.createSpecRenderer(spec, decorations, lessonData.steps, lessonData.policies);
    for (let index = 0; index < lessonData.steps.length; index += 1) {
      const markup = renderer.diagramMarkupFor(index, lessonData.steps[index].t, {});
      need(!/NaN|Infinity|undefined/.test(markup), "step " + lessonData.steps[index].id + " SVG 含无效数值");
    }
  } catch (error) {
    errors.push("renderer 试渲染失败: " + error.message);
  }
}

if (errors.length) {
  console.error("Calculus spec validation failed:");
  errors.forEach((error) => console.error("- " + error));
  process.exit(1);
}

console.log("Calculus spec validation passed:", inputDir);
