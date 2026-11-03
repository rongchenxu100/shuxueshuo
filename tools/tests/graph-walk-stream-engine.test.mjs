import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import * as stateAPI from '../../site/assets/graph-walk/walk-state.mjs';
import * as mathDOM from '../../site/assets/graph-walk/stream-math-dom.mjs';
import {buildStreamReplay} from '../../site/assets/graph-walk/walk-replay.mjs';
import * as optionWorkspace from '../../site/assets/graph-walk/option-workspace.mjs';
import * as methodCards from '../../site/assets/graph-walk/method-cards.mjs';
import {mountMethodConnections, connectedMethodAnswer} from '../../site/assets/graph-walk/method-connections.mjs';
import {formulaAnswerHTML} from '../../site/assets/graph-walk/formula-answer.mjs';
import {createFormulaFitter, renderFittedFormula} from '../../site/assets/graph-walk/formula-fit.mjs';

const source = fs.readFileSync(new URL('../../site/assets/graph-walk/walk.mjs', import.meta.url), 'utf8');
const components = fs.readFileSync(new URL('../../site/assets/practice/components.js', import.meta.url), 'utf8');
const read = path => JSON.parse(fs.readFileSync(new URL(path, import.meta.url), 'utf8'));
const base = read('../../site/lab/search/demo-lesson-q01.json').goals[0].walk.bundle;
const graph = read('../../site/knowledge/graph.json');
const d3 = read('../../site/data/graph-walk/quadratic-always-q01.source.json').intro.find(item => item.id === 'D3');
const identity = {run_id: 'engine-run', lesson_version: 'engine-lesson', stream_id: 'engine-run'};
const target = '/root/goals/0';
const routes = ['discriminant', 'extremum'];
const card = (ordinal, route = routes[0]) => ({...identity, target_ref: target, route_id: route,
  step_id: `math-${ordinal}`, ordinal, math_step_sha256: `${route}-${ordinal}-hash`, local_check: 'passed',
  title: `数学步骤 ${ordinal}`, before: [{latex: `before-${ordinal}`}], after: [{latex: `secret-after-${ordinal}`}],
  explanation: `secret-explanation-${ordinal}`, source_refs: [], used_basis: []});
const part = (id, type = 'choice') => ({id, title: id, question: `请判断 ${id}`,
  interaction: type === 'fill' ? {type, slot_labels: ['第一项'], terms: ['yes', 'no']}
    : {type, field: id, options: [{value: 'yes', label: '成立'}, {value: 'no', label: '不成立'}]},
  expected_answer: type === 'fill' ? {terms: ['yes']} : {one_of: ['yes']}});
function fixture({parts = [part('first'), part('last')], merged = false, readonly = false, folded = false} = {}) {
  const math_steps = routes.flatMap(route => Array.from({length: merged || folded ? 2 : 1}, (_, i) => card(i + 1, route)));
  const refs = route => math_steps.filter(step => step.route_id === route).map(({step_id, math_step_sha256}) => ({step_id, math_step_sha256}));
  const interactions = folded
    ? routes.flatMap(route => [
      {...identity, target_ref: target, route_id: route, interaction_id: `${route}-folded`, status: 'readonly',
        reason: 'folded', steps: refs(route).slice(0, 1), parts: []},
      {...identity, target_ref: target, route_id: route, interaction_id: `${route}-interaction`, status: 'interactive',
        steps: refs(route).slice(1), parts: structuredClone(parts)}])
    : routes.map(route => ({...identity, target_ref: target, route_id: route,
      interaction_id: `${route}-interaction`, status: readonly ? 'readonly' : 'interactive',
      steps: refs(route), parts: readonly ? [] : structuredClone(parts)}));
  const view = {...identity, goals: {}, math_steps, interaction_protocol: 'graph-step-interaction/v1',
    selection_chunks: [{target_ref: target, kind: 'D3', chunk: d3}, {target_ref: target, kind: 'D4', chunk: {id: 'D4', title: '选路线', options: [
      {branch: 'discriminant', route_id: routes[0], method: 'method-discriminant', route_plan: 'planned'},
      {branch: 'separation', route_id: routes[1], method: 'method-separation', route_plan: 'planned'},
    ]}}], interactions, interaction_states: interactions.flatMap(chunk => chunk.steps.map(step => ({...step,
      target_ref: target, route_id: chunk.route_id, interaction_id: chunk.interaction_id, status: chunk.status}))),
    completions: routes.map(route => ({identity: [target, route], status: 'verified', available: true,
      verified_route_sha256: `${route}-verified`, answer: {kind: 'find_range', status: 'set', set: {latex: '[0,+\\infty)'}}})),
  };
  const bundle = stateAPI.extendStreamBundle(base, view, target, graph);
  let state = stateAPI.createState(bundle);
  for (const decision of bundle.intro) {
    const answer = decision.interaction.type === 'plane'
      ? [...decision.expected_answer.cell, decision.interaction.methods.find(method => method.route === routes[0]).value]
      : decision.interaction.type === 'multi'
        ? decision.expected_answer.required : decision.expected_answer.one_of?.[0] || decision.expected_answer.terms;
    state = stateAPI.submitAnswer(bundle, state, {decision: decision.id, answer});
    assert.equal(state.lastFeedback.status, 'passed');
  }
  return {bundle, state, view};
}

const originalChoice = () => ({status: 'matched', kind: 'single_choice', target_ref: target,
  options: [{label: 'A', text: '$m\\le-2$ 或 $m\\ge2$'}, {label: 'B', text: '$-2<m<2$'}], correct_labels: ['A']});

function choiceFixture() {
  const value = fixture({readonly: true});
  for (const completion of value.view.completions) completion.original_choice = originalChoice();
  value.bundle = stateAPI.extendStreamBundle(value.bundle, value.view, target, graph);
  return value;
}

test('an original single-choice question finishes only after matching the verified result to its option', () => {
  const {bundle, state} = choiceFixture();
  const math = stateAPI.currentDecision(bundle, state);
  const afterMath = stateAPI.submitAnswer(bundle, state, {decision: math.id, answer: 'read'});
  assert.equal(afterMath.done, false);
  const decision = stateAPI.currentDecision(bundle, afterMath);
  assert.equal(decision.title, '选择原题答案');
  assert.equal(decision.source, 'original_choice');
  assert.deepEqual(decision.stream_steps, []);
  const wrong = stateAPI.submitAnswer(bundle, afterMath, {decision: decision.id, answer: 'B'});
  assert.equal(wrong.lastFeedback.status, 'wrong');
  assert.equal(wrong.done, false);
  const correct = stateAPI.submitAnswer(bundle, wrong, {decision: decision.id, answer: 'A'});
  assert.equal(correct.done, true);
  const beforeGraph = stateAPI.streamGraphState(bundle, afterMath), afterGraph = stateAPI.streamGraphState(bundle, correct);
  for (const field of ['nodes', 'edges', 'usedBasis', 'calls', 'stepNodes']) assert.deepEqual(afterGraph[field], beforeGraph[field]);
  const refreshed = stateAPI.refreshStreamState(bundle, JSON.parse(JSON.stringify(correct)));
  assert.equal(refreshed.done, true);
  const other = stateAPI.switchRoute(bundle, refreshed, routes[1]);
  assert.equal(other.done, false);
  assert.equal(stateAPI.switchRoute(bundle, other, routes[0]).done, true);
  assert.equal(stateAPI.undo(bundle, correct).done, false);
});

test('late verified choices add a final decision without discarding already completed math', () => {
  const value = fixture({readonly: true});
  const before = stateAPI.submitAnswer(value.bundle, value.state, {decision: 'math-1', answer: 'read'});
  assert.equal(before.done, true);
  value.view.completions[0].original_choice = originalChoice();
  const bundle = stateAPI.extendStreamBundle(value.bundle, value.view, target, graph);
  const state = stateAPI.refreshStreamState(bundle, before);
  assert.equal(state.done, false);
  assert.deepEqual(state.run.completed, before.run.completed);
  assert.equal(stateAPI.currentDecision(bundle, state).source, 'original_choice');
  const partial = {...value.view}; delete partial.completions;
  const startup = stateAPI.extendStreamBundle(bundle, partial, target, graph);
  assert.equal(startup.routes[routes[0]].steps.at(-1).id, bundle.routes[routes[0]].steps.at(-1).id);
});

test('revoking a verified route hides its original-choice decision and completion', () => {
  const value = choiceFixture();
  let state = stateAPI.submitAnswer(value.bundle, value.state, {decision: 'math-1', answer: 'read'});
  const choice = stateAPI.currentDecision(value.bundle, state);
  state = stateAPI.submitAnswer(value.bundle, state, {decision: choice.id, answer: 'A'});
  value.view.goals[target] = {status: 'conflict', available: false};
  const unavailable = stateAPI.extendStreamBundle(value.bundle, value.view, target, graph);
  const refreshed = stateAPI.refreshStreamState(unavailable, state);
  assert.equal(refreshed.done, false);
  assert.equal(stateAPI.currentDecision(unavailable, refreshed), null);
  assert.equal(unavailable.routes[routes[0]].steps.some(step => step.source === 'original_choice'), false);
});

test('unmatched or invalid original choices never invent a final question', () => {
  for (const change of [choice => { choice.status = 'unmatched'; }, choice => { choice.correct_labels = ['A', 'B']; },
    choice => { choice.correct_labels = ['C']; }, choice => { choice.options[1].label = 'A'; },
    choice => { choice.target_ref = '/other'; }, choice => { choice.kind = 'multiple_choice'; }]) {
    const value = fixture({readonly: true}), choice = originalChoice(); change(choice);
    value.view.completions[0].original_choice = choice;
    const bundle = stateAPI.extendStreamBundle(value.bundle, value.view, target, graph);
    assert.deepEqual(bundle.routes[routes[0]].steps.map(step => step.id), ['math-1']);
  }
});

test('original choices wait for pending mathematical interactions before being appended', () => {
  const value = fixture({readonly: true});
  value.view.completions[0].original_choice = originalChoice();
  value.view.interaction_states[0].status = 'pending';
  const bundle = stateAPI.extendStreamBundle(base, value.view, target, graph);
  assert.deepEqual(bundle.routes[routes[0]].steps, []);
});

// A small DOM fixture with real parent/child ownership. The engine's authored HTML
// stays opaque; only mathematical hosts and their completion pictures need parsing.
function documentFixture() {
  const roots = new Map(), document = {body: {dataset: {}, hasAttribute(name) {
    return name.startsWith('data-') && Object.hasOwn(this.dataset, dataKey(name.slice(5)));
  }, classList: {contains: () => false, toggle() {}, remove() {}}}};
  const dataKey = name => name.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
  const decode = value => value.replace(/&(quot|amp|lt|gt|#39);/g,
    (_, entity) => ({quot: '"', amp: '&', lt: '<', gt: '>', '#39': "'"})[entity]);
  class Element {
    constructor(tag = 'div') { this.tagName = tag; this.ownerDocument = document; this.children = []; this.dataset = {}; this.hidden = false; this._text = ''; this._html = ''; this.classList = {contains: name => this.className?.split(/\s+/).includes(name) || false}; }
    get childNodes() { return this.children; }
    get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
    set textContent(value) { this._text = String(value ?? ''); this.children = []; }
    append(...nodes) { for (const node of nodes) { if (node.parentNode) node.parentNode.children.splice(node.parentNode.children.indexOf(node), 1); node.parentNode = this; this.children.push(node); } }
    replaceChildren(...nodes) { for (const child of this.children) child.parentNode = null; this.children = []; this.append(...nodes); }
    remove() { if (this.parentNode) this.parentNode.children.splice(this.parentNode.children.indexOf(this), 1); this.parentNode = null; }
    closest(selector) { return selector.startsWith('.') && this.className?.split(/\s+/).includes(selector.slice(1)) ? this : this.parentNode?.closest(selector) || null; }
    setAttribute(name, value) { this[name] = value; }
    set innerHTML(value) {
      this._html = value; this.replaceChildren();
      if (/^\s*<svg\b/.test(value)) this.append(new Element('svg'));
      const completed = new Set();
      for (const match of value.matchAll(/<div class="gw-completed-body">([\s\S]*?)<div data-stream-completed="([^"]*)"><\/div>/g)) {
        const body = new Element(); body.className = 'gw-completed-body';
        for (const picture of match[1].matchAll(/<figure class="gw-figure gw-completion-graph"><span[^>]*data-graph="([^"]*)"[^>]*><\/span>/g)) {
          const figure = new Element('figure'), plot = new Element('span');
          figure.className = 'gw-figure gw-completion-graph'; plot.dataset.graph = decode(picture[1]);
          figure.append(plot); body.append(figure);
        }
        const host = new Element(); host.dataset.streamCompleted = match[2];
        body.append(host); this.append(body); completed.add(match[2]);
      }
      for (const match of value.matchAll(/<div[^>]*\bdata-stream-(context|completed|retained)(?:="([^"]*)")?[^>]*>/g)) {
        if (match[1] === 'completed' && completed.has(match[2])) continue;
        const node = new Element(); node.dataset[dataKey(`stream-${match[1]}`)] = match[2] || ''; this.append(node);
      }
      for (const match of value.matchAll(/<div data-completion-board="([^"]*)"><\/div>/g)) {
        const node = new Element(); node.dataset.completionBoard = decode(match[1]); this.append(node);
      }
      if (value.includes('<div data-derivation-board>')) {
        const node = new Element(); node.dataset.derivationBoard = ''; this.append(node);
      }
    }
    get innerHTML() { return this._html; }
    querySelectorAll(selector) {
      const attr = /^\[data-([^\]]+)\](?::not\(\[data-([^\]]+)\]\))?$/.exec(selector);
      const found = [];
      for (const child of this.children) {
        if (attr && Object.hasOwn(child.dataset, dataKey(attr[1])) && (!attr[2] || !Object.hasOwn(child.dataset, dataKey(attr[2])))) found.push(child);
        else if (selector.startsWith('.') && child.className?.split(/\s+/).includes(selector.slice(1))) found.push(child);
        else if (selector === child.tagName) found.push(child);
        found.push(...child.querySelectorAll(selector));
      }
      return found;
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  }
  document.createElement = tag => new Element(tag);
  document.querySelector = selector => {
    if (!roots.has(selector)) roots.set(selector, new Element());
    return roots.get(selector);
  };
  return {document, roots};
}

