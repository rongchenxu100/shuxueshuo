"""FR-T3 numeric branches: original conditions, nesting, proof and lesson cards."""

from copy import deepcopy

import pytest
import sympy as sp
from shuxueshuo_server.graph_lesson import function_evaluation as m9
from shuxueshuo_server.graph_lesson.stage_one.function_evaluation import (
    inspect_evaluation_target,
)
from shuxueshuo_server.graph_lesson.stage_three import evaluation_runtime as runtime
from shuxueshuo_server.graph_lesson.stage_three.evaluation_presentation import (
    compile_evaluation,
    phase_views,
)
from shuxueshuo_server.graph_lesson.stage_three.trajectory import (
    decode_value,
    encode_value,
)
from shuxueshuo_server.graph_lesson.stage_two.evaluation_surface import (
    evaluation_source_spans,
)
from shuxueshuo_server.graph_lesson.stage_two.fragments import _abstract_formula_matches
from shuxueshuo_server.problem_understanding.identity import revision


def candidate(expression='f(f(sqrt(2)))', definition='f(x)=piecewise(x+1,x<=0,x^2-3,x>0)'):
    return {'original_text': r'设 $f(x)=\begin{cases}x+1,&x\le0\\x^2-3,&x>0\end{cases}$，求 $f(f(\sqrt2))$。',
            'root': {'definitions': [definition], 'goals': [{'kind': 'find_value', 'expression': expression}]}}


def run(source):
    desc = inspect_evaluation_target(source, '/root/goals/0')
    assert desc['structure_supported'], desc
    result = m9.evaluate(desc)
    assert m9.verify(desc, decode_value(encode_value(result)))
    return desc, result


def test_nested_numeric_value_reselects_branch_and_checks_source_evidence():
    desc, result = run(candidate())
    assert result['value'] == 0
    assert [(row['input'], row['output'], row['branch_index']) for row in result['calls']] == [
        (sp.sqrt(2), -1, 1), (-1, 0, 0)]
    for key, value in [('branch_index', 1), ('branch_condition_ast', ['>', m9.ARGUMENT, ['number', '0']]),
                       ('output', sp.Integer(-4))]:
        bad = deepcopy(result)
        bad['calls'][1][key] = value
        assert not m9.verify(desc, bad), key
    changed = candidate(definition='f(t)=piecewise(t+1,t<=0,t^2-3,t>0)')
    assert run(changed)[1]['value'] == 0
    assert revision(candidate()) != revision(candidate(definition='f(x)=piecewise(x+1,x<0,x^2-3,x>=0)'))


@pytest.mark.parametrize(('input_value', 'output', 'branch'), [('0', 1, 0), ('-2', -1, 0), ('2', 1, 1)])
def test_boundaries_select_exactly_one_source_branch(input_value, output, branch):
    _, result = run(candidate(f'f({input_value})'))
    assert result['value'] == output and result['calls'][0]['branch_index'] == branch


def test_missing_branch_and_undefined_inner_value_are_not_filled_with_zero():
    definition = 'f(x)=piecewise(x+1,x<0,x^2-3,x>0)'
    desc, result = run(candidate('f(f(0))', definition))
    assert not result['defined'] and result['value'] is None
    assert all(row['branch_index'] is None for row in result['calls'])
    assert result['calls'][1]['input'] is None
    rows = runtime.extract_evaluation_conditions(desc, result)['outputs']
    assert rows['raw_terms'][0]['expression'] is None
    assert not m9.verify(desc, {**result, 'defined': True, 'value': sp.S.Zero})


def test_only_selected_branch_contributes_arithmetic_restrictions():
    definition = 'f(x)=piecewise(x+1,x<=0,1/(x-1),x>0)'
    assert run(candidate('f(0)', definition))[1]['value'] == 1
    assert run(candidate('f(sqrt(2))', definition))[1]['defined']
    assert not run(candidate('f(1)', definition))[1]['defined']
    explicit = candidate('f(0)', definition)
    explicit['root']['facts'] = ['Dom(f)=ℝ']
    desc = inspect_evaluation_target(explicit, '/root/goals/0')
    with pytest.raises(ValueError, match='declared_domain_conflict'):
        m9.evaluate(desc)


