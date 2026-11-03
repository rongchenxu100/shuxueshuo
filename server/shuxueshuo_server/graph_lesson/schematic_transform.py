"""G4: transform verified facts from a pictured curve without inventing f.

Facts describe only the displayed portion. They distinguish rough choices;
they neither define the unknown function nor prove global monotonicity.
"""
from copy import deepcopy

import sympy as sp

from ..problem_understanding.notation_parser import NotationError, parse
from .function_formula import _polynomial
from .function_graph import rational

VERSION = 'function-graph-schematic-transform/v1'


def source(goal):
    graph = goal['source_graph']
    name, variable = parse(graph['function']), parse(goal['variable'])
    target = parse(goal['expression'])
    if name[0] != 'name' or variable[0] != 'name' or name == variable:
        raise ValueError('function_graph.function_and_variable_required')
    if len(target) != 3 or target[:2] != ['call', name[1]]:
        raise ValueError('function_graph.same_unknown_function_required')
    poly = _polynomial(target[2], variable, root_input=False)
    a, b = poly.nth(1), poly.nth(0)
    if poly.degree() != 1 or a not in (-1, 1):
        raise ValueError('function_graph.schematic_translation_or_reflection_required')
    if 'input_domain' in goal or 'transformations' in goal:
        raise ValueError('function_graph.schematic_extra_transform_unsupported')
    return a, b


def facts(value):
    if value['shape'] != 'shown_monotone_curve':
        raise ValueError('function_graph.shown_monotone_curve_required')
    if value['direction'] not in ('increasing', 'decreasing'):
        raise ValueError('function_graph.unverified_direction')
    point = value['x_intercept']
    x = rational(point['x'])
    if point['evidence'] not in ('labelled', 'origin') or (point['evidence'] == 'origin' and x != 0):
        raise ValueError('function_graph.unlabelled_intercept')
    return value['direction'], x


def describe(goal, target_ref, extra_refs=()):
    desc = {'source': deepcopy(goal), 'target_ref': target_ref, 'source_refs': [target_ref],
            'extra_source_refs': list(extra_refs), 'structure_version': VERSION,
            'structure_supported': False, 'reason': ''}
    try:
        if extra_refs:
            raise ValueError('function_graph.extra_conditions_unsupported')
        source(goal)
        if goal['comparison'] != 'rough_shape' or goal['selection_mode'] not in ('single', 'unspecified'):
            raise ValueError('function_graph.schematic_rough_single_choice_required')
        if goal['source_graph']['uncertainties']:
            raise ValueError('function_graph.unverified_source_graph')
        facts(goal['source_graph']['facts'])
        options = goal['options']
        if not 2 <= len(options) <= 8 or any(len({o[k] for o in options}) != len(options) for k in ('option_id', 'label')):
            raise ValueError('function_graph.duplicate_options')
        for option in options:
            if option['uncertainties']:
                raise ValueError('function_graph.unverified_option_graph')
            facts(option['facts'])
        desc['structure_supported'] = True
    except (ValueError, NotationError, TypeError, KeyError) as exc:
        desc['reason'] = getattr(exc, 'code', str(exc))
    return desc


def verdict(option, direction, zero):
    original_direction, original_zero = facts(option['facts'])
    differences = []
    if original_direction != direction:
        differences.append('shown_direction')
    if original_zero != zero:
        differences.append('x_intercept')
    return {'option_id': option['option_id'], 'label': option['label'],
            'matches': not differences, 'differences': differences}


def solve(description):
    if not description['structure_supported']:
        raise ValueError(description['reason'])
    goal = description['source']
    a, b = source(goal)
    direction, zero = facts(goal['source_graph']['facts'])
    new_direction = direction if a == 1 else ('decreasing' if direction == 'increasing' else 'increasing')
    mapped_zero = (zero-b)/a
    rows = [verdict(option, new_direction, mapped_zero) for option in goal['options']]
    matches = [row['option_id'] for row in rows if row['matches']]
    if len(matches) != 1:
        raise ValueError('function_graph.indistinguishable_options' if matches else 'function_graph.no_matching_option')
    return {'kind': 'select_function_graph', 'structure_version': VERSION, 'a': a, 'b': b,
            'source_zero': zero, 'target_zero': mapped_zero, 'source_direction': direction,
            'target_direction': new_direction, 'option_verdicts': rows, 'correct_option_id': matches[0]}


def verify(description, result):
    """Re-check original facts and the input identity, independently of solve()."""
    try:
        goal = description['source']
        if describe(goal, description['target_ref'], description['extra_source_refs']) != description or not description['structure_supported']:
            return False
        if set(result) != {'kind', 'structure_version', 'a', 'b', 'source_zero', 'target_zero',
                           'source_direction', 'target_direction', 'option_verdicts', 'correct_option_id'}:
            return False
        a, b = source(goal)
        direction, zero = facts(goal['source_graph']['facts'])
        if (result['kind'] != 'select_function_graph' or result['structure_version'] != VERSION
                or (result['a'], result['b'], result['source_zero'], result['source_direction']) != (a, b, zero, direction)
                or sp.simplify(a*result['target_zero']+b-zero) != 0):
            return False
        expected = direction if a > 0 else ('decreasing' if direction == 'increasing' else 'increasing')
        if result['target_direction'] != expected:
            return False
        rows = [verdict(o, expected, result['target_zero']) for o in goal['options']]
        return rows == result['option_verdicts'] and [r['option_id'] for r in rows if r['matches']] == [result['correct_option_id']]
    except (ValueError, NotationError, TypeError, KeyError, AttributeError):
        return False
