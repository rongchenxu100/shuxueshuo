"""Linear remainders: exact input transport, reciprocal-sum images and zero recovery."""

from copy import deepcopy

import sympy as sp

from .capabilities import LocalCheckFailed, result
from .capabilities.ranges import quadratic_interval_range, reciprocal_range
from .capabilities.reciprocal import reciprocal_of_range


def prepare_linear_fraction(context):
    from .function_range import _map_image, inputs

    desc = deepcopy(context['range_goal'])
    source, x, domain = inputs(desc)
    numerator, denominator = sp.fraction(source)
    shift, remainder = sp.div(numerator, denominator, x)
    poly = sp.Poly(remainder, x)
    if shift.has(x) or poly.degree() != 1:
        raise LocalCheckFailed('range.linear_fraction_required')
    scale, offset = poly.nth(1), sp.cancel(poly.nth(0) / poly.nth(1))
    t = x if offset == 0 else sp.Symbol('t' if x.name != 't' else 'u', real=True)
    moved = _map_image(domain, lambda value: value + offset)
    nonzero = moved - sp.FiniteSet(0)
    transformed_q = sp.Poly(sp.expand(denominator.subs(x, t-offset)), t)
    a, b, c = (transformed_q.nth(i) for i in (2, 1, 0))
    core = a*t + c/t if c != 0 else a*t
    pole = -offset
    zero_allowed = domain.contains(pole) is sp.true
    zero_image = sp.FiniteSet(shift) if zero_allowed else sp.S.EmptySet
    identity = sp.cancel(source - shift - scale / (core+b).subs(t, x+offset)) == 0
    if not identity or (zero_allowed and sp.simplify(source.subs(x, pole)) != shift):
        raise LocalCheckFailed('range.linear_fraction_identity_failed')
    mapping = {'linear': True, 'shift': shift, 'scale': scale, 'remainder': remainder,
               'denominator': denominator, 'variable': t, 'function': core,
               'offset': offset, 'denominator_shift': b, 'transformed_domain': moved,
               'domain': nonzero, 'original_domain': domain, 'original_variable': x,
               'zero_input': pole, 'zero_allowed': zero_allowed, 'zero_image': zero_image,
               'needs_substitution': bool(offset != 0), 'has_nonzero': nonzero is not sp.S.EmptySet}
    desc['fraction_mapping'] = mapping
    return result({'description': desc, 'function': source, 'variable': x, 'domain': domain,
                   'mapping': mapping, 'child_context': None, 'linear_mode': True},
                  ['fraction_range_identity', 'function_range_substitution'],
                  [{'kind': 'linear_remainder_identity', 'passed': identity},
                   {'kind': 'bijective_affine_input_transport', 'passed': True,
                    'original': domain, 'image': moved, 'forward': x+offset, 'inverse': t-offset},
                   {'kind': 'complete_zero_partition', 'passed': True,
                    'zero_input': pole, 'zero_allowed': zero_allowed, 'nonzero_domain': nonzero}])


def solve_fraction_intermediate(context, mapping):
    from .function_range import components

    prepared = prepare_linear_fraction(context)['outputs']
    if mapping != prepared['mapping']:
        raise LocalCheckFailed('range.fraction_mapping_mismatch')
    t, core, domain = (mapping[key] for key in ('variable', 'function', 'domain'))
    rows, checks = [], []
    # Each component stays on one side of t=0 and retains every original hole.
    for part in ([] if domain is sp.S.EmptySet else components(domain)):
        if isinstance(part, sp.FiniteSet):
            image = sp.FiniteSet(*(sp.simplify(core.subs(t, p)) for p in part))
            values = {'range': {'set': image}, 'critical_points': [], 'endpoint_values': [], 'shape': 'finite'}
        else:
            computed = (quadratic_interval_range(core, t, part) if core.is_polynomial(t)
                        else reciprocal_range(core, t, part))
            values = computed['outputs']
            checks.extend(computed['checks'])
        rows.append({'domain': part, **values})
    image = sp.Union(*(row['range']['set'] for row in rows))
    desc = prepared['description']
    desc['fraction_mapping'] = {**mapping, 'pieces': rows, 'core_image': image}
    return result({'image': image, 'description': desc},
                  ['reciprocal_extrema'], checks + [
                      {'kind': 'complete_reciprocal_sum_partition', 'passed': True,
                       'domain': domain, 'image': image, 'pieces': rows}])


def return_linear_fraction(context, mapping, image):
    from .function_range import _bounds, _map_image, components

    solved = solve_fraction_intermediate(context, mapping)['outputs']
    if image != solved['image']:
        raise LocalCheckFailed('range.fraction_child_image_mismatch')
    denominator_image = (sp.S.EmptySet if image is sp.S.EmptySet else
                         _map_image(image, lambda value: value + mapping['denominator_shift']))
    if denominator_image.contains(0) is not sp.false:
        raise LocalCheckFailed('range.fraction_pole_in_domain')
    parts = ([] if denominator_image is sp.S.EmptySet else
             [reciprocal_of_range(_bounds(part)) for part in components(denominator_image)])
    reciprocal = sp.Union(*(part['outputs']['range']['set'] for part in parts))
    nonzero_image = (sp.S.EmptySet if reciprocal is sp.S.EmptySet else
                     _map_image(reciprocal, lambda value: mapping['shift'] + mapping['scale']*value,
                                increasing=mapping['scale'] > 0))
    output = nonzero_image | mapping['zero_image']
    desc = solved['description']
    desc['fraction_mapping'].update(denominator_image=denominator_image,
                                    reciprocal_image=reciprocal, nonzero_image=nonzero_image,
                                    image=output)
    return result({'description': desc, 'range': {'set': output}, 'feasible_set': output,
                   'denominator_range': {'set': denominator_image}, 'reciprocal_range': {'set': reciprocal}},
                  ['reciprocal_of_range', 'fraction_range_transport'],
                  [check for part in parts for check in part['checks']] + [
                      {'kind': 'fraction_complete_output_transport', 'passed': True,
                       'nonzero_image': nonzero_image, 'zero_image': mapping['zero_image'], 'image': output}])
