/* Concrete examples illustrate identities; sampled points never decide parity. */
import {escapeHtml as escape} from '../shared/html.js?v=1';

const math = text => `<span data-math-text>${escape(text)}</span>`;
const number = n => Math.abs(n) < 1e-8 ? '0' : String(Number(n.toFixed(2))).replace('-', '−');
const curve = (f, from = -2.5, to = 2.5, role = 'result') => ({f, from, to, role});
const buttons = cases => `<div class="pe-cases" role="group" aria-label="选择观察情形">${Object.entries(cases).map(([key,c],i)=>`<button type="button" data-pe-case="${key}" aria-pressed="${i===0}">${escape(c.label)}</button>`).join('')}</div>`;
const panel = (key, i, body) => `<section class="pe-panel" data-pe-panel="${key}"${i?' hidden':''}>${body}</section>`;
const conclusion = text => `<p class="pe-conclusion">${math(text)}</p>`;
const formula = text => `<p class="pe-formula">${math(text)}</p>`;
const explorer = (kind, body) => `<div class="pe-explorer" data-pe-kind="${kind}">${body}</div>`;
const control = (key, label, min, max, value, step = .1) => `<label class="pe-control"><span>${label}</span><input type="range" data-pe-control="${key}" min="${min}" max="${max}" step="${step}" value="${value}"><output>${number(value)}</output></label>`;

export const DOMAIN_CASES = {
  closed: {label:'对称闭区间', formula:'$D=[-2,2]$', from:-2, to:2, x:1.5, contains:x=>x>=-2&&x<=2, symmetric:true,
    explanation:'每个输入都能找到它的相反数，包括两个实心端点。定义域对称，接下来才能检查函数值。'},
  halfOpen: {label:'端点不配对', formula:'$D=[-2,2)$', from:-2, to:2, openRight:true, x:-2, contains:x=>x>=-2&&x<2, symmetric:false,
    explanation:'−2 可以取到，2 却不能取到。两个端点一实一空，定义域不对称，函数必定非奇非偶。'},
  asymmetric: {label:'区间不对称', formula:'$D=[-1,2]$', from:-1, to:2, x:2, contains:x=>x>=-1&&x<=2, symmetric:false,
    explanation:'2 在定义域内，−2 不在。仅有一部分输入能配对还不够，函数必定非奇非偶。'},
  hole: {label:'约分后的缺口', formula:'$f(x)=\\frac{2x^2+2x}{x+1}$，$D=\\mathbb R\\setminus\\{-1\\}$', from:-3, to:3, infinite:true, holes:[-1], x:1, contains:x=>x!==-1, symmetric:false,
    explanation:'约分后虽然得到 2x，原函数在 −1 处仍无定义，而 1 可以取。这个缺口不能补回，原函数非奇非偶。'},
  pairedHoles: {label:'缺口也成对', formula:'$D=\\mathbb R\\setminus\\{-1,1\\}$', from:-3, to:3, infinite:true, holes:[-1,1], x:2, contains:x=>Math.abs(x)!==1, symmetric:true,
    explanation:'−1 与 1 同时被排除，剩下的输入仍能一一配对。定义域对称；是否奇、偶还要检查函数值。'},
};

