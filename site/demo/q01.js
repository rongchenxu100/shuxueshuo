/* Q01 renderer; the tutor API owns session state and validates all student events. */
(() => {
  'use strict';
  let titles = ['观察结构', '应用基本不等式', '验证取等'];
  let methods = [];
  let methodGuidance = {};
  let lesson = null;
  const steps = document.querySelector('#steps');
  const picker = document.querySelector('#picker');
  const attemptHistory = document.querySelector('#attempt-history');
  const announcement = document.querySelector('#announcement');
  const freshState = () => ({ active: 0, method: null, swapped: false, pairs: [['', ''], ['', ''], ['', '']], elimination: { variable: null, technique: null, feasible: null }, feedback: '', hint: false });
  let state = freshState();
  let picking = null;
  let snapshot = null;
  let busy = false;
  let generation = 0;
  let requestController = null;
  let retryRequest = null;
  const local = ['localhost', '127.0.0.1'].includes(location.hostname);
  const api = local && location.port === '8765' ? `${location.protocol}//${location.hostname}:8766/api/tutor-demo` : '/api/tutor-demo';
  const messageInput = document.querySelector('#message');
  const sendButton = document.querySelector('.send-button');
  const networkStatus = document.querySelector('#network-status');
  const retryButton = document.querySelector('#request-retry');
  const escapeHTML = (text) => String(text).replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]));

  function updateBusy() {
    const blocked = busy || !snapshot || Boolean(retryRequest);
    for (const button of [...steps.querySelectorAll('button'), ...document.querySelectorAll('[data-switch-route]'), ...picker.querySelectorAll('button')]) {
      if (!button.hasAttribute('data-initial-disabled')) button.dataset.initialDisabled = String(button.disabled);
      button.disabled = blocked || button.dataset.initialDisabled === 'true';
    }
    sendButton.disabled = busy || !snapshot || Boolean(retryRequest) || !messageInput.value.trim();
    messageInput.disabled = busy;
    steps.setAttribute('aria-busy', String(busy));
  }

  function conversation(stage, attempt = null) {
    const attemptId = attempt?.id || snapshot?.attempt_id;
    const messages = (attempt?.messages || snapshot?.messages || []).filter(m => m.attempt_id === attemptId && m.stage === stage && m.kind !== 'ui');
    if (!messages.length) return '';
    const content = `<div class="node-conversation" aria-label="本步骤的对话">${messages.map(m => `<div class="chat-message ${m.role === 'student' ? 'student' : 'assistant'}"><span class="chat-author">${m.role === 'student' ? '你' : '老师'}</span><p>${escapeHTML(m.text)}</p></div>`).join('')}</div>`;
    if (attempt || stage < state.active) return `<details class="conversation-history" id="conversation-${attemptId}-${stage}"><summary>查看本步对话<span class="conversation-count">${messages.length} 条</span></summary>${content}</details>`;
    return content;
  }

  function acceptSnapshot(data) {
    if (snapshot?.session_id === data.session_id && data.revision < snapshot.revision) return;
    const changedAttempt = snapshot && snapshot.attempt_id !== data.attempt_id;
    if (changedAttempt) {
      pauseIdle();
      invitedQuestions.clear();
      idleQuestion = null;
    }
    snapshot = data;
    state = data.state;
    lesson = data.lesson;
    methods = lesson.methods.map(method => method.label);
    methodGuidance = lesson.method_guidance;
    document.querySelector('.problem-card > p').innerHTML = lesson.problem.segments.map(segment => segment.math
      ? `<span class="math nowrap">${escapeHTML(segment.math).replace(/[mn]/g, '<i>$&</i>')}</span>` : escapeHTML(segment.text)).join('');
    render();
  }

  async function request(payload = null) {
    if (busy) return;
    const thisGeneration = generation;
    const oldActive = state.active;
    const oldAttempt = snapshot?.attempt_id;
    const oldSession = snapshot?.session_id;
    const controller = new AbortController();
    requestController = controller;
    const timeout = setTimeout(() => controller.abort(), 55000);
    busy = true;
    pauseIdle();
    retryRequest = null;
    retryButton.hidden = true;
    networkStatus.textContent = payload?.kind === 'text' || payload?.kind === 'help' ? '老师正在思考…' : !snapshot ? '正在准备题目…' : '';
    updateBusy();
    try {
      const response = await fetch(payload ? `${api}/sessions/${oldSession}/events` : `${api}/sessions`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload || {lesson_id: 'q01'}), signal: controller.signal
      });
      const data = await response.json();
      if (thisGeneration !== generation) return;
      if (!response.ok) {
        if (response.status === 409 && data.snapshot) {
          acceptSnapshot(data.snapshot);
          networkStatus.textContent = data.detail;
          return;
        }
        throw new Error(typeof data.detail === 'string' ? data.detail : '暂时无法连接，请重试。');
      }
      acceptSnapshot(data);
      if (payload?.kind === 'text') messageInput.value = '';
      networkStatus.textContent = '';
      if (state.active > oldActive || (oldAttempt && oldAttempt !== snapshot.attempt_id)) {
        requestAnimationFrame(() => {
          const target = document.querySelector(state.active === 3 ? '.completion-card' : `#step-${state.active}`);
          target?.scrollIntoView({behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'center'});
        });
      } else if (payload?.kind === 'text' || payload?.kind === 'help') {
        document.querySelector(state.active === 3 ? '#completion .chat-message:last-child' : `#step-${state.active} .chat-message:last-child`)?.scrollIntoView({behavior: 'smooth', block: 'center'});
      }
      const last = data.messages.at(-1);
      announce(last?.role === 'assistant' ? last.text : '已保存你的选择。');
    } catch (error) {
      if (thisGeneration !== generation) return;
      retryRequest = {payload};
      retryButton.hidden = false;
      networkStatus.textContent = error.name === 'AbortError' ? '回复超时，请重试。你的输入已保留。' : (error.message === 'Failed to fetch' ? '连接暂时中断，请重试。你的输入已保留。' : error.message);
    } finally {
      clearTimeout(timeout);
      if (thisGeneration === generation) {
        busy = false;
        updateBusy();
        resumeIdle();
      }
    }
  }

  function sendEvent(kind, action = null, text = '') {
    if (!snapshot || busy || retryRequest) return;
    closePicker();
    request({event_id: crypto.randomUUID(), revision: snapshot.revision, kind, action, text});
  }

  function restart() {
    generation += 1;
    requestController?.abort();
    busy = false;
    snapshot = null;
    retryRequest = null;
    pauseIdle();
    invitedQuestions.clear();
    idleQuestion = null;
    state = freshState();
    messageInput.value = '';
    steps.innerHTML = '';
    attemptHistory.innerHTML = '';
    document.querySelector('#completion').hidden = true;
    document.querySelector('#progress-fill').style.width = '0%';
    window.scrollTo({top: 0, behavior: 'instant'});
    request();
  }

  retryButton.addEventListener('click', () => {
    const pending = retryRequest;
    if (pending) request(pending.payload);
  });
  sendButton.addEventListener('click', () => sendEvent('text', null, messageInput.value.trim()));
  messageInput.addEventListener('input', updateBusy);
  messageInput.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      if (!sendButton.disabled) sendButton.click();
    }
  });
  const idleDelay = 10_000;
  const invitedQuestions = new Set();
  let idleQuestion = null;
  let idleTimer = null;
  let idleStartedAt = 0;
  let idleRemaining = idleDelay;

  function currentQuestion() {
    if (state.active >= 3) return null;
    if (state.method === '1') return `elimination-${state.active}`;
    if (state.active === 0) return !state.method ? 'method' : state.method === 'direct' ? 'structure' : null;
    return state.active === 1 ? 'inequality' : 'equality';
  }

  function pauseIdle() {
    if (idleTimer !== null) {
      clearTimeout(idleTimer);
      idleRemaining = Math.max(0, idleRemaining - (performance.now() - idleStartedAt));
      idleTimer = null;
    }
  }

  function hideIdleInvitation() {
    steps.querySelector('.idle-invitation')?.remove();
    steps.querySelector('.hint-button.idle-highlight')?.classList.remove('idle-highlight');
  }

  function resumeIdle() {
    if (busy || retryRequest || idleTimer !== null || !idleQuestion || invitedQuestions.has(idleQuestion) || document.hidden || document.activeElement?.id === 'message') return;
    idleStartedAt = performance.now();
    idleTimer = setTimeout(() => {
      idleTimer = null;
      const hint = steps.querySelector('.step-card.active .hint-button');
      if (!hint || document.hidden || document.activeElement?.id === 'message') return;
      invitedQuestions.add(idleQuestion);
      hint.classList.add('idle-highlight');
      hint.insertAdjacentHTML('afterend', '<span class="idle-invitation" role="status">需要一点提示吗？</span>');
    }, idleRemaining);
  }

  function recordActivity() {
    pauseIdle();
    hideIdleInvitation();
    idleRemaining = idleDelay;
    resumeIdle();
  }

  function syncIdleQuestion() {
    const question = currentQuestion();
    if (question !== idleQuestion) {
      pauseIdle();
      idleQuestion = question;
      idleRemaining = idleDelay;
    }
    resumeIdle();
  }

  const radical = (content) => `<span class="radical"><span class="root-sign">√</span><span class="radicand">${content}</span></span>`;
  const hintIcon = '<svg class="hint-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 18h6m-5 3h4M9 15c0-2-3-3-3-7a6 6 0 0 1 12 0c0 4-3 5-3 7v1H9Z"/></svg>';
  const isElimination = () => state.method === '1';
  const ready = (stage) => isElimination() ? state.elimination[['variable', 'technique', 'feasible'][stage]] !== null : state.pairs[stage].every(Boolean);
  const announce = (text) => { announcement.textContent = text; };

  function slot(stage, index, occurrence = '') {
    const value = state.pairs[stage][index];
    const shape = index === 0 ? 'square' : 'circle';
    const name = index === 0 ? '方框' : '圆圈';
    return `<button type="button" class="shape ${shape} ${value ? '' : 'empty'}" data-stage="${stage}" data-slot="${index}" data-occurrence="${occurrence}" aria-haspopup="dialog" aria-expanded="false" aria-label="${titles[stage]}：${occurrence}${name}，${value || '未填写'}">${value || '?'}</button>`;
  }

  // Separate read-only renderer: never contains editable slots or student action handlers.
  function displayShape(value, index) {
    return `<span class="shape ${index === 0 ? 'square' : 'circle'}">${value}</span>`;
  }

  function controls(stage, label) {
    return `<div class="actions"><button type="button" class="primary" data-submit="${stage}" ${ready(stage) ? '' : 'disabled'}>${label} <span aria-hidden="true">→</span></button><button type="button" class="hint-button" data-hint="${stage}">${hintIcon}给点提示</button></div>${state.feedback ? `<p class="feedback ${state.hint ? 'helper-feedback' : ''}">${escapeHTML(state.feedback)}</p>` : ''}`;
  }

  function eliminationChoices(key, choices) {
    return `<div class="method-options" role="group" aria-label="${titles[state.active]}">${choices.map(([value, label]) => `<button type="button" class="method-choice" data-elimination-choice="${key}" data-value="${value}" aria-pressed="${state.elimination[key] === value}"><span class="radio-mark" aria-hidden="true"></span>${label}</button>`).join('')}</div>`;
  }

  function renderEliminationInteraction(stage) {
    const v = state.elimination.variable || 'm';
    if (stage === 0) return `<p class="question">利用 <span class="math"><i>m</i> + <i>n</i> = 2</span>，你准备怎样消去一个变量？</p>
      ${eliminationChoices('variable', [['m', '<span class="math"><i>n</i> = 2 − <i>m</i></span>'], ['n', '<span class="math"><i>m</i> = 2 − <i>n</i></span>']])}${controls(0, '确认消元')}`;
    if (stage === 1) return `<p class="question">怎样判断这个二次式的最大值？</p>
      <div class="visual-board"><div class="board-caption">消元后的目标式</div><div class="formula"><span><i>mn</i> = 2<i>${v}</i> − <i>${v}</i><sup>2</sup></span></div></div>
      ${eliminationChoices('technique', [['square', '配方，看平方项的取值'], ['vertex', '利用二次函数的顶点']])}${controls(1, '确认思路')}`;
    return `<p class="question">这个取值满足原题的所有条件吗？</p>
      <div class="visual-board"><div class="board-caption">取得上界时的取值</div><div class="formula"><i>m</i> = <i>n</i> = 1</div></div>
      ${eliminationChoices('feasible', [['yes', '满足：两数为正，且和为 2'], ['no', '不满足原题条件']])}${controls(2, '确认验证')}`;
  }

  function renderVertexSolution(v, other, graphId = `quadratic-${snapshot.attempt_id}`) {
    return `<div class="visual-board completed-visual">
      <div class="board-caption">从二次式的最值，转化为二次函数的最值</div>
      <div class="function-conversion">
        <div><span class="conversion-label">二次式求最大值</span><div class="math">(2<i>${v}</i> − <i>${v}</i><sup>2</sup>)<sub>max</sub></div></div>
        <span class="conversion-arrow" aria-hidden="true">→</span>
        <div><span class="conversion-label">二次函数求最大值</span><div class="math"><i>y</i> = −<i>${v}</i><sup>2</sup> + 2<i>${v}</i></div><span class="conversion-label">求 <span class="math"><i>y</i><sub>max</sub></span>，其中 <span class="math">0 &lt; <i>${v}</i> &lt; 2</span></span></div>
      </div>
    </div>
    <div class="reasoning vertex-reasoning">
      <div><span class="section-label">系统计算 · 二次函数求最值</span>
        <p class="math">令 <i>y</i> = <i>mn</i> = −<i>${v}</i><sup>2</sup> + 2<i>${v}</i>。</p>
        <p class="math">∵ 二次项系数 −1 &lt; 0，抛物线开口向下。</p>
        <p class="math">对称轴：<i>${v}</i> = −2 ÷ (2 × (−1)) = 1</p>
        <p class="math">∵ 1 ∈ (0, 2)，顶点在定义域内。</p>
        <p class="math">∴ <i>y</i><sub>max</sub> = −(1)<sup>2</sup> + 2 × 1 = 1</p>
        <p class="math">即 <i>mn</i> ≤ 1，在 <i>${v}</i> = 1 时取等。</p>
        <p class="math">代回 <i>${other}</i> = 2 − <i>${v}</i>，得 <i>${other}</i> = 1。</p>
      </div>
      <figure class="quadratic-graph">
        <svg viewBox="0 0 360 270" role="img" aria-labelledby="${graphId}-title ${graphId}-description">
          <title id="${graphId}-title">y 等于负 ${v} 平方加 2${v} 的图像</title>
          <desc id="${graphId}-description">横轴为 ${v}，纵轴为 y，也就是 mn。定义域为 0 到 2 的开区间，两端用空心点表示。抛物线开口向下，顶点为 (1,1)，在 ${v} 等于 1 时取得最大值 1。</desc>
          <rect x="60" y="48" width="220" height="162" rx="5" fill="#f0f7f4"/>
          <path d="M25 210H326M60 240V30" fill="none" stroke="#9dafaa" stroke-width="1.3"/>
          <path d="m321 206 5 4-5 4M56 35l4-5 4 5" fill="none" stroke="#9dafaa" stroke-width="1.3"/>
          <path d="M60 75H170V210" fill="none" stroke="#9abfb5" stroke-width="1.2" stroke-dasharray="4 4"/>
          <path d="M60 210Q170 -60 280 210" fill="none" stroke="#07847d" stroke-width="3"/>
          <g fill="white" stroke="#07847d" stroke-width="2"><circle cx="60" cy="210" r="4"/><circle cx="280" cy="210" r="4"/></g>
          <circle cx="170" cy="75" r="5" fill="#d18a2e"/>
          <g fill="#526e64" font-family="Georgia,serif" font-size="14">
            <text x="43" y="230">0</text><text x="166" y="230">1</text><text x="276" y="230">2</text><text x="42" y="80">1</text>
            <text x="333" y="215" font-style="italic">${v}</text><text x="43" y="24" font-style="italic">y</text>
            <text x="185" y="66" fill="#a36920">P(1, 1)</text>
            <text x="110" y="27">y = −${v}² + 2${v}</text>
            <text x="136" y="256">0 &lt; ${v} &lt; 2</text>
          </g>
        </svg>
        <figcaption>纵轴 <span class="math"><i>y</i> = <i>mn</i></span>；空心点表示端点不取。</figcaption>
      </figure>
    </div><p class="calculation-note">还需要检查这个取值是否满足原题条件。</p>`;
  }

  function renderEliminationDisplay(stage, displayState = state, prefix = snapshot.attempt_id) {
    const v = displayState.elimination.variable;
    const other = v === 'm' ? 'n' : 'm';
    if (stage === 0) return `<div class="selected-method"><span>你选择的方案</span><span class="method-pill">条件消元法</span></div>
      <div class="visual-board completed-visual"><div class="board-caption">消去一个变量</div><div class="formula"><span><i>${other}</i> = 2 − <i>${v}</i></span></div></div>
      <div class="reasoning"><span class="section-label">系统计算 · 代入目标式</span><p class="math"><i>mn</i> = <i>${v}</i>(2 − <i>${v}</i>) = 2<i>${v}</i> − <i>${v}</i><sup>2</sup></p><p class="math">∵ <i>${v}</i> &gt; 0，2 − <i>${v}</i> &gt; 0</p><p class="math">∴ 0 &lt; <i>${v}</i> &lt; 2</p></div>`;
    if (stage === 1) {
      if (displayState.elimination.technique === 'vertex') return renderVertexSolution(v, other, `quadratic-${prefix}`);
      return `<div class="visual-board completed-visual"><div class="board-caption">配方：把二次式转化为“常数 − 平方项”</div>
        <div class="function-conversion">
          <div><span class="conversion-label">二次式求最大值</span><div class="math">(2<i>${v}</i> − <i>${v}</i><sup>2</sup>)<sub>max</sub></div></div>
          <span class="conversion-arrow" aria-hidden="true">→</span>
          <div><span class="conversion-label">平方项越小，原式越大</span><div class="math">1 − <span class="square-term">(<i>${v}</i> − 1)<sup>2</sup></span></div><span class="conversion-label">平方项 ≥ 0，所以原式 ≤ 1</span></div>
        </div></div>
        <div class="reasoning"><span class="section-label">系统计算 · 配方求上界</span>
        <p class="math"><i>mn</i> = 2<i>${v}</i> − <i>${v}</i><sup>2</sup></p>
        <p class="math">= −(<i>${v}</i><sup>2</sup> − 2<i>${v}</i> + 1) + 1</p>
        <p class="math">= 1 − (<i>${v}</i> − 1)<sup>2</sup></p>
        <p class="math">∵ (<i>${v}</i> − 1)<sup>2</sup> ≥ 0</p>
        <p class="math">∴ <i>mn</i> ≤ 1</p>
        <p class="math">等号成立 ⇔ (<i>${v}</i> − 1)<sup>2</sup> = 0 ⇔ <i>${v}</i> = 1。</p>
        <p class="math">代回 <i>${other}</i> = 2 − <i>${v}</i>，得到 <i>${other}</i> = 1。</p></div><p class="calculation-note">还需要检查这个取值是否满足原题条件。</p>`;
    }
    return `<div class="visual-board completed-visual"><div class="board-caption">满足原题条件</div><div class="formula"><i>m</i> = <i>n</i> = 1</div></div>
      <div class="reasoning"><span class="section-label">系统计算 · 验证取值</span><p class="math">✓ <i>m</i> = 1 &gt; 0，<i>n</i> = 1 &gt; 0</p><p class="math">✓ <i>m</i> + <i>n</i> = 1 + 1 = 2</p><p class="math">∴ <i>mn</i> = 1，上界可以取到。</p></div>`;
  }

  function renderInteraction(stage) {
    if (isElimination() && stage > 0) return renderEliminationInteraction(stage);
    if (stage === 0 && !state.method) {
      return `<p class="question">这道题，你准备采用哪种解题方案？</p>
        <div class="method-options">${methods.map((text, index) => `<button type="button" class="method-choice" data-method="${index}"><span class="radio-mark" aria-hidden="true"></span>${text}<span class="option-arrow" aria-hidden="true">›</span></button>`).join('')}</div>
        <button type="button" class="hint-button" data-hint="0">${hintIcon}还没想好，给点提示</button>${state.feedback ? `<p class="feedback ${state.hint ? 'helper-feedback' : ''}">${escapeHTML(state.feedback)}</p>` : ''}`;
    }
    if (stage === 0) {
      const options = `<div class="method-tabs" role="group" aria-label="解题方案">${methods.map((label, index) => `<button type="button" class="method-tab" data-method="${index}" aria-pressed="${state.method === (index === 0 ? 'direct' : String(index))}">${label}</button>`).join('')}</div>`;
      if (isElimination()) return options + renderEliminationInteraction(stage);
      if (state.method !== 'direct') {
        const guidance = methodGuidance[state.method];
        return `${options}<div class="method-guidance" role="status"><h3>${guidance.title || `${methods[Number(state.method)]}：本题不优先采用`}</h3><p>${guidance.context}</p><p>${guidance.reason}</p></div><p class="question">${guidance.question}</p>`;
      }
      return `${options}
        <p class="question">定和求积还是定积求和？</p>
        <div class="visual-board">
          <div class="structure-row"><span class="row-label">条件</span><div class="formula">${slot(0, 0, '条件中的')}<span>${state.swapped ? '·' : '+'}</span>${slot(0, 1, '条件中的')}</div><span class="row-tag">${state.swapped ? '定积' : '定和'}</span></div>
          <div class="swap-row"><button type="button" class="swap-button" id="swap" aria-label="交换和与积" aria-pressed="${state.swapped}"><span class="swap-icon" aria-hidden="true">⇅</span>交换和与积</button></div>
          <div class="structure-row"><span class="row-label">目标</span><div class="formula">${slot(0, 0, '目标中的')}<span>${state.swapped ? '+' : '·'}</span>${slot(0, 1, '目标中的')}</div><span class="row-tag">${state.swapped ? '求最小值' : '求最大值'}</span></div>
        </div>${controls(0, '确认结构')}`;
    }
    if (stage === 1) {
      return `<p class="question">对 <span class="math"><i>m</i>、<i>n</i></span> 应用基本不等式，能得到什么关系？</p>
        <div class="positive-tags"><span class="math"><i>m</i> &gt; 0 <span aria-hidden="true">✓</span></span><span class="math"><i>n</i> &gt; 0 <span aria-hidden="true">✓</span></span></div>
        <div class="visual-board application-board"><div class="board-caption">基本不等式</div>
          <div class="formula" aria-label="方框加圆圈，大于等于二倍根号下方框乘圆圈">${slot(1, 0, '左侧')}<span>+</span>${slot(1, 1, '左侧')}<span>≥</span><span>2</span>${radical(`${slot(1, 0, '根号中的')}<span class="multiply">·</span>${slot(1, 1, '根号中的')}`)}</div>
        </div>${controls(1, '确认代入')}`;
    }
    return `<p class="question">什么条件下，刚才的基本不等式能取等号？</p>
      <div class="visual-board equality-board"><div class="board-caption">基本不等式取等</div><div class="formula">${slot(2, 0)}<span class="equal-sign">=</span>${slot(2, 1)}</div></div>
      ${controls(2, '确认取等')}`;
  }

  function renderDisplay(stage, displayState = state, prefix = '') {
    if (displayState.method === '1') return renderEliminationDisplay(stage, displayState, prefix || snapshot.attempt_id);
    const [a, b] = displayState.pairs[stage];
    if (stage === 0) {
      return `<div class="selected-method"><span>你选择的方案</span><span class="method-pill">直接应用基本不等式</span></div>
        <div class="visual-board completed-visual"><div class="structure-summary"><div class="summary-item"><span class="summary-label">定和</span><div class="formula">${displayShape(a, 0)} + ${displayShape(b, 1)}</div></div><span class="flow-arrow" aria-hidden="true">→</span><div class="summary-item"><span class="summary-label">求积</span><div class="formula">${displayShape(a, 0)} · ${displayShape(b, 1)}</div></div></div></div>
        <div class="reasoning"><span class="section-label">根据你的选择，整理思路</span><p><span class="reason-symbol">∵</span><span class="math"><i>m</i>, <i>n</i> &gt; 0，<i>m</i> + <i>n</i> = 2</span>，目标是求 <span class="math"><i>mn</i></span> 的最大值。</p><p><span class="reason-symbol">∴</span>定和求积，可以直接应用基本不等式。</p></div>`;
    }
    if (stage === 1) {
      return `<div class="visual-board completed-visual"><div class="board-caption">基本不等式</div><div class="formula">${displayShape(a, 0)} + ${displayShape(b, 1)} ≥ 2${radical(`<i>${a}${b}</i>`)}</div></div>
        <details class="details" id="${prefix}derivation-${stage}" open><summary>完整推导</summary><p class="math">∵ <i>m</i> &gt; 0，<i>n</i> &gt; 0</p><p class="math">∴ <i>m</i> + <i>n</i> ≥ 2${radical('<i>mn</i>')}</p><p class="math">∵ <i>m</i> + <i>n</i> = 2</p><p class="math">∴ 2 ≥ 2${radical('<i>mn</i>')}</p><p class="math">∴ 1 ≥ ${radical('<i>mn</i>')}，<i>mn</i> ≤ 1</p></details><p class="calculation-note">上界已经得到，还需要检查它能否取到。</p>`;
    }
    return `<div class="visual-board completed-visual"><div class="board-caption">你给出的取等条件</div><div class="formula">${displayShape(a, 0)} <span class="equal-sign">=</span> ${displayShape(b, 1)}</div></div>
      <div class="reasoning"><span class="section-label">系统计算 · 验证取等</span><p><span class="reason-symbol">∵</span><span class="math"><i>m</i> = <i>n</i>，<i>m</i> + <i>n</i> = 2</span></p><p><span class="reason-symbol">∴</span><span class="math"><i>m</i> = <i>n</i> = 1</span></p><p><span class="reason-symbol">✓</span>满足两数为正、和为 2，且 <span class="math"><i>mn</i> = 1</span>。上界可以取到。</p></div>`;
  }

  function renderAttemptHistory() {
    const previous = (snapshot.attempts || []).filter(attempt => attempt.id !== snapshot.attempt_id);
    attemptHistory.innerHTML = previous.map((attempt, index) => {
      const label = lesson.methods.find(method => method.id === attempt.route)?.label || '方案探索';
      const nodes = lesson.routes[attempt.route] || lesson.routes.direct;
      const completed = attempt.completed.map(record => `<section class="archived-node"><h3>${escapeHTML(nodes[record.stage].title)}</h3>${renderDisplay(record.stage, attempt.state, `${attempt.id}-`)}${conversation(record.stage, attempt)}</section>`).join('');
      const pending = attempt.status !== 'completed' ? `<p class="archived-position">停在：${escapeHTML(nodes[attempt.state.active]?.title || '选择方案')}（未完成）</p>` : '';
      return `<details class="attempt-history-card" id="attempt-${attempt.id}"><summary>第 ${index + 1} 次尝试 · ${escapeHTML(label)}<span class="attempt-status">${attempt.status === 'completed' ? '已完成' : '已保留进度'}</span></summary>${completed}${pending}${conversation(attempt.state.active, attempt)}</details>`;
    }).join('');
  }

  function render() {
    closePicker();
    titles = lesson.routes[isElimination() ? '1' : 'direct'].map(node => node.title);
    const detailStates = new Map([...document.querySelectorAll('.workspace details[id]')].map(el => [el.id, el.open]));
    renderAttemptHistory();
    steps.innerHTML = titles.map((title, stage) => {
      if (stage > state.active) return '';
      const done = stage < state.active;
      return `<article class="step-card ${done ? 'done' : 'active'}" id="step-${stage}" aria-labelledby="step-title-${stage}"><header class="step-heading"><span class="step-number" aria-hidden="true">${done ? '✓' : stage + 1}</span><h2 id="step-title-${stage}" tabindex="-1">${title}</h2><span class="status">${done ? '已完成' : '进行中'}</span></header>${done ? renderDisplay(stage) : renderInteraction(stage)}${conversation(stage)}</article>`;
    }).join('');
    document.querySelector('#progress-fill').style.width = `${state.active / 3 * 100}%`;
    document.querySelector('#conversation-focus').textContent = state.active === 3 ? '本题已完成' : `正在讨论：${titles[state.active]}`;
    const completion = document.querySelector('#completion');
    completion.hidden = state.active !== 3;
    completion.innerHTML = state.active === 3 ? '<section class="completion-card" tabindex="-1"><h2><span class="math"><i>mn</i></span> 的最大值为 <span class="math">1</span></h2><p>当 <span class="math"><i>m</i> = <i>n</i> = 1</span> 时取到。</p></section>' : '';
    if (state.active === 3 && isElimination()) completion.insertAdjacentHTML('beforeend', `<aside class="route-comparison"><h3>再看一种思路</h3><p>你用条件消元，把目标转成了二次式。观察到两正数的和固定，也可以直接用基本不等式得到上界。</p><p class="math">2 = <i>m</i> + <i>n</i> ≥ 2${radical('<i>mn</i>')}，所以 <i>mn</i> ≤ 1。</p><p>两种方法都在 <span class="math"><i>m</i> = <i>n</i> = 1</span> 时取得最大值。</p></aside>`);
    if (state.active === 3) {
      const routes = lesson.methods.filter(method => lesson.routes[method.id] && method.id !== state.method);
      completion.insertAdjacentHTML('beforeend', `<div class="route-actions">${routes.map(method => `<button type="button" class="method-tab" data-switch-route="${escapeHTML(method.id)}">再试试${escapeHTML(method.label)}</button>`).join('')}</div>` + conversation(3));
    }
    for (const [id, open] of detailStates) {
      const details = document.getElementById(id);
      if (details) details.open = open;
    }
    const question = steps.querySelector('.active .question');
    if (question && lesson.routes[state.method]) question.textContent = lesson.routes[state.method][state.active]?.question || '';
    updateBusy();
    syncIdleQuestion();
  }

  function closePicker() {
    if (picking?.button?.isConnected) picking.button.setAttribute('aria-expanded', 'false');
    picker.hidden = true;
    picking = null;
  }

  function openPicker(button) {
    const stage = Number(button.dataset.stage);
    if (stage !== state.active) return;
    closePicker();
    picking = { stage, index: Number(button.dataset.slot), button, occurrence: button.dataset.occurrence };
    button.setAttribute('aria-expanded', 'true');
    picker.hidden = false;
    const rect = button.getBoundingClientRect();
    const height = picker.offsetHeight;
    const composerTop = document.querySelector('.composer').getBoundingClientRect().top;
    const left = Math.max(12, Math.min(window.innerWidth - picker.offsetWidth - 12, rect.left + rect.width / 2 - picker.offsetWidth / 2));
    const top = rect.bottom + height + 10 > composerTop ? Math.max(8, rect.top - height - 10) : rect.bottom + 10;
    picker.style.left = `${left}px`;
    picker.style.top = `${top}px`;
    picker.querySelector('button').focus({ preventScroll: true });
  }

  steps.addEventListener('click', event => {
    const button = event.target.closest('button');
    if (!button || busy || retryRequest) return;
    if (button.hasAttribute('data-method')) sendEvent('ui', {kind: 'method', value: button.dataset.method === '0' ? 'direct' : button.dataset.method});
    else if (button.hasAttribute('data-elimination-choice')) sendEvent('ui', {kind: 'choice', value: button.dataset.value});
    else if (button.hasAttribute('data-slot')) openPicker(button);
    else if (button.id === 'swap') sendEvent('ui', {kind: 'swap', value: state.swapped ? 'sum' : 'product'});
    else if (button.hasAttribute('data-submit')) sendEvent('ui', {kind: 'submit'});
    else if (button.hasAttribute('data-hint')) {
      invitedQuestions.add(currentQuestion());
      sendEvent('help');
    }
  });

  picker.addEventListener('click', event => {
    const button = event.target.closest('[data-token]');
    if (!button || !picking) return;
    sendEvent('ui', {kind: 'fill', index: picking.index, value: button.dataset.token});
  });
  document.addEventListener('click', (event) => {
    if (picking && !picker.contains(event.target) && !event.target.closest('[data-slot]')) closePicker();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && picking) {
      const source = picking.button;
      closePicker();
      source.focus({ preventScroll: true });
    }
    if (event.key === 'Tab' && picking) {
      const buttons = [...picker.querySelectorAll('button')];
      if ((!event.shiftKey && document.activeElement === buttons.at(-1)) || (event.shiftKey && document.activeElement === buttons[0])) {
        event.preventDefault();
        buttons[event.shiftKey ? buttons.length - 1 : 0].focus();
      }
    }
  });
  window.addEventListener('resize', closePicker);
  window.addEventListener('scroll', closePicker, { passive: true });
  document.querySelector('#reset').addEventListener('click', restart);
  document.querySelector('#completion').addEventListener('click', event => {
    const button = event.target.closest('[data-switch-route]');
    if (button) sendEvent('ui', {kind:'switch_route', value:button.dataset.switchRoute});
  });
  new ResizeObserver(entries => {
    document.documentElement.style.setProperty('--composer-height', `${Math.ceil(entries[0].target.getBoundingClientRect().height)}px`);
  }).observe(document.querySelector('.composer'));
  for (const type of ['click', 'keydown', 'input']) document.addEventListener(type, recordActivity);
  document.querySelector('#message').addEventListener('focus', () => {
    pauseIdle();
    hideIdleInvitation();
  });
  document.querySelector('#message').addEventListener('blur', recordActivity);
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) pauseIdle();
    else resumeIdle();
  });
  restart();
})();
