"""R2 original domains, mirror identities and complete parameter conditions."""
from copy import deepcopy

import pytest
import sympy as sp
from shuxueshuo_server.graph_lesson import parity_parameter_math as math
from shuxueshuo_server.graph_lesson import parity_parameter_original as original
from shuxueshuo_server.graph_lesson.stage_three.trajectory import (
    decode_value,
    encode_value,
)
from tests.solver.test_graph_parity_parameter import TARGET, candidate, description


@pytest.mark.parametrize('expr,prop,facts,answer', [
    ('(x^2-1)^2+m*x', 'even', (), sp.FiniteSet(0)),
    ('m*x^4+x^3', 'odd', (), sp.FiniteSet(0)),
    ('m*x^4', 'even', ('degree(f)=4',), sp.S.Reals-sp.FiniteSet(0)),
    ('(m^2-1)*x^4+m*x^3', 'odd', (), sp.FiniteSet(-1, 1)),
    ('m*x^4+1', 'odd', ('Dom(f)={-1,1}',), sp.FiniteSet(-1)),
    ('m*x', 'odd', ('degree(f)=4',), sp.S.EmptySet),
    ('m*x', 'odd', ('m^4<4',), sp.Interval.open(-sp.sqrt(2), sp.sqrt(2))),
    ('m*x', 'odd', ('m/m>0',), sp.S.Reals-sp.FiniteSet(0)),
    ('(x-m)/(x-m)', 'even', (), sp.FiniteSet(0)),
    ('(x^2-m^2)/(x^2-m^2)', 'even', (), sp.S.Reals),
    ('x/(m*x)', 'even', (), sp.S.Reals-sp.FiniteSet(0)),
    ('m*x/x', 'odd', (), sp.FiniteSet(0)),
    ('(x^2+m*x)/(x^2+1)', 'even', (), sp.FiniteSet(0)),
    ('m/(x^2-2)', 'even_only', (), sp.S.Reals-sp.FiniteSet(0)),
    ('(x-m)/(x-m)', 'even', ('Dom(f)=ℝ',), sp.S.EmptySet),
    ('m/x', 'odd', ('Dom(f)=[-1,1]',), sp.S.EmptySet),
    ('m/x', 'odd', ('defined_on(f,[0,1])',), sp.S.EmptySet),
    ('m/x', 'odd_only', ('m>0',), sp.Interval.open(0, sp.oo)),
    ('1/(x/(x-m))', 'even', (), sp.FiniteSet(0)),
    ('(x-m)^0', 'even', (), sp.FiniteSet(0)),
    ('m*abs(x)+x', 'odd', (), sp.FiniteSet(0)),
    ('abs(x+1)+m*abs(x-1)', 'even', (), sp.FiniteSet(1)),
    ('abs(x^2-2)+m*x', 'even', (), sp.FiniteSet(0)),
    ('piecewise(m*x^2,x<0,x^2,x>=0)', 'odd', (), sp.FiniteSet(-1)),
    ('piecewise(m*x^2,x<0,x^2,x>=0)', 'even', (), sp.FiniteSet(1)),
    ('piecewise(m*x,x∈(-∞,0),x,x∈[0,∞))', 'odd', (), sp.FiniteSet(1)),
    ('piecewise(-1,x<0,m,x=0,1,x>0)', 'odd', (), sp.FiniteSet(0)),
    ('piecewise(m/x,x<0,1/x,x>0)', 'odd', (), sp.FiniteSet(1)),
    ('piecewise(m,x<0,1,x>0)', 'odd', (), sp.FiniteSet(-1)),
    ('piecewise(m,x<0,1,x>0)', 'odd', ('Dom(f)=ℝ',), sp.S.EmptySet),
    ('piecewise(m*x,x<-2,m*x,x∈[-2,-1),m*x,x∈[-1,0),m*x,x∈[0,1),m*x,x∈[1,2),m*x,x>=2)', 'odd', (), sp.S.Reals),
    ('sqrt(m-x^2)', 'even', (), sp.Interval(0, sp.oo)),
    ('sqrt(m-x^2)', 'odd', (), sp.FiniteSet(0)),
    ('sqrt(m-x^2)', 'even_only', (), sp.Interval.open(0, sp.oo)),
    ('sqrt(x^2+m)', 'even', (), sp.S.Reals),
    ('sqrt(x^2+m)', 'even', ('Dom(f)=ℝ',), sp.Interval(0, sp.oo)),
    ('sqrt(m*x^2)', 'both', (), sp.Interval(-sp.oo, 0)),
    ('sqrt(m*x^2)', 'odd', ('Dom(f)=ℝ',), sp.FiniteSet(0)),
    ('sqrt(m*x^2)', 'odd_only', (), sp.S.EmptySet),
    ('sqrt((m-1)*x^2+m+1)', 'even', (), sp.Interval(-1, sp.oo)),
    ('sqrt((m-1)*x^2+m+1)', 'odd', (), sp.FiniteSet(-1)),
    ('sqrt(0*x^2+m)', 'odd', (), sp.FiniteSet(0)),
])
def test_original_domain_and_complete_mirrored_relations(expr, prop, facts, answer):
    desc = description(candidate(expr, prop, facts=facts, goal_kind='find_range'))
    result = math.solve(desc)
    assert result['feasible_set'] == answer
    assert math.verify(desc, result)
    assert math.verify(desc, decode_value(encode_value(result)))


