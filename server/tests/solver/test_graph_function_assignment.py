"""D: universal scope, necessary candidates and full bivariate verification."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.function_assignment import recover_assignment, verify_assignment
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from tests.solver.test_graph_function_formula import TARGET, candidate, description

ROOT = Path(__file__).resolve().parents[3]


def record(name):
    return json.loads((ROOT/'internal/senior-high/authored-courses/function-formula-d-20261101'/f'{name}.json').read_text())


def pair(relation, **fields):
    return candidate(relation, **{'relation_variables': ['x', 'y'], 'relation_domain': 'ℝ', **fields})


@pytest.mark.parametrize('name', ['b07', 'b07-v'])
def test_original_source_full_identity_and_independent_verifier(name, monkeypatch):
    from shuxueshuo_server.graph_lesson.stage_one.authored import prepare_authored
    from shuxueshuo_server.graph_lesson.stage_two.contracts import validate_input
    from shuxueshuo_server.graph_lesson.stage_two.formula_surface import formula_source_spans
    from shuxueshuo_server.graph_lesson.stage_two.fragments import _abstract_formula_matches
    r = record(name); c = r['candidate']; d = description(c)
    assert d['structure_supported'] and d['structure_version'] == 'function-formula-assignment/v1'
    checked = validate_input(prepare_authored(c, run_id='assignment-test', sources=r['sources'], reviewer=r['reviewer']), admission='authored_topic')
    assert checked['ok'], checked
    assert formula_source_spans(c, TARGET, [(0, len(c['original_text']))], d, _abstract_formula_matches)
    result = recover_assignment(d); x = result['variable']
    assert sp.expand(result['expression']-sp.sympify(r['expected']['expression'], locals={'x': x})) == 0
    assert result['determined_domain'] == sp.S.Reals
    assert result['assignment_plan']['needs_zero'] == (name == 'b07-v')
    for method in ('plan_assignment', 'solve_specialized', 'recover_assignment'):
        monkeypatch.setattr('shuxueshuo_server.graph_lesson.function_assignment.'+method, lambda *_: pytest.fail('verifier must not solve again'))
    assert verify_assignment(d, result)
    for key, wrong in [('expression', result['expression']+1), ('determined_domain', sp.FiniteSet(0)),
                       ('zero_value', sp.Integer(5)), ('assignment_plan', {'substitution': {'x': 1}, 'needs_zero': False})]:
        assert not verify_assignment(d, {**result, key: wrong})
    hole = sp.Mul(result['expression'], x-1, sp.Pow(x-1, -1, evaluate=False), evaluate=False)
    assert not verify_assignment(d, {**result, 'expression': hole})


@pytest.mark.parametrize('relation,expected,fields', [
    ('p(u+v)=2*p(v)+u**2+2*u*v-v**2+3*u-3*v', 'u**2+3*u', {'function': 'p', 'variable': 'u', 'relation_variables': ['u', 'v']}),
    ('f(x+y)=2*f(x)+y**2+2*x*y-x**2', 'x**2', {}),
    ('f(x+y)=f(x)+f(-y)+2*x*y', 'x**2', {}),
    ('f(x-y)=f(x)+f(y)-2*x*y-3', 'x**2+3', {}),
    ('f(x+y)=2*f(y)+3*x-3*y', '3*x', {}),
    ('f(x+y)=2*f(y)-7', '7', {}),
])
def test_assignment_family_renaming_zero_nonzero_and_constant(relation, expected, fields):
    d = description(pair(relation, **fields)); r = recover_assignment(d)
    x = r['variable']
    assert sp.expand(r['expression']-sp.sympify(expected, locals={str(x): x})) == 0
    assert verify_assignment(d, r)


@pytest.mark.parametrize('base', ['x', 'x-y', '0', 'x**0'])
def test_zero_powers_cannot_discard_undefined_original_inputs(base):
    from shuxueshuo_server.graph_lesson.stage_three.assignment_runtime import admitted
    relation = 'f(x+y)=2*f(y)+x**2+2*x*y-y**2+3*x-3*y'
    valid = recover_assignment(description(pair(relation)))
    c = pair(relation+f'+({base})**0-1')
    d = description(c)
    assert not admitted(build_context(c, TARGET))
    with pytest.raises(ValueError, match='function_assignment.power_unsupported'):
        recover_assignment(d)
    assert not verify_assignment(d, valid)


@pytest.mark.parametrize('base', ['2', 'x**2+y**2+1'])
def test_zero_powers_with_proven_nonzero_bases_keep_the_original_identity(base):
    d = description(pair('f(x+y)=2*f(y)+x**2+2*x*y-y**2+3*x-3*y'+f'+({base})**0-1'))
    result = recover_assignment(d)
    x = result['variable']
    assert result['expression'] == x**2+3*x
    assert verify_assignment(d, result)


@pytest.mark.parametrize('relation,fields', [
    ('f(x-y)=f(x)+f(y)-2*x*y', {'relation_domain': 'ℝ∖{0}'}),
    ('f(x-y)=f(x)+f(y)-2*x*y', {'relation_domain': '[0,1]'}),
    ('f(x-y)=f(x)+f(y)-2*x*y', {'declared_domain': '(0,+∞)'}),
    ('f(x-y)=f(x)+f(y)-2*x*y', {'additional_relations': ['f(0)=1']}),
    ('f(x-y)=f(x)+f(y)-2*x*y', {'function_type': 'quadratic'}),
    ('f(x+y)=x*f(x)+f(y)', {}),
    ('f(x+y)=f(x)*f(y)', {}),
    ('f(x*y)=f(x)+f(y)', {}),
    ('f(x+y)=f(x)+f(y)+x**2*y', {}),
    ('f(x+y)=f(x)+g(y)', {}),
    ('f(x+y)=f(x)+(y-1)/(y-1)', {}),
])
def test_unsupported_scope_and_structure_never_enter_assignment(relation, fields):
    from shuxueshuo_server.graph_lesson.stage_three.assignment_runtime import admitted
    assert not admitted(build_context(pair(relation, **fields), TARGET))


@pytest.mark.parametrize('relation,code', [
    ('f(x+y)=2*f(y)+x**2+2*x*y-y**2+x*y', 'no_solution'),
    ('f(x-y)=f(x)+f(y)-2*x*y+x**2-y**2', 'no_solution'),
    ('f(x+y)=f(x)+f(y)', 'controlled_assignments_insufficient'),
    ('f(x+y)=f(x)+1', 'no_solution'),
])
def test_special_values_cannot_replace_the_full_original_identity(relation, code):
    with pytest.raises(ValueError, match='function_assignment.'+code):
        recover_assignment(description(pair(relation)))


def test_both_universal_variable_names_are_bound_to_source_not_inferred():
    from shuxueshuo_server.graph_lesson.stage_two.formula_surface import formula_source_spans
    from shuxueshuo_server.graph_lesson.stage_two.fragments import _abstract_formula_matches
    from shuxueshuo_server.graph_lesson.stage_three.assignment_runtime import admitted
    c = record('b07')['candidate']; d = description(c)
    for old, new in [(r'\forall', r'\exists'), (r'x,y\in\mathbb{R}', r'x\in\mathbb{R}'),
                     (r'\mathbb{R}', r'(0,+\infty)')]:
        bad = deepcopy(c); bad['original_text'] = bad['original_text'].replace(old, new)
        assert not formula_source_spans(bad, TARGET, [(0, len(bad['original_text']))], d, _abstract_formula_matches)
    natural = deepcopy(c); natural['original_text'] = natural['original_text'].replace(r'$\forall x,y\in\mathbb{R}$', '对任意实数 $x,y$')
    assert formula_source_spans(natural, TARGET, [(0, len(natural['original_text']))], d, _abstract_formula_matches)
    del c['root']['goals'][0]['relation_variables']
    assert not admitted(build_context(c, TARGET))


@pytest.mark.parametrize('name', ['b07', 'b07-v'])
def test_actual_public_operations_shared_cards_and_source_only_selection(name, monkeypatch):
    from shuxueshuo_server.graph_lesson.stage_three import assignment_runtime as rt
    from shuxueshuo_server.graph_lesson.stage_three.selection import evaluate_goal
    from shuxueshuo_server.graph_lesson.stage_three.formula_presentation import compile_formula
    from shuxueshuo_server.graph_lesson.stage_three.execution_contracts import load_contracts
    from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value, decode_value
    from shuxueshuo_server.learning.graph_walk import grade
    c = record(name)['candidate']; ctx = build_context(c, TARGET)
    assert 'method-function-assignment' in load_contracts()
    prepared = rt.prepare_function_assignment(ctx)['outputs']; d, plan = prepared['description'], prepared['assignment_plan']
    equations = rt.specialize_function_relation(d, plan)['outputs']['specialized']
    raw = rt.solve_assignment_equations(d, plan, equations)['outputs']
    r = rt.simplify_assignment_formula(d, plan, raw['raw_expression'], raw['zero_value'])['outputs']['formula_result']
    rt.verify_assignment_formula(d, r)
    assert decode_value(encode_value(r)) == r
    monkeypatch.setattr('shuxueshuo_server.graph_lesson.function_assignment.plan_assignment', lambda *_: pytest.fail('selection must not solve'))
    selected = evaluate_goal(c, TARGET, [], 'type-function-formula')
    assert [o['method'] for o in selected['d4']['options']] == ['method-function-assignment']
    assert selected['d3']['expected_answer']['checks'] == {'source_structure': 'two_variables'}
    for phase in ('choose', 'special', 'isolate', 'verify', 'answer'):
        p = compile_formula([{'values': encode_value({'description': d, 'formula_result': r, 'phase': phase})}], phase)['parts'][0]
        assert p['stem_board']['items'][1]['math'] is None
        for option in p['interaction']['options']:
            assert (grade(p, {'value': option['value']}, 'function-assignment') == 'passed') == (option['value'] in p['expected_answer']['one_of'])


@pytest.mark.parametrize('name', ['b07', 'b07-v'])
def test_assignment_working_and_two_sided_substitution_are_concrete(name):
    from jsonschema import Draft202012Validator
    from shuxueshuo_server.graph_lesson.stage_three.formula_presentation import compile_formula, presentation, phase_view
    from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value

    desc = build_context(record(name)['candidate'], TARGET)['formula_goal']
    result = recover_assignment(desc)
    working = {}
    for phase in ('choose', 'special', 'isolate', 'verify', 'answer'):
        values = {'description': desc, 'formula_result': result, 'phase': phase}
        working[phase] = presentation(values)['formula_explanation']
        assert '$' in working[phase] and '=' in working[phase]
        assert working[phase] != phase_view(values)['explanation']

    part = compile_formula([{'values': encode_value({
        'description': desc, 'formula_result': result, 'phase': 'verify'})}], 'a'*24)['parts'][0]
    schema = json.loads((ROOT/'internal/schemas/graph-step-interaction-v1.schema.json').read_text())
    validator = Draft202012Validator({'$ref': '#/$defs/part', '$defs': schema['$defs']})
    validator.validate(part)
    assert '作为输入' in part['question'] and '两边都等于哪个式子' in part['question']
    assert part['stem_board']['items'][1]['math'] is None
    sides = part['stem_board']['comparison_sides']
    assert len(sides) == 2 and sides == part['completion_board']['comparison_sides']
    assert sides[0]['label'].startswith('左边') and sides[1]['label'].startswith('右边')
    answer = part['completion_board']['items'][1]['math']
    assert answer not in json.dumps(part['stem_board'], ensure_ascii=False)
    assert all(option['label'].startswith('$') for option in part['interaction']['options'])
    assert f'${answer}$' in [option['label'] for option in part['interaction']['options']]
    invalid = deepcopy(part)
    invalid['stem_board']['condition_groups'] = sides
    assert not validator.is_valid(invalid), 'comparison sides cannot silently become simultaneous conditions'
    if name == 'b07':
        assert r'\left(x + y\right)^{2} + 3 \left(x + y\right)' in sides[0]['math']
        assert r'f{\left(y \right)}=y^{2} + 3 y' in sides[1]['math']
        assert r'2 \left(y^{2} + 3 y\right)' in sides[1]['math']
        assert r'- f{\left(y \right)} = - y^{2} - 3 y' in working['special']
        assert r'f{\left(y \right)} = y^{2} + 3 y' in working['special']
        assert r'\forall x\in\mathbb{R}' in working['isolate']
        assert '2 x y' in answer
    else:
        assert r'\left(x - y\right)^{2}' in sides[0]['math']
        assert r'f{\left(0 \right)} = 2 f{\left(0 \right)}' in working['special']
        assert r'- 2 f{\left(x \right)} = - 2 x^{2}' in working['isolate']
        assert '- 2 x y' in answer
    assert working['verify'].count(answer) == 2, 'each side must expand to the same polynomial'


def test_assignment_derivation_keeps_renamed_variables_and_nonzero_initial_value():
    from shuxueshuo_server.graph_lesson.stage_three.assignment_derivation import full_derivation, verification_rows
    from shuxueshuo_server.graph_lesson.function_assignment import assignment_source

    desc = description(pair('p(u-v)=p(u)+p(v)-2*u*v-3',
                            function='p', variable='u', relation_variables=['u', 'v']))
    result = recover_assignment(desc)
    values = {'description': desc, 'formula_result': result}
    assert r'p{\left(0 \right)} = 3' in full_derivation({**values, 'phase': 'special'})
    assert r'p{\left(u \right)} = u^{2} + 3' in full_derivation({**values, 'phase': 'isolate'})
    rows = verification_rows(assignment_source(desc), result['expression'])
    assert r'\left(u - v\right)^{2} + 3' in rows[0]['substitution']
    assert rows[0]['expanded'] == rows[1]['expanded']
