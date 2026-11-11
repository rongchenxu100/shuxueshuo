"""FP-T2 R2: original rational guards and fixed mirrored branches.

Parameter cells include all endpoint crossings and every parameter-only divisor
zero. Input cells include branch boundaries, absolute-value zeros and original
holes. Identities on open cells are polynomial identities, never sample tests.
"""
from copy import deepcopy
from itertools import combinations, pairwise

import sympy as sp

from . import function_cells as fixed
from . import parameter_domain as domains
from . import parity_parameter_math as base

VERSION = 'parity-parameter/r2-original-v1'
QUARTIC_VERSION = 'parity-parameter/r2-quartic-v1'
R2_LIMITS = {'input_degree': 4, 'coefficient_degree': 2, 'normal_degree': 8,
             'condition_degree': 4, 'branches': 6, 'moving_holes': 2}


def needs_extension(ast, ref, entries=()):
    if any(n[0] == '^' and n[2] == ['number', '0'] for n in fixed.walk(ast)):
        return True
    x, p = sp.symbols('_x _p', real=True)
    for row in entries:
        node = row['ast']
        if (node[0] == '=' and any(v[:2] == ['call', 'degree'] for v in node[1:])
                and any(v in (['number', '3'], ['number', '4']) for v in node[1:])):
            return True
        if node[0] in ('=', '!=', '<', '<=', '>', '>=', 'and', 'or', '∈', '∉'):
            refs = {n[1] for n in fixed.walk(node) if n[0] == 'ref'}
            if refs == {ref}:
                try:
                    base._constraint(node, x, p, ref)
                    if any(n[0] == '^' and n[2] == ['number', '0'] for n in fixed.walk(node)):
                        return True
                except ValueError:
                    return True
    try:
        value = base.polynomial(ast, x, p, ref)
        return sp.Poly(value, x).degree() > 2
    except ValueError:
        return True


def populate(desc, entries, facts, definitions, function_ref):
    from .parity_parameter_domain import populate as populate_domain
    populate_domain(desc, entries, facts, definitions, function_ref,
                    source_reader=lambda d: None, maximum_degree=4)
    desc.update(analysis_mode='original', structure_version=VERSION,
                domain_role='declared' if any(r['ast'][0] == '=' and
                    ['call', 'Dom', ['ref', function_ref, 'function']] in r['ast'][1:] for r in entries) else 'natural')
    if desc['local_rules']:
        raise ValueError('parity_param.r2_complete_formula_required')
    try:
        x, p = symbols(desc)
        poly = base.polynomial(desc['expression_ast'], x, p, desc['parameter_ref'], maximum=4)
    except ValueError:
        poly = None
    if (poly is not None and desc['domain_ast'] == ['real'] and not desc['defined_regions']
            and not any(n[0] == '^' and n[2] == ['number', '0'] for n in fixed.walk(desc['expression_ast']))):
        desc.update(analysis_mode='quartic', structure_version=QUARTIC_VERSION)
        base.source(desc)
    else:
        source(desc)  # Admission parses bounded structure, without solving parity.


def symbols(desc):
    p = sp.Symbol(desc['parameter'], real=True)
    x = sp.Symbol(desc['variable'] if desc['variable'] != desc['parameter'] else '_function_input', real=True)
    return x, p


def checked_poly(value, x, p, *, degree=8):
    poly = sp.Poly(sp.expand(value), x, p)
    if poly.degree(x) > degree or poly.degree(p) > degree or len(poly.terms()) > 128:
        raise ValueError('parity_param.r2_normal_degree_budget')
    for c in poly.coeffs():
        if not c.is_Rational or max(abs(int(c.p)).bit_length(), int(c.q).bit_length()) > base.LIMITS['bits']:
            raise ValueError('parity_param.r2_coefficient_budget')
    return poly.as_expr()


