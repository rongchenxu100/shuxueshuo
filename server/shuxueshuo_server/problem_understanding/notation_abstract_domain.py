"""Compile abstract-function domain goals without inventing a concrete body.

Batch-1 known form is the identity call ``f(x)`` with an exact declared domain.
The target is a same-name call whose argument is an affine expression in the
outer variable. No solving happens here.
"""

from .notation_compile import Report, Scope, typecheck
from .notation_parser import NotationError, clean, parse


def _pointer(path):
    from ..graph_lesson.stage_one.function_domain import source_pointer

    return source_pointer(path)


def _domain_ast(env, text, path):
    domain = env.bind(parse(text))
    if domain[0] == "tuple":
        domain = ["interval", False, False, *domain[1:]]
    if typecheck(domain) not in ("domain", "set"):
        raise NotationError("abstract_domain.declared_domain_required", path=path)
    return domain


def _bind_call(env, text, path, *, introduce_function=False):
    raw = parse(clean(text))
    if raw[0] != "call" or len(raw) != 3:
        raise NotationError("abstract_domain.function_call_required", path=path)
    name, argument = raw[1], raw[2]
    if introduce_function:
        env.declare(name, "function", local=True)
        # Placeholder identity only gates call binding; it is never a concrete body.
        env.functions[name] = ["function_definition", name, "_", ["number", "0"]]
    if name not in env.functions:
        raise NotationError("abstract_domain.unknown_function", path=path)
    # Free names in the argument become outer scalars for this goal.
    def declare_names(ast):
        if not isinstance(ast, list) or not ast:
            return
        if ast[0] == "name":
            env.declare(ast[1], "scalar")
            return
        for child in ast[1:]:
            declare_names(child)

    declare_names(argument)
    bound = env.bind(raw)
    if bound[0] != "function_call":
        raise NotationError("abstract_domain.function_call_required", path=path)
    return bound


def compile_abstract_domain(goal, path):
    """Return a bound abstract-domain goal; pointers stay candidate-local."""
    pointer = _pointer(path)
    if goal.get("strength") != "exact":
        raise NotationError("abstract_domain.exact_strength_required",
                            path=f"{pointer}/strength")
    report = Report()
    env = Scope(report, pointer)
    known = _bind_call(env, goal["known_call"], f"{pointer}/known_call",
                       introduce_function=True)
    target = _bind_call(env, goal["target_call"], f"{pointer}/target_call")
    if known[1] != target[1]:
        raise NotationError("abstract_domain.function_identity_mismatch",
                            path=f"{pointer}/target_call")
    domain = _domain_ast(env, goal["known_domain"], f"{pointer}/known_domain")
    result = {
        "kind": "find_abstract_domain",
        "target": target,
        "known_call": known,
        "known_domain": domain,
        "strength": "exact",
        "function_ref": known[1],
        "target_ref": pointer,
    }
    if "input_domain" in goal:
        result["input_domain"] = _domain_ast(
            env, goal["input_domain"], f"{pointer}/input_domain")
    return result


def canonical_abstract_domain(goal):
    """Content identity for abstract calls; never expands an unknown body."""

    def syntax(value):
        if isinstance(value, list):
            if value and value[0] == "ref":
                return ["ref", value[1].rsplit(":", 1)[-1], value[2]]
            return [syntax(child) for child in value]
        return value

    value = {
        "kind": "find_abstract_domain",
        "known_call": syntax(goal["known_call"]),
        "known_domain": syntax(goal["known_domain"]),
        "strength": goal["strength"],
        "target": syntax(goal["target"]),
    }
    if "input_domain" in goal:
        value["input_domain"] = syntax(goal["input_domain"])
    return value
