"""FP-T2 R0: exact parameter conditions for degree-at-most-two polynomials.

The given parity is an obligation, never a premise of the final verification.
Source binders, restrictions and declared degree survive coefficient expansion.
The verifier reconstructs coefficients by interpolation and checks every exact
parameter cell; it does not call the production solver or coefficient skill.
"""
from copy import deepcopy
from itertools import pairwise

import sympy as sp

from ..problem_understanding.notation_parser import definition
from .extremum_math import condition_set
from .function_cells import exact_point
from .function_coefficients import compare_coefficients, compare_quartic_coefficients

VERSION = 'parity-parameter/r0-v1'
LIMITS = {'nodes': 256, 'depth': 24, 'bits': 128, 'conditions': 32, 'cuts': 32}
PROPERTIES = {'odd': (-1,), 'even': (1,), 'both': (-1, 1),
              'odd_only': (-1,), 'even_only': (1,)}


def _budget(ast, depth=0):
    if depth > LIMITS['depth']:
        raise ValueError('parity_param.depth_budget')
    count = 1 + sum(_budget(v, depth + 1) for v in ast if isinstance(v, list))
    if count > LIMITS['nodes']:
        raise ValueError('parity_param.node_budget')
    return count


def polynomial(ast, variable, parameter, parameter_ref, *, maximum=2):
    """Read the original syntax: never cancel a variable/parameter denominator."""
    op = ast[0]
    if op == 'number':
        n = sp.Rational(ast[1])
        if max(abs(int(n.p)).bit_length(), int(n.q).bit_length()) > LIMITS['bits']:
            raise ValueError('parity_param.coefficient_budget')
        return n
    if ast == ['bound', 'function_argument']:
        return variable
    if op == 'ref' and ast[1] == parameter_ref:
        return parameter
    read = lambda v: polynomial(v, variable, parameter, parameter_ref, maximum=maximum)
    if op == 'neg':
        return -read(ast[1])
    if op not in ('+', '-', '*', '/', '^'):
        raise ValueError('parity_param.polynomial_required')
    a, b = read(ast[1]), read(ast[2])
    if op == '/' and (not isinstance(b, sp.Rational) or b == 0):
        raise ValueError('parity_param.constant_denominator_required')
    if op == '^' and (not b.is_Integer or not 0 <= b <= maximum):
        raise ValueError('parity_param.degree_budget')
    result = {'+': lambda: a+b, '-': lambda: a-b, '*': lambda: a*b,
              '/': lambda: a/b, '^': lambda: a**b}[op]()
    poly = sp.Poly(result, variable, parameter)
    if poly.total_degree() > maximum + 2:
        raise ValueError('parity_param.degree_budget')
    if any(max(abs(int(c.p)).bit_length(), int(c.q).bit_length()) > LIMITS['bits']
           for c in poly.coeffs() if isinstance(c, sp.Rational)):
        raise ValueError('parity_param.coefficient_budget')
    return result


def _region(ast):
    if ast == ['real']:
        return sp.S.Reals
    if ast[0] == 'empty_set':
        return sp.S.EmptySet
    def number(v):
        if v[0] == 'infinity':
            return (v[1] if len(v) > 1 else 1) * sp.oo
        if v[0] == 'neg':
            return -number(v[1])
        return polynomial(v, sp.Symbol('_u'), sp.Symbol('_p'), None)
    if ast[0] == 'set':
        return sp.FiniteSet(*(number(v) for v in ast[1:]))
    if ast[0] == 'interval':
        left, right = number(ast[3]), number(ast[4])
        if not left < right:
            return sp.S.EmptySet
        return sp.Interval(left, right, not ast[1], not ast[2])
    if ast[0] in ('∪', '∩', 'set_difference'):
        a, b = _region(ast[1]), _region(ast[2])
        return {'∪': lambda: a | b, '∩': lambda: a & b, 'set_difference': lambda: a-b}[ast[0]]()
    raise ValueError('parity_param.fixed_parameter_set_required')


