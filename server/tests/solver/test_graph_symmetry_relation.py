"""T5 exact mathematics and source boundaries; no live model or course rebuild."""
from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.symmetry_relation_math import (
    describe,
    solve,
    verify,
)

TARGET = '/root/goals/0'


def candidate(facts=None, expression='f(3)', text=None, goal=None):
    return {'original_text': text or r'已知函数 $f(x)$ 定义在 $\mathbf R$ 上，图像关于直线 $x=2$ 对称，且 $f(1)=3$，求 $f(3)$ 的值。',
            'root': {'facts': facts or ['Dom(f)=ℝ', 'graph_symmetry(f,axis,2)', 'f(1)=3'],
                     'goals': [goal or {'kind': 'find_value', 'expression': expression}]}}


def description(v, bound=False):
    c = build_context(v, TARGET)
    return describe(c['goal'], c['goal_ast'], TARGET, c['entries'], candidate=v if bound else None)


def a10(sum_=False):
    goal = {'kind': 'finite_sum', 'terms': [{'expression': 'f(k)', 'index': 'k', 'lower': 1, 'upper': 54}]} if sum_ else {
        'kind': 'find_value', 'expression': 'f(1)+f(2)+f(3)+f(4)'}
    target = r'f(1)+f(2)+\cdots+f(54)' if sum_ else r'f(1)+f(2)+f(3)+f(4)'
    return candidate(['Dom(f)=ℝ', 'parity(f,odd)', 'graph_symmetry(f,axis,1)', 'f(1)=1'], goal=goal,
                     text=r'已知函数 $f(x)$ 定义在 $\mathbf R$ 上，是奇函数，且图像关于直线 $x=1$ 对称，$f(1)=1$，求 $'+target+'$ 的值。')


@pytest.mark.parametrize('facts,expression,answer', [
    (['graph_symmetry(f,axis,2)', 'f(1)=3'], 'f(3)', 3),
    (['graph_symmetry(f,axis,2)', 'f(1)=3'], 'f(2)', None),
    (['graph_symmetry(f,axis,2)', 'f(1)=3'], 'f(0)', None),
    (['graph_symmetry(f,center,1,2)', 'f(0)=5'], 'f(2)', -1),
    (['graph_symmetry(f,center,1,2)'], 'f(1)', 2),
    (['graph_symmetry(f,center,1,2)'], 'f(0)+f(2)', 4),
    (['graph_symmetry(f,axis,0)', 'graph_symmetry(f,axis,3)', 'f(1)=7'], 'f(13)', 7),
    (['graph_symmetry(f,axis,0)', 'graph_symmetry(f,axis,3)', 'f(1)=7'], 'f(-11)', 7),
    (['graph_symmetry(f,center,0,0)', 'graph_symmetry(f,center,1,2)'], 'f(6)', 12),
    (['graph_symmetry(f,center,0,0)', 'graph_symmetry(f,center,1,2)'], 'f(-6)', -12),
    (['graph_symmetry(f,axis,1)', 'graph_symmetry(f,center,1,2)'], 'f(27)', 2),
    (['graph_symmetry(f,axis,1)', 'graph_symmetry(f,axis,1)'], 'f(27)', None),
    (['parity(f,odd)', 'graph_symmetry(f,axis,1/2)'], 'f(1)+f(2)+f(3)+f(4)+f(5)', 0),
    (['parity(f,odd)', 'graph_symmetry(f,axis,1/2)'], 'f(1/4)', None),
    (['∀t∈(0,1): f(-t)=f(t)+1', '∀t∈(-1,0): f(2-t)=f(t)+2', 'f(5/2)=3'], 'f(1/2)', 0),
])
def test_general_cases(facts, expression, answer):
    d = description(candidate(['Dom(f)=ℝ', *facts], expression))
    assert d['structure_supported'], d['reason']
    m = solve(d)
    assert m['proof']['value'] == answer
    assert verify(d, m)
    if answer is None:
        assert len(m['proof']['witnesses']) == 2


