"""Independent, exact critical-cell proofs for the first execution category.

The verifier reads validated original notation, never the method's normalized
expression, features, or intermediate calculations.  Samples cover a proved
sign-invariant partition; sampling a proposed answer alone is not a proof.
"""

import re
from copy import deepcopy
from dataclasses import dataclass
from functools import cmp_to_key, lru_cache, wraps
from itertools import pairwise

import sympy as sp
from sympy.polys.polyerrors import BasePolynomialError

from ...problem_understanding.notation_compile import NotationValidator
from ...problem_understanding.notation_parser import NotationError
from ...problem_understanding.notation_semantics import Canonical, bounded_expand, key
from .math_values import math_value


class VerificationGap(ValueError):
    """The supported exact proof category does not cover this input."""


class ContextMismatch(ValueError):
    pass


def _pointer(path):
    parts = re.sub(r"^r(?=\.|$)", "/root", path)
    parts = re.sub(r"\.c(\d+)", r"/children/\1", parts)
    return re.sub(r"\[(\d+)\]", r"/\1", parts.replace(".", "/"))


def _walk(ast, path=()):
    yield ast, path
    for i, child in enumerate(ast[1:], 1):
        if isinstance(child, list) and child and isinstance(child[0], str):
            yield from _walk(child, (*path, i))


def _source(candidate, path):
    value = candidate
    for part in path.strip("/").split("/"):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def collect_original(candidate, target_ref):
    """Collect sources by walking original lexical ancestry, independently of context.py."""
    if not re.fullmatch(r"/root(?:/children/\d+)*/goals/\d+", target_ref):
        raise VerificationGap("invalid_target")
    report = NotationValidator().validate_root(candidate["root"])
    if not report.ok:
        raise VerificationGap("invalid_candidate")
    goal_scope, _, goal_index = target_ref.rsplit("/", 2)
    visible = ["/root"]
    semantic = report.semantic
    for index in goal_scope.removeprefix("/root").split("/children/")[1:]:
        visible.append(visible[-1] + "/children/" + index)
        semantic = semantic["children"][int(index)]
    goal = semantic["goals"][int(goal_index)]
    entries = []
    for compiled_scope, facts in report.scope_facts.items():
        scope = _pointer(compiled_scope)
        if scope not in visible:
            continue
        for row in facts:
            source = _pointer(row["path"])
            entries.append({"source_ref": source, "scope": scope,
                            "kind": "definition" if "/definitions/" in source else "fact",
                            "expression": deepcopy(_source(candidate, source)), "ast": deepcopy(row["value"])})
    objects = [o for o in report.objects if _pointer(o["scope"]) in visible]
    default_map = {item["ref"]: item for item in report.defaults}
    symbols = []
    for obj in objects:
        refs = [e["source_ref"] for e in entries
                if any(a[0] == "ref" and a[1] == obj["ref"] for a, _ in _walk(e["ast"]))]
        if any(a[0] == "ref" and a[1] == obj["ref"] for a, _ in _walk(goal["target"])):
            refs.append(target_ref)
        symbols.append({**obj, "scope": _pointer(obj["scope"]), "source_refs": refs,
                        "default_domain": default_map.get(obj["ref"])})
    bound, denominators = [], []
    for entry in entries:
        ast = entry["ast"]
        # Determine enclosing binders by path ancestry, rather than using the
        # driver's recursive collection function.
        binders = []
        for node, path in _walk(ast):
            if node[0] in ("quantifier", "set_builder", "function_definition"):
                function = node[0] == "function_definition"
                i = 2 if node[0] == "quantifier" else 1
                ref = entry["source_ref"] + ("#function_argument" if function
                                               else "#" + "/".join(map(str, (*path, i))))
                record = {"ref": ref, "name": "function_argument" if function else node[i],
                          "kind": "function_argument" if function else "bound",
                          "scope": entry["scope"], "source_ref": entry["source_ref"],
                          "domain": ["real"] if function else deepcopy(node[i + 1]),
                          "binding_path": list(path)}
                bound.append(record)
                binders.append((path, len(node) - 1, record))
        for node, path in _walk(ast):
            if node[0] == "/":
                active = [b[2]["ref"] for b in binders
                          if len(path) > len(b[0]) and path[:len(b[0])] == b[0]
                          and (b[2]["kind"] == "function_argument" or path[len(b[0])] == b[1])]
                denominators.append({"kind": "denominator_nonzero", "source_ref": entry["source_ref"],
                                     "scope": entry["scope"], "ast_path": list(path),
                                     "denominator": deepcopy(node[2]), "binding_refs": active})
    return {"target_ref": target_ref, "scope": goal_scope, "visible_scopes": visible,
            "goal": deepcopy(_source(candidate, target_ref)), "goal_ast": deepcopy(goal),
            "entries": entries, "symbols": symbols, "bound_symbols": bound,
            "default_domains": [default_map[o["ref"]] for o in objects if o["ref"] in default_map],
            "well_definedness": denominators}


def _without_processing(value):
    if isinstance(value, dict):
        return {k: _without_processing(v) for k, v in value.items() if k != "processing"}
    if isinstance(value, list):
        return [_without_processing(v) for v in value]
    return value


def check_context(original, context):
    for field, value in original.items():
        if _without_processing(context.get(field)) != value:
            raise ContextMismatch("constraint_context_mismatch:" + field)


class _Arithmetic(Canonical):
    def __init__(self, symbols, parameter_ref, bound):
        super().__init__()
        self.names = {s["ref"]: s["name"] for s in symbols}
        self.parameter_ref = parameter_ref
        self.parameter = sp.Symbol(self.names[parameter_ref], real=True)
        self.x = sp.Dummy("quantified", real=True)
        self.bound = bound
        self.denominators = []

    def expr(self, ast, depth=0):
        if depth > 40:
            raise VerificationGap("arithmetic_depth")
        if ast[0] == "ref":
            if ast[1] != self.parameter_ref:
                raise VerificationGap("unsupported_constraint:additional_free_variable")
            return self.parameter
        if ast[0] == "bound":
            if ast[1] != self.bound:
                raise VerificationGap("unsupported_constraint:bound_variable")
            return self.x
        if ast[0] == "call" and (ast[1] != "sqrt" or self.expr(ast[2], depth + 1).free_symbols):
            raise VerificationGap("verification_incomplete:symbolic_radical")
        if ast[0] not in ("number", "+", "-", "*", "/", "^", "neg", "call", "function_call"):
            raise VerificationGap("verification_incomplete:arithmetic")
        value = super().expr(ast, depth)
        if ast[0] == "/":
            self.denominators.append(self.expr(ast[2], depth + 1))
        elif ast[0] == "^" and self.expr(ast[2], depth + 1).is_negative:
            self.denominators.append(self.expr(ast[1], depth + 1))
        return value


