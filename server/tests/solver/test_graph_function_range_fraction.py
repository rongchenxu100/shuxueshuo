"""M5: original poles, disconnected reciprocal images and real child lessons."""
from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three.capabilities import LocalCheckFailed
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.function_range import (
    FRACTION_METHOD,
    admitted,
    image_endpoints,
    independent_verify,
    inputs,
    polynomial_image,
    prepare_fraction_range,
    return_fraction_range,
)
from tests.solver.test_graph_function_range import TARGET, candidate


def test_fingerprint_freezes_fraction_range_math_and_presentation():
    from hashlib import sha256
    from pathlib import Path
    from shuxueshuo_server.graph_lesson.stage_three import (
        execution_contracts, fraction_range, fraction_range_presentation, runner,
    )
    root = Path(__file__).resolve().parents[3]
    frozen, direct = runner.fingerprint(), execution_contracts.revisions()
    for module in (fraction_range, fraction_range_presentation):
        source = Path(module.__file__).resolve()
        digest = sha256(source.read_bytes()).hexdigest()
        assert frozen[str(source.relative_to(root))] == digest
        assert direct[source.stem] == digest


CASES = [
    ('(2*x^2-2*x+1)/(x^2-x+1)', 'ℝ', sp.Interval.Ropen(sp.Rational(2,3),2)),
    ('(x+1)/(x-2)', 'ℝ', sp.S.Reals-sp.FiniteSet(1)),
    ('(x^2-x)/(x^2-x+1)', 'ℝ', sp.Interval.Ropen(-sp.Rational(1,3),1)),
    ('(2-3*x)/(x-1)', 'ℝ', sp.S.Reals-sp.FiniteSet(-3)),
    ('(2*x+1)/(x-3)', 'ℝ', sp.S.Reals-sp.FiniteSet(2)),
    ('1/(x^2-2)', 'ℝ', sp.Union(sp.Interval(-sp.oo,-sp.Rational(1,2)),sp.Interval.open(0,sp.oo))),
    ('2+3/(x^2+1)', '(-1,2]', sp.Interval.Ropen(sp.Rational(13,5),5)|sp.FiniteSet(5)),
    ('1/(-x^2-1)', 'ℝ', sp.Interval.Ropen(-1,0)),
    ('0/(x-1)+3', 'ℝ', sp.FiniteSet(3)),
    ('x/x', 'ℝ', sp.FiniteSet(1)),
    ('((x-1)/(x-1))/(x^2+1)', 'ℝ', sp.Interval.Lopen(0,1)),
    ('((x^2-1)/(x^2-1))/(x^2+1)', 'ℝ', sp.Interval.Lopen(0,1)-sp.FiniteSet(sp.Rational(1,2))),
    ('(x/x)/(x^2+1)', 'ℝ', sp.Interval.open(0,1)),
    ('1/(x-1)', '[2,2]', sp.FiniteSet(1)),
    ('1/(100*x^2+100)', 'ℝ', sp.Interval.Lopen(0, sp.Rational(1, 100))),
]

@pytest.mark.parametrize('expression,domain,expected', CASES)
def test_fraction_complete_image(expression,domain,expected):
    value=candidate(expression,domain);context=build_context(value,TARGET)
    assert admitted(context,FRACTION_METHOD)
    assert not admitted(context,'method-quadratic-interval-range')
    prepared=prepare_fraction_range(context)['outputs'];mapping=prepared['mapping']
    child=prepared['child_context']
    assert admitted(child,'method-quadratic-interval-range')
    q,x,effective=inputs(child['range_goal'])
    image=polynomial_image(q,x,effective)['outputs']['feasible_set']
    actual=return_fraction_range(context,mapping,image)['outputs']['feasible_set']
    assert actual==expected
    assert independent_verify(value,TARGET,context,actual)['status']=='verified'
    assert image_endpoints(value,TARGET,actual)['status']=='passed'
    assert independent_verify(value,TARGET,context,actual.symmetric_difference(sp.FiniteSet(123)))['status']=='math_failed'
    with pytest.raises(LocalCheckFailed):return_fraction_range(context,mapping,image|sp.FiniteSet(0))
    wrong=deepcopy(mapping);wrong['scale']+=1
    with pytest.raises(LocalCheckFailed):return_fraction_range(context,wrong,image)

