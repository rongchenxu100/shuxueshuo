"""FR-T1 A0: preserve unknown rules, root placement, ranges and proof obligations."""

from copy import deepcopy
from hashlib import sha256
from itertools import product
from pathlib import Path

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.function_formula import recover, verify
from shuxueshuo_server.graph_lesson.stage_one.extraction import validate_candidate
from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.problem_understanding.notation_compile import NotationValidator

TARGET = '/root/goals/0'


def candidate(relation='f(sqrt(x)+1)=2*x+1', **fields):
    goal = {'kind': 'find_function_formula', 'function': 'f', 'variable': 'x', 'relation': relation, **fields}
    text = f'已知 ${relation}$，求 ${goal["function"]}({goal["variable"]})$ 的解析式。'
    return {'original_text': text, 'root': {'goals': [goal]}}


def description(value):
    return build_context(value, TARGET)['formula_goal']


@pytest.mark.parametrize('relation', ['f(sqrt(x)+1)=2*x+1', 'f(-2*sqrt(x)+3)=3*x-sqrt(x)+2', 'f(x-1)=x**2-2*x'])
def test_selection_uses_source_structure_without_solving_or_inventing_routes(monkeypatch, relation):
    from shuxueshuo_server.graph_lesson.stage_three.selection import evaluate_goal
    monkeypatch.setattr('shuxueshuo_server.graph_lesson.stage_three.formula_runtime.recover',
                        lambda *_: pytest.fail('selection must not recover the answer'))
    result = evaluate_goal(candidate(relation), TARGET, [], 'type-function-formula')
    assert result['selection']['rule'] == 'rule-function-formula-method'
    assert result['d3']['interaction']['layout'] == 'connections'
    assert len(result['d3']['interaction']['method_choices']) == 5
    assert result['d3']['interaction']['connections'] == [
        {'cue': 'function_type', 'method': 'coefficients'},
        {'cue': 'composite_input', 'method': 'substitution'},
        {'cue': 'composite_input', 'method': 'matching'},
        {'cue': 'paired_values', 'method': 'system'},
        {'cue': 'two_variables', 'method': 'assignment'},
    ]
    clue = next(row for row in result['d3']['interaction']['checks'][0]['options'] if row['value'] == 'composite_input')
    assert clue['label'] == '已知复合函数的解析式'
    assert 'f\\left(' in clue['note']
    assert '=' in clue['note']
    assert len(result['d4']['options']) == 2
    assert result['d4']['options'][0]['method'] == 'method-function-substitution'
    assert result['d3']['verdicts']['matching']['value'] == 'fit'
    assert all(result['d3']['verdicts'][key]['value'] == 'not_triggered'
               for key in ('coefficients', 'system', 'assignment'))
    assert TARGET+'/relation' in result['d3']['interaction']['source_refs']
    assert result['d3']['expected_answer']['checks'] == {'source_structure': 'composite_input'}


def test_selection_does_not_grant_root_routes_to_unsupported_inputs():
    from shuxueshuo_server.graph_lesson.stage_three.selection import evaluate_goal
    result = evaluate_goal(candidate('f(x**2+1)=2*x+1'), TARGET, [], 'type-function-formula')
    assert result['d3'] is None
    assert not result['selection']['branches']


