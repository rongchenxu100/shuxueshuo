"""FP-T3 R0 recognition -> execution -> verified teaching export and resume."""
import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import runner
from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value
from shuxueshuo_server.graph_lesson.stage_three.preview import open_store
from shuxueshuo_server.search.lesson import present_lesson
from tests.solver.test_graph_function_parity_recognition import recognize
from tests.solver.test_graph_parity_extension import candidate
from tools.export_graph_walk_course import export_course

EXPECTED = {'a07': 'x**2 - x', 'a08': '-x**2 - 3*x + 1'}


@pytest.mark.parametrize('name', ['a07', 'a08'])
def test_extension_route_maps_substitutes_and_exports(name, tmp_path):
    value = candidate(name)
    prepared, recognized = recognize(value, tmp_path)
    shown = present_lesson(recognized, prepared['features'], value['original_text'], candidate=value)
    reading = shown['goals'][0]['d1']
    assert reading['rows'] and not reading.get('diagnostics')
    assert '$x<0$ 时 $f(x)$ 的解析式' in reading['summary']
    assert '/root/facts/1' in reading['rows'][0]['source_refs']
    output = tmp_path / 'stage-three'
    result = runner.run_sample(tmp_path / 'stage-two/stage-two-result.json', output)
    assert result['status'] == 'completed', result
    goal, = result['goals']
    assert goal['status'] == 'solved', goal
    assert goal['primary'] == 'type-parity-formula'
    assert goal['d3']['submit_label'] == '用对称补全法解题'
    answer = goal['answer']
    assert answer['kind'] == 'find_function_formula' and answer['status'] == 'determined_on_domain'
    assert answer['expression']['expression'] == EXPECTED[name]
    assert answer['requested_domain']['latex'] == r'\left(-\infty, 0\right)'
    assert answer['determined_domain'] == answer['requested_domain']
    snapshot = open_store(output).snapshot()
    assert len(snapshot['handoffs']) == 1
    assert all(row['status'] == 'interactive' for row in snapshot['interaction_states'])
    resumed = runner.resume_sample(output)
    assert resumed['goals'][0]['answer'] == answer
    assert open_store(output).snapshot()['handoffs'] == snapshot['handoffs']
    evidence = export_course(output, f'function-parity-{name}')
    assert evidence['lesson']['goals'][0]['primary'] == 'type-parity-formula'
    assert evidence['stream']['handoffs'][0]['answer'] == answer


def test_a09_second_part_checks_zero_and_answers_closed_range(tmp_path):
    value = candidate('a09')
    prepared, recognized = recognize(value, tmp_path)
    shown = present_lesson(recognized, prepared['features'], value['original_text'], candidate=value)
    reading = shown['goals'][1]['d1']
    assert '$x\\le 0$ 时 $f(x)$ 的解析式' in reading['summary']
    output = tmp_path / 'stage-three'
    result = runner.run_sample(tmp_path / 'stage-two/stage-two-result.json', output)
    goal = next(g for g in result['goals'] if g['target_ref'] == '/root/goals/1')
    assert goal['status'] == 'solved', goal
    answer = goal['answer']
    assert answer['expression']['expression'] == '-2*x**2 - x'
    assert answer['requested_domain']['latex'] == r'\left(-\infty, 0\right]'
    first = next(g for g in result['goals'] if g['target_ref'] == '/root/goals/0')
    assert first['answer']['value']['expression'] == '-15'


def test_a04_abstract_domain_answer_keeps_domain_identity(tmp_path):
    value = candidate('a04')
    prepared, recognized = recognize(value, tmp_path)
    shown = present_lesson(recognized, prepared['features'], value['original_text'], candidate=value)
    reading = shown['goals'][0]['d1']
    assert '在整个定义域上的解析式' in reading['summary'] and '定义在' not in reading['summary']
    output = tmp_path / 'stage-three'
    result = runner.run_sample(tmp_path / 'stage-two/stage-two-result.json', output)
    goal, = result['goals']
    assert goal['status'] == 'solved', goal
    answer = goal['answer']
    assert answer['expression']['expression'] == 'x**2 + 4*Abs(x)'
    assert answer['domain_identity'] == 'declared_symmetric_domain'
    assert answer['declared_domain'] is None and answer['determined_domain'] is None
    assert runner.resume_sample(output)['goals'][0]['answer'] == answer


