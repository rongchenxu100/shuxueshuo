"""FP-T4 R0: solve f(x) □ k from a parity fact and a local polynomial rule.

The order route (R1–R2) and the sign route (R3) live in their own modules and are
dispatched by `route`.

The rule, its range I = D ∩ (printed range) and D are bound by the T3 parity
extension contract. The inequality is solved on I, carried to −I by parity
(an odd function flips the relation and the threshold), and 0 is decided on
its own. Nothing outside I ∪ −I ∪ {0} is guessed; a free value at 0 or an
answer that depends on an unstated domain is a capability gap, not an answer.
"""
from copy import deepcopy
from itertools import pairwise

import sympy as sp

from . import parity_extension_math as extension
from .parity_extension_math import (
    SIGNS,
    combined_rule,
    reflect,
    region,
    rule_expression,
)

VERSION = 'parity-inequality/r0-v1'
OPS = {'<': sp.Lt, '<=': sp.Le, '>': sp.Gt, '>=': sp.Ge}
FLIP = {'<': '>', '<=': '>=', '>': '<', '>=': '<='}
LIMITS = {'degree': 2}
MODEL_KEYS = {'version', 'description', 'variable', 'operator', 'threshold', 'sign', 'mirror_operator',
              'mirror_threshold', 'rule', 'rule_domain', 'known_solution', 'mirror_solution',
              'mirrored_domain', 'mirrored_solution', 'cases', 'domain_identity', 'solution', 'status'}


def symbols(desc):
    return sp.Symbol(desc['variable'], real=True)


def threshold(desc):
    return rule_expression(desc['threshold_ast'], symbols(desc))


def _name(ref):
    return ref[1].rsplit(':', 1)[-1] if isinstance(ref, list) and ref[:1] == ['ref'] else None


def _has_ref(ast):
    return isinstance(ast, list) and (ast[:1] in (['ref'], ['bound']) or any(_has_ref(v) for v in ast[1:]))


def _inequality(goal_ast, name, variable):
    """f(x) □ k with the call on either side; the threshold is a constant."""
    ast = goal_ast.get('value')
    if not isinstance(ast, list) or ast[0] not in OPS:
        raise ValueError('parity_ineq.single_inequality_required')
    sides = [s for s in ast[1:] if s[:1] == ['function_call'] and _name(s[1]) == name]
    if len(sides) != 1:
        raise ValueError('parity_ineq.single_function_value_required')
    call, = sides
    if _name(call[2]) != variable or call[2][-1] != 'scalar':
        raise ValueError('parity_ineq.input_form_unsupported')
    op, other = (ast[0], ast[2]) if ast[1] is call else (FLIP[ast[0]], ast[1])
    if _has_ref(other):
        raise ValueError('parity_ineq.threshold_not_constant')
    return op, deepcopy(other)


def _rule(desc):
    x = symbols(desc)
    rule, known = combined_rule(desc['extension'])
    try:
        poly = sp.Poly(extension.rule_polynomial(desc['extension']['rule_ast'], x), x)
    except (ValueError, sp.PolynomialError) as exc:
        raise ValueError('parity_ineq.rule_form_unsupported') from exc
    if poly.degree() > LIMITS['degree']:
        raise ValueError('parity_ineq.degree_budget')
    return rule, known


def domain_cases(desc):
    """The declared D, or — when D is not printed — every D the rule ranges leave possible."""
    _, known = _rule(desc)
    ext = desc['extension']
    if ext['domain_ast'] is not None:
        return [region(ext['domain_ast'])], 'explicit'
    base = known | reflect(known)
    if (sp.S.Reals - base) - sp.FiniteSet(0) != sp.S.EmptySet:
        raise ValueError('parity_ineq.domain_required')
    if base.contains(0) is sp.true:
        return [sp.S.Reals], 'from_rule_ranges'
    return [sp.S.Reals - sp.FiniteSet(0), sp.S.Reals], 'zero_membership_open'


def _same(a, b):
    return (a - b) == sp.S.EmptySet and (b - a) == sp.S.EmptySet


def solve(desc):
    if not desc.get('structure_supported'):
        raise ValueError(desc.get('reason') or 'parity_ineq.unsupported')
    if desc.get('route') == 'order':
        from .parity_order_math import solve as solve_order
        return solve_order(desc)
    if desc.get('route') == 'sign':
        from .parity_sign_math import solve as solve_sign
        return solve_sign(desc)
    return _solve(desc)