export function domainPair(c) {
  return {x:c.x, reflected:-c.x, valid:c.contains(c.x), reflectedValid:c.contains(-c.x)};
}
function domainGraph(c) {
  const sx = x => 280 + 72*x, y=90, p=domainPair(c);
  const dot=(x,open=false,role='result',cy=y,r=5)=>`<circle class="pe-dot pe-${role}${open?' pe-open':''}" cx="${sx(x)}" cy="${cy}" r="${r}"/>`;
  const holes=(c.holes||[]).map(x=>dot(x,true)).join('');
  const ends=c.infinite?`<path class="pe-domain-line" d="M${sx(-3)+6} ${y-5}l-6 5 6 5 M${sx(3)-6} ${y-5}l6 5-6 5"/>`:dot(c.from)+dot(c.to,c.openRight);
  return `<svg class="pe-domain-plot" viewBox="0 0 560 185" role="img" aria-label="${escape(c.explanation)}">
    <path class="pe-axis" d="M35 ${y}H525"/>
    <path class="pe-domain-line" d="M${sx(c.from)} ${y}H${sx(c.to)}"/>${ends}${holes}
    ${[-3,-2,-1,0,1,2,3].map(x=>`<text class="pe-tick" x="${sx(x)}" y="118" text-anchor="middle">${number(x)}</text>`).join('')}
    <path class="pe-guide" d="M${sx(p.x)} 53V${y}M${sx(p.reflected)} 53V${y}"/>
    ${dot(p.x,!p.valid,'right',45,7)}${dot(p.reflected,!p.reflectedValid,'left',45,7)}
    <text class="pe-label pe-right" x="${sx(p.x)}" y="26" text-anchor="middle">x = ${number(p.x)}</text>
    <text class="pe-label pe-left" x="${sx(p.reflected)}" y="26" text-anchor="middle">−x = ${number(p.reflected)}</text>
    <text class="pe-label" x="280" y="158" text-anchor="middle">${c.symmetric?'定义域对称：输入能够配对':'定义域不对称：找到一个无法配对的输入'}</text>
  </svg>`;
}
function domainFigure() {
  return explorer('domain',buttons(DOMAIN_CASES)+Object.entries(DOMAIN_CASES).map(([key,c],i)=>panel(key,i,
    formula(c.formula)+domainGraph(c)+conclusion(c.explanation))).join(''));
}

// Keep a fixed coordinate window while sliders move: no rescaling or layout shifts.
function geometry({xmin=-3,xmax=3,ymin=-5,ymax=9}={}) {
  return {left:48,right:516,top:38,bottom:274,
    sx:x=>48+(x-xmin)/(xmax-xmin)*468,
    sy:y=>274-(y-ymin)/(ymax-ymin)*236, xmin,xmax,ymin,ymax};
}
function plot(id, curves, {label, points=[], bounds={}, overlay=()=>'', footer='', height=316}={}) {
  const p=geometry(bounds), x0=p.sx(0), y0=p.sy(0);
  const paths=curves.map(c=>{
    let pen=false;
    const d=Array.from({length:201},(_,i)=>{
      const x=c.from+(c.to-c.from)*i/200,y=c.f(x);
      if(!Number.isFinite(y)){pen=false;return '';}
      const part=`${pen?'L':'M'}${p.sx(x).toFixed(2)} ${p.sy(y).toFixed(2)}`;pen=true;return part;
    }).join(' ');
    return `<path class="pe-curve pe-${c.role}" d="${d}"/>`;
  }).join('');
  const grid=[];
  for(let x=Math.ceil(p.xmin);x<=p.xmax;x++) grid.push(`<path class="pe-grid" d="M${p.sx(x)} ${p.top}V${p.bottom}"/><text class="pe-tick" x="${p.sx(x)}" y="${p.bottom+21}" text-anchor="middle">${number(x)}</text>`);
  const step=(p.ymax-p.ymin)>12?4:2;
  for(let y=Math.ceil(p.ymin/step)*step;y<=p.ymax;y+=step) grid.push(`<path class="pe-grid" d="M${p.left} ${p.sy(y)}H${p.right}"/><text class="pe-tick" x="${p.left-10}" y="${p.sy(y)+5}" text-anchor="end">${number(y)}</text>`);
  const marks=points.map(({x,y,role='right',open=false,label='',dx=10,dy=-10,guide=true})=>`${guide?`<path class="pe-guide pe-${role}" d="M${p.sx(x)} ${y0}V${p.sy(y)}H${x0}"/>`:''}<circle class="pe-dot pe-${role}${open?' pe-open':''}" cx="${p.sx(x)}" cy="${p.sy(y)}" r="5"/>${label?`<text class="pe-label pe-${role} pe-halo" x="${p.sx(x)+dx}" y="${p.sy(y)+dy}">${escape(label)}</text>`:''}`).join('');
  return `<svg class="pe-plot" viewBox="0 0 560 ${height}" role="img" aria-label="${escape(label)}">
    <defs><clipPath id="pe-clip-${id}"><rect x="${p.left}" y="${p.top}" width="468" height="236"/></clipPath></defs>
    ${grid.join('')}<path class="pe-axis" d="M${p.left} ${y0}H${p.right+8}M${x0} ${p.bottom+2}V${p.top-10}"/>
    <path class="pe-axis" d="M${p.right+2} ${y0-4}l6 4-6 4M${x0-4} ${p.top-4}l4-6 4 6"/>
    <text class="pe-axis-label" x="${p.right+14}" y="${y0+4}">x</text><text class="pe-axis-label" x="${x0-15}" y="${p.top-13}">y</text>
    <g clip-path="url(#pe-clip-${id})">${paths}</g>${overlay(p)}${marks}${footer?footer(p):''}
  </svg>`;
}

