import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {
  createState, currentDecision, submitAnswer, switchRoute, undo, graphState,
  extendStreamBundle, streamGraphState, streamStepGraph, replayState, migrateStageTwoState, refreshStreamState, teachingContext,
} from '../../site/assets/graph-walk/walk-state.mjs';
import {createEventConsumer} from '../../site/assets/graph-walk/stage-three-stream.mjs';

const read = path => JSON.parse(fs.readFileSync(new URL(path, import.meta.url), 'utf8'));
const original = read('../../site/lab/search/demo-lesson-q01.json').goals[0].walk;
const graph = read('../../site/knowledge/graph.json');
const d3 = read('../../site/data/graph-walk/quadratic-always-q01.source.json').intro.find(item => item.id === 'D3');
const d4 = {id: 'D4', title: '解题路线', options: [
  {branch: 'discriminant', route_id: 'discriminant', method: 'method-discriminant', route_plan: 'planned', recommendation: 'preferred'},
  {branch: 'separation', route_id: 'extremum', method: 'method-separation', route_plan: 'planned', recommendation: 'optional'},
]};
const identity = {run_id: 'run-current', lesson_version: 'lesson-current', stream_id: 'run-current'};
const target = '/root/goals/0';
const view = { ...identity, selection_chunks: [{target_ref: target, kind: 'D3', chunk: d3},
  {target_ref: target, kind: 'D4', chunk: d4}], math_steps: []};
const step = (ordinal, basis, source = '/steps/0/calls/0') => ({...identity, target_ref: target, route_id: 'discriminant',
  step_id: `math-${ordinal}`, ordinal, local_check: 'passed', math_step_sha256: `hash-${ordinal}`,
  method_ref: 'method-discriminant#normalize', source_refs: [source], used_basis: [basis], title: `数学步骤 ${ordinal}`});
const first = step(1, 'inequality-properties#addition');
const second = step(2, 'quadratic-function-properties#definition', '/steps/1/calls/0');
const checkpoint = {target_ref: target, route_id: 'discriminant', driver_state: {trajectory: {steps: [
  {seq: 1, method: 'method-discriminant', step: 'normalize', calls: [
    {public_ref: 'skill-inequality-transform', used_basis: ['inequality-properties#addition'], postconditions: [{passed: true}]},
  ]},
  {seq: 2, method: 'method-discriminant', step: 'conditions', calls: [
    {public_ref: 'skill-quadratic-sign', used_basis: ['quadratic-function-properties#definition'], postconditions: [{passed: true}]},
  ]},
]}}};
const withMath = {...view, math_steps: [first, second], checkpoints: [checkpoint]};
const completedRoute = () => ({...identity, identity: [target, 'discriminant'], status: 'verified', available: true,
  verified_route_sha256: 'verified-current-route', answer: {kind: 'find_range', status: 'set', set: {latex: '[0,1]'}},
  original_choice: {status: 'matched', kind: 'single_choice', target_ref: target,
    options: [{label: 'A', text: '$[0,1]$'}, {label: 'B', text: '$(0,1)$'}], correct_labels: ['A']}});
const handoffRoute = () => ({...completedRoute(), target_ref: target, route_id: 'discriminant', status: 'pending'});
const routeView = extra => ({...view, math_steps: [first], ...extra});

test('live and recovered generic set choices keep the exact final without T1 option gates', () => {
  const completion = completedRoute();
  completion.answer.kind = 'find_abstract_domain';
  Object.assign(completion.original_choice, {kind: 'multiple_choice', matching: 'set_equality', selection_mode: 'unspecified'});
  const handoff = {...completion, target_ref: target, route_id: 'discriminant', status: 'pending'};
  for (const extra of [{completions: [completion]}, {handoffs: [handoff],
    checkpoints: [{target_ref: target, route_id: 'discriminant', status: 'verified'}]}]) {
    const bundle = extendStreamBundle(original.bundle, routeView(extra), target, graph);
    const route = bundle.routes.discriminant;
    const final = route.steps.at(-1);
    assert.equal(route.interactions_complete, true);
    assert.equal(final.interaction.type, 'original_choice_exact_set');
    assert.equal(final.require_complete_options, undefined);
    assert.deepEqual(final.expected_answer, {correct_labels: ['A'], option_labels: ['A', 'B']});
  }
});

for (const text of ['A. $[0,1]$', 'A．$[0,1]$', 'Ａ． $[0,1]$', 'A、$[0,1]$', 'A： $[0,1]$', 'A) $[0,1]$', 'A）$[0,1]$',
  '(A) $[0,1]$', '（Ａ）$[0,1]$', '[A] $[0,1]$', '【A】 $[0,1]$', ' \n A. $[0,1]$']) {
  test(`original option marker is displayed once without changing frozen data: ${JSON.stringify(text)}`, () => {
    const completion = completedRoute();
    completion.original_choice.options[0].text = text;
    const before = structuredClone(completion);
    const bundle = extendStreamBundle(original.bundle, routeView({completions: [completion]}), target, graph);
    const decision = bundle.routes.discriminant.steps.at(-1);
    assert.equal(decision.interaction.options[0].label, text);
    assert.equal(decision.interaction.options[0].value, 'A');
    assert.equal(decision.interaction.options[1].label, 'B. $(0,1)$');
    assert.deepEqual(completion, before);
    assert.deepEqual(bundle.routes.discriminant.completion.original_choice, before.original_choice);
    assert.equal(bundle.routes.discriminant.completion.verified_route_sha256, before.verified_route_sha256);
  });
}

