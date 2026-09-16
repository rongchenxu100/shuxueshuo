"""Bounded, scope-aware equivalences over typed math objects, never source text.

Rules are intentionally sufficient rather than complete. Each rewrite records
its premises. Unknown geometry remains distinct; no search for a solution,
case identifiers, golden answers, or model calls are involved.
"""

import json
from copy import deepcopy

import sympy as sp

from .notation_geometry_proofs import AffineCertificates, intersection
from .notation_parser import NotationError
from .proof_budget import ProofBudget


def key(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def signature(value):
    if not isinstance(value, list):
        return value
    value = [signature(x) for x in value]
    if value and value[0] in ("∩", "set"):
        value[1:] = sorted(value[1:], key=key)
    if value[:2] in (["call", "line"], ["call", "segment"]):
        value[2:] = sorted(value[2:], key=key)
    return value


def conjuncts(facts):
    for fact in facts:
        if fact[0] == "and":
            yield from conjuncts(fact[1:])
        else:
            yield fact


def pair_equality(fact, left_kind, right_kind):
    if fact[0] != "=":
        return None
    a, b = fact[1:]
    for left, right in ((a, b), (b, a)):
        if left[0] == left_kind and right[0] == right_kind:
            return left, right
    return None


class Geometry:
    def __init__(self, facts, budget):
        # Only unconditional current/ancestor facts may establish a premise.
        self.facts = list(conjuncts(facts))
        self.budget = budget

    def quadratic_axis(self, curve):
        # Reuse the bounded algebra machinery on inert bound expressions.
        from .notation_semantics import Canonical, bounded_expand

        algebra = Canonical()
        x = algebra.expr(["bound", "coordinate_x"])
        for fact in self.facts:
            if fact[0] != "curve_definition" or fact[1] != curve:
                continue
            self.budget.use()
            try:
                polynomial = sp.Poly(bounded_expand(algebra.expr(fact[2])), x)
                if polynomial.degree() != 2:
                    continue
                coefficient = polynomial.LC()
                if coefficient.is_zero is False:
                    return [fact]
                for condition in self.facts:
                    self.budget.use()
                    if condition[0] not in ("!=", ">", "<"):
                        continue
                    if ["number", "0"] not in condition[1:]:
                        continue
                    delta = algebra.expr(condition[1]) - algebra.expr(condition[2])
                    if (
                        bounded_expand(delta - coefficient) == 0
                        or bounded_expand(delta + coefficient) == 0
                    ):
                        return [fact, condition]
            except (ValueError, TypeError, sp.PolynomialError):
                continue
        return None

    def unique_intersection(self, first, second):
        """Return canonical loci and certified premises, or leave unproved."""
        self.budget.use()
        if {key(first), key(second)} == {
            key(["axis_constant", "x_axis"]),
            key(["axis_constant", "y_axis"]),
        }:
            return [first, second], "coordinate_axes_unique", []
        for axis, horizontal in ((first, second), (second, first)):
            if axis[:2] == ["call", "axis"] and horizontal == [
                "axis_constant",
                "x_axis",
            ]:
                premises = self.quadratic_axis(axis[2])
                if premises:
                    return [first, second], "quadratic_axis_unique", premises
        if any(
            x[:2] not in (["call", "line"], ["call", "segment"])
            for x in (first, second)
        ):
            return None
        endpoints = {key(sorted(first[2:], key=key)), key(sorted(second[2:], key=key))}
        for fact in self.facts:
            self.budget.use()
            if fact[:2] not in (["call", "square"], ["call", "parallelogram"]):
                continue
            vertices = fact[2:]
            if len({key(x) for x in vertices}) != 4:
                continue
            diagonals = {
                key(sorted([vertices[0], vertices[2]], key=key)),
                key(sorted([vertices[1], vertices[3]], key=key)),
            }
            if endpoints == diagonals:
                return (
                    [["call", "line", *first[2:]], ["call", "line", *second[2:]]],
                    "nondegenerate_parallelogram_diagonals",
                    [fact],
                )
        return self.numeric_intersection(first, second)

    def numeric_intersection(self, first, second):
        from .notation_semantics import Canonical

        algebra = Canonical()
        coordinates, premises = {}, []
        for fact in self.facts:
            match = pair_equality(fact, "call", "number")
            if not match or match[0][1] not in ("x", "y"):
                continue
            prop, value = match
            point = prop[2]
            if point[0] != "ref" or point[2] != "point":
                continue
            coordinates.setdefault(point[1], {})[prop[1]] = algebra.expr(value)
            premises.append(fact)
        points = first[2:] + second[2:]
        if any(
            p[0] != "ref" or set(coordinates.get(p[1], {})) != {"x", "y"}
            for p in points
        ):
            return None
        # Exact determinant with known numeric coordinates, no legacy fact IR.
        coords = [(coordinates[p[1]]["x"], coordinates[p[1]]["y"]) for p in points]
        result = intersection(*coords)
        if result is None:
            return None
        _, t, u = result
        if any(
            locus[1] == "segment" and not 0 <= parameter <= 1
            for locus, parameter in ((first, t), (second, u))
        ):
            return None
        return (
            [["call", "line", *first[2:]], ["call", "line", *second[2:]]],
            "exact_numeric_intersection",
            premises,
        )


def normalize_bound(root, objects, *, source_locations=None):
    source_locations = source_locations or {}
    budget = ProofBudget()
    proofs, bindings = [], []
    declaration_refs = set()
    owners = {obj["ref"]: obj["scope"] for obj in objects}

    def references(value):
        if isinstance(value, dict):
            return set().union(*(references(v) for v in value.values()))
        if isinstance(value, list):
            if value and value[0] == "ref":
                return {value[1]}
            return set().union(*(references(v) for v in value))
        return set()

    def record(rule, scope, before, after, premises=()):
        if before != after:
            proofs.append(
                {
                    "rule": rule,
                    "scope": scope,
                    "before": before,
                    "after": after,
                    "premises": list(premises),
                }
            )

    def coordinates(ast, scope):
        budget.use()
        if not isinstance(ast, list):
            return ast
        match = pair_equality(ast, "ref", "tuple") if ast else None
        if match and match[0][2] == "point":
            point, values = match
            after = [
                "and",
                *[
                    ["=", ["call", axis, point], value]
                    for axis, value in zip(("x", "y"), values[1:])
                ],
            ]
            record("point_coordinate_components", scope, ast, after)
            return after
        return [coordinates(x, scope) if isinstance(x, list) else x for x in ast]

    def replace(value, aliases):
        budget.use()
        if not isinstance(value, list):
            return value
        if value and value[0] == "ref" and value[1] in aliases:
            return deepcopy(aliases[value[1]])
        return [replace(v, aliases) if isinstance(v, list) else v for v in value]

    def axis_memberships(value, scope):
        budget.use()
        if not isinstance(value, list):
            return value
        if (
            value
            and value[0] == "∈"
            and value[1][0] == "ref"
            and value[1][2] == "point"
            and value[2] in (["axis_constant", "x_axis"], ["axis_constant", "y_axis"])
        ):
            coordinate = "y" if value[2][1] == "x_axis" else "x"
            after = ["=", ["call", coordinate, value[1]], ["number", "0"]]
            record("coordinate_axis_membership", scope, value, after)
            return after
        return [axis_memberships(v, scope) if isinstance(v, list) else v for v in value]

    def visit(source, inherited_facts=(), inherited_aliases=None):
        path = source["scope"]
        aliases = dict(inherited_aliases or {})
        relations = []
        for fact in source["facts"]:
            if fact[0] == "object_declaration":
                declaration_refs.update(references(fact))
                record("standalone_segment_declaration", path, fact, ["and"])
            else:
                relations.append(fact)
        facts = list(conjuncts([coordinates(f, path) for f in relations]))
        facts = [replace(f, aliases) for f in facts]
        # Deterministic alias selection; only current-scope scalar definitions
        # can be eliminated here. All their uses, including goals, are retained.
        candidates = []
        for fact in facts:
            match = pair_equality(fact, "call", "ref")
            if (
                match
                and match[0][1] in ("x", "y")
                and match[1][2] == "scalar"
                and owners.get(match[1][1]) == path
            ):
                candidates.append((match[1][1], match[0], fact))
        for identity, prop, fact in sorted(candidates, key=lambda x: (x[0], key(x[1]))):
            if identity not in aliases:
                aliases[identity] = prop
                bindings.append(
                    {
                        "scope": path,
                        "symbol_ref": identity,
                        "coordinate": prop,
                        "definition": fact,
                    }
                )
                record(
                    "coordinate_symbol_binding", path, fact, ["=", prop, prop], [fact]
                )
        facts = [replace(f, aliases) for f in facts]
        # Remove only reflexive equalities produced by exact substitution.
        facts = [f for f in facts if not (f[0] == "=" and f[1] == f[2])]
        geometry = Geometry([*inherited_facts, *facts], budget)

        def intersections(ast):
            if ast[0] == "point_intersection_definition":
                point, locus = ast[1:]
                certificate = (
                    geometry.unique_intersection(*locus[1:])
                    if len(locus) == 3
                    else None
                )
                if certificate is None:
                    origin = source_locations.get(key(ast), {})
                    raise NotationError(
                        "binding.intersection_not_proven_unique",
                        path=origin.get("path", path),
                        source=origin.get("source"),
                    )
                loci, rule, premises = certificate
                after = ["∈", point, ["∩", *loci]]
                record("point_intersection_definition", path, ast, after, premises)
                record(rule, path, ast, after, premises)
                return after
            if ast[0] in ("and", "or"):
                return [ast[0], *[intersections(x) for x in ast[1:]]]
            if ast[0] == "quantifier":
                return [*ast[:4], intersections(ast[4])]
            match = pair_equality(ast, "∩", "set")
            locus, point = (
                (match[0], match[1][1])
                if match and len(match[1]) == 2
                else (None, None)
            )
            if ast[0] == "∈" and ast[2][0] == "∩":
                point, locus = ast[1:]
            if locus is None or len(locus) != 3:
                return ast
            certificate = geometry.unique_intersection(*locus[1:])
            if certificate:
                loci, rule, premises = certificate
                after = ["∈", point, ["∩", *loci]]
                record(rule, path, ast, after, premises)
                return after
            return ast

        facts = [intersections(f) for f in facts]
        certificates = AffineCertificates([*inherited_facts, *facts], budget)

        def certified_ratios(value):
            budget.use()
            if not isinstance(value, list):
                return value
            if value[:2] in (["call", "bisects"], ["call", "cut_ratio"]):
                first, second = value[2:]
                if value[1] == "bisects":
                    first, second = second, first
                proof = certificates.cut(first, second)
                if proof:
                    ratio = ["certified_cut_ratio", first, second]
                    after = (
                        ["=", ratio, ["number", "1"]]
                        if value[1] == "bisects"
                        else ratio
                    )
                    record(
                        "bisector_unit_ratio"
                        if value[1] == "bisects"
                        else "positive_cut_ratio",
                        path,
                        value,
                        after,
                        proof["premises"],
                    )
                    return after
            return [certified_ratios(v) if isinstance(v, list) else v for v in value]

        certified = []
        for fact in facts:
            proof = (
                certificates.quadrilateral(fact[2:])
                if fact[:2] == ["call", "quadrilateral"]
                else None
            )
            if proof:
                record(proof["rule"], path, fact, ["and"], proof["premises"])
            else:
                certified.append(certified_ratios(fact))
        facts = certified
        # A finite point-set equality entails membership in the set's locus
        # and in each operand of an intersection. No OR premise is promoted.
        implied = {}

        def add_member(point, locus, premise):
            implied[key(signature(["∈", point, locus]))] = premise
            if locus[0] == "∩":
                for operand in locus[1:]:
                    add_member(point, operand, premise)

        for fact in conjuncts([*inherited_facts, *facts]):
            if fact[0] != "=":
                continue
            for locus, points in ((fact[1], fact[2]), (fact[2], fact[1])):
                if points[0] == "set" and locus[0] != "set":
                    for point in points[1:]:
                        add_member(point, locus, fact)
        kept = []
        for fact in facts:
            premise = implied.get(key(signature(fact)))
            if fact[0] == "∈" and premise is not None:
                record(
                    "finite_set_membership_redundancy", path, fact, ["and"], [premise]
                )
            else:
                kept.append(fact)
        # Coordinate-axis membership is a definition, not a geometric guess.
        # Normalize after finite-set implications so both rules compose.
        seen = {key(signature(f)): f for f in conjuncts(inherited_facts)}
        distinct = []
        for fact in kept:
            fact = axis_memberships(fact, path)
            code = key(signature(fact))
            if code in seen:
                record("duplicate_relation", path, fact, ["and"], [seen[code]])
            else:
                seen[code] = fact
                distinct.append(fact)
        kept = distinct
        goals = []
        for goal in source["goals"]:
            normalized_goal = {}
            for field, value in goal.items():
                if isinstance(value, list):
                    value = replace(value, aliases)
                    if field == "at":
                        value = intersections(value)
                    value = axis_memberships(certified_ratios(value), path)
                normalized_goal[field] = value
            goals.append(normalized_goal)
        return {
            **deepcopy(source),
            "facts": kept,
            "goals": goals,
            "children": [
                visit(c, [*inherited_facts, *kept], aliases) for c in source["children"]
            ],
        }

    result = visit(root)
    eliminated = {binding["symbol_ref"] for binding in bindings}
    # Endpoint objects used only by removed mentions have no comparison role.
    # Keep them in the original IR, but do not obstruct consistent renaming.
    eliminated.update(declaration_refs - references(result))
    return {
        "version": "math-object-normalization/v1",
        "root": result,
        "objects": [deepcopy(obj) for obj in objects if obj["ref"] not in eliminated],
        "coordinate_bindings": bindings,
        "proofs": proofs,
    }
