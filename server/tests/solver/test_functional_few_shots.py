from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from typing import Any

import pytest

from shuxueshuo_server.solver.fixtures import (
    load_expected_answers,
    load_problem_ir,
)
from shuxueshuo_server.solver.runtime.functional_few_shots import (
    FunctionalFewShotAnnotation,
    FunctionalFewShotEntry,
    FunctionalFewShotIndex,
    FunctionalFewShotSelectionRecord,
    load_functional_few_shot_entries,
    load_functional_plan_fixture,
    project_functional_few_shot_example,
    select_functional_few_shot_examples,
    split_functional_few_shot_asset,
    validate_functional_few_shot_asset,
    validate_functional_few_shot_prompt_payload,
    validate_functional_plan_fixture,
)
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.functional_plan_validation import (
    FUNCTIONAL_PLAN_JSON_SCHEMA,
)
from shuxueshuo_server.solver.runtime.orchestrator import RuntimeOrchestrator
from shuxueshuo_server.solver.runtime.strategy_payload import (
    StrategyPayloadBuilder,
    StrategyPromptRenderer,
    build_strategy_probe_inputs,
)
from shuxueshuo_server.solver.runtime.strategy_runtime_planner import (
    strategy_planner_provider,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
PROBLEM_DIR = REPO_ROOT / "internal" / "solver-fixtures"
EXPECTED_DIR = Path(__file__).resolve().parent / "expected"
FUNCTIONAL_FEW_SHOT_DIR = REPO_ROOT / "internal" / "functional-few-shots"
PROBLEM_IDS = (
    "tj-2026-nankai-yimo-25",
    "tj-2026-hexi-yimo-25",
    "tj-2026-xiqing-yimo-25",
    "tj-2026-heping-yimo-25",
    "tj-2026-heping-ermo-25",
)


class _FixtureFunctionalClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.request: dict[str, Any] | None = None

    def complete(self, payload: dict[str, Any]) -> str:
        self.request = payload
        return json.dumps(self.payload, ensure_ascii=False)


@pytest.mark.parametrize("problem_id", PROBLEM_IDS)
def test_complete_functional_plan_fixture_replays_to_expected_answers(
    problem_id: str,
) -> None:
    plan = load_functional_plan_fixture(problem_id)
    problem = load_problem_ir(PROBLEM_DIR / f"{problem_id}.json")
    expected = load_expected_answers(
        EXPECTED_DIR / f"{problem_id}.expected.json"
    )
    client = _FixtureFunctionalClient(plan)
    orchestrator = RuntimeOrchestrator(
        planner_providers={},
        default_planner_provider=strategy_planner_provider(
            mode="deepseek",
            client=client,
            output_format="functional_plan",
        ),
        max_attempts=1,
    )

    result = orchestrator.solve(problem)

    assert result.status == "ok", result.errors
    assert result.answers == expected
    assert client.request is not None
    assert client.request["planner_output_format"] == "functional_plan"


def test_complete_functional_plan_assets_are_wire_safe_and_catalog_supported() -> None:
    entries = load_functional_few_shot_entries()
    source_ids = {item.source_problem_id for item in entries}

    assert source_ids == (
        set(PROBLEM_IDS)
        - {"tj-2026-xiqing-yimo-25"}
        | {"synthetic-quadratic-core-reference"}
    )
    for problem_id in PROBLEM_IDS:
        plan = load_functional_plan_fixture(problem_id)
        validate_functional_plan_fixture(plan)
        serialized = json.dumps(plan, ensure_ascii=False)
        assert "goal_type" not in serialized
        assert "runtime_path" not in serialized
        assert "creates" not in serialized
        assert "produces" not in serialized

        problem = load_problem_ir(PROBLEM_DIR / f"{problem_id}.json")
        inputs = build_strategy_probe_inputs(problem)
        catalog = FunctionalCapabilityCatalog.from_family_spec(
            inputs.family_spec,
            inputs.method_specs,
        )
        for call in _plan_calls(plan):
            capability = catalog.get(call["capability_id"])
            assert capability is not None, call["capability_id"]
            assert set(call["args"]) <= {
                item.name for item in capability.args
            }
            assert set(call["return_bindings"]) <= {
                item.name for item in capability.returns
            }


def test_stored_functional_few_shots_use_only_functional_plan_protocol() -> None:
    paths = sorted(
        FUNCTIONAL_FEW_SHOT_DIR.glob("*.functional-few-shot.json")
    )

    assert len(paths) == 7
    annotated_paths: list[str] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["format"] == "functional_plan/v1"
        validate_functional_few_shot_asset(payload)
        annotation, plan = split_functional_few_shot_asset(payload)
        validate_functional_few_shot_prompt_payload(plan)
        if annotation is not None:
            annotated_paths.append(path.name)
        assert "functional_few_shot/v1" not in json.dumps(
            payload,
            ensure_ascii=False,
        )
    assert annotated_paths == [
        "broken-path-straightening.functional-few-shot.json",
        "quadratic-constraints-vertex.functional-few-shot.json",
        "right-angle-equal-length-construction.functional-few-shot.json",
    ]


def test_nankai_functional_few_shot_annotations_are_safe_and_complete() -> None:
    entries = {
        item.example_id: item
        for item in load_functional_few_shot_entries()
        if item.source_problem_id == "tj-2026-nankai-yimo-25"
    }

    assert set(entries) == {
        "broken_path_straightening",
        "right_angle_equal_length_construction",
    }
    assert entries["broken_path_straightening"].selection_role == "core"
    assert (
        entries["broken_path_straightening"].family_id
        == "QuadraticPathMinimumSolver"
    )
    assert (
        entries["right_angle_equal_length_construction"].selection_role
        == "supporting"
    )
    for entry in entries.values():
        annotation = entry.annotation
        assert annotation is not None
        assert annotation.purpose
        assert annotation.use_when
        assert annotation.key_idea
        assert annotation.do_not_use_when
        assert len(annotation.do_not_use_when) == len(
            set(annotation.do_not_use_when)
        )


def test_family_index_is_complete_and_quadratic_fallback_is_universal() -> None:
    entries = load_functional_few_shot_entries()
    index = FunctionalFewShotIndex.from_entries(entries)
    fallback = _entry("quadratic_constraints_vertex")

    assert fallback.selection_role == "fallback"
    assert fallback.family_id is None
    assert index.fallback_by_pack["quadratic_core"] == (fallback,)
    assert set(index.by_family) == {
        "QuadraticPathMinimumSolver",
        "QuadraticWeightedPathMinimumSolver",
        "QuadraticEqualLengthRayPathMinimumSolver",
        "QuadraticSquareReflectionPathMinimumSolver",
    }
    for problem_id in PROBLEM_IDS:
        problem = load_problem_ir(PROBLEM_DIR / f"{problem_id}.json")
        inputs = build_strategy_probe_inputs(problem)
        catalog = FunctionalCapabilityCatalog.from_family_spec(
            inputs.family_spec,
            inputs.method_specs,
        )
        assert "quadratic_core" in inputs.family_spec.base_packs
        assert set(fallback.capability_ids) <= set(catalog.items)


def test_explicit_functional_mode_wins_over_legacy_boolean() -> None:
    problem = load_problem_ir(
        PROBLEM_DIR / "tj-2026-nankai-yimo-25.json"
    )
    inputs = build_strategy_probe_inputs(problem)

    legacy = StrategyPayloadBuilder(
        allow_same_problem_few_shot=False,
    ).build(inputs, output_format="functional_plan")
    explicit = StrategyPayloadBuilder(
        allow_same_problem_few_shot=False,
        functional_few_shot_mode="new_problem",
    ).build(inputs, output_format="functional_plan")

    assert legacy["functional_few_shot_selection"]["mode"] == "strict_test"
    assert legacy["functional_few_shot_selection"]["example_id"] == (
        "quadratic_constraints_vertex"
    )
    assert explicit["functional_few_shot_selection"]["mode"] == "new_problem"
    assert explicit["functional_few_shot_selection"]["example_id"] == (
        "broken_path_straightening"
    )


def test_retry_restores_locked_example_without_prompting_selection_metadata() -> None:
    problem = load_problem_ir(
        PROBLEM_DIR / "tj-2026-nankai-yimo-25.json"
    )
    inputs = build_strategy_probe_inputs(problem)
    locked = FunctionalFewShotSelectionRecord(
        example_id="right_angle_equal_length_construction",
        mode="new_problem",
        family_id=inputs.family_spec.family_id,
        source_problem_id=problem.problem_id,
        selection_tier="same_family",
    )
    retry_inputs = replace(
        inputs,
        previous_errors=[
            {"functional_few_shot_selection": locked.to_payload()}
        ],
    )

    payload = StrategyPayloadBuilder().build(
        retry_inputs,
        output_format="functional_plan",
    )
    prompt = StrategyPromptRenderer().render(payload).user

    assert payload["functional_few_shot_selection"] == locked.to_payload()
    assert _capability_ids(payload["few_shot_examples"][0]) == [
        "right_angle_equal_length_construct_and_select",
        "quadratic_from_constraints",
    ]
    for hidden in (
        locked.example_id,
        locked.source_problem_id,
        locked.family_id,
        locked.selection_tier,
    ):
        assert hidden not in prompt


def test_functional_few_shot_annotation_rejects_duplicate_exclusions() -> None:
    with pytest.raises(
        ValueError,
        match="do_not_use_when must be unique",
    ):
        FunctionalFewShotAnnotation.from_payload(
            {
                "purpose": "purpose",
                "use_when": "use when",
                "key_idea": "key idea",
                "do_not_use_when": ["same", "same"],
            }
        )


def test_mechanism_subgraphs_are_closed_neutralized_projections() -> None:
    entries = load_functional_few_shot_entries()

    assert len(entries) == 7
    for entry in entries:
        source = load_functional_plan_fixture(entry.source_problem_id)
        projected = project_functional_few_shot_example(
            entry,
            source_plan=source,
        )
        validate_functional_few_shot_prompt_payload(projected)
        calls = _plan_calls(projected)
        source_calls = {
            call["call_id"]: call
            for call in _plan_calls(source)
            if call["call_id"] in entry.source_call_ids
        }

        assert 2 <= len(calls) <= 5
        assert [call["capability_id"] for call in calls] == [
            source_calls[call_id]["capability_id"]
            for call_id in entry.source_call_ids
        ]
        assert _call_edges(calls) == {
            (
                entry.call_id_map[source],
                entry.call_id_map[target],
                return_name,
            )
            for source, target, return_name in _call_edges(
                source_calls.values()
            )
        }
        serialized = json.dumps(projected, ensure_ascii=False)
        assert entry.source_problem_id not in serialized
        assert '"example_id"' not in serialized
        assert "goal_type" not in serialized
        assert _semantic_refs(projected) == set(
            entry.semantic_ref_map.values()
        )


def test_selection_is_catalog_gated_cross_family_and_stable() -> None:
    entry = _entry("weighted_path_transform")
    kwargs = {
        "capability_ids": entry.capability_ids,
        "base_pack_ids": ("quadratic_core",),
        "mechanism_pack_ids": ("weighted_path_transform_core",),
        "answer_value_types": ("ParameterValue",),
        "problem_id": "synthetic-cross-family-problem",
        "allow_same_problem": False,
    }

    first = select_functional_few_shot_examples(**kwargs)
    second = select_functional_few_shot_examples(**kwargs)

    assert first == second
    assert _capability_ids(first[0]) == list(entry.capability_ids)
    with pytest.raises(
        ValueError,
        match="planner_configuration_error: no compatible functional few-shot",
    ):
        select_functional_few_shot_examples(
            **{**kwargs, "capability_ids": ("quadratic_from_constraints",)}
        )


@pytest.mark.parametrize(
    ("problem_id", "expected_example_id", "expected_tier"),
    (
        (
            "tj-2026-nankai-yimo-25",
            "quadratic_constraints_vertex",
            "fallback",
        ),
        (
            "tj-2026-heping-yimo-25",
            "quadratic_constraints_vertex",
            "fallback",
        ),
        (
            "tj-2026-heping-ermo-25",
            "broken_path_straightening",
            "cross_family",
        ),
    ),
)
def test_same_problem_uses_neutralized_mechanism_example(
    problem_id: str,
    expected_example_id: str,
    expected_tier: str,
) -> None:
    problem = load_problem_ir(PROBLEM_DIR / f"{problem_id}.json")
    payload = StrategyPayloadBuilder(
        allow_same_problem_few_shot=False
    ).build(
        build_strategy_probe_inputs(problem),
        output_format="functional_plan",
    )

    assert len(payload["few_shot_examples"]) == 1
    selection = payload["functional_few_shot_selection"]
    assert selection["example_id"] == expected_example_id
    assert selection["selection_tier"] == expected_tier
    assert selection["mode"] == "strict_test"
    assert selection["source_problem_id"] != problem_id
    serialized = json.dumps(
        payload["few_shot_examples"][0],
        ensure_ascii=False,
    )
    assert problem_id not in serialized


def test_nankai_core_annotation_is_rendered_before_strict_plan() -> None:
    problem = load_problem_ir(
        PROBLEM_DIR / "tj-2026-nankai-yimo-25.json"
    )
    payload = StrategyPayloadBuilder().build(
        build_strategy_probe_inputs(problem),
        output_format="functional_plan",
    )

    example = payload["few_shot_examples"][0]
    assert example["annotation"]["purpose"] == "双动点路径降维与折线拉直。"
    prompt = StrategyPromptRenderer().render(payload).user
    assert "### 机制说明" in prompt
    assert "双动点路径降维与折线拉直" in prompt
    assert "先建立显式路径等价变换" in prompt
    assert "### FunctionalPlan 示例" in prompt
    assert '"format": "functional_plan/v1"' in prompt
    assert '"annotation"' not in prompt
    assert "selection_role" not in prompt
    assert FUNCTIONAL_PLAN_JSON_SCHEMA["additionalProperties"] is False
    assert "annotation" not in FUNCTIONAL_PLAN_JSON_SCHEMA["properties"]


def test_nankai_family_new_problem_prefers_core_path_fragment() -> None:
    problem = load_problem_ir(
        PROBLEM_DIR / "tj-2026-nankai-yimo-25.json"
    )
    inputs = build_strategy_probe_inputs(problem)
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )

    selected = select_functional_few_shot_examples(
        capability_ids=catalog.items,
        base_pack_ids=inputs.family_spec.base_packs,
        mechanism_pack_ids=inputs.family_spec.mechanism_packs,
        answer_value_types=(
            goal.value_type for goal in inputs.question_goals if goal.required
        ),
        family_id=inputs.family_spec.family_id,
        problem_id="synthetic-new-problem",
    )

    assert len(selected) == 1
    assert _capability_ids(selected[0]) == [
        "two_moving_points_path_reduction",
        "broken_path_straightening_minimum_expression",
    ]


