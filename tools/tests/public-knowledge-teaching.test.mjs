import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import vm from 'node:vm';
import { execFileSync } from 'node:child_process';
import { repoRoot, loadSources, generate } from '../build-public-knowledge-graph.mjs';
import { loadTeaching, validateSelector, checkRef } from '../lib/public-knowledge-teaching.mjs';
import {createState, currentDecision, submitAnswer} from '../../site/assets/graph-walk/walk-state.mjs';
import {replayAnswer} from '../../site/assets/graph-walk/walk-replay.mjs';
import {
  branches,
  select,
  confirmedChoices,
  libraryPath,
  previewHref,
  previewTarget
} from '../../site/assets/knowledge-next/teaching-model.mjs';

const { nodes, manifest } = await loadSources();
const teaching = await loadTeaching(repoRoot, nodes, manifest);
const legacyLessons = new Map([...teaching.lessons].filter(([, lesson]) => lesson.runtime !== 'graph-walk'));
const legacyRoutes = [...legacyLessons.values()].flatMap(lesson => Object.values(lesson.routes));
const problem = (id) => teaching.topics.flatMap((t) => Object.entries(t.problems)).find(([p]) => p === id)[1];
const actual = (tree, choices) => select(tree, choices).actual.flatMap((b) => b.value);

test('confirmed classifications use explicit identities and provenance', () => {
  assert.equal(new Set(teaching.drills.records.map((r) => r.id)).size, teaching.drills.sourceCount);
  for (const id of ['basic-inequality-q28', 'basic-inequality-q29'])
    assert.deepEqual(problem(id).types, ['type-binary-quadratic-range']);
  assert.deepEqual(problem('basic-inequality-q30').types, ['type-sum-product-extremum']);
  for (let i = 1; i <= 9; i++)
    assert.deepEqual(problem(`quadratic-always-q0${i}`).types, ['type-quantified-quadratic']);
});

test('unanswered selectors keep candidates; chosen branches never union incompatible evidence', () => {
  for (const id of ['basic-inequality-q01', 'basic-inequality-q09']) {
    const route = problem(id).routes.elimination;
    assert.equal(select(route.methods).actual.length, 0);
    assert.equal(select(route.methods).candidates.length, 2);
    assert.deepEqual(actual(route.methods, { technique: 'square' }), ['method-square-extremum']);
    assert.deepEqual(actual(route.methods, { technique: 'vertex' }), ['method-quadratic-extremum']);
    assert.deepEqual(select(route.methods, { technique: 'invalid' }), {
      actual: [],
      candidates: [],
      withheld: false
    });
    const tip = route.steps.quadratic.tip;
    assert.equal(select(tip, { technique: 'vertex' }).actual.length, 0);
    const variable = id.endsWith('q01') ? 'm' : 'a';
    const leaf = select(tip, { technique: 'vertex', variable }).actual[0].value;
    assert.equal(leaf.resource, 'parabola-axis-drag');
    assert.ok(leaf.ref.startsWith('quadratic-function-properties'));
  }
  const q30 = problem('basic-inequality-q30').routes.symmetric;
  assert.equal(branches(q30.steps.inequality.tip).length, 2);
  assert.ok(
    actual(q30.steps.inequality.refs, { inequality_form: 'p_le' }).includes('square-nonnegative#sum-product')
  );
  assert.ok(!actual(q30.steps.inequality.refs, { inequality_form: 'p_le' }).includes('skill-apply-amgm'));
  assert.ok(actual(q30.steps.inequality.refs, { inequality_form: 's_ge' }).includes('skill-apply-amgm'));
  assert.equal(checkRef('method-complete-square', nodes).kind, 'skill');
  assert.throws(() => checkRef('method-complete-square', nodes, ['method']), /类型不符/);
});

