#!/usr/bin/env node
/**
 * Validate a compiled geometry lesson spec directory.
 *
 * Usage:
 *   node tools/validate-geometry-spec.mjs <geometry-spec.json>
 *   node tools/validate-geometry-spec.mjs internal/lesson-specs/<problem-id>/
 */
import fs from "fs";
import path from "path";
import vm from "vm";
import { normalizeLessonSpec } from "./lib/lesson-normalizer.mjs";

const input = process.argv[2];
if (!input) {
  console.error(
    "用法:\n" +
      "  node tools/validate-geometry-spec.mjs <geometry-spec.json>\n" +
      "  node tools/validate-geometry-spec.mjs internal/lesson-specs/<problem-id>/"
  );
  process.exit(1);
}

const repoRoot = path.resolve(process.cwd());
const errors = [];
const presetPath = path.join(repoRoot, "internal/config/style-presets.json");

function need(cond, msg) {
  if (!cond) errors.push(msg);
}

function readJson(filePath, label = filePath) {
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch (e) {
    errors.push(label + " JSON 解析失败: " + e.message);
    return null;
  }
}

function readSchema(name) {
  return readJson(path.join(repoRoot, "internal/schemas", name), name);
}

function schemaTypeMatches(value, type) {
  if (type === "array") return Array.isArray(value);
  if (type === "object") return value !== null && typeof value === "object" && !Array.isArray(value);
  if (type === "integer") return Number.isInteger(value);
  return typeof value === type;
}

function resolveRef(rootSchema, ref) {
  if (!ref.startsWith("#/")) throw new Error("Only local schema refs are supported: " + ref);
  return ref
    .slice(2)
    .split("/")
    .reduce((obj, part) => obj?.[part], rootSchema);
}

