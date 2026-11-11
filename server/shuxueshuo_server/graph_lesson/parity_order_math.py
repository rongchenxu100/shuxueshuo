"""FP-T4 R1–R2: one comparison of two values of the same function, by parity.

Odd f turns ±f(u) ± f(v) □ 0 into f(a) □ f(w) and drops f only on a domain D
where f is strictly monotone. That direction comes from a printed half-axis rule
(proved here, carried to the mirrored half by oddness and joined across 0), from
a printed direction on all of D, or from a printed half-axis direction carried
the same way. Even f compares f(|u|) □ f(|v|) on the non-negative side, whose
strict direction is the printed one or its reflection; |u| □ |v| is solved as
(u−v)(u+v) □ 0. A half-axis direction that does not reach 0 cannot be joined for
an abstract f: that is a capability gap, never an answer. A domain parameter is
fixed only by the borrowed T2 subtask (R2, A20). Inputs are rational polynomials
of degree ≤ 2.
"""
from copy import deepcopy

import sympy as sp

from . import parity_extension_math as extension
from . import parity_parameter_math as base
from .extremum_math import domain as parse_domain
from . import parity_inequality_inputs as algebra
from .parity_extension_math import combined_rule, reflect, region

VERSION = 'parity-inequality/r2-order-v1'
OPS = {'<': sp.Lt, '<=': sp.Le, '>': sp.Gt, '>=': sp.Ge}
FLIP = {'<': '>', '<=': '>=', '>': '<', '>=': '<='}
LIMITS = {'degree': 2, 'rule_degree': 2}
MODEL_KEYS = {'version', 'description', 'variable', 'operator', 'left_input', 'right_input', 'certificate',
              'legal_set', 'converted_operator', 'ordered_set', 'solution', 'status', 'borrow'}
DIRECTIONS = ('increasing', 'decreasing')
_DUMMY = sp.Symbol('_order_dummy', real=True)


def _name(ref):
    return ref[1].rsplit(':', 1)[-1] if isinstance(ref, list) and ref[:1] == ['ref'] else None


def _calls(ast):
    if not isinstance(ast, list):
        return []
    if ast[:1] == ['function_call']:
        return [ast]
    return [c for child in ast[1:] for c in _calls(child)]


def _bound(ast, variable):
    """Input AST with the solved variable as the bound argument; any other reference is unsupported."""
    if not isinstance(ast, list):
        return ast
    if ast[:1] == ['ref']:
        if ast[-1] == 'scalar' and _name(ast) == variable:
            return ['bound', 'function_argument']
        raise ValueError('parity_ineq.input_other_symbol')
    if ast[:1] in (['function_call'], ['bound']):
        raise ValueError('parity_ineq.nested_call')
    return [_bound(v, variable) for v in ast]


def read_input(ast, x):
    return algebra.read(ast, x)


def _terms(ast, function, variable):
    """[(sign, bound input)] and the constant of a linear relation side; only ±1 · f(·) and constants."""
    calls = _calls(ast)
    if not calls:
        return [], ast
    op = ast[0]
    if op == 'function_call':
        if _name(ast[1]) != function:
            raise ValueError('parity_ineq.other_function')
        return [(1, _bound(ast[2], variable))], None
    if op == 'neg':
        terms, constant = _terms(ast[1], function, variable)
        return [(-s, a) for s, a in terms], (['neg', constant] if constant is not None else None)
    if op in ('+', '-'):
        (a, p), (b, q) = (_terms(side, function, variable) for side in ast[1:3])
        sign = 1 if op == '+' else -1
        if q is not None:
            q = q if sign == 1 else ['neg', q]
        constant = p if q is None else q if p is None else ['+', p, q]
        return [*a, *((sign * s, v) for s, v in b)], constant
    raise ValueError('parity_ineq.relation_form_unsupported')


