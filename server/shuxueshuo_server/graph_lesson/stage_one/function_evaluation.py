"""Source-complete structural description of explicit function evaluation."""

from copy import deepcopy

from ...problem_understanding.notation_compile import NotationValidator
from ...problem_understanding.notation_parser import NotationError, definition
from . import contracts
from .function_domain import source_pointer

VERSION = 'function-evaluation-structural/v1'
KINDS = ('find_value', 'check_constant', 'finite_sum')


def _scalar_refs(ast):
    if not isinstance(ast, list) or not ast:
        return set()
    if ast[0] == 'ref' and ast[2] == 'scalar':
        return {ast[1]}
    return set().union(*(_scalar_refs(child) for child in ast[1:]))


def describe_evaluation_goal(report, scope, ancestors, goal_index):
    goal = scope['goals'][goal_index]
    if goal['kind'] not in KINDS:
        raise NotationError('evaluation.goal_required')
    target_ref = f"{source_pointer(scope['scope'])}/goals/{goal_index}"
    value = {'kind': goal['kind'], 'target_ref': target_ref, 'source_ref': target_ref,
             'expression_ast': deepcopy(goal['target']), 'functions': [], 'terms': [],
             'variable_ref': '', 'variable': '',
             'input_domain_ast': deepcopy(goal.get('input_domain', ['real'])),
             'structure_supported': False, 'reason': '', 'structure_version': VERSION}
    try:
        visible = [*ancestors, scope]
        if any(item.get('uncertainties') for item in visible):
            raise NotationError('evaluation.unresolved_source')
        definitions, domains = {}, {}
        for item in visible:
            for record in report.scope_facts.get(item['scope'], []):
                ast, source = record['value'], source_pointer(record['path'])
                if ast[0] == 'function_definition':
                    ref = ast[1][1]
                    if ref in definitions:
                        raise NotationError('evaluation.duplicate_function_definition')
                    definitions[ref] = {'function_ref': ref, 'function_name': ref.rsplit(':', 1)[-1],
                                        'variable': definition(record['source'])[2],
                                        'source_ref': source, 'expression_ast': deepcopy(ast[2]),
                                        'input_domain_ast': ['real'], 'explicit_domain': False}
                elif ast[0] == '=' and any(side[:2] == ['call', 'Dom'] for side in ast[1:]):
                    left, right = ast[1:]
                    domain_call, domain = (left, right) if left[:2] == ['call', 'Dom'] else (right, left)
                    ref = domain_call[2][1]
                    if ref in domains and domains[ref][0] != domain:
                        raise NotationError('evaluation.conflicting_function_domain')
                    domains[ref] = (deepcopy(domain), source)
                else:
                    raise NotationError('evaluation.additional_conditions_unsupported')
        for ref, (domain, source) in domains.items():
            if ref not in definitions:
                raise NotationError('evaluation.missing_function_definition')
            definitions[ref].update(input_domain_ast=domain, explicit_domain=True,
                                    input_domain_source_ref=source)
        value['functions'] = list(definitions.values())
        if not definitions:
            raise NotationError('evaluation.function_definition_required')
        if goal['kind'] == 'finite_sum':
            for index, term in enumerate(goal['terms']):
                compiled = {'expression_ast': deepcopy(term['target']),
                            'source_ref': f'{target_ref}/terms/{index}'}
                if 'index' in term:
                    compiled.update(index_ref=term['index'][1], index=term['index'][1].rsplit(':', 1)[-1],
                                    lower=term['lower'], upper=term['upper'])
                value['terms'].append(compiled)
        else:
            refs = _scalar_refs(goal['target'])
            if len(refs) > 1:
                raise NotationError('evaluation.single_outer_variable_required')
            if refs:
                value['variable_ref'] = next(iter(refs))
                value['variable'] = value['variable_ref'].rsplit(':', 1)[-1]
        from ..function_evaluation import structural_inspect

        value.update(structural_inspect(value))
    except (NotationError, ValueError, TypeError, KeyError) as exc:
        value['reason'] = getattr(exc, 'code', 'evaluation.invalid_structure')
    return value


def inspect_evaluation_target(candidate, target_ref):
    report = NotationValidator().validate_root(candidate.get('root'), contracts.schema()['$defs'])
    if not report.ok:
        raise NotationError('evaluation.invalid_candidate')
    def visit(scope, ancestors=()):
        for index, _ in enumerate(scope['goals']):
            if f"{source_pointer(scope['scope'])}/goals/{index}" == target_ref:
                return describe_evaluation_goal(report, scope, ancestors, index)
        for child in scope['children']:
            found = visit(child, (*ancestors, scope))
            if found is not None:
                return found
        return None
    result = visit(report.semantic)
    if result is None:
        raise NotationError('evaluation.unknown_target')
    return result
