"""The illustration retains exact holes, finite domains and answer visibility."""
import json
import subprocess

import pytest
import sympy as sp
from shuxueshuo_server.graph_lesson import parity_parameter_math as math
from shuxueshuo_server.graph_lesson import parity_parameter_original as original
from shuxueshuo_server.graph_lesson.stage_three.contracts import ROOT
from shuxueshuo_server.graph_lesson.stage_three.interaction_graph_contract import (
    validate_part_graphs,
)
from shuxueshuo_server.graph_lesson.stage_three.parity_parameter_graphs import (
    _graph,
    _instance,
    solution_graph,
)
from shuxueshuo_server.graph_lesson.stage_three.parity_parameter_presentation import (
    compile_cards,
)
from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value
from tests.solver.test_graph_parity_parameter import candidate, description


@pytest.mark.parametrize('expr,prop,facts', [
    ('(x^2-1)^2+m*x', 'even', ()),
    ('(x-m)/(x-m)', 'even', ()),
    ('m/(x^2-2)', 'even', ()),
    ('abs(x+1)+m*abs(x-1)', 'even', ()),
    ('piecewise(-1,x<0,m,x=0,1,x>0)', 'odd', ()),
    ('sqrt(x^2+m)', 'even', ()),
    ('sqrt(m-x^2)', 'odd', ()),
    ('m*x^4+1', 'odd', ('Dom(f)={-1,1}',)),
])
def test_checked_cards_and_graphs_render_without_leaking_answers(expr, prop, facts, tmp_path):
    d = description(candidate(expr, prop, facts=facts, goal_kind='find_range'))
    model = math.solve(d)
    parts = []
    domain = original.solve_domain(d) if d['analysis_mode'] == 'original' else {}
    for phase, evidence in [('domain', domain), ('identity', []), ('compare', model['comparison']), ('solve', model), ('verify', model)]:
        values = encode_value({'phase': phase, 'description': d, 'evidence': evidence})
        compiled = compile_cards([{'values': values}], 'test-' + phase)['parts']
        validate_part_graphs(compiled)
        if phase != 'verify':
            assert all('completion_graph' not in p and 'completion_graphs' not in p for p in compiled)
        for part in compiled:
            if part['interaction']['type'] != 'read':
                assert part['stem_board']['items'][1]['math'] is None
        parts += compiled
    target = tmp_path / 'parts.json'
    target.write_text(json.dumps(parts, ensure_ascii=False))
    # Exercise actual shared SVG + KaTeX code against backend-generated shapes.
    check = subprocess.run(['node', str(ROOT/'tools/tests/fixtures/parity-r2-render-check.mjs'), str(target)],
                           check=False, capture_output=True, text=True)
    assert check.returncode == 0, check.stdout + check.stderr


def test_original_cancelled_hole_is_open_and_not_bridged():
    d = description(candidate('(x-m)/(x-m)'))
    model = math.solve(d)
    x, domain, parts, discrete = _instance(d, model, sp.S.Zero)
    assert domain == sp.S.Reals-sp.FiniteSet(0)
    graph = _graph(d, sp.S.Zero, x, domain, parts, discrete)
    trace = graph['params']['traces'][0]
    assert trace['markers'] == [{'x': 0., 'y': 1., 'closed': False}]
    assert len(trace['segments']) == 2
    assert all(all(x < 0 for x, _ in s) or all(x > 0 for x, _ in s) for s in trace['segments'])


@pytest.mark.parametrize('expr,facts', [
    ('x^2+m*x', ('degree(f)=2',)),
    ('m*x', ('degree(f)=2',)),
    ('x^2+m*x', ('Dom(f)=[-1,1]', 'degree(f)=2')),
    ('m*x', ('Dom(f)=[-1,1]', 'degree(f)=2')),
    ('x^4+m*x', ('degree(f)=4',)),
    ('m*x', ('degree(f)=4',)),
    ('sqrt(m*x^2)', ()),
    ('sqrt(m*x^2+1)', ()),
])
def test_constant_conditions_have_student_wording_on_every_parameter_route(expr, facts):
    d = description(candidate(expr, 'odd', facts=facts))
    model = math.solve(d)
    for phase in ('solve', 'verify'):
        values = encode_value({'phase': phase, 'description': d, 'evidence': model})
        cards = compile_cards([{'values': values}], 'constant-' + phase)['parts']
        displayed = json.dumps(cards, ensure_ascii=False)
        assert r'\text{True}' not in displayed and r'\text{False}' not in displayed


def test_singleton_domain_is_a_point_without_a_fabricated_curve():
    d = description(candidate('sqrt(m-x^2)', 'odd'))
    model = math.solve(d)
    instance = _instance(d, model, sp.S.Zero)
    assert instance[1] == sp.FiniteSet(0)
    trace = _graph(d, sp.S.Zero, *instance)['params']['traces'][0]
    assert trace['segments'] == []
    assert trace['markers'] == [{'x': 0., 'y': 0., 'closed': True}]


def test_domain_symmetry_alone_substitutes_the_parameter():
    from shuxueshuo_server.graph_lesson import parity_parameter_original as original
    from shuxueshuo_server.graph_lesson.stage_three.parity_parameter_runtime import (
        card_plan,
    )
    d = description(candidate('(x-m)/(x-m)', 'even', goal_kind='find_range'))
    assert card_plan(d) == {'value': False, 'merge': False}
    model = original.solve(d)
    cards = [part for phase, evidence in [('domain', original.solve_domain(d)), ('verify', model)] for part in compile_cards(
        [{'values': encode_value({'phase': phase, 'description': d, 'evidence': evidence})}], phase)['parts']]
    assert [c['title'] for c in cards] == ['求定义域', '检查定义域是否关于原点对称', '代回核验']
    assert r'$$x - m\ne0$$' in cards[0]['stem_board']['lines']
    assert r'$$m=0\text{ 时，}D=\{x\mid x\ne 0\}$$' in cards[0]['stem_board']['lines']
    assert cards[1]['interaction']['type'] != 'read'
    assert cards[2]['question'] == '把 $m=0$ 代入原式检查。'
    assert r'$$f(-x)=\frac{- x}{- x}=1$$' in cards[2]['stem_board']['lines']


