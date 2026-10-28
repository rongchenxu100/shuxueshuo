/** An observation tool only: no answers, grading, persistence or global event handlers. */
const SVG_NS = 'http://www.w3.org/2000/svg';
const COLOURS = ['#087f79', '#536ec5'];
// Rational arithmetic determines membership. Pixel rounding must never turn a
// small nonempty interval into a point, or a tiny gap into endpoint contact.
const gcd = (a, b) => { while (b) [a, b] = [b, a % b]; return a < 0n ? -a : a; };
function rational(n, d = 1n) {
  if (!d) throw new TypeError('Invalid rational endpoint');
  const divisor = gcd(n, d) * (d < 0n ? -1n : 1n);
  return {n: n / divisor, d: d / divisor};
}
function parseRational(value) {
  const source = String(value);
  if (source.length > 2048) throw new TypeError('Invalid rational endpoint');
  const fraction = /^([+-]?\d+)\/([+-]?\d+)$/.exec(source);
  if (fraction) return rational(BigInt(fraction[1]), BigInt(fraction[2]));
  const decimal = /^([+-]?)(\d+)(?:\.(\d*))?(?:e([+-]?\d+))?$/i.exec(source);
  if (!decimal || Math.abs(Number(decimal[4] || 0)) > 1000) throw new TypeError('Invalid rational endpoint');
  const digits = (decimal[3] || '').length - Number(decimal[4] || 0);
  const n = BigInt((decimal[1] || '') + decimal[2] + (decimal[3] || ''));
  return digits < 0 ? rational(n * 10n ** BigInt(-digits)) : rational(n, 10n ** BigInt(digits));
}
const compare = (a, b) => a.n * b.d < b.n * a.d ? -1 : a.n * b.d > b.n * a.d ? 1 : 0;
const add = (a, b) => rational(a.n * b.d + b.n * a.d, a.d * b.d);
const subtract = (a, b) => rational(a.n * b.d - b.n * a.d, a.d * b.d);
const multiply = (a, b) => rational(a.n * b.n, a.d * b.d);
const rationalKey = value => value.d === 1n ? String(value.n) : `${value.n}/${value.d}`;
function numeric(value) {
  if (!value.n) return 0;
  const negative = value.n < 0n, numerator = negative ? -value.n : value.n;
  let exponent = numerator.toString(2).length - value.d.toString(2).length;
  if (exponent >= 0 ? numerator < value.d << BigInt(exponent) : numerator << BigInt(-exponent) < value.d) exponent--;
  if (exponent > 1023) return negative ? -Infinity : Infinity;
  // Round the exact quotient once (ties to even), rather than separately
  // rounding a large numerator and denominator before dividing them.
  const shift = Math.max(exponent - 52, -1074);
  const top = shift < 0 ? numerator << BigInt(-shift) : numerator;
  const bottom = shift > 0 ? value.d << BigInt(shift) : value.d;
  let quotient = top / bottom;
  const remainder = top % bottom;
  if (remainder * 2n > bottom || remainder * 2n === bottom && quotient % 2n) quotient++;
  const number = Number(quotient) * 2 ** shift;
  return negative ? -number : number;
}
function rationalText(value) {
  if (value.d === 1n) return String(value.n).replace('-', '−');
  // Retain familiar terminating decimals, but never silently round an endpoint.
  const number = numeric(value);
  return Number.isFinite(number) && compare(parseRational(number), value) === 0
    ? String(number).replace('-', '−') : rationalKey(value).replace('-', '−');
}
const coefficient = (endpoint, key) => parseRational(endpoint[`${key}_exact`] ?? endpoint[key]);
const affineValue = (endpoint, parameter) => add(multiply(coefficient(endpoint, 'slope'), parameter), coefficient(endpoint, 'intercept'));
function criticalParameters(config) {
  if (config.critical_exact_values) return config.critical_exact_values.map(parseRational);
  // Old payloads contain only rounded critical values. Recover an exactly
  // coinciding affine endpoint when that value is explicitly selected.
  const endpoints = config.intervals.flatMap(row => [row.lower, row.upper]);
  return (config.critical_values ?? []).map(value => {
    for (let i = 0; i < endpoints.length; i++) for (let j = i + 1; j < endpoints.length; j++) {
      const slope = subtract(coefficient(endpoints[i], 'slope'), coefficient(endpoints[j], 'slope'));
      if (!slope.n) continue;
      const intercept = subtract(coefficient(endpoints[j], 'intercept'), coefficient(endpoints[i], 'intercept'));
      const cut = rational(intercept.n * slope.d, intercept.d * slope.n);
      if (numeric(cut) === value) return cut;
    }
    return parseRational(value);
  });
}
function parameterValue(config, value) {
  if (typeof value === 'string') return parseRational(value);
  if (!Number.isFinite(value)) throw new TypeError('Invalid parameter');
  const matches = criticalParameters(config).filter(cut => numeric(cut) === value);
  return matches.length === 1 ? matches[0] : parseRational(value);
}
function parameterSamples(config) {
  const values = [parseRational(config.parameter_min), parseRational(config.parameter_max),
    parameterValue(config, config.initial), ...criticalParameters(config)];
  return [...new Map(values.map(value => [rationalKey(value), value])).values()].sort(compare);
}
const element = (document, tag, className, content) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content !== undefined) node.textContent = content;
  return node;
};
const svgElement = (document, tag, attributes = {}, content) => {
  const node = document.createElementNS ? document.createElementNS(SVG_NS, tag) : document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
  if (content !== undefined) node.textContent = content;
  return node;
};

