"""Exact, bounded extrema certificates. No problem IDs or numeric answer tables.

Parameter cases are sets obtained from endpoint/vertex inequalities, not samples.
The source reader retains every denominator/root obligation before simplification.
"""
from copy import deepcopy
from functools import lru_cache

import sympy as sp

from ..problem_understanding.notation_parser import definition, parse
from .function_monotonicity import components


def scalar(ast, names=None, obligations=None, depth=0):
    names = names or {}
    obligations = obligations if obligations is not None else []
    if depth > 20:
        raise ValueError('extremum.expression_budget')
    read = lambda a: scalar(a, names, obligations, depth+1)
    op = ast[0]
    if op == 'number':
        value = sp.Rational(ast[1])
        if max(abs(value.p), value.q) > 10**9:
            raise ValueError('extremum.coefficient_budget')
        return value
    if op == 'name':
        return names.get(ast[1], sp.Symbol(ast[1], real=True))
    if op in ('infinity', 'infty'):
        return ast[1]*sp.oo
    if op == 'neg':
        return -read(ast[1])
    if ast[:2] == ['call', 'sqrt']:
        radicand = read(ast[2])
        obligations.append(sp.Ge(radicand, 0))
        return sp.sqrt(radicand)
    if op in ('+', '-', '*', '/', '^'):
        a, b = read(ast[1]), read(ast[2])
        if op == '/':
            obligations.append(sp.Ne(b, 0))
        if op == '^' and (not b.is_Integer or not 0 <= b <= 3):
            raise ValueError('extremum.power_budget')
        return {'+': lambda: a+b, '-': lambda: a-b, '*': lambda: a*b,
                '/': lambda: a/b, '^': lambda: a**b}[op]()
    raise ValueError('extremum.scalar_structure')


def relation(ast, names=None):
    if ast[0] in ('and', 'or'):
        return {'and': sp.And, 'or': sp.Or}[ast[0]](*(relation(v, names) for v in ast[1:]))
    if ast[0] not in ('=', '!=', '<', '<=', '>', '>='):
        raise ValueError('extremum.relation_required')
    obligations = []
    a, b = (scalar(v, names, obligations) for v in ast[1:])
    if any(v is not sp.S.true for v in obligations):
        raise ValueError('extremum.conditional_relation')
    return {'=': sp.Eq, '!=': sp.Ne, '<': sp.Lt, '<=': sp.Le, '>': sp.Gt, '>=': sp.Ge}[ast[0]](a, b)


@lru_cache(maxsize=2048)
def condition_set(condition, variable):
    """One real parameter, exact rational/algebraic polynomial boundaries."""
    if condition in (True, sp.S.true):
        return sp.S.Reals
    if condition in (False, sp.S.false):
        return sp.S.EmptySet
    if isinstance(condition, sp.And):
        return sp.Intersection(*(condition_set(c, variable) for c in condition.args))
    if isinstance(condition, sp.Or):
        return sp.Union(*(condition_set(c, variable) for c in condition.args))
    if isinstance(condition, sp.Not):
        return sp.S.Reals-condition_set(condition.args[0], variable)
    if condition.free_symbols - {variable}:
        raise ValueError('extremum.additional_parameter')
    diff = sp.cancel(condition.lhs-condition.rhs)
    num, den = sp.fraction(diff)
    if max(sp.Poly(num, variable).degree(), sp.Poly(den, variable).degree()) > 4:
        raise ValueError('extremum.parameter_degree')
    if isinstance(condition, sp.Equality):
        value = sp.solveset(diff, variable, domain=sp.S.Reals)
    elif isinstance(condition, sp.Unequality):
        value = sp.S.Reals-sp.solveset(diff, variable, domain=sp.S.Reals)
    else:
        value = sp.solve_univariate_inequality(condition, variable, relational=False)
    if not isinstance(value, (sp.Interval, sp.Union, sp.FiniteSet, type(sp.S.Reals), type(sp.S.EmptySet))):
        raise ValueError('extremum.unresolved_condition')
    return value


def domain(ast, names=None):
    if ast == ['real']:
        return sp.S.Reals
    if ast[0] == 'interval':
        return sp.Interval(scalar(ast[3], names), scalar(ast[4], names), not ast[1], not ast[2])
    if ast[0] == 'tuple' and len(ast) == 3:
        # Here the caller has explicitly supplied an input-domain field.
        return sp.Interval.open(scalar(ast[1], names), scalar(ast[2], names))
    if ast[0] == 'set':
        return sp.FiniteSet(*(scalar(a, names) for a in ast[1:]))
    if ast[0] == 'set_builder' and ast[2] == ['real']:
        variable = sp.Symbol(ast[1], real=True)
        result = condition_set(relation(ast[3]), variable)
        if isinstance(result, (sp.Interval, sp.FiniteSet)) and not result.free_symbols:
            return result
    raise ValueError('extremum.interval_required')


def raw_sources(goal, entries):
    functions, facts, refs = {}, [], []
    for row in entries:
        text = row['expression']
        ast = definition(text)
        if ast[0] == 'function_definition':
            if ast[1] in functions:
                raise ValueError('extremum.duplicate_function')
            functions[ast[1]] = {'variable': ast[2], 'ast': ast[3], 'source': text}
        else:
            facts.append(parse(text))
        refs.append(row['source_ref'])
    return functions, facts, refs


