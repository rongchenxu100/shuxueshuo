"""Regression cases for source ownership, original guards and exact T4 boundary handling."""
import copy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.parity_inequality_math import solve, verify
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.parity_inequality_presentation import phase_views
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value, encode_value
from tests.solver.test_graph_parity_even_order import on_reals
from tests.solver.test_graph_parity_inequality import candidate
from tests.solver.test_graph_parity_order import TARGET, a11, described
from tests.solver.test_graph_parity_sign import a19, given
from tests.solver.test_graph_parity_t4_mechanisms import whole


@pytest.mark.parametrize('word', ['非递增函数', '不是增函数', '不一定是增函数', '未必是增函数', '可能是增函数',
                                  '不是严格递增函数', '非严格递增函数'])
def test_direction_binding_rejects_negated_or_non_strict_predicates(word):
    value = a19()
    value['original_text'] = value['original_text'].replace('增函数', word)
    desc = described(value, bind=True)
    assert not desc['structure_supported'] and desc['reason'] == 'parity_ineq.source_not_bound'


@pytest.mark.parametrize('text', ['其中 $x<0$．', '且 $x>3$．', '另有 $f(0)=1$．'])
@pytest.mark.parametrize('target', ['/root/goals/0', '/root/goals/1'])
def test_another_goal_does_not_own_unbound_later_conditions(text, target):
    value = a11()
    value['original_text'] += text
    context = build_context(value, target)
    key = 'parity_extension_goal' if target.endswith('0') else 'parity_inequality_goal'
    assert not context[key]['structure_supported']


def test_bound_input_domain_is_intersected_and_missing_condition_rejected():
    value = a11()
    value['original_text'] += '其中 $x<0$．'
    value['root']['goals'][1]['input_domain'] = '(-∞,0)'
    desc = described(value, '/root/goals/1', bind=True)
    assert desc['structure_supported'], desc['reason']
    model = solve(desc)
    assert model['solution'] == sp.S.EmptySet and verify(desc, model)
    view = phase_views({'description': desc, 'phase': 'conclude'})[0]
    assert '题给范围' in view['proof']


def test_scalar_constraint_is_consumed_as_a_fact():
    value = whole('f(x)+f(-2)>0')
    value['root']['facts'].append('x<3')
    value['original_text'] = (r'已知 $f(x)$ 是定义在 $R$ 上的奇函数，在定义域上是增函数，'
                              r'求不等式 $f(x)+f(-2)>0$ 的解集，其中 $x<3$．')
    desc = described(value, bind=True)
    assert desc['structure_supported'], desc['reason']
    assert solve(desc)['solution'] == sp.Interval.open(2, 3)
    assert verify(desc, solve(desc))


@pytest.mark.parametrize('value,expected', [
    (whole('f(abs(x-1))+f(-2)<0'), sp.Interval.open(-1, 3)),
    (on_reals('f(1/x)<f(2)'), sp.Interval.open(-sp.oo, -sp.Rational(1, 2)) |
     sp.Interval.open(sp.Rational(1, 2), sp.oo)),
    (whole('f((x^2-1)/(x-1))+f(0)>=0'), sp.Interval(-1, sp.oo) - sp.FiniteSet(1)),
    (whole('f(x/x)+f(-1)<=0'), sp.S.Reals - sp.FiniteSet(0)),
    (given(['Dom(f)=ℝ', 'parity(f,odd)', 'f(2)=0', 'f(1/x)<0']),
     sp.Interval.open(-sp.Rational(1, 2), 0) | sp.Interval.open(sp.Rational(1, 2), sp.oo)),
    (given(['Dom(f)=ℝ', 'parity(f,odd)', 'f(2)=0', 'f(abs(x))<0']),
     sp.Interval.open(-2, 0) | sp.Interval.open(0, 2)),
    (given(['Dom(f)=ℝ', 'parity(f,odd)', 'f(2)=0', '0*f(x)<=0']), sp.S.Reals),
    (given(['Dom(f)=ℝ', 'parity(f,odd)', 'f(2)=0', '0*f(x)<0']), sp.S.EmptySet),
    (given(['Dom(f)=ℝ', 'parity(f,odd)', 'f(2)=0', 'f(2)<=0']), sp.S.Reals),
    (given(['Dom(f)=ℝ', 'parity(f,odd)', 'f(2)=0', '(x/x)*f(2)<=0']), sp.S.Reals - sp.FiniteSet(0)),
])
def test_common_inputs_preserve_exact_solution_and_original_holes(value, expected):
    desc = described(value)
    assert desc['structure_supported'], desc['reason']
    model = solve(desc)
    assert model['solution'] == expected
    assert verify(desc, model) and verify(desc, decode_value(encode_value(model)))
    phases = (['rewrite', 'direction', 'compare', 'conclude'] if desc['route'] == 'order'
              else ['sign_known', 'sign_mirror', 'sign_solve', 'conclude'])
    for phase in phases:
        view, = phase_views({'description': desc, 'phase': phase})
        assert view['proof']


