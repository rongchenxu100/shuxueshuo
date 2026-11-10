"""FM-T1: exact monotonic interval families for bounded elementary functions.

The solver uses quadratic axes, order-preserving roots, reciprocals,
absolute-value branches and explicit piecewise definitions. The verifier
independently checks the polynomial two-point difference on every open cell,
cross-piece image order at junctions, and original values at junctions.
Intervals are lists, never union-normalized answers.
"""
from copy import deepcopy
from itertools import pairwise

import sympy as sp

from ..problem_understanding.notation_parser import NotationError, parse
from .absolute_graph import polynomial_set
from .function_formula import _bounded, _polynomial
from .piecewise_evaluation import ARGUMENT, is_piecewise
from .piecewise_evaluation import branches as piecewise_branches
from .range_syntax import range_domain

KINDS = ('find_monotonic_intervals', 'prove_monotonicity_on_interval')
VERSION = 'function-monotonicity/v1'
PIECEWISE_FAMILIES = ('absolute', 'explicit_piecewise')


def _contains_abs(ast):
    return isinstance(ast, list) and (ast[:2] == ['call', 'abs'] or any(_contains_abs(v) for v in ast[1:]))


def _bind_argument(ast, name):
    if not isinstance(ast, list):
        return ast
    if ast == ['name', name]:
        return ARGUMENT
    return [ast[0], *(_bind_argument(child, name) for child in ast[1:])]


def _unbind_argument(ast, name):
    if not isinstance(ast, list):
        return ast
    if ast == ARGUMENT:
        return ['name', name]
    return [ast[0], *(_unbind_argument(child, name) for child in ast[1:])]


def _poly(ast, variable):
    p = _polynomial(ast, ['name', str(variable)], root_input=False)
    if p.degree() > 2:
        raise ValueError('monotonicity.degree_above_two')
    return sp.Poly(p.as_expr().subs(p.gens[0], variable), variable)


def _absolute_parts(ast, x):
    """Accept only P2 + c |r x+s|, inspecting syntax before cancellation."""
    if not _contains_abs(ast):
        return _poly(ast, x).as_expr(), sp.S.Zero, None
    if ast[:2] == ['call', 'abs'] and len(ast) == 3:
        p = _poly(ast[2], x)
        if p.degree() > 1:
            raise ValueError('monotonicity.affine_absolute_required')
        return sp.S.Zero, sp.S.One, p.as_expr()
    if ast[0] == 'neg':
        p, c, a = _absolute_parts(ast[1], x)
        return -p, -c, a
    if ast[0] in ('+', '-'):
        left, right = (_absolute_parts(v, x) for v in ast[1:])
        if left[2] is not None and right[2] is not None:
            raise ValueError('monotonicity.single_absolute_required')
        sign = 1 if ast[0] == '+' else -1
        return left[0]+sign*right[0], left[1]+sign*right[1], left[2] if left[2] is not None else right[2]
    if ast[0] in ('*', '/'):
        index = 1 if _contains_abs(ast[1]) else 2
        if ast[0] == '/' and index != 1:
            raise ValueError('monotonicity.absolute_denominator_unsupported')
        other = _poly(ast[3-index], x)
        if other.degree() > 0 or ast[0] == '/' and other.nth(0) == 0:
            raise ValueError('monotonicity.constant_absolute_coefficient_required')
        scale = other.nth(0) if ast[0] == '*' else 1/other.nth(0)
        p, c, a = _absolute_parts(ast[index], x)
        return scale*p, scale*c, a
    raise ValueError('monotonicity.absolute_structure_unsupported')


