import {isPreview, modeHref} from '../practice/learning-mode.mjs';
/* 3D knowledge city: every chapter is a tower. Built chapters are full knowledge towers; the rest are
   scaffolding from the textbook outline. Three levels: city → tower → node. Names are DOM buttons over the
   WebGL canvas so they stay sharp, clickable and reachable with Tab. */
import * as THREE from '/assets/vendor/three-0.186.1/three-graph.min.js';
import {KINDS, RELATIONS, nodeHref, detailLabel, chapterPath, groupPath, lifecycleLabel} from './model.mjs';
import {towerLayout, TOWER, FLOORS} from './tower.mjs';
import {cityLayout, cityGroups, chapterGraph, homeChapters, scaffoldLayout, recorded, strandColor as strandColorOf, CITY} from './city.mjs';
import {escapeHtml as h} from './resource-links.mjs';
import {renderLearningMath} from './learning-model.mjs';

const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const ORG = ['textbook', 'chapter', 'section', 'collection'];
const TAU = Math.PI * 2;
const GLOW = {collection: '#9fd3c7', textbook: '#cfe0ee', chapter: '#ffe3a3', section: '#9fd3c7', knowledge: '#2dd4bf', skill: '#7cb8ff', method: '#f5b54a', problem_type: '#ff8f7a', judgment_rule: '#c4a1ff'};
const FAMILY = {contains: 'org', extends: 'org', prerequisite: 'know', uses: 'know', involves: 'know', candidate: 'solve', calls: 'solve', method_rule: 'rule', step_rule: 'rule', selects: 'rule'};
const FAMILY_COLOR = {org: '#9fb7c9', know: '#2dd4bf', solve: '#f5b54a', rule: '#c4a1ff'};
const SECTION_COLORS = ['#5eead4', '#a78bfa', '#fbbf24', '#60a5fa', '#f472b6', '#34d399', '#fb923c'];
const NODE_TARGET = {
  rest: {glow: 0.9, opacity: 1, scale: 1},
  selected: {glow: 2, opacity: 1, scale: 1.5},
  related: {glow: 1.45, opacity: 1, scale: 1.15},
  dim: {glow: 0.12, opacity: 0.16, scale: 0.8},
  away: {glow: 0.55, opacity: 0.5, scale: 0.9},
  out: {glow: 0, opacity: 0, scale: 0.4},
};
const EDGE_OPACITY = {hidden: 0, faint: 0.035, city: 0.06, cross: 0.5, rest: 0.13, shown: 0.32, strong: 0.95};
const LINK_OPACITY = {faint: 0.06, rest: 0.26, strong: 0.9};
const FOV = 34, HOP_DELAY = 140, IDLE_SPIN = 12000, STEP_MS = 1400;
const GROUND = FLOORS[0].y - 50, ROOF = FLOORS.at(-1).y + 60, LINK_Y = ROOF + 40;

const calm = matchMedia('(prefers-reduced-motion: reduce)').matches;
const touch = matchMedia('(pointer: coarse)').matches;
const lerp = (a, b, t) => a + (b - a) * t;
const ease = t => t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
const kindText = n => `${KINDS[n.kind]}${lifecycleLabel(n) ? ` · ${lifecycleLabel(n)}` : ''}${n.subtype ? ` · ${n.subtype === 'method_selection' ? '选法规则' : '步骤选择规则'}` : ''}`;
const floorOf = n => ORG.includes(n.kind) ? 'org' : n.kind;
const facing = angle => Math.PI / 2 - angle;

function glowTexture() {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 128;
  const context = canvas.getContext('2d'), gradient = context.createRadialGradient(64, 64, 0, 64, 64, 64);
  gradient.addColorStop(0, 'rgba(255,255,255,1)');
  gradient.addColorStop(0.18, 'rgba(255,255,255,.55)');
  gradient.addColorStop(0.45, 'rgba(255,255,255,.13)');
  gradient.addColorStop(1, 'rgba(255,255,255,0)');
  context.fillStyle = gradient;
  context.fillRect(0, 0, 128, 128);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}
function cubeGeometry(size) {
  const g = new THREE.BufferGeometry(), s = size / 2;
  g.setAttribute('position', new THREE.Float32BufferAttribute([-s, -s, -s, s, -s, -s, s, s, -s, -s, s, -s, -s, -s, s, s, -s, s, s, s, s, -s, s, s], 3));
  g.setIndex([0, 2, 1, 0, 3, 2, 4, 5, 6, 4, 6, 7, 0, 1, 5, 0, 5, 4, 2, 3, 7, 2, 7, 6, 1, 2, 6, 1, 6, 5, 0, 4, 7, 0, 7, 3]);
  return g;
}
function lineGeometry(points) {
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(points.flatMap(p => [p.x, p.y, p.z]), 3));
  return g;
}
function webglAvailable() {
  try { const c = document.createElement('canvas'); return Boolean(c.getContext('webgl2') || c.getContext('webgl')); } catch { return false; }
}

let graph, byId, city, plan, view;
const chapters = new Map(), towers = new Map(), nodeTower = new Map();
const state = {level: 'city', chapter: '', node: '', hover: '', hoverTower: '', section: '', strand: '', card: false,
  floors: new Set(['org', 'knowledge', 'skill', 'method', 'problem_type', 'judgment_rule']), families: new Set(['know', 'solve', 'rule']), spin: !calm, play: null};
const status = text => { $('#tower-status').textContent = text; };
const sectionsOf = id => towers.get(nodeTower.get(id))?.layout?.sectionsOf(id) || [];
const nodeCount = c => Object.values(c.counts).reduce((a, b) => a + b, 0);
const chapterName = c => c.kind === 'collection' ? '知识集合' : `${city.books.find(b => b.id === c.book).short} · 第 ${c.number} 章`;
const strandColor = id => strandColorOf(city, id);

