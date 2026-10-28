"""Structural admission for batch-1 abstract-function domain goals.

Known form must be the identity call ``f(x)`` with an exact fixed domain.
The target argument must be an affine expression in a single outer variable.
"""

from copy import deepcopy
from fractions import Fraction

from ...problem_understanding.notation_compile import NotationValidator
from ...problem_understanding.notation_parser import NotationError
from . import contracts
from .function_domain import (
    ARGUMENT,
    _affine,
    _input_domain,
    expression_latex,
    source_pointer,
)

VERSION = "abstract-function-domain-identity-affine/v1"


def _rewrite_argument(ast, variable_ref):
    """Map the outer variable ref onto the shared ARGUMENT token for affine checks."""
    if not isinstance(ast, list) or not ast:
        return ast
    if ast[0] == "ref" and ast[1] == variable_ref:
        return deepcopy(ARGUMENT)
    return [ast[0], *(_rewrite_argument(child, variable_ref) for child in ast[1:])]


def _outer_variable(argument, *, constant_default=None):
    refs = []

    def visit(ast):
        if not isinstance(ast, list) or not ast:
            return
        if ast[0] == "ref" and ast[2] == "scalar":
            refs.append(ast[1])
            return
        for child in ast[1:]:
            visit(child)

    visit(argument)
    names = sorted(set(refs))
    if not names and constant_default is not None:
        return constant_default
    if len(names) != 1:
        raise NotationError("abstract_domain.single_outer_variable_required")
    return names[0]


def _affine_argument(argument, variable_ref):
    rewritten = _rewrite_argument(argument, variable_ref)
    slope, intercept = _affine(rewritten)
    return slope, intercept, rewritten


def describe_abstract_domain_goal(report, scope, ancestors, goal_index):
    goal = scope["goals"][goal_index]
    if goal["kind"] != "find_abstract_domain":
        raise NotationError("abstract_domain.goal_required")
    scope_ref = source_pointer(scope["scope"])
    target_ref = f"{scope_ref}/goals/{goal_index}"
    known = goal["known_call"]
    target = goal["target"]
    domain = goal["known_domain"]
    if known[1][0] != "ref" or known[1][2] != "function":
        raise NotationError("abstract_domain.function_call_required")
    function_name = known[1][1].rsplit(":", 1)[-1]
    value = {
        "kind": "find_abstract_domain",
        "function_name": function_name,
        "function_ref": deepcopy(known[1]),
        "known_call_ast": deepcopy(known),
        "known_argument_ast": deepcopy(known[2]),
        "known_domain_ast": deepcopy(domain),
        "known_strength": goal["strength"],
        "target_call_ast": deepcopy(target),
        "target_argument_ast": deepcopy(target[2]),
        "outer_domain_ast": deepcopy(goal.get("input_domain", ["real"])),
        "has_outer_domain": "input_domain" in goal,
        "source_ref": target_ref,
        "known_call_source_ref": f"{target_ref}/known_call",
        "known_domain_source_ref": f"{target_ref}/known_domain",
        "target_call_source_ref": f"{target_ref}/target_call",
        "structure_supported": False,
        "reason": "",
        "structure_version": VERSION,
        "known_form": "",
        "target_slope": None,
        "target_intercept": None,
        "variable": "",
        "known_variable": "",
        "known_argument_latex": "",
        "target_argument_latex": "",
        "input_range_latex": "",
    }
    try:
        visible = [*ancestors, scope]
        if any(item.get("uncertainties") for item in visible):
            raise NotationError("abstract_domain.unresolved_source")
        if goal["strength"] != "exact":
            raise NotationError("abstract_domain.exact_strength_required")
        if any(report.scope_facts.get(item["scope"]) for item in visible):
            raise NotationError("abstract_domain.additional_conditions_unsupported")
        _input_domain(domain)
        _input_domain(value["outer_domain_ast"])
        # The known call's dummy argument and the target's outer variable are
        # independent: f(t) and f(2*x-1) still refer to the same function.
        known_var = _outer_variable(known[2])
        if known[2] != ["ref", known_var, "scalar"]:
            raise NotationError("abstract_domain.identity_known_form_required")
        target_var = _outer_variable(target[2], constant_default=known_var)
        slope, intercept, rewritten = _affine_argument(target[2], target_var)
        # Reject non-rational encoded coeffs that somehow passed.
        Fraction(slope)
        Fraction(intercept)
        variable_name = target_var.rsplit(":", 1)[-1]
        known_variable_name = known_var.rsplit(":", 1)[-1]
        value.update(
            structure_supported=True,
            known_form="identity",
            target_slope=str(slope),
            target_intercept=str(intercept),
            variable=variable_name,
            known_variable=known_variable_name,
            known_argument_latex=expression_latex(ARGUMENT, known_variable_name),
            target_argument_latex=expression_latex(rewritten, variable_name),
            input_range_ready=True,
        )
    except (NotationError, ValueError, ZeroDivisionError, TypeError) as exc:
        value["reason"] = getattr(exc, "code", "abstract_domain.invalid_structure")
    return value


def inspect_abstract_domain_target(candidate, target_ref):
    report = NotationValidator().validate_root(candidate.get("root"), contracts.schema()["$defs"])
    if not report.ok:
        raise NotationError("abstract_domain.invalid_candidate")

    def visit(scope, ancestors=()):
        for index, _ in enumerate(scope["goals"]):
            if f"{source_pointer(scope['scope'])}/goals/{index}" == target_ref:
                return describe_abstract_domain_goal(report, scope, ancestors, index)
        for child in scope["children"]:
            found = visit(child, (*ancestors, scope))
            if found is not None:
                return found
        return None

    result = visit(report.semantic)
    if result is None:
        raise NotationError("abstract_domain.unknown_target")
    return result
