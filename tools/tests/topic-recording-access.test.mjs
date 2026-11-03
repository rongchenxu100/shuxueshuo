import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {routeRecordActions} from '../../site/assets/graph-walk/practice-route.mjs';

const source = fs.readFileSync(new URL('../../site/assets/graph-walk/topic-page.mjs', import.meta.url), 'utf8')
  .replace(/^import .*;\n/gm, '').replace("await import('../learning/learning-marks.js?v=20261026-domain-powers')", 'Promise.resolve()');
const tick = () => new Promise(resolve => setImmediate(resolve));
function harness({preview = false, fail = false} = {}) {
  const config = {problemId:'test',bundleUrl:'/bundle',replayUrl:'/replay',preview};
  const bundle = {problemId:'test',intro:[],routes:{main:{id:'main',steps:[]}}};
  const elements = new Map(), created = [], calls = [], answers = [], listeners = {};
  let mounted, release, failing = fail;
  const element = () => ({hidden:true,dataset:{},append(...children) {this.children = children;},setAttribute() {}});
  const get = selector => { if (!elements.has(selector)) elements.set(selector, element()); return elements.get(selector); };
  get('#graph-walk-page').textContent = JSON.stringify(config);
  const scope = {AbortSignal, document:{querySelector:get, createElement:() => {const el=element();created.push(el);return el;}},
    window:{SiteAuth:{user:{id:'student'}},addEventListener:(name, listener) => {listeners[name] = listener;}},
    location:{search:''}, isPreview:() => false, routeRecordActions,
    fetch:async url => {calls.push(url);return {ok:true,json:async () => url === '/bundle' ? bundle : {}};},
    mountWalk:async options => {mounted = options;}, restoreWalkProgress:() => true, disposeWalk() {},
    checkPracticeCompatibility:async () => {
      await new Promise(resolve => {release = resolve;});
      if (failing) throw Error('保存服务暂不可用');
      return {practiceVersion:'v1'};
    },
    createRecorder:() => ({graphAnswer:(...args) => answers.push(args), reset() {}}),
  };
  const ready = vm.runInNewContext(`(async () => {${source}})()`, scope);
  return {ready, calls, answers, elements, created, mount:() => mounted,
    async release() { while (!release) await tick(); const done = release; release = null; done(); },
    setFailure(value) {failing = value;}};
}

test('published static lesson mounts while recording is pending, and buffers answers', async () => {
  const h = harness(); await h.ready;
  assert.ok(h.mount());
  assert.equal(h.calls.includes('/knowledge/teaching/version.json'), false);
  h.mount().onAnswer({decision:'first',answer:'yes'}, {route:'main'});
  assert.equal(h.answers.length, 0);
  await h.release(); await tick();
  assert.deepEqual(h.answers, [['main','first','yes']]);
  assert.equal(h.elements.get('#gw-error')?.hidden ?? true, true);
});

test('recording failure is recoverable without replacing the static exercise', async () => {
  const h = harness({fail:true}); await h.ready; await h.release(); await tick();
  const [notice, message, retry] = h.created;
  assert.ok(h.mount()); assert.equal(notice.hidden, false);
  assert.match(message.textContent, /本地练习可以继续/);
  assert.equal(h.elements.get('#gw-error')?.hidden ?? true, true);
  h.mount().onAnswer({decision:'first',answer:'yes'}, {route:'main'});
  h.mount().onReset(); // Do not replay operations from an abandoned local attempt.
  h.setFailure(false); const retried = retry.onclick(); await h.release(); await retried;
  assert.equal(notice.hidden, true); assert.equal(h.answers.length, 0);
});

test('preview remains independent of recording metadata and APIs', async () => {
  const h = harness({preview:true}); await h.ready;
  assert.ok(h.mount()); assert.deepEqual(h.calls, ['/bundle','/replay']);
});