function mount() {
  const container = $('#tower');
  const renderer = new THREE.WebGLRenderer({antialias: true, alpha: true, powerPreference: 'high-performance'});
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
  renderer.domElement.setAttribute('aria-hidden', 'true');
  const labels = new THREE.CSS2DRenderer();
  labels.domElement.className = 'tower-labels';
  labels.domElement.setAttribute('role', 'group');
  labels.domElement.setAttribute('aria-label', '知识图谱中的章与节点');
  container.replaceChildren(renderer.domElement, labels.domElement);

  const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(FOV, 1, 10, 80000), world = new THREE.Group();
  scene.add(world);
  const glow = glowTexture(), R = TOWER.radius, towerMid = (TOWER.chapterY + FLOORS[0].y) / 2, extent = plan.extent;
  const additive = (color, opacity, extra = {}) => ({color, transparent: true, opacity, depthWrite: false, blending: THREE.AdditiveBlending, ...extra});
  const label = (parent, html, className, position, center = [0.5, 0.5]) => {
    const element = document.createElement('div');
    element.className = className;
    element.innerHTML = html;
    const object = new THREE.CSS2DObject(element);
    object.center.set(...center);
    object.position.copy(position);
    parent.add(object);
    return object;
  };
  const flat = (mesh, y) => { mesh.rotation.x = Math.PI / 2; mesh.position.y = y; return mesh; };

  /* Sky. */
  const sky = extent * 2.4, starCount = 2400, starPositions = new Float32Array(starCount * 3);
  for (let i = 0; i < starCount; i += 1) {
    const r = sky * (1 + Math.random()), u = Math.random() * 1.6 - 0.6, a = Math.random() * TAU;
    starPositions.set([r * Math.sqrt(1 - u * u) * Math.cos(a), r * u * 0.6, r * Math.sqrt(1 - u * u) * Math.sin(a)], i * 3);
  }
  const starGeometry = new THREE.BufferGeometry();
  starGeometry.setAttribute('position', new THREE.Float32BufferAttribute(starPositions, 3));
  const stars = new THREE.Points(starGeometry, new THREE.PointsMaterial({color: '#d7ecff', size: sky / 260, map: glow, transparent: true, opacity: 0.85, depthWrite: false, blending: THREE.AdditiveBlending}));
  scene.add(stars);
  for (const [color, x, y, z, size] of [['#1fb5a8', -1, 0.25, -1, 2.2], ['#6d5bd6', 1, 0, -0.5, 2.6], ['#c2547a', 0.2, 0.5, 1, 1.8]]) {
    const cloud = new THREE.Sprite(new THREE.SpriteMaterial({map: glow, ...additive(color, 0.08)}));
    cloud.position.set(x * sky, y * sky * 0.5, z * sky);
    cloud.scale.setScalar(size * sky);
    scene.add(cloud);
  }

  /* Ground: a shared foundation, the central plaza and one tinted wedge per strand avenue. */
  world.add(flat(new THREE.Mesh(new THREE.RingGeometry(0, extent + 500, 160, 1), new THREE.MeshBasicMaterial(additive('#7fd6ca', 0.02, {side: THREE.DoubleSide}))), GROUND - 12));
  world.add(flat(new THREE.Mesh(new THREE.RingGeometry(extent + 490, extent + 500, 220, 1), new THREE.MeshBasicMaterial(additive('#7fd6ca', 0.3, {side: THREE.DoubleSide}))), GROUND - 12));
  const plazaColor = strandColor(city.strands.find(s => s.center)?.id);
  world.add(flat(new THREE.Mesh(new THREE.RingGeometry(0, CITY.plaza + 620, 128, 1), new THREE.MeshBasicMaterial(additive(plazaColor, 0.035, {side: THREE.DoubleSide}))), GROUND - 8));
  world.add(flat(new THREE.Mesh(new THREE.RingGeometry(CITY.plaza + 612, CITY.plaza + 620, 160, 1), new THREE.MeshBasicMaterial(additive(plazaColor, 0.45, {side: THREE.DoubleSide}))), GROUND - 8));
  const groundLabels = [];
  const centreStrand = city.strands.find(s => s.center);
  if (centreStrand) {
    // On the plaza rim in front of the default camera, which faces the first built tower.
    const first = [...towers.values()].find(t => t.chapter.built)?.pos;
    const front = first ? Math.atan2(first.z, first.x) : Math.PI / 2;
    groundLabels.push(label(world, `<b>${h(centreStrand.label)}</b><span>中心广场</span>`, 'city-district', new THREE.Vector3(Math.cos(front) * (CITY.plaza + 560), GROUND, Math.sin(front) * (CITY.plaza + 560))));
    groundLabels.at(-1).element.style.setProperty('--sc', plazaColor);
  }
  const roads = [];
  for (const d of plan.districts) {
    const color = strandColor(d.id), start = d.angle - CITY.wedge, length = CITY.wedge * 2;
    world.add(flat(new THREE.Mesh(new THREE.RingGeometry(d.inner, d.outer, 64, 1, start, length), new THREE.MeshBasicMaterial(additive(color, 0.045, {side: THREE.DoubleSide}))), GROUND - 10));
    world.add(flat(new THREE.Mesh(new THREE.RingGeometry(d.outer - 8, d.outer, 96, 1, start, length), new THREE.MeshBasicMaterial(additive(color, 0.5, {side: THREE.DoubleSide}))), GROUND - 10));
    roads.push(new THREE.Vector3(Math.cos(d.angle) * (CITY.plaza + 620), GROUND - 6, Math.sin(d.angle) * (CITY.plaza + 620)), new THREE.Vector3(Math.cos(d.angle) * d.outer, GROUND - 6, Math.sin(d.angle) * d.outer));
    const object = label(world, `<b>${h(d.label)}</b><span>主线</span>`, 'city-district', new THREE.Vector3(Math.cos(d.angle) * (d.outer + 260), GROUND, Math.sin(d.angle) * (d.outer + 260)));
    object.element.style.setProperty('--sc', color);
    groundLabels.push(object);
  }
  world.add(new THREE.LineSegments(lineGeometry(roads), new THREE.LineBasicMaterial(additive('#cfe0ee', 0.22))));

  /* Towers. */
  const items = new Map(), edges = [], hitTargets = [], towerHits = [], floorLabelSets = [], sectorSets = [], axisSparks = [], ghosts = new Map(), cityLabels = new Map(), cityAnchors = [], footprints = new Map();
  for (const [chapterId, info] of towers) {
    const c = info.chapter, pos = info.pos, group = new THREE.Group(), color = strandColor(c.strand), r = pos.radius;
    group.position.set(pos.x, 0, pos.z);
    world.add(group);
    info.group = group;
    info.center = new THREE.Vector3(pos.x, 0, pos.z);
    const footprint = flat(new THREE.Mesh(new THREE.RingGeometry(r + 70, r + 84, 96, 1), new THREE.MeshBasicMaterial(additive(color, 0.55, {side: THREE.DoubleSide}))), GROUND - 4);
    group.add(footprint);
    footprints.set(chapterId, footprint);
    const hit = new THREE.Mesh(new THREE.SphereGeometry(1, 12, 8), new THREE.MeshBasicMaterial({visible: false}));
    hit.scale.set(r + 90, 520, r + 90);
    hit.position.y = towerMid;
    hit.userData.chapter = chapterId;
    group.add(hit);
    towerHits.push(hit);
    const top = c.built ? TOWER.chapterY : ROOF + 150;
    const cityLabel = label(group, `<div class="city-tower-card" style="--sc:${color}"><button type="button" data-chapter="${chapterId}"><small>${h(chapterName(c))}</small><b>${h(c.label)}</b><span>${c.built ? `已录入 · ${nodeCount(c)} 个节点` : c.partial ? `部分录入 · ${nodeCount(c)} 个节点` : `建设中 · ${c.sections.length} 节`}</span></button>${c.node ? `<div data-progress-scope="${c.node}" data-progress-compact></div>` : ''}</div>`, `city-tower${c.built ? ' is-built' : c.partial ? ' is-partial' : ''}`, new THREE.Vector3(0, top + 130, 0), [0.5, 1]);
    cityLabels.set(chapterId, cityLabel.element);
    cityAnchors.push({id: chapterId, object: cityLabel, element: cityLabel.element, built: recorded(c), small: false, hidden: false});
    if (c.built) buildTower(info);
    else { buildGhost(info, color); if (c.partial) buildScaffoldNodes(info); }
  }

  function buildGhost(info, color) {
    const c = info.chapter, r = info.pos.radius, group = info.group, n = c.sections.length, parts = [];
    const mat = (m, base) => { m.userData.base = base; parts.push(m); return m; };
    for (const f of FLOORS) {
      group.add(mat(flat(new THREE.Mesh(new THREE.RingGeometry(r, r + 3.5, 96, 1), new THREE.MeshBasicMaterial(additive(GLOW[f.key], 0.32, {side: THREE.DoubleSide}))), f.y - 14), 0.32));
      group.add(mat(flat(new THREE.Mesh(new THREE.RingGeometry(r * 0.1, r, 64, 1), new THREE.MeshBasicMaterial(additive(GLOW[f.key], 0.018, {side: THREE.DoubleSide}))), f.y - 14), 0.018));
    }
    const at = (a, y) => new THREE.Vector3(Math.cos(a) * r, y, Math.sin(a) * r), struts = [], braces = [];
    const levels = [GROUND, ...FLOORS.map(f => f.y - 14), ROOF];
    for (let i = 0; i < n; i += 1) {
      const a = -Math.PI / 2 + i * TAU / n, b = -Math.PI / 2 + (i + 1) * TAU / n;
      struts.push(at(a, GROUND), at(a, ROOF));
      for (let k = 0; k + 1 < levels.length; k += 1) braces.push(at(a, levels[k]), at(b, levels[k + 1]));
    }
    group.add(mat(new THREE.LineSegments(lineGeometry(struts), new THREE.LineBasicMaterial(additive('#cfe0ee', 0.32))), 0.32));
    group.add(mat(new THREE.LineSegments(lineGeometry(braces), new THREE.LineBasicMaterial(additive('#9fb7c9', 0.1))), 0.1));
    group.add(mat(new THREE.LineSegments(lineGeometry([new THREE.Vector3(0, GROUND, 0), new THREE.Vector3(0, ROOF + 150, 0)]), new THREE.LineBasicMaterial(additive(color, 0.35))), 0.35));
    const crown = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.OctahedronGeometry(22)), new THREE.LineBasicMaterial(additive(color, 0.9)));
    crown.position.y = ROOF + 150;
    group.add(mat(crown, 0.9));
    const beacon = new THREE.Sprite(new THREE.SpriteMaterial({map: glow, ...additive(color, 0.6)}));
    beacon.scale.setScalar(160);
    beacon.position.y = ROOF + 150;
    group.add(mat(beacon, 0.6));
    const sectionLabels = c.sections.map((s, i) => {
      const a = -Math.PI / 2 + (i + 0.5) * TAU / n;
      const object = label(group, `<span><b>${h(s.number)}</b>${h(s.label)}</span>`, 'ghost-section is-away', new THREE.Vector3(Math.cos(a) * (r + 30), ROOF - 10, Math.sin(a) * (r + 30)), [0.5, 1]);
      return {object, angle: a};
    });
    ghosts.set(c.id, {parts, crown, sectionLabels, fade: 1, target: 1});
  }

  function buildTower(info) {
    const layout = info.layout, group = info.group, chapterId = info.chapter.id;
    const floorLabels = FLOORS.map(f => {
      group.add(flat(new THREE.Mesh(new THREE.RingGeometry(R * 0.1, R + 80, 128, 1), new THREE.MeshBasicMaterial(additive(GLOW[f.key], 0.045, {side: THREE.DoubleSide}))), f.y - 14));
      group.add(flat(new THREE.Mesh(new THREE.RingGeometry(R + 78, R + 81, 160, 1), new THREE.MeshBasicMaterial(additive(GLOW[f.key], 0.4, {side: THREE.DoubleSide}))), f.y - 14));
      const object = label(group, `<i></i><b>${f.label}</b><span>${f.note}</span>`, 'tower-floor is-away', new THREE.Vector3(0, f.y, 0), [1, 0.5]);
      object.element.dataset.kind = f.key;
      return {floor: f, object};
    });
    floorLabelSets.push({chapter: chapterId, labels: floorLabels});
    const sectorParts = layout.sectors.map((s, i) => {
      const color = SECTION_COLORS[i % SECTION_COLORS.length], arcs = [];
      for (const y of [GROUND + 10, ROOF]) {
        const arc = new THREE.Mesh(new THREE.TorusGeometry(R + 80, 2.4, 6, 96, s.end - s.start), new THREE.MeshBasicMaterial(additive(color, 0.45)));
        arc.rotation.set(Math.PI / 2, 0, s.start);
        arc.position.y = y;
        group.add(arc);
        arcs.push(arc);
      }
      return {sector: s, color, arcs};
    });
    sectorSets.push({chapter: chapterId, parts: sectorParts});
    const dividers = [];
    for (const s of layout.sectors) for (const a of [s.start, s.end]) dividers.push(new THREE.Vector3(Math.cos(a) * (R + 80), GROUND + 10, Math.sin(a) * (R + 80)), new THREE.Vector3(Math.cos(a) * (R + 80), ROOF, Math.sin(a) * (R + 80)));
    group.add(new THREE.LineSegments(lineGeometry(dividers), new THREE.LineBasicMaterial(additive('#9fd3c7', 0.16))));
    const axisFrom = new THREE.Vector3(0, GROUND + 10, 0), axisTo = new THREE.Vector3(0, TOWER.chapterY, 0);
    const axisCurve = new THREE.CubicBezierCurve3(axisFrom, axisFrom.clone().lerp(axisTo, 0.33), axisFrom.clone().lerp(axisTo, 0.66), axisTo);
    group.add(new THREE.Mesh(new THREE.TubeGeometry(axisCurve, 8, 2.2, 8), new THREE.MeshBasicMaterial(additive('#9fd3c7', 0.28))));
    for (let i = 0; i < 4; i += 1) {
      const spark = new THREE.Sprite(new THREE.SpriteMaterial({map: glow, ...additive('#bff7ee', 0)}));
      spark.scale.setScalar(30);
      spark.userData = {offset: i / 4, curve: axisCurve};
      group.add(spark);
      axisSparks.push(spark);
    }
    const sectionColor = new Map(sectorParts.map(p => [p.sector.id, p.color]));
    for (const n of info.graph.nodes) addNode(info, n, layout.positions.get(n.id), sectionColor);
    for (const e of info.graph.edges) addEdge(info, e);
  }

  // A partly recorded chapter: scaffolding plus the nodes recorded so far, in their sections' sectors.
  function buildScaffoldNodes(info) {
    const c = info.chapter, sectionColor = new Map(c.sections.map((s, i) => [s.node, SECTION_COLORS[i % SECTION_COLORS.length]]));
    for (const n of info.graph.nodes) if (info.layout.positions.has(n.id)) addNode(info, n, info.layout.positions.get(n.id), sectionColor);
    for (const e of info.graph.edges) addEdge(info, e);
  }

  function addNode(info, n, p, sectionColor) {
    const group = info.group, chapterId = info.chapter.id;
    {
      const color = new THREE.Color(GLOW[n.kind]), core = color.clone().lerp(new THREE.Color('#ffffff'), 0.5);
      const node = new THREE.Group(), parts = [];
      node.position.set(p.x, p.y, p.z);
      const solid = (geometry, opacity = 0.9) => { const mesh = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({color, transparent: true, opacity})); mesh.userData.base = opacity; parts.push(mesh); return mesh; };
      const wire = geometry => { const line = new THREE.LineSegments(new THREE.EdgesGeometry(geometry), new THREE.LineBasicMaterial({color: core, transparent: true})); line.userData.base = 1; parts.push(line); return line; };
      const body = new THREE.Group();
      if (n.kind === 'knowledge') body.add(solid(new THREE.SphereGeometry(8, 24, 16), 1));
      else if (n.kind === 'skill') { const g = cubeGeometry(13); body.add(solid(g, 0.75), wire(g)); body.rotation.set(0.6, 0.6, 0); }
      else if (n.kind === 'method') { const g = new THREE.OctahedronGeometry(11); body.add(solid(g, 0.8), wire(g)); }
      else if (n.kind === 'problem_type') { const g = new THREE.ConeGeometry(10, 17, 3); body.add(solid(g, 0.8), wire(g)); }
      else if (n.kind === 'judgment_rule') body.add(solid(new THREE.TorusGeometry(9, 2.3, 8, 32), 1), solid(new THREE.SphereGeometry(3.5, 12, 8), 1));
      else if (n.kind === 'section') {
        const ring = new THREE.Mesh(new THREE.TorusGeometry(17, 1.4, 6, 48), new THREE.MeshBasicMaterial({color: sectionColor.get(n.id) || color, transparent: true}));
        ring.userData.base = 1; ring.rotation.x = Math.PI / 2.4; parts.push(ring);
        body.add(solid(new THREE.SphereGeometry(9, 24, 16), 1), ring);
      } else { const g = new THREE.OctahedronGeometry(26); body.add(wire(g), solid(new THREE.SphereGeometry(10, 24, 16), 1)); }
      const halo = new THREE.Sprite(new THREE.SpriteMaterial({map: glow, ...additive(GLOW[n.kind], 0.5)}));
      const haloSize = ORG.includes(n.kind) ? (n.kind === 'chapter' ? 150 : 90) : 54;
      halo.scale.setScalar(haloSize);
      const hit = new THREE.Mesh(new THREE.SphereGeometry(ORG.includes(n.kind) ? 30 : 20, 8, 6), new THREE.MeshBasicMaterial({visible: false}));
      hit.userData.id = n.id;
      hitTargets.push(hit);
      node.add(halo, body, hit);
      group.add(node);
      const element = document.createElement('div');
      element.className = 'tower-label is-away';
      element.dataset.kind = n.kind;
      element.innerHTML = `<button type="button" data-node="${n.id}" data-learning-node="${n.id}" aria-label="${kindText(n)}：${h(n.label)}" tabindex="-1"><span>${h(n.label)}</span></button>`;
      const name = new THREE.CSS2DObject(element);
      name.center.set(0.5, 0);
      name.position.set(0, ORG.includes(n.kind) ? -(n.kind === 'chapter' ? 34 : 24) : -15, 0);
      node.add(name);
      items.set(n.id, {node: n, tower: chapterId, p, group: node, body, parts, halo, haloSize, element, spin: ['method', 'skill', 'judgment_rule', 'chapter'].includes(n.kind) ? 0.25 + Math.random() * 0.25 : 0,
        current: {...NODE_TARGET.rest}, target: {...NODE_TARGET.rest}, startAt: 0, out: false, back: false, away: true});
    }
  }

  function flowSparks(parent, family, size) {
    return calm ? [] : Array.from({length: 2}, (_, i) => {
      const spark = new THREE.Sprite(new THREE.SpriteMaterial({map: glow, ...additive(new THREE.Color(FAMILY_COLOR[family]).lerp(new THREE.Color('#ffffff'), 0.5), 0)}));
      spark.scale.setScalar(size);
      spark.userData.offset = i / 2;
      spark.visible = false;
      parent.add(spark);
      return spark;
    });
  }
  function addEdge(info, e) {
    const group = info.group, chapterId = info.chapter.id, up = new THREE.Vector3(0, 1, 0);
    if (['contains', 'extends'].includes(e.type) && byId.get(e.from).kind === 'section') return;
    if (!items.has(e.from) || !items.has(e.to)) return;
    {
      const a = items.get(e.from).group.position, b = items.get(e.to).group.position, dy = b.y - a.y, family = FAMILY[e.type];
      const inward = (v, k) => new THREE.Vector3(v.x * k, v.y, v.z * k);
      const curve = Math.abs(dy) < 40
        ? new THREE.CubicBezierCurve3(a.clone(), inward(a, 0.7).add(new THREE.Vector3(0, 70, 0)), inward(b, 0.7).add(new THREE.Vector3(0, 70, 0)), b.clone())
        : new THREE.CubicBezierCurve3(a.clone(), inward(a, 0.8).addScaledVector(up, dy * 0.42), inward(b, 0.8).addScaledVector(up, -dy * 0.42), b.clone());
      const tube = new THREE.Mesh(new THREE.TubeGeometry(curve, 36, family === 'org' ? 1.4 : 0.95, 5), new THREE.MeshBasicMaterial(additive(FAMILY_COLOR[family], 0)));
      group.add(tube);
      edges.push({edge: e, tower: chapterId, family, curve, length: curve.getLength(), tube, sparks: flowSparks(group, family, 15), state: 'city', current: 0, target: EDGE_OPACITY.city, startAt: 0, out: false});
    }
  }

  /* Relations whose ends live in different towers arc over the streets between them. */
  world.updateMatrixWorld(true);
  for (const e of graph.edges) {
    if (['contains', 'extends'].includes(e.type) || !items.has(e.from) || !items.has(e.to)) continue;
    const from = items.get(e.from), to = items.get(e.to);
    if (from.tower === to.tower) continue;
    const a = from.group.getWorldPosition(new THREE.Vector3()), b = to.group.getWorldPosition(new THREE.Vector3()), family = FAMILY[e.type];
    const top = Math.max(a.y, b.y) + 240 + a.distanceTo(b) * 0.12;
    const curve = new THREE.CubicBezierCurve3(a, a.clone().lerp(b, 0.2).setY(top), a.clone().lerp(b, 0.8).setY(top), b);
    const tube = new THREE.Mesh(new THREE.TubeGeometry(curve, 64, 3.2, 6), new THREE.MeshBasicMaterial(additive(FAMILY_COLOR[family], 0)));
    world.add(tube);
    edges.push({edge: e, tower: from.tower, towers: [from.tower, to.tower], cross: true, family, curve, length: curve.getLength(), tube, sparks: flowSparks(world, family, 34), state: 'city', current: 0, target: EDGE_OPACITY.cross, startAt: 0, out: false});
  }

  /* Skyways: chapter prerequisites from the outline (dashed) and aggregated node relations (solid). */
  const portalAnchors = [];
  const links = city.links.filter(l => towers.has(l.from) && towers.has(l.to)).map(l => {
    const A = towers.get(l.from).center, B = towers.get(l.to).center, d = A.distanceTo(B);
    const a = A.clone().setY(LINK_Y), b = B.clone().setY(LINK_Y), lift = 260 + d * 0.16;
    const curve = new THREE.CubicBezierCurve3(a, a.clone().lerp(b, 0.25).setY(LINK_Y + lift), a.clone().lerp(b, 0.75).setY(LINK_Y + lift), b);
    let line;
    if (l.type === 'relation') line = new THREE.Mesh(new THREE.TubeGeometry(curve, 48, 3 + Math.min(10, l.count) * 0.5, 6), new THREE.MeshBasicMaterial(additive('#5eead4', 0)));
    else {
      const pts = curve.getSpacedPoints(64), dashes = [];
      for (let i = 0; i + 1 < pts.length; i += 2) dashes.push(pts[i], pts[i + 1]);
      line = new THREE.LineSegments(lineGeometry(dashes), new THREE.LineBasicMaterial(additive('#cfe0ee', 0)));
    }
    world.add(line);
    const sparks = calm ? [] : Array.from({length: 2}, (_, i) => {
      const spark = new THREE.Sprite(new THREE.SpriteMaterial({map: glow, ...additive('#e6fffb', 0)}));
      spark.scale.setScalar(70);
      spark.userData.offset = i / 2;
      spark.visible = false;
      world.add(spark);
      return spark;
    });
    const from = chapters.get(l.from), to = chapters.get(l.to);
    const portal = (t, other, text) => {
      const object = label(world, `<button type="button" data-chapter="${other.id}"><span>${text}</span><b>${h(chapterName(other))}</b>${h(other.label)}</button>`, 'city-portal is-away', curve.getPointAt(t), [0.5, 1]);
      portalAnchors.push({chapter: t < 0.5 ? l.from : l.to, object, element: object.element, hidden: false});
      return object.element;
    };
    return {link: l, curve, line, sparks, length: curve.getLength(), current: 0, target: LINK_OPACITY.rest, state: 'rest',
      portals: {[l.from]: portal(0.16, to, l.type === 'outline' ? '后续 →' : `${l.count} 条节点关联 →`), [l.to]: portal(0.84, from, l.type === 'outline' ? '← 先修' : `← ${l.count} 条节点关联`)}};
  });
  const pulse = new THREE.Mesh(new THREE.RingGeometry(12, 14, 48), new THREE.MeshBasicMaterial({color: '#ffffff', transparent: true, opacity: 0, depthWrite: false, side: THREE.DoubleSide}));
  world.add(pulse);
  scene.updateMatrixWorld(true);

  /* Camera. */
  const controls = new THREE.OrbitControls(camera, renderer.domElement);
  Object.assign(controls, {enableDamping: !calm, dampingFactor: 0.08, rotateSpeed: 0.55, zoomSpeed: 0.9, screenSpacePanning: true, minPolarAngle: Math.PI * 0.12, maxPolarAngle: Math.PI * 0.6, autoRotateSpeed: -0.7});
  controls.touches = {ONE: THREE.TOUCH.ROTATE, TWO: THREE.TOUCH.DOLLY_PAN};
  controls.mouseButtons = {LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.PAN};
  let size = {width: 1, height: 1}, towerFit = 2000, cityFit = 10000, inset = {x: 0, y: 0};
  const distanceFor = (width, height) => {
    const tan = Math.tan(THREE.MathUtils.degToRad(FOV / 2));
    return Math.max((height / 2) / tan, (width / 2) / (tan * camera.aspect)) * 1.04;
  };
  const visibleFor = (width, height) => distanceFor(width * size.width / Math.max(1, size.width - inset.x), height * size.height / Math.max(1, size.height - inset.y));
  const viewOffset = () => {
    if (inset.x || inset.y) camera.setViewOffset(size.width, size.height, inset.x / 2, inset.y / 2, size.width, size.height);
    else camera.clearViewOffset();
  };
  function resize() {
    const rect = container.getBoundingClientRect();
    size = {width: Math.max(1, rect.width), height: Math.max(1, rect.height)};
    renderer.setSize(size.width, size.height, false);
    labels.setSize(size.width, size.height);
    camera.aspect = size.width / size.height;
    viewOffset();
    camera.updateProjectionMatrix();
    towerFit = distanceFor((R + 150) * 2, TOWER.chapterY - FLOORS[0].y + 220);
    cityFit = distanceFor(extent * (size.width < 760 ? 1.05 : 1.7), extent * 0.95);
    controls.minDistance = 160;
    controls.maxDistance = cityFit * 1.6;
  }
  resize();
  const spherical = (theta, phi, r) => new THREE.Vector3(r * Math.sin(phi) * Math.sin(theta), r * Math.cos(phi), r * Math.sin(phi) * Math.cos(theta));
  const cityHome = () => {
    const first = [...towers.values()].find(t => t.chapter.built) || [...towers.values()][0];
    return {target: new THREE.Vector3(0, 0, 0), distance: cityFit, phi: 0.98, theta: facing(Math.atan2(first.pos.z, first.pos.x))};
  };
  const towerHome = id => {
    const t = towers.get(id), scale = t.chapter.built ? 1 : 0.9 * (t.pos.radius + 150) / (R + 150);
    // Along an avenue the neighbours stand in line, so look from the open side of the lane.
    const avenue = plan.districts.find(d => d.id === t.pos.strand);
    const side = t.pos.lane === 'elective' ? 1 : -1;
    const angle = avenue && t.pos.lane !== 'plaza' ? avenue.angle + side * (Math.PI / 2 - 0.35) : t.pos.distance > 40 ? Math.atan2(t.pos.z, t.pos.x) : 0;
    const built = t.chapter.built, fit = towerFit * (size.width < 760 ? 1.05 : 1.18) * Math.max(0.75, scale) * (built ? 1 : 1.9);
    return {target: t.center.clone().setY(built ? towerMid - 120 : towerMid), distance: fit, phi: built ? 1.26 : 1.05, theta: facing(angle)};
  };
  {
    const start = cityHome();
    controls.target.copy(start.target);
    camera.position.copy(start.target).add(spherical(start.theta, start.phi, start.distance));
    controls.update();
  }
  let tween = null;
  function flyTo({target, distance, theta, phi}) {
    const offset = camera.position.clone().sub(controls.target), r0 = offset.length();
    const theta0 = Math.atan2(offset.x, offset.z), phi0 = Math.acos(THREE.MathUtils.clamp(offset.y / r0, -1, 1));
    const turn = theta === undefined ? 0 : Math.atan2(Math.sin(theta - theta0), Math.cos(theta - theta0));
    const far = target.distanceTo(controls.target) > 2000;
    tween = {start: performance.now(), duration: calm ? 1 : far ? 1700 : 1100, from: controls.target.clone(), to: target, r0, r1: THREE.MathUtils.clamp(distance, controls.minDistance, controls.maxDistance), theta0, theta1: theta0 + turn, phi0, phi1: phi ?? phi0, arc: far ? Math.max(r0, distance) * 0.35 : 0};
  }
  const worldPos = id => items.get(id).group.getWorldPosition(new THREE.Vector3());
  const towerCenter = () => towers.get(state.chapter)?.center || new THREE.Vector3();
  function frame(ids, {phi = 1.25, pad = 1} = {}) {
    const points = ids.filter(id => items.has(id) && !items.get(id).out).map(worldPos);
    if (!points.length) return;
    const center = points.reduce((s, p) => s.add(p), new THREE.Vector3()).divideScalar(points.length), base = towerCenter();
    const dx = center.x - base.x, dz = center.z - base.z, horizontal = Math.hypot(dx, dz);
    const spread = Math.max(140, ...points.map(p => p.distanceTo(center) * 2));
    flyTo({target: center, distance: visibleFor(spread * 1.25 * pad, spread * pad) + (horizontal < 40 ? 200 : 0), theta: horizontal > 40 ? facing(Math.atan2(dz, dx)) : undefined, phi});
  }
  function focusNode(id) {
    const item = items.get(id);
    if (!item) return;
    const lit = [...neighbourhood(id)].filter(k => items.has(k) && !items.get(k).out);
    if (lit.length > 1 && lit.length < 18) frame(lit, {pad: 1.05});
    else flyTo({target: worldPos(id), distance: towerFit * 0.42, theta: item.p.radius > 40 ? facing(item.p.angle) : undefined, phi: 1.3});
  }
  function focusSection(id) {
    const info = towers.get(state.chapter), s = info?.layout?.sectors.find(x => x.id === id);
    if (!s) return;
    const members = [...items.keys()].filter(key => sectionsOf(key).includes(id) && !items.get(key).out);
    const base = info.center, target = new THREE.Vector3(base.x + Math.cos(s.mid) * R * 0.4, towerMid - 145, base.z + Math.sin(s.mid) * R * 0.4);
    const spread = Math.max(...members.map(key => Math.hypot(worldPos(key).x - target.x, worldPos(key).z - target.z)), R * 0.6) * 2;
    flyTo({target, distance: Math.max(distanceFor(spread * 1.15, TOWER.chapterY - FLOORS[0].y + 160), towerFit * 0.8), theta: facing(s.mid), phi: 1.24});
  }
  function focusStrand(id) {
    const ids = [...towers.values()].filter(t => t.chapter.strand === id), d = plan.districts.find(x => x.id === id);
    if (!ids.length) return;
    const center = ids.reduce((s, t) => s.add(t.center), new THREE.Vector3()).divideScalar(ids.length);
    const spread = Math.max(1200, ...ids.map(t => t.center.distanceTo(center) * 2 + t.pos.radius * 2));
    flyTo({target: center, distance: distanceFor(spread * 1.3, spread * 0.8), theta: d ? facing(d.angle) - 0.35 : undefined, phi: 1.02});
  }
  let lastInteraction = -Infinity;
  controls.addEventListener('start', () => { lastInteraction = performance.now(); tween = null; });

  /* Relations and highlight. */
  function neighbourhood(id) {
    const set = new Set([id]);
    for (const entry of edges) if (!entry.out) { if (entry.edge.from === id) set.add(entry.edge.to); if (entry.edge.to === id) set.add(entry.edge.from); }
    const n = byId.get(id);
    if (['section','collection'].includes(n?.kind)) for (const [key] of items) if (sectionsOf(key).includes(id)) set.add(key);
    if (n && !ORG.includes(n.kind)) for (const s of sectionsOf(id)) set.add(s);
    return set;
  }
  function apply() {
    const now = performance.now(), inTower = state.level === 'tower', entered = inTower ? state.chapter : '';
    container.classList.toggle('level-city', !inTower);
    container.classList.toggle('level-tower', inTower);
    for (const [, item] of items) {
      item.out = !state.floors.has(floorOf(item.node));
      item.away = item.tower !== entered;
      item.element.classList.toggle('is-out', item.out);
    }
    for (const entry of edges) entry.out = items.get(entry.edge.from).out || items.get(entry.edge.to).out || (entry.family !== 'org' && !state.families.has(entry.family));
    const active = inTower ? state.hover || state.node : '';
    let related = null, hops = new Map(), strong = () => false, focus = '';
    if (state.play) {
      related = state.play.lit; focus = state.play.id;
      strong = entry => state.play.edges.has(entry.edge.id);
    } else if (active && items.has(active)) {
      related = neighbourhood(active); focus = active;
      related.forEach(id => hops.set(id, id === active ? 0 : 1));
      strong = entry => entry.edge.from === active || entry.edge.to === active;
    } else if (inTower && state.section) {
      related = new Set([state.section, ...[...items.keys()].filter(id => sectionsOf(id).includes(state.section))]);
      for (const e of graph.edges) {
        if (e.type === 'contains' && e.to === state.section) related.add(e.from);
        if (['contains', 'extends'].includes(e.type) && e.from === state.section) related.add(e.to);
      }
    }
    const delay = calm ? 0 : state.hover ? HOP_DELAY * 0.5 : HOP_DELAY;
    const litTower = id => !inTower ? (!state.hoverTower && !state.strand) || state.hoverTower === id || chapters.get(id).strand === state.strand : id === entered;
    for (const [id, item] of items) {
      // Inside a tower, nodes of other towers that relate to the focus light up where they stand.
      const reached = inTower && item.away && !item.out && Boolean(related?.has(id));
      item.element.classList.toggle('is-away', item.away && !reached);
      item.element.querySelector('button').tabIndex = item.away && !reached ? -1 : 0;
      const kind = item.out ? 'out' : item.away && !reached ? (litTower(item.tower) ? 'away' : 'dim') : !related ? 'rest' : id === focus ? 'selected' : related.has(id) ? 'related' : 'dim';
      item.target = {...NODE_TARGET[kind]};
      if (item.away && !inTower && litTower(item.tower)) item.target = {...NODE_TARGET.rest};
      item.startAt = now + (hops.get(id) ?? 0) * delay;
      item.element.classList.toggle('is-selected', id === focus || Boolean(state.play?.current.has(id)));
      item.element.classList.toggle('is-related', kind === 'related');
      item.element.classList.toggle('is-dim', kind === 'dim');
    }
    for (const entry of edges) {
      const both = related && related.has(entry.edge.from) && related.has(entry.edge.to);
      if (entry.cross) {
        const near = id => id && entry.towers.includes(id), strand = state.strand && entry.towers.some(id => chapters.get(id).strand === state.strand);
        entry.state = entry.out ? 'hidden'
          : !inTower ? (near(state.hoverTower) || strand ? 'shown' : state.hoverTower || state.strand ? 'faint' : 'cross')
          : !near(entered) ? 'faint' : !related ? 'shown' : strong(entry) ? 'strong' : both ? 'shown' : 'faint';
      } else entry.state = entry.out ? 'hidden' : entry.tower !== entered ? (inTower ? 'faint' : 'city') : !related ? 'rest' : strong(entry) ? 'strong' : state.section && !active && both ? 'shown' : 'faint';
      entry.target = EDGE_OPACITY[entry.state];
      entry.startAt = now + (entry.state === 'strong' && !state.play ? delay : 0);
    }
    for (const set of sectorSets) set.parts.forEach(part => {
      const on = set.chapter === entered, lit = !on ? !inTower : !related || part.sector.id === state.section || (focus && sectionsOf(focus).includes(part.sector.id)) || focus === part.sector.id;
      part.arcs.forEach(arc => { arc.material.opacity = lit ? (related && on ? 0.95 : 0.45) : 0.12; });
    });
    for (const set of floorLabelSets) set.labels.forEach(f => {
      f.object.element.classList.toggle('is-away', set.chapter !== entered);
      f.object.element.classList.toggle('is-out', !state.floors.has(f.floor.key));
    });
    for (const [id, ghost] of ghosts) {
      ghost.target = litTower(id) ? 1 : inTower ? 0.12 : 0.3;
      ghost.sectionLabels.forEach(s => s.object.element.classList.toggle('is-away', id !== entered));
    }
    for (const [id, element] of cityLabels) {
      element.classList.toggle('is-current', id === entered);
      element.classList.toggle('is-hover', id === state.hoverTower);
      element.classList.toggle('is-dim', !litTower(id) && id !== state.hoverTower);
    }
    for (const [id, f] of footprints) f.material.opacity = litTower(id) ? 0.55 : inTower ? 0.08 : 0.18;
    groundLabels.forEach(g => g.element.classList.toggle('is-away', inTower));
    for (const entry of links) {
      const {from, to} = entry.link, key = inTower ? entered : state.hoverTower;
      const touching = key && (from === key || to === key), inStrand = !inTower && state.strand && (chapters.get(from).strand === state.strand || chapters.get(to).strand === state.strand);
      // Inside a tower the node-level arcs replace the aggregated chapter relation.
      entry.state = (touching && !(inTower && entry.link.type === 'relation')) || inStrand ? 'strong' : inTower || state.hoverTower || state.strand ? 'faint' : 'rest';
      entry.target = LINK_OPACITY[entry.state];
      for (const [chapterId, element] of Object.entries(entry.portals)) element.classList.toggle('is-away', !(inTower && chapterId === entered));
    }
  }

  /* Picking and hover. */
  const raycaster = new THREE.Raycaster(), pointer = new THREE.Vector2();
  const ray = event => {
    const rect = renderer.domElement.getBoundingClientRect();
    pointer.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
    raycaster.setFromCamera(pointer, camera);
  };
  const pick = event => {
    ray(event);
    if (state.level === 'tower') {
      const node = raycaster.intersectObjects(hitTargets.filter(t => { const item = items.get(t.userData.id); return !item.out && !item.away; }), false)[0]?.object.userData.id;
      if (node) return {node};
      const other = raycaster.intersectObjects(towerHits.filter(t => t.userData.chapter !== state.chapter), false)[0]?.object.userData.chapter;
      return other ? {chapter: other} : {};
    }
    const chapter = raycaster.intersectObjects(towerHits, false)[0]?.object.userData.chapter;
    return chapter ? {chapter} : {};
  };
  const setHover = ({node = '', chapter = ''} = {}) => {
    if (node === state.hover && chapter === state.hoverTower) return;
    if (state.hover) items.get(state.hover)?.element.classList.remove('is-hover');
    state.hover = node;
    state.hoverTower = state.level === 'city' ? chapter : '';
    if (node) items.get(node).element.classList.add('is-hover');
    renderer.domElement.style.cursor = node || chapter ? 'pointer' : '';
    if (!state.play) apply();
  };
  let down = null;
  renderer.domElement.addEventListener('pointerdown', event => { down = {x: event.clientX, y: event.clientY}; lastInteraction = performance.now(); });
  renderer.domElement.addEventListener('pointerup', event => {
    if (!down || Math.hypot(event.clientX - down.x, event.clientY - down.y) > 6) { down = null; return; }
    down = null;
    const hit = pick(event);
    if (hit.node) select(hit.node);
    else if (hit.chapter) enterTower(hit.chapter);
    else if (state.node || state.section) select('');
  });
  renderer.domElement.addEventListener('pointermove', event => { if (event.pointerType === 'mouse' && !event.buttons) setHover(pick(event)); });
  renderer.domElement.addEventListener('pointerleave', () => setHover());
  const nodeOf = event => event.target.closest?.('[data-node]')?.dataset.node || '';
  const chapterOf = event => event.target.closest?.('[data-chapter]')?.dataset.chapter || '';
  labels.domElement.addEventListener('click', event => {
    const id = nodeOf(event), chapter = chapterOf(event);
    if (id) select(id); else if (chapter) enterTower(chapter);
  });
  labels.domElement.addEventListener('pointerover', event => {
    if (event.pointerType !== 'mouse') return;
    if (nodeOf(event)) setHover({node: nodeOf(event)});
    else if (chapterOf(event) && state.level === 'city') setHover({chapter: chapterOf(event)});
  });
  labels.domElement.addEventListener('pointerout', event => {
    const target = event.target.closest?.('[data-node],[data-chapter]');
    if (event.pointerType === 'mouse' && target && !target.contains(event.relatedTarget)) setHover();
  });
  labels.domElement.addEventListener('focusin', event => { if (nodeOf(event)) setHover({node: nodeOf(event)}); });
  labels.domElement.addEventListener('focusout', () => setHover());

  /* Frame loop. */
  let visible = true, raf = 0, last = performance.now(), labelScale = -1, far = null, near = null;
  new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; if (visible) start(); }).observe(container);
  new ResizeObserver(() => resize()).observe(container);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) start(); });
  const right = new THREE.Vector3(), toCamera = new THREE.Vector3();
  function tick(now) {
    raf = 0;
    if (!visible || document.hidden) return;
    const dt = Math.min(0.05, (now - last) / 1000), k = calm ? 1 : 1 - Math.exp(-dt * 9), seconds = calm ? 0 : now / 1000;
    last = now;
    if (tween) {
      const t = Math.min(1, (now - tween.start) / tween.duration), e = ease(t);
      controls.target.lerpVectors(tween.from, tween.to, e);
      const r = lerp(tween.r0, tween.r1, e) + Math.sin(e * Math.PI) * tween.arc;
      camera.position.copy(controls.target).add(spherical(lerp(tween.theta0, tween.theta1, e), lerp(tween.phi0, tween.phi1, e), r));
      if (t === 1) tween = null;
    }
    controls.autoRotate = state.spin && !tween && !state.play && now - lastInteraction > IDLE_SPIN;
    controls.update(dt);
    stars.rotation.y = seconds / 900;

    for (const item of items.values()) {
      if (now >= item.startAt) for (const key of ['glow', 'opacity', 'scale']) item.current[key] = lerp(item.current[key], item.target[key], k);
      const {glow: g, opacity, scale} = item.current;
      item.group.visible = opacity > 0.02;
      item.parts.forEach(part => { part.material.opacity = part.userData.base * opacity; });
      item.body.scale.setScalar(scale);
      item.halo.material.opacity = Math.min(1, g * 0.5);
      item.halo.scale.setScalar(item.haloSize * (0.75 + g * 0.3));
      if (item.spin) item.body.rotation.y = seconds * item.spin;
    }
    for (const entry of edges) {
      if (now >= entry.startAt) entry.current = lerp(entry.current, entry.target, k);
      entry.tube.material.opacity = entry.current;
      entry.tube.visible = entry.current > 0.005;
      const flowing = entry.state === 'strong' && entry.current > 0.2;
      for (const spark of entry.sparks) {
        spark.visible = flowing;
        if (!flowing) continue;
        const t = (seconds * 120 / entry.length + spark.userData.offset) % 1;
        spark.position.copy(entry.curve.getPointAt(t));
        spark.material.opacity = Math.sin(t * Math.PI) * entry.current;
      }
    }
    for (const entry of links) {
      entry.current = lerp(entry.current, entry.target, k);
      entry.line.material.opacity = entry.current;
      const flowing = entry.state === 'strong' && entry.current > 0.3;
      for (const spark of entry.sparks) {
        spark.visible = flowing;
        if (!flowing) continue;
        const t = (seconds * 900 / entry.length + spark.userData.offset) % 1;
        spark.position.copy(entry.curve.getPointAt(t));
        spark.material.opacity = Math.sin(t * Math.PI) * entry.current;
      }
    }
    for (const ghost of ghosts.values()) {
      ghost.fade = lerp(ghost.fade, ghost.target, k);
      ghost.parts.forEach(part => { part.material.opacity = part.userData.base * ghost.fade; });
      ghost.crown.rotation.y = seconds * 0.4;
    }
    axisSparks.forEach(spark => {
      const t = (seconds / 6 + spark.userData.offset) % 1;
      spark.position.copy(spark.userData.curve.getPointAt(t));
      spark.material.opacity = calm ? 0 : Math.sin(t * Math.PI) * 0.7;
    });
    const focus = state.play?.id || state.node;
    if (!calm && focus && items.has(focus)) {
      const phase = (seconds % 1.6) / 1.6;
      pulse.position.copy(worldPos(focus));
      pulse.quaternion.copy(camera.quaternion);
      pulse.scale.setScalar(1 + phase * 2.6);
      pulse.material.opacity = 0.55 * (1 - phase);
    } else pulse.material.opacity = 0;

    // Inside a tower: far-side names fade, floor names keep to the left edge of the view.
    camera.updateMatrixWorld();
    if (state.level === 'tower') {
      const base = towerCenter();
      right.setFromMatrixColumn(camera.matrixWorld, 0).setY(0).normalize();
      toCamera.copy(camera.position).sub(base).setY(0).normalize();
      for (const item of items.values()) {
        if (item.away) continue;
        const back = item.p.radius > 60 && (Math.cos(item.p.angle) * toCamera.x + Math.sin(item.p.angle) * toCamera.z) < -0.25;
        if (back !== item.back) { item.back = back; item.element.classList.toggle('is-back', back); }
      }
      for (const ghost of ghosts.values()) ghost.sectionLabels.forEach(s => s.object.element.classList.toggle('is-back', (Math.cos(s.angle) * toCamera.x + Math.sin(s.angle) * toCamera.z) < -0.2));
      for (const set of floorLabelSets) if (set.chapter === state.chapter) for (const f of set.labels) f.object.position.set(-right.x * (R + 120), f.floor.y, -right.z * (R + 120));
    }
    const distance = camera.position.distanceTo(controls.target);
    const pixels = ((size.height / 2) / Math.tan(THREE.MathUtils.degToRad(FOV / 2))) / distance;
    const nextScale = Math.round(THREE.MathUtils.clamp(pixels * 1.05, 0.72, 1.12) * 100) / 100;
    if (nextScale !== labelScale) { labelScale = nextScale; container.style.setProperty('--tw-label-scale', String(labelScale)); }
    const nextFar = pixels < 0.42, nextNear = distance < towerFit * 0.8;
    if (nextFar !== far) { far = nextFar; container.classList.toggle('is-far', far); }
    if (nextNear !== near) { near = nextNear; container.classList.toggle('is-near', near); }

    if (++frameCount % 6 === 0) declutter();
    renderer.render(scene, camera);
    labels.render(scene, camera);
    raf = requestAnimationFrame(tick);
  }
  // Chapter cards: distant towers shrink to a name tag; where cards still collide the nearer one
  // wins, except that the lit and hovered chapters always stay readable.
  let frameCount = 0;
  const anchor = new THREE.Vector3(), placed = [];
  function declutter() {
    const smallFrom = cityFit * (state.level === 'city' ? 1.08 : 0.55);
    placed.length = 0;
    const origin = container.getBoundingClientRect();
    for (const panel of container.parentElement.querySelectorAll('.tower-hud, .tower-drawer')) {
      const r = panel.getBoundingClientRect();
      if (r.width && r.height && !panel.hidden) placed.push({l: r.left - origin.left, r: r.right - origin.left, t: r.top - origin.top, b: r.bottom - origin.top});
    }
    const own = state.level !== 'tower' ? [] : portalAnchors.filter(p => p.chapter === state.chapter).map(p => {
      p.object.getWorldPosition(anchor);
      const distance = anchor.distanceTo(camera.position);
      anchor.project(camera);
      return {p, distance, x: (anchor.x + 1) / 2 * size.width, y: (1 - anchor.y) / 2 * size.height, front: anchor.z < 1};
    }).sort((a, b) => a.distance - b.distance);
    const list = cityAnchors.map(a => {
      a.object.getWorldPosition(anchor);
      const distance = anchor.distanceTo(camera.position);
      anchor.project(camera);
      return {a, distance, x: (anchor.x + 1) / 2 * size.width, y: (1 - anchor.y) / 2 * size.height, front: anchor.z < 1};
    }).sort((p, q) => (q.a.id === state.hoverTower) - (p.a.id === state.hoverTower) || q.a.built - p.a.built || p.distance - q.distance);
    const ground = state.level !== 'city' ? [] : groundLabels.map(g => {
      g.getWorldPosition(anchor).project(camera);
      return {g, x: (anchor.x + 1) / 2 * size.width, y: (1 - anchor.y) / 2 * size.height, front: anchor.z < 1};
    });
    // Size-changing writes first, then every read, then the visibility writes,
    // so one frame costs at most one layout instead of one per label.
    for (const {a, distance} of list) {
      const small = !a.built && a.id !== state.hoverTower && distance > smallFrom;
      if (small !== a.small) { a.small = small; a.element.classList.toggle('is-small', small); }
    }
    for (const item of own) item.size = {w: item.p.element.offsetWidth, h: item.p.element.offsetHeight};
    // Progress and its retry control can change the label's height after it
    // first appears. Include the whole non-interactive card in collision tests.
    for (const item of list) { const card = item.a.element.firstElementChild; item.a.size = {w: card.offsetWidth, h: card.offsetHeight}; }
    for (const item of ground) item.size = {w: item.g.element.offsetWidth, h: item.g.element.offsetHeight};
    const overlaps = box => placed.some(q => box.l < q.r && box.r > q.l && box.t < q.b && box.b > q.t);
    for (const {p, x, y, front, size: s} of own) {
      const box = {l: x - s.w / 2 - 4, r: x + s.w / 2 + 4, t: y - s.h - 4, b: y + 2};
      const hidden = !front || overlaps(box);
      if (!hidden) placed.push(box);
      if (hidden !== p.hidden) { p.hidden = hidden; p.element.classList.toggle('is-crowded', hidden); }
    }
    for (const {a, x, y, front} of list) {
      if (a.id === state.chapter && state.level === 'tower') continue;
      const box = {l: x - a.size.w / 2 - 4, r: x + a.size.w / 2 + 4, t: y - a.size.h - 4, b: y + 2};
      const pinned = a.built || a.id === state.hoverTower;
      const hidden = !front || (!pinned && overlaps(box));
      if (!hidden) placed.push(box);
      if (hidden !== a.hidden) { a.hidden = hidden; a.element.classList.toggle('is-crowded', hidden); }
    }
    for (const {g, x, y, front, size: s} of ground) {
      const hidden = !front || overlaps({l: x - s.w / 2, r: x + s.w / 2, t: y - s.h / 2, b: y + s.h / 2});
      g.element.classList.toggle('is-crowded', hidden);
    }
  }
  function start() { if (!raf && visible && !document.hidden) { last = performance.now(); raf = requestAnimationFrame(tick); } }
  start();

  return {
    apply, focusNode, focusSection, focusStrand, frame,
    goCity: () => flyTo(cityHome()),
    goTower: id => flyTo(towerHome(id)),
    setInset(x = 0, y = 0) { inset = {x, y}; viewOffset(); camera.updateProjectionMatrix(); },
    touch(idle = false) { lastInteraction = idle ? -Infinity : performance.now(); },
  };
}

