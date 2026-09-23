from __future__ import annotations

from pathlib import Path

import pytest
from support.generated_gate_profiles import (
    assert_complete_partition,
    coverage_first_sample,
    select_shard,
    stable_bucket,
)

from tools.run_solver_tests import pytest_commands, sanitized_environment
from tools.solver_test_profiles import (
    LIVE_LLM_TEST_FILES,
    PROFILE_MARKERS,
    marker_for_test_file,
)
from tools.solver_test_profiles import (
    tests_for_changed_paths as _tests_for_changed_paths,
)


def test_profile_marker_expressions_keep_live_tests_separate() -> None:
    assert PROFILE_MARKERS == {
        "fast": "not solver_contract and not solver_full and not live_llm",
        "contract": "not solver_full and not live_llm",
        "full": "not live_llm",
    }
    assert all(
        marker_for_test_file(file_name) == "live_llm"
        for file_name in LIVE_LLM_TEST_FILES
    )


def test_parallel_profiles_split_parallel_and_serial_invocations() -> None:
    commands = pytest_commands("contract", workers=4, durations=17)

    assert len(commands) == 2
    assert commands[0][commands[0].index("-n") + 1] == "4"
    assert commands[0][commands[0].index("--dist") + 1] == "worksteal"
    parallel_marker_index = max(
        index for index, item in enumerate(commands[0]) if item == "-m"
    )
    serial_marker_index = max(
        index for index, item in enumerate(commands[1]) if item == "-m"
    )
    assert "and not serial" in commands[0][parallel_marker_index + 1]
    assert commands[1][commands[1].index("-n") + 1] == "0"
    assert "and serial" in commands[1][serial_marker_index + 1]
    assert commands[0][commands[0].index("--durations") + 1] == "17"


def test_affected_profile_runs_selected_tests_without_xdist() -> None:
    commands = pytest_commands(
        "affected",
        selected_tests=("tests/solver/test_state_identity.py",),
        workers=4,
    )

    assert len(commands) == 1
    assert "tests/solver/test_state_identity.py" in commands[0]
    assert "-n" not in commands[0]
    marker_index = max(index for index, item in enumerate(commands[0]) if item == "-m")
    assert commands[0][marker_index + 1] == "not solver_full and not live_llm"


def test_offline_environment_removes_provider_authority(monkeypatch) -> None:
    monkeypatch.setenv("RUN_LLM_INTEGRATION", "1")
    monkeypatch.setenv("RUN_DEEPSEEK_FUNCTIONAL_PLANNER", "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret")
    monkeypatch.setenv("DOUBAO_API_KEY", "secret")

    environment = sanitized_environment()

    assert environment["RUN_LLM_INTEGRATION"] == "0"
    assert "RUN_DEEPSEEK_FUNCTIONAL_PLANNER" not in environment
    assert "DEEPSEEK_API_KEY" not in environment
    assert "DOUBAO_API_KEY" not in environment


def test_affected_ownership_maps_goal_runtime_to_contract_tests() -> None:
    selected, unmapped = _tests_for_changed_paths(
        ("server/shuxueshuo_server/solver/runtime/functional_scope_retry.py",)
    )

    assert not unmapped
    assert "tests/solver/test_functional_scope_retry.py" in selected
    assert "tests/solver/test_functional_scope_retry_generated_gate.py" in selected
    assert "tests/solver/test_functional_goal_checkpoint_v3.py" in selected


@pytest.mark.parametrize(
    "path",
    [
        "server/shuxueshuo_server/problem_understanding/runtime_binding.py",
        "server/shuxueshuo_server/problem_understanding/compact_planner_input.py",
        "server/shuxueshuo_server/solver/runtime/capability_math_signatures.py",
        "server/tests/solver/fixtures/math-runtime-binding-stage-two/candidate.json",
    ],
)
def test_affected_ownership_includes_notation_runtime_binding(path):
    selected, unmapped = _tests_for_changed_paths((path,))
    assert not unmapped
    assert "tests/solver/test_math_runtime_binding.py" in selected
    assert "tests/solver/test_math_compact_planner_input.py" in selected


