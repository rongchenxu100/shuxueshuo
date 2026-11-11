"""Source-preserving structural admission for unknown function recovery."""

from copy import deepcopy

from ...problem_understanding.notation_compile import NotationValidator
from ...problem_understanding.notation_function_formula import DOMAIN_FIELDS
from ...problem_understanding.notation_parser import NotationError
from ..function_formula import VERSION, source_values
from ..function_matching import available, evaluate_relation
from . import contracts
from .function_domain import source_pointer


def _has_paired_calls(node):
    return (int(node[0] == 'function_call') + sum(_has_paired_calls(child)
            for child in node[1:] if isinstance(child, list)))


def describe_function_formula(report, scope, ancestors, goal_index):
    goal = scope['goals'][goal_index]
    ref = source_pointer(scope['scope']) + f'/goals/{goal_index}'
    extra = [source_pointer(row['path']) for visible in [*ancestors, scope]
             for row in report.scope_facts.get(visible['scope'], [])]
    value = {'kind': goal['kind'], 'target_ref': ref,
             'target_ast': deepcopy(goal['target']), 'relation_ast': deepcopy(goal['relation']),
             'function_name': goal['target'][1][1].rsplit(':', 1)[-1],
             'variable': goal['target'][2][1].rsplit(':', 1)[-1],
             'source_refs': [ref+'/'+key for key in ('function', 'variable', 'relation', *DOMAIN_FIELDS, 'function_type')
                             if key in ('function', 'variable', 'relation') or key in goal],
             'extra_source_refs': extra, 'function_type': goal.get('function_type'),
             'structure_version': VERSION, 'structure_supported': False, 'reason': ''}
    value.update({key+'_ast': deepcopy(goal.get(key)) for key in DOMAIN_FIELDS})
    if 'relation_variables' in goal:
        value['relation_variables_ast'] = deepcopy(goal['relation_variables'])
        value['source_refs'].extend(f'{ref}/relation_variables/{i}' for i in range(len(goal['relation_variables'])))
    if 'additional_relations' in goal:
        value['additional_relations_ast'] = deepcopy(goal['additional_relations'])
        value['source_refs'].extend(f'{ref}/additional_relations/{i}' for i in range(len(goal['additional_relations'])))
    if 'value' in goal:
        value['value_ast'] = deepcopy(goal['value'])
        value['source_refs'].append(ref+'/expression')
    try:
        if 'input_domain' in goal:
            # FP-T4 consumes this restriction before this generic route. Do not
            # silently discard it in older relation/coefficient consumers.
            raise NotationError('function_formula.input_restriction_unsupported')
        if 'relation_variables' in goal:
            from ..function_assignment import assignment_source, VERSION as ASSIGNMENT_VERSION
            value['structure_version'] = ASSIGNMENT_VERSION
            assignment_source(value)
        elif goal.get('function_type'):
            from ..function_coefficients import coefficient_source
            value['structure_version'] = 'function-formula-coefficients/v1'
            coefficient_source(value)
        elif goal.get('additional_relations'):
            raise ValueError('function_formula.additional_relations_unsupported')
        elif goal['kind'] == 'find_value':
            evaluate_relation(value)
        elif _has_paired_calls(value['relation_ast']) > 1:
            from ..function_system import system_source, VERSION as SYSTEM_VERSION
            value['structure_version'] = SYSTEM_VERSION
            system_source(value)
        elif not available(value):
            source_values(value)
        value['structure_supported'] = True
    except (NotationError, ValueError, TypeError) as exc:
        value['reason'] = getattr(exc, 'code', 'function_formula.unsupported_source')
    return value


def inspect_formula_target(candidate, target_ref):
    report = NotationValidator().validate_root(candidate['root'], contracts.schema()['$defs'])
    if not report.ok:
        raise ValueError('function_formula.invalid_source')
    scope, ancestors = report.semantic, []
    for part in target_ref.removeprefix('/root').split('/children/')[1:]:
        ancestors.append(scope)
        scope = scope['children'][int(part.split('/')[0])]
    return describe_function_formula(report, scope, ancestors, int(target_ref.rsplit('/', 1)[-1]))
