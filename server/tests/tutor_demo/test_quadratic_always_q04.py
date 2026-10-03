"""Chapter 2 Q04: a closed interval, solved by endpoint values or by separating the parameter."""
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
ID = 'quadratic-always-q04'


@pytest.mark.live_llm
@pytest.mark.skipif(os.getenv('RUN_TUTOR_LIVE') != '1', reason='Explicit live opt-in')
def test_live_interval_dialogue():
    from .reciprocal_live import replay

    turns = [
        ('x是全体实数。', 0, False, [('method', 'interval'), ('fill', 'all_real', 0)], []),
        ('x只在[1,2]上取值。', 1, False, [], ['interval_domain']),
        ('只要最小值小于0就行。', 1, False, [('choice', 'min')], []),
        ('为什么最小值不够？只解释。', 1, True, [], []),
        ('区间上的最大值小于0，整段才小于0。', 2, False, [], ['maximum_condition']),
        ('开口向上，离对称轴越远的端点越高，所以对称轴要和区间中点3/2比较。', 2, False, [], ['midpoint_split']),
        ('m≥-3时对称轴在中点左侧，最大值是f(2)；m<-3时最大值是f(1)。', 3, False, [], ['left_case_max', 'right_case_max']),
        ('情况①m≥-3和m<-4无解，情况②得m<-5，取并集得m<-5。', 4, False, [], ['merged_range']),
        ('m=-5时x=1处左边等于0，不满足小于0，所以排除。', 5, False, [], ['boundary_excluded']),
    ]
    asyncio.run(replay(ID, turns))


@pytest.mark.live_llm
@pytest.mark.skipif(os.getenv('RUN_TUTOR_LIVE') != '1', reason='Explicit live opt-in')
def test_live_separation_dialogue_after_route_switch():
    from .reciprocal_live import replay

    turns = [
        ('x只在[1,2]上取值。', 1, False, [('method', 'interval')], ['interval_domain']),
        ('我觉得移项后可以分离m。', 0, False,
         [('switch_route', 'extremum')], []),
        ('为什么需要看x的符号？只解释，不替我选择。', 0, True, [], []),
        ('含m的只有mx，移项再除以x；x在[1,2]上大于0，不等号不变向。', 1, False,
         [], ['separable_with_positive_divisor']),
        ('除以x后应该是m>-(x+4/x)。', 1, False, [('choice', 'flip')], []),
        ('x>0，所以除后是m<-(x+4)，不用除常数4。', 1, False, [('choice', 'partial')], []),
        ('x>0，不等号不变向，每项都除以x，得到m<-x-4/x。', 2, False,
         [], ['separated_inequality']),
        ('恒成立就是m小于h的最小值的相反数。h最小值为4，m=-4.5<-4，所以m=-4.5可以。',
         2, False, [('choice', 'min')], []),
        ('为什么这里要看h的最大值？只解释。', 2, True, [], []),
        ('-m必须大于h在[1,2]上的最大值，才对所有x成立。', 3, False,
         [], ['maximum_comparison']),
        ('基本不等式得h≥4，所以最低点是(4,5)。', 3, False,
         [('fill', 'low_4', 0)], []),
        ('x=4/x，且x>0，所以x=2，h(2)=4，最低点是(2,4)。', 3, False,
         [], ['hook_lowest_point']),
        ('x趋近0的正侧时，4/x越来越大，图像贴近y轴向上。', 3, False,
         [], ['hook_near_y_axis']),
        ('x越来越大时，4/x趋于0，所以整个h趋于0，图像贴近x轴。', 3, False,
         [('fill', 'fall', 2)], []),
        ('为什么4/x趋于0，h却不趋于0？只解释。', 3, True, [], []),
        ('h=x+4/x，h-x=4/x趋于0，所以右端贴近y=x。', 4, False,
         [], ['hook_near_line']),
        ('由基本不等式h≥4，最大值是4，在x=2取到。', 4, False,
         [('fill', 'at_right', 1)], []),
        ('h(1)=5，所以最大值为5。', 4, False, [], ['maximum_at_left']),
        ('[1,2]在最低点x=2的左边，这一段单调递减。', 5, False,
         [], ['left_of_lowest']),
        ('m=-5时x=2满足，所以保留边界。', 5, False, [('fill', 'holds', 0)], []),
        ('端点不取。', 5, False, [], []),
        ('m=-5时，x=1使x²-5x+4=0，不满足严格小于0，所以排除。', 6, False,
         [], ['boundary_excluded']),
    ]
    view = asyncio.run(replay(ID, turns))
    assert len(view['attempts']) == 2
    assert view['attempts'][-1]['status'] == 'completed'
    # A blocked answer is not enough: verify the tutor actually refutes the
    # proposed parameter with the original expression at x=1.
    messages = view['messages']
    index = next(i for i, message in enumerate(messages)
                 if message.get('text') == turns[7][0])
    reply = re.sub(r'[\s{}]', '', messages[index + 1]['text'])
    assert 'x=1' in reply or 'f(1)' in reply, reply
    assert '0.5' in reply or r'\frac12' in reply, reply


