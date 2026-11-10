"""FM-T4: find the parameter so a function is strictly monotone on a given interval.

No problem IDs. One real parameter. Supported structures:
- R0 one expression: polynomial of degree ≤2 in the variable (leading may vanish);
- R1 explicit piecewise: each branch a polynomial of degree ≤2 or ``c/x+d``; every
  branch is strictly monotone on its part of the interval and the order across each
  breakpoint holds (the breakpoint belongs to exactly one branch).
- R2 c/x+d or s*x+c/x+d with fixed s, standalone or in a piecewise branch;
- R3 sqrt(g) with a polynomial inner function of degree ≤2.
Coefficients are rational affine expressions of the parameter. Original domain
obligations and additional parameter conditions are checked before simplification.
"""
from copy import deepcopy
from itertools import pairwise

import sympy as sp

from ..problem_understanding.notation_parser import definition, parse
from .extremum_math import condition_set, domain, relation, scalar

VERSION = 'monotonicity-parameter/v7'
BASIS_KINDS = ('stated', 'difference_quotient', 'difference_product')


def relevant(goal, entries=None):
    if goal.get('kind') != 'find_range' or not isinstance(goal.get('symbol'), str):
        return False
    if isinstance(goal.get('required_monotonicity'), dict):
        return True
    return any(_source_pair(row['expression']) is not None for row in entries or [])


def routed_description(goal, target_ref, entries):
    if not relevant(goal, entries):
        return None
    return describe(goal, target_ref, entries)


def _quantified_pair(ast):
    """Read two universal inputs on one domain with an explicit distinctness guard.

    Preserve the guard; an unguarded quotient or an existential assertion is not
    a strict monotonicity condition. Both P→Q and (not P)∨Q are accepted.
    """
    if ast[:2] != ['quantifier', '∀'] or ast[4][:2] != ['quantifier', '∀']:
        raise ValueError('mono_param.two_universal_inputs_required')
    inner = ast[4]
    names = (ast[2], inner[2])
    region = _fixed_domain(ast[3])
    inner_domain = inner[3]
    excludes_first = (inner_domain[0] == 'set_difference'
                      and inner_domain[2] == ['set', ['name', names[0]]])
    if excludes_first:
        inner_domain = inner_domain[1]
    if names[0] == names[1] or _fixed_domain(inner_domain) != region:
        raise ValueError('mono_param.pair_domain_mismatch')
    body = inner[4]
    if excludes_first:
        return body, names, region
    if body[0] == 'implies':
        guard, comparison = body[1:]
        operator = '!='
    elif body[0] == 'or' and len(body) == 3:
        guard, comparison = body[1:]
        if guard[0] != '=':
            comparison, guard = guard, comparison
        operator = '='
    else:
        raise ValueError('mono_param.distinct_inputs_required')
    if (guard[0] != operator or len(guard) != 3
            or {tuple(v) for v in guard[1:]} != {('name', n) for n in names}):
        raise ValueError('mono_param.distinct_inputs_required')
    return comparison, names, region


def _basis_ast(basis):
    ast = parse(basis['statement'])
    if ast[0] == 'quantifier':
        return _quantified_pair(ast)
    return ast, None, None


def _basis_relation_text(basis):
    """Serialize the already checked difference relation for original-text matching."""
    ast, _, _ = _basis_ast(basis)
    lhs = ast[1]
    values, inputs = lhs[1:]
    calls = values[1:]
    return (f'({calls[0][1]}({calls[0][2][1]})-{calls[1][1]}({calls[1][2][1]}))'
            f'{lhs[0]}({inputs[1][1]}-{inputs[2][1]}){ast[0]}0')


def _source_pair(text):
    """Recognize a source assertion without changing the extracted candidate."""
    try:
        comparison, _, region = _quantified_pair(parse(text))
        kind = {'/': 'difference_quotient', '*': 'difference_product'}.get(comparison[1][0])
        if not kind:
            return None
        basis = {'kind': kind, 'statement': text}
        direction = _basis_direction(basis, None)
        function = comparison[1][1][1][1]
        return {'basis': basis, 'direction': direction, 'function': function, 'region': region}
    except (ValueError, TypeError, IndexError, KeyError):
        return None


def _required_goal(goal, entries):
    if isinstance(goal.get('required_monotonicity'), dict):
        return goal
    pairs = [pair for row in entries if (pair := _source_pair(row['expression'])) is not None]
    if not pairs:
        raise ValueError('mono_param.requirement_missing')
    pair = pairs[0]
    definitions = [row for row in entries if definition(row['expression'])[:2]
                   == ['function_definition', pair['function']]]
    if len(definitions) != 1:
        raise ValueError('mono_param.unique_function_definition_required')
    text = definitions[0]['expression']
    declared = definition(text)
    region = pair['region']
    if not isinstance(region, sp.Interval) and region is not sp.S.Reals:
        raise ValueError('mono_param.interval_required')
    if region is sp.S.Reals:
        interval = 'ℝ'
    else:
        left = '-∞' if region.inf == -sp.oo else str(region.inf)
        right = '+∞' if region.sup == sp.oo else str(region.sup)
        interval = ('(' if region.left_open else '[') + left + ',' + right + (')' if region.right_open else ']')
    return dict(goal, required_monotonicity={
        'expression': text.split('=', 1)[1], 'variable': declared[2],
        'function': pair['function'], 'direction': pair['direction'], 'strict': True,
        'input_domain': interval, 'basis': pair['basis'],
    })


