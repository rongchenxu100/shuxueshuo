from __future__ import annotations

from dataclasses import replace
import inspect
import json
from pathlib import Path

import pytest

from support.cross_scope_version_adapters import (
    AdapterMismatch,
    B1AllocationAdapter,
    B2PlacementAdapter,
    B3FinalizationAdapter,
    B4RetryCheckpointAdapter,
    B5bStateReadAdapter,
    C0LogicalGraphAdapter,
    compare_adapter_suite,
    run_production_adapters,
)
from support.cross_scope_version_generator import (
    GENERATOR_VERSION,
    authority_regression_scenarios,
    bounded_scenarios,
    dead_writer_liveness_scenarios,
    expanded_scenarios,
    handoff_scenarios,
    reduce_scenario,
    shrink_candidates,
)
from support.cross_scope_version_oracle import (
    CrossScopeVersionScenario,
    ModelCall,
    ModelDependency,
    ModelObject,
    ModelRetryCheckpoint,
    ModelScope,
    ModelStateRead,
    ModelStateKey,
    ModelVersion,
    ReferenceScopeVersionModel,
    rename_scenario,
)


def _basic_scenario(
    *,
    call_scope: str = "ii_1",
    wire_order: tuple[str, ...] = ("create", "read"),
    projection: str = "object",
) -> CrossScopeVersionScenario:
    key = ModelStateKey("O", "coordinate", "Point")
    initial = ModelVersion(
        "O.coordinate:Point@problem#0",
        key,
        "problem",
        "problem",
        0,
        None,
        runtime_destination="state/problem/O",
        free_symbols=("u",),
    )
    create = ModelCall(
        "create",
        call_scope,
        "close_state",
        (initial.version_id,),
        output_state_key=key,
        requested_write_mode="transition",
        storage_scope_id=call_scope,
        valid_scope_id=call_scope,
        runtime_destination=f"state/{call_scope}/O",
    )
    read = ModelCall(
        "read",
        call_scope,
        "read_state",
        ("create",),
        output_state_key=None,
        requested_write_mode="value",
        projection=projection,
    )
    return CrossScopeVersionScenario(
        scopes=(
            ModelScope("problem", None),
            ModelScope("ii", "problem"),
            ModelScope("ii_1", "ii"),
            ModelScope("ii_2", "ii"),
        ),
        objects=(ModelObject("O", "point", "problem"),),
        initial_versions=(initial,),
        calls=(create, read),
        wire_order=wire_order,
        dependency_edges=(
            ModelDependency(
                "create",
                "read",
                "state_version",
                version_id="create",
            ),
        ),
        dimensions=(("truth", "basic"),),
    )


def _blocked_scenario() -> CrossScopeVersionScenario:
    scenario = _basic_scenario()
    return replace(
        scenario,
        calls=(
            replace(scenario.calls[0], forced_failure=True),
            scenario.calls[1],
        ),
        scenario_id="",
    )


def test_reference_module_is_independent_of_production_runtime() -> None:
    import support.cross_scope_version_oracle as oracle

    source = inspect.getsource(oracle)
    assert "shuxueshuo_server" not in source
    assert "StateAllocationService" not in source
    assert "FunctionalStateReadIndex" not in source


def test_reference_truth_table_for_visibility() -> None:
    scopes = {
        "problem": None,
        "ii": "problem",
        "ii_1": "ii",
        "ii_2": "ii",
    }
    visible = ReferenceScopeVersionModel.is_visible
    assert visible("problem", "ii_1", scopes)
    assert visible("ii", "ii_2", scopes)
    assert visible("ii_1", "ii_1", scopes)
    assert not visible("ii_1", "ii_2", scopes)
    assert not visible("ii_1", "ii", scopes)