def page():
    text = (ROOT / 'site/2/q04/index.html').read_text()
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
            + choose('loose') + choose('empty') + choose('union')
            + check('holds') + check('fails')
            + [operation('switch_route', 'extremum')]
            + check('separated', 'no_division') + check('movable', 'fixed_sign')
            + choose('flip') + choose('partial') + choose('keep')
            + choose('min') + choose('one_point') + choose('max')
            + check('low_4', 'x_axis', 'flat') + check('low_2', 'y_axis', 'line')
            + check('right', 'at_right') + check('left', 'at_left')
            + check('holds') + check('fails'))

def specs(text, kind):
    return [json.loads(html.unescape(s)) for s in re.findall(rf'data-{kind}="([^"]+)"', text)]

def test_contract_templates_math_and_page_ids():
    text, config = page()
    lesson = load_lesson(ID)
    for key in ('id', 'version', 'methods'):
        assert config[key] == lesson[key]
    ids = re.findall(r'\bid="([^"]+)"', text)
    assert len(ids) == len(set(ids))
    assert len(lesson['initial_state']['pairs']) == max(len(nodes) for nodes in config['routes'].values())
    for route, nodes in config['routes'].items():
        for node, expected in zip(nodes, lesson['routes'][route]['nodes'], strict=True):
            for key in ('id', 'title', 'question', 'interaction', 'expected_answer', 'feedback'):
                assert node[key] == expected[key]
            for ref in [node['display'], *node.get('preview', {}).values(), *([node['board']] if 'board' in node else [])]:
                assert template(text, ref)
            body = template(text, node['display'])
            assert '<summary>完整推导</summary>' in body and f'id="{{{{uid}}}}-{node["id"]}-derivation"' in body
    boundary = {route: nodes[-1] for route, nodes in config['routes'].items()}
    assert boundary['interval']['interaction'] == boundary['extremum']['interaction']
    assert boundary['interval']['board'] == boundary['extremum']['board'] == 'boundary-board'
    assert 'href="/2/"' in text and 'Q04' in text
    def strings(value):
        if isinstance(value, str): return [value]
        if isinstance(value, list): return sum((strings(v) for v in value), [])
        if isinstance(value, dict): return sum((strings(v) for v in value.values()), [])
        return []
    sources = [html.unescape(s) for s in re.findall(r'data-math-text>(.*?)</', text, re.S)] + strings(config) + strings(lesson)
    formulas = [f for s in sources for f in re.findall(r'\$([^$]+)\$', s)]
    script = "const katex=require(process.argv[1]);for(const f of JSON.parse(require('fs').readFileSync(0,'utf8')))katex.renderToString(f,{throwOnError:true});"
    subprocess.run(['node','-e',script,str(ROOT/'site/assets/practice/vendor/katex-0.18.9/katex.min.js')],input=json.dumps(formulas),text=True,capture_output=True,check=True)

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

