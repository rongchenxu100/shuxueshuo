"""Chapter 2 Q07: x² − x > 0 on [2, 3], so separating m needs no case split, unlike the interval route."""
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
ID = 'quadratic-always-q07'


@pytest.mark.live_llm
@pytest.mark.skipif(os.getenv('RUN_TUTOR_LIVE') != '1', reason='Explicit live opt-in')
def test_live_positive_divisor_dialogue():
    from .reciprocal_live import replay

    turns = [
        ('这一步要判断哪些前提？只解释。', 0, True, [('method', 'extremum')], []),
        ('提出m就可以分离了。', 0, False, [], []),
        ('提出m得m(x²-x)<1，要除以x²-x，x在[2,3]上它是正的。', 1, False, [], ['separable_with_positive_divisor']),
        ('两边除以x²-x，要变号，得m>1/(x²-x)。', 1, False, [('choice', 'flip')], []),
        ('x²-x是正数，不用变号，m<1/(x²-x)。', 2, False, [], ['separated_inequality']),
        ('只要m<h(2)，就能对所有x成立。', 2, False, [('choice', 'one_point')], []),
        ('为什么不能看h(2)？只解释。', 2, True, [], []),
        ('m要比所有h(x)都小，只要比h(x)的最小值小。', 3, False, [], ['minimum_comparison']),
        ('最小值是h(2)=1/2。', 3, False, [('fill', 'h2', 1)], []),
        ('x²-x的对称轴是1/2，在[2,3]上递增。', 3, False, [], ['denominator_increasing']),
        ('分母递增，所以h也递增。', 3, False, [], []),
        ('正分母取倒数后，为什么单调性反过来？只解释。', 3, True, [], []),
        ('分母越大h越小，最小值h(3)=1/6。', 4, False, [], ['minimum_value']),
        ('m=1/6时，x=2的左边是-2/3<0，所以保留。', 4, False, [('fill', 'holds', 0)], []),
        ('是因为x=3不在区间里，所以排除吗？只解释。', 4, True, [], []),
        ('m=1/6时x=3处左边等于0，不满足<0，排除。', 5, False, [], ['boundary_excluded']),
    ]
    asyncio.run(replay(ID, turns))


@pytest.mark.live_llm
@pytest.mark.skipif(os.getenv('RUN_TUTOR_LIVE') != '1', reason='Explicit live opt-in')
def test_live_interval_cases_and_switch():
    from .reciprocal_live import replay

    turns = [
        ('提出m再除以x²-x，在[2,3]上除数为正。', 1, False, [('method', 'extremum')], ['separable_with_positive_divisor']),
        ('x取全体实数。', 0, False, [('switch_route', 'interval')], []),
        ('只要求x在闭区间[2,3]上恒成立。', 1, False, [], ['interval_domain']),
        ('只要最小值小于0。', 1, False, [('choice', 'min')], []),
        ('为什么f(2)<0不能保证恒成立？只解释。', 1, True, [], []),
        ('应要求f在[2,3]上的最大值小于0。', 2, False, [], ['maximum_condition']),
        ('对称轴和区间中点5/2比较就够了，不用看m的符号。', 2, False, [('fill', 'midpoint', 0)], []),
        ('按m>0与m<0分类，m=0不用考虑。', 2, False, [], []),
        ('按m的符号分m=0、m>0、m<0；m=0时f=-1是常数。', 2, False, [], ['sign_split']),
        ('m>0时开口向上，轴1/2在区间左侧，f递增，最大值f(3)=6m-1。', 2, False, [], ['positive_case_max']),
        ('m<0时顶点最高，所以最大值取x=1/2。', 2, False, [('fill', 'vertex', 2)], []),
        ('m<0时轴1/2在区间左侧，f在[2,3]上递减，最大值f(2)=2m-1。', 3, False, [], ['negative_case_max']),
        ('最后是m<0或0<m<1/6，不包含0。', 3, False, [('choice', 'missing_zero')], []),
        ('m=0退化后不是二次函数，为什么还要保留？只解释。', 3, True, [], []),
        ('m=0满足；正数分支交集是0<m<1/6，负数分支全满足，三支并集m<1/6。', 4, False, [], ['merged_range']),
        ('x=4时不成立，所以m=1/6应排除。', 4, False, [], []),
        ('m=1/6时x=3属于[2,3]，原式等于0不满足严格小于0，所以排除。', 5, False, [], ['boundary_excluded']),
    ]
    view = asyncio.run(replay(ID, turns))
    assert len(view['attempts']) == 2 and view['attempts'][-1]['status'] == 'completed'


