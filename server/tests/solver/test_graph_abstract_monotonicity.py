"""FM-T5: abstract-function monotonicity from a relation and a strict sign rule."""
import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
import sympy as sp
from shuxueshuo_server.graph_lesson.abstract_monotonicity_math import (
    X1,
    X2,
    describe,
    solve,
    verify,
)
from shuxueshuo_server.graph_lesson.stage_three.trajectory import (
    decode_value,
    encode_value,
)

ROOT = Path(__file__).resolve().parents[3]
RECORDS = ROOT / 'internal/senior-high/authored-courses/function-monotonicity-t5-20261109'
TARGET = '/root/goals/0'


def record(name):
    return json.loads((RECORDS / f'{name}.json').read_text())


def goal(name, **changes):
    value = deepcopy(record(name)['candidate']['root']['goals'][0])
    sign = changes.pop('sign_condition', None)
    value.update(changes)
    if sign:
        value['sign_condition'] = {**value['sign_condition'], **sign}
    return value


@pytest.mark.parametrize('name,family,key,interval', [
    ('c01', 'additive', X2 - X1, sp.S.Reals),
    ('c02', 'multiplicative', X2 / X1, sp.Interval.open(0, sp.oo)),
])
def test_gold_and_independent_verification(name, family, key, interval):
    d = describe(goal(name), TARGET, [])
    assert d['structure_supported'], d.get('reason')
    m = solve(d)
    assert (m['relation_family'], m['interval'], m['direction']) == (family, interval, 'increasing')
    assert sp.simplify(m['key'] - key) == 0
    assert verify(d, m)
    assert verify(d, decode_value(encode_value(m)))
    for field, wrong in (('direction', 'decreasing'), ('key', X1 - X2), ('interval', sp.Interval(0, 1)),
                         ('key_range', sp.Interval.open(-1, sp.oo))):
        assert not verify(d, {**m, field: wrong})


@pytest.mark.parametrize('name', ['c01', 'c02'])
def test_negative_sign_gives_decreasing(name):
    d = describe(goal(name, sign_condition={'statement': 'f(x)<0'}), TARGET, [])
    m = solve(d)
    assert m['direction'] == 'decreasing' and verify(d, m)


@pytest.mark.parametrize('name', ['c01', 'c02'])
def test_reversed_sign_and_relation_orientation(name):
    original = goal(name)
    left, right = original['relation'].split('=')
    d = describe(goal(name, relation=f'{right}={left}', sign_condition={'statement': '0<f(x)'}), TARGET, [])
    assert d['structure_supported'] and solve(d)['direction'] == 'increasing'


@pytest.mark.parametrize('name,changes,reason', [
    ('c01', {'sign_condition': {'statement': 'f(x)>=0'}}, 'abstract_mono.strict_sign_required'),
    ('c01', {'sign_condition': {'domain': '(1,+∞)'}}, 'abstract_mono.sign_range_not_covered'),
    ('c02', {'sign_condition': {'domain': '(2,+∞)'}}, 'abstract_mono.sign_range_not_covered'),
    ('c01', {'relation_domain': '(0,+∞)'}, 'abstract_mono.relation_domain_not_covered'),
    ('c02', {'input_domain': 'ℝ'}, 'abstract_mono.interval_outside_domain'),
    ('c01', {'relation': 'f(x+y)=f(x)*f(y)'}, 'abstract_mono.strict_sign_required'),
    ('c01', {'relation': 'f(x+y)=f(x)+f(x)'}, 'abstract_mono.relation_shape_unsupported'),
])
def test_insufficient_conditions_are_not_covered_never_not_monotone(name, changes, reason):
    d = describe(goal(name, **changes), TARGET, [])
    assert not d['structure_supported'] and d['reason'] == reason
    with pytest.raises(ValueError):
        solve(d)


def test_extra_facts_are_not_silently_processed():
    d = describe(goal('c01'), TARGET, [{'source_ref': '/root/facts/0', 'expression': 'f(1)=2'}])
    assert not d['structure_supported']


