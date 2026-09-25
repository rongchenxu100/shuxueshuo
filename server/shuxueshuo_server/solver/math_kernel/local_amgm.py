"""Bounded structural enumeration; never a proof or a solver."""

from itertools import combinations

from .proof_algebra import ONE, ZERO, ProofFailure, commutative_key, expr


def candidates(value):
    scale = ONE
    if value[0] == "mul":
        if value[2][0] == "add":
            scale, value = value[1], value[2]
        elif value[1][0] == "add":
            scale, value = value[2], value[1]
    elif value[0] == "div" and value[1][0] == "add":
        scale, value = expr("div", ONE, value[2]), value[1]

    def flatten(node):
        if node[0] == "add":
            return flatten(node[1]) + flatten(node[2])
        return [node]

    terms = flatten(value)
    if len(terms) > 8:
        raise ProofFailure(
            "proof_limit", "local AM-GM supports at most eight additive terms"
        )
    seen = set()
    for i, j in combinations(range(len(terms)), 2):
        u, v = terms[i], terms[j]
        rest = ZERO
        for k, term in enumerate(terms):
            if k not in (i, j):
                rest = expr("add", rest, term)
        key = commutative_key(expr("add", u, v)), commutative_key(rest), scale
        if key in seen:
            continue
        seen.add(key)
        yield u, v, rest, scale
