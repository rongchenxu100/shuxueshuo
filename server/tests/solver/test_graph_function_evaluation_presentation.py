"""M9 cards follow verified call order and hide unfinished results."""
import json
from copy import deepcopy
from pathlib import Path

import pytest
import sympy as sp
from jsonschema import Draft202012Validator

from shuxueshuo_server.graph_lesson.function_evaluation import evaluate
from shuxueshuo_server.graph_lesson.stage_one.function_evaluation import inspect_evaluation_target
from shuxueshuo_server.graph_lesson.stage_three import interaction
from shuxueshuo_server.graph_lesson.stage_three.evaluation_presentation import (
    PHASES, _ast, _composite_input_card, compile_evaluation, phase_flags, phase_views, presentation,
)
from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value

FIXTURES = Path(__file__).parent / 'fixtures/function-evaluation'


def values(name, index=0):
    candidate = json.loads((FIXTURES / f'{name}-candidate.json').read_text())
    description = inspect_evaluation_target(candidate, f'/root/goals/{index}')
    return {'before': [], 'after': [], 'description': description,
            'evaluation_result': evaluate(description)}


@pytest.mark.parametrize(('name', 'index'), [('q28a', 0), ('q28a', 1), ('q28b', 0), ('q28b', 1),
                                           ('q28c', 0), ('q28c', 1), ('q28d', 0), ('q29b', 0), ('q29b', 1)])
def test_all_nine_goals_project_registered_cards_without_revealing_pending_results(name, index):
    data = values(name, index)
    flags = phase_flags(data['description'], data['evaluation_result'])
    registry = interaction.load_registry()
    assert registry['templates']['function_evaluation_derivation']['compiler'] == 'function_evaluation'
    for phase in PHASES:
        if not flags['has_' + phase]:
            continue
        current = {**data, 'phase': phase}
        rendered = presentation(current)
        assert rendered['derivation_left_math'] and rendered['derivation_right_math']
        seed = {'template': 'function_evaluation_derivation', 'values': encode_value(current)}
        compiled = compile_evaluation([seed], 'm9-test')
        assert compiled['parts']
        for part, view in zip(compiled['parts'], phase_views(current), strict=True):
            derivation_lines = view['explanation'].splitlines()
            assert derivation_lines and all(line.startswith('$') and line.endswith('$')
                                            for line in derivation_lines)
            assert all(text not in view['explanation'] for text in
                       ('换元', '整体替换', '不能替代', '逐项代入', '不能再翻倍'))
            assert part['stem_board']['items'][1]['math'] is None
            expected = deepcopy(view['derivation'])
            expected['items'][1]['math'] = None
            assert part['stem_board'] == expected
            if part['interaction']['type'] == 'choice':
                options = part['interaction']['options']
                assert len(options) >= 2
                assert len({row['label'] for row in options}) == len(options)


def test_nested_calls_inner_card_cannot_leak_outer_output():
    data = values('q28b')
    assert [row['function_name'] for row in data['evaluation_result']['calls']] == ['g', 'f']
    inner = compile_evaluation([{'template': 'function_evaluation_derivation',
                                'values': encode_value({**data, 'phase': 'inner'})}], 'inner')['parts']
    assert len(inner) == 1
    assert '-\\frac{1}{4}' not in str(inner)
    assert 'g' in inner[0]['title']
    outer = phase_views({**data, 'phase': 'substitute'})[0]
    assert r'\frac{1}{2}' in outer['derivation']['items'][0]['math']
    assert '完整输入' in outer['question']
    assert r'f\left(\frac{1}{2}\right)=' in outer['explanation']
    assert r'=-\frac{1}{4}' in outer['explanation'].replace(' ', '')
    assert '换元' not in outer['explanation']


def test_numeric_substitution_derivation_has_function_substitution_and_value_on_one_line():
    inner = phase_views({**values('q28b'), 'phase': 'inner'})[0]
    proof = inner['explanation']
    assert proof.startswith(r'$g\left(0\right)=')
    assert proof.endswith(r'=\frac{1}{2}$')
    assert proof.count('=') == 2
    assert '0' in proof.split('=')[1] and '+2' in proof.split('=')[1]
    assert '\n' not in proof and '。' not in proof


