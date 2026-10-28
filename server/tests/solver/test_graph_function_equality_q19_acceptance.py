"""Q19 integration plus frozen independent structural acceptance inputs."""

import json
from hashlib import sha256
from pathlib import Path

import pytest

from shuxueshuo_server.graph_lesson.function_equality import compare_pair, verify_pair
from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_three import driver, interaction
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.equality_runtime import answer_for, original_choice, verify_result
from shuxueshuo_server.graph_lesson.stage_three.handoff import validate_original_choice
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value
from tests.solver.test_graph_function_equality_math import descriptor
from tests.solver.test_graph_stage_three_methods import finish

FIXTURES = Path(__file__).parent / 'fixtures/function-equality'
FROZEN = FIXTURES / 'q19-heldout-frozen.json'
HELDOUT = json.loads(FROZEN.read_text())
TARGET = '/root/goals/0'


def execute(candidate):
    context = build_context(candidate, TARGET)
    state = finish(driver.create_state(
        features=extract_features(candidate)['features'], context=context,
        method='method-function-equality', route_id='function-equality', branch='direct',
        target_ref=TARGET, run_id='q19-acceptance', lesson_version='test'))
    assert state['status'] == 'method_complete', state['diagnostics']
    result = decode_value(state['result'])['comparison_result']
    assert verify_result(context, result)['status'] == 'verified'
    return context, state, result


def test_q19_shared_baseline_full_execution_and_two_layer_interaction():
    candidate = json.loads((FIXTURES / 'q19-candidate.json').read_text())
    context, state, result = execute(candidate)
    assert result['correct_labels'] == ['A', 'B', 'C']
    assert [row['result']['relation'] for row in result['options']] == ['equal'] * 3 + ['different']
    assert result['options'][3]['result']['reason'] == 'domains_differ'
    assert result['options'][3]['result']['counterexample']['point'] == -1
    borrowed = [call for step in state['trajectory']['steps'] for call in step['calls']
                if call['capability'] == 'submethod']
    assert len(borrowed) == 8
    assert all(call['public_ref'] == 'method-domain-intersection' for call in borrowed)
    assert not any(step['case_path'] for step in state['trajectory']['steps'])
    assert not any(step['method_ref'].startswith('method-domain-intersection#') for step in state['fragments'])
    chunks, pending = interaction.compile_route(state['interaction_seeds'], interaction.load_registry())
    assert not pending
    assert len(chunks) == 8
    for chunk, _ in chunks:
        interaction.validate_chunk(chunk)
    parts = [part for chunk, _ in chunks for part in chunk['parts']]
    assert len(parts) == 11
    domains = [part for part in parts if part['interaction']['type'] == 'checklist']
    assert len(domains) == 4
    for part in domains:
        label = part['option_context']['label']
        assert [slot['label'] for slot in part['interaction']['slots']] == ['题干函数', f'选项 {label} 的函数']
        assert '题干函数的解析式' in part['question']
        assert 'f(x)' not in part['question']
    verdicts = [part for part in parts if part['option_context']['phase'] == 'verdict']
    assert [part['option_context']['label'] for part in verdicts] == list('ABCD')
    assert all(part['interaction']['type'] == 'choice' for part in verdicts)
    proofs = {part['option_context']['label']: part['feedback']['answer'] for part in parts
              if part['interaction'].get('field') == 'correspondence'}
    assert set(proofs) == set('ABC')
    assert all('>0' in value and '这些范围覆盖整个共同定义域' in value for value in proofs.values())
    assert r'\sqrt' in proofs['B'] and r'\left|' in proofs['B']
    assert '化简不能补回' in verdicts[-1]['feedback']['answer']
    choice = original_choice(context, answer_for(result))
    validate_original_choice(choice, TARGET)
    assert choice['correct_labels'] == ['A', 'B', 'C']
    assert all(option['text'].startswith('$y=') for option in choice['options'])


def test_heldout_inputs_are_frozen_before_implementation_evaluation():
    assert sha256(FROZEN.read_bytes()).hexdigest() == 'f382dde69f335e5dfdc6aa1edb04fe2046b10a107fcc70a0b97fbbad21b1f383'


@pytest.mark.parametrize('case', HELDOUT['pairs'], ids=lambda case: case['id'])
def test_independent_heldout_pairs(case):
    domain = case.get('domain')
    domain_text = None
    if domain and domain.get('base') == 'real':
        domain_text = 'ℝ∖{' + ','.join(str(point) for point in domain['excluded']) + '}'
    elif domain:
        domain_text = '(-∞,3/2]'
    left, right = (descriptor(case[side], domain=domain_text, function_ref='heldout:' + side)
                   for side in ('left', 'right'))
    result = compare_pair(left, right)
    assert result['relation'] == case['expected'], result
    assert verify_pair(left, right, result)['status'] == 'verified'


@pytest.mark.parametrize('question', HELDOUT['questions'], ids=lambda question: question['id'])
def test_independent_heldout_complete_multiple_questions(question):
    shared = question['mode'] == 'shared_baseline'
    goal = {'kind': 'compare_functions', 'mode': question['mode'],
            'select_relation': question['select_relation'], 'selection_mode': 'multiple',
            'completeness': 'complete', 'shared_functions': [], 'options': []}
    if shared:
        goal['shared_functions'] = [{'id': 'base', 'definition': 'f(x)=' + question['baseline']}]
    for option in question['options']:
        variable = option.get('left_variable', 'x')
        functions = [{'id': 'rhs', 'definition': 'g(x)=' + option['right']}]
        if not shared:
            functions.insert(0, {'id': 'lhs', 'definition': f'f({variable})=' + option['left']})
        goal['options'].append({'id': option['label'], 'label': option['label'],
                                'text': option['right'], 'functions': functions,
                                'left': 'shared:base' if shared else 'local:lhs', 'right': 'local:rhs'})
    _, _, result = execute({'original_text': '独立结构留出验收', 'root': {'goals': [goal]}})
    assert result['correct_labels'] == question['expected_labels']
