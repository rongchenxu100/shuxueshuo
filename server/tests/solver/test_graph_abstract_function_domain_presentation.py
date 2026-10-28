"""Student premises, equivalent choices and target-variable boundary contracts."""

from copy import deepcopy

import pytest
import sympy as sp
from jsonschema import ValidationError

from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_three import driver, interaction
from shuxueshuo_server.graph_lesson.stage_three.abstract_domain_presentation import (
    presentation,
)
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value
from shuxueshuo_server.graph_lesson.stage_three.verification import endpoint_check
from tests.solver.test_graph_abstract_function_domain_q25 import TARGET, candidate
from tests.solver.test_graph_stage_three_methods import finish


def execute(**goal_changes):
    value = candidate()
    value['root']['goals'][0].update(goal_changes)
    context = build_context(value, TARGET)
    state = finish(driver.create_state(
        features=extract_features(value)['features'], context=context,
        method='method-input-domain-correspondence', route_id='abstract-function-domain',
        branch='direct', target_ref=TARGET, run_id='abstract-ui', lesson_version='test',
    ))
    assert state['status'] == 'method_complete', state.get('diagnostics')
    return value, state


def parts(state):
    chunks, pending = interaction.compile_route(state['interaction_seeds'], interaction.load_registry())
    assert not pending
    for chunk, _ in chunks:
        interaction.validate_chunk(chunk)
    return [part for chunk, _ in chunks for part in chunk['parts']]


def test_q25_three_cards_follow_input_range_then_input_then_domain():
    _, state = execute()
    align, condition, conclusion = parts(state)
    assert align['title'] == '求 f 的输入范围'
    assert condition['title'] == '列出目标函数的输入条件'
    assert conclusion['title'] == '求目标函数的定义域'
    assert 'f(2\\cdot x-1)' in conclusion['question']
    for card, fragment in zip((align, condition, conclusion), state['fragments'], strict=True):
        board = card['stem_board']
        assert board['layout'] == 'derivation'
        assert board['connector'] == '⇒'
        assert len(board['items']) == 2
        assert isinstance(board['items'][0]['math'], str)
        assert board['items'][1]['math'] is None
        assert 'lines' not in board
        completed_board = fragment['highlight']
        assert completed_board['items'][1]['math']
        pending_again = deepcopy(completed_board)
        pending_again['items'][1]['math'] = None
        assert pending_again == board
        assert not any(term in str(card) + str(fragment) for term in ('对照板', '双轨', '目标式'))
    assert align['stem_board']['items'][0]['label'] == '$f(x)$ 的定义域'
    assert align['stem_board']['items'][1]['label'] == '$f$ 的输入范围'
    assert '目标函数 $f(2' in condition['stem_board']['items'][0]['note']
    assert condition['stem_board']['items'][1]['label'] == '完整输入须满足'
    assert conclusion['stem_board']['items'][0]['label'] == '输入条件'
    assert r'\frac{3}{2}' not in str(conclusion['stem_board'])
    assert '完整输入是 $2\\cdot x-1$' in condition['interaction']['options'][0]['label']
    completed = presentation(decode_value(state['interaction_seeds'][-1]['values']))
    assert r'\frac{3}{2}' in completed['derivation_right_math']
    assert len(conclusion['interaction']['options']) >= 2


@pytest.mark.parametrize(('known', 'target'), [
    ('[-1,1]', 'f(x)'),
    ('[-1,1]', 'f(-x)'),
    ('[-1,1]', 'f(0)'),
    ('[-1,1]', 'f(2)'),
    ('ℝ', 'f(2*x-1)'),
    ('[1,1]', 'f(x)'),
])
def test_all_admitted_shapes_have_unique_correct_choices(known, target):
    _, state = execute(known_domain=known, target_call=target)
    cards = parts(state)
    result = decode_value(state['result'])
    assert len(cards) == 3
    assert '函数值范围' in cards[0]['interaction']['options'][0]['label']
    assert r'\notin' in cards[1]['interaction']['options'][2]['label']
    for part in cards:
        assert '\\' not in part['title']
        options = part['interaction']['options']
        assert len({option['label'] for option in options}) == len(options)
        assert len(part['expected_answer']['one_of']) == 1
    final = cards[-1]
    correct = next(option for option in final['interaction']['options']
                   if option['value'] in final['expected_answer']['one_of'])
    assert [option['label'] for option in final['interaction']['options']].count(correct['label']) == 1
    if result['candidate_set'] == decode_value(state['interaction_seeds'][-1]['values'])['input_range']:
        assert '集合恰好相同' in final['feedback']['answer']
        assert '不是本题最终答案' not in final['feedback']['answer']
    condition = cards[1]
    if target == 'f(x)':
        assert '函数值' in condition['interaction']['options'][1]['label']
        assert '完整输入是 $x$' in condition['interaction']['options'][0]['label']


