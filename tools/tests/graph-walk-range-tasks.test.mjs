import test from 'node:test';
import assert from 'node:assert/strict';
import {matchedOriginalChoice} from '../../site/assets/graph-walk/original-choice.mjs';
import {originalChoiceDecision, createState, submitAnswer} from '../../site/assets/graph-walk/walk-state.mjs';
import {routeAnswerSummary} from '../../site/assets/graph-walk/stream-math-dom.mjs';
import {nativePracticeContract} from '../lib/graph-walk-practice.mjs';

test('parameter value summaries preserve singleton, all, multiple and empty solution sets', () => {
  const answer = {kind: 'find_value', status: 'complete', result_type: 'parameter_value', parameter: 'm'};
  assert.deepEqual(routeAnswerSummary({...answer, value: {latex: '2'}, parameter_set: {latex: '\\{2\\}'}}),
    {label: '符合条件的参数：', formula: 'm=2'});
  for (const set of ['\\mathbb{R}', '\\{-1,1\\}', '\\varnothing']) {
    assert.deepEqual(routeAnswerSummary({...answer, value: null, parameter_set: {latex: set}}),
      {label: '符合条件的参数：', formula: `m\\in ${set}`});
  }
  assert.deepEqual(routeAnswerSummary({...answer, parameter: 'α', value: {latex: '2'}, parameter_set: {latex: '\\{2\\}'}}),
    {label: '符合条件的参数：', formula: 'α=2'});
});

function completion(labels = ['D'], mode = 'single') {
  return {status: 'verified', target_ref: '/root/goals/0', verified_route_sha256: 'range-proof',
    answer: {kind: 'select_range_domain', status: 'complete', correct_labels: labels, select_relation: 'differs', selection_mode: mode},
    original_choice: {status: 'matched', kind: mode === 'single' ? 'single_choice' : 'multiple_choice',
      matching: 'range_domain_options', selection_mode: mode, target_ref: '/root/goals/0',
      options: ['(-2,4)', '(-2,1)', '(1,4)', '(-1,1)'].map((text, index) => ({label: 'ABCD'[index], text})),
      correct_labels: labels}};
}

for (const mode of ['single', 'multiple', 'unspecified']) {
  test(`domain candidates return original ${mode} labels after all checks`, () => {
    const result = completion(mode === 'single' ? ['D'] : ['A', 'C'], mode);
    assert.ok(matchedOriginalChoice(result));
    const final = originalChoiceDecision(result, result.target_ref, 'range');
    assert.equal(final.matching, 'range_domain_options');
    assert.match(final.question, /可能/);
    assert.doesNotMatch(final.question, /求得的集合/);
    const intro = {id: 'method', interaction: {type: 'read'}, expected_answer: {}, route_by_answer: {read: 'range'}};
    const steps = 'ABCD'.split('').map(label => ({id: label, interaction: {type: 'read'}, expected_answer: {}}));
    const bundle = {problemId: 'range-options', bundleVersion: 'v1', intro: [intro], routes: {range: {steps: [...steps, final], completion: result}}};
    assert.equal(nativePracticeContract(bundle).routes.range.steps.at(-1).source, 'original_choice');
    let state = createState(bundle);
    state = submitAnswer(bundle, state, {decision: 'method', answer: 'read'});
    assert.equal(submitAnswer(bundle, state, {decision: final.id, answer: 'D'}).lastFeedback.status, 'wrong');
    for (const step of steps) state = submitAnswer(bundle, state, {decision: step.id, answer: 'read'});
    state = submitAnswer(bundle, state, {decision: final.id, answer: mode === 'single' ? 'D' : ['C', 'A']});
    assert.equal(state.done, true);
  });
}

test('domain-choice wire contract cannot mask a different or contradictory goal', () => {
  for (const mutate of [c => c.answer.kind = 'find_range', c => c.answer.correct_labels = ['A'],
    c => c.original_choice.options[0].option_id = 'A', c => c.original_choice.correct_labels = ['Z']]) {
    const c = completion(); mutate(c);
    assert.equal(matchedOriginalChoice(c), null);
  }
});

