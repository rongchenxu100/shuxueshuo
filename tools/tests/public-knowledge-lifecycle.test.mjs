import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';
import {loadSources, generate} from '../build-public-knowledge-graph.mjs';
import {validateGraph, scopeMembers, curriculumStructure, projectGraph, readState, safeGraphReturn} from '../../site/assets/knowledge-next/model.mjs';
import {buildCity, homeChapters, chapterGraph, cityLayout} from '../../site/assets/knowledge-next/city.mjs';
import {towerLayout} from '../../site/assets/knowledge-next/tower.mjs';
const {nodes,manifest,outline}=await loadSources();
const edges=validateGraph(nodes,manifest),graph={nodes,edges,defaultScope:manifest.defaultScope};
const planned=nodes.filter(n=>n.status==='planned');

test('only explicit planned types and knowledge-only nodes may omit examples or method entry',()=>{
  assert.equal(planned.length,4);
  const check=(id,change,pattern)=>{const copy=structuredClone(nodes);change(copy.find(n=>n.id===id));assert.throws(()=>validateGraph(copy,manifest),pattern);};
  const id=planned[0].id, knowledge=nodes.find(n=>n.status==='knowledge_only').id;
  check(id,n=>delete n.status,/缺少 examples|题型缺少方法入口/);
  check(id,n=>n.status='active',/缺少 examples|题型缺少方法入口/);
  check(id,n=>n.methods=['method-discriminant'],/待建设题型的 methods/);
  check(id,n=>n.rules=['rule-quadratic-method'],/待建设题型的 rules/);
  check(id,n=>n.features=[],/缺少 features/);
  check(id,n=>n.knowledge=[],/缺少 knowledge/);
  check(id,n=>n.status='knowledge_only',/knowledge_only 仅用于知识点/);
  check(knowledge,n=>n.status='planned',/planned 仅用于待建设题型/);
  check(knowledge,n=>n.entries=[],/缺少 entries/);
  check(knowledge,n=>n.status='active',/缺少 examples/);
  check('method-discriminant',n=>n.status='knowledge_only',/knowledge_only 仅用于知识点/);
  assert.ok(planned.every(n=>!edges.some(e=>e.from===n.id&&['candidate','method_rule'].includes(e.type))));
});

test('entry references validate existing knowledge anchors without creating global prerequisite edges',()=>{
  const owner=nodes.find(n=>n.entries?.some(e=>e.references?.length)), entry=owner.entries.find(e=>e.references?.length);
  assert.ok(owner && entry);
  const copy=structuredClone(nodes);copy.find(n=>n.id===owner.id).entries.find(e=>e.id===entry.id).references=['function-concept#missing'];
  assert.throws(()=>validateGraph(copy,manifest),/失效条目/);
  const before=edges.filter(e=>e.type==='prerequisite');
  const stripped=structuredClone(nodes);for(const n of stripped)for(const e of n.entries||[])delete e.references;
  assert.deepEqual(validateGraph(stripped,manifest).filter(e=>e.type==='prerequisite'),before);
});

test('junior collection owns the same members in flat projection, three-dimensional placement and metadata',()=>{
  const id='junior-knowledge', members=['integer-power','rational-expression','square-root-expression','absolute-value-concept','reciprocal-function'];
  const city=buildCity(outline,graph), homes=homeChapters(outline,graph), collection=city.collections.find(c=>c.id===id);
  assert.equal(collection.kind,'collection');assert.deepEqual(collection.sections,[]);
  assert.deepEqual(new Set(collection.members),new Set(members));
  assert.ok(!city.chapters.some(c=>c.id===id));
  const state=readState('?scope='+id,graph);assert.equal(state.scope,id);
  const projected=projectGraph(graph,state,id), structure=curriculumStructure(graph,id);
  assert.deepEqual(new Set(projected.nodes.map(n=>n.id)),new Set([id,...members]));
  assert.deepEqual(structure.sections[0].members.map(n=>n.id).sort(),members.slice().sort());
  const sub=chapterGraph(graph,homes,id),layout=towerLayout(sub);
  for(const member of [id,...members]){assert.equal(homes.get(member),id);assert.ok(layout.positions.has(member));}
  assert.ok(cityLayout(city).towers.has(id));
  assert.ok(scopeMembers(graph,'section-3-1').has('reciprocal-function'));
  assert.ok(edges.some(e=>e.from==='absolute-value-concept'&&e.type==='prerequisite'&&e.to==='absolute-value-function'));
  assert.equal(safeGraphReturn('/knowledge/collections/junior-knowledge/?scope=junior-knowledge'),'/knowledge/collections/junior-knowledge/?scope=junior-knowledge');
});