def _basis_direction(basis, function):
    """Direction implied by a difference quotient/product sign; ``None`` for stated."""
    if not isinstance(basis, dict) or set(basis) != {'kind', 'statement'}:
        raise ValueError('mono_param.basis_fields')
    kind = basis['kind']
    if kind not in BASIS_KINDS:
        raise ValueError('mono_param.basis_kind')
    if kind == 'stated':
        return None
    ast, bound_names, _ = _basis_ast(basis)
    if ast[0] not in ('<', '>') or ast[2] != ['number', '0']:
        raise ValueError('mono_param.basis_strict_sign')
    expected = '/' if kind == 'difference_quotient' else '*'
    lhs = ast[1]
    if lhs[0] != expected:
        raise ValueError('mono_param.basis_shape')
    values, inputs = lhs[1], lhs[2]
    if values[0] != '-' or inputs[0] != '-':
        raise ValueError('mono_param.basis_shape')
    calls = values[1:]
    if any(call[0] != 'call' or len(call) != 3 or call[2][0] != 'name' for call in calls):
        raise ValueError('mono_param.basis_shape')
    if calls[0][1] != calls[1][1] or (function and calls[0][1] != function):
        raise ValueError('mono_param.basis_function')
    u, v = calls[0][2][1], calls[1][2][1]
    if any(side[0] != 'name' for side in inputs[1:]):
        raise ValueError('mono_param.basis_shape')
    s, t = inputs[1][1], inputs[2][1]
    if u == v or {u, v} != {s, t}:
        raise ValueError('mono_param.basis_inputs')
    if bound_names is not None and {u, v} != set(bound_names):
        raise ValueError('mono_param.basis_unbound_inputs')
    order = 1 if u == s else -1
    sign = 1 if ast[0] == '>' else -1
    return 'increasing' if order * sign > 0 else 'decreasing'


def _read_body(body, names, x, region):
    """Keep pre-cancellation domain obligations local to the actual input region."""
    obligations = []
    expr = scalar(body, names, obligations)
    for obligation in obligations:
        if obligation is sp.S.true:
            continue
        # Parameter-dependent denominators/inner roots are outside this family.
        if obligation.free_symbols - {x}:
            raise ValueError('mono_param.parameter_obligation')
        allowed = condition_set(obligation, x)
        if region.is_subset(allowed) is not True:
            raise ValueError('mono_param.branch_domain_obligation')
    return sp.cancel(expr)


def _check_coefficients(coeffs, p):
    for coefficient in coeffs:
        if coefficient.free_symbols - {p}:
            raise ValueError('mono_param.coefficient_symbols')
        if not coefficient.is_polynomial(p):
            raise ValueError('mono_param.coefficient_family')
        polynomial = sp.Poly(coefficient, p)
        if polynomial.degree() > 1 or any(c.is_Rational is not True for c in polynomial.all_coeffs()):
            raise ValueError('mono_param.coefficient_family')


def _fixed_domain(ast):
    endpoints = (ast[3:5] if ast[0] == 'interval' else
                 ast[1:] if ast[0] in ('tuple', 'set') else [])
    for endpoint in endpoints:
        obligations = []
        value = scalar(endpoint, obligations=obligations)
        if value.free_symbols or any(item is not sp.S.true for item in obligations):
            raise ValueError('mono_param.fixed_domain_required')
    value = domain(ast)
    if value.free_symbols:
        raise ValueError('mono_param.fixed_domain_required')
    return value


def _branch(body, names, x, p, region):
    """Classify one branch body on its region; raise for unsupported shapes."""
    expr = _read_body(body, names, x, region)
    if expr.free_symbols - {x, p}:
        raise ValueError('mono_param.extra_symbol')
    if isinstance(region, sp.FiniteSet) and len(region) == 1:
        value = sp.simplify(expr.subs(x, next(iter(region))))
        _check_coefficients((value,), p)
        return {'kind': 'point', 'expression': expr, 'value': value, 'region': region}
    if expr.is_polynomial(x):
        poly = sp.Poly(sp.expand(expr), x, domain=sp.EX)
        if poly.degree() > 2:
            raise ValueError('mono_param.degree_budget')
        coeffs = [poly.nth(i) for i in range(3)]
        _check_coefficients(coeffs, p)
        leading, linear = coeffs[2], coeffs[1]
        axis = None if leading == 0 and not leading.free_symbols else sp.cancel(-linear / (2 * leading))
        return {'kind': 'polynomial', 'expression': expr, 'region': region,
                'leading': leading, 'linear': linear, 'constant': coeffs[0], 'axis': axis,
                'needs_leading_split': bool(leading.free_symbols)}
    scaled = sp.expand(sp.cancel(expr * x))
    if not scaled.is_polynomial(x) or sp.Poly(scaled, x).degree() > 2:
        raise ValueError('mono_param.branch_family')
    numerator, offset, slope = scaled.coeff(x, 0), scaled.coeff(x, 1), scaled.coeff(x, 2)
    _check_coefficients((numerator, offset, slope), p)
    # A parameter in the x coefficient would need its own sign split; not admitted yet.
    if slope.free_symbols:
        raise ValueError('mono_param.branch_family')
    # The denominator restriction belongs to this branch only.
    if region.contains(0) in (True, sp.S.true) or bool(region.inf < 0) and bool(region.sup > 0):
        raise ValueError('mono_param.branch_domain')
    if slope == 0:
        return {'kind': 'reciprocal', 'expression': expr, 'region': region,
                'numerator': numerator, 'offset': offset}
    return {'kind': 'reciprocal_sum', 'expression': expr, 'region': region,
            'slope': slope, 'numerator': numerator, 'offset': offset}


