"""FM-T3 R0: known strict monotonicity turns f(u)□f(v) into an input relation.

No problem IDs. Abstract f carries a given domain and direction; inputs are
fixed-coefficient polynomials of degree at most two (or constants).
"""
from copy import deepcopy

import sympy as sp

from ..problem_understanding.notation_parser import definition, parse
from .extremum_math import condition_set, domain, scalar
from .function_monotonicity import effective_domain
from .function_monotonicity import source as monotonicity_source

VERSION = 'monotonicity-inequality/v1'
FLIP = {'<': '>', '<=': '>=', '>': '<', '>=': '<='}
OPS = {'<': sp.Lt, '<=': sp.Le, '>': sp.Gt, '>=': sp.Ge}


def relevant(goal, entries=None):
    return (goal.get('kind') == 'find_range' and isinstance(goal.get('symbol'), str)
            and isinstance(goal.get('function_monotonicity'), dict))


def routed_description(goal, target_ref, entries):
    if relevant(goal, entries):
        return describe(goal, target_ref, entries)
    if goal.get('kind') != 'find_range' or not isinstance(goal.get('symbol'), str):
        return None
    # An extractor must not invent a proved property of an explicit function.
    # Discover that route from the original definition, leaving the goal intact.
    desc = describe(goal, target_ref, entries)
    return desc if desc.get('structure_supported') else None


def _explicit_basis(entries, target_ref):
    from .function_monotonicity import describe as describe_mono
    from .function_monotonicity import solve as solve_mono
    from .function_monotonicity import verify as verify_mono

    definitions = [row for row in entries if '/definitions/' in row['source_ref']]
    if len(definitions) != 1:
        raise ValueError('mono_ineq.explicit_basis_unavailable')
    text = definitions[0]['expression']
    ast = definition(text)
    if ast[0] != 'function_definition' or ast[3][:2] != ['call', 'piecewise']:
        raise ValueError('mono_ineq.piecewise_definition_required')
    goal = {'kind': 'prove_monotonicity_on_interval', 'expression': text.split('=', 1)[1],
            'variable': ast[2], 'function': ast[1], 'direction': 'increasing', 'input_domain': 'ℝ'}
    natural, _ = effective_domain(monotonicity_source(goal), goal)
    if not isinstance(natural, sp.Interval) and natural != sp.S.Reals:
        raise ValueError('mono_ineq.interval_domain_required')
    goal['input_domain'] = _interval_source_text(natural)
    for direction in ('increasing', 'decreasing'):
        goal['direction'] = direction
        child = describe_mono(goal, target_ref)
        try:
            proof = solve_mono(child, 'piecewise')
            if verify_mono(child, proof):
                return basis_from_proof(proof)
        except ValueError:
            continue
    raise ValueError('mono_ineq.explicit_basis_unavailable')


def declared_domain_ast(ast, function):
    if ast[0] == '=' and len(ast) == 3:
        for call, bounds in ((ast[1], ast[2]), (ast[2], ast[1])):
            if call == ['call', 'Dom', ['name', function]]:
                return bounds
    return None


def describe(goal, target_ref, entries):
    desc = {
        'source': deepcopy(goal), 'target_ref': target_ref,
        'given_definitions': deepcopy(entries),
        'source_refs': [target_ref, *[row['source_ref'] for row in entries]],
        'structure_supported': False, 'reason': '', 'version': VERSION,
    }
    try:
        mono = (goal['function_monotonicity'] if 'function_monotonicity' in goal
                else _explicit_basis(entries, target_ref))
        required = {'function', 'domain', 'direction', 'strict'}
        if not required <= set(mono) or set(mono) - required - {'basis', 'function_domain'}:
            raise ValueError('mono_ineq.monotonicity_fields')
        if mono.get('basis') not in (None, 'given', 'proved_monotonicity'):
            raise ValueError('mono_ineq.monotonicity_basis')
        if mono['direction'] not in ('increasing', 'decreasing'):
            raise ValueError('mono_ineq.direction_required')
        if mono['strict'] is not True:
            raise ValueError('mono_ineq.strict_required')
        function, symbol = mono['function'], goal['symbol']
        if parse(function) != ['name', function] or parse(symbol) != ['name', symbol]:
            raise ValueError('mono_ineq.name_required')
        interval = domain(parse(mono['domain']))
        if not isinstance(interval, sp.Interval) and interval is not sp.S.Reals:
            raise ValueError('mono_ineq.interval_domain_required')
        if interval is sp.S.Reals:
            interval = sp.Interval(-sp.oo, sp.oo)
        relation_rows, definition_rows, domain_rows = [], [], []
        for row in entries:
            ast = parse(row['expression'])
            bounds = declared_domain_ast(ast, function)
            if bounds is not None:
                domain_rows.append({'source_ref': row['source_ref'], 'domain_ast': bounds})
                continue
            if '/definitions/' in row['source_ref'] or ast[0] == 'function_definition':
                definition_rows.append(row)
                continue
            if ast[0] not in OPS:
                raise ValueError('mono_ineq.unprocessed_fact')
            relation_rows.append((row, ast))
        if len(relation_rows) != 1:
            raise ValueError('mono_ineq.single_relation_required')
        _, relation = relation_rows[0]
        left, right = relation[1], relation[2]
        if left[:2] != ['call', function] or right[:2] != ['call', function]:
            raise ValueError('mono_ineq.same_function_calls_required')
        names = {symbol: sp.Symbol(symbol, real=True)}
        # Validate inputs now; keep only JSON-safe fields on the description.
        _input_expr(left[2], names, symbol)
        _input_expr(right[2], names, symbol)
        desc.update(
            function=function, variable=symbol, direction=mono['direction'],
            strict=True, mono_domain=mono['domain'],
            relation_op=relation[0],
            left_ast=deepcopy(left[2]), right_ast=deepcopy(right[2]),
            definition_refs=[row['source_ref'] for row in definition_rows],
            domain_sources=domain_rows,
            mono_basis=mono.get('basis') or 'given',
            structure_supported=True,
        )
        _coverage(desc)
    except (ValueError, KeyError, TypeError, NotImplementedError, sp.PolynomialError) as exc:
        desc['structure_supported'] = False
        desc['reason'] = str(exc) or 'mono_ineq.unsupported'
    return desc


