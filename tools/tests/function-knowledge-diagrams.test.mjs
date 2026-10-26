import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';

async function diagram(name) {
  const source = (await fs.readFile(new URL(`../../site/assets/explain/knowledge/${name}.js`, import.meta.url), 'utf8'))
    .replace(/^import .*;\n/gm, '')
    .replace('export default {', 'globalThis.diagram = {')
    .replace(/import\.meta\.url/g, '"https://site/module.js"');
  const context = vm.createContext({URL});
  vm.runInContext(source, context);
  return expression => vm.runInContext(expression, context);
}

test('piecewise graph retains both full segments and draggable points inside the viewport', async () => {
  const run = await diagram('piecewise-function');
  for (const x of [-3.2, -3.05, -2.5, 0, 2.5, 3.05, 3.2]) {
    const [y, screenY] = run(`[f(${x}), sy(f(${x}))]`);
    assert.equal(y, 1 - Math.abs(x));
    assert.ok(screenY > 16 && screenY < 210, `${x}: ${screenY}`);
  }
  assert.match(run('layer(-3.05)'), /text-anchor="start" class="pw-point-label"/);
  assert.match(run('layer(3.05)'), /text-anchor="end" class="pw-point-label"/);
  assert.match(run('layer(0)'), /左段 y = x \+ 1/);
  assert.match(run('layer(0.01)'), /右段 y = 1 − x/);
});

test('floor samples agree with the displayed input at integer boundaries and both viewport edges', async () => {
  const run = await diagram('floor-function');
  const values = [-3.05, -3, -2.999, -1.001, -0.001, 0, 0.999, 1.999, 4, 4.05];
  for (const x of values) {
    const html = run(`layer(${x})`), [, input, value] = html.match(/⌊([^⌋]+)⌋ = (-?\d+)/);
    assert.equal(Number(value), Math.floor(Number(input)), html);
    const [, px, py] = html.match(/<circle cx="([^"]+)" cy="([^"]+)" r="5.5"/);
    assert.ok(Number(py) >= 16 && Number(py) <= 210, `${x}: ${py}`);
    const segments = [...html.matchAll(/<path d="M([\d.]+) ([\d.]+)H([\d.]+)" class="fl-step"/g)];
    assert.ok(segments.some(([, left, y, right]) => Number(px) >= Number(left) - .05 && Number(px) <= Number(right) + .05 && Math.abs(Number(py) - Number(y)) < .051), `${x}: point must lie on a rendered step`);
  }
  assert.match(run('layer(-0.001)'), /⌊0⌋ = 0/);
  assert.match(run('layer(1.999)'), /⌊2⌋ = 2/);
});

test('number-line arrows point outwards toward each infinity and toward increasing x', async () => {
  const run = await diagram('interval-notation');
  for (const direction of ['left', 'right']) {
    for (const endpoint of ['open', 'closed']) {
      const html = run(`layer(CASES.find(item => item.id === 'ray-${direction}-${endpoint}'))`);
      const [, tip, base] = html.match(/<path d="M([\d.]+) 78L([\d.]+) 72V84Z" class="iv-arrow"/);
      assert.ok(direction === 'left' ? Number(tip) < Number(base) : Number(tip) > Number(base));
    }
  }
  const [, tip, base] = run('figure()').match(/<path d="M([\d.]+) 78L([\d.]+) 73V83Z" class="iv-axis-arrow"/);
  assert.ok(Number(tip) > Number(base));
});

test('reciprocal pointerdown chooses either branch while a captured drag stays on its branch', async () => {
  const run = await diagram('reciprocal-function'), callbacks = {};
  let html = '';
  const svg = {getBoundingClientRect: () => ({left:0, width:360}), addEventListener:(name, fn) => callbacks[name] = fn, setPointerCapture() {}, hasPointerCapture:() => true};
  const layer = {set innerHTML(value) { html = value; }}, note = {};
  const root = {querySelector: selector => selector === '.rf-graph' ? svg : selector === '[data-rf-layer]' ? layer : selector === '[data-rf-note]' ? note : {textContent:''}, querySelectorAll:() => []};
  run('diagram').mount(root);
  const input = () => Number(html.match(/class="rf-point-label">\(([^,]+)/)[1]);
  callbacks.pointerdown({clientX:80, pointerId:1});assert.ok(input() < 0);
  callbacks.pointermove({clientX:280, pointerId:1});assert.ok(input() < 0);
  callbacks.pointerdown({clientX:280, pointerId:2});assert.ok(input() > 0);
  callbacks.pointermove({clientX:80, pointerId:2});assert.ok(input() > 0);
});

test('all draggable samples keep their point and coordinate label inside the SVG', async () => {
  const cases = [
    ['absolute-value-function', 'av', 230, Array.from({length:173}, (_, i) => -4.3 + i * .05).map(x => `layer(${x})`)],
    ['piecewise-function', 'pw', 230, Array.from({length:123}, (_, i) => -3.05 + i * .05).map(x => `layer(${x})`)],
    ['floor-function', 'fl', 230, Array.from({length:143}, (_, i) => -3.05 + i * .05).map(x => `layer(${x})`)],
    ['reciprocal-function', 'rf', 240, [-2,-1,1,2].flatMap(k => Array.from({length:209}, (_, i) => -5.2 + i * .05).map(x => `layer({k:${k}, x:sampleX(${k}, ${x})})`))],
  ];
  for (const [name, prefix, height, expressions] of cases) {
    const run = await diagram(name);
    for (const expression of expressions) {
      const html = run(expression);
      const [, px, py] = html.match(new RegExp(`<circle cx="([^"]+)" cy="([^"]+)" r="5.5" class="${prefix}-point"`));
      assert.ok(Number(px) >= 6 && Number(px) <= 354 && Number(py) >= 6 && Number(py) <= height - 6, `${name}: ${expression}`);
      const [, x, y, anchor, label] = html.match(new RegExp(`<text x="([^"]+)" y="([^"]+)"\\s+text-anchor="([^"]+)" class="${prefix}-point-label">([^<]+)`));
      // Digits and punctuation at 12px fit within this conservative 8px-per-character bound.
      const left = Number(x) - (anchor === 'end' ? label.length * 8 : 0), right = Number(x) + (anchor === 'start' ? label.length * 8 : 0);
      assert.ok(left >= 0 && right <= 360 && Number(y) >= 12 && Number(y) <= height - 3, `${name}: ${expression}: ${label}`);
    }
  }
});
