/* Shared practice runtime: HTML owns course content; dialogue sync is opt-in. */
const practiceParams = typeof location !== 'undefined' ? new URLSearchParams(location.search) : new URLSearchParams();
// Keep this synchronous check identical to learning-mode.mjs so a preview never
// initializes authentication or recorders while the published registry loads.
const practiceKnowledgePreview = practiceParams.get('preview') === '1' ||
  (practiceParams.get('knowledge') === 'next' && practiceParams.get('learning') !== '1');
let practiceKnowledgeNext = practiceKnowledgePreview;
const practiceRuntimeSrc = document.currentScript?.src;
const practiceAccess = {enabled: false, published: null, contentVersion: null, reason: ''};
const practiceTutorEnabled = () => !practiceKnowledgePreview;
async function checkPracticeContent() {
  practiceAccess.enabled = false;
  practiceAccess.reason = '';
  practiceAccess.contentVersion = null;
  practiceAccess.practiceVersion = null;
  practiceAccess.problem = null;
  const read = async url => {
    const response = await fetch(url, {cache: 'no-cache', signal: AbortSignal.timeout(15000)});
    if (!response.ok) throw Error('学习关联暂不可用');
    return response.json();
  };
  try {
    const registry = await read('/knowledge/teaching/problems.json');
    if (!registry.problems || typeof registry.problems !== 'object' || Array.isArray(registry.problems)) {
      throw Error('已发布题目目录暂不可用');
    }
    const lessonId = JSON.parse(document.getElementById('practice-config').textContent).id;
    const entry = registry.problems[lessonId];
    practiceAccess.published = Boolean(entry && entry.path === location.pathname.replace(/index\.html$/, ''));
    practiceKnowledgeNext = practiceAccess.published;
    if (!practiceAccess.published || practiceKnowledgePreview) return practiceAccess;
    const [compatibility, problem] = await Promise.all([
      import(new URL('../learning/practice-compatibility.mjs', practiceRuntimeSrc).href),
      read(`/knowledge/teaching/problems/${encodeURIComponent(lessonId)}.json`)
    ]);
    Object.assign(practiceAccess, await compatibility.checkPracticeCompatibility(
      JSON.parse(document.getElementById('practice-config').textContent), problem, read));
    practiceAccess.problem = problem;
    practiceAccess.enabled = true;
  } catch (error) {
    practiceAccess.reason = error.message;
  }
  return practiceAccess;
}
const practiceContentReady = checkPracticeContent();
const practiceAuthReady = !practiceKnowledgePreview && practiceRuntimeSrc
  ? import(new URL('../auth/site-auth.js?v=4', practiceRuntimeSrc).href).then(() => window.SiteAuth?.ready).catch(() => {})
  : Promise.resolve();