test('published views expose the collection and planned labels without fake exercise or solving links',async()=>{
  const {outputs}=await generate();
  const collection=outputs.get('collections/junior-knowledge/index.html');
  assert.ok(collection);assert.match(collection,/集合节点目录/);assert.doesNotMatch(collection,/第 undefined 章/);
  assert.doesNotMatch(collection,/初中知识 初中知识/);
  assert.match(outputs.get('index.html'),/id="collection-junior-knowledge"/);
  const directory=outputs.get('nodes/index.html');
  assert.match(directory,/<option value="junior-knowledge">初中知识<\/option>/);
  for(const id of ['junior-knowledge','integer-power','rational-expression','square-root-expression','absolute-value-concept','reciprocal-function'])assert.match(directory,new RegExp(`data-directory-node="${id}" data-home="junior-knowledge"`));
  const data=JSON.parse(outputs.get('graph.json'));
  assert.equal(data.collections[0].id,'junior-knowledge');
  for(const n of planned){
    assert.equal(data.nodes.find(x=>x.id===n.id).status,'planned');
    const html=outputs.get(n.id+'/index.html');assert.match(html,/题型建设中/);assert.doesNotMatch(html,/data-drill-open|打开原题/);
    assert.doesNotMatch(html, /<span>例中<\/span>undefined/, 'optional feature examples must not render an undefined placeholder');
  }
  const referenced=nodes.find(n=>n.entries?.some(e=>e.references?.length));
  assert.match(outputs.get(referenced.id+'/index.html'),/相关知识条目/);
});

test('all-node directory group filter retains collection members and can restore all nodes',async()=>{
  const callbacks={},filter={value:'',options:[{value:''},{value:'junior-knowledge'}],addEventListener:(event,callback)=>callbacks[event]=callback};
  const search={value:'',addEventListener:(event,callback)=>callbacks[event]=callback};
  const status={},counts={},links={};
  const sections=[['collection',['junior-knowledge']],['knowledge',['junior-knowledge','junior-knowledge','junior-knowledge','compulsory-1-ch3']]].map(([kind,homes])=>{
    const items=homes.map((home,index)=>({dataset:{home,search:index===1?'绝对值 数轴距离':'其他'},hidden:false}));counts[kind]={};links[kind]={querySelector:()=>({})};
    return {dataset:{directoryKind:kind},querySelectorAll:()=>items,querySelector:()=>counts[kind]};
  });
  let replaced='';
  const document={querySelector:selector=>selector==='#node-group-filter'?filter:selector==='#node-directory-search'?search:selector==='#node-directory-status'?status:links[selector.match(/data-kind="([^"]+)"/)?.[1]],querySelectorAll:()=>sections};
  vm.runInNewContext(await fs.readFile(new URL('../../site/assets/knowledge-next/directory.mjs',import.meta.url),'utf8'),{document,URL,location:{href:'https://site/knowledge/nodes/?group=junior-knowledge&preview=1'},history:{replaceState:(_a,_b,url)=>replaced=url}});
  assert.equal(status.textContent,'共 4 个节点');assert.equal(counts.knowledge.textContent,3);
  assert.equal(sections[1].querySelectorAll().at(-1).hidden,true);
  search.value='数轴距离';callbacks.input();assert.equal(status.textContent,'共 1 个节点');
  search.value='不存在';callbacks.input();assert.match(status.textContent,/没有找到匹配节点/);
  search.value='';
  filter.value='';callbacks.change();assert.equal(status.textContent,'共 5 个节点');assert.equal(replaced,'/knowledge/nodes/?preview=1');
});
