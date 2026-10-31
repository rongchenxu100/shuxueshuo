"""M3 polynomial images with an independent monotone-cover verification."""

from copy import deepcopy
from itertools import pairwise

import sympy as sp

from ..range_syntax import (
    MAX_FINITE_INPUTS,
    coefficients_ast,
    range_domain,
    range_expression,
    rational_expression,
)
from ..stage_one.function_domain import _fixed_poly
from ..stage_one.function_range import inspect_range_target
from .capabilities import (
    CapabilityGap,
    LocalCheckFailed,
    quadratic_sign_pattern,
    result,
    solve_quadratic,
)
from .capabilities.ranges import quadratic_interval_range
from .math_values import math_value

METHOD_ID = 'method-quadratic-interval-range'
DIRECT_METHOD = 'method-direct-range'
SUBSTITUTION_METHOD = 'method-substitution-range'
FRACTION_METHOD = 'method-fraction-split-range'
EQUATION_METHOD = 'method-equation-real-root-range'
ENUMERATION_METHOD = 'method-finite-range'


def _inner(description):
    variable = sp.Symbol(description['variable'], real=True)
    if description.get('rational'):
        return rational_expression(description['expression_ast'], variable), variable
    if description.get('substitution'):
        if description['substitution']['kind'] == 'affine':
            return sum((sp.Rational(c)*variable**i for i, c in
                        enumerate(description['substitution']['coefficients'])), sp.S.Zero), variable
        return range_expression(description['expression_ast'], variable), variable
    coefficients = [sp.Rational(v.numerator, v.denominator)
                    for v in _fixed_poly(description['inner_ast'], max_degree=2)]
    return sum((v * variable**i for i, v in enumerate(coefficients)), sp.S.Zero), variable


def natural_domain(description):
    if description.get('rational'):
        variable = sp.Symbol(description['variable'], real=True)
        excluded = sp.S.EmptySet
        for row in description['rational']['denominators']:
            divisor = range_expression(row['ast'], variable)
            excluded |= sp.solveset(divisor, variable, domain=sp.S.Reals)
        return sp.S.Reals - excluded
    substitution = description.get('substitution')
    if substitution:
        if substitution['atom_kind'] != 'sqrt':
            return sp.S.Reals
        variable = sp.Symbol(description['variable'], real=True)
        inner = range_expression(substitution['argument_ast'], variable)
        roots = solve_quadratic(inner, variable)['outputs']
        return quadratic_sign_pattern(inner, variable, **roots, strict=False)['outputs']['solution']
    if not description['radical']:
        return sp.S.Reals
    inner, variable = _inner(description)
    roots = solve_quadratic(inner, variable)['outputs']
    return quadratic_sign_pattern(inner, variable, **roots, strict=False)['outputs']['solution']


def components(domain):
    if isinstance(domain, sp.Union):
        return list(domain.args)
    if isinstance(domain, (sp.Interval, sp.FiniteSet)):
        return [domain]
    raise CapabilityGap('range.interval_components_required')


def inputs(description):
    if not description.get('structure_supported'):
        raise CapabilityGap(description.get('reason') or 'range.input_class_unavailable')
    expression, variable = _inner(description)
    natural = natural_domain(description)
    declared = range_domain(description['declared_domain_ast'])
    if description['declared_domain_source_ref'] and declared.is_subset(natural) is not True:
        raise CapabilityGap('range.declared_domain_conflict')
    domain = natural & declared & range_domain(description['input_domain_ast'])
    for row in description['restriction_facts']:
        domain &= range_domain(row['domain_ast'])
    if domain is sp.S.EmptySet:
        raise CapabilityGap('range.empty_input')
    if domain is sp.S.Reals:
        domain = sp.Interval(-sp.oo, sp.oo)
    if len(components(domain)) > 16:
        raise CapabilityGap('range.component_budget')
    if isinstance(domain, sp.FiniteSet) and len(domain) > MAX_FINITE_INPUTS:
        raise CapabilityGap('range.finite_input_budget')
    if not isinstance(domain, sp.FiniteSet) and any(
            isinstance(part, sp.FiniteSet) and len(part) > 1 for part in components(domain)):
        raise CapabilityGap('range.mixed_finite_components_unsupported')
    return expression, variable, domain


