import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {createHash} from 'node:crypto';
import {loadSources,generate,publish,repoRoot} from '../build-public-knowledge-graph.mjs';
import {validateGraph,deriveEdges,inheritedKnowledge,scopeMembers,projectGraph,readState,writeState,safeGraphReturn,searchNodes,curriculumStructure,KINDS,normalizeViewFilters} from '../../site/assets/knowledge-next/model.mjs';
import {layoutGraph,wrapLabel,fitGraph} from '../../site/assets/knowledge-next/layout.mjs';
import {rewriteResourceLinks} from '../../site/assets/knowledge-next/resource-links.mjs';
import {towerLayout} from '../../site/assets/knowledge-next/tower.mjs';
import {buildCity,cityLayout,chapterGraph,homeChapters,scaffoldLayout,towerRadius,CITY} from '../../site/assets/knowledge-next/city.mjs';
const sources=await loadSources(),{nodes,manifest}=sources,edges=validateGraph(nodes,manifest),graph={nodes,edges,defaultScope:manifest.defaultScope};
const clone=()=>structuredClone(nodes);
const byId=id=>nodes.find(n=>n.id===id);

test('substantive originals retain explicit lifecycle states and curriculum or collection membership',()=>{
  assert.equal(nodes.length,Object.values(manifest.expectedCounts).reduce((sum,n)=>sum+n,0));assert.equal(Object.keys(KINDS).length,9);
  const whole=scopeMembers(graph,'chapter-quadratic-equations-inequalities');
  assert.equal(whole.size,63);
  for(const id of ['quantifiers','function-monotonicity','function-range-extrema'])assert.ok(whole.has(id),`${id} 仍由 2.3 拓展引用`);
  assert.equal(byId('method-complete-square').kind,'skill');
  assert.equal(byId('method-square-extremum').kind,'method');
  for(const n of nodes.filter(n=>!['textbook','chapter','section','collection'].includes(n.kind))) {
    if (!['planned','knowledge_only'].includes(n.status)) assert.ok(n.examples.length);
    else assert.deepEqual(n.examples,[]);
    assert.ok(n.summary.length>10);
  }
});

test('validation rejects dangling references, wrong roles, invalid rule subtypes and knowledge cycles',()=>{
  for(const [mutate,pattern] of [
    [ns=>{delete ns.find(n=>n.id==='amgm-formula').source;},/amgm-formula: 缺少 source/],
    [ns=>ns.find(n=>n.kind==='chapter').members.push({ref:'amgm-formula',relation:'contains'}),/类型不符/],
    [ns=>ns.find(n=>n.kind==='skill').basis.push('amgm-formula#missing'),/失效条目/],
    [ns=>ns.find(n=>n.kind==='skill').basis.push('nonexistent'),/失效引用/],
    [ns=>ns.find(n=>n.kind==='judgment_rule').branches[0].target='amgm-formula',/类型不符/],
    [ns=>ns.find(n=>n.id==='amgm-formula').prerequisites.push('amgm-formula'),/有环/],
    [ns=>ns.find(n=>n.id==='rule-interval-skill').subtype='method_selection',/步骤选择规则|类型不符/],
    [ns=>ns.find(n=>n.kind==='judgment_rule').knowledge=['amgm-formula'],/不可维护/],
    [ns=>{ns.find(n=>n.id==='amgm-formula').pitfalls[0].title='$x<0$ 时';},/标题不能含公式/],
    [ns=>{ns.find(n=>n.id==='amgm-formula').entries[0].body[0]='$x\ne0$';},/控制字符/],
  ]){const copy=clone();mutate(copy);assert.throws(()=>validateGraph(copy,manifest),pattern);}
});

test('confirmed teaching chains and repeated calls derive from the ordered source',()=>{
  const edge=(from,to,type)=>edges.find(e=>e.from===from&&e.to===to&&e.type===type);
  assert.ok(edge('type-expression-comparison','method-difference-comparison','candidate'));
  assert.equal(byId('method-difference-comparison').steps[0].calls,undefined);
  assert.ok(edge('type-quantified-quadratic','rule-quadratic-method','method_rule'));
  assert.equal(edges.filter(e=>e.from==='rule-quadratic-method'&&e.type==='selects').length,4);
  assert.ok(edge('method-interval-extremum','rule-interval-skill','step_rule'));
  assert.equal(edges.filter(e=>e.from==='rule-interval-skill'&&e.type==='selects').length,3);
  assert.ok(edge('method-amgm-parameter','method-amgm-direct','calls'));
  const repeated=edge('method-amgm-parameter','skill-quantified-range','calls');
  assert.deepEqual(repeated.occurrences.map(o=>o.step),['quantifier','parameter']);
  assert.ok(inheritedKnowledge('method-amgm-parameter',nodes,edges).includes('amgm-formula#formula'));
  assert.ok(!edges.some(e=>e.from==='amgm-formula'&&e.to==='reciprocal-sum-function'&&e.type==='prerequisite'));
});

test('scope is based on curriculum membership; expanding does not change membership',()=>{
  const state=readState('',graph),local=scopeMembers(graph,state.scope);
  assert.equal(state.scope,'section-2-1');assert.ok(!local.has('amgm-formula'));
  const projection=projectGraph(graph,{...state,view:'solution',expanded:['method-amgm-parameter']});
  assert.equal(projection.nodes.find(n=>n.id==='method-amgm-direct').related,true);
  assert.ok(!scopeMembers(graph,state.scope).has('method-amgm-direct'));
  const all=projectGraph(graph,{...state,scope:'section-2-3',view:'solution'});
  assert.ok(all.nodes.some(n=>n.id==='rule-interval-skill'));
  assert.ok(all.nodes.some(n=>n.id==='rule-quadratic-method'));
  assert.ok(all.edges.every(e=>e.type!=='uses'));
  const knowledge=projectGraph(graph,{...state,scope:'section-2-3',view:'knowledge'});
  assert.ok(knowledge.edges.some(e=>e.from==='type-quantified-quadratic'&&e.type==='involves'));
});

