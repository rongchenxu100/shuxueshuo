"""Route-side interpretation of visible constraints, independent of verification.

Input is the execution context's compiled, lexically scoped notation, never the
verifier's OriginalProblem or predicate tree. Each route condition denotes a
set directly; Boolean/set constructors compose those sets. The verifier instead
re-reads original notation and tests its own predicate tree on a critical-cell
partition. Only the notation arithmetic foundation and context-free exact real
algebra/exception utilities are shared with it.
"""

from functools import cmp_to_key, lru_cache
from itertools import pairwise

import sympy as sp
from sympy.polys.polyerrors import BasePolynomialError

from ...problem_understanding.notation_parser import NotationError
from ...problem_understanding.notation_semantics import Canonical, bounded_expand, key

# These utilities interpret no problem, AST, domain, relation, or constraint.
from .verification import (
    VerificationGap,
    _algebraic_sign,
    _rational_between,
    _sympy_call,
    _sympy_gap_boundary,
    math_value,
)


def _coefficient_polynomial(expression, parameter):
    if expression.free_symbols - {parameter} or expression.has(sp.Float, sp.nan, sp.zoo):
        raise VerificationGap("route_constraints.real_algebraic_coefficients_required")
    try:
        polynomial = sp.Poly(expression, parameter)
    except BasePolynomialError as exc:
        raise VerificationGap("route_constraints.rational_function_required") from exc
    if polynomial.degree() > 48:
        raise VerificationGap("route_constraints.polynomial_degree_limit")
    if any(c.is_real is not True or c.is_algebraic is not True for c in polynomial.all_coeffs()):
        raise VerificationGap("route_constraints.real_algebraic_coefficients_required")
    return polynomial


def _rational_parts(expression, parameter):
    parts = sp.fraction(sp.cancel(expression))
    for part in parts:
        _coefficient_polynomial(part, parameter)
    return parts


def _roots(polynomial, parameter):
    """Exact roots (possibly extra conjugates) solely from an arithmetic value."""
    if polynomial.is_zero or polynomial.degree() == 0:
        return []
    if any(c.is_Rational is not True for c in polynomial.all_coeffs()):
        extended = _sympy_call("route_algebraic_polynomial", sp.Poly,
                               polynomial.as_expr(), parameter, extension=True)
        norm = _sympy_call("route_algebraic_norm", extended.norm)
        polynomial = _sympy_call("route_rational_norm", sp.Poly, norm.as_expr(), parameter, domain=sp.QQ)
        if polynomial.degree() > 48:
            raise VerificationGap("route_constraints.norm_degree_limit")
    return _sympy_call("route_real_roots", polynomial.real_roots)


def _accept_sign(sign, operator):
    return {"=": sign == 0, "!=": sign != 0, ">": sign > 0,
            ">=": sign >= 0, "<": sign < 0, "<=": sign <= 0}[operator]


@lru_cache(maxsize=256)
def _relation_domain(expression, operator, parameter):
    """Denote a single rational relation by exact cells and singleton roots.

    This operation receives arithmetic only. It neither sees original notation
    nor knows if the relation came from a set predicate or a top-level fact.
    Original holes are handled explicitly by the corresponding lexical scope.
    """
    numerator, denominator = _rational_parts(expression, parameter)
    roots = []
    for part in (numerator, denominator):
        roots.extend(_roots(_coefficient_polynomial(part, parameter), parameter))
    roots.sort(key=cmp_to_key(lambda a, b: _algebraic_sign(a - b)))
    points = []
    for root in roots:
        if not points or _algebraic_sign(root - points[-1]):
            points.append(root)

    def holds(value):
        divisor_sign = _algebraic_sign(denominator.subs(parameter, value))
        if divisor_sign == 0:
            return False
        sign = _algebraic_sign(numerator.subs(parameter, value)) * divisor_sign
        return _accept_sign(sign, operator)

    accepted = []
    for index, (left, right) in enumerate(pairwise([-sp.oo, *points, sp.oo])):
        if holds(_rational_between(left, right)):
            accepted.append(sp.Interval.open(left, right))
        if index < len(points) and holds(points[index]):
            accepted.append(sp.FiniteSet(points[index]))
    return sp.Union(*accepted)


