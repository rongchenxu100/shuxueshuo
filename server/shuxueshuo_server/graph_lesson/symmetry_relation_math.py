"""FP-T5: source-bound rational reflections, separate from T3's opposite-input route.

Descriptors contain original syntax only. Mathematics reconstructs each directed
reflection from that syntax; quantified ranges are never promoted to graph facts.
"""
from copy import deepcopy

import sympy as sp

from . import symmetry_linear
from .parity_extension_math import (
    ARGUMENT,
    _replace,
    region,
    rule_expression,
    undefined_on,
)
from .parity_parameter_math import _budget
from .symmetry_value_math import _combine, _constant, _equation, _function_calls, linear

VERSION = 'function-symmetry/general-v1'
X = sp.Symbol('x', real=True)


def rational(v):
    v = sp.cancel(v)
    if not v.is_Rational or max(abs(int(v.p)).bit_length(), int(v.q).bit_length()) > 128:
        raise ValueError('symmetry.rational_budget')
    return v


def image(domain, slope, offset):
    if domain == sp.S.EmptySet:
        return domain
    if domain == sp.S.Reals:
        return domain
    if isinstance(domain, sp.Union):
        return sp.Union(*(image(p, slope, offset) for p in domain.args))
    if isinstance(domain, sp.FiniteSet):
        return sp.FiniteSet(*(slope*x+offset for x in domain))
    if isinstance(domain, sp.Interval):
        if slope > 0:
            return sp.Interval(slope*domain.start+offset, slope*domain.end+offset, domain.left_open, domain.right_open)
        return sp.Interval(slope*domain.end+offset, slope*domain.start+offset, domain.right_open, domain.left_open)
    raise ValueError('symmetry.domain_unsupported')


def domain_set(ast):
    if ast is None:
        raise ValueError('symmetry.declared_domain_required')
    # Interval notation represents an interval of positive length, not a singleton.
    def check(node):
        if isinstance(node, list):
            if node[:1] == ['interval']:
                a, b = (rule_expression(c, X) if c[0] != 'infinity' else c[1]*sp.oo for c in node[3:5])
                if not a < b:
                    raise ValueError('symmetry.invalid_interval')
            for child in node[1:]:
                check(child)
    check(ast)
    value = region(ast)
    parts = value.args if isinstance(value, sp.Union) else [value]
    intervals = sum(isinstance(p, sp.Interval) for p in parts)
    points = sum(len(p) for p in parts if isinstance(p, sp.FiniteSet))
    if intervals > 8 or points > 16:
        raise ValueError('symmetry.domain_budget')
    for p in parts:
        if p == sp.S.Reals:
            continue
        ends = (p.start, p.end) if isinstance(p, sp.Interval) else list(p) if isinstance(p, sp.FiniteSet) else []
        if not ends:
            raise ValueError('symmetry.empty_or_unsupported_domain')
        for e in ends:
            if e not in (-sp.oo, sp.oo):
                rational(e)
    return value


def owned(goal, entries):
    """Ownership precedes admission, including unsupported general-symmetry facts."""
    if goal.get('kind') not in ('find_value', 'finite_sum'):
        return False
    if any(r['ast'][0] == 'function_graph_symmetry' for r in entries):
        return True
    if goal['kind'] == 'finite_sum' and any(r['ast'][0] == 'function_parity' for r in entries):
        return True
    for r in entries:
        ast = r['ast']
        if ast[0] == 'quantifier' and _function_calls(ast):
            if not any(r['ast'][0] == 'function_parity' for r in entries):
                return True
            bound = ['bound', ast[2]]
            calls = _function_calls(ast[4])
            if any(c[2] not in (bound, ['neg', bound]) for c in calls):
                return True
    return False


