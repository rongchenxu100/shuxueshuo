/* Piecewise polyline y=f(x) on [-2,2]; section parts + full summary. */
import {problemNote} from '../shared/html.js?v=1';

const ORIGIN = [[-2, 0], [0, 2], [1, -1], [2, 0]];
const plot = {left: 36, right: 324, top: 18, bottom: 198};
const BOUNDS = [-3.4, 3.4, -2.6, 3.4];
const sx = x => plot.left + (x - BOUNDS[0]) / (BOUNDS[1] - BOUNDS[0]) * (plot.right - plot.left);
const sy = y => plot.bottom - (y - BOUNDS[2]) / (BOUNDS[3] - BOUNDS[2]) * (plot.bottom - plot.top);

function sortPts(pts) {
  return [...pts].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
}
const translateX = (pts, h) => pts.map(([x, y]) => [x - h, y]);
const translateY = (pts, k) => pts.map(([x, y]) => [x, y + k]);
const reflectX = pts => pts.map(([x, y]) => [x, -y]);
const reflectY = pts => sortPts(pts.map(([x, y]) => [-x, y]));
const reflectOrigin = pts => sortPts(pts.map(([x, y]) => [-x, -y]));

function absF(pts) {
  const out = [];
  for (let i = 0; i < pts.length - 1; i += 1) {
    const [x1, y1] = pts[i], [x2, y2] = pts[i + 1];
    out.push([x1, Math.abs(y1)]);
    if (y1 === 0 || y2 === 0 || y1 * y2 > 0) continue;
    const t = y1 / (y1 - y2);
    out.push([x1 + t * (x2 - x1), 0]);
  }
  out.push([pts.at(-1)[0], Math.abs(pts.at(-1)[1])]);
  return out;
}

function fAbs(pts) {
  const right = pts.filter(([x]) => x >= 0);
  const mirrored = right.filter(([x]) => x > 0).map(([x, y]) => [-x, y]);
  return sortPts([...mirrored, ...right]);
}

const ALL = [
  {id: 'origin', label: '原图', formula: 'y = f(x)', note: '定义域 [-2, 2] 上的折线', pts: () => ORIGIN, ghost: false, group: 'base'},
  {id: 'left', label: '左移 1', formula: 'y = f(x + 1)', note: '图像左移 1；定义域变为 [-3, 1]', pts: () => translateX(ORIGIN, 1), ghost: true, group: 'translation'},
  {id: 'right', label: '右移 1', formula: 'y = f(x − 1)', note: '图像右移 1；定义域变为 [-1, 3]', pts: () => translateX(ORIGIN, -1), ghost: true, group: 'translation'},
  {id: 'up', label: '上移 1', formula: 'y = f(x) + 1', note: '图像上移 1；定义域不变', pts: () => translateY(ORIGIN, 1), ghost: true, group: 'translation'},
  {id: 'down', label: '下移 1', formula: 'y = f(x) − 1', note: '图像下移 1；定义域不变', pts: () => translateY(ORIGIN, -1), ghost: true, group: 'translation'},
  {id: 'fx-neg', label: '关于 x 轴', formula: 'y = −f(x)', note: '关于 x 轴对称；定义域不变', pts: () => reflectX(ORIGIN), ghost: true, group: 'symmetry'},
  {id: 'f-neg-x', label: '关于 y 轴', formula: 'y = f(−x)', note: '关于 y 轴对称；定义域仍为 [-2, 2]', pts: () => reflectY(ORIGIN), ghost: true, group: 'symmetry'},
  {id: 'origin-sym', label: '关于原点', formula: 'y = −f(−x)', note: '关于原点对称', pts: () => reflectOrigin(ORIGIN), ghost: true, group: 'symmetry'},
  {id: 'abs-f', label: '|f(x)|', formula: 'y = |f(x)|', note: '留上翻下：x 轴下方翻到上方', pts: () => absF(ORIGIN), ghost: true, group: 'fold'},
  {id: 'f-abs', label: 'f(|x|)', formula: 'y = f(|x|)', note: '去左翻右：保留右侧，翻到左侧', pts: () => fAbs(ORIGIN), ghost: true, group: 'fold'},
];

const GROUPS = {
  all: ALL.map(c => c.id),
  translation: ['origin', 'left', 'right', 'up', 'down'],
  symmetry: ['origin', 'fx-neg', 'f-neg-x', 'origin-sym'],
  fold: ['origin', 'abs-f', 'f-abs'],
};