def relation_terms(relation_ast, function, variable):
    """L □ R as Σ s·f(input) □ 0; returns (op, [(sign, input_ast)])."""
    if not isinstance(relation_ast, list) or relation_ast[0] not in OPS:
        raise ValueError('parity_ineq.single_inequality_required')
    (left, p), (right, q) = (_terms(side, function, variable) for side in relation_ast[1:3])
    for constant in (p, q):
        try:
            nonzero = constant is not None and base.polynomial(constant, _DUMMY, _DUMMY, None) != 0
        except ValueError:
            nonzero = True
        if nonzero:
            raise ValueError('parity_ineq.threshold_value_unknown')
    terms = [*left, *((-s, a) for s, a in right)]
    if not 1 <= len(terms) <= 2:
        raise ValueError('parity_ineq.relation_form_unsupported')
    return relation_ast[0], terms


def comparison(op, terms, x):
    """Odd f: s·f(u) = f(s·u); f(a) + f(b) □ 0 ⇔ f(a) □ f(−b); a lone f(a) □ 0 compares with f(0)."""
    (s1, u1), *rest = [(s, read_input(a, x)) for s, a in terms]
    left = s1 * u1
    right = -rest[0][0] * rest[0][1] if rest else sp.S.Zero
    return op, sp.expand(left), sp.expand(right)


def _plain(op, terms):
    """Already f(u) □ f(v): parity is not needed for the comparison itself."""
    return len(terms) == 2 and [s for s, _ in terms] == [1, -1]


def _interval(value):
    if value is sp.S.Reals:
        return sp.Interval(-sp.oo, sp.oo)
    if not isinstance(value, sp.Interval):
        raise ValueError('parity_ineq.interval_domain_required')
    return value


def _side(interval):
    if interval.inf >= 0:
        return 1
    if interval.sup <= 0:
        return -1
    return 0


def _strict_direction(rule, known, x):
    """Strict direction of a degree ≤ 2 polynomial on an interval from its derivative; None if not monotone."""
    inner = sp.Interval.open(known.inf, known.sup)
    d = sp.diff(rule, x)
    if d == 0:
        return None
    if sp.solveset(d < 0, x, inner) == sp.S.EmptySet:
        return 'increasing'
    if sp.solveset(d > 0, x, inner) == sp.S.EmptySet:
        return 'decreasing'
    return None


def _other(direction):
    return DIRECTIONS[1 - DIRECTIONS.index(direction)]


def _even_side(cert, side):
    """Even f reverses direction on the mirrored side; the comparison runs on the non-negative side."""
    cert.update(positive_direction=cert['direction'] if side == 1 else _other(cert['direction']))
    return cert


def _rule_certificate(desc):
    ext = desc['direction_source']['extension']
    x = sp.Symbol(desc['variable'], real=True)
    rule, known = combined_rule(ext)
    try:
        poly = sp.Poly(extension.rule_polynomial(ext['rule_ast'], x), x)
    except (ValueError, sp.PolynomialError) as exc:
        raise ValueError('parity_ineq.rule_form_unsupported') from exc
    if poly.degree() > LIMITS['rule_degree']:
        raise ValueError('parity_ineq.degree_budget')
    if ext['domain_ast'] is None:
        raise ValueError('parity_ineq.domain_required')
    domain = _interval(region(ext['domain_ast']))
    known = _interval(known)
    side = _side(known)
    if side == 0:
        raise ValueError('parity_ineq.rule_range_not_one_side')
    if (domain - known - reflect(known)) - sp.FiniteSet(0) != sp.S.EmptySet:
        raise ValueError('parity_ineq.rule_not_covering_domain')
    direction = _strict_direction(rule, known, x)
    if direction is None:
        raise ValueError('parity_ineq.rule_not_monotone')
    if desc['property'] == 'even':
        # f(0) is not fixed by evenness: 0 must lie in the known range to be compared.
        if domain.contains(0) is sp.true and known.contains(0) is not sp.true:
            raise ValueError('parity_ineq.junction_unknown')
        return _even_side({'kind': 'even_rule', 'domain': domain, 'direction': direction, 'rule': rule,
                           'known': known, 'reflected': reflect(known) & domain}, side)
    # f(0)=0 for an odd f whose domain holds 0; across 0 the halves join only if
    # the known half lies strictly on the side of 0 that the direction requires.
    wanted = side if direction == 'increasing' else -side
    rest = known - sp.FiniteSet(0)
    bad = sp.solveset((rule <= 0) if wanted == 1 else (rule >= 0), x, rest)
    if bad != sp.S.EmptySet:
        raise ValueError('parity_ineq.junction_not_monotone')
    zero = ('in_known' if known.contains(0) is sp.true else
            'forced_zero' if domain.contains(0) is sp.true else 'not_in_domain')
    return {'kind': 'rule', 'domain': domain, 'direction': direction, 'rule': rule, 'known': known,
            'reflected': reflect(known) & domain, 'zero': zero, 'known_sign': wanted}


