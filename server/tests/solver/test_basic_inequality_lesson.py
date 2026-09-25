"""4B: real verified runtime -> teaching -> declarations -> compiled page."""

import json
import subprocess
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from shuxueshuo_server.solver.explanation import ExplanationSnapshotBuilder
from shuxueshuo_server.solver.explanation.annotated_teaching import (
    AnnotatedTeachingPlanProjector,
)
from shuxueshuo_server.solver.explanation.lesson_ir import (
    LessonAuthoringPipeline,
    RecursiveLessonIRAssembler,
    lesson_ir_from_payload,
)
from shuxueshuo_server.solver.explanation.models import (
    explanation_snapshot_from_payload,
)
from shuxueshuo_server.solver.explanation.scope_lesson import (
    LessonScopeContentValidator,
)
from shuxueshuo_server.solver.explanation.teaching_rules import (
    RuleMaterial,
    TeachingRuleRegistry,
)
from shuxueshuo_server.solver.visual import (
    VisualStepBuilder,
    VisualStepIRValidator,
    forward_compile,
)
from shuxueshuo_server.solver.visual.models import visual_step_ir_from_payload
from shuxueshuo_server.solver.visual.teaching_diagrams import (
    VisualGap,
    default_visual_specs,
    validate_diagram_block,
)
from test_basic_inequality_runtime import plan, solve, source

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    "rows, optional_roles",
    [
        (
            ["m+n>=2*sqrt(m*n)", "2>=2*sqrt(m*n)", "sqrt(m*n)<=1", "m*n<=1"],
            {"fixed_sum_substitution", "root_bound"},
        ),
        (
            ["∵m>0,n>0；∴m+n>=2*sqrt(m*n)", "2>=2*sqrt(m*n)", "sqrt(m*n)<=1", "m*n<=1"],
            {"fixed_sum_substitution", "root_bound"},
        ),
        (["m+n>=2*sqrt(m*n)", "m*n<=1"], set()),
        (["m+n>=2*sqrt(m*n)", "2>=2*sqrt(m*n)", "m*n<=1"], {"fixed_sum_substitution"}),
        (
            ["∵n>0,m>0；∴n+m>=2*sqrt(n*m)", "2*sqrt(n*m)<=2", "1>=sqrt(n*m)", "n*m<=1"],
            {"fixed_sum_substitution", "root_bound"},
        ),
        (["m+m>=2*sqrt(m*m)", "m+n>=2*sqrt(m*n)", "m*n<=1"], set()),
    ],
)
def test_amgm_visual_roles_follow_verified_math_not_row_positions(
    rows, optional_roles, tmp_path
):
    candidate = plan()
    candidate["root_scope"]["goals"][0]["steps"][0]["parameters"]["steps"] = [
        {"math": row} for row in rows
    ]
    result, runtime, _ = solve(candidate=candidate)
    assert result.status == "ok", result.to_dict()
    snapshot = ExplanationSnapshotBuilder().build(runtime.last_success_artifacts)
    evidence = next(
        v["data"]
        for v in snapshot.evidence.values()
        if v.get("schema_version") == "inequality-teaching-evidence/v1"
        and v["step_id"] == "bound"
    )
    roles = evidence["application_roles"]
    assert set(roles) == {"amgm", "bound"} | optional_roles
    for role in roles.values():
        assert role["origins"]
        assert all(origin in evidence["origins"] for origin in role["origins"])
        assert all(
            origin["source"] == rows[origin["step"]] for origin in role["origins"]
        )
    assert "√(mn)" in roles["amgm"]["math"]
    assert roles["bound"]["math"] == "mn ≤ 1"
    lesson = LessonAuthoringPipeline().build(snapshot).lesson
    visual = VisualStepBuilder().build(snapshot=snapshot, lesson=lesson)
    VisualStepIRValidator().validate(visual, lesson=lesson)
    block = visual.steps[1].diagram_blocks[0]["data"]
    assert block["mapped"] == r"\(" + roles["amgm"]["math"] + r"\)"
    assert ("replaced" in block) == ("fixed_sum_substitution" in optional_roles)
    assert ("substituted" in block) == ("root_bound" in optional_roles)
    assert block["relationOrigins"]["bound"] == roles["bound"]["origins"]
    restored = explanation_snapshot_from_payload(snapshot.to_payload())
    assert (
        VisualStepBuilder().build(snapshot=restored, lesson=lesson).to_payload()
        == visual.to_payload()
    )
    compiled = forward_compile(visual)
    compiled.lesson_data["meta"].update(
        id="amgm-shape-regression", generatedFromSolver=True
    )
    compiled.lesson_data["problem"]["answerText"] = "1"
    (tmp_path / "lesson-data.json").write_text(
        json.dumps(compiled.lesson_data, ensure_ascii=False)
    )
    subprocess.run(
        [
            "node",
            str(ROOT / "tools/build-text-page.mjs"),
            str(tmp_path),
            "--output",
            str(tmp_path / "lesson.html"),
        ],
        check=True,
        capture_output=True,
    )