const pathOf = pts => pts.map(([x, y], i) => `${i ? 'L' : 'M'}${sx(x).toFixed(1)} ${sy(y).toFixed(1)}`).join(' ');
const dots = (pts, cls) => pts.map(([x, y]) => `<circle cx="${sx(x)}" cy="${sy(y)}" r="3.8" class="${cls}"/>`).join('');

function layer(c) {
  const pts = c.pts();
  const ghost = c.ghost
    ? `<path d="${pathOf(ORIGIN)}" class="ft-curve ghost"/>${dots(ORIGIN, 'ft-dot ghost')}`
    : '';
  return `${ghost}
    <path d="${pathOf(pts)}" class="ft-curve"/>
    ${dots(pts, 'ft-dot')}
    <text data-ft-status-source hidden>${c.formula} · ${c.note}</text>`;
}

function figure(group) {
  const id = `ft-title-${group}`;
  const ticks = [-3, -2, -1, 1, 2, 3];
  return `<svg class="ft-graph" viewBox="0 0 360 220" role="img" aria-labelledby="${id}">
    <title id="${id}">函数图像变换</title>
    <rect x="${plot.left}" y="${plot.top}" width="${plot.right - plot.left}" height="${plot.bottom - plot.top}" rx="6" class="ft-plot"/>
    <path d="M${plot.left} ${sy(0)}H${plot.right}M${sx(0)} ${plot.top}V${plot.bottom}" class="ft-axis"/>
    <text x="${plot.right - 6}" y="${sy(0) - 8}" text-anchor="end" class="ft-tick">x</text>
    <text x="${sx(0) + 8}" y="${plot.top + 14}" class="ft-tick">y</text>
    ${ticks.map(t => `<text x="${sx(t)}" y="${sy(0) + 16}" text-anchor="middle" class="ft-tick">${t}</text>`).join('')}
    ${[-2, -1, 1, 2, 3].map(t => `<text x="${sx(0) - 8}" y="${sy(t) + 4}" text-anchor="end" class="ft-tick">${t}</text>`).join('')}
    <g data-ft-layer></g>
  </svg>`;
}

function explorer(group) {
  const cases = GROUPS[group].map(id => ALL.find(c => c.id === id));
  const start = cases.find(c => c.id !== 'origin') || cases[0];
  return `<div class="ft-explorer" data-ft-group="${group}" data-ft-start="${start.id}">
  <div class="ft-switch" role="group" aria-label="变换类型">
    ${cases.map(c => `<button type="button" data-ft-case="${c.id}" aria-pressed="${c.id === start.id}">${c.label}</button>`).join('')}
  </div>
  ${figure(group)}
  <p class="ft-status" aria-live="polite" data-ft-note></p>
</div>`;
}

function mountExplorer(root) {
  const box = root.querySelector('.ft-explorer');
  const ids = [...box.querySelectorAll('[data-ft-case]')].map(b => b.dataset.ftCase);
  const cases = ids.map(id => ALL.find(c => c.id === id));
  const state = {id: box.dataset.ftStart || cases[0].id};
  const draw = () => {
    const c = cases.find(item => item.id === state.id);
    root.querySelector('[data-ft-layer]').innerHTML = layer(c);
    root.querySelector('[data-ft-note]').textContent = root.querySelector('[data-ft-status-source]').textContent;
    for (const button of root.querySelectorAll('[data-ft-case]')) {
      button.setAttribute('aria-pressed', String(button.dataset.ftCase === state.id));
    }
  };
  for (const button of root.querySelectorAll('[data-ft-case]')) {
    button.addEventListener('click', () => {
      state.id = button.dataset.ftCase;
      draw();
    });
  }
  draw();
}

const make = group => () => explorer(group);

export default {
  stylesheet: new URL('function-graph-transformations.css?v=1', import.meta.url).href,
  figure: make('all'),
  translation: make('translation'),
  symmetry: make('symmetry'),
  fold: make('fold'),
  render({tip}) {
    return `${tip?.note ? `<p class="ft-problem"><span class="ft-badge">本题</span><span data-math-text>${problemNote(tip.note)}</span></p>` : ''}
    ${explorer('all')}
    <p class="ft-foot">浅色为原图；变换后端点取舍随图像一起保留。</p>`;
  },
  mount: mountExplorer,
};
