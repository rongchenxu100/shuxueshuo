"""Chapter 2 Q05: existence on an open interval, the variant of Q04 (有解 means 存在)."""
import asyncio
import html
import json
import math
import os
import re
import subprocess

import pytest
from fastapi.testclient import TestClient
from shuxueshuo_server.tutor_demo.api import create_app
from shuxueshuo_server.tutor_demo.session import Event, Session, load_lesson
from .test_local_practice import ROOT, operation, pending
from .test_q11 import local_replay, template
from .test_tutor_demo import Tutor

CARD = 'class="problem-card"'
ID = 'quadratic-always-q05'


@pytest.mark.live_llm
@pytest.mark.skipif(os.getenv('RUN_TUTOR_LIVE') != '1', reason='Explicit live opt-in')
def test_live_existence_dialogue():
    from .reciprocal_live import replay

    turns = [
        ('x只在(1,2)上取值。', 1, False, [('method', 'interval')], ['interval_domain']),
        ('要求最小值大于0。', 1, False, [('choice', 'min')], []),
        ('有解是什么意思？只解释。', 1, True, [], []),
        ('有解就是存在一个x满足，只要区间上最高处在横轴上方，也就是取值范围的上端大于0。', 2, False, [], ['existence_upper_condition']),
        ('开口向上，离对称轴越远的端点越高，所以对称轴要和区间中点3/2比较。', 2, False, [], ['midpoint_split']),
        ('m≥-3时上端是f(2)；m<-3时上端是f(1)，端点取不到。', 3, False, [], ['left_case_upper', 'right_case_upper']),
        ('情况①得m≥-3，情况②得-5<m<-3，取并集得m>-5。', 4, False, [], ['merged_range']),
        ('m=-5时(x-1)(x-4)在(1,2)内都小于0，没有解，所以排除。', 5, False, [], ['boundary_excluded']),
    ]
    asyncio.run(replay(ID, turns))


@pytest.mark.live_llm
@pytest.mark.skipif(os.getenv('RUN_TUTOR_LIVE') != '1', reason='Explicit live opt-in')
def test_live_separation_open_interval_and_partial_evidence():
    from .reciprocal_live import replay

    turns = [
        ('x只在(1,2)上取值。', 1, False, [('method', 'interval')], ['interval_domain']),
        ('移项后可以分离m。', 0, False, [('switch_route', 'extremum')], []),
        ('含m的只有mx，移项再除以x；x在(1,2)上为正，不等号不变向。', 1, False, [], ['separable_with_positive_divisor']),
        ('两边除以x后不等号变向，m<-(x+4/x)。', 1, False, [('choice', 'flip')], []),
        ('x>0，不等号不变向，得到m>-(x+4/x)。', 2, False, [], ['separated_inequality']),
        ('只要水平线y=-m下方有h的图像就有解，比如m=-5时h<5，所以m=-5可以。', 2, False, [('choice', 'min')], []),
        ('有解需要m大于h下端的相反数，也就是m>-4。', 2, False, [], []),
        ('这里到底看h的上端还是-h的下端？只解释。', 2, True, [], []),
        ('只需有一点h(x)>-m，就是-m小于h的取值上端，等价于m大于-h的取值下端。', 3, False, [], ['existence_upper_comparison']),
        ('最低点在(4,5)。', 3, False, [('fill', 'low_4', 0)], []),
        ('x=4/x且x>0得x=2，最低点(2,4)。', 3, False, [], ['hook_lowest_point']),
        ('x趋近0的正侧时，4/x越来越大，图像贴近y轴向上。', 3, False, [], ['hook_near_y_axis']),
        ('4/x趋于0，所以x趋于无穷时h也趋于0。', 3, False, [('fill', 'fall', 2)], []),
        ('h-x=4/x趋于0，所以x趋于正无穷时图像贴近y=x。', 4, False, [], ['hook_near_line']),
        ('(1,2)在最低点x=2的左侧，h在这段单调递减。', 4, False, [], ['left_of_lowest']),
        ('两端分别算出5和4，所以值域是[4,5]。', 4, False, [('fill', 'closed', 1)], []),
        ('为什么端点取不到却还能用4和5？只解释。', 4, True, [], []),
        ('x=1和2都不在区间内，函数值可无限接近5和4但取不到，值域是(4,5)。', 5, False, [], ['open_range']),
        ('m=-5时，x=1能使原式等于0，因此可以保留。', 5, False, [('fill', 'holds', 0)], []),
        ('x=1不满足，所以一定无解。', 5, False, [], []),
        ('m=-5时，对所有1<x<2，x-1>0、x-4<0，乘积为负，不存在使原式>0的x，所以排除。', 6, False, [], ['boundary_excluded']),
    ]
    view = asyncio.run(replay(ID, turns))
    assert len(view['attempts']) == 2 and view['attempts'][-1]['status'] == 'completed'
    messages = view['messages']
    index = next(i for i, message in enumerate(messages) if message.get('text') == turns[5][0])
    reply = messages[index + 1]['text']
    assert '上方' in reply, reply
    assert any(word in reply for word in ('无解', '不成立', '不能', '不满足', '不可以')), reply


