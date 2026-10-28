"""Compile option-local function comparisons without inventing child questions.

The extraction boundary contains original controlled strings. This module binds
each function independently, preserves its unsimplified body and declared input
set, and resolves only explicit local/shared references. It performs no solving.
"""

from copy import deepcopy

from .notation_parser import NotationError, clean, definition, parse


def _pointer(path):
    from ..graph_lesson.stage_one.function_domain import source_pointer

    return source_pointer(path)


def _function(source, path, identity):
    from ..graph_lesson.stage_one.function_domain import expression_latex
    from .notation_compile import Report, Scope, typecheck

    field = 'definition'
    try:
        # The shared parser accepts :=, ≔ and ≡ as assignment spelling. Use
        # its same lexical normalization for the display RHS, without changing
        # the original source field or simplifying the expression tree.
        definition_text = clean(source['definition'])
        raw = definition(definition_text)
        if raw[0] != 'function_definition':
            raise NotationError('comparison.concrete_function_required')
        local = Scope(Report(), identity)
        local.declarations(raw)
        compiled = local.bind(raw)
        typecheck(compiled)
        field = 'domain'
        domain = local.bind(parse(source['domain'])) if 'domain' in source else ['real']
        if domain[0] == 'tuple':
            domain = ['interval', False, False, *domain[1:]]
        if typecheck(domain) not in ('domain', 'set'):
            raise NotationError('comparison.declared_domain_required')
    except NotationError as exc:
        exc.path = path + '/' + field
        exc.source = source
        raise
    return {
        'function_ref': identity, 'function_name': raw[1], 'variable': raw[2],
        'source_ref': path + '/definition', 'expression': definition_text.split('=', 1)[1].strip(),
        'expression_ast': deepcopy(compiled[2]),
        'expression_latex': expression_latex(compiled[2], raw[2]),
        'input_domain_ast': domain, 'explicit_domain': 'domain' in source,
        'input_domain_source_ref': path + '/domain' if 'domain' in source else '',
    }


def compile_comparison(goal, path):
    """Return a bound comparison goal; source pointers are candidate-version local."""
    pointer = _pointer(path)
    shared = {}
    for index, item in enumerate(goal['shared_functions']):
        if item['id'] in shared:
            raise NotationError('comparison.duplicate_function_id',
                                path=f'{pointer}/shared_functions/{index}/id')
        shared[item['id']] = _function(item, f'{pointer}/shared_functions/{index}',
                                       f'{pointer}/shared_functions/{item["id"]}')
    options, identities, labels, used_shared = [], set(), set(), set()
    for index, option in enumerate(goal['options']):
        source = f'{pointer}/options/{index}'
        if option['id'] in identities:
            raise NotationError('comparison.duplicate_option', path=source + '/id')
        if option['label'] in labels:
            raise NotationError('comparison.duplicate_option', path=source + '/label')
        identities.add(option['id'])
        labels.add(option['label'])
        local = {}
        for fi, item in enumerate(option['functions']):
            if item['id'] in local:
                raise NotationError('comparison.duplicate_function_id',
                                    path=f'{source}/functions/{fi}/id')
            local[item['id']] = _function(item, f'{source}/functions/{fi}',
                                          f'{pointer}/options/{option["id"]}/functions/{item["id"]}')
        resolved, used_local = {}, set()
        for side in ('left', 'right'):
            namespace, name = option[side].split(':', 1)
            mapping = shared if namespace == 'shared' else local
            if name not in mapping:
                raise NotationError('comparison.unresolved_function_ref', path=source + '/' + side)
            resolved[side] = deepcopy(mapping[name])
            (used_shared if namespace == 'shared' else used_local).add(name)
        if used_local != set(local):
            raise NotationError('comparison.unused_local_definition', path=source + '/functions')
        if goal['mode'] == 'shared_baseline':
            namespaces = {option[side].split(':', 1)[0] for side in ('left', 'right')}
            if namespaces != {'shared', 'local'}:
                raise NotationError('comparison.shared_baseline_required', path=source)
            # Identity is symmetric. Canonicalize only the compiled roles;
            # the candidate, object identities and original definition source
            # pointers remain unchanged for review and exact repair authority.
            if option['left'].startswith('local:'):
                resolved = {'left': resolved['right'], 'right': resolved['left']}
        elif any(option[side].startswith('shared:') for side in ('left', 'right')):
            raise NotationError('comparison.local_pair_required', path=source)
        options.append({'option_id': option['id'], 'label': option['label'],
                        'text': option['text'], 'source_ref': source, **resolved})
    if used_shared != set(shared) or (goal['mode'] == 'shared_baseline' and len(shared) != 1):
        raise NotationError('comparison.shared_baseline_required', path=pointer + '/shared_functions')
    return {
        'kind': 'compare_functions', 'target': ['comparison_task', pointer],
        'target_ref': pointer, 'mode': goal['mode'], 'select_relation': goal['select_relation'],
        'selection_mode': goal['selection_mode'], 'completeness': goal['completeness'],
        'options': options,
    }


def canonical_comparison(goal):
    """Content identity excludes opaque IDs and source paths, keeps original syntax."""
    def syntax(value):
        if isinstance(value, list):
            if value and value[0] == 'ref':
                return ['ref', value[1].rsplit(':', 1)[-1], value[2]]
            return [syntax(child) for child in value]
        return value

    def function(value):
        return {'expression_ast': syntax(value['expression_ast']),
                'explicit_domain': value['explicit_domain'],
                'input_domain_ast': syntax(value['input_domain_ast'])}

    return {
        'kind': 'compare_functions', 'mode': goal['mode'],
        'select_relation': goal['select_relation'], 'selection_mode': goal['selection_mode'],
        'completeness': goal['completeness'],
        'options': [{'label': option['label'], 'left': function(option['left']),
                     'right': function(option['right'])} for option in goal['options']],
    }