@pytest.fixture(scope="module")
def snapshot():
    candidate = json.loads(
        (
            ROOT
            / "internal/functional-plan-fixtures/basic-inequality-q01-stage4b.functional-plan.json"
        ).read_text()
    )
    result, runtime, _ = solve(candidate=candidate)
    assert result.status == "ok", result.to_dict()
    return ExplanationSnapshotBuilder().build(runtime.last_success_artifacts)


def test_verified_snapshot_builds_three_units_and_replays(snapshot):
    built = LessonAuthoringPipeline().build(snapshot)
    assert [s.title for s in built.lesson.steps] == [
        "观察结构",
        "应用基本不等式",
        "验证取等",
    ]
    assert not built.projection.diagnostics
    assert all(s.visuals for s in built.lesson.steps)
    assert "mn≤1" not in "".join(built.lesson.steps[0].box)
    assert "2 ≥ 2√(mn)" in str(built.lesson.steps[1].derive)
    assert "m+n = 2" in str(built.lesson.steps[2].derive)
    assert "mn = 1" in str(built.lesson.steps[2].derive)
    restored = explanation_snapshot_from_payload(snapshot.to_payload())
    assert (
        LessonAuthoringPipeline().build(restored).lesson.to_payload()
        == built.lesson.to_payload()
    )
    assert (
        lesson_ir_from_payload(built.lesson.to_payload()).to_payload()
        == built.lesson.to_payload()
    )
    visual = VisualStepBuilder().build(snapshot=snapshot, lesson=built.lesson)
    VisualStepIRValidator().validate(visual, lesson=built.lesson)
    assert all(
        not step.frames and len(step.diagram_blocks) == 1 for step in visual.steps
    )
    assert (
        visual_step_ir_from_payload(visual.to_payload()).to_payload()
        == visual.to_payload()
    )
    assert "visuals" not in json.dumps(built.projection.plan.to_payload())
    assert "witness_proof" not in json.dumps(snapshot.to_payload())


def test_direct_application_section_label_is_code_owned_and_replayable(snapshot):
    from shuxueshuo_server.solver.explanation.amgm_sequence_rule import sequence_rule_registry

    for problem_id in (snapshot.problem_id, "renamed-problem"):
        snap = replace(snapshot, problem_id=problem_id)
        built = LessonAuthoringPipeline(rule_registry=sequence_rule_registry()).build(snap)
        assert {s.section_label for s in built.lesson.steps} == {"直接应用基本不等式"}
        restored = lesson_ir_from_payload(built.lesson.to_payload())
        assert restored.to_payload() == built.lesson.to_payload()
        visual = VisualStepBuilder().build(snapshot=snap, lesson=restored)
        assert {s["section"] for s in forward_compile(visual).lesson_data["steps"]} == {"直接应用基本不等式"}