/* Drawer, crumbs, bottom bar, search and URL state. */
const drawer = () => $('#tower-drawer'), selection = () => $('#tower-selection');
const graph2D = n => {
  if (!n.home) return '/knowledge/';
  const scope = ORG.includes(n.kind) ? n.id : sectionsOf(n.id)[0] || chapters.get(n.home).node;
  const v = ORG.includes(n.kind) ? 'curriculum' : n.kind === 'knowledge' ? 'knowledge' : 'solution';
  return `${groupPath(chapters.get(n.home))}?scope=${scope}&view=${v}&node=${n.id}&expand=${n.id}`;
};
const chip = n => `<button type="button" class="rel-node" data-kind="${n.kind}" data-select="${n.id}"><i aria-hidden="true"></i>${h(n.label)}</button>`;
const chapterChip = (c, note = '') => `<button type="button" class="rel-node chapter-chip" data-chapter-pick="${c.id}" style="--kg:${strandColor(c.strand)}"><i aria-hidden="true"></i>${c.kind === 'collection' ? h(c.label) : `${h(chapterName(c))} ${h(c.label)}`}${note}</button>`;
const stepTargets = s => [...s.calls, ...(s.rule ? [s.rule] : [])];
function relationGroups(list, outgoing) {
  const groups = new Map();
  for (const e of list) groups.set(e.type, [...(groups.get(e.type) || []), e]);
  return [...groups].map(([type, group]) => `<li data-family="${FAMILY[type]}"><span class="rel-type">${outgoing ? '' : '被'}${RELATIONS[type]}</span><span class="rel-targets">${group.map(e => chip(byId.get(outgoing ? e.to : e.from))).join('')}</span></li>`).join('');
}
function placeDrawer() {
  if (drawer().hidden) view.setInset();
  else if (innerWidth > 900) view.setInset(380, 0);
  else if (innerWidth <= 760) view.setInset(0, drawer().offsetHeight + 8);
  else view.setInset();
}
function showChapterCard(c) {
  const outline = city.links.filter(l => l.type === 'outline');
  const before = outline.filter(l => l.to === c.id).map(l => chapters.get(l.from)), after = outline.filter(l => l.from === c.id).map(l => chapters.get(l.to));
  const linked = city.links.filter(l => l.type !== 'outline' && (l.from === c.id || l.to === c.id));
  const collection = c.kind === 'collection';
  const book = city.books.find(b => b.id === c.book), strand = city.strands.find(s => s.id === c.strand);
  drawer().hidden = false;
  state.card = true;
  const own = towers.get(c.id).graph?.nodes.filter(n => !ORG.includes(n.kind)) || [];
  selection().innerHTML = `<p class="drawer-kind" data-kind="chapter"><i aria-hidden="true"></i>${collection ? '知识集合' : '章'} · ${c.built ? '已录入' : c.partial ? '部分录入' : '建设中'}</p><h2>${h(c.label)}</h2>${c.node ? `<div data-progress-scope="${c.node}"></div>` : ''}
<p class="tower-home">${collection ? '按高中学习需要逐步收录的初中知识' : `${h(book.label)} · 第 ${c.number} 章<span>· ${h(strand.label)}${strand.center ? '' : '主线'}</span>`}</p>
<p class="drawer-summary">${collection ? '集合成员保留初中知识身份，跨学段前置关系连接高中知识。' : c.built ? '本章的公共知识节点已录入，可以在塔里逐个查看。' : c.partial ? `本章目前只录入了被其他章引用的 ${own.length} 个节点，其余各节仍按教材目录预留。跨章连线从这里通向引用它们的塔。` : `本章尚未录入公共知识节点。塔身按教材目录预留了 ${c.sections.length} 节的位置，录入后会像第二章一样点亮。`}</p>
${recorded(c) ? `<div class="drawer-actions"><a class="drawer-primary" href="${groupPath(c)}">打开${collection ? '集合' : '本章'}平面图谱 ↗</a></div>` : ''}
${collection ? '' : `<section class="drawer-path"><h3>本章的节 <span>${c.sections.length}</span></h3><ol>${c.sections.map((s, i) => `<li><span class="step-dot">${h(s.number.split('.')[1] || i + 1)}</span><div>${s.node ? `<button type="button" class="rel-node" data-kind="section" data-section-pick="${s.node}"><i aria-hidden="true"></i>${h(s.number)} ${h(s.label)}</button>` : `<b>${h(s.number)} ${h(s.label)}</b>`}</div></li>`).join('')}</ol></section>`}
${own.length ? `<h3>已录入的节点 <span>${own.length}</span></h3><ul class="rel-groups"><li data-family="know"><span class="rel-type">本章</span><span class="rel-targets">${own.map(chip).join('')}</span></li></ul>` : ''}
${linked.length ? `<h3>跨章知识关联 <span>节点级</span></h3><ul class="rel-groups"><li data-family="know"><span class="rel-type">连向</span><span class="rel-targets">${linked.map(l => chapterChip(chapters.get(l.from === c.id ? l.to : l.from), ` · ${l.count} 条`)).join('')}</span></li></ul>` : ''}
${before.length ? `<h3>章间先修 <span>目录级</span></h3><ul class="rel-groups"><li data-family="org"><span class="rel-type">先学</span><span class="rel-targets">${before.map(chapterChip).join('')}</span></li></ul>` : ''}
${after.length ? `<h3>后续章节 <span>${after.length}</span></h3><ul class="rel-groups"><li data-family="org"><span class="rel-type">会用到本章</span><span class="rel-targets">${after.map(chapterChip).join('')}</span></li></ul>` : ''}`;
  placeDrawer();
}
function showSelection() {
  const n = byId.get(state.node);
  state.card = false;
  drawer().hidden = !n;
  if (!n) { selection().replaceChildren(); placeDrawer(); return; }
  const out = graph.edges.filter(e => e.from === n.id), inc = graph.edges.filter(e => e.to === n.id), sections = sectionsOf(n.id).map(id => byId.get(id));
  selection().innerHTML = `<p class="drawer-kind" data-kind="${n.kind}"><i aria-hidden="true"></i>${kindText(n)}</p><h2>${h(n.label)}</h2>${ORG.includes(n.kind)?`<div data-progress-scope="${n.id}"></div>`:`<div data-learning-node="${n.id}" data-learning-full></div>`}
${sections.length ? `<p class="tower-home">位于 ${sections.map(s => `<button type="button" data-section-pick="${s.id}">${h(s.label.split(' ')[0])}</button>`).join('')}${sections.length > 1 ? '<span>· 多节共用</span>' : ''}</p>` : ''}
<p class="drawer-summary" data-math-text>${h(n.summary)}</p>
<div class="drawer-actions">${ORG.includes(n.kind) ? `<a class="drawer-primary" href="${graph2D(n)}">在平面图谱中查看 ↗</a>` : `<a class="drawer-primary" href="${nodeHref(n.id)}">${detailLabel(n)} ↗</a><a class="drawer-secondary" href="${graph2D(n)}">在平面图谱中查看</a>`}${n.steps?.length ? '<button type="button" id="tower-play" class="drawer-play">▶ 演示解题路径</button>' : ''}</div>
${n.steps?.length ? `<section class="drawer-path"><h3>解题路径</h3><ol>${n.steps.map((s, i) => `<li data-step="${i}"><span class="step-dot">${i + 1}</span><div><b>${h(s.title)}</b>${stepTargets(s).map(id => chip(byId.get(id))).join('')}</div></li>`).join('')}</ol></section>` : ''}
${out.length ? `<h3>它指向 <span>${out.length}</span></h3><ul class="rel-groups">${relationGroups(out, true)}</ul>` : ''}
${inc.length ? `<h3>指向它 <span>${inc.length}</span></h3><ul class="rel-groups">${relationGroups(inc, false)}</ul>` : ''}`;
  $('#tower-play')?.addEventListener('click', () => playPath(n));
  placeDrawer();
  renderLearningMath(selection()).catch(() => {});
}
function renderChrome() {
  const c = chapters.get(state.chapter), inTower = state.level === 'tower' && c;
  $('#city-crumbs').innerHTML = `<button type="button" data-go-city${inTower ? '' : ' aria-current="page"'}>全高中</button>${inTower ? `<span aria-hidden="true">›</span><span>${c.kind === 'collection' ? '知识集合' : h(city.books.find(b => b.id === c.book).label)}</span><span aria-hidden="true">›</span><span aria-current="page">${c.kind === 'collection' ? '' : `第 ${c.number} 章 `}${h(c.label)}</span>` : ''}`;
  const bar = $('#tower-sections');
  if (!inTower) bar.innerHTML = [['', '全景'], ...city.strands.map(s => [s.id, s.label])].map(([id, text]) => `<button type="button" data-strand="${id}" aria-pressed="${state.strand === id}"><b>${h(text)}</b></button>`).join('') + (city.collections || []).map(c => `<button type="button" data-chapter="${c.id}"><b>${h(c.label)}</b></button>`).join('');
  else if (c.kind === 'collection') bar.innerHTML = `<button type="button" data-go-city class="bar-back">← 全景</button><span>${h(c.label)} · ${nodeCount(c)} 个知识点</span>`;
  else if (recorded(c)) bar.innerHTML = `<button type="button" data-go-city class="bar-back">← 全景</button><button type="button" data-section-filter="" aria-pressed="${!state.section}"><b>全塔</b></button>${c.sections.filter(s => s.node).map(s => `<button type="button" data-section-filter="${s.node}" aria-pressed="${state.section === s.node}"><b>${h(s.number)}</b><span>${h(s.label)}</span></button>`).join('')}${c.partial ? `<span class="bar-note">其余 ${c.sections.filter(s => !s.node).length} 节建设中</span>` : ''}`;
  else bar.innerHTML = `<button type="button" data-go-city class="bar-back">← 全景</button><span class="bar-note">建设中 · ${c.sections.length} 节已按目录预留</span>`;
}
function updateURL() {
  const p = new URLSearchParams();
  if (state.node) p.set('node', state.node);
  else if (state.section) p.set('section', state.section);
  else if (state.level === 'tower') p.set('chapter', state.chapter);
  else if (state.strand) p.set('strand', state.strand);
  history.replaceState(null, '', modeHref(`${location.pathname}${p.size ? `?${p}` : ''}`, {preview:isPreview(location.search)}, location.href));
}
function refresh() { renderChrome(); updateURL(); view.apply(); view.touch(); }
function enterTower(id, {fly = true} = {}) {
  if (!chapters.has(id)) return;
  stopPath();
  Object.assign(state, {level: 'tower', chapter: id, node: '', section: '', strand: '', hoverTower: ''});
  if (chapters.get(id).built) { drawer().hidden = true; state.card = false; selection().replaceChildren(); placeDrawer(); } else showChapterCard(chapters.get(id));
  refresh();
  if (fly) view.goTower(id);
}
function goCity() {
  stopPath();
  Object.assign(state, {level: 'city', chapter: '', node: '', section: '', hover: ''});
  drawer().hidden = true; state.card = false; selection().replaceChildren(); placeDrawer();
  refresh();
  if (state.strand) view.focusStrand(state.strand); else view.goCity();
}
function chooseStrand(id) {
  state.strand = id;
  refresh();
  if (id) view.focusStrand(id); else view.goCity();
}
function select(id, {fly = true} = {}) {
  stopPath();
  if (id && nodeTower.get(id) !== state.chapter) { Object.assign(state, {level: 'tower', chapter: nodeTower.get(id), strand: ''}); }
  state.node = id;
  if (id) state.section = '';
  showSelection(); refresh();
  if (id && fly) view.focusNode(id);
}
function chooseSection(id) {
  stopPath();
  if (id && nodeTower.get(id) !== state.chapter) Object.assign(state, {level: 'tower', chapter: nodeTower.get(id), strand: ''});
  state.node = ''; state.section = id;
  showSelection(); refresh();
  if (id) view.focusSection(id); else view.goTower(state.chapter);
}
function back() {
  if (state.node || state.section) { state.section ? chooseSection('') : select(''); view.goTower(state.chapter); }
  else if (state.level === 'tower') goCity();
  else if (state.strand) chooseStrand('');
}

