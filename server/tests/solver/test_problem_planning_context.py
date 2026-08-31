from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import re

import pytest
from jsonschema import Draft202012Validator

from shuxueshuo_server.solver.extraction.problem_domain_projection import (
    ProblemDomainProjector,
)
from shuxueshuo_server.solver.extraction.problem_domain import (
    ProblemDraft,
    ProblemPromotionService,
)
from shuxueshuo_server.solver.extraction.problem_domain_validation import (
    ProblemDomainValidator,
)
from shuxueshuo_server.solver.extraction.problem_planning_context import (
    PLANNER_PROBLEM_VIEW_CONTRACT,
    PROBLEM_PLANNING_CONTEXT_CONTRACT,
    ProblemPlanningContextError,
    ProblemPlanningContextProjector,
    _RefCandidate,
    _RuntimeNode,
    _audit_prompt_payload,
    _materialize_ref_authorities,
    planner_problem_view_schema,
)
from shuxueshuo_server.solver.extraction.problem_solver_bundle import (
    ProblemBundleAuthorityToken,
    RuntimeProjectionIndex,
    VerifiedSolverProblemBundle,
    VerifiedSolverProblemBundleLoader,
)

from _problem_planning_support import (
    CASES,
    ROOT,
    accepted_bundle_fixture as _accepted_fixture,
    domain_payload,
)


GOAL_COUNTS = {
    "tj-2026-nankai-yimo-25": 6,
    "tj-2026-heping-ermo-25": 4,
    "tj-2026-xiqing-yimo-25": 3,
    "tj-2026-hexi-yimo-25": 3,
    "tj-2026-heping-yimo-25": 3,
}


def _prompt_scopes(payload: dict) -> tuple[dict, ...]:
    result: list[dict] = []

    def visit(scope: dict) -> None:
        result.append(scope)
        for child in scope.get("children", []):
            visit(child)

    visit(payload["root_scope"])
    return tuple(result)


def _prompt_goals(payload: dict) -> tuple[dict, ...]:
    return tuple(
        goal
        for scope in _prompt_scopes(payload)
        for goal in scope.get("goals", [])
    )


def _planning_fixture(tmp_path: Path, case: str = CASES[0]):
    root, parent, accepted, store, *_ = _accepted_fixture(tmp_path, case=case)
    bundle = VerifiedSolverProblemBundleLoader().load(
        accepted,
        store,
        ancestor_contexts=(root, parent),
    )
    context = ProblemPlanningContextProjector().project(bundle)
    return bundle, context


def _rename_domain_local_ids(scope: dict, inherited: dict[str, str] | None = None) -> None:
    inherited = dict(inherited or {})
    local = {
        entity["id"]: f"src_{entity['id']}"
        for entity in scope["entities"]
    }
    visible = {**inherited, **local}

    def rewrite(value, *, key: str | None = None):
        if isinstance(value, str):
            if key in {
                    "axis",
                    "construction",
                    "kind",
                    "label",
                    "operator",
                    "orientation",
                    "quadrant",
                    "role",
                }:
                return value
            if value in visible:
                return visible[value]
            result = value
            for source, target in sorted(
                visible.items(),
                key=lambda item: len(item[0]),
                reverse=True,
            ):
                result = re.sub(
                    rf"(?<![A-Za-z0-9_]){re.escape(source)}(?![A-Za-z0-9_])",
                    target,
                    result,
                )
            return result
        if isinstance(value, list):
            return [rewrite(item, key=key) for item in value]
        if isinstance(value, dict):
            return {
                item_key: rewrite(item, key=item_key)
                for item_key, item in value.items()
            }
        return value

    scope["entities"] = [rewrite(item) for item in scope["entities"]]
    scope["facts"] = [rewrite(item) for item in scope["facts"]]
    scope["goals"] = [rewrite(item) for item in scope["goals"]]
    for position, child in enumerate(scope["children"], start=1):
        _rename_domain_local_ids(child, visible)
        child["id"] = f"source_part_{position}"
    if inherited == {}:
        scope["id"] = "source_root"