export const PAIR_CASES = {
  odd:{label:'奇函数', formula:'$f(x)=\\frac{x^3}{3}$，$D=\\mathbb R$', f:x=>x**3/3, parity:'odd',
    identity:'$f(-x)=\\frac{(-x)^3}{3}=-f(x)$', explanation:'相反输入的输出互为相反数。每一对点的中点都是原点，整幅图像绕原点旋转半周后重合。'},
  even:{label:'偶函数', formula:'$f(x)=x^2-1$，$D=\\mathbb R$', f:x=>x*x-1, parity:'even',
    identity:'$f(-x)=(-x)^2-1=f(x)$', explanation:'相反输入的输出相等。每一对点在同一高度，到 y 轴距离相同，整幅图像关于 y 轴对称。'},
  zero:{label:'既奇又偶', formula:'$f(x)=0$，$D=\\mathbb R$', f:()=>0, parity:'both',
    identity:'$f(-x)=0=f(x)=-f(x)$', explanation:'这两种对称同时成立。零函数在对称定义域上既是奇函数又是偶函数。'},
  neither:{label:'非奇非偶', formula:'$f(x)=x^2+x$，$D=\\mathbb R$', f:x=>x*x+x, parity:'neither',
    identity:'$f(-x)=x^2-x$，与 $f(x)$、$-f(x)$ 都不恒等', explanation:'定义域虽然对称，函数值却不满足奇函数或偶函数的恒等关系。定义域对称只是第一关。'},
};
export function pairValues(c,a) { return {right:c.f(a),left:c.f(-a)}; }
function pairGraph(key,a) {
  const c=PAIR_CASES[key],v=pairValues(c,a);
  return plot(`pair-${key}`,[curve(c.f)],{label:`${c.label}：输入 ${number(a)} 与 ${number(-a)}，输出 ${number(v.right)} 与 ${number(v.left)}`,bounds:{ymin:-9,ymax:9},
    points:[{x:a,y:v.right,label:'P'},{x:-a,y:v.left,role:'left',label:'Q',dx:-23}],
    overlay:p=>`<path class="pe-pair-line" d="M${p.sx(-a)} ${p.sy(v.left)}L${p.sx(a)} ${p.sy(v.right)}"/>${['odd','both'].includes(c.parity)?`<circle class="pe-center" cx="${p.sx(0)}" cy="${p.sy(0)}" r="4"/>`:''}`});
}
const pairReadout = (key,a) => {
  const v=pairValues(PAIR_CASES[key],a);
  return `P：(${number(a)}, ${number(v.right)})；Q：(${number(-a)}, ${number(v.left)})。`;
};
function pairFigure() {
  return explorer('pair',buttons(PAIR_CASES)+Object.entries(PAIR_CASES).map(([key,c],i)=>panel(key,i,
    formula(c.formula)+`<div data-pe-graph>${pairGraph(key,1.5)}</div>`+control('a','移动正数输入 a',.3,2.4,1.5)+
    `<p class="pe-readout" data-pe-readout aria-live="polite">${pairReadout(key,1.5)}</p>`+formula(c.identity)+conclusion(c.explanation))).join(''));
}

