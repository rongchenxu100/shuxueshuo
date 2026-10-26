/* y = ⌊x⌋: step graph with closed left / open right endpoints; drag x. */
import {problemNote} from '../shared/html.js?v=1';

const BOUNDS = [-3.2, 4.2, -4.5, 4.5];
const plot = {left: 28, right: 332, top: 16, bottom: 210};
const sx = x => plot.left + (x - BOUNDS[0]) / (BOUNDS[1] - BOUNDS[0]) * (plot.right - plot.left);
const sy = y => plot.bottom - (y - BOUNDS[2]) / (BOUNDS[3] - BOUNDS[2]) * (plot.bottom - plot.top);
const fromSx = px => BOUNDS[0] + (px - plot.left) / (plot.right - plot.left) * (BOUNDS[1] - BOUNDS[0]);
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const fmt = v => {
  const n = Math.round(v * 100) / 100;
  return Object.is(n, -0) ? '0' : String(n);
};

function steps() {
  const parts = [];
  for (let n = Math.floor(BOUNDS[0]); n <= Math.floor(BOUNDS[1]); n += 1) {
    const x0 = Math.max(n, BOUNDS[0]);
    const x1 = Math.min(n + 1, BOUNDS[1]);
    if (x1 <= x0) continue;
    parts.push(`<path d="M${sx(x0).toFixed(1)} ${sy(n).toFixed(1)}H${sx(x1).toFixed(1)}" class="fl-step"/>`);
    if (x0 === n) parts.push(`<circle cx="${sx(x0).toFixed(1)}" cy="${sy(n).toFixed(1)}" r="3.6" class="fl-closed"/>`);
    if (n + 1 <= BOUNDS[1]) {
      parts.push(`<circle cx="${sx(n + 1).toFixed(1)}" cy="${sy(n).toFixed(1)}" r="3.6" class="fl-open"/>`);
    }
  }
  return parts.join('');
}

function layer(x) {
  // The displayed input is the actual sample, including near integer jumps.
  x = Number(fmt(x));
  const n = Math.floor(x);
  const labelRight = x < 0;
  return `${steps()}
    <path d="M${sx(x)} ${sy(0)}V${sy(n)}" class="fl-guide"/>
    <circle cx="${sx(x)}" cy="${sy(n)}" r="5.5" class="fl-point"/>
    <text x="${sx(x) + (labelRight ? 8 : -8)}" y="${sy(n) - 8}" text-anchor="${labelRight ? 'start' : 'end'}" class="fl-point-label">(${fmt(x)}, ${n})</text>
    <text data-fl-status-source hidden>⌊${fmt(x)}⌋ = ${n} · 区间 [${n}, ${n + 1})</text>`;
}

function figure() {
  const ticks = [-3, -2, -1, 1, 2, 3, 4];
  return `<svg class="fl-graph" viewBox="0 0 360 230" role="img" aria-labelledby="fl-graph-title">
    <title id="fl-graph-title">取整函数 y = ⌊x⌋</title>
    <rect x="${plot.left}" y="${plot.top}" width="${plot.right - plot.left}" height="${plot.bottom - plot.top}" rx="6" class="fl-plot"/>
    <path d="M${plot.left} ${sy(0)}H${plot.right}M${sx(0)} ${plot.top}V${plot.bottom}" class="fl-axis"/>
    <text x="${plot.right - 6}" y="${sy(0) - 8}" text-anchor="end" class="fl-axis-label">x</text>
    <text x="${sx(0) + 8}" y="${plot.top + 14}" class="fl-axis-label">y</text>
    ${ticks.map(t => `<text x="${sx(t).toFixed(1)}" y="${sy(0) + 16}" text-anchor="middle" class="fl-tick">${t}</text>
      <text x="${sx(0) - 8}" y="${(sy(t) + 4).toFixed(1)}" text-anchor="end" class="fl-tick">${t}</text>`).join('')}
    <g data-fl-layer></g>
  </svg>`;
}

const explorer = () => `<div class="fl-explorer">
  ${figure()}
  <p class="fl-status" aria-live="polite" data-fl-note></p>
</div>`;

export default {
  stylesheet: new URL('floor-function.css?v=1', import.meta.url).href,
  figure: explorer,
  render({tip}) {
    return `${tip?.note ? `<p class="fl-problem"><span class="fl-badge">本题</span><span data-math-text>${problemNote(tip.note)}</span></p>` : ''}
    ${explorer()}
    <p class="fl-foot">阶梯：左实右空；不跨跳跃连线。</p>`;
  },
  mount(root) {
    const svg = root.querySelector('.fl-graph');
    const state = {x: 1.7};
    const draw = () => {
      state.x = clamp(state.x, BOUNDS[0] + 0.15, BOUNDS[1] - 0.15);
      root.querySelector('[data-fl-layer]').innerHTML = layer(state.x);
      root.querySelector('[data-fl-note]').textContent = root.querySelector('[data-fl-status-source]').textContent;
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
