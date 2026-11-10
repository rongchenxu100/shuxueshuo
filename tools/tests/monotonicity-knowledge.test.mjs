import test from 'node:test';
import assert from 'node:assert/strict';
import {loadSources} from '../build-public-knowledge-graph.mjs';
import {validateGraph, scopeMembers} from '../../site/assets/knowledge-next/model.mjs';
import diagrams, {
  DEFINITION_CASES, OPERATION_CASES, COMPOSITION_CASES, EXTREMA_CASES,
  definitionValues, extremaPoints, plotGeometry,
} from '../../site/assets/explain/knowledge/monotonicity-explorer.js';

test('3.2 retains monotonicity themes alongside parity and reuses existing function identities', async () => {
  const {nodes, manifest} = await loadSources();
  const graph = {nodes, edges:validateGraph(nodes, manifest)};
  const section = nodes.find(n => n.id === 'section-3-2');
  assert.deepEqual(section.members.filter(m => m.relation === 'contains').map(m => m.ref), [
    'function-monotonicity', 'function-monotonicity-operations',
    'composite-function-monotonicity', 'function-range-extrema',
    'function-parity', 'function-parity-graph', 'function-graph-symmetry',
  ]);
  const members = scopeMembers(graph, section.id);
  for (const id of ['linear-interval-extremum', 'reciprocal-function', 'quadratic-function-properties']) {
    assert.ok(members.has(id), `shared function node ${id}`);
  }
  // These anchors are already referenced by published lessons.
  for (const [id, anchors] of [
    ['function-monotonicity', ['definition', 'interval', 'combine', 'endpoints']],
    ['function-range-extrema', ['range', 'extrema', 'attainability', 'quantified', 'extremum-conditions']],
  ]) for (const anchor of anchors) {
    assert.ok(nodes.find(n => n.id === id).entries.some(e => e.id === anchor), `${id}#${anchor}`);
  }
});

test('two-point examples distinguish increasing, decreasing and a turning curve', () => {
  assert.ok(definitionValues(DEFINITION_CASES.increasing, 0, 3).quotient > 0);
  assert.ok(definitionValues(DEFINITION_CASES.decreasing, 0, 3).quotient < 0);
  const turn = DEFINITION_CASES.turning;
  assert.ok(definitionValues(turn, -2, -1).quotient < 0);
  assert.ok(definitionValues(turn, 1, 2).quotient > 0);
  assert.equal(definitionValues(turn, -1, 1).relation, '=');
});

test('operation diagrams preserve the sign conditions and show genuine counterexamples', () => {
  const positive = OPERATION_CASES.positiveProduct, negative = OPERATION_CASES.negativeProduct;
  for (const x of [0, 1, 2]) {
    assert.ok(positive.f(x) > 0 && positive.g(x) > 0);
    assert.ok(negative.f(x) < 0 && negative.g(x) < 0);
  }
  assert.ok(positive.h(0) < positive.h(2));
  assert.ok(negative.f(0) < negative.f(2) && negative.g(0) < negative.g(2));
  assert.ok(negative.h(0) > negative.h(2));
  const difference = OPERATION_CASES.difference;
  assert.ok(difference.h(0) < difference.h(.5));
  assert.ok(difference.h(.5) > difference.h(2));
  assert.ok(OPERATION_CASES.reciprocal.h(0) > OPERATION_CASES.reciprocal.h(2));
});

test('all four compositions use the actual inner image as the outer domain', () => {
  for (const c of Object.values(COMPOSITION_CASES)) {
    const inputs = Array.from({length:21}, (_, i) => i / 10);
    const inner = inputs.map(c.g);
    assert.equal(Math.min(...inner), 1);
    assert.equal(Math.max(...inner), 3);
    for (const [i, x] of inputs.entries()) {
      assert.equal(c.h(x), c.F(c.g(x)));
      if (i) assert.equal(c.h(x) > c.h(inputs[i-1]), c.increasing);
    }
  }
});

test('open interval extrema distinguish boundary limits from attained values', () => {
  const c = EXTREMA_CASES.open;
  assert.deepEqual(extremaPoints(c), [
    {x:0,y:1,open:true}, {x:1,y:0,open:false}, {x:3,y:4,open:true},
  ]);
  assert.equal(c.f(1), 0);
  for (const x of [.001, .5, 1, 2, 2.999]) assert.ok(c.f(x) >= 0 && c.f(x) < 4);
  const counter = EXTREMA_CASES.converse;
  assert.equal(counter.f(0), 0);
  assert.equal(counter.f(3), 3);
  assert.ok(counter.f(1) > counter.f(2));
});

test('graphs keep every marked point within their axes and render all four resources', () => {
  for (const c of Object.values(EXTREMA_CASES)) {
    for (const compact of [false, true]) {
      const p = plotGeometry([c], compact);
      for (const mark of extremaPoints(c)) {
        assert.ok(p.sx(mark.x) > p.left && p.sx(mark.x) < p.right);
        assert.ok(p.sy(mark.y) > p.top && p.sy(mark.y) < p.bottom);
      }
    }
  }
  for (const part of ['definitionFigure', 'operationsFigure', 'compositionFigure', 'extremaFigure']) {
    const html = diagrams[part]();
    assert.match(html, /role="img" aria-label="[^"]+"/);
    assert.doesNotMatch(html, /NaN|undefined|Infinity/);
  }
});
