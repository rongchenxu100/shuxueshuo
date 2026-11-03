import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {isPreview, modeHref, preserveModeLink} from '../../site/assets/practice/learning-mode.mjs';
import * as compatibility from '../../site/assets/learning/practice-compatibility.mjs';

const source = fs.readFileSync(new URL('../../site/assets/practice/runtime.js', import.meta.url), 'utf8');
const gate = source.slice(0, source.indexOf('const practiceAuthReady')).replace(
  "import(new URL('../learning/practice-compatibility.mjs', practiceRuntimeSrc).href)", 'Promise.resolve(compatibilityModule)');
const config = {id: 'q01', routes: {direct: [{id: 's1', question: '选择', interaction: {type: 'choice'}, expected_answer: {one_of: ['yes']}}]}};
const pageHash = await compatibility.pageContractHash(config), practiceVersion = 'a'.repeat(64);
const requestSource = source.slice(source.indexOf('  function updateBusy()'), source.indexOf('  function conversation(')) +
  source.slice(source.indexOf('  async function request(payload)'), source.indexOf('  function sendEvent('));
const recorderFailureSource = source.slice(source.indexOf('  function recorderUnavailable()'), source.indexOf('  async function enableRecorder('));
const reply = body => ({ok:true, headers:new Headers(), json:async () => body});

function harness({search = '', registered = true, content = 'current', pathname = '/1/q01/'} = {}) {
  const calls = [], state = {method:null, active:0};
  let mode = content;
  const scope = {
    compatibilityModule: compatibility,
    URL, URLSearchParams, AbortSignal, AbortController, Headers, setTimeout, clearTimeout, structuredClone,
    location:{search, pathname, href:`https://example.org${pathname}${search}`},
    document:{currentScript:{src:'https://example.org/assets/practice/runtime.js'},
      getElementById:() => ({textContent:JSON.stringify(config)}), querySelectorAll:() => [], querySelector:() => null},
    busy:false, dialoguePause:null, generation:0, state, snapshot:{attempt_id:'local-attempt',state,completed:[]},
    retryRequest:null, requestController:null, remote:null, pendingOperations:[], practiceAuthReady:Promise.resolve(),
    recorderReady:Promise.resolve({dialogue:async () => ({practice_attempt_id:'saved'}), routed() {}}),
    window:{SiteAuth:{requireLogin:async () => ({id:'student'})}}, api:'/api/tutor-demo', lesson:{id:'q01',routes:{}},
    steps:{querySelectorAll:() => [],setAttribute() {}}, picker:{querySelectorAll:() => []},
    messageInput:{value:'为什么？'}, sendButton:{}, retryButton:{}, networkStatus:{},
    pauseIdle() {}, resumeIdle() {}, showProgress() {}, announce() {}, completed:() => false,
    preview:null, renderLearningNotice() {},
    PracticeContext:{reconcile:data => ({view:data,remaining:[]})},
    acceptSnapshot(data) { scope.snapshot = data; scope.state = data.state; },
    fetch:async (url, options) => {
      calls.push({url, body:options?.body ? JSON.parse(options.body) : null});
      if (url === '/knowledge/teaching/problems.json') {
        if (mode === 'registry-offline') throw Error('offline');
        return reply({content_version:'current',problems:registered ? {q01:{path:'/1/q01/',topic:'basic-inequality'}} : {}});
      }
      if (url === '/api/learning/content/problems/q01') {
        if (mode === 'pending') return new Promise(() => {});
        if (mode === 'offline') throw Error('offline');
        if (mode === 'missing') return {ok:false,status:404};
        if (mode === 'malformed') return reply({});
        return reply({practice_version:mode === 'mismatch' ? 'changed' : practiceVersion,content_version:'current'});
      }
      if (url.startsWith('/knowledge/')) return reply({id:'q01', page_contract_hash:pageHash,
        practice_version:practiceVersion, content_version:'old-release'});
      if (url.endsWith('/sessions')) return reply({session_id:'standalone',revision:0});
      return reply({session_id:'standalone',revision:1,attempt_id:'local-attempt',state,messages:[{text:'提示内容'}]});
    }
  };
  vm.createContext(scope);
  const contentReady = vm.runInContext(gate + '\npracticeContentReady', scope);
  vm.runInContext(requestSource + recorderFailureSource, scope);
  return {scope,calls,contentReady,setMode(value) { mode = value; },run:code => vm.runInContext(code, scope)};
}

const ask = h => h.scope.request({event_id:'ask',revision:0,kind:'text',text:'为什么？',pending_operations:[]});