@pytest.mark.parametrize('relation,expected,domain', [
    ('f(sqrt(x)+1)=2*x+1', '2*t**2-4*t+3', sp.Interval(1, sp.oo)),
    ('f(sqrt(x)+1)=x+2*sqrt(x)', 't**2-1', sp.Interval(1, sp.oo)),
    ('f(sqrt(x)-2)=x-4', 't**2+4*t', sp.Interval(-2, sp.oo)),
    ('f(-2*sqrt(x)+3)=3*x-sqrt(x)+2', '3*(3-t)**2/4-(3-t)/2+2', sp.Interval(-sp.oo, 3)),
    ('f(sqrt(x)/2-3)=0*x+0*sqrt(x)+7', '7', sp.Interval(-3, sp.oo)),
    ('f(2*sqrt(x))=-3*sqrt(x)', '-3*t/2', sp.Interval(0, sp.oo)),
    ('f(sqrt(x)+1)=2*(sqrt(x)+1)**2-4*(sqrt(x)+1)+3', '2*t**2-4*t+3', sp.Interval(1, sp.oo)),
])
def test_complete_affine_root_family(relation, expected, domain):
    value = candidate(relation)
    checked = validate_candidate(value)
    assert checked['contract_valid'], checked
    desc = description(value)
    assert desc['structure_supported'], desc
    result = recover(desc)
    assert sp.expand(result['expression'] - sp.sympify(expected, locals={'t': result['variable']})) == 0
    assert result['determined_domain'] == domain
    assert result['source_domain'] == sp.Interval(0, sp.oo)
    assert verify(desc, result)
    assert 'expression' not in desc
    feature = next(f for f in extract_features(value)['features'] if f['feature_id'] == 'function_formula')
    assert feature['value'] == desc


@pytest.mark.parametrize('relation,fields', [
    ('f(sqrt(x+1))=2*x+1', {}), ('f(sqrt(sqrt(x)))=x', {}),
    ('f(sqrt(x)+1)=x+1/x-1/x', {}), ('f(0*sqrt(x)+1)=x', {}),
    ('f(0*sqrt(x)+1)=2', {}), ('f(a*sqrt(x)+1)=x', {}),
    ('f(sqrt(x)+1)=g(x)', {}), ('f(sqrt(x)+1)=x**3', {}),
    ('f(sqrt(x)+1)=2*x+1', {'relation_domain': '[0,4]'}),
    ('f(sqrt(x)+1)=2*x+1', {'declared_domain': '[0,1]'}),
    ('f(sqrt(x)+1)=2*x+1', {'function_type': 'quadratic'}),
    ('f(sqrt(x)+1)=2**100*x', {}),
])
def test_rejects_unsupported_without_dropping_original(relation, fields):
    value = candidate(relation, **fields)
    before = deepcopy(value)
    desc = description(value)
    assert not desc['structure_supported']
    assert desc['reason'].startswith(('function_formula.', 'function_coefficients.', 'function_system.'))
    assert value == before


def test_extra_conditions_and_declared_domain_are_preserved():
    value = candidate(declared_domain='ℝ', requested_domain='ℝ')
    desc = description(value)
    result = recover(desc)
    assert result['status'] == 'insufficient_information'
    assert result['determined_domain'] == sp.Interval(1, sp.oo)
    assert verify(desc, result)
    value['root']['facts'] = ['a>0']
    assert not description(value)['structure_supported']


def test_independent_verifier_rejects_tampered_formula_domain_or_inverse(monkeypatch):
    desc = description(candidate())
    result = recover(desc)
    monkeypatch.setattr('shuxueshuo_server.graph_lesson.function_formula.recover',
                        lambda _: pytest.fail('verifier must not call recovering algorithm'))
    assert verify(desc, result)
    for field, wrong in [('expression', result['expression']+1), ('determined_domain', sp.S.Reals),
                         ('determined_domain', sp.Interval.open(1, sp.oo)),
                         ('source_domain', sp.S.Reals), ('inverse_root', -result['inverse_root']),
                         ('inverse_input', result['inverse_input']+1), ('declared_domain', sp.S.Reals)]:
        assert not verify(desc, {**result, field: wrong}), field


def test_alpha_renaming_preserves_semantics_without_function_definition():
    first = candidate()
    second = candidate('p(sqrt(u)+1)=2*u+1', function='p', variable='u')
    from shuxueshuo_server.graph_lesson.stage_one import contracts
    from shuxueshuo_server.problem_understanding.notation_function_formula import (
        canonical_function_formula,
    )
    from shuxueshuo_server.problem_understanding.notation_semantics import canonical
    reports = [NotationValidator().validate_root(v['root'], contracts.schema()['$defs']) for v in (first, second)]
    assert all(r.ok for r in reports)
    assert all(not r.semantic['facts'] for r in reports)
    assert canonical_function_formula(reports[0].semantic['goals'][0]) == canonical_function_formula(reports[1].semantic['goals'][0])
    assert canonical(reports[0]) == canonical(reports[1])


