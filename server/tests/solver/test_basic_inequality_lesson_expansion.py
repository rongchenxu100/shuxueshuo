"""Verified generic minimum routes reach persisted, component-bound pages."""

import json
import subprocess
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from shuxueshuo_server.solver.explanation import ExplanationSnapshotBuilder
from shuxueshuo_server.solver.explanation.amgm_sequence_rule import (
    sequence_rule_registry,
)
from shuxueshuo_server.solver.explanation.annotated_teaching import (
    AnnotatedTeachingPlanProjector,
)
from shuxueshuo_server.solver.explanation.lesson_ir import (
    LessonAuthoringPipeline,
    lesson_ir_from_payload,
)
from shuxueshuo_server.solver.explanation.models import (
    explanation_snapshot_from_payload,
)
from shuxueshuo_server.solver.runtime.rewrite_teaching_evidence import (
    RewriteTeachingEvidence,
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
)
from tools.run_basic_inequality_stage4a import run

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def snapshots(tmp_path_factory):
    output = tmp_path_factory.mktemp("minimum-pages")
    result = {}
    for case in ("q03", "q07", "q08"):
        solved, runtime = run(
            gold=FIXTURES / f"math-notation-v1/basic-inequality/{case}.json",
            problem_ir=FIXTURES
            / f"basic-inequality-problem-ir/v1/{case}/problem-ir.json",
            output=output / case,
            mode="recorded",
            plan=FIXTURES / f"basic-inequality-stage4/{case}.json",
        )
        assert solved.status == "ok", solved.to_dict()
        result[case] = ExplanationSnapshotBuilder().build(
            runtime.last_success_artifacts
        )
    return result


@pytest.mark.parametrize("case", ["q03", "q07", "q08"])
def test_minimum_pages_cover_verified_material_and_replay(case, snapshots, tmp_path):
    snapshot = snapshots[case]
    registry = sequence_rule_registry()
    built = LessonAuthoringPipeline(rule_registry=registry).build(snapshot)
    assert not built.projection.diagnostics
    assert not built.validation.fallback_used
    lesson = built.lesson
    assert len(lesson.steps) == (3 if case == "q08" else 4)
    assert all(s.visuals and s.derive for s in lesson.steps)
    assert lesson.steps[-1].title == "验证取等"
    visual = VisualStepBuilder().build(snapshot=snapshot, lesson=lesson)
    VisualStepIRValidator().validate(visual, lesson=lesson)
    assert not visual.metadata.get("visual_gaps")
    assert all(s.diagram_blocks for s in visual.steps)
    if case == "q07":
        assert lesson.steps[0].source_step_ids == ("first", "bound")
        assert lesson.steps[0].teaching_unit_keys == ("amgm_sequence_overview",)
        assert "2次" in lesson.steps[0].goal
        assert [s.title for s in lesson.steps[:3]] == [
            "观察结构：先消元，再求解",
            "应用基本不等式消元",
            "再次应用基本不等式取极值",
        ]
        assert [s.nav_title for s in lesson.steps[1:3]] == [
            "应用基本不等式消元",
            "再次应用基本不等式取极值",
        ]
        cards = visual.steps[0].diagram_blocks[0]["data"]["organization"][
            "purposeCards"
        ]
        assert [c["progress"] for c in cards] == ["2 → 1", "1 → 定值"]
        assert cards[0]["purpose"] == "消去 a"
        assert cards[1]["purpose"] == "求解"
        planning = visual.steps[0].diagram_blocks[0]["data"]["organization"][
            "relationCountHint"
        ]
        assert [planning[k]["value"] for k in ("variable", "condition", "result")] == [
            "2",
            "0",
            "2",
        ]
        assert "规划" in lesson.steps[0].goal
        assert "b" in cards[0]["after"] and "a" not in cards[0]["after"].replace(
            "frac", ""
        )
        assert len(visual.steps[0].diagram_blocks[0]["evidence_refs"]) == 2
        assert [s.teaching_unit_keys for s in lesson.steps[1:3]] == [
            ("amgm_apply",)
        ] * 2
    elif case == "q03":
        assert [s.title for s in lesson.steps[:2]] == ["观察结构：配齐次式", "配齐次式"]
        assert (
            visual.steps[0].diagram_blocks[0]["data"]["organization"][
                "homogenizationHint"
            ]["resultDegree"]
            == "0"
        )
    else:
        assert lesson.steps[0].title == "观察结构：通分显条件"
        assert (
            visual.steps[0].diagram_blocks[0]["spec_id"]
            == "expression_rewrite.fraction_observation"
        )
        assert lesson.steps[0].source_step_ids == ("rewrite", "bound")
        assert r"\frac{" in str(lesson.steps[0].derive)
    if case == "q08":
        assert " 或 " in visual.steps[-1].diagram_blocks[0]["data"]["solved"]
    restored = explanation_snapshot_from_payload(snapshot.to_payload())
    assert (
        LessonAuthoringPipeline(rule_registry=registry)
        .build(restored)
        .lesson.to_payload()
        == lesson.to_payload()
    )
    restored_lesson = lesson_ir_from_payload(lesson.to_payload())
    assert (
        VisualStepBuilder()
        .build(snapshot=restored, lesson=restored_lesson)
        .to_payload()
        == visual.to_payload()
    )
    assert (
        visual_step_ir_from_payload(visual.to_payload()).to_payload()
        == visual.to_payload()
    )
    compiled = forward_compile(visual)
    expected_section = {
        "q03": "配齐次式",
        "q07": "多次应用基本不等式",
        "q08": "整理后应用基本不等式",
    }[case]
    assert {s.section_label for s in lesson.steps} == {expected_section}
    assert {s["section"] for s in compiled.lesson_data["steps"]} == {expected_section}
    compiled.lesson_data["meta"].update(
        id=f"generated-{case}", generatedFromSolver=True
    )
    compiled.lesson_data["problem"]["answerText"] = snapshot.answers["problem"][
        "minimum"
    ]
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
    assert "lesson-page-runtime.js" in (tmp_path / "lesson.html").read_text()