@pytest.mark.parametrize('sum_,answer', [(False, 0), (True, 1)])
def test_a10_source_and_answer(sum_, answer):
    d = description(a10(sum_), bound=True)
    assert d['structure_supported'], d['reason']
    m = solve(d)
    assert m['proof']['value'] == answer and verify(d, m)
    assert len(m['bases']) == 2
    if sum_:
        assert len(m['groups']) == 54


def test_standalone_axis_has_source_without_parity():
    d = description(candidate(), bound=True)
    assert d['structure_supported'], d['reason']
    assert solve(d)['proof']['value'] == 3


@pytest.mark.parametrize('facts,expr', [
    (['Dom(f)=[0,3]', 'graph_symmetry(f,axis,2)'], 'f(2)'),
    (['Dom(f)=ℝ', 'graph_symmetry(f,center,1,2)', 'graph_symmetry(f,center,1,3)'], 'f(2)'),
    (['Dom(f)=[-3,3]', 'graph_symmetry(f,axis,0)', 'graph_symmetry(f,axis,3)'], 'f(2)'),
    (['Dom(f)=ℝ', '∀t∈[-1,1]: f(-t)=f(t)+1'], 'f(2)'),
    (['Dom(f)=ℝ', 'graph_symmetry(f,axis,0)', 'f(1)=1', 'f(-1)=2'], 'f(1)'),
    (['Dom(f)=ℝ∖{1}', 'graph_symmetry(f,center,1,2)'], 'f(1)'),
])
def test_inconsistent_or_undefined_never_solves(facts, expr):
    d = description(candidate(facts, expr))
    if d['structure_supported']:
        with pytest.raises(ValueError):
            solve(d)
    else:
        assert d['reason']


def test_excluded_center_does_not_force_an_unrelated_value():
    d = description(candidate(['Dom(f)=ℝ∖{1}', 'graph_symmetry(f,center,1,2)'], 'f(2)'))
    m = solve(d)
    assert m['proof']['value'] is None and verify(d, m)


def test_local_scope_not_promoted_to_whole_graph():
    d = description(candidate(['Dom(f)=ℝ', '∀t∈[0,1]: f(2-t)=f(t)', 'f(0)=3'], 'f(4)'))
    m = solve(d)
    assert m['proof']['value'] is None and verify(d, m)


@pytest.mark.parametrize('mutate', [
    lambda m: m['proof'].update(value=5),
    lambda m: m['maps'][0].update(offset=5),
    lambda m: m['edges'][0].update(scope=sp.Interval(0, 1)),
    lambda m: m['groups'].pop(),
    lambda m: m['groups'].append(deepcopy(m['groups'][0])),
    lambda m: m['extension'].update(step=8),
])
def test_tampered_certificates_rejected(mutate):
    d = description(a10(True))
    m = solve(d)
    mutate(m)
    assert not verify(d, m)


@pytest.mark.parametrize('replace', ['不关于直线', '是否关于直线', '可能关于直线', '并非关于直线', '未必关于直线'])
def test_negated_or_questioned_graph_fact_not_admitted(replace):
    v = candidate();v['original_text'] = v['original_text'].replace('关于直线', replace)
    d = description(v, bound=True)
    assert not d['structure_supported'] and d['reason'] == 'symmetry.source_not_bound'


@pytest.mark.parametrize('expression,answer', [
    ('f(1)+f(-1)+f(1)', 1),
    ('f(-5)+2*f(3)', -3),
    ('f(1)-f(1)', 0),
])
def test_repeated_and_cancelled_terms_keep_their_multiplicity(expression, answer):
    v = a10(); v['root']['goals'] = [{'kind': 'find_value', 'expression': expression}]
    d = description(v)
    assert solve(d)['proof']['value'] == answer


@pytest.mark.parametrize('expression,lower,upper,answer', [
    ('f(k)', 1, 6, 1), ('f(2*k+1)', 0, 1, 0), ('f(k)', -3, 2, 1),
    ('f(k)+f(k)', 1, 6, 2), ('f(k)', 1, 4096, 0),
])
def test_indexed_sums_keep_steps_negative_indices_and_remainders(expression, lower, upper, answer):
    v = a10(True)
    v['root']['goals'][0]['terms'] = [{'expression': expression, 'index': 'k', 'lower': lower, 'upper': upper}]
    d = description(v)
    m = solve(d)
    assert m['proof']['value'] == answer and len(m['groups']) == upper-lower+1
    assert verify(d, m)


