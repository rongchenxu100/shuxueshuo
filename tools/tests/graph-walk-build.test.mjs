import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {generateDemo, publishDemo, compileNotation, SOURCE_PATH, BUNDLE_PATH, PAGE_PATH} from '../build-graph-walk-demo.mjs';
import {repoRoot, loadSources} from '../lib/public-knowledge-sources.mjs';
import {validateGraph} from '../../site/assets/knowledge-next/model.mjs';

const {bundle} = await generateDemo();
const decisions = [...bundle.intro, ...Object.values(bundle.routes).flatMap(route => route.steps)];

async function fixture(t) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'graph-walk-build-'));
  t.after(() => fs.rm(root, {recursive: true, force: true}));
  const link = async relative => {
    await fs.mkdir(path.dirname(path.join(root, relative)), {recursive: true});
    await fs.symlink(path.join(repoRoot, relative), path.join(root, relative));
  };
  const copy = async relative => {
    await fs.mkdir(path.dirname(path.join(root, relative)), {recursive: true});
    await fs.cp(path.join(repoRoot, relative), path.join(root, relative), {recursive: true});
  };
  for (const relative of ['server', 'internal', 'site/1', 'site/topics']) await link(relative);
  // Teaching now includes native graph-walk courses. Keep their verified inputs
  // available while leaving this compiler's own output absent for ownership tests.
  for (const name of await fs.readdir(path.join(repoRoot, 'site/data/graph-walk'))) {
    const relative = `site/data/graph-walk/${name}`;
    if (![SOURCE_PATH, BUNDLE_PATH].includes(relative)) await link(relative);
  }
  for (const name of await fs.readdir(path.join(repoRoot, 'site/2'))) {
    if (name === 'q01') await copy(`site/2/${name}`);
    else await link(`site/2/${name}`);
  }
  for (const name of await fs.readdir(path.join(repoRoot, 'site/assets'))) {
    if (name !== 'practice') await link(`site/assets/${name}`);
  }
  for (const name of await fs.readdir(path.join(repoRoot, 'site/assets/practice'))) {
    if (name === 'context.js') await copy(`site/assets/practice/${name}`);
    else await link(`site/assets/practice/${name}`);
  }
  for (const relative of ['site/data/knowledge-next', 'site/data/math-notation-v1/quadratic-always', SOURCE_PATH,
    'tools/build-graph-walk-demo.mjs', 'tools/templates/graph-walk.html']) await copy(relative);
  return root;
}

const rewrite = source => source.routes.discriminant.steps.find(step => step.id === 'd_rewrite');

async function edit(root, relative, fn) {
  const file = path.join(root, relative), value = JSON.parse(await fs.readFile(file, 'utf8'));
  fn(value);
  await fs.writeFile(file, JSON.stringify(value, null, 2) + '\n');
}

test('real notation compiles without matching metadata or derived answers in the problem projection', async () => {
  assert.deepEqual(bundle.problem.root.facts, ['a∈ℝ', '∀x∈ℝ: -x^2+2*x+3 ≤ a^2-3*a']);
  assert.deepEqual(bundle.problem.root.goals, [{kind: 'find_range', symbol: 'a'}]);
  assert.equal(bundle.notation.semantic.facts[1][0], 'quantifier');
  assert.ok(Object.values(bundle.notation.sourceLocations).some(location => location.path === 'r.facts[1]'));
  assert.ok(!JSON.stringify(bundle.problem).includes('family_id'));
  assert.ok(!JSON.stringify(bundle.problem).includes('最大值为'));
  const candidate = JSON.parse(await fs.readFile(path.join(repoRoot, bundle.notation.path), 'utf8'));
  candidate.root.facts[1] = '∀x∈ℝ: ???';
  assert.throws(() => compileNotation(candidate), /Notation validation failed/);
});

test('candidate traversal retains real directions and applicability separate from implemented routes', () => {
  const [d1, d2, d3] = bundle.intro;
  assert.deepEqual(d1.candidates, [
    {id: 'type-function-domain', coverage: 2},
    {id: 'type-quantified-quadratic', coverage: 2},
    {id: 'type-amgm-quantified', coverage: 1},
    {id: 'type-parameter-quadratic-solve', coverage: 1},
    {id: 'type-quadratic-solve', coverage: 1},
    {id: 'type-rational-inequality', coverage: 1},
    {id: 'type-solution-parameters', coverage: 1},
  ]);
  assert.equal(d2.interaction.options.length, 6);
  for (const id of ['type-function-domain', 'type-abstract-function-domain', 'type-function-range']) {
    assert.equal(d2.verdicts[id].value, 'unfit');
    assert.ok(d2.verdicts[id].message);
    assert.equal(d2.expected_answer.one_of.includes(id), false);
  }
  assert.ok(d2.alternatives['type-amgm-quantified'].href.startsWith('/knowledge/'));
  assert.equal(bundle.intro.length, 3);
  assert.equal(d3.interaction.type, 'plane');
  const [x, y] = d3.expected_answer.cell;
  assert.deepEqual(d3.interaction.methods.filter(method => method.cells.some(cell => cell[0] === x && cell[1] === y)).map(method => method.value), ['discriminant', 'separation']);
  assert.deepEqual(d3.interaction.methods.filter(method => method.route).map(method => method.route), ['discriminant', 'extremum']);
  assert.deepEqual(d3.interaction.methods.find(method => method.value === 'interval').cells, [['interval', 'free']]);
  assert.deepEqual(d3.alternatives, {});
  for (const id of d2.effects.edges) {
    const edge = bundle.graph.edges.find(edge => edge.id === id);
    assert.equal(edge.from, 'type-quantified-quadratic');
    assert.equal(edge.type, 'involves');
  }
  assert.ok(!d3.effects.nodes.includes('method-interval-extremum'));
  assert.ok(bundle.graph.nodes.find(node => node.id === 'method-separation').steps.find(step => step.id === 'range').calls.some(call => call.when));
});

