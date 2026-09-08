from __future__ import annotations

import inspect
import json
from pathlib import Path
import tempfile

import pytest

from shuxueshuo_server.solver.extraction.problem_domain_smoke import (
    DEFAULT_F2_INPUT,
    _repo_root,
    _resolve_repo_path,
)
from shuxueshuo_server.solver.lesson_annotated_teaching_review import (
    REVIEW_SCHEMA,
    build_annotated_teaching_review,
    main,
    render_annotated_teaching_review_html,
)
from shuxueshuo_server.solver.lesson_authoring_support import (
    CASE_ID,
    build_recorded_snapshot,
    load_teaching_rubric,
)


ROOT = Path(__file__).resolve().parents[3]
B0 = (
    ROOT
    / "server/tests/solver/fixtures/lesson_scope_authoring_vnext/"
    "heping_ermo_b0"
)
B2 = (
    ROOT
    / "server/tests/solver/fixtures/lesson_scope_authoring_vnext/"
    "heping_ermo_b2"
)


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def snapshot_and_artifacts():
    root = _repo_root()
    with tempfile.TemporaryDirectory(prefix="lesson-b2-test-authority-") as temp_dir:
        snapshot = build_recorded_snapshot(
            CASE_ID,
            authority_dir=Path(temp_dir),
            f2_root=_resolve_repo_path(root, DEFAULT_F2_INPUT),
        )
    artifacts = build_annotated_teaching_review(
        snapshot,
        rubric=load_teaching_rubric(B0 / "rubric.json"),
    )
    return snapshot, artifacts


def test_b2_review_has_complete_scope_owned_materials(snapshot_and_artifacts) -> None:
    _snapshot, artifacts = snapshot_and_artifacts
    review = artifacts.review
    summary = review["summary"]

    assert review["schema_version"] == REVIEW_SCHEMA
    assert summary["scope_count"] == 5
    assert summary["goal_count"] == 4
    assert summary["step_count"] == 12
    assert summary["teaching_material_count"] == 13
    assert summary["verified_answer_count"] == 4
    assert summary["review_status"] == "awaiting_human_review"
    assert summary["rubric_coverage"]["coverage_rate"] == 1.0
    assert summary["rubric_coverage"]["missing"] == []
    assert len(review["cards"]) == 12

    macro = next(
        card
        for card in review["cards"]
        if card["step_id"] == "derive_path_minimum_ii"
    )
    assert macro["owner"] == {"scope_ref": "ii", "goal_ref": "ii.E"}
    assert macro["material_count"] == 2
    assert macro["inputs"]
    assert macro["execution"]["outputs"]
    assert macro["execution"]["calculations"]
    assert "checks" not in macro["execution"]


def test_b2_answers_are_reviewed_against_answer_from(snapshot_and_artifacts) -> None:
    _snapshot, artifacts = snapshot_and_artifacts
    rows = artifacts.review["answers"]

    assert [item["goal_ref"] for item in rows] == [
        "i_1.A",
        "i_1.P",
        "i_2.E",
        "ii.E",
    ]
    assert all(item["answer_from"] for item in rows)
    assert all(item["verified_answer"]["display"] for item in rows)
    assert all(
        item["required_answer"]["runtime_type"]
        == item["verified_answer"]["type"]
        for item in rows
    )


