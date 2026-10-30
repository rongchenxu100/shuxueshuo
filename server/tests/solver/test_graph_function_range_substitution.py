"""M12 exact coverage, original relation semantics, and M3 child execution."""
from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_one.function_range import inspect_range_target
from shuxueshuo_server.graph_lesson.stage_three.capabilities import LocalCheckFailed
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.function_range import (
    SUBSTITUTION_METHOD,
    admitted,
    image_endpoints,
    independent_verify,
    inputs,
    polynomial_image,
    prepare_range_substitution,
    return_range_substitution,
)
from shuxueshuo_server.graph_lesson.stage_three.range_presentation import phase_view
from tests.solver.test_graph_function_range import TARGET, candidate


def relation_candidate(relation='f(2*x-1)=x^2+2'):
    return {'original_text': f'已知 ${relation}$，求 $f(x)$ 的值域。',
            'root': {'definitions': [relation], 'goals': [{'kind': 'find_range', 'object': 'f'}]}}


CASES = [
    (candidate('x+sqrt(1-x)', '(-8,1)'), sp.Interval.open(0, 3), sp.Interval.Lopen(-5, sp.Rational(5, 4))),
    (candidate('x^2+2*abs(x)-1', 'ℝ'), sp.Interval(0, sp.oo), sp.Interval(-1, sp.oo)),
    (candidate('x-sqrt(1-2*x)', 'ℝ'), sp.Interval(0, sp.oo), sp.Interval(-sp.oo, sp.Rational(1, 2))),
    (relation_candidate(), sp.S.Reals, sp.Interval(2, sp.oo)),
    (relation_candidate('f(3-2*x)=x^2+2'), sp.S.Reals, sp.Interval(2, sp.oo)),
    (candidate('x+sqrt(x+1)', '[-1,3)'), sp.Interval.Ropen(0, 2), sp.Interval.Ropen(-1, 5)),
    (candidate('abs(2*x-1)^2+abs(2*x-1)', '[0,2)'), sp.Interval.Ropen(0, 3), sp.Interval.Ropen(0, 12)),
    (candidate('x^2+2*abs(x)-1', '(-2,2]'), sp.Interval(0, 2), sp.Interval(-1, 7)),
    (candidate('x^2+2*abs(x)-1', '[-3,-2)'), sp.Interval.Lopen(2, 3), sp.Interval.Lopen(7, 14)),
    (candidate('x+sqrt(1-x)', '[0,0]'), sp.FiniteSet(1), sp.FiniteSet(1)),
    (candidate('sqrt(x)^2', '[0,2)'), sp.Interval.Ropen(0, sp.sqrt(2)), sp.Interval.Ropen(0, 2)),
    (candidate('x+sqrt(0*x+4)', '(-1,2]'), sp.Interval.Lopen(-1, 2), sp.Interval.Lopen(1, 4)),
    (candidate('x^2+abs(0*x-1)', '(0,2]'), sp.Interval.Lopen(0, 2), sp.Interval.Lopen(1, 5)),
    (candidate('abs(x)-abs(x)+2', '(-1,1)'), sp.Interval.Ropen(0, 1), sp.FiniteSet(2)),
    (relation_candidate('f(2*x-1)=3'), sp.S.Reals, sp.FiniteSet(3)),
    (relation_candidate('f(2*x-1)=2*x+3'), sp.S.Reals, sp.S.Reals),
    (relation_candidate('f(x+0)=x^2+2'), sp.S.Reals, sp.Interval(2, sp.oo)),
    (candidate('x^2+2*abs(x)-1', '[0,2]'), sp.Interval(0, 2), sp.Interval(-1, 7)),
]


@pytest.mark.parametrize('value,new_domain,expected', CASES)
def test_complete_substitution_image(value, new_domain, expected):
    context = build_context(value, TARGET)
    assert admitted(context, SUBSTITUTION_METHOD)
    prepared = prepare_range_substitution(context)['outputs']
    mapping = prepared['mapping']
    assert mapping['domain'] == new_domain
    child = prepared['child_context']
    assert admitted(child, 'method-quadratic-interval-range')
    expression, variable, domain = inputs(child['range_goal'])
    image = polynomial_image(expression, variable, domain)['outputs']['feasible_set']
    assert image == expected
    assert return_range_substitution(context, mapping, image)['outputs']['feasible_set'] == expected
    assert independent_verify(value, TARGET, context, image)['status'] == 'verified'
    assert image_endpoints(value, TARGET, image)['status'] == 'passed'
    with pytest.raises(LocalCheckFailed):
        return_range_substitution(context, {**mapping, 'domain': sp.S.EmptySet}, image)
    assert independent_verify(value, TARGET, context, sp.S.EmptySet)['status'] == 'math_failed'
    for phase in ('define', 'domain', 'rewrite', 'borrow', 'return'):
        view = phase_view({**prepared, 'phase': 'substitution_'+phase, 'range': {'set': image}})
        assert view['title'] and view['derivation']
    if mapping['kind'] == 'affine' and mapping['forward'] != mapping['original_variable']:
        view = phase_view({**prepared, 'phase': 'substitution_define'})
        assert not view['derivation']['items'][0]['math'].startswith('f(x)=')


