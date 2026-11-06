import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {
  createState, currentDecision, gradeDecision, submitAnswer, undo, switchRoute, replayState,
  extendStreamBundle, refreshStreamState, streamGraphState, streamStepGraph, setStreamDraft, streamDraft,
} from '../../site/assets/graph-walk/walk-state.mjs';

const read = path => JSON.parse(fs.readFileSync(new URL(path, import.meta.url), 'utf8'));
const base = read('../../site/lab/search/demo-lesson-q01.json').goals[0].walk.bundle;
const graph = read('../../site/knowledge/graph.json');
const d3 = read('../../site/data/graph-walk/quadratic-always-q01.source.json').intro.find(item => item.id === 'D3');
const target = '/root/goals/0';
const identity = {run_id: 'run-current', lesson_version: 'lesson-current', stream_id: 'run-current'};
const methods = {discriminant: 'method-discriminant', extremum: 'method-separation'};
const d4 = {id: 'D4', title: '解题路线', options: Object.entries(methods).map(([route, method]) => ({
  branch: route === 'extremum' ? 'separation' : route, route_id: route, method, route_plan: 'planned',
}))};
const protocol = 'graph-step-interaction/v1';
const card = (ordinal, route = 'discriminant') => ({...identity, target_ref: target, route_id: route,
  step_id: `${route}-${ordinal}`, ordinal, local_check: 'passed', math_step_sha256: `${route}-hash-${ordinal}`,
  method_ref: `${methods[route]}#normalize`, title: `数学步骤 ${ordinal}`, source_refs: ['/steps/0/calls/0'],
  before: ['before'], after: ['after'], explanation: '经过局部检查的结论'});
const part = id => ({id, title: '选出条件', question: '请选择正确条件', interaction: {type: 'choice', field: 'answer',
  options: [{value: 'correct', label: '正确'}, {value: 'wrong', label: '错误', feedback: '再检查边界。'}]},
  expected_answer: {one_of: ['correct']}, feedback: {answer: '再试一次。'}, submit_label: '确认'});
function chunk(cards, parts = [part(`question-${cards[0].step_id}`)]) {
  return {...identity, contract: protocol, target_ref: target, route_id: cards[0].route_id,
    interaction_id: `group-${cards.map(item => item.step_id).join('+')}`, interaction_revision: 'revision-1',
    status: parts.length ? 'interactive' : 'readonly', parts,
    steps: cards.map(({step_id, math_step_sha256}) => ({step_id, math_step_sha256}))};
}
function view(cards, chunks = [], extra = {}) {
  return {...identity, interaction_protocol: protocol,
    selection_chunks: [{target_ref: target, kind: 'D3', chunk: d3}, {target_ref: target, kind: 'D4', chunk: d4}],
    math_steps: cards,
    interaction_states: cards.map(item => {
      const group = chunks.find(group => group.route_id === item.route_id && group.steps.some(ref => ref.step_id === item.step_id));
      return {target_ref: target, route_id: item.route_id, step_id: item.step_id, ordinal: item.ordinal,
        math_step_sha256: item.math_step_sha256, status: group?.status || 'pending',
        ...(group ? {interaction_id: group.interaction_id} : {})};
    }), interactions: chunks, ...extra};
}
const bundleFor = (cards, chunks = [], extra = {}) => extendStreamBundle(base, view(cards, chunks, extra), target, graph);
const answer = (bundle, state, value) => {
  const decision = currentDecision(bundle, state);
  return submitAnswer(bundle, state, {decision: decision.id, answer: value ?? (decision.interaction.type === 'read' ? 'read'
    : decision.interaction.type === 'checklist' ? decision.expected_answer.terms : decision.expected_answer.one_of[0])});
};
function selected(bundle, route = 'discriminant') {
  let state = createState(bundle);
  state = answer(bundle, state); state = answer(bundle, state);
  const decision = currentDecision(bundle, state), method = decision.interaction.methods.find(item => item.route === route);
  return answer(bundle, state, [...decision.expected_answer.cell, method.value]);
}
const finished = route => ({checkpoints: [{target_ref: target, route_id: route, status: 'verified'}]});
const evidence = (ref = 'skill-inequality-transform') => ({trajectories: [{target_ref: target, route_id: 'discriminant', steps: [{
  seq: 1, method: 'method-discriminant', step: 'normalize', calls: [{public_ref: ref,
    used_basis: ['inequality-properties#addition'], postconditions: [{passed: true}]}],
}]}]});