@dataclass
class OriginalProblem:
    original: dict
    algebra: _Arithmetic
    expression: sp.Expr
    main_ref: str
    constraints: list
    denominators: list
    processing: list
    strict: bool = False
    quantifier: str = "∀"
    domain: sp.Set = sp.S.Reals
    extended_coefficients_or_constraints: bool = False

    @property
    def parameter(self):
        return self.algebra.parameter

    @property
    def x(self):
        return self.algebra.x


def _interval(ast, algebra):
    if ast == ["real"]:
        return sp.S.Reals
    if ast[0] != "interval":
        raise VerificationGap("unsupported_constraint:parameter_domain")
    endpoints = []
    for value in ast[3:]:
        endpoint = value[1] * sp.oo if value[0] == "infinity" else algebra.expr(value)
        if endpoint.free_symbols or endpoint.is_extended_real is not True:
            raise VerificationGap("unsupported_constraint:parameter_domain")
        endpoints.append(endpoint)
    return sp.Interval(*endpoints, left_open=not ast[1], right_open=not ast[2])


def _poly(expression, parameter):
    try:
        result = sp.Poly(expression, parameter, domain=sp.QQ)
    except BasePolynomialError as exc:
        raise VerificationGap("verification_incomplete:rational_polynomial_required") from exc
    if result.degree() > 48:
        raise VerificationGap("verification_incomplete:polynomial_degree_limit")
    return result


def _algebraic_poly(expression, parameter):
    """Validate a polynomial over real algebraic constants without choosing conjugates."""
    if expression.free_symbols - {parameter} or expression.has(sp.Float, sp.nan, sp.zoo):
        raise VerificationGap("verification_incomplete:real_algebraic_coefficients_required")
    try:
        poly = sp.Poly(expression, parameter)
    except BasePolynomialError as exc:
        raise VerificationGap("verification_incomplete:rational_function_required") from exc
    if poly.degree() > 48:
        raise VerificationGap("verification_incomplete:polynomial_degree_limit")
    if any(c.is_real is not True or c.is_algebraic is not True for c in poly.all_coeffs()):
        raise VerificationGap("verification_incomplete:real_algebraic_coefficients_required")
    return poly


def _rational_function(expression, parameter):
    numerator, denominator = sp.fraction(sp.cancel(expression))
    top, bottom = (_algebraic_poly(value, parameter) for value in (numerator, denominator))
    if bottom.is_zero:
        raise VerificationGap("verification_incomplete:zero_denominator")
    return top, bottom


def _legacy_polynomial(expression, parameter, maximum=48):
    top, bottom = _rational_function(expression, parameter)
    return (bottom.degree() == 0 and top.degree() <= maximum
            and all(c.is_Rational is True for poly in (top, bottom) for c in poly.all_coeffs()))


def _replace_bound(ast, name, replacement):
    if not isinstance(ast, list):
        return ast
    if ast[:2] == ["bound", name]:
        return deepcopy(replacement)
    return [_replace_bound(child, name, replacement) for child in ast]


def _membership_ast(value, domain):
    """Translate the notation's real set constructors into semialgebraic atoms."""
    kind = domain[0]
    if kind == "real":
        # The tautology still reads value, retaining its original denominator.
        return ["=", value, value]
    if kind == "empty_set":
        return ["!=", value, value]
    if kind == "interval":
        conditions = []
        for endpoint, closed, lower in ((domain[3], domain[1], True), (domain[4], domain[2], False)):
            if endpoint[0] == "infinity":
                if endpoint[1] != (-1 if lower else 1):
                    conditions.append(["!=", value, value])
                continue
            operator = (">=" if closed else ">") if lower else ("<=" if closed else "<")
            conditions.append([operator, value, endpoint])
        return ["and", *conditions] if conditions else ["=", value, value]
    if kind == "set":
        return ["or", *[["=", value, member] for member in domain[1:]]]
    if kind in ("∪", "∩"):
        return ["or" if kind == "∪" else "and", *[_membership_ast(value, member) for member in domain[1:]]]
    if kind == "set_builder":
        # Undefined predicate values are outside this set, not outside the
        # entire problem. Keep the binder boundary when substituting a member.
        return ["locally_defined", ["and", _membership_ast(value, domain[2]),
                                    _replace_bound(domain[3], domain[1], value)]]
    raise VerificationGap("unsupported_constraint:semialgebraic_membership_required")


def _constraint_tree(ast, algebra, source_ref):
    kind = ast[0]
    common = {"source_ref": source_ref}
    if kind == "locally_defined":
        outer_denominators = algebra.denominators
        algebra.denominators = []
        try:
            child = _constraint_tree(ast[1], algebra, source_ref)
            local_denominators = algebra.denominators
        except NotationError as exc:
            if exc.code != "algebra.zero_denominator":
                raise
            # A constant member can land exactly on a predicate pole during
            # substitution. Membership is then false, including under ∉;
            # the member's own outer definedness has already been retained.
            return {**common, "kind": "relation", "expression": sp.S.Zero,
                    "operator": "!=", "origin": "set_builder_definedness"}
        finally:
            algebra.denominators = outer_denominators
        guards = []
        for denominator in local_denominators:
            _rational_function(denominator, algebra.parameter)
            # Explicit atoms retain even canceled holes in both the local
            # predicate and its critical partition, underneath any complement.
            guards.append({**common, "kind": "relation", "expression": denominator,
                           "operator": "!=", "origin": "set_builder_definedness"})
        return {**common, "kind": "and", "children": [*guards, child]}
    if kind in ("and", "or"):
        return {**common, "kind": kind,
                "children": [_constraint_tree(child, algebra, source_ref) for child in ast[1:]]}
    if kind in ("∈", "∉"):
        # Read the member even for an empty set: definedness is not short-circuited.
        _rational_function(algebra.expr(ast[1]), algebra.parameter)
        child = _constraint_tree(_membership_ast(ast[1], ast[2]), algebra, source_ref)
        return child if kind == "∈" else {**common, "kind": "not", "children": [child]}
    if kind in ("<", "<=", ">", ">=", "=", "!="):
        difference = bounded_expand(algebra.expr(ast[1]) - algebra.expr(ast[2]))
        _rational_function(difference, algebra.parameter)
        return {**common, "kind": "relation", "expression": difference, "operator": kind}
    raise VerificationGap("unsupported_constraint:" + source_ref)


