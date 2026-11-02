"""A3: identity, coverage, original scalar value, and actual route execution."""

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.function_matching import (
    evaluate_relation, recover_matching, verify_matching, verify_value,
)
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from tests.solver.test_graph_function_formula import TARGET, candidate, description


def two_goals():
    value = candidate('f(x-1/x)=x**2+1/x**2')
    value['root']['goals'].insert(0, {**value['root']['goals'][0], 'kind': 'find_value', 'expression': 'f(0)'})
    value['original_text'] = r'已知 $f(x-\frac{1}{x})=x^2+\frac{1}{x^2}$，求 $f(0)$ 的值和 $f(x)$ 的解析式。'
    return value


@pytest.mark.parametrize('relation,expected', [
    ('f(x-1/x)=x**2+1/x**2', 't**2+2'),
    ('f(x-2/x)=3*x**2+12/x**2+5*x-10/x-7', '3*t**2+5*t+5'),
    ('p(u-1/4/u)=u-1/4/u', 't'),
    ('f(x-3/x)=7', '7'),
    ('f(x-1)=x**2-2*x+7', 't**2+6'),
    ('f(sqrt(x)+1)=2*x+1', '2*t**2-4*t+3'),
    ('f(-2*sqrt(x)+3)=x-4', '(3-t)**2/4-4'),
])
def test_matching_identity_coverage_and_independent_verification(monkeypatch, relation, expected):
    desc = description(candidate(relation, **({'function': 'p', 'variable': 'u'} if relation.startswith('p') else {})))
    result = recover_matching(desc)
    t = result['variable']
    assert sp.expand(result['expression']-sp.sympify(expected, locals={'t': t})) == 0
    monkeypatch.setattr('shuxueshuo_server.graph_lesson.function_matching.recover_matching', lambda _: pytest.fail('must independently verify'))
    assert verify_matching(desc, result)
    for field, wrong in [('expression', result['expression']+1), ('source_domain', sp.FiniteSet(1)),
                         ('determined_domain', sp.FiniteSet(0)), ('coverage', {}), ('status', 'complete')]:
        assert not verify_matching(desc, {**result, field: wrong})


@pytest.mark.parametrize('relation', [
    'f(x+1/x)=x**2+1/x**2', 'f(x-1/x)=x',
    'f(x-1/x)=x**2-1/x**2', 'f(x-1/x)=x**2+1/x**2+(x-1)/(x-1)',
    'f(x-1/x)=x**4+1/x**4', 'f(x-1/x)=sqrt(x)',
])
def test_nonmatching_and_restricted_fibers_are_not_admitted(relation):
    assert not description(candidate(relation))['structure_supported']


def test_two_goals_keep_scalar_independent_and_bind_both_source_questions(monkeypatch):
    from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
    from shuxueshuo_server.graph_lesson.stage_one.authored import prepare_authored
    from shuxueshuo_server.graph_lesson.stage_two.contracts import validate_input
    from shuxueshuo_server.graph_lesson.stage_two.formula_surface import formula_source_spans
    from shuxueshuo_server.graph_lesson.stage_two.fragments import _abstract_formula_matches
    value = two_goals()
    features = extract_features(value)['features']
    assert {row['target_ref'] for row in features} == {TARGET, '/root/goals/1'}
    prepared = prepare_authored(value, run_id='matching-test', sources=[{'reference': 'source.png', 'sha256': 'a'*64, 'location': 'test fixture'}], reviewer='unit-test')
    checked = validate_input(prepared, admission='authored_topic')
    assert checked['ok'], checked
    desc = build_context(value, TARGET)['evaluation_goal']
    monkeypatch.setattr('shuxueshuo_server.graph_lesson.function_matching.recover_matching', lambda _: pytest.fail('scalar must not solve formula'))
    result = evaluate_relation(desc)
    assert result['input'] == 0 and result['source_input'] == 1 and result['value'] == 2
    assert verify_value(desc, result)
    assert not verify_value(desc, {**result, 'source_input': sp.S.Zero})
    assert not verify_value(desc, {**result, 'value': sp.Integer(3)})
    for index in range(2):
        target = f'/root/goals/{index}'
        ctx = build_context(value, target)
        desc = ctx.get('formula_goal') or ctx['evaluation_goal']
        assert formula_source_spans(value, target, [(0, len(value['original_text']))], desc, _abstract_formula_matches)


def test_matching_and_scalar_use_registered_cards_and_skills():
    from shuxueshuo_server.graph_lesson.stage_three import execution_contracts, evaluation_runtime
    from shuxueshuo_server.graph_lesson.stage_three.formula_presentation import compile_formula
    from shuxueshuo_server.graph_lesson.stage_three.evaluation_presentation import compile_evaluation
    from shuxueshuo_server.graph_lesson.stage_three.matching_runtime import solve_function_matching
    from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value
    from shuxueshuo_server.learning.graph_walk import grade
    assert 'method-function-matching' in execution_contracts.load_contracts()
    value = two_goals()
    data = solve_function_matching(build_context(value, '/root/goals/1'))['outputs']
    for phase in ('square', 'match', 'rename', 'coverage'):
        part = compile_formula([{'values': encode_value({**data, 'phase': phase})}], phase)['parts'][0]
        assert grade(part, {'value': part['expected_answer']['one_of'][0]}, 'function-matching') == 'passed'
        if phase == 'coverage':
            assert '非零实根' not in part['question']  # proof stays in the expandable explanation
            assert '判别式' in part['answer_completion']['coverage']
    ctx = build_context(value, TARGET)
    scalar = evaluation_runtime.solve_function_evaluation(ctx)['outputs']
    d, r = scalar['description'], scalar['evaluation_result']
    outputs = evaluation_runtime.extract_evaluation_conditions(d, r)['outputs']
    evaluation_runtime.resolve_evaluation_domain(d, outputs['conditions'], r)
    evaluation_runtime.simplify_evaluation_expressions(outputs['substitutions'], outputs['raw_terms'], r)
    evaluation_runtime.verify_evaluation_identities(d, r)
    for phase in ('input', 'conclusion'):
        part = compile_evaluation([{'values': encode_value({**scalar, 'phase': phase})}], phase)['parts'][0]
        assert grade(part, {'value': part['expected_answer']['one_of'][0]}, 'function-evaluation') == 'passed'


def test_noninjective_selection_does_not_solve_formula(monkeypatch):
    from shuxueshuo_server.graph_lesson.stage_three.selection import evaluate_goal
    monkeypatch.setattr('shuxueshuo_server.graph_lesson.function_matching.recover_matching', lambda _: pytest.fail('selection cannot recover'))
    result = evaluate_goal(candidate('f(x-1/x)=x**2+1/x**2'), TARGET, [], 'type-function-formula')
    assert [option['method'] for option in result['d4']['options']] == ['method-function-matching']
