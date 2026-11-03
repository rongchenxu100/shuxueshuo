import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../../site/assets/learning/practice-records.js', import.meta.url), 'utf8').replace('export function', 'function');
const lesson = {id: 'test-problem', methods: [{id: 'direct', label: '直接法'}, {id: 'other', label: '另一方法'}], routes: {
  direct: [{id: 'first', interaction: {type: 'choice', field: 'a'}}, {id: 'second', interaction: {type: 'choice', field: 'b'}}],
  other: [{id: 'other-first', interaction: {type: 'choice', field: 'c'}}],
}};
const view = (route = 'direct', active = 0) => ({state: {method: route, active, choices: {a: 'yes', b: 'yes', c: 'yes'}}});
const history = (route = 'direct', id = 'attempt') => ({id, route_id: route, status: 'in_progress', steps: [], events: [], active_step: lesson.routes[route][0].id});
const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const deferred = () => { let resolve; const promise = new Promise(r => resolve = r); return {resolve, promise}; };
const tick = () => new Promise(resolve => setImmediate(resolve));

function harness(handler, {store = new Map(), onResume = () => true, user = {id: 'user'}, options = {}} = {}) {
  const elements = new Map(), listeners = {}, posted = [];
  const element = selector => {
    if (!elements.has(selector)) elements.set(selector, {hidden: false, disabled: false, textContent: '', onclick: null});
    return elements.get(selector);
  };
  let serial = 0, reloads = 0;
  const scope = {console, AbortSignal, crypto: {randomUUID: () => `id-${++serial}`},
    window: {SiteAuth: {user}, PracticeContext: {slotCount: () => 2},
      location: {reload: () => reloads++}, addEventListener: (name, fn) => listeners[name] = fn},
    sessionStorage: {getItem: k => store.get(k), setItem: (k, v) => store.set(k, v)},
    document: {createElement: () => ({setAttribute() {}, querySelector: element}), querySelector: () => ({append() {}})},
    fetch: async (url, options) => {
      const body = options.body ? JSON.parse(options.body) : undefined;
      posted.push({url, body}); return handler(url, body);
    },
  };
  vm.createContext(scope); vm.runInContext(source, scope);
  const recorder = scope.createRecorder(lesson, onResume, options);
  return {recorder, posted, store, element, listeners, reloads: () => reloads,
    saved: () => JSON.parse(store.get('sss-practice:user:test-problem')),
    submit: (route = 'direct') => recorder.action(view(route), {event_id: 'answer-id', action: {kind: 'submit'}}, view(route, 1)),
  };
}

test('unrelated release retains queued answers and restores with this problem version', async () => {
  const practiceVersion = 'a'.repeat(64), key = 'sss-practice:user:test-problem:next';
  const store = new Map([[key, JSON.stringify({aid:'saved',route:'direct',contentVersion:'old-release',practiceVersion,
    queue:[{kind:'answer',id:'stable-id',step:'first',answer:{value:'yes'}}]})]]);
  let restored = 0;
  const h = harness((url, body) => {
    if (url.endsWith('/answers')) { assert.equal(body.id, 'stable-id'); return response(history('direct','saved')); }
    assert.equal(url, `/api/learning/practice/saved?practice_version=${practiceVersion}`);
    return response(history('direct', 'saved'));
  }, {store, options:{contentVersion:'new-release',practiceVersion}, onResume:() => {restored++;}});
  await h.recorder.dialogue(view());
  assert.equal(restored, 1);
  assert.equal(h.posted.filter(row => row.url.endsWith('/answers')).length, 1);
  assert.deepEqual(JSON.parse(store.get(key)).queue, []);
  assert.equal(JSON.parse(store.get(key)).practiceVersion, practiceVersion);
});

