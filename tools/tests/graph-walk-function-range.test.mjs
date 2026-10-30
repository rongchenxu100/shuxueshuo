import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {compileCourse} from '../build-graph-walk-topic.mjs';
import {loadSources, repoRoot} from '../lib/public-knowledge-sources.mjs';
import {routeAnswerSummary} from '../../site/assets/graph-walk/stream-math-dom.mjs';
import {buildStreamReplay} from '../../site/assets/graph-walk/walk-replay.mjs';
import {createState, currentDecision, submitAnswer, replayState, extendStreamBundle} from '../../site/assets/graph-walk/walk-state.mjs';

const read = async path => JSON.parse(await fs.readFile(`${repoRoot}/${path}`, 'utf8'));
const source = await read('site/data/graph-walk/function-concepts-range-q03.source.json');
const evidence = await read(source.evidence);
const graph = await read('site/knowledge/graph.json');
const {nodes} = await loadSources();
const {bundle, replay} = compileCourse(source, evidence, graph, nodes);

test('Q3 confirms the input interval before method selection without revealing its image', () => {
  assert.deepEqual(bundle.intro.map(step => step.id), ['D1', 'D2', 'D3-domain', 'D3']);
  const domain = bundle.intro[2];
  assert.equal(domain.interaction.type, 'read');
  assert.match(domain.question, /0, 3/);
  assert.doesNotMatch(domain.question, /1, 5/);
  const updated = extendStreamBundle(bundle, evidence.stream, '/root/goals/0', graph);
  assert.equal(updated.intro.filter(step => step.id === 'D3-domain').length, 1);
});

test('Q3 wrong answers block progress and every passed prefix restores in either study mode', () => {
  let state = createState(bundle);
  for (const [index, action] of replay.actions.entries()) {
    const step = currentDecision(bundle, state);
    assert.equal(step.id, action.decision);
    if (step.source === 'stream' && step.interaction.type === 'choice') {
      const wrong = step.interaction.options.find(option => !step.expected_answer.one_of.includes(option.value));
      assert.ok(wrong);
      const rejected = submitAnswer(bundle, state, {decision: step.id, answer: wrong.value});
      assert.equal(rejected.lastFeedback.status, 'wrong');
      assert.equal(currentDecision(bundle, rejected).id, step.id);
      assert.equal(rejected.done, false);
    }
    if (step.stem_board?.layout === 'derivation') assert.equal(step.stem_board.items[1].math, null);
    state = submitAnswer(bundle, state, action);
    assert.equal(state.lastFeedback.status, 'passed');
    const restored = replayState(bundle, {...replay, status: 'partial', actions: replay.actions.slice(0, index + 1)});
    assert.equal(currentDecision(bundle, restored)?.id, currentDecision(bundle, state)?.id);
  }
  assert.equal(state.done, true);
  assert.equal(replayState(bundle, replay).done, true);
});

test('Q3 photo replay adds the domain prerequisite after the stage-two prefix', () => {
  const streamed = extendStreamBundle(bundle, evidence.stream, '/root/goals/0', graph);
  for (const prefixLength of [2, 3]) {
    const liveReplay = buildStreamReplay(streamed, {actions: replay.actions.slice(0, prefixLength)});
    assert.deepEqual(liveReplay.actions.map(action => action.decision), replay.actions.map(action => action.decision));
    assert.equal(liveReplay.actions.filter(action => action.decision === 'D3-domain').length, 1);
    assert.equal(replayState(streamed, liveReplay).done, true);
  }
});

test('Q3 closes a full image and displays both the restricted curve and output number line', () => {
  const route = bundle.routes['quadratic-interval-range'];
  assert.equal(route.completion.answer.set.expression, 'Interval(1, 5)');
  assert.equal(routeAnswerSummary(route.completion.answer).label, '值域：');
  const {object, ...parameterAnswer} = route.completion.answer;
  assert.equal(object, 'f');
  assert.equal(routeAnswerSummary(parameterAnswer).label, '参数范围：');
  const image = route.steps.find(step => step.title === '写出值域');
  assert.deepEqual(image.completion_graphs.map(item => item.kind), ['quadratic', 'number_line']);
  assert.deepEqual(image.graph.params.interval, [0, 3]);
  assert.deepEqual(image.completion_graphs[1].params.pieces, [
    {from: 1, to: 5, left_closed: true, right_closed: true},
  ]);
});
