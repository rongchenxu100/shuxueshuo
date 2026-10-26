import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {topicPath, validateTopicSource, loadTeaching} from '../lib/public-knowledge-teaching.mjs';
import {exportRows} from '../lib/public-knowledge-export.mjs';
import {topicOverviewOutputs, INDEX_BEGIN, INDEX_END, PAGE_MARKER} from '../lib/topic-overview-html.mjs';
import {generateTopicOverviews, publishTopicOverviews} from '../build-topic-overviews.mjs';

const source = JSON.parse(await fs.readFile(new URL('../../site/data/knowledge-next/topics/function-concepts.json', import.meta.url), 'utf8'));
const nodes = [
  {id:source.chapter.ref, kind:'section', label:'3.1 函数的概念及其表示', summary:'章节知识'},
  ...source.knowledge.map(id => ({id, kind:'knowledge', label:id, summary:'输入与输出的对应关系。'})),
  ...source.groups.map(group => ({id:group.type, kind:'problem_type', label:group.label, summary:group.description, status:'planned'}))
];
const manifest = {resources:{}};
const indexHtml = `<main><section id="old-topic"><a href="/1/">基本不等式</a></section>\n${INDEX_BEGIN}\n${INDEX_END}\n<footer>数学说</footer></main>\n`;

async function fixture(t) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'topic-overviews-'));
  t.after(() => fs.rm(root, {recursive:true, force:true}));
  const write = async (name, value) => {
    const file = path.join(root, name);
    await fs.mkdir(path.dirname(file), {recursive:true});
    await fs.writeFile(file, typeof value === 'string' ? value : JSON.stringify(value));
  };
  await write('site/data/knowledge-next/topics/function-concepts.json', source);
  await write('site/data/knowledge-next/catalog.json', manifest);
  await write('site/data/knowledge-next/outline.json', {});
  await write('site/data/knowledge-next/migration.json', {nodes:[], legacyRefs:{}});
  for (const node of nodes) await write(`site/data/knowledge-next/nodes/${node.id}.json`, node);
  await write('server/shuxueshuo_server/learning/drills-next/migration.json', {records:[], sourceCount:0});
  await write('server/shuxueshuo_server/learning/drills-next/retired.json', {items:[]});
  await fs.mkdir(path.join(root, 'server/shuxueshuo_server/learning/drills-next/sets'));
  await write('site/topics/index.html', indexHtml);
  return {root, write};
}

test('empty source has the agreed topic identity, eight knowledge entries and five type groups', () => {
  assert.equal(source.id, 'function-concepts');
  assert.equal(source.label, '函数的概念');
  assert.equal(topicPath(source), '/topics/function-concepts/');
  assert.equal(source.knowledge.length, 8);
  assert.deepEqual(source.groups.map(group => group.type), [
    'type-function-domain', 'type-function-equality', 'type-abstract-function-domain', 'type-function-evaluation', 'type-function-range'
  ]);
  assert.deepEqual(source.problems, {});
  assert.ok(source.groups.every(group => group.problems.length === 0));
  assert.equal(validateTopicSource(source, nodes), source);
});

test('explicit empty paths work while old topic paths keep their meaning', () => {
  assert.equal(topicPath({id:'old', legacyPath:'/2/', problems:{q01:{path:'/2/q01/'}}}), '/2/');
  assert.equal(topicPath({id:'old', problems:{q01:{path:'/1/q01/'}}}), '/1/');
  assert.equal(topicPath({...source, legacyPath:'/2/'}), '/topics/function-concepts/');
  for (const value of [undefined, '//outside.test/', '/topics/../secret/', '/topics/a/?x=1', '/topics/a/#x']) {
    assert.throws(() => topicPath({id:'empty', path:value, problems:{}}), /站内目录路径/);
  }
});

test('source validation rejects broken type/knowledge references and fake exercises', () => {
  const edit = fn => { const copy = structuredClone(source); fn(copy); return copy; };
  assert.throws(() => validateTopicSource(edit(value => value.groups[0].type = 'missing'), nodes), /节点不存在/);
  assert.throws(() => validateTopicSource(edit(value => value.groups[0].type = source.knowledge[0]), nodes), /类型不符/);
  assert.throws(() => validateTopicSource(edit(value => value.knowledge.push('missing')), nodes), /节点不存在/);
  assert.throws(() => validateTopicSource(edit(value => value.groups[0].problems.push('fake-q01')), nodes), /未覆盖题目/);
  assert.throws(() => validateTopicSource(edit(value => value.path = '/topics/'), nodes), /独立路径/);
});