def relevant(goal, entries):
    if goal.get('kind') == 'find_range' and 'object' in goal:
        return goal.get('answer_request', {}).get('kind') == 'extremum'
    if goal.get('kind') != 'find_range' or 'symbol' not in goal:
        return False
    for row in entries:
        a = parse(row['expression'])
        if a[0] == 'quantifier' and a[4][0] == 'quantifier':
            return True
        if a[0] == '=' and any(v[0] == 'extremum' for v in a[1:]):
            return True
    return False


def routed_description(goal, target_ref, entries):
    """Use T2 for supported extrema, preserving existing range solvers otherwise.

    Parameter tasks retain their unsupported diagnostics; only direct extrema
    have a pre-existing function-range path to fall back to.
    """
    from . import recurrence_extremum
    if recurrence_extremum.relevant(goal, entries):
        return recurrence_extremum.describe(goal, target_ref, entries)
    if not relevant(goal, entries):
        return None
    result = describe(goal, target_ref, entries)
    if 'object' in goal and not result['structure_supported']:
        return None
    return result


def family(expr, x, parameter=None):
    allowed = {x} | ({parameter} if parameter else set())
    if expr.free_symbols-allowed or sp.count_ops(expr) > 80:
        raise ValueError('extremum.expression_budget')
    if expr.is_polynomial(x):
        p = sp.Poly(expr, x)
        if p.degree() <= 2:
            if parameter and p.degree() == 2 and p.nth(2).has(parameter):
                raise ValueError('extremum.fixed_quadratic_curvature_required')
            return 'polynomial'
        if p.degree() == 3 and p.nth(1) == p.nth(2) == 0 and not p.nth(3).free_symbols:
            return 'cubic'
    numerator, denominator = sp.fraction(sp.cancel(expr))
    if numerator.is_polynomial(x) and denominator.is_polynomial(x):
        if sp.degree(numerator, x) <= 1 and sp.degree(denominator, x) == 1 and not parameter:
            return 'fraction'
        remainder = sp.expand(expr)
        if sp.simplify(remainder-(remainder.coeff(x)*x+remainder.coeff(x, -1)/x+remainder.coeff(x, 0))) == 0:
            if not (remainder.coeff(x).free_symbols or remainder.coeff(x, -1).free_symbols):
                return 'reciprocal_sum'
    roots = [v for v in expr.atoms(sp.Pow) if v.exp == sp.S.Half]
    if not parameter and len(roots) == 1:
        root = roots[0]
        rest = sp.expand(expr-root*expr.coeff(root))
        if sp.degree(root.base, x) == 1 and rest.is_polynomial(x) and sp.degree(rest, x) <= 2 and not expr.coeff(root).free_symbols:
            return 'root_sum'
    raise ValueError('extremum.unsupported_family')


def pieces(fn, restriction=sp.S.Reals, parameter=None):
    x = sp.Symbol(fn['variable'], real=True)
    ast = fn['ast']
    raw = list(zip(ast[2::2], ast[3::2], strict=True)) if ast[:2] == ['call', 'piecewise'] else [(ast, None)]
    result, covered = [], sp.S.EmptySet
    for body, predicate in raw:
        obligations = []
        expr = sp.cancel(scalar(body, obligations=obligations))
        kind = family(expr, x, parameter)
        region = sp.S.Reals if predicate is None else condition_set(relation(predicate), x)
        if region & covered != sp.S.EmptySet:
            raise ValueError('extremum.overlapping_pieces')
        covered |= region
        natural = sp.S.Reals
        for condition in obligations:
            if parameter and condition.has(parameter):
                raise ValueError('extremum.parameter_domain_obligation')
            natural &= condition_set(condition, x)
        region &= natural & restriction
        if region != sp.S.EmptySet:
            result.append({'expression': expr, 'variable': x, 'domain': region, 'family': kind,
                           'obligations': obligations, 'natural_domain': natural, 'source_ast': deepcopy(body)})
    return result


def describe(goal, target_ref, entries):
    desc = {'source': deepcopy(goal), 'target_ref': target_ref, 'given_definitions': deepcopy(entries),
            'source_refs': [target_ref, *[r['source_ref'] for r in entries]],
            'structure_supported': False, 'reason': '', 'task': ''}
    try:
        funcs, facts, _ = raw_sources(goal, entries)
        if goal.get('kind') != 'find_range':
            raise ValueError('extremum.goal_required')
        if 'object' in goal:
            if goal.get('answer_request', {}).get('quantity') not in ('maximum', 'minimum'):
                raise ValueError('extremum.minimum_or_maximum_required')
            fn = funcs[goal['object']]
            if len(funcs) != 1:
                raise ValueError('extremum.unused_function')
            desc.update(task='direct', function=goal['object'], quantity=goal['answer_request']['quantity'])
            restriction = domain(parse(goal.get('input_domain', 'ℝ')))
            for fact in facts:
                if fact[:2] == ['∈', ['name', fn['variable']]]:
                    restriction &= domain(fact[2])
                elif fact[0] == '=' and fact[1] == ['call', 'Dom', ['name', goal['object']]]:
                    declared = domain(fact[2])
                    natural = sp.Union(*(p['domain'] for p in pieces(fn)))
                    if declared-natural != sp.S.EmptySet:
                        raise ValueError('extremum.declared_domain_conflict')
                    restriction &= declared
                else:
                    raise ValueError('extremum.unprocessed_fact')
            rows = pieces(fn, restriction)
            desc['restriction'] = str(restriction)
            if not rows:
                raise ValueError('extremum.empty_domain')
            if len(rows) != 1 or rows[0]['family'] not in ('polynomial', 'fraction', 'root_sum'):
                raise ValueError('extremum.direct_family')
        else:
            parameter = sp.Symbol(goal['symbol'], real=True)
            special = [f for f in facts if f[0] == 'quantifier' or f[0] == '=' and any(v[0] == 'extremum' for v in f[1:])]
            if len(special) != 1:
                raise ValueError('extremum.single_condition_required')
            s = special[0]
            def used_functions(ast):
                if not ast:
                    return set()
                used = {ast[1]} if ast[0] == 'call' and ast[1] in funcs else set()
                return used.union(*(used_functions(v) for v in ast[1:] if isinstance(v, list)))
            if used_functions(s) != set(funcs):
                raise ValueError('extremum.unused_function')
            desc.update(task='quantified' if s[0] == 'quantifier' else 'specified', parameter=goal['symbol'])
            for fn in funcs.values():
                pieces(fn, parameter=parameter)
            for f in facts:
                if f is not s:
                    if f == ['∈', ['name', goal['symbol']], ['real']]:
                        continue
                    if f[0] == '=' and f[1][0] == 'name' and f[2][0] in ('interval', 'set', 'tuple', 'set_builder'):
                        if f[2][0] == 'set_builder':
                            domain(f[2])
                        continue
                    condition_set(relation(f), parameter)
            if s[0] == 'quantifier' and (s[1] != '∀' or s[4][:2] != ['quantifier', '∃'] or s[2] == s[4][2]):
                raise ValueError('extremum.independent_forall_exists_required')
        desc['structure_supported'] = True
    except (ValueError, KeyError, TypeError, NotImplementedError, sp.PolynomialError) as exc:
        desc['reason'] = str(exc) or 'extremum.unsupported'
    return desc


