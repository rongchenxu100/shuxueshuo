from __future__ import annotations

import inspect
import json
from pathlib import Path
import subprocess

import pytest

from shuxueshuo_server.solver.visual import (
    ComponentTypeSpec,
    ComponentTypeSpecRegistry,
    JsonObject,
    LayerRegistry,
    VisualStep,
    VisualStepIR,
    VisualStepIRValidationError,
    VisualStepIRValidator,
    default_component_registry,
    default_layer_registry,
    forward_compile,
    reverse_compile,
    resolved_steps_with_carry_forward,
)
from shuxueshuo_server.solver.visual import scene_accumulator
from shuxueshuo_server.solver.visual.models import visual_step_ir_from_payload
from shuxueshuo_server.solver.visual.palette import COLOR_ACCENT, COLOR_MUTED, COLOR_RESULT, COLOR_TEXT
from shuxueshuo_server.solver.visual.registry import low_level_for_visual_type


ROOT = Path(__file__).resolve().parents[3]
HEPING_LESSON_SPEC = ROOT / "internal/lesson-specs/tj-2026-heping-yimo-25"
ROUND_TRIP_LESSON_SPECS = (
    "tj-2026-nankai-yimo-25",
    "tj-2026-hexi-yimo-25",
    "tj-2026-xiqing-yimo-25",
)


def test_visual_step_ir_validator_accepts_minimal_valid_ir() -> None:
    visual_ir = _minimal_visual_ir()

    VisualStepIRValidator().validate(visual_ir)


def test_visual_step_ir_payload_round_trip() -> None:
    visual_ir = _minimal_visual_ir()
    payload = visual_ir.to_payload()
    restored = visual_step_ir_from_payload(payload)

    assert restored.to_payload() == payload


def test_visual_step_ir_validator_rejects_missing_lesson_step_id() -> None:
    visual_ir = _minimal_visual_ir(
        steps=(
            VisualStep(
                visual_step_id="visual:missing",
                lesson_step_id="",
                scope_id="i",
                scene={"inherits_from": "global", "add": []},
            ),
        )
    )

    with pytest.raises(VisualStepIRValidationError, match="missing lesson_step_id"):
        VisualStepIRValidator().validate(visual_ir)


def test_visual_step_ir_validator_rejects_unknown_component_and_invalid_state() -> None:
    visual_ir = _minimal_visual_ir(
        scene_add=(
            {"component": "NoSuchComponent", "handle": "point:i:A"},
            {"component": "Point", "handle": "point:i:B", "state": "sparkly"},
        )
    )

    with pytest.raises(VisualStepIRValidationError, match="unknown component"):
        VisualStepIRValidator().validate(visual_ir)

    visual_ir = _minimal_visual_ir(
        scene_add=({"component": "Point", "handle": "point:i:B", "state": "sparkly"},)
    )
    with pytest.raises(VisualStepIRValidationError, match="invalid state"):
        VisualStepIRValidator().validate(visual_ir)


def test_visual_step_ir_validator_rejects_invalid_state_override() -> None:
    visual_ir = _minimal_visual_ir(
        state_overrides=({"state": "highlight"},)
    )
    with pytest.raises(VisualStepIRValidationError, match="missing handle"):
        VisualStepIRValidator().validate(visual_ir)

    visual_ir = _minimal_visual_ir(
        state_overrides=({"handle": "point:i:A", "state": "glowing"},)
    )
    with pytest.raises(VisualStepIRValidationError, match="invalid state"):
        VisualStepIRValidator().validate(visual_ir)


def test_visual_step_ir_validator_rejects_invalid_carry_forward_item() -> None:
    visual_ir = _minimal_visual_ir(
        scene_add=(
            {
                "component": "ColoredLine",
                "from": "A",
                "to": "B",
                "persistence": "carry_forward",
            },
        )
    )

    with pytest.raises(VisualStepIRValidationError, match="requires handle"):
        VisualStepIRValidator().validate(visual_ir)


def test_scene_accumulator_carries_decays_overrides_and_drops_step_only_items() -> None:
    visual_ir = _minimal_visual_ir(
        steps=(
            _visual_step(
                "s1",
                scene_add=(
                    {
                        "component": "ColoredLine",
                        "handle": "line:i:BE",
                        "from": "B",
                        "to": "E",
                        "state": "highlight",
                        "persistence": "carry_forward",
                        "decay_state": "muted",
                    },
                    {
                        "component": "AngleArc",
                        "vertex": "B",
                        "rayA": "O",
                        "rayB": "E",
                        "persistence": "step_only",
                    },
                ),
            ),
            _visual_step(
                "s2",
                scene_add=(),
                state_overrides=({"handle": "line:i:BE", "state": "highlight"},),
            ),
            _visual_step("s3", scene_add=(), hide=("line:i:BE",)),
        ),
        lesson_steps=("s1", "s2", "s3"),
    )

    resolved = resolved_steps_with_carry_forward(visual_ir.steps)

    assert any(item.get("handle") == "line:i:BE" for item in resolved[0].scene["add"])
    assert any(item.get("component") == "AngleArc" for item in resolved[0].scene["add"])
    assert resolved[1].scene["add"] == [
        {
            "component": "ColoredLine",
            "handle": "line:i:BE",
            "from": "B",
            "to": "E",
            "state": "highlight",
            "persistence": "carry_forward",
            "decay_state": "muted",
        }
    ]
    assert resolved[2].scene["add"] == []