for (const text of ['$[0,1]$', '$A+B>0$', 'A+B>0', 'A = 1', '(A+B)>0', 'B. $[0,1]$']) {
  test(`unmarked original options and leading math letters keep their complete content: ${JSON.stringify(text)}`, () => {
    const completion = completedRoute();
    completion.original_choice.options[0].text = text;
    const bundle = extendStreamBundle(original.bundle, routeView({completions: [completion]}), target, graph);
    assert.equal(bundle.routes.discriminant.steps.at(-1).interaction.options[0].label, `A. ${text}`);
  });
}

test('prefixed multiple-choice source options remain frozen and cannot be mistaken for a single-choice question', () => {
  const completion = completedRoute();
  completion.original_choice = {...completion.original_choice, kind: 'multiple_choice', correct_labels: ['A', 'B'],
    options: [{label: 'A', text: 'A. $[0,1]$'}, {label: 'B', text: '（B）$0\\le x\\le1$'}]};
  const before = structuredClone(completion);
  const bundle = extendStreamBundle(original.bundle, routeView({completions: [completion]}), target, graph);
  assert.equal(bundle.routes.discriminant.math_complete, true);
  assert.equal(bundle.routes.discriminant.steps.some(step => step.source === 'original_choice'), false);
  assert.deepEqual(completion, before);
  assert.deepEqual(bundle.routes.discriminant.completion.original_choice, before.original_choice);
});

for (const field of ['run_id', 'lesson_version']) for (const source of ['completions', 'handoffs']) {
  test(`a ${source} record from another ${field} cannot complete the current route or add original options`, () => {
    const record = {...(source === 'completions' ? completedRoute() : handoffRoute()), [field]: 'old'};
    const bundle = extendStreamBundle(original.bundle, routeView({[source]: [record]}), target, graph);
    assert.equal(bundle.routes.discriminant.math_complete, false);
    assert.equal(bundle.routes.discriminant.completion, null);
    assert.deepEqual(bundle.routes.discriminant.steps.map(step => step.source), ['stream']);
  });
}

test('compact live completions and available snapshot handoffs preserve the same current-run original answer', () => {
  const live = completedRoute(); delete live.run_id; delete live.lesson_version; delete live.stream_id;
  const fromLive = extendStreamBundle(original.bundle, routeView({completions: [live]}), target, graph);
  const fromSnapshot = extendStreamBundle(original.bundle, routeView({handoffs: [handoffRoute()]}), target, graph);
  for (const bundle of [fromLive, fromSnapshot]) {
    assert.equal(bundle.routes.discriminant.math_complete, true);
    assert.equal(bundle.routes.discriminant.completion.run_id, identity.run_id);
    assert.equal(bundle.routes.discriminant.completion.lesson_version, identity.lesson_version);
    assert.equal(bundle.routes.discriminant.steps.at(-1).source, 'original_choice');
    assert.deepEqual(bundle.routes.discriminant.steps.at(-1).expected_answer, {one_of: ['A']});
    const partial = extendStreamBundle(bundle, {...identity}, target, graph);
    assert.deepEqual(partial.routes.discriminant.steps, bundle.routes.discriminant.steps);
    assert.equal(partial.routes.discriminant.math_complete, true);
  }
});

for (const available of [false, undefined]) test(`a snapshot handoff with available=${available} cannot grant completion`, () => {
  const initial = extendStreamBundle(original.bundle, routeView({completions: [completedRoute()]}), target, graph);
  const handoff = {...handoffRoute(), available};
  const revoked = extendStreamBundle(initial, routeView({handoffs: [handoff],
    checkpoints: [{target_ref: target, route_id: 'discriminant', status: 'verified'}]}), target, graph);
  assert.equal(revoked.routes.discriminant.available, false);
  assert.equal(revoked.routes.discriminant.math_complete, false);
  assert.equal(revoked.routes.discriminant.completion, null);
  assert.deepEqual(revoked.routes.discriminant.steps.map(step => step.source), ['stream']);
  const partial = extendStreamBundle(revoked, {...identity, goals: {}}, target, graph);
  assert.equal(partial.routes.discriminant.available, false);
  assert.equal(partial.routes.discriminant.completion, null);
});

test('handoffs need a verified route hash and cannot borrow one from the previous completion', () => {
  const initial = extendStreamBundle(original.bundle, routeView({completions: [completedRoute()]}), target, graph);
  const handoff = handoffRoute(); delete handoff.verified_route_sha256;
  const current = extendStreamBundle(initial, routeView({handoffs: [handoff]}), target, graph);
  assert.equal(current.routes.discriminant.math_complete, false);
  assert.equal(current.routes.discriminant.completion, null);
  assert.deepEqual(current.routes.discriminant.steps.map(step => step.source), ['stream']);
});

test('an inherited completion with an explicit foreign identity cannot leak saved original options', () => {
  const initial = extendStreamBundle(original.bundle, routeView({completions: [completedRoute()]}), target, graph);
  for (const field of ['run_id', 'lesson_version']) {
    const damaged = structuredClone(initial);
    damaged.routes.discriminant.completion[field] = 'old';
    const current = extendStreamBundle(damaged, {...identity}, target, graph);
    assert.equal(current.routes.discriminant.math_complete, false);
    assert.equal(current.routes.discriminant.completion, null);
    assert.deepEqual(current.routes.discriminant.steps.map(step => step.source), ['stream']);
  }
});

test('a nonstream base cannot donate an old route completion to a new run', () => {
  const old = extendStreamBundle(original.bundle, routeView({completions: [completedRoute()]}), target, graph);
  const base = {...structuredClone(original.bundle), routes: structuredClone(old.routes)};
  const current = extendStreamBundle(base, routeView({run_id: 'new-run', math_steps: [{...first, run_id: 'new-run'}]}), target, graph);
  assert.equal(current.routes.discriminant.math_complete, false);
  assert.equal(current.routes.discriminant.completion, null);
  assert.deepEqual(current.routes.discriminant.steps.map(step => step.source), ['stream']);
});