def test_source_binding_distinguishes_radical_and_unknown_function():
    from shuxueshuo_server.graph_lesson.stage_two.formula_surface import (
        formula_source_spans,
    )
    from shuxueshuo_server.graph_lesson.stage_two.fragments import (
        _abstract_formula_matches,
    )
    value = candidate()
    desc = description(value)
    def locate(v):
        return formula_source_spans(v, TARGET, [(0, len(v['original_text']))], desc, _abstract_formula_matches)
    assert locate(value)
    for before, after in [('sqrt(x)+1', 'sqrt(x+1)'), ('2*x+1', '2*x-1'),
                          ('求 $f(x)$', '求 $g(x)$'), ('已知', '已知二次函数')]:
        changed = deepcopy(value)
        changed['original_text'] = changed['original_text'].replace(before, after)
        assert locate(changed) is None
    # Model transcription may put the blank outside the math span.
    value['original_text'] = r'【变式2】已知 $f(\sqrt{x}+1)=2x+1$，则 $f(x)=$ ______。'
    assert locate(value)


def test_coefficient_grid_proves_identity_at_original_inputs_and_keeps_half_line():
    # Development variants, deliberately not counted as unseen-photo holdouts.
    for a, b, u, v in product((-2, sp.Rational(1, 2)), (-3, 0, 2), (-1, 0, 2), (0, 3)):
        desc = description(candidate(f'p(({a})*sqrt(q)+({b}))=({u})*q+({v})*sqrt(q)-2', function='p', variable='q'))
        answer = recover(desc)
        assert verify(desc, answer)
        assert answer['determined_domain'] == (sp.Interval(b, sp.oo) if a > 0 else sp.Interval(-sp.oo, b))
        for x in (0, 1, 4, sp.Rational(1, 9)):
            assert sp.simplify(answer['expression'].subs(answer['variable'], a*sp.sqrt(x)+b)
                               - (u*x+v*sp.sqrt(x)-2)) == 0


def test_formula_fingerprints_include_source_math_runtime_and_presentation():
    from shuxueshuo_server.graph_lesson import function_formula
    from shuxueshuo_server.graph_lesson.stage_three import (
        execution_contracts,
        formula_presentation,
        formula_runtime,
        runner,
    )
    frozen, direct = runner.fingerprint(), execution_contracts.revisions()
    repo = Path(__file__).resolve().parents[3]
    for name, module in [('function_formula', function_formula), ('formula_runtime', formula_runtime),
                         ('formula_presentation', formula_presentation)]:
        source = Path(module.__file__).resolve()
        digest = sha256(source.read_bytes()).hexdigest()
        assert frozen[str(source.relative_to(repo))] == direct[name] == digest


@pytest.mark.parametrize('relation', ['f(sqrt(x)+1)=2*x+1', 'f(x-1)=x**2-2*x', 'f(-x)=3'])
def test_registered_method_and_four_local_interactions(relation):
    from shuxueshuo_server.graph_lesson.stage_three import execution_contracts
    from shuxueshuo_server.graph_lesson.stage_three.formula_presentation import (
        compile_formula,
    )
    from shuxueshuo_server.graph_lesson.stage_three.formula_runtime import (
        solve_function_formula,
    )
    from shuxueshuo_server.graph_lesson.stage_three.interaction import load_registry
    from shuxueshuo_server.graph_lesson.stage_three.selection import evaluate_goal
    from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value
    from shuxueshuo_server.learning.graph_walk import grade
    contracts = execution_contracts.load_contracts()
    assert 'method-function-substitution' in contracts
    assert load_registry()['templates']['function_formula_derivation']['compiler'] == 'function_formula'
    value = candidate(relation)
    selected = evaluate_goal(value, TARGET, [], 'type-function-formula')
    assert selected['selection']['branches'][0]['target'] == 'method-function-substitution'
    assert not selected['d3'].get('prerequisites')  # no generic domain quiz before choosing a method
    data = solve_function_formula(build_context(value, TARGET))['outputs']
    for phase in ('input_range', 'inverse', 'rewrite', 'coverage'):
        part = compile_formula([{'values': encode_value({**data, 'phase': phase})}], phase)['parts'][0]
        assert part['interaction']['type'] == 'choice'
        assert part['stem_board']['items'][1]['math'] is None
        assert part['completion_board']['items'][1]['math']
        assert part['expected_answer']
        correct = part['expected_answer']['one_of'][0]
        wrong = next(option['value'] for option in part['interaction']['options'] if option['value'] != correct)
        assert grade(part, {'value': correct}, 'function-substitution') == 'passed'
        assert grade(part, {'value': wrong}, 'function-substitution') == 'wrong'


