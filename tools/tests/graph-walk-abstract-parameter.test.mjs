import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {createRequire} from 'node:module';
import {currentDecision, replayState, submitAnswer} from '../../site/assets/graph-walk/walk-state.mjs';
import {hasOptionWorkspaces} from '../../site/assets/graph-walk/option-workspace.mjs';
import {intervalOverlapAt} from '../../site/assets/graph-walk/interval-overlap-visual.mjs';
const read = async name => JSON.parse(await fs.readFile(new URL(`../../site/data/graph-walk/function-concepts-parameter-variant02${name}`, import.meta.url), 'utf8'));
const bundle = await read('.json'), replay = await read('.replay.json');
const route = bundle.routes['abstract-function-domain'];
const katex = createRequire(import.meta.url)('../../site/assets/practice/vendor/katex-0.18.9/katex.min.js');

test('exported parameter course retains exact critical endpoints in the shared explorer', () => {
  const graph = route.steps[2].stem_board.interval_explorer;
  assert.ok(graph.critical_exact_values.includes('-1/2'));
  assert.ok(graph.critical_exact_values.includes('1/2'));
  for (const interval of graph.intervals) {
    for (const endpoint of [interval.lower, interval.upper]) {
      assert.equal(typeof endpoint.slope_exact, 'string');
      assert.equal(typeof endpoint.intercept_exact, 'string');
    }
  }
  assert.equal(intervalOverlapAt(graph, 0).intersection, '[0, 1]');
  for (const parameter of ['-1/2', '1/2']) {
    assert.equal(intervalOverlapAt(graph, parameter).intersection, '{0.5}');
  }
  assert.equal(intervalOverlapAt(graph, '50000000001/100000000000').empty, true);
  assert.equal(intervalOverlapAt(graph, '49999999999/100000000000').kind, 'overlap');
});

test('parameter course explains common input then separation and complement', () => {
  assert.match(bundle.problem.text, /有定义/);
  assert.equal(route.completion.answer.kind, 'find_abstract_domain_parameter');
  assert.equal(route.completion.answer.set.expression, 'Interval(-1/2, 1/2)');
  assert.deepEqual(route.steps.slice(0, 6).map(row => row.title), [
    '分别列出输入条件', '求各调用允许的范围', '观察范围的公共部分',
    '找出两个区间完全错开的条件', '求交集为空时的参数范围', '取补集，得到参数范围',
  ]);
  assert.equal(route.steps[1].interaction.type, 'checklist');
  assert.equal(route.steps[1].interaction.slots.length, 2);
  assert.equal(route.steps[2].stem_board.interval_explorer.mode, 'explore');
  assert.equal(route.steps[3].stem_board.interval_explorer.mode, 'separation');
  for (const step of route.steps.slice(0, 6)) {
    const ref = step.stream_steps[0];
    const completed = bundle.stream.math_steps.find(row => row.step_id === ref.step_id && row.math_step_sha256 === ref.math_step_sha256).highlight;
    assert.equal(step.stem_board.items[1].math, null);
    assert.deepEqual(step.stem_board.items[0], completed.items[0]);
    assert.deepEqual(step.stem_board.interval_explorer, completed.interval_explorer);
    assert.equal(typeof completed.items[1].math, 'string');
    for (const item of [...step.stem_board.items, ...completed.items]) {
      if (item.math) assert.doesNotThrow(() => katex.renderToString(item.math, {throwOnError: true, strict: 'ignore'}));
    }
  }
});

test('parameter course completes eleven decisions and exact original selection without T1 workspaces', () => {
  assert.equal(replay.actions.length, 11);
  const final = route.steps.at(-1);
  assert.equal(final.interaction.type, 'original_choice_exact_set');
  assert.deepEqual(final.expected_answer.correct_labels, ['B']);
  assert.equal(final.require_complete_options, undefined);
  for (let index = 0; index < replay.actions.length; index++) {
    const before = replayState(bundle, replay, index);
    const decision = currentDecision(bundle, before);
    assert.equal(decision.id, replay.actions[index].decision);
    assert.equal(before.done, false);
    assert.equal(hasOptionWorkspaces(bundle, before), false);
    const wrong = decision.interaction.type === 'choice'
      ? decision.interaction.options.filter(row => !decision.expected_answer.one_of.includes(row.value)).map(row => row.value)
      : decision.interaction.type === 'original_choice_exact_set' ? [[], ['A'], ['A', 'B'], ['B', 'B'], ['Z']] : [];
    for (const answer of wrong) {
      const rejected = submitAnswer(bundle, before, {decision: decision.id, answer});
      assert.equal(rejected.lastFeedback.status, 'wrong');
      assert.equal(currentDecision(bundle, rejected).id, decision.id);
      assert.equal(rejected.done, false);
    }
    const passed = submitAnswer(bundle, before, replay.actions[index]);
    assert.equal(passed.lastFeedback.status, 'passed');
    assert.equal(passed.done, index === replay.actions.length - 1);
  }
});
