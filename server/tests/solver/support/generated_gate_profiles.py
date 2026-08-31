from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
import hashlib
from typing import TypeVar


T = TypeVar("T")

FULL_SHARD_COUNT = 8
QUICK_SHARD_COUNT = 4


def stable_bucket(scenario_id: str, shard_count: int = FULL_SHARD_COUNT) -> int:
    if shard_count <= 0:
        raise ValueError("shard_count must be positive")
    digest = hashlib.sha256(scenario_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % shard_count


def select_shard(
    scenarios: Iterable[T],
    shard_index: int,
    *,
    scenario_id: Callable[[T], str],
    shard_count: int = FULL_SHARD_COUNT,
) -> tuple[T, ...]:
    if not 0 <= shard_index < shard_count:
        raise ValueError(
            f"shard_index must be in [0, {shard_count}): {shard_index}"
        )
    return tuple(
        scenario
        for scenario in scenarios
        if stable_bucket(scenario_id(scenario), shard_count) == shard_index
    )


def coverage_first_sample(
    scenarios: Sequence[T],
    limit: int,
    *,
    scenario_id: Callable[[T], str],
    dimensions: Callable[[T], Mapping[str, object]],
    pinned: Callable[[T], bool] | None = None,
) -> tuple[T, ...]:
    if limit <= 0:
        raise ValueError("limit must be positive")
    if len(scenarios) <= limit:
        return tuple(scenarios)

    ordered = sorted(
        scenarios,
        key=lambda item: hashlib.sha256(
            scenario_id(item).encode("utf-8")
        ).hexdigest(),
    )
    selected: list[T] = []
    selected_ids: set[str] = set()
    covered: set[tuple[str, str]] = set()

    def add(item: T) -> None:
        item_id = scenario_id(item)
        if item_id in selected_ids:
            return
        selected.append(item)
        selected_ids.add(item_id)
        covered.update(
            (str(name), str(value))
            for name, value in dimensions(item).items()
        )

    if pinned is not None:
        for scenario in ordered:
            if pinned(scenario):
                add(scenario)
                if len(selected) > limit:
                    raise ValueError(
                        "pinned generated scenarios exceed quick sample limit"
                    )

    for scenario in ordered:
        tokens = {
            (str(name), str(value))
            for name, value in dimensions(scenario).items()
        }
        if tokens - covered:
            add(scenario)
        if len(selected) == limit:
            return tuple(selected)

    for scenario in ordered:
        add(scenario)
        if len(selected) == limit:
            break
    return tuple(selected)


def assert_complete_partition(
    scenarios: Sequence[T],
    *,
    scenario_id: Callable[[T], str],
    shard_count: int = FULL_SHARD_COUNT,
) -> None:
    source_ids = tuple(scenario_id(item) for item in scenarios)
    if len(source_ids) != len(set(source_ids)):
        raise AssertionError("generated scenario ids must be unique")
    partition_ids = tuple(
        scenario_id(item)
        for shard_index in range(shard_count)
        for item in select_shard(
            scenarios,
            shard_index,
            scenario_id=scenario_id,
            shard_count=shard_count,
        )
    )
    if len(partition_ids) != len(source_ids):
        raise AssertionError("generated shard partition changed scenario count")
    if set(partition_ids) != set(source_ids):
        raise AssertionError("generated shard partition is incomplete")