test('unanswered choices never reveal which options are accepted', () => {
  const lesson = teaching.lessons.get('basic-inequality-q30'),
    steps = lesson.routes.symmetric;
  const stage = steps.findIndex((s) => s.id === 'inequality'),
    q30 = problem('basic-inequality-q30').routes.symmetric.steps.inequality;
  const options = { inequality_form: steps[stage].interaction.options.map((o) => o.value) };
  for (const tree of [q30.tip, q30.refs]) {
    assert.deepEqual(select(tree, {}, options), { actual: [], candidates: [], withheld: true });
    for (const value of options.inequality_form) {
      const unsubmitted = confirmedChoices(steps, { active: stage, choices: { inequality_form: value } });
      assert.deepEqual(select(tree, unsubmitted, options), { actual: [], candidates: [], withheld: true });
    }
    assert.equal(
      select(
        tree,
        confirmedChoices(steps, { active: stage + 1, choices: { inequality_form: 's_ge' } }),
        options
      ).actual.length,
      1
    );
  }
  // What a student sees at a step must not depend on picks that have not been submitted yet.
  for (const [pid, lesson] of legacyLessons)
    for (const [rid, steps] of Object.entries(lesson.routes)) {
      const choiceSteps = steps.filter((s) => s.interaction.type === 'choice');
      const all = Object.fromEntries(
        choiceSteps.map((s) => [s.interaction.field, s.interaction.options.map((o) => o.value)])
      );
      const route = problem(pid).routes[rid];
      const trees = [route.methods, ...steps.flatMap((s) => [route.steps[s.id].refs, route.steps[s.id].tip])];
      for (let active = 0; active <= steps.length; active++) {
        const passed = Object.fromEntries(
          choiceSteps
            .filter((s) => steps.indexOf(s) < active)
            .map((s) => [s.interaction.field, s.expected_answer.one_of[0]])
        );
        const open = choiceSteps.filter((s) => steps.indexOf(s) >= active);
        for (const tree of trees) {
          const seen = new Set(
            open.flatMap((s) =>
              all[s.interaction.field].map((value) =>
                JSON.stringify(
                  select(
                    tree,
                    confirmedChoices(steps, { active, choices: { ...passed, [s.interaction.field]: value } }),
                    all
                  )
                )
              )
            )
          );
          assert.ok(seen.size <= 1, `${pid}/${rid} 第 ${active + 1} 步：未提交的选择影响了显示`);
          for (const json of seen) {
            const { candidates } = JSON.parse(json);
            for (const b of candidates)
              for (const field of Object.keys(b.conditions).filter((f) => !(f in passed)))
                assert.ok(
                  all[field].every((v) => candidates.some((c) => c.conditions[field] === v)),
                  `${pid}/${rid} 第 ${active + 1} 步：候选暴露了正确选项`
                );
          }
        }
      }
    }
});

test('passing a choice step without a recorded choice unlocks candidates only', () => {
  const step = teaching.lessons.get('basic-inequality-q30').routes.symmetric.find(s => s.id === 'inequality');
  const q30 = problem('basic-inequality-q30').routes.symmetric.steps.inequality;
  const options = {inequality_form:step.interaction.options.map(o => o.value)};
  for (const tree of [q30.tip, q30.refs]) {
    const selection = select(tree, {}, options, ['inequality_form']);
    assert.equal(selection.withheld, false);
    assert.equal(selection.candidates.length, 2);
    assert.deepEqual(selection.actual, []);
  }
  const nested = {field:'first',options:{a:{field:'second',options:{b:['node']}}}};
  const nestedOptions = {first:['a','wrong'],second:['b','wrong']};
  assert.equal(select(nested, {}, nestedOptions, ['first']).withheld, true);
  assert.equal(select(nested, {}, nestedOptions, ['second']).withheld, true);
  assert.equal(select(nested, {}, nestedOptions, ['first','second']).candidates.length, 1);
  assert.deepEqual(select(nested, {}, nestedOptions, ['first','second']).actual, []);
});

test('selector validation rejects missing accepted branches, invented choices and broken anchors', () => {
  const values = ['square', 'vertex'];
  values.accepted = [...values];
  const fields = new Map([['technique', values]]);
  const leaf = (refs) => refs.forEach((r) => checkRef(r, nodes));
  assert.throws(
    () =>
      validateSelector(
        { field: 'technique', options: { square: ['method-complete-square'] } },
        fields,
        leaf,
        'q'
      ),
    /遗漏/
  );
  assert.throws(() => validateSelector({ field: 'invented', options: { x: [] } }, fields, leaf, 'q'), /字段/);
  assert.throws(
    () =>
      validateSelector(
        { field: 'technique', options: { square: [], vertex: [], other: [] } },
        fields,
        leaf,
        'q'
      ),
    /分支不存在/
  );
  assert.throws(() => checkRef('amgm-formula#missing', nodes), /条目失效/);
});