function check(config) {
  if (!config || !Array.isArray(config.intervals) || config.intervals.length !== 2 ||
      !['parameter_min', 'parameter_max', 'initial'].every(key => Number.isFinite(config[key])) ||
      config.parameter_min > config.parameter_max || config.initial < config.parameter_min ||
      config.initial > config.parameter_max || typeof config.parameter !== 'string' ||
      typeof config.variable !== 'string' || !['explore', 'separation'].includes(config.mode ?? 'explore')) {
    throw new TypeError('Invalid interval explorer');
  }
  for (const row of config.intervals) {
    if (!['lower', 'upper'].every(key => row[key] && Number.isFinite(row[key].slope) && Number.isFinite(row[key].intercept)) ||
        typeof row.label !== 'string' || typeof row.call_latex !== 'string' ||
        typeof row.left_open !== 'boolean' || typeof row.right_open !== 'boolean') {
      throw new TypeError('Invalid affine interval');
    }
    for (const endpoint of [row.lower, row.upper]) for (const key of ['slope', 'intercept']) coefficient(endpoint, key);
  }
  if (config.critical_values !== undefined && (!Array.isArray(config.critical_values) ||
      !config.critical_values.every(value => Number.isFinite(value) && value >= config.parameter_min && value <= config.parameter_max))) {
    throw new TypeError('Invalid interval snapshots');
  }
  if (config.critical_exact_values !== undefined) {
    if (!Array.isArray(config.critical_exact_values) || config.critical_exact_values.length !== config.critical_values?.length ||
        config.critical_exact_values.some((value, index) => numeric(parseRational(value)) !== config.critical_values[index])) {
      throw new TypeError('Invalid exact interval snapshots');
    }
  }
}

/** Numeric observation at one parameter value, including open/closed singleton semantics. */
export function intervalOverlapAt(config, parameter) {
  check(config);
  const parameterExact = parameterValue(config, parameter);
  const bounds = config.intervals.map(row => ({...row,
    low: affineValue(row.lower, parameterExact), high: affineValue(row.upper, parameterExact)}));
  const lower = bounds.reduce((value, row) => compare(row.low, value) > 0 ? row.low : value, bounds[0].low);
  const upper = bounds.reduce((value, row) => compare(row.high, value) < 0 ? row.high : value, bounds[0].high);
  const leftOpen = bounds.some(row => compare(row.low, lower) === 0 && row.left_open);
  const rightOpen = bounds.some(row => compare(row.high, upper) === 0 && row.right_open);
  const isEmpty = row => compare(row.low, row.high) > 0 || compare(row.low, row.high) === 0 && (row.left_open || row.right_open);
  const invalid = bounds.some(isEmpty);
  const touching = compare(lower, upper) === 0;
  const kind = invalid || compare(lower, upper) > 0 ? 'separate'
    : touching ? leftOpen || rightOpen ? 'touch-empty' : 'point' : 'overlap';
  const empty = ['separate', 'touch-empty'].includes(kind);
  const intersection = empty ? '∅' : kind === 'point' ? `{${rationalText(lower)}}`
    : `${leftOpen ? '(' : '['}${rationalText(lower)}, ${rationalText(upper)}${rightOpen ? ')' : ']'}`;
  const intervals = bounds.map(({low, high, ...row}) => ({...row, lower: numeric(low), upper: numeric(high),
    lower_exact: rationalKey(low), upper_exact: rationalKey(high), empty: isEmpty({...row, low, high})}));
  return {parameter: numeric(parameterExact), parameter_exact: rationalKey(parameterExact), intervals, kind, empty,
    lower: numeric(lower), upper: numeric(upper), lower_exact: rationalKey(lower), upper_exact: rationalKey(upper),
    left_open: leftOpen, right_open: rightOpen, intersection};
}

