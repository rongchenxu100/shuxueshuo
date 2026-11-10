/* Abstract-function monotonicity: where the substituted input t lands relative to the sign condition.
   No graph of f is drawn; a graph would presuppose a formula the problem never gives. */

const W = 360, LEFT = 40, RIGHT = 320;
const FAMILIES = {
  additive: {
    label: '加法型',
    relation: 'f(x+y)=f(x)+f(y)',
    rule: 'x>0 时 f(x)>0',
    x: {min: -3, max: 3, ticks: [-3, -2, -1, 0, 1, 2, 3]},
    t: {min: -6, max: 6, ticks: [-6, -4, -2, 0, 2, 4, 6], floor: 0},
    start: [-1, 1.5],
    key: (a, b) => b - a,
    keyText: 'x₂−x₁',
    instance: 'f(x₂)=f(x₁)+f(x₂−x₁)',
    scope: 'x>0',
  },
  multiplicative: {
    label: '乘法型',
    relation: 'f(xy)=f(x)+f(y)',
    rule: 'x>1 时 f(x)>0',
    x: {min: 0, max: 4, ticks: [0, 1, 2, 3, 4], lowest: 0.5},
    t: {min: 0, max: 8, ticks: [0, 1, 2, 4, 6, 8], floor: 1},
    start: [1, 2.5],
    key: (a, b) => b / a,
    keyText: 'x₂/x₁',
    instance: 'f(x₂)=f(x₁)+f(x₂/x₁)',
    scope: 'x>1',
  },
};

const scale = axis => v => LEFT + (v - axis.min) / (axis.max - axis.min) * (RIGHT - LEFT);
// Close points push their labels apart instead of overlapping.
const anchors = (pa, pb) => Math.abs(pa - pb) >= 48 ? ['middle', 'middle'] : pa <= pb ? ['end', 'start'] : ['start', 'end'];
const fmt = v => {
  const r = Math.round(v * 100) / 100;
  return (Object.is(r, -0) ? 0 : r).toString().replace('-', '−');
};

function axisLine(axis, y, name) {
  const px = scale(axis);
  return `<path d="M${LEFT - 8} ${y}H${RIGHT + 8}" class="am-axis"/>
    <path d="M${RIGHT + 12} ${y}L${RIGHT + 2} ${y - 5}V${y + 5}Z" class="am-axis-arrow"/>
    <text x="${RIGHT + 16}" y="${y + 4}" class="am-name">${name}</text>
    ${axis.ticks.map(t => `<path d="M${px(t)} ${y - 4}V${y + 4}" class="am-axis"/><text x="${px(t)}" y="${y + 18}" text-anchor="middle" class="am-tick">${fmt(t)}</text>`).join('')}`;
}

function figure(family) {
  const f = FAMILIES[family], px = scale(f.x), pt = scale(f.t);
  const band = pt(f.t.floor), [a, b] = f.start, tone = comparisonState(family, a, b).tone, [la, lb] = anchors(px(a), px(b));
  return `<svg class="am-graph" viewBox="0 0 ${W} 196" role="img" aria-labelledby="am-graph-title">
    <title id="am-graph-title">任取两点后，代入的输入是否落在符号条件的范围内</title>
    <rect x="8" y="8" width="${W - 16}" height="180" rx="8" class="am-plot"/>
    <text x="20" y="30" class="am-caption">任取两点</text>
    ${family === 'multiplicative' ? `<rect x="${LEFT}" y="44" width="${px(0) - LEFT}" height="28" class="am-outside"/>` : ''}
    ${axisLine(f.x, 58, 'x')}
    <path data-am-gap d="M${px(a)} 58H${px(b)}" data-tone="${tone}" class="am-gap"/>
    <circle data-am-point="0" r="8" cx="${px(a)}" cy="58" class="am-dot am-dot-1"/>
    <circle data-am-point="1" r="8" cx="${px(b)}" cy="58" class="am-dot am-dot-2"/>
    <text data-am-label="0" x="${px(a)}" y="40" text-anchor="${la}" class="am-point-label">x₁=${fmt(a)}</text>
    <text data-am-label="1" x="${px(b)}" y="40" text-anchor="${lb}" class="am-point-label">x₂=${fmt(b)}</text>
    <text x="20" y="114" class="am-caption">代入的输入 t=${f.keyText}</text>
    <rect x="${band}" y="124" width="${RIGHT - band}" height="28" rx="4" class="am-band"/>
    <text x="${RIGHT - 4}" y="120" text-anchor="end" class="am-band-label">符号条件管的范围 ${f.scope.replace('x', 't')}</text>
    ${axisLine(f.t, 138, 't')}
    <circle data-am-key r="7" cx="${pt(f.key(a, b))}" cy="138" data-tone="${tone}" class="am-key"/>
  </svg>`;
}

const slider = (family, i) => {
  const f = FAMILIES[family];
  return `<input type="range" data-am-slider="${i}" min="${f.x.lowest ?? f.x.min}" max="${f.x.max}" step="0.1" value="${f.start[i]}">`;
};

