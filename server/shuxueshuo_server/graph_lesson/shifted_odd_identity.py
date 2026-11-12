"""Bounded rational families; retain printed denominator obligations before cancellation."""

from copy import deepcopy

import sympy as sp

from . import function_cells as cells
from . import function_parity as parity
from .parity_extension_math import ARGUMENT
from .parity_parameter_math import _budget
from .stage_three.abstract_function_domain import affine_preimage
from .symmetry_value_math import _literal

X = sp.Symbol("x", real=True)
VERSION = "shifted-odd-identity/v1"


def exact_budget(value):
    for q in sp.sympify(value).atoms(sp.Rational):
        if max(abs(int(q.p)).bit_length(), int(q.q).bit_length()) > 128:
            raise ValueError("shifted_odd.number_budget")
    return value


def scalar(ast, argument=X, *, guards=None):
    """Read arithmetic only, without eval/sympify of source strings."""
    _budget(ast)

    def read(node):
        op = node[0]
        if node == ARGUMENT:
            return argument
        if op == "number":
            if len(node[1]) > 160:
                raise ValueError("shifted_odd.number_budget")
            return exact_budget(sp.Rational(node[1]))
        if node[:2] == ["call", "sqrt"]:
            value = read(node[2])
            if value.free_symbols or value < 0:
                raise ValueError("shifted_odd.constant_root_required")
            return cells.exact_point(sp.sqrt(value))
        if op == "ref" and node[2] == "scalar":
            return sp.Symbol(node[1], real=True)
        if op == "neg":
            return -read(node[1])
        if op not in ("+", "-", "*", "/", "^"):
            raise ValueError("shifted_odd.arithmetic_unsupported")
        a, b = read(node[1]), read(node[2])
        if op == "^":
            if not b.is_Integer or not 0 <= b <= 5:
                raise ValueError("shifted_odd.power_budget")
            if b == 0 and guards is not None:
                guards.append(a)
            elif b == 0 and (a == 0 or a.free_symbols):
                raise ValueError("shifted_odd.zero_power_obligation")
            v = a**b
        elif op == "/":
            if guards is not None:
                guards.append(b)
            if b == 0:
                raise ValueError("shifted_odd.undefined_expression")
            if guards is None and b.free_symbols:
                raise ValueError("shifted_odd.symbolic_divisor_obligation")
            v = a / b
        else:
            v = {"+": lambda: a + b, "-": lambda: a - b, "*": lambda: a * b}[op]()
        if sp.count_ops(v) > 1024:
            raise ValueError("shifted_odd.expression_budget")
        exact_budget(v)
        if v.free_symbols:
            num, den = sp.fraction(sp.together(v))
            if (
                max(
                    sp.Poly(z, *sorted(v.free_symbols, key=str)).total_degree()
                    for z in (num, den)
                )
                > 24
            ):
                raise ValueError("shifted_odd.intermediate_degree_budget")
        return v

    return read(ast)


def fixed_set(ast):
    if ast is None:
        return sp.S.Reals

    def intervals(node):
        if isinstance(node, list):
            if node[0] == "interval":
                lo, hi = map(cells.constant, node[3:5])
                if lo >= hi:
                    raise ValueError("shifted_odd.invalid_interval")
            for child in node[1:]:
                intervals(child)

    intervals(ast)
    return cells.input_set(ast)


