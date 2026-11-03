#!/usr/bin/env node
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';
import {isDeepStrictEqual} from 'node:util';
import {loadSources, repoRoot} from './lib/public-knowledge-sources.mjs';
import {loadTeaching} from './lib/public-knowledge-teaching.mjs';
import {digest} from './lib/public-knowledge-export.mjs';
import {validateGraph, splitRef, anchors, nodeHref} from '../site/assets/knowledge-next/model.mjs';
import {lanesLayout} from '../site/assets/knowledge-next/layout.mjs';

export const SOURCE_PATH = 'site/data/graph-walk/quadratic-always-q01.source.json';
export const BUNDLE_PATH = 'site/data/graph-walk/quadratic-always-q01.json';
export const PAGE_PATH = 'site/lab/graph-walk/quadratic-always-q01/index.html';
const PAGE_TEMPLATE = 'tools/templates/graph-walk.html';
const COMPILER = 'server/tools/compile_graph_walk_notation.py';
const assert = (ok, message) => { if (!ok) throw Error(message); };
const unique = list => [...new Set(list)];
const strings = value => typeof value === 'string' ? [value] : value && typeof value === 'object' ? Object.values(value).flatMap(strings) : [];
const json = async file => JSON.parse(await fs.readFile(file, 'utf8'));
const normalizeText = text => text.replaceAll('\\\\', '\\').replace(/\s+/g, ' ').trim();

function localPath(root, relative) {
  assert(typeof relative === 'string' && relative && !path.isAbsolute(relative), `Expected repository path: ${relative}`);
  const file = path.resolve(root, relative);
  assert(file.startsWith(path.resolve(root) + path.sep), `Path escapes repository: ${relative}`);
  return file;
}

export function compileNotation(candidate, root = repoRoot) {
  const python = process.env.GRAPH_WALK_PYTHON || path.join(repoRoot, 'server/.venv/bin/python');
  try {
    return JSON.parse(execFileSync(python, [localPath(root, COMPILER)], {
      input: JSON.stringify(candidate), encoding: 'utf8', maxBuffer: 4 * 1024 * 1024,
      env: {...process.env, PYTHONDONTWRITEBYTECODE: '1'},
    }));
  } catch (error) {
    throw Error(`Notation validation failed: ${error.stderr?.toString().trim() || error.message}`);
  }
}

async function versionSources(root) {
  const compilerDir = 'server/shuxueshuo_server/problem_understanding';
  const names = (await fs.readdir(localPath(root, compilerDir))).filter(name => name.endsWith('.py')).sort();
  const files = [
    'tools/build-graph-walk-demo.mjs', COMPILER, 'internal/schemas/problem-math-notation-v1.schema.json',
    'site/assets/practice/context.js', 'site/assets/graph-walk/walk-state.mjs',
    'site/assets/knowledge-next/model.mjs', 'site/assets/knowledge-next/layout.mjs',
    ...names.map(name => `${compilerDir}/${name}`),
  ];
  return Object.fromEntries(await Promise.all(files.map(async file => [file, await fs.readFile(localPath(root, file), 'utf8')])));
}