def operation_direction(operation, directions, coefficient=None, sign=None):
    """Public skill: only sufficient strict-order rules; unknown is not nonmonotone."""
    if any(d not in (-1, 0, 1) for d in directions):
        raise ValueError('extremum.direction_required')
    if operation == 'shift':
        return directions[0]
    if operation == 'scale':
        if coefficient is None or coefficient.is_real is not True or coefficient.free_symbols:
            raise ValueError('extremum.fixed_scale_required')
        return directions[0]*int(sp.sign(coefficient))
    if operation == 'reciprocal':
        if sign not in ('positive', 'negative'):
            raise ValueError('extremum.reciprocal_one_sign_required')
        return -directions[0]
    if operation in ('sum', 'difference'):
        ds = directions if operation == 'sum' else [directions[0], -directions[1]]
        nonzero = {d for d in ds if d}
        if len(nonzero) <= 1:
            return next(iter(nonzero), 0)
    raise ValueError('extremum.direction_not_determined')


def decomposition(expr, x, kind):
    if kind == 'fraction':
        n, d = sp.fraction(sp.cancel(expr))
        quotient, remainder = sp.div(n, d, x)
        return [d], {'kind': 'fraction', 'offset': quotient, 'scale': remainder, 'denominator': d}
    if kind == 'root_sum':
        root, = [r for r in expr.atoms(sp.Pow) if r.exp == sp.S.Half]
        coefficient = expr.coeff(root)
        return [root, sp.expand(expr-coefficient*root)], {'kind': 'sum', 'root_scale': coefficient}
    return [expr], None


def numeric_model(desc):
    from .function_monotonicity import describe as describe_mono, solve as solve_mono
    from .stage_three.premises import math_text
    funcs, facts, _ = raw_sources(desc['source'], desc['given_definitions'])
    fn = funcs[desc['function']]
    x = sp.Symbol(fn['variable'], real=True)
    restriction = domain(parse(desc['source'].get('input_domain', 'ℝ')))
    for f in facts:
        restriction &= domain(f[2])
    row, = pieces(fn, restriction)
    expr, region, kind = row['expression'], row['domain'], row['family']
    child_expressions, operation = decomposition(expr, x, kind)
    children = []
    # Every child is a genuine M2 goal on the parent's effective input set.
    for child in child_expressions:
        for interval in components(region):
            text = ('(' if interval.left_open else '[')+','.join(math_text(v).replace('oo', '∞') for v in (interval.inf, interval.sup))+(')' if interval.right_open else ']')
            g = {'kind': 'find_monotonic_intervals', 'expression': math_text(child), 'variable': str(x),
                 'direction': 'both', 'input_domain': text, 'domain_role': 'restriction'}
            d = describe_mono(g, desc['target_ref'])
            children.append({'description': d, 'model': solve_mono(d), 'expression': child})
    cells = []
    for interval in components(region):
        cuts = sorted({interval.inf, interval.sup, *[v for c in children for r in c['model']['partition']
                       for v in (r['interval'].inf, r['interval'].sup) if interval.inf < v < interval.sup]})
        for a, b in zip(cuts, cuts[1:]):
            cell = sp.Interval(a, b, a not in region, b not in region)
            ds = []
            for child in child_expressions:
                rows = [r for c in children if c['expression'] == child for r in c['model']['partition']
                        if sp.Interval.open(a, b).is_subset(r['interval'])]
                if len(rows) != 1:
                    raise ValueError('extremum.child_partition')
                ds.append(rows[0]['direction'])
            stages = []
            direction = ds[0]
            if kind == 'fraction':
                d = operation['denominator']
                positive = condition_set(sp.Gt(d, 0), x)
                negative = condition_set(sp.Lt(d, 0), x)
                sign = 'positive' if cell.is_subset(positive) else 'negative' if cell.is_subset(negative) else None
                for op, coefficient in [('reciprocal', None), ('scale', operation['scale']), ('shift', operation['offset'])]:
                    after = operation_direction(op, [direction], coefficient, sign)
                    stages.append({'operation': op, 'before': direction, 'after': after, 'coefficient': coefficient, 'sign': sign})
                    direction = after
            elif kind == 'root_sum':
                ds[0] = operation_direction('scale', [ds[0]], operation['root_scale'])
                direction = operation_direction('sum', ds)
                stages.append({'operation': 'sum', 'inputs': ds, 'after': direction})
            cells.append({'interval': cell, 'direction': direction, 'operations': stages})
    candidates = []
    for cell in cells:
        r = cell['interval']
        for p, side in ((r.inf, '+'), (r.sup, '-')):
            attained = p.is_finite is True and p in region
            value = expr.subs(x, p) if attained else sp.limit(expr, x, p, dir=side)
            candidates.append({'point': p, 'value': sp.simplify(value), 'attained': attained})
        if cell['direction'] == 0:
            p = (r.inf+r.sup)/2 if r.inf.is_finite and r.sup.is_finite else r.sup-1 if r.sup.is_finite else r.inf+1 if r.inf.is_finite else sp.S.Zero
            candidates.append({'point': p, 'value': sp.simplify(expr.subs(x, p)), 'attained': True})
    if isinstance(region, sp.FiniteSet):
        candidates.extend({'point': p, 'value': sp.simplify(expr.subs(x, p)), 'attained': True} for p in region)
    value = (max if desc['quantity'] == 'maximum' else min)(c['value'] for c in candidates)
    witnesses = list(dict.fromkeys(c['point'] for c in candidates if c['attained'] and c['value'] == value))
    return {'task': 'direct', 'expression': expr, 'variable': x, 'domain': region, 'family': kind,
            'operation': operation, 'children': children, 'interval_steps': cells, 'candidates': candidates,
            'quantity': desc['quantity'], 'value': value, 'attained': bool(witnesses), 'witnesses': witnesses}


