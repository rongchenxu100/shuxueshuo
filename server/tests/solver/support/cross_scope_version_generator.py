"""Deterministic scenario generation for the cross-scope version gate."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from itertools import product
import random
from typing import Callable, Iterable, Iterator

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
)


GENERATOR_VERSION = "c0.5/v7"
EXPANDED_SEEDS = (17, 103, 1_009, 65_537)

_TOPOLOGIES = ("root", "parent_child", "siblings", "branched")
_OBJECT_ORIGINS = ("problem", "parent", "child")
_STATE_LOCATIONS = ("parent", "child_1", "siblings")
_WRITE_MODES = ("create", "transition", "value")
_RELATIONSHIPS = (
    "independent",
    "duplicate",
    "refinement",
    "conflict",
)
_DEPENDENCY_KINDS = (
    "call_result",
    "state_version",
    "condition",
    "hidden_semantic_role",
)
_WIRE_ORDERS = ("producer_first", "consumer_first", "interleaved")
_PROJECTIONS = ("object", "answer", "object+answer", "call_local")
_RETRY_MODES = (
    "none",
    "committed_restore",
    "provisional_replacement",
    "version_drift",
)
_READ_MODES = ("none", "exact", "latest", "identity_only", "call_result")


def bounded_scenarios(limit: int = 8_000) -> tuple[CrossScopeVersionScenario, ...]:
    """Return a topology-balanced deterministic sample of the full matrix."""

    scenarios: list[CrossScopeVersionScenario] = []
    remaining_dimensions = tuple(
        product(
            _OBJECT_ORIGINS,
            _STATE_LOCATIONS,
            _WRITE_MODES,
            _RELATIONSHIPS,
            _DEPENDENCY_KINDS,
            _WIRE_ORDERS,
            _PROJECTIONS,
            _RETRY_MODES,
            _READ_MODES,
        )
    )
    per_topology, remainder = divmod(limit, len(_TOPOLOGIES))
    global_index = 0
    for topology_index, topology in enumerate(_TOPOLOGIES):
        target = per_topology + (1 if topology_index < remainder else 0)
        for sample_index in range(target):
            matrix_index = (
                sample_index * len(remaining_dimensions) // target
                + topology_index
            ) % len(remaining_dimensions)
            scenarios.append(
                _bounded_scenario(
                    global_index,
                    topology,
                    *remaining_dimensions[matrix_index],
                )
            )
            global_index += 1
    if len(scenarios) != limit:
        raise AssertionError(
            f"bounded scenario matrix produced {len(scenarios)} cases"
        )
    return tuple(scenarios)


def expanded_scenarios(
    count: int = 2_000,
    *,
    seeds: tuple[int, ...] = EXPANDED_SEEDS,
) -> tuple[CrossScopeVersionScenario, ...]:
    """Generate stable longer DAGs with local pseudo-random choices."""

    per_seed, remainder = divmod(count, len(seeds))
    result: list[CrossScopeVersionScenario] = []
    for seed_index, seed in enumerate(seeds):
        rng = random.Random(seed)
        target = per_seed + (1 if seed_index < remainder else 0)
        for scenario_index in range(target):
            result.append(
                _expanded_scenario(
                    rng,
                    seed=seed,
                    scenario_index=scenario_index,
                )
            )
    return tuple(result)


def generated_scenarios(
    *,
    bounded_count: int = 8_000,
    expanded_count: int = 2_000,
    handoff_count: int = 128,
) -> tuple[CrossScopeVersionScenario, ...]:
    result = (
        *bounded_scenarios(bounded_count),
        *expanded_scenarios(expanded_count),
        *handoff_scenarios(handoff_count),
        *authority_regression_scenarios(),
    )
    ids = {item.scenario_id for item in result}
    if len(ids) != len(result):
        raise AssertionError("generated scenario ids are not unique")
    return result


def handoff_scenarios(
    count: int = 128,
) -> tuple[CrossScopeVersionScenario, ...]:
    """Exercise SemanticRef-to-exact-version publication across siblings."""

    result: list[CrossScopeVersionScenario] = []
    for index in range(count):
        key = ModelStateKey(f"O{index}", "state", "Point")
        read_mode = ("exact", "latest", "identity_only", "call_result")[
            index % 4
        ]
        with_initial = index % 2 == 0
        producer_scope, consumer_scope = (
            ("ii_1", "ii_2") if index % 4 < 2 else ("ii_2", "ii_1")
        )
        initial = (
            ModelVersion(
                version_id=f"{key.token}@problem#0",
                state_key=key,
                storage_scope_id="problem",
                valid_scope_id="problem",
                ordinal=0,
                producer_call_id=None,
                runtime_destination=f"state/problem/{key.object_id}",
                free_symbols=("u",),
            ),
        ) if with_initial else ()
        producer = ModelCall(
            "produce",
            producer_scope,
            "produce_state",
            input_version_ids=(
                (initial[0].version_id,) if with_initial else ()
            ),
            output_state_key=key,
            requested_write_mode=(
                "transition" if with_initial else "create"
            ),
            storage_scope_id=producer_scope,
            valid_scope_id=producer_scope,
            free_symbols=(),
            projection=(
                "object+answer" if index % 3 == 0 else "object"
            ),
            runtime_destination=f"state/{producer_scope}/{key.object_id}",
        )
        consumer = ModelCall(
            "consume",
            consumer_scope,
            "consume_state",
            state_reads=(
                ModelStateRead(
                    read_mode,
                    key,
                    arg_name="input",
                    version_id=(
                        initial[0].version_id
                        if read_mode == "exact" and initial
                        else None
                    ),
                    source_call_id=(
                        "produce" if read_mode == "call_result" else None
                    ),
                ),
            ),
            output_state_key=None,
            requested_write_mode="value",
            projection="call_local",
        )
        result.append(
            CrossScopeVersionScenario(
                scopes=_scopes("branched"),
                objects=(
                    ModelObject(key.object_id, "point", "problem"),
                ),
                initial_versions=initial,
                calls=(producer, consumer),
                wire_order=(
                    ("consume", "produce")
                    if index % 8 >= 4
                    and read_mode in {"latest", "identity_only"}
                    else ("produce", "consume")
                ),
                dimensions=(
                    ("generator", "handoff"),
                    ("read_mode", read_mode),
                    (
                        "bootstrap",
                        "initial" if with_initial else "identity_only",
                    ),
                    ("producer_scope", producer_scope),
                    ("projection", producer.projection),
                ),
                seed=index,
            )
        )
    return tuple(result)


def authority_regression_scenarios() -> tuple[CrossScopeVersionScenario, ...]:
    """Anonymous stage-handoff regressions found by real planner variation."""

    child_key = ModelStateKey("T", "coordinate", "Point")
    child_target = CrossScopeVersionScenario(
        scopes=(
            ModelScope("problem", None),
            ModelScope("ii", "problem"),
        ),
        objects=(ModelObject("T", "point", "ii"),),
        initial_versions=(),
        calls=(
            ModelCall(
                "materialize_child_target",
                "problem",
                "materialize_target",
                output_state_key=child_key,
                requested_write_mode="create",
                projection="object",
                runtime_destination="state/ii/T",
            ),
        ),
        wire_order=("materialize_child_target",),
        dimensions=(
            ("generator", "authority_regression"),
            ("regression", "child_target_declared_in_parent"),
            ("topology", "parent_child"),
            ("read_mode", "identity_only"),
        ),
    )

    curve_key = ModelStateKey("Q", "expression", "Parabola")
    point_key = ModelStateKey("P", "coordinate", "Point")
    sibling_isolation = CrossScopeVersionScenario(
        scopes=(
            ModelScope("problem", None),
            ModelScope("i", "problem"),
            ModelScope("ii", "problem"),
        ),
        objects=(
            ModelObject("Q", "function", "problem"),
            ModelObject("P", "point", "problem"),
        ),
        initial_versions=(),
        calls=(
            ModelCall(
                "closed_branch",
                "i",
                "build_closed_state",
                output_state_key=curve_key,
                requested_write_mode="create",
                storage_scope_id="i",
                valid_scope_id="i",
                projection="answer",
                runtime_destination="state/i/Q",
            ),
            ModelCall(
                "open_branch",
                "ii",
                "build_open_state",
                output_state_key=curve_key,
                requested_write_mode="create",
                storage_scope_id="ii",
                valid_scope_id="ii",
                free_symbols=("u",),
                runtime_destination="state/ii/Q",
            ),
            ModelCall(
                "derive_shared_value",
                "ii",
                "derive_closed_projection",
                input_version_ids=("open_branch",),
                output_state_key=point_key,
                requested_write_mode="create",
                storage_scope_id="ii",
                valid_scope_id="ii",
                runtime_destination="state/problem/P",
            ),
            ModelCall(
                "consume_shared_value",
                "problem",
                "consume_projection",
                input_version_ids=("derive_shared_value",),
                output_state_key=None,
                requested_write_mode="value",
                projection="call_local",
            ),
        ),
        wire_order=(
            "closed_branch",
            "open_branch",
            "derive_shared_value",
            "consume_shared_value",
        ),
        dependency_edges=(
            ModelDependency(
                "open_branch",
                "derive_shared_value",
                "state_version",
                version_id="open_branch",
            ),
            ModelDependency(
                "derive_shared_value",
                "consume_shared_value",
                "call_result",
                version_id="derive_shared_value",
            ),
        ),
        dimensions=(
            ("generator", "authority_regression"),
            ("regression", "sibling_isolated_parent_projection"),
            ("topology", "branched"),
            ("read_mode", "call_result"),
        ),
    )

    source_key = ModelStateKey("S", "coordinate", "Point")
    source_version = ModelVersion(
        f"{source_key.token}@problem#0",
        source_key,
        "problem",
        "problem",
        0,
        None,
        runtime_destination="state/problem/S",
        free_symbols=("u",),
    )
    retry_base = CrossScopeVersionScenario(
        scopes=(
            ModelScope("problem", None),
            ModelScope("ii", "problem"),
        ),
        objects=(ModelObject("S", "point", "problem"),),
        initial_versions=(source_version,),
        calls=(
            ModelCall(
                "close_state",
                "ii",
                "close_state",
                input_version_ids=(source_version.version_id,),
                output_state_key=source_key,
                requested_write_mode="transition",
                storage_scope_id="ii",
                valid_scope_id="ii",
                runtime_destination="state/ii/S",
            ),
            ModelCall(
                "consume_closed_state",
                "ii",
                "consume_state",
                input_version_ids=("close_state",),
                output_state_key=None,
                requested_write_mode="value",
                projection="call_local",
            ),
        ),
        wire_order=("consume_closed_state", "close_state"),
        dependency_edges=(
            ModelDependency(
                "close_state",
                "consume_closed_state",
                "state_version",
                version_id="close_state",
            ),
        ),
        dimensions=(
            ("generator", "authority_regression"),
            ("regression", "checkpoint_wire_reorder_exact_source"),
            ("topology", "parent_child"),
            ("read_mode", "exact"),
        ),
    )
    retry_outcome = ReferenceScopeVersionModel().evaluate(retry_base)
    close_version = retry_outcome.decision("close_state").selected_version_id
    checkpoint_reorder = replace(
        retry_base,
        retry_checkpoint=ModelRetryCheckpoint(
            "committed_restore",
            committed_call_ids=("close_state",),
            committed_version_ids=(
                (close_version,) if close_version is not None else ()
            ),
            provisional_call_ids=("consume_closed_state",),
        ),
        dimensions=(
            *retry_base.dimensions,
            ("retry", "committed_restore"),
        ),
        scenario_id="",
    )
    parameter_key = ModelStateKey("u", "value", "ParameterValue")
    parameter_version = ModelVersion(
        f"{parameter_key.token}@problem#0",
        parameter_key,
        "problem",
        "problem",
        0,
        None,
        runtime_destination="state/problem/u",
    )
    initial_parameter_exact_read = CrossScopeVersionScenario(
        scopes=(
            ModelScope("problem", None),
            ModelScope("i", "problem"),
        ),
        objects=(ModelObject("u", "symbol", "problem"),),
        initial_versions=(parameter_version,),
        calls=(
            ModelCall(
                "evaluate_state",
                "i",
                "evaluate_at_parameter",
                state_reads=(
                    ModelStateRead(
                        "exact",
                        parameter_key,
                        arg_name="parameter_value",
                        version_id=parameter_version.version_id,
                    ),
                ),
                output_state_key=None,
                requested_write_mode="value",
                projection="call_local",
            ),
        ),
        wire_order=("evaluate_state",),
        dimensions=(
            ("generator", "authority_regression"),
            ("regression", "initial_parameter_value_exact_read"),
            ("topology", "parent_child"),
            ("read_mode", "exact"),
        ),
    )

    private_key = ModelStateKey("Q", "expression", "Parabola")
    published_key = ModelStateKey("E", "coordinate", "Point")
    published_state_exact_read = CrossScopeVersionScenario(
        scopes=(
            ModelScope("problem", None),
            ModelScope("ii", "problem"),
            ModelScope("ii_1", "ii"),
            ModelScope("ii_2", "ii"),
        ),
        objects=(
            ModelObject("Q", "function", "problem"),
            ModelObject("E", "point", "ii"),
        ),
        initial_versions=(),
        calls=(
            ModelCall(
                "build_private_state",
                "ii_1",
                "build_private_state",
                output_state_key=private_key,
                requested_write_mode="create",
                storage_scope_id="ii_1",
                valid_scope_id="ii_1",
                runtime_destination="state/ii_1/Q",
            ),
            ModelCall(
                "publish_derived_state",
                "ii_1",
                "publish_derived_state",
                input_version_ids=("build_private_state",),
                output_state_key=published_key,
                requested_write_mode="create",
                storage_scope_id="ii",
                valid_scope_id="ii",
                runtime_destination="state/ii/E",
            ),
            ModelCall(
                "consume_published_state",
                "ii_2",
                "consume_published_state",
                input_version_ids=("publish_derived_state",),
                output_state_key=None,
                requested_write_mode="value",
                projection="call_local",
            ),
        ),
        wire_order=(
            "consume_published_state",
            "publish_derived_state",
            "build_private_state",
        ),
        dependency_edges=(
            ModelDependency(
                "build_private_state",
                "publish_derived_state",
                "hidden_semantic_role",
                version_id="build_private_state",
            ),
            ModelDependency(
                "publish_derived_state",
                "consume_published_state",
                "state_version",
                version_id="publish_derived_state",
            ),
        ),
        dimensions=(
            ("generator", "authority_regression"),
            ("regression", "published_state_exact_read_ignores_transitive_source"),
            ("topology", "branched"),
            ("read_mode", "exact"),
        ),
    )

    return (
        child_target,
        sibling_isolation,
        checkpoint_reorder,
        initial_parameter_exact_read,
        published_state_exact_read,
    )


def dead_writer_liveness_scenarios(
    count: int = 64,
) -> tuple[CrossScopeVersionScenario, ...]:
    """Generate obsolete provisional writers before independent answers."""

    result: list[CrossScopeVersionScenario] = []
    scopes = _scopes("branched")
    for index in range(count):
        scope_id = "ii_1" if index % 2 == 0 else "ii_2"
        key = ModelStateKey(f"L{index}", "state", "Point")
        result.append(
            CrossScopeVersionScenario(
                scopes=scopes,
                objects=(
                    ModelObject(key.object_id, "point", "problem"),
                ),
                initial_versions=(),
                calls=(
                    ModelCall(
                        "provisional",
                        scope_id,
                        "partial_state",
                        output_state_key=key,
                        requested_write_mode="create",
                        storage_scope_id=scope_id,
                        valid_scope_id=scope_id,
                        projection="object",
                        dead=True,
                    ),
                    ModelCall(
                        "answer",
                        scope_id,
                        "independent_answer",
                        output_state_key=key,
                        requested_write_mode="transition",
                        storage_scope_id=scope_id,
                        valid_scope_id=scope_id,
                        projection="answer",
                    ),
                ),
                wire_order=("provisional", "answer"),
                dimensions=(
                    ("generator", "liveness"),
                    ("writer", "obsolete_provisional"),
                    ("scope", scope_id),
                ),
                seed=index,
            )
        )
    return tuple(result)


def dimension_coverage(
    scenarios: Iterable[CrossScopeVersionScenario],
) -> dict[str, dict[str, int]]:
    counters: dict[str, Counter[str]] = {}
    for scenario in scenarios:
        for key, value in scenario.dimensions:
            counters.setdefault(key, Counter())[value] += 1
    return {
        key: dict(sorted(counter.items()))
        for key, counter in sorted(counters.items())
    }


def replay_scenario(
    scenario_id: str,
    *,
    bounded_count: int = 8_000,
    expanded_count: int = 2_000,
) -> CrossScopeVersionScenario:
    return next(
        item
        for item in generated_scenarios(
            bounded_count=bounded_count,
            expanded_count=expanded_count,
        )
        if item.scenario_id == scenario_id
    )


def shrink_candidates(
    scenario: CrossScopeVersionScenario,
) -> Iterator[CrossScopeVersionScenario]:
    """Yield deterministic, progressively smaller diagnostic candidates."""

    required_calls = {
        edge.producer_call_id
        for edge in scenario.dependency_edges
    } | {
        edge.consumer_call_id
        for edge in scenario.dependency_edges
    }
    semantic_keys = {
        read.state_key
        for call in scenario.calls
        for read in call.state_reads
        if read.mode == "latest"
    }
    required_calls.update(
        call.call_id
        for call in scenario.calls
        if call.output_state_key in semantic_keys
    )
    for call in reversed(scenario.calls):
        if call.call_id in required_calls:
            continue
        calls = tuple(
            item for item in scenario.calls if item.call_id != call.call_id
        )
        yield replace(
            scenario,
            calls=calls,
            wire_order=tuple(
                item for item in scenario.wire_order if item != call.call_id
            ),
            scenario_id="",
        )
    if scenario.retry_checkpoint is not None:
        yield replace(
            scenario,
            retry_checkpoint=None,
            scenario_id="",
        )
    answer_free = tuple(
        replace(item, answer_scope_ids=())
        for item in scenario.calls
    )
    if answer_free != scenario.calls:
        yield replace(
            scenario,
            calls=answer_free,
            scenario_id="",
        )


def reduce_scenario(
    scenario: CrossScopeVersionScenario,
    still_fails: Callable[[CrossScopeVersionScenario], bool],
) -> CrossScopeVersionScenario:
    """Greedily minimize a failing scenario in a stable order."""

    current = scenario
    while True:
        replacement = next(
            (
                candidate
                for candidate in shrink_candidates(current)
                if still_fails(candidate)
            ),
            None,
        )
        if replacement is None:
            return current
        current = replacement


def _bounded_scenario(
    index: int,
    topology: str,
    object_origin: str,
    state_location: str,
    write_mode: str,
    relationship: str,
    dependency_kind: str,
    wire_order: str,
    projection: str,
    retry_mode: str,
    requested_read_mode: str,
) -> CrossScopeVersionScenario:
    scopes = _scopes(topology)
    if topology == "root":
        parent_scope = child_1 = child_2 = "problem"
    elif topology == "parent_child":
        parent_scope, child_1, child_2 = "problem", "ii", "ii"
    else:
        parent_scope, child_1, child_2 = "ii", "ii_1", "ii_2"
    origin = {
        "problem": "problem",
        "parent": parent_scope,
        "child": child_1,
    }[object_origin]
    state_scope = {
        "parent": parent_scope,
        "child_1": child_1,
        "siblings": child_1,
    }[state_location]
    # A parent/child scenario must exercise both scope levels. The state
    # location remains independent so child-private bootstrap states still
    # test invalid parent reads.
    producer_scope = (
        parent_scope if topology == "parent_child" else child_1
    )
    key = ModelStateKey("O0", "state", "Point")
    effective_write_mode = (
        "value" if projection == "call_local" else write_mode
    )
    effective_projection = (
        "call_local" if effective_write_mode == "value" else projection
    )
    initial = ModelVersion(
        version_id=f"{key.token}@{state_scope}#0",
        state_key=key,
        storage_scope_id=state_scope,
        valid_scope_id=state_scope,
        ordinal=0,
        producer_call_id=None,
        runtime_destination=f"state/{state_scope}/O0",
        free_symbols=(),
    )
    output_key = None if effective_write_mode == "value" else key
    source_ids = (
        (initial.version_id,)
        if effective_write_mode == "transition"
        or relationship == "refinement"
        else ()
    )
    producer = ModelCall(
        call_id="c0",
        declared_scope_id=producer_scope,
        capability_key="cap_refine" if source_ids else "cap_create",
        input_version_ids=source_ids,
        output_state_key=output_key,
        requested_write_mode=effective_write_mode,
        storage_scope_id=producer_scope,
        valid_scope_id=producer_scope,
        free_symbols=(),
        answer_scope_ids=(
            (producer_scope,) if "answer" in effective_projection else ()
        ),
        projection=effective_projection,
        runtime_destination=f"state/{producer_scope}/O0",
        forced_failure=index % 29 == 0,
    )
    calls = [producer]
    edges: list[ModelDependency] = []
    if relationship != "independent":
        second_scope = (
            child_1
            if topology == "parent_child"
            else (
                child_2
                if state_location == "siblings"
                else child_1
            )
        )
        if relationship == "duplicate":
            capability = producer.capability_key
            second_sources = producer.input_version_ids
            second_mode = producer.requested_write_mode
        elif relationship == "refinement":
            capability = "cap_refine_2"
            second_sources = ("c0",) if output_key is not None else ()
            second_mode = "transition"
        else:
            capability = "cap_conflict"
            second_sources = ()
            second_mode = "create"
        consumer = ModelCall(
            call_id="c1",
            declared_scope_id=second_scope,
            capability_key=capability,
            input_version_ids=second_sources,
            output_state_key=output_key,
            requested_write_mode=second_mode,
            storage_scope_id=second_scope,
            valid_scope_id=second_scope,
            free_symbols=(),
            projection=effective_projection,
            runtime_destination=f"state/{second_scope}/O0",
        )
        calls.append(consumer)
        if relationship == "refinement" and output_key is not None:
            edges.append(
                ModelDependency(
                    producer_call_id="c0",
                    consumer_call_id="c1",
                    kind=dependency_kind,
                    version_id="c0",
                    condition_id=(
                        "K0" if dependency_kind == "condition" else None
                    ),
                    arg_name="input",
                )
            )
    if state_location == "siblings" and child_2 != child_1:
        sibling_initial = replace(
            initial,
            version_id=f"{key.token}@{child_2}#0",
            storage_scope_id=child_2,
            valid_scope_id=child_2,
            runtime_destination=f"state/{child_2}/O0",
        )
        initials = (initial, sibling_initial)
    else:
        initials = (initial,)
    read_mode = requested_read_mode
    if read_mode == "call_result" and output_key is None:
        read_mode = "exact"
    if read_mode != "none":
        calls.append(
            ModelCall(
                call_id="read",
                declared_scope_id=child_2,
                capability_key="cap_read",
                state_reads=(
                    ModelStateRead(
                        read_mode,
                        key,
                        version_id=(
                            initial.version_id
                            if read_mode == "exact"
                            else None
                        ),
                        source_call_id=(
                            "c0" if read_mode == "call_result" else None
                        ),
                    ),
                ),
                output_state_key=None,
                requested_write_mode="value",
                projection="call_local",
            )
        )
    order = tuple(item.call_id for item in calls)
    if wire_order == "consumer_first" and len(order) > 1:
        order = tuple(reversed(order))
    elif wire_order == "interleaved" and len(order) > 1:
        order = (order[-1], *order[:-1])
    scenario = CrossScopeVersionScenario(
        scopes=scopes,
        objects=(ModelObject("O0", "point", origin),),
        initial_versions=initials,
        calls=tuple(calls),
        wire_order=order,
        dependency_edges=tuple(edges),
        dimensions=(
            ("generator", "bounded"),
            ("generator_version", GENERATOR_VERSION),
            ("matrix_index", str(index)),
            ("topology", topology),
            ("object_origin", object_origin),
            ("state_location", state_location),
            ("write_mode", effective_write_mode),
            ("relationship", relationship),
            ("dependency_kind", dependency_kind),
            ("wire_order", wire_order),
            ("projection", effective_projection),
            ("read_mode", read_mode),
        ),
    )
    retry, effective_retry_mode = _retry_checkpoint(
        scenario,
        requested_mode=retry_mode,
    )
    return replace(
        scenario,
        retry_checkpoint=retry,
        dimensions=(
            *scenario.dimensions,
            ("retry", effective_retry_mode),
            (
                "runtime_failure",
                "producer" if producer.forced_failure else "none",
            ),
        ),
        scenario_id="",
    )


def _expanded_scenario(
    rng: random.Random,
    *,
    seed: int,
    scenario_index: int,
) -> CrossScopeVersionScenario:
    scopes = _scopes("branched")
    key_count = rng.randint(2, 3)
    keys = tuple(
        ModelStateKey(f"O{index}", "state", "Point")
        for index in range(key_count)
    )
    objects = tuple(
        ModelObject(key.object_id, "point", "problem") for key in keys
    )
    initials = tuple(
        ModelVersion(
            version_id=f"{key.token}@problem#0",
            state_key=key,
            storage_scope_id="problem",
            valid_scope_id="problem",
            ordinal=0,
            producer_call_id=None,
            runtime_destination=f"state/problem/{key.object_id}",
            free_symbols=(),
        )
        for key in keys
    )
    count = rng.randint(6, 12)
    calls: list[ModelCall] = []
    edges: list[ModelDependency] = []
    latest_token = {
        key.object_id: initial.version_id
        for key, initial in zip(keys, initials, strict=True)
    }
    object_scopes = {
        key.object_id: rng.choice(("ii_1", "ii_2"))
        for key in keys
    }
    last_producer: dict[str, str] = {}
    for call_index in range(count):
        key = rng.choice(keys)
        scope = object_scopes[key.object_id]
        source = latest_token[key.object_id]
        mode = "transition"
        call_id = f"c{call_index}"
        requested_read_mode = _READ_MODES[call_index % len(_READ_MODES)]
        state_reads: tuple[ModelStateRead, ...] = ()
        if requested_read_mode == "exact":
            state_reads = (
                ModelStateRead(
                    "exact",
                    key,
                    version_id=initials[keys.index(key)].version_id,
                ),
            )
        elif requested_read_mode == "latest":
            state_reads = (ModelStateRead("latest", key),)
        elif requested_read_mode == "identity_only":
            state_reads = (ModelStateRead("identity_only", key),)
        elif (
            requested_read_mode == "call_result"
            and key.object_id in last_producer
        ):
            state_reads = (
                ModelStateRead(
                    "call_result",
                    key,
                    source_call_id=last_producer[key.object_id],
                ),
            )
        call = ModelCall(
            call_id=call_id,
            declared_scope_id=scope,
            capability_key=f"cap_{call_index % 4}",
            input_version_ids=(source,) if mode == "transition" else (),
            state_reads=state_reads,
            output_state_key=key,
            requested_write_mode=mode,
            storage_scope_id=scope,
            valid_scope_id=scope,
            free_symbols=(),
            projection=rng.choice(
                ("object", "answer", "object+answer", "call_local")
            ),
            runtime_destination=f"state/{scope}/{key.object_id}",
            forced_failure=False,
        )
        calls.append(call)
        if mode == "transition" and key.object_id in last_producer:
            edges.append(
                ModelDependency(
                    producer_call_id=last_producer[key.object_id],
                    consumer_call_id=call_id,
                    kind=rng.choice(
                        (
                            "call_result",
                            "state_version",
                            "condition",
                            "hidden_semantic_role",
                        )
                    ),
                    version_id=source,
                    arg_name="input",
                )
            )
        latest_token[key.object_id] = call_id
        last_producer[key.object_id] = call_id
    order = [item.call_id for item in calls]
    rng.shuffle(order)
    requested_retry_mode = rng.choice(_RETRY_MODES)
    scenario = CrossScopeVersionScenario(
        scopes=scopes,
        objects=objects,
        initial_versions=initials,
        calls=tuple(calls),
        wire_order=tuple(order),
        dependency_edges=tuple(edges),
        dimensions=(
            (
                ("generator", "expanded"),
                ("generator_version", GENERATOR_VERSION),
                ("seed", str(seed)),
                ("calls", str(count)),
                ("objects", str(key_count)),
            )
            + tuple(
                ("read_mode", mode)
                for mode in sorted(
                    {
                        read.mode
                        for call in calls
                        for read in call.state_reads
                    }
                    or {"none"}
                )
            )
        ),
        seed=seed,
    )
    checkpoint, effective_retry_mode = _retry_checkpoint(
        scenario,
        requested_mode=requested_retry_mode,
    )
    return replace(
        scenario,
        retry_checkpoint=checkpoint,
        dimensions=(
            *scenario.dimensions,
            ("retry", effective_retry_mode),
        ),
        scenario_id="",
    )


def _retry_checkpoint(
    scenario: CrossScopeVersionScenario,
    *,
    requested_mode: str,
) -> tuple[ModelRetryCheckpoint | None, str]:
    if requested_mode == "none":
        return None, "none"
    outcome = ReferenceScopeVersionModel().evaluate(scenario)
    successful_versions = tuple(
        decision
        for decision in outcome.call_decisions
        if decision.canonical_call_id == decision.call_id
        and decision.issue_code is None
        and decision.selected_version_id is not None
    )
    committed_candidates = {
        decision.call_id for decision in successful_versions[:2]
    }
    provisional = tuple(
        item
        for item in outcome.canonical_order
        if item not in committed_candidates
    )[:2]
    if requested_mode in {"committed_restore", "version_drift"}:
        if not successful_versions:
            return None, "none"
        committed = successful_versions[:2]
        return (
            ModelRetryCheckpoint(
                mode=requested_mode,
                committed_call_ids=tuple(
                    item.call_id for item in committed
                ),
                committed_version_ids=tuple(
                    item.selected_version_id
                    for item in committed
                    if item.selected_version_id is not None
                ),
                provisional_call_ids=provisional,
            ),
            requested_mode,
        )
    replacement = provisional[-1:] if provisional else ()
    return (
        ModelRetryCheckpoint(
            mode="provisional_replacement",
            provisional_call_ids=provisional,
            replacement_call_ids=replacement,
        ),
        "provisional_replacement",
    )


def _scopes(topology: str) -> tuple[ModelScope, ...]:
    if topology == "root":
        return (ModelScope("problem", None),)
    if topology == "parent_child":
        return (
            ModelScope("problem", None),
            ModelScope("ii", "problem"),
        )
    if topology == "siblings":
        return (
            ModelScope("problem", None),
            ModelScope("ii", "problem"),
            ModelScope("ii_1", "ii"),
            ModelScope("ii_2", "ii"),
        )
    return (
        ModelScope("problem", None),
        ModelScope("i", "problem"),
        ModelScope("ii", "problem"),
        ModelScope("ii_1", "ii"),
        ModelScope("ii_2", "ii"),
    )
