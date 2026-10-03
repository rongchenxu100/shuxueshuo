"""Chapter 2 Q02: parameter in the leading coefficient, strict inequality, case union."""
import asyncio
import html
import json
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

ID = 'quadratic-always-q02'


@pytest.mark.live_llm
@pytest.mark.skipif(os.getenv('RUN_TUTOR_LIVE') != '1', reason='Explicit live opt-in')
def test_live_zero_coefficient_and_strict_inequality():
    from .reciprocal_live import replay

    turns = [
        ('二次项系数肯定非零，可以直接用判别式。', 0, False,
         [('method', 'discriminant'), ('fill', 'nonzero', 1)], []),
        ('x取全体实数。', 0, False, [], ['all_real_domain']),
        ('二次项系数是k，可能为零，要分k=0和k不等于0讨论。', 1, False, [], ['parameter_coefficient']),
        ('k=0不是二次式，直接舍去。', 1, False, [('choice', 'discard')], []),
        ('代入k=0为什么一次项也消失？只解释。', 1, True, [], []),
        ('k=0时两项都消失，只剩-2<0，对所有x成立，所以保留k=0。', 2, False, [], ['degenerate_holds']),
        ('k不等于0时开口向下，但相切也可以。', 2, False, [('choice', 'down_touch')], []),
        ('应是k<0开口向下，整条图像严格在横轴下方，不允许相切。', 3, False, [], ['graph_position']),
        ('判别式≤0。', 3, False, [('choice', 'le')], []),
        ('判别式是8k²+8k，必须严格小于0，同时k<0。', 4, False, [], ['discriminant_condition']),
        ('两根之间得-1<k<0，也满足k<0，交集仍是-1<k<0。', 5, False, [], ['discriminant_range']),
        ('最终就是-1<k<0。', 5, False, [('choice', 'only_second')], []),
        ('为什么这里取并集，不是交集？只问原因。', 5, True, [], []),
        ('要加回k=0，和-1<k<0取并集，得到-1<k≤0。', 6, False, [], ['case_union']),
        ('k=-1时是-(x+1)²<0，x=-1时等于0，不成立，排除。k=0时为-2<0恒成立，保留。', 7, False, [], ['boundary_check']),
    ]
    asyncio.run(replay(ID, turns))


def test_graphs_match_the_problem_or_explicitly_mark_hypothetical_case():
    text, _ = page()
    specs = [json.loads(html.unescape(s)) for s in re.findall(r'data-quadratic-graph="([^"]+)"', text)]
    for spec in specs:
        if spec['variable'] != 'x':
            continue
        k = spec['coefficient']
        assert spec['vertex'][0] == -1
        if spec['uid'].endswith('-cond-up'):
            assert '示意' in spec['title'] and '不是本题' in spec['description']
        else:
            assert abs(spec['vertex'][1] - (-2*k-2)) < 1e-9

def page():
    text = (ROOT / 'site/2/q02/index.html').read_text()
    return text, json.loads(re.search(r'id="practice-config">\s*(.*?)</script>', text, re.S)[1])

def choose(value):
    return [operation('choice', value), operation('submit')]

def check(first, second):
    return [operation('fill', first, 0), operation('fill', second, 1), operation('submit')]

def actions():
    return ([operation('method', 'discriminant')]
            + check('all_real', 'nonzero') + check('all_real', 'maybe_zero')
            + choose('discard') + choose('linear') + choose('holds')
            + choose('down_touch') + choose('up_apart') + choose('down_below')
            + choose('le') + choose('ge') + choose('lt')
            + choose('outside') + choose('closed_left') + choose('between')
            + choose('only_second') + choose('intersection') + choose('union')
            + check('holds', 'holds') + check('fails', 'holds'))

