import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {createRequire} from 'node:module';
import {compileCourse, generateCourse} from '../build-graph-walk-topic.mjs';
import {loadSources, repoRoot} from '../lib/public-knowledge-sources.mjs';
import {nativePracticeContract} from '../lib/graph-walk-practice.mjs';
import {createState, currentDecision, submitAnswer, replayState, extendStreamBundle, gradeDecision, graphState, streamGraphState} from '../../site/assets/graph-walk/walk-state.mjs';
import {methodAnswer, methodCardsHTML, projectMethodAnswer} from '../../site/assets/graph-walk/method-cards.mjs';
import {connectedMethodAnswer, mountMethodConnections} from '../../site/assets/graph-walk/method-connections.mjs';
import {formulaAnswerHTML} from '../../site/assets/graph-walk/formula-answer.mjs';
import {buildStreamReplay} from '../../site/assets/graph-walk/walk-replay.mjs';
import {routeAnswerSummary} from '../../site/assets/graph-walk/stream-math-dom.mjs';

const read = async path => JSON.parse(await fs.readFile(`${repoRoot}/${path}`, 'utf8'));
const sourcePath = 'site/data/graph-walk/function-representations-formula-a0.source.json';
const source = await read(sourcePath), evidence = await read(source.evidence);
const graph = await read('site/knowledge/graph.json');
const {nodes} = await loadSources();
const {bundle, replay} = compileCourse(source, evidence, graph, nodes);
const route = bundle.routes['function-substitution'];
const katex = createRequire(import.meta.url)('../../site/assets/practice/vendor/katex-0.18.9/katex.min.js');

test('A3 preserves two independent completions and uses each goal’s actual method in replay and graph traces', async () => {
  const source = await read('site/data/graph-walk/function-representations-b05-v3.source.json');
  const evidence = await read(source.evidence);
  const {bundle, replay} = compileCourse(source, evidence, graph, nodes);
  const state = replayState(bundle, replay), route = Object.values(bundle.routes)[0];
  assert.equal(state.done, true);
  assert.equal(replayState(bundle, buildStreamReplay(bundle)).done, true);
  assert.deepEqual(route.methods, ['method-function-matching', 'method-function-evaluation']);
  assert.deepEqual(route.goal_completions.map(row => row.target_ref), ['/root/goals/0', '/root/goals/1']);
  assert.equal(route.goal_completions[0].answer.value.expression, '2');
  assert.equal(route.goal_completions[1].answer.expression.expression, 't**2 + 2');
  assert.equal(route.goal_completions[1].answer.determined_domain.expression, 'Reals');
  const valueSteps = route.steps.filter(step => step.target_ref === '/root/goals/0');
  assert.equal(valueSteps.length, 2);
  assert.match(valueSteps[0].question, /不必先求解析式/);
  assert.ok(bundle.intro[0].interaction.options.some(option => option.label === '求出给定输入对应的函数值'));
  const d3 = route.steps.find(step => step.id === 'goal-2-D3');
  assert.equal(d3.route_id, 'function-matching');
  assert.equal(gradeDecision(d3, methodAnswer(d3, 'matching')).status, 'passed');
  const confirmed = streamGraphState(bundle, state);
  assert.equal(confirmed.nodes['method-function-matching'], 'confirmed');
  assert.equal(confirmed.nodes['method-function-evaluation'], 'confirmed');
  assert.ok(confirmed.calls.some(call => call.method === 'method-function-matching'));
  for (const step of route.steps) for (const board of [step.stem_board, step.completion_board].filter(Boolean)) {
    for (const item of board.items) if (item.math) katex.renderToString(item.math, {throwOnError: true});
  }
  const contract = nativePracticeContract(bundle);
  assert.equal(contract.routes['function-evaluation'].steps.find(step => step.id === 'goal-2-D3').route_id, 'function-matching');
});

test('A3 opens both actual routes on the earlier root and affine questions', async () => {
  for (const id of ['b05-r2', 'w02-r2', 'w09-r2', 'b05-v2-r5']) {
    const source = await read(`site/data/graph-walk/function-representations-${id}.source.json`);
    const {bundle} = compileCourse(source, await read(source.evidence), graph, nodes);
    const d3 = bundle.intro.find(step => step.id === 'D3');
    for (const branch of ['matching', 'substitution']) {
      assert.equal(gradeDecision(d3, methodAnswer(d3, branch)).status, 'passed');
      const replay = buildStreamReplay(bundle, {replayRoute: `function-${branch}`});
      assert.equal(replayState(bundle, replay).done, true);
    }
    assert.deepEqual(bundle.routes['function-matching'].completion.answer, bundle.routes['function-substitution'].completion.answer);
    assert.doesNotMatch(methodCardsHTML(d3, methodAnswer(d3, 'matching'), false), /配凑.*暂未开放/);
  }
});