@pytest.mark.parametrize("case", CASES)
def test_five_bundles_project_one_deterministic_context(tmp_path, case) -> None:
    bundle, first = _planning_fixture(tmp_path / case, case)
    second = ProblemPlanningContextProjector().project(
        bundle,
        expected_token=bundle.authority_token,
    )

    assert first.schema_version == PROBLEM_PLANNING_CONTEXT_CONTRACT
    assert first.planning_context_id == second.planning_context_id
    assert first.authority_payload() == second.authority_payload()
    assert first.to_prompt_payload() == second.to_prompt_payload()
    assert first.to_prompt_payload()["schema_version"] == (
        PLANNER_PROBLEM_VIEW_CONTRACT
    )
    assert len(first.goal_views) == GOAL_COUNTS[case]
    assert len(first.goal_views) == sum(
        len(scope.goals)
        for scope in bundle.verified_problem.graph.root_scope.iter_scopes()
    )


@pytest.mark.parametrize("case", CASES)
def test_prompt_view_does_not_depend_on_extraction_local_ids(
    tmp_path,
    case,
) -> None:
    _, expected = _planning_fixture(tmp_path / "expected", case)
    payload = domain_payload(case)
    _rename_domain_local_ids(payload["root"])
    root, parent, accepted, store, *_ = _accepted_fixture(
        tmp_path / "renamed",
        case=case,
        domain_payload_override=payload,
    )
    bundle = VerifiedSolverProblemBundleLoader().load(
        accepted,
        store,
        ancestor_contexts=(root, parent),
    )

    actual = ProblemPlanningContextProjector().project(bundle)

    assert actual.to_prompt_payload() == expected.to_prompt_payload()


def test_goal_views_only_see_owner_scope_and_ancestors(tmp_path) -> None:
    _, context = _planning_fixture(
        tmp_path,
        "tj-2026-heping-ermo-25",
    )
    views = {goal.answer_ref.ref: goal for goal in context.goal_views}

    assert views["i_1.P"].visible_scope_ids == ("problem", "i", "i_1")
    assert views["i_1.A"].visible_scope_ids == ("problem", "i", "i_1")
    assert views["i_2.E"].visible_scope_ids == ("problem", "i", "i_2")
    assert views["ii.E"].visible_scope_ids == ("problem", "ii")
    assert "ii" not in views["i_2.E"].visible_scope_ids
    assert "i_2" not in views["ii.E"].visible_scope_ids


def test_nested_scopes_are_serialized_once(tmp_path) -> None:
    _, context = _planning_fixture(
        tmp_path,
        "tj-2026-heping-ermo-25",
    )
    payload = context.to_prompt_payload()
    scope_ids = [item["id"] for item in _prompt_scopes(payload)]

    assert scope_ids == ["problem", "i", "i_1", "i_2", "ii"]
    assert len(scope_ids) == len(set(scope_ids))
    assert len(_prompt_goals(payload)) == GOAL_COUNTS[context.problem_id]


def test_prompt_items_publish_explicit_lexical_owner_scope(tmp_path) -> None:
    _, context = _planning_fixture(
        tmp_path,
        "tj-2026-heping-yimo-25",
    )
    scopes = _prompt_scopes(context.to_prompt_payload())

    for scope in scopes:
        for collection in ("entities", "facts"):
            for item in scope.get(collection, []):
                assert item["owner_scope"] == scope["id"]

    scope_i = next(scope for scope in scopes if scope["id"] == "i")
    point_on_curve_d = next(
        fact
        for fact in scope_i["facts"]
        if fact.get("point") == "D" and fact.get("curve") == "parabola"
    )
    assert point_on_curve_d["owner_scope"] == "i"