def test_alignment_names_the_target_expression_not_jargon():
    _, state = execute(known_call='f(t)', target_call='f(2*x-1)')
    align, condition, _ = parts(state)
    assert 'f(t)' in align['question']
    assert '$t$ 的范围' in align['interaction']['options'][1]['label']
    assert '函数值范围' in align['interaction']['options'][0]['label']
    assert '所求' not in align['interaction']['options'][0]['label']
    assert '本式' not in str(align['stem_board'])
    assert align['stem_board']['items'][0]['label'] == '$f(t)$ 的定义域'
    assert align['stem_board']['items'][1]['label'] == '$f$ 的输入范围'
    assert 'f(2' not in str(align['stem_board'])
    assert 'f(2\\cdot x-1)' in condition['stem_board']['items'][0]['note']
    assert '2\\cdot x-1' in condition['interaction']['options'][0]['label']


def test_outer_domain_is_a_premise_only_when_needed():
    _, state = execute(input_domain='(0,2)')
    align, condition, conclusion = parts(state)
    assert 'note' not in align['stem_board']['items'][0]
    assert condition['stem_board']['items'][0]['note'].startswith('目标函数 ')
    assert conclusion['stem_board']['items'][0]['note'] == r'题设另限 $x\in \left(0, 2\right)$'
    assert conclusion['stem_board']['items'][1]['math'] is None
    assert state['fragments'][-1]['highlight']['items'][0] == conclusion['stem_board']['items'][0]


@pytest.mark.parametrize('change', ['missing_premise', 'answer_leak', 'extra_item', 'wrong_connector'])
def test_pending_derivation_schema_rejects_missing_premises_and_visible_answers(change):
    _, state = execute()
    chunks, _ = interaction.compile_route(state['interaction_seeds'], interaction.load_registry())
    chunk = deepcopy(chunks[0][0])
    board = chunk['parts'][0]['stem_board']
    if change == 'missing_premise':
        board['items'][0]['math'] = None
    elif change == 'answer_leak':
        board['items'][1]['math'] = '[-3,2]'
    elif change == 'extra_item':
        board['items'].append(deepcopy(board['items'][1]))
    else:
        board['connector'] = '='
    with pytest.raises(ValidationError):
        interaction.validate_chunk(chunk)


@pytest.mark.parametrize(('known_call', 'target_call', 'symbol'), [
    ('f(x)', 'f(2*x-1)', 'x'),
    ('f(x)', 'f(2*t-1)', 't'),
])
def test_boundary_card_uses_the_target_outer_variable(known_call, target_call, symbol):
    value, state = execute(known_call=known_call, target_call=target_call)
    answer = decode_value(state['result'])['candidate_set']
    evidence = endpoint_check(value, TARGET, answer)
    original = deepcopy(evidence)
    finished = driver.append_endpoint(state, answer, evidence)
    assert evidence == original
    boundary = parts(finished)[-1]
    assert boundary['title'] == '复核边界'
    labels = [slot['label'] for slot in boundary['interaction']['slots']]
    assert len(labels) == 2
    assert all(label.startswith(f'${symbol}=') for label in labels)
    assert 'None' not in str(boundary)
    assert decode_value(finished['interaction_seeds'][-1]['values'])['boundary_variable'] == sp.Symbol(symbol, real=True)
    assert 'function-concept#composite-domain' in finished['fragments'][-1]['used_basis']