function engine(value = fixture()) {
  const {document, roots} = documentFixture(), storage = new Map();
  const context = vm.createContext({document, matchMedia: () => ({matches: true}), URL, structuredClone,
    setTimeout, clearTimeout, ...stateAPI, ...mathDOM, ...optionWorkspace, ...methodCards, mountMethodConnections, connectedMethodAnswer, formulaAnswerHTML, buildStreamReplay,
    createFormulaFitter, renderFittedFormula,
    PracticeMath: {render(node, text) { node.textContent = text; }},
    localStorage: {getItem: key => storage.get(key), setItem: (key, text) => storage.set(key, text)}});
  context.window = context;
  vm.runInContext(components, context);
  const definitions = source.replace(/^import .*;\n/gm, '').split("if (document.readyState === 'loading')")[0];
  const bridge = source.slice(source.indexOf('export async function mountWalk'), source.indexOf("if (document.body.dataset.walk !== 'mount')"));
  vm.runInContext(definitions + '\n' + bridge.replace(/^export /gm, ''), context);
  Object.assign(context, {fixture: value, initialBase: base});
  const run = code => vm.runInContext(code, context);
  run(`bundle = fixture.bundle; state = studentState = fixture.state; streamView = fixture.view;
    graphView = bundle.graph; bundleScope = 'search-progress:v1:student-a:submission:';
    options = {bundle: initialBase, progressScope: bundleScope, stream: {...fixture.view, target_ref: bundle.stream.target_ref}};
    actor = 'student'; renderCount = 0; realRender = render; realRenderGraph = renderGraph; realStopReplay = stopReplay;
    renderGraph = () => {}; stopReplay = () => {}; toggleSteps = () => {};
    render = () => {renderCount++; const current = currentDecision(bundle,state); if (current) ensureDraft(current); park();};`);
  return {context, roots, run, storage, value};
}

test('method prerequisite rejection displays feedback without advancing or revealing method choices', () => {
  const {context, roots, run} = engine();
  context.rangeBundle = read('../../site/data/graph-walk/function-concepts-range-q07.json');
  // This component still supports prerequisite checks for other selection cards.
  // Rational range lessons now offer their methods immediately after the domain.
  const decision = context.rangeBundle.intro.find(step => step.id === 'D3');
  decision.interaction.checks = [{id: 'domain', question: '本题定义域是否为全体实数？',
    options: [{value: 'real', label: '是'}, {value: 'restricted', label: '否'}],
    resolved: '本题定义域为全体实数', feedback: '请核对原函数的定义域。'}];
  decision.expected_answer.checks = {domain: 'real'};
  run(`bundle = rangeBundle; state = createState(bundle); options = {};
    while (currentDecision(bundle,state).id !== 'D3') {
      const d = currentDecision(bundle,state);
      state = submitAnswer(bundle,state,{decision:d.id,answer:d.expected_answer.one_of[0]});
    }
    ensureDraft(currentDecision(bundle,state));
    draft.checks[0] = 'restricted';
    changeDraft(d => confirmMethodCondition(d,1));`);
  assert.match(run('feedbackHTML()'), /再想一想.*定义域/s);
  assert.match(roots.get('#gw-announcement').textContent, /定义域/);
  assert.equal(run('draft.confirmed'), 0);
  assert.equal(run('currentDecision(bundle,state).id'), 'D3');
  assert.doesNotMatch(run('interactionHTML(currentDecision(bundle,state))'), /data-card-method/);
  run(`draft.checks[0] = 'real'; changeDraft(d => confirmMethodCondition(d,1));`);
  assert.equal(run('feedbackHTML()'), '');
  assert.equal(run('draft.confirmed'), 1);
  assert.match(run('interactionHTML(currentDecision(bundle,state))'), /data-card-method/);
  assert.equal(run('currentDecision(bundle,state).id'), 'D3');
});

function equalityEngineFixture() {
  const value = fixture({readonly: true});
  const options = ['A', 'B', 'C', 'D'].map(label => ({option_id: label, label, text: `选项 ${label} 的两个函数`}));
  const option_verdicts = options.map(row => ({...row, verdict: 'CD'.includes(row.label) ? 'equal' : 'different', reason: `reason-${row.label}`}));
  const completion = {...identity, status: 'verified', target_ref: target, route_id: routes[0], verified_route_sha256: 'equality-hash',
    answer: {kind: 'compare_functions', status: 'complete', option_verdicts},
    original_choice: {status: 'matched', kind: 'multiple_choice', selection_mode: 'multiple', target_ref: target,
      select_relation: 'equal', options, option_verdicts, correct_labels: ['C', 'D']}};
  const steps = options.flatMap(row => {
    const option_context = {option_id: row.option_id, label: row.label, target_ref: target, left_ref: `${row.label}/f`, right_ref: `${row.label}/g`};
    return [{id: `${row.label}-evidence`, source: 'page', title: `${row.label} 的证据`, question: '已验证的依据',
      option_context: {...option_context, phase: 'evidence'}, interaction: {type: 'read'}, expected_answer: {}},
    {id: `${row.label}-verdict`, source: 'page', title: `${row.label} 的结论`, question: '是否相同？',
      option_context: {...option_context, phase: 'verdict'}, interaction: {type: 'choice', field: 'verdict',
        options: [{value: 'equal', label: '相同'}, {value: 'different', label: '不同'}]},
      expected_answer: {one_of: ['CD'.includes(row.label) ? 'equal' : 'different']}}];
  });
  value.bundle.option_workspaces = options;
  Object.assign(value.bundle.routes[routes[0]], {completion, steps: [...steps, stateAPI.originalChoiceDecision(completion, target, routes[0])]});
  return value;
}

test('equality workspace shows only current option, locks old work, and accepts an explicit empty final draft', () => {
  const {run, roots} = engine(equalityEngineFixture());
  run(`state = submitAnswer(bundle, state, {decision:'A-evidence',answer:'read'});
    state = submitAnswer(bundle, state, {decision:'A-verdict',answer:'different'});
    realRender({scroll:false});`);
  let html = roots.get('#gw-steps').innerHTML;
  assert.match(html, /A ✓/);
  assert.match(html, /data-option-workspace="B"/);
  assert.doesNotMatch(html, /data-completed-decision="A-verdict"/);
  assert.equal(roots.get('#gw-undo').disabled, true);
  const position = run('state.run.completed.length');
  run(`reviewOption='A'; realRender({scroll:false});`);
  html = roots.get('#gw-steps').innerHTML;
  assert.match(html, /只读回看/);
  assert.match(html, /data-completed-decision="A-verdict"/);
  assert.doesNotMatch(html, /id="gw-active"/);
  assert.equal(run('state.run.completed.length'), position);
  run(`reviewOption=null;
    while(currentDecision(bundle,state).source!=='original_choice') {
      const d=currentDecision(bundle,state); state=submitAnswer(bundle,state,{decision:d.id,answer:d.interaction.type==='read'?'read':d.expected_answer.one_of[0]});
    }
    realRender({scroll:false});`);
  html = roots.get('#gw-steps').innerHTML;
  assert.match(html, /A ✓.*B ✓.*C ✓.*D ✓/s);
  assert.doesNotMatch(html, /reason-[ABCD]|data-completed-decision="[ABCD]-verdict"/);
  assert.equal(run('ready(currentDecision(bundle,state))'), true);
  assert.deepEqual(Array.from(run('draft')), []);
  assert.equal(roots.get('#gw-completion').innerHTML, '');
  run(`const final=currentDecision(bundle,state); state=submitAnswer(bundle,state,{decision:final.id,answer:[]}); realRender({scroll:false});`);
  assert.equal(run('state.done'), false);
  assert.equal(roots.get('#gw-completion').innerHTML, '');
  run(`state=submitAnswer(bundle,state,{decision:currentDecision(bundle,state).id,answer:['D','C']}); realRender({scroll:false});`);
  assert.equal(run('state.done'), true);
  const board = roots.get('#gw-completion [data-stream-completion]').querySelector('.gw-option-verdict-board');
  assert.ok(board);
  assert.deepEqual(board.children.map(row => row.textContent), ['A　不同：reason-A', 'B　不同：reason-B', 'C　相同：reason-C', 'D　相同：reason-D']);
});

function caseFixture({previousPath = ['constant-case'], currentPath = ['quadratic-case'], condition = 'c\\ne\\frac{1}{3}',
  previousBranch, currentBranch, branchCondition} = {}) {
  const value = fixture({merged: true, readonly: true});
  for (const math of value.view.math_steps) {
    math.case_path = math.ordinal === 1 ? previousPath : currentPath;
    if (math.ordinal === 1) math.highlight = {caption: '情况结果', items: [{label: '结论', math: '\\mathrm{true}'}],
      result: '对所有实数成立，保留本情况'};
    else if (condition !== null) math.case_condition = {latex: condition};
    const branch = math.ordinal === 1 ? previousBranch : currentBranch;
    if (branch) math.branch_id = branch;
    if (math.ordinal === 2 && branchCondition) math.branch_condition = {latex: branchCondition};
  }
  value.bundle = stateAPI.extendStreamBundle(base, value.view, target, graph);
  value.state = stateAPI.submitAnswer(value.bundle, value.state, {decision: 'math-1', answer: 'read'});
  return value;
}

function mergeFixture(history, {parent = [], folded = false, multipart = false} = {}) {
  const value = fixture({readonly: true});
  const cards = history.map((item, index) => ({...card(index + 1), ...item,
    after: [{latex: item.result}], highlight: {result: `$${item.result}$`}}));
  const active = {...card(cards.length + 1), case_path: parent,
    highlight: {layout: 'merge', items: [{label: 'hidden-input', math: 'secret-current-input'}], result: 'secret-union'}};
  cards.push(active);
  const interactions = cards.map((math, index) => ({...identity, target_ref: target, route_id: routes[0],
    interaction_id: `merge-fixture-${index}`, status: math === active ? 'interactive' : 'readonly',
    ...(folded && index === history.length - 1 ? {reason: 'folded'} : {}),
    steps: [{step_id: math.step_id, math_step_sha256: math.math_step_sha256}],
    parts: math === active ? (multipart ? [part('merge-first'), part('merge-last')] : [part('merge-last')]) : []}));
  value.view.math_steps = [...cards, ...value.view.math_steps.filter(math => math.route_id !== routes[0])];
  value.view.interactions = [...interactions, ...value.view.interactions.filter(chunk => chunk.route_id !== routes[0])];
  value.view.interaction_states = value.view.interactions.flatMap(chunk => chunk.steps.map(ref => ({...ref,
    target_ref: target, route_id: chunk.route_id, interaction_id: chunk.interaction_id, status: chunk.status})));
  value.bundle = stateAPI.extendStreamBundle(base, value.view, target, graph);
  for (let i = 0; i < history.length - Number(folded); i++) {
    value.state = stateAPI.submitAnswer(value.bundle, value.state, {decision: `math-${i + 1}`, answer: 'read'});
  }
  return value;
}

test('a merge question keeps each completed opening result visible without revealing the union', () => {
  const {run, roots} = engine(mergeFixture([
    {case_path: ['nondegenerate'], branch_id: 'opening-up', branch_condition: {latex: 'k>0'}, result: '(0,+\\infty)'},
    {case_path: ['nondegenerate'], branch_id: 'opening-down', branch_condition: {latex: 'k<0'}, result: 'old-delta-condition'},
    {case_path: ['nondegenerate'], branch_id: 'opening-down', branch_condition: {latex: 'k<0'}, result: '(-\\infty,-4)'},
  ], {parent: ['nondegenerate'], multipart: true}));
  const html = run('carryHTML()');
  assert.match(html, /汇总各情况.*已得各情况结果/);
  assert.match(html, /\$k&gt;0\$.*\$\(0,\+\\infty\)\$/);
  assert.match(html, /\$k&lt;0\$.*\$\(-\\infty,-4\)\$/);
  assert.doesNotMatch(html, /old-delta-condition|secret-|接第/);
  run('renderInteraction(currentDecision(bundle,state),{})');
  assert.match(roots.get('#gw-active').innerHTML, /已得各情况结果/);
  assert.doesNotMatch(roots.get('#gw-active').innerHTML, /secret-/);
  run(`state = submitAnswer(bundle,state,{decision:'merge-first',answer:'yes'});`);
  assert.equal(run('carryHTML()'), html, 'a partial merge answer must not expose the active card result');
  run('actor = "replay"; state = refreshStreamState(bundle,JSON.parse(JSON.stringify(state)));');
  assert.equal(run('carryHTML()'), html, 'AI and refresh keep the same confirmed inputs');
  run(`state = submitAnswer(bundle,state,{decision:'merge-last',answer:'yes'}); state = undo(bundle,state);`);
  assert.equal(run('carryHTML()'), html, 'undo hides the merge result again');
});

test('an outer merge uses the latest result of each case, including its completed inner union', () => {
  const {run} = engine(mergeFixture([
    {case_path: ['zero'], case_condition: {latex: 'k=0'}, result: '\\varnothing'},
    {case_path: ['nondegenerate'], branch_id: 'opening-up', branch_condition: {latex: 'k>0'}, result: 'old-up-result'},
    {case_path: ['nondegenerate'], branch_id: 'opening-down', branch_condition: {latex: 'k<0'}, result: 'old-down-result'},
    {case_path: ['nondegenerate'], case_condition: {latex: 'k\\ne0'}, result: '(-\\infty,-4)\\cup(0,+\\infty)'},
  ]));
  const html = run('carryHTML()');
  assert.equal(html.match(/class="gw-merge-premise"/g).length, 2);
  assert.match(html, /\$k=0\$.*\\varnothing/);
  assert.match(html, /k\\ne0.*\(-\\infty,-4\)\\cup\(0,\+\\infty\)/);
  assert.doesNotMatch(html, /old-up-result|old-down-result|secret-/);
});

test('three sign cases remain available even when a predecessor quiz was folded', () => {
  const {run} = engine(mergeFixture([
    {case_path: ['positive'], case_condition: {latex: 'x>0'}, result: '(0,2)'},
    {case_path: ['zero'], case_condition: {latex: 'x=0'}, result: '\\{0\\}'},
    {case_path: ['negative'], case_condition: {latex: 'x<0'}, result: '(-3,0)'},
  ], {folded: true}));
  const html = run('carryHTML()');
  assert.equal(html.match(/class="gw-merge-premise"/g).length, 3);
  for (const result of ['(0,2)', '\\{0\\}', '(-3,0)']) assert.ok(html.includes(result));
  assert.doesNotMatch(html, /secret-/);
});

for (const nested of [true, false]) test(`an outer merge does not substitute an unfinished inner union (${nested ? 'case paths' : 'branch IDs'})`, () => {
  const {run} = engine(mergeFixture([
    {case_path: nested ? ['A', 'left'] : ['A'], ...(nested ? {} : {branch_id: 'left'}),
      case_condition: {latex: 'a<0'}, result: 'left-result'},
    {case_path: nested ? ['A', 'right'] : ['A'], ...(nested ? {} : {branch_id: 'right'}),
      case_condition: {latex: 'a>0'}, result: 'right-result'},
    {case_path: ['B'], case_condition: {latex: 'a=0'}, result: 'B-result'},
  ]));
  const html = run('carryHTML()');
  assert.equal(html.match(/class="gw-merge-premise"/g).length, 1);
  assert.match(html, /B-result/);
  assert.doesNotMatch(html, /left-result|right-result|secret-/);
});

