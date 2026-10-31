import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {createRequire} from 'node:module';
import {compileCourse} from '../build-graph-walk-topic.mjs';
import {loadSources, repoRoot} from '../lib/public-knowledge-sources.mjs';
import {buildStreamReplay} from '../../site/assets/graph-walk/walk-replay.mjs';
import {createState, currentDecision, submitAnswer, replayState, extendStreamBundle} from '../../site/assets/graph-walk/walk-state.mjs';

const read = async path => JSON.parse(await fs.readFile(`${repoRoot}/${path}`, 'utf8'));
const graph = await read('site/knowledge/graph.json');
const {nodes} = await loadSources();
const source = await read('site/data/graph-walk/function-concepts-range-q18.source.json');
const evidence = await read(source.evidence);
const {bundle, replay} = compileCourse(source, evidence, graph, nodes);
const katex = createRequire(import.meta.url)('../../site/assets/practice/vendor/katex-0.18.9/katex.min.js');

test('Q18 teaches integer translation, exact coverage and the image union without revealing answers', () => {
  const route = bundle.routes['translation-range'];
  assert.equal(route.method, 'method-translation-range');
  assert.equal(route.completion.answer.kind, 'find_translation_range');
  assert.equal(route.completion.answer.set.expression, 'Interval(-15, 11)');
  assert.equal(bundle.intro[2].id, 'D3-domain');
  assert.deepEqual(route.steps.map(s => s.title), ['写出平移后的函数值', '用平移盖住输入范围', '把各段值域合起来']);
  assert.equal(route.label, '整段平移求值域法');
  for (const step of [...bundle.intro, ...route.steps]) {
    if (step.stem_board?.layout === 'derivation') assert.equal(step.stem_board.items[1].math, null);
    for (const board of [step.stem_board, step.completion_board]) {
      const text = JSON.stringify(board || {});
      assert.doesNotMatch(text, /\bI_0\b|\bD=/);
      for (const item of board?.items || []) {
        if (item.math) assert.doesNotThrow(() => katex.renderToString(item.math, {throwOnError: true, strict: 'ignore'}));
      }
    }
    for (const text of [step.question, ...((step.interaction?.options || []).map(o => o.label))]) {
      for (const [, math] of String(text).matchAll(/\$([^$]+)\$/g)) {
        assert.doesNotThrow(() => katex.renderToString(math, {throwOnError: true, strict: 'ignore'}));
      }
    }
  }
  assert.match(route.steps[1].question, /例如|盖住/);
  assert.match(route.steps[2].question, /合起来/);
  assert.equal(route.steps[1].graph?.kind, 'number_line');
  assert.equal(route.steps[2].graph?.kind, 'number_line');
  assert.equal(route.steps[2].graph.params.variable, 'y');
  const final = route.steps.at(-1).completion_graph;
  assert.equal(final.kind, 'number_line');
  assert.deepEqual(final.params.pieces, [{from: -15, to: 11, left_closed: true, right_closed: true}]);
  assert.equal(final.params.variable, 'y');
});

test('Q18 wrong answers stay in the current step; restored progress and photo replay finish all three cards', () => {
  let state = createState(bundle);
  for (const [index, action] of replay.actions.entries()) {
    const step = currentDecision(bundle, state);
    assert.equal(step.id, action.decision);
    if (step.interaction.type === 'choice' && step.expected_answer.one_of) {
      const wrong = step.interaction.options.find(o => !step.expected_answer.one_of.includes(o.value));
      assert.ok(wrong);
      const rejected = submitAnswer(bundle, state, {decision: step.id, answer: wrong.value});
      assert.equal(rejected.lastFeedback.status, 'wrong');
      assert.equal(currentDecision(bundle, rejected).id, step.id);
    }
    state = submitAnswer(bundle, state, action);
    assert.equal(state.lastFeedback.status, 'passed');
    const restored = replayState(bundle, {...replay, status: 'partial', actions: replay.actions.slice(0, index+1)});
    assert.equal(currentDecision(bundle, restored)?.id, currentDecision(bundle, state)?.id);
  }
  assert.equal(state.done, true);
  const streamed = extendStreamBundle(bundle, evidence.stream, source.targetRef, graph);
  assert.equal(replayState(streamed, buildStreamReplay(streamed, {actions: replay.actions.slice(0, 2)})).done, true);
});