test('pending is an ordered barrier even when later cards and math completion have arrived', () => {
  const cards = [card(1), card(2), card(3)], later = [chunk([cards[1]], []), chunk([cards[2]])];
  let bundle = bundleFor(cards, later, finished('discriminant'));
  assert.deepEqual(bundle.routes.discriminant.steps, []);
  let state = selected(bundle);
  assert.equal(currentDecision(bundle, state), null);
  assert.equal(refreshStreamState(bundle, state).done, false);
  const first = chunk([cards[0]]);
  bundle = extendStreamBundle(bundle, view(cards, [first, ...later], finished('discriminant')), target, graph);
  state = refreshStreamState(bundle, state);
  assert.deepEqual(bundle.routes.discriminant.steps.map(item => item.interaction.type), ['choice', 'read', 'choice']);
  assert.equal(currentDecision(bundle, state).id, first.parts[0].id);
  while (currentDecision(bundle, state)) state = answer(bundle, state);
  assert.equal(state.done, true);
});

test('a first pending math event cannot become a legacy read before protocol metadata arrives', () => {
  const cards = [card(1)], pending = view(cards, [], {interaction_protocol: null});
  const bundle = extendStreamBundle(base, pending, target, graph);
  assert.deepEqual(bundle.routes.discriminant.steps, []);
  assert.equal(bundle.stream.interaction_protocol, protocol);
  const resolved = extendStreamBundle(bundle, view(cards, [chunk(cards)]), target, graph);
  assert.equal(resolved.routes.discriminant.steps[0].interaction.type, 'choice');
});

test('folded cards arriving before their follower stay pending and never publish a temporary read', () => {
  const cards = [card(1), card(2), card(3)];
  const folded = cards.slice(0, 2).map(item => ({...chunk([item], []), reason: 'folded'}));
  let bundle = bundleFor(cards.slice(0, 1), folded.slice(0, 1));
  let state = selected(bundle);
  assert.deepEqual(bundle.routes.discriminant.steps, []);
  assert.equal(bundle.routes.discriminant.pending_count, 1);
  assert.equal(bundle.routes.discriminant.interactions_complete, false);
  assert.equal(currentDecision(bundle, state), null);
  assert.equal(state.done, false);
  bundle = extendStreamBundle(bundle, view(cards.slice(0, 2), folded), target, graph);
  assert.deepEqual(bundle.routes.discriminant.steps, []);
  assert.equal(bundle.routes.discriminant.pending_count, 2);
  // Even after all mathematics finishes, wait for the follower's interaction result.
  bundle = extendStreamBundle(bundle, view(cards, folded, finished('discriminant')), target, graph);
  assert.deepEqual(bundle.routes.discriminant.steps, []);
  assert.equal(bundle.routes.discriminant.pending_count, 3);
  assert.equal(refreshStreamState(bundle, state).done, false);
  const follower = chunk([cards[2]]);
  bundle = extendStreamBundle(bundle, view(cards, [...folded, follower], finished('discriminant')), target, graph);
  assert.deepEqual(bundle.routes.discriminant.steps.map(item => item.id), [follower.parts[0].id]);
  assert.deepEqual(bundle.routes.discriminant.steps[0].stream_folded, cards.slice(0, 2).map(item => item.step_id));
  state = refreshStreamState(bundle, state);
  state = answer(bundle, state);
  assert.equal(state.done, true);
  assert.equal(bundle.routes.discriminant.pending_count, 0);
  assert.deepEqual(extendStreamBundle(bundle, view(cards, [...folded, follower], finished('discriminant')), target, graph)
    .routes.discriminant.steps, bundle.routes.discriminant.steps);
});

for (const status of ['running', 'interrupted']) test(`a folded tail stays pending while its route is ${status}`, () => {
  const cards = [card(1)], folded = [{...chunk(cards, []), reason: 'folded'}];
  const bundle = bundleFor(cards, folded, {checkpoints: [{target_ref: target, route_id: 'discriminant', status}]});
  assert.deepEqual(bundle.routes.discriminant.steps, []);
  assert.equal(bundle.routes.discriminant.pending_count, 1);
  assert.equal(refreshStreamState(bundle, selected(bundle)).done, false);
});