def _constraint(ast, x, p, ref):
    if ast[0] in ('and', 'or'):
        return {'and': sp.And, 'or': sp.Or}[ast[0]](*(_constraint(v, x, p, ref) for v in ast[1:]))
    if ast[0] in ('∈', '∉'):
        if ast[1][0] != 'ref' or ast[1][1] != ref:
            raise ValueError('parity_param.parameter_membership_required')
        cond = _region(ast[2]).as_relational(p)
        return cond if ast[0] == '∈' else sp.Not(cond)
    if ast[0] not in ('=', '!=', '<', '<=', '>', '>='):
        raise ValueError('parity_param.additional_condition_unsupported')
    a, b = (polynomial(v, x, p, ref) for v in ast[1:])
    if (a.free_symbols | b.free_symbols) - {p} or sp.Poly(a-b, p).degree() > 2:
        raise ValueError('parity_param.parameter_condition_budget')
    return {'=': sp.Eq, '!=': sp.Ne, '<': sp.Lt, '<=': sp.Le, '>': sp.Gt, '>=': sp.Ge}[ast[0]](a, b)


def describe(goal, goal_ast, target_ref, entries, *, candidate=None):
    """Consume bound facts from this target's lexical scope, not name matches."""
    facts = [r for r in entries if r['ast'][0] == 'function_parity']
    if not facts or goal.get('kind') not in ('find_value', 'find_range'):
        return None
    target = goal_ast.get('target', [])
    joint = (target[:1] == ['tuple'] and len(target) == 3 and target[1] != target[2]
             and all(v[0] == 'ref' and v[-1] == 'scalar' for v in target[1:]))
    if not joint and (not target or target[0] != 'ref' or target[-1] != 'scalar'):
        return None  # f(m) remains a parent evaluation target, not a parameter goal.
    def occurs(node):
        return node == target or isinstance(node, list) and any(occurs(v) for v in node if isinstance(v, list))
    def requested_input(node):
        return isinstance(node, list) and (node[:1] == ['function_call'] and occurs(node[2])
                                          or any(requested_input(v) for v in node if isinstance(v, list)))
    if any(requested_input(r['ast']) for r in entries):
        return None  # f(x-1) <= f(2x) is a parent input-range task, even with a parameterised domain.
    desc = {'source': deepcopy(goal), 'target_ref': target_ref, 'structure_version': VERSION,
            'analysis_mode': 'coefficients',
            'source_refs': [target_ref, *[r['source_ref'] for r in entries]],
            'given_entries': [{k: deepcopy(r[k]) for k in ('source_ref', 'expression', 'ast')} for r in entries],
            'parameter_ref': target[1] if not joint else None,
            'parameter': target[1].rsplit(':', 1)[-1] if not joint else
                         '(' + ','.join(v[1].rsplit(':', 1)[-1] for v in target[1:]) + ')',
            'structure_supported': False, 'reason': ''}
    try:
        if candidate is not None:
            scope = candidate['root']
            for segment in [*target_ref.strip('/').split('/')[1:-2], None]:
                if isinstance(scope, dict) and scope.get('uncertainties'):
                    raise ValueError('parity_param.unresolved_source')
                if segment is not None:
                    scope = scope[int(segment)] if isinstance(scope, list) else scope[segment]
        if len({r['ast'][1][1] for r in facts}) != 1:
            raise ValueError('parity_param.single_function_required')
        ref = facts[0]['ast'][1][1]
        definitions = [r for r in entries if r['ast'][0] == 'function_definition' and r['ast'][1][1] == ref]
        if joint:
            from .parity_parameter_joint import populate
            populate(desc, target, entries, facts, definitions, ref)
            if candidate is not None:
                from .stage_two.parity_parameter_surface import audit_requirements
                if not audit_requirements(candidate, target_ref, desc):
                    raise ValueError('parity_param.source_property_or_domain_mismatch')
            desc['structure_supported'] = True
            return desc
        domains = [value for row in entries if row['ast'][0] == '='
                   for call, value in (row['ast'][1:], row['ast'][1:][::-1])
                   if call[:2] == ['call', 'Dom'] and call[2][1] == ref]
        if len(definitions) == 1:
            from .parity_parameter_original import needs_extension
            from .parity_parameter_original import populate as populate_original
            if needs_extension(definitions[0]['ast'][2], desc['parameter_ref'], entries):
                populate_original(desc, entries, facts, definitions, ref)
                if candidate is not None:
                    from .stage_two.parity_parameter_surface import audit_requirements
                    if not audit_requirements(candidate, target_ref, desc):
                        raise ValueError('parity_param.source_property_or_domain_mismatch')
                desc['structure_supported'] = True
                return desc
        if (not definitions or any(domain != ['real'] for domain in domains)
                or any(row['ast'][0] == 'function_defined_on' for row in entries)):
            from .parity_parameter_domain import populate
            populate(desc, entries, facts, definitions, ref)
            if candidate is not None:
                from .stage_two.parity_parameter_surface import audit_requirements
                if not audit_requirements(candidate, target_ref, desc):
                    raise ValueError('parity_param.source_property_or_domain_mismatch')
            desc['structure_supported'] = True
            return desc
        if len(definitions) != 1:
            raise ValueError('parity_param.complete_polynomial_required')
        fn = definitions[0]
        raw = definition(fn['expression'])
        desc.update(function_ref=ref, function=ref.rsplit(':', 1)[-1], variable=raw[2],
                    expression=raw[3], expression_ast=fn['ast'][2], function_source_ref=fn['source_ref'],
                    variable_ref=fn['source_ref'] + '#function_argument', constraints=[], degrees=[], parity_facts=[])
        domain_refs = []
        for row in entries:
            ast = row['ast']
            _budget(ast)
            if row is fn or row in facts:
                continue
            if ast[0] == '=':
                for call, value in (ast[1:], ast[1:][::-1]):
                    if call[:2] == ['call', 'Dom'] and call[2][1] == ref:
                        if _region(value) != sp.S.Reals:
                            raise ValueError('parity_param.real_domain_required')
                        domain_refs.append(row['source_ref'])
                        break
                    if call[:2] == ['call', 'degree'] and call[2][1] == ref:
                        if value not in (['number', '0'], ['number', '1'], ['number', '2']):
                            raise ValueError('parity_param.declared_degree_unsupported')
                        desc['degrees'].append({'degree': int(value[1]), 'source_ref': row['source_ref']})
                        break
                else:
                    desc['constraints'].append(deepcopy(row))
            else:
                desc['constraints'].append(deepcopy(row))
        for row in facts:
            desc['parity_facts'].append({
                'kind': 'function_parity', 'function_ref': ref, 'variable_ref': desc['variable_ref'],
                'domain_ref': domain_refs or [ref + '#natural_domain'], 'property': row['ast'][2],
                'source_refs': [row['source_ref'], fn['source_ref'], *domain_refs], 'origin': 'given',
            })
        if len(desc['constraints']) + len(desc['degrees']) + len(facts) > LIMITS['conditions']:
            raise ValueError('parity_param.condition_budget')
        source(desc)
        if candidate is not None:
            from .stage_two.parity_parameter_surface import audit_requirements
            if not audit_requirements(candidate, target_ref, desc):
                raise ValueError('parity_param.source_property_or_domain_mismatch')
        desc['structure_supported'] = True
    except (ValueError, TypeError, KeyError, IndexError, NotImplementedError) as exc:
        desc['reason'] = str(exc)
    return desc


