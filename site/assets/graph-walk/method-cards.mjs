import {methodConnectionsHTML} from './method-connections.mjs?v=20261101-map';
// Conditions and method choice share one scoped answer; grading never trusts UI confirmation flags.
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

export const emptyMethodAnswer = decision => ({checks: decision.interaction.checks.map(() => ''), method: '', confirmed: 0});
export const methodAnswer = (decision, method) => ({
  checks: decision.interaction.checks.map(check => decision.expected_answer.checks[check.id]),
  method, confirmed: decision.interaction.checks.length,
});
export const selectedMethod = (decision, answer) => decision.interaction.methods?.find(method =>
  method.value === (decision.interaction.type === 'method_cards' ? answer?.method : answer?.[2]));

export function checkMethodAnswers(decision, answer, count = decision.interaction.checks.length) {
  const checks = decision.interaction.checks;
  if (!answer || !Array.isArray(answer.checks) || answer.checks.length !== checks.length ||
      !Number.isInteger(count) || count < 0 || count > checks.length) return '请按顺序完成本题的条件判断。';
  for (let i = 0; i < count; i++) {
    const check = checks[i], value = answer.checks[i];
    if (!check.options.some(option => option.value === value)) return '请先选择一个判断。';
    if (value !== decision.expected_answer.checks[check.id]) return check.feedback;
  }
  return '';
}

export function gradeMethodCards(decision, answer) {
  const error = checkMethodAnswers(decision, answer);
  if (error) return {status: 'wrong', message: error};
  const method = selectedMethod(decision, answer);
  if (!method) return {status: 'wrong', message: '请选择当前提供的一种方法。'};
  const verdict = decision.verdicts?.[method.value];
  if (['unfit', 'not_triggered'].includes(verdict?.value)) return {status: 'wrong', message: verdict.message};
  const alternative = decision.alternatives?.[method.value];
  if (alternative) return {status: 'uncovered', message: alternative.message, href: alternative.href};
  if (!method.route) return {status: 'uncovered', message: '这条路线尚未展开，请选择其他方法。'};
  return {status: 'passed', message: '判断通过，按所选方法继续。'};
}

export function projectMethodAnswer(decision, value) {
  const answer = emptyMethodAnswer(decision);
  if (!value || !Array.isArray(value.checks)) return answer;
  answer.checks = answer.checks.map((_, i) => typeof value.checks[i] === 'string' ? value.checks[i] : '');
  if (decision.interaction.layout === 'connections') {
    // A pending connection represents the student's choice, not a passed premise.
    answer.checks = answer.checks.map((choice, i) => decision.interaction.checks[i].options.some(option => option.value === choice) ? choice : '');
    answer.method = decision.interaction.methods.some(method => method.value === value.method) ? value.method : '';
    return answer;
  }
  const count = Number.isInteger(value.confirmed) ? value.confirmed : 0;
  answer.confirmed = Math.max(0, Math.min(count, answer.checks.length));
  // A stale/forged draft cannot reveal the method picker after a wrong premise.
  if (checkMethodAnswers(decision, answer, answer.confirmed)) answer.confirmed = 0;
  answer.method = answer.confirmed === answer.checks.length && typeof value.method === 'string' ? value.method : '';
  return answer;
}

export function methodCardsHTML(decision, value, interactive = true) {
  const answer = projectMethodAnswer(decision, value), component = decision.interaction;
  if (component.layout === 'connections') return methodConnectionsHTML(decision, answer, interactive);
  const facts = component.facts.map(fact => `<div class="gw-method-fact" data-math-text>${escape(fact)}</div>`).join('');
  const checks = component.checks.map((check, i) => {
    if (interactive && i > answer.confirmed) return '';
    if (!interactive || i < answer.confirmed) return `<div class="gw-method-evidence"><span>✓</span><div data-math-text>${escape(check.resolved)}</div></div>`;
    return `<section class="gw-method-check"><p data-math-text>${escape(check.question)}</p><div class="method-options">${check.options.map(option => `<button type="button" class="method-choice" data-method-check="${i}" data-value="${escape(option.value)}" aria-pressed="${answer.checks[i] === option.value}" data-math-text>${escape(option.label)}</button>`).join('')}</div><button type="button" class="secondary" data-method-confirm="${i}" ${answer.checks[i] ? '' : 'disabled'}>确认判断</button></section>`;
  }).join('');
  const selected = selectedMethod(decision, answer);
  const methods = !interactive ? `<div class="gw-method-picked" data-math-text>${escape(selected?.label || '')}</div><p data-math-text>${escape(decision.verdicts?.[selected?.value]?.message || '')}</p>`
    : answer.confirmed === component.checks.length ? `<div class="gw-method-picker" role="group" aria-label="选择求值域的方法">${component.methods.map(method => {
      const blocked = !method.route || Boolean(decision.alternatives?.[method.value]);
      const message = decision.alternatives?.[method.value]?.message || decision.verdicts?.[method.value]?.message || '';
      return `<button type="button" data-card-method="${escape(method.value)}" aria-pressed="${!blocked && answer.method === method.value}" ${blocked ? 'disabled' : ''}><strong>${escape(method.label)}</strong><span data-math-text>${escape(component.method_notes[method.value] || '')}</span><span class="gw-method-availability ${blocked ? 'is-blocked' : ''}" data-math-text>${escape(blocked ? '本题暂不可用' : '本题可用')} · ${escape(message)}</span></button>`;
    }).join('')}</div>` : '';
  return `<div class="gw-method-cards"><div class="gw-method-facts">${facts}</div>${checks}${methods}</div>`;
}
