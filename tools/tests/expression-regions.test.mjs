import test from 'node:test';
import assert from 'node:assert/strict';
import {expressionRegionsHTML} from '../../site/assets/graph-walk/expression-regions.mjs';

const x = ['bound', 'function_argument'], n = value => ['number', String(value)];
const source = expression_ast => ({expression_ast, bound_symbols: {function_argument: 'x'}, regions: []});
const formulaText = html => /<div role="img"[^>]*>(.*)<\/div><\/figure>/.exec(html)[1]
  .replaceAll('<sup>', '^{').replaceAll('</sup>', '}').replace(/<[^>]*>/g, '');

test('a quadratic radicand reads naturally and keeps its original highlight target', () => {
  const value = source(['call', 'sqrt', ['+', ['+', ['*', ['neg', n(2)], ['^', x, n(2)]], x], n(6)]]);
  value.regions = [{source_ref: '/root/definitions/0', ast_path: [2], condition_id: 'c1', option_value: 'o1'}];
  const original = structuredClone(value);
  const plain = expressionRegionsHTML(value), selected = expressionRegionsHTML(value, ['o1']);
  assert.equal(formulaText(plain), '√−2x^{2}+x+6');
  assert.equal(formulaText(selected), formulaText(plain));
  assert.doesNotMatch(plain, /is-highlighted/);
  assert.equal((selected.match(/is-highlighted/g) || []).length, 1);
  assert.match(selected, /is-highlighted" data-source-ref="\/root\/definitions\/0"/);
  assert.deepEqual(value, original, 'layout must not rewrite source positions or the expression');
});

test('expression grouping preserves precedence and subtraction while removing redundant brackets', () => {
  for (const [ast, expected] of [
    [['neg', ['+', x, n(1)]], '−(x+1)'],
    [['*', n(2), ['+', x, n(1)]], '2·(x+1)'],
    [['-', x, ['-', x, n(1)]], 'x−(x−1)'],
    [['^', ['+', x, n(1)], n(2)], '(x+1)^{2}'],
    [['^', ['*', n(2), x], n(2)], '(2x)^{2}'],
    [['+', x, ['*', ['neg', n(2)], x]], 'x+(−2x)'],
    [['*', x, ['neg', n(2)]], 'x·(−2)'],
    [['+', x, ['-', x, n(1)]], 'x+x−1'],
    [['*', n(2), n(3)], '2·3'],
  ]) assert.equal(formulaText(expressionRegionsHTML(source(ast))), expected);
});

test('fraction bars delimit additive inputs without canceling or adding parentheses', () => {
  const html = expressionRegionsHTML(source(['/', ['+', x, n(1)], ['-', x, n(1)]]));
  assert.match(html, /gw-expr-fraction/);
  assert.equal(formulaText(html), 'x+1x−1');
  assert.doesNotMatch(html, /[()]/);
});