def admitted(context, method=None):
    if context.get('goal', {}).get('kind') == 'select_range_domain':
        from .range_tasks import options_admitted
        return options_admitted(context, method)
    if context.get('goal', {}).get('kind') == 'find_extrema_expression':
        from .range_tasks import child_context
        return admitted(child_context(context), method)
    if context.get('goal', {}).get('kind') == 'find_translation_range':
        from .translation_range import METHOD
        from .translation_range import admitted as admitted_translation
        return method in (None, METHOD) and admitted_translation(context)
    if context.get('goal', {}).get('kind') == 'find_abstract_range':
        from .abstract_function_range import admitted as admitted_abstract
        return method in (None, SUBSTITUTION_METHOD) and admitted_abstract(context)
    if not (context.get('goal', {}).get('kind') == 'find_range'
            and 'object' in context['goal']
            and context.get('range_goal', {}).get('structure_supported') is True):
        return False
    try:
        _, _, domain = inputs(context['range_goal'])
        from .finite_range import finite_task, input_rows
        if finite_task(context['range_goal'], domain) and not context.get('range_subproblem'):
            input_rows(context)
            return method in (None, ENUMERATION_METHOD)
        if context['range_goal'].get('substitution'):
            _prepare_range_substitution(context)
    except (CapabilityGap, ValueError):
        return False
    if context['range_goal'].get('rational'):
        spec = context['range_goal']['rational']
        methods = []
        if spec.get('fraction_split'):
            methods.append(FRACTION_METHOD)
        if spec.get('equation_denominator_ast') and domain == sp.S.Reals:
            methods.append(EQUATION_METHOD)
        return bool(methods) if method is None else method in methods
    elif context['range_goal'].get('substitution'):
        selected = SUBSTITUTION_METHOD
    else:
        selected = DIRECT_METHOD if context['range_goal']['degree'] <= 1 else METHOD_ID
    if (context.get('range_subproblem') and method == METHOD_ID
            and not any(context['range_goal'].get(key) for key in ('substitution', 'rational'))):
        return True
    return method is None or method == selected


def domain_ast(domain):
    """Transport exact input sets to a child method without turning holes into a hull."""
    from ...problem_understanding.notation_parser import parse
    def endpoint(value):
        return parse(str(value).replace('**', '^').replace('oo', '∞'))
    if isinstance(domain, sp.Union):
        parts = [domain_ast(part) for part in domain.args]
        def union(rows):
            if len(rows) == 1:
                return rows[0]
            middle = len(rows)//2
            return ['∪', union(rows[:middle]), union(rows[middle:])]
        return union(parts)
    if isinstance(domain, sp.FiniteSet):
        return ['set', *(endpoint(value) for value in domain)]
    return ['interval', not domain.left_open, not domain.right_open,
            endpoint(domain.start), endpoint(domain.end)]