def test_graphs_are_instances_of_the_problem():
    text, _ = page()
    parabolas, hooks = specs(text, 'quadratic-graph'), specs(text, 'reciprocal-sum-graph')
    assert parabolas and hooks
    for spec in parabolas:
        m = -2 * spec['vertex'][0]
        assert spec['coefficient'] == 1 and math.isclose(spec['vertex'][1], 4 - m * m / 4), spec['uid']
        assert spec['interval'] == [1, 2] and spec.get('markSign', 'above') == 'above' and spec.get('strict', True)
        assert f'm = {m:g}'.replace('-', '−') in spec['title'], spec['uid']
    for spec in hooks:
        assert (spec['a'], spec['b']) == (1, 4), spec['uid']
        assert spec.get('interval') == [1, 2] or spec.get('asymptotes'), spec['uid']
    full = [spec for spec in hooks if spec.get('asymptotes')]
    assert len(full) == 1 and full[0]['points'] == [{'x': 2, 'label': '(2, 4)', 'place': 'below-left'}]
    for explorer in specs(text, 'axis-explorer'):
        assert (explorer['coefficient'], explorer['constant'], explorer['interval']) == (1, 4, [1, 2])
        assert explorer['marks'] == [{'x': 1.5, 'label': '3/2'}]
        axis = explorer['axis']
        assert axis['min'] <= axis['value'] <= axis['max'], explorer['uid']
    node = next(n for n in page()[1]['routes']['interval'] if n['id'] == 'i_extremum')
    [board] = specs(template(text, node['board']), 'axis-explorer')
    assert board['axis']['min'] < 1 and 2 < board['axis']['max']
    left, right = (spec['axis'] for spec in specs(template(text, node['display']), 'axis-explorer'))
    assert left['max'] == 1.5 and left['min'] < 1, 'case ① keeps the axis at or left of the midpoint'
    assert right['min'] > 1.5 and right['max'] > 2, 'case ② keeps the axis right of the midpoint'
    assert 'm = −' not in template(text, node['display']), 'cases are split by −m/2, not by sample values of m'
    board = template(text, next(n for n in page()[1]['routes']['interval'] if n['id'] == 'i_range')['board'])
    assert 'f(x)_{\\max}=f(2)=2m+8&lt;0' in board and 'f(x)_{\\max}=f(1)=m+5&lt;0' in board

def test_axis_explorer_marks_the_highest_endpoint():
    script = r'''
const assert=require('node:assert/strict');global.window=global;
require(process.argv[1]);
const UI=PracticeComponents;
const spec={coefficient:1,constant:4,axis:{min:0.5,max:3,step:0.05,value:1},interval:[1,2],
  bounds:[-0.6,4.6,-5.8,7],marks:[{x:1.5,label:'3/2'}],variable:'x',title:'<t>',description:'d',uid:'u-axis'};
const highest=layer=>[...layer.matchAll(/class="axis-endpoint highest" cx="([\d.]+)"/g)].map(m=>Math.round(Number(m[1])));
const x=value=>Math.round(48+(value+0.6)/5.2*270);
assert.deepEqual(highest(UI.axisExplorerLayer(spec,1)),[x(2)]);
assert.deepEqual(highest(UI.axisExplorerLayer(spec,3)),[x(1)]);
assert.deepEqual(highest(UI.axisExplorerLayer(spec,1.5)),[x(1),x(2)]);
const html=UI.axisExplorer(spec);
assert.ok(html.includes('data-axis-input min="0.5" max="3" step="0.05" value="1"'));
assert.ok(html.includes('data-axis-layer')&&html.includes('&lt;t&gt;')&&!html.includes('readout'));
assert.equal((html.match(/class="axis-mark"/g)||[]).length,1);
assert.ok(!html.includes('NaN')&&!html.includes('Infinity'));
'''
    subprocess.run(['node','-e',script,str(ROOT/'site/assets/practice/components.js')],text=True,capture_output=True,check=True)