@pytest.mark.parametrize("mutation", ["owner", "predecessor", "applications"])
def test_sequence_rule_requires_actual_bound_dependency(snapshots, mutation):
    snapshot = snapshots["q07"]
    evidence = deepcopy(dict(snapshot.evidence))
    d = next(
        v["data"]
        for v in evidence.values()
        if v.get("step_id") == "bound"
        and v.get("schema_version") == "inequality-teaching-evidence/v1"
    )
    if mutation == "owner":
        d["target_hash"] = "different-target"
    elif mutation == "predecessor":
        d["previous_bound"] = None
    else:
        d["applications"] = []
    altered = replace(snapshot, evidence=evidence)
    projection = AnnotatedTeachingPlanProjector().project(snapshot)
    result = sequence_rule_registry().apply(projection, altered)
    assert len(result.authority["containers"]["goal:problem.minimum"]) == 5


def test_sequence_visual_requires_both_source_owners(snapshots):
    with pytest.raises(VisualGap, match="outside_step_sources"):
        default_visual_specs().bind(
            [
                {
                    "spec_id": "basic_inequality.amgm_sequence_overview",
                    "roles": {"evidence": ["first", "bound"]},
                }
            ],
            snapshot=snapshots["q07"],
            source_step_ids=("first",),
        )


def test_rewrite_public_evidence_roundtrip_and_tamper(snapshots):
    payload = next(
        v
        for v in snapshots["q03"].evidence.values()
        if v.get("schema_version") == "expression-rewrite-teaching-evidence/v1"
    )
    assert RewriteTeachingEvidence.from_payload(payload).to_payload() == payload
    assert "proofs" not in json.dumps(payload)
    corrupt = deepcopy(payload)
    corrupt["data"]["result"]["latex"] = "999"
    with pytest.raises(ValueError, match="hash mismatch"):
        RewriteTeachingEvidence.from_payload(corrupt)


def test_minimum_prose_cannot_claim_upper_bound(snapshots):
    from shuxueshuo_server.solver.explanation.scope_lesson import (
        LessonScopeContentValidator,
    )

    projection = AnnotatedTeachingPlanProjector(
        rule_registry=sequence_rule_registry()
    ).project(snapshots["q08"])
    validator = LessonScopeContentValidator(
        plan=projection.plan, authority=projection.authority
    )
    bad = deepcopy(validator.deterministic_fallback)
    bad["problem"]["goals"]["problem.minimum"][2]["goal"] = (
        "由基本不等式得到原式的上界，原式不超过4"
    )
    result = validator.validate_payload(bad)
    assert result.fallback_used
    assert any(
        d.code == "lesson_scope_bound_direction_conflict" for d in result.diagnostics
    )
    assert "上界" not in json.dumps(result.accepted_content, ensure_ascii=False)