def verify_numeric(desc, model):
    """Check original global bound and equality witnesses independently of candidate selection."""
    try:
        funcs, facts, _ = raw_sources(desc['source'], desc['given_definitions'])
        restriction = domain(parse(desc['source'].get('input_domain', 'ℝ')))
        for f in facts:
            restriction &= domain(f[2])
        row, = pieces(funcs[desc['function']], restriction)
        x, expr, region = row['variable'], row['expression'], row['domain']
        if model['expression'] != expr or model['domain'] != region or model['quantity'] != desc['quantity']:
            return False
        from .function_monotonicity import verify as verify_mono
        if not all(verify_mono(c['description'], c['model']) for c in model['children']):
            return False
        expressions, operation = decomposition(expr, x, row['family'])
        if model['family'] != row['family'] or model['operation'] != operation:
            return False
        expected_children = [(e, r) for e in expressions for r in components(region)]
        if len(model['children']) != len(expected_children):
            return False
        for child, (e, r) in zip(model['children'], expected_children, strict=True):
            if (child['expression'] != e or child['model']['expression'] != e
                    or child['model']['effective_domain'] != r or child['model']['variable'] != x):
                return False
        # Derivative signs are an independent algebraic check, never a student method.
        derivative = sp.diff(expr, x)
        covered = sp.S.EmptySet
        for cell in model['interval_steps']:
            r, d = cell['interval'], cell['direction']
            if not r.is_subset(region):
                return False
            interior = sp.Interval.open(r.inf, r.sup)
            directions = []
            for e in expressions:
                matching = [part for c in model['children'] if c['expression'] == e
                            for part in c['model']['partition'] if interior.is_subset(part['interval'])]
                if len(matching) != 1:
                    return False
                directions.append(matching[0]['direction'])
            if row['family'] == 'fraction':
                denominator = operation['denominator']
                positive = r.is_subset(condition_set(denominator > 0, x))
                negative = r.is_subset(condition_set(denominator < 0, x))
                sign = 'positive' if positive else 'negative' if negative else None
                expected, direction = [], directions[0]
                for name, coefficient in [('reciprocal', None), ('scale', operation['scale']), ('shift', operation['offset'])]:
                    after = operation_direction(name, [direction], coefficient, sign)
                    expected.append({'operation': name, 'before': direction, 'after': after, 'coefficient': coefficient, 'sign': sign})
                    direction = after
                if cell['operations'] != expected or direction != d:
                    return False
            elif row['family'] == 'root_sum':
                directions[0] = operation_direction('scale', [directions[0]], operation['root_scale'])
                direction = operation_direction('sum', directions)
                if cell['operations'] != [{'operation': 'sum', 'inputs': directions, 'after': direction}] or d != direction:
                    return False
            elif cell['operations'] or d != directions[0]:
                return False
            if d == 0:
                if sp.simplify(derivative) != 0:
                    return False
            else:
                valid = sp.solve_univariate_inequality(d*derivative > 0, x, relational=False)
                # An isolated zero of a polynomial derivative does not defeat strict order.
                missing = interior-valid
                if missing != sp.S.EmptySet and not isinstance(missing, sp.FiniteSet):
                    return False
            covered |= r
        if covered != region and not isinstance(region, sp.FiniteSet):
            return False
        v = model['value']
        op = sp.Le if model['quantity'] == 'maximum' else sp.Ge
        if v.is_finite:
            valid = sp.solve_univariate_inequality(op(expr, v), x, relational=False)
            if not region.is_subset(valid):
                return False
        # Candidate annotations are teaching evidence too. Verify each value
        # and require every cell boundary (including excluded limits).
        expected_points = {(r['interval'].inf, '+') for r in model['interval_steps']} | {(r['interval'].sup, '-') for r in model['interval_steps']}
        for point, side in expected_points:
            taken = point.is_finite is True and point in region
            value = expr.subs(x, point) if taken else sp.limit(expr, x, point, dir=side)
            if not any(c['point'] == point and sp.simplify(c['value']-value) == 0 and c['attained'] == taken
                       for c in model['candidates']) and not any(c['point'] == point and c['value'] == value and c['attained'] == taken for c in model['candidates']):
                return False
        for c in model['candidates']:
            if c['attained']:
                if c['point'] not in region or sp.simplify(expr.subs(x, c['point'])-c['value']) != 0:
                    return False
            elif not any(c['point'] == point and sp.limit(expr, x, point, dir=side) == c['value'] for point, side in expected_points):
                return False
        for p in model['witnesses']:
            if p not in region or sp.simplify(expr.subs(x, p)-v) != 0:
                return False
        if model['attained'] != bool(model['witnesses']):
            return False
        if not model['attained']:
            if v.is_finite and sp.solveset(expr-v, x, domain=region) != sp.S.EmptySet:
                return False
            # Check a genuine approach to the claimed bound (including infinity).
            if not any(sp.limit(expr, x, p, dir=side) == v for r in components(region)
                       for p, side in ((r.inf, '+'), (r.sup, '-'))):
                return False
        return True
    except (ValueError, TypeError, KeyError, NotImplementedError):
        return False