def _constraint_atoms(constraint):
    if constraint["kind"] in ("and", "or", "not"):
        return [atom for child in constraint["children"] for atom in _constraint_atoms(child)]
    return [constraint]


def _flatten(ast):
    if ast[0] == "and":
        return [atom for child in ast[1:] for atom in _flatten(child)]
    return [ast]


def read_problem(candidate, target_ref, constraint_context=None):
    original = collect_original(candidate, target_ref)
    if constraint_context is not None:
        check_context(original, constraint_context)
    goal = original["goal_ast"]
    if goal["kind"] not in ("find_range", "find_minimum", "find_maximum") or goal["target"][:1] != ["ref"]:
        raise VerificationGap("verification_incomplete:single_real_parameter")
    atoms = [(entry, atom) for entry in original["entries"] for atom in _flatten(entry["ast"])]
    quantified = [(entry, atom) for entry, atom in atoms if atom[0] == "quantifier"]
    if len(quantified) != 1:
        raise VerificationGap("unsupported_constraint:single_quantifier_required")
    main_entry, main = quantified[0]
    if main[1] not in ("∀", "∃") or main[4][0] not in (">=", "<=", ">", "<"):
        raise VerificationGap("verification_incomplete:quantified_order_relation")
    algebra = _Arithmetic(original["symbols"], goal["target"][1], main[2])
    domain = _interval(main[3], algebra)
    if any(point.is_algebraic is not True for point in _set_boundaries(domain)):
        raise VerificationGap("verification_incomplete:algebraic_quantifier_domain")
    processing, constraints, denominator_sources = [], [], []
    for entry, atom in atoms:
        if atom[0] == "function_definition":
            algebra.functions[key(algebra.tree(atom[1]))] = atom[2]
            processing.append({"source_ref": entry["source_ref"], "status": "expanded_definition"})
    # Definitions remain visible constraints even if an algebraic cancellation
    # or an unused function hides their body from the main relation.  Inspect
    # their original arithmetic before any normalization can remove holes.
    for entry, atom in atoms:
        if atom[0] == "function_definition":
            algebra.bound = "function_argument"
            algebra.expr(atom[2])
            denominator_sources.extend((d, entry["source_ref"]) for d in algebra.denominators)
            algebra.denominators.clear()
    algebra.bound = main[2]
    lhs, rhs = (algebra.expr(side) for side in main[4][1:])
    expression = bounded_expand(lhs - rhs if main[4][0] in (">=", ">") else rhs - lhs)
    denominator_sources.extend((d, main_entry["source_ref"]) for d in algebra.denominators)
    algebra.denominators.clear()
    try:
        polynomial = sp.Poly(expression, algebra.x)
    except BasePolynomialError as exc:
        raise VerificationGap("verification_incomplete:polynomial_degree_at_most_two_required") from exc
    # The same complete coefficient/endpoint partition covers original affine
    # and constant predicates, not only quadratics that degenerate at a point.
    # The identically zero polynomial has degree -oo and is included as well.
    if polynomial.degree() > 2:
        raise VerificationGap("verification_incomplete:polynomial_degree_at_most_two_required")
    legacy_coefficients = [_legacy_polynomial(coefficient, algebra.parameter) for coefficient in polynomial.all_coeffs()]
    extended = not all(legacy_coefficients)
    for entry, atom in atoms:
        source_ref = entry["source_ref"]
        if atom is main:
            processing.append({"source_ref": source_ref, "status": "main_quantifier"})
            continue
        if atom[0] == "function_definition":
            continue
        if atom[0] == "default_domain" and atom[1] == goal["target"] and atom[2] == "real":
            processing.append({"source_ref": source_ref, "status": "redundant_real_domain"})
        elif (atom[0] == "∈" and atom[1] == goal["target"]
              and atom[2][0] in ("real", "interval")
              and not any(node[0] in ("ref", "bound") for node, _ in _walk(atom[2]))):
            parameter_domain = _interval(atom[2], algebra)
            constraints.append({"source_ref": source_ref, "kind": "membership", "set": parameter_domain})
            processing.append({"source_ref": source_ref, "status": "parameter_constraint",
                               "set": math_value(parameter_domain)})
        else:
            constraint = _constraint_tree(atom, algebra, source_ref)
            constraints.append(constraint)
            extended = extended or constraint["kind"] != "relation" or not _legacy_polynomial(
                constraint["expression"], algebra.parameter, maximum=1)
            processing.append({"source_ref": source_ref, "status": "parameter_constraint"})
        denominator_sources.extend((d, source_ref) for d in algebra.denominators)
        algebra.denominators.clear()
    for denominator, _ in denominator_sources:
        if algebra.x in denominator.free_symbols:
            raise VerificationGap("verification_incomplete:bound_variable_denominator")
        _rational_function(denominator, algebra.parameter)
    return OriginalProblem(original, algebra, expression, main_entry["source_ref"], constraints,
                           denominator_sources, processing, strict=main[4][0] in (">", "<"),
                           quantifier=main[1], domain=domain,
                           extended_coefficients_or_constraints=extended)


def _relation(expression, operator):
    return {"<": sp.Lt, "<=": sp.Le, ">": sp.Gt, ">=": sp.Ge, "=": sp.Eq, "!=": sp.Ne}[operator](expression, 0)


