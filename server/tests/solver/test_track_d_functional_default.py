from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
from shuxueshuo_server.solver.runtime.strategy_runtime_planner import (
    StrategyPlanner,
)


_RUNTIME_ROOT = (
    Path(__file__).resolve().parents[2]
    / "shuxueshuo_server"
    / "solver"
    / "runtime"
)
_REPO_ROOT = Path(__file__).resolve().parents[3]

_RETIRED_MODULES = (
    "canonical_draft_finalizer",
    "strategy_normalizer",
    "strategy_resolver",
    "strategy_validator",
    "strategy_retry_state",
    "strategy_raw_outputs",
)

_RETIRED_SYMBOLS = {
    "StepIntentDraft",
    "prepare_step_intent_raw_response",
    "sanitize_step_intent_raw_payload",
    "StepIntentCandidateResolver",
    "RecipeTrialExecutor",
    "CanonicalDraftFinalizer",
    "StepIntentRepairAttempt",
}

_RETIRED_DIAGNOSTIC_TYPES = {
    "StepIntentAppliedFill",
    "StepIntentAcceptedStep",
    "StepIntentPlannerInsight",
    "StepIntentPreflightIssue",
    "StepIntentFunctionBindingEvent",
    "StepIntentMacroBindingEvent",
    "StepIntentRuntimeResult",
    "StepIntentExecutionBlocker",
    "StepIntentSkippedStep",
    "StepIntentExecutionDiagnostic",
}


def test_default_strategy_provider_is_functional() -> None:
    config = SolverRuntimeConfig()
    provider = config.build_default_planner_provider()

    assert provider is not None
    assert not hasattr(config, "planner_output_format")
    assert not hasattr(config, "functional_transaction_mode")
    assert not hasattr(config, "functional_symbolic_closure_mode")
    assert not hasattr(config, "functional_compile_mode")
    closure_values = tuple(
        cell.cell_contents for cell in (provider.__closure__ or ())
    )
    assert "recorded" in closure_values
    assert StrategyPlanner.__doc__ is not None
    assert "FunctionalPlan" in StrategyPlanner.__doc__


def test_retired_step_intent_modules_are_absent() -> None:
    for module in _RETIRED_MODULES:
        assert importlib.util.find_spec(
            f"shuxueshuo_server.solver.runtime.{module}"
        ) is None


def test_production_runtime_does_not_reference_retired_protocol_symbols() -> None:
    references: list[tuple[str, str]] = []
    for path in sorted(_RUNTIME_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in _RETIRED_SYMBOLS:
                references.append((path.name, node.id))
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    leaf = alias.name.rsplit(".", 1)[-1]
                    if leaf in _RETIRED_SYMBOLS:
                        references.append((path.name, leaf))

    assert references == []


def test_functional_runtime_diagnostic_types_do_not_use_retired_names() -> None:
    source = (
        _RUNTIME_ROOT / "strategy_models.py"
    ).read_text(encoding="utf-8")

    assert not any(name in source for name in _RETIRED_DIAGNOSTIC_TYPES)
    assert "class FunctionalExecutionDiagnostic" in source
    assert "class FunctionalRuntimeResult" in source


def test_maintenance_tools_do_not_depend_on_retired_step_intent_assets() -> None:
    for relative_path in (
        "tools/sync_strategy_few_shots.py",
        "tools/sync_explanation_few_shots.py",
    ):
        source = (_REPO_ROOT / relative_path).read_text(encoding="utf-8")
        assert "runtime.strategy_few_shots" not in source
        assert "executable-step-intents" not in source
        assert "functional_plan_fixture" in source


def test_active_architecture_and_onboarding_docs_use_functional_plan() -> None:
    for relative_path in (
        "docs/method-solver-architecture.md",
        "docs/dynamic-few-shot-strategy-plan.md",
        "internal/skills/deepseek-25-onboarding/SKILL.md",
    ):
        source = (_REPO_ROOT / relative_path).read_text(encoding="utf-8")
        assert "executable-step-intents" not in source
        assert "internal/few-shots/" not in source
        assert "functional" in source.lower()
    architecture = (_REPO_ROOT / "docs/method-solver-architecture.md").read_text(
        encoding="utf-8"
    )
    assert "functional-plan-content/v2" in architecture
    assert "functional-scope-repair/v1" in architecture
    assert "functional_plan/v2" in architecture