/** Stable shared scale prevents the moving intervals from looking stationary. */
export function intervalExplorerScale(config) {
  check(config);
  const samples = parameterSamples(config);
  const values = config.intervals.flatMap(row => ['lower', 'upper'].flatMap(key =>
    [samples[0], samples.at(-1)].map(parameter => affineValue(row[key], parameter)))).sort(compare);
  const low = values[0], high = values.at(-1), span = numeric(subtract(high, low));
  const padding = span > 0 ? span * .08 : .25;
  // Translate before converting to pixels: large close coordinates still have
  // a representable difference even when their absolute Numbers coincide.
  return {min: numeric(low) - padding, max: numeric(high) + padding,
    origin_exact: rationalKey(low), min_offset: -padding, max_offset: span + padding};
}

function line(document, svg, x1, x2, y, attributes = {}) {
  svg.append(svgElement(document, 'line', {x1, x2, y1: y, y2: y, ...attributes}));
}
function endpoint(document, svg, x, y, open, colour, radius = 5) {
  svg.append(svgElement(document, 'circle', {cx: x, cy: y, r: radius, fill: open ? '#fff' : colour,
    stroke: colour, 'stroke-width': 2, 'data-endpoint': open ? 'open' : 'closed'}));
}
function addInterval(document, svg, row, y, x, colour) {
  if (row.empty) return;
  line(document, svg, x(row.lower_exact), x(row.upper_exact), y, {stroke: colour, 'stroke-width': 6, 'stroke-linecap': 'round'});
  endpoint(document, svg, x(row.lower_exact), y, row.left_open, colour);
  endpoint(document, svg, x(row.upper_exact), y, row.right_open, colour);
}
const statusText = observation => ({separate: '分离 · 没有共同输入', 'touch-empty': '相接 · 端点未同时取到，交集为空',
  point: '相接 · 只有一个共同输入', overlap: '重叠 · 有一段共同输入'}[observation.kind]);

