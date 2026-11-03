import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {createRequire} from 'node:module';
import {compileCourse} from '../build-graph-walk-topic.mjs';
import {loadSources, repoRoot} from '../lib/public-knowledge-sources.mjs';
import {createState, currentDecision, submitAnswer, replayState} from '../../site/assets/graph-walk/walk-state.mjs';
import {replayAnswer} from '../../site/assets/graph-walk/walk-replay.mjs';
import {routeAnswerSummary} from '../../site/assets/graph-walk/stream-math-dom.mjs';

const read = async path => JSON.parse(await fs.readFile(`${repoRoot}/${path}`, 'utf8'));
const {nodes} = await loadSources();
const graph = await read('site/knowledge/graph.json');
const source = await read('site/data/graph-walk/function-representations-b12.source.json');
const evidence = await read(source.evidence);
const {bundle, replay} = compileCourse(source, evidence, graph, nodes);
const [routeId, route] = Object.entries(bundle.routes)[0];
const katex = createRequire(import.meta.url)('../../site/assets/practice/vendor/katex-0.18.9/katex.min.js');

test('both original targets retain their verified identity and sequential progress', () => {
  assert.deepEqual(route.methods, ['method-piecewise-modeling', 'method-piecewise-equation']);
  assert.deepEqual(route.goal_completions.map(r => r.target_ref), source.targetRefs);
  assert.equal(route.goal_completions[0].answer.kind, 'find_equation');
  assert.equal(route.goal_completions[1].answer.set.expression, '{320}');
  assert.equal(bundle.intro.find(s => s.id === 'D3').interaction.type, 'read');
  let state = createState(bundle);
  while (currentDecision(bundle, state)?.id !== 'goal-2-D1') {
    const step = currentDecision(bundle, state);
    assert.ok(step);
    state = submitAnswer(bundle, state, {decision:step.id, answer:replayAnswer(step, routeId)});
    assert.equal(state.lastFeedback.status, 'passed');
  }
  assert.equal(state.done, false);
  assert.equal(currentDecision(bundle, state).target_ref, '/root/goals/1');
  assert.equal(replayState(bundle, replay).done, true);
});

test('every question, choice, completed derivation and summary renders as mathematics', () => {
  const render = math => assert.doesNotThrow(() => katex.renderToString(math, {throwOnError:true, strict:'ignore'}), math);
  for (const step of [...bundle.intro, ...route.steps]) {
    const texts = [step.question, step.feedback?.answer, ...(step.interaction?.options || []).map(o => o.label)];
    for (const board of [step.stem_board, step.completion_board].filter(Boolean)) {
      for (const item of board.items || []) if (item.math) render(item.math);
      texts.push(...(board.lines || []));
    }
    for (const text of texts) for (const [, math] of String(text || '').matchAll(/\$\$?([^$]+)\$\$?/g)) render(math);
  }
  const summary = routeAnswerSummary(route.completion.answer);
  assert.equal(summary.items.length, 2);
  assert.match(summary.items[0].summary.label, /电费/);
  assert.match(summary.items[1].summary.label, /千瓦时/);
  for (const item of summary.items) render(item.summary.formula);
  assert.equal(routeAnswerSummary({kind:'find_equation',status:'complete',pricing:{},pieces:[]}), null);
});

test('marginal billing keeps previous charges, added quantity, and final checks visible', () => {
  const added = route.steps.find(s => s.title === '第2档：只给新增用量计费');
  assert.match(added.question, /x-180/);
  assert.equal(added.stem_board.items[1].math, null);
  const total = route.steps.find(s => s.title === '第3档：把两部分费用相加');
  assert.match(total.feedback.answer, /218\.5\+0\.9\(x-350\)=0\.9x-96\.5/);
  const inverse = route.steps.find(s => s.title === '先看费用关系，再反求用量');
  assert.match(inverse.stem_board.lines.join(''), /0\.65x-9/);
  assert.match(inverse.question, /199/);
  const check = route.steps.find(s => s.title === '代回计费规则，写出用电量');
  assert.match(check.feedback.answer, /108\+0\.65\(320-180\)=199/);
});