@pytest.mark.parametrize(('index', 'inner', 'outer'), [(0, 'g', 'f'), (1, 'f', 'g')])
def test_composite_input_card_teaches_actual_order_without_computing_outputs(index, inner, outer):
    data = {**values('q28b', index), 'phase': 'input'}
    card = phase_views(data)[0]
    assert card['title'] == '确定代入顺序'
    assert '应按什么顺序代入' in card['question']
    choices = card['interaction']['options']
    assert len(choices) == 2
    assert choices[0]['label'] == f'先把 $0$ 代入 ${inner}$，再把 ${inner}\\left(0\\right)$ 的结果代入 ${outer}$'
    assert choices[1]['label'].startswith(f'先把 $0$ 代入 ${outer}$')
    flow = card['derivation']['items'][1]['math']
    assert flow == rf'0\xrightarrow{{{inner}}}{inner}\left(0\right)\xrightarrow{{{outer}}}{outer}\left({inner}\left(0\right)\right)'
    assert '=' not in flow
    part = compile_evaluation([{'template': 'function_evaluation_derivation',
                               'values': encode_value(data)}], 'order')['parts'][0]
    assert part['stem_board']['items'][1]['math'] is None
    assert part['completion_board']['items'][1]['math'] == flow


@pytest.mark.parametrize('names', [('f', 'g', 'h'), ('f', 'f')])
def test_composite_input_order_projection_handles_deeper_ast_and_repeated_functions(names):
    from tests.solver.test_graph_function_evaluation_math import CALL, N, U, description, function
    expression = N(0)
    for name in names:
        expression = CALL(name, expression)
    desc = description(expression, [function(name, ['+', U, N(1)]) for name in dict.fromkeys(names)], variable=False)
    # Projection follows the AST independently of the runtime's two-layer budget.
    card = _composite_input_card(desc, _ast(expression, desc))
    labels = [option['label'] for option in card['interaction']['options']]
    assert len(set(labels)) == 2
    flow = card['derivation']['items'][1]['math']
    assert flow.count(r'\xrightarrow') == len(names)
    assert labels[0].count('代入') == len(names)
    assert '3' not in flow  # Intermediate/final values belong to calculation cards.
    if len(set(names)) == 1:
        assert '不使用上一层的结果' in labels[1]
        assert phase_views({'description': desc, 'evaluation_result': evaluate(desc), 'phase': 'input'})[0] == card


def test_composite_input_dependency_board_keeps_operations_and_independent_branches():
    from tests.solver.test_graph_function_evaluation_math import CALL, N, U, X, description, function
    functions = [function(name, ['+', U, N(1)]) for name in ('f', 'g', 'h')]
    for argument in (['+', CALL('g', X), N(1)], ['+', CALL('g', X), CALL('h', X)]):
        desc = description(CALL('f', argument), functions)
        original = deepcopy(desc)
        card = phase_views({'description': desc, 'evaluation_result': evaluate(desc), 'phase': 'input'})[0]
        flow = card['derivation']['items'][1]['math']
        assert r'g\left(x\right)+' in flow
        assert r'\xrightarrow{f}f\left(g\left(x\right)+' in flow
        if argument[-1][0] == 'function_call':
            assert r'x\xrightarrow{h}h\left(x\right)' in flow
            assert r'g\left(x\right)\xrightarrow{h}' not in flow
        assert desc == original
    parallel = description(['+', CALL('f', X), CALL('g', X)], functions)
    card = phase_views({'description': parallel, 'evaluation_result': evaluate(parallel), 'phase': 'input'})[0]
    assert card['title'] == '明确完整输入'
    assert len(card['interaction']['options']) == 2
    assert r'\xrightarrow' not in card['derivation']['items'][1]['math']