def describe(goal, goal_ast, target_ref, entries, *, candidate=None):
    if not owned(goal, entries):
        return None
    desc = {'source': deepcopy(goal), 'target_ref': target_ref, 'structure_version': VERSION,
            'source_refs': [target_ref, *[r['source_ref'] for r in entries]],
            'given_entries': [{k: deepcopy(r[k]) for k in ('source_ref', 'expression', 'ast')} for r in entries],
            'goal_ast': deepcopy(goal_ast), 'structure_supported': False, 'reason': ''}
    try:
        calls = _function_calls(goal_ast['target'])
        refs = {c[1][1] for c in calls}
        refs |= {r['ast'][1][1] for r in entries if r['ast'][0] in ('function_parity', 'function_graph_symmetry')}
        if len(refs) != 1:
            raise ValueError('symmetry.single_function_required')
        ref = next(iter(refs))
        name = ref.rsplit(':', 1)[-1]
        desc.update(function=name, function_ref=ref, variable='x', domain_ast=None,
                    domain_source_refs=[], relations=[], value_equations=[])
        for r in entries:
            ast = r['ast']
            _budget(ast)
            if ast[0] == '=' and ast[1][:2] == ['call', 'Dom'] and ast[1][2] == ['ref', ref, 'function']:
                if desc['domain_ast'] is not None and desc['domain_ast'] != ast[2]:
                    raise ValueError('symmetry.conflicting_domains')
                desc['domain_ast'] = deepcopy(ast[2])
                desc['domain_source_refs'].append(r['source_ref'])
            elif ast[0] in ('function_parity', 'function_graph_symmetry', 'quantifier'):
                desc['relations'].append({k: deepcopy(r[k]) for k in ('source_ref', 'expression', 'ast')})
            elif ast[0] == '=' and _function_calls(ast):
                desc['value_equations'].append({k: deepcopy(r[k]) for k in ('source_ref', 'expression', 'ast')})
            else:
                raise ValueError('symmetry.additional_condition_unsupported')
        if len(desc['value_equations']) > 32:
            raise ValueError('symmetry.condition_budget')
        _budget(goal_ast['target'])
        if 'relation' in goal or 'additional_relations' in goal:
            raise ValueError('symmetry.goal_relation_unsupported')
        # Parse/check only; evaluating a target belongs to the method execution.
        edges = reflections(desc)
        if not edges:
            raise ValueError('symmetry.reflection_required')
        for row in desc['value_equations']:
            _equation(row['ast'], [name], X)
        target_terms(desc)
        if candidate is not None:
            from .stage_two.fragments import _scope_ranges
            from .stage_two.symmetry_relation_surface import source_spans
            if source_spans(candidate, target_ref, _scope_ranges(candidate, target_ref), desc) is None:
                raise ValueError('symmetry.source_not_bound')
        desc['structure_supported'] = True
    except (ValueError, TypeError, KeyError, IndexError, NotImplementedError) as exc:
        desc['reason'] = str(exc)
    return desc


def reflections(desc):
    domain = domain_set(desc['domain_ast'])
    out = []
    for row in desc['relations']:
        ast, ref = row['ast'], row['source_ref']
        kind = ast[0]
        if kind in ('function_parity', 'function_graph_symmetry'):
            if ast[1] != ['ref', desc['function_ref'], 'function']:
                raise ValueError('symmetry.other_function')
            if kind == 'function_parity':
                if ast[2] not in ('odd', 'even', 'both'):
                    raise ValueError('symmetry.exclusive_parity_unsupported')
                signs = [1, -1] if ast[2] == 'both' else [-1 if ast[2] == 'odd' else 1]
                a, c = sp.S.Zero, sp.S.Zero
            else:
                a = rational(_constant(ast[3], X))
                signs = [1 if ast[2] == 'axis' else -1]
                c = sp.S.Zero if ast[2] == 'axis' else 2*rational(_constant(ast[4], X))
            if image(domain, -1, 2*a) != domain:
                raise ValueError('symmetry.domain_not_closed')
            for sign in signs:
                out.append({'a': a, 'sign': sign, 'offset': c, 'scope': domain,
                            'source_ref': ref, 'whole': True})
        elif kind == 'quantifier' and ast[1] == '∀' and ast[4][0] == '=':
            body = _replace(ast[4], ['bound', ast[2]], ARGUMENT)
            scope_ast = _replace(ast[3], ['call', 'Dom', ['ref', desc['function_ref'], 'function']], desc['domain_ast'])
            scope = domain_set(scope_ast)
            def scalar(node, scope=scope):
                # Check the printed tree even if its value later cancels or is
                # multiplied by zero. The quantifier cannot acquire new inputs.
                if undefined_on(node, None, X, scope):
                    raise ValueError('symmetry.undefined_on_scope')
                return sp.expand(rule_expression(node, X))
            def read(call, scope=scope):
                if call[1] != ['ref', desc['function_ref'], 'function']:
                    raise ValueError('symmetry.other_function')
                arg = scalar(call[2])
                if not arg.is_polynomial(X):
                    raise ValueError('symmetry.affine_reflection_required')
                poly = sp.Poly(arg, X)
                if poly.degree() != 1:
                    raise ValueError('symmetry.affine_reflection_required')
                slope, offset = rational(poly.nth(1)), rational(poly.nth(0))
                if image(scope, slope, offset).is_subset(domain) is not True:
                    raise ValueError('symmetry.input_outside_domain')
                return slope, offset
            sides = [_combine(read, side, [desc['function']], X, scalar) for side in body[1:]]
            terms, offset = dict(sides[0][0]), sp.expand(sides[1][1]-sides[0][1])
            for k, v in sides[1][0].items():
                terms[k] = terms.get(k, 0)-v
            terms = {k: v for k, v in terms.items() if v != 0}
            if len(terms) != 2 or offset.free_symbols:
                raise ValueError('symmetry.reflection_equation_required')
            (u, ku), (v, kv) = sorted(terms.items(), reverse=True)
            if u[0] != -v[0]:
                raise ValueError('symmetry.reflection_equation_required')
            a, sign, c = rational((u[1]+v[1])/2), rational(-ku/kv), rational(offset/kv)
            if sign not in (-1, 1):
                raise ValueError('symmetry.sign_required')
            source = image(scope, *u)
            if source.is_subset(domain) is not True or image(source, -1, 2*a).is_subset(domain) is not True:
                raise ValueError('symmetry.input_outside_domain')
            whole = source == domain and image(source, -1, 2*a) == domain
            out.append({'a': a, 'sign': sign, 'offset': c, 'scope': source, 'source_ref': ref, 'whole': whole})
        else:
            raise ValueError('symmetry.relation_unsupported')
    unique = {(e['a'], e['sign'], e['offset'], e['scope']) for e in out}
    if len(unique) > 2:
        raise ValueError('symmetry.generator_budget')
    return out


