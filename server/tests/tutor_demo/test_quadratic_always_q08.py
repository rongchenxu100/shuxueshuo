"""Chapter 2 Q08: y < 0 for every m in [1, 3], so m is the main variable and y is linear in m."""
import asyncio
import html
import json
import os
import re
import subprocess
from fractions import Fraction

import pytest
from fastapi.testclient import TestClient
from .auth_helpers import create_app
from shuxueshuo_server.tutor_demo.session import Event, Session, load_lesson
from .test_local_practice import ROOT, operation, pending
from .test_q11 import local_replay, template
from .test_tutor_demo import Tutor

CARD = 'class="problem-card"'
ID = 'quadratic-always-q08'


@pytest.mark.live_llm
@pytest.mark.skipif(os.getenv('RUN_TUTOR_LIVE') != '1', reason='Explicit live opt-in')
def test_live_switch_main_variable_dialogue(capsys):
    from .reciprocal_live import replay

    turns = [
        ('这一步要判断哪些前提？只解释。', 0, True, [('method', 'variable')], []),
        ('题目说x是实数，所以x∈R。', 0, False, [], []),
        ('x∈R这句话本身有错吗？只解释，不替我作答。', 0, True, [], []),
        ('既然x∈R，就要求不等式对所有实数x恒成立。', 0, False, [('fill', 'asked', 0)], []),
        ('对任意m∈[1,3]恒成立，x是待求的，应该固定x，把m作为主元。', 0, False, [], ['main_variable']),
        ('关于x确实有二次项，为什么这里不选二次式？只解释。', 0, True, [], []),
        ('把x当常数，m只有一次，是m的一次函数。', 1, False, [], ['linear_in_main_variable']),
        ('整理成(x²-x)m-6。', 1, False, [('choice', 'missing')], []),
        ('含m的项有mx²、-mx、m，提出m得f(m)=(x²-x+1)m-6。', 2, False, [], ['rewritten_in_main_variable']),
        ('只要f(2)<0就行。', 2, False, [('choice', 'one_point')], []),
        ('只看m=2为什么不行？给个本题的反例，只解释。', 2, True, [], []),
        ('要所有m都使f(m)<0，只需f(m)在[1,3]上的最大值小于0。', 3, False, [], ['maximum_condition']),
        ('斜率x²-x+1的符号不定，要讨论。', 3, False, [('fill', 'unknown', 0)], []),
        ('能不能分离参数做？只解释。', 3, True, [], []),
        ('x²-x+1=(x-1/2)²+3/4>0，斜率恒正，f(m)递增。', 3, False, [], ['slope_positive']),
        ('最大值取f(1)、f(3)中较大的一个。', 3, False, [('fill', 'ends', 1)], []),
        ('最大值是f(3)=3x²-3x-3。', 4, False, [], ['maximum_value']),
        ('开口向上，所以取两个根的外侧。', 4, False, [('choice', 'outside')], []),
        ('x²-x-1<0，两根(1±√5)/2，取两根之间。', 5, False, [], ['solved_range']),
        ('两个边界处m=1都得到-4<0，所以都保留。', 5, False, [('fill', 'holds', 0), ('fill', 'holds', 1)], []),
        ('两个边界取m=4得到2>0，所以都排除。', 5, False, [], []),
        ('m=3是区间端点，还需要检查吗？只解释。', 5, True, [], []),
        ('下边界处x²-x=1，m=3时原式为0，不满足严格小于0，排除下边界。', 5, False, [], ['low_boundary_excluded']),
        ('上边界也有x²-x=1，m=3时原式等于0，排除上边界。', 6, False, [], ['high_boundary_excluded']),
    ]
    asyncio.run(replay(ID, turns))
    output = capsys.readouterr().out
    print(output, end='')
    replies = [json.loads(line) for line in output.splitlines() if line.startswith('{"lesson"')]
    example = next(r['reply'] for r in replies if '给个本题的反例' in r['student'])
    # Check the actual numeric counterexample, not just progression/evidence.
    compact = re.sub(r'\s+', '', example).replace('\\dfrac', '\\frac').replace('\\tfrac', '\\frac')
    assert re.search(r'-\\frac\{28\}\{25\}|\\frac\{-28\}\{25\}|-28/25', compact), example
    assert re.search(r'\\frac\{33\}\{25\}|33/25', compact), example
    assert not any(re.search(r'\b(missing|collect|given|asked)\b', r['reply']) for r in replies)
    boundary_reply = next(r['reply'] for r in replies if 'm=1都得到' in r['student'])
    assert '代入对象不对' not in boundary_reply, boundary_reply


def page():
    text = (ROOT / 'site/2/q08/index.html').read_text()
    return text, json.loads(re.search(r'id="practice-config">\s*(.*?)</script>', text, re.S)[1])

def choose(value):
    return [operation('choice', value), operation('submit')]

def check(*values):
    return [operation('fill', value, i) for i, value in enumerate(values)] + [operation('submit')]

