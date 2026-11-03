"""G3: ordered translations of |quadratic|+constant, with source-only landmarks.

An omitted landmark never counts as a mismatch. A rough option is accepted
only with the complete feature whitelist; a visible contradiction can exclude
an otherwise partial drawing without inventing its hidden coordinates.
"""
from copy import deepcopy

import sympy as sp

from ..problem_understanding.notation_parser import NotationError, parse
from .function_formula import _bounded, _polynomial
from .function_graph import rational, rational_ast
from .range_syntax import range_domain

VERSION = 'function-graph-quadratic-translation/v1'


def source(goal):
    variable = parse(goal['variable'])
    if variable[0] != 'name':
        raise ValueError('function_graph.variable_required')
    ast, offset = parse(goal['expression']), sp.S.Zero
    if ast[0] in ('+', '-'):
        offset = rational_ast(ast[2]) * (1 if ast[0] == '+' else -1)
        ast = ast[1]
    if ast[:2] != ['call', 'abs'] or len(ast) != 3:
        raise ValueError('function_graph.absolute_quadratic_required')
    poly = _polynomial(ast[2], variable, root_input=False)
    if poly.degree() != 2:
        raise ValueError('function_graph.quadratic_required')
    x = sp.Symbol(variable[1], real=True)
    poly = sp.Poly(poly.as_expr().subs(poly.gen, x), x)
    discriminant = poly.discriminant()
    if discriminant <= 0 or sp.sqrt(discriminant).is_Rational is not True:
        raise ValueError('function_graph.two_rational_zeros_required')
    _bounded(discriminant)
    if range_domain(parse(goal.get('input_domain', 'ℝ'))) != sp.S.Reals:
        raise ValueError('function_graph.translation_full_domain_required')
    operations = goal['transformations']
    if not 1 <= len(operations) <= 2:
        raise ValueError('function_graph.translation_count')
    axes, moves = [], []
    for operation in operations:
        direction, distance = operation['direction'], rational(operation['distance'])
        if direction not in ('left', 'right', 'up', 'down') or distance <= 0:
            raise ValueError('function_graph.positive_translation_required')
        horizontal = direction in ('left', 'right')
        axes.append(horizontal)
        delta = distance * (-1 if direction in ('left', 'down') else 1)
        moves.append({'direction': direction, 'distance': distance,
                      'dx': delta if horizontal else sp.S.Zero,
                      'dy': sp.S.Zero if horizontal else delta})
    if len(set(axes)) != len(axes):
        raise ValueError('function_graph.one_move_per_axis')
    return x, poly.as_expr(), offset, moves


def describe(goal, target_ref, extra_refs=()):
    desc = {'source': deepcopy(goal), 'target_ref': target_ref, 'source_refs': [target_ref],
            'extra_source_refs': list(extra_refs), 'structure_version': VERSION,
            'structure_supported': False, 'reason': ''}
    try:
        if extra_refs:
            raise ValueError('function_graph.extra_conditions_unsupported')
        source(goal)
        if goal['comparison'] != 'rough_shape':
            raise ValueError('function_graph.exact_equivalence_requires_full_model')
        if goal['selection_mode'] not in ('single', 'unspecified'):
            raise ValueError('function_graph.single_choice_required')
        options = goal['options']
        if not 2 <= len(options) <= 8 or any(len({o[key] for o in options}) != len(options) for key in ('option_id', 'label')):
            raise ValueError('function_graph.duplicate_options')
        for option in options:
            facts = option['facts']
            if option['uncertainties'] or facts['shape'] != 'turning_points':
                raise ValueError('function_graph.unverified_shape')
            if facts['outer_direction'] not in ('up', 'down', 'unknown'):
                raise ValueError('function_graph.unverified_direction')
            if facts['symmetry'] not in ('symmetric', 'asymmetric', 'unknown'):
                raise ValueError('function_graph.unverified_symmetry')
            points = facts['landmarks']
            if not points or len({p['role'] for p in points}) != len(points):
                raise ValueError('function_graph.duplicate_landmarks')
            for point in points:
                if point['role'] not in ('left_corner', 'center', 'right_corner') or point['evidence'] not in ('labelled', 'axis'):
                    raise ValueError('function_graph.unlabelled_landmark')
                if not any(key in point for key in ('x', 'y')):
                    raise ValueError('function_graph.empty_landmark')
                for key in ('x', 'y'):
                    if key in point:
                        value = rational(point[key])
                        if point['evidence'] == 'axis' and value != 0:
                            raise ValueError('function_graph.axis_coordinate_must_be_zero')
        desc['structure_supported'] = True
    except (ValueError, NotationError, TypeError, KeyError) as exc:
        desc['reason'] = getattr(exc, 'code', str(exc))
    return desc