function validateAgainstSchema(value, schema, rootSchema, label) {
  if (!schema) return;
  if (schema.$ref) {
    validateAgainstSchema(value, resolveRef(rootSchema, schema.$ref), rootSchema, label);
    return;
  }
  if (schema.oneOf) {
    const before = errors.length;
    let matches = 0;
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
  if (schema.enum && !schema.enum.includes(value)) {
    errors.push(label + " 值不在允许列表: " + value);
  }
  if (typeof value === "number" && typeof schema.minimum === "number" && value < schema.minimum) {
    errors.push(label + " 应 >= " + schema.minimum);
  }
  if (Array.isArray(value)) {
    if (typeof schema.minItems === "number" && value.length < schema.minItems) {
      errors.push(label + " 数组长度应 >= " + schema.minItems);
    }
    if (typeof schema.maxItems === "number" && value.length > schema.maxItems) {
      errors.push(label + " 数组长度应 <= " + schema.maxItems);
    }
    if (schema.items) {
      value.forEach((item, i) => validateAgainstSchema(item, schema.items, rootSchema, label + "[" + i + "]"));
    }
  }
  if (value && typeof value === "object" && !Array.isArray(value)) {
    for (const key of schema.required ?? []) {
      if (!(key in value)) errors.push(label + " 缺少必填字段: " + key);
    }
    const props = schema.properties ?? {};
    for (const [key, childValue] of Object.entries(value)) {
      if (props[key]) {
        validateAgainstSchema(childValue, props[key], rootSchema, label + "." + key);
      } else if (schema.additionalProperties === false) {
        errors.push(label + " 不允许额外字段: " + key);
      } else if (schema.additionalProperties && typeof schema.additionalProperties === "object") {
        validateAgainstSchema(childValue, schema.additionalProperties, rootSchema, label + "." + key);
      }
    }
  }
}

function validateSchemaFile(value, schemaName, label) {
  const schema = readSchema(schemaName);
  if (schema && value) validateAgainstSchema(value, schema, schema, label);
}

function validateOriginalFigureRefs(spec) {
  const knownPoints = new Set([
    ...Object.keys(spec.fixedPoints ?? {}),
    ...Object.keys(spec.movingPoints ?? {}),
    ...(spec.derivedIntersections ?? []).map((item) => item.name).filter(Boolean)
  ]);
  for (const fig of spec.originalFigures ?? []) {
    const figLabel = "originalFigures." + (fig.id || "(missing id)");
    for (const listName of ["fixedLabels", "movingLabels", "intersectionLabels"]) {
      for (const [index, label] of (fig[listName] ?? []).entries()) {
        if (label && typeof label === "object" && !Array.isArray(label)) {
          need(knownPoints.has(label.at), figLabel + "." + listName + "[" + index + "].at 未声明点: " + label.at);
        }
      }
    }
    for (const [index, segment] of (fig.segments ?? []).entries()) {
      if (segment && typeof segment === "object" && !Array.isArray(segment)) {
        need(knownPoints.has(segment.from), figLabel + ".segments[" + index + "].from 未声明点: " + segment.from);
        need(knownPoints.has(segment.to), figLabel + ".segments[" + index + "].to 未声明点: " + segment.to);
      }
    }
    for (const [index, rightAngle] of (fig.rightAngles ?? []).entries()) {
      if (rightAngle && typeof rightAngle === "object" && !Array.isArray(rightAngle)) {
        need(knownPoints.has(rightAngle.vertex), figLabel + ".rightAngles[" + index + "].vertex 未声明点: " + rightAngle.vertex);
        need(knownPoints.has(rightAngle.rayA), figLabel + ".rightAngles[" + index + "].rayA 未声明点: " + rightAngle.rayA);
        need(knownPoints.has(rightAngle.rayB), figLabel + ".rightAngles[" + index + "].rayB 未声明点: " + rightAngle.rayB);
      }
    }
  }
}

function collectStrings(value, out = []) {
  if (typeof value === "string") out.push(value);
  else if (Array.isArray(value)) value.forEach(item => collectStrings(item, out));
  else if (value && typeof value === "object") Object.values(value).forEach(item => collectStrings(item, out));
  return out;
}

function hasHtmlString(value) {
  return collectStrings(value).some(s => /<\s*\/?[a-zA-Z][^>]*>|style\s*=/.test(s));
}

function readEngine() {
  const enginePath = path.join(repoRoot, "site/assets/js/geometry-engine.js");
  const lessonPath = path.join(repoRoot, "site/assets/js/geometry-lesson-from-spec.js");
  return {
    engine: fs.readFileSync(enginePath, "utf8"),
    lesson: fs.readFileSync(lessonPath, "utf8")
  };
}

function pointNames(spec) {
  return new Set([
    ...Object.keys(spec.fixedPoints ?? {}),
    ...Object.keys(spec.movingPoints ?? {}),
    ...(spec.derivedIntersections ?? []).map(item => item.name)
  ]);
}

function validatePointRefs(spec, deco) {
  const known = pointNames(spec);
  const check = (name, label) => {
    if (name && !known.has(name)) errors.push(label + " 引用了未声明点: " + name);
  };
  (spec.basePolygon ?? []).forEach((name, i) => check(name, "geometry-spec.basePolygon[" + i + "]"));
  (spec.movingPolygon ?? []).forEach((name, i) => check(name, "geometry-spec.movingPolygon[" + i + "]"));
  (spec.movingPolygons ?? []).forEach((poly, pi) => {
    (poly.vertices ?? poly.points ?? []).forEach((name, i) => {
      check(name, "geometry-spec.movingPolygons[" + pi + "].vertices[" + i + "]");
    });
  });
  const checkDecoration = (item, label) => {
    for (const key of ["at", "from", "to", "vertex", "rayA", "rayB", "anchor"]) {
      check(item[key], label + "." + key);
    }
    if (Array.isArray(item.vertices)) {
      item.vertices.forEach((name, i) => check(name, label + ".vertices[" + i + "]"));
    }
  };
  for (const [layerName, layer] of Object.entries(deco.layers ?? {})) {
    (layer.elements ?? []).forEach((item, i) => checkDecoration(item, "layers." + layerName + ".elements[" + i + "]"));
  }
  for (const [stepId, step] of Object.entries(deco.steps ?? {})) {
    (step.add ?? []).forEach((item, i) => checkDecoration(item, "steps." + stepId + ".add[" + i + "]"));
  }
}

function keyForEdge(a, b) {
  return [a, b].sort().join("\u0000");
}

function basePolygonEdges(spec) {
  const edges = new Set();
  const base = spec.basePolygon ?? [];
  for (let i = 0; i < base.length; i++) {
    const a = base[i];
    const b = base[(i + 1) % base.length];
    if (a && b) edges.add(keyForEdge(a, b));
  }
  return edges;
}

function visitDecorations(deco, visitor) {
  for (const [layerName, layer] of Object.entries(deco.layers ?? {})) {
    (layer.elements ?? []).forEach((item, i) => visitor(item, "layers." + layerName + ".elements[" + i + "]", { layerName }));
  }
  for (const [stepId, step] of Object.entries(deco.steps ?? {})) {
    (step.add ?? []).forEach((item, i) => visitor(item, "steps." + stepId + ".add[" + i + "]", { stepId }));
  }
}

function validateDecorationGeometryStyle(spec, deco) {
  const baseEdges = basePolygonEdges(spec);
  visitDecorations(deco, (item, label, ctx) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) return;
    if (item.type === "segment" && !item.label && !item.labelText && !item.text) {
      errors.push(label + " 是无标签 segment；需要可见辅助线请改用 coloredLine/dashedLine/dottedLine，需要测量线段请填写 label");
    }
    if (item.type === "segment" && item.from && item.to && baseEdges.has(keyForEdge(item.from, item.to)) && ctx.layerName) {
      errors.push(label + " 在图层中重复绘制 basePolygon 边 " + item.from + item.to + "；除非当前步骤正在计算该边，否则不要重画/标注已有边界");
    }
  });
}

