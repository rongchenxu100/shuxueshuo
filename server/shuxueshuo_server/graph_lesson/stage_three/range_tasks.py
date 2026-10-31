"""Exact adapters from verified images to domain-option and extremum goals."""

from copy import deepcopy

import sympy as sp

from ...problem_understanding.answer_requests import arithmetic, request_for_goal
from ...problem_understanding.notation_parser import NotationError, parse
from ...problem_understanding.review_contract import pointer
from ..range_syntax import range_domain
from .answer_conversion import compare_set, convert_goal, evaluate
from .capabilities import CapabilityGap, LocalCheckFailed, result


def option_domain(goal, option):
    ast = parse(goal['domain_template'])
    closed = ast[1:3] if ast[0] == 'interval' else [False, False]
    return ['interval', *closed, *(parse(value) for value in option['values'])]


def project_candidate(candidate, target_ref, option=None):
    projected = deepcopy(candidate)
    source = pointer(projected, target_ref)
    goal = {'kind': 'find_range', 'object': source['object']}
    if option is not None:
        ast = option_domain(source, option)
        goal['input_domain'] = ('[' if ast[1] else '(') + ','.join(option['values']) + (']' if ast[2] else ')')
    elif 'input_domain' in source:
        goal['input_domain'] = source['input_domain']
    source.clear()
    source.update(goal)
    return projected


def child_context(context, option=None):
    child = deepcopy(context)
    desc = child['range_goal']
    task = desc.pop('range_task')
    child['goal'] = {'kind': 'find_range', 'object': task['object']}
    child['goal_ast'] = {'kind': 'find_range', 'target': child['goal_ast']['target']}
    if option is not None:
        desc['input_domain_ast'] = option_domain(task, option)
        desc['input_domain_source_ref'] = context['target_ref']
        ast = desc['input_domain_ast']
        child['goal']['input_domain'] = ('[' if ast[1] else '(') + ','.join(option['values']) + (']' if ast[2] else ')')
        child['goal_ast']['input_domain'] = deepcopy(ast)
    elif 'input_domain' in task:
        child['goal']['input_domain'] = task['input_domain']
        child['goal_ast']['input_domain'] = deepcopy(desc['input_domain_ast'])
    return child


def options_admitted(context, method=None):
    from .function_range import METHOD_ID, admitted, inputs

    if method not in (None, METHOD_ID):
        return False
    desc = context.get('range_goal', {})
    if not desc.get('structure_supported') or desc.get('radical') or desc.get('rational') or desc.get('substitution'):
        return False
    # These are complete candidate domains, never restrictions to intersect
    # with a separately declared domain or a hidden condition.
    if desc.get('declared_domain_source_ref') or desc.get('restriction_facts'):
        return False
    try:
        for option in context['goal']['options']:
            child = child_context(context, option)
            _, _, domain = inputs(child['range_goal'])
            if not isinstance(domain, sp.Interval) or not admitted(child, METHOD_ID):
                return False
        return True
    except (ValueError, NotationError, KeyError, TypeError):
        return False


def prepare_options(context):
    if context['goal']['kind'] != 'select_range_domain':
        from .function_range import inputs
        _, _, domain = inputs(context['range_goal'])
        return result({'cases': [{'id': 'input', 'condition': sp.true, 'domain': domain,
                                  'context': context, 'task': None}]}, ['bind_range_input'])
    if not options_admitted(context):
        raise LocalCheckFailed('range_task.unsupported_domain_options')
    task = context['goal']
    cases = []
    for index, option in enumerate(task['options']):
        domain = range_domain(option_domain(task, option))
        condition = sp.And(*(sp.Eq(sp.Symbol(name, real=True), arithmetic(parse(value), {}), evaluate=False)
                             for name, value in zip(task['parameters'], option['values'], strict=True)), evaluate=False)
        cases.append({'id': f'option-{index+1}', 'index': index, 'label': option['label'],
                      'condition': condition, 'domain': domain, 'context': child_context(context, option), 'task': task})
    return result({'cases': cases}, ['bind_range_options'])


def prepare_case(option):
    return result({'context': option['context'], 'option_mode': option['task'] is not None}, ['bind_candidate_domain'])


def compare_option(option, image):
    if option['task'] is None:
        return result({'comparison': {'image': image}}, ['return_complete_image'])
    expected = range_domain(parse(option['task']['expected_range']))
    return result({'comparison': {'index': option['index'], 'label': option['label'],
                                  'domain': option['domain'], 'image': image,
                                  'expected': expected, 'matches': compare_set(image, request_for_goal(option['task'])['predicate'])['value']}},
                  ['compare_complete_images'])