test('ordered templates retain repeated occurrences and actual nested calls with basis subsets', async () => {
  const {nodes, manifest} = await loadSources(), edges = validateGraph(nodes, manifest);
  const simplify = edges.find(edge => edge.from === 'method-discriminant' && edge.to === 'skill-simplify');
  assert.deepEqual(simplify.occurrences.map(occurrence => occurrence.step), ['normalize', 'conditions', 'solve']);
  const square = bundle.routes.extremum.steps.find(step => step.id === 'e_extremum');
  assert.deepEqual(square.effects.calls.map(call => call.ref), ['method-square-extremum', 'method-complete-square']);
  assert.deepEqual(square.skippedCalls.map(call => call.ref), ['method-elimination', 'method-substitution', 'quadratic-interval-extremum']);
  assert.ok(square.effects.calls[1].usedBasis.includes('square-nonnegative#nonnegative'));
  const actual = decisions.flatMap(step => step.effects.calls), bases = actual.flatMap(call => call.usedBasis);
  assert.ok(!bases.includes('quantifiers#existential'));
  assert.ok(!bases.includes('inequality-properties#reciprocal'));
  for (const call of actual) {
    const edge = bundle.graph.edges.find(edge => edge.id === call.edge);
    assert.equal(edge.occurrences[call.occurrence].step, call.step);
    assert.ok(nodes.find(node => node.id === call.method).steps.find(step => step.id === call.step).calls[call.callIndex].ref === call.ref);
  }
  const separate = bundle.routes.extremum.steps[0];
  assert.equal(separate.effects.calls.length, 0);
  assert.ok(separate.skippedCalls.some(call => call.ref === 'skill-inequality-transform'));
});

test('a page step can be asked with graph options while keeping its page display', () => {
  const position = bundle.routes.discriminant.steps.find(step => step.id === 'd_position');
  assert.equal(position.interaction.type, 'multi');
  assert.ok(position.interaction.options.every(option => option.graph?.vertex));
  assert.deepEqual(position.expected_answer.required.sort(), ['apart', 'touch']);
  assert.equal(position.display, 'd_position-done');
  const range = bundle.routes.discriminant.steps.find(step => step.id === 'd_range');
  assert.equal(range.interaction.type, 'choice');
  assert.deepEqual(range.interaction.options.map(option => [option.value, option.graph.solution.closed]).sort(), [['inside', true], ['open', false], ['outside', true]]);
  assert.deepEqual(range.expected_answer, {one_of: ['outside']});
  const separatedRange = bundle.routes.extremum.steps.find(step => step.id === 'e_range');
  assert.equal(separatedRange.interaction.field, 'e_range');
  assert.ok(separatedRange.interaction.options.every(option => option.graph?.solution));
  assert.equal(separatedRange.display, 'e_range-done');
  assert.ok(bundle.routes.discriminant.steps.find(step => step.id === 'd_rewrite').effects.results[0].includes('g(x)='));
  const basis = bundle.routes.extremum.steps.find(step => step.id === 'e_basis');
  assert.equal(basis.interaction.type, 'grid');
  assert.deepEqual(basis.expected_answer, {cell: ['separable', 'no_division']});
  assert.equal(basis.display, 'e_basis-done');
  assert.match(basis.effects.results[0], /f\(x\)=[\s\S]*c=a\^2-3a/);
});

test('bundle includes only used template snapshots and public graph data', () => {
  assert.ok(bundle.templates['e_extremum-done'].includes('配方求最大值'));
  assert.equal(bundle.completion.answer, '$a\\in(-\\infty,-1]\\cup[4,+\\infty)$');
  assert.equal(bundle.templates['lesson-completion'], undefined);
  assert.ok(Object.values(bundle.routes).every(route => route.takeaway));
  for (const decision of decisions.filter(decision => decision.source === 'page')) {
    assert.ok(bundle.templates[decision.display]);
    if (decision.board) assert.ok(bundle.templates[decision.board]);
  }
  const text = JSON.stringify(bundle);
  for (const privateKey of ['"answer_spec"', '"_lesson"', '"item_snapshot"', '"family_id"']) assert.ok(!text.includes(privateKey));
  assert.deepEqual(Object.keys(bundle.graph.layout.positions).sort(), bundle.graph.nodes.map(node => node.id).sort());
  assert.ok(bundle.graph.nodes.every(node => !node.id.includes('#')));
});

