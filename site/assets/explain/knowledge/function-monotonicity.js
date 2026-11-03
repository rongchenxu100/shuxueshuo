/* Monotonicity passed along a chain: x → u = x² − x → h = 1/u, shown as three linked number lines. Purely local. */
import {escapeHtml as escape, problemNote} from '../shared/html.js?v=1';
import {fracLabel} from '../shared/svg-frac.js?v=2';

const X = {min: 2, max: 3, step: 0.05, value: 2.4};
const LEFT = 104, RIGHT = 330;
const ROWS = [
  {key: 'x', y: 34, name: 'x', domain: [1.85, 3.15], span: [2, 3], ticks: [[2, '2'], [3, '3']], trend: 'x 增大 →', value: x => x},
  {key: 'u', y: 112, name: 'u = x² − x', domain: [1.4, 6.6], span: [2, 6], ticks: [[2, '2'], [6, '6']], trend: 'u 增大 →', value: x => x * x - x},
  {key: 'h', y: 190, name: ['h = ', ['1', 'u']], domain: [0.12, 0.55], span: [1 / 6, 1 / 2], ticks: [[1 / 6, [['1', '6']]], [1 / 2, [['1', '2']]]], trend: '← h 减小', value: x => 1 / (x * x - x)},
];
const at = (row, v) => LEFT + (v - row.domain[0]) / (row.domain[1] - row.domain[0]) * (RIGHT - LEFT);

function layer(x) {
  const points = ROWS.map(row => ({row, v: row.value(x), start: row.value(X.min)}));
  const trails = points.map(({row, v, start}) => `<path d="M${at(row, start)} ${row.y}H${at(row, v)}" class="fm-trail"/>`).join('');
  const links = points.slice(1).map(({row, v}, i) => {
    const prev = points[i];
    return `<path d="M${at(prev.row, prev.v)} ${prev.row.y + 7}L${at(row, v)} ${row.y - 7}" class="fm-connector"/>`;
  }).join('');
  const dots = points.map(({row, v}) => `<circle cx="${at(row, v)}" cy="${row.y}" r="6.5" class="fm-dot"/>`).join('');
  return trails + links + dots;
}

function figure() {
  const rows = ROWS.map(row => `${Array.isArray(row.name) ? fracLabel(8, row.y + 4, 'start', row.name, {cls: 'fm-name'}) : `<text x="8" y="${row.y + 4}" class="fm-name">${row.name}</text>`}
    <path d="M${LEFT - 6} ${row.y}H${RIGHT + 6}" class="fm-line"/>
    <path d="M${at(row, row.span[0])} ${row.y}H${at(row, row.span[1])}" class="fm-span"/>
    ${row.ticks.map(([v, text]) => `<path d="M${at(row, v)} ${row.y - 5}V${row.y + 5}" class="fm-tick"/>${Array.isArray(text) ? fracLabel(at(row, v), row.y + 23, 'middle', text, {size: 12.5, cls: 'fm-tick-label'}) : `<text x="${at(row, v)}" y="${row.y + 21}" text-anchor="middle" class="fm-tick-label">${text}</text>`}`).join('')}
    <text x="8" y="${row.y + 22}" class="fm-trend ${row.key === 'h' ? 'down' : 'up'}">${row.trend}</text>`).join('');
  return `<svg class="fm-graph" viewBox="0 0 340 222" role="img" aria-labelledby="fm-graph-title">
    <title id="fm-graph-title">三条数轴：x 在 2 到 3 之间移动时，u = x² − x 跟着增大，h = 1/u 跟着减小</title>
    ${rows}
    <g data-fm-layer></g>
  </svg>`;
}

const RULES = [
  ['$f$、$g$ 在区间上都递增', '$f+g$ 递增'],
  ['$f$ 递增', '$-f$ 递减；$c&gt;0$ 时 $cf$ 递增'],
  ['$f$ 递增，且恒正或恒负', '$\\frac1f$ 递减'],
  ['$u=g(x)$ 递增，$y=F(u)$ 递减', '$y=F(g(x))$ 递减（同增异减）'],
];

