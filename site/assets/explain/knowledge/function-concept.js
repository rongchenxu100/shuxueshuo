/* Mapping diagrams: every x in A has exactly one image in B. */
import {problemNote} from '../shared/html.js?v=1';

const CASES = [
  {
    id: 'map',
    label: '一对一',
    ok: true,
    note: '每个输入恰有一个输出 · 是函数',
    A: [1, 2, 3],
    B: [2, 3, 4, 5],
    edges: [[1, 2], [2, 3], [3, 4]],
  },
  {
    id: 'many',
    label: '多对一',
    ok: true,
    note: '多个输入可对应同一输出 · 是函数',
    A: [1, 2, 3],
    B: [2, 3, 4],
    edges: [[1, 2], [2, 3], [3, 3]],
  },
  {
    id: 'fork',
    label: '一对多',
    ok: false,
    note: '输入 1 对应两个输出 · 不是函数',
    A: [1, 2, 3],
    B: [2, 3, 4, 5],
    edges: [[1, 2], [1, 3], [2, 4], [3, 5]],
  },
];

const oval = (cx, cy, rx, ry) =>
  `M${cx - rx} ${cy} A${rx} ${ry} 0 1 0 ${cx + rx} ${cy} A${rx} ${ry} 0 1 0 ${cx - rx} ${cy}`;

function positions(values, cx, cy, rx) {
  const n = values.length;
  const span = Math.min(118, 28 * (n - 1));
  const top = cy - span / 2;
  return Object.fromEntries(values.map((v, i) => [v, {
    x: cx,
    y: n === 1 ? cy : top + span * i / (n - 1),
  }]));
}

function layer(c) {
  const left = positions(c.A, 88, 118, 52);
  const right = positions(c.B, 272, 118, 58);
  const dots = [
    ...c.A.map(v => `<circle cx="${left[v].x}" cy="${left[v].y}" r="11" class="fc-dot a"/><text x="${left[v].x}" y="${left[v].y + 4}" text-anchor="middle" class="fc-num">${v}</text>`),
    ...c.B.map(v => `<circle cx="${right[v].x}" cy="${right[v].y}" r="11" class="fc-dot b"/><text x="${right[v].x}" y="${right[v].y + 4}" text-anchor="middle" class="fc-num">${v}</text>`),
  ].join('');
  const arrows = c.edges.map(([from, to], i) => {
    const a = left[from], b = right[to];
    const warn = c.id === 'fork' && from === 1 && i < 2;
    return `<path d="M${a.x + 12} ${a.y} C${a.x + 56} ${a.y},${b.x - 56} ${b.y},${b.x - 12} ${b.y}" class="fc-edge${warn ? ' fc-edge-warn' : ''}" marker-end="url(#${warn ? 'fc-arrow-warn' : 'fc-arrow'})"/>`;
  }).join('');
  return `<path d="${oval(88, 118, 52, 92)}" class="fc-oval"/><path d="${oval(272, 118, 58, 100)}" class="fc-oval"/>
    <text x="88" y="28" text-anchor="middle" class="fc-set">A</text>
    <text x="272" y="28" text-anchor="middle" class="fc-set">B</text>
    ${arrows}${dots}
    <text data-fc-status-source hidden>${c.note}</text>`;
}

function figure() {
  return `<svg class="fc-graph" viewBox="0 0 360 236" role="img" aria-labelledby="fc-graph-title">
    <title id="fc-graph-title">集合 A 到 B 的对应关系</title>
    <defs>
      <marker id="fc-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
        <path d="M0 1.2L9 5L0 8.8Z" fill="#087f79"/>
      </marker>
      <marker id="fc-arrow-warn" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
        <path d="M0 1.2L9 5L0 8.8Z" fill="#c2410c"/>
      </marker>
    </defs>
    <rect x="8" y="8" width="344" height="220" rx="8" class="fc-plot"/>
    <g data-fc-layer></g>
  </svg>`;
}

const explorer = () => `<div class="fc-explorer">
  <div class="fc-switch" role="group" aria-label="对应关系类型">
    ${CASES.map((c, i) => `<button type="button" data-fc-case="${c.id}" aria-pressed="${i === 0}">${c.label}</button>`).join('')}
  </div>
  ${figure()}
  <p class="fc-status" aria-live="polite" data-fc-note></p>
</div>`;

export default {
  stylesheet: new URL('function-concept.css?v=1', import.meta.url).href,
  figure: explorer,
  render({tip}) {
    return `${tip?.note ? `<p class="fc-problem"><span class="fc-badge">本题</span><span data-math-text>${problemNote(tip.note)}</span></p>` : ''}
    ${explorer()}
    <p class="fc-foot">定义域中每个输入须恰有一个输出；多对一可以，一对多不行。</p>`;
  },
  mount(root) {
    const state = {id: 'map'};
    const draw = () => {
      const c = CASES.find(item => item.id === state.id);
      root.querySelector('[data-fc-layer]').innerHTML = layer(c);
      root.querySelector('[data-fc-note]').textContent = root.querySelector('[data-fc-status-source]').textContent;
      root.querySelector('[data-fc-note]').dataset.ok = String(c.ok);
      for (const button of root.querySelectorAll('[data-fc-case]')) {
        button.setAttribute('aria-pressed', String(button.dataset.fcCase === state.id));
      }
    };
    for (const button of root.querySelectorAll('[data-fc-case]')) {
      button.addEventListener('click', () => {
        state.id = button.dataset.fcCase;
        draw();
      });
    }
    draw();
  },
};