_SYMPY_COMPUTATION_ERRORS = (BasePolynomialError, NotImplementedError, IndexError, ValueError, ZeroDivisionError)


def _sympy_call(operation, function, *args, **kwargs):
    """An explicit library boundary, never a blanket catch around our control flow.

    SymPy sometimes raises IndexError/ValueError while isolating valid algebraic
    inputs.  Those are unproved computations.  The documented undecidable
    relational truth-value TypeError is also a gap; other KeyError/TypeError,
    or an index/value error from our own bookkeeping, remain programming failures.
    """
    try:
        return function(*args, **kwargs)
    except (ContextMismatch, VerificationGap):
        raise
    except _SYMPY_COMPUTATION_ERRORS as exc:
        raise VerificationGap("verification_incomplete:sympy_" + operation) from exc
    except TypeError as exc:
        if not str(exc).startswith("cannot determine truth value of Relational"):
            raise
        raise VerificationGap("verification_incomplete:sympy_" + operation) from exc


def _sympy_traceback(exc):
    """Fallback for SymPy operations performed through Python arithmetic hooks."""
    trace = exc.__traceback__
    while trace is not None:
        if trace.tb_frame.f_globals.get("__name__", "").startswith("sympy."):
            return True
        trace = trace.tb_next
    return False


def _library_exception_details(exc):
    cause = exc.__cause__
    if isinstance(exc, VerificationGap) and cause is not None and (
        str(exc).startswith("verification_incomplete:sympy_") or _sympy_traceback(cause)
    ):
        exc = cause
    elif not _sympy_traceback(exc):
        return {}
    return {"library_exception_type": type(exc).__name__, "library_exception_message": str(exc)}


def _is_sympy_computation_failure(exc):
    return _sympy_traceback(exc) and (
        not isinstance(exc, TypeError) or str(exc).startswith("cannot determine truth value of Relational")
    )


def _sympy_gap_boundary(function):
    """Protect non-verdict operations while leaving local bugs and mismatches visible."""
    @wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (ContextMismatch, VerificationGap):
            raise
        except (*_SYMPY_COMPUTATION_ERRORS, TypeError) as exc:
            if not _is_sympy_computation_failure(exc):
                raise
            raise VerificationGap("verification_incomplete:sympy_" + function.__name__) from exc

    return guarded


@lru_cache(maxsize=512)
def _algebraic_value(value):
    """Prove zero/rational values from the minimal polynomial of the whole value.

    Expression equality/is_zero alone is insufficient for r**3-r-1 when r is
    a RootOf.  Its minimal polynomial is z, so its exact value is zero.  A
    degree-one minimal polynomial similarly gives the unique rational value.
    Higher-degree values retain their original real embedding for certified
    interval signs; the polynomial's constant term alone is not a sign test.

    Do not compose a field from every nested radical atom: sqrt(1+sqrt(2)) and
    sqrt(2) are redundant generators, and that route can make SymPy's primitive
    element construction expensive or fail internally.
    """
    if value.is_Rational:
        return value
    if value.free_symbols or value.has(sp.Float, sp.nan, sp.zoo, sp.oo, -sp.oo):
        raise VerificationGap("verification_incomplete:exact_algebraic_value_required")
    algebraic_atoms = value.atoms(sp.CRootOf) | {
        power for power in value.atoms(sp.Pow) if power.exp.is_Rational and not power.exp.is_Integer
    }
    if not algebraic_atoms:
        raise VerificationGap("verification_incomplete:algebraic_value_unsupported")
    variable = sp.Dummy("algebraic_value")
    expression = _sympy_call("minimal_polynomial", sp.minpoly, value, variable)
    polynomial = _sympy_call("minimal_polynomial_domain", sp.Poly, expression, variable, domain=sp.QQ)
    if polynomial.degree() == 1:
        return -polynomial.nth(0) / polynomial.nth(1)
    if polynomial.degree() < 1 or polynomial.nth(0) == 0:
        raise VerificationGap("verification_incomplete:invalid_minimal_polynomial")
    return value


def _interval_product(left, right):
    products = [a*b for a in left for b in right]
    return min(products), max(products)


def _integer_power(bounds, exponent):
    if exponent == 0:
        return sp.S.One, sp.S.One
    if exponent < 0:
        if bounds[0] <= 0 <= bounds[1]:
            return None
        bounds = (1 / bounds[1], 1 / bounds[0])
        exponent = -exponent
    values = [value**exponent for value in bounds]
    if exponent % 2 == 0 and bounds[0] <= 0 <= bounds[1]:
        values.append(sp.S.Zero)
    return min(values), max(values)


def _rational_root_bound(value, degree, precision):
    """Certified dyadic enclosure using integer nth roots, without evalf."""
    scale = 2**precision
    floor_power = int(sp.floor(value * scale**degree))
    lower, _exact = sp.integer_nthroot(floor_power, degree)
    lower = sp.Rational(lower, scale)
    upper = lower if lower**degree == value else lower + sp.Rational(1, scale)
    return lower, upper


def _algebraic_interval(value, roots, precision):
    """Outward rational arithmetic over real-root isolating intervals."""
    if value.is_Rational:
        return value, value
    if isinstance(value, sp.CRootOf):
        if value.is_real is not True:
            raise VerificationGap("verification_incomplete:nonreal_algebraic_value")
        interval = roots[value]
        return sp.Rational(interval.a), sp.Rational(interval.b)
    if value.is_Add or value.is_Mul:
        result = (sp.S.Zero, sp.S.Zero) if value.is_Add else (sp.S.One, sp.S.One)
        for argument in value.args:
            bound = _algebraic_interval(argument, roots, precision)
            if bound is None:
                return None
            result = ((result[0] + bound[0], result[1] + bound[1]) if value.is_Add
                      else _interval_product(result, bound))
        return result
    if value.is_Pow and value.exp.is_Rational:
        bound = _algebraic_interval(value.base, roots, precision)
        if bound is None:
            return None
        if value.exp.is_Integer:
            return _integer_power(bound, int(value.exp))
        if bound[0] < 0:
            return None
        degree = int(value.exp.q)
        if degree > 48:
            raise VerificationGap("verification_incomplete:radical_degree_limit")
        lower = _rational_root_bound(bound[0], degree, precision)[0]
        upper = _rational_root_bound(bound[1], degree, precision)[1]
        return _integer_power((lower, upper), int(value.exp.p))
    raise VerificationGap("verification_incomplete:algebraic_interval_unsupported")