function checkDecision(decision) {
  const {interaction: input, expected_answer: expected} = decision;
  assert(decision.id && decision.title && decision.question && input && expected, 'Incomplete decision');
  assert(['multi', 'choice', 'checklist', 'fill', 'plane', 'grid'].includes(input.type), `Unsupported interaction: ${decision.id}`);
  if (input.type === 'grid') {
    const [x, y] = expected.cell || [];
    assert(input.x.options.some(option => option.value === x) && input.y.options.some(option => option.value === y), `Invalid expected cell: ${decision.id}`);
    assert(['x', 'y'].every(key => decision.feedback?.[key]), `Missing grid feedback: ${decision.id}`);
    // Every cell belongs to exactly one zone, so the map has no blank or doubly labelled squares.
    const cells = input.zones.flatMap(zone => zone.cells.map(cell => cell.join('|')));
    const all = input.x.options.flatMap(column => input.y.options.map(row => `${column.value}|${row.value}`));
    assert(input.zones.every(zone => zone.value && zone.label) && cells.length === all.length && all.every(cell => cells.includes(cell)), `Grid zones must cover each cell once: ${decision.id}`);
  } else if (input.type === 'plane') {
    const [x, y] = expected.cell || [];
    assert(input.x.options.some(option => option.value === x) && input.y.options.some(option => option.value === y), `Invalid expected cell: ${decision.id}`);
    assert(['x', 'y', 'method'].every(key => decision.feedback?.[key]), `Missing plane feedback: ${decision.id}`);
  } else if (['multi', 'choice'].includes(input.type)) {
    const values = input.options.map(option => option.value);
    assert(new Set(values).size === values.length, `Duplicate options: ${decision.id}`);
    assert(input.options.every(option => typeof option.label === 'string'), `Missing option label: ${decision.id}`);
    const graphs = input.options.filter(option => option.graph);
    assert(!graphs.length || (graphs.length === input.options.length && graphs.every(({graph}) => typeof graph.coefficient === 'number' && graph.vertex?.length === 2 && graph.bounds?.length === 4)), `Incomplete graph options: ${decision.id}`);
    if (input.type === 'multi') {
      assert(expected.required.length && expected.required.every(value => expected.allowed.includes(value)), `Invalid required options: ${decision.id}`);
      assert(expected.allowed.every(value => values.includes(value)), `Unknown allowed option: ${decision.id}`);
    } else {
      assert(expected.one_of?.length && expected.one_of.every(value => values.includes(value)), `Unknown expected option: ${decision.id}`);
    }
  } else {
    const slots = input.slots || expected.terms.map(() => ({options: input.terms.map(value => ({value}))}));
    assert(slots.length === expected.terms.length && slots.every((slot, i) => slot.options.some(option => option.value === expected.terms[i])), `Invalid expected terms: ${decision.id}`);
  }
  assert(decision.effects?.log && decision.effects.results.every(result => typeof result === 'string'), `Missing effects: ${decision.id}`);
}

function checkVerdict(verdict, location) {
  // superseded: mathematically valid, but a more direct method covers the same case.
  assert(verdict && ['fit', 'superseded', 'unfit', 'not_triggered', 'pending'].includes(verdict.value) && verdict.message, `Missing verdict: ${location}`);
  if (verdict.value === 'pending') assert(verdict.next, `Pending verdict needs a next step: ${location}`);
}

function extractTemplates(html, decisions, completion) {
  const available = new Map();
  for (const match of html.matchAll(/<template\b[^>]*\bid="([^"]+)"[^>]*>([\s\S]*?)<\/template>/g)) {
    assert(!available.has(match[1]), `Duplicate template: ${match[1]}`);
    available.set(match[1], match[2].trim());
  }
  const refs = unique([...decisions.flatMap(decision => [decision.display, decision.board, ...strings(decision.attempt_calculations)]), completion].filter(Boolean));
  for (const ref of refs) assert(available.has(ref), `Missing page template: ${ref}`);
  return Object.fromEntries(refs.sort().map(ref => [ref, available.get(ref)]));
}