for (const terminal of [
  finished('discriminant'),
  {completions: [{identity: [target, 'discriminant'], status: 'verified', available: true}]},
  {route_statuses: [[JSON.stringify([target, 'discriminant']), {status: 'math_failed'}]]},
]) test(`a genuinely terminal folded tail becomes a stable read: ${JSON.stringify(terminal)}`, () => {
  const cards = [card(1), card(2)], first = chunk([cards[0]]);
  const groups = [first, {...chunk([cards[1]], []), reason: 'folded'}];
  const running = bundleFor(cards, groups);
  const state = answer(running, selected(running));
  assert.equal(currentDecision(running, state), null);
  assert.equal(state.done, false);
  const ended = extendStreamBundle(running, view(cards, groups, terminal), target, graph);
  assert.deepEqual(ended.routes.discriminant.steps.map(item => item.interaction.type), ['choice', 'read']);
  assert.deepEqual(ended.routes.discriminant.steps[0], running.routes.discriminant.steps[0]);
  assert.equal(ended.routes.discriminant.interactions_complete, true);
  assert.deepEqual(extendStreamBundle(ended, view(cards, groups, terminal), target, graph).routes.discriminant.steps,
    ended.routes.discriminant.steps);
  const restored = refreshStreamState(ended, state);
  if (ended.routes.discriminant.available) assert.equal(answer(ended, restored).done, true);
  else assert.equal(currentDecision(ended, restored), null);
});

test('a merged multi-part group expands both cards only on its final part', () => {
  const cards = [card(1), card(2)], merged = chunk(cards, [part('first-question'), part('last-question')]);
  const bundle = bundleFor(cards, [merged], {...finished('discriminant'), ...evidence(null)});
  const decisions = bundle.routes.discriminant.steps;
  assert.deepEqual(decisions.map(item => item.stream_last_part), [false, true]);
  assert.deepEqual(decisions.map(item => [item.stream_part_index, item.stream_part_count]), [[0, 2], [1, 2]]);
  assert.deepEqual(new Set(decisions.map(item => item.stream_group_title)), new Set([cards.map(item => item.title).join(' · ')]));
  assert.deepEqual(decisions.map(item => item.stream_steps), [merged.steps, merged.steps]);
  assert.ok(decisions.every(item => item.source === 'stream' && !item.effects.calls.length && !item.effects.nodes.length));
  let state = selected(bundle);
  state = answer(bundle, state);
  assert.equal(state.run.completed[0].stream_last_part, false);
  assert.ok(!streamGraphState(bundle, state).usedBasis.includes('inequality-properties#addition'));
  state = answer(bundle, state);
  assert.equal(state.done, true);
  assert.ok(streamGraphState(bundle, state).usedBasis.includes('inequality-properties#addition'));
  assert.equal(streamGraphState(bundle, state).calls.length, 0);
  const undone = undo(bundle, state);
  assert.equal(currentDecision(bundle, undone).id, 'last-question');
  assert.equal(undone.done, false);
  assert.ok(!streamGraphState(bundle, undone).usedBasis.includes('inequality-properties#addition'));
});

test('later same-title chunks preserve published decisions, saved answers and both evidence boundaries', () => {
  const cards = [card(1), card(2)].map((item, index) => ({...item,
    highlight: {caption: '结论', items: [{label: '结果', math: 'a'}], result: `条件 ${index + 1}`}}));
  const groups = cards.map((item, index) => chunk([item], [{...part(`solve-${index}`),
    card_group: 'solve', card_group_title: '求参数'}]));
  let bundle = bundleFor(cards.slice(0, 1), groups.slice(0, 1));
  let state = answer(bundle, selected(bundle));
  const published = structuredClone(bundle.routes.discriminant.steps);
  const saved = JSON.parse(JSON.stringify(state));
  const complete = view(cards, groups, finished('discriminant'));
  bundle = extendStreamBundle(bundle, complete, target, graph);
  assert.deepEqual(bundle.routes.discriminant.steps.slice(0, 1), published);
  assert.deepEqual(bundle.routes.discriminant.steps, bundleFor(cards, groups, finished('discriminant')).routes.discriminant.steps);
  state = refreshStreamState(bundle, saved);
  assert.deepEqual(state.run.completed, saved.run.completed);
  assert.equal(currentDecision(bundle, state).id, 'solve-1');
  state = answer(bundle, state);
  assert.equal(state.done, true);
  assert.deepEqual(state.run.completed.map(row => row.stream_last_part), [true, true]);
  assert.deepEqual(state.run.completed.map(row => row.stream_steps), groups.map(group => group.steps));
  assert.deepEqual(state.run.completed.map(row => row.results), [['条件 1'], ['条件 2']]);
  const restored = refreshStreamState(bundle, JSON.parse(JSON.stringify(state)));
  assert.equal(restored.done, true);
  assert.deepEqual(streamGraphState(bundle, restored), streamGraphState(bundle, state));
});