@pytest.mark.parametrize('variable', ['x', 't'])
def test_substitution_card_keeps_each_original_function_variable(variable):
    candidate = json.loads((FIXTURES / 'q28b-candidate.json').read_text())
    candidate['root']['definitions'] = [f'f({variable})=3*{variable}^2-1', 'g(s)=1/(s+2)']
    description = inspect_evaluation_target(candidate, '/root/goals/0')
    assert [row['variable'] for row in description['functions']] == [variable, 's']
    data = {'description': description, 'evaluation_result': evaluate(description)}
    for phase, name, symbol in [('inner', 'g', 's'), ('substitute', 'f', variable)]:
        card = phase_views({**data, 'phase': phase})[0]
        rule = card['derivation']['items'][0]['math']
        assert f'{name}({symbol})=' in rule
        assert symbol in rule.split('=', 1)[1]
        assert rf'{name}\left(' in card['explanation']
        assert '(u)' not in rule and '$u$' not in card['explanation']


def test_original_input_and_function_denominator_restrictions_survive_projection():
    data = values('q28c', 1)
    card = phase_views({**data, 'phase': 'domain'})[0]
    board = card['derivation']
    left, right = board['condition_groups']
    assert r'\frac{1}{x}-1' in left['math'].replace(' ', '')
    assert r'x\ne0' in left['math']
    assert r'D_{g}=\mathbb{R}\setminus' in right['math']
    assert r'\ne -2' in right['math']
    assert r'x\ne0' not in right['math']
    assert len(data['evaluation_result']['constraints']) == 2
    conclusion = phase_views({**data, 'phase': 'conclusion'})[0]
    assert '-1' in conclusion['derivation']['items'][1]['math']
    assert '0' in conclusion['derivation']['items'][1]['math']


def test_original_target_domain_is_shown_without_function_body_restrictions():
    from tests.solver.test_graph_function_evaluation_math import CALL, N, U, X, description, function
    desc = description(CALL('h', X), [function('h', ['^', U, N(2)])],
                       domain=['interval', True, True, N(2), N(3)])
    result = evaluate(desc)
    assert result['constraints'] == []
    card = phase_views({'description': desc, 'evaluation_result': result, 'phase': 'domain'})[0]
    original = card['derivation']['items'][0]['note']
    assert '无限制' not in original
    assert r'x\in' in original and '2' in original and '3' in original
    assert r'x\in' in card['explanation']


def test_polynomial_domain_card_keeps_both_conditions_instead_of_unrestricted_shortcut():
    data = {**values('q28c'), 'phase': 'domain'}
    part = compile_evaluation([{'template': 'function_evaluation_derivation',
                               'values': encode_value(data)}], 'domain')['parts'][0]
    groups = part['stem_board']['condition_groups']
    assert len(groups) == 2
    assert r'x-1' in groups[0]['math'].replace(' ', '') and '有意义' in groups[0]['math']
    assert r'D_{f}=\mathbb{R}' in groups[1]['math']
    assert r'\in D_{f}' in groups[1]['math']
    assert '无限制' not in str(groups)
    assert part['stem_board']['items'][1]['math'] is None
    assert part['completion_board']['items'][1]['math'] == r'\mathbb{R}'
    assert part['completion_board']['condition_groups'] == groups


@pytest.mark.parametrize('nested', [False, True])
def test_domain_groups_keep_cancelled_input_restrictions_and_nested_function_sources(nested):
    from tests.solver.test_graph_function_evaluation_math import CALL, N, U, X, description, function
    argument = CALL('g', X) if nested else ['/', X, X]
    desc = description(CALL('h', argument), [function('h', U), function('g', ['/', U, U])])
    card = phase_views({'description': desc, 'evaluation_result': evaluate(desc), 'phase': 'domain'})[0]
    left, right = card['derivation']['condition_groups']
    assert (r'g\left(x\right)' if nested else r'\frac{x}{x}') in left['math']
    assert r'x\ne0' in left['math']
    assert 'D_{h}' in right['math'] and 'D_{g}' not in right['math']