def _reciprocal_sum_bound(slope, region, direction):
    """For s*x+c/x+d on one side of 0: c must satisfy ``c op bound``; ``None`` means impossible.

    The derivative s-c/x^2 must keep one sign on the region, i.e. c ≤ s*x^2 (increasing)
    or c ≥ s*x^2 (decreasing) for every x there; equality at an end point is allowed.
    """
    ends = [abs(region.inf), abs(region.sup)]
    low, high = min(ends) ** 2, max(ends) ** 2
    if direction == 'increasing':
        bound = slope * low if slope > 0 else slope * high
        return ('<=', bound) if bound.is_finite else None
    bound = slope * high if slope > 0 else slope * low
    return ('>=', bound) if bound.is_finite else None


def _compile_requirement(goal):
    """Parse requirement into sympy objects; raises ValueError on unsupported form."""
    req = goal['required_monotonicity']
    required = {'expression', 'variable', 'direction', 'strict', 'input_domain'}
    if not required <= set(req) or set(req) - required - {'function', 'basis'}:
        raise ValueError('mono_param.requirement_fields')
    if req['direction'] not in ('increasing', 'decreasing'):
        raise ValueError('mono_param.direction_required')
    if req['strict'] is not True:
        raise ValueError('mono_param.strict_required')
    parameter = goal['symbol']
    variable = req['variable']
    if parse(parameter) != ['name', parameter] or parse(variable) != ['name', variable]:
        raise ValueError('mono_param.name_required')
    if parameter == variable:
        raise ValueError('mono_param.parameter_variable_collision')
    function = req.get('function')
    if function is not None and parse(function) != ['name', function]:
        raise ValueError('mono_param.function_name_required')
    basis = req.get('basis', {'kind': 'stated', 'statement': ''})
    implied = _basis_direction(basis, function)
    if implied is not None and implied != req['direction']:
        raise ValueError('mono_param.basis_direction')
    interval = _fixed_domain(parse(req['input_domain']))
    if basis['kind'] != 'stated':
        _, _, quantified_domain = _basis_ast(basis)
        if quantified_domain is not None and quantified_domain != interval:
            raise ValueError('mono_param.basis_domain_mismatch')
    if not isinstance(interval, sp.Interval) and interval is not sp.S.Reals:
        raise ValueError('mono_param.interval_required')
    if interval is sp.S.Reals:
        interval = sp.Interval(-sp.oo, sp.oo)
    if interval.measure == 0 or interval == sp.S.EmptySet:
        raise ValueError('mono_param.degenerate_interval')
    names = {
        parameter: sp.Symbol(parameter, real=True),
        variable: sp.Symbol(variable, real=True),
    }
    x, p = names[variable], names[parameter]
    ast = parse(req['expression'])
    def mentions_parameter(node):
        return isinstance(node, list) and (node == ['name', parameter]
                                           or any(mentions_parameter(child) for child in node))
    # The parameter can disappear after clipping to the requested interval (or
    # simplifying). Its presence in the original expression is what matters.
    if not mentions_parameter(ast):
        raise ValueError('mono_param.parameter_absent')
    if ast[:2] == ['call', 'piecewise']:
        raw = list(zip(ast[2::2], ast[3::2], strict=True))
        if len(raw) < 2:
            raise ValueError('mono_param.piecewise_rows')
        pieces, covered = [], sp.S.EmptySet
        for body, predicate in raw:
            condition = relation(predicate, names)
            if condition.free_symbols - {x}:
                raise ValueError('mono_param.branch_condition_symbols')
            own = condition_set(condition, x)
            if own & covered != sp.S.EmptySet:
                raise ValueError('mono_param.overlapping_branches')
            covered |= own
            region = own & interval
            if region == sp.S.EmptySet:
                continue
            if not (isinstance(region, sp.Interval)
                    or isinstance(region, sp.FiniteSet) and len(region) == 1):
                raise ValueError('mono_param.branch_region')
            row = _branch(body, names, x, p, region)
            row['condition'] = condition
            pieces.append(row)
        if sp.Complement(interval, sp.Union(*(row['region'] for row in pieces))) != sp.S.EmptySet:
            raise ValueError('mono_param.branch_coverage')
        # A singleton at b precedes an interval beginning at b, irrespective of
        # the order in which the source lists its mutually exclusive branches.
        pieces.sort(key=lambda row: (row['region'].inf, row['region'].sup))
        joins = []
        for left, right in pairwise(pieces):
            point = left['region'].sup
            if point != right['region'].inf or not point.is_finite:
                raise ValueError('mono_param.branch_gap')
            left_owns = left['region'].contains(point) is sp.S.true
            right_owns = right['region'].contains(point) is sp.S.true
            if left_owns == right_owns:
                raise ValueError('mono_param.breakpoint_owner')
            owner = 'left' if left_owns else 'right'
            joins.append({'point': point, 'owner': owner})
        expression = sp.Piecewise(*((row['expression'], row['condition']) for row in pieces))
        return {
            'parameter': parameter, 'variable': variable, 'direction': req['direction'],
            'function': function, 'input_domain': req['input_domain'],
            'expression_text': req['expression'], 'basis': deepcopy(basis),
            'structure': 'piecewise', 'expression': expression, 'interval': interval,
            'pieces': pieces, 'joins': joins, 'needs_leading_split': False,
            'leading': None, 'linear': None, 'constant': None, 'axis': None,
            'x': x, 'p': p,
        }
    # sqrt(g): the outer root preserves order on [0,+∞); g carries the parameter work.
    radical = ast[:2] == ['call', 'sqrt'] and len(ast) == 3
    if radical:
        ast = ast[2]
    piece = _branch(ast, names, x, p, interval)
    if radical and piece['kind'] != 'polynomial':
        raise ValueError('mono_param.branch_family')
    piece['condition'] = sp.S.true
    expr = piece['expression']
    return {
        'parameter': parameter, 'variable': variable, 'direction': req['direction'],
        'function': function, 'input_domain': req['input_domain'],
        'expression_text': req['expression'], 'basis': deepcopy(basis),
        'structure': 'radical' if radical else 'single', 'pieces': [piece], 'joins': [],
        'inner': expr if radical else None,
        'expression': sp.sqrt(expr) if radical else expr,
        'interval': interval, 'leading': piece.get('leading'), 'linear': piece.get('linear'),
        'constant': piece.get('constant'), 'axis': piece.get('axis'),
        'needs_leading_split': piece.get('needs_leading_split', False),
        'x': x, 'p': p,
    }


