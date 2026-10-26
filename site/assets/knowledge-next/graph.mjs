import {isPreview, modeHref} from '../practice/learning-mode.mjs';
import {KINDS,RELATIONS,VIEWS,VIEW_KINDS,VIEW_RELATIONS,nodeHref,detailLabel,chapterPath,groupPath,chapterTag,lifecycleLabel,readState,writeState,projectGraph,scopeMembers,searchNodes,curriculumStructure,normalizeViewFilters} from './model.mjs';
import {layoutGraph,fitGraph} from './layout.mjs';
import {escapeHtml as h} from './resource-links.mjs';
import {bindSearchFocus} from './search-focus.mjs';
import {renderLearningMath} from './learning-model.mjs';

const $=selector=>document.querySelector(selector);
const svg=$('#graph'),viewport=$('#viewport'),status=$('#graph-status'),drawer=$('#drawer'),selection=$('#selection'),results=$('#search-results');
const NS='http://www.w3.org/2000/svg',ORG=['textbook','chapter','section','collection'];
const FAMILY={contains:'org',extends:'org',prerequisite:'know',uses:'know',involves:'know',candidate:'solve',calls:'solve',method_rule:'rule',step_rule:'rule',selects:'rule'};
const RULES={method_selection:'选法规则',step_selection:'步骤选择规则'};
const reduced=matchMedia('(prefers-reduced-motion: reduce)'),narrow=matchMedia('(max-width: 760px)');
const config=JSON.parse($('#graph-config').textContent),scopeOptions={scopes:config.scopes,defaultScope:config.defaultScope};
let graph,byId,chapters,inChapter,state,projection,layout,transform={x:0,y:0,k:1},loading=false,hoverId='',camera=0,pathTimer=0,searchOpen=false,drag,autoView=true;

function el(tag,attrs={},text){const item=document.createElementNS(NS,tag);for(const [k,v]of Object.entries(attrs))item.setAttribute(k,v);if(text!==undefined)item.textContent=text;return item;}
const kindText=n=>`${KINDS[n.kind]}${lifecycleLabel(n) ? ` · ${lifecycleLabel(n)}` : ''}${n.subtype?` · ${RULES[n.subtype]}`:''}`;
const shortTag=id=>{const c=chapters.get(id);return chapterTag(c);};
// Nodes another chapter owns and this chapter never references open on their own chapter page.
const elsewhere=id=>{const home=byId.get(id)?.home;return Boolean(home&&home!==config.chapter&&!inChapter.has(id));};
function homeHref(id){
  const n=byId.get(id),c=chapters.get(n.home),scope=c.sections.find(s=>scopeMembers(graph,s.id).has(id))?.id||c.node;
  const view=n.kind==='knowledge'?'knowledge':ORG.includes(n.kind)?'curriculum':'solution';
  return modeHref(`${groupPath(c)}?scope=${scope}&view=${view}&node=${id}&expand=${id}${location.hash}`,{preview:isPreview(location.search)},location.href);
}
const nodeEl=id=>viewport.querySelector(`[data-node="${CSS.escape(id)}"]`);
const stepTargets=s=>[...(s.calls||[]),...(s.rule?[s.rule]:[])];

