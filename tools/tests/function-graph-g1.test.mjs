import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';
import {choiceFigures} from '../../site/assets/practice/figure-choices.mjs';
import {routeAnswerSummary} from '../../site/assets/graph-walk/stream-math-dom.mjs';

const ctx = vm.createContext({window: {}});
vm.runInContext(await fs.readFile(new URL('../../site/assets/practice/components.js', import.meta.url), 'utf8'), ctx);
const api = ctx.window.PracticeComponents;

test('a completed graph route shows the verified original label', () => {
  assert.deepEqual(routeAnswerSummary({kind:'select_function_graph', status:'complete', correct_labels:['D']}),
    {label:'原题选项：D', formula:''});
  assert.equal(routeAnswerSummary({kind:'select_function_graph', status:'unknown', correct_labels:['A']}), null);
});
const picture = extra => ({kind: 'absolute_affine', uid: 'g1', params: {
  a: -2, b: 3, c: -1, showBase: true, bounds: [-1, 4, -2, 5], interval: [0, 2], interval_closed: [true, false],
  points: [{x: 0}, {x: 2, open: true}], xTicks: [[0, '0'], [1.5, '3/2']],
  title: '图像', description: '点对应', variable: 'x', ...extra,
}});

test('absolute affine graph uses two exact segments and preserves endpoint inclusion', () => {
  const svg = api.graph(picture());
  assert.match(svg, /class="absolute-base".*stroke-dasharray/);
  const path = svg.match(/class="absolute-affine" d="([^"]+)"/)[1];
  assert.equal((path.match(/L/g)||[]).length, 2);
  assert.match(svg, /cx="102".*fill="#b65c42"/);
  assert.match(svg, /cx="210".*fill="#fff"/);
  assert.doesNotMatch(svg, /NaN|Infinity/);
  for (const extra of [{a: 0}, {b: Infinity}, {showBase: 'yes'}]) assert.equal(api.graph(picture(extra)), '');
});

test('vertical translation starts its arrow and dashed curve at the previous horizontal result', () => {
  const reference = {a:1, b:-1, c:0, interval:[null,null], interval_closed:[false,false]};
  const svg = api.graph(picture({a:1,b:-1,c:1,reference}));
  const arrow = svg.match(/class="absolute-map" d="M([\d.]+) ([\d.]+)L([\d.]+) ([\d.]+)"/);
  assert.ok(arrow);
  assert.equal(arrow[1], arrow[3]); // vertical only, not another diagonal move from (0,0)
  assert.notEqual(arrow[2], arrow[4]);
  assert.notEqual(svg.match(/class="absolute-base" d="([^"]+)"/)[1],
    api.graph(picture({a:1,b:-1,c:1})).match(/class="absolute-base" d="([^"]+)"/)[1]);
  for (const extra of [{a:0}, {b:Infinity}, {interval_closed:[true,false]}]) {
    assert.equal(api.graph(picture({reference:{...reference,...extra}})), '');
  }
});

test('picture scoring binds every option ID and label, never a positional letter alone', async () => {
  const manifest = JSON.parse(await fs.readFile(new URL('../../site/assets/question-figures/fr-t2-b09/display.json', import.meta.url)));
  const options = manifest.figures.filter(r => r.role === 'option').map(r => ({value: r.option_id, label: r.label}));
  const decision = {figure_choices: options.map(o => o.value), interaction: {type: 'choice', options}};
  const context = {targetRef: '/root/goals/0'};
  assert.deepEqual(choiceFigures(manifest, decision, context).map(r => r.label), ['A','B','C','D']);
  const changed = structuredClone(manifest); changed.figures.find(r => r.role === 'option').label = 'E';
  assert.throws(() => choiceFigures(changed, decision, context));
  assert.throws(() => choiceFigures(manifest, decision, {targetRef: '/root/goals/1'}));
  assert.throws(() => choiceFigures({...manifest, figures: manifest.figures.slice(0,-1)}, decision, context));
});

test('published B09 decisions resolve to the authored original pictures', async () => {
  const bundle = JSON.parse(await fs.readFile(new URL('../../site/data/graph-walk/function-representations-b09.json', import.meta.url)));
  const step = Object.values(bundle.routes).flatMap(r => r.steps).find(s => s.figure_choices);
  assert.ok(step);
  assert.deepEqual(choiceFigures(bundle.problem.figures, step, {targetRef:'/root/goals/0'}).map(row => row.label), ['A','B','C','D']);
});