const explorer = family => `<div class="am-explorer" data-am-family="${family}">
  <div class="am-switch" role="group" aria-label="函数关系的类型">
    ${Object.entries(FAMILIES).map(([id, f]) => `<button type="button" data-am-case="${id}" aria-pressed="${id === family}">${f.label}<small>${f.relation}</small></button>`).join('')}
  </div>
  <p class="am-given" data-am-given>已知 ${FAMILIES[family].relation}，${FAMILIES[family].rule}</p>
  <div data-am-figure>${figure(family)}</div>
  <div class="am-sliders">
    <label>x₁ ${slider(family, 0)}</label>
    <label>x₂ ${slider(family, 1)}</label>
  </div>
  <p class="am-status" aria-live="polite" data-am-status data-tone="${comparisonState(family, ...FAMILIES[family].start).tone}">${comparisonState(family, ...FAMILIES[family].start).text}</p>
</div>`;

export function comparisonState(family, a, b) {
  const f = FAMILIES[family];
  if (Math.abs(a - b) < 1e-9) return {tone: 'idle', text: '两点重合，差为 0，比较不出增减。拖开它们。'};
  const t = f.key(a, b), inside = t > f.t.floor + 1e-9;
  const rounded = Math.abs(t - Math.round(t * 100) / 100) > 1e-9;
  const head = `${f.keyText}${rounded ? '≈' : '='}${fmt(t)}`;
  if (!inside) {
    return {tone: 'bad', text: `${head}，不在 ${f.scope.replace('x', 't')} 里，符号条件用不上。取点时要先排好 x₁<x₂。`};
  }
  return {tone: 'ok', text: `${head}，落在 ${f.scope.replace('x', 't')} 里。由 ${f.instance}，得 f(x₂)−f(x₁)=f(${f.keyText})>0，所以 f(x₁)<f(x₂)。`};
}

export default {
  stylesheet: new URL('abstract-monotonicity.css?v=1', import.meta.url).href,
  figure: () => explorer('additive'),
  render: () => explorer('additive'),
  mount(root) {
    const state = {family: 'additive', values: [...FAMILIES.additive.start]};
    let drag = null;
    const bounds = f => [f.x.lowest ?? f.x.min, f.x.max];
    const svg = () => root.querySelector('.am-graph');
    const draw = () => {
      const f = FAMILIES[state.family], px = scale(f.x), pt = scale(f.t);
      const [a, b] = state.values, side = anchors(px(a), px(b));
      state.values.forEach((v, i) => {
        root.querySelector(`[data-am-point="${i}"]`).setAttribute('cx', px(v));
        const label = root.querySelector(`[data-am-label="${i}"]`);
        label.setAttribute('x', px(v));
        label.setAttribute('text-anchor', side[i]);
        label.textContent = `${i ? 'x₂' : 'x₁'}=${fmt(v)}`;
        const slider = root.querySelector(`[data-am-slider="${i}"]`);
        slider.value = v;
      });
      root.querySelector('[data-am-gap]').setAttribute('d', `M${px(a)} 58H${px(b)}`);
      const t = f.key(a, b), key = root.querySelector('[data-am-key]');
      const shown = Math.min(Math.max(t, f.t.min), f.t.max);
      key.setAttribute('cx', pt(shown));
      const result = comparisonState(state.family, a, b);
      key.dataset.tone = result.tone;
      root.querySelector('[data-am-gap]').dataset.tone = result.tone;
      const status = root.querySelector('[data-am-status]');
      status.textContent = result.text;
      status.dataset.tone = result.tone;
    };
    const setFamily = family => {
      const f = FAMILIES[family];
      state.family = family;
      state.values = [...f.start];
      root.querySelector('[data-am-figure]').innerHTML = figure(family);
      root.querySelector('[data-am-given]').textContent = `已知 ${f.relation}，${f.rule}`;
      const [lo, hi] = bounds(f);
      root.querySelectorAll('[data-am-slider]').forEach(s => { s.min = lo; s.max = hi; });
      root.querySelectorAll('[data-am-case]').forEach(btn => btn.setAttribute('aria-pressed', String(btn.dataset.amCase === family)));
      draw();
    };
    const toValue = event => {
      const f = FAMILIES[state.family], box = svg();
      const point = box.createSVGPoint();
      point.x = event.clientX; point.y = event.clientY;
      const x = point.matrixTransform(box.getScreenCTM().inverse()).x;
      const [lo, hi] = bounds(f);
      const v = f.x.min + (x - LEFT) / (RIGHT - LEFT) * (f.x.max - f.x.min);
      return Math.round(Math.min(Math.max(v, lo), hi) * 10) / 10;
    };
    const onDown = event => {
      const target = event.target.closest('[data-am-point]');
      if (!target) return;
      drag = Number(target.dataset.amPoint);
      target.setPointerCapture?.(event.pointerId);
      event.preventDefault();
    };
    const onMove = event => {
      if (drag === null) return;
      state.values[drag] = toValue(event);
      draw();
    };
    const onUp = () => { drag = null; };
    root.addEventListener('pointerdown', onDown);
    root.addEventListener('pointermove', onMove);
    root.addEventListener('pointerup', onUp);
    root.addEventListener('pointercancel', onUp);
    root.querySelectorAll('[data-am-slider]').forEach(slider => slider.addEventListener('input', () => {
      state.values[Number(slider.dataset.amSlider)] = Number(slider.value);
      draw();
    }));
    root.querySelectorAll('[data-am-case]').forEach(btn => btn.addEventListener('click', () => setFamily(btn.dataset.amCase)));
    setFamily('additive');
    return () => {
      root.removeEventListener('pointerdown', onDown);
      root.removeEventListener('pointermove', onMove);
      root.removeEventListener('pointerup', onUp);
      root.removeEventListener('pointercancel', onUp);
    };
  },
};