test('an explicit running checkpoint clears completion while preserving committed mathematical steps', () => {
  const initial = extendStreamBundle(original.bundle, routeView({completions: [completedRoute()]}), target, graph);
  const current = extendStreamBundle(initial, routeView({completions: [],
    checkpoints: [{target_ref: target, route_id: 'discriminant', status: 'running'}]}), target, graph);
  assert.equal(current.routes.discriminant.math_complete, false);
  assert.equal(current.routes.discriminant.completion, null);
  assert.deepEqual(current.routes.discriminant.steps.map(step => step.id), ['math-1']);
});

// Card-level source/path probes exercise the extracted pure evidence function.
// Actual answer-driven graph progression is covered in graph-walk-stream-interactions.
function evidenceView(bundle, state, {steps = [], route = state.run.route} = {}) {
  const result = streamGraphState(bundle, state);
  if (route !== state.run.route || state.introCompleted.length < bundle.intro.length) return result;
  const seen = new Set(), bases = new Set(result.usedBasis);
  for (const card of steps) {
    const key = JSON.stringify([card.route_id, card.step_id]);
    if (card.route_id !== route || seen.has(key)) continue;
    seen.add(key);
    const evidence = streamStepGraph(bundle, card);
    for (const node of evidence.nodes) result.nodes[node] = 'confirmed';
    for (const edge of evidence.edges) result.edges[edge] = 'chosen';
    for (const basis of evidence.usedBasis) bases.add(basis);
    result.calls.push(...evidence.calls);
  }
  result.usedBasis = [...bases].sort();
  return result;
}

function answer(bundle, state, value) {
  const decision = currentDecision(bundle, state);
  return submitAnswer(bundle, state, {decision: decision.id, answer: value ??
    (decision.interaction.type === 'checklist' ? decision.expected_answer.terms : decision.expected_answer.one_of[0])});
}
function selected(bundle, route = 'discriminant') {
  let state = createState(bundle);
  state = answer(bundle, state);
  state = answer(bundle, state);
  const plane = currentDecision(bundle, state);
  const method = plane.interaction.methods.find(item => item.route === route || item.target === methodOf[route]);
  return answer(bundle, state, [...plane.expected_answer.cell, method.value]);
}

function convertedBase() {
  const base = structuredClone(original.bundle);
  base.bundleVersion = 'with-verified-proposition-conversion';
  base.problem = {...base.problem, normalization_decision: 'D1-transform',
    source_meaning: '$\\forall u\\in[1,4], f(u)>0$ 为假命题，求 $b$ 的范围。',
    normalized_text: '$\\exists u\\in[1,4], f(u)\\le0$，求 $b$ 的范围。'};
  base.intro.splice(1, 0, {id: 'D1-transform', title: '命题转化', source: 'authored',
    interaction: {type: 'choice', field: 'transformation', options: [
      {value: 'complement', label: base.problem.normalized_text},
      {value: 'wrong', label: '全称且不改变不等号', feedback: '量词与关系需要同时取反。'},
    ]}, expected_answer: {one_of: ['complement']},
    effects: {nodes: ['quantifiers'], edges: [], calls: [], results: [base.problem.normalized_text]}});
  return base;
}

test('conversion is optional, and only the accepted canonical condition changes teaching context', () => {
  const base = convertedBase();
  let state = answer(base, createState(base));
  assert.equal(currentDecision(base, state).id, 'D1-transform');
  assert.equal(teachingContext(base, state).meaning, base.problem.source_meaning);
  const wrong = answer(base, state, 'wrong');
  assert.equal(wrong.lastFeedback.status, 'wrong');
  assert.equal(currentDecision(base, wrong).id, 'D1-transform');
  assert.equal(teachingContext(base, wrong).transformed, false);
  const outOfOrder = submitAnswer(base, wrong, {decision: 'D2', answer: base.intro[2].expected_answer.one_of[0]});
  assert.equal(outOfOrder.lastFeedback.status, 'wrong');
  assert.equal(currentDecision(base, outOfOrder).id, 'D1-transform');
  assert.equal(teachingContext(base, outOfOrder).transformed, false);
  state = answer(base, wrong);
  assert.equal(currentDecision(base, state).id, 'D2');
  assert.equal(teachingContext(base, state).text, base.problem.normalized_text);
  assert.equal(teachingContext(base, undo(base, state)).transformed, false);
  const plain = original.bundle;
  assert.equal(currentDecision(plain, answer(plain, createState(plain))).id, 'D2');
  assert.equal(teachingContext(plain, createState(plain)).text, plain.problem.text);
});

test('conversion survives stream migration and route switches and rewinds with replay', () => {
  const base = convertedBase(), stream = extendStreamBundle(base, withMath, target, graph);
  let state = createState(base);
  for (const _step of base.intro) state = answer(base, state);
  const migrated = migrateStageTwoState(base, stream, state);
  assert.equal(currentDecision(stream, migrated).id, 'D3');
  assert.equal(teachingContext(stream, migrated).text, base.problem.normalized_text);
  const choice = currentDecision(stream, migrated);
  state = answer(stream, migrated, [...choice.expected_answer.cell,
    choice.interaction.methods.find(method => method.route === 'discriminant').value]);
  assert.equal(teachingContext(stream, switchRoute(stream, state, 'extremum')).transformed, true);
  const replay = {schemaVersion: 2, problemId: base.problemId, bundleVersion: base.bundleVersion,
    status: 'partial', routes: [], actions: migrated.events.map(event => event.action)};
  assert.equal(teachingContext(base, replayState(base, replay, 1)).transformed, false);
  assert.equal(teachingContext(base, replayState(base, replay, 2)).transformed, true);
  assert.equal(teachingContext(stream, refreshStreamState(stream, JSON.parse(JSON.stringify(state)))).transformed, true);
});
const methodOf = {discriminant: 'method-discriminant', extremum: 'method-separation'};