test('a card result is carried by its last part and by a read card', () => {
  const highlight = result => ({caption: '结论', items: [{label: '结果', math: 'a'}], result});
  const cards = [{...card(1), highlight: highlight('$a \\geq h(x)$')}, {...card(2), highlight: highlight('$a \\geq \\sup h(x)$')}];
  const bundle = bundleFor(cards, [chunk([cards[0]], [part('first-question'), part('last-question')]), chunk([cards[1]], [])]);
  assert.deepEqual(bundle.routes.discriminant.steps.map(item => item.effects.results),
    [[], ['$a \\geq h(x)$'], ['$a \\geq \\sup h(x)$']]);
});

test('readonly merged fallback remains two independently completed read decisions', () => {
  const cards = [card(1), card(2)], bundle = bundleFor(cards, [chunk(cards, [])], finished('discriminant'));
  assert.deepEqual(bundle.routes.discriminant.steps.map(item => item.id), cards.map(item => item.step_id));
  assert.ok(bundle.routes.discriminant.steps.every(item => item.stream_steps.length === 1 && item.stream_last_part));
  assert.equal(gradeDecision(bundle.routes.discriminant.steps[0], 'read').status, 'passed');
  assert.equal(gradeDecision(bundle.routes.discriminant.steps[0], 'other').status, 'wrong');
  let state = selected(bundle);
  state = answer(bundle, state);
  assert.equal(state.done, false);
  state = answer(bundle, state);
  assert.equal(state.done, true);
});

test('append-only decisions reject changed questions, effects and final-part coverage', () => {
  const cards = [card(1), card(2)], groups = [chunk([cards[0]])];
  const bundle = bundleFor(cards, groups);
  const appended = extendStreamBundle(bundle, view(cards, [...groups, chunk([cards[1]], [])]), target, graph);
  assert.deepEqual(appended.routes.discriminant.steps[0], bundle.routes.discriminant.steps[0]);
  for (const mutate of [
    value => { value[0].parts[0].question = '新问题'; },
    value => { value[0].parts[0].expected_answer.one_of = ['wrong']; },
    value => { value[0].parts[0].effects = {log: 'changed'}; },
    value => { value[0].parts.push(part('new-part')); },
    value => { value[0] = chunk(cards); },
  ]) {
    const changed = structuredClone(groups); mutate(changed);
    assert.throws(() => extendStreamBundle(bundle, view(cards, changed), target, graph), /immutable_decision/);
  }
});

test('final math status can complete an already answered route without another answer', () => {
  const cards = [card(1)], groups = [chunk(cards)], bundle = bundleFor(cards, groups);
  const state = answer(bundle, selected(bundle));
  assert.equal(state.done, false);
  assert.equal(currentDecision(bundle, state), null);
  const done = extendStreamBundle(bundle, view(cards, groups, finished('discriminant')), target, graph);
  assert.equal(refreshStreamState(done, state).done, true);
  assert.equal(state.done, false, 'refresh is pure');
  for (const extra of [
    {checkpoints: [{target_ref: target, route_id: 'discriminant', status: 'math_failed'}]},
    {...finished('discriminant'), goals: {[target]: {status: 'conflict', available: false}}},
    {checkpoints: [{target_ref: target, route_id: 'discriminant', status: 'interrupted'}]},
  ]) {
    const stopped = extendStreamBundle(bundle, view(cards, groups, extra), target, graph);
    assert.equal(refreshStreamState(stopped, state).done, false);
  }
});

