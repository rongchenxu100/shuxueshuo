"""M9 frozen source and typed completion boundaries."""

from copy import deepcopy
import json
from pathlib import Path

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import evaluation_runtime
from shuxueshuo_server.graph_lesson.stage_three.capabilities import LocalCheckFailed
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value, encode_value

FIXTURES = Path(__file__).parent / 'fixtures/function-evaluation'


def test_frozen_evaluation_binds_original_goal_and_rejects_call_evidence_tampering():
    candidate = json.loads((FIXTURES / 'q28b-candidate.json').read_text())
    ref = '/root/goals/0'
    context = build_context(candidate, ref)
    result = evaluation_runtime.solve_function_evaluation(context)['outputs']['evaluation_result']
    assert evaluation_runtime.verify_frozen(candidate, ref, context, encode_value(result))['status'] == 'verified'
    forged = deepcopy(result)
    forged['calls'][0]['output'] = sp.Integer(999)
    assert evaluation_runtime.verify_frozen(candidate, ref, context, encode_value(forged))['status'] == 'math_failed'
    different_goal = build_context(candidate, '/root/goals/1')
    with pytest.raises(LocalCheckFailed, match='original_context_mismatch'):
        evaluation_runtime.verify_frozen(candidate, ref, different_goal, encode_value(result))


def test_q29b_two_typed_answers_and_completion_remain_separate():
    candidate = json.loads((FIXTURES / 'q29b-candidate.json').read_text())
    answers = []
    for index in range(2):
        context = build_context(candidate, f'/root/goals/{index}')
        result = evaluation_runtime.solve_function_evaluation(context)['outputs']['evaluation_result']
        finished = evaluation_runtime.finish({'evaluation_result_exact': encode_value(result)}, context, [])
        assert finished['consistency'] == 'consistent'
        answers.append(finished['answer'])
    assert answers[0]['kind'] == 'check_constant' and answers[0]['result_type'] == 'constant_check'
    assert answers[0]['is_constant'] is True and answers[0]['value']['expression'] == '3'
    assert answers[1]['kind'] == answers[1]['result_type'] == 'finite_sum'
    assert answers[1]['is_constant'] is None and answers[1]['value']['expression'] == '603/2'
    assert answers[0]['domain'] != answers[1]['domain']


def test_public_skill_outputs_are_consumed_and_original_conditions_survive():
    candidate = json.loads((FIXTURES / 'q28c-candidate.json').read_text())
    prepared = evaluation_runtime.solve_function_evaluation(build_context(candidate, '/root/goals/1'))['outputs']
    desc, raw = prepared['description'], prepared['evaluation_result']
    extracted = evaluation_runtime.extract_evaluation_conditions(desc, raw)
    assert extracted['operations'] == ['domain_denominator_conditions']
    rows = extracted['outputs']
    assert len(rows['conditions']) == 2 and not rows['has_quadratic_conditions']
    restored = evaluation_runtime.resolve_evaluation_domain(desc, rows['conditions'], raw)['outputs']['evaluation_result']
    simplified = evaluation_runtime.simplify_evaluation_expressions(rows['substitutions'], rows['raw_terms'], restored)['outputs']['evaluation_result']
    verified = evaluation_runtime.verify_evaluation_identities(desc, simplified)['outputs']['evaluation_result']
    x = verified['variable']
    assert verified['expression'] == x / (x + 1)
    assert verified['domain'] == sp.S.Reals - sp.FiniteSet(0, -1)
    forged_terms = deepcopy(rows['raw_terms'])
    forged_terms[0]['expression'] = sp.S.One
    forged = evaluation_runtime.simplify_evaluation_expressions(rows['substitutions'], forged_terms, restored)['outputs']['evaluation_result']
    with pytest.raises(LocalCheckFailed, match='substituted_identity_failed'):
        evaluation_runtime.verify_evaluation_identities(desc, forged)