def fraction(ast, x, p, ref):
    """Read numerator/denominator separately; preserve guards before cancelling."""
    op = ast[0]
    if op in ('number', 'ref', 'bound'):
        return base.polynomial(ast, x, p, ref, maximum=4), sp.S.One, []
    if op == 'neg':
        n, d, g = fraction(ast[1], x, p, ref)
        return -n, d, g
    if op not in ('+', '-', '*', '/', '^'):
        raise ValueError('parity_param.r2_rational_syntax_required')
    a, b, guards = fraction(ast[1], x, p, ref)
    c, d, other = fraction(ast[2], x, p, ref)
    guards += other
    if op == '^':
        if d != 1 or not c.is_Integer or not 0 <= c <= 4:
            raise ValueError('parity_param.r2_power_budget')
        if c == 0:
            guards.append(a)  # The shared real-function convention excludes 0^0.
        n, den = a**c, b**c
    elif op == '/':
        guards.append(c)
        n, den = a*d, b*c
    else:
        n, den = {'+': lambda: (a*d+c*b, b*d), '-': lambda: (a*d-c*b, b*d),
                  '*': lambda: (a*c, b*d)}[op]()
    return checked_poly(n, x, p), checked_poly(den, x, p), guards


def roots(expr, p):
    """All real roots, with factor coverage and the supported algebraic degree."""
    poly = sp.Poly(expr, p, extension=True)
    if poly.is_zero or poly.degree() <= 0:
        return []
    if poly.degree() > R2_LIMITS['condition_degree']:
        raise ValueError('parity_param.r2_parameter_degree_budget')
    points = []
    # Factorisation is exact; quadratic factors use a closed formula. A quartic
    # with higher-degree real roots is a capability gap, never an empty set.
    coefficient, factors = sp.factor_list(poly)
    if sp.expand(coefficient * sp.prod(f.as_expr()**n for f, n in factors)-poly.as_expr()) != 0:
        raise ValueError('parity_param.r2_factor_coverage')
    for f, _ in factors:
        if f.degree() <= 2:
            values = base._roots(f.as_expr(), p)
        elif f.domain.is_QQ or f.domain.is_ZZ:
            values = f.real_roots()
        else:
            raise ValueError('parity_param.r2_algebraic_roots_unsupported')
        points.extend(fixed.exact_point(sp.simplify(v)) for v in values)
    return sorted(set(points))


def cell_set(conditions, p):
    """Independent complete sign-cell verification, including divisor poles."""
    from .stage_three.verification import _rational_between
    expressions = [e for c in conditions for e in base._relations(c)]
    cuts = sorted({r for e in expressions for part in sp.cancel(e).as_numer_denom() for r in roots(part, p)})
    if len(cuts) > base.LIMITS['cuts']:
        raise ValueError('parity_param.parameter_cell_budget')
    cells = [sp.FiniteSet(r) for r in cuts]
    cells += [sp.Interval.open(a, b) for a, b in pairwise([-sp.oo, *cuts, sp.oo])]
    kept = []
    for cell in cells:
        sample = next(iter(cell)) if isinstance(cell, sp.FiniteSet) else _rational_between(cell.inf, cell.sup)
        if all(sp.simplify(c.subs(p, sample)) is sp.true for c in conditions):
            kept.append(cell)
    return sp.Union(*kept)


def conditions(desc):
    x, p = symbols(desc)
    def read(ast):
        if ast[0] in ('and', 'or'):
            return {'and': sp.And, 'or': sp.Or}[ast[0]](*(read(v) for v in ast[1:]))
        if ast[0] in ('∈', '∉'):
            return base._constraint(ast, x, p, desc['parameter_ref'])
        if ast[0] not in ('=', '!=', '>', '>=', '<', '<='):
            raise ValueError('parity_param.r2_parameter_condition_required')
        n, d, guards = fraction(['-', *ast[1:]], x, p, desc['parameter_ref'])
        if any(v.has(x) for v in [n, d, *guards]):
            raise ValueError('parity_param.r2_parameter_condition_required')
        if d == 0 or any(v == 0 for v in guards):
            return sp.false
        for v in (n, d, *guards):
            roots(v, p)
        relation = {'=': sp.Eq, '!=': sp.Ne, '>': sp.Gt, '>=': sp.Ge, '<': sp.Lt, '<=': sp.Le}[ast[0]]
        return sp.And(relation(n/d, 0), *(sp.Ne(g, 0) for g in guards))
    return [read(r['ast']) for r in desc['constraints']]