// The builder reads originals and teaching contracts. It never uses generated
// public graph projections, which intentionally omit conditional call details.
export async function generateDemo({root = repoRoot, sourcePath = SOURCE_PATH} = {}) {
  const source = await json(localPath(root, sourcePath));
  assert(source.schemaVersion === 1 && source.problemId === 'quadratic-always-q01', 'Unsupported demo source');
  const {nodes, manifest} = await loadSources(root);
  const edges = validateGraph(nodes, manifest);
  const byId = new Map(nodes.map(node => [node.id, node]));
  const byEdge = new Map(edges.map(edge => [edge.id, edge]));
  const teaching = await loadTeaching(root, nodes, manifest);
  const page = teaching.lessons.get(source.problemId);
  const topicProblem = teaching.topics.flatMap(topic => Object.entries(topic.problems)).find(([id]) => id === source.problemId)?.[1];
  assert(page && topicProblem?.path === source.page, 'Demo page does not match authored topic');
  const teacher = await json(localPath(root, `server/shuxueshuo_server/tutor_demo/lessons/${source.problemId}.json`));
  const candidate = await json(localPath(root, source.notation));
  assert(normalizeText(candidate.original_text) === normalizeText(teacher.problem.statement), 'Notation original text differs from teacher problem');
  const notation = compileNotation(candidate, root);
  assert(notation.root && notation.semantic, 'Missing compiled notation');
  const selected = new Set();
  const include = id => { assert(byId.has(id), `Unknown node: ${id}`); selected.add(id); return byId.get(id); };
  const findEdge = (from, type, to) => {
    const edge = byEdge.get(`${from}|${type}|${to}`);
    assert(edge, `Missing graph edge: ${from}|${type}|${to}`);
    include(from); include(to);
    return edge;
  };
  const checkBasis = (skill, ref) => {
    const {id, entry} = splitRef(ref), node = include(id);
    assert(node.kind === 'knowledge' && entry && anchors(node).some(item => item.id === entry), `Invalid knowledge entry: ${ref}`);
    assert(skill.kind === 'skill' && skill.basis.includes(ref), `Basis not used by skill: ${skill.id}/${ref}`);
    const edge = findEdge(skill.id, 'uses', id);
    assert(edge.occurrences.some(occurrence => occurrence.entry === entry), `Missing basis occurrence: ${ref}`);
    return edge.id;
  };
  const matchCall = call => {
    const method = include(call.method), target = include(call.ref);
    assert(method.kind === 'method' && ['method', 'skill'].includes(target.kind), `Wrong call type: ${call.method}/${call.ref}`);
    const step = method.steps.find(step => step.id === call.step);
    assert(step, `Unknown method step: ${call.method}#${call.step}`);
    const callIndex = (step.calls || []).findIndex(item => item.ref === call.ref);
    assert(callIndex !== -1, `Call not in template: ${call.method}#${call.step}/${call.ref}`);
    const edge = findEdge(call.method, 'calls', call.ref);
    const occurrenceIndex = edge.occurrences.findIndex(item => item.step === call.step && item.when === (step.calls[callIndex].when || ''));
    assert(occurrenceIndex !== -1, `Missing call occurrence: ${call.method}#${call.step}/${call.ref}`);
    assert(Array.isArray(call.usedBasis) && unique(call.usedBasis).length === call.usedBasis.length, 'Call needs distinct usedBasis');
    const basisEdges = call.usedBasis.map(ref => checkBasis(target, ref));
    return {...structuredClone(call), edge: edge.id, occurrence: occurrenceIndex, callIndex, basisEdges};
  };

  const intro = [], queryResults = {};
  let primary, rule;
  for (const authored of source.intro) {
    const {results = [], ...rest} = structuredClone(authored);
    const decision = {...rest, source: 'authored'};
    const q = authored.query;
    assert(q && !queryResults[authored.id], `Invalid query: ${authored.id}`);
    const effects = {nodes: [], edges: [], calls: [], results, log: ''};
    if (q.op === 'reverse') {
      assert(q.relation === 'involves', 'Unsupported reverse relation');
      q.from.forEach(id => assert(include(id).kind === 'knowledge', `Not a knowledge clue: ${id}`));
      const counts = new Map();
      for (const edge of edges.filter(edge => edge.type === q.relation && q.from.includes(edge.to))) counts.set(edge.from, (counts.get(edge.from) || 0) + 1);
      const ranked = [...counts].map(([id, coverage]) => ({id, coverage})).sort((a, b) => b.coverage - a.coverage || a.id.localeCompare(b.id));
      ranked.forEach(item => include(item.id));
      assert(ranked.length, 'No candidate types');
      queryResults[decision.id] = ranked;
      decision.candidateNodes = unique([...q.from, ...ranked.map(item => item.id)]);
      decision.candidates = ranked;
      effects.nodes = q.from;
      effects.log = `图谱查询：从 ${q.from.length} 个知识线索反查，找到 ${ranked.length} 个相关题型；最高覆盖 ${ranked[0].coverage}/${q.from.length}。`;
    } else if (q.op === 'rank_types') {
      const previous = queryResults[q.from];
      assert(previous?.length, `Unreachable decision query: ${decision.id}`);
      const winners = previous.filter(item => item.coverage === previous[0].coverage).map(item => item.id);
      const candidates = unique([...winners, ...(q.withConfuse ? winners.flatMap(id => (byId.get(id).confuse || []).map(item => item.ref)) : [])]);
      candidates.forEach(include);
      candidates.forEach(id => checkVerdict(authored.verdicts?.[id], `${decision.id}/${id}`));
      decision.interaction.options = candidates.map(id => ({value: id, label: byId.get(id).label}));
      decision.candidateNodes = candidates;
      decision.alternatives = Object.fromEntries(candidates.filter(id => authored.verdicts[id].implemented === false).map(id => [id, {message: authored.verdicts[id].message, href: nodeHref(id)}]));
      primary = decision.expected_answer.one_of[0];
      assert(winners.includes(primary), 'Primary type is not a highest-coverage candidate');
      effects.nodes = [primary];
      effects.edges = source.intro.find(item => item.id === q.from).query.from.map(id => findEdge(primary, 'involves', id).id);
      effects.log = `作答判断：选择主要题型「${byId.get(primary).label}」；另外 ${candidates.length - 1} 个题型保留为对照。`;
      queryResults[decision.id] = candidates;
    } else if (q.op === 'method_rule') {
      assert(q.from === primary, 'Method rule query must follow the selected type');
      const rules = edges.filter(edge => edge.from === primary && edge.type === 'method_rule');
      assert(rules.length === 1, 'Q01 requires one authored method-selection entry');
      rule = include(rules[0].to);
      assert(rule.subtype === 'method_selection', 'Not a method selection rule');
      // The plane cell is the student's judgment; each rule branch covers authored cells and
      // the methods covering the expected cell must be exactly the branches judged "fit".
      const input = decision.interaction;
      assert(input.type === 'plane', 'Method selection uses the plane interaction');
      const onAxis = (axis, value) => input[axis].options.some(option => option.value === value);
      const coverage = input.coverage || {};
      assert(isDeepStrictEqual(Object.keys(coverage).sort(), rule.branches.map(branch => branch.id).sort()), 'Coverage must list exactly the rule branches');
      input.methods = rule.branches.map(branch => {
        checkVerdict(authored.verdicts?.[branch.id], `${decision.id}/${branch.id}`);
        findEdge(rule.id, 'selects', branch.target);
        const cells = coverage[branch.id];
        assert(cells.length && cells.every(([x, y]) => onAxis('x', x) && onAxis('y', y)), `Invalid coverage: ${branch.id}`);
        const route = Object.entries(source.routes).find(([, item]) => item.branch === branch.id);
        if (route) assert(route[1].method === branch.target, `Route does not match rule branch: ${route[0]}`);
        return {value: branch.id, label: byId.get(branch.target).label, target: branch.target, cells, ...(route ? {route: route[0]} : {})};
      });
      delete input.coverage;
      for (const id of Object.keys(source.routes)) assert(input.methods.some(method => method.route === id), `Route does not match rule branch: ${id}`);
      const [cellX, cellY] = decision.expected_answer.cell;
      const here = input.methods.filter(method => method.cells.some(([x, y]) => x === cellX && y === cellY));
      const fit = rule.branches.filter(branch => authored.verdicts[branch.id].value === 'fit').map(branch => branch.id);
      assert(isDeepStrictEqual(here.map(method => method.value), fit), 'Plane coverage of the expected cell differs from the authored verdicts');
      assert(here.some(method => method.route), 'Expected cell offers no implemented route');
      decision.alternatives = Object.fromEntries(here.filter(method => !method.route).map(method => [method.value, {message: authored.verdicts[method.value].message, href: nodeHref(method.target)}]));
      decision.candidateNodes = [rule.id, ...rule.branches.map(branch => branch.target)];
      effects.nodes = [primary, rule.id];
      effects.edges = [rules[0].id];
      effects.log = `图谱查询：进入「${rule.label}」，本题这一格有 ${here.length} 种方法可用。`;
      queryResults[decision.id] = rule.branches;
    } else throw Error(`Unsupported query: ${q.op}`);
    decision.effects = effects;
    checkDecision(decision);
    intro.push(decision);
  }
  assert(isDeepStrictEqual(intro.map(decision => decision.id), ['D1', 'D2', 'D3']), 'Demo entry sequence is incomplete');

  const routes = {};
  const decisionIds = new Set(intro.map(decision => decision.id));
  for (const [id, authoredRoute] of Object.entries(source.routes)) {
    assert(id === authoredRoute.id && page.routes[id], `Unknown page route: ${id}`);
    // A route may omit page steps the Demo already settles earlier (e.g. by the method plane).
    const omitted = authoredRoute.omit || [];
    assert(omitted.every(step => page.routes[id].some(item => item.id === step)), `Unknown omitted step: ${id}`);
    assert(isDeepStrictEqual(authoredRoute.steps.map(step => step.id), page.routes[id].map(step => step.id).filter(step => !omitted.includes(step))), `Page steps or order changed: ${id}`);
    const method = include(authoredRoute.method);
    assert(method.kind === 'method' && topicProblem.routes[id].methods.includes(method.id), `Route method mismatch: ${id}`);
    const steps = [];
    const availableResults = new Set(intro.map(decision => decision.id));
    for (const mapping of authoredRoute.steps) {
      assert(!decisionIds.has(mapping.id), `Duplicate decision: ${mapping.id}`);
      decisionIds.add(mapping.id);
      assert((mapping.requires || []).every(id => availableResults.has(id)), `Future or cross-route result: ${mapping.id}`);
      const pageStep = page.routes[id].find(step => step.id === mapping.id);
      const decision = {...structuredClone(pageStep), source: 'page', templateSteps: structuredClone(mapping.templateSteps)};
      // Discard legacy graph tip identities. Public references are derived below.
      delete decision.tip;
      // The Demo may ask the same page step differently (e.g. by picking graphs); the completed display stays the page's.
      if (mapping.present) {
        assert(Object.keys(mapping.present).every(key => ['question', 'interaction', 'expected_answer', 'feedback'].includes(key)), `Unsupported presentation override: ${mapping.id}`);
        Object.assign(decision, structuredClone(mapping.present));
      }
      const activeMethods = new Set([method.id]);
      const calls = [];
      for (const call of mapping.effects.calls) {
        assert(activeMethods.has(call.method), `Submethod not called by this step: ${call.method}/${mapping.id}`);
        const actual = matchCall(call);
        calls.push(actual);
        if (byId.get(call.ref).kind === 'method') activeMethods.add(call.ref);
      }
      const candidates = new Set([method.id]);
      for (const location of mapping.templateSteps) {
        const owner = include(location.method);
        const step = owner.steps?.find(step => step.id === location.step);
        assert(activeMethods.has(owner.id) && step, `Invalid template step: ${owner.id}#${location.step}`);
        for (const call of step.calls || []) { include(call.ref); candidates.add(call.ref); }
      }
      for (const call of calls) { candidates.add(call.method); candidates.add(call.ref); }
      decision.candidateNodes = [...candidates];
      decision.skippedCalls = (mapping.skippedCalls || []).map(call => {
        assert(activeMethods.has(call.method), `Skipped call outside this step: ${call.method}`);
        return matchCall(call);
      });
      decision.effects = {
        ...structuredClone(mapping.effects),
        nodes: unique([method.id, ...calls.flatMap(call => [call.method, call.ref]), ...calls.flatMap(call => call.usedBasis.map(ref => splitRef(ref).id))]),
        edges: unique(calls.flatMap(call => [call.edge, ...call.basisEdges])), calls,
      };
      assert(!mapping.effects.nodes && !mapping.effects.edges, 'Execution edges must be derived, not authored');
      checkDecision(decision);
      steps.push(decision);
      availableResults.add(mapping.id);
    }
    assert(typeof authoredRoute.takeaway === 'string' && authoredRoute.takeaway, `Missing route takeaway: ${id}`);
    routes[id] = {id, label: method.label, method: method.id, branch: authoredRoute.branch, takeaway: authoredRoute.takeaway, steps};
  }
  const html = await fs.readFile(localPath(root, `site${source.page}index.html`), 'utf8');
  const templates = extractTemplates(html, Object.values(routes).flatMap(route => route.steps), page.completion);
  // The Demo shows its own short completion; the page card only vouches for the answer.
  const completion = source.completion;
  assert(typeof completion?.answer === 'string' && templates[page.completion]?.includes(completion.answer), 'Completion answer differs from the page');
  assert(completion.back?.href && completion.back?.label, 'Missing completion return link');
  delete templates[page.completion];
  const graphNodes = nodes.filter(node => selected.has(node.id));
  const graphEdges = edges.filter(edge => selected.has(edge.from) && selected.has(edge.to));
  const graphVersion = digest({nodes: graphNodes, edges: graphEdges});
  const clues = new Set(source.intro[0].query.from);
  const primaryMethods = new Set(rule.branches.map(branch => branch.target));
  const layout = lanesLayout(graphNodes, graphEdges, [
    {label: '知识线索', test: node => clues.has(node.id)},
    {label: '题型', test: node => node.kind === 'problem_type'},
    {label: '选法判断', test: node => node.kind === 'judgment_rule'},
    {label: '方法', test: node => primaryMethods.has(node.id)},
    {label: '技能与子方法', test: node => ['method', 'skill'].includes(node.kind)},
    {label: '数学依据', test: node => node.kind === 'knowledge'},
  ]);
  const shell = await fs.readFile(localPath(root, PAGE_TEMPLATE), 'utf8');
  const versions = await versionSources(root);
  const bundleVersion = digest({source, candidate, notation, graphVersion, page, templates, shell, versions});
  const bundle = {
    schemaVersion: 1, problemId: source.problemId, bundleVersion, graphVersion,
    problem: {text: normalizeText(candidate.original_text), root: notation.root},
    notation: {path: source.notation, version: digest(candidate), semantic: notation.semantic, sourceLocations: notation.source_locations},
    intro, routes, templates, completion: structuredClone(completion),
    graph: {nodes: graphNodes, edges: graphEdges, layout: {...layout, positions: Object.fromEntries(layout.positions)}},
    provenance: {judgments: 'authored', queries: 'computed', compilerVersion: digest(versions)},
  };
  return {bundle, outputs: new Map([[BUNDLE_PATH, JSON.stringify(bundle, null, 2) + '\n'], [PAGE_PATH, shell]])};
}

export async function publishDemo({root = repoRoot, check = false} = {}) {
  const {bundle, outputs} = await generateDemo({root});
  const changed = [];
  for (const [relative, body] of outputs) {
    let old;
    try { old = await fs.readFile(localPath(root, relative), 'utf8'); } catch (error) { if (error.code !== 'ENOENT') throw error; }
    if (old !== body) changed.push(relative);
  }
  if (check && changed.length) throw Error(`Missing or stale demo output: ${changed.join(', ')}`);
  if (!check) for (const relative of changed) {
    const file = localPath(root, relative);
    await fs.mkdir(path.dirname(file), {recursive: true});
    await fs.writeFile(file, outputs.get(relative));
  }
  return {changed: changed.length, bundleVersion: bundle.bundleVersion, graphVersion: bundle.graphVersion};
}

if (process.argv[1] && await fs.realpath(process.argv[1]) === await fs.realpath(fileURLToPath(import.meta.url))) {
  try {
    assert(process.argv.slice(2).every(arg => arg === '--check'), 'Usage: node tools/build-graph-walk-demo.mjs [--check]');
    console.log(JSON.stringify(await publishDemo({check: process.argv.includes('--check')})));
  } catch (error) { console.error(error.message); process.exitCode = 1; }
}