test('build rejects missing verdicts, wrong calls, invalid basis and future results', async t => {
  const root = await fixture(t), original = await fs.readFile(path.join(root, SOURCE_PATH));
  const cases = [
    [source => delete source.intro[1].verdicts['type-amgm-quantified'], /Missing verdict/],
    [source => source.intro[2].verdicts.interval.value = 'pending', /Pending verdict needs/],
    [source => source.intro[2].interaction.coverage.swap.push(['real', 'free']), /differs from the authored verdicts/],
    [source => source.intro[2].interaction.coverage.discriminant = [['real', 'all']], /Invalid coverage/],
    [source => rewrite(source).effects.calls[0].step = 'not-a-step', /Unknown method step/],
    [source => rewrite(source).effects.calls[0].ref = 'skill-factor', /Call not in template/],
    [source => rewrite(source).effects.calls[0].usedBasis = ['square-nonnegative#nonnegative'], /Basis not used by skill/],
    [source => rewrite(source).effects.calls[0].usedBasis = ['inequality-properties#missing'], /Invalid knowledge entry/],
    [source => rewrite(source).requires = ['d_range'], /Future or cross-route/],
    [source => source.routes.extremum.steps[2].effects.calls.shift(), /Submethod not called/],
    [source => source.routes.discriminant.steps[0].id = 'missing', /Page steps or order changed/],
    [source => source.routes.discriminant.omit = [], /Page steps or order changed/],
    [source => source.routes.discriminant.omit.push('d_missing'), /Unknown omitted step/],
    [source => source.routes.extremum.steps[0].present.interaction.zones.pop(), /Grid zones must cover each cell once/],
    [source => source.routes.extremum.steps[0].present.interaction.zones[0].cells.push(['tangled', 'no_division']), /Grid zones must cover each cell once/],
    [source => source.routes.extremum.steps[0].present.expected_answer.cell = ['separable', 'nowhere'], /Invalid expected cell/],
  ];
  for (const [change, error] of cases) {
    await fs.writeFile(path.join(root, SOURCE_PATH), original);
    await edit(root, SOURCE_PATH, change);
    await assert.rejects(generateDemo({root}), error);
  }
});

test('missing templates fail and all inputs bind the reproducible bundle version', async t => {
  const root = await fixture(t);
  const first = await generateDemo({root});
  assert.deepEqual((await generateDemo({root})).outputs, first.outputs);
  const htmlPath = path.join(root, 'site/2/q01/index.html'), original = await fs.readFile(htmlPath, 'utf8');
  await fs.writeFile(htmlPath, original.replace('id="e_extremum-done"', 'id="missing-template"'));
  await assert.rejects(generateDemo({root}), /Missing page template: e_extremum-done/);
  await fs.writeFile(htmlPath, original.replace('配方求最大值', '配方求最大值（模板修订）'));
  assert.notEqual((await generateDemo({root})).bundle.bundleVersion, first.bundle.bundleVersion);
  await fs.writeFile(htmlPath, original);
  for (const [relative, change] of [
    [SOURCE_PATH, source => source.intro[0].question += '（修订）'],
    ['site/data/math-notation-v1/quadratic-always/q01.json', value => value.root.label = '原题'],
    ['site/data/knowledge-next/nodes/skill-quadratic-sign.json', value => value.summary += '（修订）'],
  ]) {
    const file = path.join(root, relative), old = await fs.readFile(file);
    await edit(root, relative, change);
    assert.notEqual((await generateDemo({root})).bundle.bundleVersion, first.bundle.bundleVersion, relative);
    await fs.writeFile(file, old);
  }
  await fs.appendFile(path.join(root, 'site/assets/practice/context.js'), '\n// grading version fixture\n');
  assert.notEqual((await generateDemo({root})).bundle.bundleVersion, first.bundle.bundleVersion);
});

test('--check reports missing and stale outputs without writing; output ownership is limited', async t => {
  const root = await fixture(t);
  await assert.rejects(publishDemo({root, check: true}), /Missing or stale/);
  await assert.rejects(fs.stat(path.join(root, BUNDLE_PATH)), /ENOENT/);
  await publishDemo({root});
  assert.equal((await publishDemo({root, check: true})).changed, 0);
  const unrelated = path.join(root, 'site/data/graph-walk/notes.txt');
  await fs.writeFile(unrelated, 'handwritten');
  await fs.writeFile(path.join(root, PAGE_PATH), 'stale');
  await assert.rejects(publishDemo({root, check: true}), /Missing or stale/);
  assert.equal(await fs.readFile(path.join(root, PAGE_PATH), 'utf8'), 'stale');
  await publishDemo({root});
  assert.equal(await fs.readFile(unrelated, 'utf8'), 'handwritten');
});