@pytest.mark.parametrize('expression', ['x^3/(x^2+1)','1/(x-x)','1/(x^3+1)'])
def test_fraction_admission_rejects_unimplemented_or_undefined(expression):
    assert not admitted(build_context(candidate(expression,'ℝ'),TARGET),FRACTION_METHOD)


def test_narrow_fraction_image_keeps_choices_when_number_line_marks_overlap():
    from shuxueshuo_server.graph_lesson.stage_three.range_presentation import compile_range
    from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value

    context = build_context(candidate('1/(100*x^2+100)', 'ℝ'), TARGET)
    values = prepare_fraction_range(context)['outputs']
    mapping = values['mapping']
    image = polynomial_image(mapping['function'], mapping['variable'], mapping['domain'])['outputs']['feasible_set']
    values.update(return_fraction_range(context, mapping, image)['outputs'])
    assert values['feasible_set'] == sp.Interval.Lopen(0, sp.Rational(1, 100))
    compiled = compile_range([{'values': encode_value({**values, 'phase': 'fraction_return'})}], 'narrow-image')
    assert compiled['diagnostics'] == [{'kind': 'graph_unavailable', 'reason': 'marks_overlap'}]
    part = compiled['parts'][0]
    assert part['interaction']['type'] == 'choice'
    assert part['expected_answer']['one_of']
    assert part['stem_board']['items'][1]['math'] is None
    assert part['completion_board']['items'][1]['math']
    assert 'completion_graph' not in part and 'completion_graphs' not in part


@pytest.mark.parametrize('phase', ['fraction_denominator', 'fraction_nonzero', 'fraction_return'])
def test_linear_fraction_graph_failure_preserves_the_math_interaction(monkeypatch, phase):
    from shuxueshuo_server.graph_lesson.stage_three import interaction_graphs as drawing
    from shuxueshuo_server.graph_lesson.stage_three.fraction_range import solve_fraction_intermediate
    from shuxueshuo_server.graph_lesson.stage_three.range_presentation import compile_range
    from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value

    context = build_context(candidate('x/(x^2+1)', 'ℝ'), TARGET)
    values = prepare_fraction_range(context)['outputs']
    mapping = values['mapping']
    image = solve_fraction_intermediate(context, mapping)['outputs']['image']
    values.update(return_fraction_range(context, mapping, image)['outputs'])
    seed = {'values': encode_value({**values, 'phase': phase})}
    expected = compile_range([seed], 'linear-fallback')['parts'][0]

    def unavailable(*args, **kwargs):
        raise drawing.GraphUnavailable('marks_overlap')

    monkeypatch.setattr(drawing, 'number_lines', unavailable)
    compiled = compile_range([seed], 'linear-fallback')
    assert compiled['diagnostics'] == [{'kind': 'graph_unavailable', 'reason': 'marks_overlap'}]
    part = compiled['parts'][0]
    for field in ('interaction', 'expected_answer', 'stem_board', 'completion_board'):
        assert part[field] == expected[field]
    assert 'completion_graph' not in part and 'completion_graphs' not in part


def test_declared_domain_cannot_restore_an_original_pole():
    value=candidate('1/x','ℝ');value['root']['facts']=['Dom(f)=ℝ']
    assert not admitted(build_context(value,TARGET),FRACTION_METHOD)


