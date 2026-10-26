// Knowledge tower: sections are sectors around a vertical axis, node kinds are floors.
// Pure geometry shared by the 3D page and the tests; world units, y points up.
const ORG = ['textbook', 'chapter', 'section', 'collection'];
export const FLOORS = [
  {key: 'knowledge', label: '知识点', note: '地基', y: -270},
  {key: 'skill', label: '技能', note: '基本功', y: -90},
  {key: 'method', label: '方法', note: '解题策略', y: 90},
  {key: 'problem_type', label: '题型', note: '面对的问题', y: 270},
];
const RULE_Y = {step_selection: 0, method_selection: 180};
export const TOWER = {radius: 430, sectionY: 420, chapterY: 500, textbookY: 580, spacing: 104, gap: 0.12, chapterGap: 0.22};

const TAU = Math.PI * 2;
const floorY = n => n.kind === 'judgment_rule' ? RULE_Y[n.subtype] ?? 0 : FLOORS.find(f => f.key === n.kind)?.y ?? 0;
const at = (angle, radius, y) => ({x: Math.cos(angle) * radius, y, z: Math.sin(angle) * radius, angle, radius});
const meanAngle = angles => Math.atan2(angles.reduce((s, a) => s + Math.sin(a), 0), angles.reduce((s, a) => s + Math.cos(a), 0));

