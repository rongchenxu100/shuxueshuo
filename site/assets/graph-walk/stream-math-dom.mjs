/** Safe mathematical card DOM shared by completed/read steps and debug views.
 * This module never controls progress, transport, or interaction availability.
 */
import {matchedOriginalChoice} from './original-choice.mjs?v=20261028-domain-overlap';
import {createIntervalOverlapExplorer} from './interval-overlap-visual.mjs?v=20261028-domain-overlap';

const expressionText = value => typeof value === 'string' ? value : value?.latex || '';
const text = (document, tag, value, className) => {
  const node = document.createElement(tag);
  node.textContent = value;
  if (className) node.className = className;
  return node;
};

function derivationCell(document, item, role) {
  const cell = document.createElement('div');
  cell.className = 'gw-derivation-cell';
  cell.dataset.role = role;
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
  return cell;
}

function pairingTerm(document, value, id) {
  const term = text(document, 'div', `\\displaystyle ${value}`, 'gw-pairing-term');
  term.dataset.mathFormula = 'true';
  term.dataset.occurrenceId = id;
  return term;
}

/** Keep the same occurrence layout as attention moves from pairs to leftovers. */
function pairingDiagram(document, diagram) {
  const figure = document.createElement('figure');
  figure.className = 'gw-pairing-diagram';
  figure.dataset.focus = diagram.focus;
  figure.append(text(document, 'figcaption', '按互为倒数的输入对齐', 'gw-pairing-caption'));
  const viewport = document.createElement('div');
  viewport.className = 'gw-pairing-scroll';
  viewport.setAttribute('tabindex', '0');
  viewport.setAttribute('role', 'group');
  viewport.setAttribute('aria-label', '上下两项配成一对，未配对项列在左侧');
  const sequence = document.createElement('div');
  sequence.className = 'gw-pairing-sequence';
  const columns = [];
  const blank = () => text(document, 'span', '', 'gw-pairing-blank');
  const appendColumn = (column, paired) => {
    if (columns.length) {
      const plus = document.createElement('div');
      plus.className = 'gw-pairing-separator';
      plus.setAttribute('aria-hidden', 'true');
      plus.append(text(document, 'span', '+'), blank(),
        text(document, 'span', paired && columns.at(-1).paired ? '+' : ''));
      sequence.append(plus);
    }
    columns.push({paired});
    sequence.append(column);
  };
  const ellipsis = paired => {
    const column = document.createElement('div');
    column.className = 'gw-pairing-ellipsis';
    column.dataset.kind = paired ? 'pair' : 'leftover';
    column.setAttribute('aria-label', paired ? '省略中间的配对项' : '省略中间的未配对项');
    column.append(text(document, 'span', '⋯'), blank(), text(document, 'span', paired ? '⋯' : ''));
    appendColumn(column, paired);
  };
  diagram.leftovers.forEach((item, index) => {
    if (diagram.omitted_leftovers > 0 && index === diagram.leftovers.length - 1) ellipsis(false);
    const column = document.createElement('div');
    column.className = 'gw-pairing-leftover';
    column.append(pairingTerm(document, item.math, item.id), blank(), blank());
    appendColumn(column, false);
  });
  diagram.pairs.forEach((pair, index) => {
    if (diagram.omitted_pairs > 0 && index === diagram.pairs.length - 1) ellipsis(true);
    const column = document.createElement('div');
    column.className = 'gw-pairing-pair';
    const link = document.createElement('div');
    link.className = 'gw-pairing-link';
    const arrow = text(document, 'span', '↕', 'gw-pairing-link-arrow');
    arrow.setAttribute('aria-hidden', 'true');
    const sum = text(document, 'span', `\\text{和}=${diagram.pair_value}`, 'gw-pairing-value');
    sum.dataset.mathFormula = 'true';
    link.append(arrow, sum);
    column.append(pairingTerm(document, pair.left_math, pair.left_id), link,
      pairingTerm(document, pair.right_math, pair.right_id));
    appendColumn(column, true);
  });
  viewport.append(sequence);
  figure.append(viewport);
  return figure;
}

/** One local deduction, shared by its unanswered and verified states.
 * Labels and formulas always enter as text; null alone marks an unknown.
 */
