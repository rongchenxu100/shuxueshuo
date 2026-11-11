"""FP-T4 R3: the sign route for an abstract f (A19).

A strict direction on a one-sided interval I and one zero f(z)=0 with z ∈ I give
the sign of f on I; parity carries it to −I (odd flips, even keeps). The asked
relation f(u)/q □ 0, f(u)·q □ 0 or f(u) □ 0 is then read cell by cell from the
sign of f(u) and of the polynomial q. Nothing is said about f across 0: an
unprinted domain leaves 0 ∈ D open, and an even f leaves f(0) free; every such
case is solved and the answer must not depend on it, else this is a gap.
"""
from copy import deepcopy

import sympy as sp

from . import parity_order_math as order
from . import parity_inequality_inputs as algebra
from .parity_extension_math import reflect

VERSION = 'parity-inequality/r3-sign-v1'
OPS = order.OPS
FLIP = order.FLIP
SIGNS = {'odd': -1, 'even': 1}
MODEL_KEYS = {'version', 'description', 'variable', 'operator', 'input', 'factor', 'certificate', 'cases',
              'solution', 'status', 'borrow'}


def _zero_value(ast, function):
    """f(c) = 0 with a constant c; None when the fact has another shape."""
    if not isinstance(ast, list) or ast[0] != '=':
        return None
    call, other = (ast[1], ast[2]) if ast[1][:1] == ['function_call'] else (ast[2], ast[1])
    if call[:1] != ['function_call'] or order._name(call[1]) != function or other != ['number', '0']:
        return None
    if order._scalars(call[2]) or order._calls(call[2]):
        raise ValueError('parity_ineq.zero_point_not_constant')
    return deepcopy(call[2])


def _expression(ast, function):
    """f(u)/q, f(u)·q or f(u); returns (input, factor, kind)."""
    if ast[:1] == ['function_call']:
        if order._name(ast[1]) != function:
            raise ValueError('parity_ineq.other_function')
        return ast[2], None, None
    if ast[:1] == ['/'] and ast[1][:1] == ['function_call'] and not order._calls(ast[2]):
        return _expression(ast[1], function)[0], ast[2], 'quotient'
    if ast[:1] == ['*'] and len(ast) == 3:
        calls = [i for i in (1, 2) if ast[i][:1] == ['function_call']]
        if len(calls) == 1 and not order._calls(ast[3 - calls[0]]):
            return _expression(ast[calls[0]], function)[0], ast[3 - calls[0]], 'product'
    raise ValueError('parity_ineq.sign_form_unsupported')


def relation(ast, function):
    """E □ 0 with E one of the sign forms; the constant side must be 0."""
    if not isinstance(ast, list) or ast[0] not in OPS:
        raise ValueError('parity_ineq.single_inequality_required')
    if ast[2] == ['number', '0']:
        op, side = ast[0], ast[1]
    elif ast[1] == ['number', '0']:
        op, side = FLIP[ast[0]], ast[2]
    else:
        raise ValueError('parity_ineq.sign_form_unsupported')
    u, q, kind = _expression(side, function)
    return op, u, q, kind


def is_sign_shaped(entries, function):
    """A sign question owns this route; a redundant zero never steals a comparison."""
    for row in entries:
        ast = row['ast']
        if isinstance(ast, list) and ast[0] in OPS and order._calls(ast):
            try:
                relation(ast, function)
            except ValueError:
                continue
            if any(_zero_value(r['ast'], function) is not None for r in entries):
                return True
            if any(side[:1] in (['/'], ['*']) and order._calls(side) for side in ast[1:3]):
                return True
    return False


def factor_of(desc, x):
    if desc['factor_ast'] is None:
        return sp.S.One
    q = order.read_input(order._bound(desc['factor_ast'], desc['variable']), x)
    if q == 0 and desc['factor_kind'] == 'quotient':
        raise ValueError('parity_ineq.zero_factor')
    return q


def input_of(desc, x):
    return order.read_input(order._bound(desc['input_ast'], desc['variable']), x)


def _sgn(v):
    v = sp.nsimplify(v)
    return 0 if v == 0 else (1 if v > 0 else -1)


