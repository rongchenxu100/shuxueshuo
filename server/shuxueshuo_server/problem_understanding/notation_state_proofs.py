"""Sufficient certificates for projecting an attained extremum onto a parameter.

This is an answer-set equivalence, not an equality of point configurations.
Only a parameter of an ancestor graph and one free axis coordinate are covered.
The unconditional local min/max-value fact supplies existence of a witness;
we never calculate that witness, infer an infimum is attained, or drop the fact.
"""

import json


def key(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def conjuncts(facts):
    for fact in facts:
        if fact[0] == "and":
            yield from conjuncts(fact[1:])
        else:
            yield fact


def extremum_equality(fact):
    if fact[0] == "=":
        for extremum, other in (fact[1:], fact[1:][::-1]):
            if extremum[0] == "extremum":
                return extremum, other
    return None


def parameter_state_witness(
    goal, condition, local_facts, inherited_facts, owners, scope, budget
):
    """Return explicit premises, or None when parameter independence is unproved."""
    from .notation_semantics import Canonical, bounded_expand

    target = goal["target"]
    if goal["kind"] != "find_value" or target[0] != "ref" or target[2] != "scalar":
        return None
    state = extremum_equality(condition)
    if state is None:
        return None
    extremum, body = state
    algebra = Canonical()

    def same(a, b):
        budget.use()
        return bounded_expand(algebra.expr(a) - algebra.expr(b)) == 0

    def refs(value):
        budget.use()
        if not isinstance(value, list):
            return set()
        if value and value[0] == "ref":
            return {tuple(value)}
        return set().union(*(refs(v) for v in value if isinstance(v, list)))

    # A coefficient of an ancestor graph is a parameter while the later point
    # varies. Same-scope unlabelled scalars are intentionally not guessed fixed.
    graphs = [f for f in conjuncts(inherited_facts) if f[0] == "curve_definition"]
    # A graph that refers to another point/function is outside this certificate.
    graphs = [f for f in graphs if all(r[2] == "scalar" for r in refs(f[2]))]
    parameters = {r for f in graphs for r in refs(f[2]) if r[2] == "scalar"}
    target_owner = owners.get(target[1])
    if (
        tuple(target) not in parameters
        or not isinstance(target_owner, str)
        or not target_owner
        or not scope.startswith(target_owner + ".")
    ):
        return None
    if not same(body, extremum[3]):
        return None

    facts = list(conjuncts([*inherited_facts, *local_facts]))
    fixed = {}  # Coordinate -> premises establishing dependence only on parameters.

    def constant(value):
        budget.use()
        if value[0] == "number":
            return True
        if value[0] == "ref":
            return tuple(value) in parameters
        if value[:2] in (["call", "x"], ["call", "y"]):
            return key(value) in fixed
        if value[0] in ("+", "-", "*", "/", "^", "neg"):
            return all(constant(v) for v in value[1:])
        if value[:2] == ["call", "sqrt"]:
            return constant(value[2])
        return False

    # Exact coordinate definitions and y=f(x) memberships suffice for the
    # fixed endpoints. No inverse equation solving or geometric guesses.
    changed = True
    while changed:
        changed = False
        for fact in facts:
            budget.use()
            additions = []
            if fact[0] == "=":
                for coordinate, value in (fact[1:], fact[1:][::-1]):
                    if coordinate[:2] in (["call", "x"], ["call", "y"]) and constant(
                        value
                    ):
                        additions.append((coordinate, [fact]))
            elif fact[0] == "∈" and fact[1][0] == "ref":
                for graph in graphs:
                    if fact[2] == graph[1]:
                        x = ["call", "x", fact[1]]
                        if key(x) in fixed:
                            additions.append(
                                (["call", "y", fact[1]], [graph, fact, *fixed[key(x)]])
                            )
            for coordinate, premises in additions:
                if key(coordinate) not in fixed:
                    fixed[key(coordinate)] = premises
                    changed = True

    free = {}

    def inspect(value):
        budget.use()
        if value[0] in ("+", "-", "*", "/", "^", "neg"):
            return all(inspect(v) for v in value[1:])
        if value[:2] == ["call", "sqrt"]:
            return inspect(value[2])
        if value[:2] == ["call", "length"]:
            return all(
                point[0] == "ref"
                and point[2] == "point"
                and all(inspect(["call", axis, point]) for axis in ("x", "y"))
                for point in value[2:]
            )
        if value[:2] in (["call", "x"], ["call", "y"]):
            if key(value) not in fixed:
                free[key(value)] = value
            return True
        return constant(value)

    if not inspect(body) or len(free) != 1:
        return None
    coordinate = next(iter(free.values()))
    point = coordinate[2]
    if point[0] != "ref":
        return None
    point_owner = owners.get(point[1])
    if not isinstance(point_owner, str) or not point_owner.startswith(
        target_owner + "."
    ):
        return None
    # An explicit axis condition certifies the one-coordinate motion domain.
    other = ["call", "y" if coordinate[1] == "x" else "x", point]
    axis = next(
        (
            f
            for f in facts
            if f[0] == "="
            and (
                (f[1] == other and f[2] == ["number", "0"])
                or (f[2] == other and f[1] == ["number", "0"])
            )
        ),
        None,
    )
    if axis is None:
        return None
    # Never erase dependence of the requested answer form on the witness.
    if any(
        r[0] != "ref" or tuple(r) not in parameters for r in goal.get("in_terms_of", [])
    ):
        return None

    def hints_ok(hints):
        return all(hint in (point, coordinate) for hint in hints)

    if not hints_ok(extremum[2]) or not hints_ok(goal.get("variables", [])):
        return None
    for fact in conjuncts(local_facts):
        value_fact = extremum_equality(fact)
        if value_fact is None:
            continue
        known, value = value_fact
        if (
            known[1] != extremum[1]
            or not hints_ok(known[2])
            or not same(known[3], body)
        ):
            continue
        # Keep this initial certificate finite and closed; a parameter-valued
        # bound or a nested extremum needs its own definedness proof.
        if refs(value) or not constant(value):
            continue
        number = algebra.expr(value)
        if (
            number.is_finite is not True
            or number.is_real is not True
            or algebra.obligations
        ):
            continue
        return {
            "premises": [
                fact,
                axis,
                *graphs,
                *[f for ps in fixed.values() for f in ps],
            ],
            "parameter": target,
            "witness_coordinate": coordinate,
            "existence": "local_attained_extremum_value",
        }
    return None