function applyTransform(){viewport.setAttribute('transform',`translate(${transform.x},${transform.y}) scale(${transform.k})`);}
function moveTo(next,animate=true){
  cancelAnimationFrame(camera);
  if(!animate||reduced.matches){transform=next;applyTransform();return;}
  const from={...transform},start=performance.now();
  const step=now=>{const t=Math.min(1,(now-start)/420),e=1-(1-t)**3;transform={x:from.x+(next.x-from.x)*e,y:from.y+(next.y-from.y)*e,k:from.k+(next.k-from.k)*e};applyTransform();if(t<1)camera=requestAnimationFrame(step);};
  camera=requestAnimationFrame(step);
}
const drawerInset=()=>!narrow.matches&&!drawer.hidden?drawer.offsetWidth+28:0;
const readableScale=()=>narrow.matches?.68:.8;
function fit(animate=true,{readable=false}={}){
  if(!layout)return;autoView=true;const box=svg.getBoundingClientRect(),w=box.width-drawerInset();
  const next=fitGraph(layout,w,box.height),minScale=readableScale();
  // Start with legible labels from the top-left; the explicit fit action always shows the whole graph.
  if(readable&&next.k<minScale){const k=minScale;next.k=k;next.x=Math.max(0,(w-layout.width*k)/2);next.y=Math.max(0,(box.height-layout.height*k)/2);}
  moveTo(next,animate);
}
function zoom(factor,point){if(!layout)return;autoView=false;const box=svg.getBoundingClientRect(),p=point||{x:box.width/2,y:box.height/2},minScale=Math.min(.2,fitGraph(layout,box.width-drawerInset(),box.height).k);const k=Math.max(minScale,Math.min(2.4,transform.k*factor)),ratio=k/transform.k;moveTo({k,x:p.x-(p.x-transform.x)*ratio,y:p.y-(p.y-transform.y)*ratio},false);}
function center(id,animate=true){const p=layout?.positions.get(id);if(!p)return;autoView=false;const box=svg.getBoundingClientRect(),k=Math.min(1.15,Math.max(.9,transform.k));moveTo({k,x:(box.width-drawerInset())/2-(p.x+p.w/2)*k,y:box.height/2-(p.y+p.h/2)*k},animate);}
function frameAll(ids){
  const ps=ids.map(id=>layout?.positions.get(id)).filter(Boolean);if(!ps.length)return false;
  const x0=Math.min(...ps.map(p=>p.x)),y0=Math.min(...ps.map(p=>p.y)),x1=Math.max(...ps.map(p=>p.x+p.w)),y1=Math.max(...ps.map(p=>p.y+p.h));
  const box=svg.getBoundingClientRect(),w=box.width-drawerInset(),k=Math.min(1.1,(w-120)/(x1-x0),(box.height-100)/(y1-y0));
  if(k<.5)return false;
  autoView=false;moveTo({k,x:(w-(x1-x0)*k)/2-x0*k,y:(box.height-(y1-y0)*k)/2-y0*k});return true;
}
function reveal(id){
  const p=layout?.positions.get(id);if(!p)return;const box=svg.getBoundingClientRect(),right=box.width-drawerInset()-16;
  const left=transform.x+p.x*transform.k,top=transform.y+p.y*transform.k;
  if(left<16||left+p.w*transform.k>right||top<16||top+p.h*transform.k>box.height-16)center(id);
}
function stateHref() {
  return modeHref(writeState(state,config.base)+location.hash,{preview:isPreview(location.search)},location.href);
}
function updateURL(replace=false) {
  const url=new URL(stateHref(),location.origin);
  const next=url.pathname+url.search+url.hash;
  if(location.pathname+location.search+location.hash!==next) {
    const previousScope=new URLSearchParams(location.search).get('scope');
    history[replace?'replaceState':'pushState']({},'',next);
    if(previousScope!==url.searchParams.get('scope')) window.dispatchEvent(new CustomEvent('knowledge-scope-change'));
  }
}
function detailHref(id){const u=new URL(nodeHref(id),location.origin);u.searchParams.set('graph',stateHref());return modeHref(u.href,{preview:isPreview(location.search)});}

