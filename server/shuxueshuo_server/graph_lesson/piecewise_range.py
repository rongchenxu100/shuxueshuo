"""Exact images of source-bound polynomial pieces, with independent verification."""

from copy import deepcopy

import sympy as sp

from ..problem_understanding.notation_parser import NotationError
from .piecewise_equation import _polynomial
from .piecewise_evaluation import branches
from .range_syntax import expression_family, range_domain

METHOD = 'method-piecewise-range'


def piecewise_latex(ast, variable):
    from .stage_one.function_domain import expression_latex

    def condition(node):
        if node[0] == 'and':
            return r',\quad '.join(condition(child) for child in node[1:])
        op = {'<=': r'\le ', '>=': r'\ge '}.get(node[0], node[0])
        return expression_latex(node[1], variable) + op + expression_latex(node[2], variable)

    return (r'\begin{cases}' + r'\\'.join(expression_latex(row['expression_ast'], variable) + '&' +
            condition(row['condition_ast']) for row in branches(ast)) + r'\end{cases}')


def inputs(description):
    """Keep each original predicate, intersect restrictions, and retain empty pieces."""
    x = sp.Symbol(description['variable'], real=True)
    rows = [{**row, 'index': index, 'expression': _polynomial(row['expression_ast'], x).as_expr()}
            for index, row in enumerate(branches(description['expression_ast']), 1)]
    natural = sp.Union(*(row['domain'] for row in rows))
    declared = range_domain(description['declared_domain_ast'])
    if description['declared_domain_source_ref'] and declared.is_subset(natural) is not True:
        raise NotationError('piecewise_range.declared_domain_conflict')
    domain = natural & declared & range_domain(description['input_domain_ast'])
    for restriction in description['restriction_facts']:
        domain &= range_domain(restriction['domain_ast'])
    if domain is sp.S.EmptySet:
        raise NotationError('piecewise_range.empty_input')
    from .stage_three.function_range import components
    for row in rows:
        row['source_domain'] = row['domain']
        row['domain'] &= domain
        parts = components(row['domain']) if row['domain'] is not sp.S.EmptySet else []
        if len(parts) > 16 or any(isinstance(p, sp.FiniteSet) and len(p) > 1 for p in parts):
            raise NotationError('piecewise_range.input_budget')
    return x, domain, rows


def prepare_piecewise_range(context):
    from .stage_three.capabilities import result
    desc = deepcopy(context['range_goal'])
    x, domain, rows = inputs(desc)
    cases = []
    for row in rows:
        if row['domain'] is sp.S.EmptySet:
            continue
        child = {**desc, **expression_family(row['expression_ast']),
                 'expression_ast': row['expression_ast'], 'expression_latex': sp.latex(row['expression']),
                 'piecewise_index': row['index']}
        child.pop('piecewise', None)
        cases.append({'id': f'piece-{row["index"]}', 'condition': row['domain'].as_relational(x),
                      'domain': row['domain'], 'description': child, 'branch': row, 'variable': x})
    return result({'description': desc, 'branch_cases': cases}, ['piecewise_range_union'],
                  [{'kind': 'effective_piecewise_domains', 'passed': True, 'domain': domain,
                    'pieces': rows}])


def bind_piecewise_range(branch_case):
    from .stage_three.capabilities import result
    row, x = branch_case['branch'], branch_case['variable']
    quadratic = sp.degree(row['expression'], x) == 2
    return result({'description': branch_case['description'], 'branch': row, 'variable': x,
                   'function': row['expression'], 'domain': row['domain'], 'quadratic': quadratic},
                  ['piecewise_range_union'], [{'kind': 'current_piece', 'passed': True, 'index': row['index']}])


def merge_piecewise_range(context, branch_results):
    from .stage_three.capabilities import LocalCheckFailed, result
    from .stage_three.function_range import monotone_cover
    x, _, rows = inputs(context['range_goal'])
    active = [row for row in rows if row['domain'] is not sp.S.EmptySet]
    if len(branch_results) != len(active):
        raise LocalCheckFailed('piecewise_range.missing_piece')
    outputs = []
    for original, item in zip(active, branch_results, strict=True):
        output = item.get('outputs', item)
        if 'outputs' in item and (item['domain'] != original['domain'] or
                                  item['condition'] != original['domain'].as_relational(x)):
            raise LocalCheckFailed('piecewise_range.case_domain_mismatch')
        if output['branch'] != original or output['image'] != monotone_cover(original['expression'], x, original['domain'])[0]:
            raise LocalCheckFailed('piecewise_range.piece_image_mismatch')
        outputs.append(output)
    image = sp.Union(*(row['image'] for row in outputs))
    return result({'feasible_set': image, 'branch_results': outputs}, ['piecewise_range_union'],
                  [{'kind': 'union_of_output_sets', 'passed': True, 'image': image,
                    'pieces': branch_results, 'empty_pieces': [r for r in rows if r['domain'] is sp.S.EmptySet]}])


def independent_verify(description, proposed):
    from .stage_three.function_range import original_image
    from .stage_three.math_values import math_value
    x, domain, rows = inputs(description)
    cover, images = [], []
    for row in rows:
        image = (sp.S.EmptySet if row['domain'] is sp.S.EmptySet else
                 original_image(row['expression'], x, row['domain'])[0])
        cover.append({'index': row['index'], 'domain': math_value(row['domain']), 'image': math_value(image)})
        images.append(image)
    expected = sp.Union(*images)
    passed = proposed == expected
    return {'status': 'verified' if passed else 'math_failed',
            'proof': {'kind': 'complete_piecewise_image', 'passed': passed,
                      'effective_domain': math_value(domain), 'expected': math_value(expected),
                      'containment': passed, 'attainability': passed, 'cover': cover},
            'diagnostics': [] if passed else [{'code': 'piecewise_range.image_mismatch'}]}


def endpoint_witnesses(description, image):
    from .stage_three.function_range import components
    from .stage_three.math_values import math_value
    x, _, pieces = inputs(description)
    checks = []
    for point in sorted(image.boundary):
        witnesses = []
        for row in pieces:
            if row['domain'] is sp.S.EmptySet:
                continue
            if not row['expression'].has(x):
                part = components(row['domain'])[0]
                possible = [next(iter(part)) if isinstance(part, sp.FiniteSet) else
                            (part.start+part.end)/2 if part.start.is_finite and part.end.is_finite else
                            part.start+1 if part.start.is_finite else part.end-1 if part.end.is_finite else sp.S.Zero]
                possible = possible if row['expression'] == point else []
            else:
                possible = sp.solve(row['expression']-point, x)
            witnesses.extend({'branch': row['index'], 'input': math_value(v)} for v in possible
                             if v.is_real is True and row['domain'].contains(v) is sp.true)
        included = image.contains(point) is sp.true
        checks.append({'point': math_value(point), 'included': included, 'holds': bool(witnesses),
                       'passed': included == bool(witnesses), 'evidence': {'legal_preimages': witnesses}})
    return {'status': 'passed' if all(row['passed'] for row in checks) else 'failed', 'points': checks}
