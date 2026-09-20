"""Bounded DNF proofs using safe expressions produced by Canonical, never text.

Only equalities can be derived. Nonalgebraic facts, inequalities, goals,
uncertainties and scope structure remain exact. Domain obligations must agree.
"""

import sympy as sp


def entails(source, target, algebra, budget):
    from .notation_semantics import bounded_expand, key

    budget.use()
    present = {key(f) for f in source}
    missing = [f for f in target if key(f) not in present]
    if not missing:
        return True
    if any(f[:2] != ["relation", "="] for f in missing):
        return False
    equations = [algebra[key(f)] for f in source if f[:2] == ["relation", "="]]
    targets = [algebra[key(f)] for f in missing]
    symbols = sorted(
        set().union(*(e.free_symbols for e in equations + targets)), key=str
    )
    if not symbols or len(symbols) > 16 or len(equations) > 32:
        return False
    # Denominator domains were already checked by the caller. Taking a
    # numerator here preserves an equality on that common domain.
    polynomials = [bounded_expand(e.as_numer_denom()[0]) for e in equations + targets]
    if any(not e.is_polynomial(*symbols) for e in polynomials):
        return False
    if any(sp.Poly(e, *symbols).total_degree() > 4 for e in polynomials):
        return False
    equations, targets = polynomials[: len(equations)], polynomials[len(equations) :]
    linear = [e for e in equations if sp.Poly(e, *symbols).total_degree() <= 1]
    for _ in range(4):
        budget.use()
        basis = sp.groebner(linear, *symbols, domain=sp.QQ) if linear else None
        added = []
        for equation in equations:
            budget.use()
            residual = basis.reduce(equation)[1] if basis else equation
            if (
                residual != 0
                and sp.Poly(residual, *symbols).total_degree() <= 1
                and residual not in linear
                and residual not in added
            ):
                added.append(residual)
        if not added:
            break
        linear.extend(added)
    basis = sp.groebner(linear, *symbols, domain=sp.QQ) if linear else None
    if basis is None:
        return False
    for target_equation in targets:
        budget.use()
        if basis.reduce(target_equation)[1] != 0:
            return False
    return True


def fact_proof(lhs, rhs, algebra, budget, path):
    """A bidirectional proof for one scope, with caller-checked domains."""
    if len(lhs) > 64 or len(rhs) > 64:
        return None
    try:
        if not all(any(entails(x, y, algebra, budget) for y in rhs) for x in lhs):
            return None
        if not all(any(entails(y, x, algebra, budget) for x in lhs) for y in rhs):
            return None
    except (ValueError, TypeError, sp.PolynomialError, sp.CoercionFailed):
        return None
    return {
        "rule": "bounded_dnf_linear_implication",
        "path": path,
        "expected_clauses": lhs,
        "actual_clauses": rhs,
        "directions": ["expected_entails_actual", "actual_entails_expected"],
    }


def equivalent(left, right, algebra, budget):
    """Return proof records, or None. No proof is a conservative difference."""
    if left["well_definedness"] != right["well_definedness"]:
        return None
    proofs = []

    def scope(a, b, path):
        if set(a) != set(b):
            return False
        if any(a[k] != b[k] for k in a if k not in ("facts", "children")):
            return False
        if len(a["children"]) != len(b["children"]):
            return False
        lhs, rhs = a["facts"], b["facts"]
        if lhs != rhs:
            proof = fact_proof(lhs, rhs, algebra, budget, path)
            if proof is None:
                return False
            proofs.append(proof)
        return all(
            scope(x, y, path + f"/children/{i}")
            for i, (x, y) in enumerate(zip(a["children"], b["children"]))
        )

    try:
        return proofs if scope(left["root"], right["root"], "/root") else None
    except (ValueError, TypeError, sp.PolynomialError, sp.CoercionFailed):
        return None
