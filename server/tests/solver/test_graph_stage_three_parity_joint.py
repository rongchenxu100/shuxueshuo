"""R3 joint answers stay correlated through recognition, grading and resume."""
import json
import subprocess

import pytest

from shuxueshuo_server.graph_lesson.stage_three import runner
from shuxueshuo_server.graph_lesson.stage_three.contracts import ROOT
from shuxueshuo_server.graph_lesson.stage_three.preview import open_store
from shuxueshuo_server.search.lesson import present_lesson
from tests.solver.test_graph_function_parity_recognition import recognize
from tests.solver.test_graph_parity_parameter_joint import pair_candidate
from tools.export_graph_walk_course import export_course


@pytest.mark.parametrize('expr,prop,facts,kind,names', [
    ('a*x^2+b*x', 'odd', (), 'find_value', ('a', 'b')),
    ('a*x^2+b', 'odd', ('Dom(f)={-1,1}',), 'find_range', ('a', 'b')),
    ('a*x^2+b*x', 'odd_only', (), 'find_range', ('a', 'b')),
    ('a*x^2+b', 'even', ('a=1 ∨ b=2',), 'find_value', ('a', 'b')),
    ('a*x^2+b*x+1', 'odd', (), 'find_value', ('a', 'b')),
    ('α*x^2+β*x', 'odd', (), 'find_range', ('α', 'β')),
    ('a*x^2+b*x', 'even', ('Dom(f)=(-∞,-1]∪[1,∞)',), 'find_range', ('a', 'b')),
])
def test_joint_answer_export_grading_and_restore(expr, prop, facts, kind, names, tmp_path):
    value = pair_candidate(expr, prop, facts=facts, goal_kind=kind, names=names)
    prepared, recognized = recognize(value, tmp_path)
    shown = present_lesson(recognized, prepared['features'], value['original_text'], candidate=value)
    assert shown['goals'][0]['d1']['rows']
    assert '('+','.join(names)+')' in shown['goals'][0]['d1']['summary']
    output = tmp_path/'stage-three'
    result = runner.run_sample(tmp_path/'stage-two/stage-two-result.json', output)
    goal, = result['goals']
    assert goal['status'] == 'solved', goal
    assert goal['primary'] == 'type-parity-parameter'
    store = open_store(output)
    snapshot = store.snapshot()
    assert len(snapshot['handoffs']) == 1
    assert all(r['status'] == 'interactive' for r in snapshot['interaction_states']), [r['diagnostics'] for r in store.internal_snapshot()['interactions']]
    assert runner.resume_sample(output)['goals'][0]['answer'] == goal['answer']
    evidence = export_course(output, 'function-parity-r3-test')
    answer = evidence['stream']['handoffs'][0]['answer']
    assert answer['result_type'] == 'parameter_family'
    assert answer['parameters'] == list(names)
    assert 'parameter_set' not in answer
    path = tmp_path/'evidence.json'
    path.write_text(json.dumps(evidence, ensure_ascii=False))
    check = subprocess.run(['node', str(ROOT/'tools/tests/fixtures/parity-parameter-course-check.mjs'), str(path)],
                           capture_output=True, text=True, check=False)
    assert check.returncode == 0, check.stdout+check.stderr


def test_joint_tamper_cannot_handoff(tmp_path):
    recognize(pair_candidate(), tmp_path)
    def corrupt(state, store):
        state['parity_parameter_result_exact']['solution'][0]['free_parameters'] = []
    result = runner.run_sample(tmp_path/'stage-two/stage-two-result.json', tmp_path/'execution',
                               hooks={'before_verification': corrupt})
    assert result['goals'][0]['answer'] is None
    assert result['goals'][0]['routes'][0]['status'] == 'math_failed'