def test_domain_groups_separate_declared_function_domain_and_target_operation_restriction():
    from tests.solver.test_graph_function_evaluation_math import CALL, N, U, X, description, function
    desc = description(['/', N(1), CALL('h', X)],
                       [function('h', U, ['interval', True, True, N(-1), N(1)])])
    card = phase_views({'description': desc, 'evaluation_result': evaluate(desc), 'phase': 'domain'})[0]
    board = card['derivation']
    assert 'D_{h}=' in board['condition_groups'][1]['math']
    assert '-1' in board['condition_groups'][1]['math']
    assert r'x\in D_{h}' in board['condition_groups'][1]['math']
    assert r'x\ne0' not in str(board['condition_groups'])
    assert '目标式限制' in board['items'][0]['note'] and r'x\ne0' in board['items'][0]['note']


def test_undefined_input_domain_card_preserves_source_instead_of_rendering_none():
    from tests.solver.test_graph_function_evaluation_math import CALL, N, U, description, function
    desc = description(CALL('h', ['/', N(1), N(0)]), [function('h', U)], variable=False)
    card = phase_views({'description': desc, 'evaluation_result': evaluate(desc), 'phase': 'domain'})[0]
    left = card['derivation']['condition_groups'][0]['math']
    assert r'\frac{1}{0}' in left and r'0\ne0' in left
    assert 'None' not in str(card)


def test_q29b_has_trial_proof_pair_count_and_single_leftover_stages():
    constant = values('q29b')
    assert phase_flags(constant['description'], constant['evaluation_result'])['has_trial']
    trial = phase_views({**constant, 'phase': 'trial'})
    assert '不能替代' in trial[-1]['feedback']['answer']
    assert '完整合法范围内验证' in trial[-1]['interaction']['options'][0]['label']
    total = values('q29b', 1)
    pairing = phase_views({**total, 'phase': 'pairing'})[0]
    assert '201=2\\times 100+1' == pairing['derivation']['items'][1]['math']
    leftover = compile_evaluation([{'template': 'function_evaluation_derivation',
                                   'values': encode_value({**total, 'phase': 'leftovers'})}], 'left')['parts'][0]
    assert r'\frac{3}{2}' not in str(leftover['stem_board'])
    assert 'f\\left(1\\right)' in leftover['stem_board']['items'][0]['math']
    assert phase_views({**total, 'phase': 'sum'})[0]['title'] == '合计'


def test_unequal_trials_are_a_counterexample_and_compound_sum_terms_do_not_drop_calls():
    from tests.solver.test_graph_function_evaluation_math import CALL, N, U, X, description, function
    desc = description(['+', CALL('h', X), CALL('h', ['/', N(1), X])],
                       [function('h', U)], kind='check_constant')
    result = evaluate(desc)
    trial = phase_views({'description': desc, 'evaluation_result': result, 'phase': 'trial'})[-1]
    if len({row['total'] for row in result['trials']}) > 1:
        assert r'x=1\Rightarrow 2' in trial['explanation']
        assert r'x=2\Rightarrow \frac{5}{2}' in trial['explanation']
        assert r'\text{不是定值}' in trial['explanation']
        assert '已经反证' in trial['interaction']['options'][0]['label']
    desc = {'kind': 'finite_sum', 'target_ref': '/root/goals/0', 'functions': [function('h', U)],
            'terms': [{'expression_ast': ['+', CALL('h', N(1)), CALL('h', N(2))], 'source_ref': 'sum:0'}]}
    result = evaluate(desc)
    card = phase_views({'description': desc, 'evaluation_result': result, 'phase': 'leftovers'})[0]
    assert 'h\\left(1\\right)+h\\left(2\\right)' in card['derivation']['items'][0]['math']
    assert 'None' not in str(card)


