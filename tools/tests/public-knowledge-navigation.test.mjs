import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';
import {isPreview, modeHref} from '../../site/assets/practice/learning-mode.mjs';
import {safeGraphReturn, VIEW_KINDS, writeState, nodeHref, chapterPath, groupPath} from '../../site/assets/knowledge-next/model.mjs';

const origin = 'https://site';
const chapter = '/knowledge/chapters/compulsory-1-ch2/';
const detailSource = (await fs.readFile(new URL('../../site/assets/knowledge-next/detail.mjs', import.meta.url), 'utf8'))
  .replace(/^import .*;\n/gm, '');
const graphSource = await fs.readFile(new URL('../../site/assets/knowledge-next/graph.mjs', import.meta.url), 'utf8');
const towerSource = await fs.readFile(new URL('../../site/assets/knowledge-next/tower-view.mjs', import.meta.url), 'utf8');

function detailLinks(href, kind = 'skill') {
  const links = {
    '[data-graph-return]': [{href:chapter}],
    '[data-graph-locate]': [{href:chapter}],
    '[data-node-link]': [{href:origin + '/knowledge/skill-factor/#factor'}]
  };
  vm.runInNewContext(detailSource, {
    URL, URLSearchParams, location:new URL(href, origin), safeGraphReturn, VIEW_KINDS, isPreview, modeHref,
    matchMedia:() => ({matches:false}),
    document:{
      querySelector:selector => selector === '#node-page-config'
        ? {textContent:JSON.stringify({id:'method-complete-square',kind,resources:[]})} : null,
      querySelectorAll:selector => links[selector] || []
    }
  });
  return Object.fromEntries(Object.entries(links).map(([key, value]) => [key, new URL(value[0].href, origin)]));
}

test('leaving preview never reactivates a saved preview graph and retains navigation context', () => {
  for (const savedMode of ['preview=1', 'knowledge=next']) {
    const saved = chapter + '?scope=section-2-2&view=solution&node=method-complete-square&' + savedMode + '#graph-anchor';
    const preview = new URL('/knowledge/method-complete-square/?preview=1#operation', origin);
    preview.searchParams.set('graph', saved);
    // This is the same explicit exit used by learning.mjs. The outer mode is
    // authoritative even while the nested historical graph URL has old flags.
    const formal = modeHref(preview.href);
    assert.equal(new URL(formal, origin).hash, '#operation');
    const links = detailLinks(formal);
    for (const selector of ['[data-graph-return]', '[data-graph-locate]']) {
      const link = links[selector];
      assert.equal(isPreview(link.search), false);
      assert.equal(link.searchParams.get('scope'), 'section-2-2');
      assert.equal(link.searchParams.get('view'), 'solution');
      assert.equal(link.searchParams.get('node'), 'method-complete-square');
      assert.equal(link.hash, '#graph-anchor');
    }
    const related = links['[data-node-link]'];
    assert.equal(isPreview(related.search), false);
    assert.equal(related.hash, '#factor');
    const relatedGraph = new URL(related.searchParams.get('graph'), origin);
    assert.equal(isPreview(relatedGraph.search), false);
    assert.equal(relatedGraph.hash, '#graph-anchor');
  }
});

test('preview details normalize both current and legacy modes and retain compatible graph filters', () => {
  for (const mode of ['preview=1', 'knowledge=next', 'preview=1&knowledge=next&learning=1']) {
    const detail = new URL('/knowledge/method-complete-square/?' + mode, origin);
    detail.searchParams.set('graph', chapter + '?scope=section-2-2&view=solution&node=type-sum-product-extremum&kinds=skill&relations=calls#canvas');
    const links = detailLinks(detail.href);
    const locate = links['[data-graph-locate]'];
    assert.equal(locate.searchParams.get('preview'), '1');
    assert.equal(locate.searchParams.get('scope'), 'section-2-2');
    assert.equal(locate.searchParams.get('view'), 'solution');
    assert.equal(locate.searchParams.get('kinds'), 'skill');
    assert.equal(locate.searchParams.get('relations'), 'calls');
    assert.equal(locate.searchParams.get('node'), 'method-complete-square');
    assert.equal(locate.hash, '#canvas');
    assert.equal(links['[data-node-link]'].searchParams.get('preview'), '1');
  }
  assert.equal(safeGraphReturn('https://other.test' + chapter + '#canvas'), '/knowledge/');
});

