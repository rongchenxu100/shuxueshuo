/* 3.2.1: all curves are concrete examples on explicitly stated intervals. */
import {escapeHtml as escape} from '../shared/html.js?v=1';

const math = text => `<span data-math-text>${escape(text)}</span>`;
const number = n => Math.abs(n) < 1e-8 ? '0' : String(Number(n.toFixed(2))).replace('-', '−');
const curve = (f, from, to, role = 'result') => ({f, from, to, role});

export const DEFINITION_CASES = {
  increasing: {label:'递增', formula:'$f(x)=x^2$，$x\\in[0,3]$', from:0, to:3, f:x=>x*x,
    conclusion:'在 $[0,3]$ 上，$x$ 越大，$f(x)$ 越大。'},
  decreasing: {label:'递减', formula:'$f(x)=9-x^2$，$x\\in[0,3]$', from:0, to:3, f:x=>9-x*x,
    conclusion:'在 $[0,3]$ 上，$x$ 越大，$f(x)$ 越小。'},
  turning: {label:'先减后增', formula:'$f(x)=x^2$，$x\\in[-2,2]$', from:-2, to:2, f:x=>x*x,
    conclusion:'在 $[-2,0]$ 上递减，在 $[0,2]$ 上递增；整个 $[-2,2]$ 上不单调。'},
};

export const OPERATION_CASES = {
  shift:{label:'加常数', formula:'$f(x)=x+2$，$h(x)=f(x)+2=x+4$', f:x=>x+2, h:x=>x+4,
    conclusion:'加 $2$ 后图像向上平移，大小次序不变，$h$ 仍递增。'},
  negative:{label:'乘负常数', formula:'$f(x)=x+2$，$h(x)=-2f(x)=-2x-4$', f:x=>x+2, h:x=>-2*x-4,
    conclusion:'乘负数 $-2$ 使大小次序颠倒，递增的 $f$ 变为递减的 $h$。'},
  reciprocal:{label:'取倒数', formula:'$f(x)=x+2$，$h(x)=\\frac1{f(x)}=\\frac1{x+2}$', f:x=>x+2, h:x=>1/(x+2),
    conclusion:'本区间内 $f(x)\\ge2>0$，可以使用同号取倒数的结论：$h$ 递减。'},
  root:{label:'开平方', formula:'$f(x)=x+2$，$h(x)=\\sqrt{f(x)}=\\sqrt{x+2}$', f:x=>x+2, h:x=>Math.sqrt(x+2),
    conclusion:'本区间内 $f(x)>0$，开平方保持大小次序，$h$ 递增。'},
  sum:{label:'两增相加', formula:'$f(x)=x+2$，$g(x)=2x+1$，$h(x)=f(x)+g(x)=3x+3$', f:x=>x+2, g:x=>2*x+1, h:x=>3*x+3,
    conclusion:'$f,g$ 在同一区间上都递增，它们的和 $h$ 也递增。'},
  difference:{label:'两增相减', formula:'$f(x)=x$，$g(x)=x^2$，$h(x)=f(x)-g(x)=x-x^2$', f:x=>x, g:x=>x*x, h:x=>x-x*x,
    conclusion:'$f,g$ 都递增，但本例的差 $h$ 先增后减。仅知道“两者都增”，不能确定差的单调性。'},
  positiveProduct:{label:'同正相乘', formula:'$f(x)=x+2$，$g(x)=2x+1$，$h(x)=f(x)g(x)$', f:x=>x+2, g:x=>2*x+1, h:x=>(x+2)*(2*x+1),
    conclusion:'$f,g$ 在 $[0,2]$ 上都为正且都递增，所以乘积 $h$ 递增。'},
  negativeProduct:{label:'同负相乘', formula:'$f(x)=x-3$，$g(x)=2x-5$，$h(x)=f(x)g(x)$', f:x=>x-3, g:x=>2*x-5, h:x=>(x-3)*(2*x-5),
    conclusion:'$f,g$ 在 $[0,2]$ 上都为负且都递增，乘积 $h$ 却递减；乘积不能只看增减而忽略正负。'},
};

