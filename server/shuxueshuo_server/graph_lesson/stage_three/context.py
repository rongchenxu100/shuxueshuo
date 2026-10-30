"""Read-only, source-complete mathematical context with lexical symbol identities.

Collection is not mathematical discharge: every source starts pending. A later
route must record how it used each item before it can claim a verified answer.
"""

import re
from copy import deepcopy

from shuxueshuo_server.problem_understanding.notation_compile import NotationValidator
from shuxueshuo_server.problem_understanding.review_contract import pointer

from ..stage_one import contracts as stage_one_contracts
from ..stage_one.extraction import scopes


def _pointer(path):
    value = re.sub(r"^r(?=\.|$)", "/root", path)
    value = re.sub(r"\.c(\d+)", r"/children/\1", value)
    return re.sub(r"\[(\d+)\]", r"/\1", value.replace(".", "/"))


def _walk(ast, path=()):
    yield ast, path
    for index, child in enumerate(ast[1:], 1):
        if isinstance(child, list) and child and isinstance(child[0], str):
            yield from _walk(child, (*path, index))


def _lexical_records(ast, source_ref, scope, path=(), bindings=()):
    """Keep quantified/function binders local, including denominator obligations."""
    bound, obligations = [], []
    kind = ast[0]
    nested = bindings
    if kind in ("quantifier", "set_builder"):
        name_index = 2 if kind == "quantifier" else 1
        binder = {
            "ref": source_ref + "#" + "/".join(map(str, (*path, name_index))),
            "name": ast[name_index], "kind": "bound", "scope": scope,
            "source_ref": source_ref, "domain": deepcopy(ast[name_index + 1]),
            "binding_path": list(path),
        }
        bound.append(binder)
        nested = (*bindings, binder["ref"])
    elif kind in ("function_definition", "function_input_relation"):
        binder = {"ref": source_ref + "#function_argument", "name": "function_argument",
                  "kind": "function_argument", "scope": scope, "source_ref": source_ref,
                  "domain": ["real"], "binding_path": list(path)}
        bound.append(binder)
        nested = (*bindings, binder["ref"])
    if kind == "/":
        obligations.append({
            "kind": "denominator_nonzero", "source_ref": source_ref, "scope": scope,
            "ast_path": list(path), "denominator": deepcopy(ast[2]),
            "binding_refs": list(bindings), "processing": {"status": "pending"},
        })
    for index, child in enumerate(ast[1:], 1):
        if not (isinstance(child, list) and child and isinstance(child[0], str)):
            continue
        # A quantified variable does not bind its own domain.
        active = nested if kind not in ("quantifier", "set_builder") or index == len(ast) - 1 else bindings
        child_bound, child_obligations = _lexical_records(child, source_ref, scope, (*path, index), active)
        bound.extend(child_bound)
        obligations.extend(child_obligations)
    return bound, obligations


def build_context(candidate, target_ref):
    """Return all original visible conditions; never use feature source subsets."""
    matches = [(path, scope, ancestors, index)
               for path, scope, ancestors in scopes(candidate["root"])
               for index in range(len(scope.get("goals", [])))
               if target_ref == f"{path}/goals/{index}"]
    if len(matches) != 1:
        raise ValueError("context.invalid_target")
    scope_ref, _, ancestors, goal_index = matches[0]
    visible = [*ancestors, scope_ref]
    report = NotationValidator().validate_root(candidate["root"], stage_one_contracts.schema()["$defs"])
    if not report.ok:
        raise ValueError("context.invalid_candidate")
    entries, bound_symbols, obligations = [], [], []
    for compiled_scope, records in report.scope_facts.items():
        path = _pointer(compiled_scope)
        if path not in visible:
            continue
        for record in records:
            source_ref = _pointer(record["path"])
            entry = {"source_ref": source_ref, "scope": path,
                     "kind": "definition" if "/definitions/" in source_ref else "fact",
                     "expression": deepcopy(pointer(candidate, source_ref)),
                     "ast": deepcopy(record["value"]), "processing": {"status": "pending"}}
            entries.append(entry)
            bound, required = _lexical_records(entry["ast"], source_ref, path)
            bound_symbols.extend(bound)
            obligations.extend(required)
    defaults = {row["ref"]: row for row in report.defaults}
    symbols = []
    for obj in report.objects:
        if _pointer(obj["scope"]) not in visible:
            continue
        refs = [entry["source_ref"] for entry in entries
                if any(ast[0] == "ref" and ast[1] == obj["ref"] for ast, _ in _walk(entry["ast"]))]
        symbols.append({**deepcopy(obj), "scope": _pointer(obj["scope"]),
                        "source_refs": refs, "default_domain": deepcopy(defaults.get(obj["ref"]))})
    semantic = report.semantic
    for part in scope_ref.removeprefix("/root").split("/children/")[1:]:
        semantic = semantic["children"][int(part)]
    goal = deepcopy(pointer(candidate, target_ref))
    goal_ast = deepcopy(semantic["goals"][goal_index])
    for symbol in symbols:
        if any(ast[0] == "ref" and ast[1] == symbol["ref"] for ast, _ in _walk(goal_ast["target"])):
            symbol["source_refs"].append(target_ref)
    context = {
        "target_ref": target_ref, "scope": scope_ref, "visible_scopes": visible,
        "goal": goal, "goal_ast": goal_ast, "entries": entries,
        "symbols": symbols, "bound_symbols": bound_symbols,
        "default_domains": [deepcopy(defaults[symbol["ref"]]) for symbol in symbols if symbol["ref"] in defaults],
        "well_definedness": obligations,
        "processing": {"status": "pending", "unprocessed_source_refs": [entry["source_ref"] for entry in entries]},
    }

    if goal['kind'] == 'find_range' and 'object' in goal:
        from ..stage_one.function_range import inspect_range_target
        context['range_goal'] = inspect_range_target(candidate, target_ref)
    elif goal['kind'] in ('find_value', 'check_constant', 'finite_sum'):
        from ..stage_one.function_evaluation import inspect_evaluation_target
        context['evaluation_goal'] = inspect_evaluation_target(candidate, target_ref)
    elif goal['kind'] == 'find_domain':
        from ..stage_one.function_domain import inspect_domain_target
        context['domain_goal'] = inspect_domain_target(candidate, target_ref)
    elif goal['kind'] == 'match_domain':
        from ..stage_one.function_domain_parameter import inspect_match_domain_target
        context['domain_goal'] = inspect_match_domain_target(candidate, target_ref)
    elif goal['kind'] == 'compare_functions':
        from ..stage_one.function_equality import inspect_comparison_target
        context['comparison_goal'] = inspect_comparison_target(candidate, target_ref)
    elif goal['kind'] == 'find_abstract_domain':
        from ..stage_one.abstract_function_domain import inspect_abstract_domain_target
        context['abstract_domain_goal'] = inspect_abstract_domain_target(candidate, target_ref)
    elif goal['kind'] == 'find_abstract_domain_parameter':
        from ..stage_one.abstract_domain_parameter import (
            inspect_abstract_domain_parameter_target,
        )
        context['abstract_domain_parameter_goal'] = inspect_abstract_domain_parameter_target(candidate, target_ref)
    return context
