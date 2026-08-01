from __future__ import annotations

from dataclasses import replace

from support.functional_binding_generator import (
    generated_binding_role_scenarios,
    production_binding_outcome,
    reference_binding_outcome,
)


def test_c3_role_authority_generated_gate() -> None:
    scenarios = generated_binding_role_scenarios()
    assert len(scenarios) == 2048
    assert {item.source_profile for item in scenarios} == {
        "wire_state",
        "resolver_state",
        "resolver_identity",
        "compiler_selector",
    }

    failures: list[str] = []
    for scenario in scenarios:
        actual, signature = production_binding_outcome(scenario)
        expected = reference_binding_outcome(scenario)
        if actual != expected:
            failures.append(
                f"{scenario.scenario_id}: expected={expected!r}, actual={actual!r}"
            )
            continue
        renamed = replace(scenario, renamed_call=not scenario.renamed_call)
        _renamed_outcome, renamed_signature = production_binding_outcome(renamed)
        if signature != renamed_signature:
            failures.append(
                f"{scenario.scenario_id}: retry call rename changed binding signature"
            )

    assert not failures, "\n".join(failures[:10])


def test_c3_generated_dimensions_change_typed_source_identity() -> None:
    base = next(
        item
        for item in generated_binding_role_scenarios()
        if item.source_profile == "resolver_state"
        and item.cardinality == "one"
        and item.declared_scope == "ii_1"
        and item.placement_scope == "ii"
        and item.retry_round == 1
        and not item.reverse_wire_order
    )
    base_outcome, _ = production_binding_outcome(base)

    for changed in (
        replace(base, declared_scope="ii_2"),
        replace(base, placement_scope="problem"),
        replace(base, retry_round=2),
    ):
        changed_outcome, _ = production_binding_outcome(changed)
        assert changed_outcome != base_outcome


def test_many_wire_item_order_is_preserved_by_production_builder() -> None:
    base = next(
        item
        for item in generated_binding_role_scenarios()
        if item.source_profile == "wire_state"
        and item.cardinality == "many"
        and not item.reverse_wire_order
    )
    forward, _ = production_binding_outcome(base)
    reverse, _ = production_binding_outcome(
        replace(base, reverse_wire_order=True)
    )

    assert forward != reverse
    assert reverse == reference_binding_outcome(
        replace(base, reverse_wire_order=True)
    )