def source(desc):
    x, p = sp.Symbol(desc['variable'], real=True), sp.Symbol(desc['parameter'], real=True)
    if x == p:
        # Distinct bound input and parameter may have the same printed name.
        x = sp.Symbol('_function_input', real=True)
    maximum = 4 if desc.get('analysis_mode') == 'quartic' else 2
    expr = polynomial(desc['expression_ast'], x, p, desc['parameter_ref'], maximum=maximum)
    poly = sp.Poly(expr, x)
    if poly.degree() > maximum or any(sp.Poly(c, p).degree() > 2 or not sp.Poly(c, p).domain.is_QQ
                             and not sp.Poly(c, p).domain.is_ZZ for c in poly.all_coeffs()):
        raise ValueError('parity_param.coefficient_degree_budget')
    coefficients = [poly.nth(i) for i in range(maximum + 1)]
    if desc.get('analysis_mode') == 'quartic':
        from .parity_parameter_original import conditions as original_conditions
        conditions = original_conditions(desc)
    else:
        conditions = [_constraint(r['ast'], x, p, desc['parameter_ref']) for r in desc['constraints']]
    for row in desc['degrees']:
        degree = row['degree']
        conditions.extend([sp.Ne(coefficients[degree], 0), *[sp.Eq(c, 0) for c in coefficients[degree+1:]]])
    signs = sorted({s for fact in desc['parity_facts'] for s in PROPERTIES[fact['property']]})
    return x, p, expr, coefficients, conditions, signs


