"""Recorded successful solver/lesson output; no live providers or authored geometry."""
import json
from pathlib import Path

import pytest

from shuxueshuo_server.solver.explanation.models import (
    explanation_snapshot_from_payload, iter_teaching_sources,
)
from shuxueshuo_server.solver.explanation.lesson_ir import lesson_ir_from_payload
from shuxueshuo_server.solver.visual import (
    GeometrySpecBuilder, VisualStepBuilder, VisualStepIRValidator, forward_compile,
)
from shuxueshuo_server.solver.visual.role_binders import VisualRoleBinderRegistry


@pytest.fixture(scope='module')
def recorded():
    root = Path(__file__).parent / 'fixtures/anonymous_point_visual'
    return (
        explanation_snapshot_from_payload(json.loads((root / 'snapshot.json').read_text())),
        lesson_ir_from_payload(json.loads((root / 'lesson.json').read_text())),
    )


def test_recorded_anonymous_intercept_compiles_complete_page(recorded):
    snapshot, lesson = recorded
    visual = VisualStepBuilder().build(snapshot=snapshot, lesson=lesson)
    VisualStepIRValidator().validate(visual, lesson=lesson)
    compiled = forward_compile(visual)
    geometry = compiled.geometry_spec
    point_id = next(p for p, m in geometry['pointMeta'].items()
                    if m.get('sourceStepId') == 'axis_intercept_I2'
                    and m.get('returnName') == 'point')
    assert geometry['fixedPoints'][point_id] == ['0', '-1']
    assert geometry['pointMeta'][point_id]['scopeId'] == 'i_2'
    lesson_step = next(s for s in lesson.steps if 'line_intersection_I2' in s.source_step_ids)
    intersection = next(s for s in visual.steps if s.lesson_step_id == lesson_step.id)
    assert any(point_id in obj.geometry_refs for frame in intersection.frames for obj in frame.objects)
    producer_lesson = next(s for s in lesson.steps if 'axis_intercept_I2' in s.source_step_ids)
    producer_visual = next(s for s in visual.steps if s.lesson_step_id == producer_lesson.id)
    assert any(point_id in obj.geometry_refs for frame in producer_visual.frames for obj in frame.objects)
    assert geometry['pointMeta'][point_id]['label'] == 'F'
    assert compiled.lesson_data['steps']


def test_exact_result_binding_does_not_alias_coincident_points_or_siblings(recorded):
    snapshot, lesson = recorded
    geometry = GeometrySpecBuilder().build(snapshot=snapshot, lesson=lesson)
    point_id = next(p for p, m in geometry['pointMeta'].items()
                    if m.get('sourceStepId') == 'axis_intercept_I2'
                    and m.get('returnName') == 'point')
    sources = {s.source_step_id: s for s in iter_teaching_sources(snapshot.root_scope)}
    geometry['fixedPoints']['coincident'] = ['0', '-1']
    geometry['pointMeta']['coincident'] = {'label': 'Z', 'scopeId': 'problem', 'scopeRoot': 'problem'}
    binder = VisualRoleBinderRegistry(geometry, snapshot.problem)
    def bind(scope):
        return binder._teaching_input_point_role(
            sources['line_intersection_I2'], 'line_p2', sources=sources,
            snapshot=snapshot, scope_id=scope,
        )
    assert bind('i_2')['point'] == point_id
    assert bind('ii') == {}
    assert bind('i') == {}
    assert bind('i_2_1')['point'] == point_id
    geometry['fixedPoints'][point_id] = ['0', '-2']
    with pytest.raises(ValueError, match='visual_anonymous_point_value_mismatch'):
        bind('i_2')


@pytest.mark.parametrize('occupied', [
    {'F'},
    set('ABCDEFGHIJKLMNOPQRSTUVWXYZ') | {'P27'},
])
def test_anonymous_conclusion_label_and_numbered_fallback_never_reuse_labels(recorded, occupied):
    from shuxueshuo_server.solver.visual.builder import _add_anonymous_result_points

    snapshot, lesson = recorded
    if len(occupied) > 1:
        occupied = occupied | {str(e.get('name') or '') for e in snapshot.problem['entities']}
        occupied.add(f'P{len(occupied) + 1}')
    fixed, moving = {}, {}
    meta = {f'existing_{label}': {'label': label} for label in occupied}
    _add_anonymous_result_points(
        snapshot=snapshot, lesson=lesson, fixed=fixed, moving=moving,
        point_meta=meta, parameter_name='a',
    )
    generated = [m['label'] for m in meta.values() if m.get('definition') == 'anonymous_step_result']
    assert generated
    assert len(generated) == len(set(generated))
    assert not occupied.intersection(generated)
    target = next(p for p, m in meta.items() if m.get('sourceStepId') == 'axis_intercept_I2')
    assert fixed[target] == ['0', '-1']
    assert all(meta[f'existing_{label}']['label'] == label for label in occupied)


def test_attainment_identity_requires_unique_verified_role(recorded):
    from dataclasses import replace
    from shuxueshuo_server.solver.explanation.models import TeachingSource
    from shuxueshuo_server.solver.visual.role_binders import _public_point_semantic_ref

    snapshot, _ = recorded
    source = TeachingSource(
        source_step_id='new_result', capability_id='synthetic', inputs={},
        outputs={'point': {'runtime_type': 'Point', 'value': ['1', '2']}},
        calculations=({'kind': 'attainment', 'points': {'Q': ['1', '2']}},),
    )
    assert _public_point_semantic_ref(snapshot, source, 'point') == 'Q'
    assert _public_point_semantic_ref(snapshot, replace(source, calculations=()), 'point') == ''
    ambiguous = replace(source, calculations=(
        {'kind': 'attainment', 'points': {'Q': ['1', '2'], 'R': ['1', '2']}},
    ))
    assert _public_point_semantic_ref(snapshot, ambiguous, 'point') == ''
    multiple_outputs = replace(source, outputs={**source.outputs, 'other': source.outputs['point']})
    assert _public_point_semantic_ref(snapshot, multiple_outputs, 'point') == ''
    explicit = replace(source, output_targets={'point': 'R'})
    assert _public_point_semantic_ref(snapshot, explicit, 'point') == 'R'


def test_recorded_frames_use_current_curve_and_recomputed_attainment(recorded):
    import sympy as sp
    snapshot, lesson = recorded
    visual = VisualStepBuilder().build(snapshot=snapshot, lesson=lesson)
    VisualStepIRValidator().validate(visual, lesson=lesson)
    frames = {step.lesson_step_id: step.frames[-1] for step in visual.steps}
    closed = frames['teach:close_parabola_I']
    assert len({r for o in closed.objects if o.component == 'Parabola' for r in o.geometry_refs}) == 1
    assert closed.metadata['mathematical_state']['verified_parameters']['a'] == '1'
    final = frames['teach:solve_a_II']
    params = {p['name']: p for p in final.local_parameters}
    assert params['a']['mathematical_domain']['value'] == '3/4'
    assert params['u']['mathematical_domain']['value'] == '5/9'
    constraint = final.metadata['mathematical_state']['constraints'][0]
    assert constraint['mode'] == 'attainment'
    env = {sp.Symbol(k): sp.sympify(v['mathematical_domain']['value']) for k, v in params.items()}
    expressions = {r: d['expression'] for p in params.values() for r, d in p['parameterized_points'].items()}
    moving_ref = constraint['geometry_refs'][1]
    assert tuple(sp.simplify(sp.sympify(v).subs(env)) for v in expressions[moving_ref]) == (sp.Rational(20, 9), sp.Rational(-4, 3))