@pytest.mark.parametrize("case", ["q03", "q07", "q08"])
def test_lower_bounds_use_full_amgm_mapping(case, snapshots):
    lesson = (
        LessonAuthoringPipeline(rule_registry=sequence_rule_registry())
        .build(snapshots[case])
        .lesson
    )
    visual = VisualStepBuilder().build(snapshot=snapshots[case], lesson=lesson)
    applications = [
        b["data"]
        for s in visual.steps
        for b in s.diagram_blocks
        if b["component_id"] == "basic-inequality-mapping"
    ]
    assert len(applications) == (2 if case == "q07" else 1)
    for data in applications:
        assert data["formulaStyle"] == "sum-geometric"
        assert data["showPositiveStep"] is True
        if "fixedCondition" in data:
            assert data["fixedSourceTarget"] == "product"
            assert data["mappedProduct"] in {r"\(4\)", r"\(2\)"}
            assert data["replaced"]
        else:
            assert data["mappedProduct"].count(r"\left(") == 2
            assert data["mappedProduct"].count(r"\right)") == 2
        assert [m["shape"] for m in data["mappings"]] == ["square", "circle"]
        assert all(m["value"] and m["condition"] for m in data["mappings"])


@pytest.mark.parametrize("names, coefficient", [("x y", 4), ("u v", 9)])
def test_homogenization_is_structural_not_question_specific(names, coefficient):
    import sympy as sp

    from shuxueshuo_server.solver.explanation.homogenization import recognized
    from shuxueshuo_server.solver.math_kernel.expression_rewrite import verify_chain

    a, b = names.split()
    symbols = {n: sp.Symbol(n, real=True) for n in (a, b)}
    source = f"{a}+{coefficient}*{b}"
    condition = f"1/{a}+1/{b}=1"
    steps = [
        {"math": source},
        {"math": f"({source})*(1/{a}+1/{b})", "using": [condition]},
        {"math": f"{coefficient + 1}+{a}/{b}+{coefficient}*{b}/{a}"},
    ]
    trace = verify_chain(
        symbols[a] + coefficient * symbols[b],
        [f"{a}>0", f"{b}>0", condition],
        steps,
        symbols,
    )
    transition = recognized(trace)
    assert transition["homogenization"]["originalDegree"] == 1
    assert transition["homogenization"]["conditionDegree"] == -1
    assert transition["homogenization"]["factor"]["nodeId"]
    assert recognized({**trace, "transitions": trace["transitions"][1:]}) is None


def test_homogeneous_degree_rejects_mixed_sum_and_does_not_classify_plain_rewrite(
    snapshots,
):
    import sympy as sp

    from shuxueshuo_server.solver.explanation.homogenization import recognized
    from shuxueshuo_server.solver.math_kernel.expression_rewrite import (
        homogeneous_degree,
        parse_expression,
    )

    symbols = {"z": sp.Symbol("z", real=True)}
    assert homogeneous_degree(parse_expression("z+1", symbols).tree) is None
    trace = next(
        v["data"]
        for v in snapshots["q08"].evidence.values()
        if v.get("schema_version") == "expression-rewrite-teaching-evidence/v1"
    )
    assert recognized(trace) is None


def test_homogenization_does_not_merge_an_unrelated_bound(snapshots):
    registry = sequence_rule_registry()
    original = registry.rules["basic_inequality.homogenization"]

    def unrelated(container, materials, evidence):
        materials = tuple(replace(r, resolved_inputs={}) for r in materials)
        return original(container, materials, evidence)

    registry.rules["basic_inequality.homogenization"] = unrelated
    built = LessonAuthoringPipeline(rule_registry=registry).build(snapshots["q03"])
    assert len(built.lesson.steps) == 5


def test_homogenization_visual_uses_bound_pair_and_constant_product(snapshots):
    snapshot = snapshots["q03"]
    lesson = (
        LessonAuthoringPipeline(rule_registry=sequence_rule_registry())
        .build(snapshot)
        .lesson
    )
    visual = VisualStepBuilder().build(snapshot=snapshot, lesson=lesson)
    block = visual.steps[1].diagram_blocks[0]
    assert block["source_step_ids"] == ["rewrite", "bound"]
    assert len(block["evidence_refs"]) == 2
    d = block["data"]
    assert d["pattern"]["condition"]["tag"] == r"定积 \(4\)"
    assert d["pattern"]["target"]["tag"] == "求最小值"
    assert d["pattern"]["first"]["value"] == r"\(\frac{x}{y}\)"
    assert d["reading"] == "定积求和"
    assert d["organization"]["steps"][1]["expression"].startswith(r"\(x+4\cdot y=")


