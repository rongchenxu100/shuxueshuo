import {isPreview, modeHref, preserveModeLink} from '../practice/learning-mode.mjs';

// Personal state is live authenticated data; grading compatibility is checked per exercise.
export const ABILITY_KINDS = ['knowledge', 'skill', 'method', 'problem_type'];
export const STATUS_LABELS = {unassessed: '未检测', mastered: '已掌握', needs_review: '待巩固'};

// API events retain their real source: diagram displays are hint events, not a
// separate reference type. Keep the display projection independent of the DOM.
export function practiceEventView(event, contexts = new Map()) {
  const value = event.payload || {};
  let title = {context: '题目', answer: '你的作答', grade: '判定',
    message: value.role === 'student' ? '你说' : '导师', hint: '导师提示'}[event.event_type] || event.event_type;
  let text = value.text || value.question || '';
  const details = [];
  if (event.event_type === 'answer') {
    const interaction = contexts.get(event.related_event_id)?.interaction;
    text = interaction?.type === 'choice'
      ? interaction.options.find(option => option.value === value.value)?.label || value.value
      : (value.terms || []).map(term => interaction?.term_labels?.[term] || term).join('，');
    if (value.fixed) details.push(({sum: '定和', product: '定积'})[value.fixed] || value.fixed);
  } else if (event.event_type === 'grade') {
    title = value.source === 'rule' ? '自动判定' : value.source === 'llm' ? '导师判定' : '判定';
    text = {passed: '对了', wrong: '不对', incomplete: '还不完整'}[value.result] || value.result;
  } else if (event.event_type === 'hint' && value.source === 'node_explainer') {
    title = value.resource_id ? '看了图解' : '看了学习提示';
    if (value.candidate) details.push('当时还没选定做法，这是备选提示，不代表用了这种方法。');
  }
  if ((event.event_type === 'hint' || value.role === 'tutor') && !event.displayed_at) {
    details.push('没有显示出来');
  }
  return {title, text, details};
}

let mathReady;
export async function renderLearningMath(root) {
  mathReady ||= (async () => {
    if (!window.katex) await import('/assets/practice/vendor/katex-0.18.9/katex.min.js');
    if (!window.renderMathInElement) await import('/assets/practice/vendor/katex-0.18.9/auto-render.min.js');
    if (!window.PracticeMath) await import('/assets/practice/math-text.js');
  })().catch(error => { mathReady = null; throw error; });
  await mathReady;
  root.querySelectorAll('[data-math-text]').forEach(el => window.PracticeMath.render(el, el.textContent));
}

export function learningHref(path, base = 'https://knowledge.invalid') {
  return modeHref(path, {preview: false}, base);
}

export function preserveLearningLink(anchor, base) {
  preserveModeLink(anchor, base);
}

export function learningDirectoryHref(config, base) {
  const url = new URL(modeHref(config.redirectHref, {preview: isPreview(new URL(base).search)}, base), base);
  if (config.kind === 'textbook') url.searchParams.set('progress', config.id);
  return url.pathname + url.search + url.hash;
}

export function progressScope(search, graph) {
  const params = new URLSearchParams(search);
  return graph ? params.get('scope') || graph.defaultScope : params.get('progress');
}

// AbortSignal.any/timeout are missing in older Safari. Use one controller so
// caller cancellation and our deadline work there too, and release both the
// parent's listener and the timer as soon as this request ends.
function requestCancellation(parent, milliseconds) {
  const controller = new AbortController();
  let timer = null, listening = false, reason;
  const abortError = () => Object.assign(new Error('请求已取消。'), {name: 'AbortError'});
  const cleanup = () => {
    if (timer !== null) { clearTimeout(timer); timer = null; }
    if (listening) { parent.removeEventListener('abort', onAbort); listening = false; }
  };
  const abort = cause => {
    if (controller.signal.aborted) return;
    reason = cause;
    cleanup();
    controller.abort(cause);
  };
  const onAbort = () => abort(parent.reason || abortError());
  if (parent?.aborted) onAbort();
  else {
    if (parent) { parent.addEventListener('abort', onAbort, {once: true}); listening = true; }
    timer = setTimeout(() => abort(Object.assign(new Error('请求超时，请重试。'), {name: 'TimeoutError'})), milliseconds);
  }
  return {
    signal: controller.signal, cleanup,
    // Keep the reason ourselves: older AbortController implementations ignore
    // abort(reason), and a fetch may already have delivered response headers.
    throwIfAborted() { if (controller.signal.aborted) throw reason; }
  };
}

export async function learningApi(path, {body, user, signal} = {}) {
  const cancellation = requestCancellation(signal, 15000);
  try {
    cancellation.throwIfAborted();
    const response = await fetch(path.startsWith('/api/') ? path : `/api/learning${path}`, {
      method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: {'Content-Type': 'application/json', ...(user ? {'X-Learning-User': user} : {})},
      body: body === undefined ? undefined : JSON.stringify(body), signal: cancellation.signal
    });
    cancellation.throwIfAborted();
    let data;
    try { data = await response.json(); }
    catch {
      cancellation.throwIfAborted();
      throw Object.assign(Error('服务响应暂不可用，请重试。'), {retryable: response.ok || response.status >= 500});
    }
    cancellation.throwIfAborted();
    if (!response.ok) {
      const detail = data.detail;
      throw Object.assign(Error(typeof detail === 'string' ? detail : detail?.message || '学习记录暂不可用，请重试。'), {
        status: response.status, code: detail?.code, retryable: [401, 429].includes(response.status) || response.status >= 500
      });
    }
    return data;
  } catch (error) {
    cancellation.throwIfAborted();
    throw error;
  } finally { cancellation.cleanup(); }
}
