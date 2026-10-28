/** Safe mathematical card DOM shared by completed/read steps and debug views.
 * This module never controls progress, transport, or interaction availability.
 */
import {matchedOriginalChoice} from './original-choice.mjs?v=20261027-function-equality';

const expressionText = value => typeof value === 'string' ? value : value?.latex || '';
const text = (document, tag, value, className) => {
  const node = document.createElement(tag);
  node.textContent = value;
  if (className) node.className = className;
  return node;
};

/** One local deduction, shared by its unanswered and verified states.
 * Labels and formulas always enter as text; null alone marks an unknown.
 */
export function createDerivationBoard(document, board) {
  const node = document.createElement('section');
  node.className = 'gw-derivation-board';
  node.dataset.state = board.items[1].math === null ? 'pending' : 'complete';
  node.setAttribute('aria-label', board.caption);
  node.append(text(document, 'div', board.caption, 'gw-derivation-caption'));
  const row = document.createElement('div');
  row.className = 'gw-derivation-row';
  board.items.forEach((item, index) => {
    if (index) {
      const arrow = text(document, 'span', board.connector, 'gw-derivation-arrow');
      arrow.setAttribute('aria-hidden', 'true');
      row.append(arrow);
    }
    const cell = document.createElement('div');
    cell.className = 'gw-derivation-cell';
    cell.dataset.role = index ? 'result' : 'given';
    const label = text(document, 'div', item.label, 'gw-derivation-label');
    label.dataset.mathText = 'true';
    cell.append(label);
    if (item.math === null) {
      const unknown = text(document, 'div', '?', 'gw-derivation-unknown');
      unknown.setAttribute('role', 'img');
      unknown.setAttribute('aria-label', '待求');
      cell.append(unknown);
    } else {
      const formula = text(document, 'div', `\\displaystyle ${item.math}`, 'gw-derivation-formula');
      formula.dataset.mathFormula = 'true';
      cell.append(formula);
    }
    if (item.note) {
      const note = text(document, 'div', item.note, 'gw-derivation-note');
      note.dataset.mathText = 'true';
      cell.append(note);
    }
    row.append(cell);
  });
  node.append(row);
  return node;
}

export function routeAnswerSummary(answer = {}) {
  if (answer.kind === 'compare_functions' && answer.status === 'complete' &&
      Array.isArray(answer.option_verdicts) && answer.option_verdicts.length &&
      answer.option_verdicts.every(row => ['equal', 'different'].includes(row.verdict))) {
    return {label: '各项比较已完成', formula: ''};
  }
  if (['find_range', 'find_domain', 'find_abstract_domain'].includes(answer.kind) && answer.status === 'set') {
    const formula = expressionText(answer.set);
    return formula ? {label: ['find_domain', 'find_abstract_domain'].includes(answer.kind) ? '定义域：' : '参数范围：', formula} : null;
  }
  if (!['find_minimum', 'find_maximum'].includes(answer.kind)) return null;
  const minimum = answer.kind === 'find_minimum', name = minimum ? '最小值' : '最大值';
  if (answer.status === 'attained' || answer.status === 'not_attained') {
    const value = answer.status === 'attained' ? answer.value : answer.bound;
    const formula = expressionText(value);
    if (!formula || ['Infinity', 'NegativeInfinity'].includes(value?.exact?.$math)) return null;
    return {label: answer.status === 'attained' ? `${name}：`
      : `${name}不存在，只能趋近：`, formula};
  }
  if (answer.status === (minimum ? 'unbounded_below' : 'unbounded_above')) {
    return {label: `${name}不存在：可行集没有${minimum ? '下' : '上'}界。`, formula: ''};
  }
  if (answer.status === 'empty_feasible_set') return {label: `没有满足题设的参数，${name}不存在。`, formula: ''};
  return null;
}

