import {emptyMethodAnswer, projectMethodAnswer, methodCardsHTML, checkMethodAnswers, selectedMethod} from './method-cards.mjs?v=20261106-method-pairs';
import {mountMethodConnections, connectedMethodAnswer} from './method-connections.mjs?v=20261106-method-pairs';
import {formulaAnswerHTML} from './formula-answer.mjs?v=20261101-fraction';
import {createFormulaFitter, renderFittedFormula} from './formula-fit.mjs?v=20261103';
import {createState, currentDecision, submitAnswer, undo, switchRoute, graphState, replayState, extendStreamBundle, streamGraphState, migrateStageTwoState, refreshStreamState, setStreamDraft, streamDraft, teachingContext, CALL_LANE} from './walk-state.mjs?v=20261101-coefficients';
import {createWalkGraph, nodeHref} from './walk-graph.mjs?v=20261015-view-tabs';
import {createMathCard, createDerivationBoard, setMathCardLayout, attachMathQA, createRouteCompletion} from './stream-math-dom.mjs?v=20261104-composition-operation';
import {expressionRegionsHTML} from './expression-regions.mjs?v=20261104-domain-display';
import {domainNumberLineGraph, endpointChecksHTML} from './domain-visuals.mjs?v=20261026-domain-powers';
import {buildStreamReplay} from './walk-replay.mjs?v=20261101-coefficients';
import {optionProgress, hasOptionWorkspaces} from './option-workspace.mjs?v=20261027-function-equality';
import {mountQuestionFigures} from '../practice/question-figures.mjs?v=20261102-g4-source';
import {mountFigureChoices} from '../practice/figure-choices.mjs?v=20261102-g4-source';

const BUNDLE_URL = '/data/graph-walk/quadratic-always-q01.json';
const REPLAY_INDEX_URL = '/data/graph-walk/replays/index.json';
const PRACTICE_PAGE = '/2/q01/';
const GRAPH_MODE_KEY = 'gw-graph-mode';
const $ = selector => document.querySelector(selector);
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, character => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[character]));
const reduced = matchMedia('(prefers-reduced-motion: reduce)');
const narrow = matchMedia('(max-width: 959px)');
const copyAnswer = answer => answer == null ? answer : structuredClone(answer);
let bundle, state, studentState, graph, graphView;
let draft = null, draftKey = '', selectedSlot = null, submitted = null, busy = false;
let reviewOption = null;
// The student's unsubmitted answer when this bundle was parked; picked up once its step renders again.
let keptDraft = null;
let disposeMethodConnections = () => {};
let disposeProblemFigures = () => {};
let formulaFitter = null;
const choicePictureMounts = new Map(), choicePicturesReady = new Set();
let actor = 'student', replay = null, replayPosition = 0, replayTimer = null, replayPlaying = false, replayTicket = 0, loadTicket = 0;
let replayEntries = [], replayIndexLoaded = false, replayNotice = null, focusBeforeGraph = null, commitTimer = null;
let graphMode = readGraphMode(), webglFailed = false, graphTicket = 0;
let preview = null, previewTimer = null, previewTicket = 0, story = null, replayStatuses = {replay: null, values: []};
/* The Demo page loads its own snapshot. Another page sets <body data-walk="mount"> and calls mountWalk
   with a bundle and replay in hand; progress is kept per bundle so switching back resumes it. */
let options = {bundleUrl: BUNDLE_URL, practicePage: PRACTICE_PAGE, bundle: null, replay: null, actor: null, revealGraph: false};
let bound = false, disposed = false;
let bundleScope = null;
const saved = new Map();
let streamView = null, publicGraph = null, streamUpdateTicket = 0;
let streamUpdateQueue = Promise.resolve(), mountTicket = 0, streamParked = false;
const streamQA = new Map(), streamCards = new Map();
let visibleStreamCards = new Set(), replayRoutes = {}, replayRoute = null;

function readGraphMode() {
  // Phones always open in 3D: its camera follows the current step, which a small screen needs.
  if (narrow.matches) return '3d';
  try { return localStorage.getItem(GRAPH_MODE_KEY) === '2d' ? '2d' : '3d'; } catch { return '3d'; }
}

async function createGraph(current = () => true) {
  const host = $('#gw-graph'), view = graphView;
  const onSwitch = () => { if (current()) void switchGraphMode(); };
  const onSelect = (...args) => { if (current()) selectNode(...args); };
  if (graphMode === '3d' && !webglFailed) {
    try {
      const {createWalkGraph3D} = await import('./walk-graph-3d.mjs?v=20261015-view-tabs');
      if (!current()) return null;
      return await createWalkGraph3D(host, view, {onSelect, onSwitch, current});
    } catch (error) {
      if (!current()) return null;
      webglFailed = true;
      console.warn('三维图谱不可用，已改用平面图。', error);
    }
  }
  if (!current()) return null;
  return createWalkGraph(host, view, {onSelect, onSwitch: webglFailed ? null : onSwitch, usedOnlyLane: CALL_LANE});
}

async function installGraph(current = () => true) {
  const ticket = ++graphTicket;
  const active = () => ticket === graphTicket && current();
  graph?.destroy(); graph = null;
  const created = await createGraph(active);
  if (!active()) { created?.destroy(); return false; }
  graph = created;
  return Boolean(created);
}

async function switchGraphMode() {
  if (streamParked || !bundle) return;
  graphMode = graphMode === '3d' ? '2d' : '3d';
  try { localStorage.setItem(GRAPH_MODE_KEY, graphMode); } catch { /* private mode keeps the choice for this page only */ }
  if (!await installGraph()) return;
  mountCaption(); renderGraph();
  $('#gw-graph [data-graph-action="switch"]')?.focus();
}

function renderMath(root) {
  for (const label of root.querySelectorAll('[data-math-text]:not([data-math-rendered])')) {
    PracticeMath.render(label, label.textContent);
    label.dataset.mathRendered = 'true';
  }
}

function choiceStemParts(text) {
  const lines = String(text || '').split(/\r?\n/).map(line => line.trim()).filter(Boolean);
  const options = [], prompt = [];
  for (const line of lines) {
    if (/^[A-D][.、．]/.test(line)) options.push(line);
    else if (options.length) options[options.length - 1] += ` ${line}`;
    else prompt.push(line);
  }
  return options.length >= 2 ? {prompt: prompt.join(' '), options} : null;
}

function renderProblemText(element, statement) {
  const choice = choiceStemParts(statement);
  if (!choice) {
    PracticeMath.render(element, statement);
    return;
  }
  // KaTeX collapses source newlines; build a prompt + stacked A–D list first.
  element.replaceChildren();
  const prompt = document.createElement('span');
  prompt.className = 'problem-prompt';
  const list = document.createElement('span');
  list.className = 'problem-options';
  list.setAttribute('role', 'list');
  PracticeMath.render(prompt, choice.prompt);
  for (const option of choice.options) {
    const item = document.createElement('span');
    item.className = 'problem-option';
    item.setAttribute('role', 'listitem');
    PracticeMath.render(item, option);
    list.append(item);
  }
  element.append(prompt, list);
}

function template(id, uid) {
  if (!id) return '';
  const html = bundle.templates[id];
  if (typeof html !== 'string') throw new Error(`缺少步骤模板：${id}`);
  return html.replace(/\{\{uid\}\}/g, escapeHTML(uid));
}

// A redraw rebuilds the explorer, so its axis position is kept per picture uid.
const axisPositions = new Map();

function mountAxisExplorer(host) {
  const spec = JSON.parse(host.dataset.graph);
  const {uid, params} = spec, {min, max, step} = params.axis;
  const explorer = {...params, uid};
  const input = host.querySelector('[data-axis-input]'), svg = host.querySelector('svg');
  const move = value => {
    const h = Number(Math.min(max, Math.max(min, min + Math.round((value - min) / step) * step)).toFixed(6));
    axisPositions.set(uid, h);
    host.querySelector('[data-axis-layer]').innerHTML = PracticeComponents.axisExplorerLayer(explorer, h);
    input.value = h;
  };
  const fromPointer = event => {
    const box = svg.getBoundingClientRect(), [xmin, xmax] = params.bounds;
    move(xmin + ((event.clientX - box.left) / box.width * 360 - 48) / 270 * (xmax - xmin));
  };
  if (axisPositions.has(uid)) move(axisPositions.get(uid));
  input.addEventListener('input', () => move(Number(input.value)));
  svg.addEventListener('pointerdown', event => { fromPointer(event); svg.setPointerCapture(event.pointerId); });
  svg.addEventListener('pointermove', event => { if (svg.hasPointerCapture(event.pointerId)) fromPointer(event); });
}

function hydrate(root) {
  const draw = host => {
    const svg = host.dataset.graph !== undefined
      ? PracticeComponents.graph(JSON.parse(host.dataset.graph))
      : PracticeComponents.quadraticGraph(JSON.parse(host.dataset.quadraticGraph));
    if (typeof svg !== 'string' || !/^\s*<(?:svg\b|div class="axis-explorer")/.test(svg)) throw new Error('graph_unavailable');
    return svg;
  };
  const mount = (host, svg) => {
    host.innerHTML = svg;
    host.dataset.graphRendered = 'true';
    if (/^\s*<div class="axis-explorer"/.test(svg)) mountAxisExplorer(host);
  };
  // Finish the entire option group before mounting any picture. A renderer failure
  // restores every original label without changing the verified decision or draft.
  for (const group of root.querySelectorAll('[data-graph-fallback]:not([data-graph-rendered])')) {
    try {
      const hosts = [...group.querySelectorAll('[data-graph]'), ...group.querySelectorAll('[data-quadratic-graph]')];
      const pictures = hosts.map(draw);
      hosts.forEach((host, i) => mount(host, pictures[i]));
    } catch {
      group.innerHTML = group.dataset.graphFallback;
      group.className = 'gw-graph-fallback';
    }
    group.dataset.graphRendered = 'true';
  }
  const singles = [...root.querySelectorAll('[data-quadratic-graph]:not([data-graph-rendered])'),
    ...root.querySelectorAll('[data-graph]:not([data-graph-rendered])')];
  for (const host of singles) {
    try { mount(host, draw(host)); }
    catch { (host.closest('.gw-figure') || host).remove(); }
  }
  renderMath(root);
  formulaFitter?.refresh();
}

/* A server-built picture beside a question or a completed step; the caption names the sample it shows. */
function figureHTML(graph, uid, kind) {
  if (!PracticeComponents.validateGraph(graph)) return '';
  const caption = graph.caption ? `<figcaption data-math-text>${escapeHTML(graph.caption)}</figcaption>` : '';
  return `<figure class="gw-figure gw-${kind}-graph"><span class="gw-figure-plot" data-graph="${escapeHTML(JSON.stringify({...graph, uid}))}"></span>${caption}</figure>`;
}

// Case pictures come as a set: drawn side by side when every one is valid, otherwise not at all.
const caseGraphs = decision => decision?.source === 'stream' && Array.isArray(decision.completion_graphs) &&
  decision.completion_graphs.length > 1 && decision.completion_graphs.every(PracticeComponents.validateGraph)
  ? decision.completion_graphs : null;

function caseFiguresHTML(decision, uid) {
  const graphs = caseGraphs(decision);
  return graphs ? `<div class="gw-case-figures">${graphs.map((graph, index) => figureHTML(graph, `${uid}-case-${index}`, 'completion')).join('')}</div>` : '';
}

function completionFiguresHTML(decision, uid, answer) {
  if (decision.source !== 'stream') return '';
  const figures = (decision.completion_graph ? figureHTML(decision.completion_graph, uid, 'completion') : '') +
    caseFiguresHTML(decision, uid) + domainCompletionHTML(decision, uid) +
    (decision.show_source_graph ? `<div data-source-graph="${escapeHTML(decision.id)}" data-readonly="true"></div>` : '') +
    (decision.figure_choices ? `<div data-figure-choices="${escapeHTML(decision.id)}" data-selected="${escapeHTML(answer)}" data-readonly="true"></div>` : '');
  if (!decision.completion_group) return figures;
  const heading = `${uid}-group`;
  return `<section class="gw-completion-group" aria-labelledby="${escapeHTML(heading)}"><h3 id="${escapeHTML(heading)}">${escapeHTML(decision.completion_group)}</h3>${figures || partAnswerHTML(decision, answer)}</section>`;
}

function conditionLinesHTML(decision, uid) {
  return (decision.condition_number_lines || []).map((line, index) => domainLineHTML(line, `${uid}-condition-${index}`, 'condition')).join('');
}

function domainLineHTML(line, uid, kind) {
  const graph = domainNumberLineGraph(line);
  return graph ? figureHTML(graph, uid, kind)
    : `<div class="gw-number-line-fallback"><p data-math-text>$${escapeHTML(line.label)}$</p><p>端点过近，改用集合式展示。</p></div>`;
}

function domainCompletionHTML(decision, uid) {
  return conditionLinesHTML(decision, uid)
    + (decision.completion_number_line ? domainLineHTML(decision.completion_number_line, `${uid}-intersection`, 'completion') : '')
    + (decision.endpoint_checks === undefined ? '' : domainEndpointCardHTML(decision.endpoint_checks));
}

function domainEndpointCardHTML(checks) {
  try { return endpointChecksHTML(checks); }
  catch (error) {
    if (!['domain_visuals.endpoint_checks', 'domain_visuals.unverified_endpoint'].includes(error?.message)) throw error;
    return '<section class="gw-endpoint-checks" data-state="unavailable" role="status"><h3>端点检查暂不可用</h3><p>端点数据未通过校验，本卡片不展示取舍结论。请刷新重试。</p></section>';
  }
}

function domainPremisesHTML(decision, uid) {
  if (!decision.condition_number_lines?.length) return '';
  return `<div class="gw-condition-lines"><p>已求出的范围</p>${conditionLinesHTML(decision, uid)}</div>`;
}

// A server board states what the question works from, in place of the card's own premises.
function boardHTML(board) {
  if (board.layout === 'derivation') return '<div data-derivation-board></div>';
  return `<div class="visual-board gw-question-board"><div class="board-caption">${escapeHTML(board.caption)}</div><div class="formula case-lines">${board.lines.map(line => `<p class="case-line" data-math-text>${escapeHTML(line)}</p>`).join('')}</div></div>`;
}

const activeRunId = () => state.run?.id || 'intro';
const decisionKey = decision => `${activeRunId()}:${decision.id}`;
const optionsOf = component => component.options || [];

function emptyAnswer(decision) {
  const component = decision.interaction;
  if (component.type === 'read') return 'read';
  if (component.type === 'choice') return null;
  if (['multi', 'original_choice_exact_set'].includes(component.type)) return [];
  if (component.type === 'method_cards') return emptyMethodAnswer(decision);
  if (component.type === 'plane') return ['', '', ''];
  if (component.type === 'grid') return ['', ''];
  return Array(component.slots?.length ?? component.slot_labels?.length ?? 2).fill('');
}

const covers = (method, x, y) => method.cells.some(cell => cell[0] === x && cell[1] === y);

/* A plane answer is [x, y, method]: the cell the problem sits in, then one method covering it. */
function planeChoice(decision, answer) {
  const {x, y, methods} = decision.interaction;
  const [valueX, valueY, value] = Array.isArray(answer) ? answer : [];
  return {
    optionX: x.options.find(option => option.value === valueX),
    optionY: y.options.find(option => option.value === valueY),
    method: methods.find(method => method.value === value),
    here: methods.filter(method => covers(method, valueX, valueY)),
  };
}

const zoneAt = (component, x, y) => component.zones.find(zone => covers(zone, x, y));

/* A grid answer is [x, y]: one cell of a map whose zones name what that cell means. */
function gridChoice(decision, answer) {
  const {x, y} = decision.interaction;
  const [valueX, valueY] = Array.isArray(answer) ? answer : [];
  const optionX = x.options.find(option => option.value === valueX);
  const optionY = y.options.find(option => option.value === valueY);
  return {optionX, optionY, zone: optionX && optionY ? zoneAt(decision.interaction, valueX, valueY) : null};
}