def test_reference_truth_table_for_exact_and_latest_reads() -> None:
    scenario = _basic_scenario()
    outcome = ReferenceScopeVersionModel().evaluate(scenario)
    create = outcome.decision("create")
    read = outcome.decision("read")
    assert create.allocation_action == "transition"
    assert create.previous_version_id == "O.coordinate:Point@problem#0"
    assert read.visible_read_version_ids == (create.selected_version_id,)
    assert (
        "ii_1",
        "O.coordinate:Point",
        create.selected_version_id,
    ) in outcome.final_visible_versions
    assert (
        "ii_2",
        "O.coordinate:Point",
        "O.coordinate:Point@problem#0",
    ) in outcome.final_visible_versions


def test_reference_truth_table_for_retry_commit_and_provisional() -> None:
    scenario = _basic_scenario()
    expected = ReferenceScopeVersionModel().evaluate(scenario)
    scenario = replace(
        scenario,
        retry_checkpoint=ModelRetryCheckpoint(
            "provisional_replacement",
            committed_call_ids=("create",),
            committed_version_ids=(
                expected.decision("create").selected_version_id,
            ),
            provisional_call_ids=("read",),
            replacement_call_ids=("read",),
        ),
        scenario_id="",
    )
    outcome = ReferenceScopeVersionModel().evaluate(scenario)
    assert outcome.restored_call_ids == ("create",)
    assert outcome.provisional_call_ids == ()
    assert outcome.committed_version_ids == (
        expected.decision("create").selected_version_id,
    )


def test_reference_reorders_consumer_before_producer_wire() -> None:
    scenario = _basic_scenario(wire_order=("read", "create"))
    outcome = ReferenceScopeVersionModel().evaluate(scenario)
    assert outcome.canonical_order == ("create", "read")


def test_semantic_latest_read_does_not_publish_state_across_siblings() -> None:
    key = ModelStateKey("O", "coordinate", "Point")
    scenario = CrossScopeVersionScenario(
        scopes=(
            ModelScope("problem", None),
            ModelScope("i", "problem"),
            ModelScope("i_1", "i"),
            ModelScope("i_2", "i"),
        ),
        objects=(ModelObject("O", "point", "problem"),),
        initial_versions=(),
        calls=(
            ModelCall(
                "produce",
                "i_1",
                "produce_point",
                output_state_key=key,
                requested_write_mode="create",
                storage_scope_id="i_1",
                valid_scope_id="i_1",
            ),
            ModelCall(
                "consume",
                "i_2",
                "consume_point",
                state_reads=(ModelStateRead("latest", key),),
                output_state_key=None,
                requested_write_mode="value",
                projection="call_local",
            ),
        ),
        wire_order=("produce", "consume"),
        dimensions=(
            ("generator", "handoff"),
            ("read_mode", "semantic_latest"),
        ),
    )

    expected = ReferenceScopeVersionModel().evaluate(scenario)
    actual = run_production_adapters(scenario)

    assert expected.decision("produce").execution_scope_id == "i_1"
    assert expected.decision("produce").return_scope_id == "i_1"
    assert expected.decision("consume").visible_read_version_ids == ()
    assert compare_adapter_suite(expected, actual) == ()
    assert actual.stage("B2").values["consume"]["reads"] == ()


