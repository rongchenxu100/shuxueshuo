"""Frozen pre-F3 search for historical baseline tooling ONLY.

Production must not import this module or use it as a fallback. The archived
search is intentionally not maintained alongside current mathematical strategies.

Premises are explicitly supplied by the caller. A successful conditional proof
never asserts feasibility, complete solution enumeration, or execution authority.
"""

from __future__ import annotations

from fractions import Fraction as Q
from functools import partial

from shuxueshuo_server.solver.math_kernel.proof_algebra import (
    ONE,
    ZERO,
    ProofFailure,
    domains,
    expr,
    names,
    number,
    signed_integer,
    substitute,
    walk,
)
from shuxueshuo_server.solver.math_kernel.proof_checker import (
    RELATIONS,  # noqa: F401 - legacy compatibility export
    REVERSE,
    RULES,  # noqa: F401 - legacy compatibility export
    RULESET_HASH,
    RULESET_VERSION,  # noqa: F401 - legacy compatibility export
    SIGNS,
    _cancel_additive,
    _derived_source,  # noqa: F401 - legacy compatibility export
    _diff,
    _Environment,
    _factors,
    _holds,
    _noncyclic,
    _ordered,
    _payload_depth,  # noqa: F401 - legacy compatibility export
    _read_document,  # noqa: F401 - legacy compatibility export
    _relation,  # noqa: F401 - legacy compatibility export
    _root_claims,
    _roots_for_request,
    _text,  # noqa: F401 - legacy compatibility export
    _validate_expression,  # noqa: F401 - legacy compatibility export
    freeze_json,  # noqa: F401 - legacy compatibility export
    replay_proof,  # noqa: F401 - legacy compatibility export
)
from shuxueshuo_server.solver.math_kernel.proof_types import (
    ProofLimits,  # noqa: F401 - legacy compatibility export
    ProofNode,  # noqa: F401 - legacy compatibility export
    ProofResult,
    _Budget,
)