function ready(decision) {
  if (decision.figure_choices && !choicePicturesReady.has(decision.id)) return false;
  if (decision.show_source_graph && !choicePicturesReady.has(`${decision.id}:source`)) return false;
  if (decision.interaction.layout === 'connections') return draft.checks.every(Boolean) && Boolean(draft.method);
  if (decision.interaction.type === 'method_cards') return draft.confirmed === decision.interaction.checks.length && Boolean(draft.method);
  if (decision.interaction.type === 'read') return true;
  if (decision.interaction.type === 'choice') return draft != null;
  if (decision.interaction.type === 'multi') return draft.length > 0;
  if (decision.interaction.type === 'original_choice_exact_set') return Array.isArray(draft);
  return draft.length > 0 && draft.every(value => value !== '');
}

function projectDraft(decision, answer) {
  const empty = emptyAnswer(decision);
  if (decision.interaction.type === 'method_cards') return projectMethodAnswer(decision, answer);
  if (decision.interaction.type === 'read') return 'read';
  if (decision.interaction.type === 'choice') return typeof answer === 'string' ? answer : empty;
  if (!Array.isArray(answer)) return empty;
  if (['multi', 'original_choice_exact_set'].includes(decision.interaction.type)) return answer.filter(value => typeof value === 'string');
  return empty.map((_, index) => typeof answer[index] === 'string' ? answer[index] : '');
}

function ensureDraft(decision) {
  const key = decisionKey(decision);
  if (key !== draftKey) {
    const routeDraft = actor === 'student' && bundle.stream ? streamDraft(bundle, state) : null;
    const kept = routeDraft?.decision === decision.id ? {draft: routeDraft.answer, ...routeDraft}
      : actor === 'student' && keptDraft?.key === key ? keptDraft : null;
    draftKey = key; draft = kept ? projectDraft(decision, kept.draft) : emptyAnswer(decision); selectedSlot = kept?.selectedSlot ?? null;
    if (actor === 'student') { submitted = kept?.submitted ?? null; keptDraft = null; }
  }
  // Failed recorded actions can have any input shape. Only the display draft is normalized.
  if (actor === 'replay' && submitted?.decision === decision.id) draft = projectDraft(decision, submitted.answer);
}

function choiceLabel(component, answer, index = 0) {
  const options = component.slots?.[index]?.options || optionsOf(component);
  return options.find(option => option.value === answer)?.label || component.term_labels?.[answer] || answer;
}

function answerSummary(decision, answer) {
  if (decision.interaction.type === 'method_cards') return selectedMethod(decision, answer)?.label || '';
  if (decision.interaction.type === 'read') {
    const method = decision.interaction.methods?.find(item => item.route) || decision.interaction.methods?.[0];
    if (method?.label) return method.label;
    return decision.question || '已阅读';
  }
  if (decision.interaction.type === 'grid') {
    const {optionX, optionY, zone} = gridChoice(decision, answer);
    return zone ? `${zone.label}（${optionX.label}，${optionY.label}）` : '';
  }
  if (decision.interaction.type === 'plane') {
    const {optionX, optionY, method} = planeChoice(decision, answer);
    return [optionX && `${decision.interaction.x.label}${optionX.label}`, optionY && `${decision.interaction.y.label}${optionY.label}`, method?.label].filter(Boolean).join('；');
  }
  const values = Array.isArray(answer) ? answer : [answer];
  return values.map((value, index) => choiceLabel(decision.interaction, value, index)).filter(Boolean).join('；');
}

function resultText(result) {
  if (typeof result === 'string') return result;
  return result.text || result.label || result.expression || result.math || '';
}

function decisionById(id, route) {
  return bundle.intro.find(decision => decision.id === id) || bundle.routes[route]?.steps.find(decision => decision.id === id);
}
const anyDecision = id => bundle.intro.find(decision => decision.id === id) ||
  Object.values(bundle.routes).flatMap(route => route.steps).find(decision => decision.id === id);

/* A completed checklist reads as "what was asked → what was decided", one row per item. */
function checklistAnswerHTML(decision, answer) {
  const rows = decision.interaction.slots.map((slot, index) => `<div><dt data-math-text>${escapeHTML(slot.label)}</dt><dd data-math-text>${escapeHTML(choiceLabel(decision.interaction, answer?.[index], index))}</dd></div>`);
  return `<dl class="gw-answer-rows">${rows.join('')}</dl>`;
}

/* Axes cross in the middle: x options run left → right, y options top → bottom, one cell per quadrant.
   Completed cards reuse the same figure read-only, with the chosen cell marked. */
function axesHTML(decision, answer, cells, interactive) {
  const {x, y, title} = decision.interaction;
  const end = (option, side) => `<span class="gw-plane-end" data-end="${side}"><b>${escapeHTML(option.label)}</b><small data-math-text>${escapeHTML(option.note || '')}</small></span>`;
  const role = interactive ? `role="group" aria-label="${escapeHTML(title || '坐标图')}"`
    : `role="img" aria-label="${escapeHTML(answerSummary(decision, answer).replace(/\$/g, ''))}"`;
  return `<div class="gw-plane${interactive ? '' : ' is-static'}" ${role}><div class="gw-plane-top"><p class="gw-plane-ylabel" data-math-text>${escapeHTML(y.label)}</p>${end(y.options[0], 'top')}</div><div class="gw-plane-field"><span class="gw-plane-axis" data-axis="x"></span><span class="gw-plane-axis" data-axis="y"></span>${cells.join('')}${end(x.options[0], 'left')}${end(x.options[1], 'right')}</div><div class="gw-plane-bottom"><span></span>${end(y.options[1], 'bottom')}<p class="gw-plane-xlabel" data-math-text>${escapeHTML(x.label)}</p></div></div>`;
}

/* The method plane: each quadrant lists the methods covering it; the answer adds one of them. */
function planeHTML(decision, answer, interactive = true) {
  const {x, y, methods} = decision.interaction;
  const [valueX, valueY, value] = Array.isArray(answer) ? answer : [];
  const cells = y.options.flatMap(row => x.options.map(column => {
    const here = methods.filter(method => covers(method, column.value, row.value));
    const selected = column.value === valueX && row.value === valueY;
    const tags = here.map(method => `<span class="gw-plane-tag" data-method="${escapeHTML(method.value)}"${selected && method.value === value ? ' data-chosen' : ''}>${escapeHTML(method.label)}</span>`).join('');
    const content = tags + (selected ? '<span class="gw-plane-pin" aria-hidden="true">本题</span>' : '');
    if (!interactive) return `<div class="gw-plane-cell" data-selected="${selected}">${content}</div>`;
    const name = `横轴${column.label}，纵轴${row.label}；可用：${here.map(method => method.label).join('、')}`;
    return `<button type="button" class="gw-plane-cell" data-plane-cell="${escapeHTML(`${column.value}|${row.value}`)}" data-selected="${selected}" aria-pressed="${selected}" aria-label="${escapeHTML(name)}">${content}</button>`;
  }));
  const plane = axesHTML(decision, answer, cells, interactive);
  if (!interactive) return plane;
  const {here} = planeChoice(decision, answer);
  const picker = valueX && valueY
    ? `<div class="gw-plane-methods" role="group" aria-label="这一格能用的方法"><p>这一格能用的方法，选一种开始解：</p><div>${here.map(method => `<button type="button" data-plane-method="${escapeHTML(method.value)}" data-method="${escapeHTML(method.value)}" aria-pressed="${method.value === value}">${escapeHTML(method.label)}${method.route_plan === 'capability_gap' ? '<small>详细步骤暂不支持</small>' : method.route ? '' : '<small>本 Demo 未展开</small>'}</button>`).join('')}</div></div>`
    : '<p class="gw-plane-hint">先在坐标图里点一格。</p>';
  return plane + picker;
}

/* A zone map on the same crossed axes: every quadrant names what that cell means, the answer pins one. */
function gridHTML(decision, answer, interactive = true) {
  const component = decision.interaction;
  const [valueX, valueY] = Array.isArray(answer) ? answer : [];
  const cells = component.y.options.flatMap(row => component.x.options.map(column => {
    const zone = zoneAt(component, column.value, row.value);
    const selected = column.value === valueX && row.value === valueY;
    const content = `<span class="gw-plane-tag" data-zone="${escapeHTML(zone.value)}"${selected ? ' data-chosen' : ''}>${escapeHTML(zone.label)}</span>${selected ? '<span class="gw-plane-pin" aria-hidden="true">本题</span>' : ''}`;
    if (!interactive) return `<div class="gw-plane-cell" data-selected="${selected}">${content}</div>`;
    const name = `横轴${column.label}，纵轴${row.label}：${zone.label}`;
    return `<button type="button" class="gw-plane-cell" data-grid-cell="${escapeHTML(`${column.value}|${row.value}`)}" data-selected="${selected}" aria-pressed="${selected}" aria-label="${escapeHTML(name)}">${content}</button>`;
  }));
  return axesHTML(decision, answer, cells, interactive);
}

function completedFeedbackHTML(decision) {
  if (decision.stem_board?.layout === 'derivation') return '';
  return typeof decision.feedback?.answer === 'string' && decision.feedback.answer.trim()
    ? `<p class="gw-result" data-math-text>${escapeHTML(decision.feedback.answer)}</p>` : '';
}

function streamCompletedAnswerHTML(decision, answer) {
  // The verified board owns the conclusion. Do not repeat its answer and
  // feedback above it; choices without a mathematical conclusion still need them.
  if (decision.interaction.type === 'read' || decision.stem_board?.layout === 'derivation') return '';
  if (!['plane', 'grid', 'method_cards'].includes(decision.interaction.type) &&
      decisionMathSteps(decision).some(step => (step.highlight || step.after?.length) &&
        !step.highlight?.conclusion_only && step.explanation?.trim())) return '';
  const summary = answerSummary(decision, answer);
  if (!summary) return '';
  return `<p class="gw-answer" data-math-text>${escapeHTML(summary)}</p>${completedFeedbackHTML(decision)}`;
}

function completedHTML(record, number, runId, route) {
  const decision = decisionById(record.decision, route);
  if (!decision) return '';
  const uid = `gw-${runId}-${decision.id}`;
  // A grid keeps its map as the record; only the page's collapsible derivation is borrowed from the display.
  const derivation = () => decision.display ? /<details[\s\S]*<\/details>/.exec(template(decision.display, uid))?.[0] || '' : '';
  const summary = answerSummary(decision, record.answer);
  const methodNote = decision.interaction.type === 'read' && decision.question && decision.question !== summary
    ? `<p class="gw-result" data-math-text>${escapeHTML(decision.question.replace(/^使用[^：]+：/, ''))}</p>` : '';
  const body = decision.answer_completion ? formulaAnswerHTML(decision, record.answer, false)
    : decision.interaction.type === 'plane' ? planeHTML(decision, record.answer, false)
    : decision.interaction.type === 'method_cards' ? methodCardsHTML(decision, record.answer, false)
    : decision.source === 'stream' && decision.stream_last_part
    ? `${completionBoardHTML(decision)}${streamCompletedAnswerHTML(decision, record.answer)}<div data-stream-completed="${escapeHTML(decision.id)}"></div>`
    : decision.completion_board ? completionBoardHTML(decision)
    : decision.interaction.type === 'grid' ? gridHTML(decision, record.answer, false) + derivation()
    : decision.display ? template(decision.display, uid)
    : decision.interaction.type === 'checklist' ? checklistAnswerHTML(decision, record.answer)
    : `<p class="gw-answer" data-math-text>${escapeHTML(summary)}</p>${methodNote}`;
  const results = decision.source !== 'stream' && !decision.display && !decision.completion_board ? (record.results || []).map(resultText).filter(Boolean).map(text => `<p class="gw-result" data-math-text>${escapeHTML(text)}</p>`).join('') : '';
  const figure = completionFiguresHTML(decision, `${uid}-done`, record.answer);
  const context = decision.source_context ? `<p class="gw-result" data-math-text>${escapeHTML(decision.source_context)}</p>` : '';
  return `<details class="gw-completed" data-completed-decision="${escapeHTML(decision.id)}"><summary class="step-heading"><span class="step-number" aria-label="第 ${number} 步">✓</span><span class="gw-step-title" data-math-text>${escapeHTML(stepTitle(decision))}</span><span class="status">已完成</span></summary><div class="gw-completed-body">${context}${figure}${body}${results}</div></details>`;
}

/* Group only for display: later chunks may extend a card without changing published
   decisions, answers, or the math evidence belonging to each interaction. */
function groupParts(decision) {
  if (decision?.source !== 'stream') return [];
  const steps = bundle.routes[state.run?.route]?.steps || [];
  const index = steps.findIndex(item => item.id === decision.id);
  if (index < 0) return [];
  const caseScope = item => JSON.stringify([...new Set(ownMathSteps(item).map(card =>
    JSON.stringify([card.case_path || [], card.branch_id || ''])))].sort());
  const matches = item => item.source === 'stream'
    && ['target_ref', 'scope', 'route_id'].every(key => item[key] === decision[key])
    && ['option_id', 'target_ref', 'left_ref', 'right_ref', 'phase'].every(key => item.option_context?.[key] === decision.option_context?.[key])
    && (decision.stream_part_count > 1 && item.stream_interaction_id === decision.stream_interaction_id
      || decision.stream_card_group && item.stream_card_group === decision.stream_card_group
        && decision.stream_group_title && item.stream_group_title === decision.stream_group_title
        && caseScope(item) === caseScope(decision));
  let start = index, end = index + 1;
  while (start > 0 && matches(steps[start - 1])) start--;
  while (end < steps.length && matches(steps[end])) end++;
  return steps.slice(start, end);
}

const groupOf = decision => {
  const parts = groupParts(decision);
  return parts.length > 1 ? parts[0].stream_interaction_id : null;
};

function stepTitle(decision) {
  // Prefer the student-facing card title (card_group_title) when the stream set one.
  const title = decision.stream_group_title || decision.title || decision.question || '当前判断';
  const cards = bundle.stream && decision.source === 'stream' ? ownMathSteps(decision) : [];
  // Show the purpose of the reused domain method, including its smaller actions.
  // Use verified method references rather than matching a question's wording.
  return cards.length && cards.every(card => card.method_ref?.split('#')[0] === 'method-domain-intersection')
    ? `判断定义域 · ${title}` : title;
}

function stepUnits() {
  const route = state.run?.route, units = [];
  for (const record of state.run?.completed || []) {
    const group = groupOf(decisionById(record.decision, route)), last = units.at(-1);
    if (group && last?.group === group) last.records.push(record);
    else units.push({group, records: [record]});
  }
  const last = units.at(-1);
  const lastDecision = last && decisionById(last.records.at(-1).decision, route);
  const open = last?.group && groupParts(lastDecision).at(-1)?.id !== lastDecision.id ? units.pop() : null;
  return {units, open};
}

function completionBoardHTML(decision) {
  return decision.completion_board ? `<div data-completion-board="${escapeHTML(decision.id)}"></div>` : '';
}

function partAnswerHTML(decision, answer) {
  if (decision.answer_completion) return formulaAnswerHTML(decision, answer, false);
  const figure = decision.source === 'stream' && decision.completion_graph
    ? figureHTML(decision.completion_graph, `gw-${activeRunId()}-${decision.id}-part`, 'completion') : '';
  if (decision.completion_board) return figure + completionBoardHTML(decision);
  return figure + (decision.interaction.type === 'checklist' ? checklistAnswerHTML(decision, answer)
    : `<p class="gw-answer" data-math-text>${escapeHTML(answerSummary(decision, answer))}</p>`);
}

function partRowsHTML(records) {
  return records.map(record => {
    const decision = decisionById(record.decision, state.run.route);
    return `<div class="gw-part-row"><p class="gw-part-label"><span aria-hidden="true">✓</span><span data-math-text>${escapeHTML(decision.title || '')}</span></p>${partAnswerHTML(decision, record.answer)}</div>`;
  }).join('');
}

