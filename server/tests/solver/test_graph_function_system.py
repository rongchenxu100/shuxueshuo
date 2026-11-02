"""C: original relations, legal interchanges, elimination and shared lessons."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.function_system import recover_system, verify_system
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from tests.solver.test_graph_function_formula import TARGET, candidate, description

ROOT=Path(__file__).resolve().parents[3]
NAMES=['b06','b06-v','w03','w05','w06','w07','w14']


def record(name):
    return json.loads((ROOT/'internal/senior-high/authored-courses/function-formula-c-20261101'/f'{name}.json').read_text())


@pytest.mark.parametrize('name',NAMES)
def test_original_question_identity_domain_binding_and_independent_verification(name,monkeypatch):
    from shuxueshuo_server.graph_lesson.stage_one.authored import prepare_authored
    from shuxueshuo_server.graph_lesson.stage_two.contracts import validate_input
    from shuxueshuo_server.graph_lesson.stage_two.formula_surface import formula_source_spans
    from shuxueshuo_server.graph_lesson.stage_two.fragments import _abstract_formula_matches
    r=record(name);c=r['candidate'];d=description(c)
    assert d['structure_supported'] and d['structure_version']=='function-formula-system/v1'
    prepared=prepare_authored(c,run_id='system-test',sources=r['sources'],reviewer=r['reviewer'])
    checked=validate_input(prepared,admission='authored_topic')
    assert checked['ok'],checked
    assert formula_source_spans(c,TARGET,[(0,len(c['original_text']))],d,_abstract_formula_matches)
    result=recover_system(d);x=result['variable']
    assert sp.simplify(result['expression']-sp.sympify(r['expected']['expression'],locals={'x':x}))==0
    assert result['determined_domain']==(sp.S.Reals if r['expected']['domain']=='ℝ' else sp.S.Reals-sp.FiniteSet(0))
    monkeypatch.setattr('shuxueshuo_server.graph_lesson.function_system.recover_system',lambda _:pytest.fail('independent verifier'))
    monkeypatch.setattr('shuxueshuo_server.graph_lesson.function_system.eliminate',lambda *_:pytest.fail('independent verifier'))
    assert verify_system(d,result)
    for key,wrong in [('expression',result['expression']+1),('source_domain',sp.FiniteSet(1)),
                      ('determined_domain',sp.FiniteSet(1)),('transform',x+1),('determinant',sp.S.Zero)]:
        assert not verify_system(d,{**result,key:wrong})
    if name=='w07':
        assert '非零实数' in c['original_text'] and len(r['sources'])==2
        wrong=deepcopy(c);wrong['original_text']=wrong['original_text'].replace('非零实数','实数')
        assert not formula_source_spans(wrong,TARGET,[(0,len(wrong['original_text']))],d,_abstract_formula_matches)


@pytest.mark.parametrize('relation,fields',[
    ('2*p(u)-p(3-u)=u**2+1',{'function':'p','variable':'u'}),
    ('3*f(x)+f(-2/x)=x-1/x',{}),
    ('2*f(x)+f(2/x)=3**x+1',{}),
    ('2*f(x)-f(-x)=10**(2*x+1)',{}),
])
def test_closed_involution_family_and_fixed_points(relation,fields):
    d=description(candidate(relation,**fields));r=recover_system(d)
    assert verify_system(d,r)
    x=r['variable']
    for point in sp.solve(x-r['transform'],x):
        if point.is_real is True and point in r['determined_domain']:
            assert r['expression'].subs(x,point).is_finite


@pytest.mark.parametrize('relation,fields',[
    ('2*f(x)-f(x+1)=x',{}),
    ('2*f(x)-f(x**2)=x',{}),
    ('x*f(x)-f(-x)=x',{}),
    ('f(x)*f(-x)=1',{}),
    ('2*f(x)-f(-x)=1/x',{}),
    ('2*f(x)-f(1/x)=x+(x-1)/(x-1)',{}),
    ('2*f(x)-f(1/x)=x',{'relation_domain':'ℝ'}),
    ('2*f(x)-f(-x)=x',{'relation_domain':'(0,+∞)'}),
    ('2*f(x)-f(-x)=x',{'function_type':'linear'}),
    ('2*f(x)-f(-x)=x',{'additional_relations':['f(0)=1']}),
    ('2*f(x)-f(1/x)=(-2)**x',{}),
])
def test_outside_scope_cannot_enter_system_route(relation,fields):
    from shuxueshuo_server.graph_lesson.stage_three.system_runtime import admitted
    assert not admitted(build_context(candidate(relation,**fields),TARGET))


@pytest.mark.parametrize('relation,code',[
    ('f(x)+f(-x)=x','no_solution'),
    ('f(x)+f(-x)=2','insufficient_information'),
    ('f(x)-f(-x)=1','no_solution'),
    ('f(x)-f(-x)=x','insufficient_information'),
    ('f(x)+f(1/x)=10**x','no_solution'),
])
def test_zero_determinant_never_divided_or_published_as_a_unique_rule(relation,code):
    d=description(candidate(relation))
    with pytest.raises(ValueError,match='function_system.'+code):recover_system(d)


def test_declared_full_domain_does_not_invent_the_value_at_zero():
    d=description(candidate('2*f(x)-f(1/x)=x',declared_domain='ℝ',requested_domain='ℝ'))
    r=recover_system(d)
    assert r['status']=='insufficient_information'
    assert 0 not in r['determined_domain'] and verify_system(d,r)


def test_shared_route_and_cards_without_solving_during_selection(monkeypatch):
    from shuxueshuo_server.graph_lesson.stage_three import system_runtime as rt
    from shuxueshuo_server.graph_lesson.stage_three.selection import evaluate_goal
    from shuxueshuo_server.graph_lesson.stage_three.formula_presentation import compile_formula
    from shuxueshuo_server.graph_lesson.stage_three.execution_contracts import load_contracts
    from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value
    from shuxueshuo_server.learning.graph_walk import grade
    c=record('b06-v')['candidate'];ctx=build_context(c,TARGET);d=ctx['formula_goal']
    assert 'method-function-equation-system' in load_contracts()
    swapped=rt.interchange_function_inputs(d)['outputs']['rhs_swapped']
    raw=rt.eliminate_function_values(d,swapped)['outputs']['raw_expression']
    r=rt.simplify_system_formula(d,raw)['outputs']['formula_result']
    rt.verify_system_formula(d,r)
    monkeypatch.setattr('shuxueshuo_server.graph_lesson.function_system.eliminate',lambda *_:pytest.fail('selection cannot solve'))
    selected=evaluate_goal(c,TARGET,[],'type-function-formula')
    assert [o['method'] for o in selected['d4']['options']]==['method-function-equation-system']
    assert selected['d3']['expected_answer']['checks']=={'source_structure':'paired_values'}
    for phase in ('swap','second','eliminate','verify','answer'):
        p=compile_formula([{'values':encode_value({'description':d,'formula_result':r,'phase':phase})}],phase)['parts'][0]
        assert p['stem_board']['items'][1]['math'] is None
        for option in p['interaction']['options']:
            passed=grade(p,{'value':option['value']},'function-system')=='passed'
            assert passed==(option['value'] in p['expected_answer']['one_of'])


@pytest.mark.parametrize('name', ['b06', 'w06', 'w14'])
def test_system_cards_show_the_original_check_and_concrete_work(name):
    from jsonschema import Draft202012Validator
    from shuxueshuo_server.graph_lesson.stage_three.formula_presentation import compile_formula, presentation, phase_view
    from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value

    desc = build_context(record(name)['candidate'], TARGET)['formula_goal']
    result = recover_system(desc)
    working = {}
    for phase in ('swap', 'second', 'eliminate', 'verify', 'answer'):
        values = {'description': desc, 'formula_result': result, 'phase': phase}
        working[phase] = presentation(values)['formula_explanation']
        assert '$' in working[phase] and '=' in working[phase]
        assert working[phase] != phase_view(values)['explanation']

    part = compile_formula([{'values': encode_value({
        'description': desc, 'formula_result': result, 'phase': 'verify'})}], 'a'*24)['parts'][0]
    schema = json.loads((ROOT/'internal/schemas/graph-step-interaction-v1.schema.json').read_text())
    Draft202012Validator({'$ref': '#/$defs/part', '$defs': schema['$defs']}).validate(part)
    assert '原关系是 $' in part['question'] and '代入左边 $' in part['question']
    assert part['stem_board']['items'][1]['math'] is None
    stem = part['stem_board']['items'][0]['math']
    assert r'\cdot' in stem
    assert '原关系：$' in working['verify'] and '代回原等式左边：$' in working['verify']

    if name == 'b06':
        assert r'2 f{\left(x \right)} - f{\left(- x \right)}=3 x' in part['question']
        assert r'2\cdot \left(x\right) - \left(- x\right)' in stem
        for equation in (
            r'4 f{\left(x \right)} - 2 f{\left(- x \right)}=6 x',
            r'2 f{\left(- x \right)} - f{\left(x \right)}=- 3 x',
            r'3 f{\left(x \right)} = 3 x',
            r'f{\left(x \right)}=\frac{3 x}{3}=x',
        ):
            assert equation in working['eliminate']
    elif name == 'w06':
        # Positive coefficients require subtracting the second scaled equation.
        assert r'-6 f{\left(- x + 1 \right)} - 4 f{\left(x \right)}=8 x - 8' in working['eliminate']
        assert r'5 f{\left(x \right)} = 20 x - 8' in working['eliminate']
    else:
        assert r'x\ne0' in working['swap'] and r'x\ne0' in working['verify']
        assert r'10^{\frac{1}{x}}' in working['second']
        assert r'=10^{x}' in working['verify']