def _read_region(ast):
    """Extracted fact ASTs and parsed printed text share interval nodes; the parser's open pair needs the domain reader."""
    try:
        return _interval(region(ast))
    except ValueError:
        return _interval(parse_domain(ast))


def domain_of(desc):
    if desc.get('domain_ast') is not None:
        return _read_region(desc['domain_ast'])
    return _interval(parse_domain(base_parse(desc['domain_text'])))


def interval_of(source):
    if source.get('interval_ast') is not None:
        return _read_region(source['interval_ast'])
    return _interval(parse_domain(base_parse(source['interval'])))


def _given_certificate(desc):
    source = desc['direction_source']
    domain = domain_of(desc)
    interval = interval_of(source)
    direction = source['direction']
    if interval - domain != sp.S.EmptySet:
        raise ValueError('parity_ineq.monotonic_interval_outside_domain')
    if desc['property'] == 'even':
        side = _side(interval)
        if side == 0:
            # An even function is never strictly monotone on an interval with 0 inside.
            raise ValueError('parity_ineq.parity_conflict')
        if (domain - interval - reflect(interval)) - sp.FiniteSet(0) != sp.S.EmptySet:
            raise ValueError('parity_ineq.direction_not_covering_domain')
        if domain.contains(0) is sp.true and interval.contains(0) is not sp.true:
            raise ValueError('parity_ineq.junction_unknown')
        return _even_side({'kind': 'even_given', 'domain': domain, 'direction': direction, 'interval': interval,
                           'reflected': reflect(interval) & domain}, side)
    if domain - interval == sp.S.EmptySet:
        return {'kind': 'given', 'domain': domain, 'direction': direction, 'interval': interval,
                'reflected': sp.S.EmptySet, 'zero': 'in_interval' if interval.contains(0) is sp.true else 'not_in_domain'}
    side = _side(interval)
    if side == 0:
        raise ValueError('parity_ineq.direction_not_covering_domain')
    if (domain - interval - reflect(interval)) - sp.FiniteSet(0) != sp.S.EmptySet:
        raise ValueError('parity_ineq.direction_not_covering_domain')
    if interval.contains(0) is not sp.true:
        raise ValueError('parity_ineq.junction_unknown')
    return {'kind': 'given_half', 'domain': domain, 'direction': direction, 'interval': interval,
            'reflected': reflect(interval) & domain, 'zero': 'in_interval'}


def base_parse(text):
    from ..problem_understanding.notation_parser import parse
    return parse(text)


def certificate(desc):
    return (_rule_certificate if desc['direction_source']['kind'] == 'rule' else _given_certificate)(desc)


def compare_direction(cert):
    """Direction on the side where inputs are compared: all of D (odd) or the non-negative side (even)."""
    return cert.get('positive_direction', cert['direction'])


def legal_set(u_list, x, domain):
    allowed = sp.S.Reals
    for u in u_list:
        allowed &= algebra.preimage(u, x, domain)
    return sp.simplify(allowed)