def guard_parts(guard, x, p):
    """Factor an original divisor into parameter guards and fixed/affine holes."""
    if guard == 0:
        return [], [sp.S.Zero]
    coefficient, factors = sp.factor_list(guard, x, p)
    holes, parameter_guards, moving = [], [], 0
    for factor, _ in [(coefficient, 1), *factors]:
        poly = sp.Poly(factor, x)
        if poly.degree() <= 0:
            if factor != 1:
                roots(factor, p)
                parameter_guards.append(factor)
        elif not factor.has(p):
            if poly.degree() > 4:
                raise ValueError('parity_param.r2_fixed_divisor_degree')
            holes.extend(fixed.roots(poly))
        else:
            moving += 1
            if poly.degree() != 1 or poly.nth(1).has(p):
                raise ValueError('parity_param.r2_affine_holes_required')
            hole = sp.cancel(-poly.nth(0)/poly.nth(1))
            if sp.Poly(hole, p).degree() > 1:
                raise ValueError('parity_param.r2_affine_holes_required')
            holes.append(hole)
    if moving > R2_LIMITS['moving_holes']:
        raise ValueError('parity_param.r2_moving_hole_budget')
    return holes, parameter_guards


def _resolve_abs(ast, sample):
    if ast[:2] == ['call', 'abs']:
        poly = fixed.polynomial(ast[2], 2)
        sign = 1 if poly.eval(sample) >= 0 else -1
        return ast[2] if sign > 0 else ['neg', ast[2]]
    return [_resolve_abs(v, sample) if isinstance(v, list) else v for v in ast]


def source(desc):
    x, p = symbols(desc)
    ast = desc['expression_ast']
    base._budget(ast)
    if ast[:2] == ['call', 'sqrt']:
        from .parity_parameter_radical import source as radical_source
        return radical_source(desc)
    if any(n[:2] == ['call', 'sqrt'] for n in fixed.walk(ast)):
        raise ValueError('parity_param.r2_even_quadratic_radical_required')
    branches = fixed.branches(ast) if ast[:2] == ['call', 'piecewise'] else [(ast, sp.S.Reals)]
    fixed_cuts = {sp.S.Zero}
    for body, region in branches:
        fixed_cuts.update(fixed.boundaries(region))
        for n in fixed.walk(body):
            if n[:2] == ['call', 'piecewise']:
                raise ValueError('parity_param.r2_nested_piecewise_unsupported')
            if n[:2] == ['call', 'abs']:
                fixed_cuts.update(fixed.roots(fixed.polynomial(n[2], 2)))
    parts = []
    for cell, sample in fixed.cells(sp.S.Reals, fixed_cuts):
        active = [(body, domain) for body, domain in branches if cell-domain == sp.S.EmptySet]
        if not active:
            continue
        body, _ = active[0]
        n, d, guards = fraction(_resolve_abs(body, sample), x, p, desc['parameter_ref'])
        holes, parameter_guards = [], []
        for g in guards:
            h, pg = guard_parts(g, x, p)
            holes.extend(h); parameter_guards.extend(pg)
        if len({h for h in holes if h.has(p)}) > R2_LIMITS['moving_holes']:
            raise ValueError('parity_param.r2_moving_hole_budget')
        if max(sp.Poly(n, x).degree(), sp.Poly(d, x).degree()) > 4:
            raise ValueError('parity_param.r2_input_degree_budget')
        if any(sp.Poly(c, p).degree() > 2 for c in sp.Poly(n, x).all_coeffs()):
            raise ValueError('parity_param.r2_coefficient_degree_budget')
        parts.append({'scope': cell, 'numerator': n, 'denominator': d, 'guards': guards,
                      'holes': holes, 'parameter_guards': parameter_guards})
    if desc['degrees'] and (ast[:2] == ['call', 'piecewise'] or any(v['guards'] for v in parts)
                           or any(n[:2] == ['call', 'abs'] for n in fixed.walk(ast))):
        raise ValueError('parity_param.r2_polynomial_degree_statement_required')
    cond = conditions(desc)
    if desc['degrees']:
        body = base.polynomial(ast, x, p, desc['parameter_ref'], maximum=4)
        for row in desc['degrees']:
            poly, degree = sp.Poly(body, x), row['degree']
            cond += [sp.Ne(poly.nth(degree), 0), *[sp.Eq(poly.nth(i), 0) for i in range(degree+1, 5)]]
    trees = [domains.compile_domain(desc['domain_ast'], p, desc['parameter_ref'])]
    trees += [domains.compile_domain(r['domain_ast'], p, desc['parameter_ref']) for r in desc['defined_regions']]
    points = {sp.S.Zero, *fixed_cuts, *(v for row in parts for v in row['holes']),
              *(v for tree in trees for v in domains.endpoints(tree))}
    points |= {-v for v in points}
    if len(points) > fixed.MAX_CUTS:
        raise ValueError('parity_param.r2_input_cell_budget')
    cuts = set()
    for a, b in combinations(points, 2):
        cuts.update(roots(a-b, p))
    for row in parts:
        for g in row['parameter_guards']:
            cuts.update(roots(g, p))
    if len(cuts) > base.LIMITS['cuts']:
        raise ValueError('parity_param.parameter_cell_budget')
    return {'kind': 'rational_cells', 'parts': parts, 'points': sorted(points, key=sp.default_sort_key),
            'cuts': sorted(cuts), 'trees': trees, 'conditions': cond}


