"""Frozen full-plan replay and bounded transport of a local inequality."""
import json
from pathlib import Path

import pytest
from test_scoped_proof_search_stage_d import context, prove

from shuxueshuo_server.solver.math_kernel.proof_checker import replay_proof
from tools.run_basic_inequality_stage4a import run


@pytest.mark.parametrize('premises,goal', [
    (['x>=r+u', 'u>=v'], 'x>=r+v'),
    (['r+u<=x', 'v<=u'], 'r+v<=x'),
    (['x>r+u', 'u>=v'], 'x>r+v'),
    (['x>=r+u', 'u>v'], 'x>r+v'),
    (['x>=u-3*r', 'u>=v'], 'x>=v-3*r'),
])
def test_known_bound_transports_an_arbitrary_remainder(premises, goal):
    ctx = context(premises, variables='xruv')
    result = prove(goal, ctx)
    assert result.result.status == 'proved', result.result
    assert replay_proof(result.result.proof, ctx).status == 'proved'
    assert not any('amgm' in n['rule_id'] for n in result.result.proof['nodes'])
    assert result.diagnostics['counts']['arithmetic_operations'] < 3000


@pytest.mark.parametrize('goal', ['x>r+v', 'x>=v', 'x>=r+v+1'])
def test_bound_transport_does_not_drop_remainder_or_strengthen(goal):
    assert prove(goal, context(['x>=r+u', 'u>=v'], variables='xruv')).result.status != 'proved'


def test_original_expression_full_saved_plan_and_response_replay(tmp_path):
    fixtures = Path(__file__).parent / 'fixtures'
    common = {'gold': fixtures/'math-notation-v1/basic-inequality/q30.json',
              'problem_ir': fixtures/'basic-inequality-problem-ir/v1/q30/problem-ir.json',
              'plan': fixtures/'basic-inequality-stage5c/original-expression-plan.json',
              'mode': 'recorded'}
    result, runtime = run(**common, output=tmp_path/'solve')
    assert result.status == 'ok', result.to_dict()
    assert result.answers == {'problem': {'minimum': '4'}}
    assert not (tmp_path/'solve/attempt-2.canonical-plan.json').exists()
    execution = runtime.last_success_artifacts.verified_functional_execution.to_payload()
    for producer, consumer in [('organize','amgm1'), ('amgm1','amgm2'),
                               ('amgm2','quad_bound'), ('quad_bound','close')]:
        assert producer in execution['dependency_graph'][consumer]
    repeated, _ = run(**common, output=tmp_path/'replay', replay_from=tmp_path/'solve')
    assert repeated.status == 'ok'
    assert repeated.answers == result.answers
    plan = json.loads((tmp_path/'solve/attempt-1.canonical-plan.json').read_text())
    assert '原式' in json.dumps(plan, ensure_ascii=False)