def page():
    text = (ROOT / 'site/2/q05/index.html').read_text()
    return text, json.loads(re.search(r'id="practice-config">\s*(.*?)</script>', text, re.S)[1])

def choose(value):
    return [operation('choice', value), operation('submit')]

def check(*values):
    return [operation('fill', value, i) for i, value in enumerate(values)] + [operation('submit')]

def actions():
    return ([operation('method', 'interval')]
            + check('all_real') + check('interval')
            + choose('min') + choose('one_point') + choose('max')
            + check('endpoints', 'f1', 'f2') + check('midpoint', 'f2', 'f1')
            + choose('second_only') + choose('always') + choose('union')
            + check('holds') + check('fails')
            + [operation('switch_route', 'extremum')]
            + check('separated', 'no_division') + check('movable', 'fixed_sign')
            + choose('flip') + choose('partial') + choose('keep')
            + choose('min') + choose('one_point') + choose('max')
            + check('low_4', 'x_axis', 'flat') + check('low_2', 'y_axis', 'line')
            + check('right', 'closed') + check('left', 'open')
            + check('holds') + check('fails'))

def specs(text, kind):
    return [json.loads(html.unescape(s)) for s in re.findall(rf'data-{kind}="([^"]+)"', text)]

def node(route, node_id):
    return next(n for n in page()[1]['routes'][route] if n['id'] == node_id)

def test_contract_templates_math_and_page_ids():
    text, config = page()
    lesson = load_lesson(ID)
    for key in ('id', 'version', 'methods'):
        assert config[key] == lesson[key]
    ids = re.findall(r'\bid="([^"]+)"', text)
    assert len(ids) == len(set(ids))
    assert len(lesson['initial_state']['pairs']) == max(len(nodes) for nodes in config['routes'].values())
    for route, nodes in config['routes'].items():
        for item, expected in zip(nodes, lesson['routes'][route]['nodes'], strict=True):
            for key in ('id', 'title', 'question', 'interaction', 'expected_answer', 'feedback'):
                assert item[key] == expected[key]
            for ref in [item['display'], *([item['board']] if 'board' in item else [])]:
                assert template(text, ref)
            body = template(text, item['display'])
            assert '<summary>完整推导</summary>' in body and f'id="{{{{uid}}}}-{item["id"]}-derivation"' in body
    boundary = {route: nodes[-1] for route, nodes in config['routes'].items()}
    assert boundary['interval']['interaction'] == boundary['extremum']['interaction']
    assert boundary['interval']['board'] == boundary['extremum']['board'] == 'boundary-board'
    assert 'href="/2/"' in text and 'Q05' in text
    def strings(value):
        if isinstance(value, str): return [value]
        if isinstance(value, list): return sum((strings(v) for v in value), [])
        if isinstance(value, dict): return sum((strings(v) for v in value.values()), [])
        return []
    sources = [html.unescape(s) for s in re.findall(r'data-math-text>(.*?)</', text, re.S)] + strings(config) + strings(lesson)
    formulas = [f for s in sources for f in re.findall(r'\$([^$]+)\$', s)]
    script = "const katex=require(process.argv[1]);for(const f of JSON.parse(require('fs').readFileSync(0,'utf8')))katex.renderToString(f,{throwOnError:true});"
    subprocess.run(['node','-e',script,str(ROOT/'site/assets/practice/vendor/katex-0.18.9/katex.min.js')],input=json.dumps(formulas),text=True,capture_output=True,check=True)

def test_existence_is_stated_and_contrasted_with_always():
    text, config = page()
    assert '有解即存在：$\\exists x\\in(1,2),$' in text
    for route, step in (('interval', 'i_condition'), ('extremum', 'e_condition')):
        item = node(route, step)
        assert item['question'].startswith('要使存在 $x\\in(1,2)$，使 ')
        labels = {o['value']: o['label'] for o in item['interaction']['options']}
        assert '上端' in labels['max'] and '下端' in labels['min'], 'the always-true reading is the distractor'
    labels = {o['value']: o['label'] for o in node('interval', 'i_range')['interaction']['options']}
    assert labels['always'] == '$m\\ge-4$', 'the always-true answer is offered as a distractor'
    assert [n['id'] for n in config['routes']['extremum']] == ['e_basis', 'e_separate', 'e_condition', 'e_graph', 'e_extremum', 'e_boundary']
    assert node('extremum', 'e_condition')['question'] == '要使存在 $x\\in(1,2)$，使 $m>-h(x)$，$m$ 应满足哪个条件？'
    comparison = node('extremum', 'e_condition')
    assert '上方' in comparison['feedback']['answer']
    assert '下方' not in comparison['feedback']['answer']
    # The negative sign applies to the bound of h, not to the function whose
    # bound is being taken. Preserve this grouping in both options.
    for option in comparison['interaction']['options'][:2]:
        assert r'-\bigl(h(x)\text{' in option['label']
        assert r'\bigr)' in option['label']