test('identity is fixed before selection arrives and D1/D2 answers survive append-only expansion', () => {
  const waiting = extendStreamBundle(original.bundle, identity, target, graph);
  let state = answer(waiting, createState(waiting));
  state = answer(waiting, state);
  assert.equal(currentDecision(waiting, state), null);
  const bundle = extendStreamBundle(waiting, view, target, graph);
  assert.equal(bundle.bundleVersion, waiting.bundleVersion);
  assert.deepEqual(bundle.intro.slice(0, 2), original.bundle.intro);
  assert.equal(currentDecision(bundle, state).id, 'D3');
  const later = extendStreamBundle(bundle, withMath, target, graph);
  assert.equal(later.bundleVersion, bundle.bundleVersion);
  assert.deepEqual(state.introCompleted.map(item => item.decision), ['D1', 'D2']);
  assert.deepEqual(later.routes.discriminant.steps.map(item => item.interaction.type), ['read', 'read']);
  assert.equal(later.stream.math_steps.length, 2);
  assert.deepEqual(original.bundle.routes, {});
});

test('stage-two answers migrate once into the same base lesson without losing undo or wrong attempts', () => {
  const base = original.bundle, stream = extendStreamBundle(base, view, target, graph);
  let state = submitAnswer(base, createState(base), {decision: 'D1', answer: ['wrong']});
  state = answer(base, state);
  state = answer(base, state);
  const before = structuredClone(state);
  const migrated = migrateStageTwoState(base, stream, JSON.parse(JSON.stringify(state)));
  assert.equal(currentDecision(stream, migrated).id, 'D3');
  assert.deepEqual(migrated.introCompleted, state.introCompleted);
  assert.deepEqual(migrated.events, state.events);
  assert.deepEqual(state, before);
  const oldUndo = undo(base, state), newUndo = undo(stream, migrated);
  assert.deepEqual(newUndo.introCompleted, oldUndo.introCompleted);
  assert.deepEqual(newUndo.events, oldUndo.events);
  assert.equal(currentDecision(stream, newUndo).id, 'D2');
  assert.equal(currentDecision(stream, migrateStageTwoState(base, stream, oldUndo)).id, 'D2');
  const nextRun = extendStreamBundle(base, {...view, run_id: 'new-run'}, target, graph);
  for (const bad of [migrated, {...state, bundleVersion: 'other'}, {...state, run: {...state.run, route: 'discriminant'}},
    {...state, introCompleted: []}, {...state, events: [...state.events, {kind: 'switch_route', route: 'extremum'}]}]) {
    assert.throws(() => migrateStageTwoState(base, nextRun, bad), /invalid_stage_two_progress/);
  }
  assert.throws(() => migrateStageTwoState({...base, problemId: 'different'}, stream, state), /invalid_stage_two_progress/);
});

test('choosing a Q01 method in D3 starts its route without asking for the route again', () => {
  const bundle = extendStreamBundle(original.bundle, view, target, graph);
  assert.deepEqual(bundle.intro.map(item => item.id), ['D1', 'D2', 'D3']);
  for (const route of ['discriminant', 'extremum']) {
    const state = selected(bundle, route);
    assert.equal(state.lastFeedback.status, 'passed');
    assert.equal(state.run.route, route);
    assert.equal(state.done, false);
    assert.equal(currentDecision(bundle, state), null);
    assert.deepEqual(state.introCompleted.map(item => item.decision), ['D1', 'D2', 'D3']);
    assert.deepEqual(state.run.completed, []);
    const replay = {...original.replay, bundleVersion: bundle.bundleVersion, routes: [route], status: 'partial',
      actions: state.events.map(event => event.action)};
    assert.deepEqual(replayState(bundle, replay), state);
  }
});

test('a mathematically fit method with a capability gap is explained in D3 and cannot start reading', () => {
  const gapView = structuredClone(view);
  gapView.selection_chunks[1].chunk.options[1].route_plan = 'capability_gap';
  gapView.selection_chunks[1].chunk.options[1].message = '详细步骤暂不支持';
  const bundle = extendStreamBundle(original.bundle, gapView, target, graph);
  const state = selected(bundle, 'extremum');
  assert.equal(state.lastFeedback.status, 'uncovered');
  assert.equal(state.lastFeedback.message, '详细步骤暂不支持');
  assert.equal(currentDecision(bundle, state).id, 'D3');
  assert.equal(state.introCompleted.length, 2);
  assert.equal(state.run.route, null);
  assert.equal(state.done, false);
  assert.equal(evidenceView(bundle, state, {steps: [first], route: 'extremum'}).calls.length, 0);
  const usable = selected(bundle, 'discriminant');
  assert.equal(usable.lastFeedback.status, 'passed');
  assert.equal(usable.run.route, 'discriminant');
  assert.throws(() => switchRoute(bundle, usable, 'extremum'), /暂不支持/);
});

test('progress saved with the former D4 route question resumes from D3 alone', () => {
  const bundle = extendStreamBundle(original.bundle, withMath, target, graph);
  const current = selected(bundle);
  const legacy = structuredClone(current);
  const d4 = {decision: 'D4', answer: 'discriminant', reason: '', results: [], calls: [], runId: current.run.id};
  legacy.introCompleted.push(d4);
  legacy.events.push({kind: 'answer', action: {decision: 'D4', answer: 'discriminant'}, status: 'passed', runId: current.run.id});
  legacy.streamIntroEvents.push(structuredClone(legacy.events.at(-1)));
  legacy.lastFeedback = {status: 'passed', decision: 'D4'};
  const restored = refreshStreamState(bundle, legacy);
  assert.deepEqual(restored.introCompleted, current.introCompleted);
  assert.deepEqual(restored.events, current.events);
  assert.deepEqual(restored.streamIntroEvents, current.streamIntroEvents);
  assert.equal(restored.lastFeedback, null);
  assert.equal(currentDecision(bundle, restored).id, bundle.routes.discriminant.steps[0].id);
});