// Frames already show membership, so the active node's other relations surface on demand.
function surfaced(active){
  if(layout.routing!=='frames')return [];
  const drawn=new Set([...viewport.querySelectorAll('.layer-edges [data-edge]')].map(g=>g.dataset.edge));
  return graph.edges.filter(e=>(e.from===active||e.to===active)&&e.from!==e.to&&!drawn.has(e.id)&&!layout.implicit.includes(e.type)&&layout.positions.has(e.from)&&layout.positions.has(e.to));
}
function paint(){
  const active=hoverId||state.node,on=!!active&&layout.positions.has(active),near=new Set(on?[active]:[]),extra=on?surfaced(active):[];
  viewport.querySelector('.layer-surfaced')?.replaceChildren(...extra.map(drawEdge));
  if(on)for(const e of [...projection.edges,...extra]){if(e.from===active)near.add(e.to);else if(e.to===active)near.add(e.from);}
  viewport.classList.toggle('has-focus',on);
  viewport.querySelectorAll('[data-node]').forEach(g=>{const id=g.dataset.node;g.classList.toggle('lit',near.has(id));g.classList.toggle('selected',id===state.node);g.setAttribute('aria-pressed',String(id===state.node));});
  viewport.querySelectorAll('[data-edge]').forEach(g=>g.classList.toggle('lit',on&&(g.dataset.from===active||g.dataset.to===active)));
  viewport.querySelectorAll('[data-frame]').forEach(f=>f.classList.toggle('lit',near.has(f.dataset.frame)));
}
function select(id,{navigate=true,focus=false}={}){
  if(id!==state.node)stopPath();
  state.node=id||'';if(navigate)updateURL();
  paint();showSelection();
  if(!state.node)return;
  if(focus)center(state.node);else if(!frameAll([...viewport.querySelectorAll('.graph-node.lit')].map(g=>g.dataset.node)))reveal(state.node);
  if(navigate&&narrow.matches)drawer.scrollIntoView({block:'nearest',behavior:reduced.matches?'auto':'smooth'});
}
function locate(id){
  if(elsewhere(id)){location.href=homeHref(id);return;}
  const n=byId.get(id);
  if(!scopeMembers(graph,state.scope).has(id)){const scope=config.scopes.find(s=>scopeMembers(graph,s).has(id));if(scope){state.scope=scope;state.expanded=[];}}
  state.node=id;state.expanded=[...new Set([...state.expanded,id])];state.kinds=[];state.relations=[];
  if(ORG.includes(n.kind))state.view='curriculum';
  else if(n.kind==='knowledge')state.view='knowledge';
  else if(state.view==='knowledge'&&n.kind!=='skill')state.view='solution';
  updateURL();draw();center(id);
}
function relationGroups(list,outgoing){
  const groups=new Map();for(const e of list){if(!groups.has(e.type))groups.set(e.type,[]);groups.get(e.type).push(e);}
  return [...groups].map(([type,items])=>`<li><span class="rel-type" data-family="${FAMILY[type]}">${h(RELATIONS[type])}</span><div class="rel-targets">${items.map(e=>{
    const other=byId.get(outgoing?e.to:e.from),notes=e.occurrences.map(o=>o.condition||o.when||'').filter(Boolean);
    return `<span class="rel-item${notes.length?' has-note':''}">${chip(other)}${notes.length?`<small>${h(notes.join('；'))}</small>`:''}</span>`;
  }).join('')}</div></li>`).join('');
}
const outsideTag=n=>n.home&&n.home!==config.chapter?`<small class="rel-home">${h(shortTag(n.home))}</small>`:'';
const chip=n=>`<button type="button" class="rel-node" data-kind="${n.kind}" data-select-related="${n.id}"><i aria-hidden="true"></i>${h(n.label)}${outsideTag(n)}</button>`;
function showSelection(){
  const n=byId.get(state.node);
  drawer.hidden=!n;if(!n){selection.replaceChildren();return;}
  const visible=layout.positions.has(n.id),out=graph.edges.filter(e=>e.from===n.id),inc=graph.edges.filter(e=>e.to===n.id);
  const home=n.home&&n.home!==config.chapter?chapters.get(n.home):null;
  const orgHref=n.kind==='textbook'?'/knowledge/':`${groupPath(chapters.get(n.home))}${n.kind==='section'?`?scope=${n.id}`:''}`;
  const primary=!ORG.includes(n.kind)?`<a class="drawer-primary" href="${detailHref(n.id)}">${detailLabel(n)} ↗</a>`
    :config.scopes.includes(n.id)?(n.id===state.scope?'':`<button type="button" id="enter-scope" class="drawer-primary">只看${n.kind==='collection'?'这个集合':n.kind==='chapter'?'全章':'这一节'}</button>`)
    :`<a class="drawer-primary" href="${orgHref}">${n.kind==='textbook'?'打开知识图谱总览':'打开所属图谱'} ↗</a>`;
  selection.innerHTML=`<p class="drawer-kind" data-kind="${n.kind}"><i aria-hidden="true"></i>${kindText(n)}${n.related?' · 展开内容':''}</p><h2>${h(n.label)}</h2>${ORG.includes(n.kind)?`<div data-progress-scope="${n.id}"></div>`:`<div data-learning-node="${n.id}" data-learning-full></div>`}<p class="drawer-summary" data-math-text>${h(n.summary)}</p>
${home?`<p class="drawer-home">归属 <b>${home.kind === 'collection' ? h(home.label) : `${h(chapterTag(home))} ${h(home.label)}`}</b>，与本章内容直接相关。<a href="${homeHref(n.id)}">打开所属图谱 →</a></p>`:''}
<div class="drawer-actions">${primary}${n.steps?.length?'<button type="button" id="play-path" class="drawer-play">▶ 演示解题路径</button>':''}</div>
${visible?'':`<p class="drawer-note">该节点不在当前视图或筛选范围内。<button type="button" data-select-related="${n.id}">在图中显示</button></p>`}
${n.steps?.length?`<section class="drawer-path"><h3>解题路径</h3><ol>${n.steps.map((s,i)=>`<li data-step="${i}"><span class="step-dot">${i+1}</span><div><b>${h(s.title)}</b>${stepTargets(s).map(id=>chip(byId.get(id))).join('')}</div></li>`).join('')}</ol></section>`:''}
${out.length?`<h3>它指向 <span>${out.length}</span></h3><ul class="rel-groups">${relationGroups(out,true)}</ul>`:''}
${inc.length?`<h3>指向它 <span>${inc.length}</span></h3><ul class="rel-groups">${relationGroups(inc,false)}</ul>`:''}
<button type="button" id="expand-related" class="drawer-expand">把直接关联全部展开到图上</button>`;
  $('#expand-related').addEventListener('click',()=>{state.expanded=[...new Set([...state.expanded,n.id])];state.kinds=[];state.relations=[];updateURL();draw();center(n.id);});
  $('#play-path')?.addEventListener('click',()=>playPath(n));
  $('#enter-scope')?.addEventListener('click',()=>{state.scope=n.id;state.expanded=[];state.node='';updateURL();draw();});
  selection.querySelectorAll('[data-select-related]').forEach(button=>button.addEventListener('click',()=>{const id=button.dataset.selectRelated;layout.positions.has(id)&&id!==n.id?select(id,{focus:true}):locate(id);}));
  renderLearningMath(selection).catch(()=>{});
}

