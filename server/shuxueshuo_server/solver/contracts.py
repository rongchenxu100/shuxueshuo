"""Method Solver 跨层共享契约。

本模块放置会同时被 solver 对外结果、runtime、stateless method 使用的轻量模型。
它不包含 ProblemIR、SolverResult、RuntimeScope 这类具体层级对象，避免外部 I/O
模型和 runtime 黑板模型互相耦合。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal, Mapping, TypeAlias, cast

import sympy as sp


CheckStatus = Literal["passed", "failed"]
Point = tuple[sp.Expr, sp.Expr]
FunctionalResultForm = Literal[
    "open_expression",
    "closed_value",
    "open_state",
    "closed_state",
]
ScalarResultClosurePolicy = Literal["no_free_symbols"]
PlanTransformerScope = Literal["single_invocation", "all_invocations"]
MethodOutputActivationKind = Literal[
    "requires_inputs",
    "input_type",
    "runtime_condition",
]
MethodSymbolicBasisRole = Literal[
    "state_anchor",
    "align_to_anchor",
]
MethodInputViewMode = Literal[
    "identity",
    "latest_state",
    "immutable_value",
    "exact_result",
]
FunctionalArgBindingAuthority = Literal["wire", "resolver", "compiler"]
MethodInputRelationCardinality = Literal["one", "for_each"]
MacroExecutionMode = Literal["direct", "runtime_search"]


class MethodInputBindingContractError(ValueError):
    """A declarative Method input contract is incomplete or ambiguous."""

    code = "planner.method_input_binding_contract_invalid"

    def __init__(self, detail: str) -> None:
        super().__init__(
            f"planner_configuration_error: {self.code}: {detail}"
        )


def _required_name(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise MethodInputBindingContractError(
            f"{field_name} must be a non-empty string"
        )


def _required_unique_names(
    values: tuple[str, ...],
    field_name: str,
) -> None:
    if not values:
        raise MethodInputBindingContractError(
            f"{field_name} must be non-empty"
        )
    for value in values:
        _required_name(value, field_name)
    if len(set(values)) != len(values):
        raise MethodInputBindingContractError(
            f"{field_name} must contain unique values"
        )


@dataclass(frozen=True)
class PublicArgSourceSpec:
    arg_name: str
    kind: Literal["public_arg"] = field(default="public_arg", init=False)

    def __post_init__(self) -> None:
        _required_name(self.arg_name, "arg_name")

    def to_payload(self) -> dict[str, Any]:
        return {"kind": self.kind, "arg_name": self.arg_name}


@dataclass(frozen=True)
class EntityIdentitySourceSpec:
    arg_name: str | None = None
    semantic_roles: tuple[str, ...] = ()
    kind: Literal["entity_identity"] = field(
        default="entity_identity",
        init=False,
    )

    def __post_init__(self) -> None:
        if (self.arg_name is None) == (not self.semantic_roles):
            raise MethodInputBindingContractError(
                "entity_identity requires exactly one of arg_name or semantic_roles"
            )
        if self.arg_name is not None:
            _required_name(self.arg_name, "arg_name")
        else:
            _required_unique_names(self.semantic_roles, "semantic_roles")

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"kind": self.kind}
        if self.arg_name is not None:
            payload["arg_name"] = self.arg_name
        else:
            payload["semantic_roles"] = list(self.semantic_roles)
        return payload


@dataclass(frozen=True)
class LatestStateSourceSpec:
    entity_arg: str
    kind: Literal["latest_state"] = field(default="latest_state", init=False)

    def __post_init__(self) -> None:
        _required_name(self.entity_arg, "entity_arg")

    def to_payload(self) -> dict[str, Any]:
        return {"kind": self.kind, "entity_arg": self.entity_arg}


@dataclass(frozen=True)
class ConditionSourceSpec:
    arg_name: str | None = None
    condition_kinds: tuple[str, ...] = ()
    related_args: tuple[str, ...] = ()
    kind: Literal["condition"] = field(default="condition", init=False)

    def __post_init__(self) -> None:
        by_arg = self.arg_name is not None
        by_relation = bool(self.condition_kinds or self.related_args)
        if by_arg == by_relation:
            raise MethodInputBindingContractError(
                "condition requires exactly one of arg_name or "
                "condition_kinds+related_args"
            )
        if by_arg:
            _required_name(cast(str, self.arg_name), "arg_name")
            return
        _required_unique_names(self.condition_kinds, "condition_kinds")
        _required_unique_names(self.related_args, "related_args")

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"kind": self.kind}
        if self.arg_name is not None:
            payload["arg_name"] = self.arg_name
        else:
            payload["condition_kinds"] = list(self.condition_kinds)
            payload["related_args"] = list(self.related_args)
        return payload


@dataclass(frozen=True)
class ExactCallResultSourceSpec:
    arg_name: str
    semantic_roles: tuple[str, ...] = ()
    kind: Literal["exact_call_result"] = field(
        default="exact_call_result",
        init=False,
    )

    def __post_init__(self) -> None:
        _required_name(self.arg_name, "arg_name")
        if self.semantic_roles:
            _required_unique_names(self.semantic_roles, "semantic_roles")

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": self.kind,
            "arg_name": self.arg_name,
        }
        if self.semantic_roles:
            payload["semantic_roles"] = list(self.semantic_roles)
        return payload


@dataclass(frozen=True)
class ExactParameterSubstitutionSourceSpec:
    """Select one exact ParameterValue from already-pinned input lineage."""

    source_inputs: tuple[str, ...]
    target_input: str
    kind: Literal["exact_parameter_substitution"] = field(
        default="exact_parameter_substitution",
        init=False,
    )

    def __post_init__(self) -> None:
        _required_unique_names(self.source_inputs, "source_inputs")
        _required_name(self.target_input, "target_input")
        if self.target_input in self.source_inputs:
            raise MethodInputBindingContractError(
                "target_input must not also be a source_input"
            )

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "source_inputs": list(self.source_inputs),
            "target_input": self.target_input,
        }


@dataclass(frozen=True)
class ProducerLinkedSourceSpec:
    source_arg: str
    producer_arg: str
    kind: Literal["producer_linked"] = field(
        default="producer_linked",
        init=False,
    )

    def __post_init__(self) -> None:
        _required_name(self.source_arg, "source_arg")
        _required_name(self.producer_arg, "producer_arg")

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "source_arg": self.source_arg,
            "producer_arg": self.producer_arg,
        }


@dataclass(frozen=True)
class MacroPreparedRoleSourceSpec:
    role: str
    kind: Literal["macro_prepared_role"] = field(
        default="macro_prepared_role",
        init=False,
    )

    def __post_init__(self) -> None:
        _required_name(self.role, "role")

    def to_payload(self) -> dict[str, Any]:
        return {"kind": self.kind, "role": self.role}


MethodInputSourceSpec: TypeAlias = (
    PublicArgSourceSpec
    | EntityIdentitySourceSpec
    | LatestStateSourceSpec
    | ConditionSourceSpec
    | ExactCallResultSourceSpec
    | ExactParameterSubstitutionSourceSpec
    | ProducerLinkedSourceSpec
    | MacroPreparedRoleSourceSpec
)


@dataclass(frozen=True)
class CanonicalSymbolDerivationSpec:
    symbol_name: str
    kind: Literal["canonical_symbol"] = field(
        default="canonical_symbol",
        init=False,
    )

    def __post_init__(self) -> None:
        _required_name(self.symbol_name, "symbol_name")

    def to_payload(self) -> dict[str, Any]:
        return {"kind": self.kind, "symbol_name": self.symbol_name}


@dataclass(frozen=True)
class CoefficientExtractionDerivationSpec:
    source_input: str
    kind: Literal["coefficient_extraction"] = field(
        default="coefficient_extraction",
        init=False,
    )

    def __post_init__(self) -> None:
        _required_name(self.source_input, "source_input")

    def to_payload(self) -> dict[str, Any]:
        return {"kind": self.kind, "source_input": self.source_input}


@dataclass(frozen=True)
class OrdinalZeroTemplateDerivationSpec:
    source_input: str
    kind: Literal["ordinal_zero_template"] = field(
        default="ordinal_zero_template",
        init=False,
    )

    def __post_init__(self) -> None:
        _required_name(self.source_input, "source_input")

    def to_payload(self) -> dict[str, Any]:
        return {"kind": self.kind, "source_input": self.source_input}


@dataclass(frozen=True)
class PreviousOutputIdentityDerivationSpec:
    output_name: str
    kind: Literal["previous_output_identity"] = field(
        default="previous_output_identity",
        init=False,
    )

    def __post_init__(self) -> None:
        _required_name(self.output_name, "output_name")

    def to_payload(self) -> dict[str, Any]:
        return {"kind": self.kind, "output_name": self.output_name}


@dataclass(frozen=True)
class SourceObjectIdentityDerivationSpec:
    source_input: str
    kind: Literal["source_object_identity"] = field(
        default="source_object_identity",
        init=False,
    )

    def __post_init__(self) -> None:
        _required_name(self.source_input, "source_input")

    def to_payload(self) -> dict[str, Any]:
        return {"kind": self.kind, "source_input": self.source_input}


@dataclass(frozen=True)
class FreeSymbolBasisDerivationSpec:
    source_inputs: tuple[str, ...]
    kind: Literal["free_symbol_basis"] = field(
        default="free_symbol_basis",
        init=False,
    )

    def __post_init__(self) -> None:
        _required_unique_names(self.source_inputs, "source_inputs")

    def to_payload(self) -> dict[str, Any]:
        return {"kind": self.kind, "source_inputs": list(self.source_inputs)}


MethodInputDerivationSpec: TypeAlias = (
    CanonicalSymbolDerivationSpec
    | CoefficientExtractionDerivationSpec
    | OrdinalZeroTemplateDerivationSpec
    | PreviousOutputIdentityDerivationSpec
    | SourceObjectIdentityDerivationSpec
    | FreeSymbolBasisDerivationSpec
)

_METHOD_INPUT_SOURCE_TYPES = (
    PublicArgSourceSpec,
    EntityIdentitySourceSpec,
    LatestStateSourceSpec,
    ConditionSourceSpec,
    ExactCallResultSourceSpec,
    ExactParameterSubstitutionSourceSpec,
    ProducerLinkedSourceSpec,
    MacroPreparedRoleSourceSpec,
)
_METHOD_INPUT_DERIVATION_TYPES = (
    CanonicalSymbolDerivationSpec,
    CoefficientExtractionDerivationSpec,
    OrdinalZeroTemplateDerivationSpec,
    PreviousOutputIdentityDerivationSpec,
    SourceObjectIdentityDerivationSpec,
    FreeSymbolBasisDerivationSpec,
)


@dataclass(frozen=True, kw_only=True)
class MethodInputBindingSpec:
    """Strict typed declaration for one Method input.

    Exactly one branch is present.  Legacy selector strings deliberately do
    not fit this constructor.
    """

    input_name: str
    required: bool = True
    source: MethodInputSourceSpec | None = None
    derivation: MethodInputDerivationSpec | None = None
    schema_version: ClassVar[str] = "method-input-binding/v1"

    def __post_init__(self) -> None:
        _required_name(self.input_name, "input_name")
        if not isinstance(self.required, bool):
            raise MethodInputBindingContractError("required must be boolean")
        if (self.source is None) == (self.derivation is None):
            raise MethodInputBindingContractError(
                "MethodInputBindingSpec requires exactly one of source or derivation"
            )
        if self.source is not None and not isinstance(
            self.source,
            _METHOD_INPUT_SOURCE_TYPES,
        ):
            raise MethodInputBindingContractError(
                "source must be a registered MethodInputSourceSpec"
            )
        if self.derivation is not None and not isinstance(
            self.derivation,
            _METHOD_INPUT_DERIVATION_TYPES,
        ):
            raise MethodInputBindingContractError(
                "derivation must be a registered MethodInputDerivationSpec"
            )

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "input_name": self.input_name,
            "required": self.required,
        }
        if self.source is not None:
            payload["source"] = self.source.to_payload()
        else:
            payload["derivation"] = cast(
                MethodInputDerivationSpec,
                self.derivation,
            ).to_payload()
        return payload

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "MethodInputBindingSpec":
        _strict_payload_fields(
            payload,
            allowed={
                "schema_version",
                "input_name",
                "required",
                "source",
                "derivation",
            },
            required={"schema_version", "input_name", "required"},
            context="MethodInputBindingSpec",
        )
        if payload.get("schema_version") != cls.schema_version:
            raise MethodInputBindingContractError(
                "unsupported MethodInputBindingSpec schema_version"
            )
        source_payload = payload.get("source")
        derivation_payload = payload.get("derivation")
        return cls(
            input_name=_strict_name_value(payload["input_name"], "input_name"),
            required=_strict_bool(payload["required"], "required"),
            source=(
                method_input_source_from_payload(source_payload)
                if isinstance(source_payload, Mapping)
                else None
            ),
            derivation=(
                method_input_derivation_from_payload(derivation_payload)
                if isinstance(derivation_payload, Mapping)
                else None
            ),
        )


def _strict_payload_fields(
    payload: Mapping[str, Any],
    *,
    allowed: set[str],
    required: set[str],
    context: str,
) -> None:
    keys = set(payload)
    missing = required - keys
    extra = keys - allowed
    if missing or extra:
        raise MethodInputBindingContractError(
            f"{context} fields invalid: missing={sorted(missing)}, extra={sorted(extra)}"
        )


def _strict_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise MethodInputBindingContractError(f"{field_name} must be boolean")
    return value


def _strict_name_value(value: Any, field_name: str) -> str:
    _required_name(value, field_name)
    return cast(str, value)


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise MethodInputBindingContractError(f"{field_name} must be an array")
    result = tuple(value)
    _required_unique_names(result, field_name)
    return result


def method_input_source_from_payload(
    payload: Mapping[str, Any],
) -> MethodInputSourceSpec:
    kind = payload.get("kind")
    if kind == "public_arg":
        _strict_payload_fields(
            payload,
            allowed={"kind", "arg_name"},
            required={"kind", "arg_name"},
            context=kind,
        )
        return PublicArgSourceSpec(
            _strict_name_value(payload["arg_name"], "arg_name")
        )
    if kind == "entity_identity":
        _strict_payload_fields(
            payload,
            allowed={"kind", "arg_name", "semantic_roles"},
            required={"kind"},
            context=kind,
        )
        return EntityIdentitySourceSpec(
            arg_name=(
                _strict_name_value(payload["arg_name"], "arg_name")
                if payload.get("arg_name") is not None
                else None
            ),
            semantic_roles=(
                _string_tuple(payload["semantic_roles"], "semantic_roles")
                if "semantic_roles" in payload
                else ()
            ),
        )
    if kind == "latest_state":
        _strict_payload_fields(
            payload,
            allowed={"kind", "entity_arg"},
            required={"kind", "entity_arg"},
            context=kind,
        )
        return LatestStateSourceSpec(
            _strict_name_value(payload["entity_arg"], "entity_arg")
        )
    if kind == "condition":
        _strict_payload_fields(
            payload,
            allowed={"kind", "arg_name", "condition_kinds", "related_args"},
            required={"kind"},
            context=kind,
        )
        return ConditionSourceSpec(
            arg_name=(
                _strict_name_value(payload["arg_name"], "arg_name")
                if payload.get("arg_name") is not None
                else None
            ),
            condition_kinds=(
                _string_tuple(payload["condition_kinds"], "condition_kinds")
                if "condition_kinds" in payload
                else ()
            ),
            related_args=(
                _string_tuple(payload["related_args"], "related_args")
                if "related_args" in payload
                else ()
            ),
        )
    if kind == "exact_call_result":
        _strict_payload_fields(
            payload,
            allowed={"kind", "arg_name", "semantic_roles"},
            required={"kind", "arg_name"},
            context=kind,
        )
        return ExactCallResultSourceSpec(
            _strict_name_value(payload["arg_name"], "arg_name"),
            (
                _string_tuple(payload["semantic_roles"], "semantic_roles")
                if "semantic_roles" in payload
                else ()
            ),
        )
    if kind == "exact_parameter_substitution":
        _strict_payload_fields(
            payload,
            allowed={"kind", "source_inputs", "target_input"},
            required={"kind", "source_inputs", "target_input"},
            context=kind,
        )
        return ExactParameterSubstitutionSourceSpec(
            _string_tuple(payload["source_inputs"], "source_inputs"),
            _strict_name_value(payload["target_input"], "target_input"),
        )
    if kind == "producer_linked":
        _strict_payload_fields(
            payload,
            allowed={"kind", "source_arg", "producer_arg"},
            required={"kind", "source_arg", "producer_arg"},
            context=kind,
        )
        return ProducerLinkedSourceSpec(
            _strict_name_value(payload["source_arg"], "source_arg"),
            _strict_name_value(payload["producer_arg"], "producer_arg"),
        )
    if kind == "macro_prepared_role":
        _strict_payload_fields(
            payload,
            allowed={"kind", "role"},
            required={"kind", "role"},
            context=kind,
        )
        return MacroPreparedRoleSourceSpec(
            _strict_name_value(payload["role"], "role")
        )
    raise MethodInputBindingContractError(
        f"unknown MethodInputSourceSpec kind: {kind!r}"
    )


def method_input_derivation_from_payload(
    payload: Mapping[str, Any],
) -> MethodInputDerivationSpec:
    kind = payload.get("kind")
    if kind == "canonical_symbol":
        field_name = "symbol_name"
        factory = CanonicalSymbolDerivationSpec
    elif kind == "coefficient_extraction":
        field_name = "source_input"
        factory = CoefficientExtractionDerivationSpec
    elif kind == "ordinal_zero_template":
        field_name = "source_input"
        factory = OrdinalZeroTemplateDerivationSpec
    elif kind == "previous_output_identity":
        field_name = "output_name"
        factory = PreviousOutputIdentityDerivationSpec
    elif kind == "source_object_identity":
        field_name = "source_input"
        factory = SourceObjectIdentityDerivationSpec
    elif kind == "free_symbol_basis":
        _strict_payload_fields(
            payload,
            allowed={"kind", "source_inputs"},
            required={"kind", "source_inputs"},
            context=kind,
        )
        return FreeSymbolBasisDerivationSpec(
            _string_tuple(payload["source_inputs"], "source_inputs")
        )
    else:
        raise MethodInputBindingContractError(
            f"unknown MethodInputDerivationSpec kind: {kind!r}"
        )
    _strict_payload_fields(
        payload,
        allowed={"kind", field_name},
        required={"kind", field_name},
        context=str(kind),
    )
    return factory(_strict_name_value(payload[field_name], field_name))


def validate_method_input_binding_view(
    binding: MethodInputBindingSpec,
    input_spec: "MethodInputSpec",
) -> None:
    """Reject source declarations that contradict an explicit Method view."""

    expected_mode: MethodInputViewMode | None = None
    if isinstance(binding.source, EntityIdentitySourceSpec):
        expected_mode = "identity"
    elif isinstance(binding.source, LatestStateSourceSpec):
        expected_mode = "latest_state"
    elif isinstance(binding.source, ConditionSourceSpec):
        expected_mode = "immutable_value"
    elif isinstance(binding.source, ExactCallResultSourceSpec):
        expected_mode = "exact_result"
    elif isinstance(binding.source, ExactParameterSubstitutionSourceSpec):
        if input_spec.view.mode not in {"latest_state", "exact_result"}:
            raise MethodInputBindingContractError(
                f"input {binding.input_name} exact parameter substitution "
                f"requires latest_state or exact_result, observed "
                f"{input_spec.view.mode}"
            )
        return
    if expected_mode is not None and input_spec.view.mode != expected_mode:
        raise MethodInputBindingContractError(
            f"input {binding.input_name} source requires view {expected_mode}, "
            f"observed {input_spec.view.mode}"
        )


@dataclass(frozen=True)
class MacroSearchSpec:
    """Bounded implementation contract for one runtime-search Macro."""

    searchable_roles: tuple[str, ...]
    candidate_builder_id: str
    validation_policy_id: str
    lowerer_id: str | None = None
    postcondition_id: str | None = None
    evidence_builder_id: str | None = None
    max_candidates: int = 32

    def __post_init__(self) -> None:
        if not self.searchable_roles or any(
            not isinstance(item, str) or not item
            for item in self.searchable_roles
        ):
            raise ValueError("Macro search roles must be non-empty")
        if len(set(self.searchable_roles)) != len(self.searchable_roles):
            raise ValueError("Macro search roles must be unique")
        for name, value in (
            ("candidate_builder_id", self.candidate_builder_id),
            ("validation_policy_id", self.validation_policy_id),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be a non-empty string")
        for name, value in (
            ("lowerer_id", self.lowerer_id),
            ("postcondition_id", self.postcondition_id),
            ("evidence_builder_id", self.evidence_builder_id),
        ):
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError(f"{name} must be non-empty when provided")
        if self.max_candidates <= 0:
            raise ValueError("Macro search max_candidates must be positive")

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "searchable_roles": list(self.searchable_roles),
            "candidate_builder_id": self.candidate_builder_id,
            "validation_policy_id": self.validation_policy_id,
            "max_candidates": self.max_candidates,
        }
        for name in (
            "lowerer_id",
            "postcondition_id",
            "evidence_builder_id",
        ):
            value = getattr(self, name)
            if value is not None:
                payload[name] = value
        return payload


@dataclass(frozen=True)
class TrialErrorHintSpec:
    """Declarative mapping from one trial failure shape to a typed code."""

    error_contains: str
    code: str
    requires_point_answer: bool = False
    requires_planner_output_types: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "error_contains": self.error_contains,
            "code": self.code,
        }
        if self.requires_point_answer:
            payload["requires_point_answer"] = True
        if self.requires_planner_output_types:
            payload["requires_planner_output_types"] = list(
                self.requires_planner_output_types
            )
        return payload


@dataclass
class CheckResult:
    """一次可机读验算的结果。"""

    name: str
    status: CheckStatus
    detail: str
    code: str | None = None
    retryability: Literal[
        "planner_repairable",
        "problem_semantics",
        "configuration",
    ] = "planner_repairable"
    expected: dict[str, Any] = field(default_factory=dict)
    observed: dict[str, Any] = field(default_factory=dict)
    subjects: tuple[dict[str, Any], ...] = ()
    repair_action: str = "repair_failed_step"
    method_id: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "passed"


@dataclass
class DerivationStep:
    """一段可展示给用户或学生的推导骨架。"""

    title: str
    goal: str
    reason: str
    calculation: str
    conclusion: str
    method_id: str


@dataclass
class TypedValue:
    """运行时黑板中的带类型值。

    ``type`` 是 runtime 自己的轻量类型系统，用于校验 MethodSpec 的输入输出；
    ``locked`` 用来保护题设已知量，避免 invocation 把原题给定的点坐标覆盖掉；
    ``source`` 记录值来自题设、某个 method，还是测试辅助写入，便于后续 trace。
    """

    type: str
    value: Any
    locked: bool = False
    source: str = ""


@dataclass(frozen=True)
class PointRef:
    """尚未求出坐标的点引用。

    题目里很多点不是显式坐标，而是“D 是对称轴与 x 轴交点”“N 满足直角等腰
    条件”这类定义。V1.5 用 PointRef 保留原始定义和所在 path，等 Planner 找到
    合适 method 后再把它 promote 成真正的 ``Point``。
    """

    name: str
    path: str
    definition: dict[str, Any] = field(default_factory=dict)
    scope_id: str = "problem"


@dataclass(frozen=True)
class MethodInputViewSpec:
    """How the compiler materializes one domain argument for a Method."""

    mode: MethodInputViewMode
    domain_type: str
    object_kind: str | None = None
    state_kind: str | None = None

    def to_payload(self) -> dict[str, str]:
        payload = {
            "mode": self.mode,
            "domain_type": self.domain_type,
        }
        if self.object_kind is not None:
            payload["object_kind"] = self.object_kind
        if self.state_kind is not None:
            payload["state_kind"] = self.state_kind
        return payload


@dataclass(frozen=True)
class MethodInputSpec:
    """MethodSpec 中的单个、显式view输入槽位定义。"""

    name: str
    domain_type: str
    runtime_type: str
    view: MethodInputViewSpec
    role: str = ""
    required: bool = True
    functional_exposed: bool = True
    allows_anonymous_result: bool = False
    allows_empty_collection: bool = False
    symbolic_basis_role: MethodSymbolicBasisRole | None = None
    binding: MethodInputBindingSpec | None = None

    @property
    def type(self) -> str:
        """Internal compatibility alias; prompt code must use domain_type."""

        return self.runtime_type


@dataclass(frozen=True)
class MethodInputRelationSpec:
    """Structured Condition required when one Method consumes related entities.

    The Planner still supplies only domain entities.  Reconciliation resolves
    the exact Condition that proves their relationship before any Method input
    state is consumed.
    """

    relation_kind: str
    point_arg: str
    curve_arg: str
    cardinality: MethodInputRelationCardinality
    accepted_condition_kinds: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "relation_kind": self.relation_kind,
            "point_arg": self.point_arg,
            "curve_arg": self.curve_arg,
            "cardinality": self.cardinality,
            "accepted_condition_kinds": list(
                self.accepted_condition_kinds
            ),
        }


@dataclass(frozen=True)
class MethodOutputActivationSpec:
    """Declare when one optional Method output is active.

    Outputs without a declaration are unconditional. ``requires_inputs`` and
    ``input_type`` are decidable before execution; ``runtime_condition`` is
    intentionally decided by the Method and its structured checks.
    """

    kind: MethodOutputActivationKind
    required_inputs: tuple[str, ...] = ()
    input_name: str | None = None
    input_types: tuple[str, ...] = ()
    runtime_condition: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"kind": self.kind}
        if self.required_inputs:
            payload["required_inputs"] = list(self.required_inputs)
        if self.input_name is not None:
            payload["input_name"] = self.input_name
        if self.input_types:
            payload["input_types"] = list(self.input_types)
        if self.runtime_condition is not None:
            payload["runtime_condition"] = self.runtime_condition
        return payload


@dataclass(frozen=True)
class ScalarResultFormSpec:
    """LLM-facing closure metadata for symbolic scalar or object outputs.

    This is an intent and catalog contract. Runtime remains authoritative and
    determines the actual form from the produced value's free symbols.
    """

    possible_forms: tuple[FunctionalResultForm, ...]
    description: str
    closure_policy: ScalarResultClosurePolicy = "no_free_symbols"
    ignored_symbol_input_args: tuple[str, ...] = ()
    max_independent_free_parameters: int | None = None
    free_symbol_output_names: tuple[str, ...] = ()
    applied_substitutions: tuple[tuple[str, str], ...] = ()

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "possible_forms": list(self.possible_forms),
            "description": self.description,
            "closure_policy": self.closure_policy,
        }
        if self.ignored_symbol_input_args:
            payload["ignored_symbol_input_args"] = list(
                self.ignored_symbol_input_args
            )
        if self.max_independent_free_parameters is not None:
            payload["max_independent_free_parameters"] = (
                self.max_independent_free_parameters
            )
        if self.free_symbol_output_names:
            payload["free_symbol_output_names"] = list(
                self.free_symbol_output_names
            )
        if self.applied_substitutions:
            payload["applied_substitutions"] = [
                list(item) for item in self.applied_substitutions
            ]
        return payload


@dataclass(frozen=True)
class SymbolicClosureSpec:
    """Declarative target-Symbol solve and substitution effect contract.

    The runtime solver remains authoritative for concrete values and branches.
    This metadata lets planner layers identify the target, explicitly
    preserved Symbol basis and returns affected by the same substitution.
    """

    target_arg: str
    equation_builder: str
    known_substitutions: tuple[tuple[str, str], ...] = ()
    known_mapping_args: tuple[str, ...] = ()
    representation_mapper: str | None = None
    constraint_filter: str | None = None
    constraint_args: tuple[str, ...] = ()
    constraint_args_optional: bool = False
    preserved_symbol_args: tuple[str, ...] = ()
    substitution_outputs: tuple[str, ...] = ()
    output_validator: str | None = None
    require_unique_target: bool = True

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "target_arg": self.target_arg,
            "equation_builder": self.equation_builder,
            "known_substitutions": [
                list(item) for item in self.known_substitutions
            ],
            "known_mapping_args": list(self.known_mapping_args),
            "constraint_args": list(self.constraint_args),
            "preserved_symbol_args": list(self.preserved_symbol_args),
            "substitution_outputs": list(self.substitution_outputs),
            "require_unique_target": self.require_unique_target,
        }
        if self.representation_mapper is not None:
            payload["representation_mapper"] = self.representation_mapper
        if self.constraint_filter is not None:
            payload["constraint_filter"] = self.constraint_filter
        if self.constraint_args_optional:
            payload["constraint_args_optional"] = True
        if self.output_validator is not None:
            payload["output_validator"] = self.output_validator
        return payload


_OPEN_OR_CLOSED_POINT_STATE = ScalarResultFormSpec(
    possible_forms=("open_state", "closed_state"),
    description=(
        "坐标仍含未确定符号时为 open_state；不存在自由符号时为 "
        "closed_state。重复写入同一对象时，代码会验证它是否为状态收敛。"
    ),
)

_OPEN_OR_CLOSED_PARABOLA_STATE = ScalarResultFormSpec(
    possible_forms=("open_state", "closed_state"),
    description=(
        "抛物线状态仍含未确定系数或参数时为 open_state；不存在自由符号时为 "
        "closed_state。代码以 runtime 表达式的自由符号为准。"
    ),
    ignored_symbol_input_args=("x",),
)


def default_result_form_spec(runtime_type: str) -> ScalarResultFormSpec | None:
    """Return type-level result-form semantics shared by every capability.

    A Point is a coordinate state and may be symbolic or fully evaluated
    regardless of which method produced it. Keeping this rule at the runtime
    type boundary avoids per-method result-form patches.
    """
    if runtime_type == "Point":
        return _OPEN_OR_CLOSED_POINT_STATE
    if runtime_type == "Parabola":
        return _OPEN_OR_CLOSED_PARABOLA_STATE
    return None


@dataclass(frozen=True)
class TeachingSubstepSpec:
    """一个 executable capability 在 LessonIR 中建议拆出的认知子步骤。"""

    substep_id: str
    title: str
    focus: str
    nav_title: str | None = None
    title_required_terms: tuple[str, ...] = ()
    nav_title_required_terms: tuple[str, ...] = ()
    preferred_method_ids: tuple[str, ...] = ()
    forbid_merge_with_sibling_substeps: bool = True

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "substep_id": self.substep_id,
            "title": self.title,
            "focus": self.focus,
            "title_required_terms": list(self.title_required_terms),
            "nav_title_required_terms": list(self.nav_title_required_terms),
            "preferred_method_ids": list(self.preferred_method_ids),
            "forbid_merge_with_sibling_substeps": self.forbid_merge_with_sibling_substeps,
        }
        if self.nav_title:
            payload["nav_title"] = self.nav_title
        return payload


@dataclass(frozen=True)
class MethodExplanationSpec:
    """Method 面向讲解层的角色化模板。"""

    role_schema: dict[str, str]
    student_goal_template: str
    student_title_template: str = ""
    student_nav_title_template: str = ""
    student_title_templates_by_goal: dict[str, str] = field(default_factory=dict)
    derive_templates: tuple[str, ...] = ()
    box_templates: tuple[str, ...] = ()
    explanation_level: str = "template"
    role_binding_strategy: str = "role_name_registry"
    role_binder_id: str = "generic_trace"


@dataclass(frozen=True)
class MethodVisualSpec:
    """Method 面向 VisualStepIR 的角色化视觉模板。"""

    role_schema: dict[str, str]
    scene_templates: tuple[dict[str, Any], ...] = ()
    annotation_templates: tuple[dict[str, Any], ...] = ()
    timeline_templates: tuple[dict[str, Any], ...] = ()
    role_binder_id: str = "generic_visual"


@dataclass(frozen=True)
class MethodSpec:
    """可检索、可校验的 method 能力规格。

    MethodSpec 是 method 代码内 SPEC 或派生 JSON 加载后的 Python 形态。它只描述
    method 能解决什么、需要什么输入、产出什么输出，不绑定具体题号、点名或
    fixture。
    """

    method_id: str
    title: str
    solves: tuple[str, ...]
    inputs: dict[str, MethodInputSpec]
    outputs: dict[str, str]
    input_relations: tuple[MethodInputRelationSpec, ...] = ()
    internal_outputs: tuple[str, ...] = ()
    output_activation: dict[str, MethodOutputActivationSpec] = field(
        default_factory=dict
    )
    scalar_result_forms: dict[str, ScalarResultFormSpec] = field(default_factory=dict)
    summary: str = ""
    do_not_use_when: tuple[str, ...] = ()
    preconditions: tuple[str, ...] = ()
    postconditions: tuple[str, ...] = ()
    trace_template: tuple[str, ...] = ()
    repair_hints: tuple[dict[str, Any], ...] = ()
    trial_error_hints: tuple[TrialErrorHintSpec, ...] = ()
    repair_feedback_provider_id: str | None = None
    geometry_profiles: tuple[dict[str, Any], ...] = ()
    explanation: MethodExplanationSpec | None = None
    visual: MethodVisualSpec | None = None
    constraint_analyzer: str | None = None
    plan_transformer: str | None = None
    plan_transformer_scope: PlanTransformerScope = "single_invocation"
    reconciliation_validators: tuple[str, ...] = ()
    distinct_arg_groups: tuple[tuple[str, ...], ...] = ()
    interchangeable_arg_groups: tuple[tuple[str, ...], ...] = ()
    symbolic_closure: SymbolicClosureSpec | None = None
    # Missing/legacy specs are conservative. Code-owned stateless methods
    # declare purity explicitly through MethodSpecSource.
    is_pure: bool = False


@dataclass
class StatelessMethodResult:
    """无状态 method 的返回结果。

    method 只返回 typed outputs、checks 和 trace fragment；是否写入上层上下文由
    InvocationExecutor/StepPlan 决定。
    """

    method_id: str
    outputs: dict[str, TypedValue] = field(default_factory=dict)
    checks: list[Any] = field(default_factory=list)
    trace_fragments: list[Any] = field(default_factory=list)
