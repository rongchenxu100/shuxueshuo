"""Source-faithful goals that consume a function's image, not a guessed answer."""

from copy import deepcopy

from .answer_requests import arithmetic, request_for_goal, validate_request
from .notation_parser import NotationError, parse

KINDS = ('select_range_domain', 'find_extrema_expression')


def validate_task(goal):

    if goal['kind'] == 'find_extrema_expression':
        validate_request(request_for_goal(goal))
        return
    names = goal['parameters']
    if len(set(names)) != 2 or any(parse(name) != ['name', name] for name in names):
        raise NotationError('range_task.two_distinct_endpoints_required')
    domain = parse(goal['domain_template'])
    if domain[0] == 'tuple':
        domain = ['interval', False, False, *domain[1:]]
    if domain[0] != 'interval' or domain[3:] != [['name', name] for name in names]:
        raise NotationError('range_task.endpoint_template_required')
    labels = [row['label'] for row in goal['options']]
    if len(set(labels)) != len(labels):
        raise NotationError('range_task.duplicate_option_label')
    from ..graph_lesson.range_syntax import range_domain

    range_domain(parse(goal['expected_range']))
    for row in goal['options']:
        endpoints = [arithmetic(parse(value), {}) for value in row['values']]
        if any(value.is_real is not True or value.is_finite is not True for value in endpoints):
            raise NotationError('range_task.finite_real_endpoints_required')
        if endpoints[0] >= endpoints[1]:
            raise NotationError('range_task.ordered_endpoints_required')
        from ..graph_lesson.stage_three.choice_source import option_expression

        printed = option_expression(row['text'])
        surface = parse(printed) if printed else []
        if (len(surface) != 3 or surface[0] != 'tuple'
                or [arithmetic(node, {}) for node in surface[1:]] != endpoints):
            raise NotationError('range_task.option_values_mismatch')


def compile_range_task(goal, path, env):
    from .notation_compile import typecheck

    validate_task(goal)
    target = env.bind(parse(goal['object']))
    if target[0] != 'ref' or typecheck(target) != 'function':
        raise NotationError('range_task.function_required')
    result = {'kind': goal['kind'], 'target': target, 'task': deepcopy(goal)}
    if 'input_domain' in goal:
        domain = env.bind(parse(goal['input_domain']))
        if domain[0] == 'tuple':
            domain = ['interval', False, False, *domain[1:]]
        if typecheck(domain) not in ('domain', 'set'):
            raise NotationError('range_task.input_domain_required')
        result['input_domain'] = domain
    return result


def canonical_range_task(goal):
    # Keep named roles, option identity, polarity and original arithmetic.
    # No value/range computed by the solver can enter this source identity.
    return {'kind': goal['kind'], 'target': goal['target'][1].rsplit(':', 1)[-1],
            'task': deepcopy(goal['task'])}
