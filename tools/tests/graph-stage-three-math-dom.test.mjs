import test from 'node:test';
import assert from 'node:assert/strict';
import {attachMathQA, createDerivationBoard, createMathCard, setMathCardLayout, createRouteCompletion} from '../../site/assets/graph-walk/stream-math-dom.mjs';

function documentFixture() {
  const document = {createElement(tag) { return new Element(tag); }};
  class Element {
    constructor(tag) { this.tagName = tag; this.ownerDocument = document; this.children = []; this.dataset = {}; this.hidden = false; this.textContent = ''; }
    get childNodes() { return this.children; }
    append(...children) { this.children.push(...children); }
    setAttribute(name, value) { this[name] = value; }
    replaceChildren(...children) { this.children = [...children]; }
    set innerHTML(value) { throw new Error(`must not execute source markup: ${value}`); }
  }
  const find = (className, root) => [
    ...(root.className === className ? [root] : []), ...root.children.flatMap(child => find(className, child)),
  ];
  return {document, find};
}
const identity = {run_id: 'run', lesson_version: 'lesson', target_ref: '/root/goals/0', route_id: 'interval'};
const step = {...identity, step_id: 'step-1', math_step_sha256: 'step-hash', ordinal: 1,
  title: '确定最小值', before: [{latex: 'a\\ge-\\frac52'}], after: [{latex: 'a_{min}=-\\frac52'}],
  explanation: '下确界在可行集中，最小值存在。'};
const qa = {...identity, step_id: step.step_id, math_step_sha256: step.math_step_sha256, verified_route_sha256: 'route-hash',
  qa: {questions: ['为什么最小值存在？'], feedback: '因为下确界能取到。'}};
const exactValue = (value, latex = value) => ({expression: value, latex,
  exact: value.includes('/') ? {$math: 'Rational', p: value.split('/')[0], q: value.split('/')[1]} : {$math: 'Integer', value}});

test('a deduction keeps its labelled cells while the pending question mark becomes the verified formula', () => {
  const {document, find} = documentFixture();
  const board = {layout: 'derivation', caption: '求定义域', connector: '⇒', items: [
    {label: '完整输入 $2x-1$', math: '-3\\le 2x-1\\le 2'}, {label: '目标函数的定义域', math: null}]};
  const pending = createDerivationBoard(document, board);
  assert.equal(pending.dataset.state, 'pending');
  assert.deepEqual(find('gw-derivation-label', pending).map(node => node.textContent), board.items.map(item => item.label));
  assert.ok(find('gw-derivation-label', pending).every(node => node.dataset.mathText === 'true'));
  assert.deepEqual(find('gw-derivation-formula', pending).map(node => node.textContent), ['\\displaystyle -3\\le 2x-1\\le 2']);
  const unknown = find('gw-derivation-unknown', pending)[0];
  assert.equal(unknown.textContent, '?');
  assert.equal(unknown['aria-label'], '待求');
  assert.equal(find('gw-derivation-arrow', pending)[0].textContent, '⇒');
  const completed = createMathCard(document, {...step, title: '输入范围对应',
    highlight: {...board, items: [board.items[0], {...board.items[1], math: '[-1,\\frac32]'}]}},
  {embedded: true, parentTitle: '求定义域'});
  assert.equal(completed.conclusion.className, pending.className);
  assert.equal(completed.conclusion.dataset.state, 'complete');
  assert.deepEqual(find('gw-derivation-label', completed.node).map(node => node.textContent), board.items.map(item => item.label));
  assert.equal(find('gw-derivation-unknown', completed.node).length, 0);
  assert.deepEqual(find('gw-derivation-formula', completed.node).map(node => node.textContent),
    ['\\displaystyle -3\\le 2x-1\\le 2', '\\displaystyle [-1,\\frac32]']);
  assert.equal(find('details stage-three-derivation', completed.node)[0].open, false);
  assert.equal(completed.heading.hidden, true, 'the enclosing step title is enough');
  assert.equal(completed.caption.hidden, true, 'do not repeat the enclosing step title');
  setMathCardLayout(completed);
  assert.equal(completed.heading.hidden, false, 'standalone cards retain their own title');
});