function graphNavigation(search) {
  class PageLocation extends URL {
    get href() { return super.href; }
    set href(value) { super.href = new URL(value, super.href).href; }
  }
  const location = new PageLocation(chapter + search + '#canvas', origin);
  const state = {scope:'section-2-2',view:'solution',node:'method-complete-square',q:'',kinds:[],relations:[],expanded:[]};
  const config = {chapter:'compulsory-1-ch2',base:chapter};
  const code = graphSource.slice(graphSource.indexOf('function homeHref('), graphSource.indexOf('const nodeEl=')) +
    graphSource.slice(graphSource.indexOf('function stateHref('), graphSource.indexOf('// Frames already')) +
    graphSource.slice(graphSource.indexOf('function locate('), graphSource.indexOf('function relationGroups('));
  const updates = [];
  const context = vm.createContext({
    URL, URLSearchParams, location, state, config, isPreview, modeHref, writeState, nodeHref, chapterPath, groupPath,
    byId:new Map([['quantifiers',{kind:'knowledge',home:'compulsory-1-ch1'}]]),
    chapters:new Map([['compulsory-1-ch1',{id:'compulsory-1-ch1',node:'chapter-sets-logic',sections:[{id:'section-1-5'}]}]]),
    graph:{}, scopeMembers:() => new Set(['quantifiers']), elsewhere:() => true,
    window:{dispatchEvent() {}}, CustomEvent:class {},
    history:{pushState(_state, _title, href) {updates.push(href);},replaceState(_state, _title, href) {updates.push(href);}}
  });
  vm.runInContext(code, context);
  return {location, updates, run:expression => vm.runInContext(expression, context)};
}

test('cross-chapter locate preserves preview without relying on anchor click interception', () => {
  for (const [search, preview] of [['?preview=1',true],['?knowledge=next',true],['?knowledge=next&learning=1',false],['',false]]) {
    const context = graphNavigation(search);
    context.run("locate('quantifiers')");
    const result = context.location;
    assert.equal(result.pathname, '/knowledge/chapters/compulsory-1-ch1/');
    assert.equal(isPreview(result.search), preview);
    assert.equal(result.searchParams.get('scope'), 'section-1-5');
    assert.equal(result.searchParams.get('view'), 'knowledge');
    assert.equal(result.searchParams.get('node'), 'quantifiers');
    assert.equal(result.hash, '#canvas');
  }
});

test('graph state updates and detail round-trips keep mode, state and hash', () => {
  for (const [search, preview] of [['?preview=1',true],['',false]]) {
    const context = graphNavigation(search);
    context.run('updateURL()');
    const updated = new URL(context.updates[0], origin);
    assert.equal(isPreview(updated.search), preview);
    assert.equal(updated.searchParams.get('scope'), 'section-2-2');
    assert.equal(updated.searchParams.get('view'), 'solution');
    assert.equal(updated.searchParams.get('node'), 'method-complete-square');
    assert.equal(updated.hash, '#canvas');
    const detail = new URL(context.run("detailHref('method-complete-square')"), origin);
    const returned = detailLinks(detail.href)['[data-graph-return]'];
    assert.equal(returned.href, updated.href);
  }
});

test('3D collection HUD enters its tower once and does not double-handle canvas labels', () => {
  // Keep the HUD and CSS2D labels as sibling event roots, as in the generated
  // page. Exercise their real event registrations, including click bubbling.
  class Element {
    constructor(parent = null, dataset = {}) { this.parent = parent; this.dataset = dataset; this.events = new Map(); this.innerHTML = ''; }
    addEventListener(type, callback) { this.events.set(type, [...(this.events.get(type) || []), callback]); }
    setAttribute() {}
    closest(selector) {
      const attribute = selector.match(/^\[data-([a-z-]+)\]$/)?.[1];
      const key = attribute?.replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase());
      for (let node = this; node; node = node.parent) if (key && Object.hasOwn(node.dataset, key)) return node;
      return null;
    }
    click() {
      const event = {target: this};
      for (let node = this; node; node = node.parent) for (const callback of node.events.get('click') || []) callback(event);
    }
  }
  const document = new Element(), hud = new Element(document), labels = new Element(document), selection = new Element(document);
  const elements = new Map([['#tower-sections', hud]]);
  const $ = selector => { if (!elements.has(selector)) elements.set(selector, new Element(document)); return elements.get(selector); };
  const collection = {id:'junior-knowledge', kind:'collection', label:'初中知识', built:true, sections:[]};
  const entered = [], context = vm.createContext({
    $, $$:() => [], document, labels:{domElement:labels}, selection:() => selection,
    state:{level:'city',chapter:'',strand:'',spin:false}, chapters:new Map(),
    city:{chapters:[],strands:[],collections:[collection]}, graph:{nodes:[]}, nodeTower:new Map(),
    cityGroups:city => [...city.chapters,...city.collections], chapterName:() => '知识集合', h:text => text,
    enterTower:id => entered.push(id), addEventListener() {},
    select:() => assert.fail('A collection shortcut must enter its group, not select a knowledge node')
  });
  const wire = towerSource.slice(towerSource.indexOf('function wire()'), towerSource.indexOf('async function boot()'));
  const chrome = towerSource.slice(towerSource.indexOf('function renderChrome()'), towerSource.indexOf('function updateURL()'));
  const canvasClicks = towerSource.slice(towerSource.indexOf('  const nodeOf = event =>'), towerSource.indexOf("  labels.domElement.addEventListener('pointerover'"));
  vm.runInContext(chrome + wire + canvasClicks + '\nwire(); renderChrome();', context);
  const id = hud.innerHTML.match(/data-chapter="([^"]+)"/)?.[1];
  assert.equal(id, collection.id, 'the visible bottom bar offers the collection shortcut');
  const hudButton = new Element(hud, {chapter:id});
  new Element(hudButton).click(); // Click the nested bold label, not just its button.
  assert.deepEqual(entered, [collection.id]);
  const canvasButton = new Element(labels, {chapter:id});
  new Element(canvasButton).click();
  assert.deepEqual(entered, [collection.id,collection.id], 'CSS2D clicks must not also trigger the HUD handler');
  vm.runInContext('renderChrome()', context); // Re-rendering the bar keeps its delegation.
  new Element(new Element(hud, {chapter:id})).click();
  assert.deepEqual(entered, [collection.id,collection.id,collection.id]);
});