def landmarks(p, c, x):
    left, right = sorted(sp.solve(p, x))
    center = (left+right)/2
    return [[left, c], [center, abs(p.subs(x, center))+c], [right, c]]


def option_verdict(option, points):
    facts, differences = option['facts'], []
    if facts['outer_direction'] == 'down':
        differences.append('outer_direction')
    if facts['symmetry'] == 'asymmetric':
        differences.append('symmetry')
    expected = dict(zip(('left_corner', 'center', 'right_corner'), points, strict=True))
    known = {}
    for point in facts['landmarks']:
        role = point['role']
        known[role] = set(point) & {'x', 'y'}
        for index, coordinate in enumerate(('x', 'y')):
            if coordinate in point and rational(point[coordinate]) != expected[role][index]:
                differences.append(role+'_'+coordinate)
    sufficient = (facts['outer_direction'] == 'up' and facts['symmetry'] == 'symmetric' and known.get('center') == {'x', 'y'}
                  and any(known.get(role) == {'x', 'y'} for role in ('left_corner', 'right_corner')))
    if not differences and not sufficient:
        raise ValueError('function_graph.insufficient_option_features')
    return {'option_id': option['option_id'], 'label': option['label'],
            'matches': not differences, 'differences': differences}


def solve(description):
    if not description['structure_supported']:
        raise ValueError(description['reason'])
    goal = description['source']
    x, p, c, moves = source(goal)
    states = [{'polynomial': p, 'offset': c, 'landmarks': landmarks(p, c, x)}]
    for move in moves:
        p, c = p.subs(x, x-move['dx']), c+move['dy']
        states.append({'polynomial': p, 'offset': c, 'landmarks': landmarks(p, c, x)})
    verdicts = [option_verdict(option, states[-1]['landmarks']) for option in goal['options']]
    matches = [v['option_id'] for v in verdicts if v['matches']]
    if len(matches) != 1:
        raise ValueError('function_graph.indistinguishable_options' if matches else 'function_graph.no_matching_option')
    return {'kind': 'select_function_graph', 'structure_version': VERSION, 'variable': x,
            'moves': moves, 'states': states, 'option_verdicts': verdicts, 'correct_option_id': matches[0]}


def verify(description, result):
    """Check each polynomial identity and each transported point independently."""
    try:
        goal = description['source']
        if describe(goal, description['target_ref'], description['extra_source_refs']) != description or not description['structure_supported']:
            return False
        x, p, c, moves = source(goal)
        if (set(result) != {'kind', 'structure_version', 'variable', 'moves', 'states', 'option_verdicts', 'correct_option_id'}
                or result['kind'] != 'select_function_graph' or result['structure_version'] != VERSION
                or result['variable'] != x or result['moves'] != moves or len(result['states']) != len(moves)+1):
            return False
        previous = None
        for index, state in enumerate(result['states']):
            if set(state) != {'polynomial', 'offset', 'landmarks'}:
                return False
            if index:
                move = moves[index-1]
                p = previous['polynomial'].subs(x, x-move['dx'])
                c = previous['offset']+move['dy']
                transported = [[u+move['dx'], v+move['dy']] for u, v in previous['landmarks']]
                if state['landmarks'] != transported:
                    return False
            if sp.expand(state['polynomial']-p) != 0 or state['offset'] != c:
                return False
            left, center, right = state['landmarks']
            if not (left[0] < center[0] < right[0] and left[0]+right[0] == 2*center[0]):
                return False
            if any(sp.simplify(p.subs(x, point[0])) != 0 or point[1] != c for point in (left, right)):
                return False
            if sp.diff(p, x).subs(x, center[0]) != 0 or center[1] != abs(p.subs(x, center[0]))+c:
                return False
            previous = state
        rows = [option_verdict(o, previous['landmarks']) for o in goal['options']]
        matched = [row['option_id'] for row in rows if row['matches']]
        return rows == result['option_verdicts'] and matched == [result['correct_option_id']]
    except (ValueError, NotationError, TypeError, KeyError, AttributeError):
        return False