@lru_cache(maxsize=512)
def _algebraic_sign(value):
    """Return -1/0/+1 only with exact evidence; undecidable means a gap."""
    value = _algebraic_value(value)
    if value.is_Rational:
        return 0 if value == 0 else 1 if value > 0 else -1
    roots = {root: _sympy_call("root_interval", root._get_interval) for root in value.atoms(sp.CRootOf)}
    for precision in range(4, 260):
        bounds = _algebraic_interval(value, roots, precision)
        if bounds is not None:
            if bounds[0] > 0:
                return 1
            if bounds[1] < 0:
                return -1
        roots = {root: _sympy_call("root_refinement", interval.refine) for root, interval in roots.items()}
    raise VerificationGap("verification_incomplete:algebraic_sign_unproved")


def _relation_holds(expression, operator):
    sign = _algebraic_sign(expression)
    return {"<": sign < 0, "<=": sign <= 0, ">": sign > 0,
            ">=": sign >= 0, "=": sign == 0, "!=": sign != 0}[operator]


def _contains_exact(domain, value):
    if domain == sp.S.Reals:
        return True
    if domain == sp.S.EmptySet:
        return False
    if isinstance(domain, sp.Interval):
        left = 1 if domain.start is -sp.oo else _algebraic_sign(value - domain.start)
        right = -1 if domain.end is sp.oo else _algebraic_sign(value - domain.end)
        return (left > 0 or left == 0 and not domain.left_open) and (right < 0 or right == 0 and not domain.right_open)
    if isinstance(domain, sp.FiniteSet):
        return any(_algebraic_sign(value - member) == 0 for member in domain)
    if isinstance(domain, sp.Union):
        return any(_contains_exact(member, value) for member in domain.args)
    raise VerificationGap("verification_incomplete:set_membership")


def _constraint_holds(constraint, parameter, value):
    kind = constraint["kind"]
    if kind == "membership":
        return _contains_exact(constraint["set"], value)
    if kind == "relation":
        numerator, denominator = sp.fraction(sp.cancel(constraint["expression"]))
        denominator_sign = _algebraic_sign(denominator.subs(parameter, value))
        # A pole makes this atom false. Set-builder definedness guards remain
        # inside their membership predicate, so its complement can include the
        # pole; only outer arithmetic denominators exclude it problem-wide.
        if denominator_sign == 0:
            return False
        sign = _algebraic_sign(numerator.subs(parameter, value)) * denominator_sign
        return _relation_holds(sp.Integer(sign), constraint["operator"])
    if kind == "not":
        return not _constraint_holds(constraint["children"][0], parameter, value)
    if kind in ("and", "or"):
        truths = [_constraint_holds(child, parameter, value) for child in constraint["children"]]
        return all(truths) if kind == "and" else any(truths)
    raise VerificationGap("verification_incomplete:constraint_predicate")


def _constraint_sources(constraint, parameter):
    sources = []
    for atom in _constraint_atoms(constraint):
        if atom["kind"] == "relation":
            sources.append((atom["expression"], atom["source_ref"], "parameter_condition"))
        elif atom["kind"] == "membership":
            for boundary in _set_boundaries(atom["set"]):
                expression = _sympy_call("boundary_minimal_polynomial", sp.minpoly, boundary, parameter)
                sources.append((expression, atom["source_ref"], "parameter_domain_boundary"))
    return sources


def _predicate_set(points, predicate):
    accepted = []
    for index, (left, right) in enumerate(pairwise([-sp.oo, *points, sp.oo])):
        if predicate(_rational_between(left, right)):
            accepted.append(sp.Interval.open(left, right))
        if index < len(points) and predicate(points[index]):
            accepted.append(sp.FiniteSet(points[index]))
    return sp.Union(*accepted)


def _constraint_set(constraint, parameter):
    if constraint["kind"] == "membership":
        return constraint["set"]
    points, _ = _critical_sources(_constraint_sources(constraint, parameter), parameter)
    return _predicate_set(points, lambda value: _constraint_holds(constraint, parameter, value))


def _denominator_zero_set(expression, parameter):
    numerator, _ = sp.fraction(sp.cancel(expression))
    points, _ = _critical_sources([(numerator, "", "denominator_zero")], parameter)
    return _predicate_set(points, lambda value: _algebraic_sign(numerator.subs(parameter, value)) == 0)


def _extended_compare(left, right):
    if left == right:
        return 0
    if left is -sp.oo or right is sp.oo:
        return -1
    if left is sp.oo or right is -sp.oo:
        return 1
    return _algebraic_sign(left - right)


