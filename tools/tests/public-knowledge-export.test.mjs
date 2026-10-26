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
  assert.equal(data.knowledge_nodes.length, 93);
  assert.equal(new Set(data.knowledge_nodes.map((n) => n.kind)).size, 9);
  assert.equal(new Set(data.knowledge_edges.map((e) => e.relation_type)).size, 10);
  assert.equal(data.practice_problems.length, 41);
  assert.equal(data.practice_routes.length, 52);
  assert.equal(data.practice_steps.length, 273);
  assert.equal(data.knowledge_drill_items.length, 177);
  assert.equal(new Set(data.knowledge_drill_items.map((q) => q.item_id)).size, 177);
  assert.equal(data.knowledge_drill_items.filter((q) => q.node_id === 'amgm-formula').length, 1);
  assert.ok(data.knowledge_drill_items.every((q) => q.answer_spec.selected.length));
  assert.ok(data.knowledge_entries.some((e) => e.entry_type === 'branch'));
  assert.ok(data.knowledge_edges.some((e) => e.occurrences.length > 1));
});

test('chapter 3.1 exposes both domain courses with their own knowledge sources and keeps other types planned', () => {
  const topic = data.practice_topics.find((row) => row.id === 'function-concepts');
  assert.equal(topic.label, '函数的概念');
  assert.equal(topic.path, '/topics/function-concepts/');
  assert.equal(topic.groups.length, 5);
  const ids = ['function-concepts-q15', 'function-concepts-q01'];
  assert.deepEqual(topic.groups.find((group) => group.id === 'domain').problems, ids);
  assert.ok(topic.groups.filter((group) => group.id !== 'domain').every((group) => group.problems.length === 0));
  assert.deepEqual(data.practice_topic_problems.filter((row) => row.topic_id === topic.id).map(row => row.problem_id).sort(), [...ids].sort());
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
  const types = data.knowledge_nodes.filter((node) => node.body.status === 'planned');
  assert.equal(types.length, 4);
  for (const type of types) {
    assert.equal(type.kind, 'problem_type');
    assert.deepEqual(type.body.examples, []);
    assert.deepEqual(type.body.methods, []);
    assert.deepEqual(type.body.rules, []);
    assert.ok(!data.practice_problem_types.some((row) => row.node_id === type.id));
    assert.ok(!data.knowledge_drill_items.some((row) => row.node_id === type.id));
  }
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
  assert.equal(JSON.parse(outputs.get('teaching/problems/basic-inequality-q01.json')).content_version, version.content_version);
  for (const [name, output] of outputs) if (name.endsWith('.json')) {
    assert.ok(!output.includes('"answer_spec"'), name);
    assert.ok(!output.includes('"item_snapshot"'), name);
    assert.ok(!output.includes('"_lesson"'), name);
    assert.ok(!output.includes('"required_evidence"'), name);
  }
});
