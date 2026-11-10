import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {createRequire} from 'node:module';
import {generateCourse} from '../build-graph-walk-topic.mjs';
import {createState, currentDecision, submitAnswer, replayState} from '../../site/assets/graph-walk/walk-state.mjs';
import {replayAnswer} from '../../site/assets/graph-walk/walk-replay.mjs';

const read = async p => JSON.parse(await fs.readFile(p, 'utf8'));
const katex = createRequire(import.meta.url)('../../site/assets/practice/vendor/katex-0.18.9/katex.min.js');
const prefix = id => `site/data/graph-walk/function-monotonicity-${id}-v1`;
const renderMath = math => katex.renderToString(math, {throwOnError: true, strict: 'ignore'});
const IDS = ['a05', 'a09', 'a11', 'a06', 'a08', 'a17', 'a10', 'a13'];

for (const id of IDS) {
  test(`${id}: complete lesson grades, renders and resumes from the shared evidence`, async () => {
    const bundle = await read(prefix(id)+'.json');
    const replay = await read(prefix(id)+'.replay.json');
    assert.equal(replayState(bundle, replay).done, true);
    assert.deepEqual(bundle.intro.map(step => step.id), ['D1', 'D2', 'D3']);
    for (const route of Object.keys(bundle.routes)) {
      let state = createState(bundle), count = 0;
      while (!state.done && count++ < 300) {
        const step = currentDecision(bundle, state);
        assert.ok(step);
        const labels = (step.interaction.options || []).map(o => o.label);
        for (const text of [step.question, ...labels]) {
          // Sides of a breakpoint or axis are named by the math, never by 左／右.
          assert.doesNotMatch(String(text), /[左右]/, step.id);
          for (const [, math] of String(text).matchAll(/\$([^$]+)\$/g)) renderMath(math);
        }
        for (const board of [step.stem_board, step.completion_board].filter(Boolean)) {
          for (const item of board.items || []) if (item.math) renderMath(item.math);
          for (const line of board.lines || []) {
            for (const match of String(line).matchAll(/\$\$([^$]+)\$\$|\$([^$]+)\$/g)) renderMath(match[1] || match[2]);
          }
        }
        const wrong = step.interaction.type === 'read' ? null
          : step.interaction.options?.find(o => step.expected_answer?.one_of && !step.expected_answer.one_of.includes(o.value));
        if (wrong) {
          const rejected = submitAnswer(bundle, state, {decision: step.id, answer: wrong.value});
          assert.equal(rejected.lastFeedback.status, 'wrong');
          assert.equal(currentDecision(bundle, rejected).id, step.id);
        }
        state = submitAnswer(bundle, state, {decision: step.id, answer: replayAnswer(step, route)});
        assert.equal(state.lastFeedback.status, 'passed', step.id);
        state = JSON.parse(JSON.stringify(state));
      }
      assert.equal(state.done, true);
    }
    const outputs = await generateCourse({sourcePath: prefix(id)+'.source.json'});
    assert.deepEqual(JSON.parse(outputs.get(prefix(id)+'.json')), bundle);
  });
}

test('difference quotient and product courses read the sign as the required direction', async () => {
  for (const id of ['a08', 'a17']) {
    const d1 = (await read(prefix(id)+'.json')).intro.find(step => step.id === 'D1');
    const correct = d1.interaction.options.find(o => d1.expected_answer.one_of.includes(o.value));
    assert.match(correct.label, /严格递减/);
    assert.match(d1.question, id === 'a08' ? /差商/ : /差积/);
  }
});

test('A10 asks for the turning-point condition and offers the answer that drops it', async () => {
  const bundle = await read(prefix('a10')+'.json');
  const steps = Object.values(bundle.routes)[0].steps;
  const titled = title => steps.find(step => step.title === title);
  const branch = titled('$x > 1$ 段');
  assert.match(branch.question, /转折点/);
  assert.doesNotMatch(branch.question, /直接判断$/);
  const correct = branch.interaction.options.find(o => branch.expected_answer.one_of.includes(o.value));
  assert.match(correct.label, /a\\in \\left\[-1, \+\\infty\\right\)/);
  const merge = titled('合并全部条件');
  assert.ok(merge.interaction.options.some(o => o.label.includes(String.raw`\left(-\infty, - \frac{1}{2}\right]`)));
});

