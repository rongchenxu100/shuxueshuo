import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {compileCourse} from '../build-graph-walk-topic.mjs';
import {loadSources} from '../lib/public-knowledge-sources.mjs';
import {nativePracticeContract} from '../lib/graph-walk-practice.mjs';
import {replayAnswer} from '../../site/assets/graph-walk/walk-replay.mjs';
import {
  createState, currentDecision, extendStreamBundle, graphState, projectDecision, submitAnswer, switchRoute, undo,
} from '../../site/assets/graph-walk/walk-state.mjs';

const read = async path => JSON.parse(await fs.readFile(new URL(path, import.meta.url), 'utf8'));
const graph = await read('../../site/knowledge/graph.json');
const {nodes} = await loadSources();
const rule = 'rule-quadratic-method';
const route = 'domain-parameter';
const fixtures = await Promise.all(['q22-v2', 'q04', 'q12', 'q23b'].map(async suffix => {
  const id = `function-concepts-${suffix}`;
  const source = await read(`../../site/data/graph-walk/${id}.source.json`);
  const evidence = await read(`../../site/data/graph-walk/${id}.evidence.json`);
  const saved = await read(`../../site/data/graph-walk/${id}.json`);
  return {id, source, evidence, saved, base: evidence.lesson.goals.find(goal => goal.target_ref === source.targetRef).walk.bundle};
}));

function beforeBorrow(bundle) {
  let state = createState(bundle);
  for (let decision = currentDecision(bundle, state); decision; decision = currentDecision(bundle, state)) {
    if (decision.source === 'stream' && decision.interaction.type === 'plane') return state;
    state = submitAnswer(bundle, state, {decision: decision.id, answer: replayAnswer(decision, route)});
    assert.equal(state.lastFeedback.status, 'passed');
  }
  assert.fail('missing borrowed method choice');
}

for (const fixture of fixtures) {
  for (const mode of ['static', 'incremental']) test(`${fixture.id}: ${mode} nested choice has real candidate and chosen graph paths`, () => {
    const {source, evidence, base} = fixture;
    let bundle;
    if (mode === 'static') bundle = compileCourse(source, evidence, graph, nodes).bundle;
    else {
      const pending = {...evidence.stream, math_steps: [], interaction_states: [], interactions: []};
      bundle = extendStreamBundle(base, pending, source.targetRef, graph);
      assert.ok(!bundle.graph.nodes.some(node => node.id === rule));
      bundle = extendStreamBundle(bundle, evidence.stream, source.targetRef, graph);
      assert.deepEqual(extendStreamBundle(bundle, evidence.stream, source.targetRef, graph).routes, bundle.routes);
    }
    let state = beforeBorrow(bundle);
    const decision = currentDecision(bundle, state);
    const paths = graph.edges.filter(edge => edge.from === rule && edge.type === 'selects');
    const graphView = graphState(bundle, state);
    assert.equal(graphView.nodes[rule], 'active');
    assert.ok(graphView.focus.includes(rule));
    assert.ok(projectDecision(bundle, state).candidates.some(node => node.id === rule));
    assert.equal(graphView.edges['type-function-domain|candidate|method-domain-parameter'], 'chosen',
      'the non-plane top-level direct method selection retains its graph edge');
    for (const edge of paths) {
      assert.deepEqual(bundle.graph.edges.find(item => item.id === edge.id), edge);
      assert.ok(bundle.graph.nodes.some(node => node.id === edge.to));
      assert.ok(projectDecision(bundle, state).candidates.some(node => node.id === edge.to));
      assert.equal(graphView.nodes[edge.to], 'candidate');
      assert.equal(graphView.edges[edge.id], 'candidate');
    }
    for (const alternative of Object.keys(decision.alternatives || {})) {
      const next = submitAnswer(bundle, state, {decision: decision.id, answer: [...decision.expected_answer.cell, alternative]});
      assert.equal(next.lastFeedback.status, 'uncovered');
      assert.deepEqual(next.run.completed, state.run.completed);
      assert.deepEqual(graphState(bundle, next), graphView);
    }
    const answer = replayAnswer(decision, route);
    const method = decision.interaction.methods.find(item => item.value === answer[2]);
    state = submitAnswer(bundle, state, {decision: decision.id, answer});
    assert.equal(state.lastFeedback.status, 'passed');
    assert.equal(state.run.route, route, 'borrowing must retain the parent route');
    const confirmed = graphState(bundle, state);
    assert.equal(confirmed.nodes[rule], 'confirmed');
    assert.equal(confirmed.nodes[method.target], 'confirmed');
    assert.equal(confirmed.edges[`${rule}|selects|${method.target}`], 'chosen');
    for (const edge of paths.filter(edge => edge.to !== method.target)) assert.equal(confirmed.edges[edge.id], 'idle');
    const log = confirmed.logs.filter(item => item.decision === decision.id).at(-1).text;
    assert.ok(log.includes(`选择「${method.label}」`));
    assert.ok(!log.includes(`选择「${bundle.routes[route].label}」`));
    assert.deepEqual(graphState(bundle, undo(bundle, state)), graphView);
    if (mode === 'static') assert.deepEqual(nativePracticeContract(bundle), nativePracticeContract(fixture.saved),
      'graph display changes must preserve native grading identity');
  });
}