export const OPERATION_CASES = {
  evenSum:{label:'偶 + 偶', formula:'$f(x)=x^2$，$g(x)=1$；$h(x)=f(x)+g(x)=x^2+1$', f:x=>x*x,g:()=>1,h:x=>x*x+1,parity:'even',
    rule:'两部分在相反输入下都不变，所以和仍为偶函数。'},
  oddSum:{label:'奇 + 奇', formula:'$f(x)=x$，$g(x)=x^3$；$h(x)=x+x^3$', f:x=>x,g:x=>x**3,h:x=>x+x**3,parity:'odd',
    rule:'两部分同时变号，和也变号，所以和为奇函数。'},
  mixed:{label:'奇 + 偶', formula:'$f(x)=x$，$g(x)=x^2+1$；$h(x)=x+x^2+1$', f:x=>x,g:x=>x*x+1,h:x=>x+x*x+1,parity:'neither',
    rule:'本例的奇、偶两部分都不恒为 0，和非奇非偶。若有一部分恒为 0，结论会改变。'},
  sameProduct:{label:'奇 × 奇', formula:'$f(x)=x$，$g(x)=x$；$h(x)=x^2$', f:x=>x,g:x=>x,h:x=>x*x,parity:'even',
    rule:'两个因子同时变号，负负得正，所以乘积为偶函数。'},
  differentProduct:{label:'奇 × 偶', formula:'$f(x)=x$，$g(x)=x^2+1$；$h(x)=x(x^2+1)$', f:x=>x,g:x=>x*x+1,h:x=>x*(x*x+1),parity:'odd',
    rule:'只有奇函数因子变号，所以乘积为奇函数。'},
  quotient:{label:'奇 ÷ 奇', formula:'$f(x)=x^3$，$g(x)=x$；$h(x)=\\frac{x^3}{x}=x^2$，$x\\ne0$', f:x=>x**3,g:x=>x,h:x=>x===0?NaN:x*x,parity:'even',hole:true,
    rule:'分子分母同时变号，比值不变。结果为偶函数，但 x=0 仍须排除；图上的空心点不能补回。'},
  absolute:{label:'奇函数取绝对值', formula:'$f(x)=x$；$h(x)=|f(x)|=|x|$', f:x=>x,h:Math.abs,parity:'even',
    rule:'互为相反数的函数值取绝对值后相等，所以得到偶函数。这个结论的前提是原函数为奇函数或偶函数。'},
  zero:{label:'相减得到零函数', formula:'$f(x)=g(x)=x$；$h(x)=f(x)-g(x)=0$',f:x=>x,g:x=>x,h:()=>0,parity:'both',
    rule:'奇函数之差仍满足奇函数的定义；本例恰好恒为 0，同时也满足偶函数的定义。'},
};
const parityLabel = key => ({odd:'奇函数',even:'偶函数',both:'既奇又偶',neither:'非奇非偶'})[key];
function operationsFigure() {
  return explorer('operations',buttons(OPERATION_CASES)+Object.entries(OPERATION_CASES).map(([key,c],i)=>panel(key,i,
    formula(c.formula)+`<p class="pe-legend"><span>灰实线 f</span>${c.g?'<span>灰虚线 g</span>':''}<span class="pe-right">绿色 h</span><strong>${parityLabel(c.parity)}</strong></p>`+
    plot(`operation-${key}`,[curve(c.f,-2,2,'base'),...(c.g?[curve(c.g,-2,2,'other')]:[]),curve(c.h,-2,2)],{label:`${c.label}：${parityLabel(c.parity)}`,bounds:{ymin:-10,ymax:10},points:[{x:1,y:c.h(1),label:'h(1)'},{x:-1,y:c.h(-1),role:'left',label:'h(−1)',dx:-52},...(c.hole?[{x:0,y:0,open:true,guide:false}]:[])]})+
    `<p class="pe-domain">${c.hole?'h 的定义域：所有非零实数':'所有函数的定义域：实数集'}</p>`+conclusion(c.rule))).join(''));
}

