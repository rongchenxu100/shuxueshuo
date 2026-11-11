import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtemp, symlink, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { exportContent } from '../export-public-knowledge.mjs';
import { contentDigest } from '../lib/public-knowledge-export.mjs';
import { generate, repoRoot } from '../build-public-knowledge-graph.mjs';

const data = await exportContent();

test('release checks execute through a symlinked source directory', async () => {
  const temp = await mkdtemp(path.join(tmpdir(), 'knowledge-cli-'));
  try {
    const linkedRoot = path.join(temp, 'source');
    await symlink(repoRoot, linkedRoot, 'dir');
    for (const tool of ['build-public-knowledge-graph.mjs', 'build-topic-overviews.mjs', 'export-public-knowledge.mjs']) {
      const script = path.join(linkedRoot, 'tools', tool);
      const output = JSON.parse(execFileSync(process.execPath, [script, '--check'], { encoding: 'utf8' }));
      if (tool.startsWith('export-')) assert.equal(output.content_version, data._meta.content_version);
      else assert.equal(output.changed, 0);
      assert.throws(() => execFileSync(process.execPath, [script, '--invalid'], { stdio: 'pipe' }));
    }
  } finally {
    await rm(temp, { recursive: true, force: true });
  }
});

test('structured export contains current ontology and private drills without HTML rendering', () => {
  assert.equal(data.knowledge_nodes.length, 167);
  assert.equal(new Set(data.knowledge_nodes.map((n) => n.kind)).size, 9);
  assert.equal(new Set(data.knowledge_edges.map((e) => e.relation_type)).size, 10);
  assert.equal(data.practice_problems.length, 137);
  assert.equal(data.practice_routes.length, 157);
  const comparisonSteps = data.practice_steps.filter(row => row.problem_id === 'function-concepts-q20-v2');
  // B–D each merge two scored parts into one displayed card: 15 decisions, 12 cards.
  assert.equal(comparisonSteps.length, 15, '3 intro + 11 scoped mathematical decisions + 1 original exact selection');
  const sharedComparisonSteps = data.practice_steps.filter(row => row.problem_id === 'function-concepts-q19');
  assert.equal(sharedComparisonSteps.length, 15);
  assert.equal(data.practice_steps.length, 1310);
  assert.equal(data.knowledge_drill_items.length, 177);
  assert.equal(new Set(data.knowledge_drill_items.map((q) => q.item_id)).size, 177);
  assert.equal(data.knowledge_drill_items.filter((q) => q.node_id === 'amgm-formula').length, 1);
  assert.ok(data.knowledge_drill_items.every((q) => q.answer_spec.selected.length));
  assert.ok(data.knowledge_entries.some((e) => e.entry_type === 'branch'));
  assert.ok(data.knowledge_edges.some((e) => e.occurrences.length > 1));
});

