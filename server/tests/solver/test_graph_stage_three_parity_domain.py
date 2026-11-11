"""R1 shared execution, ephemeral teaching export and verified resumption."""
import json

import pytest

from shuxueshuo_server.graph_lesson.stage_three import runner
from shuxueshuo_server.graph_lesson.stage_three.contracts import ROOT
from shuxueshuo_server.graph_lesson.stage_three.preview import open_store
from shuxueshuo_server.search.lesson import present_lesson
from tests.solver.test_graph_function_parity_recognition import recognize
from tests.solver.test_graph_parity_parameter import candidate
from tests.solver.test_graph_parity_parameter_domain import abstract_candidate
from tools.export_graph_walk_course import export_course


@pytest.mark.parametrize('value', [
    json.loads((ROOT / 'internal/senior-high/authored-courses/function-parity-t2-r1-20261111/domain-endpoints.json').read_text())['candidate'],
    candidate('m*x^2+1', 'odd', facts=('Dom(f)={-1,1}',)),
    abstract_candidate('ℝ', 'odd', '∀x∈[0,∞):f(x)=x^2+m'),
    candidate('x^2', 'even', facts=('Dom(f)=[-m,m)',)),
    candidate('x^2', facts=('defined_on(f,[-1,m])',), goal_kind='find_range'),
])
def test_domain_route_and_pairing_view(value, tmp_path):
    prepared, recognized = recognize(value, tmp_path)
    shown = present_lesson(recognized, prepared['features'], value['original_text'], candidate=value)
    assert shown['goals'][0]['d1']['rows']
    assert 'D=' in shown['goals'][0]['d1']['summary']
    output = tmp_path / 'stage-three'
    result = runner.run_sample(tmp_path / 'stage-two/stage-two-result.json', output)
    goal, = result['goals']
    assert goal['status'] == 'solved', goal
    assert goal['primary'] == 'type-parity-parameter'
    snapshot = open_store(output).snapshot()
    assert len(snapshot['handoffs']) == 1
    failed = [r for r in snapshot['interaction_states'] if r['status'] != 'interactive']
    assert not failed, str(open_store(output).internal_snapshot()['interactions'][-1])
    serialized = (output / 'goals/goal-001/routes/parity-parameter.json').read_text()
    assert 'solve_domain_symmetry_conditions' in serialized
    assert 'complete_affine_domain_pairing' in serialized
    assert runner.resume_sample(output)['goals'][0]['answer'] == goal['answer']
    # Export in memory only. Do not rebuild authored/public course artifacts.
    evidence = export_course(output, 'function-parity-r1-test')
    assert evidence['stream']['handoffs'][0]['answer'] == goal['answer']


def test_changed_domain_proof_cannot_publish(tmp_path):
    recognize(abstract_candidate(), tmp_path)
    def corrupt(state, store):
        state['parity_parameter_result_exact']['comparison']['domain_evidence']['cells'].pop()
    output = tmp_path / 'stage-three'
    result = runner.run_sample(tmp_path / 'stage-two/stage-two-result.json', output,
                               hooks={'before_verification': corrupt})
    goal, = result['goals']
    assert goal['answer'] is None
    assert goal['routes'][0]['status'] == 'math_failed'
    assert not open_store(output).snapshot()['handoffs']
