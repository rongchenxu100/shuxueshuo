"""Original endpoint-choice and named-extremum goals through the range pipeline."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
import sympy as sp
from jsonschema import Draft202012Validator

from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_three import (
    calculations,
    driver,
    interaction,
    verification,
)
from shuxueshuo_server.graph_lesson.stage_three.choice_matching import (
    match_original_choice,
)
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.function_range import admitted
from shuxueshuo_server.graph_lesson.stage_three.goals import (
    GoalClosureMismatch,
    finalize_goal,
    verify_goal_answer,
)
from shuxueshuo_server.graph_lesson.stage_three.handoff import validate_original_choice
from shuxueshuo_server.graph_lesson.stage_three.selection import evaluate_goal
from shuxueshuo_server.graph_lesson.stage_three.trajectory import (
    decode_value,
    encode_value,
)
from shuxueshuo_server.graph_lesson.stage_two.fragments import build_d1
from shuxueshuo_server.graph_lesson.stage_two.recognition import evaluate_types
from shuxueshuo_server.problem_understanding.notation_parser import NotationError
from shuxueshuo_server.problem_understanding.notation_range_tasks import validate_task
from shuxueshuo_server.search.identity import candidate_schema, public_structure_errors
from shuxueshuo_server.search.lesson import d1_rows
from tests.solver.test_graph_stage_three_methods import finish

TARGET = '/root/goals/0'
FIXTURES = Path(__file__).parent / 'fixtures/function-range-tasks'
M3, M4, M5 = 'method-quadratic-interval-range', 'method-equation-real-root-range', 'method-fraction-split-range'


def candidate(name='q05'):
    return json.loads((FIXTURES / (name+'-candidate.json')).read_text())


def solve(c, method):
    features = extract_features(c)
    assert features['ok'], features
    context = build_context(c, TARGET)
    state = finish(driver.create_state(features=features['features'], context=context, method=method,
                                       route_id='range', branch='direct', target_ref=TARGET, run_id='test',
                                       lesson_version='v1', solve_budget_seconds=30))
    assert state['status'] == 'method_complete', state['diagnostics']
    constrained = calculations.dispatch({'operation': 'constraints', 'state': state, 'context': context})
    exact = constrained['feasible_set_exact']
    state['verification'] = verification.verify(c, TARGET, context, decode_value(exact))
    assert state['verification']['status'] == 'verified', state['verification']
    state['feasible_set_exact'] = exact
    boundary = calculations.dispatch({'operation': 'endpoints', 'state': state, 'candidate': c,
                                       'target_ref': TARGET, 'feasible_set_exact': exact})
    state = boundary['state']
    final = calculations.dispatch({'operation': 'finish', 'state': state, 'goal': context['goal'],
                                   'feasible_set_exact': exact, 'previous': []})
    return final['state'], final['answer'], decode_value(exact)


@pytest.mark.parametrize('name,method,label', [('q05', M3, 'D'), ('q08', M4, 'B'), ('q08', M5, 'B')])
def test_original_tasks_reach_verified_answers_and_student_cards(name, method, label):
    c = candidate(name)
    original = deepcopy(c)
    Draft202012Validator(candidate_schema()).validate(c)
    assert not public_structure_errors(c)
    state, answer, feasible = solve(c, method)
    for schema_name in ('graph-stage-three-route-v1', 'graph-stage-three-route-v2', 'graph-stage-three-result-v1'):
        schema = json.loads((Path(__file__).parents[3] / 'internal/schemas' / (schema_name+'.schema.json')).read_text())
        Draft202012Validator({'$defs': schema['$defs'], '$ref': '#/$defs/goalAnswer'}).validate(answer)
    choice = match_original_choice(c, TARGET, answer, encode_value(feasible))
    assert choice['status'] == 'matched', choice
    assert choice['correct_labels'] == [label]
    validate_original_choice(choice, TARGET)
    chunks, pending = interaction.compile_route(state['interaction_seeds'], interaction.load_registry())
    assert not pending
    assert chunks
    assert all(not diagnostics for _, diagnostics in chunks), chunks
    titles = [part['title'] for chunk, _ in chunks for part in chunk['parts']]
    if name == 'q05':
        assert feasible == sp.FiniteSet(3)
        assert [title for title in titles if title.startswith('核对选项')] == [f'核对选项 {label} 的值域' for label in 'ABCD']
        assert titles[-1] == '回答原题'
    else:
        assert feasible == sp.Interval(sp.Rational(5, 2), sp.Rational(7, 2))
        assert decode_value(answer['value']['exact']) == 6
        assert titles[-2:] == ['由值域确定最值', '计算原题所求值']
    assert c == original


@pytest.mark.parametrize('name', ['q05', 'q08'])
def test_source_binding_and_d1_retain_the_actual_target(name):
    c = candidate(name)
    features = extract_features(c)['features']
    supported = [row['type_id'] for row in evaluate_types(features) if row['status'] == 'supported']
    assert supported == ['type-function-range']
    d1 = build_d1(c, TARGET, features, {'items': []})
    assert not d1['diagnostics'], d1
    known = {row['feature_id']: row['value'] for row in features if row['status'] == 'known'}
    rendered = d1_rows(TARGET, d1['fragments'], known, c['original_text'], candidate=c)
    assert rendered['rows']
    assert ('不可能' if name == 'q05' else 'a+b') in rendered['summary']
    selection = evaluate_goal(c, TARGET, features, 'type-function-range')
    assert selection['selection']['branches']
    if name == 'q05':
        assert not selection['d3']['prerequisites']
        assert '不可能' in selection['d3']['question']


@pytest.mark.parametrize('name,before,after', [
    ('q05', '不可能', '可能'), ('q05', '值域为 $[-4,5]$', '值域为 $[-4,4]$'),
    ('q05', '定义域为 $[a,b]$', '定义域为 $(a,b)$'),
    ('q08', '最大值为 $a$', '最大值为 $b$'), ('q08', '$a+b$', '$a-b$'),
])
def test_mismatching_original_roles_ranges_and_polarity_cannot_bind(name, before, after):
    c = candidate(name)
    c['original_text'] = c['original_text'].replace(before, after)
    d1 = build_d1(c, TARGET, extract_features(c)['features'], {'items': []})
    assert d1['diagnostics']


def test_endpoint_options_follow_labels_order_and_requested_polarity():
    c = candidate()
    goal = c['root']['goals'][0]
    goal['select_relation'], goal['selection_mode'] = 'matches', 'multiple'
    goal['options'].reverse()
    goal['options'][0]['label'] = 'Z'
    _, answer, feasible = solve(c, M3)
    assert answer['correct_labels'] == ['C', 'B', 'A']
    assert feasible == sp.FiniteSet(1, 2, 3)
    # Unchanged public alternatives must never inherit reordered solver labels.
    assert match_original_choice(c, TARGET, answer, encode_value(feasible))['status'] == 'unavailable'
    assert public_structure_errors(c)
    assert verification.verify(c, TARGET, build_context(c, TARGET), sp.FiniteSet(0))['status'] == 'math_failed'


def test_changed_quadratic_is_recomputed_not_a_fixture_answer():
    c = candidate()
    c['root']['definitions'] = ['f(x)=x^2-2*x-2']
    c['root']['goals'][0]['expected_range'] = '[-3,6]'
    _, answer, _ = solve(c, M3)
    assert answer['correct_labels'] == ['D']
    c['root']['goals'][0].update(domain_template='(a,b)', selection_mode='multiple')
    _, answer, _ = solve(c, M3)
    assert answer['correct_labels'] == list('ABCD')  # No candidate attains the upper endpoint.


@pytest.mark.parametrize('mutate', [
    lambda g: g['options'][0]['values'].__setitem__(0, '-3'),
    lambda g: g['options'][0].__setitem__('text', '$(4,-2)$'),
    lambda g: g['options'][1].__setitem__('label', 'A'),
    lambda g: g.__setitem__('domain_template', '[b,a]'),
])
def test_bad_option_bindings_fail_before_mathematics(mutate):
    goal = candidate()['root']['goals'][0]
    mutate(goal)
    with pytest.raises(NotationError):
        validate_task(goal)


@pytest.mark.parametrize('extra', [['Dom(f)=[-2,4]'], ['x∈[-2,4]']])
def test_separate_input_restrictions_are_not_silently_intersected_with_candidates(extra):
    c = candidate()
    c['root']['facts'] = extra
    assert not admitted(build_context(c, TARGET), M3)


@pytest.mark.parametrize('expression,expected', [('a-b', 1), ('a*b', sp.Rational(35, 4)), ('a/b', sp.Rational(7, 5)), ('2*a+b', sp.Rational(19, 2))])
def test_extremum_arithmetic_uses_the_requested_expression(expression, expected):
    goal = candidate('q08')['root']['goals'][0]
    goal['expression'] = expression
    answer = finalize_goal(goal, sp.Interval(sp.Rational(5, 2), sp.Rational(7, 2)))
    assert decode_value(answer['value']['exact']) == expected
    wrong = deepcopy(answer)
    wrong['value']['exact'] = encode_value(expected+1)
    with pytest.raises(GoalClosureMismatch):
        verify_goal_answer(goal, sp.Interval(sp.Rational(5, 2), sp.Rational(7, 2)), wrong)


@pytest.mark.parametrize('image', [sp.Interval.open(0, 1), sp.Interval.Ropen(0, 1), sp.Interval(0, sp.oo), sp.S.EmptySet])
def test_unattained_or_unbounded_extrema_do_not_become_values(image):
    goal = candidate('q08')['root']['goals'][0]
    answer = finalize_goal(goal, image)
    assert answer == {'kind': 'find_extrema_expression', 'status': 'undefined', 'reason': 'extremum_not_attained'}


def test_defined_extrema_with_undefined_arithmetic_and_renamed_symbols():
    goal = candidate('q08')['root']['goals'][0]
    goal['extrema'] = [{'symbol': 'u', 'kind': 'minimum'}, {'symbol': 'v', 'kind': 'maximum'}]
    goal['expression'] = 'v/u'
    validate_task(goal)
    assert finalize_goal(goal, sp.Interval(0, 2))['reason'] == 'undefined_expression'
    goal['expression'] = 'u+v'
    answer = finalize_goal(goal, sp.Interval(2-sp.sqrt(3), 2+sp.sqrt(3)))
    assert decode_value(answer['value']['exact']) == 4
    goal['expression'] = 'u+w'
    with pytest.raises(NotationError, match='unknown_symbol'):
        validate_task(goal)


def test_open_bound_and_single_attained_extremum_close_through_real_m3_cards():
    c = candidate('q08')
    c['root']['definitions'] = ['f(x)=-x^2']
    goal = c['root']['goals'][0]
    goal['input_domain'] = '(0,2]'
    state, answer, image = solve(c, M3)
    assert image == sp.Interval.Ropen(-4, 0)
    assert answer['reason'] == 'extremum_not_attained'
    chunks, pending = interaction.compile_route(state['interaction_seeds'], interaction.load_registry())
    assert not pending and all(not diagnostics for _, diagnostics in chunks)
    goal['extrema'], goal['expression'] = [{'symbol': 'b', 'kind': 'minimum'}], 'b+1'
    state, answer, _ = solve(c, M3)
    assert decode_value(answer['value']['exact']) == -3
    assert all('两个边界均可取到' not in fragment['explanation'] for fragment in state['fragments'])


def test_endpoint_arithmetic_cannot_explode_during_extraction():
    from shuxueshuo_server.problem_understanding.notation_parser import parse
    from shuxueshuo_server.problem_understanding.notation_range_tasks import arithmetic

    with pytest.raises(NotationError, match='coefficient_budget'):
        arithmetic(parse('((((2^4)^4)^4)^4)^4'), {})


def test_stage_two_accepts_the_new_goals_with_reviewed_source_evidence(tmp_path):
    from shuxueshuo_server.search.identity import mathematical_candidate
    from tests.solver.test_graph_stage_three_execution import constructed_upstream

    for name in ('q05', 'q08'):
        path = constructed_upstream(tmp_path / name, mathematical_candidate(candidate(name)))
        result = json.loads(path.read_text())
        assert result['status'] == 'completed'
        assert result['goals'][0]['d1']['fragments']
        assert not result['goals'][0]['d1']['diagnostics']


def test_practice_server_requires_all_math_before_the_domain_option_answer():
    from fastapi import HTTPException

    from shuxueshuo_server.learning.graph_walk import ensure_option_prerequisites

    final = {'id': 'original', 'source': 'original_choice', 'matching': 'range_domain_options', 'target_ref': TARGET,
             'interaction': {'type': 'choice', 'field': 'original_choice', 'options': [{'value': x} for x in 'ABCD']},
             'expected_answer': {'one_of': ['D']}}
    steps = [{'id': f'compare-{label}'} for label in 'ABCD']
    contract = {'intro': [], 'routes': {'range': {'steps': [*steps, final]}}}
    with pytest.raises(HTTPException):
        ensure_option_prerequisites(contract, 'range', final, ['compare-A'])
    ensure_option_prerequisites(contract, 'range', final, [row['id'] for row in steps])