for (const [name, expression, endpoint, preferred] of [
  ['w04', 't**2 - 1', 1, 'function-matching'],
  ['w11', 't**2 + 4*t', -2, 'function-substitution'],
]) {
  test(`root course ${name} preserves both routes and its closed endpoint in grading and replay`, async () => {
    const source = await read(`site/data/graph-walk/function-representations-${name}.source.json`);
    const evidence = await read(source.evidence);
    const {bundle, replay} = compileCourse(source, evidence, graph, nodes);
    assert.equal(evidence.provenance.source_admission, 'authored_topic');
    assert.equal(source.preferredRoute, preferred);
    assert.equal(replayState(bundle, replay).run.route, preferred);
    assert.deepEqual(Object.keys(bundle.routes).sort(), ['function-matching', 'function-substitution']);
    assert.deepEqual(bundle.routes['function-matching'].completion.answer, bundle.routes['function-substitution'].completion.answer);
    const d3 = bundle.intro.find(step => step.id === 'D3');
    const streamed = extendStreamBundle(bundle, evidence.stream, '/root/goals/0', graph);
    const contract = nativePracticeContract(bundle);
    for (const branch of ['matching', 'substitution']) {
      const routeId = `function-${branch}`, route = bundle.routes[routeId];
      assert.equal(gradeDecision(d3, methodAnswer(d3, branch)).status, 'passed');
      assert.equal(replayState(bundle, buildStreamReplay(bundle, {replayRoute: routeId})).done, true);
      assert.equal(replayState(streamed, buildStreamReplay(streamed, {replayRoute: routeId})).done, true);
      assert.equal(route.steps.length, 4);
      assert.equal(contract.routes[routeId].steps.length, 4);
      const answer = route.completion.answer;
      assert.equal(answer.expression.expression, expression);
      assert.equal(answer.determined_domain.expression, `Interval(${endpoint}, oo)`);
      assert.equal(answer.source_domain.expression, 'Interval(0, oo)');
      assert.equal(answer.declared_domain, null);
      for (const step of route.steps) {
        assert.equal(step.stem_board.items[1].math, null);
        for (const option of step.interaction.options) {
          assert.equal(gradeDecision(step, option.value).status, step.expected_answer.one_of.includes(option.value) ? 'passed' : 'wrong');
        }
        for (const board of [step.stem_board, step.completion_board]) {
          for (const item of board.items) if (item.math) katex.renderToString(item.math, {throwOnError: true});
        }
      }
      const last = route.steps.at(-1), correct = last.expected_answer.one_of[0];
      const range = last.answer_completion.ranges.find(item => item.value === correct);
      assert.equal(range.left, endpoint);
      assert.equal(range.left_closed, true);
      assert.equal(range.right, null);
      assert.equal(range.condition, `x\\geq${endpoint}`);
      assert.ok(last.answer_completion.ranges.some(item => item.left === 0 && item.value !== correct));
      assert.ok(last.answer_completion.ranges.some(item => item.left === endpoint && !item.left_closed));
      const completed = formulaAnswerHTML(last, correct, false);
      assert.match(completed, /is-complete/);
      assert.match(completed, /<circle/);
      assert.doesNotMatch(completed, /data-choice=/);
      katex.renderToString(last.answer_completion.formula, {throwOnError: true});
      for (const item of last.answer_completion.ranges) katex.renderToString(item.condition, {throwOnError: true});
    }
  });
}

