import test from 'node:test';
import assert from 'node:assert/strict';
import {LearningMark, emptyMark, presentation} from '../site/assets/learning/mark-state.js';
const tick = () => new Promise(resolve => setImmediate(resolve));
const practiced = status => ({practiced:true, learning_status:status || 'unmarked'});
const wait = () => { let resolve; const promise = new Promise(r => resolve=r); return {promise, resolve}; };

function setup() {
  const calls = [], records = new Map(); let fail = false;
  const model = new LearningMark(async (kind, status, user) => {
    calls.push({kind, status, user});
    if (fail) throw new Error('offline');
    const old = records.get(user) || emptyMark();
    const value = kind === 'complete' ? {...old, practiced:true} : kind === 'status' ? practiced(status) : old;
    records.set(user, value); return value;
  }, () => {});
  return {model, calls, records, offline(value) { fail=value; }};
}

test('guest completion is held on this page, login saves once, repeat completion preserves self-evaluation', async () => {
  const {model, calls} = setup();
  model.complete(); model.complete();
  assert.equal(calls.length,0);
  await model.setUser('alice');
  assert.equal(calls.filter(c=>c.kind==='complete').length,1);
  assert.equal(presentation(model.mark).label,'待自评');
  await model.choose('mastered'); model.complete();
  assert.equal(model.mark.learning_status,'mastered');
  await model.choose('needs_review'); assert.equal(presentation(model.mark).tone,'review');
  await model.choose('unmarked'); assert.equal(presentation(model.mark).tone,'pending');
});

test('failed completion remains pending and retries without creating a new operation', async () => {
  const {model, offline} = setup(); await model.setUser('alice');
  offline(true); model.complete(); await tick();
  assert.equal(model.phase,'error'); assert.equal(model.mark.practiced,false);
  const pending=model.pending; await model.retry(); assert.equal(model.pending,pending);
  offline(false); await model.retry(); assert.equal(model.mark.practiced,true); assert.equal(model.pending,null);
});

test('failed self-evaluation is not shown as saved and can be retried', async () => {
  const {model,offline}=setup(); model.complete(); await model.setUser('alice');
  offline(true); await model.choose('mastered');
  assert.equal(model.mark.learning_status,'unmarked');
  offline(false); await model.retry(); assert.equal(model.mark.learning_status,'mastered');
});

test('completion while account read is pending is saved after the read', async () => {
  const read=wait(), calls=[];
  const model=new LearningMark(async kind => { calls.push(kind); return kind==='read' ? read.promise : practiced(); },()=>{});
  const loading=model.setUser('alice'); model.complete(); read.resolve(emptyMark()); await loading;
  assert.deepEqual(calls,['read','complete']); assert.equal(model.mark.practiced,true);
});

test('logout clears pending work and late responses cannot populate a different account', async () => {
  const saving=wait(); const calls=[];
  const model=new LearningMark(async (kind,status,user) => {calls.push({kind,user}); return kind==='complete' ? saving.promise : emptyMark();},()=>{});
  await model.setUser('alice'); model.complete();
  await model.setUser(null,'logout'); await model.setUser('bob'); saving.resolve(practiced('mastered')); await tick();
  assert.equal(model.mark.practiced,false); assert.equal(model.completedHere,false); assert.equal(model.pending,null);
  assert.equal(calls.filter(c=>c.kind==='complete'&&c.user==='bob').length,0);
});

test('expired account can retry for itself but cannot transfer its pending work to another account', async () => {
  const {model,offline,calls}=setup(); await model.setUser('alice'); offline(true); model.complete(); await tick();
  await model.setUser(null,'refresh'); offline(false); await model.setUser('alice');
  assert.equal(model.mark.practiced,true);
  await model.setUser(null,'refresh'); await model.setUser('bob');
  assert.equal(model.mark.practiced,false); assert.equal(model.completedHere,false);
  assert.equal(calls.filter(c=>c.user==='bob'&&c.kind==='complete').length,0);
});

test('saved records survive a new page without restoring any exercise steps',async()=>{
  const {model,records}=setup(); records.set('alice',practiced('needs_review')); await model.setUser('alice');
  assert.equal(model.completedHere,false); assert.equal(model.mark.learning_status,'needs_review');
  assert.deepEqual(Object.keys(model.mark).sort(),['learning_status','practiced']);
});