LINEAR_CASES = [
    ('(2*x^2+3*x+2)/(x^2+x+1)', 'ℝ', sp.Interval(1, sp.Rational(7,3))),
    ('(x+1)/(x^2+1)', 'ℝ', sp.Interval((1-sp.sqrt(2))/2, (1+sp.sqrt(2))/2)),
    ('-x/(x^2+1)', 'ℝ', sp.Interval(-sp.Rational(1,2), sp.Rational(1,2))),
    ('x/(x^2-1)', 'ℝ', sp.S.Reals),
    ('x/(x^2+1)', '(2,4]', sp.Interval.Ropen(sp.Rational(4,17), sp.Rational(2,5))),
    ('x/(x^2+1)', '(0,1)', sp.Interval.open(0, sp.Rational(1,2))),
    ('x/(x^2+1)', 'ℝ∖{0,1}', sp.Interval.Ropen(-sp.Rational(1,2),sp.Rational(1,2))-sp.FiniteSet(0)),
    ('x/(x^2+1)', '[0,0]', sp.FiniteSet(0)),
]


@pytest.mark.parametrize('expression,domain,separated,divisor,zero', [
    ('(2*x^2+3*x+2)/(x^2+x+1)', 'ℝ', r'f(x)=2+\frac{x}{x^{2} + x + 1}', 'x', 'x=0'),
    ('(x+1)/(x^2+1)', 'ℝ', r'f(x)=0+\frac{x + 1}{x^{2} + 1}', 'x + 1', 'x=-1'),
    ('-x/(x^2+1)', '(0,1)', r'f(x)=0+\frac{- x}{x^{2} + 1}', 'x', 'x=0'),
])
def test_fraction_zero_card_explains_division_from_separated_form(expression, domain, separated, divisor, zero):
    from shuxueshuo_server.graph_lesson.stage_three.range_presentation import phase_view, _source_definition

    values = prepare_fraction_range(build_context(candidate(expression, domain), TARGET))['outputs']
    card = phase_view({**values, 'phase': 'fraction_zero'})
    question = card['question']
    assert f'分离常数后，${separated}$' in question
    assert _source_definition(values['description'], values['variable']) not in question
    assert f'分子、分母同除以 ${divisor}$' in question
    assert '倒数' in question and '不能为零' in question
    assert f'当 ${zero}$ 时' in question


@pytest.mark.parametrize('expression,separated,dividing,divided,named', [
    ('(2*x^2+3*x+2)/(x^2+x+1)', r'f(x)=2+\frac{x}{x^{2} + x + 1}',
     r'f(x)=2+\frac{x}{x^{2} + x + 1}', r'f(x)=2+\frac{1}{x + 1 + \frac{1}{x}}',
     r'f(x)=2+\frac{1}{Q(x)}'),
    ('(x+1)/(x^2+1)', r'f(x)=0+\frac{x + 1}{x^{2} + 1}',
     r'f(t - 1)=0+\frac{t}{t^{2} - 2 t + 2}', r'f(t - 1)=0+\frac{1}{t - 2 + \frac{2}{t}}',
     r'f(t - 1)=\frac{1}{Q(t)}'),
])
def test_fraction_cards_follow_the_current_form(expression, separated, dividing, divided, named):
    from shuxueshuo_server.graph_lesson.stage_three.fraction_range import solve_fraction_intermediate
    from shuxueshuo_server.graph_lesson.stage_three.range_presentation import phase_view, _source_definition

    context = build_context(candidate(expression, 'ℝ'), TARGET)
    values = prepare_fraction_range(context)['outputs']
    mapping = values['mapping']
    image = solve_fraction_intermediate(context, mapping)['outputs']['image']
    values.update(return_fraction_range(context, mapping, image)['outputs'])
    source = _source_definition(values['description'], values['variable'])
    for phase, formula in [('fraction_substitution', separated), ('fraction_divide', dividing),
                           ('fraction_denominator', divided), ('fraction_reciprocal', named),
                           ('fraction_nonzero', named), ('fraction_return', separated)]:
        card = phase_view({**values, 'phase': phase})
        premises = card['question'] + card['derivation']['items'][0]['math']
        assert formula in premises, (phase, premises)
        assert source not in premises, (phase, premises)
        if phase in ('fraction_denominator', 'fraction_reciprocal', 'fraction_nonzero'):
            assert f'Q({mapping["variable"]})' in card['derivation']['items'][0]['math']
        if phase == 'fraction_return':
            assert divided not in premises  # The merged result includes the zero-input branch.
    initial = phase_view({**values, 'phase': 'fraction_separate'})
    assert source in initial['derivation']['items'][0]['math']


