/* Small HTML components; lesson-specific content is passed in as data. */
(() => {
  'use strict';
  const escape = value => String(value).replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]));
  const radical = content => `<span class="radical"><span class="root-sign">√</span><span class="radicand">${content}</span></span>`;
  const hintIcon = '<svg class="hint-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 18h6m-5 3h4M9 15c0-2-3-3-3-7a6 6 0 0 1 12 0c0 4-3 5-3 7v1H9Z"/></svg>';
  function slot({stage, index, value, label, title, occurrence = '', shape = index === 0 ? 'square' : 'circle'}) {
    const name = shape === 'square' ? '方框' : '圆圈';
    return `<button type="button" class="shape ${shape} ${label ? 'expression-slot' : ''} ${value ? '' : 'empty'}" data-stage="${stage}" data-slot="${index}" data-occurrence="${escape(occurrence)}" aria-haspopup="dialog" aria-expanded="false" aria-label="${escape(title)}：${escape(occurrence)}${name}，${escape(value || '未填写')}"><span data-math-text>${escape(label || value || '?')}</span></button>`;
  }
  function choices(component, selected, title) {
    return `<div class="method-options" role="group" aria-label="${escape(title)}">${component.options.map(({value, label}) => `<button type="button" class="method-choice" data-choice="${escape(component.field)}" data-value="${escape(value)}" aria-pressed="${selected === value}"><span class="radio-mark" aria-hidden="true"></span><span data-math-text>${escape(label)}</span></button>`).join('')}</div>`;
  }
  function controls({stage, label, ready, feedback, hint}) {
    return `<div class="actions"><button type="button" class="primary" data-submit="${stage}" ${ready ? '' : 'disabled'}>${escape(label)} <span aria-hidden="true">→</span></button><button type="button" class="hint-button" data-hint="${stage}">${hintIcon}给点提示</button></div>${feedback ? `<p class="feedback ${hint ? 'helper-feedback' : ''}" data-math-text>${escape(feedback)}</p>` : ''}`;
  }
  function structure({slot, swapped}) {
    return `<div class="visual-board">
      <div class="structure-row"><span class="row-label">条件</span><div class="formula">${slot(0, '条件中的')}<span>${swapped ? '·' : '+'}</span>${slot(1, '条件中的')}</div><span class="row-tag">${swapped ? '定积' : '定和'}</span></div>
      <div class="swap-row"><button type="button" class="swap-button" id="swap" aria-label="交换和与积" aria-pressed="${swapped}"><span class="swap-icon" aria-hidden="true">⇅</span>交换和与积</button></div>
      <div class="structure-row"><span class="row-label">目标</span><div class="formula">${slot(0, '目标中的')}<span>${swapped ? '+' : '·'}</span>${slot(1, '目标中的')}</div><span class="row-tag">${swapped ? '求最小值' : '求最大值'}</span></div>
    </div>`;
  }
  function amgmFormula(slot) {
    return `<div class="formula" aria-label="方框加圆圈，大于等于二倍根号下方框乘圆圈"><span class="amgm-side">${slot(0, '左侧')}<span>+</span>${slot(1, '左侧')}</span><span class="amgm-side"><span>≥</span><span>2</span>${radical(`${slot(0, '根号中的')}<span class="multiply">·</span>${slot(1, '根号中的')}`)}</span></div>`;
  }
  function amgm({slot, terms, positiveTerms = terms, termLabels = {}}) {
    return `<div class="positive-tags">${positiveTerms.map(term => `<span class="math"><span data-math-text>${escape(termLabels[term] || term)}</span> &gt; 0 <span aria-hidden="true">✓</span></span>`).join('')}</div>
      <div class="visual-board application-board"><div class="board-caption">基本不等式</div>
      ${amgmFormula(slot)}</div>`;
  }
  function completedAmgm({terms, labels}) {
    const shape = index => `<span class="shape ${index === 0 ? 'square' : 'circle'} ${labels[index] !== terms[index] ? 'expression-slot' : ''}"><span data-math-text>${escape(labels[index])}</span></span>`;
    return `<div class="visual-board application-board completed-visual"><div class="board-caption">基本不等式</div>${amgmFormula(shape)}</div>`;
  }
  function equality({slot, caption = '基本不等式取等'}) {
    return `<div class="visual-board equality-board"><div class="board-caption">${escape(caption)}</div><div class="formula">${slot(0)}<span class="equal-sign">=</span>${slot(1)}</div></div>`;
  }
  function symmetry({board, slotLabels, pair, terms, termLabels}) {
    const options = index => `<div class="judgment-options" role="group" aria-label="${escape(slotLabels[index])}交换后的判断">${terms.map(value => `<button type="button" data-pair-answer="${index}" data-value="${escape(value)}" aria-pressed="${pair[index] === value}">${escape(termLabels[value] || value)}</button>`).join('')}</div>`;
    // A board may place each judgment beside its own expression row.
    const inline = board.replace(/<span data-judgment="(\d+)"><\/span>/g, (_, index) => options(Number(index)));
    if (inline !== board) return inline;
    return board + `<div class="symmetry-judgments">${slotLabels.map((label, index) => `<div class="symmetry-judgment"><span>${escape(label)}交换后</span>${options(index)}</div>`).join('')}</div>`;
  }
  function substitution({component, pair, board, scopeBoard, slot, slotLabels}) {
    if (scopeBoard) {
      // New variables are named by position in the target expression, not by click order.
      const chosen = pair[0] ? pair[0].split('|') : [];
      const at = value => scopeBoard.indexOf(`data-sub-target="${escape(value)}"`);
      const names = new Map([...chosen].sort((a, b) => at(a) - at(b)).map((value, i) => [escape(value), component.slots[0].names[i]]));
      const targets = scopeBoard.replace(/<button([^>]*?) data-sub-target="([^"]+)"([^>]*)>/g, (_, before, value, after) =>
        `<button${before} data-sub-target="${value}"${after} aria-pressed="${names.has(value)}">${names.has(value) ? `<span class="sub-tag" aria-hidden="true">${escape(names.get(value))}</span>` : ''}`);
      return targets.replace(/<span data-sub-result(?:="")?><\/span>/, board || `<p class="sub-pending">${chosen.length ? '确认后看看这样换元是否合适' : '先在上面的表达式里点选要看成整体的部分'}</p>`);
    }
    return `<div class="visual-board"><div class="board-caption">用和与积定义新变量</div><div class="substitution-definitions">${slotLabels.map((label, index) => `<div class="formula"><span data-math-text>$${escape(label)}$</span><span>=</span>${slot(index, `${label} 对应的`)}</div>`).join('')}</div></div>`;
  }
  function homogeneity({component, board, slot, pair}) {
    const degrees = board.replace(/<span data-degree="(\d)"><\/span>/g, (_, index) => slot(Number(index)));
    // Degrees of added terms are compared, not summed; only a two-slot product shows a total.
    if ((component.slot_labels?.length ?? 2) !== 2) return degrees;
    const ready = pair[0] && pair[1];
    const sum = ready ? Number(pair[0]) + Number(pair[1]) : null;
    const signed = value => value > 0 ? `+${value}` : `${value}`;
    const marker = /<span data-degree-total(?:="")?><\/span>/;
    if (marker.test(degrees)) {
      const part = value => value ? `(${signed(Number(value))})` : '(?)';
      const formula = `$${part(pair[0])}+${part(pair[1])}=${ready ? signed(sum) : '?'}$`;
      return degrees.replace(marker, `<div class="deg-total" aria-live="polite"><span class="deg-total-value${ready ? '' : ' pending'}">${ready ? signed(sum).replace('-', '−') : '?'} 次</span><span class="deg-total-sum" data-math-text>${escape(formula)}</span></div>`);
    }
    return degrees + `<div class="degree-total" aria-live="polite"><span>相乘后的次数</span><span>${escape(pair[0] || '?')} + (${escape(pair[1] || '?')}) = ${ready ? sum : '?'}</span></div>`;
  }
  function fill({board, slot, slotLabels = []}) {
    const inline = board.replace(/<span data-fill="(\d+)"><\/span>/g, (_, index) => slot(Number(index)));
    if (inline !== board) return inline;
    return board + `<div class="visual-board"><div class="formula">${slotLabels.map((_, index) => slot(index)).join('')}</div></div>`;
  }
  // One row per prerequisite. Options stay visible; a chosen option's note states its consequence without marking it right or wrong.
  function checklist({component, pair, board = ''}) {
    const plain = text => String(text).replace(/\$/g, '');
    const rows = component.slots.map((row, index) => {
      const chosen = row.options.find(option => option.value === pair[index]);
      return `<div class="checklist-row ${chosen ? 'answered' : ''}"><span class="checklist-index" aria-hidden="true">${index + 1}</span><div class="checklist-body">
        <p class="checklist-label" data-math-text>${escape(row.label)}</p>${row.hint ? `<p class="checklist-hint" data-math-text>${escape(row.hint)}</p>` : ''}
        <div class="checklist-options" role="group" aria-label="${escape(plain(row.label))}">${row.options.map(({value, label}) => `<button type="button" data-pair-answer="${index}" data-value="${escape(value)}" aria-pressed="${pair[index] === value}"><span data-math-text>${escape(label)}</span></button>`).join('')}</div>
        ${chosen?.note ? `<p class="checklist-note" data-math-text>${escape(chosen.note)}</p>` : ''}</div></div>`;
    }).join('');
    const answered = component.slots.filter((_, index) => pair[index]).length;
    return `${board}<div class="checklist"><div class="checklist-head"><span class="checklist-title" data-math-text>${escape(component.title || '适用前提')}</span><span class="checklist-progress">已看 ${answered} / ${component.slots.length}</span></div>${rows}</div>`;
  }
  function rewrite({component, pair, board, scopeBoard, slot}) {
    const scopes = component.slots[0];
    const factor = board ? board.replace(/<span data-rewrite-factor(?:="")?><\/span>/g, slot(1)) : '';
    // The expression board marks each selectable part with data-rewrite-scope: the whole, one term, or a single constant.
    if (scopeBoard) {
      const targets = scopeBoard.replace(/<button([^>]*?) data-rewrite-scope="([^"]+)"/g, (_, attrs, value) => `<button${attrs} data-pair-answer="0" data-value="${escape(value)}" aria-pressed="${pair[0] === value}"`);
      return targets.replace(/<span data-rewrite-result(?:="")?><\/span>/, factor || '<div class="rw-result rw-pending"><span class="rw-placeholder">先在上面的式子里点选要乘入的部分</span></div>');
    }
    return `<div class="rewrite-scopes" role="group" aria-label="${escape(scopes.label)}">${scopes.options.map(({value, label}) => `<button type="button" data-pair-answer="0" data-value="${escape(value)}" aria-pressed="${pair[0] === value}"><span data-math-text>${escape(label)}</span></button>`).join('')}</div>` +
      (factor || '<p class="calculation-note">选定作用范围后，补全乘入的表达式。</p>');
  }
  const sampleRange = (left, right, extra = [], count = 100) => [...new Set([...Array.from({length: count + 1}, (_, i) => left + (right - left) * i / count), ...extra.filter(value => value >= left && value <= right)])].sort((a, b) => a - b);
  // An interval side given as null is unbounded: it has no guide line and extends past the window.
  const bounded = interval => interval && [interval[0] ?? -Infinity, interval[1] ?? Infinity];
  const intervalGuides = (interval, x) => interval ? `<path class="graph-interval" d="${interval.filter(Number.isFinite).map(value => `M${x(value)} 48V222`).join('')}" fill="none" stroke="#7fa79c" stroke-width="1.3" stroke-dasharray="3 4"/>` : '';
  // place: "above-right" (default), "above-left", "below-right" or "below-left" of the point.
  const pointLabels = (points, x, y) => points.map(point => {
    const [vertical, side] = (point.place || 'above-right').split('-');
    return `<text x="${x(point.x) + (side === 'left' ? -8 : 8)}" y="${y(point.x) + (vertical === 'below' ? 22 : -10)}" text-anchor="${side === 'left' ? 'end' : 'start'}" fill="#a04c36">${escape(point.label)}</text>`;
  }).join('');
  // An open point is not attained (an excluded endpoint of an open interval): drawn hollow.
  const pointDot = point => point.open ? 'r="5" fill="#fff" stroke="#b65c42" stroke-width="2.4"' : 'r="5" fill="#b65c42"';
  // Read-only quadratic in vertex form: coefficient * (x - h)^2 + k.
  // Bounds are the visible window; domain (when supplied) limits the actual curve.
  // markSign shades the violating side ("below" = y<0, the default for true; "above" = y>0), recolours the arcs there
  // and marks where the curve meets the x-axis; strict makes a touching point a violation too.
  // solution draws a chosen x-range on the axis: intervals use null for an unbounded side; closed decides filled
  // endpoints, either for all of them or as an array in endpoint order.
  // interval [a, b] is the x-range the condition is about: the curve outside it fades, and markSign only judges inside it.
  function quadraticGraph({coefficient, vertex, bounds, domain, excluded = [], xTicks, yLabel, variable, title, description, uid, referenceLines = [], points = [], showVertex = true, markSign = false, strict = false, solution = null, interval = null}) {
    interval = bounded(interval);
    const [h, k] = vertex;
    const [xmin, xmax, ymin, ymax] = bounds;
    const x = value => 48 + (value - xmin) / (xmax - xmin) * 270;
    const y = value => 222 - (value - ymin) / (ymax - ymin) * 174;
    const f = value => coefficient * (value - h) ** 2 + k;
    const left = Math.max(xmin, domain?.[0] ?? xmin);
    const right = Math.min(xmax, domain?.[1] ?? xmax);
    const spread = -k / coefficient;
    const roots = (spread > 0 ? [h - Math.sqrt(spread), h + Math.sqrt(spread)] : spread === 0 ? [h] : [])
      .filter(value => value >= (interval?.[0] ?? left) && value <= (interval?.[1] ?? right));
    const samples = sampleRange(left, right, [...roots, ...(interval || [])]);
    const path = values => values.map((value, i) => `${i ? 'L' : 'M'}${x(value).toFixed(3)} ${y(f(value)).toFixed(3)}`).join(' ');
    const focus = interval ? samples.filter(value => value >= interval[0] && value <= interval[1]) : samples;
    const curve = path(focus);
    const above = markSign === 'above';
    const sign = above ? 'positive' : 'negative';
    const violates = value => above ? value > 0 : value < 0;
    const violatingArcs = [];
    if (markSign) focus.slice(1).forEach((value, i) => {
      if (!violates(f((focus[i] + value) / 2))) return;
      const arc = violatingArcs.at(-1);
      if (arc?.at(-1) === focus[i]) arc.push(value); else violatingArcs.push([focus[i], value]);
    });
    const axisInView = ymin < 0 && ymax > 0;
    const bandX = interval ? [Math.max(48, x(interval[0])), Math.min(318, x(interval[1]))] : [48, 318];
    const endpoints = solution ? solution.intervals.flat().filter(value => value !== null) : [];
    const closedAt = i => Array.isArray(solution.closed) ? solution.closed[i] : solution.closed;
    // Under markSign, a root label moves away from the side where the curve dips below the axis.
    const tickPlacement = value => {
      if (markSign && roots.some(root => Math.abs(root - value) < 1e-9)) {
        if (f(value + 1e-3) < 0 && !(f(value - 1e-3) < 0)) return ['end', -7];
        if (f(value - 1e-3) < 0 && !(f(value + 1e-3) < 0)) return ['start', 7];
      }
      return value === 0 ? ['end', -8] : ['middle', 0];
    };
    const id = escape(uid);
    return `<svg viewBox="0 0 360 270" role="img" aria-labelledby="${id}-title ${id}-description">
      <title id="${id}-title">${escape(title)}</title><desc id="${id}-description">${escape(description)}</desc>
      <defs><clipPath id="${id}-clip"><rect x="48" y="48" width="270" height="174"/></clipPath></defs>
      <rect x="48" y="48" width="270" height="174" rx="5" fill="#f0f7f4"/>
      <path d="M25 ${y(0)}H330M${x(0)} 235V35" fill="none" stroke="#9dafaa" stroke-width="1.3"/>
      <path d="m325 ${y(0)-4} 5 4-5 4M${x(0)-4} 40l4-5 4 5" fill="none" stroke="#9dafaa" stroke-width="1.3"/>
      <g clip-path="url(#${id}-clip)">
        ${markSign && axisInView ? `<rect class="quadratic-${sign}-band" x="${bandX[0]}" y="${above ? 48 : y(0)}" width="${bandX[1] - bandX[0]}" height="${above ? y(0) - 48 : 222 - y(0)}" fill="#fbebe6"/>` : ''}
        ${intervalGuides(interval, x)}
        ${referenceLines.map(line => `<path class="quadratic-reference" d="M48 ${y(line.value)}H318" fill="none" stroke="#b6782c" stroke-width="2" stroke-dasharray="6 4"/>`).join('')}
        ${showVertex ? `<path d="M${x(0)} ${y(k)}H${x(h)}V222" fill="none" stroke="#9abfb5" stroke-width="1.2" stroke-dasharray="4 4"/>` : ''}
        ${interval ? `<path class="graph-outside" d="${path(samples)}" fill="none" stroke="#07847d" stroke-width="2.2" opacity=".3"/>` : ''}
        <path class="quadratic-curve" d="${curve}" fill="none" stroke="#07847d" stroke-width="3"/>
        ${violatingArcs.map(arc => `<path class="quadratic-${sign}" d="${path(arc)}" fill="none" stroke="#c4553f" stroke-width="3.6"/>`).join('')}
        ${solution ? solution.intervals.map(([from, to]) => `<path class="quadratic-solution" d="M${from === null ? 48 : x(from)} ${y(0)}H${to === null ? 318 : x(to)}" stroke="#087f79" stroke-width="6" stroke-linecap="butt" opacity=".85"/>`).join('') : ''}
        ${endpoints.map((value, i) => `<circle class="quadratic-endpoint" cx="${x(value)}" cy="${y(0)}" r="5.5" fill="${closedAt(i) ? '#087f79' : '#fff'}" stroke="#087f79" stroke-width="2.4"/>`).join('')}
        ${markSign && !solution ? roots.map(value => `<circle class="quadratic-root" cx="${x(value)}" cy="${y(0)}" r="5" fill="#fff" stroke="${roots.length === 1 && !strict ? '#08655f' : '#c4553f'}" stroke-width="2.4"/>`).join('') : ''}
        ${excluded.map(value => `<circle class="quadratic-excluded" cx="${x(value)}" cy="${y(f(value))}" r="4" fill="white" stroke="#07847d" stroke-width="2"/>`).join('')}
        ${showVertex ? `<circle class="quadratic-vertex" cx="${x(h)}" cy="${y(k)}" r="5" fill="#d18a2e"/>` : ''}
        ${points.map(point => `<circle class="quadratic-point" cx="${x(point.x)}" cy="${y(f(point.x))}" ${pointDot(point)}/>`).join('')}
      </g>
      <g fill="#526e64" font-family="Georgia,serif" font-size="14">
        ${xTicks.map(([value, label]) => { const [anchor, dx] = tickPlacement(value); return `<text x="${x(value)}" y="${y(0)+21}" text-anchor="${anchor}" dx="${dx}">${escape(label)}</text>`; }).join('')}
        ${showVertex ? `<text x="${x(0)-8}" y="${y(k)+5}" text-anchor="end">${escape(yLabel)}</text>` : ''}
        ${referenceLines.map(line => `<text x="312" y="${y(line.value)-8}" text-anchor="end" fill="#99611f">${escape(line.label)}</text>`).join('')}
        ${pointLabels(points, x, value => y(f(value)))}
        ${markSign && axisInView ? `<text x="312" y="${above ? 64 : 214}" text-anchor="end" fill="#b0503c" font-size="13">${above ? 'y &gt; 0' : 'y &lt; 0'}</text>` : ''}
        <text x="335" y="${y(0)+5}" font-style="italic">${escape(variable)}</text>
        <text x="${x(0)-8}" y="28" text-anchor="end" font-style="italic">y</text>
        ${showVertex ? `<text x="${x(h)+10}" y="${y(k)-13}" fill="#a36920">P(${escape(xTicks.find(([value]) => value === h)?.[1] ?? h)}, ${escape(yLabel)})</text>` : ''}
      </g>
    </svg>`;
  }
  // Read-only y = a·x + b/x on x > 0 (the hook curve when a, b > 0). Window, interval, points and reference lines
  // work as in quadraticGraph; the branch near x = 0 simply leaves the window.
  // asymptotes draws the two lines the curve approaches: the y-axis (x → 0⁺) and y = a·x (x → +∞).
  // negative draws the x < 0 branch instead (such as −x − 2/x, a hook opening upward on the left).
  function reciprocalSumGraph({a, b, bounds, interval = null, xTicks = [], variable = 'x', title, description, uid, referenceLines = [], points = [], asymptotes = false, negative = false}) {
    interval = bounded(interval);
    const [xmin, xmax, ymin, ymax] = bounds;
    const x = value => 48 + (value - xmin) / (xmax - xmin) * 270;
    const y = value => 222 - (value - ymin) / (ymax - ymin) * 174;
    const f = value => a * value + b / value;
    const gap = (xmax - xmin) / 400;
    const samples = negative ? sampleRange(xmin, Math.min(xmax, -gap), interval || [], 240) : sampleRange(Math.max(xmin, gap), xmax, interval || [], 240);
    const path = values => values.map((value, i) => `${i ? 'L' : 'M'}${x(value).toFixed(3)} ${Math.max(-400, Math.min(700, y(f(value)))).toFixed(3)}`).join(' ');
    const focus = interval ? samples.filter(value => value >= interval[0] && value <= interval[1]) : samples;
    const exit = negative
      ? (a > 0 ? Math.max(xmin, ymin / a) : a < 0 ? Math.max(xmin, ymax / a) : xmin)
      : (a > 0 ? Math.min(xmax, ymax / a) : a < 0 ? Math.min(xmax, ymin / a) : xmax);
    const inward = (negative ? 1 : -1) * 40 * (xmax - xmin) / 270;
    const id = escape(uid);
    return `<svg viewBox="0 0 360 270" role="img" aria-labelledby="${id}-title ${id}-description">
      <title id="${id}-title">${escape(title)}</title><desc id="${id}-description">${escape(description)}</desc>
      <defs><clipPath id="${id}-clip"><rect x="48" y="48" width="270" height="174"/></clipPath></defs>
      <rect x="48" y="48" width="270" height="174" rx="5" fill="#f0f7f4"/>
      <path d="M25 ${y(0)}H330M${x(0)} 235V35" fill="none" stroke="#9dafaa" stroke-width="1.3"/>
      <path d="m325 ${y(0)-4} 5 4-5 4M${x(0)-4} 40l4-5 4 5" fill="none" stroke="#9dafaa" stroke-width="1.3"/>
      <g clip-path="url(#${id}-clip)">
        ${intervalGuides(interval, x)}
        ${referenceLines.map(line => `<path class="graph-reference" d="M48 ${y(line.value)}H318" fill="none" stroke="#b6782c" stroke-width="2" stroke-dasharray="6 4"/>`).join('')}
        ${asymptotes ? `<path class="graph-asymptote" d="M${x(0)} 48V${y(0)}" fill="none" stroke="#b6782c" stroke-width="2" stroke-dasharray="6 4"/><path class="graph-asymptote" d="M${x(0)} ${y(0)}L${x(exit)} ${y(a * exit)}" fill="none" stroke="#b6782c" stroke-width="2" stroke-dasharray="6 4"/>` : ''}
        ${interval ? `<path class="graph-outside" d="${path(samples)}" fill="none" stroke="#07847d" stroke-width="2.2" opacity=".3"/>` : ''}
        <path class="reciprocal-curve" d="${path(focus)}" fill="none" stroke="#07847d" stroke-width="3"/>
        ${points.map(point => `<circle class="graph-point" cx="${x(point.x)}" cy="${y(f(point.x))}" ${pointDot(point)}/>`).join('')}
      </g>
      <g fill="#526e64" font-family="Georgia,serif" font-size="14">
        ${xTicks.map(([value, label]) => `<text x="${x(value)}" y="${y(0)+21}" text-anchor="${value === 0 ? 'end' : 'middle'}" dx="${value === 0 ? -8 : 0}">${escape(label)}</text>`).join('')}
        ${referenceLines.map(line => `<text x="312" y="${y(line.value)-8}" text-anchor="end" fill="#99611f">${escape(line.label)}</text>`).join('')}
        ${asymptotes ? `<text x="${x(exit) + (negative ? 6 : -6)}" y="${y(a * (exit + inward)) + 18}" text-anchor="${negative ? 'start' : 'end'}" fill="#99611f">y = ${a === 1 ? '' : a === -1 ? '−' : a}${escape(variable)}</text>` : ''}
        ${pointLabels(points, x, value => y(f(value)))}
        <text x="335" y="${y(0)+5}" font-style="italic">${escape(variable)}</text>
        <text x="${x(0)-8}" y="28" text-anchor="end" font-style="italic">y</text>
      </g>
    </svg>`;
  }
  // Read-only line y = slope·t + intercept, such as a function of the switched main variable on an interval.
  // Window, interval, ticks, points and markSign/strict work as in quadraticGraph.
  function linearGraph({slope, intercept, bounds, interval = null, xTicks = [], variable = 'x', title, description, uid, points = [], markSign = false, strict = false}) {
    interval = bounded(interval);
    const [xmin, xmax, ymin, ymax] = bounds;
    const x = value => 48 + (value - xmin) / (xmax - xmin) * 270;
    const y = value => 222 - (value - ymin) / (ymax - ymin) * 174;
    const f = value => slope * value + intercept;
    const left = Math.max(xmin, interval?.[0] ?? xmin);
    const right = Math.min(xmax, interval?.[1] ?? xmax);
    const segment = (from, to) => `M${x(from).toFixed(3)} ${y(f(from)).toFixed(3)}L${x(to).toFixed(3)} ${y(f(to)).toFixed(3)}`;
    const root = slope ? -intercept / slope : null;
    const roots = root !== null && root >= left && root <= right ? [root] : [];
    const above = markSign === 'above';
    const sign = above ? 'positive' : 'negative';
    // A line lying on the axis (slope and intercept 0) violates a strict inequality everywhere.
    const violates = value => (above ? value > 0 : value < 0) || (strict && Math.abs(value) < 1e-12);
    const pieces = roots.length ? [[left, root], [root, right]] : [[left, right]];
    const violating = markSign ? pieces.filter(([from, to]) => to > from && violates(f((from + to) / 2))) : [];
    const axisInView = ymin < 0 && ymax > 0;
    const bandX = interval ? [Math.max(48, x(interval[0])), Math.min(318, x(interval[1]))] : [48, 318];
    const id = escape(uid);
    return `<svg viewBox="0 0 360 270" role="img" aria-labelledby="${id}-title ${id}-description">
      <title id="${id}-title">${escape(title)}</title><desc id="${id}-description">${escape(description)}</desc>
      <defs><clipPath id="${id}-clip"><rect x="48" y="48" width="270" height="174"/></clipPath></defs>
      <rect x="48" y="48" width="270" height="174" rx="5" fill="#f0f7f4"/>
      <path d="M25 ${y(0)}H330M${x(0)} 235V35" fill="none" stroke="#9dafaa" stroke-width="1.3"/>
      <path d="m325 ${y(0)-4} 5 4-5 4M${x(0)-4} 40l4-5 4 5" fill="none" stroke="#9dafaa" stroke-width="1.3"/>
      <g clip-path="url(#${id}-clip)">
        ${markSign && axisInView ? `<rect class="linear-${sign}-band" x="${bandX[0]}" y="${above ? 48 : y(0)}" width="${bandX[1] - bandX[0]}" height="${above ? y(0) - 48 : 222 - y(0)}" fill="#fbebe6"/>` : ''}
        ${intervalGuides(interval, x)}
        ${interval ? `<path class="graph-outside" d="${segment(xmin, xmax)}" fill="none" stroke="#07847d" stroke-width="2.2" opacity=".3"/>` : ''}
        <path class="linear-line" d="${segment(left, right)}" fill="none" stroke="#07847d" stroke-width="3"/>
        ${violating.map(([from, to]) => `<path class="linear-${sign}" d="${segment(from, to)}" fill="none" stroke="#c4553f" stroke-width="3.6"/>`).join('')}
        ${markSign ? roots.map(value => `<circle class="linear-root" cx="${x(value)}" cy="${y(0)}" r="5" fill="#fff" stroke="${strict ? '#c4553f' : '#08655f'}" stroke-width="2.4"/>`).join('') : ''}
        ${points.map(point => `<circle class="graph-point" cx="${x(point.x)}" cy="${y(f(point.x))}" ${pointDot(point)}/>`).join('')}
      </g>
      <g fill="#526e64" font-family="Georgia,serif" font-size="14">
        ${xTicks.map(([value, label]) => `<text x="${x(value)}" y="${y(0)+21}" text-anchor="${value === 0 ? 'end' : 'middle'}" dx="${value === 0 ? -8 : 0}">${escape(label)}</text>`).join('')}
        ${pointLabels(points, x, value => y(f(value)))}
        ${markSign && axisInView ? `<text x="312" y="${above ? 64 : 214}" text-anchor="end" fill="#b0503c" font-size="13">${above ? 'y &gt; 0' : 'y &lt; 0'}</text>` : ''}
        <text x="335" y="${y(0)+5}" font-style="italic">${escape(variable)}</text>
        <text x="${x(0)-8}" y="28" text-anchor="end" font-style="italic">y</text>
      </g>
    </svg>`;
  }
  // Exploration, not an answer: the student drags the axis of symmetry of
  // f(x) = coefficient·(x − h)² + constant − coefficient·h² and watches which point of the interval is highest
  // (target "min": lowest — the vertex when it lies inside, otherwise the lower end).
  // axis {min, max, step, value} bounds the axis x = h; marks are dashed reference x-positions (such as the
  // interval midpoint). open makes the interval open: endpoints stay hollow and a marked end is labelled 上端／下端.
  // An interval side given as null is unbounded. runtime.js redraws only the [data-axis-layer] group while dragging,
  // so the SVG keeps its pointer capture.
  function axisFrame({bounds}) {
    const [xmin, xmax, ymin, ymax] = bounds;
    return {x: value => 48 + (value - xmin) / (xmax - xmin) * 270, y: value => 222 - (value - ymin) / (ymax - ymin) * 174};
  }
  function axisExplorerLayer(spec, h) {
    const {coefficient, constant, bounds, open = false, target = 'max'} = spec;
    const interval = bounded(spec.interval);
    const {x, y} = axisFrame(spec);
    const f = value => coefficient * (value - h) ** 2 + constant - coefficient * h * h;
    const ends = interval.filter(Number.isFinite);
    const samples = sampleRange(bounds[0], bounds[1], ends, 160);
    const path = values => values.map((value, i) => `${i ? 'L' : 'M'}${x(value).toFixed(2)} ${Math.max(-400, Math.min(700, y(f(value)))).toFixed(2)}`).join(' ');
    const lowest = target === 'min';
    const values = ends.map(f);
    const tie = values.length === 2 && Math.abs(values[0] - values[1]) < 1e-9;
    const inside = lowest && h > interval[0] && h < interval[1];
    const extreme = coefficient > 0 && !inside ? (lowest ? Math.min(...values) : Math.max(...values)) : null;
    const word = lowest ? (open ? '下端' : '最低') : (open ? '上端' : '最高');
    const endpoint = (value, fx) => {
      const marked = extreme !== null && Math.abs(fx - extreme) < 1e-9;
      const fill = marked && !open ? '#b65c42' : '#fff';
      const before = value === interval[0] && !tie;
      return `<circle class="axis-endpoint${marked ? (lowest ? ' lowest' : ' highest') : ''}" cx="${x(value)}" cy="${y(fx)}" r="${marked ? 6 : 4.5}" fill="${fill}" stroke="#b65c42" stroke-width="${marked && open ? 3 : 2.2}"/>` +
        (marked ? `<text x="${x(value) + (before ? -9 : 9)}" y="${y(fx) - 11}" text-anchor="${before ? 'end' : 'start'}" fill="#a04c36" font-size="14">${word}</text>` : '');
    };
    return `<g clip-path="url(#${escape(spec.uid)}-clip)">
        <path class="graph-outside" d="${path(samples)}" fill="none" stroke="#07847d" stroke-width="2.2" opacity=".3"/>
        <path class="quadratic-curve" d="${path(samples.filter(value => value >= interval[0] && value <= interval[1]))}" fill="none" stroke="#07847d" stroke-width="3"/>
        <path class="axis-line" d="M${x(h)} 48V222" fill="none" stroke="#b6782c" stroke-width="2.4" stroke-dasharray="7 4"/>
        <circle class="axis-vertex" cx="${x(h)}" cy="${y(f(h))}" r="3.5" fill="#b6782c"/>
      </g>
      <rect class="axis-handle" x="${x(h) - 30}" y="30" width="60" height="20" rx="10" fill="#b6782c"/>
      <text x="${x(h)}" y="44" text-anchor="middle" fill="#fff" font-size="12">‹ 对称轴 ›</text>
      ${ends.map((value, i) => endpoint(value, values[i])).join('')}
      ${inside ? `<circle class="axis-vertex lowest" cx="${x(h)}" cy="${y(f(h))}" r="6" fill="#b65c42"/><text x="${x(h)}" y="${y(f(h)) + 24}" text-anchor="middle" fill="#a04c36" font-size="14">最低</text>` : ''}`;
  }
  function axisExplorer(spec, h = spec.axis.value) {
    const {bounds, marks = [], title, description, axis, variable = 'x'} = spec;
    const interval = bounded(spec.interval);
    const {x, y} = axisFrame(spec);
    const id = escape(spec.uid);
    return `<div class="axis-explorer">
      <svg viewBox="0 0 360 270" role="img" aria-labelledby="${id}-title ${id}-description">
        <title id="${id}-title">${escape(title)}</title><desc id="${id}-description">${escape(description)}</desc>
        <defs><clipPath id="${id}-clip"><rect x="48" y="48" width="270" height="174"/></clipPath></defs>
        <rect x="48" y="48" width="270" height="174" rx="5" fill="#f0f7f4"/>
        <path d="M25 ${y(0)}H330M${x(0)} 235V35" fill="none" stroke="#9dafaa" stroke-width="1.3"/>
        <path d="m325 ${y(0)-4} 5 4-5 4M${x(0)-4} 40l4-5 4 5" fill="none" stroke="#9dafaa" stroke-width="1.3"/>
        <path class="axis-track" d="M${x(axis.min)} 40H${x(axis.max)}" fill="none" stroke="#ecdcc3" stroke-width="6" stroke-linecap="round"/>
        ${intervalGuides(interval, x)}
        ${marks.map(mark => `<path class="axis-mark" d="M${x(mark.x)} 48V222" fill="none" stroke="#5f86b8" stroke-width="1.6" stroke-dasharray="2 4"/>`).join('')}
        <g fill="#526e64" font-family="Georgia,serif" font-size="14">
          ${[...interval.filter(Number.isFinite).map(value => ({x: value, label: String(value)})), ...marks].map(tick => `<text x="${x(tick.x)}" y="240" text-anchor="middle" fill="${marks.includes(tick) ? '#3f6b9e' : '#526e64'}">${escape(tick.label)}</text>`).join('')}
          <text x="335" y="${y(0)+5}" font-style="italic">${escape(variable)}</text>
          <text x="${x(0)-8}" y="28" text-anchor="end" font-style="italic">y</text>
        </g>
        <g data-axis-layer font-family="Georgia,serif">${axisExplorerLayer(spec, h)}</g>
      </svg>
      <input class="axis-slider" type="range" data-axis-input min="${axis.min}" max="${axis.max}" step="${axis.step}" value="${h}" aria-label="对称轴的位置">
    </div>`;
  }
  window.PracticeComponents = {slot, choices, controls, structure, amgm, completedAmgm, equality, symmetry, substitution, homogeneity, fill, checklist, rewrite, quadraticGraph, reciprocalSumGraph, linearGraph, axisExplorer, axisExplorerLayer, radical, hintIcon};
})();