test('all legacy routes and every accepted choice combination complete; wrong answers cannot advance', async () => {
  const scope = vm.createContext({ structuredClone });
  new vm.Script(
    await fs.readFile(path.join(repoRoot, 'site/assets/practice/context.js'), 'utf8')
  ).runInContext(scope);
  const context = scope.PracticeContext;
  let routes = 0,
    scenarios = 0,
    submissions = 0;
  for (const [pid, lesson] of legacyLessons)
    for (const [rid, steps] of Object.entries(lesson.routes)) {
      routes++;
      const alternatives = steps
        .filter((s) => s.interaction.type === 'choice')
        .reduce(
          (list, s) =>
            list.flatMap((c) =>
              s.expected_answer.one_of.map((value) => ({ ...c, [s.interaction.field]: value }))
            ),
          [{}]
        );
      for (const choices of alternatives) {
        scenarios++;
        let view = context.create(lesson, 'initial'),
          seq = 0;
        const apply = (action) => {
          view = context.apply(view, { action, event_id: String(seq++) }, lesson);
        };
        apply({ kind: 'method', value: rid });
        for (const [stage, step] of steps.entries()) {
          apply({ kind: 'submit' });
          assert.equal(view.state.active, stage, `${pid}/${rid}/${step.id}: 空答不能推进`);
          if (step.interaction.type === 'choice') {
            const wrong = step.interaction.options.find(
              (o) => !step.expected_answer.one_of.includes(o.value)
            );
            if (wrong) {
              apply({ kind: 'choice', value: wrong.value });
              apply({ kind: 'submit' });
              assert.equal(view.state.active, stage);
            }
            apply({ kind: 'choice', value: choices[step.interaction.field] });
          } else {
            step.expected_answer.terms.forEach((value, index) => apply({ kind: 'fill', index, value }));
            if (step.interaction.type === 'structure')
              apply({ kind: 'swap', value: step.expected_answer.fixed });
          }
          const mapping = problem(pid).routes[rid].steps[step.id];
          const refs = actual(mapping.refs, view.state.choices);
          for (const b of select(mapping.tip, view.state.choices).actual)
            assert.ok(refs.includes(b.value.ref));
          apply({ kind: 'submit' });
          submissions++;
          assert.equal(view.state.active, stage + 1, `${pid}/${rid}/${step.id}: 正确选择必须推进`);
        }
        assert.ok(context.done(lesson, view.state));
        apply({ kind: 'switch_route', value: rid });
        assert.equal(view.state.active, 0);
        assert.ok(Object.values(view.state.choices).every((v) => v === null));
        assert.equal(view.attempts.find((a) => a.id === 'initial').status, 'completed');
      }
    }
  assert.equal(routes, legacyRoutes.length);
  assert.ok(scenarios > routes);
  assert.ok(submissions >= legacyRoutes.reduce((sum, steps) => sum + steps.length, 0));
});

test('all published graph-walk routes complete through their own runtime and reject unanswered decisions', async () => {
  let routes = 0;
  for (const [pid, lesson] of teaching.lessons) {
    if (lesson.runtime !== 'graph-walk') continue;
    const bundle = JSON.parse(await fs.readFile(path.join(repoRoot, 'site', problem(pid).bundle), 'utf8'));
    for (const rid of Object.keys(bundle.routes)) {
      routes++;
      let state = createState(bundle), steps = 0;
      while (!state.done && steps++ < 500) {
        const decision = currentDecision(bundle, state);
        assert.ok(decision, `${pid}/${rid}: missing decision`);
        const unanswered = submitAnswer(bundle, state, {decision: decision.id, answer: null});
        assert.equal(currentDecision(bundle, unanswered)?.id, decision.id, `${pid}/${rid}: empty answer advanced`);
        state = submitAnswer(bundle, state, {decision: decision.id, answer: replayAnswer(decision, rid)});
        assert.equal(state.lastFeedback.status, 'passed', `${pid}/${rid}/${decision.id}`);
      }
      assert.equal(state.done, true, `${pid}/${rid}: not complete`);
      assert.equal(state.run.route, rid);
    }
  }
  assert.equal(routes + legacyRoutes.length, teaching.counts.routes);
});