def _ordered(op, a, w, x):
    return algebra.condition(a - w, op, x)


def source_allowed(desc, x):
    return algebra.allowed(desc, [a for _, a in desc['terms']], x)


def ordered_inputs(op, a, w, x, even):
    """a □ w, or |a| □ |w| as (a−w)(a+w) □ 0: both sides are non-negative, so squaring keeps the order."""
    finite = algebra.preimage(a, x, sp.S.Reals) & algebra.preimage(w, x, sp.S.Reals)
    if even:
        return _ordered(op, sp.expand((a - w) * (a + w)), sp.S.Zero, x) & finite
    return _ordered(op, a, w, x) & finite


def even_terms(desc):
    """Even f relates f(u) and f(−u) only; a sum or a lone value against 0 needs an unknown value."""
    if desc['property'] != 'even':
        return
    signs = [s for s, _ in desc['terms']]
    if signs != [1, -1]:
        raise ValueError('parity_ineq.even_sum_unsupported' if len(signs) == 2 else 'parity_ineq.zero_value_unknown')


def solve(desc):
    if not desc.get('structure_supported'):
        raise ValueError(desc.get('reason') or 'parity_ineq.unsupported')
    if desc.get('parameter'):
        if not desc.get('borrowed'):
            raise ValueError('parity_ineq.parameter_requires_borrow')
        return _solve_borrowed({k: v for k, v in desc.items() if k != 'borrowed'}, desc['borrowed'])
    return _solve(desc)


def _solve(desc):
    x = sp.Symbol(desc['variable'], real=True)
    even_terms(desc)
    cert = certificate(desc)
    op, a, w = comparison(desc['operator'], desc['terms'], x)
    inputs = [read_input(t, x) for _, t in desc['terms']]
    if len(inputs) == 1 and cert['domain'].contains(0) is not sp.true:
        raise ValueError('parity_ineq.zero_not_in_domain')
    legal = legal_set(inputs, x, cert['domain']) & source_allowed(desc, x)
    converted = op if compare_direction(cert) == 'increasing' else FLIP[op]
    ordered = ordered_inputs(converted, a, w, x, desc['property'] == 'even')
    solution = sp.simplify(legal & ordered)
    return {'version': VERSION, 'description': deepcopy(desc), 'variable': x, 'operator': op,
            'left_input': a, 'right_input': w, 'certificate': cert, 'legal_set': legal,
            'converted_operator': converted, 'ordered_set': ordered, 'solution': solution, 'status': 'determined',
            'borrow': None}


def _substitute(ast, ref, literal):
    if not isinstance(ast, list):
        return ast
    if ast == ['ref', ref, 'scalar']:
        return deepcopy(literal)
    return [_substitute(v, ref, literal) for v in ast]


def instantiate(desc, value):
    """The statement with the domain parameter replaced by one returned value; checked like a numeric one."""
    from .symmetry_value_math import _literal
    ref, literal = desc['parameter']['ref'], _literal(sp.Rational(value))
    out = deepcopy({k: v for k, v in desc.items() if k != 'borrowed'})
    out['domain_ast'] = _substitute(out['domain_ast'], ref, literal)
    source = out['direction_source']
    source['interval_ast'] = _substitute(source['interval_ast'], ref, literal)
    out['parameter'] = None
    return out


def _check_instance(desc):
    if reflect(domain_of(desc)) != domain_of(desc):
        raise ValueError('parity_ineq.domain_not_symmetric')
    return _solve(desc)


def _solve_borrowed(desc, borrowed):
    """One returned parameter value is instantiated and solved; several values are not taught yet (gap)."""
    values = borrowed['parameter_set']
    if not isinstance(values, sp.FiniteSet):
        raise ValueError('parity_ineq.parameter_family_unsupported')
    if len(values) != 1:
        raise ValueError('parity_ineq.parameter_candidates_unsupported')
    value, = values
    instance = instantiate(desc, value)
    if borrowed['instantiated_domain'] != domain_of(instance):
        raise ValueError('parity_ineq.instantiated_domain_mismatch')
    model = _check_instance(instance)
    model['borrow'] = {'output': deepcopy(borrowed), 'parameter_value': value}
    return model