export const COMPOSITION_CASES = {
  evenEven:{label:'内偶 · 外偶',inner:'$g(x)=x^2$',outer:'$f(u)=u^2$',result:'$h(x)=x^4$',g:x=>x*x,f:u=>u*u,parity:'even',
    rule:'内层将相反输入变成同一个数。外层收到相同输入，输出必然相等。'},
  evenOdd:{label:'内偶 · 外奇',inner:'$g(x)=x^2$',outer:'$f(u)=u^3$',result:'$h(x)=x^6$',g:x=>x*x,f:u=>u**3,parity:'even',
    rule:'尽管外层是奇函数，内层给它的两个输入已经相等，所以复合结果仍为偶函数。'},
  evenNeither:{label:'内偶 · 外非奇非偶',inner:'$g(x)=x^2$',outer:'$f(u)=u+1$',result:'$h(x)=x^2+1$',g:x=>x*x,f:u=>u+1,parity:'even',
    rule:'只要内层是偶函数且复合有意义，外层不需要具有奇偶性，结果也为偶函数。'},
  oddEven:{label:'内奇 · 外偶',inner:'$g(x)=x$',outer:'$f(u)=u^2$',result:'$h(x)=x^2$',g:x=>x,f:u=>u*u,parity:'even',
    rule:'内层给出互为相反数的输出，外层偶函数又把它们变成相等的数，所以结果为偶函数。'},
  oddOdd:{label:'内奇 · 外奇',inner:'$g(x)=x$',outer:'$f(u)=u^3$',result:'$h(x)=x^3$',g:x=>x,f:u=>u**3,parity:'odd',
    rule:'内层输出互为相反数，外层奇函数的输出仍互为相反数，所以结果为奇函数。'},
};
export function compositionValues(c,a) {
  return {inputs:[a,-a],inner:[c.g(a),c.g(-a)],outer:[c.f(c.g(a)),c.f(c.g(-a))]};
}
function compositionGraph(key,a) {
  const c=COMPOSITION_CASES[key],v=compositionValues(c,a);
  return plot(`composition-${key}`,[curve(x=>c.f(c.g(x)),-1.4,1.4)],{label:`复合结果为${parityLabel(c.parity)}，两次输出为 ${number(v.outer[0])} 与 ${number(v.outer[1])}`,bounds:{xmin:-2,xmax:2,ymin:-4,ymax:8},points:[{x:a,y:v.outer[0],label:'h(a)'},{x:-a,y:v.outer[1],role:'left',label:'h(−a)',dx:-50}]});
}
function flowValues(values) { return `<span class="pe-right">${number(values[0])}</span><span class="pe-left">${number(values[1])}</span>`; }
function compositionFigure() {
  return explorer('composition',buttons(COMPOSITION_CASES)+Object.entries(COMPOSITION_CASES).map(([key,c],i)=>{
    const v=compositionValues(c,1.2);
    return panel(key,i,`<div class="pe-flow"><div><h4>① 相反输入</h4>${formula('$x$')}<p data-pe-flow="inputs">${flowValues(v.inputs)}</p></div><div><h4>② 内层输出</h4>${formula(c.inner)}<p data-pe-flow="inner">${flowValues(v.inner)}</p></div><div><h4>③ 外层输出</h4>${formula(c.outer)}<p data-pe-flow="outer">${flowValues(v.outer)}</p></div></div>`+
      formula(`复合结果：${c.result}，${parityLabel(c.parity)}`)+`<div data-pe-graph>${compositionGraph(key,1.2)}</div>`+
      control('a','移动输入 a',.3,1.3,1.2)+`<p class="pe-domain">本组例子内、外层及复合结果的定义域均为实数集。绿色一行从 a 出发，橙色一行从 −a 出发。</p>`+conclusion(c.rule));
  }).join(''));
}