def test_illegal_llm_merge_recovers_drafts_and_visuals(snapshot):
    projection = AnnotatedTeachingPlanProjector().project(snapshot)
    validator = LessonScopeContentValidator(
        plan=projection.plan, authority=projection.authority
    )
    content = deepcopy(validator.deterministic_fallback)
    rows = content["problem"]["goals"]["problem.maximum"]
    rows[0]["source_steps"] += rows[1]["source_steps"]
    rows[0]["derive"] += rows[1]["derive"]
    del rows[1]
    result = validator.validate_payload(content)
    assert result.independent_material_merge_repaired
    built = RecursiveLessonIRAssembler().assemble(snapshot, projection, result)
    assert len(built.lesson.steps) == 3
    assert all(s.visuals for s in built.lesson.steps)


def overview_rule(ref, rows, evidence):
    if not rows:
        return rows
    first = rows[0]
    overview = replace(
        first.material, suggested_title="路线总览", suggested_nav_title="路线总览"
    )
    authority = deepcopy(first.authority)
    authority["unit_key"] = "test.overview"
    return (RuleMaterial(overview, authority, first.source, (), first.covers), *rows)


def test_rule_created_overview_uses_same_visual_binding(snapshot):
    from shuxueshuo_server.solver.visual.teaching_diagrams import VisualSpec, structure

    def custom_overview(ref, rows, evidence):
        result = overview_rule(ref, rows, evidence)
        result[0].authority["visuals"][0]["spec_id"] = "test.overview"
        return result

    registry = TeachingRuleRegistry()
    registry.register("test.overview", custom_overview)
    built = LessonAuthoringPipeline(rule_registry=registry).build(snapshot)
    assert len(built.lesson.steps) == 4
    assert built.lesson.steps[0].title == "路线总览"
    assert built.lesson.steps[0].capability_ids == ("apply_two_term_amgm",)
    visual_specs = default_visual_specs()
    visual_specs.register(
        VisualSpec("test.overview", "basic-inequality-structure-scan", structure)
    )
    visual = VisualStepBuilder().build(
        snapshot=snapshot, lesson=built.lesson, teaching_visual_specs=visual_specs
    )
    assert all(len(s.diagram_blocks) == 1 for s in visual.steps)
    assert not visual.metadata.get("visual_gaps")
    assert visual.steps[0].diagram_blocks[0]["spec_id"] == "test.overview"
    assert built.projection.authority["rule_composition"]


def test_rule_cannot_drop_covered_material(snapshot):
    registry = TeachingRuleRegistry()
    registry.register("test.drop", lambda ref, rows, evidence: rows[1:])
    with pytest.raises(ValueError, match="coverage"):
        LessonAuthoringPipeline(rule_registry=registry).build(snapshot)


def test_same_spec_different_sources_remains_two_blocks(snapshot):
    registry = default_visual_specs()
    declarations = [
        {"spec_id": "basic_inequality.structure", "roles": {"evidence": ref}}
        for ref in ("bound", "attain")
    ]
    blocks = registry.bind(
        declarations, snapshot=snapshot, source_step_ids=("bound", "attain")
    )
    assert len(blocks) == 2
    assert blocks[0]["evidence_refs"] != blocks[1]["evidence_refs"]


@pytest.mark.parametrize(
    "declaration",
    [
        {"spec_id": "missing", "roles": {"evidence": "bound"}},
        {"spec_id": "basic_inequality.structure", "roles": {}},
        {"spec_id": "basic_inequality.structure", "roles": {"evidence": "attain"}},
    ],
)
def test_missing_or_unowned_visual_roles_fail(snapshot, declaration):
    with pytest.raises(VisualGap):
        default_visual_specs().bind(
            [declaration], snapshot=snapshot, source_step_ids=("bound",)
        )


def test_missing_visual_reports_gap_without_deleting_text(snapshot):
    built = LessonAuthoringPipeline().build(snapshot)
    goal = built.lesson.root_scope.goals[0]
    first = replace(
        goal.steps[0], visuals=({"spec_id": "missing", "roles": {"evidence": "bound"}},)
    )
    lesson = replace(
        built.lesson,
        root_scope=replace(
            built.lesson.root_scope,
            goals=(replace(goal, steps=(first, *goal.steps[1:])),),
        ),
    )
    visual = VisualStepBuilder().build(snapshot=snapshot, lesson=lesson)
    assert len(visual.metadata["visual_gaps"]) == 1
    assert lesson.steps[0].derive
    assert not visual.steps[0].diagram_blocks