@pytest.mark.parametrize("case", CASES)
def test_prompt_view_embeds_refs_once_and_omits_empty_collections(
    tmp_path,
    case,
) -> None:
    _, context = _planning_fixture(tmp_path / case, case)
    payload = context.to_prompt_payload()
    scopes = _prompt_scopes(payload)
    input_refs = [
        (scope["id"], item["ref"])
        for scope in scopes
        for key in ("entities", "facts")
        for item in scope.get(key, [])
    ]
    goal_refs = [goal["goal_ref"] for goal in _prompt_goals(payload)]
    for goal in _prompt_goals(payload):
        assert "target" not in goal
        if goal["kind"] in {
            "point_coordinate",
            "quadratic_equation",
            "parameter_value",
        }:
            assert isinstance(goal.get("target_ref"), str)
        if goal["kind"] == "minimum_value":
            assert "expression" in goal
            assert "target_ref" not in goal

    assert set(input_refs) == {
        (authority.owner_scope_id, authority.semantic_ref.ref)
        for authority in context.ref_authorities.values()
        if authority.usage == "input"
    }
    assert len(input_refs) == len(set(input_refs))
    assert set(goal_refs) == {
        authority.semantic_ref.ref
        for authority in context.ref_authorities.values()
        if authority.usage == "answer"
    }
    assert len(goal_refs) == len(set(goal_refs))
    for scope in scopes:
        for key in ("entities", "facts", "goals", "children"):
            assert key not in scope or scope[key]
    serialized = json.dumps(payload, ensure_ascii=False)
    for old_field in (
        "available_refs",
        "semantic_reads",
        "identity_only_reads",
        "scope_path",
        "visible_shared_scope_ids",
        "shared_context",
        "goal_views",
    ):
        assert old_field not in serialized


def test_semantic_refs_are_unique_stable_and_source_named(tmp_path) -> None:
    bundle, context = _planning_fixture(
        tmp_path,
        "tj-2026-heping-ermo-25",
    )
    keys = tuple(context.ref_authorities)
    refs = tuple(item.local_ref for item in keys)
    non_scope_runtime_nodes = {
        runtime_id
        for runtime_id in bundle.projection_index.runtime_node_source_units
        if not runtime_id.startswith("scope:")
    }

    assert len(keys) == len(set(keys))
    assert {item.runtime_node_id for item in context.ref_authorities.values()} == (
        non_scope_runtime_nodes
    )
    assert {"A", "B", "b", "C", "c", "parabola"}.issubset(refs)
    assert {"i_1.P", "i_1.A", "i_2.E", "ii.E"}.issubset(refs)
    assert not any(":" in ref for ref in refs)
    assert not any(
        "." in item.local_ref
        for item in keys
        if item.kind != "answer"
    )
    assert not any(re.search(r"_[0-9a-f]{12,}$", ref) for ref in refs)
    assert "square_center_h_square_ae_a_e_k_g" in refs


def test_scope_local_ref_allows_siblings_but_rejects_ancestor_shadow() -> None:
    def candidate(scope_id: str, runtime_id: str) -> _RefCandidate:
        return _RefCandidate(
            runtime_node=_RuntimeNode(
                runtime_node_id=runtime_id,
                node_kind="entity",
                owner_scope_id=scope_id,
                payload={"kind": "point", "ref": "A"},
            ),
            base_ref="A",
            kind="point",
            value_type=None,
            source_unit_ids=(f"unit:{scope_id}:A",),
            usage="input",
        )

    sibling_authorities = _materialize_ref_authorities(
        (candidate("i", "point:i:A"), candidate("ii", "point:ii:A")),
        visible_goals_by_scope={"i": ("goal:i",), "ii": ("goal:ii",)},
        scope_paths={"i": ("problem", "i"), "ii": ("problem", "ii")},
    )
    assert {(key.owner_scope_id, key.local_ref) for key in sibling_authorities} == {
        ("i", "A"),
        ("ii", "A"),
    }

    with pytest.raises(ProblemPlanningContextError) as error:
        _materialize_ref_authorities(
            (
                candidate("problem", "point:problem:A"),
                candidate("i", "point:i:A"),
            ),
            visible_goals_by_scope={
                "problem": ("goal:i",),
                "i": ("goal:i",),
            },
            scope_paths={
                "problem": ("problem",),
                "i": ("problem", "i"),
            },
        )

    assert error.value.code == "planner.problem_planning_ref_ambiguous"


