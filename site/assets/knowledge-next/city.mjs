// Knowledge city: every chapter is a tower. The preliminary strand fills the central plaza, the other
// strands are avenues radiating from it; along an avenue, compulsory books keep to one lane and
// elective books to the other, both in teaching order. Pure data and geometry, shared with the tests.
import {scopeMembers} from './model.mjs';
import {TOWER} from './tower.mjs';

const TAU = Math.PI * 2;
const ORG = ['textbook', 'chapter', 'section', 'collection'];
export const cityGroups = city => [...city.chapters, ...(city.collections || [])];
export const CITY = {plaza: 820, start: 1650, step: 1300, lane: 480, wedge: 0.5};
export const towerRadius = ch => ch.built ? TOWER.radius : 290 + 26 * ch.sections.length;
export const recorded = ch => ch.built || ch.partial;
export const STRAND_COLORS = ['#fbbf24', '#38bdf8', '#a78bfa', '#f472b6', '#34d399'];
export const strandColor = (city, id) => STRAND_COLORS[Math.max(0, city.strands.findIndex(s => s.id === id)) % STRAND_COLORS.length];

// Validates the outline against the graph and aggregates node relations into chapter links.
export function buildCity(outline, graph) {
  const errors = [], byId = new Map(graph.nodes.map(n => [n.id, n]));
  const books = new Map(outline.books.map(b => [b.id, b])), strands = new Map(outline.strands.map(s => [s.id, s]));
  const chapters = new Map();
  for (const b of outline.books) if (b.node && byId.get(b.node)?.kind !== 'textbook') errors.push(`${b.id}: 教材节点 ${b.node} 不存在`);
  for (const c of outline.chapters) {
    if (chapters.has(c.id)) errors.push(`${c.id}: 重复的章`);
    chapters.set(c.id, c);
    if (!books.has(c.book)) errors.push(`${c.id}: 未知教材 ${c.book}`);
    if (!strands.has(c.strand)) errors.push(`${c.id}: 未知主线 ${c.strand}`);
    if (!c.sections?.length) errors.push(`${c.id}: 缺少节`);
    if (c.node) {
      const n = byId.get(c.node);
      if (n?.kind !== 'chapter') errors.push(`${c.id}: 章节点 ${c.node} 不存在`);
      else if (!n.label.includes(c.label)) errors.push(`${c.id}: 章名与节点 ${c.node} 不一致`);
    }
    for (const s of c.sections || []) if (s.node) {
      const n = byId.get(s.node);
      if (n?.kind !== 'section') errors.push(`${c.id}: 节节点 ${s.node} 不存在`);
      else if (n.label !== `${s.number} ${s.label}`) errors.push(`${c.id}: 节名与节点 ${s.node} 不一致`);
      else if (!c.node || !graph.edges.some(e => e.type === 'contains' && e.from === c.node && e.to === s.node)) errors.push(`${c.id}: ${s.node} 不属于本章节点`);
    }
  }
  for (const n of graph.nodes.filter(n => n.kind === 'chapter')) if (!outline.chapters.some(c => c.node === n.id)) errors.push(`${n.id}: 章节点未登记到目录`);
  for (const [from, to] of outline.prerequisites) if (!chapters.has(from) || !chapters.has(to) || from === to) errors.push(`章间先修无效：${from} → ${to}`);
  if (errors.length) throw new Error(errors.join('\n'));

  const homes = homeChapters(outline, graph);
  // Node relations between two chapters merge into one link, earlier chapter first; directions differ
  // by relation type, so the link itself carries no direction.
  const collections = graph.nodes.filter(n => n.kind === 'collection');
  const relationCounts = new Map(), order = new Map([...outline.chapters, ...collections].map((c, i) => [c.id, i]));
  for (const e of graph.edges) {
    if (['contains', 'extends'].includes(e.type)) continue;
    const a = homes.get(e.from), b = homes.get(e.to);
    if (!a || !b || a === b) continue;
    const key = order.get(a) < order.get(b) ? `${a}|${b}` : `${b}|${a}`;
    relationCounts.set(key, (relationCounts.get(key) || 0) + 1);
  }
  const kinds = ['knowledge', 'skill', 'method', 'problem_type', 'judgment_rule'];
  return {
    schemaVersion: 1, title: outline.title, source: outline.source,
    books: outline.books.map(({id, label, short, lane}) => ({id, label, short, lane})),
    strands: outline.strands.map(({id, label, center}) => ({id, label, ...(center ? {center: true} : {})})),
    chapters: outline.chapters.map(c => {
      const members = graph.nodes.filter(n => homes.get(n.id) === c.id);
      const built = Boolean(c.node) && c.sections.every(s => s.node);
      return {id: c.id, book: c.book, number: c.number, strand: c.strand, label: c.label, ...(c.node ? {node: c.node} : {}), built, partial: Boolean(c.node) && !built,
        counts: Object.fromEntries(kinds.map(k => [k, members.filter(n => n.kind === k).length])),
        sections: c.sections.map(s => ({number: s.number, label: s.label, ...(s.node ? {node: s.node} : {})}))};
    }),
    collections: collections.map(n => ({id: n.id, node: n.id, kind: 'collection', label: n.label, built: true, recorded: true, partial: false, sections: [],
      members: n.members.map(m => m.ref), counts: Object.fromEntries(kinds.map(k => [k, graph.nodes.filter(member => homes.get(member.id) === n.id && member.kind === k).length]))})),
    links: [
      ...outline.prerequisites.map(([from, to]) => ({from, to, type: 'outline'})),
      ...[...relationCounts].map(([key, count]) => { const [from, to] = key.split('|'); return {from, to, type: 'relation', count}; }),
    ],
  };
}