@pytest.mark.parametrize('target,extra', [
    ('f(0)-f(0)', []), ('0*f(0)', []), ('f(1)', ['f(0)=f(0)']),
])
def test_cancellation_does_not_make_an_undefined_call_legal(target, extra):
    d = description(candidate(['Dom(f)=ℝ∖{0}', 'graph_symmetry(f,axis,0)', *extra], target))
    if d['structure_supported']:
        with pytest.raises(ValueError, match='symmetry.input_outside_domain'):
            solve(d)
    else:
        assert d['reason'] == 'symmetry.input_outside_domain'


@pytest.mark.parametrize('facts,expression,answer', [
    (['graph_symmetry(f,axis,-1/2)', 'f(-2)=5'], 'f(1)', 5),
    (['graph_symmetry(f,axis,1)', 'graph_symmetry(f,center,0,3)'], 'f(2)+f(0)', 6),
    (['graph_symmetry(f,center,0,3)', 'graph_symmetry(f,axis,1)'], 'f(2)+f(0)', 6),
    (['graph_symmetry(f,axis,3)', 'graph_symmetry(f,axis,0)', 'f(1)=7'], 'f(-11)', 7),
])
def test_rational_centers_order_and_nonzero_reflection_constants(facts, expression, answer):
    d = description(candidate(['Dom(f)=ℝ', *facts], expression))
    m = solve(d)
    assert m['proof']['value'] == answer and verify(d, m)


def test_verification_does_not_call_either_production_solver(monkeypatch):
    from shuxueshuo_server.graph_lesson import symmetry_linear, symmetry_relation_math
    d = description(a10(True)); m = solve(d)
    def forbidden(*_args, **_kwargs):
        pytest.fail('independent verification must not solve for the target')
    monkeypatch.setattr(symmetry_relation_math, 'solve', forbidden)
    monkeypatch.setattr(symmetry_linear, 'solve_linear', forbidden)
    assert verify(d, m)
    m['proof']['multipliers'][0] += 1
    assert not verify(d, m)


def test_local_certificate_binds_reverse_direction_and_source():
    d = description(candidate(['Dom(f)=ℝ', '∀t∈(0,1): f(-t)=f(t)+1', 'f(-1/2)=3'], 'f(1/2)'))
    m = solve(d)
    assert m['proof']['value'] == 2 and verify(d, m)
    row = next(r for r in m['maps'] if r['path'])
    row['path'][0]['direction'] *= -1
    assert not verify(d, m)


@pytest.mark.parametrize('value', [sp.nan, sp.oo, sp.I, True, 'nan'])
def test_nonuniqueness_requires_real_exact_witnesses(value):
    d = description(candidate(expression='f(0)'))
    m = solve(d)
    assert m['proof']['status'] == 'underdetermined'
    m['proof']['witnesses'][0][-1] = value
    assert not verify(d, m)


@pytest.mark.parametrize('domain', ['[-2,-1]∪[1,2]', '{-2,-1,1,2}', 'ℝ∖{-2,2}'])
def test_exact_domains_keep_holes_and_isolated_points(domain):
    d = description(candidate(['Dom(f)='+domain, 'graph_symmetry(f,axis,0)', 'f(1)=4'], 'f(-1)'))
    m = solve(d)
    assert m['proof']['value'] == 4 and verify(d, m)


@pytest.mark.parametrize('domain', ['[-2,2)', '[0,0]', 'ℝ∖{2}'])
def test_domain_reflection_rejects_open_end_or_missing_partner(domain):
    d = description(candidate(['Dom(f)='+domain, 'graph_symmetry(f,axis,0)'], 'f(1)'))
    assert not d['structure_supported']


@pytest.mark.parametrize('changed', [
    '是否有 $f(1)=3$', '不能确定 $f(1)=3$', '$f(1)=3$ 不成立',
])
def test_numeric_conditions_must_be_assertions(changed):
    v = candidate(); v['original_text'] = v['original_text'].replace('$f(1)=3$', changed)
    assert not description(v, bound=True)['structure_supported']


