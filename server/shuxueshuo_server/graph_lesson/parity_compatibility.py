"""Shared parity compatibility rules for local rules on a symmetric domain.

FP-T2 classifies inputs per parameter cell; FP-T3 classifies a fixed domain.
Both ask the same question for one input t, so the decision lives here:

* overlap      -- t and -t both carry a given value; f(-t)=s*f(t) must hold
* known        -- only t carries a given value
* mirrored     -- only -t carries one; parity determines f(t)
* forced_zero  -- odd parity at 0 (or odd-and-even anywhere) fixes the value 0
* free         -- nothing given at t or -t; any parity-respecting value works
"""
import sympy as sp

ROLES = ('overlap', 'known', 'mirrored', 'forced_zero', 'free')
_T = sp.Symbol('t', real=True)


def atom_role(signs, known_here, known_mirror, at_zero):
    if known_here and known_mirror:
        return 'overlap'
    if known_here:
        return 'known'
    if known_mirror:
        return 'mirrored'
    if len(signs) == 2 or (at_zero and signs == [-1]):
        return 'forced_zero'
    return 'free'


def constrained(signs, role):
    """Whether a given value on this atom must satisfy a parity residual."""
    return role in ('overlap', 'known') if len(signs) == 2 else role == 'overlap'


def pair_residual(here, mirror, signs):
    """Given f(t)=here and f(-t)=mirror, the value that must vanish."""
    return here if len(signs) == 2 else sp.expand(mirror - signs[0] * here)


def residuals(expr, x, signs, role):
    """Expressions that must vanish on an atom with the given role."""
    if expr is None or not constrained(signs, role):
        return []
    return [pair_residual(expr, expr.subs(x, -x, simultaneous=True), signs)]


def _boundary_points(s):
    return {p for p in s.boundary if p.is_finite} if s != sp.S.EmptySet else set()


def fixed_atoms(domain, known, signs, *, cuts=()):
    """Partition a fixed symmetric domain into points and open intervals.

    Every boundary of the domain, the known set, its mirror and 0 is a cut, so
    membership in ``known`` and ``-known`` is constant on each open atom.
    """
    mirror = sp.imageset(sp.Lambda(_T, -_T), known)
    points = sorted({sp.S.Zero, *_boundary_points(domain), *_boundary_points(known),
                     *_boundary_points(mirror), *(c for c in cuts if c.is_finite)})
    edges = [-sp.oo, *points, sp.oo]
    atoms = []
    for low, high in zip(edges, edges[1:]):
        rep = (high - 1 if low == -sp.oo else low + 1 if high == sp.oo else (low + high) / 2)
        if domain.contains(rep) is sp.true:
            atoms.append({'kind': 'open', 'set': sp.Interval.open(low, high), 'representative': rep})
        if high != sp.oo and domain.contains(high) is sp.true:
            atoms.append({'kind': 'point', 'set': sp.FiniteSet(high), 'representative': high})
    for atom in atoms:
        rep = atom['representative']
        atom['role'] = atom_role(signs, known.contains(rep) is sp.true, known.contains(-rep) is sp.true,
                                 atom['kind'] == 'point' and rep == 0)
    return atoms


def vanishes(value, x, atom):
    if atom['kind'] == 'open':
        return sp.expand(value) == 0
    return sp.expand(value.subs(x, atom['representative'])) == 0