def test_choice_order_is_stable_but_not_always_first_and_completion_board_is_local():
    data = {**values('q29b'), 'phase': 'trial'}
    seed = {'template': 'function_evaluation_derivation', 'values': encode_value(data)}
    positions = set()
    for index in range(8):
        compiled = compile_evaluation([seed], f'choice-order-{index}')
        assert compiled == compile_evaluation([seed], f'choice-order-{index}')
        for part, view in zip(compiled['parts'], phase_views(data), strict=True):
            positions.add(next(i for i, option in enumerate(part['interaction']['options'])
                               if option['value'] in part['expected_answer']['one_of']))
            assert part['completion_board'] == view['derivation']
            assert part['stem_board']['items'][1]['math'] is None
    assert len(positions) > 1


def test_wrong_choice_feedback_guides_without_revealing_calculation_or_pair_count():
    nested = values('q28b')
    for phase in ('inner', 'substitute'):
        card = phase_views({**nested, 'phase': phase})[0]
        assert '整体' in card['question'] or '完整输入' in card['question']
        assert '运算顺序' in card['feedback']['answer']
        assert '$' not in card['feedback']['answer']
    pairing = phase_views({**values('q29b', 1), 'phase': 'pairing'})[0]
    assert '100' not in pairing['feedback']['answer']
    assert '100' in pairing['explanation']


def test_sum_derivations_work_with_compact_occurrence_evidence():
    from shuxueshuo_server.graph_lesson.stage_three.evaluation_runtime import _compact_sum
    from tests.solver.test_graph_function_evaluation_math import CALL, N, U, function
    duplicate = {'kind': 'finite_sum', 'target_ref': '/root/goals/0',
                 'functions': [function('h', ['+', U, N(1)])],
                 'terms': [{'expression_ast': CALL('h', N(1)), 'source_ref': f'sum:{i}'} for i in range(2)]}
    for data in [values('q29b', 1), {'description': duplicate, 'evaluation_result': evaluate(duplicate)}]:
        compact = {**data, 'evaluation_result': _compact_sum(data['evaluation_result'])}
        flags = phase_flags(data['description'], data['evaluation_result'])
        for phase in ('pairing', 'leftovers', 'sum'):
            if flags['has_' + phase]:
                assert phase_views({**data, 'phase': phase}) == phase_views({**compact, 'phase': phase})
    remaining = phase_views({**compact, 'phase': 'leftovers'})[0]
    assert remaining['derivation']['items'][0]['math'].count(r'h\left(1\right)') == 2
    assert r'2\times' in phase_views({**compact, 'phase': 'sum'})[0]['explanation']


@pytest.mark.parametrize('nested', [False, True])
def test_finite_domain_substitution_choices_have_only_one_correct_answer(nested):
    from tests.solver.test_graph_function_evaluation_math import CALL, N, U, X, description, function
    expression = CALL('f', CALL('f', X)) if nested else CALL('f', X)
    desc = description(expression, [function('f', U, ['set', N(0)])])
    result = evaluate(desc)
    assert result['domain'] == sp.FiniteSet(0)
    for phase in (('inner', 'substitute') if nested else ('substitute',)):
        for card in phase_views({'description': desc, 'evaluation_result': result, 'phase': phase}):
            correct = []
            for option in card['interaction']['options']:
                answer = sp.sympify(option['label'].strip('$'), locals={'x': result['variable']})
                if all(sp.simplify((answer - result['expression']).subs(result['variable'], point)) == 0
                       for point in result['domain']):
                    correct.append(option['value'])
            assert correct == card['expected_answer']['one_of']
            assert len(card['interaction']['options']) >= 2


def test_empty_sum_renders_zero_and_passes_pending_and_completed_board_contracts():
    from tests.solver.test_graph_function_evaluation_math import summation
    from shuxueshuo_server.graph_lesson.stage_three.evaluation_runtime import _compact_sum
    root = Path(__file__).resolve().parents[3]
    schema = json.loads((root / 'internal/schemas/graph-math-step-v2.schema.json').read_text())
    highlight_validator = Draft202012Validator({**schema['properties']['highlight'], '$defs': schema['$defs']})
    desc = summation(0)
    result = evaluate(desc)
    assert result['term_count'] == 0 and result['total'] == 0
    for evidence in (result, _compact_sum(result)):
        data = {'description': desc, 'evaluation_result': evidence, 'phase': 'sum'}
        card = phase_views(data)[0]
        highlight_validator.validate(card['derivation'])
        assert card['derivation']['items'][0]['math'] == '0'
        assert '==' not in card['explanation']
        part = compile_evaluation([{'template': 'function_evaluation_derivation',
                                    'values': encode_value(data)}], 'empty-sum')['parts'][0]
        assert part['stem_board']['items'][0]['math'] == '0'
        assert part['stem_board']['items'][1]['math'] is None
        assert part['completion_board']['items'][1]['math'] == '0'