function stopPath(){
  clearTimeout(pathTimer);pathTimer=0;viewport.classList.remove('is-playing','path-done');
  viewport.querySelectorAll('.path-on').forEach(x=>x.classList.remove('path-on','path-current'));
  selection.querySelectorAll('.drawer-path li').forEach(li=>li.classList.remove('is-current','is-done'));
}
// Lights the method's ordered calls one step at a time, mirroring the detail page path.
function playPath(n){
  if(state.view!=='solution'||n.steps.some(s=>stepTargets(s).some(id=>!layout.positions.has(id)))){
    state.view='solution';state.kinds=[];state.relations=[];state.expanded=[...new Set([...state.expanded,n.id])];updateURL();draw();
  }
  stopPath();if(!frameAll([n.id,...n.steps.flatMap(stepTargets)]))center(n.id);
  viewport.classList.add('is-playing');nodeEl(n.id)?.classList.add('path-on');
  const items=[...selection.querySelectorAll('.drawer-path li')];let i=0;
  const tick=()=>{
    viewport.querySelectorAll('.path-current').forEach(x=>x.classList.remove('path-current'));
    items.forEach((li,k)=>{li.classList.toggle('is-current',k===i);li.classList.toggle('is-done',k<i);});
    if(i>=n.steps.length){viewport.classList.add('path-done');pathTimer=0;return;}
    for(const id of stepTargets(n.steps[i])){
      nodeEl(id)?.classList.add('path-on','path-current');
      viewport.querySelectorAll(`[data-edge][data-from="${CSS.escape(n.id)}"][data-to="${CSS.escape(id)}"]`).forEach(e=>e.classList.add('path-on','path-current'));
    }
    i++;pathTimer=setTimeout(tick,reduced.matches?700:1300);
  };
  tick();
}