def rational_family(ast):
    guards = []
    expr = scalar(ast, guards=guards)
    params = sorted(expr.free_symbols - {X}, key=str)

    # Count parameters in the original tree, including coefficients which cancel.
    def refs(n):
        return (
            {sp.Symbol(n[1], real=True)}
            if n[0] == "ref" and n[2] == "scalar"
            else set().union(*(refs(c) for c in n[1:] if isinstance(c, list)))
        )

    params = sorted(refs(ast), key=str)
    if len(params) > 2:
        raise ValueError("shifted_odd.parameter_budget")
    num, den = sp.fraction(sp.together(expr))
    try:
        if (
            sp.Poly(num, X).degree() > 5
            or sp.Poly(den, X).degree() > 4
            or den.free_symbols - {X}
        ):
            raise ValueError("shifted_odd.degree_budget")
        if params and sp.Poly(num, *params).total_degree() > 1:
            raise ValueError("shifted_odd.parameter_degree_budget")
        for g in guards:
            if (
                g.free_symbols - {X}
                or sp.Poly(sp.fraction(sp.together(g))[0], X).degree() > 4
            ):
                raise ValueError("shifted_odd.parameter_denominator_unsupported")
        for v in (num, den, *guards):
            for q in v.atoms(sp.Rational):
                if max(abs(int(q.p)).bit_length(), int(q.q).bit_length()) > 128:
                    raise ValueError("shifted_odd.number_budget")
    except sp.PolynomialError as exc:
        raise ValueError("shifted_odd.rational_required") from exc
    return expr, params, guards


def _fixed_descriptor(ast, domain_ast, function_ref, source_ref):
    function = {
        "function_ref": function_ref,
        "source_ref": source_ref,
        "expression_ast": deepcopy(ast),
    }
    if domain_ast is not None:
        fixed_set(domain_ast)
        function.update(input_domain_ast=domain_ast, domain_role="declared")
    return function


def admitted_expression(ast):
    try:
        return rational_family(ast)
    except ValueError:
        cells.inspect(ast)
        return None, [], []


def _fixed_nonalgebraic(ast, domain_ast, function_ref, source_ref):
    function = _fixed_descriptor(ast, domain_ast, function_ref, source_ref)
    solved = parity.effective_domain(function)
    domain = solved["domain"]
    symmetry = parity.domain_symmetry(function, domain)
    if symmetry["status"] != "proved":
        raise ValueError("shifted_odd.domain_not_symmetric")
    sample = parity._sample(domain)
    K = sp.simplify(cells.evaluate(ast, sample)[1] + cells.evaluate(ast, -sample)[1])
    h = {**function, "expression_ast": ["-", deepcopy(ast), _literal(K / 2)]}
    proof = parity.relation(h, symmetry, "odd")
    if proof["status"] != "proved":
        raise ValueError("shifted_odd.not_constant_sum")
    return {
        "version": VERSION,
        "source_ast": deepcopy(ast),
        "domain_ast": deepcopy(domain_ast),
        "engine": "fixed_m1",
        "parameters": [],
        "guards": [],
        "natural_domain": solved["natural_domain"],
        "domain": domain,
        "expression": None,
        "K": K,
        "fixed_proof": proof,
    }


def identity(ast, domain_ast, function_ref, source_ref):
    expr, params, guards = admitted_expression(ast)
    if expr is None:
        return _fixed_nonalgebraic(ast, domain_ast, function_ref, source_ref)
    natural = sp.S.Reals
    for g in guards:
        zeros = sp.solveset(g, X, domain=sp.S.Reals)
        if isinstance(zeros, sp.ConditionSet):
            raise ValueError("shifted_odd.denominator_roots_unsupported")  # noqa: TRY004
        natural -= zeros
    domain = natural if domain_ast is None else fixed_set(domain_ast)
    if domain == sp.S.EmptySet or domain.is_subset(natural) is not True:
        raise ValueError("shifted_odd.original_domain_invalid")
    if parity.reflect_set(domain) != domain:
        raise ValueError("shifted_odd.domain_not_symmetric")
    H = sp.cancel(expr + expr.subs(X, -X))
    if X in H.free_symbols:
        if not isinstance(domain, sp.FiniteSet):
            raise ValueError("shifted_odd.not_constant_sum")
        values = [sp.cancel(H.subs(X, p)) for p in domain]
        if any(v != values[0] for v in values):
            raise ValueError("shifted_odd.not_constant_sum")
        H = values[0]
    engine, proof = "parameter_identity", None
    if not params:
        function = {
            "function_ref": function_ref,
            "source_ref": source_ref,
            "expression_ast": deepcopy(ast),
        }
        if domain_ast is not None:
            function.update(input_domain_ast=domain_ast, domain_role="declared")
        solved = parity.effective_domain(function)
        h = {**function, "expression_ast": ["-", deepcopy(ast), _literal(H / 2)]}
        symmetry = parity.domain_symmetry(h, solved["domain"])
        proof = parity.relation(h, symmetry, "odd")
        if proof["status"] != "proved":
            raise ValueError("shifted_odd.fixed_identity_unproved")
        engine = "fixed_m1"
    return {
        "version": VERSION,
        "source_ast": deepcopy(ast),
        "domain_ast": deepcopy(domain_ast),
        "engine": engine,
        "parameters": params,
        "guards": guards,
        "natural_domain": natural,
        "domain": domain,
        "expression": expr,
        "K": H,
        "fixed_proof": proof,
    }


