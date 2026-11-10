import test from 'node:test';
import assert from 'node:assert/strict';
import {loadSources} from '../build-public-knowledge-graph.mjs';
import {validateGraph} from '../../site/assets/knowledge-next/model.mjs';
import {makeRenderer} from '../lib/public-knowledge-html.mjs';

const {nodes, manifest} = await loadSources();
const table = after => ({
  id: 'placement-check', title: '条件与结论', after,
  columns: ['条件', '结论'], rows: [{head: '输入合法', cells: ['可以代入']}],
});

test('accepted table positions render once and their contents links resolve, including individual branches', () => {
  const cases = [
    ['function-parity', n => n.entries[0].id],
    ['skill-universal-substitution', n => n.operations[0].id],
    ['method-monotonicity-definition', n => n.steps[0].id],
    ['rule-monotonicity-abstract-method', n => n.branches[0].id],
    ['rule-monotonicity-abstract-method', () => 'branches'],
    ['method-monotonicity-definition', () => 'contract'],
    ['type-monotonicity-abstract-proof', () => 'features'],
    ['function-parity', () => ''],
  ];
  for (const [id, slot] of cases) {
    const copy = structuredClone(nodes), node = copy.find(n => n.id === id);
    node.tables = [table(slot(node))];
    const edges = validateGraph(copy, manifest);
    const renderer = makeRenderer(copy, edges, manifest, {chapters: []}, new Map(), []);
    const html = renderer.detail(node);
    assert.equal(html.match(/id="table-placement-check"/g)?.length, 1, `${id}: ${slot(node)}`);
    assert.match(html, /href="#table-placement-check"/);
    const body = renderer.detailBody(node, {}, {includeResources: false});
    const position = slot(node);
    if (position) assert.ok(body.indexOf('id="table-placement-check"') > body.indexOf(`id="${position}"`));
  }
});

test('table validation rejects invisible slots and malformed rows with actionable diagnostics', () => {
  const invalid = [
    [t => { t.after = 'contract'; }, /位置 contract 不存在/],
    [t => { t.after = 'features'; }, /位置 features 不存在/],
    [t => { t.after = 'branches'; }, /位置 branches 不存在/],
    [t => { t.after = 'missing'; }, /位置 missing 不存在/],
    [t => { delete t.columns; }, /缺少表头或行/],
    [t => { t.columns = ['条件', '']; }, /缺少表头或行/],
    [t => { t.rows = {}; }, /缺少表头或行/],
    [t => { t.rows = [null]; }, /行与表头列数不符/],
    [t => { t.rows[0].cells = []; }, /行与表头列数不符/],
    [t => { t.rows[0].cells = [{ref: 'missing-node'}]; }, /失效引用/],
  ];
  for (const [mutate, diagnostic] of invalid) {
    const copy = structuredClone(nodes), node = copy.find(n => n.id === 'function-parity');
    node.tables = [table('')];
    mutate(node.tables[0]);
    assert.throws(() => validateGraph(copy, manifest), diagnostic);
  }
  const copy = structuredClone(nodes);
  copy.find(n => n.id === 'section-3-2').tables = [table('')];
  assert.throws(() => validateGraph(copy, manifest), /目录节点不展示表格/);
});