def identities(desc):
    x, p, expr, _, _, signs = source(desc)
    # Equality is intentionally unevaluated, including 0=0 and px²=px².
    return [sp.Eq(expr.subs(x, -x), sign*expr, evaluate=False) for sign in signs], x, [p], sp.S.Reals


def _sets(equations, p):
    return sp.Intersection(*(condition_set(sp.Eq(e, 0), p) for e in equations)) if equations else sp.S.Reals


def solve(desc, comparison=None):
    if desc.get('analysis_mode') == 'joint':
        from .parity_parameter_joint import solve as solve_joint
        return solve_joint(desc, comparison)
    if desc.get('analysis_mode') == 'original':
        from .parity_parameter_original import solve as solve_original
        return solve_original(desc, comparison)
    if desc.get('analysis_mode') == 'domain':
        from .parity_parameter_domain import solve as solve_domain
        return solve_domain(desc, comparison)
    compare = compare_quartic_coefficients if desc.get('analysis_mode') == 'quartic' else compare_coefficients
    expected = compare(*identities(desc))
    if comparison is not None and comparison != expected:
        raise ValueError('parity_param.coefficient_evidence_mismatch')
    _, p, _, coefficients, conditions, _ = source(desc)
    parameter_space = sp.Intersection(*(condition_set(c, p) for c in conditions)) if conditions else sp.S.Reals
    parity_set = _sets(expected['equations'], p)
    zero_set = _sets(coefficients, p)
    exclusive = any(f['property'].endswith('_only') for f in desc['parity_facts'])
    feasible = parameter_space & parity_set
    if exclusive:
        feasible -= zero_set
    return {'version': desc['structure_version'], 'description': deepcopy(desc), 'comparison': expected,
            'parameter_space': parameter_space, 'parity_set': parity_set, 'zero_set': zero_set,
            'feasible_set': feasible, 'exclusive': exclusive, 'coefficients': coefficients,
            'domain': sp.S.Reals, 'identities': identities(desc)[0],
            'conditions': conditions, 'verification_basis': 'all_coefficients_on_reals'}


def _roots(expr, p):
    """Closed quadratic formula, separate from the production set solver."""
    poly = sp.Poly(expr, p)
    if poly.is_zero or poly.degree() == 0:
        return []
    if poly.degree() == 1:
        return [exact_point(-poly.nth(0)/poly.nth(1))]
    if poly.degree() != 2:
        raise ValueError('parity_param.verification_degree_budget')
    a, b, c = poly.all_coeffs()
    delta = b*b-4*a*c
    if delta < 0:
        return []
    return list({exact_point((-b+sign*sp.sqrt(delta))/(2*a)) for sign in (-1, 1)})


def _relations(condition):
    if condition in (sp.true, sp.false):
        return []
    if condition.func in (sp.And, sp.Or, sp.Not):
        return [v for part in condition.args for v in _relations(part)]
    return [condition.lhs-condition.rhs]


