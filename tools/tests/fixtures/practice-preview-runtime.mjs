// Run the actual runtime, Context and components with a minimal DOM surface.
// Rendering geometry is tested in the browser; this harness observes effects,
// imports and fetches across all route completions and account changes.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import vm from 'node:vm';
import { repoRoot, loadSources } from '../../build-public-knowledge-graph.mjs';
import { loadTeaching } from '../../lib/public-knowledge-teaching.mjs';

class Element {
  constructor() {
    this.dataset = {};
    this.style = { setProperty() {} };
    this.value = '';
    this.innerHTML = '';
    this.textContent = '';
    this.listeners = new Map();
    this.children = new Map();
    this.classList = { remove() {} };
    this.hidden = false;
  }
  addEventListener(type, fn) {
    const list = this.listeners.get(type) || [];
    list.push(fn);
    this.listeners.set(type, list);
  }
  emit(type, event = {}) {
    for (const fn of this.listeners.get(type) || []) fn(event);
  }
  querySelector(selector) {
    if (selector.includes('idle-')) return null;
    if (!this.children.has(selector)) this.children.set(selector, new Element());
    return this.children.get(selector);
  }
  querySelectorAll() {
    return [];
  }
  setAttribute() {}
  append() {}
  before(element) {
    this.beforeElement = element;
  }
  after(element) {
    this.afterElement = element;
  }
  insertAdjacentHTML(_position, html) {
    this.innerHTML += html;
  }
  scrollIntoView() {}
  getBoundingClientRect() {
    return { height: 0 };
  }
}
const { nodes, manifest } = await loadSources(),
  teaching = await loadTeaching(repoRoot, nodes, manifest);