@pytest.mark.parametrize('name,statement,direction', [
    ('c01', 'f(x)>0', 'increasing'),
    ('c02', 'f(x)>0', 'increasing'),
    ('c01', 'f(x)<0', 'decreasing'),
    ('c02', 'f(x)<0', 'decreasing'),
])
def test_shared_definition_route_executes_and_compiles_interactions(name, statement, direction, tmp_path):
    from shuxueshuo_server.graph_lesson.stage_one.authored import prepare_authored
    from shuxueshuo_server.graph_lesson.stage_three import driver, interaction
    from shuxueshuo_server.graph_lesson.stage_three.context import build_context
    from shuxueshuo_server.graph_lesson.stage_two.runner import run_result

    candidate = deepcopy(record(name)['candidate'])
    candidate['root']['goals'][0]['sign_condition']['statement'] = statement
    sign = statement.replace('f(x)', '$f(x)').replace('0', '0$', 1)
    candidate['original_text'] = candidate['original_text'].replace('$f(x)>0$', sign)
    fixture = Path(__file__)
    prepared = prepare_authored(candidate, run_id='t5-route', reviewer='unit-test', sources=[{
        'reference': str(fixture.relative_to(ROOT)), 'sha256': sha256(fixture.read_bytes()).hexdigest(),
        'location': 'synthetic sign variants',
    }])
    stage_two = run_result(prepared, tmp_path / 'stage-two', admission='authored_topic')
    assert stage_two['status'] == 'completed', stage_two['input_diagnostics']
    assert stage_two['goals'][0]['primary'] == 'type-monotonicity-abstract-proof'
    context = build_context(candidate, TARGET)
    state = driver.create_state(
        features=prepared['features'], context=context,
        method='method-monotonicity-definition', route_id='monotonicity-definition', branch='definition',
        target_ref=TARGET, run_id='t5-route', lesson_version='v1')
    for _ in range(100):
        if state['status'] != 'running':
            break
        state = driver.advance(state)
    assert state['status'] == 'method_complete', state.get('diagnostics')
    model = driver.export_values(state)['monotonicity_result']
    assert model['direction'] == direction
    assert verify(context['abstract_monotonicity_goal'], model)
    chunks, pending = interaction.compile_route(
        state['interaction_seeds'], interaction.load_registry(), revision='test')
    assert chunks and not pending
    assert all(chunk['status'] in ('interactive', 'readonly') for chunk, _ in chunks)
    parts = [part for chunk, _ in chunks for part in chunk.get('parts', [])]
    assert len(parts) >= 4
    for part in parts:
        expected = part['expected_answer']['one_of']
        assert sum(option['value'] in expected for option in part['interaction']['options']) == 1
        text = json.dumps(part['interaction'], ensure_ascii=False)
        assert '左' not in text and '右' not in text


@pytest.mark.parametrize('name,relation', [
    ('c01', 'f(x+y)-f(x)=f(y)'),
    ('c01', '2*f(x+y)=2*f(x)+2*f(y)'),
    ('c01', 'f(y-x)=f(y)-f(x)'),
    ('c02', 'f(x*y)-f(y)=f(x)'),
    ('c02', 'f(y/x)+f(x)=f(y)'),
    ('c02', '3*f(x/y)=3*f(x)-3*f(y)'),
])
def test_equivalent_relation_forms(name, relation):
    d = describe(goal(name, relation=relation), TARGET, [])
    assert d['structure_supported'], d.get('reason')
    m = solve(d)
    assert m['direction'] == 'increasing' and verify(d, m)


@pytest.mark.parametrize('name,relation,sign', [
    ('c01', 'f(x+y)=f(x)*f(y)', 'f(x)>1'),
    ('c01', 'f(x-y)=f(x)/f(y)', 'f(x)<1'),
    ('c01', 'f(y)*f(x)=f(x+y)', '0<f(x)<1'),
    ('c02', 'f(x*y)=f(x)*f(y)', 'f(x)>1'),
    ('c02', 'f(x/y)=f(x)/f(y)', 'f(x)<1'),
    ('c02', 'f(x*y)-f(x)*f(y)=0', '0<f(x)<1'),
])
def test_product_outputs_prove_positivity_before_sign(name, relation, sign):
    d = describe(goal(name, relation=relation, sign_condition={'statement': sign}), TARGET, [])
    assert d['structure_supported'], d.get('reason')
    m = solve(d)
    assert m['direction'] == ('increasing' if '>1' in sign else 'decreasing')
    assert verify(d, m) and verify(d, decode_value(encode_value(m)))
    assert not verify(d, {**m, 'positive_certificate': None})
    bad = deepcopy(m)
    bad['positive_certificate']['square_input'] *= 2
    assert not verify(d, bad)