def prepare_fraction_range(context):
    if not admitted(context, FRACTION_METHOD):
        raise CapabilityGap('range.fraction_input_required')
    if context['range_goal']['rational'].get('linear_remainder'):
        from .fraction_range import prepare_linear_fraction
        return prepare_linear_fraction(context)
    description = deepcopy(context['range_goal'])
    source, x, domain = inputs(description)
    denominator = range_expression(description['inner_ast'], x)
    shift, scale = sp.Rational(description['shift']), sp.Rational(description['scale'])
    if sp.cancel(source - shift - scale/denominator) != 0:
        raise LocalCheckFailed('range.fraction_identity_failed')
    if (sp.solveset(denominator, x, domain=sp.S.Reals) & domain) is not sp.S.EmptySet:
        raise LocalCheckFailed('range.fraction_pole_in_domain')
    mapping = {'function': denominator, 'variable': x, 'domain': domain,
               'shift': shift, 'scale': scale}
    child = {**description, 'function_name': 'Q', 'expression_ast': description['inner_ast'],
             'expression_latex': sp.latex(denominator), 'radical': False, 'scale': '1', 'shift': '0',
             'declared_domain_ast': ['real'], 'declared_domain_source_ref': '',
             'input_domain_ast': domain_ast(domain), 'input_domain_source_ref': '', 'restriction_facts': []}
    child.pop('rational')
    inputs(child)
    description['fraction_mapping'] = mapping
    return result({'description': description, 'function': source, 'variable': x, 'domain': domain,
                   'mapping': mapping, 'linear_mode': False,
                   'child_context': {**deepcopy(context), 'range_goal': child, 'range_subproblem': True}},
                  ['fraction_range_identity'],
                  [{'kind': 'division_identity_on_original_domain', 'passed': True, 'domain': domain,
                    'original_divisors': description['rational']['denominators']}])


def return_fraction_range(context, mapping, image):
    if context['range_goal']['rational'].get('linear_remainder'):
        from .fraction_range import return_linear_fraction
        return return_linear_fraction(context, mapping, image)
    from .capabilities.reciprocal import reciprocal_of_range
    checked = prepare_fraction_range(context)['outputs']['mapping']
    if mapping != checked:
        raise LocalCheckFailed('range.fraction_mapping_mismatch')
    expected, _ = monotone_cover(mapping['function'], mapping['variable'], mapping['domain'])
    if image != expected or image.contains(0) is not sp.false:
        raise LocalCheckFailed('range.fraction_child_image_mismatch')
    parts = [reciprocal_of_range(_bounds(part)) for part in components(image)]
    reciprocal = sp.Union(*(part['outputs']['range']['set'] for part in parts))
    scale, shift = mapping['scale'], mapping['shift']
    output = (sp.FiniteSet(shift) if scale == 0 else
              _map_image(reciprocal, lambda value: shift + scale*value, increasing=scale > 0))
    return result({'description': prepare_fraction_range(context)['outputs']['description'],
                   'denominator_range': _bounds(image), 'reciprocal_range': _bounds(reciprocal),
                   'range': _bounds(output), 'feasible_set': output},
                  ['reciprocal_of_range', 'fraction_range_transport'],
                  [check for part in parts for check in part['checks']] +
                  [{'kind': 'fraction_complete_output_transport', 'passed': True,
                    'denominator_image': image, 'reciprocal_image': reciprocal, 'image': output}])


def needs_value_comparison(expression, variable, domain):
    # Bounds determine the image of a continuous quadratic on one interval.
    # Disconnected inputs need the complete image, including interior holes.
    return sp.degree(expression, variable) == 2 and isinstance(domain, sp.Interval)


def prepare_function_range(context):
    if not admitted(context):
        raise CapabilityGap('range.input_class_unavailable')
    description = deepcopy(context['range_goal'])
    expression, variable, domain = inputs(description)
    degree = int(max(0, sp.degree(expression, variable)))
    return result({'description': description, 'function': expression, 'variable': variable,
                   'domain': domain, 'degree': degree, 'quadratic': degree == 2,
                   'compare_values': needs_value_comparison(expression, variable, domain),
                   'radical': description['radical'],
                   'rescale': description['radical'] and (description['scale'], description['shift']) != ('1', '0'),
                   'natural_domain': natural_domain(description)},
                  ['radical_range_domain' if description['radical'] else 'function_range_domain'],
                  [{'kind': 'original_function_domain', 'passed': True,
                    'natural_domain': natural_domain(description),
                    'declared_domain': range_domain(description['declared_domain_ast']),
                    'effective_domain': domain}])


