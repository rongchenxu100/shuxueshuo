"""Original, scope-bound function evaluation requests; never evaluates them."""

from copy import deepcopy

from .notation_parser import NotationError, parse


def is_evaluation_goal(goal):
    if goal['kind'] in ('check_constant', 'finite_sum'):
        return True
    def has_call(ast):
        return isinstance(ast, list) and bool(ast) and (
            ast[0] == 'function_call' or any(has_call(child) for child in ast[1:]))
    return goal['kind'] == 'find_value' and has_call(goal['target'])


def compile_finite_sum(goal, path, env):
    from .notation_compile import Scope, typecheck

    terms, target = [], ['finite_sum']
    for index, term in enumerate(goal['terms']):
        local = Scope(env.report, f'{path}.terms[{index}]', env)
        compiled = {}
        if 'index' in term:
            local.declare(term['index'], 'scalar', local=True)
            compiled.update(index=local.reference(term['index']), lower=term['lower'], upper=term['upper'])
        expression = local.bind(parse(term['expression']))
        if typecheck(expression) != 'scalar':
            raise NotationError('type.goal_target')
        compiled['target'] = expression
        terms.append(compiled)
        target.append(['indexed_sum', compiled['index'], ['number', str(term['lower'])],
                       ['number', str(term['upper'])], expression]
                      if 'index' in compiled else expression)
    return {'kind': 'finite_sum', 'target': target, 'terms': terms}


def canonical_evaluation(goal, aliases):
    """Keep original calls and denominators instead of cancelling before admission."""
    def tree(value):
        if isinstance(value, dict):
            return {key: tree(child) for key, child in value.items()}
        if not isinstance(value, list):
            return value
        if value[:1] == ['ref']:
            return ['ref', aliases.get(value[1], value[1]), value[2]]
        return [tree(child) for child in value]
    return tree(deepcopy(goal))