def _parameter_condition(ast, p):
    if ast[0] in ('and', 'or'):
        sets = [_parameter_condition(child, p) for child in ast[1:]]
        return (sp.Intersection if ast[0] == 'and' else sp.Union)(*sets)
    if ast[0] == '∈' and ast[1] == ['name', p.name]:
        return _fixed_domain(ast[2])
    return condition_set(relation(ast, {p.name: p}), p)


def _compile_source(goal, entries):
    """Account for every original source, or decline this bounded method."""
    goal = _required_goal(goal, entries)
    model = _compile_requirement(goal)
    req = goal['required_monotonicity']
    parameter_conditions = []
    for row in entries:
        text = row['expression']
        ast = definition(text)
        body = None
        if ast[0] == 'function_definition':
            if model['function'] is None:
                model['function'] = ast[1]
                _basis_direction(model['basis'], model['function'])
            if ast[1] != model['function'] or ast[2] != model['variable']:
                raise ValueError('mono_param.definition_mismatch')
            body = text.split('=', 1)[1]
        elif ast[0] == '=' and ast[1] == ['name', 'y'] and model['function'] is None:
            body = text.split('=', 1)[1]
        if body is not None:
            original = _compile_requirement(dict(goal, required_monotonicity=dict(req, expression=body)))
            if (original['structure'] != model['structure']
                    or len(original['pieces']) != len(model['pieces'])
                    or any(a['region'] != b['region'] or sp.simplify(a['expression'] - b['expression']) != 0
                           for a, b in zip(original['pieces'], model['pieces']))):
                raise ValueError('mono_param.definition_mismatch')
            continue
        if ast[0] == '=' and ast[1] == ['call', 'Dom', ['name', model['function']]]:
            declared = _fixed_domain(ast[2])
            if model['interval'].is_subset(declared) is not True:
                raise ValueError('mono_param.declared_domain_mismatch')
            # A larger declared domain must also be legal. For a root this would
            # require a separate non-negativity proof outside the target interval.
            if declared != model['interval']:
                if model['structure'] == 'radical':
                    raise ValueError('mono_param.additional_radical_domain')
                _compile_requirement(dict(goal, required_monotonicity=dict(
                    req, input_domain=text.split('=', 1)[1])))
            continue
        basis = model['basis']
        if basis['kind'] != 'stated' and ast == parse(basis['statement']):
            continue
        pair = _source_pair(text)
        if (pair is not None and pair['function'] == model['function']
                and pair['direction'] == model['direction'] and pair['region'] == model['interval']):
            continue
        try:
            feasible = _parameter_condition(ast, model['p'])
        except (ValueError, TypeError, NotImplementedError, sp.PolynomialError) as exc:
            raise ValueError('mono_param.unprocessed_source:' + row['source_ref']) from exc
        parameter_conditions.append({'source_ref': row['source_ref'], 'feasible': feasible})
    model['parameter_conditions'] = parameter_conditions
    model['requirement'] = deepcopy(req)
    model['parameter_set'] = (sp.Intersection(*(row['feasible'] for row in parameter_conditions))
                              if parameter_conditions else sp.S.Reals)
    return model