/* The conclusion first: a caption over labelled formulas joined by arrows, as in the authored lessons. */
function highlightBoard(document, highlight, parallel = false) {
  if (highlight.layout === 'derivation') return createDerivationBoard(document, highlight);
  if (highlight.layout === 'merge') return mergeBoard(document, highlight);
  const board = document.createElement('div');
  board.className = 'visual-board completed-visual stage-three-highlight';
  board.append(text(document, 'div', highlight.caption, 'board-caption'));
  const row = document.createElement('div');
  row.className = parallel ? 'gw-domain-parallel' : 'function-conversion';
  highlight.items.forEach((item, index) => {
    if (index && !parallel) {
      const arrow = text(document, 'span', highlight.connector === undefined ? '→' : highlight.connector, 'conversion-arrow');
      arrow.setAttribute('aria-hidden', 'true'); row.append(arrow);
    }
    const cell = document.createElement('div');
    const label = text(document, 'span', item.label, 'conversion-label');
    const formula = text(document, 'div', `\\displaystyle ${item.math}`, 'math');
    label.dataset.mathText = 'true'; formula.dataset.mathFormula = 'true';
    cell.append(label, formula);
    if (item.note) {
      const note = text(document, 'span', item.note, 'conversion-label');
      note.dataset.mathText = 'true'; cell.append(note);
    }
    row.append(cell);
  });
  board.append(row);
  if (highlight.show_result === true && typeof highlight.result === 'string' && highlight.result.trim()) {
    const result = text(document, 'p', highlight.result, 'gw-result');
    result.dataset.mathText = 'true';
    board.append(result);
  }
  return board;
}

/* Each case's result in its own cell, then the union of all cells on one line. */
function mergeBoard(document, highlight) {
  const board = document.createElement('div'), group = document.createElement('div');
  board.className = 'case-merge stage-three-highlight';
  group.className = 'case-merge-group';
  for (const item of highlight.items) {
    const cell = document.createElement('span');
    cell.className = 'case-merge-cell';
    const label = text(document, 'span', item.label, 'case-merge-name');
    const value = text(document, 'span', `$${item.math}$`, 'case-merge-value');
    label.dataset.mathText = 'true'; value.dataset.mathText = 'true';
    cell.append(label, value);
    group.append(cell);
  }
  const total = text(document, 'span', `${highlight.caption}：${highlight.result}`, 'case-merge-total');
  total.dataset.mathText = 'true';
  group.append(total);
  board.append(group);
  return board;
}

function formulaLines(document, values, field) {
  return values.map(value => {
    const formula = text(document, 'p', expressionText(value), `stage-three-${field}`);
    formula.dataset.mathFormula = 'true';
    return formula;
  });
}

/* Keep mathematical blocks intact while splitting prose into sentences/lines.
 * A standalone derivation has no sentence-ending full stop; prose still does.
 */
function derivationLines(explanation) {
  const parts = explanation.split(/(\$\$[\s\S]+?\$\$|\$(?:\\[\s\S]|[^\\$])+\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\))/g);
  const lines = [];
  let line = '', prose = '', hasMath = false;
  const finish = () => {
    if (line.trim()) {
      lines.push(hasMath && /^[\s，,]*。\s*$/.test(prose) ? line.replace(/。\s*$/, '') : line);
    }
    line = ''; prose = ''; hasMath = false;
  };
  parts.forEach((part, index) => {
    if (index % 2) { line += part; hasMath = true; return; }
    for (const text of part.split(/(。|\n)/)) {
      if (text === '\n') { finish(); continue; }
      line += text; prose += text;
      if (text === '。') finish();
    }
  });
  finish();
  return lines;
}

/* The full derivation follows, one prose sentence or mathematical derivation per line. */
function derivationDetails(document, explanation, before = [], open = true) {
  const details = document.createElement('details');
  details.className = 'details stage-three-derivation'; details.open = open;
  details.append(text(document, 'summary', '完整推导'));
  details.append(...formulaLines(document, before, 'before'));
  for (const sentence of derivationLines(explanation)) {
    const line = text(document, 'p', sentence, 'stage-three-explanation');
    line.dataset.mathText = 'true'; details.append(line);
  }
  return details;
}

/** Return a detached card; renderer failure cannot publish a partially built card. */
export function createMathCard(document, step, options = {}) {
  const node = document.createElement('article');
  node.className = 'stage-three-math-step';
  Object.assign(node.dataset, {stepId: step.step_id, mathStepSha256: step.math_step_sha256,
    targetRef: step.target_ref, routeId: step.route_id, ordinal: String(step.ordinal)});
  const heading = text(document, 'h3', step.title);
  node.append(heading);
  let conclusion = null, caption = null;
  if (step.highlight) {
    conclusion = highlightBoard(document, step.highlight, ['domain_locations', 'domain_conditions', 'domain_solutions'].includes(step.display_unit));
    if (step.highlight.layout !== 'merge') caption = conclusion.children[0];
    node.append(conclusion);
    if (!step.highlight.conclusion_only) node.append(derivationDetails(document, step.explanation || '', [], step.highlight.layout !== 'derivation'));
  } else if (step.derivation) {
    // Conclusion is the step's pictures or another board; this card is only the prose.
    node.append(derivationDetails(document, step.explanation || ''));
  } else {
    const after = step.after || [];
    if (after.length) {
      conclusion = document.createElement('div');
      conclusion.className = 'visual-board completed-visual stage-three-conclusion';
      caption = text(document, 'div', '结论', 'board-caption');
      conclusion.append(caption, ...formulaLines(document, after, 'after'));
      node.append(conclusion);
    }
    const conclusions = new Set(after.map(value => expressionText(value).trim()));
    const before = (step.before || []).filter(value => !conclusions.has(expressionText(value).trim()));
    node.append(derivationDetails(document, step.explanation || '', before));
  }
  const qa = document.createElement('aside');
  qa.className = 'stage-three-qa'; qa.hidden = true; node.append(qa);
  options.renderMath?.(node);
  const card = {node, qa, heading, conclusion, caption, step: structuredClone(step)};
  setMathCardLayout(card, options);
  if (options.qa) attachMathQA(card, options.qa, options);
  return card;
}

