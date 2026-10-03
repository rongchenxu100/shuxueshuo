"""Chapter 2: two routes, prerequisites, universal quantifier and inclusive endpoints."""
import asyncio
import html
import json
import os
import re
import subprocess

import pytest
from fastapi.testclient import TestClient
from shuxueshuo_server.tutor_demo.api import create_app
from shuxueshuo_server.tutor_demo.llm import Proposal
from shuxueshuo_server.tutor_demo.session import Event, Session, load_lesson
from .test_local_practice import ROOT, operation, pending
from .test_q11 import local_replay, template
from .test_tutor_demo import Tutor

CARD = 'class="problem-card"'
ID = 'quadratic-always-q01'


@pytest.mark.live_llm
@pytest.mark.skipif(os.getenv('RUN_TUTOR_LIVE') != '1', reason='Explicit live opt-in')
def test_live_parameter_separation_dialogue():
    from .reciprocal_live import replay

    turns = [
        ('参数没分离，要先移项再除以含x的式子，符号不确定。', 0, False,
         [('method', 'extremum'), ('fill', 'movable', 0), ('fill', 'unknown_sign', 1)], []),
        ('为什么我刚才的选择不对？只解释，不替我提交。', 0, True, [], []),
        ('左边只含x，右边只含a，固定a以后右侧与x无关。', 1, False, [], ['fixed_parameter_side']),
        ('恒成立就是右侧不小于左侧最小值。', 1, False, [('choice', 'min')], []),
        ('如果改成存在一个x成立，也是和最大值比较吗？只是问问。', 1, True, [], []),
        ('对所有x成立，所以c必须大于等于f的最大值。', 2, False, [], ['maximum_comparison']),
        ('我配成3-(x-1)^2，对吗？只帮我展开检查。', 2, True,
         [('fill', '3', 0), ('fill', '1', 1), ('submit',)], []),
        ('应该是4-(x-1)^2，x=1时最大值是4。', 3, False, [], ['maximum_value']),
        ('a小于等于-1或者大于等于4。', 4, False, [], ['parameter_range']),
        ('只代x=1检查端点，就能说明对所有x成立吗？', 4, True, [], []),
        ('两个端点都使右侧等于4，而左侧为4-(x-1)^2，对所有实数都不超过4，所以都保留。', 5, False, [], ['boundary_valid']),
    ]
    view = asyncio.run(replay(ID, turns))
    # A real reply previously gave the right expansion but called -2x correct.
    assert not any(re.search(r'一次项[^。；]*-2x[^。；]*(?:没问题|正确|对的)', m['text'])
                   for m in view['messages'] if m['role'] == 'assistant')


@pytest.mark.live_llm
@pytest.mark.skipif(os.getenv('RUN_TUTOR_LIVE') != '1', reason='Explicit live opt-in')
def test_live_discriminant_dialogue():
    from .reciprocal_live import replay

    turns = [
        ('二次项系数是a平方，所以可能为零。', 0, False, [('method', 'discriminant')], []),
        ('题目要求对全体实数x成立。', 0, False, [], ['all_real_domain']),
        ('关于x的二次项系数是-1，确定非零。', 1, False, [], ['nonzero_quadratic']),
        ('移项后x²-2x+a²-3a-3≥0。', 2, False, [], ['equivalent_quadratic']),
        ('相切也可以吗？只是问原因。', 2, True, [('choice', 'strict_above')], []),
        ('整条图像不低于横轴，可以在上方，也允许相切。', 3, False, [], ['nonnegative_graph']),
        ('判别式必须严格小于0。', 3, False, [('choice', 'lt')], []),
        ('相切对应等于0，不相交对应小于0，所以判别式≤0。', 4, False, [], ['discriminant_nonpositive']),
        ('a≤-1或a≥4。', 5, False, [], ['parameter_range']),
        ('a=-1和a=4时都化为(x-1)²≥0，对所有x成立，所以两个端点保留。', 6, False, [], ['boundary_valid']),
    ]
    asyncio.run(replay(ID, turns))

def page():
    text = (ROOT / 'site/2/q01/index.html').read_text()
    return text, json.loads(re.search(r'id="practice-config">\s*(.*?)</script>', text, re.S)[1])

def choose(value):
    return [operation('choice', value), operation('submit')]

def check(first, second):
    return [operation('fill', first, 0), operation('fill', second, 1), operation('submit')]