test('publisher rejects corrupted teaching contracts and resource branches', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'teaching-contract-'));
  try {
    await fs.mkdir(path.join(root, 'site/data/knowledge-next'), { recursive: true });
    await fs.cp(
      path.join(repoRoot, 'site/data/knowledge-next/topics'),
      path.join(root, 'site/data/knowledge-next/topics'),
      { recursive: true }
    );
    await fs.copyFile(
      path.join(repoRoot, 'site/data/knowledge-next/migration.json'),
      path.join(root, 'site/data/knowledge-next/migration.json')
    );
    for (const part of ['1', '2'])
      await fs.symlink(path.join(repoRoot, 'site', part), path.join(root, 'site', part), 'dir');
    await fs.symlink(path.join(repoRoot, 'server'), path.join(root, 'server'), 'dir');
    const file = path.join(root, 'site/data/knowledge-next/topics/basic-inequality.json');
    const original = JSON.parse(await fs.readFile(file, 'utf8'));
    for (const [mutate, pattern] of [
      [
        (d) => {
          d.problems['basic-inequality-q01'].routes.direct.methods = ['method-complete-square'];
        },
        /类型不符/
      ],
      [
        (d) => {
          delete d.problems['basic-inequality-q01'].routes.direct.steps.structure;
        },
        /步骤集合/
      ],
      [
        (d) => {
          d.problems['basic-inequality-q01'].routes.direct.steps.structure.tip.resource = 'missing';
        },
        /资源失效/
      ],
      [
        (d) => {
          d.problems['basic-inequality-q01'].routes.direct.steps.structure.tip.case = 'missing';
        },
        /case 失效/
      ],
      [
        (d) => {
          d.problems['basic-inequality-q01'].routes.direct.steps.structure.refs = ['amgm-formula'];
        },
        /提示未登记/
      ],
      [
        (d) => {
          d.problems['basic-inequality-q01'].routes.elimination.steps.eliminate.refs =
            d.problems['basic-inequality-q01'].routes.elimination.methods;
        },
        /未来步骤/
      ]
    ]) {
      const data = structuredClone(original);
      mutate(data);
      await fs.writeFile(file, JSON.stringify(data));
      await assert.rejects(loadTeaching(root, nodes, manifest), pattern);
    }
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});

test('problem-page links stay in the preview for any associated problem path', () => {
  const link = (href) => new URL(href, 'http://localhost/');
  const targets = {
    paths: ['/1/q01/', '/1/q02/', '/quadratic/q01/', '/preview-extra/q01/'],
    library: libraryPath('/quadratic/q01/'),
    topic: '/knowledge/topics/quadratic-always/'
  };
  assert.equal(libraryPath('/1/q01/'), '/1/');
  assert.equal(targets.library, '/quadratic/');
  assert.equal(previewTarget(link('/quadratic/'), targets), '/quadratic/?preview=1');
  assert.equal(previewTarget(link('/preview-extra/q01/#step-2'), targets), '/preview-extra/q01/?preview=1#step-2');
  assert.equal(previewTarget(link('/1/q02/'), targets), '/1/q02/?preview=1');
  assert.equal(previewTarget(link('/'), targets), null);
  assert.equal(previewTarget(link('/1/q99/'), targets), null);
  assert.equal(previewTarget(link('/'), { ...targets, library: libraryPath('/q01/') }), null);
});

