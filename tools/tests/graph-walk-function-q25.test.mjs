import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {buildStreamReplay} from '../../site/assets/graph-walk/walk-replay.mjs';
import {currentDecision, replayState, submitAnswer} from '../../site/assets/graph-walk/walk-state.mjs';
import {routeAnswerSummary} from '../../site/assets/graph-walk/stream-math-dom.mjs';
import {compileCourse} from '../build-graph-walk-topic.mjs';
import {loadSources} from '../lib/public-knowledge-sources.mjs';
import {exportContent} from '../export-public-knowledge.mjs';

const read = async path => JSON.parse(await fs.readFile(new URL(path, import.meta.url), 'utf8'));
const id = 'function-concepts-q25';
const bundle = await read(`../../site/data/graph-walk/${id}.json`);
const replay = await read(`../../site/data/graph-walk/${id}.replay.json`);
const route = bundle.routes['abstract-function-domain'];

test('Q25 is registered in the abstract-domain group with a stepwise deduction course', async () => {
  const source = await read(`../../site/data/graph-walk/${id}.source.json`);
  const topic = await read('../../site/data/knowledge-next/topics/function-concepts.json');
  const group = topic.groups.find(group => group.id === 'abstract-domain');
  assert.deepEqual(group.problems, [id]);
  assert.equal(source.page, '/topics/function-concepts/q25/');
  assert.equal(topic.problems[id].path, source.page);
  assert.equal(topic.problems[id].bundle, `/data/graph-walk/${id}.json`);
  assert.equal(bundle.problemId, id);
  assert.match(bundle.problem.text, /f\(x\).*\[-3,2\].*f\(2x-1\)/s);
  assert.deepEqual(bundle.intro.map(step => step.id), ['D1', 'D2', 'D3']);
  assert.equal(bundle.intro[0].interaction.type, 'choice');
  const d2 = bundle.intro.find(step => step.id === 'D2');
  assert.equal(d2.interaction.options[0].note, '未给出 $f$ 的解析式，只知道输入范围');
  assert.equal(d2.interaction.options[1].note, '给出了具体解析式，据此确定合法输入（或求参）');
  const evidence = await read(`../../site/data/graph-walk/${id}.evidence.json`);
  assert.deepEqual(evidence.lesson.goals.map(goal => goal.target_ref), ['/root/goals/0']);
  assert.equal(evidence.lesson.goals[0].primary, 'type-abstract-function-domain');
  const html = await fs.readFile(new URL('../../site/topics/function-concepts/q25/index.html', import.meta.url), 'utf8');
  assert.match(html, /"problemId":"function-concepts-q25"/);
  const {nodes} = await loadSources();
  for (const page of ['/topics/function-concepts/q25/../', '/topics/function-concepts/q25/extra/', '/topics/function-concepts/q25b/extra/']) {
    assert.throws(() => compileCourse({...source, page}, evidence, bundle.graph, nodes), /Invalid topic problem path/);
  }
});

test('Q25 keeps three local deduction cards and closes with the preimage interval', () => {
  assert.equal(route.method, 'method-input-domain-correspondence');
  const titles = route.steps.map(step => step.title);
  assert.deepEqual(titles.slice(0, 3), [
    '求 f 的输入范围',
    '列出目标函数的输入条件',
    '求目标函数的定义域',
  ]);
  assert.equal(route.steps[0].expected_answer.one_of[0], 'o2');
  assert.equal(route.steps[1].expected_answer.one_of[0], 'o1');
  assert.equal(route.steps[2].expected_answer.one_of[0], 'o1');
  for (const step of route.steps.slice(0, 3)) {
    const board = step.stem_board;
    assert.equal(board.layout, 'derivation');
    assert.equal(board.items.length, 2);
    assert.equal(board.connector, '⇒');
    assert.equal(typeof board.items[0].math, 'string');
    assert.equal(board.items[1].math, null);
    assert.doesNotMatch(JSON.stringify(board), /对照板|目标式|本式|所求|上轨|下轨/);
    const ref = step.stream_steps[0];
    const completed = bundle.stream.math_steps.find(math => math.step_id === ref.step_id && math.math_step_sha256 === ref.math_step_sha256).highlight;
    assert.equal(completed.layout, 'derivation');
    assert.equal(completed.caption, board.caption);
    assert.deepEqual(completed.items[0], board.items[0]);
    assert.equal(completed.items[1].label, board.items[1].label);
    assert.equal(typeof completed.items[1].math, 'string', 'completion fills the unknown in the same card');
  }
  assert.doesNotMatch(JSON.stringify(route.steps[0].stem_board), /2\\\\cdot x-1/, 'the first beat only asks about the known function');
  assert.match(route.steps[1].stem_board.items[0].note, /f\(2\\cdot x-1\)/);
  assert.match(route.steps[0].interaction.options[0].label, /函数值范围/);
  assert.match(route.steps[0].interaction.options[1].label, /输入范围/);
  assert.match(route.steps[1].interaction.options[0].label, /2\\cdot x-1/);
  assert.doesNotMatch(route.steps[0].interaction.options.map(option => option.label).join('\n'), /上轨|下轨|所求/);
  assert.equal(route.completion.status, 'verified');
  assert.equal(route.completion.answer.set.expression, 'Interval(-1, 3/2)');
  assert.match(route.completion.answer.set.latex, /\\frac\{3\}\{2\}/);
  assert.deepEqual(routeAnswerSummary(route.completion.answer), {
    label: '定义域：', formula: route.completion.answer.set.latex,
  });
  const boundary = route.steps[3];
  assert.equal(boundary.title, '复核边界');
  assert.equal(boundary.interaction.slots.length, 2);
  assert.ok(boundary.interaction.slots.every(slot => slot.label.startsWith('$x=')));
  assert.doesNotMatch(JSON.stringify(boundary), /None/);
});

test('Q25 student cards withhold each current answer and reject wrong choices without advancing', () => {
  const offset = bundle.intro.length;
  for (let index = 0; index < 3; index += 1) {
    const state = replayState(bundle, replay, offset + index);
    const decision = currentDecision(bundle, state);
    assert.equal(decision.id, route.steps[index].id);
    assert.doesNotMatch(decision.title, /\\/);
    const board = decision.stem_board;
    assert.equal(board.items[1].math, null);
    assert.doesNotMatch(JSON.stringify(board), /\\\\frac\{3\}\{2\}/);
    const correct = decision.expected_answer.one_of;
    for (const option of decision.interaction.options.filter(option => !correct.includes(option.value))) {
      const wrong = submitAnswer(bundle, state, {decision: decision.id, answer: option.value});
      assert.equal(currentDecision(bundle, wrong).id, decision.id);
      assert.equal(wrong.run.completed.length, state.run.completed.length);
      assert.equal(wrong.done, false);
    }
  }
});

test('Q25 publishes the same course and finishes the static replay', async () => {
  const data = await exportContent();
  const published = data.practice_problems.find(problem => problem.id === id);
  assert.equal(published.path, '/topics/function-concepts/q25/');
  assert.equal(published.problem_data._graph_walk.bundleVersion, bundle.bundleVersion);
  assert.equal(replay.actions.length, 7);
  const streamed = buildStreamReplay(bundle, {
    actions: replay.actions.slice(0, bundle.intro.findIndex(step => step.id === 'D3')),
    currentRoute: 'abstract-function-domain',
  });
  assert.deepEqual(streamed.actions, replay.actions);
  for (const actions of [replay, streamed]) {
    const state = replayState(bundle, actions);
    assert.equal(state.done, true);
    assert.equal(currentDecision(bundle, state), null);
  }
});
