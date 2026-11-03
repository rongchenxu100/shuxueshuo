import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {preserveCourseIdentity} from '../lib/graph-walk-course-identity.mjs';
import {pageContract} from '../../site/assets/learning/practice-compatibility.mjs';
import {createState, currentDecision, submitAnswer} from '../../site/assets/graph-walk/walk-state.mjs';
import {replayAnswer} from '../../site/assets/graph-walk/walk-replay.mjs';

const read = pid => JSON.parse(fs.readFileSync(new URL(`../../site/data/graph-walk/${pid}.json`, import.meta.url)));
const decisions = bundle => [...bundle.intro, ...Object.values(bundle.routes).flatMap(route => route.steps)];

// Model a fresh execution: proof identity changes, public choices are shuffled
// and numbered anew, while the question and the verified answers are identical.
function rerun(previous) {
  const current = structuredClone(previous);
  current.bundleVersion = 'new-execution';
  current.stream.run_id = 'new-verified-run';
  for (const step of decisions(current)) {
    if (step.source !== 'stream') continue;
    const oldId = step.id;
    step.id = 'rerun-' + oldId;
    step.stream_interaction_id = 'rerun-' + step.stream_interaction_id;
    if (step.interaction.field === oldId) step.interaction.field = step.id;
    const answers = new Map();
    for (const options of [step.interaction.options, ...(step.interaction.slots || []).map(slot => slot.options)].filter(Boolean)) {
      options.reverse();
      for (const option of options) {
        const next = 'new-' + option.value;
        answers.set(option.value, next); option.value = next;
      }
    }
    for (const key of ['one_of', 'required', 'allowed', 'terms']) {
      if (Array.isArray(step.expected_answer?.[key])) {
        step.expected_answer[key] = step.expected_answer[key].map(value => answers.get(value) ?? value);
      }
    }
  }
  return current;
}

for (const pid of ['function-concepts-q23b-v2', 'function-representations-b11-v1', 'function-representations-b11-v2']) {
  test(`${pid}: re-verification preserves all saved answers without rewriting proof identity`, () => {
    const previous = read(pid), fresh = rerun(previous), original = structuredClone(fresh);
    const result = preserveCourseIdentity(fresh, previous);
    assert.notEqual(result, fresh);
    assert.equal(result.bundleVersion, previous.bundleVersion);
    assert.deepEqual(pageContract(result), pageContract(previous));
    assert.deepEqual(result.stream, fresh.stream);
    assert.deepEqual(fresh, original, 'the verified compiler result is not mutated');
    for (const route of Object.keys(previous.routes)) {
      let old = createState(previous), restored = createState(result);
      for (let step = currentDecision(previous, old); step; step = currentDecision(previous, old)) {
        const action = {decision: step.id, answer: replayAnswer(step, route)};
        old = submitAnswer(previous, old, action);
        restored = submitAnswer(result, restored, action);
        assert.equal(restored.lastFeedback.status, 'passed', step.id);
      }
      assert.ok(old.done && restored.done);
    }
    assert.deepEqual(preserveCourseIdentity(result, result), result, 'repeated builds are stable');
  });
}

const base = read('function-representations-b11-v1');
for (const [name, change] of Object.entries({
  statement: b => { b.problem.text += ' 新条件'; },
  question: b => { b.routes[Object.keys(b.routes)[0]].steps[0].question += ' 新问题'; },
  endpoint: b => {
    const step = decisions(b).find(s => s.source === 'stream' && s.interaction.type === 'choice');
    step.interaction.options[0].label += '（端点不能取到）';
  },
  answer: b => {
    const step = decisions(b).find(s => s.source === 'stream' && s.interaction.type === 'choice');
    step.expected_answer.one_of = [step.interaction.options.find(o => !step.expected_answer.one_of.includes(o.value)).value];
  },
  stepOrder: b => { b.routes[Object.keys(b.routes)[0]].steps.reverse(); },
  addedStep: b => { b.routes[Object.keys(b.routes)[0]].steps.push(structuredClone(b.intro[0])); },
  conclusion: b => { b.routes[Object.keys(b.routes)[0]].completion.answer = {kind: 'set', value: 'changed'}; },
  method: b => { b.routes[Object.keys(b.routes)[0]].method = 'another-method'; },
  identity: b => { b.problemId += '-v3'; },
  stemGraph: b => { decisions(b).find(s => s.source === 'stream').graph = {kind: 'different-condition'}; },
  sourceFigure: b => { b.problem.figures = {version: 'different-diagram'}; },
  figureOptions: b => { decisions(b).find(s => s.source === 'stream').figure_choices = ['A', 'B']; },
  field: b => {
    const step = decisions(b).find(s => s.source === 'stream' && s.interaction.type === 'choice');
    step.interaction.field = 'different-semantic-input';
  },
  ambiguousOptions: b => {
    const step = decisions(b).find(s => s.source === 'stream' && s.interaction.type === 'choice');
    step.interaction.options[1] = {...step.interaction.options[0], value: step.interaction.options[1].value};
  },
})) test(`a genuine ${name} change does not reuse the published identity`, () => {
  const current = rerun(base); change(current);
  assert.equal(preserveCourseIdentity(current, base), current);
});

test('a new course builds without a previous publication', () => {
  const current = rerun(base);
  assert.equal(preserveCourseIdentity(current, null), current);
});
