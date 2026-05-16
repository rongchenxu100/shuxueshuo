#!/usr/bin/env node
/**
 * Teaching-quality lint for compiled lesson specs.
 *
 * Usage:
 *   node tools/lint-lesson-quality.mjs internal/lesson-specs/<problem-id>/
 *   node tools/lint-lesson-quality.mjs --all-published
 *   node tools/lint-lesson-quality.mjs --config /path/to/lint-config.json internal/lesson-specs/<problem-id>/
 */
import fs from "fs";
import path from "path";

const repoRoot = path.resolve(process.cwd());
const DEFAULT_CONFIG = path.join(repoRoot, "internal/config/lint-config.json");
const KNOWLEDGE_FILE = path.join(repoRoot, "internal/knowledge-points/junior-math-methods.md");
const CASE_INDEX_FILE = path.join(repoRoot, "internal/knowledge-points/case-index.md");
const PROBLEMS_FILE = path.join(repoRoot, "site/data/problems.json");

const reports = [];

function usage() {
  console.error(
    "用法:\n" +
      "  node tools/lint-lesson-quality.mjs internal/lesson-specs/<problem-id>/\n" +
      "  node tools/lint-lesson-quality.mjs --all-published\n" +
      "  node tools/lint-lesson-quality.mjs --config /path/to/lint-config.json internal/lesson-specs/<problem-id>/"
  );
}

function report(level, problemId, code, message) {
  reports.push({ level, problemId: problemId || "-", code, message });
}

function readText(filePath) {
  return fs.readFileSync(filePath, "utf8");
}

function readJson(filePath) {
  return JSON.parse(readText(filePath));
}

function parseArgs(argv) {
  const args = [...argv];
  let configPath = DEFAULT_CONFIG;
  let allPublished = false;
  let target = null;

  while (args.length) {
    const arg = args.shift();
    if (arg === "--help" || arg === "-h") {
      usage();
      process.exit(0);
    }
    if (arg === "--all-published") {
      allPublished = true;
      continue;
    }
    if (arg === "--config") {
      const next = args.shift();
      if (!next) {
        usage();
        process.exit(1);
      }
      configPath = path.resolve(repoRoot, next);
      continue;
    }
    if (arg.startsWith("--")) {
      console.error("未知参数: " + arg);
      usage();
      process.exit(1);
    }
    if (target) {
      console.error("只能传入一个 lesson spec 目录。");
      usage();
      process.exit(1);
    }
    target = arg;
  }

  if ((allPublished && target) || (!allPublished && !target)) {
    usage();
    process.exit(1);
  }

  return { allPublished, target, configPath };
}

function stripBackticks(value) {
  return value.trim().replace(/^`+|`+$/g, "");
}