test('nested choices never synthesize a rule node or a selection edge absent from the authoritative graph', () => {
  const {base, evidence, source} = fixtures.at(-1);
  for (const omit of ['rule', 'selected-edge']) {
    const selected = `${rule}|selects|method-separation`;
    const limited = {...graph,
      nodes: graph.nodes.filter(node => omit !== 'rule' || node.id !== rule),
      edges: graph.edges.filter(edge => omit === 'rule' ? edge.from !== rule && edge.to !== rule : edge.id !== selected),
    };
    const bundle = extendStreamBundle(base, evidence.stream, source.targetRef, limited);
    let state = beforeBorrow(bundle);
    const decision = currentDecision(bundle, state);
    for (const view of [graphState(bundle, state), graphState(bundle,
      submitAnswer(bundle, state, {decision: decision.id, answer: replayAnswer(decision, route)}))]) {
      assert.equal(view.edges[selected], undefined);
      if (omit === 'rule') assert.equal(view.nodes[rule], undefined);
    }
    assert.ok(!bundle.graph.edges.some(edge => edge.id === selected));
    if (omit === 'rule') assert.ok(!bundle.graph.nodes.some(node => node.id === rule));
  }
});

test('late full graph metadata enriches nested choices without mutating committed decisions or answers', () => {
  const {base, evidence, source} = fixtures.at(-1);
  const limited = {...graph, nodes: graph.nodes.filter(node => node.id !== rule),
    edges: graph.edges.filter(edge => edge.from !== rule && edge.to !== rule)};
  const initial = extendStreamBundle(base, evidence.stream, source.targetRef, limited);
  const state = beforeBorrow(initial);
  assert.equal(graphState(initial, state).nodes[rule], undefined);
  const complete = extendStreamBundle(initial, evidence.stream, source.targetRef, graph);
  assert.deepEqual(complete.routes, initial.routes, 'graph enrichment must leave immutable decisions unchanged');
  assert.equal(currentDecision(complete, state).id, currentDecision(initial, state).id);
  assert.equal(graphState(complete, state).nodes[rule], 'active');
  assert.equal(graphState(complete, state).edges[`${rule}|selects|method-separation`], 'candidate');
  assert.ok(projectDecision(complete, state).candidates.some(node => node.id === rule));
});

test('switching static top-level routes preserves the former real selection edge in archived history', async () => {
  const bundle = await read('../../site/data/graph-walk/quadratic-always-q01.json');
  let state = createState(bundle);
  for (let decision = currentDecision(bundle, state); decision; decision = currentDecision(bundle, state)) {
    state = submitAnswer(bundle, state, {decision: decision.id, answer: replayAnswer(decision, 'discriminant')});
    assert.equal(state.lastFeedback.status, 'passed');
  }
  assert.equal(state.done, true);
  state = switchRoute(bundle, state, 'extremum');
  const view = graphState(bundle, state);
  assert.ok(view.archivedEdges.includes(`${rule}|selects|method-discriminant`));
  assert.equal(view.edges[`${rule}|selects|method-separation`], 'chosen');
  assert.equal(view.edges[`${rule}|selects|method-discriminant`], 'idle');
});
