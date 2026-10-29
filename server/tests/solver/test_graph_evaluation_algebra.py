"""Expanded rational calculations preserve source order, signs and equality."""

from copy import deepcopy
import json
from pathlib import Path

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.function_evaluation import evaluate
from shuxueshuo_server.graph_lesson.stage_one.function_evaluation import inspect_evaluation_target
from shuxueshuo_server.graph_lesson.stage_three.evaluation_algebra import (
    _rational_sum_steps, rational_sum_derivation,
)
from tests.solver.test_graph_function_evaluation_math import CALL, N, U, X, description, function


def proof(desc):
    result = evaluate(desc)
    return result, rational_sum_derivation(desc, result['calls'], result.get('value'))


def test_q29_keeps_original_target_and_supplies_fraction_simplification_steps():
    fixture = Path(__file__).parent / 'fixtures/function-evaluation/q29b-candidate.json'
    desc = inspect_evaluation_target(json.loads(fixture.read_text()), '/root/goals/0')
    result, rendered = proof(desc)
    assert rendered
    rows = rendered.removeprefix(r'\begin{gathered}').removesuffix(r'\end{gathered}').split(r'\\')
    assert rows[0] == r'f\left(x\right)+f\left(\frac{1}{x}\right)'
    assert r'\frac{1}{x}' in rows[1]  # The first substitution retains the complex fraction.
    assert rows[2] == r'=\frac{x + 2}{x + 1}+\frac{2 x + 1}{x + 1}'
    assert rows[3] == r'=\frac{\left(x + 2\right)+\left(2 x + 1\right)}{x + 1}'
    assert rows[4] == r'=\frac{3 x + 3}{x + 1}'
    assert rows[5] == '=3'
    assert result['domain'] == sp.S.Reals - sp.FiniteSet(-1, 0)


@pytest.mark.parametrize(('name', 'variable', 'a', 'b'), [('h', 't', 5, -2), ('p', 's', -2, 7)])
def test_coefficients_and_variable_names_are_not_tied_to_q29(name, variable, a, b):
    body = ['/', ['+', ['*', N(a), U], N(b)], ['+', U, N(1)]]
    desc = description(['+', CALL(name, X), CALL(name, ['/', N(1), X])], [function(name, body)], kind='check_constant')
    desc['variable'] = variable
    result, rendered = proof(desc)
    assert result['value'] == a + b
    assert rendered.startswith(r'\begin{gathered}' + name + r'\left(' + variable + r'\right)+')
    assert rendered.endswith('=' + str(a + b) + r'\end{gathered}')
    steps = _rational_sum_steps(desc, result['calls'], result['value'])
    assert len(steps) >= 6
    assert all(sp.cancel(expression - result['value']) == 0 for _, expression in steps)


def test_subtraction_stays_subtraction_when_the_numerators_are_combined():
    h = function('h', ['/', ['+', ['*', N(3), U], N(2)], ['+', U, N(1)]])
    k = function('k', ['/', ['+', ['*', N(2), U], N(1)], ['+', U, N(1)]])
    desc = description(['-', CALL('h', X), CALL('k', X)], [h, k], kind='check_constant')
    result, rendered = proof(desc)
    assert result['value'] == 1
    assert r'h\left(x\right)-k\left(x\right)' in rendered
    assert r'\frac{\left(3 x + 2\right)-\left(2 x + 1\right)}{x + 1}' in rendered
    assert r'\frac{x + 1}{x + 1}' in rendered
    assert all(sp.cancel(expression - 1) == 0 for _, expression in _rational_sum_steps(desc, result['calls'], 1))


def test_rational_coefficients_use_an_exact_common_denominator():
    h = function('h', ['/', N(1), U])
    k = function('k', ['/', ['-', ['*', N(2), U], N(1)], ['*', N(2), U]])
    desc = description(['+', CALL('h', ['*', N(2), X]), CALL('k', X)], [h, k], kind='check_constant')
    result, rendered = proof(desc)
    assert result['value'] == 1 and rendered
    assert all(sp.cancel(expression - 1) == 0 for _, expression in _rational_sum_steps(desc, result['calls'], 1))


def test_unsupported_nonconstant_and_unverified_values_use_existing_fallback():
    f = function('f', ['/', ['+', U, N(2)], ['+', U, N(1)]])
    nested = description(CALL('f', CALL('f', X)), [f])
    assert proof(nested)[1] is None
    polynomial = description(['+', CALL('h', X), CALL('h', X)], [function('h', N(2))], kind='check_constant')
    assert proof(polynomial)[1] is None
    nonconstant = description(['-', CALL('f', X), CALL('f', ['/', N(1), X])], [f], kind='check_constant')
    assert proof(nonconstant)[1] is None
    desc = description(['+', CALL('f', X), CALL('f', ['/', N(1), X])], [f], kind='check_constant')
    result = evaluate(desc)
    assert rational_sum_derivation(desc, result['calls'], 99) is None
    corrupt = deepcopy(result['calls'])
    corrupt[0]['substitution'] += 1
    assert rational_sum_derivation(desc, corrupt, result['value']) is None
    assert rational_sum_derivation({}, [], 3) is None