test('URL state round-trips and rejects unsafe returns or unknown state',()=>{
  const state={scope:'section-2-2',view:'solution',q:'配方',node:'method-complete-square',kinds:['skill'],relations:['calls'],expanded:['method-amgm-direct']};
  assert.deepEqual(readState(writeState(state).split('?')[1],graph),state);
  assert.equal(readState('?scope=missing&view=bogus&node=missing',graph).node,'');
  assert.equal(safeGraphReturn('https://evil.test/knowledge/'),'/knowledge/');
  assert.equal(safeGraphReturn('//evil.test/knowledge/'),'/knowledge/');
  assert.equal(safeGraphReturn('/knowledge/?view=solution'),'/knowledge/?view=solution');
  assert.equal(safeGraphReturn('/knowledge/chapters/compulsory-1-ch3/?scope=section-3-2'),'/knowledge/chapters/compulsory-1-ch3/?scope=section-3-2');
  assert.equal(safeGraphReturn('/knowledge/chapters/../x/'),'/knowledge/');
  assert.equal(searchNodes(nodes,'倒勾函数')[0].id,'reciprocal-sum-function');
  const ch3={scopes:['section-3-2','chapter-functions'],defaultScope:'section-3-2'};
  assert.equal(readState('?scope=section-2-1',graph,ch3).scope,'section-3-2');
  assert.equal(readState('?scope=chapter-functions',graph,ch3).scope,'chapter-functions');
  assert.equal(writeState({...state,scope:'section-3-2'},'/knowledge/chapters/compulsory-1-ch3/').split('?')[0],'/knowledge/chapters/compulsory-1-ch3/');
});

test('view changes and restored URLs discard hidden filters while keeping compatible ones',()=>{
  const initial=readState('?scope=section-2-3&view=knowledge&kinds=knowledge&relations=uses',graph);
  const solution=normalizeViewFilters({...initial,view:'solution'});
  assert.deepEqual(solution.kinds,[]);assert.deepEqual(solution.relations,[]);
  assert.ok(projectGraph(graph,solution).nodes.length>0,'切换视图后不能被隐藏的知识点筛选清空');
  const mixed=normalizeViewFilters({...initial,view:'solution',kinds:['knowledge','skill'],relations:['uses','calls']});
  assert.deepEqual(mixed.kinds,['skill']);assert.deepEqual(mixed.relations,['calls']);
  assert.ok(projectGraph(graph,mixed).nodes.every(n=>n.kind==='skill'));
  const restored=readState('?scope=section-2-3&view=solution&kinds=knowledge&relations=uses',graph);
  assert.deepEqual(restored,solution);
  assert.equal(writeState(restored).includes('kinds='),false);
  const back=normalizeViewFilters({...initial,view:'knowledge',kinds:['method'],relations:['calls']});
  assert.ok(projectGraph(graph,back).nodes.length>0);
});

test('fit contains every node on mobile and desktop, including an open desktop drawer',()=>{
  for(const scope of ['section-2-3','chapter-quadratic-equations-inequalities'])for(const view of ['curriculum','knowledge','solution']){
    const state={...readState('',graph),scope,view};
    const projected=projectGraph(graph,state);
    const layout=layoutGraph(projected.nodes,projected.edges,{view,structure:view==='curriculum'?curriculumStructure(graph,scope):null});
    for(const [width,height] of [[333,520],[1207,560],[1207-378,560]]){
      const t=fitGraph(layout,width,height);
      assert.ok(Number.isFinite(t.k)&&t.k>0);
      for(const [id,p] of layout.positions){
        const left=t.x+p.x*t.k,top=t.y+p.y*t.k;
        assert.ok(left>=0&&top>=0&&left+p.w*t.k<=width&&top+p.h*t.k<=height,`${scope}/${view}: ${id} 超出 ${width}×${height} 画布`);
      }
    }
  }
});

test('chapter frames wrap or narrow to the arrangement that shows them largest',()=>{
  const scope='chapter-quadratic-equations-inequalities',state={...readState('',graph),scope,view:'curriculum'};
  const projected=projectGraph(graph,state),structure=curriculumStructure(graph,scope);
  const flat=layoutGraph(projected.nodes,projected.edges,{view:'curriculum',structure});
  for(const [width,height,rearranged] of [[2400,1400,false],[713,880,true],[333,520,true]]){
    const wrapped=layoutGraph(projected.nodes,projected.edges,{view:'curriculum',structure,canvas:{width,height}});
    assert.equal(wrapped.perRow<flat.frames.length||wrapped.cols<flat.cols,rearranged,`${width}×${height}`);
    assert.ok(fitGraph(wrapped,width,height).k>=fitGraph(flat,width,height).k);
    assert.equal(wrapped.positions.size,flat.positions.size);
    for(const [a,b] of wrapped.frames.flatMap((f,i)=>wrapped.frames.slice(i+1).map(g=>[f,g])))
      assert.ok(a.x+a.w<=b.x||b.x+b.w<=a.x||a.y+a.h<=b.y||b.y+b.h<=a.y,`${a.id} 与 ${b.id} 重叠`);
  }
});