test('deduction labels, notes, captions and formulas are inserted as text, never source HTML', () => {
  const {document, find} = documentFixture();
  const untrusted = '<img src=x onerror=alert(1)>', formula = '\\text{<svg/onload=alert(1)>}';
  const board = createDerivationBoard(document, {layout: 'derivation', caption: untrusted,
    connector: untrusted, items: [{label: untrusted, note: untrusted, math: formula}, {label: '结果', math: null}]});
  assert.equal(find('gw-derivation-caption', board)[0].textContent, untrusted);
  assert.equal(find('gw-derivation-label', board)[0].textContent, untrusted);
  assert.equal(find('gw-derivation-note', board)[0].textContent, untrusted);
  assert.equal(find('gw-derivation-formula', board)[0].textContent, `\\displaystyle ${formula}`);
  assert.equal(find('gw-derivation-arrow', board)[0].textContent, untrusted);
  for (const name of ['gw-derivation-caption', 'gw-derivation-label', 'gw-derivation-note', 'gw-derivation-formula', 'gw-derivation-arrow']) {
    assert.ok(find(name, board).every(node => node.children.length === 0));
  }
});

test('shared card preserves identity, formula structure and a separate empty QA region', () => {
  const {document, find} = documentFixture(), rendered = [];
  const card = createMathCard(document, step, {renderMath: node => rendered.push(node)});
  assert.deepEqual(card.step, step);
  assert.notEqual(card.step, step);
  assert.equal(card.node.dataset.mathStepSha256, step.math_step_sha256);
  assert.equal(card.node.dataset.targetRef, identity.target_ref);
  assert.equal(card.node.dataset.routeId, identity.route_id);
  assert.equal(find('stage-three-before', card.node)[0].textContent, step.before[0].latex);
  assert.equal(find('stage-three-after', card.node)[0].textContent, step.after[0].latex);
  assert.equal(find('stage-three-explanation', card.node)[0].dataset.mathText, 'true');
  assert.equal(card.qa.hidden, true);
  assert.deepEqual(rendered, [card.node]);
});

test('a generic card leads with its after conclusion and keeps premises and prose inside open derivation', () => {
  const {document, find} = documentFixture();
  const card = createMathCard(document, step);
  const [details] = find('details stage-three-derivation', card.node);
  assert.equal(card.node.children[1], card.conclusion);
  assert.equal(card.conclusion.className, 'visual-board completed-visual stage-three-conclusion');
  assert.deepEqual(find('stage-three-after', card.conclusion).map(node => node.textContent), [step.after[0].latex]);
  assert.equal(card.node.children[2], details);
  assert.equal(details.open, true);
  assert.deepEqual(details.children.map(node => node.textContent), ['完整推导', step.before[0].latex, step.explanation]);
});

test('generic derivations omit only premises already stated in the conclusion', () => {
  const {document, find} = documentFixture();
  const card = createMathCard(document, {...step, before: [{latex: 'x>0'}, {latex: ' a=1 '}], after: ['a=1']});
  assert.deepEqual(find('stage-three-before', card.node).map(node => node.textContent), ['x>0']);
  assert.deepEqual(find('stage-three-after', card.node).map(node => node.textContent), ['a=1']);
  assert.equal(find('stage-three-explanation', card.node)[0].textContent, step.explanation);
  const premiseOnly = createMathCard(document, {...step, after: []});
  assert.equal(premiseOnly.conclusion, null);
  assert.equal(find('stage-three-before', premiseOnly.node)[0].textContent, step.before[0].latex);
});

test('embedding hides only a repeated title and moving the card restores its standalone heading without rebuilding math', () => {
  const {document} = documentFixture();
  const card = createMathCard(document, step, {embedded: true, parentTitle: step.title});
  const children = [...card.node.children];
  assert.equal(card.heading.hidden, true);
  assert.match(card.node.className, /\bis-embedded\b/);
  setMathCardLayout(card, {embedded: true, parentTitle: '检查边界并得出最值'});
  assert.equal(card.heading.hidden, false, 'a merged step keeps each distinct subheading');
  setMathCardLayout(card);
  assert.equal(card.heading.hidden, false);
  assert.equal(card.node.className, 'stage-three-math-step');
  assert.deepEqual(card.node.children, children, 'layout changes do not replace the math or QA nodes');
});

