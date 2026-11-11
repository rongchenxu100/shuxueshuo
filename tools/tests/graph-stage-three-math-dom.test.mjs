import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
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

for (const [classification, label] of [
  ['odd_only', '奇函数'], ['even_only', '偶函数'],
  ['both', '既是奇函数又是偶函数'], ['neither', '既不是奇函数也不是偶函数'],
]) test(`verified parity completion displays ${classification}`, () => {
  const {document, find} = documentFixture();
  const answer = {kind: 'determine_function_parity', status: 'complete', classification, latex: `\\text{${label}}`};
  const {node, complete} = createRouteCompletion(document, {status: 'verified', answer});
  assert.equal(complete, true);
  assert.equal(node.children[0].textContent, '奇偶性：');
  assert.equal(find('stage-three-answer', node)[0].textContent, answer.latex);
  for (const payload of [
    {status: 'verified', available: false, answer},
    {status: 'verified', answer: {...answer, status: 'unresolved'}},
    {status: 'verified', answer: {...answer, classification: 'unknown'}},
  ]) assert.equal(createRouteCompletion(document, payload).complete, false);
});

test('generic set-answer completion displays labels without a T1 verdict board', () => {
  const {document, find} = documentFixture();
  const payload = {status: 'verified', target_ref: '/root/goals/0',
    answer: {kind: 'find_abstract_domain', status: 'set', set: {latex: '(\\frac13,5)'}},
    original_choice: {status: 'matched', kind: 'multiple_choice', matching: 'set_equality',
      selection_mode: 'unspecified', target_ref: '/root/goals/0',
      options: [{label: 'A', text: '(1/3,3)'}, {label: 'D', text: '(1/3,5)'}], correct_labels: ['D']}};
  const {node, complete} = createRouteCompletion(document, payload);
  assert.equal(complete, true);
  assert.equal(find('stage-three-choice-answer', node)[0].textContent, '答案：D　');
  assert.equal(find('gw-option-verdict-board', node).length, 0);
});

test('abstract-domain parameter completion identifies the result as a parameter range', () => {
  const {document, find} = documentFixture();
  const {node, complete} = createRouteCompletion(document, {status: 'verified',
    answer: {kind: 'find_abstract_domain_parameter', status: 'set', set: {latex: '[-\\frac12,\\frac12]'}}});
  assert.equal(complete, true);
  assert.equal(node.children[0].textContent, '参数范围：');
  assert.equal(find('stage-three-answer', node)[0].textContent, '[-\\frac12,\\frac12]');
});

for (const name of ['b11-v1', 'b11-v2']) test(`${name}: verified parameter answer remains visible in the completed course`, async () => {
  const bundle = JSON.parse(await readFile(new URL(`../../site/data/graph-walk/function-representations-${name}.json`, import.meta.url), 'utf8'));
  const payload = bundle.routes['piecewise-range-parameter'].completion;
  const {document, find} = documentFixture();
  const view = createRouteCompletion(document, payload);
  assert.equal(view.complete, true);
  assert.equal(view.node.hidden, false);
  assert.equal(find('stage-three-answer', view.node)[0].textContent, payload.answer.set.latex);
  assert.ok(view.node.children.some(child => child.textContent === '参数范围：'));
  if (name === 'b11-v1') assert.equal(find('stage-three-choice-answer', view.node)[0].textContent, '答案：C　');
  assert.equal(createRouteCompletion(document, {...payload, available: false}).complete, false);
});

test('piecewise equation completion labels input solutions without changing parameter or range answers', () => {
  const {document} = documentFixture();
  const answer = {kind: 'find_range', status: 'set', set: {latex: '\\{-3/2,2\\}'}};
  for (const [route_id, value, label] of [
    ['piecewise-equation', answer, '原方程的解集：'],
    ['piecewise-inequality', answer, '原不等式的解集：'],
    ['interval', answer, '参数范围：'],
    ['function-range', {...answer, object: 'f'}, '值域：'],
  ]) {
    const {node, complete} = createRouteCompletion(document, {status: 'verified', route_id, answer: value});
    assert.equal(complete, true);
    assert.equal(node.children[0].textContent, label);
  }
});

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