const towerRestore = towerSource.slice(towerSource.lastIndexOf('  const p = new URLSearchParams(location.search);'), towerSource.indexOf("\n}\n$('#tower-retry')"));

function towerFocusNavigation(search = '') {
  const state = {level:'city',chapter:'',node:'',section:'',strand:''};
  const location = new URL('/knowledge/3d/' + search, origin), focused = [];
  const context = vm.createContext({
    URLSearchParams, state, location, isPreview, modeHref,
    byId:new Map([
      ['junior-knowledge',{kind:'collection'}], ['section-3-1',{kind:'section'}],
      ['function-concept',{kind:'knowledge'}], ['unplaced-collection',{kind:'collection'}]
    ]),
    nodeTower:new Map([['junior-knowledge','junior-knowledge'],['section-3-1','compulsory-1-ch3'],['function-concept','compulsory-1-ch3']]),
    chapters:new Map(), city:{strands:[]},
    history:{replaceState(_state, _title, href) {location.href = new URL(href, location.href).href;}},
    stopPath() {}, showSelection() {}, renderChrome() {},
    view:{focusSection:id => focused.push(id),apply:() => focused.push('city')},
    select:() => assert.fail('A section URL must not select a node'),
    enterTower:() => assert.fail('A section URL must preserve its focused scope'),
    chooseStrand:() => assert.fail('A section URL must not select a strand')
  });
  const update = towerSource.slice(towerSource.indexOf('function updateURL()'), towerSource.indexOf('function refresh()'));
  const choose = towerSource.slice(towerSource.indexOf('function chooseSection('), towerSource.indexOf('function back()'));
  vm.runInContext(update + choose + '\nfunction refresh() { updateURL(); }', context);
  return {state,location,focused,run:expression => vm.runInContext(expression, context)};
}

test('3D collection and chapter section focus survives serializing and restoring its URL', () => {
  for (const id of ['junior-knowledge','section-3-1']) {
    for (const search of ['', '?preview=1', '?knowledge=next']) {
      const context = towerFocusNavigation(search);
      context.run(`chooseSection(${JSON.stringify(id)})`);
      assert.equal(context.location.searchParams.get('section'), id);
      assert.equal(isPreview(context.location.search), Boolean(search));
      const selected = {...context.state};
      Object.assign(context.state, {level:'city',chapter:'',node:'',section:'',strand:''});
      context.run(towerRestore);
      assert.deepEqual(context.state, selected, `${id} must restore its focused group after reload`);
      assert.deepEqual(context.focused, [id,id]);
      assert.equal(isPreview(context.location.search), Boolean(search));
    }
  }
});

test('3D section URL rejects missing, non-scope and unplaced collection IDs', () => {
  for (const id of ['missing','function-concept','unplaced-collection']) {
    const context = towerFocusNavigation(`?section=${id}`);
    context.run(towerRestore);
    assert.deepEqual(context.focused, ['city']);
    assert.equal(context.state.level, 'city');
    assert.equal(context.state.section, '');
  }
});
