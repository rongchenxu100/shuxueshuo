"""R0 cards from source syntax and checked coefficient/parameter evidence."""
from copy import deepcopy
from hashlib import sha256

import sympy as sp

from ..function_parity import reflect_ast
from ..stage_one.function_domain import ARGUMENT, expression_latex
from .absolute_graph_presentation import choice_card
from .math_values import latex
from .monotonicity_parameter_presentation import _gathered_rows, _lines
from .trajectory import decode_value

PROPERTY = {'odd': '奇函数', 'even': '偶函数', 'both': '既奇又偶',
            'odd_only': '奇函数且不是偶函数', 'even_only': '偶函数且不是奇函数'}


def _display_ast(ast):
    if ast == ['bound', 'function_argument']:
        return ARGUMENT
    return [_display_ast(v) if isinstance(v, list) else v for v in ast]


def condition_latex(ast, variable):
    if ast[0] in ('and', 'or'):
        operator = r'\land ' if ast[0] == 'and' else r'\lor '
        return operator.join('(' + condition_latex(v, variable) + ')' for v in ast[1:])
    if ast[0] == '∉':
        return expression_latex(ast[1], variable) + r'\notin ' + expression_latex(ast[2], variable)
    return expression_latex(ast, variable)


def condition_value_latex(condition):
    """Show simplified constant obligations as student-facing statements."""
    if condition is sp.true or condition is True:
        return r'\text{条件恒成立，不增加参数限制}'
    if condition is sp.false or condition is False:
        return r'\text{条件不成立，没有参数满足}'
    return latex(condition)


def board_lines(proof):
    """Read-card boards render each line separately; prose rows stay plain text."""
    rows = []
    for row in _gathered_rows(proof) or [proof]:
        row = row.removeprefix('{}')
        prose = row.startswith(r'\text{') and row.endswith('}') and row.count('{') == 1
        rows.append(row[len(r'\text{'):-1] if prose else '$$' + row + '$$')
    return rows


def membership_options(parameter, correct, wrong):
    return parameter + r'\in ' + correct, [parameter + r'\in ' + v for v in wrong]


def _read(title, question, left_label, left, right_label, right, proof):
    view = choice_card(title, question, left_label, left, right_label, right, [], proof)
    view.update(interaction={'type': 'read'}, expected_answer={})
    return view


def compare_view(title, question, relations, rows, right_label, conditions, *,
                 relation_label='要恒成立的关系', rows_label='逐项比较'):
    view = _read(title, question, relation_label, relations, right_label, conditions, _lines([*rows, conditions]))
    if rows:
        view['read_board'] = {'layout': 'derivation', 'caption': title, 'connector': '⇒', 'items': [
            {'label': rows_label, 'math': _lines(rows)}, {'label': right_label, 'math': conditions}]}
    return view