def test_child_exact_source_cannot_publish_result_to_sibling_scope() -> None:
    key = ModelStateKey("O", "coordinate", "Point")
    initial = ModelVersion(
        "O.coordinate:Point@i_1#0",
        key,
        "i_1",
        "i_1",
        0,
        None,
        runtime_destination="state/i_1/O",
    )
    scenario = CrossScopeVersionScenario(
        scopes=(
            ModelScope("problem", None),
            ModelScope("i", "problem"),
            ModelScope("i_1", "i"),
            ModelScope("i_2", "i"),
        ),
        objects=(ModelObject("O", "point", "problem"),),
        initial_versions=(initial,),
        calls=(
            ModelCall(
                "produce",
                "i_1",
                "refine_point",
                input_version_ids=(initial.version_id,),
                output_state_key=key,
                requested_write_mode="transition",
                storage_scope_id="i_1",
                valid_scope_id="i_1",
                answer_scope_ids=("i",),
                projection="object+answer",
                runtime_destination="state/i_1/O",
            ),
            ModelCall(
                "consume",
                "i_2",
                "consume_point",
                state_reads=(
                    ModelStateRead(
                        "call_result",
                        key,
                        source_call_id="produce",
                    ),
                ),
                output_state_key=None,
                requested_write_mode="value",
                projection="call_local",
            ),
        ),
        wire_order=("produce", "consume"),
        dimensions=(("truth", "child_source_publication_boundary"),),
    )

    expected = ReferenceScopeVersionModel().evaluate(scenario)
    actual = run_production_adapters(scenario)

    assert expected.decision("produce").return_scope_id == "i_1"
    assert expected.decision("consume").issue_code == (
        "state.read_version_invisible"
    )
    assert compare_adapter_suite(expected, actual) == ()


def test_reference_exact_read_does_not_upgrade_to_later_version() -> None:
    scenario = _basic_scenario()
    first = scenario.calls[0]
    later = replace(
        first,
        call_id="later",
        input_version_ids=("create",),
        capability_key="close_again",
    )
    scenario = replace(
        scenario,
        calls=(*scenario.calls, later),
        wire_order=("create", "read", "later"),
        dependency_edges=(
            *scenario.dependency_edges,
            ModelDependency("create", "later", "state_version"),
        ),
        scenario_id="",
    )
    outcome = ReferenceScopeVersionModel().evaluate(scenario)
    assert outcome.decision("read").source_version_ids == (
        outcome.decision("create").selected_version_id,
    )
    assert (
        outcome.decision("read").source_version_ids
        != outcome.decision("later").selected_version_id
    )


def test_metamorphic_renaming_preserves_decision_shape() -> None:
    original = _basic_scenario()
    renamed = rename_scenario(original, prefix="R")
    left = ReferenceScopeVersionModel().evaluate(original)
    right = ReferenceScopeVersionModel().evaluate(renamed)
    assert tuple(
        item.allocation_action for item in left.call_decisions
    ) == tuple(item.allocation_action for item in right.call_decisions)
    assert tuple(
        item.issue_code for item in left.call_decisions
    ) == tuple(item.issue_code for item in right.call_decisions)
    assert len(left.final_visible_versions) == len(
        right.final_visible_versions
    )


def test_metamorphic_answer_projection_does_not_change_computation() -> None:
    scenario = _basic_scenario()
    projected = replace(
        scenario,
        calls=tuple(
            replace(item, projection="object+answer")
            for item in scenario.calls
        ),
        scenario_id="",
    )
    left = ReferenceScopeVersionModel().evaluate(scenario)
    right = ReferenceScopeVersionModel().evaluate(projected)
    assert tuple(
        (item.allocation_action, item.previous_version_id)
        for item in left.call_decisions
    ) == tuple(
        (item.allocation_action, item.previous_version_id)
        for item in right.call_decisions
    )


def test_metamorphic_dead_branch_does_not_change_live_branch() -> None:
    scenario = _basic_scenario()
    dead = ModelCall(
        "dead",
        "ii_2",
        "unused",
        output_state_key=None,
        requested_write_mode="value",
        dead=True,
    )
    expanded = replace(
        scenario,
        calls=(*scenario.calls, dead),
        wire_order=(*scenario.wire_order, "dead"),
        scenario_id="",
    )
    left = ReferenceScopeVersionModel().evaluate(scenario)
    right = ReferenceScopeVersionModel().evaluate(expanded)
    assert tuple(
        item for item in right.canonical_order if item != "dead"
    ) == left.canonical_order


