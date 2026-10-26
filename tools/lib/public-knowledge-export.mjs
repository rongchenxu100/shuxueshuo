import fs from 'node:fs/promises';
import path from 'node:path';
import { topicPath } from './public-knowledge-teaching.mjs';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import { branches } from '../../site/assets/knowledge-next/teaching-model.mjs';

export function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object')
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonical(value[key])]));
  return value;
}
export const digest = (value) => createHash('sha256').update(JSON.stringify(canonical(value))).digest('hex');
// JSON.stringify reorders integer-like object keys after canonical(); serialize
// keys explicitly for the cross-language release checksum (e.g. term labels -1,0,1).
function stableJson(value) {
  if (Array.isArray(value)) return '[' + value.map(stableJson).join(',') + ']';
  if (value && typeof value === 'object')
    return '{' + Object.keys(value).sort().map((key) => JSON.stringify(key) + ':' + stableJson(value[key])).join(',') + '}';
  return JSON.stringify(value);
}
export const contentDigest = (value) => createHash('sha256').update(stableJson(value)).digest('hex');
const read = async (file) => JSON.parse(await fs.readFile(file, 'utf8'));

export async function resourceMetadata(root, resources) {
  const result = {};
  for (const [id, authored] of Object.entries(resources)) {
    const resource = structuredClone(authored);
    if (!resource.module.startsWith('/') || resource.module.includes('..')) throw Error(`Invalid resource ${id}`);
    const file = path.join(root, 'site', resource.module);
    const module = (await import(pathToFileURL(file).href)).default;
    if (module.stylesheet) {
      const relative = path.relative(path.dirname(await fs.realpath(file)), fileURLToPath(module.stylesheet));
      resource.stylesheet = path.posix.join(path.posix.dirname(resource.module), relative.split(path.sep).join('/'));
      if (!resource.stylesheet.startsWith('/') || resource.stylesheet.startsWith('//')) throw Error(`Resource stylesheet escapes site: ${id}`);
    }
    const hash = createHash('sha256').update(await fs.readFile(file));
    if (resource.stylesheet) hash.update(await fs.readFile(path.join(root, 'site', resource.stylesheet)));
    resource.version = hash.digest('hex').slice(0, 12);
    result[id] = resource;
  }
  return result;
}

// Ignore pedagogical prose when deciding whether an in-flight association changed.
function associations(route) {
  const tips = (tip) => {
    if (!tip) return null;
    if (tip.field) return { field: tip.field, options: Object.fromEntries(Object.entries(tip.options).map(([k, v]) => [k, tips(v)])) };
    return { ref: tip.ref, resource: tip.resource || null, case: tip.case || null };
  };
  return { methods: route.methods, steps: Object.fromEntries(Object.entries(route.steps).map(([id, s]) => [id, { refs: s.refs, tip: tips(s.tip) }])) };
}