test('A2 fractional substitution preserves its excluded point in grading, preview and replay', async () => {
  const source = await read('site/data/graph-walk/function-representations-b05-v1.source.json');
  const evidence = await read(source.evidence);
  assert.equal(evidence.provenance.source_admission, 'authored_topic');
  const {bundle, replay} = compileCourse(source, evidence, graph, nodes);
  assert.equal(replayState(bundle, replay).done, true);
  const streamed = extendStreamBundle(bundle, evidence.stream, '/root/goals/0', graph);
  assert.equal(replayState(streamed, buildStreamReplay(streamed, {actions: replay.actions.slice(0, 2)})).done, true);
  const route = bundle.routes['function-substitution'];
  assert.equal(route.steps.length, 4);
  assert.equal(route.steps[0].title, '换元后，哪些数不能取');
  const expected = (await read('internal/senior-high/authored-courses/function-formula-a2-20261101/b05-v1.json')).expected;
  assert.equal(route.completion.answer.expression.expression, expected.expression);
  assert.equal(route.completion.answer.determined_domain.expression, expected.determined_domain);
  assert.equal(route.completion.answer.source_domain.expression, 'Union(Interval.open(-oo, -1), Interval.open(-1, oo))');
  for (const step of route.steps) {
    assert.equal(gradeDecision(step, step.expected_answer.one_of[0]).status, 'passed');
    for (const option of step.interaction.options) {
      if (!step.expected_answer.one_of.includes(option.value)) assert.equal(gradeDecision(step, option.value).status, 'wrong');
    }
    for (const board of [step.stem_board, step.completion_board]) {
      for (const item of board.items) if (item.math) katex.renderToString(item.math, {throwOnError: true});
    }
  }
  const step = route.steps.at(-1), answer = step.expected_answer.one_of[0];
  const view = step.answer_completion, correct = view.ranges.find(row => row.value === answer);
  assert.deepEqual(correct.excluded, [1]);
  assert.equal(correct.condition, String.raw`x\ne1`);
  const wrong = view.ranges.find(row => row.excluded?.[0] === -1);
  assert.ok(wrong, 'the original denominator exclusion is a distinct distractor');
  const initial = formulaAnswerHTML(step, null);
  assert.doesNotMatch(initial, /class="gw-formula-excluded"/);
  const completed = formulaAnswerHTML(step, answer, false);
  const draft = formulaAnswerHTML({...step, expected_answer: {}}, wrong.value);
  assert.match(completed, /is-complete/);
  assert.doesNotMatch(completed, /data-choice=/);
  const point = html => html.match(/class="gw-formula-excluded" cx="([^"]+)"/)[1];
  assert.notEqual(point(completed), point(draft));
  assert.equal((completed.match(/class="gw-formula-excluded"/g) || []).length, 1);
  assert.match(completed, /fill="white"/);
  for (const range of view.ranges) katex.renderToString(range.condition, {throwOnError: true});
  katex.renderToString(view.formula, {throwOnError: true});
  assert.equal(nativePracticeContract(bundle).routes['function-substitution'].steps.length, 4);
  const d3 = bundle.intro.find(row => row.id === 'D3');
  const map = methodCardsHTML(d3, methodAnswer(d3, 'substitution'), false);
  assert.match(map, /gw-method-pair-arrow/);
  assert.equal((map.match(/data-method-map-row/g) || []).length, 4);
});

for (const [id, expression] of [['b05', 't**2 - 1'], ['w02', 't**2 + 6'], ['w09', 't**2 - 8*t + 12']]) {
  test(`A1 ${id} keeps the shared selection, grading, replay and whole-real answer`, async () => {
    const source = await read(`site/data/graph-walk/function-representations-${id}.source.json`);
    const evidence = await read(source.evidence);
    assert.equal(evidence.provenance.source_admission, 'authored_topic');
    const {bundle, replay} = compileCourse(source, evidence, graph, nodes);
    assert.deepEqual(Object.keys(bundle.routes), ['function-substitution']);
    assert.equal(replayState(bundle, replay).done, true);
    const route = bundle.routes['function-substitution'];
    assert.equal(route.steps.length, 4);
    assert.equal(route.steps[0].title, '把函数的输入换成新变量');
    assert.equal(route.completion.answer.expression.expression, expression);
    assert.equal(route.completion.answer.determined_domain.expression, 'Reals');
    assert.equal(route.completion.answer.source_domain.expression, 'Reals');
    for (const step of route.steps) {
      assert.equal(gradeDecision(step, step.expected_answer.one_of[0]).status, 'passed');
      for (const option of step.interaction.options.filter(row => !step.expected_answer.one_of.includes(row.value))) {
        assert.equal(gradeDecision(step, option.value).status, 'wrong');
      }
      for (const board of [step.stem_board, step.completion_board]) {
        for (const item of board.items) if (item.math) katex.renderToString(item.math, {throwOnError: true});
      }
    }
    const step = route.steps.at(-1), answer = step.expected_answer.one_of[0];
    const range = step.answer_completion.ranges.find(row => row.value === answer);
    assert.equal(range.left, null);
    assert.equal(range.right, null);
    const completed = formulaAnswerHTML(step, answer, false);
    assert.match(completed, /is-complete/);
    assert.match(completed, /M24,42 H576/);
    assert.doesNotMatch(completed, /<circle|data-choice=|范围外/);
    katex.renderToString(step.answer_completion.formula, {throwOnError: true});
    const d3 = bundle.intro.find(row => row.id === 'D3');
    const map = methodCardsHTML(d3, methodAnswer(d3, 'substitution'), false);
    assert.equal((map.match(/gw-method-pair/g) || []).length >= 1, true);
    assert.equal((map.match(/data-card-method=/g) || []).length, 0);
    assert.match(map, /gw-method-pair-arrow/);
    assert.match(map, /已知复合函数的解析式/);
    assert.match(map, /本题选择/);
    assert.equal(nativePracticeContract(bundle).routes['function-substitution'].steps.length, 4);
  });
}

