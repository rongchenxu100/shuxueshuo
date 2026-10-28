// Verify the real exported T3 lesson through the shared student state machine.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {compileCourse} from '../build-graph-walk-topic.mjs';
import {loadSources, repoRoot} from '../lib/public-knowledge-sources.mjs';
import {nativePracticeContract} from '../lib/graph-walk-practice.mjs';
import {createState, currentDecision, submitAnswer, replayState} from '../../site/assets/graph-walk/walk-state.mjs';
import {replayAnswer} from '../../site/assets/graph-walk/walk-replay.mjs';

const evidence = JSON.parse(await fs.readFile(process.argv[2], 'utf8'));
const graph = JSON.parse(await fs.readFile(`${repoRoot}/site/knowledge/graph.json`, 'utf8'));
const {nodes} = await loadSources(repoRoot);
const {bundle, replay} = compileCourse({schemaVersion: 1, problemId: 'abstract-domain-acceptance-test',
  page: '/topics/function-concepts/q25/', topicHref: '/topics/function-concepts/',
  title: '抽象函数的定义域', targetRef: '/root/goals/0'}, evidence, graph, nodes);
const routeId = Object.keys(bundle.routes)[0], route = bundle.routes[routeId];
assert.ok(bundle.intro.some(step => step.id === 'D1'), 'photo lesson must retain its reading step');
assert.equal(route.completion.answer.kind, 'find_abstract_domain');
assert.equal(route.completion.answer.set.expression, 'Interval(-1, 3/2)');
assert.doesNotMatch(JSON.stringify(route.steps), /\\text\{None\}|None=/);
const deductions = route.steps.filter(step => step.stem_board?.layout === 'derivation');
assert.equal(deductions.length, 3, 'the lesson has exactly three focused deduction cards');
for (const decision of deductions) {
  const board = decision.stem_board;
  assert.equal(board.items.length, 2);
  assert.equal(board.items[1].math, null, 'each current conclusion starts unknown');
  assert.doesNotMatch(JSON.stringify(board), /对照板|目标式|上轨|下轨/);
  const ref = decision.stream_steps[0];
  const completed = bundle.stream.math_steps.find(step => step.step_id === ref.step_id && step.math_step_sha256 === ref.math_step_sha256).highlight;
  assert.equal(completed.layout, 'derivation');
  assert.deepEqual(completed.items[0], board.items[0]);
  assert.equal(completed.items[1].label, board.items[1].label);
  assert.equal(typeof completed.items[1].math, 'string');
}
const final = route.steps.find(step => step.interaction?.field === 'domain_answer');
assert.ok(final, 'the outer-variable domain remains a student decision');
assert.ok(!JSON.stringify(final.stem_board).includes(route.completion.answer.set.latex),
  'the pending domain card must not print the answer on its board');
let state = createState(bundle);
const actions = [];
// Student history is a prefix, not an AI recording declared completed. The
// shared replay reducer also accepts an unfinished history without that status.
const restoreStudent = history => replayState(bundle, {
  schemaVersion: 2, bundleVersion: bundle.bundleVersion, problemId: bundle.problemId,
  routes: [routeId], actions: history,
});
while (currentDecision(bundle, state)) {
  const step = currentDecision(bundle, state);
  const answer = replayAnswer(step, routeId);
  assert.notEqual(answer, null);
  if (step.interaction.type === 'choice') {
    const options = step.interaction.options;
    assert.equal(new Set(options.map(option => option.label)).size, options.length);
    const wrong = options.find(option => !step.expected_answer.one_of.includes(option.value));
    if (wrong) {
      const rejected = submitAnswer(bundle, state, {decision: step.id, answer: wrong.value});
      assert.equal(rejected.lastFeedback.status, 'wrong');
      assert.equal(currentDecision(bundle, rejected).id, step.id);
      assert.equal(rejected.done, false);
    }
  }
  const before = structuredClone(state);
  const ai = replayState(bundle, replay);
  assert.equal(ai.done, true);
  assert.deepEqual(state, before, 'AI replay cannot advance student progress');
  const action = {decision: step.id, answer};
  actions.push(action);
  state = submitAnswer(bundle, state, action);
  assert.equal(state.lastFeedback.status, 'passed');
  const saved = JSON.parse(JSON.stringify(state));
  assert.equal(currentDecision(bundle, saved)?.id, currentDecision(bundle, state)?.id);
  assert.equal(saved.done, state.done, 'refresh preserves the student completion state');
  const restored = restoreStudent(JSON.parse(JSON.stringify(actions)));
  assert.equal(currentDecision(bundle, restored)?.id, currentDecision(bundle, state)?.id);
  assert.deepEqual(restored.introCompleted, state.introCompleted);
  assert.deepEqual(restored.run.completed, state.run.completed);
  assert.equal(restored.done, state.done);
}
assert.equal(state.done, true);
assert.equal(restoreStudent(actions).done, true);
process.stdout.write(JSON.stringify(nativePracticeContract(bundle)));