@pytest.mark.parametrize('expression', [
    'x^2+sqrt(1-x)', 'x+abs(x)', 'sqrt(x)+sqrt(x+1)',
    'x+sqrt(x^2+1)', 'x+sqrt(x)/x', '(x-1)^0+abs(x)',
    'x+sqrt(0*x-1)', 'm*x+sqrt(x)',
    '((x+abs(x))^4)^4',
])
def test_substitution_fail_closed(expression):
    value = candidate(expression, 'ℝ')
    assert not inspect_range_target(value, TARGET)['structure_supported']


def test_affine_relation_is_not_a_direct_definition_or_a_restricted_relation():
    value = relation_candidate()
    description = inspect_range_target(value, TARGET)
    assert description['relation_input_ast'] != description['expression_ast']
    altered = deepcopy(value)
    altered['root']['goals'][0]['input_domain'] = '[0,1]'
    assert not inspect_range_target(altered, TARGET)['structure_supported']
    assert not inspect_range_target(relation_candidate('f(0*x+1)=x^2+2'), TARGET)['structure_supported']


@pytest.mark.parametrize('body', [
    'sqrt(x)^2', '0*sqrt(x)+3', 'sqrt(x)-sqrt(x)+3', '(x^2-1)/(x-1)',
])
def test_affine_relation_cannot_erase_original_input_restrictions(body):
    value = relation_candidate(f'f(2*x-1)={body}')
    description = inspect_range_target(value, TARGET)
    assert not description['structure_supported']
    assert description['reason'] == 'range.full_real_polynomial_relation_required'
    assert not admitted(build_context(value, TARGET))


@pytest.mark.parametrize('index', [1, 6, 8])
def test_absolute_inverse_branches_are_alternatives_in_cards_and_derivations(index):
    prepared = prepare_range_substitution(build_context(CASES[index][0], TARGET))['outputs']
    view = phase_view({**prepared, 'phase': 'substitution_rewrite'})
    for text in (view['derivation']['items'][0]['math'], view['explanation'], view['feedback']['answer']):
        assert r'\text{或}' in text
        assert r'x=t\\x=-' not in text
        assert '$x=t$\n$x=-' not in text


@pytest.mark.parametrize('value,interaction_type', [
    (relation_candidate('f(x+0)=x^2+2'), 'read'),
    (candidate('x^2+2*abs(x)-1', '[0,2]'), 'read'),
    (candidate('x^2+2*abs(x)-1', '[-3,-2)'), 'choice'),
    (candidate('sqrt(x)^2', '[0,0]'), 'read'),
    (candidate('sqrt(x)^2', '[1,1]'), 'read'),
    (candidate('sqrt(x)^2', '[0,2]'), 'choice'),
    (relation_candidate(), 'choice'),
])
def test_substitution_confirmation_never_rejects_an_equivalent_option_or_emits_one_choice(value, interaction_type):
    import json

    from jsonschema import Draft202012Validator

    from shuxueshuo_server.graph_lesson.stage_three.interaction import CHUNK_SCHEMA
    from shuxueshuo_server.graph_lesson.stage_three.range_presentation import (
        compile_range,
    )
    from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value

    prepared = prepare_range_substitution(build_context(value, TARGET))['outputs']
    part = compile_range([{'values': encode_value({**prepared, 'phase': 'substitution_define'})}], 'a'*24)['parts'][0]
    schema = json.loads(CHUNK_SCHEMA.read_text())
    Draft202012Validator({'$ref': '#/$defs/part', '$defs': schema['$defs']}).validate(part)
    assert part['interaction']['type'] == interaction_type
    if interaction_type == 'choice':
        assert '整体设为新变量' in part['question']
        assert '改写为至多二次式' not in part['question']
        options = part['interaction']['options']
        assert len(options) >= 2 and len({row['label'] for row in options}) == len(options)
        assert part['stem_board']['items'][1]['math'] is None


def test_absolute_substitution_checkpoint_preserves_exact_mapping():
    from shuxueshuo_server.graph_lesson.stage_three.trajectory import (
        decode_value,
        encode_value,
    )
    mapping = prepare_range_substitution(build_context(CASES[1][0], TARGET))['outputs']['mapping']
    assert decode_value(encode_value(mapping)) == mapping