def _interval_predicate(problem, a, b, c):
    """Independent range certificate for a fixed original parameter value.

    Quadratic continuity, its derivative, and endpoint limits exhaust its
    range on an interval. Excluded endpoints contribute bounds but never
    attained values. No inequality solver or method range is trusted here.
    """
    domain = problem.domain
    if domain is sp.S.EmptySet:
        return problem.quantifier == "∀", {"kind": "empty_quantifier_domain", "domain": math_value(domain),
                                            "quantifier": problem.quantifier}
    leading_sign, slope_sign = _algebraic_sign(a), _algebraic_sign(b)
    candidates = []

    def add(point, attained, kind):
        if point in (-sp.oo, sp.oo):
            sign = leading_sign or (slope_sign if point is sp.oo else -slope_sign)
            value = sp.oo if sign > 0 else -sp.oo if sign < 0 else c
        else:
            value = _algebraic_value(a*point**2 + b*point + c)
        candidates.append({"point": point, "value": value, "attained": attained, "kind": kind})

    if isinstance(domain, sp.FiniteSet):
        for point in domain:
            add(point, True, "domain_point")
    elif leading_sign == 0 and slope_sign == 0:
        # A constant is attained everywhere even on a wholly open interval.
        add(_rational_between(domain.start, domain.end), True, "constant_value")
    else:
        add(domain.start, not domain.left_open, "left_endpoint_limit")
        add(domain.end, not domain.right_open, "right_endpoint_limit")
        if leading_sign:
            vertex = _algebraic_value(-b / (2*a))
            if _contains_exact(domain, vertex):
                add(vertex, True, "stationary_point")

    lower = min((row["value"] for row in candidates), key=cmp_to_key(_extended_compare))
    upper = max((row["value"] for row in candidates), key=cmp_to_key(_extended_compare))
    lower_attained = any(row["attained"] and _extended_compare(row["value"], lower) == 0 for row in candidates)
    upper_attained = any(row["attained"] and _extended_compare(row["value"], upper) == 0 for row in candidates)
    if problem.quantifier == "∀":
        sign = _extended_compare(lower, sp.S.Zero)
        holds = sign > 0 or sign == 0 and (not problem.strict or not lower_attained)
    else:
        sign = _extended_compare(upper, sp.S.Zero)
        holds = sign > 0 or sign == 0 and not problem.strict and upper_attained
    certificate = {
        "kind": "interval_polynomial_range", "quantifier": problem.quantifier,
        "domain": math_value(domain), "strict": problem.strict,
        "coefficients": [math_value(coefficient) for coefficient in (a, b, c)],
        "lower_bound": math_value(lower), "lower_attained": lower_attained,
        "upper_bound": math_value(upper), "upper_attained": upper_attained,
        "candidates": [{**row, "point": math_value(row["point"]), "value": math_value(row["value"])}
                       for row in candidates],
    }
    return holds, certificate


def _point(problem, value):
    evidence = []
    for expression, source in problem.denominators:
        evaluated = sp.cancel(expression.subs(problem.parameter, value))
        holds = evaluated not in (sp.nan, sp.zoo) and _algebraic_sign(evaluated) != 0
        evidence.append({"source_ref": source, "kind": "definedness", "holds": holds,
                         "value": math_value(evaluated)})
        if not holds:
            return False, evidence
    for constraint in problem.constraints:
        holds = _constraint_holds(constraint, problem.parameter, value)
        evidence.append({"source_ref": constraint["source_ref"], "kind": "parameter_constraint", "holds": holds})
        if not holds:
            return False, evidence
    # Prove the original predicate directly at this exact parameter.  A set
    # returned by solve_univariate_inequality may retain unsimplified RootOf
    # endpoints, so structural inequality with Reals must never mean False.
    # This independently constructed square identity uses no method outputs.
    polynomial = sp.Poly(problem.expression.subs(problem.parameter, value), problem.x)
    a, b, c = (_algebraic_value(polynomial.nth(i)) for i in (2, 1, 0))
    if problem.quantifier != "∀" or problem.domain != sp.S.Reals:
        holds, certificate = _interval_predicate(problem, a, b, c)
        evidence.append({"source_ref": problem.main_ref, "kind": "quantified_predicate", "holds": holds,
                         "certificate": certificate})
        return holds, evidence
    leading_sign = _algebraic_sign(a)
    if leading_sign == 0:
        slope_sign = _algebraic_sign(b)
        if slope_sign == 0:
            constant_sign = _algebraic_sign(c)
            holds = constant_sign > 0 if problem.strict else constant_sign >= 0
            certificate = {"kind": "constant_predicate", "leading_coefficient": math_value(a),
                           "linear_coefficient": math_value(b), "constant": math_value(c),
                           "constant_sign": constant_sign, "strict": problem.strict}
            witness, evaluated = sp.S.Zero, c
        else:
            # A nonconstant affine function cannot be positive/nonnegative on
            # the entire real line. Produce a concrete original-input witness.
            witness = _algebraic_value((-c - 1) / b)
            evaluated = _algebraic_value(b * witness + c)
            if _algebraic_sign(evaluated + 1) != 0:
                raise VerificationGap("verification_incomplete:linear_counterexample")
            holds = False
            certificate = {"kind": "nonconstant_linear_counterexample", "leading_coefficient": math_value(a),
                           "linear_coefficient": math_value(b), "slope_sign": slope_sign,
                           "constant": math_value(c), "strict": problem.strict}
        evidence.append({"source_ref": problem.main_ref, "kind": "quantified_predicate", "holds": holds,
                         "certificate": certificate})
        if not holds:
            evidence[-1]["counterexample"] = {"bound_variable": math_value(witness), "value": math_value(evaluated)}
        return holds, evidence
    vertex = _algebraic_value(-b / (2*a))
    minimum = _algebraic_value(c - b**2 / (4*a))
    identity = sp.Poly(bounded_expand(polynomial.as_expr() - a*(problem.x-vertex)**2-minimum), problem.x)
    if any(_algebraic_sign(coefficient) != 0 for coefficient in identity.all_coeffs()):
        raise VerificationGap("verification_incomplete:point_square_identity")
    sign = _algebraic_sign(minimum)
    if leading_sign < 0:
        # The negative quadratic has a negative value sufficiently far from
        # its vertex. This explicit distance satisfies |a|*d² > minimum.
        distance = _algebraic_value((minimum if sign >= 0 else -minimum) + 1 - 1 / a)
        witness = _algebraic_value(vertex + distance)
        evaluated = _algebraic_value(a * distance**2 + minimum)
        if _algebraic_sign(evaluated) >= 0:
            raise VerificationGap("verification_incomplete:negative_quadratic_counterexample")
        holds = False
    else:
        witness, evaluated = vertex, minimum
        holds = sign > 0 if problem.strict else sign >= 0
    evidence.append({"source_ref": problem.main_ref, "kind": "quantified_predicate", "holds": holds,
                     "certificate": {"kind": "positive_quadratic_minimum" if leading_sign > 0 else "negative_quadratic_counterexample",
                                     "identity_verified": True, "leading_sign": leading_sign, "strict": problem.strict,
                                     "leading_coefficient": math_value(a), "vertex": math_value(vertex),
                                     "minimum": math_value(minimum), "minimum_sign": sign}})
    if not holds:
        evidence[-1]["counterexample"] = {"bound_variable": math_value(witness), "value": math_value(evaluated)}
    return holds, evidence


def _compare(a, b):
    return _algebraic_sign(a - b)


