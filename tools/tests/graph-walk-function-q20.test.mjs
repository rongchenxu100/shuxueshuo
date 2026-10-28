import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {buildStreamReplay, replayAnswer} from '../../site/assets/graph-walk/walk-replay.mjs';
import {createState, currentDecision, replayState, submitAnswer} from '../../site/assets/graph-walk/walk-state.mjs';
import {optionProgress} from '../../site/assets/graph-walk/option-workspace.mjs';
import {exportContent} from '../export-public-knowledge.mjs';

const read = async file => JSON.parse(await fs.readFile(new URL(file, import.meta.url), 'utf8'));
const id = 'function-concepts-q20-v2';
const bundle = await read(`../../site/data/graph-walk/${id}.json`);
const replay = await read(`../../site/data/graph-walk/${id}.replay.json`);
const routeId = 'function-equality';
const route = bundle.routes[routeId];

test('Q20 is published in the equality group with all four original comparisons', async () => {
  const source = await read(`../../site/data/graph-walk/${id}.source.json`);
  const topic = await read('../../site/data/knowledge-next/topics/function-concepts.json');
  assert.ok(topic.groups.find(group => group.id === 'equality').problems.includes(id));
  assert.equal(source.problemId, id);
  assert.equal(source.page, '/topics/function-concepts/q20/');
  assert.equal(topic.problems[id].path, source.page);
  assert.deepEqual(topic.problems[id].types, ['type-function-equality']);
  assert.equal(topic.problems[id].bundle, `/data/graph-walk/${id}.json`);
  assert.deepEqual(bundle.option_workspaces.map(row => row.label), ['A', 'B', 'C', 'D']);
  for (const row of bundle.option_workspaces) {
    assert.ok(bundle.problem.text.includes(`${row.label}. ${row.text}`));
    assert.deepEqual(Object.keys(row).sort(), ['label', 'option_id', 'text']);
  }
  const html = await fs.readFile(new URL('../../site/topics/function-concepts/q20/index.html', import.meta.url), 'utf8');
  assert.match(html, /"problemId":"function-concepts-q20-v2"/);
});

test('Q20 preserves light/fold domain cards and four independent verdicts in its recorded course', () => {
  assert.equal(route.method, 'method-function-equality');
  assert.equal(bundle.stream.math_steps.length, 11);
  assert.ok(bundle.stream.math_steps.every(step => step.local_check === 'passed'));
  const borrowed = bundle.stream.math_steps.filter(step => step.method_ref?.startsWith('method-domain-intersection#'));
  assert.equal(borrowed.length, 0, 'M1 still runs for certificates but never publishes student cards');
  const domains = bundle.stream.math_steps.filter(step => step.display_unit === 'equality_domains');
  assert.equal(domains.length, 4);
  assert.equal(domains[0].highlight.caption, '定义域');
  assert.equal(domains[0].highlight.connector, '≠');
  assert.equal(domains[0].highlight.conclusion_only, true);
  assert.ok(domains.slice(1).every(step => step.highlight.connector === '='));
  const domainChecks = route.steps.filter(step => step.interaction.type === 'checklist');
  assert.equal(domainChecks.length, 4);
  assert.ok(domainChecks.every(step => /分别选出两边的定义域/.test(step.question)));
  assert.ok(domainChecks.every(step => !/mathbb\{R\}/.test(step.question)));
  const merged = route.steps.filter(step => step.stream_part_count === 2);
  assert.equal(merged.length, 6);
  assert.deepEqual(merged.filter(step => step.stream_part_index === 0).map(step => step.option_context.label), ['B', 'C', 'D']);
  assert.ok(merged.filter(step => step.stream_part_index === 1).every(step =>
    step.interaction.field === 'correspondence' && /对应关系是否等价/.test(step.question)));
  const verdicts = route.steps.filter(step => step.option_context?.phase === 'verdict');
  assert.deepEqual(verdicts.map(step => step.option_context.label), ['A', 'B', 'C', 'D']);
  assert.ok(verdicts.every(step => step.interaction.type === 'choice' && step.interaction.field === 'function_relation'));
  assert.deepEqual(verdicts.map(step => step.expected_answer.one_of), [['different'], ['different'], ['equal'], ['equal']]);
  assert.ok(verdicts.every(step => /是否相同/.test(step.question)));
  for (const [index, step] of verdicts.entries()) {
    assert.equal(step.option_context.option_id, bundle.option_workspaces[index].option_id);
    assert.ok(route.steps.slice(0, route.steps.indexOf(step)).some(prior =>
      prior.option_context?.option_id === step.option_context.option_id && prior.option_context.phase === 'evidence'));
  }
  assert.equal(route.completion.status, 'verified');
  assert.equal(route.completion.answer.kind, 'compare_functions');
  assert.deepEqual(route.completion.answer.option_verdicts.map(row => row.reason),
    ['domains_differ', 'outputs_differ', 'same_domain_and_correspondence', 'same_domain_and_correspondence']);
});

