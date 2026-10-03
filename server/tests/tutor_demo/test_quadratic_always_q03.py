"""Chapter 2 Q03: two degenerate parameter values with different outcomes."""
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
ID = 'quadratic-always-q03'


@pytest.mark.live_llm
@pytest.mark.skipif(os.getenv('RUN_TUTOR_LIVE') != '1', reason='Explicit live opt-in')
def test_live_two_degenerate_values_and_strict_boundaries():
    from .reciprocal_live import replay

    turns = [
        ('二次项系数是a²，肯定非零，直接用判别式。', 0, False,
         [('method', 'discriminant'), ('fill', 'nonzero', 1)], []),
        ('x取全体实数。', 0, False, [], ['all_real_domain']),
        ('二次项系数应是a²-1，可能为零，先讨论a²-1=0，再讨论不为零。', 1, False,
         [], ['parameter_coefficient']),
        ('a²-1=0只有a=1，代入为-1<0，成立。', 1, False, [('choice', 'only_one')], []),
        ('a=±1都使二次项消失，因此都剩下-1<0，两个都保留。', 1, False,
         [('choice', 'both_hold')], []),
        ('为什么a=-1时一次项没有消失？只解释，不替我作答。', 1, True, [], []),
        ('a=1时为-1<0，对所有x成立；a=-1时为2x-1<0，仅x<1/2成立，不恒成立，舍去。',
         2, False, [], ['degenerate_cases']),
        ('非退化时只需a<0，开口向下。', 2, False, [], []),
        ('应该是a²-1<0开口向下，但允许相切。', 2, False, [('choice', 'down_touch')], []),
        ('要求a²-1<0，开口向下，整条图像严格在横轴下方，没有公共点。', 3, False,
         [], ['graph_position']),
        ('判别式≤0即可。', 3, False, [('choice', 'le')], []),
        ('为什么不能取等号？只是问原因。', 3, True, [], []),
        ('Δ=(a-1)²-4(a²-1)<0，同时a²-1<0。', 3, False, [], []),
        ('常数项是-1，所以Δ=(a-1)²+4(a²-1)=5a²-2a-3<0，同时a²-1<0。',
         4, False, [], ['discriminant_condition']),
        ('解得-3/5≤a<1，左端点也能取。', 4, False, [('choice', 'closed_left')], []),
        ('(5a+3)(a-1)<0得-3/5<a<1，与开口条件-1<a<1取交集仍是-3/5<a<1。',
         5, False, [], ['discriminant_range']),
        ('最终范围就是-3/5<a<1。', 5, False, [('choice', 'only_second')], []),
        ('为什么两种情况取并集而不是交集？只问原因。', 5, True, [], []),
        ('还要把a=1并进来，得到-3/5<a≤1；a=-1已不满足，不能并入。', 6, False,
         [], ['case_union']),
        ('a=-3/5时左边是负的平方，一定严格小于0，可以保留；a=1也保留。', 6, False,
         [('fill', 'holds', 0), ('fill', 'holds', 1)], []),
        ('负的平方为什么不一定小于零？只解释。', 6, True, [], []),
        ('a=-3/5时为-(4x/5-1)²，x=5/4时等于0，不满足<0，排除；a=1时-1<0恒成立，保留。',
         7, False, [], ['boundary_check']),
    ]
    view = asyncio.run(replay(ID, turns))
    # Blocking advancement alone is insufficient: the tutor must also correct
    # the mistaken opening condition, rather than only discuss intersections.
    messages = view['messages']
    index = next(i for i, message in enumerate(messages)
                 if message.get('text') == '非退化时只需a<0，开口向下。')
    reply = messages[index + 1]['text']
    normalized = re.sub(r'[\s{}]', '', reply).replace('²', '^2')
    assert 'a^2-1<0' in normalized or '-1<a<1' in normalized, reply
    for question in (turns[19][0], turns[20][0]):
        index = next(i for i, message in enumerate(messages)
                     if message.get('text') == question)
        reply = messages[index + 1]['text']
        normalized = re.sub(r'[\s{}]', '', reply).replace(r'\dfrac', r'\frac')
        assert r'x=\frac54' in normalized or 'x=5/4' in normalized or 'x=1.25' in normalized, reply
        assert r'x=-\frac54' not in normalized and 'x=-5/4' not in normalized, reply


def page():
    text = (ROOT / 'site/2/q03/index.html').read_text()
    return text, json.loads(re.search(r'id="practice-config">\s*(.*?)</script>', text, re.S)[1])

def choose(value):
    return [operation('choice', value), operation('submit')]

def check(first, second):
    return [operation('fill', first, 0), operation('fill', second, 1), operation('submit')]

def actions():
    return ([operation('method', 'discriminant')]
            + check('all_real', 'nonzero') + check('all_real', 'maybe_zero')
            + choose('only_one') + choose('both_hold') + choose('one_holds')
            + choose('down_touch') + choose('up_apart') + choose('down_below')
            + choose('le') + choose('ge') + choose('lt')
            + choose('outside') + choose('closed_left') + choose('between')
            + choose('only_second') + choose('intersection') + choose('union')
            + check('holds', 'holds') + check('fails', 'holds'))

def specs(text):
    return [json.loads(html.unescape(s)) for s in re.findall(r'data-quadratic-graph="([^"]+)"', text)]

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
    assert 'href="/2/"' in text and 'Q03' in text
    assert not re.search(r'\$k\b|\bk\$|\bk\b|个k', text + json.dumps(lesson, ensure_ascii=False))
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

def test_graphs_are_instances_of_the_problem_or_marked_hypothetical():
    text, _ = page()
    found = specs(text)
    assert found and all(spec.get('markSign') == 'above' and spec.get('strict') for spec in found)
    for spec in found:
        if spec['variable'] == 'a':
            assert spec['coefficient'] == 5 and spec['vertex'] == [0.2, -3.2]
            continue
        if spec['uid'].endswith('-cond-up'):
            assert '示意' in spec['title'] and '不是本题' in spec['description']
            continue
        leading = spec['coefficient']
        if leading == 0:
            assert spec['uid'].endswith('-boundary-flat') and spec['vertex'][1] == -1, 'a = 1 gives f(x) = -1'
            continue
        def vertex(a):
            b = -(a - 1)
            x = -b / (2 * leading)
            return [x, leading * x * x + b * x - 1]
        candidates = {math.sqrt(leading + 1), -math.sqrt(leading + 1)}
        assert any(all(math.isclose(u, v, abs_tol=1e-9) for u, v in zip(vertex(a), spec['vertex'])) for a in candidates), spec['uid']

def test_chapter_lists_and_serves_q03():
    with TestClient(create_app(Tutor())) as client:
        home = client.get('/2/').text
        assert home.count('href="/2/q03/"') == 1 and f'<strong>{home.count(CARD)}</strong>' in home
        assert client.get('/2/q03/').status_code == 200
        response = client.post('/api/tutor-demo/sessions', json={'lesson_id': ID})
        assert response.status_code == 201 and response.json()['lesson_id'] == ID
        for path in re.findall(r'(?:href|src)="(/[^"#]+)"', page()[0]):
            if path != '/': assert client.get(path).status_code == 200, path
