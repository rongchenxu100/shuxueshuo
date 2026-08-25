from __future__ import annotations

import pytest

from shuxueshuo_server.solver.runtime.functional_subplan import (
    FunctionalPlanFragment,
)
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedDerivedResultRef,
    ScopedFunctionalStep,
    ScopedReturnBinding,
)


pytestmark = pytest.mark.solver_contract


def _fragment(*, source: str, prefix: str, derived_ref: str) -> FunctionalPlanFragment:
    producer_id = f"{prefix}_construct"
    consumer_id = f"{prefix}_verify"
    producer = ScopedFunctionalStep(
        step_id=producer_id,
        capability_id="construct_point_on_ray_at_reference_distance",
        args={"anchor": ("C",), "ray_point": ("D",), "reference_point": ("B",)},
        return_bindings={
            "point": ScopedReturnBinding(kind="derived", ref=derived_ref)
        },
        return_expectations={},
    )
    point = ScopedDerivedResultRef(
        step_id=producer_id,
        return_name="point",
        local_ref=derived_ref,
        canonical_ref=f"ii::{derived_ref}",
        domain_type="Point",
        semantic_role="auxiliary_point",
        owner_scope="ii",
    )
    consumer = ScopedFunctionalStep(
        step_id=consumer_id,
        capability_id="verify_point_on_ray",
        args={"point": (point,), "anchor": ("C",), "ray_point": ("D",)},
        return_bindings={},
        return_expectations={},
    )
    return FunctionalPlanFragment(
        source=source,  # type: ignore[arg-type]
        scope_id="ii",
        steps=(producer, consumer),
        exports={"auxiliary_point": (producer_id, "point")},
        dependency_envelope=("B", "C", "D"),
        blueprint_id="equal-length-ray-transparent/v1",
    )


def test_fragment_round_trip_preserves_typed_derived_refs() -> None:
    fragment = _fragment(
        source="macro",
        prefix="macro",
        derived_ref="macro.point",
    )

    restored = FunctionalPlanFragment.from_payload(fragment.to_payload())

    assert restored.to_payload() == fragment.to_payload()
    assert isinstance(restored.steps[1].args["point"][0], ScopedDerivedResultRef)


def test_macro_and_llm_fragments_share_alpha_normalized_graph_identity() -> None:
    macro = _fragment(
        source="macro",
        prefix="macro",
        derived_ref="macro.point",
    )
    authored = _fragment(
        source="llm",
        prefix="authored",
        derived_ref="G",
    )

    assert macro.fragment_signature == authored.fragment_signature
    assert macro.alpha_normalized_payload() == authored.alpha_normalized_payload()


def test_fragment_rejects_duplicate_step_ids_and_invalid_exports() -> None:
    fragment = _fragment(
        source="macro",
        prefix="macro",
        derived_ref="macro.point",
    )
    with pytest.raises(ValueError, match="step ids must be unique"):
        FunctionalPlanFragment(
            source="macro",
            scope_id="ii",
            steps=(fragment.steps[0], fragment.steps[0]),
            exports={},
        )
    with pytest.raises(ValueError, match="export is invalid"):
        FunctionalPlanFragment(
            source="macro",
            scope_id="ii",
            steps=fragment.steps,
            exports={"value": ("missing", "value")},
        )