@pytest.mark.parametrize('name,relation,domain,statement,direction', [
    ('c01', 'f(x+y)=f(x)+f(y)', '(-∞,0)', 'f(x)>0', 'decreasing'),
    ('c01', 'f(x-y)=f(x)-f(y)', '(-∞,0)', 'f(x)<0', 'increasing'),
    ('c02', 'f(x*y)=f(x)+f(y)', '(0,1)', 'f(x)>0', 'decreasing'),
    ('c02', 'f(x/y)=f(x)-f(y)', '(0,1)', 'f(x)<0', 'increasing'),
    ('c01', 'f(x+y)=f(x)*f(y)', '(-∞,0)', 'f(x)>1', 'decreasing'),
    ('c02', 'f(x*y)=f(x)*f(y)', '(0,1)', '0<f(x)<1', 'increasing'),
])
def test_reverse_construction_reverses_the_difference_sign(name, relation, domain, statement, direction):
    d = describe(goal(name, relation=relation, sign_condition={'domain': domain, 'statement': statement}), TARGET, [])
    m = solve(d)
    assert m['orientation'] == -1 and m['direction'] == direction and verify(d, m)
    assert not verify(d, {**m, 'orientation': 1})


@pytest.mark.parametrize('name,interval,sign_domain,expected', [
    ('c01', '[2,4]', '(0,2]', sp.Interval.Lopen(0, 2)),
    ('c01', '[2,4)', '(0,2)', sp.Interval.open(0, 2)),
    ('c02', '[2,4]', '(1,2]', sp.Interval.Lopen(1, 2)),
    ('c02', '(2,4)', '(1,2)', sp.Interval.open(1, 2)),
    ('c01', '[2,4]', '[-2,0)', sp.Interval.Ropen(-2, 0)),
    ('c02', '[2,4]', '[1/2,1)', sp.Interval.Ropen(sp.Rational(1, 2), 1)),
])
def test_finite_target_requires_exact_attainable_boundary(name, interval, sign_domain, expected):
    d = describe(goal(name, input_domain=interval, sign_condition={'domain': sign_domain}), TARGET, [])
    m = solve(d)
    assert m['key_range'] == expected and verify(d, m)
    if not expected.left_open or not expected.right_open:
        smaller = sp.Interval.open(expected.inf, expected.sup)
        d['source']['sign_condition']['domain'] = str(smaller).replace('Interval.open', '')
        assert not verify(d, m)


@pytest.mark.parametrize('name,changes,reason', [
    ('c01', {'sign_condition': {'domain': '[0,+∞)'}}, 'conditions_conflict'),
    ('c02', {'sign_condition': {'domain': '[1,+∞)'}}, 'conditions_conflict'),
    ('c01', {'input_domain': '[2,4]', 'sign_condition': {'domain': '(0,2)'}}, 'sign_range_not_covered'),
    ('c02', {'input_domain': '[2,4]', 'sign_condition': {'domain': '(1,2)'}}, 'sign_range_not_covered'),
    ('c01', {'relation': 'f(x+y)=f(x)*f(y)', 'sign_condition': {'statement': 'f(x)<1'}}, 'nonzero_witness_required'),
    ('c02', {'relation': 'f(x*y)=f(x)*f(y)', 'sign_condition': {'statement': 'f(x)<1', 'domain': '[1,+∞)'}}, 'nonzero_witness_required'),
    ('c01', {'relation': 'f(x+y)=f(x)*f(y)', 'sign_condition': {'statement': '0<f(x)<1', 'domain': '[0,+∞)'}}, 'conditions_conflict'),
    ('c01', {'kind': 'prove_monotonicity_on_interval', 'direction': 'decreasing'}, 'requested_direction_conflict'),
    ('c01', {'relation': '(x-y)*f(x+y)=(x-y)*(f(x)+f(y))'}, 'relation_shape_unsupported'),
])
def test_invalid_and_insufficient_variants_fail_closed(name, changes, reason):
    d = describe(goal(name, **changes), TARGET, [])
    assert d.get('reason') == 'abstract_mono.'+reason and not d['structure_supported']


def test_missing_domain_is_schema_error_and_direct_compiler_diagnostic():
    from shuxueshuo_server.graph_lesson.stage_one.extraction import validate_candidate
    from shuxueshuo_server.problem_understanding.notation_abstract_monotonicity import (
        compile_abstract_monotonicity,
    )
    from shuxueshuo_server.problem_understanding.notation_parser import NotationError
    candidate = deepcopy(record('c01')['candidate'])
    g = candidate['root']['goals'][0]
    del g['declared_domain']
    assert not validate_candidate(candidate)['contract_valid']
    with pytest.raises(NotationError, match='declared_domain_required'):
        compile_abstract_monotonicity(g, TARGET)


