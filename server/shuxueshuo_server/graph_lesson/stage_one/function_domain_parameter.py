"""Structural admission for Dom(f)=R with sqrt(P) or N/sqrt(P).

P is quadratic with affine parameter coefficients; N is a bounded polynomial.
"""

from copy import deepcopy
from fractions import Fraction

import sympy as sp

from ...problem_understanding.notation_parser import NotationError, definition
from ...problem_understanding.notation_semantics import bounded_expand
from ..domain_expression import expression
from .function_domain import (
    ARGUMENT,
    MAX_INTEGER_EXPONENT,
    MAX_NESTED_POWER,
    MAX_RADICAND_DEGREE,
    _affine,
    _coefficient_budget,
    _input_domain,
    expression_latex,
    source_pointer,
)

VERSION = "domain-parameter-reals-quadratic/v1"
HALFLINE_VERSION = "domain-parameter-halfline-root-ratio/v1"


def _zero():
    return (Fraction(0), Fraction(0))


def _trim(coeffs):
    while len(coeffs) > 1 and coeffs[-1] == _zero():
        coeffs.pop()
    return coeffs


def _add(left, right):
    size = max(len(left), len(right))
    out = []
    for i in range(size):
        c1, p1 = left[i] if i < len(left) else _zero()
        c2, p2 = right[i] if i < len(right) else _zero()
        const, param = c1 + c2, p1 + p2
        _coefficient_budget(const)
        _coefficient_budget(param)
        out.append((const, param))
    return out


def _param_affine(ast, parameter_ref, depth=0):
    """Map AST → polynomial in the bound argument whose coeffs are affine in the parameter.

    Each coefficient is a pair (const, param_coeff) meaning const + param_coeff * parameter.
    """
    if depth > 24:
        raise NotationError("domain.structure_limit")
    if ast == ARGUMENT:
        return [(Fraction(0), Fraction(0)), (Fraction(1), Fraction(0))]
    if ast[0] == "number":
        value = Fraction(ast[1])
        _coefficient_budget(value)
        return [(value, Fraction(0))]
    if ast[0] == "ref" and ast[1] == parameter_ref and ast[2] == "scalar":
        return [(Fraction(0), Fraction(1))]
    if ast[0] == "neg":
        return [(-c, -p) for c, p in _param_affine(ast[1], parameter_ref, depth + 1)]
    if ast[0] == "^":
        if ast[2][0] != "number":
            raise NotationError("domain.parameter_structure_unsupported")
        exponent = Fraction(ast[2][1])
        if exponent.denominator != 1 or exponent < 1:
            raise NotationError("domain.parameter_structure_unsupported")
        exponent = int(exponent)
        if exponent > MAX_RADICAND_DEGREE:
            raise NotationError("domain.parameter_structure_unsupported")
        base = _param_affine(ast[1], parameter_ref, depth + 1)
        # Only allow powers of the argument (or fixed rationals), not of the parameter alone as base
        # that would create higher parameter degree via (a+bk)^n.
        if any(p != 0 for _, p in base) and len(_trim([(c, p) for c, p in base])) > 1:
            raise NotationError("domain.parameter_structure_unsupported")
        if len(_trim([(c, p) for c, p in base])) == 1:
            c0, p0 = base[0]
            if p0 != 0:
                # parameter^n with n>1 is out of first-batch affine-in-parameter coeffs
                if exponent != 1:
                    raise NotationError("domain.parameter_structure_unsupported")
                return [(c0, p0)]
            value = c0**exponent
            _coefficient_budget(value)
            return [(value, Fraction(0))]
        # Pure argument power: (x)^n → degree n with unit leading coeff.
        if base != [(Fraction(0), Fraction(0)), (Fraction(1), Fraction(0))]:
            raise NotationError("domain.parameter_structure_unsupported")
        out = [(Fraction(0), Fraction(0))] * (exponent + 1)
        out[exponent] = (Fraction(1), Fraction(0))
        return out
    if ast[0] in ("+", "-", "*"):
        left = _param_affine(ast[1], parameter_ref, depth + 1)
        right = _param_affine(ast[2], parameter_ref, depth + 1)
        if ast[0] == "+":
            return _add(left, right)
        if ast[0] == "-":
            return _add(left, [(-c, -p) for c, p in right])
        # Product: each coeff is affine; product of two affine-in-parameter terms
        # must not create parameter^2.
        out = [(Fraction(0), Fraction(0))] * (len(left) + len(right) - 1)
        for i, (c1, p1) in enumerate(left):
            for j, (c2, p2) in enumerate(right):
                if p1 != 0 and p2 != 0:
                    raise NotationError("domain.parameter_structure_unsupported")
                const = c1 * c2
                param = c1 * p2 + p1 * c2
                _coefficient_budget(const)
                _coefficient_budget(param)
                cc, pp = out[i + j]
                total_const, total_param = cc + const, pp + param
                _coefficient_budget(total_const)
                _coefficient_budget(total_param)
                out[i + j] = (total_const, total_param)
        return out
    raise NotationError("domain.parameter_structure_unsupported")