def test_quadratic_skill_checks_complete_forbidden_roots_and_is_guarded():
    from shuxueshuo_server.graph_lesson.function_evaluation import evaluate
    from shuxueshuo_server.graph_lesson.stage_three.execution_contracts import load_contracts

    u, x = ['bound', 'function_argument'], ['ref', 'outer:x', 'scalar']
    call = lambda name, value: ['function_call', ['ref', name, 'function'], value]
    desc = {'kind': 'find_value', 'target_ref': '/root/goals/0', 'variable_ref': 'outer:x', 'variable': 'x',
            'expression_ast': call('g', call('f', x)),
            'functions': [
                {'function_ref': 'f', 'function_name': 'f', 'source_ref': 'def:f',
                 'expression_ast': ['^', u, ['number', '2']]},
                {'function_ref': 'g', 'function_name': 'g', 'source_ref': 'def:g',
                 'expression_ast': ['/', ['number', '1'], ['-', u, ['number', '2']]]}],
            'input_domain_ast': ['real']}
    evaluated = evaluate(desc)
    extracted = evaluation_runtime.extract_evaluation_conditions(desc, evaluated)['outputs']
    assert extracted['has_quadratic_conditions'] is True
    checked = evaluation_runtime.check_evaluation_quadratic_conditions(extracted['quadratic_conditions'], evaluated)
    assert checked['outputs']['root_checks'][0]['roots'] == [-sp.sqrt(2), sp.sqrt(2)]
    assert checked['operations'] == ['quadratic_roots']
    forged = deepcopy(evaluated)
    forged['domain'] = sp.S.Reals
    with pytest.raises(LocalCheckFailed, match='forbidden_root_retained'):
        evaluation_runtime.check_evaluation_quadratic_conditions(extracted['quadratic_conditions'], forged)
    contract = load_contracts()['method-function-evaluation']
    calls = contract['steps'][0]['calls']
    assert {row['public_ref'] for row in calls if row['public_ref']} == {
        'skill-expression-defined', 'skill-simplify', 'skill-equality-transform', 'skill-solve-quadratic'}
    quadratic = next(row for row in calls if row['public_ref'] == 'skill-solve-quadratic')
    assert quadratic['guard'] == {'ref': 'evaluation_has_quadratic_conditions', 'equals': True}


def test_undefined_numeric_input_retains_conditions_without_checkpointing_fake_value():
    from shuxueshuo_server.graph_lesson.function_evaluation import evaluate

    desc = {'kind': 'find_value', 'target_ref': '/root/goals/0', 'variable_ref': '', 'variable': 'x',
            'expression_ast': ['function_call', ['ref', 'f', 'function'], ['number', '0']],
            'functions': [{'function_ref': 'f', 'function_name': 'f', 'source_ref': 'def:f',
                           'expression_ast': ['/', ['number', '1'], ['bound', 'function_argument']]}],
            'input_domain_ast': ['real']}
    evaluated = evaluate(desc)
    extracted = evaluation_runtime.extract_evaluation_conditions(desc, evaluated)['outputs']
    restored = decode_value(encode_value(extracted))
    assert restored['raw_terms'][0]['expression'] is None
    assert restored['substitutions']['target'] is None
    assert restored['conditions'][0]['expression'] == 0
    simplified = evaluation_runtime.simplify_evaluation_expressions(restored['substitutions'], restored['raw_terms'], evaluated)['outputs']['evaluation_result']
    result = evaluation_runtime.verify_evaluation_identities(desc, simplified)['outputs']['evaluation_result']
    assert result['defined'] is False and result['value'] is None and result['domain'] == sp.S.EmptySet


