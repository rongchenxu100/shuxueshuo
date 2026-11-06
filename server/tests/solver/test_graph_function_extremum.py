"""T2: source-bound extrema, parameter coverage, and shared lesson contracts."""
import json
from copy import deepcopy
from pathlib import Path

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.extremum_math import (
    describe, numeric_model, operation_direction, parameter_model,
    verify_numeric, verify_parameter,
)
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value, encode_value

ROOT = Path(__file__).resolve().parents[3]
RECORDS = ROOT/'internal/senior-high/authored-courses/function-monotonicity-t2-20261104'
TARGET = '/root/goals/0'


def source(name):
    record = json.loads((RECORDS/f'{name}.json').read_text())
    candidate = record['candidate']
    entries = [{'source_ref': f'/root/{field}/{i}', 'expression': text}
               for field in ('definitions', 'facts') for i, text in enumerate(candidate['root'].get(field, []))]
    return record, describe(candidate['root']['goals'][0], TARGET, entries)


def direct(expr, interval='ℝ', quantity='minimum'):
    return describe({'kind': 'find_range', 'object': 'f', 'input_domain': interval,
                     'answer_request': {'kind': 'extremum', 'quantity': quantity}}, TARGET,
                    [{'source_ref': '/root/definitions/0', 'expression': f'f(x)={expr}'}])


@pytest.mark.parametrize('expression', ['0', 'sqrt(1-2*x)'])
def test_zero_polynomial_terms_compile_into_valid_teaching_graphs(expression):
    from shuxueshuo_server.graph_lesson.stage_three.extremum_presentation import compile_extremum
    from shuxueshuo_server.graph_lesson.stage_three.interaction_graph_contract import validate_part_graphs
    d = direct(expression, '[0,1/2]')
    model = numeric_model(d)
    assert model['value'] == 0 and model['attained'] and verify_numeric(d, model)
    for phase in ('children', 'conclude'):
        parts = compile_extremum([{'values': encode_value({
            'description': d, 'extremum_result': model, 'phase': phase})}], 'zero-'+phase)['parts']
        assert parts
        validate_part_graphs(parts)
        assert any(part.get('graph') or part.get('completion_graph') for part in parts)


@pytest.mark.parametrize('expression,interval,quantity,expected', [
    ('sqrt(4-x^2)', 'ℝ', 'maximum', 2),
    ('sqrt(x^2+1)', 'ℝ', 'minimum', 1),
    ('x^2', '(0,2)', 'supremum', 4),
])
def test_extrema_outside_t2_keep_the_existing_verified_range_route(expression, interval, quantity, expected):
    from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
    from shuxueshuo_server.graph_lesson.stage_three.context import build_context
    from shuxueshuo_server.graph_lesson.stage_two.recognition import evaluate_types
    from tests.solver.test_graph_function_range import candidate
    from tests.solver.test_graph_range_tasks import M3, solve
    value = candidate(expression, interval)
    value['root']['goals'][0]['answer_request'] = {'kind': 'extremum', 'quantity': quantity}
    features = extract_features(value)
    assert features['ok']
    assert [row['type_id'] for row in evaluate_types(features['features']) if row['status'] == 'supported'] == ['type-function-range']
    context = build_context(value, TARGET)
    assert 'range_goal' in context and 'extremum_goal' not in context
    _, answer, _ = solve(value, M3)
    assert decode_value(answer['value']['exact']) == expected


@pytest.mark.parametrize('name,gold', [
    ('a16', sp.S.One), ('a14', sp.Integer(3)),
    ('a07', sp.Interval.Lopen(0, 2)), ('a18', sp.Interval.Lopen(0, 2)),
    ('b16', sp.Interval.open(-sp.oo, -1)),
    ('b11', sp.Union(sp.Interval(-sp.oo, -4), sp.Interval(2, sp.oo))),
    ('b10', sp.Interval.open(2+sp.sqrt(7), sp.oo)),
    ('b08', sp.Interval(0, 2)),
    ('b14', sp.Union(sp.Interval(-sp.oo, -2), sp.Interval((3+sp.sqrt(13))/2, sp.oo))),
])
def test_original_nine_gold_and_independent_verification(name, gold, monkeypatch):
    _, d = source(name)
    assert d['structure_supported'], d['reason']
    solve, verify = (numeric_model, verify_numeric) if d['task'] == 'direct' else (parameter_model, verify_parameter)
    m = solve(d)
    assert m.get('feasible_set', m.get('value')) == gold
    monkeypatch.setattr('shuxueshuo_server.graph_lesson.extremum_math.'+solve.__name__, lambda *_: pytest.fail('solver called by verifier'))
    assert verify(d, m)
    assert verify(d, decode_value(encode_value(m)))
    bad = deepcopy(m)
    if d['task'] == 'direct':
        bad['attained'] = not m['attained']
    else:
        bad['feasible_set'] = gold ^ sp.FiniteSet(0)
    assert not verify(d, bad)


