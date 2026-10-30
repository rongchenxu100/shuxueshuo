import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {RELATIONS, createWalkGraph, laneMembers, nodeHref, panoramaLayout, treeLayout} from '../../site/assets/graph-walk/walk-graph.mjs';
import {createState, currentDecision, replayState, streamDraft, submitAnswer} from '../../site/assets/graph-walk/walk-state.mjs';
import {domainNumberLineGraph, endpointChecksHTML} from '../../site/assets/graph-walk/domain-visuals.mjs';
import {buildStreamReplay, replayAnswer} from '../../site/assets/graph-walk/walk-replay.mjs';

const source = fs.readFileSync(new URL('../../site/assets/graph-walk/walk.mjs', import.meta.url), 'utf8');
const components = fs.readFileSync(new URL('../../site/assets/practice/components.js', import.meta.url), 'utf8');
const bundle = JSON.parse(fs.readFileSync(new URL('../../site/data/graph-walk/quadratic-always-q01.json', import.meta.url), 'utf8'));
const equalityBundle = JSON.parse(fs.readFileSync(new URL('../../site/data/graph-walk/function-concepts-q20-v2.json', import.meta.url), 'utf8'));

function viewContext() {
  const nodes = new Map();
  const document = {querySelector(selector) {
    if (!nodes.has(selector)) nodes.set(selector, {textContent: '', hidden: false});
    return nodes.get(selector);
  }};
  const context = vm.createContext({document, matchMedia: () => ({matches: true}), URL,
    location: {origin: 'http://127.0.0.1:8779'}, setTimeout, clearTimeout, structuredClone, buildStreamReplay});
  context.window = context;
  vm.runInContext(components, context);
  vm.runInContext(source.replace(/^import .*;\n/gm, '').split("if (document.readyState === 'loading')")[0], context);
  context.fixture = structuredClone(bundle);
  vm.runInContext('bundle = fixture; state = {run: {id: 1}, events: [], lastFeedback: null};', context);
  return {context, nodes, run: code => vm.runInContext(code, context)};
}

test('comparison original text renders a prompt and separate options without splitting formulas', () => {
  const {context, nodes, run} = viewContext();
  const element = tagName => ({tagName, childNodes: [], append(...items) { this.childNodes.push(...items); },
    replaceChildren(...items) { this.childNodes = items; }, setAttribute(key, value) { this[key] = value; }});
  context.document.createElement = element;
  const host = context.document.querySelector('#gw-problem');
  Object.assign(host, element('p'));
  const rendered = [];
  context.PracticeMath = {render(host, text) {
    rendered.push({host, text}); host.source = text;
    host.childNodes = [{tagName: 'span', className: 'katex', childNodes: [{data: 'formula\ncontent'}]}];
  }};
  context.statement = equalityBundle.problem.text;
  run(`renderProblemText(document.querySelector('#gw-problem'), statement);`);
  const [prompt, options] = nodes.get('#gw-problem').childNodes;
  const [stem, ...originalOptions] = equalityBundle.problem.text.split('\n');
  assert.equal(prompt.className, 'problem-prompt');
  assert.equal(prompt.source, stem);
  assert.equal(options.className, 'problem-options');
  assert.equal(options.role, 'list');
  assert.equal(options.childNodes.length, 4);
  assert.deepEqual(options.childNodes.map(option => option.source), originalOptions);
  assert.ok(options.childNodes.every(option => option.className === 'problem-option' && option.role === 'listitem'));
  assert.deepEqual(rendered.map(item => item.text), [stem, ...originalOptions], 'each complete mathematical option renders once');
  assert.ok(rendered.every(({host}) => host.childNodes[0].childNodes[0].data === 'formula\ncontent'),
    'layout does not modify rendered formula descendants');
  rendered.length = 0;
  context.statement = '求函数 $f(x)=x^2$ 的定义域。';
  run(`renderProblemText(document.querySelector('#gw-problem'), statement);`);
  assert.equal(rendered.length, 1);
  assert.equal(rendered[0].host, host, 'ordinary problem text retains the direct renderer');
  assert.equal(host.source, context.statement);
});

for (const label of ['C', 'D']) test(`Q20 ${label} preserves completed proof feedback in student, replay and read-only cards`, () => {
  const route = Object.keys(equalityBundle.routes)[0];
  const parts = equalityBundle.routes[route].steps.filter(step => step.option_context?.label === label &&
    step.option_context.phase === 'evidence');
  assert.equal(parts.length, 2);
  assert.equal(parts[0].stream_interaction_id, parts[1].stream_interaction_id);
  const proof = parts[1].feedback.answer;
  assert.match(proof, label === 'C' ? /整个共同定义域/ : /统一记为 \$u\$/);
  const actions = [];
  let student = createState(equalityBundle);
  while (currentDecision(equalityBundle, student)?.id !== parts[1].id) {
    const decision = currentDecision(equalityBundle, student);
    assert.ok(decision, 'the correspondence decision must be reachable');
    const action = {decision: decision.id, answer: replayAnswer(decision, route)};
    actions.push(action); student = submitAnswer(equalityBundle, student, action);
    assert.equal(student.lastFeedback.status, 'passed');
  }
  const {context, run} = viewContext();
  Object.assign(context, {fixture: structuredClone(equalityBundle), progress: student, group: parts[1].stream_interaction_id});
  run('bundle = fixture; state = progress;');
  assert.equal(run('stepUnits().units.some(unit => unit.group === group)'), false, 'unfinished group is not a completed card');
  assert.equal(run('stepUnits().open.records.length'), 1);
  assert.ok(!run('partRowsHTML(stepUnits().open.records)').includes(proof), 'the pending correspondence answer does not leak');
  const action = {decision: parts[1].id, answer: replayAnswer(parts[1], route)};
  actions.push(action); student = submitAnswer(equalityBundle, student, action);
  const recording = {schemaVersion: 2, problemId: equalityBundle.problemId, bundleVersion: equalityBundle.bundleVersion,
    routes: [route], actions};
  for (const mode of ['student', 'replay', 'review']) {
    context.progress = mode === 'replay' ? replayState(equalityBundle, recording) : student;
    context.mode = mode; context.option = label;
    run("state = progress; actor = mode === 'replay' ? 'replay' : 'student'; reviewOption = mode === 'review' ? option : null;");
    const html = run('groupCompletedHTML(stepUnits().units.find(unit => unit.group === group), 7)');
    assert.ok(html.includes(proof), `${mode} retains the verified correspondence explanation`);
    for (const part of parts) assert.ok(html.includes(part.feedback.answer), `${mode} keeps each part's feedback`);
    assert.match(html, /data-stream-completed=/, 'the existing conclusion board remains mounted');
    assert.doesNotMatch(html, /本项结论：相同|gw-option-verdict-board|答案：C/, 'later verdict and final answers stay unpublished');
  }
});

