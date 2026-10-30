"""Original function image requests with bounded polynomial and radical syntax."""

from copy import deepcopy

from ...problem_understanding.notation_compile import NotationValidator
from ...problem_understanding.notation_parser import NotationError, definition
from ..range_syntax import expression_family, range_domain, substitution_family
from . import contracts
from .function_domain import (
    expression_latex,
    source_pointer,
)

VERSION = 'function-range-substitution/v3'


def _domain(ast):
    range_domain(ast)


def _budget(ast, depth=0, count=None):
    count = count if count is not None else [0]
    count[0] += 1
    if count[0] > 256 or depth > 24:
        raise NotationError('range.expression_budget')
    for child in ast[1:]:
        if isinstance(child, list):
            _budget(child, depth + 1, count)


def describe_range_goal(report, scope, ancestors, goal_index):
    goal = scope['goals'][goal_index]
    if goal['kind'] != 'find_range' or goal['target'][0] != 'ref' or goal['target'][2] != 'function':
        raise NotationError('range.function_goal_required')
    visible = [*ancestors, scope]
    records = [row for item in visible for row in report.scope_facts.get(item['scope'], [])]
    definitions = [row for row in records if row['value'][0] in ('function_definition', 'function_input_relation')
                   and row['value'][1] == goal['target']]
    if len(definitions) != 1:
        raise NotationError('range.single_function_definition_required')
    source = definitions[0]
    name, variable = definition(source['source'])[1:3]
    target_ref = f"{source_pointer(scope['scope'])}/goals/{goal_index}"
    relation = source['value'][0] == 'function_input_relation'
    body = source['value'][3 if relation else 2]
    value = {'function_ref': goal['target'][1], 'function_name': name, 'variable': variable,
             'source_ref': source_pointer(source['path']), 'target_ref': target_ref,
             'expression_ast': deepcopy(body), 'expression_latex': expression_latex(body, variable),
             'declared_domain_ast': ['real'], 'declared_domain_source_ref': '',
             'input_domain_ast': deepcopy(goal.get('input_domain', ['real'])),
             'input_domain_source_ref': target_ref+'/input_domain' if 'input_domain' in goal else '',
             'restriction_facts': [], 'degree': 0, 'structure_supported': False,
             'structure_version': VERSION, 'reason': ''}
    try:
        if any(item.get('uncertainties') for item in visible):
            raise NotationError('range.unresolved_source')
        _budget(body)
        if relation:
            value.update(substitution_family(body, relation_input=source['value'][2]))
            value['relation_input_ast'] = deepcopy(source['value'][2])
        else:
            try:
                family = expression_family(body)
            except NotationError:
                family = substitution_family(body)
            value.update(family)
        for row in records:
            if row is source:
                continue
            ast, ref = row['value'], source_pointer(row['path'])
            if ast[0] == '=' and ['call', 'Dom', goal['target']] in ast[1:]:
                domain = ast[2] if ast[1] == ['call', 'Dom', goal['target']] else ast[1]
                if value['declared_domain_source_ref']:
                    raise NotationError('range.duplicate_domain_declaration')
                _domain(domain)
                value.update(declared_domain_ast=deepcopy(domain), declared_domain_source_ref=ref)
            elif ast[0] == '∈' and ast[1][0] == 'ref' and ast[1][2] == 'scalar' and ast[1][1].rsplit(':', 1)[-1] == variable:
                _domain(ast[2])
                value['restriction_facts'].append({'domain_ast': deepcopy(ast[2]), 'source_ref': ref})
            else:
                raise NotationError('range.additional_conditions_unsupported')
        _domain(value['input_domain_ast'])
        if relation and (value['declared_domain_ast'] != ['real'] or value['input_domain_ast'] != ['real']
                         or value['restriction_facts']):
            raise NotationError('range.full_real_input_relation_required')
        value['structure_supported'] = True
    except (NotationError, ValueError, ZeroDivisionError) as exc:
        value['reason'] = getattr(exc, 'code', 'range.invalid_structure')
    return value


def inspect_range_target(candidate, target_ref):
    report = NotationValidator().validate_root(candidate.get('root'), contracts.schema()['$defs'])
    if not report.ok:
        raise NotationError('range.invalid_candidate')
    def visit(scope, ancestors=()):
        for index, _ in enumerate(scope['goals']):
            if f"{source_pointer(scope['scope'])}/goals/{index}" == target_ref:
                return describe_range_goal(report, scope, ancestors, index)
        for child in scope['children']:
            found = visit(child, (*ancestors, scope))
            if found is not None:
                return found
        return None
    result = visit(report.semantic)
    if result is None:
        raise NotationError('range.unknown_target')
    return result