/** Safe SVG construction, independent of controls and exercise state. No shared IDs/defs. */
export function createIntervalOverlapSVG(document, config, observation) {
  const scale = intervalExplorerScale(config), origin = parseRational(scale.origin_exact);
  const span = scale.max_offset - scale.min_offset;
  const xOffset = value => 40 + (value - scale.min_offset) / span * 338;
  const x = value => xOffset(numeric(subtract(parseRational(value), origin)));
  const svg = svgElement(document, 'svg', {viewBox: '0 0 420 226', role: 'img',
    'aria-label': `${config.parameter}=${rationalText(parseRational(observation.parameter_exact))}，${statusText(observation)}，交集 ${observation.intersection}`});
  svg.setAttribute('class', 'gw-interval-svg');
  const ys = [59, 121];
  if (!observation.empty) {
    const width = x(observation.upper_exact) - x(observation.lower_exact);
    svg.append(svgElement(document, 'rect', {x: x(observation.lower_exact) - (width < 2 ? 2 : 0), y: 35,
      width: Math.max(width, 4), height: 110, rx: 3, fill: '#d9efe4', opacity: '.8'}));
  }
  for (const y of [...ys, 183]) line(document, svg, 30, 392, y, {stroke: '#d1ded8', 'stroke-width': 1.4});
  // Use few shared ticks; endpoints are labelled on each track, even between ticks.
  const rawStep = span / 5, power = 10 ** Math.floor(Math.log10(rawStep));
  const step = [1, 2, 5, 10].map(value => value * power).find(value => value >= rawStep);
  const firstTick = Math.ceil(scale.min_offset / step);
  for (let index = 0; index < 10; index++) {
    const value = (firstTick + index) * step;
    if (value > scale.max_offset) break;
    svg.append(svgElement(document, 'line', {x1: xOffset(value), x2: xOffset(value), y1: 36, y2: 188,
      stroke: '#dce7e1', 'stroke-dasharray': '2 5'}));
    const tick = add(origin, parseRational(Number(value.toPrecision(15))));
    svg.append(svgElement(document, 'text', {x: xOffset(value), y: 215, 'text-anchor': 'middle', fill: '#7a8e85', 'font-size': 13}, rationalText(tick)));
  }
  observation.intervals.forEach((row, index) => {
    svg.append(svgElement(document, 'text', {x: 9, y: ys[index] + 5, fill: COLOURS[index], 'font-size': 15, 'font-weight': 650}, row.label));
    addInterval(document, svg, row, ys[index], x, COLOURS[index]);
    if (!row.empty) {
      const endpoints = [...new Set([row.lower_exact, row.upper_exact])];
      for (const value of endpoints) {
        svg.append(svgElement(document, 'text', {x: x(value), y: ys[index] - 14, 'text-anchor': 'middle', fill: COLOURS[index], 'font-size': 14}, rationalText(parseRational(value))));
      }
    }
  });
  svg.append(svgElement(document, 'text', {x: 9, y: 188, fill: '#527c60', 'font-size': 14}, '∩'));
  if (!observation.empty) addInterval(document, svg, observation, 183, x, '#438d62');
  else svg.append(svgElement(document, 'text', {x: 210, y: 177, 'text-anchor': 'middle', fill: '#94a49c', 'font-size': 19}, '∅'));
  svg.append(svgElement(document, 'text', {x: 403, y: 219, fill: '#7a8e85', 'font-size': 14}, config.variable));
  return svg;
}

function affineText(endpoint, parameter) {
  const slope = coefficient(endpoint, 'slope'), intercept = coefficient(endpoint, 'intercept');
  const variable = slope.n === 0n ? '' : `${slope.n === -slope.d ? '−' : slope.n === slope.d ? '' : rationalText(slope)}${parameter}`;
  if (!variable) return rationalText(intercept);
  if (!intercept.n) return variable;
  if (slope.n < 0n && intercept.n > 0n) return `${rationalText(intercept)}${variable}`;
  return `${variable}${intercept.n > 0n ? '+' : '−'}${rationalText(rational(intercept.n < 0n ? -intercept.n : intercept.n, intercept.d))}`;
}
function createSeparationView(document, config) {
  const group = element(document, 'div', 'gw-interval-separations');
  for (const [leftIndex, rightIndex] of [[0, 1], [1, 0]]) {
    const left = config.intervals[leftIndex], right = config.intervals[rightIndex];
    const card = element(document, 'div', 'gw-interval-separation');
    card.append(element(document, 'div', 'gw-interval-separation-title', `${left.label} 在 ${right.label} 左侧`));
    const svg = svgElement(document, 'svg', {viewBox: '0 0 420 152', role: 'img',
      'aria-label': `示意：${left.label} 在左，${right.label} 在右；比较两个相邻端点`});
    svg.setAttribute('class', 'gw-interval-svg');
    for (const y of [45, 103]) line(document, svg, 30, 395, y, {stroke: '#d1ded8', 'stroke-width': 1.4});
    for (const [index, low, high, y] of [[leftIndex, 60, 175, 45], [rightIndex, 245, 360, 103]]) {
      const row = config.intervals[index];
      line(document, svg, low, high, y, {stroke: COLOURS[index], 'stroke-width': 6});
      endpoint(document, svg, low, y, row.left_open, COLOURS[index]);
      endpoint(document, svg, high, y, row.right_open, COLOURS[index]);
      svg.append(svgElement(document, 'text', {x: 9, y: y + 5, fill: COLOURS[index], 'font-size': 15}, row.label));
      for (const [key, position] of [['lower', low], ['upper', high]]) {
        svg.append(svgElement(document, 'text', {x: position, y: y + 24, 'text-anchor': 'middle', fill: COLOURS[index], 'font-size': 15}, affineText(row[key], config.parameter)));
      }
    }
    svg.append(svgElement(document, 'line', {x1: 175, x2: 175, y1: 29, y2: 108, stroke: '#9dadb7', 'stroke-dasharray': '3 4'}));
    svg.append(svgElement(document, 'line', {x1: 245, x2: 245, y1: 29, y2: 108, stroke: '#9dadb7', 'stroke-dasharray': '3 4'}));
    card.append(svg);
    group.append(card);
  }
  group.append(element(document, 'p', 'gw-interval-hint', '示意图不按比例；相接时，还要看两个端点是否都取到'));
  return group;
}