def parameter_inputs(desc):
    funcs, facts, _ = raw_sources(desc['source'], desc['given_definitions'])
    p = sp.Symbol(desc['parameter'], real=True)
    special = [f for f in facts if f[0] == 'quantifier' or f[0] == '=' and any(v[0] == 'extremum' for v in f[1:])]
    if len(special) != 1:
        raise ValueError('extremum.single_condition_required')
    special, = special
    if special[0] == '=':
        # min(f(x)) is the unindexed spelling of min_x f(x), but only
        # the function's declared formal argument may supply the binder.
        special = deepcopy(special)
        for side in special[1:]:
            if side[0] == 'extremum':
                call = side[3]
                if call[0] != 'call' or call[1] not in funcs:
                    raise ValueError('extremum.specified_function_required')
                variable = funcs[call[1]]['variable']
                if call[2:] != [['name', variable]] or side[2] not in ([], [variable]):
                    raise ValueError('extremum.specified_variable_binding')
                side[2] = [variable]
    allowed, sets = sp.S.Reals, {}
    for f in facts:
        if (f[0] == '=' and any(v[0] == 'extremum' for v in f[1:])) or f is special or f == ['∈', ['name', str(p)], ['real']]:
            continue
        if f[0] == '=' and f[1][0] == 'name' and f[2][0] in ('interval', 'set', 'tuple', 'set_builder'):
            sets[f[1][1]] = f[2]
        else:
            allowed &= condition_set(relation(f), p)
    return funcs, special, p, allowed, sets


def input_interval(ast, p, sets):
    if ast[0] == 'name':
        ast = sets[ast[1]]
    if ast[0] == 'set_builder':
        value = domain(ast)
        if not isinstance(value, sp.Interval):
            raise ValueError('extremum.quantified_interval_required')
        return {'low': value.inf, 'high': value.sup, 'left_closed': not value.left_open,
                'right_closed': not value.right_open, 'nonempty': sp.S.Reals}
    if ast == ['real']:
        ast = ['interval', False, False, ['infinity', -1], ['infinity', 1]]
    if ast[0] == 'tuple' and len(ast) == 3:
        ast = ['interval', False, False, *ast[1:]]
    if ast[0] != 'interval':
        raise ValueError('extremum.quantified_interval_required')
    a, b = scalar(ast[3]), scalar(ast[4])
    if (a.free_symbols | b.free_symbols)-{p}:
        raise ValueError('extremum.dependent_quantifier_domain')
    if a.has(p) and b.has(p):
        raise ValueError('extremum.single_moving_endpoint_required')
    nonempty = condition_set(sp.Le(a, b) if ast[1] and ast[2] else sp.Lt(a, b), p)
    return {'low': a, 'high': b, 'left_closed': ast[1], 'right_closed': ast[2], 'nonempty': nonempty}