def page():
    text = (ROOT / 'site/2/q07/index.html').read_text()
    return text, json.loads(re.search(r'id="practice-config">\s*(.*?)</script>', text, re.S)[1])

def choose(value):
    return [operation('choice', value), operation('submit')]

def check(*values):
    return [operation('fill', value, i) for i, value in enumerate(values)] + [operation('submit')]

def actions():
    return ([operation('method', 'extremum')]
            + check('separated', 'no_division') + check('movable', 'fixed_sign')
            + choose('flip') + choose('invert') + choose('keep')
            + choose('max') + choose('one_point') + choose('min')
            + check('mixed', 'vertex') + check('increasing', 'h3')
            + check('holds') + check('fails')
            + [operation('switch_route', 'interval')]
            + check('all_real') + check('interval')
            + choose('min') + choose('one_point') + choose('max')
            + check('midpoint', 'f2', 'f3') + check('sign', 'f3', 'f2')
            + choose('positive_only') + choose('missing_zero') + choose('union')
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
    assert 'href="/2/"' in text and 'Q07' in text
    def strings(value):
        if isinstance(value, str): return [value]
        if isinstance(value, list): return sum((strings(v) for v in value), [])
        if isinstance(value, dict): return sum((strings(v) for v in value.values()), [])
        return []
    sources = [html.unescape(s) for s in re.findall(r'data-math-text>(.*?)</', text, re.S)] + strings(config) + strings(lesson)
    formulas = [f for s in sources for f in re.findall(r'\$([^$]+)\$', s)]
    script = "const katex=require(process.argv[1]);for(const f of JSON.parse(require('fs').readFileSync(0,'utf8')))katex.renderToString(f,{throwOnError:true});"
    subprocess.run(['node','-e',script,str(ROOT/'site/assets/practice/vendor/katex-0.18.9/katex.min.js')],input=json.dumps(formulas),text=True,capture_output=True,check=True)

def test_positive_divisor_keeps_the_sign_and_the_minimum_is_at_the_right_end():
    text, config = page()
    assert [m['id'] for m in config['methods']] == ['extremum', 'interval'], 'separation is the main route'
    assert [n['id'] for n in config['routes']['extremum']] == ['e_basis', 'e_separate', 'e_condition', 'e_extremum', 'e_boundary']
    separate = node('extremum', 'e_separate')
    labels = {o['value']: o['label'] for o in separate['interaction']['options']}
    assert separate['expected_answer'] == {'one_of': ['keep']} and labels['keep'] == '$m<\\frac1{x^2-x}$'
    assert '不等号方向不变' in template(text, separate['display'])
    # m < h(3) is equivalent to the answer, so the one-point distractor must be another point.
    assert {o['value']: o['label'] for o in node('extremum', 'e_condition')['interaction']['options']}['one_point'] == '$m<h(2)$'
    h = lambda x: 1 / (x * x - x)
    assert all(x * x - x > 0 and h(x) >= h(3) for x in (2, 2.25, 2.5, 2.75, 3))
    assert node('extremum', 'e_extremum')['expected_answer'] == {'terms': ['increasing', 'h3']}
    for route in config['routes'].values():
        assert route[-1]['expected_answer'] == {'terms': ['fails']}, 'm = 1/6 makes f(3) = 0, and the inequality is strict'
    assert '$m&lt;\\boxed{\\frac16}$' in template(text, 'boundary-board')

def test_interval_route_splits_by_the_sign_of_m():
    extremum = node('interval', 'i_extremum')
    assert extremum['title'] == '分类讨论最值' and extremum['expected_answer'] == {'terms': ['sign', 'f3', 'f2']}
    assert 'm=0' in extremum['interaction']['slots'][0]['options'][0]['label']
    f = lambda m, x: m * x * x - m * x - 1
    for m in (Fraction(1, 10), Fraction(1, 7), Fraction(-1, 2), Fraction(-3)):
        values = [f(m, Fraction(2) + Fraction(i, 10)) for i in range(11)]
        assert max(values) == (f(m, 3) if m > 0 else f(m, 2))
    # f(2) < 0 alone is not enough: m = 1/4 keeps f(2) negative but f(3) positive.
    assert f(Fraction(1, 4), 2) < 0 < f(Fraction(1, 4), 3)
    labels = {o['value']: o['label'] for o in node('interval', 'i_range')['interaction']['options']}
    assert labels == {'union': '$m<\\frac16$', 'positive_only': '$0<m<\\frac16$', 'missing_zero': '$m<0$ 或 $0<m<\\frac16$'}
    text, _ = page()
    done = template(text, node('interval', 'i_range')['display'])
    assert done.count('class="case-merge-cell"') == 3 and '取并集：$m&lt;\\frac16$' in done

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
        assert errors == {('extremum', i) for i in range(5)} | {('interval', i) for i in range(5)}
        assert result['state']['active'] == 5
        assert len(result['attempts']) == 2 and all(a['status'] == 'completed' for a in result['attempts'])
        assert not tutor.calls
    asyncio.run(run())

def test_graphs_are_instances_on_the_interval():
    text, _ = page()
    parabolas = specs(text, 'quadratic-graph')
    assert not specs(text, 'axis-explorer') and not specs(text, 'reciprocal-sum-graph')
    assert all(spec['interval'] == [2, 3] for spec in parabolas)
    for spec in parabolas:
        if spec['uid'].endswith('-denominator'):
            assert (spec['coefficient'], spec['vertex']) == (1, [0.5, -0.25]), 'the denominator x² − x'
        else:
            m = spec['coefficient']
            assert spec['vertex'] == [0.5, round(-m / 4 - 1, 6)], f'f(x) with m = {m}'
    cases = lambda ref: [spec['coefficient'] for spec in specs(template(text, ref), 'quadratic-graph')]
    item = node('interval', 'i_extremum')
    assert cases(item['board']) == cases(item['display']) == [0, 0.1, -0.5], 'm = 0 is case ①'
    assert not any(spec['points'] for spec in specs(template(text, item['board']), 'quadratic-graph')), 'the board does not show the answer'
    for ref in ('e_boundary-done', 'i_boundary-done'):
        [boundary] = specs(template(text, ref), 'quadratic-graph')
        assert boundary['coefficient'] == round(1 / 6, 6) and boundary['strict'] and boundary['markSign'] == 'above'

def test_three_case_merge_and_flat_case_render():
    script = r'''
const assert=require('node:assert/strict');global.window=global;
require(process.argv[1]);
const flat=PracticeComponents.quadraticGraph({coefficient:0,vertex:[0.5,-1],bounds:[-1,4,-1.6,0.7],interval:[2,3],xTicks:[[2,'2'],[3,'3']],yLabel:'',variable:'x',title:'t',description:'d',uid:'f',showVertex:false});
assert.ok(!flat.includes('NaN')&&!flat.includes('Infinity'), 'm = 0 draws the line y = -1');
'''
    subprocess.run(['node','-e',script,str(ROOT/'site/assets/practice/components.js')],text=True,capture_output=True,check=True)
    css = (ROOT / 'site/assets/practice/practice.css').read_text()
    assert '.case-merge-group:has(> .case-merge-cell:nth-child(3)) { grid-template-columns:repeat(3,minmax(0,1fr)); }' in css

def test_chapter_lists_and_serves_q07():
    with TestClient(create_app(Tutor())) as client:
        home = client.get('/2/').text
        assert home.count('class="problem-card" href="/2/q07/"') == 1 and f'<strong>{home.count(CARD)}</strong>' in home
        group = home[home.index('id="group-separation"'):home.index('id="group-variable"')]
        assert 'href="/2/q07/"' in group and f'<span class="type-count">{group.count(CARD)} 题</span>' in group
        toc = home[home.index('href="#group-separation"'):]
        assert toc[:toc.index('</a>')].endswith(f'{group.count(CARD)} 题</span>')
        assert client.get('/2/q07/').status_code == 200
        response = client.post('/api/tutor-demo/sessions', json={'lesson_id': ID})
        assert response.status_code == 201 and response.json()['lesson_id'] == ID
        for path in re.findall(r'(?:href|src)="(/[^"#]+)"', page()[0]):
            if path != '/': assert client.get(path).status_code == 200, path