test('a merge never pulls a result from a sibling scope, another route, or a future card', () => {
  const {run} = engine(mergeFixture([
    {case_path: ['sibling'], case_condition: {latex: 'p=0'}, result: 'sibling-secret'},
    {case_path: ['active', 'left'], case_condition: {latex: 'p<0'}, result: 'known-left'},
    {case_path: ['active', 'right'], case_condition: {latex: 'p>0'}, result: 'known-right'},
  ], {parent: ['active']}));
  run(`bundle.stream.math_steps.push({...bundle.stream.math_steps[0], ordinal:999, step_id:'future-card',
    case_path:['active','future'], highlight:{result:'future-secret'}});`);
  const html = run('carryHTML()');
  assert.match(html, /known-left.*known-right/);
  assert.doesNotMatch(html, /sibling-secret|future-secret|secret-after/);
});

test('crossing a case boundary carries only the new frozen condition, never the previous case result', () => {
  const {run} = engine(caseFixture());
  const html = run('carryHTML()');
  assert.match(html, /切换情况/);
  assert.match(html, /当前条件：\$c\\ne\\frac\{1\}\{3\}\$/);
  assert.doesNotMatch(html, /对所有实数成立|保留本情况|接第|constant-case|quadratic-case/);
  run('actor = "replay"');
  assert.equal(run('carryHTML()'), html, 'AI replay follows the same scope boundary');
  run(`state = submitAnswer(bundle,state,{decision:'math-2',answer:'read'}); state = undo(bundle,state);`);
  assert.equal(run('carryHTML()'), html, 'undo recomputes context from the current decision');
});

test('within the same case, the prior result continues to carry normally', () => {
  const {run} = engine(caseFixture({previousPath: ['branch'], currentPath: ['branch']}));
  const html = run('carryHTML()');
  assert.match(html, /接第/);
  assert.match(html, /对所有实数成立，保留本情况/);
  assert.doesNotMatch(html, /切换情况/);
});

test('opening branches have separate carry scopes without changing their execution case path', () => {
  const value = caseFixture({previousPath: ['nondegenerate'], currentPath: ['nondegenerate'],
    previousBranch: 'opening-up', currentBranch: 'opening-down', condition: 'k\\ne0', branchCondition: 'k<0'});
  const {run} = engine(value);
  const html = run('carryHTML()');
  assert.match(html, /切换情况.*当前条件：\$k\\ne0\$ 且 \$k&lt;0\$/);
  assert.doesNotMatch(html, /对所有实数成立|保留本情况|接第|opening-up|opening-down/);
  assert.deepEqual(value.bundle.stream.math_steps[0].case_path, ['nondegenerate']);
  assert.deepEqual(value.bundle.stream.math_steps[1].case_path, ['nondegenerate']);
  run('actor = "replay"');
  assert.equal(run('carryHTML()'), html);
  run(`state = refreshStreamState(bundle,JSON.parse(JSON.stringify(state)));`);
  assert.equal(run('carryHTML()'), html, 'saved progress restores the same branch boundary');
  run(`state = submitAnswer(bundle,state,{decision:'math-2',answer:'read'}); state = undo(bundle,state);`);
  assert.equal(run('carryHTML()'), html);
});

test('within one opening branch its confirmed condition carries to its range question', () => {
  const {run} = engine(caseFixture({previousPath: ['nondegenerate'], currentPath: ['nondegenerate'],
    previousBranch: 'opening-down', currentBranch: 'opening-down', condition: 'k\\ne0', branchCondition: 'k<0'}));
  assert.match(run('carryHTML()'), /接第.*对所有实数成立，保留本情况/);
  assert.doesNotMatch(run('carryHTML()'), /切换情况|汇总各情况/);
});

test('merging openings inside the parent case does not carry the last opening result', () => {
  const {run} = engine(caseFixture({previousPath: ['nondegenerate'], currentPath: ['nondegenerate'],
    previousBranch: 'opening-down', condition: 'k\\ne0'}));
  const html = run('carryHTML()');
  assert.match(html, /data-case-transition="merge".*汇总各情况.*当前条件：\$k\\ne0\$/);
  assert.doesNotMatch(html, /对所有实数成立|保留本情况|接第/);
});

test('opening metadata works outside execution cases and never invents a missing sign condition', () => {
  const {run} = engine(caseFixture({previousPath: [], currentPath: [], condition: null,
    currentBranch: 'opening-up', branchCondition: 'a>2'}));
  assert.match(run('carryHTML()'), /当前情况.*当前条件：\$a&gt;2\$/);
  const fixed = engine(caseFixture({previousPath: ['nondegenerate'], currentPath: ['nondegenerate'],
    condition: null, currentBranch: 'opening-up'}));
  assert.match(fixed.run('carryHTML()'), /切换情况/);
  assert.doesNotMatch(fixed.run('carryHTML()'), /当前条件|1&gt;0|保留本情况/);
});

test('identical parent and opening conditions appear once without dropping independent premises', () => {
  const {run} = engine(caseFixture({previousPath: [], currentPath: ['nondegenerate'],
    condition: 'a>2', currentBranch: 'opening-up', branchCondition: 'a>2'}));
  assert.equal(run('carryHTML()').split('$a&gt;2$').length - 1, 1);
});

test('leaving cases for a merge does not claim that the last branch is a global premise', () => {
  const {run} = engine(caseFixture({currentPath: [], condition: null}));
  const html = run('carryHTML()');
  assert.match(html, /汇总各情况/);
  assert.doesNotMatch(html, /当前条件|对所有实数成立|保留本情况|接第/);
});

test('nested cases return to the frozen parent condition and older cards never guess one', () => {
  const nested = engine(caseFixture({previousPath: ['outer', 'inner'], currentPath: ['outer'], condition: 'b>2'}));
  assert.match(nested.run('carryHTML()'), /返回上层情况.*当前条件：\$b&gt;2\$/);
  const legacy = engine(caseFixture({condition: null}));
  legacy.run(`bundle.stream.math_steps.find(card => card.step_id === 'math-2').explanation = '设 k=0，这不是可供推断的条件字段。';`);
  const html = legacy.run('carryHTML()');
  assert.match(html, /切换情况/);
  assert.doesNotMatch(html, /k=0|当前条件|保留本情况/);
});

test('a first branch announces its current condition without treating classification results as its premise', () => {
  const {run} = engine(caseFixture({previousPath: [], currentPath: ['quadratic'], condition: 'p<7'}));
  assert.match(run('carryHTML()'), /当前情况.*当前条件：\$p&lt;7\$/);
  assert.doesNotMatch(run('carryHTML()'), /保留本情况/);
});

test('folded evidence from another case does not override the actual preceding case', () => {
  const {run} = engine(caseFixture({previousPath: ['other-case'], currentPath: ['active-case']}));
  run(`bundle.stream.math_steps.push({...bundle.stream.math_steps[1],step_id:'math-3'});
    beforeCase = {source:'stream',stream_steps:[{step_id:'math-2',math_step_sha256:'discriminant-2-hash'},
      {step_id:'math-1',math_step_sha256:'discriminant-1-hash'}],stream_folded:['math-1']};
    afterCase = {source:'stream',stream_steps:[{step_id:'math-3',math_step_sha256:'discriminant-2-hash'}]};`);
  assert.equal(run('caseCarryHTML(beforeCase,afterCase)'), null);
});

test('AI replay answers the original choice using the shared decision engine', () => {
  const value = choiceFixture(), {run} = engine(value);
  const replay = JSON.parse(run('JSON.stringify(streamReplay())'));
  const last = value.bundle.routes[routes[0]].steps.at(-1);
  assert.deepEqual(replay.actions.at(-1), {decision: last.id, answer: 'A'});
  let state = value.state;
  for (const action of replay.actions.filter(action => action.decision !== 'D3')) {
    state = stateAPI.submitAnswer(value.bundle, state, action);
  }
  assert.equal(state.done, true);
});

test('interactive parts hide frozen formulas; only the last completed part mounts every merged math card', () => {
  const {run, roots} = engine(fixture({merged: true}));
  run('renderInteraction(currentDecision(bundle,state))');
  const active = roots.get('#gw-active');
  assert.equal(active.dataset.decisionId, 'first');
  assert.doesNotMatch(active.textContent, /before-1|before-2/, 'derivation inputs are not student-visible givens');
  assert.doesNotMatch(active.innerHTML, /data-stream-context/);
  assert.doesNotMatch(active.textContent, /secret-/);
  assert.doesNotMatch(run(`completedHTML({decision:'first',answer:'yes'},5,1,'discriminant')`), /stream-completed|secret-/);
  run(`state = studentState = submitAnswer(bundle,state,{decision:'first',answer:'yes'}); renderInteraction(currentDecision(bundle,state));`);
  assert.doesNotMatch(active.textContent, /secret-/);
  run(`state = studentState = submitAnswer(bundle,state,{decision:'last',answer:'yes'});
    document.querySelector('#gw-steps').innerHTML=completedHTML(state.run.completed.at(-1),6,1,'discriminant'); mountCompletedMath();`);
  assert.match(roots.get('#gw-steps').textContent, /secret-after-1.*secret-explanation-1.*secret-after-2/);
  assert.equal(run('visibleStreamCards.size'), 2);
  const mounted = [...run('streamCards.values()')];
  assert.ok(mounted.every(card => card.node.className.includes('is-embedded')));
  assert.ok(mounted.every(card => !card.heading.hidden), 'distinct mathematical substeps retain their headings');
});

test('completed child cards retain the original branch context, safely escaped', () => {
  const child = part('child');
  child.source_context = '第 2 段函数：$f(x)=ax^2-x+2$，$x>1$。<script>bad</script>';
  const {run} = engine(fixture({parts: [child]}));
  const html = run(`completedHTML({decision:'child',answer:'yes'},5,1,'discriminant')`);
  assert.match(html, /第 2 段函数/);
  assert.match(html, /ax\^2-x\+2/);
  assert.match(html, /x&gt;1/);
  assert.doesNotMatch(html, /<script>/);
});

test('completed submethod selection keeps the shared selection plane instead of a math summary', () => {
  const value = fixture({parts: [part('borrow')]});
  const selection = value.bundle.intro.find(item => item.interaction.type === 'plane');
  for (const route of Object.values(value.bundle.routes)) Object.assign(route.steps[0], {
    interaction: structuredClone(selection.interaction), expected_answer: selection.expected_answer,
  });
  const chosen = selection.interaction.methods.find(method => method.route === routes[0]);
  const answer = [...selection.expected_answer.cell, chosen.value];
  const {run, roots} = engine(value);
  run('renderInteraction(currentDecision(bundle,state))');
  assert.match(roots.get('#gw-active').innerHTML, /gw-plane/);
  const html = run(`completedHTML({decision:'borrow',answer:${JSON.stringify(answer)}},7,1,'discriminant')`);
  const plane = run(`planeHTML(currentDecision(bundle,state),${JSON.stringify(answer)},false)`);
  assert.ok(html.includes(plane), 'reuse the same readonly plane renderer as the parent selection');
  assert.match(html, /gw-plane-pin/);
  assert.ok(html.includes(`data-method="${chosen.value}" data-chosen>${chosen.label}</span>`));
  assert.doesNotMatch(html, /data-stream-completed|gw-answer|data-plane-cell/);
});

test('completed shared math cards show one derivation without repeating answers or part feedback', () => {
  for (const grouped of [false, true]) for (const conclusionOnly of [false, true]) {
    const parts = (grouped ? [part('move'), part('divide')] : [part('policy')]).map(value => ({
      ...value, feedback: {answer: '重复的步骤说明'},
      interaction: {...value.interaction, options: [{value: 'yes', label: '重复的答案'}, {value: 'no', label: '不成立'}]},
    }));
    const value = fixture({parts});
    for (const step of value.bundle.stream.math_steps) step.highlight = {
      caption: '数学关系', items: [{label: '结论', math: 'a\\ge h(x)'}], conclusion_only: conclusionOnly,
    };
    const {run, roots} = engine(value);
    for (const p of parts) run(`state=submitAnswer(bundle,state,{decision:'${p.id}',answer:'yes'});`);
    const html = grouped ? 'groupCompletedHTML(stepUnits().units.at(-1),5)'
      : "completedHTML(state.run.completed.at(-1),5,1,'discriminant')";
    run(`document.querySelector('#gw-steps').innerHTML=${html}; mountCompletedMath();`);
    const completed = roots.get('#gw-steps');
    assert.match(completed.textContent, /a\\ge h\(x\)/);
    if (conclusionOnly) {
      assert.match(completed.innerHTML, /重复的步骤说明/, 'feedback remains when the math card has no derivation');
    } else {
      assert.doesNotMatch(completed.innerHTML, /重复的答案|重复的步骤说明/);
      assert.match(completed.textContent, /secret-explanation-1/);
      assert.equal(completed.querySelectorAll('.stage-three-derivation').length, 1);
    }
  }
});

