"""Read a concrete function's original input syntax without solving its domain.

Both recognition and execution admission use this bounded structural contract.
The AST is never simplified: a cancelled divisor still has its own position.
"""

import re
from copy import deepcopy
from fractions import Fraction

from ...problem_understanding.notation_parser import NotationError, definition

VERSION = "fixed-affine-function-domain/v2"
ARGUMENT = ["bound", "function_argument"]
# Match the canonical notation service's existing single-exponent bound.
MAX_INTEGER_EXPONENT = 12
MAX_NESTED_POWER = 64


def source_pointer(path):
    path = re.sub(r"^r(?=\.|$)", "/root", path)
    path = re.sub(r"\.c(\d+)", r"/children/\1", path)
    return re.sub(r"\[(\d+)\]", r"/\1", path.replace(".", "/"))


def _affine(ast, depth=0):
    """Exact rational slope/intercept; reject symbolic coefficients and holes."""
    if depth > 24:
        raise NotationError("domain.structure_limit")
    if ast == ARGUMENT:
        return Fraction(1), Fraction(0)
    if ast[0] == "number":
        value = Fraction(ast[1])
        if max(value.numerator.bit_length(), value.denominator.bit_length()) > 128:
            raise NotationError("domain.coefficient_limit")
        return Fraction(0), value
    if ast[0] == "neg":
        a, b = _affine(ast[1], depth + 1)
        return -a, -b
    if ast[0] in ("+", "-", "*", "/"):
        a, b = _affine(ast[1], depth + 1)
        c, d = _affine(ast[2], depth + 1)
        if ast[0] == "+":
            return a + c, b + d
        if ast[0] == "-":
            return a - c, b - d
        if ast[0] == "*" and not a * c:
            return a * d + b * c, b * d
        if ast[0] == "/" and not c and d:
            return a / d, b / d
    raise NotationError("domain.fixed_affine_condition_required")


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
    counts = {"nodes": 0, "has_radical": False, "has_division": False, "has_zero_power": False}

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
            _affine(value[2])
            walk(value[2], depth + 1, power_weight)
            return
        if kind == "/":
            counts["has_division"] = True
            divisor = value[2]
            if divisor[:2] == ["call", "sqrt"]:
                _affine(divisor[2])
            else:
                _affine(divisor)
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


def expression_latex(ast, variable):
    """Display the source tree, preserving every radical and division node."""
    if ast == ARGUMENT:
        return variable
    if ast[0] == "number":
        return ast[1]
    if ast[0] == "neg":
        return r"-\left(" + expression_latex(ast[1], variable) + r"\right)"
    if ast[:2] == ["call", "sqrt"]:
        return r"\sqrt{" + expression_latex(ast[2], variable) + "}"
    if ast[0] == "/":
        return r"\frac{" + expression_latex(ast[1], variable) + "}{" + expression_latex(ast[2], variable) + "}"
    if ast[0] == "^":
        return r"\left(" + expression_latex(ast[1], variable) + r"\right)^{" + expression_latex(ast[2], variable) + "}"
    if ast[0] in ("+", "-", "*"):
        op = r"\cdot " if ast[0] == "*" else ast[0]
        return r"\left(" + expression_latex(ast[1], variable) + op + expression_latex(ast[2], variable) + r"\right)"
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
        "has_zero_power": False,
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
                                                ("has_radical", "has_division", "has_zero_power")})
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
