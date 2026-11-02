"""Concrete input changes and whole-identity checks for assignment lessons."""
import sympy as sp
from sympy.core.function import AppliedUndef

from ..function_assignment import assignment_source, specialized_equations
from .assignment_derivation import verification_rows
from .evaluation_presentation import _choice, _lines
from .math_values import latex
from .range_presentation import _card


def phase_view(values):
    desc, r, phase = (values[key] for key in ('description', 'formula_result', 'phase'))
    s = assignment_source(desc)
    plan, p = r['assignment_plan'], r['expression']
    sub = plan['substitution']
    e = specialized_equations(s, plan)
    variable, f = e['variable'], s.function
    assignment = r',\quad '.join(k+'='+latex(v) for k, v in sub.items())
    original = latex(sp.Eq(s.left, s.right, evaluate=False))
    new = latex(sp.Eq(s.apply(s.left, sub), s.apply(s.right, sub), evaluate=False))
    rule = latex(sp.Eq(f(s.x), p, evaluate=False))
    local_rule = latex(sp.Eq(f(variable), p.subs(s.x, variable), evaluate=False))
    if phase == 'choose':
        target = f(0) if plan['needs_zero'] else f(variable)
        calls = sorted(s.left.atoms(AppliedUndef) | s.right.atoms(AppliedUndef), key=str)
        focus = next((c for c in calls if c != target and s.apply(c, sub) == target), None)
        wrong = [r',\quad '.join(k+'='+latex(v) for k, v in other.items()) for other in s.substitutions
                 if other != sub and (focus is None or s.apply(focus, other) != target)]
        i, expected = _choice(rf'令 ${assignment}$', [rf'令 ${w}$' for w in wrong[:2]])
        question = (rf'要把 ${latex(focus)}$ 变成 ${latex(target)}$，应该怎样代入？' if focus is not None
                    else '哪种代入能得到下面只含一个变量的等式？')
        before = _lines([original, rf'{latex(focus)}\longrightarrow {latex(target)}']) if focus is not None else new
        return _card('选择赋值，消去一个变量', question, '原关系与希望得到的函数值', before,
                     '整条关系同时代入', _lines([assignment, new]),
                     '原题对任意两个实数都成立，所以这个代入合法；等式两边的对应变量都要一起替换。', i, expected)
    if phase == 'special':
        if plan['needs_zero']:
            z = {str(s.x): sp.S.Zero, str(s.y): sp.S.Zero}
            before = latex(sp.Eq(s.apply(s.left, z), s.apply(s.right, z), evaluate=False))
            answer = latex(sp.Eq(f(0), r['zero_value'], evaluate=False))
            i, expected = _choice(rf'${answer}$', [rf'${latex(sp.Eq(f(0), r["zero_value"]+1, evaluate=False))}$'])
            return _card('先求出零对应的函数值', rf'先令 ${latex(s.x)}={latex(s.y)}=0$。由下面等式可得什么？',
                         '两个变量都取零', before, '求出 f(0)', answer,
                         '先算出这个常数，再代回上一步得到的等式，就能继续求解析式。', i, expected)
        i, expected = _choice(rf'${local_rule}$', [rf'${latex(sp.Eq(f(variable), p.subs(s.x, variable)+1, evaluate=False))}$'])
        return _card('整理等式，求出函数值', '把相同的函数值移到同一边，整理后得到什么？',
                     '代入后的等式', new, '整理结果', local_rule,
                     rf'这里的 ${latex(variable)}$ 仍可取任意实数，因此得到的是一整条函数规则。', i, expected)
    if phase == 'isolate':
        if plan['needs_zero']:
            question = rf'把 ${latex(f(0))}={latex(r["zero_value"])}$ 代入，再解出 ${latex(f(s.x))}$。'
            before = _lines([new, rf'{latex(f(0))}={latex(r["zero_value"])}'])
            explanation = '先代入已求出的常数，再合并同类项并除以非零系数。'
        else:
            question = rf'${latex(variable)}$ 可以取任意实数。把变量名改写成 ${latex(s.x)}$，解析式是什么？'
            before = local_rule
            explanation = '变量只是输入的名字；换一个字母，函数的对应规则和取值范围不变。'
        i, expected = _choice(rf'${rule}$', [rf'${latex(sp.Eq(f(s.x), p+1, evaluate=False))}$'])
        return _card('得到任意输入的解析式', question, '已有等式', before, '函数解析式', rule,
                     explanation, i, expected)
    if phase == 'verify':
        rows = verification_rows(s, p)
        expanded = rows[0]['expanded']
        cross_term = sp.Poly(expanded, s.x, s.y).coeff_monomial(s.x*s.y)
        wrong = expanded-cross_term*s.x*s.y if cross_term else expanded+1
        i, expected = _choice(rf'${latex(expanded)}$', [rf'${latex(wrong)}$'])
        question = (rf'左边把 ${latex(s.left.args[0])}$ 作为输入，求 ${latex(s.left)}$；右边也代入已求的解析式。'
                    if isinstance(s.left, AppliedUndef) else '把已求的解析式分别代入原等式两边。')
        card = _card('分别代入，比较等式两边', question+'展开后，两边都等于哪个式子？',
                     '已求解析式与原关系', _lines([rule, original]), '两边展开后都等于', latex(expanded),
                     '两边展开后完全相同，因此对任意两个实数，原等式都成立。', i, expected)
        card['derivation']['comparison_sides'] = [
            {'label': row['label']+' · 代入已求的解析式',
             'math': _lines(row['calls']+([r'\text{'+row['label']+'}='+row['substitution']]
                                         if len(row['calls']) != 1 or row['original']+'='+row['substitution'] != row['calls'][0] else []))}
            for row in rows]
        return card
    if phase == 'answer':
        final = rule+rf',\quad {latex(s.x)}\in\mathbb{{R}}'
        i, expected = _choice(rf'${final}$', [rf'只知道 ${latex(f(0))}={latex(p.subs(s.x,0))}$'])
        return _card('写出完整答案', '结合已经验证的函数规则，应怎样回答原题？',
                     '已验证的解析式', rule, '完整答案', final,
                     '原关系对任意实数成立，代入后的自由变量仍遍历实数，所以最终规则适用于所有实数输入。', i, expected)
    raise ValueError('function_assignment.unknown_phase')