export function compositionCase(innerIncreasing, outerIncreasing) {
  const g = innerIncreasing ? x=>x+1 : x=>3-x;
  const F = outerIncreasing ? u=>u*u : u=>-u*u;
  return {g,F,h:x=>F(g(x)), increasing:innerIncreasing===outerIncreasing,
    innerFormula:innerIncreasing?'$u=x+1$':'$u=3-x$',
    outerFormula:outerIncreasing?'$y=u^2$':'$y=-u^2$',
    resultFormula:`$y=${outerIncreasing?'':'-'}${innerIncreasing?'(x+1)':'(3-x)'}^2$`,
    innerTrend:innerIncreasing?'递增':'递减', outerTrend:outerIncreasing?'递增':'递减'};
}
export const COMPOSITION_CASES = {
  upUp:compositionCase(true,true), upDown:compositionCase(true,false),
  downUp:compositionCase(false,true), downDown:compositionCase(false,false),
};
const zigzag = x => x<=1 ? 2*x : x<=2 ? 3-x : 2*x-3;
export const EXTREMA_CASES = {
  increasing:{label:'闭区间递增', formula:'$f(x)=x+1$，$x\\in[0,2]$', f:x=>x+1, from:0, to:2, points:[0,2],
    conclusion:'最小值 $f(0)=1$，最大值 $f(2)=3$，分别在左、右端点取得。'},
  decreasing:{label:'闭区间递减', formula:'$f(x)=3-x$，$x\\in[0,2]$', f:x=>3-x, from:0, to:2, points:[0,2],
    conclusion:'最大值 $f(0)=3$，最小值 $f(2)=1$，分别在左、右端点取得。'},
  valley:{label:'先减后增', formula:'$f(x)=(x-1)^2$，$x\\in[0,3]$', f:x=>(x-1)**2, from:0, to:3, points:[0,1,3],
    conclusion:'最低点在 $x=1$，最小值为 $0$。两端 $f(0)=1$、$f(3)=4$，较大的 $4$ 是最大值。'},
  peak:{label:'先增后减', formula:'$f(x)=4-(x-1)^2$，$x\\in[0,3]$', f:x=>4-(x-1)**2, from:0, to:3, points:[0,1,3],
    conclusion:'最高点在 $x=1$，最大值为 $4$。两端 $f(0)=3$、$f(3)=0$，较小的 $0$ 是最小值。'},
  open:{label:'开区间的最值', formula:'$f(x)=(x-1)^2$，$x\\in(0,3)$', f:x=>(x-1)**2, from:0, to:3, points:[0,1,3], open:true,
    conclusion:'最小值 $0$ 在内部的 $x=1$ 处取得。$4$ 只能趋近、不能取到，所以没有最大值；值域为 $[0,4)$。'},
  converse:{label:'端点最值反例', formula:'$f(x)=\\begin{cases}2x,&0\\le x\\le1\\\\3-x,&1<x\\le2\\\\2x-3,&2<x\\le3\\end{cases}$', f:zigzag, from:0, to:3, points:[0,1,2,3],
    conclusion:'最小值 $f(0)=0$、最大值 $f(3)=3$ 都在端点取得，但 $[1,2]$ 上图像下降，所以整个 $[0,3]$ 上并不递增。'},
};

