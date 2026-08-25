from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest

from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.functional_goal_execution import (
    ScopedFunctionalGoalExecutionService,
)
from shuxueshuo_server.solver.runtime.functional_subplan import (
    FunctionalPlanFragment,
)
from shuxueshuo_server.solver.runtime.macro_plan_materialization import (
    macro_standard_output_payload,
)
from shuxueshuo_server.solver.runtime.macro_preparation import (
    MacroPreparationService,
)

from _problem_planning_support import planning_binding_fixture
from _scoped_functional_plan_support import load_v3_fixture_payload


pytestmark = pytest.mark.solver_contract


EXPLICIT_PLAN_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "explicit_function_plans"
    / "heping_equal_length_ray.json"
)


def _execute(fixture, payload, *, macro_expansions=()):
    return ScopedFunctionalGoalExecutionService().execute_raw_json(
        json.dumps(payload, ensure_ascii=False),
        inputs=fixture[3],
        planning_context=fixture[1],
        problem_binding_catalog=fixture[7],
        handle_registry=fixture[5],
        context=ContextBuilder().build(fixture[2]),
        planner_state_context=fixture[6],
        problem_payload=fixture[4],
        macro_expansions=macro_expansions,
    )


def _load_explicit_function_plan(case: str) -> tuple[dict[str, Any], dict[str, Any]]:
    fragment = json.loads(EXPLICIT_PLAN_FIXTURE.read_text(encoding="utf-8"))
    assert fragment["case_id"] == case
    payload = deepcopy(load_v3_fixture_payload(case))
    macro_step_id = str(fragment["replaces_step_id"])
    export = dict(fragment["exports"]["minimum_expression"])

    def rewrite(value: Any) -> Any:
        if isinstance(value, list):
            rewritten: list[Any] = []
            for item in value:
                if (
                    isinstance(item, Mapping)
                    and item.get("step_id") == macro_step_id
                    and "capability_id" in item
                ):
                    rewritten.extend(deepcopy(fragment["steps"]))
                else:
                    rewritten.append(rewrite(item))
            return rewritten
        if isinstance(value, Mapping):
            if (
                value.get("step_id") == macro_step_id
                and value.get("return") == "minimum_expression"
                and "capability_id" not in value
            ):
                return deepcopy(export)
            return {str(key): rewrite(child) for key, child in value.items()}
        return value

    return rewrite(payload), fragment


def _fragment_from_result(result, step_ids, exports) -> FunctionalPlanFragment:
    by_id = {step.step_id: step for step in result.canonical_plan.steps}
    return FunctionalPlanFragment(
        scope_id="ii",
        steps=tuple(by_id[step_id] for step_id in step_ids),
        exports={
            name: (str(value["step_id"]), str(value["return"]))
            if isinstance(value, Mapping)
            else tuple(value)
            for name, value in exports.items()
        },
    )


def _replace_step_names(value: Any, step_tokens: Mapping[str, str]) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _replace_step_names(child, step_tokens)
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_replace_step_names(child, step_tokens) for child in value]
    if isinstance(value, str):
        normalized = value
        for step_id, token in sorted(
            step_tokens.items(),
            key=lambda item: len(item[0]),
            reverse=True,
        ):
            normalized = normalized.replace(step_id, token)
        return normalized
    return value


def _alpha_normalized_f5c_graph(result, step_ids: Sequence[str]) -> list[dict[str, Any]]:
    reconciliation = result.replay.functional_reconciliation
    assert reconciliation is not None
    context = reconciliation.functional_problem_binding_context
    assert context is not None
    by_id = {step.step_id: step for step in result.canonical_plan.steps}
    step_tokens = {
        step_id: f"step:{index}" for index, step_id in enumerate(step_ids)
    }
    graph: list[dict[str, Any]] = []
    for step_id in step_ids:
        binding = context.call_binding(step_id).authority_payload()
        inputs = []
        for item in binding["input_bindings"]:
            typed_source = dict(item["typed_source"])
            if typed_source["kind"] == "condition":
                typed_source = {
                    "kind": "condition",
                    "runtime_node_id": item.get("runtime_node_id"),
                }
            inputs.append(
                _replace_step_names(
                    {
                        "arg_name": item["arg_name"],
                        "item_index": item["item_index"],
                        "source_kind": item["source_kind"],
                        "selection_policy": item["selection_policy"],
                        "semantic_ref": item.get("semantic_ref"),
                        "runtime_node_id": item.get("runtime_node_id"),
                        "source_unit_ids": item.get("source_unit_ids", []),
                        "typed_source": typed_source,
                    },
                    step_tokens,
                )
            )
        graph.append(
            {
                "step": step_tokens[step_id],
                "capability_id": by_id[step_id].capability_id,
                "inputs": sorted(
                    inputs,
                    key=lambda item: (item["arg_name"], item["item_index"]),
                ),
            }
        )
    return graph


def _alpha_normalized_conditions(result, step_ids: Sequence[str]) -> list[dict[str, Any]]:
    attempt = result.replay.transactional_attempt_result
    assert attempt is not None
    step_tokens = {
        step_id: f"step:{index}" for index, step_id in enumerate(step_ids)
    }
    selected = set(step_ids)
    conditions = []
    for call in attempt.execution_report.call_results:
        if call.call_id not in selected:
            continue
        for condition in call.published_conditions:
            payload = condition.to_payload()
            conditions.append(
                _replace_step_names(
                    {
                        "kind": payload["kind"],
                        "scope_id": payload["scope_id"],
                        "object_roles": payload["object_roles"],
                        "source_step_id": payload["source_step_id"],
                        "valid_scope": payload["valid_scope"],
                    },
                    step_tokens,
                )
            )
    return conditions


