"""FP-T1: determine the parity of a concrete function by the definition."""
import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.function_parity import (
    inspect_parity_target,
    solve,
    verify,
)
from shuxueshuo_server.graph_lesson.stage_three.trajectory import (
    decode_value,
    encode_value,
)
from shuxueshuo_server.problem_understanding.notation_parser import NotationError

ROOT = Path(__file__).resolve().parents[3]
RECORDS = ROOT / 'internal/senior-high/authored-courses/function-parity-t1-20261110'
TARGET = '/root/goals/0'


def record(name):
    return json.loads((RECORDS / f'{name}.json').read_text())


def candidate(expression, **changes):
    goal = {'kind': 'determine_function_parity', 'function': 'f', 'variable': 'x', 'expression': expression,
            **changes}
    domain = '，定义域为 $' + changes['input_domain'] + '$' if 'input_domain' in changes else ''
    return {'original_text': f'判断函数 $f(x)={expression}$ 的奇偶性{domain}。', 'root': {'goals': [goal]}}


def described(expression, **changes):
    goal = inspect_parity_target(candidate(expression, **changes), TARGET)
    assert goal['structure_supported'], goal.get('reason')
    return goal


@pytest.mark.parametrize('expression,changes,classification', [
    ('x/(x^2+1)', {}, 'odd_only'),
    ('abs(x)+x^2', {}, 'even_only'),
    ('1/x', {}, 'odd_only'),
    ('x*abs(x)', {}, 'odd_only'),
    ('x^3', {'input_domain': '[-1,1]'}, 'odd_only'),
    ('x^2+x', {}, 'neither'),
    ('x-x', {}, 'both'),
    ('sqrt(1-x^2)+sqrt(x^2-1)', {}, 'both'),
    ('x^2', {'input_domain': '[-2,2)'}, 'neither'),
    ('sqrt(x)', {}, 'neither'),
    ('(x^2-x)/(x-1)', {}, 'neither'),
])
def test_gold_classification_and_independent_verification(expression, changes, classification):
    goal = described(expression, **changes)
    result = solve(goal)
    assert result['classification'] == classification
    assert verify(goal, result)['status'] == 'verified'
    assert verify(goal, decode_value(encode_value(result)))['status'] == 'verified'


def test_asymmetric_domain_refutes_both_relations_with_a_domain_witness():
    goal = described('(x^2-x)/(x-1)')
    result = solve(goal)
    witness = result['domain_symmetry']['witness']
    assert result['domain_symmetry']['status'] == 'refuted'
    assert witness['in_domain'] and not witness['opposite_in_domain'] and witness['point'] == -1
    assert all(result[p]['reason'] == 'domain_not_symmetric' for p in ('odd', 'even'))


def test_refuted_relation_carries_an_exact_rational_counterexample():
    result = solve(described('x/(x^2+1)'))
    witness = result['even']['witness']
    assert witness['kind'] == 'value' and isinstance(witness['point'], sp.Rational)
    assert witness['opposite_value'] != witness['value']


def _tampered(result, path, value):
    bad = deepcopy(result)
    target = bad
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return bad


@pytest.mark.parametrize('expression,path,value', [
    ('x/(x^2+1)', ('classification',), 'even_only'),
    ('x/(x^2+1)', ('classification',), 'both'),
    ('x/(x^2+1)', ('even', 'status'), 'proved'),
    ('abs(x)+x^2', ('odd', 'status'), 'proved'),
    ('x/(x^2+1)', ('even', 'witness', 'point'), sp.Integer(0)),
    ('x/(x^2+1)', ('even', 'witness', 'value'), sp.Integer(7)),
    ('x/(x^2+1)', ('even', 'witness', 'point'), sp.sqrt(2)),
    ('x/(x^2+1)', ('domain',), sp.Interval(-1, 1)),
    ('x^2', ('domain_symmetry', 'status'), 'proved'),
])
def test_tampered_results_fail_independent_verification(expression, path, value):
    changes = {'input_domain': '[-2,2)'} if expression == 'x^2' else {}
    goal = described(expression, **changes)
    result = solve(goal)
    try:
        status = verify(goal, _tampered(result, path, value))['status']
    except (NotationError, KeyError, TypeError, ValueError):
        status = 'math_failed'
    assert status == 'math_failed'


