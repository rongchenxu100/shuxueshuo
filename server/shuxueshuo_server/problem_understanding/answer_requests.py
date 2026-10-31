"""Source-only answer requests, compiled into a bounded conversion plan.

The request describes what the question asks, never a computed answer or a
solver method. Plans are produced by code, not accepted as model instructions.
"""

from copy import deepcopy

import sympy as sp

from .notation_parser import NotationError, parse

VERSION = 'answer-conversion/v1'
QUANTITIES = ('minimum', 'maximum', 'infimum', 'supremum')


def arithmetic(ast, values, *, depth=0, count=None):
    """Bounded exact arithmetic for option endpoints and named extrema."""
    import sympy as sp

    count = count if count is not None else [0]
    count[0] += 1
    if depth > 12 or count[0] > 64:
        raise NotationError('range_task.expression_budget')
    read = lambda node: arithmetic(node, values, depth=depth+1, count=count)
    if ast[0] == 'name':
        if ast[1] not in values:
            raise NotationError('range_task.unknown_symbol')
        return values[ast[1]]
    if ast[0] == 'number':
        result = sp.Rational(ast[1])
        if max(abs(int(result.p)).bit_length(), int(result.q).bit_length()) > 64:
            raise NotationError('range_task.coefficient_budget')
        return result
    if ast[0] == 'neg':
        return -read(ast[1])
    if ast[:2] == ['call', 'sqrt']:
        value = read(ast[2])
        if value.is_nonnegative is False:
            raise NotationError('range_task.undefined_expression')
        return sp.sqrt(value)
    if ast[0] not in ('+', '-', '*', '/', '^') or len(ast) != 3:
        raise NotationError('range_task.arithmetic_required')
    left, right = read(ast[1]), read(ast[2])
    if ast[0] == '/' and right == 0:
        raise NotationError('range_task.undefined_expression')
    if ast[0] == '^' and (right.is_Integer is not True or not 0 <= right <= 4):
        raise NotationError('range_task.bounded_integer_power_required')
    if ast[0] == '^' and left == right == 0:
        raise NotationError('range_task.undefined_expression')
    value = {'+': lambda: left+right, '-': lambda: left-right, '*': lambda: left*right,
             '/': lambda: left/right, '^': lambda: left**right}[ast[0]]()
    if isinstance(value, sp.Rational) and max(abs(int(value.p)).bit_length(), int(value.q).bit_length()) > 512:
        raise NotationError('range_task.coefficient_budget')
    return value



def validate_goal_request(goal):
    """Only concrete range goals expose the public answer-request contract."""
    if 'answer_request' not in goal:
        return
    if goal.get('kind') != 'find_range':
        raise NotationError('answer_request.unsupported_goal')
    if not isinstance(goal.get('object'), str) or not goal['object'].strip():
        raise NotationError('answer_request.function_target_required')
    validate_request(goal['answer_request'])


def request_for_goal(goal):
    validate_goal_request(goal)
    if 'answer_request' in goal:
        return deepcopy(goal['answer_request'])
    if goal['kind'] == 'find_extrema_expression':
        return {'kind': 'expression', 'bindings': [
            {'symbol': row['symbol'], 'quantity': row['kind']} for row in goal['extrema']],
            'expression': goal['expression']}
    if goal['kind'] == 'select_range_domain':
        return {'kind': 'select', 'predicate': {'kind': 'compare_set', 'expected': goal['expected_range'], 'relation': 'equal'},
                'when': goal['select_relation'] == 'matches', 'selection_mode': goal['selection_mode']}
    return None


def validate_request(request):
    """Validate the public graph-answer-request/v1 contract; no internal select."""
    from ..graph_lesson.range_syntax import range_domain

    if not isinstance(request, dict):
        raise NotationError('answer_request.invalid_fields')
    kind = request.get('kind')
    if kind == 'select':
        raise NotationError('answer_request.candidate_inputs_required')
    fields = {'identity': {'kind'}, 'extremum': {'kind', 'quantity'},
              'expression': {'kind', 'bindings', 'expression'},
              'compare_set': {'kind', 'expected', 'relation'}}
    if kind not in fields or set(request) != fields[kind]:
        raise NotationError('answer_request.invalid_fields')
    if kind == 'extremum' and request['quantity'] not in QUANTITIES:
        raise NotationError('answer_request.unknown_quantity')
    if kind == 'expression':
        rows = request['bindings']
        if not isinstance(rows, list) or not 1 <= len(rows) <= 4:
            raise NotationError('answer_request.binding_budget')
        if any(set(row) != {'symbol', 'quantity'} or row['quantity'] not in QUANTITIES for row in rows):
            raise NotationError('answer_request.invalid_binding')
        names = [row['symbol'] for row in rows]
        if len(set(names)) != len(names) or any(parse(name) != ['name', name] for name in names):
            raise NotationError('answer_request.distinct_symbols_required')
        arithmetic(parse(request['expression']), {name: sp.Symbol(name, real=True) for name in names})
    elif kind == 'compare_set':
        if request['relation'] not in ('equal', 'not_equal'):
            raise NotationError('answer_request.unknown_relation')
        range_domain(parse(request['expected']))


def compile_candidate_plan(request):
    """Internal candidate adapter; never accepted as a source answer_request."""
    if (not isinstance(request, dict) or request.get('kind') != 'select'
            or set(request) != {'kind', 'predicate', 'when', 'selection_mode'}):
        raise NotationError('answer_request.invalid_selection')
    if not isinstance(request['predicate'], dict) or request['predicate'].get('kind') != 'compare_set':
        raise NotationError('answer_request.candidate_inputs_required')
    if type(request['when']) is not bool or request['selection_mode'] not in ('single', 'multiple', 'unspecified'):
        raise NotationError('answer_request.invalid_selection')
    validate_request(request['predicate'])
    return _compile_plan(request)


def compile_plan(request):
    """Compile a public request with explicit dependencies, without solving."""
    validate_request(request)
    return _compile_plan(request)


def _compile_plan(request):
    kind = request['kind']
    steps = []
    if kind == 'identity':
        steps.append({'id': 'answer', 'operation': 'return_set', 'source': 'result'})
    elif kind == 'extremum':
        steps.append({'id': 'answer', 'operation': 'extract_quantity', 'source': 'result', 'quantity': request['quantity']})
    elif kind == 'expression':
        for index, row in enumerate(request['bindings']):
            steps.append({'id': f'quantity-{index}', 'operation': 'extract_quantity', 'source': 'result',
                          'quantity': row['quantity'], 'symbol': row['symbol']})
        steps.append({'id': 'answer', 'operation': 'evaluate_expression',
                      'bindings': {row['symbol']: f'quantity-{i}' for i, row in enumerate(request['bindings'])},
                      'expression': request['expression']})
    elif kind == 'compare_set':
        steps.append({'id': 'answer', 'operation': 'compare_set', 'source': 'result',
                      'expected': request['expected'], 'relation': request['relation']})
    elif kind == 'select':
        steps.append({'id': 'comparisons', 'operation': 'compare_candidates', 'source': 'candidates',
                      'predicate': deepcopy(request['predicate'])})
        steps.append({'id': 'answer', 'operation': 'select_truth', 'source': 'comparisons',
                      'when': request['when'], 'selection_mode': request['selection_mode']})
    else:
        raise NotationError('answer_request.invalid_fields')
    return {'version': VERSION, 'input': 'candidates' if kind == 'select' else 'set', 'steps': steps, 'output': 'answer'}