def test_fixed_homogenization_title_survives_llm_rewording(snapshots):
    from shuxueshuo_server.solver.explanation.lesson_ir import (
        RecursiveLessonIRAssembler,
    )
    from shuxueshuo_server.solver.explanation.scope_lesson import (
        LessonScopeContentValidator,
    )

    snapshot = snapshots["q03"]
    projection = AnnotatedTeachingPlanProjector(
        rule_registry=sequence_rule_registry()
    ).project(snapshot)
    validator = LessonScopeContentValidator(
        plan=projection.plan, authority=projection.authority
    )
    payload = deepcopy(validator.deterministic_fallback)
    payload["problem"]["goals"]["problem.minimum"][1]["title"] = (
        "乘入条件式并展开，整理原式"
    )
    validation = validator.validate_payload(payload)
    assert not validation.fallback_used
    lesson = (
        RecursiveLessonIRAssembler().assemble(snapshot, projection, validation).lesson
    )
    assert lesson.steps[1].title == "配齐次式"


def test_purpose_titles_and_navigation_survive_llm_rewording(snapshots):
    from shuxueshuo_server.solver.explanation.lesson_ir import (
        RecursiveLessonIRAssembler,
    )
    from shuxueshuo_server.solver.explanation.scope_lesson import (
        LessonScopeContentValidator,
    )

    snapshot = snapshots["q07"]
    projection = AnnotatedTeachingPlanProjector(
        rule_registry=sequence_rule_registry()
    ).project(snapshot)
    validator = LessonScopeContentValidator(
        plan=projection.plan, authority=projection.authority
    )
    payload = deepcopy(validator.deterministic_fallback)
    for step in payload["problem"]["goals"]["problem.minimum"][:3]:
        step.update(title="配对求下界", nav_title="求界")
    validation = validator.validate_payload(payload)
    assert not validation.fallback_used
    lesson = (
        RecursiveLessonIRAssembler().assemble(snapshot, projection, validation).lesson
    )
    assert lesson.steps[1].title == "应用基本不等式消元"
    assert lesson.steps[1].nav_title == "应用基本不等式消元"
    assert lesson.steps[2].title == "再次应用基本不等式取极值"
    assert lesson.steps[2].nav_title == "再次应用基本不等式取极值"


@pytest.mark.parametrize(
    "source,result,kind,removed",
    [
        ("u+v+w", "v+w", "eliminate_variable", ["u"]),
        ("v+w", "w", "eliminate_variable", ["v"]),
        ("w", "2", "constant_bound", ["w"]),
        ("u+v", "u+w", "bound", ["v"]),
        ("xy+u", "xy", "eliminate_variable", ["u"]),
        ("0*u+v", "v", "bound", []),
    ],
)
def test_bound_purpose_uses_variable_effect_not_problem_or_variable_count(
    source, result, kind, removed
):
    import sympy as sp

    from shuxueshuo_server.solver.explanation.bound_purpose import verified_bound_effect

    symbols = {name: sp.Symbol(name) for name in ("u", "v", "w", "xy")}
    effect = verified_bound_effect(source, result, symbols)
    assert effect["kind"] == kind
    assert effect["removed_symbols"] == removed


def test_sequence_rule_rejects_different_resolved_predecessor(snapshots):
    registry = sequence_rule_registry()
    original = registry.rules["basic_inequality.amgm_sequence_overview"]

    def unrelated(container, materials, evidence):
        altered = []
        for row in materials:
            inputs = deepcopy(row.resolved_inputs)
            if inputs and inputs.get("previous_bound"):
                inputs["previous_bound"][0]["ref"]["step_id"] = "other-call"
            altered.append(replace(row, resolved_inputs=inputs))
        return original(container, tuple(altered), evidence)

    registry.rules["basic_inequality.amgm_sequence_overview"] = unrelated
    built = LessonAuthoringPipeline(rule_registry=registry).build(snapshots["q07"])
    assert len(built.lesson.steps) == 5


def test_later_label_rule_cannot_remove_independence_of_composed_units(snapshots):
    registry = sequence_rule_registry()

    def remove_boundary(container, materials, evidence):
        return tuple(
            replace(
                r, authority={**r.authority, "requires_independent_lesson_step": False}
            )
            if len(r.covers) > 1
            else r
            for r in materials
        )

    registry.register("test.bad_label", remove_boundary)
    with pytest.raises(ValueError, match="independent_boundary_removed"):
        LessonAuthoringPipeline(rule_registry=registry).build(snapshots["q07"])