test('published registry identity and path enable ordinary learning without a mode flag', async () => {
  for (const search of ['', '?knowledge=next&learning=1']) {
    const h = harness({search});
    await h.contentReady;
    assert.equal(h.run('practiceAccess.enabled'), true);
    await ask(h);
    assert.deepEqual(h.calls.find(call => call.url.endsWith('/sessions')).body,
      {lesson_id:'q01',practice_attempt_id:'saved',practice_version:practiceVersion});
  }
  const unrelated = harness({pathname:'/unpublished/q01/'});
  await unrelated.contentReady;
  assert.equal(unrelated.run('practiceAccess.enabled'), false);
  assert.equal(unrelated.run('practiceAccess.published'), false);
  assert.ok(!unrelated.calls.some(call => call.url.startsWith('/api/learning/')));
});

test('unpublished runtime users keep standalone tutor without learning API requests', async () => {
  const h = harness({registered:false});
  await h.contentReady;
  assert.equal(h.run('practiceAccess.enabled'), false);
  h.scope.updateBusy();
  assert.equal(Boolean(h.scope.messageInput.disabled), false);
  await ask(h);
  assert.deepEqual(h.calls.find(call => call.url.endsWith('/sessions')).body, {lesson_id:'q01'});
  assert.ok(!h.calls.some(call => call.url.startsWith('/api/learning/')));
});

test('metadata failure or delay never blocks standalone tutor and never binds a false attempt', async () => {
  for (const content of ['offline','missing','malformed','mismatch','registry-offline','pending']) {
    const h = harness({content});
    if (content !== 'pending') await h.contentReady;
    h.scope.updateBusy();
    assert.equal(Boolean(h.scope.messageInput.disabled), false, content);
    await ask(h);
    assert.deepEqual(h.calls.find(call => call.url.endsWith('/sessions')).body, {lesson_id:'q01'}, content);
  }
});

test('choosing a recorded route starts a bound tutor without reattributing earlier independent dialogue', async () => {
  const h = harness();
  h.scope.recorderReady = Promise.resolve({dialogue:async view => view.state.method ? {practice_attempt_id:'saved'} : {}, routed() {}});
  await h.contentReady;
  await ask(h);
  assert.equal(h.scope.remote.practiceAttemptId, null);
  h.scope.state.method = 'main';
  h.scope.lesson.routes.main = [];
  h.scope.pendingOperations = [{event_id:'independent-operation'}];
  await ask(h);
  const sessions = h.calls.filter(call => call.url.endsWith('/sessions'));
  assert.equal(sessions.length, 2);
  assert.deepEqual(sessions[0].body, {lesson_id:'q01'});
  assert.deepEqual(sessions[1].body, {lesson_id:'q01',practice_attempt_id:'saved',practice_version:practiceVersion});
  const savedEvent = h.calls.filter(call => call.url.endsWith('/events')).at(-1);
  assert.equal(savedEvent.body.practice_attempt_id, 'saved');
  assert.deepEqual(savedEvent.body.pending_operations, []);
  assert.equal(h.scope.remote.practiceAttemptId, 'saved');
});

function attachNotice(h) {
  const from = source.indexOf('  let learningNotice = null;');
  const notice = source.slice(from, source.indexOf('  practiceContentReady.then(() => {', from));
  const controls = new Map();
  const composer = {hidden:false}, aside = {innerHTML:'', setAttribute() {}, querySelector(selector) {
    if (!controls.has(selector)) controls.set(selector, {});
    return controls.get(selector);
  }};
  Object.assign(h.scope, {document:{...h.scope.document, querySelector:() => composer, createElement:() => aside}, steps:{...h.scope.steps, before() {}}});
  h.run(source.slice(source.indexOf('  const escapeHTML'), source.indexOf('\n', source.indexOf('  const escapeHTML'))) +
    `\n${notice}\nrenderLearningNotice();`);
  return {composer, aside};
}

async function renderNotice(options = {}) {
  const h = harness({...options,content:'offline'});
  await h.contentReady;
  return attachNotice(h);
}

test('failed published learning explains unsaved work while keeping tutor and retry', async () => {
  const {composer, aside} = await renderNotice();
  assert.equal(composer.hidden, false);
  assert.match(aside.innerHTML, /本次暂不保存进度/);
  assert.match(aside.innerHTML, /data-check-learning/);
  assert.match(aside.innerHTML, /data-refresh-learning/);
  assert.doesNotMatch(aside.innerHTML, /联调/);
  assert.equal((await renderNotice({registered:false})).aside.hidden, true);
});