@pytest.mark.parametrize('expr,interval,quantity,value,attained', [
    ('(3*x-1)/(x+2)', '[-1,3]', 'maximum', sp.Rational(8,5), True),
    ('(3*x-1)/(x+2)', '[-1,3)', 'maximum', sp.Rational(8,5), False),
    ('sqrt(3-2*x)+x^2-4*x+6', 'ℝ', 'minimum', sp.Rational(9,4), True),
    ('x^2', '(-2,2)', 'maximum', sp.Integer(4), False),
    ('x^2', '(-2,2)', 'minimum', sp.S.Zero, True),
    ('4', '(0,1)', 'minimum', sp.Integer(4), True),
    ('(2*x+2)/(x+1)', '[-2,0]', 'maximum', sp.Integer(2), True),
    ('x^2', '[2,2]', 'minimum', sp.Integer(4), True),
    ('x', 'ℝ', 'maximum', sp.oo, False),
])
def test_unseen_coefficients_open_endpoints_constants_holes_and_singleton(expr, interval, quantity, value, attained):
    d = direct(expr, interval, quantity)
    m = numeric_model(d)
    assert (m['value'], m['attained']) == (value, attained)
    assert verify_numeric(d, m)
    if '/(x+1)' in expr:
        assert -1 not in m['domain'] and -1 not in m['witnesses']


def test_operation_rules_do_not_guess_missing_signs():
    assert operation_direction('sum', [-1, -1]) == -1
    assert operation_direction('sum', [0, 1]) == 1
    assert operation_direction('difference', [1, -1]) == 1
    for c in (-2, 0, 3):
        assert operation_direction('scale', [1], sp.Integer(c)) == sp.sign(c)
    for sign in ('positive', 'negative'):
        assert operation_direction('reciprocal', [1], sign=sign) == -1
    for op, ds, sign in [('sum', [1, -1], None), ('difference', [1, 1], None), ('reciprocal', [1], None), ('product', [1, 1], None)]:
        with pytest.raises(ValueError):
            operation_direction(op, ds, sign=sign)


def test_numeric_quadratic_proof_has_a_domain_clipped_picture():
    from shuxueshuo_server.graph_lesson.stage_three.extremum_graphs import proof_graph
    _, description = source('a07')
    model = parameter_model(description)
    graph = proof_graph(model['existential']['proofs'][0])
    assert graph['kind'] == 'piecewise_curve'
    assert graph['params']['segments'][0]['interval'] == [-2.0, 1.0]


def test_original_quantifier_roles_strictness_and_unused_conditions():
    _, d = source('b16')
    # Reversed written sides retain the two independently bound inputs.
    for row in d['given_definitions']:
        if '∀' in row['expression']:
            text = row['expression']
            row['expression'] = text.replace('x2^2-3*x2>m*x1+1', 'm*x1+1<x2^2-3*x2')
    assert parameter_model(d)['feasible_set'] == sp.Interval.open(-sp.oo, -1)
    _, bad = source('a07')
    bad['given_definitions'].append({'source_ref': '/root/definitions/2', 'expression': 'h(x)=x+1'})
    rebuilt = describe(bad['source'], TARGET, bad['given_definitions'])
    assert not rebuilt['structure_supported']


def test_operation_certificate_cannot_be_relabelled_after_solving():
    _, d = source('a16'); m = numeric_model(d)
    bad = deepcopy(m); bad['interval_steps'][0]['operations'][0]['after'] = 1
    assert not verify_numeric(d, bad)
    bad = deepcopy(m); bad['children'][0]['expression'] += 1
    assert not verify_numeric(d, bad)
    bad = deepcopy(m); bad['witnesses'] = [] ; bad['attained'] = False
    assert not verify_numeric(d, bad)


