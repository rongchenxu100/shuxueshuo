"""FP-T2 R1: parity conditions on affine domains and compatible partial rules.

The complete domain is mandatory for an abstract function. A local rule remains
local; the result certifies existence of a parity extension, not a unique formula.
"""
from copy import deepcopy

import sympy as sp

from ..problem_understanding.notation_parser import definition
from . import parameter_domain as domains
from . import parity_parameter_math as base

VERSION = 'parity-parameter/r1-domain-v1'


def _replace(ast, before, after):
    if ast == before:
        return deepcopy(after)
    return [_replace(v, before, after) if isinstance(v, list) else v for v in ast]


def _local_rule(row, function_ref, domain_ast):
    ast = row['ast']
    if ast[:2] != ['quantifier', '∀'] or ast[4][0] != '=':
        raise ValueError('parity_param.local_rule_required')
    call = ['function_call', ['ref', function_ref, 'function'], ['bound', ast[2]]]
    lhs, rhs = ast[4][1:]
    expr = rhs if lhs == call else lhs if rhs == call else None
    if expr is None:
        raise ValueError('parity_param.local_rule_binding')
    scope = ast[3]
    dom = ['call', 'Dom', ['ref', function_ref, 'function']]
    if scope[0] == '∩' and dom in scope[1:]:
        mask = scope[2] if scope[1] == dom else scope[1]
    elif domain_ast == ['real']:
        mask = scope
    else:
        raise ValueError('parity_param.local_rule_must_restrict_declared_domain')
    half = base._region(mask)
    if half not in (sp.Interval(0, sp.oo), sp.Interval.open(0, sp.oo),
                    sp.Interval(-sp.oo, 0), sp.Interval.open(-sp.oo, 0)):
        raise ValueError('parity_param.local_half_axis_required')
    return {'expression_ast': _replace(expr, ['bound', ast[2]], ['bound', 'function_argument']),
            'scope_ast': deepcopy(scope), 'mask_ast': deepcopy(mask), 'source_ref': row['source_ref']}


def populate(desc, entries, facts, definitions, function_ref, *, source_reader=None, maximum_degree=2):
    if len(definitions) > 1:
        raise ValueError('parity_param.single_formula_required')
    domain_rows = [(r, value) for r in entries if r['ast'][0] == '='
                   for call, value in (r['ast'][1:], r['ast'][1:][::-1])
                   if call == ['call', 'Dom', ['ref', function_ref, 'function']]]
    if (not domain_rows and not definitions) or (domain_rows and any(v != domain_rows[0][1] for _, v in domain_rows)):
        raise ValueError('parity_param.one_declared_domain_required')
    domain_ast = domain_rows[0][1] if domain_rows else ['real']
    p = sp.Symbol(desc['parameter'], real=True)
    tree = domains.compile_domain(domain_ast, p, desc['parameter_ref'])
    domains.partition(tree, p)  # Reject over-budget arrangements at admission.
    fn = definitions[0] if definitions else None
    raw = definition(fn['expression']) if fn else None
    domain_refs = [r['source_ref'] for r, _ in domain_rows] or [fn['source_ref']]
    desc.update(structure_version=VERSION, analysis_mode='domain', function_ref=function_ref,
                function=function_ref.rsplit(':', 1)[-1], variable=raw[2] if raw else 'x',
                expression=raw[3] if raw else None, expression_ast=fn['ast'][2] if fn else None,
                function_source_ref=fn['source_ref'] if fn else domain_refs[0],
                variable_ref=(fn['source_ref'] if fn else function_ref) + '#function_argument',
                domain_ast=deepcopy(domain_ast), domain_source_refs=domain_refs,
                constraints=[], degrees=[], parity_facts=[], local_rules=[], defined_regions=[])
    for row in entries:
        ast = row['ast']
        base._budget(ast)
        if row in facts or row in definitions or row['source_ref'] in domain_refs:
            continue
        if ast[0] == 'function_defined_on':
            if ast[1] != ['ref', function_ref, 'function'] or not fn or domain_ast != ['real']:
                raise ValueError('parity_param.defined_on_requires_full_real_polynomial')
            domains.compile_domain(ast[2], p, desc['parameter_ref'])
            desc['defined_regions'].append({'domain_ast': deepcopy(ast[2]), 'source_ref': row['source_ref']})
        elif ast[0] == 'quantifier':
            if fn or desc['local_rules']:
                raise ValueError('parity_param.single_local_rule_required')
            desc['local_rules'].append(_local_rule(row, function_ref, domain_ast))
        elif ast[0] == '=' and any(call == ['call', 'degree', ['ref', function_ref, 'function']]
                                  for call in ast[1:]):
            value = ast[2] if ast[1][0] == 'call' else ast[1]
            if not fn or value not in [['number', str(n)] for n in range(maximum_degree+1)]:
                raise ValueError('parity_param.declared_degree_unsupported')
            desc['degrees'].append({'degree': int(value[1]), 'source_ref': row['source_ref']})
        else:
            desc['constraints'].append(deepcopy(row))
    for row in facts:
        desc['parity_facts'].append({'kind': 'function_parity', 'function_ref': function_ref,
                                    'variable_ref': desc['variable_ref'], 'domain_ref': domain_refs,
                                    'property': row['ast'][2], 'origin': 'given',
                                    'source_refs': [row['source_ref'], *domain_refs,
                                                    *([fn['source_ref']] if fn else [])]})
    if len(desc['constraints']) + len(desc['degrees']) + len(facts) + len(desc['defined_regions']) > base.LIMITS['conditions']:
        raise ValueError('parity_param.condition_budget')
    (source_reader or source)(desc)


