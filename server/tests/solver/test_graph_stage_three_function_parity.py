"""Parity results must survive independent verification, storage and export."""

from copy import deepcopy

import pytest

from shuxueshuo_server.graph_lesson.stage_three import runner
from shuxueshuo_server.graph_lesson.stage_three.preview import open_store
from tests.solver.test_graph_function_parity_recognition import candidate, recognize
from tools.export_graph_walk_course import export_course


@pytest.mark.parametrize('expression,changes,classification', [
    ('x/(x^2+1)', {}, 'odd_only'),
    ('abs(x+1)+abs(x-1)', {}, 'even_only'),
    ('x', {'input_domain': '{0}'}, 'both'),
    ('x^2', {'input_domain': '[-2,1]'}, 'neither'),
])
def test_verified_parity_can_be_published_resumed_and_exported(expression, changes, classification, tmp_path):
    recognize(candidate(expression, **changes), tmp_path)
    output = tmp_path / 'stage-three'
    result = runner.run_sample(tmp_path / 'stage-two/stage-two-result.json', output)
    assert result['status'] == 'completed', result
    goal, = result['goals']
    assert goal['status'] == 'solved', goal
    assert goal['primary'] == 'type-function-parity'
    assert goal['answer']['kind'] == 'determine_function_parity'
    assert goal['answer']['classification'] == classification
    assert goal['feasible_set'] is None
    snapshot = open_store(output).snapshot()
    handoff, = snapshot['handoffs']
    assert handoff['answer'] == goal['answer'] and handoff['feasible_set'] is None
    assert 'original_choice' not in handoff
    assert all(route['status'] == 'verified' for route in goal['routes'])
    saved = deepcopy(snapshot['handoffs'])
    resumed = runner.resume_sample(output)
    assert resumed['goals'][0]['answer'] == goal['answer']
    assert open_store(output).snapshot()['handoffs'] == saved
    evidence = export_course(output, 'function-parity-a01-1')
    assert evidence['lesson']['goals'][0]['primary'] == 'type-function-parity'
    assert evidence['stream']['handoffs'][0]['answer']['classification'] == classification


def test_incorrect_parity_cannot_pass_final_verification_or_publish(tmp_path):
    recognize(candidate('x^2'), tmp_path)

    def corrupt_classification(state, store):
        state['parity_result_exact']['classification'] = 'odd_only'

    output = tmp_path / 'stage-three'
    result = runner.run_sample(tmp_path / 'stage-two/stage-two-result.json', output,
                               hooks={'before_verification': corrupt_classification})
    goal, = result['goals']
    assert goal['answer'] is None
    assert goal['routes'][0]['status'] == 'math_failed'
    assert not open_store(output).snapshot()['handoffs']
    with pytest.raises(ValueError, match='course_export'):
        export_course(output, 'function-parity-a01-1')


def test_no_applicable_method_does_not_execute_a_missing_choice_card(tmp_path, monkeypatch):
    recognize(candidate('x^2'), tmp_path)
    original = runner.TargetPreparation.prepare

    def refuse_method(self, operation, **payload):
        result = original(self, operation, **payload)
        if operation == 'evaluate_goal':
            result.update(status='no_applicable_method', d3=None, d4=None)
            result['selection'].update(branches=[], recommendation_rule=None)
        return result

    monkeypatch.setattr(runner.TargetPreparation, 'prepare', refuse_method)
    output = tmp_path / 'stage-three'
    result = runner.run_sample(tmp_path / 'stage-two/stage-two-result.json', output)
    goal, = result['goals']
    assert goal['status'] == 'no_applicable_method'
    assert not goal['routes'] and goal['d4'] is None
    assert not goal['diagnostics'] and not open_store(output).snapshot()['handoffs']
    broken = deepcopy(result)
    broken['goals'][0]['status'] = 'solved'
    # A structurally valid answer still cannot make an empty method selection solved.
    broken['goals'][0]['answer'] = {
        'kind': 'determine_function_parity', 'status': 'complete',
        'classification': 'even_only', 'odd': 'refuted', 'even': 'proved',
        'latex': r'\text{偶函数}',
    }
    with pytest.raises(ValueError, match='empty_selection_without_admission_failure'):
        runner.validate_result(broken)
