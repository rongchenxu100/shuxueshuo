import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';
import {expressionRegionsHTML} from '../../site/assets/graph-walk/expression-regions.mjs';
import {domainNumberLineGraph, endpointChecksHTML} from '../../site/assets/graph-walk/domain-visuals.mjs';

const argument = ['bound', 'function_argument'];
const q01 = {
  expression: '(x+4)^0*(x^2-1)/(x-1)', bound_symbols: {function_argument: 'x'},
  expression_ast: ['/', ['*', ['^', ['+', argument, ['number', '4']], ['number', '0']],
    ['-', ['^', argument, ['number', '2']], ['number', '1']]], ['-', argument, ['number', '1']]],
  regions: [
    {source_ref: '/root/definitions/0', ast_path: [1, 1, 1], condition_id: 'zero-power', option_value: 'o1', basis_refs: ['integer-power#zero-exponent']},
    {source_ref: '/root/definitions/0', ast_path: [2], condition_id: 'denominator', option_value: 'o2', basis_refs: ['rational-expression#meaning']},
  ],
};

test('Q01 highlights the original zero-power base and denominator without canceling its numerator', () => {
  const plain = expressionRegionsHTML(q01);
  assert.doesNotMatch(plain, /is-highlighted/);
  assert.equal((plain.match(/<sup>/g) || []).length, 2, 'zero and positive powers both remain visible');
  assert.match(plain, /<sup>.*>0<.*<sup>.*>2</);
  assert.match(plain, /gw-expr-fraction/);
  const zero = expressionRegionsHTML(q01, ['o1']);
  assert.equal((zero.match(/is-highlighted/g) || []).length, 1);
  assert.ok(zero.indexOf('is-highlighted') < zero.indexOf('<sup>'));
  const denominator = expressionRegionsHTML(q01, ['o2']);
  assert.equal((denominator.match(/is-highlighted/g) || []).length, 1);
  assert.ok(denominator.indexOf('is-highlighted') > denominator.lastIndexOf('</sup>'));
  assert.equal((expressionRegionsHTML(q01, ['o1', 'o2']).match(/is-highlighted/g) || []).length, 2);
  assert.equal(q01.expression_ast[1][1][2][1], '0', 'display never rewrites a zero power to 1');
});

for (const base of [
  ['neg', argument], ['number', '-3'], ['^', argument, ['number', '2']], ['/', ['number', '1'], argument],
]) test(`a power visibly groups its whole base: ${JSON.stringify(base)}`, () => {
  const html = expressionRegionsHTML({...q01, regions: [], expression_ast: ['^', base, ['number', '2']]});
  assert.match(html, /<span>\(<span class="gw-expr-node"/);
  assert.match(html, /\)<sup>/);
});

test('Q01 typed number lines and endpoint reasons keep both exclusions visible', async () => {
  const line = {label: 'D_f=\\mathbb{R}\\setminus\\{-4,1\\}', variable: 'x', bounds: [-5.25, 2.25],
    intervals: [{left: null, right: -4, left_closed: false, right_closed: false},
      {left: -4, right: 1, left_closed: false, right_closed: false},
      {left: 1, right: null, left_closed: false, right_closed: false}], points: [],
    ticks: [{at: -4, label: '-4'}, {at: 1, label: '1'}]};
  const graph = domainNumberLineGraph(line);
  const scope = vm.createContext({window: {}});
  vm.runInContext(await fs.readFile(new URL('../../site/assets/practice/components.js', import.meta.url), 'utf8'), scope);
  const html = scope.window.PracticeComponents.numberLine({...graph.params, uid: 'q01'});
  assert.equal((html.match(/class="number-line-end"/g) || []).length, 4);
  assert.doesNotMatch(html, /is-closed/);
  assert.match(html, />-4<.*>1</s);
  const checks = endpointChecksHTML([
    {at: -4, label: 'x=-4', included: false, holds: false, passed: true,
      reason: '零次幂的底数为 0，出现 $0^0$。', sources: [{kind: 'zero_power_base_nonzero', ast_path: [1, 1, 1]}]},
    {at: 1, label: 'x=1', included: false, holds: false, passed: true,
      reason: '原分母为 0，约分不能取消这个限制。', sources: [{kind: 'denominator_nonzero', ast_path: [2]}]},
  ]);
  assert.equal((checks.match(/不能取到/g) || []).length, 2);
  assert.match(checks, /零次幂的底数为 0.*原分母为 0/s);
});
