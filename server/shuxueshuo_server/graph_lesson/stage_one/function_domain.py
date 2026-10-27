"""Read a concrete function's original input syntax without solving its domain.

Both recognition and execution admission use this bounded structural contract.
The AST is never simplified: a cancelled divisor still has its own position.
"""

import re
from copy import deepcopy
from fractions import Fraction
from math import isqrt

from ...problem_understanding.notation_parser import NotationError, definition

VERSION = "fixed-affine-function-domain/v3"
ARGUMENT = ["bound", "function_argument"]
# Match the canonical notation service's existing single-exponent bound.
MAX_INTEGER_EXPONENT = 12
MAX_NESTED_POWER = 64
MAX_RADICAND_DEGREE = 2
MAX_COEFFICIENT_BITS = 128


def source_pointer(path):
    path = re.sub(r"^r(?=\.|$)", "/root", path)
    path = re.sub(r"\.c(\d+)", r"/children/\1", path)
    return re.sub(r"\[(\d+)\]", r"/\1", path.replace(".", "/"))


def _trim_coeffs(coeffs):
    while len(coeffs) > 1 and coeffs[-1] == 0:
        coeffs.pop()
    return coeffs


def _add_coeffs(left, right):
    size = max(len(left), len(right))
    return [
        (left[i] if i < len(left) else Fraction(0))
        + (right[i] if i < len(right) else Fraction(0))
        for i in range(size)
    ]


def _mul_coeffs(left, right):
    out = [Fraction(0)] * (len(left) + len(right) - 1)
    for i, a in enumerate(left):
        for j, b in enumerate(right):
            out[i + j] += a * b
    return out


def _coefficient_budget(value):
    if max(value.numerator.bit_length(), value.denominator.bit_length()) > MAX_COEFFICIENT_BITS:
        raise NotationError("domain.coefficient_limit")


def _perfect_square(value):
    if value < 0:
        return False
    root = isqrt(value)
    return root * root == value


def _rational_root_radicand(coeffs):
    """Degree ≤2 radicands must have rational real roots when the discriminant is positive.

    Irrational endpoints break interactive set checks and were incorrectly verified
    when structural equality missed algebraic zeros.
    """
    coeffs = _trim_coeffs(list(coeffs))
    if len(coeffs) - 1 <= 1:
        return True
    c, b, a = (coeffs + [Fraction(0), Fraction(0)])[:3]
    disc = b * b - 4 * a * c
    if disc < 0:
        return True
    if disc == 0:
        return True
    return _perfect_square(disc.numerator) and _perfect_square(disc.denominator)


def _fixed_poly(ast, max_degree=1, depth=0):
    """Exact rational univariate polynomial coeffs in ARGUMENT; low to high degree."""
    if depth > 24:
        raise NotationError("domain.structure_limit")
    if ast == ARGUMENT:
        coeffs = [Fraction(0), Fraction(1)]
    elif ast[0] == "number":
        value = Fraction(ast[1])
        _coefficient_budget(value)
        coeffs = [value]
    elif ast[0] == "neg":
        coeffs = [-c for c in _fixed_poly(ast[1], max_degree, depth + 1)]
    elif ast[0] == "^":
        # Positive integer powers only; zero powers stay outside condition polynomials.
        exponent = _integer_exponent(ast[2])
        if exponent == 0:
            raise NotationError("domain.fixed_affine_condition_required")
        base = _fixed_poly(ast[1], max_degree, depth + 1)
        base_degree = len(_trim_coeffs(list(base))) - 1
        if base_degree * exponent > max_degree:
            raise NotationError("domain.fixed_affine_condition_required")
        if base_degree == 0:
            value = base[0] ** exponent
            _coefficient_budget(value)
            coeffs = [value]
        else:
            coeffs = [Fraction(1)]
            for _ in range(exponent):
                coeffs = _mul_coeffs(coeffs, base)
                coeffs = _trim_coeffs(coeffs)
                if any(
                    max(c.numerator.bit_length(), c.denominator.bit_length()) > MAX_COEFFICIENT_BITS
                    for c in coeffs
                ):
                    raise NotationError("domain.coefficient_limit")
    elif ast[0] in ("+", "-", "*", "/"):
        left = _fixed_poly(ast[1], max_degree, depth + 1)
        right = _fixed_poly(ast[2], max_degree, depth + 1)
        if ast[0] == "+":
            coeffs = _add_coeffs(left, right)
        elif ast[0] == "-":
            coeffs = _add_coeffs(left, [-c for c in right])
        elif ast[0] == "*":
            coeffs = _mul_coeffs(left, right)
        else:
            right = _trim_coeffs(list(right))
            if len(right) != 1 or right[0] == 0:
                raise NotationError("domain.fixed_affine_condition_required")
            coeffs = [c / right[0] for c in left]
    else:
        raise NotationError("domain.fixed_affine_condition_required")
    coeffs = _trim_coeffs(coeffs)
    if len(coeffs) - 1 > max_degree:
        raise NotationError("domain.fixed_affine_condition_required")
    return coeffs


