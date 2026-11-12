"""Source and answer-contract regressions found by genuine T6 photo calls."""

from copy import deepcopy

import pytest

from shuxueshuo_server.graph_lesson import shifted_odd_math as math
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.trajectory import (
    decode_value,
    encode_value,
)
from tests.solver.test_graph_shifted_odd import TARGET, originals


def range_request(*, upper='M', lower='m', domain='[-1,1]', declared=False):
    p = originals()[-1]
    p['root']['facts'] = ['Dom(f)=ℝ'] if declared else []
    p['root']['goals'] = [{
        'kind': 'find_range', 'object': 'f', 'input_domain': domain,
        'answer_request': {'kind': 'expression', 'bindings': [
            {'symbol': upper, 'quantity': 'maximum'}, {'symbol': lower, 'quantity': 'minimum'}],
            'expression': lower + '+' + upper},
    }]
    p['original_text'] = (r'已知函数 $f(x)=\frac{(x+1)^2+ax^5}{x^2+1}$，'
                          + (r'定义域为 $\mathbb R$，' if declared else '')
                          + r'当 $x\in ' + domain + '$ 时，最大值为 $' + upper
                          + '$，最小值为 $' + lower + '$，其中 $a$ 为常数，则 $'
                          + lower + '+' + upper + r'=\_\_\_$。')
    return p


@pytest.mark.parametrize('upper,lower,declared', [('M', 'm', False), ('U', 'L', True), ('a', 'b', False)])
def test_existing_extrema_request_preserves_bindings_scope_and_parameter_roles(upper, lower, declared):
    p = range_request(upper=upper, lower=lower, declared=declared)
    original = deepcopy(p)
    d = build_context(p, TARGET)['shifted_odd_goal']
    assert d['structure_supported'], d
    assert d['source'] == original['root']['goals'][0]
    assert p == original
    assert TARGET in d['source_refs']
    m = math.solve(d)
    assert m['proof']['value'] == 2
    assert math.verify(d, decode_value(encode_value(m)))
    bad = deepcopy(m)
    bad['proof']['value'] = 3
    assert not math.verify(d, bad)


def test_legacy_extrema_goal_consumes_the_same_adapter():
    p = range_request()
    goal = p['root']['goals'][0]
    request = goal.pop('answer_request')
    goal.update(kind='find_extrema_expression', expression=request['expression'], extrema=[
        {'symbol': r['symbol'], 'kind': r['quantity']} for r in request['bindings']])
    d = build_context(p, TARGET)['shifted_odd_goal']
    assert d['structure_supported']
    assert math.solve(d)['proof']['value'] == 2


def test_open_interval_request_does_not_invent_attained_extrema():
    d = build_context(range_request(domain='(-1,1)'), TARGET)['shifted_odd_goal']
    with pytest.raises(ValueError, match='attained_extrema_required'):
        math.solve(d)


@pytest.mark.parametrize('change', ['difference', 'infimum', 'wrong_function', 'omitted_range'])
def test_other_range_requests_and_unbound_conditions_cannot_receive_the_sum_result(change):
    p = range_request()
    goal = p['root']['goals'][0]
    if change == 'difference':
        goal['answer_request']['expression'] = 'M-m'
    elif change == 'infimum':
        goal['answer_request']['bindings'][1]['quantity'] = 'infimum'
    elif change == 'wrong_function':
        p['root']['definitions'].append('g(x)=x^2')
        goal['object'] = 'g'
    else:
        goal.pop('input_domain')
    d = build_context(p, TARGET).get('shifted_odd_goal')
    assert d is None or not d['structure_supported']


@pytest.mark.parametrize('colon', [':', '：'])
def test_function_introduction_before_conditions_is_not_a_second_parity_subject(colon):
    p = originals()[0]
    p['original_text'] = '若函数 $f(x)$ 满足' + colon + p['original_text']
    d = build_context(p, TARGET)['shifted_odd_goal']
    assert d['structure_supported']
    assert math.solve(d)['proof']['value'] == -13


def test_plain_source_math_preserves_offsets_and_extra_conditions():
    p = originals()[0]
    p['original_text'] = '16. 若函数f(x)满足：g(x)=f(x)+2是R上的奇函数，且f(1)=9，则f(-1)的值为____。'
    d = build_context(p, TARGET)['shifted_odd_goal']
    assert d['structure_supported']
    assert math.solve(d)['proof']['value'] == -13
    from shuxueshuo_server.graph_lesson.stage_two.shifted_odd_surface import (
        source_spans,
    )

    spans = source_spans(p, TARGET, [(0, len(p['original_text']))], d)
    assert {p['original_text'][a:b] for a, b, kind, _ in spans if kind == 'goal'} == {'f(-1)', '____'}
    p['original_text'] = p['original_text'].replace('且f(1)=9', '且f(x)为偶函数，f(1)=9')
    assert not build_context(p, TARGET)['shifted_odd_goal']['structure_supported']


