"""Exact, bounded method preconditions over stage-one mathematical features.

Expressions use the same bound notation arithmetic as feature extraction; no
Python/SymPy expression parser evaluates feature strings. These functions are
also usable by execution capabilities without an LLM or a problem identifier.
"""

from dataclasses import dataclass
from functools import lru_cache

import sympy as sp
from sympy.polys.polyerrors import BasePolynomialError

from ...problem_understanding.notation_compile import NotationValidator
from ...problem_understanding.notation_parser import NotationError
from ...problem_understanding.notation_semantics import bounded_expand
from ..stage_one.features import FEATURE_REGISTRY, _Algebra
from .math_values import BOUND_NAMES, latex

_REGISTERED_FEATURES = frozenset(spec.feature_id for spec in FEATURE_REGISTRY)


def math_text(value):
    return sp.sstr(value).replace("**", "^")


class UnknownPremise(ValueError):
    pass


@lru_cache(maxsize=256)
def parse_expression(text, allow_conditions=False):
    """Compile a scalar through the stage-one binding and arithmetic pipeline."""
    report = NotationValidator().validate_root({"facts": [f"({text})=0"]})
    if not report.ok:
        raise UnknownPremise("invalid_expression")
    algebra = _Algebra(report.objects, {})
    value = algebra.expr(report.semantic["facts"][0][1])
    if algebra.conditions and not allow_conditions:
        raise UnknownPremise("conditional_expression")
    return bounded_expand(value)


@dataclass
class FeatureMath:
    features: dict

    def value(self, key):
        if key not in _REGISTERED_FEATURES:
            raise KeyError(f"selection.unregistered_feature:{key}")
        row = self.features.get(key, {})
        # Conditional rows still carry a usable mathematical value; well-
        # definedness provisos stay on the feature for later discharge.
        if row.get("status") not in ("known", "conditional"):
            raise UnknownPremise(f"unknown_feature:{key}")
        return row["value"]

    def _parse(self, text, *, feature_id):
        row = self.features.get(feature_id, {})
        return parse_expression(text, allow_conditions=row.get("status") == "conditional")

    @property
    def x(self):
        names = self.value("bound_vars")
        if len(names) != 1:
            raise UnknownPremise("single_bound_variable_required")
        return sp.Symbol(names[0], real=True)

    @property
    def parameter(self):
        value = self.value("goal")
        if value.get("kind") not in ("find_range", "find_minimum", "find_maximum"):
            raise UnknownPremise("unsupported_goal")
        return sp.Symbol(value["symbol"], real=True)

    @property
    def expression(self):
        value = self.value("normal_form")
        if value["operator"] not in (">", ">=") or value["rhs"] != "0":
            raise UnknownPremise("unsupported_normal_form")
        result = self._parse(value["expression"], feature_id="normal_form")
        if result.free_symbols - {self.x, self.parameter}:
            raise UnknownPremise("additional_free_variables")
        return result

    @property
    def domain(self):
        value = self.value("domain")

        def endpoint(text):
            if text in ("-∞", "-oo"):
                return -sp.oo
            if text in ("∞", "+∞", "oo"):
                return sp.oo
            number = parse_expression(text)
            if number.free_symbols or number.is_real is not True:
                raise UnknownPremise("symbolic_domain")
            return number

        domain = sp.Interval(endpoint(value["lower"]), endpoint(value["upper"]),
                             left_open=not value["left_closed"],
                             right_open=not value["right_closed"])
        if not isinstance(domain, sp.Interval):
            raise UnknownPremise("noninterval_domain")
        return domain


def _result(status, reason, **bindings):
    # Render from the computed objects, never by parsing machine/debug strings.
    mathematical = {key: value for key, value in bindings.items() if isinstance(value, sp.Basic)}
    return {
        "status": status, "reason": reason,
        "bindings": {**bindings, **{key: math_text(value) for key, value in mathematical.items()}},
        "display_bindings": {**bindings, **{key: latex(value) for key, value in mathematical.items()}},
        "evidence": [],
    }


def _solve_set(expression, variable, domain):
    try:
        return sp.solveset(expression, variable, domain=domain)
    except NotImplementedError as exc:
        raise UnknownPremise("set_solver_unsupported") from exc


def _solve_inequality(relation, variable):
    try:
        return sp.solve_univariate_inequality(relation, variable, relational=False)
    except NotImplementedError as exc:
        raise UnknownPremise("inequality_solver_unsupported") from exc


def _polynomial(expression, variable, maximum=2):
    try:
        polynomial = sp.Poly(expression, variable)
    except sp.PolynomialError as exc:
        raise UnknownPremise("nonpolynomial_expression") from exc
    if polynomial.degree() > maximum:
        raise UnknownPremise("polynomial_degree_limit")
    return polynomial


def degenerate_branches(values):
    variable = values.x  # Require the role even for a constant coefficient.
    coefficient = parse_expression(values.value("leading_coeff_in_bound")["expression"])
    parameter = values.parameter
    if coefficient.free_symbols - {parameter}:
        raise UnknownPremise("additional_free_variables")
    _polynomial(coefficient, parameter)
    zero_set = _solve_set(coefficient, parameter, sp.S.Reals)
    if not isinstance(zero_set, (sp.FiniteSet, type(sp.S.EmptySet))) and zero_set != sp.S.Reals:
        raise UnknownPremise("coefficient_zero_set")
    return _result("holds", "coefficient_zero_set_proved", coefficient=coefficient,
                   variable=variable, parameter=parameter, zero_set=zero_set,
                   may_be_zero=zero_set != sp.S.EmptySet)


