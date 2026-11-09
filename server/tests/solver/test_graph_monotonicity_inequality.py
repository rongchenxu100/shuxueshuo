"""FM-T3 R0: known monotonicity order inequalities."""
import json
from copy import deepcopy
from pathlib import Path

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.function_monotonicity import (
    describe as describe_mono,
)
from shuxueshuo_server.graph_lesson.function_monotonicity import (
    solve as solve_mono,
)
from shuxueshuo_server.graph_lesson.function_monotonicity import (
    verify as verify_mono,
)
from shuxueshuo_server.graph_lesson.monotonicity_inequality_math import (
    basis_from_proof,
    convert_relation,
    describe,
    routed_description,
    solve,
    verify,
)
from shuxueshuo_server.graph_lesson.stage_three.trajectory import (
    decode_value,
    encode_value,
)

ROOT = Path(__file__).resolve().parents[3]
RECORDS = ROOT / 'internal/senior-high/authored-courses/function-monotonicity-t3-20261106'
TARGET = '/root/goals/0'


def source(name):
    record = json.loads((RECORDS / f'{name}.json').read_text())
    candidate = record['candidate']
    entries = [{'source_ref': f'/root/{field}/{i}', 'expression': text}
               for field in ('definitions', 'facts')
               for i, text in enumerate(candidate['root'].get(field, []))]
    return record, describe(candidate['root']['goals'][0], TARGET, entries)


@pytest.mark.parametrize('name,gold', [
    ('b01', sp.Interval.open(0, 1)),
    ('b02', sp.Interval.Lopen(sp.Rational(1, 2), sp.Rational(2, 3))),
    ('b03', sp.Interval.open(sp.Rational(-3, 2), 2)),
    ('b04', sp.Interval.open(-1, 3)),
    ('b05', sp.Interval.Ropen(sp.Rational(1, 2), sp.Rational(2, 3))),
    ('b06', sp.Interval.open(0, sp.Rational(2, 3))),
    ('b13', sp.Interval.Ropen(sp.Rational(1, 2), sp.Rational(2, 3))),
])
def test_r0_gold_and_independent_verification(name, gold, monkeypatch):
    _, d = source(name)
    assert d['structure_supported'], d['reason']
    m = solve(d)
    assert m['feasible_set'] == gold
    monkeypatch.setattr('shuxueshuo_server.graph_lesson.monotonicity_inequality_math.solve',
                        lambda *_: pytest.fail('solver called by verifier'))
    assert verify(d, m)
    assert verify(d, decode_value(encode_value(m)))
    bad = deepcopy(m)
    bad['feasible_set'] = gold ^ sp.FiniteSet(0)
    assert not verify(d, bad)


def test_order_skill_keeps_or_flips_relation():
    assert convert_relation('increasing', '<') == '<'
    assert convert_relation('decreasing', '<') == '>'
    assert convert_relation('decreasing', '>=') == '<='


@pytest.mark.parametrize('fact', ['Dom(f)=(0,+∞)', '(0,+∞)=Dom(f)'])
def test_explicit_domain_fact_covers_known_monotonicity(fact):
    record, d = source('b01')
    goal = deepcopy(record['candidate']['root']['goals'][0])
    goal['function_monotonicity'].pop('function_domain')
    entries = [*d['given_definitions'], {'source_ref': '/root/facts/1', 'expression': fact}]
    desc = describe(goal, TARGET, entries)
    assert desc['structure_supported'], desc['reason']
    result = solve(desc)
    assert result['feasible_set'] == sp.Interval.open(0, 1)
    assert verify(desc, result)
    goal['function_monotonicity']['function_domain'] = 'ℝ'
    assert describe(goal, TARGET, entries)['reason'] == 'mono_ineq.conflicting_function_domain'
    entries[-1]['expression'] = fact.replace('Dom(f)', 'Dom(g)')
    assert not describe(goal, TARGET, entries)['structure_supported']