test('recorder import failure while a question waits shows unsaved notice and keeps the tutor independent', async () => {
  const h = harness();
  await h.contentReady;
  const {composer, aside} = attachNotice(h);
  let rejectImport;
  h.scope.recorderReady = new Promise((resolve, reject) => { rejectImport = reject; })
    .catch(h.scope.recorderUnavailable);
  const asking = ask(h);
  await Promise.resolve();
  rejectImport(Error('module unavailable'));
  await asking;
  assert.equal(h.run('practiceAccess.enabled'), false);
  assert.match(aside.innerHTML, /学习记录组件加载失败/);
  assert.match(aside.innerHTML, /本次暂不保存进度/);
  assert.match(aside.innerHTML, /data-check-learning/);
  assert.equal(aside.hidden, false);
  assert.equal(composer.hidden, false);
  assert.deepEqual(h.calls.find(call => call.url.endsWith('/sessions')).body, {lesson_id:'q01'});
  assert.ok(!h.calls.some(call => call.body?.practice_attempt_id));
  assert.doesNotMatch(h.scope.networkStatus.textContent, /组件不可用/);
});

test('recorder retry reports repeated failure then enables saving only after successful loading', async () => {
  const h = harness();
  await h.contentReady;
  const {aside} = attachNotice(h);
  let fail = true;
  Object.assign(h.scope, {
    recorder:null, runtimeSrc:null, reloadKnowledgePreview:null,
    initializeKnowledge:async () => {}, render() {},
    enableRecorder:async () => {
      if (fail) throw Error('module unavailable');
      h.scope.recorder = {dialogue:async () => ({practice_attempt_id:'saved'}), routed() {}};
      return h.scope.recorder;
    }
  });
  // Use the actual startup expression and the actual notice retry handler.
  h.run('recorderReady = ' + source.match(/let recorderReady = ([^;]+);/)[1]);
  await h.scope.recorderReady;
  const retry = () => aside.querySelector('[data-check-learning]').onclick({currentTarget:{}});
  await retry();
  assert.equal(h.run('practiceAccess.enabled'), false);
  assert.equal(aside.hidden, false);
  fail = false;
  await retry();
  assert.equal(h.run('practiceAccess.enabled'), true);
  assert.equal(aside.hidden, true);
  await ask(h);
  assert.equal(h.calls.find(call => call.url.endsWith('/sessions')).body.practice_attempt_id, 'saved');
});

test('recovering the recorder after unsaved work requires refresh instead of attributing it retroactively', async () => {
  for (const work of [{completed:[{}]}, {remote:{session_id:'standalone'}}]) {
    const h = harness();
    await h.contentReady;
    const {aside} = attachNotice(h);
    Object.assign(h.scope, {recorder:null, runtimeSrc:null, initializeKnowledge:async () => {}, render() {},
      enableRecorder:() => {throw Error('must not start recording');}});
    h.scope.recorderUnavailable();
    if (work.completed) h.scope.snapshot.completed = work.completed;
    if (work.remote) h.scope.remote = work.remote;
    await aside.querySelector('[data-check-learning]').onclick({currentTarget:{}});
    assert.equal(h.run('practiceAccess.enabled'), false);
    assert.match(aside.innerHTML, /当前已有未保存的步骤，请刷新/);
  }
});

test('explicit preview dominates legacy learning flags and never opens tutor or learning API', async () => {
  for (const search of ['?preview=1','?knowledge=next','?preview=1&knowledge=next&learning=1']) {
    const h = harness({search});
    await h.contentReady;
    h.scope.updateBusy();
    assert.equal(h.scope.messageInput.disabled, true);
    await ask(h);
    assert.equal(h.run('practiceAccess.enabled'), false);
    assert.equal(h.calls.filter(call => call.url.startsWith('/api/')).length, 0);
    assert.equal(isPreview(search), true);
  }
  assert.equal(isPreview('?knowledge=next&learning=1'), false);
});

test('retry revalidates publication version without relaxing write checks', async () => {
  const h = harness({content:'offline'});
  await h.contentReady;
  assert.equal(h.run('practiceAccess.enabled'), false);
  h.setMode('current');
  await h.run('checkPracticeContent()');
  assert.equal(h.run('practiceAccess.contentVersion'), 'current');
  assert.equal(h.run('practiceAccess.enabled'), true);
});

test('a late metadata response never starts recording a standalone tutor or prior completed work', async () => {
  const helper = source.slice(source.indexOf('  async function enableRecorder('), source.indexOf('  let recorderReady ='));
  for (const oldWork of [{busy:true}, {remote:{session_id:'standalone'}}, {snapshot:{completed:[{}]}}]) {
    const access = {enabled:true};
    const scope = {access, recorder:null, busy:false, remote:null, snapshot:{completed:[]}, ...oldWork};
    await vm.runInNewContext(helper + '\nenableRecorder(access)', scope);
    assert.equal(access.enabled, false);
    assert.match(access.reason, /刷新/);
  }
  const access = {enabled:true};
  const result = await vm.runInNewContext(helper + '\nenableRecorder(access)',
    {access,recorder:'already-recording',busy:true,remote:{},snapshot:{completed:[{}]}});
  assert.equal(result, 'already-recording');
  assert.equal(access.enabled, true);
});