test('legacy D4 overriding D3 migrates the actual selected route and preserves wrong attempts and progress', () => {
  const routeCard = {...first, route_id: 'extremum', method_ref: 'method-separation#separate'};
  const bundle = extendStreamBundle(original.bundle, {...view, math_steps: [routeCard]}, target, graph);
  // Exercise the former four-question flow through the real grader and state writer. Disabling stream migration
  // while authoring this legacy record lets D4 be answered after D3, as it was before the format change.
  const legacyBundle = {...bundle, stream: null, intro: [...bundle.intro, {id: 'D4', source: 'authored',
    interaction: {type: 'choice', field: 'route', options: d4.options.map(option => ({value: option.route_id, label: option.route_id}))},
    expected_answer: {one_of: d4.options.map(option => option.route_id)},
    route_by_answer: Object.fromEntries(d4.options.map(option => [option.route_id, option.route_id])),
    effects: {results: [], calls: []}}]};
  let legacy = selected(legacyBundle, 'discriminant');
  legacy = answer(legacyBundle, legacy, 'not-a-route');
  assert.equal(legacy.lastFeedback.status, 'wrong');
  legacy = answer(legacyBundle, legacy, 'extremum');
  assert.equal(legacy.lastFeedback.status, 'passed');
  legacy = answer(legacyBundle, legacy, 'read');
  assert.equal(legacy.lastFeedback.status, 'passed');
  assert.equal(legacy.run.route, 'extremum');
  assert.equal(legacy.introCompleted.find(entry => entry.decision === 'D3').answer[2], 'discriminant');
  legacy.streamIntroEvents = structuredClone(legacy.events.filter(event => ['D1', 'D2', 'D3', 'D4'].includes(event.action.decision)));
  const wrongD3 = {kind: 'answer', action: {decision: 'D3', answer: ['interval', 'free', 'discriminant']}, status: 'wrong', runId: legacy.run.id};
  legacy.events.splice(2, 0, wrongD3);
  legacy.streamIntroEvents.splice(2, 0, structuredClone(wrongD3));
  const before = structuredClone(legacy);
  for (const waitingFirst of [false, true]) {
    let restored = JSON.parse(JSON.stringify(legacy));
    if (waitingFirst) {
      const waiting = extendStreamBundle(original.bundle, identity, target, graph);
      restored = refreshStreamState(waiting, restored);
      assert.ok(restored.introCompleted.some(entry => entry.decision === 'D4'), 'defer migration until the route mapping arrives');
    }
    restored = refreshStreamState(bundle, restored);
    assert.deepEqual(restored.run, before.run);
    assert.deepEqual(restored.introCompleted.slice(0, 2), before.introCompleted.slice(0, 2));
    assert.deepEqual(restored.introCompleted.find(entry => entry.decision === 'D3').answer,
      [...bundle.intro.find(item => item.id === 'D3').expected_answer.cell, 'separation']);
    for (const events of [restored.events, restored.streamIntroEvents]) {
      assert.equal(events.some(event => event.action.decision === 'D4'), false);
      assert.deepEqual(events.find(event => event.action.decision === 'D3' && event.status === 'wrong'), wrongD3);
      assert.equal(events.find(event => event.action.decision === 'D3' && event.status === 'passed').action.answer[2], 'separation');
    }
    assert.equal(graphState(bundle, restored).nodes['method-separation'], 'confirmed');
    assert.deepEqual(refreshStreamState(bundle, restored), restored, 'migration is idempotent');
    const undone = undo(bundle, restored);
    assert.equal(currentDecision(bundle, undone).id, routeCard.step_id);
    assert.equal(undone.run.route, 'extremum');
    assert.deepEqual(switchRoute(bundle, switchRoute(bundle, restored, 'discriminant'), 'extremum').run, restored.run);
  }
  assert.deepEqual(legacy, before, 'migration does not mutate the stored source record');
});

test('route changes preserve target decisions and undo stays on the current route after refresh', () => {
  const bundle = extendStreamBundle(original.bundle, withMath, target, graph);
  const prior = selected(bundle);
  const changed = switchRoute(bundle, prior, 'extremum');
  assert.deepEqual(changed.introCompleted.slice(0, 2), prior.introCompleted.slice(0, 2));
  assert.equal(changed.introCompleted[2].answer[2], 'separation');
  assert.equal(changed.run.route, 'extremum');
  const restored = JSON.parse(JSON.stringify(changed));
  assert.equal(graphState(bundle, restored).nodes['method-separation'], 'confirmed');
  assert.deepEqual(undo(bundle, restored).run, changed.run);
  assert.equal(switchRoute(bundle, restored, 'discriminant').run.route, 'discriminant');
});

test('new calculation data does not illuminate unread skills or future mathematics', () => {
  const bundle = extendStreamBundle(original.bundle, withMath, target, graph);
  const state = selected(bundle);
  const initial = evidenceView(bundle, state);
  assert.equal(initial.nodes['skill-inequality-transform'], 'idle');
  assert.equal(initial.nodes['skill-quadratic-sign'], 'idle');
  assert.equal(initial.calls.length, 0);
  const reached = evidenceView(bundle, state, {steps: [first]});
  assert.equal(reached.nodes['skill-inequality-transform'], 'confirmed');
  assert.equal(reached.edges['method-discriminant|calls|skill-inequality-transform'], 'chosen');
  assert.ok(reached.usedBasis.includes('inequality-properties#addition'));
  assert.equal(reached.nodes['skill-quadratic-sign'], 'idle');
  assert.equal(reached.calls.length, 1);
  assert.equal(reached.calls[0].decision, first.step_id);
  assert.equal(reached.calls[0].ref, 'skill-inequality-transform');
  assert.equal(state.events.length, 3); // Reading is not an invented graded answer.
});