test('punctuation sticks to the formula before it while long formulas still wrap',async()=>{
  const {textHtml}=await import('../lib/public-knowledge-html.mjs');
  assert.match(textHtml('令 $t=x-2$。然后'),/<span class="math-tail"><span class="katex">[\s\S]*<\/span>。<\/span>然后/);
  for(const [file,scope] of [['knowledge.css',''],['practice-preview.css','.kxp-sheet ']]){
    const css=await fs.readFile(path.join(repoRoot,'site/assets/knowledge-next',file),'utf8');
    assert.ok(css.includes(`${scope}.math-tail { white-space: nowrap; }`),file);
    // nowrap is inherited; KaTeX breaks between its inline boxes only under normal.
    assert.ok(css.includes(`${scope}.math-tail > .katex { white-space: normal; }`),file);
  }
});

test('on a phone the readable first view needs no sideways panning',()=>{
  for(const scope of ['chapter-quadratic-equations-inequalities','section-2-1','section-2-2','section-2-3']){
    const state={...readState('',graph),scope,view:'curriculum'},projected=projectGraph(graph,state),structure=curriculumStructure(graph,scope);
    const flat=layoutGraph(projected.nodes,projected.edges,{view:'curriculum',structure});
    const phone=layoutGraph(projected.nodes,projected.edges,{view:'curriculum',structure,canvas:{width:390,height:520,minScale:.68}});
    assert.ok(phone.width*Math.max(.68,fitGraph(phone,390,520).k)<=390,scope);
    assert.equal(phone.positions.size,flat.positions.size,scope);
    const desk=layoutGraph(projected.nodes,projected.edges,{view:'curriculum',structure,canvas:{width:1400,height:900,minScale:.8}});
    assert.ok(Math.max(.8,fitGraph(desk,1400,900).k)>=Math.max(.8,fitGraph(flat,1400,900).k)-1e-6,scope);
  }
});

test('layout accepts mixed graph cycles and keeps labels intact',()=>{
  const list=[{id:'a',kind:'method',label:'方法 A'},{id:'b',kind:'skill',label:'技能 B'},{id:'c',kind:'knowledge',label:'知识点 C'}];
  const l=layoutGraph(list,[{from:'a',to:'b'},{from:'b',to:'a'},{from:'b',to:'c'}]);
  assert.equal(l.positions.size,3);assert.ok(Number.isFinite(l.height));
  for(const n of nodes) assert.equal(wrapLabel(n.label).join(''),n.label);
});

test('views lay out as lanes or section frames; shared nodes appear once',()=>{
  const state=readState('',graph);
  const solution=projectGraph(graph,{...state,scope:'section-2-3',view:'solution'});
  const lanes=layoutGraph(solution.nodes,solution.edges,{view:'solution'}),x=id=>lanes.positions.get(id).x;
  assert.equal(lanes.positions.size,solution.nodes.length);
  assert.ok(x('type-quantified-quadratic')<x('rule-quadratic-method')&&x('rule-quadratic-method')<x('method-interval-extremum')&&x('method-interval-extremum')<x('rule-interval-skill')&&x('rule-interval-skill')<x('skill-simplify'));
  const structure=curriculumStructure(graph,'chapter-quadratic-equations-inequalities');
  assert.deepEqual(structure.crumbs,['textbook-pep-a-compulsory-1','chapter-quadratic-equations-inequalities']);
  assert.deepEqual(structure.sections.map(s=>s.id),['section-2-1','section-2-2','section-2-3']);
  const chapter=projectGraph(graph,{...state,scope:'chapter-quadratic-equations-inequalities',view:'curriculum'});
  const frames=layoutGraph(chapter.nodes,chapter.edges,{view:'curriculum',structure});
  assert.equal(frames.positions.size,63);assert.equal(frames.frames.length,3);
  assert.ok(frames.notes.flatMap(n=>n.items).some(i=>i.id==='square-nonnegative'));
});

test('3D tower: floors stack by kind, solo nodes stay in their section sector, shared nodes sit nearer the axis',()=>{
  const sub=chapterGraph(graph,homeChapters(sources.outline,graph),'compulsory-1-ch2');
  const t=towerLayout(sub),y=id=>t.positions.get(id).y;
  assert.equal(t.positions.size,59);
  assert.deepEqual(t.sectors.map(s=>s.id),['section-2-1','section-2-2','section-2-3']);
  assert.ok(y('square-nonnegative')<y('skill-simplify')&&y('skill-simplify')<y('method-interval-extremum')&&y('method-interval-extremum')<y('type-quantified-quadratic')&&y('type-quantified-quadratic')<y('section-2-3')&&y('section-2-3')<y('chapter-quadratic-equations-inequalities'));
  const inside=(a,s)=>{const d=Math.atan2(Math.sin(a-s.mid),Math.cos(a-s.mid));return Math.abs(d)<=(s.end-s.start)/2+1e-9;};
  for (const n of sub.nodes.filter(n=>!['textbook','chapter','section','collection'].includes(n.kind))) {
    const owners=t.sectionsOf(n.id),p=t.positions.get(n.id);
    assert.ok(owners.length,`${n.id} 没有所属节`);
    if(owners.length===1) assert.ok(inside(p.angle,t.sectors.find(s=>s.id===owners[0])),`${n.id} 越出所属扇区`);
    else assert.ok(p.radius<t.radius*0.7,`${n.id} 共用节点应靠近中轴`);
  }
  const ps=[...t.positions.values()];
  for(let i=0;i<ps.length;i++)for(let j=i+1;j<ps.length;j++)assert.ok(Math.hypot(ps[i].x-ps[j].x,ps[i].y-ps[j].y,ps[i].z-ps[j].z)>=60,'节点重叠');
});

