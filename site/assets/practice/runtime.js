/* Shared practice runtime: HTML owns course content; dialogue sync is opt-in. */
// Shared account UI; failure must never prevent local practice.
if (typeof document !== 'undefined' && document.currentScript?.src) import(new URL('../auth/site-auth.js?v=2', document.currentScript.src).href).catch(() => {});
(() => {
  'use strict';
  const lesson = JSON.parse(document.getElementById('practice-config').textContent);
  const methods = lesson.methods;
  let titles = [];
  let remote = null;
  let pendingOperations = [];
  const steps = document.querySelector('#steps');
  const picker = document.querySelector('#picker');
  const attemptHistory = document.querySelector('#attempt-history');
  const announcement = document.querySelector('#announcement');
  let state = PracticeContext.freshState(lesson);
  let picking = null;
  let snapshot = null;
  let busy = false;
  let generation = 0;
  let requestController = null;
  let retryRequest = null;
  let dialoguePause = null;
  let dialogueTimer = null;
  const local = ['localhost', '127.0.0.1'].includes(location.hostname);
  const api = local && location.port === '8765' ? `${location.protocol}//${location.hostname}:8766/api/tutor-demo` : '/api/tutor-demo';
  const messageInput = document.querySelector('#message');
  const sendButton = document.querySelector('.send-button');
  const networkStatus = document.querySelector('#network-status');
  const retryButton = document.querySelector('#request-retry');
  const escapeHTML = (text) => String(text).replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]));

  function updateBusy() {
    const blocked = busy;
    const paused = dialoguePause && dialoguePause.until > Date.now();
    for (const button of [...steps.querySelectorAll('button'), ...document.querySelectorAll('[data-switch-route]'), ...picker.querySelectorAll('button')]) {
      if (!button.hasAttribute('data-initial-disabled')) button.dataset.initialDisabled = String(button.disabled);
      button.disabled = blocked || (paused && button.hasAttribute('data-hint')) || button.dataset.initialDisabled === 'true';
    }
    sendButton.disabled = busy || paused || !snapshot || Boolean(retryRequest) || !messageInput.value.trim();
    messageInput.disabled = busy || paused;
    steps.setAttribute('aria-busy', String(busy));
  }

  function conversation(stage, attempt = null) {
    const attemptId = attempt?.id || snapshot?.attempt_id;
    const source = attempt?.messages || snapshot?.messages || [];
    const node = lesson.routes[attempt?.route || state.method]?.[stage];
    const messages = source.filter((m, i) => {
      if (m.attempt_id !== attemptId || m.stage !== stage || m.kind === 'ui') return false;
      // Automatic feedback already has a place beside the exercise. Only hide
      // the reply to that UI submit; keep genuine dialogue and Context intact.
      const previous = source[i - 1];
      const automaticFeedback = node?.interaction.type === 'choice' ? node.feedback?.answer
        : node?.attempt_calculations ? node.feedback?.terms : null;
      return !(automaticFeedback && m.role === 'assistant' && m.text === automaticFeedback &&
        previous?.kind === 'ui' && previous.action?.kind === 'submit' && previous.attempt_id === attemptId && previous.stage === stage);
    });
    if (!messages.length) return '';
    const content = `<div class="node-conversation" aria-label="本步骤的对话">${messages.map(m => `<div class="chat-message ${m.role === 'student' ? 'student' : 'assistant'}" role="group" aria-label="${m.role === 'student' ? '学生消息' : '老师回复'}"><p data-math-text>${escapeHTML(m.text)}</p></div>`).join('')}</div>`;
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
    render();
  }

  function showProgress(oldActive, oldAttempt) {
    if (state.active > oldActive || oldAttempt !== snapshot.attempt_id) requestAnimationFrame(() => {
      document.querySelector(completed() ? '.completion-card' : `#step-${state.active}`)?.scrollIntoView({
        behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'center'});
    });
  }

  async function request(payload) {
    if (busy || (dialoguePause && dialoguePause.until > Date.now())) return;
    const thisGeneration = generation, oldActive = state.active, oldAttempt = snapshot.attempt_id;
    const controller = new AbortController();
    requestController = controller;
    const timeout = setTimeout(() => controller.abort(), 55000);
    busy = true; pauseIdle(); retryRequest = null; retryButton.hidden = true;
    networkStatus.textContent = '老师正在思考…'; updateBusy();
    const post = async (url, body) => {
      const response = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body), signal: controller.signal});
      const data = await response.json();
      if (!response.ok) {
        const error = Error(typeof data.detail === 'string' ? data.detail : '暂时无法连接老师，请重试。');
        error.code = data.code; error.retryAfter = data.retry_after;
        throw error;
      }
      return data;
    };
    try {
      if (!remote) {
        const started = await post(`${api}/sessions`, {lesson_id: lesson.id});
        if (thisGeneration !== generation) return;
        remote = {session_id: started.session_id, revision: started.revision};
      }
      const data = await post(`${api}/sessions/${remote.session_id}/events`, payload);
      if (thisGeneration !== generation) return;
      // A failed request can be retried after more local work. Replay that tail onto
      // the acknowledged state, rather than erasing the student's newer choices.
      const acknowledged = new Set(payload.pending_operations.map(operation => operation.event_id));
      const tail = pendingOperations.filter(operation => !acknowledged.has(operation.event_id));
      const merged = PracticeContext.reconcile(data, tail, lesson);
      remote = {session_id: data.session_id, revision: data.revision};
      pendingOperations = merged.remaining;
      acceptSnapshot(merged.view);
      if (payload.kind === 'text' && messageInput.value.trim() === payload.text) messageInput.value = '';
      networkStatus.textContent = '';
      showProgress(oldActive, oldAttempt);
      if (state.active === oldActive && oldAttempt === snapshot.attempt_id) {
        document.querySelector(completed() ? '#completion .chat-message:last-child' : `#step-${state.active} .chat-message:last-child`)?.scrollIntoView({behavior: 'smooth', block: 'center'});
      }
      announce(data.messages.at(-1)?.text || '老师已回复。');
    } catch (error) {
      if (thisGeneration !== generation) return;
      const limited = ['session_limit', 'daily_limit', 'retry_cooldown', 'session_busy'].includes(error.code);
      const exhausted = ['session_limit', 'daily_limit'].includes(error.code);
      retryRequest = exhausted ? null : payload; retryButton.hidden = limited;
      if (limited) {
        dialoguePause = {code: error.code, message: error.message, until: error.code === 'session_limit' ? Infinity : Date.now() + Math.max(1, error.retryAfter || 5) * 1000};
        clearTimeout(dialogueTimer);
        if (Number.isFinite(dialoguePause.until)) dialogueTimer = setTimeout(() => {
          dialoguePause = null;
          retryButton.hidden = !retryRequest;
          networkStatus.textContent = retryRequest ? '现在可以重试，原来的输入和进度已保留。' : '';
          updateBusy(); resumeIdle();
        }, dialoguePause.until - Date.now());
      }
      networkStatus.textContent = (error.name === 'AbortError' ? '老师回复超时。' : error.message === 'Failed to fetch' ? '暂时无法连接老师。' : error.message) + (limited ? ' 输入和进度已保留。' : ' 可以继续点选练习，输入和进度已保留。');
    } finally {
      clearTimeout(timeout);
      if (thisGeneration === generation) { busy = false; updateBusy(); resumeIdle(); }
    }
  }

  function sendEvent(kind, action = null, text = '') {
    if (busy) return;
    closePicker();
    if (kind === 'ui') {
      const oldActive = state.active, oldAttempt = snapshot.attempt_id;
      const operation = {event_id: crypto.randomUUID(), action, position: PracticeContext.position(snapshot)};
      pendingOperations.push(operation);
      acceptSnapshot(PracticeContext.apply(snapshot, operation, lesson));
      showProgress(oldActive, oldAttempt);
      announce(state.feedback || '已记录你的选择。');
      return;
    }
    if (retryRequest) return;
    request({event_id: crypto.randomUUID(), revision: remote?.revision || 0,
      lesson_version: lesson.version, pending_operations: structuredClone(pendingOperations), kind, text});
  }

  function restart() {
    generation++; requestController?.abort(); busy = false;
    if (dialoguePause?.code !== 'daily_limit') {
      dialoguePause = null; clearTimeout(dialogueTimer);
    }
    remote = null; pendingOperations = []; retryRequest = null;
    retryButton.hidden = true; networkStatus.textContent = dialoguePause?.message || '';
    pauseIdle(); invitedQuestions.clear(); idleQuestion = null; messageInput.value = '';
    steps.innerHTML = ''; attemptHistory.innerHTML = '';
    acceptSnapshot(PracticeContext.create(lesson, crypto.randomUUID()));
    window.scrollTo({top: 0, behavior: 'instant'});
  }

  retryButton.addEventListener('click', () => { if (retryRequest) request(retryRequest); });
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
    return completed() ? null : `${snapshot.attempt_id}-${state.method || 'method'}-${state.active}`;
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
    if (busy || (dialoguePause && dialoguePause.until > Date.now()) || retryRequest || idleTimer !== null || !idleQuestion || invitedQuestions.has(idleQuestion) || document.hidden || document.activeElement?.id === 'message') return;
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

  const UI = PracticeComponents;
  const axisPositions = new Map();
  const {hintIcon} = UI;
  const routeNodes = () => lesson.routes[state.method] || lesson.routes[methods[0].id];
  const completed = () => PracticeContext.done(lesson, state);
  const nodeAt = stage => lesson.routes[state.method]?.[stage];
  const ready = stage => nodeAt(stage).interaction.type === 'choice'
    ? state.choices[nodeAt(stage).interaction.field] != null : Array.from({length: PracticeContext.slotCount(nodeAt(stage).interaction)}, (_, index) => state.pairs[stage][index]).every(Boolean);
  const announce = (text) => { announcement.textContent = text; };

  function slot(stage, index, occurrence = '') {
    const value = state.pairs[stage][index];
    const component = nodeAt(stage).interaction;
    const label = component.slots ? component.slots[index].options.find(option => option.value === value)?.label : component.term_labels?.[value];
    return UI.slot({stage, index, occurrence, value, label, shape: component.slot_shapes?.[index], title: component.slot_labels?.[index] || component.slots?.[index]?.label || titles[stage]});
  }

  function template(id, displayState = state, stage = 0, prefix = snapshot.attempt_id) {
    if (!id) return '';
    const pair = displayState.pairs[stage] || [];
    const variable = displayState.choices.variable || lesson.variables[0];
    const termLabels = lesson.routes[displayState.method]?.[stage]?.interaction.term_labels || {};
    const values = {...displayState.choices, variable,
      other: lesson.variables.find(term => term !== variable), first: pair[0], second: pair[1],
      first_math: termLabels[pair[0]] || pair[0], second_math: termLabels[pair[1]] || pair[1],
      uid: `${prefix}-${stage}`};
    return document.getElementById(id).innerHTML.replace(/\{\{(\w+)\}\}/g, (_, key) => escapeHTML(values[key] ?? ''));
  }

  function renderInteraction(stage) {
    if (!state.method) return `<p class="question">${escapeHTML(lesson.method_question)}</p>
      <div class="method-options">${methods.map(({id, label}) => `<button type="button" class="method-choice" data-method="${escapeHTML(id)}"><span class="radio-mark" aria-hidden="true"></span>${escapeHTML(label)}<span class="option-arrow" aria-hidden="true">›</span></button>`).join('')}</div>
      <button type="button" class="hint-button" data-hint="0">${hintIcon}还没想好，给点提示</button>`;
    const node = nodeAt(stage), component = node.interaction;
    const boardId = node.scope_boards ? node.scope_boards[state.pairs[stage][0]] : node.board;
    const props = {slot: (index, occurrence) => slot(stage, index, occurrence), component, terms: component.terms, positiveTerms: component.positive_terms, termLabels: component.term_labels, caption: component.caption, swapped: state.swapped, slotLabels: component.slot_labels, pair: state.pairs[stage], board: template(boardId, state, stage),
      scopeBoard: node.scope_boards ? template(node.board, state, stage) : ''};
    const tabs = stage === 0 ? `<div class="method-tabs" role="group" aria-label="解题方案">${methods.map(({id, label}) => `<button type="button" class="method-tab" data-method="${escapeHTML(id)}" aria-pressed="${state.method === id}">${escapeHTML(label)}</button>`).join('')}</div>` : '';
    const board = component.type === 'choice'
      ? template(node.board) + UI.choices(component, state.choices[component.field], node.title) + template(node.preview?.[state.choices[component.field]])
      : UI[component.type](props);
    const confirmedPair = ['rewrite', 'fill'].includes(component.type) && node.attempt_calculations
      ? PracticeContext.confirmedPair(snapshot) : null;
    const calculationEntry = confirmedPair ? node.attempt_calculations?.[confirmedPair[0]] : null;
    const calculationId = PracticeContext.slotCount(component) === 1
      ? calculationEntry : calculationEntry?.[confirmedPair?.[1]];
    return tabs + `<p class="question" data-math-text>${escapeHTML(node.question)}</p>` + board +
      UI.controls({stage, label: node.submit_label, ready: ready(stage), feedback: calculationId ? '' : state.feedback, hint: state.hint}) +
      template(calculationId, state, stage);
  }

  function renderDisplay(stage, displayState = state, prefix = snapshot.attempt_id) {
    const node = lesson.routes[displayState.method][stage];
    const display = typeof node.display === 'string' ? node.display : node.display.options[displayState.choices[node.display.field]];
    return template(display, displayState, stage, prefix);
  }

  function renderAttemptHistory() {
    const previous = (snapshot.attempts || []).filter(attempt => attempt.id !== snapshot.attempt_id);
    attemptHistory.innerHTML = previous.map((attempt, index) => {
      const label = lesson.methods.find(method => method.id === attempt.route)?.label || '方案探索';
      const nodes = lesson.routes[attempt.route] || lesson.routes[methods[0].id];
      const completed = attempt.completed.map(record => `<section class="archived-node"><h3>${escapeHTML(nodes[record.stage].title)}</h3>${renderDisplay(record.stage, attempt.state, `${attempt.id}-`)}${conversation(record.stage, attempt)}</section>`).join('');
      const pending = attempt.status !== 'completed' ? `<p class="archived-position">停在：${escapeHTML(nodes[attempt.state.active]?.title || '选择方案')}（未完成）</p>` : '';
      return `<details class="attempt-history-card" id="attempt-${attempt.id}"><summary>第 ${index + 1} 次尝试 · ${escapeHTML(label)}<span class="attempt-status">${attempt.status === 'completed' ? '已完成' : '已保留进度'}</span></summary>${completed}${pending}${conversation(attempt.state.active, attempt)}</details>`;
    }).join('');
  }

  function render() {
    closePicker();
    titles = routeNodes().map(node => node.title);
    const detailStates = new Map([...document.querySelectorAll('.workspace details[id]')].map(el => [el.id, el.open]));
    renderAttemptHistory();
    steps.innerHTML = titles.map((title, stage) => {
      if (stage > state.active) return '';
      const done = stage < state.active;
      return `<article class="step-card ${done ? 'done' : 'active'}" id="step-${stage}" aria-labelledby="step-title-${stage}"><header class="step-heading"><span class="step-number" aria-hidden="true">${done ? '✓' : stage + 1}</span><h2 id="step-title-${stage}" tabindex="-1">${title}</h2><span class="status">${done ? '已完成' : '进行中'}</span></header>${done ? renderDisplay(stage) : renderInteraction(stage)}${conversation(stage)}</article>`;
    }).join('');
    document.querySelector('#progress-fill').style.width = `${state.active / routeNodes().length * 100}%`;
    document.querySelector('#conversation-focus').textContent = completed() ? '本题已完成' : `正在讨论：${titles[state.active]}`;
    const completion = document.querySelector('#completion');
    completion.hidden = !completed();
    completion.innerHTML = completed() ? template(lesson.completion) + template(lesson.comparisons?.[state.method]) : '';
    if (completed()) {
      const routes = lesson.methods.filter(method => lesson.routes[method.id] && method.id !== state.method);
      completion.insertAdjacentHTML('beforeend', `<div class="route-actions">${routes.map(method => `<button type="button" class="method-tab" data-switch-route="${escapeHTML(method.id)}">再试试${escapeHTML(method.label)}</button>`).join('')}</div>` + conversation(state.active));
    }
    for (const [id, open] of detailStates) {
      const details = document.getElementById(id);
      if (details) details.open = open;
    }
    const workspace = document.querySelector('.workspace');
    for (const board of workspace.querySelectorAll('[data-completed-amgm]')) {
      board.innerHTML = UI.completedAmgm({terms: [board.dataset.first, board.dataset.second], labels: [board.dataset.firstLabel, board.dataset.secondLabel]});
    }
    for (const graph of workspace.querySelectorAll('[data-quadratic-graph]')) {
      graph.innerHTML = UI.quadraticGraph(JSON.parse(graph.dataset.quadraticGraph));
    }
    for (const graph of workspace.querySelectorAll('[data-reciprocal-sum-graph]')) {
      graph.innerHTML = UI.reciprocalSumGraph(JSON.parse(graph.dataset.reciprocalSumGraph));
    }
    for (const graph of workspace.querySelectorAll('[data-linear-graph]')) {
      graph.innerHTML = UI.linearGraph(JSON.parse(graph.dataset.linearGraph));
    }
    for (const host of workspace.querySelectorAll('[data-axis-explorer]')) mountAxisExplorer(host);
    renderMath(workspace);
    updateBusy();
    syncIdleQuestion();
  }

  // A full render rebuilds the explorer, so its axis position is kept per graph uid.
  function mountAxisExplorer(host) {
    const spec = JSON.parse(host.dataset.axisExplorer);
    const {min, max, step} = spec.axis;
    host.innerHTML = UI.axisExplorer(spec, axisPositions.get(spec.uid) ?? spec.axis.value);
    const svg = host.querySelector('svg'), input = host.querySelector('[data-axis-input]');
    const move = value => {
      const h = Math.min(max, Math.max(min, min + Math.round((value - min) / step) * step));
      const rounded = Number(h.toFixed(6));
      axisPositions.set(spec.uid, rounded);
      host.querySelector('[data-axis-layer]').innerHTML = UI.axisExplorerLayer(spec, rounded);
      input.value = rounded;
    };
    const fromPointer = event => {
      const box = svg.getBoundingClientRect();
      const px = (event.clientX - box.left) / box.width * 360;
      const [xmin, xmax] = spec.bounds;
      move(xmin + (px - 48) / 270 * (xmax - xmin));
    };
    input.addEventListener('input', () => move(Number(input.value)));
    svg.addEventListener('pointerdown', event => { fromPointer(event); svg.setPointerCapture(event.pointerId); });
    svg.addEventListener('pointermove', event => { if (svg.hasPointerCapture(event.pointerId)) fromPointer(event); });
  }

  function closePicker() {
    if (picking?.button?.isConnected) picking.button.setAttribute('aria-expanded', 'false');
    picker.hidden = true;
    picking = null;
  }

  function renderMath(root) {
    for (const label of root.querySelectorAll('[data-math-text]:not([data-math-rendered])')) {
      PracticeMath.render(label, label.textContent);
      label.dataset.mathRendered = 'true';
    }
  }

  function openPicker(button) {
    const stage = Number(button.dataset.stage);
    if (stage !== state.active) return;
    closePicker();
    picking = { stage, index: Number(button.dataset.slot), button, occurrence: button.dataset.occurrence };
    button.setAttribute('aria-expanded', 'true');
    picker.hidden = false;
    const component = nodeAt(stage).interaction;
    const candidates = component.slots ? component.slots[picking.index].options : component.terms.map(value => ({value, label: component.term_labels?.[value] || value}));
    picker.querySelector('.picker-options').innerHTML = candidates.map(({value, label}) => `<button type="button" data-token="${escapeHTML(value)}" aria-label="选择 ${escapeHTML(value)}"><span data-math-text>${escapeHTML(label)}</span></button>`).join('');
    renderMath(picker);
    const rect = button.getBoundingClientRect();
    const height = picker.offsetHeight;
    const composerTop = document.querySelector('.composer').getBoundingClientRect().top;
    const left = Math.max(12, Math.min(window.innerWidth - picker.offsetWidth - 12, rect.left + rect.width / 2 - picker.offsetWidth / 2));
    const top = rect.bottom + height + 10 > composerTop ? Math.max(8, rect.top - height - 10) : rect.bottom + 10;
    picker.style.left = `${left}px`;
    picker.style.top = `${top}px`;
    picker.querySelector('button').focus({ preventScroll: true });
  }

  // Toggle one substitution target. Nested targets overlap (a sits inside a+1), so choosing one clears the other.
  function toggleTarget(button) {
    const slotSpec = nodeAt(state.active).interaction.slots[0];
    const order = slotSpec.options.map(option => option.value);
    const source = button.closest('.sub-source');
    const region = element => element.classList.contains('sub-frame') ? element.parentElement : element;
    const value = button.dataset.subTarget, mine = region(button);
    let chosen = state.pairs[state.active][0] ? state.pairs[state.active][0].split('|') : [];
    if (chosen.includes(value)) chosen = chosen.filter(item => item !== value);
    else {
      chosen = chosen.filter(item => {
        const other = region(source.querySelector(`[data-sub-target="${CSS.escape(item)}"]`));
        return !mine.contains(other) && !other.contains(mine);
      });
      chosen.push(value);
      if (chosen.length > slotSpec.names.length) chosen.shift();
    }
    chosen.sort((a, b) => order.indexOf(a) - order.indexOf(b));
    sendEvent('ui', {kind: 'fill', index: 0, value: chosen.join('|')});
  }

  steps.addEventListener('click', event => {
    const button = event.target.closest('button');
    if (!button || busy) return;
    if (button.hasAttribute('data-method')) sendEvent('ui', {kind: 'method', value: button.dataset.method});
    else if (button.hasAttribute('data-sub-target')) toggleTarget(button);
    else if (button.hasAttribute('data-choice')) sendEvent('ui', {kind: 'choice', value: button.dataset.value});
    else if (button.hasAttribute('data-pair-answer')) sendEvent('ui', {kind: 'fill', index: Number(button.dataset.pairAnswer), value: button.dataset.value});
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
  let accountId;
  window.addEventListener('site-auth-change', event => {
    const nextId = event.detail.user?.id || null;
    if (accountId && accountId !== nextId) restart();
    accountId = nextId;
  });
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