test('composition boards keep the operation visible while only the output direction is unanswered', () => {
  const {document, find} = documentFixture();
  for (const operation of [{label: '开方', math: 'v=\\sqrt{u}'}, {label: '取倒数', math: 'f(x)=\\frac1v'}]) {
    const board = {layout: 'derivation', caption: '逐层传递增减性', connector: '⇒', operation,
      items: [{label: '这一层的输入', math: 'u\\ge0'}, {label: '输出函数的增减', math: null}]};
    const pending = createDerivationBoard(document, board);
    assert.equal(pending.dataset.layout, 'function-composition');
    const middle = find('gw-derivation-operation', pending)[0];
    assert.equal(find('gw-derivation-label', middle)[0].textContent, operation.label);
    assert.equal(find('gw-derivation-formula', middle)[0].textContent, operation.math);
    assert.equal(find('gw-derivation-formula', middle)[0].dataset.mathFormula, 'true');
    assert.equal(find('gw-derivation-unknown', pending).length, 1);
    const complete = createDerivationBoard(document, {...board, items: [board.items[0], {...board.items[1], math: '\\uparrow'}]});
    assert.equal(find('gw-derivation-unknown', complete).length, 0);
    assert.equal(find('gw-derivation-operation', complete)[0].children[1].textContent, operation.math);
  }
  const unsafe = '<img src=x onerror=alert(1)>';
  const board = createDerivationBoard(document, {caption: '复合', connector: '⇒', operation: {label: unsafe, math: unsafe},
    items: [{label: '输入', math: 'u'}, {label: '输出', math: null}]});
  const middle = find('gw-derivation-operation', board)[0];
  assert.ok(middle.children.slice(0, 2).every(node => node.textContent === unsafe && !node.children.length));
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

test('domain conditions remain parallel while only the final unknown becomes the verified domain', () => {
  const {document, find} = documentFixture();
  const board = {layout: 'derivation', caption: '确定定义域', connector: '⇒', items: [
    {label: '目标函数', math: 'g(\\frac1x-1)'}, {label: '定义域（$x$ 的取值范围）', math: null}],
  condition_groups: [
    {label: '输入表达式有意义', math: '\\frac1x-1\\text{ 有意义}\\iff x\\ne0'},
    {label: '输入属于 $g$ 的定义域', math: '\\frac1x-1\\ne-2'}]};
  const pending = createDerivationBoard(document, board);
  assert.equal(pending.dataset.layout, 'parallel-conditions');
  const groups = find('gw-domain-conditions', pending)[0];
  assert.equal(groups.children.length, 2);
  assert.equal(groups['aria-label'], '需要同时满足的两个条件');
  assert.deepEqual(groups.children.map(node => node.dataset.role), ['condition', 'condition']);
  assert.deepEqual(find('gw-derivation-label', groups).map(node => node.textContent), board.condition_groups.map(group => group.label));
  assert.equal(find('gw-derivation-arrow', pending).length, 0, 'parallel conditions have no sequential arrow');
  assert.equal(find('gw-domain-condition-join-label', pending)[0].textContent, '同时满足');
  assert.equal(find('gw-derivation-unknown', pending).length, 1);
  const completed = createMathCard(document, {...step, highlight: {...board,
    items: [board.items[0], {...board.items[1], math: '\\mathbb R\\setminus\\{-1,0\\}'}]}});
  assert.equal(completed.conclusion.dataset.state, 'complete');
  assert.deepEqual(find('gw-derivation-formula', find('gw-domain-conditions', completed.node)[0]).map(node => node.textContent),
    find('gw-derivation-formula', groups).map(node => node.textContent));
  assert.equal(find('gw-derivation-unknown', completed.node).length, 0);
  assert.equal(find('gw-derivation-formula', completed.conclusion).at(-1).textContent, '\\displaystyle \\mathbb R\\setminus\\{-1,0\\}');
});

test('parallel condition labels and formulas stay inert text and retain math rendering markers', () => {
  const {document, find} = documentFixture();
  const source = '<img src=x onerror=alert(1)>', formula = '\\text{<svg/onload=alert(1)>}';
  const board = createDerivationBoard(document, {layout: 'derivation', caption: '定义域', connector: '⇒',
    items: [{label: '目标', math: 'g(x)'}, {label: '结果', math: null}],
    condition_groups: [{label: source, math: formula}, {label: '输入属于 $g$ 的定义域', math: 'x\\ne0'}]});
  const groups = find('gw-domain-conditions', board)[0];
  assert.equal(find('gw-derivation-label', groups)[0].textContent, source);
  assert.equal(find('gw-derivation-formula', groups)[0].textContent, `\\displaystyle ${formula}`);
  assert.ok(find('gw-derivation-label', groups).every(node => node.dataset.mathText === 'true' && !node.children.length));
  assert.ok(find('gw-derivation-formula', groups).every(node => node.dataset.mathFormula === 'true' && !node.children.length));
});

test('identity verification keeps both substitution sides visible before and after comparison', () => {
  const {document, find} = documentFixture();
  const board = {layout: 'derivation', caption: '分别代入，比较等式两边', connector: '⇒',
    items: [{label: '已求解析式', math: 'f(x)=x^2+3x'}, {label: '两边展开后都等于', math: null}],
    comparison_sides: [{label: '左边', math: 'f(x+y)=(x+y)^2+3(x+y)'},
      {label: '右边', math: '2(y^2+3y)+x^2+2xy-y^2+3x-3y'}]};
  const pending = createDerivationBoard(document, board);
  const groups = find('gw-domain-conditions', pending)[0];
  assert.equal(groups['aria-label'], '原等式的左边和右边');
  assert.equal(find('gw-domain-condition-join-label', pending)[0].textContent, '展开并比较');
  assert.deepEqual(find('gw-domain-condition-number', groups).map(node => node.textContent), ['左', '右']);
  assert.equal(find('gw-derivation-unknown', pending).length, 1);
  const completed = createMathCard(document, {...step, highlight: {...board,
    items: [board.items[0], {...board.items[1], math: 'x^2+2xy+y^2+3x+3y'}]}});
  assert.equal(find('gw-derivation-unknown', completed.node).length, 0);
  assert.deepEqual(find('gw-derivation-formula', find('gw-domain-conditions', completed.node)[0]).map(node => node.textContent),
    find('gw-derivation-formula', groups).map(node => node.textContent));
});

test('pairing preserves occurrences and the same arrangement when leftovers become the focus', () => {
  const {document, find} = documentFixture();
  const diagram = {focus: 'pairs', pair_value: '3', omitted_pairs: 97, omitted_leftovers: 0,
    pairs: [
      {left_id: 't2', right_id: 'r2', left_math: 'f(2)', right_math: 'f(\\frac12)'},
      {left_id: 't3', right_id: 'r3', left_math: 'f(3)', right_math: 'f(\\frac13)'},
      {left_id: 't101', right_id: 'r101', left_math: 'f(101)', right_math: 'f(\\frac1{101})'}],
    leftovers: [{id: 't1', math: 'f(1)'}, {id: 'duplicate-t1', math: 'f(1)'}]};
  const board = {layout: 'derivation', caption: '配对计数', connector: '⇒', pairing_diagram: diagram,
    items: [{label: '旧示例卡不应出现', math: '2\\leftrightarrow\\frac12'}, {label: '配对与单列项', math: null}]};
  const pending = createDerivationBoard(document, board);
  assert.equal(pending.dataset.layout, 'pairing');
  assert.equal(find('gw-derivation-unknown', pending).length, 1);
  assert.deepEqual(find('gw-derivation-label', pending).map(node => node.textContent), ['配对与单列项']);
  const figure = find('gw-pairing-diagram', pending)[0];
  assert.equal(figure.dataset.focus, 'pairs');
  assert.equal(find('gw-pairing-scroll', figure)[0].tabindex, '0');
  const terms = find('gw-pairing-term', figure);
  assert.deepEqual(terms.map(node => node.dataset.occurrenceId), ['t1', 'duplicate-t1', 't2', 'r2', 't3', 'r3', 't101', 'r101']);
  assert.deepEqual(terms.slice(0, 2).map(node => node.textContent), ['\\displaystyle f(1)', '\\displaystyle f(1)']);
  assert.equal(find('gw-pairing-pair', figure).length, 3);
  assert.equal(find('gw-pairing-ellipsis', figure).length, 1);
  assert.equal(find('gw-pairing-link-arrow', figure).length, 3);
  assert.deepEqual(find('gw-pairing-value', figure).map(node => node.textContent), Array(3).fill('\\text{和}=3'));
  const texts = node => [node.textContent, ...node.children.flatMap(texts)];
  assert.ok(!texts(figure).some(value => /97|100|201|3\/2/.test(value)), 'the picture does not disclose the counting or leftover result');
  const completed = createDerivationBoard(document, {...board,
    pairing_diagram: {...diagram, focus: 'leftovers'}, items: [board.items[0], {label: '单列项之和', math: '3'}]});
  const leftoverFigure = find('gw-pairing-diagram', completed)[0];
  assert.equal(leftoverFigure.dataset.focus, 'leftovers');
  assert.deepEqual(find('gw-pairing-term', leftoverFigure).map(node => [node.dataset.occurrenceId, node.textContent]),
    terms.map(node => [node.dataset.occurrenceId, node.textContent]));
  assert.equal(find('gw-derivation-unknown', completed).length, 0);
  assert.equal(find('gw-derivation-formula', completed)[0].textContent, '\\displaystyle 3');
});

test('pairing formulas and occurrence IDs remain inert source text', () => {
  const {document, find} = documentFixture();
  const untrusted = '<img src=x onerror=alert(1)>';
  const node = createDerivationBoard(document, {layout: 'derivation', caption: '配对', connector: '⇒',
    items: [{label: '输入', math: 'f(x)'}, {label: '结果', math: null}],
    pairing_diagram: {focus: 'leftovers', pair_value: untrusted, omitted_pairs: 0, omitted_leftovers: 0,
      pairs: [{left_id: untrusted, right_id: 'r', left_math: untrusted, right_math: 'f(1)'}],
      leftovers: [{id: 'l', math: untrusted}]}});
  assert.equal(find('gw-pairing-term', node)[1].dataset.occurrenceId, untrusted);
  assert.equal(find('gw-pairing-term', node)[0].textContent, `\\displaystyle ${untrusted}`);
  assert.equal(find('gw-pairing-value', node)[0].textContent, `\\text{和}=${untrusted}`);
  for (const name of ['gw-pairing-term', 'gw-pairing-value']) {
    assert.ok(find(name, node).every(term => term.dataset.mathFormula === 'true' && term.children.length === 0));
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

test('M9 typed completion retains expression domain and treats nonconstant separately', () => {
  const {document, find} = documentFixture();
  const answer = {kind: 'find_value', status: 'complete', result_type: 'expression_with_domain',
    defined: true, expression: {latex: '\\frac{x}{x+1}'}, domain: {latex: '\\mathbb{R}\\setminus\\{-1,0\\}'}};
  const view = createRouteCompletion(document, {answer});
  assert.equal(view.complete, true);
  assert.match(find('stage-three-answer-domain', view.node)[0].textContent, /-1,0/);
  assert.equal(createRouteCompletion(document, {answer: {...answer, domain: null}}).complete, false);
  const negative = createRouteCompletion(document, {answer: {kind: 'check_constant', status: 'complete',
    result_type: 'constant_check', defined: true, is_constant: false, value: null}});
  assert.equal(negative.complete, true);
  assert.equal(negative.node.children[0].textContent, '不是定值。');
  assert.equal(find('stage-three-answer', negative.node).length, 0);
});

test('M9 grouped completion requires every target and shows each original result', () => {
  const {document, find} = documentFixture();
  const answers = [{target_ref: '/root/goals/0', title: '求 f(1)', answer: {kind: 'find_value', status: 'complete',
    result_type: 'scalar_value', defined: true, value: {latex: '2'}}},
  {target_ref: '/root/goals/1', title: '求 g(1)', answer: {kind: 'find_value', status: 'complete',
    result_type: 'scalar_value', defined: true, value: {latex: '\\frac13'}}}];
  const answer = {kind: 'goal_group', status: 'complete', answers};
  const view = createRouteCompletion(document, {answer});
  assert.equal(view.complete, true);
  assert.equal(find('stage-three-goal-answers', view.node)[0].children.length, 2);
  assert.equal(createRouteCompletion(document, {answer: {...answer, answers: []}}).complete, false);
  assert.equal(createRouteCompletion(document, {answer: {...answer, answers: [answers[0], {...answers[1], answer: {status: 'pending'}}]}}).complete, false);
});