def test_new_variable_endpoint_must_be_supported_before_admission():
    value = candidate('x+sqrt(x+1)', '[0,sqrt(2)]')
    assert not admitted(build_context(value, TARGET), SUBSTITUTION_METHOD)


def test_function_context_switches_from_original_relation_to_child_without_revealing_rewrite():
    from shuxueshuo_server.graph_lesson.stage_three.capabilities import complete_square
    from shuxueshuo_server.graph_lesson.stage_three.range_presentation import (
        compile_range,
        domain_prerequisite,
    )
    from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value

    prepared = prepare_range_substitution(build_context(relation_candidate(), TARGET))['outputs']
    assert 'f(2 x - 1)=x^{2}+2' in domain_prerequisite(prepared['description'])['question']
    for phase in ('substitution_domain', 'substitution_rewrite'):
        part = compile_range([{'values': encode_value({**prepared, 'phase': phase})}], phase)['parts'][0]
        assert 'f(2 x - 1)=x^{2}+2' in part['question']
        assert 'f(x)=x^{2}+2' not in part['question']
        assert 'f(t)=' not in part['question']
        assert part['stem_board']['items'][1]['math'] is None
    description = prepared['child_context']['range_goal']
    expression, variable, domain = inputs(description)
    values = {'description': description, 'function': expression, 'variable': variable, 'domain': domain,
              **complete_square(expression, variable)['outputs'],
              **polynomial_image(expression, variable, domain)['outputs']}
    for phase in ('position', 'values', 'image'):
        part = compile_range([{'values': encode_value({**values, 'phase': phase})}], phase)['parts'][0]
        assert r'f(t)=\frac{t^{2}}{4} + \frac{t}{2} + \frac{9}{4}' in part['question']
        assert 'f(2 x - 1)' not in part['question']
        assert part['stem_board']['items'][1]['math'] is None


@pytest.mark.parametrize('index', [0, 1, 2, 3, 10, 14, 16, 17])
def test_substitution_lesson_executes_real_child_method(tmp_path, index):
    from shuxueshuo_server.graph_lesson.stage_three import runner
    from tests.solver.test_graph_stage_three_execution import (
        constructed_upstream,
        store,
    )
    from tools.export_graph_walk_course import export_course
    value, _, expected = CASES[index]
    upstream = constructed_upstream(tmp_path, value)
    output = tmp_path/'run'
    result = runner.run_sample(upstream, output)
    assert result['status'] == 'completed', result
    goal = result['goals'][0]
    assert goal['status'] == 'solved', result
    assert sp.sympify(goal['answer']['set']['expression']) == expected
    snapshot = store(output).snapshot()
    assert all(row['status'] == 'interactive' for row in snapshot['interaction_states'])
    evidence = export_course(output, 'function-concepts-range-q08')
    lesson = evidence['lesson']['goals'][0]
    assert lesson['d1']['rows'] and not lesson['d1'].get('diagnostics')
    assert lesson['walk'] is not None
    serialized = str(evidence['stream'])
    assert '确定新变量范围' in serialized
    assert 'method-quadratic-interval-range' in str(evidence)

@pytest.mark.parametrize('printed', [
    r'y=x+\sqrt{1-x}(-8<x<1)',
    r'y=x+\sqrt{1-x},\quad -8<x<1',
    r'y=x+\sqrt{1-x}\left(-8<x<1\right)',
])
def test_original_formula_with_attached_input_annotation(printed):
    from shuxueshuo_server.graph_lesson.stage_two.fragments import (
        _abstract_formula_matches,
    )
    from shuxueshuo_server.graph_lesson.stage_two.range_surface import (
        range_source_spans,
    )
    value = candidate('x+sqrt(1-x)', '(-8,1)')
    value['original_text'] = f'函数 ${printed}$ 的值域是 ______。'
    desc = inspect_range_target(value, TARGET)
    def locate(source):
        return range_source_spans(source, TARGET, [(0, len(source['original_text']))], desc, _abstract_formula_matches)
    assert locate(value)
    for wrong in ('-8<x<=1', '-7<x<1', '-8<t<1'):
        altered = {**value, 'original_text': value['original_text'].replace('-8<x<1', wrong)}
        assert locate(altered) is None

@pytest.mark.parametrize('absolute', [r'|x|', r'\lvert x\rvert', r'\left|x\right|', 'abs(x)'])
def test_absolute_value_printing_keeps_original_source_tree(absolute):
    from shuxueshuo_server.graph_lesson.stage_two.fragments import (
        _abstract_formula_matches,
    )
    body = f'f(x)=x^2+2{absolute}-1'
    assert _abstract_formula_matches(body, 'f(x)=x^2+2*abs(x)-1')
    assert not _abstract_formula_matches(body, 'f(x)=x^2+2*x-1')
    assert not _abstract_formula_matches(body, 'f(x)=x^2+2*abs(x+1)-1')
