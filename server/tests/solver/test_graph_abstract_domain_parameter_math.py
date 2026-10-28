"""General common-input existence for linear calls, independent of a fixture."""

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import (
    abstract_domain_parameter as domain,
)
from shuxueshuo_server.graph_lesson.stage_three import goals, verification
from shuxueshuo_server.graph_lesson.stage_three.context import build_context

TARGET = '/root/goals/0'


def candidate(target='f(x+a)+f(x-a)', known='[0,2]', strength='exact', *, variable='x', parameter='a'):
    return {'original_text': '多个函数调用的共同定义域非空，求参数范围', 'root': {'goals': [{
        'kind': 'find_abstract_domain_parameter', 'known_call': 'f(t)', 'known_domain': known,
        'strength': strength, 'target_call': target, 'variable': variable,
        'parameter': parameter, 'quantifier': 'exists',
    }]}}


@pytest.mark.parametrize(('value', 'expected'), [
    (candidate(), sp.Interval(-1, 1)),
    (candidate(known='(0,2]'), sp.Interval.open(-1, 1)),
    (candidate(known='[0,2)'), sp.Interval.open(-1, 1)),
    (candidate(known='[0,0]'), sp.FiniteSet(0)),
    (candidate('f(x)+f(x+a)+f(x+2*a)'), sp.Interval(-1, 1)),
    (candidate('f(2*x+a)+f(-x+a)'), sp.Interval(0, 2)),
    (candidate('f(x+a)*f(3*x-a)'), sp.Interval(-sp.Rational(1, 2), sp.Rational(3, 2))),
    (candidate('f(x+a)+f(x-2*a)', '[-2,4]'), sp.Interval(-2, 2)),
    (candidate('f(a)+f(x)', '(0,1]'), sp.Interval.Lopen(0, 1)),
    (candidate('f(a)+f(2*a)', '[0,1]'), sp.Interval(0, sp.Rational(1, 2))),
    (candidate('f(2)+f(x+a)', '[0,1]'), sp.S.EmptySet),
    (candidate('f(1)+f(x+a)', '[0,1]'), sp.S.Reals),
    (candidate('f(x+a)-f(x+a)'), sp.S.Reals),
    (candidate('f(x+a)+f(x+a+3)'), sp.S.EmptySet),
    (candidate('f(x+a)+f(x-a+2)'), sp.Interval(0, 2)),
    (candidate('f(x)+f(x+a)', '{1}'), sp.FiniteSet(0)),
    (candidate('f(2*u+k/2)+f(u-k/2)', '[0,3]', variable='u', parameter='k'), sp.Interval(-4, 2)),
])
def test_general_linear_elimination_and_independent_original_projection(value, expected):
    context = build_context(value, TARGET)
    assert domain.admitted(context), context['abstract_domain_parameter_goal']
    solved = domain.solve_abstract_domain_parameter(context)
    assert solved['outputs']['candidate_set'] == expected
    assert domain.independent_verify(value, TARGET, expected)['status'] == 'verified'
    assert verification.verify(value, TARGET, context, expected)['status'] == 'verified'
    assert verification.endpoint_check(value, TARGET, expected)['status'] == 'passed'


@pytest.mark.parametrize('strength', ['exact', 'meaningful_only'])
def test_known_strength_is_retained_in_evidence_and_answer_meaning(strength):
    value = candidate(strength=strength)
    context = build_context(value, TARGET)
    result = domain.solve_abstract_domain_parameter(context)['outputs']
    assert result['candidate_set'] == sp.Interval(-1, 1)
    assert result['parameter_result']['strength'] == strength
    assert result['parameter_result']['meaning'] == (
        'exact_parameter_range' if strength == 'exact' else 'guaranteed_parameter_range')
    assert domain.independent_verify(value, TARGET, result['candidate_set'])['checks'][0]['strength'] == strength


def test_each_call_and_endpoint_source_survives_with_negative_and_zero_x_coefficients():
    context = build_context(candidate('f(-2*x+a)+f(a)'), TARGET)
    result = domain.solve_abstract_domain_parameter(context)['outputs']
    assert result['variable'] == sp.Symbol('x', real=True)
    assert result['parameter'] == sp.Symbol('a', real=True)
    assert result['input_range'] == sp.Interval(0, 2)
    first, second = result['call_ranges']
    a = result['parameter']
    assert first['lower'] == (a - 2) / 2 and first['upper'] == a / 2
    assert first['ast_path'] == [1] and second['ast_path'] == [2]
    assert first['source_ref'] == second['source_ref'] == TARGET + '/target_call'
    assert second['lower'] == -sp.oo and second['upper'] == sp.oo
    assert len(second['parameter_conditions']) == 2
    assert len(result['call_conditions']) == 2


