"""Certify the local AM-GM template, including its unchanged remainder."""

import sympy as sp

from .expression_parser import MathParseError, parse_math_expression, parse_math_relation
from .local_amgm import candidates
from .proof_algebra import Arithmetic, ProofFailure, from_node
from .proof_kernel import _Budget, verify_relation_sequence


def reciprocal_coefficient(value, result, a, b):
    """Propose a coefficient, never proof authority, for one reciprocal gap."""
    gap = sp.cancel(1 / (a * b) - 4 / (a + b) ** 2)
    if gap != 0:
        coefficient = sp.cancel((value - result) / gap)
        if coefficient != 0 and not coefficient.free_symbols & (a.free_symbols | b.free_symbols):
            return coefficient
    return None


def verify_local_application(
    context, source, bound, u, v, *, budget, certificates=None
):
    from .inequality_bound_v2 import math_text

    def scalar(text):
        return parse_math_expression(text, context.symbols).to_sympy(context.symbols)

    a, b = scalar(math_text(u)), scalar(math_text(v))
    value, result = scalar(source), scalar(bound)
    factors = [sp.Integer(1)]
    for _, _, _, scale in candidates(
        from_node(parse_math_expression(source, context.symbols).ast)
    ):
        factor = scalar(math_text(scale))
        if factor not in factors:
            factors.append(factor)
    for term in sp.Add.make_args(sp.expand(value)):
        for paired in (a, b):
            factor = sp.cancel(term / paired)
            if factor.is_Rational and factor > 0 and factor not in factors:
                factors.append(factor)
    options = []
    for factor in factors:
        local_result = sp.cancel(result - value + factor * (a + b))
        options.append(
            [
                f"({sp.cancel(local_result**2)})=({sp.cancel(4 * factor**2 * a * b)})",
                f"({local_result})>0",
                f"({factor})>0",
            ]
        )
    for term in sp.Add.make_args(sp.expand(value)):
        coefficient = sp.cancel(term * a * b)
        if coefficient == 0 or coefficient.free_symbols & (
            a.free_symbols | b.free_symbols
        ):
            continue
        expected = value - term + 4 * coefficient / (a + b) ** 2
        options.insert(0, [f"({bound})=({expected})", f"({coefficient})>0"])
    # Recognize the same reciprocal application across equivalent sums of
    # fractions. SymPy only proposes a coefficient; the exact full-expression
    # identity and positivity are still certified below and replayed. Requiring
    # independence from both participating terms prevents hiding another bound
    # (for example dropping a square) inside this coefficient.
    coefficient = reciprocal_coefficient(value, result, a, b)
    if coefficient is not None:
        expected = value - coefficient / (a * b) + 4 * coefficient / (a + b) ** 2
        options.append([f"({bound})=({expected})", f"({coefficient})>0"])
    limits = budget.limits
    if certificates is not None:
        if certificates["relations"] not in options:
            raise ProofFailure("invalid_proof", "local application template changed")
        verify_relation_sequence(
            [
                parse_math_relation(r, context.symbols)
                for r in certificates["relations"]
            ],
            context,
            budget=_Budget(limits),
            certificates=certificates["proofs"],
        )
        return certificates
    arithmetic = Arithmetic(_Budget(limits))
    divisors = [
        arithmetic.equation_divisor(from_node(p.ast))
        for p in context.premises.values()
        if p.ast.op == "="
    ]
    for option in options:
        try:
            relations = [parse_math_relation(r, context.symbols) for r in option]
        except MathParseError:
            # These are speculative templates generated above, not submitted
            # mathematics. An unsupported candidate must not prevent checking
            # a different template. Source parsing and certificate replay stay
            # strict; only a fully proved candidate can be returned below.
            continue
        _, remainder = arithmetic.reduce(
            arithmetic.difference(from_node(relations[0].ast)), divisors
        )
        if remainder:
            continue
        proofs = verify_relation_sequence(relations, context, budget=_Budget(limits))
        return {"relations": option, "proofs": proofs}
    raise ProofFailure(
        "amgm_remainder_changed",
        "cannot certify this full-expression change as one AM-GM application "
        "with an equivalent remainder; check the source expression binding and "
        "local algebraic identity. If a separate square bound is used, call M12",
    )
