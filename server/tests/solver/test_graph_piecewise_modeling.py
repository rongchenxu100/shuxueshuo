"""P5: marginal billing semantics, target isolation and source-bound lessons."""
import json
from copy import deepcopy
from pathlib import Path

import pytest
import sympy as sp
from jsonschema import Draft202012Validator

from shuxueshuo_server.graph_lesson import piecewise_equation as pe
from shuxueshuo_server.graph_lesson import piecewise_modeling as pm
from shuxueshuo_server.graph_lesson.stage_one.runner import candidate_features
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.piecewise_equation_presentation import (
    compile_piecewise,
)
from shuxueshuo_server.graph_lesson.stage_three.piecewise_modeling_presentation import (
    compile_step,
)
from shuxueshuo_server.graph_lesson.stage_three.selection import evaluate_goal
from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value
from shuxueshuo_server.graph_lesson.stage_two.fragments import build_d1
from shuxueshuo_server.learning.graph_walk import grade
from shuxueshuo_server.search.lesson import d1_rows

ROOT = Path(__file__).resolve().parents[3]
MODEL, INVERSE = '/root/goals/0', '/root/goals/1'


def candidate(bill='199', rates=None):
    c = json.loads((ROOT/'internal/senior-high/authored-courses/piecewise-p5-20261102/b12.json').read_text())['candidate']
    p = c['root']['goals'][0]['pricing']
    if rates:
        p['rates'] = rates
    text = pm.statement(p, bill)
    c['original_text'] = text
    for g in c['root']['goals']:
        g.update(pricing=deepcopy(p), bill=bill, source_text=text)
    return c


def inverse(c):
    ctx = build_context(c, INVERSE)
    roots = pe.solve_branches(ctx)['outputs']
    return ctx, {**roots, **pe.filter_branches(roots['description'], roots['branch_roots'])['outputs']}


def test_cumulative_model_boundaries_and_complete_domain():
    c = candidate(); before = deepcopy(c)
    ctx = build_context(c, MODEL); built = pm.build(ctx)['outputs']['model_result']
    x = sp.Symbol('x', real=True)
    assert [r['expression'] for r in built['rows']] == [3*x/5, 13*x/20-9, 9*x/10-sp.Rational(193,2)]
    assert sp.Union(*(r['domain'] for r in built['rows'])) == sp.Interval(0, sp.oo)
    for point, value in [(0,0), (180,108), (350,sp.Rational(437,2)), (400,sp.Rational(527,2))]:
        rows = [r for r in built['rows'] if point in r['domain']]
        assert len(rows) == 1 and rows[0]['expression'].subs(x, point) == value
    assert pm.verify_frozen(c, MODEL, ctx, encode_value(built))['status'] == 'verified'
    assert c == before


@pytest.mark.parametrize(('bill','expected'), [('0',0), ('108',180), ('218.5',350), ('199',320), ('263.5',400), ('0.3',sp.Rational(1,2))])
def test_inverse_preserves_exact_prices_and_endpoint_ownership(bill, expected):
    c=candidate(bill);ctx,v=inverse(c)
    assert v['feasible_set'] == sp.FiniteSet(expected)
    assert pe.independent_verify(c, INVERSE, ctx, v['feasible_set'])['status'] == 'verified'
    assert pe.endpoints(c, INVERSE, v['feasible_set'])['status'] == 'passed'
    if bill == '199':
        assert [r['candidates'] for r in v['branch_results']] == [sp.FiniteSet(sp.Rational(995,3)),sp.FiniteSet(320),sp.FiniteSet(sp.Rational(985,3))]
        assert [r['accepted'] for r in v['branch_results']] == [sp.S.EmptySet,sp.FiniteSet(320),sp.S.EmptySet]
        assert v['description']['source_refs'] == [INVERSE]
        assert all(r['source_ref'] == INVERSE for r in v['description']['sources'])


def test_quantity_name_does_not_collide_with_the_internal_function():
    c=candidate()
    p=c['root']['goals'][0]['pricing'];p['quantity']='g'
    text=pm.statement(p,'199');c['original_text']=text
    for g in c['root']['goals']:g.update(pricing=deepcopy(p),source_text=text)
    c['root']['goals'][1]['symbol']='g'
    ctx,v=inverse(c)
    assert v['feasible_set']==sp.FiniteSet(320)
    assert pe.independent_verify(c,INVERSE,ctx,v['feasible_set'])['status']=='verified'