def test_tampered_component_version_is_rejected(snapshot):
    lesson = LessonAuthoringPipeline().build(snapshot).lesson
    visual = VisualStepBuilder().build(snapshot=snapshot, lesson=lesson)
    block = deepcopy(visual.steps[0].diagram_blocks[0])
    block["component_version"] = 999
    with pytest.raises(VisualGap):
        validate_diagram_block(block)


def test_renamed_problem_and_constant_use_same_teaching():
    data = source()
    data["problem_id"] = "anonymous-lesson"
    for entity, name in zip(data["entities"], ("a", "b"), strict=True):
        entity.update(name=name, handle=f"symbol:s0:{name}")
    for fact, math in zip(data["facts"], ("a>0", "b>0", "a+b=6"), strict=True):
        fact.update(normalized_expression=math, source_text=math)
    data["question_goals"][0]["target_expression"] = "a*b"
    candidate = plan()
    calls = candidate["root_scope"]["goals"][0]["steps"]
    calls[0]["parameters"]["steps"] = [
        {"math": r}
        for r in ["a+b>=2*sqrt(a*b)", "6>=2*sqrt(a*b)", "sqrt(a*b)<=3", "a*b<=9"]
    ]
    calls[1]["parameters"]["steps"] = [
        {"math": r} for r in ["a=b", "a=b=3", "a+b=6", "a*b=9"]
    ]
    result, runtime, _ = solve(data=data, candidate=candidate)
    assert result.status == "ok"
    snapshot = ExplanationSnapshotBuilder().build(runtime.last_success_artifacts)
    lesson = LessonAuthoringPipeline().build(snapshot).lesson
    visual = VisualStepBuilder().build(snapshot=snapshot, lesson=lesson)
    assert len(lesson.steps) == 3
    payload = str(visual.steps[2].diagram_blocks)
    assert "a=3" in payload and "b=3" in payload and "9" in payload
    assert "m=n=1" not in payload


def test_compiles_generated_page_without_authored_answers(snapshot, tmp_path):
    lesson = LessonAuthoringPipeline().build(snapshot).lesson
    visual = VisualStepBuilder().build(snapshot=snapshot, lesson=lesson)
    compiled = forward_compile(visual)
    data = compiled.lesson_data
    data["meta"].update(id="no-authored-page", generatedFromSolver=True)
    data["problem"]["answerText"] = "1"
    (tmp_path / "lesson-data.json").write_text(json.dumps(data, ensure_ascii=False))
    subprocess.run(
        [
            "node",
            str(ROOT / "tools/build-text-page.mjs"),
            str(tmp_path),
            "--output",
            str(tmp_path / "lesson.html"),
        ],
        check=True,
        capture_output=True,
    )
    html = (tmp_path / "lesson.html").read_text()
    assert all(
        k in html
        for k in (
            "basic-inequality-structure-scan",
            "basic-inequality-mapping",
            "basic-inequality-equality-check",
        )
    )
    assert "witness_proof" not in html and "AmgmBound" not in html


def test_recorded_real_lesson_has_no_fallback(snapshot):
    from shuxueshuo_server.solver.explanation.scope_lesson import (
        ScopeLessonAuthoringService,
    )

    class RecordedClient:
        def complete(self, payload, **kwargs):
            return (
                ROOT
                / "server/tests/solver/fixtures/lesson_scope_authoring_vnext/basic_inequality_q01/scope-content.json"
            ).read_text()

    built = LessonAuthoringPipeline(
        authoring_service=ScopeLessonAuthoringService(client=RecordedClient())
    ).build(snapshot)
    assert built.generation.metadata_payload()["direct_acceptance"]
    assert not built.generation.metadata_payload()["fallback_used"]
    metadata = json.loads(
        (
            ROOT
            / "server/tests/solver/fixtures/lesson_scope_authoring_vnext/basic_inequality_q01/call-metadata.json"
        ).read_text()
    )
    # The recorded response remains valid after prompt wording evolves. Keep
    # historical call metadata unchanged; compare its material/schema contract.
    current_hashes = built.generation.metadata_payload()["hashes"]
    assert current_hashes["output_schema"] == metadata["hashes"]["output_schema"]
    assert len(current_hashes["prompt"]) == 64
    assert len(built.lesson.steps) == 3
    assert all(step.visuals for step in built.lesson.steps)