def param_candidates(fn, bounds, p, *, require_full_input=False):
    """Endpoint limits and every stationary point for the declared families.

Each candidate has a parameter set on which its point belongs to the closure;
attainment is a separate set. Infinite endpoints are never witnesses.
"""
    x = sp.Symbol(fn['variable'], real=True)
    moving = bounds['low'].has(p) or bounds['high'].has(p)
    if moving and fn['ast'][:2] == ['call', 'piecewise']:
        raise ValueError('extremum.moving_piecewise_domain')
    source_pieces = pieces(fn, parameter=p)
    candidates, proofs = [], []
    nonempty = bounds['nonempty']
    if require_full_input and not moving:
        supplied = sp.Interval(bounds['low'], bounds['high'], not bounds['left_closed'], not bounds['right_closed'])
        if not supplied.is_subset(sp.Union(*(r['domain'] for r in source_pieces))):
            raise ValueError('extremum.quantifier_input_outside_function_domain')
    for row in source_pieces:
        if moving:
            if row['natural_domain'] != sp.S.Reals or row['domain'] != sp.S.Reals:
                raise ValueError('extremum.moving_domain_obligation')
            intervals = [bounds]
        else:
            fixed = sp.Interval(bounds['low'], bounds['high'], not bounds['left_closed'], not bounds['right_closed'])
            intervals = []
            region = row['domain'] & fixed
            for r in components(region):
                intervals.append({'low': r.inf, 'high': r.sup, 'left_closed': not r.left_open,
                                  'right_closed': not r.right_open, 'nonempty': sp.S.Reals})
            if isinstance(region, sp.FiniteSet):
                intervals.extend({'low': t, 'high': t, 'left_closed': True, 'right_closed': True,
                                  'nonempty': sp.S.Reals} for t in region)
        for r in intervals:
            expr = row['expression']
            derivative = sp.expand(sp.diff(expr, x))
            numerator = sp.fraction(sp.cancel(derivative))[0]
            critical = [] if numerator == 0 else sp.solve(numerator, x)
            if len(critical) > 2 or any(v.free_symbols-{p} or v.is_real is False for v in critical):
                raise ValueError('extremum.critical_points_unsupported')
            proof = {'expression': expr, 'variable': x, 'bounds': r, 'derivative': derivative,
                     'critical': critical, 'family': row['family'], 'source_ast': deepcopy(row['source_ast'])}
            proofs.append(proof)
            for point, closed, direction in ((r['low'], r['left_closed'], '+'), (r['high'], r['right_closed'], '-')):
                value = sp.simplify(expr.subs(x, point)) if point.is_finite else sp.limit(expr, x, point, dir=direction)
                # A pole at an excluded finite endpoint needs its one-sided limit.
                if value.has(sp.zoo, sp.nan):
                    if closed:
                        raise ValueError('extremum.undefined_endpoint')
                    value = sp.limit(expr, x, point, dir=direction)
                if value.has(sp.sign, sp.zoo, sp.nan):
                    raise ValueError('extremum.unresolved_limit')
                candidates.append({'value': value, 'point': point, 'active': nonempty,
                                   'attained': nonempty if closed and point.is_finite else sp.S.EmptySet,
                                   'proof': len(proofs)-1})
            for point in critical:
                active = nonempty & condition_set(sp.And(point >= r['low'], point <= r['high']), p)
                attained = nonempty & condition_set(sp.And(point >= r['low'] if r['left_closed'] else point > r['low'],
                                                           point <= r['high'] if r['right_closed'] else point < r['high']), p)
                candidates.append({'value': sp.simplify(expr.subs(x, point)), 'point': point,
                                   'active': active, 'attained': attained, 'proof': len(proofs)-1})
            if numerator == 0:
                point = (r['low']+r['high'])/2 if r['low'].is_finite and r['high'].is_finite else r['high']-1 if r['high'].is_finite else r['low']+1 if r['low'].is_finite else sp.S.Zero
                candidates.append({'value': expr, 'point': point, 'active': nonempty, 'attained': nonempty, 'proof': len(proofs)-1})
    if not candidates:
        raise ValueError('extremum.empty_function_domain')
    return {'function': deepcopy(fn), 'bounds': bounds, 'proofs': proofs, 'candidates': candidates, 'nonempty': nonempty}


def bound_cases(certificate, p, maximum=True):
    result = []
    for c in certificate['candidates']:
        valid = c['active']
        for other in certificate['candidates']:
            comparison = sp.Ge(c['value'], other['value']) if maximum else sp.Le(c['value'], other['value'])
            valid &= (sp.S.Reals-other['active']) | condition_set(comparison, p)
        attained = sp.S.EmptySet
        for other in certificate['candidates']:
            attained |= other['attained'] & condition_set(sp.Eq(c['value'], other['value']), p)
        if valid != sp.S.EmptySet:
            result.append({'value': c['value'], 'parameter_set': valid, 'attained': valid & attained,
                           'point': c['point']})
    # Equal bounds from different endpoints retain every attainment witness.
    unique = []
    for c in result:
        if not any(c['value'] == r['value'] and c['parameter_set'] == r['parameter_set'] and c['attained'] == r['attained'] for r in unique):
            unique.append(c)
    return unique


def quantified_sources(desc):
    funcs, q, p, allowed, sets = parameter_inputs(desc)
    if q[:2] != ['quantifier', '∀'] or q[4][:2] != ['quantifier', '∃']:
        raise ValueError('extremum.independent_forall_exists_required')
    outer, inner = q, q[4]
    u, v = outer[2], inner[2]
    rel = inner[4]
    if u == v or rel[0] not in ('=', '<', '<=', '>', '>='):
        raise ValueError('extremum.quantifier_roles')
    def names(a):
        return ({a[1]} if a[0] == 'name' else set()).union(*(names(c) for c in a[1:] if isinstance(c, list)))
    left, right = rel[1:]
    op = rel[0]
    if u in names(right) and v in names(left):
        left, right = right, left
        op = {'<': '>', '<=': '>=', '>': '<', '>=': '<=', '=': '='}[op]
    if v in names(left) or u in names(right) or u not in names(left) or v not in names(right):
        raise ValueError('extremum.separable_quantifier_sides_required')
    def fn(a, variable):
        if a[0] == 'call' and a[1] in funcs and a[2:] == [['name', variable]]:
            return funcs[a[1]]
        # Direct scalar expressions also occur in quantified comparison tasks.
        scalar(a)
        return {'variable': variable, 'ast': a, 'source': ''}
    ub, vb = input_interval(outer[3], p, sets), input_interval(inner[3], p, sets)
    # This admission deliberately excludes vacuous universal domains.
    if ub['nonempty'] != sp.S.Reals:
        raise ValueError('extremum.fixed_nonempty_universal_domain_required')
    return p, allowed & vb['nonempty'], op, param_candidates(fn(left, u), ub, p, require_full_input=True), param_candidates(fn(right, v), vb, p, require_full_input=True)