const samples = c => Array.from({length:121},(_,i)=>[c.from+(c.to-c.from)*i/120,c.f(c.from+(c.to-c.from)*i/120)]);
function ticks(min,max) {
  const raw=(max-min)/5, power=10**Math.floor(Math.log10(raw));
  const step=[1,2,5,10].map(n=>n*power).find(n=>n>=raw);
  const result=[];
  for(let n=Math.ceil(min/step)*step;n<=max+step/100;n+=step) result.push(n);
  return result;
}
export function plotGeometry(curves, compact=false) {
  const points=curves.flatMap(samples), xs=points.map(p=>p[0]), ys=points.map(p=>p[1]);
  const a=Math.min(0,...xs), b=Math.max(0,...xs), low=Math.min(0,...ys), high=Math.max(0,...ys);
  const dx=Math.max(b-a,1)*.15, dy=Math.max(high-low,1)*.16;
  const box={left:48,right:compact?300:416,top:22,bottom:compact?190:236,width:compact?320:440,height:compact?224:270};
  return {...box, xMin:a-dx,xMax:b+dx,yMin:low-dy,yMax:high+dy,
    sx:x=>box.left+(x-a+dx)/(b-a+2*dx)*(box.right-box.left),
    sy:y=>box.bottom-(y-low+dy)/(high-low+2*dy)*(box.bottom-box.top)};
}
function plot(curves,{label,points=[],compact=false,xLabel='x',yLabel='y'}={}) {
  const p=plotGeometry(curves,compact), x0=p.sx(0),y0=p.sy(0);
  const paths=curves.map(c=>`<path class="me-curve me-${c.role}" d="${samples(c).map(([x,y],i)=>`${i?'L':'M'}${p.sx(x).toFixed(2)} ${p.sy(y).toFixed(2)}`).join(' ')}"/>`).join('');
  const grid=ticks(p.xMin,p.xMax).map(x=>`<path d="M${p.sx(x)} ${p.top}V${p.bottom}" class="me-grid"/><text x="${p.sx(x)}" y="${p.bottom+20}" text-anchor="middle" class="me-tick">${number(x)}</text>`).join('')+
    ticks(p.yMin,p.yMax).map(y=>`<path d="M${p.left} ${p.sy(y)}H${p.right}" class="me-grid"/><text x="${p.left-9}" y="${p.sy(y)+4}" text-anchor="end" class="me-tick">${number(y)}</text>`).join('');
  const marks=points.map(({x,y,role='point',open=false,guide=true})=>`${guide?`<path d="M${p.sx(x)} ${y0}V${p.sy(y)}H${x0}" class="me-guide me-${role}"/>`:''}<circle cx="${p.sx(x)}" cy="${p.sy(y)}" r="5" class="me-dot me-${role}${open?' me-open':''}"/>`).join('');
  return `<svg class="me-plot" viewBox="0 0 ${p.width} ${p.height}" role="img" aria-label="${escape(label)}">${grid}
    <path d="M${p.left} ${y0}H${p.right}M${x0} ${p.bottom}V${p.top}" class="me-axis"/>
    <path d="M${p.right-5} ${y0-3}L${p.right} ${y0}L${p.right-5} ${y0+3}M${x0-3} ${p.top+5}L${x0} ${p.top}L${x0+3} ${p.top+5}" class="me-axis"/>
    <text x="${p.right+6}" y="${y0-8}" class="me-axis-label">${xLabel}</text><text x="${x0+10}" y="${p.top-4}" class="me-axis-label">${yLabel}</text>
    ${paths}${marks}</svg>`;
}
const buttons = cases => `<div class="me-cases" role="group" aria-label="选择观察情形">${Object.entries(cases).map(([key,c],i)=>`<button type="button" data-me-case="${key}" aria-pressed="${i===0}">${escape(c.label)}</button>`).join('')}</div>`;
const panel = (key,i,body) => `<section class="me-panel" data-me-panel="${key}"${i?' hidden':''}>${body}</section>`;
const conclusion = text => `<p class="me-conclusion">${math(text)}</p>`;
const controls = (label,attr,min,max,value) => `<label class="me-control"><span>${label}</span><input type="range" ${attr} min="${min}" max="${max}" step="0.1" value="${value}"></label>`;

