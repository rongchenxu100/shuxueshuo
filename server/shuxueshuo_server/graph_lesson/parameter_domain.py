"""Exact one-parameter affine domains, with a complete endpoint-order certificate.

An open parameter cell contains no equality of two original/reflected endpoints.
Thus its input ordering, endpoint membership and reflection pairing are invariant.
Rational representatives select this ordering; they are not heuristic samples.
Every written interval must have strictly ordered endpoints, even inside a union.
"""
from copy import deepcopy
from itertools import combinations, pairwise

import sympy as sp

from .parity_parameter_math import LIMITS, _budget, polynomial

VERSION = 'affine-domain-symmetry/v1'
DOMAIN_LIMITS = {'intervals': 4, 'points': 8, 'input_cuts': 48}


def compile_domain(ast, parameter, parameter_ref):
    _budget(ast)
    counts = {'intervals': 0, 'points': 0}

    def endpoint(node):
        if node[0] == 'infinity':
            return node[1] * sp.oo
        if node[0] == 'neg' and node[1][0] == 'infinity':
            return -endpoint(node[1])
        value = sp.expand(polynomial(node, sp.Symbol('_domain_input'), parameter, parameter_ref))
        poly = sp.Poly(value, parameter)
        if poly.degree() > 1 or not (poly.domain.is_QQ or poly.domain.is_ZZ):
            raise ValueError('parameter_domain.affine_endpoint_required')
        return value

    def read(node):
        op = node[0]
        if op in ('real', 'empty_set'):
            return [op]
        if op == 'interval':
            counts['intervals'] += 1
            a, b = map(endpoint, node[3:])
            return [op, node[1], node[2], a, b]
        if op == 'set':
            counts['points'] += len(node)-1
            points = [endpoint(v) for v in node[1:]]
            if any(v in (-sp.oo, sp.oo) for v in points):
                raise ValueError('parameter_domain.finite_point_required')
            return [op, *points]
        if op in ('∪', '∩', 'set_difference'):
            return [op, read(node[1]), read(node[2])]
        raise ValueError('parameter_domain.set_syntax_required')

    tree = read(ast)
    if any(counts[k] > DOMAIN_LIMITS[k] for k in counts):
        raise ValueError('parameter_domain.domain_budget')
    return tree


def endpoints(tree):
    if tree[0] == 'interval':
        return [v for v in tree[3:] if v not in (-sp.oo, sp.oo)]
    if tree[0] == 'set':
        return tree[1:]
    return [v for child in tree[1:] if isinstance(child, list) for v in endpoints(child)]


def interval_valid(tree, parameter, value):
    if tree[0] == 'interval':
        a, b = [v.subs(parameter, value) for v in tree[3:]]
        return bool(a < b) and not (tree[1] and a == -sp.oo or tree[2] and b == sp.oo)
    return all(interval_valid(child, parameter, value) for child in tree[1:] if isinstance(child, list))


def contains(tree, parameter, value, point):
    op = tree[0]
    if op in ('real', 'empty_set'):
        return op == 'real'
    if op == 'set':
        return any(point == v.subs(parameter, value) for v in tree[1:])
    if op == 'interval':
        a, b = [v.subs(parameter, value) for v in tree[3:]]
        return bool((point > a or tree[1] and point == a) and (point < b or tree[2] and point == b))
    a, b = [contains(child, parameter, value, point) for child in tree[1:]]
    return {'∪': lambda: a or b, '∩': lambda: a and b, 'set_difference': lambda: a and not b}[op]()


def fixed_set(tree, parameter, value):
    """For independent checking and display only; invalid syntax is rejected."""
    if not interval_valid(tree, parameter, value):
        raise ValueError('parameter_domain.invalid_interval_notation')
    op = tree[0]
    if op == 'real':
        return sp.S.Reals
    if op == 'empty_set':
        return sp.S.EmptySet
    if op == 'set':
        return sp.FiniteSet(*(v.subs(parameter, value) for v in tree[1:]))
    if op == 'interval':
        return sp.Interval(*(v.subs(parameter, value) for v in tree[3:]),
                           left_open=not tree[1], right_open=not tree[2])
    a, b = [fixed_set(child, parameter, value) for child in tree[1:]]
    return {'∪': lambda: a | b, '∩': lambda: a & b, 'set_difference': lambda: a-b}[op]()


def partition(tree, parameter):
    points = sorted({sp.S.Zero, *endpoints(tree), *[-v for v in endpoints(tree)]}, key=sp.default_sort_key)
    if len(points) > DOMAIN_LIMITS['input_cuts']:
        raise ValueError('parameter_domain.input_cell_budget')
    cuts = set()
    for a, b in combinations(points, 2):
        poly = sp.Poly(a-b, parameter)
        if poly.degree() == 1:
            cuts.add(-poly.nth(0)/poly.nth(1))
    if len(cuts) > LIMITS['cuts']:
        raise ValueError('parameter_domain.parameter_cell_budget')
    cuts = sorted(cuts)
    cells = [sp.FiniteSet(c) for c in cuts]
    cells += [sp.Interval.open(a, b) for a, b in pairwise([-sp.oo, *cuts, sp.oo])]
    return points, cuts, cells


