"""Comparable mathematical snapshots for migration review, never acceptance.

The original bound tree and comparison tree are both retained. Qualifiers are
audited separately because the existing bounded equivalence projection does
not preserve every planning-relevant field (notably extremum variables).
Attained states are also retained: a parameter-answer equivalence certificate
does not prove equality of the original point configurations or conditions.
"""

import json
from collections import defaultdict
from copy import deepcopy
from hashlib import sha256

from .candidate_common import validate_match
from .legacy_math_tree import LegacyMathTree
from .notation_compile import NotationValidator, typecheck
from .notation_normalization import normalize_bound
from .notation_semantics import Canonical, canonical, key, prove_equivalent
from .notation_state_proofs import conjuncts, extremum_equality
from .proof_budget import ProofBudget


def fingerprint(value):
    return sha256(key(value).encode()).hexdigest()


def scopes(root):
    yield root
    for child in root.get("children", []):
        yield from scopes(child)


def remap(value, aliases):
    if isinstance(value, list):
        return [remap(x, aliases) for x in value]
    if isinstance(value, dict):
        return {k: remap(v, aliases) for k, v in value.items()}
    return aliases.get(value, value) if isinstance(value, str) else value


def _curve_aliases(objects):
    groups = defaultdict(list)
    for obj in objects:
        if obj["kind"] == "curve":
            groups[obj["scope"]].append(obj)
    # One curve per scope is unambiguous; with multiple curves retain names.
    # Changed curve equations remain visible in the relations comparison.
    return {
        items[0]["ref"]: f"{scope}:curve:__curve"
        for scope, items in groups.items()
        if len(items) == 1
    }


def _scope_compilers(root):
    compiler = Canonical()
    scope_functions = {}
    for scope in scopes(root):
        parent = scope["scope"].rsplit(".c", 1)[0] if ".c" in scope["scope"] else None
        compiler.functions = dict(scope_functions.get(parent, {}))
        for fact in scope["facts"]:
            if fact[0] == "function_definition":
                compiler.functions[key(compiler.tree(fact[1]))] = fact[2]
        scope_functions[scope["scope"]] = dict(compiler.functions)
        yield scope, compiler


def _qualifiers(root):
    result = []

    def target(value):
        return (
            compiler.math(value)
            if typecheck(value) in ("scalar", "length", "angle", "area")
            else compiler.tree(value)
        )

    def extrema(value, scope, container):
        if isinstance(value, list):
            if value and value[0] == "extremum" and value[2]:
                result.append(
                    {
                        "scope": scope,
                        "container": container,
                        "kind": "extremum_variables",
                        "operator": value[1],
                        "target": target(value[3]),
                        "variables": sorted(value[2], key=key),
                    }
                )
            for child in value:
                extrema(child, scope, container)
        elif isinstance(value, dict):
            for child in value.values():
                extrema(child, scope, container)

    for scope, compiler in _scope_compilers(root):
        for goal in scope["goals"]:
            modifiers = {
                k: sorted(goal[k], key=key)
                for k in ("variables", "in_terms_of")
                if k in goal
            }
            if modifiers:
                result.append(
                    {
                        "scope": scope["scope"],
                        "kind": "goal_modifiers",
                        "goal_kind": goal["kind"],
                        "target": target(goal["target"]),
                        **modifiers,
                    }
                )
        extrema(scope["facts"], scope["scope"], "facts")
        extrema(scope["goals"], scope["scope"], "goals")
    return sorted({key(x): x for x in result}.values(), key=key)


def _states(root):
    result = []
    for scope in scopes(root):
        for index, fact in enumerate(scope["facts"]):
            if fact[0] == "curve_definition":
                result.append(
                    {
                        "scope": scope["scope"],
                        "object": fact[1],
                        "property": "definition",
                        "value": fact[2],
                        "status": "given",
                    }
                )
            if fact[0] != "=":
                continue
            for target, value in ((fact[1], fact[2]), (fact[2], fact[1])):
                if target[0] == "ref" and (
                    target[2] == "scalar" or value[0] == "tuple"
                ):
                    result.append(
                        {
                            "scope": scope["scope"],
                            "object": target,
                            "property": "coordinates"
                            if target[2] == "point"
                            else "value",
                            "value": value,
                            "status": "given_relation",
                            "fact_index": index,
                        }
                    )
    return result