test('graph evidence is scoped by run, target, route, step identity and mathematical hash', () => {
  const bundle = extendStreamBundle(original.bundle, withMath, target, graph);
  const state = selected(bundle);
  for (const bad of [{...first, run_id: 'old'}, {...first, target_ref: '/root/children/0/goals/0'},
    {...first, route_id: 'extremum'}, {...first, step_id: 'unknown'}, {...first, math_step_sha256: 'changed'}]) {
    assert.equal(evidenceView(bundle, state, {steps: [bad]}).calls.length, 0);
  }
  assert.equal(evidenceView(bundle, state, {steps: [first, first]}).calls.length, 1);
  assert.equal(evidenceView(bundle, state, {steps: [first], route: 'extremum'}).calls.length, 0);
  const early = answer(bundle, createState(bundle));
  assert.equal(evidenceView(bundle, early, {steps: [first], route: 'discriminant'}).calls.length, 0);
});

test('snapshot and incremental trajectory evidence produce the same reached graph', () => {
  const incremental = {...withMath, checkpoints: [], trajectories: [{target_ref: target, route_id: 'discriminant',
    steps: checkpoint.driver_state.trajectory.steps}]};
  const a = extendStreamBundle(original.bundle, withMath, target, graph);
  const b = extendStreamBundle(original.bundle, incremental, target, graph);
  assert.deepEqual(evidenceView(a, selected(a), {steps: [first, second]}),
    evidenceView(b, selected(b), {steps: [first, second]}));
  const noEvidence = extendStreamBundle(original.bundle, {...withMath, checkpoints: []}, target, graph);
  assert.equal(evidenceView(noEvidence, selected(noEvidence), {steps: [first]}).calls.length, 0);
});

test('QA and arrival order never rewrite mathematical data or selection identities', () => {
  const bundle = extendStreamBundle(original.bundle, withMath, target, graph);
  assert.deepEqual(extendStreamBundle(bundle, {...withMath, qa: [{qa: {hints: ['提示']}}]}, target, graph), bundle);
  assert.throws(() => extendStreamBundle(bundle, {...view, run_id: 'old'}, target, graph), /identity_mismatch/);
  const changed = structuredClone(withMath);
  changed.math_steps[0].title = '偷偷改正文';
  assert.throws(() => extendStreamBundle(bundle, changed, target, graph), /immutable_math_step/);
  const changedSelection = structuredClone(withMath);
  changedSelection.selection_chunks[0].chunk.title = '改变选法';
  assert.throws(() => extendStreamBundle(bundle, changedSelection, target, graph), /immutable_selection/);
});

const q03Evidence = read('./fixtures/graph-stage-three-q03-evidence.json');
const q03Bundle = snapshot => extendStreamBundle(original.bundle, snapshot, target, graph);
const q03Reached = (snapshot, steps) => {
  const bundle = q03Bundle(snapshot);
  return evidenceView(bundle, selected(bundle), {steps});
};

test('Q03 checked internal operations light their bases only after their own card is read', () => {
  const bundle = q03Bundle(q03Evidence), state = selected(bundle);
  const [classification, negativeCase, positiveCase, , , , solution, merge, boundary] = q03Evidence.math_steps;
  const unread = evidenceView(bundle, state);
  assert.equal(unread.nodes['linear-interval-extremum'], 'idle');
  assert.ok(!unread.usedBasis.includes('method-discriminant#merge'));
  const classified = evidenceView(bundle, state, {steps: [classification]});
  assert.equal(classified.nodes['linear-interval-extremum'], 'idle');
  for (const card of [negativeCase, positiveCase]) {
    const reached = evidenceView(bundle, state, {steps: [card]});
    assert.equal(reached.nodes['linear-interval-extremum'], 'confirmed');
    assert.ok(reached.usedBasis.includes('method-discriminant#degree'));
    assert.ok(reached.usedBasis.includes('quadratic-function-properties#definition'));
    assert.ok(!reached.usedBasis.includes('method-discriminant#merge'));
    assert.equal(reached.calls.length, 0); // No synthetic public call for an internal operation.
  }
  const solved = evidenceView(bundle, state, {steps: [solution]});
  assert.ok(solved.usedBasis.includes('method-discriminant#solve'));
  assert.equal(solved.nodes['skill-solve-quadratic'], 'confirmed');
  assert.ok(!solved.usedBasis.includes('method-discriminant#merge'));
  const merged = evidenceView(bundle, state, {steps: [merge]});
  assert.ok(merged.usedBasis.includes('method-discriminant#merge'));
  assert.equal(merged.nodes['linear-interval-extremum'], 'idle'); // No scan of earlier cases.
  assert.equal(merged.calls.length, 0);
  assert.ok(evidenceView(bundle, state, {steps: [boundary]}).usedBasis.includes('function-range-extrema#attainability'));
});

