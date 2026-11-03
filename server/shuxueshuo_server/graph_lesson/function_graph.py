"""FR-T2: exact affine-absolute transformations and source-bound rough graphs.

Coordinates come only from labelled source facts. Pixel slopes and sampled
points never decide an answer. Incomplete or indistinguishable choices fail
closed rather than promoting a plausible-looking picture to a unique answer.
"""

from copy import deepcopy

import sympy as sp

from ..problem_understanding.notation_parser import NotationError, parse
from .function_formula import _bounded, _polynomial
from .range_syntax import range_domain

VERSION = 'function-graph-affine-absolute/v1'


def rational(text):
    polynomial = _polynomial(parse(text), ['name', '_unused'], root_input=False)
    if polynomial.degree() > 0:
        raise ValueError('function_graph.fixed_coordinate_required')
    return _bounded(polynomial.nth(0))


def source(goal):
    """Inspect original syntax without erasing poles or degeneracies."""
    variable = parse(goal['variable'])
    if variable[0] != 'name':
        raise ValueError('function_graph.variable_required')
    ast = parse(goal['expression'])
    shift = sp.S.Zero
    if ast[0] in ('+', '-'):
        shift = rational_ast(ast[2]) * (1 if ast[0] == '+' else -1)
        ast = ast[1]
    if ast[:2] != ['call', 'abs'] or len(ast) != 3:
        raise ValueError('function_graph.affine_absolute_required')
    polynomial = _polynomial(ast[2], variable, root_input=False)
    if polynomial.degree() > 1:
        raise ValueError('function_graph.affine_absolute_required')
    a, b = polynomial.nth(1), polynomial.nth(0)
    if a == 0:
        raise ValueError('function_graph.constant_degeneracy')
    domain = range_domain(parse(goal.get('input_domain', 'ℝ')))
    if domain != sp.S.Reals and not isinstance(domain, sp.Interval):
        raise ValueError('function_graph.interval_required')
    if isinstance(domain, sp.Interval):
        for value in (domain.start, domain.end):
            if value.is_finite:
                _bounded(value)
    return a, b, shift, domain


def rational_ast(ast):
    polynomial = _polynomial(ast, ['name', '_unused'], root_input=False)
    if polynomial.degree() > 0:
        raise ValueError('function_graph.fixed_coefficient_required')
    return _bounded(polynomial.nth(0))


def identical_function_definition(goal, text):
    """Only the same explicit f(x) rule is redundant with a pictured-choice goal."""
    try:
        return (goal.get('kind') == 'select_function_graph' and 'source_graph' not in goal
                and 'transformations' not in goal
                and parse(text) == ['=', ['call', 'f', parse(goal['variable'])], parse(goal['expression'])])
    except (ValueError, NotationError, TypeError, KeyError):
        return False


def describe(goal, target_ref, extra_refs=(), *, given_definitions=()):
    if 'source_graph' in goal:
        from .schematic_transform import describe as describe_schematic
        return describe_schematic(goal, target_ref, extra_refs)
    if goal.get('transformations') is not None:
        from .quadratic_translation import describe as describe_translation
        return describe_translation(goal, target_ref, extra_refs)
    if goal.get('kind') in ('draw_function_graph', 'solve_graph_inequality'):
        from .absolute_graph import describe as absolute_describe
        return absolute_describe(goal, target_ref, extra_refs)
    description = {'source': deepcopy(goal), 'target_ref': target_ref,
                   'source_refs': [target_ref], 'extra_source_refs': list(extra_refs),
                   'structure_version': VERSION, 'structure_supported': False, 'reason': ''}
    if given_definitions:
        description['given_definitions'] = deepcopy(list(given_definitions))
        description['source_refs'].extend(row['source_ref'] for row in given_definitions)
    try:
        if extra_refs:
            raise ValueError('function_graph.extra_conditions_unsupported')
        if len(given_definitions) > 1 or any(
                not identical_function_definition(goal, row['expression']) for row in given_definitions):
            raise ValueError('function_graph.shared_definition_mismatch')
        a, b, _, domain = source(goal)
        if domain != sp.S.Reals and not (domain.start < -b/a < domain.end):
            raise ValueError('function_graph.single_branch_domain_unsupported')
        if goal.get('selection_mode') not in ('single', 'unspecified'):
            raise ValueError('function_graph.single_choice_required')
        if goal['comparison'] != 'rough_shape':
            raise ValueError('function_graph.exact_equivalence_requires_full_model')
        options = goal['options']
        if (len({o['option_id'] for o in options}) != len(options)
                or len({o['label'] for o in options}) != len(options)):
            raise ValueError('function_graph.duplicate_options')
        for option in options:
            facts = option['facts']
            if option.get('uncertainties') or facts['shape'] != 'two_straight_branches':
                raise ValueError('function_graph.unverified_shape')
            if facts['vertex']['evidence'] != 'labelled':
                raise ValueError('function_graph.unlabelled_vertex')
            rational(facts['vertex']['x'])
            rational(facts['vertex']['y'])
            if any(facts[key] not in ('increasing', 'decreasing')
                   for key in ('left_direction', 'right_direction')):
                raise ValueError('function_graph.unverified_direction')
            if domain != sp.S.Reals and 'domain' not in facts:
                raise ValueError('function_graph.option_domain_missing')
            if 'domain' in facts:
                range_domain(parse(facts['domain']))
        description['structure_supported'] = True
    except (ValueError, NotationError, TypeError, KeyError) as exc:
        description['reason'] = getattr(exc, 'code', str(exc))
    return description