def test_unavailable_llm_retains_three_drafts_and_visuals(snapshot):
    from shuxueshuo_server.solver.explanation.scope_lesson import (
        ScopeLessonAuthoringService,
    )

    class UnavailableClient:
        def complete(self, payload, **kwargs):
            raise TimeoutError("unavailable provider")

    service = ScopeLessonAuthoringService(
        client=UnavailableClient(), sleep_fn=lambda _: None
    )
    built = LessonAuthoringPipeline(authoring_service=service).build(snapshot)
    assert built.validation.whole_fallback
    assert len(built.lesson.steps) == 3
    visual = VisualStepBuilder().build(snapshot=snapshot, lesson=built.lesson)
    assert all(step.diagram_blocks for step in visual.steps)


def test_visual_authority_cannot_be_replaced_after_llm_validation(snapshot):
    from shuxueshuo_server.solver.explanation.lesson_ir import LessonIRValidationError

    projection = AnnotatedTeachingPlanProjector().project(snapshot)
    validator = LessonScopeContentValidator(
        plan=projection.plan, authority=projection.authority
    )
    result = validator.validate_payload(validator.deterministic_fallback)
    rows = dict(result.bound_steps)
    key = next(k for k, values in rows.items() if values)
    rows[key] = (replace(rows[key][0], visuals=()), *rows[key][1:])
    with pytest.raises(LessonIRValidationError, match="provenance_drift"):
        RecursiveLessonIRAssembler().assemble(
            snapshot, projection, replace(result, bound_steps=rows)
        )


def test_missing_public_evidence_is_reported(snapshot):
    missing = replace(snapshot, evidence={})
    with pytest.raises(ValueError, match="inequality_public_teaching_evidence_missing"):
        LessonAuthoringPipeline().build(missing)


def test_method_teaching_declarations_are_mutually_exclusive():
    from shuxueshuo_server.solver.runtime.methods._spec import MethodSpecContractError
    from shuxueshuo_server.solver.runtime.methods.apply_two_term_amgm import SPEC

    with pytest.raises(MethodSpecContractError, match="single or multiple"):
        replace(SPEC, teaching_unit=SPEC.teaching_units[0])


def test_diagrams_coexist_with_scene_and_survive_serialization(snapshot):
    from shuxueshuo_server.solver.visual.models import VisualFrame, VisualObject

    lesson = LessonAuthoringPipeline().build(snapshot).lesson
    visual = VisualStepBuilder().build(snapshot=snapshot, lesson=lesson)
    first = visual.root_scope.goals[0].steps[0]
    # Exercise mixed output without inventing geometry in the q01 builder.
    frame = VisualFrame(
        "mixed-frame",
        ("test_scene",),
        {"xMin": -2, "xMax": 2, "yMin": -2, "yMax": 2},
        (
            VisualObject(
                "point:origin",
                "Point",
                "origin",
                ({"kind": "test", "ref": "origin"},),
                ("origin",),
                "focus",
                {"id": "origin", "x": 0, "y": 0},
            ),
        ),
    )
    mixed = replace(
        first,
        visual_mode="scene",
        frames=(frame,),
        diagram_blocks=first.diagram_blocks * 2,
    )
    goal = visual.root_scope.goals[0]
    visual = replace(
        visual,
        root_scope=replace(
            visual.root_scope, goals=(replace(goal, steps=(mixed, *goal.steps[1:])),)
        ),
    )
    restored = visual_step_ir_from_payload(visual.to_payload())
    assert restored.steps[0].frames == mixed.frames
    assert len(restored.steps[0].diagram_blocks) == 2
    compiled = forward_compile(visual)
    assert (
        compiled.lesson_data["steps"][0]["visual"]["kind"] == "teaching-diagram-group"
    )
    assert (
        len(compiled.step_decorations["steps"][first.lesson_step_id]["visualFrames"])
        == 1
    )
