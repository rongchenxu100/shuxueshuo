"""Teaching walks for whole-domain reflections: every value is reached from a known point, one reflection at a time.

The linear certificate of symmetry_relation_math remains the proof of the answer. A walk is only
offered when each step replays against the original relations and the walked values reproduce
that certificate; otherwise the caller keeps its older presentation.
"""
import sympy as sp

from .function_symmetry_iteration import Orbit
from .symmetry_relation_math import X, _equation, rational, target_terms

LETTERS = ('m', 'n')
DEPTH = 2


def _edges(m):
    return list({(e['a'], e['sign'], e['offset']): e for e in reversed(m['edges'])}.values())[::-1]


def step(e, point, value):
    """f(2a-x) = sign·f(x) + offset, read at x = point."""
    return {'edge': e, 'from': point, 'to': 2*e['a']-point,
            'value_from': value, 'value_to': sp.expand(e['sign']*value+e['offset'])}


def knowns(d, m):
    """Printed single values first, then values forced at a center of symmetry inside the domain."""
    out = {}
    for row in d['value_equations']:
        terms, rhs = _equation(row['ast'], [d['function']], X)
        if len(terms) != 1:
            return None
        ((_, q), k), = terms.items()
        q, value = rational(q), sp.nsimplify(rhs/k)
        if out.setdefault(q, {'x': q, 'value': value, 'reason': 'given'})['value'] != value:
            return None
    for e in _edges(m):
        if e['sign'] == -1 and m['domain'].contains(e['a']) is sp.true:
            value = e['offset']/2
            if out.setdefault(e['a'], {'x': e['a'], 'value': value, 'reason': 'center', 'edge': e})['value'] != value:
                return None
    return out


def _search(edges, domain, start, known):
    """Shortest reflection route (≤ DEPTH) from some known point to start, in walking order."""
    frontier, seen = [(start, [])], {start}
    for _ in range(DEPTH):
        nxt = []
        for p, route in frontier:
            for e in edges:
                q = 2*e['a']-p
                if q in seen or domain.contains(q) is not sp.true:
                    continue
                seen.add(q)
                path = [(e, p), *route]
                if q in known:
                    return q, path
                nxt.append((q, path))
        frontier = nxt
    return None


def plan(m, known, targets):
    """Greedy: the target closest to what is already known goes first; solved points become known."""
    edges, orbit = _edges(m), Orbit(m['edges'], m['domain'])
    known = {k: dict(v) for k, v in known.items()}
    letters, walks = list(LETTERS), []
    pending = [t for t in dict.fromkeys(targets) if t not in known]
    while pending:
        found = [(len(r[1]), i, t, r) for i, t in enumerate(pending)
                 if (r := _search(edges, m['domain'], t, known))]
        if not found:
            t = pending[0]
            if orbit.reduce(t)['base'] in {orbit.reduce(k)['base'] for k in known} or not letters:
                return None
            known[t] = {'x': t, 'value': sp.Symbol(letters.pop(0), real=True), 'reason': 'letter'}
            walks.append({'target': t, 'steps': [], 'value': known[t]['value']})
            pending.remove(t)
            continue
        _, _, t, (q, path) = min(found, key=lambda row: row[:2])
        steps, point, value = [], q, known[q]['value']
        for e, to in path:
            s = step(e, point, value)
            assert s['to'] == to
            steps.append(s)
            point, value = to, s['value_to']
            known.setdefault(point, {'x': point, 'value': value, 'reason': 'walk'})
        walks.append({'target': t, 'steps': steps, 'value': value})
        pending.remove(t)
    return walks


def replay(m, known, walks):
    """Independent check: every step is an original whole-domain relation applied at a legal point."""
    edges = [(e['a'], e['sign'], e['offset']) for e in m['edges'] if e['whole']]
    values = {k: v['value'] for k, v in known.items()}
    for w in walks:
        if not w['steps']:
            if w['target'] in values or not isinstance(w['value'], sp.Symbol):
                return False
            values[w['target']] = w['value']
            continue
        point = w['steps'][0]['from']
        for s in w['steps']:
            e = s['edge']
            if ((e['a'], e['sign'], e['offset']) not in edges or s['from'] != point
                    or values.get(point) != s['value_from'] or s['to'] != 2*e['a']-point
                    or m['domain'].contains(s['to']) is not sp.true
                    or sp.expand(s['value_to']-(e['sign']*s['value_from']+e['offset'])) != 0):
                return False
            point = s['to']
            values.setdefault(point, s['value_to'])
            if values[point] != s['value_to']:
                return False
        if point != w['target'] or values[point] != w['value']:
            return False
    return True


