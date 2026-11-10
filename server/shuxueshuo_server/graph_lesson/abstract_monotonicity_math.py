"""Bounded proofs for additive, logarithmic, exponential and power relations.

Relations are normalized algebraically with opaque function values. No formula,
continuity, or sampled values are assumed. A sign condition must cover every
constructed input, and product outputs require a proof of strict positivity.
"""
from copy import deepcopy

import sympy as sp

from ..problem_understanding.notation_parser import NotationError, parse
from .extremum_math import domain

VERSION = 'abstract-monotonicity/v2'
KIND = 'determine_monotonicity_on_interval'
FAMILIES = {
    'additive': {'input': 'sum', 'output': 'sum', 'domain': sp.S.Reals},
    'multiplicative': {'input': 'product', 'output': 'sum', 'domain': sp.Interval.open(0, sp.oo)},
    'exponential': {'input': 'sum', 'output': 'product', 'domain': sp.S.Reals},
    'power': {'input': 'product', 'output': 'product', 'domain': sp.Interval.open(0, sp.oo)},
}
X1, X2 = sp.symbols('x_1 x_2', real=True)
U, V = sp.symbols('_u _v', real=True)
F = sp.Function('_f', real=True)


def relevant(goal):
    return isinstance(goal, dict) and (goal.get('kind') == KIND or (
        goal.get('kind') == 'prove_monotonicity_on_interval' and 'relation' in goal))


def routed_description(goal, target_ref, entries):
    return describe(goal, target_ref, entries) if relevant(goal) else None


def _set(text):
    try:
        value = domain(parse(text))
    except (NotationError, ValueError, KeyError, TypeError) as exc:
        raise ValueError('abstract_mono.domain_unreadable') from exc
    if not isinstance(value, sp.Interval) and value != sp.S.Reals:
        raise ValueError('abstract_mono.interval_required')
    return value


def _expression(ast, names, function, denominators):
    tag = ast[0]
    if tag == 'number':
        return sp.Rational(ast[1])
    if tag == 'name' and ast[1] in names:
        return names[ast[1]]
    if tag == 'call' and ast[1] == function:
        arg = _expression(ast[2], names, function, denominators)
        if arg.has(F):
            raise ValueError('abstract_mono.nested_call_unsupported')
        return F(arg)
    if tag == 'neg':
        return -_expression(ast[1], names, function, denominators)
    if tag in ('+', '-', '*', '/'):
        a, b = [_expression(t, names, function, denominators) for t in ast[1:]]
        if tag == '/':
            if b == 0:
                raise ValueError('abstract_mono.undefined_relation')
            denominators.append(b)
        return {'+': lambda: a+b, '-': lambda: a-b, '*': lambda: a*b, '/': lambda: a/b}[tag]()
    raise ValueError('abstract_mono.expression_unsupported')


def _relation(goal):
    names = goal.get('relation_variables', [])
    if len(names) != 2 or names[0] == names[1]:
        raise ValueError('abstract_mono.two_universal_variables_required')
    tree = parse(goal['relation'])
    if tree[0] != '=':
        raise ValueError('abstract_mono.equality_relation_required')
    denominators = []
    mapping = dict(zip(names, (U, V)))
    residual = _expression(tree[1], mapping, goal['function'], denominators) - _expression(
        tree[2], mapping, goal['function'], denominators)
    numerator = sp.expand(sp.together(residual).as_numer_denom()[0])
    for family, spec in FAMILIES.items():
        for reverse in (False, True):
            a, b = (V, U) if reverse else (U, V)
            for variant in ('direct', 'inverse'):
                joint = (a+b if variant == 'direct' else a-b) if spec['input'] == 'sum' else (
                    a*b if variant == 'direct' else a/b)
                if spec['output'] == 'sum':
                    expected = F(joint)-F(a)-(F(b) if variant == 'direct' else -F(b))
                else:
                    expected = F(joint)-F(a)*F(b) if variant == 'direct' else F(joint)*F(b)-F(a)
                ratio = sp.cancel(numerator / expected)
                if not isinstance(ratio, sp.Rational) or ratio == 0:
                    continue
                # Preserve definedness before clearing a denominator. No arbitrary
                # variable factors or cancellations may introduce a new solution.
                allowed = {U, V} if spec['input'] == 'product' else set()
                if spec['output'] == 'product':
                    allowed |= {F(U), F(V)}
                if any(not (d.is_number and d.is_zero is False) and d not in allowed for d in denominators):
                    raise ValueError('abstract_mono.denominator_scope_unsupported')
                return {'family': family, 'variant': variant, 'swapped': reverse,
                        'nonzero_from_relation': any(d.has(F) for d in denominators)}
    raise ValueError('abstract_mono.relation_shape_unsupported')


