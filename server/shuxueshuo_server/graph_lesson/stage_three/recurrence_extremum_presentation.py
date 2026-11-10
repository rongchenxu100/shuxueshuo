"""Student steps for verified shift/scale prefix bounds."""
import sympy as sp

from .evaluation_presentation import _lines
from .extremum_presentation import card
from .math_values import latex


def phase_views(values):
    m, phase = values['extremum_result'], values['phase']
    a, length, scale = (m[k] for k in ('coefficient', 'length', 'scale'))
    origin, bound, n = (m[k] for k in ('origin', 'threshold', 'block'))
    x, p, fn = latex(m['variable']), latex(m['parameter']), m['function']
    t = sp.Symbol('t', real=True)
    base = a*t*(t-length)
    general = rf'{fn}({latex(origin)}+n\cdot {latex(length)}+t)={latex(scale)}^n\cdot {latex(base)}'
    minimum = m['base_minimum']
    block_start = origin+n*length
    if phase == 'prepare':
        view = card('把各段移回已知区间',
                    '向右平移一段乘同一个正数，向左则除以它。整数 n 可以为负，因此也覆盖左侧所有区间。',
                    _lines([rf'{fn}({x}+{latex(length)})={latex(scale)}{fn}({x})',
                            rf'{fn}({latex(origin)}+t)={latex(base)},\quad 0<t\le {latex(length)}']),
                    _lines([general, rf'n\in\mathbb Z,\quad 0<t\le {latex(length)}']),
                    [rf'{fn}({latex(origin)}+n\cdot {latex(length)}+t)={latex(base)}',
                     rf'{fn}({latex(origin)}+n\cdot {latex(length)}+t)={latex(scale)}^n+{latex(base)}'],
                    right_label='任意一段的函数式')
        return [view]
    if phase == 'children':
        square = sp.Add(a*(t-length/2)**2, minimum, evaluate=False)
        return [card('求每一整段的最小值',
                     '先把基准段配方。乘数始终为正，所以每段都在中点取得最小值。',
                     _lines([general, rf'{latex(base)}={latex(square)}']),
                     rf'\min={latex(scale)}^n\cdot\left({latex(minimum)}\right)',
                     ['0', rf'{latex(scale)}^n\cdot {latex(-minimum)}'],
                     right_label='第 n 段的最小值')]
    if phase == 'operations':
        previous, current = minimum*scale**(n-1), minimum*scale**n
        view = card('找到第一次低于下界的一段',
                    '整段最小值随 n 增大而变小。只要上一整段仍满足下界，就能同时保证它前面的所有整段。',
                    _lines([rf'\min_n={latex(minimum)}\cdot {latex(scale)}^n',
                            rf'{fn}({x})\ge {latex(bound)}']),
                    _lines([rf'n={n}', rf'\min_{{{n-1}}}={latex(previous)}\ge {latex(bound)}',
                            rf'\min_{{{n}}}={latex(current)}<{latex(bound)}']),
                    [rf'n={n-1}', rf'n={n+1}'], right_label='首次出现不满足下界的位置')
        view['full_derivation'] = [
            rf'{latex(scale)}>1,\quad {latex(minimum)}<0',
            rf'j<{n}\Rightarrow {latex(minimum)}\cdot {latex(scale)}^j\ge {latex(previous)}\ge {latex(bound)}',
            rf'\text{{此前所有整段均满足下界；只需研究 }}({latex(block_start)},{latex(block_start+length)}]']
        return [view]
    if phase == 'conclude':
        scaled = sp.expand(scale**n*base)
        second = sp.simplify(block_start+length-m['offset'])
        first = card('在下降的一侧找到边界',
                     '这一段从左端向中点递减。先求第一次碰到下界的位置；超过它后，会出现小于下界的函数值。',
                     _lines([rf'{latex(scaled)}={latex(bound)}', rf'0<t<{latex(length/2)}']),
                     _lines([rf't={latex(m["offset"])}', rf'{x}={latex(block_start)}+t={latex(m["value"])}']),
                     [rf'{x}={latex(second)}', rf'{x}={latex(block_start+length/2)}'],
                     right_label='第一次到达下界')
        last = card('写出右端点的最大值',
                    '边界处恰好等于下界，可以取到；任何更大的右端点都会包含不满足条件的点。',
                    _lines([rf'\forall {x}\le {p},\quad {fn}({x})\ge {latex(bound)}',
                            rf'{fn}({latex(m["value"])})={latex(bound)}']),
                    rf'{p}_{{\max}}={latex(m["value"])}',
                    [rf'{p}_{{\max}}={latex(bound)}', rf'{p}_{{\max}}={latex(second)}'],
                    right_label='右端点的最大值')
        return [first, last]
    return []