def test_photo_wording_locates_declared_domain_and_solution_set(tmp_path):
    from shuxueshuo_server.graph_lesson.stage_one.runner import candidate_features
    from shuxueshuo_server.graph_lesson.stage_two.fragments import build_d1

    record, _ = source('b01')
    candidate = record['candidate']
    candidate['original_text'] = ('已知函数 $f(x)$ 的定义域为 $(0,+∞)$，且在定义域内单调递增，'
                                  '则使得不等式 $f(2x)<f(x+1)$ 成立的 $x$ 的取值集合为____。')
    candidate['root']['goals'][0]['function_monotonicity'].pop('function_domain')
    candidate['root']['facts'].append('Dom(f)=(0,+∞)')
    features = candidate_features(candidate)
    assert features['ok'], features.get('diagnostics')
    result = build_d1(candidate, TARGET, features['features'], {'items': []})
    assert not result['diagnostics'], result
    refs = [ref for row in result['fragments'] for ref in row.get('source_refs', [])]
    assert '/root/facts/1' in refs


def test_local_monotonicity_is_not_a_complete_domain():
    record, d = source('b06')
    g = deepcopy(record['candidate']['root']['goals'][0])
    g['function_monotonicity'].pop('function_domain')
    partial = describe(g, TARGET, d['given_definitions'])
    assert not partial['structure_supported']
    assert partial['reason'] == 'mono_ineq.incomplete_domain_coverage'
    with pytest.raises(ValueError, match='incomplete_domain_coverage'):
        solve(partial)
    forged = deepcopy(partial)
    forged['structure_supported'] = True
    assert not verify(forged, solve(d))


def test_goal_range_can_supply_coverage_without_inventing_function_domain():
    record, d = source('b06')
    g = deepcopy(record['candidate']['root']['goals'][0])
    g['function_monotonicity'].pop('function_domain')
    g['input_domain'] = '(0,1/2]'
    restricted = describe(g, TARGET, d['given_definitions'])
    assert restricted['structure_supported'], restricted['reason']
    result = solve(restricted)
    assert result['feasible_set'] == sp.Interval.Lopen(0, sp.Rational(1, 2))
    assert verify(restricted, result)
    g['input_domain'] = '(0,1]'
    assert not describe(g, TARGET, d['given_definitions'])['structure_supported']


def test_exact_domain_must_cover_the_stated_monotonic_interval():
    record, d = source('b06')
    g = deepcopy(record['candidate']['root']['goals'][0])
    g['function_monotonicity']['function_domain'] = '(0,1)'
    assert not describe(g, TARGET, d['given_definitions'])['structure_supported']
    g['function_monotonicity']['function_domain'] = 'ℝ'
    assert not describe(g, TARGET, d['given_definitions'])['structure_supported']


@pytest.mark.parametrize('field,value', [('domain', '(-2,2)'), ('function_domain', 'ℝ'),
                                        ('direction', 'decreasing'), ('basis', 'proved_monotonicity')])
def test_monotonicity_assumptions_survive_semantic_comparison(field, value):
    from shuxueshuo_server.graph_lesson.stage_one import contracts
    from shuxueshuo_server.problem_understanding.notation_compile import (
        NotationValidator,
    )
    from shuxueshuo_server.problem_understanding.notation_semantics import (
        compare_reports,
    )

    record, _ = source('b06')
    before = record['candidate']['root']
    after = deepcopy(before)
    after['goals'][0]['function_monotonicity'][field] = value
    validator = NotationValidator()
    reports = [validator.validate_root(root, contracts.schema()['$defs']) for root in (before, after)]
    assert all(report.ok for report in reports)
    assert not compare_reports(*reports)['ok']


@pytest.mark.parametrize('name,target', [
    ('b01', '/root/goals/0'),
    ('b03', '/root/goals/0'),
    ('b09', '/root/goals/1'),
])
def test_d1_locates_comparison_and_range_ask(name, target):
    from shuxueshuo_server.graph_lesson.stage_one.runner import candidate_features
    from shuxueshuo_server.graph_lesson.stage_two.fragments import build_d1
    from shuxueshuo_server.search.lesson import d1_rows

    record, _ = source(name)
    features = candidate_features(record['candidate'])
    assert features['ok'], features.get('diagnostics')
    fragments = build_d1(record['candidate'], target, features['features'], {'items': []})
    assert not fragments['diagnostics']
    assert any(row['fragment_kind'] == 'goal' for row in fragments['fragments'])
    mono = next(row['value'] for row in features['features']
                if row['feature_id'] == 'monotonicity_inequality' and row['target_ref'] == target)
    rows = d1_rows(target, fragments['fragments'], {'monotonicity_inequality': mono},
                   record['candidate']['original_text'])
    assert rows['interaction'] == 'choice'
    assert rows['rows'] and '严格单调' in rows['summary']


