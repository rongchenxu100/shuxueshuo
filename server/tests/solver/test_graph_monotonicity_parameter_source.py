"""Source forms exposed by live T4 photos; keep all quantifiers and guards."""

from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.monotonicity_parameter_math import (
    describe,
    routed_description,
    solve,
    verify,
)
from shuxueshuo_server.graph_lesson.stage_one.repair_authority import repair_violations
from shuxueshuo_server.graph_lesson.stage_one.runner import candidate_features
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.problem_understanding.notation_parser import NotationError, parse

PAIR = '(f(s)-f(t))/(s-t)<0'
GOAL = {'kind': 'find_range', 'symbol': 'a'}
DEFINITION = {'source_ref': '/root/definitions/0', 'expression': 'f(x)=a*x^2-2*x+3'}


def entries(condition):
    return [DEFINITION, {'source_ref': '/root/facts/0', 'expression': condition}]


@pytest.mark.parametrize('condition', [
    f'∀s,t∈[2,+∞): s≠t → {PAIR}',
    f'∀s,t∈[2,+∞), s≠t: {PAIR}',
    f'∀s∈[2,+∞):∀t∈[2,+∞):s=t ∨ {PAIR}',
    f'∀s∈[2,+∞):∀t∈[2,+∞):{PAIR} ∨ t=s',
    f'∀s∈[2,+∞):∀t∈[2,+∞)∖{{s}}:{PAIR}',
    '∀s,t∈[2,+∞),s≠t:(f(t)-f(s))*(s-t)>0',
])
def test_code_derives_requirement_from_original_two_point_condition(condition):
    candidate = {'original_text': 'source', 'root': {
        'definitions': [DEFINITION['expression']], 'facts': [condition], 'goals': [deepcopy(GOAL)]}}
    before = deepcopy(candidate)
    assert candidate_features(candidate)['ok']
    d = build_context(candidate, '/root/goals/0')['mono_parameter_goal']
    assert d['structure_supported'], d['reason']
    model = solve(d)
    assert model['feasible_set'] == sp.Interval(-sp.oo, 0) and verify(d, model)
    assert candidate == before and d['source'] == GOAL
    assert d['requirement']['input_domain'] == '[2,+∞)'


@pytest.mark.parametrize('condition', [
    f'∃s∈[2,+∞):∀t∈[2,+∞):s≠t → {PAIR}',
    f'∀s∈[2,+∞):∀t∈[3,+∞):s≠t → {PAIR}',
    f'∀s,t∈[2,+∞):{PAIR}',
    f'∀s,t∈[2,+∞):s≠t ∧ {PAIR}',
    f'∀s,t∈[2,+∞):s≠u → {PAIR}',
    '∀s,t∈[2,+∞):s≠t → (f(s)-f(u))/(s-u)<0',
    '∀s,t∈[2,+∞):s≠t → (f(s)-f(t))/(s-t)<=0',
    f'∀s∈[2,+∞):∀t∈[2,+∞)∖{{s,3}}:{PAIR}',
])
def test_partial_or_unguarded_conditions_do_not_become_strict_monotonicity(condition):
    assert routed_description(GOAL, '/root/goals/0', entries(condition)) is None


def test_additional_or_conflicting_conditions_are_not_discarded():
    sources = entries(f'∀s,t∈[2,+∞),s≠t:{PAIR}')
    sources.append({'source_ref': '/root/facts/1', 'expression': 'a>=-1'})
    d = describe(GOAL, '/root/goals/0', sources)
    assert solve(d)['feasible_set'] == sp.Interval(-1, 0)
    sources[-1]['expression'] = '∀s,t∈[2,+∞),s≠t:(f(s)-f(t))/(s-t)>0'
    d = describe(GOAL, '/root/goals/0', sources)
    assert not d['structure_supported'] and 'unprocessed_source' in d['reason']


def test_quantified_basis_must_match_metadata_domain_and_direction():
    d = describe(GOAL, '/root/goals/0', entries(f'∀s,t∈[2,+∞),s≠t:{PAIR}'))
    goal = dict(GOAL, required_monotonicity=d['requirement'])
    goal['required_monotonicity']['input_domain'] = '[1,+∞)'
    assert describe(goal, '/root/goals/0', [DEFINITION])['reason'] == 'mono_param.basis_domain_mismatch'
    goal['required_monotonicity']['input_domain'] = '[2,+∞)'
    goal['required_monotonicity']['direction'] = 'increasing'
    assert describe(goal, '/root/goals/0', [DEFINITION])['reason'] == 'mono_param.basis_direction'


def test_guarded_quantifier_parser_preserves_logic_and_binding():
    assert parse('∀s,t∈ℝ,s≠t:s+t>0') == parse('∀s∈ℝ:∀t∈ℝ:s≠t⇒s+t>0')
    assert parse('∃s,t∈ℝ,s≠t:s+t>0') == parse('∃s∈ℝ:∃t∈ℝ:s≠t∧s+t>0')
    assert parse('s>0 → t>0 → s+t>0')[2][0] == 'implies'
    with pytest.raises(NotationError, match='quantifier_variable'):
        parse('∀s,s∈ℝ:s>0')
    with pytest.raises(NotationError, match='quantifier_domain_dependency'):
        parse('∀s,t∈[0,s]:s>t')


@pytest.mark.parametrize('alteration,allowed', [
    ('wrap', True), ('relation', False), ('direction', False), ('sibling', False), ('existential', False),
])
def test_missing_condition_grant_only_wraps_the_unchanged_basis(alteration, allowed):
    d = describe(GOAL, '/root/goals/0', entries(f'∀s,t∈[2,+∞),s≠t:{PAIR}'))
    before = {'root': {'goals': [dict(GOAL, required_monotonicity=d['requirement'])]}}
    before['root']['goals'][0]['required_monotonicity']['basis']['statement'] = PAIR
    after = deepcopy(before)
    req = after['root']['goals'][0]['required_monotonicity']
    req['basis']['statement'] = f'∀s,t∈[2,+∞),s≠t:{PAIR}'
    if alteration == 'relation':
        req['basis']['statement'] = req['basis']['statement'].replace('<0', '>0')
    elif alteration == 'direction':
        req['direction'] = 'increasing'
    elif alteration == 'sibling':
        after['root']['goals'].append({'kind': 'find_range', 'symbol': 'b'})
    elif alteration == 'existential':
        req['basis']['statement'] = req['basis']['statement'].replace('∀', '∃')
    grants = [{'action': 'repair', 'code': 'missing_condition',
               'path': '/root/goals/0/required_monotonicity/basis/statement'}]
    assert (not repair_violations(before, after, grants)) == allowed
