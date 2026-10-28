import test from 'node:test';
import assert from 'node:assert/strict';
import {createState, currentDecision, submitAnswer, originalChoiceDecision, gradeDecision, undo, replayState, extendStreamBundle} from '../../site/assets/graph-walk/walk-state.mjs';
import {matchedOriginalChoice} from '../../site/assets/graph-walk/original-choice.mjs';
import {optionProgress} from '../../site/assets/graph-walk/option-workspace.mjs';
import {replayAnswer} from '../../site/assets/graph-walk/walk-replay.mjs';
import {createEventConsumer} from '../../site/assets/graph-walk/stage-three-stream.mjs';
import {nativePracticeContract} from '../lib/graph-walk-practice.mjs';

function fixture(relation = 'equal', truths = ['different', 'different', 'equal', 'equal']) {
  const target = '/root/goals/0';
  const options = truths.map((_, index) => ({option_id: `option-${index}`, label: 'ABCD'[index], text: `比较第 ${index + 1} 组函数`}));
  const original_choice = {status: 'matched', kind: 'multiple_choice', selection_mode: 'multiple', target_ref: target,
    select_relation: relation, options, correct_labels: options.filter((_, index) => truths[index] === relation).map(row => row.label),
    option_verdicts: options.map((row, index) => ({...row, verdict: truths[index], reason: '已验证的逐项理由'}))};
  const completion = {status: 'verified', target_ref: target, verified_route_sha256: 'verified', original_choice};
  const steps = options.flatMap((row, index) => {
    const option_context = {option_id: row.option_id, label: row.label, target_ref: target, left_ref: `${row.option_id}/f`, right_ref: `${row.option_id}/g`};
    return [{id: `${row.label}-evidence`, source: 'page', title: '比较证据', question: '核对依据',
      option_context: {...option_context, phase: 'evidence'}, interaction: {type: 'read'}, expected_answer: {}},
    {id: `${row.label}-verdict`, source: 'page', title: '本项结论', question: '这两个函数是否相同？',
      option_context: {...option_context, phase: 'verdict'}, interaction: {type: 'choice', field: 'verdict',
        options: [{value: 'equal', label: '相同'}, {value: 'different', label: '不同'}]}, expected_answer: {one_of: [truths[index]]}}];
  });
  const final = originalChoiceDecision(completion, target, 'equality');
  const bundle = {problemId: 'q20-test', bundleVersion: 'v1', option_workspaces: options,
    graph: {nodes: [], edges: []}, intro: [{id: 'method', source: 'authored', interaction: {type: 'read'}, expected_answer: {}, route_by_answer: {read: 'equality'}}],
    routes: {equality: {steps: [...steps, final], completion}}};
  return {bundle, completion, final};
}

function next(bundle, state) {
  const decision = currentDecision(bundle, state);
  return submitAnswer(bundle, state, {decision: decision.id, answer: replayAnswer(decision, state.run.route)});
}

test('Q20 requires each evidence and single verdict before its independent exact final', () => {
  const {bundle, final} = fixture();
  let state = createState(bundle);
  state = submitAnswer(bundle, state, {decision: final.id, answer: ['C', 'D']});
  assert.equal(state.lastFeedback.status, 'wrong');
  assert.equal(state.done, false);
  state = next(bundle, state);
  assert.equal(optionProgress(bundle, state).options.filter(row => row.unlocked).length, 1);
  state = submitAnswer(bundle, state, {decision: 'A-verdict', answer: 'different'});
  assert.equal(currentDecision(bundle, state).id, 'A-evidence');
  state = next(bundle, state);
  state = submitAnswer(bundle, state, {decision: 'A-verdict', answer: 'equal'});
  assert.equal(currentDecision(bundle, state).id, 'A-verdict');
  assert.equal(optionProgress(bundle, state).options[1].unlocked, false);
  state = next(bundle, state);
  assert.equal(currentDecision(bundle, state).id, 'B-evidence');
  assert.equal(optionProgress(bundle, state).options[0].complete, true);
  const locked = structuredClone(state);
  assert.deepEqual(undo(bundle, state), locked);
  const stale = submitAnswer(bundle, state, {decision: 'A-verdict', answer: 'equal'});
  assert.deepEqual(stale.run.completed, state.run.completed);
  while (currentDecision(bundle, state).id !== final.id) state = next(bundle, state);
  assert.equal(optionProgress(bundle, state).finalReady, true);
  assert.equal(optionProgress(bundle, state).finalPassed, false);
  for (const answer of [[], ['C'], ['A', 'C', 'D'], ['C', 'C', 'D'], ['C', 'D', 'Z']]) {
    state = submitAnswer(bundle, state, {decision: final.id, answer});
    assert.equal(state.lastFeedback.status, 'wrong');
    assert.equal(state.done, false);
  }
  state = submitAnswer(bundle, state, {decision: final.id, answer: ['D', 'C']});
  assert.equal(state.done, true);
  assert.equal(optionProgress(bundle, state).finalPassed, true);
});

test('polarity and empty original answers are independent of generic step multi', () => {
  const {final} = fixture('different');
  assert.equal(gradeDecision(final, ['A', 'B']).status, 'passed');
  assert.equal(gradeDecision(final, ['C', 'D']).status, 'wrong');
  const empty = fixture('equal', ['different', 'different']).final;
  assert.equal(gradeDecision(empty, []).status, 'passed');
  assert.equal(gradeDecision(empty, ['A']).status, 'wrong');
  assert.equal(gradeDecision({...final, expected_answer: {...final.expected_answer, allowed: ['A', 'B', 'C']}}, ['A', 'B', 'C']).status, 'wrong');
  assert.equal(gradeDecision({interaction: {type: 'multi'}, expected_answer: {required: ['A'], allowed: ['A', 'B']}}, ['A', 'B']).status, 'passed');
});