def test_every_wrong_answer_blocks_and_local_matches_server():
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
        assert errors == {('interval', i) for i in range(5)} | {('extremum', i) for i in range(6)}
        assert result['state']['active'] == 6
        assert len(result['attempts']) == 2 and all(a['status'] == 'completed' for a in result['attempts'])
        assert not tutor.calls
    asyncio.run(run())

def test_graphs_are_instances_with_open_endpoints():
    text, _ = page()
    parabolas, hooks, explorers = specs(text, 'quadratic-graph'), specs(text, 'reciprocal-sum-graph'), specs(text, 'axis-explorer')
    assert parabolas and hooks and len(explorers) == 3
    for spec in parabolas:
        m = -2 * spec['vertex'][0]
        assert spec['coefficient'] == 1 and math.isclose(spec['vertex'][1], 4 - m * m / 4), spec['uid']
        assert spec['interval'] == [1, 2] and 'markSign' not in spec
        assert f'm = {m:g}'.replace('-', '−') in spec['title'], spec['uid']
    for spec in hooks:
        assert (spec['a'], spec['b']) == (1, 4), spec['uid']
        assert spec.get('interval') == [1, 2] or spec.get('asymptotes'), spec['uid']
    for spec in parabolas + hooks:
        if spec.get('interval'):
            assert all(p.get('open') for p in spec.get('points', []) if p['x'] in (1, 2)), 'endpoints of (1,2) are not attained'
    for spec in explorers:
        assert (spec['coefficient'], spec['constant'], spec['interval'], spec['open']) == (1, 4, [1, 2], True)
        assert spec['marks'] == [{'x': 1.5, 'label': '3/2'}]
    item = node('interval', 'i_extremum')
    [board] = specs(template(text, item['board']), 'axis-explorer')
    assert board['axis']['min'] < 1 and 2 < board['axis']['max']
    left, right = (spec['axis'] for spec in specs(template(text, item['display']), 'axis-explorer'))
    assert left['max'] == 1.5 and right['min'] > 1.5
    board = template(text, node('interval', 'i_range')['board'])
    assert 'f(2)=2m+8&gt;0' in board and 'f(1)=m+5&gt;0' in board
    assert '$m&gt;\\boxed{-5}$' in template(text, 'boundary-board')

def test_open_endpoints_render_hollow():
    script = r'''
const assert=require('node:assert/strict');global.window=global;
require(process.argv[1]);
const UI=PracticeComponents;
const spec={coefficient:1,constant:4,axis:{min:0.5,max:3,step:0.05,value:1},interval:[1,2],open:true,
  bounds:[-0.6,4.6,-5.8,7],marks:[{x:1.5,label:'3/2'}],variable:'x',title:'t',description:'d',uid:'u'};
let layer=UI.axisExplorerLayer(spec,1);
assert.ok(layer.includes('>上端</text>')&&!layer.includes('>最高</text>'));
assert.ok(!/class="axis-endpoint[^"]*"[^>]*fill="#b65c42"/.test(layer), 'open endpoints stay hollow');
layer=UI.axisExplorerLayer({...spec,open:false},1);
assert.ok(layer.includes('>最高</text>')&&/class="axis-endpoint highest"[^>]*fill="#b65c42"/.test(layer));
const hook={a:1,b:4,bounds:[-0.3,4.7,-0.6,7.4],interval:[1,2],title:'t',description:'d',uid:'h'};
let svg=UI.reciprocalSumGraph({...hook,points:[{x:1,label:'a',open:true},{x:2,label:'b'}]});
assert.equal((svg.match(/class="graph-point"[^>]*fill="#fff"/g)||[]).length,1);
svg=UI.quadraticGraph({coefficient:1,vertex:[2.5,-2.25],bounds:[-0.6,4.6,-5.8,4.8],xTicks:[],yLabel:'',variable:'x',title:'t',description:'d',uid:'q',showVertex:false,interval:[1,2],points:[{x:1,label:'a',open:true}]});
assert.ok(/class="quadratic-point"[^>]*fill="#fff"/.test(svg));
'''
    subprocess.run(['node','-e',script,str(ROOT/'site/assets/practice/components.js')],text=True,capture_output=True,check=True)

def test_chapter_lists_and_serves_q05():
    with TestClient(create_app(Tutor())) as client:
        home = client.get('/2/').text
        assert home.count('href="/2/q05/"') == 1 and f'<strong>{home.count(CARD)}</strong>' in home
        group = home[home.index('id="group-interval"'):home.index('id="group-separation"')]
        assert group.index('href="/2/q04/"') < group.index('href="/2/q05/"') and '<span class="type-count">2 题</span>' in group
        assert client.get('/2/q05/').status_code == 200
        response = client.post('/api/tutor-demo/sessions', json={'lesson_id': ID})
        assert response.status_code == 201 and response.json()['lesson_id'] == ID
        for path in re.findall(r'(?:href|src)="(/[^"#]+)"', page()[0]):
            if path != '/': assert client.get(path).status_code == 200, path