test('a changed problem contract never replays pending answers even in the same release', async () => {
  const key = 'sss-practice:user:test-problem:next';
  const store = new Map([[key, JSON.stringify({aid:'saved',route:'direct',contentVersion:'release',practiceVersion:'a'.repeat(64),
    queue:[{kind:'answer',id:'stale-answer',step:'first',answer:{value:'yes'}}]})]]);
  const h = harness(() => {throw Error('must not replay');}, {store, options:{contentVersion:'release',practiceVersion:'b'.repeat(64)}});
  await tick(); await h.recorder.flush();
  assert.equal(h.posted.length, 0);
});

test('new starts use the problem token instead of the site release', async () => {
  const practiceVersion = 'b'.repeat(64);
  const h = harness((_url, body) => response({...history(), id:body.id}), {options:{contentVersion:'unrelated-release',practiceVersion}});
  h.recorder.start('direct', 'new-attempt'); await h.recorder.flush();
  assert.equal(h.posted[0].body.practice_version, practiceVersion);
  assert.equal(h.posted[0].body.content_version, undefined);
});

for (const status of [404, 409, 422]) test(`${status} clears rejected/dependent operations and refresh restores confirmed progress`, async () => {
  const h = harness((url, body) => url.endsWith('/practice')
    ? response({...history(), id: body.id}) : response({detail: '不能接受此记录'}, status));
  h.recorder.start('direct', 'start-id'); h.submit();
  await h.recorder.flush();
  assert.deepEqual(h.saved().queue, []);
  assert.equal(h.saved().recovery.kind, 'refresh');
  assert.equal(h.element('[data-retry]').hidden, true);
  assert.equal(h.element('[data-reload]').hidden, false);
  const count = h.posted.length;
  await h.recorder.flush();
  await assert.rejects(h.recorder.dialogue(view()), error => error.code === 'learning_recovery');
  assert.equal(h.posted.length, count);
  h.element('[data-reload]').onclick(); assert.equal(h.reloads(), 1);
  let restored = 0;
  const fresh = harness(url => { assert.equal(url, '/api/learning/practice/start-id'); return response(history('direct', 'start-id')); },
    {store: h.store, onResume: () => { restored++; }});
  assert.equal((await fresh.recorder.dialogue(view())).practice_attempt_id, 'start-id');
  assert.equal(restored, 1); assert.equal(fresh.saved().recovery, null);
  assert.equal(fresh.posted.length, 1); // Only read; never replay the refused answer.
});

for (const status of ['network', 401, 429, 503]) test(`${status} retains the exact operation for retry`, async () => {
  let fail = true;
  const h = harness((url, body) => {
    if (url.endsWith('/practice')) return response({...history(), id: body.id});
    if (fail) { if (status === 'network') throw Error('offline'); return response({}, status); }
    return response({});
  });
  h.recorder.start('direct', 'start-id'); h.submit();
  await assert.rejects(h.recorder.flush());
  assert.equal(h.saved().queue[0].id, 'answer-id');
  assert.equal(h.element('[data-retry]').hidden, false);
  fail = false; await h.recorder.flush();
  const answers = h.posted.filter(item => item.url.endsWith('/answers'));
  assert.deepEqual(answers[0], answers[1]); assert.deepEqual(h.saved().queue, []);
  assert.equal((await h.recorder.dialogue(view('direct', 1))).practice_attempt_id, 'start-id');
});