test('direct-method live replay enters the route without a judgment plane', () => {
  const {run, context} = viewContext();
  const bridge = source.slice(source.indexOf('function streamReplay()'), source.indexOf('/** The same safe text/LaTeX renderer'));
  vm.runInContext(bridge.replace(/^export /gm, ''), context);
  run(`options = {replay: {actions: [{decision: 'D1', answer: 'seen'}]}};
    bundle = {problemId: 'domain', bundleVersion: 'v1', intro: [{id: 'D3', interaction: {
      type: 'read', methods: [{value: 'direct', route: 'domain'}]}, expected_answer: {}}],
      routes: {domain: {route_plan: 'planned', steps: [{id: 'intersection',
        interaction: {type: 'choice'}, expected_answer: {one_of: ['interval', 'set']}}]}}};`);
  const replay = JSON.parse(run('JSON.stringify(streamReplay())'));
  assert.deepEqual(replay.actions, [{decision: 'D1', answer: 'seen'}, {decision: 'D3', answer: 'read'},
    {decision: 'intersection', answer: 'interval'}]);
  assert.deepEqual(replay.routes, ['domain']);
});

test('completed direct-method card shows the method name, not a bare read receipt', () => {
  const {run} = viewContext();
  run(`bundle = {problemId: 'domain', intro: [{id: 'D3', title: '选择解题方法', source: 'authored',
    question: '使用列条件求交集法：按原式列出有意义的条件，分别求解，再取交集。',
    interaction: {type: 'read', methods: [{value: 'direct', label: '列条件求交集法', route: 'domain'}]},
    expected_answer: {}}], routes: {}};
    state = {introCompleted: [{decision: 'D3', answer: 'read'}], run: null};`);
  const reviewed = run('completedHTML(state.introCompleted[0], 3, 1, null)');
  assert.match(reviewed, /列条件求交集法/);
  assert.match(reviewed, /按原式列出有意义的条件/);
  assert.doesNotMatch(reviewed, />已阅读</);
});

test('Q5 domain prerequisite mounts its pending board and reveals the result only after acceptance', () => {
  const {context, nodes, run} = viewContext();
  const range = JSON.parse(fs.readFileSync(new URL('../../site/data/graph-walk/function-concepts-range-q05.json', import.meta.url), 'utf8'));
  const domain = range.intro.find(step => step.id === 'D3-domain');
  let progress = createState(range);
  while (currentDecision(range, progress).id !== domain.id) {
    const step = currentDecision(range, progress);
    progress = submitAnswer(range, progress, {decision: step.id, answer: replayAnswer(step)});
  }
  const boardHost = {children: [], append(node) { this.children.push(node); }, querySelectorAll() { return []; }};
  const completedHost = {dataset: {completionBoard: domain.id}, children: [],
    replaceChildren(node) { this.children = [node]; }, querySelectorAll() { return []; }};
  const active = {dataset: {}, innerHTML: '', querySelectorAll() { return []; }, querySelector(selector) {
    return selector === '[data-derivation-board]' && this.innerHTML.includes('data-derivation-board') ? boardHost : null;
  }};
  nodes.set('#gw-active', active);
  Object.assign(context, {fixture: range, progress, currentDecision, streamDraft,
    createDerivationBoard: (_document, board) => structuredClone(board), renderStreamMath: () => {},
    completedRoot: {querySelectorAll: () => [completedHost]}});
  run('bundle = fixture; state = progress; renderInteraction(currentDecision(bundle, state));');
  assert.equal(boardHost.children.length, 1, 'the original-domain premise must be visible in the active card');
  assert.deepEqual(boardHost.children[0], domain.stem_board);
  assert.equal(boardHost.children[0].items.at(-1).math, null, 'the result remains a question mark');
  run('mountCompletionBoards(completedRoot);');
  assert.equal(completedHost.children.length, 0, 'a result placeholder cannot reveal an unanswered prerequisite');
  context.progress = submitAnswer(range, progress, {decision: domain.id, answer: replayAnswer(domain)});
  run('state = progress;');
  assert.match(run('completedHTML(state.introCompleted.at(-1), 3, "intro", null)'), /data-completion-board="D3-domain"/);
  run('mountCompletionBoards(completedRoot);');
  assert.deepEqual(completedHost.children, [domain.completion_board]);
  assert.ok(completedHost.children[0].items.every(item => typeof item.math === 'string'));
});

test('a later function goal renders its mathematical heading in completed review and carry', () => {
  const {context, run} = viewContext();
  const evaluation = JSON.parse(fs.readFileSync(new URL('../../site/data/graph-walk/function-concepts-q28a.json', import.meta.url), 'utf8'));
  const route = Object.keys(evaluation.routes)[0];
  const goal = evaluation.routes[route].steps.find(step => step.title === '求 $g(1)$');
  assert.ok(goal, 'the second goal has an authored formula title');
  context.fixture = evaluation;
  Object.assign(context, {goal, route});
  run(`bundle = {intro: [], routes: {[route]: {steps: [goal]}}}; state = {introCompleted: [], run: {id: 1, route,
    completed: [{decision: goal.id, answer: goal.expected_answer.one_of?.[0] || 'read', results: ['已读懂本目标']}]}};`);
  const completed = run('completedHTML(state.run.completed[0], 7, 1, route)');
  const carry = run('carryHTML()');
  assert.match(completed, /<span class="gw-step-title" data-math-text>求 \$g\(1\)\$<\/span>/);
  assert.match(carry, /<p class="gw-carry-label" data-math-text>接第 1 步 · 求 \$g\(1\)\$<\/p>/);
  const labels = [completed, carry].map(html => {
    const text = /class="gw-(?:step-title|carry-label)" data-math-text>([^<]+)</.exec(html)[1];
    return {textContent: text, dataset: {}};
  });
  const rendered = [];
  context.PracticeMath = {render(node, text) { rendered.push(text); node.textContent = text.replaceAll('$', ''); }};
  context.headingRoot = {querySelectorAll(selector) {
    assert.equal(selector, '[data-math-text]:not([data-math-rendered])');
    return labels.filter(node => !node.dataset.mathRendered);
  }};
  run('renderMath(headingRoot); renderMath(headingRoot);');
  assert.deepEqual(rendered, ['求 $g(1)$', '接第 1 步 · 求 $g(1)$']);
  assert.ok(labels.every(label => label.dataset.mathRendered === 'true'));
});

test('AI completion never claims student practice completion', () => {
  const {run} = viewContext();
  run(`bundle.stream = {}; state.run.route = 'discriminant'; actor = 'replay';`);
  assert.match(run('completionHTML([])'), /回放已结束/);
  assert.doesNotMatch(run('completionHTML([])'), /练习已完成/);
});

