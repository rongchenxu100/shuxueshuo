"""Chapter 2 Q06: separating the parameter means dividing by x < 0, so the inequality flips."""
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
ID = 'quadratic-always-q06'
R2 = round(math.sqrt(2), 4)


@pytest.mark.live_llm
@pytest.mark.skipif(os.getenv('RUN_TUTOR_LIVE') != '1', reason='Explicit live opt-in')
def test_live_negative_divisor_dialogue():
    from .reciprocal_live import replay

    turns = [
        ('移项就可以分离a。', 0, False, [('method', 'extremum')], []),
        ('含a的只有ax，移项后除以x就能分离，x<0符号确定。', 1, False, [], ['separable_with_negative_divisor']),
        ('两边除以x得a≥-x-2/x。', 1, False, [('choice', 'keep')], []),
        ('x是负数，除以负数要变号，所以a≤-x-2/x。', 2, False, [], ['separated_inequality']),
        ('检查x=-1，a≤3就可以保证恒成立。', 2, False, [('choice', 'one_point')], []),
        ('为什么不能只看x=-1？只解释。', 2, True, [], []),
        ('所有x<0都要满足，只需a不超过h(x)的最小值。', 3, False, [], ['minimum_comparison']),
        ('最低点在(√2,2√2)。', 3, False, [('fill', 'low_pos', 0)], []),
        ('-x与-2/x都是正数，积为2，和至少2√2，取等时x=-√2，最低点(-√2,2√2)。', 3, False, [], ['hook_lowest_point']),
        ('x从左侧趋于0时，-2/x趋于正无穷，贴近y轴向上。', 3, False, [], ['hook_near_y_axis']),
        ('x趋于负无穷时-2/x趋于0，所以h趋于0。', 3, False, [('fill', 'flat', 2)], []),
        ('h(x)-(-x)=-2/x趋于0，所以左端贴近y=-x。', 4, False, [], ['hook_near_line']),
        ('这是开区间，没有最小值。', 4, False, [('fill', 'none', 1)], []),
        ('(-∞,0)在最低点左侧，h(x)一直下降。', 4, False, [('fill', 'left', 0)], []),
        ('-√2在(-∞,0)内，区间在最低点两侧都有，先降后升。', 4, False, [], ['lowest_inside']),
        ('最小值是h(-√2)=2√2。', 5, False, [], ['minimum_value']),
        ('边界使函数取到0，所以应该排除。', 5, False, [('fill', 'fails', 0)], []),
        ('x=-√2时等于0，满足≥0，所以可以保留边界。', 5, False, [], []),
        ('a=2√2时原式是(x+√2)²，对所有x<0都非负，≥允许等号，所以保留。', 6, False, [], ['boundary_included']),
    ]
    view = asyncio.run(replay(ID, turns))
    messages = view['messages']
    for turn in (8, 9, 10):
        index = next(i for i, message in enumerate(messages) if message.get('text') == turns[turn][0])
        reply = messages[index + 1]['text']
        assert '改选' not in reply, reply  # The lowest point has already been corrected in text.


@pytest.mark.live_llm
@pytest.mark.skipif(os.getenv('RUN_TUTOR_LIVE') != '1', reason='Explicit live opt-in')
def test_live_interval_endpoint_value_and_switch():
    from .reciprocal_live import replay

    turns = [
        ('含a的项是ax，移项后除以x，x<0要变号。', 1, False, [('method', 'extremum')], ['separable_with_negative_divisor']),
        ('x取全体实数。', 0, False, [('switch_route', 'interval')], []),
        ('只要求对x<0，即(-∞,0)上恒成立。', 1, False, [], ['interval_domain']),
        ('只要f(-1)≥0。', 1, False, [('choice', 'one_point')], []),
        ('需要f在(-∞,0)上的取值下端≥0。', 2, False, [], ['lower_end_condition']),
        ('开口向上，顶点总是最低，所以不用比较区间。', 2, False, [('fill', 'vertex_always', 0)], []),
        ('要把对称轴和端点0比较，看顶点是否在x<0内。', 2, False, [], ['endpoint_split']),
        ('a>0时虽然0取不到，但是x=-a也有f(-a)=2，所以2可以取到吧？只解释。', 2, True, [('fill', 'f0', 2)], []),
        ('a=0时，x=0取得最小值2。', 2, False, [], []),
        ('a≤0时轴在0或右侧，负半轴上递减，下端2但取不到，包括a=0也没有最小值。', 2, False, [], ['right_case_lower']),
        ('a>0时顶点-a/2在区间内，下端为最小值2-a²/4；2虽可在-a处取到，却不是下端。', 3, False, [], ['left_case_lower']),
        ('只解2-a²/4≥0，得-2√2≤a≤2√2。', 3, False, [('choice', 'vertex_only')], []),
        ('a≤0都满足；a>0时交集得0<a≤2√2，两支并集为a≤2√2。', 4, False, [], ['merged_range']),
        ('a=2√2时x=-√2使原式为0，所以排除。', 4, False, [('fill', 'fails', 0)], []),
        ('a=2√2时原式为(x+√2)²≥0，对整个x<0都成立，所以保留。', 5, False, [], ['boundary_included']),
    ]
    view = asyncio.run(replay(ID, turns))
    assert len(view['attempts']) == 2 and view['attempts'][-1]['status'] == 'completed'