test('late revoked or failed status does not expose pending practice after a result arrives', () => {
  const cards = [card(1)], bundle = bundleFor(cards), state = selected(bundle);
  for (const extra of [
    {checkpoints: [{target_ref: target, route_id: 'discriminant', status: 'execution_error'}]},
    {goals: {[target]: {available: false, status: 'no_verified_route'}}},
  ]) {
    const failed = extendStreamBundle(bundle, view(cards, [chunk(cards)], extra), target, graph);
    const next = refreshStreamState(failed, state);
    assert.equal(next.done, false);
    assert.equal(currentDecision(failed, next), null);
    assert.equal(submitAnswer(failed, next, {decision: chunk(cards).parts[0].id, answer: 'correct'}).lastFeedback.status, 'wrong');
  }
});

test('same decision keeps draft and selected fill slot through later cards and terminal refreshes', () => {
  const cards = [card(1), card(2)], groups = [chunk([cards[0]])], bundle = bundleFor(cards, groups);
  const draft = {decision: groups[0].parts[0].id, answer: ['value', ''], selectedSlot: 1, submitted: {answer: 'wrong'}};
  const state = setStreamDraft(bundle, selected(bundle), draft);
  const later = extendStreamBundle(bundle, view(cards, [...groups, chunk([cards[1]], [])], finished('discriminant')), target, graph);
  assert.deepEqual(streamDraft(later, refreshStreamState(later, state)), draft);
  const advanced = answer(later, refreshStreamState(later, state));
  assert.equal(streamDraft(later, advanced), null);
  assert.throws(() => setStreamDraft(later, advanced, draft), /draft_decision_mismatch/);
});

test('route switching restores only that route history, feedback and draft; undo never touches its sibling', () => {
  const cards = [card(1), card(2), card(1, 'extremum'), card(2, 'extremum')];
  const groups = cards.map(item => chunk([item]));
  const bundle = bundleFor(cards, groups, {checkpoints: ['discriminant', 'extremum'].map(route =>
    ({target_ref: target, route_id: route, status: 'verified'}))});
  let state = answer(bundle, selected(bundle));
  const draftA = {decision: currentDecision(bundle, state).id, answer: 'wrong', selectedSlot: 0, submitted: {answer: 'wrong'}};
  state = setStreamDraft(bundle, state, draftA);
  const aRun = structuredClone(state.run), aEvents = structuredClone(state.events);
  state = switchRoute(bundle, state, 'extremum');
  assert.equal(state.run.completed.length, 0);
  assert.equal(streamDraft(bundle, state), null);
  state = answer(bundle, state, 'wrong');
  state = answer(bundle, state);
  const draftB = {decision: currentDecision(bundle, state).id, answer: 'correct', selectedSlot: null};
  state = setStreamDraft(bundle, state, draftB);
  const bRun = structuredClone(state.run), bEvents = structuredClone(state.events);
  state = switchRoute(bundle, JSON.parse(JSON.stringify(state)), 'discriminant');
  assert.deepEqual(state.run, aRun);
  assert.deepEqual(state.events, aEvents);
  assert.deepEqual(streamDraft(bundle, state), draftA);
  const undone = undo(bundle, state);
  assert.equal(undone.run.route, 'discriminant');
  assert.equal(undone.run.completed.length, 0);
  const restoredB = switchRoute(bundle, undone, 'extremum');
  assert.deepEqual(restoredB.run, bRun);
  assert.deepEqual(restoredB.events, bEvents);
  assert.deepEqual(streamDraft(bundle, restoredB), draftB);
  assert.equal(restoredB.events.some(event => event.kind === 'switch_route'), false);
  assert.equal(restoredB.archives.length, 0);
});