@pytest.mark.parametrize('problem,index,expected', [
    ('q28a', 0, sp.Integer(2)), ('q28a', 1, sp.Rational(1, 3)),
    ('q28b', 0, -sp.Rational(1, 4)), ('q28b', 1, sp.Integer(1)),
    ('q28c', 0, None), ('q28c', 1, None), ('q28d', 0, None),
    ('q29b', 0, sp.Integer(3)), ('q29b', 1, sp.Rational(603, 2)),
])
def test_all_nine_targets_through_skill_pipeline_with_checkpoint_between_calls(problem, index, expected):
    def run(function, *args):
        return decode_value(encode_value(function(*args)['outputs']))

    candidate = json.loads((FIXTURES / f'{problem}-candidate.json').read_text())
    ref = f'/root/goals/{index}'
    context = build_context(candidate, ref)
    prepared = run(evaluation_runtime.solve_function_evaluation, context)
    desc, evaluated = prepared['description'], prepared['evaluation_result']
    extracted = run(evaluation_runtime.extract_evaluation_conditions, desc, evaluated)
    restored = run(evaluation_runtime.resolve_evaluation_domain, desc, extracted['conditions'], evaluated)['evaluation_result']
    if extracted['has_quadratic_conditions']:
        run(evaluation_runtime.check_evaluation_quadratic_conditions, extracted['quadratic_conditions'], restored)
    simplified = run(evaluation_runtime.simplify_evaluation_expressions, extracted['substitutions'], extracted['raw_terms'], restored)['evaluation_result']
    checked = run(evaluation_runtime.verify_evaluation_identities, desc, simplified)['evaluation_result']
    assert evaluation_runtime.verify_frozen(candidate, ref, context, encode_value(checked))['status'] == 'verified'
    if expected is not None:
        assert checked['value'] == expected
    if problem == 'q28c' and index == 1:
        assert checked['domain'] == sp.S.Reals - sp.FiniteSet(0, -1)
    if problem == 'q29b' and index == 1:
        assert (checked['term_count'], checked['pair_count'], checked['leftover_count']) == (201, 100, 1)


def test_compact_sum_certificate_keeps_every_occurrence_and_rejects_tampering():
    candidate = json.loads((FIXTURES / 'q29b-candidate.json').read_text())
    context = build_context(candidate, '/root/goals/1')
    result = evaluation_runtime.solve_function_evaluation(context)['outputs']['evaluation_result']
    assert result['certificate_encoding'] == evaluation_runtime.SUM_CERTIFICATE
    assert len(result['occurrence_certificate']) == 201
    assert len(result['terms']) == 1 and len(result['pairs']) == 100
    assert 'calls' not in result and 'constraints' not in result
    for change in ('value', 'omit', 'pair', 'leftover'):
        altered = deepcopy(result)
        if change == 'value':
            altered['occurrence_certificate'][0][3] += 1
        elif change == 'omit':
            altered['occurrence_certificate'].pop()
        elif change == 'pair':
            altered['pairs'][0]['right_id'] = altered['pairs'][0]['left_id']
        else:
            altered['terms'][0]['value'] += 1
        assert evaluation_runtime.verify_frozen(candidate, '/root/goals/1', context, encode_value(altered))['status'] == 'math_failed'


@pytest.mark.parametrize('domain, inputs, expected, pair_count', [
    (['interval', True, True, ['number', '1'], ['number', '2']], ('1', '2'), 5, 0),
    (['set', ['number', '2'], ['number', '1/2']], ('2', '1/2'), sp.Rational(17, 4), 1),
])
def test_compact_sum_preserves_and_checks_actual_domain_pair_proof(domain, inputs, expected, pair_count):
    desc = {'kind': 'finite_sum', 'target_ref': '/root/goals/0', 'structure_supported': True,
            'functions': [{'function_ref': 'f', 'function_name': 'f', 'source_ref': 'def:f',
                           'expression_ast': ['^', ['bound', 'function_argument'], ['number', '2']],
                           'input_domain_ast': domain, 'explicit_domain': True,
                           'input_domain_source_ref': 'domain:f'}],
            'terms': [{'expression_ast': ['function_call', ['ref', 'f', 'function'], ['number', value]]}
                      for value in inputs]}
    context = {'goal': {'kind': 'finite_sum'}, 'evaluation_goal': desc}
    prepared = evaluation_runtime.solve_function_evaluation(context)['outputs']
    checked = decode_value(encode_value(prepared['evaluation_result']))
    assert checked['total'] == expected and checked['pair_count'] == pair_count
    assert evaluation_runtime._verify_evaluation(desc, checked)
    assert evaluation_runtime.verify_evaluation_identities(desc, checked)['checks'][0]['passed']
    altered = deepcopy(checked)
    altered['pairing']['proof']['inputs'].pop()
    assert not evaluation_runtime._verify_evaluation(desc, altered)
