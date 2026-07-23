from __future__ import annotations

from types import SimpleNamespace

from shuxueshuo_server.solver.runtime.functional_input_closure import (
    resolve_functional_input_closure,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    FunctionalCapability,
    FunctionalCapabilityArg,
    FunctionalInputClosureRequirement,
    ResolvedFunctionalValue,
)


class _SemanticIndex:
    views = ()

    def compatible_views(self, **_: object) -> tuple[object, ...]:
        return ()

    def available_refs(self, **_: object) -> tuple[dict[str, str], ...]:
        return (
            {"kind": "line", "ref": "only_visible_line", "value_type": "Line"},
        )


class _Registry:
    def ancestor_scopes(self, scope_id: str) -> tuple[str, ...]:
        return (scope_id, "problem")


def _capability() -> FunctionalCapability:
    return FunctionalCapability(
        capability_id="consume_structured_state",
        kind="macro",
        goal_types=("derive_value",),
        title="consume structured state",
        use_when="a structured state and its evidence are available",
        do_not_use_when=(),
        args=(
            FunctionalCapabilityArg(
                name="structured_state",
                runtime_type="PathTransformation",
                required=True,
                cardinality="one",
                kind="slot_read",
                semantic_role="structured_state",
                accepted_item_types=("PathTransformation",),
                provides_semantic_roles=("trajectory",),
            ),
            FunctionalCapabilityArg(
                name="trajectory",
                runtime_type="Line",
                required=False,
                cardinality="optional",
                kind="slot_read",
                semantic_role="trajectory",
                accepted_item_types=("Line",),
            ),
        ),
        returns=(),
        source=SimpleNamespace(),
        is_pure=True,
        dependency_policy="explicit_args",
        input_closure_requirements=(
            FunctionalInputClosureRequirement(
                semantic_role="trajectory",
                provider_arg_roles=("structured_state",),
                cardinality="one",
                description=(
                    "结构化状态必须包含轨迹依据，或显式提供该轨迹。"
                ),
            ),
        ),
    )


def _provider(**changes: object) -> ResolvedFunctionalValue:
    values = {
        "handle": "fact:s:transformation",
        "runtime_type": "PathTransformation",
        "valid_scope": "s",
        "state_slot_id": "slot:transformation",
        "source_call_id": "build_state",
        "return_name": "structured_state",
        "dependency_object_refs": (),
        "source_state_slot_ids": (),
        "provides_semantic_roles": (),
    }
    values.update(changes)
    return ResolvedFunctionalValue(**values)


def _line() -> ResolvedFunctionalValue:
    return ResolvedFunctionalValue(
        handle="fact:s:trajectory",
        runtime_type="Line",
        valid_scope="s",
        state_slot_id="slot:trajectory",
        source_call_id="build_trajectory",
        return_name="trajectory",
        object_ref="line:s:trajectory",
    )


def test_unrelated_global_unique_state_is_not_used_for_input_closure() -> None:
    result = resolve_functional_input_closure(
        _capability(),
        {"structured_state": (_provider(),)},
        call_id="consume",
        scope_id="s",
        produced={("build_trajectory", "trajectory"): _line()},
        semantic_index=_SemanticIndex(),
        handle_registry=_Registry(),
    )

    assert not result.additions
    assert [item.code for item in result.issues] == [
        "functional.arg_dependency_missing"
    ]
    assert result.issues[0].details is not None
    assert result.issues[0].details["compatible_refs"] == [
        {"kind": "line", "ref": "only_visible_line", "value_type": "Line"}
    ]


def test_provenance_linked_unique_state_closes_optional_input() -> None:
    result = resolve_functional_input_closure(
        _capability(),
        {
            "structured_state": (
                _provider(source_state_slot_ids=("slot:trajectory",)),
            )
        },
        call_id="consume",
        scope_id="s",
        produced={("build_trajectory", "trajectory"): _line()},
        semantic_index=_SemanticIndex(),
        handle_registry=_Registry(),
    )

    assert result.issues == ()
    assert result.additions["trajectory"] == (_line(),)
    assert [item.action for item in result.repairs] == [
        "close_input_dependency"
    ]
    assert not result.reads_closed


def test_return_role_proof_closes_input_without_materializing_extra_arg() -> None:
    result = resolve_functional_input_closure(
        _capability(),
        {
            "structured_state": (
                _provider(provides_semantic_roles=("trajectory",)),
            )
        },
        call_id="consume",
        scope_id="s",
        produced={},
        semantic_index=_SemanticIndex(),
        handle_registry=_Registry(),
    )

    assert result.issues == ()
    assert result.additions == {}
    assert result.reads_closed
