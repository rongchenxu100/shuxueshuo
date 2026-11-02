"""Unknown-function relations are constraints, never invented function bodies."""

from copy import deepcopy

from .notation_compile import ARITY, Report, Scope, typecheck
from .notation_parser import NotationError, parse

DOMAIN_FIELDS = ('relation_domain', 'declared_domain', 'requested_domain')


def compile_function_formula(goal, path):
    env = Scope(Report(), path)
    names = {}
    for key in ('function', 'variable'):
        ast = parse(goal[key])
        if ast[0] != 'name':
            raise NotationError('function_formula.name_required', key)
        names[key] = ast[1]
    if names['function'] == names['variable']:
        raise NotationError('function_formula.distinct_names_required')
    env.declare(names['function'], 'function')
    env.abstract_functions.add(names['function'])
    env.declare(names['variable'], 'scalar')
    variables = []
    if 'relation_variables' in goal:
        for name in goal['relation_variables']:
            ast = parse(name)
            if ast[0] != 'name' or ast[1] == names['function'] or ast[1] in variables:
                raise NotationError('function_formula.distinct_variables_required')
            variables.append(ast[1])
            env.declare(ast[1], 'scalar')
        if names['variable'] not in variables:
            raise NotationError('function_formula.target_variable_not_quantified')
    raw = parse(goal['relation'])
    if raw[0] != '=' or len(raw) != 3:
        raise NotationError('function_formula.equality_required')

    def declare(ast):
        if ast[0] == 'name':
            env.declare(ast[1], 'scalar')
        elif ast[0] == 'call' and ast[1] not in ARITY:
            env.declare(ast[1], 'function')
            env.abstract_functions.add(ast[1])
        for child in ast[1:]:
            if isinstance(child, list):
                declare(child)

    declare(raw)
    relation = env.bind(raw)
    if typecheck(relation) != 'boolean':
        raise NotationError('function_formula.equality_required')
    compiled = {'kind': goal['kind'],
                'target': ['function_call', env.reference(names['function']), env.reference(names['variable'])],
                'relation': relation}
    if variables:
        compiled['relation_variables'] = [env.reference(name) for name in variables]
    if 'additional_relations' in goal:
        compiled['additional_relations'] = []
        for item in goal['additional_relations']:
            ast = parse(item)
            if ast[0] != '=' or len(ast) != 3:
                raise NotationError('function_formula.equality_required')
            declare(ast)
            compiled['additional_relations'].append(env.bind(ast))
    if goal['kind'] in ('find_value', 'find_range'):
        compiled['value'] = env.bind(parse(goal['expression']))
        expected = 'scalar' if goal['kind'] == 'find_value' else 'boolean'
        if typecheck(compiled['value']) != expected:
            raise NotationError('function_value.scalar_required')
        if goal['kind'] == 'find_range' and goal['symbol'] != goal['variable']:
            raise NotationError('function_formula.range_variable_mismatch')
    from .notation_abstract_domain import _domain_ast
    for field in DOMAIN_FIELDS:
        if field in goal:
            compiled[field] = _domain_ast(env, goal[field], path + '.' + field)
    if 'function_type' in goal:
        compiled['function_type'] = goal['function_type']
    return compiled


def canonical_function_formula(goal):
    """Rename only bound identities; preserve radicals, original holes and scope."""
    refs = {goal['target'][1][1]: 'function:0', goal['target'][2][1]: 'scalar:0'}

    def walk(value):
        if isinstance(value, list):
            if value and value[0] == 'ref':
                if value[1] not in refs:
                    refs[value[1]] = value[2] + ':' + str(len(refs))
                return ['ref', refs[value[1]], value[2]]
            return [walk(item) for item in value]
        if isinstance(value, dict):
            return {key: walk(item) for key, item in value.items()}
        return deepcopy(value)

    return walk(goal)