def _solve(desc):
    from .parity_inequality_inputs import requested
    x = symbols(desc)
    allowed = requested(desc, x)
    rule, known = _rule(desc)
    op, k = desc['operator'], threshold(desc)
    sign = SIGNS[desc['property']]
    mop, mk = (op, k) if sign == 1 else (FLIP[op], -k)
    known_solution = sp.solveset(OPS[op](rule, k), x, known)
    mirror_solution = sp.solveset(OPS[mop](rule, mk), x, known)
    domains, identity = domain_cases(desc)
    cases = []
    for domain in domains:
        mirrored = (domain & reflect(known)) - known
        rest = domain - known - reflect(known)
        if rest - sp.FiniteSet(0) != sp.S.EmptySet:
            raise ValueError('parity_ineq.rule_not_covering_domain')
        if rest == sp.S.EmptySet:
            zero, included = ('known' if known.contains(0) is sp.true else 'not_in_domain'), None
        elif allowed.contains(0) is not sp.true:
            zero, included = 'outside_requested_range', False
        elif sign == 1 and allowed.contains(0) is sp.true:
            raise ValueError('parity_ineq.zero_value_free')
        else:
            zero, included = 'forced_zero', bool(OPS[op](sp.S.Zero, k))
        mirrored_solution = reflect(mirror_solution) & mirrored
        solution = (known_solution | mirrored_solution | (sp.FiniteSet(0) if included else sp.S.EmptySet)) & allowed
        cases.append({'domain': domain, 'mirrored_domain': mirrored, 'mirrored_solution': mirrored_solution,
                      'zero_status': zero, 'zero_included': included, 'solution': solution})
    if any(not _same(c['solution'], cases[0]['solution']) for c in cases[1:]):
        raise ValueError('parity_ineq.domain_dependent_answer')
    first = cases[0]
    return {'version': VERSION, 'description': deepcopy(desc), 'variable': x, 'operator': op, 'threshold': k,
            'sign': sign, 'mirror_operator': mop, 'mirror_threshold': mk, 'rule': rule, 'rule_domain': known,
            'known_solution': known_solution, 'mirror_solution': mirror_solution,
            'mirrored_domain': first['mirrored_domain'], 'mirrored_solution': first['mirrored_solution'],
            'cases': [{k2: c[k2] for k2 in ('domain', 'zero_status', 'zero_included', 'solution')} for c in cases],
            'domain_identity': identity, 'solution': first['solution'], 'status': 'determined'}


def _bind(desc, candidate, target_ref):
    from .stage_two.fragments import _scope_ranges
    from .stage_two.parity_inequality_surface import source_spans
    if source_spans(candidate, target_ref, _scope_ranges(candidate, target_ref), desc) is None:
        raise ValueError('parity_ineq.source_not_bound')


