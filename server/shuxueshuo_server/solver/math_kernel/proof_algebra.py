"""Budgeted exact arithmetic used by proof construction and certificate replay.

Sparse polynomials have rational coefficients. Radicals are inert generators;
only the proof rules can authorize their defining equations.
"""

from __future__ import annotations

import json
from fractions import Fraction as Q
from hashlib import sha256
from math import isqrt

import sympy as sp


class ProofFailure(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def freeze(value):
    return (
        tuple(freeze(x) for x in value) if isinstance(value, (tuple, list)) else value
    )


def digest(value):
    return sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


def number(value):
    q = Q(value)
    return ("rat", str(q.numerator), str(q.denominator))


ZERO, ONE = number(0), number(1)


def rat(e):
    return Q(int(e[1]), int(e[2])) if e[0] == "rat" else None


def expr(op, *args):
    if op == "sub" and args[1] == ZERO:
        return args[0]
    if op == "add" and args[1] == ZERO:
        return args[0]
    if op == "mul" and args[1] == ONE:
        return args[0]
    return (op, *args)


def from_node(node):
    if node.op in {"integer", "rat"}:
        return number(node.text)
    if node.op == "symbol":
        return ("symbol", node.text)
    if node.op in {"group", "pos"}:
        return from_node(node.children[0])
    return (node.op, *(from_node(c) for c in node.children))


def walk(e):
    yield e
    for child in e[1:]:
        if isinstance(child, tuple):
            yield from walk(child)


def names(e):
    return {n[1] for n in walk(e) if n[0] == "symbol"}


def substitute(e, mapping):
    if e[0] == "symbol":
        return mapping.get(e[1], e)
    return (
        e[0],
        *(substitute(c, mapping) if isinstance(c, tuple) else c for c in e[1:]),
    )


def signed_integer(e):
    if e[0] == "neg":
        value = signed_integer(e[1])
        return -value if value is not None else None
    value = rat(e)
    return int(value) if value is not None and value.denominator == 1 else None


def domains(e):
    """Postorder obligations, before any cancellation or SymPy evaluation."""
    result = []
    for child in e[1:]:
        if isinstance(child, tuple):
            result.extend(domains(child))
    if e[0] == "div":
        result.append(("!=", e[2], ZERO))
    elif e[0] == "pow" and signed_integer(e[2]) < 0:
        result.append(("!=", e[1], ZERO))
    elif e[0] == "sqrt":
        result.append((">=", e[1], ZERO))
    return tuple(dict.fromkeys(result))


def root_key(e):
    return "r:" + digest(e)


class Arithmetic:
    def __init__(self, budget):
        self.budget = budget
        self.limits = budget.limits
        self._gcd_cache = {}

    def check(self, p):
        if len(p) > self.limits.polynomial_terms:
            raise ProofFailure("proof_limit", "polynomial term limit")
        for m, c in p.items():
            if sum(v for _, v in m) > self.limits.polynomial_degree:
                raise ProofFailure("proof_limit", "polynomial degree limit")
            self.check_q(c)
        return {m: c for m, c in p.items() if c}

    def check_q(self, c):
        if (
            max(abs(c.numerator).bit_length(), c.denominator.bit_length())
            > self.limits.coefficient_bits
        ):
            raise ProofFailure("proof_limit", "coefficient bit limit")
        return c

    def constant(self, q):
        return self.check({(): Q(q)}) if q else {}

    def add(self, a, b, factor=Q(1)):
        p = dict(a)
        for m, c in b.items():
            p[m] = p.get(m, Q(0)) + factor * c
            p = self.check(p)
        return p

    def mul(self, a, b):
        p = {}
        for m, c in a.items():
            for n, d in b.items():
                powers = dict(m)
                for key, degree in n:
                    powers[key] = powers.get(key, 0) + degree
                term = tuple(sorted(powers.items()))
                p[term] = p.get(term, Q(0)) + c * d
                p = self.check(p)
        return p

    def power(self, a, n):
        if not 0 <= n <= 12:
            raise ProofFailure("proof_limit", "power limit")
        p = self.constant(1)
        for _ in range(n):
            p = self.mul(p, a)
        return p

    def rational(self, e):
        op = e[0]
        if op == "rat":
            return self.constant(rat(e)), self.constant(1)
        if op in {"symbol", "sqrt"}:
            key = "s:" + e[1] if op == "symbol" else root_key(e)
            return {((key, 1),): Q(1)}, self.constant(1)
        if op == "neg":
            a, b = self.rational(e[1])
            return self.add({}, a, Q(-1)), b
        a, b = self.rational(e[1])
        if op == "pow":
            n = signed_integer(e[2])
            if n is None or abs(n) > 12:
                raise ProofFailure("invalid_input", "integer power required")
            if n < 0:
                a, b, n = b, a, -n
            if not b:
                raise ProofFailure("proof_missing", "zero denominator")
            return self.power(a, n), self.power(b, n)
        c, d = self.rational(e[2])
        if op in {"add", "sub"}:
            return self.add(
                self.mul(a, d), self.mul(c, b), Q(1 if op == "add" else -1)
            ), self.mul(b, d)
        if op == "mul":
            return self.mul(a, c), self.mul(b, d)
        if op == "div":
            if not c:
                raise ProofFailure("proof_missing", "zero denominator")
            return self.mul(a, d), self.mul(b, c)
        raise ProofFailure("invalid_input", "unsupported scalar node")

    def difference(self, relation):
        return self.rational(expr("sub", relation[1], relation[2]))[0]

    def equation_divisor(self, relation):
        """Reduce denominator content before using an equality as a divisor.

        The original relation still supplies all domain guards. In particular,
        1/x = 2/x has residual -1/x, not an equality asserting x = 0.
        """
        numerator, denominator = self.rational(expr("sub", relation[1], relation[2]))
        common = self.polynomial_gcd(numerator, denominator)
        divisor = self.exact_quotient(numerator, common)
        if set(divisor) == {()}:
            raise ProofFailure(
                "inconsistent_premises", "nonzero constant equality residual"
            )
        return divisor

    def exact_quotient(self, numerator, denominator):
        if set(denominator) == {()}:
            return self.check({m: c / denominator[()] for m, c in numerator.items()})
        quotients, remainder = self.reduce(numerator, [denominator])
        if remainder:
            raise ProofFailure("invalid_proof", "non-exact polynomial cancellation")
        return quotients[0]

    def polynomial_gcd(self, a, b):
        """Deterministic primitive pseudo-remainder GCD over rational scalars.

        Coefficient content recurses over fewer generators. Every remainder
        step shares the request's reduction budget; every intermediate sparse
        polynomial obeys the degree, term and coefficient limits. No unbounded
        CAS GCD/factorization is used, including during certificate replay.
        """

        def monic(p):
            if not p:
                return {}
            lead = p[max(p)]
            return self.check({m: c / lead for m, c in p.items()})

        a, b = monic(a), monic(b)
        if not a or not b:
            return b if not a else a
        one = self.constant(1)
        if a == one or b == one:
            return one
        if a == b:
            return a
        cache_key = tuple(sorted((tuple(sorted(a.items())), tuple(sorted(b.items())))))
        if cache_key in self._gcd_cache:
            return self._gcd_cache[cache_key]
        self.budget.use("reductions")
        variable = min(key for p in (a, b) for m in p for key, _ in m)

        def coefficients(p):
            result = {}
            for m, c in p.items():
                degree = dict(m).get(variable, 0)
                term = tuple((key, power) for key, power in m if key != variable)
                result.setdefault(degree, {})[term] = c
            return result

        def primitive(p):
            content = {}
            for _, coefficient in sorted(coefficients(p).items()):
                content = self.polynomial_gcd(content, coefficient)
                if content == one:
                    break
            return content, self.exact_quotient(p, content)

        content_a, a = primitive(a)
        content_b, b = primitive(b)
        content = self.polynomial_gcd(content_a, content_b)
        while b:
            coefficients_b = coefficients(b)
            degree_b = max(coefficients_b)
            lead_b = coefficients_b[degree_b]
            remainder = a
            while remainder:
                coefficients_r = coefficients(remainder)
                degree_r = max(coefficients_r)
                if degree_r < degree_b:
                    break
                self.budget.use("reductions")
                shift = degree_r - degree_b
                term = {((variable, shift),) if shift else (): Q(1)}
                remainder = self.add(
                    self.mul(lead_b, remainder),
                    self.mul(self.mul(coefficients_r[degree_r], term), b),
                    Q(-1),
                )
            a, b = b, primitive(remainder)[1] if remainder else {}
        result = monic(self.mul(content, a))
        self._gcd_cache[cache_key] = result
        return result

    def constant_expression(self, e):
        """Detect constant residuals on their domain, including ghost symbols.

        This is only for rejecting inconsistent premises. Cancellation here
        neither rewrites the source AST nor proves any domain obligation.
        """
        numerator, denominator = self.rational(e)
        if not numerator:
            return ZERO
        if set(numerator) == set(denominator):
            monomial = next(iter(denominator))
            ratio = self.check_q(numerator[monomial] / denominator[monomial])
            if all(numerator[m] == ratio * c for m, c in denominator.items()):
                return number(ratio)
        roots = self.roots([e])
        normalized = (
            "div",
            self.expression(numerator, roots),
            self.expression(denominator, roots),
        )
        return None if names(normalized) else normalized

    def literal_rational(self, e):
        """Evaluate rational literals without rewriting the source/domain AST.

        Symbolic cancellation and radical identities are not literal endpoints.
        Reuse bounded arithmetic so compound fractions and signed powers have
        the same coefficient limits and zero-denominator checks as certificates.
        """
        if any(node[0] in {"symbol", "sqrt"} for node in walk(e)):
            return None
        numerator, denominator = self.rational(e)
        return self.check_q(numerator.get((), Q(0)) / denominator[()])

    def reduce(self, target, divisors):
        generators = sorted(
            {key for p in [target, *divisors] for m in p for key, _ in m}
        )

        def order(m):
            powers = dict(m)
            return sum(powers.values()), tuple(powers.get(key, 0) for key in generators)

        p, remainder = dict(target), {}
        quotients = [{} for _ in divisors]
        while p:
            self.budget.use("reductions")
            lead = max(p, key=order)
            for i, divisor in enumerate(divisors):
                if not divisor:
                    continue
                dlead = max(divisor, key=order)
                powers = dict(lead)
                if any(powers.get(k, 0) < v for k, v in dlead):
                    continue
                for k, v in dlead:
                    powers[k] -= v
                monomial = tuple(sorted((k, v) for k, v in powers.items() if v))
                term = {monomial: p[lead] / divisor[dlead]}
                quotients[i] = self.add(quotients[i], term)
                p = self.add(p, self.mul(term, divisor), Q(-1))
                break
            else:
                remainder[lead] = p.pop(lead)
        return quotients, self.check(remainder)

    def linear_combination(self, target, divisors):
        """Bounded rational row reduction; not a general equation solver."""
        monomials = sorted(set(target).union(*(set(p) for p in divisors)))
        rows = [
            [p.get(m, Q(0)) for p in divisors] + [target.get(m, Q(0))]
            for m in monomials
        ]
        pivot_rows = []
        cursor = 0
        for column in range(len(divisors)):
            pivot = next((i for i in range(cursor, len(rows)) if rows[i][column]), None)
            if pivot is None:
                continue
            self.budget.use("reductions")
            rows[cursor], rows[pivot] = rows[pivot], rows[cursor]
            scale = rows[cursor][column]
            rows[cursor] = [self.check_q(x / scale) for x in rows[cursor]]
            for i in range(len(rows)):
                if i != cursor and rows[i][column]:
                    factor = rows[i][column]
                    rows[i] = [
                        self.check_q(x - factor * y)
                        for x, y in zip(rows[i], rows[cursor], strict=True)
                    ]
            pivot_rows.append((column, cursor))
            cursor += 1
        if any(not any(row[:-1]) and row[-1] for row in rows):
            return None
        result = [{} for _ in divisors]
        for column, row in pivot_rows:
            result[column] = self.constant(rows[row][-1])
        return result

    def encode(self, p):
        return [
            [[[k, v] for k, v in m], str(c.numerator), str(c.denominator)]
            for m, c in sorted(p.items())
        ]

    def decode(self, data):
        if (
            not isinstance(data, (tuple, list))
            or len(data) > self.limits.polynomial_terms
        ):
            raise ProofFailure("invalid_proof", "invalid polynomial certificate")
        p = {}
        for monomial, numerator, denominator in data:
            m = tuple((k, v) for k, v in monomial)
            if (
                m in p
                or tuple(sorted(m)) != m
                or len(dict(m)) != len(m)
                or any(type(v) is not int or v <= 0 for _, v in m)
            ):
                raise ProofFailure("invalid_proof", "invalid monomial")
            if max(len(numerator), len(denominator)) > self.limits.coefficient_bits:
                raise ProofFailure("proof_limit", "oversized coefficient")
            p[m] = Q(int(numerator), int(denominator))
        return self.check(p)

    def expression(self, p, roots):
        result = ZERO
        for monomial, coefficient in sorted(p.items()):
            term = number(coefficient)
            for key, degree in monomial:
                atom = ("symbol", key[2:]) if key.startswith("s:") else roots[key]
                term = expr(
                    "mul", term, atom if degree == 1 else ("pow", atom, number(degree))
                )
            result = term if result == ZERO else expr("add", result, term)
        return result

    def roots(self, expressions):
        roots = {root_key(n): n for e in expressions for n in walk(e) if n[0] == "sqrt"}
        if len(roots) > self.limits.radicals:
            raise ProofFailure("proof_limit", "radical generator limit")
        return dict(sorted(roots.items()))

    def root_polynomial(self, root):
        a, b = self.rational(root[1])
        r, _ = self.rational(root)
        return self.add(self.mul(self.mul(r, r), b), a, Q(-1))

    def factor(self, target, base):
        a, b = self.rational(target)
        c, d = self.rational(base)
        if not c:
            return None
        quotient, remainder = self.reduce(self.mul(a, d), [c])
        if remainder:
            return None
        roots = self.roots([target, base])
        return ("div", self.expression(quotient[0], roots), self.expression(b, roots))

    def proportional(self, a, b):
        x, y = self.rational(a)
        u, v = self.rational(b)
        left, right = self.mul(x, v), self.mul(u, y)
        if not right or set(left) != set(right):
            return None
        m = next(iter(right))
        ratio = left[m] / right[m]
        return ratio if all(left[k] == ratio * right[k] for k in right) else None

    def constant_interval(self, e, bits):
        """Outward rational interval arithmetic, including principal square roots."""
        op = e[0]
        if op == "rat":
            q = self.check_q(rat(e))
            return q, q
        if op == "symbol":
            raise ProofFailure("invalid_input", "constant required")
        a, b = self.constant_interval(e[1], bits)
        if op == "neg":
            return -b, -a
        if op == "sqrt":
            if b < 0:
                raise ProofFailure("proof_missing", "negative radicand")
            a = max(a, Q(0))
            scale = 1 << bits
            lo = isqrt(a.numerator * scale * scale // a.denominator)
            hi = isqrt(b.numerator * scale * scale // b.denominator)
            upper = Q(hi, scale)
            if upper * upper != b:
                upper = Q(hi + 1, scale)
            return self.check_q(Q(lo, scale)), self.check_q(upper)
        if op == "pow":
            n = signed_integer(e[2])
            if n < 0:
                if a <= 0 <= b:
                    raise ProofFailure(
                        "proof_missing", "interval denominator contains zero"
                    )
                a, b, n = 1 / b, 1 / a, -n
            values = [a**n, b**n]
            if n > 0 and n % 2 == 0 and a <= 0 <= b:
                values.append(Q(0))
            return self.check_q(min(values)), self.check_q(max(values))
        c, d = self.constant_interval(e[2], bits)
        if op == "add":
            values = (a + c, b + d)
        elif op == "sub":
            values = (a - d, b - c)
        else:
            if op == "div":
                if c <= 0 <= d:
                    raise ProofFailure(
                        "proof_missing", "interval denominator contains zero"
                    )
                c, d = 1 / d, 1 / c
            values = [a * c, a * d, b * c, b * d]
        return self.check_q(min(values)), self.check_q(max(values))

    def _constant_sympy(self, e):
        if e[0] == "rat":
            return sp.Rational(int(e[1]), int(e[2]))
        args = [self._constant_sympy(c) for c in e[1:]]
        return {
            "neg": lambda a: -a,
            "add": lambda a, b: a + b,
            "sub": lambda a, b: a - b,
            "mul": lambda a, b: a * b,
            "div": lambda a, b: a / b,
            "pow": lambda a, b: a**b,
            "sqrt": sp.sqrt,
        }[e[0]](*args)

    def constant_certificate(self, e, *, supplied=None):
        roots = self.roots([e])
        if names(e) or 2 ** len(roots) > self.limits.algebraic_degree:
            raise ProofFailure("proof_limit", "algebraic degree bound")
        # Check input arithmetic/bit budgets before entering algebraic routines.
        self.rational(e)
        for root in roots.values():
            self.rational(root[1])
        value = self._constant_sympy(e)
        variable = sp.Symbol("z")
        polynomial = sp.Poly(sp.minpoly(value, variable), variable, domain=sp.QQ)
        if polynomial.degree() > self.limits.algebraic_degree:
            raise ProofFailure("proof_limit", "algebraic degree limit")
        coefficients = [
            self.check_q(Q(int(c.p), int(c.q))) for c in polynomial.all_coeffs()
        ]
        encoded = [[str(c.numerator), str(c.denominator)] for c in coefficients]
        if polynomial.degree() == 1:
            exact = -coefficients[1] / coefficients[0]
            cert = {
                "polynomial": encoded,
                "bits": 0,
                "interval": [str(exact), str(exact)],
                "root_index": 0,
            }
            # A degree-one minimal polynomial uniquely selects the value.
            return (exact > 0) - (exact < 0), cert
        if supplied is not None:
            bits = supplied.get("bits")
            if type(bits) is not int or not 1 <= bits <= self.limits.refinements:
                raise ProofFailure("invalid_proof", "invalid isolation budget")
            attempts = [bits]
        else:
            attempts = range(1, self.limits.refinements + 1)
        for bits in attempts:
            self.budget.use("refinements")
            try:
                lo, hi = self.constant_interval(e, bits)
            except ProofFailure as exc:
                if exc.code == "proof_missing":
                    continue
                raise
            if lo <= 0 <= hi:
                continue
            sl, sh = (
                sp.Rational(lo.numerator, lo.denominator),
                sp.Rational(hi.numerator, hi.denominator),
            )
            if (
                polynomial.count_roots(sl, sh) != 1
                or polynomial.eval(sl) == 0
                or polynomial.eval(sh) == 0
            ):
                continue
            # Count roots strictly below the isolating interval, exactly.
            index = int(polynomial.count_roots(-sp.oo, sl))
            cert = {
                "polynomial": encoded,
                "bits": bits,
                "interval": [str(lo), str(hi)],
                "root_index": index,
            }
            return (1 if lo > 0 else -1), cert
        raise ProofFailure("proof_limit", "algebraic isolation limit")
