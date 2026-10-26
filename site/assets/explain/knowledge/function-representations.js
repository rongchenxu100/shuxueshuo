/* Same function f(x)=x² on {-2,-1,0,1,2}: analytic / table / graph. */
import {problemNote} from '../shared/html.js?v=1';
import {renderLearningMath} from '../../knowledge-next/learning-model.mjs';

const XS = [-2, -1, 0, 1, 2];
const f = x => x * x;
const PAIRS = XS.map(x => [x, f(x)]);

const plot = {left: 48, right: 312, top: 20, bottom: 188};
const BOUNDS = [-2.6, 2.6, -0.5, 4.6];
const sx = x => plot.left + (x - BOUNDS[0]) / (BOUNDS[1] - BOUNDS[0]) * (plot.right - plot.left);
const sy = y => plot.bottom - (y - BOUNDS[2]) / (BOUNDS[3] - BOUNDS[2]) * (plot.bottom - plot.top);

const VIEWS = [
  {
    id: 'analytic',
    label: '解析法',
    note: '表达式 + 定义域，便于计算与推导',
    body: () => `<div class="fr-panel fr-analytic">
      <p class="fr-formula" data-math-text>$f(x)=x^{2}$</p>
      <p class="fr-domain" data-math-text>定义域 $D=\\{-2,-1,0,1,2\\}$</p>
      <p class="fr-hint">写出对应规则，并写清允许输入。</p>
    </div>`,
  },
  {
    id: 'table',
    label: '列表法',
    note: '有限定义域可完整列出；查值方便',
    body: () => `<div class="fr-panel fr-table-wrap">
      <table class="fr-table">
        <thead><tr><th scope="col">x</th>${XS.map(x => `<th scope="col">${x}</th>`).join('')}</tr></thead>
        <tbody><tr><th scope="row">f(x)</th>${PAIRS.map(([, y]) => `<td>${y}</td>`).join('')}</tr></tbody>
      </table>
      <p class="fr-hint">本表列完了全部允许输入。</p>
    </div>`,
  },
  {
    id: 'graph',
    label: '图像法',
    note: '有限定义域只画离散点，不连成连续曲线',
    body: () => {
      const ticksX = [-2, -1, 1, 2];
      const ticksY = [1, 2, 3, 4];
      const points = PAIRS.map(([x, y]) =>
        `<circle cx="${sx(x)}" cy="${sy(y)}" r="5" class="fr-point"/><text x="${sx(x)}" y="${sy(y) - 10}" text-anchor="middle" class="fr-point-label">(${x},${y})</text>`
      ).join('');
      return `<div class="fr-panel">
        <svg class="fr-graph" viewBox="0 0 360 210" role="img" aria-label="五点图像">
          <rect x="${plot.left}" y="${plot.top}" width="${plot.right - plot.left}" height="${plot.bottom - plot.top}" rx="6" class="fr-plot"/>
          <path d="M${plot.left} ${sy(0)}H${plot.right}M${sx(0)} ${plot.top}V${plot.bottom}" class="fr-axis"/>
          <text x="${plot.right - 6}" y="${sy(0) - 8}" text-anchor="end" class="fr-tick">x</text>
          <text x="${sx(0) + 8}" y="${plot.top + 14}" class="fr-tick">y</text>
          ${ticksX.map(t => `<text x="${sx(t)}" y="${sy(0) + 16}" text-anchor="middle" class="fr-tick">${t}</text>`).join('')}
          ${ticksY.map(t => `<text x="${sx(0) - 8}" y="${sy(t) + 4}" text-anchor="end" class="fr-tick">${t}</text>`).join('')}
          ${points}
        </svg>
        <p class="fr-hint">只画定义域里的点，不要连成抛物线。</p>
      </div>`;
    },
  },
];

const explorer = () => `<div class="fr-explorer">
  <div class="fr-switch" role="group" aria-label="表示法">
    ${VIEWS.map((v, i) => `<button type="button" data-fr-view="${v.id}" aria-pressed="${i === 0}">${v.label}</button>`).join('')}
  </div>
  <div data-fr-body></div>
  <p class="fr-status" aria-live="polite" data-fr-note></p>
</div>`;

export default {
  stylesheet: new URL('function-representations.css?v=1', import.meta.url).href,
  figure: explorer,
  render({tip}) {
    return `${tip?.note ? `<p class="fr-problem"><span class="fr-badge">本题</span><span data-math-text>${problemNote(tip.note)}</span></p>` : ''}
    ${explorer()}
    <p class="fr-foot" data-math-text>同一函数 $f(x)=x^{2}$（$x\\in\\{-2,-1,0,1,2\\}$）的三种写法。</p>`;
  },
  mount(root) {
    const state = {id: 'analytic'};
    const draw = () => {
      const view = VIEWS.find(v => v.id === state.id);
      root.querySelector('[data-fr-body]').innerHTML = view.body();
      root.querySelector('[data-fr-note]').textContent = view.note;
      for (const button of root.querySelectorAll('[data-fr-view]')) {
        button.setAttribute('aria-pressed', String(button.dataset.frView === state.id));
      }
      renderLearningMath(root).catch(() => {});
    };
    for (const button of root.querySelectorAll('[data-fr-view]')) {
      button.addEventListener('click', () => {
        state.id = button.dataset.frView;
        draw();
      });
    }
    draw();
  },
};
