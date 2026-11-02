"""A2: exact fractional substitution without erasing original domain holes."""

from copy import deepcopy
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.function_formula import recover, verify
from shuxueshuo_server.graph_lesson.stage_three.formula_presentation import compile_formula
from shuxueshuo_server.graph_lesson.stage_three.formula_runtime import solve_function_formula
from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value
from tests.solver.test_graph_function_formula import TARGET, build_context, candidate, description


@pytest.mark.parametrize('relation,expected,source_holes,image_holes', [
    ('f(x/(x+1))=x-1', '(2*t-1)/(1-t)', [-1], [1]),
    ('f((2*x+3)/(x-2))=x**2', '((2*t+3)/(t-2))**2', [2], [2]),
    ('f(1/x)=1/(x-2)', 't/(1-2*t)', [0, 2], [0, sp.Rational(1, 2)]),
    ('f((x/2-3)/(2*x+1))=0', '0', [sp.Rational(-1, 2)], [sp.Rational(1, 4)]),
    ('f(x/(x+1))=(x-2)/(x-2)', '1', [-1, 2], [1, sp.Rational(2, 3)]),
    ('f((x*(x-2))/((x+1)*(x-2)))=x', 't/(1-t)', [-1, 2], [1, sp.Rational(2, 3)]),
    ('f(1/(1+1/x))=x', 't/(1-t)', [-1, 0], [1, 0]),
    ('f(x/(x+1))=1/(x*x+1)', '(1-t)**2/((1-t)**2+t**2)', [-1], [1]),
    ('f(x/(x+1))=x+0/(x-2)', 't/(1-t)', [-1, 2], [1, sp.Rational(2, 3)]),
])
def test_fractional_family_keeps_all_original_exclusions(relation, expected, source_holes, image_holes):
    desc = description(candidate(relation))
    assert desc['structure_supported'], desc
    result = recover(desc)
    assert sp.cancel(result['expression']-sp.sympify(expected, locals={'t': result['variable']})) == 0
    assert result['source_domain'] == sp.S.Reals-sp.FiniteSet(*source_holes)
    assert result['determined_domain'] == sp.S.Reals-sp.FiniteSet(*image_holes)
    assert result['inverse_root'] is None
    assert verify(desc, result)
    assert not verify(desc, {**result, 'determined_domain': sp.S.Reals})


@pytest.mark.parametrize('relation,fields', [
    ('f((2*x+2)/(x+1))=x', {}),
    ('f((x*x+1)/(x+1))=x', {}),
    ('f(x/(x+1))=1/(x*x-2)', {}),
    ('f(x/(x+1))=x**3', {}),
    ('f(x/(x+1))=1/(x-x)', {}),
    ('f((a*x+1)/(x+1))=x', {}),
    ('f(x/(x+1))=x', {'relation_domain': '[0,+∞)'}),
    ('f(x/(x+1))=x', {'declared_domain': '[0,+∞)'}),
    ('f(x/(x+1))=x', {'function_type': 'quadratic'}),
    ('f(x/(x+1))=1/x+1/(x-1)+1/(x-2)+1/(x-3)', {}),
])
def test_outside_frozen_scope_is_not_silently_simplified(relation, fields):
    value = candidate(relation, **fields)
    before = deepcopy(value)
    assert not description(value)['structure_supported']
    assert value == before


def test_constant_answer_still_cannot_determine_the_missing_function_value():
    desc = description(candidate('f(x/(x+1))=7', declared_domain='ℝ', requested_domain='ℝ'))
    result = recover(desc)
    assert result['expression'] == 7
    assert result['status'] == 'insufficient_information'
    assert verify(desc, result)
    assert not verify(desc, {**result, 'status': 'determined_on_domain'})


def test_independent_verification_requires_identity_and_a_legal_inverse(monkeypatch):
    desc = description(candidate('f(x/(x+1))=x-1'))
    result = recover(desc)
    monkeypatch.setattr('shuxueshuo_server.graph_lesson.function_formula.recover',
                        lambda _: pytest.fail('verification must not call recover'))
    assert verify(desc, result)
    for field in ('expression', 'inverse_input'):
        assert not verify(desc, {**result, field: result[field]+1})
        t = result['variable']
        hole = sp.Mul(result[field], t-2, sp.Pow(t-2, -1, evaluate=False), evaluate=False)
        assert not verify(desc, {**result, field: hole})
    assert not verify(desc, {**result, 'source_domain': sp.S.Reals})
    assert not verify(desc, {**result, 'determined_domain': result['source_domain']})


@pytest.mark.parametrize('relation,holes', [
    ('f(x/(x+1))=x-1', [1]),
    ('f(1/x)=1/(x-2)', [0, 0.5]),
    ('f(x/(x+1))=(x-2)/(x-2)', [2/3, 1]),
])
def test_fractional_cards_grade_and_preview_the_new_variable_exclusions(relation, holes):
    from shuxueshuo_server.learning.graph_walk import grade
    data = solve_function_formula(build_context(candidate(relation), TARGET))['outputs']
    schema = json.loads((Path(__file__).resolve().parents[3]/'internal/schemas/graph-step-interaction-v1.schema.json').read_text())
    validator = Draft202012Validator({'$defs': schema['$defs'], '$ref': '#/$defs/part'})
    for phase in ('input_range', 'inverse', 'rewrite', 'coverage'):
        part = compile_formula([{'values': encode_value({**data, 'phase': phase})}], 'a'*24)['parts'][0]
        validator.validate(part)
        correct = part['expected_answer']['one_of'][0]
        assert grade(part, {'value': correct}, 'function-substitution') == 'passed'
        wrong = [row for row in part['interaction']['options'] if row['value'] != correct]
        assert wrong
        for row in wrong:
            assert grade(part, {'value': row['value']}, 'function-substitution') == 'wrong'
        if phase == 'coverage':
            card = part['answer_completion']
            chosen = next(row for row in card['ranges'] if row['value'] == correct)
            assert chosen['excluded'] == holes
            assert chosen['left'] is chosen['right'] is None
            assert '范围外的函数值' in card['coverage']
            assert '根式' not in str(card)


def test_fraction_source_binding_and_variable_rename():
    from shuxueshuo_server.graph_lesson.stage_two.formula_surface import formula_source_spans
    from shuxueshuo_server.graph_lesson.stage_two.fragments import _abstract_formula_matches
    from shuxueshuo_server.graph_lesson.stage_three.selection import evaluate_goal
    value = candidate('p(t/(t+1))=t-1', function='p', variable='t')
    value['original_text'] = r'已知 $p(\frac{t}{t+1})=t-1$，则 $p(t)=$ ______。'
    desc = description(value)
    assert formula_source_spans(value, TARGET, [(0, len(value['original_text']))], desc, _abstract_formula_matches)
    changed = deepcopy(value)
    changed['original_text'] = changed['original_text'].replace('t+1', 't-1')
    assert formula_source_spans(changed, TARGET, [(0, len(changed['original_text']))], desc, _abstract_formula_matches) is None
    result = recover(desc)
    assert str(result['variable']) == 'z'
    assert verify(desc, result)
    selection = evaluate_goal(value, TARGET, [], 'type-function-formula')
    assert '先令 $z=' in selection['d3']['verdicts']['substitution']['message']