def source(goal):
    ast, var = parse(goal['expression']), parse(goal['variable'])
    if var[0] != 'name':
        raise ValueError('monotonicity.variable_required')
    count = 0

    def budget(node, depth=0):
        nonlocal count
        count += 1
        if count > 128 or depth > 16:
            raise ValueError('monotonicity.expression_budget')
        for child in node[1:]:
            if isinstance(child, list):
                budget(child, depth+1)
    budget(ast)
    x = sp.Symbol(var[1], real=True)
    family, core = 'polynomial', ast
    if is_piecewise(ast):
        family = 'explicit_piecewise'
    elif ast[:2] == ['call', 'sqrt']:
        family, core = 'sqrt', ast[2]
    elif ast[0] == '/' and ast[1] == ['number', '1'] and ast[2][:2] == ['call', 'sqrt']:
        family, core = 'reciprocal_sqrt', ast[2][2]
    elif _contains_abs(ast):
        family = 'absolute'
    piece_rows = []
    if family == 'absolute':
        p, c, arg = _absolute_parts(ast, x)
        for v in (*sp.Poly(p, x).all_coeffs(), c, *sp.Poly(arg, x).all_coeffs()):
            _bounded(v)
        expr = p+c*sp.Abs(arg)
        affine = sp.Poly(arg, x)
        if c == 0 or affine.nth(1) == 0:
            family, q = 'polynomial', sp.Poly(expr, x)
        else:
            zero = _bounded(-affine.nth(0)/affine.nth(1))
            s = sp.sign(affine.nth(1))
            piece_rows = [{'expression': sp.expand(p-s*c*arg), 'domain': sp.Interval.open(-sp.oo, zero)},
                          {'expression': sp.expand(p+s*c*arg), 'domain': sp.Interval(zero, sp.oo)}]
            q = None
    elif family == 'explicit_piecewise':
        rows = piecewise_branches(_bind_argument(ast, var[1]))
        if len(rows) != 2:
            raise ValueError('monotonicity.piecewise_branch_budget')
        rows = sorted(rows, key=lambda row: (row['domain'].inf, row['domain'].sup))
        for row in rows:
            poly = _poly(_unbind_argument(row['expression_ast'], var[1]), x)
            for value in poly.all_coeffs():
                _bounded(value)
            if not isinstance(row['domain'], sp.Interval):
                raise TypeError('monotonicity.piecewise_interval_branch_required')
            for value in (row['domain'].inf, row['domain'].sup):
                if value.is_finite:
                    _bounded(value)
            piece_rows.append({'expression': poly.as_expr(), 'domain': row['domain']})
        expr = sp.Piecewise(*[(row['expression'], row['domain'].as_relational(x)) for row in piece_rows])
        q = None
    else:
        q = _poly(core, x)
        expr = q.as_expr() if family == 'polynomial' else sp.Pow(q.as_expr(), sp.Rational(1, 2), evaluate=False)
        if family == 'reciprocal_sqrt':
            expr = sp.Pow(expr, -1, evaluate=False)
    domain_ast = parse(goal.get('input_domain', 'ℝ'))
    if domain_ast[0] == 'tuple' and len(domain_ast) == 3:
        domain_ast = ['interval', False, False, *domain_ast[1:]]
    domain = range_domain(domain_ast)
    if domain != sp.S.Reals and not isinstance(domain, sp.Interval):
        raise ValueError('monotonicity.single_input_interval_required')
    for value in (domain.inf, domain.sup):
        if value.is_finite:
            _bounded(value)
    if q is not None:
        for value in q.all_coeffs():
            _bounded(value)
        if family != 'polynomial':
            for root in q.real_roots() if q.degree() > 0 else []:
                _bounded(root)
    if goal['kind'] == 'prove_monotonicity_on_interval':
        allowed = family in ('polynomial', 'explicit_piecewise')
        if not allowed or 'input_domain' not in goal or goal['direction'] == 'both':
            raise ValueError('monotonicity.definition_polynomial_interval_required')
    return {'variable': x, 'expression': expr, 'polynomial': q.as_expr() if q is not None else None,
            'family': family, 'input_domain': domain, 'pieces': piece_rows}