def parameter_model(desc):
    if desc['task'] == 'quantified':
        p, allowed, op, u, v = quantified_sources(desc)
        low_u, high_u = bound_cases(u, p, False), bound_cases(u, p)
        low_v, high_v = bound_cases(v, p, False), bound_cases(v, p)
        cases, feasible, covered = [], sp.S.EmptySet, sp.S.EmptySet
        if op == '=':
            # A continuous function on one closed interval has its entire image
            # between its attained bounds. Disconnected images are not admitted.
            for cert in (u, v):
                if len(cert['proofs']) != 1 or not cert['bounds']['left_closed'] or not cert['bounds']['right_closed']:
                    raise ValueError('extremum.continuous_closed_image_required')
                proof = cert['proofs'][0]
                if proof['family'] not in ('polynomial', 'cubic'):
                    raise ValueError('extremum.interval_image_certificate_required')
            from itertools import product
            for ul, uh, vl, vh in product(low_u, high_u, low_v, high_v):
                branch = (allowed & ul['attained'] & uh['attained'] & vl['attained'] & vh['attained'])-covered
                if branch == sp.S.EmptySet:
                    continue
                covered |= branch
                conditions = [sp.Ge(ul['value'], vl['value']), sp.Le(uh['value'], vh['value'])]
                answer = branch & condition_set(sp.And(*conditions), p)
                cases.append({'branch': branch, 'conditions': conditions, 'answer': answer,
                              'u_bounds': [ul['value'], uh['value']], 'v_bounds': [vl['value'], vh['value']]})
                feasible |= answer
        else:
            compare = {'<': sp.Lt, '<=': sp.Le, '>': sp.Gt, '>=': sp.Ge}[op]
            us, vs = (high_u, high_v) if op in ('<', '<=') else (low_u, low_v)
            for a in us:
                for b in vs:
                    branch = (allowed & a['attained'] & b['attained'])-covered
                    if branch == sp.S.EmptySet:
                        continue
                    covered |= branch
                    cond = compare(a['value'], b['value'])
                    answer = branch & condition_set(cond, p)
                    cases.append({'branch': branch, 'conditions': [cond], 'answer': answer,
                                  'u_bounds': [a['value']], 'v_bounds': [b['value']]})
                    feasible |= answer
            if covered != allowed:
                raise ValueError('extremum.quantified_bound_not_attained')
        if covered != allowed:
            raise ValueError('extremum.incomplete_quantified_cases')
        return {'task': 'quantified', 'parameter': p, 'allowed': allowed, 'operator': op,
                'universal': u, 'existential': v, 'cases': cases, 'feasible_set': feasible}
    funcs, fact, p, allowed, _ = parameter_inputs(desc)
    left, right = fact[1:]
    if right[0] == 'extremum':
        left, right = right, left
    if left[0] != 'extremum' or left[3][0] != 'call' or right[0] != 'call' or left[3][1] != right[1]:
        raise ValueError('extremum.specified_function_required')
    fn = funcs[right[1]]
    x = sp.Symbol(fn['variable'], real=True)
    if left[2] != [str(x)] or left[3][2:] != [['name', str(x)]]:
        raise ValueError('extremum.specified_variable_binding')
    point = scalar(right[2])
    if point.free_symbols or point.is_real is not True:
        raise ValueError('extremum.fixed_specified_point_required')
    rows = pieces(fn, parameter=p)
    owners = [r for r in rows if point in r['domain']]
    if len(owners) != 1:
        raise ValueError('extremum.specified_point_undefined')
    value = sp.simplify(owners[0]['expression'].subs(x, point))
    bounds = input_interval(['real'], p, {})
    cert = param_candidates(fn, bounds, p)
    feasible, out, piece_solutions = allowed, [], []
    for index, proof in enumerate(cert['proofs']):
        component = {**cert, 'candidates': [c for c in cert['candidates'] if c['proof'] == index]}
        cases = bound_cases(component, p, left[1] == 'max')
        covered, solution = sp.S.EmptySet, sp.S.EmptySet
        for c in cases:
            branch = (allowed & c['parameter_set'])-covered
            if branch == sp.S.EmptySet:
                continue
            covered |= branch
            cond = sp.Le(c['value'], value) if left[1] == 'max' else sp.Ge(c['value'], value)
            answer = branch & condition_set(cond, p)
            out.append({'piece': index, 'branch': branch, 'conditions': [cond], 'answer': answer,
                        'bound': c['value'], 'bound_attained': c['attained'] & branch})
            solution |= answer
        if covered != allowed:
            raise ValueError('extremum.incomplete_piece_cases')
        piece_solutions.append(solution)
        feasible &= solution
    return {'task': 'specified', 'parameter': p, 'allowed': allowed, 'quantity': left[1],
            'point': point, 'specified_value': value, 'certificate': cert, 'cases': out,
            'piece_solutions': piece_solutions, 'feasible_set': feasible}