def test_piecewise_point_normalization_does_not_evaluate_inactive_division():
    from shuxueshuo_server.graph_lesson.stage_one.authored import prepare_authored
    from shuxueshuo_server.graph_lesson.stage_two.runner import run_result
    import tempfile
    r, _ = source('b08')
    first = prepare_authored(r['candidate'], run_id='test-b08', sources=r['sources'], reviewer=r['reviewer'])
    result = run_result(first, Path(tempfile.mkdtemp())/"run", admission='authored_topic')
    assert result['goals'][0]['status'] == 'resolved'
    assert result['goals'][0]['primary'] == 'type-monotonicity-extremum'


@pytest.mark.parametrize('name', ['a07', 'a18', 'b16', 'b11', 'b10'])
def test_quantified_certificates_match_borrowed_range_classifiers(name):
    from shuxueshuo_server.graph_lesson.stage_three.extremum_runtime import check_ranges
    _, d = source(name); m = parameter_model(d)
    output = check_ranges(d, m)
    assert output['checks'] and all(c['passed'] for c in output['checks'])


def test_b16_negative_slope_reads_max_at_left_endpoint():
    """m<0 is already given; max(mx+1) on [1,3] is m+1, not the unconstrained 3m+1."""
    from shuxueshuo_server.graph_lesson.stage_three.extremum_presentation import parameter_views
    from shuxueshuo_server.graph_lesson.stage_three.math_values import latex
    _, d = source('b16')
    views = parameter_views({'description': d, 'extremum_result': parameter_model(d), 'phase': 'ranges'})
    view = next(v for v in views if v['title'] == '由图像读出 g 的最大值')
    assert view['derivation']['items'][1]['math'] == latex(sp.Symbol('m') + 1)


@pytest.mark.parametrize('name', ['a16', 'a14', 'a07', 'a18', 'b16', 'b11', 'b10', 'b08', 'b14'])
def test_every_teaching_choice_is_answerable_and_unrevealed(name):
    from shuxueshuo_server.graph_lesson.stage_three.extremum_presentation import compile_extremum
    from shuxueshuo_server.graph_lesson.stage_three.interaction_graph_contract import validate_part_graphs
    _, d = source(name)
    m = numeric_model(d) if d['task'] == 'direct' else parameter_model(d)
    phases = ['prepare', 'children', 'operations', 'conclude'] if d['task'] == 'direct' else ['prepare', 'ranges', 'conditions', 'conclude']
    for phase in phases:
        parts = compile_extremum([{'values': encode_value({'description': d, 'extremum_result': m, 'phase': phase})}], name+phase)['parts']
        if not parts:
            # Quantified lessons may skip prepare when the existential domain is already nonempty.
            # Specified M8 skips ranges／conditions; per-piece transform／method＋子方法 expand 求参.
            assert ((d['task'] == 'quantified' and phase == 'prepare')
                    or (d['task'] == 'specified' and phase in ('ranges', 'conditions')))
            continue
        assert parts
        validate_part_graphs(parts)
        for part in parts:
            if part['interaction'].get('type') == 'read':
                # Inform boards use a lines layout—no blank「下一步 ?」result cell.
                assert 'lines' in part['stem_board'] and 'items' not in part['stem_board']
                assert not part['interaction'].get('options')
                continue
            assert part['stem_board']['items'][1]['math'] is None
            assert len(part['interaction']['options']) >= 2
            assert len({o['value'] for o in part['interaction']['options']}) == len(part['interaction']['options'])
        if d['task'] == 'direct' and phase == 'conclude':
            assert parts[0]['graph']['params']['points'] == []
            assert parts[0]['completion_graph']['params']['points']


