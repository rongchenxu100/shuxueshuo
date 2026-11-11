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

test('given parity and declared degree stay visible as conditions of the parameter goal', () => {
  const text = context.meaningBlocks({definitions: ['f(x)=m*x^2'],
    facts: ['parity(f,even)', 'degree(f)=2', 'm>0'],
    goals: [{kind: 'find_value', expression: 'm'}]}, '', []).join('');
  assert.match(text, /是偶函数/);
  assert.match(text, /是二次函数/);
  assert.match(text, /求 \$m\$ 的值/);
  assert.doesNotMatch(text, /parity|degree|m=2/);
  for (const [degree, label] of [[3, '三次函数'], [4, '四次函数']]) {
    const meaning = context.meaningBlocks({definitions: [`f(x)=m*x^${degree}`],
      facts: ['parity(f,even)', `degree(f)=${degree}`],
      goals: [{kind: 'find_value', expression: 'm'}]}, '', []).join('');
    assert.ok(meaning.includes(label));
    assert.doesNotMatch(meaning, /degree/);
  }
});

test('photographed formula questions show the given relation and requested formula without solving it', () => {
  const goal = {kind: 'find_function_formula', function: 'f', variable: 'x',
    relation: 'f(sqrt(x)+1)=x+2*sqrt(x)'};
  const text = context.meaningBlocks({goals: [goal]}, '', []).join('');
  assert.ok(text.includes('已知 $f(\\sqrt{x}+1)=x+2\\sqrt{x}$；求 $f(x)$ 的解析式'));
  assert.doesNotMatch(text, /undefined|定义域|所求范围|\\in|x\^\{2\}-1/);
  for (const [, formula] of text.matchAll(/\$([^$]+)\$/g)) {
    assert.doesNotThrow(() => katex.renderToString(formula, {throwOnError: true}));
  }
});

test('formula meaning preserves stated domains and both variables in a functional relation', () => {
  const goal = {kind: 'find_function_formula', function: 'f', variable: 'x',
    relation: 'f(x+y)=2*f(y)+x^2+2*x*y-y^2+3*x-3*y',
    relation_variables: ['x', 'y'], relation_domain: 'ℝ', declared_domain: 'ℝ', requested_domain: 'ℝ'};
  const text = context.meaningBlocks({goals: [goal]}, '', []).join('');
  assert.ok(text.includes('$f$ 的定义域为 $\\mathbb{R}$'));
  assert.ok(text.includes('对任意 $x,y\\in \\mathbb{R}$'));
  assert.ok(text.includes('求 $f(x)$ 的解析式（所求范围 $\\mathbb{R}$）'));
  assert.doesNotMatch(text, /undefined/);
});

test('relation value and inequality targets keep function type and additional conditions', () => {
  const given = {function: 'f', variable: 'x', function_type: 'quadratic',
    relation: 'f(x-1)=f(x)+3*x-5', additional_relations: ['f(0)=0']};
  const text = context.meaningBlocks({goals: [
    {...given, kind: 'find_value', expression: 'f(1)'},
    {...given, kind: 'find_range', expression: 'f(x)>0', symbol: 'x'},
  ]}, '', []).join('');
  assert.match(text, /\$f\$ 是二次函数/);
  assert.match(text, /\$f\(x-1\)=f\(x\)\+3x-5\$/);
  assert.match(text, /\$f\(0\)=0\$/);
  assert.match(text, /求 \$f\(1\)\$ 的值/);
  assert.match(text, /求 满足 \$f\(x\)&gt;0\$ 的 \$x\$ 的取值范围/);
  assert.equal((text.match(/f\(0\)=0/g) || []).length, 1, 'shared given conditions appear once');
  assert.doesNotMatch(text, /undefined/);
});

test('translation-range meaning retains both functions, the known image and the target interval', () => {
  const candidate = JSON.parse(fs.readFileSync(new URL('server/tests/solver/fixtures/function-range/q18-candidate.json', base), 'utf8'));
  const text = context.meaningBlocks(candidate.root, '', []).join('');
  assert.match(text, /已知 \$f\(x\)=x\+g\(x\)\$/);
  assert.match(text, /\$g\$ 定义在 .* 上、以 \$1\$ 为周期/);
  assert.match(text, /基础区间 \$\[3,4\]\$ 上的值域为 \$\[-2,5\]\$/);
  assert.match(text, /求 \$f\(x\)\$ 在 \$\[-10,10\]\$ 上的值域/);
  assert.doesNotMatch(text, /undefined|-15|11|\$f\$ 定义在/);
});

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