def test_all_six_production_adapters_have_independent_stage_outputs() -> None:
    scenario = _basic_scenario()
    suite = run_production_adapters(scenario)
    assert tuple(item.authority for item in suite.stages) == (
        "B1",
        "B2",
        "B3",
        "B4",
        "B5b",
        "C0",
    )
    assert isinstance(B1AllocationAdapter(), B1AllocationAdapter)
    assert isinstance(B2PlacementAdapter(), B2PlacementAdapter)
    assert isinstance(B3FinalizationAdapter(), B3FinalizationAdapter)
    assert isinstance(B4RetryCheckpointAdapter(), B4RetryCheckpointAdapter)
    assert isinstance(B5bStateReadAdapter(), B5bStateReadAdapter)
    assert isinstance(C0LogicalGraphAdapter(), C0LogicalGraphAdapter)
    assert not compare_adapter_suite(
        ReferenceScopeVersionModel().evaluate(scenario),
        suite,
    )


def test_adapter_comparison_detects_mutated_predecessor() -> None:
    scenario = _basic_scenario()
    expected = ReferenceScopeVersionModel().evaluate(scenario)
    suite = run_production_adapters(scenario)
    b1 = suite.stage("B1")
    mutated_values = {
        key: dict(value) for key, value in b1.values.items()
    }
    mutated_values["create"]["previous"] = "wrong#99"
    mutated = replace(
        suite,
        stages=(
            replace(b1, values=mutated_values),
            *suite.stages[1:],
        ),
    )
    mismatch = compare_adapter_suite(expected, mutated)
    assert mismatch == (
        AdapterMismatch(
            "B1",
            "create.previous",
            "O.coordinate:Point@problem#0",
            "wrong#99",
        ),
    )


def test_adapter_comparison_detects_sibling_latest_read_mutation() -> None:
    scenario = _basic_scenario()
    expected = ReferenceScopeVersionModel().evaluate(scenario)
    suite = run_production_adapters(scenario)
    b5 = suite.stage("B5b")
    mutated_latest = dict(b5.values["latest"])
    mutated_latest[("ii_2", "O.coordinate:Point")] = (
        expected.decision("create").selected_version_id
    )
    mutated = replace(
        suite,
        stages=(
            *suite.stages[:4],
            replace(
                b5,
                values={**b5.values, "latest": mutated_latest},
            ),
            suite.stages[5],
        ),
    )
    mismatch = compare_adapter_suite(expected, mutated)
    assert mismatch[0].authority == "B5b"


def test_adapter_comparison_detects_missing_hidden_dependency() -> None:
    scenario = _basic_scenario()
    expected = ReferenceScopeVersionModel().evaluate(scenario)
    suite = run_production_adapters(scenario)
    c0 = suite.stage("C0")
    mutated = replace(
        suite,
        stages=(
            *suite.stages[:5],
            replace(c0, values={**c0.values, "edges": ()}),
        ),
    )
    mismatch = compare_adapter_suite(expected, mutated)
    assert mismatch == (
        AdapterMismatch(
            "C0",
            "dependency_edges",
            (("create", "read", "call_result"),),
            (),
        ),
    )


def test_adapter_comparison_rejects_blocked_precanonical_mutation() -> None:
    scenario = _blocked_scenario()
    expected = ReferenceScopeVersionModel().evaluate(scenario)
    suite = run_production_adapters(scenario)
    assert not compare_adapter_suite(expected, suite)
    assert (
        expected.decision("read").allocation_action
        == "call_local_value"
    )
    b1 = suite.stage("B1")
    values = {key: dict(value) for key, value in b1.values.items()}
    values["read"]["action"] = "create"
    mismatch = compare_adapter_suite(
        expected,
        replace(
            suite,
            stages=(replace(b1, values=values), *suite.stages[1:]),
        ),
    )
    assert mismatch[0].authority == "B1"
    assert mismatch[0].field == "read.action"