test('mode links retain preview for dynamic and SVG anchors without changing external links', () => {
  assert.equal(modeHref('/1/q02/?knowledge=next&learning=1#step-2', {preview:true}), '/1/q02/?preview=1#step-2');
  assert.equal(modeHref('/1/q02/?preview=1&x=2', {preview:false}), '/1/q02/?x=2');
  const link = {href:'', getAttribute:() => '/knowledge/n/#item',hasAttribute:() => false,
    setAttribute(name, value) {this.href = value;}};
  preserveModeLink(link, 'https://site/1/q01/?preview=1');
  assert.equal(link.href, '/knowledge/n/?preview=1#item');
  preserveModeLink({...link,getAttribute:() => '/1/q01/?preview=1',setAttribute(_name, value) {
    assert.equal(value, '/1/q01/?preview=1');
  }}, 'https://site/knowledge/');
  preserveModeLink({...link,getAttribute:() => 'https://other.test/knowledge/',setAttribute() {throw Error('external');}}, 'https://site/?preview=1');
});

test('preview navigation stays unrecorded before enhancements load or when their import fails', () => {
  const listeners = new Map();
  const link = href => ({href, getAttribute() {return this.href;},hasAttribute:() => false,
    setAttribute(_name,value) {this.href = value;}});
  const topic = link('../'), detail = link('/knowledge/amgm-formula/'), external = link('https://other.test/');
  const guard = source.slice(source.indexOf('  // Keep preview navigation safe'),
    source.indexOf("  import(new URL('./learning-mode.mjs"));
  vm.runInNewContext(guard, {URL,practiceKnowledgePreview:true,location:{href:'https://site/1/q01/?preview=1'},
    document:{querySelectorAll:() => [topic,external],addEventListener:(type,fn) => listeners.set(type,fn)}});
  assert.equal(topic.href, '/1/?preview=1');
  assert.equal(external.href, 'https://other.test/');
  for (const event of ['click','auxclick','contextmenu']) listeners.get(event)({target:{closest:() => detail}});
  assert.equal(detail.href, '/knowledge/amgm-formula/?preview=1');
});

test('confirmed completed fields come from server passed steps without inventing a choice', () => {
  const from = source.indexOf('  const confirmedProgress =');
  const helper = source.slice(from, source.indexOf('  const restorePractice', from));
  const scope = {lesson:{routes:{main:[
    {id:'choose',interaction:{type:'choice',field:'rule'}},
    {id:'fill',interaction:{type:'structure',field:'terms'}},
    {id:'later',interaction:{type:'choice',field:'later'}}
  ]}}};
  vm.createContext(scope);
  vm.runInContext('let confirmedOnServer = {}, passedFieldsOnServer = [];\n' + helper, scope);
  vm.runInContext("confirmedProgress({route_id:'main',confirmed_choices:{},steps:[{step_id:'choose',passed:true},{step_id:'fill',passed:true},{step_id:'later',passed:false}]})", scope);
  assert.deepEqual(Array.from(vm.runInContext('passedFieldsOnServer', scope)), ['rule']);
  assert.deepEqual(Object.keys(vm.runInContext('confirmedOnServer', scope)), []);
});

test('formal hints use server progress only with an authenticated enabled recorder', () => {
  const from = source.indexOf('  const useServerProgress =');
  const helper = source.slice(from, source.indexOf('\n', from));
  const scope = {practiceAccess:{enabled:true}, recorder:null, window:{SiteAuth:{user:null}}};
  vm.createContext(scope);
  vm.runInContext(helper, scope);
  assert.equal(vm.runInContext('useServerProgress()', scope), false);
  scope.recorder = {};
  assert.equal(vm.runInContext('useServerProgress()', scope), false, 'anonymous recorder has no confirmed history');
  scope.window.SiteAuth.user = {id:'student'};
  assert.equal(vm.runInContext('useServerProgress()', scope), true);
  scope.practiceAccess.enabled = false;
  assert.equal(vm.runInContext('useServerProgress()', scope), false, 'version check failure leaves local hints usable');
  scope.practiceAccess.enabled = true;
  scope.window.SiteAuth.user = null;
  assert.equal(vm.runInContext('useServerProgress()', scope), false, 'logout cannot keep server mode');
  assert.match(source, /learning: !practiceKnowledgePreview,\s+useServerProgress,/);
});