export function definitionValues(c,x1,x2) {
  const y1=c.f(x1),y2=c.f(x2);
  return {y1,y2,quotient:(y2-y1)/(x2-x1), relation:Math.abs(y1-y2)<1e-8?'=':y1<y2?'<':'>'};
}
function definitionGraph(c,x1,x2) {
  return plot([curve(c.f,c.from,c.to)],{label:`两点比较：${c.label}示例`,points:[{x:x1,y:c.f(x1),role:'first'},{x:x2,y:c.f(x2),role:'second'}]});
}
function definitionReadout(c,x1,x2) {
  const {y1,y2,quotient,relation}=definitionValues(c,x1,x2);
  return `<span class="me-first">x₁ = ${number(x1)}，f(x₁) = ${number(y1)}</span><span class="me-second">x₂ = ${number(x2)}，f(x₂) = ${number(y2)}</span><span>x₁ &lt; x₂，f(x₁) ${escape(relation)} f(x₂)；这两点的差商约为 ${number(quotient)}。</span>`;
}
function definitionFigure() {
  return `<div class="me-explorer" data-me-kind="definition">${buttons(DEFINITION_CASES)}${Object.entries(DEFINITION_CASES).map(([key,c],i)=>{
    const x1=Number((c.from+(c.to-c.from)/4).toFixed(1)), x2=Number((c.from+3*(c.to-c.from)/4).toFixed(1));
    return panel(key,i,`<p class="me-formula">${math(c.formula)}</p><div data-me-graph>${definitionGraph(c,x1,x2)}</div><div class="me-controls">${controls('左点 x₁','data-me-first',c.from,x2-.1,x1)}${controls('右点 x₂','data-me-second',x1+.1,c.to,x2)}</div><p class="me-readout" data-me-readout aria-live="polite">${definitionReadout(c,x1,x2)}</p>${conclusion(c.conclusion)}`);
  }).join('')}</div>`;
}
function operationsFigure() {
  return `<div class="me-explorer" data-me-kind="operations">${buttons(OPERATION_CASES)}${Object.entries(OPERATION_CASES).map(([key,c],i)=>panel(key,i,
    `<p class="me-domain">所有函数都只在同一区间 ${math('$[0,2]$')} 上比较</p><p class="me-formula">${math(c.formula)}</p><div class="me-legend"><span class="me-base">灰实线：f</span>${c.g?'<span class="me-other">灰虚线：g</span>':''}<span class="me-result">彩线：运算后的 h</span></div>${plot([curve(c.f,0,2,'base'),...(c.g?[curve(c.g,0,2,'other')]:[]),curve(c.h,0,2)],{label:`${c.label}：运算前后的函数图像`})}${conclusion(c.conclusion)}`
  )).join('')}</div>`;
}
function compositionGraphs(c,x) {
  const u=c.g(x), y=c.F(u);
  const card=(title,formula,domain,graph)=>`<div class="me-flow-card"><h4>${title}</h4><p>${math(formula)}</p><p class="me-domain">${math(domain)}</p>${graph}</div>`;
  return card(`① 内层 · ${c.innerTrend}`,c.innerFormula,'$x\\in[0,2]$',plot([curve(c.g,0,2)],{label:'内层：x 变化时 u 的变化',points:[{x,y:u}],compact:true,yLabel:'u'}))+
    card(`② 外层 · ${c.outerTrend}`,c.outerFormula,'$u\\in[1,3]$',plot([curve(c.F,1,3)],{label:'外层：u 变化时 y 的变化',points:[{x:u,y}],compact:true,xLabel:'u'}))+
    card(`③ 复合 · ${c.increasing?'递增':'递减'}`,c.resultFormula,'$x\\in[0,2]$',plot([curve(c.h,0,2)],{label:'复合结果：x 变化时 y 的变化',points:[{x,y}],compact:true}));
}
function compositionFigure() {
  const cases=Object.fromEntries(Object.entries(COMPOSITION_CASES).map(([key,c])=>[key,{label:`内${c.innerTrend.slice(-1)} · 外${c.outerTrend.slice(-1)}`}])) ;
  return `<div class="me-explorer" data-me-kind="composition">${buttons(cases)}${Object.entries(COMPOSITION_CASES).map(([key,c],i)=>panel(key,i,
    `<div class="me-flow" data-me-flow>${compositionGraphs(c,1)}</div>${controls('移动输入 x','data-me-input',0,2,1)}<p class="me-readout" data-me-readout aria-live="polite">${compositionReadout(c,1)}</p>${conclusion(`内层${c.innerTrend}、外层${c.outerTrend}，所以复合函数在 $[0,2]$ 上${c.increasing?'递增':'递减'}。外层使用的区间始终是内层值域 $[1,3]$。`)}`
  )).join('')}</div>`;
}
function compositionReadout(c,x) {
  return `x = ${number(x)} → u = ${number(c.g(x))} → y = ${number(c.h(x))}`;
}
export function extremaPoints(c) {
  return c.points.map(x=>({x,y:c.f(x),open:Boolean(c.open&&(x===c.from||x===c.to))}));
}
function extremaFigure() {
  return `<div class="me-explorer" data-me-kind="extrema">${buttons(EXTREMA_CASES)}${Object.entries(EXTREMA_CASES).map(([key,c],i)=>panel(key,i,
    `<p class="me-formula">${math(c.formula)}</p>${plot([curve(c.f,c.from,c.to)],{label:`${c.label}：端点与转折点`,points:extremaPoints(c)})}<div class="me-values">${extremaPoints(c).map(p=>`<span>${p.open?'○ 边界（不取）':'● 图像上的点'}：(${number(p.x)}, ${number(p.y)})</span>`).join('')}</div>${conclusion(c.conclusion)}`
  )).join('')}</div>`;
}