def verify_parameter(desc, model):
    """Rebind the original statement and check all candidate inequalities.

Does not call parameter_model or trust its branch answers. Candidate completeness
comes from the bounded polynomial/reciprocal critical-point theorem; comparisons
are checked in the original quantified direction, including parameter endpoints.
"""
    try:
        funcs, fact, p, allowed, sets = parameter_inputs(desc)
        if model['parameter'] != p or model['task'] != desc['task']:
            return False
        if desc['task'] == 'quantified':
            p, allowed, op, u, v = quantified_sources(desc)
            if model['operator'] != op or model['universal'] != u or model['existential'] != v:
                return False
            if op == '=':
                if any(len(c['proofs']) != 1 or c['proofs'][0]['family'] not in ('polynomial', 'cubic')
                       or not c['bounds']['left_closed'] or not c['bounds']['right_closed'] for c in (u, v)):
                    return False
                # For interval images: every universal candidate lies between
                # some lower and upper values of the existential image.
                accepted = allowed
                for uc in u['candidates']:
                    lower, upper = sp.S.EmptySet, sp.S.EmptySet
                    for vc in v['candidates']:
                        lower |= vc['attained'] & condition_set(sp.Le(vc['value'], uc['value']), p)
                        upper |= vc['attained'] & condition_set(sp.Ge(vc['value'], uc['value']), p)
                    accepted &= (sp.S.Reals-uc['active']) | (lower & upper)
            else:
                compare = {'<': sp.Lt, '<=': sp.Le, '>': sp.Gt, '>=': sp.Ge}[op]
                accepted = allowed
                for uc in u['candidates']:
                    witnesses = sp.S.EmptySet
                    for vc in v['candidates']:
                        witnesses |= vc['attained'] & condition_set(compare(uc['value'], vc['value']), p)
                    accepted &= (sp.S.Reals-uc['active']) | witnesses
                # The supported fast path requires actual extrema on both sides.
                for cert in (u, v):
                    has_extremum = sp.Union(*(b['attained'] for b in bound_cases(cert, p, op in ('<', '<='))))
                    if not allowed.is_subset(has_extremum):
                        return False
        else:
            ext, at = fact[1:]
            if at[0] == 'extremum':
                ext, at = at, ext
            fn = funcs[at[1]]
            point = scalar(at[2])
            rows = pieces(fn, parameter=p)
            owner, = [r for r in rows if point in r['domain']]
            value = sp.simplify(owner['expression'].subs(owner['variable'], point))
            cert = param_candidates(fn, input_interval(['real'], p, sets), p)
            if model['certificate'] != cert or model['point'] != point or model['specified_value'] != value or model['quantity'] != ext[1]:
                return False
            accepted = allowed
            for c in cert['candidates']:
                inequality = sp.Le(c['value'], value) if ext[1] == 'max' else sp.Ge(c['value'], value)
                accepted &= (sp.S.Reals-c['active']) | condition_set(inequality, p)
        if model['allowed'] != allowed or model['feasible_set'] != accepted:
            return False
        groups = range(len(model['certificate']['proofs'])) if desc['task'] == 'specified' else [None]
        group_answers = []
        for group in groups:
            covered, answers = sp.S.EmptySet, sp.S.EmptySet
            for case in model['cases']:
                if case.get('piece') != group:
                    continue
                if not case['branch'].is_subset(allowed):
                    return False
                if covered & case['branch'] != sp.S.EmptySet:
                    return False
                covered |= case['branch']
                # Bind every displayed bound and condition to this exact
                # parameter branch, not just to the final union.
                if group is not None:
                    component = {**cert, 'candidates': [c for c in cert['candidates'] if c['proof'] == group]}
                    bound = case['bound']
                    compare = sp.Le if ext[1] == 'max' else sp.Ge
                    expected_condition = compare(bound, value)
                    if case['conditions'] != [expected_condition]:
                        return False
                    bounds = bound_cases(component, p, ext[1] == 'max')
                    equivalent = sp.Union(*(b['parameter_set'] & condition_set(sp.Eq(bound, b['value']), p) for b in bounds))
                    attained = sp.Union(*(b['attained'] & condition_set(sp.Eq(bound, b['value']), p) for b in bounds))
                    if not case['branch'].is_subset(equivalent) or case['bound_attained'] != case['branch'] & attained:
                        return False
                else:
                    ub, vb = case['u_bounds'], case['v_bounds']
                    for certificate, values in ((u, ub), (v, vb)):
                        maximums = [False, True] if op == '=' else [op in ('<', '<=')]
                        if len(values) != len(maximums):
                            return False
                        for value, maximum in zip(values, maximums, strict=True):
                            correct = sp.Union(*(b['attained'] & condition_set(sp.Eq(value, b['value']), p) for b in bound_cases(certificate, p, maximum)))
                            if not case['branch'].is_subset(correct):
                                return False
                    expected_conditions = ([sp.Ge(ub[0], vb[0]), sp.Le(ub[1], vb[1])] if op == '=' else
                                           [{'<' : sp.Lt, '<=': sp.Le, '>': sp.Gt, '>=': sp.Ge}[op](ub[0], vb[0])])
                    if case['conditions'] != expected_conditions:
                        return False
                check = case['branch'] & condition_set(sp.And(*case['conditions']), p)
                if check != case['answer']:
                    return False
                answers |= check
            if covered != allowed:
                return False
            group_answers.append(answers)
        if desc['task'] == 'specified':
            return group_answers == model['piece_solutions'] and sp.Intersection(*group_answers) == accepted
        return group_answers == [accepted]
    except (ValueError, TypeError, KeyError, NotImplementedError):
        return False
