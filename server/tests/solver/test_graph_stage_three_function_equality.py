"""Shared M8 execution, option isolation and typed goal closure."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_three import (
    capabilities,
    driver,
    interaction,
    runner,
)
from shuxueshuo_server.graph_lesson.stage_three.calculations import _advance_visible
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.equality_runtime import (
    answer_for,
    original_choice,
    verify_result,
)
from shuxueshuo_server.graph_lesson.stage_three.execution_contracts import (
    load_contracts,
)
from shuxueshuo_server.graph_lesson.stage_three.handoff import validate_original_choice
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value
from tests.solver.test_graph_stage_three_execution import constructed_upstream, store
from tests.solver.test_graph_stage_three_methods import finish
from tools.export_graph_walk_course import export_course

TARGET = '/root/goals/0'
FIXTURE = Path(__file__).parent / 'fixtures/function-equality/q20-candidate.json'


@pytest.fixture(scope='module')
def executed():
    candidate = json.loads(FIXTURE.read_text())
    context = build_context(candidate, TARGET)
    state = finish(driver.create_state(
        features=extract_features(candidate)['features'], context=context,
        method='method-function-equality', route_id='function-equality', branch='direct',
        target_ref=TARGET, run_id='equality-test', lesson_version='test'))
    assert state['status'] == 'method_complete', state['diagnostics']
    return candidate, context, state


def test_each_option_keeps_its_m1_calls_and_finishes_with_a_choice(executed):
    _, context, state = executed
    result = decode_value(state['result'])['comparison_result']
    assert result['correct_labels'] == ['C', 'D']
    assert verify_result(context, result)['status'] == 'verified'
    assert [row['result']['relation'] for row in result['options']] == ['different', 'different', 'equal', 'equal']
    trace = state['trajectory']['steps']
    borrowed = [call for step in trace for call in step['calls'] if call['capability'] == 'submethod']
    assert len(borrowed) == 8
    assert all(call['public_ref'] == 'method-domain-intersection' for call in borrowed)
    assert all(not step['case_path'] for step in trace)
    registry = interaction.load_registry()
    chunks, pending = interaction.compile_route(state['interaction_seeds'], registry)
    assert not pending
    assert all(chunk['status'] == 'interactive' for chunk, _ in chunks)
    for chunk, _ in chunks:
        interaction.validate_chunk(chunk)
    parts = [part for chunk, _ in chunks for part in chunk['parts']]
    assert {part['option_context']['label'] for part in parts} == {'A', 'B', 'C', 'D'}
    verdicts = [part for part in parts if part['option_context']['phase'] == 'verdict']
    assert [part['expected_answer'] for part in verdicts] == [
        {'one_of': [relation]} for relation in ['different', 'different', 'equal', 'equal']]
    assert all(part['interaction']['type'] == 'choice' for part in verdicts)
    assert not any(part['interaction']['type'] == 'original_choice_exact_set' for part in parts)
    assert all(part['option_context']['target_ref'] == TARGET for part in parts)
    # Light/fold surface: M1 still runs (8 calls above) but never publishes student cards.
    m1 = [step for step in state['fragments'] if step['method_ref'].startswith('method-domain-intersection#')]
    assert m1 == []
    assert {part['option_context']['phase'] for part in verdicts} == {'verdict'}
    assert all(part['interaction']['field'] == 'function_relation' for part in verdicts)
    assert [part['option_context']['label'] for part in verdicts] == ['A', 'B', 'C', 'D']
    # Every option closes on a dedicated verdict; same-domain items merge domain+correspondence.
    closing = {step['option_context']['label']: step['display_unit']
               for step in state['fragments'] if step['option_context']['phase'] == 'verdict'}
    assert closing == {'A': 'equality_verdict', 'B': 'equality_verdict',
                       'C': 'equality_verdict', 'D': 'equality_verdict'}
    verdict_cards = [step for step in state['fragments'] if step['display_unit'] == 'equality_verdict']
    assert [step['highlight']['connector'] for step in verdict_cards] == ['≠', '≠', '=', '=']
    assert all(step['highlight']['caption'] == '本项比较' for step in verdict_cards)
    assert all('=' in step['highlight']['items'][0]['math'] for step in verdict_cards)
    domains = [step for step in state['fragments'] if step['display_unit'] == 'equality_domains']
    assert len(domains) == 4
    assert all(step['option_context']['phase'] == 'evidence' for step in domains)
    assert all(step['highlight']['connector'] for step in domains)
    a_domains = next(step for step in domains if step['option_context']['label'] == 'A')
    assert a_domains['highlight']['connector'] == '≠'
    assert [item['math'] for item in a_domains['highlight']['items']] == [
        r'\mathbb{R}', r'\left[0, \infty\right)']
    domain_parts = [part for part in parts
                    if part['interaction']['type'] == 'checklist']
    assert len(domain_parts) == 4
    assert all('分别选出两边的定义域' in part['question'] for part in domain_parts)
    assert all(r'\mathbb{R}' not in part['question'] for part in domain_parts)
    # Full real line is one teaching token; never offer both R and (-∞, ∞).
    for part in domain_parts:
        for slot in part['interaction']['slots']:
            labels = [option['label'] for option in slot['options']]
            assert sum(r'\mathbb{R}' in label for label in labels) == 1
            assert not any(r'-\infty, \infty' in label or r'-\infty,\infty' in label for label in labels)
    merged = [chunk for chunk, _ in chunks if len(chunk['parts']) == 2]
    assert len(merged) == 3
    assert all(chunk['parts'][0]['interaction']['type'] == 'checklist' for chunk in merged)
    assert all(chunk['parts'][1]['interaction']['field'] == 'correspondence' for chunk in merged)
    correspondence = [step for step in state['fragments'] if step['display_unit'] == 'equality_correspondence']
    by_label = {step['option_context']['label']: step for step in correspondence}
    assert by_label['B']['highlight']['caption'].startswith('输入')
    assert by_label['B']['highlight']['connector'] == '≠'
    assert by_label['B']['highlight']['items'][0]['math'] == '0'
    assert by_label['C']['highlight']['caption'] == '对应关系等价'
    assert by_label['C']['highlight']['connector'] == '='
    assert '- u' not in by_label['C']['highlight']['items'][0]['math']
    assert by_label['D']['highlight']['caption'] == '对应关系等价'
    for step in correspondence:
        assert ('absolute-value-concept#rules' in step['used_basis']) == (step['option_context']['label'] == 'C')
        assert step['option_context']['phase'] == 'evidence'
        assert step['highlight']['conclusion_only'] is True
    assert not any(step['display_unit'] == 'equality_entry' for step in state['fragments'])


def test_correspondence_proof_lives_in_feedback_not_the_stem(executed):
    _, _, state = executed
    chunks, pending = interaction.compile_route(state['interaction_seeds'], interaction.load_registry())
    assert not pending
    parts = {part['option_context']['label']: part
             for chunk, _ in chunks for part in chunk['parts']
             if part['interaction'].get('field') == 'correspondence'}
    assert set(parts) == {'B', 'C', 'D'}
    assert all('对应关系是否等价' in parts[label]['question'] for label in parts)
    assert '用 $u$ 表示共同定义域内的同一个输入。' in parts['C']['feedback']['answer']
    assert '将两边的自变量 $x$、$t$ 统一记为 $u$' in parts['D']['feedback']['answer']
    assert all(parts[label]['feedback']['answer'].index('同一个输入')
               < parts[label]['feedback']['answer'].index('当 $u') for label in ('C', 'D'))


@pytest.mark.parametrize('mutation', ['polarity', 'missing', 'swap', 'proof', 'labels'])
def test_final_verification_rejects_incomplete_or_misbound_results(executed, mutation):
    _, context, state = executed
    result = decode_value(state['result'])['comparison_result']
    if mutation == 'polarity':
        result['select_relation'] = 'different'
    elif mutation == 'missing':
        result['options'].pop()
    elif mutation == 'swap':
        result['options'][0], result['options'][1] = result['options'][1], result['options'][0]
    elif mutation == 'proof':
        result['options'][2]['result']['proof']['cells'].pop()
    else:
        result['correct_labels'].append('A')
    assert verify_result(context, result)['status'] == 'math_failed'


def test_original_choice_requires_complete_verdicts_and_exact_polarity(executed):
    _, context, state = executed
    result = decode_value(state['result'])['comparison_result']
    choice = original_choice(context, answer_for(result))
    validate_original_choice(choice, TARGET)
    assert choice['kind'] == 'multiple_choice'
    assert choice['correct_labels'] == ['C', 'D']
    for field, value in [('correct_labels', ['A', 'C', 'D']), ('option_verdicts', choice['option_verdicts'][:-1]),
                         ('select_relation', 'different'), ('target_ref', '/root/goals/9')]:
        bad = deepcopy(choice)
        bad[field] = value
        with pytest.raises(ValueError, match='invalid_original_choice'):
            validate_original_choice(bad, TARGET)
    empty = deepcopy(choice)
    for row in empty['option_verdicts']:
        row['verdict'] = 'different'
    empty['correct_labels'] = []
    validate_original_choice(empty, TARGET)


def test_different_polarity_is_derived_from_verified_relations(executed):
    _, context, state = executed
    context = deepcopy(context)
    context['comparison_goal']['select_relation'] = 'different'
    result = decode_value(state['result'])['comparison_result']
    result['select_relation'] = 'different'
    result['correct_labels'] = ['A', 'B']
    assert verify_result(context, result)['status'] == 'verified'
    choice = original_choice(context, answer_for(result))
    validate_original_choice(choice, TARGET)
    assert choice['correct_labels'] == ['A', 'B']


def test_singleton_declared_domain_is_not_replaced_by_natural_domain():
    candidate = json.loads(FIXTURE.read_text())
    goal = candidate['root']['goals'][0]
    goal.update(mode='pair', select_relation=None, selection_mode='none')
    goal['options'] = [goal['options'][1]]
    goal['options'][0]['functions'] = [
        {'id': 'f', 'definition': 'f(x)=x', 'domain': '[0,0]'},
        {'id': 'g', 'definition': 'g(x)=x^2', 'domain': '{0}'},
    ]
    context = build_context(candidate, TARGET)
    state = finish(driver.create_state(
        features=extract_features(candidate)['features'], context=context,
        method='method-function-equality', route_id='function-equality', branch='direct',
        target_ref=TARGET, run_id='single-point', lesson_version='test'))
    assert state['status'] == 'method_complete', state['diagnostics']
    result = decode_value(state['result'])['comparison_result']
    assert verify_result(context, result)['status'] == 'verified'
    assert result['options'][0]['result']['relation'] == 'equal'
    assert original_choice(context, answer_for(result)) is None


def test_folded_domain_batches_keep_every_call_and_visible_boundary(executed):
    candidate, context, ordinary = executed
    contracts = load_contracts()
    state = driver.create_state(
        features=extract_features(candidate)['features'], context=context,
        method='method-function-equality', route_id='function-equality', branch='direct',
        target_ref=TARGET, run_id='equality-test', lesson_version='test', contracts=contracts)
    calls = 0
    while state['status'] == 'running':
        before = len(state['fragments'])
        state = _advance_visible(state, contracts)
        calls += 1
        # A batch never crosses two display actions or leaks into another option.
        added = state['fragments'][before:]
        assert len({step['option_context']['option_id'] for step in added}) <= 1
        assert calls < 60
    assert state['result'] == ordinary['result']
    assert state['trajectory']['steps'] == ordinary['trajectory']['steps']
    assert state['fragments'] == ordinary['fragments']


def test_folded_domain_failure_stops_in_the_current_option(executed, monkeypatch):
    candidate, context, _ = executed
    contracts = load_contracts()
    state = driver.create_state(
        features=extract_features(candidate)['features'], context=context,
        method='method-function-equality', route_id='function-equality', branch='direct',
        target_ref=TARGET, run_id='failure', lesson_version='test', contracts=contracts)

    def fail(**inputs):
        raise capabilities.LocalCheckFailed('test.folded_domain_invalid')

    monkeypatch.setitem(capabilities.REGISTRY, 'extract_domain_conditions', fail)
    for _ in range(10):
        state = _advance_visible(state, contracts)
        if state['status'] != 'running':
            break
    assert state['status'] == 'math_failed'
    assert state['diagnostics'][-1]['code'] == 'test.folded_domain_invalid'
    # Domain cards publish only after both M1 certificates; a borrow failure can
    # stop with no teaching card yet, but must not leak into later options.
    assert {step['option_context']['label'] for step in state['fragments']} <= {'A'}
    assert all(step['option_context']['phase'] != 'verdict' for step in state['fragments'])


def test_shared_runner_publishes_typed_completion_and_resume(executed, tmp_path):
    candidate, _, _ = executed
    source = constructed_upstream(tmp_path, candidate)
    output = tmp_path / 'run'
    result = runner.run_sample(source, output)
    assert result['status'] == 'completed', result
    goal = result['goals'][0]
    assert goal['status'] == 'solved', goal
    assert goal['answer']['kind'] == 'compare_functions'
    assert goal['answer']['correct_labels'] == ['C', 'D']
    assert goal['feasible_set'] is None
    snapshot = store(output).snapshot()
    handoff, = snapshot['handoffs']
    assert handoff['original_choice']['correct_labels'] == ['C', 'D']
    assert handoff['feasible_set'] is None
    assert len([step for step in snapshot['math_steps'] if step['option_context']['phase'] == 'verdict']) == 4
    saved = deepcopy(snapshot)
    rerun = runner.resume_sample(output)
    assert rerun['goals'][0]['status'] == 'solved'
    assert store(output).snapshot()['handoffs'] == saved['handoffs']
    evidence = export_course(output, 'function-concepts-q20')
    assert evidence['lesson']['goals'][0]['primary'] == 'type-function-equality'
    assert evidence['stream']['handoffs'][0]['original_choice']['correct_labels'] == ['C', 'D']
