import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';

const context = vm.createContext({window: {}});
vm.runInContext(await fs.readFile(new URL('../../site/assets/practice/components.js', import.meta.url), 'utf8'), context);
const api = context.window.PracticeComponents;
const piece = (from, to, left_closed = false, right_closed = false) => ({from, to, left_closed, right_closed});
const graph = (pieces, extra = {}) => ({kind: 'reciprocal_sum', uid: 'reciprocal', params: {
  a: 0, b: 1, negative: false, bounds: [-5, 5, -2, 2], variable: 'u', outputVariable: 'v',
  interval: [null, null], interval_closed: [false, false], points: [], xTicks: [[0, '0']], yTicks: [],
  pieces, title: '反比例函数 v=1/u', description: 'u=Q(x)', ...extra,
}});
const curves = svg => [...svg.matchAll(/class="reciprocal-curve" d="([^"]+)"/g)].map(match => match[1]);
const abscissas = path => [...path.matchAll(/[ML]([\d.-]+) /g)].map(match => Number(match[1]));

test('reciprocal mapping draws both branches without joining across zero', () => {
  const spec = graph([piece(null, 0), piece(0, null)]);
  assert.equal(api.validateGraph(spec), true);
  const svg = api.graph(spec), paths = curves(svg), origin = 183;
  assert.equal(paths.length, 2);
  assert.ok(abscissas(paths[0]).every(x => x < origin));
  assert.ok(abscissas(paths[1]).every(x => x > origin));
  assert.match(svg, /font-style="italic">u<\/text>/);
  assert.match(svg, /font-style="italic">v<\/text>/);
  assert.doesNotMatch(svg, /class="graph-point"|NaN|Infinity/);
});

test('separate allowed intervals retain their gap and open and closed endpoints', () => {
  const svg = api.graph(graph([piece(1, 2, true, false), piece(3, 4, false, true)], {
    points: [{x: 1}, {x: 2, open: true}, {x: 3, open: true}, {x: 4}],
    xTicks: [[1, '1'], [2, '2'], [3, '3'], [4, '4']], yTicks: [[1, '1'], [0.25, '1/4']],
  }));
  const paths = curves(svg), screenX = value => 48 + (value + 5) / 10 * 270;
  assert.equal(paths.length, 2);
  assert.ok(Math.max(...abscissas(paths[0])) <= screenX(2));
  assert.ok(Math.min(...abscissas(paths[1])) >= screenX(3));
  assert.equal((svg.match(/class="graph-point"[^>]*fill="#fff"/g) || []).length, 2);
  assert.equal((svg.match(/class="graph-point"[^>]*fill="#b65c42"/g) || []).length, 2);
  assert.equal((svg.match(/class="reciprocal-projection"/g) || []).length, 4);
  assert.match(svg, />1\/4<\/text>/);
  assert.doesNotMatch(svg, /NaN|Infinity/);
});

test('invalid reciprocal domains are rejected and existing single-branch graphs remain valid', () => {
  for (const pieces of [[piece(-1, 1)], [piece(0, 1, true, true)], [piece(-1, 0, true, true)],
    [piece(null, -1, true, true)], [piece(2, 1)]]) {
    assert.equal(api.validateGraph(graph(pieces)), false);
    assert.equal(api.graph(graph(pieces)), '');
  }
  const legacy = graph([]);
  delete legacy.params.pieces;
  delete legacy.params.outputVariable;
  delete legacy.params.yTicks;
  legacy.params.interval = [-4, -1];
  legacy.params.negative = true;
  assert.equal(api.validateGraph(legacy), true);
  assert.equal(curves(api.graph(legacy)).length, 1);
  assert.ok(abscissas(curves(api.graph(legacy))[0]).every(x => x < 183));
});
