"""M1 parity cards, projected from the checked domain symmetry and relations."""
from copy import deepcopy
from hashlib import sha256

import sympy as sp

from .. import function_cells
from ..function_parity import reflect_ast
from ..piecewise_evaluation import is_piecewise
from ..stage_one.function_domain import ARGUMENT, expression_latex
from .absolute_graph_presentation import choice_card
from .equality_presentation import _domain_latex
from .math_values import latex
from .monotonicity_parameter_presentation import _lines, _with_feedback
from .trajectory import decode_value

LABELS = {'odd_only': '是奇函数，不是偶函数', 'even_only': '是偶函数，不是奇函数',
          'both': '既是奇函数又是偶函数', 'neither': '既不是奇函数也不是偶函数'}
PROPERTY = {'odd': '奇函数', 'even': '偶函数'}


def _value(ast, argument):
    if is_piecewise(ast):
        symbol = sp.Dummy('input', real=True)
        return sp.Piecewise(*[(_value(body, argument), domain.as_relational(symbol).subs(symbol, argument))
                              for body, domain in function_cells.branches(ast)])
    if ast == ARGUMENT:
        return argument
    if ast[0] == 'number':
        return sp.Rational(ast[1])
    if ast[0] == 'neg':
        return -_value(ast[1], argument)
    if ast[0] == 'call':
        return {'abs': sp.Abs, 'sqrt': sp.sqrt}[ast[1]](_value(ast[2], argument))
    lhs, rhs = _value(ast[1], argument), _value(ast[2], argument)
    return {'+': lambda: lhs + rhs, '-': lambda: lhs - rhs, '*': lambda: lhs * rhs,
            '/': lambda: lhs / rhs, '^': lambda: lhs ** rhs}[ast[0]]()


def _context(values):
    goal = decode_value(values['description'])
    function = goal['function']
    name, variable = function['function_name'], function['variable']
    x = sp.Symbol(variable, real=True)
    call = lambda arg: rf'{name}\left({arg}\right)'
    ast = function['expression_ast']
    return {'function': function, 'ast': ast, 'name': name, 'x': x, 'variable': latex(x),
            'domain': function_cells.source_domain(function)[0],
            'call': call, 'fx': call(latex(x)), 'fneg': call('-' + latex(x)),
            'original': expression_latex(ast, latex(x)),
            'substituted': substitution_latex(reflect_ast(ast), latex(x)),
            'simplified': latex(_value(ast, -x))}


def _definition(c):
    return c['fx'] + '=' + c['original']


def _domain_view(c, evidence):
    symmetry = evidence['symmetry']
    domain = _domain_latex(symmetry['domain'])
    reflected = _domain_latex(symmetry['reflected_domain'])
    symmetric = r'D\ \text{关于原点对称}'
    asymmetric = r'D\ \text{不关于原点对称}'
    if symmetry['status'] == 'proved':
        right, wrong = symmetric, [asymmetric]
        proof = [rf'D={domain}', rf'-D={reflected}=D']
    else:
        point = symmetry['witness']['point']
        right, wrong = asymmetric, [symmetric]
        proof = [rf'D={domain}', rf'{latex(point)}\in D,\ {latex(-point)}\notin D']
    view = choice_card('检查定义域的对称性', '先求出定义域 $D$。把 $D$ 中每个数换成相反数，得到的集合还是 $D$ 吗？',
                       '函数与定义域', _lines([_definition(c), rf'D={domain}']), '定义域的对称性', right, wrong,
                       _lines(proof))
    return _with_feedback(view, {
        symmetric: '找一找：是否有某个数在定义域内，而它的相反数不在？端点的开闭和挖去的点都要换成相反数再比较。',
        asymmetric: '把定义域内每个数取相反数后，得到的集合与原定义域相同。'})


def _replace(ast, index, counter):
    if ast == ARGUMENT:
        counter[0] += 1
        return ['neg', ARGUMENT] if counter[0] - 1 == index else ast
    if not isinstance(ast, list) or ast[0] == 'number':
        return ast
    return [ast[0], *[_replace(child, index, counter) for child in ast[1:]]]


