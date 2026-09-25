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
        if node[0] == "sub":
            return flatten(node[1]) + [expr("neg", node[2])]
        return [node]

    terms = flatten(value)
    if len(terms) > 8:
        raise ProofFailure(
            "proof_limit", "local AM-GM supports at most eight additive terms"
        )
    def rest_key(rest):
        return tuple(sorted((commutative_key(t) for t in flatten(rest) if t != ZERO), key=repr))

    seen = set()

    # Preserve explicitly grouped positive terms as well as flattened sums.
    # In (a+1)+3/(a+1)-3 the whole a+1 is one participating term.
    def grouped(node, rest):
        if node[0] == "add":
            yield node[1], node[2], rest, scale
            yield from grouped(node[1], expr("add", rest, node[2]))
            yield from grouped(node[2], expr("add", rest, node[1]))
        elif node[0] == "sub":
            yield from grouped(node[1], expr("sub", rest, node[2]))

    for u, v, rest, factor in grouped(value, ZERO):
        key = commutative_key(expr("add", u, v)), rest_key(rest), factor
        if key not in seen:
            seen.add(key)
            yield u, v, rest, factor
    for i, j in combinations(range(len(terms)), 2):
        u, v = terms[i], terms[j]
        rest = ZERO
        for k, term in enumerate(terms):
            if k not in (i, j):
                rest = expr("add", rest, term)
        key = commutative_key(expr("add", u, v)), rest_key(rest), scale
        if key in seen:
            continue
        seen.add(key)
        yield u, v, rest, scale