def _basis(mono, x_name='x'):
    basis = mono.get('basis')
    if basis in (None, 'given'):
        return {'kind': 'stated', 'statement': ''}
    if basis == 'proved_monotonicity' or (isinstance(basis, dict) and basis.get('kind') == 'proved_monotonicity'):
        raise ValueError('parity_ineq.basis_not_source')
    if not isinstance(basis, dict):
        raise ValueError('parity_ineq.monotonicity_basis')
    from .monotonicity_parameter_math import _basis_direction
    try:
        implied = _basis_direction(basis, mono['function'])
    except ValueError as exc:
        raise ValueError('parity_ineq.monotonicity_basis') from exc
    if implied is not None and implied != mono['direction']:
        raise ValueError('parity_ineq.basis_direction_conflict')
    return deepcopy(basis)


def _origin_rows(entries, function):
    from .parity_sign_math import _zero_value
    return [r for r in entries if _zero_value(r['ast'], function) == ['number', '0']]


def _relation_rows(entries, function, variable):
    rows = [r for r in entries if isinstance(r['ast'], list) and r['ast'][0] in OPS and _calls(r['ast'])]
    used = [*rows, *_origin_rows(entries, function), *_domain_rows(entries, function),
            *algebra.constraint_rows(entries, variable),
            *(r for r in entries if r['ast'][0] == 'function_parity' and _name(r['ast'][1]) == function)]
    if any(r not in used for r in entries):
        raise ValueError('parity_ineq.unprocessed_fact')
    if len(rows) != 1:
        raise ValueError('parity_ineq.single_inequality_required')
    return rows[0]


def _domain_rows(entries, function):
    return [r for r in entries if r['ast'][0] == '=' and r['ast'][1][:2] == ['call', 'Dom']
            and _name(r['ast'][1][2]) == function]


def _scalars(ast):
    if not isinstance(ast, list):
        return set()
    if ast[:1] == ['ref']:
        return {ast[1]} if ast[-1] == 'scalar' else set()
    return set().union(*(_scalars(v) for v in ast))


def _named(ast, parameter):
    """Parsed printed text: the parameter's name becomes its source reference; any other name is unsupported."""
    if not isinstance(ast, list):
        return ast
    if ast[:1] == ['name']:
        if parameter is not None and ast[1] == parameter['name']:
            return ['ref', parameter['ref'], 'scalar']
        raise ValueError('parity_ineq.domain_other_symbol')
    return [_named(v, parameter) for v in ast]


def _same_domain(asts, parameter):
    if parameter is None:
        values = [_read_region(v) for v in asts]
        return all(v == values[0] for v in values[1:])
    from .parameter_domain import compile_domain
    p = sp.Symbol(parameter['name'], real=True)
    trees = [compile_domain(v, p, parameter['ref']) for v in asts]
    return all(t == trees[0] for t in trees[1:])


def quantified_direction(entries):
    """Reuse the checked two-input, distinctness-guarded quotient/product contract."""
    from .monotonicity_parameter_math import _source_pair
    pairs = [(row, pair) for row in entries if (pair := _source_pair(row['expression'])) is not None]
    if len(pairs) != 1:
        return None
    row, pair = pairs[0]
    try:
        interval = _interval(pair['region'])
    except ValueError:
        return None
    text = (('(' if interval.left_open else '[') + str(interval.inf).replace('-oo', '-∞') + ','
            + str(interval.sup).replace('oo', '∞') + (')' if interval.right_open else ']'))
    return {'source_ref': row['source_ref'], 'monotonicity': {
        'function': pair['function'], 'domain': text, 'direction': pair['direction'],
        'strict': True, 'basis': pair['basis']}}


