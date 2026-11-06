"""The same solving task answers different questions through a shared plan."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
import sympy as sp
from jsonschema import Draft202012Validator
from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_three.answer_conversion import (
    convert_goal,
    evaluate,
)
from shuxueshuo_server.graph_lesson.stage_three.answer_conversion_presentation import (
    display_groups,
    phase_view,
)
from shuxueshuo_server.graph_lesson.stage_three.choice_matching import (
    match_original_choice,
)
from shuxueshuo_server.graph_lesson.stage_three.goals import (
    GoalClosureMismatch,
    finalize_goal,
    verify_goal_answer,
)
from shuxueshuo_server.graph_lesson.stage_three.interaction import (
    compile_route,
    load_registry,
)
from shuxueshuo_server.graph_lesson.stage_three.trajectory import (
    decode_value,
    encode_value,
)
from shuxueshuo_server.graph_lesson.stage_three.verification import VerificationGap
from shuxueshuo_server.graph_lesson.stage_two.fragments import build_d1
from shuxueshuo_server.problem_understanding.answer_requests import (
    compile_candidate_plan,
    compile_plan,
    request_for_goal,
    validate_request,
)
from shuxueshuo_server.problem_understanding.notation_compile import (
    NotationValidator,
    Report,
)
from shuxueshuo_server.problem_understanding.notation_parser import NotationError
from shuxueshuo_server.search.identity import candidate_schema, mathematical_candidate
from tests.solver.test_graph_range_tasks import M3, M4, M5, TARGET, candidate, solve


def converted_candidate(request=None):
    c = candidate('q08')
    old = c['root']['goals'][0]
    c['root']['goals'][0] = {'kind': 'find_range', 'object': 'f', 'answer_request': request or request_for_goal(old)}
    return c


@pytest.mark.parametrize('goal,reason', [
    (candidate('q05')['root']['goals'][0], 'unsupported_goal'),
    (candidate('q08')['root']['goals'][0], 'unsupported_goal'),
    ({'kind': 'find_domain', 'object': 'f'}, 'unsupported_goal'),
    ({'kind': 'match_domain', 'object': 'f', 'symbol': 'a', 'domain': 'R'}, 'unsupported_goal'),
    ({'kind': 'find_minimum', 'expression': 'a'}, 'unsupported_goal'),
    ({'kind': 'find_range', 'symbol': 'a'}, 'function_target_required'),
])
def test_request_cannot_override_a_different_goal_even_without_schema_validation(goal, reason):
    goal = {**deepcopy(goal), 'answer_request': {'kind': 'identity'}}
    # Q5's verified set stores option indices, not a function's image.
    with pytest.raises(VerificationGap, match=reason):
        finalize_goal(goal, sp.FiniteSet(3))
    with pytest.raises(NotationError, match=reason):
        convert_goal(goal, sp.FiniteSet(3))
    with pytest.raises(NotationError, match=reason):
        request_for_goal(goal)
    root = {'definitions': ['f(x)=x^2'], 'facts': [], 'goals': [goal], 'uncertainties': [], 'children': []}
    report = Report()
    compiled = NotationValidator().scope(root, report, 'r')
    assert compiled['goals'] == []
    assert any(row.get('reason_code') == 'answer_request.' + reason for row in report.issues)
    assert not NotationValidator().validate_root(root).ok


def test_public_request_contract_stays_separate_from_internal_candidate_plans():
    folder = Path(__file__).parents[3] / 'internal/schemas'
    schemas = [json.loads((folder / 'graph-answer-request-v1.schema.json').read_text())]
    schemas += [json.loads((folder / (name+'.schema.json')).read_text())['$defs']['AnswerRequest']
                for name in ('graph-problem-extraction-v2', 'problem-math-notation-v1', 'graph-stage-two-input-feature-values-v1')]
    requests = [{'kind': 'identity'}, {'kind': 'extremum', 'quantity': 'supremum'},
                {'kind': 'expression', 'bindings': [{'symbol': 'a', 'quantity': 'maximum'}], 'expression': 'a+1'},
                {'kind': 'compare_set', 'expected': '[0,1]', 'relation': 'not_equal'}]
    for request in requests:
        validate_request(request)
        assert compile_plan(request)['input'] == 'set'
        for schema in schemas:
            Draft202012Validator(schema).validate(request)
    selection = request_for_goal(candidate('q05')['root']['goals'][0])
    assert compile_candidate_plan(selection)['input'] == 'candidates'
    for schema in schemas:
        assert not Draft202012Validator(schema).is_valid(selection)
    with pytest.raises(NotationError, match='candidate_inputs_required'):
        compile_plan(selection)
    with pytest.raises(NotationError, match='invalid_selection'):
        compile_candidate_plan({'kind': 'identity'})
    with pytest.raises(VerificationGap, match='candidate_inputs_required'):
        finalize_goal({'kind': 'find_range', 'object': 'f', 'answer_request': selection}, sp.FiniteSet(3))


@pytest.mark.parametrize('operation', ['compare_candidates', 'select_truth', 'unknown_operation'])
def test_unimplemented_display_operations_cannot_fall_back_to_a_range_card(operation):
    row = {'step': {'operation': operation}, 'output': encode_value({'type': 'selection', 'labels': ['D']})}
    with pytest.raises(ValueError, match='unsupported_operation:' + operation):
        display_groups({'steps': [row]}, sp.FiniteSet(3))
    with pytest.raises(ValueError, match='unsupported_operation:' + operation):
        phase_view({'range': {'steps': [row], 'image': sp.FiniteSet(3)}})


@pytest.mark.parametrize('method', [M4, M5])
def test_generic_request_uses_same_range_routes_and_original_choices(method):
    c = converted_candidate()
    Draft202012Validator(candidate_schema()).validate(c)
    state, answer, result = solve(c, method)
    assert answer['kind'] == 'derived_answer'
    assert decode_value(answer['value']['exact']) == 6
    assert result == sp.Interval(sp.Rational(5, 2), sp.Rational(7, 2))
    assert match_original_choice(c, TARGET, answer, encode_value(result))['correct_labels'] == ['B']
    trace = state['finalization'][-1]['outputs']['evidence']['conversion']
    assert [step['operation'] for step in trace['plan']['steps']] == ['extract_quantity', 'extract_quantity', 'evaluate_expression']
    chunks, pending = compile_route(state['interaction_seeds'], load_registry())
    assert not pending and all(not diagnostics for _, diagnostics in chunks)
    assert chunks[-1][0]['parts'][-1]['title'] == '计算原题所求值'
    for name in ('graph-stage-three-route-v1', 'graph-stage-three-route-v2', 'graph-stage-three-result-v1'):
        schema = json.loads((Path(__file__).parents[3] / 'internal/schemas' / (name+'.schema.json')).read_text())
        Draft202012Validator({'$defs': schema['$defs'], '$ref': '#/$defs/goalAnswer'}).validate(answer)


@pytest.mark.parametrize('answer_request,expected', [
    ({'kind': 'identity'}, sp.Interval(1, 5)),
    ({'kind': 'extremum', 'quantity': 'minimum'}, 1),
    ({'kind': 'extremum', 'quantity': 'maximum'}, 5),
    ({'kind': 'compare_set', 'expected': '[1,5]', 'relation': 'equal'}, True),
    ({'kind': 'compare_set', 'expected': '(1,5]', 'relation': 'equal'}, False),
    ({'kind': 'compare_set', 'expected': '(1,5]', 'relation': 'not_equal'}, True),
])
def test_question_changes_leave_solver_result_unchanged(answer_request, expected):
    c = converted_candidate(answer_request)
    c['root']['definitions'] = ['f(x)=x^2-2*x+2']
    c['root']['goals'][0]['input_domain'] = '[0,3]'
    if answer_request['kind'] == 'extremum':
        # Supported direct extrema now use T2; the public answer must still
        # agree with converting the full image through the shared contract.
        from shuxueshuo_server.graph_lesson.stage_three import driver, extremum_runtime
        from shuxueshuo_server.graph_lesson.stage_three.context import build_context
        from tests.solver.test_graph_stage_three_methods import finish
        context = build_context(c, TARGET)
        state = finish(driver.create_state(features=extract_features(c)['features'], context=context,
                       method='method-monotonicity-extremum', route_id='extremum', branch='direct',
                       target_ref=TARGET, run_id='conversion', lesson_version='v1'))
        assert state['status'] == 'method_complete', state['diagnostics']
        state['extremum_result_exact'] = state['result']['extremum_result']
        assert extremum_runtime.verify_frozen(c, TARGET, context, state['extremum_result_exact'])['status'] == 'verified'
        answer = extremum_runtime.finish(state, context, [])['answer']
        assert answer == finalize_goal(c['root']['goals'][0], sp.Interval(1, 5))
    else:
        state, answer, result = solve(c, M3)
        assert result == sp.Interval(1, 5)
    actual = answer['value'] if answer['status'] == 'boolean' else decode_value(answer.get('value', answer.get('set'))['exact'])
    assert actual == expected
    chunks, pending = compile_route(state['interaction_seeds'], load_registry())
    assert not pending and all(not diagnostics for _, diagnostics in chunks)


def test_bound_is_not_an_unattained_maximum_and_cannot_be_cancelled():
    interval = sp.Interval.Ropen(0, 2)
    maximum, _ = evaluate({'kind': 'extremum', 'quantity': 'maximum'}, result=interval)
    supremum, _ = evaluate({'kind': 'extremum', 'quantity': 'supremum'}, result=interval)
    assert not maximum['available'] and supremum['available'] and supremum['value'] == 2
    request = {'kind': 'expression', 'bindings': [{'symbol': 'a', 'quantity': 'maximum'}], 'expression': 'a-a'}
    value, _ = evaluate(request, result=interval)
    assert value == {'type': 'undefined', 'reason': 'quantity_unavailable'}


def test_shared_conversion_runs_after_a_substitution_route():
    from shuxueshuo_server.graph_lesson.stage_three.function_range import (
        SUBSTITUTION_METHOD,
    )

    c = converted_candidate({'kind': 'extremum', 'quantity': 'minimum'})
    c['root']['definitions'] = ['f(2*x-1)=x^2+2']
    _, answer, result = solve(c, SUBSTITUTION_METHOD)
    assert result == sp.Interval(2, sp.oo)
    assert decode_value(answer['value']['exact']) == 2


@pytest.mark.parametrize('change', [
    lambda r: r['bindings'][0].update(quantity='maximum_at_x'),
    lambda r: r.update(expression='a+unknown'),
    lambda r: r['bindings'][1].update(symbol='a'),
    lambda r: r.update(expression='a^100'),
])
def test_request_rejects_unbound_quantities_and_unsupported_operations(change):
    c = converted_candidate()
    change(c['root']['goals'][0]['answer_request'])
    assert not extract_features(c)['ok']


def test_candidate_engine_uses_complete_results_and_polarity_without_range_methods():
    cases = [{'label': 'left', 'value': sp.Interval.Ropen(0, 1)}, {'label': 'right', 'value': sp.Interval(0, 1)}]
    request = {'kind': 'select', 'predicate': {'kind': 'compare_set', 'expected': '[0,1]', 'relation': 'equal'},
               'when': False, 'selection_mode': 'single'}
    answer, trace = evaluate(request, candidates=cases)
    assert answer['labels'] == ['left']
    assert [row['operation'] for row in trace['plan']['steps']] == ['compare_candidates', 'select_truth']
    request['when'] = True
    assert evaluate(request, candidates=cases)[0]['labels'] == ['right']
    with pytest.raises(VerificationGap, match='candidate_identity'):
        evaluate(request, candidates=[cases[0], cases[0]])
    with pytest.raises(NotationError, match='candidate_inputs_required'):
        compile_plan(request)


def test_declared_plan_and_display_evidence_cannot_override_exact_result():
    goal = converted_candidate()['root']['goals'][0]
    answer = finalize_goal(goal, sp.Interval(2, 4))
    bad = deepcopy(answer)
    bad['value']['exact'] = encode_value(sp.Integer(7))
    with pytest.raises(GoalClosureMismatch):
        verify_goal_answer(goal, sp.Interval(2, 4), bad)
    wrong = deepcopy(goal['answer_request'])
    wrong['steps'] = [{'operation': 'return', 'value': 6}]
    with pytest.raises(NotationError, match='invalid_fields'):
        compile_plan(wrong)


def test_named_givens_cannot_be_misread_as_the_requested_extremum():
    c = converted_candidate({'kind': 'extremum', 'quantity': 'minimum'})
    assert build_d1(c, TARGET, extract_features(c)['features'], {'items': []})['diagnostics']
    c = converted_candidate({'kind': 'identity'})
    c['original_text'] = '已知函数 $f(x)=(3*x^2+x+3)/(x^2+1)$，判断值域是否为 $[5/2,7/2]$。'
    assert build_d1(c, TARGET, extract_features(c)['features'], {'items': []})['diagnostics']


@pytest.mark.parametrize('relation,label', [('equal', 'A'), ('not_equal', 'B')])
def test_boolean_answer_matches_original_yes_no_options(relation, label):
    c = converted_candidate({'kind': 'compare_set', 'expected': '[5/2,7/2]', 'relation': relation})
    c['public_content']['scopes'][0]['choices'][0]['options'] = [{'label': 'A', 'text': '是'}, {'label': 'B', 'text': '否'}]
    answer = finalize_goal(c['root']['goals'][0], sp.Interval(sp.Rational(5, 2), sp.Rational(7, 2)))
    choice = match_original_choice(c, TARGET, answer, encode_value(sp.Interval(sp.Rational(5, 2), sp.Rational(7, 2))))
    assert choice['status'] == 'matched', choice
    assert choice['correct_labels'] == [label]


@pytest.mark.parametrize('question,answer_request', [
    ('最大值为 $a$，最小值为 $b$，则 $a+b=$', None),
    ('求最大值与最小值的和。', None),
    ('求最大值。', {'kind': 'extremum', 'quantity': 'maximum'}),
    ('判断值域是否为 $[5/2,7/2]$。', {'kind': 'compare_set', 'expected': '[5/2,7/2]', 'relation': 'equal'}),
    ('判断值域是否不等于 $[5/2,7/2]$。', {'kind': 'compare_set', 'expected': '[5/2,7/2]', 'relation': 'not_equal'}),
])
def test_question_source_and_stage_two_keep_the_answer_request(question, answer_request, tmp_path):
    from tests.solver.test_graph_stage_three_execution import constructed_upstream

    c = converted_candidate(answer_request)
    c['original_text'] = '已知函数 $f(x)=(3*x^2+x+3)/(x^2+1)$，' + question
    d1 = build_d1(c, TARGET, extract_features(c)['features'], {'items': []})
    assert not d1['diagnostics'], d1
    path = constructed_upstream(tmp_path, mathematical_candidate(c))
    assert json.loads(path.read_text())['status'] == 'completed'
    c['original_text'] = c['original_text'].replace('最大值', '最小值').replace('[5/2,7/2]', '(5/2,7/2)')
    assert build_d1(c, TARGET, extract_features(c)['features'], {'items': []})['diagnostics']
