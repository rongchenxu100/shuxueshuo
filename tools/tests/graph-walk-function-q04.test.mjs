import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {buildStreamReplay} from '../../site/assets/graph-walk/walk-replay.mjs';
import {currentDecision, replayState} from '../../site/assets/graph-walk/walk-state.mjs';
import {exportContent} from '../export-public-knowledge.mjs';

const read = async path => JSON.parse(await fs.readFile(new URL(path, import.meta.url), 'utf8'));
const id = 'function-concepts-q04';
const bundle = await read(`../../site/data/graph-walk/${id}.json`);
const replay = await read(`../../site/data/graph-walk/${id}.replay.json`);
const route = bundle.routes['domain-parameter'];

test('Q04 follows Q22 in the function topic and has its own course identity', async () => {
  const source = await read(`../../site/data/graph-walk/${id}.source.json`);
  const topic = await read('../../site/data/knowledge-next/topics/function-concepts.json');
  const group = topic.groups.find(group => group.id === 'domain');
  assert.equal(group.problems[group.problems.indexOf(id) - 1], 'function-concepts-q22-v2');
  assert.equal(source.problemId, id);
  assert.equal(source.page, '/topics/function-concepts/q04/');
  assert.equal(source.evidence, `site/data/graph-walk/${id}.evidence.json`);
  assert.equal(topic.problems[id].path, source.page);
  assert.equal(topic.problems[id].bundle, `/data/graph-walk/${id}.json`);
  assert.equal(bundle.problemId, id);
  const html = await fs.readFile(new URL('../../site/topics/function-concepts/q04/index.html', import.meta.url), 'utf8');
  assert.match(html, /"problemId":"function-concepts-q04"/);
});

test('Q04 keeps the valid zero-coefficient case and both closed endpoints', () => {
  assert.equal(route.completion.status, 'verified');
  assert.equal(route.completion.feasible_set.expression, 'Interval(0, 3/4)');
  assert.equal(route.completion.answer.set.expression, 'Interval(0, 3/4)');
  const zero = bundle.stream.math_steps.find(step => step.display_unit === 'degenerate_case');
  assert.ok(zero);
  assert.equal(zero.case_condition.expression, 'Eq(m, 0)');
  assert.equal(zero.local_check, 'passed');
  assert.ok(zero.after.some(value => value.expression === '{0}'), 'm=0 is retained as a feasible parameter');
  assert.match(zero.highlight.result, /保留/);
  const merge = bundle.stream.math_steps.find(step => step.display_unit === 'merge_cases');
  assert.ok(merge.after.some(value => value.expression === 'Interval(0, 3/4)'));
});

test('Q04 reuses domain-parameter and discriminant methods in its native publication', async () => {
  assert.equal(route.method, 'method-domain-parameter');
  const borrow = route.steps.find(step => step.interaction.type === 'plane');
  assert.ok(borrow);
  assert.equal(borrow.expected_answer.method, 'discriminant');
  assert.deepEqual(borrow.effects.nodes, ['rule-quadratic-method', 'method-discriminant']);
  assert.ok(bundle.stream.math_steps.some(step => step.method_ref === 'method-discriminant#degree'));
  const data = await exportContent();
  const published = data.practice_problems.find(problem => problem.id === id);
  assert.equal(published.path, '/topics/function-concepts/q04/');
  assert.equal(published.problem_data._graph_walk.bundleVersion, bundle.bundleVersion);
  assert.deepEqual(published.problem_data._graph_walk.routes['domain-parameter'].steps.map(step => step.id),
    route.steps.map(step => step.id));
});

test('Q04 static and photo stream replay both cross the submethod judgment and finish', () => {
  assert.equal(replay.actions.length, 14);
  const streamed = buildStreamReplay(bundle, {
    actions: replay.actions.slice(0, bundle.intro.findIndex(step => step.id === 'D3')),
    currentRoute: 'domain-parameter',
  });
  assert.deepEqual(streamed.actions, replay.actions);
  for (const actions of [replay, streamed]) {
    const state = replayState(bundle, actions);
    assert.equal(state.done, true);
    assert.equal(currentDecision(bundle, state), null);
  }
});