export function towerLayout(graph) {
  const byId = new Map(graph.nodes.map(n => [n.id, n]));
  const out = (id, types) => graph.edges.filter(e => e.from === id && types.includes(e.type)).map(e => e.to);
  const textbooks = graph.nodes.filter(n => n.kind === 'textbook');
  const chapters = [...textbooks.flatMap(t => out(t.id, ['contains'])), ...graph.nodes.filter(n => n.kind === 'chapter').map(n => n.id)].filter((id, i, a) => a.indexOf(id) === i);
  const sectionIds = [...chapters.flatMap(c => out(c, ['contains']).filter(id => byId.get(id)?.kind === 'section')), ...graph.nodes.filter(n => n.kind === 'collection').map(n => n.id)];
  const chapterOf = new Map(chapters.flatMap(c => out(c, ['contains']).map(s => [s, c])));

  // Home sections: direct membership wins over "extends"; rules live where they are referenced.
  const homes = new Map();
  const addHome = (id, section, rank) => { const h = homes.get(id) || {rank, list: []}; if (rank < h.rank) { h.rank = rank; h.list = []; } if (rank === h.rank && !h.list.includes(section)) h.list.push(section); homes.set(id, h); };
  for (const s of sectionIds) for (const e of graph.edges.filter(e => e.from === s)) if (e.type === 'contains') addHome(e.to, s, 0); else if (e.type === 'extends') addHome(e.to, s, 1);
  for (const e of graph.edges) if (['method_rule', 'step_rule'].includes(e.type)) for (const s of homes.get(e.from)?.list || []) addHome(e.to, s, 2);
  const sectionsOf = id => homes.get(id)?.list.slice().sort((a, b) => sectionIds.indexOf(a) - sectionIds.indexOf(b)) || [];

  // Sector width follows the busiest floor of each section, so a large section is not cramped.
  const floorKey = n => n.kind === 'judgment_rule' ? `rule-${n.subtype}` : n.kind;
  const solo = graph.nodes.filter(n => !ORG.includes(n.kind) && sectionsOf(n.id).length === 1);
  const weight = s => Math.max(3, ...Object.values(solo.filter(n => sectionsOf(n.id)[0] === s).reduce((c, n) => ({...c, [floorKey(n)]: (c[floorKey(n)] || 0) + 1}), {}))) + 2;
  const gaps = sectionIds.map((s, i) => i === 0 ? 0 : chapterOf.get(s) !== chapterOf.get(sectionIds[i - 1]) ? TOWER.chapterGap : TOWER.gap);
  const wrapGap = sectionIds.length > 1 ? (chapterOf.get(sectionIds[0]) !== chapterOf.get(sectionIds.at(-1)) ? TOWER.chapterGap : TOWER.gap) : 0;
  const free = TAU - gaps.reduce((a, b) => a + b, 0) - wrapGap, total = sectionIds.reduce((s, id) => s + weight(id), 0) || 1;
  let cursor = -Math.PI / 2 - (sectionIds.length ? free * weight(sectionIds[0]) / total / 2 : 0);
  const sectors = sectionIds.map((id, i) => {
    cursor += gaps[i];
    const span = free * weight(id) / total, sector = {id, label: byId.get(id).label, chapter: chapterOf.get(id), start: cursor, end: cursor + span, mid: cursor + span / 2};
    cursor += span;
    return sector;
  });
  const sectorOf = new Map(sectors.map(s => [s.id, s]));

  const positions = new Map(), R = TOWER.radius;
  // Solo nodes: spread along their sector's arc, extra rows step inward. Order by neighbours' angles.
  const groups = new Map();
  for (const n of solo) { const key = `${sectionsOf(n.id)[0]}|${floorKey(n)}`; groups.set(key, [...(groups.get(key) || []), n]); }
  const neighbours = new Map(graph.nodes.map(n => [n.id, []]));
  for (const e of graph.edges) if (!['contains', 'extends'].includes(e.type)) { neighbours.get(e.from)?.push(e.to); neighbours.get(e.to)?.push(e.from); }
  const place = () => {
    for (const [key, list] of groups) {
      const sector = sectorOf.get(key.split('|')[0]), span = (sector.end - sector.start) * 0.86;
      const perRow = Math.max(1, Math.floor(span * R / TOWER.spacing) + 1), rows = Math.ceil(list.length / perRow);
      list.forEach((n, i) => {
        const row = Math.floor(i / perRow), inRow = Math.min(perRow, list.length - row * perRow), k = i % perRow;
        const angle = sector.mid + (inRow === 1 ? 0 : (k / (inRow - 1) - 0.5) * span * Math.min(1, (inRow - 1) / (perRow - 1 || 1)));
        positions.set(n.id, {...at(angle, R - row * 92, floorY(n) + (rows > 1 ? (row % 2 ? -22 : 22) : 0)), floor: floorKey(n)});
      });
    }
  };
  // Shared nodes: between their sections, nearer the axis the more sections share them.
  const shared = graph.nodes.filter(n => !ORG.includes(n.kind) && sectionsOf(n.id).length !== 1);
  const placeShared = () => {
    const bucket = new Map();
    for (const n of shared) { const key = `${sectionsOf(n.id).join('+')}|${floorKey(n)}`; bucket.set(key, [...(bucket.get(key) || []), n]); }
    for (const [key, list] of bucket) {
      const owners = key.split('|')[0].split('+').filter(Boolean), radius = owners.length >= 3 || !owners.length ? R * 0.2 : R * 0.56;
      const angle = owners.length ? meanAngle(owners.map(s => sectorOf.get(s).mid)) : 0, step = TOWER.spacing / radius;
      list.forEach((n, i) => positions.set(n.id, {...at(angle + (i - (list.length - 1) / 2) * step, radius, floorY(n)), floor: floorKey(n)}));
    }
  };
  place(); placeShared();
  for (let pass = 0; pass < 6; pass += 1) {
    for (const list of groups.values()) {
      const score = n => { const a = neighbours.get(n.id).map(id => positions.get(id)?.angle).filter(x => x !== undefined); return a.length ? meanAngle(a) : positions.get(n.id).angle; };
      const mid = sectorOf.get(sectionsOf(list[0].id)[0]).mid, rel = a => Math.atan2(Math.sin(a - mid), Math.cos(a - mid));
      const scores = new Map(list.map(n => [n.id, rel(score(n))]));
      list.sort((a, b) => scores.get(a.id) - scores.get(b.id) || a.label.localeCompare(b.label, 'zh'));
    }
    place();
  }

  // Organisation: sections crown their sectors, chapters above, textbooks on the axis.
  for (const s of sectors) positions.set(s.id, {...at(s.mid, R * 0.72, TOWER.sectionY), floor: 'section'});
  chapters.forEach(c => {
    const own = sectors.filter(s => s.chapter === c);
    positions.set(c, {...(chapters.length > 1 && own.length ? at(meanAngle(own.map(s => s.mid)), R * 0.34, TOWER.chapterY) : at(0, 0, TOWER.chapterY)), floor: 'chapter'});
  });
  textbooks.forEach((t, i) => positions.set(t.id, {...at(0, 0, TOWER.textbookY + i * 60), floor: 'textbook'}));
  for (const n of graph.nodes) if (!positions.has(n.id)) positions.set(n.id, {...at(0, 0, floorY(n)), floor: floorKey(n)});

  return {positions, sectors, floors: FLOORS, sectionsOf, radius: R, top: TOWER.textbookY + (textbooks.length - 1) * 60, bottom: FLOORS[0].y};
}
