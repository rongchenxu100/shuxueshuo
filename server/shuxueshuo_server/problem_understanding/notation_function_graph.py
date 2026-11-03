"""Preserve source graph facts, never synthesize formulas from option pictures."""
from copy import deepcopy

from .notation_compile import Report, Scope, typecheck
from .notation_parser import NotationError, parse


def compile_function_graph(goal, path):
    variable = parse(goal['variable'])
    if variable[0] != 'name':
        raise NotationError('function_graph.variable_required')
    env = Scope(Report(), path)
    env.declare(variable[1], 'scalar')
    if 'source_graph' in goal:
        name = parse(goal['source_graph']['function'])
        if name[0] != 'name' or name == variable:
            raise NotationError('function_graph.function_and_variable_required')
        env.declare(name[1], 'function')
        env.abstract_functions.add(name[1])
    expression = env.bind(parse(goal['expression']))
    if typecheck(expression) != 'scalar':
        raise NotationError('function_graph.scalar_expression_required')
    return {**deepcopy(goal), 'target': expression}
