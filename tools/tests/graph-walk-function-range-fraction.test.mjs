import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {createRequire} from 'node:module';
import {compileCourse} from '../build-graph-walk-topic.mjs';
import {loadSources, repoRoot} from '../lib/public-knowledge-sources.mjs';
import {buildStreamReplay} from '../../site/assets/graph-walk/walk-replay.mjs';
import {createState, currentDecision, submitAnswer, replayState, extendStreamBundle} from '../../site/assets/graph-walk/walk-state.mjs';
const read = async path => JSON.parse(await fs.readFile(`${repoRoot}/${path}`, 'utf8'));
const graph = await read('site/knowledge/graph.json');
const {nodes} = await loadSources();
const katex = createRequire(import.meta.url)('../../site/assets/practice/vendor/katex-0.18.9/katex.min.js');
for (const [q, answer] of [['07','Interval.Ropen(2/3, 2)'],['09','Union(Interval.open(-oo, 1), Interval.open(1, oo))'],['10','Interval.Ropen(-1/3, 1)'],['17','Union(Interval.open(-oo, -3), Interval.open(-3, oo))']]) {
  const source = await read(`site/data/graph-walk/function-concepts-range-q${q}.source.json`);
  const evidence = await read(source.evidence);
  const {bundle, replay} = compileCourse(source, evidence, graph, nodes);
  test(`Q${q} retains the domain, borrows M3, and transports reciprocal ranges without leaking answers`, () => {
    const route = bundle.routes['fraction-split-range'];
    assert.equal(route.method, 'method-fraction-split-range');
    assert.equal(route.completion.answer.set.expression, answer);
    assert.equal(bundle.intro[2].id, 'D3-domain');
    const titles = route.steps.map(s => s.title);
    assert.ok(titles.indexOf('求分母的范围') < titles.indexOf('分段取倒数'));
    assert.ok(titles.indexOf('分段取倒数') < titles.indexOf('还原原函数值域'));
    for (const step of [...bundle.intro, ...route.steps]) {
      if (step.stem_board?.layout === 'derivation') assert.equal(step.stem_board.items[1].math, null);
      for (const board of [step.stem_board, step.completion_board]) {
        for (const item of board?.items || []) {
          if (item.math) assert.doesNotThrow(() => katex.renderToString(item.math, {throwOnError: true, strict: 'ignore'}));
        }
      }
      for (const text of [step.question, ...((step.interaction?.options || []).map(o => o.label))]) {
        for (const [, math] of String(text).matchAll(/\$([^$]+)\$/g)) assert.doesNotThrow(() => katex.renderToString(math, {throwOnError:true,strict:'ignore'}));
      }
    }
    const final = route.steps.find(s => s.title === '还原原函数值域');
    assert.equal(final.completion_graph.kind, 'number_line');
  });
  test(`Q${q} self practice, wrong choices, restored prefixes and photo replay all complete`, () => {
    let state = createState(bundle);
    for (const [index, action] of replay.actions.entries()) {
      const step = currentDecision(bundle, state);
      assert.equal(step.id, action.decision);
      if (step.interaction.type === 'choice' && step.expected_answer.one_of) {
        const wrong = step.interaction.options.find(o => !step.expected_answer.one_of.includes(o.value));
        assert.ok(wrong);
        const rejected = submitAnswer(bundle, state, {decision:step.id, answer:wrong.value});
        assert.equal(rejected.lastFeedback.status, 'wrong');
        assert.equal(currentDecision(bundle, rejected).id, step.id);
      }
      state = submitAnswer(bundle, state, action);
      assert.equal(state.lastFeedback.status, 'passed');
      const restored = replayState(bundle, {...replay,status:'partial',actions:replay.actions.slice(0,index+1)});
      assert.equal(currentDecision(bundle,restored)?.id,currentDecision(bundle,state)?.id);
    }
    assert.equal(state.done,true);
    const streamed = extendStreamBundle(bundle,evidence.stream,source.targetRefs[0],graph);
    assert.equal(replayState(streamed,buildStreamReplay(streamed,{actions:replay.actions.slice(0,2)})).done,true);
    if (q === '09') {
      const domain = compileCourse({...source,targetRefs:['/root/goals/0'],statement:undefined},evidence,graph,nodes);
      assert.equal(replayState(domain.bundle,domain.replay).done,true);
      assert.equal(domain.bundle.routes['domain-intersection'].completion.answer.set.expression,'Union(Interval.open(-oo, 2), Interval.open(2, oo))');
    }
  });
}
