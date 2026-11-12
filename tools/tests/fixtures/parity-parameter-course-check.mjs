// Compile the supplied temporary evidence in memory; never rebuild public courses.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {createRequire} from 'node:module';
import vm from 'node:vm';
import {compileCourse} from '../../build-graph-walk-topic.mjs';
import {loadSources, publicGraphNodes} from '../../lib/public-knowledge-sources.mjs';
import {validateGraph} from '../../../site/assets/knowledge-next/model.mjs';
import {createState, currentDecision, submitAnswer, replayState, undo} from '../../../site/assets/graph-walk/walk-state.mjs';
import {routeAnswerSummary} from '../../../site/assets/graph-walk/stream-math-dom.mjs';
import {domainNumberLineGraph} from '../../../site/assets/graph-walk/domain-visuals.mjs';

const evidence = JSON.parse(await fs.readFile(process.argv[2], 'utf8'));
const {nodes, manifest} = await loadSources();
const source = process.argv[3] ? JSON.parse(await fs.readFile(process.argv[3], 'utf8'))
  : {schemaVersion: 1, problemId: 'function-parity-r3-test', title: '两参数联合条件 · 开发题',
    page: '/topics/function-parity/variant99/', topicHref: '/topics/function-parity/', targetRef: '/root/goals/0'};
const graph = {...evidence.lesson.goals[0].walk.bundle.graph,
  nodes: publicGraphNodes(nodes), edges: validateGraph(nodes, manifest)};
const {bundle, replay} = compileCourse(source, evidence, graph, nodes);
let state = createState(bundle);
for (const [index, action] of replay.actions.entries()) {
  const decision = currentDecision(bundle, state);
  assert.equal(decision.id, action.decision);
  assert.equal(state.done, false);
  assert.equal(currentDecision(bundle, replayState(bundle, replay, index)).id, decision.id);
  if (decision.interaction.type === 'choice') {
    for (const option of decision.interaction.options.filter(row => !decision.expected_answer.one_of.includes(row.value))) {
      const rejected = submitAnswer(bundle, state, {decision: decision.id, answer: option.value});
      assert.equal(rejected.lastFeedback.status, 'wrong');
      assert.equal(currentDecision(bundle, rejected).id, decision.id);
      assert.equal(rejected.done, false);
    }
  }
  const passed = submitAnswer(bundle, state, action);
  assert.equal(passed.lastFeedback.status, 'passed');
  if (decision.id !== 'D3') assert.equal(currentDecision(bundle, undo(bundle, passed)).id, decision.id);
  state = passed;
}
assert.equal(state.done, true);
assert.equal(replayState(bundle, replay).done, true);
const answer = bundle.routes[process.argv[4] || 'parity-parameter'].completion.answer;
const targets = source.targetRefs || [source.targetRef];
if (targets.length > 1) {
  assert.equal(answer.kind, 'goal_group');
  assert.deepEqual(answer.answers.map(item => item.target_ref), targets);
  assert.deepEqual(bundle.stream.target_refs, targets);
} else {
  assert.notEqual(answer.kind, 'goal_group');
}
const summary = routeAnswerSummary(answer);
if (answer.result_type === 'parameter_family') {
  assert.equal(answer.parameters.length, 2);
  assert.equal(new Set(answer.parameters).size, 2);
  assert.equal(summary.label, '符合条件的联合参数：');
}
if (answer.kind === 'goal_group') assert.ok(summary.items.every(item => item.summary.formula));
else assert.ok(summary.formula);
const katex = createRequire(import.meta.url)('../../../site/assets/practice/vendor/katex-0.18.9/katex.min.js');
let rendered = 0;
let numberLines = 0;
const context = vm.createContext({window: {}});
vm.runInContext(await fs.readFile(new URL('../../../site/assets/practice/components.js', import.meta.url), 'utf8'), context);
const components = context.window.PracticeComponents;
const render = math => { katex.renderToString(math, {throwOnError: true, strict: 'ignore'}); rendered++; };
function visit(value) {
  if (Array.isArray(value)) return value.forEach(visit);
  if (!value || typeof value !== 'object') return;
  for (const [key, item] of Object.entries(value)) {
    if (key === 'condition_number_lines') for (const line of item) {
      const graph = domainNumberLineGraph(line);
      if (!graph) continue; // Crowded exact marks deliberately retain their formula instead.
      assert.ok(components.validateGraph(graph));
      const svg = components.graph({...graph, uid: `checked-line-${numberLines++}`});
      assert.match(svg, /^<svg/);
      assert.doesNotMatch(svg, /NaN|Infinity/);
    }
    if (key === 'math' && typeof item === 'string') render(item);
    else if (typeof item === 'string') for (const match of item.matchAll(/\$\$([\s\S]*?)\$\$|\$([^$]+)\$/g)) render(match[1] ?? match[2]);
    else visit(item);
  }
}
visit(bundle);
for (const formula of answer.kind === 'goal_group' ? summary.items.map(item => item.summary.formula) : [summary.formula]) render(formula);
assert.ok(rendered > 8);
if (process.argv[4] === 'function-symmetry') assert.ok(numberLines > 0);
console.log(JSON.stringify({targets, decisions: replay.actions.length, formulas: rendered, numberLines, summary}));