function syncControls(){
  document.querySelectorAll('[data-scope]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.scope===state.scope)));
  $('#search').value=state.q;
  document.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.view===state.view)));
  document.querySelectorAll('[name="kind"]').forEach(i=>{i.checked=state.kinds.includes(i.value);i.closest('label').hidden=!VIEW_KINDS[state.view].includes(i.value)||(state.view==='curriculum'&&ORG.includes(i.value));});
  document.querySelectorAll('[name="relation"]').forEach(i=>{i.checked=state.relations.includes(i.value);i.closest('label').hidden=!VIEW_RELATIONS[state.view].includes(i.value);});
  $('#filters-active').hidden=!state.kinds.length&&!state.relations.length;
  $('.kx-canvas-foot [data-reset-filters]').hidden=!state.kinds.length&&!state.relations.length&&!state.q;
}
function linkDirectory(){
  document.querySelectorAll('.fallback-directory [data-directory-node]').forEach(li=>{
    if(li.querySelector('.dir-locate'))return;
    const button=document.createElement('button');button.type='button';button.className='dir-locate';button.textContent='在图中定位';
    button.addEventListener('click',()=>{locate(li.dataset.directoryNode);svg.scrollIntoView({block:'center',behavior:reduced.matches?'auto':'smooth'});});
    li.append(button);
  });
}
function showSearch(){
  const list=searchNodes(graph.nodes,state.q);
  results.innerHTML=list.length?list.map(n=>`<li><button type="button" data-search-node="${n.id}" data-kind="${n.kind}"><i aria-hidden="true"></i><span>${h(n.label)}</span><small>${kindText(n)}${n.home&&n.home!==config.chapter?` · ${h(shortTag(n.home))}`:''}</small></button></li>`).join(''):'<li class="search-empty">没有找到匹配节点。</li>';
  results.hidden=!searchOpen||!state.q.trim();
  results.querySelectorAll('[data-search-node]').forEach(b=>b.addEventListener('click',()=>{searchOpen=false;results.hidden=true;locate(b.dataset.searchNode);}));
  const matches=new Set(list.map(n=>n.id));viewport.querySelectorAll('[data-node]').forEach(g=>g.classList.toggle('search-match',matches.has(g.dataset.node)));
}