def test_scene_accumulator_priority_uses_palette_constants() -> None:
    assert scene_accumulator._current_item_priority({"color": COLOR_ACCENT}) == 90
    assert scene_accumulator._current_item_priority({"color": COLOR_RESULT}) == 90
    assert scene_accumulator._current_item_priority({"color": COLOR_TEXT}) == 50
    assert scene_accumulator._current_item_priority({"color": COLOR_MUTED}) == 50

    source = inspect.getsource(scene_accumulator._current_item_priority)
    assert "#dc2626" not in source
    assert "#b45309" not in source


def test_forward_compile_accumulates_only_when_scene_model_requests_it() -> None:
    base = _minimal_visual_ir(
        steps=(
            _visual_step(
                "s1",
                scene_add=(
                    {
                        "component": "ColoredLine",
                        "handle": "line:i:BE",
                        "from": "B",
                        "to": "E",
                        "persistence": "carry_forward",
                        "decay_state": "muted",
                        "metadata": {"low_level_type": "coloredLine"},
                    },
                ),
            ),
            _visual_step("s2", scene_add=()),
        ),
        lesson_steps=("s1", "s2"),
    )

    compiled_plain = forward_compile(base)
    assert "add" not in compiled_plain.step_decorations["steps"]["s2"]

    payload = base.to_payload()
    payload["metadata"]["scene_model"] = "section_accumulator"
    compiled_accumulated = forward_compile(visual_step_ir_from_payload(payload))
    assert compiled_accumulated.step_decorations["steps"]["s2"]["add"] == [
        {
            "type": "coloredLine",
            "from": "B",
            "to": "E",
        }
    ]


def test_scene_accumulator_resets_when_scope_root_changes() -> None:
    visual_ir = _minimal_visual_ir(
        steps=(
            _visual_step(
                "s1",
                scope_id="i_2",
                scene_add=(
                    {
                        "component": "ColoredLine",
                        "handle": "line:i_2:BE",
                        "from": "B1",
                        "to": "E1",
                        "persistence": "carry_forward",
                    },
                ),
            ),
            _visual_step("s2", scope_id="ii", scene_add=()),
        ),
        lesson_steps=("s1", "s2"),
    )

    resolved = resolved_steps_with_carry_forward(visual_ir.steps)

    assert any(item.get("handle") == "line:i_2:BE" for item in resolved[0].scene["add"])
    assert resolved[1].scene["add"] == []


def test_visual_step_ir_validator_rejects_bad_annotation_text_source() -> None:
    visual_ir = _minimal_visual_ir(
        annotations=(
            {
                "type": "label",
                "target": "point:i:A",
                "text_source": "lesson_step.box",
                "index": 99,
            },
        )
    )

    with pytest.raises(VisualStepIRValidationError, match="box index out of range"):
        VisualStepIRValidator().validate(visual_ir)


def test_visual_step_ir_validator_rejects_empty_annotation() -> None:
    visual_ir = _minimal_visual_ir(
        annotations=({"type": "label", "target": "point:i:A"},)
    )

    with pytest.raises(VisualStepIRValidationError, match="requires text_source or text"):
        VisualStepIRValidator().validate(visual_ir)

    visual_ir = _minimal_visual_ir(
        annotations=({"type": "label", "target": "point:i:A", "text": "  "},)
    )

    with pytest.raises(VisualStepIRValidationError, match="annotation text cannot be empty"):
        VisualStepIRValidator().validate(visual_ir)


def test_visual_step_ir_validator_rejects_unsafe_visual_gap_payload() -> None:
    visual_ir = _minimal_visual_ir(
        scene_add=(
            {
                "component": "VisualGap",
                "expected_role": "p2",
                "reason": "missing role",
                "coordinates": ["0", "0"],
            },
        )
    )

    with pytest.raises(VisualStepIRValidationError, match="VisualGap cannot carry geometry fields"):
        VisualStepIRValidator().validate(visual_ir)