def _affine(ast, depth=0):
    """Exact rational slope/intercept; reject symbolic coefficients and holes."""
    coeffs = _fixed_poly(ast, max_degree=1, depth=depth)
    while len(coeffs) < 2:
        coeffs.append(Fraction(0))
    return coeffs[1], coeffs[0]


def _require_nonzero_expression(ast, depth=0):
    """Divisors must decompose into affine, zero-power, or sqrt(poly≤2) factors."""
    if depth > 24:
        raise NotationError("domain.structure_limit")
    if ast[:2] == ["call", "sqrt"]:
        coeffs = _fixed_poly(ast[2], max_degree=MAX_RADICAND_DEGREE, depth=depth + 1)
        if not _rational_root_radicand(coeffs):
            raise NotationError("domain.fixed_affine_condition_required")
        return
    if ast[0] == "*":
        _require_nonzero_expression(ast[1], depth + 1)
        _require_nonzero_expression(ast[2], depth + 1)
        return
    if ast[0] == "^" and _integer_exponent(ast[2]) == 0:
        _affine(ast[1], depth + 1)
        return
    _affine(ast, depth + 1)


def _integer_exponent(ast):
    """A bounded literal integer, never an expression to simplify or evaluate."""
    if ast[0] != "number":
        raise NotationError("domain.fixed_nonnegative_integer_exponent_required")
    value = Fraction(ast[1])
    if value.denominator != 1 or value < 0:
        raise NotationError("domain.fixed_nonnegative_integer_exponent_required")
    if value > MAX_INTEGER_EXPONENT:
        raise NotationError("domain.integer_exponent_limit")
    return int(value)


def _inspect_expression(ast):
    counts = {
        "nodes": 0,
        "has_radical": False,
        "has_division": False,
        "has_zero_power": False,
        "has_quadratic_condition": False,
    }

    def walk(value, depth=0, power_weight=1):
        counts["nodes"] += 1
        if counts["nodes"] > 256 or depth > 24:
            raise NotationError("domain.structure_limit")
        kind = value[0]
        if value == ARGUMENT or kind == "number":
            _affine(value)
            return
        if kind == "neg":
            walk(value[1], depth + 1, power_weight)
            return
        if kind in ("+", "-", "*"):
            walk(value[1], depth + 1, power_weight)
            walk(value[2], depth + 1, power_weight)
            return
        if kind == "^":
            exponent = _integer_exponent(value[2])
            if exponent == 0:
                # Only the zero power adds a new nonzero condition, whose
                # expression must stay within the existing affine solver.
                _affine(value[1])
                counts["has_zero_power"] = True
            weight = power_weight * max(1, exponent)
            if weight > MAX_NESTED_POWER:
                raise NotationError("domain.nested_power_limit")
            walk(value[1], depth + 1, weight)
            walk(value[2], depth + 1, power_weight)
            return
        if kind == "call" and value[1] == "sqrt":
            counts["has_radical"] = True
            coeffs = _fixed_poly(value[2], max_degree=MAX_RADICAND_DEGREE)
            if not _rational_root_radicand(coeffs):
                raise NotationError("domain.fixed_affine_condition_required")
            if len(coeffs) - 1 == 2:
                # Radicand ≥ 0 becomes a unary quadratic inequality at solve time.
                counts["has_quadratic_condition"] = True
            walk(value[2], depth + 1, power_weight)
            return
        if kind == "/":
            counts["has_division"] = True
            divisor = value[2]
            _require_nonzero_expression(divisor)
            walk(value[1], depth + 1, power_weight)
            walk(divisor, depth + 1, power_weight)
            return
        raise NotationError("domain.unsupported_expression", kind)

    walk(ast)
    return counts


def _input_domain(ast):
    if ast == ["real"]:
        return
    if ast[0] != "interval":
        raise NotationError("domain.explicit_interval_required")
    for endpoint, closed in zip(ast[3:], ast[1:3], strict=True):
        if endpoint[0] == "infinity" or endpoint == ["neg", ["infinity"]]:
            if closed:
                raise NotationError("domain.infinity_must_be_open")
            continue
        slope, _ = _affine(endpoint)
        if slope:
            raise NotationError("domain.fixed_interval_required")


# Display-only precedence; never changes the AST or admission.
_PREC_SUM = 1
_PREC_PROD = 2
_PREC_POW = 3
_PREC_ATOM = 4