def test_parameter_endpoints_check_common_input_existence_and_witness():
    result = domain.parameter_endpoints(candidate(), TARGET, sp.Interval(-1, 1))
    assert result['status'] == 'passed'
    assert [row['point']['expression'] for row in result['points']] == ['-1', '1']
    assert all(row['holds'] and row['included'] for row in result['points'])
    assert all(row['evidence']['witness']['expression'] == '1' for row in result['points'])
    open_result = domain.parameter_endpoints(candidate(known='(0,2]'), TARGET, sp.Interval.open(-1, 1))
    assert open_result['status'] == 'passed'
    assert all(not row['holds'] and row['evidence']['witness'] is None for row in open_result['points'])


def test_tampered_elimination_coefficients_cannot_self_verify(monkeypatch):
    value = candidate()
    context = build_context(value, TARGET)
    context['abstract_domain_parameter_goal']['calls'][1]['parameter_coefficient'] = '1'
    wrong = domain.solve_abstract_domain_parameter(context)['outputs']['candidate_set']
    assert wrong == sp.S.Reals

    def forbidden(*_):
        raise AssertionError('independent verification reused execution')

    monkeypatch.setattr(domain, 'solve_abstract_domain_parameter', forbidden)
    monkeypatch.setattr(domain, '_known_set', forbidden)
    monkeypatch.setattr(domain, '_relation', forbidden)
    assert domain.independent_verify(value, TARGET, wrong)['status'] == 'verification_failed'
    assert domain.independent_verify(value, TARGET, sp.Interval(-1, 1))['status'] == 'verified'


@pytest.mark.parametrize('wrong', [sp.Interval.open(-1, 1), sp.Interval(-1, 1) - sp.FiniteSet(0),
                                   sp.Interval(-2, 1), sp.S.EmptySet])
def test_complete_parameter_partition_rejects_endpoint_interior_and_empty_tampering(wrong):
    assert domain.independent_verify(candidate(), TARGET, wrong)['status'] == 'verification_failed'


def test_new_goal_closes_exactly_and_detects_display_answer_drift():
    goal = candidate()['root']['goals'][0]
    exact = sp.Interval(-1, 1)
    answer, evidence = goals.finalize_goal_with_evidence(goal, exact)
    assert answer['kind'] == 'find_abstract_domain_parameter' and answer['status'] == 'set'
    assert evidence['checks'][0]['kind'] == 'abstract_domain_parameter_identity'
    assert goals.verify_goal_answer(goal, exact, answer)['checks'][-1]['passed'] is True
    wrong = deepcopy(answer)
    wrong['set']['expression'] = 'Reals'
    with pytest.raises(goals.GoalClosureMismatch):
        goals.verify_goal_answer(goal, exact, wrong)


@pytest.mark.parametrize('relative', [
    'server/shuxueshuo_server/graph_lesson/stage_three/abstract_domain_parameter.py',
    'server/shuxueshuo_server/graph_lesson/stage_one/abstract_domain_parameter.py',
])
def test_parameter_source_module_is_part_of_math_fingerprint(tmp_path, monkeypatch, relative):
    from shuxueshuo_server.graph_lesson.stage_three import runner

    source = runner.ROOT / relative
    read_bytes = Path.read_bytes
    original = read_bytes(source)
    before = runner.fingerprint()
    assert before[relative] == sha256(original).hexdigest()
    changed = tmp_path / source.name
    changed.write_bytes(original + b'\n# mathematical source change\n')
    monkeypatch.setattr(Path, 'read_bytes', lambda path: read_bytes(changed) if path == source else read_bytes(path))
    assert runner.fingerprint()[relative] != before[relative]


@pytest.mark.parametrize(('known', 'expected', 'empty', 'contact_holds'), [
    ('[0,2]', sp.Interval(-1, 1), sp.S.Reals - sp.Interval(-1, 1), True),
    ('(0,2]', sp.Interval.open(-1, 1), sp.S.Reals - sp.Interval.open(-1, 1), False),
])
def test_moving_interval_strategy_uses_checked_complement_and_exact_contact(known, expected, empty, contact_holds):
    outputs = domain.solve_abstract_domain_parameter(build_context(candidate(known=known), TARGET))['outputs']
    strategy = outputs['parameter_result']['overlap_strategy']
    assert outputs['use_complement'] is True
    assert strategy['recommended'] == 'complement'
    assert strategy['reason'] == 'changing_order' and strategy['reason_text']
    assert strategy['empty_overlap_parameters'] == empty
    assert strategy['complement_base'] == sp.S.Reals
    assert strategy['constant_guard_set'] == sp.S.Reals
    assert strategy['complement_parameters'] == strategy['legal_parameters'] == expected
    assert strategy['agrees_with_direct'] is True
    diagram = outputs['parameter_result']['overlap_diagram']
    assert diagram['parameter'] == 'a' and diagram['variable'] == 'x'
    assert diagram['critical_values'] == [-1.0, 0.0, 1.0]
    assert diagram['parameter_min'] < -1 < diagram['initial'] < 1 < diagram['parameter_max']
    assert [row['label'] for row in diagram['intervals']] == ['A', 'B']
    assert diagram['intervals'][0]['lower'] == {
        'slope': -1.0, 'intercept': 0.0, 'slope_exact': '-1', 'intercept_exact': '0'}
    assert diagram['intervals'][1]['upper'] == {
        'slope': 1.0, 'intercept': 2.0, 'slope_exact': '1', 'intercept_exact': '2'}
    contacts = [row for row in diagram['snapshots'] if row['relation'] == 'touching']
    assert len(contacts) == 2 and all(row['holds'] is contact_holds for row in contacts)
    assert {'separated', 'touching', 'overlapping'} <= {row['relation'] for row in diagram['snapshots']}