export default {
  stylesheet:new URL('monotonicity-explorer.css',import.meta.url).href,
  definitionFigure,operationsFigure,compositionFigure,extremaFigure,
  render:definitionFigure,
  mount(root) {
    const explorer=root.querySelector('[data-me-kind]');
    if(!explorer) return;
    const cleanups=[];
    const on=(element,event,fn)=>{element.addEventListener(event,fn);cleanups.push(()=>element.removeEventListener(event,fn));};
    for(const button of explorer.querySelectorAll('[data-me-case]')) on(button,'click',()=>{
      for(const b of explorer.querySelectorAll('[data-me-case]')) b.setAttribute('aria-pressed',String(b===button));
      for(const p of explorer.querySelectorAll('[data-me-panel]')) p.hidden=p.dataset.mePanel!==button.dataset.meCase;
    });
    for(const p of explorer.querySelectorAll('[data-me-panel]')) {
      const key=p.dataset.mePanel;
      if(explorer.dataset.meKind==='definition') {
        const c=DEFINITION_CASES[key], first=p.querySelector('[data-me-first]'), second=p.querySelector('[data-me-second]');
        const draw=()=>{
          const x1=Number(first.value),x2=Number(second.value);
          first.max=String(Number((x2-.1).toFixed(1)));second.min=String(Number((x1+.1).toFixed(1)));
          p.querySelector('[data-me-graph]').innerHTML=definitionGraph(c,x1,x2);
          p.querySelector('[data-me-readout]').innerHTML=definitionReadout(c,x1,x2);
        };
        on(first,'input',draw);on(second,'input',draw);
      }
      if(explorer.dataset.meKind==='composition') {
        const c=COMPOSITION_CASES[key], input=p.querySelector('[data-me-input]');
        on(input,'input',()=>{
          const x=Number(input.value),graphs=p.querySelectorAll('.me-plot');
          // Keep the pre-rendered formula text intact; only the SVG points change.
          const holder=document.createElement('div');holder.innerHTML=compositionGraphs(c,x);
          holder.querySelectorAll('.me-plot').forEach((svg,i)=>graphs[i].replaceWith(svg));
          p.querySelector('[data-me-readout]').textContent=compositionReadout(c,x);
        });
      }
    }
    return ()=>cleanups.forEach(fn=>fn());
  },
};