def describe_given(goal, target_ref, entries, desc, *, inferred=None):
    """Printed strict direction (function_monotonicity) and the inequality as a fact."""
    mono = inferred['monotonicity'] if inferred else goal['function_monotonicity']
    function, variable = mono.get('function'), goal.get('symbol')
    parity = [r for r in entries if r['ast'][0] == 'function_parity' and _name(r['ast'][1]) == function]
    if len(parity) != 1:
        return None
    try:
        if mono.get('strict') is not True:
            raise ValueError('parity_ineq.strict_required')
        if mono.get('direction') not in DIRECTIONS:
            raise ValueError('parity_ineq.direction_required')
        row = _relation_rows([r for r in entries if not inferred or r['source_ref'] != inferred['source_ref']],
                             function, variable)
        op, terms = relation_terms(row['ast'], function, variable)
        domains = _domain_rows(entries, function)
        scalars = set().union(*(_scalars(r['ast'][2]) for r in domains))
        if len(scalars) > 1:
            raise ValueError('parity_ineq.parameter_count')
        parameter = None
        if scalars:
            ref, = scalars
            if _name(['ref', ref]) == variable:
                raise ValueError('parity_ineq.parameter_is_variable')
            owned = {*(r['source_ref'] for r in domains), parity[0]['source_ref']}
            parameter = {'ref': ref, 'name': ref.rsplit(':', 1)[-1],
                         'source_refs': [r['source_ref'] for r in entries if r['source_ref'] in owned]}
        stated = mono.get('function_domain')
        stated_ast = _named(base_parse(stated), parameter) if stated else None
        interval_ast = _named(base_parse(mono['domain']), parameter)
        asts = [r['ast'][2] for r in domains] + ([stated_ast] if stated_ast is not None else [])
        if not asts:
            raise ValueError('parity_ineq.domain_required')
        if not _same_domain(asts, parameter):
            raise ValueError('parity_ineq.conflicting_function_domain')
        prop = parity[0]['ast'][2]
        desc.update(function=function, variable=variable, property=prop, operator=op,
                    terms=[[s, a] for s, a in terms], relation_ast=deepcopy(row['ast']),
                    relation_source_ref=row['source_ref'], parity_source_ref=parity[0]['source_ref'],
                    domain_ast=deepcopy(asts[0]), domain_text=None,
                    domain_source_refs=([r['source_ref'] for r in domains]
                                        or [target_ref + '/function_monotonicity/function_domain']),
                    direction_source={'kind': 'given', 'interval': mono['domain'], 'interval_ast': interval_ast,
                                      'direction': mono['direction'], 'basis': None,
                                      'source_ref': inferred['source_ref'] if inferred else target_ref + '/function_monotonicity'},
                    parameter=parameter)
        if inferred:
            desc['direction_source']['from_fact'] = True
        origins = _origin_rows(entries, function)
        if origins and (prop != 'odd' or parameter is not None or domain_of(desc).contains(0) is not sp.true):
            raise ValueError('parity_ineq.unprocessed_fact')
        # Preserve the old polynomial comparison route. Additional conditions or
        # non-polynomial inputs need this route's explicit consumption/guards.
        x = sp.Symbol(variable, real=True)
        polynomial_inputs = all(read_input(a, x).is_polynomial(x) and algebra.guard([a], x) == sp.S.Reals
                                for _, a in terms)
        if (parameter is None and _plain(op, terms) and not origins
                and not algebra.constraint_rows(entries, variable) and polynomial_inputs
                and not inferred and domain_of(desc).is_subset(interval_of(desc['direction_source']))):
            return None
        desc['direction_source']['basis'] = _basis(mono)
        even_terms(desc)
        if parameter is None:
            _check_instance(desc)
        desc['structure_supported'] = True
    except (ValueError, TypeError, KeyError, IndexError, NotImplementedError, sp.PolynomialError) as exc:
        desc['reason'] = str(exc)
    return desc