export function createDerivationBoard(document, board) {
  const node = document.createElement('section');
  node.className = 'gw-derivation-board';
  node.dataset.state = board.items[1].math === null ? 'pending' : 'complete';
  node.setAttribute('aria-label', board.caption);
  node.append(text(document, 'div', board.caption, 'gw-derivation-caption'));
  if (board.pairing_diagram) {
    node.dataset.layout = 'pairing';
    const arrow = text(document, 'div', '↓', 'gw-pairing-result-arrow');
    arrow.setAttribute('aria-hidden', 'true');
    node.append(pairingDiagram(document, board.pairing_diagram), arrow,
      derivationCell(document, board.items[1], 'result'));
    return node;
  }
  if (board.condition_groups) {
    node.dataset.layout = 'parallel-conditions';
    node.append(derivationCell(document, board.items[0], 'target'));
    const groups = document.createElement('div');
    groups.className = 'gw-domain-conditions';
    groups.setAttribute('role', 'group');
    groups.setAttribute('aria-label', '需要同时满足的两个条件');
    board.condition_groups.forEach((item, index) => {
      const condition = derivationCell(document, item, 'condition');
      const number = text(document, 'span', String(index + 1), 'gw-domain-condition-number');
      number.setAttribute('aria-hidden', 'true');
      condition.append(number);
      groups.append(condition);
    });
    const join = document.createElement('div');
    join.className = 'gw-domain-condition-join';
    join.append(text(document, 'span', '同时满足', 'gw-domain-condition-join-label'));
    node.append(groups, join, derivationCell(document, board.items[1], 'result'));
    return node;
  }
  const row = document.createElement('div');
  row.className = 'gw-derivation-row';
  board.items.forEach((item, index) => {
    if (index) {
      const arrow = text(document, 'span', board.connector, 'gw-derivation-arrow');
      arrow.setAttribute('aria-hidden', 'true');
      row.append(arrow);
    }
    row.append(derivationCell(document, item, index ? 'result' : 'given'));
  });
  if (board.interval_explorer) node.append(createIntervalOverlapExplorer(document, board.interval_explorer));
  node.append(row);
  return node;
}

export function routeAnswerSummary(answer = {}) {
  if (answer.kind === 'goal_group' && answer.status === 'complete') {
    const rows = answer.answers;
    if (!Array.isArray(rows) || !rows.length || new Set(rows.map(row => row.target_ref)).size !== rows.length) return null;
    const items = rows.map(row => ({title: row.title || '', summary: routeAnswerSummary(row.answer)}));
    return items.every(item => item.summary) ? {label: '本题全部目标已完成', formula: '', items} : null;
  }
  if (['find_value', 'check_constant', 'finite_sum'].includes(answer.kind) && answer.status === 'complete') {
    if (answer.defined === false) return {label: answer.result_type === 'constant_check'
      ? '没有合法输入，不能确定唯一的定值。' : '原目标无定义。', formula: ''};
    if (answer.defined !== true) return null;
    if (answer.result_type === 'constant_check') {
      if (answer.is_constant === false) return {label: '不是定值。', formula: '', domain: expressionText(answer.domain)};
      if (answer.is_constant !== true || !expressionText(answer.value)) return null;
      return {label: '定值：', formula: expressionText(answer.value), domain: expressionText(answer.domain)};
    }
    if (answer.result_type === 'expression_with_domain') {
      const formula = expressionText(answer.expression), domain = expressionText(answer.domain);
      return formula && domain ? {label: '函数值表达式：', formula, domain} : null;
    }
    if (['scalar_value', 'finite_sum'].includes(answer.result_type)) {
      const formula = expressionText(answer.value);
      return formula ? {label: answer.result_type === 'finite_sum' ? '总和：' : '函数值：', formula} : null;
    }
    return null;
  }
  if (answer.kind === 'compare_functions' && answer.status === 'complete' &&
      Array.isArray(answer.option_verdicts) && answer.option_verdicts.length &&
      answer.option_verdicts.every(row => ['equal', 'different'].includes(row.verdict))) {
    return {label: '各项比较已完成', formula: ''};
  }
  if (['find_range', 'find_domain', 'find_abstract_domain', 'find_abstract_domain_parameter'].includes(answer.kind) && answer.status === 'set') {
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
  if (choice?.kind === 'multiple_choice' && Array.isArray(choice.option_verdicts)) {
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
  if (summary?.domain) {
    const domain = text(document, 'span', `　合法输入范围：$${summary.domain}$`, 'stage-three-answer-domain');
    domain.dataset.mathText = 'true'; node.append(domain);
  }
  if (summary?.items) {
    const list = document.createElement('ul');
    list.className = 'stage-three-goal-answers';
    for (const item of summary.items) {
      const row = text(document, 'li', `${item.title}　${item.summary.label}${item.summary.formula ? `$${item.summary.formula}$` : ''}`
        + (item.summary.domain ? `，合法输入范围：$${item.summary.domain}$` : ''));
      row.dataset.mathText = 'true'; list.append(row);
    }
    node.append(list);
  }
  options.renderMath?.(node);
  return {node, complete, answerStatus, statusText: complete ? '本路线已完成数学验证。'
    : '目标答案尚未确定，暂不发布完成结论。'};
}
