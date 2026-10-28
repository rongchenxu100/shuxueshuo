"""Common-input parameter cards use the actual method execution contract."""

import json
from pathlib import Path

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_three import driver, interaction
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.route_constraints import (
    apply_visible_constraints,
)
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value
from tests.solver.test_graph_stage_three_methods import finish


def execute(target=None, domain=None):
    candidate = json.loads((Path(__file__).parent / 'fixtures/abstract-function-domain/variant02-candidate.json').read_text())
    goal = candidate['root']['goals'][0]
    if target:
        goal['target_call'] = target
    if domain:
        goal['known_domain'] = domain
    state = finish(driver.create_state(
        features=extract_features(candidate)['features'], context=build_context(candidate, '/root/goals/0'),
        method='method-input-domain-correspondence', route_id='abstract-function-domain',
        branch='direct', target_ref='/root/goals/0', run_id='parameter-cards', lesson_version='test',
    ))
    assert state['status'] == 'method_complete', state.get('diagnostics')
    answer = decode_value(state['result'])['candidate_set']
    restricted, evidence = apply_visible_constraints(build_context(candidate, '/root/goals/0'), answer)
    assert restricted == answer
    assert evidence[0]['status'] == 'abstract_domain_parameter_identity'
    chunks, pending = interaction.compile_route(state['interaction_seeds'], interaction.load_registry())
    assert not pending
    for chunk, _ in chunks:
        interaction.validate_chunk(chunk)
    return state, [part for chunk, _ in chunks for part in chunk['parts']]


def test_variant_two_uses_complement_path_with_local_visual_cards():
    state, cards = execute()
    result = decode_value(state['result'])
    assert result['candidate_set'] == sp.Interval(-sp.Rational(1, 2), sp.Rational(1, 2))
    assert result['domain_evidence']['meaning'] == 'guaranteed_parameter_range'
    assert result['domain_evidence']['overlap_strategy']['recommended'] == 'complement'
    assert [row['title'] for row in cards] == [
        '分别列出输入条件', '求各调用允许的范围', '观察范围的公共部分',
        '找出两个区间完全错开的条件', '求交集为空时的参数范围', '取补集，得到参数范围',
    ]
    assert [row['interaction']['type'] for row in cards] == ['choice', 'checklist', 'choice', 'checklist', 'choice', 'choice']
    assert len(cards[1]['interaction']['slots']) == 2
    assert '可以没有共同取值' in cards[2]['interaction']['options'][1]['label']
    assert cards[2]['stem_board']['interval_explorer']['mode'] == 'explore'
    assert cards[3]['stem_board']['interval_explorer']['mode'] == 'separation'
    assert {-0.5, 0.5} <= set(cards[2]['stem_board']['interval_explorer']['critical_values'])
    assert all('<' in slot['options'][0]['label'] for slot in cards[3]['interaction']['slots'])
    for card, completed in zip(cards, state['fragments'], strict=True):
        assert card['stem_board']['items'][1]['math'] is None
        assert card['stem_board']['items'][0] == completed['highlight']['items'][0]
        assert completed['highlight']['items'][1]['math']
        assert card['stem_board'].get('interval_explorer') == completed['highlight'].get('interval_explorer')
        assert '对照板' not in str(card)
    assert r'\frac{1}{2}' not in str(cards[0]) + str(cards[1]) + str(cards[2])


@pytest.mark.parametrize(('target', 'domain', 'answer'), [
    ('f(a)+f(a+1)', '[0,1]', sp.FiniteSet(0)),
    ('f(-2*x+a)+f(x-a)', '(0,1)', sp.Interval.open(-3, 0)),
])
def test_parameter_cards_cover_constant_input_and_negative_slopes(target, domain, answer):
    state, cards = execute(target, domain)
    assert decode_value(state['result'])['candidate_set'] == answer
    strategy = decode_value(state['result'])['domain_evidence']['overlap_strategy']
    assert len(cards) == (6 if strategy['recommended'] == 'complement' else 4)
    for card in cards:
        for slot in card['interaction'].get('slots', []):
            assert len({option['label'] for option in slot['options']}) == len(slot['options'])


def test_fixed_relative_positions_keep_direct_path():
    state, cards = execute('f(x+a)+f(x+a+1)', '[0,2]')
    assert decode_value(state['result'])['domain_evidence']['overlap_strategy']['recommended'] == 'direct'
    assert len(cards) == 4
    assert cards[-1]['title'] == '求参数范围'
    assert not any('补集' in row['title'] for row in cards)


@pytest.mark.parametrize(('target', 'answer'), [
    ('f(x+a)+f(x-a)+f(a)', sp.Interval(0, 1)),
    ('f(x+a)+f(x-a)+f(-1)', sp.S.EmptySet),
])
def test_independent_parameter_limits_are_not_replaced_by_two_interval_overlap(target, answer):
    state, cards = execute(target, '[0,2]')
    result = decode_value(state['result'])
    assert result['candidate_set'] == answer
    assert result['domain_evidence']['overlap_strategy']['constant_guard_conditions']
    assert all('interval_explorer' not in card['stem_board'] for card in cards)
    assert all('interval_explorer' not in fragment['highlight'] for fragment in state['fragments'])
    overlap = cards[2]
    assert '移动参数' not in overlap['question']
    assert '参数限制' in overlap['question']
    correct = next(option for option in overlap['interaction']['options']
                   if option['value'] in overlap['expected_answer']['one_of'])
    assert '参数限制' in correct['label']
    assert '参数限制' in state['fragments'][2]['explanation']


@pytest.mark.parametrize('domain', ['(0,1/100000000000)', '[10000000000,10000000001]', '[0,2/3]'])
def test_exact_explorer_values_survive_pending_and_completed_projection(domain):
    state, cards = execute('f(x+a)+f(x-a)', domain)
    graph = cards[2]['stem_board']['interval_explorer']
    assert graph == state['fragments'][2]['highlight']['interval_explorer']
    assert [float(sp.Rational(value)) for value in graph['critical_exact_values']] == graph['critical_values']
    for row in graph['intervals']:
        for side in ('lower', 'upper'):
            endpoint = row[side]
            assert float(sp.Rational(endpoint['slope_exact'])) == endpoint['slope']
            assert float(sp.Rational(endpoint['intercept_exact'])) == endpoint['intercept']