def test_function_and_dummy_variable_rename_bind_to_source():
    v = a10()
    v['original_text'] = v['original_text'].replace('f(', 'h(').replace('h(x)', 'h(t)')
    v['root']['facts'] = [s.replace('(f', '(h').replace('f(', 'h(') for s in v['root']['facts']]
    v['root']['goals'][0]['expression'] = v['root']['goals'][0]['expression'].replace('f(', 'h(')
    d = description(v, bound=True)
    assert d['structure_supported'], d['reason']
    assert solve(d)['proof']['value'] == 0


def test_center_and_quantified_source_paths():
    v = candidate(['Dom(f)=ℝ', 'graph_symmetry(f,center,1,2)', 'f(0)=5'], 'f(2)',
                  text=r'已知函数 $f(x)$ 定义域为 $\mathbb R$，图像关于点 $(1,2)$ 中心对称，且 $f(0)=5$，求 $f(2)$ 的值。')
    d = description(v, bound=True)
    assert d['structure_supported'], d['reason']
    assert solve(d)['proof']['value'] == -1
    v = candidate(['Dom(f)=ℝ', '∀t∈Dom(f): f(2-t)=f(t)', 'f(0)=5'], 'f(2)',
                  text=r'已知函数 $f(x)$ 定义域为 $\mathbb R$，对任意 $t\in\mathbb R$，有 $f(2-t)=f(t)$，且 $f(0)=5$，求 $f(2)$ 的值。')
    d = description(v, bound=True)
    assert d['structure_supported'], d['reason']
    assert solve(d)['proof']['value'] == 5


def test_conflicting_known_values_and_sum_budget_never_publish_answers():
    v = a10(); v['root']['facts'].append('f(3)=2')
    with pytest.raises(ValueError, match='symmetry.conditions_inconsistent'):
        solve(description(v))
    v = a10(True); v['root']['goals'][0]['terms'][0]['upper'] = 4097
    d = description(v)
    assert not d['structure_supported'] and d['reason'] == 'symmetry.sum_budget'


@pytest.mark.parametrize('fact', ['graph_symmetry(f,axis)', 'graph_symmetry(f,axis,1,2)',
                                'graph_symmetry(f,center,1)', 'graph_symmetry(f,unknown,1)',
                                'graph_symmetry(f,center,1,ℝ)'])
def test_graph_fact_notation_has_strict_arity_and_coordinate_types(fact):
    from shuxueshuo_server.graph_lesson.stage_one.extraction import validate_candidate
    assert not validate_candidate(candidate(['Dom(f)=ℝ', fact]))['contract_valid']


def test_sum_board_keeps_remainder_visible_without_revealing_the_total():
    from shuxueshuo_server.graph_lesson.stage_three.symmetry_relation_presentation import (
        phase_views,
    )
    d = description(a10(True))
    cards = phase_views({'description': d, 'phase': 'conclude'})
    grouping, answer = cards
    assert [line['label'] for line in grouping['condition_number_lines']] == ['每组 4 项，共 13 组', '剩余 2 项']
    assert [p['at'] for p in grouping['condition_number_lines'][1]['points']] == [53, 54]
    assert grouping['interaction']['type'] == 'read'
    assert answer['interaction']['type'] == 'choice'


@pytest.mark.parametrize('equation', [
    'f(2-t)=f(t)+t/t-1',
    'f(2-t)=f(t)+(t-1)/(t-1)-1',
    'f(2-t)=f(t)+0*(1/t)',
    'f(2-t+(t-1)/(t-1)-1)=f(t)',
    'f(2-t)=f(t)+sqrt(t)-sqrt(t)',
    'f(2-t+0*sqrt(t))=f(t)',
    'f(2-t)=(t/t)*f(t)',
])
def test_quantified_original_expressions_must_be_defined_before_cancellation(equation):
    d = description(candidate(['Dom(f)=ℝ', '∀t∈ℝ: '+equation, 'f(0)=5'], 'f(2)'))
    assert not d['structure_supported'] and d['reason'] == 'symmetry.undefined_on_scope'
    valid = description(candidate(['Dom(f)=ℝ', '∀t∈ℝ: f(2-t)=f(t)', 'f(0)=5'], 'f(2)'))
    assert not verify(d, solve(valid))