def prepare_range_substitution(context):
    if not admitted(context, SUBSTITUTION_METHOD):
        raise CapabilityGap('range.substitution_input_required')
    return _prepare_range_substitution(context)


def _prepare_range_substitution(context):
    description = deepcopy(context['range_goal'])
    source, x, domain = inputs(description)
    spec = description['substitution']
    kind = spec['kind']
    t = sp.Symbol('t' if x.name != 't' else 'u', real=True)
    a, b = sp.Rational(spec['slope']), sp.Rational(spec['intercept'])
    argument = range_expression(spec['argument_ast'], x)
    polynomial = sum((sp.Rational(c)*t**i for i, c in enumerate(spec['coefficients'])), sp.S.Zero)
    branches = []
    if kind == 'constant':
        forward, preimages, new_domain = x, [t], domain
        branches = [{'original_domain': domain, 'image': domain}]
    else:
        argument_image = polynomial_image(argument, x, domain)['outputs']['feasible_set']
        if kind == 'sqrt':
            forward, preimages = sp.sqrt(argument), [(t**2-b)/a]
            new_domain = _map_image(argument_image, sp.sqrt)
            branches = [{'original_domain': domain, 'image': new_domain}]
        elif kind == 'abs':
            forward, preimages = sp.Abs(argument), [(t-b)/a, (-t-b)/a]
            for sign, region in ((1, sp.Interval(0, sp.oo)), (-1, sp.Interval(-sp.oo, 0))):
                segment = argument_image & region
                if segment is not sp.S.EmptySet:
                    branches.append({'argument_domain': segment,
                                     'image': _map_image(segment, lambda v, sign=sign: sign*v, increasing=sign > 0)})
            new_domain = sp.Union(*(row['image'] for row in branches))
        else:
            forward, preimages, new_domain = argument, [(t-b)/a], argument_image
            branches = [{'original_domain': domain, 'image': new_domain}]
    original_relation = range_expression(description['expression_ast'], x) if kind == 'affine' else source
    identity = sp.simplify(polynomial.subs(t, forward) - original_relation) == 0
    if not identity or new_domain is sp.S.EmptySet:
        raise LocalCheckFailed('range.substitution_identity_failed')
    mapping = {'kind': kind, 'original_variable': x, 'original_domain': domain,
               'forward': forward, 'variable': t, 'domain': new_domain,
               'function': polynomial, 'preimages': preimages, 'coverage': branches}
    child_description = {**description, 'variable': t.name,
                         'function_name': description['function_name'] if kind == 'affine' else 'h',
                         'function_ref': description['function_ref'],
                         'expression_ast': coefficients_ast(spec['coefficients']),
                         'inner_ast': coefficients_ast(spec['coefficients']),
                         'expression_latex': sp.latex(polynomial),
                         'declared_domain_ast': ['real'], 'declared_domain_source_ref': '',
                         'input_domain_source_ref': '', 'restriction_facts': [],
                         'radical': False, 'scale': '1', 'shift': '0'}
    # Preserve the complete exact set when a punctured input has several images.
    child_description['input_domain_ast'] = domain_ast(new_domain)
    for field in ('substitution', 'relation_input_ast'):
        child_description.pop(field, None)
    # Admission must cover the child domain as well: e.g. a supported surd
    # endpoint can become an unsupported nested radical after substitution.
    inputs(child_description)
    child_context = {**deepcopy(context), 'range_goal': child_description, 'range_subproblem': True}
    description['mapping'] = mapping
    return result({'description': description, 'function': source, 'variable': x,
                   'domain': domain, 'mapping': mapping, 'child_context': child_context},
                  ['function_range_substitution'],
                  [{'kind': 'substitution_identity', 'passed': identity},
                   {'kind': 'substitution_complete_input_image', 'passed': True,
                    'original_domain': domain, 'image': new_domain, 'cover': branches,
                    'inverse_branches': preimages}])