const explorer = () => `<div class="fm-explorer">
      <p class="fm-ask" data-math-text>例：$h(x)=\\frac1{x^2-x}$，$x\\in[2,3]$。拖动 $x$，看 $u=x^2-x$ 和 $h=\\frac1u$ 怎样跟着走。</p>
      ${figure()}
      <input class="fm-slider" type="range" data-fm-slider min="${X.min}" max="${X.max}" step="${X.step}" value="${X.value}" aria-label="x 的值">
      <p class="fm-readout" aria-live="polite" data-fm-readout></p>
      <p class="fm-result" data-math-text>$x$ 从 $2$ 走到 $3$，$u$ 从 $2$ 增大到 $6$，都是正数，$h$ 从 $\\frac12$ 减小到 $\\frac16$：$h(x)$ 在 $[2,3]$ 上递减，最小值 $h(3)=\\frac16$，最大值 $h(2)=\\frac12$。</p>
    </div>`;

export default {
  stylesheet: new URL('function-monotonicity.css?v=1', import.meta.url).href,

  figure: explorer,

  render({tip}) {
    return `<p class="fm-core" data-math-text>在区间上任取 $x_1&lt;x_2$，都有 $f(x_1)&lt;f(x_2)$，$f(x)$ 就在这个区间上递增（都有 $f(x_1)&gt;f(x_2)$ 则递减）。递增函数在 $[p,q]$ 上的最小值是 $f(p)$、最大值是 $f(q)$，递减时反过来。</p>
    ${tip?.note ? `<p class="fm-problem"><span class="fm-badge">本题</span><span data-math-text>${problemNote(tip.note)}</span></p>` : ''}
    ${explorer()}
    <table class="fm-table">
      <caption>由已知函数推出单调性</caption>
      <thead><tr><th scope="col">已知</th><th scope="col">结论</th></tr></thead>
      <tbody>${RULES.map(([known, result]) => `<tr><td data-math-text>${known}</td><td data-math-text>${result}</td></tr>`).join('')}</tbody>
    </table>
    <div class="fm-notes">
      <section class="fm-note">
        <h3>单调要说清在哪个区间</h3>
        <p data-math-text>$\\frac1x$ 在 $(-\\infty,0)$ 和 $(0,+\\infty)$ 上分别递减，但不能说在定义域上递减：$-1&lt;1$，而 $\\frac1{-1}&lt;\\frac11$。</p>
      </section>
      <section class="fm-note">
        <h3>开区间：最值可能取不到</h3>
        <p data-math-text>严格单调函数在开区间上没有最大值、最小值。例如 $x+\\frac4x$ 在 $(1,2)$ 上递减，取值范围是 $(4,5)$。这不适用于常函数或区间内有转折的函数。</p>
        <p>见 <button type="button" class="fm-link" data-explain-open="endpoint-attainability"></button>。</p>
      </section>
      <section class="fm-note">
        <h3>取倒数为什么变向</h3>
        <p data-math-text>同号的两个数取倒数，大小顺序颠倒；所以恒正（或恒负）的递增函数取倒数后递减。</p>
        <p>见 <button type="button" class="fm-link" data-explain-open="inequality-properties"></button>。</p>
      </section>
    </div>`;
  },

  mount(root) {
    const slider = root.querySelector('[data-fm-slider]');
    const draw = () => {
      const x = Number(slider.value);
      root.querySelector('[data-fm-layer]').innerHTML = layer(x);
      const u = x * x - x, h = 1 / u;
      root.querySelector('[data-fm-readout]').textContent = `x = ${x.toFixed(2)}　→　u = ${u.toFixed(2)}　→　h ≈ ${h.toFixed(3)}`;
    };
    slider.addEventListener('input', draw);
    draw();
  },
};