def certificate(desc):
    """Sign of f on I from the strict direction and the one zero there; the mirrored part by parity."""
    source = desc['direction_source']
    interval = order.interval_of(source)
    side = order._side(interval)
    if side == 0:
        raise ValueError('parity_ineq.sign_interval_not_one_side')
    x = sp.Symbol(desc['variable'], real=True)
    printed = [order.read_input(z, x) for z in desc['zero_asts']]
    if any(p.free_symbols for p in printed):
        raise ValueError('parity_ineq.zero_point_not_constant')
    if desc['domain_ast'] is not None:
        domain = order._read_region(desc['domain_ast'])
        if any(domain.contains(p) is not sp.true for p in printed):
            raise ValueError('parity_ineq.zero_outside_domain')
    candidates = {p for p in printed if interval.contains(p) is sp.true}
    candidates |= {-p for p in printed if interval.contains(-p) is sp.true}
    if desc['property'] == 'odd' and interval.contains(0) is sp.true:
        candidates.add(sp.S.Zero)
    if len(candidates) > 1:
        raise ValueError('parity_ineq.zero_conflict')
    if not candidates:
        raise ValueError('parity_ineq.sign_zero_unknown')
    zero, = candidates
    increasing = source['direction'] == 'increasing'
    below, above = (-1, 1) if increasing else (1, -1)
    known = [(interval & sp.Interval.open(-sp.oo, zero), below), (sp.FiniteSet(zero), 0),
             (interval & sp.Interval.open(zero, sp.oo), above)]
    known = [(s, v) for s, v in known if s != sp.S.EmptySet]
    parity = SIGNS[desc['property']]
    mirrored = []
    for s, v in known:
        part = reflect(s) - interval
        if part != sp.S.EmptySet:
            mirrored.append((part, parity * v))
    origin = None
    if sp.S.Zero in printed and (interval | reflect(interval)).contains(0) is not sp.true:
        origin = 'printed_zero'
    return {'interval': interval, 'direction': source['direction'], 'zero': zero, 'printed_zeros': printed,
            'known': known, 'mirrored': mirrored, 'origin': origin}


def domain_cases(desc, cert):
    """[(D, f(0) sign or None)]: the printed D, or both D the facts leave possible."""
    covered = cert['interval'] | reflect(cert['interval'])
    for p in cert['printed_zeros']:
        if not (covered | sp.FiniteSet(0)).contains(p):
            raise ValueError('parity_ineq.zero_outside_domain')
    if desc['domain_ast'] is not None:
        domain = order._read_region(desc['domain_ast'])
        if reflect(domain) != domain:
            raise ValueError('parity_ineq.domain_not_symmetric')
        if not cert['interval'].is_subset(domain):
            raise ValueError('parity_ineq.monotonic_interval_outside_domain')
        if (domain - covered) - sp.FiniteSet(0) != sp.S.EmptySet:
            raise ValueError('parity_ineq.direction_not_covering_domain')
        domains, identity = [domain], 'explicit'
    else:
        if (sp.S.Reals - covered) - sp.FiniteSet(0) != sp.S.EmptySet:
            raise ValueError('parity_ineq.domain_required')
        if covered.contains(0) is sp.true or cert['origin'] == 'printed_zero':
            domains, identity = [sp.S.Reals], 'from_facts'
        else:
            domains, identity = [sp.S.Reals - sp.FiniteSet(0), sp.S.Reals], 'zero_membership_open'
    cases = []
    for domain in domains:
        if domain.contains(0) is not sp.true or covered.contains(0) is sp.true:
            cases.append((domain, None))
        elif desc['property'] == 'odd' or cert['origin'] == 'printed_zero':
            cases.append((domain, 0))
        else:
            cases.extend((domain, v) for v in (-1, 0, 1))
    return cases, identity


def sign_cells(cert, zero_sign):
    cells = [*cert['known'], *cert['mirrored']]
    if zero_sign is not None:
        cells.append((sp.FiniteSet(0), zero_sign))
    return cells


def preimage(u, x, part):
    return algebra.preimage(u, x, part)


def factor_sets(q, x, kind):
    """{sign of q: x where q has it}; a quotient never takes q = 0."""
    if kind is None:
        return {1: sp.S.Reals}
    sets = {1: algebra.condition(q, '>', x), -1: algebra.condition(q, '<', x)}
    if kind == 'product':
        sets[0] = algebra.condition(q, '=', x)
    return sets


def solve_case(op, u, q, kind, x, cells):
    qs = factor_sets(q, x, kind)
    legal = sp.Union(*(preimage(u, x, part) for part, _ in cells))
    if kind == 'quotient':
        legal &= algebra.preimage(q, x, sp.S.Reals) - algebra.condition(q, '=', x)
    pieces = []
    for part, s in cells:
        for t, where in qs.items():
            if bool(OPS[op](s * t, 0)):
                pieces.append(preimage(u, x, part) & where)
    return sp.simplify(legal), sp.simplify(sp.Union(*pieces) & legal) if pieces else sp.S.EmptySet


def input_asts(desc):
    return [order._bound(a, desc['variable']) for a in (desc['input_ast'], desc['factor_ast']) if a is not None]


