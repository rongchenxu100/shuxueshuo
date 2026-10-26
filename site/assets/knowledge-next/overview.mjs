import {KINDS,groupPath,chapterTag,scopeMembers,searchNodes} from './model.mjs';
import {escapeHtml as h} from './resource-links.mjs';
import {bindSearchFocus} from './search-focus.mjs';
import {legacyGraphHref} from './compat.mjs';
import {isPreview, modeHref} from '../practice/learning-mode.mjs';

const $=selector=>document.querySelector(selector);
const input=$('#search'),results=$('#search-results');
const ORG=['textbook','chapter','section','collection'];
let graph,chapters,byId,open=false;

const loadGraph=async()=>{
  if(graph)return graph;
  const res=await fetch('/knowledge/graph.json',{cache:'no-cache'});if(!res.ok)throw new Error(String(res.status));
  graph=await res.json();byId=new Map(graph.nodes.map(n=>[n.id,n]));chapters=new Map([...graph.chapters,...(graph.collections||[])].map(c=>[c.id,c]));
  return graph;
};
function nodeHome(id){
  const n=byId.get(id),c=chapters.get(n?.home);if(!c)return '';
  const scope=ORG.includes(n.kind)?n.id:c.sections.find(s=>scopeMembers(graph,s.id).has(id))?.id||c.node;
  const view=ORG.includes(n.kind)?'curriculum':n.kind==='knowledge'?'knowledge':'solution';
  return `${groupPath(c)}?scope=${scope}&view=${view}&node=${id}&expand=${id}`;
}

// Links from before chapter pages existed (?scope=…&node=…) land on the chapter that owns them.
const legacy=new URLSearchParams(location.search);
if(legacy.has('scope')||legacy.has('node')||legacy.has('topic')||location.hash)loadGraph().then(async()=>{
  const response = await fetch('/knowledge/teaching/migration.json', {cache: 'no-cache'});
  if (!response.ok) return;
  const next = legacyGraphHref(graph, await response.json(), location.href);
  if (next) location.replace(next);
}).catch(()=>{});

function show(){
  const list=searchNodes(graph.nodes,input.value).slice(0,30);
  results.innerHTML=list.length?list.map(n=>{const c=chapters.get(n.home);return `<li><button type="button" data-go="${n.id}" data-kind="${n.kind}"><i aria-hidden="true"></i><span>${h(n.label)}</span><small>${KINDS[n.kind]}${c?` · ${h(chapterTag(c))}`:''}</small></button></li>`;}).join(''):'<li class="search-empty">没有找到匹配节点。</li>';
  results.hidden=!open||!input.value.trim();
  results.querySelectorAll('[data-go]').forEach(b=>b.addEventListener('click',()=>go(b.dataset.go)));
}
function go(id){const href=nodeHome(id);if(href)location.href=modeHref(href,{preview:isPreview(location.search)},location.href);}
input.addEventListener('input',async()=>{open=true;try{await loadGraph();show();}catch{results.innerHTML='<li class="search-empty">图谱数据加载失败，请稍后重试。</li>';results.hidden=false;}});
input.addEventListener('focus',()=>{open=true;loadGraph().then(show).catch(()=>{});});
bindSearchFocus(input,results,()=>{open=false;results.hidden=true;});
input.addEventListener('keydown',e=>{
  if(e.key==='Enter'&&graph){const first=searchNodes(graph.nodes,input.value)[0];if(first){e.preventDefault();go(first.id);}}
});

function focusChapter(map,id){
  map.classList.toggle('has-focus',Boolean(id));
  map.querySelectorAll('.map-link').forEach(l=>l.classList.toggle('lit',l.dataset.a===id||l.dataset.b===id));
  map.querySelectorAll('.map-chapter').forEach(c=>{
    const linked=id&&(c.dataset.mapChapter===id||map.querySelector(`.map-link[data-a="${id}"][data-b="${c.dataset.mapChapter}"],.map-link[data-b="${id}"][data-a="${c.dataset.mapChapter}"]`));
    c.classList.toggle('lit',Boolean(linked));
  });
}
document.querySelectorAll('.map-svg').forEach(map=>map.querySelectorAll('.map-chapter').forEach(c=>{
  c.addEventListener('pointerenter',e=>{if(e.pointerType==='mouse')focusChapter(map,c.dataset.mapChapter);});
  c.addEventListener('focus',()=>focusChapter(map,c.dataset.mapChapter));
  c.addEventListener('pointerleave',()=>focusChapter(map,''));
  c.addEventListener('blur',()=>focusChapter(map,''));
}));
