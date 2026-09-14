import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import {validateExpressionRewrite} from '../lib/expression-rewrite-spec.mjs';
import {validateTextLesson} from '../build-text-page.mjs';
const base = new URL('../../', import.meta.url);
const spec = JSON.parse(fs.readFileSync(new URL('internal/experiments/organize-expressions-q08/deterministic/visual-spec.json',base),'utf8'));
const context = vm.createContext({});
vm.runInContext(fs.readFileSync(new URL('site/assets/js/expression-rewrite.js',base),'utf8'),context);

test('generated q08 spec and lesson validate with structural node references',()=>{
  assert.equal(validateExpressionRewrite(spec),spec);
  const lesson=JSON.parse(fs.readFileSync(new URL('internal/experiments/organize-expressions-q08/deterministic/lesson-data.json',base),'utf8'));
  assert.equal(validateTextLesson(lesson),lesson);
});
test('invalid visual references fail closed',()=>{
  const broken=structuredClone(spec);
  broken.transitions[0].highlights[0].nodeId='missing';
  assert.throws(()=>validateExpressionRewrite(broken),/invalid highlight/);
});
test('render four beats, condition and complete chains without literal q08 constants',()=>{
  const html=context.ExpressionRewrite.render(spec,s=>s);
  assert.equal((html.match(/class="er-frame"/g)||[]).length,4);
  assert.match(html,/通分显条件/);
  assert.match(html,/data-er="replay"/);
  assert.match(html,/er-highlight/);
  const source=fs.readFileSync(new URL('site/assets/js/expression-rewrite.js',base),'utf8');
  assert.doesNotMatch(source,/2\*a|a\*b|8\/|最小值|定积/);
});
test('text and tree leaves are escaped',()=>{
  const unsafe=structuredClone(spec);
  unsafe.title='<img src=x onerror=alert(1)>';
  const html=context.ExpressionRewrite.render(unsafe,s=>s);
  assert.doesNotMatch(html,/<img/);
  assert.match(html,/&lt;img/);
});
test('next previous replay and static all operate independently of outer lesson',()=>{
  const frames=spec.beats.map((_,i)=>({dataset:{frame:String(i)},hidden:i!==0}));
  const nodes={'.er-progress':{},'[data-er="prev"]':{},'[data-er="next"]':{}};
  const figure={dataset:{count:'4',beat:'0'},querySelectorAll:()=>frames,querySelector:s=>nodes[s]};
  context.ExpressionRewrite.move(figure,'next');
  assert.equal(figure.dataset.beat,'1'); assert.equal(frames[1].hidden,false);
  context.ExpressionRewrite.move(figure,'prev'); assert.equal(figure.dataset.beat,'0');
  context.ExpressionRewrite.move(figure,'all'); assert.ok(frames.every(f=>!f.hidden));
  context.ExpressionRewrite.move(figure,'replay'); assert.equal(frames.filter(f=>!f.hidden).length,1);
});
test('compiled preview includes reusable assets and narrow-screen overflow rules',()=>{
  const html=fs.readFileSync(new URL('site/previews/inequality-basic-q08-organize.html',base),'utf8');
  assert.match(html,/expression-rewrite\.js/); assert.match(html,/expression-rewrite\.css/);
  const css=fs.readFileSync(new URL('site/assets/css/expression-rewrite.css',base),'utf8');
  assert.match(css,/overflow-x/); assert.match(css,/@media/);
});
