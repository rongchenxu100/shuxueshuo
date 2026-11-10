// Shared by the static publisher and browser. IDs never determine node types.
export const KINDS = {collection: '知识集合', textbook: '教材', chapter: '章', section: '节', knowledge: '知识点', skill: '技能', method: '方法', problem_type: '题型', judgment_rule: '判断规则'};
export const RELATIONS = {contains: '包含', extends: '拓展', prerequisite: '前置于', involves: '涉及', candidate: '可选用', method_rule: '进入选法判断', calls: '调用', step_rule: '进入步骤判断', selects: '条件满足时选择', uses: '使用数学依据'};
export const VIEWS = {curriculum: '章节视图', knowledge: '知识关系', solution: '解题关系'};
export const VIEW_KINDS = {curriculum: Object.keys(KINDS), knowledge: ['knowledge','skill','problem_type'], solution: ['problem_type','judgment_rule','method','skill']};
const DETAIL_CONTENTS = {collection: '集合内容', textbook: '全书目录', chapter: '本章目录', section: '本节内容', knowledge: '知识条目与题例', skill: '操作步骤与题例', method: '完整步骤与例题', problem_type: '题型特征与题例', judgment_rule: '判断分支与题例'};
export const detailLabel = node => node.status === 'planned' ? '看题型特征' : node.status === 'knowledge_only' ? '看知识条目' : `看${DETAIL_CONTENTS[node.kind] || '完整详情'}`;
export const VIEW_RELATIONS = {curriculum: ['contains','extends','method_rule','step_rule'], knowledge: ['prerequisite','uses','involves'], solution: ['candidate','method_rule','calls','step_rule','selects']};
export const splitRef = ref => { const [id, entry] = ref.split('#'); return {id, entry}; };
export const nodeHref = ref => { const {id, entry} = splitRef(ref); return `/knowledge/${id}/${entry ? `#${entry}` : ''}`; };
export const chapterPath = id => `/knowledge/chapters/${id}/`;
export const groupPath = c => c.kind === 'collection' ? `/knowledge/collections/${c.id}/` : chapterPath(c.id);
export const chapterTag = c => c.kind === 'collection' ? c.label : `${c.book} · 第 ${c.number} 章`;
// knowledge_only is an authoring state; do not surface it on student-facing pages.
export const lifecycleLabel = n => n.status === 'planned' ? '题型建设中' : '';
export const ORG_KINDS = ['textbook', 'chapter', 'section', 'collection'];
export const RESERVED_PATHS = ['3d', 'assets', 'chapters', 'collections', 'nodes', 'topics', 'teaching'];
export const anchors = node => [...(node.entries || []), ...(node.steps || []), ...(node.operations || []), ...(node.branches || [])];

export function deriveEdges(nodes) {
  const edges = new Map();
  const add = (from, ref, type, occurrence = {}) => {
    const {id: to, entry} = splitRef(ref);
    const key = `${from}|${type}|${to}`;
    if (!edges.has(key)) edges.set(key, {id: key, from, to, type, occurrences: []});
    edges.get(key).occurrences.push({...occurrence, ...(entry ? {entry} : {})});
  };
  for (const n of nodes) {
    for (const m of n.members || []) add(n.id, m.ref, m.relation);
    for (const p of n.prerequisites || []) add(p, n.id, 'prerequisite');
    for (const k of n.knowledge || []) add(n.id, k, 'involves');
    for (const m of n.methods || []) add(n.id, m, 'candidate');
    for (const r of n.rules || []) add(n.id, r, 'method_rule');
    for (const b of n.basis || []) add(n.id, b, 'uses');
    if (n.kind === 'method') for (const s of n.steps || []) {
      for (const c of s.calls || []) add(n.id, c.ref, 'calls', {step: s.id, when: c.when || ''});
      if (s.rule) add(n.id, s.rule, 'step_rule', {step: s.id});
    }
    for (const b of n.branches || []) add(n.id, b.target, 'selects', {branch: b.id, condition: b.condition});
  }
  return [...edges.values()].sort((a, b) => a.id.localeCompare(b.id, 'en'));
}

const strings = v => typeof v === 'string' ? [v] : v && typeof v === 'object' ? Object.values(v).flatMap(strings) : [];

export function validateGraph(nodes, manifest) {
  const errors = [], byId = new Map();
  const err = (id, message) => errors.push(`${id}: ${message}`);
  const requireText = (n, key) => { if (typeof n[key] !== 'string' || !n[key].trim()) err(n.id, `缺少 ${key}`); };
  const requireList = (n, key) => { if (!Array.isArray(n[key]) || !n[key].length) err(n.id, `缺少 ${key}`); };
  for (const n of nodes) {
    if (!/^[a-z][a-z0-9-]*$/.test(n.id || '')) err(n.id, '非法 ID');
    if (byId.has(n.id)) err(n.id, '重复 ID');
    byId.set(n.id, n);
    if (!KINDS[n.kind]) err(n.id, '未知 kind');
    const planned = n.status === 'planned', knowledgeOnly = n.status === 'knowledge_only';
    if (n.status !== undefined && !['active', 'planned', 'knowledge_only'].includes(n.status)) err(n.id, '节点状态无效');
    if (planned && n.kind !== 'problem_type') err(n.id, 'planned 仅用于待建设题型');
    if (knowledgeOnly && n.kind !== 'knowledge') err(n.id, 'knowledge_only 仅用于知识点');
    if (planned) for (const key of ['methods', 'rules', 'examples']) if (!Array.isArray(n[key]) || n[key].length) err(n.id, `待建设题型的 ${key} 必须为空数组`);
    if (knowledgeOnly && (!Array.isArray(n.examples) || n.examples.length)) err(n.id, '知识录入状态的 examples 必须为空数组');
    ['label', 'summary', 'source'].forEach(k => requireText(n, k));
    if (/待补充|TODO|TBD/.test(JSON.stringify(n))) err(n.id, '正文含占位内容');
    if (strings(n).some(s => /[\u0000-\u001f]/.test(s))) err(n.id, '文字含控制字符（多半是 \\ne、\\frac、\\times 之类在 JSON 里少写了一个反斜杠）');
    const ids = new Set();
    for (const a of anchors(n)) {
      if (!/^[a-z][a-z0-9-]*$/.test(a.id || '') || ids.has(a.id)) err(n.id, '条目或步骤 ID 无效／重复');
      ids.add(a.id);
      requireText({...a, id: `${n.id}#${a.id}`}, 'title');
    }
    const required = {
      knowledge: ['entries', 'examples'], skill: ['operations', 'examples', 'basis'],
      method: ['steps', 'examples'], problem_type: ['knowledge', 'features', 'examples'],
      judgment_rule: ['branches', 'examples'], textbook: ['members'], chapter: ['members'], section: ['members'], collection: ['members'],
    }[n.kind] || [];
    required.filter(k => k !== 'examples' || !(planned || knowledgeOnly)).forEach(k => requireList(n, k));
    if (['skill', 'method', 'judgment_rule'].includes(n.kind)) ['input', 'output', 'conditions'].forEach(k => requireText(n, k));
    for (const item of [...(n.entries || []), ...(n.operations || []), ...(n.steps || [])]) {
      if (!Array.isArray(item.body) || !item.body.length || item.body.some(t => typeof t !== 'string' || !t.trim())) err(n.id, `缺少 ${item.id} 正文`);
    }
    for (const e of n.entries || []) if (!e.type || !e.conditions) err(n.id, `条目 ${e.id} 缺少类型／条件`);
    for (const e of n.examples || []) if (!e.title || !e.prompt || !e.source || !e.solution?.length) err(n.id, '例题不完整');
    // Titles feed the TOC, anchors and aria-labels as plain text; write math there in Unicode.
    for (const k of ['entries','operations','steps','branches','pitfalls','examples']) for (const e of n[k] || []) if (e.title?.includes('$')) err(n.id, `标题不能含公式：${e.title}`);
    for (const p of n.pitfalls || []) {
      if (!/^[a-z][a-z0-9-]*$/.test(p.id || '') || ids.has(p.id)) err(n.id, '易错 ID 无效／重复');
      ids.add(p.id);
      if (!p.title || !p.wrong || !p.why || !Array.isArray(p.fix) || !p.fix.length) err(n.id, `易错 ${p.id} 不完整`);
    }
    const tableSlots = new Set(['', ...anchors(n).map(a => a.id)]);
    if (n.input) tableSlots.add('contract');
    if (n.features) tableSlots.add('features');
    if (n.branches) tableSlots.add('branches');
    if (n.tables !== undefined && !Array.isArray(n.tables)) err(n.id, 'tables 必须为数组');
    if (n.tables?.length && ORG_KINDS.includes(n.kind)) err(n.id, '目录节点不展示表格');
    for (const t of Array.isArray(n.tables) ? n.tables : []) {
      if (!t || typeof t !== 'object') { err(n.id, '表格必须为对象'); continue; }
      if (!/^[a-z][a-z0-9-]*$/.test(t.id || '') || ids.has(t.id)) err(n.id, '表格 ID 无效／重复');
      ids.add(t.id);
      if (typeof t.title !== 'string' || !t.title.trim() || t.title.includes('$')) err(n.id, `表格 ${t.id} 缺少标题或标题含公式`);
      if (!tableSlots.has(t.after || '')) err(n.id, `表格 ${t.id} 的位置 ${t.after} 不存在`);
      if (!Array.isArray(t.columns) || t.columns.length < 2 || t.columns.some(c => typeof c !== 'string' || !c.trim()) || !Array.isArray(t.rows) || !t.rows.length) {
        err(n.id, `表格 ${t.id} 缺少表头或行`);
        continue;
      }
      for (const r of t.rows || []) {
        if (typeof r?.head !== 'string' || !r.head.trim() || !Array.isArray(r.cells) || r.cells.length !== t.columns.length - 1) {
          err(n.id, `表格 ${t.id} 的行与表头列数不符`);
          continue;
        }
        for (const c of r.cells) {
          if (typeof c === 'string' ? !c.trim() : typeof c?.ref !== 'string') err(n.id, `表格 ${t.id} 有空单元格`);
        }
      }
      if (t.notes && (!Array.isArray(t.notes) || t.notes.some(x => typeof x !== 'string' || !x.trim()))) err(n.id, `表格 ${t.id} 的注意事项无效`);
    }
    if (n.kind === 'problem_type' && !planned && !((n.methods || []).length || (n.rules || []).length)) err(n.id, '题型缺少方法入口');
    if (n.kind === 'judgment_rule' && !['method_selection', 'step_selection'].includes(n.subtype)) err(n.id, '规则子类无效');
    const allowedFields = {members: ORG_KINDS, prerequisites: ['knowledge'], knowledge: ['problem_type'], methods: ['problem_type'], rules: ['problem_type'], basis: ['skill'], steps: ['method'], branches: ['judgment_rule']};
    for (const [field, kinds] of Object.entries(allowedFields)) if (n[field] && !kinds.includes(n.kind)) err(n.id, `${n.kind} 不可维护 ${field}`);
  }
  function checkRef(owner, ref, kinds, withAnchor = false) {
    if (typeof ref !== 'string') { err(owner, '引用必须为字符串'); return; }
    const {id, entry} = splitRef(ref), target = byId.get(id);
    if (!target) return err(owner, `失效引用 ${ref}`);
    if (kinds && !kinds.includes(target.kind)) err(owner, `引用 ${ref} 类型不符`);
    if (entry && (!withAnchor || !anchors(target).some(a => a.id === entry))) err(owner, `失效条目 ${ref}`);
  }
  for (const n of nodes) {
    for (const m of n.members || []) {
      if (!['contains', 'extends'].includes(m.relation) || (n.kind !== 'section' && m.relation !== 'contains')) err(n.id, '目录关系无效');
      checkRef(n.id, m.ref, {textbook: ['chapter'], chapter: ['section'], section: ['knowledge','skill','method','problem_type'], collection: ['knowledge']}[n.kind]);
    }
    for (const entry of n.entries || []) if (entry.references !== undefined) {
      if (!Array.isArray(entry.references) || !entry.references.length || new Set(entry.references).size !== entry.references.length) err(n.id, '条目 references 必须为非空且不重复的引用');
      else for (const ref of entry.references) checkRef(n.id, ref, ['knowledge'], true);
    }
    for (const p of n.prerequisites || []) checkRef(n.id, p, ['knowledge']);
    for (const k of n.knowledge || []) checkRef(n.id, k, ['knowledge']);
    for (const b of n.basis || []) checkRef(n.id, b, ['knowledge'], true);
    for (const m of n.methods || []) checkRef(n.id, m, ['method']);
    for (const r of n.rules || []) { checkRef(n.id, r, ['judgment_rule']); if (byId.get(r)?.subtype !== 'method_selection') err(n.id, '题型只能进入选法规则'); }
    for (const s of n.steps || []) {
      for (const c of s.calls || []) checkRef(n.id, c.ref, ['skill','method']);
      if (s.rule) { checkRef(n.id, s.rule, ['judgment_rule']); if (byId.get(s.rule)?.subtype !== 'step_selection') err(n.id, '方法只能进入步骤选择规则'); }
    }
    for (const b of n.branches || []) {
      if (!b.condition) err(n.id, '规则缺少分支条件');
      checkRef(n.id, b.target, n.subtype === 'method_selection' ? ['method'] : ['skill','method']);
    }
    for (const r of n.resources || []) {
      if (!manifest.resources[r]) { err(n.id, `未登记资源 ${r}`); continue; }
      if (manifest.resources[r].title.includes('$')) err(n.id, `资源 ${r} 的标题不能含公式`);
      const after = manifest.resources[r].after;
      if (after && ![...(n.entries || []), ...(n.operations || []), ...(n.steps || [])].some(e => e.id === after)) err(n.id, `资源 ${r} 的位置条目 ${after} 不存在`);
    }
    for (const p of n.pitfalls || []) if (p.see) checkRef(n.id, p.see, ['knowledge','skill','method','problem_type','judgment_rule'], true);
    for (const t of Array.isArray(n.tables) ? n.tables : []) for (const r of Array.isArray(t?.rows) ? t.rows : []) for (const c of Array.isArray(r?.cells) ? r.cells : []) if (typeof c === 'object' && c) checkRef(n.id, c.ref, ['knowledge','skill','method','problem_type','judgment_rule'], true);
    if (n.pitfalls && !['knowledge','skill','method'].includes(n.kind)) err(n.id, `${n.kind} 不可维护 pitfalls`);
  }
  // Only prerequisites are a learning dependency DAG; mixed relations are not.
  const visiting = new Set(), visited = new Set();
  function visit(id) {
    if (visiting.has(id)) { err(id, '知识前置关系有环'); return; }
    if (visited.has(id)) return;
    visiting.add(id);
    for (const p of byId.get(id)?.prerequisites || []) visit(p);
    visiting.delete(id); visited.add(id);
  }
  nodes.filter(n => n.kind === 'knowledge').forEach(n => visit(n.id));
  for (const [kind, count] of Object.entries(manifest.expectedCounts || {})) if (nodes.filter(n => n.kind === kind).length !== count) err('catalog', `${kind} 应有 ${count} 个节点`);
  if (byId.get(manifest.defaultScope)?.kind !== 'section') err('catalog', '默认范围必须是节');
  for (const [old, ref] of Object.entries(manifest.resourceLinks || {})) checkRef(`resourceLinks.${old}`, ref, null, true);
  if (errors.length) throw new Error(errors.join('\n'));
  return deriveEdges(nodes);
}

export function inheritedKnowledge(id, nodes, edges, seen = new Set()) {
  if (seen.has(id)) return [];
  const nextSeen = new Set(seen).add(id), result = new Set();
  for (const e of edges.filter(e => e.from === id)) {
    if (e.type === 'uses') for (const o of e.occurrences) result.add(`${e.to}${o.entry ? `#${o.entry}` : ''}`);
    if (['calls', 'step_rule', 'selects'].includes(e.type)) for (const r of inheritedKnowledge(e.to, nodes, edges, nextSeen)) result.add(r);
  }
  return [...result].sort();
}

export function scopeMembers(graph, scope) {
  const ids = new Set([scope]);
  const addChildren = id => { for (const e of graph.edges.filter(e => e.from === id && ['contains','extends'].includes(e.type))) { if (!ids.has(e.to)) { ids.add(e.to); if (ORG_KINDS.includes(graph.nodes.find(n => n.id === e.to)?.kind)) addChildren(e.to); } } };
  addChildren(scope);
  // Include organization ancestors, and referenced rules, without inventing membership.
  let changed = true;
  while (changed) { changed = false; for (const e of graph.edges) {
    if ((e.type === 'contains' && ids.has(e.to) && ['textbook','chapter','collection'].includes(graph.nodes.find(n => n.id === e.from)?.kind)) || (['method_rule','step_rule'].includes(e.type) && ids.has(e.from))) {
      const id = e.type === 'contains' ? e.from : e.to;
      if (!ids.has(id)) { ids.add(id); changed = true; }
    }
  } }
  return ids;
}

// Curriculum view draws sections as frames: breadcrumbs above, members inside.
export function curriculumStructure(graph, scope) {
  const byId = new Map(graph.nodes.map(n => [n.id, n])), org = id => ORG_KINDS.includes(byId.get(id)?.kind);
  const children = id => graph.edges.filter(e => e.from === id && ['contains','extends'].includes(e.type)).map(e => ({id: e.to, relation: e.type}));
  const parentOf = id => graph.edges.find(e => e.type === 'contains' && e.to === id && ['textbook','chapter','collection'].includes(byId.get(e.from)?.kind))?.from;
  const node = byId.get(scope);
  let sections = [];
  if (['section','collection'].includes(node?.kind)) sections = [scope];
  else if (node?.kind === 'chapter') sections = children(scope).map(c => c.id);
  else if (node?.kind === 'textbook') sections = children(scope).flatMap(c => children(c.id)).map(c => c.id);
  const crumbs = [];
  for (let id = node?.kind === 'section' ? parentOf(scope) : scope; id; id = parentOf(id)) crumbs.unshift(id);
  return {crumbs, sections: sections.filter(id => ['section','collection'].includes(byId.get(id)?.kind)).map(id => ({id, label: byId.get(id).label, members: children(id).filter(m => !org(m.id))}))};
}

// On a chapter page, nodes living in another chapter are external; relation views also pull in the far
// end of cross-chapter relations so they stay visible without expanding.
export function projectGraph(graph, state, chapter = '') {
  const members = scopeMembers(graph, state.scope), ids = new Set(members), cross = new Set();
  for (const id of state.expanded || []) if (graph.nodes.some(n => n.id === id)) {
    ids.add(id); for (const e of graph.edges) if (e.from === id || e.to === id) { ids.add(e.from); ids.add(e.to); }
  }
  const viewKinds = VIEW_KINDS[state.view] || Object.keys(KINDS);
  const viewEdges = VIEW_RELATIONS[state.view];
  const home = new Map(graph.nodes.map(n => [n.id, n.home]));
  const outside = id => Boolean(chapter && home.get(id) && home.get(id) !== chapter);
  if (chapter && state.view !== 'curriculum') for (const e of graph.edges) if (viewEdges.includes(e.type) && members.has(e.from) !== members.has(e.to)) {
    const other = members.has(e.from) ? e.to : e.from;
    if (outside(other) && !ids.has(other)) { ids.add(other); cross.add(other); }
  }
  const nodes = graph.nodes.filter(n => ids.has(n.id) && viewKinds.includes(n.kind) && (!state.kinds?.length || state.kinds.includes(n.kind))).map(n => ({...n, related: !members.has(n.id) && !cross.has(n.id), external: outside(n.id) ? n.home : ''}));
  const visible = new Set(nodes.map(n => n.id));
  const edges = graph.edges.filter(e => visible.has(e.from) && visible.has(e.to) && viewEdges.includes(e.type) && (!state.relations?.length || state.relations.includes(e.type)));
  return {nodes, edges};
}

// Hidden controls must not keep filtering a different view, including restored URLs.
export function normalizeViewFilters(state) {
  return {...state,
    kinds: state.kinds.filter(kind => VIEW_KINDS[state.view].includes(kind)),
    relations: state.relations.filter(relation => VIEW_RELATIONS[state.view].includes(relation)),
  };
}

// A chapter page only accepts its own scopes; without a list any organization node is a scope.
export function readState(search, graph, {scopes, defaultScope = graph.defaultScope} = {}) {
  const p = new URLSearchParams(search), known = new Set(graph.nodes.map(n => n.id));
  const scope = p.get('scope'), view = p.get('view');
  const list = (key, valid) => [...new Set((p.get(key) || '').split(',').filter(x => valid.has(x)))];
  const validScope = scopes ? scopes.includes(scope) : graph.nodes.some(n => n.id === scope && ORG_KINDS.includes(n.kind));
  return normalizeViewFilters({scope: validScope ? scope : defaultScope, view: VIEWS[view] ? view : 'curriculum', q: (p.get('q') || '').slice(0,150), node: known.has(p.get('node')) ? p.get('node') : '', kinds: list('kinds',new Set(Object.keys(KINDS))), relations: list('relations',new Set(Object.keys(RELATIONS))), expanded: list('expand',known)});
}
export function writeState(state, base = '/knowledge/') {
  const p = new URLSearchParams({scope: state.scope, view: state.view});
  for (const k of ['q','node']) if (state[k]) p.set(k,state[k]);
  for (const [key, attr] of [['kinds','kinds'],['relations','relations'],['expand','expanded']]) if (state[attr]?.length) p.set(key,state[attr].join(','));
  return `${base}?${p}`;
}
export function safeGraphReturn(value) {
  if (!value) return '/knowledge/';
  try {
    const u = new URL(value, 'https://local.invalid');
    if (u.pathname.startsWith('/knowledge-next/')) u.pathname = u.pathname.replace('/knowledge-next/', '/knowledge/');
    return u.origin === 'https://local.invalid' && /^\/knowledge\/((?:chapters|collections)\/[a-z0-9-]+\/)?$/.test(u.pathname) ? u.pathname + u.search + u.hash : '/knowledge/';
  } catch { return '/knowledge/'; }
}
export function searchNodes(nodes, q) { const needle = q.trim().toLocaleLowerCase(); return needle ? nodes.filter(n => [n.label,...(n.aliases || [])].some(x => x.toLocaleLowerCase().includes(needle))) : []; }
