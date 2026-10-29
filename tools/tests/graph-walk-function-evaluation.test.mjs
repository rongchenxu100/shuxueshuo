import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {compileCourse} from '../build-graph-walk-topic.mjs';
import {loadSources, repoRoot} from '../lib/public-knowledge-sources.mjs';
import {nativePracticeContract} from '../lib/graph-walk-practice.mjs';
import {createState, currentDecision, submitAnswer, replayState, streamStepGraph} from '../../site/assets/graph-walk/walk-state.mjs';

const read = async path => JSON.parse(await fs.readFile(`${repoRoot}/${path}`, 'utf8'));
const graph = await read('site/knowledge/graph.json');
const {nodes} = await loadSources();

for (const [name, targetCount] of [['q28a', 2], ['q28b', 2], ['q28c', 2], ['q28d', 1], ['q29b', 2]]) {
  test(`${name}: original goal certificates, all inputs and both study modes survive the topic composition`, async () => {
    const source = await read(`site/data/graph-walk/function-concepts-${name}.source.json`);
    const evidence = await read(source.evidence);
    const originalStatements = evidence.lesson.goals.map(goal => goal.walk.bundle.problem.text);
    const {bundle, replay} = compileCourse(source, evidence, graph, nodes);
    assert.equal(bundle.problem.text, source.statement);
    assert.doesNotMatch(bundle.problem.text, /【例\s*10】|[（(][1-4][）)]\s*(?:求|判断)/);
    assert.deepEqual(evidence.lesson.goals.map(goal => goal.walk.bundle.problem.text), originalStatements,
      'independent question wording must not rewrite the source evidence');
    const targets = source.targetRefs || [source.targetRef];
    assert.equal(targets.length, targetCount);
    const routeId = Object.keys(bundle.routes)[0], route = bundle.routes[routeId];
    const native = nativePracticeContract(bundle);
    assert.equal(native.routes[routeId].steps.length, route.steps.length);
    if (targetCount > 1) {
      assert.equal(route.completion.answer.kind, 'goal_group');
      assert.equal(route.completion.verified_route_sha256, undefined, 'no single goal certificate can prove all goals');
      assert.deepEqual(route.goal_completions.map(item => item.target_ref), targets);
      assert.equal(new Set(route.goal_completions.map(item => item.verified_route_sha256)).size, targetCount);
      for (const target of targets) {
        const {bundle: single} = compileCourse({...source, targetRefs: undefined, targetRef: target}, evidence, graph, nodes);
        const captured = single.routes[routeId].completion;
        assert.equal(route.goal_completions.find(item => item.target_ref === target).verified_route_sha256, captured.verified_route_sha256);
        for (const node of single.graph.nodes) assert.deepEqual(bundle.graph.nodes.find(item => item.id === node.id), node);
        for (const edge of single.graph.edges) assert.deepEqual(bundle.graph.edges.find(item => item.id === edge.id), edge);
      }
    }
    let state = createState(bundle);
    for (const [index, action] of replay.actions.entries()) {
      const decision = currentDecision(bundle, state);
      assert.equal(decision.id, action.decision);
      assert.equal(state.done, false, 'no goal prefix can complete the topic');
      const snapshot = structuredClone(state);
      assert.equal(replayState(bundle, replay).done, true);
      assert.deepEqual(state, snapshot, 'AI replay never writes student progress');
      if (decision.source === 'stream') {
        assert.ok(targets.includes(decision.target_ref || targets[0]));
        const step = bundle.stream.math_steps.find(item => item.step_id === decision.stream_steps[0].step_id);
        assert.equal(step.target_ref, decision.target_ref || targets[0]);
        assert.deepEqual(step, evidence.stream.math_steps.find(item => item.step_id === step.step_id),
          'composition cannot rewrite mathematical identity, ordinal or hash');
        const checked = streamStepGraph(bundle, {...bundle.stream, target_ref: step.target_ref, route_id: routeId,
          step_id: step.step_id, math_step_sha256: step.math_step_sha256});
        assert.ok(checked.logs.length);
        assert.equal(streamStepGraph(bundle, {...step, target_ref: '/root/goals/999'}).logs.length, 0);
      }
      if (decision.stem_board) assert.equal(decision.stem_board.items[1].math, null);
      state = submitAnswer(bundle, state, action);
      assert.equal(state.lastFeedback.status, 'passed');
      const prefix = {...replay, status: 'partial', actions: replay.actions.slice(0, index + 1)};
      const restored = replayState(bundle, prefix);
      assert.equal(restored.done, state.done);
      assert.equal(currentDecision(bundle, restored)?.id, currentDecision(bundle, state)?.id);
    }
    assert.equal(state.done, true);
    if (targetCount > 1) {
      const second = route.steps.find(item => item.target_ref === targets[1]);
      assert.ok(second && second.id !== 'D1');
      const firstLastIndex = replay.actions.findIndex(action => action.decision === second.id);
      assert.ok(firstLastIndex > 0);
      assert.equal(replayState(bundle, {...replay, status: 'partial'}, firstLastIndex).done, false);
    }
  });
}