def _rational_between(left, right):
    if left is -sp.oo and right is sp.oo:
        return sp.S.Zero
    if left is -sp.oo:
        return sp.floor(right) - 1
    if right is sp.oo:
        return sp.ceiling(left) + 1
    scale = 1
    for _ in range(256):
        sample = (sp.floor(left * scale) + 1) / scale
        if _compare(left, sample) < 0 and _compare(sample, right) < 0:
            return sample
        scale *= 2
    raise VerificationGap("verification_incomplete:rational_isolation")


def _critical(problem):
    parameter, x = problem.parameter, problem.x
    polynomial = sp.Poly(problem.expression, x)
    sources = [(c, problem.main_ref, "coefficient") for c in polynomial.all_coeffs()]
    sources.append((sp.discriminant(polynomial.as_expr(), x), problem.main_ref, "discriminant"))
    endpoint_values = []
    for boundary in _set_boundaries(problem.domain):
        value = bounded_expand(problem.expression.subs(x, boundary))
        endpoint_values.append(value)
        sources.append((value, problem.main_ref, "quantifier_endpoint_value"))
        sources.append((bounded_expand(sp.diff(problem.expression, x).subs(x, boundary)),
                        problem.main_ref, "stationary_point_boundary"))
    if len(endpoint_values) == 2:
        sources.append((endpoint_values[0] - endpoint_values[1], problem.main_ref, "endpoint_value_order"))
    for constraint in problem.constraints:
        sources.extend(_constraint_sources(constraint, parameter))
    sources.extend((d, ref, "original_denominator") for d, ref in problem.denominators)
    return _critical_sources(sources, parameter)


def _critical_sources(sources, parameter):
    """All real roots of rational/algebraic source numerators and denominators."""
    records, roots = [], []
    for expression, source, kind in sources:
        numerator, denominator = sp.fraction(sp.cancel(expression))
        for part, value in (("numerator", numerator), ("denominator", denominator)):
            # Rational input coefficients can become algebraic after substituting
            # an exact interval endpoint. The algebraic-field norm has rational
            # coefficients and contains all real zeros of the original expression.
            # Extra conjugate roots only refine the invariant partition.
            if value.has(sp.CRootOf) or any(coefficient.is_Rational is not True
                                           for coefficient in sp.Poly(value, parameter).all_coeffs()):
                algebraic_poly = _sympy_call("algebraic_endpoint_polynomial", sp.Poly,
                                            value, parameter, extension=True)
                rational_poly = _sympy_call("algebraic_endpoint_norm", algebraic_poly.norm)
                poly = _poly(rational_poly.as_expr(), parameter)
            else:
                poly = _poly(value, parameter)
            real_roots = [] if poly.is_zero or poly.degree() == 0 else _sympy_call("real_roots", poly.real_roots)
            isolation = [] if not real_roots else [
                {"lower": math_value(bounds[0]), "upper": math_value(bounds[1]), "multiplicity": multiplicity}
                for bounds, multiplicity in _sympy_call("root_isolation", poly.intervals)
            ]
            record = {"source_ref": source, "kind": kind, "part": part, "polynomial": math_value(value),
                      "root_polynomial": math_value(poly.as_expr()),
                      "identically_zero": bool(poly.is_zero), "roots": [math_value(r) for r in real_roots],
                      "isolating_intervals": isolation}
            records.append(record)
            roots.extend(real_roots)
    ordered = sorted(roots, key=cmp_to_key(_compare))
    unique = []
    for root in ordered:
        if not unique or _compare(root, unique[-1]):
            unique.append(root)
    return unique, records


def _supported_set(value):
    if value in (sp.S.EmptySet, sp.S.Reals):
        return
    if isinstance(value, sp.Union):
        for part in value.args:
            _supported_set(part)
        return
    if not isinstance(value, (sp.Interval, sp.FiniteSet)):
        raise VerificationGap("verification_incomplete:candidate_set")
    endpoints = value.args[:2] if isinstance(value, sp.Interval) else value.args
    if any(e not in (-sp.oo, sp.oo) and (e.is_real is not True or e.is_algebraic is not True) for e in endpoints):
        raise VerificationGap("verification_incomplete:candidate_endpoint")


def _set_boundaries(value):
    if value in (sp.S.EmptySet, sp.S.Reals):
        return []
    if isinstance(value, sp.FiniteSet):
        return list(value)
    if isinstance(value, sp.Union):
        return [point for part in value.args for point in _set_boundaries(part)]
    if isinstance(value, sp.Interval):
        return [point for point in (value.start, value.end) if point not in (-sp.oo, sp.oo)]
    raise VerificationGap("verification_incomplete:set_comparison")


def _set_mismatch(left, right):
    """Exact equality for supported finite unions, independent of set simplification.

    RootOf and nested-radical spellings can denote the same endpoint without
    SymPy normalizing their symmetric difference.  On the common, exactly
    ordered endpoint partition each set's membership is constant on every open
    cell.  Comparing all cells and singleton endpoints is a complete equality
    proof, after the independent original-predicate proof has been built.
    """
    points = []
    for point in sorted([*_set_boundaries(left), *_set_boundaries(right)], key=cmp_to_key(_compare)):
        if not points or _compare(point, points[-1]) != 0:
            points.append(point)
    for index, (lower, upper) in enumerate(pairwise([-sp.oo, *points, sp.oo])):
        sample = _rational_between(lower, upper)
        if _contains_exact(left, sample) != _contains_exact(right, sample):
            return sample
        if index < len(points) and _contains_exact(left, points[index]) != _contains_exact(right, points[index]):
            return points[index]
    return None


