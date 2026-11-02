"""D: derive a rule by legal specializations of a two-variable identity.

The search is bounded to four named substitutions. A specialization supplies a
necessary candidate; the full bivariate identity must still be proved exactly.
"""
from dataclasses import dataclass

import sympy as sp
from sympy.core.function import AppliedUndef

from ..problem_understanding.notation_parser import NotationError
from .function_formula import _bounded
from .range_syntax import range_domain

VERSION = 'function-formula-assignment/v1'


@dataclass(frozen=True)
class AssignmentSource:
    x: sp.Symbol
    y: sp.Symbol
    function: object
    left: sp.Expr
    right: sp.Expr
    declared: object
    requested: object

    @property
    def residual(self):
        return sp.expand(self.left-self.right)

    @property
    def substitutions(self):
        return ({str(self.x): sp.S.Zero}, {str(self.y): sp.S.Zero},
                {str(self.y): self.x}, {str(self.y): -self.x})

    def apply(self, expression, substitution):
        return sp.expand(expression.subs({sp.Symbol(k, real=True): v for k, v in substitution.items()}, simultaneous=True))


def assignment_source(desc):
    refs = desc.get('relation_variables_ast', [])
    if (desc.get('kind') != 'find_function_formula' or desc.get('function_type')
            or desc.get('extra_source_refs') or desc.get('additional_relations_ast')
            or len(refs) != 2 or refs[0] == refs[1] or desc['target_ast'][2] not in refs):
        raise NotationError('function_assignment.two_universal_variables_required')
    if desc.get('relation_domain_ast') is None or range_domain(desc['relation_domain_ast']) != sp.S.Reals:
        raise NotationError('function_assignment.all_real_pairs_required')
    declared = range_domain(desc['declared_domain_ast']) if desc.get('declared_domain_ast') is not None else None
    requested = range_domain(desc['requested_domain_ast']) if desc.get('requested_domain_ast') is not None else None
    if any(d is not None and d != sp.S.Reals for d in (declared, requested)):
        raise NotationError('function_assignment.extra_domain_unsupported')
    x = sp.Symbol(desc['variable'], real=True)
    other = next(ref for ref in refs if ref != desc['target_ast'][2])
    y = sp.Symbol(other[1].rsplit(':', 1)[-1], real=True)
    f = sp.Function(desc['function_name'])
    coordinates = {ref[1]: (x if ref == desc['target_ast'][2] else y) for ref in refs}
    count = 0

    def read(ast, depth=0, in_call=False):
        nonlocal count
        count += 1
        if count > 192 or depth > 16:
            raise NotationError('function_assignment.expression_budget')
        if ast[0] == 'ref' and ast[1] in coordinates:
            return coordinates[ast[1]]
        if ast[0] == 'number' and len(ast[1]) <= 80:
            return _bounded(sp.Rational(ast[1]))
        if ast[0] == 'function_call':
            if in_call or ast[1] != desc['target_ast'][1]:
                raise NotationError('function_assignment.single_unknown_function_required')
            arg = read(ast[2], depth+1, True)
            if sp.Poly(arg, x, y).total_degree() > 1:
                raise NotationError('function_assignment.affine_inputs_required')
            return f(arg)
        if ast[0] == 'neg':
            return -read(ast[1], depth+1, in_call)
        if ast[0] not in ('+', '-', '*', '/', '^') or len(ast) != 3:
            raise NotationError('function_assignment.expression_unsupported')
        a, b = (read(child, depth+1, in_call) for child in ast[1:])
        if ast[0] == '/':
            if not b.is_Rational or b == 0:
                raise NotationError('function_assignment.constant_divisor_required')
            value = a/b
        elif ast[0] == '^':
            if (b not in (1, 2) and not (b == 0 and a.is_nonzero is True)) or a.atoms(AppliedUndef):
                raise NotationError('function_assignment.power_unsupported')
            value = a**b
        else:
            value = {'+': lambda: a+b, '-': lambda: a-b, '*': lambda: a*b}[ast[0]]()
        if sp.count_ops(value) > 96:
            raise NotationError('function_assignment.expression_budget')
        for n in value.atoms(sp.Rational):
            _bounded(n)
        return value

    relation = desc['relation_ast']
    if relation[0] != '=':
        raise NotationError('function_assignment.equality_required')
    left, right = (read(ast) for ast in relation[1:])
    if (left.free_symbols | right.free_symbols) != {x, y}:
        raise NotationError('function_assignment.both_variables_required')
    calls = sorted(left.atoms(AppliedUndef) | right.atoms(AppliedUndef), key=str)
    if not 1 <= len(calls) <= 6:
        raise NotationError('function_assignment.call_budget')
    symbols = sp.symbols(f'_call0:{len(calls)}')
    # Check each side before cancellation: nonlinear calls cannot be hidden.
    for side in (left, right):
        p = sp.Poly(sp.expand(side.xreplace(dict(zip(calls, symbols)))), *symbols)
        if p.total_degree() > 1:
            raise NotationError('function_assignment.linear_function_values_required')
        for symbol in symbols:
            _bounded(p.coeff_monomial(symbol))
        h = sp.Poly(p.coeff_monomial(1), x, y)
        if h.total_degree() > 2 or len(h.terms()) > 16:
            raise NotationError('function_assignment.quadratic_right_side_required')
        for c in h.coeffs():
            _bounded(c)
    return AssignmentSource(x, y, f, left, right, declared, requested)