for (const [folder, question, subject, interval, direction] of [
  ['initial', 'a05', 'f(x)', '[1,2]', '严格递增'],
  ['initial', 'a09', 'f(x)', '(-∞,4]', '严格递减'],
  ['second', 'a11', 'a*x^2-2*x+3', '[2,∞)', '严格递减'],
]) {
  test(`monotonicity parameter meaning retains the photographed condition: ${question}`, () => {
    const candidate = JSON.parse(fs.readFileSync(new URL(
      `server/tests/search/fixtures/function-monotonicity-topic/${folder}/${question}/workflow/candidate.json`, base), 'utf8'));
    const text = context.meaningBlocks(candidate.root, '', []).join('');
    assert.ok(text.includes(`求使 $${tex(subject)}$ 在 $${tex(interval)}$ 上${direction}的`), text);
    assert.ok(text.includes(`$${candidate.root.goals[0].symbol}$ 的取值范围`));
    assert.doesNotMatch(text, /undefined|m\\le 2|a\\ge 5|a\\le 0/);
    for (const [, formula] of text.matchAll(/\$([^$]+)\$/g)) {
      assert.doesNotThrow(() => katex.renderToString(formula, {throwOnError: true}));
    }
  });
}

test('difference quotient meaning keeps the original condition instead of declaring its conclusion given', () => {
  const candidate = JSON.parse(fs.readFileSync(new URL(
    'server/tests/search/fixtures/function-monotonicity-topic/second/a13/workflow/candidate.json', base), 'utf8'));
  const text = context.meaningBlocks(candidate.root, '', []).join('');
  assert.ok(text.includes(`$${tex(candidate.root.facts[0]).replaceAll('<', '&lt;')}$`));
  assert.match(text, /求 \$a\$ 的取值范围/);
  assert.doesNotMatch(text, /严格递减|undefined/);
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

for (const name of ['c01', 'c02']) {
  test(`abstract monotonicity ${name} meaning retains all source conditions without inventing direction`, () => {
    const record = JSON.parse(fs.readFileSync(new URL(`internal/senior-high/authored-courses/function-monotonicity-t5-20261109/${name}.json`, base), 'utf8'));
    const g = record.candidate.root.goals[0];
    const text = context.meaningBlocks(record.candidate.root, '', []).join('');
    assert.ok(text.includes(`$${tex(g.declared_domain)}$`));
    assert.ok(text.includes(`$${tex(g.relation)}$`));
    assert.ok(text.includes(tex(g.sign_condition.statement).replace(/>/g, '&gt;')));
    assert.ok(text.includes(`判断 $f$ 在 $${tex(g.input_domain)}$ 上的单调性`));
    assert.doesNotMatch(text, /undefined|严格递增|严格递减/);
    for (const [, formula] of text.matchAll(/\$([^$]+)\$/g)) {
      assert.doesNotThrow(() => katex.renderToString(formula.replace(/&gt;/g, '>').replace(/&lt;/g, '<'), {throwOnError: true}));
    }
  });
}

test('abstract proof meaning preserves the requested direction and chained sign condition', () => {
  const g = {kind: 'prove_monotonicity_on_interval', direction: 'decreasing', function: 'g', variable: 't',
    declared_domain: 'ℝ', input_domain: '[1,2]', relation_variables: ['u', 'v'], relation_domain: 'ℝ',
    relation: 'g(u+v)=g(u)*g(v)', sign_condition: {variable: 't', domain: '(0,+∞)', statement: '0<g(t)<1'}};
  const text = context.meaningBlocks({goals: [g]}, '', []).join('');
  assert.match(text, /证明 \$g\$ 在 \$\[1,2\]\$ 上严格递减/);
  assert.match(text, /0&lt;g\(t\)&lt;1/);
  assert.doesNotMatch(text, /严格递增|undefined/);
});
