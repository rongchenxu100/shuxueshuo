"""FM-T1: exact monotonic interval families for bounded elementary functions.

The solver uses quadratic axes, order-preserving roots, reciprocals and
absolute-value branches. The verifier independently checks the polynomial
two-point difference on every open cell and original values at junctions.
Intervals are lists, never union-normalized answers.
"""
from copy import deepcopy
from itertools import pairwise

import sympy as sp

from ..problem_understanding.notation_parser import NotationError, parse
from .absolute_graph import polynomial_set
from .function_formula import _bounded, _polynomial
from .range_syntax import range_domain

KINDS = ('find_monotonic_intervals', 'prove_monotonicity_on_interval')
VERSION = 'function-monotonicity/v1'


def _contains_abs(ast):
    return isinstance(ast, list) and (ast[:2] == ['call', 'abs'] or any(_contains_abs(v) for v in ast[1:]))


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
    if ast[:2] == ['call', 'sqrt']:
        family, core = 'sqrt', ast[2]
    elif ast[0] == '/' and ast[1] == ['number', '1'] and ast[2][:2] == ['call', 'sqrt']:
        family, core = 'reciprocal_sqrt', ast[2][2]
    elif _contains_abs(ast):
        family = 'absolute'
    branches = []
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
            branches = [{'expression': sp.expand(p-s*c*arg), 'domain': sp.Interval.open(-sp.oo, zero)},
                        {'expression': sp.expand(p+s*c*arg), 'domain': sp.Interval(zero, sp.oo)}]
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
    if goal['kind'] == 'prove_monotonicity_on_interval' and (family != 'polynomial' or 'input_domain' not in goal or goal['direction'] == 'both'):
        raise ValueError('monotonicity.definition_polynomial_interval_required')
    return {'variable': x, 'expression': expr, 'polynomial': q.as_expr() if q is not None else None,
            'family': family, 'input_domain': domain, 'pieces': branches}


def describe(goal, target_ref, entries=()):
    desc = {'source': deepcopy(goal), 'target_ref': target_ref, 'source_refs': [target_ref],
            'given_definitions': [], 'extra_source_refs': [], 'structure_version': VERSION,
            'structure_supported': False, 'reason': ''}
    try:
        if goal['kind'] not in KINDS or goal.get('direction') not in ('increasing', 'decreasing', 'both'):
            raise ValueError('monotonicity.goal_required')
        expected = ['=', ['call', goal.get('function', 'f'), parse(goal['variable'])], parse(goal['expression'])]
        for row in entries:
            clean = {key: row[key] for key in ('source_ref', 'expression')}
            if '/definitions/' in row['source_ref'] and parse(row['expression']) == expected:
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
    if spec['family'] in ('sqrt', 'reciprocal_sqrt'):
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


def _merge(rows, direction):
    out = []
    for row in rows:
        if row['direction'] != direction:
            continue
        region = row['interval']
        if out and out[-1].sup == region.inf and (not out[-1].right_open or not region.left_open):
            out[-1] = sp.Interval(out[-1].inf, region.sup, left_open=out[-1].left_open, right_open=region.right_open)
        else:
            out.append(region)
    return out


def solve(desc, method='structure'):
    if not desc['structure_supported']:
        raise ValueError(desc['reason'])
    goal, spec = desc['source'], source(desc['source'])
    if method == 'definition' and spec['family'] != 'polynomial':
        raise ValueError('monotonicity.definition_polynomial_required')
    natural, domain = effective_domain(spec, goal)
    x = spec['variable']
    pieces = spec['pieces'] or [{'expression': spec['polynomial'], 'domain': sp.S.Reals}]
    partition, branch_models = [], []
    for index, piece in enumerate(pieces):
        p = sp.Poly(piece['expression'], x)
        axis = -p.nth(1)/(2*p.nth(2)) if p.degree() == 2 else None
        branch_models.append({**piece, 'axis': axis, 'coefficients': [p.nth(i) for i in (2, 1, 0)]})
        for region in components(domain & piece['domain']):
            cuts = [region.inf, *([axis] if axis is not None and region.inf < axis < region.sup else []), region.sup]
            for low, high in pairwise(cuts):
                interval = sp.Interval(low, high, left_open=low not in domain, right_open=high not in domain)
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
              'increasing_intervals': _merge(partition, 1), 'decreasing_intervals': _merge(partition, -1),
              'constant_intervals': _merge(partition, 0), 'method': method,
              'junctions': [], 'coverage_and_maximality': True}
    for left, right in pairwise(partition):
        t = left['interval'].sup
        if t == right['interval'].inf and t.is_finite:
            result['junctions'].append({'point': t, 'included': t in domain,
                'value': sp.simplify(spec['expression'].subs(x, t)) if t in domain else None,
                'merge': t in domain and left['direction'] == right['direction']})
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
            # All admitted branches are continuous on their source closures.
            for t in (region.inf, region.sup):
                if (t.is_finite and t in region and spec['family'] == 'absolute'
                        and sp.simplify(spec['expression'].subs(x, t)-p.eval(t)) != 0):
                    return False
                if t.is_finite and t in domain and t not in region:
                    return False  # legal endpoints must be retained in canonical certificates
            covered |= region
        if covered != domain:
            return False
        # Check connected runs directly, without trusting the solver's union flag.
        for direction, key in ((1, 'increasing_intervals'), (-1, 'decreasing_intervals'), (0, 'constant_intervals')):
            expected, run = [], None
            for row in rows:
                r = row['interval']
                if row['direction'] != direction:
                    if run is not None:
                        expected.append(run)
                        run = None
                    continue
                if run is not None and run.sup == r.inf and r.inf in domain:
                    run = sp.Interval(run.inf, r.sup, left_open=run.left_open, right_open=r.right_open)
                else:
                    if run is not None:
                        expected.append(run)
                    run = r
            if run is not None:
                expected.append(run)
            if model[key] != expected:
                return False
        junctions = []
        for left, right in pairwise(rows):
            t = left['interval'].sup
            if t == right['interval'].inf and t.is_finite:
                junctions.append({'point': t, 'included': t in domain,
                    'value': sp.simplify(spec['expression'].subs(x, t)) if t in domain else None,
                    'merge': t in domain and left['direction'] == right['direction']})
        if model['junctions'] != junctions:
            return False
        if g['kind'] == 'prove_monotonicity_on_interval':
            return model[g['direction']+'_intervals'] == [spec['input_domain']]
        return True
    except (ValueError, TypeError, KeyError, AttributeError, IndexError, NotationError):
        return False
