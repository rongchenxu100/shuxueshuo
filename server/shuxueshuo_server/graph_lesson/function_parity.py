"""FP-T1 parity by the definition: domain symmetry first, then two identities.

Odd and even are decided independently. Each is either proved by a complete
identity certificate from the shared exact-cell comparator, refuted by an
exact witness on the original syntax, or left unresolved. Only two decided
properties produce one of the four classifications; an unproved identity is
never reported as "neither".
"""

from copy import deepcopy

import sympy as sp

from ..problem_understanding.notation_compile import NotationValidator
from ..problem_understanding.notation_parser import NotationError, definition
from . import function_cells as cells
from .function_cells import VERSION as COMPARISON_VERSION
from .function_cells import evaluate as _evaluate
from .stage_one import contracts
from .stage_one.function_domain import ARGUMENT, source_pointer
from .stage_three.verification import _rational_between

VERSION = 'function-parity-definition/v2'
KIND = 'determine_function_parity'
CLASSIFICATIONS = {
    ('proved', 'refuted'): 'odd_only',
    ('refuted', 'proved'): 'even_only',
    ('proved', 'proved'): 'both',
    ('refuted', 'refuted'): 'neither',
}
_WITNESS_POINTS = [sp.Integer(1), sp.Integer(2), sp.Integer(3), sp.Rational(1, 2), sp.Integer(4),
                   sp.Integer(5), sp.Rational(1, 3), sp.Rational(3, 2), sp.Integer(6), sp.Integer(10)]
_NICE_POINTS = [sp.Integer(n) for n in (0, 1, -1, 2, -2, 3, -3, 4, -4, 5, -5, 6, -6)] + [
    sp.Rational(n, 2) for n in (1, -1, 3, -3, 5, -5)]


def _copy(value):
    # deepcopy re-creates assumption symbols, so copied guards stop comparing equal.
    from .stage_three.trajectory import decode_value, encode_value
    return decode_value(encode_value(value))


def reflect_ast(ast):
    """g(x)=f(-x): substitute the bound argument as a whole, never a name."""
    if ast == ARGUMENT:
        return ['neg', deepcopy(ARGUMENT)]
    return [reflect_ast(child) if isinstance(child, list) else child for child in ast]


def _negate_endpoint(ast):
    if ast == ['infinity']:
        return ['neg', ['infinity']]
    if ast[0] == 'neg':
        return deepcopy(ast[1])
    return ['neg', deepcopy(ast)]


def reflect_domain_ast(ast):
    if ast == ['real']:
        return ['real']
    if ast[0] == 'interval':
        return ['interval', ast[2], ast[1], _negate_endpoint(ast[4]), _negate_endpoint(ast[3])]
    if ast[0] == 'set':
        return ['set', *(_negate_endpoint(point) for point in ast[1:])]
    if ast[0] in ('∪', '∩', 'set_difference'):
        return [ast[0], reflect_domain_ast(ast[1]), reflect_domain_ast(ast[2])]
    raise NotationError('function_parity.domain_reflection_unsupported')


def reflect_set(value):
    """-D = {-x : x in D}; open/closed ends swap with their endpoints."""
    return cells.reflect_set(value)


def _same_set(left, right):
    return left - right == sp.S.EmptySet and right - left == sp.S.EmptySet


def _member(domain, point):
    return domain.contains(point) is sp.true


def _sample(value):
    """A readable exact point of a nonempty set; small integers first."""
    for point in _NICE_POINTS:
        if _member(value, point):
            return point
    if isinstance(value, sp.FiniteSet):
        return min(value, key=lambda point: (abs(point), point))
    if isinstance(value, sp.Interval):
        return _rational_between(value.start, value.end)
    if isinstance(value, (sp.Union, sp.Complement)):
        for part in value.args if isinstance(value, sp.Union) else [value.args[0]]:
            try:
                point = _sample(part)
            except NotationError:
                continue
            if _member(value, point):
                return point
    raise NotationError('function_parity.witness_unavailable')


def reflected_descriptor(function):
    return {**deepcopy(function), 'function_ref': function['function_ref'] + '#reflected',
            'expression_ast': reflect_ast(function['expression_ast']),
            'input_domain_ast': reflect_domain_ast(function.get('input_domain_ast', ['real'])),
            'derivation': {'substitution': 'argument->-argument', 'source_function_ref': function['function_ref']}}


def negated_descriptor(function):
    return {**deepcopy(function), 'function_ref': function['function_ref'] + '#negated',
            'expression_ast': ['neg', deepcopy(function['expression_ast'])],
            'derivation': {'negation': 'output', 'source_function_ref': function['function_ref']}}


def _pair(function, prop):
    right = function if prop == 'even' else negated_descriptor(function)
    return reflected_descriptor(function), right


# Goal description -----------------------------------------------------------

def repeats_goal_definition(ast, source, function):
    """Accept a repeated source rule, never discard an extra condition.

    Compare bound original syntax, not algebraic equality: cancellation can
    change the natural domain. The caller supplies only the target's ancestors
    and its own scope, so independent subquestions may reuse a function name.
    """
    if len(ast) != 3 or ast[0] != 'function_definition' or ast[2] != function['expression_ast']:
        return False
    raw = definition(source)
    return raw[0] == 'function_definition' and raw[1] == function['function_name']