def _sign(goal, output):
    rule = goal['sign_condition']
    tree = parse(rule['statement'])
    comparisons = tree[1:] if tree[0] == 'and' else [tree]
    bounds = []
    z = sp.Symbol('_value', real=True)
    for comparison in comparisons:
        op = comparison[0]
        if op not in ('>', '<', '>=', '<='):
            raise ValueError('abstract_mono.sign_comparison_required')
        denominators = []
        env = {rule['variable']: U}
        delta = sp.expand(_expression(comparison[1], env, goal['function'], denominators)
                          - _expression(comparison[2], env, goal['function'], denominators))
        delta = delta.xreplace({F(U): z})
        if delta.free_symbols - {z} or delta.has(F) or any(not d.is_number for d in denominators):
            raise ValueError('abstract_mono.sign_shape_unsupported')
        poly = sp.Poly(delta, z)
        if poly.degree() != 1:
            raise ValueError('abstract_mono.sign_shape_unsupported')
        a, b = poly.all_coeffs()
        if not a.is_Rational or not b.is_Rational:
            raise ValueError('abstract_mono.sign_shape_unsupported')
        if a < 0:
            op = {'>': '<', '<': '>', '>=': '<=', '<=': '>='}[op]
        bounds.append((op, -b/a))
    threshold = sp.S.Zero if output == 'sum' else sp.S.One
    usable = [(op, n) for op, n in bounds if n == threshold and op in ('>', '<')]
    if len(usable) != 1:
        raise ValueError('abstract_mono.strict_sign_required')
    op, _ = usable[0]
    # Only the comparison at the identity and an optional positive lower bound
    # are consumed. Do not silently ignore additional restrictions.
    if any((cmp, n) != usable[0] and (output != 'product' or (cmp, n) != ('>', 0)) for cmp, n in bounds):
        raise ValueError('abstract_mono.extra_sign_constraint_unsupported')
    positive = output == 'product' and (op == '>' or ('>', sp.S.Zero) in bounds)
    return op, _set(rule['domain']), positive


def pair_symbols(goal):
    used = set(goal['relation_variables']) | {goal['function'], goal['variable'], goal['sign_condition']['variable']}
    for prefix in ('x', 'a', 'b', 'p', 'q'):
        names = (prefix+'_1', prefix+'_2')
        if not used.intersection(names):
            return sp.symbols(' '.join(names), real=True)
    raise ValueError('abstract_mono.fresh_pair_unavailable')


def key_range(interval, input_operation, orientation):
    closed = interval != sp.S.Reals and not interval.left_open and not interval.right_open
    if input_operation == 'sum':
        width = interval.measure
        return sp.Interval(0, width, True, not closed) if orientation == 1 else sp.Interval(-width, 0, not closed, True)
    upper = sp.oo if interval.inf == 0 or interval.sup == sp.oo else interval.sup/interval.inf
    return sp.Interval(1, upper, True, not closed) if orientation == 1 else sp.Interval(1/upper, 1, not closed, True)


def _structure(goal):
    if not relevant(goal):
        raise ValueError('abstract_mono.goal_unsupported')
    relation = _relation(goal)
    spec = FAMILIES[relation['family']]
    interval, declared, relation_domain = [_set(goal[k]) for k in ('input_domain', 'declared_domain', 'relation_domain')]
    if relation_domain != spec['domain'] or declared != relation_domain:
        raise ValueError('abstract_mono.relation_domain_not_covered')
    if interval.is_subset(declared) is not True or interval.measure == 0:
        raise ValueError('abstract_mono.interval_outside_domain')
    sign, sign_domain, positive = _sign(goal, spec['output'])
    if sign_domain.is_subset(declared) is not True:
        raise ValueError('abstract_mono.sign_domain_outside_domain')
    if spec['output'] == 'product' and not (positive or relation['nonzero_from_relation']):
        raise ValueError('abstract_mono.nonzero_witness_required')
    unit = sp.S.Zero if spec['input'] == 'sum' else sp.S.One
    if sign_domain.contains(unit) is sp.true:
        raise ValueError('abstract_mono.conditions_conflict')
    for orientation in (1, -1):
        bounds = key_range(interval, spec['input'], orientation)
        if bounds.is_subset(sign_domain) is True:
            break
    else:
        raise ValueError('abstract_mono.sign_range_not_covered')
    delta_sign = sign if orientation == 1 else ('<' if sign == '>' else '>')
    direction = 'increasing' if delta_sign == '>' else 'decreasing'
    if goal['kind'] == 'prove_monotonicity_on_interval' and goal.get('direction') != direction:
        raise ValueError('abstract_mono.requested_direction_conflict')
    return {'relation_family': relation['family'], 'normalization': relation, **spec,
            'interval': interval, 'relation_domain': relation_domain, 'sign_relation': sign,
            'sign_domain': sign_domain, 'orientation': orientation, 'key_range': bounds,
            'direction': direction, 'delta_sign': delta_sign, 'unit': unit,
            'positive_witness': 'sign' if positive else 'relation'}