test('a local deduction reveals its result only after passing, with no repeated carry, answer or feedback', () => {
  const value = fixture({parts: [part('deduction')]});
  const board = {layout: 'derivation', caption: '求 $f(x)$ 的定义域', connector: '⇒', items: [
    {label: '完整输入的范围', math: '-3\\le 2x-1\\le2'}, {label: '目标函数的定义域', math: null}]};
  for (const route of Object.values(value.bundle.routes)) {
    const decision = route.steps[0];
    Object.assign(decision, {title: '求定义域', stem_board: structuredClone(board),
      feedback: {answer: '重复的正确反馈', wrong: '请检查外层自变量的范围'}});
    decision.interaction.options[0].label = '已选答案总结';
  }
  for (const step of value.bundle.stream.math_steps) {
    step.highlight = {...board, items: [board.items[0], {...board.items[1], math: '[-1,\\frac32]'}]};
  }
  const {run, roots} = engine(value);
  assert.equal(run('carryHTML()'), '');
  run('renderInteraction(currentDecision(bundle,state))');
  const active = roots.get('#gw-active');
  const pending = active.querySelector('.gw-derivation-board');
  assert.equal(pending.dataset.state, 'pending');
  assert.equal(pending.querySelector('.gw-derivation-caption').dataset.mathText, 'true');
  assert.equal(pending.querySelector('.gw-derivation-unknown').textContent, '?');
  assert.equal(pending.querySelector('.gw-derivation-formula').dataset.fittedFormula, 'true');
  assert.equal(pending.querySelectorAll('.gw-formula-line').length, 1, 'the unknown answer stays hidden');
  assert.match(pending.textContent, /-3\\le 2x-1\\le2/);
  assert.doesNotMatch(active.textContent, /secret-|\\frac32/);
  run(`state=submitAnswer(bundle,state,{decision:'deduction',answer:'no'}); renderInteraction(currentDecision(bundle,state));`);
  assert.equal(active.querySelector('.gw-derivation-board').dataset.state, 'pending');
  assert.doesNotMatch(active.textContent, /\\frac32/);
  run(`state=submitAnswer(bundle,state,{decision:'deduction',answer:'yes'});
    document.querySelector('#gw-steps').innerHTML=completedHTML(state.run.completed.at(-1),5,1,'discriminant'); mountCompletedMath();`);
  const completed = roots.get('#gw-steps');
  assert.doesNotMatch(completed.innerHTML, /gw-answer|gw-result|已选答案总结|重复的正确反馈/);
  assert.equal(completed.querySelector('.gw-derivation-board').dataset.state, 'complete');
  assert.equal(completed.querySelector('.gw-derivation-unknown'), null);
  assert.equal(completed.querySelectorAll('.gw-formula-line').length, 2, 'given and verified result both use responsive formulas');
  assert.match(completed.querySelector('.gw-derivation-formula').textContent, /-3\\le 2x-1\\le2/);
  assert.match(completed.textContent, /\\frac32/);
  assert.equal(completed.querySelector('.stage-three-derivation').open, false);
  assert.ok([...run('streamCards.values()')].every(card => card.heading.hidden));
});

test('a discriminant condition is only an option until confirmed, including retry, restore and undo', () => {
  const condition = 'm^2-4\\ge0';
  const decision = {...part('delta'), title: '开口向上：建立判别式条件',
    question: '本步判别式为 $\\Delta=m^2-4$，应对判别式施加哪个条件？'};
  decision.interaction.options[0].label = `$${condition}$`;
  decision.interaction.options[1].label = '$m^2-4<0$';
  const value = fixture({parts: [decision]});
  for (const step of value.bundle.stream.math_steps) {
    step.before = [{latex: condition}];
    step.after = [{latex: condition}];
  }
  const {run, roots} = engine(value);
  const checkQuestion = () => {
    run('renderInteraction(currentDecision(bundle,state))');
    const active = roots.get('#gw-active');
    assert.doesNotMatch(active.innerHTML, /data-stream-context|stage-three-before/);
    assert.ok(active.innerHTML.includes(decision.question), 'the discriminant expression stays in the explicit question');
    const option = /<button\b[^>]*data-value="yes"[^>]*>[\s\S]*?<\/button>/.exec(active.innerHTML)?.[0];
    assert.ok(option?.includes(`<span data-math-text>$${condition}$</span>`));
    assert.ok(!active.innerHTML.replace(option, '').includes(condition),
      'the condition appears only in its option, whose accessible name repeats its visible label');
    assert.ok(!active.textContent.includes(condition), 'no formula is mounted from before');
  };
  checkQuestion();
  run("draft = 'yes'");
  checkQuestion();
  run("state = studentState = submitAnswer(bundle,state,{decision:'delta',answer:'no'});");
  checkQuestion();
  run('state = studentState = refreshStreamState(bundle, JSON.parse(JSON.stringify(state)));');
  checkQuestion();
  run(`state = studentState = submitAnswer(bundle,state,{decision:'delta',answer:'yes'});
    document.querySelector('#gw-steps').innerHTML=completedHTML(state.run.completed.at(-1),4,1,'discriminant'); mountCompletedMath();`);
  assert.ok(roots.get('#gw-steps').textContent.includes(condition), 'confirmed conclusion remains visible');
  run('state = studentState = undo(bundle,state);');
  checkQuestion();
});

test('a named lesson step owns the title in both readonly and completed views', () => {
  const {run, roots} = engine(fixture({readonly: true}));
  run('renderInteraction(currentDecision(bundle,state))');
  const context = roots.get('#gw-active').querySelector('[data-stream-context]');
  assert.equal(context.children[0].children[0].hidden, true, 'the active read card does not repeat its parent title');
  assert.match(context.children[0].className, /\bis-embedded\b/);
  run(`state = studentState = submitAnswer(bundle,state,{decision:currentDecision(bundle,state).id,answer:'read'});
    document.querySelector('#gw-steps').innerHTML=completedHTML(state.run.completed.at(-1),4,1,'discriminant'); mountCompletedMath();`);
  const mounted = [...run('streamCards.values()')][0];
  assert.equal(mounted.heading.hidden, true, 'the completed card also uses its enclosing title');
  assert.match(mounted.node.className, /\bis-embedded\b/);
});

test('folded cards ask nothing, ride with the next step and mount collapsed after its own card', () => {
  const value = fixture({folded: true});
  const steps = value.bundle.routes[routes[0]].steps;
  assert.deepEqual(steps.map(step => step.id), ['first', 'last']);
  for (const step of steps) {
    assert.deepEqual(step.stream_steps.map(ref => ref.step_id), ['math-2', 'math-1']);
    assert.deepEqual(step.stream_folded, ['math-1']);
  }
  const {run, roots} = engine(value);
  run('renderInteraction(currentDecision(bundle,state))');
  const active = roots.get('#gw-active');
  assert.doesNotMatch(active.textContent, /before-1|before-2|secret-/);
  run(`state = studentState = submitAnswer(bundle,state,{decision:'first',answer:'yes'});
    state = studentState = submitAnswer(bundle,state,{decision:'last',answer:'yes'});
    document.querySelector('#gw-steps').innerHTML=completedHTML(state.run.completed.at(-1),6,1,'discriminant'); mountCompletedMath();`);
  const host = roots.get('#gw-steps').querySelector('[data-stream-completed]');
  const [own, fold] = host.children;
  assert.match(own.textContent, /secret-after-2/);
  assert.equal(fold.tagName, 'details');
  assert.match(fold.textContent, /各情况的推导/);
  assert.match(fold.textContent, /secret-after-1/);
  assert.equal(run('visibleStreamCards.size'), 2);
});

const quadratic = {kind: 'quadratic', caption: '示意图：取 $a=0$', params: {coefficient: 1, vertex: [0, 1], bounds: [-0.25, 0.75, -0.25, 1.5],
  xTicks: [[0, '0'], [0.5, '1/2']], variable: 'x', interval: [0, 0.5], interval_closed: [false, true],
  points: [{x: 0, open: true}, {x: 0.5}], yLabel: '1', showVertex: false, title: '曲线', description: '左端空心'}};
const line = (pieces, description) => ({kind: 'number_line', params: {bounds: [-3.25, -0.25], pieces, points: [],
  ticks: [[-2.5, '-5/2'], [-1, '-1']], variable: 'a', title: 'a 的取值范围', description}});

test('server pictures dispatch by kind; open ends stay hollow and dashed', () => {
  const {context} = engine();
  const draw = spec => context.PracticeComponents.graph({...spec, uid: 'u'});
  const curve = draw(quadratic);
  assert.match(curve, /class="graph-interval is-closed" d="M\S+ 48V222"/);
  assert.match(curve, /class="graph-interval" d="M\S+ 48V222"[^>]*stroke-dasharray/);
  assert.match(curve, /class="quadratic-point"[^>]*r="5" fill="#fff"/);
  assert.doesNotMatch(curve, /undefined/, 'unlabelled points draw no label');
  const set = draw(line([{from: -2.5, to: null, left_closed: false, right_closed: false}], '(-5/2, +∞)'));
  assert.match(set, /class="number-line-end" cx="[\d.]+" cy="50" r="6" fill="#fff"/);
  assert.match(set, /<path d="M316 42L326 50L316 58Z"/, 'an unbounded side ends in an arrow');
  assert.match(set, /<desc id="u-description">\(-5\/2, \+∞\)<\/desc>/);
  assert.match(draw(line([{from: -2.5, to: -1, left_closed: true, right_closed: true}], '[-5/2,-1]')), /number-line-end is-closed/);
  assert.equal(draw({kind: 'unknown', params: {}}), '');
  const authored = context.PracticeComponents.quadraticGraph({...quadratic.params, interval_closed: undefined, uid: 'old'});
  assert.match(authored, /class="graph-interval" d="M\S+ 48V222M\S+ 48V222"[^>]*stroke-dasharray/);
  assert.doesNotMatch(authored, /is-closed/, 'authored graphs keep both guides dashed');
});

test('streamed graph contracts reject malformed drawing data without affecting the authored API', () => {
  const {context} = engine(), api = context.PracticeComponents;
  const common = {bounds: [-1, 1, -1, 1], variable: 'x', points: [], xTicks: [], interval: [0, 1], interval_closed: [false, true], title: '函数', description: '函数示意图'};
  const linear = {kind: 'linear', params: {...common, slope: 0, intercept: 0}};
  const reciprocal = {kind: 'reciprocal_sum', params: {...common, a: -1, b: -1, negative: false}};
  const valid = [quadratic, linear, reciprocal, line([], '空集'), line([{from: null, to: null, left_closed: false, right_closed: false}], '实数集')];
  for (const spec of valid) {
    assert.equal(api.validateGraph(spec), true, spec.kind);
    assert.match(api.graph({...spec, uid: 'valid'}), /^<svg/);
  }
  const changed = (spec, params) => ({...spec, params: {...spec.params, ...params}});
  const invalid = [null, {}, {kind: 'toString', params: {}}, {...quadratic, kind: 'unknown'}, {kind: {toString: null}, params: {}},
    changed(quadratic, {vertex: undefined}), changed(quadratic, {vertex: [0]}), changed(quadratic, {coefficient: '1'}),
    changed(quadratic, {coefficient: 0}), changed(quadratic, {bounds: [-1, 1]}), changed(quadratic, {bounds: [-1, 1, 0, 0]}),
    changed(quadratic, {bounds: [-1e308, 1e308, -1, 1]}), changed(quadratic, {bounds: [-1, 1, -1e308, 1e308]}),
    changed(quadratic, {variable: undefined}), changed(quadratic, {points: undefined}), changed(linear, {interval: undefined}),
    changed(linear, {xTicks: undefined}), changed(linear, {interval_closed: undefined}),
    changed(quadratic, {bounds: [-1, Infinity, -1, 1]}), changed(quadratic, {xTicks: [[0]]}),
    changed(quadratic, {points: [{x: '0'}]}), changed(quadratic, {points: [{x: 0, place: 1}]}),
    changed(quadratic, {interval: [1, 0]}), changed(quadratic, {interval_closed: ['false', true]}),
    changed(line([], '空集'), {bounds: [0, 0]}), changed(line([], '空集'), {bounds: [-1, 1, -1, 1]}),
    changed(line([], '空集'), {pieces: [{from: null, to: 1, left_closed: true, right_closed: true}]}),
    changed(line([], '空集'), {pieces: [{from: 1, to: 0, left_closed: false, right_closed: true}]}),
    changed(line([], '空集'), {pieces: 'empty'}), changed(line([], '空集'), {points: null}),
    changed(line([], '空集'), {ticks: [[0, {}]]}), changed(line([], '空集'), {description: null}),
    changed(linear, {slope: NaN}), changed(reciprocal, {a: '<text>bad</text>'}), changed(reciprocal, {b: 0}),
    changed(reciprocal, {points: [{x: 0}]})];
  for (const spec of invalid) {
    assert.equal(api.validateGraph(spec), false, JSON.stringify(spec));
    assert.equal(api.graph(spec), '', 'bad graph returns no SVG rather than throwing');
  }
  assert.equal(api.graph({...changed(quadratic, {coefficient: 1e308, vertex: [-1e308, 1e308]}), uid: 'overflow'}), '', 'finite inputs must not produce nonfinite SVG coordinates');
});

test('streamed axis explorers drag a fixed-shape parabola and mark the target on each end as drawn', () => {
  const {context} = engine(), api = context.PracticeComponents;
  // x^2+ax+1 on (0,1/2], minimum: the open left end is a hollow "下端", the closed right end a solid "最低".
  const params = {bounds: [-0.94, 1.45, -0.28, 2.12], xTicks: [[0, '0'], [0.5, '1/2']], variable: 'x', points: [],
    interval: [0, 0.5], interval_closed: [false, true], title: '对称轴与区间', description: '拖动对称轴',
    coefficient: 1, constant: 1, axis: {min: -0.59, max: 1.1, step: 0.01, value: 0.25}, marks: [], target: 'min'};
  const spec = {kind: 'axis_explorer', params, caption: '拖动对称轴'};
  assert.equal(api.validateGraph(spec), true);
  const html = api.graph({...spec, uid: 'axis'});
  assert.match(html, /^<div class="axis-explorer">/);
  assert.match(html, /data-axis-input min="-0.59" max="1.1" step="0.01" value="0.25"/);
  assert.match(html, />1\/2<\/text>/, 'server tick labels replace raw decimals');
  const layer = h => api.axisExplorerLayer({...params, uid: 'axis'}, h);
  assert.match(layer(0.25), /class="axis-vertex lowest"[^>]*>.*最低/s, 'the vertex is lowest while the axis is inside');
  assert.match(layer(1), /class="axis-endpoint lowest"[^>]*fill="#b65c42"[^>]*\/><text[^>]*>最低</, 'a closed end is attained');
  assert.match(layer(-0.3), /class="axis-endpoint lowest"[^>]*fill="#fff"[^>]*\/><text[^>]*>下端</, 'an open end is only approached');
  assert.match(layer(0.25), /class="axis-endpoint"[^>]*fill="#b65c42"/, 'a closed endpoint remains solid even when the vertex is lowest');
  assert.match(layer(0.25), /class="axis-endpoint"[^>]*fill="#fff"/, 'the open endpoint remains hollow even when it is not lowest');
  // A downward parabola turns towards its highest point.
  assert.match(api.axisExplorerLayer({...params, coefficient: -1, target: 'max', uid: 'down'}, 0.25), /axis-vertex highest/);
  const changed = values => ({...spec, params: {...params, ...values}});
  for (const bad of [changed({axis: {min: 1, max: 0, step: 0.01, value: 0.5}}), changed({axis: {min: 0, max: 1, step: 0, value: 0.5}}),
    changed({axis: {min: 0, max: 1, step: 0.01, value: 2}}), changed({constant: '1'}), changed({target: 'middle'}),
    changed({marks: [{x: 1}]})]) assert.equal(api.validateGraph(bad), false, JSON.stringify(bad.params));
});