def test_m8_specified_spine_reuses_quantified_subproblem_plane():
    """B08/M8: 每段复用「判断转化后的问题」+ 恒成立 plane，正路分离参数。"""
    from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
    from shuxueshuo_server.graph_lesson.stage_three import driver, interaction
    from shuxueshuo_server.graph_lesson.stage_three.context import build_context
    from shuxueshuo_server.graph_lesson.stage_three.extremum_presentation import parameter_views
    from shuxueshuo_server.graph_lesson.stage_three.extremum_runtime import (
        prepare_parameter_children, bind_parameter_child)
    _, d = source('b08')
    m = parameter_model(d)
    assert parameter_views({'description': d, 'extremum_result': m, 'phase': 'ranges'}) == []
    conclude = parameter_views({'description': d, 'extremum_result': m, 'phase': 'conclude'})
    assert conclude and '第' not in conclude[0]['title'] and '左' not in conclude[0]['question']
    cases = prepare_parameter_children(d, m)['outputs']['piece_cases']
    for case in cases:
        child = bind_parameter_child(case, m)['outputs']
        assert child['piece_kind'] == 'separable'
        assert child['borrowed_method'] == 'method-separation'
        assert '第' not in child['subproblem_context'] and '左' not in child['subproblem_context']
    record, _ = source('b08')
    state = driver.create_state(
        features=extract_features(record['candidate'])['features'],
        context=build_context(record['candidate'], TARGET),
        method='method-extremum-condition-parameter',
        route_id='extremum-condition-parameter', branch='direct',
        target_ref=TARGET, run_id='m8-plane', lesson_version='v1')
    for _ in range(500):
        if state['status'] != 'running':
            break
        state = driver.advance(state)
    assert state['status'] == 'method_complete'
    chunks, pending = interaction.compile_route(
        state['interaction_seeds'], interaction.load_registry(), revision='test')
    assert pending == []
    parts = [part for chunk, _ in chunks for part in chunk.get('parts') or []]
    assert all(chunk['status'] == 'interactive' for chunk, _ in chunks)
    assert sum(1 for part in parts if part['title'] == '判断转化后的问题') == 2
    planes = [part for part in parts if part['title'] == '选择恒成立问题的解题方法']
    assert len(planes) == 2
    assert all(part['interaction']['type'] == 'plane' for part in planes)
    assert all(part['expected_answer'] == {'cell': ['interval', 'free'], 'method': 'separation'}
               for part in planes)
    assert not any(part['title'] in ('选择解法', '写成恒成立') for part in parts)


def test_branch_and_candidate_evidence_tampering_is_rejected():
    _, d = source('b11'); m = parameter_model(d)
    for field, value in [('u_bounds', [sp.Integer(-1), sp.Integer(4)]), ('conditions', [sp.S.true])]:
        bad = deepcopy(m); bad['cases'][0][field] = value
        assert not verify_parameter(d, bad)
    bad = deepcopy(m); bad['cases'].append(deepcopy(bad['cases'][0]))
    assert not verify_parameter(d, bad)
    _, d = source('a16'); m = numeric_model(d)
    bad = deepcopy(m); bad['candidates'][0]['value'] += 10
    assert not verify_numeric(d, bad)


def test_m8_borrowed_contract_compares_zero_on_left():
    from shuxueshuo_server.graph_lesson.stage_three.extremum_runtime import prepare_parameter_children, bind_parameter_child
    for name, operator in [('b08', '<='), ('b14', '>=')]:
        _, d = source(name); m = parameter_model(d)
        case = prepare_parameter_children(d, m)['outputs']['piece_cases'][0]
        child = bind_parameter_child(case, m)['outputs']
        assert child['interval_operator'] == operator
        assert sp.expand(child['interval_function']-(case['proof']['expression']-m['specified_value'])) == 0


def test_m8_bind_prefers_separable_for_both_b08_pieces():
    from shuxueshuo_server.graph_lesson.stage_three.extremum_runtime import (
        prepare_parameter_children, bind_parameter_child)
    _, d = source('b08'); m = parameter_model(d)
    cases = prepare_parameter_children(d, m)['outputs']['piece_cases']
    assert [case['kind'] for case in cases] == ['polynomial', 'reciprocal_sum']
    for case in cases:
        child = bind_parameter_child(case, m)['outputs']
        assert child['piece_kind'] == 'separable'
        assert child['quantifier'] == '∀'
        assert child['relation_kind'] == 'inequality'
        assert child['function_name'] == 'h'
        assert child['strict'] is False
        assert child['relation'].lhs == case['proof']['expression']
        assert child['relation'].rhs == m['specified_value']
    left = bind_parameter_child(cases[0], m)['outputs']
    assert left['piece_domain'] == sp.Interval.open(-sp.oo, 0)