def describe(goal, target_ref, entries):
    # Feature values must be JSON-serializable; sympy objects stay out of this dict.
    desc = {
        'source': deepcopy(goal), 'target_ref': target_ref,
        'given_definitions': deepcopy(entries),
        'source_refs': [target_ref, *[row['source_ref'] for row in entries]],
        'structure_supported': False, 'reason': '', 'version': VERSION,
        'family': '', 'parameter': '', 'variable': '', 'direction': '',
        'strict': True, 'expression_text': '', 'input_domain': '',
        'function': None, 'needs_leading_split': False,
        'basis_kind': 'stated', 'piece_count': 0,
    }
    try:
        model = _compile_source(goal, entries)
        desc.update(
            structure_supported=True,
            family={'piecewise': 'piecewise_parameter', 'radical': 'radical_parameter'}.get(
                model['structure'], 'quadratic_parameter' if model['pieces'][0]['kind'] == 'polynomial'
                else 'reciprocal_parameter'),
            parameter=model['parameter'], variable=model['variable'],
            direction=model['direction'], strict=True,
            expression_text=model['expression_text'],
            input_domain=model['input_domain'], function=model['function'],
            needs_leading_split=model['needs_leading_split'],
            basis_kind=model['basis']['kind'], piece_count=len(model['pieces']),
            requirement=model['requirement'],
            basis_relation=(_basis_relation_text(model['basis']) if model['basis']['kind'] != 'stated' else ''),
        )
        return desc
    except (ValueError, TypeError, IndexError, KeyError, NotImplementedError, sp.PolynomialError) as exc:
        desc['reason'] = str(exc)
        return desc


def _model(desc):
    if not desc.get('structure_supported'):
        raise ValueError(desc.get('reason') or 'mono_param.unsupported')
    return _compile_source(desc['source'], desc['given_definitions'])


def _compare_axis(axis, bound, op):
    """Translate axis □ bound into a set on the free symbols of the relation."""
    if bound in (-sp.oo, sp.oo):
        if op == '<=' and bound is sp.oo:
            return sp.S.Reals
        if op == '>=' and bound is -sp.oo:
            return sp.S.Reals
        if op == '<=' and bound is -sp.oo:
            return sp.S.EmptySet
        if op == '>=' and bound is sp.oo:
            return sp.S.EmptySet
    free = axis.free_symbols
    if len(free) != 1:
        if not free:
            left = sp.simplify(axis - bound)
            ok = (left <= 0) if op == '<=' else (left >= 0)
            return sp.S.Reals if ok else sp.S.EmptySet
        raise ValueError('mono_param.axis_symbols')
    parameter = next(iter(free))
    relation_ = sp.Le(axis, bound) if op == '<=' else sp.Ge(axis, bound)
    return condition_set(relation_, parameter)


def _sign_set(value, positive, parameter):
    if not value.free_symbols:
        if value == 0:
            return sp.S.EmptySet
        return sp.S.Reals if (value > 0) == positive else sp.S.EmptySet
    return condition_set(sp.Gt(value, 0) if positive else sp.Lt(value, 0), parameter)


def _linear_case(slope, direction, parameter):
    if slope == 0:
        return sp.S.EmptySet, 'constant'
    return _sign_set(slope, direction == 'increasing', parameter), 'linear'


def _quadratic_side(leading_sign, region, direction, axis, parameter):
    """The region must lie entirely on the mono side of the axis; endpoint equality allowed."""
    left, right = region.inf, region.sup
    if direction == 'increasing':
        if leading_sign > 0:
            return _compare_axis(axis, left, '<=')
        return _compare_axis(axis, right, '>=')
    if leading_sign > 0:
        return _compare_axis(axis, right, '>=')
    return _compare_axis(axis, left, '<=')


def _case_feasible(leading, linear, region, direction, parameter, premise):
    """Feasible parameter set under a premise on the leading coefficient."""
    p = parameter
    if premise == 'zero':
        if leading.free_symbols:
            zeros = condition_set(sp.Eq(leading, 0), p)
            if isinstance(zeros, sp.FiniteSet) and len(zeros) == 1:
                root = next(iter(zeros))
                slope = sp.simplify(linear.subs(p, root))
                feasible, kind = _linear_case(slope, direction, p)
                if feasible == sp.S.Reals:
                    return zeros, kind, {'leading': 0, 'slope': slope}
                if feasible == sp.S.EmptySet:
                    return sp.S.EmptySet, kind, {'leading': 0, 'slope': slope}
                return sp.Intersection(zeros, feasible), kind, {'leading': 0, 'slope': slope}
            slope_set, kind = _linear_case(linear, direction, p)
            return sp.Intersection(zeros, slope_set), kind, {'leading': 0, 'slope': linear}
        slope_set, kind = _linear_case(linear, direction, p)
        return slope_set, kind, {'leading': 0, 'slope': linear}

    sign = 1 if premise == 'positive' else -1
    lead_set = _sign_set(leading, sign > 0, p)
    if lead_set == sp.S.EmptySet:
        return sp.S.EmptySet, 'quadratic', {'leading_sign': sign}
    axis = sp.cancel(-linear / (2 * leading))
    side = _quadratic_side(sign, region, direction, axis, p)
    return sp.Intersection(lead_set, side), 'quadratic', {'leading_sign': sign, 'axis': axis}