def test_pairing_diagram_preserves_arrangement_between_count_and_leftover_steps():
    data = values('q29b', 1)
    pair_board = phase_views({**data, 'phase': 'pairing'})[0]['derivation']
    leftover_board = phase_views({**data, 'phase': 'leftovers'})[0]['derivation']
    pairs = pair_board['pairing_diagram']
    assert pairs == {**leftover_board['pairing_diagram'], 'focus': 'pairs'}
    assert pairs['pair_value'] == '3'
    assert pairs['omitted_pairs'] == 97
    assert [row['left_math'] for row in pairs['pairs']] == [
        r'f\left(2\right)', r'f\left(3\right)', r'f\left(101\right)']
    assert pairs['pairs'][-1]['right_math'] == r'f\left(\frac{1}{101}\right)'
    assert [row['math'] for row in pairs['leftovers']] == [r'f\left(1\right)']
    assert r'\frac{3}{2}' not in str(pairs)
    assert presentation({**data, 'phase': 'pairing'})['pairing_diagram'] == pairs


def test_pairing_diagram_retains_duplicate_occurrences_and_omits_only_middle():
    from tests.solver.test_graph_function_evaluation_math import CALL, N, U, function
    inputs = [2, 2, 1, 1, 1, 1, 1, '1/2', '1/2']
    desc = {'kind': 'finite_sum', 'target_ref': '/root/goals/0',
            'functions': [function('h', ['/', ['+', U, N(2)], ['+', U, N(1)]])],
            'terms': [{'expression_ast': CALL('h', N(value)), 'source_ref': f'sum:{i}'}
                      for i, value in enumerate(inputs)]}
    result = evaluate(desc)
    board = phase_views({'description': desc, 'evaluation_result': result, 'phase': 'pairing'})[0]['derivation']
    diagram = board['pairing_diagram']
    assert len(diagram['pairs']) == 2
    assert len({row['left_id'] for row in diagram['pairs']}) == 2
    assert len({row['right_id'] for row in diagram['pairs']}) == 2
    assert diagram['pairs'][0]['left_math'] == diagram['pairs'][1]['left_math']
    assert len(diagram['leftovers']) == 3 and diagram['omitted_leftovers'] == 2
    assert [row['id'] for row in diagram['leftovers']] == result['leftovers'][:2] + result['leftovers'][-1:]
    assert all(row['math'] == r'h\left(1\right)' for row in diagram['leftovers'])


def test_constant_card_uses_expanded_fraction_chain_and_preserves_original_domain():
    card = phase_views({**values('q29b'), 'phase': 'constant'})[0]
    assert r'$x\in\mathbb{R}\setminus\left\{-1,0\right\}$' in card['explanation'].replace(' ', '')
    assert r'=\frac{3 x + 3}{x + 1}' in card['explanation']
    assert r'\left(2 x + 1\right)' in card['explanation']
    assert r'3 x + 3' not in card['derivation']['items'][0]['math']


def test_constant_card_pending_labels_and_wrong_feedback_do_not_reveal_verdict():
    data = {**values('q29b'), 'phase': 'constant'}
    seed = {'template': 'function_evaluation_derivation', 'values': encode_value(data)}
    part = compile_evaluation([seed], 'constant-hidden')['parts'][0]
    assert part['stem_board']['items'][1]['label'] == '判断结果'
    assert part['stem_board']['items'][1]['math'] is None
    assert '是定值' not in part['feedback']['answer']
    assert '是定值' in part['completion_board']['items'][1]['math']