@pytest.mark.parametrize('name', ['b08', 'b14'])
def test_m8_prepare_and_conclude_full_derivation_uses_because_therefore(name):
    """指定最值准备／汇总的完整推导写 ∵∴，不只堆结论板书。"""
    from shuxueshuo_server.graph_lesson.stage_three.extremum_presentation import presentation
    _, d = source(name)
    m = parameter_model(d)
    prepare = presentation({
        'description': d, 'extremum_result': m, 'phase': 'prepare',
        'before': [], 'after': [],
    })
    assert r'\because' in prepare['formula_explanation']
    assert r'\therefore' in prepare['formula_explanation']
    assert r'\forall' in prepare['formula_explanation']
    # 结论卡仍是最后一问的短板书，不是完整 ∵∴ 链。
    assert r'\because' not in (prepare.get('derivation_left_math') or '')
    conclude = presentation({
        'description': d, 'extremum_result': m, 'phase': 'conclude',
        'before': [], 'after': [],
    })
    assert r'\therefore' in conclude['formula_explanation']
    assert '各段结果取交集' in conclude['formula_explanation']
    assert r'\therefore' not in (conclude.get('derivation_right_math') or '')


@pytest.mark.parametrize('name', ['a07', 'a18', 'b16', 'b11', 'b10'])
def test_m7_host_phases_full_derivation_uses_because_therefore(name):
    """M7 读值域／求参／汇总的完整推导写 ∵∴，不只堆结论板书。"""
    from shuxueshuo_server.graph_lesson.stage_three.extremum_presentation import presentation
    _, d = source(name)
    m = parameter_model(d)
    for phase in ('ranges', 'conditions', 'conclude'):
        shown = presentation({
            'description': d, 'extremum_result': m, 'phase': phase,
            'before': [], 'after': [],
        })
        expl = shown['formula_explanation']
        assert r'\begin{gathered}' not in expl
        assert r'\therefore' in expl or r'\because' in expl
        assert r'\because' not in (shown.get('derivation_right_math') or '')


@pytest.mark.parametrize('name', ['a16', 'a14'])
def test_m4_host_phases_full_derivation_is_student_writeup(name):
    """M4 分离／辅助增减／运算／最值的完整推导写学生链，不只堆结论板书。"""
    from shuxueshuo_server.graph_lesson.stage_three.extremum_presentation import presentation
    _, d = source(name)
    m = numeric_model(d)
    for phase in ('prepare', 'children', 'operations', 'conclude'):
        shown = presentation({
            'description': d, 'extremum_result': m, 'phase': phase,
            'before': [], 'after': [],
        })
        expl = shown['formula_explanation']
        assert r'\begin{gathered}' not in expl
        assert r'\therefore' in expl
        assert r'\because' not in (shown.get('derivation_right_math') or '')


def test_m8_b14_right_piece_is_one_quick_check():
    """B14 右段不含 a：跳过恒成立入口，只留一步快速验证。"""
    from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
    from shuxueshuo_server.graph_lesson.stage_three import driver, interaction
    from shuxueshuo_server.graph_lesson.stage_three.context import build_context
    from shuxueshuo_server.graph_lesson.stage_three.extremum_runtime import (
        prepare_parameter_children, bind_parameter_child)
    record, d = source('b14')
    m = parameter_model(d)
    cases = prepare_parameter_children(d, m)['outputs']['piece_cases']
    left = bind_parameter_child(cases[0], m)['outputs']
    right = bind_parameter_child(cases[1], m)['outputs']
    assert left['piece_kind'] == 'polynomial'
    assert left['borrowed_method'] == 'method-interval-extremum'
    assert right['piece_kind'] == 'independent'
    assert m['parameter'] not in right['universal_statement'].free_symbols
    state = driver.create_state(
        features=extract_features(record['candidate'])['features'],
        context=build_context(record['candidate'], TARGET),
        method='method-extremum-condition-parameter',
        route_id='extremum-condition-parameter', branch='direct',
        target_ref=TARGET, run_id='m8-b14-independent', lesson_version='v1')
    for _ in range(500):
        if state['status'] != 'running':
            break
        state = driver.advance(state)
    assert state['status'] == 'method_complete'
    chunks, pending = interaction.compile_route(
        state['interaction_seeds'], interaction.load_registry(), revision='test')
    assert pending == []
    assert all(chunk['status'] == 'interactive' for chunk, _ in chunks)
    parts = [part for chunk, _ in chunks for part in chunk.get('parts') or []]
    assert sum(1 for part in parts if part['title'] == '判断转化后的问题') == 1
    selects = [part for part in parts if part['title'] == '选择恒成立问题的解题方法']
    assert len(selects) == 1 and selects[0]['interaction']['type'] == 'plane'
    quick = [part for part in parts if part['title'] == '快速验证本段']
    assert len(quick) == 1
    board = quick[0]['completion_board']
    assert board.get('layout') == 'derivation'
    assert r'\because' not in (board['items'][0]['math'] or '')
    assert '无额外限制' in (board['items'][1]['math'] or '')
    # 完整推导在 math_step.explanation，不在结论卡里。
    from shuxueshuo_server.graph_lesson.stage_three.extremum_presentation import presentation
    from shuxueshuo_server.graph_lesson.stage_three.extremum_runtime import (
        independent_parameter_piece)
    verified = independent_parameter_piece(
        right['relation'], right['piece_variable'], right['piece_domain'], m['parameter'])
    shown = presentation({
        'description': d, 'extremum_result': m, 'phase': 'independent',
        'piece_expression': right['piece_expression'],
        'piece_variable': right['piece_variable'],
        'piece_domain': right['piece_domain'],
        'piece_kind': 'independent',
        'relation': right['relation'],
        **{k: verified['outputs'][k] for k in (
            'independent_holds', 'independent_expression', 'independent_bound',
            'independent_operator', 'independent_range', 'independent_slope',
            'independent_bound_key')},
        'parameter': m['parameter'],
        'before': [right['relation']],
        'after': [verified['outputs']['piece_solution']],
    })
    assert r'\because' in shown['formula_explanation']
    assert r'\therefore' in shown['formula_explanation']
    assert '判断本段增减' not in [part['title'] for part in parts]


