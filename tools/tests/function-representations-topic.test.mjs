import test from 'node:test';
import assert from 'node:assert/strict';
import {exportContent} from '../export-public-knowledge.mjs';
import {generateTopicOverviews} from '../build-topic-overviews.mjs';

const data = await exportContent();
const topic = data.practice_topics.find(row => row.id === 'function-representations');
const concepts = data.practice_topics.find(row => row.id === 'function-concepts');

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
  assert.ok(!data.practice_topic_problems.some(row => row.topic_id === topic.id));
  for (const group of topic.groups) {
    const type = data.knowledge_nodes.find(row => row.id === group.type);
    assert.equal(type.body.status, 'planned');
    assert.deepEqual(group.problems, []);
    assert.deepEqual(type.body.methods, []);
    assert.deepEqual(type.body.rules, []);
    assert.deepEqual(type.body.examples, []);
    assert.ok(!data.practice_problem_types.some(row => row.node_id === type.id));
    assert.ok(!data.knowledge_drill_items.some(row => row.node_id === type.id));
  }
});

test('both topics have separate catalog entries while the empty topic exposes only knowledge and type navigation', async () => {
  const outputs = await generateTopicOverviews();
  const index = outputs.get('topics/index.html');
  for (const id of [topic.id, concepts.id]) assert.match(index, new RegExp(`id="topic-${id}"`));
  const page = outputs.get('topics/function-representations/index.html');
  assert.match(page, /href="\/knowledge\/function-representations\/"/);
  assert.match(page, /题目建设中/);
  assert.doesNotMatch(page, /data-problem-id|learning-marks\.js|href="\/topics\/function-concepts\/q/);
  for (const group of topic.groups) assert.match(page, new RegExp(`href="/knowledge/${group.type}/"`));
  assert.match(outputs.get('topics/function-concepts/index.html'), /data-problem-id="function-concepts-q15"/);
});