def test_relation_planning_supports_existing_conditions_and_more_variables():
    from shuxueshuo_server.solver.explanation.bound_purpose import relation_count_plan

    data = {
        "teaching_effect": {"input_symbols": ["u", "v", "w"]},
        "condition_equations_latex": ["u+v+w=3"],
        "applications": [{"equality": "u=v"}, {"equality": "v=w"}],
    }
    hint = relation_count_plan([data])
    assert [hint[k]["value"] for k in ("variable", "condition", "result")] == [
        "3",
        "1",
        "2",
    ]
    assert hint["variable"]["detail"] == "u、v、w"
    assert hint["condition"]["detail"] == r"\(u+v+w=3\)"


@pytest.mark.parametrize("equalities", [["u=v"], ["u=v", "2*v=2*u"], ["u=u", "v=1"]])
def test_planning_never_uses_variable_count_as_application_count(equalities):
    from shuxueshuo_server.solver.explanation.bound_purpose import relation_count_plan

    assert (
        relation_count_plan(
            [
                {
                    "teaching_effect": {"input_symbols": ["u", "v"]},
                    "condition_equations_latex": [],
                    "applications": [{"equality": e} for e in equalities],
                }
            ]
        )
        is None
    )


@pytest.mark.parametrize(
    "source, expected",
    [
        ("由 x/y 与 4y/x 配对", r"由 \(\frac{x}{y}\) 与 \(\frac{4\cdot y}{x}\) 配对"),
        ("1/(x+y)", r"\(\frac{1}{x+y}\)"),
        ("x/y+1=2", r"\(\frac{x}{y}+1=2\)"),
        (r"\(x/y≥1\)", r"\(\frac{x}{y}≥1\)"),
        (r"\(x/y\geq 1\)", r"\(\frac{x}{y}≥1\)"),
        (r"\(x/y\le 1\)", r"\(\frac{x}{y}≤1\)"),
        (r"\(x/y\neq 0\)", r"\(\frac{x}{y}≠0\)"),
        (r"\(\frac{x}{y}\geq 1\)", r"\(\frac{x}{y}\geq 1\)"),
        (r"\(x/y\geqword\)", r"\(x/y\geqword\)"),
        (
            r"\\(1/(2a)+1/(2b)+8/(a+b) \\geq 4\\)",
            r"\(\frac{1}{2\cdot a}+\frac{1}{2\cdot b}+\frac{8}{a+b}≥4\)",
        ),
        (r"\(\frac{x}{y}\)", r"\(\frac{x}{y}\)"),
        ("x/xy", r"\(\frac{x}{xy}\)"),
        ("x/y/z", r"\(\frac{\frac{x}{y}}{z}\)"),
        ("https://example.com/x/y", "https://example.com/x/y"),
    ],
)
def test_fraction_typography_preserves_grouping_and_existing_tex(source, expected):
    from shuxueshuo_server.solver.explanation.math_typography import fraction_prose

    assert fraction_prose(source) == expected
    assert fraction_prose(expected) == expected


def test_fraction_formatting_covers_prose_without_changing_identifiers():
    from shuxueshuo_server.solver.explanation.math_typography import typeset_lesson_data

    data = {
        "problem": {
            "lines": [{"text": "已知 1/x+1/y=1"}],
            "keyPoints": {"items": ["考虑 x/y"]},
        },
        "steps": [
            {
                "id": "method/x/y",
                "title": "估计 x/y",
                "derive": [["∴", "x/y≥1"]],
                "visual": {"spec_id": "method/x/y", "relations": [r"\(x/y≥1\)"]},
            }
        ],
    }
    result = typeset_lesson_data(data)
    assert result["steps"][0]["id"] == data["steps"][0]["id"]
    assert result["steps"][0]["visual"]["spec_id"] == "method/x/y"
    for text in (
        result["problem"]["lines"][0]["text"],
        result["problem"]["keyPoints"]["items"][0],
        result["steps"][0]["title"],
        result["steps"][0]["derive"][0][1],
        result["steps"][0]["visual"]["relations"][0],
    ):
        assert r"\frac{" in text


def test_fraction_typography_handles_math_lists_and_double_escaped_tex():
    from shuxueshuo_server.solver.explanation.math_typography import fraction_prose

    assert fraction_prose(r"\(x=3，y=3/2\)") == r"\(x=3，y=\frac{3}{2}\)"
    assert fraction_prose(r"\\(\\frac{x}{y}\\)") == r"\(\frac{x}{y}\)"