test('single-choice D1 keeps the chosen meaning and its explanation in the completed review and replay', () => {
  const {run, context} = viewContext();
  const summary = '求定义域，就是找出使原解析式有意义的全部实数 $x$。';
  const reading = {id: 'D1', title: '读题', source: 'authored', question: '定义域是在求什么？',
    interaction: {type: 'choice', field: 'domain_reading', options: [
      {value: 'input', label: '自变量 $x$ 的取值范围'},
      {value: 'output', label: '函数值 $f(x)$ 的取值范围', feedback: '输出的集合是值域。'}]},
    expected_answer: {one_of: ['input']}, effects: {results: [summary]}};
  context.fixture.intro[0] = reading;
  const wrong = submitAnswer(context.fixture, createState(context.fixture), {decision: 'D1', answer: 'output'});
  assert.equal(wrong.introCompleted.length, 0);
  assert.match(wrong.lastFeedback.message, /值域/);
  context.readingState = submitAnswer(context.fixture, wrong, {decision: 'D1', answer: 'input'});
  run('bundle = fixture; state = readingState; draft = null;');
  assert.doesNotMatch(run('interactionHTML(bundle.intro[0])'), /原解析式有意义|checklist/);
  const reviewed = run('completedHTML(state.introCompleted[0], 1, 1, null)');
  assert.match(reviewed, /自变量 \$x\$ 的取值范围/);
  assert.match(reviewed, /原解析式有意义/);
  assert.doesNotMatch(reviewed, /函数值|gw-answer-rows/);
  assert.match(run('carryHTML()'), /原解析式有意义/);
  const replay = {schemaVersion: 2, problemId: context.fixture.problemId, bundleVersion: context.fixture.bundleVersion,
    status: 'partial', routes: [], actions: [{decision: 'D1', answer: 'input'}]};
  const replayed = replayState(context.fixture, replay, 1);
  assert.equal(replayed.introCompleted[0].answer, 'input');
  assert.deepEqual(replayed.introCompleted[0].results, [summary]);
});

test('domain self-mode only shows solved conditions before the final answer is accepted', () => {
  const {run, context} = viewContext();
  Object.assign(context, {domainNumberLineGraph, endpointChecksHTML});
  run(`line = {label: 'CONDITION', variable: 'x', bounds: [0, 3], intervals: [
      {left: 1, right: null, left_closed: true, right_closed: false}], points: [], ticks: [{at: 1, label: '1'}]};
    testDecision = {source: 'stream', condition_number_lines: [line],
      completion_number_line: {...line, label: 'FINAL_RESULT'}, endpoint_checks: [
        {at: 1, label: 'x=1', included: true, holds: true, passed: true, reason: 'ENDPOINT_REASON', sources: []}]};`);
  const before = run(`domainPremisesHTML(testDecision, 'test')`);
  assert.match(before, /CONDITION/);
  assert.doesNotMatch(before, /FINAL_RESULT|ENDPOINT_REASON/);
  assert.doesNotMatch(run(`domainPremisesHTML({condition_number_lines: [line]}, 'solve')`), /CONDITION/);
  const after = run(`completionFiguresHTML(testDecision, 'test', 'accepted')`);
  assert.match(after, /FINAL_RESULT/);
  assert.match(after, /ENDPOINT_REASON/);
});

test('nearby domain endpoints fall back to the checked set formula without overlapping markers', () => {
  const {run, context} = viewContext();
  Object.assign(context, {domainNumberLineGraph, endpointChecksHTML});
  const html = run(`domainLineHTML({label: '[1,1.01) \\u222a (1.01,+\\u221e)', variable: 'x', bounds: [0.25, 1.76],
    intervals: [{left: 1, right: 1.01, left_closed: true, right_closed: false},
      {left: 1.01, right: null, left_closed: false, right_closed: false}], points: [],
    ticks: [{at: 1, label: '1'}, {at: 1.01, label: '101/100'}]}, 'close', 'completion')`);
  assert.match(html, /端点过近，改用集合式展示/);
  assert.match(html, /\[1,1\.01\)/);
  assert.doesNotMatch(html, /data-graph|<svg/);
});

for (const badChecks of [null, {}, [null], [{at: 2, label: 'UNVERIFIED_ENDPOINT', included: true,
  holds: false, passed: false, reason: 'UNVERIFIED_REASON', sources: []}]]) {
  test(`invalid endpoint cards fail closed without breaking the other completed figures: ${JSON.stringify(badChecks)}`, () => {
    const {run, context} = viewContext();
    Object.assign(context, {domainNumberLineGraph, endpointChecksHTML, badChecks});
    run(`line = {label: 'VERIFIED_CONDITION', variable: 'x', bounds: [0, 3], intervals: [
      {left: 1, right: null, left_closed: true, right_closed: false}], points: [], ticks: [{at: 1, label: '1'}]};
      testDecision = {source: 'stream', condition_number_lines: [line], endpoint_checks: badChecks};`);
    const html = run(`completionFiguresHTML(testDecision, 'bad-endpoint', 'accepted')`);
    assert.match(html, /VERIFIED_CONDITION/);
    assert.match(html, /data-state="unavailable".*端点检查暂不可用.*未通过校验/s);
    assert.doesNotMatch(html, /UNVERIFIED_|可以取到|不能取到/);
    const repaired = run(`domainEndpointCardHTML([{at: 1, label: 'x=1', included: true,
      holds: true, passed: true, reason: '已验证原式有意义', sources: []}])`);
    assert.match(repaired, /可以取到/);
    assert.doesNotMatch(repaired, /unavailable/);
  });
}

test('one unverified endpoint prevents partial endpoint conclusions and does not hide unrelated code errors', () => {
  const {run, context} = viewContext();
  Object.assign(context, {endpointChecksHTML});
  const html = run(`domainEndpointCardHTML([{at: 1, label: 'VALID_ENDPOINT', included: true,
    holds: true, passed: true, reason: 'VALID_REASON', sources: []},
    {at: 2, label: 'BAD_ENDPOINT', included: false, holds: false, passed: false, reason: 'BAD_REASON', sources: []}])`);
  assert.match(html, /端点检查暂不可用/);
  assert.doesNotMatch(html, /VALID_|BAD_|可以取到|不能取到/);
  context.endpointChecksHTML = () => { throw Error('unexpected renderer bug'); };
  assert.throws(() => run('domainEndpointCardHTML([])'), /unexpected renderer bug/);
  context.endpointChecksHTML = () => { throw Error('domain_visuals.unknown_validation'); };
  assert.throws(() => run('domainEndpointCardHTML([])'), /domain_visuals.unknown_validation/);
});