def source(desc):
    ast = desc['expression_ast']
    if ast is None and desc['local_rules']:
        ast = desc['local_rules'][0]['expression_ast']
    # The zero expression is only a parsing scaffold for parameter constraints.
    # The returned body stays None when no formula is given.
    x, p, expr, coefficients, conditions, signs = base.source({
        **desc, 'expression_ast': ast if ast is not None else ['number', '0']})
    def interval_conditions(tree):
        if tree[0] == 'interval':
            if tree[1] and tree[3] == -sp.oo or tree[2] and tree[4] == sp.oo:
                return [sp.false]
            return [sp.Lt(tree[3], tree[4])]
        return [c for child in tree[1:] if isinstance(child, list) for c in interval_conditions(child)]
    for region in desc['defined_regions']:
        conditions.extend(interval_conditions(domains.compile_domain(region['domain_ast'], p, desc['parameter_ref'])))
    return x, p, expr if ast is not None else None, coefficients if ast is not None else [], conditions, signs


def domain_contract(desc):
    return {key: deepcopy(desc[key]) for key in ('domain_ast', 'parameter', 'parameter_ref')}


def domain_evidence(desc):
    return domains.solve_domain_symmetry_conditions(**domain_contract(desc), source_refs=desc['domain_source_refs'])


def verify_domain(desc, proof):
    return domains.verify_domain_symmetry_conditions(**domain_contract(desc),
                                                     source_refs=desc['domain_source_refs'], proof=proof)


def _equations(expr, atoms, x, p, region):
    if not atoms:
        return []
    if any(a['kind'] == 'open' for a in atoms):
        values = sp.Poly(expr, x).all_coeffs()
    else:
        values = [expr.subs(x, a['point']) for a in atoms]
    if isinstance(region, sp.FiniteSet):
        values = [v.subs(p, next(iter(region))) for v in values]
    values = sorted({sp.expand(v) for v in values if sp.expand(v) != 0}, key=sp.default_sort_key)
    if any(sp.Poly(v, p).degree() > 2 for v in values):
        raise ValueError('parity_param.point_condition_degree_budget')
    return values