let playTimer = 0;
function stopPath() {
  clearTimeout(playTimer); playTimer = 0;
  if (!state.play) return;
  state.play = null;
  selection().querySelectorAll('.drawer-path li').forEach(li => li.classList.remove('is-current', 'is-done'));
  view.apply();
}
// Lights the method's ordered calls one step at a time, as on the detail page.
function playPath(n) {
  stopPath();
  for (const id of [n.id, ...n.steps.flatMap(stepTargets)]) state.floors.add(floorOf(byId.get(id)));
  syncFilters();
  const edgeOf = to => graph.edges.find(e => e.from === n.id && e.to === to)?.id;
  state.play = {id: n.id, lit: new Set([n.id]), current: new Set(), edges: new Set()};
  view.apply();
  view.frame([n.id, ...n.steps.flatMap(stepTargets)], {pad: 1.05});
  const rows = [...selection().querySelectorAll('.drawer-path li')];
  let i = 0;
  const step = () => {
    if (!state.play) return;
    rows.forEach((li, k) => { li.classList.toggle('is-current', k === i); li.classList.toggle('is-done', k < i); });
    state.play.current = new Set(i < n.steps.length ? stepTargets(n.steps[i]) : []);
    if (i < n.steps.length) for (const id of stepTargets(n.steps[i])) { state.play.lit.add(id); const e = edgeOf(id); if (e) state.play.edges.add(e); }
    view.apply();
    if (i >= n.steps.length) { playTimer = 0; return; }
    i += 1;
    playTimer = setTimeout(step, STEP_MS);
  };
  playTimer = setTimeout(step, calm ? 0 : 700);
}