def test_adapter_comparison_rejects_missing_dependent_blocking() -> None:
    scenario = _blocked_scenario()
    expected = ReferenceScopeVersionModel().evaluate(scenario)
    suite = run_production_adapters(scenario)
    assert expected.blocked_call_ids == ("read",)
    assert not compare_adapter_suite(expected, suite)
    c0 = suite.stage("C0")
    mutated = replace(
        suite,
        stages=(
            *suite.stages[:5],
            replace(
                c0,
                values={**c0.values, "blocked_call_ids": ()},
            ),
            *suite.stages[6:],
        ),
    )
    mismatch = compare_adapter_suite(expected, mutated)
    assert mismatch[0].authority == "C0"
    assert mismatch[0].field == "blocked_call_ids"


def test_blocking_is_checked_even_when_b3_rejects_graph() -> None:
    scenario = bounded_scenarios(8_000)[2_320]
    expected = ReferenceScopeVersionModel().evaluate(scenario)
    suite = run_production_adapters(scenario)
    assert expected.blocked_call_ids == ("read",)
    assert expected.b3_issue_categories
    assert not compare_adapter_suite(expected, suite)
    c0 = suite.stage("C0")
    mutated = replace(
        suite,
        stages=(
            *suite.stages[:5],
            replace(
                c0,
                values={**c0.values, "blocked_call_ids": ()},
            ),
            *suite.stages[6:],
        ),
    )
    mismatch = compare_adapter_suite(expected, mutated)
    assert mismatch[0].authority == "C0"
    assert mismatch[0].field == "blocked_call_ids"


def test_adapter_comparison_rejects_blocked_b2_mutation() -> None:
    scenario = _blocked_scenario()
    expected = ReferenceScopeVersionModel().evaluate(scenario)
    suite = run_production_adapters(scenario)
    assert not compare_adapter_suite(expected, suite)
    b2 = suite.stage("B2")
    values = {
        call_id: dict(value) for call_id, value in b2.values.items()
    }
    values["read"]["execution_scope"] = "problem"
    mismatch = compare_adapter_suite(
        expected,
        replace(
            suite,
            stages=(
                suite.stages[0],
                replace(b2, values=values),
                *suite.stages[2:],
            ),
        ),
    )
    assert mismatch[0].authority == "B2"
    assert mismatch[0].field == "read.execution_scope"


def test_adapter_comparison_rejects_c0_edge_kind_mutation() -> None:
    scenario = _basic_scenario()
    expected = ReferenceScopeVersionModel().evaluate(scenario)
    suite = run_production_adapters(scenario)
    c0 = suite.stage("C0")
    edges = tuple(
        (producer, consumer, "WRONG_KIND")
        for producer, consumer, _kind in c0.values["edges"]
    )
    mismatch = compare_adapter_suite(
        expected,
        replace(
            suite,
            stages=(
                *suite.stages[:5],
                replace(c0, values={**c0.values, "edges": edges}),
            ),
        ),
    )
    assert mismatch[0].authority == "C0"
    assert mismatch[0].field == "dependency_edges"


def test_adapter_comparison_rejects_c0_issue_mutation() -> None:
    scenario = _basic_scenario()
    expected = ReferenceScopeVersionModel().evaluate(scenario)
    suite = run_production_adapters(scenario)
    c0 = suite.stage("C0")
    mismatch = compare_adapter_suite(
        expected,
        replace(
            suite,
            stages=(
                *suite.stages[:5],
                replace(c0, issue_codes=("logical_graph_cycle",)),
            ),
        ),
    )
    assert mismatch[0] == AdapterMismatch(
        "C0",
        "issues",
        (),
        ("logical_graph_cycle",),
    )