test('a repeated board caption is hidden while distinct conclusion labels remain visible', () => {
  const {document} = documentFixture();
  const card = createMathCard(document, {...step, highlight: {caption: '外层步骤', items: [{label: '范围', math: 'a>1'}]}},
    {embedded: true, parentTitle: '外层步骤'});
  assert.equal(card.heading.hidden, false);
  assert.equal(card.caption.hidden, true);
  setMathCardLayout(card);
  assert.equal(card.caption.hidden, false, 'standalone views recover a caption different from their own title');
  const repeated = createMathCard(document, {...step, highlight: {caption: step.title, items: [{label: '最小值', math: '-1'}]}});
  assert.equal(repeated.caption.hidden, true);
  assert.equal(repeated.heading.hidden, false);
});

test('only an explicit graph replacement hides a conclusion, and reused cards restore their fallback', () => {
  const {document, find} = documentFixture();
  for (const replace_with_graph of [true, false, undefined]) {
    const card = createMathCard(document, {...step, highlight: {caption: '判定', replace_with_graph,
      items: [{label: '结论', math: 'a>1'}]}}, {externalConclusion: true});
    const nodes = [...card.node.children];
    assert.equal(card.conclusion.hidden, replace_with_graph === true);
    assert.equal(find('details stage-three-derivation', card.node)[0].open, true);
    setMathCardLayout(card);
    assert.equal(card.conclusion.hidden, false, 'readonly, retained and failed-graph views show the fallback again');
    assert.deepEqual(card.node.children, nodes);
  }
  const generic = createMathCard(document, step, {externalConclusion: true});
  assert.equal(generic.conclusion.hidden, false, 'a separate formula conclusion is not replaced by a picture');
});

test('a highlighted card leads with the conclusion board and folds the prose into a derivation', () => {
  const {document, find} = documentFixture();
  const highlighted = {...step, title: '分离参数', explanation: '$\\because x<0$，$\\therefore x<0$。移项得 $ax\\ge-x^2-2$。',
    highlight: {caption: '两边同除以负数', items: [{label: '移项后', math: 'ax\\ge-x^2-2'},
      {label: '两边除以 $x$', math: 'a\\le-x-\\frac2x', note: '$x<0$，不等号方向改变'}]}};
  const {node} = createMathCard(document, highlighted);
  const [board] = find('visual-board completed-visual stage-three-highlight', node);
  assert.equal(find('board-caption', board)[0].textContent, '两边同除以负数');
  assert.deepEqual(find('math', board).map(item => [item.textContent, item.dataset.mathFormula]),
    [['\\displaystyle ax\\ge-x^2-2', 'true'], ['\\displaystyle a\\le-x-\\frac2x', 'true']]);
  assert.deepEqual(find('conversion-label', board).map(item => item.textContent), ['移项后', '两边除以 $x$', '$x<0$，不等号方向改变']);
  assert.equal(find('conversion-arrow', board).length, 1);
  const [details] = find('details stage-three-derivation', node);
  assert.equal(details.open, true);
  assert.deepEqual(find('stage-three-explanation', details).map(line => line.textContent),
    ['$\\because x<0$，$\\therefore x<0$', '移项得 $ax\\ge-x^2-2$。']);
  assert.equal(find('stage-three-after', node).length, 0);
});

test('parallel case conclusions preserve an explicit empty connector instead of implying a transformation', () => {
  const {document, find} = documentFixture();
  const highlight = {caption: '分类条件', connector: '', items: [
    {label: '一次或常数情况', math: 'k=0'}, {label: '二次情况', math: 'k\\ne0'}]};
  const card = createMathCard(document, {...step, highlight});
  const arrows = find('conversion-arrow', card.node);
  assert.equal(arrows.length, 1, 'the empty layout spacer keeps the cases side by side');
  assert.equal(arrows[0].textContent, '');
  assert.equal(arrows[0]['aria-hidden'], 'true');
  assert.deepEqual(find('math', card.node).map(item => item.textContent), ['\\displaystyle k=0', '\\displaystyle k\\ne0']);
  const defaultHighlight = {...highlight}; delete defaultHighlight.connector;
  assert.equal(find('conversion-arrow', createMathCard(document, {...step, highlight: defaultHighlight}).node)[0].textContent, '→');
  assert.equal(find('conversion-arrow', createMathCard(document, {...step, highlight: {...highlight, connector: '⇔'}}).node)[0].textContent, '⇔');
});