def return_range_substitution(context, mapping, image):
    checked = prepare_range_substitution(context)['outputs']['mapping']
    if mapping != checked:
        raise LocalCheckFailed('range.substitution_mapping_mismatch')
    expected, _ = monotone_cover(mapping['function'], mapping['variable'], mapping['domain'])
    if image != expected:
        raise LocalCheckFailed('range.substitution_child_image_mismatch')
    return result({'range': _bounds(image), 'feasible_set': image}, ['function_range_substitution'],
                  [{'kind': 'substitution_complete_output_transport', 'passed': True,
                    'image': image, 'input_cover': mapping['coverage']}])


def polynomial_image(expression, variable, domain):
    if isinstance(domain, sp.Union):
        parts = [polynomial_image(expression, variable, part) for part in components(domain)]
        image = sp.Union(*(part['outputs']['feasible_set'] for part in parts))
        return result({'range': _bounds(image), 'feasible_set': image,
                       'endpoint_values': [row for part in parts for row in part['outputs']['endpoint_values']],
                       'critical_points': [row for part in parts for row in part['outputs']['critical_points']]},
                      ['interval_extrema'], [check for part in parts for check in part['checks']])
    if isinstance(domain, sp.FiniteSet) and len(domain) == 1:
        point = next(iter(domain))
        value = expression.subs(variable, point)
        bounds = {'inf': value, 'sup': value, 'inf_attained': True,
                  'sup_attained': True, 'set': sp.FiniteSet(value)}
        computed = result({'range': bounds, 'endpoint_values': [
            {'point': point, 'value': value, 'attained': True}], 'critical_points': []},
            ['interval_extrema'], [{'kind': 'singleton_image', 'passed': True}])
    else:
        computed = quadratic_interval_range(expression, variable, domain)
    expected, _ = monotone_cover(expression, variable, domain)
    if computed['outputs']['range']['set'] != expected:
        raise LocalCheckFailed('range.local_image_mismatch')
    computed['outputs']['feasible_set'] = expected
    return computed


def _bounds(image):
    low, high = image.inf, image.sup
    return {'inf': low, 'sup': high, 'inf_attained': image.contains(low) is sp.true,
            'sup_attained': image.contains(high) is sp.true, 'set': image}


def _map_image(image, transform, *, increasing=True):
    if isinstance(image, sp.Union):
        return sp.Union(*(_map_image(part, transform, increasing=increasing) for part in image.args))
    if isinstance(image, sp.FiniteSet):
        return sp.FiniteSet(*(sp.simplify(transform(point)) for point in image))
    left, right = sp.simplify(transform(image.start)), sp.simplify(transform(image.end))
    return (sp.Interval(left, right, left_open=image.left_open, right_open=image.right_open) if increasing else
            sp.Interval(right, left, left_open=image.right_open, right_open=image.left_open))


def transform_function_range(description, image):
    if not description['radical']:
        return result({'inner_range': _bounds(image), 'root_range': _bounds(image),
                       'range': _bounds(image), 'feasible_set': image}, [],
                      [{'kind': 'original_polynomial_image', 'passed': True}])
    if image is sp.S.EmptySet or image.is_subset(sp.Interval(0, sp.oo)) is not True:
        raise LocalCheckFailed('range.nonnegative_image_required')
    root = _map_image(image, sp.sqrt)
    scale, shift = sp.Rational(description['scale']), sp.Rational(description['shift'])
    output = (sp.FiniteSet(shift) if scale == 0 else
              _map_image(root, lambda value: scale*value+shift, increasing=scale > 0))
    return result({'inner_range': _bounds(image), 'root_range': _bounds(root),
                   'range': _bounds(output), 'feasible_set': output},
                  ['function_range_transform'],
                  [{'kind': 'square_root_bijection', 'passed': True, 'source': image, 'image': root},
                   {'kind': 'affine_image', 'passed': True, 'scale': scale, 'shift': shift,
                    'source': root, 'image': output}])