def solve_description_case(desc, u, q, x, cells):
    allowed = algebra.allowed(desc, input_asts(desc), x)
    legal, solution = solve_case(desc['operator'], u, q, desc['factor_kind'], x, cells)
    return legal & allowed, solution & allowed


def _same(a, b):
    return (a - b) == sp.S.EmptySet and (b - a) == sp.S.EmptySet


def solve(desc):
    if not desc.get('structure_supported'):
        raise ValueError(desc.get('reason') or 'parity_ineq.unsupported')
    return _solve(desc)


def _solve(desc):
    x = sp.Symbol(desc['variable'], real=True)
    cert = certificate(desc)
    u, q = input_of(desc, x), factor_of(desc, x)
    cases, identity = domain_cases(desc, cert)
    rows = []
    for domain, zero_sign in cases:
        legal, solution = solve_description_case(desc, u, q, x, sign_cells(cert, zero_sign))
        rows.append({'domain': domain, 'zero_sign': zero_sign, 'legal_set': legal, 'solution': solution})
    if any(not _same(r['solution'], rows[0]['solution']) for r in rows[1:]):
        raise ValueError('parity_ineq.zero_value_unknown' if any(r['zero_sign'] not in (None, 0) for r in rows)
                         else 'parity_ineq.domain_dependent_answer')
    cert['domain_identity'] = identity
    return {'version': VERSION, 'description': deepcopy(desc), 'variable': x, 'operator': desc['operator'],
            'input': u, 'factor': q, 'certificate': cert, 'cases': rows, 'solution': rows[0]['solution'],
            'status': 'determined', 'borrow': None}


def describe(goal, target_ref, entries, desc):
    """Printed one-sided direction, printed zero(s) and E □ 0 as facts."""
    mono = goal['function_monotonicity']
    function, variable = mono.get('function'), goal.get('symbol')
    parity = [r for r in entries if r['ast'][0] == 'function_parity' and order._name(r['ast'][1]) == function]
    if len(parity) != 1 or not is_sign_shaped(entries, function):
        return None
    try:
        if mono.get('strict') is not True:
            raise ValueError('parity_ineq.strict_required')
        if mono.get('direction') not in order.DIRECTIONS:
            raise ValueError('parity_ineq.direction_required')
        zeros = [(r, _zero_value(r['ast'], function)) for r in entries]
        zeros = [(r, z) for r, z in zeros if z is not None]
        rows = [r for r in entries if isinstance(r['ast'], list) and r['ast'][0] in OPS and order._calls(r['ast'])]
        domains = order._domain_rows(entries, function)
        used = {parity[0]['source_ref'], *(r['source_ref'] for r, _ in zeros), *(r['source_ref'] for r in rows),
                *(r['source_ref'] for r in domains),
                *(r['source_ref'] for r in algebra.constraint_rows(entries, variable))}
        if any(r['source_ref'] not in used for r in entries):
            raise ValueError('parity_ineq.unprocessed_fact')
        if len(rows) != 1:
            raise ValueError('parity_ineq.single_inequality_required')
        row, = rows
        op, u, q, kind = relation(row['ast'], function)
        if any(order._scalars(r['ast'][2]) for r in domains):
            raise ValueError('parity_ineq.parameter_unsupported')
        stated = mono.get('function_domain')
        asts = [r['ast'][2] for r in domains] + ([order.base_parse(stated)] if stated else [])
        if asts and not order._same_domain(asts, None):
            raise ValueError('parity_ineq.conflicting_function_domain')
        desc.update(function=function, variable=variable, property=parity[0]['ast'][2], operator=op,
                    input_ast=deepcopy(u), factor_ast=deepcopy(q), factor_kind=kind,
                    relation_ast=deepcopy(row['ast']), relation_source_ref=row['source_ref'],
                    parity_source_ref=parity[0]['source_ref'],
                    zero_asts=[deepcopy(z) for _, z in zeros], zero_source_refs=[r['source_ref'] for r, _ in zeros],
                    domain_ast=deepcopy(asts[0]) if asts else None, domain_text=None,
                    domain_source_refs=([r['source_ref'] for r in domains]
                                        or ([target_ref + '/function_monotonicity/function_domain'] if stated else [])),
                    direction_source={'kind': 'given', 'interval': mono['domain'],
                                      'interval_ast': order.base_parse(mono['domain']),
                                      'direction': mono['direction'], 'basis': order._basis(mono),
                                      'source_ref': target_ref + '/function_monotonicity'},
                    parameter=None)
        for part in (u, q):
            if part is not None:
                order._bound(part, variable)
        _solve(desc)
        desc['structure_supported'] = True
    except (ValueError, TypeError, KeyError, IndexError, NotImplementedError, sp.PolynomialError) as exc:
        desc['reason'] = str(exc)
    return desc


