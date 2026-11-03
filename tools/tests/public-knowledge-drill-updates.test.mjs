import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';
import {escapeHtml} from '../../site/assets/knowledge-next/resource-links.mjs';
import {updateLocalDrillProgress} from '../../site/assets/knowledge-next/personal-overlay.mjs';

const drillSource = (await fs.readFile(new URL('../../site/assets/knowledge-next/learning-drill.mjs', import.meta.url), 'utf8'))
  .replace(/^import .*;\n/gm, '').replace('export async function openDrill', 'async function openDrill');
const detailSource = (await fs.readFile(new URL('../../site/assets/knowledge-next/learning.mjs', import.meta.url), 'utf8'))
  .replace(/^import .*;\n/gm, '');
const tick = () => new Promise(resolve => setImmediate(resolve));

class Element {
  constructor() {
    this.nodes = new Map(); this.style = {}; this.innerHTML = ''; this.textContent = '';
    this.classList = {add() {}, toggle() {}};
  }
  querySelector(selector) {
    if (!this.nodes.has(selector)) this.nodes.set(selector, new Element());
    return this.nodes.get(selector);
  }
  querySelectorAll() { return []; }
  replaceChildren() { this.innerHTML = ''; }
  setAttribute() {}
  addEventListener() {}
  append() {}
  after() {}
}
function eventWindow() {
  const listeners = new Map(), events = [];
  return {
    events, SiteAuth:{user:{id:'student'}, ready:Promise.resolve()},
    addEventListener(type, callback) { (listeners.get(type) || listeners.set(type, []).get(type)).push(callback); },
    dispatchEvent(event) {
      events.push(event);
      for (const callback of listeners.get(event.type) || []) callback(event);
    }
  };
}
class CustomEvent {
  constructor(type, options = {}) { this.type = type; this.detail = options.detail; }
}
function round(answered, status = answered === 5 ? 'completed' : 'in_progress', id = 'round') {
  return {id, node_id:'skill', status, items:Array.from({length:5}, (_, index) => ({
    position:index + 1, statement_md:`第 ${index + 1} 题`, question_type:'single',
    options:[{value:'a',label:'A'}], answered_at:index < answered ? 'now' : null,
    is_correct:true, selected:index < answered ? ['a'] : [], answer:['a'], feedback:[]
  }))};
}
function drillFixture() {
  const window = eventWindow(), writes = [], dialog = new Element();
  const context = vm.createContext({
    window, CustomEvent, AbortController, h:escapeHtml,
    crypto:{randomUUID:() => 'new-round'},
    learningApi:async () => { if (context.error) throw context.error; return context.next; },
    localStorage:{setItem:(...entry) => writes.push(entry)},
    fixtureDialog:dialog
  });
  vm.runInContext(drillSource, context);
  vm.runInContext("dialog = fixtureDialog; owner = 'student'; source = {node:'skill', label:'技能'};", context);
  async function save(next, position, error = null) {
    context.next = next; context.position = position; context.error = error;
    return vm.runInContext("pending = {path:position == null ? '/drills' : '/drills/round/answers/' + position, body:{}, position}; perform();", context);
  }
  return {window, writes, dialog, context, save};
}

test('starting a drill sends only the selected node pool version', async () => {
  const fixture = drillFixture(), requests = [];
  fixture.context.learningApi = async (path, options) => {requests.push({path, body:options.body});return round(0);};
  vm.runInContext("source.drillVersion = 'pool-version'; source.contentVersion = 'unrelated-release';", fixture.context);
  await vm.runInContext("start('previous-round')", fixture.context);
  assert.deepEqual(JSON.parse(JSON.stringify(requests)), [{path:'/drills', body:{
    id:'new-round', node_id:'skill', drill_version:'pool-version', previous_attempt_id:'previous-round'
  }}]);
});

test('opening and the first four answers update only local progress; completion broadcasts once', async () => {
  const fixture = drillFixture(), host = new Element();
  fixture.window.addEventListener('learning-drill-progress', event => updateLocalDrillProgress(host, event.detail, 'student', 'skill'));
  for (let count = 0; count < 5; count++) {
    await fixture.save(round(count), count || undefined);
    assert.equal(fixture.writes.length, 0);
    assert.equal(fixture.window.events.filter(event => event.type === 'learning-nodes-change').length, 0);
    assert.equal(host.textContent, ` · 本轮已答 ${count} / 5`);
    assert.equal(fixture.dialog.querySelector('.kd-bar span').style.width, `${count * 20}%`);
  }
  await fixture.save(round(5), 5);
  assert.equal(host.textContent, '');
  assert.equal(fixture.window.events.filter(event => event.type === 'learning-nodes-change').length, 1);
  assert.equal(fixture.writes.length, 1);
  assert.equal(fixture.writes[0][0], 'sss-learning-change');
  // A repeated confirmed response for the same completion does not refresh all tabs twice.
  await fixture.save(round(5), 5);
  assert.equal(fixture.writes.length, 1);
});