test('answer summaries show original options and scalar results, not intermediate images', () => {
  assert.deepEqual(routeAnswerSummary(completion().answer), {label: '原题选项：D', formula: ''});
  assert.deepEqual(routeAnswerSummary({kind: 'find_extrema_expression', status: 'value', value: {expression: '6', latex: '6'}}),
    {label: '所求值：', formula: '6'});
  assert.match(routeAnswerSummary({kind: 'find_extrema_expression', status: 'undefined', reason: 'extremum_not_attained'}).label, /最值不存在/);
});

test('generic answer requests display the requested result and preserve unattained extrema', () => {
  const summary = value => routeAnswerSummary({kind: 'derived_answer', ...value});
  assert.deepEqual(summary({request_kind: 'expression', status: 'value', value: {expression: '6', latex: '6'}}),
    {label: '所求值：', formula: '6'});
  assert.deepEqual(summary({request_kind: 'compare_set', status: 'boolean', value: false}),
    {label: '原题判断：否', formula: ''});
  assert.match(summary({request_kind: 'extremum', quantity: 'maximum', status: 'not_attained', bound: {latex: '2'}}).label, /最大值不存在/);
  assert.deepEqual(summary({request_kind: 'extremum', quantity: 'supremum', status: 'not_attained', value: {latex: '2'}}),
    {label: '上确界：', formula: '2'});
  assert.match(summary({request_kind: 'expression', status: 'undefined', reason: 'quantity_unavailable'}).label, /所需量不存在/);
});

test('generic set answers still use exact original option selection', () => {
  const c = completion(['A'], 'single');
  c.answer = {kind: 'derived_answer', request_kind: 'identity', status: 'set', set: {latex: '[1,5]',
    exact: {$math: 'Interval', args: [{$math: 'Integer', value: '1'}, {$math: 'Integer', value: '5'}, false, false]}}};
  c.original_choice.matching = 'set_equality';
  assert.ok(matchedOriginalChoice(c));
  c.answer.request_kind = 'expression';
  assert.equal(matchedOriginalChoice(c), null);
  c.answer.request_kind = 'identity';
  c.answer.status = 'value';
  assert.equal(matchedOriginalChoice(c), null);
});

test('single choice without matching requires a supported, available typed answer', () => {
  const c = completion(['A']);
  delete c.original_choice.matching;
  delete c.original_choice.selection_mode;
  const value = {expression: '6', latex: '6', exact: {$math: 'Integer', value: '6'}};
  for (const answer of [
    {kind: 'derived_answer', request_kind: 'expression', status: 'value', value},
    {kind: 'derived_answer', request_kind: 'compare_set', status: 'boolean', value: false},
    {kind: 'derived_answer', request_kind: 'extremum', quantity: 'maximum', status: 'attained', value},
    {kind: 'derived_answer', request_kind: 'extremum', quantity: 'supremum', status: 'not_attained', value},
    {kind: 'find_extrema_expression', status: 'value', value},
    {kind: 'find_minimum', status: 'attained', value},
    {kind: 'find_range', status: 'set', set: {latex: '[0,1]'}},
  ]) assert.ok(matchedOriginalChoice({...c, answer}), JSON.stringify(answer));
  for (const answer of [
    undefined,
    {kind: 'unknown', status: 'value', value},
    {kind: 'derived_answer', request_kind: 'select', status: 'value', value},
    {kind: 'derived_answer', request_kind: 'expression', status: 'undefined', value},
    {kind: 'derived_answer', request_kind: 'expression', status: 'value'},
    {kind: 'derived_answer', request_kind: 'expression', status: 'value', value: {latex: '6'}},
    {kind: 'derived_answer', request_kind: 'compare_set', status: 'boolean', value: 'false'},
    {kind: 'derived_answer', request_kind: 'compare_set', status: 'value', value},
    {kind: 'derived_answer', request_kind: 'extremum', quantity: 'maximum', status: 'not_attained', value},
    {kind: 'derived_answer', request_kind: 'extremum', quantity: 'maximum_at_x', status: 'attained', value},
    {kind: 'derived_answer', request_kind: 'identity', status: 'set', set: value},
    {kind: 'find_extrema_expression', status: 'undefined', reason: 'extremum_not_attained'},
    {kind: 'find_range', status: 'set'},
  ]) assert.equal(matchedOriginalChoice({...c, answer}), null, JSON.stringify(answer));
});
