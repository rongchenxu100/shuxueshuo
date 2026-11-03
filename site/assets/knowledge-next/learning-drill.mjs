import {escapeHtml as h} from './resource-links.mjs';
import {learningApi} from './learning-model.mjs';

let dialog, run, source, owner = null, pending = null, busy = false, epoch = 0;
let selected = new Set(), mathReady = null, requestController = new AbortController();
function math(root) {
  root.querySelectorAll('[data-math-text]').forEach(el => window.PracticeMath?.render(el, el.textContent));
}
async function loadMath() {
  mathReady ||= (async () => {
    if (!window.katex) await import('/assets/practice/vendor/katex-0.18.9/katex.min.js');
    if (!window.renderMathInElement) await import('/assets/practice/vendor/katex-0.18.9/auto-render.min.js');
    if (!window.PracticeMath) await import('/assets/practice/math-text.js');
  })().catch(error => { mathReady = null; throw error; });
  await mathReady;
}
function current() {
  return run?.items.find(item => item.position === run.showPosition) || run?.items.find(item => !item.answered_at);
}
function start(previous = null) {
  pending = {path:'/drills', body:{id:crypto.randomUUID(), node_id:source.node,
    drill_version:source.drillVersion, ...(previous ? {previous_attempt_id:previous} : {})}};
  return perform();
}
function shell() {
  if (dialog) return;
  dialog = document.createElement('dialog');
  dialog.className = 'kd-sheet';
  dialog.setAttribute('aria-label', '节点五题检测');
  dialog.innerHTML = '<div class="kd-inner"><header class="kd-head"><h2></h2><button class="kd-close" aria-label="关闭">×</button></header><div class="kd-bar"><span></span></div><div class="kd-body"></div><p class="kd-network" role="status"></p><button class="kd-secondary" data-retry hidden>重试保存</button><button class="kd-secondary" data-refresh hidden>刷新内容</button></div>';
  document.body.append(dialog);
  dialog.addEventListener('click', event => {
    if (event.target.closest('.kd-close')) { dialog.close(); return; }
    if (busy) return;
    if (event.target.closest('[data-refresh]')) { location.reload(); return; }
    if (event.target.closest('[data-retry]')) { perform(); return; }
    if (event.target.closest('[data-restart]')) { start(run?.id); return; }
    if (event.target.closest('[data-next]')) { run.showPosition = null; render(); return; }
    if (pending) return;
    const option = event.target.closest('.kd-option'), item = current();
    if (option && item && !item.answered_at) {
      const value = option.dataset.value;
      if (item.question_type === 'multi') selected.has(value) ? selected.delete(value) : selected.add(value);
      else selected = new Set([value]);
      dialog.querySelectorAll('.kd-option').forEach(button => button.setAttribute('aria-checked', String(selected.has(button.dataset.value))));
      dialog.querySelector('[data-submit]').disabled = !selected.size;
    }
    if (event.target.closest('[data-submit]') && item && selected.size) {
      pending = {path:`/drills/${run.id}/answers/${item.position}`, body:{selected:[...selected]}, position:item.position};
      perform();
    }
  });
  window.addEventListener('site-auth-change', event => {
    if (owner && event.detail.user?.id !== owner) {
      epoch++; requestController.abort(); requestController = new AbortController(); run = pending = owner = null; busy = false; dialog.close();
    }
  });
}
function render() {
  dialog.querySelector('h2').textContent = source.label;
  const body = dialog.querySelector('.kd-body');
  const answered = run.items.filter(item => item.answered_at);
  dialog.querySelector('.kd-bar span').style.width = `${answered.length / 5 * 100}%`;
  if (run.status === 'closed') {
    body.innerHTML = '<p>本轮内容关联已更新，已答记录保留；请重新开练。</p><button class="kd-submit" data-restart>重新开练</button>';
    return;
  }
  const item = current();
  selected = new Set(item?.selected || []);
  if (!item) {
    const correct = answered.filter(item => item.is_correct).length;
    body.innerHTML = `<div class="kd-summary"><p class="kd-summary-title">本轮首答 ${correct} / 5</p><p>${correct === 5 ? '已掌握' : '待巩固'} · 依据本轮五题首答</p><ol>${run.items.map(row => `<li data-math-text>${h(row.statement_md)} · ${row.is_correct ? '答对' : '答错'}</li>`).join('')}</ol><p>下一轮完成后重新评估，掌握状态可以变化。</p></div><button class="kd-submit" data-restart>再练五题</button>`;
  } else {
    body.innerHTML = `<p class="kd-progress">第 ${item.position} / 5 题${item.question_type === 'multi' ? ' · 多选' : ''}</p><p class="kd-question" data-math-text>${h(item.statement_md)}</p><div class="kd-options" role="${item.question_type === 'multi' ? 'group' : 'radiogroup'}" aria-label="选择答案">${item.options.map(option => `<button class="kd-option" role="${item.question_type === 'multi' ? 'checkbox' : 'radio'}" aria-checked="${selected.has(option.value)}" data-value="${h(option.value)}" ${item.answered_at ? 'disabled' : ''}><span class="kd-box"></span><span data-math-text>${h(option.label)}</span></button>`).join('')}</div>${item.answered_at ? `<div class="kd-feedback"><p>${item.is_correct ? '首答正确' : '首答已记录，本题需巩固。'}</p>${(item.feedback || []).map(text => `<p data-math-text>${h(text)}</p>`).join('')}<p data-math-text>正确选择：${h(item.options.filter(option => item.answer.includes(option.value)).map(option => option.label).join('；'))}</p></div><button class="kd-submit" data-next>${run.status === 'completed' ? '查看本轮结果' : '下一题'}</button>` : '<button class="kd-submit" data-submit disabled>提交首答</button>'}`;
  }
  math(body);
}
async function perform() {
  if (!pending || busy) return;
  busy = true;
  const stamp = epoch, request = pending;
  dialog.querySelector('.kd-network').textContent = '正在保存…';
  dialog.querySelector('[data-retry]').hidden = true;
  dialog.querySelector('[data-refresh]').hidden = true;
  try {
    const next = await learningApi(request.path, {body:request.body, user:owner, signal:requestController.signal});
    if (stamp !== epoch) return;
    const completed = request.position != null && next.status === 'completed' &&
      !(run?.id === next.id && run.status === 'completed');
    run = {...next, showPosition:request.position}; pending = null; render();
    dialog.querySelector('.kd-network').textContent = '已保存';
    // Intermediate answers only change this round. Keep the current detail's
    // progress up to date without reloading assessments in this or other tabs.
    window.dispatchEvent(new CustomEvent('learning-drill-progress', {detail:{
      userId:owner, nodeId:source.node, attemptId:run.id, status:run.status,
      answered:run.items.filter(item => item.answered_at).length, total:run.items.length
    }}));
    if (completed) {
      window.dispatchEvent(new CustomEvent('learning-nodes-change'));
      try { localStorage.setItem('sss-learning-change', `${owner}:${run.id}:${Date.now()}`); } catch {}
    }
  } catch (error) {
    if (stamp !== epoch) return;
    const retryable = error.retryable || !error.status;
    dialog.querySelector('.kd-network').textContent = error.message + (retryable ? ' 首答选择已保留，可重试保存。' : ' 请刷新，从服务端确认的记录继续。');
    dialog.querySelector('[data-retry]').hidden = !retryable;
    dialog.querySelector('[data-refresh]').hidden = retryable;
    if (!retryable) pending = null;
  } finally { if (stamp === epoch) busy = false; }
}
export async function openDrill(data) {
  await loadMath();
  shell();
  await window.SiteAuth?.ready;
  const user = await window.SiteAuth?.requireLogin({title:'登录后开始五题检测', intro:'保存首答记录，并在五题全部完成后更新节点状态。'});
  if (!user) return;
  owner = user.id; source = data;
  if (!dialog.open) dialog.showModal();
  if (pending && run?.node_id === data.node) return perform();
  run = null;
  dialog.querySelector('.kd-body').textContent = '正在读取本轮题目…';
  await start();
}