for (const display_unit of ['domain_locations', 'domain_conditions', 'domain_solutions']) test(`${display_unit} keeps independent restrictions on separate lines`, () => {
  const {document, find} = documentFixture();
  const value = {...step, display_unit, highlight: {caption: '原式的条件', items: [
    {label: '被开方数', math: 'x-1\\ge0'}, {label: '分母', math: 'x-2\\ne0'}]}};
  const card = createMathCard(document, value);
  assert.equal(find('gw-domain-parallel', card.node).length, 1);
  assert.equal(find('conversion-arrow', card.node).length, 0, 'independent conditions never imply one another');
  assert.deepEqual(find('math', card.node).map(item => item.textContent), ['\\displaystyle x-1\\ge0', '\\displaystyle x-2\\ne0']);
  assert.deepEqual(card.step, value, 'display layout leaves the verified mathematical source untouched');
});

test('an ordinary conclusion board displays a result only when explicitly requested', () => {
  const {document, find} = documentFixture(), rendered = [];
  const highlight = {caption: '检查退化情况', items: [{label: '代入后', math: '0\\ge0'}],
    result: '满足原题，保留 $k=0$。', show_result: true};
  const card = createMathCard(document, {...step, highlight}, {renderMath: node => rendered.push(node)});
  const [result] = find('gw-result', card.conclusion);
  assert.equal(result.textContent, highlight.result);
  assert.equal(result.dataset.mathText, 'true');
  assert.equal(card.conclusion.children.at(-1), result);
  assert.deepEqual(rendered, [card.node], 'the result is present before mathematical text is rendered');
  for (const show_result of [undefined, false, 'true']) {
    assert.equal(find('gw-result', createMathCard(document, {...step, highlight: {...highlight, show_result}}).node).length, 0,
      'legacy carry results do not duplicate the mathematical conclusion');
  }
  for (const value of [undefined, '', '   ']) {
    assert.equal(find('gw-result', createMathCard(document, {...step, highlight: {...highlight, result: value}}).node).length, 0);
  }
  const untrusted = '<img src=x onerror=alert(1)> $k=0$';
  const safe = createMathCard(document, {...step, highlight: {...highlight, result: untrusted}});
  assert.equal(find('gw-result', safe.node)[0].textContent, untrusted);
  assert.equal(find('gw-result', safe.node)[0].children.length, 0);
});

test('a newline in the derivation starts a new line, as each ∵/∴ step does', () => {
  const {document, find} = documentFixture();
  const chained = {...step, explanation: '$\\because x>0$，$\\therefore \\frac1x>0$，\n$\\therefore h(x)\\le-2$。由对勾函数的性质。',
    highlight: {caption: '对勾函数', items: [{label: '最高点', math: '(1,-2)'}]}};
  const [details] = find('details stage-three-derivation', createMathCard(document, chained).node);
  assert.deepEqual(find('stage-three-explanation', details).map(line => line.textContent),
    ['$\\because x>0$，$\\therefore \\frac1x>0$，', '$\\therefore h(x)\\le-2$', '由对勾函数的性质。']);
});

test('standalone derivations omit full stops without splitting math blocks or changing verified source', () => {
  const {document, find} = documentFixture();
  const formulas = [
    '$\\begin{aligned}16m^2-12m\\le0&\\iff m\\in[0,3/4]\\\\\nm&\\in(0,3/4]\\end{aligned}$',
    '$\\{0\\}\\cup(0,3/4]=[0,3/4]$',
    '$$m\\in[0,3/4]$$', '\\[m\\in[0,3/4]\\]', '\\(m\\in[0,3/4]\\)',
    '$\\text{保留句号。}\\quad m=0$',
  ];
  const original = {...step, explanation: formulas.map(formula => `${formula}。`).join('\n')};
  const before = structuredClone(original);
  const card = createMathCard(document, original);
  assert.deepEqual(find('stage-three-explanation', card.node).map(line => line.textContent), formulas);
  assert.deepEqual(original, before);
  assert.deepEqual(card.step, before, 'punctuation is presentation only, not a new mathematical revision');
});

test('prose punctuation and unmatched math remain untouched', () => {
  const {document, find} = documentFixture();
  const lines = ['当 $m=0$ 时，条件成立。', '$m=0$ 时，条件成立。',
    '因此：$m\\in[0,3/4]$。', '$m=0。', '\\(m=0。'];
  const card = createMathCard(document, {...step, explanation: lines.join('\n')});
  assert.deepEqual(find('stage-three-explanation', card.node).map(line => line.textContent), lines);
});