test('reciprocal and tick-shaped pieces slide the parameter, starting where the piece fails', async () => {
  const pieces = [['a17', '$x \\geq 1$ 段'], ['a10', '$0 < x \\leq 1$ 段'], ['a10', '$x > 1$ 段']];
  for (const [id, title] of pieces) {
    const steps = Object.values((await read(prefix(id)+'.json')).routes)[0].steps;
    const step = steps.find(item => item.title === title);
    assert.ok(step, `${id} ${title}: ${steps.map(item => item.title).join(' | ')}`);
    assert.equal(step.graph?.kind, 'coefficient_explorer', `${id} ${title}`);
    assert.equal(step.graph.params.coefficients.length, 4);
    const {min, max, value} = step.graph.params.parameter;
    assert.ok(min < value && value < max);
    assert.equal(step.completion_graph?.kind, 'coefficient_explorer');
  }
});

test('A13 checks the whole interval stays under the root before merging', async () => {
  const bundle = await read(prefix('a13')+'.json');
  const steps = Object.values(bundle.routes)[0].steps;
  const titles = steps.map(step => step.title);
  const order = ['转化为内层条件', '$a=0$', '$a>0$', '$a<0$', '汇总三类', '整段能开方', '合并全部条件']
    .map(title => titles.indexOf(title));
  assert.ok(order.every((index, i) => index >= 0 && (i === 0 || order[i - 1] < index)), titles.join(' | '));
  const zero = steps.find(step => step.title === '$a=0$');
  assert.equal(zero.graph?.kind, 'linear');
  assert.equal(steps.find(step => step.title === '$a>0$').graph?.kind, 'coefficient_explorer');
  assert.match(steps.find(step => step.title === '汇总三类').question, /内层/);
  const domain = steps.find(step => step.title === '整段能开方');
  assert.match(domain.question, /x=-2/);
  const correct = domain.interaction.options.find(o => domain.expected_answer.one_of.includes(o.value));
  assert.match(correct.label, /1 - a\\ge 0/);
  const merge = steps.find(step => step.title === '合并全部条件');
  assert.ok(merge.interaction.options.some(o => o.label.includes(String.raw`\left[\frac{1}{2}, +\infty\right)`)));
});

test('A11 discusses a=0, a>0 and a<0 on separate cards before the merge', async () => {
  const bundle = await read(prefix('a11')+'.json');
  const steps = Object.values(bundle.routes)[0].steps;
  const titles = steps.map(step => step.title);
  const cases = ['$a=0$', '$a>0$', '$a<0$'].map(title => titles.indexOf(title));
  assert.ok(cases.every(index => index >= 0) && cases[0] < cases[1] && cases[1] < cases[2], titles.join(' | '));
  assert.ok(cases[2] < titles.indexOf('汇总三类'));
  const card = title => steps.find(step => step.title === title);
  const correct = step => step.interaction.options.find(o => step.expected_answer.one_of.includes(o.value));
  assert.match(correct(card('$a=0$')).label, /a=0\\ \\text\{成立\}/);
  assert.ok(card('$a=0$').interaction.options.some(o => /不是二次函数/.test(o.label) && o.feedback));
  const positive = card('$a>0$');
  assert.equal(positive.graph.kind, 'coefficient_explorer');
  assert.match(correct(positive).label, /全部舍去/);
  // Copying the bounded-interval rule gives 0<a≤1/2; the card must offer and explain it.
  assert.ok(positive.interaction.options.some(o => o.label.includes(String.raw`\left(0, \frac{1}{2}\right]`) && /越过对称轴/.test(o.feedback)));
  const negative = card('$a<0$');
  assert.match(correct(negative).label, /恒成立/);
  assert.ok(negative.interaction.options.some(o => /变向/.test(o.feedback || '')));
  const merge = card('汇总三类');
  assert.match(correct(merge).label, /a\\in \\left\(-\\infty, 0\\right\]/);
  assert.ok(merge.interaction.options.some(o => /漏掉了 \$a=0\$/.test(o.feedback || '')));
});

test('the parameter group lists the quadratic and piecewise courses in order', async () => {
  const topic = await read('site/data/knowledge-next/topics/function-monotonicity.json');
  const group = topic.groups.find(item => item.id === 'parameter');
  assert.deepEqual(group.problems, IDS.map(id => `function-monotonicity-${id}-v1`));
  for (const id of group.problems) assert.ok(topic.problems[id].types.includes('type-monotonicity-parameter'));
});
