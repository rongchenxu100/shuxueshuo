"""Chapter 2 Q09: y > 0 for every a in [-1, 1]; y is affine in a (possibly constant), and the slope x² − x changes sign, so both ends count."""
import asyncio
import html
import json
import os
import re
import subprocess
from fractions import Fraction

import pytest
from fastapi.testclient import TestClient
from shuxueshuo_server.tutor_demo.api import create_app
from shuxueshuo_server.tutor_demo.session import Event, Session, load_lesson
from .test_local_practice import ROOT, operation, pending
from .test_q11 import local_replay, template
from .test_tutor_demo import Tutor

CARD = 'class="problem-card"'
ID = 'quadratic-always-q09'


@pytest.mark.live_llm
@pytest.mark.skipif(os.getenv('RUN_TUTOR_LIVE') != '1', reason='Explicit live opt-in')
def test_live_endpoint_dialogue():
    from .reciprocal_live import replay

    turns = [
        ('x∈R，所以要对所有实数x恒成立。', 0, False, [('method', 'variable')], []),
        ('x=0时不就是常数1吗？请先解释，不要替我选。', 0, True, [], []),
        ('x=0时是常数1，x=1时是常数0，所以关于a至多一次，并不一定是一次式。', 0, False, [], ['linear_in_main_variable']),
        ('对任意a∈[-1,1]恒成立，x待求，固定x，把a作为主元。', 1, False, [], ['main_variable']),
        ('为什么去括号后常数项有一个-x？只解释。', 1, True, [], []),
        ('去括号后按a整理得f(a)=(x²-x)a-x+1。', 2, False, [], ['rewritten_in_main_variable']),
        ('只要f(0)>0不就够了吗？能给一个反例吗？', 2, True, [], []),
        ('要所有a都使f(a)>0，只需最小值大于0。', 3, False, [], ['minimum_condition']),
        ('斜率x²-x恒为正，最小值是f(-1)。', 3, False, [('fill', 'positive', 0)], []),
        ('为什么不能只看一端？只解释。', 3, True, [], []),
        ('x²-x=x(x-1)，x=2时为正，x=1/2时为负，符号不定。', 3, False, [], ['slope_sign_varies']),
        ('最小值是两端中较小的，所以f(-1)>0且f(1)>0。', 4, False, [], ['endpoint_minimum']),
        ('1-x²>0得-1<x<1，(x-1)²>0得x≠1，取交集-1<x<1。', 5, False, [], ['solved_range']),
        ('x=-1时取a=1得到4>0，所以保留x=-1；x=1时取a=0得到0，不满足>0，所以排除x=1。', 5, False, [], ['high_boundary_excluded']),
        ('x=-1也排除，因为a=-2时2a+2=-2<0。', 5, False, [], []),
        ('x=-1时取a=-1，2a+2=0不满足>0，所以排除。', 6, False, [], ['low_boundary_excluded']),
    ]
    asyncio.run(replay(ID, turns))


@pytest.mark.live_llm
@pytest.mark.skipif(os.getenv('RUN_TUTOR_LIVE') != '1', reason='Explicit live opt-in')
def test_live_other_boundary_is_independent():
    from .reciprocal_live import replay

    ops = [('method', 'variable'), ('fill', 'given', 0), ('fill', 'linear', 1), ('submit',),
           ('choice', 'collect'), ('submit',), ('choice', 'min'), ('submit',),
           ('fill', 'unknown', 0), ('fill', 'ends', 1), ('submit',),
           ('choice', 'intersect'), ('submit',)]
    asyncio.run(replay(ID, [
        ('x=-1时取a=-1左边为0，排除x=-1；x=1时虽然左边为0，但0也算大于0，所以保留x=1。', 5, False, ops, ['low_boundary_excluded']),
        ('x=1代入为什么是0？先解释，不要帮我完成。', 5, True, [], []),
        ('0不大于0，x=1时对所有a左边都为0，排除x=1。', 6, False, [], ['high_boundary_excluded']),
    ]))