def describe(goal, target_ref, entries):
    base = {'version': VERSION, 'family': 'abstract', 'target_ref': target_ref,
            'source': deepcopy(goal), 'source_refs': [target_ref], 'given_definitions': deepcopy(list(entries))}
    try:
        if entries:
            raise ValueError('abstract_mono.extra_facts_unsupported')
        structure = _structure(goal)
    except (ValueError, NotationError, KeyError, IndexError, TypeError) as exc:
        reason = str(exc) if str(exc).startswith('abstract_mono.') else 'abstract_mono.source_unreadable'
        return {**base, 'structure_supported': False, 'reason': reason}
    return {**base, 'structure_supported': True, 'relation_family': structure['relation_family'],
            **{k: deepcopy(goal[k]) for k in ('function', 'variable', 'relation', 'relation_variables', 'relation_domain')},
            'interval': goal['input_domain'], 'sign_variable': goal['sign_condition']['variable'],
            'sign_domain': goal['sign_condition']['domain'], 'sign_statement': goal['sign_condition']['statement'],
            'sign_relation': structure['sign_relation']}


def construction(desc):
    s = _structure(desc['source'])
    x1, x2 = pair_symbols(desc['source'])
    anchor, target = (x1, x2) if s['orientation'] == 1 else (x2, x1)
    key = target-anchor if s['input'] == 'sum' else target/anchor
    composite = anchor+key if s['input'] == 'sum' else anchor*key
    certificate = None
    if s['output'] == 'product':
        certificate = {'witness': s['positive_witness'], 'unit': s['unit'], 'unit_value': sp.S.One,
                       'square_input': anchor/2 if s['input'] == 'sum' else sp.sqrt(anchor)}
    return {'kind': desc['source']['kind'], 'family': 'abstract', 'relation_family': s['relation_family'],
            'interval': s['interval'], 'pair': [x1, x2], 'orientation': s['orientation'],
            'normalization': deepcopy(s['normalization']), 'substitution': {'u': anchor, 'v': key},
            'key': key, 'composite': composite, 'positive_certificate': certificate}


def solve(desc):
    if not desc.get('structure_supported'):
        raise ValueError(desc.get('reason', 'abstract_mono.unsupported'))
    s = _structure(desc['source'])
    return {**construction(desc), 'key_range': s['key_range'], 'sign': s['delta_sign'], 'direction': s['direction']}


def verify_construction(desc, model):
    """Recheck the symbolic substitution and positivity certificate, not passed flags."""
    try:
        s = _structure(desc['source'])
        x1, x2 = pair_symbols(desc['source'])
        if (model['family'] != 'abstract' or model['kind'] != desc['source']['kind'] or model['relation_family'] != s['relation_family']
                or model['interval'] != s['interval'] or model['pair'] != [x1, x2]
                or model['orientation'] != s['orientation'] or model['normalization'] != s['normalization']):
            return False
        anchor, target = (x1, x2) if model['orientation'] == 1 else (x2, x1)
        key = model['key']
        composite = anchor+key if s['input'] == 'sum' else anchor*key
        if model['substitution'] != {'u': anchor, 'v': key} or sp.simplify(composite-target) != 0 or model['composite'] != composite:
            return False
        # Replace an arbitrary ordered pair by a, a+h, h>0. This verifies the
        # sign of the constructed input without making assumptions about f.
        a = sp.Symbol('_a', positive=True) if s['input'] == 'product' else sp.Symbol('_a', real=True)
        h = sp.Symbol('_h', positive=True)
        gap = sp.simplify((key-s['unit']).subs({x1: a, x2: a+h}, simultaneous=True) * model['orientation'])
        if gap.is_positive is not True:
            return False
        if s['output'] == 'sum':
            return model['positive_certificate'] is None
        proof = model['positive_certificate']
        if not proof or proof['witness'] != s['positive_witness'] or proof['unit'] != s['unit'] or proof['unit_value'] != 1:
            return False
        # A nonzero value gives f(unit)=1, hence f(t)f(inverse(t))=1.
        # f(t)=f(t/2)^2 (or f(sqrt(t))^2) is therefore strictly positive.
        preimage = proof['square_input']
        double = 2*preimage if s['input'] == 'sum' else preimage**2
        return sp.simplify(double-anchor) == 0 and preimage == (anchor/2 if s['input'] == 'sum' else sp.sqrt(anchor))
    except (ValueError, NotationError, KeyError, IndexError, TypeError, AttributeError):
        return False


def verify(desc, model):
    if not isinstance(model, dict) or not verify_construction(desc, model):
        return False
    s = _structure(desc['source'])
    return (model.get('key_range') == key_range(s['interval'], s['input'], model['orientation'])
            and model['key_range'].is_subset(s['sign_domain']) is True
            and model.get('sign') == s['delta_sign'] and model.get('direction') == s['direction'])