def _piece_cases(piece, direction, p):
    if piece['kind'] == 'point':
        # A single input has no pair to compare. Its actual value is checked at
        # each adjacent join, rather than treating it as a constant interval.
        return [{'premise': 'point', 'kind': 'point', 'feasible': sp.S.Reals,
                 'meta': {'value': piece['value']}, 'kept': True}]
    if piece['kind'] == 'reciprocal':
        # c/x+d on one side of 0: increasing iff c<0, decreasing iff c>0.
        part = _sign_set(piece['numerator'], direction == 'decreasing', p)
        return [{'premise': 'reciprocal', 'kind': 'reciprocal', 'feasible': sp.simplify(part),
                 'meta': {'numerator': piece['numerator']}, 'kept': part != sp.S.EmptySet}]
    if piece['kind'] == 'reciprocal_sum':
        rule = _reciprocal_sum_bound(piece['slope'], piece['region'], direction)
        if rule is None:
            part = sp.S.EmptySet
        else:
            op, bound = rule
            rel = (sp.Le if op == '<=' else sp.Ge)(piece['numerator'], bound)
            part = (condition_set(rel, p) if rel.free_symbols
                    else (sp.S.Reals if bool(rel) else sp.S.EmptySet))
        return [{'premise': 'reciprocal_sum', 'kind': 'reciprocal_sum', 'feasible': sp.simplify(part),
                 'meta': {'slope': piece['slope'], 'numerator': piece['numerator'],
                          'bound': None if rule is None else rule[1],
                          'relation': None if rule is None else rule[0]},
                 'kept': part != sp.S.EmptySet}]
    leading = piece['leading']
    premises = (['zero', 'negative', 'positive'] if piece['needs_leading_split']
                else (['zero'] if leading == 0 else (['positive'] if leading > 0 else ['negative'])))
    cases = []
    for premise in premises:
        part, kind, meta = _case_feasible(leading, piece['linear'], piece['region'], direction, p, premise)
        part = sp.simplify(part)
        cases.append({'premise': premise, 'kind': kind, 'feasible': part,
                      'meta': dict(meta), 'kept': part != sp.S.EmptySet})
    return cases


def _boundary_value(piece, point, x):
    """Finite boundary value, with the coefficient that must vanish at a pole.

    A strictly monotone s*x+c/x+d branch approaching a finite, included join
    at zero cannot diverge there in the required order. Thus c=0 is necessary;
    after imposing it, the boundary value is d. Branch strictness is separate.
    """
    if point == 0 and piece['kind'] in ('reciprocal', 'reciprocal_sum'):
        return piece['offset'], piece['numerator']
    return sp.simplify(piece['expression'].subs(x, point)), None


def _join_condition(left, right, point, direction, p, x):
    left_value, left_pole = _boundary_value(left, point, x)
    right_value, right_pole = _boundary_value(right, point, x)
    zero_terms = [term for term in (left_pole, right_pole) if term is not None]
    finite_set = (sp.Intersection(*(condition_set(sp.Eq(term, 0), p) for term in zero_terms))
                  if zero_terms else sp.S.Reals)
    gap = sp.simplify(left_value - right_value)
    rel = sp.Le(gap, 0) if direction == 'increasing' else sp.Ge(gap, 0)
    feasible = condition_set(rel, p) & finite_set
    return {'left_value': left_value, 'right_value': right_value,
            'zero_terms': zero_terms, 'finite_set': finite_set,
            'feasible': sp.simplify(feasible)}


def _minimum_end(interval, direction):
    """Where a strictly monotone inner function takes its least values on the interval."""
    return interval.sup if direction == 'decreasing' else interval.inf


def _solve_radical(model, direction, p, x):
    """sqrt(g) is strictly monotone iff g is, in the same direction, and g ≥ 0 on the whole interval.

    Under strict monotonicity the infimum of g sits at one end; an infinite end means g → -∞.
    """
    cases = _piece_cases(model['pieces'][0], direction, p)
    monotone = sp.simplify(sp.Union(*(case['feasible'] for case in cases)))
    interval = model['interval']
    end = _minimum_end(interval, direction)
    attained = bool(end.is_finite) and interval.contains(end) in (True, sp.S.true)
    if end.is_finite:
        end_value = sp.simplify(model['inner'].subs(x, end))
        rel = sp.Ge(end_value, 0)
        nonnegative = (sp.simplify(condition_set(rel, p)) if rel.free_symbols
                       else (sp.S.Reals if bool(rel) else sp.S.EmptySet))
    else:
        end_value, nonnegative = None, sp.S.EmptySet
    return {
        'task': 'monotonicity_parameter', 'structure': 'radical',
        'parameter': model['parameter'], 'variable': model['variable'],
        'direction': direction, 'interval': interval,
        'expression': model['expression'], 'inner': model['inner'],
        'leading': model['leading'], 'axis': model['axis'],
        'needs_leading_split': model['needs_leading_split'],
        'cases': cases, 'monotone_set': monotone,
        'minimum_end': end, 'minimum_value': end_value, 'minimum_attained': attained,
        'nonnegative_set': nonnegative,
        'feasible_set': sp.simplify(sp.Intersection(monotone, nonnegative)),
        'version': VERSION,
    }