@pytest.mark.parametrize(
    ('fact', 'expected'),
    [
        ('∀x∈ℝ:x^2+a>=0', True),
        ('∀x∈(0,∞):x+1/x+a>=a^2', True),
        ('∀x∈ℝ:x+1/x+a>=a^2', False),
        ('∀x∈ℝ:x^3+a>=0', False),
    ],
)
def test_separation_admits_quadratic_or_separable_reciprocal(fact, expected):
    from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
    from shuxueshuo_server.graph_lesson.stage_three import driver
    from shuxueshuo_server.graph_lesson.stage_three.context import build_context
    value = {'original_text': fact, 'root': {'facts': [fact], 'goals': [{'kind': 'find_range', 'symbol': 'a'}]}}
    features = extract_features(value)['features']
    context = build_context(value, TARGET)
    assert driver.can_execute('method-separation', features, context) is expected


def test_m8_expanded_children_compile_interactive_without_parent_solve_cards():
    from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
    from shuxueshuo_server.graph_lesson.stage_three import driver, interaction
    from shuxueshuo_server.graph_lesson.stage_three.context import build_context
    record, _ = source('b08')
    cand = record['candidate']
    state = driver.create_state(
        features=extract_features(cand)['features'],
        context=build_context(cand, TARGET),
        method='method-extremum-condition-parameter',
        route_id='extremum-condition-parameter', branch='direct',
        target_ref=TARGET, run_id='m8-light', lesson_version='v1')
    for _ in range(500):
        if state['status'] != 'running':
            break
        state = driver.advance(state)
    assert state['status'] == 'method_complete', state['trajectory']
    assert driver.export_values(state)['extremum_result']['feasible_set'] == sp.Interval(0, 2)
    chunks, pending = interaction.compile_route(
        state['interaction_seeds'], interaction.load_registry(), revision='test')
    assert pending == []
    assert all(chunk['status'] == 'interactive' for chunk, _ in chunks)
    titles = [part.get('title') for chunk, _ in chunks for part in chunk.get('parts') or []]
    assert titles.count('判断转化后的问题') == 2
    assert titles.count('选择恒成立问题的解题方法') == 2
    assert any('分离' in (title or '') for title in titles)
    assert any('对勾' in (title or '') for title in titles)
    assert not any(title and ('段：求参' in title or '第 1 段' in title or '选择解法' in title) for title in titles)