def test_contract_templates_math_and_page_ids():
    text, config = page()
    lesson = load_lesson(ID)
    for key in ('id', 'version', 'methods'):
        assert config[key] == lesson[key]
    ids = re.findall(r'\bid="([^"]+)"', text)
    assert len(ids) == len(set(ids))
    nodes = config['routes']['discriminant']
    assert len(nodes) == len(lesson['initial_state']['pairs']) == 7
    for node, expected in zip(nodes, lesson['routes']['discriminant']['nodes'], strict=True):
        for key in ('id', 'title', 'question', 'interaction', 'expected_answer', 'feedback'):
            assert node[key] == expected[key]
        for ref in [node['display'], *node.get('preview', {}).values(), *([node['board']] if 'board' in node else [])]:
            assert template(text, ref)
        body = template(text, node['display'])
        assert '<summary>完整推导</summary>' in body and f'id="{{{{uid}}}}-{node["id"]}-derivation"' in body
    assert 'href="/2/"' in text and 'Q02' in text
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
                errors.add(before)
        assert errors == set(range(7))
        assert result['state']['active'] == 7
        assert result['attempts'][-1]['status'] == 'completed'
        assert not tutor.calls
    asyncio.run(run())

def test_strict_graphs_mark_the_upper_side():
    text, _ = page()
    specs = [json.loads(html.unescape(s)) for s in re.findall(r'data-quadratic-graph="([^"]+)"', text)]
    assert specs and all(spec.get('markSign') == 'above' and spec.get('strict') for spec in specs)

def test_chapter_lists_and_serves_q02():
    with TestClient(create_app(Tutor())) as client:
        home = client.get('/2/').text
        assert home.count('href="/2/q02/"') == 1
        assert client.get('/2/q02/').status_code == 200
        response = client.post('/api/tutor-demo/sessions', json={'lesson_id': ID})
        assert response.status_code == 201 and response.json()['lesson_id'] == ID
        for path in re.findall(r'(?:href|src)="(/[^"#]+)"', page()[0]):
            if path != '/': assert client.get(path).status_code == 200, path

def test_quadratic_graph_upper_side_strict_and_mixed_endpoints():
    script = r'''
const assert=require('node:assert/strict');global.window=global;
require(process.argv[1]);
const base={bounds:[-2,4,-6,3],xTicks:[],yLabel:'',variable:'x',title:'t',description:'d',uid:'u',showVertex:false};
const count=(svg,name)=>(svg.match(new RegExp(`class="${name}"`,'g'))||[]).length;
let svg=PracticeComponents.quadraticGraph({...base,coefficient:-1,vertex:[1,1.5],markSign:'above'});
assert.equal(count(svg,'quadratic-positive-band'),1);assert.equal(count(svg,'quadratic-positive'),1);
assert.equal(count(svg,'quadratic-negative-band'),0);assert.equal(count(svg,'quadratic-negative'),0);
assert.ok(svg.includes('y &gt; 0'));
svg=PracticeComponents.quadraticGraph({...base,coefficient:-1,vertex:[1,0],markSign:'above'});
assert.ok(svg.includes('stroke="#08655f"'));
svg=PracticeComponents.quadraticGraph({...base,coefficient:-1,vertex:[1,0],markSign:'above',strict:true});
assert.equal(count(svg,'quadratic-root'),1);assert.ok(!svg.includes('stroke="#08655f"'));
svg=PracticeComponents.quadraticGraph({...base,coefficient:0,vertex:[0,-2],markSign:'above'});
assert.equal(count(svg,'quadratic-root'),0);assert.equal(count(svg,'quadratic-positive'),0);assert.ok(!svg.includes('NaN'));
svg=PracticeComponents.quadraticGraph({...base,coefficient:8,vertex:[-0.5,-2],bounds:[-2,1.2,-3.5,5],markSign:'above',solution:{intervals:[[-1,0]],closed:[true,false]}});
const ends=svg.match(/class="quadratic-endpoint"[^>]*/g);
assert.equal(ends.length,2);assert.ok(ends[0].includes('fill="#087f79"'));assert.ok(ends[1].includes('fill="#fff"'));
'''
    subprocess.run(['node','-e',script,str(ROOT/'site/assets/practice/components.js')],text=True,capture_output=True,check=True)