@pytest.mark.parametrize('expression,named', [
    (CASES[0][0], r'f(x)=2-\frac{1}{Q(x)}'),
    (CASES[1][0], r'f(x)=1+\frac{3}{Q(x)}'),
])
def test_constant_remainder_cards_use_named_denominator_after_introducing_it(expression, named):
    from shuxueshuo_server.graph_lesson.stage_three.range_presentation import phase_view, _source_definition

    context = build_context(candidate(expression, 'ℝ'), TARGET)
    values = prepare_fraction_range(context)['outputs']
    q, x, domain = inputs(values['child_context']['range_goal'])
    image = polynomial_image(q, x, domain)['outputs']['feasible_set']
    values.update(return_fraction_range(context, values['mapping'], image)['outputs'])
    separate = phase_view({**values, 'phase': 'fraction_separate'})['derivation']['items'][1]['math']
    source = _source_definition(values['description'], values['variable'])
    for phase in ('fraction_borrow', 'fraction_reciprocal', 'fraction_return'):
        card = phase_view({**values, 'phase': phase})
        premises = card['question'] + card['derivation']['items'][0]['math']
        assert (separate if phase == 'fraction_borrow' else named) in premises, (phase, premises)
        assert source not in premises, (phase, premises)


def test_linear_denominator_card_selects_the_complete_image_with_its_hole():
    from shuxueshuo_server.graph_lesson.stage_three.function_range import prepare_function_range
    from shuxueshuo_server.graph_lesson.stage_three.range_presentation import phase_view, _set_latex

    values = prepare_fraction_range(build_context(candidate('(x+1)/(x-2)', 'ℝ'), TARGET))['outputs']
    child = prepare_function_range(values['child_context'])['outputs']
    q, x, domain = child['function'], child['variable'], child['domain']
    outputs = polynomial_image(q, x, domain)['outputs']
    expected_image = sp.S.Reals - sp.FiniteSet(0)
    assert child['compare_values'] is False
    assert outputs['feasible_set'] == expected_image
    card = phase_view({**child, **outputs, 'phase': 'image'})
    assert 'Q(x)' in card['question']
    assert r'Q(x)=x - 2' in card['derivation']['items'][0]['math']
    assert _set_latex(domain) in card['derivation']['items'][0]['math']
    answers = card['expected_answer']['one_of']
    assert [option['label'] for option in card['interaction']['options'] if option['value'] in answers] == [
        f'${_set_latex(expected_image)}$']
    assert not any('无界' in option['label'] for option in card['interaction']['options'])


@pytest.mark.parametrize('expression', [CASES[0][0], CASES[1][0], LINEAR_CASES[0][0]])
def test_reciprocal_step_plots_denominator_values_on_the_same_two_branch_graph(expression):
    from shuxueshuo_server.graph_lesson.stage_three.fraction_range import solve_fraction_intermediate
    from shuxueshuo_server.graph_lesson.stage_three.interaction_graph_contract import validate_part_graphs
    from shuxueshuo_server.graph_lesson.stage_three.range_presentation import _compile_range_values

    context = build_context(candidate(expression, 'ℝ'), TARGET)
    values = prepare_fraction_range(context)['outputs']
    mapping = values['mapping']
    if mapping.get('linear'):
        image = solve_fraction_intermediate(context, mapping)['outputs']['image']
    else:
        q, x, domain = inputs(values['child_context']['range_goal'])
        image = polynomial_image(q, x, domain)['outputs']['feasible_set']
    values.update(return_fraction_range(context, mapping, image)['outputs'])
    compiled = _compile_range_values({**values, 'phase': 'fraction_reciprocal'}, 'reciprocal')
    assert not compiled['diagnostics']
    validate_part_graphs(compiled['parts'])
    part = compiled['parts'][0]
    assert part['graph'] == part['completion_graph']
    graph = part['graph']
    assert graph['kind'] == 'reciprocal_sum'
    assert (graph['params']['a'], graph['params']['b']) == (0, 1)
    assert graph['params']['variable'] == 'u'
    assert graph['params']['outputVariable'] == 'v'
    assert '$u=Q(x)$' in graph['caption']
    assert part['stem_board']['items'][1]['math'] is None
    if expression == CASES[1][0]:
        assert graph['params']['pieces'] == [
            {'from': None, 'to': 0.0, 'left_closed': False, 'right_closed': False},
            {'from': 0.0, 'to': None, 'left_closed': False, 'right_closed': False},
        ]
        assert graph['params']['points'] == []  # Zero is an asymptote, never an endpoint on the curve.