def test_b03_piecewise_proof_feeds_m5_basis():
    prove = {
        'kind': 'prove_monotonicity_on_interval',
        'expression': 'piecewise(2*x-1,x<1,x^2,x>=1)',
        'variable': 'x', 'direction': 'increasing', 'input_domain': 'ℝ',
    }
    mono_desc = describe_mono(prove, TARGET)
    proof = solve_mono(mono_desc, 'piecewise')
    assert verify_mono(mono_desc, proof)
    basis = basis_from_proof(proof)
    assert basis == {
        'function': 'f', 'domain': 'ℝ', 'direction': 'increasing',
        'strict': True, 'basis': 'proved_monotonicity',
    }
    _, inequality = source('b03')
    assert inequality['structure_supported']
    assert inequality['direction'] == basis['direction']
    model = solve(inequality)
    assert model['feasible_set'] == sp.Interval.open(sp.Rational(-3, 2), 2)
    assert verify(inequality, model)


@pytest.mark.parametrize('name,index,gold', [('b03', 0, sp.Interval.open(sp.Rational(-3, 2), 2)),
                                          ('b09', 1, sp.Interval.open(1, 4))])
def test_photographed_piecewise_goal_needs_no_model_invented_proof(name, index, gold):
    from shuxueshuo_server.graph_lesson.stage_one.runner import candidate_features
    from shuxueshuo_server.graph_lesson.stage_three import driver
    from shuxueshuo_server.graph_lesson.stage_three.context import build_context
    from shuxueshuo_server.graph_lesson.stage_two.fragments import build_d1

    fixture = Path(__file__).parents[1] / 'search/fixtures/function-monotonicity-inequality'
    candidate = json.loads((fixture / f'{name}-initial/result.json').read_text())['candidate']
    before = deepcopy(candidate)
    target = f'/root/goals/{index}'
    assert 'function_monotonicity' not in candidate['root']['goals'][index]
    features = candidate_features(candidate)
    for i in range(len(candidate['root']['goals'])):
        assert not build_d1(candidate, f'/root/goals/{i}', features['features'], {'items': []})['diagnostics']
    context = build_context(candidate, target)
    desc = context['mono_inequality_goal']
    assert desc['mono_basis'] == 'proved_monotonicity'
    state = driver.create_state(features=features['features'], context=context,
                                method='method-monotonicity-inequality', route_id='monotonicity-inequality',
                                branch='order', target_ref=target, run_id='photo-piecewise', lesson_version='v1')
    for _ in range(200):
        if state['status'] != 'running':
            break
        state = driver.advance(state)
    assert state['status'] == 'method_complete', state.get('diagnostics')
    model = driver.export_values(state)['mono_inequality_result']
    assert model['feasible_set'] == gold and verify(desc, model)
    assert candidate == before


@pytest.mark.parametrize('definition', [
    'f(x)=piecewise(x^2+1,x>=0,1,x<0)',  # a constant branch prevents strict order
    'f(x)=piecewise(x,x<1,x-2,x>=1)',  # increasing branches but a downward jump
    'f(x)=piecewise(x,x<0,x,x>1)',  # disconnected domain
])
def test_explicit_order_route_refuses_unproved_global_monotonicity(definition):
    entries = [{'source_ref': '/root/definitions/0', 'expression': definition},
               {'source_ref': '/root/facts/0', 'expression': 'f(1-x^2)>f(2*x)'}]
    assert routed_description({'kind': 'find_range', 'symbol': 'x'}, TARGET, entries) is None