def page():
    text = (ROOT / 'site/2/q09/index.html').read_text()
    return text, json.loads(re.search(r'id="practice-config">\s*(.*?)</script>', text, re.S)[1])

def choose(value):
    return [operation('choice', value), operation('submit')]

def check(*values):
    return [operation('fill', value, i) for i, value in enumerate(values)] + [operation('submit')]

def actions():
    return ([operation('method', 'variable')]
            + check('asked', 'quadratic') + check('given', 'linear')
            + choose('sign') + choose('merged') + choose('collect')
            + choose('max') + choose('one_point') + choose('min')
            + check('positive', 'left') + check('unknown', 'ends')
            + choose('only_right') + choose('closed') + choose('intersect')
            + check('holds', 'fails') + check('fails', 'fails'))

def specs(text, kind):
    return [json.loads(html.unescape(s)) for s in re.findall(rf'data-{kind}="([^"]+)"', text)]

def node(node_id):
    return next(n for n in page()[1]['routes']['variable'] if n['id'] == node_id)

def test_contract_templates_math_and_page_ids():
    text, config = page()
    lesson = load_lesson(ID)
    for key in ('id', 'version', 'methods'):
        assert config[key] == lesson[key]
    assert config['variables'] == ['a', 'x'], 'the quantified variable comes first'
    ids = re.findall(r'\bid="([^"]+)"', text)
    assert len(ids) == len(set(ids))
    assert len(lesson['initial_state']['pairs']) == len(config['routes']['variable'])
    for item, expected in zip(config['routes']['variable'], lesson['routes']['variable']['nodes'], strict=True):
        for key in ('id', 'title', 'question', 'interaction', 'expected_answer', 'feedback'):
            assert item[key] == expected[key]
        for ref in [item['display'], *([item['board']] if 'board' in item else [])]:
            assert template(text, ref)
        body = template(text, item['display'])
        assert '<summary>完整推导</summary>' in body and f'id="{{{{uid}}}}-{item["id"]}-derivation"' in body
    assert 'href="/2/"' in text and 'Q09' in text and 'Q08' not in text
    def strings(value):
        if isinstance(value, str): return [value]
        if isinstance(value, list): return sum((strings(v) for v in value), [])
        if isinstance(value, dict): return sum((strings(v) for v in value.values()), [])
        return []
    sources = [html.unescape(s) for s in re.findall(r'data-math-text>(.*?)</', text, re.S)] + strings(config) + strings(lesson)
    formulas = [f for s in sources for f in re.findall(r'\$([^$]+)\$', s)]
    script = "const katex=require(process.argv[1]);for(const f of JSON.parse(require('fs').readFileSync(0,'utf8')))katex.renderToString(f,{throwOnError:true});"
    subprocess.run(['node','-e',script,str(ROOT/'site/assets/practice/vendor/katex-0.18.9/katex.min.js')],input=json.dumps(formulas),text=True,capture_output=True,check=True)

def test_slope_changes_sign_so_both_ends_must_be_positive():
    labels = {o['value']: o['label'] for o in node('v_rewrite')['interaction']['options']}
    assert labels['collect'] == '$f(a)=(x^2-x)a-x+1$'
    y = lambda a, x: a * x * x - (a + 1) * x + 1
    f = lambda a, x: (x * x - x) * a - x + 1
    xs = [Fraction(i, 4) for i in range(-12, 13)]
    assert all(y(a, x) == f(a, x) for a in (-1, 0, 1) for x in xs)
    assert {(x * x - x > 0) - (x * x - x < 0) for x in xs} == {-1, 0, 1}, 'the slope takes every sign'
    for x in xs:
        values = [f(Fraction(i, 4) - 1, x) for i in range(9)]
        assert min(values) == min(f(-1, x), f(1, x))
        assert (min(values) > 0) == (-1 < x < 1)
    assert f(-1, Fraction(1, 2)) > f(1, Fraction(1, 2)) and f(-1, Fraction(-1, 2)) < f(1, Fraction(-1, 2)), 'either end can be lowest'
    assert node('v_condition')['expected_answer'] == {'one_of': ['min']}
    # f(0) > 0 alone is not enough: x = -3/2 keeps f(0) positive but f(-1) negative.
    assert f(0, Fraction(-3, 2)) > 0 > f(-1, Fraction(-3, 2))
    assert node('v_extremum')['expected_answer'] == {'terms': ['unknown', 'ends']}
    assert node('v_range')['expected_answer'] == {'one_of': ['intersect']}
    assert all(f(-1, -1) == 0 == f(a, 1) for a in (-1, 0, 1)), 'x = -1 fails at a = -1; x = 1 fails for every a'
    assert node('v_boundary')['expected_answer'] == {'terms': ['fails', 'fails']}

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
        assert errors == set(range(6))
        assert result['state']['active'] == 6
        assert result['attempts'][-1]['status'] == 'completed'
        assert not tutor.calls
    asyncio.run(run())

