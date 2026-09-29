"""Bounded-real search capabilities. Scheduling lives in proof_search.

These constructors only propose existing rules; _Environment.add checks every
node. Historical search is archived in tools only and is never a runtime fallback.
"""

from __future__ import annotations

from fractions import Fraction as Q
from functools import partial

from .proof_algebra import (
    ONE,
    ZERO,
    Arithmetic,
    ProofFailure,
    domains,
    expr,
    names,
    number,
    signed_integer,
    substitute,
    walk,
)
from .proof_checker import (
    REVERSE,
    RULESET_HASH,
    RULESET_VERSION,
    SIGNS,
    _cancel_additive,
    _diff,
    _Environment,
    _factors,
    _holds,
    _noncyclic,
    _ordered,
    _root_claims,
)


class SearchArithmetic(Arithmetic):
    """Count algebra operations in addition to legacy reductions/structure caps."""

    def constant(self, *args, **kwargs):
        self.budget.use("arithmetic_operations")
        return super().constant(*args, **kwargs)

    def add(self, *args, **kwargs):
        self.budget.use("arithmetic_operations")
        return super().add(*args, **kwargs)

    def mul(self, *args, **kwargs):
        self.budget.use("arithmetic_operations")
        return super().mul(*args, **kwargs)

    def power(self, *args, **kwargs):
        self.budget.use("arithmetic_operations")
        return super().power(*args, **kwargs)

    def rational(self, *args, **kwargs):
        self.budget.use("arithmetic_operations")
        return super().rational(*args, **kwargs)

    def difference(self, *args, **kwargs):
        self.budget.use("arithmetic_operations")
        return super().difference(*args, **kwargs)

    def equation_divisor(self, *args, **kwargs):
        self.budget.use("arithmetic_operations")
        return super().equation_divisor(*args, **kwargs)

    def exact_quotient(self, *args, **kwargs):
        self.budget.use("arithmetic_operations")
        return super().exact_quotient(*args, **kwargs)

    def polynomial_gcd(self, *args, **kwargs):
        self.budget.use("arithmetic_operations")
        return super().polynomial_gcd(*args, **kwargs)

    def reduce(self, *args, **kwargs):
        self.budget.use("arithmetic_operations")
        return super().reduce(*args, **kwargs)

    def linear_combination(self, *args, **kwargs):
        self.budget.use("arithmetic_operations")
        return super().linear_combination(*args, **kwargs)

    def factor(self, *args, **kwargs):
        self.budget.use("arithmetic_operations")
        return super().factor(*args, **kwargs)

    def proportional(self, *args, **kwargs):
        self.budget.use("arithmetic_operations")
        return super().proportional(*args, **kwargs)

    def constant_interval(self, *args, **kwargs):
        self.budget.use("arithmetic_operations")
        return super().constant_interval(*args, **kwargs)

    def constant_certificate(self, value, *, supplied=None):
        self.budget.use("arithmetic_operations")
        # Exact constants depend on neither Scope nor premises. Candidate
        # construction may reuse their isolating certificate; independent
        # checker replay uses Arithmetic and recomputes it from scratch.
        ledger = getattr(self.budget, "parent", None) or self.budget
        if not hasattr(ledger, "constant_certificates"):
            ledger.constant_certificates = {}
        cache = ledger.constant_certificates
        key = (value, self.limits)
        if key in cache and (supplied is None or cache[key][1] == supplied):
            from copy import deepcopy

            return deepcopy(cache[key])
        result = super().constant_certificate(value, supplied=supplied)
        if len(cache) >= 64:
            cache.pop(next(iter(cache)))
        from copy import deepcopy

        cache[key] = deepcopy(result)
        return result


