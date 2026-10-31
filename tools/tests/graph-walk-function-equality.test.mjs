import test from 'node:test';
import assert from 'node:assert/strict';
import {createState, currentDecision, submitAnswer, originalChoiceDecision, gradeDecision, undo, replayState, extendStreamBundle} from '../../site/assets/graph-walk/walk-state.mjs';
import {matchedOriginalChoice} from '../../site/assets/graph-walk/original-choice.mjs';
import {optionProgress} from '../../site/assets/graph-walk/option-workspace.mjs';
import {replayAnswer} from '../../site/assets/graph-walk/walk-replay.mjs';
import {createEventConsumer} from '../../site/assets/graph-walk/stage-three-stream.mjs';
import {nativePracticeContract} from '../lib/graph-walk-practice.mjs';

function fixture(relation = 'equal', truths = ['different', 'different', 'equal', 'equal'], selectionMode = 'multiple') {
  const target = '/root/goals/0';
  const options = truths.map((_, index) => ({option_id: `option-${index}`, label: 'ABCD'[index], text: `比较第 ${index + 1} 组函数`}));
  const original_choice = {status: 'matched', kind: selectionMode === 'single' ? 'single_choice' : 'multiple_choice', selection_mode: selectionMode, target_ref: target,
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

test('single-answer comparisons retain all four verdict gates and final navigation', () => {
  const {bundle, final} = fixture('equal', ['different', 'different', 'equal', 'different'], 'single');
  assert.equal(final.interaction.type, 'choice');
  assert.deepEqual(final.require_complete_options, bundle.option_workspaces.map(row => row.option_id));
  let state = createState(bundle);
  assert.equal(optionProgress(bundle, state).finalReady, false);
  assert.equal(submitAnswer(bundle, state, {decision: final.id, answer: 'C'}).lastFeedback.status, 'wrong');
  while (currentDecision(bundle, state).id !== final.id) {
    const decision = currentDecision(bundle, state);
    if (decision.id === 'D-verdict') {
      const wrong = submitAnswer(bundle, state, {decision: decision.id, answer: 'equal'});
      assert.equal(currentDecision(bundle, wrong).id, 'D-verdict');
      assert.equal(optionProgress(bundle, wrong).finalReady, false);
    }
    state = next(bundle, state);
  }
  assert.equal(optionProgress(bundle, state).finalReady, true);
  assert.equal(optionProgress(bundle, state).finalCurrent, true);
  for (const answer of ['A', 'B', 'D', 'Z', '', ['C'], ['C', 'D']]) {
    const wrong = submitAnswer(bundle, state, {decision: final.id, answer});
    assert.equal(wrong.lastFeedback.status, 'wrong');
    assert.equal(wrong.done, false);
  }
  const passed = submitAnswer(bundle, state, {decision: final.id, answer: 'C'});
  assert.equal(passed.done, true);
  assert.equal(optionProgress(bundle, passed).finalPassed, true);
  const exported = nativePracticeContract(bundle).routes.equality.steps.at(-1);
  assert.equal(exported.source, 'original_choice');
  assert.deepEqual(exported.require_complete_options, final.require_complete_options);
  assert.deepEqual(exported.expected_answer, {one_of: ['C']});
  assert.equal(gradeDecision({...final, expected_answer: {one_of: 'C'}}, 'C').status, 'wrong');
});

test('single-answer comparison handoffs validate every verdict and preserve ordinary single choice', () => {
  const {completion} = fixture('equal', ['different', 'different', 'equal', 'different'], 'single');
  assert.ok(matchedOriginalChoice(completion));
  for (const mutate of [value => value.original_choice.option_verdicts.pop(),
    value => value.original_choice.correct_labels = ['A'],
    value => value.original_choice.correct_labels.push('D'),
    value => value.original_choice.option_verdicts[0].option_id = 'another',
    value => value.original_choice.selection_mode = 'multiple']) {
    const bad = structuredClone(completion); mutate(bad);
    assert.equal(matchedOriginalChoice(bad), null);
  }
  const ordinary = structuredClone(completion);
  delete ordinary.original_choice.option_verdicts;
  delete ordinary.original_choice.select_relation;
  ordinary.answer = {kind: 'find_range', status: 'set', set: {latex: '[0,1]'}};
  assert.ok(matchedOriginalChoice(ordinary));
  const ordinaryFinal = originalChoiceDecision(ordinary, '/root/goals/0', 'ordinary');
  assert.equal(ordinaryFinal.require_complete_options, undefined);
  const exported = nativePracticeContract({problemId: 'ordinary', bundleVersion: 'v1', intro: [],
    routes: {ordinary: {steps: [ordinaryFinal]}}}).routes.ordinary.steps[0];
  assert.equal(exported.source, undefined, 'ordinary single-choice published contracts keep their existing identity');
});

for (const truths of [['different', 'different', 'equal', 'different'],
  ['different', 'different', 'equal', 'equal'], ['different', 'different', 'different', 'different']]) {
  for (const streaming of [false, true]) {
    test(`unspecified original selection stays exact with ${truths.filter(value => value === 'equal').length} correct labels (${streaming ? 'stream' : 'static'})`, () => {
      const {bundle, final, completion} = fixture('equal', truths, 'unspecified');
      const frozenCompletion = structuredClone(completion);
      assert.ok(matchedOriginalChoice(completion));
      assert.equal(completion.original_choice.selection_mode, 'unspecified');
      assert.equal(final.interaction.type, 'original_choice_exact_set');
      assert.deepEqual(final.expected_answer.correct_labels, completion.original_choice.correct_labels);
      assert.match(final.question, /按不定项选择作答，选出全部符合题意的选项/);
      assert.doesNotMatch(final.question, /单选|多选|一项|两项|至少|最多/);
      assert.match(final.feedback.answer, /漏选或多选/);
      if (streaming) {
        bundle.stream = {target_ref: '/root/goals/0'};
        Object.assign(bundle.routes.equality, {math_complete: true, interactions_complete: true, available: true});
      }
      let state = createState(bundle);
      while (currentDecision(bundle, state)?.id !== final.id) {
        const premature = submitAnswer(bundle, state, {decision: final.id, answer: final.expected_answer.correct_labels});
        assert.equal(premature.lastFeedback.status, 'wrong');
        assert.equal(premature.done, false);
        assert.equal(optionProgress(bundle, state).finalReady, false);
        state = next(bundle, state);
      }
      assert.equal(optionProgress(bundle, state).finalReady, true);
      for (const answer of [[], ['C'], ['C', 'D'], ['A', 'C', 'D'], ['C', 'C'], ['Z'], 'C']) {
        const exact = Array.isArray(answer) && new Set(answer).size === answer.length &&
          answer.length === final.expected_answer.correct_labels.length &&
          answer.every(value => final.expected_answer.correct_labels.includes(value));
        assert.equal(gradeDecision(final, answer).status, exact ? 'passed' : 'wrong');
      }
      state = submitAnswer(bundle, state, {decision: final.id, answer: [...final.expected_answer.correct_labels].reverse()});
      assert.equal(state.done, true);
      assert.deepEqual(submitAnswer(bundle, state, {decision: final.id, answer: ['Z']}), state);
      assert.deepEqual(submitAnswer(bundle, state, {decision: 'A-verdict', answer: 'equal'}), state);
      assert.deepEqual(completion, frozenCompletion);
    });
  }
}

test('unspecified source selection never becomes single by counting the verified labels', () => {
  const {completion} = fixture('equal', ['different', 'different', 'equal', 'different'], 'unspecified');
  for (const kind of ['single_choice', 'unknown']) {
    const bad = structuredClone(completion);
    bad.original_choice.kind = kind;
    assert.equal(matchedOriginalChoice(bad), null);
  }
  for (const mode of [undefined, 'none', 'single', 'unknown']) {
    const bad = structuredClone(completion);
    bad.original_choice.selection_mode = mode;
    assert.equal(matchedOriginalChoice(bad), null);
  }
});

for (const mode of ['single', 'multiple']) for (const streaming of [false, true]) {
  test(`completed ${mode} comparison is immutable on resubmission (${streaming ? 'stream' : 'static'})`, () => {
    const {bundle, final} = fixture('equal', ['different', 'different', 'equal', 'different'], mode);
    if (streaming) {
      bundle.stream = {target_ref: '/root/goals/0'};
      Object.assign(bundle.routes.equality, {math_complete: true, interactions_complete: true, available: true});
    }
    let state = createState(bundle);
    while (currentDecision(bundle, state)) state = next(bundle, state);
    assert.equal(state.done, true);
    if (streaming) assert.ok(state.streamRoutes.equality);
    const frozen = structuredClone(state);
    for (const action of [{decision: final.id, answer: mode === 'single' ? 'C' : ['C']},
      {decision: final.id, answer: mode === 'single' ? 'D' : ['D']},
      {decision: 'A-verdict', answer: 'equal'}]) {
      assert.deepEqual(submitAnswer(bundle, state, action), frozen);
      assert.deepEqual(state, frozen);
    }
  });
}

test('completed ordinary original single choice retains its existing stale-answer behavior', () => {
  const {bundle, completion} = fixture('equal', ['different', 'different', 'equal', 'different'], 'single');
  delete completion.original_choice.option_verdicts;
  delete completion.original_choice.select_relation;
  completion.answer = {kind: 'find_range', status: 'set', set: {latex: '[0,1]'}};
  const final = originalChoiceDecision(completion, '/root/goals/0', 'equality');
  bundle.routes.equality.steps = [final];
  let state = createState(bundle);
  while (currentDecision(bundle, state)) state = next(bundle, state);
  const changed = submitAnswer(bundle, state, {decision: final.id, answer: 'D'});
  assert.equal(changed.done, true);
  assert.deepEqual(changed.run.completed, state.run.completed);
  assert.equal(changed.events.length, state.events.length + 1);
  assert.equal(changed.lastFeedback.status, 'wrong');
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

for (const selectionMode of ['multiple', 'unspecified']) test(`live completion and snapshot recovery preserve the ${selectionMode} exact two-layer contract`, () => {
  const value = fixture('equal', ['different', 'different', 'equal', 'equal'], selectionMode);
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
  const answer = {kind: 'compare_functions', status: 'complete', selection_mode: selectionMode, select_relation: 'equal',
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
