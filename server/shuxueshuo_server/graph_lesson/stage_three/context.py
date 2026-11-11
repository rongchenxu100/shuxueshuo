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
    from ...problem_understanding.answer_requests import (
        compile_candidate_plan,
        compile_plan,
        request_for_goal,
    )
    if request := request_for_goal(goal):
        context['answer_plan'] = (compile_candidate_plan(request) if goal['kind'] == 'select_range_domain'
                                  else compile_plan(request))

    from ..piecewise_equation import inspect_target as inspect_piecewise_equation
    from ..piecewise_equation import relevant as piecewise_equation_relevant
    from ..piecewise_inequality import inspect_target as inspect_piecewise_inequality
    from ..piecewise_inequality import relevant as piecewise_inequality_relevant
    from ..extremum_math import routed_description as extremum_description
    from ..monotonicity_inequality_math import routed_description as mono_inequality_description
    from ..monotonicity_parameter_math import routed_description as mono_parameter_description
    source_entries = [{k: r[k] for k in ('source_ref', 'expression')} for r in entries]
    from ..abstract_monotonicity_math import routed_description as abstract_mono_description
    from ..parity_parameter_math import describe as parity_parameter_description
    from ..parity_extension_math import describe as parity_extension_description
    from ..symmetry_value_math import describe as symmetry_value_description
    if desc := parity_extension_description(goal, goal_ast, target_ref, entries, candidate=candidate):
        context['parity_extension_goal'] = desc
    elif desc := symmetry_value_description(goal, goal_ast, target_ref, entries, candidate=candidate):
        context['symmetry_value_goal'] = desc
    elif desc := parity_parameter_description(goal, goal_ast, target_ref, entries, candidate=candidate):
        context['parity_parameter_goal'] = desc
    elif desc := abstract_mono_description(goal, target_ref, source_entries):
        context['abstract_monotonicity_goal'] = desc
    elif desc := mono_parameter_description(goal, target_ref, source_entries):
        context['mono_parameter_goal'] = desc
    elif desc := mono_inequality_description(goal, target_ref, source_entries):
        context['mono_inequality_goal'] = desc
    elif desc := extremum_description(goal, target_ref, source_entries):
        context['extremum_goal'] = desc
    elif 'pricing' in goal_ast:
        from ..piecewise_modeling import admitted, equation_description, inspect_target
        context['piecewise_modeling'] = inspect_target(candidate, target_ref)
        if goal_ast['kind'] == 'find_range' and admitted(context):
            context['piecewise_equation'] = equation_description(context)
    elif goal_ast['kind'] == 'match_range':
        from ..piecewise_range_parameter import inspect_target
        context['piecewise_range_parameter'] = inspect_target(candidate, target_ref)
    elif piecewise_inequality_relevant(goal_ast, [{'value': e['ast']} for e in entries]):
        context['piecewise_inequality'] = inspect_piecewise_inequality(candidate, target_ref)
    elif piecewise_equation_relevant(goal_ast, [{'value': e['ast']} for e in entries]):
        context['piecewise_equation'] = inspect_piecewise_equation(candidate, target_ref)
    elif goal['kind'] in ('find_monotonic_intervals', 'prove_monotonicity_on_interval'):
        from ..function_monotonicity import describe
        context['monotonicity_goal'] = describe(goal, target_ref, entries)
    elif goal['kind'] in ('select_function_graph', 'draw_function_graph', 'solve_graph_inequality'):
        from ..function_graph import describe_scoped
        context['graph_goal'] = describe_scoped(goal, target_ref, entries)
    elif 'relation' in goal and goal.get('function_type'):
        from ..stage_one.function_formula import inspect_formula_target
        context['formula_goal'] = inspect_formula_target(candidate, target_ref)
    elif goal['kind'] in ('find_range', 'select_range_domain', 'find_extrema_expression') and 'object' in goal:
        from ..stage_one.function_range import inspect_range_target
        context['range_goal'] = inspect_range_target(candidate, target_ref)
    elif goal['kind'] == 'find_value' and 'relation' in goal:
        from ..stage_one.function_formula import inspect_formula_target
        context['evaluation_goal'] = inspect_formula_target(candidate, target_ref)
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
    elif goal['kind'] == 'determine_function_parity':
        from ..function_parity import inspect_parity_target
        context['parity_goal'] = inspect_parity_target(candidate, target_ref)
    elif goal['kind'] == 'find_function_formula':
        from ..stage_one.function_formula import inspect_formula_target
        context['formula_goal'] = inspect_formula_target(candidate, target_ref)
    elif goal['kind'] == 'find_translation_range':
        from ..stage_one.translation_range import inspect_translation_target
        context['translation_range_goal'] = inspect_translation_target(candidate, target_ref)
    elif goal['kind'] == 'find_abstract_range':
        from ..stage_one.abstract_function_range import inspect_abstract_range_target
        context['abstract_range_goal'] = inspect_abstract_range_target(candidate, target_ref)
    elif goal['kind'] == 'find_abstract_domain':
        from ..stage_one.abstract_function_domain import inspect_abstract_domain_target
        context['abstract_domain_goal'] = inspect_abstract_domain_target(candidate, target_ref)
    elif goal['kind'] == 'find_abstract_domain_parameter':
        from ..stage_one.abstract_domain_parameter import (
            inspect_abstract_domain_parameter_target,
        )
        context['abstract_domain_parameter_goal'] = inspect_abstract_domain_parameter_target(candidate, target_ref)
    return context
