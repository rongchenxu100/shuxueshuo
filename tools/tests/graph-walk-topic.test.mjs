import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import vm from 'node:vm';
import {expressionRegionsHTML} from '../../site/assets/graph-walk/expression-regions.mjs';
import {domainNumberLineGraph, endpointChecksHTML} from '../../site/assets/graph-walk/domain-visuals.mjs';
import {compileCourse, buildCourse} from '../build-graph-walk-topic.mjs';
import {repoRoot, loadSources} from '../lib/public-knowledge-sources.mjs';
import {exportContent} from '../export-public-knowledge.mjs';
import {createState, currentDecision, gradeDecision, submitAnswer} from '../../site/assets/graph-walk/walk-state.mjs';

const expression = variable => ['/', ['call', 'sqrt', ['-', ['name', variable], ['number', '3']]], ['-', ['name', variable], ['number', '5']]];
const source = variable => ({expression_ast: expression(variable), expression: `sqrt(${variable}-3)/(${variable}-5)`, regions: [
  {source_ref: '/root/definitions/0/value/1/2', ast_path: [1, 2], condition_id: 'radical', basis_refs: ['square-root-expression#meaning']},
  {source_ref: '/root/definitions/0/value/2', ast_path: [2], condition_id: 'denominator', basis_refs: ['rational-expression#meaning']},
]});

test('S3 source paths control expression highlighting without inferring conditions from numbers', () => {
  const plain = expressionRegionsHTML(source('t'));
  assert.doesNotMatch(plain, /is-highlighted/);
  const chosen = expressionRegionsHTML(source('t'), ['radical']);
  assert.equal((chosen.match(/is-highlighted/g) || []).length, 1);
  assert.match(chosen, /data-source-ref="\/root\/definitions\/0\/value\/1\/2"/);
  assert.match(chosen, />t<\/span>/);
  assert.equal((expressionRegionsHTML(source('z'), ['radical', 'denominator']).match(/is-highlighted/g) || []).length, 2);
});

test('invalid or missing S3 positions fail rather than guessing a highlight', () => {
  const broken = source('x'); broken.regions[0].ast_path = [8];
  assert.throws(() => expressionRegionsHTML(broken), /unresolved_reference/);
  broken.regions[0].ast_path = [1, 2]; delete broken.regions[0].source_ref;
  assert.throws(() => expressionRegionsHTML(broken), /invalid_reference/);
});