def test_q03_semantic_stages_and_conditional_equation_solution(snapshots):
    snapshot = snapshots["q03"]
    lesson = (
        LessonAuthoringPipeline(rule_registry=sequence_rule_registry())
        .build(snapshot)
        .lesson
    )
    visual = VisualStepBuilder().build(snapshot=snapshot, lesson=lesson)
    application = visual.steps[2].diagram_blocks[0]["data"]
    assert application["stageLabel"] == "代入定积"
    assert application["mappedProduct"] == r"\(4\)"
    assert r"5+4" in application["substituted"]
    equality = visual.steps[3].diagram_blocks[0]["data"]
    assert "equalityRelations" not in equality
    assert equality["solvedLabel"] == "联立求得"
    assert r"\frac{1}{x}+\frac{1}{y}=1" in equality["condition"]
    assert r"\frac{x}{y}" in equality["first"]["value"]
    text = json.dumps(lesson.to_payload(), ensure_ascii=False)
    assert "设取" not in text
    assert "下界" in text
    assert "便于估计" not in text
    # Absence of a solving proof must retain a truthful witness-only layout.
    from shuxueshuo_server.solver.visual.teaching_diagrams import lower_equality

    data = next(
        v["data"]
        for v in snapshot.evidence.values()
        if v.get("method_id") == "close_equality_and_restore"
    )
    fallback = lower_equality({**data, "equality_derivation": []})
    assert fallback["solvedLabel"] == "可取的具体值"
    assert fallback["equalityRelations"]


@pytest.mark.parametrize("case", ["q07", "q08"])
def test_generated_equality_components_use_verified_solving_evidence(case, snapshots):
    snapshot = snapshots[case]
    lesson = (
        LessonAuthoringPipeline(rule_registry=sequence_rule_registry())
        .build(snapshot)
        .lesson
    )
    visual = VisualStepBuilder().build(snapshot=snapshot, lesson=lesson)
    data = visual.steps[-1].diagram_blocks[0]["data"]
    assert "equalityRelations" not in data
    assert "设取" not in json.dumps(lesson.to_payload(), ensure_ascii=False)
    if case == "q07":
        assert len(data["equalities"]) == 2
        assert data["equalities"][0]["result"] == r"\(a=b\)"
        assert data["equalities"][1]["result"] == r"\(b=\sqrt{2}\)"
    else:
        assert len(data["solutionBranches"]) == 2
        assert data["solutionBranches"][0]["when"] == r"\(a-2\geq 0\)"
        assert data["solutionBranches"][1]["when"] == r"\(a-2\leq 0\)"
        assert (
            data["solutionBranches"][0]["result"]
            != data["solutionBranches"][1]["result"]
        )
        assert r"\frac{a+b}{2}" in data["first"]["value"]
    assert '"proof":' not in json.dumps(snapshot.evidence, ensure_ascii=False)


def test_compound_terms_keep_grouping_in_amgm_teaching_projection(snapshots):
    data = next(
        v["data"]
        for v in snapshots["q08"].evidence.values()
        if v.get("method_id") == "apply_two_term_amgm"
    )
    assert (
        data["constant_product_roles"]["product_identity"]
        == r"\frac{a+b}{2}\cdot \frac{8}{a+b}=4"
    )
    assert (
        data["constant_product_roles"]["local_bound"]
        == r"\frac{a+b}{2}+\frac{8}{a+b}\geq 4"
    )
    from shuxueshuo_server.solver.explanation.math_typography import fraction_prose

    assert "{b}" not in fraction_prose("a/b^2")
    assert r"\left(a-2\right)^{2}" in fraction_prose("(a-2)^2/3")


def _project_verified_inequality(method_id, target, evidence):
    from shuxueshuo_server.solver.runtime.inequality_teaching_evidence import (
        collect_inequality_evidence,
    )

    return collect_inequality_evidence("test-call", [SimpleNamespace(
        method_id=method_id,
        trace_fragments=[{"source_target": target, "evidence": evidence}],
    )])[0]


def _validate_equality_visual(evidence):
    from shuxueshuo_server.solver.visual.teaching_diagrams import (
        lower_equality,
        validate_diagram_block,
    )

    data = lower_equality(evidence.data)
    block = {
        "spec_id": "basic_inequality.equality", "spec_version": 1,
        "visual_kind": "teaching_diagram",
        "component_id": "basic-inequality-equality-check", "component_version": 1,
        "source_step_ids": [evidence.step_id], "evidence_refs": [evidence.evidence_id],
        "data": data,
    }
    validate_diagram_block(json.loads(json.dumps(block)))
    return data


