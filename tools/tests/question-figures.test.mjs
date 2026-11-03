import assert from 'node:assert/strict';
import test from 'node:test';
import {figureLabel, projectFigures, mountQuestionFigures} from '../../site/assets/practice/question-figures.mjs';
import {mountFigureChoices} from '../../site/assets/practice/figure-choices.mjs';

const searchId = 'abcdef012345';
function manifest(privateAssets = false) {
  const value = {schema_version: 'question-figures/v1', content_id: 'a'.repeat(64),
    source: {sha256: 'b'.repeat(64), width: 1000, height: 500, quality: 'original'}, figures: [
      {id: 'original', role: 'source', scope_ref: '/root', box: [0, 0, 1, 1]},
      ...['B', 'A'].map((label, i) => ({id: `option-${label.toLowerCase()}`, role: 'option',
        option_id: `choice-${label.toLowerCase()}`, label, scope_ref: '/root', target_ref: '/root/goals/0', box: [i / 2, 0, (i + 1) / 2, 1]})),
      {id: 'subquestion', role: 'option', option_id: 'choice-a', label: 'A', scope_ref: '/root/children/0', target_ref: '/root/children/0/goals/0', box: [0, 0, 1, 1]},
    ]};
  for (const row of value.figures) row.image_url = privateAssets
    ? `/api/search/problems/${searchId}/figures/${row.id}?version=${value.content_id}`
    : `/assets/question-figures/b09/${row.id}.png`;
  return value;
}

test('option order and stable IDs survive projection; another target is not mixed in', () => {
  const value = manifest();
  const selected = projectFigures(value, {targetRef: '/root/goals/0'});
  assert.deepEqual(selected.rows.map(row => [row.label, row.option_id]), [['B', 'choice-b'], ['A', 'choice-a']]);
  assert.equal(projectFigures(value, {targetRef: '/root/children/0/goals/0'}).rows[0].id, 'subquestion');
  assert.equal(projectFigures(value, {targetRef: '/root/goals/1'}).rows.length, 0);
  assert.equal(selected.source.id, 'original');
});

test('private image URLs cannot be injected into static lessons or reused for another upload/version', () => {
  const value = manifest(true);
  assert.equal(projectFigures(value, {searchId}).rows.length, 3);
  assert.throws(() => projectFigures(value));
  assert.throws(() => projectFigures(value, {searchId: '012345abcdef'}));
  value.content_id = 'c'.repeat(64);
  assert.throws(() => projectFigures(value, {searchId}));
  for (const bad of ['https://other.test/image.png', '/api/search/problems/abc/image', '/assets/question-figures/../private.png', 'data:image/svg+xml,svg']) {
    const publicValue = manifest(); publicValue.figures[0].image_url = bad;
    assert.throws(() => projectFigures(publicValue));
  }
});

test('duplicate bindings, empty boxes and mismatched scopes are rejected', () => {
  for (const edit of [
    v => { v.figures[1].id = 'original'; },
    v => { v.figures[1].box = [0, 0, 0, 1]; },
    v => { v.figures[1].box = [0, 0, .00001, 1]; },
    v => { v.figures[1].option_id = v.figures[2].option_id; },
    v => { v.figures[1].label = 'A'; },
    v => { v.figures[1].target_ref = '/root/children/0/goals/0'; },
  ]) { const value = manifest(); edit(value); assert.throws(() => projectFigures(value)); }
});

test('alt text comes only from role and original label, never model descriptions or answer hints', () => {
  const row = {...manifest().figures[1], alt: '正确答案', description: '应该选这个', correct: true};
  assert.equal(figureLabel(row, 'original'), '选项 B 的原图');
  assert.equal(figureLabel(manifest().figures[0], 'processed'), '识别用图（原始裁图未保留）');
});

// Small DOM fixture for the component's event/focus/disposal contract, not a browser suite.
function dom() {
  const doc = {createElement: tag => new Element(tag), activeElement: null};
  class Element {
    constructor(tag) { this.tag = tag; this.ownerDocument = doc; this.children = []; this.dataset = {}; this.attrs = {}; this.events = {}; this.isConnected = true; this.classList = {add() {}, remove() {}}; }
    setAttribute(k, v) { this.attrs[k] = v; }
    removeAttribute(k) { delete this.attrs[k]; delete this[k]; }
    append(...nodes) { this.children.push(...nodes); for (const node of nodes) node.parent = this; }
    replaceChildren(...nodes) { this.children = []; this.append(...nodes); }
    remove() { this.isConnected = false; this.parent.children = this.parent.children.filter(n => n !== this); }
    addEventListener(k, fn) { this.events[k] = fn; }
    click() { this.events.click?.(); }
    focus() { doc.activeElement = this; }
    showModal() { this.open = true; }
    close() { this.open = false; this.events.close?.(); }
  }
  doc.body = doc.createElement('body');
  const host = doc.createElement('section'); doc.body.append(host);
  const all = (node, tag) => [node, ...node.children.flatMap(child => all(child, tag))].filter(n => !tag || n.tag === tag);
  return {doc, host, all};
}