def _cell_set(conditions, p):
    from .stage_three.verification import _rational_between
    roots = sorted({r for c in conditions for expression in _relations(c) for r in _roots(expression, p)})
    if len(roots) > LIMITS['cuts']:
        raise ValueError('parity_param.parameter_cell_budget')
    regions = [sp.FiniteSet(r) for r in roots]
    regions += [sp.Interval.open(a, b) for a, b in pairwise([-sp.oo, *roots, sp.oo])]
    accepted = []
    for cell in regions:
        sample = next(iter(cell)) if isinstance(cell, sp.FiniteSet) else _rational_between(cell.inf, cell.sup)
        if all(c.subs(p, sample) is sp.true for c in conditions):
            accepted.append(cell)
    return sp.Union(*accepted)


def verify(desc, model):
    if desc.get('analysis_mode') == 'joint':
        from .parity_parameter_joint import verify as verify_joint
        return verify_joint(desc, model)
    """Necessary AND sufficient: cover the real parameter line, including roots."""
    if desc.get('analysis_mode') == 'original':
        from .parity_parameter_original import verify as verify_original
        return verify_original(desc, model)
    if desc.get('analysis_mode') == 'domain':
        from .parity_parameter_domain import verify as verify_domain
        return verify_domain(desc, model)
    try:
        if model.get('version') != desc['structure_version'] or model.get('description') != desc:
            return False
        x, p, expr, _, conditions, signs = source(desc)
        # A degree <= 2 polynomial is uniquely fixed by these three values.
        c0 = expr.subs(x, 0)
        c1 = sp.expand((expr.subs(x, 1)-expr.subs(x, -1))/2)
        c2 = sp.expand((expr.subs(x, 1)+expr.subs(x, -1))/2-c0)
        coefficients = [c0, c1, c2]
        set_for = _cell_set
        if desc.get('analysis_mode') == 'quartic':
            from .parity_parameter_original import cell_set
            set_for = cell_set
            reconstructed = sp.interpolate([(v, expr.subs(x, v)) for v in (-2, -1, 0, 1, 2)], x).expand()
            coefficients = [reconstructed.coeff(x, i) for i in range(5)]
        parity = [sp.Eq(c*((-1)**degree-sign), 0) for sign in signs for degree, c in enumerate(coefficients)]
        nonzero = sp.Or(*(sp.Ne(c, 0) for c in coefficients))
        exclusive = any(f['property'].endswith('_only') for f in desc['parity_facts'])
        expected = set_for([*conditions, *parity, *([nonzero] if exclusive else [])], p)
        return (model.get('feasible_set') == expected and model.get('coefficients') == coefficients
                and model.get('parameter_space') == set_for(conditions, p)
                and model.get('parity_set') == set_for(parity, p)
                and model.get('zero_set') == set_for([sp.Eq(c, 0) for c in coefficients], p)
                and model.get('exclusive') == exclusive and model.get('domain') == sp.S.Reals
                and model.get('conditions') == conditions and model.get('identities') == identities(desc)[0]
                and _verify_comparison(model.get('comparison', {}), coefficients, signs))
    except (ValueError, TypeError, KeyError, IndexError, NotImplementedError):
        return False


def _verify_comparison(comparison, coefficients, signs):
    """Check every row and equation without invoking the coefficient skill."""
    rows, equations = [], []
    degree = max((i for i, c in enumerate(coefficients) if c != 0), default=0)
    for sign in signs:
        for power in range(degree, -1, -1):
            left, right = sp.expand((-1)**power*coefficients[power]), sp.expand(sign*coefficients[power])
            rows.append({'degree': power, 'left': left, 'right': right})
            residual = sp.expand(left-right)
            if residual != 0 and residual not in equations:
                equations.append(residual)
    return comparison == {'rows': rows, 'equations': equations, 'domain': sp.S.Reals}
