from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable


PROFILE_MARKERS = {
    "fast": "not solver_contract and not solver_full and not live_llm",
    "contract": "not solver_full and not live_llm",
    "full": "not live_llm",
}

DEFAULT_WORKERS = 4

CORE_INVARIANT_TESTS = (
    "tests/solver/test_functional_plan_content_schema.py",
    "tests/solver/test_scoped_functional_plan_authority.py",
    "tests/solver/test_method_input_read_authority.py",
    "tests/solver/test_method_output_write_authority.py",
    "tests/solver/test_functional_goal_checkpoint_v3.py",
    "tests/solver/test_functional_scope_retry.py",
)

CONTRACT_TEST_FILES = frozenset(
    {
        "test_functional_direct_compiler.py",
        "test_functional_goal_checkpoint_v3.py",
        "test_functional_goal_execution.py",
        "test_functional_scope_retry.py",
        "test_functional_transaction_execution.py",
        "test_macro_prebinding_runtime_search.py",
        "test_method_output_write_authority.py",
        "test_problem_planning_binding.py",
        "test_runtime_authority_convergence.py",
        "test_scoped_functional_plan_replay.py",
        "test_strategy_planner_functional_parity.py",
        "test_verified_functional_plan_execution.py",
        "test_verified_solver_cold_path.py",
    }
)

FULL_TEST_FILES: frozenset[str] = frozenset()

LIVE_LLM_TEST_FILES = frozenset(
    {
        "test_deepseek_functional_planner_heping.py",
        "test_deepseek_functional_planner_heping_ermo.py",
        "test_deepseek_functional_planner_hexi.py",
        "test_deepseek_functional_planner_nankai.py",
        "test_deepseek_functional_planner_xiqing.py",
        "test_llm_provider_integration.py",
    }
)


@dataclass(frozen=True)
class OwnershipRule:
    patterns: tuple[str, ...]
    tests: tuple[str, ...]

    def matches(self, path: str) -> bool:
        normalized = PurePosixPath(path)
        return any(normalized.match(pattern) for pattern in self.patterns)