def describe_rule(goal, goal_ast, target_ref, entries, desc, ext):
    """Half-axis rule in the goal (as in R0) and a composite comparison as the asked inequality."""
    name, variable = goal['function'], goal['variable']
    op, terms = relation_terms(goal_ast['value'], name, variable)
    desc.update(function=name, variable=variable, property=ext['property'], operator=op,
                terms=[[s, a] for s, a in terms], relation_ast=deepcopy(goal_ast['value']),
                relation_source_ref=desc.get('relation_source_ref', target_ref + '/expression'),
                parity_source_ref=ext['parity_source_ref'],
                domain_ast=deepcopy(ext['domain_ast']), domain_text=None,
                domain_source_refs=ext['domain_source_refs'],
                direction_source={'kind': 'rule', 'extension': ext}, parameter=None)
    _solve(desc)


def _sign(value):
    value = sp.nsimplify(value)
    return 0 if value == 0 else (1 if value > 0 else -1)


def _limit(expr, x, point, side):
    return sp.limit(expr, x, point, dir='+' if side == 1 else '-')


def _quotient_direction(rule, known, x):
    """Independent of the derivative: the difference quotient of a ≤ 2 degree rule is b + c(s+t)."""
    poly = sp.Poly(rule, x)
    if poly.degree() > LIMITS['rule_degree']:
        return None
    coeffs = poly.all_coeffs()[::-1] + [0, 0, 0]
    b, c = coeffs[1], coeffs[2]
    s = sp.Symbol('s', real=True)
    quotient = b + c * s
    ends = [_limit(quotient, s, 2 * known.inf, 1) if known.inf.is_finite else (c * -sp.oo if c else b),
            _limit(quotient, s, 2 * known.sup, -1) if known.sup.is_finite else (c * sp.oo if c else b)]
    signs = {1 if e > 0 else -1 if e < 0 else 0 for e in ends}
    return 'increasing' if signs - {0} == {1} else 'decreasing' if signs - {0} == {-1} else None


def _verify_rule(cert, desc, x):
    ext = desc['direction_source']['extension']
    rule, known = combined_rule(ext)
    if sp.expand(cert['rule'] - rule) != 0 or cert['known'] != _interval(known):
        return False
    known = cert['known']
    direction = _quotient_direction(rule, known, x)
    if direction is None or direction != cert['direction']:
        return False
    side = 1 if known.inf >= 0 else -1 if known.sup <= 0 else 0
    if side == 0:
        return False
    if desc['property'] == 'even':
        domain = cert['domain']
        return (cert['kind'] == 'even_rule' and _even_ok(cert, domain, known, side)
                and (domain - known - reflect(known)).is_subset(sp.FiniteSet(0)))
    wanted = side if direction == 'increasing' else -side
    inner = known.inf if side == 1 else known.sup
    if cert['kind'] != 'rule' or inner != 0 or wanted != cert['known_sign']:
        return False
    # Moving away from 0 the rule moves toward `wanted`, so it stays on that side iff its value at 0 does not oppose.
    at_zero = sp.expand(rule.subs(x, 0))
    return _sign(at_zero) in (0, wanted) and (known.contains(0) is not sp.true or at_zero == 0)


def _even_ok(cert, domain, interval, side):
    """Reflected direction is reversed; 0 in D must be inside the proved interval."""
    positive = cert['direction'] if side == 1 else _other(cert['direction'])
    return (cert['positive_direction'] == positive
            and (domain.contains(0) is not sp.true or interval.contains(0) is sp.true))


