import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {createRequire} from 'node:module';
import {compileCourse} from '../build-graph-walk-topic.mjs';
import {loadSources, repoRoot} from '../lib/public-knowledge-sources.mjs';
import {createState, currentDecision, submitAnswer, gradeDecision, replayState, graphState} from '../../site/assets/graph-walk/walk-state.mjs';
import {replayAnswer} from '../../site/assets/graph-walk/walk-replay.mjs';

const read = async path => JSON.parse(await fs.readFile(`${repoRoot}/${path}`, 'utf8'));
const {nodes} = await loadSources();
const graph = await read('site/knowledge/graph.json');
const rule = 'rule-piecewise-method';
const katex = createRequire(import.meta.url)('../../site/assets/practice/vendor/katex-0.18.9/katex.min.js');

for (const [name, method] of [
  ['b10', 'method-function-evaluation'],
  ['b10-v1', 'method-piecewise-equation'],
  ['b10-v2', 'method-piecewise-inequality'],
  ['b11', 'method-piecewise-range'],
  ['b11-v1', 'method-piecewise-range-parameter'],
  ['b11-v2', 'method-piecewise-range-parameter'],
]) {
  test(`${name}: show the admitted method and start its route without method selection`, async () => {
    const source = await read(`site/data/graph-walk/function-representations-${name}.source.json`);
    const {bundle, replay} = compileCourse(source, await read(source.evidence), graph, nodes);
    const d3 = bundle.intro.find(step => step.id === 'D3');
    assert.equal(d3.title, '解题方法');
    assert.equal(d3.submit_label, '开始解题');
    assert.equal(d3.interaction.type, 'read');
    assert.equal(d3.interaction.connections, undefined);
    assert.equal(d3.interaction.methods.length, 1);
    const [route] = Object.keys(bundle.routes);
    assert.deepEqual(d3.route_by_answer, {read: route});
    assert.match(d3.question, new RegExp(`使用${bundle.routes[route].label}：`));
    assert.equal(gradeDecision(d3, 'read').status, 'passed');
    assert.equal(gradeDecision(d3, {checks: ['inequality'], method: 'inequality'}).status, 'wrong');
    let state = createState(bundle);
    while (currentDecision(bundle, state).id !== 'D3') {
      const step = currentDecision(bundle, state);
      state = submitAnswer(bundle, state, {decision: step.id, answer: replayAnswer(step, Object.keys(bundle.routes)[0])});
      assert.equal(state.lastFeedback.status, 'passed');
    }
    state = submitAnswer(bundle, state, {decision: 'D3', answer: 'read'});
    assert.equal(state.lastFeedback.status, 'passed');
    assert.equal(bundle.routes[state.run.route].method, method);
    assert.equal(state.introCompleted.at(-1).answer, 'read');
    const trace = graphState(bundle, state);
    assert.equal(trace.nodes[method], 'confirmed');
    assert.equal(trace.nodes[rule], undefined);
    assert.equal(graph.nodes.some(node => node.id === rule), false);
    assert.equal(replayState(bundle, replay).done, true);
  });
}

test('b11: preserve branch endpoints and combine output ranges before matching the original option', async () => {
  const source = await read('site/data/graph-walk/function-representations-b11.source.json');
  const {bundle} = compileCourse(source, await read(source.evidence), graph, nodes);
  const route = Object.values(bundle.routes)[0];
  const graphs = route.steps.filter(step => step.graph).map(step => step.graph);
  assert.ok(graphs.some(g => g.kind === 'quadratic' && g.params.interval_closed.every(Boolean)));
  assert.ok(graphs.some(g => g.kind === 'linear' && g.params.interval_closed[0] && !g.params.interval_closed[1]));
  const union = route.steps.find(step => step.condition_number_lines);
  assert.equal(union.condition_number_lines.length, 2);
  const lines = [...union.condition_number_lines, union.completion_number_line];
  assert.ok(lines.every(line => line.variable === 'y'));
  for (const line of lines) {
    assert.deepEqual(line.bounds, lines[0].bounds);
    assert.deepEqual(line.ticks, lines[0].ticks);
  }
  assert.deepEqual(lines.map(line => line.intervals[0].right_closed), [true, false, true]);
  assert.equal(union.stem_board.items[1].math, null);
  assert.match(union.feedback.answer, /f\(0\)=3/);
  const final = route.steps.at(-1);
  assert.deepEqual(final.expected_answer.correct_labels, ['D']);
  assert.equal(gradeDecision(final, ['D']).status, 'passed');
  assert.equal(gradeDecision(final, ['C']).status, 'wrong');
});

test('b11 parameter variants: all card formulas render and J2 number lines share the output scale', async () => {
  for (const name of ['b11-v1', 'b11-v2']) {
    const source = await read(`site/data/graph-walk/function-representations-${name}.source.json`);
    const {bundle} = compileCourse(source, await read(source.evidence), graph, nodes);
    const steps = Object.values(bundle.routes)[0].steps;
    for (const step of steps) {
      for (const board of [step.stem_board, step.completion_board].filter(Boolean)) {
        for (const item of board.items) if (item.math) {
          assert.doesNotThrow(() => katex.renderToString(item.math, {throwOnError: true, strict: 'ignore'}), `${name}: ${step.title}`);
        }
      }
      for (const text of [step.question, step.feedback?.answer, ...(step.interaction?.options || []).map(option => option.label),
        ...[step.stem_board, step.completion_board].filter(Boolean).flatMap(board =>
          [board.caption, ...board.items.flatMap(item => [item.label, item.note])])]) {
        for (const [, math] of String(text || '').matchAll(/\$\$?([^$]+)\$\$?/g)) {
          assert.doesNotThrow(() => katex.renderToString(math, {throwOnError: true, strict: 'ignore'}), `${name}: ${step.title}`);
        }
      }
    }
    const decision = steps.find(step => step.condition_number_lines);
    const lines = [...decision.condition_number_lines, ...[decision.completion_number_line].filter(Boolean)];
    assert.equal(lines.length, name === 'b11-v2' ? 3 : 2);
    for (const line of lines) {
      assert.equal(line.variable, 'y');
      assert.deepEqual(line.bounds, lines[0].bounds);
      assert.deepEqual(line.ticks, lines[0].ticks);
      assert.doesNotThrow(() => katex.renderToString(line.label, {throwOnError: true, strict: 'ignore'}));
    }
    assert.equal(decision.stem_board.items[1].math, null);
  }
});
