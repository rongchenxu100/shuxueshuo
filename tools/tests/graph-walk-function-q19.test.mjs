import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {createState, currentDecision, submitAnswer, replayState} from '../../site/assets/graph-walk/walk-state.mjs';
import {replayAnswer} from '../../site/assets/graph-walk/walk-replay.mjs';
import {optionProgress} from '../../site/assets/graph-walk/option-workspace.mjs';
import {exportContent} from '../export-public-knowledge.mjs';

const read = async name => JSON.parse(await fs.readFile(new URL(name, import.meta.url), 'utf8'));
const id = 'function-concepts-q19', routeId = 'function-equality';
const bundle = await read(`../../site/data/graph-walk/${id}.json`);
const replay = await read(`../../site/data/graph-walk/${id}.replay.json`);
const route = bundle.routes[routeId];

test('Q19 retains the shared original baseline and four separate option workspaces', async () => {
  const topic = await read('../../site/data/knowledge-next/topics/function-concepts.json');
  assert.ok(topic.groups.find(group => group.id === 'equality').problems.includes(id));
  assert.equal(topic.problems[id].path, '/topics/function-concepts/q19/');
  assert.deepEqual(bundle.option_workspaces.map(option => option.label), [...'ABCD']);
  assert.match(bundle.problem.text, /y=2x\^2\+1/);
  assert.doesNotMatch(bundle.problem.text, /【例5】|ABC|答案/);
  const domains = route.steps.filter(step => step.interaction.type === 'checklist');
  assert.equal(domains.length, 4);
  for (const step of domains) {
    assert.deepEqual(step.interaction.slots.map(slot => slot.label), ['题干函数', `选项 ${step.option_context.label} 的函数`]);
    assert.match(step.question, /题干函数的解析式/);
    assert.doesNotMatch(step.question, /[fg]\(x\)/);
  }
});

test('Q19 gives ABC their sign proofs and D its original forbidden input before closing each item', () => {
  const verdicts = route.steps.filter(step => step.option_context?.phase === 'verdict');
  assert.deepEqual(verdicts.map(step => step.expected_answer.one_of), [['equal'], ['equal'], ['equal'], ['different']]);
  const proofSteps = route.steps.filter(step => step.interaction.field === 'correspondence');
  assert.deepEqual(proofSteps.map(step => step.option_context.label), [...'ABC']);
  assert.ok(proofSteps.every(step => />0/.test(step.feedback.answer)));
  assert.match(proofSteps[1].feedback.answer, /\\sqrt/);
  assert.match(verdicts[3].feedback.answer, /-1/);
  assert.match(verdicts[3].feedback.answer, /化简不能补回/);
  assert.equal(bundle.stream.math_steps.length, 11);
  assert.equal(replay.actions.length, 15);
  assert.equal(route.steps.filter(step => step.stream_part_count === 2 && step.stream_part_index === 0).length, 3);
});

test('Q19 cannot skip option work or finish with incomplete or extra final labels', () => {
  const final = route.steps.at(-1);
  let state = createState(bundle);
  const skipped = submitAnswer(bundle, state, {decision: final.id, answer: ['A', 'B', 'C']});
  assert.equal(skipped.lastFeedback.status, 'wrong');
  while (currentDecision(bundle, state).id !== final.id) {
    const step = currentDecision(bundle, state);
    if (step.option_context?.label === 'D' && step.option_context.phase === 'verdict') {
      const wrong = submitAnswer(bundle, state, {decision: step.id, answer: 'equal'});
      assert.equal(wrong.lastFeedback.status, 'wrong');
      assert.equal(currentDecision(bundle, wrong).id, step.id);
      assert.equal(optionProgress(bundle, wrong).finalReady, false);
    }
    state = submitAnswer(bundle, state, {decision: step.id, answer: replayAnswer(step, routeId)});
    assert.equal(state.lastFeedback.status, 'passed');
  }
  assert.equal(optionProgress(bundle, state).finalReady, true);
  assert.equal(optionProgress(bundle, state).finalPassed, false);
  for (const answer of [[], ['A', 'B'], ['A', 'B', 'C', 'D'], ['A', 'A', 'B', 'C'], ['A', 'B', 'C', 'Z']]) {
    const wrong = submitAnswer(bundle, state, {decision: final.id, answer});
    assert.equal(wrong.lastFeedback.status, 'wrong');
    assert.equal(wrong.done, false);
  }
  state = submitAnswer(bundle, state, {decision: final.id, answer: ['C', 'B', 'A']});
  assert.equal(state.done, true);
  assert.equal(replayState(bundle, replay).done, true);
});

test('Q19 publication preserves all 15 independent grading contracts and exact ABC handoff', async () => {
  const data = await exportContent();
  const problem = data.practice_problems.find(row => row.id === id);
  assert.equal(problem.path, '/topics/function-concepts/q19/');
  assert.equal(data.practice_steps.filter(step => step.problem_id === id).length, 15);
  const published = problem.problem_data._graph_walk;
  assert.equal(published.bundleVersion, bundle.bundleVersion);
  assert.deepEqual(published.routes[routeId].steps.at(-1).expected_answer,
    {correct_labels: ['A', 'B', 'C'], option_labels: ['A', 'B', 'C', 'D']});
});
