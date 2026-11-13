"""FP-T4 R0: half-axis inequality solved on the printed range, mirrored by parity, verified per cell."""
import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.parity_inequality_math import describe, solve, verify
from shuxueshuo_server.graph_lesson.stage_three.context import build_context

TARGET = '/root/goals/0'
X = sp.Symbol('x', real=True)
A02 = (r'已知 $y=f(x)$ 是 $\mathbf R$ 上的偶函数，且当 $x\ge0$ 时，$f(x)=x^2-3x$，'
       r'则不等式 $f(x)\le0$ 的解集为____．')


def candidate(facts=('Dom(f)=ℝ', 'parity(f,even)'), rule='x^2-3*x', known='[0,∞)', expression='f(x)<=0',
              text=A02):
    return {'original_text': text, 'root': {'facts': list(facts), 'goals': [{
        'kind': 'find_range', 'function': 'f', 'variable': 'x', 'relation': f'f(x)={rule}',
        'relation_domain': known, 'expression': expression, 'symbol': 'x'}]}}


def described(value, *, bind=False):
    context = build_context(value, TARGET)
    return describe(context['goal'], context['goal_ast'], TARGET, context['entries'],
                    candidate=value if bind else None)


def test_a02_is_bound_and_routed_through_the_feature():
    context = build_context(candidate(), TARGET)
    desc = context['parity_inequality_goal']
    assert desc['structure_supported'], desc['reason']
    assert desc['property'] == 'even' and desc['operator'] == '<='
    model = solve(desc)
    assert model['known_solution'] == sp.Interval(0, 3)
    assert model['mirrored_solution'] == sp.Interval.Ropen(-3, 0)
    assert model['solution'] == sp.Interval(-3, 3) and verify(desc, model)


@pytest.mark.parametrize('facts,rule,known,expression,expected', [
    (('Dom(f)=ℝ', 'parity(f,odd)'), 'x', '[0,∞)', 'f(x)<=1', sp.Interval(-sp.oo, 1)),
    (('Dom(f)=ℝ', 'parity(f,odd)'), 'x+1', '(0,∞)', 'f(x)>0', sp.Interval.open(0, sp.oo)),
    (('parity(f,odd)',), 'x-1', '(0,∞)', 'f(x)<0',
     sp.Union(sp.Interval.open(-sp.oo, -1), sp.Interval.open(0, 1))),
    (('Dom(f)=ℝ', 'parity(f,even)'), 'x^2+x', '(-∞,0]', '0>f(x)',
     sp.Union(sp.Interval.open(-1, 0), sp.Interval.open(0, 1))),
])
def test_odd_flips_relation_and_zero_is_checked(facts, rule, known, expression, expected):
    desc = described(candidate(facts, rule, known, expression))
    assert desc['structure_supported'], desc['reason']
    model = solve(desc)
    assert model['solution'] == expected and verify(desc, model)


@pytest.mark.parametrize('facts', [('Dom(f)=ℝ', 'parity(f,odd)'), ('parity(f,odd)',)])
def test_mirror_card_keeps_open_origin_when_plotting_both_halves(facts):
    from shuxueshuo_server.graph_lesson.stage_three.interaction_graph_contract import validate_part_graphs
    from shuxueshuo_server.graph_lesson.stage_three.parity_inequality_presentation import compile_cards
    from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value

    desc = described(candidate(facts, 'x+1', '(0,∞)', 'f(x)>0'))
    assert desc['structure_supported'], desc['reason']
    result = compile_cards([{'values': encode_value({'description': desc, 'phase': 'mirror'})}], 'open-origin')
    validate_part_graphs(result['parts'])
    part, = result['parts']
    params = part['completion_graph']['params']
    assert params['interval'] == [None, None]
    assert [piece['interval'] for piece in params['segments']] == [[0, None], [None, 0]]
    assert all(piece['interval_closed'] == [False, False] for piece in params['segments'])


@pytest.mark.parametrize('facts,rule,known,expression,reason', [
    (('parity(f,odd)',), 'x-1', '(0,∞)', 'f(x)<=0', 'parity_ineq.domain_dependent_answer'),
    (('Dom(f)=ℝ', 'parity(f,even)'), 'x-1', '(0,∞)', 'f(x)<0', 'parity_ineq.zero_value_free'),
    (('Dom(f)=ℝ', 'parity(f,even)'), 'x^3', '[0,∞)', 'f(x)<1', 'parity_ineq.degree_budget'),
    (('Dom(f)=ℝ', 'parity(f,even)'), 'x', '[1,∞)', 'f(x)<2', 'parity_ineq.rule_not_covering_domain'),
    (('Dom(f)=(-3,3)', 'parity(f,odd)'), 'x^2-2', '[0,3)', 'f(x)>=0', 'parity_ext.overlap_conflict'),
])
def test_insufficient_or_conflicting_conditions_are_gaps(facts, rule, known, expression, reason):
    desc = described(candidate(facts, rule, known, expression))
    assert not desc['structure_supported'] and desc['reason'] == reason


@pytest.mark.parametrize('field,value', [
    ('solution', sp.Interval(0, 3)),
    ('solution', sp.Interval.open(-3, 3)),
    ('known_solution', sp.Interval.open(0, 3)),
    ('mirror_operator', '>='),
    ('sign', -1),
])
def test_verify_rejects_tampered_models(field, value):
    desc = described(candidate())
    assert not verify(desc, {**solve(desc), field: value})


@pytest.mark.parametrize('text,ok', [
    (A02, True),
    (A02.replace('$y=f(x)$', '$f(x)$'), True),
    (A02.replace('偶函数', '奇函数'), False),
    (A02.replace(r'f(x)\le0', r'f(x)<0'), False),
    (A02.replace(r'x\ge0', r'x>0'), False),
    (A02.replace(r'是 $\mathbf R$ 上的偶函数', '是偶函数'), False),
])
def test_source_binding_follows_the_printed_text(text, ok):
    desc = described(candidate(text=text), bind=True)
    assert desc['structure_supported'] is ok, desc['reason']
    if not ok:
        assert desc['reason'] == 'parity_ineq.source_not_bound'
