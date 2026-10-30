import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {createRequire} from 'node:module';
import {compileCourse} from '../build-graph-walk-topic.mjs';
import {loadSources, repoRoot} from '../lib/public-knowledge-sources.mjs';
import {routeAnswerSummary} from '../../site/assets/graph-walk/stream-math-dom.mjs';
import {buildStreamReplay} from '../../site/assets/graph-walk/walk-replay.mjs';
import {createState, currentDecision, submitAnswer, replayState, extendStreamBundle} from '../../site/assets/graph-walk/walk-state.mjs';

const read = async path => JSON.parse(await fs.readFile(`${repoRoot}/${path}`, 'utf8'));
const katex = createRequire(import.meta.url)('../../site/assets/practice/vendor/katex-0.18.9/katex.min.js');
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

const q5Source = await read('site/data/graph-walk/function-concepts-range-q05.source.json');
const q5Evidence = await read(q5Source.evidence);
const q5 = compileCourse(q5Source, q5Evidence, graph, nodes);

test('Q5 asks for the original domain before M3 and carries the inner range into a separate square-root step', () => {
  assert.deepEqual(q5.bundle.intro.map(step => step.id), ['D1', 'D2', 'D3-domain', 'D3']);
  const domain = q5.bundle.intro[2];
  assert.equal(domain.interaction.type, 'choice');
  assert.equal(domain.stem_board.items[1].math, null);
  assert.match(domain.stem_board.items[0].math, /ge0/);
  assert.match(domain.completion_board.items[1].math, /-5, -1/);
  const route = q5.bundle.routes['quadratic-interval-range'];
  assert.equal(route.method, 'method-quadratic-interval-range');
  assert.equal(route.completion.answer.set.expression, 'Interval(0, 2)');
  const inner = route.steps.find(step => step.title === '确定被开方数范围');
  const root = route.steps.find(step => step.title === '写出原函数值域');
  assert.ok(inner && root && route.steps.indexOf(inner) < route.steps.indexOf(root));
  assert.match(inner.completion_board.items[1].math, /0, 4/);
  assert.match(root.stem_board.items[0].math, /0, 4/);
  assert.equal(root.stem_board.items[1].math, null);
  assert.match(root.completion_board.items[1].math, /0, 2/);
  assert.deepEqual(inner.completion_graphs.map(item => item.kind), ['quadratic', 'number_line']);
  assert.equal(root.completion_graph.kind, 'number_line');
});

test('Q5 requires the domain and every transformation; wrong answers and restored prefixes cannot skip them', () => {
  let state = createState(q5.bundle);
  for (const [index, action] of q5.replay.actions.entries()) {
    const step = currentDecision(q5.bundle, state);
    assert.equal(step.id, action.decision);
    if (step.interaction.type === 'choice' && step.expected_answer.one_of) {
      const wrong = step.interaction.options.find(option => !step.expected_answer.one_of.includes(option.value));
      const rejected = submitAnswer(q5.bundle, state, {decision: step.id, answer: wrong.value});
      assert.equal(rejected.lastFeedback.status, 'wrong');
      assert.equal(currentDecision(q5.bundle, rejected).id, step.id);
    }
    assert.equal(state.done, false);
    state = submitAnswer(q5.bundle, state, action);
    assert.equal(state.lastFeedback.status, 'passed');
    const restored = replayState(q5.bundle, {...q5.replay, status: 'partial', actions: q5.replay.actions.slice(0, index + 1)});
    assert.equal(currentDecision(q5.bundle, restored)?.id, currentDecision(q5.bundle, state)?.id);
  }
  assert.equal(state.done, true);
  const streamed = extendStreamBundle(q5.bundle, q5Evidence.stream, '/root/goals/0', graph);
  const liveReplay = buildStreamReplay(streamed, {actions: q5.replay.actions.slice(0, 2)});
  assert.equal(liveReplay.actions.filter(action => action.decision === 'D3-domain').length, 1);
  assert.equal(replayState(streamed, liveReplay).done, true);
});

for (const [q, answer] of [['08', 'Interval.Lopen(-5, 5/4)'], ['11', 'Interval(2, oo)'], ['16', 'Interval(-1, oo)']]) {
  const source = await read(`site/data/graph-walk/function-concepts-range-q${q}.source.json`);
  const evidence = await read(source.evidence);
  const course = compileCourse(source, evidence, graph, nodes);
  test(`Q${q} maps the input range before M3 and returns its full image to the original function`, () => {
    const route = course.bundle.routes['substitution-range'];
    assert.equal(route.method, 'method-substitution-range');
    assert.equal(route.completion.answer.set.expression, answer);
    const titles = route.steps.map(step => step.title);
    assert.ok(titles.indexOf('确定新变量范围') < titles.indexOf('配方'));
    assert.ok(titles.indexOf('写出值域') < titles.indexOf('回到原函数值域'));
    const range = route.steps.find(step => step.title === '确定新变量范围');
    assert.equal(range.stem_board.items[1].math, null);
    assert.ok(range.completion_board.items[1].math);
    assert.equal(course.bundle.intro[2].id, 'D3-domain');
    if (q === '11') assert.match(course.bundle.intro[2].completion_board.items[1].math, /D_\{f\}/);
    if (q === '16') {
      const define = route.steps.find(step => step.title === '设新变量');
      const rewrite = route.steps.find(step => step.title === '改写为新变量的函数');
      assert.match(define.question, /将绝对值.*整体设为新变量/);
      assert.match(rewrite.stem_board.items[0].math, /\\text\{或\}/);
      assert.match(rewrite.completion_board.items[0].math, /\\text\{或\}/);
      assert.doesNotMatch(rewrite.stem_board.items[0].math, /x=t\\\\x=-/);
      for (const board of [rewrite.stem_board, rewrite.completion_board]) {
        for (const item of board.items) {
          if (item.math) assert.doesNotThrow(() => katex.renderToString(item.math, {throwOnError: true, strict: 'ignore'}));
        }
      }
    }
  });
  test(`Q${q} topic and photo interactions block wrong answers and restore every completed prefix`, () => {
    let state = createState(course.bundle);
    for (const [index, action] of course.replay.actions.entries()) {
      const step = currentDecision(course.bundle, state);
      assert.equal(step.id, action.decision);
      if (step.interaction.type === 'choice' && step.expected_answer.one_of) {
        const wrong = step.interaction.options.find(option => !step.expected_answer.one_of.includes(option.value));
        assert.ok(wrong);
        const rejected = submitAnswer(course.bundle, state, {decision: step.id, answer: wrong.value});
        assert.equal(rejected.lastFeedback.status, 'wrong');
        assert.equal(currentDecision(course.bundle, rejected).id, step.id);
      }
      state = submitAnswer(course.bundle, state, action);
      assert.equal(state.lastFeedback.status, 'passed');
      const restored = replayState(course.bundle, {...course.replay, status: 'partial', actions: course.replay.actions.slice(0, index+1)});
      assert.equal(currentDecision(course.bundle, restored)?.id, currentDecision(course.bundle, state)?.id);
    }
    assert.equal(state.done, true);
    const streamed = extendStreamBundle(course.bundle, evidence.stream, '/root/goals/0', graph);
    const liveReplay = buildStreamReplay(streamed, {actions: course.replay.actions.slice(0, 2)});
    assert.equal(replayState(streamed, liveReplay).done, true);
    assert.equal(liveReplay.actions.filter(action => action.decision === 'D3-domain').length, 1);
  });
}
