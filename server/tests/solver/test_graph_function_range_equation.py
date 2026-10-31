"""M4 degree degeneracy, real preimages and layered method selection."""

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.function_range import (
    EQUATION_METHOD,
    FRACTION_METHOD,
    admitted,
    image_endpoints,
    independent_verify,
)
from shuxueshuo_server.graph_lesson.stage_three.range_equation import (
    solve_equation_range,
)
from shuxueshuo_server.graph_lesson.stage_three.selection import evaluate_goal
from tests.solver.test_graph_function_range import TARGET, candidate

CASES = [
    ('(2*x^2+3*x+2)/(x^2+x+1)', sp.Interval(1, sp.Rational(7, 3)), 'linear'),
    ('(2*x^2-2*x+1)/(x^2-x+1)', sp.Interval.Ropen(sp.Rational(2, 3), 2), 'inconsistent'),
    ('(x^2+1)/(x^2+1)', sp.FiniteSet(1), 'identity'),
    ('0/(x^2+1)', sp.FiniteSet(0), 'identity'),
    ('x/(-x^2-1)', sp.Interval(-sp.Rational(1, 2), sp.Rational(1, 2)), 'linear'),
    ('1/(x^2+1)', sp.Interval.Lopen(0, 1), 'inconsistent'),
    ('(x^2-x)/(x^2-x+1)', sp.Interval.Ropen(-sp.Rational(1, 3), 1), 'inconsistent'),
    ('(x^2+2*x+2)/(x^2+1)', sp.Interval( sp.Rational(3,2)-sp.sqrt(5)/2, sp.Rational(3,2)+sp.sqrt(5)/2), 'linear'),
]


@pytest.mark.parametrize('index,special,attainable', [(0, 2, True), (1, 2, False), (2, 1, True), (4, 0, True)])
def test_equation_cards_keep_equation_context_and_conclude_output_attainability(index, special, attainable):
    from shuxueshuo_server.graph_lesson.stage_three.range_presentation import phase_view

    values = solve_equation_range(build_context(candidate(CASES[index][0], 'ℝ'), TARGET))['outputs']
    for phase in ('equation_degenerate', 'equation_discriminant', 'equation_merge'):
        card = phase_view({**values, 'phase': phase})
        assert '当前关于 $x$ 的方程为 $' in card['question']
        assert '=0$' in card['question']
        assert 'f(x)' not in card['question']
    card = phase_view({**values, 'phase': 'equation_degenerate'})
    verdict = '可以取到' if attainable else '不能取到'
    assert f'y={special}' in card['derivation']['items'][0]['math']
    assert rf'y={special}\text{{{verdict}}}' in card['derivation']['items'][1]['math']
    correct = next(option for option in card['interaction']['options']
                   if option['value'] in card['expected_answer']['one_of'])
    assert f'$y={special}$ {verdict}' in correct['label']
    if index == 0:
        assert 'x=0' in correct['label'] and '$y=0$' not in correct['label']


@pytest.mark.parametrize('expression,expected,kind', CASES)
def test_real_root_image_all_degree_branches(expression, expected, kind):
    value = candidate(expression, 'ℝ'); context = build_context(value, TARGET)
    assert admitted(context, EQUATION_METHOD)
    solved = solve_equation_range(context)['outputs']
    assert solved['feasible_set'] == expected
    mapping = solved['description']['equation_mapping']
    assert mapping['degenerate_kind'] == kind
    assert (mapping['degenerate_image'] & mapping['quadratic_image']) is sp.S.EmptySet
    assert independent_verify(value, TARGET, context, expected)['status'] == 'verified'
    assert image_endpoints(value, TARGET, expected)['status'] == 'passed'
    assert independent_verify(value, TARGET, context, expected.symmetric_difference(sp.FiniteSet(42)))['status'] == 'math_failed'


@pytest.mark.parametrize('expression,domain', [
    ('x/(x^2-1)', 'ℝ'), ('1/x', 'ℝ'), ('x^2/2', 'ℝ'), ('1/(x^2+1)', '[0,1]'),
    ('(x/x)/(x^2+1)', 'ℝ'), ('1/(x^3+1)', 'ℝ'), ('x^3/(x^2+1)', 'ℝ'),
])
def test_m4_preserves_scope_and_original_holes(expression, domain):
    assert not admitted(build_context(candidate(expression, domain), TARGET), EQUATION_METHOD)


@pytest.mark.parametrize('index', [0, 1])
def test_rational_method_selection_keeps_math_and_execution_distinct(index):
    value = candidate(CASES[index][0], 'ℝ')
    selection = evaluate_goal(value, TARGET, [], 'type-function-range')
    assert selection['d3']['interaction']['type'] == 'method_cards'
    assert selection['d3']['interaction']['checks'] == []
    assert selection['d3']['expected_answer']['checks'] == {}
    branches = {v['branch']: v for v in selection['selection']['branches']}
    assert branches['equation']['applicability'] == 'applicable'
    assert branches['fraction']['applicability'] == 'applicable'
    assert branches['fraction']['recommendation'] == ('preferred' if index else 'optional')
    assert admitted(build_context(value, TARGET), FRACTION_METHOD)


@pytest.mark.parametrize('expression,domain', [('1/x','ℝ'), ('x/(x^2+1)','(0,1)'), ('(x/x)/(x^2+1)','ℝ')])
def test_rational_cards_keep_m4_visible_but_reject_illegal_preimages(expression, domain):
    selection = evaluate_goal(candidate(expression, domain), TARGET, [], 'type-function-range')
    branches = {v['branch']: v for v in selection['selection']['branches']}
    assert branches['fraction']['applicability'] == 'applicable'
    assert branches['equation']['applicability'] == 'unknown'
    assert '域内实根筛选' in selection['d3']['verdicts']['equation']['message']
    assert selection['d3']['interaction']['checks'] == []


@pytest.mark.parametrize('domain,declared', [
    ('[1,2]∪{3,4}', None),
    ('{0}', None),
    ('ℝ', 'ℝ'),
])
def test_rational_selection_rejects_unsupported_input_without_execution_error(domain, declared):
    value = candidate('1/x', domain)
    if declared is not None:
        value['root']['facts'] = [f'Dom(f)={declared}']
    selection = evaluate_goal(value, TARGET, [], 'type-function-range')
    assert selection['status'] == 'no_applicable_method'
    assert selection['selection']['branches'] == []
    assert selection['d3'] is None and selection['d4'] is None


@pytest.mark.stage_three_db
@pytest.mark.parametrize('index', [0, 1, 2])
def test_real_root_complete_lesson(tmp_path, index):
    from shuxueshuo_server.graph_lesson.stage_three import runner
    from tests.solver.test_graph_stage_three_execution import (
        constructed_upstream,
        store,
    )
    from tools.export_graph_walk_course import export_course
    expression, expected, _ = CASES[index]
    upstream = constructed_upstream(tmp_path, candidate(expression, 'ℝ'))
    output = tmp_path/'run'
    result = runner.run_sample(upstream, output)
    assert result['status'] == 'completed', result
    goal = result['goals'][0]
    assert goal['status'] == 'solved', goal
    assert sp.sympify(goal['answer']['set']['expression']) == expected
    assert any(route['method'] == EQUATION_METHOD and route['status'] == 'verified' for route in goal['routes'])
    snapshot = store(output).snapshot()
    assert all(row['status'] == 'interactive' for row in snapshot['interaction_states']), snapshot['interaction_states']
    course = export_course(output, 'function-concepts-range-q06')
    assert course['lesson']['goals'][0]['walk'] is not None