@pytest.mark.parametrize('domain,scope,equation,given,goal,answer', [
    ('ℝ∖{1}', 'ℝ∖{1}', 'f(2-t)=f(t)+(t-1)/(t-1)-1', 'f(0)=5', 'f(2)', 5),
    ('ℝ', '[0,1]', 'f(2-t)=f(t)+sqrt(t)-sqrt(t)', 'f(0)=5', 'f(2)', 5),
    ('ℝ', 'ℝ', 'f(2*t+1)=f(3-2*t)', 'f(0)=5', 'f(4)', 5),
    ('ℝ', 'ℝ', 'f(1-t/2)+f(3+t/2)=8', 'f(0)=5', 'f(4)', 3),
    ('[0,4]', '[0,1]', 'f(2*t)=f(4-2*t)', 'f(1)=5', 'f(3)', 5),
    ('(0,4)', '(0,1)', 'f(2*t)=f(4-2*t)+1', 'f(1)=5', 'f(3)', 4),
    ('ℝ∖{2}', 'ℝ∖{1/2}', 'f(2*t+1)=f(3-2*t)', 'f(0)=5', 'f(4)', 5),
])
def test_rational_affine_reflections_keep_exact_scope(domain, scope, equation, given, goal, answer):
    d = description(candidate(['Dom(f)='+domain, f'∀t∈{scope}: '+equation, given], goal))
    assert d['structure_supported'], d['reason']
    m = solve(d)
    assert m['proof']['value'] == answer and verify(d, m)


@pytest.mark.parametrize('domain,scope,equation', [
    ('ℝ', 'ℝ', 'f(2*t+1)=f(3-t)'),
    ('ℝ', 'ℝ', 'f(1)=f(3-2*t)'),
    ('(0,4)', '[0,1]', 'f(2*t)=f(4-2*t)'),
    ('ℝ∖{2}', 'ℝ', 'f(2*t+1)=f(3-2*t)'),
    ('ℝ', 'ℝ', 'f(abs(t))=f(-t)'),
    ('ℝ', 'ℝ', 'f(sqrt(t^2))=f(-t)'),
    ('ℝ', 'ℝ∖{0}', 'f(1/t)=f(-t)'),
])
def test_affine_admission_requires_opposite_nonzero_slopes_and_legal_inputs(domain, scope, equation):
    d = description(candidate(['Dom(f)='+domain, f'∀t∈{scope}: '+equation], 'f(1)'))
    assert not d['structure_supported']


def two_axes(statement):
    return candidate(['Dom(f)=ℝ', 'graph_symmetry(f,axis,0)', 'graph_symmetry(f,axis,3)', 'f(1)=7'], 'f(13)',
                     text=r'已知函数 $f(x)$ 定义域为 $\mathbb R$，'+statement+r'，且 $f(1)=7$，求 $f(13)$ 的值。')


@pytest.mark.parametrize('statement', [
    r'图像关于直线 $x=0$ 和 $x=3$ 对称',
    r'图像关于直线 $x=0,x=3$ 都对称',
    r'图像的对称轴为 $x=0$ 和 $x=3$',
    r'对任意 $t\in\mathbb R$，有 $f(-t)=f(t)$；对任意 $t\in\mathbb R$，有 $f(6-t)=f(t)$',
    r'对任意 $t\in\mathbb R$，有 $f(-t)=f(t)$，对任意 $t\in\mathbb R$，有 $f(6-t)=f(t)$',
    r'对任意 $t\in\mathbb R$，有 $f(-t)=f(t)$ 且 $f(6-t)=f(t)$',
    r'$\forall t\in\mathbb R,f(-t)=f(t)$；$\forall t\in\mathbb R,f(6-t)=f(t)$',
])
def test_grouped_graph_statements_and_owned_quantifiers(statement):
    v = two_axes(statement)
    if '任意' in statement or r'\forall' in statement:
        v['root']['facts'][1:3] = ['∀t∈ℝ: f(-t)=f(t)', '∀t∈ℝ: f(6-t)=f(t)']
    d = description(v, bound=True)
    assert d['structure_supported'], d['reason']
    assert solve(d)['proof']['value'] == 7