def _occurrences(ast):
    if ast == ARGUMENT:
        return 1
    if not isinstance(ast, list) or ast[0] == 'number':
        return 0
    return sum(_occurrences(child) for child in ast[1:])


def _power_sign_slip(ast):
    """(-x)^n misread as -(x^n); every other occurrence is substituted."""
    if ast == ARGUMENT:
        return ['neg', ARGUMENT]
    if not isinstance(ast, list) or ast[0] == 'number':
        return ast
    if ast[0] == '^' and ast[1] == ARGUMENT:
        return ['neg', deepcopy(ast)]
    return [ast[0], *[_power_sign_slip(child) for child in ast[1:]]]


def _slots(tree):
    if tree == ['neg', ARGUMENT]:
        return ['ref', 'neg']
    if isinstance(tree, list) and tree[0] == 'neg' and isinstance(tree[1], list) and tree[1][:2] == ['^', ARGUMENT]:
        return ['ref', 'power:' + tree[1][2][1]]
    if not isinstance(tree, list) or tree == ARGUMENT or tree[0] == 'number':
        return tree
    return [tree[0], *[_slots(child) for child in tree[1:]]]


def substitution_latex(tree, variable):
    """Every substituted input keeps its own parentheses, as written by hand."""
    names = {'neg': f'(-{variable})'}
    names.update({f'power:{n}': f'(-{variable}^{{{n}}})' for n in map(str, range(2, 10))})
    return expression_latex(_slots(tree), variable, names=names)


def _reflect_view(c):
    ast = c['ast']

    def write(tree):
        if tree[0] == 'neg' and tree[1] == ast:
            return c['fneg'] + '=-(' + c['original'] + ')'
        return c['fneg'] + '=' + substitution_latex(tree, c['variable'])

    right = write(reflect_ast(ast))
    count = _occurrences(ast)
    slips = [(['neg', deepcopy(ast)], rf'代入是把每一处 ${c["variable"]}$ 都换成 $-{c["variable"]}$，不是在整个式子前加负号。'),
             (_power_sign_slip(ast), rf'$\left(-{c["variable"]}\right)$ 要整体乘方：偶数次幂没有负号，奇数次幂才有。'),
             *[(_replace(ast, index, [0]), rf'解析式中每一处 ${c["variable"]}$ 都要换成 $-{c["variable"]}$，不能只换一处。')
               for index in sorted({0, count - 1}) if count > 1],
             (deepcopy(ast), rf'还没有代入：$-{c["variable"]}$ 要替换解析式中的 ${c["variable"]}$。')]
    notes = {}
    for tree, note in slips:
        text = write(tree)
        if text == right or text in notes:
            continue
        # Require an exact counterexample on this function's actual domain.
        # Unknown comparisons and rewrites equal only on a finite domain stay out.
        try:
            comparison = function_cells.compare_on_domain(reflect_ast(ast), tree, c['domain'])
        except (ValueError, KeyError, TypeError, NotImplementedError):
            continue
        if comparison['relation'] == 'different':
            notes[text] = note
    wrong = list(notes)[:3]
    view = choice_card('代入相反数', rf'把 $-{c["variable"]}$ 作为整体代入解析式，$' + c['fneg'] + '$ 应写成什么？',
                       '函数解析式', _definition(c), '代入后的式子', right, wrong, _lines([right]))
    if not wrong:
        view.update(interaction={'type': 'read'}, expected_answer={},
                    question='观察把相反数作为整体代入后的式子。')
        return view
    return _with_feedback(view, notes)