def _alpha_normalized_runtime_authority(
    result,
    step_ids: Sequence[str],
) -> list[dict[str, Any]]:
    attempt = result.replay.transactional_attempt_result
    assert attempt is not None
    by_call = {
        item.call_id: item for item in attempt.execution_report.call_results
    }
    step_tokens = {
        step_id: f"step:{index}" for index, step_id in enumerate(step_ids)
    }
    authority = []
    for step_id in step_ids:
        call = by_call[step_id]
        writes = []
        for write in call.state_writes:
            payload = write.to_payload()
            writes.append(
                _replace_step_names(
                    {
                        "output_key": payload["output_key"],
                        "runtime_type": payload["runtime_type"],
                        "identity_policy": payload["identity_policy"],
                        "identity_role": payload["identity_role"],
                        "object_ref": payload["object_ref"],
                        "write_mode": payload["write_mode"],
                        "selected_version_id": payload["selected_version_id"],
                        "previous_version_id": payload["previous_version_id"],
                        "source_version_ids": payload["source_version_ids"],
                        "allocation_action": payload["allocation_action"],
                        "return_name": payload["return_name"],
                        "canonical_producer_call_id": payload[
                            "canonical_producer_call_id"
                        ],
                        "valid_scope_id": payload["valid_scope_id"],
                    },
                    step_tokens,
                )
            )
        versions = []
        for version in call.committed_versions:
            payload = version.to_payload()
            versions.append(
                _replace_step_names(
                    {
                        "version_id": payload["version_id"],
                        "valid_scope_id": payload["valid_scope_id"],
                        "producer_call_id": payload["producer_call_id"],
                        "previous_version_id": payload["previous_version_id"],
                        "source_version_ids": payload["source_version_ids"],
                        "result_form": payload["result_form"],
                    },
                    step_tokens,
                )
            )
        authority.append(
            {
                "step": step_tokens[step_id],
                "writes": writes,
                "committed_versions": versions,
            }
        )
    return authority


def _export_value(result, export: Mapping[str, str]) -> Any:
    attempt = result.replay.transactional_attempt_result
    assert attempt is not None
    call = next(
        item
        for item in attempt.execution_report.call_results
        if item.call_id == export["step_id"]
    )
    return_name = export["return"]
    writes = tuple(
        item for item in call.state_writes if item.return_name == return_name
    )
    candidates = tuple(
        item
        for item in call.runtime_results
        if item.output_key == return_name
        or item.output_key.rsplit(".", 1)[-1] == return_name
        or any(
            item.output_key == write.output_key
            or item.produced_handle == write.produced_handle
            for write in writes
        )
    )
    assert len(candidates) == 1
    return macro_standard_output_payload(candidates[0].value)


def test_macro_materialization_matches_independently_authored_function_plan(
    tmp_path,
    monkeypatch,
) -> None:
    case = "tj-2026-heping-yimo-25"
    authored_payload, authored_fragment = _load_explicit_function_plan(case)
    assert all(
        str(step["step_id"]).startswith("llm_")
        and step["capability_id"] != "equal_length_ray_path_reduction"
        for step in authored_fragment["steps"]
    )

    macro_fixture = planning_binding_fixture(tmp_path / "macro", case=case)
    macro = _execute(macro_fixture, load_v3_fixture_payload(case))
    assert macro.checkpoint is not None
    assert macro.checkpoint.all_required_goals_verified
    expansion = macro.macro_expansions[0]

    def forbidden_prepare(*_args, **_kwargs):
        raise AssertionError("an authored Function Plan must not search a Macro")

    monkeypatch.setattr(MacroPreparationService, "prepare", forbidden_prepare)
    authored_fixture = planning_binding_fixture(tmp_path / "authored", case=case)
    authored = _execute(authored_fixture, authored_payload)
    assert authored.checkpoint is not None
    assert authored.checkpoint.all_required_goals_verified
    assert authored.macro_expansions == ()

    macro_ids = tuple(expansion.generated_step_ids)
    authored_ids = tuple(
        str(step["step_id"]) for step in authored_fragment["steps"]
    )
    macro_graph = _fragment_from_result(
        macro,
        macro_ids,
        {
            name: {"step_id": value[0], "return": value[1]}
            for name, value in expansion.export_map.items()
        },
    )
    authored_graph = _fragment_from_result(
        authored,
        authored_ids,
        authored_fragment["exports"],
    )

    assert macro_graph.alpha_normalized_payload() == (
        authored_graph.alpha_normalized_payload()
    )
    assert _alpha_normalized_f5c_graph(macro, macro_ids) == (
        _alpha_normalized_f5c_graph(authored, authored_ids)
    )
    assert _alpha_normalized_conditions(macro, macro_ids) == (
        _alpha_normalized_conditions(authored, authored_ids)
    )
    assert _alpha_normalized_runtime_authority(macro, macro_ids) == (
        _alpha_normalized_runtime_authority(authored, authored_ids)
    )
    macro_export = {
        "step_id": expansion.export_map["minimum_expression"][0],
        "return": expansion.export_map["minimum_expression"][1],
    }
    assert _export_value(macro, macro_export) == _export_value(
        authored,
        authored_fragment["exports"]["minimum_expression"],
    )