function groupCompletedHTML(unit, number) {
  const decisions = unit.records.map(record => decisionById(record.decision, state.run.route)), last = decisions.at(-1);
  const sourceTargets = new Set();
  // Keep each part's figure with that part's board, not stacked above every sub-question.
  const body = decisions.map((item, index) => {
    const target = item.target_ref || bundle.stream?.target_ref || '';
    const repeatedSource = item.show_source_graph && sourceTargets.has(target);
    if (item.show_source_graph) sourceTargets.add(target);
    const figure = completionFiguresHTML(repeatedSource ? {...item, show_source_graph: false} : item,
      `gw-${activeRunId()}-${item.id}-done`, unit.records[index].answer);
    const evidence = item.stream_last_part && item.id !== last.id
      ? `<div data-stream-completed="${escapeHTML(item.id)}"></div>` : '';
    return `<div class="gw-part-row">${figure}${completionBoardHTML(item)}${evidence}</div>`;
  }).join('');
  // A merged card may keep its proof in each part's feedback rather than its
  // conclusion-only math boards. Preserve that explanation after all parts pass.
  const feedback = decisions.map(decision => {
    if (decisionMathSteps(decision).some(step => !step.highlight?.conclusion_only && step.explanation?.trim())) return '';
    const explanation = completedFeedbackHTML(decision);
    return explanation ? `<div class="gw-part-row"><p class="gw-part-label" data-math-text>${escapeHTML(decision.title || '')}</p>${explanation}</div>` : '';
  }).join('');
  return `<details class="gw-completed" data-completed-decision="${escapeHTML(last.id)}"><summary class="step-heading"><span class="step-number" aria-label="第 ${number} 步">✓</span><span class="gw-step-title" data-math-text>${escapeHTML(stepTitle(last))}</span><span class="status">已完成</span></summary><div class="gw-completed-body">${body}<div data-stream-completed="${escapeHTML(last.id)}"></div>${feedback}</div></details>`;
}

/* Within the card: every part as a numbered stop, the answered ones folded into rows above the current one. */
function partStepperHTML(decision) {
  const parts = groupParts(decision), currentIndex = parts.findIndex(part => part.id === decision.id);
  return `<ol class="gw-part-stepper" aria-label="这一步的小问">${parts.map((part, index) => {
    const status = index < currentIndex ? 'done' : index === currentIndex ? 'current' : 'todo';
    return `<li data-state="${status}"${status === 'current' ? ' aria-current="step"' : ''}><span aria-hidden="true">${status === 'done' ? '✓' : index + 1}</span><span data-math-text>${escapeHTML(part.title || '')}</span></li>`;
  }).join('')}</ol>`;
}

// Graph options carry no visible formula unless they set a name: the student has to read the picture.
function graphOptionsHTML(decision) {
  const component = decision.interaction, multi = component.type === 'multi';
  const uid = `gw-${activeRunId()}-${decision.id}`, options = optionsOf(component);
  const fallback = textOptionsHTML(decision);
  if (options.some(option => !option.graph || (decision.source === 'stream' || Object.hasOwn(option.graph, 'kind')) && !PracticeComponents.validateGraph(option.graph))) return fallback;
  // Streamed pictures name their kind; authored ones are bare quadratic parameters.
  const kind = options.find(option => option.graph?.kind)?.graph.kind;
  return `<div class="gw-graph-options" role="group" aria-label="${escapeHTML(decision.title || decision.question)}" data-graph-fallback="${escapeHTML(fallback)}" data-count="${options.length}"${kind ? ` data-kind="${escapeHTML(kind)}"` : ''}>${options.map(option => {
    const selected = multi ? draft.includes(option.value) : draft === option.value;
    const pick = multi ? `data-multi="${escapeHTML(option.value)}"` : `data-choice="${escapeHTML(component.field)}" data-value="${escapeHTML(option.value)}"`;
    const graph = escapeHTML(JSON.stringify({...option.graph, uid: `${uid}-${option.value}`}));
    const figure = option.graph?.kind ? `<span class="gw-graph-figure" data-graph="${graph}"></span>` : `<span class="gw-graph-option-figure" data-quadratic-graph="${graph}"></span>`;
    const caption = option.graph?.caption ? `<span class="gw-graph-option-caption" data-math-text>${escapeHTML(option.graph.caption)}</span>` : '';
    return `<button type="button" ${pick} aria-pressed="${selected}" aria-label="${escapeHTML(option.label)}"><span class="gw-checkbox" aria-hidden="true">${selected ? '✓' : ''}</span>${figure}${caption}${option.name ? `<span class="gw-graph-option-name">${escapeHTML(option.name)}</span>` : ''}</button>`;
  }).join('')}</div>`;
}

function textOptionsHTML(decision) {
  const component = decision.interaction;
  if (component.type === 'choice') return PracticeComponents.choices(component, draft, decision.title || decision.question);
  return `<div class="gw-multi" role="group" aria-label="${escapeHTML(decision.title || decision.question)}">${optionsOf(component).map(option => `<button type="button" data-multi="${escapeHTML(option.value)}" aria-pressed="${draft.includes(option.value)}"><span class="gw-checkbox" aria-hidden="true">${draft.includes(option.value) ? '✓' : ''}</span><span data-math-text>${escapeHTML(option.label)}</span></button>`).join('')}</div>`;
}

function interactionHTML(decision) {
  const component = decision.interaction;
  if (decision.answer_completion) return formulaAnswerHTML(decision, draft);
  if (component.type === 'read') return '';
  const board = template(decision.board, `gw-${activeRunId()}-${decision.id}-active`);
  if (['choice', 'multi'].includes(component.type) && optionsOf(component).some(option => option.graph)) return board + graphOptionsHTML(decision);
  if (component.type === 'choice') return board + textOptionsHTML(decision);
  if (component.type === 'method_cards') return board + methodCardsHTML(decision, draft);
  if (component.type === 'plane') return board + planeHTML(decision, draft);
  if (component.type === 'grid') return board + gridHTML(decision, draft);
  if (['multi', 'original_choice_exact_set'].includes(component.type)) {
    return board + textOptionsHTML(decision);
  }
  if (component.type === 'checklist') {
    // A draft only marks a selection. Correctness and authored feedback wait for submission.
    const slots = component.slots.map(row => ({...row, options: row.options.map(({note, ...option}) => option)}));
    return PracticeComponents.checklist({component: {...component, slots}, pair: draft, board});
  }
  if (component.type === 'fill') {
    const content = PracticeComponents.fill({board, slotLabels: component.slot_labels,
      slot: index => PracticeComponents.slot({stage: 0, index, value: draft[index],
        label: component.term_labels?.[draft[index]], title: component.slot_labels?.[index] || `第 ${index + 1} 项`,
        shape: component.slot_shapes?.[index]})});
    const picker = selectedSlot == null ? '' : `<div class="gw-token-panel" role="group" aria-label="${escapeHTML(component.slot_labels?.[selectedSlot] || '选择填空值')}"><p>${escapeHTML(component.slot_labels?.[selectedSlot] || '填入数学项')}</p><div>${component.terms.map(value => `<button type="button" data-token="${escapeHTML(value)}" aria-pressed="${draft[selectedSlot] === value}"><span data-math-text>${escapeHTML(component.term_labels?.[value] || value)}</span></button>`).join('')}</div><button type="button" class="gw-token-close">收起选项</button></div>`;
    return content + picker;
  }
  throw new Error(`暂不支持的交互：${component.type}`);
}

function attemptedCalculation(decision) {
  if (!submitted || state.lastFeedback?.status !== 'wrong' || !decision.attempt_calculations || !Array.isArray(submitted.answer)) return '';
  const answers = submitted.answer;
  const id = answers.length === 1 ? decision.attempt_calculations[answers[0]] : decision.attempt_calculations[answers[0]]?.[answers[1]];
  return id ? template(id, `gw-${activeRunId()}-${decision.id}-attempt`) : '';
}

function feedbackHTML() {
  const feedback = state.lastFeedback;
  if (!feedback || (!submitted && actor !== 'replay')) return '';
  const label = {wrong: '再想一想', uncovered: '有效思路 · 本 Demo 未展开', passed: '这一步已确认', ...bundle.feedbackLabels}[feedback.status] || '提示';
  const href = feedback.href?.startsWith('/knowledge/') ? `<a href="${escapeHTML(feedback.href)}" target="_blank" rel="noopener">查看这条思路 ↗</a>` : '';
  return `<div class="gw-feedback" data-status="${escapeHTML(feedback.status)}" role="status"><strong>${label}</strong><p data-math-text>${escapeHTML(feedback.message || '')}</p>${href}</div>`;
}

const ownMathSteps = decision => decisionMathSteps(decision).filter(card => !(decision.stream_folded || []).includes(card.step_id));

/* Merge inputs come from completed branches, never the active card's answer. */
function mergePremisesHTML(current) {
  if (!bundle.stream || current?.source !== 'stream') return '';
  const active = ownMathSteps(current)[0];
  if (active?.highlight?.layout !== 'merge') return '';
  const parent = active.case_path || [], cases = new Map();
  const collect = (card, results = []) => {
    if (card.ordinal >= active.ordinal) return;
    const path = card.case_path || [];
    if (!parent.every((part, index) => path[index] === part)) return;
    // A descendant branch is not the result of its whole parent case.
    if (path.length > parent.length + 1 || (path.length > parent.length && card.branch_id)) return;
    const key = path.length > parent.length ? JSON.stringify(path)
      : card.branch_id ? JSON.stringify([path, card.branch_id]) : null;
    if (!key) return;
    const lines = results.length ? results : card.highlight?.result ? [card.highlight.result]
      : (card.after || []).map(value => value.latex ? `$${value.latex}$` : '').filter(Boolean);
    if (!lines.length || (cases.get(key)?.ordinal || 0) > card.ordinal) return;
    const condition = card.branch_condition || card.case_condition;
    const label = condition?.latex ? `$${condition.latex}$` : card.title || '已完成情况';
    cases.set(key, {ordinal: card.ordinal, label, lines});
  };
  for (const record of state.run?.completed || []) {
    const decision = decisionById(record.decision, state.run.route);
    if (decision?.source !== 'stream' || !decision.stream_last_part) continue;
    const cards = decisionMathSteps(decision), last = ownMathSteps(decision).at(-1);
    for (const card of cards) collect(card, card === last ? (record.results || []).map(resultText).filter(Boolean) : []);
  }
  // Explicitly folded predecessors are already available givens, even when
  // their repetitive quiz was omitted. Their formulas are not the merge result.
  for (const card of decisionMathSteps(current)) if ((current.stream_folded || []).includes(card.step_id)) collect(card);
  if (!cases.size) return '';
  const rows = [...cases.values()].map(({label, lines}) => `<div class="gw-merge-premise"><dt data-math-text>${escapeHTML(label)}</dt><dd>${lines.map(line => `<p data-math-text>${escapeHTML(line)}</p>`).join('')}</dd></div>`).join('');
  return `<div class="gw-carry gw-merge-premises"><p class="gw-carry-label">已得各情况结果</p><dl>${rows}</dl></div>`;
}

/* Case-local results may only carry within their frozen branch. A new branch supplies its own premise. */
function caseCarryHTML(previous, current) {
  if (!bundle.stream || current?.source !== 'stream') return null;
  const active = ownMathSteps(current)[0], prior = previous?.source === 'stream' ? ownMathSteps(previous).at(-1) : null;
  if (!active) return null;
  const from = prior?.case_path || [], to = active.case_path || [];
  const fromBranch = typeof prior?.branch_id === 'string' ? prior.branch_id : '';
  const toBranch = typeof active.branch_id === 'string' ? active.branch_id : '';
  const sameCase = JSON.stringify(from) === JSON.stringify(to);
  if (sameCase && fromBranch === toBranch) return null;
  const returning = to.length < from.length && to.every((part, index) => from[index] === part);
  const merging = (!to.length && !toBranch) || (sameCase && Boolean(fromBranch) && !toBranch);
  const label = merging ? '汇总各情况' : returning ? '返回上层情况'
    : from.length || fromBranch ? '切换情况' : '当前情况';
  // The server publishes this condition with the mathematical card and includes it in its hash.
  // Legacy cards can announce the boundary, but must not infer a condition from prose or branch IDs.
  const formulas = to.length || toBranch ? [...new Set([active.case_condition, ...(toBranch ? [active.branch_condition] : [])]
    .map(value => value?.latex).filter(value => typeof value === 'string' && value))] : [];
  const condition = formulas.length
    ? `<p data-math-text>${escapeHTML(`当前条件：${formulas.map(formula => `$${formula}$`).join(' 且 ')}`)}</p>` : '';
  return `<div class="gw-carry gw-case-transition" data-case-transition="${merging ? 'merge' : 'case'}"><p class="gw-carry-label">${label}</p>${condition}</div>`;
}

/* The previous step carried into the active card: its results, or its answer when it produced none. */
function carryHTML() {
  const {units, open} = stepUnits(), held = new Set(open?.records || []);
  const records = [...(state.introCompleted || []), ...(state.run?.completed || [])].filter(record => !held.has(record));
  const record = records.at(-1), decision = record && anyDecision(record.decision);
  const current = bundle.stream ? currentDecision(bundle, state) : null, premises = mergePremisesHTML(current);
  const active = current || bundle.routes?.[state.run?.route]?.steps?.[state.run?.completed?.length || 0];
  if (active?.stem_board?.layout === 'derivation') return '';
  if (active?.interaction.layout === 'connections') return '';
  if (active?.interaction.type === 'original_choice_exact_set' || active?.source === 'original_choice' && active.require_complete_options) return '';
  if (active?.option_context && decision?.option_context?.option_id !== active.option_context.option_id) return '';
  const transition = bundle.stream && caseCarryHTML(decision, current);
  if (transition || premises) return (transition || '') + premises;
  if (!decision) return '';
  const results = (record.results || []).map(resultText).filter(Boolean);
  const lines = results.length ? results : [carrySummary(decision, record.answer)].filter(Boolean);
  if (!lines.length) return '';
  const number = (state.introCompleted?.length || 0) + units.length;
  return `<div class="gw-carry"><p class="gw-carry-label" data-math-text>接第 ${number} 步 · ${escapeHTML(stepTitle(decision))}</p>${lines.map(text => `<p data-math-text>${escapeHTML(text)}</p>`).join('')}</div>`;
}

function carrySummary(decision, answer) {
  if (decision.interaction.type !== 'plane') return answerSummary(decision, answer);
  const {optionX, optionY, method} = planeChoice(decision, answer);
  return method ? `选用${method.label}（${[optionX?.note, optionY?.note].filter(Boolean).join('；')}）` : '';
}