// A node lives in the chapter of the section that contains it; a section that only extends it borrows
// it. Nodes referenced by no section of any chapter (rules) live where they are first reached.
export function homeChapters(outline, graph) {
  const kinds = new Map(graph.nodes.map(n => [n.id, n.kind])), homes = new Map();
  const listed = outline.chapters.filter(c => c.node);
  // Collections own their direct members before a high-school section borrows them.
  for (const n of graph.nodes.filter(n => n.kind === 'collection')) {
    homes.set(n.id, n.id);
    for (const e of graph.edges) if (e.from === n.id && e.type === 'contains') homes.set(e.to, n.id);
  }
  for (const relation of ['contains', 'extends']) for (const c of listed) for (const s of c.sections.filter(s => s.node)) {
    for (const e of graph.edges) if (e.from === s.node && e.type === relation && !homes.has(e.to)) homes.set(e.to, c.id);
  }
  for (const c of listed) {
    homes.set(c.node, c.id);
    for (const s of c.sections.filter(s => s.node)) homes.set(s.node, c.id);
    for (const id of scopeMembers(graph, c.node)) if (!ORG.includes(kinds.get(id)) && !homes.has(id)) homes.set(id, c.id);
  }
  return homes;
}

// The nodes that live in one chapter's tower, with the relations among them.
export function chapterGraph(graph, homes, chapterId) {
  const ids = new Set(graph.nodes.filter(n => homes.get(n.id) === chapterId).map(n => n.id));
  return {nodes: graph.nodes.filter(n => ids.has(n.id)), edges: graph.edges.filter(e => ids.has(e.from) && ids.has(e.to)), defaultScope: graph.defaultScope};
}

