(function (global) {
  "use strict";
  const esc = value => String(value == null ? "" : value).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  function find(tree, id) {
    if (!tree) return null;
    if (tree.id === id) return tree;
    for (const child of tree.children || []) { const result = find(child, id); if (result) return result; }
    return null;
  }
  function mathTree(node, marks) {
    if (!node) return "";
    const children = node.children || [];
    const child = i => mathTree(children[i], marks);
    let content;
    switch (node.op) {
      case "integer": case "symbol": content = esc(node.text); break;
      case "add": content = child(0) + '<span class="er-op">+</span>' + (children[1].op === "add" ? '('+child(1)+')' : child(1)); break;
      case "sub": content = child(0) + '<span class="er-op">−</span>(' + child(1) + ')'; break;
      case "mul": content = children.map((c) => ['add','sub'].includes(c.op) ? '('+mathTree(c,marks)+')' : mathTree(c,marks)).join('<span class="er-mul">·</span>'); break;
      case "div": content = '<span class="er-fraction"><span>'+child(0)+'</span><span>'+child(1)+'</span></span>'; break;
      case "pow": content = '('+child(0)+')<sup>'+child(1)+'</sup>'; break;
      case "neg": case "pos": content = (node.op === 'neg' ? '−' : '+')+'('+child(0)+')'; break;
      default: throw new Error("Unsupported expression tree operation");
    }
    const mark = (marks || []).find(m => m.nodeId === node.id);
    return '<span class="er-node'+(mark ? ' er-highlight er-'+esc(mark.role) : '')+'" data-node-id="'+esc(node.id)+'">'+content+'</span>';
  }
  function formula(value, renderFormula, marks) {
    return value.tree ? mathTree(value.tree, marks) : renderFormula('\\('+value.latex+'\\)');
  }
  function local(t, side, renderFormula) {
    const value = side === 'before' ? t.localBefore : t.localAfter;
    const whole = side === 'before' ? t.before : t.after;
    const marks = (t.highlights || []).filter(m => m.side === side);
    if (value.nodeIds && value.nodeIds.length) return value.nodeIds.map(id=>mathTree(find(whole.tree,id),marks)).join('<span class="er-op">+</span>');
    return formula(whole,renderFormula,marks);
  }
  function render(spec, renderFormula) {
    const cards = ids => spec.conditionCards.filter(c => !ids || ids.includes(c.id)).map(c=>'<span class="er-condition">'+renderFormula('\\('+c.latex+'\\)')+'</span>').join('');
    let frames = '';
    spec.beats.forEach((beat,index)=>{
      const t=spec.transitions.find(t=>t.id===beat.transitionId);
      let body='';
      if(beat.kind==='focus') body='<p>观察要整理的部分及已知条件</p><div class="er-formula">'+formula(t.before,renderFormula,[...(t.highlights||[]).filter(m=>m.side==='before'),...t.unchanged.map(u=>({nodeId:u.beforeNodeId,role:'unchanged'}))])+'</div>';
      else if(beat.kind==='transform') {
        body='<div class="er-formula er-transform">'+local(t,'before',renderFormula)+'<span class="er-arrow">→</span>'+local(t,'after',renderFormula)+'</div>';
        if(t.effect==='reveal_condition') body+='<p>通分后的分母出现条件量</p>'+cards(t.conditionCardIds);
        else if(t.operation==='substitute_condition') body+='<p>使用已知条件</p>'+cards(t.conditionCardIds)+(t.replacements||[]).map(r=>'<div class="er-formula">'+renderFormula('\\('+r.block.latex+'\\)')+'<span class="er-arrow">→</span>'+renderFormula('\\('+r.value.latex+'\\)')+'</div>').join('');
        if(t.unchanged.length) body+='<p class="er-unchanged">保持不变：'+t.unchanged.map(x=>renderFormula('\\('+x.latex+'\\)')).join('，')+'</p>';
      } else body='<p>整理后的完整目标式</p><div class="er-formula">'+formula(spec.result,renderFormula)+'</div>';
      const shown = beat.kind==='focus' ? [] : beat.kind==='result' ? spec.transitions : spec.transitions.slice(0,spec.transitions.indexOf(t)+1);
      body+='<div class="er-chain"><small>完整推导</small><div class="er-formula">'+formula(spec.source,renderFormula)+'</div>'+shown.map(s=>'<div class="er-formula"><span class="er-equals">=</span>'+formula(s.after,renderFormula)+'</div>').join('')+'</div>';
      frames+='<section class="er-frame" data-frame="'+index+'"'+(index ? ' hidden':'')+'><h4>'+esc(beat.title)+'</h4>'+body+'</section>';
    });
    return '<figure class="lesson-step-visual expression-rewrite" data-beat="0" data-count="'+spec.beats.length+'" aria-label="'+esc(spec.title)+'"><header><strong>'+esc(spec.title)+'</strong><span>仅演示整理步骤</span></header><div class="er-conditions">'+cards()+'</div><div class="er-frames" aria-live="polite">'+frames+'</div><nav aria-label="推导播放"><button type="button" data-er="prev" disabled>上一步</button><span class="er-progress">1 / '+spec.beats.length+'</span><button type="button" data-er="next">下一步</button><button type="button" data-er="replay">重播</button><button type="button" data-er="all">查看全部</button></nav></figure>';
  }
  function move(figure, action) {
    const count=Number(figure.dataset.count);
    let index=Number(figure.dataset.beat);
    index=action==='replay'?0:action==='next'?Math.min(count-1,index+1):action==='prev'?Math.max(0,index-1):index;
    const all=action==='all';
    figure.dataset.beat=String(index);
    figure.querySelectorAll('[data-frame]').forEach(frame=>{frame.hidden=!all && Number(frame.dataset.frame)!==index;});
    figure.querySelector('.er-progress').textContent=all?'全部步骤':(index+1)+' / '+count;
    figure.querySelector('[data-er="prev"]').disabled=!all && index===0;
    figure.querySelector('[data-er="next"]').disabled=!all && index===count-1;
  }
  if (global.document) global.document.addEventListener('click',event=>{
    const button=event.target.closest('[data-er]');
    if(button) move(button.closest('.expression-rewrite'),button.dataset.er);
  });
  global.ExpressionRewrite={render,move};
})(typeof window === 'undefined' ? globalThis : window);
