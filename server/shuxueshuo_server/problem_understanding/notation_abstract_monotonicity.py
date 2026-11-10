"""Check the fields of an abstract-function monotonicity goal; preserve any explicitly requested direction."""
from copy import deepcopy

from .notation_abstract_domain import _domain_ast
from .notation_compile import Report, Scope, typecheck
from .notation_parser import NotationError, parse


def compile_abstract_monotonicity(goal, path):
    if not goal.get('declared_domain'):
        raise NotationError('abstract_monotonicity.declared_domain_required')
    names = [parse(goal['function']), parse(goal['variable']),
             *(parse(v) for v in goal['relation_variables']), parse(goal['sign_condition']['variable'])]
    if any(n[0] != 'name' for n in names):
        raise NotationError('abstract_monotonicity.names_required')
    function, variable, first, second, sign_variable = (n[1] for n in names)
    if first == second or function in (variable, first, second, sign_variable):
        raise NotationError('abstract_monotonicity.distinct_names_required')
    relation_env = Scope(Report(), path)
    relation_env.declare(function, 'function')
    relation_env.abstract_functions.add(function)
    for name in (first, second):
        relation_env.declare(name, 'scalar')
    relation = relation_env.bind(parse(goal['relation']))
    if relation[0] != '=':
        raise NotationError('abstract_monotonicity.relation_equality_required')
    sign_env = Scope(Report(), path)
    sign_env.declare(function, 'function')
    sign_env.abstract_functions.add(function)
    sign_env.declare(sign_variable, 'scalar')
    statement = sign_env.bind(parse(goal['sign_condition']['statement']))
    comparisons = statement[1:] if statement[0] == 'and' else [statement]
    if any(row[0] not in ('<', '>', '<=', '>=') for row in comparisons):
        raise NotationError('abstract_monotonicity.sign_comparison_required')
    for text in (goal['input_domain'], goal['declared_domain'], goal['relation_domain'],
                 goal['sign_condition']['domain']):
        _domain_ast(Scope(Report(), path), text, path)
    target = relation_env.bind(parse(goal['function']))
    if typecheck(target) != 'function':
        raise NotationError('abstract_monotonicity.function_target_required')
    return {**deepcopy(goal), 'target': target}