// A partly recorded chapter keeps its scaffolding: one sector per outline section, nodes standing on
// their kind's floor inside the sector of the section that holds them.
export function scaffoldLayout(chapter, sub, radius, floors) {
  const n = chapter.sections.length, sectors = [], positions = new Map(), member = new Map();
  for (const e of sub.edges) if (['contains', 'extends'].includes(e.type)) member.set(e.to, [...(member.get(e.to) || []), e.from]);
  chapter.sections.forEach((s, i) => {
    if (!s.node) return;
    const start = -Math.PI / 2 + i * TAU / n, end = start + TAU / n;
    sectors.push({id: s.node, label: `${s.number} ${s.label}`, chapter: chapter.node, start, end, mid: (start + end) / 2});
  });
  const sectorOf = new Map(sectors.map(s => [s.id, s])), groups = new Map();
  for (const node of sub.nodes) {
    if (node.kind === 'chapter') continue;
    const sector = sectorOf.get(node.kind === 'section' ? node.id : (member.get(node.id) || []).find(id => sectorOf.has(id)));
    if (!sector) continue;
    const y = node.kind === 'section' ? floors.sectionY : floors.y[node.kind];
    const key = `${sector.id}|${y}`;
    groups.set(key, [...(groups.get(key) || []), {node, sector, y}]);
  }
  for (const list of groups.values()) list.forEach(({node, sector, y}, k) => {
    const spread = (sector.end - sector.start) * 0.5, angle = sector.mid + (list.length > 1 ? (k / (list.length - 1) - 0.5) * spread : 0);
    const r = node.kind === 'section' ? radius * 0.85 : radius * 0.62;
    positions.set(node.id, {x: Math.cos(angle) * r, y, z: Math.sin(angle) * r, angle, radius: r});
  });
  return {positions, sectors, radius, sectionsOf: id => sectors.filter(s => s.id === id || (member.get(id) || []).includes(s.id)).map(s => s.id)};
}

export function cityLayout(city) {
  const lane = new Map(city.books.map(b => [b.id, b.lane]));
  const outer = city.strands.filter(s => !s.center), centre = new Set(city.strands.filter(s => s.center).map(s => s.id));
  const rays = new Map(outer.map((s, i) => [s.id, -Math.PI / 2 + i * TAU / Math.max(1, outer.length)]));
  const towers = new Map(), districts = [];
  const put = (c, x, z, extra = {}) => towers.set(c.id, {x, z, radius: towerRadius(c), angle: Math.atan2(z, x), distance: Math.hypot(x, z), ...extra});
  for (const s of outer) {
    const a = rays.get(s.id), dir = {x: Math.cos(a), z: Math.sin(a)}, side = {x: -Math.sin(a), z: Math.cos(a)};
    const list = city.chapters.filter(c => c.strand === s.id);
    const lanes = [list.filter(c => lane.get(c.book) !== 'elective'), list.filter(c => lane.get(c.book) === 'elective')];
    let far = CITY.start;
    lanes.forEach((group, li) => group.forEach((c, k) => {
      const along = CITY.start + k * CITY.step + (li && lanes[0].length ? CITY.step / 2 : 0);
      const lateral = lanes[1 - li].length ? (li ? 1 : -1) * CITY.lane : 0;
      put(c, dir.x * along + side.x * lateral, dir.z * along + side.z * lateral, {strand: s.id, lane: li ? 'elective' : 'required'});
      far = Math.max(far, along);
    }));
    districts.push({id: s.id, label: s.label, angle: a, inner: CITY.plaza + 180, outer: far + 760});
  }
  // Plaza towers sit in the gaps between avenues, the first one facing the default camera.
  const plaza = city.chapters.filter(c => centre.has(c.strand)), gaps = outer.length ? outer.map(s => rays.get(s.id) + Math.PI / outer.length) : [0];
  plaza.forEach((c, i) => {
    const a = gaps[(i + 1) % gaps.length] , r = CITY.plaza * (1 + Math.floor(i / gaps.length) * 0.8);
    put(c, Math.cos(a) * r, Math.sin(a) * r, {strand: c.strand, lane: 'plaza'});
  });
  // Independent collections occupy a separate place near the plaza, not a textbook chapter.
  (city.collections || []).forEach((c, i) => put(c, (i - ((city.collections || []).length - 1) / 2) * 1200, CITY.plaza * 2.45, {lane: 'collection'}));
  const extent = Math.max(CITY.plaza, ...[...towers.values()].map(t => t.distance + t.radius + 120));
  return {towers, districts, plaza: CITY.plaza, extent};
}