def _state_conditions(root):
    """Audit source states before answer-only normalization can remove them."""
    result = []

    def contains_state(value):
        if not isinstance(value, list) or not value:
            return False
        state = extremum_equality(value)
        if state is not None:
            extremum, other = state
            if compiler.math(extremum[3]) == compiler.math(other):
                return True
        return any(contains_state(child) for child in value)

    for scope, compiler in _scope_compilers(root):
        for fact in conjuncts(scope["facts"]):
            if contains_state(fact):
                # Keep disjunction/quantifier context. A state in one branch
                # must not become an unconditional assertion in the audit.
                result.append(
                    {"scope": scope["scope"], "condition": compiler.logic([fact])}
                )
    return sorted({key(x): x for x in result}.values(), key=key)


def _objective_uses(root):
    result = []

    def visit(value, scope):
        if isinstance(value, list):
            if value and value[0] == "extremum":
                result.append({"scope": scope, "target": compiler.math(value[3])})
            for child in value:
                visit(child, scope)
        elif isinstance(value, dict):
            for child in value.values():
                visit(child, scope)

    for scope, compiler in _scope_compilers(root):
        visit(scope["facts"], scope["scope"])
        visit(scope["goals"], scope["scope"])
        for goal in scope["goals"]:
            if goal["kind"] in ("find_minimum", "find_maximum"):
                result.append(
                    {"scope": scope["scope"], "target": compiler.math(goal["target"])}
                )
    return result


def build_math_tree(payload, *, format):
    coverage, annotations = [], []
    if format == "legacy":
        builder = LegacyMathTree()
        report = builder.build(payload)
        coverage, annotations = builder.coverage, builder.annotations
    elif format == "notation":
        report = NotationValidator().validate(payload)
        from shuxueshuo_server.solver.family import DEFAULT_FAMILY_REGISTRY

        if isinstance(payload, dict):
            match = validate_match(
                payload, [f.family_id for f in DEFAULT_FAMILY_REGISTRY.families]
            )
            report.issues.extend(
                {"stage": "match", "code": issue} for issue in match["issues"]
            )
        if report.normalized:

            def record(source, path="r"):
                for field in ("definitions", "facts", "goals", "uncertainties"):
                    for index, item in enumerate(source[field]):
                        coverage.append(
                            {
                                "path": f"{path}.{field}[{index}]",
                                "category": field,
                                "source": item,
                            }
                        )
                for index, child in enumerate(source["children"]):
                    record(child, f"{path}.c{index}")

            record(report.normalized["root"])
    else:
        raise ValueError(f"unknown audit input format: {format}")
    result = {
        "schema_version": "math-object-tree-audit/v1",
        "format": format,
        "input_sha256": fingerprint(payload),
        "parse_valid": report.ok,
        "family_id": payload.get("family_id") if isinstance(payload, dict) else None,
        "solver_ready": False,
        "runtime_bound": False,
        "issues": report.issues,
        "raw_objects": report.objects,
        "raw_tree": report.semantic,
        "source_coverage": coverage,
        "annotations": annotations,
    }
    if not report.ok:
        return result
    aliases = _curve_aliases(report.objects)
    mapped = deepcopy(report)
    mapped.semantic = remap(report.semantic, aliases)
    mapped.objects = remap(report.objects, aliases)
    mapped.semantic_normalization = normalize_bound(mapped.semantic, mapped.objects)
    compiler = Canonical()
    comparison = canonical(mapped, compiler=compiler)
    objects = mapped.semantic_normalization.get("objects", mapped.objects)
    result.update(
        comparison_aliases=aliases,
        objects=[
            {"ref": obj["ref"], "kind": obj["kind"], "scope": obj["scope"]}
            for obj in sorted(objects, key=lambda x: x["ref"])
        ],
        scopes=[
            {"scope": s["scope"], "children": [c["scope"] for c in s["children"]]}
            for s in scopes(mapped.semantic)
        ],
        initial_states=_states(mapped.semantic),
        state_conditions=_state_conditions(mapped.semantic),
        qualifiers=_qualifiers(mapped.semantic),
        objective_uses=_objective_uses(mapped.semantic),
        objective_descriptors=[
            {
                "scope": x["scope"],
                "target": Canonical().math(remap(x["target"], aliases)),
            }
            for x in annotations
            if x["kind"] == "minimum_target"
        ],
        comparison_tree=comparison,
        atoms=compiler.atoms,
        # Only used in-process; the on-disk snapshot stores inert ASTs/text.
        normalization=mapped.semantic_normalization,
        counts={
            "named_objects": len(report.objects),
            "normalized_objects": len(objects),
            "scopes": sum(1 for _ in scopes(report.semantic)),
            "facts": sum(len(s["facts"]) for s in scopes(report.semantic)),
            "goals": sum(len(s["goals"]) for s in scopes(report.semantic)),
        },
    )
    return result