def collect_options(context, comparisons):
    from .verification import VerificationGap
    if context['goal']['kind'] != 'select_range_domain':
        if len(comparisons) != 1:
            raise LocalCheckFailed('range_task.single_image_required')
        return result({'feasible_set': comparisons[0]['outputs']['comparison']['image']}, ['return_complete_image'])
    options = context['goal']['options']
    if len(comparisons) != len(options):
        raise LocalCheckFailed('range_task.incomplete_options')
    candidates = []
    for index, (row, option) in enumerate(zip(comparisons, options, strict=True)):
        value = row['outputs']['comparison']
        if value['index'] != index or value['label'] != option['label']:
            raise LocalCheckFailed('range_task.option_identity_mismatch')
        candidates.append({'label': option['label'], 'value': value['image']})
    try:
        answer, _ = evaluate(request_for_goal(context['goal']), candidates=candidates)
    except VerificationGap as exc:
        raise CapabilityGap(str(exc)) from exc
    selected = [i for i, row in enumerate(options) if row['label'] in answer['labels']]
    return result({'feasible_set': sp.FiniteSet(*selected)}, ['select_original_range_options'])


def independent_verify(candidate, target_ref, context, feasible):
    from .context import build_context
    from .function_range import independent_verify as verify_image
    from .function_range import inputs, monotone_cover

    original = build_context(candidate, target_ref)
    if original != context:
        return {'status': 'math_failed', 'proof': {}, 'diagnostics': [{'code': 'range_task.context_mismatch'}]}
    goal = context['goal']
    if goal['kind'] == 'find_extrema_expression':
        projected = project_candidate(candidate, target_ref)
        return verify_image(projected, target_ref, build_context(projected, target_ref), feasible)
    if not options_admitted(context):
        return {'status': 'capability_gap', 'proof': {}, 'diagnostics': [{'code': 'range_task.unsupported_domain_options'}]}
    rows, candidates = [], []
    for index, option in enumerate(goal['options']):
        projected = project_candidate(candidate, target_ref, option)
        child = build_context(projected, target_ref)
        expression, variable, domain = inputs(child['range_goal'])
        image, _ = monotone_cover(expression, variable, domain)
        proof = verify_image(projected, target_ref, child, image)
        if proof['status'] != 'verified':
            return proof
        matches = compare_set(image, request_for_goal(goal)['predicate'])['value']
        candidates.append({'label': option['label'], 'value': image})
        rows.append({'label': option['label'], 'matches': matches, 'proof': proof['proof']})
    answer, conversion = evaluate(request_for_goal(goal), candidates=candidates)
    selected = [i for i, row in enumerate(goal['options']) if row['label'] in answer['labels']]
    passed = feasible == sp.FiniteSet(*selected)
    return {'status': 'verified' if passed else 'math_failed',
            'proof': {'kind': 'complete_range_option_check', 'passed': passed, 'options': rows, 'conversion': conversion},
            'diagnostics': [] if passed else [{'code': 'range_task.option_verdict_mismatch'}]}


def endpoints(candidate, target_ref, feasible):
    from .context import build_context
    from .function_range import image_endpoints
    if pointer(candidate, target_ref)['kind'] == 'find_extrema_expression':
        return image_endpoints(project_candidate(candidate, target_ref), target_ref, feasible)
    verified = independent_verify(candidate, target_ref, build_context(candidate, target_ref), feasible)
    return {'status': 'passed' if verified['status'] == 'verified' else 'failed', 'points': [],
            'options': verified['proof'].get('options', [])}


def close_goal(goal, feasible):
    from .goals import _exact_math
    from .verification import VerificationGap

    evidence = {'kind': 'goal_closure', 'goal_kind': goal['kind'],
                'feasible_set': _exact_math(feasible), 'checks': []}
    if goal['kind'] == 'select_range_domain':
        allowed = sp.FiniteSet(*range(len(goal['options'])))
        if (not isinstance(feasible, sp.FiniteSet) and feasible != sp.S.EmptySet) or not feasible.is_subset(allowed):
            raise VerificationGap('range_task.invalid_option_indices')
        labels = [row['label'] for i, row in enumerate(goal['options']) if i in feasible]
        if goal['selection_mode'] == 'single' and len(labels) != 1:
            raise VerificationGap('range_task.single_choice_ambiguous')
        answer = {'kind': goal['kind'], 'status': 'complete', 'correct_labels': labels,
                  'selection_mode': goal['selection_mode'], 'select_relation': goal['select_relation']}
        evidence['checks'].append({'kind': 'complete_option_selection', 'passed': True})
        return answer, evidence
    return convert_goal(goal, feasible)
