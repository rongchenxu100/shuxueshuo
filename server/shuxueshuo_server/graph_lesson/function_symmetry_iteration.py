"""Exact affine value transport along legal reflection paths.

Two whole-domain involutions have dihedral normal forms. Bounded local
relations instead use a closed interval partition and explicit directed paths.
An unvisited orbit can be filled by the recorded extension, so a null-space
witness represents a function, not merely unrelated values at a few points.
"""
from itertools import pairwise

import sympy as sp

from .symmetry_relation_math import image


def iterate(sign, offset, n):
    return (sp.S.One, n*offset) if sign == 1 else (sp.Integer(-1)**n, (1-sp.Integer(-1)**n)*offset/2)


def _edges(edges):
    out = []
    for index, e in enumerate(edges):
        out.append({**e, 'index': index, 'direction': 1})
        out.append({**e, 'offset': -e['sign']*e['offset'], 'scope': image(e['scope'], -1, 2*e['a']),
                    'index': index, 'direction': -1})
    return out


def _graph(start, neighbors, budget):
    """Potentials f(node)=A*f(start)+B and all closed-path constraints."""
    seen, queue, constraints = {start: (sp.S.One, sp.S.Zero, [])}, [start], []
    while queue:
        at = queue.pop(0)
        a, b, path = seen[at]
        for to, e in neighbors(at):
            na, nb = e['sign']*a, e['sign']*b+e['offset']
            step = {'source_ref': e['source_ref'], 'direction': e['direction'], 'from': at, 'to': to}
            if to in seen:
                ca, cb, _ = seen[to]
                constraints.append((ca-na, nb-cb))
            else:
                if len(seen) >= budget or len(path) >= 32:
                    raise ValueError('symmetry.local_path_budget')
                seen[to] = na, nb, [*path, step]
                queue.append(to)
    return seen, list(dict.fromkeys(constraints))


def _constant(constraints):
    fixed = None
    for k, v in constraints:
        if k == 0:
            if v != 0:
                raise ValueError('symmetry.conditions_inconsistent')
        elif fixed is not None and fixed != v/k:
            raise ValueError('symmetry.conditions_inconsistent')
        else:
            fixed = v/k
    return fixed