class RealSearchTools(_Environment):
    def raw(self, rule, goal, required=(), cert=None):
        required = (
            tuple(required)
            if rule in {"sign", "scale", "equal_sign", "transitive"}
            else tuple(dict.fromkeys(required))
        )
        return self.add(rule, goal, tuple(self.need(g) for g in required), cert)

    def polynomial(self, g, *, identities_only=False):
        a = self.arithmetic
        equations = [
            (key, p)
            for key, p in self.premises.items()
            if p[0] == "=" and p != g and not identities_only
        ]
        equations.sort(
            key=lambda item: not any(side[0] == "symbol" for side in item[1][1:])
        )
        if len(equations) > self.budget.limits.equations:
            unique = {}
            for item in equations:
                divisor = a.equation_divisor(item[1])
                if not divisor:
                    continue
                leading = divisor[min(divisor)]
                key = tuple(sorted(((m, c / leading) for m, c in divisor.items())))
                unique.setdefault(key, item)
            equations = list(unique.values())
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
        e, op = (g[1], g[0])
        kind = e[0]
        if kind == "neg":
            return self.raw("sign", g, [(REVERSE[op], e[1], ZERO)])
        if kind == "pow":
            exponent = signed_integer(e[2])
            if exponent == 0 and 1 in SIGNS[op]:
                return self.raw("sign", g)
            if exponent > 0 and exponent % 2 == 0 and ({0, 1} <= SIGNS[op]):
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
            options.sort(
                key=lambda pair: (
                    -sum(
                        (
                            (op, operand, ZERO) in self.premises.values()
                            for op, operand in zip(pair, e[1:])
                        )
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

    def substitution(self, g, *, ground_only=False):
        mapping, bindings, equations = ({}, [], [])
        pending = set(names(g))
        available = list(self.premises.items())
        for _ in range(len(self.symbols)):
            for key, p in available:
                if p[0] != "=":
                    continue
                for side in (1, 2):
                    if (
                        p[side][0] == "symbol"
                        and p[side][1] in pending
                        and (p[side][1] not in names(p[3 - side]))
                    ):
                        name = p[side][1]
                        if name not in mapping:
                            mapping[name] = p[3 - side]
                            bindings.append({"premise_id": key, "side": side})
                            equations.append(p)
                            pending.update(names(p[3 - side]))
                        break
        if not mapping:
            raise ProofFailure("proof_missing", "no substitution")
        _noncyclic(mapping)
        replaced = substitute(g, mapping)
        if ground_only:
            # Eligibility follows the entire acyclic dependency graph. Keep the
            # one-step substitution below: the checker and historical proofs
            # still verify every equation and each intermediate substitution.
            unresolved = set(names(replaced))
            visited = set()
            while unresolved:
                name = unresolved.pop()
                if name not in mapping:
                    return None
                if name not in visited:
                    visited.add(name)
                    unresolved.update(names(mapping[name]) - visited)
        return self.raw(
            "substitution",
            g,
            [*equations, replaced],
            {"bindings": bindings},
        )


def given(self, g):
    for key, premise in self.premises.items():
        if premise == g:
            return self.add("given", g, certificate={"premise_id": key})


def verified_fragment(self, g):
    return self.seed_provider(self, g) if self.seed_provider else None


def constant(self, g):
    a = self.arithmetic
    if not names(g) and (not (g[0] == ">=" and g[1][0] == "add")):
        sign, certificate = a.constant_certificate(_diff(g))
        if _holds(sign, g[0]):
            return self.add("constant", g, certificate=certificate)
        raise ProofFailure("proof_missing", "exact constant comparison is false")


def cancel_sign(self, g):
    if g[0] != "=" and g[2] == ZERO:
        cancelled = _cancel_additive(g[1])
        if cancelled != g[1]:
            found = self.attempt(
                partial(
                    self.raw,
                    "equal_sign",
                    g,
                    [("=", g[1], cancelled), (g[0], cancelled, ZERO)],
                )
            )
            if found:
                return found
        if g[0] == "<" and g[1][0] == "pow":
            exponent = signed_integer(g[1][2])
            if exponent is not None and exponent > 0 and (exponent % 2 == 0):
                raise ProofFailure(
                    "proof_missing", "a real even power cannot be negative"
                )


def power_sign(self, g):
    if g[0] != "=" and g[2] == ZERO and (g[1][0] == "pow"):
        found = self.attempt(partial(self.sign, g))
        if found:
            return found


def positive_denominator(self, g):
    a = self.arithmetic
    if g[0] != "=" and g[2] == ZERO and (g[1][0] == "div"):
        denominator = a.literal_rational(g[1][2])
        if denominator is not None and denominator > 0:
            found = self.attempt(
                partial(
                    self.raw, "sign", g, [(g[0], g[1][1], ZERO), (">", g[1][2], ZERO)]
                )
            )
            if found:
                return found


def nonzero_product(self, g):
    if g[0] == "!=" and g[2] == ZERO and (g[1][0] in {"mul", "div"}):
        found = self.attempt(
            partial(self.raw, "sign", g, [("!=", side, ZERO) for side in g[1][1:]])
        )
        if found:
            return found


def operand_signs(self, g):
    if g[0] != "=" and g[2] == ZERO and (g[1][0] in {"add", "sub", "mul", "div"}):
        operand_signs = [
            [
                p
                for p in self.premises.values()
                if p[0] in SIGNS and p[1] == operand and (p[2] == ZERO)
            ]
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


def positive_components(self, g):
    """Compose positive subexpressions without searching unrelated sign cases.

    A known positive composite (e.g. z-h) is a leaf, just like a positive
    variable. This is structural matching only; every edge uses the sign checker.
    """
    if g[0] not in {">", ">=", "!="} or g[2] != ZERO or g[1][0] not in {"add", "mul", "div"}:
        return None
    known = set(self.premises.values())

    def positive(e):
        if (">", e, ZERO) in known or (">", e, ZERO) in self.cache:
            return True
        if e[0] == "rat":
            return Q(int(e[1]), int(e[2])) > 0
        return e[0] in {"add", "mul", "div"} and all(positive(c) for c in e[1:])

    if all(positive(c) for c in g[1][1:]):
        return self.raw("sign", g, [(">", c, ZERO) for c in g[1][1:]])


def nonnegative_components(self, g):
    """Compose explicit weak signs without first guessing strict positivity."""
    known = set(self.premises.values())

    def nonnegative(e):
        if any((op, e, ZERO) in known for op in (">", ">=", "=")):
            return True
        if e[0] == "rat":
            return Q(int(e[1]), int(e[2])) >= 0
        if e[0] == "sqrt":
            # Principal roots are nonnegative on their domain. Do not search
            # for strict positivity of the radicand just to prove a weak sign.
            # raw/need still prove the domain and replay the root/sign rules.
            return True
        if e[0] == "pow":
            exponent = signed_integer(e[2])
            return exponent is not None and exponent > 0 and exponent % 2 == 0
        return e[0] in {"add", "mul"} and all(nonnegative(c) for c in e[1:])

    if all(nonnegative(c) for c in g[1][1:]):
        return self.raw("sign", g, [(">=", c, ZERO) for c in g[1][1:]])


def same_difference(self, g):
    a = self.arithmetic
    for premise in self.premises.values():
        if premise[0] != g[0] or g[0] == "=" or (not names(premise) <= names(g)):
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
        # Rationally identical left sides with differently written algebraic
        # constants need a radical identity, not a search through equations.
        if not a.difference(("=", g[1], premise[1])):
            equality = ("=", _diff(g), expr("mul", ONE, _diff(premise)))
            found = self.attempt(
                partial(self.polynomial, equality, identities_only=True)
            )
            if found:
                guards = tuple(self.need(d) for d in domains(equality))
                self.cache[equality] = self.add("guard", equality, (found, *guards))
                return self.raw(
                    "relation_transport", g, [premise, equality], {"ratio": "1"}
                )


def known_transitivity(self, g):
    a = self.arithmetic
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
                    and (not a.difference(("=", a1[2], a2[1])))
                    and (not a.difference(("=", a2[2], ordered_target[2])))
                ):
                    if ordered_target[0] == ">" and a1[0] == a2[0] == ">=":
                        continue
                    return self.raw("transitive", g, [first, second])
            # A known local bound may carry the same remainder on both sides:
            # F >= R+U and U >= V imply F >= R+V. Match the difference exactly
            # before constructing the intermediate; do not search for a new
            # AM-GM pair inside F or assume the remainder is nonnegative.
            for second in self.premises.values():
                a2 = _ordered(second)
                if not a2 or (ordered_target[0] == ">" and a1[0] == a2[0] == ">="):
                    continue
                bridge = (a2[0], a1[2], ordered_target[2])
                if a.difference(("=", _diff(bridge), _diff(a2))):
                    continue
                if second[0] in {"<", "<="}:
                    bridge = (second[0], bridge[2], bridge[1])
                root = self.raw("weaken", bridge, [second], {"ratio": "1"})
                guards = tuple(self.need(d) for d in domains(bridge))
                self.cache[bridge] = self.add("guard", bridge, (root, *guards))
                return self.raw("transitive", g, [first, bridge])


def scalar_transitivity(self, g):
    ordered = _ordered(g)
    if ordered and all(e[0] in {"symbol", "rat"} for e in g[1:]):
        for premise in self.premises.values():
            first = _ordered(premise)
            if first and first[1] == ordered[1] and (first[2] != ordered[2]):
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


def strict_nonzero(self, g):
    if g[0] == "!=":
        strict_ops = sorted(
            (">", "<"), key=lambda op: -((op, g[1], g[2]) in self.premises.values())
        )
        for strict in strict_ops:
            found = self.attempt(
                partial(self.raw, "weaken", g, [(strict, g[1], g[2])], {"ratio": "1"})
            )
            if found:
                return found


def normalize_reciprocal(self, g):
    a = self.arithmetic
    if g[0] in {">=", ">", "<=", "<"} and all(side[0] == "div" for side in g[1:]):
        numerators = [a.literal_rational(side[1]) for side in g[1:]]
        if all(n is not None and n > 0 for n in numerators) and any(
            n != 1 for n in numerators
        ):
            normalized = tuple(
                (
                    expr(
                        "div", ONE, side[2] if n == 1 else expr("div", side[2], side[1])
                    )
                    for side, n in zip(g[1:], numerators)
                )
            )
            found = self.attempt(
                partial(self.raw, "weaken", g, [(g[0], *normalized)], {"ratio": "1"})
            )
            if found:
                return found


def reciprocal_monotone(self, g):
    if g[0] in {"<=", "<", ">=", ">"} and all(
        side[0] == "div" and side[1] == ONE for side in g[1:]
    ):
        x, y = (g[1][2], g[2][2])
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


def sum_sign_transport(self, g):
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
                                [("=", _diff(g), candidate), (g[0], candidate, ZERO)],
                            )
                        )
                        if found:
                            self.cache[difference] = self.add(
                                "guard",
                                difference,
                                (found, *(self.need(d) for d in domains(difference))),
                            )
                            return self.raw("difference", g, [difference])


def signed_variable_scale(self, g):
    a = self.arithmetic
    if g[0] != "=":
        for premise in self.premises.values():
            if (
                premise[0] == "="
                or not names(premise) <= names(g)
                or (not any(n[0] == "div" for n in walk(premise)))
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
                    found = self.raw("scale", difference, [premise, (op, factor, ZERO)])
                    if g[2] == ZERO:
                        return found
                    self.cache[difference] = self.add(
                        "guard",
                        difference,
                        (found, *(self.need(d) for d in domains(difference))),
                    )
                    return self.raw("difference", g, [difference])


def reorder_bound(self, g):
    a = self.arithmetic
    for premise in self.premises.values():
        if (
            g[0] in {">", ">=", "<", "<="}
            and premise[0] == g[0]
            and a.difference(g)
            and (not a.difference(("=", premise[1], g[1])))
            and (not a.difference(("=", premise[2], g[2])))
        ):
            found = self.attempt(
                partial(self.raw, "weaken", g, [premise], {"ratio": "1"})
            )
            if found:
                return found


def equality_bound(self, g):
    a = self.arithmetic
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
                        and (not a.difference(("=", ordered[1], right)))
                        and (not a.difference(("=", ordered[2], ordered_goal[2])))
                    ):
                        return self.raw(
                            "equality_bound_transport", g, [equality, bound]
                        )


def endpoint_transport(self, g):
    ordered_goal = _ordered(g)
    if not ordered_goal:
        return
    for premise in self.premises.values():
        ordered = _ordered(premise)
        if (ordered and ordered[0] == ordered_goal[0]
                and ordered[2] == ordered_goal[2]
                and ordered[1] != ordered_goal[1]):
            equality = ("=", ordered_goal[1], ordered[1])
            found = self.attempt(partial(
                self.raw, "equality_bound_transport", g, [equality, premise]))
            if found:
                return found


def sum_bound(self, g):
    if g[0] == ">=" and g[1][0] == "add":
        try:
            required = self.amgm_requirements("two_term_amgm", g, {})
        except ProofFailure as exc:
            if exc.code != "invalid_proof":
                raise
        else:
            return self.raw("two_term_amgm", g, required)


def local_sum_bound(self, g):
    a = self.arithmetic
    if (
        g[0] == ">="
        and g[2] != ZERO
        and (not any(p[0] == g[0] and p[2] == g[2] for p in self.premises.values()))
    ):
        from .local_amgm import candidates

        matches = []
        for u, v, rest, scale in candidates(g[1]):
            reduced = expr("sub", expr("div", g[2], scale), rest)
            square = (
                "=",
                expr("pow", reduced, number(2)),
                expr("mul", number(4), expr("mul", u, v)),
            )
            if (
                a.difference(square)
                and (not any(p[0] == "=" for p in self.premises.values()))
                and (not any(n[0] == "sqrt" for n in walk(square)))
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


def squared_bound(self, g):
    a = self.arithmetic
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
            if not a.difference(("=", g[1], expr("mul", u, v))) and (
                not a.difference(("=", g[2], rhs))
            ):
                return self.raw(
                    "amgm_squared_bound", g, [premise, *required], {"amgm_premise": key}
                )


def product_bound(self, g):
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
                required = self.amgm_requirements("fixed_sum_product_bound", g, cert)
            except ProofFailure as exc:
                if exc.code != "invalid_proof":
                    raise
            else:
                return self.raw("fixed_sum_product_bound", g, required, cert)


def constant_sum(self, g):
    a = self.arithmetic
    if not names(g):
        sign, certificate = a.constant_certificate(_diff(g))
        if _holds(sign, g[0]):
            return self.add("constant", g, certificate=certificate)
        raise ProofFailure("proof_missing", "exact constant comparison is false")


def even_power(self, g):
    a = self.arithmetic
    if g[2] == ZERO and g[0] in {">", ">=", "!="}:
        e = g[1]

        def even_power(n):
            return (
                n[0] == "pow"
                and (signed_integer(n[2]) or 0) > 0
                and (signed_integer(n[2]) % 2 == 0)
            )

        if even_power(e) and g[0] == ">=":
            return self.raw("sign", g)
        if e[0] == "add":
            for i, j in ((1, 2), (2, 1)):
                literal = a.literal_rational(e[j])
                if even_power(e[i]) and literal is not None and (literal > 0):
                    children = [(">=", e[i], ZERO), (">", e[j], ZERO)]
                    if i == 2:
                        children.reverse()
                    return self.raw("sign", g, children)


def positive_structure(self, g):
    if (
        g[2] == ZERO
        and g[0] in {">", ">=", "<", "<=", "!="}
        and (g[1][0] in {"add", "mul", "div", "pow", "sqrt", "neg"})
        and all(n[0] != "sub" for n in walk(g[1]))
        and all(
            (">", ("symbol", name), ZERO) in self.premises.values()
            for name in names(g[1])
        )
    ):
        found = self.attempt(partial(self.sign, g))
        if found:
            return found


def proportional(self, g):
    a = self.arithmetic
    for premise in self.premises.values():
        ratio = a.proportional(_diff(g), _diff(premise))
        if (
            ratio
            and {x * (1 if ratio > 0 else -1) for x in SIGNS[premise[0]]} <= SIGNS[g[0]]
        ):
            found = self.attempt(
                partial(self.raw, "weaken", g, [premise], {"ratio": str(ratio)})
            )
            if found:
                return found


def explicit_sign_transport(self, g):
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


def explicit_difference(self, g):
    if (
        g[0] != "="
        and g[2] != ZERO
        and any(
            p[0] == "=" and _diff(g) in tuple(walk(p)) for p in self.premises.values()
        )
    ):
        found = self.attempt(
            partial(self.raw, "difference", g, [(g[0], _diff(g), ZERO)])
        )
        if found:
            return found


def equation_factor(self, g):
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


def polynomial_transport(self, g):
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
                equality = ("=", _diff(g), expr("mul", number(ratio), _diff(premise)))
                found = self.attempt(partial(self.polynomial, equality))
                if found:
                    guards = tuple(self.need(d) for d in domains(equality))
                    self.cache[equality] = self.add("guard", equality, (found, *guards))
                    return self.raw(
                        "relation_transport",
                        g,
                        [premise, equality],
                        {"ratio": str(ratio)},
                    )


def equality(self, g):
    if g[0] == "=":
        if (
            g[1][0] == "pow"
            and g[1][1][0] == "sqrt"
            and (signed_integer(g[1][2]) == 2)
            and (g[2] == g[1][1][1])
        ):
            return self.raw("root_square", g, [(">=", g[2], ZERO)])
        found = self.attempt(partial(self.polynomial, g))
        if found:
            return found
        if (
            g[1] != ZERO
            and g[2] != ZERO
            and (g[1][0] != "pow")
            and (g[2][0] != "pow")
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


def root_monotone(self, g):
    if g[1][0] == g[2][0] == "sqrt":
        found = self.attempt(
            partial(self.raw, "monotone", g, [(g[0], g[1][1], g[2][1])])
        )
        if found:
            return found


def reciprocal_relation(self, g):
    if g[1][:2] == g[2][:2] == ("div", ONE):
        required = [
            (">", g[1][2], ZERO),
            (">", g[2][2], ZERO),
            (REVERSE[g[0]], g[1][2], g[2][2]),
        ]
        found = self.attempt(partial(self.raw, "monotone", g, required))
        if found:
            return found


def difference(self, g):
    if g[2] != ZERO:
        return self.raw("difference", g, [(g[0], _diff(g), ZERO)])


def factor_nonzero(self, g):
    if g[0] == "!=" and g[2] == ZERO:
        for premise in self.premises.values():
            for product in (premise[1], premise[2], _diff(premise)):
                if product != g[1] and g[1] in _factors(product):
                    found = self.attempt(
                        partial(self.raw, "factor_nonzero", g, [("!=", product, ZERO)])
                    )
                    if found:
                        return found


def known_product_nonzero(self, g):
    for premise in self.premises.values():
        if premise[0] != "=":
            continue
        for product, value in (premise[1:], premise[1:][::-1]):
            literal = self.arithmetic.literal_rational(value)
            if (product[0] == "mul" and literal is not None and literal != 0
                    and g[1] in _factors(product)):
                nonzero = ("!=", product, ZERO)
                core = self.raw("equal_sign", nonzero, [("=", product, value), ("!=", value, ZERO)])
                guards = [self.need(d) for d in domains(nonzero)]
                checked = self.add("guard", nonzero, [core, *guards])
                return self.add("factor_nonzero", g, [checked])


def product_sign(self, g):
    if g[1][0] == "mul":
        for left in self.premises.values():
            for right in self.premises.values():
                if left[1:] == (g[1][1], ZERO) and right[1:] == (g[1][2], ZERO):
                    try:
                        self.check_sign(g, [left, right], {})
                    except ProofFailure:
                        continue
                    found = self.attempt(partial(self.raw, "sign", g, [left, right]))
                    if found:
                        return found


def polynomial_scale(self, g):
    a = self.arithmetic
    for premise in self.premises.values():
        if premise[0] == "=":
            continue
        factor = a.factor(g[1], _diff(premise))
        if factor is None:
            continue
        scale_ops = [">", "<", ">=", "<=", "!=", "="]
        scale_ops.sort(key=lambda op: -((op, factor, ZERO) in self.premises.values()))
        for op in scale_ops:
            possible = {x * y for x in SIGNS[premise[0]] for y in SIGNS[op]}
            if possible <= SIGNS[g[0]]:
                found = self.attempt(
                    partial(self.raw, "scale", g, [premise, (op, factor, ZERO)])
                )
                if found:
                    return found


def structural_sign(self, g):
    found = self.attempt(partial(self.sign, g))
    if found:
        return found


def interval(self, g):
    found = self.attempt(partial(self.interval, g))
    if found:
        return found


def equation_sign(self, g):
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


def substitution(self, g):
    found = self.attempt(partial(self.substitution, g))
    if found:
        return found


def ground_substitution(self, g):
    return self.substitution(g, ground_only=True)


def identity(self, g):
    return self.polynomial(g, identities_only=True)


def root_sign(self, g):
    return self.sign(g)


CAPABILITIES = (
    ("identity", 2, 0, identity),
    ("root_sign", 1, 0, root_sign),
    ("given", 0, 0, given),
    ("verified_fragment", 1, 2, verified_fragment),
    ("constant", 1, 0, constant),
    ("cancel_sign", 2, 0, cancel_sign),
    ("power_sign", 1, 0, power_sign),
    ("positive_denominator", 1, 0, positive_denominator),
    ("nonzero_product", 1, 0, nonzero_product),
    ("operand_signs", 1, 0, operand_signs),
    ("positive_components", 1, 0, positive_components),
    ("nonnegative_components", 1, 0, nonnegative_components),
    ("same_difference", 2, 1, same_difference),
    ("known_transitivity", 2, 1, known_transitivity),
    ("scalar_transitivity", 2, 0, scalar_transitivity),
    ("strict_nonzero", 1, 1, strict_nonzero),
    ("normalize_reciprocal", 2, 1, normalize_reciprocal),
    ("reciprocal_monotone", 3, 0, reciprocal_monotone),
    ("sum_sign_transport", 2, 1, sum_sign_transport),
    ("signed_variable_scale", 2, 2, signed_variable_scale),
    ("reorder_bound", 2, 2, reorder_bound),
    ("equality_bound", 2, 2, equality_bound),
    ("sum_bound", 3, 1, sum_bound),
    ("local_sum_bound", 3, 2, local_sum_bound),
    ("squared_bound", 3, 1, squared_bound),
    ("product_bound", 3, 1, product_bound),
    ("constant_sum", 3, 3, constant_sum),
    ("even_power", 1, 0, even_power),
    ("positive_structure", 1, 1, positive_structure),
    ("proportional", 2, 2, proportional),
    ("explicit_sign_transport", 2, 0, explicit_sign_transport),
    ("explicit_difference", 2, 0, explicit_difference),
    ("equation_factor", 2, 2, equation_factor),
    ("polynomial_transport", 3, 4, polynomial_transport),
    ("equality", 2, 3, equality),
    ("endpoint_transport", 2, 3, endpoint_transport),
    ("root_monotone", 3, 0, root_monotone),
    ("reciprocal_relation", 3, 1, reciprocal_relation),
    ("difference", 4, 0, difference),
    ("factor_nonzero", 2, 1, factor_nonzero),
    ("known_product_nonzero", 1, 0, known_product_nonzero),
    ("product_sign", 1, 0, product_sign),
    ("polynomial_scale", 4, 3, polynomial_scale),
    ("structural_sign", 4, 4, structural_sign),
    ("interval", 3, 2, interval),
    ("equation_sign", 2, 1, equation_sign),
    ("ground_substitution", 1, 2, ground_substitution),
    ("substitution", 4, 3, substitution),
)


class ScheduledRealSearch(RealSearchTools):
    def __init__(self, context, request, *, budget, policy, manifest_hash):
        super().__init__(context, request, budget=budget)
        self.arithmetic = SearchArithmetic(budget)
        self.policy, self.manifest_hash = policy, manifest_hash
        self.cache_authority = (RULESET_HASH, self.context_hash, manifest_hash, policy.fingerprint)
        self.cache, self.active, self.requests = {}, set(), []
        self.scheduler = None
        self.seed_provider = None
        self.seed_reads = {}

    def checkpoint(self):
        return (
            len(self.nodes),
            dict(self.cache),
            dict(self.depths),
            dict(self.node_keys),
            dict(self.interned_nodes),
            dict(self.seed_reads),
            len(self.requests),
        )

    def rollback(self, saved):
        (
            count,
            self.cache,
            self.depths,
            self.node_keys,
            self.interned_nodes,
            self.seed_reads,
            _,
        ) = saved
        self.nodes = self.nodes[:count]
        self.by_id = {n.node_id: n for n in self.nodes}
        # Arithmetic work and previously checked node charges are never refunded.

    def requested_since(self, saved):
        return self.requests[saved[-1] :][:16]

    def dependencies(self, root):
        return list(self.by_id[root].premises)

    def check_candidate(self, root, goal):
        if root not in self.by_id or self.by_id[root].conclusion != goal:
            raise ProofFailure("invalid_proof", "strategy returned a different goal")
        self.check_node(self.by_id[root])

    def add(self, rule, conclusion, children=(), certificate=None):
        if "math." + rule not in self.policy.allowed_rules:
            raise ProofFailure(
                "strategy_not_applicable", "rule disabled by SearchPolicy"
            )
        return super().add(rule, conclusion, children, certificate)

    def attempt(self, function):
        self.budget.use("attempts")
        try:
            return function()
        except ProofFailure as exc:
            if exc.code not in {"proof_missing", "strategy_not_applicable"}:
                raise
            return None

    def need(self, goal):
        if len(self.requests) < self.policy.candidate_limit * 2:
            self.requests.append(goal)
        if goal in self.cache:
            self.budget.cache_hits += 1
            return self.cache[goal]
        # Reuse a checked subgraph only under the identical search authority.
        # Successful subgoals of abandoned candidates remain valid; their work
        # was charged and every imported node is checked again on attachment.
        shared_key = (*self.cache_authority, goal)
        if shared_key in self.budget.proven_goals:
            graph, root, reads = self.budget.proven_goals[shared_key]
            imported = {}

            def attach(key):
                if key not in imported:
                    node = graph[key]
                    imported[key] = self.add(
                        node.rule_id.removeprefix("math."), node.conclusion,
                        [attach(c) for c in node.children], node.certificate)
                    if key in reads:
                        self.seed_reads[imported[key]] = reads[key]
                return imported[key]

            result = attach(root)
            self.cache[goal] = result
            self.budget.cache_hits += 1
            return result
        if goal in self.active:
            raise ProofFailure("proof_missing", "active goal cycle")
        if len(self.active) >= self.budget.limits.depth:
            raise ProofFailure("strategy_budget_exhausted", "candidate recursion depth")
        self.budget.use("attempts")
        self.active.add(goal)
        try:
            guards = tuple(self.need(d) for d in domains(goal))
            root = self.scheduler.prove(self, goal)
            result = self.add("guard", goal, (root, *guards))
            self.cache[goal] = result
            self.budget.proven_goals[shared_key] = (
                dict(self.by_id), result, dict(self.seed_reads))
            return result
        finally:
            self.active.remove(goal)

    def run(self):
        from .proof_checker import _roots_for_request

        roots = []
        for goal in _roots_for_request(self):
            if goal[0] == "all":
                roots.append(
                    self.add("all", goal, tuple(self.need(g) for g in goal[1:]))
                )
            else:
                roots.append(self.need(goal))
        # Only successful reachable nodes belong in the final certificate.
        used = set()

        def visit(root):
            if root not in used:
                used.add(root)
                for child in self.by_id[root].children:
                    visit(child)

        for root in roots:
            visit(root)
        from dataclasses import replace

        self.used_seed_reads = {
            ref for node, ref in self.seed_reads.items() if node in used
        }
        selected = [n for n in self.nodes if n.node_id in used]
        mapping = {n.node_id: f"p{i:04d}" for i, n in enumerate(selected)}
        self.nodes = [
            replace(
                n,
                node_id=mapping[n.node_id],
                children=tuple(mapping[c] for c in n.children),
            )
            for n in selected
        ]
        return self.payload([mapping[r] for r in roots])


def real_strategy_package():
    from .proof_search import CandidateDescriptor, ProofStrategy, StrategyPackage

    # Required rule declarations are capabilities, not proof ownership guesses.
    primary = {
        "given": ("given",),
        "constant": ("constant",),
        "cancel_sign": ("equal_sign",),
        "power_sign": ("sign",),
        "positive_denominator": ("sign",),
        "nonzero_product": ("sign",),
        "operand_signs": ("sign",),
        "positive_components": ("sign",),
        "nonnegative_components": ("sign",),
        "same_difference": ("weaken", "polynomial", "relation_transport"),
        "known_transitivity": ("transitive", "weaken", "guard"),
        "scalar_transitivity": ("transitive",),
        "strict_nonzero": ("weaken",),
        "normalize_reciprocal": ("weaken",),
        "reciprocal_monotone": ("monotone",),
        "sum_sign_transport": ("difference", "equal_sign", "guard"),
        "signed_variable_scale": ("difference", "guard", "scale"),
        "reorder_bound": ("weaken",),
        "equality_bound": ("equality_bound_transport",),
        "sum_bound": ("two_term_amgm",),
        "local_sum_bound": ("local_two_term_amgm", "polynomial"),
        "squared_bound": ("amgm_squared_bound",),
        "product_bound": ("fixed_sum_product_bound", "two_term_product_bound"),
        "constant_sum": ("constant",),
        "even_power": ("sign",),
        "positive_structure": ("sign",),
        "proportional": ("weaken",),
        "explicit_sign_transport": ("equal_sign",),
        "explicit_difference": ("difference",),
        "equation_factor": ("equal_sign",),
        "polynomial_transport": ("guard", "polynomial", "relation_transport"),
        "equality": ("polynomial", "root_square", "square_equal"),
        "root_monotone": ("monotone",),
        "reciprocal_relation": ("monotone",),
        "difference": ("difference",),
        "factor_nonzero": ("factor_nonzero",),
        "product_sign": ("sign",),
        "polynomial_scale": ("scale",),
        "structural_sign": ("sign",),
        "interval": ("interval",),
        "equation_sign": ("equal_sign",),
        "substitution": ("substitution",),
    }
    primary.update(identity=("polynomial",), root_sign=("sign",))
    primary["endpoint_transport"] = ("equality_bound_transport",)
    primary["ground_substitution"] = ("substitution",)
    primary["known_product_nonzero"] = ("equal_sign", "factor_nonzero")
    equal = {
        "verified_fragment",
        "ground_substitution",
        "equality",
        "substitution",
        "constant",
        "constant_sum",
        "given",
        "root_monotone",
        "reciprocal_relation",
        "proportional",
        "difference",
        "structural_sign",
        "interval",
        "polynomial_transport",
    }
    exact_kind = {
        "sum_bound": (">=",),
        "local_sum_bound": (">=",),
        "squared_bound": ("<=",),
        "product_bound": ("<=",),
        "strict_nonzero": ("!=",),
        "equality": ("=",),
        "identity": ("=",),
    }
    strategies = []
    for name, phase, cost, function in CAPABILITIES:
        kinds = exact_kind.get(
            name, tuple(sorted(SIGNS if name in equal else set(SIGNS) - {"="}))
        )

        def match(goal, engine, name=name):
            op, left, right = goal
            values = tuple(engine.premises.values())
            equations = (
                tuple(p for p in values if p[0] == "=")
                if name
                in {
                    "sum_sign_transport",
                    "equality_bound",
                    "explicit_sign_transport",
                    "explicit_difference",
                    "equation_factor",
                    "polynomial_transport",
                    "equation_sign",
                    "substitution",
                    "ground_substitution",
                }
                else ()
            )
            is_sign = right == ZERO
            ordered = op in {">", ">=", "<", "<="}
            relevant = (
                tuple(p for p in values if names(p) <= names(goal))
                if name
                in {
                    "same_difference",
                    "signed_variable_scale",
                    "reorder_bound",
                    "proportional",
                    "polynomial_scale",
                }
                else ()
            )
            if name == "identity":
                applicable = op == "=" and not any(
                    side[0] == "symbol" and side[1] not in names(other)
                    for side, other in ((left, right), (right, left)))
            elif name == "root_sign":
                applicable = is_sign and left[0] == "sqrt"
            elif name == "given":
                applicable = goal in values
            elif name == "verified_fragment":
                applicable = engine.seed_provider is not None
            elif name == "constant" or name == "constant_sum":
                applicable = not names(goal)
            elif name == "cancel_sign":
                applicable = is_sign and left[0] in {"add", "sub", "pow"}
            elif name == "power_sign":
                applicable = is_sign and left[0] == "pow"
            elif name == "positive_denominator":
                applicable = is_sign and left[0] == "div" and (not names(left[2]))
            elif name == "nonzero_product":
                applicable = is_sign and op == "!=" and (left[0] in {"mul", "div"})
            elif name == "positive_components":
                applicable = is_sign and op in {">", ">=", "!="} and left[0] in {"add", "mul", "div"}
            elif name == "nonnegative_components":
                applicable = is_sign and op == ">=" and left[0] in {"add", "mul"}
            elif name == "operand_signs":
                applicable = is_sign and left[0] in {"add", "sub", "mul", "div"}
            elif name == "same_difference":
                applicable = op != "=" and any(p[0] == op for p in relevant)
            elif name == "known_transitivity":
                goal_order = _ordered(goal)
                applicable = goal_order is not None and any(
                    p is not None and p[1] == goal_order[1]
                    for p in map(_ordered, values)
                )
            elif name == "scalar_transitivity":
                applicable = (
                    ordered
                    and left[0] in {"symbol", "rat"}
                    and (right[0] in {"symbol", "rat"})
                )
            elif name == "strict_nonzero":
                applicable = op == "!="
            elif name == "known_product_nonzero":
                applicable = op == "!=" and is_sign
            elif name == "normalize_reciprocal":
                applicable = ordered and left[0] == right[0] == "div"
            elif name == "reciprocal_monotone":
                applicable = ordered and left[:2] == right[:2] == ("div", ONE)
            elif name == "sum_sign_transport":
                applicable = not is_sign and any(
                    p[1][0] == "add" or p[2][0] == "add" for p in equations
                )
            elif name == "signed_variable_scale":
                applicable = op != "=" and any(
                    any(n[0] == "div" for n in walk(p)) for p in relevant
                )
            elif name == "reorder_bound":
                applicable = ordered and any(p[0] == op for p in relevant)
            elif name == "endpoint_transport":
                goal_order = _ordered(goal)
                applicable = goal_order is not None and any(
                    p is not None and p[0] == goal_order[0]
                    and p[2] == goal_order[2] and p[1] != goal_order[1]
                    for p in map(_ordered, values)
                )
            elif name == "equality_bound":
                applicable = ordered and bool(equations)
            elif name == "sum_bound":
                applicable = op == ">=" and left[0] == "add"
            elif name == "local_sum_bound":
                applicable = op == ">=" and (not is_sign)
            elif name == "squared_bound":
                applicable = op == "<=" and any(
                    p[0] == ">=" and p[1][0] == "add" for p in values
                )
            elif name == "product_bound":
                applicable = op == "<="
            elif name == "even_power":
                applicable = is_sign and left[0] in {"pow", "add"}
            elif name == "positive_structure":
                applicable = (
                    is_sign
                    and bool(names(left))
                    and all((">", ("symbol", n), ZERO) in values for n in names(left))
                )
            elif name == "proportional":
                applicable = bool(relevant)
            elif name == "explicit_sign_transport":
                applicable = is_sign and any(left in p[1:] for p in equations)
            elif name == "explicit_difference":
                applicable = not is_sign and bool(equations)
            elif name == "equation_factor":
                applicable = is_sign and bool(equations)
            elif name == "polynomial_transport":
                applicable = bool(equations)
            elif name == "equality":
                applicable = op == "="
            elif name == "root_monotone":
                applicable = left[0] == right[0] == "sqrt"
            elif name == "reciprocal_relation":
                applicable = left[:2] == right[:2] == ("div", ONE)
            elif name == "difference":
                applicable = not is_sign and op != "="
            elif name == "factor_nonzero":
                applicable = (
                    op == "!="
                    and is_sign
                    and any(
                        left in _factors(p[1]) or left in _factors(p[2]) for p in values
                    )
                )
            elif name == "product_sign":
                applicable = is_sign and left[0] == "mul"
            elif name == "polynomial_scale":
                applicable = is_sign and any(p[0] != "=" for p in relevant)
            elif name == "structural_sign":
                applicable = is_sign and left[0] in {
                    "neg",
                    "add",
                    "sub",
                    "mul",
                    "div",
                    "sqrt",
                    "pow",
                }
            elif name == "interval":
                applicable = len(names(goal)) == 1
            elif name == "equation_sign":
                applicable = is_sign and any(left in p[1:] for p in equations)
            elif name in {"substitution", "ground_substitution"}:
                applicable = bool(equations)
            else:
                raise ValueError("unknown strategy: " + name)
            return (CandidateDescriptor(),) if applicable else ()

        def propose(engine, goal, candidate, function=function):
            return function(engine, goal)

        strategies.append(
            ProofStrategy(
                name,
                phase,
                cost,
                kinds,
                tuple("math." + rule for rule in primary.get(name, ())),
                match,
                propose,
            )
        )
    return StrategyPackage(
        RULESET_VERSION,
        RULESET_HASH,
        tuple(strategies),
        ScheduledRealSearch,
        compact_real_context,
    )


def compact_real_context(context, proof):
    """Rebuild checked nodes after dropping unused local premise documents."""
    from dataclasses import replace

    from .proof_algebra import freeze
    from .proof_checker import DEFAULT_RULE_REGISTRY

    if (proof["schema_version"], proof["ruleset_hash"]) != (
        RULESET_VERSION,
        RULESET_HASH,
    ):
        return context, proof
    records = {n["node_id"]: n for n in proof["nodes"]}
    used = set().union(*(set(records[r]["premises"]) for r in proof["roots"]))
    minimal = replace(
        context, premises={k: v for k, v in context.premises.items() if k in used}
    )
    if minimal == context:
        return context, proof
    env = _Environment(minimal, proof["request"])
    mapping = {}
    for node in proof["nodes"]:
        mapping[node["node_id"]] = env.add(
            node["rule_id"].removeprefix("math."),
            freeze(node["conclusion"]),
            tuple(mapping[c] for c in node["children"]),
            node["certificate"],
        )
    rebuilt = env.payload([mapping[r] for r in proof["roots"]])
    DEFAULT_RULE_REGISTRY.replay(rebuilt, minimal)
    return minimal, rebuilt