function syncFilters() {
  $$('[name=floor]').forEach(input => { input.checked = state.floors.has(input.value); });
  $$('[name=family]').forEach(input => { input.checked = state.families.has(input.value); });
}
function wire() {
  $('#tower-drawer-close').addEventListener('click', () => { if (state.card) { drawer().hidden = true; state.card = false; placeDrawer(); } else select(''); });
  selection().addEventListener('click', event => {
    const id = event.target.closest('[data-select]')?.dataset.select, section = event.target.closest('[data-section-pick]')?.dataset.sectionPick, chapter = event.target.closest('[data-chapter-pick]')?.dataset.chapterPick;
    if (id) select(id); else if (section) chooseSection(section); else if (chapter) enterTower(chapter);
  });
  // The HUD is outside the CSS2D label root; keep its delegation separate so
  // canvas labels are not handled twice when their click bubbles to document.
  $('#tower-sections').addEventListener('click', event => {
    const chapter = event.target.closest('[data-chapter]');
    if (chapter) enterTower(chapter.dataset.chapter);
  });
  document.addEventListener('click', event => {
    if (event.target.closest('[data-go-city]')) goCity();
    const strand = event.target.closest('[data-strand]');
    if (strand) chooseStrand(strand.dataset.strand);
    const section = event.target.closest('[data-section-filter]');
    if (section) chooseSection(section.dataset.sectionFilter);
  });
  $$('[name=floor]').forEach(input => input.addEventListener('change', () => { state.floors[input.checked ? 'add' : 'delete'](input.value); stopPath(); view.apply(); }));
  $$('[name=family]').forEach(input => input.addEventListener('change', () => { state.families[input.checked ? 'add' : 'delete'](input.value); stopPath(); view.apply(); }));
  const spin = $('#tower-spin');
  spin.setAttribute('aria-pressed', String(state.spin));
  spin.addEventListener('click', () => { state.spin = !state.spin; spin.setAttribute('aria-pressed', String(state.spin)); view.touch(state.spin); });
  $('#tower-reset').addEventListener('click', () => { if (state.level === 'tower') { state.node || state.section ? back() : view.goTower(state.chapter); } else { state.strand = ''; refresh(); view.goCity(); } });
  addEventListener('keydown', event => { if (event.key === 'Escape' && !event.target.closest?.('input')) back(); });

  const input = $('#tower-search'), results = $('#tower-results');
  const entries = [
    ...graph.nodes.filter(n => nodeTower.has(n.id)).map(n => ({key: n.id, label: n.label, aliases: n.aliases || [], kind: n.kind, note: KINDS[n.kind], run: () => select(n.id)})),
    ...cityGroups(city).map(c => ({key: c.id, label: c.label, aliases: c.kind === 'collection' ? [] : [`第${c.number}章`], kind: c.kind || 'chapter', note: `${chapterName(c)}${c.built ? '' : c.partial ? ' · 部分录入' : ' · 建设中'}`, run: () => enterTower(c.id)})),
    ...city.chapters.flatMap(c => c.sections.filter(s => !s.node).map(s => ({key: `${c.id}-${s.number}`, label: `${s.number} ${s.label}`, aliases: [], kind: 'section', note: `节 · ${chapterName(c)} · 建设中`, run: () => enterTower(c.id)}))),
  ];
  let found = [];
  const render = () => {
    const q = input.value.trim().toLocaleLowerCase();
    found = q ? entries.filter(e => [e.label, ...e.aliases].some(x => x.toLocaleLowerCase().includes(q))).slice(0, 14) : [];
    results.hidden = !q;
    results.innerHTML = found.length ? found.map((e, i) => `<li><button type="button" data-kind="${e.kind}" data-result="${i}"><i aria-hidden="true"></i><span>${h(e.label)}</span><small>${h(e.note)}</small></button></li>`).join('') : '<li class="search-empty">没有匹配的章、节或节点</li>';
  };
  input.addEventListener('input', render);
  input.addEventListener('keydown', event => {
    if (event.key === 'Enter') { render(); if (found[0]) { results.hidden = true; found[0].run(); } }
    if (event.key === 'Escape') { input.value = ''; results.hidden = true; }
  });
  results.addEventListener('click', event => { const i = event.target.closest('[data-result]')?.dataset.result; if (i !== undefined && found[i]) { results.hidden = true; input.value = ''; found[i].run(); } });
  document.addEventListener('click', event => { if (!event.target.closest('.tower-search')) results.hidden = true; });
}

