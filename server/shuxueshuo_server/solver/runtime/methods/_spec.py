"""MethodSpec 的代码源。

MethodSpec JSON 不再手写维护，而是从每个 method 文件里的 ``SPEC`` 生成。
``description`` 默认取 method class 的 docstring 首段，因此 method 的能力说明会和
代码注释待在一起。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import inspect

from shuxueshuo_server.solver.contracts import (
    CanonicalSymbolDerivationSpec,
    MethodInputBindingSpec,
    MethodExplanationSpec,
    MethodInputRelationSpec,
    MethodInputViewMode,
    MethodCompanionOutputSpec,
    MethodOutputActivationSpec,
    MethodVisualSpec,
    PlanTransformerScope,
    PredicatePublicationSpec,
    ScalarResultFormSpec,
    SymbolicClosureSpec,
    TrialErrorHintSpec,
)
from shuxueshuo_server.solver.runtime.method_input_contracts import (
    validate_interchangeable_input_groups,
)


class MethodSpecContractError(RuntimeError):
    """A code-authored MethodSpec is internally inconsistent."""


def canonical_symbol_input(symbol_name: str) -> dict[str, Any]:
    """Declare one required Symbol identity owned by a typed derivation."""

    return {
        "type": "Symbol",
        "required": True,
        "binding": MethodInputBindingSpec(
            input_name=symbol_name,
            derivation=CanonicalSymbolDerivationSpec(symbol_name),
        ),
    }


def declare_input_views(
    *,
    identity: tuple[str, ...] = (),
    latest_state: tuple[str, ...] = (),
    immutable_value: tuple[str, ...] = (),
    exact_result: tuple[str, ...] = (),
) -> dict[str, MethodInputViewMode]:
    """Declare every Method input view without name/type inference."""

    result: dict[str, MethodInputViewMode] = {}
    for mode, names in (
        ("identity", identity),
        ("latest_state", latest_state),
        ("immutable_value", immutable_value),
        ("exact_result", exact_result),
    ):
        for name in names:
            if name in result:
                raise MethodSpecContractError(
                    f"duplicate Method input view declaration: {name}"
                )
            result[name] = mode
    return result


@dataclass(frozen=True)
class MethodSpecSource:
    """一个 method 文件内的结构化 MethodSpec 源。

    ``method_cls`` 提供 method_id 和 docstring；其他字段提供 validator 需要的
    输入、输出、solves 和前后置条件。
    """

    method_cls: type
    title: str
    solves: tuple[str, ...]
    inputs: dict[str, dict[str, Any]]
    input_views: dict[str, MethodInputViewMode]
    outputs: dict[str, str]
    companion_outputs: tuple[MethodCompanionOutputSpec, ...] = ()
    predicate_publications: tuple[PredicatePublicationSpec, ...] = ()
    input_relations: tuple[MethodInputRelationSpec, ...] = ()
    internal_outputs: tuple[str, ...] = ()
    output_activation: dict[str, MethodOutputActivationSpec] = field(
        default_factory=dict
    )
    scalar_result_forms: dict[str, ScalarResultFormSpec] = field(default_factory=dict)
    preconditions: tuple[str, ...] = ()
    postconditions: tuple[str, ...] = ()
    trace_template: tuple[str, ...] = ()
    repair_hints: tuple[dict[str, Any], ...] = ()
    trial_error_hints: tuple[TrialErrorHintSpec, ...] = ()
    repair_feedback_provider_id: str | None = None
    geometry_profiles: tuple[dict[str, Any], ...] = ()
    explanation: MethodExplanationSpec | None = None
    visual: MethodVisualSpec | None = None
    description: str = ""
    summary: str = ""
    do_not_use_when: tuple[str, ...] = ()
    constraint_analyzer: str | None = None
    plan_transformer: str | None = None
    plan_transformer_scope: PlanTransformerScope = "single_invocation"
    reconciliation_validators: tuple[str, ...] = ()
    distinct_arg_groups: tuple[tuple[str, ...], ...] = ()
    interchangeable_arg_groups: tuple[tuple[str, ...], ...] = ()
    symbolic_closure: SymbolicClosureSpec | None = None
    # This source type is reserved for runtime/stateless methods. Stateful
    # implementations must opt out so liveness analysis cannot delete them.
    is_pure: bool = True

    @property
    def method_id(self) -> str:
        return str(self.method_cls.method_id)

    def to_payload(self) -> dict[str, Any]:
        description = self.description or _first_docstring_paragraph(self.method_cls)
        inputs = _input_payloads(self.inputs, self.input_views)
        payload: dict[str, Any] = {
            "method_id": self.method_id,
            "title": self.title,
            "description": description,
            "summary": self.summary,
            "solves": list(self.solves),
            "inputs": inputs,
            "outputs": self.outputs,
            "is_pure": self.is_pure,
        }
        if self.companion_outputs:
            _validate_companion_outputs(
                self.companion_outputs,
                output_names=frozenset(self.outputs),
                activated_output_names=frozenset(self.output_activation),
            )
            payload["companion_outputs"] = [
                item.to_payload() for item in self.companion_outputs
            ]
        if self.predicate_publications:
            _validate_predicate_publications(
                self.predicate_publications,
                input_names=frozenset(self.inputs),
                outputs=self.outputs,
            )
            payload["predicate_publications"] = [
                item.to_payload() for item in self.predicate_publications
            ]
        if self.internal_outputs:
            payload["internal_outputs"] = list(self.internal_outputs)
        if self.input_relations:
            _validate_input_relations(
                self.input_relations,
                input_names=frozenset(self.inputs),
            )
            payload["input_relations"] = [
                item.to_payload() for item in self.input_relations
            ]
        if self.output_activation:
            payload["output_activation"] = {
                name: spec.to_payload()
                for name, spec in self.output_activation.items()
            }
        if self.scalar_result_forms:
            payload["scalar_result_forms"] = {
                name: spec.to_payload()
                for name, spec in self.scalar_result_forms.items()
            }
        if self.preconditions:
            payload["preconditions"] = list(self.preconditions)
        if self.do_not_use_when:
            payload["do_not_use_when"] = list(self.do_not_use_when)
        if self.postconditions:
            payload["postconditions"] = list(self.postconditions)
        if self.trace_template:
            payload["trace_template"] = list(self.trace_template)
        if self.repair_hints:
            payload["repair_hints"] = [
                _json_ready_hint(item) for item in self.repair_hints
            ]
        if self.trial_error_hints:
            payload["trial_error_hints"] = [
                item.to_payload() for item in self.trial_error_hints
            ]
        if self.repair_feedback_provider_id is not None:
            payload["repair_feedback_provider_id"] = (
                self.repair_feedback_provider_id
            )
        if self.geometry_profiles:
            payload["geometry_profiles"] = [
                _json_ready_hint(item) for item in self.geometry_profiles
            ]
        if self.explanation is not None:
            payload["explanation"] = _json_ready_explanation(self.explanation)
        if self.visual is not None:
            payload["visual"] = _json_ready_visual(self.visual)
        if self.constraint_analyzer is not None:
            payload["constraint_analyzer"] = self.constraint_analyzer
        if self.plan_transformer is not None:
            payload["plan_transformer"] = self.plan_transformer
            payload["plan_transformer_scope"] = self.plan_transformer_scope
        if self.reconciliation_validators:
            payload["reconciliation_validators"] = list(
                self.reconciliation_validators
            )
        if self.distinct_arg_groups:
            payload["distinct_arg_groups"] = [
                list(group) for group in self.distinct_arg_groups
            ]
        if self.interchangeable_arg_groups:
            validate_interchangeable_input_groups(
                self.interchangeable_arg_groups,
                inputs=inputs,
                field_name="MethodSpec.interchangeable_arg_groups",
                error_factory=MethodSpecContractError,
            )
            payload["interchangeable_arg_groups"] = [
                list(group) for group in self.interchangeable_arg_groups
            ]
        if self.symbolic_closure is not None:
            payload["symbolic_closure"] = self.symbolic_closure.to_payload()
        return payload


def _validate_companion_outputs(
    companions: tuple[MethodCompanionOutputSpec, ...],
    *,
    output_names: frozenset[str],
    activated_output_names: frozenset[str],
) -> None:
    names = tuple(item.output_name for item in companions)
    if len(names) != len(set(names)):
        raise MethodSpecContractError(
            "planner.method_output_binding_contract_invalid: duplicate "
            "companion output"
        )
    unknown = sorted(set(names) - output_names)
    if unknown:
        raise MethodSpecContractError(
            "planner.method_output_binding_contract_invalid: companion "
            "outputs reference unknown Method outputs: " + ", ".join(unknown)
        )
    conditional = sorted(set(names) & activated_output_names)
    if conditional:
        raise MethodSpecContractError(
            "planner.method_output_binding_contract_invalid: always-emitted "
            "companion outputs cannot be conditionally activated: "
            + ", ".join(conditional)
        )


def _validate_predicate_publications(
    publications: tuple[PredicatePublicationSpec, ...],
    *,
    input_names: frozenset[str],
    outputs: dict[str, str],
) -> None:
    output_names = tuple(item.output_name for item in publications)
    if len(output_names) != len(set(output_names)):
        raise MethodSpecContractError(
            "planner.predicate_publication_contract_invalid: duplicate output"
        )
    for publication in publications:
        output_type = outputs.get(publication.output_name)
        if output_type != "Boolean":
            raise MethodSpecContractError(
                "planner.predicate_publication_contract_invalid: predicate "
                f"output {publication.output_name!r} must be Boolean"
            )
        unknown_roles = sorted(
            set(publication.related_input_roles) - input_names
        )
        if unknown_roles:
            raise MethodSpecContractError(
                "planner.predicate_publication_contract_invalid: unknown "
                "related input roles: " + ", ".join(unknown_roles)
            )
def _validate_input_relations(
    relations: tuple[MethodInputRelationSpec, ...],
    *,
    input_names: frozenset[str],
) -> None:
    seen: set[tuple[str, str, str]] = set()
    for relation in relations:
        key = (
            relation.relation_kind,
            relation.point_arg,
            relation.curve_arg,
        )
        if key in seen:
            raise MethodSpecContractError(
                f"duplicate Method input relation declaration: {key}"
            )
        seen.add(key)
        unknown = sorted(
            {relation.point_arg, relation.curve_arg} - input_names
        )
        if unknown:
            raise MethodSpecContractError(
                "Method input relation references unknown inputs: "
                + ", ".join(unknown)
            )
        if relation.relation_kind != "point_on_curve":
            raise MethodSpecContractError(
                "unsupported Method input relation kind: "
                f"{relation.relation_kind}"
            )
        if relation.cardinality not in {"one", "for_each"}:
            raise MethodSpecContractError(
                "Method input relation cardinality must be one or for_each"
            )
        if not relation.accepted_condition_kinds:
            raise MethodSpecContractError(
                "Method input relation must accept at least one Condition kind"
            )
        unsupported_condition_kinds = sorted(
            set(relation.accepted_condition_kinds)
            - {
                "point_on_curve",
                "point_on_curve_with_x_coordinate",
            }
        )
        if unsupported_condition_kinds:
            raise MethodSpecContractError(
                "unsupported point-on-curve Condition kinds: "
                + ", ".join(unsupported_condition_kinds)
            )


def _input_payloads(
    inputs: dict[str, dict[str, Any]],
    input_views: dict[str, MethodInputViewMode],
) -> dict[str, dict[str, Any]]:
    missing = sorted(set(inputs) - set(input_views))
    unknown = sorted(set(input_views) - set(inputs))
    if missing or unknown:
        raise MethodSpecContractError(
            "Method input view declarations must exactly cover inputs: "
            f"missing={missing}, unknown={unknown}"
        )
    return {
        name: _input_payload(name, raw, input_views[name])
        for name, raw in inputs.items()
    }


def _input_payload(
    name: str,
    raw: dict[str, Any],
    mode: MethodInputViewMode,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise MethodSpecContractError(
            f"Method input source must be an object: {name}"
        )
    runtime_type = str(raw.get("type", ""))
    domain_type, object_kind, state_kind = _domain_view_metadata(
        name,
        runtime_type,
        mode,
    )
    binding = raw.get("binding")
    if binding is not None and not isinstance(binding, MethodInputBindingSpec):
        raise MethodSpecContractError(
            f"Method input binding must use MethodInputBindingSpec: {name}"
        )
    if binding is not None:
        if binding.input_name != name:
            raise MethodSpecContractError(
                "Method input binding name mismatch: "
                f"{binding.input_name} != {name}"
            )
    payload = {
        key: value
        for key, value in raw.items()
        if key
        not in {
            "type",
            "domain_type",
            "object_kind",
            "state_kind",
            "view",
            "binding",
        }
    }
    payload.update(
        {
            "domain_type": str(raw.get("domain_type", domain_type)),
            "runtime_type": runtime_type,
            "view": {
                "mode": mode,
                "domain_type": str(raw.get("domain_type", domain_type)),
            },
        }
    )
    effective_object_kind = raw.get("object_kind", object_kind)
    effective_state_kind = raw.get("state_kind", state_kind)
    if effective_object_kind is not None:
        payload["view"]["object_kind"] = str(effective_object_kind)
    if effective_state_kind is not None:
        payload["view"]["state_kind"] = str(effective_state_kind)
    if binding is not None:
        payload["binding"] = binding.to_payload()
    return payload


def _domain_view_metadata(
    name: str,
    runtime_type: str,
    mode: MethodInputViewMode,
) -> tuple[str, str | None, str | None]:
    variants = set(runtime_type.split("|"))
    if variants <= {"Point", "PointRef"}:
        return "Point", "point", "coordinate"
    if variants == {"Parabola"}:
        return "QuadraticFunction", "function", "expression"
    if variants == {"Symbol"}:
        return "Symbol", "symbol", "value"
    if variants == {"ParameterValue"}:
        return "Symbol", "symbol", "value"
    if variants == {"Line"}:
        return "Line", "line", "equation"
    if variants == {"Expression"} and (
        "quadratic" in name or name == "parabola"
    ):
        return "QuadraticFunction", "function", "expression"
    if variants & {"Expression", "MinimumExpression", "Parabola"}:
        return "Expression", None, None
    if variants & {"Condition", "Constraint", "Equation", "AngleEquality"}:
        return "Fact", None, None
    if variants == {"OrientationHint"}:
        return "Fact", None, None
    if runtime_type.endswith("List") or "List" in runtime_type:
        return runtime_type, None, None
    if mode == "identity":
        return runtime_type, runtime_type.lower(), None
    return runtime_type, None, None


def _first_docstring_paragraph(method_cls: type) -> str:
    doc = inspect.getdoc(method_cls) or ""
    return doc.split("\n\n", 1)[0]


def _json_ready_hint(raw: dict[str, Any]) -> dict[str, Any]:
    """Convert repair hint tuple values to JSON-equivalent lists."""
    return {
        key: list(value) if isinstance(value, tuple) else value
        for key, value in raw.items()
    }


def _json_ready_explanation(explanation: MethodExplanationSpec) -> dict[str, Any]:
    payload = {
        "role_schema": dict(explanation.role_schema),
        "student_goal_template": explanation.student_goal_template,
        "student_title_template": explanation.student_title_template,
        "student_title_templates_by_goal": dict(explanation.student_title_templates_by_goal),
        "derive_templates": list(explanation.derive_templates),
        "box_templates": list(explanation.box_templates),
        "explanation_level": explanation.explanation_level,
        "role_binding_strategy": explanation.role_binding_strategy,
        "role_binder_id": explanation.role_binder_id,
    }
    if explanation.student_nav_title_template:
        payload["student_nav_title_template"] = explanation.student_nav_title_template
    return payload


def _json_ready_visual(visual: MethodVisualSpec) -> dict[str, Any]:
    return {
        "role_schema": dict(visual.role_schema),
        "scene_templates": [dict(item) for item in visual.scene_templates],
        "annotation_templates": [dict(item) for item in visual.annotation_templates],
        "timeline_templates": [dict(item) for item in visual.timeline_templates],
        "role_binder_id": visual.role_binder_id,
    }
