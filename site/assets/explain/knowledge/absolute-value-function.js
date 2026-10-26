/* y = |x|: V-shaped graph with a draggable point. */
import {problemNote} from '../shared/html.js?v=1';

const BOUNDS = [-4.5, 4.5, -0.6, 4.5];
const plot = {left: 28, right: 332, top: 16, bottom: 210};
const sx = x => plot.left + (x - BOUNDS[0]) / (BOUNDS[1] - BOUNDS[0]) * (plot.right - plot.left);
const sy = y => plot.bottom - (y - BOUNDS[2]) / (BOUNDS[3] - BOUNDS[2]) * (plot.bottom - plot.top);
const fromSx = px => BOUNDS[0] + (px - plot.left) / (plot.right - plot.left) * (BOUNDS[1] - BOUNDS[0]);
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const fmt = v => {
  const n = Math.round(v * 10) / 10;
  return Object.is(n, -0) ? '0' : String(n);
};

function layer(x) {
  const y = Math.abs(x);
  const rule = x >= 0 ? '|x| = x' : '|x| = −x';
  return `<path d="M${sx(BOUNDS[0])} ${sy(-BOUNDS[0])}L${sx(0)} ${sy(0)}L${sx(BOUNDS[1])} ${sy(BOUNDS[1])}" class="av-curve"/>
    <path d="M${sx(0)} ${sy(y)}H${sx(x)}V${sy(0)}" class="av-guide"/>
    <circle cx="${sx(x)}" cy="${sy(y)}" r="5.5" class="av-point"/>
    <text x="${sx(x) + (x >= 0 ? -8 : 8)}" y="${sy(y) - 8}" text-anchor="${x >= 0 ? 'end' : 'start'}" class="av-point-label">(${fmt(x)}, ${fmt(y)})</text>
    <text data-av-status-source hidden>${rule} · 值域 [0, +∞)</text>`;
}

function figure() {
  const ticks = [-4, -2, 2, 4];
  return `<svg class="av-graph" viewBox="0 0 360 230" role="img" aria-labelledby="av-graph-title">
    <title id="av-graph-title">绝对值函数 y = |x|</title>
    <rect x="${plot.left}" y="${plot.top}" width="${plot.right - plot.left}" height="${plot.bottom - plot.top}" rx="6" class="av-plot"/>
    <path d="M${plot.left} ${sy(0)}H${plot.right}M${sx(0)} ${plot.top}V${plot.bottom}" class="av-axis"/>
    <text x="${plot.right - 6}" y="${sy(0) - 8}" text-anchor="end" class="av-axis-label">x</text>
    <text x="${sx(0) + 8}" y="${plot.top + 14}" class="av-axis-label">y</text>
    ${ticks.map(t => `<text x="${sx(t).toFixed(1)}" y="${sy(0) + 16}" text-anchor="middle" class="av-tick">${t}</text>`).join('')}
    ${[1, 2, 3, 4].map(t => `<text x="${sx(0) - 8}" y="${(sy(t) + 4).toFixed(1)}" text-anchor="end" class="av-tick">${t}</text>`).join('')}
    <g data-av-layer></g>
  </svg>`;
}

const explorer = () => `<div class="av-explorer">
  ${figure()}
  <p class="av-status" aria-live="polite" data-av-note></p>
</div>`;

export default {
  stylesheet: new URL('absolute-value-function.css?v=1', import.meta.url).href,
  figure: explorer,
  render({tip}) {
    return `${tip?.note ? `<p class="av-problem"><span class="av-badge">本题</span><span data-math-text>${problemNote(tip.note)}</span></p>` : ''}
    ${explorer()}
    <p class="av-foot" data-math-text>$y=|x|$：V 形，关于 $y$ 轴对称。</p>`;
  },
  mount(root) {
    const svg = root.querySelector('.av-graph');
    const state = {x: 2};
    const draw = () => {
      state.x = clamp(state.x, BOUNDS[0] + 0.2, BOUNDS[1] - 0.2);
      root.querySelector('[data-av-layer]').innerHTML = layer(state.x);
      root.querySelector('[data-av-note]').textContent = root.querySelector('[data-av-status-source]').textContent;
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
