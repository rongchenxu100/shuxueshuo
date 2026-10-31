"""Finite inputs remain discrete and consume verified M9 child results."""

from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.function_evaluation import evaluate
from shuxueshuo_server.graph_lesson.stage_three.capabilities import LocalCheckFailed
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.finite_range import (
    collect_finite_range,
    input_rows,
)
from shuxueshuo_server.graph_lesson.stage_three.function_range import (
    ENUMERATION_METHOD,
    admitted,
    image_endpoints,
    independent_verify,
)
from shuxueshuo_server.graph_lesson.stage_three.range_presentation import compile_range
from shuxueshuo_server.graph_lesson.stage_three.selection import evaluate_goal
from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value
from tests.solver.test_graph_function_range import TARGET, candidate


def evaluated_rows(context):
    return [{'case_id': row['id'], 'condition': row['condition'], 'domain': row['domain'],
             'outputs': {'evaluation_result': evaluate(row['evaluation_goal'])}}
            for row in input_rows(context)]


@pytest.mark.parametrize('expression,domain,expected', [
    ('2*x-1', '{-1,0,1,2}', sp.FiniteSet(-3, -1, 1, 3)),
    ('x^2', '{-2,-1,0,1,2}', sp.FiniteSet(0, 1, 4)),
    ('3', '{0,1,1,2}', sp.FiniteSet(3)),
    ('x+2', '{3/2}', sp.FiniteSet(sp.Rational(7, 2))),
    ('1/(x-1)', '{0,1,2}', sp.FiniteSet(-1, 1)),
    ('(x^2-1)/(x-1)', '{-1,0,1,2}', sp.FiniteSet(0, 1, 3)),
    ('(2*x+3)/(x+1)', '{-3,-2,0,2}', sp.FiniteSet(sp.Rational(3, 2), 1, 3, sp.Rational(7, 3))),
])
def test_complete_finite_image(expression, domain, expected):
    value = candidate(expression, domain)
    context = build_context(value, TARGET)
    assert admitted(context, ENUMERATION_METHOD)
    selection = evaluate_goal(value, TARGET, [], 'type-function-range')
    assert [b['target'] for b in selection['selection']['branches']] == [ENUMERATION_METHOD]
    computed = collect_finite_range(context, evaluated_rows(context))['outputs']
    assert computed['feasible_set'] == expected
    assert independent_verify(value, TARGET, context, expected)['status'] == 'verified'
    assert image_endpoints(value, TARGET, expected)['status'] == 'passed'
    assert independent_verify(value, TARGET, context, expected-sp.FiniteSet(min(expected)))['status'] == 'math_failed'
    if len(expected) > 1:
        assert independent_verify(value, TARGET, context, sp.Interval(min(expected), max(expected)))['status'] == 'math_failed'
    for phase in ('finite_evaluate', 'finite_collect'):
        part = compile_range([{'values': encode_value({**computed, 'phase': phase})}], 'finite')['parts'][0]
        assert part['stem_board']['items'][1]['math'] is None
        assert part['interaction']['type'] == 'choice'
        assert 'f(x)=' in part['question'] or 'f(x)=' in part['stem_board']['items'][0]['math']
        if phase == 'finite_collect':
            assert part['completion_graph']['params']['pieces'] == []
            assert len(part['completion_graph']['params']['points']) == len(expected)


def test_input_partition_and_values_cannot_be_dropped_reordered_or_forged():
    context = build_context(candidate('x^2', '{-1,0,1}'), TARGET)
    original = evaluated_rows(context)
    tampered = deepcopy(original)
    tampered[0]['outputs']['evaluation_result']['value'] = sp.Integer(99)
    wrong_domain = deepcopy(original)
    wrong_domain[0]['domain'] = sp.FiniteSet(99)
    for rows in (original[:-1], original[::-1], original+[original[0]], tampered, wrong_domain):
        with pytest.raises(LocalCheckFailed):
            collect_finite_range(context, rows)
    duplicate = build_context(candidate('x^2', '{-1,0,1,1,0}'), TARGET)
    assert [r['id'] for r in input_rows(context)] == [r['id'] for r in input_rows(duplicate)]


@pytest.mark.parametrize('expression,domain', [
    ('x', '{0,1,2,3,4,5,6,7,8}'), ('x', '∅'), ('1/x', '{0}'),
    ('sqrt(x)', '{0,1,2}'), ('x', '{sqrt(2),2}'),
])
def test_unsupported_inputs_fail_closed(expression, domain):
    assert not admitted(build_context(candidate(expression, domain), TARGET), ENUMERATION_METHOD)


def test_declared_domain_conflict_is_not_silently_filtered():
    value = candidate('1/x', '{1,2}')
    value['root']['facts'] = ['Dom(f)={0,1,2}']
    assert not admitted(build_context(value, TARGET))


@pytest.mark.stage_three_db
@pytest.mark.parametrize('domain,source', [
    ('{-1,0,1,2}', 'input_domain'),
])
def test_complete_lesson_uses_real_folded_m9_calls(tmp_path, domain, source):
    from shuxueshuo_server.graph_lesson.stage_three import runner
    from tests.solver.test_graph_stage_three_execution import (
        constructed_upstream,
        store,
    )
    from tools.export_graph_walk_course import export_course

    value = candidate('2*x-1', domain)
    if source == 'declared_domain':
        value['root']['goals'][0].pop('input_domain')
        value['root']['facts'] = [f'Dom(f)={domain}']
        value['original_text'] = f'已知函数 $f(x)=2x-1$ 的定义域为 ${domain}$，求值域。'
    upstream = constructed_upstream(tmp_path, value)
    output = tmp_path/'run'
    completed = runner.run_sample(upstream, output)
    goal = completed['goals'][0]
    assert goal['status'] == 'solved', goal
    snapshot = store(output).snapshot()
    assert all(row['status'] == 'interactive' for row in snapshot['interaction_states'])
    course = export_course(output, 'finite-range-regression')
    assert course['lesson']['goals'][0]['walk'] is not None
    # Two parent teaching cards, not a new M9 tutorial for every input.
    fragments = snapshot['math_steps']
    assert len(fragments) == 2
    trajectory = store(output).checkpoint(TARGET, 'finite-range')['driver_state']['trajectory']
    calls = [c for step in trajectory['steps'] for c in step['calls']]
    assert sum(c['capability'] == 'submethod' and c['public_ref'] == 'method-function-evaluation'
               for c in calls) == len(input_rows(build_context(value, TARGET)))


def test_eight_input_driver_checkpoint_roundtrip():
    import json

    from shuxueshuo_server.graph_lesson.stage_three import driver, execution_contracts
    from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value

    context = build_context(candidate('x^2', '{0,1,2,3,4,5,6,7}'), TARGET)
    contracts = execution_contracts.load_contracts()
    state = driver.create_state(features=[], context=context, method=ENUMERATION_METHOD,
                                route_id='finite-range', branch='direct', target_ref=TARGET,
                                run_id='finite-input-test', lesson_version='finite-input-test',
                                contracts=contracts, solve_budget_seconds=30)
    while state['status'] == 'running':
        state = driver.advance(json.loads(json.dumps(state)), contracts=contracts)
    assert state['status'] == 'method_complete', state['diagnostics']
    assert decode_value(state['result'])['candidate_set'] == sp.FiniteSet(0, 1, 4, 9, 16, 25, 36, 49)
    calls = [c for step in state['trajectory']['steps'] for c in step['calls']]
    assert sum(c['capability'] == 'submethod' for c in calls) == 8
    assert len(state['fragments']) == 2
