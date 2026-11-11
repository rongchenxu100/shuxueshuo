"""FP-T4 R0–R1 recognition -> execution -> verified teaching export and resume."""
import json

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import runner
from shuxueshuo_server.graph_lesson.stage_three.preview import open_store
from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value
from shuxueshuo_server.search.lesson import present_lesson
from tests.solver.test_graph_function_parity_recognition import recognize
from tests.solver.test_graph_parity_inequality import candidate
from tests.solver.test_graph_parity_order import a05, given
from tools.export_graph_walk_course import export_course


def _parts(evidence):
    return [part for row in evidence['stream']['interactions'] for part in row['parts']]


def test_a02_solves_mirrors_and_exports(tmp_path):
    value = candidate()
    prepared, recognized = recognize(value, tmp_path)
    shown = present_lesson(recognized, prepared['features'], value['original_text'], candidate=value)
    reading = shown['goals'][0]['d1']
    assert reading['rows'] and not reading.get('diagnostics'), reading
    assert '求不等式 $f(x)\\le 0$ 的解集' in reading['summary']
    output = tmp_path / 'stage-three'
    result = runner.run_sample(tmp_path / 'stage-two/stage-two-result.json', output)
    assert result['status'] == 'completed', result
    goal, = result['goals']
    assert goal['status'] == 'solved', goal
    assert goal['primary'] == 'type-parity-inequality'
    assert goal['d3']['submit_label'] == '用奇偶性解不等式法解题'
    answer = goal['answer']
    assert answer['kind'] == 'find_range' and answer['set']['expression'] == 'Interval(-3, 3)'
    snapshot = open_store(output).snapshot()
    assert len(snapshot['handoffs']) == 1
    assert all(row['status'] == 'interactive' for row in snapshot['interaction_states'])
    assert runner.resume_sample(output)['goals'][0]['answer'] == answer
    assert open_store(output).snapshot()['handoffs'] == snapshot['handoffs']
    evidence = export_course(output, 'function-parity-a02')
    assert evidence['lesson']['goals'][0]['primary'] == 'type-parity-inequality'
    assert evidence['stream']['handoffs'][0]['answer'] == answer
    text = json.dumps(evidence['stream'], ensure_ascii=False)
    assert '左' not in text and '右' not in text
    parts = _parts(evidence)
    assert [part['title'] for part in parts] == ['先在已知范围内解不等式', '用奇偶性得到另一侧的解',
                                                  '合并各部分，写出解集']
    for part in parts:
        labels = [option['label'] for option in part['interaction']['options']]
        assert len(labels) == len(set(labels)) >= 3
        assert part['feedback']['answer'] == '结合卡片中的式子和范围，再核对一次。'
    conclude = [option['label'] for option in parts[2]['interaction']['options']]
    assert '$-3\\le x\\le 3$' in conclude


def test_odd_known_side_flips_threshold_end_to_end(tmp_path):
    value = candidate(('Dom(f)=ℝ', 'parity(f,odd)'), 'x', '[0,∞)', 'f(x)<=1',
                      text=r'已知 $f(x)$ 是定义在 $\mathbf R$ 上的奇函数，当 $x\ge0$ 时，$f(x)=x$，'
                           r'则不等式 $f(x)\le1$ 的解集为____．')
    recognize(value, tmp_path)
    output = tmp_path / 'stage-three'
    result = runner.run_sample(tmp_path / 'stage-two/stage-two-result.json', output)
    goal, = result['goals']
    assert goal['status'] == 'solved', goal
    assert goal['answer']['set']['expression'] == 'Interval(-oo, 1)'
    mirror = _parts(export_course(output, 'function-parity-t4-odd'))[1]
    assert '奇函数' in mirror['question'] and '$f(x)\\le 1$' in mirror['question']


@pytest.mark.parametrize('field,value', [('solution', encode_value(sp.Interval(0, 3))),
                                         ('mirror_threshold', encode_value(sp.Integer(1)))])
def test_corrupt_inequality_result_never_publishes(field, value, tmp_path):
    recognize(candidate(), tmp_path)

    def corrupt(state, store):
        state['parity_inequality_result_exact'][field] = value
    output = tmp_path / 'stage-three'
    result = runner.run_sample(tmp_path / 'stage-two/stage-two-result.json', output,
                               hooks={'before_verification': corrupt})
    goal, = result['goals']
    assert goal['answer'] is None
    assert goal['routes'][0]['status'] == 'math_failed'
    assert not open_store(output).snapshot()['handoffs']
    with pytest.raises(ValueError, match='course_export'):
        export_course(output, 'function-parity-a02')


ORDER_TITLES = ['改写成两个函数值的比较', '确定整个定义域上的单调方向', '去掉函数符号比较输入', '合法输入求交，写出解集']


def test_a18_printed_direction_compares_inputs_end_to_end(tmp_path):
    value = given()
    prepared, recognized = recognize(value, tmp_path)
    shown = present_lesson(recognized, prepared['features'], value['original_text'], candidate=value)
    reading = shown['goals'][0]['d1']
    assert reading['rows'] and '求满足 $f(1-2a)+f(a-3)>0$ 的 $a$ 的取值范围' in reading['summary']
    assert '$f(a)$' not in json.dumps(reading, ensure_ascii=False)
    output = tmp_path / 'stage-three'
    result = runner.run_sample(tmp_path / 'stage-two/stage-two-result.json', output)
    goal, = result['goals']
    assert goal['status'] == 'solved', goal
    assert goal['answer']['set']['expression'] == 'Interval(1, 3/2)'
    assert runner.resume_sample(output)['goals'][0]['answer'] == goal['answer']
    evidence = export_course(output, 'function-parity-a18')
    text = json.dumps(evidence['stream'], ensure_ascii=False)
    assert '左' not in text and '右' not in text and '先在已知范围内解不等式' not in text
    parts = _parts(evidence)
    assert [part['title'] for part in parts] == ORDER_TITLES
    for part in parts:
        labels = [option['label'] for option in part['interaction']['options']]
        assert len(labels) == len(set(labels)) >= 3
    assert '$1 - 2 a<3 - a$' in [o['label'] for o in parts[2]['interaction']['options']]


def test_a05_whole_problem_solves_both_goals(tmp_path):
    recognize(a05(), tmp_path)
    output = tmp_path / 'stage-three'
    result = runner.run_sample(tmp_path / 'stage-two/stage-two-result.json', output)
    first, second = result['goals']
    assert first['status'] == second['status'] == 'solved', result
    assert second['primary'] == 'type-parity-inequality'
    assert second['answer']['set']['expression'] == 'Interval.open(-1, 1/2)'
    titles = [part['title'] for part in _parts(export_course(output, 'function-parity-a05'))]
    assert titles[-4:] == ORDER_TITLES


@pytest.mark.parametrize('field,value', [('solution', encode_value(sp.Interval(1, 2))),
                                         ('converted_operator', '>')])
def test_corrupt_order_result_never_publishes(field, value, tmp_path):
    recognize(given(), tmp_path)

    def corrupt(state, store):
        state['parity_inequality_result_exact'][field] = value
    output = tmp_path / 'stage-three'
    result = runner.run_sample(tmp_path / 'stage-two/stage-two-result.json', output,
                               hooks={'before_verification': corrupt})
    goal, = result['goals']
    assert goal['answer'] is None and goal['routes'][0]['status'] == 'math_failed'
    assert not open_store(output).snapshot()['handoffs']
