"""Sufficient affine certificates; no exam names or arbitrary geometry search."""

import json

import sympy as sp


def key(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def unconditional(facts):
    for fact in facts:
        if fact[0] == "and":
            yield from unconditional(fact[1:])
        else:
            yield fact


def cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def subtract(a, b):
    return (a[0] - b[0], a[1] - b[1])


def intersection(a, b, c, d):
    u, v = subtract(b, a), subtract(d, c)
    det = cross(u, v)
    if det == 0:
        return None
    offset = subtract(c, a)
    t, s = cross(offset, v) / det, cross(offset, u) / det
    return (a[0] + t * u[0], a[1] + t * u[1]), t, s


class AffineCertificates:
    """Use only unconditional premises and exact rational affine constructions.

    A nondegenerate parallelogram supplies an affine coordinate frame. This
    preserves incidence, midpoints, convexity and ratios along a line, but is
    never used for Euclidean angles or arbitrary distances.
    """

    def __init__(self, facts, budget):
        self.facts = list(unconditional(facts))
        self.budget = budget
        self.frames = []
        if len(self.facts) > 128:
            return
        for fact in self.facts:
            if fact[:2] not in (["call", "square"], ["call", "parallelogram"]):
                continue
            vertices = fact[2:]
            if len(vertices) != 4 or len({key(p) for p in vertices}) != 4:
                continue
            if len(self.frames) >= 8:
                break
            basis = ((0, 0), (1, 0), (1, 1), (0, 1))
            points = {
                key(p): tuple(map(sp.Rational, xy)) for p, xy in zip(vertices, basis)
            }
            self.extend(points, [fact])

    def extend(self, points, premises):
        for _ in range(16):
            added = False
            for fact in self.facts:
                self.budget.use()
                target, xy = None, None
                if fact[0] == "=":
                    for lhs, rhs in ((fact[1], fact[2]), (fact[2], fact[1])):
                        if lhs[0] == "ref" and rhs[:2] == ["call", "midpoint"]:
                            a, b = (points.get(key(p)) for p in rhs[2:])
                            if a is not None and b is not None:
                                target = lhs
                                xy = tuple((x + y) / 2 for x, y in zip(a, b))
                point, locus = None, None
                if fact[0] == "∈":
                    point, locus = fact[1:]
                elif fact[0] == "=":
                    for lhs, rhs in ((fact[1], fact[2]), (fact[2], fact[1])):
                        if rhs[0] == "set" and len(rhs) == 2:
                            point, locus = rhs[1], lhs
                if (
                    point is not None
                    and point[0] == "ref"
                    and locus[0] == "∩"
                    and len(locus) == 3
                ):
                    loci = locus[1:]
                    if all(
                        l[:2] in (["call", "line"], ["call", "segment"]) for l in loci
                    ):
                        coords = [points.get(key(p)) for l in loci for p in l[2:]]
                        if all(p is not None for p in coords):
                            result = intersection(*coords)
                            if result is not None and all(
                                l[1] != "segment" or 0 <= t <= 1
                                for l, t in zip(loci, result[1:])
                            ):
                                target, xy = point, result[0]
                if target is None:
                    continue
                code = key(target)
                if code in points and points[code] != xy:
                    return  # Conflicting constructions cannot supply a certificate.
                if code not in points:
                    if len(points) >= 64:
                        return
                    points[code] = xy
                    premises.append(fact)
                    added = True
            if not added:
                break
        self.frames.append((points, premises))

    def quadrilateral(self, vertices):
        """Certify ordered strict convexity; never use the target polygon itself."""
        for points, premises in self.frames:
            self.budget.use()
            coords = [points.get(key(p)) for p in vertices]
            if any(p is None for p in coords) or len(set(coords)) != 4:
                continue
            turns = [
                cross(
                    subtract(coords[(i + 1) % 4], coords[i]),
                    subtract(coords[(i + 2) % 4], coords[(i + 1) % 4]),
                )
                for i in range(4)
            ]
            if all(t > 0 for t in turns) or all(t < 0 for t in turns):
                return {
                    "rule": "affine_convex_quadrilateral",
                    "premises": premises,
                    "coordinates": [list(p) for p in coords],
                }
        return None

    def cut(self, first, second):
        """Unique supporting-line intersection, away from all four endpoints."""
        if first[0] != "endpoints" or second[0] != "endpoints":
            return None
        ends = first[1:] + second[1:]
        if len(ends) != 4 or len({key(p) for p in ends}) != 4:
            return None
        # A valid nondegenerate quadrilateral has nonparallel diagonal lines;
        # their intersection cannot be a vertex. It need not lie inside both.
        requested = {key(sorted(first[1:], key=key)), key(sorted(second[1:], key=key))}
        for fact in self.facts:
            self.budget.use()
            if fact[:2] not in (
                ["call", "quadrilateral"],
                ["call", "parallelogram"],
                ["call", "square"],
            ):
                continue
            v = fact[2:]
            if len(v) != 4 or len({key(p) for p in v}) != 4:
                continue
            diagonals = {
                key(sorted([v[0], v[2]], key=key)),
                key(sorted([v[1], v[3]], key=key)),
            }
            if requested == diagonals:
                return {
                    "rule": "nondegenerate_polygon_diagonal_cut",
                    "premises": [fact],
                }
        for points, premises in self.frames:
            self.budget.use()
            coords = [points.get(key(p)) for p in ends]
            if any(p is None for p in coords):
                continue
            result = intersection(*coords)
            if result is not None and all(t not in (0, 1) for t in result[1:]):
                return {"rule": "affine_nonzero_diagonal_cut", "premises": premises}
        return None