@pytest.mark.parametrize(('value', 'reason'), [
    (candidate('f(x+a)+f(x+a+1)'), 'fixed_order'),
    (candidate('f(x)+f(x+a)+f(x+2*a)'), 'multiple_intervals'),
    (candidate(known='{1}'), 'point_domains'),
    (candidate('f(a)+f(x)'), 'parameter_guards'),
])
def test_direct_strategy_is_structural_not_problem_identity(value, reason):
    outputs = domain.solve_abstract_domain_parameter(build_context(value, TARGET))['outputs']
    strategy = outputs['parameter_result']['overlap_strategy']
    assert outputs['use_complement'] is False
    assert strategy['recommended'] == 'direct' and strategy['reason'] == reason
    assert strategy['legal_parameters'] == outputs['candidate_set']


def test_complement_evidence_intersects_parameter_only_guards_after_reals_complement():
    value = candidate('f(x+a)+f(x-a)+f(a)')
    outputs = domain.solve_abstract_domain_parameter(build_context(value, TARGET))['outputs']
    strategy = outputs['parameter_result']['overlap_strategy']
    assert strategy['recommended'] == 'direct'
    assert strategy['constant_guard_set'] == sp.Interval(0, 2)
    assert strategy['empty_overlap_parameters'] == sp.S.Reals - sp.Interval(-1, 1)
    assert strategy['complement_parameters'] == outputs['candidate_set'] == sp.Interval(0, 1)
    assert strategy['agrees_with_direct'] is True
    assert strategy['constant_guard_conditions']


def test_wrong_reverse_separation_solution_is_rejected_before_presentation(monkeypatch):
    from shuxueshuo_server.graph_lesson.stage_three import capabilities

    original = capabilities.solve_conditions

    def wrong_separation(conditions, *args, **kwargs):
        result = original(conditions, *args, **kwargs)
        if len(conditions) == 1 and hasattr(conditions[0], 'rel_op'):
            result['outputs']['solution'] = sp.S.EmptySet
        return result

    monkeypatch.setattr(capabilities, 'solve_conditions', wrong_separation)
    with pytest.raises(capabilities.LocalCheckFailed, match='complement_disagrees_with_direct'):
        domain.solve_abstract_domain_parameter(build_context(candidate(), TARGET))


@pytest.mark.parametrize('value', [candidate(), candidate(known='(0,2]'),
                                  candidate('f(x+a)+f(x-a)+f(a)'), candidate('f(a)+f(2*a)')])
def test_interval_explorer_is_json_native_and_solver_checkpoint_is_serializable(value):
    from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value

    result = domain.solve_abstract_domain_parameter(build_context(value, TARGET))
    outputs = result['outputs']
    json.dumps(encode_value(result), allow_nan=False)
    diagram = outputs['parameter_result']['overlap_diagram']
    assert json.loads(json.dumps(diagram, allow_nan=False)) == diagram
    for row in diagram['intervals']:
        assert type(row['left_open']) is bool and type(row['right_open']) is bool
    for case in outputs['parameter_result']['overlap_strategy']['separation_cases']:
        assert type(case['contact_excluded']) is bool


@pytest.mark.parametrize(('value', 'required_cut', 'required_coefficient'), [
    (candidate('f(x+a)+f(x-2*a)', '[0,1]'), '1/3', '-1'),
    (candidate(known='[0,1/100000000000000000000]'), '1/200000000000000000000', '-1'),
    (candidate('f(x+a)+f(x-a+20000000000000000)', '[0,1]'),
     '19999999999999999/2', '-20000000000000000'),
])
def test_interval_diagram_keeps_exact_rationals_for_contacts_and_affine_endpoints(
        value, required_cut, required_coefficient):
    outputs = domain.solve_abstract_domain_parameter(build_context(value, TARGET))['outputs']
    diagram = outputs['parameter_result']['overlap_diagram']
    exact = diagram['critical_exact_values']
    assert required_cut in exact
    assert [float(sp.Rational(point)) for point in exact] == diagram['critical_values']
    assert exact == [row['expression'] for row in diagram['critical_parameters']]
    coefficients = [endpoint[field] for row in diagram['intervals']
                    for endpoint in (row['lower'], row['upper'])
                    for field in ('slope_exact', 'intercept_exact')]
    assert required_coefficient in coefficients
    assert all(str(sp.Rational(coefficient)) == coefficient for coefficient in coefficients)
    assert json.loads(json.dumps(diagram, allow_nan=False)) == diagram
    if required_coefficient == '-20000000000000000':
        assert len(set(exact)) > len(set(diagram['critical_values']))