def describe(goal, goal_ast, target_ref, entries, *, candidate=None):
    """Bind the asked inequality to a parity fact and a rule or direction; None when this is not such a target."""
    from . import parity_order_math as order
    facts = [r for r in entries if r['ast'][0] == 'function_parity']
    if goal.get('kind') != 'find_range' or not facts:
        return None
    base = {'source': deepcopy(goal), 'target_ref': target_ref,
            'source_refs': [target_ref, *[r['source_ref'] for r in entries]],
            'given_entries': [{k: deepcopy(r[k]) for k in ('source_ref', 'expression', 'ast')} for r in entries],
            'structure_supported': False, 'reason': ''}
    inferred = order.quantified_direction(entries) if 'function_monotonicity' not in goal else None
    if 'relation' not in goal and (isinstance(goal.get('function_monotonicity'), dict) or inferred):
        from . import parity_sign_math as sign
        desc = (None if inferred else
                sign.describe(goal, target_ref, entries, {**base, 'route': 'sign', 'structure_version': sign.VERSION}))
        if desc is None:
            desc = order.describe_given(goal, target_ref, entries,
                                        {**base, 'route': 'order', 'structure_version': order.VERSION}, inferred=inferred)
        if desc is not None and desc['structure_supported'] and candidate is not None:
            try:
                _bind(desc, candidate, target_ref)
            except (ValueError, TypeError, KeyError, IndexError) as exc:
                desc.update(structure_supported=False, reason=str(exc))
        return desc
    name = goal.get('function') or (order._name(facts[0]['ast'][1]) if len(facts) == 1 else None)
    if 'relation' not in goal and not any(extension.quantified_rule(r['ast'], r['source_ref'], facts[0]['ast'][1][1])
                                         for r in entries):
        return None
    if not any(_name(r['ast'][1]) == name for r in facts):
        return None
    relation_rows = [r for r in entries if r['ast'][0] in OPS and order._calls(r['ast'])]
    target = goal_ast.get('value')
    if not (isinstance(target, list) and target[0] in OPS and order._calls(target)) and not relation_rows:
        # A local formula and a parity fact also occur in parameter problems.
        # They do not, by themselves, make the requested range an inequality.
        return None
    desc = {**base, 'route': 'half_axis', 'structure_version': VERSION}
    try:
        variable = goal.get('variable', goal['symbol'])
        if goal['symbol'] != variable:
            raise ValueError('parity_ineq.variable_mismatch')
        goal_ast = deepcopy(goal_ast)
        if 'expression' in goal:
            relation_ref = target_ref + '/expression'
            owned = [r for r in relation_rows if r['ast'] == goal_ast.get('value')]
        else:
            if len(relation_rows) != 1:
                raise ValueError('parity_ineq.single_inequality_required')
            row, = relation_rows
            goal_ast['value'], relation_ref, owned = row['ast'], row['source_ref'], [row]
        desc['relation_source_ref'] = relation_ref
        formula = {k: deepcopy(goal[k]) for k in ('function', 'variable', 'relation', 'relation_domain',
                                                   'declared_domain', 'additional_relations', 'function_type')
                   if k in goal}
        formula.update(kind='find_function_formula', function=name, variable=variable)
        formula_ast = {k: deepcopy(goal_ast[k]) for k in ('relation', 'relation_domain', 'declared_domain',
                                                          'additional_relations') if k in goal_ast}
        from .parity_inequality_inputs import constraint_rows
        constraints = constraint_rows(entries, variable)
        ext = extension.describe(formula, formula_ast, target_ref,
                                 [r for r in entries if r not in constraints and r not in owned])
        if not ext['structure_supported']:
            raise ValueError(ext['reason'] or 'parity_ext.unsupported')
        if len(extension.rule_rows(ext)) != 1 or ext['point_rules']:
            raise ValueError('parity_ineq.single_rule_required')
        if ext['property'] not in ('odd', 'even'):
            raise ValueError('parity_ineq.property_unsupported')
        try:
            op, threshold_ast = _inequality(goal_ast, name, variable)
        except ValueError as exc:
            if str(exc) not in ('parity_ineq.single_function_value_required', 'parity_ineq.input_form_unsupported'):
                raise
            desc.update(route='order', structure_version=order.VERSION)
            order.describe_rule({**goal, 'function': name, 'variable': variable}, goal_ast, target_ref, entries, desc, ext)
        else:
            desc.update(extension=ext, function=name, variable=variable, property=ext['property'],
                        operator=op, threshold_ast=threshold_ast, relation_ast=deepcopy(goal_ast['value']),
                        parity_source_ref=ext['parity_source_ref'], domain_source_refs=ext['domain_source_refs'])
            k = threshold(desc)
            if k.free_symbols or not k.is_real:
                raise ValueError('parity_ineq.threshold_not_constant')
            _solve(desc)
        if candidate is not None:
            _bind(desc, candidate, target_ref)
        desc['structure_supported'] = True
    except (ValueError, TypeError, KeyError, IndexError, NotImplementedError) as exc:
        desc['reason'] = str(exc)
    return desc


def _roots(expr, x):
    return [r for r in sp.roots(sp.Poly(expr, x)) if r.is_real]


def _truth(value, op, k):
    relation = OPS[op](sp.radsimp(value), k)
    if relation not in (sp.true, sp.false):
        raise ValueError('parity_ineq.undecided_comparison')
    return relation is sp.true


def _cells(points, domain):
    """Points of the domain and the open cells between consecutive cut points, each with a representative."""
    ordered = sorted({p for p in points if p.is_finite}, key=lambda p: float(p))
    rows = [(sp.FiniteSet(p), p) for p in ordered if domain.contains(p) is sp.true]
    ends = [-sp.oo, *ordered, sp.oo]
    for a, b in pairwise(ends):
        cell = sp.Interval.open(a, b)
        rep = b - 1 if a == -sp.oo and b != sp.oo else a + 1 if b == sp.oo and a != -sp.oo else \
            sp.S.Zero if a == -sp.oo else (a + b) / 2
        if domain.contains(rep) is sp.true:
            rows.append((cell, rep))
    return rows