def test_b2_prompt_and_audit_are_ready_for_manual_review(snapshot_and_artifacts) -> None:
    _snapshot, artifacts = snapshot_and_artifacts
    audit = artifacts.audit

    assert audit["status"] == "ready_for_human_review"
    assert audit["projection_diagnostics"] == []
    assert audit["forbidden_hits"] == {
        "annotated_plan": [],
        "prompt": [],
    }
    assert audit["prompt_chars"]["smaller_than_b0"] is True
    assert audit["llm_invoked"] is False
    assert "## Annotated Teaching Plan" in artifacts.prompt.user
    assert "## 输出 JSON Schema" in artifacts.prompt.user
    assert "## 全题型共享示例" in artifacts.prompt.user
    assert "你不需要返回 conclusions 或 box" in artifacts.prompt.system
    assert "不得自行新增代入、化简、方程、坐标计算或数值运算" in artifacts.prompt.system
    assert "学生步骤的边界应对应一次需要理解的新数学思考" in artifacts.prompt.system
    assert "而不是一次代码调用" in artifacts.prompt.system
    assert "不需要新的选择或理由" in artifacts.prompt.system
    assert "而不是压缩数学内容" in artifacts.prompt.system
    assert "每个输出步骤用 source_steps" in artifacts.prompt.system
    assert "root_scope 仅按真实父子关系递归展示上下文" in artifacts.prompt.system
    assert "child Scope 或 sibling Scope 的结果绝不能提前写回" in artifacts.prompt.system
    assert '"source_steps":["s1","s2","s3"]' in artifacts.prompt.user
    assert "material_count" not in artifacts.prompt.system
    assert "## 必须独立的教学材料" in artifacts.prompt.user
    assert 'Goal i_2.E：必须分别输出 ["s1"]、["s2"]、["s3"]' in artifacts.prompt.user
    assert 'Goal ii.E：必须分别输出 ["s2"]、["s3"]、["s7"]' in artifacts.prompt.user
    assert "## 可考虑合并的连续材料" in artifacts.prompt.user
    assert 'Goal ii.E：["s4","s5","s6"]' in artifacts.prompt.user


def test_b2_review_html_is_self_contained_and_exposes_raw_prompt_tabs(
    snapshot_and_artifacts,
) -> None:
    _snapshot, artifacts = snapshot_and_artifacts
    html = render_annotated_teaching_review_html(artifacts)

    assert html.count('<article class="card"') == 12
    for label in (
        "Exact Inputs",
        "Verified Execution",
        "LLM-facing Teaching Materials",
        "Raw Plan",
        "Actual Prompt",
        "Schema / Audit",
    ):
        assert label in html
    assert "step-derive_path_minimum_ii" in html
    assert "<script src=" not in html
    assert "<link rel=" not in html


def test_b2_plan_schema_and_human_approved_boundary_prompt_are_stable(
    snapshot_and_artifacts,
) -> None:
    _snapshot, artifacts = snapshot_and_artifacts

    assert artifacts.projection.plan.to_payload() == _json(
        B2 / "annotated-teaching-plan.json"
    )
    assert artifacts.output_schema == _json(B2 / "output-schema.json")
    previous_audit = _json(B2 / "projection-audit.json")
    assert artifacts.audit["hashes"]["annotated_plan"] == previous_audit["hashes"][
        "annotated_plan"
    ]
    assert artifacts.audit["hashes"]["output_schema"] == previous_audit["hashes"][
        "output_schema"
    ]
    assert artifacts.audit["hashes"]["prompt"] == previous_audit["hashes"]["prompt"]
    assert artifacts.audit["independent_step_refs"] == {
        "goal:i_2.E": ["s1", "s2", "s3"],
        "goal:ii.E": ["s2", "s3", "s7"],
    }
    assert artifacts.prompt.system + "\n" == (B2 / "prompt.system.md").read_text(
        encoding="utf-8"
    )
    assert artifacts.prompt.user + "\n" == (B2 / "prompt.user.md").read_text(
        encoding="utf-8"
    )


def test_b2_builder_has_no_lesson_llm_dependency() -> None:
    import shuxueshuo_server.solver.lesson_annotated_teaching_review as module

    source = inspect.getsource(module)
    assert "LLMLessonPlanner" not in source
    assert ".complete(" not in source


def test_b2_cli_writes_create_once_auditable_artifacts(tmp_path: Path) -> None:
    args = [
        "--case",
        CASE_ID,
        "--batch-id",
        "b2-review-test",
        "--output-root",
        str(tmp_path),
    ]
    assert main(args) == 0
    output = tmp_path / "b2-review-test"
    assert {item.name for item in output.iterdir()} == {
        "sample-01",
        "review.json",
        "review.html",
    }
    assert {item.name for item in (output / "sample-01").iterdir()} == {
        "snapshot.json",
        "teaching-authority.json",
        "annotated-teaching-plan.json",
        "output-schema.json",
        "prompt.system.md",
        "prompt.user.md",
        "projection-audit.json",
    }
    with pytest.raises(Exception, match="output_exists"):
        main(args)