def actions():
    return ([operation('method', 'discriminant'), operation('fill', 'interval', 0),
             operation('fill', 'maybe_zero', 1), operation('submit'),
             operation('fill', 'all_real', 0), operation('submit'),
             operation('fill', 'nonzero', 1), operation('submit')]
            + choose('constant') + choose('nonnegative')
            + choose('strict_above') + choose('above_or_touch')
            + choose('lt') + choose('le') + choose('inside') + choose('outside')
            + check('fails', 'fails') + check('holds', 'holds')
            + [operation('switch_route', 'extremum')]
            + check('movable', 'unknown_sign') + check('separated', 'no_division')
            + choose('min') + choose('one_point') + choose('max')
            + check('3', '1') + check('4', '1')
            + choose('open') + choose('outside') + check('holds', 'fails') + check('holds', 'holds'))

def test_contract_templates_math_and_unique_chapter_id():
    text, config = page()
    lesson = load_lesson(ID)
    for key in ('id', 'version', 'methods'):
        assert config[key] == lesson[key]
    assert load_lesson('q01')['id'] != ID
    ids = re.findall(r'\bid="([^"]+)"', text)
    assert len(ids) == len(set(ids))
    for route, nodes in config['routes'].items():
        for node, expected in zip(nodes, lesson['routes'][route]['nodes'], strict=True):
            for key in ('id', 'title', 'question', 'interaction', 'expected_answer', 'feedback'):
                assert node[key] == expected[key]
            for ref in [node['display'], *node.get('preview', {}).values(), *([node['board']] if 'board' in node else [])]:
                assert template(text, ref)
    shared = {route: next(n for n in nodes if n['id'].endswith('_range')) for route, nodes in config['routes'].items()}
    assert shared['discriminant']['board'] == shared['extremum']['board']
    assert 'href="/2/"' in text
    assert len(lesson['initial_state']['pairs']) == 6
    def strings(value):
        if isinstance(value, str): return [value]
        if isinstance(value, list): return sum((strings(v) for v in value), [])
        if isinstance(value, dict): return sum((strings(v) for v in value.values()), [])
        return []
    sources = [html.unescape(s) for s in re.findall(r'data-math-text>(.*?)</', text, re.S)] + strings(config) + strings(lesson)
    formulas = [f for s in sources for f in re.findall(r'\$([^$]+)\$', s)]
    script = "const katex=require(process.argv[1]);for(const f of JSON.parse(require('fs').readFileSync(0,'utf8')))katex.renderToString(f,{throwOnError:true});"
    subprocess.run(['node','-e',script,str(ROOT/'site/assets/practice/vendor/katex-0.18.9/katex.min.js')],input=json.dumps(formulas),text=True,capture_output=True,check=True)

def test_wrong_answers_corrections_and_route_switch_match_server():
    ops = pending(actions())
    local = local_replay(page()[1], ops)
    async def run():
        session, tutor = Session(load_lesson(ID)), Tutor()
        errors = set()
        for expected, op in zip(local, ops, strict=True):
            before = session.state['active']
            result = await session.handle(Event(**op, revision=session.revision, kind='ui'), tutor)
            assert result['state'] == expected['state']
            if result['state']['feedback']:
                assert result['state']['active'] == before
                errors.add((result['state']['method'], before))
        assert errors == {('discriminant', i) for i in range(6)} | {('extremum', i) for i in range(5)}
        assert result['state']['active'] == 5
        assert len(result['attempts']) == 2
        assert all(a['status'] == 'completed' for a in result['attempts'])
        assert not tutor.calls
    asyncio.run(run())

def test_dialogue_sync_partial_evidence_questions_and_retry():
    async def run():
        session, tutor = Session(load_lesson(ID)), Tutor()
        tutor.proposal = Proposal(reply='需要两个依据。', intent='question', actions=[], evidence=['all_real_domain','nonzero_quadratic'])
        event = Event(event_id='question', revision=0, kind='text', text='为什么要看二次项系数？',
                      lesson_version=1, pending_operations=pending([operation('method','discriminant')]))
        result = await session.handle(event,tutor)
        assert result['state']['active'] == 0 and result['accepted_evidence'] == []
        assert tutor.calls[-1]['lesson']['id'] == ID
        tutor.proposal = Proposal(reply='范围正确。',intent='answer',actions=[],evidence=['all_real_domain'])
        result = await session.handle(Event(event_id='partial',revision=session.revision,kind='text',text='对所有实数x'),tutor)
        assert result['state']['active'] == 0
        assert result['accepted_evidence'] == ['all_real_domain']
        tutor.proposal = Proposal(reply='系数也正确。',intent='answer',actions=[],evidence=['nonzero_quadratic'])
        event = Event(event_id='finish',revision=session.revision,kind='text',text='二次项系数是-1，不会为零')
        result = await session.handle(event,tutor)
        assert result['state']['active'] == 1
        count = len(tutor.calls)
        assert await session.handle(event,tutor) == result
        assert len(tutor.calls) == count
    asyncio.run(run())