def _whole(value):
    del value['root']['goals'][0]['requested_domain']
    return value


R1_CASES = {
    'free_zero': (lambda: candidate(
        'a08', prop='even', requested='(-∞,0]',
        text=r'函数 $f(x)$ 是定义在 $\mathbf R$ 上的偶函数，当 $x>0$ 时，$f(x)=x^2-3x-1$，'
             r'则当 $x\le 0$ 时，$f(x)=$____．'),
        'insufficient_information', 'x**2 + 3*x - 1', '{0}'),
    'point_rule': (lambda: _whole(candidate(
        'a08', prop='even', extra_facts=['f(0)=1'],
        text=r'函数 $f(x)$ 是定义在 $\mathbf R$ 上的偶函数，当 $x>0$ 时，$f(x)=x^2-3x-1$，且 $f(0)=1$，'
             r'则 $f(x)$ 的解析式是____．')),
        'determined_on_domain', None, None),
    'radical': (lambda: candidate(
        'a08', rule='sqrt(x)+1',
        text=r'函数 $f(x)$ 是定义在 $\mathbf R$ 上的奇函数，当 $x>0$ 时，$f(x)=\sqrt{x}+1$，'
             r'则当 $x<0$ 时，$f(x)=$____．'),
        'determined_on_domain', '-sqrt(-x) - 1', None),
}


@pytest.mark.parametrize('name', list(R1_CASES))
def test_r1_extensions_run_end_to_end(name, tmp_path):
    build, status, expression, free = R1_CASES[name]
    value = build()
    prepared, recognized = recognize(value, tmp_path)
    shown = present_lesson(recognized, prepared['features'], value['original_text'], candidate=value)
    reading = shown['goals'][0]['d1']
    assert reading['rows'] and not reading.get('diagnostics'), reading
    output = tmp_path / 'stage-three'
    result = runner.run_sample(tmp_path / 'stage-two/stage-two-result.json', output)
    goal, = result['goals']
    assert goal['status'] == 'solved', goal
    answer = goal['answer']
    assert answer['status'] == status
    if expression:
        assert sp.simplify(sp.sympify(answer['expression']['expression'], locals={'x': X})
                           - sp.sympify(expression, locals={'x': X})) == 0
    assert (answer.get('free_domain') or {}).get('expression') == free
    assert runner.resume_sample(output)['goals'][0]['answer'] == answer
    evidence = export_course(output, f'function-parity-r1-{name}')
    assert evidence['stream']['handoffs'][0]['answer'] == answer


def test_formula_answer_needs_a_route_result(tmp_path):
    from shuxueshuo_server.graph_lesson.stage_three.handoff import complete_route
    answer = {'kind': 'find_function_formula', 'status': 'determined_on_domain'}
    with pytest.raises(ValueError, match='incomplete_finalization'):
        complete_route(None, {'status': 'verified'}, route={'status': 'verified', 'result': {'answer': answer}},
                       verification={'status': 'verified'}, feasible_set=None, answer=answer, commit_id='tampered')


X = sp.Symbol('x', real=True)


@pytest.mark.parametrize('field,value', [('expression', encode_value(X**2 + X)), ('sign', -1),
                                         ('mapped_domain', encode_value(sp.Interval(0, sp.oo)))])
def test_corrupt_extension_result_never_publishes(field, value, tmp_path):
    recognize(candidate('a07'), tmp_path)

    def corrupt(state, store):
        state['parity_extension_result_exact'][field] = value
    output = tmp_path / 'stage-three'
    result = runner.run_sample(tmp_path / 'stage-two/stage-two-result.json', output,
                               hooks={'before_verification': corrupt})
    goal, = result['goals']
    assert goal['answer'] is None
    assert goal['routes'][0]['status'] == 'math_failed'
    assert not open_store(output).snapshot()['handoffs']
    with pytest.raises(ValueError, match='course_export'):
        export_course(output, 'function-parity-a07')
