import test from 'node:test';
import assert from 'node:assert/strict';
import explainer, {comparisonState} from '../../site/assets/explain/knowledge/abstract-monotonicity.js';

test('static figure starts on an ordered additive pair whose difference lands in the sign range', () => {
  const html = explainer.figure();
  assert.doesNotMatch(html, /NaN|undefined/);
  assert.match(html, /x₂−x₁=2\.5，落在 t>0 里/);
  assert.match(html, /aria-pressed="true">加法型/);
  assert.doesNotMatch(html, /[左右]/);
});

test('sliders follow the drawn axis and no graph of f is drawn', () => {
  const html = explainer.figure();
  assert.match(html, /data-am-slider="0" min="-3" max="3"/);
  assert.doesNotMatch(html, /y=f\(x\)|am-curve/);
});

test('both relation families require ordered inputs before applying their strict sign condition', () => {
  for (const family of ['additive', 'multiplicative']) {
    assert.equal(comparisonState(family, 1, 2).tone, 'ok');
    assert.equal(comparisonState(family, 2, 1).tone, 'bad');
    assert.equal(comparisonState(family, 1, 1).tone, 'idle');
  }
});

test('rounded quotient readouts never replace the exact input in a functional identity', () => {
  const rounded = comparisonState('multiplicative', 3.9, 4);
  assert.match(rounded.text, /x₂\/x₁≈1\.03/);
  assert.match(rounded.text, /f\(x₂\)−f\(x₁\)=f\(x₂\/x₁\)>0/);
  assert.doesNotMatch(rounded.text, /f\(1\.03\)/);
  assert.match(comparisonState('multiplicative', 1, 2.5).text, /x₂\/x₁=2\.5/);
});
