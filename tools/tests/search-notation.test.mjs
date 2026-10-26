import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createRequire} from 'node:module';
import test from 'node:test';
import vm from 'node:vm';

const base = new URL('../../', import.meta.url);
const require = createRequire(import.meta.url);
const katex = require('../../site/assets/practice/vendor/katex-0.18.9/katex.min.js');
const context = vm.createContext({
  URLSearchParams,
  location: {search: ''},
  performance: {now: () => 0},
  document: {addEventListener() {}},
  window: {},
});
vm.runInContext(fs.readFileSync(new URL('site/lab/search/problem.js', base), 'utf8'), context);
const tex = expression => context.tex(expression);
const render = expression => katex.renderToString(tex(expression), {throwOnError: true, output: 'mathml', strict: 'ignore'});

test('domain goal renders the input question and preserves an explicitly given range', () => {
  const plain = context.meaningBlocks({goals: [{kind: 'find_domain', object: 'f'}]}, '', []);
  assert.match(plain.join(''), /求 \$f\$ 的定义域/);
  const limited = context.meaningBlocks({goals: [{kind: 'find_domain', object: 'g', input_domain: '[0,1]'}]}, '', []);
  assert.match(limited.join(''), /求 \$g\$ 的定义域（题设范围 \$\[0,1\]\$）/);
});

for (const [expression, expected] of [
  ['2sqrt(4)=a', '2\\sqrt{4}=a'],
  ['2 sqrt(4)=a', '2\\sqrt{4}=a'],
  ['0.5\t sqrt (4)=a', '0.5\\sqrt{4}=a'],
  ['2abs(x-1)=a', '2\\left|x-1\\right|=a'],
  ['2 abs(x-1)=a', '2\\left|x-1\\right|=a'],
  ['2sqrt(abs(x-1))=a', '2\\sqrt{\\left|x-1\\right|}=a'],
  ['sqrt(2 abs(x))=a', '\\sqrt{2\\left|x\\right|}=a'],
  ['x^2sqrt(4)=a', 'x^{2}\\sqrt{4}=a'],
]) {
  test(`renders the function after an implicit coefficient: ${expression}`, () => {
    assert.equal(tex(expression), expected);
    assert.match(render(expression), expression.includes('sqrt') ? /<msqrt>/ : /<mo[^>]*>∣<\/mo>/);
  });
}

test('implicit coefficients have the same display as explicit multiplication', () => {
  for (const coefficient of ['2', '0.5']) {
    for (const operand of ['abs(x)', 'sqrt(4)', 'sum(S)', 'mod(n,3)', 'min(x,2)', 'tan(30°)', 'length(A,B)', 'x_12', 'α', '(x+1)', '∠ABC', '√4']) {
      const explicit = `${coefficient}*${operand}`;
      for (const separator of ['', ' ', '\t\n']) {
        const implicit = `${coefficient}${separator}${operand}`;
        assert.equal(tex(implicit), tex(explicit), implicit);
        assert.doesNotThrow(() => render(implicit), implicit);
      }
    }
  }
});

test('digits inside complete identifiers do not become multiplication', () => {
  for (const [expression, expected] of [
    ['x_12^2', 'x_{12}^{2}'], ['a1b', 'a1b'], ['f2(x)', 'f2(x)'],
    ['a2sqrt(x)', 'a2sqrt(x)'], ['α2β', 'α2β'], ['xy', 'xy'],
  ]) assert.equal(tex(expression), expected, expression);
});

test('normalization preserves exponent precedence and nested function arguments', () => {
  for (const [expression, expected] of [
    ['x **\t12', 'x^{12}'], ['x^-2^2', 'x^{-2^{2}}'], ['x^(-2)^2', 'x^{(-2)^{2}}'],
    ['x^(2-a)', 'x^{2-a}'], ['x_12 ²', 'x_{12}^{2}'],
    ['abs (x − 1) ≤ 2', '\\left|x-1\\right|\\le 2'],
    ['mod(n,3)^2', '(n\\bmod 3)^{2}'],
  ]) {
    assert.equal(tex(expression), expected, expression);
    assert.doesNotThrow(() => render(expression), expression);
  }
});

test('set sums remain a single operand when multiplied or raised to a power', () => {
  assert.equal(tex('2sum(S)'), '2\\left(S\\text{ 的元素之和}\\right)');
  assert.equal(tex('sum(S)^2'), '\\left(S\\text{ 的元素之和}\\right)^{2}');
  assert.match(render('sum(S)^2'), /<msup><mrow>.*<mtext>.*元素之和.*<\/mtext>.*<\/mrow><mn>2<\/mn><\/msup>/);
  assert.doesNotThrow(() => render('mod(sum({1,2,3}),4)=2'));
});

test('multiplication after a fraction cannot merge into the denominator', () => {
  assert.equal(tex('a/2*x=b'), '\\frac{a}{2}x=b');
  assert.equal(tex('a/(2*x)=b'), '\\frac{a}{2x}=b');
  assert.match(render('a/2*x=b'), /<mfrac>/);
  assert.match(render('a/(2*x)=b'), /<mfrac>/);
});

test('a number over a number displays as a fraction', () => {
  assert.equal(tex('∀x∈(0,1/2]: x^2+a*x+1>=0'), '\\forall x\\in (0,\\frac{1}{2}]\\colon x^{2}+ax+1\\ge 0');
  assert.match(render('x∈(0,1/2]'), /<mfrac>/);
  assert.equal(tex('2/3sqrt(4)=a'), '\\frac{2}{3}\\sqrt{4}=a');
  assert.equal(tex('2^1/2'), '\\frac{2^{1}}{2}');
});

test('algebraic division displays as a vertical fraction', () => {
  assert.equal(tex('(x^2-1)/(x-1)'), '\\frac{x^{2}-1}{x-1}');
  assert.equal(tex('f(x)=(x+4)^0*(x^2-1)/(x-1)'), 'f(x)=(x+4)^{0}\\frac{x^{2}-1}{x-1}');
  assert.match(render('(x^2-1)/(x-1)'), /<mfrac>/);
  assert.match(render('f(x)=(x+4)^0*(x^2-1)/(x-1)'), /<mfrac>/);
});

test('chained division keeps every slash, so a/2/3 never reads as a over two thirds', () => {
  for (const expr of ['a/2/3', '1/2/3', 'sqrt(4)/2/3', 'sqrt(4)/-2/3', 'a/+2/3', 'a/--2/3', 'a/+-2/3', 'a/-+-2/3']) {
    assert.doesNotMatch(tex(expr), /\\frac/, expr);
  }
  assert.equal(tex('a/2/3'), 'a/2/3');
  assert.equal(tex('sqrt(4)/2/3'), '\\sqrt{4}/2/3');
  assert.equal(tex('sqrt(4)/-2/3'), '\\sqrt{4}/-2/3');
  assert.equal(tex('(0,-1/2]'), '(0,-\\frac{1}{2}]');
});

test('the stage-one expression catalog renders with the bundled KaTeX', () => {
  const catalog = JSON.parse(fs.readFileSync(new URL('internal/llm-prompts/problem-math-notation-expressions.json', base), 'utf8'));
  const overlay = JSON.parse(fs.readFileSync(new URL('internal/llm-prompts/graph-stage-one-expressions.json', base), 'utf8'));
  const entries = catalog.expressions.map(entry => overlay.overrides[entry.id] || entry).concat(overlay.additions || []);
  for (const expression of entries.flatMap(entry => entry.examples || [])) {
    if (!/[\u4e00-\u9fff]/.test(expression)) assert.doesNotThrow(() => render(expression), expression);
  }
});
