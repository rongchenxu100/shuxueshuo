import {mountResource} from './resource-runtime.mjs';
import {safeGraphReturn,VIEW_KINDS} from './model.mjs';
import {isPreview,modeHref} from '../practice/learning-mode.mjs';

const config=JSON.parse(document.querySelector('#node-page-config').textContent);
const params=new URLSearchParams(location.search);
// The current page owns its mode. A saved graph URL may still carry preview
// after the student has explicitly returned to the formal detail page.
const preview=isPreview(location.search);
const returnTo=modeHref(safeGraphReturn(params.get('graph')),{preview},location.href);
if(params.has('graph')) {
  document.querySelectorAll('[data-graph-return]').forEach(a=>a.href=returnTo);
  const locate=new URL(returnTo,location.origin);
  locate.searchParams.set('node',config.id);
  const view=locate.searchParams.get('view') || 'curriculum';
  if(!VIEW_KINDS[view]?.includes(config.kind)) {
    locate.searchParams.set('view',config.kind==='knowledge'?'knowledge':['textbook','chapter','section','collection'].includes(config.kind)?'curriculum':'solution');
    locate.searchParams.delete('relations');
  }
  const kinds=(locate.searchParams.get('kinds') || '').split(',').filter(Boolean);
  if(kinds.length && !kinds.includes(config.kind)) locate.searchParams.delete('kinds');
  const expanded=new Set((locate.searchParams.get('expand') || '').split(',').filter(Boolean));
  expanded.add(config.id);locate.searchParams.set('expand',[...expanded].join(','));
  document.querySelectorAll('[data-graph-locate]').forEach(a=>a.href=locate.pathname+locate.search+locate.hash);
  document.querySelectorAll('[data-node-link]').forEach(a=>{const u=new URL(a.href);u.searchParams.set('graph',returnTo);a.href=modeHref(u.href,{preview},location.href);});
}
if(matchMedia('(max-width: 760px)').matches) document.querySelector('.detail-toc details').open=false;

for (const resource of config.resources) {
  const root=document.querySelector(`[data-resource="${resource.id}"]`);
  const status=document.querySelector(`[data-resource-status="${resource.id}"]`), retry=document.querySelector(`[data-resource-retry="${resource.id}"]`);
  let busy=false, cleanup;
  async function mount(force=false) {
    if(busy) return;busy=true;retry.hidden=true;status.textContent='正在加载图解交互…';
    root.querySelectorAll('button,input').forEach(el=>el.disabled=true);
    try {
      cleanup?.();cleanup=await mountResource(root,resource,{node:config,retry:force});
      root.querySelectorAll('button,input').forEach(el=>el.disabled=false);
      status.textContent=root.querySelector('button,input,select') ? '图解已加载，可操作控件观察变化。' : '';
    } catch(error) {
      status.textContent='图解交互加载失败，正文、公式和普通链接仍可阅读。';retry.hidden=false;
    } finally {busy=false;}
  }
  retry.addEventListener('click',()=>mount(true));
  mount();
}