test('Q03 card basis claims cannot bypass source, branch and nonempty local-check validation', () => {
  const caseIndex = 1;
  const base = structuredClone(q03Evidence);
  base.math_steps[caseIndex].used_basis.push('inequality-properties#addition', 'invented-basis');
  const reached = q03Reached(base, [base.math_steps[caseIndex]]);
  assert.ok(!reached.usedBasis.includes('inequality-properties#addition'));
  assert.ok(!reached.usedBasis.includes('invented-basis'));
  assert.equal(reached.nodes['invented-basis'], undefined);
  const invalid = [
    value => value.checkpoints[0].driver_state.trajectory.steps[1].calls[0].postconditions = [],
    value => delete value.checkpoints[0].driver_state.trajectory.steps[1].calls[0].postconditions,
    value => value.checkpoints[0].driver_state.trajectory.steps[1].calls[0].postconditions[0].passed = false,
    value => value.checkpoints[0].driver_state.trajectory.steps[1].calls[0].postconditions[0].passed = 'true',
    value => value.checkpoints[0].driver_state.trajectory.steps[1].case_path = ['degenerate-1'],
    value => value.checkpoints[0].driver_state.trajectory.steps[1].calls[0].case_path = ['degenerate-1'],
    value => value.checkpoints[0].route_id = 'extremum',
    value => value.checkpoints[0].target_ref = '/root/children/0/goals/0',
    value => value.math_steps[caseIndex].source_refs = ['/steps/8/skipped_calls/0'],
    value => value.math_steps[caseIndex].source_refs = ['/steps/0/judgments/0'],
    value => value.math_steps[caseIndex].source_refs = ['/steps/999/calls/0'],
  ];
  for (const mutate of invalid) {
    const snapshot = structuredClone(base);
    mutate(snapshot);
    const result = q03Reached(snapshot, [snapshot.math_steps[caseIndex]]);
    assert.ok(!result.usedBasis.includes('linear-interval-extremum'));
    assert.ok(!result.usedBasis.includes('method-discriminant#degree'));
    assert.equal(result.calls.length, 0);
  }
  const unverifiedBoundary = structuredClone(base);
  unverifiedBoundary.checkpoints[0].driver_state.trajectory.finalization[2].postconditions = [];
  assert.ok(!q03Reached(unverifiedBoundary, [unverifiedBoundary.math_steps.at(-1)]).usedBasis.includes('function-range-extrema#attainability'));
});

test('unchecked public calls cannot light a skill or inherit a card basis claim', () => {
  for (const postconditions of [undefined, [], [{passed: false}], [{passed: true}, {passed: false}]]) {
    const changed = structuredClone(withMath);
    changed.checkpoints[0].driver_state.trajectory.steps[0].calls[0].postconditions = postconditions;
    const bundle = extendStreamBundle(original.bundle, changed, target, graph);
    const reached = evidenceView(bundle, selected(bundle), {steps: [first]});
    assert.equal(reached.calls.length, 0);
    assert.notEqual(reached.nodes['skill-inequality-transform'], 'confirmed');
    assert.ok(!reached.usedBasis.includes('inequality-properties#addition'));
  }
});

test('Q03 snapshot and committed events give identical internal, public and boundary graph evidence', () => {
  const snapshotConsumer = createEventConsumer(q03Evidence);
  snapshotConsumer.hydrate(q03Evidence);
  const eventConsumer = createEventConsumer(q03Evidence);
  let seq = 0;
  const emit = (type, payload, route = null) => eventConsumer.accept({
    run_id: q03Evidence.run_id, lesson_version: q03Evidence.lesson_version, stream_id: q03Evidence.stream_id,
    event_id: `event-${++seq}`, seq, type, target_ref: target, route_id: route, payload,
  });
  for (const {kind, chunk} of q03Evidence.selection_chunks) emit('lesson.chunk_ready', {kind, chunk});
  const trajectory = q03Evidence.checkpoints[0].driver_state.trajectory;
  emit('solver.step_completed', {trajectory: trajectory.steps}, 'discriminant');
  for (const card of q03Evidence.math_steps) {
    if (card.source_refs[0].startsWith('/finalization/')) {
      // The sparse event carries the original index, never a compacted array.
      emit('solver.step_completed', {trajectory: [], operation: 'endpoint_check',
        finalization: [{index: 2, record: trajectory.finalization[2]}]}, 'discriminant');
    }
    emit('lesson.chunk_ready', {kind: 'math_step', step_id: card.step_id,
      math_step_sha256: card.math_step_sha256, chunk: card}, 'discriminant');
    const snapshotGraph = q03Reached({...snapshotConsumer.view(),
      math_steps: q03Evidence.math_steps.filter(step => step.ordinal <= card.ordinal)}, [card]);
    const eventGraph = q03Reached(eventConsumer.view(), [card]);
    assert.deepEqual(eventGraph, snapshotGraph);
  }
  const finalView = eventConsumer.view();
  assert.deepEqual(finalView.trajectories[0].finalization.map(item => item.index), [2]);
  assert.ok(q03Reached(finalView, [q03Evidence.math_steps.at(-1)]).usedBasis.includes('function-range-extrema#attainability'));
  assert.throws(() => emit('solver.step_completed', {trajectory: [], finalization: [{index: 2,
    record: {...trajectory.finalization[2], used_basis: ['invented-basis']}}]}, 'discriminant'), /immutable_finalization_source/);
});

// Minimal Q05 interval-envelope trace: the actual public graph declares this
// skill under the select-step rule, so there is no direct method/calls edge.
const intervalCard = {...first, route_id: 'interval', method_ref: 'method-interval-extremum#select',
  source_refs: ['/steps/1/calls/0'], used_basis: ['quadratic-interval-extremum'], title: '区间端点候选'};