def test_affected_ownership_maps_private_path_helpers_to_atomic_macro_tests() -> None:
    selected, unmapped = _tests_for_changed_paths(
        (
            (
                "server/shuxueshuo_server/solver/runtime/methods/"
                "_internal/path/square_path_dimension_reduction.py"
            ),
        )
    )

    assert not unmapped
    assert "tests/solver/test_method_spec_loader.py" in selected
    assert "tests/solver/test_runtime_stateless_methods.py" in selected
    assert "tests/solver/test_coupled_segment_path_macro.py" in selected
    assert "tests/solver/test_quadratic_square_path_macro.py" in selected
    assert "tests/solver/test_weighted_axis_path_macro.py" in selected


def test_affected_ownership_maps_b2_projection_and_review_to_b2_gates() -> None:
    selected, unmapped = _tests_for_changed_paths(
        (
            "server/shuxueshuo_server/solver/explanation/annotated_teaching.py",
            "server/shuxueshuo_server/solver/lesson_annotated_teaching_review.py",
            "internal/schemas/functional-annotated-teaching-plan.schema.json",
        )
    )

    assert not unmapped
    assert "tests/solver/test_annotated_teaching_plan.py" in selected
    assert "tests/solver/test_lesson_scope_authoring_b2.py" in selected
    assert "tests/solver/test_teaching_unit_specs.py" in selected


def test_affected_ownership_maps_b3_service_and_harness_to_b3_gates() -> None:
    selected, unmapped = _tests_for_changed_paths(
        (
            "server/shuxueshuo_server/solver/explanation/scope_lesson.py",
            "server/shuxueshuo_server/solver/lesson_scope_content_smoke.py",
            "server/shuxueshuo_server/solver/runtime/llm_clients.py",
        )
    )

    assert not unmapped
    assert "tests/solver/test_lesson_scope_content.py" in selected
    assert "tests/solver/test_lesson_scope_authoring_b3.py" in selected
    assert "tests/solver/test_llm_clients.py" in selected


def test_affected_ownership_ignores_docs_only_changes() -> None:
    selected, unmapped = _tests_for_changed_paths(("docs/solver-test-strategy.md",))

    assert selected == ()
    assert unmapped == ()


@pytest.mark.parametrize(
    "path",
    [
        "server/shuxueshuo_server/problem_understanding/notation_normalization.py",
        "server/shuxueshuo_server/problem_understanding/review_contract.py",
        "server/shuxueshuo_server/problem_understanding/workflow_diagnostics.py",
        "server/shuxueshuo_server/problem_understanding/repair_guard.py",
        "server/shuxueshuo_server/solver/extraction/deepseek_files.py",
        "server/shuxueshuo_server/solver/extraction/multimodal_provider.py",
        "server/shuxueshuo_server/problem_understanding/notation_geometry_proofs.py",
        "server/shuxueshuo_server/problem_understanding/notation_implication.py",
        "server/shuxueshuo_server/problem_understanding/proof_budget.py",
        "internal/llm-prompts/problem-math-notation-expressions.json",
        "internal/llm-prompts/problem-math-notation-review-families.json",
        "internal/llm-prompts/problem-math-notation-system.md",
        "internal/schemas/problem-math-notation-v1.schema.json",
        "internal/schemas/problem-math-source-review-v1.schema.json",
        "server/tools/report_math_notation_workflow.py",
        "server/tests/solver/fixtures/math-notation-v1/example.json",
        "server/tests/solver/fixtures/math-notation-v1/future-recorded-batch/example.txt",
    ],
)
def test_math_notation_changes_select_generated_and_recorded_gates(path):
    selected, unmapped = _tests_for_changed_paths([path])
    assert not unmapped
    assert "tests/solver/test_math_notation_normalization.py" in selected
    assert "tests/solver/test_math_notation_state_proofs.py" in selected
    assert "tests/solver/test_math_notation_state_scope.py" in selected
    assert "tests/solver/test_math_notation_recorded.py" in selected
    assert "tests/solver/test_math_notation_extraction_rules.py" in selected
    assert "tests/solver/test_math_notation_redundancy.py" in selected
    assert "tests/solver/test_math_notation_geometry_proofs.py" in selected
    assert "tests/solver/test_math_notation_intersection_definition.py" in selected
    assert "tests/solver/test_math_notation_angle_catalog.py" in selected
    assert "tests/solver/test_math_notation_workflow.py" in selected
    assert "tests/solver/test_math_notation_repair_authority.py" in selected
    assert "tests/solver/test_math_notation_diagnostic_routes.py" in selected
    assert "tests/solver/test_math_notation_transport_accounting.py" in selected
    assert "tests/solver/test_math_notation_review_families.py" in selected
    assert "tests/solver/test_deepseek_files.py" in selected
    assert "tests/solver/test_deepseek_vision.py" in selected
    assert "tests/solver/test_math_notation_cleanup.py" in selected


