import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {currentDecision, replayState, submitAnswer} from '../../site/assets/graph-walk/walk-state.mjs';
import {hasOptionWorkspaces} from '../../site/assets/graph-walk/option-workspace.mjs';
const read = async name => JSON.parse(await fs.readFile(new URL(`../../site/data/graph-walk/function-concepts-abstract-mixed-q03${name}`, import.meta.url), 'utf8'));
const bundle = await read('.json'), replay = await read('.replay.json');
const route = bundle.routes['abstract-function-domain'];

test('mixed domain preserves the original fraction and five local derivations', () => {
  assert.match(bundle.problem.text, /sqrt|\\sqrt/);
  assert.match(bundle.problem.text, /f\(x\+2\)/);
  assert.equal(route.completion.answer.set.expression, 'Interval.open(1/3, 5)');
  assert.deepEqual(route.steps.slice(0, 5).map(row => row.title), [
    '求 f 的输入范围', '列出抽象调用的输入条件', '求抽象调用允许的范围',
    '求分母允许的范围', '取交集，写出定义域',
  ]);
  for (const step of route.steps.slice(0, 5)) {
    const ref = step.stream_steps[0];
    const completed = bundle.stream.math_steps.find(row => row.step_id === ref.step_id && row.math_step_sha256 === ref.math_step_sha256).highlight;
    assert.equal(step.stem_board.items[1].math, null);
    assert.deepEqual(step.stem_board.items[0], completed.items[0]);
    assert.equal(typeof completed.items[1].math, 'string');
  }
  const denominator = route.steps[3].stem_board.items[0];
  assert.match(denominator.note, /\\geq/);
  assert.match(denominator.note, /\\neq/);
  assert.match(route.steps[4].stem_board.items[0].math, /\\cap/);
});

test('mixed course completes ten decisions and exact original selection without T1 workspaces', () => {
  assert.equal(replay.actions.length, 10);
  const final = route.steps.at(-1);
  assert.equal(final.interaction.type, 'original_choice_exact_set');
  assert.deepEqual(final.expected_answer.correct_labels, ['D']);
  assert.equal(final.require_complete_options, undefined);
  for (let index = 0; index < replay.actions.length; index++) {
    const before = replayState(bundle, replay, index);
    const decision = currentDecision(bundle, before);
    assert.equal(decision.id, replay.actions[index].decision);
    assert.equal(before.done, false);
    assert.equal(hasOptionWorkspaces(bundle, before), false);
    const wrong = decision.interaction.type === 'choice'
      ? decision.interaction.options.filter(row => !decision.expected_answer.one_of.includes(row.value)).map(row => row.value)
      : decision.interaction.type === 'original_choice_exact_set' ? [[], ['A'], ['A', 'D'], ['D', 'D'], ['Z']] : [];
    for (const answer of wrong) {
      const rejected = submitAnswer(bundle, before, {decision: decision.id, answer});
      assert.equal(rejected.lastFeedback.status, 'wrong');
      assert.equal(currentDecision(bundle, rejected).id, decision.id);
      assert.equal(rejected.done, false);
    }
    const passed = submitAnswer(bundle, before, replay.actions[index]);
    assert.equal(passed.lastFeedback.status, 'passed');
    assert.equal(passed.done, index === 9);
  }
});
