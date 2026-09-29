/* Small HTML components; lesson-specific content is passed in as data. */
(() => {
  'use strict';
  const escape = value => String(value).replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]));
  const radical = content => `<span class="radical"><span class="root-sign">√</span><span class="radicand">${content}</span></span>`;
  const hintIcon = '<svg class="hint-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 18h6m-5 3h4M9 15c0-2-3-3-3-7a6 6 0 0 1 12 0c0 4-3 5-3 7v1H9Z"/></svg>';
  function slot({stage, index, value, label, title, occurrence = ''}) {
    const shape = index === 0 ? 'square' : 'circle';
    const name = index === 0 ? '方框' : '圆圈';
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
  function substitution({slot, slotLabels}) {
    return `<div class="visual-board"><div class="board-caption">用和与积定义新变量</div><div class="substitution-definitions">${slotLabels.map((label, index) => `<div class="formula"><span data-math-text>$${escape(label)}$</span><span>=</span>${slot(index, `${label} 对应的`)}</div>`).join('')}</div></div>`;
  }
  // Read-only quadratic in vertex form: coefficient * (x - h)^2 + k.
  // Bounds are the visible window; domain (when supplied) limits the actual curve.
  function quadraticGraph({coefficient, vertex, bounds, domain, excluded = [], xTicks, yLabel, variable, title, description, uid}) {
    const [h, k] = vertex;
    const [xmin, xmax, ymin, ymax] = bounds;
    const x = value => 48 + (value - xmin) / (xmax - xmin) * 270;
    const y = value => 222 - (value - ymin) / (ymax - ymin) * 174;
    const f = value => coefficient * (value - h) ** 2 + k;
    const left = Math.max(xmin, domain?.[0] ?? xmin);
    const right = Math.min(xmax, domain?.[1] ?? xmax);
    const curve = Array.from({length: 101}, (_, i) => {
      const value = left + (right - left) * i / 100;
      return `${i ? 'L' : 'M'}${x(value).toFixed(3)} ${y(f(value)).toFixed(3)}`;
    }).join(' ');
    const id = escape(uid);
    return `<svg viewBox="0 0 360 270" role="img" aria-labelledby="${id}-title ${id}-description">
      <title id="${id}-title">${escape(title)}</title><desc id="${id}-description">${escape(description)}</desc>
      <defs><clipPath id="${id}-clip"><rect x="48" y="48" width="270" height="174"/></clipPath></defs>
      <rect x="48" y="48" width="270" height="174" rx="5" fill="#f0f7f4"/>
      <path d="M25 ${y(0)}H330M${x(0)} 235V35" fill="none" stroke="#9dafaa" stroke-width="1.3"/>
      <path d="m325 ${y(0)-4} 5 4-5 4M${x(0)-4} 40l4-5 4 5" fill="none" stroke="#9dafaa" stroke-width="1.3"/>
      <g clip-path="url(#${id}-clip)">
        <path d="M${x(0)} ${y(k)}H${x(h)}V222" fill="none" stroke="#9abfb5" stroke-width="1.2" stroke-dasharray="4 4"/>
        <path class="quadratic-curve" d="${curve}" fill="none" stroke="#07847d" stroke-width="3"/>
        ${excluded.map(value => `<circle class="quadratic-excluded" cx="${x(value)}" cy="${y(f(value))}" r="4" fill="white" stroke="#07847d" stroke-width="2"/>`).join('')}
        <circle class="quadratic-vertex" cx="${x(h)}" cy="${y(k)}" r="5" fill="#d18a2e"/>
      </g>
      <g fill="#526e64" font-family="Georgia,serif" font-size="14">
        ${xTicks.map(([value, label]) => `<text x="${x(value)}" y="${y(0)+21}" text-anchor="${value === 0 ? 'end' : 'middle'}" dx="${value === 0 ? -8 : 0}">${escape(label)}</text>`).join('')}
        <text x="${x(0)-8}" y="${y(k)+5}" text-anchor="end">${escape(yLabel)}</text>
        <text x="335" y="${y(0)+5}" font-style="italic">${escape(variable)}</text>
        <text x="${x(0)-8}" y="28" text-anchor="end" font-style="italic">y</text>
        <text x="${x(h)+10}" y="${y(k)-13}" fill="#a36920">P(${escape(xTicks.find(([value]) => value === h)?.[1] ?? h)}, ${escape(yLabel)})</text>
      </g>
    </svg>`;
  }
  window.PracticeComponents = {slot, choices, controls, structure, amgm, completedAmgm, equality, symmetry, substitution, quadraticGraph, radical, hintIcon};
})();