def verify_identity(ast, domain_ast, function_ref, source_ref, proof):
    """Check the original expression and supplied certificate without the producer."""
    try:
        expr, params, guards = admitted_expression(ast)
        if expr is None:
            function = _fixed_descriptor(ast, domain_ast, function_ref, source_ref)
            domain, natural = cells.source_domain(function)
        else:
            natural = sp.S.Reals
            for g in guards:
                natural -= sp.solveset(g, X, domain=sp.S.Reals)
            domain = natural if domain_ast is None else fixed_set(domain_ast)
        K = proof["K"]
        expected = {
            "version": VERSION,
            "source_ast": ast,
            "domain_ast": domain_ast,
            "parameters": params,
            "guards": guards,
            "natural_domain": natural,
            "domain": domain,
            "expression": expr,
            "engine": "parameter_identity" if params else "fixed_m1",
        }
        if (
            set(proof) != {*expected, "K", "fixed_proof"}
            or any(proof[k] != v for k, v in expected.items())
            or domain == sp.S.EmptySet
            or domain.is_subset(natural) is not True
            or parity.reflect_set(domain) != domain
            or X in K.free_symbols
        ):
            return False
        if expr is not None:
            residual = sp.cancel(expr + expr.subs(X, -X) - K)
            if isinstance(domain, sp.FiniteSet):
                if any(sp.cancel(residual.subs(X, t)) != 0 for t in domain):
                    return False
            elif residual != 0:
                return False
        if params:
            return proof["fixed_proof"] is None
        h = ["-", deepcopy(ast), _literal(K / 2)]
        row = proof["fixed_proof"]
        if row["status"] != "proved" or row["reason"] != "identity_on_domain":
            return False
        cells.verify_identity(
            parity.reflect_ast(h), ["neg", h], domain, row["comparison"]
        )
        return True
    except (ValueError, TypeError, KeyError, AttributeError, NotImplementedError):
        return False


def _equations(expr, equations, symbol):
    polys, arguments = [], []
    for arg, value in equations:
        if arg.free_symbols - {symbol} or value.free_symbols:
            raise ValueError("shifted_odd.symbolic_condition_unsupported")
        argument = sp.Poly(arg, symbol)
        if argument.degree() > 1:
            raise ValueError("shifted_odd.symbolic_input_affine_required")
        num, _ = sp.fraction(sp.together(expr.subs(X, arg) - value))
        poly = sp.Poly(num, symbol, domain=sp.QQ)
        for coefficient in poly.all_coeffs():
            exact_budget(coefficient)
        if poly.degree() > 5:
            raise ValueError("shifted_odd.input_degree_budget")
        polys.append(poly)
        arguments.append(argument)
    return polys, arguments


def _interval_legal(arguments, symbol, lo, hi, domain):
    for arg in arguments:
        ends = [arg.eval(t) for t in (lo, hi)]
        image = (
            sp.FiniteSet(ends[0])
            if ends[0] == ends[1]
            else sp.Interval(min(ends), max(ends))
        )
        if image.is_subset(domain) is not True:
            return False
    return True