def _value_sign(t, interval, zero, increasing, parity, zero_sign):
    """Pointwise sign of f(t) straight from the facts; None outside every proved place."""
    if interval.contains(t) is sp.true:
        d = _sgn(t - zero)
        return d if increasing else -d
    if interval.contains(-t) is sp.true:
        d = _sgn(-t - zero)
        return parity * (d if increasing else -d)
    if t == 0:
        return zero_sign
    return None


def verify(desc, model):
    """Rebuild the zero and every case from the source facts, then read each cell between cut points."""
    try:
        if not desc.get('structure_supported') or model.get('description') != desc:
            return False
        if set(model) != MODEL_KEYS or model['version'] != VERSION or model['status'] != 'determined':
            return False
        if model.get('borrow') is not None:
            return False
        x = sp.Symbol(desc['variable'], real=True)
        u, q = input_of(desc, x), factor_of(desc, x)
        if (model['variable'] != x or model['operator'] != desc['operator'] or sp.expand(model['input'] - u) != 0
                or sp.expand(model['factor'] - q) != 0):
            return False
        source = desc['direction_source']
        interval = order.interval_of(source)
        cert = model['certificate']
        if cert['interval'] != interval or cert['direction'] != source['direction']:
            return False
        zero = cert['zero']
        if interval.contains(zero) is not sp.true:
            return False
        printed = [order.read_input(z, x) for z in desc['zero_asts']]
        zero_ok = (zero in printed or -zero in printed
                   or (zero == 0 and desc['property'] == 'odd'))
        if not zero_ok:
            return False
        others = {p for p in printed if interval.contains(p) is sp.true} | \
                 {-p for p in printed if interval.contains(-p) is sp.true}
        if others - {zero}:
            return False
        covered = interval | reflect(interval)
        origin = 'printed_zero' if sp.S.Zero in printed and covered.contains(0) is not sp.true else None
        if cert['origin'] != origin:
            return False
        cases, identity = domain_cases(desc, {**cert, 'printed_zeros': printed})
        if cert['domain_identity'] != identity or len(model['cases']) != len(cases):
            return False
        increasing, parity = source['direction'] == 'increasing', SIGNS[desc['property']]
        kind, op = desc['factor_kind'], desc['operator']
        cut = {zero, -zero, sp.S.Zero, *(p for p in interval.boundary if p.is_finite)}
        asts = input_asts(desc)
        allowed = algebra.allowed(desc, asts, x)
        points = algebra.source_points(asts) | set(allowed.boundary) | set(algebra.cut_points(u, x))
        for t in cut | {-p for p in cut}:
            points |= set(algebra.cut_points(u - t, x))
        if kind is not None:
            points |= set(algebra.cut_points(q, x))
        expected_known = [(interval & sp.Interval.open(-sp.oo, zero), -1 if increasing else 1),
                          (sp.FiniteSet(zero), 0),
                          (interval & sp.Interval.open(zero, sp.oo), 1 if increasing else -1)]
        expected_known = [(p, v) for p, v in expected_known if p != sp.S.EmptySet]
        expected_mirrored = [(reflect(p) - interval, parity * v) for p, v in expected_known
                             if reflect(p) - interval != sp.S.EmptySet]
        if ([tuple(r) for r in cert['known']] != expected_known
                or [tuple(r) for r in cert['mirrored']] != expected_mirrored or cert['printed_zeros'] != printed):
            return False
        for (domain, zero_sign), row in zip(cases, model['cases']):
            if not _same(row['domain'], domain) or row['zero_sign'] != zero_sign:
                return False
            if not _same(row['solution'], model['solution']):
                return False
            extra = set().union(*(algebra.cut_points(u-p, x) for p in domain.boundary if p.is_finite))
            for cell, rep in order._cells(points | extra, None):
                t = sp.expand(u.subs(x, rep))
                qv = q.subs(x, rep)
                from .function_cells import evaluate
                inside = (allowed.contains(rep) is sp.true and all(evaluate(a, rep)[0] for a in asts)
                          and domain.contains(t) is sp.true and not (kind == 'quotient' and qv == 0))
                truth = False
                if inside:
                    s = _value_sign(t, interval, zero, increasing, parity, zero_sign)
                    if s is None:
                        return False
                    truth = bool(OPS[op](s * (_sgn(qv) if kind else 1), 0))
                for claimed, value in ((row['legal_set'], inside), (row['solution'], truth)):
                    if value and not cell.is_subset(claimed):
                        return False
                    if not value and (cell & claimed) != sp.S.EmptySet:
                        return False
        return True
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, NotImplementedError, sp.PolynomialError):
        return False