for (const status of [401, 429]) test(`${status} preserves dependent operations across refresh`, async () => {
  const h = harness((url, body) => url.endsWith('/practice')
    ? response({...history(), id: body.id})
    : {ok: false, status, json: async () => {throw Error('non-JSON error page');}});
  h.recorder.start('direct', 'start-id'); h.submit();
  h.recorder.reference(view(), 0, 'node');
  h.recorder.displayed({event_id: 'display-id', attempt_id: 'start-id'});
  await assert.rejects(h.recorder.flush());
  const pending = h.saved().queue;
  assert.deepEqual(pending.map(op => op.kind), ['answer', 'reference', 'display']);
  assert.equal(h.saved().recovery, null);
  assert.equal(h.element('[data-retry]').hidden, false);
  assert.equal(h.element('[data-reload]').hidden, true);
  assert.match(h.element('span').textContent, status === 401 ? /登录/ : /稍后/);

  const fresh = harness((url, body) => response(body ? {} : history('direct', 'start-id')), {store: h.store});
  assert.equal((await fresh.recorder.dialogue(view('direct', 1))).practice_attempt_id, 'start-id');
  const writes = fresh.posted.filter(op => op.body);
  assert.deepEqual(writes.map(op => op.body.id || op.url.split('/').at(-1)), pending.map(op => op.id));
  assert.deepEqual(writes[0], h.posted.find(op => op.url.endsWith('/answers')));
  assert.deepEqual(fresh.saved().queue, []);
});

test('401 queue resumes after the same account logs in again', async () => {
  let expired = true;
  const h = harness((url, body) => {
    if (expired) return response({detail: '请先登录'}, 401);
    return response(body ? {...history(), id: body.id} : history('direct', 'start-id'));
  });
  h.recorder.start('direct', 'start-id'); h.submit();
  await assert.rejects(h.recorder.flush());
  const pending = h.saved().queue;
  assert.deepEqual(pending.map(op => op.id), ['start-id', 'answer-id']);
  h.listeners['site-auth-change']({detail: {user: null}});
  assert.deepEqual(h.saved().queue, pending);
  const count = h.posted.length;
  h.listeners['site-auth-change']({detail: {user: {id: 'other'}}});
  await tick(); assert.equal(h.posted.length, count);
  h.listeners['site-auth-change']({detail: {user: null}});
  expired = false;
  h.listeners['site-auth-change']({detail: {user: {id: 'user'}}});
  assert.equal((await h.recorder.dialogue(view('direct', 1))).practice_attempt_id, 'start-id');
  const starts = h.posted.filter(op => op.url.endsWith('/practice'));
  assert.deepEqual(starts[0], starts[1]);
  assert.equal(h.posted.find(op => op.url.endsWith('/answers')).body.id, 'answer-id');
  assert.deepEqual(h.saved().queue, []);
});

test('non-JSON 422 is still a permanent rejection', async () => {
  const h = harness(() => ({ok: false, status: 422, json: async () => {throw Error('html');}}));
  h.recorder.start('direct', 'start-id'); await h.recorder.flush();
  assert.equal(h.saved().queue.length, 0); assert.equal(h.element('[data-retry]').hidden, true);
});

for (const restart of [false, true]) test(`slow route conflict waits for explicit ${restart ? 'replacement' : 'continuation'}`, async () => {
  const pending = deferred(), resumes = [];
  const h = harness((url, body) => {
    if (url.endsWith('/practice')) {
      if (!body.previous_attempt_id) return pending.promise;
      assert.equal(body.previous_attempt_id, 'old'); assert.equal(body.route_id, 'other');
      return response(history('other', body.id));
    }
    assert.equal(body, undefined); // New-route answer must not reach the old attempt.
    return response(history(url.endsWith('/old') ? 'direct' : 'other', url.split('/').at(-1)));
  }, {onResume: (data, options) => {resumes.push({data, options});}});
  h.recorder.start('other', 'slow-start'); h.submit('other');
  pending.resolve(response({detail: {code: 'practice_route_conflict', current_attempt: {id: 'old', route_id: 'direct'}}}, 409));
  await h.recorder.flush();
  assert.equal(resumes.length, 0); assert.deepEqual(h.saved().queue, []);
  assert.equal(h.element('[data-continue]').hidden, false);
  assert.equal(h.element('[data-restart]').hidden, false);
  // Refresh must preserve the choice, not repeat the rejected request.
  const fresh = harness((url, body) => {
    if (url.endsWith('/practice')) {
      assert.equal(body.previous_attempt_id, 'old'); assert.equal(body.route_id, 'other');
      return response(history('other', body.id));
    }
    return response(history(restart ? 'other' : 'direct', url.split('/').at(-1)));
  }, {store: h.store, onResume: (data, options) => resumes.push({data, options})});
  await tick(); assert.equal(fresh.posted.length, 0);
  await fresh.element(restart ? '[data-restart]' : '[data-continue]').onclick();
  assert.equal(resumes.length, 1); assert.equal(resumes[0].options.force, true);
  assert.equal(resumes[0].data.route_id, restart ? 'other' : 'direct');
  assert.equal(fresh.saved().recovery, null); assert.equal(fresh.saved().queue.length, 0);
  const binding = await fresh.recorder.dialogue(view(restart ? 'other' : 'direct'));
  assert.equal(binding.practice_attempt_id, resumes[0].data.id);
});