test('a derivation-only card skips before/after and opens the prose under 完整推导', () => {
  const {document, find} = documentFixture();
  const cases = {...step, title: '分类讨论最值', derivation: true,
    explanation: '$g(x)$ 开口向上，\n① 当 $a\\le-1$ 时，$g(x)_{\\min}=g(\\frac12)$。'};
  const {node} = createMathCard(document, cases);
  assert.equal(find('visual-board completed-visual stage-three-highlight', node).length, 0);
  assert.equal(find('stage-three-before', node).length + find('stage-three-after', node).length, 0);
  const [details] = find('details stage-three-derivation', node);
  assert.equal(details.open, true);
  assert.deepEqual(find('stage-three-explanation', details).map(line => line.textContent),
    ['$g(x)$ 开口向上，', '① 当 $a\\le-1$ 时，$g(x)_{\\min}=g(\\frac12)$。']);
});

test('a merge card shows one cell per case and the union on its own line, then the derivation', () => {
  const {document, find} = documentFixture();
  const merged = {...step, title: '求参数范围', explanation: '① 由 $m\\ge-3$ 得 $m\\in\\varnothing$；\n综上，取并集得 $m<-5$。',
    highlight: {caption: '取并集', layout: 'merge', result: '$m<-5$', items: [
      {label: '情况①（$m\\ge-3$）', math: '\\text{无解}'}, {label: '情况②（$m<-3$）', math: 'm<-5'}]}};
  const {node} = createMathCard(document, merged);
  const [board] = find('case-merge stage-three-highlight', node);
  assert.deepEqual(find('case-merge-name', board).map(item => item.textContent), ['情况①（$m\\ge-3$）', '情况②（$m<-3$）']);
  assert.deepEqual(find('case-merge-value', board).map(item => item.textContent), ['$\\text{无解}$', '$m<-5$']);
  assert.equal(find('case-merge-total', board)[0].textContent, '取并集：$m<-5$');
  assert.equal(find('conversion-arrow', node).length, 0);
  assert.equal(find('details stage-three-derivation', node).length, 1);
});

test('a conclusion-only card shows the board alone, with no derivation or formula lists', () => {
  const {document, find} = documentFixture();
  const closing = {...step, title: '确定最小值', explanation: '$\\therefore$ $a$ 的最小值为 $-1$。',
    highlight: {caption: '确定最小值', items: [{label: '$a$ 的最小值', math: '-1'}], conclusion_only: true}};
  const {node} = createMathCard(document, closing);
  assert.equal(find('visual-board completed-visual stage-three-highlight', node).length, 1);
  assert.equal(find('details stage-three-derivation', node).length, 0);
  assert.equal(find('stage-three-before', node).length + find('stage-three-after', node).length, 0);
});

test('late QA only changes its region and preserves the mathematical DOM', () => {
  const {document} = documentFixture(), rendered = [];
  const card = createMathCard(document, step), nodes = [...card.node.children];
  attachMathQA(card, qa, {renderMath: node => rendered.push(node)});
  assert.deepEqual(card.node.children, nodes);
  assert.equal(card.qa.hidden, false);
  assert.equal(card.qa.children[1].textContent, qa.qa.questions[0]);
  assert.equal(card.qa.children[1].dataset.mathText, 'true');
  assert.equal(rendered.length, 1);
  const recovered = createMathCard(document, step, {qa});
  assert.deepEqual(recovered.qa.children.map(node => node.textContent), card.qa.children.map(node => node.textContent));
});

test('a failed QA renderer leaves the previous attachment intact and can retry', () => {
  const {document} = documentFixture(), card = createMathCard(document, step);
  assert.throws(() => attachMathQA(card, qa, {renderMath() { throw new Error('renderer loading'); }}), /renderer loading/);
  assert.equal(card.qa.hidden, true);
  assert.deepEqual(card.qa.children, []);
  attachMathQA(card, qa);
  const children = [...card.qa.children];
  assert.throws(() => attachMathQA(card, qa, {renderMath() { throw new Error('renderer loading'); }}), /renderer loading/);
  assert.deepEqual(card.qa.children, children);
});

for (const key of ['run_id', 'lesson_version', 'target_ref', 'route_id', 'step_id', 'math_step_sha256']) {
  test(`QA helper rejects a mismatched ${key}`, () => {
    const {document} = documentFixture(), card = createMathCard(document, step);
    assert.throws(() => attachMathQA(card, {...qa, [key]: 'different'}), /qa_hash_mismatch/);
    assert.equal(card.qa.hidden, true);
  });
}