def describe_parity_goal(report, scope, ancestors, goal_index, *, candidate=None):
    goal = scope['goals'][goal_index]
    if goal['kind'] != KIND:
        raise NotationError('function_parity.goal_required')
    value = {**deepcopy(goal), 'structure_supported': False, 'reason': '', 'structure_version': VERSION}
    visible = [*ancestors, scope]
    if any(s.get('uncertainties') for s in visible):
        value['reason'] = 'function_parity.unresolved_source'
        return value
    if any(not repeats_goal_definition(record['value'], record['source'], goal['function'])
           for s in visible for record in report.scope_facts.get(s['scope'], [])):
        value['reason'] = 'function_parity.additional_conditions_unsupported'
        return value
    try:
        cells.inspect(goal['function']['expression_ast'])
        cells.input_set(goal['function'].get('input_domain_ast', ['real']))
        if candidate is not None:
            from .stage_two.parity_surface import audit_domain
            audit_domain(candidate, goal['target_ref'])
    except (NotationError, ValueError, KeyError, TypeError) as exc:
        value['reason'] = getattr(exc, 'code', 'function_parity.invalid_structure')
        return value
    value['structure_supported'] = True
    return value


def inspect_parity_target(candidate, target_ref):
    report = NotationValidator().validate_root(candidate.get('root'), contracts.schema()['$defs'])
    if not report.ok:
        raise NotationError('function_parity.invalid_candidate')

    def visit(scope, ancestors=()):
        for index, _ in enumerate(scope['goals']):
            if f"{source_pointer(scope['scope'])}/goals/{index}" == target_ref:
                return describe_parity_goal(report, scope, ancestors, index, candidate=candidate)
        for child in scope['children']:
            found = visit(child, (*ancestors, scope))
            if found is not None:
                return found
        return None

    result = visit(report.semantic)
    if result is None:
        raise NotationError('function_parity.unknown_target')
    return result


# Production steps -----------------------------------------------------------

def effective_domain(function):
    return cells.solve_domain(function)


def domain_symmetry(function, domain):
    reflected = reflect_set(domain)
    if not _same_set(reflect_set(reflected), domain):
        raise NotationError('function_parity.domain_reflection_unsupported')
    if _same_set(reflected, domain):
        return {'status': 'proved', 'domain': domain, 'reflected_domain': reflected, 'witness': None}
    point = _sample(domain - reflected)
    return {'status': 'refuted', 'domain': domain, 'reflected_domain': reflected,
            'witness': {'point': point, 'in_domain': True, 'opposite_in_domain': False}}


def _value_witness(function, point, prop):
    valid_point, value = _evaluate(function['expression_ast'], point)
    valid_opposite, opposite = _evaluate(function['expression_ast'], -point)
    if not (valid_point and valid_opposite):
        return None
    target = value if prop == 'even' else -value
    if sp.simplify(opposite - target).is_zero is False:
        return {'point': point, 'value': value, 'opposite_value': opposite}
    return None


def _witness_points(domain):
    if isinstance(domain, sp.FiniteSet):
        return sorted(domain, key=lambda point: (abs(point), point))
    points = [point for point in [sp.S.Zero, *_WITNESS_POINTS] if _member(domain, point)]
    parts = domain.args if isinstance(domain, sp.Union) else [domain]
    for part in parts:
        positive = part.intersect(sp.Interval.open(0, sp.oo))
        if isinstance(positive, sp.Interval) and positive.measure > 0:
            points.append(_rational_between(positive.start, positive.end))
    return points[:32]


def _search_witness(function, domain, prop):
    for point in _witness_points(domain):
        if _member(domain, point) and _member(domain, -point):
            witness = _value_witness(function, point, prop)
            if witness:
                return witness
    return None


def relation(function, symmetry, prop):
    """Decide f(-x)=f(x) (even) or f(-x)=-f(x) (odd) on a symmetric domain."""
    if symmetry['status'] == 'refuted':
        return {'status': 'refuted', 'reason': 'domain_not_symmetric',
                'witness': {'kind': 'domain', **_copy(symmetry['witness'])}}
    left, right = _pair(function, prop)
    comparison = cells.compare_on_domain(left['expression_ast'], right['expression_ast'], symmetry['domain'])
    if comparison['relation'] == 'equal':
        cells.verify_identity(left['expression_ast'], right['expression_ast'], symmetry['domain'], comparison)
        return {'status': 'proved', 'reason': 'identity_on_domain', 'comparison': comparison}
    domain = symmetry['domain']
    witness = _search_witness(function, domain, prop)
    if witness is None and comparison['relation'] == 'different':
        witness = _value_witness(function, comparison['point'], prop)
    if witness:
        return {'status': 'refuted', 'reason': 'output_counterexample',
                'witness': {'kind': 'value', **witness}}
    return {'status': 'unresolved', 'reason': comparison.get('reason') or 'function_parity.identity_incomplete'}


