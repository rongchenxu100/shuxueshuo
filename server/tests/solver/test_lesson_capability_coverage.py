from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from shuxueshuo_server.solver.explanation.models import iter_teaching_sources
from shuxueshuo_server.solver.explanation.teaching_specs import TeachingSpecBinder
from shuxueshuo_server.solver.extraction.problem_domain_smoke import (
    DEFAULT_F2_INPUT,
    _repo_root,
    _resolve_repo_path,
)
from shuxueshuo_server.solver.lesson_authoring_support import build_recorded_snapshot
from shuxueshuo_server.solver.lesson_capability_coverage import (
    build_lesson_capability_coverage,
    discover_public_lesson_capabilities,
)
from shuxueshuo_server.solver.lesson_capability_coverage_review import (
    RECORDED_CASE_IDS,
    build_capability_coverage_review,
    capability_coverage_fixture_payloads,
)
from shuxueshuo_server.solver.lesson_capability_synthetic import (
    build_synthetic_capability_scenarios,
)
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.recipes import RecipeSpecRegistry


FIXTURE_ROOT = (
    Path(__file__).resolve().parent
    / "fixtures/lesson_scope_authoring_vnext/public_capability_c0"
)


@pytest.fixture(scope="module")
def c0_inputs():
    root = _repo_root()
    with TemporaryDirectory(prefix="lesson-c0-test-") as temp_dir:
        snapshots = tuple(
            build_recorded_snapshot(
                problem_id,
                authority_dir=Path(temp_dir) / problem_id,
                f2_root=_resolve_repo_path(root, DEFAULT_F2_INPUT),
            )
            for problem_id in RECORDED_CASE_IDS
        )
    return snapshots, build_synthetic_capability_scenarios()


def test_public_set_is_derived_from_family_catalog() -> None:
    public = discover_public_lesson_capabilities()
    assert len(public) == 29
    assert sum(item.kind == "function" for item in public) == 23
    assert sum(item.kind == "macro" for item in public) == 6
    assert len({item.capability_id for item in public}) == 29
    assert all(item.families for item in public)


def test_recorded_and_typed_synthetic_execution_cover_all_public_capabilities(
    c0_inputs,
) -> None:
    snapshots, scenarios = c0_inputs
    report = build_lesson_capability_coverage(
        snapshots=snapshots,
        synthetic_scenarios={
            capability_id: scenario.coverage_payload()
            for capability_id, scenario in scenarios.items()
        },
    )
    assert report["summary"] == {
        "public_capability_count": 29,
        "public_function_count": 23,
        "public_macro_count": 6,
        "recorded_coverage_count": 26,
        "synthetic_coverage_count": 3,
        "complete_coverage_count": 29,
        "diagnostic_count": 0,
    }
    assert set(scenarios) == {
        "distance_between_points",
        "equal_length_ray_point",
        "line_intersection_point",
    }
    assert all(
        scenario.coverage_payload()["execution"] == "real_stateless_method"
        and scenario.coverage_payload()["checks_passed"]
        for scenario in scenarios.values()
    )


def test_each_public_function_and_macro_has_one_complete_disposition(
    c0_inputs,
) -> None:
    snapshots, scenarios = c0_inputs
    report = build_lesson_capability_coverage(
        snapshots=snapshots,
        synthetic_scenarios={
            key: value.coverage_payload() for key, value in scenarios.items()
        },
    )
    methods = MethodSpecRegistry.load_from_code()
    recipes = RecipeSpecRegistry.load_from_code()
    for capability_id, card in report["capabilities"].items():
        assert card["diagnostics"] == []
        if card["kind"] == "function":
            spec = methods.require(card["source_id"])
            assert (spec.teaching_unit is None) != (
                spec.generic_teaching_reason is None
            )
            assert (spec.visual is None) != (
                spec.no_new_visual_reason is None
            )
        else:
            spec = recipes.get(card["source_id"])
            assert spec is not None
            assert spec.teaching is not None
            assert spec.visual is not None
            unit_tails = {
                key.rsplit("/", 1)[-1]
                for key in card["teaching_units"]
            }
            assert unit_tails == set(spec.visual.teaching_substep_templates)


def test_new_public_macros_are_atomic_sources_with_two_bound_units(
    c0_inputs,
) -> None:
    snapshots, _ = c0_inputs
    sources = {
        source.capability_id: (snapshot, source)
        for snapshot in snapshots
        for source in iter_teaching_sources(snapshot.root_scope)
        if source.capability_id in {
            "right_angle_equal_length_construct_and_select",
            "curve_candidate_parameter_solve",
        }
    }
    assert set(sources) == {
        "right_angle_equal_length_construct_and_select",
        "curve_candidate_parameter_solve",
    }
    binder = TeachingSpecBinder()
    for snapshot, source in sources.values():
        assert len(binder.bind_source(source, snapshot=snapshot)) == 2
        assert source.calculations
        assert source.outputs


def test_review_has_one_card_per_public_capability(c0_inputs) -> None:
    snapshots, scenarios = c0_inputs
    artifacts = build_capability_coverage_review(
        snapshots=snapshots,
        synthetic_scenarios=scenarios,
    )
    assert len(artifacts.review["cards"]) == 29
    assert artifacts.review["human_review_approved"] is False
    assert artifacts.review["status"] == "awaiting_human_review"
    assert all(not card["diagnostics"] for card in artifacts.review["cards"])


def test_human_approved_c0_fixtures_match_current_public_registry(c0_inputs) -> None:
    snapshots, scenarios = c0_inputs
    artifacts = build_capability_coverage_review(
        snapshots=snapshots,
        synthetic_scenarios=scenarios,
    )
    expected = capability_coverage_fixture_payloads(artifacts)

    for filename, payload in expected.items():
        assert json.loads(
            (FIXTURE_ROOT / filename).read_text(encoding="utf-8")
        ) == payload

    review = json.loads(
        (FIXTURE_ROOT / "human-review-summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert review["review_status"] == "approved"
    assert review["source_batch"] == "f5-f5c0-public-capability-review"
    assert review["checks"]["all_29_capability_cards_reviewed"] is True
    assert review["checks"]["no_problem_specific_visual_patch"] is True


def test_generic_visual_builder_contains_no_public_capability_dispatch() -> None:
    builder_path = (
        Path(__file__).resolve().parents[2]
        / "shuxueshuo_server/solver/visual/builder.py"
    )
    source = builder_path.read_text(encoding="utf-8")
    public_ids = {
        item.capability_id for item in discover_public_lesson_capabilities()
    }
    assert sorted(capability_id for capability_id in public_ids if capability_id in source) == []


def test_conditional_visual_is_declared_by_output_presence() -> None:
    spec = MethodSpecRegistry.load_from_code().require(
        "evaluate_expression_at_parameter"
    )
    assert spec.visual is not None
    assert [
        template.get("when") for template in spec.visual.scene_templates
    ] == [{"output_present": "evaluated_parabola"}]