function route(a,b,routing){
  const cubic=(x1,y1,c1x,c1y,c2x,c2y,x2,y2)=>({d:`M${x1},${y1} C${c1x},${c1y} ${c2x},${c2y} ${x2},${y2}`,mid:{x:(x1+3*c1x+3*c2x+x2)/8,y:(y1+3*c1y+3*c2y+y2)/8}});
  if(b.x>=a.x+a.w){const x1=a.x+a.w,y1=a.y+a.h/2,x2=b.x-2,y2=b.y+b.h/2,dx=Math.max(36,(x2-x1)/2);return cubic(x1,y1,x1+dx,y1,x2-dx,y2,x2,y2);}
  if(b.x+b.w<=a.x){const x1=a.x,y1=a.y+a.h/2,x2=b.x+b.w+2,y2=b.y+b.h/2,dx=Math.max(36,(x1-x2)/2);return cubic(x1,y1,x1-dx,y1,x2+dx,y2,x2,y2);}
  if(routing==='frames'){
    const down=b.y>a.y,x1=a.x+a.w/2,y1=down?a.y+a.h:a.y,x2=b.x+b.w/2,y2=down?b.y-2:b.y+b.h+2,dy=Math.max(30,Math.abs(y2-y1)/2)*(down?1:-1);
    return cubic(x1,y1,x1,y1+dy,x2,y2-dy,x2,y2);
  }
  const x1=a.x+a.w,y1=a.y+a.h/2,x2=b.x+b.w+2,y2=b.y+b.h/2,side=Math.max(x1,x2)+30+Math.min(90,Math.abs(y2-y1)*.25);
  return cubic(x1,y1,side,y1,side,y2,x2,y2);
}
function icon(kind,cy){
  const g=el('g',{class:'node-icon',transform:`translate(18,${cy})`});
  const shape={knowledge:()=>el('circle',{r:5.5}),skill:()=>el('rect',{x:-5,y:-5,width:10,height:10,rx:2.5}),method:()=>el('path',{d:'M0-7L7 0L0 7L-7 0Z'}),problem_type:()=>el('path',{d:'M0-6.5L6.5 5H-6.5Z'}),judgment_rule:()=>el('path',{d:'M0 7V1L-5.5-5M0 1L5.5-5',class:'stroke-icon'})}[kind];
  g.append(el('circle',{r:11,class:'icon-halo'}),shape?shape():el('path',{d:'M-6-5H6V5H-6ZM-2-5V5',class:'stroke-icon'}));
  return g;
}
function drawNode(n,i){
  const p=layout.positions.get(n.id),tag=n.external?shortTag(n.external):p.tag||(n.related?'展开':'');
  const g=el('g',{'data-node':n.id,'data-kind':n.kind,transform:`translate(${p.x},${p.y})`,class:`graph-node${n.related?' related':''}${p.tag?' extends':''}${n.external?' external':''}${ORG.includes(n.kind)?' org':''}`,role:'button',tabindex:'0','aria-label':`${kindText(n)}：${n.label}${tag?`，${tag}`:''}`,'aria-pressed':'false'});
  const body=el('g',{class:'node-body',style:`--i:${Math.min(i,40)}`});
  body.append(el('rect',{class:'node-box',width:p.w,height:p.h,rx:Math.min(14,p.h/2)}),icon(n.kind,p.h/2));
  const label=el('text',{x:36,y:p.h/2-(p.lines.length-1)*8.5+4.5,class:'node-label'});
  p.lines.forEach((line,k)=>label.append(el('tspan',{x:36,dy:k?17:0},line)));body.append(label);
  if(tag){const w=tag.length*11+14;body.append(el('rect',{class:'node-tag-bg',x:p.w-w-10,y:-8,width:w,height:16,rx:8}),el('text',{class:'node-tag',x:p.w-10-w/2,y:4,'text-anchor':'middle'},tag));}
  body.append(el('title',{},`${kindText(n)} · ${n.summary}`));
  if(!ORG.includes(n.kind)&&n.kind!=='judgment_rule')body.append(el('g',{'data-learning-node':n.id,transform:`translate(${p.w-6},${p.h-4})`,class:'kx-personal-svg'}));
  g.append(body);
  g.addEventListener('click',()=>select(n.id));
  g.addEventListener('pointerenter',e=>{if(e.pointerType==='mouse'){hoverId=n.id;paint();}});
  g.addEventListener('pointerleave',()=>{if(hoverId){hoverId='';paint();}});
  g.addEventListener('keydown',e=>{if(['Enter',' '].includes(e.key)){e.preventDefault();select(n.id,{focus:true});}});
  return g;
}
function drawEdge(e){
  const {d,mid}=route(layout.positions.get(e.from),layout.positions.get(e.to),layout.routing),family=FAMILY[e.type]||'org';
  const notes=e.occurrences.map(o=>o.condition||o.when||'').filter(Boolean).join('；');
  const g=el('g',{class:'edge','data-edge':e.id,'data-from':e.from,'data-to':e.to,'data-family':family});
  g.append(el('title',{},`${byId.get(e.from).label} → ${RELATIONS[e.type]} → ${byId.get(e.to).label}${notes?`：${notes}`:''}`),el('path',{class:'edge-line',d,'marker-end':`url(#arrow-${family})`}));
  const text=RELATIONS[e.type],w=text.length*11+16,label=el('g',{class:'edge-label',transform:`translate(${mid.x},${mid.y})`});
  label.append(el('rect',{x:-w/2,y:-10,width:w,height:20,rx:10}),el('text',{y:4,'text-anchor':'middle'},text));g.append(label);
  return g;
}
function drawJump(item){
  const g=el('g',{class:'jump-chip','data-jump':item.id,'data-kind':byId.get(item.id).kind,transform:`translate(${item.x},${item.y})`,role:'button',tabindex:'0','aria-label':`定位到${item.label}`});
  g.append(el('rect',{width:item.w,height:item.h,rx:item.h/2}),el('circle',{cx:12,cy:item.h/2,r:3}),el('text',{x:20,y:item.h/2+4},item.label));
  g.addEventListener('click',()=>select(item.id,{focus:true}));
  g.addEventListener('keydown',e=>{if(['Enter',' '].includes(e.key)){e.preventDefault();select(item.id,{focus:true});}});
  return g;
}

