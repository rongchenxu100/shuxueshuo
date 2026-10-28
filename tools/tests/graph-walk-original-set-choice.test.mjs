import test from 'node:test';
import assert from 'node:assert/strict';
import {matchedOriginalChoice} from '../../site/assets/graph-walk/original-choice.mjs';
import {createState, currentDecision, submitAnswer, originalChoiceDecision, replayState} from '../../site/assets/graph-walk/walk-state.mjs';
import {optionProgress, hasOptionWorkspaces} from '../../site/assets/graph-walk/option-workspace.mjs';
import {nativePracticeContract} from '../lib/graph-walk-practice.mjs';

function fixture(correct = ['D'], mode = 'unspecified') {
  const target = '/root/goals/0';
  const completion = {status: 'verified', target_ref: target, verified_route_sha256: 'set-proof',
    answer: {kind: 'find_abstract_domain', status: 'set', set: {expression: 'Interval.open(1/3, 5)'}},
    original_choice: {status: 'matched', kind: mode === 'single' ? 'single_choice' : 'multiple_choice',
      matching: 'set_equality', selection_mode: mode, target_ref: target,
      options: ['(-4,3)', '(-2,5)', '(1/3,3)', '(1/3,5)'].map((text, index) => ({label: 'ABCD'[index], text})),
      correct_labels: correct}};
  const final = originalChoiceDecision(completion, target, 'domain');
  const intro = {id: 'method', interaction: {type: 'read'}, expected_answer: {}, route_by_answer: {read: 'domain'}};
  const math = {id: 'intersection', interaction: {type: 'choice', field: 'range', options: [{value: 'right', label: '(1/3,5)'}, {value: 'wrong', label: '(1/3,5]'}]}, expected_answer: {one_of: ['right']}};
  const bundle = {problemId: 'mixed-set', bundleVersion: 'v1', intro: [intro], routes: {domain: {steps: [math, final], completion}}};
  return {bundle, completion, final};
}

for (const correct of [[], ['D'], ['A', 'D']]) for (const mode of ['multiple', 'unspecified']) {
  test(`generic ${mode} set choice accepts exactly ${JSON.stringify(correct)} after mathematics`, () => {
    const {bundle, completion, final} = fixture(correct, mode);
    assert.ok(matchedOriginalChoice(completion));
    assert.equal(final.require_complete_options, undefined);
    assert.doesNotMatch(final.question + final.feedback.answer, /各项判断|相同还是不同|进度标签/);
    assert.equal(nativePracticeContract(bundle).routes.domain.steps.at(-1).source, 'original_choice');
    assert.equal(nativePracticeContract(bundle).routes.domain.steps.at(-1).matching, 'set_equality');
    let state = createState(bundle);
    state = submitAnswer(bundle, state, {decision: final.id, answer: correct});
    assert.equal(state.lastFeedback.status, 'wrong');
    state = submitAnswer(bundle, state, {decision: 'method', answer: 'read'});
    state = submitAnswer(bundle, state, {decision: 'intersection', answer: 'wrong'});
    assert.equal(currentDecision(bundle, state).id, 'intersection');
    state = submitAnswer(bundle, state, {decision: 'intersection', answer: 'right'});
    assert.equal(state.done, false);
    assert.equal(hasOptionWorkspaces(bundle, state), false);
    assert.deepEqual(optionProgress(bundle, state).options, []);
    for (const answer of [['Z'], ['D', 'D'], 'D', ...[[], ['D'], ['A', 'D'], ['A', 'C', 'D']].filter(value => JSON.stringify(value) !== JSON.stringify(correct))]) {
      const rejected = submitAnswer(bundle, state, {decision: final.id, answer});
      assert.equal(rejected.lastFeedback.status, 'wrong');
      assert.equal(rejected.done, false);
    }
    state = submitAnswer(bundle, state, {decision: final.id, answer: [...correct].reverse()});
    assert.equal(state.done, true);
    assert.deepEqual(submitAnswer(bundle, state, {decision: final.id, answer: ['Z']}), state);
    assert.equal(replayState(bundle, {schemaVersion: 2, routes: ['domain'], status: 'completed',
      problemId: bundle.problemId, bundleVersion: bundle.bundleVersion,
      actions: [{decision: 'method', answer: 'read'}, {decision: 'intersection', answer: 'right'},
        {decision: final.id, answer: correct}]}).done, true);
  });
}

test('explicit single set choice retains a scalar final and demands one certified label', () => {
  const {completion, final} = fixture(['D'], 'single');
  assert.ok(matchedOriginalChoice(completion));
  assert.equal(final.interaction.type, 'choice');
  for (const labels of [[], ['A', 'D']]) {
    const invalid = structuredClone(completion); invalid.original_choice.correct_labels = labels;
    assert.equal(matchedOriginalChoice(invalid), null);
  }
});

test('abstract-domain parameter answer reuses the exact set final without T1 workspace gates', () => {
  const {completion} = fixture(['B']);
  completion.answer = {kind: 'find_abstract_domain_parameter', status: 'set',
    set: {expression: 'Interval(-1/2, 1/2)', latex: '[-\\frac12,\\frac12]'}};
  assert.ok(matchedOriginalChoice(completion));
  const final = originalChoiceDecision(completion, '/root/goals/0', 'parameter');
  assert.equal(final.matching, 'set_equality');
  assert.equal(final.require_complete_options, undefined);
  assert.equal(final.interaction.type, 'original_choice_exact_set');
  assert.deepEqual(final.expected_answer.correct_labels, ['B']);
});

test('generic set contract cannot masquerade as a T1 answer or weaken its verdict contract', () => {
  const {completion} = fixture();
  for (const mutate of [value => value.answer.kind = 'compare_functions',
    value => value.answer.status = 'complete', value => value.original_choice.option_verdicts = [],
    value => value.original_choice.select_relation = 'equal', value => delete value.original_choice.matching,
    value => value.original_choice.options[0].option_id = 'A',
    value => value.original_choice.correct_labels = ['Z'],
    value => value.original_choice.kind = 'single_choice']) {
    const invalid = structuredClone(completion); mutate(invalid);
    assert.equal(matchedOriginalChoice(invalid), null);
  }
});
