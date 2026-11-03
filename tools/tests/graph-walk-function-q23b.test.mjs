import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {buildStreamReplay} from '../../site/assets/graph-walk/walk-replay.mjs';
import {currentDecision, replayState} from '../../site/assets/graph-walk/walk-state.mjs';
import {compileCourse} from '../build-graph-walk-topic.mjs';
import {loadSources} from '../lib/public-knowledge-sources.mjs';
import {exportContent} from '../export-public-knowledge.mjs';

const read = async path => JSON.parse(await fs.readFile(new URL(path, import.meta.url), 'utf8'));
const id = 'function-concepts-q23b-v2';
const bundle = await read(`../../site/data/graph-walk/${id}.json`);
const replay = await read(`../../site/data/graph-walk/${id}.replay.json`);
const route = bundle.routes['domain-parameter'];

test('Q23 second question has an independent course identity without the first question condition', async () => {
  const source = await read(`../../site/data/graph-walk/${id}.source.json`);
  const topic = await read('../../site/data/knowledge-next/topics/function-concepts.json');
  const group = topic.groups.find(group => group.id === 'domain');
  assert.equal(group.problems[group.problems.indexOf(id) - 1], 'function-concepts-q12');
  assert.equal(source.page, '/topics/function-concepts/q23b/');
  assert.equal(topic.problems[id].path, source.page);
  assert.equal(topic.problems[id].bundle, `/data/graph-walk/${id}.json`);
  assert.equal(bundle.problemId, id);
  assert.ok(bundle.problem.text.replaceAll('\\dfrac', '\\frac').includes(String.raw`\frac{\sqrt{x^2-3x-m}}{\sqrt{x-1}}`));
  assert.doesNotMatch(bundle.problem.text, /10|第一问|（1）/);
  const evidence = await read(`../../site/data/graph-walk/${id}.evidence.json`);
  assert.deepEqual(evidence.lesson.goals.map(goal => goal.target_ref), ['/root/goals/0']);
  const html = await fs.readFile(new URL('../../site/topics/function-concepts/q23b/index.html', import.meta.url), 'utf8');
  assert.match(html, /"problemId":"function-concepts-q23b-v2"/);
  const {nodes} = await loadSources();
  for (const page of ['/topics/function-concepts/q23b/../', '/topics/function-concepts/q23b/extra/', '/topics/function-concepts/q23bb/']) {
    assert.throws(() => compileCourse({...source, page}, evidence, bundle.graph, nodes), /Invalid topic problem path/);
  }
});

test('Q23b preserves three source restrictions, exact domain, and the closed parameter endpoint', () => {
  const steps = bundle.stream.math_steps;
  const constraints = steps.find(step => step.display_unit === 'domain_parameter_conditions');
  assert.ok(constraints.used_basis.includes('square-root-expression#meaning'));
  assert.ok(constraints.used_basis.includes('rational-expression#meaning'));
  const conditions = route.steps.find(step => step.title === '列出根号与分母的条件');
  assert.equal(conditions.interaction.slots.length, 3);
  const labels = conditions.interaction.slots.map((slot, index) =>
    slot.options.find(option => option.value === conditions.expected_answer.terms[index]).label);
  assert.match(labels[0], /m.*\\geq 0/);
  assert.match(labels[1], /x - 1 \\geq 0/);
  assert.match(labels[2], /\\sqrt\{x - 1\} \\neq 0/);
  const universal = steps.find(step => step.display_unit === 'domain_parameter_universal');
  assert.match(universal.explanation, /分母.*恰好.*原式自动被排除/s);
  assert.ok(universal.after.some(value => value.expression === '-m + x**2 - 3*x >= 0'));
  const range = steps.find(step => step.display_unit === 'interval_range');
  assert.ok(range.after.some(value => value.expression === 'Interval(-9/4, oo)'));
  assert.equal(route.completion.status, 'verified');
  assert.equal(route.completion.answer.set.expression, 'Interval(-oo, -9/4)');
  assert.ok(route.completion.answer.set.latex.endsWith(String.raw`\right]`));
  const returned = route.steps.find(step => step.title === '回到定义域求参');
  const label = returned.interaction.options.find(option => option.value === returned.expected_answer.one_of[0]).label;
  assert.match(label, /D_\{f\}=.*1.*\\infty/);
  assert.doesNotMatch(label, /mathbb/);
});

test('Q23b borrows separation on the actual halfline and publishes the same course', async () => {
  assert.equal(route.method, 'method-domain-parameter');
  const borrow = route.steps.find(step => step.interaction.type === 'plane');
  assert.deepEqual(borrow.expected_answer, {cell: ['interval', 'free'], method: 'separation'});
  assert.deepEqual(borrow.effects.nodes, ['rule-quadratic-method', 'method-separation']);
  const data = await exportContent();
  const published = data.practice_problems.find(problem => problem.id === id);
  assert.equal(published.path, '/topics/function-concepts/q23b/');
  assert.equal(published.problem_data._graph_walk.bundleVersion, bundle.bundleVersion);
  assert.deepEqual(published.problem_data._graph_walk.routes['domain-parameter'].steps.map(step => step.id),
    route.steps.map(step => step.id));
  const refs = data.practice_steps.filter(step => step.problem_id === id).flatMap(step => step.refs);
  for (const ref of ['method-separation', 'rational-expression#meaning', 'square-root-expression#meaning', 'quadratic-interval-extremum']) {
    assert.ok(refs.includes(ref), `missing public reference: ${ref}`);
  }
});

test('Q23b static and photo stream replay both finish all 13 actions', () => {
  assert.equal(replay.actions.length, 13);
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