def test_chapter_and_development_mounts():
    with TestClient(create_app(Tutor())) as client:
        home = client.get('/2/').text
        assert home.count('class="type-group"') == 4
        assert home.count('href="/2/q01/"') == 1 and home.count('href="/2/q02/"') == 1
        assert f'<strong>{home.count(CARD)}</strong>' in home
        assert client.get('/2/q01/').status_code == 200
        assert client.get('/1/').status_code == 200
        response = client.post('/api/tutor-demo/sessions',json={'lesson_id':ID})
        assert response.status_code == 201 and response.json()['lesson_id'] == ID
        for path in re.findall(r'(?:href|src)="(/[^"#]+)"', page()[0]):
            if path != '/': assert client.get(path).status_code == 200, path

def test_shared_quadratic_graph_legacy_and_comparison_options():
    script = r'''
const assert=require('node:assert/strict');global.window=global;
require(process.argv[1]);
const base={coefficient:1,vertex:[1,0],bounds:[-2,4,-3,6],xTicks:[[0,'0'],[1,'1']],yLabel:'0',variable:'x',title:'test',description:'test',uid:'test'};
let svg=PracticeComponents.quadraticGraph(base);
assert.ok(svg.includes('quadratic-vertex'));assert.ok(!svg.includes('quadratic-reference'));
svg=PracticeComponents.quadraticGraph({...base,showVertex:false,referenceLines:[{value:2,label:'<c>'}],points:[{x:1,label:'<point>'}]});
assert.ok(svg.includes('quadratic-reference'));assert.ok(svg.includes('quadratic-point'));
assert.ok(!svg.includes('quadratic-vertex'));assert.ok(svg.includes('&lt;c&gt;'));assert.ok(svg.includes('&lt;point&gt;'));
assert.ok(!svg.includes('NaN'));
'''
    subprocess.run(['node','-e',script,str(ROOT/'site/assets/practice/components.js')],text=True,capture_output=True,check=True)

def test_shared_checklist_shows_only_chosen_consequence():
    script = r'''
const assert=require('node:assert/strict');global.window=global;
require(process.argv[1]);
const component={type:'checklist',title:'<前提>',slots:[
  {label:'范围',hint:'<看题>',options:[{value:'a',label:'甲',note:'<甲的后果>'},{value:'b',label:'乙',note:'乙的后果'}]},
  {label:'系数',options:[{value:'c',label:'丙'},{value:'d',label:'丁'}]}]};
let html=PracticeComponents.checklist({component,pair:['','']});
assert.ok(html.includes('已看 0 / 2'));assert.ok(!html.includes('checklist-note'));assert.ok(!html.includes('answered'));
assert.ok(html.includes('&lt;前提&gt;'));assert.ok(html.includes('&lt;看题&gt;'));
assert.equal((html.match(/data-pair-answer="1"/g)||[]).length,2);
html=PracticeComponents.checklist({component,pair:['a','']});
assert.ok(html.includes('已看 1 / 2'));assert.ok(html.includes('&lt;甲的后果&gt;'));assert.ok(!html.includes('乙的后果'));
assert.ok(html.includes('data-value="a" aria-pressed="true"'));assert.ok(html.includes('data-value="b" aria-pressed="false"'));
assert.equal((html.match(/checklist-row answered/g)||[]).length,1);
'''
    subprocess.run(['node','-e',script,str(ROOT/'site/assets/practice/components.js')],text=True,capture_output=True,check=True)