test('chapter 3.1 exposes verified courses with their own sources and implemented types', () => {
  const topic = data.practice_topics.find((row) => row.id === 'function-concepts');
  assert.equal(topic.label, '函数的概念');
  assert.equal(topic.path, '/topics/function-concepts/');
  assert.equal(topic.groups.length, 5);
  const ids = ['function-concepts-q15', 'function-concepts-q01', 'function-concepts-q22-v2', 'function-concepts-q04', 'function-concepts-q12', 'function-concepts-q23b-v2'];
  assert.deepEqual(topic.groups.find((group) => group.id === 'domain').problems, ids);
  const comparisonIds = ['function-concepts-q20-v2', 'function-concepts-q19'];
  assert.deepEqual(topic.groups.find(group => group.id === 'equality').problems, comparisonIds);
  const abstractIds = ['function-concepts-q25', 'function-concepts-q26', 'function-concepts-abstract-mixed-q03', 'function-concepts-parameter-variant02'];
  const evaluationIds = ['function-concepts-q28a-v2', 'function-concepts-q28b-v2', 'function-concepts-q28c-v2', 'function-concepts-q28d-v2', 'function-concepts-q29b-v2'];
  const rangeIds = ['function-concepts-range-q03', 'function-concepts-range-q05', 'function-concepts-range-q06', 'function-concepts-range-q07', 'function-concepts-range-q08', 'function-concepts-range-q09', 'function-concepts-range-q10', 'function-concepts-range-q11', 'function-concepts-range-q13', 'function-concepts-range-q16', 'function-concepts-range-q17', 'function-concepts-range-q18'];
  assert.deepEqual(topic.groups.find((group) => group.id === 'abstract-domain').problems, abstractIds);
  assert.deepEqual(topic.groups.find((group) => group.id === 'evaluation').problems, evaluationIds);
  assert.deepEqual(topic.groups.find((group) => group.id === 'range').problems, rangeIds);
  assert.deepEqual(
    data.practice_topic_problems.filter((row) => row.topic_id === topic.id).map(row => row.problem_id).sort(),
    [...ids, ...comparisonIds, ...abstractIds, ...evaluationIds, ...rangeIds].sort(),
  );
  for (const [id, basis] of [[ids[0], 'square-root-expression#meaning'], [ids[1], 'integer-power#zero-exponent']]) {
    const problem = data.practice_problems.find((row) => row.id === id);
    const course = problem.problem_data._graph_walk;
    assert.equal(course.schema, 'graph-walk-practice/v1');
    assert.equal(course.problemId, id);
    assert.deepEqual(Object.keys(course.routes), ['domain-intersection']);
    assert.deepEqual(course.intro.map(step => step.id), ['D1', 'D2', 'D3']);
    assert.equal(course.routes['domain-intersection'].steps.length, 4);
    const regions = course.routes['domain-intersection'].steps[0].source_regions.regions;
    assert.deepEqual(regions.flatMap(region => region.basis_refs).sort(), [basis, 'rational-expression#meaning'].sort());
    const steps = data.practice_steps.filter((row) => row.problem_id === id);
    assert.equal(steps.length, 7);
    assert.ok(steps.some(step => step.refs.includes(basis)), `${id} exports its own mathematical basis`);
    assert.ok(data.practice_problem_types.some((row) => row.problem_id === id && row.node_id === 'type-function-domain'));
  }
  for (const id of ['function-concepts-q22-v2', 'function-concepts-q04', 'function-concepts-q12', 'function-concepts-q23b-v2']) {
    const problem = data.practice_problems.find((row) => row.id === id);
    const course = problem.problem_data._graph_walk;
    assert.equal(course.schema, 'graph-walk-practice/v1');
    assert.deepEqual(Object.keys(course.routes), ['domain-parameter']);
    assert.deepEqual(course.intro.map(step => step.id), ['D1', 'D2', 'D3']);
    const expectedSteps = {'function-concepts-q12': 15, 'function-concepts-q23b-v2': 13}[id] ?? 14;
    assert.equal(course.routes['domain-parameter'].steps.length, expectedSteps - 3);
    const steps = data.practice_steps.filter((row) => row.problem_id === id);
    assert.equal(steps.length, expectedSteps);
    if (['function-concepts-q12', 'function-concepts-q23b-v2'].includes(id)) {
      assert.ok(steps.some(step => step.refs.includes('rational-expression#meaning')));
    }
    const borrowed = id === 'function-concepts-q23b-v2' ? 'method-separation' : 'method-discriminant';
    assert.ok(steps.some(step => step.refs.includes(borrowed)
      || step.refs.some(ref => ref.startsWith(borrowed + '#'))), `${id} keeps its borrowed submethod refs`);
    assert.ok(data.practice_problem_types.some((row) => row.problem_id === id && row.node_id === 'type-function-domain'));
  }
  const types = data.knowledge_nodes.filter((node) => node.body.status === 'planned');
  assert.deepEqual(types.map(type => type.id).sort(), []);
  for (const id of ['type-function-graph', 'type-piecewise-function',
    'type-monotonicity-abstract-proof', 'type-monotonicity-extremum',
    'type-monotonicity-inequality', 'type-monotonicity-parameter', 'type-function-parity', 'type-parity-parameter']) {
    assert.ok(data.knowledge_nodes.find(node => node.id === id).body.methods.length);
    assert.ok(data.practice_problem_types.some(row => row.node_id === id));
  }
  for (const type of types) {
    assert.equal(type.kind, 'problem_type');
    assert.deepEqual(type.body.examples, []);
    assert.deepEqual(type.body.methods, []);
    assert.deepEqual(type.body.rules, []);
    assert.ok(!data.practice_problem_types.some((row) => row.node_id === type.id));
    assert.ok(!data.knowledge_drill_items.some((row) => row.node_id === type.id));
  }
});

