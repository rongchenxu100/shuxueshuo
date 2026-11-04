import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';
import {createRequire} from 'node:module';
import {generateCourse} from '../build-graph-walk-topic.mjs';
import {createState,currentDecision,submitAnswer,replayState} from '../../site/assets/graph-walk/walk-state.mjs';
import {replayAnswer} from '../../site/assets/graph-walk/walk-replay.mjs';
import {methodCardsHTML} from '../../site/assets/graph-walk/method-cards.mjs';
const read = async p => JSON.parse(await fs.readFile(p,'utf8'));
const katex = createRequire(import.meta.url)('../../site/assets/practice/vendor/katex-0.18.9/katex.min.js');
const scope=vm.createContext({window:{}});
vm.runInContext(await fs.readFile('site/assets/practice/components.js','utf8'),scope);
const ui=scope.window.PracticeComponents;
const prefixFor = id => `site/data/graph-walk/function-monotonicity-a${id}${['02','15','12','04'].includes(id)?'-v4':'-v2'}`;

for(const id of ['03','02','15','12','04','01']) test(`A${id}: every route grades, draws and restores to verified completion`,async()=>{
 const prefix=prefixFor(id);
 const b=await read(prefix+'.json');
 assert.equal(replayState(b,await read(prefix+'.replay.json')).done,true);
 for(const route of Object.keys(b.routes)){
  let state=createState(b), count=0;
  while(!state.done && count++<100){
   const step=currentDecision(b,state);
   assert.ok(step);
   if(step.stem_board) assert.equal(step.stem_board.items[1].math,null);
   for(const board of [step.stem_board,step.completion_board].filter(Boolean)){
    for(const item of board.items) if(item.math) assert.doesNotThrow(()=>katex.renderToString(item.math,{throwOnError:true,strict:'ignore'}));
   }
   for(const g of [step.graph,step.completion_graph,...(step.completion_graphs||[])].filter(Boolean)){
    assert.equal(ui.validateGraph(g),true);
    const html=ui.graph(g,{uid:'fm-test'});
    assert.match(html,/<svg/);assert.doesNotMatch(html,/NaN|Infinity/);
   }
   const answer=replayAnswer(step,route);
   state=submitAnswer(b,state,{decision:step.id,answer});
   assert.equal(state.lastFeedback.status,'passed',step.id);
   state=JSON.parse(JSON.stringify(state));
  }
  assert.equal(state.done,true);assert.equal(state.run.route,route);
 }
 const output=await generateCourse({sourcePath:prefix+'.source.json'});
 assert.deepEqual(JSON.parse(output.get(prefix+'.json')),b);
});

test('interval families preserve gaps and turning points in authored answers',async()=>{
 const b=await read(prefixFor('01')+'.json');
 const answer=Object.values(b.routes)[0].completion.answer;
 assert.equal(answer.interval_families.increasing.length,2);
 assert.match(answer.latex,/和/);assert.doesNotMatch(answer.latex,/cup/);
 const reciprocal=await read(prefixFor('04')+'.json');
 const graphs=Object.values(reciprocal.routes).flatMap(r=>r.steps).map(s=>s.graph).filter(g=>g?.kind==='piecewise_curve');
 const g=graphs.find(g=>g.params.segments[0].transform==='reciprocal_sqrt');
 assert.equal(g.params.segments.length,2);
 assert.ok(g.params.segments.every(s=>s.interval_closed.every(x=>!x)));
 const html=ui.graph(g,{uid:'fm-poles'});
 assert.equal((html.match(/class="piecewise-segment"/g)||[]).length,2);
 assert.doesNotMatch(html,/class="piecewise-endpoint"/);
});

test('quadratic practice asks for vertex form before progressive graph judgments', async()=>{
 const b=await read(prefixFor('03')+'.json');
 assert.deepEqual(Object.keys(b.routes),['monotonicity-structure']);
 const choice=b.intro.find(s=>s.interaction.type==='method_cards');
 const map=methodCardsHTML(choice,null,true);
 assert.match(map,/一次、二次、反比例/);
 assert.match(map,/data-method-node="definition"[^>]*disabled/);
 assert.doesNotMatch(map,/data-method-node="piecewise"[^>]*disabled/);
 for(const cue of choice.interaction.checks[0].options){
  assert.ok(cue.note);
  for(const [,tex] of cue.note.matchAll(/\$([^$]+)\$/g)) katex.renderToString(tex,{throwOnError:true,strict:'ignore'});
 }
 const steps=b.routes['monotonicity-structure'].steps;
 const square=steps.findIndex(s=>s.title.includes('配成顶点式'));
 const judgments=steps.filter(s=>s.graph?.params.interval_marks?.some(m=>m.trend==='pending'));
 assert.equal(judgments.length,2);
 assert.ok(square>=0 && square<steps.indexOf(judgments[0]));
 assert.equal(steps[square].graph,undefined);
 assert.ok(steps[square].completion_graph);
 assert.notEqual(judgments[0].title,judgments[1].title);
 assert.ok(judgments.every(s=>s.title.includes('二次函数')));
 const initial=ui.graph(judgments[0].graph,{uid:'fm-question'});
 assert.match(initial,/piecewise-active-interval/);
 assert.match(initial,/>\?<\/text>/);
 assert.match(initial,/\[0, 2\]/);
 assert.doesNotMatch(initial,/↑|↓/);
 const second=ui.graph(judgments[1].graph,{uid:'fm-second'});
 assert.match(second,/↑/);assert.doesNotMatch(second,/↓/);
 assert.match(second,/\[2, 3\]/);
 const answer=steps.at(-1);
 const final=ui.graph(answer.graph,{uid:'fm-answer'});
 assert.match(final,/↑/);assert.match(final,/↓/);
 assert.doesNotMatch(final,/>\?<\/text>/);
 // The completed group shows one combined figure instead of repeating the plot per part.
 assert.equal(judgments.filter(s=>s.completion_graph).length,1);
 const bad=structuredClone(answer.graph);
 bad.params.interval_marks[0].from=null;bad.params.interval_marks[0].left_closed=true;
 assert.equal(ui.validateGraph(bad),false);
});