def test_missing_functional_selection_fails_before_prompt_render(
    tmp_path: Path,
) -> None:
    problem = load_problem_ir(
        PROBLEM_DIR / "tj-2026-nankai-yimo-25.json"
    )
    with pytest.raises(
        ValueError,
        match="planner_configuration_error: no compatible functional few-shot",
    ):
        StrategyPayloadBuilder(
            functional_few_shot_dir=tmp_path,
        ).build(
            build_strategy_probe_inputs(problem),
            output_format="functional_plan",
        )


def test_explicit_functional_examples_take_precedence() -> None:
    problem = load_problem_ir(
        PROBLEM_DIR / "tj-2026-nankai-yimo-25.json"
    )
    explicit = [
        {
            "format": "functional_plan/v1",
            "scopes": [
                {
                    "scope_id": "example",
                    "label": "example",
                    "calls": [],
                }
            ],
        }
    ]
    payload = StrategyPayloadBuilder(
        functional_few_shot_examples=explicit,
    ).build(
        build_strategy_probe_inputs(problem),
        output_format="functional_plan",
    )

    assert payload["few_shot_examples"] is explicit


def _entry(example_id: str) -> FunctionalFewShotEntry:
    return next(
        item
        for item in load_functional_few_shot_entries()
        if item.example_id == example_id
    )


def _plan_calls(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        call
        for scope in plan["scopes"]
        for call in scope["calls"]
    ]


def _call_edges(
    calls: Any,
) -> set[tuple[str, str, str]]:
    result: set[tuple[str, str, str]] = set()
    for call in calls:
        for value in call["args"].values():
            for ref in value if isinstance(value, list) else (value,):
                if isinstance(ref, dict) and "from_call" in ref:
                    result.add(
                        (
                            ref["from_call"],
                            call["call_id"],
                            ref["return"],
                        )
                    )
    return result


def _capability_ids(example: dict[str, Any]) -> list[str]:
    return [
        call["capability_id"]
        for call in _plan_calls(example)
    ]


def _semantic_refs(value: Any) -> set[str]:
    if isinstance(value, dict):
        if {"ref", "kind"} <= set(value):
            return {str(value["ref"])}
        return {
            ref
            for item in value.values()
            for ref in _semantic_refs(item)
        }
    if isinstance(value, list):
        return {
            ref
            for item in value
            for ref in _semantic_refs(item)
        }
    return set()