@pytest.mark.parametrize('expression,classification', [
    ('sqrt(2-x^2)', 'even_only'), ('x/(x^2-2)', 'odd_only'),
    ('abs(x+1)-abs(x-1)', 'odd_only'), ('abs(x+1)+abs(x-1)', 'even_only'),
])
def test_common_variants_have_verified_classifications(expression, classification):
    goal = described(expression)
    result = solve(goal)
    assert result['classification'] == classification
    assert verify(goal, decode_value(encode_value(result)))['status'] == 'verified'
    assert verify(goal, {**result, 'classification': 'neither'})['status'] == 'math_failed'


def test_extra_facts_are_not_silently_processed():
    value = candidate('x^2')
    value['root']['facts'] = [{'kind': 'relation', 'expression': 'f(1)=1'}]
    try:
        goal = inspect_parity_target(value, TARGET)
    except NotationError:
        return
    assert not goal['structure_supported']


def test_schema_and_compiler_keep_the_original_rule():
    from shuxueshuo_server.graph_lesson.stage_one.extraction import validate_candidate
    from shuxueshuo_server.problem_understanding.notation_function_parity import (
        compile_parity,
    )
    assert validate_candidate(record('a01-1')['candidate'])['contract_valid']
    compiled = compile_parity(record('a01-2')['candidate']['root']['goals'][0], TARGET)
    assert compiled['function']['expression_ast'][0] == '+'
    assert compiled['function']['source_ref'] == TARGET + '/expression'
    with pytest.raises(NotationError):
        compile_parity({'kind': 'determine_function_parity', 'function': 'x', 'variable': 'x',
                        'expression': 'x^2'}, TARGET)


def _prepare(value, tmp_path, run_id):
    from shuxueshuo_server.graph_lesson.stage_one.authored import prepare_authored
    from shuxueshuo_server.graph_lesson.stage_two.runner import run_result
    fixture = Path(__file__)
    prepared = prepare_authored(value, run_id=run_id, reviewer='unit-test', sources=[{
        'reference': str(fixture.relative_to(ROOT)), 'sha256': sha256(fixture.read_bytes()).hexdigest(),
        'location': 'synthetic parity variants',
    }])
    stage_two = run_result(prepared, tmp_path / 'stage-two', admission='authored_topic')
    return prepared, stage_two


@pytest.mark.parametrize('name,classification', [('a01-1', 'odd_only'), ('a01-2', 'even_only')])
def test_route_executes_and_compiles_cards(name, classification, tmp_path):
    from shuxueshuo_server.graph_lesson.stage_three import driver, interaction
    from shuxueshuo_server.graph_lesson.stage_three.context import build_context

    value = record(name)['candidate']
    prepared, stage_two = _prepare(value, tmp_path, 'fp-route')
    assert stage_two['status'] == 'completed', stage_two.get('input_diagnostics')
    assert stage_two['goals'][0]['primary'] == 'type-function-parity'
    context = build_context(value, TARGET)
    state = driver.create_state(
        features=prepared['features'], context=context, method='method-parity-definition',
        route_id='parity-definition', branch='direct', target_ref=TARGET, run_id='fp-route', lesson_version='v1')
    for _ in range(100):
        if state['status'] != 'running':
            break
        state = driver.advance(state)
    assert state['status'] == 'method_complete', state.get('diagnostics')
    result = driver.export_values(state)['parity_result']
    assert result['classification'] == classification
    assert verify(context['parity_goal'], result)['status'] == 'verified'
    chunks, pending = interaction.compile_route(state['interaction_seeds'], interaction.load_registry(), revision='test')
    assert chunks and not pending
    parts = [part for chunk, _ in chunks for part in chunk.get('parts', [])]
    assert [part['title'] for part in parts] == ['检查定义域的对称性', '代入相反数', '核对奇函数的条件',
                                                 '核对偶函数的条件', '得出结论']
    for part in parts:
        expected = part['expected_answer']['one_of']
        assert sum(option['value'] in expected for option in part['interaction']['options']) == 1
        labels = [option['label'] for option in part['interaction']['options']]
        assert len(set(labels)) == len(labels)
        text = json.dumps(part, ensure_ascii=False)
        assert '左' not in text and '右' not in text