function parseKnowledgeIds() {
  const text = readText(KNOWLEDGE_FILE);
  const patterns = new Set();
  const methods = new Set();
  let inPatternSection = false;

  for (const line of text.split(/\r?\n/)) {
    if (/^##\s+题型标签/.test(line)) {
      inPatternSection = true;
      continue;
    }
    if (inPatternSection && /^##\s+/.test(line)) {
      inPatternSection = false;
    }
    if (inPatternSection) {
      const match = line.match(/^\|\s*(`?[a-z][a-z0-9-]+`?)\s*\|/);
      if (match) patterns.add(stripBackticks(match[1]));
    }
    const methodMatch = line.match(/^###\s+method:\s*([a-z][a-z0-9-]+)/);
    if (methodMatch) methods.add(methodMatch[1]);
  }

  return { patterns, methods };
}

function parseCaseIndex() {
  const text = readText(CASE_INDEX_FILE);
  const part1 = new Map();
  const part2 = new Map();
  let part = null;
  let group = null;

  for (const line of text.split(/\r?\n/)) {
    if (/^##\s+Part 1/.test(line)) {
      part = 1;
      group = null;
      continue;
    }
    if (/^##\s+Part 2/.test(line)) {
      part = 2;
      group = null;
      continue;
    }
    const heading = line.match(/^###\s+(.+?)\s*$/);
    if (heading && part) {
      group = stripBackticks(heading[1]);
      const target = part === 1 ? part1 : part2;
      if (!target.has(group)) target.set(group, new Set());
      continue;
    }
    if (!part || !group || !line.startsWith("|")) continue;
    const idMatch = line.match(/`([^`]+)`/);
    if (!idMatch) continue;
    const target = part === 1 ? part1 : part2;
    target.get(group).add(idMatch[1]);
  }

  return { part1, part2 };
}

function collectStrings(value, out = []) {
  if (typeof value === "string") out.push(value);
  else if (Array.isArray(value)) value.forEach((item) => collectStrings(item, out));
  else if (value && typeof value === "object") Object.values(value).forEach((item) => collectStrings(item, out));
  return out;
}

function stepText(step) {
  return [...collectStrings(step.derive ?? []), ...collectStrings(step.box ?? [])].join("\n");
}

function containsAllowedNegation(text, keywordIndex, allowIfPrecededBy, windowChars) {
  const start = Math.max(0, keywordIndex - windowChars);
  const before = text.slice(start, keywordIndex);
  return (allowIfPrecededBy ?? []).some((phrase) => before.includes(phrase));
}

function lintForbiddenKeywords(problemId, lessonData, config) {
  const windowChars = Number.isFinite(config.negationWindowChars) ? config.negationWindowChars : 8;
  for (const step of lessonData.steps ?? []) {
    const text = stepText(step);
    for (const item of config.forbiddenDeriveKeywords ?? []) {
      const keyword = item.keyword;
      if (!keyword) continue;
      let fromIndex = 0;
      while (fromIndex < text.length) {
        const index = text.indexOf(keyword, fromIndex);
        if (index === -1) break;
        if (!containsAllowedNegation(text, index, item.allowIfPrecededBy, windowChars)) {
          report(
            "ERROR",
            problemId,
            "FORBIDDEN_METHOD_KEYWORD",
            `step ${step.id || "(unknown)"} contains forbidden keyword "${keyword}"`
          );
        }
        fromIndex = index + keyword.length;
      }
    }
  }
}

function normalizeParam(value) {
  return String(value ?? "")
    .replace(/\s/g, "")
    .replace(/[=＝:：]/g, "")
    .trim();
}

function lintSuspiciousDraggableCoefficients(problemId, lessonData, geometrySpec, config) {
  const suspicious = new Set(config.suspiciousDraggableCoefficients ?? []);
  const candidates = [geometrySpec?.movingParam, lessonData.ui?.paramLabelPrefix].map(normalizeParam).filter(Boolean);
  const matched = candidates.filter((value) => suspicious.has(value));
  if (matched.length === 0) return;

  for (const [stepId, policy] of Object.entries(lessonData.policies ?? {})) {
    if (policy?.movable === true) {
      report(
        "WARN",
        problemId,
        "SUSPICIOUS_DRAGGABLE_COEFFICIENT",
        `step ${stepId} is movable while parameter "${matched[0]}" looks like a coefficient`
      );
    }
  }
}

function decorationText(item) {
  return [item.label, item.text, item.labelText].filter((value) => typeof value === "string").join(" ");
}

function walkDecorations(stepDecorations, callback) {
  for (const [layerName, layer] of Object.entries(stepDecorations.layers ?? {})) {
    for (const [index, item] of (layer.elements ?? []).entries()) {
      callback(item, { scope: "layer", id: layerName, index });
    }
  }
  for (const [stepId, step] of Object.entries(stepDecorations.steps ?? {})) {
    for (const [index, item] of (step.add ?? []).entries()) {
      callback(item, { scope: "step", id: stepId, index });
    }
  }
}

function lintRightAngleLabels(problemId, stepDecorations) {
  if (!stepDecorations) return;
  walkDecorations(stepDecorations, (item, loc) => {
    if (item?.type === "rightAngle" && /45\s*°/.test(decorationText(item))) {
      report(
        "ERROR",
        problemId,
        "RIGHT_ANGLE_LABEL_45",
        `${loc.scope} ${loc.id} decoration ${loc.index} is a rightAngle labelled as 45°`
      );
    }
  });
}

function normalizeMathText(value) {
  return String(value ?? "")
    .replace(/\s+/g, "")
    .replace(/[，,。.;；:：、]/g, "")
    .replace(/[（）()【】\[\]{}]/g, "")
    .trim();
}

function formulaTexts(item) {
  const texts = [];
  if (typeof item.text === "string") texts.push(item.text);
  if (typeof item.label === "string") texts.push(item.label);
  if (typeof item.labelText === "string") texts.push(item.labelText);
  for (const term of item.terms ?? []) {
    if (typeof term?.text === "string") texts.push(term.text);
  }
  return texts;
}

function lintFormulaCardDuplication(problemId, lessonData, stepDecorations, config) {
  if (!stepDecorations) return;
  const minLen = Number.isFinite(config.formulaCardMinMatchLength) ? config.formulaCardMinMatchLength : 6;
  const stepById = new Map((lessonData.steps ?? []).map((step) => [step.id, step]));
  for (const [stepId, decoStep] of Object.entries(stepDecorations.steps ?? {})) {
    const lessonStep = stepById.get(stepId);
    if (!lessonStep) continue;
    const source = normalizeMathText(stepText(lessonStep));
    if (!source) continue;
    for (const [index, item] of (decoStep.add ?? []).entries()) {
      if (item?.type !== "areaFormulaCard") continue;
      for (const text of formulaTexts(item)) {
        const normalized = normalizeMathText(text);
        if (normalized.length >= minLen && source.includes(normalized)) {
          report(
            "WARN",
            problemId,
            "FORMULA_CARD_DUPLICATES_DERIVE",
            `step ${stepId} areaFormulaCard ${index} repeats derive/box text "${text}"`
          );
          break;
        }
      }
    }
  }
}

function lintClassificationIds(problemId, lessonData, knowledge, mode) {
  const classification = lessonData.meta?.classification;
  if (!classification) {
    report(
      mode === "all-published" ? "ERROR" : "WARN",
      problemId,
      "CLASSIFICATION_MISSING",
      "lesson-data.json meta.classification is missing"
    );
    return null;
  }

  if (!knowledge.patterns.has(classification.pattern)) {
    report(
      "ERROR",
      problemId,
      "CLASSIFICATION_UNKNOWN_PATTERN",
      `unknown pattern "${classification.pattern}"`
    );
  }

  for (const method of classification.methods ?? []) {
    if (!knowledge.methods.has(method)) {
      report(
        "ERROR",
        problemId,
        "CLASSIFICATION_UNKNOWN_METHOD",
        `unknown method "${method}"`
      );
    }
  }

  return classification;
}

function groupsContaining(indexMap, problemId) {
  const groups = [];
  for (const [group, ids] of indexMap.entries()) {
    if (ids.has(problemId)) groups.push(group);
  }
  return groups;
}

function lintCaseIndexConsistency(problemId, classification, caseIndex, level) {
  if (!classification) return;

  const indexedPatterns = groupsContaining(caseIndex.part1, problemId);
  if (!caseIndex.part1.get(classification.pattern)?.has(problemId)) {
    report(
      level,
      problemId,
      "CASE_INDEX_PATTERN_MISSING",
      `case-index Part 1 is missing this problem under pattern "${classification.pattern}"`
    );
  }
  for (const pattern of indexedPatterns) {
    if (pattern !== classification.pattern) {
      report(
        level,
        problemId,
        "CASE_INDEX_PATTERN_MISMATCH",
        `case-index Part 1 lists this problem under "${pattern}", but classification uses "${classification.pattern}"`
      );
    }
  }

  const classifiedMethods = new Set(classification.methods ?? []);
  for (const method of classifiedMethods) {
    if (!caseIndex.part2.get(method)?.has(problemId)) {
      report(
        level,
        problemId,
        "CASE_INDEX_METHOD_MISSING",
        `case-index Part 2 is missing this problem under method "${method}"`
      );
    }
  }

  for (const method of groupsContaining(caseIndex.part2, problemId)) {
    if (!classifiedMethods.has(method)) {
      report(
        level,
        problemId,
        "CASE_INDEX_METHOD_MISMATCH",
        `case-index Part 2 lists this problem under "${method}", but classification does not`
      );
    }
  }
}

function loadSpecFiles(specDir) {
  const lessonPath = path.join(specDir, "lesson-data.json");
  const geometryPath = path.join(specDir, "geometry-spec.json");
  const decorationsPath = path.join(specDir, "step-decorations.json");
  const lessonData = readJson(lessonPath);
  return {
    lessonData,
    geometrySpec: fs.existsSync(geometryPath) ? readJson(geometryPath) : null,
    stepDecorations: fs.existsSync(decorationsPath) ? readJson(decorationsPath) : null
  };
}

function lintSpecDir(specDir, context) {
  const { config, knowledge, caseIndex, mode } = context;
  const resolvedDir = path.resolve(repoRoot, specDir);
  const { lessonData, geometrySpec, stepDecorations } = loadSpecFiles(resolvedDir);
  const problemId = lessonData.meta?.id || path.basename(resolvedDir);

  lintForbiddenKeywords(problemId, lessonData, config);
  lintSuspiciousDraggableCoefficients(problemId, lessonData, geometrySpec, config);
  lintRightAngleLabels(problemId, stepDecorations);
  lintFormulaCardDuplication(problemId, lessonData, stepDecorations, config);
  const classification = lintClassificationIds(problemId, lessonData, knowledge, mode);
  const caseIndexLevel = mode === "all-published" ? "ERROR" : "WARN";
  lintCaseIndexConsistency(problemId, classification, caseIndex, caseIndexLevel);
}

function lintAllPublished(context) {
  const problems = readJson(PROBLEMS_FILE);
  for (const problem of problems) {
    if (problem.status !== "published") continue;
    const specDir = path.join(repoRoot, "internal/lesson-specs", problem.id);
    const lessonDataPath = path.join(specDir, "lesson-data.json");
    if (!fs.existsSync(lessonDataPath)) {
      report(
        "INFO",
        problem.id,
        "PUBLISHED_MARKDOWN_ONLY_SKIPPED",
        "published problem has no complete lesson-data.json spec; skipping quality lint"
      );
      continue;
    }
    lintSpecDir(specDir, { ...context, mode: "all-published" });
  }
}

function printReports() {
  for (const item of reports) {
    if (item.level === "INFO") {
      console.log(`INFO ${item.problemId} ${item.code}: ${item.message}`);
    } else {
      console.log(`${item.level} ${item.problemId} ${item.code}: ${item.message}`);
    }
  }
  const errors = reports.filter((item) => item.level === "ERROR").length;
  const warnings = reports.filter((item) => item.level === "WARN").length;
  const infos = reports.filter((item) => item.level === "INFO").length;
  console.log(`summary: errors=${errors} warnings=${warnings} infos=${infos}`);
  return errors;
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const config = readJson(args.configPath);
  const knowledge = parseKnowledgeIds();
  const caseIndex = parseCaseIndex();
  const context = { config, knowledge, caseIndex, mode: "single" };

  if (args.allPublished) {
    lintAllPublished(context);
  } else {
    lintSpecDir(args.target, context);
  }

  const errors = printReports();
  process.exit(errors > 0 ? 1 : 0);
}

try {
  main();
} catch (error) {
  console.error("lint-lesson-quality failed: " + (error?.stack || error?.message || error));
  process.exit(1);
}
