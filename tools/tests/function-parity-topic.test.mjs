import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {createState, currentDecision, submitAnswer, replayState} from '../../site/assets/graph-walk/walk-state.mjs';
import {replayAnswer} from '../../site/assets/graph-walk/walk-replay.mjs';

const read = async name => JSON.parse(await fs.readFile(name, 'utf8'));
const topic = await read('site/data/knowledge-next/topics/function-parity.json');

test('all six parity groups publish the complete source questions and six additional exercises', async () => {
  assert.deepEqual(topic.groups.map(group => [group.id, group.problems.length]), [
    ['judgment', 2], ['parameter', 7], ['formula', 9], ['inequality', 6], ['symmetry', 2], ['shifted-odd', 5],
  ]);
  assert.deepEqual(topic.knowledgeGroups[0].refs,
    ['function-parity', 'function-parity-graph', 'function-graph-symmetry']);
  const grouped = topic.groups.flatMap(group => group.problems);
  assert.equal(new Set(grouped).size, 31);
  assert.deepEqual(new Set(grouped), new Set(Object.keys(topic.problems)));
  const paths = Object.values(topic.problems).map(entry => entry.path);
  assert.equal(new Set(paths).size, 31);
  for (let n = 2; n <= 24; n++) assert.ok(paths.includes(`/topics/function-parity/q${String(n).padStart(2, '0')}/`));
  for (const path of ['/q01a/', '/q01b/', ...Array.from({length: 6}, (_, i) => `/variant${i+1}/`)]) {
    assert.ok(paths.includes(`/topics/function-parity${path}`));
  }
  let goals = 0;
  for (const [id, entry] of Object.entries(topic.problems)) {
    const source = await read(`site/data/graph-walk/${id}.source.json`);
    assert.equal(source.problemId, id);
    assert.equal(source.page, entry.path);
    assert.equal(source.preview, undefined);
    assert.equal(entry.bundle, `/data/graph-walk/${id}.json`);
    const targets = source.targetRefs || [source.targetRef];
    goals += targets.length;
    const record = await read(source.authoringSource);
    // A01 intentionally has a separate page per goal; every other source is published whole.
    if (!['/topics/function-parity/q01a/', '/topics/function-parity/q01b/'].includes(entry.path)) {
      assert.deepEqual(targets, record.candidate.root.goals.map((_, index) => `/root/goals/${index}`));
    }
    const html = await fs.readFile(`site${entry.path}index.html`, 'utf8');
    const config = JSON.parse(html.match(/<script type="application\/json" id="graph-walk-page">(.*?)<\/script>/s)[1]);
    assert.equal(config.problemId, id);
    assert.equal(config.bundleUrl, entry.bundle);
    assert.equal(config.preview, undefined);
  }
  assert.equal(goals, 35);
});

for (const [id, entry] of Object.entries(topic.problems)) {
  test(`${id}: every published route grades to completion and resumes from saved answers`, async () => {
    const bundle = await read(`site${entry.bundle}`);
    const replay = await read(`site/data/graph-walk/${id}.replay.json`);
    const source = await read(`site/data/graph-walk/${id}.source.json`);
    const targets = source.targetRefs || [source.targetRef];
    assert.equal(replayState(bundle, replay).done, true);
    assert.doesNotMatch(bundle.problem.text, /【?变式\s*\d/);
    for (const [routeId, route] of Object.entries(bundle.routes)) {
      const completions = route.goal_completions || [route.completion];
      assert.deepEqual(completions.map(value => value.target_ref), targets);
      assert.ok(completions.every(value => value.status === 'verified' && value.available));
      let state = createState(bundle);
      const actions = [];
      while (!state.done && actions.length < 300) {
        const step = currentDecision(bundle, state);
        assert.ok(step);
        const wrong = step.interaction.type === 'choice' && step.interaction.options
          .find(option => step.expected_answer?.one_of && !step.expected_answer.one_of.includes(option.value));
        if (wrong) {
          const rejected = submitAnswer(bundle, state, {decision: step.id, answer: wrong.value});
          assert.equal(rejected.lastFeedback.status, 'wrong');
          assert.equal(currentDecision(bundle, rejected).id, step.id);
        }
        const action = {decision: step.id, answer: replayAnswer(step, routeId)};
        actions.push(action);
        state = submitAnswer(bundle, state, action);
        assert.equal(state.lastFeedback.status, 'passed', step.id);
      }
      assert.equal(state.done, true);
      const saved = {schemaVersion: 2, problemId: id, bundleVersion: bundle.bundleVersion,
        status: 'completed', routes: [routeId], actions};
      assert.equal(replayState(bundle, JSON.parse(JSON.stringify(saved))).done, true);
      const midpoint = Math.floor(actions.length / 2);
      const resumed = replayState(bundle, saved, midpoint);
      assert.equal(currentDecision(bundle, resumed).id, actions[midpoint].decision);
    }
  });
}
