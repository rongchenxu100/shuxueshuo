"""Frame-local mathematical state, independent of drawing styles and labels.

The caller supplies only branch-visible objects and verified parameter values.
The registry is a catalogue, never permission to reveal a future result.
"""
from dataclasses import dataclass, replace
from hashlib import sha256
import copy
import json

import sympy as sp

from .geometry_naming import scope_lineage


@dataclass(frozen=True)
class FrameMathStateResolver:
    geometry: dict
    problem: dict
    scope_id: str

    def project(self, objects):
        """Select one visible version per canonical object; rebind dependants."""
        lineage = scope_lineage(self.scope_id)
        entities = self.problem.get('entities', ())
        metadata = dict(self.geometry.get('pointMeta', {}))
        for curve in self.geometry.get('curves', ()):
            metadata[curve['id']] = curve
        visible = {ref for obj in objects for ref in obj.geometry_refs}
        groups = {}
        for ref in visible:
            meta = metadata.get(ref, {})
            scope = meta.get('scopeId', 'problem')
            if scope not in lineage:
                continue
            identity = meta.get('objectRef')
            if not identity and meta.get('definition') not in {
                'anonymous_step_result', 'public_candidate', 'curve_vertex_feature',
            }:
                identity = meta.get('sourceRef')
                if not identity:
                    candidates = [e for e in entities if e.get('entity_type') == 'point'
                                  and e.get('name') == meta.get('label')
                                  and e.get('scope_id', 'problem') in scope_lineage(scope)]
                    candidates.sort(key=lambda e: scope_lineage(scope).index(e.get('scope_id', 'problem')))
                    if candidates:
                        nearest = candidates[0].get('scope_id', 'problem')
                        refs = {e.get('handle') for e in candidates if e.get('scope_id', 'problem') == nearest}
                        if len(refs) == 1:
                            identity = next(iter(refs))
            if identity:
                groups.setdefault(identity, []).append(ref)
        replacements = {}
        for identity, refs in groups.items():
            # Only versions already present in this frame participate. Distinct
            # objects and exact anonymous results are never coordinate aliases.
            ordered = sorted(refs, key=lambda r: (
                lineage.index(metadata[r].get('scopeId', 'problem')),
                -metadata[r].get('stateRevision', -1), r,
            ))
            best = ordered[0]
            for old in ordered[1:]:
                if (metadata[old].get('scopeId') != metadata[best].get('scopeId')
                    or metadata[old].get('stateRevision', -1) < metadata[best].get('stateRevision', -1)):
                    replacements[old] = best
        def rewrite(value):
            if isinstance(value, dict):
                return {k: rewrite(v) for k, v in value.items()}
            if isinstance(value, (list, tuple)):
                return [rewrite(v) for v in value]
            return replacements.get(value, value) if isinstance(value, str) else value
        result = {}
        for obj in objects:
            refs = tuple(replacements.get(ref, ref) for ref in obj.geometry_refs)
            key = (obj.component, obj.role, refs)
            # Coordinate annotations for an obsolete state must not survive.
            if obj.component == 'CoordinateLabel' and refs != obj.geometry_refs:
                continue
            updated = obj if refs == obj.geometry_refs else replace(
                obj, geometry_refs=refs, component_payload=rewrite(obj.component_payload),
                visual_object_id='object:' + sha256(json.dumps(key).encode()).hexdigest()[:24],
            )
            if key not in result or updated.state == 'focus':
                result[key] = updated
        return tuple(result.values()), replacements


