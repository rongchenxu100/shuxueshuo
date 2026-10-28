"""Structural admission for exact abstract-function domain goals.

Known form is an identity or invertible rational affine call with an exact domain.
The target argument and any concrete denominator share one outer variable.
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

VERSION = "abstract-function-domain-mixed-and-parameter/v4"


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


def _target_parts(target):
    """Allow one abstract call, optionally over an affine concrete denominator."""
    calls = []

    def visit(ast):
        if not isinstance(ast, list) or not ast:
            return
        if ast[0] == "function_call":
            calls.append(ast)
        for child in ast[1:]:
            visit(child)

    visit(target)
    if len(calls) != 1:
        raise NotationError("abstract_domain.single_abstract_call_required")
    if target[0] == "function_call":
        return target, "plain", None
    if target[0] == "/" and target[1][0] == "function_call":
        denominator = target[2]
        form = "sqrt_affine_denominator" if denominator[:2] == ["call", "sqrt"] else "affine_denominator"
        return target[1], form, denominator
    raise NotationError("abstract_domain.target_structure_unsupported")


def _target_latex(target, variable):
    """Render the source tree without expanding or simplifying the abstract call."""
    labels = {}

    def substitute(ast):
        if not isinstance(ast, list) or not ast:
            return ast
        if ast[0] == "function_call":
            key = f"abstract_call_{len(labels)}"
            name = ast[1][1].rsplit(":", 1)[-1]
            labels[key] = f"{name}({expression_latex(ast[2], variable)})"
            return ["ref", key, "scalar"]
        return [ast[0], *(substitute(child) for child in ast[1:])]

    return expression_latex(substitute(target), variable, names=labels)


def describe_abstract_domain_goal(report, scope, ancestors, goal_index):
    goal = scope["goals"][goal_index]
    if goal['kind'] == 'find_abstract_domain_parameter':
        from .abstract_domain_parameter import describe_abstract_domain_parameter

        return describe_abstract_domain_parameter(report, scope, ancestors, goal_index)
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
        "target_argument_ast": [],
        "target_form": None,
        "target_latex": "",
        "concrete_denominator_ast": None,
        "concrete_denominator_latex": "",
        "denominator_slope": None,
        "denominator_intercept": None,
        "denominator_ast_path": [],
        "outer_domain_ast": deepcopy(goal.get("input_domain", ["real"])),
        "has_outer_domain": "input_domain" in goal,
        "source_ref": target_ref,
        "known_call_source_ref": f"{target_ref}/known_call",
        "known_domain_source_ref": f"{target_ref}/known_domain",
        "target_call_source_ref": f"{target_ref}/target_call",
        "structure_supported": False,
        "reason": "",
        "structure_version": VERSION,
        "known_form": None,
        "known_slope": None,
        "known_intercept": None,
        "target_slope": None,
        "target_intercept": None,
        "variable": "",
        "known_variable": "",
        "known_argument_latex": "",
        "target_argument_latex": "",
        "input_range_latex": "",
    }
    # A stated output range belongs to the same abstract function, but is not
    # an input-domain restriction. Keep its original typed source as evidence.
    if "known_range" in goal:
        value["known_range_ast"] = deepcopy(goal["known_range"])
        value["known_range_source_ref"] = f"{target_ref}/known_range"
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
        target_call, target_form, denominator = _target_parts(target)
        # The known call's dummy argument and the target's outer variable are
        # independent: f(t) and f(2*x-1) still refer to the same function.
        known_var = _outer_variable(known[2])
        known_slope, known_intercept, known_rewritten = _affine_argument(known[2], known_var)
        if known_slope == 0:
            raise NotationError("abstract_domain.nonzero_known_slope_required")
        target_var = _outer_variable(target, constant_default=known_var)
        slope, intercept, rewritten = _affine_argument(target_call[2], target_var)
        denominator_slope = denominator_intercept = None
        if denominator is not None:
            base = denominator[2] if target_form == "sqrt_affine_denominator" else denominator
            denominator_slope, denominator_intercept, _ = _affine_argument(base, target_var)
            if denominator_slope == 0 and (
                    denominator_intercept == 0
                    or (target_form == "sqrt_affine_denominator" and denominator_intercept < 0)):
                raise NotationError("abstract_domain.invalid_constant_denominator")
        # Reject non-rational encoded coeffs that somehow passed.
        Fraction(known_slope)
        Fraction(known_intercept)
        Fraction(slope)
        Fraction(intercept)
        variable_name = target_var.rsplit(":", 1)[-1]
        known_variable_name = known_var.rsplit(":", 1)[-1]
        known_identity = known[2] == ["ref", known_var, "scalar"]
        value.update(
            structure_supported=True,
            known_form="identity" if known_identity else "affine",
            known_slope=str(known_slope),
            known_intercept=str(known_intercept),
            target_slope=str(slope),
            target_intercept=str(intercept),
            target_argument_ast=deepcopy(target_call[2]),
            target_form=target_form,
            target_latex=_target_latex(target, variable_name),
            concrete_denominator_ast=deepcopy(denominator),
            concrete_denominator_latex=expression_latex(denominator, variable_name) if denominator is not None else "",
            denominator_slope=str(denominator_slope) if denominator is not None else None,
            denominator_intercept=str(denominator_intercept) if denominator is not None else None,
            denominator_ast_path=[2] if denominator is not None else [],
            variable=variable_name,
            known_variable=known_variable_name,
            known_argument_latex=expression_latex(known_rewritten, known_variable_name),
            target_argument_latex=expression_latex(rewritten, variable_name),
            input_range_ready=known_identity,
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