def _limit(expression, variable, endpoint):
    if endpoint not in (-sp.oo, sp.oo):
        return expression.subs(variable, endpoint)
    return sp.limit(expression, variable, endpoint)


def monotone_cover(expression, variable, domain):
    """Partition at the derivative's zero and map each whole monotone piece.

    This verifier does not use the solver's extrema candidates/attainment flags.
    Every piece is continuous and monotone, so its endpoint image is both an
    upper/lower containment bound and a proof that every intermediate value is
    attained. Union retains a boundary if any other legal preimage attains it.
    """
    if isinstance(domain, sp.Union):
        parts = [monotone_cover(expression, variable, part) for part in domain.args]
        return sp.Union(*(part[0] for part in parts)), [row for part in parts for row in part[1]]
    if isinstance(domain, sp.FiniteSet):
        point = next(iter(domain))
        image = sp.FiniteSet(expression.subs(variable, point))
        return image, [{'domain': domain, 'image': image, 'reason': 'singleton'}]
    derivative = sp.diff(expression, variable)
    if derivative == 0:
        image = sp.FiniteSet(expression)
        return image, [{'domain': domain, 'image': image, 'reason': 'constant_on_nonempty_domain'}]
    cuts = [domain.start, domain.end]
    for point in sp.solve(derivative, variable):
        if point.is_real is True and domain.start < point < domain.end:
            cuts.append(point)
    cuts = sorted(set(cuts))
    pieces, images = [], []
    for left, right in pairwise(cuts):
        a, b = _limit(expression, variable, left), _limit(expression, variable, right)
        take_left = domain.contains(left) is sp.true and left not in (-sp.oo, sp.oo)
        take_right = domain.contains(right) is sp.true and right not in (-sp.oo, sp.oo)
        region = sp.Interval(left, right, left_open=not take_left, right_open=not take_right)
        image = (sp.Interval(a, b, left_open=not take_left, right_open=not take_right) if a < b else
                 sp.Interval(b, a, left_open=not take_right, right_open=not take_left))
        images.append(image)
        pieces.append({'domain': region, 'image': image, 'reason': 'continuous_strictly_monotone',
                       'direction': 'increasing' if a < b else 'decreasing'})
    return sp.Union(*images), pieces


def process_context(context, feasible_set):
    if context['goal']['kind'] == 'select_range_domain':
        if not admitted(context):
            raise CapabilityGap('range_task.unsupported_domain_options')
    else:
        inputs(context['range_goal'])
    # Definition, declared domain and extra restrictions have all been read by
    # the structural contract. The result is an OUTPUT set, never intersect it
    # with an input constraint here.
    return feasible_set, [{'source_ref': row['source_ref'], 'status': 'function_image_source'}
                          for row in context['entries']]


def original_image(expression, variable, domain):
    """Analyze original continuous pieces; a second endpoint can attain an open-boundary value."""
    from sympy.calculus.util import function_range
    pieces = []
    for part in components(domain):
        if isinstance(part, sp.FiniteSet):
            image = sp.FiniteSet(*(expression.subs(variable, point) for point in part))
        else:
            image = function_range(expression, variable, part)
            # Critical-value radicals can be algebraically equal but expressed
            # differently from the equation solver's quadratic roots.
            if isinstance(image, sp.Interval):
                image = sp.Interval(sp.simplify(image.start), sp.simplify(image.end),
                                    left_open=image.left_open, right_open=image.right_open)
            # SymPy may mark a shared endpoint output open when only the first
            # preimage is excluded. Include every legal closed endpoint directly.
            endpoints = [p for p in (part.start, part.end) if p.is_finite and p in part]
            image |= sp.FiniteSet(*(sp.simplify(expression.subs(variable, p)) for p in endpoints))
        pieces.append({'domain': part, 'image': image, 'reason': 'original_function_complete_image'})
    return sp.Union(*(row['image'] for row in pieces)), pieces