@pytest.mark.parametrize('statement,fact,answer', [
    (r'其图像的对称轴为 $x=2$', 'graph_symmetry(f,axis,2)', 5),
    (r'其图像的对称中心是 $(2,3)$', 'graph_symmetry(f,center,2,3)', 1),
    (r'对任意 $t\in\mathbb R$，有 $f(2t+1)=f(3-2t)$', '∀t∈ℝ: f(2*t+1)=f(3-2*t)', 5),
])
def test_nominal_graph_and_affine_source_wordings(statement, fact, answer):
    v = candidate(['Dom(f)=ℝ', fact, 'f(0)=5'], 'f(4)',
                  text=r'已知函数 $f(x)$ 定义域为 $\mathbb R$，'+statement+r'，且 $f(0)=5$，求 $f(4)$ 的值。')
    d = description(v, bound=True)
    assert d['structure_supported'], d['reason']
    assert solve(d)['proof']['value'] == answer


@pytest.mark.parametrize('statement', [
    r'并非对任意 $t\in\mathbb R$，都有 $f(2-t)=f(t)$',
    r'不是对所有 $t\in\mathbb R$ 都有 $f(2-t)=f(t)$',
    r'对任意 $t\in\mathbb R$，都有 $f(2-t)=f(t)$ 吗？',
    r'对任意 $t\in[0,1]$，有 $f(2-t)=f(t)$',
])
def test_quantified_claim_polarity_and_scope_are_not_discarded(statement):
    v = candidate(['Dom(f)=ℝ', '∀t∈ℝ: f(2-t)=f(t)', 'f(0)=5'], 'f(2)',
                  text=r'已知函数 $f(x)$ 定义域为 $\mathbb R$，'+statement+r'，且 $f(0)=5$，求 $f(2)$ 的值。')
    assert not description(v, bound=True)['structure_supported']


@pytest.mark.parametrize('replacement', [
    r'对任意 $t\in[0,1]$，有 $f(6-t)=f(t)$',
    r'并非对任意 $t\in\mathbb R$，有 $f(6-t)=f(t)$',
    r'对任意 $u\in\mathbb R$，有 $f(6-t)=f(t)$',
])
@pytest.mark.parametrize('separator', ['；', '，'])
def test_second_relation_cannot_borrow_first_quantifier(replacement, separator):
    v = two_axes(r'对任意 $t\in\mathbb R$，有 $f(-t)=f(t)$'+separator+replacement)
    v['root']['facts'][1:3] = ['∀t∈ℝ: f(-t)=f(t)', '∀t∈ℝ: f(6-t)=f(t)']
    assert not description(v, bound=True)['structure_supported']


@pytest.mark.parametrize('statement', [
    r'图像关于点 $(0,0)$ 和 $(1,2)$ 中心对称',
    r'图像的对称中心分别为 $(0,0)$、$(1,2)$',
])
def test_grouped_centers_keep_their_own_coordinate_pairs(statement):
    v = candidate(['Dom(f)=ℝ', 'graph_symmetry(f,center,0,0)', 'graph_symmetry(f,center,1,2)'], 'f(6)',
                  text=r'已知函数 $f(x)$ 定义域为 $\mathbb R$，'+statement+r'，求 $f(6)$ 的值。')
    d = description(v, bound=True)
    assert d['structure_supported'], d['reason']
    assert solve(d)['proof']['value'] == 12


@pytest.mark.parametrize('old,new', [
    ('对称，', '对称吗？'),
    ('对称，', '对称，对吗？'),
    ('$f(1)=3$', '“$f(1)=3$”不成立'),
    ('$f(1)=3$', '“$f(1)=3$”，这个结论，不成立'),
    ('图像关于直线 $x=2$ 对称', '图像的对称轴不是 $x=2$'),
    ('图像关于直线 $x=2$ 对称', '图像仅在区间 $[0,4]$ 上关于直线 $x=2$ 对称'),
])
def test_questions_quoted_negations_and_local_graphs_are_not_facts(old, new):
    v = candidate(); v['original_text'] = v['original_text'].replace(old, new)
    assert not description(v, bound=True)['structure_supported']