test('generated public links offer explicit preview and publish no private drill answers', async () => {
  const { outputs } = await generate();
  assert.equal(previewHref('/1/q01/?a=1#step-1'), '/1/q01/?a=1&preview=1#step-1');
  const paths = JSON.parse(outputs.get('teaching/problems/basic-inequality-q01.json')).problemPaths;
  assert.deepEqual(
    paths,
    teaching.topics.flatMap((t) => Object.values(t.problems).map((p) => p.path)).sort()
  );
  for (const [file, body] of outputs) {
    if (file.endsWith('.html'))
      for (const [, href] of body.matchAll(/href="(\/[^"]*)"/g))
        if (paths.includes(href.split(/[?#]/)[0]))
          assert.ok(!href.includes('knowledge=next') && !href.includes('learning=1'), `${file}: ${href}`);
    if (file.startsWith('teaching/'))
      assert.doesNotMatch(body, /"(?:answer|expected_answer|feedback|correct_options)"\s*:/);
    if (file.endsWith('/index.html')) assert.doesNotMatch(body, /class="drill-button"/);
  }
  assert.equal(Object.keys(JSON.parse(outputs.get('teaching/reverse.json'))).length > 20, true);
  assert.ok(outputs.has('topics/basic-inequality/review/index.html'));
  assert.ok(outputs.has('topics/quadratic-always/review/index.html'));
  assert.ok(!outputs.has('teaching/resources.json'));
  for (const id of Object.keys(manifest.resources)) {
    assert.ok(JSON.parse(outputs.get(`teaching/resources/${id}.json`)).html);
  }
  const review = outputs.get('topics/basic-inequality/review/index.html');
  assert.match(review, /href="\/1\/q01\/\?preview=1"/);
  assert.match(outputs.get('method-amgm-direct/index.html'), /href="\/1\/q03\/"/);
  assert.match(review, /基本不等式 · 求最值前检查：一正、二定、三相等/);
  assert.doesNotMatch(review, />[^<]* · checklist</);
  const body = JSON.parse(outputs.get('teaching/nodes/amgm-formula.json')).html;
  assert.match(body, /id="formula"/);
  assert.doesNotMatch(body, /resource-section|data-resource=/);
});

test('shared diagram stylesheet has one in-flight load and retries a failed request', async () => {
  const original = globalThis.document,
    links = [];
  const { stylesheet } = await import('../../site/assets/knowledge-next/resource-runtime.mjs');
  globalThis.document = {
    querySelectorAll: () => links,
    head: { append: (link) => links.push(link) },
    createElement: () => ({
      events: {},
      getAttribute() {
        return this.href;
      },
      addEventListener(type, fn) {
        this.events[type] = fn;
      },
      remove() {
        links.splice(links.indexOf(this), 1);
      }
    })
  };
  try {
    const a = stylesheet('/shared.css'),
      b = stylesheet('/shared.css');
    assert.equal(links.length, 1);
    links[0].sheet = {};
    links[0].events.load();
    await Promise.all([a, b]);
    await stylesheet('/shared.css');
    assert.equal(links.length, 1);
    const failed = stylesheet('/retry.css');
    links[1].events.error();
    await assert.rejects(failed, /样式加载失败/);
    assert.equal(links.length, 1);
    const retry = stylesheet('/retry.css');
    links[1].sheet = {};
    links[1].events.load();
    await retry;
    // A stylesheet declared in HTML can fail before the adapter starts listening.
    const stale = globalThis.document.createElement('link');
    stale.href = '/pre-existing-failure.css';
    links.push(stale);
    const recovered = stylesheet(stale.href),
      replacement = links.at(-1);
    assert.notEqual(replacement, stale);
    assert.ok(!links.includes(stale));
    replacement.events.error();
    await assert.rejects(recovered, /样式加载失败/);
    const secondTry = stylesheet('/pre-existing-failure.css');
    links.at(-1).sheet = {};
    links.at(-1).events.load();
    await secondTry;
  } finally {
    globalThis.document = original;
  }
});

test('builder works without legacy sources and accepts additional problems and new drills', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'teaching-independent-'));
  const write = async (file, data) => {
    const target = path.join(root, file);
    await fs.mkdir(path.dirname(target), { recursive: true });
    await fs.writeFile(target, typeof data === 'string' ? data : JSON.stringify(data));
  };
  try {
    await fs.mkdir(path.join(root, 'site/data'), { recursive: true });
    await fs.cp(
      path.join(repoRoot, 'site/data/knowledge-next'),
      path.join(root, 'site/data/knowledge-next'),
      { recursive: true }
    );
    await fs.symlink(path.join(repoRoot, 'site/data/graph-walk'), path.join(root, 'site/data/graph-walk'), 'dir');
    for (const part of ['assets', '1', '2', 'topics'])
      await fs.symlink(path.join(repoRoot, 'site', part), path.join(root, 'site', part), 'dir');
    const base = 'server/shuxueshuo_server';
    for (const part of ['tutor_demo/lessons', 'learning/drills-next']) {
      await fs.mkdir(path.join(root, base, path.dirname(part)), { recursive: true });
      await fs.cp(path.join(repoRoot, base, part), path.join(root, base, part), { recursive: true });
    }
    await assert.rejects(fs.stat(path.join(root, 'site/data/knowledge')), /ENOENT/);
    await assert.rejects(fs.stat(path.join(root, base, 'learning/drills')), /ENOENT/);
    const baseline = await generate(root);
    assert.deepEqual(baseline.teaching.counts, teaching.counts);

    const file = 'site/data/knowledge-next/topics/basic-inequality.json';
    const topic = JSON.parse(await fs.readFile(path.join(root, file), 'utf8'));
    const previousId = 'basic-inequality-q01',
      addedId = 'preview-added-question';
    const added = structuredClone(topic.problems[previousId]);
    added.path = '/preview-extra/q01/';
    added.label = '新增题目';
    added.routes.direct.steps.structure.tip.note = '经复核的新提示说明，不要求同步旧配置。';
    topic.problems[addedId] = added;
    topic.groups[0].problems.push(addedId);
    await write(file, topic);
    const lesson = structuredClone(teaching.lessons.get(previousId));
    lesson.id = addedId;
    const teacherFile = `${base}/tutor_demo/lessons/${previousId}.json`;
    const teacher = JSON.parse(await fs.readFile(path.join(root, teacherFile), 'utf8'));
    teacher.id = addedId;
    await write(`${base}/tutor_demo/lessons/${addedId}.json`, teacher);
    await write(
      'site/preview-extra/q01/index.html',
      `<script id="practice-config" type="application/json">${JSON.stringify(lesson)}</script>`
    );

    const setFile = `${base}/learning/drills-next/sets/amgm-formula.json`;
    const set = JSON.parse(await fs.readFile(path.join(root, setFile), 'utf8'));
    const item = structuredClone(set.items[0]);
    item.id = 'new-native-question';
    delete item.origin;
    set.items.push(item);
    await write(setFile, set);
    const expanded = await generate(root);
    assert.equal(expanded.teaching.counts.problems, teaching.counts.problems + 1);
    assert.equal(expanded.teaching.counts.routes, teaching.counts.routes + Object.keys(lesson.routes).length);
    assert.equal(expanded.teaching.drills.active, teaching.drills.active + 1);
    assert.equal(expanded.teaching.drills.newCount, 1);
    assert.equal(expanded.teaching.drills.sourceCount, teaching.drills.sourceCount);
    assert.ok(expanded.outputs.has(`teaching/problems/${addedId}.json`));
    assert.ok(
      JSON.parse(expanded.outputs.get(`teaching/problems/${previousId}.json`)).problemPaths.includes(added.path)
    );
    assert.match(expanded.outputs.get('topics/drills/index.html'), /新增 1 道/);
    const changedLesson = structuredClone(lesson);
    changedLesson.routes.direct[0].title = '不一致的标题';
    await write(
      'site/preview-extra/q01/index.html',
      `<script id="practice-config" type="application/json">${JSON.stringify(changedLesson)}</script>`
    );
    await assert.rejects(generate(root), /教学契约不符.*title/);
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});

test('real runtime keeps preview isolated for both login states, including failure and retry', () => {
  const result = execFileSync(
    process.execPath,
    ['--experimental-vm-modules', path.join(repoRoot, 'tools/tests/fixtures/practice-preview-runtime.mjs')],
    { encoding: 'utf8', timeout: 30000 }
  );
  assert.match(
    result,
    new RegExp(`${legacyRoutes.length} routes, 2 preview modes, 2 login states, failure and retry: passed`)
  );
});

test('preview sheet preserves the teaching boundary and text when diagrams fail', () => {
  const result = execFileSync(
    process.execPath,
    ['--experimental-vm-modules', path.join(repoRoot, 'tools/tests/fixtures/practice-preview-sheet.mjs')],
    { encoding: 'utf8', timeout: 30000 }
  );
  assert.match(result, /sheet boundaries, independent failures, retry, text-only fallback and in-place node sheet: passed/);
});