test('stream arrival preserves the AI replay reading position and chooses an executable route', async () => {
  const {context, run} = viewContext();
  const bridge = source.slice(source.indexOf('function streamReplay()'), source.indexOf('/** The same safe text/LaTeX renderer'));
  vm.runInContext(bridge.replace(/^export /gm, ''), context);
  context.extendStreamBundle = value => structuredClone(value);
  context.refreshStreamState = (_bundle, value) => value;
  context.replayState = (_bundle, _replay, position) => ({introCompleted: [], run: {route: 'discriminant'}, readingPosition: position});
  run(`options = {bundle: {problemId: 'sample', bundleVersion: 'stable', graph: {nodes: [], edges: []},
      intro: [{id: 'D3', expected_answer: {cell: ['real', 'free']}, interaction: {type: 'plane', methods: [
        {value: 'discriminant', route: 'discriminant'}, {value: 'unsupported', route: 'unsupported'}]}}],
      routes: {discriminant: {route_plan: 'planned'}, unsupported: {route_plan: 'capability_gap'}}},
      stream: {run_id: 'run', lesson_version: 'version', target_ref: '/root/goals/0'},
      replay: {actions: [{decision: 'D1'}, {decision: 'D2'}]}};
    bundle = options.bundle; actor = 'replay'; replayPosition = 1;
    state = {introCompleted: [], run: {route: 'unsupported'}};
    renderGraph = () => {};`);
  assert.equal(run('streamReplay().routes[0]'), 'discriminant');
  await run(`updateStreamSelection({run_id: 'run', lesson_version: 'version'})`);
  assert.equal(run('replayPosition'), 1);
  assert.equal(run('state.readingPosition'), 1);
  const parkSource = source.slice(source.indexOf('export function parkWalk()'), source.indexOf('/* The actor the walk'));
  vm.runInContext(parkSource.replace(/^export /gm, ''), context);
  let compiled = 0;
  context.extendStreamBundle = value => { compiled++; return structuredClone(value); };
  run('stopReplay = () => {}; park = () => {};');
  const pending = run(`updateStreamSelection({run_id: 'run', lesson_version: 'version'})`);
  run('parkWalk()');
  await pending;
  assert.equal(compiled, 0, 'parked questions reject queued updates before recompiling or rendering');
});

for (const entry of ['load', 'mount']) for (const mode of ['playing', 'at-end', 'paused']) test(`stage-two to stream migration preserves AI playback intent: ${entry}/${mode}`, async () => {
  const {context, nodes, run} = viewContext();
  const bridge = source.slice(source.indexOf('function streamReplay()'), source.indexOf('/** The same safe text/LaTeX renderer'));
  vm.runInContext(bridge.replace(/^export /gm, ''), context);
  const mountSource = source.slice(source.indexOf('export async function mountWalk'), source.indexOf('/* The actor the walk'));
  vm.runInContext(mountSource.replace(/^export /gm, ''), context);
  context.document.body = {dataset: {}};
  context.PracticeMath = {render() {}};
  context.createState = value => ({bundleVersion: value.bundleVersion, introCompleted: [], run: {route: null}, events: []});
  context.replayState = (value, recording, position) => ({bundleVersion: value.bundleVersion,
    introCompleted: recording.actions.slice(0, position), run: {route: position === 3 ? 'discriminant' : null}, events: []});
  context.migrateStageTwoState = (_base, value, state) => ({...state, bundleVersion: value.bundleVersion});
  context.refreshStreamState = (_bundle, state) => state;
  context.extendStreamBundle = value => ({...structuredClone(value), bundleVersion: 'stream-version',
    stream: {run_id: 'run', lesson_version: 'version', target_ref: '/root/goals/0', base_bundle_version: value.bundleVersion},
    intro: [...value.intro, {id: 'D3', expected_answer: {cell: ['real', 'free']},
      interaction: {type: 'plane', methods: [{value: 'discriminant', route: 'discriminant'}]}}],
    routes: {discriminant: {route_plan: 'planned'}}});
  run(`options = {bundle: {problemId: 'sample', bundleVersion: 'base-version', graphVersion: 'graph',
      graph: {nodes: [], edges: [], layout: {}}, templates: {}, problem: {text: ''},
      intro: [{id: 'D1'}, {id: 'D2'}], routes: {}},
      stream: {run_id: 'run', lesson_version: 'version', target_ref: '/root/goals/0'},
      replay: {actions: [{decision: 'D1'}, {decision: 'D2'}]}};
    bundle = options.bundle; publicGraph = {}; actor = 'replay';
    studentState = state = createState(bundle); replay = options.replay;
    render = () => {}; updatePlayButton = () => {}; toggleSteps = () => {};
    mountProblemBar = () => {}; mountCaption = () => {}; mountPlayer = () => {};
    createGraph = async () => ({destroy() {}}); bound=true;`);
  for (const selector of ['#gw-graph-panel', '#gw-student', '#gw-ai']) {
    context.document.querySelector(selector);
    Object.assign(nodes.get(selector), {classList: {contains: () => false}, setAttribute() {}});
  }
  const scheduled = [];
  context.setTimeout = callback => { scheduled.push(callback); return scheduled.length; };
  run(`replayPosition = ${mode === 'at-end' ? 2 : 1}; replayPlaying = ${mode === 'playing'};`);
  await run(entry === 'mount' ? 'mountWalk({})' : 'load()');
  assert.equal(run('bundle.bundleVersion'), 'stream-version');
  const expected = {playing: 2, 'at-end': 3, paused: 1}[mode];
  assert.equal(run('replayPosition'), expected, 'playback continues step by step from where stage two left it');
  assert.equal(run('state.introCompleted.length'), expected);
  assert.equal(run('replayPlaying'), mode === 'playing');
  assert.equal(nodes.get('#gw-error')?.hidden, true);
});

test('draft choices do not reveal checklist notes or wrong-attempt calculations', () => {
  const {run} = viewContext();
  run(`testDecision = {id: 'draft', board: null, interaction: {type: 'checklist', slots: [
    {label: '判断', options: [{value: 'yes', label: '符合', note: 'This belongs after submission'}]}]}};
    draft = ['yes'];`);
  assert.doesNotMatch(run('interactionHTML(testDecision)'), /checklist-note|This belongs/);
  run(`bundle.templates.attempt = '<p>Submitted attempt</p>';
    testDecision.attempt_calculations = {yes: 'attempt'};
    state.lastFeedback = {status: 'wrong'}; submitted = null;`);
  assert.equal(run('attemptedCalculation(testDecision)'), '');
  run(`submitted = {decision: 'draft', answer: ['yes']};`);
  assert.match(run('attemptedCalculation(testDecision)'), /Submitted attempt/);
  run('submitted = null;');
  assert.equal(run('feedbackHTML()'), '');
  assert.equal(run('state.events.length'), 0);
});

test('malformed replay answers render safely without changing original evidence or feedback', () => {
  const {context, run} = viewContext();
  const decisions = [...bundle.intro, ...Object.values(bundle.routes).flatMap(route => route.steps)];
  for (const type of new Set(decisions.map(decision => decision.interaction.type))) {
    context.testDecision = structuredClone(decisions.find(decision => decision.interaction.type === type));
    for (const answer of [null, 42, {}, 'wrong shape', [null, {}, 3]]) {
      context.rawAnswer = structuredClone(answer);
      const original = JSON.stringify(answer);
      run(`actor = 'replay'; draftKey = ''; submitted = {decision: testDecision.id, answer: rawAnswer};
        state.lastFeedback = {status: 'wrong', message: '保留本次提交的判定'}; ensureDraft(testDecision);`);
      assert.doesNotThrow(() => run('interactionHTML(testDecision)'), type);
      assert.match(run('feedbackHTML()'), /保留本次提交的判定/);
      assert.equal(run('JSON.stringify(submitted.answer)'), original);
      assert.equal(run('state.lastFeedback.status'), 'wrong');
      if (type !== 'choice') assert.equal(run('Array.isArray(draft)'), true);
    }
  }
});