/** A cached mathematical card can move between a named lesson step and a standalone view. */
export function setMathCardLayout(card, {embedded = false, parentTitle = '', externalConclusion = false} = {}) {
  card.node.className = `stage-three-math-step${embedded ? ' is-embedded' : ''}`;
  card.heading.hidden = embedded && (card.step.title === parentTitle || card.step.highlight?.layout === 'derivation');
  if (card.caption) card.caption.hidden = card.caption.textContent === card.step.title ||
    embedded && card.caption.textContent === parentTitle;
  if (card.conclusion) card.conclusion.hidden = Boolean(card.step.highlight?.replace_with_graph && externalConclusion);
}

/** Only replace the QA region. The caller decides whether the card is completed. */
export function attachMathQA(card, chunk, options = {}) {
  if (['run_id', 'lesson_version', 'target_ref', 'route_id', 'step_id', 'math_step_sha256']
    .some(key => chunk[key] !== card.step[key])) throw new Error('stream.qa_hash_mismatch');
  const document = card.node.ownerDocument, staging = document.createElement('aside');
  const labels = {questions: '想一想', possible_questions: '你可能会问', hints: '提示', common_errors: '常见错误', feedback: '反馈'};
  for (const [key, value] of Object.entries(chunk.qa || {})) {
    const values = Array.isArray(value) ? value : [value];
    const lines = values.map(item => typeof item === 'string' ? item : item?.text || item?.question || item?.message || '').filter(Boolean);
    if (!lines.length) continue;
    staging.append(text(document, 'strong', labels[key] || '补充说明'));
    for (const line of lines) {
      const node = text(document, 'p', line);
      node.dataset.mathText = 'true'; staging.append(node);
    }
  }
  options.renderMath?.(staging);
  card.qa.replaceChildren(...staging.childNodes);
  card.qa.hidden = false;
}

/** Detached route answer; unknown/unavailable answers never claim completion. */
export function createRouteCompletion(document, payload, options = {}) {
  const answer = payload.answer || {}, summary = routeAnswerSummary(answer);
  const complete = Boolean(summary) && payload.available !== false;
  const node = text(document, 'p', '', 'stage-three-completion');
  node.hidden = !complete;
  const answerStatus = summary ? answer.status : 'unknown';
  node.dataset.answerStatus = answerStatus;
  const choice = complete && matchedOriginalChoice(payload);
  if (choice) node.append(text(document, 'strong', `答案：${choice.correct_labels.join('、') || '无符合项'}　`, 'stage-three-choice-answer'));
  if (choice?.kind === 'multiple_choice') {
    const board = document.createElement('ul');
    board.className = 'gw-option-verdict-board';
    const reasons = {domains_differ: '定义域不同', outputs_differ: '存在同一个输入，两式的函数值不同',
      same_domain_and_correspondence: '定义域相同，且每个输入对应的函数值都相同'};
    for (const row of choice.option_verdicts) {
      const item = text(document, 'li', `${row.label}　${row.verdict === 'equal' ? '相同' : '不同'}：${reasons[row.reason] || row.reason}`);
      item.dataset.mathText = 'true'; board.append(item);
    }
    node.append(board);
  }
  node.append(text(document, 'span', summary?.label || '目标答案尚未确定。'));
  if (summary?.formula) {
    const formula = text(document, 'span', summary.formula, 'stage-three-answer');
    formula.dataset.mathFormula = 'true'; node.append(formula);
  }
  options.renderMath?.(node);
  return {node, complete, answerStatus, statusText: complete ? '本路线已完成数学验证。'
    : '目标答案尚未确定，暂不发布完成结论。'};
}
