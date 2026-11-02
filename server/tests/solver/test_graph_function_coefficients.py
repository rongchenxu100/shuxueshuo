"""B: complete candidates, honest goals, type/source guards and shared cards."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.function_coefficients import (
    coefficient_source, compare_coefficients, recover_coefficients, verify_coefficients,
)
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.coefficients_runtime import (
    coefficient_target_roots, coefficient_target_signs, answer_for,
)
from tests.solver.test_graph_function_formula import TARGET, candidate

ROOT = Path(__file__).resolve().parents[3]


def record(name):
    return json.loads((ROOT/'internal/senior-high/authored-courses/function-formula-b-20261101'/f'{name}.json').read_text())


@pytest.mark.parametrize('name', ['b04', 'w01', 'w12', 'b04-v', 'w10'])
def test_original_questions_keep_all_answers_and_source_conditions(name, monkeypatch):
    from shuxueshuo_server.graph_lesson.stage_one.authored import prepare_authored
    from shuxueshuo_server.graph_lesson.stage_two.contracts import validate_input
    from shuxueshuo_server.graph_lesson.stage_two.formula_surface import formula_source_spans
    from shuxueshuo_server.graph_lesson.stage_two.fragments import _abstract_formula_matches
    r = record(name); c = r['candidate']
    prepared = prepare_authored(c, run_id='coefficient-test', sources=r['sources'], reviewer=r['reviewer'])
    assert validate_input(prepared, admission='authored_topic')['ok']
    d = build_context(c, TARGET)['formula_goal']; result = recover_coefficients(d)
    x = result['variable']
    assert set(result['candidates']) == {sp.sympify(p, locals={'x': x}) for p in r['expected']['candidates']}
    assert formula_source_spans(c, TARGET, [(0,len(c['original_text']))], d, _abstract_formula_matches)
    monkeypatch.setattr('shuxueshuo_server.graph_lesson.function_coefficients.recover_coefficients', lambda _: pytest.fail('independent verifier'))
    monkeypatch.setattr('shuxueshuo_server.graph_lesson.function_coefficients.solve_coefficients', lambda *_: pytest.fail('independent completeness check'))
    assert verify_coefficients(d, result)
    wrong = deepcopy(result); wrong['candidates'][0] += 1
    assert not verify_coefficients(d, wrong)
    wrong = deepcopy(result);wrong['determined_domain'] = sp.Interval(0,1)
    assert not verify_coefficients(d, wrong)
    if len(result['candidates']) > 1:
        wrong = deepcopy(result);wrong['candidates'].pop();wrong['coefficient_tuples'].pop()
        assert not verify_coefficients(d, wrong)
    answer = answer_for(result)
    assert answer['kind'] == c['root']['goals'][0]['kind']
    if name == 'b04':
        assert result['value'] == 1 and result['values'] == [1,1]
    if name == 'w10':
        assert result['solution'] == sp.Interval.open(0, sp.Rational(7,3))
        roots = coefficient_target_roots(d, result)['outputs']['root_records']
        assert roots[0]['roots'] == [0,sp.Rational(7,3)]
        coefficient_target_signs(d, result, roots)
        assert len(c['root']['goals']) == 1  # no invented formula goal


def test_same_scalar_is_not_assumed_for_multiple_functions():
    c=record('b04')['candidate'];c['root']['goals'][0]['expression']='f(0)'
    r=recover_coefficients(build_context(c,TARGET)['formula_goal'])
    assert r['status']=='insufficient_information' and r['value'] is None and set(r['values'])=={-1,3}


def test_multiple_functions_do_not_imply_a_unique_inequality_solution():
    c=record('w10')['candidate'];goal=c['root']['goals'][0]
    goal.update(function_type='linear', relation='f(f(x))=4*x-3')
    goal.pop('additional_relations')
    r=recover_coefficients(build_context(c,TARGET)['formula_goal'])
    assert r['status']=='insufficient_information' and r['solution'] is None
    assert len(set(r['solution_sets']))==2
    assert verify_coefficients(build_context(c,TARGET)['formula_goal'],r)
    assert answer_for(r)['kind']=='find_range'


def test_single_relation_methods_cannot_drop_additional_conditions():
    from shuxueshuo_server.graph_lesson.function_formula import source_values
    from shuxueshuo_server.graph_lesson.function_matching import available
    c=candidate('f(x-1/x)=x**2+1/x**2',additional_relations=['f(0)=3'])
    d=build_context(c,TARGET)['formula_goal']
    with pytest.raises(ValueError):source_values(d)
    assert not available(d)


@pytest.mark.parametrize('relation,fields', [
    ('f(f(x))=4*x-3', {'function_type':None}),
    ('f(f(x))=4*x-3', {'relation_domain':'{0,1}'}),
    ('f(x)/x=1', {}),
    ('f(f(x))=x**4', {'function_type':'quadratic'}),
    ('f(x)=k*x', {}),
])
def test_unsupported_or_nonuniversal_source_never_admitted(relation, fields):
    from shuxueshuo_server.graph_lesson.stage_three.coefficients_runtime import admitted
    fields={'function_type':'linear',**fields}
    if fields.get('function_type') is None:fields.pop('function_type')
    assert not admitted(build_context(candidate(relation,**fields), TARGET))


@pytest.mark.parametrize('relation', ['f(f(x))=x', 'f(x)=0', 'f(f(x))=-x'])
def test_infinite_degenerate_or_no_real_candidates_are_not_published(relation):
    d=build_context(candidate(relation,function_type='linear'),TARGET)['formula_goal']
    with pytest.raises(ValueError):recover_coefficients(d)


def test_coefficient_skill_requires_identity_and_keeps_missing_terms():
    x,a,b=sp.symbols('x a b',real=True)
    relations=[sp.Eq(a*x+b,2*x,evaluate=False)]
    r=compare_coefficients(relations,x,[a,b],sp.S.Reals)
    assert r['equations']==[a-2,b]
    with pytest.raises(ValueError):compare_coefficients(relations,x,[a,b],sp.FiniteSet(0,1))


def test_selection_and_cards_use_stated_type_without_solving(monkeypatch):
    from shuxueshuo_server.graph_lesson.stage_three.selection import evaluate_goal
    from shuxueshuo_server.graph_lesson.stage_three.formula_presentation import compile_formula
    from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value
    from shuxueshuo_server.learning.graph_walk import grade
    from shuxueshuo_server.graph_lesson.stage_three.execution_contracts import load_contracts
    c=record('b04')['candidate'];d=build_context(c,TARGET)['formula_goal'];r=recover_coefficients(d)
    monkeypatch.setattr('shuxueshuo_server.graph_lesson.function_coefficients.recover_coefficients',lambda _:pytest.fail('selection cannot solve'))
    s=evaluate_goal(c,TARGET,[],'type-function-formula')
    assert [o['method'] for o in s['d4']['options']]==['method-function-coefficients']
    assert s['d3']['expected_answer']['checks']=={'source_structure':'function_type'}
    assert 'method-function-coefficients' in load_contracts()
    for phase in ('template','expand','compare','solve','verify','answer'):
        p=compile_formula([{'values':encode_value({'description':d,'formula_result':r,'phase':phase})}],phase)['parts'][0]
        assert grade(p,{'value':p['expected_answer']['one_of'][0]},'function-coefficients')=='passed'
        assert p['stem_board']['items'][1]['math'] is None


def test_source_binding_rejects_misread_type_or_unrecorded_initial_condition():
    from shuxueshuo_server.graph_lesson.stage_two.formula_surface import formula_source_spans
    from shuxueshuo_server.graph_lesson.stage_two.fragments import _abstract_formula_matches
    c=record('b04-v')['candidate'];c['root']['goals'][0]['function_type']='linear'
    d=build_context(c,TARGET)['formula_goal']
    assert not formula_source_spans(c,TARGET,[(0,len(c['original_text']))],d,_abstract_formula_matches)
    c=record('b04-v')['candidate'];c['root']['goals'][0].pop('additional_relations')
    d=build_context(c,TARGET)['formula_goal']
    assert not formula_source_spans(c,TARGET,[(0,len(c['original_text']))],d,_abstract_formula_matches)


@pytest.mark.parametrize('name', ['b04', 'b04-v', 'w10'])
def test_coefficient_comparison_keeps_previous_equations_as_context(name):
    from shuxueshuo_server.graph_lesson.stage_three.formula_presentation import compile_formula
    from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value

    desc = build_context(record(name)['candidate'], TARGET)['formula_goal']
    result = recover_coefficients(desc)

    def card(phase):
        seed = {'values': encode_value({'description': desc, 'formula_result': result, 'phase': phase})}
        return compile_formula([seed], phase)['parts'][0]

    previous, comparison = card('expand'), card('compare')
    equations = previous['completion_board']['items'][1]['math']
    assert f'${equations}$' in comparison['question']
    assert comparison['completion_board']['items'][1]['math'] not in comparison['question']
    assert comparison['stem_board']['items'][1]['math'] is None


@pytest.mark.parametrize('name,multiple', [('w10', False), ('b04-v', False), ('b04', True)])
def test_verification_wording_matches_the_number_of_results(name, multiple):
    from shuxueshuo_server.graph_lesson.stage_three.formula_presentation import compile_formula
    from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value

    desc = build_context(record(name)['candidate'], TARGET)['formula_goal']
    result = recover_coefficients(desc)
    seed = {'values': encode_value({'description': desc, 'formula_result': result, 'phase': 'verify'})}
    part = compile_formula([seed], 'verify')['parts'][0]
    assert part['title'] == ('把每个结果代回检查' if multiple else '把结果代回检查')
    if not multiple:
        text = json.dumps(part, ensure_ascii=False)
        assert all(word not in text for word in ('这些解析式', '它们', '逐个', '其中一个解析式'))
        assert '代回原题的全部等式，并检查函数类型' in text
        assert '只检查函数类型，不代回原题' in text


@pytest.mark.parametrize('expression,side,strict,roots,pieces', [
    ('f(x)>0', 'above', True, [0, sp.Rational(7, 3)], [(0, 7/3, False, False)]),
    ('f(x)<=0', 'below', False, [0, sp.Rational(7, 3)],
     [(None, 0, False, True), (7/3, None, True, False)]),
    ('f(x)>=2', 'above', False, [1, sp.Rational(4, 3)], [(1, 4/3, True, True)]),
])
def test_inequality_graph_keeps_the_solution_for_completion(expression, side, strict, roots, pieces):
    from jsonschema import Draft202012Validator
    from shuxueshuo_server.graph_lesson.stage_three.formula_presentation import compile_formula
    from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value

    c = record('w10')['candidate']
    c['root']['goals'][0]['expression'] = expression
    desc = build_context(c, TARGET)['formula_goal']
    result = recover_coefficients(desc)
    seed = {'values': encode_value({'description': desc, 'formula_result': result, 'phase': 'answer'})}
    compiled = compile_formula([seed], 'a'*24)
    assert compiled['diagnostics'] == []
    part = compiled['parts'][0]
    schema = json.loads((ROOT/'internal/schemas/graph-step-interaction-v1.schema.json').read_text())
    Draft202012Validator({'$ref': '#/$defs/part', '$defs': schema['$defs']}).validate(part)
    stem = part['graph']
    assert stem['kind'] == 'quadratic'
    assert stem['params']['coefficient'] == -1.5
    assert stem['params']['vertex'][0] == pytest.approx(7/6)
    assert stem['params']['xTicks'] == [[float(root), str(root)] for root in roots]
    assert 'markSign' not in stem['params'] and 'solution' not in stem['params']
    assert part['stem_board']['items'][1]['math'] is None
    curve, line = part['completion_graphs']
    assert curve['params']['markSign'] == side
    assert curve['params']['strict'] is strict
    assert curve['params']['points'] == [{'x': float(root), 'open': strict} for root in roots]
    assert line['kind'] == 'number_line'
    assert line['params']['pieces'] == [dict(zip(('from', 'to', 'left_closed', 'right_closed'), p)) for p in pieces]
    if expression == 'f(x)>=2':
        assert curve['params']['vertex'][1] == pytest.approx(1/24)
        assert r'f(x)-\left(2\right)' in stem['caption']


def test_unavailable_inequality_graph_preserves_the_question(monkeypatch):
    from shuxueshuo_server.graph_lesson.stage_three import interaction_graphs as drawing
    from shuxueshuo_server.graph_lesson.stage_three.formula_presentation import compile_formula
    from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value

    desc = build_context(record('w10')['candidate'], TARGET)['formula_goal']
    result = recover_coefficients(desc)
    def unavailable(*args, **kwargs):
        raise drawing.GraphUnavailable('marks_overlap')
    monkeypatch.setattr(drawing, 'function_graph', unavailable)
    compiled = compile_formula([{'values': encode_value({
        'description': desc, 'formula_result': result, 'phase': 'answer'})}], 'inequality')
    part = compiled['parts'][0]
    assert 'graph' not in part and 'completion_graphs' not in part
    assert part['question'] == '结合零点和开口方向，原不等式的解集是什么？'
    assert part['expected_answer']['one_of']
    assert compiled['diagnostics'] == [{'kind': 'graph_unavailable', 'reason': 'marks_overlap'}]


@pytest.mark.parametrize('name,initial', [('w10', 0), ('b04-v', 1)])
def test_expansion_conditions_show_both_original_relations_without_their_answers(name, initial):
    from jsonschema import Draft202012Validator
    from shuxueshuo_server.graph_lesson.stage_three.formula_presentation import compile_formula
    from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value
    from shuxueshuo_server.graph_lesson.stage_three.math_values import latex

    desc = build_context(record(name)['candidate'], TARGET)['formula_goal']
    result = recover_coefficients(desc)
    seed = {'values': encode_value({'description': desc, 'formula_result': result, 'phase': 'expand'})}
    part = compile_formula([seed], 'a'*24)['parts'][0]
    schema = json.loads((ROOT/'internal/schemas/graph-step-interaction-v1.schema.json').read_text())
    Draft202012Validator({'$ref': '#/$defs/part', '$defs': schema['$defs']}).validate(part)
    groups = part['stem_board']['condition_groups']
    f, x = sp.Function('f'), result['variable']
    assert groups[0]['math'] == latex(sp.Eq(f(0), initial, evaluate=False))
    relation = sp.Eq(f(x-1), f(x)+3*x-5, evaluate=False) if name == 'w10' else sp.Eq(f(x+1)-f(x), 2*x, evaluate=False)
    assert groups[1]['math'] == latex(relation)
    assert '2 个条件' in part['question']
    assert part['completion_board']['condition_groups'] == groups
    assert part['stem_board']['items'][1]['math'] is None
    assert f'c = {initial}' not in json.dumps(part['stem_board'], ensure_ascii=False)
    # Both choices account for the initial value; no option quietly drops it.
    assert all(f'c = {initial}' in option['label'] for option in part['interaction']['options'])


@pytest.mark.parametrize('name', ['b04', 'w01', 'w12', 'b04-v', 'w10'])
def test_full_derivation_contains_concrete_work_for_every_coefficient_step(name):
    from shuxueshuo_server.graph_lesson.stage_three.formula_presentation import presentation, phase_view
    from shuxueshuo_server.graph_lesson.stage_three.math_values import latex

    desc = build_context(record(name)['candidate'], TARGET)['formula_goal']
    result = recover_coefficients(desc)
    working = {}
    for phase in ('template', 'expand', 'compare', 'solve', 'verify', 'answer'):
        values = {'description': desc, 'formula_result': result, 'phase': phase}
        working[phase] = presentation(values)['formula_explanation']
        assert '$' in working[phase] and '=' in working[phase]
        assert working[phase] != phase_view(values)['explanation']
    assert r'a\ne0' in working['template']
    for candidate in result['candidates']:
        assert latex(candidate) in working['solve']
        assert latex(candidate) in working['verify']
        assert latex(candidate) in working['answer']
    if name == 'w10':
        assert 'c = 0' in working['expand']
        assert r'a \left(x - 1\right)^{2}' in working['expand']
        assert '- 2 a + b = b + 3' in working['compare']
        assert r'\frac{7}{2} - b = 0' in working['solve']
        assert r'\frac{13 x}{2} - 5' in working['verify']
        assert '&-&0&+&0&-' in working['answer']
        assert latex(sp.Interval.open(0, sp.Rational(7, 3))) in working['answer']
    elif name == 'b04-v':
        assert 'c = 1' in working['expand'] and 'c = 0' not in working['expand']
    elif name == 'b04':
        assert 'a=-2' in working['solve'] and 'a=2' in working['solve']
        assert r'f(1)=3 - 2 \left(1\right)=1' in working['answer']