def test_asymmetric_domain_folds_substitution_and_comparison(tmp_path):
    from shuxueshuo_server.graph_lesson.stage_three import driver, interaction
    from shuxueshuo_server.graph_lesson.stage_three.context import build_context

    value = candidate('x^2', input_domain='[-2,2)')
    value['original_text'] = '判断函数 $f(x)=x^2$，$x\\in[-2,2)$ 的奇偶性。'
    prepared, stage_two = _prepare(value, tmp_path, 'fp-asym')
    assert stage_two['status'] == 'completed', stage_two.get('input_diagnostics')
    state = driver.create_state(
        features=prepared['features'], context=build_context(value, TARGET), method='method-parity-definition',
        route_id='parity-definition', branch='direct', target_ref=TARGET, run_id='fp-asym', lesson_version='v1')
    for _ in range(100):
        if state['status'] != 'running':
            break
        state = driver.advance(state)
    assert state['status'] == 'method_complete', state.get('diagnostics')
    assert driver.export_values(state)['parity_result']['classification'] == 'neither'
    chunks, _ = interaction.compile_route(state['interaction_seeds'], interaction.load_registry(), revision='test')
    titles = [part['title'] for chunk, _ in chunks for part in chunk.get('parts', [])]
    assert titles == ['检查定义域的对称性', '得出结论']


def test_substitution_card_distractors_are_never_equal_to_f_of_minus_x():
    from shuxueshuo_server.graph_lesson.stage_three.parity_presentation import (
        _context,
        _reflect_view,
    )
    for expression in ('x/(x^2+1)', 'abs(x)+x^2', 'x^3-x', '1+x', 'sqrt(1-x^2)+1/x'):
        view = _reflect_view(_context({'description': described(expression)}))
        labels = [option['label'] for option in view['interaction']['options']]
        assert len(labels) >= 2 and not any('+-' in label for label in labels)


@pytest.mark.parametrize('expression,prop,line', [
    ('x/(x^2+1)', 'even', r'f\left(-1\right)\ne \frac{1}{2}'),
    ('abs(x)+x^2', 'odd', r'f\left(-1\right)\ne -2'),
])
def test_counterexample_card_compares_with_the_required_value(expression, prop, line):
    from shuxueshuo_server.graph_lesson.stage_three.parity_presentation import (
        _context,
        _relation_view,
    )
    goal = described(expression)
    result = solve(goal)
    view = _relation_view(_context({'description': goal}), {p: result[p] for p in ('odd', 'even')}, prop)
    assert line in view['proof']


def test_math_and_presentation_sources_are_frozen():
    from shuxueshuo_server.graph_lesson.stage_three.runner import fingerprint
    for path in ('server/shuxueshuo_server/graph_lesson/function_parity.py',
                 'server/shuxueshuo_server/graph_lesson/function_cells.py',
                 'server/shuxueshuo_server/graph_lesson/stage_three/function_cells.py',
                 'server/shuxueshuo_server/graph_lesson/stage_three/parity_runtime.py',
                 'server/shuxueshuo_server/graph_lesson/stage_three/parity_presentation.py'):
        assert fingerprint()[path] == sha256((ROOT / path).read_bytes()).hexdigest()


