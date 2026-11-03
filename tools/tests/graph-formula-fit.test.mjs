import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {gatheredRows, renderFittedFormula, fitFormulaLines, createFormulaFitter} from '../../site/assets/graph-walk/formula-fit.mjs';

const require = createRequire(import.meta.url);
const katex = require('../../site/assets/practice/vendor/katex-0.18.9/katex.min.js');
const rows = [String.raw`f(x)=\frac{-10^{\frac1x}+2\cdot10^x}{3}`,
  String.raw`f\left(\frac1x\right)=\frac{2\cdot10^{\frac1x}-10^x}{3}`,
  String.raw`2f(x)+f\left(\frac1x\right)=2\cdot\left(\frac{-10^{\frac1x}+2\cdot10^x}{3}\right)+\left(\frac{2\cdot10^{\frac1x}-10^x}{3}\right)`];

test('the photographed substitution keeps every row and renders each safely with KaTeX', () => {
  const source = String.raw`\displaystyle \begin{gathered}` + rows.join('\\\\') + String.raw`\end{gathered}`;
  assert.deepEqual(gatheredRows(source), rows.map(row => `\\displaystyle ${row}`));
  const node = {dataset: {}, ownerDocument: {createElement: () => ({})}, replaceChildren(...nodes) { this.children = nodes; }};
  renderFittedFormula(node, source, (line, value) => {
    line.value = value;
    const html = katex.renderToString(value.slice(1, -1), {throwOnError: true});
    assert.ok(html.includes('class="katex-base"'));
  });
  assert.equal(node.children.length, 3);
  assert.deepEqual(node.children.map(line => line.value.replace(/\\nobreak /g, '')),
    rows.map(row => `$\\displaystyle ${row}$`));
  assert.ok(node.children[2].value.includes('\\cdot\\nobreak \\left'), 'a coefficient stays with its following fraction');
});

test('nested cases, matrices and text groups keep their own line breaks and braces', () => {
  const nested = String.raw`\begin{cases}x^2,&x>0\\-x,&x\le0\end{cases}`;
  const text = String.raw`\text{集合 \{a,b\}}`;
  assert.deepEqual(gatheredRows(`\\begin{gathered}f(x)=${nested}\\\\${text}\\end{gathered}`),
    [`\\displaystyle f(x)=${nested}`, `\\displaystyle ${text}`]);
  for (const source of [String.raw`\begin{aligned}a&=b\\&=c\end{aligned}`,
    String.raw`\begin{gathered}a=b\\[6pt]b=c\end{gathered}`, String.raw`\frac{a+b}{c}`]) {
    assert.deepEqual(gatheredRows(source), [source]);
  }
});

function layoutFixture(width = 242) {
  const line = {dataset: {}, style: {fontSize: ''}};
  const document = {defaultView: {getComputedStyle: () => ({fontSize: '21px'})}};
  const scale = () => (parseFloat(line.style.fontSize) || 21) / 21;
  const math = {getBoundingClientRect: () => ({width: 300 * scale()}),
    children: [100, 190].map(width => ({classList: {contains: name => name === 'katex-base'},
      getBoundingClientRect: () => ({width: width * scale()})}))};
  line.querySelector = () => math;
  const node = {clientWidth: width, ownerDocument: document, querySelectorAll: () => [line]};
  return {line, math, node, document};
}

test('fit shrinks a modest overflow, wraps a long equation, and restores normal size in a wide card', () => {
  const {line, node} = layoutFixture();
  fitFormulaLines(node);
  assert.equal(line.dataset.wrap, 'false');
  assert.equal(line.style.fontSize, '16.8px');
  node.clientWidth = 182;
  fitFormulaLines(node);
  assert.equal(line.dataset.wrap, 'true');
  assert.ok(parseFloat(line.style.fontSize) >= 16, 'break at operators instead of shrinking the whole equation too far');
  assert.ok(190 * parseFloat(line.style.fontSize) / 21 <= 180);
  fitFormulaLines(node);
  assert.ok(parseFloat(line.style.fontSize) >= 16, 'repeated fitting does not compound the shrink');
  node.clientWidth = 402;
  fitFormulaLines(node);
  assert.equal(line.style.fontSize, '');
  assert.equal(line.dataset.wrap, 'false');
  node.clientWidth = 0;
  fitFormulaLines(node);
  assert.equal(line.style.fontSize, '', 'closed details must not collapse the font size');
});

test('observer refits opened and resized cards, reacts to fonts and releases removed nodes', async () => {
  const {node, document, line} = layoutFixture(0);
  const frames = new Map(), events = new Map(), observed = new Set();
  let nodes = [node], next = 0, resize;
  document.querySelectorAll = () => nodes;
  document.addEventListener = (type, callback) => events.set(type, callback);
  document.removeEventListener = type => events.delete(type);
  document.fonts = {ready: Promise.resolve(), addEventListener: document.addEventListener,
    removeEventListener: document.removeEventListener};
  Object.assign(document.defaultView, {addEventListener: document.addEventListener,
    removeEventListener: document.removeEventListener,
    requestAnimationFrame: callback => { frames.set(++next, callback); return next; },
    cancelAnimationFrame: id => frames.delete(id),
    ResizeObserver: class {
      constructor(callback) { resize = callback; }
      observe(target) { observed.add(target); }
      unobserve(target) { observed.delete(target); }
      disconnect() { observed.clear(); }
    }});
  const flush = () => { const callbacks = [...frames.values()]; frames.clear(); callbacks.forEach(callback => callback()); };
  const fitter = createFormulaFitter(document);
  fitter.refresh(); fitter.refresh();
  assert.equal(frames.size, 1);
  flush();
  assert.equal(line.style.fontSize, '');
  node.clientWidth = 242;
  resize([{target: node}]); flush();
  assert.equal(line.style.fontSize, '16.8px');
  resize([{target: node}]);
  assert.equal(frames.size, 0, 'height changes do not create a resize loop');
  await document.fonts.ready; flush();
  assert.equal(line.style.fontSize, '16.8px');
  node.clientWidth = 402;
  events.get('toggle')(); flush();
  assert.equal(line.style.fontSize, '');
  nodes = []; fitter.refresh(); flush();
  assert.equal(observed.size, 0);
  fitter.refresh(); fitter.dispose();
  assert.equal(frames.size, 0);
  assert.equal(events.size, 0);
});