def test_graphs_are_instances():
    text, _ = page()
    f = lambda x: (x * x - x, 1 - x)
    lines = specs(template(text, 'v_extremum-done'), 'linear-graph')
    assert [(s['slope'], s['intercept']) for s in lines] == [f(-0.5), f(0), f(0.5)], 'f(a) with x = -1/2, 0, 1/2'
    assert [[p['x'] for p in s['points']] for s in lines] == [[-1], [], [1]], 'the lowest end follows the slope sign'
    assert template(text, 'v_extremum-done').count('class="graph-case"') == 3
    assert not specs(template(text, 'v_extremum-board'), 'linear-graph'), 'the board does not show the answer'
    assert all(s['interval'] == [-1, 1] and s['variable'] == 'a' for s in specs(text, 'linear-graph'))
    left, right = specs(template(text, 'v_range-done'), 'quadratic-graph')
    assert (left['coefficient'], left['vertex'], left['solution']['intervals']) == (-1, [0, 1], [[-1, 1]])
    assert (right['coefficient'], right['vertex'], right['solution']['intervals']) == (1, [1, 0], [[None, 1], [1, None]])
    assert '取交集：$-1&lt;x&lt;1$' in template(text, 'v_range-done')
    low, high = specs(template(text, 'v_boundary-done'), 'linear-graph')
    assert [(low['slope'], low['intercept']), (high['slope'], high['intercept'])] == [f(-1), f(1)]
    assert all(s['strict'] and s['markSign'] == 'below' for s in (low, high))

def test_a_line_on_the_axis_fails_a_strict_inequality():
    script = r'''
const assert=require('node:assert/strict');global.window=global;
require(process.argv[1]);
const base={bounds:[-1.8,1.8,-1,4.4],interval:[-1,1],xTicks:[],variable:'a',title:'t',description:'d',uid:'u',markSign:'below'};
assert.ok(PracticeComponents.linearGraph({...base,slope:0,intercept:0,strict:true}).includes('class="linear-negative"'));
assert.ok(!PracticeComponents.linearGraph({...base,slope:0,intercept:0}).includes('class="linear-negative"'));
assert.ok(!PracticeComponents.linearGraph({...base,slope:2,intercept:2,strict:true}).includes('class="linear-negative"'));
'''
    subprocess.run(['node','-e',script,str(ROOT/'site/assets/practice/components.js')],text=True,capture_output=True,check=True)

def test_chapter_lists_and_serves_q09():
    with TestClient(create_app(Tutor())) as client:
        home = client.get('/2/').text
        assert home.count('class="problem-card" href="/2/q09/"') == 1 and f'<strong>{home.count(CARD)}</strong>' in home
        group = home[home.index('id="group-variable"'):]
        group = group[:group.index('</section>')]
        assert group.index('href="/2/q08/"') < group.index('href="/2/q09/"')
        assert f'<span class="type-count">{group.count(CARD)} 题</span>' in group
        assert client.get('/2/q09/').status_code == 200
        response = client.post('/api/tutor-demo/sessions', json={'lesson_id': ID})
        assert response.status_code == 201 and response.json()['lesson_id'] == ID
        for path in re.findall(r'(?:href|src)="(/[^"#]+)"', page()[0]):
            if path != '/': assert client.get(path).status_code == 200, path
