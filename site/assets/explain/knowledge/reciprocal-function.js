/* y = k/x (k ≠ 0): two hyperbola branches; drag a point to keep xy = k. */
import {problemNote} from '../shared/html.js?v=1';

const KS = [2, 1, -1, -2];
const BOUNDS = [-5.2, 5.2, -5.2, 5.2];
const plot = {left: 28, right: 332, top: 16, bottom: 216};
const sx = x => plot.left + (x - BOUNDS[0]) / (BOUNDS[1] - BOUNDS[0]) * (plot.right - plot.left);
const sy = y => plot.bottom - (y - BOUNDS[2]) / (BOUNDS[3] - BOUNDS[2]) * (plot.bottom - plot.top);
const fromSx = px => BOUNDS[0] + (px - plot.left) / (plot.right - plot.left) * (BOUNDS[1] - BOUNDS[0]);
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const fmt = v => {
  const n = Math.round(v * 100) / 100;
  return Object.is(n, -0) ? '0' : String(n);
};

function path(k, from, to) {
  return Array.from({length: 97}, (_, i) => from + (to - from) * i / 96)
    .map((x, i) => `${i ? 'L' : 'M'}${sx(x).toFixed(1)} ${sy(k / x).toFixed(1)}`).join(' ');
}

function entry(k) {
  return Math.max(Math.abs(k) / BOUNDS[3], 0.28);
}

function sampleX(k, preferred) {
  const start = entry(k);
  return preferred > 0
    ? clamp(preferred, start, BOUNDS[1] - 0.35)
    : clamp(preferred, BOUNDS[0] + 0.35, -start);
}

function layer({k, x}) {
  const start = entry(k);
  const y = k / x;
  const sides = k > 0 ? '一、三象限' : '二、四象限';
  return `<g clip-path="url(#rf-clip)">
      <path d="${path(k, start, BOUNDS[1])}" class="rf-curve"/>
      <path d="${path(k, -start, BOUNDS[0])}" class="rf-curve"/>
    </g>
    <path d="M${sx(0)} ${sy(y)}H${sx(x)}V${sy(0)}" class="rf-rect"/>
    <circle cx="${sx(x)}" cy="${sy(y)}" r="5.5" class="rf-point"/>
    <text x="${sx(x) + (x > 0 ? -8 : 8)}" y="${clamp(sy(y) + (y > 0 ? -8 : 14), 16, 230)}"
      text-anchor="${x > 0 ? 'end' : 'start'}" class="rf-point-label">(${fmt(x)}, ${fmt(y)})</text>
    <text data-rf-status-source hidden>y = ${k}/x · ${sides} · xy = ${k}</text>`;
}

function figure() {
  const ticks = [-4, -2, 2, 4];
  return `<svg class="rf-graph" viewBox="0 0 360 240" role="img" aria-labelledby="rf-graph-title">
    <title id="rf-graph-title">反比例函数 y = k/x</title>
    <defs><clipPath id="rf-clip"><rect x="${plot.left}" y="${plot.top}" width="${plot.right - plot.left}" height="${plot.bottom - plot.top}"/></clipPath></defs>
    <rect x="${plot.left}" y="${plot.top}" width="${plot.right - plot.left}" height="${plot.bottom - plot.top}" rx="6" class="rf-plot"/>
    <path d="M${plot.left} ${sy(0)}H${plot.right}M${sx(0)} ${plot.top}V${plot.bottom}" class="rf-axis"/>
    <path d="M${sx(0)} ${plot.top}V${plot.bottom}" class="rf-asymptote"/>
    <path d="M${plot.left} ${sy(0)}H${plot.right}" class="rf-asymptote"/>
    <text x="${plot.right - 6}" y="${sy(0) - 8}" text-anchor="end" class="rf-axis-label">x</text>
    <text x="${sx(0) + 8}" y="${plot.top + 14}" class="rf-axis-label">y</text>
    ${ticks.map(t => `<text x="${sx(t).toFixed(1)}" y="${sy(0) + 16}" text-anchor="middle" class="rf-tick">${t}</text>
      <text x="${sx(0) - 8}" y="${(sy(t) + 4).toFixed(1)}" text-anchor="end" class="rf-tick">${t}</text>`).join('')}
    <g data-rf-layer></g>
  </svg>`;
}

const explorer = () => `<div class="rf-explorer">
  <div class="rf-switch" role="group" aria-label="k 的值">
    ${KS.map(k => `<button type="button" data-rf-k="${k}" aria-pressed="${k === 2}">k = ${k}</button>`).join('')}
  </div>
  ${figure()}
  <p class="rf-status" aria-live="polite" data-rf-note></p>
</div>`;

export default {
  stylesheet: new URL('reciprocal-function.css?v=2', import.meta.url).href,
  figure: explorer,
  render({tip}) {
    return `${tip?.note ? `<p class="rf-problem"><span class="rf-badge">本题</span><span data-math-text>${problemNote(tip.note)}</span></p>` : ''}
    ${explorer()}
    <p class="rf-foot" data-math-text>$xy=k$ 不变；两支不相连，不交坐标轴。</p>`;
  },
  mount(root) {
    const svg = root.querySelector('.rf-graph');
    const state = {k: 2, x: 2};
    const draw = () => {
      state.x = sampleX(state.k, state.x);
      root.querySelector('[data-rf-layer]').innerHTML = layer(state);
      for (const button of root.querySelectorAll('[data-rf-k]')) {
        button.setAttribute('aria-pressed', String(Number(button.dataset.rfK) === state.k));
      }
      root.querySelector('[data-rf-note]').textContent = root.querySelector('[data-rf-status-source]').textContent;
    };
    const move = (clientX, chooseBranch = false) => {
      const box = svg.getBoundingClientRect();
      const x = fromSx((clientX - box.left) / box.width * 360);
      const positive = chooseBranch && x !== 0 ? x > 0 : state.x >= 0;
      state.x = sampleX(state.k, positive ? Math.max(x, 0.01) : Math.min(x, -0.01));
      draw();
    };
    svg.addEventListener('pointerdown', event => {
      move(event.clientX, true);
      svg.setPointerCapture(event.pointerId);
    });
    svg.addEventListener('pointermove', event => {
      if (svg.hasPointerCapture(event.pointerId)) move(event.clientX);
    });
    for (const button of root.querySelectorAll('[data-rf-k]')) {
      button.addEventListener('click', () => {
        state.k = Number(button.dataset.rfK);
        state.x = sampleX(state.k, state.x >= 0 ? Math.max(Math.abs(state.k), 1) : -Math.max(Math.abs(state.k), 1));
        draw();
      });
    }
    draw();
  },
};