export const INTERVAL_CASES = {
  oddIncreasing:{label:'奇函数 · [1, 3] 上递增',odd:true,increasing:true},
  oddDecreasing:{label:'奇函数 · [1, 3] 上递减',odd:true,increasing:false},
  evenIncreasing:{label:'偶函数 · [1, 3] 上递增',odd:false,increasing:true},
  evenDecreasing:{label:'偶函数 · [1, 3] 上递减',odd:false,increasing:false},
};
export function intervalState(c) {
  const right=x=>c.increasing?x+1:4-x;
  const f=x=>x>0?right(x):(c.odd?-1:1)*right(-x);
  const endpoints=xs=>xs.map(x=>({x,y:f(x)}));
  const side=xs=>{
    const points=endpoints(xs);
    return {points,min:points.reduce((a,b)=>a.y<b.y?a:b),max:points.reduce((a,b)=>a.y>b.y?a:b)};
  };
  return {f,right:side([1,3]),left:side([-3,-1]),leftIncreasing:c.odd?c.increasing:!c.increasing};
}
function intervalGraph(key) {
  const c=INTERVAL_CASES[key],s=intervalState(c);
  return plot(`interval-${key}`,[curve(s.f,-3,-1,'left'),curve(s.f,1,3)],{label:`${c.label}；[−3, −1] 上${s.leftIncreasing?'递增':'递减'}，最小值 ${s.left.min.y}、最大值 ${s.left.max.y}`,bounds:{xmin:-4,xmax:4,ymin:-5,ymax:5},height:360,
    points:[...s.right.points.map(p=>({...p,label:number(p.y)})),...s.left.points.map(p=>({...p,role:'left',label:number(p.y),dx:-22}))],
    overlay:p=>`<text class="pe-label pe-left" x="${p.sx(-2)}" y="23" text-anchor="middle">${s.leftIncreasing?'递增 ↗':'递减 ↘'}</text><text class="pe-label pe-right" x="${p.sx(2)}" y="23" text-anchor="middle">${c.increasing?'递增 ↗':'递减 ↘'}</text>`,
    footer:p=>[[-3,-1,'left'],[1,3,'right']].map(([a,b,role])=>`<path class="pe-interval pe-${role}" d="M${p.sx(a)} 312v8H${p.sx(b)}v-8"/><text class="pe-label pe-${role}" x="${p.sx((a+b)/2)}" y="344" text-anchor="middle">[${number(a)}, ${number(b)}]</text>`).join('')});
}
function intervalsFigure() {
  return explorer('intervals',buttons(INTERVAL_CASES)+Object.entries(INTERVAL_CASES).map(([key,c],i)=>{
    const s=intervalState(c);
    const card=(label,side,role)=>`<div class="pe-value-card pe-${role}"><h4>${label}</h4><p>最大值 ${number(side.max.y)}，在 x = ${number(side.max.x)} 取得</p><p>最小值 ${number(side.min.y)}，在 x = ${number(side.min.x)} 取得</p></div>`;
    return panel(key,i,formula(`$D=[-3,-1]\\cup[1,3]$，$[1,3]$ 上 $f(x)=${c.increasing?'x+1':'4-x'}$，$[-3,-1]$ 上按${c.odd?'奇':'偶'}函数配对`)+intervalGraph(key)+
      `<div class="pe-values">${card('[−3, −1] 上',s.left,'left')}${card('[1, 3] 上',s.right,'right')}</div>`+
      conclusion(c.odd?'奇函数：两个区间上单调方向相同；一个区间上的最大值对应另一个区间上的最小值，数值取反。两段区间分别讨论，不能跨过中间的空白连接图像。':'偶函数：两个区间上单调方向相反；最大值相等、最小值也相等，取得它们的输入互为相反数。'));
  }).join(''));
}

export function symmetryState(kind,a,b,t) {
  const f=kind==='center'?x=>.5*(x-a)**3+b:x=>.5*(x-a)**2+b;
  return {f,left:{x:a-t,y:f(a-t)},right:{x:a+t,y:f(a+t)},a,b,t};
}
function symmetryGraph(kind,a,b,t) {
  const s=symmetryState(kind,a,b,t);
  return plot(`symmetry-${kind}`,[curve(s.f,-4,4)],{label:`关于${kind==='center'?`点 (${number(a)}, ${number(b)})`:`直线 x=${number(a)}`}对称；点 L (${number(s.left.x)}, ${number(s.left.y)})，点 R (${number(s.right.x)}, ${number(s.right.y)})`,bounds:{xmin:-4,xmax:4,ymin:-6,ymax:6},
    points:[{...s.left,role:'left',label:'L',dx:-22},{...s.right,label:'R'}],
    overlay:p=>`<path class="pe-pair-line" d="M${p.sx(s.left.x)} ${p.sy(s.left.y)}L${p.sx(s.right.x)} ${p.sy(s.right.y)}"/>`+(kind==='axis'?
      `<path class="pe-symmetry-axis" d="M${p.sx(a)} ${p.top}V${p.bottom}"/><text class="pe-label pe-halo" x="${p.sx(a)+8}" y="28">x = ${number(a)}</text>`:
      `<circle class="pe-center" cx="${p.sx(a)}" cy="${p.sy(b)}" r="5"/><text class="pe-label pe-halo" x="${p.sx(a)+9}" y="${p.sy(b)-12}">C (${number(a)}, ${number(b)})</text>`)});
}
function symmetryReadout(kind,a,b,t) {
  const s=symmetryState(kind,a,b,t);
  return `点 L：(${number(s.left.x)}, ${number(s.left.y)})；点 R：(${number(s.right.x)}, ${number(s.right.y)})。`+
    (kind==='center'?`横坐标平均值 ${number(a)}，纵坐标平均值 ${number(b)}。L、R 的中点就是 C。`:`两点到 x = ${number(a)} 的距离都是 ${number(t)}，高度都为 ${number(s.left.y)}。`);
}
function symmetryFigure(kind) {
  const center=kind==='center',a=1,b=center?1:-1,t=1.2;
  return explorer(kind,formula(center?'示例 $f(x)=\\frac12(x-a)^3+b$，定义域为 $\\mathbb R$':'示例 $f(x)=\\frac12(x-a)^2+b$，定义域为 $\\mathbb R$')+
    `<div data-pe-graph>${symmetryGraph(kind,a,b,t)}</div><div class="pe-controls">`+
    control('a',center?'中心横坐标 a':'对称轴位置 a',-1.5,1.5,a)+control('b',center?'中心纵坐标 b':'上下移动 b',-1.5,1.5,b)+control('t','水平偏移 t',.3,1.8,t)+`</div>`+
    `<p class="pe-readout" data-pe-readout aria-live="polite">${symmetryReadout(kind,a,b,t)}</p>`+
    formula(center?'$f(a-t)+f(a+t)=2b$；平移后 $g(t)=f(a+t)-b=\\frac12t^3$，是奇函数':'$f(a-t)=f(a+t)$；平移后 $g(t)=f(a+t)=\\frac12t^2+b$，是偶函数')+
    conclusion(center?'移动 a、b 改变对称中心，移动 t 改变一对点的位置。只有中心移到原点时，本例的原函数才是奇函数。':'移动 a 改变对称轴，移动 b 只改变图像高度。只有 a=0 时，本例的原函数才是偶函数。'));
}