test('slow same-route start drains a submitted answer before UI restoration', async () => {
  const pending = deferred(), order = [];
  const h = harness((url, body) => {
    if (url.endsWith('/practice')) return pending.promise;
    if (url.endsWith('/answers')) {order.push('answer'); return response({});}
    order.push('read'); return response({...history(), active_step: 'second', steps: [{step_id: 'first', passed: true}]});
  }, {onResume: data => { order.push('resume'); assert.equal(data.active_step, 'second'); return true; }});
  h.recorder.start('direct', 'start'); h.submit();
  pending.resolve(response({...history(), steps: [{step_id: 'first', passed: false}]}));
  await h.recorder.flush();
  assert.deepEqual(order, ['answer', 'read', 'resume']); assert.deepEqual(h.saved().queue, []);
});

test('UI progress mismatch never replays an already accepted start', async () => {
  const h = harness((url, body) => response(url.endsWith('/practice')
    ? {...history(), steps: [{step_id: 'first', passed: true}]} : history()), {onResume: () => false});
  h.recorder.start('direct', 'start'); await h.recorder.flush();
  assert.deepEqual(h.saved().queue, []); assert.equal(h.saved().recovery.kind, 'refresh');
  await h.recorder.flush(); assert.equal(h.posted.filter(p => p.url.endsWith('/practice')).length, 1);
});

test('history transport failure remains recoverable after a permanent rejection and reload', async () => {
  const store = new Map([['sss-practice:user:test-problem', JSON.stringify({aid: 'attempt', route: 'direct', queue: [], recovery: {kind: 'refresh', message: 'refresh'}})]]);
  let fail = true, resumed = 0;
  const h = harness(() => { if (fail) throw Error('offline'); return response(history()); }, {store, onResume: () => resumed++});
  await tick(); fail = false; await h.recorder.flush();
  assert.equal(resumed, 1); assert.equal(h.saved().recovery, null);
  assert.equal((await h.recorder.dialogue(view())).practice_attempt_id, 'attempt');
});

test('late rejection from previous account cannot clear the new account queue', async () => {
  const pending = deferred();
  const h = harness(() => pending.promise);
  h.recorder.start('direct', 'old-start');
  h.listeners['site-auth-change']({detail: {user: {id: 'other'}}});
  pending.resolve(response({}, 409)); await tick();
  assert.equal(h.element('[data-reload]').hidden, true);
  assert.equal(h.store.has('sss-practice:other:test-problem'), false);
});

test('missing attempt on refresh releases the old binding', async () => {
  const store = new Map([['sss-practice:user:test-problem', JSON.stringify({aid: 'missing', route: 'direct', queue: []})]]);
  const h = harness((url, body) => response(body ? history('direct', body.id) : {detail: 'not found'}, body ? 200 : 404), {store});
  await tick();
  assert.equal(h.saved().aid, null); assert.equal(h.saved().recovery, null);
  const binding = await h.recorder.dialogue(view()); assert.notEqual(binding.practice_attempt_id, 'missing');
});

