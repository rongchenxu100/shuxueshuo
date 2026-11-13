"""Symbolic endpoint certificates for sqrt(alpha(p)*x²+beta(p)).

Nine exhaustive coefficient-sign cases include empty and singleton natural
domains. Declaring R adds a separate all-input legality obligation.
"""
import sympy as sp

from . import parity_parameter_math as base


def source(desc):
    from .parity_parameter_original import conditions, symbols
    x, p = symbols(desc)
    if desc['domain_ast'] != ['real'] or desc['defined_regions'] or desc['degrees']:
        raise ValueError('parity_param.r2_radical_natural_or_real_domain_required')
    expr = base.polynomial(desc['expression_ast'][2], x, p, desc['parameter_ref'], maximum=4)
    poly = sp.Poly(expr, x)
    a, b = poly.nth(2), poly.nth(0)
    if poly.degree() > 2 or poly.nth(1) != 0 or any(sp.Poly(c, p).degree() > 1 for c in (a, b)):
        raise ValueError('parity_param.r2_even_affine_radical_required')
    return {'kind': 'radical', 'alpha': a, 'beta': b, 'conditions': conditions(desc)}


def domain_proof(desc, src, *, independent=False):
    from .parity_parameter_original import cell_set, symbols
    _, p = symbols(desc)
    a, b = src['alpha'], src['beta']
    cases = []
    signs = {-1: sp.Lt, 0: sp.Eq, 1: sp.Gt}
    for sa in (-1, 0, 1):
        for sb in (-1, 0, 1):
            condition = sp.And(signs[sa](a, 0), signs[sb](b, 0))
            if sa <= 0 and sb < 0:
                kind = 'empty'
            elif sa < 0 and sb == 0:
                kind = 'singleton_zero'
            elif sa < 0 and sb > 0:
                kind = 'closed_bounded'
            elif sa > 0 and sb < 0:
                kind = 'closed_exterior'
            else:
                kind = 'real'
            # Use abstract nonzero coefficient symbols in the certificate even
            # when this sign case is impossible for the concrete source.
            alpha = sp.Symbol('alpha', real=True)
            beta = sp.Symbol('beta', real=True)
            radius = sp.sqrt(-beta/alpha)
            endpoints = {'left': -radius, 'right': radius, 'square': -beta/alpha,
                         'left_closed': True, 'right_closed': True} if kind.startswith('closed_') else None
            if (independent and endpoints is not None
                    and (sp.simplify(alpha*radius**2+beta) != 0 or endpoints['left']+endpoints['right'] != 0)):
                raise ValueError('parity_param.r2_radical_endpoint_identity')
            cases.append({'alpha_sign': sa, 'beta_sign': sb, 'condition': condition,
                          'parameter_cell': cell_set([condition], p) if independent else base.condition_set(condition, p),
                          'domain_kind': kind, 'endpoints': endpoints,
                          'coefficient_bindings': {'alpha': a, 'beta': b},
                          'nonempty': kind != 'empty', 'symmetric': kind != 'empty',
                          'zero_on_domain': kind == 'singleton_zero' or sa == sb == 0})
    declared = desc['domain_role'] == 'declared'
    domain = sp.And(a >= 0, b >= 0) if declared else sp.Or(a > 0, b >= 0)
    if independent:
        case_domain = sp.Or(*(c['condition'] for c in cases if c['nonempty']
                             and (not declared or c['domain_kind'] == 'real')))
        if cell_set([domain], p) != cell_set([case_domain], p):
            raise ValueError('parity_param.r2_radical_case_coverage')
    return {'kind': 'radical', 'source': src, 'cases': cases, 'domain_conditions': [domain]}


def compare(desc, src, *, independent=False):
    from .parity_parameter_original import cell_set, symbols
    proof = domain_proof(desc, src, independent=independent)
    a, b = src['alpha'], src['beta']
    _, p = symbols(desc)
    cases = proof['cases']
    domain, = proof['domain_conditions']
    declared = desc['domain_role'] == 'declared'
    zero = sp.And(sp.Eq(a, 0), sp.Eq(b, 0)) if declared else sp.And(a <= 0, sp.Eq(b, 0))
    odd = any(-1 in base.PROPERTIES[f['property']] for f in desc['parity_facts'])
    # Independent reasoning: a nonnegative odd function is zero on its entire
    # symmetric domain. Check the union of the exhaustive zero/domain cases.
    if independent:
        case_zero = sp.Or(*(c['condition'] for c in cases if c['zero_on_domain']
                           and (not declared or c['domain_kind'] == 'real')))
        if cell_set([zero], p) != cell_set([case_zero], p):
            raise ValueError('parity_param.r2_radical_case_coverage')
    return {**proof, 'zero_conditions': [zero],
            'parity_conditions': [zero if odd else domain]}