@pytest.mark.parametrize('domain,points', [
    (sp.Interval.Ropen(1, 3), [{'x': 1.0}, {'x': 3.0, 'open': True}]),
    (sp.Interval.Lopen(-3, -1), [{'x': -3.0, 'open': True}, {'x': -1.0}]),
    (sp.S.Reals-sp.FiniteSet(0, 2), [{'x': 2.0, 'open': True}]),
    (sp.FiniteSet(2), [{'x': 2.0}]),
])
def test_reciprocal_range_graph_preserves_holes_and_endpoint_inclusion(domain, points):
    from shuxueshuo_server.graph_lesson.stage_three import interaction_graphs as drawing
    from shuxueshuo_server.graph_lesson.stage_three.interaction_graph_contract import validate_graph

    graph = drawing.reciprocal_image_graph(domain, source='Q(t)')
    validate_graph(graph)
    assert graph['params']['points'] == points
    assert 'Q(t)' in graph['caption']
    for point in points:
        assert point['x'] != 0
        assert domain.contains(sp.Rational(point['x'])) is (sp.false if point.get('open') else sp.true)


def test_reciprocal_range_graph_rejects_zero_as_an_input():
    from shuxueshuo_server.graph_lesson.stage_three import interaction_graphs as drawing

    with pytest.raises(drawing.GraphUnavailable, match='reciprocal_input_contains_zero'):
        drawing.reciprocal_image_graph(sp.S.Reals, source='Q(x)')


@pytest.mark.parametrize('expression,domain,expected', LINEAR_CASES)
def test_linear_remainder_transports_full_image_and_zero_branch(expression, domain, expected):
    from shuxueshuo_server.graph_lesson.stage_three.fraction_range import solve_fraction_intermediate
    value = candidate(expression, domain)
    context = build_context(value, TARGET)
    assert admitted(context, FRACTION_METHOD)
    prepared = prepare_fraction_range(context)['outputs']
    mapping = prepared['mapping']
    solved = solve_fraction_intermediate(context, mapping)['outputs']
    restored = return_fraction_range(context, mapping, solved['image'])['outputs']
    assert restored['feasible_set'] == expected
    assert independent_verify(value, TARGET, context, expected)['status'] == 'verified'
    for row in solved['description']['fraction_mapping']['pieces']:
        assert row['domain'].contains(0) is sp.false
    with pytest.raises(LocalCheckFailed):
        return_fraction_range(context, mapping, solved['image'].symmetric_difference(sp.FiniteSet(123)))
    wrong = deepcopy(mapping); wrong['zero_image'] = sp.FiniteSet(123)
    with pytest.raises(LocalCheckFailed):
        return_fraction_range(context, wrong, solved['image'])


@pytest.mark.stage_three_db
@pytest.mark.parametrize('index', [0, 1, 3, 7])
def test_linear_remainder_complete_lesson(tmp_path, index):
    from shuxueshuo_server.graph_lesson.stage_three import runner
    from tests.solver.test_graph_stage_three_execution import constructed_upstream, store
    expression, domain, expected = LINEAR_CASES[index]
    output = tmp_path/'run'
    result = runner.run_sample(constructed_upstream(tmp_path,candidate(expression,domain)), output)
    goal = result['goals'][0]
    route = next(r for r in goal['routes'] if r['method'] == FRACTION_METHOD)
    assert route['status'] == 'verified', route
    assert sp.sympify(goal['answer']['set']['expression']) == expected
    snapshot = store(output).snapshot()
    assert all(row['status'] == 'interactive' for row in snapshot['interaction_states']), snapshot['interaction_states']