test('actual runtime resume callback requires explicit choice for route/progress changes', () => {
  const runtime = fs.readFileSync(new URL('../../site/assets/practice/runtime.js', import.meta.url), 'utf8');
  const start = runtime.indexOf('(history, {force = false} = {}) => {');
  const callback = runtime.slice(start, runtime.indexOf(';\n  let recorder =', start));
  const contextSource = fs.readFileSync(new URL('../../site/assets/practice/context.js', import.meta.url), 'utf8');
  const scope = {window: {}, structuredClone, crypto: {randomUUID: () => 'local-attempt'}, lesson,
    state: {method: 'other', active: 1}, snapshot: {completed: [{node: 'other-first'}]},
    generation: 0, requestController: null, busy: false, remote: {}, pendingOperations: [{}], retryRequest: {},
    retryButton: {}, networkStatus: {}, render() {}, confirmedProgress() {},
  };
  vm.createContext(scope); vm.runInContext(contextSource, scope);
  const resume = vm.runInContext(callback, scope);
  assert.equal(resume(history()), false); assert.equal(scope.state.method, 'other');
  resume(history(), {force: true});
  assert.equal(scope.state.method, 'direct'); assert.equal(scope.state.active, 0);
  assert.equal(scope.snapshot.completed.length, 0); assert.equal(scope.retryRequest, null);
  scope.state.active = 1;
  assert.equal(resume({...history(), active_step: 'second'}), true);
  assert.equal(scope.state.active, 1);
});

for (const conflict of [false, true]) test(`delayed initial login reloads saved ${conflict ? 'route conflict' : 'recovery progress'}`, async () => {
  const recovery = conflict ? {kind: 'route', current: {id: 'attempt', route_id: 'direct'}, requested: 'other', message: 'choose'} : {kind: 'refresh', message: 'refresh'};
  const store = new Map([['sss-practice:user:test-problem', JSON.stringify({aid: 'attempt', route: 'direct', queue: [], recovery})]]);
  let resumed = 0;
  const h = harness(() => response(history()), {store, user: null, onResume: () => resumed++});
  await tick(); assert.equal(h.posted.length, 0);
  h.listeners['site-auth-change']({detail: {user: {id: 'user'}, reason: 'refresh'}});
  await tick();
  if (conflict) {
    assert.equal(h.posted.length, 0); assert.equal(h.element('[data-continue]').hidden, false);
  } else {
    assert.equal(resumed, 1); assert.equal(h.posted.length, 1);
    assert.equal((await h.recorder.dialogue(view())).practice_attempt_id, 'attempt');
  }
});

for (const source of ['rule', 'llm', 'legacy']) test(`runtime restores ${source} conclusions without promoting the last wrong answer`, () => {
  const runtime = fs.readFileSync(new URL('../../site/assets/practice/runtime.js', import.meta.url), 'utf8');
  const start = runtime.indexOf('(history, {force = false} = {}) => {');
  const callback = runtime.slice(start, runtime.indexOf(';\n  let recorder =', start));
  const contextSource = fs.readFileSync(new URL('../../site/assets/practice/context.js', import.meta.url), 'utf8');
  const localLesson = structuredClone(lesson);
  localLesson.routes.direct[0].expected_answer = {one_of: ['right']};
  localLesson.routes.direct[1] = {id: 'second', interaction: {type: 'structure', terms: ['m', 'n']}, expected_answer: {terms: ['m', 'n'], fixed: 'sum'}};
  const scope = {window: {}, structuredClone, crypto: {randomUUID: () => 'local-attempt'}, lesson: localLesson,
    state: {method: null, active: 0}, snapshot: {completed: []}, generation: 0, requestController: null,
    busy: false, remote: {}, pendingOperations: [], retryRequest: null, retryButton: {}, networkStatus: {}, render() {}, confirmedProgress() {},
  };
  vm.createContext(scope); vm.runInContext(contextSource, scope);
  const resume = vm.runInContext(callback, scope);
  const order = source === 'rule' ? ['n', 'm'] : ['m', 'n'];
  const choice = source === 'rule' ? 'also-right' : 'right';
  resume({...history(), active_step: null,
    steps: [{step_id: 'first', passed: true, ...(source !== 'legacy' ? {answer: {value: choice}} : {})},
      {step_id: 'second', passed: true, ...(source !== 'legacy' ? {answer: {terms: order, fixed: 'sum'}} : {})}],
    events: [{step_id: 'first', event_type: 'answer', payload: {value: 'wrong'}},
      {step_id: 'second', event_type: 'answer', payload: {terms: ['m', 'm'], fixed: 'product'}}],
  });
  assert.equal(scope.state.choices.a, choice);
  assert.deepEqual(Array.from(scope.state.pairs[1]), order);
  assert.equal(scope.state.swapped, false);
  assert.equal(scope.state.active, 2); assert.equal(scope.snapshot.completed.length, 2);
});


