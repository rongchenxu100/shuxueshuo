import test from 'node:test';
import assert from 'node:assert/strict';
import {intervalOverlapAt, intervalExplorerScale, createIntervalOverlapSVG, createIntervalOverlapExplorer} from '../../site/assets/graph-walk/interval-overlap-visual.mjs';
import {createDerivationBoard} from '../../site/assets/graph-walk/stream-math-dom.mjs';

const config = {parameter: 'a', variable: 'x', mode: 'explore', strategy: 'complement',
  intervals: [
    {label: 'A', call_latex: 'f(x+a)', lower: {slope: -1, intercept: 0}, upper: {slope: -1, intercept: 1}, left_open: false, right_open: false},
    {label: 'B', call_latex: 'f(x-a)', lower: {slope: 1, intercept: 0}, upper: {slope: 1, intercept: 1}, left_open: false, right_open: false},
  ], parameter_min: -1, parameter_max: 1, initial: 0, critical_values: [-.5, .5]};
const all = node => [node, ...node.children.flatMap(all)];
const find = (root, className) => all(root).filter(node => node.className === className || node.attributes.class === className);
const contents = root => all(root).map(node => node.textContent).filter(Boolean).join(' ');
function documentFixture() {
  const document = {createElement: tag => new Element(tag), createElementNS: (_, tag) => new Element(tag)};
  class Element {
    constructor(tag) { this.tagName = tag; this.children = []; this.attributes = {}; this.dataset = {}; this.textContent = ''; this.listeners = {}; }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = children; }
    setAttribute(name, value) { this.attributes[name] = value; }
    addEventListener(name, handler) { (this.listeners[name] ??= []).push(handler); }
    fire(name) { this.listeners[name]?.forEach(handler => handler({target: this})); }
    set innerHTML(value) { throw Error(`unsafe markup ${value}`); }
  }
  return document;
}

test('one pure observation distinguishes separation, overlap and closed endpoint contact', () => {
  const saved = JSON.stringify(config);
  for (const value of [-1, 1]) assert.equal(intervalOverlapAt(config, value).kind, 'separate');
  assert.equal(intervalOverlapAt(config, 0).intersection, '[0, 1]');
  assert.equal(intervalOverlapAt(config, .25).intersection, '[0.25, 0.75]');
  for (const value of [-.5, .5]) {
    const observation = intervalOverlapAt(config, value);
    assert.equal(observation.kind, 'point');
    assert.equal(observation.empty, false);
    assert.equal(observation.intersection, '{0.5}');
  }
  assert.equal(JSON.stringify(config), saved, 'exploration never mutates the authored board');
});

test('touching open endpoints are empty; irrelevant outer endpoints do not remove a common point', () => {
  const open = structuredClone(config);
  open.intervals[0].right_open = true;
  assert.equal(intervalOverlapAt(open, .5).kind, 'touch-empty');
  assert.equal(intervalOverlapAt(open, .5).intersection, '∅');
  assert.equal(intervalOverlapAt(open, -.5).kind, 'point');
  assert.equal(intervalOverlapAt(open, 0).intersection, '[0, 1)');
  open.intervals[1].left_open = true;
  assert.equal(intervalOverlapAt(open, 0).intersection, '(0, 1)');
});

test('constant intervals, singleton intervals and impossible reversed bounds retain set semantics', () => {
  const constant = structuredClone(config);
  constant.intervals.forEach(row => { row.lower.slope = 0; row.upper.slope = 0; });
  assert.equal(intervalOverlapAt(constant, 1).intersection, '[0, 1]');
  constant.intervals[1].upper.intercept = 0;
  assert.equal(intervalOverlapAt(constant, .5).intersection, '{0}');
  constant.intervals[1].left_open = true;
  assert.equal(intervalOverlapAt(constant, .5).empty, true);
  constant.intervals[1].lower.intercept = 2;
  assert.equal(intervalOverlapAt(constant, .5).empty, true);
});

