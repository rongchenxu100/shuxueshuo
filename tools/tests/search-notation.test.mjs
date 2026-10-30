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

test('photographed function-range goals render without assuming a scalar symbol', () => {
  const candidate = JSON.parse(fs.readFileSync(new URL('server/tests/solver/fixtures/function-range/q03-candidate.json', base), 'utf8'));
  const text = context.meaningBlocks(candidate.root, '', []).join('');
  assert.match(text, /求 \$f\$ 的值域/);
  assert.match(text, /题设输入范围 \$\[0,3\]\$/);
  assert.doesNotMatch(text, /undefined|参数/);
  const unrestricted = context.meaningBlocks({goals: [{kind: 'find_range', object: 'g'}]}, '', []).join('');
  assert.match(unrestricted, /求 \$g\$ 的值域/);
  const parameter = context.meaningBlocks({goals: [{kind: 'find_range', symbol: 'a'}]}, '', []).join('');
  assert.match(parameter, /求 \$a\$ 的取值范围/);
});

test('abstract-domain meaning preserves the given call and requested outer expression', () => {
  const goal = {kind: 'find_abstract_domain', known_call: 'f(t)', known_domain: '[-3,2]',
    strength: 'exact', target_call: 'f(2*x-1)'};
  const text = context.meaningBlocks({goals: [goal]}, '', []).join('');
  assert.match(text, /已知 \$f\(t\)\$ 的定义域为 \$\[-3,2\]\$/);
  assert.match(text, /求 \$f\(2x-1\)\$ 的定义域/);
  assert.doesNotMatch(text, /\[-1|undefined/);
  const limited = context.meaningBlocks({goals: [{...goal, input_domain: '(0,2)'}]}, '', []).join('');
  assert.match(limited, /题设另限外层自变量范围 \$\(0,2\)\$/);
  const meaningful = context.meaningBlocks({goals: [{...goal, strength: 'meaningful_only'}]}, '', []).join('');
  assert.match(meaningful, /\$f\(t\)\$ 在 \$\[-3,2\]\$ 上有意义/);
  assert.doesNotMatch(meaningful, /定义域为/);
});

test('abstract-domain parameter meaning preserves guaranteed input scope and the shared variable', () => {
  const goal = {kind: 'find_abstract_domain_parameter', known_call: 'f(t)', known_domain: '[0,1]',
    strength: 'meaningful_only', target_call: 'f(x+a)+f(x-a)', parameter: 'a', variable: 'x', quantifier: 'exists'};
  const text = context.meaningBlocks({goals: [goal]}, '', []).join('');
  assert.match(text, /\$f\(t\)\$ 在 \$\[0,1\]\$ 上有意义/);
  assert.match(text, /在题设给定输入范围内/);
  assert.match(text, /\$f\(x\+a\)\+f\(x-a\)\$ 的各调用有共同合法 \$x\$/);
  assert.match(text, /参数 \$a\$ 的取值范围/);
  assert.doesNotMatch(text, /定义域为|D_f|undefined|frac|1\/2/);
  const exact = context.meaningBlocks({goals: [{...goal, strength: 'exact'}]}, '', []).join('');
  assert.match(exact, /定义域为/);
});

test('same-scope abstract domain and range goals retain the known range without inventing subquestions', () => {
  const known = {known_call: 'f(x)', known_domain: '[-1,2]', known_range: '[3,5]',
    strength: 'exact', target_call: 'f(2*x-1)'};
  const root = {goals: [{kind: 'find_abstract_domain', ...known}, {kind: 'find_abstract_range', ...known}]};
  const text = context.meaningBlocks(root, '', []).join('');
  assert.match(text, /已知 \$f\(x\)\$ 的定义域为 \$\[-1,2\]\$/);
  assert.match(text, /值域为 \$\[3,5\]\$/);
  assert.match(text, /求 \$f\(2x-1\)\$ 的定义域/);
  assert.match(text, /求 \$f\(2x-1\)\$ 的值域/);
  assert.doesNotMatch(text, /第[12]问|undefined/);
  assert.equal((text.match(/值域为/g) || []).length, 1, 'shared given range is stated once');
});
const render = expression => katex.renderToString(tex(expression), {throwOnError: true, output: 'mathml', strict: 'ignore'});

test('domain goal renders the input question and preserves an explicitly given range', () => {
  const plain = context.meaningBlocks({goals: [{kind: 'find_domain', object: 'f'}]}, '', []);
  assert.match(plain.join(''), /求 \$f\$ 的定义域/);
  const limited = context.meaningBlocks({goals: [{kind: 'find_domain', object: 'g', input_domain: '[0,1]'}]}, '', []);
  assert.match(limited.join(''), /求 \$g\$ 的定义域（题设范围 \$\[0,1\]\$）/);
});

test('comparison meaning preserves selection polarity without flattening option scopes or revealing answers', () => {
  for (const [polarity, wording] of [['equal', '同一'], ['different', '不同']]) {
    const blocks = context.meaningBlocks({goals: [{kind: 'compare_functions', mode: 'groups',
      select_relation: polarity, selection_mode: 'multiple', options: [{label: 'A'}, {label: 'B'}]}]}, '', []).join('');
    assert.ok(blocks.includes(`再选出表示${wording}函数的全部选项`));
    assert.doesNotMatch(blocks, /undefined|求 <|CD/);
  }
  const pair = context.meaningBlocks({goals: [{kind: 'compare_functions', mode: 'pair'}]}, '', []).join('');
  assert.match(pair, /判断题给的两个函数是否为同一函数/);
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

test('function evaluation names constant judgment and finite sum as two same-scope targets', () => {
  const root = {definitions: ['f(x)=(x+2)/(x+1)'], goals: [
    {kind: 'check_constant', expression: 'f(x)+f(1/x)'},
    {kind: 'finite_sum', terms: [{expression: 'f(n)', index: 'n', lower: 1, upper: 101},
      {expression: 'f(1/n)', index: 'n', lower: 2, upper: 101}]},
  ]};
  const html = context.meaningBlocks(root, '', []).join('');
  assert.match(html, /判断.*是否为定值/);
  assert.match(html, /\\sum_\{n=1\}\^\{101\}/);
  assert.match(html, /\\sum_\{n=2\}\^\{101\}/);
  assert.doesNotMatch(html, /undefined|第.*问|求.*求/);
  const formulas = [...html.matchAll(/\$([^$]+)\$/g)].map(match => match[1]);
  for (const formula of formulas) assert.doesNotThrow(() => katex.renderToString(formula, {throwOnError: true}));
});
