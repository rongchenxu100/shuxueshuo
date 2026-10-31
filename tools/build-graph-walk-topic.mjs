#!/usr/bin/env node
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {repoRoot, loadSources} from './lib/public-knowledge-sources.mjs';
import {digest} from './lib/public-knowledge-export.mjs';
import {projectGraphWalkTeaching} from './lib/graph-walk-practice.mjs';
import {extendStreamBundle, createState, currentDecision, submitAnswer, replayState} from '../site/assets/graph-walk/walk-state.mjs';
import {expressionRegionsHTML} from '../site/assets/graph-walk/expression-regions.mjs';
import {domainNumberLineGraph, endpointChecksHTML} from '../site/assets/graph-walk/domain-visuals.mjs';
import {replayAnswer} from '../site/assets/graph-walk/walk-replay.mjs';

const assert = (ok, message) => { if (!ok) throw Error(message); };
const json = async file => JSON.parse(await fs.readFile(file, 'utf8'));
const SOURCE = 'site/data/graph-walk/function-concepts-q15.source.json';
const h = value => String(value).replace(/[&<>"']/g, ch => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[ch]));

function compileTarget(source, evidence, graph, nodes, targetRef) {
  assert(source.schemaVersion === 1 && /^[a-z][a-z0-9-]*$/.test(source.problemId), 'Invalid course source');
  assert(/^\/topics\/[a-z][a-z0-9-]*\/(?:q\d+[a-z]?|variant\d+)\/$/.test(source.page), 'Invalid topic problem path');
  assert(typeof source.title === 'string' && source.title.trim(), 'Missing course title');
  assert(/^\/topics\/[a-z][a-z0-9-]*\/$/.test(source.topicHref) && source.page.startsWith(source.topicHref), 'Invalid course topic');
  const goal = evidence.lesson?.goals?.find(item => item.target_ref === targetRef);
  assert(goal?.walk?.bundle && evidence.stream, 'Missing real lesson projection or committed stream');
  const base = structuredClone(goal.walk.bundle);
  base.problemId = source.problemId;
  // Independently published questions may omit the source's example/subquestion
  // labels. Keep that authored wording separate from the recorded evidence.
  if (source.statement !== undefined) {
    assert(typeof source.statement === 'string' && source.statement.trim(), 'Invalid course statement');
    base.problem.text = source.statement;
  }
  base.completion = {...base.completion, back: {href: source.topicHref, label: '返回专题'}};
  // Attach authored choice hints from current type nodes so rebuilt courses get
  // student-facing notes without re-recording every D2 evidence snapshot.
  const typeHints = new Map(nodes.filter(node => node.kind === 'problem_type' && node.choice_hint)
    .map(node => [node.id, node.choice_hint]));
  for (const step of base.intro || []) {
    if (step.id !== 'D2' || step.interaction?.type !== 'choice') continue;
    for (const option of step.interaction.options || []) {
      const hint = typeHints.get(option.value);
      if (hint) option.note = hint;
      else delete option.note;
    }
  }
  base.bundleVersion = digest(base);
  // Keep node metadata already captured by this course's execution. The live
  // graph supplies additional called nodes without rewriting older lessons
  // when a shared method later gains another supported branch.
  const capturedNodes = new Map(base.graph.nodes.map(node => [node.id, node]));
  const courseGraph = {...graph, nodes: graph.nodes.map(node => capturedNodes.get(node.id) || node)};
  const bundle = extendStreamBundle(base, evidence.stream, targetRef, courseGraph);
  // Unexpanded candidates remain selectable as uncovered alternatives in D3,
  // but cannot become published practice routes without verified steps.
  bundle.routes = Object.fromEntries(Object.entries(bundle.routes).filter(([, route]) => route.route_plan === 'planned'));
  projectGraphWalkTeaching(bundle, nodes);
  return bundle;
}

// Compose independently verified goals in order. Their mathematical identities
// and completion hashes remain attached to their original goal, never rewritten.
export function compileCourse(source, evidence, graph, nodes) {
  const targets = source.targetRefs || [source.targetRef];
  assert(targets.length && new Set(targets).size === targets.length, 'Invalid course targets');
  const parts = targets.map(ref => compileTarget(source, evidence, graph, nodes, ref));
  const bundle = parts[0];
  if (parts.length > 1) {
    const [routeId] = Object.keys(bundle.routes);
    const route = bundle.routes[routeId];
    assert(parts.every(part => Object.keys(part.routes).length === 1 && part.routes[routeId]?.method === route.method),
      'Sequential goals require the same verified method route');
    const completions = parts.map((part, index) => ({...structuredClone(part.routes[routeId].completion),
      title: source.targetTitles?.[index] || `目标 ${index + 1}`}));
    for (const [index, part] of parts.entries()) {
      for (const step of [...part.intro, ...part.routes[routeId].steps]) step.target_ref = targets[index];
      if (!index) continue;
      const read = structuredClone(part.intro.find(step => step.id === 'D1'));
      assert(read, 'Missing next-goal reading');
      read.id = `goal-${index + 1}-D1`;
      read.title = source.targetTitles?.[index] || `目标 ${index + 1}：读题`;
      const prerequisites = part.intro.filter(step => step.id === 'D3-domain').map(step => ({
        ...structuredClone(step), id: `goal-${index + 1}-${step.id}`,
      }));
      route.steps.push(read, ...prerequisites, ...part.routes[routeId].steps);
      bundle.stream.math_steps.push(...part.stream.math_steps);
      Object.assign(bundle.stream.step_calls, part.stream.step_calls);
      bundle.stream.interaction_states.push(...part.stream.interaction_states);
      bundle.stream.interactions.push(...part.stream.interactions);
    }
    // Each target projection contains only its own used graph. Union these
    // captured nodes/edges so a later target can introduce a new basis or skill.
    const mergeGraphEntries = key => {
      const merged = new Map();
      for (const part of parts) for (const entry of part.graph[key]) {
        const previous = merged.get(entry.id);
        assert(!previous || digest(previous) === digest(entry), `Conflicting captured graph ${key}: ${entry.id}`);
        if (!previous) merged.set(entry.id, structuredClone(entry));
      }
      return [...merged.values()];
    };
    const lanes = new Map();
    for (const part of parts) for (const lane of part.graph.lanes || []) {
      const key = JSON.stringify([lane.label, lane.kind || null]);
      if (!lanes.has(key)) lanes.set(key, structuredClone(lane));
      else if (lane.ids) lanes.get(key).ids = [...new Set([...(lanes.get(key).ids || []), ...lane.ids])];
    }
    bundle.graph = {...bundle.graph, nodes: mergeGraphEntries('nodes'), edges: mergeGraphEntries('edges'), lanes: [...lanes.values()]};
    delete bundle.graph.layout;
    bundle.stream.target_refs = targets;
    route.goal_completions = completions;
    route.completion = {
      status: 'verified', available: true, composition: 'sequential_goals',
      run_id: bundle.stream.run_id, lesson_version: bundle.stream.lesson_version,
      target_ref: targets[0], target_refs: targets, route_id: routeId,
      answer: {kind: 'goal_group', status: 'complete', answers: completions.map(value =>
        ({target_ref: value.target_ref, title: value.title, answer: value.answer}))},
    };
    bundle.bundleVersion = digest(bundle);
    projectGraphWalkTeaching(bundle, nodes);
  }
  const routeIds = Object.keys(bundle.routes);
  assert(routeIds.length > 0, 'Static course requires a verified route');
  const actions = [];
  let state = createState(bundle);
  for (let step = currentDecision(bundle, state); step; step = currentDecision(bundle, state)) {
    if (step.source_regions) expressionRegionsHTML(step.source_regions);
    for (const line of step.condition_number_lines || []) domainNumberLineGraph(line);
    if (step.completion_number_line) domainNumberLineGraph(step.completion_number_line);
    endpointChecksHTML(step.endpoint_checks);
    const answer = replayAnswer(step, routeIds[0]);
    assert(answer !== null, `Unsupported replay interaction: ${step.id}`);
    const action = {decision: step.id, answer: structuredClone(answer)};
    actions.push(action);
    state = submitAnswer(bundle, state, action);
    assert(state.lastFeedback?.status === 'passed', `Verified contract cannot replay: ${step.id}`);
  }
  assert(state.done, 'Course does not reach verified completion');
  const replay = {schemaVersion: 2, problemId: bundle.problemId, bundleVersion: bundle.bundleVersion,
    status: 'completed', routes: [routeIds[0]], actions};
  replayState(bundle, replay);
  return {bundle, replay};
}

export async function generateCourse({root = repoRoot, sourcePath = SOURCE} = {}) {
  assert(/^site\/data\/graph-walk\/[a-z][a-z0-9-]*\.source\.json$/.test(sourcePath), 'Invalid course source path');
  const source = await json(path.join(root, sourcePath));
  assert(typeof source.evidence === 'string' && source.evidence.startsWith('site/data/graph-walk/') && !source.evidence.includes('..'), 'Invalid evidence path');
  const evidence = await json(path.join(root, source.evidence));
  const graph = await json(path.join(root, 'site/knowledge/graph.json'));
  const {nodes} = await loadSources(root);
  const {bundle, replay} = compileCourse(source, evidence, graph, nodes);
  const bundleUrl = `/data/graph-walk/${source.problemId}.json`, replayUrl = `/data/graph-walk/${source.problemId}.replay.json`;
  const config = {problemId: source.problemId, bundleUrl, replayUrl, topicHref: source.topicHref};
  let html = await fs.readFile(path.join(root, 'tools/templates/graph-walk.html'), 'utf8');
  html = html.replace('<body class="gw-page">', '<body class="gw-page" data-walk="mount">')
    .replace('/assets/practice/practice.css"', '/assets/practice/practice.css?v=20261028-choice-hint"')
    .replace('/assets/practice/components.js"', '/assets/practice/components.js?v=20261028-choice-hint"')
    .replace('/assets/graph-walk/walk.css"', '/assets/graph-walk/walk.css?v=20261031-derivation-stack"')
    .replace('<script type="module" src="/assets/graph-walk/walk.mjs"></script>',
      '<script type="module" src="/assets/auth/site-auth.js?v=4"></script>\n  <script type="module" src="/assets/graph-walk/topic-page.mjs?v=20261031-derivation-stack"></script>')
    .replace('<title>跟着图谱解一道题 · 数学说</title>', `<title>${h(source.title)} · 数学说</title>`)
    .replace('恒成立 Q01 · 解题过程', h(source.title))
    .replace('<h1>跟着图谱解一道题</h1>', `<h1>${h(source.title)}</h1>`)
    .replace('本页不保存学习记录。适用性结论由人工编写；候选与关联来自真实图谱查询。', '自己做与 AI 回放分别保留进度；登录后保存已确认的练习记录。')
    .replace('<small id="gw-version"></small>', '')
    .replace('<noscript><p class="gw-error">请启用 JavaScript 体验解题过程。也可以阅读<a href="/2/q01/?preview=1">原题的无记录练习</a>。</p></noscript>',
      `<noscript><p class="gw-error">请启用 JavaScript 完成练习，或<a href="${h(source.topicHref)}">返回专题</a>。</p></noscript>`)
    .replace('</body>', `<script type="application/json" id="graph-walk-page">${JSON.stringify(config).replaceAll('<', '\\u003c')}</script>\n</body>`);
  return new Map([[`site${bundleUrl}`, JSON.stringify(bundle, null, 2) + '\n'],
    [`site${replayUrl}`, JSON.stringify(replay, null, 2) + '\n'], [`site${source.page}index.html`, html]]);
}

export async function buildCourse({root = repoRoot, check = false, sourcePath = SOURCE} = {}) {
  const outputs = await generateCourse({root, sourcePath});
  let changed = 0;
  for (const [name, body] of outputs) {
    const file = path.join(root, name), previous = await fs.readFile(file, 'utf8').catch(error => { if (error.code !== 'ENOENT') throw error; return null; });
    if (previous === body) continue;
    if (check) throw Error(`Graph-walk topic artifact is missing or stale: ${name}`);
    await fs.mkdir(path.dirname(file), {recursive: true});
    await fs.writeFile(file, body); changed++;
  }
  return {changed};
}

export async function buildCourses({root = repoRoot, check = false} = {}) {
  const directory = 'site/data/knowledge-next/topics', problems = new Set();
  for (const name of (await fs.readdir(path.join(root, directory))).filter(name => name.endsWith('.json'))) {
    const topic = await json(path.join(root, directory, name));
    for (const [id, problem] of Object.entries(topic.problems || {})) {
      if (problem.runtime === 'graph-walk') problems.add(id);
    }
  }
  let changed = 0;
  for (const id of [...problems].sort()) {
    changed += (await buildCourse({root, check, sourcePath: `site/data/graph-walk/${id}.source.json`})).changed;
  }
  return {changed};
}

if (process.argv[1] && await fs.realpath(process.argv[1]).catch(() => null) === await fs.realpath(fileURLToPath(import.meta.url))) {
  try {
    const args = process.argv.slice(2), settings = {};
    for (let index = 0; index < args.length; index++) {
      if (args[index] === '--check') settings.check = true;
      else if (args[index] === '--source' && args[index + 1]) settings.sourcePath = args[++index];
      else throw Error('Usage: node tools/build-graph-walk-topic.mjs [--check] [--source site/data/graph-walk/id.source.json]');
    }
    console.log(JSON.stringify(await (settings.sourcePath ? buildCourse(settings) : buildCourses(settings))));
  }
  catch (error) { console.error(error.message); process.exitCode = 1; }
}