test('graph options pick by picture for both single and multiple choice', () => {
  const {context, run} = viewContext();
  const steps = bundle.routes.discriminant.steps;
  context.testDecision = structuredClone(steps.find(step => step.id === 'd_range'));
  run(`draft = 'outside';`);
  const single = run('interactionHTML(testDecision)');
  assert.equal((single.match(/data-quadratic-graph=/g) || []).length, 3);
  assert.match(single, /data-choice="d_range" data-value="outside" aria-pressed="true"/);
  assert.match(single, /data-value="open" aria-pressed="false"/);
  assert.doesNotMatch(single.slice(single.indexOf('gw-graph-options')).replace(/ data-graph-fallback="[^"]*"/, ''), /gw-graph-option-name|data-math-text/);
  run(`draft = 42;`);
  assert.doesNotThrow(() => run('interactionHTML(testDecision)'));
  context.testDecision = structuredClone(steps.find(step => step.id === 'd_position'));
  run(`draft = ['touch'];`);
  const multi = run('interactionHTML(testDecision)');
  assert.match(multi, /data-multi="touch" aria-pressed="true"/);
  assert.match(multi, /data-multi="apart" aria-pressed="false"/);
  assert.match(multi, /gw-graph-option-name">相切</);
});

test('the separation map picks one cell and keeps the pinned map as the completed record', () => {
  const {context, run} = viewContext();
  context.testDecision = structuredClone(bundle.routes.extremum.steps.find(step => step.id === 'e_basis'));
  run(`draft = ['', ''];`);
  const empty = run('interactionHTML(testDecision)');
  assert.equal((empty.match(/data-grid-cell=/g) || []).length, 4);
  assert.doesNotMatch(empty, /gw-plane-pin|data-chosen/);
  // Same reading order as the method plane: top row first, so this problem's cell is bottom-right.
  const cells = [...empty.matchAll(/data-grid-cell="([^"]+)"/g)].map(match => match[1]);
  assert.deepEqual(cells, ['tangled|division', 'separable|division', 'tangled|no_division', 'separable|no_division']);
  run(`draft = ['separable', 'no_division'];`);
  assert.match(run('interactionHTML(testDecision)'), /data-zone="direct" data-chosen>直接比较最值<\/span><span class="gw-plane-pin"[^>]*>本题<\/span><\/button>/);
  const done = run(`completedHTML({decision: 'e_basis', answer: ['separable', 'no_division']}, 4, 1, 'extremum')`);
  assert.match(done, /gw-plane is-static" role="img" aria-label="直接比较最值（能分离，不用除）"/);
  assert.doesNotMatch(done, /data-grid-cell|checklist/);
  assert.match(done, /<details[\s\S]*完整推导[\s\S]*<\/details>/);
  run(`state = {introCompleted: [], run: {id: 1, completed: [{decision: 'e_basis', answer: ['separable', 'no_division'], results: []}]}, events: []};`);
  assert.match(run('carryHTML()'), /直接比较最值（能分离，不用除）/);
});

test('the completion card shows the answer, this route\'s key idea and next actions', () => {
  const {run} = viewContext();
  run(`actor = 'student'; state = {run: {id: 2, route: 'discriminant', completed: []}, events: []};`);
  const html = run('completionHTML([])');
  assert.match(html, /判别式法 · 完成/);
  assert.match(html, /a\\in\(-\\infty,-1\]\\cup\[4,\+\\infty\)/);
  assert.match(html, /\\Delta\\le0/);
  assert.match(html, /data-route="extremum">再用分离参数法做一遍/);
  assert.match(html, /href="\/2\/">返回恒成立题库/);
  assert.doesNotMatch(html, /最大值/);
  const both = run(`completionHTML([{route: 'extremum'}])`);
  assert.match(both, /分离参数法 · 判别式法 · 完成/);
  assert.match(both, /<b>分离参数法<\/b>[\s\S]*最大值[\s\S]*<b>判别式法<\/b>[\s\S]*\\Delta\\le0/);
  run(`actor = 'replay';`);
  assert.doesNotMatch(run('completionHTML([])'), /data-route/);
});

test('the active card carries the immediately previous step: results, else its answer', () => {
  const {run} = viewContext();
  run(`state = {introCompleted: [{decision: 'D1', results: ['读题结论']}],
    run: {id: 1, completed: [{decision: 'd_rewrite', results: ['整理结果 $x$']}]}, events: []};`);
  assert.match(run('carryHTML()'), /接第 2 步 · 整理不等式[\s\S]*整理结果/);
  run(`state.run.completed.push({decision: 'd_position', answer: ['touch', 'apart'], results: []});`);
  const html = run('carryHTML()');
  assert.match(html, /接第 3 步 · 判断图像位置[\s\S]*相切[\s\S]*不相交/);
  assert.doesNotMatch(html, /整理结果|读题结论/);
  run(`state = {introCompleted: [{decision: 'D1', results: []}, {decision: 'D2', answer: 'type-quantified-quadratic', results: []},
    {decision: 'D3', answer: ['real', 'free', 'separation'], results: []}], run: {id: 1, completed: []}, events: []};`);
  assert.match(run('carryHTML()'), /接第 3 步 · 选择解题方法[\s\S]*选用分离参数法/);
  run(`state = {introCompleted: [], run: {id: 1, completed: []}, events: []};`);
  assert.equal(run('carryHTML()'), '');
});

test('the parts of one streamed interaction share a card, a step number and one completed record', () => {
  const {context, run} = viewContext();
  const part = (index, title, interaction) => ({id: `sep#${index + 1}`, source: 'stream', title, question: `${title}？`, interaction,
    stream_steps: [{step_id: 'divide', math_step_sha256: 'h'}], stream_interaction_id: 'sep', stream_part_index: index,
    stream_part_count: 3, stream_last_part: index === 2, stream_group_title: '分离参数'});
  const choice = (field, label) => ({type: 'choice', field, options: [{value: 'right', label}, {value: 'wrong', label: '错'}]});
  context.fixture.routes.separation = {id: 'separation', steps: [
    {id: 'rewrite', source: 'stream', title: '整理不等式', question: '', interaction: {type: 'read'}, stream_steps: [], stream_last_part: true},
    part(0, '移项', choice('moved', '$ax\\ge -x^2-1$')),
    part(1, '判断除数符号与不等号方向', {type: 'checklist', slots: [
      {label: '除数 $x$ 的符号', options: [{value: 'positive', label: '恒正'}]},
      {label: '不等号方向', options: [{value: 'keep', label: '保持不变'}]}]}),
    part(2, '分离参数', choice('separated', '$a\\ge -x-\\frac1x$'))]};
  run(`bundle = fixture; state = {introCompleted: [{decision: 'D1', results: ['读题结论']}],
    run: {id: 1, route: 'separation', completed: [{decision: 'rewrite', answer: 'read', results: ['整理结果']}, {decision: 'sep#1', answer: 'right', results: []}]}, events: []};`);
  assert.equal(run('JSON.stringify(stepUnits().units.map(unit => unit.records.length))'), '[1]');
  assert.equal(run('stepUnits().open.records[0].decision'), 'sep#1');
  // Partway through the card, the carry still points at the step before it, numbered by whole steps.
  assert.match(run('carryHTML()'), /接第 2 步 · 整理不等式[\s\S]*整理结果/);
  const stepper = run(`partStepperHTML(bundle.routes.separation.steps[2])`);
  assert.match(stepper, /data-state="done"[^>]*><span aria-hidden="true">✓<\/span><span data-math-text>移项[\s\S]*data-state="current" aria-current="step"><span aria-hidden="true">2<\/span><span data-math-text>判断除数符号与不等号方向[\s\S]*data-state="todo"><span aria-hidden="true">3<\/span><span data-math-text>分离参数/);
  assert.match(run('partRowsHTML(stepUnits().open.records)'), /✓<\/span><span data-math-text>移项[\s\S]*ax\\ge -x\^2-1/);
  run(`state.run.completed.push({decision: 'sep#2', answer: ['positive', 'keep'], results: []}, {decision: 'sep#3', answer: 'right', results: []});`);
  const {units, open} = JSON.parse(run('JSON.stringify(stepUnits())'));
  assert.equal(open, null);
  assert.deepEqual(units.map(unit => [unit.group, unit.records.length]), [[null, 1], ['sep', 3]]);
  const done = run('groupCompletedHTML(stepUnits().units[1], 3)');
  assert.equal((done.match(/class="gw-completed"/g) || []).length, 1);
  assert.match(done, /data-completed-decision="sep#3"[\s\S]*aria-label="第 3 步"[\s\S]*分离参数<\/span>/);
  assert.match(done, /data-stream-completed="sep#3"><\/div><\/div><\/details>$/);
  assert.doesNotMatch(done, /gw-part-row|查看各小问作答/);
  assert.match(run('carryHTML()'), /接第 3 步 · 分离参数/);
});

test('call records use the authored method step title', () => {
  const {context, run} = viewContext();
  run('graphView = bundle.graph;');
  for (const method of bundle.graph.nodes.filter(node => node.kind === 'method')) {
    for (const step of method.steps || []) {
      if (!step.calls?.length) continue;
      context.call = {method: method.id, step: step.id};
      assert.equal(run('callStepTitle(call)'), step.title);
    }
  }
  assert.equal(run(`callStepTitle({method: 'method-discriminant', step: 'normalize'})`), '移项整理成与 0 比较');
});

test('template hydration renders only math labels and graph hosts, preserving surrounding HTML', () => {
  const {context, run} = viewContext();
  const label = {textContent: '$x^2$', dataset: {}}, graphHost = {dataset: {quadraticGraph: '{}'}};
  const kindHost = {dataset: {graph: '{"kind":"number_line","params":{},"uid":"u"}'}};
  const visited = [];
  context.PracticeMath = {render(node, text) { visited.push([node, text]); }};
  context.root = {querySelectorAll(selector) {
    if (selector.startsWith('[data-graph-fallback]')) return [];
    if (selector.startsWith('[data-quadratic-graph]')) return [graphHost];
    if (selector.startsWith('[data-graph]')) return [kindHost];
    if (selector.startsWith('[data-math-text]')) return [label];
    throw new Error(`Unexpected hydration target: ${selector}`);
  }};
  run(`PracticeComponents.quadraticGraph = () => '<svg></svg>';
    PracticeComponents.graph = spec => '<svg data-kind="' + spec.kind + '"></svg>'; hydrate(root);`);
  assert.equal(graphHost.innerHTML, '<svg></svg>');
  assert.equal(kindHost.innerHTML, '<svg data-kind="number_line"></svg>');
  assert.equal(kindHost.dataset.graphRendered, 'true');
  assert.equal(visited.length, 1);
  assert.equal(visited[0][0], label);
  assert.equal(label.dataset.mathRendered, 'true');
  run(`bundle.templates.uid = '<svg id="{{uid}}"><use href="#{{uid}}" /></svg>';`);
  assert.match(run(`template('uid', 'run-1')`), /id="run-1"/);
  assert.doesNotMatch(run(`template('uid', 'run-2')`), /run-1/);
});

test('picture hydration failure restores the whole option group and remains retry safe', () => {
  for (const failure of ['throw', 'empty', 'json']) {
    const {context, run} = viewContext();
    const hosts = [{dataset: {graph: '{"kind":"linear","uid":"first"}'}, innerHTML: ''},
      {dataset: {graph: failure === 'json' ? '{' : '{"kind":"linear","uid":"second"}'}, innerHTML: ''}];
    let activeHosts = hosts;
    const group = {dataset: {graphFallback: '<button data-choice="p" data-value="a" aria-pressed="true"><span data-math-text>$a$</span></button><button data-choice="p" data-value="b"><span data-math-text>$b$</span></button>'},
      className: 'gw-graph-options', querySelectorAll: selector => selector === '[data-graph]' ? activeHosts : [],
      set innerHTML(value) { this.html = value; activeHosts = []; }};
    const label = {dataset: {}, textContent: '$a$'}, visited = [];
    context.PracticeMath = {render(node, text) { visited.push([node, text]); }};
    context.root = {querySelectorAll(selector) {
      if (selector.startsWith('[data-graph-fallback]')) return group.dataset.graphRendered ? [] : [group];
      if (selector.startsWith('[data-quadratic-graph]')) return [];
      if (selector.startsWith('[data-graph]')) return activeHosts.filter(host => !host.dataset.graphRendered);
      if (selector.startsWith('[data-math-text]')) return group.html && !label.dataset.mathRendered ? [label] : [];
      throw new Error(selector);
    }};
    context.failure = failure;
    run(`PracticeComponents.graph = spec => {
      if (spec.uid === 'first') return '<svg></svg>';
      if (failure === 'throw') throw new Error('renderer failure');
      return '';
    }; hydrate(root); hydrate(root);`);
    assert.equal(group.html, group.dataset.graphFallback, failure);
    assert.equal(group.className, 'gw-graph-fallback');
    assert.equal(group.dataset.graphRendered, 'true');
    assert.equal(hosts[0].innerHTML, '', 'a successful sibling was not mounted before the failure');
    assert.equal(hosts[0].dataset.graphRendered, undefined);
    assert.equal(visited.length, 1, 'the restored label receives math rendering exactly once');
  }
});

test('a failed stem or completion picture is removed with its caption while the rest hydrates', () => {
  const {context, run} = viewContext();
  const figures = [0, 1].map(() => ({removed: false, remove() { this.removed = true; }}));
  const hosts = figures.map((figure, i) => ({dataset: {graph: i ? '{' : '{"kind":"linear"}'},
    closest: selector => selector === '.gw-figure' ? figure : null}));
  const label = {dataset: {}, textContent: '$x^2+ax+1\\geq0$'}, visited = [];
  context.PracticeMath = {render(node, text) { visited.push([node, text]); }};
  context.root = {querySelectorAll(selector) {
    if (selector.startsWith('[data-graph-fallback]') || selector.startsWith('[data-quadratic-graph]')) return [];
    if (selector.startsWith('[data-graph]')) return hosts.filter((_, i) => !figures[i].removed);
    if (selector.startsWith('[data-math-text]')) return label.dataset.mathRendered ? [] : [label];
    throw new Error(selector);
  }};
  run(`PracticeComponents.graph = () => { throw new Error('renderer failure'); }; hydrate(root); hydrate(root);`);
  assert.deepEqual(figures.map(figure => figure.removed), [true, true]);
  assert.equal(visited.length, 1);
  assert.equal(visited[0][1], label.textContent);
});

test('replay paths resolve beside the index and reject off-demo or stale recordings', async () => {
  const {context, nodes, run} = viewContext();
  const fetched = [];
  let response = {bundleVersion: bundle.bundleVersion, problemId: bundle.problemId, actions: []};
  context.fetch = async url => { fetched.push(String(url)); return {ok: true, json: async () => response}; };
  run(`actor = 'replay'; render = () => {}; updatePlayButton = () => {}; applyReplayPosition = () => {}; playReplay = () => { played = true; };`);
  await run(`loadReplay('discriminant.json')`);
  assert.equal(fetched[0], 'http://127.0.0.1:8779/data/graph-walk/replays/discriminant.json');
  assert.equal(run('replay.problemId'), bundle.problemId);
  assert.equal(run('played'), true);
  assert.equal(run('replayNotice'), null);
  await run(`loadReplay('https://other.example/discriminant.json')`);
  assert.equal(fetched.length, 1);
  assert.match(run('replayNotice.text'), /不属于本 Demo/);
  response = {...response, bundleVersion: 'old'};
  await run(`loadReplay('discriminant.json')`);
  assert.equal(run('replay'), null);
  assert.match(run('replayNotice.text'), /版本不同/);
  assert.match(run('replayPendingHTML(null)'), /gw-replay-retry/);
});

test('leaving the AI while its replay file is still loading reads it again on return', async () => {
  const {context, run} = viewContext();
  Object.assign(context, {createState, replayState});
  const replayFile = {schemaVersion: 2, bundleVersion: bundle.bundleVersion, problemId: bundle.problemId, routes: [], actions: [], status: 'failed'};
  const pending = [], fetched = [];
  context.fetch = url => {
    fetched.push(String(url));
    if (String(url).endsWith('index.json')) {
      return Promise.resolve({ok: true, json: async () => ({bundleVersion: bundle.bundleVersion, replays: [{path: 'walk.json'}]})});
    }
    return new Promise(resolve => pending.push(() => resolve({ok: true, json: async () => replayFile})));
  };
  const element = {classList: {contains: () => false, toggle() {}}, setAttribute() {}, textContent: '', hidden: false};
  context.document.querySelector = () => element;
  context.document.body = {dataset: {}, classList: {toggle() {}, contains: () => false}};
  run(`render = () => {}; updatePlayButton = () => {}; closeGraph = () => {}; applyReplayPosition = () => {}; playReplay = () => {};`);
  run(`chooseActor('replay')`);
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(pending.length, 1);
  run(`chooseActor('student')`);
  pending.shift()();
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(run('replay'), null);
  run(`chooseActor('replay')`);
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(pending.length, 1);
  assert.equal(fetched.filter(url => url.endsWith('walk.json')).length, 2);
  pending.shift()();
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(run('replay.status'), 'failed');
  assert.equal(run('replayNotice'), null);
});

class SVGElement {
  constructor(tag) {
    this.tag = tag; this.children = []; this.attributes = {}; this.dataset = {};
    this.clientWidth = 450; this.clientHeight = 480;
    this.classList = {toggle() {}};
  }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  append(...nodes) { for (const node of nodes) node.parentNode = this; this.children.push(...nodes); }
  replaceChildren(...nodes) { for (const node of this.children) node.parentNode = null; this.children = []; this.append(...nodes); }
  remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(node => node !== this); this.parentNode = null; }
  insertBefore(node, other) { this.children.splice(this.children.indexOf(other), 0, node); }
  addEventListener(type, listener) { (this.listeners ||= {})[type] = listener; }
  getBoundingClientRect() { return {left: 0, top: 0}; }
  setPointerCapture() {}
  hasPointerCapture() { return false; }
  closest() { return null; }
  querySelector(selector) {
    return this.children.find(node => node.attributes.class === selector.slice(1));
  }
}

test('the 2D graph shows the whole tree and stays still while the walk advances', () => {
  const globals = ['document', 'matchMedia', 'ResizeObserver', 'cancelAnimationFrame'];
  const previous = new Map(globals.map(key => [key, globalThis[key]]));
  try {
    globalThis.document = {createElement: tag => new SVGElement(tag), createElementNS: (_, tag) => new SVGElement(tag)};
    globalThis.matchMedia = () => ({matches: true});
    globalThis.ResizeObserver = class {observe() {} disconnect() {}};
    globalThis.cancelAnimationFrame = () => {};
    const host = new SVGElement('div');
    const graph = structuredClone(bundle.graph);
    const view = createWalkGraph(host, graph);
    const svg = host.children[1], viewport = svg.children[1];
    const transform = () => viewport.attributes.transform;
    const before = transform();
    const [x, y, scale] = before.match(/-?\d+(?:\.\d+)?/g).map(Number);
    const {width, height} = panoramaLayout(graph, 450, 480);
    assert.ok(x >= 0 && y >= 0 && x + width * scale <= 450 + 1e-6 && y + height * scale <= 480 + 1e-6);
    const [first, second] = graph.edges;
    view.render({nodes: {[first.from]: 'confirmed', [first.to]: 'active'}, edges: {[first.id]: 'chosen'}, focus: [first.to]});
    view.render({nodes: {[second.to]: 'active'}, edges: {}, focus: [second.to]});
    assert.equal(transform(), before);
    const edges = viewport.children.find(node => node.attributes.class === 'gw-edge-layer').children;
    assert.equal(edges.find(edge => edge.attributes['data-edge'] === first.id).children.at(-1).textContent, RELATIONS[first.type]);
    assert.equal(nodeHref({id: 'quadratic', ref: 'quadratic#sign'}), '/knowledge/quadratic/#sign');
  } finally {
    for (const key of globals) previous.get(key) === undefined ? delete globalThis[key] : globalThis[key] = previous.get(key);
  }
});

test('destroying an obsolete 2D graph preserves the replacement graph nodes', () => {
  const globals = ['document', 'matchMedia', 'ResizeObserver', 'cancelAnimationFrame'];
  const previous = new Map(globals.map(key => [key, globalThis[key]]));
  try {
    globalThis.document = {createElement: tag => new SVGElement(tag), createElementNS: (_namespace, tag) => new SVGElement(tag)};
    globalThis.matchMedia = () => ({matches: true});
    globalThis.ResizeObserver = class {observe() {} disconnect() {}};
    globalThis.cancelAnimationFrame = () => {};
    const host = new SVGElement('div');
    const stale = createWalkGraph(host, structuredClone(bundle.graph));
    const current = createWalkGraph(host, structuredClone(bundle.graph));
    const retained = [...host.children];
    stale.destroy();
    assert.deepEqual(host.children, retained);
    current.render({nodes: {}, edges: {}, focus: []});
    current.destroy();
    assert.equal(host.children.length, 0);
  } finally {
    for (const key of globals) previous.get(key) === undefined ? delete globalThis[key] : globalThis[key] = previous.get(key);
  }
});

test('the 2D calls lane shows only used nodes, each with its step numbers, until the toggle shows the rest', () => {
  const globals = ['document', 'matchMedia', 'ResizeObserver', 'cancelAnimationFrame'];
  const previous = new Map(globals.map(key => [key, globalThis[key]]));
  try {
    globalThis.document = {createElement: tag => new SVGElement(tag), createElementNS: (_, tag) => new SVGElement(tag)};
    globalThis.matchMedia = () => ({matches: true});
    globalThis.ResizeObserver = class {observe() {} disconnect() {}};
    globalThis.cancelAnimationFrame = () => {};
    const graph = structuredClone(bundle.graph);
    const lane = graph.layout.bands.at(-1).label, members = [...laneMembers(graph, lane)];
    assert.ok(members.length >= 2, 'the fixture lane has a used and an unused node');
    const [used, unused] = members;
    const host = new SVGElement('div');
    const view = createWalkGraph(host, graph, {usedOnlyLane: lane});
    const [controls, svg] = host.children;
    const nodeOf = id => svg.children[1].children[2].children.find(node => node.attributes['data-node'] === id);
    view.render({nodes: {[used]: 'confirmed'}, edges: {}, stepMarks: {[used]: [4, 5]}});
    assert.equal(nodeOf(used).attributes.display, 'inline');
    assert.equal(nodeOf(unused).attributes.display, 'none');
    assert.equal(nodeOf(used).querySelector('.gw-node-steps').textContent, '第 4、5 步');
    assert.ok(!treeLayout(graph, {hidden: new Set([unused])}).positions.has(unused));
    controls.listeners.click({target: {closest: () => ({setAttribute() {}, dataset: {graphAction: 'idle'}})}});
    assert.equal(nodeOf(unused).attributes.display, 'inline');
  } finally {
    for (const key of globals) previous.get(key) === undefined ? delete globalThis[key] : globalThis[key] = previous.get(key);
  }
});

test('two fingers pinch the 2D graph around their midpoint', () => {
  const globals = ['document', 'matchMedia', 'ResizeObserver', 'cancelAnimationFrame'];
  const previous = new Map(globals.map(key => [key, globalThis[key]]));
  try {
    globalThis.document = {createElement: tag => new SVGElement(tag), createElementNS: (_, tag) => new SVGElement(tag)};
    globalThis.matchMedia = () => ({matches: true});
    globalThis.ResizeObserver = class {observe() {} disconnect() {}};
    globalThis.cancelAnimationFrame = () => {};
    const host = new SVGElement('div');
    createWalkGraph(host, structuredClone(bundle.graph));
    const svg = host.children[1], viewport = svg.children[1];
    const read = () => viewport.attributes.transform.match(/-?\d+(?:\.\d+)?/g).map(Number);
    const [x0, y0, k0] = read();
    const pointer = (type, id, x, y) => svg.listeners[type]({pointerId: id, clientX: x, clientY: y, target: svg});
    pointer('pointerdown', 1, 200, 200); pointer('pointerdown', 2, 240, 200);
    pointer('pointermove', 1, 180, 200); pointer('pointermove', 2, 260, 200);
    const [x, y, k] = read();
    assert.ok(Math.abs(k - k0 * 2) < 1e-9);
    assert.ok(Math.abs((220 - x) / k - (220 - x0) / k0) < 1e-9 && Math.abs((200 - y) / k - (200 - y0) / k0) < 1e-9);
    pointer('pointerup', 1, 180, 200); pointer('pointermove', 2, 300, 200);
    assert.deepEqual(read(), [x, y, k]);
  } finally {
    for (const key of globals) previous.get(key) === undefined ? delete globalThis[key] : globalThis[key] = previous.get(key);
  }
});

test('the 2D tree stacks the snapshot lanes top-down in a grid, without overlaps', () => {
  const {positions, bands, direction, width, height} = treeLayout(bundle.graph, {perRow: 4});
  assert.equal(direction, 'down');
  assert.deepEqual(bands.map(band => band.label), bundle.graph.layout.bands.map(band => band.label));
  assert.deepEqual([...positions.keys()].sort(), Object.keys(bundle.graph.layout.positions).sort());
  bands.forEach((band, index) => { if (index) assert.ok(band.y >= bands[index - 1].y + bands[index - 1].h); });
  const boxes = [...positions.values()];
  const rows = Map.groupBy(boxes, box => Math.round(box.y + box.h / 2));
  assert.ok([...rows.values()].every(row => row.length <= 4));
  for (const [i, a] of boxes.entries()) {
    assert.ok(a.x >= 0 && a.y >= 0 && a.x + a.w <= width && a.y + a.h <= height);
    for (const b of boxes.slice(i + 1)) assert.ok(a.x + a.w <= b.x || b.x + b.w <= a.x || a.y + a.h <= b.y || b.y + b.h <= a.y);
  }
});

test('the panorama widens its rows in a wide panel and narrows them in a tall one', () => {
  const wide = panoramaLayout(bundle.graph, 1200, 560), tall = panoramaLayout(bundle.graph, 390, 700);
  assert.ok(wide.perRow > tall.perRow);
  assert.ok(wide.width / wide.height > tall.width / tall.height);
});

test('bare formulas in AI reasons render as math; authored math and words stay as they are', () => {
  const {run} = viewContext();
  const text = reason => run(`mathText(${JSON.stringify(reason)})`);
  assert.equal(text('a^2-3a-4=(a-4)(a+1)≥0，即 a≤-1 或 a≥4。'), '$a^2-3a-4=(a-4)(a+1)\\ge 0$，即 $a\\le -1$ 或 $a\\ge 4$。');
  assert.equal(text('判别式 Δ≤0，只需 c≥f(x)_max.'), '判别式 $\\Delta \\le 0$，只需 $c\\ge f(x)_{\\mathrm{max}}$.');
  assert.equal(text('配方得 $-x^2+2x+3=4-(x-1)^2$，故常数为 4。'), '配方得 $-x^2+2x+3=4-(x-1)^2$，故常数为 4。');
  assert.equal(text('AI 看关于 x 的式子 ax^2+bx'), 'AI 看关于 $x$ 的式子 $ax^2+bx$');
  assert.equal(text('x∈ℝ，落在 real/free；需 Δ≤0'), '$x\\in \\mathbb R$，落在 real/free；需 $\\Delta \\le 0$');
});