class LegacySearch(_Environment):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Child nodes were already charged while constructing their proofs.
        # Attachment still checks every certificate, with a separate validation
        # budget shared across branches. Independent replay uses one budget for
        # both parent and nested nodes through _Environment instead.
        self.witness_replay_budget = _Budget(self.budget.limits)
        self.cache, self.active = {}, set()

    def need(self, goal):
        if goal in self.cache:
            found = self.cache[goal]
            if found is None:
                raise ProofFailure(
                    "proof_missing", "no bounded proof for requested relation"
                )
            return found
        shared_key = (RULESET_HASH, self.context_hash, goal)
        if shared_key in self.budget.proven_goals:
            graph, root = self.budget.proven_goals[shared_key]
            imported = {}

            def attach(node_id):
                if node_id not in imported:
                    n = graph[node_id]
                    imported[node_id] = self.add(n.rule_id.removeprefix("math."), n.conclusion,
                                                 [attach(c) for c in n.children], n.certificate)
                return imported[node_id]

            # Recheck every imported rule against this request's source map.
            self.cache[goal] = attach(root)
            return self.cache[goal]
        if goal in self.active:
            raise ProofFailure("proof_missing", "cyclic proof dependency")
        if len(self.active) >= self.budget.limits.depth:
            raise ProofFailure("proof_limit", "proof depth limit")
        self.budget.use("attempts")
        self.active.add(goal)
        try:
            guards = [self.need(d) for d in domains(goal)]
            core = self.core(goal)
            result = self.add("guard", goal, (core, *guards))
            self.cache[goal] = result
            self.budget.proven_goals[shared_key] = (dict(self.by_id), result)
            return result
        except ProofFailure as exc:
            if exc.code == "proof_missing":
                # Failure through an active ancestor is context-dependent; do
                # not cache failures and suppress a later independent proof.
                pass
            raise
        finally:
            self.active.remove(goal)

    def attempt(self, function):
        self.budget.use("attempts")
        try:
            return function()
        except ProofFailure as exc:
            if exc.code != "proof_missing":
                raise
            return None

    def raw(self, rule, goal, required=(), cert=None):
        required = (
            tuple(required)
            if rule in {"sign", "scale", "equal_sign", "transitive"}
            else tuple(dict.fromkeys(required))
        )
        return self.add(rule, goal, tuple(self.need(g) for g in required), cert)

    def core(self, g):
        a = self.arithmetic
        for key, premise in self.premises.items():
            if premise == g:
                return self.add("given", g, certificate={"premise_id": key})
        if not names(g) and not (g[0] == ">=" and g[1][0] == "add"):
            sign, certificate = a.constant_certificate(_diff(g))
            if _holds(sign, g[0]):
                return self.add("constant", g, certificate=certificate)
            raise ProofFailure("proof_missing", "exact constant comparison is false")
        if g[0] != "=" and g[2] == ZERO:
            cancelled = _cancel_additive(g[1])
            if cancelled != g[1]:
                found = self.attempt(partial(
                    self.raw, "equal_sign", g,
                    [("=", g[1], cancelled), (g[0], cancelled, ZERO)],
                ))
                if found:
                    return found
            if g[0] == "<" and g[1][0] == "pow":
                exponent = signed_integer(g[1][2])
                if exponent is not None and exponent > 0 and exponent % 2 == 0:
                    raise ProofFailure("proof_missing", "a real even power cannot be negative")
        # Powers and positive constant denominators have direct sign
        # certificates. Try these before transporting signs through unrelated
        # equations; reciprocal domain checks need them before monotonicity.
        if g[0] != "=" and g[2] == ZERO and g[1][0] == "pow":
            found = self.attempt(partial(self.sign, g))
            if found:
                return found
        if g[0] != "=" and g[2] == ZERO and g[1][0] == "div":
            denominator = a.literal_rational(g[1][2])
            if denominator is not None and denominator > 0:
                found = self.attempt(partial(
                    self.raw, "sign", g,
                    [(g[0], g[1][1], ZERO), (">", g[1][2], ZERO)],
                ))
                if found:
                    return found
        if g[0] == "!=" and g[2] == ZERO and g[1][0] in {"mul", "div"}:
            found = self.attempt(
                partial(self.raw, "sign", g, [("!=", side, ZERO) for side in g[1][1:]])
            )
            if found:
                return found
        # Prefer exact, already-proved operand signs before transporting a
        # product through unrelated equations. Operands may be compound terms
        # such as a-b; symbol-only positivity heuristics miss these. This path
        # does not speculate about signs: the existing sign rule checks every
        # combination and its domain, using only verified premises.
        if g[0] != "=" and g[2] == ZERO and g[1][0] in {"add", "sub", "mul", "div"}:
            operand_signs = [
                [p for p in self.premises.values()
                 if p[0] in SIGNS and p[1] == operand and p[2] == ZERO]
                for operand in g[1][1:]
            ]
            for left_sign in operand_signs[0]:
                for right_sign in operand_signs[1]:
                    required = [left_sign, right_sign]
                    try:
                        self.check_sign(g, required, {})
                    except ProofFailure:
                        continue
                    return self.raw("sign", g, required)
        # Reuse the same algebraic relation before searching transports through
        # unrelated inequalities (which may introduce high-degree denominators).
        for premise in self.premises.values():
            # Adding an unchanged remainder may introduce extra parameters in
            # the written goal. The certified difference (and sign) is still
            # the same; do not search new AM-GM pairs before transporting it.
            if premise[0] != g[0] or g[0] == "=" or not names(premise) <= names(g):
                continue
            try:
                ratio = a.proportional(_diff(g), _diff(premise))
            except ProofFailure as exc:
                if exc.code == "proof_limit" and str(exc) == "polynomial degree limit":
                    continue
                raise
            if ratio and ratio > 0:
                found = self.attempt(
                    partial(self.raw, "weaken", g, [premise], {"ratio": str(ratio)})
                )
                if found:
                    return found
        ordered_target = _ordered(g)
        if ordered_target:
            for first in self.premises.values():
                a1 = _ordered(first)
                if not a1 or a.difference(("=", a1[1], ordered_target[1])):
                    continue
                for second in self.premises.values():
                    a2 = _ordered(second)
                    if (
                        a2
                        and not a.difference(("=", a1[2], a2[1]))
                        and not a.difference(("=", a2[2], ordered_target[2]))
                    ):
                        if ordered_target[0] == ">" and a1[0] == a2[0] == ">=":
                            continue
                        return self.raw("transitive", g, [first, second])
        ordered = _ordered(g)
        if ordered and all(e[0] in {"symbol", "rat"} for e in g[1:]):
            for premise in self.premises.values():
                first = _ordered(premise)
                if first and first[1] == ordered[1] and first[2] != ordered[2]:
                    second_op = ">=" if ordered[0] == ">=" or first[0] == ">" else ">"
                    found = self.attempt(
                        partial(
                            self.raw,
                            "transitive",
                            g,
                            [premise, (second_op, first[2], ordered[2])],
                        )
                    )
                    if found:
                        return found
        if g[0] == "!=":
            strict_ops = sorted(
                (">", "<"), key=lambda op: -((op, g[1], g[2]) in self.premises.values())
            )
            for strict in strict_ops:
                found = self.attempt(
                    partial(
                        self.raw, "weaken", g, [(strict, g[1], g[2])], {"ratio": "1"}
                    )
                )
                if found:
                    return found
        # Normalize positive literal numerators before reciprocal monotonicity;
        # e.g. 4/a^2 is exactly 1/(a^2/4), not a new proof rule.
        if g[0] in {">=", ">", "<=", "<"} and all(side[0] == "div" for side in g[1:]):
            numerators = [a.literal_rational(side[1]) for side in g[1:]]
            if all(n is not None and n > 0 for n in numerators) and any(
                n != 1 for n in numerators
            ):
                normalized = tuple(
                    expr(
                        "div", ONE, side[2] if n == 1 else expr("div", side[2], side[1])
                    )
                    for side, n in zip(g[1:], numerators)
                )
                found = self.attempt(
                    partial(
                        self.raw, "weaken", g, [(g[0], *normalized)], {"ratio": "1"}
                    )
                )
                if found:
                    return found
        if g[0] in {"<=", "<", ">=", ">"} and all(
            side[0] == "div" and side[1] == ONE for side in g[1:]
        ):
            x, y = g[1][2], g[2][2]
            found = self.attempt(
                partial(
                    self.raw,
                    "monotone",
                    g,
                    [(">", x, ZERO), (">", y, ZERO), (REVERSE[g[0]], x, y)],
                )
            )
            if found:
                return found
        # A submitted sum equation isolates the sign of the missing term.
        # Construct only these finite candidates; the existing equality/domain
        # and sign rules still certify every algebraic transport.
        if g[0] != "=" and g[2] != ZERO:
            for premise in self.premises.values():
                if premise[0] != "=":
                    continue
                for total, value in (premise[1:], premise[1:][::-1]):
                    if total[0] != "add" or value != g[2]:
                        continue
                    for i, j in ((1, 2), (2, 1)):
                        if total[i] == g[1]:
                            candidate = ("neg", total[j])
                            difference = (g[0], _diff(g), ZERO)
                            found = self.attempt(
                                partial(
                                    self.raw,
                                    "equal_sign",
                                    difference,
                                    [
                                        ("=", _diff(g), candidate),
                                        (g[0], candidate, ZERO),
                                    ],
                                )
                            )
                            if found:
                                self.cache[difference] = self.add(
                                    "guard",
                                    difference,
                                    (
                                        found,
                                        *(self.need(d) for d in domains(difference)),
                                    ),
                                )
                                return self.raw("difference", g, [difference])
        # Try only a single signed variable as multiplier before equation
        # transport (e.g. clearing a positive reciprocal denominator).
        if g[0] != "=":
            for premise in self.premises.values():
                if (
                    premise[0] == "="
                    or not names(premise) <= names(g)
                    or not any(n[0] == "div" for n in walk(premise))
                ):
                    continue
                for name in sorted(names(g)):
                    symbol = ("symbol", name)
                    if (">", symbol, ZERO) not in self.premises.values():
                        continue
                    for factor, op in ((symbol, ">"), (("neg", symbol), "<")):
                        if (
                            not {x * y for x in SIGNS[premise[0]] for y in SIGNS[op]}
                            <= SIGNS[g[0]]
                        ):
                            continue
                        if a.difference(
                            ("=", _diff(g), expr("mul", _diff(premise), factor))
                        ):
                            continue
                        difference = (g[0], _diff(g), ZERO)
                        found = self.raw(
                            "scale", difference, [premise, (op, factor, ZERO)]
                        )
                        if g[2] == ZERO:
                            return found
                        self.cache[difference] = self.add(
                            "guard",
                            difference,
                            (found, *(self.need(d) for d in domains(difference))),
                        )
                        return self.raw("difference", g, [difference])
        # Reordering a previously proved bound does not introduce a second
        # AM-GM application. Preserve that dependency before template search.
        for premise in self.premises.values():
            if (
                g[0] in {">", ">=", "<", "<="}
                and premise[0] == g[0]
                and a.difference(g)
                and not a.difference(("=", premise[1], g[1]))
                and not a.difference(("=", premise[2], g[2]))
            ):
                found = self.attempt(
                    partial(self.raw, "weaken", g, [premise], {"ratio": "1"})
                )
                if found:
                    return found
        ordered_goal = _ordered(g)
        if ordered_goal:
            for equality in self.premises.values():
                if equality[0] != "=":
                    continue
                for left, right in (equality[1:], equality[1:][::-1]):
                    if a.difference(("=", ordered_goal[1], left)):
                        continue
                    for bound in self.premises.values():
                        ordered = _ordered(bound)
                        if (
                            ordered
                            and ordered[0] == ordered_goal[0]
                            and not a.difference(("=", ordered[1], right))
                            and not a.difference(("=", ordered[2], ordered_goal[2]))
                        ):
                            return self.raw(
                                "equality_bound_transport", g, [equality, bound]
                            )
        if g[0] == ">=" and g[1][0] == "add":
            try:
                required = self.amgm_requirements("two_term_amgm", g, {})
            except ProofFailure as exc:
                if exc.code != "invalid_proof":
                    raise
            else:
                return self.raw("two_term_amgm", g, required)
        if (
            g[0] == ">="
            and g[2] != ZERO
            and not any(p[0] == g[0] and p[2] == g[2] for p in self.premises.values())
        ):
            # Finite structural candidates only; the equality subproofs certify
            # the unchanged context and any simplification of the radical.
            from shuxueshuo_server.solver.math_kernel.local_amgm import candidates

            matches = []
            for u, v, rest, scale in candidates(g[1]):
                reduced = expr("sub", expr("div", g[2], scale), rest)
                square = (
                    "=",
                    expr("pow", reduced, number(2)),
                    expr("mul", number(4), expr("mul", u, v)),
                )
                # A necessary algebraic check filters unrelated pairs before
                # recursive sign search. This check never authorizes a bound.
                if (
                    a.difference(square)
                    and not any(p[0] == "=" for p in self.premises.values())
                    and not any(n[0] == "sqrt" for n in walk(square))
                ):
                    continue
                found = self.attempt(partial(self.polynomial, square))
                if not found:
                    continue
                required = self.local_amgm_requirements(g, u, v, rest, scale)
                result = self.attempt(
                    partial(
                        self.raw,
                        "local_two_term_amgm",
                        g,
                        required,
                        {"u": u, "v": v, "rest": rest, "scale": scale},
                    )
                )
                if result:
                    matches.append(result)
            if len(matches) > 1:
                raise ProofFailure(
                    "inequality_ambiguous",
                    "multiple local AM-GM pairs; split the submitted relation",
                )
            if matches:
                return matches[0]
        if g[0] == "<=":
            for key, premise in self.premises.items():
                if premise[0] != ">=" or premise[1][0] != "add":
                    continue
                try:
                    required = self.amgm_requirements("two_term_amgm", premise, {})
                except ProofFailure as exc:
                    if exc.code != "invalid_proof":
                        raise
                    continue
                u, v = premise[1][1:]
                rhs = expr("div", expr("pow", expr("add", u, v), number(2)), number(4))
                if not a.difference(
                    ("=", g[1], expr("mul", u, v))
                ) and not a.difference(("=", g[2], rhs)):
                    return self.raw(
                        "amgm_squared_bound",
                        g,
                        [premise, *required],
                        {"amgm_premise": key},
                    )
        if g[0] == "<=":
            try:
                required = self.amgm_requirements("two_term_product_bound", g, {})
            except ProofFailure as exc:
                if exc.code != "invalid_proof":
                    raise
            else:
                return self.raw("two_term_product_bound", g, required)
            for key in self.premises:
                cert = {"sum_premise": key}
                try:
                    required = self.amgm_requirements(
                        "fixed_sum_product_bound", g, cert
                    )
                except ProofFailure as exc:
                    if exc.code != "invalid_proof":
                        raise
                else:
                    return self.raw("fixed_sum_product_bound", g, required, cert)
        if not names(g):
            sign, certificate = a.constant_certificate(_diff(g))
            if _holds(sign, g[0]):
                return self.add("constant", g, certificate=certificate)
            raise ProofFailure("proof_missing", "exact constant comparison is false")
        # Even powers are nonnegative irrespective of their base's sign.
        # Prefer that direct certificate before unrelated equation transport.
        if g[2] == ZERO and g[0] in {">", ">=", "!="}:
            e = g[1]

            def even_power(n):
                return (
                    n[0] == "pow"
                    and (signed_integer(n[2]) or 0) > 0
                    and signed_integer(n[2]) % 2 == 0
                )

            if even_power(e) and g[0] == ">=":
                return self.raw("sign", g)
            if e[0] == "add":
                for i, j in ((1, 2), (2, 1)):
                    literal = a.literal_rational(e[j])
                    if even_power(e[i]) and literal is not None and literal > 0:
                        children = [(">=", e[i], ZERO), (">", e[j], ZERO)]
                        if i == 2:
                            children.reverse()
                        return self.raw("sign", g, children)
        # Cheap positive arithmetic/domain guards precede polynomial transport.
        # In particular an unrelated bound must not exhaust the budget while
        # checking a+b != 0 from a>0,b>0.
        if (
            g[2] == ZERO
            and g[0] in {">", ">=", "<", "<=", "!="}
            and g[1][0] in {"add", "mul", "div", "pow", "sqrt", "neg"}
            and all(n[0] != "sub" for n in walk(g[1]))
            and all(
                (">", ("symbol", name), ZERO) in self.premises.values()
                for name in names(g[1])
            )
        ):
            found = self.attempt(partial(self.sign, g))
            if found:
                return found
        for premise in self.premises.values():
            ratio = a.proportional(_diff(g), _diff(premise))
            if (
                ratio
                and {x * (1 if ratio > 0 else -1) for x in SIGNS[premise[0]]}
                <= SIGNS[g[0]]
            ):
                found = self.attempt(
                    partial(self.raw, "weaken", g, [premise], {"ratio": str(ratio)})
                )
                if found:
                    return found
        if g[0] != "=" and g[2] == ZERO:
            for premise in self.premises.values():
                if premise[0] != "=":
                    continue
                for left, right in (premise[1:], premise[1:][::-1]):
                    if left == g[1] and left not in tuple(walk(right)):
                        found = self.attempt(
                            partial(
                                self.raw,
                                "equal_sign",
                                g,
                                [("=", left, right), (g[0], right, ZERO)],
                            )
                        )
                        if found:
                            return found
        if (
            g[0] != "="
            and g[2] != ZERO
            and any(
                p[0] == "=" and _diff(g) in tuple(walk(p))
                for p in self.premises.values()
            )
        ):
            found = self.attempt(
                partial(
                    self.raw,
                    "difference",
                    g,
                    [(g[0], _diff(g), ZERO)],
                )
            )
            if found:
                return found
        # A factor explicitly present in an equation can inherit a sign from
        # the other side and its cofactor. This is finite algebraic transport,
        # not equation solving: e.g. P/c=d gives P=c*d, with all domains proved.
        # Try it before reducing against unrelated signed premises.
        if g[2] == ZERO and g[0] in {">", "<", ">=", "<=", "!="}:
            for premise in self.premises.values():
                if premise[0] != "=":
                    continue
                for side, other in (premise[1:], premise[1:][::-1]):
                    candidate = None
                    if side[0] == "div":
                        if side[1] == g[1]:
                            candidate = expr("mul", other, side[2])
                        elif side[2] == g[1]:
                            candidate = expr("div", side[1], other)
                    elif side[0] == "mul":
                        if side[1] == g[1]:
                            candidate = expr("div", other, side[2])
                        elif side[2] == g[1]:
                            candidate = expr("div", other, side[1])
                    if candidate is None or g[1] in tuple(walk(candidate)):
                        continue
                    found = self.attempt(
                        partial(
                            self.raw,
                            "equal_sign",
                            g,
                            [("=", g[1], candidate), (g[0], candidate, ZERO)],
                        )
                    )
                    if found:
                        return found
        # Move an already proved inequality through an equality. The equality
        # of differences is certified by bounded polynomial reduction, with
        # all original domains still guarded. Never trust a textual rewrite.
        if any(p[0] == "=" for p in self.premises.values()) and (
            g[0] != "="
            or (
                not any(n[0] == "sqrt" for n in walk(g))
                and any(
                    p[0] == "=" and any(side[0] == "symbol" for side in p[1:])
                    for p in self.premises.values()
                )
            )
        ):
            for premise in sorted(self.premises.values(), key=lambda p: p[2] != g[2]):
                if (premise[0] == "=") != (g[0] == "="):
                    continue
                for ratio in (Q(1), Q(-1)):
                    if (
                        not {s * (1 if ratio > 0 else -1) for s in SIGNS[premise[0]]}
                        <= SIGNS[g[0]]
                    ):
                        continue
                    equality = (
                        "=",
                        _diff(g),
                        expr("mul", number(ratio), _diff(premise)),
                    )
                    # Only try a direct polynomial certificate, not recursive
                    # sign search for every unrelated source inequality.
                    found = self.attempt(partial(self.polynomial, equality))
                    if found:
                        guards = tuple(self.need(d) for d in domains(equality))
                        self.cache[equality] = self.add(
                            "guard", equality, (found, *guards)
                        )
                        return self.raw(
                            "relation_transport",
                            g,
                            [premise, equality],
                            {"ratio": str(ratio)},
                        )
        if g[0] == "=":
            if (
                g[1][0] == "pow"
                and g[1][1][0] == "sqrt"
                and signed_integer(g[1][2]) == 2
                and g[2] == g[1][1][1]
            ):
                return self.raw("root_square", g, [(">=", g[2], ZERO)])
            found = self.attempt(partial(self.polynomial, g))
            if found:
                return found
            if (
                g[1] != ZERO
                and g[2] != ZERO
                and g[1][0] != "pow"
                and g[2][0] != "pow"
                and (
                    any(n[0] == "sqrt" for n in walk(g))
                    or any(
                        p[0] == "=" and any(n[0] == "pow" for n in walk(p))
                        for p in self.premises.values()
                    )
                )
            ):
                required = [
                    (">=", g[1], ZERO),
                    (">=", g[2], ZERO),
                    ("=", ("pow", g[1], number(2)), ("pow", g[2], number(2))),
                ]
                found = self.attempt(partial(self.raw, "square_equal", g, required))
                if found:
                    return found
        if g[1][0] == g[2][0] == "sqrt":
            found = self.attempt(
                partial(self.raw, "monotone", g, [(g[0], g[1][1], g[2][1])])
            )
            if found:
                return found
        if g[1][:2] == g[2][:2] == ("div", ONE):
            required = [
                (">", g[1][2], ZERO),
                (">", g[2][2], ZERO),
                (REVERSE[g[0]], g[1][2], g[2][2]),
            ]
            found = self.attempt(partial(self.raw, "monotone", g, required))
            if found:
                return found
        if g[2] != ZERO:
            return self.raw("difference", g, [(g[0], _diff(g), ZERO)])
        if g[0] == "!=" and g[2] == ZERO:
            for premise in self.premises.values():
                for product in (premise[1], premise[2], _diff(premise)):
                    if product != g[1] and g[1] in _factors(product):
                        found = self.attempt(
                            partial(
                                self.raw, "factor_nonzero", g, [("!=", product, ZERO)]
                            )
                        )
                        if found:
                            return found
        # Prefer a directly certified product sign before polynomial expansion.
        if g[1][0] == "mul":
            for left in self.premises.values():
                for right in self.premises.values():
                    if left[1:] == (g[1][1], ZERO) and right[1:] == (g[1][2], ZERO):
                        try:
                            self.check_sign(g, [left, right], {})
                        except ProofFailure:
                            continue
                        found = self.attempt(
                            partial(self.raw, "sign", g, [left, right])
                        )
                        if found:
                            return found
        # Exact polynomial multiples of a signed premise preserve or reverse
        # its sign only after the multiplier sign has itself been proved.
        for key, premise in self.premises.items():
            if premise[0] == "=":
                continue
            factor = a.factor(g[1], _diff(premise))
            if factor is None:
                continue
            scale_ops = [">", "<", ">=", "<=", "!=", "="]
            scale_ops.sort(
                key=lambda op: -((op, factor, ZERO) in self.premises.values())
            )
            for op in scale_ops:
                possible = {x * y for x in SIGNS[premise[0]] for y in SIGNS[op]}
                if possible <= SIGNS[g[0]]:
                    found = self.attempt(
                        partial(self.raw, "scale", g, [premise, (op, factor, ZERO)])
                    )
                    if found:
                        return found
        found = self.attempt(partial(self.sign, g))
        if found:
            return found
        found = self.attempt(partial(self.interval, g))
        if found:
            return found
        # Transfer a known sign across an explicitly supplied equation.
        for premise in self.premises.values():
            if premise[0] == "=":
                for left, right in (premise[1:], premise[1:][::-1]):
                    if left == g[1] and right != left:
                        found = self.attempt(
                            partial(
                                self.raw,
                                "equal_sign",
                                g,
                                [("=", left, right), (g[0], right, ZERO)],
                            )
                        )
                        if found:
                            return found
        found = self.attempt(partial(self.substitution, g))
        if found:
            return found
        raise ProofFailure("proof_missing", "no registered rule proves the relation")

    def polynomial(self, g):
        a = self.arithmetic
        equations = [
            (key, p) for key, p in self.premises.items() if p[0] == "=" and p != g
        ]
        # Eliminate an explicitly isolated variable before general equations.
        # This is a deterministic divisor order, not equation solving.
        equations.sort(
            key=lambda item: not any(side[0] == "symbol" for side in item[1][1:])
        )
        if len(equations) > self.budget.limits.equations:
            # Restated identities and scalar multiples add no polynomial
            # constraint. Only remove premises; never invent an equation.
            unique = {}
            for item in equations:
                divisor = a.equation_divisor(item[1])
                if not divisor:
                    continue
                leading = divisor[min(divisor)]
                key = tuple(sorted((m, c / leading) for m, c in divisor.items()))
                unique.setdefault(key, item)
            equations = list(unique.values())
        # First try an identity independent of premises; unused equations must
        # not create unnecessary domain or provenance dependencies.
        for selected in ([], equations):
            if len(selected) > self.budget.limits.equations:
                raise ProofFailure("proof_limit", "equation premise budget")
            roots = a.roots([g, *(p for _, p in selected)])
            divisors = [a.equation_divisor(p) for _, p in selected] + [
                a.root_polynomial(r) for r in roots.values()
            ]
            quotients, remainder = a.reduce(a.difference(g), divisors)
            if remainder:
                quotients = a.linear_combination(a.difference(g), divisors)
                if quotients is None:
                    continue
            used = [item for item, quotient in zip(selected, quotients) if quotient]
            if len(used) != len(selected):
                selected = used
                roots = a.roots([g, *(p for _, p in selected)])
                divisors = [a.equation_divisor(p) for _, p in selected] + [
                    a.root_polynomial(r) for r in roots.values()
                ]
                quotients, remainder = a.reduce(a.difference(g), divisors)
                if remainder:
                    quotients = a.linear_combination(a.difference(g), divisors)
                    if quotients is None:
                        continue
            required = [p for _, p in selected] + [
                claim for r in roots.values() for claim in _root_claims(r)
            ]
            cert = {
                "equations": [k for k, _ in selected],
                "roots": list(roots),
                "multipliers": [a.encode(q) for q in quotients],
            }
            return self.raw("polynomial", g, required, cert)
        raise ProofFailure("proof_missing", "polynomial remainder is nonzero")

    def sign(self, g):
        e, op = g[1], g[0]
        kind = e[0]
        if kind == "neg":
            return self.raw("sign", g, [(REVERSE[op], e[1], ZERO)])
        if kind == "pow":
            exponent = signed_integer(e[2])
            if exponent == 0 and 1 in SIGNS[op]:
                return self.raw("sign", g)
            if exponent > 0 and exponent % 2 == 0 and {0, 1} <= SIGNS[op]:
                return self.raw("sign", g)
            options = ["!=", "=", ">", "<", ">=", "<="] if exponent % 2 == 0 else [op]
            for required in options:
                possible = {abs(s) if exponent % 2 == 0 else s for s in SIGNS[required]}
                if possible <= SIGNS[op] and (
                    exponent >= 0 or 0 not in SIGNS[required]
                ):
                    found = self.attempt(
                        partial(self.raw, "sign", g, [(required, e[1], ZERO)])
                    )
                    if found:
                        return found
        if kind == "sqrt":
            required = op if op in {">", ">=", "="} else ">" if op == "!=" else "="
            if op != "<":
                return self.raw("sign", g, [(required, e[1], ZERO)])
        if kind in {"add", "sub", "mul", "div"}:
            # Short, deterministic sufficient sign combinations. Opposite sums
            # need an explicit relation/interval rule, never numerical probing.
            options = [
                (">", ">"),
                ("<", "<"),
                (">=", ">="),
                ("<=", "<="),
                (">", ">="),
                (">=", ">"),
                ("<", "<="),
                ("<=", "<"),
                (">", "<"),
                ("<", ">"),
                ("!=", "!="),
                ("=", "!="),
                ("=", "="),
                (">=", "<"),
                ("<=", ">"),
                (">", "<="),
                ("<", ">="),
            ]
            # Prefer already certified operand signs over speculative strict
            # signs (a square may be zero at the extremum).
            options.sort(
                key=lambda pair: (
                    -sum(
                        (op, operand, ZERO) in self.premises.values()
                        for op, operand in zip(pair, e[1:])
                    )
                )
            )
            for x, y in options:
                children = [(x, e[1], ZERO), (y, e[2], ZERO)]
                try:
                    self.check_sign(g, children, {})
                except ProofFailure:
                    continue
                found = self.attempt(partial(self.raw, "sign", g, children))
                if found:
                    return found
        raise ProofFailure("proof_missing", "structural signs insufficient")

    def interval(self, g):
        if len(names(g)) != 1:
            raise ProofFailure("proof_missing", "no univariate interval")
        name = next(iter(names(g)))
        bounds = self.bounds()
        for lo in bounds.get((name, "lower"), []):
            for hi in bounds.get((name, "upper"), []):
                cert = self.interval_certificate(_diff(g), lo[1], hi[1])
                values = [Q(v) for v in cert["values"]]
                possible = (
                    {0}
                    if min(values) == max(values) == 0
                    else {1}
                    if min(values) > 0
                    else {-1}
                    if max(values) < 0
                    else {0, 1}
                    if min(values) >= 0
                    else {-1, 0}
                    if max(values) <= 0
                    else {-1, 0, 1}
                )
                if possible <= SIGNS[g[0]]:
                    return self.raw(
                        "interval",
                        g,
                        [self.premises[lo[1]], self.premises[hi[1]]],
                        cert,
                    )
        raise ProofFailure("proof_missing", "interval sign not established")

    def substitution(self, g):
        mapping, bindings, equations = {}, [], []
        for key, p in self.premises.items():
            if p[0] != "=":
                continue
            for side in (1, 2):
                if (
                    p[side][0] == "symbol"
                    and p[side][1] in names(g)
                    and p[side][1] not in names(p[3 - side])
                ):
                    name = p[side][1]
                    if name not in mapping:
                        mapping[name] = p[3 - side]
                        bindings.append({"premise_id": key, "side": side})
                        equations.append(p)
                    break
        if not mapping:
            raise ProofFailure("proof_missing", "no substitution")
        _noncyclic(mapping)
        return self.raw(
            "substitution",
            g,
            [*equations, substitute(g, mapping)],
            {"bindings": bindings},
        )



def run_request(context, request, *, budget=None):
    env = LegacySearch(context, request, budget=budget)
    roots = []
    for g in _roots_for_request(env):
        roots.append(env.add("all", g, tuple(env.need(h) for h in g[1:]))) if g[0] == "all" else roots.append(env.need(g))
    return ProofResult("proved", proof=env.payload(roots))


class HistoricalRequests:
    """Tool-only injection for old baselines, including already imported aliases."""

    def __enter__(self):
        import sys
        from contextlib import ExitStack
        from unittest.mock import patch

        from shuxueshuo_server.solver.math_kernel import proof_kernel

        original = proof_kernel._run_request
        targets = [module for name, module in tuple(sys.modules.items())
                   if name.startswith("shuxueshuo_server.solver.math_kernel.")
                   and getattr(module, "_run_request", None) is original]
        self.stack = ExitStack()
        for module in targets:
            self.stack.enter_context(patch.object(module, "_run_request", run_request))
        return self

    def __exit__(self, *exc):
        return self.stack.__exit__(*exc)