@pytest.mark.parametrize('expression,changes,classification', [
    ('x^4+abs(x)', {}, 'even_only'),
    ('abs(x^2-2)', {}, 'even_only'),
    ('sqrt((x^2-2)^2)', {}, 'even_only'),
    ('sqrt(2*x^2)', {}, 'even_only'),
    ('sqrt(2)*x', {}, 'odd_only'),
    ('x/sqrt(x^2-2)', {}, 'odd_only'),
    ('(x^4-4)/(x^2-2)', {}, 'even_only'),
    ('x^2/x', {'input_domain': '[-1,1]', 'domain_role': 'restriction'}, 'odd_only'),
    ('x', {'input_domain': '{0}'}, 'both'),
    ('x', {'input_domain': '{-2,-1,0,1,2}'}, 'odd_only'),
    ('x^2-2', {'input_domain': '{-sqrt(2),sqrt(2)}'}, 'both'),
    ('x', {'input_domain': '[-2,-1]∪[1,2]'}, 'odd_only'),
    ('x^2', {'input_domain': '[-sqrt(2),sqrt(2)]'}, 'even_only'),
    ('x^2', {'input_domain': '{0,sqrt(2)}'}, 'neither'),
    ('piecewise(-x,x<0,x,x>=0)', {}, 'even_only'),
    ('piecewise(-x^2,x<0,x^2,x>=0)', {}, 'odd_only'),
    ('piecewise(-1,x<0,0,x=0,1,x>0)', {}, 'odd_only'),
    ('piecewise(-1,x<0,1,x>=0)', {}, 'neither'),
    ('piecewise(x^2,x<0,x,x>=0)', {}, 'neither'),
    ('piecewise(x,x<0,x,x>0)^2', {}, 'even_only'),
    ('piecewise(-x,x∈[-2,0),x,x∈[0,2])', {}, 'even_only'),
    ('0', {}, 'both'),
    ('3', {}, 'even_only'),
])
def test_generalized_structures_preserve_original_domain_and_proof(expression, changes, classification):
    goal = described(expression, **changes)
    result = solve(goal)
    assert result['classification'] == classification
    assert verify(goal, decode_value(encode_value(result)))['status'] == 'verified'
    if expression in ('x^2/x', '(x^4-4)/(x^2-2)'):
        forbidden = sp.S.Zero if expression == 'x^2/x' else sp.sqrt(2)
        assert result['domain'].contains(forbidden) is sp.false


@pytest.mark.parametrize('expression,changes,code', [
    ('x^2/x', {'input_domain': '[-1,1]', 'domain_role': 'declared'}, 'declared_domain_conflict'),
    ('sqrt(x)', {'input_domain': '[-2,-1]', 'domain_role': 'restriction'}, 'empty_function_domain'),
    ('piecewise(x,x<0,x,x>0)', {'input_domain': 'ℝ'}, 'declared_domain_conflict'),
])
def test_invalid_domain_contracts_do_not_produce_a_parity_answer(expression, changes, code):
    with pytest.raises(NotationError, match=code):
        solve(described(expression, **changes))


@pytest.mark.parametrize('source', [
    '判断函数 $f(x)=x^2$ 在区间 $[-2,1]$ 上的奇偶性。',
    '判断函数 $f(x)=x^2$ 在 [-2, 1] 上的奇偶性。',
    '判断函数 $f(x)=x^2$，定义域为 $[-2,1]$，求奇偶性。',
    r'判断函数 $f(x)=x^2$，$x\in[-2,1]$ 的奇偶性。',
    '判断函数 $f(x)=x^2$，x∈[-2,1] 的奇偶性。',
])
def test_original_domain_is_required_at_admission_and_bound_to_source(source):
    from shuxueshuo_server.graph_lesson.stage_two.parity_surface import audit_domain

    value = candidate('x^2')
    value['original_text'] = source
    goal = inspect_parity_target(value, TARGET)
    assert not goal['structure_supported'] and goal['reason'] == 'function_parity.source_domain_missing'
    value['root']['goals'][0]['input_domain'] = '[-2,2]'
    goal = inspect_parity_target(value, TARGET)
    assert not goal['structure_supported'] and goal['reason'] == 'function_parity.source_domain_mismatch'
    value['root']['goals'][0]['input_domain'] = '[-2,1]'
    goal = inspect_parity_target(value, TARGET)
    assert goal['structure_supported'] and audit_domain(value, TARGET)
    assert solve(goal)['classification'] == 'neither'


def test_source_domain_omission_blocks_the_type_route(tmp_path):
    value = candidate('x^2')
    value['original_text'] = '判断函数 $f(x)=x^2$ 在 $[-2,1]$ 上的奇偶性。'
    _, stage_two = _prepare(value, tmp_path, 'fp-missing-domain')
    assert not any(goal.get('primary') == 'type-function-parity' for goal in stage_two.get('goals', []))