def test_quadratic_graph_marks_sign_and_axis_points():
    script = r'''
const assert=require('node:assert/strict');global.window=global;
require(process.argv[1]);
const base={coefficient:1,bounds:[-2,4,-3,6],xTicks:[],yLabel:'',variable:'x',title:'t',description:'d',uid:'u',showVertex:false};
const count=(svg,name)=>(svg.match(new RegExp(`class="${name}"`,'g'))||[]).length;
let svg=PracticeComponents.quadraticGraph({...base,vertex:[1,-1.5]});
assert.equal(count(svg,'quadratic-negative-band'),0);assert.equal(count(svg,'quadratic-root'),0);
svg=PracticeComponents.quadraticGraph({...base,vertex:[1,-1.5],markSign:true});
assert.equal(count(svg,'quadratic-negative-band'),1);assert.equal(count(svg,'quadratic-negative'),1);assert.equal(count(svg,'quadratic-root'),2);
svg=PracticeComponents.quadraticGraph({...base,vertex:[1,0],markSign:true});
assert.equal(count(svg,'quadratic-negative'),0);assert.equal(count(svg,'quadratic-root'),1);
svg=PracticeComponents.quadraticGraph({...base,vertex:[1,1],markSign:true});
assert.equal(count(svg,'quadratic-negative'),0);assert.equal(count(svg,'quadratic-root'),0);
assert.ok(!svg.includes('NaN'));
'''
    subprocess.run(['node','-e',script,str(ROOT/'site/assets/practice/components.js')],text=True,capture_output=True,check=True)

def test_quadratic_graph_draws_solution_intervals():
    script = r'''
const assert=require('node:assert/strict');global.window=global;
require(process.argv[1]);
const base={coefficient:1,vertex:[1.5,-6.25],bounds:[-2.5,5.5,-7.5,7.5],xTicks:[],yLabel:'',variable:'a',title:'t',description:'d',uid:'u',showVertex:false,markSign:true};
const count=(svg,name)=>(svg.match(new RegExp(`class="${name}"`,'g'))||[]).length;
let svg=PracticeComponents.quadraticGraph({...base,solution:{intervals:[[null,-1],[4,null]],closed:true}});
assert.equal(count(svg,'quadratic-solution'),2);assert.equal(count(svg,'quadratic-endpoint'),2);assert.equal(count(svg,'quadratic-root'),0);
assert.ok(svg.includes('fill="#087f79" stroke="#087f79"'));
svg=PracticeComponents.quadraticGraph({...base,solution:{intervals:[[null,-1],[4,null]],closed:false}});
assert.ok(!svg.includes('fill="#087f79" stroke="#087f79"'));
svg=PracticeComponents.quadraticGraph({...base,solution:{intervals:[[-1,4]],closed:true}});
assert.equal(count(svg,'quadratic-solution'),1);assert.equal(count(svg,'quadratic-endpoint'),2);
assert.ok(!svg.includes('NaN'));
'''
    subprocess.run(['node','-e',script,str(ROOT/'site/assets/practice/components.js')],text=True,capture_output=True,check=True)

def test_checklist_renders_optional_board_first():
    script = r'''
const assert=require('node:assert/strict');global.window=global;
require(process.argv[1]);
const component={type:'checklist',slots:[{label:'x',options:[{value:'a',label:'甲'}]}]};
assert.ok(!PracticeComponents.checklist({component,pair:['']}).includes('BOARD'));
const html=PracticeComponents.checklist({component,pair:[''],board:'<div>BOARD</div>'});
assert.ok(html.startsWith('<div>BOARD</div><div class="checklist">'));
'''
    subprocess.run(['node','-e',script,str(ROOT/'site/assets/practice/components.js')],text=True,capture_output=True,check=True)

def test_every_completed_step_keeps_exam_derivation():
    text, config = page()
    for nodes in config['routes'].values():
        for node in nodes:
            body = template(text, node['display'])
            assert '<summary>完整推导</summary>' in body, node['id']
            assert f'id="{{{{uid}}}}-{node["id"]}-derivation"' in body, node['id']

def test_completing_square_attempts_cover_every_combination():
    text, config = page()
    node = next(n for n in config['routes']['extremum'] if n['id'] == 'e_extremum')
    terms = node['interaction']['terms']
    calculations = node['attempt_calculations']
    assert sorted(calculations) == sorted(terms)
    for first in terms:
        assert sorted(calculations[first]) == sorted(terms)
        for second in terms:
            assert template(text, calculations[first][second])
    assert calculations['4']['1'] == node['display']