@pytest.mark.parametrize(('expression', 'definition', 'reason'), [
    ('f(0)', 'f(x)=piecewise(x+1,x<=0,x^2-3,x>=0)', 'overlapping_branches'),
    ('f(x)', 'f(x)=piecewise(x+1,x<=0,x^2-3,x>0)', 'piecewise_numeric_goal_required'),
    ('f(1)+f(2)', 'f(x)=piecewise(x+1,x<=0,x^2-3,x>0)', 'piecewise_direct_call_required'),
    ('f(f(1)+2)', 'f(x)=piecewise(x+1,x<=0,x^2-3,x>0)', 'piecewise_direct_call_required'),
    ('f(0)', 'f(x)=piecewise(x+1,x^2<=0,x^2-3,x>0)', 'branch_condition'),
    ('f(sqrt(x))', 'f(x)=x+1', 'numeric_radical_required'),
    ('f(sqrt(1000001))', 'f(x)=x+1', 'radical_budget'),
])
def test_unsupported_structures_stop_before_solving(expression, definition, reason):
    desc = inspect_evaluation_target(candidate(expression, definition), '/root/goals/0')
    assert not desc['structure_supported'] and desc['reason'].endswith(reason), desc


def test_piecewise_uses_existing_skill_pipeline_and_stepwise_cards():
    desc, result = run(candidate())
    rows = decode_value(encode_value(runtime.extract_evaluation_conditions(desc, result)['outputs']))
    restored = runtime.resolve_evaluation_domain(desc, rows['conditions'], result)['outputs']['evaluation_result']
    restored = runtime.simplify_evaluation_expressions(rows['substitutions'], rows['raw_terms'], restored)['outputs']['evaluation_result']
    assert runtime.verify_evaluation_identities(desc, restored)['outputs']['evaluation_result']['value'] == 0
    data = {'description': desc, 'evaluation_result': restored}
    for phase in ('inner', 'substitute'):
        views = phase_views({**data, 'phase': phase})
        assert len(views) == 2
        assert r'\begin{cases}' in views[0]['derivation']['items'][0]['math']
        assert all(line.startswith('$') and line.endswith('$') for v in views for line in v['explanation'].splitlines())
        assert '计算' in views[1]['title']
        compiled = compile_evaluation([{'values': encode_value({**data, 'phase': phase})}], 'piecewise-' + phase)
        assert all(part['stem_board']['items'][1]['math'] is None for part in compiled['parts'])
    outer = phase_views({**data, 'phase': 'substitute'})
    assert outer[0]['title'] == '用中间值重新选段' and '$-1$' in outer[0]['question']
    assert r'-1\le 0' in outer[1]['question']


def test_original_cases_reading_keeps_every_branch_and_its_endpoint():
    source = candidate()
    desc, _ = run(source)
    def spans(value):
        return evaluation_source_spans(value, '/root/goals/0', [(0, len(value['original_text']))],
                                       desc, _abstract_formula_matches)
    assert len(spans(source)) == 2
    for old, replacement in [(r'x\le0', 'x<0'), ('x^2-3', 'x^2+3'), (r'\\x^2-3,&x>0', '')]:
        bad = deepcopy(source)
        bad['original_text'] = bad['original_text'].replace(old, replacement)
        assert spans(bad) is None


def test_piecewise_source_module_participates_in_frozen_revisions():
    from shuxueshuo_server.graph_lesson.stage_one.extraction import frozen_files
    from shuxueshuo_server.graph_lesson.stage_three.runner import fingerprint
    path = 'server/shuxueshuo_server/graph_lesson/piecewise_evaluation.py'
    assert path in frozen_files() and path in fingerprint()