test('pairing cards do not require SVG edge geometry', () => {
  const dispose = mountMethodConnections({querySelectorAll: () => [{
    querySelectorAll: () => [{querySelector: () => null}],
  }]});
  dispose();
});
test('A0 preview retains unknown-function source and one implemented method in its own topic', async () => {
  assert.equal(source.preview, true);
  assert.equal(source.topicHref, '/topics/function-representations/');
  assert.deepEqual(Object.keys(bundle.routes), ['function-substitution']);
  assert.equal(route.method, 'method-function-substitution');
  assert.deepEqual(bundle.intro.map(step => step.id), ['D1', 'D2', 'D3']);
  assert.equal(bundle.intro[2].interaction.type, 'method_cards');
  assert.equal(bundle.intro[2].interaction.layout, 'connections');
  assert.equal(route.steps.length, 4);
  const outputs = await generateCourse({sourcePath});
  const html = outputs.get(`site${source.page}index.html`);
  assert.match(html, /"preview":true/);
  assert.match(html, /不提交练习记录/);
  assert.throws(() => compileCourse({...source, preview: false}, evidence, graph, nodes), /Invalid topic problem path/);
  assert.throws(() => compileCourse({...source, page: '/topics/function-representations/q01/'}, evidence, graph, nodes), /Invalid topic problem path/);
  const topic = await read('site/data/knowledge-next/topics/function-representations.json');
  assert.equal(topic.problems[source.problemId], undefined, 'the lab preview is not a formal exercise');
  const formalPath = 'site/data/graph-walk/function-representations-b05-v2-r4.source.json';
  const formalSource = await read(formalPath);
  assert.equal(topic.problems[formalSource.problemId], undefined, 'the previous formal revision remains archived');
  assert.equal(topic.problems['function-representations-b05-v2-r5'].path, formalSource.page);
  const formal = compileCourse(formalSource, evidence, graph, nodes);
  assert.notEqual(formal.bundle.problemId, bundle.problemId);
  assert.deepEqual(formal.bundle.routes, bundle.routes);
  assert.equal(replayState(formal.bundle, formal.replay).done, true);
  const formalOutputs = await generateCourse({sourcePath: formalPath});
  const formalHtml = formalOutputs.get(`site${formalSource.page}index.html`);
  assert.doesNotMatch(formalHtml, /"preview":true|不提交练习记录/);
  assert.match(formalHtml, /登录后保存已确认的练习记录/);
});

test('formula selection connects a source cue to a method without leaking or inventing routes', () => {
  const d3 = bundle.intro.find(step => step.id === 'D3');
  assert.equal(d3.interaction.methods.length, 5);
  assert.equal(d3.interaction.methods.filter(method => method.route).length, 1);
  const initial = methodCardsHTML(d3, null);
  assert.match(initial, /选法配对卡/);
  assert.match(initial, /已知复合函数的解析式/);
  assert.match(initial, /data-method-cue="composite_input"/);
  assert.equal((initial.match(/data-method-map-row/g) || []).length, 4, 'each authored cue becomes one pairing card');
  assert.match(initial, /gw-method-pair-arrow/);
  assert.equal((initial.match(/data-card-method=/g) || []).length, 5, 'all five methods remain selectable');
  assert.equal((initial.match(/<button/g) || []).length, 5, 'only the methods are selectable');
  assert.doesNotMatch(initial, /aria-pressed="true"|暂未开放|本题可用|本题推荐|先令/);
  const good = methodAnswer(d3, 'substitution');
  assert.equal(gradeDecision(d3, good).status, 'passed');
  for (const method of ['coefficients', 'system', 'assignment']) {
    assert.equal(gradeDecision(d3, {...good, method}).status, 'wrong');
  }
  assert.equal(gradeDecision(d3, {...good, method: 'matching'}).status, 'uncovered');
  const bad = {...good, checks: ['function_type'], confirmed: 99};
  assert.equal(gradeDecision(d3, bad).status, 'wrong');
  assert.equal(gradeDecision(d3, {...bad, method: 'matching'}).status, 'wrong');
  const pending = projectMethodAnswer(d3, bad);
  assert.deepEqual(pending.checks, bad.checks, 'a wrong draft must not reveal the right cue before submission');
  assert.equal(pending.confirmed, 0);
  assert.match(methodCardsHTML(d3, pending), /已选择/);
  for (const [method, status] of [['substitution', 'passed'], ['matching', 'uncovered'], ['coefficients', 'wrong'], ['system', 'wrong'], ['assignment', 'wrong']]) {
    assert.equal(gradeDecision(d3, connectedMethodAnswer(d3, method)).status, status, 'a method click supplies its authored cue, not the expected answer');
  }
  const completed = methodCardsHTML(d3, good, false);
  assert.match(completed, /配凑法也适用/);
  assert.match(completed, /先令/);
  assert.equal((completed.match(/data-method-map-row/g) || []).length, 4, 'completion preserves the full pairing map');
  assert.match(completed, /✓ 本题选择/);
  assert.doesNotMatch(completed, /<button/);
  let state = createState(bundle);
  for (const action of replay.actions.slice(0, 2)) state = submitAnswer(bundle, state, action);
  for (const method of ['coefficients', 'matching']) {
    const rejected = submitAnswer(bundle, state, {decision: 'D3', answer: {...good, method}});
    assert.equal(currentDecision(bundle, rejected).id, 'D3');
  }
  state = submitAnswer(bundle, state, {decision: 'D3', answer: good});
  assert.equal(graphState(bundle, state).nodes['rule-function-formula-method'], 'confirmed');
  assert.ok(graphState(bundle, state).edges['rule-function-formula-method|selects|method-function-substitution']);
});