def test_interval_emphasis_and_reciprocal_sum_graph():
    script = r'''
const assert=require('node:assert/strict');global.window=global;
require(process.argv[1]);
const count=(svg,name)=>(svg.match(new RegExp(`class="${name}"`,'g'))||[]).length;
const base={coefficient:1,bounds:[-0.6,4.6,-5.8,4.8],xTicks:[],yLabel:'',variable:'x',title:'t',description:'d',uid:'u',showVertex:false,markSign:'above',strict:true};
let svg=PracticeComponents.quadraticGraph({...base,vertex:[2.25,-1.0625]});
assert.equal(count(svg,'graph-interval'),0);assert.equal(count(svg,'graph-outside'),0);assert.equal(count(svg,'quadratic-root'),2);
svg=PracticeComponents.quadraticGraph({...base,vertex:[2.25,-1.0625],interval:[1,2]});
assert.equal(count(svg,'graph-interval'),1);assert.equal(count(svg,'graph-outside'),1);
assert.equal(count(svg,'quadratic-root'),1);assert.equal(count(svg,'quadratic-positive'),1);
svg=PracticeComponents.quadraticGraph({...base,vertex:[3,-5],interval:[1,2],points:[{x:1,label:'<p>',place:'below-left'}]});
assert.equal(count(svg,'quadratic-positive'),0);assert.equal(count(svg,'quadratic-root'),0);
assert.ok(svg.includes('&lt;p&gt;'));assert.ok(svg.includes('text-anchor="end" fill="#a04c36"'));
const hook={a:1,b:4,bounds:[-0.3,4.7,-0.6,7.4],xTicks:[[1,'1']],title:'t',description:'d',uid:'h'};
svg=PracticeComponents.reciprocalSumGraph(hook);
assert.equal(count(svg,'reciprocal-curve'),1);assert.equal(count(svg,'graph-outside'),0);assert.equal(count(svg,'graph-asymptote'),0);
svg=PracticeComponents.reciprocalSumGraph({...hook,interval:[1,2],points:[{x:1,label:'(1, 5)'}],referenceLines:[{value:5,label:'y = −m'}]});
assert.equal(count(svg,'graph-outside'),1);assert.equal(count(svg,'graph-point'),1);assert.equal(count(svg,'graph-reference'),1);
assert.ok(!svg.includes('NaN')&&!svg.includes('Infinity'));
svg=PracticeComponents.reciprocalSumGraph({...hook,bounds:[-0.5,8.5,-0.9,9.5],asymptotes:true});
assert.equal(count(svg,'graph-asymptote'),2);assert.ok(svg.includes('>y = x</text>'));
assert.ok(!svg.includes('NaN')&&!svg.includes('Infinity'));
'''
    subprocess.run(['node','-e',script,str(ROOT/'site/assets/practice/components.js')],text=True,capture_output=True,check=True)

def test_chapter_lists_and_serves_q04():
    with TestClient(create_app(Tutor())) as client:
        home = client.get('/2/').text
        assert home.count('class="problem-card" href="/2/q04/"') == 1 and f'<strong>{home.count(CARD)}</strong>' in home
        group = home[home.index('id="group-interval"'):home.index('id="group-separation"')]
        assert 'href="/2/q04/"' in group and 'type-empty' not in group
        assert client.get('/2/q04/').status_code == 200
        response = client.post('/api/tutor-demo/sessions', json={'lesson_id': ID})
        assert response.status_code == 201 and response.json()['lesson_id'] == ID
        for path in re.findall(r'(?:href|src)="(/[^"#]+)"', page()[0]):
            if path != '/': assert client.get(path).status_code == 200, path
