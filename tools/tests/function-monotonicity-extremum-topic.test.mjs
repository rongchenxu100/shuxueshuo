import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';
import {createRequire} from 'node:module';
import {generateCourse} from '../build-graph-walk-topic.mjs';
import {createState, currentDecision, submitAnswer, replayState, extendStreamBundle} from '../../site/assets/graph-walk/walk-state.mjs';
import {replayAnswer} from '../../site/assets/graph-walk/walk-replay.mjs';

const read = async p => JSON.parse(await fs.readFile(p, 'utf8'));
const katex = createRequire(import.meta.url)('../../site/assets/practice/vendor/katex-0.18.9/katex.min.js');
const scope = vm.createContext({window: {}});
vm.runInContext(await fs.readFile('site/assets/practice/components.js', 'utf8'), scope);
const ui = scope.window.PracticeComponents;
const VERSIONS = {a14: 'v1', a16: 'v3', a07: 'v3', a18: 'v3', b16: 'v3', b11: 'v3', b10: 'v3', b08: 'v3', b14: 'v3'};
const prefix = id => `site/data/graph-walk/function-monotonicity-${id}-${VERSIONS[id] || 'v2'}`;
const renderMath = math => katex.renderToString(math, {throwOnError: true, strict: 'ignore'});

for (const id of ['a16', 'a14', 'a07', 'a18', 'b16', 'b11', 'b10', 'b08', 'b14']) {
  test(`${id}: complete lesson grades, renders and resumes from the shared evidence`, async () => {
    const bundle = await read(prefix(id)+'.json');
    const replay = await read(prefix(id)+'.replay.json');
    assert.equal(replayState(bundle, replay).done, true);
    for (const route of Object.keys(bundle.routes)) {
      let state = createState(bundle), count = 0;
      while (!state.done && count++ < 300) {
        const step = currentDecision(bundle, state);
        assert.ok(step);
        if (step.stem_board) {
          // Choice stems usually hide the result in items[1]; interval merge／inform boards use lines.
          if (step.stem_board.lines) {
            assert.ok(step.stem_board.lines.length);
            assert.equal(step.stem_board.items, undefined);
          } else assert.equal(step.stem_board.items[1].math, null);
        }
        for (const board of [step.stem_board, step.completion_board].filter(Boolean)) {
          for (const item of board.items || []) if (item.math) renderMath(item.math);
          // lines boards carry $…$ / $$…$$ delimiters for PracticeMath; strip before KaTeX.
          for (const line of board.lines || []) {
            for (const match of String(line).matchAll(/\$\$([^$]+)\$\$|\$([^$]+)\$/g)) {
              renderMath(match[1] || match[2]);
            }
          }
          if (board.operation?.math) renderMath(board.operation.math);
        }
        for (const text of [step.question, ...((step.interaction.options || []).map(o => o.label))]) {
          for (const [, math] of String(text).matchAll(/\$([^$]+)\$/g)) renderMath(math);
        }
        for (const graph of [step.graph, step.completion_graph, ...(step.completion_graphs || [])].filter(Boolean)) {
          assert.equal(ui.validateGraph(graph), true, step.id);
          const svg = ui.graph(graph, {uid: 'extremum-test'});
          assert.match(svg, /<svg/);
          assert.doesNotMatch(svg, /NaN|Infinity/);
        }
        // Informational read cards (e.g. inventing g/f names) have no options to grade.
        const wrong = step.interaction.type === 'read' ? null
          : step.interaction.options?.find(o => step.expected_answer?.one_of && !step.expected_answer.one_of.includes(o.value));
        if (wrong) {
          const rejected = submitAnswer(bundle, state, {decision: step.id, answer: wrong.value});
          assert.equal(rejected.lastFeedback.status, 'wrong');
          assert.equal(currentDecision(bundle, rejected).id, step.id);
        }
        state = submitAnswer(bundle, state, {decision: step.id, answer: replayAnswer(step, route)});
        assert.equal(state.lastFeedback.status, 'passed', step.id);
        state = JSON.parse(JSON.stringify(state));
      }
      assert.equal(state.done, true);
    }
    const outputs = await generateCourse({sourcePath: prefix(id)+'.source.json'});
    assert.deepEqual(JSON.parse(outputs.get(prefix(id)+'.json')), bundle);
  });
}

test('direct extrema pictures preserve poles and legal root inputs', async () => {
  const a16 = await read(prefix('a16')+'.json');
  const graphs = Object.values(a16.routes).flatMap(r => r.steps).flatMap(s => [s.graph, s.completion_graph]).filter(Boolean);
  const rational = graphs.find(g => g.params?.segments?.some(s => s.transform === 'rational'));
  assert.ok(rational);
  const pole = structuredClone(rational);
  pole.params.segments[0].interval[0] = -3;
  pole.params.segments[0].interval_closed[0] = true;
  assert.equal(ui.validateGraph(pole), false);
  const a14 = await read(prefix('a14')+'.json');
  const root = Object.values(a14.routes).flatMap(r => r.steps).map(s => s.graph).find(g => g?.params?.segments?.some(s => s.transform === 'root_sum'));
  assert.ok(root);
  const negative = structuredClone(root);
  negative.params.segments[0].interval[1] = 1;
  assert.equal(ui.validateGraph(negative), false);
});

test('A07 conditions and conclusion append incrementally without rewriting published decisions', async () => {
  const evidence = await read(prefix('a07')+'.evidence.json');
  const goal = evidence.lesson.goals[0], graph = await read('site/knowledge/graph.json');
  const snapshot = evidence.stream;
  let bundle = goal.walk.bundle;
  for (let count = 1; count <= snapshot.interactions.length; count++) {
    const interactions = snapshot.interactions.slice(0, count);
    const visible = new Set(interactions.flatMap(row => row.steps.map(step => step.step_id)));
    const partial = {...snapshot, interactions,
      math_steps: snapshot.math_steps.filter(row => visible.has(row.step_id)),
      interaction_states: snapshot.interaction_states.filter(row => visible.has(row.step_id))};
    const published = structuredClone(bundle.routes);
    const next = extendStreamBundle(bundle, partial, goal.target_ref, graph);
    for (const [id, route] of Object.entries(published)) {
      assert.deepEqual(next.routes[id].steps.slice(0, route.steps.length), route.steps);
    }
    bundle = next;
  }
  assert.deepEqual(bundle.routes, extendStreamBundle(goal.walk.bundle, snapshot, goal.target_ref, graph).routes);
});

test('only photo-accepted courses enter the topic, with T1 order unchanged', async () => {
  const topic = await read('site/data/knowledge-next/topics/function-monotonicity.json');
  assert.deepEqual(topic.groups.find(g => g.id === 'judgment').problems,
    ['a03-v2', 'a02-v4', 'a15-v4', 'a12-v4', 'a04-v4', 'a01-v2'].map(s => 'function-monotonicity-'+s));
  assert.equal(topic.groups.find(g => g.id === 'extremum').problems.length, 8);
  assert.ok(!topic.problems['function-monotonicity-a14-v1']);
  assert.equal((await read(prefix('a14')+'.source.json')).preview, true);
});