test('restored answers ahead of initial D1/D2 or pending snapshot survive without false completion', () => {
  const cards = [card(1), card(2)], groups = cards.map(item => chunk([item]));
  const bundle = bundleFor(cards, groups, finished('discriminant'));
  let state = answer(bundle, selected(bundle));
  state = setStreamDraft(bundle, state, {decision: currentDecision(bundle, state).id, answer: 'wrong', selectedSlot: 1});
  const parked = JSON.parse(JSON.stringify(state));
  const initial = extendStreamBundle(base, identity, target, graph);
  const first = refreshStreamState(initial, parked);
  assert.equal(first.done, false);
  assert.deepEqual(first.run, parked.run);
  assert.deepEqual(first.events, parked.events);
  assert.deepEqual(first.streamRoutes, parked.streamRoutes);
  const graphBefore = structuredClone(first);
  assert.deepEqual(streamGraphState(initial, first).focus, []);
  assert.equal(streamGraphState(initial, first).calls.length, 0);
  assert.deepEqual(first, graphBefore, 'rendering a partial startup projection cannot rewrite saved progress');
  const withoutRoutes = {...bundle, routes: {}};
  assert.doesNotThrow(() => streamGraphState(withoutRoutes, refreshStreamState(withoutRoutes, parked)),
    'selection records can also arrive before their route definitions');
  const pending = bundleFor(cards);
  const waiting = refreshStreamState(pending, first);
  assert.equal(waiting.done, false);
  assert.deepEqual(waiting.run, parked.run);
  const restored = refreshStreamState(bundle, waiting);
  assert.equal(currentDecision(bundle, restored).id, groups[1].parts[0].id);
  assert.deepEqual(streamDraft(bundle, restored), parked.streamDraft);
  assert.equal(streamGraphState(bundle, restored).nodes['method-discriminant'], 'confirmed');
  const allDone = answer(bundle, parked);
  const pendingUndo = undo(pending, refreshStreamState(pending, allDone));
  assert.deepEqual(pendingUndo.run.completed, parked.run.completed, 'undo preserves the earlier saved answer before decisions arrive');
});

test('subquestion and run identities keep independent progress and reject mixed refresh', () => {
  const cards = [card(1)], bundle = bundleFor(cards, [chunk(cards)]), state = answer(bundle, selected(bundle));
  for (const [key, value] of [['run_id', 'other-run'], ['lesson_version', 'other-version'], ['target_ref', '/root/children/0/goals/0']]) {
    const otherView = view([], []);
    if (key !== 'target_ref') otherView[key] = value;
    const other = extendStreamBundle(base, otherView, key === 'target_ref' ? value : target, graph);
    assert.throws(() => refreshStreamState(other, state), /版本/);
    assert.equal(createState(other).run.completed.length, 0);
  }
});

test('answer completion drives public graph evidence and undo extinguishes it', () => {
  const cards = [card(1)], bundle = bundleFor(cards, [chunk(cards)], {...finished('discriminant'), ...evidence()});
  let state = selected(bundle);
  assert.equal(streamGraphState(bundle, state).nodes['skill-inequality-transform'], 'idle');
  state = answer(bundle, state);
  const complete = streamGraphState(bundle, state);
  assert.equal(complete.nodes['skill-inequality-transform'], 'confirmed');
  assert.equal(complete.edges['method-discriminant|calls|skill-inequality-transform'], 'chosen');
  assert.equal(complete.calls.length, 1);
  assert.equal(streamGraphState(bundle, undo(bundle, state)).nodes['skill-inequality-transform'], 'idle');
  assert.deepEqual(streamStepGraph(bundle, {...cards[0], math_step_sha256: 'wrong'}).nodes, []);
});

test('unknown public references retain checked internal bases but cannot invent skill calls', () => {
  const cards = [card(1)], bundle = bundleFor(cards, [chunk(cards)], evidence('not-in-the-public-graph'));
  const state = answer(bundle, selected(bundle));
  const result = streamGraphState(bundle, state);
  assert.ok(result.usedBasis.includes('inequality-properties#addition'));
  assert.equal(result.calls.length, 0);
  assert.equal(result.nodes['not-in-the-public-graph'], undefined);
});

