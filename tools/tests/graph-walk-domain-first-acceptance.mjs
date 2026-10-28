// Called by the Python integration test with a freshly exported real Stage3 run.
// This exercises the product compiler/state machine, not a handwritten bundle.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {isDeepStrictEqual} from 'node:util';
import {compileCourse} from '../build-graph-walk-topic.mjs';
import {loadSources, repoRoot} from '../lib/public-knowledge-sources.mjs';
import {nativePracticeContract} from '../lib/graph-walk-practice.mjs';
import {createState, currentDecision, submitAnswer, replayState} from '../../site/assets/graph-walk/walk-state.mjs';
import {optionProgress} from '../../site/assets/graph-walk/option-workspace.mjs';
import {replayAnswer} from '../../site/assets/graph-walk/walk-replay.mjs';

const evidence = JSON.parse(await fs.readFile(process.argv[2], 'utf8'));
const graph = JSON.parse(await fs.readFile(`${repoRoot}/site/knowledge/graph.json`, 'utf8'));
const {nodes} = await loadSources(repoRoot);
const {bundle, replay} = compileCourse({schemaVersion: 1, problemId: 'function-equality-domain-first-test',
  page: '/topics/function-concepts/q02/', topicHref: '/topics/function-concepts/',
  title: '同一函数：先比较定义域', targetRef: '/root/goals/0'}, evidence, graph, nodes);
const routeId = Object.keys(bundle.routes)[0], route = bundle.routes[routeId], final = route.steps.at(-1);
const mode = route.completion.original_choice.selection_mode;
assert.ok(['single', 'unspecified'].includes(mode));
const scalar = mode === 'single', correctAnswer = scalar ? 'C' : ['C'];
assert.equal(final.interaction.type, scalar ? 'choice' : 'original_choice_exact_set');
assert.deepEqual(final.expected_answer, scalar ? {one_of: ['C']}
  : {correct_labels: ['C'], option_labels: ['A', 'B', 'C', 'D']});
assert.deepEqual(final.require_complete_options, ['option_a', 'option_b', 'option_c', 'option_d']);
assert.equal(route.completion.original_choice.kind, scalar ? 'single_choice' : 'multiple_choice');
const verdicts = route.steps.filter(step => step.option_context?.phase === 'verdict');
assert.deepEqual(verdicts.map(step => step.option_context.label), ['A', 'B', 'C', 'D']);
assert.deepEqual(verdicts.map(step => step.expected_answer.one_of), [['different'], ['different'], ['equal'], ['different']]);
assert.deepEqual(route.steps.filter(step => step.interaction.field === 'correspondence')
  .map(step => step.option_context.label), ['A', 'C']);
let student = createState(bundle);
const actions = [];
while (currentDecision(bundle, student)?.id !== final.id) {
  const decision = currentDecision(bundle, student);
  assert.ok(decision);
  assert.equal(optionProgress(bundle, student).finalReady, false);
  const premature = submitAnswer(bundle, student, {decision: final.id, answer: correctAnswer});
  assert.equal(premature.lastFeedback.status, 'wrong');
  assert.equal(premature.done, false);
  assert.equal(currentDecision(bundle, premature).id, decision.id);
  if (decision.option_context?.phase === 'verdict') {
    const correct = decision.expected_answer.one_of[0];
    const wrong = submitAnswer(bundle, student, {decision: decision.id, answer: correct === 'equal' ? 'different' : 'equal'});
    assert.equal(wrong.lastFeedback.status, 'wrong');
    assert.equal(currentDecision(bundle, wrong).id, decision.id);
    assert.equal(optionProgress(bundle, wrong).finalReady, false);
  }
  const action = {decision: decision.id, answer: replayAnswer(decision, routeId)};
  actions.push(action);
  student = submitAnswer(bundle, student, action);
  assert.equal(student.lastFeedback.status, 'passed');
}
assert.equal(optionProgress(bundle, student).finalReady, true);
assert.ok(optionProgress(bundle, student).options.every(option => option.complete));
assert.equal(optionProgress(bundle, student).finalPassed, false);
const wrongAnswers = scalar ? ['', 'A', 'B', 'D', 'Z', [], ['C'], ['C', 'D']]
  : ['', 'C', [], ['A'], ['B'], ['D'], ['C', 'D'], ['C', 'C'], ['Z']];
for (const answer of wrongAnswers) {
  const wrong = submitAnswer(bundle, student, {decision: final.id, answer});
  assert.equal(wrong.lastFeedback.status, 'wrong');
  assert.equal(wrong.done, false);
  assert.equal(currentDecision(bundle, wrong).id, final.id);
}
const untouched = structuredClone(student);
const ai = replayState(bundle, replay);
assert.equal(ai.done, true);
assert.deepEqual(student, untouched);
assert.equal(student.done, false);
actions.push({decision: final.id, answer: correctAnswer});
student = submitAnswer(bundle, student, actions.at(-1));
assert.equal(student.done, true);
assert.equal(optionProgress(bundle, student).finalPassed, true);
for (const action of [{decision: final.id, answer: 'D'},
  {decision: verdicts[0].id, answer: 'equal'}, {decision: final.id, answer: correctAnswer}]) {
  assert.ok(isDeepStrictEqual(submitAnswer(bundle, student, action), student),
    'completed comparison must reject a resubmission without changing its state');
}
const restored = replayState(bundle, {...replay, actions});
assert.equal(restored.done, true);
assert.deepEqual(restored.run.completed, student.run.completed);
process.stdout.write(JSON.stringify(nativePracticeContract(bundle)));