def page():
    text = (ROOT / 'site/2/q06/index.html').read_text()
    return text, json.loads(re.search(r'id="practice-config">\s*(.*?)</script>', text, re.S)[1])

def choose(value):
    return [operation('choice', value), operation('submit')]

def check(*values):
    return [operation('fill', value, i) for i, value in enumerate(values)] + [operation('submit')]

def actions():
    return ([operation('method', 'extremum')]
            + check('separated', 'no_division') + check('movable', 'fixed_sign')
            + choose('keep') + choose('partial') + choose('flip')
            + choose('max') + choose('one_point') + choose('min')
            + check('low_pos', 'x_axis', 'flat') + check('low_neg', 'y_axis', 'line')
            + check('left', 'none') + check('around', 'vertex')
            + check('fails') + check('holds')
            + [operation('switch_route', 'interval')]
            + check('all_real') + check('interval')
            + choose('max') + choose('one_point') + choose('min')
            + check('vertex_always', 'vertex', 'vertex') + check('endpoint', 'f0', 'vertex')
            + choose('second_only') + choose('vertex_only') + choose('union')
            + check('fails') + check('holds'))

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
    assert 'href="/2/"' in text and 'Q06' in text
    def strings(value):
        if isinstance(value, str): return [value]
        if isinstance(value, list): return sum((strings(v) for v in value), [])
        if isinstance(value, dict): return sum((strings(v) for v in value.values()), [])
        return []
    sources = [html.unescape(s) for s in re.findall(r'data-math-text>(.*?)</', text, re.S)] + strings(config) + strings(lesson)
    formulas = [f for s in sources for f in re.findall(r'\$([^$]+)\$', s)]
    script = "const katex=require(process.argv[1]);for(const f of JSON.parse(require('fs').readFileSync(0,'utf8')))katex.renderToString(f,{throwOnError:true});"
    subprocess.run(['node','-e',script,str(ROOT/'site/assets/practice/vendor/katex-0.18.9/katex.min.js')],input=json.dumps(formulas),text=True,capture_output=True,check=True)

def test_negative_divisor_flips_and_the_minimum_is_attained():
    text, config = page()
    assert [m['id'] for m in config['methods']] == ['extremum', 'interval'], 'separation is the main route'
    separate = node('extremum', 'e_separate')
    labels = {o['value']: o['label'] for o in separate['interaction']['options']}
    assert separate['expected_answer'] == {'one_of': ['flip']} and labels['flip'] == '$a\\le-x-\\frac2x$'
    assert labels['keep'] == '$a\\ge-x-\\frac2x$', 'forgetting to flip is the distractor'
    assert '不等号方向改变' in template(text, separate['display'])
    condition = node('extremum', 'e_condition')
    assert condition['title'] == '转化为最值条件' and condition['expected_answer'] == {'one_of': ['min']}
    interval = node('interval', 'i_condition')
    assert interval['title'] == '转化为范围条件' and '下端' in {o['value']: o['label'] for o in interval['interaction']['options']}['min']
    assert [n['id'] for n in config['routes']['extremum']] == ['e_basis', 'e_separate', 'e_condition', 'e_graph', 'e_extremum', 'e_boundary']
    for route in config['routes'].values():
        assert route[-1]['expected_answer'] == {'terms': ['holds']}, 'a = 2√2 is kept: the inequality is ≥'
    assert '$a\\le\\boxed{2\\sqrt2}$' in template(text, 'boundary-board')
    options = node('interval', 'i_extremum')['interaction']['slots'][2]['options']
    note = next(option['note'] for option in options if option['value'] == 'f0')
    assert '不代表' in note
    # Excluding x=0 does not exclude its function value: f(-a)=f(0)=2 for a>0.
    for a in (0.5, 1, 4):
        x = -a
        assert x < 0 and x*x + a*x + 2 == 2

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
        assert errors == {('extremum', i) for i in range(6)} | {('interval', i) for i in range(5)}
        assert result['state']['active'] == 5
        assert len(result['attempts']) == 2 and all(a['status'] == 'completed' for a in result['attempts'])
        assert not tutor.calls
    asyncio.run(run())