/* `pending` replaces the current part while the AI has not answered it yet; only a part card uses it. */
function renderInteraction(decision, {focus, pending = null} = {}) {
  const host = $('#gw-active');
  if (!host) return;
  for (const [node, dispose] of choicePictureMounts) if (host.contains(node)) { dispose(); choicePictureMounts.delete(node); }
  choicePicturesReady.delete(decision.id);
  host.dataset.decisionId = decision.id;
  ensureDraft(decision);
  const disabled = actor === 'replay';
  const {units, open} = stepUnits(), grouped = Boolean(groupOf(decision));
  const number = (state.introCompleted?.length || 0) + units.length + 1;
  const title = stepTitle(decision);
  const head = `<header class="step-heading"><span class="step-number" aria-hidden="true">${number}</span><h2 id="gw-current-title" tabindex="-1" data-math-text>${escapeHTML(title)}</h2><span class="status">进行中</span></header>${carryHTML()}`;
  const parts = grouped ? partStepperHTML(decision) + (open ? `<div class="gw-part-done">${partRowsHTML(open.records)}</div>` : '') : '';
  const label = grouped ? `<p class="gw-part-current" id="gw-part-title" tabindex="-1" data-math-text>第 ${groupParts(decision).findIndex(part => part.id === decision.id) + 1} 问 · ${escapeHTML(decision.title || '')}</p>` : '';
  host.innerHTML = head + parts + (pending ?? `${label}<p class="question" data-math-text>${escapeHTML(decision.question || '')}</p>${decision.show_source_graph ? `<div data-source-graph="${escapeHTML(decision.id)}"></div>` : ''}${decision.source === 'stream' && decision.graph ? figureHTML(decision.graph, `gw-${activeRunId()}-${decision.id}-stem`, 'stem') : ''}${decision.stem_board && !decision.answer_completion ? boardHTML(decision.stem_board) : decision.source === 'stream' && decision.interaction.type === 'read' ? '<div class="gw-stream-context" data-stream-context></div>' : ''}<div class="gw-interaction" ${disabled ? 'inert' : ''}>${interactionHTML(decision)}</div>${feedbackHTML()}${attemptedCalculation(decision)}<div class="gw-submit-row"><button type="button" class="primary" id="gw-submit" ${disabled || busy || !ready(decision) ? 'disabled' : ''}>${escapeHTML(decision.submit_label || (decision.interaction.type === 'read' ? '读完了，下一步' : '确认，看看图谱如何变化'))} <span aria-hidden="true">→</span></button>${disabled ? '<span>正在查看 AI 回放</span>' : ''}</div>`);
  // Frozen before formulas are derivation inputs, not necessarily givens: they can be
  // the answer being asked for. Interactive premises belong in question/graph/stem_board
  // or the completed-step carry above; only read cards reveal the mathematical record.
  mountCompletionBoards(host);
  if (pending == null && decision.figure_choices) {
    const interaction = host.querySelector('.gw-interaction');
    interaction.innerHTML = `<div data-figure-choices="${escapeHTML(decision.id)}"></div>`;
    mountChoicePictures(interaction);
  }
  const context = pending == null && host.querySelector('[data-stream-context]');
  const derivation = pending == null && host.querySelector('[data-derivation-board]');
  if (derivation) {
    derivation.append(createDerivationBoard(document, decision.stem_board));
    renderStreamMath(derivation);
  }
  if (pending == null && decision.source_regions) {
    const selected = Array.isArray(draft) ? draft : draft == null ? [] : [draft];
    const question = host.querySelector('.question');
    question?.insertAdjacentHTML('afterend', expressionRegionsHTML(decision.source_regions, selected));
  }
  // The final choice may use already solved condition sets. Its own intersection
  // and endpoint checks only appear in completedHTML after an accepted answer.
  if (pending == null && decision.condition_number_lines?.length) {
    host.querySelector('.question')?.insertAdjacentHTML('afterend', domainPremisesHTML(decision, `gw-${activeRunId()}-${decision.id}-premise`));
  }
  if (context) {
    const folded = new Set(decision.stream_folded || []);
    const steps = decisionMathSteps(decision).filter(step => !folded.has(step.step_id));
    for (const step of steps) context.append(createMathCard(document, step,
      {renderMath: renderStreamMath, embedded: true, parentTitle: title}).node);
  }
  for (const button of host.querySelectorAll('[data-slot]')) {
    const expanded = Number(button.dataset.slot) === selectedSlot;
    button.setAttribute('aria-expanded', String(expanded));
    button.setAttribute('aria-haspopup', 'false');
  }
  hydrate(host);
  if (decision.interaction.layout === 'connections') {
    disposeMethodConnections();
    disposeMethodConnections = mountMethodConnections($('#gw-steps'));
  }
  if (focus) host.querySelector(focus)?.focus({preventScroll: true});
}

function describeBasis(ref) {
  const raw = typeof ref === 'string' ? ref : ref.ref || ref.id;
  const [id, entry] = raw.split('#');
  const node = graphView.nodes.find(item => item.id === id);
  const item = (node?.entries || node?.items || []).find(value => value.id === entry);
  return {id: raw, ref: raw, label: entry ? `${node?.label || id} · ${item?.title || item?.label || entry}` : node?.label || id};
}

function selectNode(node, view) {
  const panel = $('#gw-selection');
  const actual = (view?.calls || []).filter(call => call.ref === node.id || call.method === node.id);
  const note = actual.length ? `本路线已记录 ${actual.length} 次相关调用。` : '这是本题子图中的关联对象；候选不代表已经调用。';
  panel.hidden = false;
  panel.innerHTML = `<button type="button" class="gw-selection-close" data-selection-close aria-label="关闭节点详情">×</button><h3>${escapeHTML(node.label || node.id)}</h3><p>${escapeHTML(note)}</p><a href="${nodeHref(node)}" target="_blank" rel="noopener">查看公共节点详情 ↗</a>`;
}

function callStepTitle(call) {
  const method = graphView.nodes.find(node => node.id === call.method);
  return method?.steps?.find(step => step.id === call.step)?.title || call.step;
}

/* Graph state plus every node the walk has reached or offered so far, for the 3D growth view. */
function viewFor(shown) {
  const view = bundle.stream ? streamGraphState(bundle, shown) : graphState(bundle, shown);
  const seen = new Set(Object.keys(view.nodes).filter(id => view.nodes[id] !== 'idle'));
  for (const run of [{completed: shown.introCompleted}, ...(shown.archives || []), shown.run]) {
    for (const record of run.completed || []) for (const id of anyDecision(record.decision)?.candidateNodes || []) seen.add(id);
  }
  for (const id of view.archivedEdges) { const [from, , to] = id.split('|'); seen.add(from); seen.add(to); }
  view.seen = [...seen];
  return view;
}

const passedEvents = () => state.events.filter(event => event.status === 'passed');
const timelineNow = () => actor === 'replay' ? replayPosition : passedEvents().length;

function studentStateAt(count) {
  let next = createState(bundle);
  for (const event of passedEvents().slice(0, count)) {
    next = event.kind === 'switch_route' ? switchRoute(bundle, next, event.route) : submitAnswer(bundle, next, event.action);
  }
  return next;
}

function timelinePoints() {
  if (actor === 'replay') {
    if (!replay) return [];
    if (replayStatuses.replay !== replay) {
      let values = [];
      try { values = replayState(bundle, replay).events.map(event => event.status); } catch { /* chips fall back to neutral dots */ }
      replayStatuses = {replay, values};
    }
    return [{label: '起点', status: ''}, ...replay.actions.map((action, index) => ({status: replayStatuses.values[index] || '',
      label: action?.switch_route ? `换用${bundle.routes[action.switch_route]?.label || action.switch_route}` : anyDecision(action?.decision)?.title || action?.decision}))];
  }
  return [{label: '起点', status: ''}, ...passedEvents().map(event => ({status: 'passed',
    label: event.kind === 'switch_route' ? `换用${bundle.routes[event.route]?.label || event.route}` : anyDecision(event.action.decision)?.title || event.action.decision}))];
}

/* Model reasons are free text and often write formulas bare, like a^2-3a-4≥0. Wrap each bare run in $…$ so it
   renders like the authored steps; runs already inside $…$ and plain words are left alone. */
