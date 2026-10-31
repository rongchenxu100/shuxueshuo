"""Complete images of quadratic rational functions via legal real preimages."""

from copy import deepcopy

import sympy as sp

from ..range_syntax import range_expression
from .capabilities import (
    CapabilityGap,
    LocalCheckFailed,
    quadratic_sign_pattern,
    result,
    solve_quadratic,
)
from .function_range import EQUATION_METHOD, _bounds, admitted, inputs


def prepare_equation_range(context):
    if not admitted(context, EQUATION_METHOD):
        raise CapabilityGap('range.real_root_input_required')
    description = deepcopy(context['range_goal'])
    function, x, domain = inputs(description)
    y = sp.Symbol('y' if x.name != 'y' else 'v', real=True)
    denominator = range_expression(description['rational']['equation_denominator_ast'], x)
    numerator = sp.cancel(function*denominator)
    if (domain != sp.S.Reals or sp.degree(denominator, x) != 2 or
            sp.discriminant(denominator, x) >= 0 or not numerator.is_polynomial(x) or
            sp.degree(numerator, x) > 2):
        raise LocalCheckFailed('range.real_root_equivalence_failed')
    equation = sp.Poly(sp.expand(y*denominator-numerator), x)
    a, b, c = (equation.nth(i) for i in (2, 1, 0))
    special = sp.solve(a, y)
    if len(special) != 1 or special[0].is_real is not True:
        raise LocalCheckFailed('range.real_root_degree_partition_failed')
    description['equation_mapping'] = {
        'output_variable': y, 'numerator': numerator, 'denominator': denominator,
        'equation': equation.as_expr(), 'a': a, 'b': b, 'c': c,
        'special_value': special[0], 'discriminant': sp.expand(b*b-4*a*c),
    }
    return result({'description': description, 'function': function, 'variable': x, 'domain': domain},
                  ['range_real_preimage_equivalence'],
                  [{'kind': 'real_roots_are_legal_original_inputs', 'passed': True,
                    'domain': domain, 'denominator_discriminant': sp.discriminant(denominator, x),
                    'original_divisors': description['rational']['denominators']}])


def solve_equation_range(context):
    prepared = prepare_equation_range(context)
    output = prepared['outputs']
    mapping = output['description']['equation_mapping']
    y, special = mapping['output_variable'], mapping['special_value']
    b, c = (sp.simplify(mapping[key].subs(y, special)) for key in ('b', 'c'))
    kind = 'linear' if b != 0 else 'identity' if c == 0 else 'inconsistent'
    degenerate = sp.FiniteSet(special) if kind != 'inconsistent' else sp.S.EmptySet
    witness = -c/b if kind == 'linear' else sp.S.Zero if kind == 'identity' else None
    if witness is not None and sp.simplify(output['function'].subs(output['variable'], witness)-special) != 0:
        raise LocalCheckFailed('range.degenerate_preimage_failed')
    roots = solve_quadratic(mapping['discriminant'], y)
    signs = quadratic_sign_pattern(mapping['discriminant'], y, **roots['outputs'], strict=False)
    quadratic = signs['outputs']['solution'] - sp.FiniteSet(special)
    image = quadratic | degenerate
    mapping.update({'degenerate_kind': kind, 'degenerate_b': b, 'degenerate_c': c,
                    'degenerate_witness': witness, 'degenerate_image': degenerate,
                    'discriminant_image': signs['outputs']['solution'], 'quadratic_image': quadratic})
    return result({**output, 'range': _bounds(image), 'feasible_set': image},
                  ['range_real_preimage_equivalence', *roots['operations'], *signs['operations'],
                   'range_real_preimage_partition'],
                  [*prepared['checks'], *roots['checks'], *signs['checks'],
                   {'kind': 'exhaustive_disjoint_degree_partition', 'passed': True,
                    'quadratic_outputs': quadratic, 'degenerate_outputs': degenerate,
                    'degenerate_kind': kind, 'witness': witness}])