def _solve_model(model):
    p, x = model['p'], model['x']
    direction = model['direction']
    if model['structure'] == 'radical':
        return _solve_radical(model, direction, p, x)
    if model['structure'] == 'single':
        cases = _piece_cases(model['pieces'][0], direction, p)
        feasible = sp.simplify(sp.Union(*(case['feasible'] for case in cases)))
        return {
            'task': 'monotonicity_parameter', 'structure': 'single',
            'parameter': model['parameter'], 'variable': model['variable'],
            'direction': direction, 'interval': model['interval'],
            'expression': model['expression'], 'leading': model['leading'],
            'axis': model['axis'], 'needs_leading_split': model['needs_leading_split'],
            'kind': model['pieces'][0]['kind'],
            'feasible_set': feasible, 'cases': cases, 'version': VERSION,
        }
    pieces, feasible = [], sp.S.Reals
    for piece in model['pieces']:
        cases = _piece_cases(piece, direction, p)
        part = sp.simplify(sp.Union(*(case['feasible'] for case in cases)))
        pieces.append({'kind': piece['kind'], 'expression': piece['expression'],
                       'region': piece['region'], 'axis': piece.get('axis'),
                       'feasible': part, 'cases': cases})
        feasible = sp.Intersection(feasible, part)
    joins = []
    for index, join in enumerate(model['joins']):
        comparison = _join_condition(
            model['pieces'][index], model['pieces'][index + 1], join['point'], direction, p, x)
        joins.append({'point': join['point'], 'owner': join['owner'],
                      'relation': '<=' if direction == 'increasing' else '>=', **comparison})
        feasible = sp.Intersection(feasible, comparison['feasible'])
    return {
        'task': 'monotonicity_parameter', 'structure': 'piecewise',
        'parameter': model['parameter'], 'variable': model['variable'],
        'direction': direction, 'interval': model['interval'],
        'expression': model['expression'], 'pieces': pieces, 'joins': joins,
        'needs_leading_split': False, 'feasible_set': sp.simplify(feasible),
        'cases': [], 'version': VERSION,
    }


def solve(desc):
    model = _model(desc)
    solved = _solve_model(model)
    solved['parameter_set'] = model['parameter_set']
    solved['unrestricted_set'] = solved['feasible_set']
    solved['feasible_set'] = sp.simplify(solved['feasible_set'] & model['parameter_set'])
    return solved


def _concrete_holds(expr, variable, region, direction):
    poly = sp.Poly(sp.expand(expr), variable, domain=sp.EX)
    if poly.degree() > 2:
        return False
    a, b = poly.nth(2), poly.nth(1)
    if a == 0:
        if b == 0:
            return False
        return bool(b > 0) if direction == 'increasing' else bool(b < 0)
    axis = -b / (2 * a)
    left, right = region.inf, region.sup
    if direction == 'increasing':
        return bool(axis <= left) if a > 0 else bool(axis >= right)
    return bool(axis >= right) if a > 0 else bool(axis <= left)


def _concrete_piece_holds(kind, expr, variable, region, direction):
    if kind == 'point':
        return expr.subs(variable, next(iter(region))).is_real is True
    if kind == 'polynomial':
        return _concrete_holds(expr, variable, region, direction)
    scaled = sp.expand(sp.cancel(expr * variable))
    numerator, slope = scaled.coeff(variable, 0), scaled.coeff(variable, 2)
    if region.contains(0) in (True, sp.S.true) or bool(region.inf < 0) and bool(region.sup > 0):
        return False
    if slope != 0:
        rule = _reciprocal_sum_bound(slope, region, direction)
        if rule is None:
            return False
        return bool(numerator <= rule[1]) if rule[0] == '<=' else bool(numerator >= rule[1])
    if numerator == 0:
        return False
    return bool(numerator < 0) if direction == 'increasing' else bool(numerator > 0)


def _sample_points(region, count=6):
    if isinstance(region, sp.FiniteSet):
        return list(region)
    left, right = region.inf, region.sup
    if left == -sp.oo and right == sp.oo:
        grid = [-2, -1, 0, 1, 2]
    elif left == -sp.oo:
        grid = [right - k for k in range(1, count + 1)]
    elif right == sp.oo:
        grid = [left + k for k in range(1, count + 1)]
    else:
        grid = [left + (right - left) * sp.Rational(k, count + 1) for k in range(1, count + 1)]
        if not region.left_open:
            grid.append(left)
        if not region.right_open:
            grid.append(right)
    points = []
    for value in grid:
        value = sp.sympify(value)
        if value in (-sp.oo, sp.oo):
            continue
        if region.contains(value) in (True, sp.S.true):
            points.append(sp.simplify(value))
    return list(dict.fromkeys(points))


def _pair_ok(evaluate, x1, x2, direction):
    gap = sp.simplify(x2 - x1)
    if gap == 0:
        return True
    signed = sp.simplify((evaluate(x2) - evaluate(x1)) / gap)
    if signed.is_extended_real is not True:
        return False
    return bool(signed > 0) if direction == 'increasing' else bool(signed < 0)


def _holds_by_pairs(expr, variable, region, direction, kind='polynomial'):
    points = _sample_points(region)
    evaluate = lambda value: expr.subs(variable, value)
    for i, x1 in enumerate(points):
        for x2 in points[i + 1:]:
            if not _pair_ok(evaluate, x1, x2, direction):
                return False
    return _concrete_piece_holds(kind, expr, variable, region, direction)


