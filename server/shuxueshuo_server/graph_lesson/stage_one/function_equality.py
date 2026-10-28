"""Original scoped comparison structure, shared by recognition and admission."""

from copy import deepcopy

from ...problem_understanding.notation_compile import NotationValidator
from ...problem_understanding.notation_parser import NotationError
from . import contracts
from .function_domain import source_pointer

VERSION = 'function-comparison-domain-first/v2'


def describe_comparison_goal(report, scope, ancestors, goal_index):
    from ..function_equality import structural_inspect

    goal = scope['goals'][goal_index]
    if goal['kind'] != 'compare_functions':
        raise NotationError('comparison.goal_required')
    value = {**deepcopy(goal), 'structure_supported': False, 'reason': '', 'structure_version': VERSION}
    visible = [*ancestors, scope]
    if any(s.get('uncertainties') for s in visible) or goal['completeness'] != 'complete':
        value['reason'] = 'comparison.unresolved_source'
        return value
    if any(report.scope_facts.get(s['scope']) for s in visible):
        value['reason'] = 'comparison.additional_conditions_unsupported'
        return value
    if goal['mode'] != 'pair' and goal['select_relation'] not in ('equal', 'different'):
        value['reason'] = 'comparison.selection_polarity_unknown'
        return value
    for option in value['options']:
        for side in ('left', 'right'):
            # M1 domain syntax is the admission boundary. Whether M8 can
            # simplify the correspondence matters only after domains agree.
            inspected = structural_inspect(option[side])
            option[side].update(inspected)
            if not inspected['structure_supported']:
                value['reason'] = inspected['reason']
                return value
    value['structure_supported'] = True
    return value


def inspect_comparison_target(candidate, target_ref):
    report = NotationValidator().validate_root(candidate.get('root'), contracts.schema()['$defs'])
    if not report.ok:
        raise NotationError('comparison.invalid_candidate')

    def visit(scope, ancestors=()):
        for index, _ in enumerate(scope['goals']):
            if f"{source_pointer(scope['scope'])}/goals/{index}" == target_ref:
                return describe_comparison_goal(report, scope, ancestors, index)
        for child in scope['children']:
            found = visit(child, (*ancestors, scope))
            if found is not None:
                return found
        return None

    result = visit(report.semantic)
    if result is None:
        raise NotationError('comparison.unknown_target')
    return result
