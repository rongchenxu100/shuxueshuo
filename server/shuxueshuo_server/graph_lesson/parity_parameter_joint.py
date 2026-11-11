"""FP-T2 R3: two real parameters, fixed domain, joint affine conditions."""
from copy import deepcopy

import sympy as sp

from ..problem_understanding.notation_parser import definition
from . import function_cells as fixed
from . import linear_parameter_family as linear
from . import parity_parameter_math as base

VERSION = 'parity-parameter/r3-joint-v1'
LIMITS = {**base.LIMITS, **linear.LIMITS, 'input_degree': 4, 'intervals': 4, 'points': 8}


def symbols(desc):
    parameters = [sp.Symbol(v, real=True) for v in desc['parameters']]
    x = sp.Symbol(desc['variable'], real=True)
    if x in parameters:
        name = '_function_input'
        while sp.Symbol(name, real=True) in parameters:
            name += '_'
        x = sp.Symbol(name, real=True)
    return x, parameters


def polynomial(ast, x, parameters, refs):
    if ast[0] == 'number':
        return fixed.exact_point(sp.Rational(ast[1]))
    if ast == ['bound', 'function_argument']:
        return x
    if ast[0] == 'ref' and ast[1] in refs:
        return parameters[refs.index(ast[1])]
    read = lambda v: polynomial(v, x, parameters, refs)
    if ast[0] == 'neg':
        return -read(ast[1])
    if ast[0] not in ('+', '-', '*', '/', '^'):
        raise ValueError('parity_joint.polynomial_required')
    a, b = read(ast[1]), read(ast[2])
    if ast[0] == '/' and (not isinstance(b, sp.Rational) or b == 0):
        raise ValueError('parity_joint.constant_denominator_required')
    if ast[0] == '^' and (not b.is_Integer or not 1 <= b <= LIMITS['input_degree']):
        raise ValueError('parity_joint.positive_bounded_power_required')
    result = {'+': lambda: a+b, '-': lambda: a-b, '*': lambda: a*b,
              '/': lambda: a/b, '^': lambda: a**b}[ast[0]]()
    poly = sp.Poly(sp.expand(result), x)
    if poly.degree() > LIMITS['input_degree']:
        raise ValueError('parity_joint.input_degree_budget')
    for coefficient in poly.all_coeffs():
        linear.vector(coefficient, parameters)
    return poly.as_expr()


def _fixed_domain(ast):
    if ast == ['empty_set']:
        return sp.S.EmptySet
    counts = {'intervals': 0, 'points': 0}
    valid = True
    for node in fixed.walk(ast):
        if node[0] == 'interval':
            counts['intervals'] += 1
            a, b = map(fixed.constant, node[3:])
            valid = valid and bool(a < b)
        elif node[0] == 'set':
            counts['points'] += len(node)-1
    if any(counts[k] > LIMITS[k] for k in counts):
        raise ValueError('parity_joint.domain_budget')
    return fixed.input_set(ast) if valid else sp.S.EmptySet


def populate(desc, target, entries, facts, definitions, function_ref):
    if len(definitions) != 1:
        raise ValueError('parity_joint.complete_formula_required')
    fn, = definitions
    raw = definition(fn['expression'])
    refs = [v[1] for v in target[1:]]
    names = [r.rsplit(':', 1)[-1] for r in refs]
    if len(set(names)) != 2:
        raise ValueError('parity_joint.distinct_parameters_required')
    desc.update(analysis_mode='joint', structure_version=VERSION, parameter_refs=refs,
                parameters=names, function_ref=function_ref, function=function_ref.rsplit(':', 1)[-1],
                expression_ast=deepcopy(fn['ast'][2]), expression=raw[3], variable=raw[2],
                variable_ref=fn['source_ref']+'#function_argument', function_source_ref=fn['source_ref'],
                domain_asts=[], domain_source_refs=[], constraints=[], degrees=[], parity_facts=[])
    for row in entries:
        ast = row['ast']
        base._budget(ast)
        if row is fn or row in facts:
            continue
        if ast[0] == '=' and ['call', 'Dom', ['ref', function_ref, 'function']] in ast[1:]:
            domain = ast[2] if ast[1][0] == 'call' else ast[1]
            _fixed_domain(domain)
            desc['domain_asts'].append(deepcopy(domain))
            desc['domain_source_refs'].append(row['source_ref'])
        elif ast[0] == '=' and ['call', 'degree', ['ref', function_ref, 'function']] in ast[1:]:
            degree = ast[2] if ast[1][0] == 'call' else ast[1]
            if degree not in [['number', str(i)] for i in range(5)]:
                raise ValueError('parity_joint.declared_degree_budget')
            desc['degrees'].append({'degree': int(degree[1]), 'source_ref': row['source_ref']})
        else:
            desc['constraints'].append(deepcopy(row))
    desc['domain_ast'] = desc['domain_asts'][0] if desc['domain_asts'] else ['real']
    for row in facts:
        desc['parity_facts'].append({'kind': 'function_parity', 'function_ref': function_ref,
                                    'variable_ref': desc['variable_ref'], 'property': row['ast'][2],
                                    'domain_ref': desc['domain_source_refs'] or [function_ref+'#natural_domain'],
                                    'source_refs': [row['source_ref'], fn['source_ref'], *desc['domain_source_refs']],
                                    'origin': 'given'})
    if len(entries) > LIMITS['conditions']:
        raise ValueError('parity_joint.condition_budget')
    source(desc)


def combine(first, second):
    if len(first)*len(second) > LIMITS['branches']:
        raise ValueError('parity_joint.branch_budget')
    return [{'equations': a['equations']+b['equations'], 'nonzero': a['nonzero']+b['nonzero']}
            for a in first for b in second]