test('Q20 cannot skip a verdict or finish through a loose multi-selection', () => {
  const final = route.steps.at(-1);
  assert.equal(final.interaction.type, 'original_choice_exact_set');
  assert.deepEqual(final.require_complete_options, bundle.option_workspaces.map(row => row.option_id));
  let state = submitAnswer(bundle, createState(bundle), {decision: final.id, answer: ['C', 'D']});
  assert.equal(state.lastFeedback.status, 'wrong');
  assert.equal(state.done, false);
  while (currentDecision(bundle, state).id !== final.id) {
    const step = currentDecision(bundle, state);
    if (step.option_context?.phase === 'verdict') {
      const wrong = step.expected_answer.one_of[0] === 'equal' ? 'different' : 'equal';
      state = submitAnswer(bundle, state, {decision: step.id, answer: wrong});
      assert.equal(currentDecision(bundle, state).id, step.id);
      assert.equal(state.lastFeedback.status, 'wrong');
      assert.equal(optionProgress(bundle, state).finalReady, false);
    }
    state = submitAnswer(bundle, state, {decision: step.id, answer: replayAnswer(step, routeId)});
    assert.equal(state.lastFeedback.status, 'passed');
  }
  assert.equal(optionProgress(bundle, state).finalReady, true);
  assert.equal(optionProgress(bundle, state).finalPassed, false);
  for (const answer of [[], ['C'], ['A', 'C', 'D'], ['C', 'C', 'D'], ['C', 'D', 'Z']]) {
    const rejected = submitAnswer(bundle, state, {decision: final.id, answer});
    assert.equal(rejected.lastFeedback.status, 'wrong');
    assert.equal(rejected.done, false);
  }
  state = submitAnswer(bundle, state, {decision: final.id, answer: ['D', 'C']});
  assert.equal(state.done, true);
  assert.equal(optionProgress(bundle, state).finalPassed, true);
});

test('Q20 publication preserves the native option scopes and exact final contract', async () => {
  const data = await exportContent();
  const problem = data.practice_problems.find(row => row.id === id);
  const published = problem.problem_data._graph_walk;
  assert.equal(problem.path, '/topics/function-concepts/q20/');
  assert.equal(published.bundleVersion, bundle.bundleVersion);
  assert.deepEqual(published.routes[routeId].steps.map(step => step.id), route.steps.map(step => step.id));
  assert.deepEqual(published.routes[routeId].steps.at(-1).expected_answer,
    {correct_labels: ['C', 'D'], option_labels: ['A', 'B', 'C', 'D']});
  const steps = data.practice_steps.filter(step => step.problem_id === id);
  assert.equal(steps.length, 15);
  const refs = steps.flatMap(step => step.refs);
  assert.ok(refs.some(ref => ref === 'method-function-equality' || ref.startsWith('method-function-equality#')));
  assert.ok(refs.includes('function-concept#identity'));
  assert.ok(data.practice_problem_types.some(row => row.problem_id === id && row.node_id === 'type-function-equality'));
});

test('Q20 static and photo stream replay preserve all 15 confirmations including the final multiple choice', () => {
  assert.equal(replay.actions.length, 15);
  const streamed = buildStreamReplay(bundle, {
    actions: replay.actions.slice(0, bundle.intro.findIndex(step => step.id === 'D3')),
    currentRoute: routeId,
  });
  assert.deepEqual(streamed.actions, replay.actions);
  assert.deepEqual(replay.actions.at(-1).answer, ['C', 'D']);
  for (const actions of [replay, streamed]) {
    const state = replayState(bundle, actions);
    assert.equal(state.done, true);
    assert.equal(currentDecision(bundle, state), null);
  }
});