@pytest.mark.stage_three_db
@pytest.mark.parametrize('index',[0,1,8,11,14])
def test_fraction_lesson_executes_child_and_closes(tmp_path,index):
    from shuxueshuo_server.graph_lesson.stage_three import runner
    from tests.solver.test_graph_stage_three_execution import (
        constructed_upstream,
        store,
    )
    from tools.export_graph_walk_course import export_course
    expression,domain,expected=CASES[index]
    upstream=constructed_upstream(tmp_path,candidate(expression,domain))
    output=tmp_path/'run';result=runner.run_sample(upstream,output)
    assert result['status']=='completed',result
    goal=result['goals'][0];assert goal['status']=='solved',goal
    assert sp.sympify(goal['answer']['set']['expression'])==expected
    assert all(row['status']=='interactive' for row in store(output).snapshot()['interaction_states'])
    evidence=export_course(output,'function-concepts-range-q07')
    assert evidence['lesson']['goals'][0]['walk'] is not None
    assert 'method-quadratic-interval-range' in str(evidence)
    assert '分段取倒数' in str(evidence['stream'])


@pytest.mark.parametrize('question', ['07','09','10','17'])
def test_photo_fixtures_keep_the_function_and_each_goal(question):
    import json
    from pathlib import Path

    from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
    from shuxueshuo_server.graph_lesson.stage_two.fragments import (
        _abstract_formula_matches,
    )
    from shuxueshuo_server.graph_lesson.stage_two.range_surface import (
        range_source_spans,
    )
    value=json.loads((Path(__file__).parent/'fixtures/function-range'/f'q{question}-candidate.json').read_text())
    assert extract_features(value)['ok']
    goals=value['root']['goals']
    if question=='09':assert [g['kind'] for g in goals]==['find_domain','find_range']
    target=f'/root/goals/{len(goals)-1}'
    context=build_context(value,target)
    assert admitted(context,FRACTION_METHOD)
    assert range_source_spans(value,target,[(0,len(value['original_text']))],context['range_goal'],_abstract_formula_matches)


def test_substitution_keeps_disconnected_input_images_in_child_context():
    from shuxueshuo_server.graph_lesson.stage_three.function_range import (
        prepare_range_substitution,
        return_range_substitution,
    )
    value=candidate('x+sqrt(1-x)','[-8,-3)∪(0,1]')
    context=build_context(value,TARGET)
    prepared=prepare_range_substitution(context)['outputs']
    child=prepared['child_context']['range_goal']
    expression,variable,domain=inputs(child)
    assert domain==sp.Union(sp.Interval.Ropen(0,1),sp.Interval.Lopen(2,3))
    image=polynomial_image(expression,variable,domain)['outputs']['feasible_set']
    assert return_range_substitution(context,prepared['mapping'],image)['outputs']['feasible_set']==image
    assert independent_verify(value,TARGET,context,image)['status']=='verified'


@pytest.mark.parametrize('domain,expected', [
    ('(-3,-1)∪(1,3)', sp.Union(sp.Interval.open(-1,-sp.Rational(1,3)),sp.Interval.open(sp.Rational(1,3),1))),
    ('(ℝ∖{0})∩[1,2]', sp.Interval(sp.Rational(1,2),1)),
])
def test_explicit_interval_unions_and_intersections_bind_as_numeric_domains(domain,expected):
    value=candidate('1/x',domain)
    context=build_context(value,TARGET)
    p=prepare_fraction_range(context)['outputs'];m=p['mapping']
    image=polynomial_image(m['function'],m['variable'],m['domain'])['outputs']['feasible_set']
    assert return_fraction_range(context,m,image)['outputs']['feasible_set']==expected
    assert independent_verify(value,TARGET,context,expected)['status']=='verified'