def collect(goal, solved, symmetry, odd, even):
    classification = CLASSIFICATIONS.get((odd['status'], even['status']))
    function = goal['function']
    return {'kind': KIND, 'version': VERSION, 'comparison_version': COMPARISON_VERSION,
            'target_ref': goal['target_ref'], 'function_ref': function['function_ref'],
            'source_ref': function['source_ref'], 'expression_ast': deepcopy(function['expression_ast']),
            'input_domain_ast': deepcopy(function.get('input_domain_ast', ['real'])),
            'domain_role': function.get('domain_role', 'declared'),
            'domain': solved['domain'], 'natural_domain': solved['natural_domain'],
            'domain_symmetry': _copy(symmetry),
            'reflected_expression_ast': reflect_ast(function['expression_ast']),
            'odd': _copy(odd), 'even': _copy(even), 'classification': classification}


def solve(goal):
    function = goal['function']
    solved = effective_domain(function)
    symmetry = domain_symmetry(function, solved['domain'])
    odd = relation(function, symmetry, 'odd')
    even = relation(function, symmetry, 'even')
    return collect(goal, solved, symmetry, odd, even)


# Independent verification ---------------------------------------------------

def _check_value_witness(function, domain, witness, prop):
    point = witness['point']
    if witness.get('kind') != 'value' or not _exact_point(point):
        raise NotationError('function_parity.invalid_witness')
    if not (_member(domain, point) and _member(domain, -point)):
        raise NotationError('function_parity.witness_outside_domain')
    valid_point, value = _evaluate(function['expression_ast'], point)
    valid_opposite, opposite = _evaluate(function['expression_ast'], -point)
    target = value if prop == 'even' else -value
    if (not valid_point or not valid_opposite or witness.get('value') != value
            or witness.get('opposite_value') != opposite or sp.simplify(opposite - target).is_zero is not False):
        raise NotationError('function_parity.invalid_witness')


def _exact_point(point):
    try:
        cells.exact_point(point)
        return True
    except (NotationError, ValueError, TypeError, AttributeError):
        return False


def verify(goal, result):
    """Rebuild the domain and both relations from the frozen original function."""
    try:
        function = goal['function']
        expected = {'kind': KIND, 'version': VERSION, 'comparison_version': COMPARISON_VERSION,
                    'target_ref': goal['target_ref'], 'function_ref': function['function_ref'],
                    'source_ref': function['source_ref'], 'expression_ast': function['expression_ast'],
                    'input_domain_ast': function.get('input_domain_ast', ['real']),
                    'domain_role': function.get('domain_role', 'declared'),
                    'reflected_expression_ast': reflect_ast(function['expression_ast'])}
        if any(result.get(key) != value for key, value in expected.items()):
            raise NotationError('function_parity.result_binding_mismatch')
        domain, natural = cells.source_domain(function)
        if not (_same_set(result['domain'], domain) and _same_set(result['natural_domain'], natural)):
            raise NotationError('function_parity.domain_mismatch')
        symmetry = result['domain_symmetry']
        if (not _same_set(symmetry['domain'], domain)
                or not _same_set(symmetry['reflected_domain'], reflect_set(domain))):
            raise NotationError('function_parity.domain_mismatch')
        if symmetry['status'] == 'proved':
            if symmetry['witness'] is not None or not _same_set(reflect_set(domain), domain):
                raise NotationError('function_parity.symmetry_claim_invalid')
        elif symmetry['status'] == 'refuted':
            point = symmetry['witness']['point']
            if not _exact_point(point) or not _member(domain, point) or _member(domain, -point):
                raise NotationError('function_parity.symmetry_witness_invalid')
            for prop in ('odd', 'even'):
                row = result[prop]
                if (row.get('status') != 'refuted' or row.get('reason') != 'domain_not_symmetric'
                        or row['witness'].get('point') != point or row['witness'].get('kind') != 'domain'):
                    raise NotationError('function_parity.domain_refutation_mismatch')
        else:
            raise NotationError('function_parity.symmetry_status_invalid')
        if symmetry['status'] == 'proved':
            for prop in ('odd', 'even'):
                row = result[prop]
                if row.get('status') == 'proved':
                    left, right = _pair(function, prop)
                    cells.verify_identity(left['expression_ast'], right['expression_ast'], domain, row['comparison'])
                elif row.get('status') == 'refuted':
                    _check_value_witness(function, domain, row['witness'], prop)
                else:
                    raise NotationError('function_parity.relation_unresolved')
        if result.get('classification') != CLASSIFICATIONS[(result['odd']['status'], result['even']['status'])]:
            raise NotationError('function_parity.classification_mismatch')
        return {'status': 'verified', 'diagnostics': [], 'version': VERSION}
    except (NotationError, ValueError, TypeError, KeyError, IndexError, ZeroDivisionError, NotImplementedError) as exc:
        return {'status': 'math_failed', 'diagnostics': [{
            'code': getattr(exc, 'code', 'function_parity.verification_incomplete')}]}
