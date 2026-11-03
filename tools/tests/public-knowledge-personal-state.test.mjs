import test from 'node:test';
import assert from 'node:assert/strict';
import {createPersonalState} from '../../site/assets/knowledge-next/personal-state.mjs';
import {isPreview} from '../../site/assets/practice/learning-mode.mjs';

const node = (node_id, kind = 'skill', status = 'mastered') => ({node_id, kind, status});
const result = nodes => ({content_version:'v1', nodes});
const deferred = () => { let resolve, reject; const promise = new Promise((yes,no) => { resolve=yes; reject=no; }); return {promise,resolve,reject}; };
function fixture(request, extra = {}) {
  const values = new Map();
  return createPersonalState({request,storage:{getItem:key => values.get(key),setItem:(key,value) => values.set(key,value)},...extra});
}

test('all consumers share one authenticated node request and retain only four ability kinds', async () => {
  let calls = 0;
  const reply = deferred();
  const store = fixture(() => { calls++; return reply.promise; });
  const requests = [store.setUser({id:'one'}), store.load(), store.load()];
  reply.resolve(result(['knowledge','skill','method','problem_type','chapter','judgment_rule'].map(kind => node(kind,kind))));
  await Promise.all(requests);
  assert.equal(calls,1);
  assert.deepEqual([...store.snapshot().nodes.keys()], ['knowledge','skill','method','problem_type']);
  await store.load(); assert.equal(calls,1);
});

test('preview and signed-out pages make no personal or version requests', async () => {
  for (const search of ['?preview=1','?knowledge=next','?preview=1&knowledge=next&learning=1']) {
    let calls = 0;
    const store = fixture(() => calls++, {preview:isPreview(search),loadVersion:async () => calls++});
    await store.setUser({id:'one'}); await store.refresh();
    assert.equal(calls,0); assert.equal(store.snapshot().phase,'preview');
  }
  const store = fixture(() => { throw Error('anonymous fetch'); });
  await store.load(); assert.equal(store.snapshot().phase,'anonymous');
});

test('logout and account switch abort requests and discard responses even if fetch ignores abort', async () => {
  const replies = new Map(), signals = [];
  const store = fixture((path, {user,signal}) => { const reply=deferred(); replies.set(user,reply); signals.push(signal); return reply.promise; });
  const old = store.setUser({id:'one'});
  const next = store.setUser({id:'two'});
  assert.equal(signals[0].aborted,true);
  assert.equal(store.snapshot().nodes.size,0);
  replies.get('two').resolve(result([node('new')])) ; await next;
  replies.get('one').resolve(result([node('old')])); await old;
  assert.deepEqual([...store.snapshot().nodes.keys()],['new']);
  await store.setUser(null);
  assert.equal(store.snapshot().nodes.size,0); assert.equal(store.snapshot().contentVersion,null);
});

test('visibility preference is scoped per account and disabled accounts do not fetch', async () => {
  const owners=[];
  const store = fixture(async (path,{user}) => { owners.push(user); return result([node(user)]); });
  await store.setUser({id:'one'}); await store.setEnabled(false);
  assert.equal(store.snapshot().nodes.size,0);
  await store.setUser({id:'two'}); assert.equal(store.snapshot().enabled,true);
  await store.setUser({id:'one'}); assert.equal(store.snapshot().phase,'disabled');
  assert.deepEqual(owners,['one','two']);
  await store.setEnabled(true); assert.deepEqual(owners,['one','two','one']);
});

test('failures do not invent unassessed states; retry fetches anew', async () => {
  let fails=true;
  const store = fixture(async () => { if(fails)throw Error('offline'); return result([node('tested')]); });
  await store.setUser({id:'one'});
  assert.equal(store.snapshot().phase,'error'); assert.equal(store.snapshot().nodes.size,0);
  fails=false; await store.refresh(); assert.equal(store.snapshot().phase,'ready');
});

test('directory consumers coalesce scopes into one batch, deduplicate and cache results', async () => {
  const batches=[];
  const store = fixture(async path => {
    if(path==='/nodes')return result([node('tested')]);
    const scopes=new URL(path,'https://test').searchParams.getAll('scope'); batches.push(scopes);
    return {content_version:'v1',progress:scopes.map(scope => ({scope}))};
  });
  await store.setUser({id:'one'});
  const [a,b]=await Promise.all([store.getProgress(['chapter','section']),store.getProgress(['section','book'])]);
  assert.deepEqual(batches,[['chapter','section','book']]);
  assert.deepEqual(a,[{scope:'chapter'},{scope:'section'}]);
  assert.deepEqual(b,[{scope:'section'},{scope:'book'}]);
  await store.getProgress(['chapter']); assert.equal(batches.length,1);
});

test('directory errors remain errors until retry and stale in-flight summaries cannot cross accounts', async () => {
  let fail=true;
  const waiting=deferred();
  const store=fixture(async (path,{user}) => {
    if(path==='/nodes') return result([node(user)]);
    if(fail)throw Error('offline');
    return waiting.promise;
  });
  await store.setUser({id:'one'});
  assert.deepEqual(await store.getProgress(['book']),[null]);
  assert.equal(store.snapshot().progress.has('book'),false);
  assert.match(store.snapshot().progressErrors.get('book').message,/offline/);
  fail=false;
  const old=store.getProgress(['book'],{retry:true}); await Promise.resolve();
  await store.setUser({id:'two'});
  waiting.resolve({content_version:'v1',progress:[{scope:'book',label:'old'}]}); await old;
  assert.equal(store.snapshot().progress.size,0);
});


test('old static pages read live records without a release stamp, including across publication', async () => {
  const store = fixture(async path => path === '/nodes'
    ? {...result([node('skill')]), content_version:'new-release'}
    : {content_version:'even-newer-release', progress:[{scope:'chapter'}]},
  {loadVersion:() => {throw Error('Static release must not gate live records');}});
  await store.setUser({id:'one'});
  assert.equal(store.snapshot().phase, 'ready');
  assert.equal(store.snapshot().nodes.get('skill').status, 'mastered');
  assert.deepEqual(await store.getProgress(['chapter']), [{scope:'chapter'}]);
  assert.equal(store.snapshot().progressErrors.size, 0);
});