def test_entity_fact_and_goal_array_reordering_does_not_drift_context(
    tmp_path,
) -> None:
    bundle, original = _planning_fixture(
        tmp_path,
        "tj-2026-heping-ermo-25",
    )

    def reordered_scope(scope):
        return replace(
            scope,
            entities=tuple(reversed(scope.entities)),
            facts=tuple(reversed(scope.facts)),
            goals=tuple(reversed(scope.goals)),
            children=tuple(reordered_scope(child) for child in scope.children),
        )

    reordered_graph = replace(
        bundle.verified_problem.graph,
        root_scope=reordered_scope(bundle.verified_problem.graph.root_scope),
    )
    validation = ProblemDomainValidator().validate(
        ProblemDraft.from_graph(
            reordered_graph,
            parent_revision_id=bundle.verified_problem.parent_revision_id,
        )
    )
    assert validation.report.ok
    reordered_verified = ProblemPromotionService().promote(validation.draft)
    assert reordered_verified.revision_id == bundle.verified_problem.revision_id

    reordered = ProblemPlanningContextProjector().project(
        replace(bundle, verified_problem=reordered_verified)
    )

    assert reordered.planning_context_id == original.planning_context_id
    assert reordered.authority_payload() == original.authority_payload()


def test_answer_refs_are_not_input_refs_or_cross_goal_visible(tmp_path) -> None:
    _, context = _planning_fixture(tmp_path)
    scope_refs = {
        ref.ref for scope in context.scopes for ref in scope.available_refs
    }
    answer_authorities = [
        item for item in context.ref_authorities.values() if item.usage == "answer"
    ]

    assert len(answer_authorities) == len(context.goal_views)
    assert all(item.semantic_ref.ref not in scope_refs for item in answer_authorities)
    assert all(len(item.visible_goal_unit_ids) == 1 for item in answer_authorities)
    for goal in context.goal_views:
        authority = context.answer_authority_for_goal(goal.goal_unit_id)
        assert authority.visible_goal_unit_ids == (goal.goal_unit_id,)


def test_goal_scoped_authority_api_is_the_only_complete_binding_catalog(
    tmp_path,
) -> None:
    _, context = _planning_fixture(
        tmp_path,
        "tj-2026-heping-ermo-25",
    )
    views = {item.answer_ref.ref: item for item in context.goal_views}
    i_2 = views["i_2.E"]
    ii = views["ii.E"]
    i_2_refs = {
        item.semantic_ref.ref
        for item in context.input_authorities_for_goal(i_2.goal_unit_id)
    }
    ii_refs = {
        item.semantic_ref.ref
        for item in context.input_authorities_for_goal(ii.goal_unit_id)
    }

    assert i_2_refs == {item.ref for item in i_2.semantic_reads}
    assert ii_refs == {item.ref for item in ii.semantic_reads}
    assert "point_on_curve_parabola_g" in i_2_refs
    assert "point_on_curve_parabola_g" not in ii_refs
    assert "minimum_value" in ii_refs
    assert "minimum_value" not in i_2_refs
    assert context.answer_authority_for_goal(i_2.goal_unit_id).semantic_ref == (
        i_2.answer_ref
    )


def test_sibling_facts_do_not_enter_another_goal_prompt_slice(tmp_path) -> None:
    _, context = _planning_fixture(
        tmp_path,
        "tj-2026-heping-ermo-25",
    )
    goals = {item.answer_ref.ref: item for item in context.goal_views}

    def visible_fact_refs(answer_ref: str) -> set[str]:
        payload = context.to_prompt_payload(
            goal_unit_ids=(goals[answer_ref].goal_unit_id,),
        )
        return {
            str(fact["ref"])
            for scope in _prompt_scopes(payload)
            for fact in scope.get("facts", [])
        }

    i_2_facts = visible_fact_refs("i_2.E")
    ii_facts = visible_fact_refs("ii.E")
    assert "point_on_curve_parabola_g" in i_2_facts
    assert "minimum_value" not in i_2_facts
    assert "minimum_value" in ii_facts
    assert "point_on_curve_parabola_g" not in ii_facts