def period_walk(m):
    """A generic point (x, m) taken through both reflections until it returns to its own height."""
    ext = m['extension']
    if ext['kind'] != 'dihedral' or ext['period'] is None or not all(e['whole'] for e in m['edges']):
        return None
    centers = sorted({e['a'] for e in m['edges']})
    first = next(e for e in _edges(m) if e['a'] == centers[0])
    second = next(e for e in _edges(m) if e['a'] == centers[-1])
    x, v = sp.Symbol('x', real=True), sp.Symbol('m', real=True)
    steps, point, value = [], x, v
    for _ in range(2 if ext['sign'] == -1 else 1):
        for e in (first, second):
            steps.append(step(e, point, value))
            point, value = steps[-1]['to'], steps[-1]['value_to']
    if sp.expand(point-x-ext['period']) != 0 or sp.expand(value-v) != 0:
        return None
    return {'steps': steps, 'period': ext['period'], 'first': first, 'second': second, 'x': x, 'm': v}


def _replay_period(m, cycle):
    x, v = cycle['x'], cycle['m']
    edges = [(e['a'], e['sign'], e['offset']) for e in m['edges'] if e['whole']]

    def legal(s, point, value):
        e = s['edge']
        return ((e['a'], e['sign'], e['offset']) in edges and s['from'] == point and s['value_from'] == value
                and sp.expand(s['to']-(2*e['a']-point)) == 0
                and sp.expand(s['value_to']-(e['sign']*value+e['offset'])) == 0)
    point, value = x, v
    for s in cycle['steps']:
        if not legal(s, point, value):
            return False
        point, value = s['to'], s['value_to']
    return sp.expand(point-x-cycle['period']) == 0 and sp.expand(value-v) == 0


def representative(k, low, period):
    return k-period*sp.floor((k-low)/period)


def _total(d, value_of):
    total = sp.S.Zero
    for row in target_terms(d):
        total += row['constant']+sum(c*value_of(rational(q)) for (_, q), c in row['terms'].items())
    return sp.expand(total)


def teaching_plan(d, m):
    """{'mode': 'walk' | 'period', ...} or None when the older presentation must stay."""
    if m['proof']['status'] != 'determined' or not all(e['whole'] for e in m['edges']):
        return None
    try:
        known = knowns(d, m)
        if known is None:
            return None
        inputs = list(dict.fromkeys(p for row in target_terms(d) for p in row['inputs']))
        ext = m['extension']
        period = ext['period'] if ext['kind'] == 'dihedral' else None
        if len(inputs) <= 8 and (period is None or max(inputs)-min(inputs) < period):
            walks = plan(m, known, inputs)
            if walks is not None and replay(m, known, walks):
                values = {**{k: v['value'] for k, v in known.items()}, **{w['target']: w['value'] for w in walks}}
                if _total(d, values.__getitem__) == m['proof']['value']:
                    return {'mode': 'walk', 'known': known, 'walks': walks, 'inputs': inputs}
        if period is None:
            return None
        cycle = period_walk(m)
        if cycle is None or not _replay_period(m, cycle):
            return None
        low = min(inputs)
        if abs(low) > 2*period:
            low = min(known) if known else sp.S.Zero
        reps = list(dict.fromkeys(representative(k, low, period) for k in inputs))
        walks = plan(m, known, reps)
        if walks is None or not replay(m, known, walks):
            return None
        values = {**{k: v['value'] for k, v in known.items()}, **{w['target']: w['value'] for w in walks}}
        if _total(d, lambda k: values[representative(k, low, period)]) != m['proof']['value']:
            return None
        return {'mode': 'period', 'known': known, 'walks': walks, 'inputs': inputs, 'cycle': cycle,
                'low': low, 'period': period, 'reps': reps}
    except (ValueError, KeyError, AssertionError):
        return None
