import test from 'node:test';
import assert from 'node:assert/strict';
import {exportContent} from '../export-public-knowledge.mjs';
import {generateTopicOverviews} from '../build-topic-overviews.mjs';

const data = await exportContent();
const topic = data.practice_topics.find(row => row.id === 'function-representations');
const concepts = data.practice_topics.find(row => row.id === 'function-concepts');
const problemId = 'function-representations-b05-v2-r5';
const problemIds = ['b05-r2', 'w02-r2', 'w09-r2', 'b05-v2-r5', 'b05-v1', 'b05-v3', 'b04', 'w01', 'w12', 'b04-v', 'w10', 'b06', 'b06-v', 'w03', 'w05', 'w06', 'w07', 'w14', 'b07', 'b07-v', 'w04', 'w11'].map(id => `function-representations-${id}`);

test('the representation topic and its same-named knowledge node retain independent identities', () => {
  assert.equal(topic.path, '/topics/function-representations/');
  assert.equal(concepts.path, '/topics/function-concepts/');
  const knowledge = data.knowledge_nodes.filter(row => row.id === topic.id);
  assert.equal(knowledge.length, 1);
  assert.equal(knowledge[0].kind, 'knowledge');
  assert.equal(topic.groups.length, 4);
  assert.equal(concepts.groups.length, 5);
  assert.ok(concepts.groups.every(group => !topic.groups.some(other => other.type === group.type)));
  assert.ok(data.practice_topic_problems.some(row => row.topic_id === concepts.id));
  assert.deepEqual(data.practice_topic_problems.filter(row => row.topic_id === topic.id).map(row => row.problem_id).sort(), [...problemIds].sort());
  assert.ok(!data.practice_topic_problems.some(row => row.topic_id === concepts.id && row.problem_id === problemId));
  for (const group of topic.groups) {
    const type = data.knowledge_nodes.find(row => row.id === group.type);
    if (type.id === 'type-function-formula') {
      assert.deepEqual(group.problems, problemIds);
      assert.equal(group.groupBy, 'method');
      assert.equal(type.body.status, 'active');
      assert.deepEqual(type.body.methods, ['method-function-substitution', 'method-function-matching', 'method-function-coefficients', 'method-function-equation-system', 'method-function-assignment']);
      assert.equal(type.body.examples.length, 1);
      assert.deepEqual(type.body.rules, ['rule-function-formula-method']);
      assert.deepEqual(data.practice_problem_types.filter(row => row.node_id === type.id).map(row => row.problem_id).sort(), [...problemIds].sort());
    } else {
      assert.deepEqual(group.problems, []);
      assert.equal(type.body.status, 'planned');
      assert.deepEqual(type.body.methods, []);
      assert.deepEqual(type.body.examples, []);
      assert.deepEqual(type.body.rules, []);
      assert.ok(!data.practice_problem_types.some(row => row.node_id === type.id));
    }
    assert.ok(!data.knowledge_drill_items.some(row => row.node_id === type.id));
  }
});

test('the representation topic groups its formal exercise by method and exposes learning marks', async () => {
  const outputs = await generateTopicOverviews();
  const index = outputs.get('topics/index.html');
  for (const id of [topic.id, concepts.id]) assert.match(index, new RegExp(`id="topic-${id}"`));
  const page = outputs.get('topics/function-representations/index.html');
  assert.match(page, /href="\/knowledge\/function-representations\/"/);
  assert.match(page, /4 个题型 · 22 道题/);
  assert.match(page, /learning-marks\.js/);
  const methodGroup = page.match(/<section class="topic-method-group"[^>]*>([\s\S]*?)<\/section>/);
  assert.ok(methodGroup);
  assert.equal((page.match(/class="topic-method-group"/g) || []).length, 5);
  assert.match(page, /赋值法求函数解析式/);
  assert.match(page, /构造方程组法求函数解析式/);
  assert.match(page, /配凑法求函数解析式/);
  assert.match(methodGroup[1], /换元法求函数解析式/);
  assert.match(methodGroup[1], /href="\/topics\/function-representations\/variant02\/"/);
  assert.match(methodGroup[1], /href="\/topics\/function-representations\/q11\/"/);
  const matchingGroup = [...page.matchAll(/<section class="topic-method-group"[^>]*>([\s\S]*?)<\/section>/g)]
    .find(match => match[1].includes('配凑法求函数解析式'));
  assert.match(matchingGroup[1], /href="\/topics\/function-representations\/q04b\/"/);
  assert.match(methodGroup[1], new RegExp(`data-problem-id="${problemId}"`));
  for (const id of problemIds) {
    assert.match(page, new RegExp(`data-problem-id="${id}"`));
    assert.ok(!data.practice_topic_problems.some(row => row.topic_id === concepts.id && row.problem_id === id));
  }
  assert.doesNotMatch(page, /href="\/lab\/graph-walk\/|href="\/topics\/function-concepts\/q/);
  assert.equal((page.match(/class="topic-group-empty"/g) || []).length, 3);
  for (const group of topic.groups) assert.match(page, new RegExp(`href="/knowledge/${group.type}/"`));
  assert.match(outputs.get('topics/function-concepts/index.html'), /data-problem-id="function-concepts-q15"/);
  assert.doesNotMatch(outputs.get('topics/function-concepts/index.html'), new RegExp(`data-problem-id="${problemId}"`));
  const published = data.practice_problems.find(row => row.id === problemId);
  assert.equal(published.problem_data._graph_walk.problemId, problemId);
  assert.deepEqual(data.practice_routes.filter(row => row.problem_id === problemId).map(row => row.methods), [['method-function-substitution'], ['method-function-matching']]);
  assert.equal(data.practice_steps.filter(row => row.problem_id === problemId).length, 14);
});