def test_changed_solver_test_selects_itself() -> None:
    selected, unmapped = _tests_for_changed_paths(
        ("server/tests/solver/test_math_kernel.py",)
    )

    assert "tests/solver/test_math_kernel.py" in selected
    assert not unmapped


def test_unknown_solver_subsystem_fails_loud() -> None:
    selected, unmapped = _tests_for_changed_paths(
        ("server/shuxueshuo_server/solver/new_subsystem/engine.py",)
    )

    assert selected
    assert unmapped == ("server/shuxueshuo_server/solver/new_subsystem/engine.py",)


def test_current_solver_sources_have_an_ownership_rule() -> None:
    server_root = Path(__file__).resolve().parents[2]
    solver_root = server_root / "shuxueshuo_server" / "solver"
    unmapped: list[str] = []
    for path in solver_root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        repo_path = "server/" + path.relative_to(server_root).as_posix()
        _, missing = _tests_for_changed_paths((repo_path,))
        unmapped.extend(missing)

    assert not unmapped, unmapped


def test_stable_generated_shards_are_complete_and_disjoint() -> None:
    scenarios = tuple(f"scenario:{index}" for index in range(257))

    assert_complete_partition(scenarios, scenario_id=lambda item: item)
    shards = tuple(
        select_shard(
            scenarios,
            shard_index,
            scenario_id=lambda item: item,
        )
        for shard_index in range(8)
    )

    assert sum(map(len, shards)) == len(scenarios)
    assert set().union(*map(set, shards)) == set(scenarios)
    assert stable_bucket(scenarios[0]) == stable_bucket(scenarios[0])


def test_quick_sample_preserves_pinned_cases_and_dimension_values() -> None:
    scenarios = tuple(
        {
            "id": f"scenario:{index}",
            "kind": f"kind-{index % 7}",
            "pinned": index in {2, 101},
        }
        for index in range(200)
    )

    sample = coverage_first_sample(
        scenarios,
        32,
        scenario_id=lambda item: item["id"],
        dimensions=lambda item: {"kind": item["kind"]},
        pinned=lambda item: item["pinned"],
    )

    assert len(sample) == 32
    assert {item["id"] for item in sample} >= {"scenario:2", "scenario:101"}
    assert {item["kind"] for item in sample} == {f"kind-{index}" for index in range(7)}


def test_math_expression_parser_ownership_includes_legacy_and_frozen_inputs():
    for module in ("expression_parser", "expression_rewrite"):
        selected, unmapped = _tests_for_changed_paths(
            (f"server/shuxueshuo_server/solver/math_kernel/{module}.py",)
        )
        assert not unmapped
        assert {
            "tests/solver/test_expression_parser.py",
            "tests/solver/test_organize_expressions.py",
            "tests/solver/test_organize_expressions_transaction.py",
            "tests/solver/test_basic_inequality_problem_ir.py",
        }.issubset(selected)


def test_proof_kernel_ownership_includes_parser_and_existing_runtime_regressions():
    for module in ("proof_kernel", "proof_algebra"):
        selected, unmapped = _tests_for_changed_paths(
            (f"server/shuxueshuo_server/solver/math_kernel/{module}.py",)
        )
        assert not unmapped
        assert {
            "tests/solver/test_math_proof_kernel.py",
            "tests/solver/test_expression_parser.py",
            "tests/solver/test_organize_expressions.py",
            "tests/solver/test_organize_expressions_transaction.py",
            "tests/solver/test_basic_inequality_problem_ir.py",
        }.issubset(selected)