test('auxiliary reference rejection never discards subsequent formal submissions', async () => {
  const hold = deferred();
  const h = harness((url, body) => {
    if (url.endsWith('/practice')) return hold.promise;
    if (url.endsWith('/references')) return response({detail:'提示分支已改变'}, 422);
    return response({...history(), confirmed_choices:{a:'yes'}});
  });
  h.recorder.start('direct', 'start');
  h.recorder.reference(view(), 0, 'node#entry', 'diagram');
  h.submit();
  hold.resolve(response(history('direct', 'start')));
  await h.recorder.flush();
  assert.equal(h.posted.filter(op => op.url.endsWith('/answers')).length, 1);
  assert.equal(h.saved().recovery, null);
  assert.deepEqual(h.saved().queue, []);
  assert.equal((await h.recorder.dialogue(view())).practice_attempt_id, 'start');
  assert.deepEqual(h.posted.find(op => op.url.endsWith('/references')).body,
    {id:'id-2', step_id:'first', node_id:'node', ref:'node#entry', resource_id:'diagram'});
});

test('new association version travels on starts; confirmation comes from the server', async () => {
  const confirmed = [];
  const h = harness((url, body) => response({...history('direct', body?.id || 'start'), confirmed_choices:{a:'yes'}}),
    {options:{contentVersion:'version-2', onConfirmed:data => confirmed.push(data.confirmed_choices)}});
  h.recorder.start('direct', 'start'); h.submit();
  await h.recorder.flush();
  assert.equal(h.posted[0].body.content_version, 'version-2');
  assert.equal(confirmed.length, 2);
  assert.deepEqual(confirmed[1], {a:'yes'});
  assert.ok(h.store.has('sss-practice:user:test-problem:next'));
});

test('pending submissions from an old association version are never relabeled and replayed', async () => {
  const store = new Map([['sss-practice:user:test-problem:next', JSON.stringify({contentVersion:'old', aid:'attempt', route:'direct', queue:[{kind:'answer', id:'old-answer'}]})]]);
  const h = harness(() => {throw Error('Old operation must not be replayed');}, {store, options:{contentVersion:'new'}});
  await tick();
  assert.equal(h.posted.length, 0);
});

for (const value of [['radical', 'denominator'], 'input_domain']) test(`native graph answers preserve ${Array.isArray(value) ? 'structured' : 'single-choice'} values and retry event identity`, async () => {
  let unavailable = true;
  const h = harness((url, body) => url.endsWith('/practice') ? response({...history(), id: body.id})
    : unavailable ? response({}, 503) : response(history()));
  h.recorder.graphAnswer('direct', 'first', value, 'graph-answer');
  await assert.rejects(h.recorder.flush(), error => error.status === 503);
  unavailable = false;
  await h.recorder.flush();
  const answers = h.posted.filter(op => op.url.endsWith('/answers'));
  assert.equal(answers.length, 2);
  assert.deepEqual(answers[0].body, {id: 'graph-answer', step_id: 'first', answer: {value}});
  assert.deepEqual(answers[1].body, answers[0].body);
});