@pytest.mark.parametrize("case", CASES)
def test_source_units_and_runtime_nodes_have_complete_coverage(tmp_path, case) -> None:
    bundle, context = _planning_fixture(tmp_path / case, case)
    represented_source_units = {
        scope.source_scope_unit_id for scope in context.scopes
    }
    represented_source_units.update(
        item.source_unit_id
        for scope in context.scopes
        for item in (*scope.entities, *scope.facts)
    )
    represented_source_units.update(goal.goal_unit_id for goal in context.goal_views)
    expected_source_units = {
        item["unit_id"]
        for item in bundle.verified_problem.to_payload()["unit_registry"]
        if item["unit_kind"] != "family"
    }

    assert represented_source_units == expected_source_units
    assert set(bundle.projection_index.scope_runtime_id_by_unit) == {
        scope.source_scope_unit_id for scope in context.scopes
    }
    assert {
        item.runtime_node_id for item in context.ref_authorities.values()
    } | {
        f"scope:{scope.scope_id}" for scope in context.scopes
    } == set(bundle.projection_index.runtime_node_source_units)


def test_folded_facts_remain_in_source_view_without_duplicate_runtime_refs(
    tmp_path,
) -> None:
    bundle, context = _planning_fixture(
        tmp_path,
        "tj-2026-heping-yimo-25",
    )
    source_fact_units = {
        item.source_unit_id: item.to_prompt_payload()
        for scope in context.scopes
        for item in scope.facts
    }
    folded = [
        fact
        for scope in bundle.verified_problem.graph.root_scope.iter_scopes()
        for fact in scope.facts
        if fact.kind in {"function_expression", "point_construction"}
    ]

    assert folded
    assert all(fact.unit_id in source_fact_units for fact in folded)
    runtime_ref_counts = [
        sum(
            authority.runtime_node_id == runtime_id
            for authority in context.ref_authorities.values()
        )
        for fact in folded
        for runtime_id in bundle.projection_index.source_unit_runtime_nodes[fact.unit_id]
        if not runtime_id.startswith("scope:")
    ]
    assert runtime_ref_counts and set(runtime_ref_counts) == {1}


def test_combined_fact_keeps_one_to_many_runtime_provenance(tmp_path) -> None:
    bundle, context = _planning_fixture(
        tmp_path,
        "tj-2026-nankai-yimo-25",
    )
    fact_units = {
        item["unit_id"]
        for item in bundle.verified_problem.to_payload()["unit_registry"]
        if item["unit_kind"] == "fact"
    }
    combined = [
        unit_id
        for unit_id in fact_units
        if len(bundle.projection_index.source_unit_runtime_nodes[unit_id]) > 1
    ]

    assert combined
    for unit_id in combined:
        runtime_nodes = set(bundle.projection_index.source_unit_runtime_nodes[unit_id])
        covered = {
            authority.runtime_node_id
            for authority in context.ref_authorities.values()
            if unit_id in authority.source_unit_ids
        }
        assert runtime_nodes.issubset(covered)


def test_prompt_payload_contains_no_internal_authority_identity(tmp_path) -> None:
    bundle, context = _planning_fixture(tmp_path)
    payload_text = json.dumps(
        context.to_prompt_payload(),
        ensure_ascii=False,
        sort_keys=True,
    )

    assert bundle.authority_token.bundle_id not in payload_text
    assert bundle.authority_token.extraction_context_id not in payload_text
    for artifact in bundle.artifact_refs.authority_payload().values():
        assert artifact["artifact_id"] not in payload_text
    for item in bundle.verified_problem.to_payload()["unit_registry"]:
        if item["unit_kind"] != "family":
            assert item["unit_id"] not in payload_text
    for runtime_id in bundle.projection_index.runtime_node_source_units:
        assert runtime_id not in payload_text
    assert "MathObjectId" not in payload_text
    assert "StateVersionId" not in payload_text