def test_cancelled_denominator_is_still_visible_and_verified():
    desc = described(whole('f((x^2-1)/(x-1))+f(0)>=0'))
    model = solve(desc)
    bad = copy.deepcopy(model)
    bad['solution'] |= sp.FiniteSet(1)
    assert not verify(desc, bad)
    view, = phase_views({'description': desc, 'phase': 'conclude'})
    assert '原式有意义' in view['proof'] and r'\frac{x^{2}-1}{x-1}' in view['proof']


def test_redundant_origin_fact_keeps_order_route_and_is_bound():
    value = whole('f(2*x+1)>f(5)')
    value['root']['facts'].insert(1, 'f(0)=0')
    value['original_text'] = (r'已知 $f(x)$ 是定义在 $R$ 上的奇函数，在定义域上是增函数，且 $f(0)=0$，'
                              r'则不等式 $f(2x+1)>f(5)$ 的解集为____．')
    desc = described(value, bind=True)
    assert desc['structure_supported'] and desc['route'] == 'order', desc['reason']
    model = solve(desc)
    assert model['solution'] == sp.Interval.open(2, sp.oo) and verify(desc, model)
    value['original_text'] = value['original_text'].replace('f(0)=0', 'f(0)=1')
    assert not described(value, bind=True)['structure_supported']


def test_zero_is_in_the_sign_answer_and_the_step_card():
    desc = described(given(['Dom(f)=ℝ', 'parity(f,odd)', 'f(2)=0', 'f(x)<=0']))
    model = solve(desc)
    assert model['solution'] == sp.Interval(-sp.oo, -2) | sp.Interval(0, 2)
    view, = phase_views({'description': desc, 'phase': 'sign_solve'})
    from shuxueshuo_server.graph_lesson.stage_three.math_values import latex
    assert latex(model['solution']) in view['proof']
    assert 'f(0)=0' in str(view['derivation'])


def test_product_zero_branch_appears_in_the_proof():
    desc = described(given(['Dom(f)=ℝ', 'parity(f,odd)', 'f(2)=0', 'x*f(x)<=0']))
    view, = phase_views({'description': desc, 'phase': 'conclude'})
    assert r'x=0\Rightarrow' in view['proof']


def test_tampered_intermediate_sign_table_or_order_set_is_rejected():
    desc = described(a19())
    model = solve(desc)
    model['certificate']['known'] = [(sp.Interval.open(0, sp.oo), 1)]
    assert not verify(desc, model)
    desc = described(whole('f(x)+f(1)>0'))
    model = solve(desc)
    model['ordered_set'] = sp.S.EmptySet
    assert not verify(desc, model)


@pytest.mark.parametrize('rule,ok', [('piecewise(-x^2+x,x<0,x^2+x,x>=0)', True),
                                     ('piecewise(-x^2+x-1,x<0,x^2+x,x>=0)', False)])
def test_explicit_piecewise_direction_with_a_parity_fact(rule, ok):
    from shuxueshuo_server.graph_lesson import monotonicity_inequality_math as mono
    value = {'original_text': '', 'root': {'definitions': [f'f(x)={rule}'],
             'facts': ['parity(f,odd)', 'f(2*x)>f(1)'], 'goals': [{'kind': 'find_range', 'symbol': 'x'}]}}
    context = build_context(value, TARGET)
    desc = mono.describe(context['goal'], TARGET, context['entries'])
    assert desc['structure_supported'] is ok, desc['reason']
    if ok:
        assert mono.verify(desc, mono.solve(desc))
    else:
        assert desc['reason'] == 'mono_ineq.parity_conflict'


def test_half_axis_restriction_avoids_an_unneeded_unknown_origin():
    value = candidate(('Dom(f)=ℝ', 'parity(f,even)'), 'x^2', '(0,∞)', 'f(x)<=1')
    value['root']['goals'][0]['input_domain'] = '(0,∞)'
    desc = described(value)
    assert desc['structure_supported'], desc['reason']
    assert solve(desc)['solution'] == sp.Interval.Lopen(0, 1)
    assert verify(desc, solve(desc))


