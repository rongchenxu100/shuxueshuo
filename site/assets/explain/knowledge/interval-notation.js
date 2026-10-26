/* Number-line intervals: open/closed endpoints and unbounded rays. */
import {problemNote} from '../shared/html.js?v=1';

const A = 1, B = 4;
const AXIS = {left: 36, right: 324, y: 78, min: -1.2, max: 6.2};
const px = v => AXIS.left + (v - AXIS.min) / (AXIS.max - AXIS.min) * (AXIS.right - AXIS.left);

const CASES = [
  {id: 'closed', label: '[a, b]', text: '[1, 4]', note: '闭区间：两端都取到', from: A, to: B, fromClosed: true, toClosed: true},
  {id: 'open', label: '(a, b)', text: '(1, 4)', note: '开区间：两端都不取', from: A, to: B, fromClosed: false, toClosed: false},
  {id: 'left', label: '[a, b)', text: '[1, 4)', note: '左闭右开', from: A, to: B, fromClosed: true, toClosed: false},
  {id: 'right', label: '(a, b]', text: '(1, 4]', note: '左开右闭', from: A, to: B, fromClosed: false, toClosed: true},
  {id: 'ray-right-closed', label: '[a, +∞)', text: '[1, +∞)', note: '无界：+∞ 侧只能用圆括号', from: A, to: Infinity, fromClosed: true, toClosed: false},
  {id: 'ray-right-open', label: '(a, +∞)', text: '(1, +∞)', note: '无界：右方延伸，不含端点', from: A, to: Infinity, fromClosed: false, toClosed: false},
  {id: 'ray-left-closed', label: '(−∞, b]', text: '(−∞, 4]', note: '无界：−∞ 侧只能用圆括号', from: -Infinity, to: B, fromClosed: false, toClosed: true},
  {id: 'ray-left-open', label: '(−∞, b)', text: '(−∞, 4)', note: '无界：左方延伸，不含端点', from: -Infinity, to: B, fromClosed: false, toClosed: false},
];

function endMark(x, closed) {
  return `<circle cx="${x}" cy="${AXIS.y}" r="5" class="iv-dot ${closed ? 'closed' : 'open'}"/>`;
}

function layer(c) {
  const x1 = Number.isFinite(c.from) ? px(c.from) : AXIS.left;
  const x2 = Number.isFinite(c.to) ? px(c.to) : AXIS.right;
  const leftEnd = Number.isFinite(c.from)
    ? endMark(x1, c.fromClosed)
    : `<path d="M${x1 - 9} ${AXIS.y}L${x1 + 2} ${AXIS.y - 6}V${AXIS.y + 6}Z" class="iv-arrow"/>`;
  const rightEnd = Number.isFinite(c.to)
    ? endMark(x2, c.toClosed)
    : `<path d="M${x2 + 9} ${AXIS.y}L${x2 - 2} ${AXIS.y - 6}V${AXIS.y + 6}Z" class="iv-arrow"/>`;
  const labels = [];
  if (Number.isFinite(c.from)) labels.push(`<text x="${x1}" y="${AXIS.y + 28}" text-anchor="middle" class="iv-end">a</text>`);
  if (Number.isFinite(c.to)) labels.push(`<text x="${x2}" y="${AXIS.y + 28}" text-anchor="middle" class="iv-end">b</text>`);
  return `<path d="M${x1} ${AXIS.y}H${x2}" class="iv-bar"/>
    ${leftEnd}${rightEnd}${labels.join('')}
    <text data-iv-status-source hidden>${c.text} · ${c.note}</text>`;
}

function figure() {
  const ticks = [0, 1, 2, 3, 4, 5];
  return `<svg class="iv-graph" viewBox="0 0 360 130" role="img" aria-labelledby="iv-graph-title">
    <title id="iv-graph-title">区间的数轴表示</title>
    <rect x="8" y="8" width="344" height="114" rx="8" class="iv-plot"/>
    <path d="M${AXIS.left - 8} ${AXIS.y}H${AXIS.right + 8}" class="iv-axis"/>
    <path d="M${AXIS.right + 12} ${AXIS.y}L${AXIS.right + 2} ${AXIS.y - 5}V${AXIS.y + 5}Z" class="iv-axis-arrow"/>
    <text x="${AXIS.right + 16}" y="${AXIS.y + 4}" class="iv-tick">x</text>
    ${ticks.map(t => `<path d="M${px(t)} ${AXIS.y - 4}V${AXIS.y + 4}" class="iv-axis"/><text x="${px(t)}" y="${AXIS.y - 12}" text-anchor="middle" class="iv-tick">${t}</text>`).join('')}
    <g data-iv-layer></g>
  </svg>`;
}

const explorer = () => `<div class="iv-explorer">
  <div class="iv-switch" role="group" aria-label="区间类型">
    ${CASES.map((c, i) => `<button type="button" data-iv-case="${c.id}" aria-pressed="${i === 0}">${c.label}</button>`).join('')}
  </div>
  ${figure()}
  <p class="iv-status" aria-live="polite" data-iv-note></p>
</div>`;

export default {
  stylesheet: new URL('interval-notation.css?v=1', import.meta.url).href,
  figure: explorer,
  render({tip}) {
    return `${tip?.note ? `<p class="iv-problem"><span class="iv-badge">本题</span><span data-math-text>${problemNote(tip.note)}</span></p>` : ''}
    ${explorer()}
    <p class="iv-foot">实心取端点，空心不取；∞ 不是实数，旁侧只能用圆括号。</p>`;
  },
  mount(root) {
    const state = {id: 'closed'};
    const draw = () => {
      const c = CASES.find(item => item.id === state.id);
      root.querySelector('[data-iv-layer]').innerHTML = layer(c);
      root.querySelector('[data-iv-note]').textContent = root.querySelector('[data-iv-status-source]').textContent;
      for (const button of root.querySelectorAll('[data-iv-case]')) {
        button.setAttribute('aria-pressed', String(button.dataset.ivCase === state.id));
      }
    };
    for (const button of root.querySelectorAll('[data-iv-case]')) {
      button.addEventListener('click', () => {
        state.id = button.dataset.ivCase;
        draw();
      });
    }
    draw();
  },
};