test('teaching and private publication accept zero exercises without reading a teacher contract', async t => {
  const {root} = await fixture(t);
  const teaching = await loadTeaching(root, nodes, manifest);
  assert.deepEqual(teaching.counts, {problems:0, routes:0, steps:0, tips:0});
  assert.equal(teaching.lessons.size, 0);
  const rows = await exportRows(root, {nodes, edges:[], manifest, teaching});
  assert.equal(rows.practice_topics[0].path, '/topics/function-concepts/');
  assert.equal(rows.practice_topics[0].is_active, true);
  for (const name of ['practice_problems', 'practice_topic_problems', 'practice_routes', 'practice_steps', 'practice_step_nodes']) assert.deepEqual(rows[name], []);
});

test('planned types can organize an empty topic but cannot publish a practice exercise', async t => {
  const {root, write} = await fixture(t);
  const topic = structuredClone(source), id = 'function-concepts-q01';
  const lesson = {id, version:1, methods:[], routes:{}};
  topic.problems[id] = {label:'Q01', path:'/topics/function-concepts/q01/', types:[topic.groups[0].type], routes:{}};
  topic.groups[0].problems.push(id);
  await write('site/data/knowledge-next/topics/function-concepts.json', topic);
  await write('site/topics/function-concepts/q01/index.html', `<script id="practice-config" type="application/json">${JSON.stringify(lesson)}</script>`);
  await write(`server/shuxueshuo_server/tutor_demo/lessons/${id}.json`, {...lesson, problem:{statement:'验证待建设题型不能纳题'}});
  await assert.rejects(loadTeaching(root, nodes, manifest), /练习不能关联待建设题型/);
});

test('empty overview and catalog expose real knowledge/type links without exercise or progress controls', () => {
  const outputs = topicOverviewOutputs([source], nodes, indexHtml);
  const page = outputs.get('topics/function-concepts/index.html');
  assert.ok(page.includes(PAGE_MARKER));
  assert.match(page, /<title>函数的概念 · 高中专题 · 数学说<\/title>/);
  assert.match(page, /题目建设中/);
  for (const ref of [...source.knowledge, ...source.groups.map(group => group.type)]) assert.ok(page.includes(`href="/knowledge/${ref}/"`), ref);
  assert.equal((page.match(/class="type-group"/g) || []).length, 5);
  assert.doesNotMatch(page, /0\s*\/\s*0|已完成|开始答题|data-problem-id|progressbar|practice-config|\/api\//);
  const index = outputs.get('topics/index.html');
  assert.ok(index.includes('<section id="old-topic"><a href="/1/">基本不等式</a></section>'));
  assert.match(index, /href="\/topics\/function-concepts\/"/);
  assert.match(index, /题目建设中/);
  assert.deepEqual(topicOverviewOutputs([source], nodes, index), outputs);
  assert.throws(() => topicOverviewOutputs([source, source], nodes, index), /路径重复/);
});

test('topic builder is deterministic and check mode reports staleness without writing', async t => {
  const {root, write} = await fixture(t);
  const before = await fs.readFile(path.join(root, 'site/topics/index.html'), 'utf8');
  await assert.rejects(publishTopicOverviews({root, check:true}), /缺失或过期/);
  assert.equal(await fs.readFile(path.join(root, 'site/topics/index.html'), 'utf8'), before);
  assert.deepEqual(await publishTopicOverviews({root}), {changed:2});
  assert.deepEqual(await publishTopicOverviews({root, check:true}), {changed:0});
  const outputs = await generateTopicOverviews(root);
  assert.equal(await fs.readFile(path.join(root, 'site/topics/function-concepts/index.html'), 'utf8'), outputs.get('topics/function-concepts/index.html'));
  await write('site/topics/function-concepts/index.html', '<html>手写页面</html>');
  await assert.rejects(publishTopicOverviews({root}), /拒绝覆盖非生成专题页/);
});