def resolve_attainment_constraints(contracts, constraints, *, active_parameters):
    """Re-solve certified geometric relations in the current parameter state.

    Exploration retains a free control. Once released, the same relation owns
    its value; unrelated parameters changing can never leave a stale default.
    """
    result = [copy.deepcopy(c) for c in contracts]
    values = {c['name']: sp.sympify(str(c['default_value'])) for c in result}
    audits = []
    for constraint in constraints:
        name = constraint['parameter']
        target = next((c for c in result if c['name'] == name), None)
        if target is None:
            continue
        variable = sp.Symbol(name)
        expression = sp.sympify(constraint['equation'])
        substitutions = {sp.Symbol(k): v for k, v in values.items() if k != name}
        # Exact values take precedence over their floating-point display.
        for contract in result:
            domain = contract['mathematical_domain']
            if contract['name'] != name and domain.get('kind') == 'exact':
                substitutions[sp.Symbol(contract['name'])] = sp.sympify(domain['value'])
        resolved = sp.simplify(expression.subs(substitutions))
        if resolved.free_symbols - {variable}:
            raise ValueError('visual_math_state_unresolved_constraint: ' + name)
        solutions = sp.solve(resolved, variable)
        lower, upper = map(sp.sympify, constraint['domain'])
        legal = [v for v in solutions if not v.free_symbols and v.is_real is not False
                 and bool(v >= lower) and bool(v <= upper)]
        if len(legal) != 1:
            raise ValueError('visual_math_state_ambiguous_attainment: ' + name)
        exact = sp.simplify(legal[0])
        target['default_value'] = float(exact)
        mode = 'exploration' if name in active_parameters else 'attainment'
        if mode == 'attainment':
            target['controls'] = []
            target['mathematical_domain'] = {'kind': 'exact', 'value': str(exact)}
            target['display_window'] = {'min': float(exact), 'max': float(exact), 'step': 0}
        residual = sp.simplify(resolved.subs(variable, exact))
        if abs(float(residual)) > 1e-9:
            raise ValueError('visual_math_state_attainment_failed: ' + name)
        audits.append({**constraint, 'mode': mode, 'resolved_value': str(exact),
                       'residual': str(residual), 'parameters': {str(k): str(v) for k,v in substitutions.items()}})
        values[name] = exact
    return tuple(result), audits


def validate_frame_math_state(frame, geometry):
    """Independently check displayed geometry, not the resolver's audit residual."""
    state = frame.metadata.get('mathematical_state')
    if not state:
        return
    curve_by_id = {c['id']: c for c in geometry.get('curves', ())}
    seen = {}
    for obj in frame.objects:
        if obj.component != 'Parabola':
            continue
        for ref in obj.geometry_refs:
            identity = curve_by_id.get(ref, {}).get('objectRef')
            if identity and identity in seen and seen[identity] != ref:
                raise ValueError('visual_math_state_duplicate_object: ' + identity)
            if identity:
                seen[identity] = ref
    parameters = {sp.Symbol(c['name']): sp.sympify(str(c['default_value']))
                  for c in frame.local_parameters}
    pairs = {**geometry.get('fixedPoints', {}), **geometry.get('movingPoints', {})}
    for contract in frame.local_parameters:
        for ref, definition in contract['parameterized_points'].items():
            pairs[ref] = definition['expression']
    def point(ref):
        return tuple(float(sp.sympify(str(v)).subs(parameters)) for v in pairs[ref])
    def cross(p, q, r):
        return (q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0])
    def between(p,q,r):
        return abs(cross(p,q,r)) < 1e-7 and sum((q[i]-p[i])*(q[i]-r[i]) for i in range(2)) <= 1e-7
    for constraint in state.get('constraints', ()):
        try:
            p,q,r = map(point, constraint['geometry_refs'])
            if not between(p,q,r):
                raise ValueError('point is not on the attaining segment')
            if constraint.get('carrier') and not between(*map(point, constraint['carrier'])):
                raise ValueError('point is not on its carrier')
            if constraint.get('equal_lengths'):
                a,b,c,d = map(point, constraint['equal_lengths'])
                residual = sum((a[i]-b[i])**2-(c[i]-d[i])**2 for i in range(2))
                if abs(residual) > 1e-7:
                    raise ValueError('linked lengths differ')
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError('visual_math_state_constraint_failed: ' + str(exc)) from exc