test('untrusted titles, formula text, explanation and QA never become executable HTML', () => {
  const {document, find} = documentFixture(), source = '<img src=x onerror="attack()">';
  const card = createMathCard(document, {...step, title: source, before: [{latex: source}], after: [{latex: source}], explanation: source},
    {qa: {...qa, qa: {questions: [source], extra: {text: source}}}});
  assert.equal(card.node.children[0].textContent, source);
  assert.equal(find('stage-three-before', card.node).length, 0, 'identical before/after text is only shown once');
  for (const name of ['stage-three-after', 'stage-three-explanation']) {
    assert.equal(find(name, card.node)[0].textContent, source);
  }
  const premise = createMathCard(document, {...step, before: [{latex: source}], after: []});
  assert.equal(find('stage-three-before', premise.node)[0].textContent, source);
  assert.equal(card.qa.children[1].textContent, source);
  assert.equal(card.qa.children[3].textContent, source);
});

test('render failure returns no partially initialized math card', () => {
  const {document} = documentFixture();
  assert.throws(() => createMathCard(document, step, {renderMath() { throw new Error('renderer loading'); }}), /renderer loading/);
  assert.equal(createMathCard(document, step).node.dataset.stepId, step.step_id);
});

test('range completion preserves readable math and calls the injected renderer', () => {
  const {document, find} = documentFixture(), rendered = [];
  const value = createRouteCompletion(document, {answer: {kind: 'find_range', status: 'set', set: {latex: '[0,+\\infty)'}}},
    {renderMath: node => rendered.push(node)});
  assert.equal(value.complete, true);
  assert.equal(value.node.hidden, false);
  assert.equal(find('stage-three-answer', value.node)[0].textContent, '[0,+\\infty)');
  assert.deepEqual(rendered, [value.node]);
});

test('domain completion labels the verified set as the domain', () => {
  const {document, find} = documentFixture();
  const value = createRouteCompletion(document, {answer: {kind: 'find_domain', status: 'set', set: {latex: '[1,2)\\cup(2,+\\infty)'}}});
  assert.equal(value.complete, true);
  assert.equal(value.node.children[0].textContent, '定义域：');
  assert.equal(find('stage-three-answer', value.node)[0].textContent, '[1,2)\\cup(2,+\\infty)');
});

for (const formula of ['[-1,\\frac{3}{2}]', '\\mathbb{R}', '\\varnothing']) test(`abstract domain completion displays ${formula}`, () => {
  const {document, find} = documentFixture();
  const payload = {status: 'verified', answer: {kind: 'find_abstract_domain', status: 'set', set: {latex: formula}}};
  const value = createRouteCompletion(document, payload);
  assert.equal(value.complete, true);
  assert.equal(value.node.children[0].textContent, '定义域：');
  assert.equal(find('stage-three-answer', value.node)[0].textContent, formula);
  assert.equal(createRouteCompletion(document, {...payload, available: false}).complete, false);
});

test('comparison conclusion board explains verified reason codes in student language', () => {
  const {document, find} = documentFixture();
  const options = ['A', 'B', 'C', 'D'].map(label => ({option_id: label, label, text: `比较 ${label} 的两个函数`}));
  const option_verdicts = options.map((option, index) => ({option_id: option.option_id, label: option.label,
    verdict: index < 2 ? 'different' : 'equal',
    reason: ['domains_differ', 'outputs_differ', 'same_domain_and_correspondence', '两式仅自变量名称不同'][index]}));
  const payload = {status: 'verified', target_ref: '/root/goals/0',
    answer: {kind: 'compare_functions', status: 'complete', option_verdicts},
    original_choice: {status: 'matched', kind: 'multiple_choice', selection_mode: 'multiple', target_ref: '/root/goals/0',
      select_relation: 'equal', options, correct_labels: ['C', 'D'], option_verdicts}};
  const before = structuredClone(payload);
  const value = createRouteCompletion(document, payload);
  assert.deepEqual(find('gw-option-verdict-board', value.node)[0].children.map(row => row.textContent), [
    'A　不同：定义域不同', 'B　不同：存在同一个输入，两式的函数值不同',
    'C　相同：定义域相同，且每个输入对应的函数值都相同', 'D　相同：两式仅自变量名称不同',
  ]);
  assert.deepEqual(payload, before, 'presentation does not rewrite verified mathematical results');
});