const MATH_RUN = /[-+(A-Za-z0-9Δ≤≥≠<>=∈][A-Za-z0-9Δℝ^_()+\-*/=<>≤≥≠∈.,]*/g;
const MATH_SYMBOLS = {'≤': '\\le ', '≥': '\\ge ', '≠': '\\ne ', 'Δ': '\\Delta ', '∈': '\\in ', 'ℝ': '\\mathbb R', '*': '\\cdot '};
function mathText(text) {
  return String(text ?? '').split(/(\$[^$]+\$)/).map((part, index) => index % 2 ? part : part.replace(MATH_RUN, run => {
    const tail = /[.,]+$/.exec(run)?.[0] || '', body = run.slice(0, run.length - tail.length);
    const letters = /[A-Za-zΔ]/.test(body), operators = /[\^_=<>≤≥≠∈+\-*/()]/.test(body);
    // Variables are single letters; a longer word (AI, real/free) is prose or an option value, not a formula.
    const word = /^[A-Za-z]{2,}$/.test(body) || /[A-Za-z]{3,}/.test(body.replace(/_[A-Za-z]+/g, ''));
    if (!body || word || (!letters && !(operators && /\d/.test(body)))) return run;
    const latex = body.replace(/_([A-Za-z]{2,})/g, '_{\\mathrm{$1}}').replace(/[≤≥≠Δ∈ℝ*]/g, symbol => MATH_SYMBOLS[symbol]).trim();
    return `$${latex}$${tail}`;
  })).join('');
}

function captionFor(shown, view, index) {
  const current = currentDecision(bundle, shown);
  const route = bundle.routes[shown.run?.route];
  const next = current ? `下一步 · ${current.title}` : shown.done ? `${route?.label || '本'}路线完成` : '';
  if (actor === 'replay') {
    if (!replay) return {kicker: 'AI 回放', text: '选择一条回放，看 AI 怎样一步步走过这张图谱。', next: ''};
    const action = replay.actions[index - 1];
    if (!action) return {kicker: 'AI 回放 · 起点', text: `从题目出发：AI 将逐步找出线索、判断题型、选择方法。${replayPlaying ? '' : '点下方 ▶ 开始播放。'}`, next};
    if (action.switch_route) {
      return {kicker: 'AI · 换一种方法', status: 'passed', next,
        text: `再用${bundle.routes[action.switch_route]?.label || action.switch_route}做一遍，和刚才的方法对照。`};
    }
    const decision = anyDecision(action.decision), feedback = shown.lastFeedback || {};
    const verdict = {passed: '通过', wrong: '答错', uncovered: '有效思路 · 未展开'}[feedback.status];
    return {kicker: `AI · ${decision?.title || action.decision}${verdict ? ` · ${verdict}` : ''}`, status: feedback.status,
      text: mathText(action.reason) || (decision ? answerSummary(decision, action.answer) : ''), next: feedback.status === 'passed' ? next : feedback.message || next};
  }
  const prefix = preview ? `回看 T${index} · ` : '';
  if (!preview && shown.lastFeedback && shown.lastFeedback.status !== 'passed') {
    return {kicker: '再想一想', text: shown.lastFeedback.message || '', next, status: shown.lastFeedback.status};
  }
  const log = view.logs?.at(-1);
  const text = typeof log === 'string' ? log : log?.text || '';
  if (!text) return {kicker: `${prefix}起点`, text: '从题目出发：先逐句读懂题目，图谱会随着解题一步步长出来。', next};
  const match = /^([^：]{2,6})：(.+)$/s.exec(text);
  return {kicker: prefix + (match ? match[1] : '这一步'), text: match ? match[2] : text, next, status: 'passed'};
}

function ensureStory() {
  if (story) return story;
  const caption = document.createElement('div');
  caption.className = 'gw-caption';
  caption.toggleAttribute('data-stage-overlay', true);
  caption.innerHTML = '<p class="gw-caption-kicker"></p><p class="gw-caption-text"></p><p class="gw-caption-next"></p>';
  const timeline = document.createElement('div');
  timeline.className = 'gw-timeline';
  timeline.innerHTML = '<button type="button" class="gw-timeline-play" aria-label="播放解题过程">▶</button><ol aria-label="解题时间轴，选择一步回看图谱"></ol>';
  $('#gw-graph').after(caption, timeline);
  timeline.addEventListener('click', event => {
    if (event.target.closest('.gw-timeline-play')) { togglePlay(); return; }
    const button = event.target.closest('[data-time]');
    if (button && !button.disabled) goToTime(Number(button.dataset.time));
  });
  timeline.querySelector('ol').addEventListener('keydown', event => {
    const step = {ArrowLeft: -1, ArrowRight: 1}[event.key];
    const buttons = [...timeline.querySelectorAll('[data-time]:not(:disabled)')];
    const index = buttons.indexOf(document.activeElement);
    if (!step || index < 0 || !buttons[index + step]) return;
    event.preventDefault();
    goToTime(Number(buttons[index + step].dataset.time));
  });
  story = {caption, timeline};
  mountDock();
  return story;
}

/* Logs, basis and calls collapse into one row of chips under the timeline; one opens at a time. */
function mountDock() {
  const panel = $('#gw-graph-panel'), log = panel.querySelector('.gw-log-panel');
  const [used, calls] = panel.querySelectorAll('details.gw-used');
  const dock = document.createElement('div');
  dock.className = 'gw-panel-dock';
  $('#gw-log-history summary').innerHTML = '过程记录 <span id="gw-logs-count">0</span>';
  used.querySelector('summary').innerHTML = '用到的依据 <span id="gw-used-count">0</span>';
  calls.querySelector('summary').innerHTML = '调用记录 <span id="gw-calls-count">0</span>';
  log.before(dock);
  dock.append(log, used, calls);
  dock.addEventListener('toggle', event => {
    if (!event.target.open) return;
    for (const item of dock.querySelectorAll('details[open]')) if (item !== event.target) item.open = false;
  }, true);
  document.addEventListener('pointerdown', event => {
    if (!dock.contains(event.target)) for (const item of dock.querySelectorAll('details[open]')) item.open = false;
  });
  panel.addEventListener('click', event => {
    if (event.target.closest('[data-selection-close]')) $('#gw-selection').hidden = true;
  });
}

/* Over the 3D stage the caption reads as a subtitle; with the SVG graph it sits under the graph. */
function mountCaption() {
  const {caption, timeline} = ensureStory();
  $('#gw-graph-panel').dataset.mode = graph?.stage ? '3d' : '2d';
  if (graph?.stage) graph.stage.append(caption);
  else timeline.before(caption);
}

function updatePlayButton() {
  if (!story) return;
  const playing = actor === 'replay' ? replayPlaying : Boolean(previewTimer);
  const button = story.timeline.querySelector('.gw-timeline-play');
  button.textContent = playing ? '❚❚' : '▶';
  button.setAttribute('aria-label', playing ? '暂停播放' : '播放解题过程');
  button.disabled = actor === 'replay' ? !replay : busy || timelineNow() === 0;
}

function renderStory(shown, view) {
  const {caption, timeline} = ensureStory();
  const now = timelineNow(), index = preview ? preview.index : now;
  const text = captionFor(shown, view, index);
  const key = JSON.stringify(text);
  if (key !== caption.dataset.key) {
    caption.dataset.key = key;
    caption.dataset.status = text.status || '';
    for (const [selector, value] of [['.gw-caption-kicker', text.kicker], ['.gw-caption-text', text.text], ['.gw-caption-next', text.next]]) {
      const label = caption.querySelector(selector);
      label.textContent = value;
      label.removeAttribute('data-math-rendered');
      label.setAttribute('data-math-text', '');
    }
    renderMath(caption);
    if (!reduced.matches) caption.animate([{opacity: 0, transform: 'translateY(12px)'}, {opacity: 1, transform: 'none'}], {duration: 480, easing: 'cubic-bezier(.2,.7,.2,1)'});
  }
  const list = timelinePoints().map((point, time) => ({...point, time, future: time > now}));
  const current = actor === 'student' ? currentDecision(bundle, state) : null;
  if (current) list.push({label: current.title, time: -1, status: 'next', future: true});
  const ol = timeline.querySelector('ol');
  const focused = ol.contains(document.activeElement) ? document.activeElement.dataset.time : null;
  ol.innerHTML = list.map(point => `<li><button type="button" data-time="${point.time}" data-status="${point.status}"${point.time === -1 ? ' disabled' : ''}${point.time === index ? ' aria-current="step"' : ''}${point.future ? ' class="is-future"' : ''}><b>${point.time === -1 ? '下一步' : `T${point.time}`}</b><span data-math-text>${escapeHTML(point.label)}</span></button></li>`).join('');
  renderMath(ol);
  if (focused != null) ol.querySelector(`[data-time="${CSS.escape(focused)}"]`)?.focus({preventScroll: true});
  scrollTimeline();
  updatePlayButton();
}

function scrollTimeline(behavior = reduced.matches ? 'auto' : 'smooth') {
  const ol = story?.timeline.querySelector('ol'), active = ol?.querySelector('[aria-current]');
  if (active) ol.scrollTo({left: active.offsetLeft - (ol.clientWidth - active.offsetWidth) / 2, behavior});
}

function showPreview(index) {
  preview = index >= timelineNow() ? null : {index, state: studentStateAt(index)};
  renderGraph();
}
function stopPreview() { ++previewTicket; clearTimeout(previewTimer); previewTimer = null; }

function goToTime(index) {
  if (actor === 'replay') {
    if (!replay) return;
    stopReplay();
    try { applyReplayPosition(index); } catch (error) { notifyReplay(error.message); }
    story?.timeline.querySelector(`[data-time="${index}"]`)?.focus({preventScroll: true});
    return;
  }
  if (busy) return;
  stopPreview(); showPreview(index);
  story?.timeline.querySelector(`[data-time="${index}"]`)?.focus({preventScroll: true});
}

/* Play the walk from T0: the AI replay advances its own record; a student's own path is replayed on the graph only. */
function togglePlay() {
  if (actor === 'replay') {
    if (!replay) return;
    if (replayPlaying) { stopReplay(); return; }
    if (replayPosition >= replay.actions.length) applyReplayPosition(0);
    playReplay();
    return;
  }
  if (previewTimer) { stopPreview(); updatePlayButton(); return; }
  const end = timelineNow();
  if (!end || busy) return;
  const ticket = ++previewTicket;
  let index = 0;
  const step = () => {
    if (disposed || ticket !== previewTicket) return;
    previewTimer = index >= end ? null : setTimeout(step, reduced.matches ? 900 : 1700);
    showPreview(index++);
  };
  step();
}

/* The step-card numbers, as the cards show them, of the completed steps that lit each node. */
function stepMarks(shown, view) {
  const route = shown.run?.route, numbers = new Map();
  let number = shown.introCompleted?.length || 0, group = null;
  for (const record of shown.run?.completed || []) {
    const next = groupOf(decisionById(record.decision, route));
    if (!next || next !== group) number++;
    group = next;
    numbers.set(record.decision, number);
  }
  return Object.fromEntries(Object.entries(view.stepNodes || {}).map(([id, decisions]) =>
    [id, [...new Set(decisions.map(decision => numbers.get(decision)).filter(Boolean))].sort((left, right) => left - right)]));
}

function renderGraph() {
  const shown = preview?.state || state;
  const view = viewFor(shown);
  view.stepMarks = stepMarks(shown, view);
  renderStory(shown, view);
  graph?.render(view);
  const logs = (view.logs || []).map(log => typeof log === 'string' ? log : log.text || log.message || log.log || '');
  const logHTML = values => values.map(log => `<li data-math-text>${escapeHTML(log)}</li>`).join('');
  $('#gw-logs').innerHTML = logHTML(logs.slice(-3));
  $('#gw-log-history').hidden = !logs.length;
  $('#gw-log-history ol').innerHTML = logHTML(logs);
  $('#gw-logs-count').textContent = String(logs.length);
  $('#gw-calls-count').textContent = String(view.calls?.length || 0);
  const basis = [...new Set((view.usedBasis || []).map(ref => typeof ref === 'string' ? ref : ref.ref || ref.id))].map(describeBasis);
  $('#gw-used-count').textContent = String(basis.length);
  $('#gw-used').innerHTML = basis.length ? basis.map(node => `<li><a href="${nodeHref(node)}" target="_blank" rel="noopener">${escapeHTML(node.label)}</a></li>`).join('') : '<li>确认步骤后，这里显示实际用到的依据。</li>';
  const name = id => graphView.nodes.find(node => node.id === id)?.label || id;
  $('#gw-calls').innerHTML = view.calls?.length ? view.calls.map(call => `<li><span>${escapeHTML(name(call.method))} · ${escapeHTML(callStepTitle(call))}</span><strong>调用 ${escapeHTML(name(call.ref))}</strong></li>`).join('') : '<li>尚未发生方法或技能调用。</li>';
  const current = currentDecision(bundle, state);
  const pathEl = $('#gw-path');
  const pathText = [state.run?.route ? bundle.routes[state.run.route]?.label || '正在恢复解题路线' : '从读题开始', current?.title || (state.done ? '完成本路线' : '')].filter(Boolean).join(' › ');
  // Titles may carry $…$; path chrome must render them (textContent alone shows raw TeX).
  pathEl.removeAttribute('data-math-rendered');
  pathEl.setAttribute('data-math-text', '');
  pathEl.textContent = pathText;
  PracticeMath.render(pathEl, pathText);
  pathEl.dataset.mathRendered = 'true';
  hydrate($('#gw-graph-panel'));
  return view;
}

function optionNavigationHTML(progress) {
  if (!progress.options.length) return '';
  const selected = reviewOption || progress.current;
  const chips = progress.options.map(row => `<button type="button" data-option-review="${escapeHTML(row.option_id)}" ${!row.unlocked || actor !== 'student' ? 'disabled' : ''} aria-current="${row.option_id === selected ? 'step' : 'false'}">${escapeHTML(row.label)}${row.complete ? ' ✓' : ''}</button>`).join('');
  return `<nav class="gw-option-progress" aria-label="逐项判断进度">${chips}<button type="button" data-option-answer ${!progress.finalReady || actor !== 'student' ? 'disabled' : ''} aria-current="${!reviewOption && (progress.finalCurrent || progress.finalPassed) ? 'step' : 'false'}">答题${progress.finalPassed ? ' ✓' : ''}</button></nav>`;
}

function optionHeadingHTML(progress) {
  const row = progress.options.find(item => item.option_id === (reviewOption || progress.current));
  if (!row) return progress.finalReady && !progress.finalPassed
    ? '<p class="gw-option-ready" role="status">各项判断已完成，请按原题要求选择答案。</p>' : '';
  return `<section class="gw-option-heading" data-option-workspace="${escapeHTML(row.option_id)}"><h2>选项 ${escapeHTML(row.label)}${reviewOption ? ' · 只读回看' : ''}</h2>${row.text ? `<p data-math-text>${escapeHTML(row.text)}</p>` : ''}${reviewOption ? '<button type="button" data-option-resume>回到当前进度</button>' : ''}</section>`;
}

function scrollRoot() {
  // Phone AI player scrolls the bottom sheet; otherwise the page scrolls.
  return isPlayer() ? $('.gw-lesson') : (document.scrollingElement || document.documentElement);
}

function readScrollTop() {
  const root = scrollRoot();
  return root === document.scrollingElement || root === document.documentElement ? window.scrollY : root.scrollTop;
}

function writeScrollTop(top) {
  const root = scrollRoot();
  if (root === document.scrollingElement || root === document.documentElement) window.scrollTo(0, top);
  else root.scrollTop = top;
}

function render({focus = false, scroll = focus} = {}) {
  if (disposed) return;
  stopPreview(); preview = null;
  // Replacing #gw-steps often resets the scroll container to the top; keep the
  // viewport first, then ease to the new part / step so the page does not jump.
  const keepY = scroll ? readScrollTop() : null;
  renderProblemContext();
  const open = new Set([...$('#gw-steps').querySelectorAll('details[open]')].map(item => item.dataset.completedDecision));
  const current = currentDecision(bundle, state);
  const optionState = optionProgress(bundle, state);
  if (!optionState.options.some(row => row.option_id === reviewOption && row.complete) || actor !== 'student') reviewOption = null;
  const introCount = state.introCompleted?.length || 0;
  const intro = (state.introCompleted || []).map((record, index) => completedHTML(record, index + 1, 'intro', null)).join('');
  const {units, open: openPart} = stepUnits();
  const visibleOption = reviewOption || optionState.current;
  const completed = units.map((unit, index) => {
    if (optionState.options.length) {
      const context = anyDecision(unit.records[0]?.decision)?.option_context;
      if (!context || context.option_id !== visibleOption) return '';
    }
    return unit.group ? groupCompletedHTML(unit, introCount + index + 1)
      : completedHTML(unit.records[0], introCount + index + 1, activeRunId(), state.run.route);
  }).join('');
  // The AI's cards appear only as it submits: a step it has not reached yet stays a one-line placeholder.
  // A card it is partway through stays open, with that line in place of the next part.
  const shown = !reviewOption && current && (actor === 'student' || submitted?.decision === current.id);
  const partway = !reviewOption && !shown && openPart && current && groupOf(current) === openPart.group;
  const pending = actor === 'replay' && !shown ? replayPendingHTML(current) : '';
  const waiting = !current && !state.done ? waitingHTML(introCount + units.length + 1) : '';
  $('#gw-steps').innerHTML = streamRouteTabsHTML() + optionNavigationHTML(optionState) + intro + optionHeadingHTML(optionState) + completed + (shown || partway ? '<section id="gw-active" class="gw-active" aria-labelledby="gw-current-title"></section>' : reviewOption ? '' : pending || waiting);
  revealGraph();
  const lastCompleted = [...(state.introCompleted || []), ...(state.run?.completed || [])].at(-1)?.decision;
  // Watching the AI reads the whole solution, so every card it has completed stays open.
  $('#gw-steps').querySelectorAll('details[data-completed-decision]').forEach(item => { item.open = actor === 'replay' || Boolean(reviewOption) || open.has(item.dataset.completedDecision) || item.dataset.completedDecision === lastCompleted; });
  mountRetainedMath();
  if (shown) renderInteraction(current);
  else if (partway) renderInteraction(current, {pending});
  const archives = state.archives?.filter(run => run.route) || [];
  $('#gw-completion').innerHTML = state.done ? completionHTML(archives) : '';
  const completionHost = $('#gw-completion [data-stream-completion]');
  if (completionHost) {
    const completion = streamCompletion(state.run.route);
    if (completion) completionHost.append(createRouteCompletion(document, completion, {renderMath: renderStreamMath}).node);
  }
  // Streamed undo only rewinds the current route; with no route answer there is nothing to undo.
  const routeOnly = bundle.stream && state.run?.route && state.introCompleted.length >= bundle.intro.length;
  $('#gw-undo').disabled = actor !== 'student' || busy || optionState.options.length > 0 || !(routeOnly ? state.run.completed.length
    : state.introCompleted?.length || state.run?.completed?.length || state.run?.route);
  const completedCount = introCount + units.length;
  $('#gw-progress').textContent = `${completedCount} 个步骤已确认${actor === 'replay' ? ` · AI 回放 ${replayPosition} / ${replay?.actions.length || 0}` : ''}`;
  hydrate($('#gw-steps')); hydrate($('#gw-completion'));
  disposeMethodConnections();
  disposeMethodConnections = mountMethodConnections($('#gw-steps'));
  // A completion picture replaces its fallback only after every picture has drawn successfully.
  mountCompletedMath();
  renderGraph();
  const target = (openPart && $('#gw-part-title')) || $('#gw-current-title') || $('#gw-completion h2');
  if (target && focus) { target.tabIndex = -1; target.focus({preventScroll: true}); }
  if (scroll) {
    if (keepY != null) writeScrollTop(keepY);
    // Wait a frame so layout after innerHTML + images/math settles, then ease to the anchor.
    requestAnimationFrame(() => {
      if (!disposed) revealStep();
    });
  }
  if (options.stream || options.progressScope) park();
  options.onState?.(walkView());
}

function revealStep(behavior = reduced.matches ? 'auto' : 'smooth') {
  // Prefer the current sub-question after a part confirms; do not jump back to the whole step heading.
  const anchor = $('#gw-part-title') || $('#gw-active') || $('#gw-completion .gw-completion') || [...$('#gw-steps').querySelectorAll('details[data-completed-decision]')].at(-1);
  if (!anchor) return;
  // A column that just narrowed rewraps the bar before its ResizeObserver reports; scroll with the new height.
  measureProblemBar();
  if (!isPlayer()) { anchor.scrollIntoView({block: 'start', behavior}); return; }
  // In the phone player the steps live in a bottom sheet; scroll only the sheet, never the page under the graph.
  const lesson = $('.gw-lesson'), head = lesson.querySelector('.gw-sheet-head')?.offsetHeight || 0;
  lesson.scrollTo({top: lesson.scrollTop + anchor.getBoundingClientRect().top - lesson.getBoundingClientRect().top - head - 8, behavior});
}

/* On a phone, watching the AI is a player: the graph fills the screen and the step cards wait in a bottom sheet.
   Doing it yourself keeps the cards full-width; the live graph shrinks to a floating preview you can expand. */
const isPlayer = () => narrow.matches && actor === 'replay';

function toggleSteps(open = !document.body.classList.contains('gw-sheet-open')) {
  document.body.classList.toggle('gw-sheet-open', open);
  $('#gw-open-steps')?.setAttribute('aria-expanded', String(open));
  if (open) requestAnimationFrame(() => revealStep('auto'));
}

function mountPlayer() {
  if ($('.gw-sheet-head')) { renderProblemText($('.gw-player-problem'), bundle.problem.text); return; }
  const panel = $('#gw-graph-panel'), lesson = $('.gw-lesson');
  const problem = document.createElement('p');
  problem.className = 'gw-player-problem';
  renderProblemText(problem, bundle.problem.text);
  panel.querySelector('.gw-graph-heading').after(problem);
  const exit = document.createElement('button');
  exit.type = 'button'; exit.id = 'gw-player-exit'; exit.textContent = '换我来做';
  exit.addEventListener('click', () => { if (!busy) chooseActor('student'); });
  $('#gw-close-graph').before(exit);
  const steps = document.createElement('button');
  steps.type = 'button'; steps.id = 'gw-open-steps'; steps.textContent = '步骤详情';
  steps.setAttribute('aria-controls', 'gw-steps'); steps.setAttribute('aria-expanded', 'false');
  steps.addEventListener('click', () => toggleSteps());
  panel.querySelector('.gw-panel-dock').prepend(steps);
  const head = document.createElement('div');
  head.className = 'gw-sheet-head';
  head.innerHTML = '<strong>解题步骤</strong><button type="button" data-close-steps>回到图谱</button>';
  head.querySelector('button').addEventListener('click', () => toggleSteps(false));
  lesson.prepend(head);
  document.addEventListener('pointerdown', event => {
    if (document.body.classList.contains('gw-sheet-open') && !lesson.contains(event.target) && !event.target.closest('#gw-open-steps')) toggleSteps(false);
  });
  // Mini preview disables pointer events on the canvas, so a tap lands on the panel itself.
  // Keep target === panel: after × closes the modal, the same click would otherwise bubble and reopen.
  panel.addEventListener('click', event => {
    if (event.target !== panel || !narrow.matches || actor !== 'student' || panel.classList.contains('is-open')) return;
    openGraph();
  });
}

/* A bundle may stop before its routes exist; the next step then shows as a numbered card still on its way. */
function waitingHTML(number) {
  const route = bundle.stream && bundle.routes[state.run?.route];
  const next = route ? route.available === false
    ? {title: '此路线暂不可用', status: '已停止', text: '已计算的步骤保留供检查。'}
    : {title: route.math_complete ? '计算已完成，正在准备练习' : '正在准备这一步的练习', text: '练习准备好后会自动显示。'}
    : bundle.stream && state.run?.route ? {title: '正在恢复解题路线', text: '已保存的练习进度会随步骤一起恢复。'} : bundle.pending;
  if (!next) return '';
  const retained = route?.available === false ? '<div class="gw-stream-retained" data-stream-retained></div>' : '';
  return `<section class="gw-active gw-waiting" aria-labelledby="gw-current-title"><header class="step-heading"><span class="step-number" aria-hidden="true">${number}</span><h2 id="gw-current-title" tabindex="-1" data-math-text>${escapeHTML(next.title)}</h2><span class="status">${escapeHTML(next.status || '准备中')}</span></header>${carryHTML()}<p class="gw-ai-status"><span class="gw-ai-dot" aria-hidden="true"></span><span data-math-text>${escapeHTML(next.text || '')}</span></p>${retained}</section>`;
}

function streamRouteTabsHTML() {
  if (!bundle.stream || state.introCompleted.length !== bundle.intro.length) return '';
  const routes = Object.values(bundle.routes).filter(route => route.route_plan === 'planned');
  if (routes.length < 2) return '';
  return `<nav class="gw-stream-routes" aria-label="解题路线">${routes.map(route =>
    `<button type="button" data-stream-route="${escapeHTML(route.id)}" aria-pressed="${route.id === state.run.route}" ${route.available === false ? 'disabled' : ''}>${escapeHTML(route.label)}</button>`).join('')}</nav>`;
}

const GRAPH_FOLDED_KEY = 'graph-walk:graph-folded';

function graphFolded() {
  try { return localStorage.getItem(GRAPH_FOLDED_KEY) === '1'; } catch { return false; }
}

function syncGraphToggle() {
  const button = $('#gw-graph-toggle');
  if (!button) return;
  const folded = document.body.hasAttribute('data-graph-folded');
  button.textContent = folded ? '展开图谱' : '收起图谱';
  button.setAttribute('aria-expanded', String(!folded));
}

/* On a wide screen the student can fold the graph away; phones keep the modal open/close path. */
function foldGraph(folded) {
  if (narrow.matches) return;
  document.body.toggleAttribute('data-graph-folded', folded);
  try { localStorage.setItem(GRAPH_FOLDED_KEY, folded ? '1' : '0'); } catch { /* private mode */ }
  syncGraphToggle();
}

/* With revealGraph, the graph column waits until the first step is confirmed, then opens beside the steps. */
function revealGraph() {
  if (!options.revealGraph) {
    document.body.dataset.graph = 'shown';
    syncGraphToggle();
    return;
  }
  const shown = (state.introCompleted?.length || 0) > 0 || Boolean(state.run?.route);
  document.body.dataset.graph = shown ? 'shown' : 'hidden';
  syncGraphToggle();
}

function replayPendingHTML(current) {
  if (replayNotice) return `<p class="gw-ai-status" role="status">${escapeHTML(replayNotice.text)}${replayNotice.retry ? ' <button type="button" id="gw-replay-retry">重新读取</button>' : ''}</p>`;
  if (!replay || !current) return '';
  const text = replayPlaying ? `AI 正在看：${current.title}` : `下一步：${current.title}`;
  const control = `<button type="button" data-replay-play aria-label="${replayPlaying ? '暂停播放' : '继续播放'}">${replayPlaying ? '❚❚ 暂停' : '▶ 继续播放'}</button>`;
  return `<p class="gw-ai-status${replayPlaying ? ' is-thinking' : ''}" role="status"><span class="gw-ai-dot" aria-hidden="true"></span>${escapeHTML(text)}${control}</p>`;
}

function notifyReplay(text, retry = false) {
  replayNotice = text ? {text, retry} : null;
  if (actor === 'replay' && bundle) render();
}

function completionHTML(archives) {
  const route = bundle.routes[state.run?.route], {answer, back} = bundle.completion;
  if (bundle.stream) {
    const others = actor === 'student' ? Object.values(bundle.routes).filter(item => item.id !== route?.id && item.available !== false && item.route_plan === 'planned') : [];
    return `<section class="gw-completion"><h2>${escapeHTML(route?.label || '本路线')} · ${actor === 'student' ? '练习已完成' : '回放已结束'}</h2><div data-stream-completion></div><div class="gw-toolbar">${others.map(item => `<button type="button" data-route="${escapeHTML(item.id)}">再用${escapeHTML(item.label)}做一遍</button>`).join('')}${back?.href ? `<a class="gw-completion-back" href="${escapeHTML(back.href)}">${escapeHTML(back.label)}</a>` : ''}</div></section>`;
  }
  const walked = [...new Set([...archives.map(run => run.route), route?.id])].map(id => bundle.routes[id]).filter(Boolean);
  const others = actor === 'student' ? Object.values(bundle.routes).filter(item => item.id !== route?.id) : [];
  const takeaways = walked.length > 1
    ? `<ul class="gw-completion-takeaways">${walked.map(item => `<li data-math-text><b>${escapeHTML(item.label)}</b>　${escapeHTML(item.takeaway)}</li>`).join('')}</ul>`
    : route?.takeaway ? `<p data-math-text>${escapeHTML(route.takeaway)}</p>` : '';
  return `<section class="gw-completion"><h2>${escapeHTML(walked.map(item => item.label).join(' · '))} · 完成</h2>`
    + `<div class="gw-completion-answer" data-math-text>${escapeHTML(answer)}</div>`
    + takeaways
    + `<div class="gw-toolbar">${others.map(item => `<button type="button" data-route="${escapeHTML(item.id)}">再用${escapeHTML(item.label)}做一遍</button>`).join('')}<a class="gw-completion-back" href="${escapeHTML(back.href)}">${escapeHTML(back.label)}</a></div></section>`;
}

function changeDraft(action) {
  const decision = currentDecision(bundle, state);
  if (!decision || actor !== 'student' || busy || reviewOption) return;
  ensureDraft(decision); submitted = null;
  action(decision);
  renderInteraction(decision);
  if (options.stream || options.progressScope) park();
}

function confirmMethodCondition(decision, count) {
  const error = checkMethodAnswers(decision, draft, count);
  if (error) {
    state.lastFeedback = {status: 'wrong', message: error, decision: decision.id};
    submitted = {decision: decision.id, answer: copyAnswer(draft)};
    $('#gw-announcement').textContent = error;
    return;
  }
  draft.confirmed = count; state.lastFeedback = null;
}

function submit() {
  const decision = currentDecision(bundle, state);
  if (!decision || actor !== 'student' || busy || reviewOption || !ready(decision)) return;
  const answer = copyAnswer(draft);
  stopPreview(); preview = null;
  state = submitAnswer(bundle, state, {decision: decision.id, answer}); studentState = state;
  submitted = {decision: decision.id, answer};
  options.onAnswer?.({decision: decision.id, answer: structuredClone(answer)}, walkView());
  const feedback = state.lastFeedback;
  $('#gw-announcement').textContent = feedback?.message || (feedback?.status === 'passed' ? '已确认，进入下一步。' : '请再想一想。');
  if (feedback?.status !== 'passed') { renderInteraction(decision); renderGraph(); if (bundle.stream || options.progressScope) park(); return; }
  busy = true;
  $('#gw-submit').disabled = true;
  renderGraph();
  clearTimeout(commitTimer);
  const ticket = loadTicket;
  commitTimer = setTimeout(() => {
    if (disposed || ticket !== loadTicket) return;
    busy = false; draftKey = ''; render({focus: true});
  }, reduced.matches ? 0 : 350);
}

function stopReplay() {
  clearTimeout(replayTimer); replayTimer = null;
  const was = replayPlaying; replayPlaying = false;
  if (was && actor === 'replay' && replay) render(); else updatePlayButton();
}

function applyReplayPosition(next) {
  replayPosition = next;
  state = replayState(bundle, replay, replayPosition);
  const action = replay.actions[replayPosition - 1];
  submitted = action?.decision ? {decision: action.decision, answer: action.answer} : null;
  draftKey = ''; render({scroll: replayPosition > 0});
  const feedback = state.lastFeedback;
  $('#gw-announcement').textContent = feedback?.message || `回放第 ${replayPosition} 次提交`;
}

function playReplay() {
  if (!replay || replayPosition >= replay.actions.length) return;
  const ticket = replayTicket;
  function advance() {
    if (actor !== 'replay' || ticket !== replayTicket) return;
    replayPlaying = replayPosition + 1 < replay.actions.length;
    try { applyReplayPosition(replayPosition + 1); }
    catch (error) { stopReplay(); notifyReplay(`回放无法继续：${error.message}`); return; }
    replayTimer = replayPlaying ? setTimeout(advance, state.lastFeedback?.status === 'wrong' ? 2200 : 1500) : null;
    updatePlayButton();
  }
  advance();
}

async function readJSON(url) {
  const response = await (options.fetch || fetch)(url, {cache: 'no-store'});
  if (!response.ok) throw new Error(`读取失败（${response.status}）`);
  return response.json();
}

/* The problem restatement is authored once, on the practice page; borrow it so both pages read the same. */
async function loadMeaning() {
  const card = $('.gw-lesson .problem-card');
  if (card.querySelector('.meaning-panel')) return;
  try {
    const response = await fetch(PRACTICE_PAGE, {cache: 'no-store'});
    if (!response.ok) return;
    const panel = new DOMParser().parseFromString(await response.text(), 'text/html').querySelector('.meaning-panel');
    if (!panel || card.querySelector('.meaning-panel')) return;
    card.append(document.importNode(panel, true));
    renderMath(card);
  } catch { /* the original text alone is still complete */ }
}

/* Once the problem card scrolls away, a compact copy pins to the top of the lesson column.
   The dock has no height, so showing it never shifts the steps underneath. */
function mountProblemBar() {
  const lesson = $('.gw-lesson'), card = lesson.querySelector('.problem-card');
  let dock = lesson.querySelector('.gw-problem-dock');
  if (!dock) {
    dock = document.createElement('div');
    dock.className = 'gw-problem-dock';
    dock.setAttribute('aria-hidden', 'true');
    dock.innerHTML = '<div class="gw-problem-bar"><span class="gw-problem-bar-label">原题</span><span class="gw-problem-bar-text"></span></div>';
    lesson.prepend(dock);
    new ResizeObserver(measureProblemBar).observe(dock.firstElementChild);
    new IntersectionObserver(([entry]) => {
      dock.classList.toggle('is-shown', !entry.isIntersecting);
      const button = dock.querySelector('.gw-figures-access');
      dock.setAttribute('aria-hidden', String(entry.isIntersecting || !button));
      if (button) button.tabIndex = entry.isIntersecting ? -1 : 0;
    }).observe(card);
  }
  dock.querySelector('.gw-figures-access')?.remove();
  const pictures = card.querySelector('.qf-panel');
  document.body.classList.toggle('gw-has-question-figures', Boolean(pictures));
  if (pictures) {
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'gw-figures-access'; button.textContent = '查看题图';
    const visible = dock.classList.contains('is-shown');
    button.tabIndex = visible ? 0 : -1;
    dock.setAttribute('aria-hidden', String(!visible));
    button.addEventListener('click', () => {
      pictures.scrollIntoView({behavior: reduced.matches ? 'instant' : 'smooth', block: 'start'});
      pictures.querySelector('button')?.focus({preventScroll: true});
    });
    dock.firstElementChild.append(button);
  } else dock.setAttribute('aria-hidden', 'true');
  renderProblemContext();
}

function renderProblemContext() {
  const context = teachingContext(bundle, state), bar = $('.gw-problem-bar');
  if (!bar) return;
  const label = bar.querySelector('.gw-problem-bar-label'), text = bar.querySelector('.gw-problem-bar-text');
  if (!label || !text) return;
  const signature = JSON.stringify([context.label, context.text]);
  if (bar.dataset.context === signature) return;
  label.textContent = context.label;
  renderProblemText(text, context.text);
  bar.dataset.context = signature;
}

function measureProblemBar() {
  const bar = $('.gw-problem-bar');
  if (bar) $('.gw-lesson').style.setProperty('--gw-bar-h', `${bar.offsetHeight}px`);
}

async function loadReplay(path, autoplay = true) {
  stopReplay();
  const ticket = ++replayTicket;
  replay = null;
  if (!path) return;
  notifyReplay('正在读取 AI 解题记录…');
  try {
    const url = new URL(path, new URL(REPLAY_INDEX_URL, location.origin));
    if (url.origin !== location.origin || !url.pathname.startsWith('/data/graph-walk/replays/')) throw new Error('回放地址不属于本 Demo。');
    const value = await readJSON(url.href);
    if (ticket !== replayTicket || actor !== 'replay') return;
    if (value.bundleVersion !== bundle.bundleVersion || value.problemId !== bundle.problemId) throw new Error('回放与当前题目版本不同，请重新生成同版回放。');
    if (!Array.isArray(value.actions)) throw new Error('回放没有有效的作答记录。');
    replay = value; replayPosition = 0; replayNotice = null;
    applyReplayPosition(0);
    if (autoplay) playReplay();
  } catch (error) {
    if (ticket !== replayTicket) return;
    notifyReplay(error.message, true);
  }
}

/* A mounted bundle brings its replay along; a position saved for this bundle resumes where it stopped. */
function useReplay(value, autoplay) {
  if (!value) { notifyReplay('这一问还没有 AI 解题记录，可以先自己做。'); return; }
  try {
    if (value.bundleVersion !== bundle.bundleVersion || value.problemId !== bundle.problemId) throw new Error('回放与当前题目版本不同。');
    replay = value; replayNotice = null;
    applyReplayPosition(Math.min(replayPosition, replay.actions.length));
    if (autoplay && replayPosition < replay.actions.length) playReplay();
  } catch (error) { replay = null; notifyReplay(error.message); }
}

async function loadReplayIndex(autoplay = true) {
  const ticket = replayTicket;
  notifyReplay('正在读取 AI 解题记录…');
  try {
    const index = await readJSON(REPLAY_INDEX_URL);
    if (ticket !== replayTicket || actor !== 'replay') return;
    replayEntries = index.bundleVersion === bundle.bundleVersion ? index.replays || [] : []; replayIndexLoaded = true;
    if (replayEntries.length) {
      await loadReplay(replayEntries[0].path, autoplay);
    }
    else notifyReplay('当前版本的 AI 解题还没录制，可以先自己做。');
  } catch (error) {
    if (ticket !== replayTicket) return;
    notifyReplay(`暂时不能读取 AI 解题：${error.message}`, true);
  }
}

/* Switching away drops an in-flight read (its ticket goes stale), so coming back must read again
   whatever was missing: the index, or just the replay file the index points to. */
function ensureReplay(autoplay = true) {
  if (options.bundle) { useReplay(options.replay, autoplay); return; }
  if (replayIndexLoaded && replayEntries.length) void loadReplay(replayEntries[0].path, autoplay);
  else void loadReplayIndex(autoplay);
}

/* A route the AI has not shown yet plays from `from` (the start by default); a seen one resumes paused where it stopped. */
function chooseActor(next, {autoplay = true, from = 0} = {}) {
  reviewOption = null;
  rememberStreamDraft(); rememberReplayRoute();
  if (bundle.stream && next === 'replay' && !replayRoute) replayRoute = state?.run?.route || null;
  stopReplay(); ++replayTicket; actor = next;
  if ($('#gw-graph-panel').classList.contains('is-open')) closeGraph();
  document.body.dataset.actor = next; toggleSteps(false);
  $('#gw-student').setAttribute('aria-pressed', String(next === 'student'));
  $('#gw-ai').setAttribute('aria-pressed', String(next === 'replay'));
  draftKey = ''; submitted = null;
  state = next === 'student' ? studentState : createState(bundle);
  if (options.stream && next === 'replay') {
    replay = streamReplay();
    const remembered = replayRoutes[replay.routes[0] || ''];
    replayPosition = Math.min(remembered ?? from, replay.actions.length);
    replayRoute = replay.routes[0] || null;
    state = replayState(bundle, replay, replayPosition);
    render();
    if (remembered == null && autoplay) playReplay();
    return;
  }
  if (next === 'replay' && replay) {
    try { applyReplayPosition(replayPosition); } catch (error) { notifyReplay(error.message); return; }
    if (autoplay) playReplay();
    return;
  }
  render();
  if (next === 'replay') ensureReplay(autoplay);
}

function closeGraph() {
  if (!narrow.matches) {
    foldGraph(true);
    focusBeforeGraph?.focus({preventScroll: true}); focusBeforeGraph = null;
    return;
  }
  $('#gw-graph-panel').classList.remove('is-open');
  $('#gw-graph-panel').removeAttribute('role'); $('#gw-graph-panel').removeAttribute('aria-modal');
  $('#gw-open-graph').setAttribute('aria-expanded', 'false');
  document.body.classList.remove('gw-modal-open');
  $('.gw-lesson').inert = false;
  focusBeforeGraph?.focus({preventScroll: true}); focusBeforeGraph = null;
}

function openGraph() {
  if (!narrow.matches) {
    foldGraph(false);
    requestAnimationFrame(() => { graph?.focus(); scrollTimeline('auto'); });
    return;
  }
  focusBeforeGraph = document.activeElement;
  $('#gw-graph-panel').classList.add('is-open');
  $('#gw-graph-panel').setAttribute('role', 'dialog'); $('#gw-graph-panel').setAttribute('aria-modal', 'true');
  $('#gw-open-graph').setAttribute('aria-expanded', 'true');
  document.body.classList.add('gw-modal-open'); $('.gw-lesson').inert = true;
  $('#gw-close-graph').focus(); requestAnimationFrame(() => { graph?.focus(); scrollTimeline('auto'); });
}

/* A bundle may name its lanes instead of shipping positions; the public lane layout places them here. */
async function withLayout(value) {
  if (value.graph.layout || !value.graph.lanes) return value;
  const {lanesLayout} = await import('../knowledge-next/layout.mjs');
  const defs = value.graph.lanes.map(lane => {
    const ids = new Set(lane.ids || []);
    return {label: lane.label, test: node => ids.has(node.id) || node.kind === lane.kind};
  });
  return {...value, graph: {...value.graph, layout: lanesLayout(value.graph.nodes, value.graph.edges, defs)}};
}

function rememberStreamDraft() {
  if (!bundle?.stream || actor !== 'student' || !state) return;
  const decision = currentDecision(bundle, state);
  if (!decision || draftKey !== decisionKey(decision)) return;
  state = setStreamDraft(bundle, state, {decision: decision.id, answer: structuredClone(draft), selectedSlot,
    submitted: submitted ? structuredClone(submitted) : null});
  studentState = state;
}

function rememberReplayRoute() {
  if (!bundle?.stream || actor !== 'replay' || !replay) return;
  const route = replay.routes?.[0];
  if (route) replayRoute = route;
  replayRoutes[route || ''] = replayPosition;
}

const progressKey = (value, scope = bundleScope) => JSON.stringify([scope || 'demo', value.problemId, value.bundleVersion]);
const storedProgressKey = (value, scope) => scope ? `${scope}walk:${JSON.stringify([value.problemId, value.bundleVersion])}` : null;

function savedProgress(value) {
  const scope = options.progressScope || null;
  let kept = saved.get(progressKey(value, scope));
  const storageKey = storedProgressKey(value, scope);
  if (!kept && storageKey) try { kept = JSON.parse(localStorage.getItem(storageKey) || 'null'); } catch {}
  // The previous stage can be parked just before this run receives its identity.
  return kept || (value.stream && saved.get(progressKey({...value, bundleVersion: value.stream.base_bundle_version}, scope)));
}

const streamCardKey = step => JSON.stringify([step.run_id, step.lesson_version, step.target_ref, step.route_id, step.step_id, step.math_step_sha256]);
const streamQAKey = chunk => JSON.stringify([streamCardKey(chunk), chunk.verified_route_sha256]);

function decisionMathSteps(decision) {
  const route = decision.route_id || state.run?.route;
  return (decision.stream_steps || []).map(ref => bundle.stream.math_steps.find(step =>
    step.target_ref === (decision.target_ref || bundle.stream.target_ref) && step.route_id === route && step.step_id === ref.step_id &&
    step.math_step_sha256 === ref.math_step_sha256)).filter(Boolean);
}

function streamCompletion(route, targetRef = null) {
  const target = targetRef || bundle.stream.target_ref;
  const goal = streamView?.goals?.[target];
  if (goal && (goal.available === false || goal.status === 'conflict' || goal.reason === 'route_consistency_undecidable')) return null;
  const matchesGoal = value => value.target_ref === target && value.route_id === route;
  const current = bundle.routes[route] || (targetRef && Object.values(bundle.routes).find(value =>
    value.goal_completions?.some(matchesGoal)));
  const completion = targetRef && current?.goal_completions
    ? current.goal_completions.find(matchesGoal) : current?.completion;
  if (current?.available === false || !current?.math_complete || completion?.status !== 'verified' ||
      completion.available === false || completion.run_id !== bundle.stream.run_id ||
      completion.lesson_version !== bundle.stream.lesson_version ||
      completion.target_ref !== target || completion.route_id !== route) return null;
  return completion;
}

function availableQA(step) {
  const completion = streamCompletion(step.route_id, step.target_ref);
  return completion?.verified_route_sha256 ? streamQA.get(streamQAKey({...step, verified_route_sha256: completion.verified_route_sha256})) : null;
}

function mountCardQA(card, chunk) {
  const key = streamQAKey(chunk);
  if (card.qaKey !== key) {
    attachMathQA(card, chunk, {renderMath: renderStreamMath});
    card.qaKey = key;
  } else card.qa.hidden = false;
}

function mountCompletionBoards(root) {
  const completed = new Set([...(state.introCompleted || []), ...(state.run?.completed || [])].map(record => record.decision));
  for (const host of root.querySelectorAll('[data-completion-board]')) {
    const id = host.dataset.completionBoard;
    const decision = decisionById(id, state.run?.route);
    if (!completed.has(id) || !decision?.completion_board) continue;
    const board = decision.completion_board;
    // Derivation boards need the DOM builder; lines / inform boards are plain HTML.
    if (board.layout === 'derivation' || Array.isArray(board.items)) {
      host.replaceChildren(createDerivationBoard(document, board));
    } else {
      host.innerHTML = boardHTML(board);
    }
    renderStreamMath(host);
  }
  mountChoicePictures(root);
}

function mountSourceGraphs(root) {
  for (const host of root.querySelectorAll('[data-source-graph]')) {
    if (choicePictureMounts.has(host)) continue;
    const decision = decisionById(host.dataset.sourceGraph, state.run?.route);
    if (!decision?.show_source_graph) continue;
    const readOnly = host.dataset.readonly === 'true';
    const key = `${decision.id}:source`;
    try {
      const dispose = mountQuestionFigures(host, options.figureManifest || bundle.problem.figures, {
        searchId: options.figureSearchId || null, targetRef: decision.target_ref || bundle.stream?.target_ref || null,
        statementOnly: true,
        onReady: loaded => {
          if (readOnly || !host.isConnected) return;
          if (loaded) choicePicturesReady.add(key); else choicePicturesReady.delete(key);
          const submit = $('#gw-submit');
          if (submit && $('#gw-active')?.dataset.decisionId === decision.id) submit.disabled = actor === 'replay' || busy || !ready(decision);
        },
      });
      choicePictureMounts.set(host, dispose);
    } catch {
      host.textContent = '题干原图缺失或未能加载，请重新打开题目。';
      choicePicturesReady.delete(key);
      if (!readOnly && $('#gw-submit')) $('#gw-submit').disabled = true;
    }
  }
}

function mountChoicePictures(root) {
  mountSourceGraphs(root);
  for (const [node, dispose] of choicePictureMounts) if (!node.isConnected) { dispose(); choicePictureMounts.delete(node); }
  for (const host of root.querySelectorAll('[data-figure-choices]')) {
    if (choicePictureMounts.has(host)) continue;
    const decision = decisionById(host.dataset.figureChoices, state.run?.route);
    if (!decision?.figure_choices) continue;
    const readOnly = host.dataset.readonly === 'true';
    try {
      const dispose = mountFigureChoices(host, options.figureManifest || bundle.problem.figures, decision, {
        searchId: options.figureSearchId || null, targetRef: decision.target_ref || bundle.stream?.target_ref || null,
        selected: readOnly ? host.dataset.selected : draft, readOnly,
        onReady: loaded => {
          if (readOnly || !host.isConnected) return;
          if (loaded) choicePicturesReady.add(decision.id); else choicePicturesReady.delete(decision.id);
          const submit = $('#gw-submit');
          if (submit && $('#gw-active')?.dataset.decisionId === decision.id) submit.disabled = actor === 'replay' || busy || !ready(decision);
        },
      });
      choicePictureMounts.set(host, dispose);
    } catch {
      host.textContent = '原选项图片不完整或与当前题目不匹配，请重新打开题目。';
      choicePicturesReady.delete(decision.id);
      if (!readOnly && $('#gw-submit')) $('#gw-submit').disabled = true;
    }
  }
}

function mountCompletedMath() {
  mountCompletionBoards($('#gw-steps'));
  visibleStreamCards = new Set();
  if (!bundle.stream) return;
  for (const host of $('#gw-steps').querySelectorAll('[data-stream-completed]')) {
    const decision = decisionById(host.dataset.streamCompleted, state.run.route);
    if (!decision?.stream_last_part) continue;
    const parentTitle = stepTitle(decision);
    const pictured = groupOf(decision) ? groupParts(decision) : [decision];
    const expectedGraphs = pictured.reduce((count, part) => count + Number(Boolean(part.completion_graph)) +
      (Array.isArray(part.completion_graphs) ? part.completion_graphs.length : 0), 0);
    const figures = [...(host.closest('.gw-completed-body')?.querySelectorAll('.gw-completion-graph') || [])];
    const externalConclusion = expectedGraphs > 0 && figures.length === expectedGraphs && figures.every(figure =>
      [...figure.querySelectorAll('[data-graph-rendered]')].some(plot => plot.dataset.graphRendered === 'true' && plot.querySelector('svg')));
    const folded = new Set(decision.stream_folded || []);
    let fold = null;
    for (const step of decisionMathSteps(decision)) {
      const key = streamCardKey(step);
      let card = streamCards.get(key);
      if (!card) { card = createMathCard(document, step, {renderMath: renderStreamMath}); streamCards.set(key, card); }
      setMathCardLayout(card, {embedded: true, parentTitle: folded.has(step.step_id) ? '' : parentTitle,
        externalConclusion: !folded.has(step.step_id) && externalConclusion});
      if (decision.completion_board && card.conclusion) card.conclusion.hidden = true;
      const qa = availableQA(step);
      if (qa) mountCardQA(card, qa);
      else card.qa.hidden = true;
      if (folded.has(step.step_id)) {
        if (!fold) {
          const summary = document.createElement('summary');
          summary.textContent = '各情况的推导';
          fold = document.createElement('details');
          fold.className = 'gw-folded';
          fold.append(summary);
          host.append(fold);
        }
        fold.append(card.node);
      } else host.append(card.node);
      visibleStreamCards.add(key);
    }
  }
}

/* A stopped route ends practice, but its committed cards not yet shown stay readable for checking. */
function mountRetainedMath() {
  const host = bundle.stream && $('#gw-steps').querySelector('[data-stream-retained]');
  if (!host) return;
  const route = state.run.route, shown = new Set();
  for (const record of state.run.completed) {
    const decision = decisionById(record.decision, route);
    if (decision?.stream_last_part) for (const ref of decision.stream_steps) shown.add(ref.step_id);
  }
  const retained = bundle.stream.math_steps.filter(step => (bundle.stream.target_refs || [bundle.stream.target_ref]).includes(step.target_ref) &&
    step.route_id === route && !shown.has(step.step_id)).sort((left, right) => left.ordinal - right.ordinal);
  for (const step of retained) {
    const key = streamCardKey(step);
    let card = streamCards.get(key);
    if (!card) { card = createMathCard(document, step, {renderMath: renderStreamMath}); streamCards.set(key, card); }
    setMathCardLayout(card);
    card.qa.hidden = true;
    host.append(card.node);
  }
}

function park() {
  if (disposed || !bundle) return;
  rememberStreamDraft(); rememberReplayRoute();
  const previous = saved.get(progressKey(bundle));
  const draftNow = actor === 'student' && draftKey ? {key: draftKey, draft: structuredClone(draft), submitted, selectedSlot} : keptDraft;
  const value = {bundleVersion: bundle.bundleVersion, studentState, replayPosition, replayRoute, replayRoutes, actor,
    draft: draftNow ?? (previous?.bundleVersion === bundle.bundleVersion ? previous.draft : null)};
  saved.set(progressKey(bundle), value);
  const storageKey = storedProgressKey(bundle, bundleScope);
  if (storageKey) try { localStorage.setItem(storageKey, JSON.stringify(value)); } catch {}
}

async function load({replayFollowing} = {}) {
  const ticket = ++loadTicket;
  const config = options, selection = streamView;
  ++graphTicket;
  // A stage-two replay can already be playing when the stream identity arrives.
  // Capture its intent before stopping the old timer for the bundle migration.
  const replayWasFollowing = replayFollowing ?? (actor === 'replay' && Boolean(replayPlaying ||
    replay && replayPosition === replay.actions.length));
  stopReplay(); ++replayTicket; clearTimeout(commitTimer); busy = false;
  park();
  $('#gw-loading').hidden = false; $('#gw-error').hidden = true;
  try {
    let value = config.bundle || await readJSON(config.bundleUrl);
    if (ticket !== loadTicket) return;
    if (config.stream) {
      publicGraph ||= await readJSON('/knowledge/graph.json');
      if (ticket !== loadTicket) return;
      value = extendStreamBundle(value, selection || config.stream, config.stream.target_ref, publicGraph);
    }
    value = await withLayout(value);
    if (ticket !== loadTicket) return;
    if (!value.bundleVersion || !value.templates || !value.intro?.length || !value.routes || !value.graph) throw new Error('Demo 快照不完整，请重新构建后重试。');
    bundle = value; bundleScope = options.progressScope || null; graphView = bundle.graph;
    const kept = savedProgress(bundle);
    // Stage two may be readable a moment before stage three publishes its run identity.
    // Carry those same-version D1/D2 answers into that run, never across an old run.
    let resume = kept?.bundleVersion === bundle.bundleVersion, restoredState = kept?.studentState, migrated = false;
    if (!resume && options.stream && kept?.bundleVersion === options.bundle?.bundleVersion) try {
      restoredState = migrateStageTwoState(options.bundle, bundle, kept.studentState); resume = true; migrated = true;
    } catch { /* Unrelated or invalid progress starts this run at D1. */ }
    studentState = state = resume ? bundle.stream ? refreshStreamState(bundle, restoredState) : restoredState : createState(bundle);
    replay = null; replayPosition = resume ? kept.replayPosition : 0; replayNotice = null;
    replayRoute = resume ? kept.replayRoute || null : null;
    replayRoutes = resume ? structuredClone(kept.replayRoutes || {}) : {};
    keptDraft = resume ? kept.draft : null;
    draftKey = ''; submitted = null;
    if ($('#gw-problem')) renderProblemText($('#gw-problem'), bundle.problem.text);
    disposeProblemFigures();
    $('#gw-question-figures')?.remove();
    if (bundle.problem.figures) {
      const host = document.createElement('div'); host.id = 'gw-question-figures';
      $('.gw-lesson .problem-card').append(host);
      // Static bundles can only reference curated public assets. Private photos
      // are mounted by their authenticated host and never copied into a bundle.
      disposeProblemFigures = mountQuestionFigures(host, bundle.problem.figures, {targetRef: config.stream?.target_ref || null});
    }
    mountProblemBar();
    if (options.practicePage) void loadMeaning();
    if ($('#gw-version')) $('#gw-version').textContent = `版本 ${bundle.bundleVersion.slice(0, 12)} · 公共图谱 ${bundle.graphVersion.slice(0, 12)}`;
    $('#gw-ready').hidden = false;
    if (!await installGraph(() => ticket === loadTicket)) return;
    mountCaption(); mountPlayer();
    // A phone opens on the AI player, paused at the start; the visitor presses ▶ to watch.
    if ((options.stream || options.progressScope) && kept?.actor) chooseActor(kept.actor, {autoplay: !migrated || replayWasFollowing,
      from: migrated ? replayPosition : 0});
    else if (options.actor) chooseActor(options.actor);
    else if (narrow.matches) chooseActor('replay', {autoplay: false}); else render();
  } catch (error) {
    if (ticket !== loadTicket) return;
    $('#gw-error p').textContent = `暂时无法打开演示：${error.message}`;
    $('#gw-error').hidden = false;
  } finally { if (ticket === loadTicket) $('#gw-loading').hidden = true; }
}

function bind() {
  $('#gw-ai').textContent = '看 AI 解题';
  document.body.dataset.actor = actor;
  $('#gw-open-graph span:last-child').textContent = '展开图谱 ⤢';
  $('#gw-reset').innerHTML = '<span aria-hidden="true">↺</span> 重新练习';
  if (!$('#gw-graph-toggle')) {
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.id = 'gw-graph-toggle';
    toggle.setAttribute('aria-controls', 'gw-graph-panel');
    toggle.setAttribute('aria-expanded', 'true');
    toggle.textContent = '收起图谱';
    $('#gw-reset').before(toggle);
  }
  foldGraph(graphFolded());
  $('#gw-retry').addEventListener('click', load);
  $('#gw-steps').addEventListener('click', event => {
    const button = event.target.closest('button');
    if (button?.id === 'gw-replay-retry') { ensureReplay(); return; }
    if (button?.hasAttribute('data-replay-play')) { togglePlay(); return; }
    if (button?.dataset.streamRoute && !busy) { chooseStreamRoute(button.dataset.streamRoute); return; }
    if (!button || actor !== 'student' || busy) return;
    if (button.hasAttribute('data-option-review')) {
      const progress = optionProgress(bundle, state), row = progress.options.find(item => item.option_id === button.dataset.optionReview);
      if (row?.unlocked && (row.complete || row.current)) {
        reviewOption = row.current ? null : row.option_id;
        render({scroll: false});
      }
      return;
    }
    if (button.hasAttribute('data-option-resume') || button.hasAttribute('data-option-answer')) {
      if (button.hasAttribute('data-option-resume') || optionProgress(bundle, state).finalReady) {
        reviewOption = null; render({scroll: false});
      }
      return;
    }
    if (button.id === 'gw-submit') { submit(); return; }
    const focus = button.dataset.methodLink != null ? `[data-method-link="${CSS.escape(button.dataset.methodLink)}"]`
      : button.dataset.cardMethod != null ? `[data-card-method="${CSS.escape(button.dataset.cardMethod)}"]`
      : button.dataset.choice != null ? `[data-choice][data-value="${CSS.escape(button.dataset.value)}"]`
      : button.dataset.pairAnswer != null ? `[data-pair-answer="${button.dataset.pairAnswer}"][data-value="${CSS.escape(button.dataset.value)}"]`
      : button.dataset.multi != null ? `[data-multi="${CSS.escape(button.dataset.multi)}"]`
        : button.dataset.planeCell != null ? `[data-plane-cell="${CSS.escape(button.dataset.planeCell)}"]`
        : button.dataset.gridCell != null ? `[data-grid-cell="${CSS.escape(button.dataset.gridCell)}"]`
          : button.dataset.planeMethod != null ? `[data-plane-method="${CSS.escape(button.dataset.planeMethod)}"]` : null;
    if (button.hasAttribute('data-method-link')) changeDraft(() => {
      draft.checks[0] = button.dataset.methodLink; state.lastFeedback = null;
    });
    else if (button.hasAttribute('data-method-check')) changeDraft(() => {
      const i = Number(button.dataset.methodCheck); draft.checks[i] = button.dataset.value; draft.confirmed = i; draft.method = ''; state.lastFeedback = null;
    });
    else if (button.hasAttribute('data-method-confirm')) changeDraft(decision => confirmMethodCondition(decision, Number(button.dataset.methodConfirm) + 1));
    else if (button.hasAttribute('data-card-method')) changeDraft(decision => {
      if (decision.interaction.layout === 'connections' && decision.interaction.connections) draft = connectedMethodAnswer(decision, button.dataset.cardMethod);
      else draft.method = button.dataset.cardMethod;
    });
    else if (button.hasAttribute('data-choice')) changeDraft(() => { draft = button.dataset.value; });
    else if (button.hasAttribute('data-pair-answer')) changeDraft(() => { draft[Number(button.dataset.pairAnswer)] = button.dataset.value; });
    else if (button.hasAttribute('data-multi')) changeDraft(() => { const value = button.dataset.multi; draft = draft.includes(value) ? draft.filter(item => item !== value) : [...draft, value]; });
    else if (button.hasAttribute('data-plane-cell')) changeDraft(decision => {
      const [x, y] = button.dataset.planeCell.split('|');
      const kept = decision.interaction.methods.find(method => method.value === draft[2]);
      draft = [x, y, kept && covers(kept, x, y) ? draft[2] : ''];
    });
    else if (button.hasAttribute('data-plane-method')) changeDraft(() => { draft[2] = button.dataset.planeMethod; });
    else if (button.hasAttribute('data-grid-cell')) changeDraft(() => { draft = button.dataset.gridCell.split('|'); });
    else if (button.hasAttribute('data-slot')) changeDraft(() => { selectedSlot = Number(button.dataset.slot); });
    else if (button.hasAttribute('data-token')) {
      const slot = selectedSlot;
      if (slot != null) changeDraft(() => { draft[slot] = button.dataset.token; selectedSlot = null; });
      $('#gw-active')?.querySelector(`[data-slot="${slot}"]`)?.focus({preventScroll: true});
    } else if (button.classList.contains('gw-token-close')) changeDraft(() => { selectedSlot = null; });
    if (focus) $('#gw-active')?.querySelector(focus)?.focus({preventScroll: true});
    else if (button.hasAttribute('data-slot')) $('#gw-active [data-token]')?.focus({preventScroll: true});
  });
  $('#gw-completion').addEventListener('click', event => {
    const button = event.target.closest('[data-route]');
    if (!button || actor !== 'student' || busy) return;
    rememberStreamDraft();
    state = switchRoute(bundle, state, button.dataset.route); studentState = state;
    options.onRouteChange?.(walkView());
    draftKey = ''; submitted = null; render({focus: true});
  });
  $('#gw-undo').addEventListener('click', () => {
    if (busy || actor !== 'student' || hasOptionWorkspaces(bundle, state)) return;
    state = undo(bundle, state); studentState = state; draftKey = ''; submitted = null; render({focus: true});
  });
  $('#gw-reset').addEventListener('click', () => {
    clearTimeout(commitTimer); busy = false; stopReplay(); ++replayTicket;
    // Drop any parked unsubmitted answer; otherwise the next student render restores it.
    keptDraft = null; draftKey = ''; submitted = null; reviewOption = null;
    studentState = createState(bundle); state = studentState; replayPosition = 0; replayRoutes = {}; replayRoute = null;
    const kept = saved.get(progressKey(bundle));
    if (kept) saved.set(progressKey(bundle), {...kept, studentState, replayPosition: 0, draft: null});
    options.onReset?.();
    chooseActor('student');
  });
  $('#gw-student').addEventListener('click', () => { if (!busy) chooseActor('student'); });
  $('#gw-ai').addEventListener('click', () => { if (!busy) chooseActor('replay'); });
  $('#gw-open-graph').addEventListener('click', openGraph);
  $('#gw-close-graph').addEventListener('click', event => { event.stopPropagation(); closeGraph(); });
  $('#gw-graph-toggle').addEventListener('click', () => {
    if (narrow.matches) return;
    foldGraph(!document.body.hasAttribute('data-graph-folded'));
  });
  narrow.addEventListener('change', () => {
    if (narrow.matches) {
      document.body.removeAttribute('data-graph-folded');
      syncGraphToggle();
      return;
    }
    // Leaving the phone modal must not fold the desktop column.
    $('#gw-graph-panel').classList.remove('is-open');
    $('#gw-graph-panel').removeAttribute('role');
    $('#gw-graph-panel').removeAttribute('aria-modal');
    $('#gw-open-graph').setAttribute('aria-expanded', 'false');
    document.body.classList.remove('gw-modal-open');
    $('.gw-lesson').inert = false;
    toggleSteps(false);
  });
  document.addEventListener('keydown', event => {
    const modal = $('#gw-graph-panel').classList.contains('is-open');
    const desktop = !narrow.matches && document.body.dataset.graph !== 'hidden'
      && !document.body.hasAttribute('data-graph-folded');
    if (!modal && !desktop) return;
    if (event.key === 'Escape') { event.preventDefault(); closeGraph(); }
    if (!modal) return;
    if (event.key !== 'Tab') return;
    const focusable = [...$('#gw-graph-panel').querySelectorAll('button,a[href],summary,[tabindex="0"]')].filter(node => node.getClientRects().length);
    const first = focusable[0], last = focusable.at(-1);
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  });
}

if (document.readyState === 'loading') await new Promise(resolve => document.addEventListener('DOMContentLoaded', resolve, {once: true}));

/* Mount (or switch to) a bundle on a page that hosts the walk markup. Each bundle keeps its own progress. */
export async function mountWalk(next) {
  const ticket = ++mountTicket;
  const replayFollowing = actor === 'replay' && Boolean(replayPlaying || replay && replayPosition === replay.actions.length);
  streamParked = true; ++streamUpdateTicket;
  ++loadTicket; ++graphTicket; ++replayTicket;
  stopReplay(); stopPreview(); clearTimeout(commitTimer); busy = false;
  park();
  disposed = false;
  graph?.destroy(); graph = null;
  const scopeChanged = Object.hasOwn(next, 'progressScope') && next.progressScope !== options.progressScope;
  const newRun = scopeChanged || next.stream?.run_id !== options.stream?.run_id || next.stream?.lesson_version !== options.stream?.lesson_version;
  if (newRun || next.stream?.target_ref !== options.stream?.target_ref) {
    if (newRun) {
      streamQA.clear(); streamCards.clear(); axisPositions.clear(); visibleStreamCards = new Set();
    }
    streamView = next.stream || null; ++streamUpdateTicket;
  }
  options = {...options, ...next};
  if (!bound) { bind(); bound = true; }
  await streamUpdateQueue.catch(() => {});
  if (ticket !== mountTicket) return;
  streamParked = false;
  await load({replayFollowing});
}

/* Leave the walk without a bundle, e.g. for a part with nothing to walk; its progress stays parked. */
export function parkWalk() {
  streamParked = true; ++streamUpdateTicket; ++mountTicket;
  ++graphTicket;
  stopReplay(); ++replayTicket; ++loadTicket; clearTimeout(commitTimer); busy = false;
  park();
}

export function disposeWalk() {
  disposed = true;
  formulaFitter?.dispose(); formulaFitter = null;
  disposeMethodConnections();
  disposeProblemFigures();
  for (const dispose of choicePictureMounts.values()) dispose();
  choicePictureMounts.clear(); choicePicturesReady.clear();
  document.body.classList.remove('gw-has-question-figures');
  streamParked = true;
  ++graphTicket;
  ++streamUpdateTicket; ++mountTicket; ++loadTicket; ++replayTicket;
  stopReplay(); stopPreview(); clearTimeout(commitTimer);
  graph?.destroy(); graph = null;
  saved.clear(); streamQA.clear(); streamCards.clear(); axisPositions.clear(); visibleStreamCards.clear();
  bundle = null; bundleScope = null; streamView = null; studentState = null; state = null;
  keptDraft = null; draft = null; submitted = null; replay = null; busy = false;
  draftKey = ''; selectedSlot = null; preview = null; story = null; replayRoutes = {}; replayRoute = null;
  options = {...options, bundle: null, replay: null, stream: null, onState: null, onAnswer: null, onReset: null, progressScope: null, fetch: undefined, figureManifest: null, figureSearchId: null};
}

/* The actor the walk currently shows, so a host can carry it across bundles. */
export const walkActor = () => actor;

function streamReplay() {
  return buildStreamReplay(bundle, {actions: options.replay?.actions,
    replayRoute, currentRoute: state?.run?.route});
}

export function walkView() {
  return {actor, route: state?.run?.route || null, target_ref: options.stream?.target_ref,
    practice_answers: [...(state?.introCompleted || []), ...(state?.run?.completed || [])]
      .map(entry => ({decision: entry.decision, answer: structuredClone(entry.answer)})),
    bundle_version: bundle?.bundleVersion, done: Boolean(state?.done),
    problem_id: bundle?.problemId, teaching_context: teachingContext(bundle, state),
    base_bundle_version: bundle?.stream?.base_bundle_version || bundle?.bundleVersion,
    intro_complete: Boolean(bundle?.intro.some(item => item.id === 'D3') && state?.introCompleted.length === bundle.intro.length),
    intro_completed: state?.introCompleted.map(item => item.decision) || []};
}

/** Restore only server-confirmed student answers; AI playback keeps its own position. */
export function restoreWalkProgress(history) {
  if (!bundle || !bundle.routes[history.route_id]) return false;
  const answers = new Map((history.steps || []).filter(step => step.passed).map(step => [step.step_id, step.answer]));
  let restored = createState(bundle);
  for (let decision = currentDecision(bundle, restored); decision && answers.has(decision.id); decision = currentDecision(bundle, restored)) {
    const value = answers.get(decision.id);
    if (!value || !Object.hasOwn(value, 'value')) return false;
    const next = submitAnswer(bundle, restored, {decision: decision.id, answer: value.value});
    if (next.lastFeedback?.status !== 'passed') return false;
    restored = next;
  }
  studentState = restored;
  if (actor === 'student') { state = studentState; keptDraft = null; draftKey = ''; submitted = null; render(); }
  else park();
  return true;
}

/** Extend the same decision engine; existing answers/draft retain their identity. */
export function updateStreamSelection(view) {
  const ticket = mountTicket;
  // HTTP and WebSocket may deliver independently; serialize graph replacement.
  const update = streamUpdateQueue.catch(() => {}).then(() => {
    if (ticket === mountTicket) return applyStreamSelection(view);
  });
  streamUpdateQueue = update;
  return update;
}

async function applyStreamSelection(view) {
  if (streamParked || !options.stream || view.run_id !== options.stream.run_id || view.lesson_version !== options.stream.lesson_version || !bundle) return;
  rememberStreamDraft();
  const signature = graph => JSON.stringify([graph.nodes, graph.edges, graph.lanes]);
  const decisionSignature = value => JSON.stringify([value.intro, Object.entries(value.routes).map(([id, route]) =>
    [id, route.steps, route.status, route.available, route.math_complete, route.interactions_complete, route.pending_count, route.completion]),
    value.stream?.interaction_states]);
  const ticket = ++streamUpdateTicket, previousGraph = signature(bundle.graph);
  const previousDecisionSignature = JSON.stringify([decisionSignature(bundle), streamView?.goals]);
  const next = extendStreamBundle(bundle, view, options.stream.target_ref, publicGraph);
  const decisionsChanged = JSON.stringify([decisionSignature(next), view.goals]) !== previousDecisionSignature;
  if (signature(next.graph) !== previousGraph) {
    delete next.graph.layout;
    const laidOut = await withLayout(next);
    if (ticket !== streamUpdateTicket) return;
    bundle = laidOut; graphView = bundle.graph;
    if (!await installGraph(() => ticket === streamUpdateTicket)) return;
    mountCaption();
  } else bundle = {...bundle, ...next, graph: bundle.graph};
  streamView = view;
  studentState = refreshStreamState(bundle, studentState);
  if (actor === 'replay') {
    const followedEnd = replay && replayPosition === replay.actions.length;
    const following = followedEnd || replayPlaying;
    const nextReplay = streamReplay();
    const samePath = replay && JSON.stringify(replay.routes) === JSON.stringify(nextReplay.routes) &&
      replay.actions.every((action, index) => JSON.stringify(action) === JSON.stringify(nextReplay.actions[index]));
    if (replay && !samePath) {
      rememberReplayRoute();
      // A withdrawn route can shorten or replace the replay. Invalidate even
      // already queued callbacks before they advance the replacement's cursor.
      clearTimeout(replayTimer); replayTimer = null; replayPlaying = false; ++replayTicket;
    }
    replay = nextReplay;
    replayPosition = followedEnd && !samePath ? replay.actions.length : Math.min(replayPosition, replay.actions.length);
    state = replayState(bundle, replay, replayPosition);
    if (samePath && following && !replayTimer) playReplay();
  } else state = studentState;
  if (decisionsChanged) render();
  else { renderGraph(); options.onState?.(walkView()); }
}

export function chooseStreamRoute(route) {
  if (!bundle?.stream || !walkView().intro_complete || !bundle.routes[route]) return;
  rememberStreamDraft(); rememberReplayRoute();
  stopReplay(); ++replayTicket;
  state = switchRoute(bundle, state, route);
  if (actor === 'student') { studentState = state; options.onRouteChange?.(walkView()); }
  else {
    replayRoute = route; replay = streamReplay();
    replayPosition = Math.min(replayRoutes[route] ?? replay.actions.length, replay.actions.length);
    state = replayState(bundle, replay, replayPosition);
  }
  draftKey = ''; submitted = null;
  render();
}

/** QA never advances practice or replaces a mathematical card. */
export function attachStreamQA(chunk) {
  if (streamParked || !bundle?.stream || chunk.run_id !== bundle.stream.run_id ||
      chunk.lesson_version !== bundle.stream.lesson_version ||
      !(bundle.stream.target_refs || [bundle.stream.target_ref]).includes(chunk.target_ref)) return;
  const step = bundle.stream.math_steps.find(value => streamCardKey(value) === streamCardKey(chunk));
  if (!step) return;
  const key = streamQAKey(chunk), previous = streamQA.get(key);
  if (previous && JSON.stringify(previous) !== JSON.stringify(chunk)) throw new Error('stream.immutable_qa');
  const cardKey = streamCardKey(chunk), card = streamCards.get(cardKey);
  const completion = streamCompletion(chunk.route_id, chunk.target_ref);
  if (visibleStreamCards.has(cardKey) && card && completion?.verified_route_sha256 === chunk.verified_route_sha256) {
    mountCardQA(card, chunk);
  }
  if (!previous) streamQA.set(key, structuredClone(chunk));
}

/** The same safe text/LaTeX renderer used by authored walk steps. */
export function renderStreamMath(root) {
  for (const node of root.querySelectorAll('[data-math-formula]:not([data-math-rendered])')) {
    if (node.classList.contains('gw-derivation-formula')) {
      renderFittedFormula(node, node.textContent, (line, value) => PracticeMath.render(line, value));
      formulaFitter ||= createFormulaFitter(document);
    } else PracticeMath.render(node, `$${node.textContent}$`);
    node.dataset.mathRendered = 'true';
  }
  for (const node of root.querySelectorAll('.stage-three-qa p')) node.dataset.mathText = 'true';
  renderMath(root);
  formulaFitter?.refresh();
}

if (document.body.dataset.walk !== 'mount') await mountWalk({});