test('completion projection refuses incomplete scope, wrong polarity, or duplicate labels', () => {
  const {completion} = fixture();
  assert.ok(matchedOriginalChoice(completion));
  for (const mutate of [value => value.original_choice.option_verdicts.pop(), value => delete value.original_choice.select_relation,
    value => value.original_choice.option_verdicts[0].option_id = 'other-option',
    value => value.original_choice.correct_labels.push('C'), value => value.original_choice.correct_labels = ['A', 'B']]) {
    const value = structuredClone(completion); mutate(value);
    assert.equal(matchedOriginalChoice(value), null);
  }
});

test('AI replay cannot change the separately held student progress', () => {
  const {bundle} = fixture();
  const student = createState(bundle), saved = structuredClone(student);
  const actions = [...bundle.intro, ...bundle.routes.equality.steps].map(decision => ({decision: decision.id, answer: replayAnswer(decision, 'equality')}));
  const replay = replayState(bundle, {schemaVersion: 2, routes: ['equality'], bundleVersion: bundle.bundleVersion, problemId: bundle.problemId, actions});
  assert.equal(replay.done, true);
  assert.deepEqual(student, saved);
  assert.equal(optionProgress(bundle, student).finalReady, false);
});

test('live completion, snapshot recovery, stream composer and native export preserve the exact two-layer contract', () => {
  const value = fixture();
  const identity = {run_id: 'q20-run', lesson_version: 'q20-lesson', stream_id: 'q20-run'};
  const target = '/root/goals/0', route = 'equality';
  const parts = value.bundle.routes.equality.steps.slice(0, -1);
  const math_steps = parts.map((part, index) => ({...identity, target_ref: target, route_id: route,
    step_id: `math-${index}`, ordinal: index + 1, math_step_sha256: `hash-${index}`, local_check: 'passed',
    title: part.title, option_context: structuredClone(part.option_context)}));
  const interactions = parts.map((part, index) => ({contract: 'graph-step-interaction/v1', ...identity,
    target_ref: target, route_id: route, interaction_id: `interaction-${index}`, status: 'interactive',
    steps: [{step_id: math_steps[index].step_id, math_step_sha256: math_steps[index].math_step_sha256}], parts: [part]}));
  const interaction_states = interactions.map((chunk, index) => ({target_ref: target, route_id: route,
    ...chunk.steps[0], ordinal: index + 1, interaction_id: chunk.interaction_id, status: chunk.status}));
  const answer = {kind: 'compare_functions', status: 'complete', selection_mode: 'multiple', select_relation: 'equal',
    option_verdicts: value.completion.original_choice.option_verdicts, correct_labels: ['C', 'D']};
  const snapshot = {...identity, last_seq: 0, math_steps, interaction_protocol: 'graph-step-interaction/v1',
    interactions, interaction_states, goals: {}};
  const consumer = createEventConsumer(identity);
  consumer.hydrate(snapshot);
  consumer.accept({contract: 'graph-stage-three-event/v1', ...identity, seq: 1, event_id: 'done',
    target_ref: target, route_id: route, type: 'lesson.chunk_ready', payload: {kind: 'route_completion',
      status: 'verified', answer, verified_route_sha256: 'verified', original_choice: value.completion.original_choice}});
  const refreshed = createEventConsumer(identity);
  refreshed.hydrate({...snapshot, last_seq: 1, handoffs: [{target_ref: target, route_id: route, available: true,
    answer, verified_route_sha256: 'verified', original_choice: value.completion.original_choice}]});
  const base = structuredClone(value.bundle);
  base.routes.equality = {id: route, streaming: true, steps: []};
  const live = extendStreamBundle(base, consumer.view(), target);
  const restored = extendStreamBundle(base, refreshed.view(), target);
  assert.deepEqual(live.routes.equality.steps, restored.routes.equality.steps);
  assert.deepEqual(live.routes.equality.completion.original_choice, value.completion.original_choice);
  const terminal = live.routes.equality.steps.at(-1);
  assert.equal(terminal.interaction.type, 'original_choice_exact_set');
  assert.deepEqual(terminal.expected_answer, {correct_labels: ['C', 'D'], option_labels: ['A', 'B', 'C', 'D']});
  assert.deepEqual(terminal.require_complete_options, ['option-0', 'option-1', 'option-2', 'option-3']);
  const exported = nativePracticeContract(live).routes.equality.steps;
  for (const key of ['source', 'target_ref', 'select_relation', 'require_complete_options', 'expected_answer']) {
    assert.deepEqual(exported.at(-1)[key], terminal[key]);
  }
  assert.deepEqual(exported[0].option_context, parts[0].option_context);
  let state = createState(restored);
  const actions = [];
  for (let decision = currentDecision(restored, state); decision; decision = currentDecision(restored, state)) {
    const action = {decision: decision.id, answer: replayAnswer(decision, route)};
    actions.push(action); state = submitAnswer(restored, state, action);
    assert.equal(state.lastFeedback.status, 'passed');
  }
  assert.equal(state.done, true);
  assert.deepEqual(actions.at(-1).answer, ['C', 'D']);
  const replay = replayState(restored, {schemaVersion: 2, routes: [route], bundleVersion: restored.bundleVersion,
    problemId: restored.problemId, actions});
  assert.equal(replay.done, true);
  assert.equal(optionProgress(restored, createState(restored)).finalReady, false);
});
