import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {replayAnswer, buildStreamReplay} from '../../site/assets/graph-walk/walk-replay.mjs';
import {replayState, currentDecision} from '../../site/assets/graph-walk/walk-state.mjs';

const read = path => JSON.parse(fs.readFileSync(new URL(path, import.meta.url), 'utf8'));

test('Q22 photo AI replay crosses the nested selection and reaches the same end as the topic replay', () => {
  const topic = read('../../site/data/knowledge-next/topics/function-concepts.json');
  const course = Object.values(topic.problems).find(problem => problem.path === '/topics/function-concepts/q22/');
  const bundle = read(`../../site${course.bundle}`);
  const recorded = read(`../../site${course.bundle.replace(/\.json$/, '.replay.json')}`);
  const nested = Object.values(bundle.routes).flatMap(route => route.steps).filter(step => step.interaction.type === 'plane');
  assert.equal(nested.length, 1, 'the active course contains the borrowed-method judgment');
  const stream = buildStreamReplay(bundle, {
    actions: recorded.actions.slice(0, bundle.intro.findIndex(step => step.id === 'D3')),
    currentRoute: 'domain-parameter',
  });
  assert.deepEqual(stream.actions, recorded.actions);
  const state = replayState(bundle, stream);
  assert.equal(state.done, true);
  assert.equal(currentDecision(bundle, state), null);
});

const direct = () => ({problemId: 'test', bundleVersion: 'v1', intro: [{id: 'D3', interaction: {
  type: 'read', methods: [{value: 'a', route: 'a'}, {value: 'b', route: 'b'}]}}], routes: {
  a: {route_plan: 'planned', steps: []}, b: {route_plan: 'planned', steps: []},
}});

test('stream replay prefers the chosen available route and never enters a revoked route', () => {
  const bundle = direct();
  assert.deepEqual(buildStreamReplay(bundle, {replayRoute: 'b', currentRoute: 'a'}).routes, ['b']);
  bundle.routes.b.available = false;
  assert.deepEqual(buildStreamReplay(bundle, {replayRoute: 'b', currentRoute: 'a'}).routes, ['a']);
  bundle.routes.a.route_plan = 'capability_gap';
  assert.deepEqual(buildStreamReplay(bundle).actions, []);
});

test('stream replay stops at an incomplete answer contract and resumes when it arrives', () => {
  const bundle = direct();
  bundle.routes.a.steps = [
    {id: 'plane', interaction: {type: 'plane', methods: [{value: 'discriminant', route: 'a'}]}, expected_answer: {}},
    {id: 'return', interaction: {type: 'choice'}, expected_answer: {one_of: ['done']}},
  ];
  assert.deepEqual(buildStreamReplay(bundle).actions, [{decision: 'D3', answer: 'read'}]);
  bundle.routes.a.steps[0].expected_answer = {cell: ['real', 'free'], method: 'discriminant'};
  assert.deepEqual(buildStreamReplay(bundle).actions, [
    {decision: 'D3', answer: 'read'}, {decision: 'plane', answer: ['real', 'free', 'discriminant']},
    {decision: 'return', answer: 'done'},
  ]);
});

test('nested method identity takes precedence over the parent route and replay answers are detached', () => {
  const decision = {interaction: {type: 'plane', methods: [{value: 'parent', route: 'domain'}]},
    expected_answer: {cell: ['real', 'free'], method: 'discriminant'}};
  const answer = replayAnswer(decision, 'domain');
  assert.deepEqual(answer, ['real', 'free', 'discriminant']);
  answer[0] = 'changed';
  assert.deepEqual(decision.expected_answer.cell, ['real', 'free']);
});
