"""FP-T3 R2–R3 recognition -> symmetric evaluation -> verified teaching export and resume."""
import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import runner
from shuxueshuo_server.graph_lesson.stage_three.preview import open_store
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value, encode_value
from shuxueshuo_server.search.lesson import present_lesson
from tests.solver.test_graph_function_parity_recognition import recognize
from tests.solver.test_graph_symmetry_value import candidate
from tools.export_graph_walk_course import export_course

CASES = {
    'a12': (lambda: candidate('a12'), 'complete', '-4'),
    'a13': (lambda: candidate('a13'), 'complete', '-3'),
    'a03': (lambda: candidate('a03'), 'complete', '-2'),
    'a06': (lambda: candidate('a06'), 'complete', '5'),
    'a15': (lambda: candidate('a15'), 'complete', '-8'),
    'only_f1': (lambda: candidate('a13', goal={'kind': 'find_value', 'expression': 'f(1)'}, text=(
        r'已知 $f(x)$ 是定义在 $\mathbf R$ 上的奇函数，且 $f(-1)+f(2)=3$，则 $f(1)=$____．')),
        'insufficient_information', None),
}


@pytest.mark.parametrize('name', list(CASES))
def test_symmetry_route_runs_end_to_end(name, tmp_path):
    build, status, value = CASES[name]
    problem = build()
    prepared, recognized = recognize(problem, tmp_path)
    shown = present_lesson(recognized, prepared['features'], problem['original_text'], candidate=problem)
    reading = shown['goals'][0]['d1']
    assert reading['rows'] and not reading.get('diagnostics'), reading
    assert '奇函数' in reading['summary']
    output = tmp_path / 'stage-three'
    result = runner.run_sample(tmp_path / 'stage-two/stage-two-result.json', output)
    assert result['status'] == 'completed', result
    goal, = result['goals']
    assert goal['status'] == 'solved', goal
    assert goal['primary'] == 'type-function-evaluation'
    assert goal['d3']['submit_label'] == '用对称关系法解题'
    answer = goal['answer']
    assert answer['kind'] == 'find_value' and answer['status'] == status
    assert (answer['value'] or {}).get('expression') == value
    snapshot = open_store(output).snapshot()
    assert all(row['status'] == 'interactive' for row in snapshot['interaction_states'])
    assert runner.resume_sample(output)['goals'][0]['answer'] == answer
    evidence = export_course(output, f'function-symmetry-{name}')
    assert evidence['stream']['handoffs'][0]['answer'] == answer


def test_a09_first_part_is_answered_by_symmetry(tmp_path):
    recognize(candidate('a09'), tmp_path)
    result = runner.run_sample(tmp_path / 'stage-two/stage-two-result.json', tmp_path / 'stage-three')
    first = next(g for g in result['goals'] if g['target_ref'] == '/root/goals/0')
    assert first['status'] == 'solved', first
    assert first['answer']['value']['expression'] == '-15'
    second = next(g for g in result['goals'] if g['target_ref'] == '/root/goals/1')
    assert second['answer']['expression']['expression'] == '-2*x**2 - x'


def _drop_instance(model):
    return {**model, 'equations': model['equations'][:1]}


def _flip_sign(model):
    return {**model, 'signs': {**model['signs'], 'g': -model['signs']['g']}}


def _borrowed(field, wrong):
    def change(model):
        return {**model, 'borrow': {**model['borrow'], 'output': {**model['borrow']['output'], field: wrong}}}
    return change


@pytest.mark.parametrize('name,change', [
    ('a15', _borrowed('parameter_set', sp.FiniteSet(4))),
    ('a15', _borrowed('remaining_source_refs', ['/root/facts/1'])),
    ('a15', lambda m: {**m, 'borrow': None}),
    ('a13', lambda m: {**m, 'value': sp.Integer(4)}),
    ('a13', lambda m: {**m, 'multipliers': [sp.Integer(1)]}),
    ('a03', lambda m: {**m, 'value': sp.Integer(2)}),
    ('a03', _drop_instance),
    ('a03', _flip_sign),
])
def test_corrupt_symmetry_result_never_publishes(name, change, tmp_path):
    recognize(candidate(name), tmp_path)

    def corrupt(state, store):
        state['symmetry_result_exact'] = encode_value(change(decode_value(state['symmetry_result_exact'])))
    output = tmp_path / 'stage-three'
    result = runner.run_sample(tmp_path / 'stage-two/stage-two-result.json', output,
                               hooks={'before_verification': corrupt})
    goal, = result['goals']
    assert goal['answer'] is None
    assert goal['routes'][0]['status'] == 'math_failed'
    assert not open_store(output).snapshot()['handoffs']
