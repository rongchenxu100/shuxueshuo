"""Q25 IR, recognition, M2 execution and step-local derivation interaction."""

import json
from pathlib import Path

import sympy as sp

from shuxueshuo_server.graph_lesson.stage_one import contracts
from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_three import driver, interaction
from shuxueshuo_server.graph_lesson.stage_three.abstract_function_domain import (
    independent_verify,
)
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.selection import evaluate_goal
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value
from shuxueshuo_server.graph_lesson.stage_two.recognition import evaluate_types
from shuxueshuo_server.problem_understanding.notation_compile import NotationValidator
from tests.solver.test_graph_stage_three_methods import finish

FIXTURES = Path(__file__).parent / 'fixtures/abstract-function-domain'
TARGET = '/root/goals/0'


def candidate():
    return json.loads((FIXTURES / 'q25-candidate.json').read_text())


def test_q25_compiles_and_features_support_structure():
    value = candidate()
    report = NotationValidator().validate_root(value['root'], contracts.schema()['$defs'])
    assert report.ok, report.issues
    goal = report.semantic['goals'][0]
    assert goal['kind'] == 'find_abstract_domain'
    assert goal['strength'] == 'exact'
    features = extract_features(value)['features']
    indexed = {row['feature_id']: row for row in features if row['target_ref'] == TARGET}
    assert indexed['goal']['value']['kind'] == 'find_abstract_domain'
    assert indexed['abstract_function_domain']['value']['structure_supported'] is True
    assert indexed['abstract_function_domain']['value']['known_form'] == 'identity'
    assert indexed['abstract_function_domain']['value']['target_slope'] == '2'
    assert indexed['abstract_function_domain']['value']['target_intercept'] == '-1'


def test_q25_recognition_selects_abstract_type():
    value = candidate()
    features = extract_features(value)['features']
    reports = evaluate_types(features)
    assert reports[0]['type_id'] == 'type-abstract-function-domain'
    assert reports[0]['status'] == 'supported'


def test_q25_selection_admits_m2():
    value = candidate()
    features = extract_features(value)['features']
    result = evaluate_goal(value, TARGET, features, 'type-abstract-function-domain')
    assert result['d3'] is not None
    assert result['d4']['options'][0]['method'] == 'method-input-domain-correspondence'
    assert '输入范围' in result['d3']['question']


def test_q25_full_execution_and_step_derivation_interaction():
    value = candidate()
    context = build_context(value, TARGET)
    assert context['abstract_domain_goal']['structure_supported'] is True
    state = finish(driver.create_state(
        features=extract_features(value)['features'], context=context,
        method='method-input-domain-correspondence', route_id='abstract-function-domain',
        branch='direct', target_ref=TARGET, run_id='q25-acceptance', lesson_version='test',
    ))
    assert state['status'] == 'method_complete', state.get('diagnostics')
    result = decode_value(state['result'])
    answer = result['candidate_set']
    assert answer == sp.Interval(-1, sp.Rational(3, 2))
    verified = independent_verify(value, TARGET, answer)
    assert verified['status'] == 'verified'
    chunks, pending = interaction.compile_route(state['interaction_seeds'], interaction.load_registry())
    assert not pending
    assert len(chunks) == 3
    for chunk, _ in chunks:
        interaction.validate_chunk(chunk)
    parts = [part for chunk, _ in chunks for part in chunk['parts']]
    assert len(parts) == 3
    assert [part['title'] for part in parts] == [
        '求 f 的输入范围',
        '列出目标函数的输入条件',
        '求目标函数的定义域',
    ]
    for part in parts:
        assert part['interaction']['type'] == 'choice'
        assert part['stem_board']['layout'] == 'derivation'
        assert len(part['stem_board']['items']) == 2
        assert part['stem_board']['items'][1]['math'] is None
    assert parts[0]['expected_answer']['one_of'] == ['o2']
    assert parts[1]['expected_answer']['one_of'] == ['o1']
    assert parts[2]['expected_answer']['one_of'] == ['o1']
    assert '上轨' not in parts[0]['interaction']['options'][0]['label']
    assert '下轨' not in parts[0]['interaction']['options'][1]['label']
    assert '本式' not in str(parts[0]['stem_board'])
    assert '所求' not in parts[0]['interaction']['options'][0]['label']
    assert parts[0]['stem_board']['items'][0]['label'] == '$f(x)$ 的定义域'
    assert '输入范围' in parts[0]['interaction']['options'][1]['label']
    assert '函数值范围' in parts[0]['interaction']['options'][0]['label']
    assert '一回事' in parts[0]['feedback']['answer']
    assert '完整输入是 $2\\cdot x-1$' in parts[1]['interaction']['options'][0]['label']
    assert '不是本题最终答案' in parts[2]['feedback']['answer']
    assert '本式' not in parts[2]['title']