test('the final answer retries without premature broadcast, and a later completed round notifies again', async () => {
  const fixture = drillFixture();
  await fixture.save(round(4), 4);
  await fixture.save(round(5), 5, Object.assign(Error('offline'), {retryable:true}));
  assert.equal(fixture.writes.length, 0);
  assert.equal(fixture.dialog.querySelector('[data-retry]').hidden, false);
  fixture.context.error = null;
  await vm.runInContext('perform()', fixture.context);
  assert.equal(fixture.writes.length, 1);
  await fixture.save(round(0, 'in_progress', 'second'));
  assert.equal(fixture.writes.length, 1);
  await fixture.save(round(5, 'completed', 'second'), 5);
  assert.equal(fixture.writes.length, 2);
  assert.notEqual(fixture.writes[0][1], fixture.writes[1][1]);
});

test('closed rounds and stale account responses never publish assessment changes', async () => {
  const fixture = drillFixture();
  await fixture.save(round(3, 'closed'), 3);
  assert.equal(fixture.writes.length, 0);
  let resolve;
  fixture.context.learningApi = () => new Promise(done => { resolve = done; });
  const pending = fixture.save(round(5), 5);
  vm.runInContext("epoch++; owner = 'other-student';", fixture.context);
  resolve(round(5)); await pending;
  assert.equal(fixture.writes.length, 0);
  assert.equal(fixture.window.events.length, 1); // Only the earlier local closed-round notice.
});

test('detail progress events update the current node locally without reloading evidence or assessments', async () => {
  const window = eventWindow(), controls = new Element(), hero = new Element(), created = [];
  const node = {id:'skill',kind:'skill',label:'技能',entryIds:[]};
  const current = {userId:'student',enabled:true,phase:'ready',revision:1,contentVersion:'v',
    nodes:new Map([['skill',{status:'mastered',in_progress:false,eligible:true,item_count:5}]])};
  let refreshes = 0, evidenceRequests = 0;
  const store = {snapshot:() => current, subscribe(callback) { callback(current); }, setUser() {}, refresh() { refreshes++; }};
  const document = {
    querySelector:selector => selector === '#node-page-config' ? {textContent:JSON.stringify(node)}
      : selector === 'main .hero' ? hero : selector === '[data-personal-controls]' ? controls : null,
    createElement:() => { const element = new Element(); created.push(element); return element; }
  };
  vm.runInNewContext(detailSource, {
    window, document, location:new URL('https://test/knowledge/skill/'), AbortController,
    personalState:() => store, bindPersonalOverlay() {}, updateLocalDrillProgress,
    isPreview:() => false, bindModeLinks() {}, h:escapeHtml,
    ABILITY_KINDS:['skill'], STATUS_LABELS:{mastered:'已掌握'},
    progressScope:() => null,
    learningApi:async () => { evidenceRequests++; return {evidence:[],drills:[]}; }
  });
  await tick();
  const mine = created.find(element => element.className === 'kx-mine');
  const notice = {userId:'student',nodeId:'skill',status:'in_progress',answered:2,total:5};
  window.dispatchEvent(new CustomEvent('learning-drill-progress', {detail:notice}));
  assert.equal(mine.querySelector('[data-drill-progress]').textContent, ' · 本轮已答 2 / 5');
  assert.equal(refreshes, 0); assert.equal(evidenceRequests, 1);
  assert.match(mine.innerHTML, /已掌握/);
  assert.match(mine.innerHTML, /做 5 道题检测/);
  assert.equal(created.find(element => element.className === 'kx-records').hidden, true, '没有记录时不显示记录区');
  for (const other of [{userId:'other'}, {nodeId:'other'}]) {
    window.dispatchEvent(new CustomEvent('learning-drill-progress', {detail:{...notice,...other,answered:4}}));
  }
  assert.equal(mine.querySelector('[data-drill-progress]').textContent, ' · 本轮已答 2 / 5');
  window.dispatchEvent(new CustomEvent('learning-nodes-change'));
  assert.equal(refreshes, 1);
});
