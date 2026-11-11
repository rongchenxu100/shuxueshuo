"""R2 real recognition/execution, in-memory export, interactions and restoration."""
import json

import pytest

from shuxueshuo_server.graph_lesson.stage_three import runner
from shuxueshuo_server.graph_lesson.stage_three.preview import open_store
from shuxueshuo_server.search.lesson import present_lesson
from tests.solver.test_graph_function_parity_recognition import recognize
from tests.solver.test_graph_parity_parameter import candidate
from tools.export_graph_walk_course import export_course


@pytest.mark.parametrize('expr,prop,facts', [
    ('(x^2-1)^2+m*x', 'even', ()),
    ('(x^2-m^2)/(x^2-m^2)', 'even', ()),
    ('abs(x+1)+m*abs(x-1)', 'even', ()),
    ('piecewise(-1,x<0,m,x=0,1,x>0)', 'odd', ()),
    ('sqrt(x^2+m)', 'even', ()),
    ('sqrt(m*x^2)', 'odd', ()),
    ('sqrt(m*x^2+1)', 'odd', ()),
    ('sqrt(m*x^2)', 'odd', ('Dom(f)=ℝ',)),
])
def test_original_route_export_and_restore(expr, prop, facts, tmp_path):
    value = candidate(expr, prop, facts=facts, goal_kind='find_range')
    prepared, recognized = recognize(value, tmp_path)
    shown = present_lesson(recognized, prepared['features'], value['original_text'], candidate=value)
    assert shown['goals'][0]['d1']['rows']
    output = tmp_path / 'stage-three'
    result = runner.run_sample(tmp_path / 'stage-two/stage-two-result.json', output)
    goal, = result['goals']
    assert goal['status'] == 'solved', goal
    assert goal['primary'] == 'type-parity-parameter'
    store = open_store(output)
    snapshot = store.snapshot()
    assert len(snapshot['handoffs']) == 1
    # Constant conditions belong in student prose, not Python/SymPy booleans.
    for step in snapshot['math_steps']:
        displayed = [step['explanation'], *[item['math'] for item in step['highlight']['items']]]
        assert all(r'\text{True}' not in text and r'\text{False}' not in text for text in displayed)
    assert all(r['status'] == 'interactive' for r in snapshot['interaction_states']), [r['diagnostics'] for r in store.internal_snapshot()['interactions']]
    assert runner.resume_sample(output)['goals'][0]['answer'] == goal['answer']
    evidence = export_course(output, 'function-parity-r2-test')  # no public files written
    assert evidence['stream']['handoffs'][0]['answer'] == goal['answer']
    serialized = json.dumps(evidence, ensure_ascii=False)
    assert 'sampled_curve' in serialized
    assert 'condition_number_lines' in serialized


def test_missing_original_holes_cannot_publish(tmp_path):
    recognize(candidate('(x-m)/(x-m)'), tmp_path)
    def corrupt(state, store):
        state['parity_parameter_result_exact']['comparison']['source']['parts'][0]['guards'] = []
    output = tmp_path / 'stage-three'
    result = runner.run_sample(tmp_path / 'stage-two/stage-two-result.json', output,
                               hooks={'before_verification': corrupt})
    assert result['goals'][0]['answer'] is None
    assert result['goals'][0]['routes'][0]['status'] == 'math_failed'
    assert not open_store(output).snapshot()['handoffs']