def expression_latex(ast, variable, parent=_PREC_SUM, names=None):
    """Readable LaTeX for the source tree; parentheses follow precedence only."""
    names = names or {}
    if ast == ARGUMENT:
        return variable
    if ast[0] == "number":
        return ast[1]
    if ast[0] == "ref":
        return names.get(ast[1], ast[1].rsplit(":", 1)[-1])
    if ast[0] == "neg":
        body = "-" + expression_latex(ast[1], variable, _PREC_POW, names)
        return f"({body})" if parent > _PREC_SUM else body
    if ast[:2] == ["call", "sqrt"]:
        return r"\sqrt{" + expression_latex(ast[2], variable, _PREC_SUM, names) + "}"
    if ast[0] == "/":
        return (
            r"\frac{"
            + expression_latex(ast[1], variable, _PREC_SUM, names)
            + "}{"
            + expression_latex(ast[2], variable, _PREC_SUM, names)
            + "}"
        )
    if ast[0] == "^":
        base = expression_latex(ast[1], variable, _PREC_POW + 1, names)
        expo = expression_latex(ast[2], variable, _PREC_SUM, names)
        body = f"{base}^{{{expo}}}"
        return f"({body})" if parent > _PREC_POW else body
    if ast[0] in ("+", "-", "*"):
        prec = _PREC_PROD if ast[0] == "*" else _PREC_SUM
        # Left-associative: the right child of - needs a stricter bind so
        # a-(b-c) keeps parentheses without wrapping every atom.
        left = expression_latex(ast[1], variable, prec, names)
        right = expression_latex(ast[2], variable, prec + (0 if ast[0] == "+" else 1), names)
        op = r"\cdot " if ast[0] == "*" else ast[0]
        body = left + op + right
        return f"({body})" if parent > prec else body
    # Unsupported syntax is still represented by the original expression text;
    # it never gains a fabricated display or becomes admissible via rendering.
    return ""


def describe_domain_goal(report, scope, ancestors, goal_index):
    """Describe one compiled goal and prove only its accepted syntax boundary.

    ``source_ref`` addresses the original definition string; ``expression_ast``
    is that definition's body. A condition location is this source plus its
    integer path within the body, not a position in a simplified expression.
    """
    goal = scope["goals"][goal_index]
    if goal["kind"] != "find_domain" or goal["target"][0] != "ref" or goal["target"][2] != "function":
        raise NotationError("domain.function_goal_required")
    target = goal["target"][1]
    records = [record for visible in [*ancestors, scope]
               for record in report.scope_facts.get(visible["scope"], [])]
    definitions = [r for r in records if r["value"][:2] == ["function_definition", goal["target"]]]
    if len(definitions) != 1:
        raise NotationError("domain.single_concrete_definition_required")
    record = definitions[0]
    raw = definition(record["source"])
    if raw[0] != "function_definition":
        raise NotationError("domain.concrete_definition_required")
    name, variable = raw[1:3]
    body = record["value"][2]
    scope_ref = source_pointer(scope["scope"])
    target_ref = f"{scope_ref}/goals/{goal_index}"
    domain = goal.get("input_domain", ["real"])
    value = {
        "function_ref": target, "function_name": name, "variable": variable,
        "source_ref": source_pointer(record["path"]),
        "expression": record["source"].split("=", 1)[1].strip(),
        "expression_latex": expression_latex(body, variable),
        "expression_ast": deepcopy(body), "input_domain_ast": deepcopy(domain),
        "input_domain_source_ref": target_ref + "/input_domain" if "input_domain" in goal else "",
        "structure_supported": False, "reason": "", "has_radical": False, "has_division": False,
        "has_zero_power": False, "has_quadratic_condition": False,
    }
    try:
        if any(visible.get("uncertainties") for visible in [*ancestors, scope]):
            raise NotationError("domain.unresolved_source")
        # Do not silently discard a parameter constraint, relation, modelling
        # assumption or a second definition when returning a full input set.
        if any(r is not record for r in records):
            raise NotationError("domain.additional_conditions_unsupported")
        counts = _inspect_expression(body)
        _input_domain(domain)
        value.update(structure_supported=True, **{key: counts[key] for key in
                                                ("has_radical", "has_division", "has_zero_power",
                                                 "has_quadratic_condition")})
    except (NotationError, ValueError, ZeroDivisionError) as exc:
        value["reason"] = getattr(exc, "code", "domain.invalid_exact_arithmetic")
    return value


def inspect_domain_target(candidate, target_ref):
    """Recompute admission from candidate source; never trust supplied features."""
    from ...problem_understanding.notation_compile import NotationValidator
    from . import contracts

    report = NotationValidator().validate_root(candidate.get("root"), contracts.schema()["$defs"])
    if not report.ok:
        raise NotationError("domain.invalid_candidate")

    def visit(scope, ancestors=()):
        for index, _ in enumerate(scope["goals"]):
            if f"{source_pointer(scope['scope'])}/goals/{index}" == target_ref:
                return describe_domain_goal(report, scope, ancestors, index)
        for child in scope["children"]:
            found = visit(child, (*ancestors, scope))
            if found is not None:
                return found
        return None

    result = visit(report.semantic)
    if result is None:
        raise NotationError("domain.unknown_target")
    return result
