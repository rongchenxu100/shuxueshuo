from types import SimpleNamespace

from shuxueshuo_server.solver.runtime.binding_selector_semantics import (
    expansion_selector_semantics,
    selector_context_binding,
    selector_semantics,
)
from shuxueshuo_server.solver.runtime.functional_plan_graph import (
    canonical_call_aliases,
    rewrite_call_aliases,
    wire_inputs_are_stable,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    CallResultRef,
    FunctionalCall,
    FunctionalPlan,
    FunctionalScope,
    SemanticRef,
)
from shuxueshuo_server.solver.runtime.object_dependencies import (
    expand_object_dependencies,
    structured_object_refs,
)


def _call(
    call_id: str,
    *,
    args: dict[str, tuple[SemanticRef | CallResultRef, ...]],
) -> FunctionalCall:
    return FunctionalCall(
        call_id=call_id,
        capability_id="test_capability",
        args=args,
        return_bindings={},
        strategy="test",
        reason="test",
    )


def test_call_alias_rewrite_resolves_chains_and_drops_alias_nodes() -> None:
    source = _call(
        "source",
        args={"condition": (SemanticRef("given", "fact"),)},
    )
    alias = _call(
        "alias",
        args={"condition": (SemanticRef("given", "fact"),)},
    )
    consumer = _call(
        "consumer",
        args={"value": (CallResultRef("alias", "result"),)},
    )
    plan = FunctionalPlan(
        scopes=(FunctionalScope("i", "i", (source, alias, consumer)),)
    )

    aliases = canonical_call_aliases({"alias": "middle", "middle": "source"})
    rewritten = rewrite_call_aliases(plan, aliases)

    assert aliases == {"alias": "source", "middle": "source"}
    assert [call.call_id for call in rewritten.calls] == ["source", "consumer"]
    ref = rewritten.calls[1].args["value"][0]
    assert isinstance(ref, CallResultRef)
    assert ref.from_call == "source"


def test_wire_stability_uses_dependency_policy_not_capability_id() -> None:
    call = _call(
        "source",
        args={"condition": (SemanticRef("given", "fact"),)},
    )
    explicit = SimpleNamespace(dependency_policy="explicit_args")
    closure = SimpleNamespace(dependency_policy="context_closure")

    assert wire_inputs_are_stable(call, explicit)
    assert not wire_inputs_are_stable(call, closure)


def test_selector_semantics_are_one_descriptor_per_selector_grammar() -> None:
    midpoint = selector_semantics("midpoint:p1")
    endpoint = selector_semantics("straightening_minimum:p1")
    intersection = selector_semantics("intersection:line1_p1")
    expansion = expansion_selector_semantics(
        "distance_parameter_value_if_read"
    )

    assert midpoint.mechanical
    assert midpoint.prerequisite_condition_kind == "midpoint_definition"
    assert endpoint.semantic_roles == ("path_minimum_point_1",)
    assert endpoint.requires_materialized_state
    assert intersection.context_prerequisites == (
        "fact_type:segment_relation",
    )
    assert expansion.arg_resolvers == (
        ("parameter_value", "unique_related_state"),
    )
    assert selector_context_binding("right_angle:anchor") == (
        "condition_object_roles",
        "anchor",
    )
    assert selector_context_binding("path_reduction:relation") == (
        "path_reduction_roles",
        "binding_relation",
    )
    assert selector_context_binding("point_output_ref") is None


def test_structured_object_dependencies_are_shared_and_transitive() -> None:
    payload = {
        "subject": "point:problem:P",
        "relation": ["segment:i:AB", {"angle": "angle:i:ABC"}],
        "description": "point:fake:not parsed from prose",
    }
    refs = structured_object_refs(payload)
    expanded = expand_object_dependencies(
        refs,
        {
            "point:problem:P": ("symbol:problem:t",),
            "symbol:problem:t": ("point:problem:Origin",),
        },
    )

    assert refs == [
        "point:problem:P",
        "segment:i:AB",
        "angle:i:ABC",
    ]
    assert expanded[-2:] == ["symbol:problem:t", "point:problem:Origin"]
