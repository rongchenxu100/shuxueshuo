import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import {createState} from '../../site/assets/graph-walk/walk-state.mjs';

const html = fs.readFileSync(new URL('../../site/lab/search/problem.html', import.meta.url), 'utf8');
const source = fs.readFileSync(new URL('../../site/assets/graph-walk/walk.mjs', import.meta.url), 'utf8');

function page({mobile = false, folded = '0'} = {}) {
  const nodes = new Map(), toolbar = [], preferences = new Map([
    ['graph-walk:graph-folded', folded], ['search-walk:graph-folded', folded === '1' ? '0' : '1'],
  ]);
  function element(id = '') {
    const attributes = new Map(), classes = new Set(), listeners = new Map();
    const node = {id, textContent: '', dataset: {}, listeners,
      classList: {add: value => classes.add(value), remove: value => classes.delete(value),
        contains: value => classes.has(value), toggle(value, enabled = !classes.has(value)) {
          if (enabled) classes.add(value); else classes.delete(value); return enabled;
        }},
      setAttribute: (name, value) => attributes.set(name, String(value)),
      getAttribute: name => attributes.get(name), hasAttribute: name => attributes.has(name),
      removeAttribute: name => attributes.delete(name),
      toggleAttribute(name, enabled) { if (enabled) attributes.set(name, ''); else attributes.delete(name); },
      addEventListener(name, fn) { listeners.set(name, [...listeners.get(name) || [], fn]); },
      dispatch(name, event = {}) { for (const fn of listeners.get(name) || []) fn({stopPropagation() {}, ...event}); },
      focus() {}, querySelectorAll: () => [],
      before(inserted) { toolbar.splice(toolbar.indexOf(node), 0, inserted); nodes.set(`#${inserted.id}`, inserted); },
    };
    return node;
  }
  for (const [, id] of html.matchAll(/id="([^"]+)"/g)) nodes.set(`#${id}`, element(id));
  for (const [, id] of html.match(/<div class="gw-toolbar">(.*?)<\/div>/s)[1].matchAll(/id="([^"]+)"/g)) toolbar.push(nodes.get(`#${id}`));
  nodes.set('#gw-open-graph span:last-child', element());
  nodes.set('.gw-lesson', element());
  const body = element(); body.dataset.walk = 'mount';
  const document = {...element(), body, readyState: 'complete', querySelector: selector => nodes.get(selector) || null,
    createElement: () => element()};
  const narrow = {...element(), matches: mobile};
  const context = vm.createContext({document, createState, structuredClone, setTimeout, clearTimeout,
    matchMedia: query => query.includes('max-width') ? narrow : {matches: false},
    localStorage: {getItem: key => preferences.get(key), setItem: (key, value) => preferences.set(key, value)},
    requestAnimationFrame: callback => callback()});
  const run = code => vm.runInContext(code, context);
  run(source.replace(/^import .*;\n/gm, '').replace(/^export /gm, '')
    .replace(/^if \(document.readyState === 'loading'\).*$/m, '')
    .replace(/^if \(document.body.dataset.walk !== 'mount'\).*$/m, ''));
  // Keep real mounting, control binding, actor changes and graph state; omit network/rendering work.
  run(`render = () => revealGraph(); ensureReplay = () => {}; scrollTimeline = () => {};
    load = async () => {
      bundle = options.bundle; studentState = createState(bundle); state = studentState;
      studentState.introCompleted = [{decision: 'D1'}];
      chooseActor(options.actor || 'student', {autoplay: false});
    };`);
  const mount = () => run(`mountWalk({bundle: {problemId: 'photo', bundleVersion: 'v1', intro: [], routes: {}},
    actor: 'student', revealGraph: true})`);
  return {body, document, nodes, toolbar, preferences, run, mount,
    resize(mobile) { narrow.matches = mobile; narrow.dispatch('change'); }};
}

test('photo lessons mount one graph toggle and keep its state across remounts and actor changes', async () => {
  const view = page({folded: '1'});
  await view.mount();
  await view.mount();
  const toggles = view.toolbar.filter(node => node.getAttribute('aria-controls') === 'gw-graph-panel'
    || /graph-toggle$/.test(node.id));
  assert.equal(toggles.length, 1);
  const [toggle] = toggles;
  assert.equal(toggle.listeners.get('click').length, 1);
  assert.equal(toggle.textContent, '展开图谱');
  assert.equal(toggle.getAttribute('aria-expanded'), 'false');
  assert.equal(view.body.hasAttribute('data-graph-folded'), true);
  toggle.dispatch('click');
  assert.equal(toggle.textContent, '收起图谱');
  assert.equal(toggle.getAttribute('aria-expanded'), 'true');
  assert.equal(view.body.hasAttribute('data-graph-folded'), false);
  assert.equal(view.preferences.get('graph-walk:graph-folded'), '0');
  view.nodes.get('#gw-ai').dispatch('click');
  view.nodes.get('#gw-student').dispatch('click');
  assert.equal(toggle.textContent, '收起图谱');
  toggle.dispatch('click');
  await view.mount();
  assert.equal(toggle.textContent, '展开图谱');
  assert.equal(toggle.getAttribute('aria-expanded'), 'false');
  assert.equal(view.body.hasAttribute('data-graph-folded'), true);
});

test('photo graph close and mobile modal share controls without carrying desktop folding into the modal', async () => {
  const view = page();
  await view.mount();
  const toggle = view.nodes.get('#gw-graph-toggle');
  view.nodes.get('#gw-close-graph').dispatch('click');
  assert.equal(toggle.textContent, '展开图谱');
  view.resize(true);
  assert.equal(view.body.hasAttribute('data-graph-folded'), false);
  assert.equal(toggle.getAttribute('aria-expanded'), 'true');
  const panel = view.nodes.get('#gw-graph-panel'), opener = view.nodes.get('#gw-open-graph');
  opener.dispatch('click');
  assert.equal(panel.getAttribute('role'), 'dialog');
  assert.equal(panel.classList.contains('is-open'), true);
  assert.equal(opener.getAttribute('aria-expanded'), 'true');
  view.nodes.get('#gw-ai').dispatch('click');
  assert.equal(panel.classList.contains('is-open'), false);
  assert.equal(opener.getAttribute('aria-expanded'), 'false');
  assert.equal(view.nodes.get('.gw-lesson').inert, false);
  opener.dispatch('click');
  view.resize(false);
  assert.equal(panel.classList.contains('is-open'), false);
  assert.equal(panel.hasAttribute('aria-modal'), false);
  assert.equal(view.body.hasAttribute('data-graph-folded'), false);
  assert.equal(toggle.textContent, '收起图谱');
});

test('a phone ignores the stored desktop fold preference and uses the graph modal', async () => {
  const view = page({mobile: true, folded: '1'});
  await view.mount();
  assert.equal(view.body.hasAttribute('data-graph-folded'), false);
  view.nodes.get('#gw-open-graph').dispatch('click');
  assert.equal(view.nodes.get('#gw-graph-panel').classList.contains('is-open'), true);
  view.nodes.get('#gw-close-graph').dispatch('click');
  assert.equal(view.nodes.get('#gw-graph-panel').classList.contains('is-open'), false);
  assert.equal(view.preferences.get('graph-walk:graph-folded'), '1');
});