@pytest.mark.parametrize('old,new', [
    (r'定义在 $\mathbf R$ 上，', r'定义域可能为 $\mathbf R$；'),
    ('是奇函数，', '是奇函数吗？'),
])
def test_domain_and_parity_assertions_keep_polarity_across_sentences(old, new):
    v = a10(); v['original_text'] = v['original_text'].replace(old, new)
    assert not description(v, bound=True)['structure_supported']


def compound_sum(upper=10):
    v = a10(True)
    v['root']['goals'][0]['terms'][0].update(expression='f(k)+1', upper=upper)
    v['original_text'] = v['original_text'].replace(r'f(1)+f(2)+\cdots+f(54)',
                                                   rf'\sum_{{k=1}}^{{{upper}}}\left(f(k)+1\right)')
    return v


def test_compound_summand_scope_is_preserved_in_reading_choices_and_grouping():
    from shuxueshuo_server.graph_lesson.stage_three.symmetry_relation_presentation import (
        phase_views,
        target_math,
    )
    d = description(compound_sum(), bound=True)
    assert d['structure_supported'], d['reason']
    assert solve(d)['proof']['value'] == 11
    formula = r'\sum_{k=1}^{10}\left(f(k)+1\right)'
    assert target_math(d) == formula
    cards = phase_views({'description': d, 'phase': 'conclude'})
    assert len(cards) == 2
    def strings(value):
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            return [s for child in value.values() for s in strings(child)]
        if isinstance(value, list):
            return [s for child in value for s in strings(child)]
        return []
    for card in cards:
        rendered = strings(card)
        assert any(formula in s for s in rendered)
        assert not any(r'\sum_{k=1}^{10}f(k)+1' in s for s in rendered)


@pytest.mark.parametrize('expression,answer', [('f(k)+1', 8), ('f(k)-1', -4)])
def test_compound_summand_and_separate_sum_blocks_keep_distinct_scopes(expression, answer):
    from shuxueshuo_server.graph_lesson.stage_three.symmetry_relation_presentation import (
        target_math,
    )
    v = a10(True)
    v['root']['goals'][0]['terms'] = [
        {'expression': expression, 'index': 'k', 'lower': 1, 'upper': 6},
        {'expression': 'f(j)', 'index': 'j', 'lower': -1, 'upper': 2},
        {'expression': 'f(1)'},
    ]
    printed = rf'\sum_{{k=1}}^{{6}}({expression})+\sum_{{j=-1}}^{{2}}f(j)+f(1)'
    v['original_text'] = v['original_text'].replace(r'f(1)+f(2)+\cdots+f(54)', printed)
    d = description(v, bound=True)
    assert d['structure_supported'], d['reason']
    m = solve(d)
    assert m['proof']['value'] == answer and verify(d, m)
    assert target_math(d) == rf'\sum_{{k=1}}^{{6}}\left({expression}\right)+\sum_{{j=-1}}^{{2}}f(j)+f(1)'


@pytest.mark.parametrize('expression,printed,answer', [
    ('f(3)*(-2)', r'f(3)\cdot \left(-2\right)', -6),
    ('(f(3)+1)*(-2)', r'\left(f(3)+1\right)\cdot \left(-2\right)', -8),
])
def test_negative_multipliers_remain_products_in_the_printed_target(expression, printed, answer):
    from shuxueshuo_server.graph_lesson.stage_three.symmetry_relation_presentation import (
        target_math,
    )
    d = description(candidate(expression=expression))
    assert solve(d)['proof']['value'] == answer
    assert target_math(d) == printed


def test_quantified_source_keeps_its_original_variable_and_negative_multiplier():
    from shuxueshuo_server.graph_lesson.stage_three.symmetry_relation_presentation import (
        source_math,
    )
    d = description(candidate(['Dom(f)=ℝ', '∀t∈ℝ: f(2-t)=f(t)*(-1)+4', 'f(0)=5'], 'f(2)'))
    assert solve(d)['proof']['value'] == -1
    assert source_math(d)[1] == r'f(2-t)=f(t)\cdot \left(-1\right)+4\quad(t\in \mathbf{R})'