for (const id of ['02', '04']) test(`A${id}: composition graphs mark the known input interval and name each operation`, async()=>{
 const b=await read(prefixFor(id)+'.json');
 const parts=Object.values(b.routes).flatMap(r=>r.steps).filter(p=>p.stem_board?.operation);
 assert.equal(parts.length,id==='02'?2:4);
 for (const part of parts){
  const {operation}=part.stem_board;
  assert.deepEqual(operation,part.completion_board.operation);
  assert.equal(part.stem_board.items[1].math,null);
  katex.renderToString(operation.math,{throwOnError:true,strict:'ignore'});
  const graph=part.graph, mark=graph.params.interval_marks[0];
  assert.equal(ui.validateGraph(graph),true);
  assert.equal(graph.params.interval_marks.length,1);
  assert.deepEqual([mark.from,mark.to],[graph.params.highlights[0].from,graph.params.highlights[0].to]);
  const svg=ui.graph(graph,{uid:'fm-composition'});
  assert.ok(svg.includes(mark.label));
  assert.match(svg,/class="piecewise-highlight"/);
  assert.match(svg,/class="piecewise-interval-divider"/);
  assert.doesNotMatch(svg,/>\?<\/text>|NaN|Infinity/);
  assert.equal((svg.match(/class="piecewise-trend"/g)||[]).length,1);
  assert.ok(svg.includes(mark.trend==='increasing'?'↑':'↓'));
  assert.equal(graph.params.segments[0].transform,operation.label==='开方'?'identity':'sqrt');
 }
 if(id==='04'){
  assert.deepEqual(parts.map(p=>p.stem_board.operation.label),['开方','取倒数','开方','取倒数']);
  assert.ok(parts.every(p=>p.graph.params.interval_marks.every(m=>!m.left_closed&&!m.right_closed)));
 }
});

test('interval dividers mark the shared boundary once in active and summary graphs', async()=>{
 const b=await read(prefixFor('03')+'.json');
 const steps=b.routes['monotonicity-structure'].steps;
 const active=steps.find(s=>s.graph?.params.interval_marks?.some(m=>m.trend==='pending')).graph;
 for(const graph of [active,steps.at(-1).graph]){
  const html=ui.graph(graph,{uid:'fm-divider'});
  assert.deepEqual([...html.matchAll(/class="piecewise-interval-divider" data-x="([^"]+)"/g)].map(m=>Number(m[1])),[2]);
  assert.match(html,/aria-label="区间分界 x = 2"/);
  assert.match(html,/stroke-dasharray="4 4"/);
 }
 assert.match(ui.graph(active,{uid:'fm-pending'}),/>\?<\/text>/);
});

test('interval dividers handle unbounded intervals without inventing viewport boundaries', async()=>{
 const b=await read(prefixFor('03')+'.json');
 const graph=structuredClone(b.routes['monotonicity-structure'].steps.at(-1).graph);
 delete graph.params.interval_marks;
 assert.doesNotMatch(ui.graph(graph,{uid:'fm-unmarked'}),/piecewise-interval-divider/);
 graph.params.bounds=[-2,2,-2,2];
 graph.params.interval=[null,null]; graph.params.interval_closed=[false,false];
 graph.params.segments=[{coefficients:[0,1,0],interval:[null,null],interval_closed:[false,false]}];
 graph.params.xTicks=[[-2,'-2'],[0,'0'],[2,'2']];
 graph.params.interval_marks=[[null,-4],[-4,0],[0,4],[4,null]].map(([from,to])=>({
  from,to,left_closed:from!==null,right_closed:to!==null,label:`${from??'-∞'}, ${to??'+∞'}`,trend:'pending'
 }));
 assert.equal(ui.validateGraph(graph),true);
 const html=ui.graph(graph,{uid:'fm-unbounded'});
 assert.deepEqual([...html.matchAll(/class="piecewise-interval-divider" data-x="([^"]+)"/g)].map(m=>Number(m[1])),[0]);
 assert.doesNotMatch(html,/NaN|Infinity/);
});