def test_prompt_audit_rejects_internal_identity_hidden_in_a_value(tmp_path) -> None:
    bundle, context = _planning_fixture(tmp_path)
    payload = context.to_prompt_payload()
    runtime_id = next(iter(bundle.projection_index.runtime_node_source_units))
    payload["root_scope"]["entities"][0]["kind"] = runtime_id

    with pytest.raises(ProblemPlanningContextError) as error:
        _audit_prompt_payload(payload, forbidden_values={runtime_id})

    assert error.value.code == "planner.problem_planning_context_invalid"


def test_expected_bundle_token_drift_fails_loud(tmp_path) -> None:
    bundle, _ = _planning_fixture(tmp_path)
    stale = replace(bundle.authority_token, bundle_id="stale")

    with pytest.raises(ProblemPlanningContextError) as error:
        ProblemPlanningContextProjector().project(bundle, expected_token=stale)

    assert error.value.code == "planner.problem_revision_drift"


def test_missing_goal_mapping_fails_loud(tmp_path) -> None:
    bundle, _ = _planning_fixture(tmp_path)
    goal_map = dict(bundle.projection_index.goal_answer_handle_by_unit)
    goal_map.pop(next(iter(goal_map)))
    index = replace(bundle.projection_index, goal_answer_handle_by_unit=goal_map)

    with pytest.raises(ProblemPlanningContextError) as error:
        ProblemPlanningContextProjector().project(
            replace(bundle, projection_index=index)
        )

    assert error.value.code == "planner.problem_planning_projection_drift"


def test_missing_runtime_node_mapping_fails_loud(tmp_path) -> None:
    bundle, _ = _planning_fixture(tmp_path)
    forward = dict(bundle.projection_index.runtime_node_source_units)
    runtime_id = next(key for key in forward if not key.startswith("scope:"))
    forward.pop(runtime_id)
    reverse = {
        source_id: tuple(item for item in runtime_ids if item != runtime_id)
        for source_id, runtime_ids in bundle.projection_index.source_unit_runtime_nodes.items()
    }
    index = replace(
        bundle.projection_index,
        runtime_node_source_units=forward,
        source_unit_runtime_nodes=reverse,
    )

    with pytest.raises(ProblemPlanningContextError) as error:
        ProblemPlanningContextProjector().project(
            replace(bundle, projection_index=index)
        )

    assert error.value.code == "planner.problem_planning_projection_drift"


def test_cross_sibling_source_mapping_fails_loud(tmp_path) -> None:
    bundle, _ = _planning_fixture(
        tmp_path,
        "tj-2026-nankai-yimo-25",
    )
    registry = {
        item["unit_id"]: item
        for item in bundle.verified_problem.to_payload()["unit_registry"]
    }
    source_unit_id = next(
        unit_id
        for unit_id, item in registry.items()
        if item["scope_path"].endswith("/ii_2") and item["unit_kind"] == "fact"
    )
    runtime_id = next(
        runtime_id
        for runtime_id, source_ids in bundle.projection_index.runtime_node_source_units.items()
        if any(registry[item]["scope_path"].endswith("/ii_1") for item in source_ids)
        and not runtime_id.startswith(("scope:", "answer:"))
    )
    forward = dict(bundle.projection_index.runtime_node_source_units)
    forward[runtime_id] = tuple(sorted((*forward[runtime_id], source_unit_id)))
    reverse = dict(bundle.projection_index.source_unit_runtime_nodes)
    reverse[source_unit_id] = tuple(sorted((*reverse[source_unit_id], runtime_id)))
    index = RuntimeProjectionIndex(
        runtime_node_source_units=forward,
        source_unit_runtime_nodes=reverse,
        scope_runtime_id_by_unit=bundle.projection_index.scope_runtime_id_by_unit,
        goal_answer_handle_by_unit=bundle.projection_index.goal_answer_handle_by_unit,
        value_object_handles=bundle.projection_index.value_object_handles,
    )

    with pytest.raises(ProblemPlanningContextError) as error:
        ProblemPlanningContextProjector().project(
            replace(bundle, projection_index=index)
        )

    assert error.value.code == "planner.problem_scope_visibility_drift"