def representative(cell):
    from .stage_three.verification import _rational_between
    return next(iter(cell)) if isinstance(cell, sp.FiniteSet) else _rational_between(cell.inf, cell.sup)


def input_atoms(points, parameter, value):
    ordered = sorted(points, key=lambda v: (v.subs(parameter, value), sp.default_sort_key(v)))
    unique = []
    for point in ordered:
        if not unique or point.subs(parameter, value) != unique[-1].subs(parameter, value):
            unique.append(point)
    return ([{'kind': 'point', 'point': p} for p in unique]
            + [{'kind': 'open', 'left': a, 'right': b}
               for a, b in pairwise([-sp.oo, *unique, sp.oo])])


def atom_point(atom, parameter, value):
    if atom['kind'] == 'point':
        return atom['point'].subs(parameter, value)
    a, b = (atom[k].subs(parameter, value) for k in ('left', 'right'))
    return b-1 if a == -sp.oo else a+1 if b == sp.oo else (a+b)/2


def solve_domain_symmetry_conditions(domain_ast, parameter, parameter_ref, source_refs):
    p = sp.Symbol(parameter, real=True)
    tree = compile_domain(domain_ast, p, parameter_ref)
    points, cuts, regions = partition(tree, p)
    cells = []
    for region in regions:
        value = representative(region)
        atoms = input_atoms(points, p, value)
        for atom in atoms:
            v = atom_point(atom, p, value)
            atom.update(member=contains(tree, p, value, v), reflected_member=contains(tree, p, value, -v))
        valid = interval_valid(tree, p, value)
        nonempty = valid and any(a['member'] for a in atoms)
        symmetric = nonempty and all(a['member'] == a['reflected_member'] for a in atoms)
        cells.append({'parameter_cell': region, 'representative': value, 'intervals_valid': valid,
                      'nonempty': nonempty, 'symmetric': symmetric, 'input_atoms': atoms})
    return {'version': VERSION, 'domain_ast': deepcopy(domain_ast), 'parameter': parameter,
            'parameter_ref': parameter_ref, 'source_refs': list(source_refs), 'cuts': cuts, 'cells': cells,
            'valid_parameters': sp.Union(*(c['parameter_cell'] for c in cells if c['nonempty'])),
            'symmetric_parameters': sp.Union(*(c['parameter_cell'] for c in cells if c['symmetric']))}


def verify_domain_symmetry_conditions(domain_ast, parameter, parameter_ref, source_refs, proof):
    """Check full cell coverage and reflection independently using fixed set algebra."""
    from .function_parity import reflect_set
    try:
        p = sp.Symbol(parameter, real=True)
        tree = compile_domain(domain_ast, p, parameter_ref)
        points, cuts, regions = partition(tree, p)
        if (proof['version'] != VERSION or proof['domain_ast'] != domain_ast
                or proof['parameter'] != parameter or proof['parameter_ref'] != parameter_ref
                or proof['source_refs'] != list(source_refs) or proof['cuts'] != cuts
                or [c['parameter_cell'] for c in proof['cells']] != regions):
            return False
        valid_regions, symmetric_regions = [], []
        for cell, region in zip(proof['cells'], regions, strict=True):
            value = cell['representative']
            if value != representative(region):
                return False
            # All endpoint crossings are in cuts; hence these atoms and their
            # membership cover every input for every parameter in this cell.
            expected_atoms = input_atoms(points, p, value)
            if len(cell['input_atoms']) != len(expected_atoms):
                return False
            valid = interval_valid(tree, p, value)
            domain = fixed_set(tree, p, value) if valid else sp.S.EmptySet
            for atom, expected in zip(cell['input_atoms'], expected_atoms, strict=True):
                if {k: v for k, v in atom.items() if k not in ('member', 'reflected_member')} != expected:
                    return False
                if valid:
                    q = atom_point(expected, p, value)
                    if (atom['member'] != bool(domain.contains(q))
                            or atom['reflected_member'] != bool(domain.contains(-q))):
                        return False
                elif (atom['member'] != contains(tree, p, value, atom_point(expected, p, value))
                      or atom['reflected_member'] != contains(tree, p, value, -atom_point(expected, p, value))):
                    return False
            nonempty = domain != sp.S.EmptySet
            symmetric = nonempty and domain == reflect_set(domain)
            if (cell['intervals_valid'], cell['nonempty'], cell['symmetric']) != (valid, nonempty, symmetric):
                return False
            if nonempty:
                valid_regions.append(region)
            if symmetric:
                symmetric_regions.append(region)
        return (proof['valid_parameters'] == sp.Union(*valid_regions)
                and proof['symmetric_parameters'] == sp.Union(*symmetric_regions))
    except (ValueError, TypeError, KeyError, IndexError, NotImplementedError):
        return False
