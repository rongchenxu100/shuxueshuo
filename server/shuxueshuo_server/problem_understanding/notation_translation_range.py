"""Bind the source relation, periodic identity, and local exact image separately."""

from .notation_abstract_domain import _domain_ast, _pointer
from .notation_compile import Report, Scope, typecheck
from .notation_parser import NotationError, definition, parse

FIELDS = ('function_relation', 'periodic_function', 'period', 'periodic_domain',
          'known_domain', 'known_range', 'input_domain')


def compile_translation_range(goal, path):
    ref = _pointer(path)
    raw = definition(goal['function_relation'])
    if raw[0] != 'function_definition':
        raise NotationError('translation_range.function_relation_required')
    name, variable, body = raw[1:]
    periodic = goal['periodic_function']
    if parse(periodic) != ['name', periodic] or len({name, variable, periodic}) != 3:
        raise NotationError('translation_range.distinct_function_names_required')
    env = Scope(Report(), ref)
    for fn in (name, periodic):
        env.declare(fn, 'function', local=True)
        # Binding identity only; no invented concrete rule enters the IR.
        env.functions[fn] = ['function_definition', fn, '_', ['number', '0']]
    env.declare(variable, 'scalar')
    relation = env.bind(body)
    period = env.bind(parse(goal['period']))
    if typecheck(relation) != 'scalar' or typecheck(period) != 'scalar':
        raise NotationError('translation_range.scalar_relation_required')
    return {'kind': goal['kind'], 'target_ref': ref,
            'target': ['function_call', env.reference(name, 'function'), env.reference(variable, 'scalar')],
            'periodic_ref': env.reference(periodic, 'function'), 'relation': relation,
            'period': period, **{key: _domain_ast(env, goal[key], ref + '/' + key)
                               for key in ('periodic_domain', 'known_domain', 'known_range', 'input_domain')}}


def canonical_translation_range(goal):
    def syntax(value):
        if isinstance(value, list):
            if value and value[0] == 'ref':
                return ['ref', value[1].rsplit(':', 1)[-1], value[2]]
            return [syntax(part) for part in value]
        return value
    return {key: syntax(value) for key, value in goal.items() if key != 'target_ref'}
