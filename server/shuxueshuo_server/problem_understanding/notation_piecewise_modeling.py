"""Source pricing data is a goal input, never an already-given function."""
from copy import deepcopy

from .notation_compile import Report, Scope
from .notation_parser import NotationError, parse


def compile_pricing(goal, path):
    env = Scope(Report(), path)
    for name in (goal['pricing']['quantity'], goal['pricing']['amount']):
        if parse(name)[0] != 'name':
            raise NotationError('pricing.scalar_name_required')
        env.declare(name, 'scalar')
    if goal['pricing']['quantity'] == goal['pricing']['amount']:
        raise NotationError('pricing.distinct_variables_required')
    name = goal['pricing']['amount' if goal['kind'] == 'find_equation' else 'quantity']
    if goal.get('object', goal.get('symbol')) != name:
        raise NotationError('pricing.target_mismatch')
    return {**deepcopy(goal), 'target': env.bind(parse(name))}
