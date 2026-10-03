import {LearningMark, emptyMark, presentation} from './mark-state.js?v=1';

const css = document.createElement('link');
css.rel = 'stylesheet'; css.href = new URL('./learning-marks.css?v=1', import.meta.url).href;
document.head.append(css);
await import('../auth/site-auth.js?v=4');
await window.SiteAuth?.ready;
const auth = window.SiteAuth;

async function api(path, method, body, user) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(`/api/learning/marks${path}`, {
      method, credentials: 'same-origin', cache: 'no-store', signal: controller.signal,
      headers: {'Content-Type': 'application/json', 'X-Learning-User': user},
      body: body == null ? undefined : JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok) {
      const message = response.status === 401 ? '登录已过期，请登录后重试。'
        : response.status === 409 ? '账号或练习记录已变化，请刷新后重试。'
        : '学习记录暂时无法保存，请稍后重试。';
      throw new Error(message);
    }
    return data;
  } catch (error) {
    if (error.name === 'AbortError' || error instanceof TypeError || error instanceof SyntaxError) {
      throw new Error('暂时无法连接学习记录服务，请稍后重试。');
    }
    throw error;
  } finally { clearTimeout(timer); }
}

const config = document.getElementById('practice-config');
if (config) {
  const {id} = JSON.parse(config.textContent);
  const panel = document.createElement('section');
  panel.id = 'learning-mark'; panel.className = 'learning-mark'; panel.hidden = true;
  panel.setAttribute('aria-label', '本题学习记录');
  panel.innerHTML = `<div class="learning-mark-head"><span class="learning-badge"></span><span class="learning-save" role="status" aria-live="polite"></span></div>
    <h2>这道题，你觉得自己掌握了吗？</h2>
    <p class="learning-note"></p>
    <div class="learning-actions">
      <button type="button" data-learning-status="mastered">已熟练掌握</button>
      <button type="button" data-learning-status="needs_review">还需再练</button>
      <button type="button" class="learning-clear" data-learning-status="unmarked">清除选择</button>
      <button type="button" class="learning-primary" data-learning-login>登录并保存</button>
      <button type="button" data-learning-retry>重试保存</button>
    </div>
    <a class="learning-return">返回题库，继续选题 →</a>`;
  document.getElementById('completion').after(panel);
  panel.querySelector('.learning-return').href = new URL('../', location.href).href;
  let scrolledToMark = false;
  const state = new LearningMark(async (kind, status, user) => {
    const base = `/${encodeURIComponent(id)}`;
    const mark = await api(base + (kind === 'read' ? '' : `/${kind}`), kind === 'read' ? 'GET' : kind === 'complete' ? 'POST' : 'PUT',
      kind === 'read' ? null : kind === 'complete' ? {} : {learning_status: status}, user);
    if (kind !== 'read') {
      try { localStorage.setItem('sss-learning-change', String(Date.now())); } catch { /* Optional tab refresh only. */ }
    }
    return mark;
  }, render);
  function render() {
    panel.hidden = !(state.completedHere || state.mark.practiced || (state.user && state.phase === 'error'));
    if (!panel.hidden && !scrolledToMark && location.hash === '#learning-mark') {
      scrolledToMark = true; requestAnimationFrame(() => panel.scrollIntoView({block: 'center'}));
    }
    const display = presentation(state.mark);
    const badge = panel.querySelector('.learning-badge');
    badge.textContent = state.mark.practiced ? display.label : state.completedHere ? '本题已完成' : '学习记录';
    badge.dataset.tone = state.mark.practiced ? display.tone : 'pending';
    panel.querySelector('.learning-save').textContent = state.phase === 'saving' ? '正在保存…'
      : state.phase === 'loading' ? '正在读取记录…' : state.phase === 'error' ? state.error
      : state.user && state.mark.practiced ? '已保存' : '';
    panel.querySelector('h2').textContent = state.user ? '这道题，你觉得自己掌握了吗？' : '登录后保存这道题的练习记录';
    panel.querySelector('.learning-note').textContent = !state.user ? '登录后会记下你练过这道题，之后可以标记掌握情况；本页不会刷新。'
      : state.mark.learning_status === 'mastered' ? '已标记为掌握，可以返回题库继续学习。'
      : state.mark.learning_status === 'needs_review' ? '已加入需再练的题目，可以再做一次巩固。'
      : '按自己的感受选择，也可以稍后再评。';
    for (const button of panel.querySelectorAll('[data-learning-status]')) {
      button.hidden = !state.user || !state.mark.practiced || (button.dataset.learningStatus === 'unmarked' && state.mark.learning_status === 'unmarked');
      button.disabled = Boolean(state.pending) || ['loading', 'saving'].includes(state.phase);
      button.setAttribute('aria-pressed', String(state.mark.learning_status === button.dataset.learningStatus));
    }
    const login = panel.querySelector('[data-learning-login]');
    login.hidden = Boolean(state.user) && state.phase !== 'error';
    login.textContent = state.user ? '重新确认登录' : '登录并保存';
    panel.querySelector('[data-learning-retry]').hidden = !state.user || state.phase !== 'error';
  }
  panel.addEventListener('click', async event => {
    const button = event.target.closest('button');
    if (!button) return;
    if (button.dataset.learningStatus) return state.choose(button.dataset.learningStatus);
    if (button.hasAttribute('data-learning-retry')) return state.retry();
    if (button.hasAttribute('data-learning-login')) {
      try {
        // Recheck the cookie after a 401/409; requireLogin may trust its cached user.
        await auth.refresh();
        const user = await auth.requireLogin({title: '登录后保存学习记录',
          intro: '登录后会保存这道题的练习记录，当前页面不会刷新。'});
        if (user && state.user === user.id && state.phase === 'error') await state.retry();
      } catch (error) { state.error = error.message; state.phase = 'error'; render(); }
    }
  });
  window.addEventListener('site-auth-change', event => { void state.setUser(event.detail.user?.id || null, event.detail.reason); });
  window.addEventListener('practice-completed', event => { if (event.detail.problemId === id) state.complete(); });
  // The local completion event can precede loading this optional module.
  if (document.getElementById('completion').dataset.learningCompleted === 'true') state.complete();
  void state.setUser(auth?.user?.id || null);
  const refresh = () => { if (!document.hidden && !state.pending) void state.reload(); };
  window.addEventListener('storage', event => { if (event.key === 'sss-learning-change') refresh(); });
  document.addEventListener('visibilitychange', refresh);
  window.addEventListener('pageshow', event => { if (event.persisted) refresh(); });
} else {
  const cards = [...document.querySelectorAll('[data-problem-id]')];
  let generation = 0;
  const notice = document.createElement('p'); notice.className = 'learning-list-notice'; notice.hidden = true;
  notice.setAttribute('role', 'status');
  notice.innerHTML = '<span>暂时无法读取学习记录。</span> <button type="button">重试</button>';
  const summary = document.createElement('p'); summary.className = 'learning-summary'; summary.hidden = true;
  document.querySelector('.bank-heading')?.after(summary, notice);
  for (const card of cards) {
    const spoken = document.createElement('span'); spoken.className = 'visually-hidden learning-spoken';
    card.append(spoken);
    card.dataset.originalHref = card.getAttribute('href');
  }
  let paintedUser = null;
  // The number circle carries the state (fill + border style, never colour alone);
  // unpracticed cards and guests keep the plain circle.
  function paint(marks, user = null) {
    paintedUser = user;
    const counts = {pending: 0, mastered: 0, review: 0};
    let firstPending = null;
    for (const card of cards) {
      const mark = (marks || []).find(row => row.problem_id === card.dataset.problemId) || emptyMark();
      const value = presentation(mark);
      const number = card.querySelector('.problem-number');
      if (marks && mark.practiced) {
        counts[value.tone]++;
        card.dataset.learning = value.tone;
        number.title = value.tone === 'pending' ? '待自评，点击去标记' : value.label;
        card.querySelector('.learning-spoken').textContent = `，${value.label}`;
        if (value.tone === 'pending') firstPending ||= card;
      } else {
        delete card.dataset.learning; number.removeAttribute('title');
        card.querySelector('.learning-spoken').textContent = '';
      }
      card.href = card.dataset.originalHref + (marks && value.tone === 'pending' ? '#learning-mark' : '');
    }
    const practiced = counts.pending + counts.mastered + counts.review;
    summary.hidden = !marks;
    summary.replaceChildren();
    if (!marks) return;
    if (!practiced) { summary.textContent = '完成一道题后，这里会记录你的练习情况。'; return; }
    summary.append(`已练习 ${practiced} / ${cards.length} 题`);
    for (const [tone, label] of [['mastered', '已掌握'], ['review', '需再练'], ['pending', '待自评']]) {
      if (!counts[tone]) continue;
      const item = document.createElement(tone === 'pending' ? 'a' : 'span');
      item.className = 'learning-legend'; item.dataset.tone = tone;
      item.textContent = `${label} ${counts[tone]}`;
      if (tone === 'pending') { item.href = firstPending.href; item.title = '去标记第一道待自评的题'; }
      summary.append(item);
    }
  }
  async function refresh() {
    const ticket = ++generation, user = auth?.user?.id || null;
    notice.hidden = true;
    if (!user || user !== paintedUser) paint(null);
    if (!user) return;
    try {
      const data = await api('', 'GET', null, user);
      if (ticket !== generation) return;
      paint(data.marks, user);
    } catch {
      if (ticket !== generation) return;
      notice.hidden = false;
    }
  }
  notice.querySelector('button').addEventListener('click', refresh);
  window.addEventListener('site-auth-change', refresh);
  window.addEventListener('storage', event => { if (event.key === 'sss-learning-change') void refresh(); });
  window.addEventListener('pageshow', event => { if (event.persisted) void refresh(); });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) void refresh(); });
  void refresh();
}