def _matches(claimed, domain, points, value_at):
    """claimed equals {t ∈ domain : value_at(t)} when the value's truth is constant between the cut points."""
    if not claimed.is_subset(domain):
        return False
    for cell, rep in _cells(points, domain):
        if not cell.is_subset(domain):
            return False
        if value_at(rep):
            if not cell.is_subset(claimed):
                return False
        elif (cell & claimed) != sp.S.EmptySet:
            return False
    return True


def verify(desc, model):
    """Independent check from the source rule: cut ℝ at roots and range ends, then read f by parity at each cell."""
    if desc.get('route') == 'order':
        from .parity_order_math import verify as verify_order
        return verify_order(desc, model)
    if desc.get('route') == 'sign':
        from .parity_sign_math import verify as verify_sign
        return verify_sign(desc, model)
    try:
        if not desc.get('structure_supported') or model.get('description') != desc:
            return False
        if set(model) != MODEL_KEYS or model['version'] != VERSION or model['status'] != 'determined':
            return False
        x = sp.Symbol(desc['variable'], real=True)
        ext = desc['extension']
        rule, known = combined_rule(ext)
        if sp.Poly(rule, x).degree() > LIMITS['degree']:
            return False
        op, k = desc['operator'], rule_expression(desc['threshold_ast'], x)
        sign = SIGNS[desc['property']]
        mop, mk = (op, k) if sign == 1 else (FLIP[op], -k)
        if (model['variable'] != x or model['operator'] != op or model['threshold'] != k or model['sign'] != sign
                or model['mirror_operator'] != mop or model['mirror_threshold'] != mk
                or sp.expand(model['rule'] - rule) != 0 or not _same(model['rule_domain'], known)):
            return False
        neg = lambda s: sp.imageset(sp.Lambda(x, -x), s)
        roots = [*_roots(rule - k, x), *_roots(rule - mk, x)]
        bounds = [p for s in (known, neg(known)) for p in s.boundary if p.is_finite]
        cuts = {sp.S.Zero, *roots, *(-r for r in roots), *bounds}
        if not (_matches(model['known_solution'], known, cuts, lambda t: _truth(rule.subs(x, t), op, k))
                and _matches(model['mirror_solution'], known, cuts, lambda t: _truth(rule.subs(x, t), mop, mk))):
            return False
        if ext['domain_ast'] is not None:
            domains, identity = [region(ext['domain_ast'])], 'explicit'
        else:
            base = known | neg(known)
            if (sp.S.Reals - base) - sp.FiniteSet(0) != sp.S.EmptySet:
                return False
            domains, identity = (([sp.S.Reals], 'from_rule_ranges') if base.contains(0) is sp.true
                                 else ([sp.S.Reals - sp.FiniteSet(0), sp.S.Reals], 'zero_membership_open'))
        if model['domain_identity'] != identity or len(model['cases']) != len(domains):
            return False

        def value(t):
            if known.contains(t) is sp.true:
                return rule.subs(x, t)
            if known.contains(-t) is sp.true:
                return sign * rule.subs(x, -t)
            if t == 0 and sign == -1:
                return sp.S.Zero
            raise ValueError('parity_ineq.value_not_determined')

        from .parity_inequality_inputs import requested
        allowed = requested(desc, x)
        for domain, case in zip(domains, model['cases']):
            if not _same(case['domain'], domain) or not _same(case['solution'], model['solution']):
                return False
            cut = cuts | {p for p in (domain & allowed).boundary if p.is_finite}
            if not _matches(model['solution'], domain & allowed, cut, lambda t: _truth(value(t), op, k)):
                return False
        mirrored = (domains[0] & neg(known)) - known
        if (not _same(model['mirrored_domain'], mirrored)
                or not _same(model['mirrored_solution'], neg(model['mirror_solution']) & mirrored)):
            return False
        zero = sp.FiniteSet(0) if any(c['zero_included'] for c in model['cases'][:1]) else sp.S.EmptySet
        return _same(model['solution'], (model['known_solution'] | model['mirrored_solution'] | zero) & allowed)
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, NotImplementedError, sp.PolynomialError):
        return False