def test_opt_in_quartic_skill_keeps_old_quadratic_contract():
    from shuxueshuo_server.graph_lesson.function_coefficients import (
        compare_coefficients,
        compare_quartic_coefficients,
    )
    d = description(candidate('(x^2-1)^2+m*x'))
    inputs = math.identities(d)
    with pytest.raises(ValueError, match='unsupported_polynomial'):
        compare_coefficients(*inputs)
    assert compare_quartic_coefficients(*inputs)['equations']
    with pytest.raises(ValueError, match='equality_required'):
        compare_quartic_coefficients([sp.true], inputs[1], inputs[2], sp.S.Reals)


@pytest.mark.parametrize('expr', ['(x^2-m^2)/(x^2-m^2)', 'piecewise(-1,x<0,m,x=0,1,x>0)', 'sqrt(x^2+m)'])
def test_verifier_does_not_call_production_solver_and_rejects_tampering(expr, monkeypatch):
    d = description(candidate(expr))
    model = math.solve(d)
    def forbidden(*args, **kwargs):
        pytest.fail('verification invoked a production solver')
    monkeypatch.setattr(math, 'solve', forbidden)
    monkeypatch.setattr(math, 'condition_set', forbidden)
    monkeypatch.setattr(original, 'solve', forbidden)
    monkeypatch.setattr(original, 'compare', forbidden)
    assert math.verify(d, model)
    corrupted = deepcopy(model)
    proof = corrupted['comparison']
    proof['cases' if proof['kind'] == 'radical' else 'rows'].pop()
    assert not math.verify(d, corrupted)
    corrupted = deepcopy(model)
    corrupted['feasible_set'] = model['feasible_set'] ^ sp.FiniteSet(0)
    assert not math.verify(d, corrupted)


@pytest.mark.parametrize('expr,facts', [
    ('m*abs(x-m)', ()), ('sqrt(x^2+m*x)', ()), ('sqrt(m^2*x^2+1)', ()),
    ('1/(x^2-m)', ()), ('m*x^5', ()), ('a*x^4+m*x', ()),
    ('piecewise(m*x,x<m,x^2,x>=m)', ()),
    ('piecewise(m,x<=0,1,x>=0)', ()), ('sqrt(x^2+m)', ('Dom(f)=[-1,1]',)),
    ('m/(x^4-2)', ()), ('1/(x-m)/(x-m-1)/(x-m-2)', ()),
])
def test_unsupported_structure_is_not_a_mathematical_empty_set(expr, facts):
    from shuxueshuo_server.graph_lesson.stage_three.context import build_context
    d = build_context(candidate(expr, facts=facts), TARGET)['parity_parameter_goal']
    assert not d['structure_supported'], d