test('A0 blocks every wrong choice and restores every prefix; AI replay leaves student state alone', () => {
  let state = createState(bundle);
  for (const [index, action] of replay.actions.entries()) {
    const step = currentDecision(bundle, state);
    assert.equal(step.id, action.decision);
    const saved = structuredClone(state);
    assert.equal(replayState(bundle, replay).done, true);
    assert.deepEqual(state, saved);
    if (step.interaction.type === 'choice') {
      const wrong = step.interaction.options.find(option => !step.expected_answer.one_of.includes(option.value));
      assert.ok(wrong);
      const rejected = submitAnswer(bundle, state, {decision: step.id, answer: wrong.value});
      assert.equal(rejected.lastFeedback.status, 'wrong');
      assert.equal(currentDecision(bundle, rejected).id, step.id);
      assert.equal(rejected.done, false);
    }
    if (step.stem_board) assert.equal(step.stem_board.items[1].math, null);
    state = submitAnswer(bundle, state, action);
    assert.equal(state.lastFeedback.status, 'passed');
    const restored = replayState(bundle, {...replay, status: 'partial', actions: replay.actions.slice(0, index+1)});
    assert.equal(restored.done, state.done);
    assert.equal(currentDecision(bundle, restored)?.id, currentDecision(bundle, state)?.id);
  }
  assert.equal(state.done, true);
});

test('A0 photo projection, static course and native grading share the same four decisions', () => {
  const streamed = extendStreamBundle(bundle, evidence.stream, '/root/goals/0', graph);
  const photoReplay = buildStreamReplay(streamed, {actions: replay.actions.slice(0, 2)});
  assert.deepEqual(photoReplay.actions, replay.actions);
  assert.equal(replayState(streamed, photoReplay).done, true);
  assert.equal(nativePracticeContract(bundle).routes['function-substitution'].steps.length, 4);
  for (const part of route.steps) {
    for (const board of [part.stem_board, part.completion_board]) {
      for (const item of board.items) if (item.math) katex.renderToString(item.math, {throwOnError: true});
    }
  }
});