/** Controls mutate only this explorer. Repeated rendering cannot share events or element IDs. */
export function createIntervalOverlapExplorer(document, config) {
  check(config);
  const node = element(document, 'section', 'gw-interval-explorer');
  node.dataset.mode = config.mode ?? 'explore';
  node.setAttribute('aria-label', '观察两个输入区间的交集');
  const legend = element(document, 'div', 'gw-interval-legend');
  for (const [index, row] of config.intervals.entries()) {
    const item = element(document, 'span', 'gw-interval-legend-item');
    item.dataset.interval = String(index);
    item.append(element(document, 'span', 'gw-interval-legend-dot', row.label));
    const label = element(document, 'span', '', `$${row.call_latex}$`);
    label.dataset.mathText = 'true'; item.append(label); legend.append(item);
  }
  node.append(legend);
  if (config.mode === 'separation') {
    node.append(createSeparationView(document, config));
    return node;
  }
  const viewport = element(document, 'div', 'gw-interval-viewport');
  const controls = element(document, 'label', 'gw-interval-controls');
  const current = element(document, 'span', 'gw-interval-current');
  const slider = element(document, 'input', 'gw-interval-slider');
  slider.type = 'range'; slider.min = String(config.parameter_min); slider.max = String(config.parameter_max);
  slider.step = 'any'; slider.value = String(config.initial);
  slider.disabled = config.parameter_min === config.parameter_max;
  slider.setAttribute('aria-label', `调整参数 ${config.parameter}`);
  controls.append(current, slider);
  const snapshots = element(document, 'div', 'gw-interval-snapshots');
  const status = element(document, 'div', 'gw-interval-status');
  status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
  const message = element(document, 'span', 'gw-interval-status-text');
  const result = element(document, 'span', 'gw-interval-intersection');
  status.append(message, result);
  const values = parameterSamples(config);
  const buttons = values.map(value => {
    const button = element(document, 'button', 'gw-interval-snapshot', `${config.parameter} = ${rationalText(value)}`);
    button.type = 'button'; button.dataset.parameter = String(numeric(value));
    button.dataset.parameterExact = rationalKey(value);
    button.addEventListener('click', () => update(rationalKey(value)));
    snapshots.append(button); return button;
  });
  function update(value) {
    if (typeof value !== 'string' && !Number.isFinite(value)) return;
    let parameter = parameterValue(config, value);
    if (compare(parameter, values[0]) < 0) parameter = values[0];
    if (compare(parameter, values.at(-1)) > 0) parameter = values.at(-1);
    const observation = intervalOverlapAt(config, rationalKey(parameter));
    slider.value = String(numeric(parameter));
    slider.setAttribute('aria-valuetext', `${config.parameter} = ${rationalText(parameter)}`);
    current.textContent = `${config.parameter} = ${rationalText(parameter)}`;
    viewport.replaceChildren(createIntervalOverlapSVG(document, config, observation));
    node.dataset.state = observation.kind;
    message.textContent = statusText(observation);
    result.textContent = `${config.intervals.map(row => row.label).join(' ∩ ')} = ${observation.intersection}`;
    buttons.forEach(button => button.setAttribute('aria-pressed', button.dataset.parameterExact === rationalKey(parameter) ? 'true' : 'false'));
  }
  slider.addEventListener('input', () => update(Number(slider.value)));
  node.append(viewport, status, controls, snapshots,
    element(document, 'p', 'gw-interval-hint', `${slider.disabled ? '选择参数快照观察变化' : '拖动参数观察变化'} · ● 端点取到　○ 端点不取`));
  update(config.initial);
  return node;
}