def test_single_equality_solution_without_original_equation_keeps_sign_condition():
    from test_basic_inequality_stage4_expansion import rows, target

    from shuxueshuo_server.solver.math_kernel.inequality_evidence import (
        close_bound,
        public_bound,
        verify_bound,
    )

    t = target("u+4/u", ("u>0",), ("u",))
    bound = public_bound(verify_bound(t, rows("u+4/u>=4")))
    value, evidence = close_bound(t, bound, rows("u=2"), equality_derivation=[
        {"math": "u^2=4", "using": ["u=4/u"]},
        {"math": "u=2", "using": ["u^2=4"]},
    ])
    assert value == 4
    public = _project_verified_inequality("close_equality_and_restore", t, evidence)
    assert public.data["condition_equations_latex"] == []
    data = _validate_equality_visual(public)
    assert data["condition"] == r"\(u > 0\)"
    assert data["solvedLabel"] == "联立求得"
    assert data["solved"] == r"\(u=2\)"


def test_three_certified_applications_use_actual_equality_count():
    from test_basic_inequality_stage4_expansion import rows, target

    from shuxueshuo_server.solver.math_kernel.inequality_evidence import (
        close_bound,
        public_bound,
        verify_bound,
    )

    t = target("x+1/x+y+1/y+z+1/z", ("x>0", "y>0", "z>0"), ("x", "y", "z"))
    bound = public_bound(verify_bound(t, rows("x+1/x+y+1/y+z+1/z>=2+y+1/y+z+1/z")))
    for statement in ("2+y+1/y+z+1/z>=4+z+1/z", "4+z+1/z>=6"):
        bound = public_bound(verify_bound(t, rows(statement), previous_bound=bound))
    derivation = [row for var in ("x", "y", "z") for row in (
        {"math": f"{var}^2=1", "using": [f"{var}=1/{var}"]},
        {"math": f"{var}=1", "using": [f"{var}^2=1"]},
    )]
    value, evidence = close_bound(t, bound, rows("x=y=z=1"), equality_derivation=derivation)
    assert value == 6
    data = _validate_equality_visual(
        _project_verified_inequality("close_equality_and_restore", t, evidence)
    )
    assert data["templateLabel"] == "3次基本不等式同时取等"
    assert len(data["equalities"]) == 3
    assert data["equalities"][-1]["label"] == "第3次取等"


def test_structure_does_not_mislabel_equations_as_positivity():
    from test_basic_inequality_stage4_expansion import rows, target

    from shuxueshuo_server.solver.math_kernel.inequality_evidence import (
        verify_bound,
    )
    from shuxueshuo_server.solver.visual.teaching_diagrams import lower_structure

    t = target("x+y", ("x>0", "y>0", "x*y=4"), ("x", "y"))
    bound = verify_bound(t, rows("x+y>=2*sqrt(x*y)", "x+y>=4"))
    public = _project_verified_inequality("apply_two_term_amgm", t, bound)
    data = lower_structure(public.data)
    assert "= 4" in data["condition"]["expression"]
    assert data["condition"]["tag"] == "已知条件"


@pytest.mark.parametrize(
    "mutation", ["unrelated", "target", "gap", "duplicate", "missing_expression"]
)
def test_fraction_rule_requires_adjacent_unique_committed_dependency(
    snapshots, mutation
):
    from shuxueshuo_server.solver.explanation.fraction_observation import RULE_ID

    registry = sequence_rule_registry()
    composer = registry.rules[RULE_ID]

    def changed(container, materials, evidence):
        items = list(materials)
        index = next(
            i for i, r in enumerate(items) if r.authority["unit_key"] == "amgm_observe"
        )
        row = items[index]
        inputs = deepcopy(row.resolved_inputs)
        if mutation == "unrelated":
            inputs["expression"][0]["resolved_from"]["step_id"] = "other-rewrite"
        elif mutation == "target":
            inputs["target"][0]["value"]["expression_owner"] = "other-target"
        elif mutation == "missing_expression":
            inputs.pop("expression")
        elif mutation == "gap":
            items[index], items[index + 1] = items[index + 1], items[index]
            assert composer(container, tuple(items), evidence) == tuple(items)
            return materials
        elif mutation == "duplicate":
            items.append(row)
            assert composer(container, tuple(items), evidence) == tuple(items)
            return materials
        items[index] = replace(row, resolved_inputs=inputs)
        assert composer(container, tuple(items), evidence) == tuple(items)
        return materials

    registry.rules[RULE_ID] = changed
    lesson = (
        LessonAuthoringPipeline(rule_registry=registry).build(snapshots["q08"]).lesson
    )
    assert len(lesson.steps) == 4