class _RouteArithmetic(Canonical):
    """Execute notation arithmetic and retain original, uncanceled divisors.

    Binder environments avoid substituting a set-builder variable into the
    global problem. Its guards are discharged inside its own membership set.
    """

    def __init__(self, context):
        super().__init__()
        goal = context["goal_ast"]
        if goal["kind"] not in ("find_range", "find_minimum", "find_maximum") or goal["target"][0] != "ref":
            raise VerificationGap("route_constraints.single_parameter_required")
        self.parameter_ref = goal["target"][1]
        names = {symbol["ref"]: symbol["name"] for symbol in context["symbols"]}
        self.parameter = sp.Symbol(names[self.parameter_ref], real=True)
        self.bindings = {}
        self.guards = []

    def expr(self, ast, depth=0):
        if depth > 40:
            raise VerificationGap("route_constraints.arithmetic_depth")
        kind = ast[0]
        if kind == "ref":
            if ast[1] != self.parameter_ref:
                raise VerificationGap("route_constraints.additional_free_variable")
            return self.parameter
        if kind == "bound":
            if ast[1] not in self.bindings:
                raise VerificationGap("route_constraints.unbound_variable")
            return self.bindings[ast[1]]
        if kind == "call" and (ast[1] != "sqrt" or self.expr(ast[2], depth + 1).free_symbols):
            raise VerificationGap("route_constraints.symbolic_radical")
        if kind not in ("number", "+", "-", "*", "/", "^", "neg", "call", "function_call"):
            raise VerificationGap("route_constraints.arithmetic")
        value = super().expr(ast, depth)
        if kind == "/":
            self.guards.append(self.expr(ast[2], depth + 1))
        elif kind == "^" and self.expr(ast[2], depth + 1).is_negative:
            self.guards.append(self.expr(ast[1], depth + 1))
        return value


def _member_set(value, domain, algebra):
    """Preimage of a notation set, with lexical definedness at builder borders."""
    kind = domain[0]
    if kind == "real":
        return sp.S.Reals
    if kind == "empty_set":
        return sp.S.EmptySet
    if kind == "interval":
        endpoints = [endpoint[1] * sp.oo if endpoint[0] == "infinity" else algebra.expr(endpoint)
                     for endpoint in domain[3:]]
        if value == algebra.parameter and all(not endpoint.free_symbols for endpoint in endpoints):
            # A direct parameter domain already denotes its exact set. Keep
            # the authored algebraic endpoints instead of replacing radicals
            # by conjugate norm roots merely to rediscover the same interval.
            if any(endpoint.is_extended_real is not True for endpoint in endpoints):
                raise VerificationGap("route_constraints.real_interval_required")
            return sp.Interval(*endpoints, left_open=not domain[1], right_open=not domain[2])
        result = sp.S.Reals
        for side, endpoint in enumerate(endpoints):
            if endpoint in (-sp.oo, sp.oo):
                if endpoint != (-sp.oo if side == 0 else sp.oo):
                    return sp.S.EmptySet
                continue
            operator = ((">=" if domain[1] else ">") if side == 0
                        else ("<=" if domain[2] else "<"))
            result &= _relation_domain(value - endpoint, operator, algebra.parameter)
        return result
    if kind == "set":
        return sp.Union(*[_relation_domain(value - algebra.expr(member), "=", algebra.parameter)
                          for member in domain[1:]])
    if kind in ("∪", "∩"):
        operation = sp.Union if kind == "∪" else sp.Intersection
        return operation(*[_member_set(value, child, algebra) for child in domain[1:]])
    if kind == "set_builder":
        outer_guards, outer_bindings = algebra.guards, algebra.bindings
        algebra.guards = []
        try:
            domain_set = _member_set(value, domain[2], algebra)
            algebra.bindings = {**outer_bindings, domain[1]: value}
            predicate_set = _condition_set(domain[3], algebra)
            result = domain_set & predicate_set
            for divisor in algebra.guards:
                result &= _relation_domain(divisor, "!=", algebra.parameter)
            return result
        except NotationError as exc:
            if exc.code != "algebra.zero_denominator":
                raise
            # A constant member may land at a predicate's pole. It is outside
            # this set; a surrounding nonmembership/union can still accept it.
            return sp.S.EmptySet
        finally:
            algebra.guards, algebra.bindings = outer_guards, outer_bindings
    raise VerificationGap("route_constraints.unsupported_set_constructor")


def _condition_set(ast, algebra):
    kind = ast[0]
    if kind in ("and", "or"):
        operation = sp.Intersection if kind == "and" else sp.Union
        # Eagerly read every branch: outer definedness is not short-circuited.
        return operation(*[_condition_set(child, algebra) for child in ast[1:]])
    if kind in ("∈", "∉"):
        value = algebra.expr(ast[1])
        _rational_parts(value, algebra.parameter)
        members = _member_set(value, ast[2], algebra)
        return members if kind == "∈" else sp.S.Reals - members
    if kind in ("<", "<=", ">", ">=", "=", "!="):
        difference = bounded_expand(algebra.expr(ast[1]) - algebra.expr(ast[2]))
        return _relation_domain(difference, kind, algebra.parameter)
    raise VerificationGap("route_constraints.unsupported_condition")


