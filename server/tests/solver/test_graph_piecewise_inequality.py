"""FR-T3 P2b: source thresholds, strictness, branch domains and progressive cards."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
import sympy as sp
from jsonschema import Draft202012Validator

from shuxueshuo_server.graph_lesson import piecewise_inequality as pi
from shuxueshuo_server.graph_lesson.stage_one.runner import candidate_features
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.piecewise_inequality_presentation import (
    compile_piecewise,
    phase_views,
)
from shuxueshuo_server.graph_lesson.stage_three.trajectory import (
    decode_value,
    encode_value,
)
from shuxueshuo_server.learning.graph_walk import grade

ROOT = Path(__file__).resolve().parents[3]
TARGET = '/root/goals/0'
ANSWER = sp.Union(sp.Interval.open(-3, 1), sp.Interval.open(3, sp.oo))


def candidate(definition=None, relation=None):
    value = json.loads((ROOT/'internal/senior-high/authored-courses/piecewise-p2-20261102/b10-v2.json').read_text())['candidate']
    if definition:
        value['root']['definitions'] = [definition]
    if relation:
        value['root']['facts'] = [relation]
    return value


def run(c):
    ctx = build_context(c, TARGET)
    assert pi.admitted(ctx), ctx.get('piecewise_inequality')
    level = pi.evaluate_level(ctx)['outputs']
    roots = pi.solve_roots(**level)['outputs']
    signs = pi.solve_signs(**level, **decode_value(encode_value(roots)))['outputs']
    result = pi.filter_branches(**level, **decode_value(encode_value(signs)))['outputs']
    return ctx, {**level, **result}


def test_original_threshold_branches_and_independent_full_set_verification(monkeypatch):
    c = candidate()
    ctx, result = run(c)
    assert result['level'] == 3 and result['feasible_set'] == ANSWER
    first, second = result['branch_results']
    assert first['accepted'] == sp.Union(sp.Interval.Ropen(0, 1), sp.Interval.open(3, sp.oo))
    assert second['accepted'] == sp.Interval.open(-3, 0)
    assert 0 in result['feasible_set']
    monkeypatch.setattr(pi, 'solve_signs', lambda *_: pytest.fail('verification must be independent'))
    assert pi.independent_verify(c, TARGET, ctx, ANSWER)['status'] == 'verified'
    for bad in [ANSWER-sp.FiniteSet(0), ANSWER|sp.FiniteSet(1), first['accepted']]:
        assert pi.independent_verify(c, TARGET, ctx, bad)['status'] == 'math_failed'
    assert pi.independent_verify(candidate(relation='f(x)>=f(1)'), TARGET, ctx, ANSWER)['status'] == 'math_failed'
    boundary = pi.endpoints(c, TARGET, ANSWER)
    assert boundary['status'] == 'passed'
    assert {p['point']['expression']: p['included'] for p in boundary['points']} == {'-3': False, '0': True, '1': False, '3': False}
    for key, value in [('domain', sp.S.Reals), ('positive_expression', sp.S.Zero), ('accepted', sp.S.Reals), ('roots', [])]:
        bad = deepcopy(result['branch_results']); bad[0][key] = value
        assert not pi.verify_rows(result['description'], 3, bad)
    assert not pi.verify_rows(result['description'], 4, result['branch_results'])


@pytest.mark.parametrize(('definition', 'relation', 'expected'), [
    (None, 'f(x)>=f(1)', sp.Union(sp.Interval(-3, 1), sp.Interval(3, sp.oo))),
    (None, 'f(1)<f(x)', ANSWER),
    (None, 'f(x)<=f(1)', sp.Union(sp.Interval(-sp.oo, -3), sp.Interval(1, 3))),
    ('f(t)=piecewise(t^2,t>=0,t+1,t<0)', 'f(x)>f(0)', sp.Interval.open(-1, 0)|sp.Interval.open(0, sp.oo)),
    ('f(t)=piecewise(0,t<=0,t^2,t>0)', 'f(x)>=0', sp.S.Reals),
    ('f(x)=piecewise(0,x<0,0,x>0)', 'f(x)>0', sp.S.EmptySet),
    ('f(x)=piecewise(x^2,x<0,x,x>0)', 'f(x)<2', sp.Interval.open(-sp.sqrt(2), 0)|sp.Interval.open(0, 2)),
])
def test_strict_closed_reversed_constant_gap_and_irrational_cases(definition, relation, expected):
    c = candidate(definition, relation)
    ctx, result = run(c)
    assert result['feasible_set'] == expected
    assert pi.independent_verify(c, TARGET, ctx, expected)['status'] == 'verified'
    assert pi.endpoints(c, TARGET, expected)['status'] == 'passed'


@pytest.mark.parametrize(('definition', 'relation'), [
    ('f(x)=piecewise(x,x<0,x^2,x>0)', 'f(x)>f(0)'),
    ('f(x)=piecewise(x,x<=0,x^2,x>=0)', 'f(x)>f(1)'),
    ('f(x)=piecewise(1/x,x<0,x,x>=0)', 'f(x)>1'),
    ('f(x)=piecewise(x^3,x<0,x,x>=0)', 'f(x)>1'),
    (None, 'f(x)>f(f(1))'),
    (None, 'f(x)>x'),
    (None, 'f(f(x))>1'),
])
def test_unsupported_sources_are_refused(definition, relation):
    assert not pi.inspect_target(candidate(definition, relation), TARGET)['structure_supported']


def test_additional_conditions_and_source_uncertainties_are_preserved():
    for field, extra in [('facts', 'x>0'), ('uncertainties', {'kind': 'ambiguous_symbol', 'text': '分界点不清'})]:
        c = candidate(); c['root'].setdefault(field, []).append(extra)
        assert not pi.inspect_target(c, TARGET)['structure_supported']


def test_source_reading_selection_original_options_and_frozen_contracts():
    from shuxueshuo_server.graph_lesson.stage_one.extraction import frozen_files
    from shuxueshuo_server.graph_lesson.stage_three.choice_matching import (
        match_original_choice,
    )
    from shuxueshuo_server.graph_lesson.stage_three.execution_contracts import (
        load_contracts,
    )
    from shuxueshuo_server.graph_lesson.stage_three.goals import finalize_goal
    from shuxueshuo_server.graph_lesson.stage_three.runner import fingerprint
    from shuxueshuo_server.graph_lesson.stage_three.selection import evaluate_goal
    from shuxueshuo_server.graph_lesson.stage_two.fragments import build_d1
    from shuxueshuo_server.search.lesson import d1_rows
    c = candidate(); features = candidate_features(c)
    assert features['ok'], features['diagnostics']
    assert pi.METHOD in load_contracts()
    selected = evaluate_goal(c, TARGET, features['features'], 'type-piecewise-function')
    assert selected['d4']['options'][0]['method'] == pi.METHOD
    fragments = build_d1(c, TARGET, features['features'], {'items': []})
    assert not fragments['diagnostics'] and len(fragments['fragments']) == 3
    rows = d1_rows(TARGET, fragments['fragments'], {'piecewise_inequality': pi.inspect_target(c, TARGET)}, c['original_text'])
    assert len(rows['rows']) == 1 and '不等式' in rows['summary']
    bad = deepcopy(c); bad['original_text'] = bad['original_text'].replace('f(x)>f(1)', 'f(x)>=f(1)')
    assert build_d1(bad, TARGET, features['features'], {'items': []})['diagnostics']
    answer = finalize_goal(c['root']['goals'][0], ANSWER)
    assert match_original_choice(c, TARGET, answer, encode_value(ANSWER))['correct_labels'] == ['A']
    path = 'server/shuxueshuo_server/graph_lesson/piecewise_inequality.py'
    assert path in frozen_files() and path in fingerprint()


def test_b12_two_composite_inputs_constant_piece_and_strip_f_counterexample():
    gold = sp.Interval.open(-1, -1 + sp.sqrt(2))
    c = {
        'original_text': (
            r'已知函数 $f(x)=\begin{cases}x^{2}+1,&x\ge0,\\1,&x<0\end{cases}$。'
            r'若 $f(1-x^{2})>f(2x)$，则 $x$ 的取值范围是______。'),
        'root': {
            'definitions': ['f(x)=piecewise(x^2+1,x>=0,1,x<0)'],
            'facts': ['f(1-x^2)>f(2*x)'],
            'goals': [{'kind': 'find_range', 'symbol': 'x'}],
        },
    }
    desc = pi.inspect_target(c, TARGET)
    assert desc['structure_supported'], desc.get('reason')
    assert pi.source(desc)['mode'] == 'two_inputs'
    result = pi.solve_two_input_cases(desc)['outputs']
    assert result['feasible_set'] == gold
    assert len(result['case_results']) == 4
    ctx = build_context(c, TARGET)
    assert pi.admitted(ctx)
    assert pi.independent_verify(c, TARGET, ctx, gold)['status'] == 'verified'
    assert pi.endpoints(c, TARGET, gold)['status'] == 'passed'
    # Directly stripping f yields a strictly larger wrong set.
    wrong = sp.Interval.open(-1 - sp.sqrt(2), -1 + sp.sqrt(2))
    assert pi.independent_verify(c, TARGET, ctx, wrong)['status'] == 'math_failed'
    assert (-2 in wrong) and (-2 not in gold)
    for phase in ('applicability', 'cases', 'merge'):
        values = {**result, 'phase': phase}
        parts = compile_piecewise([{'values': encode_value(values)}], 'd' * 24)['parts']
        assert parts and all(part['stem_board']['items'][1]['math'] is None for part in parts)
    applicability = compile_piecewise(
        [{'values': encode_value({**result, 'phase': 'applicability'})}], 'e' * 24)['parts'][0]
    assert '严格单调' in applicability['title']
    assert '去函数符号' not in applicability['title']
    assert '去函数符号' not in applicability['question']
    assert applicability['graph']['kind'] == 'piecewise_curve'
    assert applicability['completion_graph']['kind'] == 'piecewise_curve'
    assert len(applicability['graph']['params']['segments']) == 2
    case_parts = compile_piecewise(
        [{'values': encode_value({**result, 'phase': 'cases'})}], 'f' * 24)['parts']
    assert case_parts and all(part['graph']['kind'] == 'piecewise_curve' for part in case_parts)
    assert all(part['graph']['params'].get('highlights') for part in case_parts)
    assert all('第1段' not in part['title'] and '第2段' not in part['title'] for part in case_parts)
    assert '1 - x^{2}' in case_parts[0]['title'] or '1 - x^2' in case_parts[0]['title']
    assert '- x^{2} + 1' not in case_parts[0]['question']
    assert '结合图像' in case_parts[0]['question']
    assert '着色段' not in case_parts[0]['question']
    assert '着色段' not in (case_parts[0]['graph'].get('caption') or '')
    assert '第1段' not in case_parts[0]['question']
    assert '严格递增' in case_parts[0]['question'] or '严格递减' in case_parts[0]['question']
    assert 'x\\ge 0' in case_parts[0]['question'] or r'x\ge0' in case_parts[0]['question']
    assert r'\Leftrightarrow' in case_parts[0]['question'] or 'Leftrightarrow' in case_parts[0]['question']
    assert len(case_parts[0]['graph']['params'].get('points') or []) == 2
    assert {p['place'] for p in case_parts[0]['graph']['params']['points']} == {'above', 'below'}
    assert r'x\in' in case_parts[0]['stem_board']['items'][0]['math']
    assert '1 - x^{2}' in case_parts[0]['stem_board']['items'][0]['math']
    ticks = [tick[1] for tick in case_parts[0]['graph']['params'].get('xTicks') or []]
    assert '3/4' not in ticks and '1' not in ticks
    assert all(len(part['graph']['params'].get('points') or []) == 2 for part in case_parts)
    for part in case_parts:
        xs = [point['x'] for point in part['graph']['params']['points']]
        lo, hi, *_ = part['graph']['params']['bounds']
        assert lo <= min(xs) <= max(xs) <= hi
    case2 = next(part for part in case_parts if '2 x<0' in part['title'] or '2x<0' in part['title'].replace(' ', ''))
    assert '右输入' not in case2['question'] and '左边' not in case2['question']
    assert '2 x' in case2['question'] or '2x' in case2['question']
    assert [g['kind'] for g in case_parts[0]['completion_graphs']] == ['piecewise_curve', 'number_line']


def test_progressive_cards_include_context_math_derivations_and_graphs():

    _, data = run(candidate())
    schema = json.loads((ROOT/'internal/schemas/graph-step-interaction-v1.schema.json').read_text())
    validator = Draft202012Validator({'$defs': schema['$defs'], '$ref': '#/$defs/part'})
    for phase in ('level', 'branches', 'merge'):
        values = {**data, 'phase': phase}
        views = phase_views(values)
        parts = compile_piecewise([{'values': encode_value(values)}], 'b'*24)['parts']
        for part, view in zip(parts, views, strict=True):
            validator.validate(part)
            assert part['stem_board']['items'][1]['math'] is None
            assert '=' in view['proof'] or '>' in view['proof']
            answer = part['expected_answer']['one_of'][0]
            assert grade(part, {'value': answer}, 'piecewise-inequality') == 'passed'
            wrong = next(o['value'] for o in part['interaction']['options'] if o['value'] != answer)
            assert grade(part, {'value': wrong}, 'piecewise-inequality') != 'passed'
        if phase == 'branches':
            assert len(parts) == 4 and 'x\\ge 0' in parts[1]['question']
            # Both disjoint intervals must be intersected with the branch domain.
            assert r'\right)\cap' in views[1]['proof']
            assert parts[0]['graph']['kind'] == 'quadratic'
            assert 'markSign' not in parts[0]['graph']['params']
            assert parts[0]['completion_graph']['params']['markSign'] == 'above'


@pytest.mark.parametrize('expression', [
    'piecewise(t,t<0,t+1,t>=0)',
    'piecewise(-t,t<0,-t-1,t>=0)',
    'piecewise(t^2,t<1,t+1,t>=1)',
])
def test_general_two_input_cards_do_not_invent_a_constant_branch(expression):
    c = {'original_text': '按分段表达式比较两个函数值。', 'root': {
        'definitions': ['f(t)=' + expression], 'facts': ['f(x)<f(2*x)'],
        'goals': [{'kind': 'find_range', 'symbol': 'x'}]}}
    d = pi.inspect_target(c, TARGET)
    assert d['structure_supported'], d['reason']
    values = {'description': d, 'phase': 'applicability'}
    part, = compile_piecewise([{'values': encode_value(values)}], 'e' * 24)['parts']
    assert part['title'] == '确定两个输入的分支'
    assert '不严格单调' not in json.dumps(part, ensure_ascii=False)
    correct = part['expected_answer']['one_of'][0]
    assert grade(part, {'value': correct}, {}) == 'passed'
    if 't^2' in expression:
        trends = part['completion_graph']['params']['interval_marks']
        assert {mark['trend'] for mark in trends} >= {'decreasing', 'increasing'}


def test_constant_branch_can_be_on_the_right_of_a_decreasing_branch():
    c = {'original_text': '按分段表达式比较两个函数值。', 'root': {
        'definitions': ['f(t)=piecewise(-t,t<0,1,t>=0)'], 'facts': ['f(x)<f(2*x)'],
        'goals': [{'kind': 'find_range', 'symbol': 'x'}]}}
    d = pi.inspect_target(c, TARGET)
    part, = compile_piecewise([{'values': encode_value({'description': d, 'phase': 'applicability'})}], 'e' * 24)['parts']
    rendered = json.dumps(part, ensure_ascii=False)
    assert '左段水平' not in rendered and '右段上升' not in rendered
    assert r't\in \left[0, \infty\right)' in part['stem_board']['items'][0]['math']
    correct = part['expected_answer']['one_of'][0]
    assert grade(part, {'value': correct}, {}) == 'passed'