const intervalRecord = {seq: 2, method: 'method-interval-extremum', step: 'select', case_path: [], calls: [{
  public_ref: 'quadratic-interval-extremum', rule_ref: 'rule-interval-skill', branch: 'quadratic',
  used_basis: ['quadratic-interval-extremum'], postconditions: [{passed: true}],
}]};
const intervalView = {...identity, math_steps: [intervalCard], selection_chunks: [
  {target_ref: target, kind: 'D3', chunk: {...structuredClone(d3), expected_answer: {cell: ['interval', 'free']}}},
  {target_ref: target, kind: 'D4', chunk: {id: 'D4', title: '解题路线', options: [
    {branch: 'interval', route_id: 'interval', method: 'method-interval-extremum', route_plan: 'planned', recommendation: 'preferred'},
  ]}},
], checkpoints: [{target_ref: target, route_id: 'interval', driver_state: {trajectory: {steps: [intervalRecord]}}}]};
const intervalRuleEdge = 'method-interval-extremum|step_rule|rule-interval-skill';
const intervalSkillEdge = 'rule-interval-skill|selects|quadratic-interval-extremum';
const syntheticIntervalEdge = 'method-interval-extremum|calls|quadratic-interval-extremum';
const intervalReached = snapshot => {
  const bundle = extendStreamBundle(original.bundle, snapshot, target, graph);
  return evidenceView(bundle, selected(bundle, 'interval'), {steps: snapshot.math_steps});
};

test('read checked rule calls light the real method/rule/skill path with no synthetic calls edge', () => {
  const bundle = extendStreamBundle(original.bundle, intervalView, target, graph);
  const state = selected(bundle, 'interval');
  const unread = evidenceView(bundle, state);
  assert.equal(unread.nodes['rule-interval-skill'], 'idle');
  assert.equal(unread.edges[intervalRuleEdge], 'idle');
  assert.equal(unread.edges[intervalSkillEdge], 'idle');
  const reached = evidenceView(bundle, state, {steps: [intervalCard]});
  assert.equal(reached.nodes['rule-interval-skill'], 'confirmed');
  assert.equal(reached.nodes['quadratic-interval-extremum'], 'confirmed');
  assert.equal(reached.edges[intervalRuleEdge], 'chosen');
  assert.equal(reached.edges[intervalSkillEdge], 'chosen');
  assert.equal(reached.edges[syntheticIntervalEdge], undefined);
  assert.equal(reached.calls.length, 1);
  assert.equal(reached.calls[0].rule_ref, 'rule-interval-skill');
  assert.equal(reached.calls[0].branch, 'quadratic');
  assert.equal(reached.calls[0].edge, intervalSkillEdge);
  assert.deepEqual(reached.calls[0].rule_edges, [intervalRuleEdge, intervalSkillEdge]);
  assert.equal(reached.calls[0].occurrence, 0);
});

test('wrong rule, branch, method step, target and unchecked or skipped sources cannot invent a rule path', () => {
  const mutations = [
    record => record.calls[0].rule_ref = 'rule-quadratic-method',
    record => record.calls[0].rule_ref = 'rule-interval-skill#invented',
    record => record.calls[0].branch = 'linear',
    record => record.calls[0].branch = '',
    record => delete record.calls[0].rule_ref,
    record => delete record.calls[0].branch,
    record => { delete record.calls[0].rule_ref; delete record.calls[0].branch; },
    record => record.step = 'conditions',
    record => record.calls[0].public_ref = 'skill-reciprocal-range',
    record => record.calls[0].postconditions = [],
    record => record.calls[0].postconditions[0].passed = false,
  ];
  for (const mutate of mutations) {
    const snapshot = structuredClone(intervalView);
    mutate(snapshot.checkpoints[0].driver_state.trajectory.steps[0]);
    const reached = intervalReached(snapshot);
    assert.equal(reached.calls.length, 0);
    assert.notEqual(reached.nodes['rule-interval-skill'], 'confirmed');
    assert.notEqual(reached.edges[intervalRuleEdge], 'chosen');
    assert.notEqual(reached.edges[intervalSkillEdge], 'chosen');
    assert.equal(reached.edges[syntheticIntervalEdge], undefined);
  }
  const skipped = structuredClone(intervalView);
  skipped.math_steps[0].source_refs = ['/steps/1/skipped_calls/0'];
  assert.equal(intervalReached(skipped).calls.length, 0);
  const wrongGraph = structuredClone(graph);
  wrongGraph.edges.find(item => item.id === intervalRuleEdge).occurrences[0].step = 'other';
  const bundle = extendStreamBundle(original.bundle, intervalView, target, wrongGraph);
  assert.equal(evidenceView(bundle, selected(bundle, 'interval'), {steps: [intervalCard]}).calls.length, 0);
});

test('rule metadata never falls back to a valid direct method/skill edge', () => {
  const snapshot = structuredClone(withMath);
  const call = snapshot.checkpoints[0].driver_state.trajectory.steps[0].calls[0];
  Object.assign(call, {rule_ref: 'rule-interval-skill', branch: 'quadratic'});
  const bundle = extendStreamBundle(original.bundle, snapshot, target, graph);
  const reached = evidenceView(bundle, selected(bundle), {steps: [first]});
  assert.equal(reached.calls.length, 0);
  assert.notEqual(reached.edges['method-discriminant|calls|skill-inequality-transform'], 'chosen');
});

test('rule-directed snapshot and per-event reconstruction retain identical checked paths', () => {
  const snapshot = {...intervalView, last_seq: 0, minimum_seq: 0};
  const consumer = createEventConsumer(snapshot);
  let seq = 0;
  const emit = (type, payload, route_id = null) => consumer.accept({...identity,
    event_id: `rule-event-${++seq}`, seq, type, target_ref: target, route_id, payload});
  for (const {kind, chunk} of snapshot.selection_chunks) emit('lesson.chunk_ready', {kind, chunk});
  emit('solver.step_completed', {trajectory: [intervalRecord]}, 'interval');
  emit('lesson.chunk_ready', {kind: 'math_step', chunk: intervalCard,
    step_id: intervalCard.step_id, math_step_sha256: intervalCard.math_step_sha256}, 'interval');
  assert.deepEqual(intervalReached(consumer.view()), intervalReached(snapshot));
});