class Orbit:
    def __init__(self, edges, domain):
        self.edges, self.domain = edges, domain
        self.directed = _edges(edges)
        self.global_ = all(e['whole'] for e in edges)
        self.cache = {}
        if self.global_:
            for e in edges:
                if (e['sign']+1)*e['offset'] != 0:
                    raise ValueError('symmetry.conditions_inconsistent')
            centers = sorted({e['a'] for e in edges})
            self.a = centers[0]
            self.p = 2*(centers[-1]-self.a)
            if self.p:
                # A finite union of rational intervals/points invariant under a
                # nonzero translation is R or empty; the latter was rejected.
                if domain != sp.S.Reals:
                    raise ValueError('symmetry.domain_not_translation_closed')
                self.first = next(e for e in edges if e['a'] == self.a)
                self.second = next(e for e in edges if e['a'] == centers[-1])
                self.sign = self.first['sign']*self.second['sign']
                self.offset = self.second['sign']*self.first['offset']+self.second['offset']
                self.extension = {'kind': 'dihedral', 'base_interval': sp.Interval(self.a, self.a+self.p/2),
                                  'step': self.p, 'sign': self.sign, 'offset': self.offset,
                                  'period': 2*self.p if self.sign == -1 else self.p if self.offset == 0 else None,
                                  'generic_base_value': sp.S.Zero,
                                  'fixed_values': [self._fixed(self.a), self._fixed(self.a+self.p/2)]}
            else:
                self.first = edges[0]
                # Different value laws on the very same reflection may force
                # a constant on every orbit, even when the center is missing.
                self.common = [(e['sign']-self.first['sign'], self.first['offset']-e['offset']) for e in edges]
                _constant(self.common)
                at_center = self.common + [(1-e['sign'], e['offset']) for e in edges]
                fixed = _constant(at_center) if domain.contains(self.a) is sp.true else None
                self.extension = {'kind': 'reflection', 'center': self.a,
                                  'generic_base_value': _constant(self.common) or sp.S.Zero, 'fixed_value': fixed}
        else:
            self.extension = self._local_extension()

    def _fixed(self, point):
        return _constant([(1-e['sign'], e['offset']) for e in self.edges if e['a'] == point])

    def _neighbors(self, point):
        for e in self.directed:
            if e['scope'].contains(point) is sp.true:
                yield 2*e['a']-point, e

    def reduce(self, point):
        if self.domain.contains(point) is not sp.true:
            raise ValueError('symmetry.input_outside_domain')
        if self.global_:
            n = int(sp.floor((point-self.a)/self.p)) if self.p else 0
            r = point-n*self.p
            reflected = r > self.a+self.p/2 if self.p else r < self.a
            e = self.second if self.p else self.first
            base = 2*e['a']-r if reflected else r
            sign, offset = iterate(self.sign, self.offset, n) if self.p else (sp.S.One, sp.S.Zero)
            return {'base': base, 'factor': sign*e['sign'] if reflected else sign,
                    'offset': offset+sign*e['offset'] if reflected else offset,
                    'path': {'translation_count': n, 'reflected': reflected}}
        if point not in self.cache:
            group, _ = _graph(point, self._neighbors, 32)
            base = min(group)
            rooted, constraints = _graph(base, self._neighbors, 32)
            _constant(constraints)
            for c, (a, b, path) in rooted.items():
                self.cache[c] = ({'base': base, 'factor': a, 'offset': b, 'path': path}, constraints)
        return self.cache[point][0]

    def constraints(self, base):
        if not self.global_:
            self.reduce(base)
            return self.cache[base][1]
        if self.p:
            return [(1-e['sign'], e['offset']) for e in self.edges if e['a'] == base]
        return self.common + ([(1-e['sign'], e['offset']) for e in self.edges] if base == self.a else [])

    def _local_extension(self):
        # Only finite, exactly paired atoms are accepted. Refining every image
        # cut makes an edge a bijection between atoms; no sampling of a scope.
        boundaries = set()
        for domain in [self.domain, *(e['scope'] for e in self.directed)]:
            parts = domain.args if isinstance(domain, sp.Union) else [domain]
            for part in parts:
                if isinstance(part, sp.Interval):
                    boundaries.update(p for p in (part.start, part.end) if p not in (-sp.oo, sp.oo))
                elif isinstance(part, sp.FiniteSet):
                    boundaries.update(part)
        for _ in range(32):
            new = {2*e['a']-p for p in boundaries for e in self.directed
                   if e['scope'].closure.contains(p) is sp.true}
            if new <= boundaries:
                break
            boundaries |= new
            if len(boundaries) > 128:
                raise ValueError('symmetry.local_partition_budget')
        else:
            raise ValueError('symmetry.local_partition_budget')
        cuts = [-sp.oo, *sorted(boundaries), sp.oo]
        atoms = [sp.Interval.open(a, b) & self.domain for a, b in pairwise(cuts)]
        atoms += [sp.FiniteSet(p) for p in boundaries if self.domain.contains(p) is sp.true]
        atoms = [a for a in atoms if a != sp.S.EmptySet]
        def neighbors(at):
            atom = atoms[at]
            for e in self.directed:
                if atom.is_subset(e['scope']) is True:
                    target = image(atom, -1, 2*e['a'])
                    if target not in atoms:
                        raise ValueError('symmetry.local_partition_not_closed')
                    yield atoms.index(target), e
                elif atom.intersect(e['scope']) != sp.S.EmptySet:
                    raise ValueError('symmetry.local_partition_not_closed')
        filled, values = set(), [sp.S.Zero]*len(atoms)
        for i in range(len(atoms)):
            if i in filled:
                continue
            component, constraints = _graph(i, neighbors, 256)
            z = _constant(constraints)
            z = sp.S.Zero if z is None else z
            for j, (a, b, _) in component.items():
                values[j] = a*z+b
                filled.add(j)
        return {'kind': 'local_atoms', 'atoms': atoms, 'values': values,
                'exception_rule': 'replace entire finite numeric orbits by certified values'}