def independent_verify(candidate, target_ref, context, proposed):
    description = inspect_range_target(candidate, target_ref)
    if description != context.get('range_goal'):
        return {'status': 'math_failed', 'proof': {},
                'diagnostics': [{'code': 'range.source_context_mismatch'}]}
    from .verification import check_context, collect_original
    check_context(collect_original(candidate, target_ref), context)
    expression, variable, domain = inputs(description)
    if isinstance(domain, sp.FiniteSet) or description.get('rational'):
        expected, pieces = original_image(expression, variable, domain)
    elif description.get('substitution'):
        spec = description['substitution']
        if spec['kind'] == 'affine':
            # The original relation holds on all reals and its input map is
            # onto: analyze its original RHS, independently of the new formula.
            original = range_expression(description['expression_ast'], variable)
            expected, pieces = monotone_cover(original, variable, sp.S.Reals)
        elif spec['kind'] == 'abs':
            argument = range_expression(spec['argument_ast'], variable)
            images, pieces = [], []
            for sign in (1, -1):
                roots = solve_quadratic(sign*argument, variable)['outputs']
                region = domain & quadratic_sign_pattern(sign*argument, variable, **roots, strict=False)['outputs']['solution']
                if region is sp.S.EmptySet:
                    continue
                original = expression.xreplace({sp.Abs(argument): sign*argument})
                image, rows = monotone_cover(sp.expand(original), variable, region)
                images.append(image)
                pieces.extend(rows)
            expected = sp.Union(*images)
        else:
            expected, pieces = original_image(expression, variable, domain)
    else:
        expected, pieces = monotone_cover(expression, variable, domain)
    if description['radical']:
        # Independent analysis of the original function on each exact input
        # component, not the solver's transformed endpoints or flags.
        target = sp.Rational(description['shift']) + sp.Rational(description['scale'])*sp.sqrt(expression)
        expected, pieces = original_image(target, variable, domain)
    passed = proposed == expected
    return {'status': 'verified' if passed else 'math_failed',
            'proof': {'kind': 'complete_function_image', 'passed': passed,
                      'effective_domain': math_value(domain), 'expected': math_value(expected),
                      'containment': passed, 'attainability': passed,
                      'cover': [{**row, 'domain': math_value(row['domain']), 'image': math_value(row['image'])}
                                for row in pieces]},
            'diagnostics': [] if passed else [{'code': 'range.image_mismatch'}]}


def image_endpoints(candidate, target_ref, image):
    desc = inspect_range_target(candidate, target_ref)
    expression, variable, domain = inputs(desc)
    if desc['radical']:
        expression = sp.Rational(desc['shift']) + sp.Rational(desc['scale'])*sp.sqrt(expression)
    rows = []
    for point in sorted(image.boundary):
        if sp.diff(expression, variable) == 0:
            part = components(domain)[0]
            witnesses = [next(iter(part)) if isinstance(part, sp.FiniteSet) else
                         (part.start + part.end)/2 if part.start.is_finite and part.end.is_finite else
                         part.start+1 if part.start.is_finite else part.end-1 if part.end.is_finite else sp.S.Zero]
            witnesses = [v for v in witnesses if expression == point]
        else:
            witnesses = [v for v in sp.solve(expression-point, variable)
                         if v.is_real is True and domain.contains(v) is sp.true]
        included = image.contains(point) is sp.true
        rows.append({'point': math_value(point), 'included': included, 'holds': bool(witnesses),
                     'passed': included == bool(witnesses),
                     'evidence': {'legal_preimages': [math_value(v) for v in witnesses]}})
    return {'status': 'passed' if all(row['passed'] for row in rows) else 'failed', 'points': rows}