@pytest.mark.parametrize('source_set', ['R', '$R$', r'$\mathbb R$', '实数集'])
def test_source_real_domain_spellings_are_bound_as_a_set(source_set):
    value = candidate('x^2', input_domain='ℝ')
    value['original_text'] = f'判断函数 $f(x)=x^2$ 的奇偶性，定义域为{source_set}。'
    goal = inspect_parity_target(value, TARGET)
    assert goal['structure_supported'], goal['reason']
    assert solve(goal)['classification'] == 'even_only'


@pytest.mark.parametrize('expression', [
    'sin(x)', 'sqrt(x^3-2)', 'abs(abs(x)-1)', 'piecewise(x,x<=0,x,x>=0)',
])
def test_unsupported_or_overlapping_structures_fail_closed(expression):
    try:
        goal = inspect_parity_target(candidate(expression), TARGET)
    except NotationError:
        return
    assert not goal['structure_supported']


@pytest.mark.parametrize('expression,prop,mutation', [
    ('abs(x+1)-abs(x-1)', 'odd', 'coverage'),
    ('piecewise(-1,x<0,0,x=0,1,x>0)', 'odd', 'zero'),
    ('sqrt(2-x^2)', 'even', 'form'),
])
def test_cell_certificate_tampering_fails_verification(expression, prop, mutation):
    goal = described(expression)
    result = solve(goal)
    rows = result[prop]['comparison']['cells']
    if mutation == 'coverage':
        rows.pop(0)
    elif mutation == 'zero':
        rows[:] = [row for row in rows if row['domain'] != sp.FiniteSet(0)]
    else:
        rows[0]['left'] += 1
    assert verify(goal, result)['status'] == 'math_failed'


@pytest.mark.parametrize('expression,changes,classification', [
    ('0', {}, 'both'),
    ('x', {'input_domain': '{0}'}, 'both'),
    ('piecewise(-x,x<0,x,x>=0)', {}, 'even_only'),
    ('sqrt(2-x^2)', {}, 'even_only'),
    ('x^2/x', {'input_domain': '[-1,1]', 'domain_role': 'restriction'}, 'odd_only'),
])
def test_generalized_courses_have_valid_interactions(expression, changes, classification, tmp_path):
    from shuxueshuo_server.graph_lesson.stage_three import driver, interaction
    from shuxueshuo_server.graph_lesson.stage_three.context import build_context

    value = candidate(expression, **changes)
    prepared, stage_two = _prepare(value, tmp_path, 'fp-generalized')
    assert stage_two['status'] == 'completed', stage_two.get('input_diagnostics')
    assert stage_two['goals'][0]['primary'] == 'type-function-parity'
    context = build_context(value, TARGET)
    state = driver.create_state(
        features=prepared['features'], context=context, method='method-parity-definition',
        route_id='parity-definition', branch='direct', target_ref=TARGET, run_id='fp-generalized', lesson_version='v1')
    for _ in range(100):
        if state['status'] != 'running':
            break
        state = driver.advance(state)
    assert state['status'] == 'method_complete', state.get('diagnostics')
    result = driver.export_values(state)['parity_result']
    assert result['classification'] == classification
    assert verify(context['parity_goal'], result)['status'] == 'verified'
    chunks, pending = interaction.compile_route(state['interaction_seeds'], interaction.load_registry(), revision='0' * 64)
    assert chunks and not pending
    for chunk, _ in chunks:
        interaction.validate_chunk(chunk)
    parts = [part for chunk, _ in chunks for part in chunk['parts']]
    substitution = next(part for part in parts if part['title'] == '代入相反数')
    if expression == '0' or changes.get('input_domain') == '{0}':
        assert substitution['interaction']['type'] == 'read'
        assert substitution['expected_answer'] == {}
    for part in parts:
        if part['interaction']['type'] == 'choice':
            assert len(part['interaction']['options']) >= 2
            assert sum(option['value'] in part['expected_answer']['one_of']
                       for option in part['interaction']['options']) == 1
