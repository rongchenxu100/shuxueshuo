import test from 'node:test';
import assert from 'node:assert/strict';
import {loadSources} from '../build-public-knowledge-graph.mjs';
import {validateGraph, scopeMembers} from '../../site/assets/knowledge-next/model.mjs';
import diagrams, {
  DOMAIN_CASES, PAIR_CASES, OPERATION_CASES, COMPOSITION_CASES, INTERVAL_CASES,
  domainPair, pairValues, compositionValues, intervalState, symmetryState,
} from '../../site/assets/explain/knowledge/parity-explorer.js';

const near = (a,b) => assert.ok(Math.abs(a-b)<1e-9, `${a} ≈ ${b}`);

test('parity follows the three textbook knowledge nodes and every visualization belongs to an entry', async () => {
  const {nodes,manifest}=await loadSources();
  const graph={nodes,edges:validateGraph(nodes,manifest)};
  const ids=['function-parity','function-parity-graph','function-graph-symmetry'];
  assert.equal(manifest.expectedCounts.knowledge,32);
  for(const id of ids) {
    const node=nodes.find(n=>n.id===id);
    assert.equal(node.kind,'knowledge');
    assert.ok(scopeMembers(graph,'section-3-2').has(id));
    assert.ok(node.resources.length);
    for(const resourceId of node.resources) {
      const r=manifest.resources[resourceId];
      assert.ok(node.entries.some(entry=>entry.id===r.after));
      assert.equal(typeof diagrams[r.part],'function');
      const html=diagrams[r.part]();
      assert.match(html, /role="img" aria-label="[^"]+"/);
      assert.doesNotMatch(html, /NaN|undefined|Infinity/);
    }
  }
  const first=nodes.find(n=>n.id===ids[0]);
  assert.ok(first.entries.some(e=>e.id==='operations'));
  assert.ok(first.entries.some(e=>e.id==='composition'));
  const second=nodes.find(n=>n.id===ids[1]);
  assert.ok(second.entries.some(e=>e.id==='monotonicity'));
  assert.ok(second.entries.some(e=>e.id==='extrema'));
});

test('domain pairing respects missing points and open endpoints even after cancellation', () => {
  for(const key of ['closed','pairedHoles']) {
    const c=DOMAIN_CASES[key];
    for(const x of [-3,-2,-1.5,-1,0,1,1.5,2,3]) assert.equal(c.contains(x),c.contains(-x));
    assert.equal(domainPair(c).reflectedValid,true);
  }
  for(const key of ['halfOpen','asymmetric','hole']) {
    const p=domainPair(DOMAIN_CASES[key]);
    assert.equal(p.valid,true);
    assert.equal(p.reflectedValid,false);
  }
  assert.equal(DOMAIN_CASES.pairedHoles.contains(-1),false);
  assert.equal(DOMAIN_CASES.pairedHoles.contains(1),false);
  assert.equal(DOMAIN_CASES.hole.contains(-1+1e-9),true,'a missing point is not a missing interval');
});

test('the displayed odd, even, zero and neither examples satisfy their claimed identities', () => {
  for(const a of [.3,1,1.5,2.4]) {
    for(const c of [...Object.values(PAIR_CASES),...Object.values(OPERATION_CASES)]) {
      const {left,right}=pairValues({f:c.h||c.f},a);
      if(['odd','both'].includes(c.parity)) near(left,-right);
      if(['even','both'].includes(c.parity)) near(left,right);
      if(c.parity==='neither') {assert.notEqual(left,right);assert.notEqual(left,-right);}
    }
  }
  assert.ok(Number.isNaN(OPERATION_CASES.quotient.h(0)),'cancelled denominator must retain its hole');
  assert.ok(Number.isFinite(OPERATION_CASES.quotient.h(1e-10)),'nonzero inputs remain valid');
});

test('composition transmits paired inputs through the actual inner and outer functions', () => {
  for(const c of Object.values(COMPOSITION_CASES)) for(const a of [.3,.8,1.3]) {
    const v=compositionValues(c,a);
    assert.deepEqual(v.inputs,[a,-a]);
    for(let i=0;i<2;i++) near(v.outer[i],c.f(c.g(v.inputs[i])));
    near(v.outer[1],c.parity==='odd'?-v.outer[0]:v.outer[0]);
  }
  const v=compositionValues(COMPOSITION_CASES.evenNeither,1.3);
  near(v.inner[0],v.inner[1]);
  near(v.outer[0],v.outer[1]);
});

test('mirrored intervals preserve odd monotonicity, reverse even monotonicity, and transfer extrema', () => {
  for(const c of Object.values(INTERVAL_CASES)) {
    const s=intervalState(c);
    assert.equal(s.f(-3)<s.f(-1),s.leftIncreasing);
    assert.equal(s.leftIncreasing,c.odd?c.increasing:!c.increasing);
    near(s.left.max.y,c.odd?-s.right.min.y:s.right.max.y);
    near(s.left.min.y,c.odd?-s.right.max.y:s.right.min.y);
    near(s.left.max.x,c.odd?-s.right.min.x:-s.right.max.x);
    near(s.left.min.x,c.odd?-s.right.max.x:-s.right.min.x);
  }
});

test('shifted symmetry pairs remain valid across all slider extremes and translate to odd/even identities', () => {
  for(const kind of ['axis','center']) for(const a of [-1.5,0,1.5]) for(const b of [-1.5,0,1.5]) for(const t of [.3,1.2,1.8]) {
    const s=symmetryState(kind,a,b,t);
    near((s.left.x+s.right.x)/2,a);
    if(kind==='center') {
      near((s.left.y+s.right.y)/2,b);
      near(s.f(a-t)-b,-(s.f(a+t)-b));
    } else {
      near(s.left.y,s.right.y);
      near(s.f(a-t),s.f(a+t));
    }
    assert.ok(Math.abs(s.left.x)<=4 && Math.abs(s.right.x)<=4);
    assert.ok(Math.abs(s.left.y)<=6 && Math.abs(s.right.y)<=6);
  }
});