def compatibility(expr, domain, equations, symbol):
    """Isolate one common real root on original legal inputs; never round a root."""
    polys, arguments = _equations(expr, equations, symbol)
    nonzero = [p for p in polys if not p.is_zero]
    common = nonzero[0] if nonzero else sp.Poly(0, symbol)
    for p in nonzero[1:]:
        common = sp.gcd(common, p)
    allowed = sp.S.Reals
    for arg in arguments:
        allowed &= affine_preimage(domain, arg.nth(1), arg.nth(0))
    if allowed == sp.S.EmptySet:
        raise ValueError("shifted_odd.conditions_inconsistent")

    def certificate(lo, hi):
        cells.exact_point(exact_budget(lo))
        cells.exact_point(exact_budget(hi))
        return {
            "equations": equations,
            "symbol": symbol,
            "domain": domain,
            "common_polynomial": common.as_expr(),
            "interval": [lo, hi],
        }

    if common.is_zero:
        # All value equations are identities. Select from the intersection of
        # their legal preimages, rather than trying a fixed list of small inputs.
        point = parity._sample(allowed)
        return certificate(point, point)

    # Closed endpoints and isolated algebraic points need point certificates;
    # a rational isolating interval cannot fit inside an isolated point.
    parts = allowed.args if isinstance(allowed, sp.Union) else [allowed]
    for part in parts:
        points = (
            list(part)
            if isinstance(part, sp.FiniteSet)
            else ([part.start, part.end] if isinstance(part, sp.Interval) else [])
        )
        for point in points:
            if (
                point.is_finite
                and allowed.contains(point) is sp.true
                and sp.simplify(common.eval(point)) == 0
            ):
                return certificate(point, point)
    intervals = [pair for pair, _ in common.intervals(eps=sp.Rational(1, 1024))]
    if not intervals:
        raise ValueError("shifted_odd.conditions_inconsistent")
    for lo, hi in intervals:
        for _ in range(32):
            if _interval_legal(arguments, symbol, lo, hi, domain):
                return certificate(lo, hi)
            image = sp.FiniteSet(lo) if lo == hi else sp.Interval(lo, hi)
            if image & allowed == sp.S.EmptySet or lo == hi:
                break
            # Refine toward the same root when the legal interval is narrow.
            lo, hi = common.refine_root(lo, hi, steps=4)
            exact_budget(lo)
            exact_budget(hi)
    # Root isolation has not proved existence in the allowed set; do not guess.
    raise ValueError("shifted_odd.legal_common_root_unproved")


def verify_compatibility(expr, domain, equations, symbol, proof):
    """Verify divisibility and a real-root interval, without finding a new root."""
    try:
        if (
            set(proof)
            != {"equations", "symbol", "domain", "common_polynomial", "interval"}
            or proof["equations"] != equations
            or proof["symbol"] != symbol
            or proof["domain"] != domain
        ):
            return False
        polys, arguments = _equations(expr, equations, symbol)
        lo, hi = proof["interval"]
        if lo > hi or (lo != hi and not all(t.is_Rational for t in (lo, hi))):
            return False
        cells.exact_point(exact_budget(lo))
        cells.exact_point(exact_budget(hi))
        if not _interval_legal(arguments, symbol, lo, hi, domain):
            return False
        common = sp.Poly(proof["common_polynomial"], symbol, domain=sp.QQ)
        for coefficient in common.all_coeffs():
            exact_budget(coefficient)
        if common.is_zero:
            return lo == hi and all(p.is_zero for p in polys)
        if (
            common.degree() < 1
            or common.degree() > 5
            or any(not p.rem(common).is_zero for p in polys)
        ):
            return False
        return (
            bool(sp.simplify(common.eval(lo)) == 0)
            if lo == hi
            else bool(common.count_roots(lo, hi) > 0)
        )
    except (ValueError, TypeError, KeyError, NotImplementedError, sp.PolynomialError):
        return False