test('affine substitution read cards use the registered separation range call path', () => {
  const contract = read('../../site/data/knowledge-next/execution/method-separation.json');
  const range = contract.steps.find(step => step.id === 'range');
  const capabilities = ['substitution', 'restore_substitution_range'];
  const calls = capabilities.map(capability => {
    const call = range.calls.find(call => call.capability === capability);
    assert.equal(call?.public_ref, 'method-substitution');
    return {public_ref: call.public_ref, used_basis: ['equality-properties#identity'],
      postconditions: [{passed: true}]};
  });
  const cards = calls.map((_, index) => ({...card(index + 1, 'extremum'),
    method_ref: 'method-separation#range', display_unit: index ? 'affine_restore' : 'affine_substitution',
    source_refs: [`/steps/0/calls/${index}`], case_path: []}));
  const source = view(cards, cards.map(item => chunk([item], [])), {trajectories: [{
    target_ref: target, route_id: 'extremum', steps: [{seq: 1, method: 'method-separation',
      step: 'range', case_path: [], calls}],
  }]});
  const edgeId = 'method-separation|calls|method-substitution';
  const publicEdge = graph.edges.find(edge => edge.id === edgeId);
  assert.ok(publicEdge?.occurrences.some(occurrence => occurrence.step === 'range'));
  const bundle = extendStreamBundle(base, source, target, graph);
  for (const item of cards) {
    const evidence = streamStepGraph(bundle, item);
    assert.ok(evidence.nodes.includes('method-substitution'));
    assert.ok(evidence.edges.includes(edgeId));
    assert.equal(evidence.calls.length, 1);
    assert.equal(evidence.calls[0].source, item.source_refs[0]);
    assert.equal(publicEdge.occurrences[evidence.calls[0].occurrence].step, 'range');
  }
  let state = selected(bundle, 'extremum');
  assert.equal(currentDecision(bundle, state).interaction.type, 'read');
  assert.equal(streamGraphState(bundle, state).nodes['method-substitution'], 'idle');
  state = answer(bundle, state);
  assert.equal(streamGraphState(bundle, state).edges[edgeId], 'chosen');
  assert.equal(streamGraphState(bundle, undo(bundle, state)).edges[edgeId], 'idle');

  const wrongStep = structuredClone(source);
  wrongStep.trajectories[0].steps[0].step = 'restore';
  const rejected = extendStreamBundle(base, wrongStep, target, graph);
  assert.deepEqual(streamStepGraph(rejected, cards[0]).calls, []);
  assert.ok(!streamStepGraph(rejected, cards[0]).edges.includes(edgeId));
});

test('completed rule-directed cards light method/rule/skill edges and undo removes that path', () => {
  const item = {...card(1), route_id: 'interval', method_ref: 'method-interval-extremum#select'};
  const group = chunk([item]);
  const source = view([item], [group], {selection_chunks: [
    {target_ref: target, kind: 'D3', chunk: {...d3, expected_answer: {cell: ['interval', 'free']}}},
    {target_ref: target, kind: 'D4', chunk: {id: 'D4', title: '选法', options: [
      {branch: 'interval', route_id: 'interval', method: 'method-interval-extremum', route_plan: 'planned'},
    ]}},
  ], trajectories: [{target_ref: target, route_id: 'interval', steps: [{seq: 1,
    method: 'method-interval-extremum', step: 'select', calls: [{public_ref: 'quadratic-interval-extremum',
      rule_ref: 'rule-interval-skill', branch: 'quadratic', used_basis: ['quadratic-interval-extremum'],
      postconditions: [{passed: true}]}],
  }]}]});
  const bundle = extendStreamBundle(base, source, target, graph);
  const state = answer(bundle, selected(bundle, 'interval'));
  const edges = ['method-interval-extremum|step_rule|rule-interval-skill',
    'rule-interval-skill|selects|quadratic-interval-extremum'];
  const complete = streamGraphState(bundle, state), undone = streamGraphState(bundle, undo(bundle, state));
  assert.ok(edges.every(edge => complete.edges[edge] === 'chosen' && undone.edges[edge] === 'idle'));
  assert.equal(complete.calls[0].rule_ref, 'rule-interval-skill');
  assert.equal(complete.edges['method-interval-extremum|calls|quadratic-interval-extremum'], undefined);
});

test('stream replay uses the same grading and leaves separately held student progress untouched', () => {
  const cards = [card(1)], bundle = bundleFor(cards, [chunk(cards)], finished('discriminant'));
  const student = selected(bundle), before = structuredClone(student), done = answer(bundle, student);
  const replay = {schemaVersion: 2, bundleVersion: bundle.bundleVersion, problemId: bundle.problemId,
    routes: ['discriminant'], status: 'completed', actions: done.events.map(event => event.action)};
  assert.equal(replayState(bundle, replay).done, true);
  assert.deepEqual(student, before);
  assert.equal(student.run.completed.length, 0);
});