def phase_views(values):
    d, phase = values['description'], values['phase']
    if d.get('analysis_mode') == 'joint':
        from .parity_joint_presentation import phase_views as joint_views
        return joint_views(values)
    if d.get('analysis_mode') == 'original':
        from .parity_original_presentation import phase_views as original_views
        return original_views(values)
    if d.get('analysis_mode') == 'domain':
        from .parity_domain_presentation import phase_views as domain_views
        return domain_views(values)
    ast = _display_ast(d['expression_ast'])
    x, p, f = d['variable'], d['parameter'], d['function']
    fx, fneg = rf'{f}({x})', rf'{f}(-{x})'
    original = fx + '=' + expression_latex(ast, x)
    properties = {fact['property'] for fact in d['parity_facts']}
    facts = r'\text{' + '、'.join(PROPERTY[k] for k in sorted(properties)) + '}'
    reflected = fneg + '=' + expression_latex(reflect_ast(ast), x)
    signs = {s for prop in properties for s in ({-1, 1} if prop == 'both' else {-1} if prop.startswith('odd') else {1})}
    relations = [fneg + ('=-' if sign == -1 else '=') + fx for sign in sorted(signs)]
    if phase == 'domain':
        return [choice_card('检查定义域', '原式是多项式。对每个实数参数，定义域是什么？它是否关于原点对称？',
                            '原函数与题给性质', _lines([original, facts]), '定义域', r'\mathbb R',
                            [r'(0,+\infty)', r'\mathbb R\setminus\{0\}'],
                            _lines([r'D=\mathbb R', r'-D=D']))]
    if phase == 'identity':
        wrong = [fneg + ('=-' if signs == {1} else '=') + fx] if len(signs) == 1 else []
        view = choice_card('把奇偶性写成关系', '先把相反数作为整体代入。题给的奇偶性要求哪条关系对每个合法输入都成立？',
                           '原函数与相反输入', _lines([original, reflected, facts]), '要恒成立的关系',
                           _lines(relations), wrong, _lines([reflected, *relations]))
        if not wrong:
            view.update(interaction={'type': 'read'}, expected_answer={})
        return [view]
    if phase == 'compare':
        comparison = values['evidence']
        terms = {i: x + rf'^{{{i}}}\text{{ 项系数：}}' for i in range(2, 5)}
        terms.update({1: x + r'\text{ 项系数：}', 0: r'\text{常数项：}'})
        rows = [terms[int(r['degree'])] + latex(r['left']) + '=' + latex(r['right']) for r in comparison['rows']]
        conditions = [latex(v) + '=0' for v in comparison['equations']]
        summary = _lines(conditions) if conditions else r'\text{对所有实数参数都恒成立}'
        return [compare_view('比较对应项的系数', '两边要对所有实数输入都相等，各次项的系数必须分别相等；相同的项不再限制参数。',
                             _lines(relations), rows, '系数条件', summary)]
    model = values['evidence']
    solution = model['feasible_set']
    conditions = [condition_value_latex(v) for v in model['conditions']]
    if model['exclusive']:
        conditions += [rf'{p}\notin {latex(model["zero_set"])}\quad\text{{排除恒为零的情形}}']
    proof = _lines([rf'{p}\in {latex(model["parity_set"])}', *conditions, rf'{p}\in {latex(solution)}'])
    if phase == 'solve':
        candidates = [sp.S.Reals, sp.S.EmptySet, sp.FiniteSet(0), model['parity_set'], model['zero_set']]
        if isinstance(solution, sp.FiniteSet):
            candidates += [sp.FiniteSet(-v) for v in solution] + [solution | sp.FiniteSet(0)]
        wrong = []
        for alternative in candidates:
            if alternative == solution or alternative in wrong:
                continue
            wrong.append(alternative)
        coefficient = [latex(v) + '=0' for v in model['comparison']['equations']] or [r'\text{系数条件对每个实数参数都成立}']
        known = [r'\text{定义域 }\mathbb R\text{ 关于原点对称}', *coefficient, *conditions]
        right, others = membership_options(p, latex(solution), [latex(v) for v in wrong[:3]])
        return [choice_card('合并全部参数条件', '将系数条件与原参数限制一起求解；若题目明确排除零函数或声明次数，也要同时满足。',
                            '已得到的条件', _lines(known), '参数的取值集合', right, others, proof)]
    # Back substitution is displayed only for a complete, finite candidate set;
    # infinite solutions are verified symbolically, never by sample parameters.
    from ..parity_parameter_math import source
    variable, parameter, expr, _, _, _ = source(d)
    if isinstance(solution, sp.FiniteSet) and solution != sp.S.EmptySet:
        given, checks = [], []
        for value in sorted(solution):
            prefix = rf'{p}={latex(value)}\text{{ 时，}}' if len(solution) > 1 else ''
            value_expr = sp.expand(expr.subs(parameter, value))
            given.append(prefix + fx + '=' + latex(value_expr))
            checks.append(prefix + fneg + '=' + latex(sp.expand(value_expr.subs(variable, -variable))))
            if model['exclusive']:
                checks.append(prefix + fx + r'\text{ 不恒为零}')
        return [substitution_view(d, solution, given, [*checks, r'\Rightarrow\ ' + r'\text{、}'.join(relations)])]
    return [_read('代回核验', '把求出的参数代回原式检查。',
                  '原函数', original, '最终参数集合', latex(solution), proof)]


def substitution_view(d, solution, given, checks):
    """Left: the original after substituting the parameter; right: the check."""
    p = d['parameter']
    single = len(solution) == 1
    value = latex(next(iter(solution)))
    return _read('代回核验', f'把 ${p}={value}$ 代入原式检查。' if single else '把求出的参数代入原式检查。',
                 f'代入 {p}={value}' if single else '代入参数', _lines(given), '检验', _lines(checks),
                 _lines([*given, *checks, p + r'\in ' + latex(solution)]))


def presentation(values):
    view = phase_views(decode_value(values))[-1]
    left, right = view['derivation']['items']
    return {'formula_title': view['title'], 'formula_explanation': '$$'+view['proof']+'$$',
            'derivation_caption': view['title'], 'derivation_left_label': left['label'],
            'derivation_left_math': left['math'], 'derivation_left_note': '',
            'derivation_right_label': right['label'], 'derivation_right_math': right['math']}


def compile_cards(seeds, interaction_id):
    seed, = seeds
    parts = []
    for index, view in enumerate(phase_views(decode_value(seed['values'])), 1):
        board, interaction = deepcopy(view['derivation']), deepcopy(view['interaction'])
        if interaction['type'] == 'read':
            board = view.get('read_board') or {'caption': view['title'], 'lines': board_lines(view['proof'])}
        else:
            board['items'][1]['math'] = None
            interaction['options'].sort(key=lambda row: sha256(f'{interaction_id}:{index}:{row["value"]}'.encode()).digest())
        parts.append({'id': f'{interaction_id}#{index}', 'title': view['title'], 'question': view['question'],
                      'interaction': interaction, 'expected_answer': view['expected_answer'],
                      'feedback': view['feedback'], 'submit_label': '继续' if interaction['type'] == 'read' else '确认判断',
                      'stem_board': board, 'completion_board': view['derivation']})
        values = decode_value(seed['values'])
        if values['description'].get('analysis_mode') in ('original', 'quartic'):
            from .parity_original_presentation import attach_graphs
            attach_graphs(parts[-1], values)
    return {'parts': parts, 'diagnostics': []}