def _value_branch(src, x, p, parameter, point):
    for i, row in enumerate(src['parts']):
        if (row['scope'].contains(point) is sp.true
                and all(sp.simplify(g.subs({x: point, p: parameter})) != 0 for g in row['guards'])):
            return i
    return None


def _original_value(ast, xvalue, pvalue, ref):
    """Independent numeric source evaluation, retaining undefined operations."""
    if ast == ['bound', 'function_argument']:
        return True, xvalue
    if ast[0] == 'ref' and ast[1] == ref:
        return True, pvalue
    if ast[0] == 'number':
        return True, sp.Rational(ast[1])
    if ast[:2] == ['call', 'piecewise']:
        active = [body for body, domain in fixed.branches(ast) if domain.contains(xvalue) is sp.true]
        return _original_value(active[0], xvalue, pvalue, ref) if len(active) == 1 else (False, None)
    if ast[:2] == ['call', 'abs']:
        ok, v = _original_value(ast[2], xvalue, pvalue, ref)
        return ok, abs(v) if ok else None
    ok, a = _original_value(ast[1], xvalue, pvalue, ref)
    if ast[0] == 'neg':
        return ok, -a if ok else None
    valid, b = _original_value(ast[2], xvalue, pvalue, ref)
    if not ok or not valid or ast[0] == '/' and b == 0 or ast[0] == '^' and a == b == 0:
        return False, None
    return True, sp.simplify({'+': lambda: a+b, '-': lambda: a-b, '*': lambda: a*b,
                             '/': lambda: a/b, '^': lambda: a**b}[ast[0]]())


def _equations(expr, atom, x, p, region, *, independent=False):
    if atom['kind'] == 'point':
        values = [expr.subs(x, atom['point'])]
    elif independent:
        degree = max(0, sp.Poly(expr, x).degree())
        # Derivatives at zero recover every coefficient on an open input cell.
        values = [sp.diff(expr, x, i).subs(x, 0)/sp.factorial(i) for i in range(degree+1)]
    else:
        values = sp.Poly(expr, x).all_coeffs()
    if isinstance(region, sp.FiniteSet):
        values = [v.subs(p, next(iter(region))) for v in values]
    values = sorted({sp.simplify(v) for v in values if sp.simplify(v) != 0}, key=sp.default_sort_key)
    for v in values:
        roots(v, p)
    return values


def compare(desc):
    return _derive(desc)