def test_parameter_poles_and_quartic_roots_are_not_lost():
    d = description(candidate('m/x', 'odd', facts=('(m^2-1)/(m^2-1)>0', 'm^4<=4'), goal_kind='find_range'))
    result = math.solve(d)
    assert result['feasible_set'] == sp.Interval(-sp.sqrt(2), sp.sqrt(2))-sp.FiniteSet(-1, 1)
    assert math.verify(d, result)


@pytest.mark.parametrize('expr,facts,value,domain', [
    ('piecewise(m,x<0,1,x>0)', (), 0, sp.S.Reals-sp.FiniteSet(0)),
    ('piecewise(m/(x-1),x<0,-1/(x+1),x>=0)', (), 1, sp.S.Reals),
    ('piecewise(m/(x-1),x<0,1/(x-1),x>=0)', (), 1, sp.S.Reals-sp.FiniteSet(1)),
    ('x/(m*x)', (), 0, sp.S.EmptySet),
    ('x/(m*x)', (), 1, sp.S.Reals-sp.FiniteSet(0)),
    ('m/x', ('Dom(f)={-1,1}',), 0, sp.FiniteSet(-1, 1)),
    ('sqrt(m*x^2)', ('Dom(f)=ℝ',), 0, sp.S.Reals),
    ('sqrt(x^2+m)', (), -2, sp.Interval(-sp.oo, -sp.sqrt(2)) | sp.Interval(sp.sqrt(2), sp.oo)),
])
def test_domain_submethod_preserves_original_scope_and_parameter_degeneracy(expr, facts, value, domain):
    d = description(candidate(expr, facts=facts, goal_kind='find_range'))
    proof = original.solve_domain(d)
    assert original.verify_domain(d, proof)
    assert original.verify_domain(d, decode_value(encode_value(proof)))
    assert original.domain_at(d, proof, sp.sympify(value)) == domain


@pytest.mark.parametrize('expr,facts', [
    ('m/x', ('Dom(f)=[-1,1]',)),
    ('piecewise(m,x<0,1,x>0)', ('Dom(f)=ℝ',)),
    ('sqrt(m*x^2)', ('Dom(f)=ℝ',)),
])
def test_domain_submethod_rejects_illegal_declared_domains(expr, facts):
    d = description(candidate(expr, facts=facts, goal_kind='find_range'))
    proof = original.solve_domain(d)
    with pytest.raises(ValueError, match='invalid_declared_domain'):
        original.domain_at(d, proof, sp.S.NegativeOne)


@pytest.mark.parametrize('expr', ['piecewise(m/(x-1),x<0,-1/(x+1),x>=0)', 'sqrt(m*x^2)'])
def test_domain_submethod_certificate_is_checked_against_original_source(expr, monkeypatch):
    from shuxueshuo_server.graph_lesson.stage_three.capabilities import LocalCheckFailed
    from shuxueshuo_server.graph_lesson.stage_three.parity_parameter_runtime import (
        solve_original_domain,
    )
    d = description(candidate(expr, goal_kind='find_range'))
    proof = original.solve_domain(d)
    def forbidden(*args, **kwargs):
        pytest.fail('domain verification invoked a production solver')
    monkeypatch.setattr(original, 'solve_domain', forbidden)
    assert original.verify_domain(d, proof)
    corrupted = deepcopy(proof)
    if corrupted['kind'] == 'radical':
        corrupted['cases'].pop()
    else:
        corrupted['rows'][0]['input_atoms'][0]['member'] = False
    assert not original.verify_domain(d, corrupted)
    monkeypatch.setattr(original, 'solve_domain', lambda _: corrupted)
    with pytest.raises(LocalCheckFailed, match='original_domain_certificate_failed'):
        solve_original_domain(d)