// This export contains private grading data. It is consumed by the management
// process over stdout, never copied into site/ or the static outputs map.
export async function exportRows(root, { nodes, edges, manifest, teaching }) {
  const rows = Object.fromEntries([
    'knowledge_nodes', 'knowledge_entries', 'knowledge_edges', 'knowledge_resources',
    'practice_topics', 'practice_problems', 'practice_topic_problems', 'practice_problem_types',
    'practice_routes', 'practice_steps', 'practice_step_nodes', 'knowledge_drill_items'
  ].map((name) => [name, []]));
  for (const node of nodes) {
    rows.knowledge_nodes.push({ id: node.id, label: node.label, kind: node.kind, subtype: node.subtype || null,
      summary: node.summary, explanation_md: node.summary, sheet: null, aliases: node.aliases || [], body: node, is_active: true });
    for (const [key, type] of [['entries', 'entry'], ['operations', 'operation'], ['steps', 'step'], ['branches', 'branch']])
      (node[key] || []).forEach((entry, position) => rows.knowledge_entries.push({ node_id: node.id, entry_id: entry.id,
        entry_type: type, title: entry.title, position, body: entry, is_active: true }));
  }
  rows.knowledge_edges = edges.map((edge) => ({ source_id: edge.from, target_id: edge.to, relation_type: edge.type, occurrences: edge.occurrences }));
  const resources = await resourceMetadata(root, manifest.resources);
  rows.knowledge_resources = Object.entries(resources).map(([id, body]) => ({ id, body, version: body.version, is_active: true }));
  for (const topic of teaching.topics) {
    const { problems, ...body } = topic;
    rows.practice_topics.push({ id: topic.id, label: topic.label, path: topicPath(topic), body, groups: topic.groups, is_active: true });
    for (const [position, [pid, problem]] of Object.entries(problems).entries()) {
      const native = problem.runtime === 'graph-walk' ? teaching.lessons.get(pid) : null;
      const teacher = native ? null : await read(path.join(root, `server/shuxueshuo_server/tutor_demo/lessons/${pid}.json`));
      const contracts = native || Object.fromEntries(Object.entries(teacher.routes).map(([rid, route]) => [rid,
        route.nodes.map(({ tip, ...node }) => node)]));
      const contract_hash = native ? digest(native) : digest({ problem: teacher.problem, version: teacher.version, methods: teacher.methods, routes: contracts });
      const association_hash = digest({ types: problem.types, routes: Object.fromEntries(Object.entries(problem.routes).map(([rid, route]) => [rid, associations(route)])) });
      rows.practice_problems.push({ id: pid, label: problem.label, path: problem.path, lesson_file: `${pid}.json`,
        statement_md: native ? problem.statement : teacher.problem.statement,
        problem_data: native ? {statement: problem.statement, contract_hash, _graph_walk: native}
          : { ...teacher.problem, contract_hash, _lesson: teacher }, contract_hash, association_hash, is_active: true });
      rows.practice_topic_problems.push({ topic_id: topic.id, problem_id: pid, position });
      rows.practice_problem_types.push(...problem.types.map((node_id) => ({ problem_id: pid, node_id })));
      for (const [route_id, route] of Object.entries(problem.routes)) {
        rows.practice_routes.push({ problem_id: pid, route_id, label: route.label, methods: route.methods,
          association_hash: digest({ types: problem.types, ...associations(route) }), is_active: true });
        for (const [step_id, step] of Object.entries(route.steps)) {
          rows.practice_steps.push({ problem_id: pid, route_id, step_id, title: step.title, position: step.position,
            refs: step.refs, tip: step.tip || null, reason: step.reason || null, is_active: true });
          for (const node_id of new Set(branches(step.refs).flatMap((b) => b.value).map((ref) => ref.split('#')[0])))
            rows.practice_step_nodes.push({ problem_id: pid, route_id, step_id, node_id });
        }
      }
    }
  }
  const dir = path.join(root, 'server/shuxueshuo_server/learning/drills-next/sets');
  for (const name of (await fs.readdir(dir)).filter((f) => f.endsWith('.json')).sort()) {
    const set = await read(path.join(dir, name));
    for (const item of set.items) {
      const answer = Array.isArray(item.answer) ? item.answer : [item.answer];
      const content = { statement_md: [item.given, item.question].filter(Boolean).join('\n\n'), question_type: item.type,
        options: item.options, answer_spec: { selected: [...answer].sort() }, explanation_md: item.explanation || '' };
      rows.knowledge_drill_items.push({ node_id: set.node, item_id: item.id, entry_id: item.entry || null,
        origin: item.origin || {}, ...content, content_hash: digest(content), is_active: true });
    }
  }
  const counts = { nodes: nodes.length, edges: edges.length, ...teaching.counts, drills: rows.knowledge_drill_items.length,
    drill_nodes: teaching.drills.sets.length, eligible_drill_nodes: teaching.drills.sets.filter((set) => set.eligible).length };
  return { ...rows, _meta: { schema_version: 2, content_version: contentDigest(rows), counts } };
}