def _derive(desc, *, independent=False):
    src = source(desc)
    if src['kind'] == 'radical':
        from .parity_parameter_radical import compare as radical_compare
        return radical_compare(desc, src, independent=independent)
    x, p = symbols(desc)
    cuts = src['cuts']
    regions = [sp.FiniteSet(c) for c in cuts]
    regions += [sp.Interval.open(a, b) for a, b in pairwise([-sp.oo, *cuts, sp.oo])]
    signs = sorted({s for f in desc['parity_facts'] for s in base.PROPERTIES[f['property']]})
    rows = []
    for region in regions:
        sample = domains.representative(region)
        atoms = domains.input_atoms(src['points'], p, sample)
        valid = all(domains.interval_valid(tree, p, sample) for tree in src['trees'])
        equations, zeros = set(), set()
        for atom in atoms:
            q = domains.atom_point(atom, p, sample)
            own, other = (_value_branch(src, x, p, sample, v) for v in (q, -q))
            if independent:
                for v, index in ((q, own), (-q, other)):
                    ok, actual = _original_value(desc['expression_ast'], v, sample, desc['parameter_ref'])
                    if ok != (index is not None):
                        raise ValueError('parity_param.r2_original_guard_mismatch')
                    if ok:
                        r = src['parts'][index]
                        expected = (r['numerator']/r['denominator']).subs({x: v, p: sample})
                        if sp.simplify(actual-expected) != 0:
                            raise ValueError('parity_param.r2_source_value_mismatch')
            declared = desc['domain_role'] == 'declared'
            member = domains.contains(src['trees'][0], p, sample, q) if declared else own is not None
            reflected = domains.contains(src['trees'][0], p, sample, -q) if declared else other is not None
            if declared and member and own is None:
                valid = False
            if any(domains.contains(t, p, sample, q) and own is None for t in src['trees'][1:]):
                valid = False
            atom.update(member=member, reflected_member=reflected, branch=own, reflected_branch=other)
            if member and own is not None:
                a = src['parts'][own]
                zeros.update(_equations(a['numerator'], atom, x, p, region, independent=independent))
                if reflected and other is not None:
                    b = src['parts'][other]
                    for sign in signs:
                        residual = sp.expand(b['numerator'].subs(x, -x)*a['denominator']
                                             - sign*a['numerator']*b['denominator'].subs(x, -x))
                        equations.update(_equations(residual, atom, x, p, region, independent=independent))
        nonempty = any(a['member'] for a in atoms)
        symmetric = all(a['member'] == a['reflected_member'] for a in atoms)
        rows.append({'parameter_cell': region, 'sample': sample, 'valid': valid, 'nonempty': nonempty,
                     'symmetric': symmetric, 'input_atoms': atoms,
                     'equations': sorted(equations, key=sp.default_sort_key),
                     'zero_equations': sorted(zeros, key=sp.default_sort_key)})
    all_cuts = set(cuts)
    expressions = [e for c in src['conditions'] for e in base._relations(c)]
    expressions += [e for row in rows for e in [*row['equations'], *row['zero_equations']]]
    for e in expressions:
        for part in sp.cancel(e).as_numer_denom():
            all_cuts.update(roots(part, p))
    if len(all_cuts) > base.LIMITS['cuts']:
        raise ValueError('parity_param.parameter_cell_budget')
    return {'kind': 'rational_cells', 'source': src, 'rows': rows}


def aggregate(desc, comparison, *, independent=False):
    _, p = symbols(desc)
    set_for = (lambda cs: cell_set(cs, p)) if independent else (
        lambda cs: sp.Intersection(*(base.condition_set(c, p) for c in cs)) if cs else sp.S.Reals)
    cond = comparison['source']['conditions']
    parameter_space = set_for(cond)
    if comparison['kind'] == 'radical':
        parity = set_for(comparison['parity_conditions'])
        zero = set_for(comparison['zero_conditions'])
        domain_parameters = set_for(comparison['domain_conditions'])
    else:
        parity, zero, valid = [], [], []
        for row in comparison['rows']:
            if not (row['valid'] and row['nonempty'] and row['symmetric']):
                continue
            region = row['parameter_cell']
            valid.append(region)
            parity.append(region & set_for([sp.Eq(e, 0) for e in row['equations']]))
            zero.append(region & set_for([sp.Eq(e, 0) for e in row['zero_equations']]))
        parity, zero, domain_parameters = sp.Union(*parity), sp.Union(*zero), sp.Union(*valid)
    exclusive = any(f['property'].endswith('_only') for f in desc['parity_facts'])
    feasible = parameter_space & domain_parameters & parity
    if exclusive:
        feasible -= zero
    return {'parameter_space': parameter_space, 'parity_set': parity, 'zero_set': zero,
            'domain_parameters': domain_parameters, 'feasible_set': feasible,
            'exclusive': exclusive, 'conditions': cond}


def solve(desc, comparison=None):
    expected = compare(desc)
    if comparison is not None and comparison != expected:
        raise ValueError('parity_param.r2_source_certificate_mismatch')
    return {'version': VERSION, 'description': deepcopy(desc), 'comparison': expected,
            **aggregate(desc, expected), 'verification_basis': 'original_guards_and_complete_mirror_cells'}


def verify(desc, model):
    try:
        if model.get('version') != VERSION or model.get('description') != desc:
            return False
        checked = _derive(desc, independent=True)
        return (model.get('comparison') == checked
                and all(model.get(k) == v for k, v in aggregate(desc, checked, independent=True).items()))
    except (ValueError, TypeError, KeyError, IndexError, NotImplementedError):
        return False