const legacyLessons = [...teaching.lessons].filter(([, lesson]) => lesson.runtime !== 'graph-walk');
const routeCount = legacyLessons.reduce((sum, [, lesson]) => sum + Object.keys(lesson.routes).length, 0);
const scripts = await Promise.all(
  ['context.js', 'components.js', 'runtime.js'].map((f) =>
    fs.readFile(path.join(repoRoot, 'site/assets/practice', f), 'utf8')
  )
);
const tick = () => new Promise((resolve) => setImmediate(resolve));
let total = 0;
for (const previewSearch of ['?knowledge=next', '?preview=1&knowledge=next&learning=1'])
for (const signedIn of [false, true])
  for (const [pid, lesson] of legacyLessons) {
    const document = new Element(),
      window = new Element(),
      requests = [],
      imports = [],
      events = [];
    document.currentScript = { src: 'http://localhost/assets/practice/runtime.js?v=40' };
    document.head = new Element();
    document.documentElement = new Element();
    document.createElement = () => new Element();
    document.getElementById = (id) => document.querySelector('#' + id);
    document.getElementById('practice-config').textContent = JSON.stringify(lesson);
    const html = await fs.readFile(
      path.join(
        repoRoot,
        `site${teaching.topics.flatMap((t) => Object.entries(t.problems)).find(([p]) => p === pid)[1].path}index.html`
      ),
      'utf8'
    );
    for (const m of html.matchAll(/<template[^>]*id="([^"]+)"[^>]*>([\s\S]*?)<\/template>/g))
      document.getElementById(m[1]).innerHTML = m[2];
    window.scrollTo = () => {};
    window.dispatchEvent = (e) => events.push(e);
    window.SiteAuth = {
      enabled: true,
      user: signedIn ? { id: 'student' } : null,
      requireLogin() {
        throw Error('Preview must not request login');
      }
    };
    let observed = null,
      fetchOk = false,
      sequence = 0;
    const sandbox = vm.createContext({
      document,
      window,
      structuredClone,
      URL,
      URLSearchParams,
      location: { search: previewSearch, href: 'http://localhost/1/q01/' + previewSearch, pathname: '/1/q01/' },
      AbortSignal,
      crypto: { randomUUID: () => String(++sequence) },
      performance,
      clearTimeout,
      setTimeout: () => {
        throw Error('Preview must not start dialogue timers');
      },
      requestAnimationFrame: (fn) => fn(),
      matchMedia: () => ({ matches: true }),
      ResizeObserver: class {
        observe() {}
      },
      PracticeMath: { render() {} },
      CustomEvent: class {
        constructor(type) {
          this.type = type;
        }
      },
      fetch: async (url) => {
        requests.push(url);
        return {
          ok: fetchOk,
          status: fetchOk ? 200 : 503,
          json: async () => ({ module: '/assets/knowledge-next/practice-preview.mjs' })
        };
      }
    });
    const importModuleDynamically = async (spec) => {
      imports.push(spec);
      if (spec.endsWith('learning-mode.mjs')) {
        const modes = new vm.SyntheticModule(['bindModeLinks'], function () {this.setExport('bindModeLinks', () => {});}, {context:sandbox});
        await modes.link(() => {}); await modes.evaluate(); return modes;
      }
      assert.match(spec, /^\/assets\/knowledge-next\/practice-preview\.mjs/);
      const module = new vm.SyntheticModule(
        ['createPreview'],
        function () {
          this.setExport('createPreview', async () => ({
            update(view) {
              observed = structuredClone(view);
            },
            openStep() {}
          }));
        },
        { context: sandbox }
      );
      await module.link(() => {});
      await module.evaluate();
      return module;
    };
    for (const source of scripts) {
      new vm.Script(source, { importModuleDynamically }).runInContext(sandbox);
      if (window.PracticeComponents) sandbox.PracticeComponents = window.PracticeComponents;
    }
    await tick();
    // Problem-level associations live below all steps and stay hidden until they have content.
    const host = document.querySelector('#completion').afterElement;
    assert.equal(host.id, 'knowledge-preview');
    assert.equal(host.hidden, false);
    assert.match(host.querySelector('[role="status"]').textContent, /加载失败/);
    assert.equal(host.querySelector('button').hidden, false);
    const click = (element, attrs) => {
      const button = {
        dataset: attrs,
        hasAttribute(name) {
          return Object.hasOwn(
            attrs,
            name.replace(/^data-/, '').replace(/-([a-z])/g, (_, c) => c.toUpperCase())
          );
        },
        closest() {
          return this;
        }
      };
      element.emit('click', { target: button });
    };
    const steps = document.querySelector('#steps');
    // Local interaction still works while associations are unavailable.
    click(steps, { method: lesson.methods[0].id });
    assert.match(steps.innerHTML, /step-card/);
    fetchOk = true;
    host.querySelector('button').emit('click');
    await tick();
    await tick();
    assert.equal(observed.state.method, lesson.methods[0].id);
    assert.equal(host.querySelector('button').hidden, true);
    assert.equal(document.querySelector('.composer').hidden, true);
    assert.equal(document.querySelector('#message').disabled, true);
    const before = observed.attempt_id;
    window.emit('site-auth-change', { detail: { reason: 'logout', user: null } });
    assert.equal(observed.attempt_id, before);
    // Even direct hint/send events cannot reach the network.
    click(steps, { hint: '0' });
    document.querySelector('#message').value = '帮我';
    document.querySelector('.send-button').emit('click');
    for (const [rid, route] of Object.entries(lesson.routes)) {
      document.querySelector('#reset').emit('click');
      click(steps, { method: rid });
      for (const [stage, node] of route.entries()) {
        click(steps, { submit: String(stage) });
        assert.equal(observed.state.active, stage);
        const component = node.interaction;
        if (component.type === 'choice')
          click(steps, { choice: component.field, value: node.expected_answer.one_of[0] });
        else {
          node.expected_answer.terms.forEach((value, i) => click(steps, { pairAnswer: String(i), value }));
          if (component.type === 'structure' && node.expected_answer.fixed === 'product') {
            steps.emit('click', {
              target: {
                closest() {
                  return { id: 'swap', hasAttribute: () => false };
                }
              }
            });
          }
        }
        click(steps, { submit: String(stage) });
        assert.equal(observed.state.active, stage + 1, `${pid}/${rid}/${node.id}`);
      }
      assert.equal(document.querySelector('#completion').hidden, false);
      assert.equal(document.querySelector('#completion').dataset.learningCompleted, 'false');
      click(document.querySelector('#completion'), { switchRoute: rid });
      assert.equal(observed.state.active, 0);
      if (!signedIn) total++;
    }
    await tick();
    assert.deepEqual(requests, [
      '/knowledge/teaching/problems.json',
      '/knowledge/teaching/manifest.json',
      '/knowledge/teaching/manifest.json'
    ]);
    assert.equal(imports.length, 2);
    assert.deepEqual(events, []);
  }
assert.equal(total, routeCount * 2);
console.log(`${routeCount} routes, 2 preview modes, 2 login states, failure and retry: passed`);