def actions():
    return ([operation('method', 'variable')]
            + check('asked', 'quadratic') + check('given', 'linear')
            + choose('missing') + choose('merged') + choose('collect')
            + choose('min') + choose('one_point') + choose('max')
            + check('unknown', 'ends') + check('positive', 'right')
            + choose('outside') + choose('closed') + choose('between')
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
    assert config['variables'] == ['m', 'x'], 'the quantified variable comes first'
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
    assert 'href="/2/"' in text and 'Q08' in text and 'Q07' not in text
    def strings(value):
        if isinstance(value, str): return [value]
        if isinstance(value, list): return sum((strings(v) for v in value), [])
        if isinstance(value, dict): return sum((strings(v) for v in value.values()), [])
        return []
    sources = [html.unescape(s) for s in re.findall(r'data-math-text>(.*?)</', text, re.S)] + strings(config) + strings(lesson)
    formulas = [f for s in sources for f in re.findall(r'\$([^$]+)\$', s)]
    script = "const katex=require(process.argv[1]);for(const f of JSON.parse(require('fs').readFileSync(0,'utf8')))katex.renderToString(f,{throwOnError:true});"
    subprocess.run(['node','-e',script,str(ROOT/'site/assets/practice/vendor/katex-0.18.9/katex.min.js')],input=json.dumps(formulas),text=True,capture_output=True,check=True)

def test_positive_slope_puts_the_maximum_at_m_3_and_both_boundaries_fail():
    text, config = page()
    assert [m['id'] for m in config['methods']] == ['variable'], 'only the switched main variable route'
    labels = {o['value']: o['label'] for o in node('v_rewrite')['interaction']['options']}
    assert labels['collect'] == '$f(m)=(x^2-x+1)m-6$'
    y = lambda m, x: m * x * x - m * x - 6 + m
    f = lambda m, x: (x * x - x + 1) * m - 6
    xs = [Fraction(i, 4) for i in range(-12, 13)]
    assert all(y(m, x) == f(m, x) for m in (1, 2, 3) for x in xs)
    assert all(x * x - x + 1 > 0 and max(f(m, x) for m in (1, Fraction(3, 2), 2, 3)) == f(3, x) for x in xs)
    assert node('v_extremum')['expected_answer'] == {'terms': ['positive', 'right']}
    # f(2) < 0 is not enough: x = 1.8 keeps f(2) negative but f(3) positive.
    assert f(2, Fraction(9, 5)) < 0 < f(3, Fraction(9, 5))
    roots = [(1 - 5 ** 0.5) / 2, (1 + 5 ** 0.5) / 2]
    for x in roots:
        assert abs(x * x - x - 1) < 1e-12 and abs(f(3, x)) < 1e-12, 'm = 3 makes the left side 0'
    assert node('v_boundary')['expected_answer'] == {'terms': ['fails', 'fails']}
    assert '分离参数' in load_lesson(ID)['routes']['variable']['nodes'][0]['criteria'], 'separation is handled by the tutor'

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

def test_line_graphs_are_instances_on_the_m_interval():
    text, _ = page()
    lines = specs(text, 'linear-graph')
    assert all(spec['interval'] == [1, 3] and spec['variable'] == 'm' for spec in lines)
    extremum = specs(template(text, 'v_extremum-done'), 'linear-graph')
    assert [(s['slope'], s['intercept']) for s in extremum] == [(1, -6), (3, -6)], 'f(m) with x = 0 and x = 2'
    assert all(s['slope'] > 0 and [p['x'] for p in s['points']] == [3] for s in extremum)
    assert not specs(template(text, 'v_extremum-board'), 'linear-graph'), 'the board does not show the answer'
    [boundary] = specs(template(text, 'v_boundary-done'), 'linear-graph')
    assert (boundary['slope'], boundary['intercept']) == (2, -6) and boundary['strict'] and boundary['markSign'] == 'above'
    [solution] = specs(template(text, 'v_range-done'), 'quadratic-graph')
    assert solution['vertex'] == [0.5, -1.25] and solution['solution']['closed'] is False

def test_linear_graph_renders_segment_root_and_mount():
    script = r'''
const assert=require('node:assert/strict');global.window=global;
require(process.argv[1]);
const base={bounds:[-0.6,3.8,-6.6,3.8],interval:[1,3],xTicks:[[1,'1'],[3,'3']],variable:'m',title:'t',description:'d',uid:'u'};
const rising=PracticeComponents.linearGraph({...base,slope:3,intercept:-6,points:[{x:3,label:'最高',place:'above-left'}]});
assert.ok(rising.includes('linear-line')&&rising.includes('最高')&&!rising.includes('NaN'));
const edge=PracticeComponents.linearGraph({...base,slope:2,intercept:-6,markSign:'above',strict:true});
assert.ok(edge.includes('class="linear-root"')&&edge.includes('y &gt; 0')&&!edge.includes('class="linear-positive"'), 'the root sits at the right end, nothing above the axis');
const flat=PracticeComponents.linearGraph({...base,slope:0,intercept:-2});
assert.ok(!flat.includes('NaN')&&!flat.includes('Infinity'));
'''
    subprocess.run(['node','-e',script,str(ROOT/'site/assets/practice/components.js')],text=True,capture_output=True,check=True)
    assert '[data-linear-graph]' in (ROOT / 'site/assets/practice/runtime.js').read_text()

def test_chapter_lists_and_serves_q08():
    with TestClient(create_app(Tutor())) as client:
        home = client.get('/2/').text
        assert home.count('class="problem-card" href="/2/q08/"') == 1 and f'<strong>{home.count(CARD)}</strong>' in home
        group = home[home.index('id="group-variable"'):]
        group = group[:group.index('</section>')]
        assert 'href="/2/q08/"' in group and f'<span class="type-count">{group.count(CARD)} 题</span>' in group
        assert '题目准备中' not in home
        toc = home[home.index('href="#group-variable"'):]
        assert toc[:toc.index('</a>')].endswith(f'{group.count(CARD)} 题</span>')
        assert client.get('/2/q08/').status_code == 200
        response = client.post('/api/tutor-demo/sessions', json={'lesson_id': ID})
        assert response.status_code == 201 and response.json()['lesson_id'] == ID
        for path in re.findall(r'(?:href|src)="(/[^"#]+)"', page()[0]):
            if path != '/': assert client.get(path).status_code == 200, path