async function boot() {
  $('#tower-retry').hidden = true;
  if (!webglAvailable()) {
    status('当前浏览器无法使用 WebGL，3D 知识图谱无法显示。可改用平面图谱或下方的节点目录。');
    document.body.classList.add('tower-failed');
    return;
  }
  try {
    const [g, c] = await Promise.all(['/knowledge/graph.json', '/knowledge/city.json'].map(async url => { const res = await fetch(url, {cache: 'no-cache'}); if (!res.ok) throw new Error(String(res.status)); return res.json(); }));
    graph = g; city = c;
  } catch {
    status('知识图谱数据加载失败，请检查网络后重试。');
    $('#tower-retry').hidden = false;
    return;
  }
  byId = new Map(graph.nodes.map(n => [n.id, n]));
  plan = cityLayout(city);
  const homes = homeChapters(city, graph), floorY = {sectionY: TOWER.sectionY, y: Object.fromEntries(FLOORS.map(f => [f.key, f.y]))};
  for (const c of cityGroups(city)) {
    chapters.set(c.id, c);
    const info = {chapter: c, pos: plan.towers.get(c.id)};
    if (recorded(c)) {
      info.graph = chapterGraph(graph, homes, c.id);
      info.layout = c.built ? towerLayout(info.graph) : scaffoldLayout(c, info.graph, info.pos.radius, floorY);
      for (const n of info.graph.nodes) if (info.layout.positions.has(n.id)) nodeTower.set(n.id, c.id);
    }
    towers.set(c.id, info);
  }
  view = mount();
  wire();
  const built = city.chapters.filter(c => c.built), partial = city.chapters.filter(c => c.partial);
  const total = [...built, ...partial, ...(city.collections || [])].reduce((sum, c) => sum + nodeCount(c), 0);
  status(`${city.chapters.length} 章${city.collections?.length ? ` · ${city.collections.length} 个知识集合` : ''} · 已录入 ${built.length} 章${partial.length ? `、部分录入 ${partial.length} 章` : ''}（${total} 个节点）· ${touch ? '单指旋转，双指缩放' : '拖动旋转，滚轮缩放，右键平移'}`);
  document.body.classList.add('tower-ready');
  const p = new URLSearchParams(location.search);
  renderChrome();
  if (nodeTower.has(p.get('node'))) select(p.get('node'));
  else if (['section', 'collection'].includes(byId.get(p.get('section'))?.kind) && nodeTower.has(p.get('section'))) chooseSection(p.get('section'));
  else if (chapters.has(p.get('chapter'))) enterTower(p.get('chapter'));
  else if (city.strands.some(s => s.id === p.get('strand'))) chooseStrand(p.get('strand'));
  else view.apply();
}
$('#tower-retry')?.addEventListener('click', boot);
boot();