def _numerator_poly(ast, parameter_ref, depth=0, power_weight=1, budget=None):
    """Bounded, everywhere-defined polynomial in the argument and parameter.

    Inspect original syntax before any cancellation: 0/x and x^0 are not
    everywhere-defined numerators. Monomial degrees and exact coefficients use
    the same power and coefficient budgets as ordinary domain admission.
    """
    budget = {"nodes": 0, "has_zero_power": False} if budget is None else budget
    budget["nodes"] += 1
    if depth > 24 or budget["nodes"] > 256:
        raise NotationError("domain.structure_limit")

    def visit(child, weight=power_weight):
        return _numerator_poly(child, parameter_ref, depth + 1, weight, budget)

    if ast == ARGUMENT:
        return {(1, 0): Fraction(1)}
    if ast[:2] == ["ref", parameter_ref] and ast[2] == "scalar":
        return {(0, 1): Fraction(1)}
    if ast[0] == "number":
        value = Fraction(ast[1])
        _coefficient_budget(value)
        return {(0, 0): value} if value else {}
    if ast[0] == "neg":
        return {key: -value for key, value in visit(ast[1]).items()}

    def combine(left, right, multiply=False):
        result = {} if multiply else dict(left)
        for key, value in right.items():
            terms = left.items() if multiply else [((0, 0), Fraction(1))]
            for other, factor in terms:
                target = (key[0] + other[0], key[1] + other[1])
                if sum(target) > MAX_NESTED_POWER:
                    raise NotationError("domain.structure_limit")
                combined = result.get(target, Fraction(0)) + value * factor
                _coefficient_budget(combined)
                if combined:
                    result[target] = combined
                else:
                    result.pop(target, None)
        return result

    if ast[0] == "^" and ast[2][0] == "number":
        exponent = Fraction(ast[2][1])
        if exponent.denominator != 1 or not 0 <= exponent <= MAX_INTEGER_EXPONENT:
            raise NotationError("domain.parameter_numerator_unsupported")
        weight = power_weight * max(1, int(exponent))
        if weight > MAX_NESTED_POWER:
            raise NotationError("domain.nested_power_limit")
        base = visit(ast[1], weight)
        if exponent == 0 and (set(base) != {(0, 0)} or not base[(0, 0)]):
            raise NotationError("domain.parameter_numerator_unsupported")
        budget["has_zero_power"] |= exponent == 0
        result = {(0, 0): Fraction(1)}
        for _ in range(int(exponent)):
            result = combine(result, base, multiply=True)
        return result
    if ast[0] in ("+", "-", "*", "/"):
        left = visit(ast[1])
        right = visit(ast[2])
        if ast[0] == "/":
            if set(right) != {(0, 0)} or not right[(0, 0)]:
                raise NotationError("domain.parameter_numerator_unsupported")
            result = {key: value / right[(0, 0)] for key, value in left.items()}
            for value in result.values():
                _coefficient_budget(value)
            return result
        if ast[0] == "-":
            right = {key: -value for key, value in right.items()}
        return combine(left, right, multiply=ast[0] == "*")
    raise NotationError("domain.parameter_numerator_unsupported")


def _inspect_parameter_radicand(ast, parameter_ref):
    """Admit sqrt(P) or N/sqrt(P), with a polynomial numerator and quadratic P."""
    denominator = ast[0] == "/"
    numerator_budget = {"nodes": 0, "has_zero_power": False}
    if denominator:
        _numerator_poly(ast[1], parameter_ref, budget=numerator_budget)
    radical = ast[2] if denominator else ast
    if radical[:2] != ["call", "sqrt"]:
        raise NotationError("domain.parameter_structure_unsupported")
    coeffs = _trim(_param_affine(radical[2], parameter_ref))
    if len(coeffs) - 1 != 2:
        raise NotationError("domain.parameter_structure_unsupported")
    if not any(p != 0 for _, p in coeffs):
        raise NotationError("domain.parameter_missing_in_expression")
    # The original polynomial must be quadratic. Its leading coefficient may
    # vanish at particular parameter values; the discriminant method splits
    # those cases, but does not admit a polynomial that is already linear.
    return {
        "has_radical": True,
        "has_division": denominator,
        "has_zero_power": numerator_budget["has_zero_power"],
        "has_quadratic_condition": True,
    }