test('rendered HTML is complete, pre-renders math and links every entry, step and branch',async()=>{
  const a=await generate(),b=await generate();assert.deepEqual(a.outputs,b.outputs);
  for(const n of nodes.filter(n=>!['textbook','chapter','section','collection'].includes(n.kind))){
    const html=a.outputs.get(`${n.id}/index.html`);assert.ok(html.includes(`<h1>${n.label}</h1>`));assert.ok(!/待补充|TODO/.test(html));
    for(const part of [...(n.entries||[]),...(n.operations||[]),...(n.steps||[]),...(n.branches||[])])assert.ok(html.includes(`id="${part.id}"`));
    assert.ok(!/api\/learning|learning-marks|drill\.js|\/assets\/explain\/explain\.js/.test(html));
  }
  assert.match(a.outputs.get('amgm-formula/index.html'),/class="katex"/);
  const square=a.outputs.get('square-nonnegative/index.html');
  assert.ok(square.includes('explain-square-nonnegative'));assert.ok(!square.includes('data-explain-open'));
  assert.match(square,/href="\/knowledge\/amgm-formula\//);
  const method=a.outputs.get('method-amgm-parameter/index.html');
  assert.ok(method.includes('id="quantifier"')&&method.includes('id="parameter"'));
  const rule=a.outputs.get('rule-quadratic-method/index.html');
  assert.match(rule,/data-graph-locate href="\/knowledge\/chapters\/compulsory-1-ch2\/\?scope=section-2-3&view=solution&node=rule-quadratic-method/);
  assert.match(a.outputs.get('chapters/compulsory-1-ch2/index.html'),/src="\/assets\/knowledge-next\/graph.mjs"/);
  const assets=new Set([...a.outputs.values(),...a.compatibility.values()].flatMap(body=>[...body.matchAll(/\/assets\/knowledge-next\/[\w.-]+\.(?:mjs|css)/g)].map(m=>m[0])));
  assert.ok(assets.size>5);
  for (const asset of assets) assert.ok((await fs.stat(path.join(repoRoot,'site',asset))).isFile(),asset);
  assert.ok(![...a.outputs.keys()].some(name=>name.startsWith('assets/')));
});

test('detail pages: position chain, two-sided relations, compact method path, method choice, organisation redirects',async()=>{
  const {outputs}=await generate();
  const amgm=outputs.get('amgm-formula/index.html');
  assert.match(amgm,/<p class="appears"><span>出现在<\/span><a href="\/knowledge\/chapters\/compulsory-1-ch2\/\?scope=section-2-2">/);
  const hero=amgm.match(/<section class="hero detail-hero".*?<\/section>/s)[0];
  assert.match(hero,/<div class="region" data-kind="knowledge"><p class="region-label">前置知识 <span class="count">1<\/span>.*平方的非负性.*<div class="region" data-kind="skill"><p class="region-label">应用它的技能 <span class="count">2<\/span>.*<div class="region" data-kind="problem_type"><p class="region-label">考查它的题型 <span class="count">2<\/span>/s);
  assert.ok(!amgm.includes('id="relationships"')&&!amgm.includes('href="#relationships"'));
  const entry=amgm.match(/<article class="entry" id="formula">.*?<\/article>/s)[0];
  assert.match(entry,/<p class="entry-users" data-kind="skill"><span>用到这一条的技能<\/span>.*应用基本不等式/s);
  assert.match(amgm,/<article class="entry" id="formula">.*?<\/article><section class="resource-section is-placed" id="resource-amgm-semicircle"><h3>/s);
  assert.match(amgm,/<li><a href="#formula">公式与取等<\/a><\/li><li><a href="#resource-amgm-semicircle">/);
  assert.match(amgm,/class="ag-slider"/);assert.ok(!amgm.includes('class="ag-tabs"'));
  const traps=amgm.match(/<section id="pitfalls">.*?<\/section>/s)[0];
  assert.equal(traps.match(/class="pitfall"/g).length,4);
  assert.match(traps,/id="pitfall-fixed".*错误做法.*正确做法.*href="\/knowledge\/method-matching\/"/s);
  const homogeneous=outputs.get('method-homogeneous/index.html');
  assert.match(homogeneous,/<li id="fill">.*?<section class="resource-section is-placed" id="resource-homogeneous-degree">.*?<\/section><\/li>/s);
  assert.ok(homogeneous.includes('class="method-figure"') && !homogeneous.includes('class="method-steps"') && !homogeneous.includes('第 10 题'));
  assert.match(outputs.get('method-separation/index.html'),/<li id="quantifier">.*?id="resource-separation-horizontal-line"/s);
  assert.match(homogeneous,/<li id="degree">.*?id="resource-homogeneous-degree-count".*?<\/li>/s);
  assert.ok(!homogeneous.includes('class="he-notes"'));
  assert.match(outputs.get('skill-apply-amgm/index.html'),/<li id="apply">.*?id="resource-apply-amgm-slots"/s);
  assert.match(outputs.get('method-interval-extremum/index.html'),/<li id="conditions">.*?id="resource-case-merge-union"/s);
  assert.match(outputs.get('skill-reciprocal-range/index.html'),/<li id="bounds">.*?id="resource-reciprocal-window-range".*?<li id="merge">.*?id="resource-reciprocal-split-range"/s);
  for (const [file, html] of outputs) if (/^type-[^/]+\/index\.html$/.test(file) && byId(file.split('/')[0]).status !== 'planned') {
    const node = byId(file.split('/')[0]);
    assert.match(html,/<section id="features"><h2>题型特征<\/h2>/,file);
    if (node.sample) assert.match(html,/<div class="feature-sample">/,file);
    if ((node.features || []).some((feature) => feature && typeof feature === 'object' && feature.example)) {
      assert.match(html,/class="cue-example"/,file);
    }
    if (node.confuse?.length) assert.match(html,/class="feature-confuse".*?class="node-chip"/s,file);
    else assert.doesNotMatch(html,/class="feature-confuse"/,file);
  }
  const sumProductRange = outputs.get('method-sum-product-range/index.html');
  assert.match(sumProductRange,/<li id="choose">.*?id="resource-symmetric-swap-check".*?<li id="sum-product">/s);
  assert.ok(!sumProductRange.includes('class="sp-table"'));
  assert.match(outputs.get('skill-quadratic-sign/index.html'),/<li id="signs">.*?id="resource-quadratic-sign-chart".*?<li id="zeros">/s);
  assert.match(outputs.get('function-range-extrema/index.html'),/id="attainability".*?id="resource-attainability-boundary".*?id="quantified".*?id="resource-quantified-horizontal-line"/s);
  assert.match(outputs.get('function-monotonicity/index.html'),/id="pitfall-open-interval".*?相关<\/span><a class="node-chip"[^>]*href="\/knowledge\/function-range-extrema\/#attainability"><i aria-hidden="true"><\/i>函数的值域与最值 · /s);
  assert.ok(!amgm.includes('data-drill-open'));
  assert.match(amgm,/"drill":false/);
  assert.ok(!outputs.get('type-sum-product-extremum/index.html').includes('data-drill-open'));
  assert.equal(outputs.get('equality-properties/index.html').match(/<div class="region" data-kind="skill">.*?<\/div><\/div>/s)[0].match(/class="node-chip"/g).length,11);
  assert.match(outputs.get('square-nonnegative/index.html'),/前置知识<\/p><span class="region-empty">无，可以直接学习<\/span>/);
  assert.match(outputs.get('method-amgm-direct/index.html'),/data-kind="skill"><p class="region-label">用到的技能/);
  assert.ok(!amgm.includes('<table')&&!amgm.includes('node-identity')&&!amgm.includes('← 返回图谱'));
  const skill=outputs.get('method-matching/index.html');
  assert.match(skill,/href="\/knowledge\/method-amgm-direct\/#prepare"/);
  const method=outputs.get('method-amgm-direct/index.html');
  assert.match(method,/<div class="step-calls"><p class="rel-label">看题目情况选用<\/p>/);
  assert.match(method,/<div class="step-calls is-inline"><p class="rel-label">这一步用到<\/p>/);
  const quantified=outputs.get('type-quantified-quadratic/index.html');
  assert.match(quantified,/<section id="choose">.*rule-quadratic-method.*class="branch-list".*method-discriminant/s);
  assert.match(quantified,/<small>必修一·1章<\/small>/);
  assert.equal(outputs.get('type-sum-product-extremum/index.html').match(/class="choose-method"/g).length,4);
  assert.equal(outputs.get('type-sum-product-extremum/index.html').match(/class="choose-when"><strong>适合什么题：/g).length,4);
  assert.match(outputs.get('section-2-2/index.html'), /"redirectHref":"\/knowledge\/chapters\/compulsory-1-ch2\/\?scope=section-2-2"/);
  assert.match(outputs.get('section-2-2/index.html'), /<noscript><meta http-equiv="refresh" content="0;url=\/knowledge\/chapters\/compulsory-1-ch2\/\?scope=section-2-2"><\/noscript>/);
  assert.match(outputs.get('section-2-2/index.html'), /src="\/assets\/knowledge-next\/learning.mjs"/);
  assert.match(outputs.get('chapter-functions/index.html'), /"redirectHref":"\/knowledge\/chapters\/compulsory-1-ch3\/"/);
  assert.match(outputs.get('textbook-pep-a-compulsory-1/index.html'), /"redirectHref":"\/knowledge\/"/);
  for(const [file,html] of outputs)if(file.endsWith('.html'))assert.ok(!/href="\/knowledge\/(section-|chapter-|textbook-)/.test(html),file);
});

test('2D pages: whole-curriculum overview, one graph page per recorded chapter, external nodes marked',async()=>{
  const {outputs}=await generate();
  assert.deepEqual([...outputs.keys()].filter(k=>k.startsWith('chapters/')).sort(),['chapters/compulsory-1-ch1/index.html','chapters/compulsory-1-ch2/index.html','chapters/compulsory-1-ch3/index.html']);
  const overview=outputs.get('index.html');
  assert.equal(overview.match(/class="chapter-card /g).length,19);
  const wide=overview.match(/<svg class="map-svg is-wide"[\s\S]*?<\/svg>/)[0],narrow=overview.match(/<svg class="map-svg is-narrow"[\s\S]*?<\/svg>/)[0];
  for(const map of [wide,narrow]){assert.equal(map.match(/class="map-chapter /g).length,18);assert.equal(map.match(/class="map-link is-relation"/g).length,JSON.parse(outputs.get('city.json')).links.filter(l=>l.type==='relation'&&!l.from.includes('junior')&&!l.to.includes('junior')).length);}
  assert.ok(wide.includes('is-outline')&&!narrow.includes('is-outline'),'手机版关系图只画跨章知识关联');
  assert.match(overview,/id="chapter-compulsory-1-ch3"[\s\S]*?<span>先修<\/span>/);
  assert.match(overview,/href="\/knowledge\/chapters\/compulsory-1-ch2\/\?scope=section-2-3"/);
  assert.match(overview,/overview\.mjs/);
  const ch2=outputs.get('chapters/compulsory-1-ch2/index.html'),config=JSON.parse(ch2.match(/<script id="graph-config" type="application\/json">(.*?)<\/script>/)[1]);
  assert.deepEqual(config,{chapter:'compulsory-1-ch2',node:'chapter-quadratic-equations-inequalities',base:'/knowledge/chapters/compulsory-1-ch2/',defaultScope:'section-2-1',scopes:['section-2-1','section-2-2','section-2-3','chapter-quadratic-equations-inequalities']});
  assert.ok(!ch2.includes('data-scope="section-3-2"'));
  assert.match(ch2,/<details class="fallback-directory" open>/);
  const sections=[...ch2.matchAll(/<section id="dir-(section-[\d-]+)" class="dir-section"><h2><b>[\d.]+<\/b> [^<]+<span class="count">(\d+)<\/span>/g)];
  assert.deepEqual(sections.map(m=>m[1]),['section-2-1','section-2-2','section-2-3']);
  assert.equal(sections.reduce((s,m)=>s+Number(m[2]),0),(ch2.match(/data-directory-node=/g)||[]).length);
  assert.equal(new Set(ch2.match(/data-directory-node="[^"]+"/g)).size,(ch2.match(/data-directory-node=/g)||[]).length);
  const ch3=outputs.get('chapters/compulsory-1-ch3/index.html');
  assert.match(ch3,/data-scope="section-3-2"/);assert.match(ch3,/其余 2 节建设中/);
  const json=JSON.parse(outputs.get('graph.json')),home=new Map(json.nodes.map(n=>[n.id,n.home]));
  assert.equal(home.get('quantifiers'),'compulsory-1-ch1');assert.equal(home.get('textbook-pep-a-compulsory-1'),undefined);
  assert.equal(json.chapters.length,18);assert.deepEqual(json.chapters.filter(c=>c.recorded).map(c=>c.id),['compulsory-1-ch1','compulsory-1-ch2','compulsory-1-ch3']);
  const homed={...graph,nodes:json.nodes},state=readState('',homed);
  const borrowed=projectGraph(homed,{...state,scope:'section-2-3',view:'knowledge'},'compulsory-1-ch2');
  assert.equal(borrowed.nodes.find(n=>n.id==='quantifiers').external,'compulsory-1-ch1');
  assert.equal(borrowed.nodes.find(n=>n.id==='type-quantified-quadratic').external,'');
  const reached=projectGraph(homed,{...state,scope:'section-3-2',view:'knowledge'},'compulsory-1-ch3');
  const visitor=reached.nodes.find(n=>n.id==='type-quantified-quadratic');
  assert.ok(visitor&&visitor.external==='compulsory-1-ch2'&&!visitor.related,'第二章的题型应作为外章节点出现在第三章的知识关系视图');
  assert.ok(reached.edges.some(e=>e.from==='type-quantified-quadratic'&&e.to==='function-range-extrema'));
  assert.ok(!projectGraph(homed,{...state,scope:'section-3-2',view:'curriculum'},'compulsory-1-ch3').nodes.some(n=>n.id==='type-quantified-quadratic'));
  const detail=outputs.get('quantifiers/index.html');
  assert.ok(!detail.includes('id="cross-chapter"'));
  assert.match(detail.match(/<section class="hero detail-hero".*?<\/section>/s)[0],/<small>必修一·2章<\/small>/,'别章节点在上方关系行里带章标');
  assert.match(detail,/<a data-graph-return href="\/knowledge\/chapters\/compulsory-1-ch1\/\?scope=section-1-5/);
});

test('knowledge city: whole-curriculum outline, chapter 2 built, towers inside their districts without overlap',async()=>{
  const {outline}=sources,city=buildCity(outline,graph),plan=cityLayout(city);
  assert.equal(city.chapters.length,18);assert.equal(city.books.length,5);
  const built=city.chapters.filter(c=>c.built);
  assert.deepEqual(built.map(c=>c.id),['compulsory-1-ch2']);
  assert.deepEqual(city.chapters.filter(c=>c.partial).map(c=>c.id),['compulsory-1-ch1','compulsory-1-ch3']);
  assert.deepEqual(built[0].counts,{knowledge:10,skill:20,method:14,problem_type:9,judgment_rule:2});
  assert.deepEqual(built[0].sections.map(s=>s.node),['section-2-1','section-2-2','section-2-3']);
  const homes=homeChapters(outline,graph);
  assert.equal(homes.get('quantifiers'),'compulsory-1-ch1');
  assert.equal(homes.get('function-range-extrema'),'compulsory-1-ch3');
  assert.equal(homes.get('skill-quantified-range'),'compulsory-1-ch2');
  assert.equal(homes.get('rule-quadratic-method'),'compulsory-1-ch2');
  const sub=chapterGraph(graph,homes,'compulsory-1-ch2');
  assert.ok(!sub.nodes.some(n=>n.kind==='textbook'||n.id==='quantifiers'));
  assert.deepEqual(city.links.filter(l=>l.type==='relation').map(l=>[l.from,l.to,l.count]),[['compulsory-1-ch3','junior-knowledge',11],['compulsory-1-ch2','compulsory-1-ch3',16],['compulsory-1-ch1','compulsory-1-ch2',5],['compulsory-1-ch1','compulsory-1-ch3',9]]);
  const crossing=graph.edges.filter(e=>!['contains','extends'].includes(e.type)&&homes.get(e.from)!==homes.get(e.to));
  assert.ok(crossing.some(e=>e.from==='type-quantified-quadratic'&&e.to==='quantifiers'));
  const ch3=city.chapters.find(c=>c.id==='compulsory-1-ch3'),r=towerRadius(ch3);
  const scaffold=scaffoldLayout(ch3,chapterGraph(graph,homes,ch3.id),r,{sectionY:420,y:{knowledge:-270}});
  assert.deepEqual(scaffold.sectors.map(s=>s.id),['section-3-1','section-3-2']);
  for(const id of ['function-monotonicity','function-range-extrema']){
    const p=scaffold.positions.get(id),s=scaffold.sectors.find(s=>s.id==='section-3-2');
    assert.ok(p.radius<r&&p.angle>=s.start&&p.angle<=s.end&&p.y===-270,`${id} 应在 3.2 扇区的地基层`);
    assert.deepEqual(scaffold.sectionsOf(id),['section-3-2']);
  }
  const towers=[...plan.towers.entries()];assert.equal(towers.length,19);
  for(let i=0;i<towers.length;i++)for(let j=i+1;j<towers.length;j++){
    const [a,p]=towers[i],[b,q]=towers[j];
    assert.ok(Math.hypot(p.x-q.x,p.z-q.z)>p.radius+q.radius+60,`${a} 与 ${b} 重叠`);
  }
  for(const d of plan.districts)for(const [id,t] of towers.filter(([,t])=>t.strand===d.id)){
    const off=Math.abs(Math.atan2(Math.sin(t.angle-d.angle),Math.cos(t.angle-d.angle)));
    assert.ok(off<CITY.wedge&&t.distance>d.inner&&t.distance<d.outer,`${id} 不在 ${d.label} 街区内`);
  }
  for(const [,t] of towers.filter(([,t])=>t.lane==='plaza'))assert.ok(t.distance<CITY.start-t.radius);
  const json=JSON.parse((await generate()).outputs.get('city.json'));assert.equal(json.chapters.length,18);
});

test('knowledge city validation rejects bad outline references',()=>{
  const {outline}=sources;
  for(const [mutate,pattern] of [
    [o=>{o.chapters[1].book='nope';},/未知教材/],
    [o=>{o.chapters[1].strand='nope';},/未知主线/],
    [o=>{o.chapters.push(structuredClone(o.chapters[0]));},/重复的章/],
    [o=>{o.chapters.find(c=>c.node).node=undefined;},/章节点未登记/],
    [o=>{o.chapters.find(c=>c.id==='compulsory-1-ch2').sections[0].label='错名';},/节名与节点/],
    [o=>{o.prerequisites.push(['compulsory-1-ch2','missing']);},/章间先修无效/],
  ]){const o=structuredClone(outline);mutate(o);assert.throws(()=>buildCity(o,graph),pattern);}
});

test('resource adapter uses explicit mappings and fails unknown old links',()=>{
  const html='<button type="button" class="old" data-explain-open="old"></button>';
  const next=rewriteResourceLinks(html,{old:'function-range-extrema#attainability'},{'function-range-extrema':'函数的值域与最值'});
  assert.match(next,/href="\/knowledge\/function-range-extrema\/#attainability"/);
  assert.ok(!next.includes('data-explain-open'));
  assert.throws(()=>rewriteResourceLinks(html,{},{}),/未映射/);
});

test('--check catches missing and stale pages; cleanup is limited to inventoried outputs',async()=>{
  const root=await fs.mkdtemp(path.join(os.tmpdir(),'knowledge-next-test-'));
  try {
    await fs.mkdir(path.join(root,'site'));
    for(const part of ['data','assets','1','2','topics'])await fs.symlink(path.join(repoRoot,'site',part),path.join(root,'site',part),'dir');
    await fs.symlink(path.join(repoRoot,'server'),path.join(root,'server'),'dir');
    await fs.symlink(path.join(repoRoot,'tools'),path.join(root,'tools'),'dir');
    await fs.mkdir(path.join(root,'site/knowledge'));await fs.writeFile(path.join(root,'site/knowledge/handwritten.txt'),'untouched');
    await publish({root});assert.equal((await publish({root,check:true})).changed,0);
    const target=path.join(root,'site/knowledge/amgm-formula/index.html');
    await fs.unlink(target);await assert.rejects(publish({root,check:true}),/缺失或过期/);
    await assert.rejects(fs.stat(target),/ENOENT/);
    await publish({root});await fs.writeFile(target,'stale');await assert.rejects(publish({root,check:true}),/缺失或过期/);
    await fs.writeFile(path.join(root,'site/knowledge/removed.html'),'orphan');
    const manifestPath=path.join(root,'site/knowledge/manifest.json');
    const manifest=JSON.parse(await fs.readFile(manifestPath,'utf8'));
    manifest.files.push('removed.html');await fs.writeFile(manifestPath,JSON.stringify(manifest));
    await assert.rejects(publish({root,check:true}),/obsolete: knowledge\/removed.html/);await publish({root});
    assert.equal(await fs.readFile(path.join(root,'site/knowledge/handwritten.txt'),'utf8'),'untouched');
    await assert.rejects(fs.stat(path.join(root,'site/knowledge/removed.html')),/ENOENT/);
  }finally{await fs.rm(root,{recursive:true,force:true});}
});

test('cleanup removes only empty owned ancestors, including leftovers after first replacement', async () => {
  const root=await fs.mkdtemp(path.join(os.tmpdir(),'knowledge-empty-directories-'));
  try {
    await fs.mkdir(path.join(root,'site'));
    for(const part of ['data','assets','1','2','topics']) await fs.symlink(path.join(repoRoot,'site',part),path.join(root,'site',part),'dir');
    await fs.symlink(path.join(repoRoot,'server'),path.join(root,'server'),'dir');
    await fs.mkdir(path.join(root,'tools/data'),{recursive:true});
    const oldFiles={'retired/deep/node/index.html':'old node','retained/node/index.html':'old retained node','old-empty/child/index.html':'already removed'};
    await fs.writeFile(path.join(root,'tools/data/public-knowledge-legacy-files.json'),JSON.stringify({files:Object.fromEntries(Object.entries(oldFiles).map(([name,body])=>[name,createHash('sha256').update(body).digest('hex')]))}));
    for(const [name,body] of Object.entries(oldFiles)) {
      await fs.mkdir(path.dirname(path.join(root,'site/knowledge',name)),{recursive:true});
      if(!name.startsWith('old-empty/')) await fs.writeFile(path.join(root,'site/knowledge',name),body);
    }
    await fs.writeFile(path.join(root,'site/knowledge/retained/node/notes.txt'),'handwritten');
    await fs.mkdir(path.join(root,'site/knowledge/retired/handwritten-empty'),{recursive:true});
    await fs.mkdir(path.join(root,'site/knowledge/untouched-empty'),{recursive:true});
    await publish({root});
    await assert.rejects(fs.stat(path.join(root,'site/knowledge/retired/deep')),/ENOENT/);
    await assert.rejects(fs.stat(path.join(root,'site/knowledge/old-empty')),/ENOENT/);
    assert.equal(await fs.readFile(path.join(root,'site/knowledge/retained/node/notes.txt'),'utf8'),'handwritten');
    assert.ok((await fs.stat(path.join(root,'site/knowledge/retired/handwritten-empty'))).isDirectory());
    assert.ok((await fs.stat(path.join(root,'site/knowledge/untouched-empty'))).isDirectory());

    // A previous run may already have replaced the manifest but left empty
    // legacy paths and obsolete bundle directories behind.
    await fs.mkdir(path.join(root,'site/knowledge/old-empty/child'),{recursive:true});
    await fs.mkdir(path.join(root,'site/knowledge-next/assets/0123456789ab'),{recursive:true});
    await fs.mkdir(path.join(root,'site/knowledge-next/assets/handwritten-empty'),{recursive:true});
    await assert.rejects(publish({root,check:true}),/obsolete directory: knowledge\/old-empty\/child/);
    assert.ok((await fs.stat(path.join(root,'site/knowledge/old-empty/child'))).isDirectory());
    await publish({root});
    await assert.rejects(fs.stat(path.join(root,'site/knowledge/old-empty')),/ENOENT/);
    await assert.rejects(fs.stat(path.join(root,'site/knowledge-next/assets/0123456789ab')),/ENOENT/);
    assert.ok((await fs.stat(path.join(root,'site/knowledge-next/assets/handwritten-empty'))).isDirectory());
    assert.equal((await publish({root,check:true})).changed,0);
  } finally {
    await fs.rm(root,{recursive:true,force:true});
  }
});

for (const failure of ['modified deletion', 'modified replacement', 'unowned replacement', 'compatibility ownership']) {
  test(`first replacement validates ${failure} before writing; retry preserves the same guard`, async () => {
    const root = await fs.mkdtemp(path.join(os.tmpdir(), 'knowledge-first-replacement-'));
    const snapshot = async () => {
      const result = new Map();
      const visit = async directory => {
        for (const entry of await fs.readdir(path.join(root, 'site', directory), {withFileTypes: true})) {
          const name = path.posix.join(directory, entry.name);
          if (entry.isDirectory()) await visit(name);
          else result.set(name, createHash('sha256').update(await fs.readFile(path.join(root, 'site', name))).digest('hex'));
        }
      };
      for (const directory of ['knowledge', 'knowledge-next']) await visit(directory);
      return result;
    };
    try {
      await fs.mkdir(path.join(root, 'site'));
      for (const part of ['data', 'assets', '1', '2', 'topics']) await fs.symlink(path.join(repoRoot, 'site', part), path.join(root, 'site', part), 'dir');
      await fs.symlink(path.join(repoRoot, 'server'), path.join(root, 'server'), 'dir');
      await fs.mkdir(path.join(root, 'tools/data'), {recursive: true});
      await fs.mkdir(path.join(root, 'site/knowledge/nodes'), {recursive: true});
      await fs.mkdir(path.join(root, 'site/knowledge-next'));
      const oldFiles = {'index.html': 'old index', 'data.js': 'old data'};
      if (failure === 'modified replacement') oldFiles['nodes/index.html'] = 'old nodes';
      for (const [name, body] of Object.entries(oldFiles)) await fs.writeFile(path.join(root, 'site/knowledge', name), body);
      const inventory = Object.fromEntries(Object.entries(oldFiles).map(([name, body]) => [name, createHash('sha256').update(body).digest('hex')]));
      await fs.writeFile(path.join(root, 'tools/data/public-knowledge-legacy-files.json'), JSON.stringify({files: inventory}));
      await fs.writeFile(path.join(root, 'site/knowledge-next/index.html'), 'old preview');
      await fs.writeFile(path.join(root, 'site/knowledge-next/manifest.json'), JSON.stringify({
        generator: failure === 'compatibility ownership' ? 'another-generator' : 'tools/build-public-knowledge-graph.mjs',
        files: ['index.html', 'manifest.json'],
      }));
      let error;
      if (failure === 'modified deletion') {
        await fs.writeFile(path.join(root, 'site/knowledge/data.js'), 'user-modified data');
        error = /拒绝删除已修改的旧文件：knowledge\/data.js/;
      } else if (failure === 'modified replacement') {
        await fs.writeFile(path.join(root, 'site/knowledge/nodes/index.html'), 'user-modified nodes');
        error = /首次替换发现旧文件已被修改：knowledge\/nodes\/index.html/;
      } else if (failure === 'unowned replacement') {
        await fs.writeFile(path.join(root, 'site/knowledge/nodes/index.html'), 'handwritten nodes');
        error = /拒绝覆盖未登记文件：knowledge\/nodes\/index.html/;
      } else {
        error = /无法管理其他生成器的目录：knowledge-next/;
      }
      const before = await snapshot();
      for (let attempt = 0; attempt < 2; attempt++) {
        await assert.rejects(publish({root}), error);
        assert.deepEqual(await snapshot(), before, `attempt ${attempt + 1} changed files or manifests`);
        await assert.rejects(fs.stat(path.join(root, 'site/knowledge/manifest.json')), /ENOENT/);
      }
    } finally {
      await fs.rm(root, {recursive: true, force: true});
    }
  });
}