def test_radical_route_discusses_each_parameter_range_then_unions():
    from shuxueshuo_server.graph_lesson import parity_parameter_original as original
    d = description(candidate('sqrt(m*x^2)', 'odd', goal_kind='find_range'))
    model = original.solve(d)
    cards = {phase: compile_cards([{'values': encode_value({'phase': phase, 'description': d, 'evidence': evidence})}],
                                  phase)['parts'][0]
             for phase, evidence in [('domain', original.solve_domain(d)), ('compare', model['comparison']), ('solve', model), ('verify', model)]}
    assert r'\text{定义域由根号内非负确定}' in cards['domain']['completion_board']['items'][0]['math']
    discussion, results = (item['math'] for item in cards['compare']['stem_board']['items'])
    assert r'm\ge 0\text{ 时：}D=\mathbb R\text{，需 }f(x)=0\text{ 恒成立}' in discussion
    assert r'm<0\text{ 时：}D=\{0\}\text{，}f(0)=0' in discussion
    assert results == r'\begin{gathered}m\ge 0\text{ 时：}m=0\\m<0\text{ 时：}\text{都满足}\end{gathered}'
    assert '\\alpha' not in json.dumps(cards, ensure_ascii=False)
    assert cards['solve']['title'] == '取并集'
    assert cards['verify']['completion_board']['items'][1]['math'].startswith(r'\begin{gathered}m=0\text{ 时，}f(-x)=0')


def test_value_conditions_keep_the_full_original_route():
    from shuxueshuo_server.graph_lesson.stage_three.parity_parameter_runtime import (
        card_plan,
    )
    for expr in ('piecewise(x^2+m,x>0,m,x=0,-x^2-m,x<0)', 'sqrt(m*x^2)'):
        assert card_plan(description(candidate(expr, 'odd', goal_kind='find_range'))) == {'value': True, 'merge': True}


def test_verify_shows_one_accepted_graph_without_number_lines():
    d = description(candidate('x^4+m*x', 'even', facts=('degree(f)=4',)))
    model = math.solve(d)
    graph = solution_graph(d, model)
    assert graph['params']['title'].startswith('m=0 ')
    assert '重合' in graph['caption']
    values = encode_value({'phase': 'verify', 'description': d, 'evidence': model})
    part, = compile_cards([{'values': values}], 'verify')['parts']
    assert part['completion_graph'] == graph
    assert 'completion_graphs' not in part and 'condition_number_lines' not in part
    assert part['question'] == '把 $m=0$ 代入原式检查。'
    assert r'$$f(-x)=x^{4}$$' in part['stem_board']['lines']


@pytest.mark.parametrize('expr,prop,facts,expected', [
    ('piecewise(m,x<0,1,x>0)', 'odd', (), r'D=\{x\mid x\ne 0\}'),
    ('piecewise(m/(x-1),x<0,-1/(x+1),x>=0)', 'even', (), r'D=\mathbb R'),
    ('m/x', 'even', ('Dom(f)={-1,1}',), r'D=\left\{-1, 1\right\}'),
])
def test_domain_card_uses_child_result_and_substitution_keeps_the_same_domain(expr, prop, facts, expected, monkeypatch):
    from shuxueshuo_server.graph_lesson.stage_three.math_values import latex
    from shuxueshuo_server.graph_lesson.stage_three.parity_original_presentation import (
        phase_views,
    )
    d = description(candidate(expr, prop, facts=facts, goal_kind='find_range'))
    proof, model = original.solve_domain(d), original.solve(d)
    # Formatting the domain must consume the submethod result, without silently
    # rebuilding a different domain from all denominator holes.
    monkeypatch.setattr('shuxueshuo_server.graph_lesson.stage_three.parity_parameter_runtime.domain_decides', lambda _: False)
    monkeypatch.setattr(original, 'source', lambda _: pytest.fail('presentation recomputed the source domain'))
    domain_card = phase_views({'description': d, 'phase': 'domain', 'evidence': proof})[0]
    assert expected in domain_card['derivation']['items'][1]['math']
    value, = model['feasible_set']
    domain = original.domain_at(d, model['comparison'], value)
    verify_card = phase_views({'description': d, 'phase': 'verify', 'evidence': model})[0]
    assert 'D=' + latex(domain) in verify_card['derivation']['items'][0]['math']


def test_declared_real_domain_is_not_replaced_by_radical_singleton():
    from shuxueshuo_server.graph_lesson.stage_three.parity_original_presentation import (
        phase_views,
    )
    d = description(candidate('sqrt(m*x^2)', 'odd', facts=('Dom(f)=ℝ',), goal_kind='find_range'))
    model = original.solve(d)
    for phase, evidence in [('domain', original.solve_domain(d)), ('compare', model['comparison']), ('verify', model)]:
        card = phase_views({'description': d, 'phase': phase, 'evidence': evidence})[0]
        text = json.dumps(card, ensure_ascii=False)
        assert r'D=\\{0\\}' not in text
        assert r'D=\\mathbb R' in text