OWNERSHIP_RULES = (
    OwnershipRule(
        (
            "server/tools/run_solver_tests.py",
            "server/tools/solver_test_profiles.py",
            "server/tests/solver/conftest.py",
            "server/pyproject.toml",
        ),
        ("tests/solver/test_solver_test_profiles.py",),
    ),
    OwnershipRule(
        (
            "server/shuxueshuo_server/solver/runtime/functional_goal*.py",
            "server/shuxueshuo_server/solver/runtime/functional_scope_retry.py",
            "server/shuxueshuo_server/solver/runtime/*checkpoint*.py",
            "server/shuxueshuo_server/solver/runtime/scoped_functional_plan_replay.py",
        ),
        (
            "tests/solver/test_functional_goal_execution.py",
            "tests/solver/test_functional_scope_retry.py",
            "tests/solver/test_functional_goal_checkpoint_v3.py",
            "tests/solver/test_scoped_functional_plan_replay.py",
        ),
    ),
    OwnershipRule(
        (
            "server/shuxueshuo_server/solver/runtime/macro*.py",
            "server/shuxueshuo_server/solver/runtime/recipes/*.py",
            "server/shuxueshuo_server/solver/runtime/recipe_compiler.py",
            "server/shuxueshuo_server/solver/runtime/functional_transaction_execution.py",
        ),
        (
            "tests/solver/test_macro_prebinding_runtime_search.py",
            "tests/solver/test_macro_runtime_search.py",
            "tests/solver/test_functional_transaction_execution.py",
            "tests/solver/test_runtime_authority_convergence.py",
            "tests/solver/test_verified_functional_plan_execution.py",
        ),
    ),
    OwnershipRule(
        (
            "server/shuxueshuo_server/solver/runtime/methods/*.py",
            "server/shuxueshuo_server/solver/runtime/method_input*.py",
            "server/shuxueshuo_server/solver/runtime/method_output*.py",
            "server/shuxueshuo_server/solver/runtime/invocation*.py",
            "internal/method-specs/*.json",
            "internal/schemas/method-*.schema.json",
        ),
        (
            "tests/solver/test_runtime_stateless_methods.py",
            "tests/solver/test_method_input_views.py",
            "tests/solver/test_method_input_read_authority.py",
            "tests/solver/test_method_output_write_authority.py",
            "tests/solver/test_method_input_relations.py",
            "tests/solver/test_invocation_executor.py",
            "tests/solver/test_functional_diagnostics.py",
        ),
    ),
    OwnershipRule(
        ("server/shuxueshuo_server/solver/family/*.py",),
        (
            "tests/solver/test_family_spec.py",
            "tests/solver/test_strategy_planner_function_specs.py",
            "tests/solver/test_strategy_planner_macro_specs.py",
            "tests/solver/test_equal_length_ray_path_macro.py",
        ),
    ),
    OwnershipRule(
        ("server/shuxueshuo_server/solver/math_kernel/*.py",),
        (
            "tests/solver/test_math_kernel.py",
            "tests/solver/test_symbolic_closure_execution.py",
        ),
    ),
    OwnershipRule(
        ("server/shuxueshuo_server/solver/extraction/*.py",),
        (
            "tests/solver/test_problem_extraction_context.py",
            "tests/solver/test_problem_extraction_observations.py",
            "tests/solver/test_problem_extraction_evidence_pack.py",
            "tests/solver/test_problem_extraction_source_fingerprint.py",
        ),
    ),
    OwnershipRule(
        (
            "server/shuxueshuo_server/solver/explanation/*.py",
            "server/shuxueshuo_server/solver/explanation/**/*.py",
        ),
        (
            "tests/solver/test_explanation_snapshot_symbolic_closure.py",
            "tests/solver/test_explanation_builder_text_heping_yimo.py",
        ),
    ),
    OwnershipRule(
        ("server/shuxueshuo_server/solver/visual/*.py",),
        (
            "tests/solver/test_visual_step_ir_vs0.py",
            "tests/solver/test_visual_step_ir_vs1.py",
        ),
    ),
    OwnershipRule(
        (
            "server/shuxueshuo_server/solver/runtime/problem_planning*.py",
            "server/shuxueshuo_server/solver/runtime/*binding*.py",
            "server/shuxueshuo_server/solver/runtime/*provenance*.py",
        ),
        (
            "tests/solver/test_problem_planning_binding.py",
            "tests/solver/test_functional_binding_context.py",
            "tests/solver/test_problem_runtime_provenance.py",
            "tests/solver/test_functional_entity_view_binding.py",
        ),
    ),
    OwnershipRule(
        (
            "server/shuxueshuo_server/solver/runtime/scoped_functional_plan*.py",
            "server/shuxueshuo_server/solver/runtime/functional_plan_content*.py",
            "internal/llm-prompts/strategy-functional*.jinja",
            "internal/schemas/functional-*.schema.json",
        ),
        (
            "tests/solver/test_functional_plan_content_schema.py",
            "tests/solver/test_functional_plan_content_assembly.py",
            "tests/solver/test_scoped_functional_plan_schema.py",
            "tests/solver/test_scoped_functional_plan_prompt.py",
            "tests/solver/test_functional_scope_retry.py",
        ),
    ),
    OwnershipRule(
        ("server/shuxueshuo_server/solver/runtime/*.py",),
        (
            "tests/solver/test_runtime_context_scopes.py",
            "tests/solver/test_state_identity.py",
            "tests/solver/test_state_semantics.py",
            "tests/solver/test_runtime_authority_convergence.py",
        ),
    ),
    OwnershipRule(
        ("server/shuxueshuo_server/solver/*.py",),
        (
            "tests/solver/test_question_goals.py",
            "tests/solver/test_result_builder.py",
            "tests/solver/test_problem_solver_bundle.py",
            "tests/solver/test_verified_solver_cold_path.py",
        ),
    ),
    OwnershipRule(
        ("server/tests/solver/support/*.py",),
        (
            "tests/solver/test_scope_native_c0_c5_oracle.py",
            "tests/solver/test_scope_native_c0_c5_generated_gate.py",
            "tests/solver/test_functional_scope_retry.py",
            "tests/solver/test_scope_native_runtime_authority_generated_gate.py",
        ),
    ),
    OwnershipRule(
        ("server/tests/solver/fixtures/**/*.json",),
        (
            "tests/solver/test_fixture_schema.py",
            "tests/solver/test_scope_native_c0_c5_generated_gate.py",
        ),
    ),
)


def normalize_repo_path(path: str | Path) -> str:
    return str(path).replace("\\", "/").removeprefix("./")


def is_solver_source(path: str | Path) -> bool:
    normalized = normalize_repo_path(path)
    return normalized.startswith(
        (
            "server/shuxueshuo_server/solver/",
            "internal/llm-prompts/strategy-functional",
            "internal/schemas/functional-",
        )
    )


def tests_for_changed_paths(
    paths: Iterable[str | Path],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    selected = set(CORE_INVARIANT_TESTS)
    unmapped: list[str] = []
    relevant = False
    for raw_path in paths:
        path = normalize_repo_path(raw_path)
        if path.startswith("server/tests/solver/test_") and path.endswith(".py"):
            relevant = True
            selected.add(path.removeprefix("server/"))
        matching = tuple(rule for rule in OWNERSHIP_RULES if rule.matches(path))
        if matching:
            relevant = True
            for rule in matching:
                selected.update(rule.tests)
        elif is_solver_source(path):
            relevant = True
            unmapped.append(path)
    if not relevant:
        return (), tuple(sorted(unmapped))
    return tuple(sorted(selected)), tuple(sorted(unmapped))


def marker_for_test_file(file_name: str) -> str | None:
    if file_name in LIVE_LLM_TEST_FILES:
        return "live_llm"
    if file_name in FULL_TEST_FILES:
        return "solver_full"
    if file_name in CONTRACT_TEST_FILES:
        return "solver_contract"
    return None