@pytest.mark.parametrize('name,gold', [
    ('b01', sp.Interval.open(0, 1)),
    ('b02', sp.Interval.Lopen(sp.Rational(1, 2), sp.Rational(2, 3))),
    ('b03', sp.Interval.open(sp.Rational(-3, 2), 2)),
    ('b04', sp.Interval.open(-1, 3)),
    ('b05', sp.Interval.Ropen(sp.Rational(1, 2), sp.Rational(2, 3))),
    ('b06', sp.Interval.open(0, sp.Rational(2, 3))),
    ('b13', sp.Interval.Ropen(sp.Rational(1, 2), sp.Rational(2, 3))),
])
def test_feature_recognition_and_method_complete(name, gold, tmp_path):
    from shuxueshuo_server.graph_lesson.stage_one.authored import prepare_authored
    from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
    from shuxueshuo_server.graph_lesson.stage_three import driver, interaction
    from shuxueshuo_server.graph_lesson.stage_three.context import build_context
    from shuxueshuo_server.graph_lesson.stage_three.interaction_graph_contract import (
        validate_part_graphs,
    )
    from shuxueshuo_server.graph_lesson.stage_three.monotonicity_inequality_runtime import (
        admitted,
    )
    from shuxueshuo_server.graph_lesson.stage_two.recognition import evaluate_types
    from shuxueshuo_server.graph_lesson.stage_two.runner import run_result

    record, _ = source(name)
    features = extract_features(record['candidate'])
    assert features['ok'], features.get('diagnostics')
    supported = [row['type_id'] for row in evaluate_types(features['features']) if row['status'] == 'supported']
    assert supported == ['type-monotonicity-inequality']
    prepared = prepare_authored(record['candidate'], run_id=f't3-r0-{name}',
                                sources=record['sources'], reviewer=record['reviewer'])
    context = build_context(prepared['candidate'], TARGET)
    assert admitted(context)
    stage_two = run_result(prepared, tmp_path / name, admission='authored_topic')
    assert stage_two['goals'][0]['status'] == 'resolved'
    assert stage_two['goals'][0]['primary'] == 'type-monotonicity-inequality'

    state = driver.create_state(
        features=features['features'], context=context,
        method='method-monotonicity-inequality',
        route_id='monotonicity-inequality', branch='order',
        target_ref=TARGET, run_id=f't3-{name}', lesson_version='v1')
    for _ in range(200):
        if state['status'] != 'running':
            break
        state = driver.advance(state)
    assert state['status'] == 'method_complete', state.get('diagnostics')
    model = driver.export_values(state)['mono_inequality_result']
    assert model['feasible_set'] == gold
    assert verify(context['mono_inequality_goal'], model)

    chunks, pending = interaction.compile_route(
        state['interaction_seeds'], interaction.load_registry(), revision='test')
    assert pending == []
    assert chunks
    assert all(chunk['status'] in ('interactive', 'readonly') for chunk, _ in chunks)
    parts = [part for chunk, _ in chunks for part in chunk.get('parts') or []]
    assert parts
    validate_part_graphs(parts)
    titles = {part['title'] for part in parts}
    assert '利用单调性转化比较' in titles
    assert '回到原目标' in titles
    if name == 'b03':
        assert '核对比较对象与单调性' not in titles
        assert '带回整体严格单调结论' not in titles
        assert '两个输入的合法条件' not in titles
        assert any(title.startswith('检查跨段单调性') for title in titles)
        assert len(parts) <= 8
        piece_cards = [part for part in parts if '上的增减' in part['title']]
        assert len(piece_cards) >= 2
        assert all(part.get('graph') or part.get('completion_graph') for part in piece_cards)
        join = next(part for part in parts if part['title'] == '检查跨段单调性')
        assert join.get('graph') and join.get('completion_graph')
    for part in parts:
        assert part['interaction']['type'] == 'choice'
        assert part['expected_answer'].get('one_of')
        assert part['stem_board']['items'][1]['math'] is None
        if part['title'] == '利用单调性转化比较':
            assert '?' not in (part['completion_board']['items'][1]['math'] or '')
    conclude = next(row for row in parts if row['title'] == '回到原目标')
    assert all(r'\in' in row['label'] for row in conclude['interaction']['options'])
    inputs = next((row for row in parts if row['title'] == '两个输入的合法条件'), None)
    if inputs is not None:
        assert all(r'\in' in row['label'] for row in inputs['interaction']['options'])