@pytest.mark.parametrize('value,condition', [
    (candidate(), r'x\geq1'),
    (candidate('p(-2*sqrt(u)+3)=3*u-sqrt(u)+2', function='p', variable='u'), r'u\leq3'),
    (candidate(requested_domain='ℝ'), r'x\geq1'),
])
def test_complete_answer_preserves_variable_range_feedback_and_schema(value, condition):
    import json
    from jsonschema import Draft202012Validator
    from shuxueshuo_server.graph_lesson.stage_three.formula_presentation import compile_formula
    from shuxueshuo_server.graph_lesson.stage_three.formula_runtime import solve_function_formula
    from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value
    data = solve_function_formula(build_context(value, TARGET))['outputs']
    part = compile_formula([{'values': encode_value({**data, 'phase': 'coverage'})}], 'a'*24)['parts'][0]
    schema = json.loads((Path(__file__).resolve().parents[3]/'internal/schemas/graph-step-interaction-v1.schema.json').read_text())
    Draft202012Validator({'$defs': schema['$defs'], '$ref': '#/$defs/part'}).validate(part)
    assert part['title'] == '写出完整答案'
    assert part['submit_label'] == '确认答案'
    view = part['answer_completion']
    goal = value['root']['goals'][0]
    assert view['formula'].startswith(f'{goal["function"]}({goal["variable"]})=')
    assert 't' not in view['formula']
    correct = part['expected_answer']['one_of'][0]
    assert next(row for row in view['ranges'] if row['value'] == correct)['condition'] == condition
    assert len(part['interaction']['options']) == len(view['ranges']) == 4
    assert all(row['feedback'] for row in part['interaction']['options'])
    assert '每个数都能取到' in view['coverage']
    if goal.get('requested_domain'):
        assert '不足' in view['reminder']


@pytest.mark.stage_three_db
def test_complete_formula_lesson_and_replay(tmp_path):
    from collections import Counter
    from shuxueshuo_server.graph_lesson.stage_three import runner
    from tests.solver.test_graph_stage_three_execution import (
        constructed_upstream,
        store,
    )
    from tools.export_graph_walk_course import export_course
    value = candidate()
    upstream = constructed_upstream(tmp_path, value)
    output = tmp_path/'run'
    completed = runner.run_sample(upstream, output)
    goal = completed['goals'][0]
    assert goal['status'] == 'solved', goal
    assert goal['answer']['kind'] == 'find_function_formula'
    assert goal['answer']['expression']['expression'] == '2*t**2 - 4*t + 3'
    assert goal['answer']['determined_domain']['expression'] == 'Interval(1, oo)'
    assert goal['feasible_set'] is None
    snapshot = store(output).snapshot()
    assert Counter(row['route_id'] for row in snapshot['math_steps']) == {
        'function-substitution': 4, 'function-matching': 4,
    }
    step_ids = {row['step_id'] for row in snapshot['math_steps']}
    assert len(step_ids) == 8
    assert all(row['status'] == 'interactive' for row in snapshot['interaction_states'])
    course = export_course(output, 'function-formula-a0-regression')
    assert course['lesson']['goals'][0]['walk'] is not None
    assert not course['lesson']['goals'][0]['d1'].get('diagnostics')
    replay = runner.run_sample(upstream, output, resume=True)
    assert replay['goals'][0]['answer'] == goal['answer']
    assert {row['step_id'] for row in store(output).snapshot()['math_steps']} == step_ids
