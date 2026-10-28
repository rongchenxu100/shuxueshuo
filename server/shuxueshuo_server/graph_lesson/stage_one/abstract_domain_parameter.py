"""Read linear multi-call feasibility over a stated, finite input interval."""

from copy import deepcopy
from fractions import Fraction

from ...problem_understanding.notation_parser import NotationError
from .abstract_function_domain import VERSION, _target_latex
from .function_domain import (
    _affine,
    _coefficient_budget,
    _input_domain,
    expression_latex,
    source_pointer,
)


def _linear(ast, variable, parameter, depth=0):
    if depth > 24:
        raise NotationError('abstract_domain.structure_limit')
    if ast == variable:
        values = (Fraction(1), Fraction(0), Fraction(0))
    elif ast == parameter:
        values = (Fraction(0), Fraction(1), Fraction(0))
    elif ast[0] == 'number':
        values = (Fraction(0), Fraction(0), Fraction(ast[1]))
    elif ast[0] == 'neg':
        values = tuple(-value for value in _linear(ast[1], variable, parameter, depth + 1))
    elif ast[0] in ('+', '-', '*', '/'):
        left = _linear(ast[1], variable, parameter, depth + 1)
        right = _linear(ast[2], variable, parameter, depth + 1)
        if ast[0] in ('+', '-'):
            sign = 1 if ast[0] == '+' else -1
            values = tuple(a + sign * b for a, b in zip(left, right, strict=True))
        elif ast[0] == '/':
            if any(right[:2]) or not right[2]:
                raise NotationError('abstract_domain.linear_rational_inputs_required')
            values = tuple(value / right[2] for value in left)
        elif not any(left[:2]):
            values = tuple(left[2] * value for value in right)
        elif not any(right[:2]):
            values = tuple(right[2] * value for value in left)
        else:
            raise NotationError('abstract_domain.linear_rational_inputs_required')
    else:
        raise NotationError('abstract_domain.linear_rational_inputs_required')
    for value in values:
        _coefficient_budget(value)
    return values


def describe_abstract_domain_parameter(report, scope, ancestors, goal_index):
    goal = scope['goals'][goal_index]
    target_ref = f"{source_pointer(scope['scope'])}/goals/{goal_index}"
    known, target = goal['known_call'], goal['target']
    variable, parameter = goal['variable'], goal['parameter']
    value = {
        'kind': 'find_abstract_domain_parameter',
        'function_name': known[1][1].rsplit(':', 1)[-1],
        'function_ref': deepcopy(known[1]),
        'known_call_ast': deepcopy(known), 'known_argument_ast': deepcopy(known[2]),
        'known_domain_ast': deepcopy(goal['known_domain']), 'known_strength': goal['strength'],
        'target_call_ast': deepcopy(target), 'target_latex': '',
        'variable': variable[1].rsplit(':', 1)[-1], 'variable_ref': deepcopy(variable),
        'parameter': parameter[1].rsplit(':', 1)[-1], 'parameter_ref': deepcopy(parameter),
        'known_variable': '', 'known_form': None, 'quantifier': goal['quantifier'],
        'calls': [], 'structure_supported': False, 'reason': '', 'structure_version': VERSION,
        'source_ref': target_ref, 'known_call_source_ref': f'{target_ref}/known_call',
        'known_domain_source_ref': f'{target_ref}/known_domain',
        'target_call_source_ref': f'{target_ref}/target_call',
        'parameter_source_ref': f'{target_ref}/parameter',
        'variable_source_ref': f'{target_ref}/variable',
        'quantifier_source_ref': f'{target_ref}/quantifier',
    }
    try:
        visible = [*ancestors, scope]
        if any(item.get('uncertainties') for item in visible):
            raise NotationError('abstract_domain.unresolved_source')
        if any(report.scope_facts.get(item['scope']) for item in visible):
            raise NotationError('abstract_domain.additional_conditions_unsupported')
        if goal['strength'] not in ('exact', 'meaningful_only') or goal['quantifier'] != 'exists':
            raise NotationError('abstract_domain.parameter_scope_unsupported')
        if known[2][0] != 'ref' or known[2][2] != 'scalar':
            raise NotationError('abstract_domain.identity_known_call_required')
        domain = goal['known_domain']
        _input_domain(domain)
        if domain[0] == 'interval':
            if any(endpoint[0] == 'infinity' or
                   (endpoint[0] == 'neg' and endpoint[1][0] == 'infinity') for endpoint in domain[-2:]):
                raise NotationError('abstract_domain.finite_known_domain_required')
            lower, upper = (_affine(endpoint)[1] for endpoint in domain[-2:])
            if lower > upper or (lower == upper and not all(domain[1:3])):
                raise NotationError('abstract_domain.nonempty_known_domain_required')
        elif domain[0] != 'set' or len(domain) != 2:
            raise NotationError('abstract_domain.finite_known_domain_required')
        calls = []

        def visit(ast, path=(), depth=0):
            if depth > 24 or len(calls) > 16:
                raise NotationError('abstract_domain.structure_limit')
            if ast[0] == 'function_call':
                if ast[1] != known[1]:
                    raise NotationError('abstract_domain.function_identity_mismatch')
                x_coefficient, parameter_coefficient, constant = _linear(ast[2], variable, parameter)
                calls.append({
                    'argument_ast': deepcopy(ast[2]),
                    'argument_latex': expression_latex(ast[2], value['variable']),
                    'x_coefficient': str(x_coefficient),
                    'parameter_coefficient': str(parameter_coefficient),
                    'constant': str(constant), 'ast_path': list(path),
                })
            elif ast[0] in ('+', '-', '*'):
                visit(ast[1], (*path, 1), depth + 1)
                visit(ast[2], (*path, 2), depth + 1)
            elif ast[0] == 'neg':
                visit(ast[1], (*path, 1), depth + 1)
            else:
                raise NotationError('abstract_domain.call_combination_required')

        visit(target)
        if not 2 <= len(calls) <= 16:
            raise NotationError('abstract_domain.multiple_calls_required')
        value.update(structure_supported=True, known_form='identity',
                     known_variable=known[2][1].rsplit(':', 1)[-1], calls=calls,
                     target_latex=_target_latex(target, value['variable']))
    except (NotationError, ValueError, ZeroDivisionError, TypeError) as exc:
        value['reason'] = getattr(exc, 'code', 'abstract_domain.invalid_structure')
    return value


def inspect_abstract_domain_parameter_target(candidate, target_ref):
    from .abstract_function_domain import inspect_abstract_domain_target

    result = inspect_abstract_domain_target(candidate, target_ref)
    if result['kind'] != 'find_abstract_domain_parameter':
        raise NotationError('abstract_domain.parameter_goal_required')
    return result