def _context_atoms(context):
    """Use context lexical ancestry as supplied; no second original reader."""
    atoms = []
    pending = [(entry, entry["ast"]) for entry in reversed(context["entries"])]
    while pending:
        entry, ast = pending.pop()
        if ast[0] == "and":
            pending.extend((entry, child) for child in reversed(ast[1:]))
        else:
            atoms.append((entry["source_ref"], ast))
    return atoms


@_sympy_gap_boundary
def apply_visible_constraints(constraint_context, feasible_set):
    """Compute the route's restriction intersection from its own context only."""
    if constraint_context.get("goal", {}).get("kind") == "find_domain":
        from .function_domain import process_context
        return process_context(constraint_context, feasible_set)
    if constraint_context.get("goal", {}).get("kind") == "match_domain":
        from .function_domain import process_parameter_context
        return process_parameter_context(constraint_context, feasible_set)
    if constraint_context.get("goal", {}).get("kind") == "find_abstract_domain_parameter":
        from .abstract_domain_parameter import admitted
        if not admitted(constraint_context):
            raise VerificationGap("abstract_domain_parameter.context_not_admitted")
        return feasible_set, [{
            "source_ref": constraint_context["target_ref"],
            "status": "abstract_domain_parameter_identity",
        }]
    if constraint_context.get("goal", {}).get("kind") == "find_abstract_domain":
        # M2 already returns the independent-variable domain. Batch-1 identity
        # goals carry no additional visible parameter facts to intersect.
        goal = constraint_context.get("abstract_domain_goal") or {}
        return feasible_set, [
            {
                "source_ref": goal.get("source_ref") or constraint_context.get("target_ref"),
                "status": "abstract_domain_identity",
            }
        ]
    if 'range_goal' in constraint_context:
        from .function_range import process_context
        return process_context(constraint_context, feasible_set)
    algebra = _RouteArithmetic(constraint_context)
    atoms = _context_atoms(constraint_context)
    quantified = [ast for _, ast in atoms if ast[0] == "quantifier"]
    if len(quantified) != 1:
        raise VerificationGap("route_constraints.single_quantifier_required")
    main, = quantified
    if main[1] not in ("∀", "∃") or main[4][0] not in (">", ">=", "<", "<="):
        raise VerificationGap("route_constraints.quantified_relation_required")
    definitions = [(ref, ast) for ref, ast in atoms if ast[0] == "function_definition"]
    for _, definition in definitions:
        algebra.functions[key(algebra.tree(definition[1]))] = definition[2]
    result, processing, denominator_sources = feasible_set, [], []
    for source_ref, ast in atoms:
        if ast[0] == "function_definition":
            algebra.bindings = {"function_argument": sp.Dummy("route_argument", real=True)}
            algebra.expr(ast[2])
            processing.append({"source_ref": source_ref, "status": "expanded_definition"})
        elif ast is main:
            algebra.bindings = {main[2]: sp.Dummy("route_quantified", real=True)}
            # This step only reads arithmetic definedness; the method has
            # already solved the quantified relation and supplied feasible_set.
            if main[3][0] not in ("real", "interval"):
                raise VerificationGap("route_constraints.quantifier_interval_required")
            if main[3][0] == "interval":
                for endpoint in main[3][3:]:
                    if endpoint[0] != "infinity" and algebra.expr(endpoint).free_symbols:
                        raise VerificationGap("route_constraints.fixed_quantifier_domain_required")
            for side in main[4][1:]:
                algebra.expr(side)
            processing.append({"source_ref": source_ref, "status": "main_quantifier"})
        elif ast == ["default_domain", constraint_context["goal_ast"]["target"], "real"]:
            processing.append({"source_ref": source_ref, "status": "redundant_real_domain"})
        else:
            algebra.bindings = {}
            domain = _condition_set(ast, algebra)
            result &= domain
            processing.extend([
                {"source_ref": source_ref, "status": "parameter_constraint"},
                {"source_ref": source_ref, "status": "intersected",
                 "constraint_set": math_value(domain), "result": math_value(result)},
            ])
        denominator_sources.extend((divisor, source_ref) for divisor in algebra.guards)
        algebra.guards.clear()
    for divisor, source_ref in denominator_sources:
        # A quantifier/function-bound divisor is outside the accepted category,
        # even if simplification removed it from the displayed relation.
        if divisor.free_symbols - {algebra.parameter}:
            raise VerificationGap("route_constraints.bound_variable_denominator")
        zeros = _relation_domain(divisor, "=", algebra.parameter)
        result -= zeros
        processing.append({"source_ref": source_ref, "status": "original_denominator_nonzero",
                           "denominator": math_value(divisor), "excluded": math_value(zeros)})
    return result, processing