@pytest.mark.parametrize('declaration', ['a为常数。', 'a 是实常数', 'a∈ℝ'])
def test_explicit_constant_declaration_keeps_the_parameter_free(declaration):
    p = range_request()
    p['root']['facts'] = [declaration]
    d = build_context(p, TARGET)['shifted_odd_goal']
    assert d['structure_supported']
    assert math.solve(d)['proof']['value'] == 2
    p['root']['facts'] = ['b为常数。']
    assert not build_context(p, TARGET)['shifted_odd_goal']['structure_supported']


def test_only_nonmathematical_textbook_heading_is_ignored():
    p = originals()[1]
    p['original_text'] = '类型VI：奇函数+常数结论的应用\n【例15】' + p['original_text']
    assert build_context(p, TARGET)['shifted_odd_goal']['structure_supported']
    p['original_text'] = p['original_text'].replace('【例15】', '【例15】且 $f(x)$ 是偶函数，')
    assert not build_context(p, TARGET)['shifted_odd_goal']['structure_supported']


@pytest.mark.parametrize('blank', ['____', r'\_\_\_', r'\underline{\quad}', r'\underline{\qquad}'])
def test_printed_answer_blanks_do_not_become_supplied_equalities(blank):
    p = originals()[1]
    p['original_text'] = p['original_text'].replace('求 $f(2)$ 的值', '则 $f(2)=' + blank + '$')
    d = build_context(p, TARGET)['shifted_odd_goal']
    assert d['structure_supported']
    assert math.solve(d)['proof']['value'] == -1
    p['original_text'] = p['original_text'].replace(blank, '7')
    assert not build_context(p, TARGET)['shifted_odd_goal']['structure_supported']


def test_adapted_extrema_remain_bound_to_the_frozen_goal_and_entries():
    from shuxueshuo_server.graph_lesson.stage_three.symmetry_runtime import admitted

    context = build_context(range_request(), TARGET)
    assert admitted(context)
    changed = deepcopy(context)
    changed['goal']['answer_request']['expression'] = 'M-m'
    assert not admitted(changed)
    changed = deepcopy(context)
    changed['shifted_odd_goal']['given_entries'][-1]['ast'][2][1] = 'max'
    assert not admitted(changed)


@pytest.mark.parametrize('legacy', [False, True])
def test_extrema_sum_closes_only_the_original_scalar_request(legacy):
    from shuxueshuo_server.graph_lesson.stage_three.handoff import (
        _symmetry_expression_answer,
    )
    from shuxueshuo_server.graph_lesson.stage_three.shifted_odd_runtime import finish

    p = range_request()
    if legacy:
        goal = p['root']['goals'][0]
        request = goal.pop('answer_request')
        goal.update(kind='find_extrema_expression', expression=request['expression'], extrema=[
            {'symbol': r['symbol'], 'kind': r['quantity']} for r in request['bindings']])
    context = build_context(p, TARGET)
    model = encode_value(math.solve(context['shifted_odd_goal']))
    output = finish({'symmetry_result_exact': model}, context, [])
    answer = output['answer']
    assert answer['kind'] == ('find_extrema_expression' if legacy else 'derived_answer')
    assert answer['status'] == 'value' and answer['value']['expression'] == '2'
    assert 'set' not in answer
    route = {'result': {'answer': answer, 'symmetry_result': model}}
    assert _symmetry_expression_answer(route, answer)
    bad = deepcopy(answer)
    bad['value']['exact']['value'] = '3'
    route['result']['answer'] = bad
    assert not _symmetry_expression_answer(route, bad)
    route['result']['answer'] = answer
    route['result']['symmetry_result']['extrema'] = None
    assert not _symmetry_expression_answer(route, answer)


@pytest.mark.stage_three_db
@pytest.mark.parametrize('declaration', [False, True])
def test_legacy_extrema_request_executes_and_resumes(tmp_path, declaration):
    from shuxueshuo_server.graph_lesson.stage_three import runner
    from tests.solver.test_graph_function_parity_recognition import recognize

    p = range_request(upper='U', lower='L', declared=True)
    if declaration:
        p['root']['facts'].append('a为常数。')
    goal = p['root']['goals'][0]
    request = goal.pop('answer_request')
    goal.update(kind='find_extrema_expression', expression=request['expression'], extrema=[
        {'symbol': r['symbol'], 'kind': r['quantity']} for r in request['bindings']])
    recognize(p, tmp_path)
    output = tmp_path / 'execution'
    result = runner.run_sample(tmp_path / 'stage-two/stage-two-result.json', output)
    assert result['status'] == 'completed'
    assert result['goals'][0]['answer']['kind'] == 'find_extrema_expression'
    assert result['goals'][0]['answer']['value']['expression'] == '2'
    assert runner.resume_sample(output)['goals'] == result['goals']