def _integration_cases():
    absolute = on_reals('f(abs(x-1))<=f(2)')
    absolute['original_text'] = (r'已知 $f(x)$ 是定义在 $R$ 上的偶函数，在 $[0,+\infty)$ 上是增函数，'
                                  r'则不等式 $f(|x-1|)\le f(2)$ 的解集为____．')
    rational = whole('f((x^2-1)/(x-1))+f(0)>=0')
    rational['original_text'] = (r'已知 $f(x)$ 是定义在 $R$ 上的奇函数，在定义域上是增函数，'
                                  r'则不等式 $f(\frac{x^2-1}{x-1})+f(0)\ge0$ 的解集为____．')
    zero = given(['Dom(f)=ℝ', 'parity(f,odd)', 'f(2)=0', 'f(x)<=0'])
    zero['original_text'] = (r'已知 $f(x)$ 是定义在 $R$ 上的奇函数，在 $(0,+\infty)$ 上是增函数，且 $f(2)=0$，'
                              r'则不等式 $f(x)\le0$ 的解集为____．')
    redundant = whole('f(2*x+1)>f(5)')
    redundant['root']['facts'].insert(1, 'f(0)=0')
    redundant['original_text'] = (r'已知 $f(x)$ 是定义在 $R$ 上的奇函数，在定义域上是增函数，且 $f(0)=0$，'
                                   r'则不等式 $f(2x+1)>f(5)$ 的解集为____．')
    restricted = a11()
    restricted['original_text'] += '其中 $x<0$．'
    restricted['root']['goals'][1]['input_domain'] = '(-∞,0)'
    degenerate = copy.deepcopy(zero)
    degenerate['root']['facts'][-1] = '0*f(x)<=0'
    degenerate['original_text'] = degenerate['original_text'].replace(r'$f(x)\le0$', r'$0\cdot f(x)\le0$')
    return [(absolute, sp.Interval(-1, 3)), (rational, sp.Interval(-1, sp.oo) - sp.FiniteSet(1)),
            (zero, sp.Interval(-sp.oo, -2) | sp.Interval(0, 2)), (redundant, sp.Interval.open(2, sp.oo)),
            (restricted, sp.S.EmptySet), (degenerate, sp.S.Reals)]


@pytest.mark.stage_three_db
@pytest.mark.parametrize('value,expected', _integration_cases(),
                         ids=['absolute', 'rational-hole', 'zero-boundary', 'redundant-fact', 'restricted-sibling', 'zero-product'])
def test_new_variants_generate_grade_and_replay(value, expected, tmp_path):
    import json
    import subprocess
    from tests.solver.test_graph_function_parity_recognition import recognize
    from shuxueshuo_server.graph_lesson.stage_three import runner
    from shuxueshuo_server.graph_lesson.stage_three.contracts import ROOT
    from tools.export_graph_walk_course import export_course
    recognize(value, tmp_path)
    output = tmp_path / 'execution'
    result = runner.run_sample(tmp_path / 'stage-two/stage-two-result.json', output)
    goal = result['goals'][-1]
    assert all(g['status'] == 'solved' for g in result['goals']), result['goals']
    solution = sp.sympify(goal['answer']['set']['expression'])
    assert solution == expected
    assert runner.resume_sample(output)['goals'][-1]['answer'] == goal['answer']
    evidence = export_course(output, 'parity-t4-generalization')
    evidence_file, course_file = tmp_path / 'evidence.json', tmp_path / 'source.json'
    evidence_file.write_text(json.dumps(evidence, ensure_ascii=False))
    course_file.write_text(json.dumps({'schemaVersion': 1, 'problemId': 'parity-t4-generalization',
        'title': '奇偶性不等式', 'preview': True, 'page': '/lab/graph-walk/parity-t4-generalization/',
        'topicHref': '/topics/function-parity/', 'targetRef': TARGET,
        'authoringSource': str(tmp_path / 'authored.json'), 'evidence': str(evidence_file)}, ensure_ascii=False))
    route = 'parity-extension' if len(result['goals']) > 1 else 'parity-inequality'
    check = subprocess.run(['node', str(ROOT/'tools/tests/fixtures/parity-parameter-course-check.mjs'),
                            str(evidence_file), str(course_file), route], capture_output=True, text=True, check=False)
    assert check.returncode == 0, check.stdout + check.stderr


def test_a_new_input_restriction_cannot_be_ignored_by_an_older_formula_route():
    from shuxueshuo_server.graph_lesson.stage_one.function_formula import inspect_formula_target
    goal = {'kind': 'find_range', 'function': 'f', 'variable': 'x', 'relation': 'f(x)=x^2',
            'expression': 'f(x)>1', 'symbol': 'x', 'function_type': 'quadratic', 'input_domain': '[0,2]'}
    value = {'original_text': '', 'root': {'goals': [goal]}}
    context = build_context(value, TARGET)
    assert 'input_domain' in context['goal_ast']
    desc = inspect_formula_target(value, TARGET)
    assert not desc['structure_supported'] and desc['reason'] == 'function_formula.input_restriction_unsupported'
