import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';
import {choiceFigures} from '../../site/assets/practice/figure-choices.mjs';

test('B09-v2 moves the existing graph in two steps and selects source-bound pictures', async () => {
  const bundle = JSON.parse(await fs.readFile(new URL('../../site/data/graph-walk/function-representations-b09-v2.json',import.meta.url)));
  const route = Object.values(bundle.routes)[0];
  assert.equal(route.completion.answer.correct_option_id,'option-c');
  assert.deepEqual(route.steps.map(s => s.title), ['向左平移 2 个单位','向下平移 3 个单位','总结平移后的关键点','对照原图，选择图像']);
  const [left,down,summary,options] = route.steps;
  assert.deepEqual(down.graph,left.completion_graph);
  assert.deepEqual(left.completion_graph.params.reference,left.graph.params.segments);
  assert.deepEqual(down.completion_graph.params.reference,down.graph.params.segments);
  assert.equal(down.interaction.options.length,3); // includes a shift incorrectly placed inside abs
  assert.deepEqual(summary.completion_graph.params.points.map(p => p.label),['(-3, -1)','(-2, 0)','(-1, -1)']);
  assert.deepEqual(choiceFigures(bundle.problem.figures,options,{targetRef:'/root/goals/0'}).map(p => p.label),['A','B','C','D']);
  const ctx = vm.createContext({window:{}});
  vm.runInContext(await fs.readFile(new URL('../../site/assets/practice/components.js',import.meta.url),'utf8'),ctx);
  for (const step of route.steps) for (const graph of [step.graph,step.completion_graph].filter(Boolean)) {
    assert.ok(ctx.window.PracticeComponents.validateGraph(graph));
    const svg = ctx.window.PracticeComponents.graph({...graph,uid:step.id});
    assert.equal((svg.match(/class="piecewise-segment"/g)||[]).length,3);
    assert.doesNotMatch(svg,/NaN|Infinity|<script/);
  }
  assert.doesNotMatch(JSON.stringify(bundle),/_input/);
});