def _verify_given(cert, desc):
    source = desc['direction_source']
    domain = domain_of(desc)
    interval = interval_of(source)
    if cert['domain'] != domain or cert['interval'] != interval or cert['direction'] != source['direction']:
        return False
    if not interval.is_subset(domain):
        return False
    if desc['property'] == 'even':
        side = 1 if interval.inf >= 0 else -1 if interval.sup <= 0 else 0
        return (cert['kind'] == 'even_given' and side != 0 and _even_ok(cert, domain, interval, side)
                and (domain - interval - reflect(interval)) == sp.S.EmptySet)
    if cert['kind'] == 'given':
        return domain.is_subset(interval)
    if cert['kind'] != 'given_half' or interval.contains(0) is not sp.true:
        return False
    return (domain - interval - reflect(interval)).is_subset(sp.FiniteSet(0))


def _cells(points, inside):
    from .function_cells import cells
    return cells(sp.S.Reals, points)


def verify(desc, model):
    """Rebuild the certificate without the solver, then read every cell between cut points.

    With a domain parameter, the model must be the instance at the borrowed value; the
    borrowed subtask itself is re-verified against the frozen context by the runtime.
    """
    try:
        if desc.get('parameter'):
            borrow = model['borrow']
            value = borrow['parameter_value']
            if borrow['output']['parameter_set'] != sp.FiniteSet(value):
                return False
            instance = instantiate(desc, value)
            if borrow['output']['instantiated_domain'] != domain_of(instance):
                return False
            return _verify(instance, model)
        return model.get('borrow') is None and _verify(desc, model)
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, NotImplementedError, sp.PolynomialError):
        return False


def _verify(desc, model):
    if not desc.get('structure_supported') or model.get('description') != desc:
        return False
    if set(model) != MODEL_KEYS or model['version'] != VERSION or model['status'] != 'determined':
        return False
    x = sp.Symbol(desc['variable'], real=True)
    even = desc['property'] == 'even'
    if model['variable'] != x or desc['property'] not in ('odd', 'even'):
        return False
    inputs = [(s, read_input(a, x)) for s, a in desc['terms']]
    if even and [s for s, _ in inputs] != [1, -1]:
        return False
    a = inputs[0][0] * inputs[0][1]
    w = -inputs[1][0] * inputs[1][1] if len(inputs) == 2 else sp.S.Zero
    if (model['operator'] != desc['operator'] or sp.expand(model['left_input'] - a) != 0
            or sp.expand(model['right_input'] - w) != 0):
        return False
    cert = model['certificate']
    if cert['kind'] in ('rule', 'even_rule'):
        if not _verify_rule(cert, desc, x) or cert['domain'] != domain_of(desc):
            return False
    elif not _verify_given(cert, desc):
        return False
    domain = cert['domain']
    if reflect(domain) != domain or (len(inputs) == 1 and domain.contains(0) is not sp.true):
        return False
    converted = desc['operator'] if compare_direction(cert) == 'increasing' else FLIP[desc['operator']]
    if model['converted_operator'] != converted:
        return False
    asts = [ast for _, ast in desc['terms']]
    allowed = source_allowed(desc, x)
    points = algebra.source_points(asts) | set(allowed.boundary)
    for _, u in inputs:
        points |= set(algebra.cut_points(u, x))
        for p in domain.boundary:
            if p.is_finite:
                points |= set(algebra.cut_points(u - p, x))
    for target in ((w, -w) if even else (w,)):
        points |= set(algebra.cut_points(a - target, x))
    size = (lambda v: abs(v)) if even else (lambda v: v)
    solution, legal = model['solution'], model['legal_set']
    from .function_cells import evaluate
    for cell, rep in _cells(points, domain):
        original = [evaluate(ast, rep) for ast in asts]
        finite = all(valid for valid, _ in original)
        ok = (finite and allowed.contains(rep) is sp.true
              and all(domain.contains(v) is sp.true for _, v in original))
        a_value, w_value = a.subs(x, rep), w.subs(x, rep)
        ordered = (a_value.is_finite is True and w_value.is_finite is True
                   and bool(OPS[converted](size(a_value), size(w_value))))
        for claimed, truth in ((legal, ok), (solution, ok and ordered), (model['ordered_set'], ordered)):
            if not algebra.matches(claimed, cell, truth):
                return False
    return True