@pytest.mark.parametrize(
    "mutation",
    [
        "no_substitution",
        "pair_mismatch",
        "no_product",
        "broken_chain",
        "second_combine",
    ],
)
def test_fraction_rule_preserves_steps_when_semantic_evidence_is_incomplete(
    snapshots, mutation
):
    snapshot = snapshots["q08"]
    evidence = deepcopy(dict(snapshot.evidence))
    trace = next(v["data"] for v in evidence.values() if v.get("step_id") == "rewrite")
    pair = next(v["data"] for v in evidence.values() if v.get("step_id") == "bound")
    if mutation == "no_substitution":
        trace["transitions"][1]["conditionCardIds"] = []
    elif mutation == "pair_mismatch":
        pair["applications"][0]["terms"] = ["a", "b"]
    elif mutation == "no_product":
        pair.pop("constant_product_roles")
    elif mutation == "broken_chain":
        trace["transitions"][1]["before"] = trace["source"]
    else:
        trace["transitions"].append(deepcopy(trace["transitions"][0]))
    projection = AnnotatedTeachingPlanProjector().project(snapshot)
    result = sequence_rule_registry().apply(
        projection, replace(snapshot, evidence=evidence)
    )
    assert len(result.authority["containers"]["goal:problem.minimum"]) == 4


@pytest.mark.parametrize("names,coefficient,constant", [("a b", 2, 1), ("u v", 3, 2)])
def test_fraction_observation_generalizes_verified_rewrite_and_pair(
    names, coefficient, constant
):
    import sympy as sp
    from test_basic_inequality_stage4_expansion import target

    from shuxueshuo_server.solver.explanation.fraction_observation import (
        observation_visual,
        recognized,
    )
    from shuxueshuo_server.solver.math_kernel.expression_rewrite import verify_chain
    from shuxueshuo_server.solver.math_kernel.inequality_evidence import verify_bound

    a, b = names.split()
    c, k = coefficient, constant
    symbols = {n: sp.Symbol(n, real=True) for n in (a, b)}
    source = f"1/({c}*{a})+1/({c}*{b})+{4 * c * k}/({a}+{b})"
    final = f"({a}+{b})/{c * k}+{4 * c * k}/({a}+{b})"
    condition = f"{a}*{b}={k}"
    from shuxueshuo_server.solver.math_kernel.expression_parser import (
        parse_math_expression,
    )

    trace = verify_chain(
        parse_math_expression(source, symbols).to_sympy(symbols),
        [f"{a}>0", f"{b}>0", condition],
        [
            {"math": source},
            {"math": f"({a}+{b})/({c}*{a}*{b})+{4 * c * k}/({a}+{b})"},
            {"math": final, "using": [condition]},
        ],
        symbols,
        input_source=source,
    )
    bound = verify_bound(
        target(final, (f"{a}>0", f"{b}>0"), (a, b)), [{"math": final + ">=4"}]
    )
    pair = {
        "direction": ">=",
        "applications": bound["applications"],
        "term_latex": [
            rf"\frac{{{a}+{b}}}{{{c * k}}}",
            rf"\frac{{{4 * c * k}}}{{{a}+{b}}}",
        ],
        "constant_product_roles": {"product": "4"},
    }
    assert recognized(trace, pair)
    # Term order and question identity do not participate in recognition.
    pair["applications"][0]["terms"].reverse()
    assert recognized(trace, pair)
    diagram = observation_visual([trace, pair])
    assert len(diagram["organization"]["combineHint"]["terms"]) == 2
    assert names.split()[0] in diagram["organization"]["combineHint"]["terms"][0]
    assert diagram["pattern"]["condition"]["tag"] == r"定积 \(4\)"


def test_fraction_combination_keeps_coverage_and_independent_application(snapshots):
    from shuxueshuo_server.solver.explanation.fraction_observation import VISUAL_ID

    snapshot = replace(snapshots["q08"], problem_id="renamed-without-question-number")
    built = LessonAuthoringPipeline(rule_registry=sequence_rule_registry()).build(
        snapshot
    )
    records = built.projection.authority["containers"]["goal:problem.minimum"]
    assert [r["unit_key"] for r in records] == [
        "fraction_observation",
        "amgm_apply",
        "equality_verify",
    ]
    assert all(r["requires_independent_lesson_step"] for r in records)
    block = (
        VisualStepBuilder()
        .build(snapshot=snapshot, lesson=built.lesson)
        .steps[0]
        .diagram_blocks[0]
    )
    assert block["spec_id"] == VISUAL_ID
    assert block["source_step_ids"] == ["rewrite", "bound"]
    assert len(block["evidence_refs"]) == 2
    assert len(block["data"]["organization"]["steps"]) == 3
    with pytest.raises(VisualGap, match="outside_step_sources"):
        default_visual_specs().bind(
            built.lesson.steps[0].visuals,
            snapshot=snapshot,
            source_step_ids=("rewrite",),
        )