test('A0 answer cannot replace the determined input range with the original variable domain', () => {
  const answer = route.completion.answer;
  assert.equal(answer.source_domain.expression, 'Interval(0, oo)');
  assert.equal(answer.determined_domain.expression, 'Interval(1, oo)');
  assert.equal(answer.declared_domain, null);
  const summary = routeAnswerSummary(answer);
  assert.match(summary.formula, /1,/);
  assert.doesNotMatch(summary.formula, /0,/);
  katex.renderToString(summary.formula, {throwOnError: true});
  assert.equal(routeAnswerSummary({...answer, determined_domain: null}), null);
  assert.match(routeAnswerSummary({...answer, status: 'insufficient_information'}).label, /不足/);
  const free = {latex: '\\left\\{0\\right\\}', expression: '{0}', exact: '{0}'};
  const partial = routeAnswerSummary({...answer, status: 'insufficient_information', free_domain: free});
  assert.match(partial.formula, /不能唯一确定/);
  katex.renderToString(partial.formula, {throwOnError: true});
  const abstract = routeAnswerSummary({...answer, status: 'insufficient_information', free_domain: free,
    declared_domain: null, determined_domain: null, requested_domain: null,
    domain_identity: 'declared_symmetric_domain'});
  assert.match(abstract.formula, /D\\setminus/);
  katex.renderToString(abstract.formula, {throwOnError: true});
  assert.equal(routeAnswerSummary({...answer, free_domain: {}}), null);
  const value = {kind: 'find_value', result_type: 'scalar_value', defined: true, domain: free,
    expression: null, is_constant: null};
  assert.equal(routeAnswerSummary({...value, status: 'complete', value: free}).label, '函数值：');
  assert.match(routeAnswerSummary({...value, status: 'insufficient_information', value: null}).label, /不能唯一确定/);
  assert.equal(routeAnswerSummary({...value, status: 'insufficient_information', value: free}), null);
});

test('complete-answer preview follows each draft and only completion uses confirmed styling', () => {
  const step = route.steps.at(-1), view = step.answer_completion;
  assert.equal(step.title, '写出完整答案');
  assert.equal(step.submit_label, '确认答案');
  assert.match(view.formula, /^f\(x\)=/);
  const initial = formulaAnswerHTML(step, null);
  assert.match(initial, /选择范围/);
  assert.match(initial, /<details[^>]*><summary>为什么这个范围都能取到/);
  assert.doesNotMatch(initial, /is-complete|gw-formula-range-slot is-filled|<g class="gw-formula-range"/);
  assert.equal((initial.match(/data-choice=/g) || []).length, 4);
  for (const option of step.interaction.options) {
    const selected = view.ranges.find(range => range.value === option.value);
    const draft = formulaAnswerHTML({...step, expected_answer: {}}, option.value);
    assert.match(draft, /gw-formula-range-slot is-filled/);
    assert.ok(draft.includes(selected.condition.replaceAll('>', '&gt;')));
    assert.match(draft, /当前选择 · 确认后检查答案/);
    assert.doesNotMatch(draft, /is-complete/);
    katex.renderToString(selected.condition, {throwOnError: true});
    const grade = gradeDecision(step, option.value);
    if (grade.status === 'wrong') assert.equal(grade.message, option.feedback);
    if (selected.left !== null || selected.right !== null) {
      assert.ok(draft.includes(`fill="${selected.left_closed || selected.right_closed ? 'currentColor' : 'white'}"`));
    }
  }
  const completed = formulaAnswerHTML(step, step.expected_answer.one_of[0], false);
  assert.match(completed, /is-complete/);
  assert.match(completed, /范围，要随解析式一起保留/);
  assert.doesNotMatch(completed, /data-choice=|前面已经得到/);
  katex.renderToString(view.formula, {throwOnError: true});
});

