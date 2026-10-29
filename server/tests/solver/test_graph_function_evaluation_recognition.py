"""T4 source-preserving IR, independent targets and bounded recognition."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from shuxueshuo_server.graph_lesson.stage_one import contracts
from shuxueshuo_server.graph_lesson.stage_one.extraction import frozen_files
from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_one.function_evaluation import inspect_evaluation_target
from shuxueshuo_server.graph_lesson.stage_two.contracts import validate_input
from shuxueshuo_server.graph_lesson.stage_two.evaluation_surface import evaluation_source_spans, sum_source_matches
from shuxueshuo_server.graph_lesson.stage_two.fragments import _abstract_formula_matches
from shuxueshuo_server.graph_lesson.stage_two.recognition import evaluate_types
from shuxueshuo_server.graph_lesson.stage_two.runner import run_result
from shuxueshuo_server.problem_understanding.notation_compile import NotationValidator
from shuxueshuo_server.search.extraction import SearchStageOneContract
from shuxueshuo_server.search.identity import mathematical_candidate
from tests.solver.test_graph_stage_two_input_values import accepted, student_upload

FIXTURES = Path(__file__).parent / 'fixtures/function-evaluation'


def candidate(name='q28a'):
    return json.loads((FIXTURES / (name + '-candidate.json')).read_text())


def compile_root(value):
    return NotationValidator().validate_root(value['root'], contracts.schema()['$defs'])


@pytest.mark.parametrize('name,count', [('q28a', 2), ('q28b', 2), ('q28c', 2), ('q28d', 1), ('q29b', 2)])
def test_five_source_complete_candidates_preserve_nine_independent_targets(name, count):
    value = candidate(name)
    before = deepcopy(value)
    checked = SearchStageOneContract().parse(json.dumps(value), problem_id=name,
                                            source_hash='fixture', registry=[], store=None)
    assert checked['contract_valid'], checked
    result = extract_features(value)
    assert result['ok'], result
    envelope = student_upload(accepted())
    envelope.update(candidate=mathematical_candidate(value), features=result['features'])
    validation = validate_input(envelope, admission='student_upload')
    assert validation['ok'], validation
    assert len(value['root']['goals']) == count
    assert 'children' not in value['root']
    for index in range(count):
        target = f'/root/goals/{index}'
        features = [row for row in result['features'] if row['target_ref'] == target]
        assert [row['type_id'] for row in evaluate_types(features) if row['status'] == 'supported'] == ['type-function-evaluation']
        description = inspect_evaluation_target(value, target)
        spans = evaluation_source_spans(value, target, [(0, len(value['original_text']))],
                                        description, _abstract_formula_matches)
        assert spans
        assert len(description['functions']) == len(value['root']['definitions'])
    assert value == before


@pytest.mark.parametrize('variable', [None, 7, '', {}, []])
def test_function_display_variable_is_a_nonempty_string_at_the_feature_boundary(variable):
    value = candidate()
    envelope = student_upload(accepted())
    envelope.update(candidate=mathematical_candidate(value), features=extract_features(value)['features'])
    description = next(row['value'] for row in envelope['features']
                       if row['feature_id'] == 'function_evaluation')
    description['functions'][0]['variable'] = variable
    validation = validate_input(envelope, admission='student_upload')
    assert not validation['ok']
    assert any(row['code'] == 'input.feature_value'
               and row['path'].endswith('/functions/0/variable')
               for row in validation['diagnostics'])


def test_function_feature_boundary_still_rejects_unregistered_fields():
    value = candidate()
    envelope = student_upload(accepted())
    envelope.update(candidate=mathematical_candidate(value), features=extract_features(value)['features'])
    description = next(row['value'] for row in envelope['features']
                       if row['feature_id'] == 'function_evaluation')
    description['functions'][0]['unregistered_field'] = 'x'
    assert not validate_input(envelope, admission='student_upload')['ok']


@pytest.mark.parametrize('separator', [', ', r',\quad ', '，', '、', '; ', '；'])
def test_grouped_definitions_and_goals_keep_exact_individual_source_spans(separator):
    value = candidate()
    value['original_text'] = (
        '$f(x)=3x^2-1' + separator + r'g(x)=\frac{1}{x+2}$，求 $f(1)' + separator + 'g(1)$。')
    text = value['original_text']
    for index in range(2):
        target = f'/root/goals/{index}'
        description = inspect_evaluation_target(value, target)
        spans = evaluation_source_spans(value, target, [(0, len(text))],
                                        description, _abstract_formula_matches)
        assert spans
        assert [refs for _, _, _, refs in spans] == [
            ['/root/definitions/0'], ['/root/definitions/1'], [target]]
        expected = ['f(x)=3x^2-1', r'g(x)=\frac{1}{x+2}', ('f(1)', 'g(1)')[index]]
        canonical = [*value['root']['definitions'], value['root']['goals'][index]['expression']]
        for (start, end, _, _), formula, source in zip(spans, expected, canonical, strict=True):
            assert text[start:end].endswith(formula)
            assert _abstract_formula_matches(text[start:end], source)


def test_grouped_formula_student_upload_generates_both_reading_interactions(tmp_path):
    value = candidate()
    text = r'已知 $f(x)=3x^2-1,\quad g(x)=\frac{1}{x+2}$，求 $f(1),g(1)$。'
    value['original_text'] = value['public_content']['scopes'][0]['statement'] = text
    envelope = student_upload(accepted())
    envelope.update(candidate=mathematical_candidate(value), features=extract_features(value)['features'])
    result = run_result(envelope, tmp_path / 'grouped', admission='student_upload')
    assert result['status'] == 'completed'
    assert len(result['goals']) == 2
    for index, goal in enumerate(result['goals']):
        assert not goal['d1']['diagnostics']
        fragments = goal['d1']['fragments']
        assert len(fragments) == 3
        assert fragments[-1]['text'] == ('f(1)', 'g(1)')[index]
        for fragment in fragments:
            assert fragment['text'] == text[fragment['start']:fragment['end']]


@pytest.mark.parametrize('body', [
    'g(f(1)),g(1)', 'f(1)+g(1)', 'f(1)^2,g(1)', r'f(1)\,g(1)',
    r'\frac{f(1)}{2},g(1)', 'h(f(1),g(1))',
])
def test_grouped_formula_matching_never_extracts_a_target_subexpression(body):
    value = candidate()
    value['original_text'] = r'已知 $f(x)=3x^2-1,g(x)=\frac{1}{x+2}$，求 $' + body + '$。'
    description = inspect_evaluation_target(value, '/root/goals/0')
    assert evaluation_source_spans(value, '/root/goals/0', [(0, len(value['original_text']))],
                                   description, _abstract_formula_matches) is None


def test_grouped_domain_intervals_and_function_definitions_remain_whole():
    value = candidate('q28c')
    value['root']['facts'] = ['Dom(f)=[0,2]']
    value['root']['goals'][0]['input_domain'] = '[0,1]'
    value['original_text'] = (
        r'$f(x)=3x^2-1,g(x)=\frac{1}{x+2},Dom(f)=[0,2]$，'
        r'当 $x\in[0,1]$ 时，求 $f(x-1),g(\frac{1}{x}-1)$。')
    text, target = value['original_text'], '/root/goals/0'
    description = inspect_evaluation_target(value, target)
    spans = evaluation_source_spans(value, target, [(0, len(text))], description, _abstract_formula_matches)
    assert spans
    by_ref = {refs[0]: text[start:end] for start, end, _, refs in spans}
    assert by_ref['/root/facts/0'] == 'Dom(f)=[0,2]'
    assert by_ref[target+'/input_domain'] == r'x\in[0,1]'


def test_original_nested_order_and_divisor_survive_binding_without_evaluation():
    report = compile_root(candidate('q28b'))
    first, second = report.semantic['goals']
    assert first['target'][1][1] == second['target'][2][1][1]
    assert first['target'][2][1][1] == second['target'][1][1]
    report = compile_root(candidate('q28c'))
    target = report.semantic['goals'][1]['target']
    assert target[2][0] == '-'
    assert target[2][1][0] == '/'
    assert target[2][1][2] == ['ref', 'r:scalar:x', 'scalar']


def test_sum_indices_are_local_and_do_not_capture_the_constant_goal_variable():
    value = candidate('q29b')
    for term in value['root']['goals'][1]['terms']:
        term['expression'] = term['expression'].replace('n', 'x')
        term['index'] = 'x'
    report = compile_root(value)
    assert report.ok, report.issues
    first, second = report.semantic['goals']
    refs = [term['index'][1] for term in second['terms']]
    assert len(set(refs)) == 2
    assert 'r:scalar:x' not in refs
    assert first['target'][1][2] == ['ref', 'r:scalar:x', 'scalar']
    assert second['terms'][0]['target'][2][1] == refs[0]


@pytest.mark.parametrize('domain', ['[0,2]', '(0,2)', '{0,1,2}', 'ℝ∖{-1,1/2}'])
def test_explicit_domains_bind_to_their_own_visible_function(domain):
    value = candidate()
    value['root']['facts'] = [f'Dom(f)={domain}']
    report = compile_root(value)
    assert report.ok, report.issues
    description = inspect_evaluation_target(value, '/root/goals/0')
    f, g = description['functions']
    assert f['explicit_domain'] and f['input_domain_source_ref'] == '/root/facts/0'
    assert not g['explicit_domain'] and g['input_domain_ast'] == ['real']


@pytest.mark.parametrize('fact', ['x>0', 'f(1)=2', 'Dom(f)=[0,1]'])
def test_unknown_or_conflicting_given_conditions_are_not_silently_dropped(fact):
    value = candidate()
    value['root']['facts'] = ['Dom(f)=[0,2]', fact]
    description = inspect_evaluation_target(value, '/root/goals/0')
    assert not description['structure_supported']


@pytest.mark.parametrize('expression', ['g(f(0))', 'f(g(1))', 'f(0)'])
def test_mismatched_target_source_does_not_get_a_reading_fragment(expression):
    value = candidate('q28b')
    value['root']['goals'][0]['expression'] = expression
    # Remove the other target's occurrence so each mutation is independently unbound.
    value['original_text'] = '已知函数 $f(x)=3x^2-1$，$g(x)=1/(x+2)$，求 $f(g(0))$。'
    description = inspect_evaluation_target(value, '/root/goals/0')
    assert evaluation_source_spans(value, '/root/goals/0', [(0, len(value['original_text']))],
                                   description, _abstract_formula_matches) is None


@pytest.mark.parametrize('limit', [1, 2, 7, 101, 173])
def test_sum_source_ellipsis_is_bound_to_actual_counts_and_endpoints(limit):
    terms = [{'expression':'f(n)', 'index':'n', 'lower':1, 'upper':limit}]
    source = 'f(1)' if limit == 1 else 'f(1)+f(2)' if limit == 2 else f'f(1)+f(2)+\\cdots+f({limit})'
    assert sum_source_matches(source, terms, _abstract_formula_matches)
    assert not sum_source_matches(source + '+f(1)', terms, _abstract_formula_matches)
    terms[0]['upper'] += 1
    assert not sum_source_matches(source, terms, _abstract_formula_matches)


def test_missing_sum_endpoint_and_wrong_duplicate_multiplicity_fail_source_binding():
    terms = [{'expression':'f(1)'}, {'expression':'f(1)'}, {'expression':'f(2)'}]
    assert sum_source_matches('f(1)+f(1)+f(2)', terms, _abstract_formula_matches)
    assert not sum_source_matches('f(1)+f(2)', terms, _abstract_formula_matches)
    assert not sum_source_matches('f(1)+…', terms, _abstract_formula_matches)


def test_explicit_integer_sum_source_binds_its_own_index_and_bounds():
    terms = [{'expression': 'f(n)', 'index': 'n', 'lower': 2, 'upper': 7},
             {'expression': 'f(1/n)', 'index': 'n', 'lower': 2, 'upper': 7}]
    text = r'\sum_{k=2}^{7} f(k)+\sum_{j=2}^{7} f(1/j)'
    assert sum_source_matches(text, terms, _abstract_formula_matches)
    assert not sum_source_matches(text.replace('^{7}', '^{8}', 1), terms, _abstract_formula_matches)


def test_explicit_sum_instantiates_shifted_indices_without_cancelling_undefined_inputs():
    terms = [{'expression': 'f(n+1)', 'index': 'n', 'lower': 1, 'upper': 3}]
    assert sum_source_matches(r'\sum_{k=1}^{3} f(k+1)', terms, _abstract_formula_matches)
    singular = r'\sum_{k=1}^{3} f((k^2-1)/(k-1))'
    # The k=1 source input is undefined, even though cancelling would give k+1.
    assert not sum_source_matches(singular, terms, _abstract_formula_matches)
    terms[0]['expression'] = 'f((n^2-1)/(n-1))'
    assert sum_source_matches(singular, terms, _abstract_formula_matches)


@pytest.mark.parametrize('condition,valid', [
    ('，当 $x\\in[0,1]$ 时', True),
    ('', False),
    ('，当 $t\\in[0,1]$ 时', False),
    ('，当 $x\\in[0,2]$ 时', False),
])
def test_goal_input_domain_requires_original_source_for_the_same_outer_variable(condition, valid):
    value = candidate('q28c')
    target = '/root/goals/0'
    value['root']['goals'][0]['input_domain'] = '[0,1]'
    value['original_text'] = (
        '已知函数 $f(x)=3x^2-1$，$g(x)=1/(x+2)$' + condition + '，求 $f(x-1)$。')
    description = inspect_evaluation_target(value, target)
    spans = evaluation_source_spans(value, target, [(0, len(value['original_text']))],
                                   description, _abstract_formula_matches)
    assert bool(spans) is valid
    if valid:
        assert any(target+'/input_domain' in span[3] for span in spans)


@pytest.mark.parametrize('text,valid', [
    ('已知函数 $f(x)=3x^2-1$，定义域为 $[0,2]$，$g(x)=1/(x+2)$，求 $f(1)$。', True),
    ('已知函数 $f(x)=3x^2-1$，$Dom(f)=[0,2]$，$g(x)=1/(x+2)$，求 $f(1)$。', True),
    ('已知函数 $f(x)=3x^2-1$，$g(x)=1/(x+2)$，定义域为 $[0,2]$，求 $f(1)$。', False),
    ('已知函数 $f(x)=3x^2-1$，定义域为 $[0,3]$，$g(x)=1/(x+2)$，求 $f(1)$。', False),
])
def test_source_explicit_domain_must_belong_to_the_same_function(text, valid):
    value = candidate()
    value['root']['facts'] = ['Dom(f)=[0,2]']
    value['original_text'] = text
    description = inspect_evaluation_target(value, '/root/goals/0')
    spans = evaluation_source_spans(value, '/root/goals/0', [(0, len(text))],
                                    description, _abstract_formula_matches)
    assert bool(spans) is valid


def test_evaluation_math_module_is_an_actual_stage_one_fingerprint_input(monkeypatch):
    path = 'server/shuxueshuo_server/graph_lesson/function_evaluation.py'
    before = frozen_files()
    assert path in before
    original = Path.read_bytes
    def changed_read(file):
        data = original(file)
        return data+b'\n# changed evaluation source\n' if file.as_posix().endswith(path) else data
    monkeypatch.setattr(Path, 'read_bytes', changed_read)
    assert frozen_files()[path] != before[path]


def test_extraction_review_repair_share_the_independent_subquestion_completeness_rule():
    for prompt in (contracts.SYSTEM, contracts.REVIEW_SYSTEM, contracts.REPAIR_SYSTEM):
        assert '编号不是数学依赖' in prompt
        assert '不要求补拍上一问' in prompt
        assert '只有当前所求真正依赖的条件或明确引用的前问结果' in prompt
    value = candidate('q29b')
    value['original_text'] = value['original_text'].replace('判断', '（2）判断', 1)
    checked = SearchStageOneContract().parse(json.dumps(value), problem_id='q29b-cropped',
                                            source_hash='fixture', registry=[], store=None)
    assert checked['contract_valid'], checked
    assert [goal['kind'] for goal in value['root']['goals']] == ['check_constant', 'finite_sum']
    assert not value['root'].get('uncertainties')
