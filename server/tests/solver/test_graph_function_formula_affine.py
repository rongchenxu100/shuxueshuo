"""A1 additions: whole real domain, exact affine inverse and honest admission."""

from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.function_formula import recover, verify
from shuxueshuo_server.graph_lesson.stage_three.formula_presentation import phase_view
from tests.solver.test_graph_function_formula import candidate, description


@pytest.mark.parametrize('relation,expected', [
    ('f(x-1)=x**2-2*x', 't**2-1'),
    ('f(x-1)=x**2-2*x+7', 't**2+6'),
    ('f(x+2)=x**2-4*x', 't**2-8*t+12'),
    ('f(-2*x+3)=x**2+x+1', '(3-t)**2/4+(3-t)/2+1'),
    ('f(x/2-3)=2*x-1', '4*t+11'),
    ('f(-x)=7', '7'),
    ('f(x)=0', '0'),
])
def test_affine_family_proves_identity_and_covers_all_reals(relation, expected):
    desc = description(candidate(relation, relation_domain='ℝ', declared_domain='ℝ', requested_domain='ℝ'))
    assert desc['structure_supported'], desc
    result = recover(desc)
    t = result['variable']
    assert sp.expand(result['expression']-sp.sympify(expected, locals={'t': t})) == 0
    assert result['source_domain'] == result['determined_domain'] == sp.S.Reals
    assert result['inverse_root'] is None
    assert result['status'] == 'determined_on_domain'
    assert verify(desc, result)
    # A half-line, a wrong inverse, or unnecessary "insufficient" must fail.
    for field, wrong in [('determined_domain', sp.Interval(0, sp.oo)),
                         ('inverse_input', result['inverse_input']+1),
                         ('expression', result['expression']+t),
                         ('inverse_root', result['inverse_input']),
                         ('status', 'insufficient_information')]:
        assert not verify(desc, {**result, field: wrong})


@pytest.mark.parametrize('relation,fields', [
    ('f(0*x+1)=x', {}), ('f(0*x+1)=2', {}),
    ('f(a*x+1)=x', {}), ('f(x+1)=sqrt(x)', {}),
    ('f(x+1)=x**3', {}), ('f(x+1)=x/x', {}),
    ('f(x+1)=x+1/x-1/x', {}), ('f(x/x+x)=x', {}),
    ('f(x+1)=x', {'relation_domain': '[0,+∞)'}),
    ('f(x+1)=x', {'declared_domain': '[0,+∞)'}),
])
def test_affine_admission_keeps_source_restrictions(relation, fields):
    value = candidate(relation, **fields)
    before = deepcopy(value)
    assert not description(value)['structure_supported']
    assert value == before


def test_affine_cards_choose_substitution_without_root_language():
    desc = description(candidate('p(-2*u+3)=u**2+u+1', function='p', variable='u'))
    result = recover(desc)
    views = {phase: phase_view({'description': desc, 'formula_result': result, 'phase': phase})
             for phase in ('input_range', 'inverse', 'rewrite', 'coverage')}
    assert views['input_range']['title'] == '把函数的输入换成新变量'
    assert '应该令什么' in views['input_range']['question']
    assert '根式' not in str(views) and '\\sqrt' not in str(views)
    final = views['coverage']
    card = final['answer_completion']
    assert card['formula'].startswith('p(u)=')
    correct = final['expected_answer']['one_of'][0]
    assert next(row for row in card['ranges'] if row['value'] == correct) == {
        'value': correct, 'condition': r'u\in\mathbb{R}', 'left': None, 'right': None,
        'left_closed': False, 'right_closed': False}
    assert '范围外' not in card['coverage']
    assert len(card['ranges']) == 3


def test_authored_topic_admission_does_not_invent_photo_or_gold_acceptance():
    from shuxueshuo_server.graph_lesson.stage_one.authored import prepare_authored
    from shuxueshuo_server.graph_lesson.stage_two.contracts import validate_input
    value = prepare_authored(candidate('f(x-1)=x**2-2*x'), run_id='authored-test',
                             sources=[{'reference': 'source-image-03.png', 'sha256': 'a'*64, 'location': '例5'}],
                             reviewer='test-author')
    assert validate_input(value, admission='authored_topic')['ok']
    assert not validate_input(value, admission='student_upload')['ok']
    assert not validate_input(value, admission='acceptance')['ok']
    for change in ('source_reviewed', 'passed', 'candidate', 'features', 'provenance'):
        changed = deepcopy(value)
        if change in ('source_reviewed', 'passed'):
            changed['statuses'][change] = True
        elif change == 'candidate':
            changed['candidate'] = candidate('f(x-1)=x**2-2*x+7')
        elif change == 'features':
            changed['features'].pop()
        else:
            changed.pop('provenance')
        assert not validate_input(changed, admission='authored_topic')['ok'], change

    # Preserve both existing admission modes without starting the event database.
    from tests.solver.test_graph_stage_three_contracts import accepted
    historical = accepted()
    assert validate_input(historical)['ok']
    historical['statuses'].update(admission='student_upload')
    historical['statuses'].pop('evaluation')
    historical['statuses'].pop('passed')
    assert validate_input(historical, admission='student_upload')['ok']