def _input_expr(ast, names, symbol):
    obligations = []
    expr = sp.cancel(scalar(ast, names, obligations))
    if any(item is not sp.S.true for item in obligations):
        raise ValueError('mono_ineq.input_obligation')
    variable = names[symbol]
    free = expr.free_symbols - {variable}
    if free:
        raise ValueError('mono_ineq.single_variable_required')
    if expr.free_symbols:
        poly = sp.Poly(sp.together(expr), variable)
        if poly.degree() > 2:
            raise ValueError('mono_ineq.degree_budget')
    return expr


def _hydrate(description):
    """Rebuild SymPy inputs from the JSON-safe description."""
    symbol = description['variable']
    names = {symbol: sp.Symbol(symbol, real=True)}
    interval = domain(parse(description['mono_domain']))
    if interval is sp.S.Reals:
        interval = sp.Interval(-sp.oo, sp.oo)
    return {
        'variable': names[symbol],
        'interval': interval,
        'left': _input_expr(description['left_ast'], names, symbol),
        'right': _input_expr(description['right_ast'], names, symbol),
    }


def _coverage(description):
    """Prove the order rule covers every input allowed by the original goal.

    A monotonic interval only certifies where f is defined and ordered. It
    does not exclude values outside that interval from the original problem.
    """
    parts = _hydrate(description)
    x, interval, u, v = (parts[k] for k in ('variable', 'interval', 'left', 'right'))
    requested = domain(parse(description['source'].get('input_domain', 'ℝ')))
    mono = description['source'].get('function_monotonicity', {})
    exact = domain(parse(mono['function_domain'])) if 'function_domain' in mono else None
    for row in description.get('domain_sources', []):
        stated = domain(row['domain_ast'])
        if exact is not None and stated != exact:
            raise ValueError('mono_ineq.conflicting_function_domain')
        exact = stated
    definitions = [row for row in description['given_definitions']
                   if row['source_ref'] in description['definition_refs']]
    if description['mono_basis'] == 'proved_monotonicity':
        if len(definitions) != 1:
            raise ValueError('mono_ineq.single_definition_required')
        text = definitions[0]['expression']
        ast = definition(text)
        if ast[:2] != ['function_definition', description['function']]:
            raise ValueError('mono_ineq.function_definition_required')
        goal = {'kind': 'prove_monotonicity_on_interval', 'expression': text.split('=', 1)[1],
                'variable': ast[2], 'direction': description['direction'], 'input_domain': description['mono_domain']}
        spec = monotonicity_source(goal)
        natural, _ = effective_domain(spec, goal)
        if exact is not None and exact - natural != sp.S.EmptySet:
            raise ValueError('mono_ineq.conflicting_function_domain')
        if exact is None:
            exact = natural
    elif definitions:
        raise ValueError('mono_ineq.definition_requires_proof')
    if exact is not None:
        if exact is sp.S.Reals:
            exact = sp.Interval(-sp.oo, sp.oo)
        if not isinstance(exact, sp.Interval) or interval - exact != sp.S.EmptySet:
            raise ValueError('mono_ineq.conflicting_function_domain')
    allowed = requested
    if exact is not None:
        allowed &= membership(u, x, exact) & membership(v, x, exact)
    usable = requested & membership(u, x, interval) & membership(v, x, interval)
    if sp.simplify(allowed - usable) != sp.S.EmptySet:
        raise ValueError('mono_ineq.incomplete_domain_coverage')
    return sp.simplify(usable)


def convert_relation(direction, op):
    """Public skill core: strict mono order on one interval."""
    if direction not in ('increasing', 'decreasing') or op not in FLIP:
        raise ValueError('mono_ineq.convert_inputs')
    return op if direction == 'increasing' else FLIP[op]