for (const name of ['b04', 'w01', 'w12', 'b04-v', 'w10']) {
  test(`B ${name} keeps the original goal, full candidates, coefficient skill and replay`, async () => {
    const source = await read(`site/data/graph-walk/function-representations-${name}.source.json`);
    const evidence = await read(source.evidence);
    const {bundle, replay} = compileCourse(source, evidence, graph, nodes);
    const route = bundle.routes['function-coefficients'];
    assert.equal(replayState(bundle, replay).done, true);
    assert.equal(replayState(bundle, buildStreamReplay(bundle)).done, true);
    const d3 = bundle.intro.find(step => step.id === 'D3');
    assert.equal(gradeDecision(d3, methodAnswer(d3, 'coefficients')).status, 'passed');
    assert.match(methodCardsHTML(d3, methodAnswer(d3, 'coefficients'), false), /已知函数类型/);
    const streamed = extendStreamBundle(bundle, evidence.stream, '/root/goals/0', graph);
    assert.equal(replayState(streamed, buildStreamReplay(streamed, {actions: replay.actions.slice(0, 2)})).done, true);
    const state = replayState(bundle, replay);
    const confirmed = streamGraphState(bundle, state);
    assert.ok(confirmed.calls.some(call => call.ref === 'skill-polynomial-coefficient-comparison' || call.skill === 'skill-polynomial-coefficient-comparison' || call.public_ref === 'skill-polynomial-coefficient-comparison'));
    const answer = route.completion.answer;
    assert.equal(answer.candidates.length, ['b04','w01','w12'].includes(name) ? 2 : 1);
    const verification = route.steps.at(-2);
    assert.equal(verification.title, answer.candidates.length === 1 ? '把结果代回检查' : '把每个结果代回检查');
    for (const step of bundle.stream.math_steps) {
      const math = [...step.explanation.matchAll(/\$([^$]+)\$/g)].map(match => match[1]);
      assert.ok(math.length > 0, `${step.title} must contain its actual mathematical working`);
      for (const expression of math) katex.renderToString(expression, {throwOnError: true});
    }
    if (['b04-v', 'w10'].includes(name)) {
      const expansion = route.steps[1];
      assert.equal(expansion.stem_board.condition_groups.length, 2);
      assert.equal(expansion.stem_board.items[1].math, null);
      assert.deepEqual(expansion.completion_board.condition_groups, expansion.stem_board.condition_groups);
      assert.deepEqual(streamed.routes['function-coefficients'].steps[1].stem_board, expansion.stem_board);
      for (const condition of expansion.stem_board.condition_groups) {
        katex.renderToString(condition.math, {throwOnError: true});
      }
    }
    const summary = routeAnswerSummary(answer);
    assert.ok(summary);
    if (name === 'b04') {
      assert.equal(answer.kind, 'find_value');
      assert.equal(summary.formula, '1');
    } else if (name === 'w10') {
      assert.equal(answer.kind, 'find_range');
      assert.match(summary.label, /解集/);
      assert.equal(answer.set.expression, 'Interval.open(0, 7/3)');
      const inequality = route.steps.at(-1);
      assert.equal(inequality.graph.kind, 'quadratic');
      assert.equal(inequality.graph.params.markSign, undefined);
      assert.deepEqual(inequality.completion_graphs.map(picture => picture.kind), ['quadratic', 'number_line']);
      const streamedInequality = streamed.routes['function-coefficients'].steps.at(-1);
      assert.deepEqual(streamedInequality.graph, inequality.graph);
      assert.deepEqual(streamedInequality.completion_graphs, inequality.completion_graphs);
    } else {
      assert.equal(answer.kind, 'find_function_formula');
      if (answer.candidates.length === 2) assert.match(summary.formula, /或/);
    }
    for (const step of route.steps) {
      assert.equal(gradeDecision(step, step.expected_answer.one_of[0]).status, 'passed');
      for (const option of step.interaction.options) {
        if (!step.expected_answer.one_of.includes(option.value)) assert.equal(gradeDecision(step, option.value).status, 'wrong');
      }
      for (const board of [step.stem_board, step.completion_board]) {
        for (const item of board.items) if (item.math) katex.renderToString(item.math, {throwOnError:true});
      }
    }
    katex.renderToString(summary.formula, {throwOnError:true});
  });
}

for (const name of ['b06', 'b06-v', 'w03', 'w05', 'w06', 'w07', 'w14']) {
  test(`C ${name} preserves the legal swap, original relation, shared skills and complete answer`, async () => {
    const source = await read(`site/data/graph-walk/function-representations-${name}.source.json`);
    const evidence = await read(source.evidence);
    assert.equal(evidence.provenance.source_admission, 'authored_topic');
    const {bundle, replay} = compileCourse(source, evidence, graph, nodes);
    const route = bundle.routes['function-system'];
    assert.equal(route.steps.length, 5);
    assert.equal(replayState(bundle, replay).done, true);
    const streamed = extendStreamBundle(bundle, evidence.stream, '/root/goals/0', graph);
    assert.equal(replayState(streamed, buildStreamReplay(streamed, {actions: replay.actions.slice(0, 2)})).done, true);
    const d3 = bundle.intro.find(step => step.id === 'D3');
    assert.equal(gradeDecision(d3, methodAnswer(d3, 'system')).status, 'passed');
    const connections = methodCardsHTML(d3, methodAnswer(d3, 'system'), false);
    assert.match(connections, /出现关联函数值/);
    assert.match(connections, /构造方程组法/);
    assert.match(connections, /本题选择/);
    const confirmed = streamGraphState(bundle, replayState(bundle, replay));
    for (const skill of ['skill-equality-transform', 'method-elimination', 'skill-simplify']) {
      assert.ok(confirmed.calls.some(call => call.ref === skill));
    }
    assert.equal(route.completion.answer.kind, 'find_function_formula');
    const summary = routeAnswerSummary(route.completion.answer);
    assert.ok(summary);
    const verification = route.steps[3];
    assert.match(verification.question, /原关系是 \$/);
    assert.match(verification.question, /代入左边 \$/);
    assert.match(verification.stem_board.items[0].math, /\\cdot/);
    assert.deepEqual(streamed.routes['function-system'].steps[3].stem_board, verification.stem_board);
    for (const step of bundle.stream.math_steps) {
      const math = [...step.explanation.matchAll(/\$([^$]+)\$/g)].map(match => match[1]);
      assert.ok(math.length > 0, `${step.title} must contain its actual mathematical working`);
      for (const expression of math) katex.renderToString(expression, {throwOnError: true});
    }
    for (const step of route.steps) {
      for (const option of step.interaction.options) {
        const correct = step.expected_answer.one_of.includes(option.value);
        assert.equal(gradeDecision(step, option.value).status, correct ? 'passed' : 'wrong');
      }
      assert.equal(step.stem_board.items[1].math, null);
      for (const board of [step.stem_board, step.completion_board]) {
        for (const item of board.items) if (item.math) katex.renderToString(item.math, {throwOnError: true});
      }
    }
    assert.match(route.steps[0].completion_board.items[1].math, /array/);
    if (['b06-v','w05','w07','w14'].includes(name)) {
      assert.match(route.steps.at(-1).completion_board.items[1].math, /ne0/);
      assert.match(route.completion.answer.determined_domain.expression, /Interval.open/);
    }
    if (name === 'w07') assert.match(bundle.problem.text, /任意非零实数/);
    if (name === 'w14') assert.match(summary.formula, /10/);
    katex.renderToString(summary.formula, {throwOnError: true});
  });
}