(() => {
  'use strict';
  const lesson = JSON.parse(document.getElementById('practice-config').textContent);
  let confirmedOnServer = {};
  let passedFieldsOnServer = [];
  const confirmedProgress = history => {
    confirmedOnServer = history.confirmed_choices || {};
    const passed = new Set((history.steps || []).filter(step => step.passed).map(step => step.step_id));
    passedFieldsOnServer = (lesson.routes[history.route_id] || [])
      .filter(step => passed.has(step.id) && step.interaction.type === 'choice')
      .map(step => step.interaction.field);
  };
  const restorePractice = (history, {force = false} = {}) => {
    // Resume saved, confirmed progress only; never infer success from unsubmitted inputs.
    const route = lesson.routes[history.route_id];
    const active = history.active_step ? route.findIndex(node => node.id === history.active_step) : route.length;
    if (!force && (state.active !== 0 || snapshot.completed.length)) {
      // A slow start can finish after local submissions. Matching progress needs
      // no UI restore; differing progress requires an explicit recovery instead.
      return state.method === history.route_id && state.active === active;
    }
    if (!force && state.method && state.method !== history.route_id) return false;
    confirmedProgress(history);
    generation++; requestController?.abort(); busy = false;
    remote = null; pendingOperations = []; retryRequest = null;
    retryButton.hidden = true; networkStatus.textContent = '';
    snapshot = PracticeContext.create(lesson, crypto.randomUUID());
    state = snapshot.state; state.method = history.route_id;
    for (const saved of history.steps.filter(item => item.passed)) {
      const index = route.findIndex(n => n.id === saved.step_id), node = route[index];
      // Server links a passing rule grade to its answer; dialogue passes use the standard conclusion.
      const answer = saved.answer;
      if (node.interaction.type === 'choice') state.choices[node.interaction.field] = answer?.value || node.expected_answer.one_of[0];
      else { state.pairs[index] = answer?.terms || [...node.expected_answer.terms]; if (node.interaction.type === 'structure') state.swapped = (answer?.fixed || node.expected_answer.fixed) === 'product'; }
      snapshot.completed.push({stage:index,node:node.id,route:state.method,state:structuredClone(state),source:'saved'});
    }
    state.active = history.active_step ? route.findIndex(n => n.id === history.active_step) : route.length;
    snapshot.completed = snapshot.completed.filter((item,index,items)=>items.findIndex(x=>x.node===item.node&&x.route===item.route)===index);
    snapshot.messages = history.events.filter(e => ['message','hint'].includes(e.event_type)).map(e => ({role:e.payload.role === 'student'?'student':'assistant',kind:'text',text:e.payload.text,stage:route.findIndex(n=>n.id===e.step_id),route:state.method,attempt_id:snapshot.attempt_id}));
    snapshot.state = state; render();
  };
  let recorder = null;
  let recorderPracticeVersion = null;
  let recorderLoadAttempts = 0;
  const useServerProgress = () => Boolean(practiceAccess.enabled && recorder && window.SiteAuth?.user?.id);
  function recorderUnavailable() {
    practiceAccess.enabled = false;
    practiceAccess.reason = '学习记录组件加载失败，请重试保存连接。';
    renderLearningNotice();
    preview?.update(snapshot);
    return null;
  }
  async function enableRecorder(access) {
    if (!access.enabled) return null;
    if (recorder) return recorder;
    if (snapshot?.completed.length || remote || busy) {
      access.enabled = false;
      access.reason = '当前已有未保存的练习，请刷新后开始保存。';
      return null;
    }
    await practiceAuthReady;
    const moduleURL = new URL('../learning/practice-records.js', runtimeSrc);
    if (recorderLoadAttempts++) moduleURL.searchParams.set('retry', String(recorderLoadAttempts));
    const module = await import(moduleURL.href);
    recorder = module.createRecorder(lesson, restorePractice, {contentVersion: access.contentVersion, practiceVersion: access.practiceVersion, onConfirmed: history => {
      if (history.route_id !== state.method) return;
      confirmedProgress(history);
      if (preview) preview.update(snapshot);
    }});
    recorderPracticeVersion = access.practiceVersion;
    preview?.update(snapshot);
    return recorder;
  }
  let recorderReady = practiceContentReady.then(enableRecorder).catch(recorderUnavailable);
  const methods = lesson.methods;
  const runtimeSrc = document.currentScript?.src;
  practiceContentReady.then(access => {
    if (access.enabled && runtimeSrc) import(new URL('../learning/learning-marks.js', runtimeSrc).href).catch(() => {});
  });
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
  const api = '/api/tutor-demo';
  const messageInput = document.querySelector('#message');
  const sendButton = document.querySelector('.send-button');
  const networkStatus = document.querySelector('#network-status');
  const retryButton = document.querySelector('#request-retry');
  const escapeHTML = (text) => String(text).replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]));

  function updateBusy() {
    const blocked = busy;
    const paused = dialoguePause && dialoguePause.until > Date.now();
    for (const button of [...steps.querySelectorAll('button'), ...document.querySelectorAll('[data-switch-route]'), ...picker.querySelectorAll('button')]) {
      if (button.hasAttribute('data-tip')) continue;
      if (!button.hasAttribute('data-initial-disabled')) button.dataset.initialDisabled = String(button.disabled);
      button.disabled = blocked || (paused && button.hasAttribute('data-hint')) || button.dataset.initialDisabled === 'true';
    }
    sendButton.disabled = !practiceTutorEnabled() || busy || paused || !snapshot || Boolean(retryRequest) || !messageInput.value.trim();
    messageInput.disabled = !practiceTutorEnabled() || busy || paused;
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
    if (completed() && practiceAccess.enabled) {
      document.getElementById('completion').dataset.learningCompleted = 'true';
      window.dispatchEvent(new CustomEvent('practice-completed', {detail: {problemId: lesson.id}}));
    }
  }

  function showProgress(oldActive, oldAttempt) {
    if (state.active > oldActive || oldAttempt !== snapshot.attempt_id) requestAnimationFrame(() => {
      const target = completed()
        ? document.querySelector('#learning-mark:not([hidden])') || document.querySelector('.completion-card')
        : document.querySelector(`#step-${state.active}`);
      target?.scrollIntoView({
        behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'center'});
    });
  }

  async function request(payload) {
    if (!practiceTutorEnabled()) return;
    if (busy || (dialoguePause && dialoguePause.until > Date.now())) return;
    const thisGeneration = generation, oldActive = state.active, oldAttempt = snapshot.attempt_id;
    const retrying = retryRequest === payload;
    const controller = new AbortController();
    requestController = controller;
    let timeout;
    busy = true; pauseIdle(); retryRequest = null; retryButton.hidden = true;
    networkStatus.textContent = ''; updateBusy();
    const asking = payload.kind === 'text';
    const loginPrompt = {
      title: asking ? '登录后向老师提问' : '登录后获取提示',
      intro: asking ? '登录后会自动发送你刚才写的问题，当前练习不会丢失。' : '登录后老师会针对这一步给你提示，当前练习不会丢失。',
      onPrompt: () => { networkStatus.textContent = '请先登录，登录后会自动继续。'; },
    };
    let remainingCalls = null;
    const post = async (url, body) => {
      const response = await fetch(url, {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body), signal: controller.signal});
      const remaining = response.headers.get('X-Tutor-Calls-Remaining');
      if (remaining !== null) remainingCalls = Number(remaining);
      const data = await response.json();
      if (!response.ok) {
        const error = Error(typeof data.detail === 'string' ? data.detail : '暂时无法连接老师，请重试。');
        error.status = response.status; error.code = data.code; error.retryAfter = data.retry_after;
        throw error;
      }
      return data;
    };
    try {
      await practiceAuthReady;
      if (!window.SiteAuth?.requireLogin) throw new Error('登录组件暂不可用，请刷新后重试。');
      let user = await window.SiteAuth.requireLogin(loginPrompt);
      if (thisGeneration !== generation) return;
      if (!user) {
        if (retrying) { retryRequest = payload; retryButton.hidden = false; }
        networkStatus.textContent = asking ? '未登录，问题还留在输入框里；可以继续点选练习。' : '未登录，可以继续点选练习。';
        return;
      }
      let data;
      for (let attempt = 0; attempt < 2; attempt++) {
        networkStatus.textContent = '老师正在思考…';
        timeout = setTimeout(() => controller.abort(), 55000);
        try {
          if (practiceAccess.enabled && !payload.practice_attempt_id) {
            const recorder = await recorderReady;
            if (!recorder && practiceAccess.enabled) recorderUnavailable();
            // Loading may fail while this question is waiting. Continue with
            // an independent tutor instead of binding an unsaved attempt.
            if (practiceAccess.enabled && recorder) Object.assign(payload, await recorder.dialogue(snapshot));
            // Questions asked before choosing a route use an independent tutor
            // session. Once a recorded route exists, restore a new bound session
            // instead of attributing the earlier conversation to that attempt.
            if (payload.practice_attempt_id && remote && !remote.practiceAttemptId) remote = null;
          }
          if (thisGeneration !== generation) return;
          if (!remote) {
            const started = await post(`${api}/sessions`, {lesson_id: lesson.id,
              ...(payload.practice_attempt_id ? {practice_attempt_id:payload.practice_attempt_id, practice_version:practiceAccess.practiceVersion} : {})});
            if (thisGeneration !== generation) return;
            if (payload.practice_attempt_id) {
              // Confirmed submissions were restored by the server. Only synchronize
              // the current unsubmitted selections, without recording them as answers.
              const current = lesson.routes[state.method]?.[state.active], actions = [];
              if (current?.interaction.type === 'choice') {
                const value = state.choices[current.interaction.field];
                if (value) actions.push({kind:'choice',value});
              } else if (current) {
                state.pairs[state.active].slice(0,PracticeContext.slotCount(current.interaction)).forEach((value,index)=>{if(value)actions.push({kind:'fill',index,value});});
                if(current.interaction.type==='structure')actions.push({kind:'swap',value:state.swapped?'product':'sum'});
              }
              pendingOperations = actions.map(action=>({event_id:crypto.randomUUID(),action,position:PracticeContext.position(started)}));
              payload.pending_operations = structuredClone(pendingOperations);
              payload.revision = started.revision;
            }
            remote = {session_id: started.session_id, revision: started.revision, user_id: user.id, practiceAttemptId: payload.practice_attempt_id || null,
              lessonVersion: started.lesson_version};
          }
          if (remote.user_id !== user.id) { restart(); return; }
          if (remote.practiceAttemptId && remote.lessonVersion != null) payload.lesson_version = remote.lessonVersion;
          data = await post(`${api}/sessions/${remote.session_id}/events`, payload);
          break;
        } catch (error) {
          if (thisGeneration !== generation) return;
          if (error.status !== 401 || attempt > 0) throw error;
          clearTimeout(timeout);
          user = await window.SiteAuth.requireLogin({...loginPrompt, force: true, title: '登录已过期',
            onPrompt: () => { networkStatus.textContent = '登录已过期，重新登录后会自动继续。'; },
            intro: '重新验证手机号后会继续刚才的请求，当前练习不会丢失。'});
          if (thisGeneration !== generation) return;
          if (!user) {
            retryRequest = payload; retryButton.hidden = false;
            networkStatus.textContent = '重新登录后可重试，当前输入和练习已保留。';
            return;
          }
        } finally { clearTimeout(timeout); }
      }
      if (thisGeneration !== generation) return;
      // A failed request can be retried after more local work. Replay that tail onto
      // the acknowledged state, rather than erasing the student's newer choices.
      const acknowledged = new Set(payload.pending_operations.map(operation => operation.event_id));
      const tail = pendingOperations.filter(operation => !acknowledged.has(operation.event_id));
      const merged = PracticeContext.reconcile(data, tail, lesson);
      remote = {session_id: data.session_id, revision: data.revision, user_id: user.id, practiceAttemptId: payload.practice_attempt_id || remote?.practiceAttemptId || null,
        lessonVersion: data.lesson_version};
      pendingOperations = merged.remaining;
      acceptSnapshot(merged.view);
      if (payload.practice_attempt_id) recorderReady.then(r => practiceAccess.enabled && r?.routed(snapshot));
      if (data.learning_delivery) requestAnimationFrame(() => {
        const messages = [...document.querySelectorAll('.chat-message.assistant')];
        const reply = data.messages.at(-1)?.text;
        const target = messages.reverse().find(el => el.querySelector('[data-math-text]')?.dataset.mathSource === reply || el.textContent === reply) || messages[0];
        if (!target) return;
        const observer = new IntersectionObserver(entries => {
          if (thisGeneration !== generation) {observer.disconnect();return;}
          if (document.visibilityState === 'visible' && entries.some(entry=>entry.isIntersecting)) {
            recorderReady.then(r => practiceAccess.enabled && r?.displayed(data.learning_delivery));observer.disconnect();
          }
        });
        observer.observe(target);
      });
      if (payload.kind === 'text' && messageInput.value.trim() === payload.text) messageInput.value = '';
      networkStatus.textContent = remainingCalls === 0 ? '今天的 AI 提问与提示次数已用完，明天零点恢复；仍可继续点选练习。'
        : remainingCalls > 0 && remainingCalls <= 5 ? `今天还可以向老师提问或要提示 ${remainingCalls} 次。` : '';
      showProgress(oldActive, oldAttempt);
      if (state.active === oldActive && oldAttempt === snapshot.attempt_id) {
        document.querySelector(completed() ? '#completion .chat-message:last-child' : `#step-${state.active} .chat-message:last-child`)?.scrollIntoView({behavior: 'smooth', block: 'center'});
      }
      announce(data.messages.at(-1)?.text || '老师已回复。');
    } catch (error) {
      if (thisGeneration !== generation) return;
      const limited = ['session_limit', 'user_daily_limit', 'daily_limit', 'retry_cooldown', 'session_busy'].includes(error.code);
      const exhausted = ['session_limit', 'user_daily_limit', 'daily_limit'].includes(error.code);
      const recovering = error.code === 'learning_recovery';
      retryRequest = exhausted || recovering ? null : payload; retryButton.hidden = limited || recovering;
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
    if (['method', 'switch_route'].includes(action?.kind) && action.value !== state.method) {
      confirmedOnServer = {}; passedFieldsOnServer = [];
    }
    closePicker();
    if (kind === 'ui') {
      const oldActive = state.active, oldAttempt = snapshot.attempt_id;
      const operation = {event_id: crypto.randomUUID(), action, position: PracticeContext.position(snapshot)};
      const previousView = structuredClone(snapshot);
      pendingOperations.push(operation);
      acceptSnapshot(PracticeContext.apply(snapshot, operation, lesson));
      const nextView = structuredClone(snapshot);
      if (practiceAccess.enabled) recorderReady.then(r => r?.action(previousView, operation, nextView));
      showProgress(oldActive, oldAttempt);
      announce(state.feedback || '已记录你的选择。');
      return;
    }
    if (retryRequest) return;
    request({event_id: crypto.randomUUID(), revision: remote?.revision || 0,
      lesson_version: lesson.version, pending_operations: structuredClone(pendingOperations), kind, text});
  }

  function restart({accountChanged = false, initial = false} = {}) {
    if (!initial) recorderReady.then(r => r?.reset());
    confirmedOnServer = {}; passedFieldsOnServer = [];
    generation++; requestController?.abort(); busy = false;
    document.getElementById('completion').dataset.learningCompleted = 'false';
    if (dialoguePause?.code !== 'daily_limit' && !(dialoguePause?.code === 'user_daily_limit' && !accountChanged)) {
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
    if (!practiceTutorEnabled()) return;
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
    const tipLink = node.tip && state.feedback && !state.hint && !calculationId
      ? `<button type="button" class="tip-link" data-tip="${stage}" aria-haspopup="dialog">拿不准？打开图解看看这个知识点 →</button>` : '';
    return tabs + `<p class="question" data-math-text>${escapeHTML(node.question)}</p>` + board +
      UI.controls({stage, label: node.submit_label, ready: ready(stage), feedback: calculationId ? '' : state.feedback, hint: state.hint}) +
      tipLink + template(calculationId, state, stage);
  }

  const tipIcon = '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><line x1="1" y1="7" x2="15" y2="7" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" opacity=".6"/><path d="M2.5 2.5 Q8 17 13.5 2.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>';
  const tipButton = stage => (!practiceKnowledgeNext || state.method) && routeNodes()[stage]?.tip
    ? `<button type="button" class="tip-chip" data-tip="${stage}" aria-haspopup="dialog">${tipIcon}知识点</button>` : '';
  let explain = null;
  let preview = null;

  // A tip can branch on the student's choices like display does: {field, options: {value: tip}}, nested as needed.
  // An unanswered field falls back to its first option.
  const resolveTip = tip => {
    while (tip?.field) tip = tip.options[state.choices[tip.field]] || Object.values(tip.options)[0];
    return tip;
  };

  // Before the step is answered the sheet only teaches the rule; afterwards it also marks this problem's case.
  function openTip(stage) {
    if (practiceKnowledgeNext) {
      if (preview) preview.openStep(state.method, stage, structuredClone(snapshot));
      else announce('本题的知识点还在加载；如果页面下方显示加载失败，点那里的“重试”。');
      return;
    }
    if (practiceAccess.published === null) {
      announce('知识点暂时打不开：还没连上学习服务，可以点题目上方的“重试保存连接”。');
      return;
    }
    const tip = resolveTip(nodeAt(stage)?.tip);
    if (!tip || !runtimeSrc) return;
    const view = structuredClone(snapshot), ticket = generation;
    explain ||= import(new URL('../explain/explain.js', runtimeSrc).href);
    explain.then(async module => {
      if (ticket !== generation || snapshot.attempt_id !== view.attempt_id) return;
      const shown = await module.openExplainer(tip.id, {tip: stage < view.state.active ? tip : null, detail: false});
      if (shown && ticket === generation && snapshot.attempt_id === view.attempt_id && document.visibilityState === 'visible') {
        recorderReady.then(r => practiceAccess.enabled && r?.reference(view, stage, tip.id));
      }
    }).catch(() => {
      explain = null;
      announce('知识点暂时打不开，可以继续练习。');
    });
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
      return `<article class="step-card ${done ? 'done' : 'active'}" id="step-${stage}" aria-labelledby="step-title-${stage}"><header class="step-heading"><span class="step-number" aria-hidden="true">${done ? '✓' : stage + 1}</span><h2 id="step-title-${stage}" tabindex="-1">${title}</h2>${tipButton(stage)}<span class="status">${done ? '已完成' : '进行中'}</span></header>${done ? renderDisplay(stage) : renderInteraction(stage)}${conversation(stage)}</article>`;
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
    if (!practiceTutorEnabled()) steps.querySelectorAll('[data-hint]').forEach(button => button.hidden = true);
    if (practiceKnowledgeNext) {
      steps.querySelectorAll('.tip-chip').forEach(button => button.innerHTML = tipIcon + '学习提示');
      steps.querySelectorAll('.tip-link').forEach(button => button.textContent = '打开本步学习提示 →');
      preview?.update(snapshot);
    }
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
    if (button?.hasAttribute('data-tip')) { openTip(Number(button.dataset.tip)); return; }
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
  const defaultPlaceholder = messageInput.placeholder;
  window.addEventListener('site-auth-change', event => {
    if (practiceKnowledgePreview) return;
    const nextId = event.detail.user?.id || null;
    messageInput.placeholder = window.SiteAuth?.enabled && !nextId ? '登录后可以在这里向老师提问…' : defaultPlaceholder;
    if (event.detail.reason === 'logout' || (accountId && nextId && accountId !== nextId)) {
      restart({accountChanged: true});
      accountId = nextId;
    } else if (nextId) accountId = nextId;
    preview?.update(snapshot);
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
  // Keep preview navigation safe even when the optional enhancement fails to
  // load. This guard is synchronous; the shared module also handles formal and
  // dynamically inserted links once available.
  if (practiceKnowledgePreview) {
    const preservePreview = anchor => {
      const href = anchor?.getAttribute('href');
      if (!href || href.startsWith('#') || anchor.hasAttribute('data-learning-exit')) return;
      const url = new URL(href, location.href);
      if (url.origin !== new URL(location.href).origin || !['http:', 'https:'].includes(url.protocol)) return;
      url.searchParams.delete('knowledge');
      url.searchParams.delete('learning');
      url.searchParams.set('preview', '1');
      anchor.setAttribute('href', url.pathname + url.search + url.hash);
    };
    document.querySelectorAll('a[href]').forEach(preservePreview);
    for (const type of ['click', 'auxclick', 'contextmenu']) {
      document.addEventListener(type, event => preservePreview(event.target.closest('a[href]')), true);
    }
  }
  import(new URL('./learning-mode.mjs', runtimeSrc).href).then(module => module.bindModeLinks(document, location.href)).catch(() => {});
  if (practiceKnowledgePreview) {
    const style = document.createElement('style');
    style.textContent = '.composer,[data-hint]{display:none!important}';
    document.head.append(style);
    document.querySelector('.composer').hidden = true;
  }
  let reloadKnowledgePreview = null;
  async function initializeKnowledge() {
    if (reloadKnowledgePreview || !practiceKnowledgeNext) return;
    const style = document.createElement('style');
    if (practiceKnowledgePreview) {
      style.textContent = '.composer,[data-hint]{display:none!important}';
      document.head.append(style);
      document.querySelector('.composer').hidden = true;
    }
    if (practiceKnowledgePreview) {
      const banner = document.createElement('p');
      banner.className = 'kxp-preview-banner';
      banner.textContent = '关联预览 · 不保存练习记录';
      steps.before(banner);
    }
    // Problem-level associations sit below all steps and never compete with the exercise.
    const host = document.createElement('aside');
    host.id = 'knowledge-preview';
    host.className = 'kxp-bar';
    host.setAttribute('aria-label', '本题涉及的题型与方法');
    host.innerHTML = '<p class="kxp-status" role="status"></p><button type="button" class="kxp-reload" hidden>重试</button>';
    host.hidden = true;
    document.querySelector('#completion').after(host);
    const status = host.querySelector('[role="status"]');
    const retry = host.querySelector('button');
    let loading = false;
    async function loadPreview() {
      if (loading) return;
      loading = true;
      retry.hidden = true;
      status.textContent = '';
      try {
        const response = await fetch('/knowledge/teaching/manifest.json', {cache:'no-cache'});
        if (!response.ok) throw Error('新关联目录不可用');
        const manifest = await response.json();
        if (manifest.module !== '/assets/knowledge-next/practice-preview.mjs') {
          throw Error('新关联模块地址无效');
        }
        const module = await import(manifest.module + (retry.dataset.attempt ? '?retry=' + Date.now() : ''));
        const access = await practiceContentReady;
        preview?.update(snapshot);
        host.querySelector('.kxp-associations')?.remove?.();
        preview = await module.createPreview(lesson, host, {
          learning: !practiceKnowledgePreview,
          useServerProgress,
          expectedPracticeVersion: access.practiceVersion,
          problem: access.problem,
          getConfirmedChoices: () => confirmedOnServer,
          getPassedFields: () => passedFieldsOnServer,
          onShown: (view, stage, tip) => {
            if (!practiceAccess.enabled || snapshot.attempt_id !== view.attempt_id || document.visibilityState !== 'visible') return;
            recorderReady.then(r => r?.reference(view, stage, tip.ref, tip.resource));
          }
        });
        preview.update(snapshot);
        status.textContent = '';
        host.hidden = false;
      } catch (error) {
        if (error.code === 'content_version_mismatch') {
          practiceAccess.enabled = false;
          practiceAccess.reason = error.message;
          renderLearningNotice();
          render();
        }
        status.textContent = '本题的题型与方法加载失败，不影响做题。';
        retry.hidden = false;
        host.hidden = false;
        retry.dataset.attempt = '1';
      } finally {
        loading = false;
      }
    }
    retry.addEventListener('click', loadPreview);
    reloadKnowledgePreview = loadPreview;
    await loadPreview();
  }
  let learningNotice = null;
  function renderLearningNotice() {
    document.querySelector('.composer').hidden = !practiceTutorEnabled();
    if (practiceKnowledgePreview) return;
    if (!learningNotice) {
      learningNotice = document.createElement('aside');
      learningNotice.className = 'practice-record-status';
      learningNotice.setAttribute('role', 'status');
      steps.before(learningNotice);
    }
    learningNotice.hidden = practiceAccess.enabled || practiceAccess.published === false;
    if (!practiceAccess.enabled) {
      learningNotice.innerHTML = `<p>${escapeHTML(practiceAccess.reason)} 本次暂不保存进度，点选练习和向老师提问仍可使用。</p><button type="button" data-check-learning>重试保存连接</button> <button type="button" data-refresh-learning>刷新页面</button>`;
      learningNotice.querySelector('[data-refresh-learning]').onclick = () => location.reload();
      learningNotice.querySelector('[data-check-learning]').onclick = async event => {
        event.currentTarget.disabled = true;
        const access = await checkPracticeContent();
        if (access.enabled && recorder && recorderPracticeVersion !== access.practiceVersion) {
          access.enabled = false;
          access.reason = '内容版本已变化，请刷新页面后再保存。';
        } else if (access.enabled && !recorder && (snapshot.completed.length || remote)) {
          // Static work predating the version check is not server-confirmed evidence.
          access.enabled = false;
          access.reason = '学习服务已恢复；当前已有未保存的步骤，请刷新后开始保存。';
        } else if (access.enabled) {
          recorderReady = enableRecorder(access).catch(recorderUnavailable);
          await recorderReady;
          if (access.enabled && runtimeSrc) import(new URL('../learning/learning-marks.js', runtimeSrc).href).catch(() => {});
          await reloadKnowledgePreview?.();
        }
        await initializeKnowledge();
        renderLearningNotice();
        render();
      };
    }
  }
  practiceContentReady.then(() => {
    initializeKnowledge();
    renderLearningNotice();
    render();
  });
  restart({initial: true});
})();