def _conditions(ast, x, ps, refs):
    if ast[0] in ('and', 'or'):
        branches = [{'equations': [], 'nonzero': []}] if ast[0] == 'and' else []
        for child in ast[1:]:
            other = _conditions(child, x, ps, refs)
            branches = combine(branches, other) if ast[0] == 'and' else branches+other
            if len(branches) > LIMITS['branches']:
                raise ValueError('parity_joint.branch_budget')
        return branches
    if ast[0] == '∈' and ast[2] == ['real'] and ast[1][0] == 'ref' and ast[1][1] in refs:
        return [{'equations': [], 'nonzero': []}]
    if ast[0] not in ('=', '!='):
        raise ValueError('parity_joint.affine_equalities_and_nonzero_required')
    residual = polynomial(['-', *ast[1:]], x, ps, refs)
    if residual.has(x):
        raise ValueError('parity_joint.parameter_condition_required')
    residual = linear.canonical(residual, ps)
    return [{'equations': [residual] if ast[0] == '=' else [],
             'nonzero': [residual] if ast[0] == '!=' else []}]


def source(desc):
    x, ps = symbols(desc)
    expression = polynomial(desc['expression_ast'], x, ps, desc['parameter_refs'])
    domain = _fixed_domain(desc['domain_ast'])
    if any(_fixed_domain(a) != domain for a in desc['domain_asts']):
        domain = sp.S.EmptySet  # Contradictory complete-domain statements.
    branches = [{'equations': [], 'nonzero': []}]
    for row in desc['constraints']:
        branches = combine(branches, _conditions(row['ast'], x, ps, desc['parameter_refs']))
    coefficients = [sp.Poly(expression, x).nth(i) for i in range(5)]
    for row in desc['degrees']:
        degree = row['degree']
        branches = combine(branches, [{'equations': coefficients[degree+1:], 'nonzero': [coefficients[degree]]}])
    signs = sorted({s for fact in desc['parity_facts'] for s in base.PROPERTIES[fact['property']]})
    return x, ps, expression, domain, branches, signs


def _comparison(desc, *, independent):
    x, ps, expression, domain, _, signs = source(desc)
    valid = domain != sp.S.EmptySet and domain == fixed.reflect_set(domain)
    finite = isinstance(domain, sp.FiniteSet)
    mode = 'finite_points' if finite else 'polynomial_identity'
    rows, equations = [], []
    if independent:
        # Five exact input values recover the complete degree <= 4 polynomial;
        # this is not a numerical test of parity on sampled points.
        values = [(sp.Integer(i), expression.subs(x, i)) for i in range(-2, 3)]
        expression = sp.expand(sp.interpolate(values, x))
    for sign in signs:
        residual = sp.expand(expression.subs(x, -x)-sign*expression)
        for index in (sorted(domain) if finite else range(4, -1, -1)):
            value = residual.subs(x, index) if finite else sp.Poly(residual, x).nth(index)
            value = sp.simplify(value)
            linear.vector(value, ps)
            rows.append({'point' if finite else 'degree': index, 'sign': sign, 'residual': value})
            normalized = linear.canonical(value, ps)
            if normalized != 0 and normalized not in equations:
                equations.append(normalized)
    zeros = ([sp.simplify(expression.subs(x, q)) for q in sorted(domain)] if finite
             else [sp.Poly(expression, x).nth(i) for i in range(5)])
    zeros = sorted({linear.canonical(v, ps) for v in zeros if v != 0}, key=sp.default_sort_key)
    return {'domain': domain, 'domain_valid': bool(valid), 'mode': mode,
            'rows': rows, 'equations': equations, 'zero_equations': zeros}


def compare(desc):
    return _comparison(desc, independent=False)


def obligations(desc, comparison):
    _, ps, _, _, branches, _ = source(desc)
    parity = comparison['equations'] + ([] if comparison['domain_valid'] else [sp.S.One])
    branches = combine(branches, [{'equations': parity, 'nonzero': []}])
    if any(f['property'].endswith('_only') for f in desc['parity_facts']):
        branches = combine(branches, [{'equations': [], 'nonzero': [v]} for v in comparison['zero_equations']])
    canonical = []
    for branch in branches:
        row = {k: sorted({linear.canonical(v, ps) for v in values if v != 0 or k == 'nonzero'},
                         key=sp.default_sort_key) for k, values in branch.items()}
        if len(row['equations'])+len(row['nonzero']) > LIMITS['conditions']:
            raise ValueError('parity_joint.condition_budget')
        if row not in canonical:
            canonical.append(row)
    return canonical


def solve(desc, comparison=None):
    expected = compare(desc)
    if comparison is not None and comparison != expected:
        raise ValueError('parity_joint.comparison_mismatch')
    _, parameters = symbols(desc)
    branches = obligations(desc, expected)
    result = linear.solve(branches, parameters)
    return {'version': VERSION, 'description': deepcopy(desc), 'comparison': expected,
            'branches': branches, 'elimination': result, 'solution': result['families']}


def verify(desc, model):
    try:
        if model['version'] != VERSION or model['description'] != desc:
            return False
        expected = _comparison(desc, independent=True)
        if model['comparison'] != expected:
            return False
        branches = obligations(desc, expected)
        _, parameters = symbols(desc)
        return (model['branches'] == branches and linear.verify(branches, parameters, model['elimination'])
                and model['solution'] == model['elimination']['families'])
    except (ValueError, TypeError, KeyError, IndexError, NotImplementedError, sp.PolynomialError):
        return False
