"""R1 basic range routes retain original domains and exact output coverage."""
from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_one.function_range import inspect_range_target
from shuxueshuo_server.graph_lesson.stage_three.capabilities import CapabilityGap
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.function_range import (
    admitted,
    image_endpoints,
    independent_verify,
    inputs,
    polynomial_image,
    transform_function_range,
)
from shuxueshuo_server.graph_lesson.stage_three.range_presentation import (
    domain_prerequisite,
)
from tests.solver.test_graph_function_range import TARGET, candidate


@pytest.mark.parametrize('expression,domain,expected_domain,expected', [
    ('sqrt(-x^2-6*x-5)', '(-∞,+∞)', sp.Interval(-5, -1), sp.Interval(0, 2)),
    ('3-2*sqrt(-x^2-6*x-5)', '(-∞,+∞)', sp.Interval(-5, -1), sp.Interval(-1, 3)),
    ('0*sqrt(-x^2-6*x-5)+7', '(-∞,+∞)', sp.Interval(-5, -1), sp.FiniteSet(7)),
    ('sqrt(x)-1', '(-∞,+∞)', sp.Interval(0, sp.oo), sp.Interval(-1, sp.oo)),
    ('sqrt(x)-1', '(0,4]', sp.Interval.Lopen(0, 4), sp.Interval.Lopen(-1, 1)),
    ('3-2*sqrt(1-x)', '(-∞,+∞)', sp.Interval(-sp.oo, 1), sp.Interval(-sp.oo, 3)),
    ('sqrt(4)-1', '(-∞,+∞)', sp.S.Reals, sp.FiniteSet(1)),
    ('0*sqrt(x-1)', '(-∞,+∞)', sp.Interval(1, sp.oo), sp.FiniteSet(0)),
    ('sqrt(2-x^2)', '(-∞,+∞)', sp.Interval(-sp.sqrt(2), sp.sqrt(2)), sp.Interval(0, sp.sqrt(2))),
    ('sqrt(x^2-2)', '(-∞,+∞)', sp.Union(sp.Interval(-sp.oo, -sp.sqrt(2)), sp.Interval(sp.sqrt(2), sp.oo)), sp.Interval(0, sp.oo)),
    ('2-sqrt(x^2-2)', '[-2,2]', sp.Union(sp.Interval(-2, -sp.sqrt(2)), sp.Interval(sp.sqrt(2), 2)), sp.Interval(2-sp.sqrt(2), 2)),
    ('sqrt(2-x^2)', '(0,sqrt(2))', sp.Interval.open(0, sp.sqrt(2)), sp.Interval.open(0, sp.sqrt(2))),
    ('sqrt(x^2)', '[-1,1]', sp.Interval(-1, 1), sp.Interval(0, 1)),
    ('sqrt(-x^2)', '(-∞,+∞)', sp.FiniteSet(0), sp.FiniteSet(0)),
    ('sqrt(0*x+4)', '(0,1)', sp.Interval.open(0, 1), sp.FiniteSet(2)),
])
def test_exact_radical_image_with_independent_original_verification(expression, domain, expected_domain, expected):
    value = candidate(expression, domain)
    desc = inspect_range_target(value, TARGET)
    assert desc['structure_supported'], desc
    expression, x, actual_domain = inputs(desc)
    assert actual_domain == expected_domain
    inner = polynomial_image(expression, x, actual_domain)['outputs']['feasible_set']
    computed = transform_function_range(desc, inner)
    assert computed['outputs']['feasible_set'] == expected
    context = build_context(value, TARGET)
    assert admitted(context)
    method = 'method-direct-range' if desc['degree'] <= 1 else 'method-quadratic-interval-range'
    assert admitted(context, method)
    other = 'method-quadratic-interval-range' if desc['degree'] <= 1 else 'method-direct-range'
    assert not admitted(context, other)
    proof = independent_verify(value, TARGET, context, expected)
    assert proof['status'] == 'verified', proof
    assert image_endpoints(value, TARGET, expected)['status'] == 'passed'
    outside = expected.sup+1 if expected.sup.is_finite else expected.inf-1
    assert independent_verify(value, TARGET, context, expected | sp.FiniteSet(outside))['status'] == 'math_failed'
    step = domain_prerequisite(desc)
    assert step['interaction']['type'] == 'choice'
    assert step['stem_board']['items'][1]['math'] is None
    assert step['completion_board']['items'][1]['math']


@pytest.mark.parametrize('expression', ['sqrt(-x^2-1)', '0*sqrt(-1)', 'sqrt(-1)', '0*sqrt(-x^2-1)+7'])
def test_empty_original_domain_cannot_become_a_constant_image(expression):
    value = candidate(expression, '(-∞,+∞)')
    with pytest.raises(CapabilityGap, match='range.empty_input'):
        inputs(inspect_range_target(value, TARGET))
    assert not admitted(build_context(value, TARGET))


def test_domain_declaration_conflicts_are_not_silently_intersected():
    value = candidate('sqrt(x)', '[-1,4]')
    assert inputs(inspect_range_target(value, TARGET))[2] == sp.Interval(0, 4)
    declared = deepcopy(value)
    declared['root']['goals'][0].pop('input_domain')
    declared['root']['facts'] = ['Dom(f)=[-1,4]']
    with pytest.raises(CapabilityGap, match='range.declared_domain_conflict'):
        inputs(inspect_range_target(declared, TARGET))
    assert not admitted(build_context(declared, TARGET))


def test_radical_cards_name_the_current_inner_function_and_restore_the_original_function():
    from shuxueshuo_server.graph_lesson.stage_three.capabilities import complete_square
    from shuxueshuo_server.graph_lesson.stage_three.range_presentation import phase_view

    description = inspect_range_target(candidate('sqrt(-x^2-6*x-5)', 'ℝ'), TARGET)
    expression, variable, domain = inputs(description)
    computed = polynomial_image(expression, variable, domain)['outputs']
    values = {'description': description, 'function': expression, 'variable': variable, 'domain': domain,
              **complete_square(expression, variable)['outputs'], **computed}
    original = r'f(x)=\sqrt{-x^{2}-6\cdot x-5}'
    assert original in domain_prerequisite(description)['question']
    for phase in ('position', 'values', 'image'):
        question = phase_view({**values, 'phase': phase})['question']
        assert r'P(x)=- x^{2} - 6 x - 5' in question
        assert original not in question
    root = transform_function_range(description, computed['feasible_set'])['outputs']['root_range']
    assert original in phase_view({**values, 'phase': 'root', 'range': root})['question']


@pytest.mark.parametrize('expression', ['x^2+sqrt(x)', 'x*sqrt(x)', '1/sqrt(x)', 'sqrt(sqrt(x))'])
def test_expression_family_cannot_drop_correlated_or_original_constraints(expression):
    assert not inspect_range_target(candidate(expression, '(-∞,+∞)'), TARGET)['structure_supported']


def test_shared_range_syntax_invalidates_both_mathematical_fingerprints(monkeypatch):
    from pathlib import Path

    from shuxueshuo_server.graph_lesson.stage_three import execution_contracts, runner

    before = runner.fingerprint()
    key = 'server/shuxueshuo_server/graph_lesson/range_syntax.py'
    path = runner.ROOT / key
    revisions = execution_contracts.revisions()
    original = Path.read_bytes
    monkeypatch.setattr(Path, 'read_bytes', lambda item: original(item) + (b'\n# changed\n' if item == path else b''))
    assert runner.fingerprint()[key] != before[key]
    assert execution_contracts.revisions()['range_syntax'] != revisions['range_syntax']
