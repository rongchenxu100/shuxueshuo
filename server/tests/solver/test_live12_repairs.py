"""Recorded q30 failures: contextual facts, bound transport, closure phrases."""
import json
import re
from dataclasses import replace
from pathlib import Path
import pytest
from shuxueshuo_server.solver.math_kernel.inequality_evidence import verify_bound, public_bound, close_bound
from shuxueshuo_server.solver.math_kernel.bound_chain import replay_bound
from shuxueshuo_server.solver.math_kernel.proof_algebra import ProofFailure
from shuxueshuo_server.solver.math_kernel.expression_parser import MathParseError
from shuxueshuo_server.solver.runtime.functional_plan_reconciliation import _bind_original_expression_conditions
from shuxueshuo_server.solver.runtime.functional_plan_elaboration import FunctionalSemanticIndex, FunctionalSemanticView
from shuxueshuo_server.solver.runtime.functional_plan_models import FunctionalPlan, FunctionalScope, FunctionalCall
from shuxueshuo_server.solver.runtime.strategy_models import SemanticRef
from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
from tools.run_basic_inequality_stage4a import run
FIXTURES = Path(__file__).parent / 'fixtures'


def target(expression, conditions, symbols):
    return {'type': 'extremum_target', 'goal_kind': 'find_minimum', 'scope_id': 'problem',
            'scalar_symbols': symbols, 'target_math': expression,
            'source_conditions': [{'handle': f'c{i}', 'source_path': f'/facts/{i}', 'math': c}
                                  for i, c in enumerate(conditions)]}


@pytest.mark.parametrize('attempt', ['2', '3'])
@pytest.mark.parametrize('rename', [False, True])
def test_live12_local_bound_lifts_over_extra_parameters(attempt, rename):
    steps = json.loads((FIXTURES/'basic-inequality-stage5c/live12-budget.json').read_text())[attempt]
    f = '2*a^2+1/(a*b)+1/(a*(a-b))-10*a*c+25*c^2'
    expression = '2*a^2+1/(b*(a-b))-10*a*c+25*c^2'
    conditions = ['a>b', 'b>c', 'c>0']
    symbols = ['a', 'b', 'c']
    if rename:
        mapping = dict(zip('abc', 'xyz'))
        convert = lambda s: re.sub(r'\b[abc]\b', lambda m: mapping[m[0]], s)
        steps = [{'math': convert(r['math'])} for r in steps]
        f, expression = convert(f), convert(expression)
        conditions = [convert(s) for s in conditions]
        symbols = list('xyz')
    t = target(f, conditions, symbols)
    bound = public_bound(verify_bound(t, steps, expression=expression))
    assert replay_bound(t, bound)['bound'] == bound['bound']
    bad = [*steps[:-1], {'math': f'{expression}>=4/{symbols[0]}^2'}]
    with pytest.raises(ProofFailure):
        verify_bound(t, bad, expression=expression)


@pytest.fixture
def simple_bound():
    t = target('x+4/x', ['x>0', 'x<3'], ['x'])
    return t, public_bound(verify_bound(t, [{'math': 'x+4/x>=4'}]))


@pytest.mark.parametrize('phrase', ['∴ 最小值为 4', '∵ x>0；∴ 满足原条件',
                                   '∴ 满足原条件；∴ 最小值为 4'])
def test_closure_statement_expands_verified_obligations(simple_bound, phrase):
    t, bound = simple_bound
    value, evidence = close_bound(t, bound, [{'math': 'x=2'}, {'math': phrase}])
    assert value == 4
    origins = evidence['derivation_origins']
    assert any('statement_reference' in r for r in origins)
    assert all(r['source'] == phrase for r in origins if 'statement_reference' in r)


@pytest.mark.parametrize('phrase', ['∴ 最小值为 5', '∴ 最大值为 4',
                                   '∵ 最小值为 4', '∴ 不满足原条件',
                                   '∴ 最小值为 4 或 5', '∴ 满足原条件 x<0'])
def test_closure_phrases_cannot_bypass_proof_or_change_meaning(simple_bound, phrase):
    t, bound = simple_bound
    with pytest.raises((ProofFailure, MathParseError)):
        close_bound(t, bound, [{'math': 'x=2'}, {'math': phrase}])


