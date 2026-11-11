"""Shared recognition -> execution -> verified teaching export and resume."""
import pytest

from shuxueshuo_server.graph_lesson.stage_three import runner
from shuxueshuo_server.graph_lesson.stage_three.preview import open_store
from shuxueshuo_server.search.lesson import present_lesson
from tests.solver.test_graph_function_parity_recognition import recognize
from tests.solver.test_graph_parity_parameter import candidate
from tools.export_graph_walk_course import export_course


@pytest.mark.parametrize('value', [candidate(), candidate('m*x^2', goal_kind='find_range'),
                                  candidate('(m^2-1)*x^2+m*x', 'odd', goal_kind='find_range'),
                                  candidate('m*x', 'odd_only', goal_kind='find_range'),
                                  candidate('m*x^2'), candidate('x^2+m*x', 'odd'),
                                  candidate('m*x^2', 'both')])
def test_parameter_route_uses_public_skill_and_exports(value, tmp_path):
    prepared, recognized = recognize(value, tmp_path)
    shown = present_lesson(recognized, prepared['features'], value['original_text'], candidate=value)
    reading = shown['goals'][0]['d1']
    assert reading['rows'] and not reading.get('diagnostics')
    assert '参数 $m$ 的全部取值' in reading['summary']
    assert '/root/facts/0' in reading['rows'][0]['source_refs']
    output = tmp_path / 'stage-three'
    result = runner.run_sample(tmp_path / 'stage-two/stage-two-result.json', output)
    assert result['status'] == 'completed', result
    goal, = result['goals']
    assert goal['status'] == 'solved', goal
    assert goal['primary'] == 'type-parity-parameter'
    assert goal['answer']['kind'] == value['root']['goals'][0]['kind']
    assert goal['d3']['title'] == '选择解题方法'
    snapshot = open_store(output).snapshot()
    assert len(snapshot['handoffs']) == 1
    assert all(row['status'] == 'interactive' for row in snapshot['interaction_states'])
    resumed = runner.resume_sample(output)
    assert resumed['goals'][0]['answer'] == goal['answer']
    assert open_store(output).snapshot()['handoffs'] == snapshot['handoffs']
    evidence = export_course(output, 'function-parity-a17')
    assert evidence['lesson']['goals'][0]['primary'] == 'type-parity-parameter'
    assert evidence['stream']['handoffs'][0]['answer'] == goal['answer']
    if goal['answer']['kind'] == 'find_value':
        from shuxueshuo_server.graph_lesson.stage_three.handoff import complete_route
        # A verified parameter result cannot be relabelled as another task or
        # paired with a different answer at the publication boundary.
        for answer in [{**goal['answer'], 'parameter': 'q'},
                       {'kind': 'check_constant', 'status': 'complete'}]:
            with pytest.raises(ValueError, match='incomplete_finalization'):
                complete_route(None, {'status': 'verified'}, route={
                    'status': 'verified', 'result': {'parity_parameter_result': {}, 'answer': goal['answer']}},
                    verification={'status': 'verified'}, feasible_set=None, answer=answer, commit_id='tampered')


def test_corrupt_parameter_result_never_publishes(tmp_path):
    recognize(candidate(), tmp_path)
    def corrupt(state, store):
        state['parity_parameter_result_exact']['feasible_set'] = {'$math': 'Reals'}
    output = tmp_path / 'stage-three'
    result = runner.run_sample(tmp_path / 'stage-two/stage-two-result.json', output,
                               hooks={'before_verification': corrupt})
    goal, = result['goals']
    assert goal['answer'] is None
    assert goal['routes'][0]['status'] == 'math_failed'
    assert not open_store(output).snapshot()['handoffs']
    with pytest.raises(ValueError, match='course_export'):
        export_course(output, 'function-parity-a17')