for (const name of ['b07', 'b07-v']) {
  test(`D ${name} preserves universal scope, legal assignments, full verification and shared replay`, async () => {
    const source = await read(`site/data/graph-walk/function-representations-${name}.source.json`);
    const evidence = await read(source.evidence);
    assert.equal(evidence.provenance.source_admission, 'authored_topic');
    const {bundle, replay} = compileCourse(source, evidence, graph, nodes);
    const route = bundle.routes['function-assignment'];
    assert.equal(route.steps.length, 5);
    assert.equal(replayState(bundle, replay).done, true);
    const streamed = extendStreamBundle(bundle, evidence.stream, '/root/goals/0', graph);
    assert.equal(replayState(streamed, buildStreamReplay(streamed, {actions: replay.actions.slice(0, 2)})).done, true);
    const d3 = bundle.intro.find(step => step.id === 'D3');
    assert.equal(gradeDecision(d3, methodAnswer(d3, 'assignment')).status, 'passed');
    const connections = methodCardsHTML(d3, methodAnswer(d3, 'assignment'), false);
    assert.match(connections, /含两个变量的恒等式/);
    assert.match(connections, /赋值法/);
    assert.match(connections, /本题选择/);
    const confirmed = streamGraphState(bundle, replayState(bundle, replay));
    for (const skill of ['skill-equality-transform', 'method-elimination', 'skill-simplify']) {
      assert.ok(confirmed.calls.some(call => call.ref === skill));
    }
    assert.match(bundle.problem.text, /forall x,y/);
    const answer = route.completion.answer;
    assert.equal(answer.kind, 'find_function_formula');
    assert.equal(answer.determined_domain.expression, 'Reals');
    assert.equal(answer.expression.expression, name === 'b07' ? 'x**2 + 3*x' : 'x**2');
    assert.match(route.steps[0].completion_board.items[1].math, name === 'b07' ? /x=0/ : /y=x/);
    assert.match(route.steps[3].feedback.answer, /任意两个实数/);
    const verification = route.steps[3];
    assert.match(verification.question, /作为输入/);
    assert.equal(verification.stem_board.comparison_sides.length, 2);
    assert.deepEqual(verification.stem_board.comparison_sides, verification.completion_board.comparison_sides);
    assert.deepEqual(streamed.routes['function-assignment'].steps[3].stem_board, verification.stem_board);
    for (const side of verification.stem_board.comparison_sides) katex.renderToString(side.math, {throwOnError: true});
    for (const step of bundle.stream.math_steps) {
      const math = [...step.explanation.matchAll(/\$([^$]+)\$/g)].map(match => match[1]);
      assert.ok(math.length > 0, `${step.title} must contain its actual mathematical working`);
      for (const expression of math) katex.renderToString(expression, {throwOnError: true});
    }
    for (const step of route.steps) {
      assert.equal(step.stem_board.items[1].math, null);
      for (const option of step.interaction.options) {
        assert.equal(gradeDecision(step, option.value).status, step.expected_answer.one_of.includes(option.value) ? 'passed' : 'wrong');
      }
      for (const board of [step.stem_board, step.completion_board]) {
        for (const item of board.items) if (item.math) katex.renderToString(item.math, {throwOnError: true});
      }
    }
    katex.renderToString(routeAnswerSummary(answer).formula, {throwOnError: true});
  });
}