function distance(a, b) {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function originalNameForFoldedPoint(name) {
  return /^[A-Z]p$/.test(name) ? name.slice(0, -1) : null;
}

function validateDerivedIntersectionsFinite(specObj, state, tVal) {
  for (const item of specObj.derivedIntersections ?? []) {
    if (!item?.name) continue;
    const p = state.points?.[item.name];
    need(
      p && Number.isFinite(p.x) && Number.isFinite(p.y),
      "derivedIntersections." + item.name + " 在 " + (specObj.movingParam || "t") + "=" + tVal + " 时应计算为有限坐标"
    );
  }
}

function validateFoldLengthPreservation(specObj, state, tVal) {
  const points = state.points ?? {};
  const anchor = points.D;
  if (!anchor || !(specObj.movingPolygon ?? []).includes("D")) return;
  for (const name of Object.keys(specObj.movingPoints ?? {})) {
    const originalName = originalNameForFoldedPoint(name);
    if (!originalName || !points[originalName] || !points[name]) continue;
    const originalDistance = distance(anchor, points[originalName]);
    const foldedDistance = distance(anchor, points[name]);
    if (Math.abs(originalDistance - foldedDistance) > 1e-6) {
      errors.push(
        "movingPoints." + name + " 在 " + (specObj.movingParam || "t") + "=" + tVal +
          " 时不满足折叠保距: D" + originalName + "=" + originalDistance.toFixed(6) +
          ", D" + name + "=" + foldedDistance.toFixed(6)
      );
    }
  }
}

const resolvedInput = path.resolve(input);
const stat = fs.existsSync(resolvedInput) ? fs.statSync(resolvedInput) : null;
if (!stat) {
  console.error("路径不存在:", resolvedInput);
  process.exit(1);
}

const geometryPath = stat.isDirectory()
  ? path.join(resolvedInput, "geometry-spec.json")
  : resolvedInput;
const baseDir = stat.isDirectory() ? resolvedInput : path.dirname(geometryPath);
const decoPath = path.join(baseDir, "step-decorations.json");
const lessonDataPath = path.join(baseDir, "lesson-data.json");

if (!fs.existsSync(geometryPath)) {
  console.error("缺少 geometry-spec:", geometryPath);
  process.exit(1);
}

let spec = readJson(geometryPath, "geometry-spec.json");
validateSchemaFile(spec, "geometry-spec.schema.json", "geometry-spec.json");

let deco = null;
let lessonData = null;
if (fs.existsSync(decoPath)) {
  deco = readJson(decoPath, "step-decorations.json");
  validateSchemaFile(deco, "step-decorations.schema.json", "step-decorations.json");
}
if (fs.existsSync(lessonDataPath)) {
  lessonData = readJson(lessonDataPath, "lesson-data.json");
  validateSchemaFile(lessonData, "lesson-data.schema.json", "lesson-data.json");
}

const stylePresets = readJson(presetPath, "style-presets.json") ?? {};
const normalized = normalizeLessonSpec({
  geometrySpec: spec,
  stepDecorations: deco,
  lessonData,
  stylePresets
});
spec = normalized.geometrySpec;
deco = normalized.stepDecorations;
lessonData = normalized.lessonData;

if (spec) {
  const { engine, lesson } = readEngine();
  const sandbox = { window: {}, Math };
  vm.createContext(sandbox);
  vm.runInNewContext(engine, sandbox);
  vm.runInNewContext(lesson, sandbox);
  const GE = sandbox.window.GeometryEngine;
  const GLS = sandbox.window.GeometryLessonFromSpec;

  function buildTrialEnv(specObj, tVal) {
    const paramName = specObj.movingParam || "t";
    const tv = Number(tVal);
    const envTrial = { S3: Math.sqrt(3), t: tv };
    envTrial[paramName] = tv;
    for (const item of specObj.expressionEnv ?? []) {
      if (!item?.name) continue;
      envTrial[item.name] = GE.evalExpr(String(item.expr ?? ""), envTrial);
    }
    return envTrial;
  }

  function uniqueFinite(values) {
    return [...new Set(values.map(Number).filter(Number.isFinite))];
  }

  function collectTrialValues(specObj, lessonDataObj) {
    const values = [];
    for (const step of lessonDataObj?.steps ?? []) {
      if (Number.isFinite(Number(step.t))) values.push(Number(step.t));
      const range = lessonDataObj?.policies?.[step.id]?.range;
      if (Array.isArray(range) && range.length >= 2) {
        const lo = Number(range[0]);
        const hi = Number(range[1]);
        if (Number.isFinite(lo)) values.push(lo);
        if (Number.isFinite(hi)) values.push(hi);
        if (Number.isFinite(lo) && Number.isFinite(hi)) values.push((lo + hi) / 2);
      }
    }
    if (!values.length) values.push(specObj.movingParam === "m" ? 3 : 2);
    return uniqueFinite(values);
  }

  function needFinitePoint(p, label) {
    need(p && Number.isFinite(p.x) && Number.isFinite(p.y), label + " 应计算为有限坐标");
  }

  function needFiniteCurves(state, tVal) {
    for (const [curveId, curve] of Object.entries(state.curves ?? {})) {
      for (const key of ["a", "b", "c"]) {
        need(Number.isFinite(curve[key]), "curves." + curveId + "." + key + " 在 " + (spec.movingParam || "t") + "=" + tVal + " 时应为有限数");
      }
    }
  }

  const trialValues = collectTrialValues(spec, lessonData);
  validateOriginalFigureRefs(spec);
  for (const trialValue of trialValues) {
    const trialEnv = buildTrialEnv(spec, trialValue);
    for (const [name, pair] of Object.entries(spec.fixedPoints ?? {})) {
      try {
        needFinitePoint(GE.evalPoint(pair, trialEnv), "fixedPoints." + name + " 在 " + (spec.movingParam || "t") + "=" + trialValue + " 时");
      } catch (e) {
        errors.push("fixedPoints." + name + ": " + e.message);
      }
    }
    for (const [name, pair] of Object.entries(spec.movingPoints ?? {})) {
      try {
        needFinitePoint(GE.evalPoint(pair, trialEnv), "movingPoints." + name + " 在 " + (spec.movingParam || "t") + "=" + trialValue + " 时");
      } catch (e) {
        errors.push("movingPoints." + name + ": " + e.message);
      }
    }
    try {
      const st = GLS.resolveClipOverlap(spec, trialValue);
      need(st.overlap.length >= 0, "overlap 计算异常");
      need(Number.isFinite(st.area), "area 应为有限数");
      validateDerivedIntersectionsFinite(spec, st, trialValue);
      validateFoldLengthPreservation(spec, st, trialValue);
      needFiniteCurves(st, trialValue);
    } catch (e) {
      errors.push("resolveClipOverlap(" + (spec.movingParam || "t") + "=" + trialValue + "): " + e.message);
    }
  }

  if (deco && lessonData) {
    if (lessonData.meta?.id && spec.id) {
      need(lessonData.meta.id === spec.id, "meta.id 与 geometry-spec.id 不一致");
    }

    for (const s of lessonData.steps ?? []) {
      need(typeof s.id === "string" && s.id, "lesson-data.steps[] 每项需要 id");
      if (s?.id) {
        need(lessonData.policies?.[s.id], "policies 缺少: " + s.id);
        need(lessonData.stepLabels?.[s.id], "stepLabels 缺少: " + s.id);
        need(deco.steps?.[s.id], "step-decorations.steps 缺少: " + s.id);
        const policy = lessonData.policies?.[s.id];
        const range = policy?.range;
        const rangeMessage = policy?.movable === true
          ? "policies." + s.id + " 是可拖动步骤，必须显式提供 range"
          : "policies." + s.id + " 缺少 range；不可拖动步骤应由 normalizer 补齐";
        need(Array.isArray(range) && range.length >= 2, rangeMessage);
      }
    }

    const originalFigureIds = new Set((spec.originalFigures ?? []).map(fig => fig.id));
    for (const line of lessonData.problem?.lines ?? []) {
      for (const fig of line.figures ?? []) {
        need(originalFigureIds.has(fig.id), "problem.lines 原题图 id 未在 geometry-spec.originalFigures 中声明: " + fig.id);
      }
    }

    need(!hasHtmlString(lessonData.problem?.lines ?? []), "lesson-data.problem.lines 不能包含 HTML 字符串");
    need(!hasHtmlString(lessonData.ui?.legend ?? []), "lesson-data.ui.legend 不能包含 HTML 或 style 字符串");
    validatePointRefs(spec, deco);
    validateDecorationGeometryStyle(spec, deco);

    try {
      const renderer = GLS.createSpecRenderer(spec, deco, lessonData.steps, lessonData.policies);
      const svg0 = renderer.diagramMarkupFor(0);
      need(typeof svg0 === "string" && svg0.includes("<"), "diagramMarkupFor(0) 应输出 SVG 字符串");
      const firstStep = lessonData.steps?.[0];
      const mini = renderer.drawMini(firstStep?.t ?? trialValues[0] ?? 2, null, firstStep);
      need(typeof mini === "string" && mini.includes("<svg"), "drawMini(t) 应输出 <svg>");
    } catch (e) {
      errors.push("createSpecRenderer/diagramMarkupFor: " + e.message);
    }
  }
}

if (errors.length) {
  console.error("校验失败:\n" + errors.join("\n"));
  process.exit(1);
}

console.log("OK:", path.resolve(geometryPath));