def describe(goal, target_ref, entries=()):
    desc = {'source': deepcopy(goal), 'target_ref': target_ref, 'source_refs': [target_ref],
            'given_definitions': [], 'extra_source_refs': [], 'structure_version': VERSION,
            'structure_supported': False, 'reason': ''}
    try:
        if goal['kind'] not in KINDS or goal.get('direction') not in ('increasing', 'decreasing', 'both'):
            raise ValueError('monotonicity.goal_required')
        expected = ['=', ['call', goal.get('function', 'f'), parse(goal['variable'])], parse(goal['expression'])]
        output_alias = ['=', ['name', 'y'], parse(goal['expression'])]
        for row in entries:
            clean = {key: row[key] for key in ('source_ref', 'expression')}
            ast = parse(row['expression'])
            if '/definitions/' in row['source_ref'] and (ast == expected or
                    (goal['variable'] != 'y' and ast == output_alias)):
                desc['given_definitions'].append(clean)
                desc['source_refs'].append(row['source_ref'])
            else:
                desc['extra_source_refs'].append(row['source_ref'])
        if desc['extra_source_refs']:
            raise ValueError('monotonicity.extra_conditions_unsupported')
        spec = source(goal)
        desc['family'] = spec['family']
        desc['structure_supported'] = True
    except (ValueError, NotationError, TypeError, KeyError, sp.PolynomialError) as exc:
        desc['reason'] = getattr(exc, 'code', str(exc))
    return desc


def components(domain):
    if domain == sp.S.Reals:
        return [sp.Interval(-sp.oo, sp.oo)]
    parts = domain.args if isinstance(domain, sp.Union) else [domain]
    return sorted((p for p in parts if isinstance(p, sp.Interval)), key=lambda p: p.inf)


def effective_domain(spec, goal):
    natural = sp.S.Reals
    if spec['family'] == 'explicit_piecewise':
        natural = sp.Union(*(piece['domain'] for piece in spec['pieces']))
    elif spec['family'] in ('sqrt', 'reciprocal_sqrt'):
        natural = polynomial_set(sp.Poly(spec['polynomial'], spec['variable']),
                                 '>' if spec['family'] == 'reciprocal_sqrt' else '>=')
    supplied = spec['input_domain']
    if goal.get('domain_role', 'restriction') == 'declared' and supplied-natural != sp.S.EmptySet:
        raise ValueError('monotonicity.declared_domain_conflict')
    domain = supplied & natural
    if domain == sp.S.EmptySet:
        raise ValueError('monotonicity.empty_effective_domain')
    if not components(domain):
        raise ValueError('monotonicity.no_nondegenerate_interval')
    return natural, domain


def _direction(poly, region):
    a, b = poly.nth(2), poly.nth(1)
    if a == 0:
        return int(sp.sign(b))
    axis = -b/(2*a)
    return int(sp.sign(a)) * (-1 if region.sup <= axis else 1)


def _end_value(expr, point, x):
    poly = sp.Poly(expr, x)
    if point == sp.oo:
        if poly.degree() == 0:
            return poly.nth(0)
        return sp.oo if poly.LC() > 0 else -sp.oo
    if point == -sp.oo:
        if poly.degree() == 0:
            return poly.nth(0)
        sign = sp.sign(poly.LC()) * (1 if poly.degree() % 2 == 0 else -1)
        return sp.oo if sign > 0 else -sp.oo
    return sp.simplify(expr.subs(x, point))


def _mono_image(expr, interval, x, piece_domain=None):
    """Attainable values of a degree-≤2 piece that is mono on ``interval``.

    Partition cells may close a junction for coverage; image order uses the
    original branch domain so an open endpoint is not treated as attained.
    """
    region = interval if piece_domain is None else sp.simplify(interval & piece_domain)
    if region == sp.S.EmptySet or not isinstance(region, sp.Interval):
        return sp.S.EmptySet
    poly = sp.Poly(expr, x)
    direction = 0 if poly.degree() == 0 else _direction(poly, region)
    left = _end_value(expr, region.inf, x)
    right = _end_value(expr, region.sup, x)
    left_open = region.left_open or not region.inf.is_finite
    right_open = region.right_open or not region.sup.is_finite
    if direction >= 0:
        return sp.Interval(left, right, left_open=left_open, right_open=right_open)
    return sp.Interval(right, left, left_open=right_open, right_open=left_open)