test('repeated subexpressions keep distinct structural positions', () => {
  const value = source('x'); value.expression_ast[2] = structuredClone(value.expression_ast[1][2]);
  const html = expressionRegionsHTML(value, ['denominator']);
  assert.equal((html.match(/is-highlighted/g) || []).length, 1);
  assert.match(html, /is-highlighted" data-source-ref="\/root\/definitions\/0\/value\/2"/);
});

test('bound argument display comes from the S3 symbol map', () => {
  const value = source('t');
  value.expression_ast[1][2][1] = ['bound', 'function_argument'];
  assert.throws(() => expressionRegionsHTML(value), /missing_bound_symbol/);
  value.bound_symbols = {function_argument: 't'};
  assert.doesNotMatch(expressionRegionsHTML(value), /function_argument/);
});

test('verified set geometry draws included and excluded endpoints without interpreting an answer', async () => {
  const line = {label: '交集', variable: 't', bounds: [0, 4], points: [], ticks: [{at: 1, label: '1'}, {at: 2, label: '2'}],
    intervals: [{left: 1, right: 2, left_closed: true, right_closed: false},
      {left: 2, right: null, left_closed: false, right_closed: false}]};
  const graph = domainNumberLineGraph(line), scope = vm.createContext({window: {}});
  vm.runInContext(await fs.readFile(path.join(repoRoot, 'site/assets/practice/components.js'), 'utf8'), scope);
  assert.equal(scope.window.PracticeComponents.validateGraph(graph), true);
  const html = scope.window.PracticeComponents.numberLine({...graph.params, uid: 'domain-test'});
  assert.equal((html.match(/number-line-end is-closed/g) || []).length, 1);
  assert.equal((html.match(/class="number-line-end"/g) || []).length, 2);
  assert.match(html, />t<\/text>/);
  assert.throws(() => domainNumberLineGraph({...line, intervals: [{left: null, right: 2, left_closed: true, right_closed: false}]}), /interval/);
  const close = {...line, bounds: [0.25, 1.76], ticks: [{at: 1, label: '1'}, {at: 1.01, label: '101/100'}],
    intervals: [{left: 1, right: 1.01, left_closed: true, right_closed: false},
      {left: 1.01, right: null, left_closed: false, right_closed: false}]};
  assert.equal(domainNumberLineGraph(close), null, 'nearby open and closed endpoints must never cover one another');
  const endpoint = {at: 2, label: 't=2', included: false, holds: false, passed: true,
    reason: '原式的分母为零。', sources: [{source_ref: '/root/definitions/0'}]};
  assert.match(endpointChecksHTML([endpoint]), /不能取到.*原式的分母为零/s);
  assert.throws(() => endpointChecksHTML([{...endpoint, passed: false}]), /unverified_endpoint/);
  assert.throws(() => endpointChecksHTML([null]), /unverified_endpoint/);
});

const json = async file => JSON.parse(await fs.readFile(path.join(repoRoot, file), 'utf8'));
test('real recorded course and photo projection share all seven verified decisions', async () => {
  const {nodes} = await loadSources();
  const source = await json('site/data/graph-walk/function-concepts-q15.source.json');
  const evidence = await json(source.evidence);
  const {bundle, replay} = compileCourse(source, evidence, await json('site/knowledge/graph.json'), nodes);
  const decisions = [...bundle.intro, ...bundle.routes['domain-intersection'].steps];
  assert.deepEqual(decisions.map(step => step.interaction.type), ['choice', 'choice', 'read', 'multi', 'checklist', 'checklist', 'choice']);
  const reading = decisions[0];
  assert.equal(reading.id, 'D1');
  assert.deepEqual(reading.interaction.options.map(option => option.label).sort(),
    ['自变量 $x$ 的取值范围', '函数值 $f(x)$ 的取值范围'].sort());
  assert.equal(reading.interaction.slots, undefined);
  assert.deepEqual(bundle.problem.givens.map(given => given.kind), ['expression']);
  assert.equal(bundle.problem.givens[0].options, undefined, 'the formula is given information, not another question');
  assert.deepEqual(new Set(reading.effects.nodes), new Set(['function-concept', 'square-root-expression', 'rational-expression']));
  assert.match(reading.effects.results[0], /原解析式有意义/);
  assert.equal(typeof replay.actions[0].answer, 'string');
  assert.deepEqual(replay.actions[0], {decision: 'D1', answer: reading.expected_answer.one_of[0]});
  const outputRange = reading.interaction.options.find(option => !reading.expected_answer.one_of.includes(option.value));
  const wrongReading = submitAnswer(bundle, createState(bundle), {decision: 'D1', answer: outputRange.value});
  assert.equal(currentDecision(bundle, wrongReading).id, 'D1');
  assert.match(wrongReading.lastFeedback.message, /值域/);
  assert.equal(decisions[3].source_regions.bound_symbols.function_argument, 'x');
  assert.equal(replay.actions.length, 7);
  const final = decisions.at(-1);
  assert.equal(final.expected_answer.one_of.length, 2);
  assert.equal(decisions.at(-2).condition_number_lines.length, 2);
  assert.equal(final.condition_number_lines.length, 2);
  assert.deepEqual(final.condition_number_lines.map(line => line.bounds), [final.completion_number_line.bounds, final.completion_number_line.bounds]);
  assert.deepEqual(final.condition_number_lines.map(line => line.ticks), [final.completion_number_line.ticks, final.completion_number_line.ticks]);
  assert.deepEqual(final.endpoint_checks.map(check => [check.at, check.included, check.passed]), [[1, true, true], [2, false, true]]);
  assert.match(final.endpoint_checks[1].reason, /分母为 0/);
  let state = createState(bundle);
  for (const action of replay.actions.slice(0, -1)) state = submitAnswer(bundle, state, action);
  assert.equal(currentDecision(bundle, state).id, final.id);
  for (const answer of final.expected_answer.one_of) assert.equal(submitAnswer(bundle, state, {decision: final.id, answer}).done, true);
  const wrong = final.interaction.options.find(option => !final.expected_answer.one_of.includes(option.value)).value;
  assert.equal(submitAnswer(bundle, state, {decision: final.id, answer: wrong}).done, false);
  const broken = structuredClone(evidence); broken.stream.handoffs[0].available = false;
  assert.throws(() => compileCourse(source, broken, bundle.graph, nodes), /未完成双重校验/);
  assert.deepEqual(await buildCourse({check: true}), {changed: 0});
});

test('native topic publication derives its steps from the verified course without a legacy teacher', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'native-topic-export-'));
  try {
    await fs.mkdir(path.join(root, 'site/data'), {recursive: true});
    await fs.symlink(path.join(repoRoot, 'server'), path.join(root, 'server'));
    for (const name of ['assets', '1', '2', 'topics']) await fs.symlink(path.join(repoRoot, 'site', name), path.join(root, 'site', name));
    await fs.symlink(path.join(repoRoot, 'site/data/graph-walk'), path.join(root, 'site/data/graph-walk'));
    await fs.cp(path.join(repoRoot, 'site/data/knowledge-next'), path.join(root, 'site/data/knowledge-next'), {recursive: true});
    const topicFile = path.join(root, 'site/data/knowledge-next/topics/function-concepts.json');
    const topic = JSON.parse(await fs.readFile(topicFile, 'utf8'));
    topic.groups.find(group => group.id === 'domain').problems = ['function-concepts-q15'];
    topic.problems['function-concepts-q15'] = {label: '求函数的定义域 · Q15', path: '/topics/function-concepts/q15/',
      runtime: 'graph-walk', bundle: '/data/graph-walk/function-concepts-q15.json', types: ['type-function-domain']};
    await fs.writeFile(topicFile, JSON.stringify(topic));
    const rows = await exportContent(root);
    const published = rows.practice_problems.find(problem => problem.id === 'function-concepts-q15');
    assert.equal(published.problem_data._graph_walk.schema, 'graph-walk-practice/v1');
    const native = published.problem_data._graph_walk;
    const bundle = await json('site/data/graph-walk/function-concepts-q15.json');
    const replay = await json('site/data/graph-walk/function-concepts-q15.replay.json');
    assert.deepEqual(native.intro[0].interaction, bundle.intro[0].interaction);
    assert.deepEqual(native.intro[0].expected_answer, bundle.intro[0].expected_answer);
    assert.equal(native.intro[0].expected_answer.terms, undefined);
    assert.equal(native.bundleVersion, replay.bundleVersion);
    assert.equal(gradeDecision(native.intro[0], replay.actions[0].answer).status, 'passed');
    assert.equal(gradeDecision(native.intro[0], [replay.actions[0].answer]).status, 'wrong', 'the old checklist answer is not accepted as a choice');
    assert.equal(published.problem_data._lesson, undefined);
    assert.equal(rows.practice_steps.filter(step => step.problem_id === published.id).length, 7);
    assert.ok(rows.practice_step_nodes.some(step => step.problem_id === published.id && step.node_id === 'skill-expression-defined'));
  } finally { await fs.rm(root, {recursive: true, force: true}); }
});
