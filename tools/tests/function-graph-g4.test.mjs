import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {choiceFigures} from '../../site/assets/practice/figure-choices.mjs';
import {projectFigures} from '../../site/assets/practice/question-figures.mjs';

test('B09-v3 transports points using the given graph without inventing a formula or curve', async () => {
  const bundle = JSON.parse(await fs.readFile(new URL('../../site/data/graph-walk/function-representations-b09-v3.json', import.meta.url)));
  const route = Object.values(bundle.routes)[0];
  assert.equal(route.completion.answer.correct_option_id, 'option-c');
  assert.deepEqual(route.steps.map(s => s.title), ['先关于 y 轴对称', '再向右平移 2 个单位', '总结点的移动与图像方向', '横轴交点移到哪里', '对照原图，选择图像']);
  for (const step of route.steps) {
    assert.equal(step.show_source_graph, true);
    assert.equal(step.graph, undefined);
    assert.equal(step.completion_graph, undefined);
    assert.equal(step.stem_board.items[1].math, null);
  }
  const source = projectFigures(bundle.problem.figures, {targetRef: '/root/goals/0'}).rows.filter(r => r.role === 'statement');
  assert.equal(source.length, 1);
  assert.match(source[0].image_url, /given-graph\.png$/);
  assert.deepEqual(choiceFigures(bundle.problem.figures, route.steps.at(-1), {targetRef: '/root/goals/0'}).map(r => r.label), ['A', 'B', 'C', 'D']);
  assert.doesNotMatch(JSON.stringify(bundle), /_input/);
});
