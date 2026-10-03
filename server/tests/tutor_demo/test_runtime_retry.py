"""Run the actual runtime request handler with deterministic transport and timers."""

import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize('code', ['session_busy', 'retry_cooldown', 'session_limit', 'daily_limit',
                                 'cancel_login', 'resume_login', 'expired', 'expired_cancel', 'account_changed'])
def test_auth_gate_and_timeout_retry(code):
    runtime = Path(__file__).resolve().parents[3] / 'site/assets/practice/runtime.js'
    script = r'''
const assert = require('node:assert/strict');
const vm = require('node:vm');
const source = require('node:fs').readFileSync(process.argv[1], 'utf8');
const code = process.argv[2];
const timers = new Map();
let timerId = 0, now = 1000, mode = 'timeout';
const posted = [];
let loginCalls = 0, finishLogin;
const scope = {
  Date: {now: () => now}, AbortController,
  setTimeout: (callback, delay) => { timers.set(++timerId, {callback, delay}); return timerId; },
  clearTimeout: id => timers.delete(id),
  busy: false, dialoguePause: null, dialogueTimer: null, generation: 0,
  retryRequest: null, requestController: null,
  state: {active: 0}, snapshot: {attempt_id: 'attempt'},
  remote: {session_id: 'session', revision: 0, user_id: 'student'}, pendingOperations: [],
  practiceAuthReady: Promise.resolve(), window: {SiteAuth: {requireLogin: async options => {
    loginCalls++;
    if (['cancel_login', 'resume_login', 'account_changed'].includes(code)) return new Promise(resolve => { finishLogin = resolve; });
    if (loginCalls > 1 && ['expired', 'expired_cancel'].includes(code)) {
      assert.equal(options.force, true);
      if (code === 'expired_cancel') return null;
    }
    return {id: 'student'};
  }}},
  api: '/api/tutor-demo', lesson: {},
  steps: {querySelectorAll: () => [], setAttribute: () => {}},
  picker: {querySelectorAll: () => []},
  document: {querySelectorAll: () => [], querySelector: () => null},
  messageInput: {value: '为什么？'}, sendButton: {}, retryButton: {}, networkStatus: {},
  pauseIdle() {}, resumeIdle() {}, showProgress() {}, announce() {}, completed: () => false,
  PracticeContext: {reconcile: data => ({view: data, remaining: []})},
  acceptSnapshot(data) { scope.snapshot = data; scope.state = data.state; },
  fetch: async (url, options) => {
    posted.push(JSON.parse(options.body));
    if (mode === 'expired' && posted.length === 1) return {ok: false, status: 401, json: async () => ({detail: '请先登录'})};
    if (mode === 'timeout') return new Promise((resolve, reject) => {
      options.signal.addEventListener('abort', () => {
        const error = new Error('timeout'); error.name = 'AbortError'; reject(error);
      });
    });
    if (mode === 'limited') return {ok: false, json: async () => ({code, detail: code, retry_after: 2})};
    return {ok: true, json: async () => ({session_id: 'session', revision: 1,
      attempt_id: 'attempt', state: {active: 0}, messages: [{text: '回复'}]})};
  },
};
vm.createContext(scope);
vm.runInContext(source.slice(source.indexOf('  function updateBusy()'), source.indexOf('  function conversation(')) +
  source.slice(source.indexOf('  async function request(payload)'), source.indexOf('  function sendEvent(')), scope);
const payload = {event_id: 'original-event', revision: 0, kind: 'text', text: '为什么？',
  pending_operations: [{event_id: 'local-choice', action: {kind: 'method', value: 'direct'}}]};
const runTimer = delay => {
  const entry = [...timers].find(([, timer]) => timer.delay === delay);
  assert.ok(entry, `missing ${delay}ms timer`);
  timers.delete(entry[0]); now += delay; entry[1].callback();
};
(async () => {
  if (['cancel_login', 'resume_login', 'account_changed'].includes(code)) {
    mode = 'success';
    scope.retryRequest = payload; // Preserve the identity of an uncertain earlier request.
    const gated = scope.request(payload);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(posted.length, 0);
    assert.equal(timers.size, 0); // SMS entry never consumes the AI timeout.
    if (code === 'account_changed') scope.generation++; // Logout/switch invalidates pending work.
    finishLogin(code === 'cancel_login' ? null : {id: 'student'});
    await gated;
    if (code === 'resume_login') {
      assert.equal(posted.length, 1);
      assert.deepEqual(posted[0], payload);
      assert.equal(scope.messageInput.value, '');
    } else {
      assert.equal(posted.length, 0);
      assert.equal(scope.messageInput.value, '为什么？');
      if (code === 'cancel_login') {
        assert.equal(scope.retryRequest, payload);
        assert.equal(scope.retryButton.hidden, false);
        assert.equal(scope.busy, false);
      }
    }
    return;
  }
  if (['expired', 'expired_cancel'].includes(code)) {
    mode = 'expired';
    await scope.request(payload);
    assert.equal(loginCalls, 2);
    assert.equal(posted.length, code === 'expired' ? 2 : 1);
    for (const body of posted) assert.deepEqual(body, payload);
    if (code === 'expired_cancel') {
      assert.equal(scope.retryRequest, payload);
      assert.equal(scope.retryButton.hidden, false);
      assert.equal(scope.messageInput.value, '为什么？');
    } else assert.equal(scope.messageInput.value, '');
    assert.equal(scope.busy, false);
    return;
  }
  const waiting = scope.request(payload);
  await new Promise(resolve => setImmediate(resolve)); // Login check precedes the model timeout.
  runTimer(55000);
  await waiting;
  assert.equal(scope.retryRequest, payload);
  assert.equal(scope.retryButton.hidden, false);
  mode = 'limited';
  await scope.request(scope.retryRequest);
  assert.equal(scope.retryButton.hidden, true);
  assert.ok(scope.sendButton.disabled);
  const count = posted.length;
  await scope.request(payload); // Cooldown prevents another network call.
  assert.equal(posted.length, count);
  if (['session_busy', 'retry_cooldown'].includes(code)) {
    assert.equal(scope.retryRequest, payload);
    runTimer(2000);
    assert.equal(scope.retryButton.hidden, false);
    assert.ok(scope.sendButton.disabled); // Cannot create a different event by sending again.
    mode = 'success';
    await scope.request(scope.retryRequest);
    assert.equal(scope.remote.revision, 1);
    assert.equal(scope.retryRequest, null);
    assert.equal(scope.retryButton.hidden, true);
    assert.equal(scope.messageInput.value, '');
    assert.equal(posted.length, 3);
  } else {
    assert.equal(scope.retryRequest, null);
    if (code === 'daily_limit') runTimer(2000);
    assert.equal(scope.retryButton.hidden, true);
  }
  for (const body of posted) assert.deepEqual(body, payload);
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
    subprocess.run(['node', '-e', script, str(runtime), code], check=True, capture_output=True, text=True)