test('choices become ready only after every required original image has loaded', () => {
  const {host, all} = dom(), ready = [];
  const dispose = mountQuestionFigures(host, manifest(), {targetRef: '/root/goals/0', onReady: value => ready.push(value)});
  const pictures = all(host, 'img');
  assert.equal(ready.at(-1), false);
  for (const [i, picture] of pictures.slice(0, 2).entries()) {
    picture.complete = true; picture.naturalWidth = 100; picture.events.load();
    assert.equal(ready.at(-1), i === 1);
  }
  pictures[2].events.error(); // optional whole-source preview does not block readable choices
  assert.equal(ready.at(-1), true);
  pictures[0].naturalWidth = 0; pictures[0].events.error();
  assert.equal(ready.at(-1), false);
  dispose();
});

test('rendered options preserve labels; keyboard modal restores focus and disposal erases private sources', () => {
  const {doc, host, all} = dom();
  const dispose = mountQuestionFigures(host, manifest(true), {searchId, targetRef: '/root/goals/0'});
  assert.deepEqual(all(host, 'figcaption').map(n => n.textContent), ['选项 B 的原图', '选项 A 的原图', '原始裁图']);
  const opener = all(host, 'button')[0];
  const dialog = all(doc.body, 'dialog')[0];
  opener.click();
  assert.ok(dialog.open);
  assert.equal(doc.activeElement.textContent, '关闭图片');
  dialog.close(); // native Escape sends close too
  assert.equal(doc.activeElement, opener);
  opener.click();
  const images = all(doc.body, 'img');
  assert.ok(images.every(n => n.src.startsWith('/api/search/problems/')));
  dispose();
  assert.equal(dialog.open, false);
  assert.equal(all(doc.body, 'dialog').length, 0);
  assert.equal(host.children.length, 0);
  assert.ok(images.every(n => !n.src));
});

test('clicking an answer picture selects its stable ID; only the separate zoom button opens a modal', () => {
  const {doc, host, all} = dom();
  const decision = {figure_choices: ['choice-b', 'choice-a'], interaction: {type:'choice', field:'answer',
    options:[{value:'choice-b', label:'B'}, {value:'choice-a', label:'A'}]}};
  const dispose = mountFigureChoices(host, manifest(), decision, {targetRef:'/root/goals/0', selected:'choice-a'});
  const choices = all(host, 'button').filter(n => n.dataset.choice);
  assert.deepEqual(choices.map(n => n.dataset.value), ['choice-b', 'choice-a']);
  assert.deepEqual(choices.map(n => n.attrs['aria-pressed']), ['false', 'true']);
  assert.ok(choices.every(n => all(n, 'img').length === 1));
  const dialog = all(doc.body, 'dialog')[0];
  choices[0].click();
  assert.ok(!dialog.open);
  const zoom = all(host, 'button').find(n => n.attrs['aria-label'] === '放大选项 B 的原图');
  assert.equal(zoom.dataset.choice, undefined);
  zoom.click();
  assert.equal(dialog.open, true);
  assert.equal(choices[1].attrs['aria-pressed'], 'true');
  dialog.close();
  assert.equal(doc.activeElement, zoom);
  dispose();
});

test('a required source graph is shown by itself and blocks answering until it loads', () => {
  const {host, all} = dom(), ready = [], value = manifest();
  const options = {targetRef: '/root/goals/0', statementOnly: true, onReady: v => ready.push(v)};
  assert.throws(() => mountQuestionFigures(host, value, options));
  value.figures.push({id: 'given', role: 'statement', scope_ref: '/root', target_ref: '/root/goals/0',
    box: [0, 0, 1, .4], image_url: '/assets/question-figures/b09/given.png'});
  const dispose = mountQuestionFigures(host, value, options);
  const [picture] = all(host, 'img');
  assert.equal(all(host, 'img').length, 1);
  assert.equal(all(host, 'details').length, 0);
  assert.equal(ready.at(-1), false);
  picture.complete = true; picture.naturalWidth = 100; picture.events.load();
  assert.equal(ready.at(-1), true);
  picture.events.error();
  assert.equal(ready.at(-1), false);
  dispose();
});