def _inspect_parameter_structure(ast, parameter_ref, prescribed):
    """Two admitted M6 source families; each proves its stated domain guard."""
    if prescribed == ["real"]:
        return _inspect_parameter_radicand(ast, parameter_ref)
    if (ast[0] != "/" or ast[1][:2] != ["call", "sqrt"]
            or ast[2][:2] != ["call", "sqrt"]):
        raise NotationError("domain.parameter_halfline_root_ratio_required")
    slope, intercept = _affine(ast[2][2])
    _coefficient_budget(slope)
    _coefficient_budget(intercept)
    if not slope:
        raise NotationError("domain.parameter_nonconstant_affine_denominator_required")
    boundary = -intercept / slope
    _input_domain(prescribed)
    if prescribed[0] != "interval" or prescribed[1:3] != [False, False]:
        raise NotationError("domain.parameter_denominator_domain_mismatch")
    finite, infinite = (prescribed[3], prescribed[4]) if slope > 0 else (prescribed[4], prescribed[3])
    def infinity_sign(node):
        if node[0] == "infinity":
            return node[1] if len(node) > 1 else 1
        if node[0] == "neg" and infinity_sign(node[1]) is not None:
            return -infinity_sign(node[1])
        return None

    if infinity_sign(infinite) != (1 if slope > 0 else -1) or infinity_sign(finite) is not None:
        raise NotationError("domain.parameter_denominator_domain_mismatch")
    finite_slope, finite_value = _affine(finite)
    if finite_slope or finite_value != boundary:
        raise NotationError("domain.parameter_denominator_domain_mismatch")
    budget = {"nodes": 0, "has_zero_power": False}
    coefficients = _numerator_poly(ast[1][2], parameter_ref, budget=budget)
    if (set(coefficients) - {(2, 0), (1, 0), (0, 0), (0, 1)}
            or not coefficients.get((0, 1))):
        raise NotationError("domain.parameter_constant_offset_required")
    # Coefficient cancellation can hide a large expansion in the original
    # syntax. After the structural bounds pass, apply the execution budget to
    # the same power-preserving expression that source_problem will expand.
    variable, parameter = sp.symbols("domain_argument domain_parameter", real=True)
    bounded_expand(expression(ast[1][2], variable, {parameter_ref: parameter}))
    return {
        "has_radical": True, "has_division": True,
        "has_zero_power": budget["has_zero_power"],
        "has_quadratic_condition": bool(coefficients.get((2, 0))),
        "parameter_family": "halfline_root_ratio",
        "structure_version": HALFLINE_VERSION,
    }


def describe_match_domain_goal(report, scope, ancestors, goal_index):
    """Describe one match_domain goal under the first-batch parametric contract."""
    goal = scope["goals"][goal_index]
    if goal["kind"] != "match_domain" or goal["target"][0] != "ref" or goal["target"][2] != "function":
        raise NotationError("domain.function_goal_required")
    parameter = goal.get("parameter")
    if not parameter or parameter[0] != "ref" or parameter[2] != "scalar":
        raise NotationError("domain.parameter_goal_required")
    prescribed = goal.get("domain", ["real"])
    target = goal["target"][1]
    records = [
        record
        for visible in [*ancestors, scope]
        for record in report.scope_facts.get(visible["scope"], [])
    ]
    definitions = [r for r in records if r["value"][:2] == ["function_definition", goal["target"]]]
    if len(definitions) != 1:
        raise NotationError("domain.single_concrete_definition_required")
    record = definitions[0]
    raw = definition(record["source"])
    if raw[0] != "function_definition":
        raise NotationError("domain.concrete_definition_required")
    name, variable = raw[1:3]
    body = record["value"][2]
    objects = {obj["ref"]: obj for obj in report.objects}
    parameter_name = objects[parameter[1]]["name"]
    names = {ref: obj["name"] for ref, obj in objects.items()}
    value = {
        "function_ref": target,
        "function_name": name,
        "variable": variable,
        "source_ref": source_pointer(record["path"]),
        "expression": record["source"].split("=", 1)[1].strip(),
        "expression_latex": expression_latex(body, variable, names=names),
        "expression_ast": deepcopy(body),
        "input_domain_ast": ["real"],
        "input_domain_source_ref": "",
        "prescribed_domain_ast": deepcopy(prescribed),
        "parameter": parameter_name,
        "parameter_ref": parameter[1],
        "task": "match_domain",
        "structure_version": VERSION,
        "structure_supported": False,
        "reason": "",
        "has_radical": False,
        "has_division": False,
        "has_zero_power": False,
        "has_quadratic_condition": False,
    }
    try:
        if any(visible.get("uncertainties") for visible in [*ancestors, scope]):
            raise NotationError("domain.unresolved_source")
        if any(r is not record for r in records):
            raise NotationError("domain.additional_conditions_unsupported")
        _input_domain(prescribed)
        counts = _inspect_parameter_structure(body, parameter[1], prescribed)
        value.update(structure_supported=True, **counts)
    except (NotationError, ValueError, ZeroDivisionError) as exc:
        value["reason"] = getattr(exc, "code", "domain.invalid_exact_arithmetic")
    return value


def inspect_match_domain_target(candidate, target_ref):
    """Recompute match_domain admission from the candidate source."""
    from ...problem_understanding.notation_compile import NotationValidator
    from . import contracts

    report = NotationValidator().validate_root(candidate.get("root"), contracts.schema()["$defs"])
    if not report.ok:
        raise NotationError("domain.invalid_candidate")

    def visit(scope, ancestors=()):
        for index, goal in enumerate(scope.get("goals", ())):
            pointer = f"{source_pointer(scope['scope'])}/goals/{index}"
            if pointer == target_ref:
                return describe_match_domain_goal(report, scope, ancestors, index)
        for child in scope.get("children", ()):
            found = visit(child, (*ancestors, scope))
            if found is not None:
                return found
        return None

    value = visit(report.semantic)
    if value is None:
        raise NotationError("domain.target_missing")
    return value