def test_graphs_are_instances_on_the_negative_half_line():
    text, _ = page()
    parabolas, hooks, explorers = specs(text, 'quadratic-graph'), specs(text, 'reciprocal-sum-graph'), specs(text, 'axis-explorer')
    assert len(parabolas) == 1 and hooks and len(explorers) == 3
    [boundary] = parabolas
    assert boundary['vertex'] == [-R2, 0] and boundary['interval'] == [None, 0]
    assert any(p['x'] == 0 and p.get('open') for p in boundary['points']), 'x = 0 is not attained'
    for spec in hooks:
        assert (spec['a'], spec['b'], spec['negative']) == (-1, -2, True), spec['uid']
        assert {'x': -R2, 'label': '(−√2, 2√2)', 'place': 'below-right'} in spec['points']
    assert any(spec.get('asymptotes') for spec in hooks)
    for spec in explorers:
        assert (spec['coefficient'], spec['constant'], spec['interval'], spec['open'], spec['target']) == (1, 2, [None, 0], True, 'min')
    item = node('interval', 'i_extremum')
    [board] = specs(template(text, item['board']), 'axis-explorer')
    assert board['axis']['min'] < 0 < board['axis']['max']
    right, left = (spec['axis'] for spec in specs(template(text, item['display']), 'axis-explorer'))
    assert right['min'] == 0 and left['max'] < 0
    board = template(text, node('interval', 'i_range')['board'])
    assert 'f(0)=2\\ge0' in board and '2-\\frac{a^2}4\\ge0' in board

def test_lowest_point_explorer_and_negative_hook_render():
    script = r'''
const assert=require('node:assert/strict');global.window=global;
require(process.argv[1]);
const UI=PracticeComponents;
const spec={coefficient:1,constant:2,axis:{min:-2.5,max:1.5,step:0.05,value:-1},interval:[null,0],open:true,target:'min',
  bounds:[-4.2,2.2,-4.8,6.4],variable:'x',title:'t',description:'d',uid:'u'};
let layer=UI.axisExplorerLayer(spec,-1);
assert.ok(layer.includes('class="axis-vertex lowest"')&&layer.includes('>最低</text>'), 'a vertex inside the interval is the lowest point');
assert.equal((layer.match(/class="axis-endpoint/g)||[]).length,1, 'an unbounded side has no endpoint');
layer=UI.axisExplorerLayer(spec,0.8);
assert.ok(layer.includes('>下端</text>')&&!layer.includes('axis-vertex lowest'));
assert.ok(/class="axis-endpoint lowest"[^>]*fill="#fff"/.test(layer), 'the open end x = 0 stays hollow');
const svg=UI.axisExplorer(spec);
assert.equal((svg.match(/class="graph-interval" d="M[\d.]+ 48V222"/g)||[]).length,1);
const hook=UI.reciprocalSumGraph({a:-1,b:-2,negative:true,asymptotes:true,bounds:[-5.6,0.9,-0.9,7.6],title:'t',description:'d',uid:'h',points:[{x:-1.4142,label:'p'}]});
const zero=48+5.6/6.5*270;
const xs=[...hook.match(/class="reciprocal-curve" d="([^"]+)"/)[1].matchAll(/[ML]([\d.-]+) /g)].map(m=>+m[1]);
assert.ok(xs.length>100&&xs.every(v=>v<zero), 'only the x < 0 branch is drawn');
assert.ok(hook.includes('y = −x'));
const parabola=UI.quadraticGraph({coefficient:1,vertex:[-1.4142,0],bounds:[-4.2,1.2,-1.2,6.2],xTicks:[],yLabel:'',variable:'x',title:'t',description:'d',uid:'q',showVertex:false,interval:[null,0]});
assert.ok(/class="graph-interval" d="M[\d.]+ 48V222"/.test(parabola)&&!parabola.includes('NaN')&&!parabola.includes('Infinity'));
'''
    subprocess.run(['node','-e',script,str(ROOT/'site/assets/practice/components.js')],text=True,capture_output=True,check=True)

def test_chapter_lists_and_serves_q06():
    with TestClient(create_app(Tutor())) as client:
        home = client.get('/2/').text
        assert home.count('href="/2/q06/"') == 1 and f'<strong>{home.count(CARD)}</strong>' in home
        group = home[home.index('id="group-separation"'):home.index('id="group-variable"')]
        assert 'href="/2/q06/"' in group and f'<span class="type-count">{group.count(CARD)} 题</span>' in group
        assert client.get('/2/q06/').status_code == 200
        response = client.post('/api/tutor-demo/sessions', json={'lesson_id': ID})
        assert response.status_code == 201 and response.json()['lesson_id'] == ID
        for path in re.findall(r'(?:href|src)="(/[^"#]+)"', page()[0]):
            if path != '/': assert client.get(path).status_code == 200, path