def test_finite_domain_constant_derivation_checks_each_point_without_claiming_polynomial_identity():
    from tests.solver.test_graph_function_evaluation_math import CALL, N, U, X, description, function
    desc = description(CALL('h', X),
                       [function('h', ['^', U, N(2)], ['set', N(-1), N(1)])], kind='check_constant')
    result = evaluate(desc)
    assert result['proof']['kind'] == 'complete_finite_domain'
    proof = phase_views({'description': desc, 'evaluation_result': result, 'phase': 'constant'})[0]['explanation']
    assert r'h\left(x\right)' in proof
    assert r'|_{x=-1}=1' in proof
    assert r'|_{x=1}=1' in proof
    assert r'x\in' in proof and '-1' in proof
    assert r'x^{2}=1' not in proof and r'x^2=1' not in proof


def test_nonconstant_derivation_keeps_legal_counterexample_values():
    from tests.solver.test_graph_function_evaluation_math import CALL, U, X, description, function
    from shuxueshuo_server.graph_lesson.stage_three.math_values import latex
    desc = description(CALL('h', X), [function('h', U)], kind='check_constant')
    result = evaluate(desc)
    proof = phase_views({'description': desc, 'evaluation_result': result, 'phase': 'constant'})[0]['explanation']
    assert result['is_constant'] is False
    assert len(result['witness']) == 2
    for witness in result['witness']:
        assert rf'|_{{x={latex(witness["input"])}}}={latex(witness["output"])}' in proof
    assert r'\ne' in proof


def test_q29_trial_keeps_both_f_one_occurrences_and_hides_total():
    data = {**values('q29b'), 'phase': 'trial'}
    trial = next(index for index, row in enumerate(data['evaluation_result']['trials']) if row['input'] == 1)
    part = compile_evaluation([{'template': 'function_evaluation_derivation',
                                'values': encode_value(data)}], 'trial-source')['parts'][trial]
    left = part['stem_board']['items'][0]['math']
    assert r'f\left(1\right)+f\left(1\right)' in left
    assert left.count(r'\frac{\left(1\right)+2}{\left(1\right)+1}') == 2
    assert '3' not in left
    assert part['stem_board']['items'][1]['math'] is None
    assert part['completion_board']['items'][1]['math'] == '3'


@pytest.mark.parametrize('operator', ['-', '*'])
def test_trial_and_constant_boards_preserve_full_target_operator(operator):
    from tests.solver.test_graph_function_evaluation_math import CALL, N, U, X, description, function
    desc = description([operator, CALL('h', X), CALL('h', ['/', N(1), X])],
                       [function('h', U)], kind='check_constant')
    result = evaluate(desc)
    for phase in ('trial', 'constant'):
        card = phase_views({'description': desc, 'evaluation_result': result, 'phase': phase})[0]
        left = card['derivation']['items'][0]['math']
        assert left.count(r'h\left(') == 2
        assert (r'\cdot' if operator == '*' else '-') in left
        assert '=' in left


def test_cofinite_domain_display_is_compact_without_changing_evidence():
    data = values('q28c', 1)
    original = encode_value(data['evaluation_result'])
    conclusion = phase_views({**data, 'phase': 'conclusion'})[0]
    assert r'\mathbb{R}\setminus' in conclusion['derivation']['items'][1]['math']
    assert r'\cup' not in conclusion['derivation']['items'][1]['math']
    domain = phase_views({**data, 'phase': 'domain'})[0]
    assert r'\cup' not in domain['interaction']['options'][0]['label']
    assert encode_value(data['evaluation_result']) == original
    from tests.solver.test_graph_function_evaluation_math import CALL, N, U, X, description, function
    desc = description(CALL('h', X), [function('h', U, ['interval', True, True, N(0), N(2)])])
    bounded = evaluate(desc)
    result = phase_views({'description': desc, 'evaluation_result': bounded, 'phase': 'conclusion'})[0]
    assert r'\setminus' not in result['derivation']['items'][1]['math']