def available(desc):
    try:
        assignment_source(desc)
        return True
    except (ValueError, KeyError, TypeError, sp.PolynomialError):
        return False


def _zero_equation(s):
    residual = s.apply(s.residual, {str(s.x): sp.S.Zero, str(s.y): sp.S.Zero})
    if residual.atoms(AppliedUndef)-{s.function(0)}:
        return None
    z = sp.Symbol('_zero_value', real=True)
    p = sp.Poly(residual.xreplace({s.function(0): z}), z)
    return {'coefficient': p.coeff_monomial(z), 'rhs': -p.coeff_monomial(1)}


def specialized_equations(s, plan):
    if plan['substitution'] not in s.substitutions:
        raise NotationError('function_assignment.illegal_specialization')
    residual = s.apply(s.residual, plan['substitution'])
    remaining = s.y if str(s.x) in plan['substitution'] else s.x
    fx, f0 = s.function(remaining), s.function(0)
    if residual.atoms(AppliedUndef)-{fx, f0} or not residual.has(fx):
        raise NotationError('function_assignment.did_not_isolate')
    u, z = sp.symbols('_function_value _zero_value', real=True)
    p = sp.Poly(residual.xreplace({fx: u, f0: z}), u, z)
    coefficient, zero_coefficient = p.coeff_monomial(u), p.coeff_monomial(z)
    if not coefficient.is_Rational or coefficient == 0:
        raise NotationError('function_assignment.nonzero_coefficient_required')
    return {'variable': remaining, 'coefficient': coefficient, 'zero_coefficient': zero_coefficient,
            'rhs': -p.coeff_monomial(1), 'zero_equation': _zero_equation(s)}


def plan_assignment(desc):
    s = assignment_source(desc)
    zero = _zero_equation(s)
    if zero and zero['coefficient'] == 0 and zero['rhs'] != 0:
        raise NotationError('function_assignment.no_solution')
    options = []
    for substitution in s.substitutions:
        plan = {'substitution': substitution}
        try:
            eq = specialized_equations(s, plan)
        except NotationError:
            continue
        needs_zero = eq['zero_coefficient'] != 0
        if needs_zero and (not zero or zero['coefficient'] == 0):
            continue
        plan['needs_zero'] = bool(needs_zero)
        options.append(plan)
    if not options:
        raise NotationError('function_assignment.controlled_assignments_insufficient')
    return next((p for p in options if not p['needs_zero']), options[0])


def solve_specialized(s, plan, equations):
    if equations != specialized_equations(s, plan):
        raise NotationError('function_assignment.specialization_mismatch')
    e = equations
    z = e['zero_equation']
    needs_zero = e['zero_coefficient'] != 0
    if plan['needs_zero'] != bool(needs_zero) or needs_zero and (not z or z['coefficient'] == 0):
        raise NotationError('function_assignment.zero_value_not_determined')
    value = sp.cancel(z['rhs']/z['coefficient']) if needs_zero else None
    expression = sp.expand((e['rhs']-e['zero_coefficient']*(value or 0))/e['coefficient'])
    return expression.subs(e['variable'], s.x), value


def result_for(desc, s, plan, expression, zero_value):
    return {'kind': 'function_formula', 'derivation': 'assignment', 'function_name': desc['function_name'],
            'variable': s.x, 'expression': expression, 'source_domain': sp.S.Reals, 'determined_domain': sp.S.Reals,
            'declared_domain': s.declared, 'requested_domain': s.requested, 'status': 'determined_on_domain',
            'assignment_plan': plan, 'zero_value': zero_value}


def valid_derivation(desc, proposed):
    """Check the submitted specialization, without searching or solving again."""
    try:
        s, p = assignment_source(desc), proposed['expression']
        if (not isinstance(p, sp.Expr) or p.free_symbols-{s.x} or p.has(sp.Float)
                or sp.count_ops(p) > 128):
            return False
        if any(t.is_Pow and t.exp.is_negative and t.base.has(s.x) for t in sp.preorder_traversal(p)):
            return False
        poly = sp.Poly(p, s.x)
        if poly.total_degree() > 2 or not all(c.is_Rational for c in poly.coeffs()):
            return False
        plan, z = proposed['assignment_plan'], proposed['zero_value']
        e = specialized_equations(s, plan)
        if plan['needs_zero'] != bool(e['zero_coefficient'] != 0):
            return False
        if plan['needs_zero']:
            eq = e['zero_equation']
            if not eq or eq['coefficient'] == 0 or z is None or eq['coefficient']*z != eq['rhs']:
                return False
        elif z is not None:
            return False
        if sp.expand(e['coefficient']*p.subs(s.x, e['variable'])+e['zero_coefficient']*(z or 0)-e['rhs']) != 0:
            return False
        return proposed == result_for(desc, s, plan, p, z)
    except (ValueError, KeyError, TypeError, sp.PolynomialError):
        return False


def full_identity(s, expression):
    replacements = {call: expression.subs(s.x, call.args[0]) for call in s.residual.atoms(AppliedUndef)}
    return sp.expand(s.residual.xreplace(replacements)) == 0


def verify_assignment(desc, proposed):
    return valid_derivation(desc, proposed) and full_identity(assignment_source(desc), proposed['expression'])


def recover_assignment(desc):
    s, plan = assignment_source(desc), plan_assignment(desc)
    expression, zero = solve_specialized(s, plan, specialized_equations(s, plan))
    result = result_for(desc, s, plan, expression, zero)
    if not verify_assignment(desc, result):
        raise NotationError('function_assignment.no_solution')
    return result
