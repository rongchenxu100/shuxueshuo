import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {createRequire} from 'node:module';
import {createState, currentDecision, submitAnswer, replayState, undo} from '../../site/assets/graph-walk/walk-state.mjs';
import {routeAnswerSummary} from '../../site/assets/graph-walk/stream-math-dom.mjs';

const read = async suffix => JSON.parse(await fs.readFile(new URL(`../../site/data/graph-walk/function-parity-a17${suffix}`, import.meta.url), 'utf8'));
const bundle = await read('.json'), replay = await read('.replay.json');
const route = bundle.routes['parity-parameter'];
const katex = createRequire(import.meta.url)('../../site/assets/practice/vendor/katex-0.18.9/katex.min.js');

test('A17 can be answered, restored and backed up without exposing an unearned result', () => {
  let state = createState(bundle);
  assert.equal(replay.actions.length, 8);
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
    // The shared stream keeps D3's accepted route when backing up from its
    // first card. Every answered method card itself must remain reversible.
    if (decision.id !== 'D3') assert.equal(currentDecision(bundle, undo(bundle, passed)).id, decision.id);
    state = passed;
  }
  assert.equal(state.done, true);
  assert.equal(replayState(bundle, replay).done, true);
  assert.deepEqual(routeAnswerSummary(route.completion.answer), {label: '符合条件的参数：', formula: 'm=2'});
});

test('A17 preserves the source expression and renders every board and choice formula', () => {
  const source = route.steps[0].stem_board.items[0].math;
  assert.match(source, /2-m/);
  assert.match(source, /m\^\{2\}/);
  assert.match(source, /偶函数/);
  assert.match(route.steps.at(-1).stem_board.lines.join('\n'), /x\^\{2\} \+ 16/);
  let count = 0;
  const render = math => { katex.renderToString(math, {throwOnError: true, strict: 'ignore'}); count++; };
  const visit = value => {
    if (Array.isArray(value)) return value.forEach(visit);
    if (!value || typeof value !== 'object') return;
    for (const [key, item] of Object.entries(value)) {
      if (key === 'math' && typeof item === 'string') render(item);
      else if (key === 'lines' && Array.isArray(item)) item.forEach(line => {
        if (typeof line !== 'string') return;
        for (const match of line.matchAll(/\$\$([\s\S]*?)\$\$|\$([^$]+)\$/g)) render(match[1] ?? match[2]);
      });
      else if (typeof item === 'string') {
        for (const match of item.matchAll(/\$([^$]+)\$/g)) render(match[1]);
      } else visit(item);
    }
  };
  visit([...bundle.intro, ...route.steps, ...bundle.stream.math_steps]);
  assert.ok(count > 20);
});
