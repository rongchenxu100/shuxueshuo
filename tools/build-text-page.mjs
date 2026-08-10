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
    if (step.visual?.kind === "basic-inequality-mapping") {
      const visual = step.visual;
      const requiredFields = [
        "title",
        "template",
        "mapped",
        "fixedCondition",
        "replaced",
        "substituted",
        "conclusion",
        "equalityTemplate",
        "equalityMapped",
        "equalityResult",
      ];
      if (requiredFields.some((field) => typeof visual[field] !== "string" || !visual[field].trim())) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual 基本不等式映射缺少公式或结论`);
      }
      if (!Array.isArray(visual.mappings) || visual.mappings.length !== 2) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.mappings 必须包含两个公式槽位`);
      }
      visual.mappings.forEach((mapping, index) => {
        if ([mapping?.slot, mapping?.value, mapping?.condition].some((value) => typeof value !== "string" || !value.trim())) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.mappings[${index}] 缺少槽位、题目变量或正数条件`);
        }
      });
      if (visual.conditionFlow && (!Array.isArray(visual.conditionFlow) || visual.conditionFlow.length < 2 || visual.conditionFlow.some((item) => typeof item !== "string" || !item.trim()))) {
        throw new Error(`${meta.id} 的步骤 ${step.id}.visual.conditionFlow 必须包含至少两个有效公式`);
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
      if (construction.kind === "completion") {
        if (!construction.givenTerm || !construction.matchingTerm || !construction.identity || !construction.focus || !construction.constant || !construction.simplification) {
          throw new Error(`${meta.id} 的步骤 ${step.id}.visual.construction 补项构造缺少配对项、补项式、正项和、常数或换元简写`);
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