function arrange(){
  const box=svg.getBoundingClientRect();
  return layoutGraph(projection.nodes,projection.edges,{view:state.view,structure:state.view==='curriculum'?curriculumStructure(graph,state.scope):null,canvas:{width:box.width,height:box.height,minScale:readableScale()}});
}
function draw(){
  stopPath();syncControls();hoverId='';
  projection=projectGraph(graph,state,config.chapter);
  layout=arrange();
  const back=el('g',{class:'layer-back'}),edges=el('g',{class:'layer-edges'}),nodes=el('g',{class:'layer-nodes'}),implicit=new Set(layout.implicit);
  for(const b of layout.bands)if(b.label){const g=el('g',{class:'lane'});g.append(el('rect',{x:b.x,y:b.y,width:b.w,height:b.h,rx:24,class:'lane-band'}),el('text',{x:b.x+20,y:b.y+30,class:'lane-label'},b.label),el('text',{x:b.x+b.w-20,y:b.y+30,class:'lane-count','text-anchor':'end'},String(b.count)));back.append(g);}
  for(const f of layout.frames)back.append(el('rect',{x:f.x,y:f.y,width:f.w,height:f.h,rx:26,class:`frame${f.dashed?' dashed':''}`,'data-frame':f.id}));
  for(const t of layout.labels)back.append(el('text',{x:t.x,y:t.y,class:t.cls,...(t.kind?{'data-kind':t.kind}:{})},t.text));
  for(const note of layout.notes)note.items.forEach(item=>back.append(drawJump(item)));
  for(const e of projection.edges)if(!implicit.has(e.type)&&e.from!==e.to&&layout.positions.has(e.from)&&layout.positions.has(e.to))edges.append(drawEdge(e));
  projection.nodes.forEach((n,i)=>{if(layout.positions.has(n.id))nodes.append(drawNode(n,i));});
  viewport.replaceChildren(back,edges,el('g',{class:'layer-surfaced'}),nodes);
  const counts=projectGraph(graph,{...state,kinds:[]},config.chapter).nodes.reduce((m,n)=>m.set(n.kind,(m.get(n.kind)||0)+1),new Map());
  document.querySelectorAll('[data-kind-count]').forEach(s=>{const k=s.dataset.kindCount;s.textContent=counts.get(k)||0;if(!counts.get(k)&&!state.kinds.includes(k))s.closest('label').hidden=true;});
  const related=projection.nodes.filter(n=>n.related).length;
  status.textContent=`${VIEWS[state.view]} · ${projection.nodes.length} 个节点 · ${projection.edges.length} 条关系${related?` · 含 ${related} 个展开内容`:''}${!projection.nodes.length?'。当前筛选没有节点，可清除筛选。':''}`;
  showSearch();paint();showSelection();fit(false,{readable:true});
}