def verify(candidate, target_ref, constraint_context, feasible_set):
    """Prove the entire proposed set by an original-input critical partition."""
    if _source(candidate, target_ref).get("kind") == "find_domain":
        from .function_domain import verify_domain
        return verify_domain(candidate, target_ref, constraint_context, feasible_set)
    if _source(candidate, target_ref).get("kind") == "match_domain":
        from .function_domain import verify_domain_parameter
        return verify_domain_parameter(candidate, target_ref, constraint_context, feasible_set)
    if _source(candidate, target_ref).get("kind") == "find_abstract_domain":
        from .abstract_function_domain import independent_verify

        rebuilt = independent_verify(candidate, target_ref, feasible_set)
        if rebuilt["status"] != "verified":
            return {
                "status": "math_failed",
                "proof": {
                    "kind": "abstract_domain_preimage",
                    "passed": False,
                    "checks": rebuilt["checks"],
                    "expected": rebuilt["expected"],
                    "actual": rebuilt["actual"],
                },
                "diagnostics": rebuilt.get("diagnostics", []),
            }
        return {
            "status": "verified",
            "proof": {
                "kind": "abstract_domain_preimage",
                "passed": True,
                "checks": rebuilt["checks"],
                "expected": rebuilt["expected"],
                "actual": rebuilt["actual"],
                "structure_version": rebuilt["checks"][0].get("structure_version"),
            },
            "diagnostics": [],
        }
    result = {"status": "capability_gap", "proof": {}, "diagnostics": []}
    try:
        problem = read_problem(candidate, target_ref, constraint_context)
        _supported_set(feasible_set)
        points, critical = _critical(problem)
        boundaries = [-sp.oo, *points, sp.oo]
        cells, accepted = [], []
        for i, (left, right) in enumerate(pairwise(boundaries)):
            interval = sp.Interval.open(left, right)
            sample = _rational_between(left, right)
            holds, evidence = _point(problem, sample)
            cells.append({"kind": "open_interval", "domain": math_value(interval), "sample": math_value(sample),
                          "holds": holds, "evidence": evidence})
            if holds:
                accepted.append(interval)
            if i < len(points):
                point = points[i]
                holds, evidence = _point(problem, point)
                cells.append({"kind": "critical_point", "domain": math_value(sp.FiniteSet(point)),
                              "sample": math_value(point), "holds": holds, "evidence": evidence})
                if holds:
                    accepted.append(sp.FiniteSet(point))
        reconstructed = sp.Union(*accepted)
        result["proof"] = {
            "category": ("real-algebraic-rational-coefficients-semialgebraic-constraints/v1"
                         if problem.extended_coefficients_or_constraints
                         else "rational-polynomial-coefficients-quantified-affine/v1"
                         if sp.Poly(problem.expression, problem.x).degree() < 2
                         else "rational-polynomial-coefficients-universal-real-quadratic/v2"
                         if problem.quantifier == "∀" and problem.domain == sp.S.Reals
                         else "rational-polynomial-coefficients-quantified-interval-quadratic/v1"),
            "source_refs": [e["source_ref"] for e in problem.original["entries"]],
            "critical_polynomials": critical,
            "critical_points": [{**math_value(p), "sources": [
                {"source_ref": item["source_ref"], "kind": item["kind"], "part": item["part"]}
                for item in critical if math_value(p) in item["roots"]
            ]} for p in points],
            "invariance": {"proved": True, "reason": "All coefficient, discriminant, endpoint-value, stationary-point boundary, endpoint-order, condition and original-denominator signs are fixed between their complete exact real roots (or rational norm roots for algebraic endpoints); critical points are checked independently for quadratic, affine and constant predicates with the original quantifier, domain and strictness."},
            "cells": cells, "reconstructed_set": math_value(reconstructed), "candidate_set": math_value(feasible_set),
        }
        sample = _set_mismatch(reconstructed, feasible_set)
        if sample is None:
            result["status"] = "verified"
        else:
            holds, evidence = _point(problem, sample)
            included = _contains_exact(feasible_set, sample)
            if holds == included:
                raise VerificationGap("verification_incomplete:set_equivalence")
            result.update(status="math_failed", counterexample={"parameter": math_value(sample),
                          "original_holds": holds, "candidate_includes": included,
                          "reason": "missing_feasible_point" if holds else "extraneous_point", "evidence": evidence})
            result["diagnostics"].append({"code": "verification.set_mismatch", "path": target_ref})
    except ContextMismatch as exc:
        result.update(status="math_failed", diagnostics=[{"code": "constraint_context_mismatch", "message": str(exc), "path": target_ref}])
    except (VerificationGap, NotationError, BasePolynomialError, NotImplementedError) as exc:
        result.update(status="capability_gap", diagnostics=[{
            "code": "verification_incomplete", "message": str(exc), "path": target_ref,
            **_library_exception_details(exc),
        }])
    except (IndexError, ValueError, ZeroDivisionError, TypeError) as exc:
        # Arithmetic overloads can enter library code without an explicit call
        # above. Only a traceback actually crossing SymPy is a computation gap;
        # an error in our own source/partition bookkeeping must not disappear.
        if not _is_sympy_computation_failure(exc):
            raise
        result.update(status="capability_gap", diagnostics=[{
            "code": "verification_incomplete", "message": "sympy_computation_failed:" + type(exc).__name__,
            "path": target_ref, **_library_exception_details(exc),
        }])
    return result


@_sympy_gap_boundary
def endpoint_check(candidate, target_ref, feasible_set):
    """Independent exact boundary evidence, including excluded candidate ends."""
    if _source(candidate, target_ref).get("kind") == "find_domain":
        from .function_domain import domain_endpoints
        return domain_endpoints(candidate, target_ref, feasible_set)
    if _source(candidate, target_ref).get("kind") == "match_domain":
        from .function_domain import domain_parameter_endpoints
        return domain_parameter_endpoints(candidate, target_ref, feasible_set)
    if _source(candidate, target_ref).get("kind") == "find_abstract_domain":
        from .abstract_function_domain import abstract_domain_endpoints

        return abstract_domain_endpoints(candidate, target_ref, feasible_set)
    problem = read_problem(candidate, target_ref)
    _supported_set(feasible_set)
    boundaries = feasible_set.boundary
    if not isinstance(boundaries, sp.FiniteSet) and boundaries != sp.S.EmptySet:
        raise VerificationGap("verification_incomplete:boundary_set")
    rows = []
    for point in sorted(boundaries, key=cmp_to_key(_compare)):
        holds, evidence = _point(problem, point)
        included = _contains_exact(feasible_set, point)
        rows.append({"point": math_value(point), "included": included, "holds": holds,
                     "passed": included == holds, "evidence": evidence})
    return {"status": "passed" if all(r["passed"] for r in rows) else "failed", "points": rows}