def test_context_is_recursively_immutable_and_prompt_is_a_copy(tmp_path) -> None:
    _, context = _planning_fixture(tmp_path)
    prompt = context.to_prompt_payload()
    prompt["source"]["question_number"] = "changed"

    assert context.source["question_number"] == "25"
    with pytest.raises(TypeError):
        context.source["question_number"] = "changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        context.ref_authorities[next(iter(context.ref_authorities))] = next(  # type: ignore[index]
            iter(context.ref_authorities.values())
        )


def test_child_scope_order_is_semantic(tmp_path) -> None:
    bundle, original = _planning_fixture(
        tmp_path,
        "tj-2026-heping-ermo-25",
    )
    root = bundle.verified_problem.graph.root_scope
    assert len(root.children) > 1
    reordered_graph = replace(
        bundle.verified_problem.graph,
        root_scope=replace(root, children=tuple(reversed(root.children))),
    )
    validation = ProblemDomainValidator().validate(
        ProblemDraft.from_graph(
            reordered_graph,
            parent_revision_id=bundle.verified_problem.parent_revision_id,
        )
    )
    assert validation.report.ok
    reordered_verified = ProblemPromotionService().promote(validation.draft)
    assert reordered_verified.semantic_hash != bundle.verified_problem.semantic_hash

    reordered = ProblemPlanningContextProjector().project(
        replace(bundle, verified_problem=reordered_verified)
    )

    assert reordered.planning_context_id != original.planning_context_id


def test_prompt_schema_snapshot_matches_runtime_and_validates_five_cases(
    tmp_path,
) -> None:
    runtime_schema = planner_problem_view_schema()
    checked_in = json.loads(
        (
            ROOT
            / "internal/schemas/planner-problem-view.schema.json"
        ).read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(runtime_schema)

    assert checked_in == runtime_schema
    validator = Draft202012Validator(runtime_schema)
    for case in CASES:
        _, context = _planning_fixture(tmp_path / case, case)
        assert list(validator.iter_errors(context.to_prompt_payload())) == []

    _, context = _planning_fixture(tmp_path / "legacy-target", CASES[-1])
    legacy = context.to_prompt_payload()
    goal = _prompt_goals(legacy)[0]
    goal["target"] = goal.pop("target_ref")
    errors = list(validator.iter_errors(legacy))
    assert errors
    assert any("target_ref" in error.message for error in errors)
    assert any("Additional properties" in error.message for error in errors)


def test_projection_does_not_call_runtime_or_generation_services(
    tmp_path,
    monkeypatch,
) -> None:
    bundle, _ = _planning_fixture(tmp_path)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("F5-B projector called a forbidden service")

    monkeypatch.setattr(ProblemDomainProjector, "project", forbidden)
    monkeypatch.setattr(ProblemDomainValidator, "validate", forbidden)
    monkeypatch.setattr(VerifiedSolverProblemBundle, "build_solver_problem", forbidden)

    projected = ProblemPlanningContextProjector().project(bundle)

    assert projected.problem_id == bundle.verified_problem.graph.problem_id


def test_authority_token_type_remains_bundle_native(tmp_path) -> None:
    bundle, context = _planning_fixture(tmp_path)

    assert isinstance(context.bundle_authority_token, ProblemBundleAuthorityToken)
    assert context.bundle_authority_token == bundle.authority_token
    assert context.problem_revision_id == bundle.authority_token.problem_revision_id
    assert context.problem_semantic_hash == bundle.authority_token.problem_semantic_hash
    authority = context.authority_payload()
    assert authority["problem_revision_id"] == context.problem_revision_id
    assert authority["problem_semantic_hash"] == context.problem_semantic_hash