def test_arbitrary_pair_and_cards_cover_restricted_interval_without_name_capture():
    from shuxueshuo_server.graph_lesson.stage_three.abstract_monotonicity_presentation import (
        phase_views,
    )
    g = goal('c01', input_domain='(0,+∞)', relation='g(x_1+x_2)=g(x_1)+g(x_2)',
             relation_variables=['x_1', 'x_2'], function='g', sign_condition={'statement': 'g(x)>0'})
    d = describe(g, TARGET, [])
    m = solve(d)
    assert all(str(v) not in g['relation_variables'] for v in m['pair'])
    views = [v for phase in ('pair', 'construct', 'sign', 'conclude') for v in phase_views({'description': d, 'phase': phase})]
    assert '定义域' not in views[0]['derivation']['items'][0]['math']
    all_text = json.dumps(views, ensure_ascii=False)
    assert 'a_{1}' in all_text and 'a_{2}' in all_text
    assert 'x_2=x_2-x_1' not in all_text
    for view in views:
        options = view['interaction']['options']
        assert len({row['label'] for row in options}) == len(options)


@pytest.mark.stage_three_db
@pytest.mark.parametrize('name,changes', [
    ('c01', {'relation': 'f(x+y)-f(x)=f(y)', 'input_domain': '[2,4]'}),
    ('c02', {'relation': 'f(y/x)=f(y)-f(x)', 'sign_condition': {'domain': '(0,1)', 'statement': 'f(x)<0'}}),
    ('c01', {'relation': 'f(x+y)=f(x)*f(y)', 'sign_condition': {'statement': '0<f(x)<1'}}),
    ('c02', {'relation': 'f(x/y)=f(x)/f(y)', 'sign_condition': {'statement': 'f(x)<1'}}),
    ('c01', {'kind': 'prove_monotonicity_on_interval', 'direction': 'increasing', 'input_domain': '(0,+∞)'}),
])
def test_generalized_course_runs_through_final_independent_verification(name, changes, tmp_path):
    from shuxueshuo_server.graph_lesson.stage_one.authored import prepare_authored
    from shuxueshuo_server.graph_lesson.stage_three.runner import run_sample
    from shuxueshuo_server.graph_lesson.stage_two.runner import run_result
    candidate = deepcopy(record(name)['candidate'])
    candidate['root']['goals'][0] = g = goal(name, **changes)
    candidate['original_text'] = f'已知 {g["function"]} 的定义域为 {g["declared_domain"]}，对任意 {g["relation_variables"]}∈{g["relation_domain"]}，{g["relation"]}；当 {g["sign_condition"]["variable"]}∈{g["sign_condition"]["domain"]} 时 {g["sign_condition"]["statement"]}。判断在 {g["input_domain"]} 上的单调性。'
    fixture = Path(__file__)
    prepared = prepare_authored(candidate, run_id='t5-generalized', reviewer='unit-test', sources=[{
        'reference': str(fixture.relative_to(ROOT)), 'sha256': sha256(fixture.read_bytes()).hexdigest(),
        'location': 'synthetic generalization, not a photograph',
    }])
    stage_two = run_result(prepared, tmp_path/'stage-two', admission='authored_topic')
    assert stage_two['status'] == 'completed', stage_two.get('input_diagnostics')
    assert stage_two['goals'][0]['primary'] == 'type-monotonicity-abstract-proof'
    result = run_sample(tmp_path/'stage-two/stage-two-result.json', tmp_path/'execution')
    routes = result['goals'][0]['routes']
    assert routes and all(r['status'] == 'verified' for r in routes), result
    for route in routes:
        assert route['answer']['kind'] == g['kind']
        assert route['answer']['direction'] == solve(describe(g, TARGET, []))['direction']


def test_math_source_is_frozen_with_execution_contract():
    from shuxueshuo_server.graph_lesson.stage_three.runner import fingerprint
    path = 'server/shuxueshuo_server/graph_lesson/abstract_monotonicity_math.py'
    assert fingerprint()[path] == sha256((ROOT/path).read_bytes()).hexdigest()
