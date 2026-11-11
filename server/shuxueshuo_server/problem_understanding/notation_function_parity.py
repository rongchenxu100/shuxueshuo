"""Compile a concrete parity goal without simplifying its original rule.

The function body keeps every denominator, radical and absolute value of the
source; the declared input set keeps its open/closed ends. No answer, no
reflected rule and no natural domain is produced here.
"""

from copy import deepcopy

from .notation_parser import NotationError

KIND = 'determine_function_parity'


def compile_parity(goal, path):
    from ..graph_lesson.stage_one.function_domain import source_pointer
    from .notation_function_comparison import _function

    pointer = source_pointer(path)
    name = goal.get('function', 'f')
    if name == goal['variable']:
        raise NotationError('function_parity.function_and_variable_required', path=pointer + '/function')
    source = {'definition': f"{name}({goal['variable']})={goal['expression']}"}
    if 'input_domain' in goal:
        source['domain'] = goal['input_domain']
    try:
        function = _function(source, pointer, pointer + '/function')
    except NotationError as exc:
        exc.path = pointer + ('/input_domain' if exc.path.endswith('/domain') else '/expression')
        raise
    function['source_ref'] = pointer + '/expression'
    function['input_domain_source_ref'] = pointer + '/input_domain' if 'input_domain' in goal else ''
    function['domain_role'] = goal.get('domain_role', 'declared')
    return {'kind': KIND, 'target': ['parity_task', pointer], 'target_ref': pointer, 'function': function}


def canonical_parity(goal):
    """Content identity: original syntax, input set and its role; no source paths."""
    function = goal['function']
    return {'kind': KIND, 'expression_ast': deepcopy(function['expression_ast']),
            'explicit_domain': function['explicit_domain'],
            'input_domain_ast': deepcopy(function['input_domain_ast']),
            'domain_role': function['domain_role']}