def _piecewise_holds(compiled, value):
    """Exact decision for one concrete parameter value: branches, then each breakpoint."""
    p, x, direction = compiled['p'], compiled['x'], compiled['direction']
    concrete = [dict(piece, expression=sp.simplify(piece['expression'].subs(p, value)))
                for piece in compiled['pieces']]
    if any(row['expression'].free_symbols - {x} for row in concrete):
        return False
    for row in concrete:
        if not _concrete_piece_holds(row['kind'], row['expression'], x, row['region'], direction):
            return False
    for index, join in enumerate(compiled['joins']):
        values = []
        for row, side in ((concrete[index], '-'), (concrete[index + 1], '+')):
            # Substitute the concrete parameter first: a vanishing reciprocal
            # coefficient gives a regular limit, while nonzero ones may diverge.
            point = join['point']
            value = (row['expression'].subs(x, point) if row['region'].contains(point) is sp.S.true
                     else sp.limit(row['expression'], x, point, dir=side))
            if value.is_extended_real is not True:
                return False
            values.append(value)
        left, right = values
        if not (bool(left <= right) if direction == 'increasing' else bool(left >= right)):
            return False

    def evaluate(point):
        row = next(row for row in concrete if row['region'].contains(point) in (True, sp.S.true))
        return row['expression'].subs(x, point)

    points = [point for row in concrete for point in _sample_points(row['region'], 3)]
    for i, x1 in enumerate(points):
        for x2 in points[i + 1:]:
            if not _pair_ok(evaluate, x1, x2, direction):
                return False
    return True


def _radical_holds(compiled, value):
    """Exact decision for one parameter value: inner order, whole-interval definition, then pairs."""
    p, x, direction = compiled['p'], compiled['x'], compiled['direction']
    interval = compiled['interval']
    inner = sp.simplify(compiled['inner'].subs(p, value))
    if inner.free_symbols - {x} or not _concrete_holds(inner, x, interval, direction):
        return False
    end = _minimum_end(interval, direction)
    if not end.is_finite or not bool(inner.subs(x, end) >= 0):
        return False
    evaluate = lambda point: sp.sqrt(inner.subs(x, point))
    points = _sample_points(interval)
    for i, x1 in enumerate(points):
        for x2 in points[i + 1:]:
            if not _pair_ok(evaluate, x1, x2, direction):
                return False
    return True


def _boundary_samples(feasible, limit=8):
    """Points inside feasible and just outside complementary components."""
    inside, outside = [], []
    if feasible == sp.S.Reals:
        return [0, 1, -1], []
    if feasible == sp.S.EmptySet:
        return [], [0, 1, -1]
    parts = feasible.args if isinstance(feasible, sp.Union) else (feasible,)
    for part in parts:
        if isinstance(part, sp.FiniteSet):
            inside.extend(list(part)[:limit])
            for value in list(part)[:limit]:
                outside.extend([value - sp.Rational(1, 10), value + sp.Rational(1, 10)])
            continue
        if not isinstance(part, sp.Interval):
            continue
        step = min(sp.Rational(1, 10), part.measure / 3)
        for end, open_end in ((part.start, part.left_open), (part.end, part.right_open)):
            if end in (-sp.oo, sp.oo):
                continue
            (outside if open_end else inside).append(end)
            if end == part.start:
                outside.append(end - step)
                if open_end:
                    inside.append(end + step)
            if end == part.end:
                outside.append(end + step)
                if open_end:
                    inside.append(end - step)
        if part.start.is_finite and part.end.is_finite:
            inside.append(sp.simplify((part.start + part.end) / 2))
        elif part.start == -sp.oo and part.end.is_finite:
            inside.append(part.end - 1)
        elif part.end == sp.oo and part.start.is_finite:
            inside.append(part.start + 1)
    clean = lambda rows: [sp.simplify(v) for v in dict.fromkeys(rows) if sp.sympify(v).is_extended_real is True]
    return ([v for v in clean(inside) if feasible.contains(v) is sp.S.true][:limit],
            [v for v in clean(outside) if feasible.contains(v) is sp.S.false][:2 * limit])


def verify(desc, model):
    if not desc.get('structure_supported'):
        return False
    if model.get('task') != 'monotonicity_parameter':
        return False
    try:
        compiled = _model(desc)
    except ValueError:
        return False
    if model.get('parameter') != compiled['parameter'] or model.get('direction') != compiled['direction']:
        return False
    if model.get('interval') != compiled['interval'] or model.get('structure', 'single') != compiled['structure']:
        return False
    p, x = compiled['p'], compiled['x']
    try:
        rebuilt = solve(desc)
    except ValueError:
        return False
    if sp.simplify(sp.SymmetricDifference(rebuilt['feasible_set'], model['feasible_set'])) != sp.S.EmptySet:
        return False
    if compiled['structure'] == 'piecewise':
        holds = lambda value: _piecewise_holds(compiled, value)
    elif compiled['structure'] == 'radical':
        holds = lambda value: _radical_holds(compiled, value)
    else:
        def holds(value):
            concrete = sp.simplify(compiled['expression'].subs(p, value))
            if concrete.free_symbols - {x}:
                return False
            return _holds_by_pairs(concrete, x, compiled['interval'], compiled['direction'],
                                   compiled['pieces'][0]['kind'])
    inside, outside = _boundary_samples(model['feasible_set'])
    member = lambda value: model['feasible_set'].contains(value) in (True, sp.S.true)
    satisfies_original = lambda value: compiled['parameter_set'].contains(value) in (True, sp.S.true) and holds(value)
    if any(not satisfies_original(value) for value in inside):
        return False
    # A point outside the claimed set that still works means the set is incomplete.
    return not any(satisfies_original(value) for value in outside if not member(value))