def _images_strictly_ordered(earlier, later):
    """True iff every attainable value in ``earlier`` is strictly less than every value in ``later``."""
    if earlier == sp.S.EmptySet or later == sp.S.EmptySet:
        return True
    if earlier.sup < later.inf:
        return True
    if earlier.sup == later.inf:
        return bool(earlier.right_open or later.left_open)
    return False


def _cross_piece_merge_ok(left, right, pieces, x):
    if left['direction'] != right['direction']:
        return False
    if left['branch'] == right['branch']:
        return True
    left_piece, right_piece = pieces[left['branch']], pieces[right['branch']]
    if left['direction'] == 0:
        return sp.simplify(left_piece['expression'] - right_piece['expression']) == 0
    left_image = _mono_image(left_piece['expression'], left['interval'], x, left_piece['domain'])
    right_image = _mono_image(right_piece['expression'], right['interval'], x, right_piece['domain'])
    if left['direction'] == 1:
        return _images_strictly_ordered(left_image, right_image)
    return _images_strictly_ordered(right_image, left_image)


def _merge(rows, direction, pieces=None, x=None):
    out, last = [], None
    for row in rows:
        if row['direction'] != direction:
            continue
        region = row['interval']
        can_touch = out and out[-1].sup == region.inf and (not out[-1].right_open or not region.left_open)
        if can_touch and (pieces is None or _cross_piece_merge_ok(last, row, pieces, x)):
            out[-1] = sp.Interval(out[-1].inf, region.sup, left_open=out[-1].left_open, right_open=region.right_open)
            last = row
        else:
            out.append(region)
            last = row
    return out


def _maximal_intervals(rows, direction, pieces, x, domain, expression, *, explicit=False):
    intervals = _merge(rows, direction, pieces, x)
    if not explicit:
        return intervals
    result = []
    for interval in intervals:
        opened = [interval.left_open, interval.right_open]
        for side, point in enumerate((interval.inf, interval.sup)):
            if not opened[side] or not point.is_finite or point not in domain:
                continue
            # Keep partition ownership unchanged. The value at a junction can
            # come from the other branch, including a jump in the right order.
            edge = next(row for row in rows if row['direction'] == direction
                        and (row['interval'].inf if side == 0 else row['interval'].sup) == point)
            limit = pieces[edge['branch']]['expression'].subs(x, point)
            actual = expression.subs(x, point)
            delta = sp.simplify(actual - limit)
            can_close = (delta == 0 if direction == 0 else
                         bool(direction * delta * (-1 if side == 0 else 1) >= 0))
            if can_close:
                opened[side] = False
        result.append(sp.Interval(interval.inf, interval.sup,
                                  left_open=opened[0], right_open=opened[1]))
    return result


def _junctions(partition, domain, expression, x, pieces):
    rows = []
    for left, right in pairwise(partition):
        t = left['interval'].sup
        if t == right['interval'].inf and t.is_finite:
            merge = (t in domain and left['direction'] == right['direction']
                     and _cross_piece_merge_ok(left, right, pieces, x))
            rows.append({'point': t, 'included': t in domain,
                         'value': sp.simplify(expression.subs(x, t)) if t in domain else None,
                         'merge': merge})
    return rows


