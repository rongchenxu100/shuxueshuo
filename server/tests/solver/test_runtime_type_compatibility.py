from __future__ import annotations

import pytest

from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    _return_satisfies_arg,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    FunctionalCapabilityArg,
    FunctionalCapabilityReturn,
)
from shuxueshuo_server.solver.runtime.runtime_type_compatibility import (
    normalize_runtime_type,
    runtime_type_compatible,
)


@pytest.mark.parametrize(
    ("expected", "actual"),
    (
        ("Constraint", "Condition"),
        ("Condition", "Constraint"),
        ("Point", "PointRef"),
        ("Expression", "Parabola"),
        ("Point", "point_coordinate"),
    ),
)
def test_runtime_type_compatibility_is_shared_by_catalog_and_reconciliation(
    expected: str,
    actual: str,
) -> None:
    assert runtime_type_compatible(expected, actual)


def test_catalog_accepts_condition_return_for_constraint_argument() -> None:
    result = FunctionalCapabilityReturn(
        name="condition",
        runtime_type="Condition",
        required=True,
        cardinality="one",
        state_kind="condition",
        semantic_role="given_relation",
        identity_policy="value_only",
        identity_arg=None,
        write_mode="value",
    )
    arg = FunctionalCapabilityArg(
        name="constraint",
        runtime_type="Constraint",
        required=True,
        cardinality="one",
        kind="condition_read",
        accepted_item_types=("Constraint",),
    )

    assert _return_satisfies_arg(result, arg)
    assert normalize_runtime_type("point_coordinate") == "Point"
