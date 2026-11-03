"""FR-T3 P4: exact parameter cases, source binding, J2 and two native courses."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
import sympy as sp
from jsonschema import Draft202012Validator
from shuxueshuo_server.graph_lesson import piecewise_range_parameter as pr
from shuxueshuo_server.graph_lesson.stage_one.runner import candidate_features
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.math_values import latex as tex
from shuxueshuo_server.graph_lesson.stage_three.piecewise_range_parameter_presentation import (
    compile_step,
    presentation,
)
from shuxueshuo_server.graph_lesson.stage_three.selection import evaluate_goal
from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value
from shuxueshuo_server.graph_lesson.stage_two.fragments import build_d1

ROOT = Path(__file__).resolve().parents[3]
TARGET = '/root/goals/0'


def candidate(i):
    return json.loads((ROOT/f'internal/senior-high/authored-courses/piecewise-p4-20261102/b11-v{i}.json').read_text())['candidate']


def calculate(c):
    context = build_context(c, TARGET)
    assert pr.admitted(context), context
    v = pr.prepare(context)['outputs']
    route = pr.choose_route(v['description'], v['fixed_range'])['selected']
    if route == 'contained':
        from shuxueshuo_server.graph_lesson.stage_three import driver
        from shuxueshuo_server.graph_lesson.stage_three.domain_borrow import (
            _quantified_fact,
        )
        from tests.solver.test_graph_stage_three_methods import finish, start
        subproblem = pr.reduce_to_universal(v['description'], v['fixed_range'])['outputs']
        fact, parameter = _quantified_fact(subproblem)
        child = {'original_text': fact, 'root': {'facts': [fact], 'goals': [{'kind': 'find_range', 'symbol': parameter}]}}
        state = finish(start(child, method='method-separation'))
        assert state['status'] == 'method_complete', state['diagnostics']
        answer = driver.export_values(state)['feasible_set']
        v.update(pr.accept_subproblem(v['description'], v['fixed_range'], answer)['outputs'])
    else:
        v.update(pr.solve(v['description'], v['fixed_range'], route)['outputs'])
    return context, v


@pytest.mark.parametrize(('i', 'expected'), [(1, sp.Interval(sp.Rational(1,16), sp.oo)),
                                          (2, sp.Interval.Ropen(-sp.Rational(1,2), 0))])
def test_original_parameter_cases_and_independent_verification(i, expected, monkeypatch):
    c = candidate(i); context, values = calculate(c)
    assert values['feasible_set'] == expected
    monkeypatch.setattr(pr, 'solve', lambda *_: pytest.fail('independent verifier cannot reuse solver'))
    assert pr.independent_verify(c, TARGET, context, expected)['status'] == 'verified'
    for bad in [sp.S.Reals, sp.Interval.open(expected.start, expected.end),
                sp.Interval(expected.start, expected.end) if i == 2 else sp.Interval(-sp.oo, expected.start)]:
        assert pr.independent_verify(c, TARGET, context, bad)['status'] == 'math_failed'
    assert pr.endpoints(c, TARGET, expected)['status'] == 'passed'
    tampered = deepcopy(context); tampered['piecewise_range_parameter']['sources'][0]['expression'] += '+1'
    assert not pr.admitted(tampered)
    assert pr.independent_verify(c, TARGET, tampered, expected)['status'] == 'math_failed'
    if i == 2:
        zero = next(e for e in pr.endpoints(c, TARGET, expected)['points'] if e['point']['expression'] == '0')
        assert not zero['holds'] and not zero['included']
        assert zero['evidence']['complete_original_image']['expression'] == 'Interval(-2, oo)'


@pytest.mark.parametrize(('i', 'before', 'after', 'expected'), [
    (1, 'a*x^2-x+2', 'a*x^2-2*x+6', sp.Interval(sp.Rational(1,8), sp.oo)),
    (2, 'a*x^2-2*x', 'a*x^2-4*x', sp.Interval.Ropen(-2, 0)),
    (2, 'x+1,x>1', '2*x+1,x>1', sp.Interval.Ropen(-sp.Rational(1,3), 0)),
])
def test_numeric_variants_use_structure_not_problem_identity(i, before, after, expected):
    c = candidate(i); c['root']['definitions'][0] = c['root']['definitions'][0].replace(before, after)
    context, v = calculate(c)
    assert v['feasible_set'] == expected
    assert pr.independent_verify(c, TARGET, context, expected)['status'] == 'verified'


@pytest.mark.parametrize('definition', [
    'f(x)=piecewise(x^2-2,x<=1,a*x^3-x+2,x>1)',
    'f(x)=piecewise(x^2-2,x<=1,a*x^2+x+2,x>1)',
    'f(x)=piecewise(x^2-2,x<=1,a*x^2-x+2,x>=1)',
    'f(x)=piecewise(a*x^2-2,x<=1,a*x^2-x+2,x>1)',
    'f(x)=piecewise(x^2-2,x<=1,a*x^2-x+2+0/x,x>1)',
])
def test_unsupported_or_ambiguous_originals_are_not_admitted(definition):
    c = candidate(1); c['root']['definitions'] = [definition]
    assert not pr.inspect_target(c, TARGET)['structure_supported']


def test_extra_conditions_and_target_range_identity_are_preserved():
    c = candidate(1); c['root']['facts'].append('a>0')
    assert not pr.inspect_target(c, TARGET)['structure_supported']
    c = candidate(1); c['root']['uncertainties'] = [{'kind':'ambiguous_symbol','text':'分界点不清'}]
    assert not pr.inspect_target(c, TARGET)['structure_supported']
    from shuxueshuo_server.graph_lesson.stage_one.contracts import schema
    from shuxueshuo_server.problem_understanding.notation_compile import (
        NotationValidator,
    )
    from shuxueshuo_server.problem_understanding.notation_semantics import canonical
    a = candidate(1); b = deepcopy(a); b['root']['goals'][0]['range'] = '[-1,+∞)'
    validator = NotationValidator()
    assert canonical(validator.validate_root(a['root'], schema()['$defs'])) != canonical(validator.validate_root(b['root'], schema()['$defs']))


def test_fixed_piece_outside_target_has_no_parameter_solution():
    c = candidate(1); c['root']['goals'][0]['range'] = '[-1,+∞)'
    context, v = calculate(c)
    assert v['calculation']['route'] == 'impossible' and v['feasible_set'] == sp.S.EmptySet
    assert pr.independent_verify(c, TARGET, context, sp.S.EmptySet)['status'] == 'verified'
    assert pr.independent_verify(c, TARGET, context, sp.Interval(1, sp.oo))['status'] == 'math_failed'


@pytest.mark.parametrize('i', [1, 2])
def test_reading_direct_method_and_math_only_derivations(i):
    c = candidate(i); features = candidate_features(c)
    assert features['ok'], features['diagnostics']
    assert not build_d1(c, TARGET, features['features'], {'items':[]})['diagnostics']
    c_bad = deepcopy(c); c_bad['original_text'] = c_bad['original_text'].replace('值域为', '定义域为')
    assert build_d1(c_bad, TARGET, features['features'], {'items':[]})['diagnostics']
    selected = evaluate_goal(c, TARGET, features['features'], 'type-piecewise-function')
    assert selected['selection']['rule'] is None
    assert selected['d3']['title'] == '解题方法'
    _, v = calculate(c)
    phases = ['fixed','decision', *(['constraint'] if i == 1 else ['zero','sign','vertex','image','join']), 'answer','verify']
    schema = json.loads((ROOT/'internal/schemas/graph-step-interaction-v1.schema.json').read_text())
    for phase in phases:
        part = compile_step([{'values':encode_value({**v,'phase':phase})}], 'a'*24)['parts'][0]
        Draft202012Validator({'$defs':schema['$defs'], '$ref':'#/$defs/part'}).validate(part)
        assert part['stem_board']['items'][1]['math'] is None
        assert part['feedback']['answer'].startswith('$$')
        assert '=' in part['feedback']['answer'] or r'\iff' in part['feedback']['answer'] or r'\Rightarrow' in part['feedback']['answer']
        if phase == 'decision':
            assert all(line['variable'] == 'y' for line in part['condition_number_lines'])
            assert len({tuple(line['bounds']) for line in part['condition_number_lines']}) == 1
    assert pr.classify(sp.Interval(-1, sp.oo), sp.Interval(-2, sp.oo)) == 'cover'
    assert pr.classify(sp.S.Reals, sp.Interval(-2, sp.oo)) == 'impossible'


@pytest.mark.parametrize('i', [1, 2])
@pytest.mark.parametrize('reverse_branches', [False, True])
def test_every_card_keeps_original_branch_formula_boundary_and_range_identity(i, reverse_branches):
    c = candidate(i)
    if reverse_branches:
        prefix, pieces = c['root']['definitions'][0].split('piecewise(')
        parts = pieces[:-1].split(',')
        c['root']['definitions'][0] = prefix+'piecewise('+','.join(parts[2:]+parts[:2])+')'
    _, values = calculate(c)
    d = pr.source(values['description'])
    fixed, varying = d['fixed'], d['varying']
    rf, ra = (f'R_{{{branch["index"]}}}' for branch in (fixed, varying))
    phases = ['fixed', 'decision', *(['constraint']
              if i == 1 else ['zero', 'sign', 'vertex', 'image', 'join']), 'answer', 'verify']
    for phase in phases:
        v = {**values, 'phase': phase}
        part = compile_step([{'values': encode_value(v)}], 'b'*24)['parts'][0]
        branch = fixed if phase == 'fixed' else varying
        for board in (part['stem_board'], part['completion_board']):
            assert f'第 {branch["index"]} 段函数' in board['caption']
            assert f'f(x)={tex(branch["expression"])}' in board['caption']
            assert tex(branch['domain'].as_relational(d['x'])) in board['caption']
        rendered = presentation(v)
        assert rendered['derivation_caption'] == part['completion_board']['caption']
        assert rendered['derivation_left_note'] == part['completion_board']['items'][0].get('note', '')
        assert part['stem_board']['items'][1]['math'] is None
        if phase == 'fixed':
            assert part['completion_board']['items'][1]['math'] == rf+'='+tex(values['fixed_range'])
        if phase == 'decision':
            left, right = part['completion_board']['items']
            assert rf+'='+tex(values['fixed_range']) in left['math']
            assert ra in right['math'] and f'第 {varying["index"]} 段函数' in right['label']
            known, target = part['condition_number_lines']
            assert known['exact_set']['expression'] == str(values['fixed_range'])
            assert f'第 {fixed["index"]} 段函数' in known['label']
            assert f'f(x)={tex(fixed["expression"])}' in known['label']
            assert tex(fixed['domain'].as_relational(d['x'])) in known['label']
            assert rf in known['label'] and ra not in known['label']
            assert '整个函数' in target['label']


@pytest.mark.parametrize('definition', [
    'f(x)=piecewise(x+1,x>1,a*x^2-2*x,x<=1)',
    'f(x)=piecewise(a*x^2-4*x+1,x<=2,x+1,x>2)',
])
def test_cover_graphs_keep_source_intervals_and_identify_parameter_examples(definition):
    c = candidate(2)
    c['root']['definitions'] = [definition]
    _, values = calculate(c)
    d = pr.source(values['description'])
    x, p, h = (d[key] for key in ('x', 'parameter', 'split'))
    schema = json.loads((ROOT/'internal/schemas/graph-step-interaction-v1.schema.json').read_text())
    validator = Draft202012Validator({'$defs': schema['$defs'], '$ref': '#/$defs/part'})
    for phase in ('fixed', 'zero', 'sign', 'vertex', 'image'):
        result = compile_step([{'values': encode_value({**values, 'phase': phase})}], 'c'*24)
        assert not result['diagnostics']
        part = result['parts'][0]
        validator.validate(part)
        branch = d['fixed' if phase == 'fixed' else 'varying']
        if phase == 'sign':
            options = part['interaction']['options']
            pictures = [option['graph'] for option in options]
            assert pictures == part['completion_graphs']
            assert len(pictures) == 2 and 'graph' not in part
            for option in options:
                negative = option['value'] in part['expected_answer']['one_of']
                assert (option['graph']['params']['coefficient'] < 0) == negative
        else:
            assert part['graph'] == part['completion_graph']
            pictures = [part['graph']]
        for graph in pictures:
            params = graph['params']
            fixed = phase == 'fixed'
            assert f'第 {branch["index"]} 段函数' in graph['caption']
            assert tex(branch['domain'].as_relational(x)) in graph['caption']
            assert params['interval'] == ([float(h), None] if fixed else [None, float(h)])
            assert params['interval_closed'] == ([False, False] if fixed else [False, True])
            assert params['points'][0].get('open', False) == fixed
            if phase in ('fixed', 'zero'):
                expression = branch['expression'].subs(p, 0)
                assert graph['kind'] == 'linear' and '示意' not in graph['caption']
                assert params['slope'] == float(expression.diff(x))
                assert params['intercept'] == float(expression.subs(x, 0))
                assert params['points'][0]['label'].endswith(f'{expression.subs(x, h)})')
                if phase == 'zero':
                    assert '$a=0$' in graph['caption']
            else:
                coefficient = sp.Rational(str(params['coefficient']))
                sample = branch['expression'].subs(p, coefficient)
                vertex = -d['b']/(2*coefficient)
                assert graph['kind'] == 'quadratic' and params['showVertex']
                assert params['vertex'] == [float(vertex), float(sample.subs(x, vertex))]
                assert '示意' in graph['caption'] and f'$a={tex(coefficient)}$' in graph['caption']
                assert any(tick == [float(h), str(h)] for tick in params['xTicks'])
                assert vertex in branch['domain']
                if phase in ('vertex', 'image'):
                    assert vertex < 0 < h
                    # The symbolic conclusion remains general, despite the numeric picture.
                    assert 'a' in part['completion_board']['items'][1]['math']


def test_opening_graphs_fall_back_together_without_changing_the_answer(monkeypatch):
    from shuxueshuo_server.graph_lesson.stage_three import (
        piecewise_range_parameter_presentation as ui,
    )
    _, values = calculate(candidate(2))
    seed = [{'values': encode_value({**values, 'phase': 'sign'})}]
    original = compile_step(seed, 'd'*24)['parts'][0]
    draw = ui._branch_graph
    calls = 0

    def second_graph_unavailable(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ui.drawing.GraphUnavailable('marks_overlap')
        return draw(*args, **kwargs)

    monkeypatch.setattr(ui, '_branch_graph', second_graph_unavailable)
    result = compile_step(seed, 'd'*24)
    part = result['parts'][0]
    assert result['diagnostics'] == [{'kind': 'graph_unavailable', 'reason': 'marks_overlap'}]
    assert all('graph' not in option for option in part['interaction']['options'])
    assert 'completion_graphs' not in part
    assert part['expected_answer'] == original['expected_answer']
    assert part['completion_board'] == original['completion_board']


def test_j2_is_registered_as_a_method_local_judgment():
    from shuxueshuo_server.graph_lesson.stage_three.execution_contracts import (
        read,
        validate_contract,
    )
    contract = read(pr.METHOD)
    validate_contract(contract)
    assert contract['steps'][1]['judgments'][0]['rule_ref'] == pr.RULE
    wrong = deepcopy(contract); wrong['steps'][1]['judgments'][0]['options'].pop()
    with pytest.raises(ValueError, match='rule_decision_options'):
        validate_contract(wrong)


@pytest.mark.parametrize('i', [1,2])
@pytest.mark.stage_three_db
def test_native_course_completes(i, tmp_path):
    from shuxueshuo_server.graph_lesson.stage_three import runner
    from tests.solver.test_graph_stage_three_execution import constructed_upstream
    from tools.export_graph_walk_course import export_course
    result = runner.run_sample(constructed_upstream(tmp_path, candidate(i)), tmp_path/'run')
    assert result['status'] == 'completed' and result['goals'][0]['status'] == 'solved', result
    assert result['goals'][0]['answer']['kind'] == 'match_range'
    course = export_course(tmp_path/'run', f'function-representations-b11-v{i}')
    assert course['lesson']['goals'][0]['walk'] is not None