def _cell_relations(desc, proof, *, interpolate=False):
    x, p, expr, _, _, signs = source(desc)
    if expr is not None and interpolate:
        f0, f1, fm1 = [expr.subs(x, v) for v in (0, 1, -1)]
        expr = sp.expand(f0 + (f1-fm1)*x/2 + ((f1+fm1)/2-f0)*x*x)
    partial = desc['expression_ast'] is None
    mask = base._region(desc['local_rules'][0]['mask_ast']) if desc['local_rules'] else sp.S.EmptySet
    rows = []
    for cell in proof['cells']:
        if not cell['symmetric']:
            continue
        atoms = [a for a in cell['input_atoms'] if a['member']]
        region, value = cell['parameter_cell'], cell['representative']
        if partial:
            known = [a for a in atoms if mask.contains(domains.atom_point(a, p, value))]
            overlap = [a for a in known if mask.contains(-domains.atom_point(a, p, value))]
            # Zero is fixed by reflection; odd extensions must take value zero.
            relation_atoms = known if len(signs) == 2 else overlap
            residuals = ([expr] if len(signs) == 2 else [expr.subs(x, -x)-sign*expr for sign in signs]) if expr is not None else []
            free_nonzero = len(signs) < 2 and any(
                not mask.contains(domains.atom_point(a, p, value))
                and not mask.contains(-domains.atom_point(a, p, value))
                and (signs == [1] or a['kind'] == 'open' or domains.atom_point(a, p, value) != 0)
                for a in atoms)
            zero_atoms = known
        else:
            relation_atoms, zero_atoms, free_nonzero = atoms, atoms, False
            residuals = [expr.subs(x, -x)-sign*expr for sign in signs]
        equations = sorted({e for residual in residuals
                            for e in _equations(residual, relation_atoms, x, p, region)}, key=sp.default_sort_key)
        zeros = _equations(expr, zero_atoms, x, p, region) if expr is not None else []
        rows.append({'parameter_cell': region, 'equations': equations, 'zero_equations': zeros,
                     'free_nonzero_extension': free_nonzero,
                     'basis': 'partial_rule_overlap' if partial else
                              'polynomial_identity_on_interval' if any(a['kind'] == 'open' for a in atoms)
                              else 'all_domain_points'})
    return rows


def compare(desc, proof):
    if not verify_domain(desc, proof):
        raise ValueError('parity_param.domain_certificate_failed')
    return {'domain_evidence': proof, 'rows': _cell_relations(desc, proof)}


def _aggregate(desc, comparison, *, independent=False):
    _, p, _, _, conditions, _ = source(desc)
    set_for = (lambda conditions: base._cell_set(conditions, p)) if independent else (
        lambda conditions: sp.Intersection(*(base.condition_set(c, p) for c in conditions))
        if conditions else sp.S.Reals)
    parameter_space = set_for(conditions)
    parity, zero = [], []
    for row in comparison['rows']:
        region = row['parameter_cell']
        parity.append(region & set_for([sp.Eq(e, 0) for e in row['equations']]))
        if not row['free_nonzero_extension']:
            zero.append(region & set_for([sp.Eq(e, 0) for e in row['zero_equations']]))
    parity_set, zero_set = sp.Union(*parity), sp.Union(*zero)
    exclusive = any(f['property'].endswith('_only') for f in desc['parity_facts'])
    feasible = parameter_space & parity_set
    if exclusive:
        feasible -= zero_set
    return {'parameter_space': parameter_space, 'parity_set': parity_set, 'zero_set': zero_set,
            'feasible_set': feasible, 'exclusive': exclusive, 'conditions': conditions}


def solve(desc, comparison=None):
    if comparison is None:
        comparison = compare(desc, domain_evidence(desc))
    if (not verify_domain(desc, comparison['domain_evidence'])
            or comparison['rows'] != _cell_relations(desc, comparison['domain_evidence'])):
        raise ValueError('parity_param.domain_relation_evidence_mismatch')
    return {'version': VERSION, 'description': deepcopy(desc), 'comparison': comparison,
            'verification_basis': 'complete_affine_parameter_and_input_cells',
            'domain_ast': deepcopy(desc['domain_ast']), **_aggregate(desc, comparison)}


def verify(desc, model):
    try:
        proof = model['comparison']['domain_evidence']
        if (model.get('version') != VERSION or model.get('description') != desc
                or model.get('domain_ast') != desc['domain_ast'] or not verify_domain(desc, proof)
                or model['comparison']['rows'] != _cell_relations(desc, proof, interpolate=True)):
            return False
        expected = _aggregate(desc, model['comparison'], independent=True)
        return all(model.get(k) == v for k, v in expected.items())
    except (ValueError, TypeError, KeyError, IndexError, NotImplementedError):
        return False