def describe_scoped(goal, target_ref, sources):
    """Retain every visible source; consume only an identical explicit function rule."""
    absolute = goal.get('kind') in ('draw_function_graph', 'solve_graph_inequality')
    pictured = (goal.get('kind') == 'select_function_graph' and 'source_graph' not in goal
                and 'transformations' not in goal)
    if not (absolute or pictured):
        return describe(goal, target_ref, [row['source_ref'] for row in sources])
    definitions, extra = [], []
    for row in sources:
        if '/definitions/' in row['source_ref']:
            definitions.append({key: row[key] for key in ('source_ref', 'expression')})
        else:
            extra.append(row['source_ref'])
    if absolute:
        from .absolute_graph import describe as absolute_describe
        return absolute_describe(goal, target_ref, extra, given_definitions=definitions)
    return describe(goal, target_ref, extra, given_definitions=definitions)


def transform_interval(domain, a, b):
    """u=ax+b; endpoint inclusion follows its point when a is negative."""
    if domain == sp.S.Reals:
        return domain
    ends = [a*domain.start+b, a*domain.end+b]
    closed = [not domain.left_open, not domain.right_open]
    if a < 0:
        ends.reverse()
        closed.reverse()
    return sp.Interval(*ends, left_open=not closed[0], right_open=not closed[1])


def option_verdict(option, h, k, domain):
    facts = option['facts']
    reasons = []
    for field, actual, expected in (
        ('vertex_x', rational(facts['vertex']['x']), h),
        ('vertex_y', rational(facts['vertex']['y']), k),
        ('left_direction', facts['left_direction'], 'decreasing'),
        ('right_direction', facts['right_direction'], 'increasing'),
    ):
        if actual != expected:
            reasons.append(field)
    if 'domain' in facts and range_domain(parse(facts['domain'])) != domain:
        reasons.append('domain')
    return {'option_id': option['option_id'], 'label': option['label'],
            'matches': not reasons, 'differences': reasons}


def solve(description):
    if 'source_graph' in description['source']:
        from .schematic_transform import solve as solve_schematic
        return solve_schematic(description)
    if description['source'].get('transformations') is not None:
        from .quadratic_translation import solve as solve_translation
        return solve_translation(description)
    if description['source']['kind'] != 'select_function_graph':
        from .absolute_graph import solve as solve_absolute
        return solve_absolute(description)
    if not description['structure_supported']:
        raise ValueError(description['reason'])
    goal = description['source']
    a, b, c, domain = source(goal)
    h = -b/a
    verdicts = [option_verdict(option, h, c, domain) for option in goal['options']]
    matches = [row['option_id'] for row in verdicts if row['matches']]
    # G1 never resolves a tie by choosing the first picture or by pixel slope.
    if len(matches) != 1:
        raise ValueError('function_graph.indistinguishable_options' if matches else 'function_graph.no_matching_option')
    return {'kind': 'select_function_graph', 'a': a, 'b': b, 'c': c,
            'vertex': [h, c], 'domain': domain, 'base_domain': transform_interval(domain, a, b),
            'option_verdicts': verdicts, 'correct_option_id': matches[0]}


def verify(description, result):
    """Independent identity, endpoint transport and every original option check."""
    if 'source_graph' in description['source']:
        from .schematic_transform import verify as verify_schematic
        return verify_schematic(description, result)
    if description['source'].get('transformations') is not None:
        from .quadratic_translation import verify as verify_translation
        return verify_translation(description, result)
    if description['source']['kind'] != 'select_function_graph':
        from .absolute_graph import verify as verify_absolute
        return verify_absolute(description, result)
    try:
        goal = description['source']
        current = describe(goal, description['target_ref'], description['extra_source_refs'],
                           given_definitions=description.get('given_definitions', ()))
        if current != description or not current['structure_supported']:
            return False
        a, b, c, domain = source(goal)
        if set(result) != {'kind', 'a', 'b', 'c', 'vertex', 'domain', 'base_domain', 'option_verdicts', 'correct_option_id'}:
            return False
        h, k = result['vertex']
        if (result['kind'] != 'select_function_graph' or
                (result['a'], result['b'], result['c'], result['domain']) != (a, b, c, domain)
                or a*h+b != 0 or k != c):
            return False
        # Check the proposed inverse point map, including open finite ends.
        base = result['base_domain']
        if domain == sp.S.Reals:
            if base != sp.S.Reals:
                return False
        else:
            if not isinstance(base, sp.Interval):
                return False
            mapped = [(base.start-b)/a, (base.end-b)/a]
            opened = [base.left_open, base.right_open]
            if a < 0:
                mapped.reverse()
                opened.reverse()
            if mapped != [domain.start, domain.end] or opened != [domain.left_open, domain.right_open]:
                return False
        rows = result['option_verdicts']
        if len(rows) != len(goal['options']):
            return False
        for option, row in zip(goal['options'], rows, strict=True):
            if row != option_verdict(option, h, k, domain):
                return False
        matched = [r['option_id'] for r in rows if r['matches']]
        return len(matched) == 1 and matched[0] == result['correct_option_id']
    except (ValueError, NotationError, TypeError, KeyError, AttributeError):
        return False