export default {
  stylesheet:new URL('parity-explorer.css',import.meta.url).href,
  domainFigure,pairFigure,operationsFigure,compositionFigure,intervalsFigure,
  centerFigure:()=>symmetryFigure('center'),axisFigure:()=>symmetryFigure('axis'),
  render:domainFigure,
  mount(root) {
    const el=root.querySelector('[data-pe-kind]');
    if(!el) return;
    const cleanups=[],on=(target,type,fn)=>{target.addEventListener(type,fn);cleanups.push(()=>target.removeEventListener(type,fn));};
    for(const button of el.querySelectorAll('[data-pe-case]')) on(button,'click',()=>{
      for(const b of el.querySelectorAll('[data-pe-case]')) b.setAttribute('aria-pressed',String(b===button));
      for(const p of el.querySelectorAll('[data-pe-panel]')) p.hidden=p.dataset.pePanel!==button.dataset.peCase;
    });
    for(const p of el.querySelectorAll('[data-pe-panel]')) {
      const key=p.dataset.pePanel,input=p.querySelector('[data-pe-control="a"]');
      if(!input) continue;
      on(input,'input',()=>{
        const a=Number(input.value);input.nextElementSibling.value=number(a);
        if(el.dataset.peKind==='pair') {
          p.querySelector('[data-pe-graph]').innerHTML=pairGraph(key,a);
          p.querySelector('[data-pe-readout]').textContent=pairReadout(key,a);
        } else if(el.dataset.peKind==='composition') {
          const v=compositionValues(COMPOSITION_CASES[key],a);
          p.querySelector('[data-pe-graph]').innerHTML=compositionGraph(key,a);
          for(const output of p.querySelectorAll('[data-pe-flow]')) output.innerHTML=flowValues(v[output.dataset.peFlow]);
        }
      });
    }
    if(['center','axis'].includes(el.dataset.peKind)) {
      const inputs=[...el.querySelectorAll('[data-pe-control]')];
      const draw=()=>{
        const values=Object.fromEntries(inputs.map(input=>[input.dataset.peControl,Number(input.value)]));
        for(const input of inputs) input.nextElementSibling.value=number(Number(input.value));
        el.querySelector('[data-pe-graph]').innerHTML=symmetryGraph(el.dataset.peKind,values.a,values.b,values.t);
        el.querySelector('[data-pe-readout]').textContent=symmetryReadout(el.dataset.peKind,values.a,values.b,values.t);
      };
      for(const input of inputs) on(input,'input',draw);
    }
    // KaTeX formulas are pre-rendered; only SVG and numeric readouts change on input.
    return ()=>cleanups.forEach(fn=>fn());
  },
};