const parameterAxis = (values = {}) => ({kind: 'axis_explorer', uid: 'parameter-axis', params: {
  bounds: [-3, 5, -30, 40], xTicks: [[0, '0'], [2, '2']], variable: 'x', points: [],
  interval: [0, 2], interval_closed: [true, true], title: '对称轴与参数', description: '拖动对称轴观察函数',
  coefficient: 1, constant: 15, constant_by_axis: {linear: -2, quadratic: 0},
  parameter: {name: 'm', scale: 2, offset: 0},
  axis: {min: -1, max: 3, step: 0.1, value: 1}, marks: [], target: 'min', ...values,
}});

test('parameter axis curves, vertices and endpoints follow the original quadratic family', () => {
  const {context} = engine(), api = context.PracticeComponents;
  const cases = [
    {spec: parameterAxis(), value: (x, m) => x * x - m * x - m + 15},
    {spec: parameterAxis({coefficient: -2, constant: -7, constant_by_axis: {linear: 3, quadratic: 2},
      parameter: {name: 'k', scale: -4, offset: 3}, variable: 't', target: 'max'}),
    value: (t, k) => -2 * t * t + (3 - k) * t - 7 + 3 * (3 - k) / 4 + 2 * ((3 - k) / 4) ** 2},
    {spec: parameterAxis({coefficient: 0.5, constant: 0, constant_by_axis: {linear: 0, quadratic: -1},
      parameter: {name: 'b', scale: 1, offset: -2}, variable: 'u'}),
    value: (u, b) => 0.5 * u * u - (b + 2) * u - (b + 2) ** 2},
  ];
  for (const {spec, value} of cases) {
    assert.equal(api.validateGraph(spec), true);
    const p = spec.params, [xmin, xmax, ymin, ymax] = p.bounds;
    const pixelY = value => 222 - (value - ymin) / (ymax - ymin) * 174;
    const near = (actual, expected, message, tolerance = 1e-8) => assert.ok(Math.abs(actual - expected) < tolerance,
      `${message}: ${actual} versus ${expected}`);
    for (const h of [-1, 0, 0.5, 1, 2, 3]) {
      const parameter = p.parameter.scale * h + p.parameter.offset;
      const layer = api.axisExplorerLayer({...p, uid: spec.uid}, h);
      const vertex = /class="axis-vertex" cx="([^"]+)" cy="([^"]+)"/.exec(layer);
      near(Number(vertex[2]), pixelY(value(h, parameter)), `${p.parameter.name}=${parameter} vertex`);
      const endpoints = [...layer.matchAll(/class="axis-endpoint[^"]*" cx="([^"]+)" cy="([^"]+)"/g)];
      for (const [i, endpoint] of endpoints.entries()) near(Number(endpoint[2]), pixelY(value(p.interval[i], parameter)), 'endpoint');
      const path = /class="quadratic-curve" d="([^"]+)"/.exec(layer)[1];
      for (const [, px, py] of path.matchAll(/[ML](-?[\d.]+) (-?[\d.]+)/g)) {
        const x = xmin + (Number(px) - 48) / 270 * (xmax - xmin);
        near(Number(py), pixelY(value(x, parameter)), 'curve point matches the parameterized function', 0.02);
      }
      assert.match(layer, new RegExp(`>${p.target === 'min' ? '最低' : '最高'}<`));
      assert.match(layer, new RegExp(`对称轴 ${p.variable} = ${h}；${p.parameter.name} = `));
    }
  }
  const original = api.graph(parameterAxis());
  assert.match(original, /data-axis-layer[^]*class="axis-value-label"[^>]*>对称轴 x = 1；m = 2<\/text>/);
  const noParameter = parameterAxis();
  delete noParameter.params.parameter;
  assert.match(api.graph(noParameter), /对称轴 x = 1<\/text>/, 'moving constants can be rendered without parameter metadata');
});