def test_separation_solves_b08_right_residual_directly():
    from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
    from shuxueshuo_server.graph_lesson.stage_three import driver
    from shuxueshuo_server.graph_lesson.stage_three.context import build_context
    fact = '∀x∈(0,∞):x+1/x+a>=a^2'
    value = {'original_text': fact, 'root': {'facts': [fact], 'goals': [{'kind': 'find_range', 'symbol': 'a'}]}}
    state = driver.create_state(
        features=extract_features(value)['features'],
        context=build_context(value, TARGET),
        method='method-separation', route_id='separation', branch='separation',
        target_ref=TARGET, run_id='sep-b08', lesson_version='v1')
    for _ in range(200):
        if state['status'] != 'running':
            break
        state = driver.advance(state)
    assert state['status'] == 'method_complete', state['trajectory']
    assert driver.export_values(state)['feasible_set'] == sp.Interval(-1, 2)


@pytest.mark.parametrize('name', ['b08', 'b14'])
def test_natural_specified_extremum_source_is_located(name, tmp_path):
    from shuxueshuo_server.graph_lesson.stage_one.authored import prepare_authored
    from shuxueshuo_server.graph_lesson.stage_two.runner import run_result
    record, _ = source(name)
    first = prepare_authored(record['candidate'], run_id='source-'+name, sources=record['sources'], reviewer=record['reviewer'])
    result = run_result(first, tmp_path/name, admission='authored_topic')
    assert not result['goals'][0]['d1'].get('diagnostics')


@pytest.mark.parametrize('expression,point,quantity,gold', [
    ('piecewise((x-a)^2,x<=1,x+3,x>1)', '1', 'min', sp.Interval(1,3)),
    ('piecewise(-(x-a)^2+a+2,x<2,-x+5,x>=2)', '2', 'max',
     sp.Union(sp.Interval(-sp.oo,1),sp.Interval((5+sp.sqrt(5))/2,sp.oo))),
])
def test_unseen_specified_points_boundaries_and_coefficients(expression, point, quantity, gold):
    d = describe({'kind':'find_range','symbol':'a'}, TARGET, [
        {'source_ref':'/root/definitions/0','expression':'h(x)='+expression},
        {'source_ref':'/root/facts/0','expression':quantity+'_{x}(h(x))=h('+point+')'}])
    m = parameter_model(d)
    assert m['feasible_set'] == gold and verify_parameter(d,m)


@pytest.mark.parametrize('fact', [
    '∀s∈[0,1):∃t∈[0,1]:s<t+a',
    '∀s∈[0,1]:∃t∈[0,1):s<=t+a',
    '∀s∈[0,1]:∃t∈[s,1]:s<=t+a',
    '∃t∈[0,1]:∀s∈[0,1]:s<=t+a',
])
def test_unsupported_unattained_extrema_dependent_or_reversed_quantifiers(fact):
    d = describe({'kind':'find_range','symbol':'a'}, TARGET, [
        {'source_ref':'/root/facts/0','expression':fact}])
    if d['structure_supported']:
        with pytest.raises(ValueError):
            parameter_model(d)


def test_equal_extremes_do_not_imply_coverage_of_a_disconnected_image():
    d = describe({'kind':'find_range','symbol':'a'}, TARGET, [
        {'source_ref':'/root/definitions/0','expression':'h(t)=piecewise(0,t<0,2,t>=0)'},
        {'source_ref':'/root/facts/0','expression':'∀s∈[0,2]:∃t∈[-1,1]:s=h(t)+a'}])
    with pytest.raises(ValueError):
        parameter_model(d)


@pytest.mark.parametrize('body,source,expected', [
    (r'-\frac{1}{2}x+1','-x/2+1',True),
    (r'-\frac{1}{x}+x','-1/x+x',True),
    (r'\frac{x}{x}','1',False),
    (r'\sqrt{x}+1','sqrt(x+1)',False),
    (r'\frac{x}{y/z}','x*z/y',False),
])
def test_surface_matching_retains_operators_and_denominator_obligations(body, source, expected):
    from shuxueshuo_server.graph_lesson.stage_two.fragments import _abstract_formula_matches
    assert _abstract_formula_matches(body,source) is expected


def test_extremum_seed_retains_teaching_intervals():
    from shuxueshuo_server.graph_lesson.stage_three.presentation import _seed_values
    from shuxueshuo_server.graph_lesson.stage_three.extremum_presentation import compile_extremum
    _, d = source('a16')
    m = numeric_model(d)
    seed = {'values': encode_value(_seed_values({'extremum_result':m,'phase':'operations','description':d}))}
    parts = compile_extremum([seed], 'probe')['parts']
    assert [p['stem_board']['operation']['label'] for p in parts] == ['取倒数','乘常数','加常数']
