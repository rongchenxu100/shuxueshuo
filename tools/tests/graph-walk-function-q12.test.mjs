import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {buildStreamReplay} from '../../site/assets/graph-walk/walk-replay.mjs';
import {currentDecision, replayState} from '../../site/assets/graph-walk/walk-state.mjs';
import {exportContent} from '../export-public-knowledge.mjs';

const read = async path => JSON.parse(await fs.readFile(new URL(path, import.meta.url), 'utf8'));
const id = 'function-concepts-q12';
const bundle = await read(`../../site/data/graph-walk/${id}.json`);
const replay = await read(`../../site/data/graph-walk/${id}.replay.json`);
const route = bundle.routes['domain-parameter'];

test('Q12 follows Q04 and exposes the same course through the topic page', async () => {
  const source = await read(`../../site/data/graph-walk/${id}.source.json`);
  const topic = await read('../../site/data/knowledge-next/topics/function-concepts.json');
  const group = topic.groups.find(group => group.id === 'domain');
  assert.equal(group.problems[group.problems.indexOf(id) - 1], 'function-concepts-q04');
  assert.equal(source.problemId, id);
  assert.equal(source.page, '/topics/function-concepts/q12/');
  assert.equal(source.evidence, `site/data/graph-walk/${id}.evidence.json`);
  assert.equal(topic.problems[id].path, source.page);
  assert.equal(topic.problems[id].bundle, `/data/graph-walk/${id}.json`);
  assert.equal(bundle.problemId, id);
  const html = await fs.readFile(new URL('../../site/topics/function-concepts/q12/index.html', import.meta.url), 'utf8');
  assert.match(html, /"problemId":"function-concepts-q12"/);
});

test('Q12 preserves both original restrictions and strictness through the verified result', () => {
  const steps = bundle.stream.math_steps;
  const constraints = steps.find(step => step.display_unit === 'domain_parameter_conditions');
  assert.ok(constraints.used_basis.includes('square-root-expression#meaning'));
  assert.ok(constraints.used_basis.includes('rational-expression#meaning'));
  assert.match(constraints.explanation, /\\geq 0/);
  assert.ok(constraints.explanation.includes(String.raw`\sqrt{m x^{2} - 6 m x + m + 8} \neq 0`));
  const universal = steps.find(step => step.display_unit === 'domain_parameter_universal');
  assert.ok(universal.after.some(value => value.expression === 'm*x**2 - 6*m*x + m + 8 > 0'));
  const zero = steps.find(step => step.display_unit === 'degenerate_case');
  assert.equal(zero.case_condition.expression, 'Eq(m, 0)');
  assert.ok(zero.after.some(value => value.expression === '8 > 0'));
  assert.ok(zero.after.some(value => value.expression === '{0}'));
  const delta = steps.find(step => step.display_unit === 'discriminant');
  assert.ok(delta.after.some(value => value.expression.includes('< 0') && !value.expression.includes('<=')));
  assert.equal(route.completion.status, 'verified');
  assert.equal(route.completion.feasible_set.expression, 'Interval.Ropen(0, 1)');
  assert.equal(route.completion.answer.set.expression, 'Interval.Ropen(0, 1)');
});

test('Q12 reuses M6 and discriminant with the two source knowledge references in publication', async () => {
  assert.equal(route.method, 'method-domain-parameter');
  const borrow = route.steps.find(step => step.interaction.type === 'plane');
  assert.equal(borrow.expected_answer.method, 'discriminant');
  assert.deepEqual(borrow.effects.nodes, ['rule-quadratic-method', 'method-discriminant']);
  const data = await exportContent();
  const published = data.practice_problems.find(problem => problem.id === id);
  assert.equal(published.path, '/topics/function-concepts/q12/');
  assert.equal(published.problem_data._graph_walk.bundleVersion, bundle.bundleVersion);
  assert.deepEqual(published.problem_data._graph_walk.routes['domain-parameter'].steps.map(step => step.id),
    route.steps.map(step => step.id));
  const refs = data.practice_steps.filter(step => step.problem_id === id).flatMap(step => step.refs);
  assert.ok(refs.includes('rational-expression#meaning'));
  assert.ok(refs.includes('square-root-expression#meaning'));
});

test('Q12 static and photo stream replay both finish the strict-condition judgment and submethod', () => {
  assert.equal(replay.actions.length, 15);
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
