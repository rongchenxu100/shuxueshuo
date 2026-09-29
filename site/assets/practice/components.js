/* Small HTML components; lesson-specific content is passed in as data. */
(() => {
  'use strict';
  const escape = value => String(value).replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]));
  const radical = content => `<span class="radical"><span class="root-sign">√</span><span class="radicand">${content}</span></span>`;
  const hintIcon = '<svg class="hint-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 18h6m-5 3h4M9 15c0-2-3-3-3-7a6 6 0 0 1 12 0c0 4-3 5-3 7v1H9Z"/></svg>';
  function slot({stage, index, value, title, occurrence = ''}) {
    const shape = index === 0 ? 'square' : 'circle';
    const name = index === 0 ? '方框' : '圆圈';
    return `<button type="button" class="shape ${shape} ${value ? '' : 'empty'}" data-stage="${stage}" data-slot="${index}" data-occurrence="${escape(occurrence)}" aria-haspopup="dialog" aria-expanded="false" aria-label="${escape(title)}：${escape(occurrence)}${name}，${escape(value || '未填写')}">${escape(value || '?')}</button>`;
  }
  function choices(component, selected, title) {
    return `<div class="method-options" role="group" aria-label="${escape(title)}">${component.options.map(({value, label}) => `<button type="button" class="method-choice" data-choice="${escape(component.field)}" data-value="${escape(value)}" aria-pressed="${selected === value}"><span class="radio-mark" aria-hidden="true"></span><span data-math-text>${escape(label)}</span></button>`).join('')}</div>`;
  }
  function controls({stage, label, ready, feedback, hint}) {
    return `<div class="actions"><button type="button" class="primary" data-submit="${stage}" ${ready ? '' : 'disabled'}>${escape(label)} <span aria-hidden="true">→</span></button><button type="button" class="hint-button" data-hint="${stage}">${hintIcon}给点提示</button></div>${feedback ? `<p class="feedback ${hint ? 'helper-feedback' : ''}">${escape(feedback)}</p>` : ''}`;
  }
  function structure({slot, swapped}) {
    return `<div class="visual-board">
      <div class="structure-row"><span class="row-label">条件</span><div class="formula">${slot(0, '条件中的')}<span>${swapped ? '·' : '+'}</span>${slot(1, '条件中的')}</div><span class="row-tag">${swapped ? '定积' : '定和'}</span></div>
      <div class="swap-row"><button type="button" class="swap-button" id="swap" aria-label="交换和与积" aria-pressed="${swapped}"><span class="swap-icon" aria-hidden="true">⇅</span>交换和与积</button></div>
      <div class="structure-row"><span class="row-label">目标</span><div class="formula">${slot(0, '目标中的')}<span>${swapped ? '+' : '·'}</span>${slot(1, '目标中的')}</div><span class="row-tag">${swapped ? '求最小值' : '求最大值'}</span></div>
    </div>`;
  }
  function amgm({slot, terms}) {
    return `<div class="positive-tags">${terms.map(term => `<span class="math"><i>${escape(term)}</i> &gt; 0 <span aria-hidden="true">✓</span></span>`).join('')}</div>
      <div class="visual-board application-board"><div class="board-caption">基本不等式</div>
      <div class="formula" aria-label="方框加圆圈，大于等于二倍根号下方框乘圆圈">${slot(0, '左侧')}<span>+</span>${slot(1, '左侧')}<span>≥</span><span>2</span>${radical(`${slot(0, '根号中的')}<span class="multiply">·</span>${slot(1, '根号中的')}`)}</div></div>`;
  }
  function equality({slot}) {
    return `<div class="visual-board equality-board"><div class="board-caption">基本不等式取等</div><div class="formula">${slot(0)}<span class="equal-sign">=</span>${slot(1)}</div></div>`;
  }
  window.PracticeComponents = {slot, choices, controls, structure, amgm, equality, radical, hintIcon};
})();