test('set semantics preserve narrow open intervals and distinct large endpoints', () => {
  for (const [lower, upper, open, expected] of [
    ['0', '1/100000000000', true, '(0, 1e−11)'],
    ['10000000000', '10000000001', false, '[10000000000, 10000000001]'],
    ['100000000000000000000', '100000000000000000001', false, '[100000000000000000000, 100000000000000000001]'],
  ]) {
    const narrow = structuredClone(config);
    for (const row of narrow.intervals) {
      row.lower = {slope: 0, intercept: Number(lower), slope_exact: '0', intercept_exact: lower};
      row.upper = {slope: 0, intercept: upper.includes('/') ? 1e-11 : Number(upper), slope_exact: '0', intercept_exact: upper};
      row.left_open = open; row.right_open = open;
    }
    const observation = intervalOverlapAt(narrow, 0);
    assert.equal(observation.kind, 'overlap');
    assert.equal(observation.intersection, expected);
    const svg = createIntervalOverlapSVG(documentFixture(), narrow, observation);
    assert.ok(all(svg).every(node => Object.values(node.attributes).every(value => !/NaN|Infinity/.test(value))));
  }
  const legacy = structuredClone(config);
  legacy.intervals.forEach(row => { row.upper.intercept = 1e-11; row.left_open = true; row.right_open = true; });
  assert.equal(intervalOverlapAt(legacy, 0).kind, 'overlap', 'old numeric payloads do not use drawing tolerance either');
});

test('exact critical parameters distinguish contact from neighbouring parameter values', () => {
  const thirds = structuredClone(config);
  thirds.intervals[0].lower = {slope: 0, intercept: 0};
  thirds.intervals[0].upper = {slope: 0, intercept: 1};
  thirds.intervals[1].lower = {slope: 3, intercept: 0};
  thirds.intervals[1].upper = {slope: 3, intercept: 1};
  thirds.critical_values = [1 / 3]; thirds.critical_exact_values = ['1/3'];
  assert.equal(intervalOverlapAt(thirds, 1 / 3).kind, 'point');
  assert.equal(intervalOverlapAt(thirds, 1 / 3 + Number.EPSILON).kind, 'separate');
  assert.equal(intervalOverlapAt(thirds, 1 / 3 - Number.EPSILON).kind, 'overlap');
  delete thirds.critical_exact_values;
  assert.equal(intervalOverlapAt(thirds, 1 / 3).kind, 'point', 'legacy critical values can be recovered from affine endpoints');
});

test('collapsed numeric parameter ranges retain distinct exact snapshot buttons', () => {
  const precise = structuredClone(config);
  precise.parameter_min = precise.parameter_max = precise.initial = 1e20;
  precise.critical_values = [1e20, 1e20];
  precise.critical_exact_values = ['100000000000000000000', '100000000000000000001'];
  precise.intervals[0].lower = {slope: 0, intercept: 0};
  precise.intervals[0].upper = {slope: 0, intercept: 1};
  precise.intervals[1].lower = {slope: 1, intercept: -1e20, intercept_exact: '-100000000000000000000'};
  precise.intervals[1].upper = {slope: 1, intercept: -1e20, intercept_exact: '-99999999999999999999'};
  const node = createIntervalOverlapExplorer(documentFixture(), precise);
  const buttons = find(node, 'gw-interval-snapshot');
  assert.equal(buttons.length, 2);
  assert.equal(find(node, 'gw-interval-slider')[0].disabled, true);
  buttons[0].fire('click');
  assert.equal(node.dataset.state, 'overlap');
  buttons[1].fire('click');
  assert.equal(node.dataset.state, 'point');
  assert.equal(find(node, 'gw-interval-intersection')[0].textContent, 'A ∩ B = {1}');
});

test('both tracks share a stable scale and SVG distinguishes filled/open endpoints', () => {
  const document = documentFixture(), scale = intervalExplorerScale(config);
  assert.ok(scale.min < -1 && scale.max > 2);
  const open = structuredClone(config); open.intervals[0].left_open = true;
  const svg = createIntervalOverlapSVG(document, open, intervalOverlapAt(open, .25));
  const points = all(svg).filter(node => node.tagName === 'circle');
  assert.equal(points.filter(node => node.attributes['data-endpoint'] === 'open').length, 1);
  assert.ok(points.find(node => node.attributes['data-endpoint'] === 'open').attributes.fill === '#fff');
  assert.ok(points.filter(node => node.attributes['data-endpoint'] === 'closed').every(node => node.attributes.fill !== '#fff'));
  assert.match(svg.attributes['aria-label'], /重叠.*交集 \[0.25, 0.75\]/);
  const point = createIntervalOverlapSVG(document, config, intervalOverlapAt(config, .5));
  assert.ok(all(point).some(node => node.tagName === 'circle' && node.attributes.stroke === '#438d62'));
  const apart = createIntervalOverlapSVG(document, config, intervalOverlapAt(config, 1));
  assert.ok(!all(apart).some(node => node.tagName === 'circle' && node.attributes.stroke === '#438d62'));
});