def _interval_source_text(interval):
    if interval == sp.S.Reals or interval == sp.Interval(-sp.oo, sp.oo):
        return 'ℝ'
    left = '-∞' if interval.inf == -sp.oo else str(interval.inf)
    right = '+∞' if interval.sup == sp.oo else str(interval.sup)
    return (('(' if interval.left_open else '[') + left + ',' + right
            + (')' if interval.right_open else ']'))


def basis_from_proof(model):
    """Turn a verified prove_monotonicity_on_interval certificate into M5 fields.

    R1: M5 consumes the covering strict interval after M3 (or another mono method)
    has already certified it; this does not re-run the piecewise proof.
    """
    if model.get('kind') != 'prove_monotonicity_on_interval':
        raise ValueError('mono_ineq.proof_kind_required')
    direction = model.get('requested_direction')
    if direction not in ('increasing', 'decreasing'):
        raise ValueError('mono_ineq.proof_direction_required')
    intervals = model.get(direction + '_intervals') or []
    if len(intervals) != 1:
        raise ValueError('mono_ineq.proof_single_interval_required')
    if not model.get('partition') or any(not row.get('strict') for row in model['partition']):
        raise ValueError('mono_ineq.proof_strict_required')
    if any(not row.get('merge', False) for row in model.get('junctions', [])):
        raise ValueError('mono_ineq.proof_cross_piece_required')
    return {
        'function': model.get('function', 'f'),
        'domain': _interval_source_text(intervals[0]),
        'direction': direction,
        'strict': True,
        'basis': 'proved_monotonicity',
    }


def membership(expr, variable, interval):
    if expr.free_symbols - {variable}:
        raise ValueError('mono_ineq.membership_variable')
    if not expr.free_symbols:
        return sp.S.Reals if bool(interval.contains(expr)) else sp.S.EmptySet
    parts = []
    if interval.left != -sp.oo:
        parts.append((sp.Gt if interval.left_open else sp.Ge)(expr, interval.left))
    if interval.right != sp.oo:
        parts.append((sp.Lt if interval.right_open else sp.Le)(expr, interval.right))
    if not parts:
        return sp.S.Reals
    return condition_set(sp.And(*parts) if len(parts) > 1 else parts[0], variable)


def _ordered_set(converted_op, u, v, variable):
    if sp.simplify(u - v) == 0:
        return sp.S.Reals if converted_op in ('<=', '>=') else sp.S.EmptySet
    converted = OPS[converted_op](u, v)
    if converted in (True, sp.S.true):
        return sp.S.Reals
    if converted in (False, sp.S.false):
        return sp.S.EmptySet
    return condition_set(converted, variable)


def solve(description):
    if not description.get('structure_supported'):
        raise ValueError(description.get('reason') or 'mono_ineq.unsupported')
    parts = _hydrate(description)
    variable, interval, u, v = parts['variable'], parts['interval'], parts['left'], parts['right']
    left_ok = membership(u, variable, interval)
    right_ok = membership(v, variable, interval)
    usable = _coverage(description)
    converted_op = convert_relation(description['direction'], description['relation_op'])
    ordered = _ordered_set(converted_op, u, v, variable)
    feasible = sp.simplify(sp.Intersection(usable, ordered))
    return {
        'task': 'known_monotonicity',
        'feasible_set': feasible,
        'usable_set': usable,
        'ordered_set': ordered,
        'left_ok': left_ok,
        'right_ok': right_ok,
        'converted_op': converted_op,
        'converted_relation': OPS[converted_op](u, v),
        'direction': description['direction'],
        'relation_op': description['relation_op'],
        'variable': description['variable'],
        'function': description['function'],
        'mono_interval': interval,
        'left_input': u,
        'right_input': v,
        'version': VERSION,
    }


def verify(description, model):
    """Recompute from retained inputs; do not call solve()."""
    try:
        if not description.get('structure_supported'):
            return False
        if describe(description['source'], description['target_ref'], description['given_definitions']) != description:
            return False
        if model.get('version') != VERSION or model.get('task') != 'known_monotonicity':
            return False
        if model.get('direction') != description['direction']:
            return False
        if model.get('relation_op') != description['relation_op']:
            return False
        parts = _hydrate(description)
        variable, u, v = parts['variable'], parts['left'], parts['right']
        if sp.simplify(model['left_input'] - u) != 0 or sp.simplify(model['right_input'] - v) != 0:
            return False
        usable = _coverage(description)
        converted_op = convert_relation(description['direction'], description['relation_op'])
        if model.get('converted_op') != converted_op:
            return False
        ordered = _ordered_set(converted_op, u, v, variable)
        feasible = sp.simplify(sp.Intersection(usable, ordered))
        return bool(sp.simplify(sp.SymmetricDifference(model['feasible_set'], feasible)) == sp.S.EmptySet)
    except (ValueError, TypeError, NotImplementedError, KeyError, sp.PolynomialError):
        return False
