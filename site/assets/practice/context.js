/* Local practice state. No network and no model calls. */
(() => {
  'use strict';
  const copy = value => structuredClone(value);
  const freshState = lesson => ({active: 0, method: null, swapped: false,
    pairs: Array.from({length: Math.max(...Object.values(lesson.routes).map(nodes => nodes.length))}, () => ['', '']),
    choices: Object.fromEntries(Object.values(lesson.routes).flat().filter(node => node.interaction.type === 'choice').map(node => [node.interaction.field, null])), feedback: '', hint: false});
  const done = (lesson, state) => Boolean(state.method) && state.active >= lesson.routes[state.method].length;
  const slotCount = component => component.slots?.length ?? component.slot_labels?.length ?? 2;
  // Recover the last confirmed UI combination from Context. Dialogue does not
  // erase it; any new UI selection requires confirmation again.
  function confirmedPair(view) {
    const {state} = view;
    const operations = view.messages.filter(message => message.kind === 'ui' &&
      message.attempt_id === view.attempt_id && message.route === state.method && message.stage === state.active);
    if (operations.at(-1)?.action.kind !== 'submit') return null;
    // State keeps two storage cells even for a one-slot fill.
    const pair = Array(state.pairs[state.active].length).fill('');
    for (const {action} of operations) {
      if (action.kind === 'fill') pair[action.index] = action.value;
    }
    return pair.length && JSON.stringify(pair) === JSON.stringify(state.pairs[state.active]) ? pair : null;
  }
  // A slot with names selects up to names.length targets, joined by "|" in option order; "" clears it.
  function slotAccepts(slot, value) {
    if (!slot) return false;
    const values = slot.options.map(option => option.value);
    if (!slot.names) return values.includes(value);
    const parts = value ? value.split('|') : [];
    return parts.length <= slot.names.length && parts.every((part, i) => values.includes(part) && (i === 0 || values.indexOf(parts[i - 1]) < values.indexOf(part)));
  }
  function create(lesson, id) {
    return {session_id: null, revision: 0, lesson_id: lesson.id, lesson_version: lesson.version,
      attempt_id: id, attempts: [], state: freshState(lesson), messages: [], completed: [], accepted_evidence: []};
  }
  const position = view => ({route: view.state.method, stage: view.state.active,
    attempt: view.attempts.filter(item => item.id !== view.attempt_id).length});
  function reconcile(view, operations, lesson) {
    const remaining = [];
    for (const operation of operations) {
      const current = position(view), original = operation.position;
      // The reply may have confirmed a step that the student also completed
      // locally while offline. Never reinterpret those old fills as a new step.
      if (original.attempt === current.attempt && original.route === current.route && original.stage < current.stage) continue;
      if (JSON.stringify(original) !== JSON.stringify(current)) throw Error('老师回复改变了路径，与断线后的操作冲突。本地进度保持不变，可重新练习后开始新对话。');
      view = apply(view, operation, lesson); remaining.push(operation);
    }
    return {view, remaining};
  }
  function attempt(view, lesson) {
    return copy({id: view.attempt_id, route: view.state.method,
      status: done(lesson, view.state) ? 'completed' : 'learning', state: view.state,
      completed: view.completed, accepted_evidence: view.accepted_evidence,
      messages: view.messages.filter(message => message.attempt_id === view.attempt_id)});
  }
  function validate(node, state) {
    const component = node.interaction, expected = node.expected_answer, feedback = node.feedback || {};
    if (component.type === 'choice') {
      if (!expected.one_of.includes(state.choices[component.field])) throw Error(feedback.answer || '还需要表达你对这个问题的判断。');
    } else {
      const ordered = ['symmetry', 'substitution', 'homogeneity', 'fill', 'rewrite'].includes(component.type);
      const actual = state.pairs[state.active].slice(0, slotCount(component)), wanted = [...expected.terms];
      if (JSON.stringify(ordered ? actual : actual.sort()) !== JSON.stringify(ordered ? wanted : wanted.sort())) throw Error(feedback.terms || '再看看两个数学项是否对应。');
      if (component.type === 'structure' && ((state.swapped ? 'product' : 'sum') !== expected.fixed || (state.swapped ? 'sum' : 'product') !== expected.target)) throw Error(feedback.structure || '再看看条件和目标的关系。');
    }
  }
  function apply(view, operation, lesson) {
    const next = copy(view), before = copy(view.state), action = operation.action;
    let state = next.state;
    state.feedback = ''; state.hint = false;
    let reply = null, switched = false;
    try {
      if (action.kind === 'switch_route') {
        if (!lesson.routes[action.value]) throw Error('这条路径暂不可用，请选择题目提供的解题路径。');
        if (next.attempts.filter(item => item.id !== next.attempt_id).length >= 20) throw Error('本次会话的路径尝试已达演示上限，请重新体验。');
        switched = true;
      } else if (action.kind === 'method') {
        if (state.active !== 0 || !lesson.routes[action.value]) throw Error('当前步骤不能直接更换方法，请使用切换路径。');
        if (state.method !== action.value) {
          state = next.state = freshState(lesson); state.method = action.value;
          next.accepted_evidence = [];
        }
      } else {
        const node = lesson.routes[state.method]?.[state.active];
        if (!node) throw Error('当前没有可作答的节点，请选择可用路径。');
        const component = node.interaction;
        if (action.kind === 'submit') { validate(node, state); state.active++; }
        else if (action.kind === 'fill' && Number.isInteger(action.index) && action.index >= 0 && action.index < slotCount(component) && (component.slots
          ? slotAccepts(component.slots[action.index], action.value)
          : component.terms?.includes(action.value))) {
          const pair = state.pairs[state.active];
          while (pair.length < action.index) pair.push('');
          pair[action.index] = action.value;
        }
        else if (action.kind === 'swap' && component.type === 'structure' && ['sum', 'product'].includes(action.value)) state.swapped = action.value === 'product';
        else if (action.kind === 'choice' && component.type === 'choice' && component.options.some(option => option.value === action.value)) state.choices[component.field] = action.value;
        else throw Error('这个操作不属于当前节点。');
      }
    } catch (error) {
      state = next.state = before; state.feedback = error.message; reply = error.message;
    }
    next.messages.push({role: 'student', kind: 'ui', action: copy(action), stage: before.active,
      route: before.method, attempt_id: next.attempt_id, event_id: operation.event_id});
    if (switched) {
      const archived = attempt(next, lesson);
      if (archived.status !== 'completed') archived.status = 'paused';
      next.attempts = next.attempts.filter(item => item.id !== next.attempt_id).concat(archived);
      next.attempt_id = operation.event_id;
      state = next.state = freshState(lesson); state.method = action.value;
      next.completed = []; next.accepted_evidence = [];
      reply = `好，我们再用“${lesson.methods.find(method => method.id === action.value).label}”试一次。`;
    }
    if (reply) next.messages.push({role: 'assistant', kind: 'text', text: reply,
      stage: switched ? 0 : before.active, route: state.method, attempt_id: next.attempt_id});
    if (!switched && state.active > before.active) {
      next.completed.push({stage: before.active, node: lesson.routes[state.method][before.active].id,
        route: state.method, state: copy(state), source: 'ui'});
      next.accepted_evidence = [];
    }
    next.attempts = next.attempts.filter(item => item.id !== next.attempt_id).concat(attempt(next, lesson));
    return next;
  }
  globalThis.PracticeContext = {create, apply, freshState, done, position, reconcile, slotCount, confirmedPair};
})();
