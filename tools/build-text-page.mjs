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

function relationMath(symbol) {
  const commands = {
    "∈": "\\in",
    "∉": "\\notin",
    "⊆": "\\subseteq",
    "⊊": "\\subsetneq",
    "⊇": "\\supseteq",
    "⊋": "\\supsetneq",
  };
  return setMath(commands[symbol] ?? symbol);
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
      return "答案：" + schema.expected.map(relationMath).join("，");
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
    case "multipart-choice": {
      const parts = (schema.expected ?? []).map((item, index) => (
        (item.label ?? "（" + (index + 1) + "）") + item.expected
      ));
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
  if (problem.keyPoints?.kind === "linear-combination-range-flow") {
    const { inputs, stages, result } = problem.keyPoints;
    if (!Array.isArray(inputs) || inputs.length < 2 || inputs.some((item) => typeof item !== "string" || !item.trim())) {
      throw new Error(`${meta.id} 的 problem.keyPoints.inputs 至少需要两个抽象输入`);
    }
    if (!Array.isArray(stages) || stages.length !== 3) {
      throw new Error(`${meta.id} 的 problem.keyPoints.stages 必须包含重组、求界、相加三个阶段`);
    }
    const expectedLabels = ["重组", "求界", "相加"];
    const expectedVisuals = ["regroup", "bound", "add"];
    if (stages.some((stage, index) => stage?.label !== expectedLabels[index] || stage?.visual !== expectedVisuals[index])) {
      throw new Error(`${meta.id} 的三阶段标签或图解类型不符合重组、求界、相加规范`);
    }
    for (const [index, stage] of stages.entries()) {
      if (!stage?.label || !stage?.method || !Array.isArray(stage.content) || stage.content.length === 0 || stage.content.some((line) => typeof line !== "string" || !line.trim())) {
        throw new Error(`${meta.id} 的 problem.keyPoints.stages[${index}] 缺少标签、方法或内容`);
      }
    }
    if (typeof result !== "string" || !result.trim()) {
      throw new Error(`${meta.id} 的 problem.keyPoints.result 不能为空`);
    }
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
    if (step.visual?.kind === "basic-inequality-structure-scan") {
      const visual = step.visual;
      if ([visual.reading, visual.route].some((value) => typeof value !== "string" || !value.trim())) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual 观察结构缺少结构读法或方法入口`);
      }
      if (visual.title !== undefined && (typeof visual.title !== "string" || !visual.title.trim())) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.title 必须是非空字符串`);
      }
      if (visual.showFocus !== undefined && typeof visual.showFocus !== "boolean") {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.showFocus 必须是布尔值`);
      }
      for (const field of ["condition", "target"]) {
        const panel = visual[field];
        if (!panel || typeof panel !== "object" || typeof panel.expression !== "string" || !panel.expression.trim()) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.${field} 必须包含非空 expression`);
        }
        if (panel.label !== undefined && (typeof panel.label !== "string" || !panel.label.trim())) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.${field}.label 必须是非空字符串`);
        }
        if (panel.tag !== undefined && (typeof panel.tag !== "string" || !panel.tag.trim())) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.${field}.tag 必须是非空字符串`);
        }
      }
      if (visual.pattern !== undefined) {
        const pattern = visual.pattern;
        if (!pattern || typeof pattern !== "object") {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.pattern 必须是观察结构对象`);
        }
        for (const field of ["first", "second"]) {
          const term = pattern[field];
          if (!term || typeof term.value !== "string" || !term.value.trim() || !new Set(["square", "circle"]).has(term.shape)) {
            throw new Error(`${meta.id} 的步骤 ${step.id}.visual.pattern.${field} 必须包含正项与方框或圆框`);
          }
        }
        for (const field of ["condition", "target"]) {
          const row = pattern[field];
          if (!row || [row.operator, row.tag].some((value) => typeof value !== "string" || !value.trim())) {
            throw new Error(`${meta.id} 的步骤 ${step.id}.visual.pattern.${field} 必须包含运算符与结构标签`);
          }
        }
      }
      if (visual.caption !== undefined && (typeof visual.caption !== "string" || !visual.caption.trim())) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.caption 必须是非空字符串`);
      }
      if (visual.organization !== undefined) {
        const organization = visual.organization;
        if (!organization || typeof organization !== "object") {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization 必须是整理对象`);
        }
        if (organization.label !== undefined && (typeof organization.label !== "string" || !organization.label.trim())) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.label 必须是非空字符串`);
        }
        const organizationSteps = Array.isArray(organization.steps) ? organization.steps : [];
        if (
          !organizationSteps.length
          && organization.substitutionHint === undefined
          && organization.eliminationHint === undefined
          && organization.homogenizationHint === undefined
          && organization.localHomogenizationHint === undefined
          && organization.termSpot === undefined
          && organization.slotHint === undefined
          && organization.expandHint === undefined
          && organization.combineHint === undefined
          && organization.squareHint === undefined
          && organization.baseHint === undefined
          && organization.alignmentHint === undefined
          && organization.relationCountHint === undefined
          && organization.symmetryHint === undefined
        ) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization 必须包含整理公式或规则图`);
        }
        organizationSteps.forEach((item, index) => {
          if (typeof item === "string") {
            if (!item.trim()) {
              throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.steps[${index}] 必须是非空公式`);
            }
            return;
          }
          if (!item || typeof item !== "object" || typeof item.expression !== "string" || !item.expression.trim()) {
            throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.steps[${index}] 必须包含非空 expression`);
          }
          if (item.label !== undefined && (typeof item.label !== "string" || !item.label.trim())) {
            throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.steps[${index}].label 必须是非空字符串`);
          }
          if (item.marks !== undefined) {
            const marks = item.marks;
            if (!marks || typeof marks !== "object") {
              throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.steps[${index}].marks 必须是对象`);
            }
            for (const field of ["bracket", "bypass"]) {
              if (marks[field] !== undefined && (typeof marks[field] !== "string" || !marks[field].trim())) {
                throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.steps[${index}].marks.${field} 必须是非空字符串`);
              }
            }
          }
        });
        if (organization.motive !== undefined && (typeof organization.motive !== "string" || !organization.motive.trim())) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.motive 必须是非空字符串`);
        }
        if (organization.note !== undefined && (typeof organization.note !== "string" || !organization.note.trim())) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.note 必须是非空字符串`);
        }
        if (organization.slotHint !== undefined) {
          const slotHint = organization.slotHint;
          if (!slotHint || typeof slotHint !== "object" || typeof slotHint.numerator !== "string" || !slotHint.numerator.trim() || typeof slotHint.value !== "string" || !slotHint.value.trim()) {
            throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.slotHint 必须包含非空 numerator 与 value`);
          }
          if (slotHint.rewrite !== undefined) {
            const rewrite = slotHint.rewrite;
            if (!rewrite || typeof rewrite !== "object" || typeof rewrite.source !== "string" || !rewrite.source.trim()) {
              throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.slotHint.rewrite 必须包含非空 source`);
            }
            if (rewrite.note !== undefined && (typeof rewrite.note !== "string" || !rewrite.note.trim())) {
              throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.slotHint.rewrite.note 必须是非空字符串`);
            }
          }
        }
        if (organization.expandHint !== undefined) {
          const expandHint = organization.expandHint;
          if (!expandHint || typeof expandHint !== "object" || typeof expandHint.action !== "string" || !expandHint.action.trim()) {
            throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.expandHint 必须包含非空 action`);
          }
          if (expandHint.note !== undefined && (typeof expandHint.note !== "string" || !expandHint.note.trim())) {
            throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.expandHint.note 必须是非空字符串`);
          }
          if (expandHint.ariaLabel !== undefined && (typeof expandHint.ariaLabel !== "string" || !expandHint.ariaLabel.trim())) {
            throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.expandHint.ariaLabel 必须是非空字符串`);
          }
        }
        if (organization.combineHint !== undefined) {
          const combineHint = organization.combineHint;
          if (!combineHint || typeof combineHint !== "object" || typeof combineHint.action !== "string" || !combineHint.action.trim()) {
            throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.combineHint 必须包含非空 action`);
          }
          for (const field of ["note", "mark", "ariaLabel"]) {
            if (combineHint[field] !== undefined && (typeof combineHint[field] !== "string" || !combineHint[field].trim())) {
              throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.combineHint.${field} 必须是非空字符串`);
            }
          }
        }
        if (organization.alignmentHint !== undefined) {
          const alignmentHint = organization.alignmentHint;
          if (!alignmentHint || typeof alignmentHint !== "object" || alignmentHint.kind !== "condition-positive-term-alignment") {
            throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.alignmentHint 必须是 condition-positive-term-alignment 整理提示`);
          }
          for (const field of ["method", "conditionLabel", "linkLabel", "targetLabel", "productLabel", "product"]) {
            if (typeof alignmentHint[field] !== "string" || !alignmentHint[field].trim()) {
              throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.alignmentHint.${field} 必须是非空字符串`);
            }
          }
          const alignmentCondition = alignmentHint.condition;
          const alignmentTarget = alignmentHint.target;
          if (!alignmentCondition || typeof alignmentCondition !== "object" || typeof alignmentCondition.fixed !== "string" || !alignmentCondition.fixed.trim()) {
            throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.alignmentHint.condition 必须包含定积`);
          }
          if (!alignmentTarget || typeof alignmentTarget !== "object" || [alignmentTarget.constant, alignmentTarget.constantLabel].some((value) => typeof value !== "string" || !value.trim())) {
            throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.alignmentHint.target 必须包含旁置常数`);
          }
          for (const [groupName, group, requiresCoefficient] of [["condition", alignmentCondition, false], ["target", alignmentTarget, true]]) {
            for (const termName of ["first", "second"]) {
              const term = group[termName];
              if (!term || typeof term.value !== "string" || !term.value.trim() || !new Set(["square", "circle"]).has(term.shape) || (requiresCoefficient && (typeof term.coefficient !== "string" || !term.coefficient.trim()))) {
                throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.alignmentHint.${groupName}.${termName} 缺少完整正项、系数或槽位形状`);
              }
            }
          }
          if (alignmentHint.ariaLabel !== undefined && (typeof alignmentHint.ariaLabel !== "string" || !alignmentHint.ariaLabel.trim())) {
            throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.alignmentHint.ariaLabel 必须是非空字符串`);
          }
        }
        if (organization.substitutionHint !== undefined) {
          const hint = organization.substitutionHint;
          if (!hint || typeof hint !== "object" || !Array.isArray(hint.mappings) || !hint.mappings.length) {
            throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.substitutionHint 必须包含非空 mappings`);
          }
          hint.mappings.forEach((mapping, index) => {
            const kind = mapping?.kind === "radical" ? "radical" : "denominator";
            const requiredFields = kind === "radical"
              ? ["source", "variable", "assignment"]
              : ["numerator", "denominator", "variable", "assignment"];
            for (const field of requiredFields) {
              if (!mapping || typeof mapping[field] !== "string" || !mapping[field].trim()) {
                throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.substitutionHint.mappings[${index}].${field} 必须是非空字符串`);
              }
            }
            if (mapping?.kind !== undefined && !new Set(["denominator", "radical"]).has(mapping.kind)) {
              throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.substitutionHint.mappings[${index}].kind 必须是 denominator 或 radical`);
            }
          });
          if (hint.ariaLabel !== undefined && (typeof hint.ariaLabel !== "string" || !hint.ariaLabel.trim())) {
            throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.substitutionHint.ariaLabel 必须是非空字符串`);
          }
        }
        if (organization.eliminationHint !== undefined) {
          const hint = organization.eliminationHint;
          const requiredFields = ["variable", "isolated", "independentVariable", "targetBefore", "targetAfter"];
          if (!hint || typeof hint !== "object" || requiredFields.some((field) => typeof hint[field] !== "string" || !hint[field].trim())) {
            throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.eliminationHint 必须完整复用条件消元结构图`);
          }
          if (hint.ariaLabel !== undefined && (typeof hint.ariaLabel !== "string" || !hint.ariaLabel.trim())) {
            throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.eliminationHint.ariaLabel 必须是非空字符串`);
          }
        }
        if (organization.homogenizationHint !== undefined) {
          const hint = organization.homogenizationHint;
          const requiredFields = [
            "originalLabel", "original", "originalDegree",
            "conditionLabel", "condition", "conditionDegree",
            "resultDegree", "resultLabel", "result", "balance",
          ];
          if (!hint || typeof hint !== "object" || requiredFields.some((field) => typeof hint[field] !== "string" || !hint[field].trim())) {
            throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.homogenizationHint 必须完整复用配齐次式结构图`);
          }
          if (hint.ariaLabel !== undefined && (typeof hint.ariaLabel !== "string" || !hint.ariaLabel.trim())) {
            throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.homogenizationHint.ariaLabel 必须是非空字符串`);
          }
        }
        if (organization.localHomogenizationHint !== undefined) {
          const hint = organization.localHomogenizationHint;
          const requiredFields = [
            "originalLabel", "original", "originalDegree",
            "conditionLabel", "condition", "conditionDegree",
            "resultDegree", "resultLabel", "result", "balance",
          ];
          if (!hint || typeof hint !== "object" || requiredFields.some((field) => typeof hint[field] !== "string" || !hint[field].trim())) {
            throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.localHomogenizationHint 必须完整复用配齐次式核心公式图`);
          }
          for (const field of ["method", "scopeNote", "ariaLabel"]) {
            if (hint[field] !== undefined && (typeof hint[field] !== "string" || !hint[field].trim())) {
              throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.localHomogenizationHint.${field} 必须是非空字符串`);
            }
          }
          if (hint.scopes !== undefined) {
            if (!Array.isArray(hint.scopes) || !hint.scopes.length) {
              throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.localHomogenizationHint.scopes 必须是非空数组`);
            }
            hint.scopes.forEach((scope, index) => {
              if (!scope || typeof scope !== "object" || typeof scope.label !== "string" || !scope.label.trim() || typeof scope.expression !== "string" || !scope.expression.trim()) {
                throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.localHomogenizationHint.scopes[${index}] 必须包含非空 label 与 expression`);
              }
            });
          }
        }
        if (organization.termSpot !== undefined) {
          const termSpot = organization.termSpot;
          if (!termSpot || typeof termSpot !== "object" || !Array.isArray(termSpot.factors) || !termSpot.factors.length) {
            throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.termSpot 必须包含非空 factors`);
          }
          for (const field of ["label", "join", "ariaLabel"]) {
            if (termSpot[field] !== undefined && (typeof termSpot[field] !== "string" || !termSpot[field].trim())) {
              throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.termSpot.${field} 必须是非空字符串`);
            }
          }
          termSpot.factors.forEach((factor, factorIndex) => {
            if (!factor || typeof factor !== "object" || !Array.isArray(factor.terms) || !factor.terms.length) {
              throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.termSpot.factors[${factorIndex}] 必须包含非空 terms`);
            }
            factor.terms.forEach((term, termIndex) => {
              if (!term || typeof term !== "object" || typeof term.value !== "string" || !term.value.trim()) {
                throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.termSpot.factors[${factorIndex}].terms[${termIndex}] 必须包含非空 value`);
              }
              if (term.role !== undefined && !new Set(["spot", "keep", "plain"]).has(term.role)) {
                throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.termSpot.factors[${factorIndex}].terms[${termIndex}].role 必须是 spot、keep 或 plain`);
              }
              if (term.mark !== undefined && (typeof term.mark !== "string" || !term.mark.trim())) {
                throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.termSpot.factors[${factorIndex}].terms[${termIndex}].mark 必须是非空字符串`);
              }
            });
          });
        }
        if (organization.relationCountHint !== undefined) {
          const hint = organization.relationCountHint;
          if (!hint || typeof hint !== "object") {
            throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.relationCountHint 必须是关系缺口判断图`);
          }
          for (const field of ["ariaLabel"]) {
            if (typeof hint[field] !== "string" || !hint[field].trim()) {
              throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.relationCountHint.${field} 必须是非空字符串`);
            }
          }
          if (hint.substitution !== undefined) {
            throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.relationCountHint 已直接使用本题数值，不应再显示代入行`);
          }
          if (hint.conclusion !== undefined) {
            throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.relationCountHint 不应重复显示应用次数结论`);
          }
          for (const field of ["variable", "condition", "result"]) {
            const item = hint[field];
            if (!item || typeof item !== "object" || [item.label, item.value].some((value) => typeof value !== "string" || !value.trim())) {
              throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.relationCountHint.${field} 必须包含标签与数值`);
            }
            if (item.symbol !== undefined) {
              throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.relationCountHint.${field} 应直接使用数值，不引入抽象符号`);
            }
            for (const optionalField of ["detail"]) {
              if (item[optionalField] !== undefined && (typeof item[optionalField] !== "string" || !item[optionalField].trim())) {
                throw new Error(`${meta.id} 的步骤 ${step.id}.visual.organization.relationCountHint.${field}.${optionalField} 必须是非空字符串`);
              }
            }
          }
        }
      }
    }
    if (step.visual?.kind === "basic-inequality-mapping") {
      const visual = step.visual;
      const requiredFields = [
        "template",
        "mapped",
        "replaced",
        "substituted",
        "conclusion",
      ];
      if (visual.formulaStyle !== "square-sum") {
        requiredFields.push("fixedCondition");
      }
      if (requiredFields.some((field) => typeof visual[field] !== "string" || !visual[field].trim())) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual 基本不等式映射缺少公式或结论`);
      }
      for (const field of ["title", "templateLabel"]) {
        if (visual[field] !== undefined && (typeof visual[field] !== "string" || !visual[field].trim())) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.${field} 必须是非空字符串`);
        }
      }
      if (visual.formulaStyle !== undefined && !new Set(["fraction-geometric", "sum-geometric", "square-sum"]).has(visual.formulaStyle)) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.formulaStyle 不是受支持的公式样式`);
      }
      if (visual.showPositiveStep !== undefined && typeof visual.showPositiveStep !== "boolean") {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.showPositiveStep 必须是布尔值`);
      }
      const equalityFields = ["equalityTemplate", "equalityMapped", "equalityResult"];
      const equalityPresent = equalityFields.filter((field) => visual[field] !== undefined);
      if (equalityPresent.length && (equalityPresent.length !== equalityFields.length || equalityFields.some((field) => typeof visual[field] !== "string" || !visual[field].trim()))) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual 等号条件字段必须同时给出且非空，或全部省略`);
      }
      if (!Array.isArray(visual.mappings) || visual.mappings.length !== 2) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.mappings 必须包含两个公式槽位`);
      }
      visual.mappings.forEach((mapping, index) => {
        if ([mapping?.slot, mapping?.value, mapping?.condition].some((value) => typeof value !== "string" || !value.trim())) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.mappings[${index}] 缺少槽位、题目变量或正数条件`);
        }
      });
      for (const field of ["mappedSum", "mappedProduct"]) {
        if (visual[field] !== undefined && (typeof visual[field] !== "string" || !visual[field].trim())) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.${field} 必须是非空公式`);
        }
      }
      if (visual.fixedSourceTarget !== undefined && !new Set(["sum", "product"]).has(visual.fixedSourceTarget)) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.fixedSourceTarget 只能是 sum 或 product`);
      }
      if (visual.conditionFlow && (!Array.isArray(visual.conditionFlow) || visual.conditionFlow.length < 2 || visual.conditionFlow.some((item) => typeof item !== "string" || !item.trim()))) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.conditionFlow 必须包含至少两个有效公式`);
      }
    }
    if (step.visual?.kind === "basic-inequality-equality-check") {
      const visual = step.visual;
      const equalities = Array.isArray(visual.equalities) ? visual.equalities : [];
      const requiredFields = equalities.length
        ? ["templateLabel", "solved", "verificationLabel", "verification", "conclusion"]
        : ["templateLabel", "conditionLabel", "condition", "solved", "verificationLabel", "verification", "conclusion"];
      if (requiredFields.some((field) => typeof visual[field] !== "string" || !visual[field].trim())) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual 验证取等缺少条件、结果或结论`);
      }
      const validateEqualityTerm = (term, fieldPath) => {
        if (!term || typeof term.value !== "string" || !term.value.trim() || !new Set(["square", "circle"]).has(term.shape)) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.${fieldPath} 必须包含正项与方框或圆框`);
        }
      };
      if (equalities.length) {
        if (equalities.length < 2) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.equalities 至少包含两组待联立的取等条件`);
        }
        equalities.forEach((item, index) => {
          if (!item || [item.label, item.result].some((value) => typeof value !== "string" || !value.trim())) {
            throw new Error(`${meta.id} 的步骤 ${step.id}.visual.equalities[${index}] 缺少标签或单组求解结果`);
          }
          validateEqualityTerm(item.first, `equalities[${index}].first`);
          validateEqualityTerm(item.second, `equalities[${index}].second`);
        });
      } else {
        validateEqualityTerm(visual.first, "first");
        validateEqualityTerm(visual.second, "second");
      }
    }
    if (step.visual?.kind === "repeated-basic-inequality-flow") {
      const visual = step.visual;
      const mode = visual.mode || "full";
      if (mode !== "full") {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.mode 不是受支持的连续估计模式`);
      }
      if ([visual.title, visual.methodTag, visual.conclusion].some((value) => typeof value !== "string" || !value.trim())) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual 连续估计缺少标题、方法标签或结论`);
      }
      const count = visual.count;
      if (!count || !Array.isArray(count.variables) || count.variables.length < 1 || !Array.isArray(count.conditions) || !Number.isInteger(count.estimatedRounds) || count.estimatedRounds < 1) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.count 必须包含变量、有效条件与预计轮数`);
      }
      if (count.estimatedRelations !== undefined && (!Number.isInteger(count.estimatedRelations) || count.estimatedRelations < count.estimatedRounds)) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.count.estimatedRelations 必须是不小于基本不等式轮数的正整数`);
      }
      if (count.relationSources !== undefined && (!Array.isArray(count.relationSources) || count.relationSources.length < 1 || count.relationSources.some((value) => typeof value !== "string" || !value.trim()))) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.count.relationSources 必须列出取等关系的来源`);
      }
      if (visual.preparation) {
        const preparation = visual.preparation;
        if ([preparation.label, preparation.current, preparation.result, preparation.insight].some((value) => typeof value !== "string" || !value.trim()) || !Array.isArray(preparation.flow) || preparation.flow.length < 1 || preparation.flow.some((value) => typeof value !== "string" || !value.trim())) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.preparation 缺少整理过程、结果或观察结论`);
        }
      }
      const expectedRounds = count.estimatedRounds;
      if (!Array.isArray(visual.rounds) || visual.rounds.length !== expectedRounds) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.rounds 必须与预计轮数一致`);
      }
      visual.rounds.forEach((round, index) => {
        if ([round?.current, round?.reason, round?.relation, round?.inequality, round?.result, round?.insight, round?.equality].some((value) => typeof value !== "string" || !value.trim())) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.rounds[${index}] 缺少当前式、配对理由、推导、结果或取等条件`);
        }
        if (!Array.isArray(round.terms) || round.terms.length !== 2 || round.terms.some((value) => typeof value !== "string" || !value.trim())) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.rounds[${index}].terms 必须包含两个正项`);
        }
        if (round.afterward) {
          const afterward = round.afterward;
          if ([afterward.label, afterward.current, afterward.observation, afterward.result, afterward.insight].some((value) => typeof value !== "string" || !value.trim()) || !Array.isArray(afterward.flow) || afterward.flow.length < 1 || afterward.flow.some((value) => typeof value !== "string" || !value.trim())) {
            throw new Error(`${meta.id} 的步骤 ${step.id}.visual.rounds[${index}].afterward 缺少新式整理过程或平方取等条件`);
          }
        }
      });
      const equality = visual.equality;
      const requiredEqualityCount = Number.isInteger(count.estimatedRelations) ? count.estimatedRelations : visual.rounds.length;
      if (!equality || !Array.isArray(equality.conditions) || equality.conditions.length < requiredEqualityCount || [equality.solved, equality.verification].some((value) => typeof value !== "string" || !value.trim())) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.equality 缺少取等条件、联立结果或检验`);
      }
    }
    if (["substitution-homogeneous-lifecycle", "substitution-basic-inequality-lifecycle", "elimination-basic-inequality-lifecycle"].includes(step.visual?.kind)) {
      const visual = step.visual;
      const substitution = visual.substitution;
      const elimination = visual.elimination;
      const homogeneous = visual.homogeneous;
      const basicInequality = visual.basicInequality;
      const restoration = visual.restoration;
      const usesElimination = visual.kind === "elimination-basic-inequality-lifecycle";
      const usesBasicInequality = visual.kind !== "substitution-homogeneous-lifecycle";
      if ([visual.title, visual.methodTag, visual.conclusion].some((value) => typeof value !== "string" || !value.trim())) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual 换元闭环缺少标题、方法标签或结论`);
      }
      if ((!usesElimination && !substitution) || (usesElimination && !elimination) || !restoration || (usesBasicInequality ? !basicInequality : !homogeneous)) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual 降维流程缺少入口步骤、求值方法或 restoration`);
      }
      if (usesElimination) {
        if ([elimination.label, elimination.observation, elimination.condition, elimination.target].some((value) => typeof value !== "string" || !value.trim())) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.elimination 缺少标题、观察、条件或一元目标`);
        }
        for (const field of ["conditionFlow", "isolateFlow", "targetFlow"]) {
          if (!Array.isArray(elimination[field]) || elimination[field].length < 2 || elimination[field].some((value) => typeof value !== "string" || !value.trim())) {
            throw new Error(`${meta.id} 的步骤 ${step.id}.visual.elimination.${field} 必须包含至少两个有效公式`);
          }
        }
      } else {
        if (!Array.isArray(substitution.mappings) || substitution.mappings.length < 1 || substitution.mappings.length > 2) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.substitution.mappings 必须包含一至两个完整换元映射`);
        }
        substitution.mappings.forEach((mapping, index) => {
          if ([mapping?.source, mapping?.target, mapping?.reverse].some((value) => typeof value !== "string" || !value.trim())) {
            throw new Error(`${meta.id} 的步骤 ${step.id}.visual.substitution.mappings[${index}] 缺少原整体、新变量或反向关系`);
          }
        });
        if ([substitution.condition, substitution.target].some((value) => typeof value !== "string" || !value.trim())) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.substitution 缺少换元后的条件或目标`);
        }
        if (substitution.rearrangement !== undefined) {
          const rearrangement = substitution.rearrangement;
          if ([rearrangement?.label, rearrangement?.before, rearrangement?.result].some((value) => typeof value !== "string" || !value.trim())) {
            throw new Error(`${meta.id} 的步骤 ${step.id}.visual.substitution.rearrangement 缺少标题、整理前目标或整理结果`);
          }
          if (!Array.isArray(rearrangement.identities) || rearrangement.identities.length !== 2 || rearrangement.identities.some((value) => typeof value !== "string" || !value.trim())) {
            throw new Error(`${meta.id} 的步骤 ${step.id}.visual.substitution.rearrangement.identities 必须包含两个有效的分式整理公式`);
          }
          if (rearrangement.conditionFlow !== undefined && (!Array.isArray(rearrangement.conditionFlow) || rearrangement.conditionFlow.length < 2 || rearrangement.conditionFlow.some((value) => typeof value !== "string" || !value.trim()))) {
            throw new Error(`${meta.id} 的步骤 ${step.id}.visual.substitution.rearrangement.conditionFlow 必须包含至少两个有效的条件整理公式`);
          }
        }
      }
      const inequalityMethod = usesBasicInequality ? basicInequality : homogeneous;
      if (!usesBasicInequality) {
        if (!Array.isArray(homogeneous.degrees) || homogeneous.degrees.length !== 3) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.homogeneous.degrees 必须展示正一次、负一次与零次结果`);
        }
        homogeneous.degrees.forEach((item, index) => {
          if ([item?.label, item?.expression, item?.degree].some((value) => typeof value !== "string" || !value.trim())) {
            throw new Error(`${meta.id} 的步骤 ${step.id}.visual.homogeneous.degrees[${index}] 缺少次数信息`);
          }
        });
        if (typeof homogeneous.identity !== "string" || !homogeneous.identity.trim()) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.homogeneous 缺少配齐次恒等式`);
        }
      }
      if (!Array.isArray(inequalityMethod.positiveTerms) || inequalityMethod.positiveTerms.length !== 2) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual 求值方法必须包含两个正项`);
      }
      inequalityMethod.positiveTerms.forEach((item, index) => {
        if ([item?.value, item?.condition].some((value) => typeof value !== "string" || !value.trim())) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual 求值方法的 positiveTerms[${index}] 缺少公式或正数条件`);
        }
      });
      if ([inequalityMethod.label, inequalityMethod.methodTag, inequalityMethod.product, inequalityMethod.inequality, inequalityMethod.bound, inequalityMethod.equality, inequalityMethod.equalitySolved].some((value) => typeof value !== "string" || !value.trim())) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual 求值方法缺少标题、基本不等式或取等结论`);
      }
      if (inequalityMethod.relationLabel !== undefined && (typeof inequalityMethod.relationLabel !== "string" || !inequalityMethod.relationLabel.trim())) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual 求值方法的 relationLabel 必须是非空说明`);
      }
      if ([restoration.transformedEquality, restoration.solved, restoration.reverse, restoration.result, restoration.verification].some((value) => typeof value !== "string" || !value.trim())) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.restoration 缺少反向还原链条`);
      }
      if (restoration.variableLabel !== undefined && (typeof restoration.variableLabel !== "string" || !restoration.variableLabel.trim())) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.restoration.variableLabel 必须是非空原变量名称`);
      }
    }
    if (step.visual?.kind === "symmetric-reduction-flow") {
      const visual = step.visual;
      if (!visual.title || !visual.goal?.expression || !visual.goal?.task) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual 对称消元流程缺少标题或目标`);
      }
      if (visual.variant === "normalize-before-symmetry") {
        const preparation = visual.preparation;
        if (!visual.symmetryVariables || !preparation || ["observation", "substitution", "target", "conclusion"].some((field) => !preparation[field])
          || !Array.isArray(preparation.conditionFlow) || preparation.conditionFlow.length < 2
          || preparation.conditionFlow.some((item) => typeof item !== "string" || !item.trim())) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.preparation 必须先完整展示观察、缩放换元与条件变形，再校验对称`);
        }
      } else if (visual.preparation !== undefined) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual 只有 normalize-before-symmetry 变式可以提供 preparation`);
      }
      if (!Array.isArray(visual.symmetryChecks) || visual.symmetryChecks.length !== 2
        || visual.symmetryChecks.some((item) => (
          !item?.label || !item?.original || !item?.swapped || !item?.verdict
        ))) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.symmetryChecks 必须分别检查目标与条件`);
      }
      const requiredObjects = ["substitution", "elimination", "closure"];
      if (requiredObjects.some((field) => !visual[field] || typeof visual[field] !== "object" || Array.isArray(visual[field]))) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual 对称消元流程缺少换元、基本不等式消元或范围闭包`);
      }
      if (!Array.isArray(visual.substitution.definitions) || visual.substitution.definitions.length !== 2
        || visual.substitution.definitions.some((item) => typeof item !== "string" || !item.trim())
        || ["identity", "condition", "solved"].some((field) => !visual.substitution[field])) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.substitution 必须完整定义 s、p 并改写条件`);
      }
      if (["label", "relationLabel", "relation", "basis", "substitutionLabel", "substituted", "expanded", "simplified", "range"].some((field) => !visual.elimination[field])) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.elimination 必须分行展示基本不等式关系与代入消元过程`);
      }
      if (["question", "equalityLabel", "equalityCondition", "conclusion"].some((field) => !visual.closure[field])
        || !Array.isArray(visual.closure.endpoints) || visual.closure.endpoints.length < 1 || visual.closure.endpoints.length > 2
        || visual.closure.endpoints.some((item) => !item?.value || !item?.boundaryCondition || !item?.witness || !item?.verification)) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.closure 必须给出基本不等式的取等条件，并分别验证上下边界`);
      }
    }
    if (step.visual?.kind === "symmetric-objective-reduction") {
      const visual = step.visual;
      if (!visual.title || !visual.goal?.expression || !visual.goal?.task
        || !visual.symmetryCheck?.original || !visual.symmetryCheck?.swapped || !visual.symmetryCheck?.verdict) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual 对称目标降维流程缺少目标或交换校验`);
      }
      if (!Array.isArray(visual.pairing?.terms) || visual.pairing.terms.length !== 2
        || visual.pairing.terms.some((item) => typeof item !== "string" || !item.trim())
        || ["label", "inequality", "productVariable", "reduced"].some((field) => !visual.pairing?.[field])) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.pairing 必须完整展示对称项配对与积换元`);
      }
      if (["original", "lowerBound", "completion", "conclusion"].some((field) => !visual.reduction?.[field])) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.reduction 必须完整展示一元降维与配方`);
      }
      if (["pairingCondition", "completionCondition", "result", "verification"].some((field) => !visual.equality?.[field]) || !visual.conclusion) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.equality 必须联立配对与配方的取等条件`);
      }
    }
    if (step.visual?.kind === "fixed-product-construction-flow") {
      const visual = step.visual;
      const requiredObjects = ["goal", "initialCheck", "clue", "construction", "fixedPair", "application", "equality"];
      if (requiredObjects.some((field) => !visual[field] || typeof visual[field] !== "object" || Array.isArray(visual[field]))) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual 定积构造思维链缺少结构化阶段`);
      }
      if (!visual.title || !visual.strategy || !visual.goal.expression || !visual.initialCheck.product || !visual.clue.condition) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual 定积构造思维链缺少目标、策略或条件`);
      }
      const construction = visual.construction;
      if (typeof construction.expanded !== "string" || !construction.expanded.trim()) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.construction.expanded 必须展示完整展开式`);
      }
      if (construction.kind === "homogeneous") {
        if (visual.variant !== "homogeneous-reduction") {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual 齐次构造必须使用 homogeneous-reduction 变体`);
        }
        const degreeBalance = visual.degreeBalance;
        if (!degreeBalance || ["target", "condition", "result"].some((field) => {
          const item = degreeBalance[field];
          return !item || !item.label || !item.expression || !item.degree || !item.scale || !item.note;
        })) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.degreeBalance 必须完整描述目标、条件与零次结果`);
        }
        if (!construction.identity || !construction.identityNote || !construction.constant || !construction.ratio) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.construction 齐次构造缺少恒等式、数值说明、常数项或消元说明`);
        }
        if (!Array.isArray(construction.positiveTerms) || construction.positiveTerms.length !== 2 || construction.positiveTerms.some((item) => !item?.value || !item?.condition || !new Set(["square", "circle"]).has(item.shape))) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.construction.positiveTerms 必须提供方槽和圆槽两个正项表达式`);
        }
      } else if (construction.kind === "completion") {
        if (!construction.givenTerm || !construction.matchingTerm || !construction.identity || !construction.focus || !construction.constant || !construction.simplification) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.construction 补项构造缺少配对项、补项式、正项和、常数或换元简写`);
        }
      } else if (construction.kind === "grouping") {
        if (!construction.identity || !construction.focus || !construction.positive) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.construction 分组构造缺少通分式、重组结果或正项条件`);
        }
      } else if (construction.kind === "substitution") {
        if (!Array.isArray(construction.substitutions) || construction.substitutions.length !== 2 || construction.substitutions.some((item) => !item?.source || !item?.target || !item?.note)) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.construction.substitutions 必须提供两个完整换元映射`);
        }
        if (!construction.identity || !construction.focus || !construction.constant) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.construction 换元构造缺少换元式、正项和或保留常数`);
        }
      } else {
        if (!Array.isArray(construction.rows) || construction.rows.length !== 2 || !Array.isArray(construction.columns) || construction.columns.length !== 2) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.construction 必须提供 2×2 展开表的行列`);
        }
        if (!Array.isArray(construction.cells) || construction.cells.length !== 2 || construction.cells.some((row) => !Array.isArray(row) || row.length !== 2)) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.construction.cells 必须是 2×2 数组`);
        }
        construction.cells.flat().forEach((cell, index) => {
          if (!cell?.text || !new Set(["constant", "constructed"]).has(cell.role)) {
            throw new Error(`${meta.id} 的步骤 ${step.id}.visual.construction.cells[${index}] 缺少公式或角色`);
          }
        });
      }
      if (!Array.isArray(visual.fixedPair.terms) || visual.fixedPair.terms.length !== 2 || !visual.fixedPair.product || !visual.application.inequality || !visual.application.conclusion) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual 定积验证或基本不等式结论不完整`);
      }
      if (!visual.application.template || !Array.isArray(visual.application.mappings) || visual.application.mappings.length !== 2) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.application 必须提供基本不等式模板和两个槽位映射`);
      }
      visual.application.mappings.forEach((mapping, index) => {
        if (!mapping?.slot || !mapping?.value) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.application.mappings[${index}] 缺少槽位或构造项`);
        }
        if (visual.variant === "homogeneous-reduction" && (!mapping.condition || !new Set(["square", "circle"]).has(mapping.shape))) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.application.mappings[${index}] 必须提供彩色槽位形状和正数条件`);
        }
      });
    }
    if (step.visual?.kind === "implication-condition-pairs") {
      const cases = step.visual.cases;
      if (!Array.isArray(cases) || cases.length === 0) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.cases 必须是非空数组`);
      }
      for (const [index, item] of cases.entries()) {
        if (!item?.label || !item.pText || !item.qText || !item.result) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.cases[${index}] 缺少标签、p、q 或结论`);
        }
        if (typeof item.sufficient !== "boolean" || typeof item.necessary !== "boolean") {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.cases[${index}] 必须明确充分与必要是否成立`);
        }
        if (item.setEvidence) {
          const evidence = item.setEvidence;
          const requiredFields = evidence.kind === "nested-open-intervals"
            ? ["pSet", "qSet", "sharedLeft", "qRight", "pRight", "relation"]
            : evidence.kind === "complement-right-ray-parameter"
              ? ["pRowLabel", "qRowLabel", "resultRowLabel", "pSet", "qSet", "pLeftEndpoint", "pRightEndpoint", "qEndpoint", "resultEndpoint", "relation", "parameterSet"]
            : ["pSet", "qSet", "relation"];
          if (!["nested-open-intervals", "parameter-interval-containment", "complement-right-ray-parameter"].includes(evidence.kind) || requiredFields.some((field) => typeof evidence[field] !== "string" || !evidence[field].trim())) {
            throw new Error(`${meta.id} 的步骤 ${step.id}.visual.cases[${index}].setEvidence 无效`);
          }
          if (evidence.kind === "parameter-interval-containment") {
            const layoutFields = evidence.layout === "fixed-inside-right-ray"
              ? ["pLeft", "pRight", "qEndpoint"]
              : evidence.layout === "nested-left-rays"
                ? ["pEndpoint", "qEndpoint"]
                : null;
            if (!layoutFields || layoutFields.some((field) => typeof evidence[field] !== "string" || !evidence[field].trim())) {
              throw new Error(`${meta.id} 的步骤 ${step.id}.visual.cases[${index}].setEvidence 参数数轴字段无效`);
            }
          }
          const expectedExplanationCount = evidence.kind === "complement-right-ray-parameter" ? 3 : 2;
          if (evidence.explanations && (!Array.isArray(evidence.explanations) || evidence.explanations.length !== expectedExplanationCount || evidence.explanations.some((line) => typeof line !== "string" || !line.trim()))) {
            throw new Error(`${meta.id} 的步骤 ${step.id}.visual.cases[${index}].setEvidence.explanations 必须包含 ${expectedExplanationCount} 句说明`);
          }
        }
      }
    }
    if (step.visual?.kind === "inequality-sign-chart") {
      const { columns, rows, notes } = step.visual;
      if (!Array.isArray(columns) || columns.length < 2 || !Array.isArray(rows) || rows.length === 0) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual 符号表必须包含 columns 和 rows`);
      }
      for (const [index, row] of rows.entries()) {
        if (!row?.label || !Array.isArray(row.values) || row.values.length !== columns.length - 1) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.rows[${index}] 与符号表列数不一致`);
        }
        if (row.selectedIndices && (!Array.isArray(row.selectedIndices) || row.selectedIndices.some((value) => !Number.isInteger(value) || value < 0 || value >= row.values.length))) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.rows[${index}].selectedIndices 无效`);
        }
      }
      if (notes && (!Array.isArray(notes) || notes.some((note) => typeof note !== "string" || !note.trim()))) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.notes 必须是非空字符串数组`);
      }
    }
    if (step.visual?.kind === "option-counterexample-review") {
      const { rows } = step.visual;
      if (!Array.isArray(rows) || rows.length < 2 || rows.some((row) => (
        !row?.option || typeof row.correct !== "boolean" ||
        [row.judgment, row.example, row.calculation].some((value) => typeof value !== "string" || !value.trim())
      ))) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual 反例审查必须包含完整选项、判断、代入与计算`);
      }
    }
    if (step.visual?.kind === "number-line-reasoning") {
      const { rows, ticks } = step.visual;
      if (!Array.isArray(rows) || rows.length === 0 || !Array.isArray(ticks) || ticks.length === 0) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual 数轴图必须包含 rows 和 ticks`);
      }
      const endpointKinds = new Set(["open", "closed", "ray"]);
      rows.forEach((row, rowIndex) => {
        if (!row?.label || !row.condition || !Array.isArray(row.segments) || row.segments.length === 0) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.rows[${rowIndex}] 缺少条件或区间段`);
        }
        row.segments.forEach((segment) => {
          if (![segment.start, segment.end].every((value) => typeof value === "number" && value >= 0 && value <= 1) || segment.start > segment.end || !endpointKinds.has(segment.left) || !endpointKinds.has(segment.right)) {
            throw new Error(`${meta.id} 的步骤 ${step.id}.visual.rows[${rowIndex}] 区间段无效`);
          }
        });
      });
      if (ticks.some((tick) => typeof tick?.label !== "string" || typeof tick.position !== "number" || tick.position < 0 || tick.position > 1)) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.ticks 无效`);
      }
      const implicationCheck = step.visual.implicationCheck;
      if (implicationCheck != null) {
        const directions = implicationCheck.directions;
        if (
          typeof implicationCheck.title !== "string" || !implicationCheck.title.trim() ||
          typeof implicationCheck.conclusion !== "string" || !implicationCheck.conclusion.trim() ||
          !Array.isArray(directions) || directions.length !== 2 ||
          directions.some((direction) => (
            !direction?.from || !direction?.to || direction.from === direction.to ||
            typeof direction.holds !== "boolean" ||
            [direction.question, direction.setRelation, direction.reasoning].some((value) => typeof value !== "string" || !value.trim())
          )) ||
          directions[0].from !== directions[1].to ||
          directions[0].to !== directions[1].from
        ) {
          throw new Error(meta.id + " 的步骤 " + step.id + ".visual.implicationCheck 必须完整描述互为反向的两次条件检验");
        }
      }
    }
    if (step.visual?.kind === "absolute-direct-rule-map") {
      const { mode, original, rules, intersection } = step.visual;
      if (!["single", "intersection"].includes(mode) || typeof original !== "string" || !original.trim()) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual 直接法组件缺少有效 mode 或 original`);
      }
      const expectedRuleCount = mode === "intersection" ? 2 : 1;
      if (!Array.isArray(rules) || rules.length !== expectedRuleCount) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.rules 必须包含 ${expectedRuleCount} 条直接法规则`);
      }
      rules.forEach((rule, index) => {
        if (
          [rule?.index, rule?.name, rule?.template, rule?.substituted, rule?.solved, rule?.solution]
            .some((value) => typeof value !== "string" || !value.trim()) ||
          !Array.isArray(rule.mappings) || rule.mappings.length !== 2 ||
          rule.mappings.some((value) => typeof value !== "string" || !value.trim())
        ) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.rules[${index}] 缺少规则、槽位映射或求解结果`);
        }
      });
      if (mode === "intersection" && (
        !intersection || [intersection.label, intersection.expression, intersection.result]
          .some((value) => typeof value !== "string" || !value.trim())
      )) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.intersection 必须完整描述交集运算`);
      }
    }
    if (step.visual?.kind === "quadratic-integer-window") {
      const { original, completedSquare, integers, conclusion } = step.visual;
      if ([original, completedSquare, conclusion].some((value) => typeof value !== "string" || !value.trim()) || !Array.isArray(integers) || integers.length !== 3) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual 二次函数整数窗字段无效`);
      }
    }
    if (step.visual?.kind === "quadratic-symmetric-integer-window") {
      const { function: functionText, axis, movement, lockStatement, innerPairLabel, outerPairLabel, included, excluded, checks, range, integerValues, conclusion } = step.visual;
      if (
        [functionText, axis, movement, lockStatement, innerPairLabel, outerPairLabel, range, integerValues, conclusion].some((value) => typeof value !== "string" || !value.trim()) ||
        !Array.isArray(included) || included.length !== 3 || included.some((value) => typeof value !== "string" || !value.trim()) ||
        !Array.isArray(excluded) || excluded.length !== 2 || excluded.some((value) => typeof value !== "string" || !value.trim()) ||
        !Array.isArray(checks) || checks.length !== 2 || checks.some((check) => (
          [check?.role, check?.point, check?.symmetry, check?.condition, check?.calculation, check?.result].some((value) => typeof value !== "string" || !value.trim())
        ))
      ) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual 对称整数窗字段无效`);
      }
    }
    if (step.visual?.kind === "difference-factor-sign") {
      const { difference, factorization, factors, conclusion, equality } = step.visual;
      if ([difference, factorization, conclusion, equality].some((value) => typeof value !== "string" || !value.trim()) || !Array.isArray(factors) || factors.length < 2) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual 作差因式图字段无效`);
      }
    }
    if (step.visual?.kind === "product-range-plane") {
      const { intro, lower, upper } = step.visual;
      if ([intro, lower, upper].some((value) => typeof value !== "string" || !value.trim())) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual 二维乘积范围字段无效`);
      }
    }
    if (step.visual?.kind === "positive-interval-product-chain") {
      const { normalize, multiply, restore, conclusion, caption } = step.visual;
      const validTransform = (transform) => transform && [transform.source, transform.factor, transform.rule, transform.result].every((value) => typeof value === "string" && value.trim());
      if (
        !validTransform(normalize) || !validTransform(restore) ||
        !multiply || !Array.isArray(multiply.rows) || multiply.rows.length !== 2 || multiply.rows.some((value) => typeof value !== "string" || !value.trim()) ||
        [multiply.positivity, multiply.rule, multiply.expanded, multiply.result, conclusion, caption].some((value) => typeof value !== "string" || !value.trim())
      ) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual 正区间乘积链字段无效`);
      }
    }
    if (step.visual?.kind === "absolute-case-analysis") {
      const { original, breakpoints, cases, graph, merge } = step.visual;
      const nonEmpty = (value) => typeof value === "string" && value.trim();
      if (!nonEmpty(original) || !Array.isArray(breakpoints) || breakpoints.length < 1 || breakpoints.some((point) => (
        !nonEmpty(point?.equation) || !nonEmpty(point?.value) || !Number.isFinite(point?.numeric)
      ))) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual 分类讨论组件缺少题目或有效零点`);
      }
      if (!Array.isArray(cases) || cases.length !== breakpoints.length + 1 || cases.some((item) => (
        [item?.index, item?.interval, item?.signs, item?.rewrite, item?.inequality, item?.result].some((value) => !nonEmpty(value))
      ))) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.cases 必须完整覆盖零点划分出的所有区间`);
      }
      const rangeIsValid = (range) => Array.isArray(range) && range.length === 2 && range.every(Number.isFinite) && range[0] < range[1];
      const pieces = graph?.pieces;
      if (
        !graph || !rangeIsValid(graph.xRange) || !rangeIsValid(graph.yRange) ||
        !Array.isArray(pieces) || pieces.length !== cases.length || pieces.some((piece) => (
          ![piece?.from, piece?.to, piece?.slope, piece?.intercept].every(Number.isFinite) || piece.from >= piece.to
        )) ||
        !graph.threshold || !Number.isFinite(graph.threshold.value) || !nonEmpty(graph.threshold.label) || !["ge", "gt", "le", "lt"].includes(graph.threshold.relation) ||
        !Array.isArray(graph.ticks) || graph.ticks.some((tick) => !Number.isFinite(tick?.value) || !nonEmpty(tick?.label)) ||
        !Array.isArray(graph.solutionSegments) || graph.solutionSegments.length < 1 || graph.solutionSegments.some((segment) => (
          (segment.start !== null && !Number.isFinite(segment.start)) || (segment.end !== null && !Number.isFinite(segment.end)) ||
          !["open", "closed", "ray"].includes(segment.left) || !["open", "closed", "ray"].includes(segment.right)
        )) ||
        !merge || !nonEmpty(merge.label) || !nonEmpty(merge.result)
      ) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual 分类讨论图像或合并结果字段无效`);
      }
      const tolerance = 1e-9;
      for (let index = 0; index < pieces.length - 1; index += 1) {
        const left = pieces[index];
        const right = pieces[index + 1];
        const leftY = left.slope * left.to + left.intercept;
        const rightY = right.slope * right.from + right.intercept;
        if (Math.abs(left.to - right.from) > tolerance || Math.abs(leftY - rightY) > tolerance) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.graph.pieces 在第 ${index + 1} 个分界点没有连续衔接`);
        }
      }
    }
    if (step.visual?.kind === "piecewise-threshold-graph") {
      const { points, ticks, intersections, solutionSegments, solution, thresholdY } = step.visual;
      const validPoint = (point) => point && typeof point.x === "number" && typeof point.y === "number" && point.x >= 0 && point.x <= 1 && point.y >= 0 && point.y <= 1;
      if (!Array.isArray(points) || points.length < 2 || points.some((point) => !validPoint(point)) || !Array.isArray(ticks) || !Array.isArray(intersections) || intersections.some((point) => !validPoint(point)) || !Array.isArray(solutionSegments) || typeof thresholdY !== "number" || thresholdY < 0 || thresholdY > 1 || typeof solution !== "string" || !solution.trim()) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual 分段阈值图字段无效`);
      }
    }
    if (step.visual?.kind === "polynomial-threading-graph") {
      const { roots, signs, selectSign, inclusive, standardized, target, solution, facts } = step.visual;
      if (!Array.isArray(roots) || roots.length === 0 || roots.length > 5) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.roots 必须包含 1 至 5 个有序实根`);
      }
      for (const [index, root] of roots.entries()) {
        if (!root?.label || !Number.isInteger(root.multiplicity) || root.multiplicity < 1) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.roots[${index}] 必须包含根标签和正整数重数`);
        }
      }
      if (!Array.isArray(signs) || signs.length !== roots.length + 1 || signs.some((sign) => !["+", "-"].includes(sign))) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.signs 必须按区间给出 + 或 -`);
      }
      roots.forEach((root, index) => {
        const shouldChange = root.multiplicity % 2 === 1;
        if ((signs[index] !== signs[index + 1]) !== shouldChange) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual 在根 ${root.label} 处没有遵循奇穿偶不穿`);
        }
      });
      if (!["+", "-"].includes(selectSign) || typeof inclusive !== "boolean") {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.selectSign 或 inclusive 无效`);
      }
      if ([standardized, target, solution].some((value) => typeof value !== "string" || !value.trim())) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual 缺少标准式、目标符号或解集`);
      }
      if (facts && (!Array.isArray(facts) || facts.some((fact) => typeof fact !== "string" || !fact.trim()))) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.facts 必须是非空字符串数组`);
      }
    }
    if (step.visual?.kind === "rational-threading-graph") {
      const { roots, signs, selectSign, standardized, target, solution, facts, denominatorEvidence } = step.visual;
      if (!Array.isArray(roots) || roots.length < 2 || roots.length > 5) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.roots 必须包含 2 至 5 个有序分界点`);
      }
      for (const [index, root] of roots.entries()) {
        if (!root?.label || !["numerator", "denominator"].includes(root.kind) || typeof root.included !== "boolean") {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.roots[${index}] 必须包含标签、分子/分母类型和端点取舍`);
        }
        if (root.kind === "denominator" && root.included) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual 分母禁值点 ${root.label} 不能并入解集`);
        }
      }
      if (!Array.isArray(signs) || signs.length !== roots.length + 1 || signs.some((sign) => !["+", "-"].includes(sign)) || signs.some((sign, index) => index > 0 && sign === signs[index - 1])) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.signs 必须按一次分界点给出交替符号`);
      }
      if (!["+", "-"].includes(selectSign) || [standardized, target, solution].some((value) => typeof value !== "string" || !value.trim())) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual 缺少目标符号、标准式或解集`);
      }
      if (facts && (!Array.isArray(facts) || facts.some((fact) => typeof fact !== "string" || !fact.trim()))) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.facts 必须是非空字符串数组`);
      }
      if (denominatorEvidence && [denominatorEvidence.expression, denominatorEvidence.conclusion].some((value) => typeof value !== "string" || !value.trim())) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.denominatorEvidence 缺少函数式或恒正结论`);
      }
    }
    if (step.visual?.kind === "absolute-inequality-visual") {
      const allowedModes = new Set(["direct-inclusion", "rhs-sign-classification", "piecewise-sum"]);
      const { mode, method, title, solution, transformations, facts } = step.visual;
      if (!allowedModes.has(mode) || [method, title, solution].some((value) => typeof value !== "string" || !value.trim())) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual 缺少有效的绝对值方法、标题或结论`);
      }
      if (!Array.isArray(transformations) || transformations.length === 0 || transformations.some((line) => typeof line !== "string" || !line.trim())) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.transformations 必须包含转化过程`);
      }
      if (facts && (!Array.isArray(facts) || facts.some((fact) => typeof fact !== "string" || !fact.trim()))) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.facts 必须是非空字符串数组`);
      }
      if (mode === "direct-inclusion") {
        if (!Array.isArray(step.visual.tickLabels) || step.visual.tickLabels.length !== 3 || [step.visual.outerCondition, step.visual.innerCondition].some((value) => typeof value !== "string" || !value.trim())) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual 直接法包含图缺少三个端点或两个条件`);
        }
      }
      if (mode === "rhs-sign-classification") {
        if (!Array.isArray(step.visual.tickLabels) || step.visual.tickLabels.length !== 3 || !Array.isArray(step.visual.branches) || step.visual.branches.length !== 2) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual 分类图必须包含三个数轴标记和两个分支`);
        }
        step.visual.branches.forEach((branch, index) => {
          if ([branch.condition, branch.result, branch.explanation].some((value) => typeof value !== "string" || !value.trim())) {
            throw new Error(`${meta.id} 的步骤 ${step.id}.visual.branches[${index}] 缺少条件、结果或说明`);
          }
        });
      }
      if (mode === "piecewise-sum") {
        if (!Array.isArray(step.visual.breakpoints) || step.visual.breakpoints.length !== 2 || !Array.isArray(step.visual.intersections) || step.visual.intersections.length !== 2 || typeof step.visual.threshold !== "string" || !step.visual.threshold.trim()) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual 分段折线图缺少分界点、交点或阈值`);
        }
      }
    }
    if (step.visual?.kind === "quadratic-function-sign-graphs") {
      const graphs = step.visual.graphs;
      const allowedOpenings = new Set(["up", "down"]);
      const allowedDiscriminants = new Set(["positive", "zero", "negative"]);
      const allowedSolutionModes = new Set([
        "middle-open",
        "middle-closed",
        "outside-open",
        "outside-closed",
        "except-root",
        "all",
        "none",
      ]);
      if (!Array.isArray(graphs) || graphs.length === 0 || graphs.length > 4) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.graphs 必须包含 1 至 4 幅二次函数图像`);
      }
      for (const [index, graph] of graphs.entries()) {
        if (!graph?.label || !graph.expression || !graph.target || !graph.solution) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.graphs[${index}] 缺少题号、函数式、目标不等式或解集`);
        }
        if (!allowedOpenings.has(graph.opening) || !allowedDiscriminants.has(graph.discriminant) || !allowedSolutionModes.has(graph.solutionMode)) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.graphs[${index}] 的开口、判别式或解集模式无效`);
        }
        const expectedRootCount = graph.discriminant === "positive" ? 2 : graph.discriminant === "zero" ? 1 : 0;
        if (!Array.isArray(graph.roots) || graph.roots.length !== expectedRootCount) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.graphs[${index}].roots 与判别式状态不一致`);
        }
        if (graph.facts && (!Array.isArray(graph.facts) || graph.facts.some((fact) => typeof fact !== "string" || !fact.trim()))) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.graphs[${index}].facts 必须是非空字符串数组`);
        }
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