def solve(desc, method='structure'):
    if not desc['structure_supported']:
        raise ValueError(desc['reason'])
    goal, spec = desc['source'], source(desc['source'])
    if method == 'definition' and spec['family'] != 'polynomial':
        raise ValueError('monotonicity.definition_polynomial_required')
    if method == 'piecewise' and spec['family'] not in PIECEWISE_FAMILIES:
        raise ValueError('monotonicity.piecewise_family_required')
    natural, domain = effective_domain(spec, goal)
    x = spec['variable']
    pieces = spec['pieces'] or [{'expression': spec['polynomial'], 'domain': sp.S.Reals}]
    partition, branch_models = [], []
    for index, piece in enumerate(pieces):
        p = sp.Poly(piece['expression'], x)
        axis = -p.nth(1)/(2*p.nth(2)) if p.degree() == 2 else None
        branch_models.append({**piece, 'axis': axis, 'coefficients': [p.nth(i) for i in (2, 1, 0)]})
        owned = domain & piece['domain']
        for region in components(owned):
            cuts = [region.inf, *([axis] if axis is not None and region.inf < axis < region.sup else []), region.sup]
            for low, high in pairwise(cuts):
                # Explicit branches keep original endpoint ownership. Absolute pieces are
                # continuous, so ambient-domain closure still yields a valid certificate.
                if spec['family'] == 'explicit_piecewise':
                    left_open, right_open = low not in owned, high not in owned
                else:
                    left_open, right_open = low not in domain, high not in domain
                interval = sp.Interval(low, high, left_open=left_open, right_open=right_open)
                inner = _direction(p, interval)
                layers = []
                direction = inner
                if spec['family'] in ('sqrt', 'reciprocal_sqrt'):
                    layers.append({'operation': 'sqrt', 'input_sign': 'positive' if spec['family'] == 'reciprocal_sqrt' else 'nonnegative',
                                   'before': direction, 'after': direction, 'basis': 'function-monotonicity-operations#roots'})
                if spec['family'] == 'reciprocal_sqrt':
                    layers.append({'operation': 'reciprocal', 'input_sign': 'positive', 'before': direction, 'after': -direction,
                                   'basis': 'function-monotonicity-operations#reciprocal'})
                    direction *= -1
                partition.append({'interval': interval, 'direction': direction, 'inner_direction': inner,
                                  'branch': index, 'layers': layers, 'strict': direction != 0,
                                  'difference_factor': [p.nth(2), p.nth(1)]})
    partition.sort(key=lambda row: row['interval'].inf)
    result = {'kind': goal['kind'], 'target_ref': desc['target_ref'], 'function': goal.get('function', 'f'),
              'variable': x, 'expression': spec['expression'], 'family': spec['family'],
              'natural_domain': natural, 'effective_domain': domain, 'requested_direction': goal['direction'],
              'branches': branch_models, 'partition': partition,
              'method': method,
              'junctions': _junctions(partition, domain, spec['expression'], x, pieces),
              'coverage_and_maximality': True}
    for direction, key in ((1, 'increasing_intervals'), (-1, 'decreasing_intervals'), (0, 'constant_intervals')):
        result[key] = _maximal_intervals(partition, direction, pieces, x, domain, spec['expression'],
                                         explicit=spec['family'] == 'explicit_piecewise')
    if goal['kind'] == 'prove_monotonicity_on_interval':
        direction = 1 if goal['direction'] == 'increasing' else -1
        intervals = result['increasing_intervals' if direction == 1 else 'decreasing_intervals']
        if len(intervals) != 1 or intervals[0] != spec['input_domain']:
            raise ValueError('monotonicity.requested_direction_false')
    return result