test('monotonicity publishes verified courses for all five implemented types', () => {
  const topic = data.practice_topics.find(row => row.id === 'function-monotonicity');
  assert.ok(topic);
  const ids = ['function-monotonicity-a03-v2', 'function-monotonicity-a02-v4',
    'function-monotonicity-a15-v4', 'function-monotonicity-a12-v4',
    'function-monotonicity-a04-v4', 'function-monotonicity-a01-v2'];
  assert.deepEqual(topic.groups.find(group => group.id === 'judgment').problems, ids);
  assert.deepEqual(topic.groups.map(group => [group.id, group.problems.length]), [
    ['judgment', 6], ['extremum', 8], ['inequality', 9], ['parameter', 8], ['abstract-proof', 2],
  ]);
  const allIds = topic.groups.flatMap(group => group.problems);
  assert.equal(new Set(allIds).size, 33);
  assert.deepEqual(data.practice_topic_problems.filter(row => row.topic_id === topic.id)
    .map(row => row.problem_id).sort(), [...allIds].sort());
  for (const group of topic.groups) for (const id of group.problems) {
    assert.ok(data.practice_problems.find(row => row.id === id)?.problem_data._graph_walk);
    assert.ok(data.practice_problem_types.some(row => row.problem_id === id && row.node_id === group.type));
    assert.ok(data.practice_steps.some(row => row.problem_id === id));
  }
  for (const id of ids) {
    const problem = data.practice_problems.find(row => row.id === id);
    assert.ok(problem?.problem_data._graph_walk);
    assert.ok(data.practice_problem_types.some(row => row.problem_id === id && row.node_id === 'type-function-monotonicity'));
    assert.ok(data.practice_steps.some(row => row.problem_id === id));
  }
});

test('parity exports T1 and the verified T2 parameter course with their own methods', () => {
  const topic = data.practice_topics.find(row => row.id === 'function-parity');
  assert.equal(topic.groups.length, 2);
  assert.equal(topic.groups[0].type, 'type-function-parity');
  assert.deepEqual(topic.groups[0].problems, ['function-parity-a01-1-v2', 'function-parity-a01-2-v2']);
  for (const id of topic.groups[0].problems) {
    const course = data.practice_problems.find(row => row.id === id).problem_data._graph_walk;
    assert.deepEqual(Object.keys(course.routes), ['parity-definition']);
    assert.equal(course.intro[0].id, 'D1');
    assert.equal(course.intro[0].question, '这一问需要判断什么？');
    assert.ok(data.practice_problem_types.some(row => row.problem_id === id && row.node_id === 'type-function-parity'));
    assert.ok(data.practice_steps.some(row => row.problem_id === id));
  }
  assert.equal(topic.groups[1].type, 'type-parity-parameter');
  assert.deepEqual(topic.groups[1].problems, ['function-parity-a17']);
  const id = 'function-parity-a17';
  const course = data.practice_problems.find(row => row.id === id).problem_data._graph_walk;
  assert.deepEqual(Object.keys(course.routes), ['parity-parameter']);
  assert.equal(course.routes['parity-parameter'].steps.length, 5);
  assert.ok(data.practice_problem_types.some(row => row.problem_id === id && row.node_id === 'type-parity-parameter'));
  const steps = data.practice_steps.filter(row => row.problem_id === id);
  assert.equal(steps.length, 8);
  assert.ok(steps.some(row => row.refs.includes('skill-polynomial-coefficient-comparison')));
});

test('exports are reproducible and preserve conditional route associations', async () => {
  assert.deepEqual(await exportContent(), data);
  const { _meta, ...rows } = data;
  assert.equal(_meta.content_version, contentDigest(rows));
  const route = data.practice_routes.find((r) => r.problem_id === 'basic-inequality-q01' && r.route_id === 'elimination');
  assert.equal(route.methods.field, 'technique');
  const text = JSON.stringify(route.methods);
  assert.ok(text.includes('method-quadratic-extremum'));
  assert.ok(text.includes('method-square-extremum'));
});

test('static and database content versions agree, static outputs never carry drill answers', async () => {
  const { outputs } = await generate();
  const version = JSON.parse(outputs.get('teaching/version.json'));
  assert.deepEqual(version, data._meta);
  const problem = JSON.parse(outputs.get('teaching/problems/basic-inequality-q01.json'));
  assert.equal(problem.content_version, undefined);
  assert.match(problem.practice_version, /^[0-9a-f]{64}$/);
  for (const [name, output] of outputs) if (name.endsWith('.json')) {
    assert.ok(!output.includes('"answer_spec"'), name);
    assert.ok(!output.includes('"item_snapshot"'), name);
    assert.ok(!output.includes('"_lesson"'), name);
    assert.ok(!output.includes('"required_evidence"'), name);
  }
});
