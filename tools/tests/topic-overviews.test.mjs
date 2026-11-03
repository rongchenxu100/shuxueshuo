import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {topicPath, validateTopicSource, loadTeaching} from '../lib/public-knowledge-teaching.mjs';
import {exportRows} from '../lib/public-knowledge-export.mjs';
import {topicOverviewOutputs, INDEX_BEGIN, INDEX_END, PAGE_MARKER} from '../lib/topic-overview-html.mjs';
import {generateTopicOverviews, publishTopicOverviews} from '../build-topic-overviews.mjs';

const currentTopic = JSON.parse(await fs.readFile(new URL('../../site/data/knowledge-next/topics/function-concepts.json', import.meta.url), 'utf8'));
// Keep the P0 empty-topic compiler contract covered as the real topic grows.
const source = {...currentTopic, problems:{}, groups:currentTopic.groups.map(group => ({...group, problems:[]}))};
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

test('empty source keeps grouped knowledge and five type groups without exercises', () => {
  assert.equal(source.id, 'function-concepts');
  assert.equal(source.label, '函数的概念');
  assert.equal(topicPath(source), '/topics/function-concepts/');
  assert.deepEqual(source.knowledgeGroups.flatMap(group => group.refs), source.knowledge);
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

test('knowledge groups cannot lose, duplicate or invent knowledge links', () => {
  const edit = fn => { const copy = structuredClone(source); fn(copy); return copy; };
  assert.throws(() => validateTopicSource(edit(value => value.knowledgeGroups[0].refs.pop()), nodes), /未完整覆盖/);
  assert.throws(() => validateTopicSource(edit(value => value.knowledgeGroups[0].refs.push('missing')), nodes), /未完整覆盖/);
  assert.throws(() => validateTopicSource(edit(value => value.knowledgeGroups[1].refs.push(value.knowledge[0])), nodes), /引用重复/);
  assert.throws(() => validateTopicSource(edit(value => value.knowledgeGroups[1].id = value.knowledgeGroups[0].id), nodes), /分组重复/);
  assert.throws(() => validateTopicSource(edit(value => value.knowledgeGroups[0].refs = []), nodes), /分组无效/);
});

test('knowledge headings organize real links and flat topics remain supported', () => {
  const page = topicOverviewOutputs([source], nodes, indexHtml).get('topics/function-concepts/index.html');
  const knowledge = page.slice(page.indexOf('id="knowledge-map"'));
  for (const group of source.knowledgeGroups) {
    const section = knowledge.match(new RegExp(`<section class="topic-knowledge-group" aria-labelledby="knowledge-${group.id}">([\\s\\S]*?)</section>`));
    assert.ok(section, group.id);
    for (const ref of group.refs) assert.ok(section[1].includes(`href="/knowledge/${ref}/"`), ref);
  }
  assert.equal((knowledge.match(/<li>/g) || []).length, source.knowledge.length);
  const flat = structuredClone(source);
  delete flat.knowledgeGroups;
  const flatPage = topicOverviewOutputs([flat], nodes, indexHtml).get('topics/function-concepts/index.html');
  assert.doesNotMatch(flatPage, /class="topic-knowledge-group"/);
  for (const ref of flat.knowledge) assert.ok(flatPage.includes(`href="/knowledge/${ref}/"`));
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
  assert.ok(page.indexOf('class="bank"') < page.indexOf('id="knowledge-map"'));
  assert.match(page, /href="#knowledge-map"/);
  assert.doesNotMatch(page, /0\s*\/\s*0|已完成|开始答题|data-problem-id|progressbar|practice-config|\/api\//);
  const index = outputs.get('topics/index.html');
  assert.ok(index.includes('<section id="old-topic"><a href="/1/">基本不等式</a></section>'));
  assert.match(index, /href="\/topics\/function-concepts\/"/);
  assert.match(index, /题目建设中/);
  assert.deepEqual(topicOverviewOutputs([source], nodes, index), outputs);
  assert.throws(() => topicOverviewOutputs([source, source], nodes, index), /路径重复/);
});

test('overview prefers original problem statement over short labels', () => {
  const topic = structuredClone(source);
  const id = 'function-concepts-q15';
  topic.groups[0].problems = [id];
  topic.problems[id] = {
    label: '求函数的定义域 · Q15',
    path: '/topics/function-concepts/q15/',
    statement: '15. 函数$f(x)=\\frac{\\sqrt{x-1}}{x-2}$的定义域为____',
    types: [topic.groups[0].type],
  };
  // Planned types cannot publish practice; mark active for overview rendering only.
  const activeNodes = nodes.map(node => node.id === topic.groups[0].type ? {...node, status:'active'} : node);
  const page = topicOverviewOutputs([topic], activeNodes, indexHtml).get('topics/function-concepts/index.html');
  assert.match(page, /data-problem-id="function-concepts-q15"/);
  assert.match(page, /定义域为/);
  assert.doesNotMatch(page, /problem-stem">求函数的定义域 · Q15/);
  assert.ok(page.includes('katex') || page.includes('\\frac') === false);
  assert.ok(page.indexOf('class="bank"') < page.indexOf('id="knowledge-map"'));
});

test('real topic keeps all five courses and their knowledge links', async () => {
  const ids = ['function-concepts-q15', 'function-concepts-q01', 'function-concepts-q22-v2', 'function-concepts-q04', 'function-concepts-q12', 'function-concepts-q23b-v2'];
  assert.deepEqual(currentTopic.groups.find(group => group.id === 'domain').problems, ids);
  const comparison = 'function-concepts-q20-v2';
  const abstract = ['function-concepts-q25', 'function-concepts-q26', 'function-concepts-abstract-mixed-q03', 'function-concepts-parameter-variant02'];
  assert.deepEqual(currentTopic.groups.find(group => group.id === 'equality').problems, [comparison, 'function-concepts-q19']);
  assert.deepEqual(currentTopic.groups.find(group => group.id === 'abstract-domain').problems, abstract);
  const evaluation = currentTopic.groups.find(group => group.id === 'evaluation').problems;
  const range = currentTopic.groups.find(group => group.id === 'range').problems;
  assert.equal(evaluation.length, 5);
  assert.equal(range.length, 12);
  assert.deepEqual(Object.keys(currentTopic.problems).sort(), [...ids, comparison, 'function-concepts-q19', ...abstract, ...evaluation, ...range].sort());
  const page = (await generateTopicOverviews()).get('topics/function-concepts/index.html');
  assert.equal((page.match(/data-problem-id=/g) || []).length, 29);
  const equality = page.slice(page.indexOf('data-problem-id="function-concepts-q20-v2"'));
  assert.doesNotMatch(equality.slice(0, 1200), /【变式】/);
  assert.match(equality.slice(0, 1200), /class="problem-options"/);
  assert.match(equality.slice(0, 2500), /class="problem-option"/);
  assert.ok(page.indexOf(`data-problem-id="${ids[0]}"`) < page.indexOf(`data-problem-id="${ids[1]}"`));
  assert.ok(page.indexOf(`data-problem-id="${ids[1]}"`) < page.indexOf(`data-problem-id="${ids[2]}"`));
  assert.ok(page.indexOf(`data-problem-id="${ids[2]}"`) < page.indexOf(`data-problem-id="${ids[3]}"`));
  assert.ok(page.indexOf(`data-problem-id="${ids[3]}"`) < page.indexOf(`data-problem-id="${ids[4]}"`));
  assert.ok(page.indexOf(`data-problem-id="${ids[4]}"`) < page.indexOf(`data-problem-id="${ids[5]}"`));
  for (const [index, suffix] of ['q15', 'q01', 'q22', 'q04', 'q12', 'q23b'].entries()) {
    assert.match(page, new RegExp(`href="/topics/function-concepts/${suffix}/"`));
    assert.equal(currentTopic.problems[ids[index]].runtime, 'graph-walk');
  }
  assert.match(page, /x\+4/);
  assert.match(page, /x\^2-1/);
  assert.match(page, /sqrt\{x-1\}/);
  assert.match(page, /kx\^\{2\}/);
  assert.match(page, /5 个题型 · 29 道题/);
  assert.match(page, /href="\/topics\/function-concepts\/q20\/"/);
  assert.match(page, /href="\/topics\/function-concepts\/q19\/"/);
  assert.ok(page.indexOf(`data-problem-id="${comparison}"`) < page.indexOf('data-problem-id="function-concepts-q19"'));
  assert.match(page, /表示同一个函数/);
  assert.equal(currentTopic.problems[comparison].runtime, 'graph-walk');
  assert.deepEqual(currentTopic.problems[comparison].types, ['type-function-equality']);
  assert.ok(page.indexOf(`data-problem-id="${abstract[0]}"`) < page.indexOf(`data-problem-id="${abstract[1]}"`));
  for (const id of abstract) {
    assert.ok(page.includes(`href="${currentTopic.problems[id].path}"`));
    assert.equal(currentTopic.problems[id].runtime, 'graph-walk');
    assert.deepEqual(currentTopic.problems[id].types, ['type-abstract-function-domain']);
  }
  assert.equal(currentTopic.problems['function-concepts-q02'], undefined, 'Q2 validates reuse without adding a duplicate topic exercise');
  for (const ref of currentTopic.knowledge) {
    await fs.access(new URL(`../../site/knowledge/${ref}/index.html`, import.meta.url));
    assert.ok(page.includes(`href="/knowledge/${ref}/"`), ref);
  }
  const knowledge = page.slice(page.indexOf('id="knowledge-map"'));
  for (const ref of ['set-intersection-union', 'function-range-extrema', 'function-monotonicity', 'quadratic-function-properties', 'reciprocal-sum-function']) {
    assert.ok(knowledge.includes(`href="/knowledge/${ref}/"`), ref);
  }
  assert.doesNotMatch(knowledge, /href="\/knowledge\/(?:floor-function|piecewise-function)\//);
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
