import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {createRequire} from 'node:module';
import {createState, currentDecision, submitAnswer, switchRoute, replayState, extendStreamBundle, graphState} from '../../site/assets/graph-walk/walk-state.mjs';
import {replayAnswer, buildStreamReplay} from '../../site/assets/graph-walk/walk-replay.mjs';
import {methodAnswer, methodCardsHTML} from '../../site/assets/graph-walk/method-cards.mjs';
import {routeRecordActions} from '../../site/assets/graph-walk/practice-route.mjs';

const read = async file => JSON.parse(await fs.readFile(new URL(`../../${file}`, import.meta.url), 'utf8'));
const graph = await read('site/knowledge/graph.json');
const katex = createRequire(import.meta.url)('../../site/assets/practice/vendor/katex-0.18.9/katex.min.js');
for (const q of ['06','07','10']) {
  const bundle = await read(`site/data/graph-walk/function-concepts-range-q${q}.json`);
  const evidence = await read(`site/data/graph-walk/function-concepts-range-q${q}.evidence.json`);
  test(`Q${q}: condition gate, all methods, replay and restored prefixes`, () => {
    assert.deepEqual(Object.keys(bundle.routes).sort(), ['equation-real-root-range','fraction-split-range']);
    const decision = bundle.intro.find(s => s.id === 'D3');
    assert.equal(decision.interaction.type, 'method_cards');
    const initial = methodCardsHTML(decision, null);
    assert.ok(initial.includes('data-card-method="fraction"'));
    assert.ok(initial.includes('data-card-method="equation"'));
    assert.deepEqual(decision.interaction.checks, []);
    assert.ok(!initial.includes('分离常数后，余项'));
    const wrong = {checks:[],method:'not-a-method',confirmed:0};
    for (const route of Object.keys(bundle.routes)) {
      let state = createState(bundle), actions = [];
      while (currentDecision(bundle,state)) {
        const step = currentDecision(bundle,state);
        if (step.id === 'D3') {
          const rejected = submitAnswer(bundle,state,{decision:step.id,answer:wrong});
          assert.equal(rejected.lastFeedback.status,'wrong');
          assert.equal(currentDecision(bundle,rejected).id,'D3');
        }
        const action = {decision:step.id,answer:replayAnswer(step,route)};
        actions.push(action);state=submitAnswer(bundle,state,action);
        assert.equal(state.lastFeedback.status,'passed');
        const restored=replayState(bundle,{schemaVersion:2,bundleVersion:bundle.bundleVersion,problemId:bundle.problemId,status:'partial',routes:[route],actions});
        assert.equal(currentDecision(bundle,restored)?.id,currentDecision(bundle,state)?.id);
      }
      assert.equal(state.done,true);
      assert.equal(graphState(bundle,state).nodes['rule-function-range-method'],'confirmed');
      const stream=extendStreamBundle(bundle,evidence.stream,'/root/goals/0',graph);
      const replay=buildStreamReplay(stream,{actions:actions.slice(0,2),replayRoute:route});
      assert.equal(replayState(stream,replay).done,true);
      const other=Object.keys(bundle.routes).find(id=>id!==route);
      if (other) {
        const switched=switchRoute(bundle,state,other);
        assert.equal(switched.run.route,other);
        assert.equal(switched.done,false);
        assert.equal(switchRoute(bundle,switched,route).done,true);
      }
    }
  });
  test(`Q${q}: formulas render and current results remain hidden`, () => {
    const decision=bundle.intro.find(s=>s.id==='D3');
    const mathTexts=[...decision.interaction.facts,...decision.interaction.checks.flatMap(c=>[c.resolved,c.feedback])];
    for (const step of [...bundle.intro,...Object.values(bundle.routes).flatMap(r=>r.steps)]) {
      if(step.stem_board?.layout==='derivation') assert.equal(step.stem_board.items[1].math,null);
      for(const board of [step.stem_board,step.completion_board]) for(const item of board?.items||[]) {
        if(item.math) assert.doesNotThrow(()=>katex.renderToString(item.math,{throwOnError:true,strict:'ignore'}));
      }
      mathTexts.push(step.question, ...(step.interaction.options||[]).map(o=>o.label));
    }
    for(const text of mathTexts) {
      assert.equal((String(text).match(/\$/g) || []).length % 2, 0, `unclosed formula: ${text}`);
      for(const [,formula] of String(text).matchAll(/\$([^$]+)\$/g)) {
        assert.doesNotThrow(()=>katex.renderToString(formula,{throwOnError:true,strict:'ignore'}));
      }
    }
  });
}

test('a non-real original domain blocks M4 in both the picker and grading', async () => {
  const bundle = await read('site/data/graph-walk/function-concepts-range-q17.json');
  let state = createState(bundle);
  while (currentDecision(bundle,state).id !== 'D3') {
    const step=currentDecision(bundle,state);
    state=submitAnswer(bundle,state,{decision:step.id,answer:replayAnswer(step)});
  }
  const decision=currentDecision(bundle,state);
  const html=methodCardsHTML(decision,null);
  assert.match(html,/data-card-method="equation"[^>]*disabled/);
  assert.ok(html.includes('域内实根筛选'));
  const blocked=submitAnswer(bundle,state,{decision:'D3',answer:methodAnswer(decision,'equation')});
  assert.equal(blocked.lastFeedback.status,'uncovered');
  assert.equal(currentDecision(bundle,blocked).id,'D3');
});

test('Q06 M5 includes both hook branches, exact zero recovery and visible graphs', async () => {
  const bundle=await read('site/data/graph-walk/function-concepts-range-q06.json');
  const route=bundle.routes['fraction-split-range'];
  const hooks=route.steps.filter(s=>s.title.startsWith('对勾函数：'));
  assert.equal(hooks.length,2);
  assert.equal(new Set(hooks.map(s=>s.title)).size,2);
  for(const step of hooks) {
    assert.ok(step.question.includes('h(x)='));
    assert.ok(!step.question.includes('f(x)='));
    assert.equal(step.graph.kind,'reciprocal_sum');
    assert.equal(step.stem_board.items[1].math,null);
    assert.ok(step.graph.params.points.length);
  }
  const titles=route.steps.map(s=>s.title);
  assert.ok(titles.indexOf('检查同除的条件') < titles.indexOf('分子分母同除'));
  assert.ok(titles.indexOf('还原非零分支的值域') < titles.indexOf('合并原函数值域'));
  assert.equal(route.completion.answer.set.expression,'Interval(1, 7/3)');
});

test('topic recording carries confirmed prerequisites into the selected route, without duplicating current answer',()=>{
  const bundle={routes:{fraction:{},equation:{}}};
  const prefix=[{decision:'D1',answer:'read'},{decision:'D3',answer:{checks:['constant'],method:'equation'}}];
  const plan=routeRecordActions(bundle,{route:'equation',practice_answers:prefix},prefix[1],'fraction');
  assert.equal(plan.route,'equation');assert.deepEqual(plan.actions,prefix);
  assert.deepEqual(routeRecordActions(bundle,{route:'equation',practice_answers:prefix},null,'equation').actions,[]);
  assert.deepEqual(routeRecordActions(bundle,{route:'equation',practice_answers:prefix},null,'fraction').actions,prefix);
});