def test_provisional_call_is_not_restored_by_retry_adapter() -> None:
    base = _basic_scenario()
    committed_version = (
        ReferenceScopeVersionModel()
        .evaluate(base)
        .decision("create")
        .selected_version_id
    )
    assert committed_version is not None
    scenario = replace(
        base,
        retry_checkpoint=ModelRetryCheckpoint(
            "provisional_replacement",
            committed_call_ids=("create",),
            committed_version_ids=(committed_version,),
            provisional_call_ids=("read",),
            replacement_call_ids=("read",),
        ),
        scenario_id="",
    )
    expected = ReferenceScopeVersionModel().evaluate(scenario)
    suite = run_production_adapters(scenario)
    assert suite.stage("B4").values["restored_call_ids"] == ("create",)
    assert suite.stage("B4").values["provisional_call_ids"] == ()
    assert not compare_adapter_suite(expected, suite)


def test_retry_adapter_derives_provisional_calls_from_restored_graph() -> None:
    base = _basic_scenario()
    committed_version = (
        ReferenceScopeVersionModel()
        .evaluate(base)
        .decision("create")
        .selected_version_id
    )
    assert committed_version is not None
    scenario = replace(
        base,
        retry_checkpoint=ModelRetryCheckpoint(
            "committed_restore",
            committed_call_ids=("create",),
            committed_version_ids=(committed_version,),
            provisional_call_ids=("ghost",),
        ),
        scenario_id="",
    )
    expected = ReferenceScopeVersionModel().evaluate(scenario)
    suite = run_production_adapters(scenario)
    assert expected.provisional_call_ids == ("read",)
    assert suite.stage("B4").values["provisional_call_ids"] == ("read",)
    assert not compare_adapter_suite(expected, suite)


def test_adapter_comparison_detects_finalizer_mutation() -> None:
    scenario = _basic_scenario()
    expected = ReferenceScopeVersionModel().evaluate(scenario)
    suite = run_production_adapters(scenario)
    b3 = suite.stage("B3")
    mutated = replace(
        suite,
        stages=(
            *suite.stages[:2],
            replace(
                b3,
                issue_codes=("state.transition_source_unresolved",),
            ),
            *suite.stages[3:],
        ),
    )
    mismatch = compare_adapter_suite(expected, mutated)
    assert mismatch[0].authority == "B3"


def test_adapter_comparison_detects_missing_finalizer_issue() -> None:
    scenario = bounded_scenarios(2_261)[2_260]
    expected = ReferenceScopeVersionModel().evaluate(scenario)
    suite = run_production_adapters(scenario)
    assert expected.b3_issue_categories
    assert suite.stage("B3").issue_codes
    b3 = suite.stage("B3")
    mutated = replace(
        suite,
        stages=(
            *suite.stages[:2],
            replace(b3, issue_codes=()),
            *suite.stages[3:],
        ),
    )
    mismatch = compare_adapter_suite(expected, mutated)
    assert mismatch[0].authority == "B3"
    assert mismatch[0].field == "issue_categories"


def test_adapter_comparison_detects_missing_elimination() -> None:
    scenario = dead_writer_liveness_scenarios()[0]
    expected = ReferenceScopeVersionModel().evaluate(scenario)
    suite = run_production_adapters(scenario)
    assert expected.eliminated_call_ids == ("provisional",)
    mutated = replace(
        suite,
        stages=tuple(
            replace(stage, values={**stage.values, "dropped": ()})
            if stage.authority == "Liveness"
            else stage
            for stage in suite.stages
        ),
    )
    mismatch = compare_adapter_suite(expected, mutated)
    assert mismatch[0].authority == "Liveness"
    assert mismatch[0].field == "eliminated_call_ids"


def test_shrinker_is_deterministic_and_removes_retry_first_class_data() -> None:
    scenario = replace(
        _basic_scenario(),
        retry_checkpoint=ModelRetryCheckpoint(
            "provisional_replacement",
            provisional_call_ids=("read",),
        ),
        scenario_id="",
    )
    first = tuple(item.to_payload() for item in shrink_candidates(scenario))
    second = tuple(item.to_payload() for item in shrink_candidates(scenario))
    assert first == second
    assert any(item["retry_checkpoint"] is None for item in first)