def separate_parameter(values):
    """Factor parameter-dependent coefficients as a rank-one polynomial."""
    expression, x, parameter = values.expression, values.x, values.parameter
    polynomial = _polynomial(expression, parameter, maximum=4)
    if polynomial.is_zero:
        return None
    powers = [i for i in range(1, max(0, int(polynomial.degree())) + 1) if polynomial.nth(i) != 0]
    if not powers:
        return None
    source = polynomial.nth(powers[-1])
    divisor = _polynomial(source, x).monic().as_expr()
    parameter_part = 0
    for power in powers:
        ratio = sp.cancel(polynomial.nth(power) / divisor)
        if ratio.free_symbols:
            return None
        parameter_part += ratio * parameter ** power
    bound_part = -polynomial.nth(0)
    if bounded_expand(expression - (parameter_part * divisor - bound_part)) != 0:
        raise UnknownPremise("separation_identity")
    return parameter_part, divisor, bound_part


def param_separable(values):
    separated = separate_parameter(values)
    if separated is None:
        return _result("fails", "parameter_coefficients_not_proportional")
    parameter, divisor, bound = separated
    relation = values.value("relation")
    left, right = (parse_expression(relation[side]) for side in ("lhs", "rhs"))
    already_separated = (
        values.parameter in left.free_symbols and values.x not in left.free_symbols
        and values.parameter not in right.free_symbols
        or values.parameter in right.free_symbols and values.x not in right.free_symbols
        and values.parameter not in left.free_symbols
    )
    return _result("holds", "separation_identity_proved", parameter_expression=parameter,
                   divisor=divisor, bound_expression=bound,
                   already_separated=bool(already_separated), requires_division=bool(divisor.free_symbols))


def _witness(domain):
    if isinstance(domain, sp.FiniteSet):
        return min(domain, key=sp.default_sort_key)
    if isinstance(domain, sp.Union):
        return _witness(domain.args[0])
    if not isinstance(domain, sp.Interval):
        raise UnknownPremise("sign_witness")
    if domain.start is -sp.oo and domain.end is sp.oo:
        return sp.S.Zero
    if domain.start is -sp.oo:
        return domain.end - 1
    if domain.end is sp.oo:
        return domain.start + 1
    return (domain.start + domain.end) / 2


def divisor_sign(values):
    separated = separate_parameter(values)
    if separated is None:
        raise UnknownPremise("separation_required")
    _, divisor, _ = separated
    domain, x = values.domain, values.x
    _polynomial(divisor, x)
    positive = _solve_inequality(divisor > 0, x).intersect(domain)
    negative = _solve_inequality(divisor < 0, x).intersect(domain)
    zero = _solve_set(divisor, x, domain)
    if positive == domain or negative == domain:
        return _result("holds", "constant_strict_sign", divisor=divisor,
                       sign="positive" if positive == domain else "negative",
                       domain=domain)
    evidence = []
    for sign, subset in (("positive", positive), ("negative", negative), ("zero", zero)):
        if subset is not sp.S.EmptySet:
            point = _witness(subset)
            evidence.append({"point": math_text(point), "value": math_text(divisor.subs(x, point)),
                             "sign": sign})
    if not evidence:
        raise UnknownPremise("divisor_sign_unproved")
    return {**_result("fails", "divisor_changes_sign_or_vanishes", divisor=divisor,
                      domain=domain), "evidence": evidence}


def extremum_computable(values):
    expression, x = values.expression, values.x
    domain = values.domain
    polynomial = _polynomial(expression, x)
    degree = polynomial.degree()
    return _result("holds", "polynomial_extremum_supported", degree=0 if degree == -sp.oo else int(degree),
                   domain=domain)


def interval_case_split(values):
    polynomial = _polynomial(values.expression, values.x)
    quantifier = values.value("quantifier")
    if quantifier not in ("∀", "∃"):
        raise UnknownPremise("unsupported_quantifier")
    if polynomial.degree() < 2:
        return _result("fails", "linear_extremum_no_vertex")
    coefficient = polynomial.nth(2)
    if coefficient.is_positive is not True and coefficient.is_negative is not True:
        return _result("holds", "leading_coefficient_requires_cases", coefficient=coefficient)
    vertex_extremum = coefficient.is_positive if quantifier == "∀" else coefficient.is_negative
    axis = sp.cancel(-polynomial.nth(1) / (2 * coefficient))
    needs_cases = bool(vertex_extremum and values.parameter in axis.free_symbols and values.domain != sp.S.Reals)
    return _result("holds" if needs_cases else "fails",
                   "parameter_vertex_requires_cases" if needs_cases else "no_parameter_cases",
                   axis=axis, coefficient=coefficient,
                   opening="向上" if coefficient.is_positive else "向下",
                   bound_kind=BOUND_NAMES["inf" if quantifier == "∀" else "sup"],
                   vertex_extremum=bool(vertex_extremum))


def swap_linearity(values):
    polynomial = _polynomial(values.expression, values.x)
    linear = polynomial.degree() <= 1
    return _result("holds" if linear else "fails", "affine_in_bound_variable" if linear else "nonlinear_in_bound_variable",
                   variable=values.x, coefficient=polynomial.nth(1))


CHECKS = {function.__name__: function for function in (
    degenerate_branches, param_separable, divisor_sign, extremum_computable,
    interval_case_split, swap_linearity,
)}


def check_premise(check_id, indexed):
    """Unsupported computation is unknown; only exact counterevidence fails."""
    if check_id not in CHECKS:
        raise ValueError(f"selection.unregistered_premise:{check_id}")
    try:
        result = CHECKS[check_id](FeatureMath(indexed))
    except (UnknownPremise, NotationError, BasePolynomialError) as exc:
        result = _result("unknown", getattr(exc, "code", str(exc)))
    return {"check_id": check_id, **result}