async function load(){
  if(loading)return;loading=true;$('#retry-graph').hidden=true;
  try{
    const res=await fetch('/knowledge/graph.json',{cache:'no-cache'});if(!res.ok)throw new Error(String(res.status));
    graph=await res.json();if(!Array.isArray(graph.nodes)||!Array.isArray(graph.edges))throw new Error('Invalid graph');
    byId=new Map(graph.nodes.map(n=>[n.id,n]));chapters=new Map([...graph.chapters,...(graph.collections||[])].map(c=>[c.id,c]));inChapter=scopeMembers(graph,config.node);
    state=readState(location.search,graph,scopeOptions);
    // A node arriving without a scope opens in the section that holds it.
    if(state.node&&!scopeMembers(graph,state.scope).has(state.node))state.scope=config.scopes.find(s=>scopeMembers(graph,s).has(state.node))||state.scope;
    updateURL(true);draw();linkDirectory();if(state.node)center(state.node,false);
  }catch(error){status.textContent='图谱数据加载失败。可使用下方全部节点目录继续阅读。';$('#retry-graph').hidden=false;$('.fallback-directory').open=true;}
  finally{loading=false;}
}
$('#retry-graph').addEventListener('click',load);
document.querySelectorAll('[data-scope]').forEach(b=>b.addEventListener('click',()=>{if(!state)return;state.scope=b.dataset.scope;state.expanded=[];state.node='';updateURL();draw();}));
document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>{if(!state)return;state=normalizeViewFilters({...state,view:b.dataset.view,relations:[]});updateURL();draw();if(state.node)reveal(state.node);}));
$('#search').addEventListener('input',event=>{if(!state)return;state.q=event.target.value;searchOpen=true;updateURL(true);showSearch();});
$('#search').addEventListener('focus',()=>{if(!state)return;searchOpen=true;showSearch();});
bindSearchFocus($('#search'),results,()=>{searchOpen=false;results.hidden=true;});
$('#search').addEventListener('keydown',event=>{
  if(!state)return;
  if(event.key==='Enter'){const first=searchNodes(graph.nodes,state.q)[0];if(first){event.preventDefault();searchOpen=false;results.hidden=true;locate(first.id);}}
});
document.querySelectorAll('[name="kind"],[name="relation"]').forEach(i=>i.addEventListener('change',()=>{if(!state)return;state.kinds=[...document.querySelectorAll('[name="kind"]:checked')].map(i=>i.value);state.relations=[...document.querySelectorAll('[name="relation"]:checked')].map(i=>i.value);updateURL();draw();}));
document.querySelectorAll('[data-reset-filters]').forEach(b=>b.addEventListener('click',()=>{if(!state)return;state.kinds=[];state.relations=[];state.q='';updateURL();draw();}));
$('#zoom-in').addEventListener('click',()=>zoom(1.25));$('#zoom-out').addEventListener('click',()=>zoom(.8));$('#fit').addEventListener('click',()=>fit());
$('#drawer-close').addEventListener('click',()=>select(''));
svg.addEventListener('wheel',event=>{if(!layout)return;event.preventDefault();const box=svg.getBoundingClientRect();zoom(Math.exp(-event.deltaY*.0012),{x:event.clientX-box.left,y:event.clientY-box.top});},{passive:false});
svg.addEventListener('pointerdown',e=>{if(e.target.closest('[data-node],[data-jump]'))return;cancelAnimationFrame(camera);drag={id:e.pointerId,x:e.clientX,y:e.clientY,startX:transform.x,startY:transform.y,moved:false};svg.setPointerCapture(e.pointerId);svg.classList.add('is-dragging');});
svg.addEventListener('pointermove',e=>{if(drag?.id!==e.pointerId)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(Math.abs(dx)+Math.abs(dy)>4){drag.moved=true;autoView=false;}transform.x=drag.startX+dx;transform.y=drag.startY+dy;applyTransform();});
const endDrag=clear=>{if(clear&&drag&&!drag.moved&&state?.node)select('');drag=null;svg.classList.remove('is-dragging');};
svg.addEventListener('pointerup',()=>endDrag(true));svg.addEventListener('pointercancel',()=>endDrag(false));
svg.addEventListener('keydown',e=>{if(e.target!==svg)return;const delta={ArrowLeft:[40,0],ArrowRight:[-40,0],ArrowUp:[0,40],ArrowDown:[0,-40]}[e.key];if(delta){e.preventDefault();autoView=false;transform.x+=delta[0];transform.y+=delta[1];applyTransform();}else if(e.key==='+')zoom(1.25);else if(e.key==='-')zoom(.8);else if(e.key==='0')fit();});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&state?.node&&!e.target.closest?.('input'))select('');});
window.addEventListener('popstate',()=>{if(!graph)return;state=readState(location.search,graph,scopeOptions);draw();if(state.node)center(state.node,false);});
let resizeTimer,lastWidth=0;new ResizeObserver(([entry])=>{const w=Math.round(entry.contentRect.width),first=!lastWidth;if(w===lastWidth)return;lastWidth=w;if(first)return;clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{
  if(!layout)return;
  // Re-flow only when the frame arrangement changes; a view the reader has moved stays put.
  const next=layout.perRow?arrange():null;
  if(next&&(next.perRow!==layout.perRow||next.cols!==layout.cols)){draw();if(state.node)reveal(state.node);}
  else if(autoView)fit(false,{readable:true});
  else if(state.node)reveal(state.node);
},100);}).observe(svg);
load();