def test_reducer_keeps_only_fields_required_to_reproduce_failure() -> None:
    scenario = replace(
        _basic_scenario(),
        retry_checkpoint=ModelRetryCheckpoint(
            "provisional_replacement",
            provisional_call_ids=("read",),
        ),
        scenario_id="",
    )
    reduced = reduce_scenario(
        scenario,
        lambda item: any(call.call_id == "read" for call in item.calls),
    )
    assert reduced.retry_checkpoint is None
    assert tuple(item.call_id for item in reduced.calls) == (
        "create",
        "read",
    )


def test_historical_anonymous_corpus_replays() -> None:
    path = Path(__file__).parent / "fixtures" / (
        "cross_scope_version_failures/historical_scope_version_v1.json"
    )
    payload = json.loads(path.read_text())
    assert payload["generator_version"] == GENERATOR_VERSION
    bounded = bounded_scenarios(8_000)
    expanded = expanded_scenarios(500)
    handoff = handoff_scenarios(128)
    regressions = authority_regression_scenarios()
    for record in payload["scenarios"]:
        cohorts = {
            "bounded": bounded,
            "expanded": expanded,
            "handoff": handoff,
            "authority_regression": regressions,
        }
        scenario = cohorts[record["source"]][record["index"]]
        assert scenario.scenario_id == record["scenario_id"]
        dimensions = dict(scenario.dimensions)
        assert all(
            dimensions.get(key) == value
            for key, value in record.get("expect_dimensions", {}).items()
        ), record["name"]
        expected = ReferenceScopeVersionModel().evaluate(scenario)
        actual = run_production_adapters(scenario)
        assert not compare_adapter_suite(expected, actual), record["name"]
        serialized = json.dumps(scenario.to_payload(), ensure_ascii=True)
        for forbidden in ("Nankai", "Heping", "Hexi", "Xiqing"):
            assert forbidden not in serialized


def test_partial_checkpoint_keeps_state_writer_in_semantic_owner_scope() -> None:
    scenario = authority_regression_scenarios()[5]
    expected = ReferenceScopeVersionModel().evaluate(scenario)
    actual = run_production_adapters(scenario)

    assert not compare_adapter_suite(expected, actual)
    for call_id, version_id in (
        (
            "build_shared_curve",
            "SharedCurve.expression:Parabola@ii_1#1",
        ),
        (
            "derive_shared_point",
            "SharedPoint.coordinate:Point@ii_1#1",
        ),
    ):
        decision = expected.decision(call_id)
        assert decision.execution_scope_id == "ii_1"
        assert decision.return_scope_id == "ii_1"
        assert decision.selected_version_id == version_id
    assert actual.stage("B4").issue_codes == ()


def test_checkpoint_runtime_symbol_representation_uses_typed_identity() -> None:
    alias_scenario, drift_scenario = authority_regression_scenarios()[-2:]
    model = ReferenceScopeVersionModel()

    alias_expected = model.evaluate(alias_scenario)
    alias_actual = run_production_adapters(alias_scenario)
    assert alias_expected.issue_codes == ()
    assert alias_actual.stage("B4").issue_codes == ()
    assert compare_adapter_suite(alias_expected, alias_actual) == ()

    drift_expected = model.evaluate(drift_scenario)
    drift_actual = run_production_adapters(drift_scenario)
    assert "planner.retry_state_version_drift" in drift_expected.issue_codes
    assert drift_actual.stage("B4").issue_codes == (
        "planner.retry_state_version_drift",
    )
    assert compare_adapter_suite(drift_expected, drift_actual) == ()


@pytest.mark.parametrize("bad_import", ["state_identity", "functional_state_reads"])
def test_oracle_source_does_not_import_authority_modules(
    bad_import: str,
) -> None:
    import support.cross_scope_version_oracle as oracle

    assert bad_import not in inspect.getsource(oracle)