test('sliders and snapshot buttons update only their own node and never reveal the parameter answer', () => {
  const document = documentFixture(), first = createIntervalOverlapExplorer(document, config), second = createIntervalOverlapExplorer(document, config);
  const buttons = find(first, 'gw-interval-snapshot');
  assert.equal(buttons.length, 5);
  assert.equal(first.dataset.state, 'overlap');
  buttons.find(button => button.dataset.parameter === '0.5').fire('click');
  assert.equal(first.dataset.state, 'point');
  assert.equal(second.dataset.state, 'overlap');
  assert.equal(find(first, 'gw-interval-intersection')[0].textContent, 'A ∩ B = {0.5}');
  const slider = find(first, 'gw-interval-slider')[0];
  slider.value = '-1'; slider.fire('input');
  assert.equal(first.dataset.state, 'separate');
  assert.equal(find(first, 'gw-interval-current')[0].textContent, 'a = −1');
  assert.ok(buttons.every(button => button.type === 'button'));
  assert.ok(all(first).every(node => node.attributes.id === undefined && !node.dataset.choice && !node.dataset.multi));
  assert.doesNotMatch(contents(first), /参数范围|\[-0\.5, 0\.5\]|正确答案/);
});

test('separation mode shows both labelled relative orders, not a solved inequality', () => {
  const node = createIntervalOverlapExplorer(documentFixture(), {...config, mode: 'separation'});
  assert.deepEqual(find(node, 'gw-interval-separation-title').map(item => item.textContent), ['A 在 B 左侧', 'B 在 A 左侧']);
  assert.equal(find(node, 'gw-interval-svg').length, 2);
  assert.match(contents(node), /−a/);
  assert.match(contents(node), /a\+1/);
  assert.match(contents(node), /1−a/);
  assert.doesNotMatch(contents(node), /[<>≤≥]|参数范围/);
  assert.equal(find(node, 'gw-interval-slider').length, 0);
});

test('exploration is additive to pending and completed deduction boards without changing answers', () => {
  const document = documentFixture(), board = {layout: 'derivation', caption: '观察交集', connector: '⇒',
    items: [{label: '输入区间', math: 'A\\cap B'}, {label: '共同输入', math: null}], interval_explorer: config};
  const pending = createDerivationBoard(document, board);
  assert.equal(find(pending, 'gw-derivation-unknown').length, 1);
  find(pending, 'gw-interval-snapshot')[0].fire('click');
  assert.equal(pending.dataset.state, 'pending');
  assert.equal(board.items[1].math, null);
  const completed = createDerivationBoard(document, {...board, items: [board.items[0], {...board.items[1], math: 'A\\cap B\\ne\\varnothing'}]});
  assert.equal(completed.dataset.state, 'complete');
  assert.equal(find(completed, 'gw-interval-explorer').length, 1);
  assert.equal(find(completed, 'gw-derivation-unknown').length, 0);
});

test('untrusted strings are text and invalid numeric configurations fail closed', () => {
  const malicious = structuredClone(config);
  malicious.intervals[0].label = '<img onerror=alert(1)>';
  malicious.intervals[0].call_latex = '<script>alert(1)</script>';
  const node = createIntervalOverlapExplorer(documentFixture(), malicious);
  assert.ok(contents(node).includes(malicious.intervals[0].label));
  assert.ok(!all(node).some(item => ['script', 'img', 'foreignObject'].includes(item.tagName)));
  assert.throws(() => intervalOverlapAt({...config, parameter_min: Infinity}, 0), TypeError);
  assert.throws(() => intervalOverlapAt(config, NaN), TypeError);
  assert.throws(() => createIntervalOverlapExplorer(documentFixture(), {...config, critical_values: [NaN]}), TypeError);
});