def verify(desc, model):
    """Recheck original syntax, exact coverage, strict differences and maximality.

No call to solve; on a quadratic cell the difference quotient is
A(x1+x2)+B. Its extrema and strict interior order certify every pair.
"""
    try:
        if describe(desc['source'], desc['target_ref'], desc['given_definitions']) != desc:
            return False
        spec, g = source(desc['source']), desc['source']
        natural, domain = effective_domain(spec, g)
        for key, expected in {'kind': g['kind'], 'target_ref': desc['target_ref'], 'function': g.get('function', 'f'),
                              'variable': spec['variable'], 'expression': spec['expression'], 'family': spec['family'],
                              'requested_direction': g['direction'], 'effective_domain': domain, 'natural_domain': natural,
                              'coverage_and_maximality': True}.items():
            if model[key] != expected:
                return False
        if model['method'] not in ('structure', 'piecewise', 'definition') or (model['method'] == 'definition' and spec['family'] != 'polynomial'):
            return False
        x, rows = spec['variable'], model['partition']
        source_pieces = spec['pieces'] or [{'expression': spec['polynomial'], 'domain': sp.S.Reals}]
        if len(model['branches']) != len(source_pieces):
            return False
        for branch, original in zip(model['branches'], source_pieces, strict=True):
            p = sp.Poly(original['expression'], x)
            axis = -p.nth(1)/(2*p.nth(2)) if p.degree() == 2 else None
            if branch != {**original, 'axis': axis, 'coefficients': [p.nth(i) for i in (2, 1, 0)]}:
                return False
        covered = sp.S.EmptySet
        last = None
        for row in rows:
            region = row['interval']
            if not isinstance(region, sp.Interval) or region-domain != sp.S.EmptySet:
                return False
            if last is not None and (region.inf < last.inf or region.interior & last.interior != sp.S.EmptySet):
                return False
            last = region
            original = source_pieces[row['branch']]
            if region.interior-original['domain'] != sp.S.EmptySet:
                return False
            p = sp.Poly(original['expression'], x)
            a, b = p.nth(2), p.nth(1)
            # Independently partition the affine difference quotient's sign.
            positive = polynomial_set(sp.Poly(2*a*x+b, x), '>')
            negative = polynomial_set(sp.Poly(2*a*x+b, x), '<')
            inner = 0 if a == b == 0 else 1 if region.interior-positive == sp.S.EmptySet else -1 if region.interior-negative == sp.S.EmptySet else None
            if inner is None or row['inner_direction'] != inner or row['difference_factor'] != [a, b]:
                return False
            layers, direction = [], inner
            if spec['family'] in ('sqrt', 'reciprocal_sqrt'):
                valid = polynomial_set(p, '>' if spec['family'] == 'reciprocal_sqrt' else '>=')
                if region-valid != sp.S.EmptySet:
                    return False
                layers.append({'operation': 'sqrt', 'input_sign': 'positive' if spec['family'] == 'reciprocal_sqrt' else 'nonnegative',
                               'before': direction, 'after': direction, 'basis': 'function-monotonicity-operations#roots'})
            if spec['family'] == 'reciprocal_sqrt':
                layers.append({'operation': 'reciprocal', 'input_sign': 'positive', 'before': direction, 'after': -direction,
                               'basis': 'function-monotonicity-operations#reciprocal'})
                direction *= -1
            if row['layers'] != layers or row['direction'] != direction or row['strict'] != (direction != 0):
                return False
            # Closed ends that this branch owns must match the source expression.
            for t in (region.inf, region.sup):
                owned_here = t in original['domain'] if spec['family'] == 'explicit_piecewise' else True
                if (t.is_finite and t in region and owned_here and spec['family'] in PIECEWISE_FAMILIES
                        and sp.simplify(spec['expression'].subs(x, t)-p.eval(t)) != 0):
                    return False
                if t.is_finite and t in domain and t not in region and owned_here:
                    return False  # legal endpoints retained by this cell must stay closed
            covered |= region
        if covered != domain:
            return False
        for direction, key in ((1, 'increasing_intervals'), (-1, 'decreasing_intervals'), (0, 'constant_intervals')):
            if model[key] != _maximal_intervals(rows, direction, source_pieces, x, domain, spec['expression'],
                                                explicit=spec['family'] == 'explicit_piecewise'):
                return False
        if model['junctions'] != _junctions(rows, domain, spec['expression'], x, source_pieces):
            return False
        if g['kind'] == 'prove_monotonicity_on_interval':
            return model[g['direction']+'_intervals'] == [spec['input_domain']]
        return True
    except (ValueError, TypeError, KeyError, AttributeError, IndexError, NotationError):
        return False