def test_visual_step_ir_validator_checks_interactions_timeline_and_hide_refs() -> None:
    visual_ir = _minimal_visual_ir(
        steps=(
            VisualStep(
                visual_step_id="visual:s1",
                lesson_step_id="s1",
                scope_id="i",
                scene={"inherits_from": "global", "add": [], "hide": ["missingLayer"]},
            ),
        )
    )
    with pytest.raises(VisualStepIRValidationError, match="unknown hide target"):
        VisualStepIRValidator().validate(visual_ir)

    visual_ir = _minimal_visual_ir(
        steps=(
            VisualStep(
                visual_step_id="visual:s1",
                lesson_step_id="s1",
                scope_id="i",
                scene={"inherits_from": "global", "add": []},
                interactions=({"component": "DragEverything"},),
            ),
        )
    )
    with pytest.raises(VisualStepIRValidationError, match="unknown interaction component"):
        VisualStepIRValidator().validate(visual_ir)

    visual_ir = _minimal_visual_ir(
        steps=(
            VisualStep(
                visual_step_id="visual:s1",
                lesson_step_id="s1",
                scope_id="i",
                scene={"inherits_from": "global", "add": []},
                timeline={"mode": "cinematic"},
            ),
        )
    )
    with pytest.raises(VisualStepIRValidationError, match="invalid timeline mode"):
        VisualStepIRValidator().validate(visual_ir)


def test_component_registry_rejects_duplicates_and_covers_low_level_types() -> None:
    registry = default_component_registry()

    for low_level in {
        "angleArc",
        "coloredLine",
        "coordinateLabel",
        "dashedLine",
        "grid",
        "parabola",
        "point",
        "polygon",
        "ray",
        "segment",
    }:
        assert low_level in registry.low_level_types
    assert registry.require("DistanceMarker").compiles_to == ("segment", "coordinateLabel")

    with pytest.raises(ValueError, match="duplicate visual component type"):
        ComponentTypeSpecRegistry(
            (
                ComponentTypeSpec("DistanceMarker", ("segment",)),
                ComponentTypeSpec("DistanceMarker", ("coordinateLabel",)),
            )
        )


def test_visual_type_reverse_lookup_uses_registered_low_level_mapping() -> None:
    payload: JsonObject = {"component": "Point"}

    assert payload["component"] == "Point"
    assert low_level_for_visual_type("Point") == "point"
    assert low_level_for_visual_type("ColoredLine") == "coloredLine"
    assert low_level_for_visual_type("DistanceMarker") is None


def test_layer_registry_is_configurable_and_rejects_unknown_refs() -> None:
    registry = LayerRegistry({"global": "global", "section:i": "partI"})

    assert registry.require_layer_key("section:i") == "partI"
    assert registry.semantic_for_layer_key("partI") == "section:i"

    with pytest.raises(KeyError, match="unknown semantic layer ref"):
        registry.require_layer_key("section:ii")

    with pytest.raises(ValueError, match="must define global"):
        LayerRegistry({"section:i": "partI"})