def _set_difference(left, right):
    a, b = {key(x): x for x in left}, {key(x): x for x in right}
    return {
        "legacy_only": [a[k] for k in sorted(a.keys() - b.keys())],
        "notation_only": [b[k] for k in sorted(b.keys() - a.keys())],
    }


def compare_math_trees(old, new):
    if not old["parse_valid"] or not new["parse_valid"]:
        return {
            "status": "invalid_input",
            "equivalent": False,
            "legacy_issues": old["issues"],
            "notation_issues": new["issues"],
        }
    differences = []
    if old["family_id"] != new["family_id"]:
        differences.append(
            {
                "category": "family",
                "legacy": old["family_id"],
                "notation": new["family_id"],
            }
        )
    for field in ("scopes", "objects", "qualifiers", "state_conditions"):
        diff = _set_difference(old[field], new[field])
        if diff["legacy_only"] or diff["notation_only"]:
            differences.append({"category": field, **diff})
    for descriptor in old["objective_descriptors"]:
        if not any(
            use["target"] == descriptor["target"]
            and (
                use["scope"] == descriptor["scope"]
                or use["scope"].startswith(descriptor["scope"] + ".c")
            )
            for use in new["objective_uses"]
        ):
            differences.append(
                {"category": "legacy_objective_unmatched", "legacy": descriptor}
            )

    a, b = old["comparison_tree"], new["comparison_tree"]
    # Rebuild the small canonical compiler state, never parse serialized SymPy.
    compilers = [Canonical(), Canonical()]
    for snapshot, compiler in zip((old, new), compilers):
        compiler.scope(snapshot["normalization"]["root"])
    proofs = (
        []
        if a == b
        else prove_equivalent(
            a, b, {**compilers[0].algebra, **compilers[1].algebra}, ProofBudget()
        )
    )
    semantic_equivalent = proofs is not None
    if not semantic_equivalent:

        def walk(left, right, path):
            for field in ("facts", "goals", "uncertainties"):
                left_items, right_items = left[field], right[field]
                if field == "facts" and len(left_items) == len(right_items) == 1:
                    # The usual case is one conjunction. Show only changed
                    # literals; never flatten alternatives from a disjunction.
                    left_items, right_items = left_items[0], right_items[0]
                diff = _set_difference(left_items, right_items)
                if diff["legacy_only"] or diff["notation_only"]:
                    differences.append({"category": field, "scope": path, **diff})
            if len(left["children"]) != len(right["children"]):
                differences.append(
                    {
                        "category": "scope_count",
                        "scope": path,
                        "legacy": len(left["children"]),
                        "notation": len(right["children"]),
                    }
                )
            for index, (lchild, rchild) in enumerate(
                zip(left["children"], right["children"])
            ):
                walk(lchild, rchild, f"{path}.c{index}")

        walk(a["root"], b["root"], "r")
        if a["well_definedness"] != b["well_definedness"]:
            differences.append(
                {
                    "category": "well_definedness",
                    **_set_difference(a["well_definedness"], b["well_definedness"]),
                }
            )
    return {
        "status": "equivalent"
        if not differences and semantic_equivalent
        else "needs_review",
        "equivalent": not differences and semantic_equivalent,
        "bounded_semantic_equivalence": semantic_equivalent,
        "proofs": proofs or [],
        "differences": differences,
        "runtime_equivalence": "not_established",
        "source_correctness": "not_established",
    }


def display_ast(value):
    """Human-readable diagnostic notation, not an executable round-trip format."""
    if not isinstance(value, list) or not value:
        return str(value)
    kind, *args = value
    if kind == "ref":
        return args[0].replace(":curve:__curve", ":curve:Γ")
    if kind in ("number", "bound", "axis_constant"):
        return str(args[0])
    if kind == "call":
        return f"{args[0]}({', '.join(display_ast(x) for x in args[1:])})"
    if kind == "tuple":
        return "(" + ", ".join(display_ast(x) for x in args) + ")"
    if kind == "set":
        return "{" + ", ".join(display_ast(x) for x in args) + "}"
    if kind == "neg":
        return "-" + display_ast(args[0])
    if kind == "degrees":
        return display_ast(args[0]) + "°"
    if kind == "curve_definition":
        return display_ast(args[0]) + ": y=" + display_ast(args[1])
    if kind == "extremum":
        if len(args) == 2:
            return f"{args[0]}({args[1]})"
        return f"{args[0]}_{{{','.join(display_ast(x) for x in args[1])}}}({display_ast(args[2])})"
    if len(args) == 2:
        return f"({display_ast(args[0])} {kind} {display_ast(args[1])})"
    return json.dumps(value, ensure_ascii=False)