def _substitute(ast, key, value):
    if ast == key:
        from .symmetry_value_math import _literal
        return _literal(value)
    return [_substitute(a, key, value) if isinstance(a, list) else a for a in ast]


def _inputs(ast, desc):
    # Preserve definedness even when a call cancels algebraically or has a zero coefficient.
    out = []
    domain = domain_set(desc['domain_ast'])
    for call in _function_calls(ast):
        if call[1] != ['ref', desc['function_ref'], 'function']:
            raise ValueError('symmetry.other_function')
        point = rational(_constant(call[2], X))
        if domain.contains(point) is not sp.true:
            raise ValueError('symmetry.input_outside_domain')
        out.append(point)
    return out


def target_terms(desc):
    """Preserve every summand's index/multiplicity; the 32 limit applies after orbit reduction."""
    goal = desc['goal_ast']
    blocks = goal['terms'] if goal['kind'] == 'finite_sum' else [{'target': goal['target']}]
    out, count = [], 0
    for block_id, block in enumerate(blocks):
        indices = range(block['lower'], block['upper']+1) if 'index' in block else [None]
        if 'index' in block and (block['lower'] > block['upper'] or max(abs(block['lower']), abs(block['upper'])) > 10000):
            raise ValueError('symmetry.sum_index_budget')
        count += len(indices)
        if count > 4096:
            raise ValueError('symmetry.sum_budget')
        for index in indices:
            ast = block['target'] if index is None else _substitute(block['target'], block['index'], sp.Integer(index))
            inputs = _inputs(ast, desc)
            terms, c = linear(ast, [desc['function']], X)
            for (_, arg), coeff in terms.items():
                rational(arg)
                rational(coeff)
            out.append({'block': block_id, 'index': index, 'terms': terms, 'inputs': inputs, 'constant': rational(c)})
    if goal['kind'] != 'finite_sum' and len({point for row in out for point in row['inputs']}) > 32:
        raise ValueError('symmetry.call_budget')
    return out


def system(desc):
    from .function_symmetry_iteration import Orbit
    edges, domain = reflections(desc), domain_set(desc['domain_ast'])
    orbit = Orbit(edges, domain)
    originals = target_terms(desc)
    equations = [_equation(r['ast'], [desc['function']], X) for r in desc['value_equations']]
    given_inputs = {c for r in desc['value_equations'] for c in _inputs(r['ast'], desc)}
    for terms, rhs in equations:
        rational(rhs)
        for k in terms.values():
            rational(k)
    used = sorted({c for row in originals for c in row['inputs']} | given_inputs)
    maps = {c: orbit.reduce(rational(c)) for c in used}
    bases = sorted({m['base'] for m in maps.values()})
    if len(bases) > 32:
        raise ValueError('symmetry.unknown_budget')
    def reduce(terms, constant):
        vector = [sp.S.Zero]*len(bases)
        for (_, c), k in terms.items():
            m = maps[c]
            vector[bases.index(m['base'])] += k*m['factor']
            constant += k*m['offset']
        return vector, constant
    rows, rhs = [], []
    for terms, b in equations:
        v, d = reduce(terms, sp.S.Zero)
        rows.append(v)
        rhs.append(b-d)
    for base in bases:
        for k, v in orbit.constraints(base):
            row = [sp.S.Zero]*len(bases)
            row[bases.index(base)] = k
            rows.append(row)
            rhs.append(v)
    target, constant, groups = [sp.S.Zero]*len(bases), sp.S.Zero, []
    for original in originals:
        v, d = reduce(original['terms'], original['constant'])
        target = [a+b for a, b in zip(target, v)]
        constant += d
        groups.append({'block': original['block'], 'index': original['index'], 'coefficients': v, 'constant': d})
    return {'version': VERSION, 'description': deepcopy(desc), 'edges': edges, 'domain': domain,
            'maps': [{'input': c, **m} for c, m in maps.items()], 'bases': bases, 'rows': rows, 'rhs': rhs,
            'target': target, 'constant': constant, 'groups': groups, 'extension': orbit.extension}


def solve(desc):
    model = system(desc)
    model['proof'] = symmetry_linear.certificate(model['rows'], len(model['bases']), model['rhs'], model['target'], model['constant'])
    return model


def verify(desc, model):
    """Replay original relations, domains, paths and sum indices, then check the supplied linear proof."""
    try:
        actual = system(desc)
        if set(model) != {*actual, 'proof'} or any(model[k] != v for k, v in actual.items()):
            return False
        return symmetry_linear.verify(actual['rows'], len(actual['bases']), actual['rhs'], actual['target'], actual['constant'], model['proof'])
    except (ValueError, TypeError, KeyError, IndexError, NotImplementedError):
        return False