def _relation_view(c, relations, prop):
    row = relations[prop]
    target = c['fx'] if prop == 'even' else '-' + c['fx']
    holds = rf'{c["fneg"]}={target}\ \text{{对定义域内每个}}\ {c["variable"]}\ \text{{成立}}'
    fails = rf'\text{{存在}}\ {c["variable"]}\ \text{{使}}\ {c["fneg"]}\ne {target}'
    if row['status'] == 'proved':
        right, wrong = holds, [fails]
        proof = [rf'{c["fneg"]}={c["substituted"]}={c["simplified"]}={target}']
    else:
        witness = row['witness']
        t = witness['point']
        right, wrong = fails, [holds]
        value, opposite = witness['value'], witness['opposite_value']
        compare = value if prop == 'even' else -value
        proof = [rf'{c["call"](latex(t))}={latex(value)},\ {c["call"](latex(-t))}={latex(opposite)}',
                 rf'{c["call"](latex(-t))}\ne {latex(compare)}']
    title = '核对奇函数的条件' if prop == 'odd' else '核对偶函数的条件'
    view = choice_card(title, rf'化简 ${c["fneg"]}$，它与 ${target}$ 在整个定义域上都相等吗？',
                       '代入后的式子', c['fneg'] + '=' + c['substituted'], f'{PROPERTY[prop]}的条件', right, wrong,
                       _lines(proof))
    return _with_feedback(view, {
        holds: '代入一个具体的数，比较两边的值；只要有一个数不满足，条件就不成立。',
        fails: '化简后两边恒等，定义域内每个数都满足这个关系。'})


def _conclude_view(c, result):
    name = c['fx']
    right = rf'{name}\ \text{{{LABELS[result["classification"]]}}}'
    wrong = [rf'{name}\ \text{{{label}}}' for key, label in LABELS.items() if key != result['classification']]
    if result['domain_symmetry']['status'] == 'refuted':
        basis = [r'D\ \text{不关于原点对称}']
    else:
        basis = []
        for prop, target in (('odd', '-' + name), ('even', name)):
            holds = result[prop]['status'] == 'proved'
            basis.append(rf'{c["fneg"]}={target}' + ('' if holds else r'\ \text{不恒成立}'))
    view = choice_card('得出结论', '根据定义域的对称性和上面两项核对，判断这个函数的奇偶性。',
                       '核对结果', _lines(basis), '奇偶性', right, wrong, _lines([*basis, right]))
    return _with_feedback(view, {w: '回到定义：奇函数要求 $f(-x)=-f(x)$，偶函数要求 $f(-x)=f(x)$，且定义域关于原点对称。'
                                 for w in wrong})


def phase_views(values):
    c = _context(values)
    phase = values.get('phase')
    evidence = decode_value(values['evidence'])
    if phase == 'domain':
        return [_domain_view(c, evidence)]
    if phase == 'reflect':
        return [_reflect_view(c)]
    if phase == 'compare':
        return [_relation_view(c, evidence, 'odd'), _relation_view(c, evidence, 'even')]
    if phase == 'conclude':
        return [_conclude_view(c, evidence)]
    return []


def presentation(values):
    views = phase_views(values)
    view = views[0]
    left, right = view['derivation']['items']
    return {
        'formula_title': view['title'],
        'formula_explanation': '\n\n'.join('$$' + v['proof'] + '$$' for v in views),
        'derivation_caption': view['title'],
        'derivation_left_label': left['label'],
        'derivation_left_math': left['math'],
        'derivation_left_note': '',
        'derivation_right_label': right['label'],
        'derivation_right_math': right['math'],
    }


def compile_parity_cards(seeds, interaction_id):
    from .interaction import NotInteractive

    seed, = seeds
    views = phase_views(decode_value(seed['values']))
    if not views:
        raise NotInteractive('folded')
    parts = []
    for index, view in enumerate(views, 1):
        board = deepcopy(view['derivation'])
        interaction = deepcopy(view['interaction'])
        if interaction['type'] == 'read':
            board = {'caption': view['title'], 'lines': [view['proof']]}
        else:
            board['items'][1]['math'] = None
            interaction['options'].sort(
                key=lambda row: sha256(f'{interaction_id}:{index}:{row["value"]}'.encode()).digest())
        parts.append({
            'id': f'{interaction_id}#{index}',
            'title': view.get('part_title', view['title']),
            'question': view['question'],
            'interaction': interaction,
            'expected_answer': view['expected_answer'],
            'feedback': view['feedback'],
            'submit_label': '继续' if interaction['type'] == 'read' else '确认判断',
            'stem_board': board,
            'completion_board': view['derivation'],
        })
    return {'parts': parts, 'diagnostics': []}
