/* One piecewise example: f(x)=x+1 (x≤0), 1−x (x>0). */
import {problemNote} from '../shared/html.js?v=1';

const BOUNDS = [-3.2, 3.2, -2.6, 1.6];
const plot = {left: 28, right: 332, top: 16, bottom: 210};
const sx = x => plot.left + (x - BOUNDS[0]) / (BOUNDS[1] - BOUNDS[0]) * (plot.right - plot.left);
const sy = y => plot.bottom - (y - BOUNDS[2]) / (BOUNDS[3] - BOUNDS[2]) * (plot.bottom - plot.top);
const fromSx = px => BOUNDS[0] + (px - plot.left) / (plot.right - plot.left) * (BOUNDS[1] - BOUNDS[0]);
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const fmt = v => {
  const n = Math.round(v * 10) / 10;
  return Object.is(n, -0) ? '0' : String(n);
};
const f = x => (x <= 0 ? x + 1 : 1 - x);

function layer(x) {
  const y = f(x);
  const piece = x <= 0 ? '左段 y = x + 1' : '右段 y = 1 − x';
  const labelRight = Math.abs(x) > 1.5 ? x < 0 : x >= 0;
  return `<path d="M${sx(BOUNDS[0])} ${sy(BOUNDS[0] + 1)}L${sx(0)} ${sy(1)}" class="pw-curve left"/>
    <path d="M${sx(0)} ${sy(1)}L${sx(BOUNDS[1])} ${sy(1 - BOUNDS[1])}" class="pw-curve right"/>
    <circle cx="${sx(0)}" cy="${sy(1)}" r="4" class="pw-closed"/>
    <text x="${sx(-2.2)}" y="${sy(0.2)}" class="pw-caption">x ≤ 0</text>
    <text x="${sx(2.2)}" y="${sy(0.2)}" text-anchor="end" class="pw-caption">x &gt; 0</text>
    <path d="M${sx(x)} ${sy(0)}V${sy(y)}" class="pw-guide"/>
    <circle cx="${sx(x)}" cy="${sy(y)}" r="5.5" class="pw-point"/>
    <text x="${sx(x) + (labelRight ? 8 : -8)}" y="${sy(y) - 8}" text-anchor="${labelRight ? 'start' : 'end'}" class="pw-point-label">(${fmt(x)}, ${fmt(y)})</text>
    <text data-pw-status-source hidden>${piece}</text>`;
}

function figure() {
  const ticks = [-3, -2, -1, 1, 2, 3];
  return `<svg class="pw-graph" viewBox="0 0 360 230" role="img" aria-labelledby="pw-graph-title">
    <title id="pw-graph-title">分段函数示例</title>
    <rect x="${plot.left}" y="${plot.top}" width="${plot.right - plot.left}" height="${plot.bottom - plot.top}" rx="6" class="pw-plot"/>
    <path d="M${plot.left} ${sy(0)}H${plot.right}M${sx(0)} ${plot.top}V${plot.bottom}" class="pw-axis"/>
    <text x="${plot.right - 6}" y="${sy(0) - 8}" text-anchor="end" class="pw-axis-label">x</text>
    <text x="${sx(0) + 8}" y="${plot.top + 14}" class="pw-axis-label">y</text>
    ${ticks.map(t => `<text x="${sx(t).toFixed(1)}" y="${sy(0) + 16}" text-anchor="middle" class="pw-tick">${t}</text>`).join('')}
    ${[-2, -1, 1].map(t => `<text x="${sx(0) - 8}" y="${(sy(t) + 4).toFixed(1)}" text-anchor="end" class="pw-tick">${t}</text>`).join('')}
    <g data-pw-layer></g>
  </svg>`;
}

const explorer = () => `<div class="pw-explorer">
  <p class="pw-formula" data-math-text>$f(x)=\\begin{cases}x+1,&x\\le0\\\\1-x,&x&gt;0\\end{cases}$</p>
  ${figure()}
  <p class="pw-status" aria-live="polite" data-pw-note></p>
</div>`;

export default {
  stylesheet: new URL('piecewise-function.css?v=1', import.meta.url).href,
  figure: explorer,
  render({tip}) {
    return `${tip?.note ? `<p class="pw-problem"><span class="pw-badge">本题</span><span data-math-text>${problemNote(tip.note)}</span></p>` : ''}
    ${explorer()}
    <p class="pw-foot">两段合写仍是一个函数；分界点只归一段。</p>`;
  },
  mount(root) {
    const svg = root.querySelector('.pw-graph');
    const state = {x: -1.2};
    const draw = () => {
      state.x = clamp(state.x, BOUNDS[0] + 0.15, BOUNDS[1] - 0.15);
      root.querySelector('[data-pw-layer]').innerHTML = layer(state.x);
      root.querySelector('[data-pw-note]').textContent = root.querySelector('[data-pw-status-source]').textContent;
    };
    const move = clientX => {
      const box = svg.getBoundingClientRect();
      state.x = fromSx((clientX - box.left) / box.width * 360);
      draw();
    };
    svg.addEventListener('pointerdown', event => {
      move(event.clientX);
      svg.setPointerCapture(event.pointerId);
    });
    svg.addEventListener('pointermove', event => {
      if (svg.hasPointerCapture(event.pointerId)) move(event.clientX);
    });
    draw();
  },
};
