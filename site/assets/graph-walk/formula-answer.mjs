// Preview an authored range; correctness remains with the shared choice grader.
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const math = value => `<span data-math-text>$${escape(value)}$</span>`;

export function formulaAnswerHTML(decision, answer, interactive = true) {
  const view = decision.answer_completion;
  if (!view) return '';
  const selected = view.ranges.find(range => range.value === answer);
  const [low, high] = view.bounds, position = value => 50 + (value - low) / (high - low) * 500;
  const range = selected ? (() => {
    const left = selected.left === null ? 24 : position(selected.left);
    const right = selected.right === null ? 576 : position(selected.right);
    const end = (at, closed, direction) => at === null
      ? `<path d="${direction < 0 ? 'M31,36 L24,42 L31,48' : 'M569,36 L576,42 L569,48'}"/>`
      : `<circle cx="${position(at)}" cy="42" r="6" fill="${closed ? 'currentColor' : 'white'}"/>`;
    const holes = (selected.excluded || []).map(at => `<circle class="gw-formula-excluded" cx="${position(at)}" cy="42" r="6" fill="white"/>`).join('');
    return `<g class="gw-formula-range"><path d="M${left},42 H${right}"/>${end(selected.left, selected.left_closed, -1)}${end(selected.right, selected.right_closed, 1)}${holes}</g>`;
  })() : '';
  const line = `<div class="gw-formula-number-line" role="img" aria-label="${escape(selected ? `范围数轴：${selected.condition}` : '范围数轴，等待选择')}">
    <svg viewBox="0 0 600 90" aria-hidden="true"><path class="gw-formula-axis" d="M24,42 H576 M569,37 L576,42 L569,47"/>${view.ticks.map(tick => `<path class="gw-formula-axis" d="M${position(tick.at)},37 V47"/>`).join('')}${range}</svg>
    ${view.ticks.map(tick => `<span class="gw-formula-tick" style="left:${position(tick.at)/6}%">${math(tick.label)}</span>`).join('')}
    <span class="gw-formula-axis-name">${math(view.variable)}</span>
  </div>`;
  const choices = interactive ? `<div class="gw-formula-range-options" role="group" aria-label="选择答案的范围">${decision.interaction.options.map(option => `<button type="button" data-choice="${escape(decision.interaction.field)}" data-value="${escape(option.value)}" aria-label="${escape(option.label)}" aria-pressed="${option.value === answer}">${math(view.ranges.find(row => row.value === option.value).condition)}</button>`).join('')}</div>` : '';
  return `<div class="gw-formula-answer${interactive ? '' : ' is-complete'}">
    ${interactive ? `<div class="gw-formula-given"><span>前面已经得到</span><p data-math-text>${escape(view.given)}</p></div>` : ''}
    <div class="gw-formula-answer-preview" aria-live="polite"><div class="gw-formula-answer-expression">${math(view.formula)}<span>，</span><span class="gw-formula-range-slot${selected ? ' is-filled' : ''}">${selected ? math(selected.condition) : '选择范围'}</span></div>
    ${line}<p class="gw-formula-preview-label">${interactive ? selected ? '当前选择 · 确认后检查答案' : '点选下方范围，补全答案并查看数轴。' : '答案范围'}</p></div>
    ${choices}
    ${interactive ? '' : `<p class="gw-formula-reminder" data-math-text>${escape(view.reminder)}</p>`}
    <details class="gw-formula-coverage"><summary>为什么这个范围都能取到？</summary><p data-math-text>${escape(view.coverage)}</p></details>
  </div>`;
}