for (const [kind, status, field, label, formula] of [
  ['find_minimum', 'attained', 'value', '最小值：', '-5/2'],
  ['find_maximum', 'attained', 'value', '最大值：', '5/2'],
  ['find_minimum', 'not_attained', 'bound', '最小值不存在，只能趋近：', '-5/2'],
  ['find_maximum', 'not_attained', 'bound', '最大值不存在，只能趋近：', '5/2'],
  ['find_minimum', 'unbounded_below', null, '最小值不存在：可行集没有下界。', null],
  ['find_maximum', 'unbounded_above', null, '最大值不存在：可行集没有上界。', null],
  ['find_minimum', 'empty_feasible_set', null, '没有满足题设的参数，最小值不存在。', null],
  ['find_maximum', 'empty_feasible_set', null, '没有满足题设的参数，最大值不存在。', null],
]) test(`typed ${kind}/${status} distinguishes extrema, bounds and absence`, () => {
  const {document, find} = documentFixture();
  const value = createRouteCompletion(document, {answer: {kind, status, ...(field ? {[field]: exactValue(formula)} : {})}});
  assert.equal(value.node.hidden, false);
  assert.equal(value.complete, true);
  assert.equal(value.node.children[0].textContent, label);
  assert.deepEqual(find('stage-three-answer', value.node).map(node => node.textContent), formula ? [formula] : []);
  assert.equal(value.answerStatus, status);
});

for (const answer of [
  {kind: 'find_minimum', status: 'unknown', value: exactValue('2')},
  {kind: 'find_minimum', status: 'attained'},
  {kind: 'find_maximum', status: 'not_attained'},
  {kind: 'find_maximum', status: 'unbounded_below'},
  {kind: 'find_minimum', status: 'unbounded_above'},
  {kind: 'find_range', status: 'attained', value: exactValue('2')},
  {kind: 'unrecognized', status: 'attained', value: exactValue('2')},
  {kind: 'find_minimum', status: 'attained', value: {expression: '-oo', latex: '-\\infty', exact: {$math: 'NegativeInfinity'}}},
]) test(`an incomplete answer cannot render a successful completion: ${JSON.stringify(answer)}`, () => {
  const {document, find} = documentFixture(), value = createRouteCompletion(document, {answer});
  assert.equal(value.node.hidden, true);
  assert.equal(value.complete, false);
  assert.equal(find('stage-three-answer', value.node).length, 0);
  assert.equal(value.answerStatus, 'unknown');
  assert.match(value.statusText, /目标答案尚未确定/);
});

test('revoked mathematical answers do not show a successful completion', () => {
  const {document} = documentFixture();
  const value = createRouteCompletion(document, {available: false, answer: {kind: 'find_range', status: 'set', set: '[0,1]'}});
  assert.equal(value.complete, false);
  assert.equal(value.node.hidden, true);
});

test('verified original option appears alongside the mathematical answer, with no HTML interpretation', () => {
  const {document, find} = documentFixture();
  const payload = {status: 'verified', identity: ['/root/goals/0', 'discriminant'],
    answer: {kind: 'find_range', status: 'set', set: {latex: '(-\\infty,-2]\\cup[2,\\infty)'}},
    original_choice: {status: 'matched', kind: 'single_choice', target_ref: '/root/goals/0',
      options: [{label: 'A', text: '$m\\le-2$ 或 $m\\ge2$'}, {label: 'B', text: '<img src=x>'}], correct_labels: ['A']}};
  const result = createRouteCompletion(document, payload);
  assert.equal(result.complete, true);
  assert.equal(find('stage-three-choice-answer', result.node)[0].textContent, '答案：A　');
  assert.equal(find('stage-three-answer', result.node)[0].textContent, payload.answer.set.latex);
  assert.equal(find('stage-three-choice-answer', createRouteCompletion(document, {...payload, available: false}).node).length, 0);
  for (const original_choice of [{...payload.original_choice, status: 'unmatched'},
    {...payload.original_choice, target_ref: '/wrong'}, {...payload.original_choice, correct_labels: ['A', 'B']}]) {
    assert.equal(find('stage-three-choice-answer', createRouteCompletion(document, {...payload, original_choice}).node).length, 0);
  }
});
