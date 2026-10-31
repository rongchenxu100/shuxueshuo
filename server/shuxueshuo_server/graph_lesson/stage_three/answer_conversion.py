"""Compose answer operations over independently verified solver results.

This layer knows exact sets, quantities, comparisons and original option labels.
It does not know quadratic, rational or other problem-solving methods.
"""

from copy import deepcopy

import sympy as sp

from ...problem_understanding.answer_requests import (
    arithmetic,
    compile_candidate_plan,
    compile_plan,
    request_for_goal,
)
from ...problem_understanding.notation_parser import NotationError, parse
from ..range_syntax import range_domain
from .trajectory import decode_value, encode_value
from .verification import VerificationGap, _set_mismatch, _supported_set


def quantity(value, role):
    from .goals import finalize_goal_with_evidence

    minimum = role in ('minimum', 'infimum')
    answer, proof = finalize_goal_with_evidence({'kind': 'find_minimum' if minimum else 'find_maximum'}, value)
    field = 'value' if answer['status'] == 'attained' else 'bound'
    available = answer['status'] == 'attained' or (role in ('infimum', 'supremum') and answer['status'] == 'not_attained')
    return {'type': 'quantity', 'quantity': role, 'available': available, 'status': answer['status'],
            'value': decode_value(answer[field]['exact']) if available else None,
            'bound': decode_value(answer[field]['exact']) if field in answer else None, 'proof': proof}


def compare_set(value, predicate):
    _supported_set(value)
    expected = range_domain(parse(predicate['expected']))
    _supported_set(expected)
    equal = _set_mismatch(value, expected) is None
    return {'type': 'boolean', 'value': equal if predicate['relation'] == 'equal' else not equal,
            'actual': value, 'expected': expected, 'relation': predicate['relation']}


def evaluate(request, *, result=None, candidates=None):
    """Rebuild and execute a small plan; recorded traces are never trusted input."""
    plan = (compile_candidate_plan(request) if candidates is not None and request.get('kind') == 'select'
            else compile_plan(request))
    if plan['input'] == 'set':
        _supported_set(result)
        values = {'result': result}
    else:
        if not isinstance(candidates, list) or not 1 <= len(candidates) <= 8:
            raise VerificationGap('answer_conversion.incomplete_candidates')
        labels = [row['label'] for row in candidates]
        if len(set(labels)) != len(labels) or any(not isinstance(label, str) or not label for label in labels):
            raise VerificationGap('answer_conversion.invalid_candidate_identity')
        values = {'candidates': candidates}
    trace = []
    for step in plan['steps']:
        operation = step['operation']
        if operation == 'return_set':
            output = {'type': 'set', 'value': values[step['source']]}
        elif operation == 'extract_quantity':
            output = quantity(values[step['source']], step['quantity'])
        elif operation == 'evaluate_expression':
            bindings = {name: values[reference] for name, reference in step['bindings'].items()}
            if any(not row['available'] for row in bindings.values()):
                output = {'type': 'undefined', 'reason': 'quantity_unavailable'}
            else:
                try:
                    value = sp.simplify(arithmetic(parse(step['expression']), {name: row['value'] for name, row in bindings.items()}))
                    if value.is_real is not True or value.is_finite is not True:
                        raise NotationError('range_task.undefined_expression')
                    output = {'type': 'scalar', 'value': value}
                except NotationError as exc:
                    if exc.code != 'range_task.undefined_expression':
                        raise
                    output = {'type': 'undefined', 'reason': 'undefined_expression'}
        elif operation == 'compare_set':
            output = compare_set(values[step['source']], step)
        elif operation == 'compare_candidates':
            output = [{'label': row['label'], **compare_set(row['value'], step['predicate'])}
                      for row in values[step['source']]]
        elif operation == 'select_truth':
            selected = [row['label'] for row in values[step['source']] if row['value'] is step['when']]
            if step['selection_mode'] == 'single' and len(selected) != 1:
                raise VerificationGap('answer_conversion.single_choice_ambiguous')
            output = {'type': 'selection', 'labels': selected, 'selection_mode': step['selection_mode']}
        else:
            raise VerificationGap('answer_conversion.unknown_operation')
        values[step['id']] = output
        trace.append({'step': deepcopy(step), 'output': encode_value(output)})
    return values[plan['output']], {'plan': plan, 'steps': trace}


def convert_goal(goal, feasible):
    """Close an explicit request; retain the existing wire type for old Q8 goals."""
    from .goals import _exact_math

    request = request_for_goal(goal)
    converted, trace = evaluate(request, result=feasible)
    evidence = {'kind': 'goal_closure', 'goal_kind': goal['kind'], 'feasible_set': _exact_math(feasible),
                'conversion': trace, 'checks': [{'kind': 'answer_conversion_recomputed', 'passed': True}]}
    quantities = [decode_value(row['output']) for row in trace['steps'] if row['step']['operation'] == 'extract_quantity']
    if goal['kind'] == 'find_extrema_expression':
        evidence['extrema'] = [{**row, 'answer': ({'status': 'attained', 'value': _exact_math(value['value'])}
                                               if value['available'] else {'status': value['status']}), 'proof': value['proof']}
                              for row, value in zip(goal['extrema'], quantities, strict=True)]
        if converted['type'] == 'undefined':
            reason = 'extremum_not_attained' if converted['reason'] == 'quantity_unavailable' else converted['reason']
            return {'kind': goal['kind'], 'status': 'undefined', 'reason': reason}, evidence
        return {'kind': goal['kind'], 'status': 'value', 'value': _exact_math(converted['value'])}, evidence
    answer = {'kind': 'derived_answer', 'request_kind': request['kind']}
    kind = converted['type']
    if kind == 'quantity':
        answer.update(status=converted['status'], quantity=converted['quantity'])
        if converted['available']:
            answer['value'] = _exact_math(converted['value'])
        elif converted['bound'] is not None:
            answer['bound'] = _exact_math(converted['bound'])
    elif kind in ('scalar', 'set'):
        answer.update(status='value' if kind == 'scalar' else 'set', **{'value' if kind == 'scalar' else 'set': _exact_math(converted['value'])})
    elif kind == 'boolean':
        answer.update(status='boolean', value=converted['value'])
    else:
        answer.update(status='undefined', reason=converted['reason'])
    return answer, evidence