def test_reverse_compile_heping_visual_step_ir_round_trips_and_validates(tmp_path) -> None:
    geometry_spec, step_decorations, lesson_data = _load_heping_specs()
    visual_ir = reverse_compile(geometry_spec, step_decorations, lesson_data)

    VisualStepIRValidator().validate(visual_ir)
    assert len(visual_ir.steps) == len(step_decorations["steps"])
    assert _interaction_count(visual_ir) == _expected_interaction_count(lesson_data)
    for step in visual_ir.steps:
        original_add = step_decorations["steps"][step.lesson_step_id].get("add") or []
        assert len(step.scene.get("add") or []) >= len(original_add)

    compiled = forward_compile(visual_ir)
    assert compiled.step_decorations == step_decorations
    assert compiled.geometry_spec == geometry_spec
    assert compiled.lesson_data == lesson_data

    _write_compiled(tmp_path, compiled)
    result = subprocess.run(
        ["node", str(ROOT / "tools/validate-geometry-spec.mjs"), str(tmp_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_reverse_compile_derives_scope_from_layer_registry_not_step_id_prefix() -> None:
    geometry_spec = {"version": 1, "id": "scope-case", "domain": {}}
    step_decorations = {
        "layers": {
            "global": {"elements": []},
            "partI": {"stepStartsWith": ["alpha"], "elements": []},
        },
        "steps": {"alpha1": {"add": []}},
    }
    lesson_data = {"meta": {"id": "scope-case"}, "steps": [{"id": "alpha1", "box": []}]}

    visual_ir = reverse_compile(geometry_spec, step_decorations, lesson_data)

    assert visual_ir.steps[0].scope_id == "i"


def test_reverse_compile_scope_is_none_when_no_section_layer_matches() -> None:
    geometry_spec = {"version": 1, "id": "scope-case", "domain": {}}
    step_decorations = {
        "layers": {"global": {"elements": []}},
        "steps": {"q1s1": {"add": []}, "iii1": {"add": []}},
    }
    lesson_data = {
        "meta": {"id": "scope-case"},
        "steps": [{"id": "q1s1", "box": []}, {"id": "iii1", "box": []}],
    }

    visual_ir = reverse_compile(geometry_spec, step_decorations, lesson_data)

    assert [step.scope_id for step in visual_ir.steps] == [None, None]


def test_forward_compile_rejects_component_without_low_level_mapping() -> None:
    visual_ir = _minimal_visual_ir(
        scene_add=({"component": "SyntheticComposite", "handle": "point:i:A"},)
    )

    with pytest.raises(ValueError, match="cannot compile component"):
        forward_compile(visual_ir)


@pytest.mark.parametrize("problem_id", ROUND_TRIP_LESSON_SPECS)
def test_reverse_forward_round_trip_multiple_lesson_specs(problem_id: str) -> None:
    geometry_spec, step_decorations, lesson_data = _load_lesson_specs(problem_id)

    visual_ir = reverse_compile(geometry_spec, step_decorations, lesson_data)
    VisualStepIRValidator().validate(visual_ir)
    compiled = forward_compile(visual_ir)

    assert compiled.geometry_spec == geometry_spec
    assert compiled.lesson_data == lesson_data
    assert compiled.step_decorations == step_decorations


def _minimal_visual_ir(
    *,
    steps: tuple[VisualStep, ...] | None = None,
    scene_add: tuple[dict, ...] = ({"component": "Point", "handle": "point:i:A", "state": "visible"},),
    state_overrides: tuple[dict, ...] = (),
    annotations: tuple[dict, ...] = (),
    lesson_steps: tuple[str, ...] | None = None,
) -> VisualStepIR:
    step = VisualStep(
        visual_step_id="visual:s1",
        lesson_step_id="s1",
        scope_id="i",
        geometry_context={
            "coordinate_system": "cartesian_2d",
            "domain": {"minX": 0, "maxX": 1, "minY": 0, "maxY": 1},
            "domain_override": None,
            "moving_param": None,
            "expression_env_handles": [],
            "panels": [],
        },
        scene={
            "inherits_from": "global",
            "add": list(scene_add),
            "state_overrides": list(state_overrides),
            "hide": [],
            "focus": {"primary": [], "dim": []},
            "annotations": list(annotations),
        },
    )
    return VisualStepIR(
        version=1,
        problem_id="minimal",
        geometry_spec={"version": 1, "id": "minimal", "domain": {}},
        lesson_data={
            "meta": {"id": "minimal"},
            "steps": [{"id": step_id, "box": ["A(0,0)"]} for step_id in (lesson_steps or ("s1",))],
        },
        layers={"global": {"elements": []}},
        layer_registry=dict(default_layer_registry().semantic_to_layer),
        steps=steps or (step,),
    )


def _visual_step(
    step_id: str,
    *,
    scope_id: str = "i",
    scene_add: tuple[dict, ...],
    state_overrides: tuple[dict, ...] = (),
    hide: tuple[str, ...] = (),
) -> VisualStep:
    return VisualStep(
        visual_step_id=f"visual:{step_id}",
        lesson_step_id=step_id,
        scope_id=scope_id,
        scene={
            "inherits_from": "global",
            "add": list(scene_add),
            "state_overrides": list(state_overrides),
            "hide": list(hide),
            "focus": {"primary": [], "dim": []},
            "annotations": [],
        },
    )


def _load_heping_specs() -> tuple[dict, dict, dict]:
    return _load_lesson_specs("tj-2026-heping-yimo-25")


def _load_lesson_specs(problem_id: str) -> tuple[dict, dict, dict]:
    base = ROOT / "internal/lesson-specs" / problem_id
    return (
        json.loads((base / "geometry-spec.json").read_text(encoding="utf-8")),
        json.loads((base / "step-decorations.json").read_text(encoding="utf-8")),
        json.loads((base / "lesson-data.json").read_text(encoding="utf-8")),
    )


def _interaction_count(visual_ir: VisualStepIR) -> int:
    return sum(len(step.interactions) for step in visual_ir.steps)


def _expected_interaction_count(lesson_data: dict) -> int:
    local = sum(1 for step in lesson_data.get("steps") or [] if step.get("localControls"))
    movable = sum(1 for policy in (lesson_data.get("policies") or {}).values() if policy.get("movable"))
    return local + movable


def _write_compiled(tmp_path: Path, compiled) -> None:
    (tmp_path / "geometry-spec.json").write_text(
        json.dumps(compiled.geometry_spec, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (tmp_path / "step-decorations.json").write_text(
        json.dumps(compiled.step_decorations, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (tmp_path / "lesson-data.json").write_text(
        json.dumps(compiled.lesson_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