def test_numeric_variant_and_independent_rejection_of_corrupt_models(monkeypatch):
    c = candidate('178', ['0.5','0.8','1.2']); ctx,v=inverse(c)
    assert v['feasible_set'] == sp.FiniteSet(290)
    mctx=build_context(c,MODEL);built=pm.build(mctx)['outputs']['model_result']
    monkeypatch.setattr(pm,'build',lambda *_: pytest.fail('verifier cannot call solver'))
    assert pm.verify_frozen(c,MODEL,mctx,encode_value(built))['status'] == 'verified'
    for field,bad in [('expression',sp.Rational(4,5)*sp.Symbol('x',real=True)), ('domain',sp.Interval(180,350)),('prior',0)]:
        changed=deepcopy(built);changed['rows'][1][field]=bad
        assert not pm.verify_model(mctx['goal_ast'],changed)
    badrows=deepcopy(v['branch_results']);badrows[0]['accepted']=badrows[0]['candidates']
    assert not pe.verify_rows(v['description'],badrows)
    modified=deepcopy(v['description']);modified['sources'][0]['expression']+=' + 1'
    assert not pe.verify_rows(modified,v['branch_results'])
    assert pe.independent_verify(c, INVERSE, ctx,sp.FiniteSet(320))['status']=='math_failed'


@pytest.mark.parametrize('change', ['whole_quantity','extra_fee','integer_only','price_mismatch','source_mismatch','uncertainty','extra_fact'])
def test_unbound_or_unsupported_billing_is_not_admitted(change):
    c=candidate()
    if change=='price_mismatch': c['root']['goals'][0]['pricing']['rates'][1]='0.66'
    elif change=='source_mismatch': c['original_text']+='另收费用。'
    elif change=='uncertainty': c['root']['uncertainties']=[{'kind':'ambiguous_symbol','text':'单价不清'}]
    elif change=='extra_fact': c['root']['facts']=['x>0']
    else:
        text=c['original_text'].replace('的部分','的全部用量') if change=='whole_quantity' else c['original_text']+('另收服务费10元。' if change=='extra_fee' else '用量取整数。')
        c['original_text']=text
        for g in c['root']['goals']:g['source_text']=text
    assert not pm.inspect_target(c,MODEL)['structure_supported']


def test_two_targets_select_existing_methods_and_keep_separate_reading_goals():
    c=candidate();features=candidate_features(c)
    assert features['ok']
    for ref,method,phrase in [(MODEL,pm.METHOD,'分段关系式'),(INVERSE,pe.METHOD,'用电量')]:
        selected=evaluate_goal(c,ref,[],'type-piecewise-function')
        assert selected['d4']['options'][0]['method']==method
        assert selected['d3']['interaction']['type']=='read' and selected['selection']['rule'] is None
        fragments=build_d1(c,ref,features['features'],{'items':[]})
        assert not fragments['diagnostics']
        reader=d1_rows(ref,fragments['fragments'],{'piecewise_modeling':pm.inspect_target(c,ref)},c['original_text'])
        assert phrase in reader['summary'] and reader['rows']
        quote=reader['rows'][0]['quote'][0]['text']
        assert ('（1）' in quote) == (ref==MODEL)


def test_interaction_schema_actual_arithmetic_and_independent_progress():
    c=candidate();ctx=build_context(c,MODEL);values=pm.build(ctx)['outputs']
    first=compile_step([{'values':encode_value(values)}],'a'*24)['parts']
    _,v=inverse(c)
    second=[p for phase in ('branches','merge') for p in compile_piecewise([{'values':encode_value({**v,'phase':phase})}],'b'*24)['parts']]
    schema=json.loads((ROOT/'internal/schemas/graph-step-interaction-v1.schema.json').read_text())
    validator=Draft202012Validator({'$defs':schema['$defs'],'$ref':'#/$defs/part'})
    for part in first+second:
        validator.validate(part)
        assert '$$' in part['feedback']['answer'] and '=' in part['feedback']['answer']
        if part['interaction']['type']=='choice':
            correct=part['expected_answer']['one_of'][0]
            assert grade(part,{'value':correct},'pricing')=='passed'
            wrong=next(o['value'] for o in part['interaction']['options'] if o['value']!=correct)
            assert grade(part,{'value':wrong},'pricing')!='passed'
    assert {p['id'] for p in first}.isdisjoint(p['id'] for p in second)
    assert 'x-180' in first[2]['question'] and '0.65' in first[2]['question']
    assert r'0.9x-96.5' in json.dumps(first,ensure_ascii=False)
    assert '千瓦时' in second[-1]['completion_board']['items'][1]['math']
    from shuxueshuo_server.graph_lesson.stage_three.execution_contracts import (
        load_contracts,
    )
    assert pm.METHOD in load_contracts()


def test_answer_units_and_original_pricing_participate_in_verification():
    from shuxueshuo_server.graph_lesson.stage_three.goals import (
        GoalClosureMismatch,
        finalize_goal,
        verify_goal_answer,
    )
    c=candidate();ctx,v=inverse(c)
    answer=finalize_goal(ctx['goal'],v['feasible_set'])
    assert answer['quantity']=={'symbol':'x','unit':'千瓦时'}
    verify_goal_answer(ctx['goal'],v['feasible_set'],answer)
    changed=deepcopy(answer);changed['quantity']['unit']='元'
    with pytest.raises(GoalClosureMismatch):verify_goal_answer(ctx['goal'],v['feasible_set'],changed)
    changed=candidate('199',['0.6','0.66','0.9'])
    assert pe.independent_verify(changed,INVERSE,ctx,v['feasible_set'])['status']=='math_failed'