def test_summary_does_not_supply_missing_witness(simple_bound):
    t, bound = simple_bound
    with pytest.raises(ProofFailure, match='explicit constant assignment'):
        close_bound(t, bound, [{'math': '∴ 最小值为 4'}])
    with pytest.raises(ProofFailure):
        close_bound(t, bound, [{'math': 'x=-2'}, {'math': '∴ 满足原条件'}])


def binding_case():
    registry = CanonicalHandleRegistry(frozenset(['problem', 'problem.child']),
                                       frozenset(), frozenset(), frozenset(),
                                       scope_parents={'problem': None, 'problem.child': 'problem'})
    views = [FunctionalSemanticView('f', 'function', 'function:problem:f', 'Expression', 'problem',
                                  object_ref='function:problem:f', authority_scope_id='problem'),
             FunctionalSemanticView('goal', 'fact', 'fact:problem:goal', 'Condition', 'problem',
                                  authority_scope_id='problem'),
             FunctionalSemanticView('positive', 'fact', 'fact:problem:positive', 'Condition', 'problem',
                                  authority_scope_id='problem')]
    payload = {'handle': 'fact:problem:goal', 'type': 'extremum_target',
               'expression_owner': 'function:problem:f',
               'source_conditions': [{'handle': 'fact:problem:positive'}]}
    index = FunctionalSemanticIndex(views, handle_registry=registry,
                                   fact_payloads={payload['handle']: payload}, relation_authority_views=views)
    call = FunctionalCall('rewrite', 'organize_expressions', {'expression': (SemanticRef('f', 'function'),)}, {}, '', '')
    plan = FunctionalPlan((FunctionalScope('problem', '', (call,)),))
    return plan, index


def test_original_conditions_bound_by_owner_not_labels():
    plan, index = binding_case()
    normalized, repairs = _bind_original_expression_conditions(plan, semantic_index=index)
    assert normalized.calls[0].args['conditions'] == (SemanticRef('positive', 'fact'),)
    assert repairs[0].action == 'bind_original_expression_conditions'


@pytest.mark.parametrize('case', ['wrong_owner', 'child_condition', 'child_target', 'not_allowlisted', 'explicit_empty', 'ambiguous'])
def test_original_conditions_cannot_cross_authority(case):
    plan, index = binding_case()
    if case == 'wrong_owner':
        index.fact_payloads['fact:problem:goal']['expression_owner'] = 'function:problem:other'
    elif case in ('child_condition', 'child_target'):
        i = 2 if case == 'child_condition' else 1
        index.views = tuple(replace(v, valid_scope='problem.child') if j == i else v for j, v in enumerate(index.views))
    elif case == 'not_allowlisted':
        index = index.with_call_allowlists({'rewrite': frozenset({('problem', 'f', 'function'), ('problem', 'goal', 'fact')})})
    elif case == 'explicit_empty':
        call = replace(plan.calls[0], args={**plan.calls[0].args, 'conditions': ()})
        plan = replace(plan, scopes=(replace(plan.scopes[0], calls=(call,)),))
    else:
        extra = replace(index.views[1], ref='other', handle='fact:problem:other')
        index.views = (*index.views, extra)
        index.fact_payloads[extra.handle] = {**index.fact_payloads['fact:problem:goal'], 'handle': extra.handle}
    normalized, repairs = _bind_original_expression_conditions(plan, semantic_index=index)
    assert normalized == plan
    assert not repairs


@pytest.mark.parametrize('natural_closure', [False, True])
def test_q30_m01_omitted_conditions_are_runtime_bound(tmp_path, natural_closure):
    p = json.loads((FIXTURES/'basic-inequality-stage5c/q30.json').read_text())
    p['root_scope']['goals'][0]['steps'][0]['args'].pop('conditions')
    if natural_closure:
        p['root_scope']['goals'][0]['steps'][-1]['parameters']['steps'].extend([
            {'math': '∵ a>b>c>0；∴ 满足原条件'}, {'math': '∴ 最小值为 4'},
        ])
    plan = tmp_path/'plan.json'
    plan.write_text(json.dumps(p))
    result, _ = run(gold=FIXTURES/'math-notation-v1/basic-inequality/q30.json',
                    problem_ir=FIXTURES/'basic-inequality-problem-ir/v1/q30/problem-ir.json',
                    plan=plan, mode='recorded', output=tmp_path/'run')
    assert result.status == 'ok', result.to_dict()
    assert result.answers == {'problem': {'minimum': '4'}}
