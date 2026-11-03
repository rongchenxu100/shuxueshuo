import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';
import {routeAnswerSummary} from '../../site/assets/graph-walk/stream-math-dom.mjs';

const ctx = vm.createContext({window:{}});
vm.runInContext(await fs.readFile(new URL('../../site/assets/practice/components.js', import.meta.url), 'utf8'), ctx);
const api = ctx.window.PracticeComponents;
const picture = extra => ({kind:'piecewise_curve', uid:'g2', params:{
  bounds:[-3,5,-1,8], interval:[null,null], interval_closed:[false,false],
  segments:[
    {coefficients:[1,-2,-3],interval:[null,-1],interval_closed:[false,false]},
    {coefficients:[-1,2,3],interval:[-1,3],interval_closed:[true,false]},
    {coefficients:[1,-2,-3],interval:[3,null],interval_closed:[true,false]},
  ], level:3, xTicks:[[0,'0'],[2,'2']], points:[{x:0,open:false},{x:2,open:true}],
  highlights:[{from:0,to:2,left_closed:true,right_closed:false}],
  variable:'x', title:'图像', description:'分段曲线与水平线', ...extra,
}});

test('piecewise renderer separates curves and keeps shared boundaries and strict endpoints', () => {
  const svg = api.graph(picture());
  assert.equal((svg.match(/class="piecewise-segment"/g)||[]).length,3);
  assert.match(svg,/piecewise-level/);
  assert.match(svg,/piecewise-highlight/);
  // Both joins are included by one of their adjacent pieces, without a spurious open hole.
  const joins = svg.match(/<circle class="piecewise-endpoint"[^>]+>/g);
  assert.equal(joins.length,2);
  assert.ok(joins.every(dot => dot.includes('fill="#07847d"')));
  const points = svg.match(/<circle class="graph-point"[^>]+>/g);
  assert.match(points[0],/fill="#b65c42"/);
  assert.match(points[1],/fill="#fff"/);
  assert.doesNotMatch(svg,/NaN|Infinity|<script/);
});

test('drawing rejects malformed intervals and numbers before rendering', () => {
  const valid = picture().params.segments[0];
  for (const bad of [{coefficients:[NaN,0,1]}, {interval:[2,1]}, {interval_closed:[true,false]}, {coefficients:['x',1,1]}]) {
    assert.equal(api.graph(picture({segments:[{...valid,...bad}]})), '');
  }
  assert.equal(api.graph(picture({segments:[]})), '');
  assert.equal(api.graph(picture({level:Infinity})), '');
  assert.equal(api.graph(picture({highlights:[{from:0,to:0,left_closed:true,right_closed:true}]})), '');
});

test('published two-goal course has staged drawing and a complete curve/number-line result', async () => {
  const b = JSON.parse(await fs.readFile(new URL('../../site/data/graph-walk/function-representations-b09-v1.json', import.meta.url)));
  const route = Object.values(b.routes)[0];
  assert.deepEqual(route.methods,['method-absolute-piecewise-graph','method-piecewise-graph-inequality']);
  const steps = route.steps;
  const segments = steps.filter(s => /^画第 [123] 段$/.test(s.title));
  assert.equal(segments.length,3);
  for (const step of steps) {
    for (const graph of [step.graph,step.completion_graph,...(step.completion_graphs||[])].filter(Boolean)) {
      assert.equal(api.validateGraph(graph),true);
      assert.match(api.graph({...graph,uid:step.id}),/<svg/);
    }
  }
  const end = steps.find(s => s.title === '判断端点，写出解集');
  assert.deepEqual(end.completion_graphs.map(g => g.kind),['piecewise_curve','number_line']);
  assert.equal(end.completion_graphs[1].params.pieces.length,3);
  assert.deepEqual(routeAnswerSummary({kind:'solve_graph_inequality',status:'complete',latex:'[0,2]'}),
    {label:'不等式的解集：',formula:'[0,2]'});
});