test('axis explorer extension is optional, escaped and validated before rendering', () => {
  const {context} = engine(), api = context.PracticeComponents;
  const legacy = parameterAxis();
  delete legacy.params.constant_by_axis;
  delete legacy.params.parameter;
  const explicitZero = {...legacy, params: {...legacy.params, constant_by_axis: {linear: 0, quadratic: 0}}};
  const layer = spec => api.axisExplorerLayer({...spec.params, uid: spec.uid}, 1);
  assert.equal(api.validateGraph(legacy), true);
  assert.doesNotMatch(layer(legacy), /axis-value-label/);
  const drawings = html => [...html.matchAll(/<(?:path|circle)\b[^>]*>/g)].map(match => match[0]);
  assert.deepEqual(drawings(layer(legacy)), drawings(layer(explicitZero)), 'zero extra terms keep every legacy curve and marker coordinate');
  const label = '<img src=x onerror="alert(1)">';
  const escaped = parameterAxis({parameter: {name: label, scale: -1, offset: 2}, variable: 't<&'});
  const html = api.graph(escaped);
  assert.match(html, /对称轴 t&lt;&amp; = 1；&lt;img src=x onerror=&quot;alert\(1\)&quot;&gt; = 1/);
  assert.doesNotMatch(html, /<img|onerror="/);
  for (const [field, invalid] of [
    ['constant_by_axis', [null, [], 2, {}, {linear: 1}, {quadratic: 1}, {linear: '1', quadratic: 0},
      {linear: Infinity, quadratic: 0}, {linear: 0, quadratic: NaN}, {linear: 0, quadratic: 0, expression: 'h'}]],
    ['parameter', [null, [], 'm', {}, {name: 'm', scale: 2}, {name: 'm', offset: 0}, {scale: 2, offset: 0},
      {name: '', scale: 2, offset: 0}, {name: 3, scale: 2, offset: 0}, {name: 'm', scale: 0, offset: 0},
      {name: 'm', scale: '2', offset: 0}, {name: 'm', scale: Infinity, offset: 0},
      {name: 'm', scale: 2, offset: NaN}, {name: 'm', scale: 2, offset: 0, expression: '2*h'}]],
  ]) for (const value of invalid) {
    const bad = parameterAxis({[field]: value});
    assert.equal(api.validateGraph(bad), false, `${field}: ${JSON.stringify(value)}`);
    assert.equal(api.graph(bad), '', 'invalid metadata falls back to the original answer labels');
  }
});

test('mounted parameter explorers update values during drag and stay on their case tracks', () => {
  const {context, run} = engine();
  const mounted = spec => {
    const events = {}, layer = {}, input = {value: spec.params.axis.value,
      addEventListener: (name, callback) => { events[name] = callback; }};
    const svg = {getBoundingClientRect: () => ({left: 0, width: 360}),
      addEventListener: (name, callback) => { events[name] = callback; },
      setPointerCapture(id) { this.pointer = id; }, hasPointerCapture(id) { return this.pointer === id; }};
    const host = {dataset: {graph: JSON.stringify(spec)}, querySelector: selector =>
      selector === '[data-axis-layer]' ? layer : selector === '[data-axis-input]' ? input : svg};
    context.axisTestHost = host;
    run('mountAxisExplorer(axisTestHost)');
    return {events, layer, input};
  };
  const whole = mounted(parameterAxis());
  whole.input.value = '1.5'; whole.events.input();
  assert.match(whole.layer.innerHTML, /对称轴 x = 1.5；m = 3/);
  whole.events.pointerdown({clientX: 48, pointerId: 1});
  assert.equal(whole.input.value, -1);
  assert.match(whole.layer.innerHTML, /对称轴 x = -1；m = -2/);
  const remounted = mounted(parameterAxis());
  assert.equal(remounted.input.value, -1, 'a redraw restores both the axis position and the parameter value');
  assert.match(remounted.layer.innerHTML, /m = -2/);
  for (const [index, [min, max]] of [[-1, 0], [0, 2], [2, 3]].entries()) {
    const spec = {...parameterAxis({axis: {min, max, step: 0.1, value: min}}), uid: `case-axis-${index}`};
    const current = mounted(spec);
    current.events.pointerdown({clientX: -100, pointerId: 1});
    assert.equal(current.input.value, min);
    current.events.pointermove({clientX: 1000, pointerId: 1});
    assert.equal(current.input.value, max);
    assert.match(current.layer.innerHTML, new RegExp(`对称轴 x = ${max}；m = ${2 * max}`));
  }
});

test('explicit question boards remain visible without frozen derivation inputs', () => {
  const board = {caption: '各情况各自要满足', lines: ['① $a\\le-1$：$g(x)_{\\min}\\ge0$', '② $a>-1$：$1\\ge0$']};
  const {run, roots} = engine(fixture({parts: [{...part('first'), stem_board: board}]}));
  run('renderInteraction(currentDecision(bundle,state))');
  const active = roots.get('#gw-active');
  assert.match(active.innerHTML, /<div class="visual-board gw-question-board"><div class="board-caption">各情况各自要满足<\/div>/);
  assert.match(active.innerHTML, /<p class="case-line" data-math-text>① \$a\\le-1\$：/);
  assert.doesNotMatch(active.innerHTML, /data-stream-context/);
  assert.doesNotMatch(active.textContent, /before-1/);
});

test('case pictures are the conclusion; the math card mounts open under them; one bad picture drops the set', () => {
  const panel = (min, max, caption) => ({kind: 'axis_explorer', caption, params: {bounds: [-0.44, 0.95, -0.23, 1.77],
    xTicks: [[0, '0'], [0.5, '1/2']], variable: 'x', points: [], interval: [0, 0.5], interval_closed: [false, true],
    title: caption, description: caption, coefficient: 1, constant: 1, marks: [], target: 'min',
    axis: {min, max, step: 0.01, value: min}}});
  const cases = [panel(0.5, 0.8, '情况①：最小值在右端点'), panel(-0.29, 0, '情况②：最小值取不到')];
  const finish = (graphs, card = {}) => {
    const {run, roots} = engine(fixture({parts: [part('first'), {...part('last'), completion_graphs: graphs}]}));
    run(`bundle.stream.math_steps.forEach(step => Object.assign(step, ${JSON.stringify(card)}));
      state = studentState = submitAnswer(bundle,state,{decision:'first',answer:'yes'});
      state = studentState = submitAnswer(bundle,state,{decision:'last',answer:'yes'});
      document.querySelector('#gw-steps').innerHTML=completedHTML(state.run.completed.at(-1),6,1,'discriminant'); mountCompletedMath();`);
    const steps = roots.get('#gw-steps');
    return {html: steps.innerHTML, host: steps.querySelector('[data-stream-completed]')};
  };
  const shown = finish(cases, {derivation: true, explanation: '① 当 $a\\le-1$ 时最小值在右端点。\n② 当 $a\\ge0$ 时取不到。', highlight: undefined});
  assert.match(shown.html, /<div class="gw-case-figures">(?:<figure[^]*?<\/figure>){2}<\/div>/);
  assert.match(shown.html, /情况①：最小值在右端点[^]*情况②：最小值取不到/);
  assert.doesNotMatch(shown.html, /gw-derivation|各情况的最小值/);
  const card = shown.host.children[0];
  assert.equal(card.tagName, 'article');
  const details = card.querySelector?.('details') || card.children.find(child => child.tagName === 'details');
  assert.equal(details.open, true, 'the derivation under the pictures starts open');
  assert.match(details.textContent, /完整推导/);
  assert.match(details.textContent, /最小值在右端点/);
  const broken = finish([cases[0], {...cases[1], params: {...cases[1].params, axis: {min: 1, max: 0, step: 0.01, value: 0}}}]);
  assert.doesNotMatch(broken.html, /gw-case-figures/);
  assert.match(broken.host.textContent, /secret-after-1/);
});

test('completed opening parts keep their pictures under separate direction headings', () => {
  const up = [1, 0, -1].map(height => ({...quadratic, params: {...quadratic.params, vertex: [0, height]}}));
  const down = {...quadratic, params: {...quadratic.params, coefficient: -1}};
  const value = fixture({parts: [
    {...part('up'), completion_group: '开口向上', completion_graphs: up},
    {...part('down'), completion_group: '开口向下', completion_graph: down},
  ]});
  assert.deepEqual(value.bundle.routes.discriminant.steps.map(part => part.completion_group), ['开口向上', '开口向下']);
  const {run, roots} = engine(value);
  run(`state = studentState = submitAnswer(bundle,state,{decision:'up',answer:'yes'});
    state = studentState = submitAnswer(bundle,state,{decision:'down',answer:'yes'});
    renderStory = () => {}; revealStep = () => {}; realRender();`);
  const steps = roots.get('#gw-steps');
  const groups = [...steps.innerHTML.matchAll(/<section class="gw-completion-group" aria-labelledby="([^"]+)">([\s\S]*?)<\/section>/g)];
  assert.equal(groups.length, 2);
  assert.deepEqual(groups.map(group => /<h3[^>]+>([^<]*)<\/h3>/.exec(group[2])[1]), ['开口向上', '开口向下']);
  assert.deepEqual(groups.map(group => (group[2].match(/class="gw-figure gw-completion-graph"/g) || []).length), [3, 1]);
  assert.ok(groups.every(group => group[1] === /<h3 id="([^"]+)">/.exec(group[2])[1]));
  assert.equal(steps.querySelectorAll('svg').length, 4, 'all grouped pictures still hydrate in the normal render');
  assert.equal(steps.querySelectorAll('[data-stream-completed]').length, 1);
});

test('a rejected opening retains its answer under an escaped direction heading without a picture', () => {
  const title = '开口向下 <img src=x onerror="bad()">';
  const value = fixture({parts: [{...part('rejected'), completion_group: title}]});
  value.bundle.routes.discriminant.steps[0].interaction.options[0].label = '此开口不适合';
  const {run, roots} = engine(value);
  run(`state = studentState = submitAnswer(bundle,state,{decision:'rejected',answer:'yes'});
    renderStory = () => {}; revealStep = () => {}; realRender();`);
  const html = roots.get('#gw-steps').innerHTML;
  assert.match(html, /<section class="gw-completion-group"[^>]*><h3[^>]*>开口向下 &lt;img src=x onerror=&quot;bad\(\)&quot;&gt;<\/h3>/);
  assert.doesNotMatch(html, /<img\b|class="gw-figure/);
  assert.match(html, /<p class="gw-answer" data-math-text>此开口不适合<\/p><\/section>/);
});

for (const count of [1, 2]) test(`${count} completion picture(s) replace only the opted-in board after successful drawing and recover on failure`, () => {
  const pictures = Array.from({length: count}, (_, index) => ({...quadratic, caption: `图 ${index + 1}`}));
  const pictured = {...part('last'), ...(count === 1 ? {completion_graph: pictures[0]} : {completion_graphs: pictures})};
  const value = fixture({parts: [pictured], merged: true});
  for (const step of value.bundle.stream.math_steps) step.highlight = {caption: `结论 ${step.ordinal}`,
    ...(step.ordinal === 1 ? {replace_with_graph: true} : {}), items: [{label: '结论', math: step.after[0].latex}]};
  const {context, run, roots} = engine(value);
  run(`state = studentState = submitAnswer(bundle,state,{decision:'last',answer:'yes'});
    renderStory = () => {}; revealStep = () => {};
    document.querySelector('#gw-steps').innerHTML=completedHTML(state.run.completed.at(-1),5,1,'discriminant'); mountCompletedMath();`);
  const [opening, range] = [...run('streamCards.values()')];
  assert.equal(opening.conclusion.hidden, false, 'a valid graph specification is not yet a rendered conclusion');
  run('realRender()');
  const graphs = () => roots.get('#gw-steps').querySelectorAll('.gw-completion-graph');
  assert.equal(graphs().length, count);
  assert.ok(graphs().every(figure => figure.querySelector('svg')));
  assert.equal(opening.conclusion.hidden, true, 'the normal render cycle mounts cards after drawing');
  assert.equal(range.conclusion.hidden, false, 'a separate range result stays beside the image');
  assert.equal(opening.node.querySelector('.stage-three-derivation').open, true);
  assert.match(opening.node.querySelector('.stage-three-derivation').textContent, /secret-explanation-1/);

  graphs()[0].querySelector('[data-graph-rendered]').replaceChildren();
  run('mountCompletedMath()');
  assert.equal(opening.conclusion.hidden, false, 'a rendered flag without SVG cannot hide the fallback');

  const draw = context.PracticeComponents.graph;
  context.PracticeComponents.graph = spec => {
    if (spec.caption === `图 ${count}`) throw new Error('drawing unavailable');
    return draw(spec);
  };
  run('realRender()');
  assert.equal(graphs().length, count - 1, 'failed picture is removed by hydration');
  assert.equal(opening.conclusion.hidden, false, 'a partial set of case pictures does not replace the complete conclusion');
  assert.equal(range.conclusion.hidden, false);
  context.PracticeComponents.graph = draw;
  run('realRender()');
  assert.equal(opening.conclusion.hidden, true, 'a later redraw can replace the fallback without rebuilding the math card');
  assert.equal([...run('streamCards.values()')][0], opening);
});

test('a folded earlier conclusion is not replaced by another step’s completion picture', () => {
  const value = fixture({parts: [{...part('last'), completion_graph: quadratic}], folded: true});
  for (const step of value.bundle.stream.math_steps) step.highlight = {caption: step.title,
    replace_with_graph: true, items: [{label: '结论', math: step.after[0].latex}]};
  const {run} = engine(value);
  run(`state = studentState = submitAnswer(bundle,state,{decision:'last',answer:'yes'});
    renderStory = () => {}; revealStep = () => {}; realRender();`);
  const cards = [...run('streamCards.values()')];
  assert.equal(cards.find(card => card.step.step_id === 'math-2').conclusion.hidden, true);
  assert.equal(cards.find(card => card.step.step_id === 'math-1').conclusion.hidden, false);
});

test('strict linear plots distinguish small nonzero values from a line lying on the axis', () => {
  const {context} = engine();
  // The boundary builder for x*(a+1/10^13)>0 on (0,1], at a=0,
  // produces these exact drawing parameters: its positive segment must stay green.
  const params = {bounds: [-0.25, 1.25, -0.25, 0.25], xTicks: [[0, '0'], [1, '1']], variable: 'x',
    interval: [0, 1], interval_closed: [false, true], points: [{x: 0, open: true}, {x: 1}],
    title: '边界处的函数', description: '只看区间 (0,1]'};
  const cases = [[1e-13, 0, 1], [-1e-13, 0, -1], [0, 1e-13, 1], [0, -1e-13, -1], [0, 0, 0]];
  for (const [slope, intercept, sign] of cases) for (const strict of [false, true]) for (const markSign of ['below', 'above']) {
    const graph = {kind: 'linear', uid: 'small-linear', params: {...params, slope, intercept, strict, markSign}};
    const svg = context.PracticeComponents.graph(graph), name = `${slope}*x+${intercept}, ${markSign}, strict=${strict}`;
    const violates = sign === 0 ? strict : markSign === 'below' ? sign < 0 : sign > 0;
    assert.match(svg, /class="linear-line"/, name);
    assert.equal((svg.match(/<path class="linear-(?:negative|positive)"/g) || []).length, violates ? 1 : 0, name);
    if (slope) assert.match(svg, new RegExp(`class="linear-root"[^>]*stroke="${strict ? '#c4553f' : '#08655f'}"`), 'isolated roots retain their strictness mark');
  }
});

test('one invalid or missing option picture restores every label and keeps answers and decisions intact', () => {
  for (const type of ['choice', 'multi']) for (const bad of [undefined, {kind: 'unknown', params: {}}, {kind: 'quadratic', params: {bounds: [-1, 1]}}]) {
    const pictured = {...part('last', type), graph: bad, completion_graph: bad};
    pictured.interaction.options[0].graph = quadratic;
    pictured.interaction.options[1].graph = bad;
    if (type === 'multi') pictured.expected_answer = {required: ['yes'], allowed: ['yes']};
    const {run, roots, value} = engine(fixture({parts: [pictured]}));
    const before = JSON.stringify(value.bundle);
    run(`draft = ${type === 'multi' ? "['yes']" : "'yes'"}; draftKey = decisionKey(currentDecision(bundle,state)); renderInteraction(currentDecision(bundle,state));`);
    const html = roots.get('#gw-active').innerHTML;
    assert.doesNotMatch(html, /data-graph=|data-quadratic-graph=|gw-stem-graph/);
    assert.match(html, /<span data-math-text>成立<\/span>/);
    assert.match(html, /<span data-math-text>不成立<\/span>/);
    assert.match(html, /data-(?:value|multi)="yes"[^>]*aria-pressed="true"/);
    run(`state = studentState = submitAnswer(bundle,state,{decision:'last',answer:draft})`);
    assert.equal(run('state.lastFeedback.status'), 'passed');
    assert.equal(run('state.run.completed.length'), 1);
    assert.doesNotMatch(run(`completedHTML(state.run.completed.at(-1),5,1,'discriminant')`), /gw-completion-graph/);
    assert.equal(JSON.stringify(value.bundle), before, 'fallback never edits the verified decision data');
  }
});

test('streamed stem, option and completion pictures render beside the question and the finished card', () => {
  const options = [
    {value: 'yes', label: '$[-5/2,-1]$', graph: line([{from: -2.5, to: -1, left_closed: true, right_closed: true}], '[-5/2, -1]')},
    {value: 'no', label: '$(-5/2,-1]$', graph: line([{from: -2.5, to: -1, left_closed: false, right_closed: true}], '(-5/2, -1]')}];
  options[0].graph.caption = '示意图：取 $a=-1$，只看 $x\\le1$';
  const pictured = {...part('last'), graph: quadratic, completion_graph: {...quadratic, caption: '完成图'}};
  pictured.interaction = {...pictured.interaction, options};
  const {run, roots} = engine(fixture({parts: [pictured]}));
  run('renderInteraction(currentDecision(bundle,state))');
  const html = roots.get('#gw-active').innerHTML;
  assert.match(html, /<figure class="gw-figure gw-stem-graph"><span class="gw-figure-plot" data-graph="[^"]*&quot;kind&quot;:&quot;quadratic&quot;/);
  assert.match(html, /<figcaption data-math-text>示意图：取 \$a=0\$<\/figcaption>/);
  assert.match(html, /class="gw-graph-options"[^>]*data-count="2" data-kind="number_line"/);
  assert.equal((html.match(/class="gw-graph-figure" data-graph=/g) || []).length, 2);
  assert.match(html, /<span class="gw-graph-option-caption" data-math-text>示意图：取 \$a=-1\$，只看 \$x\\le1\$<\/span>/,
    'sample values must remain visible on clickable graph options, not only in SVG accessibility text');
  assert.doesNotMatch(html, /data-quadratic-graph/);
  assert.doesNotMatch(html, /完成图/, 'the completion picture waits for the answer');
  run(`state = studentState = submitAnswer(bundle,state,{decision:'last',answer:'yes'})`);
  const done = run(`completedHTML(state.run.completed.at(-1),5,1,'discriminant')`);
  assert.match(done, /<figure class="gw-figure gw-completion-graph">[\s\S]*完成图[\s\S]*data-stream-completed/);
});

test('read presents the full card and advances through the normal answer state machine', () => {
  const {run, roots} = engine(fixture({readonly: true}));
  run('renderInteraction(currentDecision(bundle,state))');
  assert.equal(run('draft'), 'read');
  assert.match(roots.get('#gw-active').innerHTML, /读完了，下一步/);
  assert.match(roots.get('#gw-active').textContent, /secret-after-1/);
  run(`state = submitAnswer(bundle,state,{decision:currentDecision(bundle,state).id,answer:draft})`);
  assert.equal(run('state.lastFeedback.status'), 'passed');
  assert.equal(run('state.done'), true);
});

for (const failure of ['route', 'goal']) test(`a stopped ${failure} keeps its committed math readable without reopening practice or QA`, () => {
  const value = fixture({merged: true});
  value.state = stateAPI.submitAnswer(value.bundle, value.state, {decision: 'first', answer: 'yes'});
  if (failure === 'route') value.view.route_statuses = [[JSON.stringify([target, routes[0]]), {status: 'capability_gap'}]];
  else value.view.goals[target] = {status: 'conflict', available: false};
  value.bundle = stateAPI.extendStreamBundle(base, value.view, target, graph);
  value.state = stateAPI.refreshStreamState(value.bundle, value.state);
  const {run, roots} = engine(value);
  assert.equal(run('currentDecision(bundle,state)'), null);
  run(`document.querySelector('#gw-steps').innerHTML = waitingHTML(6); mountRetainedMath();`);
  const steps = roots.get('#gw-steps');
  assert.match(steps.innerHTML, /此路线暂不可用/);
  assert.match(steps.textContent, /secret-after-1.*secret-explanation-1.*secret-after-2/);
  assert.equal(steps.querySelectorAll('.stage-three-math-step').length, 2);
  assert.ok(steps.querySelectorAll('.stage-three-qa').every(node => node.hidden));
  assert.equal(run('visibleStreamCards.size'), 0, 'retained cards never receive late QA');
  assert.equal(run('state.done'), false);
});

test('stream undo stays disabled until the chosen route has an answer to rewind', () => {
  const {run, roots} = engine(fixture());
  run(`busy = false; renderStory = () => {}; revealStep = () => {}; realRender();`);
  assert.equal(roots.get('#gw-undo').disabled, true);
  run(`state = studentState = submitAnswer(bundle,state,{decision:'first',answer:'yes'}); realRender();`);
  assert.equal(roots.get('#gw-undo').disabled, false);
});

test('undo after restoring a multipart card rewinds one question and persists across stream updates', async () => {
  const value = fixture({parts: [part('location'), part('value'), part('condition'), part('range')]});
  const first = engine(value);
  first.run(`state = studentState = submitAnswer(bundle,state,{decision:'location',answer:'yes'}); render();`);
  const persisted = [...first.storage.entries()].find(([key]) => key.startsWith('search-progress:v1:student-a:submission:walk:'));
  assert.ok(persisted, 'park wrote the real progress serializer');
  // Start a new engine, whose in-memory event history and saved map are empty.
  const {run, storage} = engine(value);
  storage.set(...persisted);
  run(`restored = savedProgress(bundle);
    state = studentState = refreshStreamState(bundle, restored.studentState);
    keptDraft = restored.draft; draftKey = ''; submitted = null;
    chooseActor(restored.actor, {autoplay:false});`);
  assert.equal(run('currentDecision(bundle,state).id'), 'value');
  // Exercise exactly the button handler, including draft reset and persistence.
  const callback = source.match(/\$\('#gw-undo'\)\.addEventListener\('click', \(\) => \{([\s\S]*?)\n  \}\);/)[1];
  run(`(() => {${callback}})()`);
  assert.equal(run('currentDecision(bundle,state).id'), 'location');
  assert.equal(run('state.run.completed.length'), 0);
  assert.equal(run('studentState.run.completed.length'), 0);
  assert.equal(run('draft'), null);
  await run('updateStreamSelection(fixture.view)');
  assert.equal(run('currentDecision(bundle,state).id'), 'location');
  run(`state = studentState = refreshStreamState(bundle,
    JSON.parse(localStorage.getItem(storedProgressKey(bundle,bundleScope))).studentState);`);
  assert.equal(run('currentDecision(bundle,state).id'), 'location');
});

for (const field of ['target_ref', 'run_id', 'lesson_version']) test(`changing ${field} ${field === 'target_ref' ? 'keeps' : 'drops'} cached cards and QA`, async () => {
  const {run, context, value} = engine(fixture({parts: [part('last')]}));
  run(`state = studentState = submitAnswer(bundle,state,{decision:'last',answer:'yes'});
    document.querySelector('#gw-steps').innerHTML=completedHTML(state.run.completed.at(-1),5,1,'discriminant'); mountCompletedMath();
    bind = () => {}; bound = true; load = async () => {};`);
  context.chunk = {...value.view.math_steps[0], verified_route_sha256: 'discriminant-verified', qa: {questions: ['q']}};
  run('attachStreamQA(chunk)');
  assert.equal(run('streamCards.size'), 1);
  assert.equal(run('streamQA.size'), 1);
  context.next = {...run('options.stream'), [field]: field === 'target_ref' ? '/root/goals/1' : `next-${field}`};
  await run('mountWalk({stream: next})');
  const kept = field === 'target_ref' ? 1 : 0;
  assert.equal(run('streamCards.size'), kept);
  assert.equal(run('streamQA.size'), kept);
});

test('late QA is cached until completion, is idempotent, and preserves math DOM across attachment and remount', () => {
  const {run, context, roots, value} = engine(fixture({parts: [part('last')]}));
  context.chunk = {...value.view.math_steps[0], verified_route_sha256: 'discriminant-verified', qa: {questions: ['late question']}};
  run('attachStreamQA(chunk)');
  assert.equal(run('streamCards.size'), 0);
  run(`state = studentState = submitAnswer(bundle,state,{decision:'last',answer:'yes'});
    document.querySelector('#gw-steps').innerHTML=completedHTML(state.run.completed.at(-1),5,1,'discriminant'); mountCompletedMath();`);
  const cardNode = roots.get('#gw-steps').querySelector('.stage-three-math-step');
  const beforeNode = cardNode.querySelector('.stage-three-before'), qaNode = cardNode.querySelector('.stage-three-qa');
  const question = qaNode.children[1];
  assert.match(qaNode.textContent, /late question/);
  run('attachStreamQA(chunk); mountCompletedMath()');
  assert.equal(roots.get('#gw-steps').querySelector('.stage-three-math-step'), cardNode);
  assert.equal(cardNode.querySelector('.stage-three-before'), beforeNode);
  assert.equal(qaNode.children[1], question, 'identical QA does not replace its own region either');
  assert.throws(() => run(`attachStreamQA({...chunk,qa:{questions:['changed']}})`), /immutable_qa/);
  run(`attachStreamQA({...chunk,run_id:'other',qa:{questions:['wrong run']}})`);
  assert.doesNotMatch(qaNode.textContent, /wrong run|changed/);
  run(`streamView.goals[bundle.stream.target_ref]={available:false}; mountCompletedMath()`);
  assert.equal(qaNode.hidden, true);
  assert.equal(run('renderCount'), 0, 'QA attachment never rerenders the walk');
});

for (const field of ['run_id', 'lesson_version']) test(`completion rendering and QA ignore raw completion from another ${field}`, () => {
  const value = fixture({parts: [part('last')]});
  value.view.completions = value.view.completions.map(completion => ({...completion, [field]: 'old'}));
  value.bundle = stateAPI.extendStreamBundle(base, value.view, target, graph);
  const {run, context, roots} = engine(value);
  context.chunk = {...value.view.math_steps[0], verified_route_sha256: 'discriminant-verified',
    qa: {questions: ['must stay hidden']}};
  run(`state = studentState = submitAnswer(bundle,state,{decision:'last',answer:'yes'});
    document.querySelector('#gw-steps').innerHTML=completedHTML(state.run.completed.at(-1),5,1,'discriminant');
    mountCompletedMath(); attachStreamQA(chunk);`);
  assert.equal(run('streamCompletion(state.run.route)'), null);
  assert.equal(run('state.done'), false);
  assert.equal(roots.get('#gw-steps').querySelector('.stage-three-qa').hidden, true);
  assert.equal(run('availableQA(bundle.stream.math_steps[0])'), null);
});

test('a same-run partial update retains the normalized completion and its late QA', async () => {
  const {run, context, roots, value} = engine(fixture({parts: [part('last')]}));
  context.chunk = {...value.view.math_steps[0], verified_route_sha256: 'discriminant-verified',
    qa: {questions: ['retained answer explanation']}};
  run(`state = studentState = submitAnswer(bundle,state,{decision:'last',answer:'yes'});
    document.querySelector('#gw-steps').innerHTML=completedHTML(state.run.completed.at(-1),5,1,'discriminant');
    mountCompletedMath(); attachStreamQA(chunk);`);
  const qa = roots.get('#gw-steps').querySelector('.stage-three-qa');
  context.partial = {...value.view}; delete context.partial.completions;
  await run('updateStreamSelection(partial)');
  run('mountCompletedMath()');
  assert.equal(run('streamCompletion(state.run.route).verified_route_sha256'), 'discriminant-verified');
  assert.equal(run('state.done'), true);
  assert.equal(qa.hidden, false);
  assert.match(qa.textContent, /retained answer explanation/);
  assert.equal(run('renderCount'), 0, 'omitted raw completion data does not replace the normalized result');
});

test('a late available handoff refreshes completion and already cached QA after a verified checkpoint', async () => {
  const value = fixture({parts: [part('last')]});
  const completion = value.view.completions[0];
  delete value.view.completions;
  value.view.checkpoints = [{target_ref: target, route_id: routes[0], status: 'verified'}];
  value.bundle = stateAPI.extendStreamBundle(base, value.view, target, graph);
  const {run, context, roots} = engine(value);
  context.chunk = {...value.view.math_steps[0], verified_route_sha256: 'discriminant-verified',
    qa: {questions: ['cached before handoff']}};
  run(`state = studentState = submitAnswer(bundle,state,{decision:'last',answer:'yes'});
    document.querySelector('#gw-steps').innerHTML=completedHTML(state.run.completed.at(-1),5,1,'discriminant');
    mountCompletedMath(); attachStreamQA(chunk);
    render = () => { renderCount++; mountCompletedMath(); };`);
  const qa = roots.get('#gw-steps').querySelector('.stage-three-qa');
  assert.equal(run('state.done'), true);
  assert.equal(run('streamCompletion(state.run.route)'), null);
  assert.equal(qa.hidden, true);
  context.updated = {...value.view, handoffs: [{...identity, ...completion,
    target_ref: target, route_id: routes[0], status: 'pending', available: true}]};
  await run('updateStreamSelection(updated)');
  assert.equal(run('renderCount'), 1, 'the normalized completion changed although steps and route status did not');
  assert.equal(run('streamCompletion(state.run.route).verified_route_sha256'), 'discriminant-verified');
  assert.equal(qa.hidden, false);
  assert.match(qa.textContent, /cached before handoff/);
});

test('stream revisions refresh waiting/completion and retain an unchanged fill draft and selected slot', async () => {
  const value = fixture({parts: [part('first', 'fill')]}), {run, context} = engine(value);
  run(`ensureDraft(currentDecision(bundle,state)); draft=['no']; selectedSlot=0;`);
  const updated = structuredClone(value.view);
  updated.route_statuses = [[JSON.stringify([target, routes[0]]), {status: 'running'}]];
  updated.completions = []; updated.checkpoints = [{target_ref: target, route_id: routes[0], status: 'running'}];
  context.updated = updated;
  await run('updateStreamSelection(updated)');
  assert.equal(run('JSON.stringify(draft)'), '["no"]');
  assert.equal(run('selectedSlot'), 0);
  assert.equal(run('renderCount'), 1);
  run(`state = studentState = submitAnswer(bundle,state,{decision:'first',answer:['yes']});`);
  await run('updateStreamSelection(updated)');
  assert.equal(run('state.done'), false);
  assert.match(run('waitingHTML(6)'), /正在准备这一步的练习/);
  context.finished = value.view;
  await run('updateStreamSelection(finished)');
  assert.equal(run('state.done'), true);
});

test('routes retain independent drafts and selected fill slots, including persisted student state', () => {
  const {run, storage} = engine(fixture({parts: [part('first', 'fill')]}));
  run(`ensureDraft(currentDecision(bundle,state)); draft=['no']; selectedSlot=0;
    chooseStreamRoute('extremum'); draft=['yes']; selectedSlot=null; chooseStreamRoute('discriminant');`);
  assert.equal(run('JSON.stringify(draft)'), '["no"]');
  assert.equal(run('selectedSlot'), 0);
  run('park()');
  const saved = JSON.parse([...storage.values()].at(-1));
  assert.equal(saved.studentState.streamRoutes.extremum.draft.answer[0], 'yes');
  assert.equal(saved.studentState.streamRoutes.discriminant.draft.selectedSlot, 0);
  run(`state = studentState = refreshStreamState(bundle,JSON.parse(localStorage.getItem(storedProgressKey(bundle,bundleScope))).studentState);
    draftKey=''; draft=null; selectedSlot=null; ensureDraft(currentDecision(bundle,state));`);
  assert.equal(run('JSON.stringify(draft)'), '["no"]');
  assert.equal(run('selectedSlot'), 0);
});

test('AI route replay uses expected answers without completing or overwriting the student route', () => {
  const {run, context} = engine(fixture({parts: [part('first', 'fill')]}));
  const scheduled = [];
  context.setTimeout = callback => { scheduled.push(callback); return scheduled.length; };
  context.introActions = run('state.events.map(event=>event.action).filter(action=>action.decision!=="D3")');
  run(`options.replay={actions:introActions}; ensureDraft(currentDecision(bundle,state)); draft=['no']; selectedSlot=0;
    chooseActor('replay');`);
  while (scheduled.length) scheduled.shift()();
  assert.equal(run('state.done'), true);
  assert.equal(run('studentState.run.completed.length'), 0);
  run(`chooseStreamRoute('extremum'); replayPosition=3; park(); chooseActor('student');`);
  assert.equal(run('state.run.route'), 'discriminant');
  assert.equal(run('JSON.stringify(draft)'), '["no"]');
  assert.equal(run('selectedSlot'), 0);
  run(`chooseActor('replay')`);
  assert.equal(run('state.run.route'), 'extremum');
  assert.equal(run('replayPosition'), 3);
  assert.equal(run('state.done'), false);
});

test('same problem ID keeps distinct parked progress per subquestion and run even without browser storage', () => {
  const {run, context, value} = engine(fixture({parts: [part('first', 'fill')]}));
  context.other = structuredClone(value.bundle);
  context.other.bundleVersion += '-sibling-goal'; context.other.stream.target_ref = '/root/goals/1';
  context.newRun = structuredClone(value.bundle);
  context.newRun.bundleVersion += '-new-run'; context.newRun.stream.run_id = 'new-run';
  run(`localStorage.setItem=()=>{throw new Error('storage unavailable')};
    ensureDraft(currentDecision(bundle,state)); draft=['no']; selectedSlot=0; park();
    bundle=other; state=studentState=createState(bundle); draftKey=''; park();
    bundle=newRun; state=studentState=createState(bundle); draftKey=''; park();`);
  assert.equal(run('saved.size'), 3);
  assert.equal(run('savedProgress(fixture.bundle).studentState.streamDraft.answer[0]'), 'no');
  assert.equal(run('savedProgress(fixture.bundle).studentState.streamDraft.selectedSlot'), 0);
  assert.equal(run('savedProgress(other).studentState.introCompleted.length'), 0);
  assert.equal(run('savedProgress(newRun).studentState.introCompleted.length'), 0);
});

test('changing account scopes never saves the previous bundle under the next account', () => {
  const {run, storage} = engine(fixture({parts: [part('first', 'fill')]}));
  run(`ensureDraft(currentDecision(bundle,state)); draft=['no']; selectedSlot=0; park();
    options.progressScope='search-progress:v1:student-b:submission:'; park();`);
  assert.equal(run('savedProgress(bundle)'), undefined);
  assert.equal([...storage.keys()].some(key => key.startsWith('search-progress:v1:student-b:')), false);
  run(`bundleScope=options.progressScope; state=studentState=createState(bundle); draftKey=''; keptDraft=null; park();`);
  assert.equal(run('savedProgress(bundle).studentState.introCompleted.length'), 0);
  run(`options.progressScope='search-progress:v1:student-a:submission:';`);
  assert.equal(run('savedProgress(bundle).studentState.streamDraft.answer[0]'), 'no');
  assert.equal(run('savedProgress(bundle).studentState.streamDraft.selectedSlot'), 0);
});

test('legacy unscoped progress is ignored and stage-two fallback stays within the account', () => {
  const {run, storage, value} = engine(fixture());
  storage.set(`graph-walk:${value.bundle.problemId}:${value.bundle.bundleVersion}`, JSON.stringify({studentState: value.state}));
  assert.equal(run('savedProgress(bundle)'), undefined);
  run(`saved.set(progressKey({...bundle,stream:null,bundleVersion:bundle.stream.base_bundle_version},options.progressScope), {stage:'two'});`);
  assert.equal(run('savedProgress(bundle).stage'), 'two');
  run(`options.progressScope='search-progress:v1:student-b:submission:';`);
  assert.equal(run('savedProgress(bundle)'), undefined);
});

test('disposing an account cancels queued graph work and cannot rewrite cleared progress', async () => {
  const {run, storage} = engine(fixture());
  run('park()');
  assert.ok(storage.size);
  const pending = run('updateStreamSelection(fixture.view)');
  run('disposeWalk()');
  storage.clear();
  await pending;
  run('park()');
  assert.equal(storage.size, 0);
  assert.equal(run('saved.size'), 0);
  assert.equal(run('bundle'), null);
});

test('stage-two versions keep independent in-memory progress for the same search and problem', () => {
  const {run, context} = engine();
  context.first = structuredClone(base);
  context.second = {...structuredClone(base), bundleVersion: base.bundleVersion + '-next'};
  run(`bundle=first; state=studentState=createState(bundle); actor='student'; park();
    bundle=second; state=studentState=createState(bundle); actor='replay'; park();`);
  assert.equal(run('saved.size'), 2);
  assert.equal(run('savedProgress(first).actor'), 'student');
  assert.equal(run('savedProgress(second).actor'), 'replay');
});

test('disposing during AI playback cannot rewrite already-deleted local progress', () => {
  const {run, storage} = engine();
  run(`park(); actor='replay'; replay=streamReplay(); replayPlaying=true; stopReplay=realStopReplay;`);
  storage.clear();
  run('disposeWalk()');
  assert.equal(storage.size, 0);
  assert.equal(run('saved.size'), 0);
});

test('late graph construction is destroyed after disposal without restoring the graph', async () => {
  const {run, context, storage} = engine();
  let resolve;
  context.pendingGraph = new Promise(done => { resolve = done; });
  run('createGraph=()=>pendingGraph');
  const installing = run('installGraph()');
  run('disposeWalk()');
  storage.clear();
  let destroyed = 0;
  resolve({destroy() { destroyed++; }});
  assert.equal(await installing, false);
  assert.equal(destroyed, 1);
  assert.equal(run('graph'), null);
  assert.equal(storage.size, 0);
});

test('late graph mode switches cannot replace a newer mounted graph', async () => {
  const {run, context} = engine();
  let resolve;
  context.pendingGraph = new Promise(done => { resolve = done; });
  run(`createGraph=()=>pendingGraph; mountCaption=()=>{};`);
  const switching = run('switchGraphMode()');
  let staleDestroyed = 0, currentDestroyed = 0;
  context.newGraph = {destroy() { currentDestroyed++; }};
  run('createGraph=async()=>newGraph');
  assert.equal(await run('installGraph()'), true);
  resolve({destroy() { staleDestroyed++; }});
  await switching;
  assert.equal(run('graph'), context.newGraph);
  assert.equal(staleDestroyed, 1);
  assert.equal(currentDestroyed, 0);
});

test('a pending load cannot render the old bundle while a new account mount waits for stream work', async () => {
  const {run, context} = engine();
  let releaseLayout, releaseQueue;
  context.layout = new Promise(done => { releaseLayout = done; });
  context.queue = new Promise(done => { releaseQueue = done; });
  context.publicFixture = graph;
  run(`publicGraph=publicFixture; withLayout=()=>layout; bound=true;`);
  const loading = run('load()');
  run('streamUpdateQueue=queue');
  const mounting = run(`mountWalk({progressScope:'search-progress:v1:student-b:submission:'})`);
  releaseLayout(run('bundle'));
  await loading;
  assert.equal(run('bundleScope'), 'search-progress:v1:student-a:submission:');
  assert.equal(run('renderCount'), 0);
  run('disposeWalk()');
  releaseQueue();
  await mounting;
});

test('queued stream work is discarded even when a new account uses the same public run identity', async () => {
  const {run, context} = engine();
  let release;
  context.queue = new Promise(done => { release = done; });
  run('streamUpdateQueue=queue; applied=0; applyStreamSelection=()=>{applied++}');
  const updating = run('updateStreamSelection(fixture.view)');
  run(`mountTicket++; options.progressScope='search-progress:v1:student-b:submission:'`);
  release();
  await updating;
  assert.equal(run('applied'), 0);
});

test('an already-queued submit animation cannot clear the next mount draft or persist it', () => {
  const {run, context, storage} = engine(fixture({parts: [part('first')]}));
  let callback;
  context.setTimeout = task => { callback = task; return 1; };
  run(`ensureDraft(currentDecision(bundle,state)); draft='yes'; submit();`);
  assert.equal(typeof callback, 'function');
  run(`loadTicket++; draftKey='new-account-draft'; busy=true;`);
  storage.clear();
  callback();
  assert.equal(run('draftKey'), 'new-account-draft');
  assert.equal(run('busy'), true);
  assert.equal(storage.size, 0);
});

test('an already-queued preview animation cannot show old private state after disposal', () => {
  const {run, context} = engine();
  let callback;
  context.setTimeout = task => { callback = task; return 1; };
  run('shownPreviews=0; showPreview=()=>{shownPreviews++}; togglePlay()');
  assert.equal(run('shownPreviews'), 1);
  run('disposeWalk()');
  callback();
  assert.equal(run('shownPreviews'), 1);
  assert.equal(run('previewTimer'), null);
});

test('a late final interaction replaces the waiting state and leaves the next draft empty', async () => {
  const final = fixture({parts: [part('first')]}), pending = structuredClone(final.view);
  pending.interactions = []; pending.interaction_states.forEach(row => { row.status = 'pending'; delete row.interaction_id; });
  const pendingBundle = stateAPI.extendStreamBundle(base, pending, target, graph);
  const pendingState = stateAPI.refreshStreamState(pendingBundle, {...final.state, bundleVersion: pendingBundle.bundleVersion});
  const {run, context} = engine({bundle: pendingBundle, state: pendingState, view: pending});
  assert.equal(run('currentDecision(bundle,state)'), null);
  assert.match(run('waitingHTML(5)'), /计算已完成，正在准备练习/);
  context.finalView = final.view;
  await run('updateStreamSelection(finalView)');
  assert.equal(run('currentDecision(bundle,state).id'), 'first');
  assert.equal(run('draft'), null);
  assert.equal(run('renderCount'), 1);
  assert.equal(run('state.done'), false);
});

test('an initial D1/D2-only snapshot renders saved route progress without requiring its route metadata', () => {
  const full = fixture({parts: [part('first')]}), partial = stateAPI.extendStreamBundle(base, identity, target, graph);
  const restored = stateAPI.refreshStreamState(partial, full.state);
  const {run, roots} = engine({bundle: partial, state: restored, view: identity});
  run('renderStory=()=>{}; realRenderGraph()');
  assert.equal(roots.get('#gw-path').textContent, '正在恢复解题路线');
  assert.match(run('waitingHTML(5)'), /正在恢复解题路线/);
  assert.equal(run('state.run.route'), 'discriminant');
  assert.equal(run('state.introCompleted.length'), 3);
});

test('switching AI routes cancels its old timer and invalidates an already queued playback callback', () => {
  const {run, context} = engine(fixture({parts: [part('first'), part('last')]}));
  const scheduled = [], cancelled = [];
  context.setTimeout = callback => { scheduled.push(callback); return scheduled.length; };
  context.clearTimeout = handle => cancelled.push(handle);
  context.introActions = run('state.events.map(event=>event.action).filter(action=>action.decision!=="D3")');
  run(`options.replay={actions:introActions}; replayRoutes={discriminant:0}; chooseActor('replay');
    stopReplay=realStopReplay; updatePlayButton=()=>{}; replayPosition=3; playReplay();`);
  assert.equal(run('replayPosition'), 4);
  assert.equal(run('replayPlaying'), true);
  assert.equal(scheduled.length, 1);
  const oldTicket = run('replayTicket');
  run(`chooseStreamRoute('extremum')`);
  assert.equal(run('state.run.route'), 'extremum');
  assert.equal(run('replayPlaying'), false);
  assert.equal(run('replayTimer'), null);
  assert.ok(cancelled.includes(1));
  assert.ok(run('replayTicket') > oldTicket);
  const position = run('replayPosition'), renders = run('renderCount');
  scheduled[0]();
  assert.equal(run('replayPosition'), position);
  assert.equal(run('renderCount'), renders);
  assert.equal(run('replayNotice'), null);
});

for (const allRoutes of [true, false]) test(`withdrawing ${allRoutes ? 'all routes' : 'the playing route'} cancels stale AI callbacks and preserves student progress`, async () => {
  const value = fixture({parts: [part('first'), part('last')]});
  // The alternative has one fewer question, so a stale callback would exceed
  // its end even when a replacement route remains available.
  value.view.interactions[1].parts.pop();
  value.bundle = stateAPI.extendStreamBundle(base, value.view, target, graph);
  const {run, context} = engine(value), scheduled = [], cancelled = [];
  context.setTimeout = callback => { scheduled.push(callback); return scheduled.length; };
  context.clearTimeout = handle => cancelled.push(handle);
  context.introActions = run('state.events.map(event=>event.action).filter(action=>action.decision!=="D3")');
  const studentBefore = run('JSON.stringify([studentState.introCompleted,studentState.run,studentState.events])');
  run(`options.replay={actions:introActions}; replayRoutes={discriminant:0}; chooseActor('replay');
    stopReplay=realStopReplay; updatePlayButton=()=>{}; replayPosition=3; playReplay();`);
  assert.equal(run('replayPosition'), 4);
  assert.equal(scheduled.length, 1);
  const previousTicket = run('replayTicket');
  context.revoked = structuredClone(value.view);
  if (allRoutes) context.revoked.goals[target] = {status: 'conflict', available: false};
  else context.revoked.route_statuses = [[JSON.stringify([target, routes[0]]), {status: 'math_failed'}]];
  await assert.doesNotReject(run('updateStreamSelection(revoked)'));
  assert.equal(run('replayPlaying'), false);
  assert.equal(run('replayTimer'), null);
  assert.ok(cancelled.includes(1));
  assert.ok(run('replayTicket') > previousTicket);
  assert.equal(run('JSON.stringify([studentState.introCompleted,studentState.run,studentState.events])'), studentBefore);
  assert.equal(run('studentState.done'), false);
  assert.equal(run('currentDecision(bundle,studentState)'), null);
  assert.equal(run('replayRoutes.discriminant'), 4, 'a revoked route keeps its own last replay cursor');
  if (allRoutes) {
    assert.equal(run('replay.routes.length'), 0);
    assert.equal(run('state.done'), false);
  } else assert.equal(run('state.run.route'), 'extremum');
  const cursor = run('replayPosition'), renders = run('renderCount');
  scheduled[0]();
  assert.equal(run('replayPosition'), cursor);
  assert.equal(run('renderCount'), renders);
  assert.equal(run('replayNotice'), null);
});

test('the AI plays a route from the start the first time, whatever the student did, and resumes paused later', () => {
  const {run, context} = engine(fixture({parts: [part('first'), part('last')]}));
  const scheduled = [];
  context.setTimeout = callback => { scheduled.push(callback); return scheduled.length; };
  context.clearTimeout = () => {};
  context.introActions = run('state.events.map(event=>event.action).filter(action=>action.decision!=="D3")');
  assert.ok(run('studentState.introCompleted.length') > 0, 'the student is part way through');
  run(`options.replay={actions:introActions}; stopReplay=realStopReplay; updatePlayButton=()=>{}; chooseActor('replay');`);
  assert.equal(run('replayPosition'), 1);
  assert.equal(run('replayPlaying'), true);
  while (scheduled.length) scheduled.shift()();
  assert.equal(run('replayPosition'), run('replay.actions.length'), 'it plays on to the last step without stopping');
  run(`replayPosition=2; chooseActor('student'); chooseActor('replay');`);
  assert.equal(run('replayPosition'), 2);
  assert.equal(run('replayPlaying'), false);
  assert.equal(scheduled.length, 0);
});

test('an AI following the end keeps playing into steps that arrive later', async () => {
  const final = fixture({parts: [part('first')]}), pending = structuredClone(final.view);
  pending.interactions = []; pending.interaction_states.forEach(row => { row.status = 'pending'; delete row.interaction_id; });
  const pendingBundle = stateAPI.extendStreamBundle(base, pending, target, graph);
  const pendingState = stateAPI.refreshStreamState(pendingBundle, {...final.state, bundleVersion: pendingBundle.bundleVersion});
  const {run, context} = engine({bundle: pendingBundle, state: pendingState, view: pending});
  const scheduled = [];
  context.setTimeout = callback => { scheduled.push(callback); return scheduled.length; };
  context.clearTimeout = () => {};
  context.introActions = run('state.events.map(event=>event.action).filter(action=>!["D3","first"].includes(action.decision))');
  run(`options.replay={actions:introActions}; stopReplay=realStopReplay; updatePlayButton=()=>{}; chooseActor('replay');`);
  while (scheduled.length) scheduled.shift()();
  const end = run('replay.actions.length');
  assert.equal(run('replayPosition'), end);
  context.finalView = final.view;
  await run('updateStreamSelection(finalView)');
  assert.ok(run('replay.actions.length') > end);
  assert.equal(run('replayPosition'), end + 1, 'the next step is played, not skipped to the end');
});

function sequentialGoalsFixture(secondRoute = routes[0]) {
  const value = fixture({parts: [part('goal-one')]});
  const route = value.bundle.routes[routes[0]], secondTarget = '/root/goals/1';
  route.steps[0].target_ref = target;
  const firstCompletion = structuredClone(route.completion);
  const secondCompletion = {...firstCompletion, target_ref: secondTarget, route_id: secondRoute, verified_route_sha256: 'goal-two-verified'};
  const firstMath = value.bundle.stream.math_steps.find(step => step.route_id === routes[0]);
  const secondMath = {...structuredClone(firstMath), target_ref: secondTarget, route_id: secondRoute, step_id: 'second-goal-math',
    math_step_sha256: 'second-goal-math-hash', title: '第二目标数学步骤', after: [{latex: 'second-secret-answer'}]};
  const second = {...structuredClone(route.steps[0]), id: 'goal-two', target_ref: secondTarget,
    ...(secondRoute !== routes[0] ? {route_id: secondRoute} : {}),
    stream_interaction_id: 'second-goal-interaction', stream_steps: [{step_id: secondMath.step_id, math_step_sha256: secondMath.math_step_sha256}]};
  route.steps.push(second);
  route.goal_completions = [firstCompletion, secondCompletion];
  route.completion = {...firstCompletion, composition: 'sequential_goals', target_refs: [target, secondTarget],
    answer: {kind: 'goal_group', status: 'complete', answers: [firstCompletion, secondCompletion].map((item, index) =>
      ({target_ref: item.target_ref, title: `目标 ${index + 1}`, answer: item.answer}))}};
  delete route.completion.verified_route_sha256;
  value.bundle.stream.target_refs = [target, secondTarget];
  value.bundle.stream.math_steps.push(secondMath);
  value.secondMath = secondMath;
  return value;
}

for (const secondRoute of ['discriminant', 'function-matching']) test(`sequential targets retain ${secondRoute} cards and its own QA certificate without early completion`, () => {
  const value = sequentialGoalsFixture(secondRoute);
  const {run, context, roots} = engine(value);
  context.secondChunk = {...value.secondMath, verified_route_sha256: 'goal-two-verified', qa: {questions: ['第二目标的解释']}};
  run(`state = studentState = submitAnswer(bundle,state,{decision:'goal-one',answer:'yes'});`);
  assert.equal(run('state.done'), false);
  assert.equal(run('currentDecision(bundle,state).id'), 'goal-two');
  assert.equal(run('streamCards.size'), 0, 'future second-goal formulas remain hidden');
  const studentPrefix = run('JSON.stringify(studentState)');
  run(`const ai = replayState(bundle, buildStreamReplay(bundle,{currentRoute:'discriminant',actions:state.introCompleted.filter(row=>row.decision!=='D3').map(({decision,answer})=>({decision,answer}))}));`);
  assert.equal(run('JSON.stringify(studentState)'), studentPrefix, 'AI completion does not finish the student target');
  run(`state = studentState = submitAnswer(bundle,state,{decision:'goal-two',answer:'yes'});
    document.querySelector('#gw-steps').innerHTML=completedHTML(state.run.completed.at(-1),6,1,'discriminant');
    mountCompletedMath(); attachStreamQA(secondChunk);`);
  assert.equal(run('state.done'), true);
  const rendered = roots.get('#gw-steps').querySelector('.stage-three-math-step');
  assert.equal(rendered.dataset.targetRef, '/root/goals/1');
  assert.equal(rendered.dataset.routeId, secondRoute);
  assert.match(rendered.textContent, /second-secret-answer/);
  assert.match(rendered.querySelector('.stage-three-qa').textContent, /第二目标的解释/);
  assert.equal(run(`streamCompletion('${secondRoute}','/root/goals/1').verified_route_sha256`), 'goal-two-verified');
  assert.equal(run("streamCompletion('discriminant').verified_route_sha256"), undefined);
});

test('a multi-part derivation reveals only confirmed local completion boards', () => {
  const board = (label, output) => ({layout: 'derivation', caption: label, connector: '⇒',
    items: [{label: '输入', math: '1'}, {label: '输出', math: output}]});
  const first = {...part('trial-one'), completion_board: board('第一次试算', 'first-result')};
  const second = {...part('trial-two'), completion_board: board('第二次试算', 'second-result')};
  const {run, roots} = engine(fixture({parts: [first, second]}));
  run(`document.querySelector('#gw-steps').innerHTML='<div data-completion-board="trial-one"></div><div data-completion-board="trial-two"></div>';
    mountCompletionBoards(document.querySelector('#gw-steps'));`);
  assert.equal(roots.get('#gw-steps').textContent, '');
  run(`state = studentState = submitAnswer(bundle,state,{decision:'trial-one',answer:'yes'});
    mountCompletionBoards(document.querySelector('#gw-steps'));`);
  assert.match(roots.get('#gw-steps').textContent, /first-result/);
  assert.doesNotMatch(roots.get('#gw-steps').textContent, /second-result/);
  assert.equal(run('state.done'), false);
  run(`state = studentState = submitAnswer(bundle,state,{decision:'trial-two',answer:'yes'});
    document.querySelector('#gw-steps').innerHTML=groupCompletedHTML(stepUnits().units.at(-1),5);
    mountCompletedMath();`);
  assert.match(roots.get('#gw-steps').textContent, /first-result/);
  assert.match(roots.get('#gw-steps').textContent, /second-result/);
});
