/* A separate recording channel. Transport, 401/429 and 5xx failures retain operations for retry. */
export function createRecorder(lesson, onResume, {contentVersion = null, practiceVersion = null, onConfirmed = null} = {}) {
  let owner = window.SiteAuth?.user?.id, aid = null, route = null;
  let queue = [], running = null, epoch = 0, failed = false, restoring = false;
  let recovery = null, resume = null, resolving = false;
  const key = () => `sss-practice:${owner}:${lesson.id}${contentVersion || practiceVersion ? ":next" : ""}`;
  const save = () => {
    if (owner) try { sessionStorage.setItem(key(), JSON.stringify({aid, route, queue, recovery, resume, contentVersion, practiceVersion})); } catch {}
  };
  let saved = null;
  function loadSaved() {
    saved = null;
    try { saved = owner ? JSON.parse(sessionStorage.getItem(key()) || 'null') : null; } catch {}
    const compatible = saved && (practiceVersion && saved.practiceVersion
      ? saved.practiceVersion === practiceVersion : saved.contentVersion === contentVersion);
    if (saved && !compatible && (contentVersion || practiceVersion)) {
      // Never replay an old page's pending operations using newly published associations.
      saved = null;
    }
    if (saved) {
      aid = saved.aid; route = saved.route; queue = saved.queue || [];
      recovery = saved.recovery || null; resume = saved.resume || null;
    }
  }
  loadSaved();

  const notice = document.createElement('div');
  notice.className = 'practice-record-status'; notice.setAttribute('role', 'status');
  notice.innerHTML = '<span></span> <button type="button" data-retry hidden>重试保存</button> <button type="button" data-reload hidden>刷新并继续</button> <button type="button" data-continue hidden>继续旧路线</button> <button type="button" data-restart hidden>按所选路线重新开始</button>';
  document.querySelector('.workspace, .gw-workspace')?.append(notice);
  const buttons = Object.fromEntries(['retry', 'reload', 'continue', 'restart'].map(name => [name, notice.querySelector(`[data-${name}]`)]));
  const say = (text, retry = false) => {
    notice.querySelector('span').textContent = text;
    for (const button of Object.values(buttons)) { button.hidden = true; button.disabled = resolving; }
    buttons.retry.hidden = !retry;
    if (recovery?.kind === 'route') buttons.continue.hidden = buttons.restart.hidden = false;
    else if (recovery) buttons.reload.hidden = false;
  };
  const recoveryError = () => Object.assign(Error(recovery?.message || '请先恢复已保存的练习。'), {code: 'learning_recovery'});
  const showRecovery = () => {
    say(recovery.message);
    notice.scrollIntoView?.({block: 'center', behavior: 'smooth'});
  };
  function reject(error, op) {
    // Later submissions depend on this operation's route/progress. Never attach
    // them to another attempt, or leave them available for replay after refresh.
    queue = []; resume = null; failed = false;
    const current = error.detail?.current_attempt;
    if (op?.kind === 'start' && error.detail?.code === 'practice_route_conflict' && current?.id && current?.route_id) {
      const label = lesson.methods?.find(method => method.id === current.route_id)?.label || current.route_id;
      recovery = {kind: 'route', current, requested: op.route,
        message: `本题已有“${label}”路线的练习。请选择继续旧路线，或按刚选的路线重新开始；尚未保存的操作不会写入旧练习。`};
    } else {
      recovery = {kind: 'refresh', message: `${error.message} 未确认的操作已停止保存，请刷新页面，从服务端已确认的进度继续。`};
    }
    save(); showRecovery();
  }
  buttons.retry.onclick = () => flush().catch(() => {});
  buttons.reload.onclick = () => window.location.reload();
  buttons.continue.onclick = () => resolveRoute(false);
  buttons.restart.onclick = () => resolveRoute(true);
  window.addEventListener('site-auth-change', event => {
    const next = event.detail.user?.id;
    if (next === owner) return;
    const firstLogin = !owner && next;
    epoch++; owner = next; aid = null; route = null;
    if (!firstLogin) queue = [];
    running = null; restoring = false; recovery = resume = null; failed = resolving = false; say('');
    // Auth's ready promise means its UI mounted; the cookie lookup may finish
    // later. Load this account's saved queue when that initial lookup completes.
    if (firstLogin && !queue.length) { loadSaved(); restored = restoreSaved(); }
    else if (firstLogin) flush().catch(() => {});
  });

  async function api(path, body) {
    // Bind history restores to this page as well as new starts. The server
    // validates against frozen attempt data before we replay any old answers.
    if (body === undefined && practiceVersion && /^\/practice\/[^/]+$/.test(path)) {
      path += '?practice_version=' + encodeURIComponent(practiceVersion);
    }
    let response;
    try {
      response = await fetch('/api/learning' + path, {
        method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: {'Content-Type': 'application/json', 'X-Learning-User': owner},
        body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(15000),
      });
    } catch (error) { error.retryable = true; throw error; }
    let data;
    try { data = await response.json(); }
    catch { data = {}; if (response.ok) throw Object.assign(Error('学习记录响应不完整，请重试。'), {retryable: true}); }
    if (!response.ok) {
      const detail = data.detail;
      const fallback = response.status === 401 ? '登录已过期，请登录后重试保存。'
        : response.status === 429 ? '保存请求过于频繁，请稍后重试。' : '服务端未接受这条学习记录。';
      throw Object.assign(Error(typeof detail === 'string' ? detail : detail?.message || fallback),
        {status: response.status, detail, retryable: [401, 429].includes(response.status) || response.status >= 500});
    }
    return data;
  }

  async function applyHistory(history, force = false) {
    if (history.status === 'closed') throw Error('本次练习已结束，请重新选择路线。');
    onConfirmed?.(history);
    if (onResume?.(history, {force}) === false) throw Error('已保存的进度与当前页面不同。');
  }

  async function flush() {
    if (running) return running;
    if (recovery) { showRecovery(); return; }
    const ticket = epoch;
    running = (async () => {
      failed = false;
      while (queue.length && owner && ticket === epoch && !recovery) {
        const op = queue[0];
        try {
          if (op.kind === 'start') {
            // Freeze the replacement target for retries, even if the response is lost.
            if (!Object.hasOwn(op, 'previous')) { op.previous = aid; save(); }
            const data = await api('/practice', {
              id: op.id, problem_id: lesson.id, route_id: op.route, previous_attempt_id: op.previous,
              ...(practiceVersion ? {practice_version: practiceVersion}
                : contentVersion ? {content_version: contentVersion} : {}),
            });
            if (ticket !== epoch) return;
            if (data.route_id !== op.route) throw Error('返回的练习路线与所选路线不同。');
            aid = data.id; route = data.route_id; onConfirmed?.(data);
            // Commit the start before reading history or calling the UI. A slow
            // start may already have locally queued answers; drain them first.
            resume = op.resume || data.steps.length || restoring ? {id: aid, force: Boolean(op.resume)} : null;
          } else if (op.kind === 'answer' || op.kind === 'reference') {
            if (!aid) throw Error('请先选择解题路线。');
            if (op.route && route !== op.route) throw Error('操作对应的路线与本次练习不同。');
            if (op.kind === 'answer') {
              const history = await api(`/practice/${aid}/answers`, {id: op.id, step_id: op.step, answer: op.answer});
              if (ticket !== epoch) return;
              onConfirmed?.(history);
            }
            else await api(`/practice/${aid}/references`, {id: op.id, step_id: op.step, node_id: op.node.split('#')[0], ref: op.node, ...(op.resource ? {resource_id: op.resource} : {})});
          } else if (op.kind === 'display') {
            await api(`/practice/${op.attempt}/displayed/${op.id}`, {});
          }
        } catch (error) {
          if (ticket !== epoch) return;
          if (error.retryable) throw error;
          if (op.kind === 'reference' && error.status >= 400 && error.status < 500) {
            queue.shift(); save();
            say('这条提示展示记录未保存；后续作答仍会正常保存。');
            continue;
          }
          reject(error, op); return;
        }
        if (ticket !== epoch) return;
        queue.shift(); save(); say('学习记录已保存');
      }
      if (resume && !recovery && owner && ticket === epoch) {
        const pending = resume;
        try {
          const history = await api(`/practice/${pending.id}`);
          if (ticket !== epoch) return;
          if (queue.length) return; // New input arrived during the read; flush it first.
          await applyHistory(history, pending.force);
          if (ticket !== epoch) return;
          resume = null; save();
        } catch (error) {
          if (ticket !== epoch) return;
          if (error.retryable) throw error;
          reject(error);
        }
      }
    })().catch(error => {
      if (ticket === epoch) { failed = true; say(`${error.message} 当前页面保留待保存内容。`, true); }
      throw error;
    }).finally(() => {
      if (ticket !== epoch) return;
      running = null;
      if (!failed && !recovery && owner && queue.length) return flush();
    });
    return running;
  }

  async function resolveRoute(restart) {
    if (resolving || recovery?.kind !== 'route') return;
    const choice = recovery, ticket = epoch;
    resolving = true; showRecovery();
    try {
      if (running) await running.catch(() => {});
      if (ticket !== epoch) return;
      if (restart) {
        queue = [{kind: 'start', route: choice.requested, id: crypto.randomUUID(), previous: choice.current.id, resume: true}];
        recovery = null; save(); await flush();
      } else {
        const history = await api(`/practice/${choice.current.id}`);
        if (ticket !== epoch) return;
        await applyHistory(history, true);
        if (ticket !== epoch) return;
        aid = history.id; route = history.route_id; queue = []; resume = recovery = null; failed = false;
        save(); say('已继续原路线，后续操作会保存到这次练习。');
      }
    } catch (error) {
      if (ticket !== epoch) return;
      if (error.retryable) say(error.message, !recovery);
      else reject(error);
    } finally {
      if (ticket === epoch) {
        resolving = false;
        for (const button of Object.values(buttons)) button.disabled = false;
      }
    }
  }

  function start(routeId, id) {
    if (recovery) return showRecovery();
    queue.push({kind: 'start', route: routeId, id}); save(); flush().catch(() => {});
  }
  function ensureRoute(routeId, id = crypto.randomUUID()) {
    if (recovery) return;
    const planned = queue.filter(op => op.kind === 'start').at(-1);
    if (planned ? planned.route !== routeId : (!aid || route !== routeId)) start(routeId, id);
  }
  function action(before, operation, after) {
    if (recovery) return showRecovery();
    const action = operation.action;
    if (['method', 'switch_route'].includes(action.kind) && after.state.method) {
      ensureRoute(after.state.method, operation.event_id); return;
    }
    if (action.kind !== 'submit') return;
    ensureRoute(before.state.method);
    const step = lesson.routes[before.state.method][before.state.active], component = step.interaction;
    const answer = component.type === 'choice'
      ? {value: before.state.choices[component.field]}
      : {terms: before.state.pairs[before.state.active].slice(0, window.PracticeContext.slotCount(component)),
        ...(component.type === 'structure' ? {fixed: before.state.swapped ? 'product' : 'sum'} : {})};
    queue.push({kind: 'answer', id: operation.event_id, route: before.state.method, step: step.id, answer}); save(); flush().catch(() => {});
  }
  // Native graph-walk decisions use their own versioned contract, not tutor actions.
  function graphAnswer(routeId, step, value, id = crypto.randomUUID()) {
    if (recovery) return showRecovery();
    ensureRoute(routeId);
    queue.push({kind: 'answer', id, route: routeId, step, answer: {value}});
    save(); flush().catch(() => {});
  }
  async function dialogue(view) {
    if (!owner || !view.state.method) return {};
    await restored;
    if (recovery) throw recoveryError();
    ensureRoute(view.state.method);
    await flush();
    if (recovery) throw recoveryError();
    if (failed) throw Error('请先重试保存学习记录。');
    const steps = lesson.routes[view.state.method];
    return {practice_attempt_id: aid, practice_step_id: steps[Math.min(view.state.active, steps.length - 1)].id};
  }
  function displayed(delivery) {
    if (!delivery || !owner || recovery) return;
    queue.push({kind: 'display', id: delivery.event_id, attempt: delivery.attempt_id}); save(); flush().catch(() => {});
  }
  function reset() {
    route = null; save(); // Keep aid so explicit route selection closes the old attempt.
  }
  async function restoreSaved() {
    if (!owner || !saved) return;
    const ticket = epoch;
    restoring = true;
    try {
      await flush();
      if (ticket !== epoch || recovery?.kind === 'route') { if (recovery) showRecovery(); return; }
      if (!aid || (!route && !recovery)) { recovery = null; save(); return; }
      recovery = null; save();
      const history = await api(`/practice/${aid}`);
      if (ticket !== epoch) return;
      if (history.status === 'closed') { aid = route = recovery = resume = null; queue = []; save(); say('原练习已结束，请重新选择路线。'); return; }
      await applyHistory(history);
      if (ticket !== epoch) return;
      recovery = resume = null; save(); say('已恢复服务端确认的练习进度。');
    } catch (error) {
      if (ticket !== epoch) return;
      if (error.retryable) { failed = true; if (!queue.length && aid) resume = {id: aid, force: false}; save(); say(error.message, true); }
      else if (error.status === 404) { aid = route = recovery = resume = null; queue = []; save(); say('原练习不可用，请重新选择路线。'); }
      else reject(error);
    } finally {
      if (ticket === epoch) restoring = false;
    }
  }
  let restored = restoreSaved();
  function reference(view, stage, node, resource) {
    if (!view.state.method || recovery) return;
    ensureRoute(view.state.method);
    queue.push({kind: 'reference', id: crypto.randomUUID(), route: view.state.method, step: lesson.routes[view.state.method][stage].id, node, resource});
    save(); flush().catch(() => {});
  }
  async function routed(view) {
    if (!view.state.method) return;
    ensureRoute(view.state.method);
    if (!onConfirmed || !owner) return;
    const ticket = epoch;
    try {
      await flush();
      if (!aid || recovery) return;
      const history = await api(`/practice/${aid}`);
      if (ticket === epoch) onConfirmed(history);
    } catch (error) { if (ticket === epoch) say(error.message, Boolean(error.retryable)); }
  }
  return {action, graphAnswer, dialogue, displayed, reset, start, flush, reference, routed};
}
