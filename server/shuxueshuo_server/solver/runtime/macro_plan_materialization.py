"""Deterministically replace one selected Macro with ordinary Function steps."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Mapping

import sympy as sp

from shuxueshuo_server.solver.extraction.source_identity import stable_hash
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.functional_subplan import (
    FunctionalPlanFragment,
)
from shuxueshuo_server.solver.runtime.macro_preparation import (
    MacroPreparationAuthority,
)
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedDerivedResultRef,
    ScopedFunctionalAnswerSource,
    ScopedFunctionalGoalPlan,
    ScopedFunctionalPlan,
    ScopedFunctionalRef,
    ScopedFunctionalScope,
    ScopedFunctionalStep,
    ScopedPublishedGoalResultRef,
    ScopedStepResultRef,
    scoped_functional_plan_id,
)

if TYPE_CHECKING:
    from shuxueshuo_server.solver.runtime.functional_transaction_execution import (
        FunctionalRestoredCallSeed,
        FunctionalTransactionalExecutionReport,
    )


class MacroPlanMaterializationError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.details = MappingProxyType(dict(details or {}))
        super().__init__(f"{code}: {message}")


def macro_expansion_record_schema() -> dict[str, Any]:
    nonempty = {"type": "string", "minLength": 1}
    return {
        "type": "object",
        "required": [
            "schema_version",
            "authored_plan_id",
            "materialized_plan_id",
            "macro_step_id",
            "macro_id",
            "implementation_id",
            "preparation_signature",
            "winner_candidate_id",
            "search_signature",
            "winner_fragment_signature",
            "winner_output_signature",
            "authored_input_refs",
            "authored_roles",
            "chosen_roles",
            "generated_step_ids",
            "generated_step_signatures",
            "generated_return_roles",
            "export_map",
            "generated_step_origins",
            "expansion_signature",
        ],
        "properties": {
            "schema_version": {"const": "macro-expansion-record/v1"},
            "authored_plan_id": nonempty,
            "materialized_plan_id": nonempty,
            "macro_step_id": nonempty,
            "macro_id": nonempty,
            "implementation_id": nonempty,
            "preparation_signature": nonempty,
            "winner_candidate_id": nonempty,
            "search_signature": nonempty,
            "winner_fragment_signature": nonempty,
            "winner_output_signature": nonempty,
            "authored_input_refs": {
                "type": "object",
                "additionalProperties": {
                    "type": "array",
                    "minItems": 1,
                    "items": nonempty,
                },
            },
            "authored_roles": {
                "type": "object",
                "additionalProperties": nonempty,
            },
            "chosen_roles": {
                "type": "object",
                "minProperties": 1,
                "additionalProperties": nonempty,
            },
            "generated_step_ids": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": nonempty,
            },
            "generated_step_signatures": {
                "type": "object",
                "minProperties": 1,
                "additionalProperties": nonempty,
            },
            "generated_return_roles": {
                "type": "object",
                "minProperties": 1,
                "additionalProperties": {
                    "type": "object",
                    "additionalProperties": nonempty,
                },
            },
            "export_map": {
                "type": "object",
                "minProperties": 1,
                "additionalProperties": {
                    "type": "object",
                    "required": ["step_id", "return"],
                    "properties": {
                        "step_id": nonempty,
                        "return": nonempty,
                    },
                    "additionalProperties": False,
                },
            },
            "generated_step_origins": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": [
                        "generated_step_id",
                        "macro_step_id",
                        "winner_candidate_id",
                        "generated_ordinal",
                    ],
                    "properties": {
                        "generated_step_id": nonempty,
                        "macro_step_id": nonempty,
                        "winner_candidate_id": nonempty,
                        "generated_ordinal": {
                            "type": "integer",
                            "minimum": 0,
                        },
                    },
                    "additionalProperties": False,
                },
            },
            "expansion_signature": nonempty,
        },
        "additionalProperties": False,
    }


@dataclass(frozen=True)
class MacroGeneratedStepOrigin:
    generated_step_id: str
    macro_step_id: str
    winner_candidate_id: str
    generated_ordinal: int

    def __post_init__(self) -> None:
        if not self.generated_step_id or not self.macro_step_id:
            raise ValueError("Macro generated-step origin is incomplete")
        if not self.winner_candidate_id or self.generated_ordinal < 0:
            raise ValueError("Macro generated-step origin is invalid")

    def to_payload(self) -> dict[str, Any]:
        return {
            "generated_step_id": self.generated_step_id,
            "macro_step_id": self.macro_step_id,
            "winner_candidate_id": self.winner_candidate_id,
            "generated_ordinal": self.generated_ordinal,
        }

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
    ) -> "MacroGeneratedStepOrigin":
        return cls(
            generated_step_id=_required_string(payload, "generated_step_id"),
            macro_step_id=_required_string(payload, "macro_step_id"),
            winner_candidate_id=_required_string(
                payload,
                "winner_candidate_id",
            ),
            generated_ordinal=int(payload["generated_ordinal"]),
        )


@dataclass(frozen=True)
class MacroExpansionRecord:
    authored_plan_id: str
    materialized_plan_id: str
    macro_step_id: str
    macro_id: str
    implementation_id: str
    preparation_signature: str
    winner_candidate_id: str
    search_signature: str
    winner_fragment_signature: str
    winner_output_signature: str
    authored_input_refs: Mapping[str, tuple[str, ...]]
    authored_roles: Mapping[str, str]
    chosen_roles: Mapping[str, str]
    generated_step_ids: tuple[str, ...]
    generated_step_signatures: Mapping[str, str]
    generated_return_roles: Mapping[str, Mapping[str, str]]
    export_map: Mapping[str, tuple[str, str]]
    generated_step_origins: tuple[MacroGeneratedStepOrigin, ...]
    expansion_signature: str = field(init=False)
    schema_version: str = "macro-expansion-record/v1"

    def __post_init__(self) -> None:
        for name in (
            "authored_plan_id",
            "materialized_plan_id",
            "macro_step_id",
            "macro_id",
            "implementation_id",
            "preparation_signature",
            "winner_candidate_id",
            "search_signature",
            "winner_fragment_signature",
            "winner_output_signature",
        ):
            if not getattr(self, name):
                raise ValueError(f"{name} must be non-empty")
        if not self.generated_step_ids:
            raise ValueError("Macro expansion must generate ordinary steps")
        authored_roles = dict(sorted(self.authored_roles.items()))
        authored_input_refs = {
            name: tuple(refs)
            for name, refs in sorted(self.authored_input_refs.items())
        }
        if any(
            not name or not refs or any(not ref for ref in refs)
            for name, refs in authored_input_refs.items()
        ):
            raise ValueError("Macro expansion authored input refs are invalid")
        chosen_roles = dict(sorted(self.chosen_roles.items()))
        if not chosen_roles or any(
            not role or not ref for role, ref in chosen_roles.items()
        ):
            raise ValueError("Macro expansion chosen roles are invalid")
        if any(not role or not ref for role, ref in authored_roles.items()):
            raise ValueError("Macro expansion authored roles are invalid")
        if len(self.generated_step_ids) != len(set(self.generated_step_ids)):
            raise ValueError("Macro expansion generated duplicate step ids")
        generated_step_signatures = dict(
            sorted(self.generated_step_signatures.items())
        )
        if set(generated_step_signatures) != set(self.generated_step_ids) or any(
            not signature for signature in generated_step_signatures.values()
        ):
            raise ValueError("Macro generated-step signatures are incomplete")
        generated_return_roles = {
            step_id: MappingProxyType(dict(sorted(roles.items())))
            for step_id, roles in sorted(self.generated_return_roles.items())
        }
        if set(generated_return_roles) != set(self.generated_step_ids) or any(
            not return_name or not semantic_role
            for roles in generated_return_roles.values()
            for return_name, semantic_role in roles.items()
        ):
            raise ValueError("Macro generated-return roles are incomplete")
        exports = dict(sorted(self.export_map.items()))
        if not exports:
            raise ValueError("Macro expansion requires at least one export")
        for export_name, producer in exports.items():
            if (
                not export_name
                or len(producer) != 2
                or producer[0] not in self.generated_step_ids
                or not producer[1]
            ):
                raise ValueError("Macro expansion export map is invalid")
        origins = tuple(self.generated_step_origins)
        if tuple(item.generated_step_id for item in origins) != (
            self.generated_step_ids
        ):
            raise ValueError("Macro generated-step origin order drift")
        if any(
            item.macro_step_id != self.macro_step_id
            or item.winner_candidate_id != self.winner_candidate_id
            or item.generated_ordinal != ordinal
            for ordinal, item in enumerate(origins)
        ):
            raise ValueError("Macro generated-step origin authority drift")
        object.__setattr__(self, "export_map", MappingProxyType(exports))
        object.__setattr__(
            self,
            "authored_input_refs",
            MappingProxyType(authored_input_refs),
        )
        object.__setattr__(
            self,
            "authored_roles",
            MappingProxyType(authored_roles),
        )
        object.__setattr__(
            self,
            "chosen_roles",
            MappingProxyType(chosen_roles),
        )
        object.__setattr__(
            self,
            "generated_step_signatures",
            MappingProxyType(generated_step_signatures),
        )
        object.__setattr__(
            self,
            "generated_return_roles",
            MappingProxyType(generated_return_roles),
        )
        object.__setattr__(self, "generated_step_origins", origins)
        object.__setattr__(
            self,
            "expansion_signature",
            stable_hash(self._payload(include_signature=False)),
        )

    def _payload(self, *, include_signature: bool) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "authored_plan_id": self.authored_plan_id,
            "materialized_plan_id": self.materialized_plan_id,
            "macro_step_id": self.macro_step_id,
            "macro_id": self.macro_id,
            "implementation_id": self.implementation_id,
            "preparation_signature": self.preparation_signature,
            "winner_candidate_id": self.winner_candidate_id,
            "search_signature": self.search_signature,
            "winner_fragment_signature": self.winner_fragment_signature,
            "winner_output_signature": self.winner_output_signature,
            "authored_input_refs": {
                name: list(refs)
                for name, refs in self.authored_input_refs.items()
            },
            "authored_roles": dict(self.authored_roles),
            "chosen_roles": dict(self.chosen_roles),
            "generated_step_ids": list(self.generated_step_ids),
            "generated_step_signatures": dict(
                self.generated_step_signatures
            ),
            "generated_return_roles": {
                step_id: dict(roles)
                for step_id, roles in self.generated_return_roles.items()
            },
            "export_map": {
                name: {"step_id": producer[0], "return": producer[1]}
                for name, producer in self.export_map.items()
            },
            "generated_step_origins": [
                item.to_payload() for item in self.generated_step_origins
            ],
        }
        if include_signature:
            payload["expansion_signature"] = self.expansion_signature
        return payload

    def to_payload(self) -> dict[str, Any]:
        return self._payload(include_signature=True)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "MacroExpansionRecord":
        exports = _required_mapping(payload, "export_map")
        record = cls(
            authored_plan_id=_required_string(payload, "authored_plan_id"),
            materialized_plan_id=_required_string(
                payload,
                "materialized_plan_id",
            ),
            macro_step_id=_required_string(payload, "macro_step_id"),
            macro_id=_required_string(payload, "macro_id"),
            implementation_id=_required_string(payload, "implementation_id"),
            preparation_signature=_required_string(
                payload,
                "preparation_signature",
            ),
            winner_candidate_id=_required_string(
                payload,
                "winner_candidate_id",
            ),
            search_signature=_required_string(payload, "search_signature"),
            winner_fragment_signature=_required_string(
                payload,
                "winner_fragment_signature",
            ),
            winner_output_signature=_required_string(
                payload,
                "winner_output_signature",
            ),
            authored_input_refs={
                str(name): tuple(
                    str(ref)
                    for ref in _required_sequence_value(
                        refs,
                        f"authored_input_refs.{name}",
                    )
                )
                for name, refs in _required_mapping(
                    payload,
                    "authored_input_refs",
                ).items()
            },
            authored_roles={
                str(name): str(ref)
                for name, ref in _required_mapping(
                    payload,
                    "authored_roles",
                ).items()
            },
            chosen_roles={
                str(name): str(ref)
                for name, ref in _required_mapping(
                    payload,
                    "chosen_roles",
                ).items()
            },
            generated_step_ids=tuple(
                str(item)
                for item in _required_sequence(payload, "generated_step_ids")
            ),
            generated_step_signatures={
                str(step_id): str(signature)
                for step_id, signature in _required_mapping(
                    payload,
                    "generated_step_signatures",
                ).items()
            },
            generated_return_roles={
                str(step_id): {
                    str(return_name): str(semantic_role)
                    for return_name, semantic_role in _required_mapping_value(
                        roles,
                        "generated_return_roles[]",
                    ).items()
                }
                for step_id, roles in _required_mapping(
                    payload,
                    "generated_return_roles",
                ).items()
            },
            export_map={
                str(name): (
                    _required_string(
                        _required_mapping_value(value, "export_map[]"),
                        "step_id",
                    ),
                    _required_string(
                        _required_mapping_value(value, "export_map[]"),
                        "return",
                    ),
                )
                for name, value in exports.items()
            },
            generated_step_origins=tuple(
                MacroGeneratedStepOrigin.from_payload(
                    _required_mapping_value(item, "generated_step_origins[]")
                )
                for item in _required_sequence(
                    payload,
                    "generated_step_origins",
                )
            ),
            schema_version=_required_string(payload, "schema_version"),
        )
        if record.schema_version != "macro-expansion-record/v1":
            raise ValueError("unsupported Macro expansion record contract")
        if payload.get("expansion_signature") != record.expansion_signature:
            raise ValueError("Macro expansion record signature drift")
        return record


@dataclass(frozen=True)
class MacroWinnerPlanMaterializationRequest:
    authority: MacroPreparationAuthority

    def __post_init__(self) -> None:
        fragment = self.authority.winner.candidate.fragment
        if fragment.scope_id != self.authority.scope_id:
            raise ValueError("Macro winner fragment scope drift")

    @property
    def fragment(self) -> FunctionalPlanFragment:
        return self.authority.winner.candidate.fragment


class MacroWinnerPlanMaterializationRequired(RuntimeError):
    """Internal control signal; it is not a planner/runtime failure."""

    def __init__(
        self,
        request: MacroWinnerPlanMaterializationRequest,
        *,
        restored_seed: FunctionalRestoredCallSeed | None = None,
        prefix_report: FunctionalTransactionalExecutionReport | None = None,
    ) -> None:
        self.request = request
        self.restored_seed = restored_seed
        self.prefix_report = prefix_report
        super().__init__(
            "selected Macro winner must be materialized as ordinary Plan steps"
        )


def materialize_macro_winner(
    plan: ScopedFunctionalPlan,
    request: MacroWinnerPlanMaterializationRequest,
    *,
    capability_catalog: FunctionalCapabilityCatalog,
) -> tuple[ScopedFunctionalPlan, MacroExpansionRecord]:
    """Replace exactly one Macro step and rewrite every public export edge."""

    authority = request.authority
    fragment = request.fragment
    authored_plan_id = scoped_functional_plan_id(plan)
    if authority.plan_id != authored_plan_id:
        raise _materialization_error(
            "Macro preparation refers to a different authored Plan",
            authority=authority,
            expected_plan_id=authored_plan_id,
        )
    generated_ids = tuple(step.step_id for step in fragment.steps)
    existing_ids = {step.step_id for step in plan.steps}
    collisions = tuple(
        sorted((set(generated_ids) & existing_ids) - {authority.call_id})
    )
    if collisions:
        raise _materialization_error(
            "Macro-generated step ids collide with the authored Plan",
            authority=authority,
            generated_step_ids=list(collisions),
        )
    for step in fragment.steps:
        capability = capability_catalog.get(step.capability_id)
        if capability is None or capability.kind != "function":
            raise _materialization_error(
                "Macro winner may only materialize ordinary Function steps",
                authority=authority,
                generated_step_id=step.step_id,
                capability_id=step.capability_id,
            )

    occurrence = _find_macro_occurrence(plan.root_scope, authority.call_id)
    if occurrence.count != 1 or occurrence.scope_id != authority.scope_id:
        raise _materialization_error(
            "Macro step does not have one stable owner in the authored Plan",
            authority=authority,
            occurrence_count=occurrence.count,
            observed_scope_id=occurrence.scope_id,
        )
    macro_step = occurrence.step
    assert macro_step is not None
    generated_steps = _transfer_macro_return_contract(
        macro_step,
        fragment=fragment,
    )
    export_map = dict(fragment.exports)
    rewritten_root, replacement_count = _rewrite_scope(
        plan.root_scope,
        macro_step_id=authority.call_id,
        generated_steps=generated_steps,
        export_map=export_map,
    )
    if replacement_count != 1:
        raise _materialization_error(
            "Macro winner replacement count drifted during Plan rewrite",
            authority=authority,
            replacement_count=replacement_count,
        )
    materialized = replace(plan, root_scope=rewritten_root)
    materialized_plan_id = scoped_functional_plan_id(materialized)
    winner_evaluations = tuple(
        item
        for item in authority.search_report.evaluations
        if item.candidate_id == authority.winner.candidate.candidate_id
    )
    if (
        len(winner_evaluations) != 1
        or not winner_evaluations[0].passed
        or not winner_evaluations[0].output_signature
    ):
        raise _materialization_error(
            "Macro winner has no authenticated shadow output",
            authority=authority,
        )
    record = MacroExpansionRecord(
        authored_plan_id=authored_plan_id,
        materialized_plan_id=materialized_plan_id,
        macro_step_id=authority.call_id,
        macro_id=authority.macro_id,
        implementation_id=authority.implementation_id,
        preparation_signature=authority.preparation_signature,
        winner_candidate_id=authority.winner.candidate.candidate_id,
        search_signature=authority.search_report.search_signature,
        winner_fragment_signature=fragment.fragment_signature,
        winner_output_signature=winner_evaluations[0].output_signature,
        authored_input_refs={
            name: tuple(_macro_argument_ref(value) for value in values)
            for name, values in macro_step.args.items()
        },
        authored_roles=authority.authored_roles,
        chosen_roles=authority.winner.candidate.role_bindings,
        generated_step_ids=generated_ids,
        generated_step_signatures={
            step.step_id: stable_hash(step.to_payload())
            for step in generated_steps
        },
        generated_return_roles=_generated_return_roles(
            generated_steps,
            role_source_steps=fragment.steps,
            capability_catalog=capability_catalog,
            authority=authority,
        ),
        export_map=export_map,
        generated_step_origins=tuple(
            MacroGeneratedStepOrigin(
                generated_step_id=step_id,
                macro_step_id=authority.call_id,
                winner_candidate_id=authority.winner.candidate.candidate_id,
                generated_ordinal=ordinal,
            )
            for ordinal, step_id in enumerate(generated_ids)
        ),
    )
    return materialized, record


def _generated_return_roles(
    steps: tuple[ScopedFunctionalStep, ...],
    *,
    role_source_steps: tuple[ScopedFunctionalStep, ...],
    capability_catalog: FunctionalCapabilityCatalog,
    authority: MacroPreparationAuthority,
) -> dict[str, dict[str, str]]:
    instance_roles: dict[tuple[str, str], str] = {}
    for consumer in role_source_steps:
        for values in consumer.args.values():
            for value in values:
                if not isinstance(value, ScopedDerivedResultRef):
                    continue
                key = (value.step_id, value.return_name)
                prior = instance_roles.get(key)
                if prior is not None and prior != value.semantic_role:
                    raise _materialization_error(
                        "Macro fragment assigns conflicting roles to one return",
                        authority=authority,
                        generated_step_id=value.step_id,
                        return_name=value.return_name,
                        expected_role=prior,
                        observed_role=value.semantic_role,
                    )
                instance_roles[key] = value.semantic_role
    result: dict[str, dict[str, str]] = {}
    for step in steps:
        capability = capability_catalog.get(step.capability_id)
        if capability is None:
            raise _materialization_error(
                "Macro-generated Function is missing from the capability catalog",
                authority=authority,
                generated_step_id=step.step_id,
                capability_id=step.capability_id,
            )
        declared_returns = {item.name: item for item in capability.returns}
        roles: dict[str, str] = {}
        for return_name, binding in step.return_bindings.items():
            if binding.kind != "derived":
                continue
            returned = declared_returns.get(return_name)
            if returned is None:
                raise _materialization_error(
                    "Macro-generated return is absent from its Function contract",
                    authority=authority,
                    generated_step_id=step.step_id,
                    capability_id=step.capability_id,
                    return_name=return_name,
                )
            roles[return_name] = instance_roles.get(
                (step.step_id, return_name),
                returned.semantic_role or returned.name,
            )
        result[step.step_id] = roles
    return result


def macro_standard_output_payload(value: Any) -> Any:
    if isinstance(value, sp.Basic):
        return str(sp.simplify(value))
    if isinstance(value, Mapping):
        return {
            str(key): macro_standard_output_payload(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [macro_standard_output_payload(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    to_payload = getattr(value, "to_payload", None)
    if callable(to_payload):
        return macro_standard_output_payload(to_payload())
    raise MacroPlanMaterializationError(
        "planner.macro_contract_invalid",
        "Macro output has no canonical standard representation",
        details={"runtime_value_type": type(value).__name__},
    )


def verify_macro_expansion_clean_outputs(
    record: MacroExpansionRecord,
    execution_report: Any | None,
) -> None:
    """Compare ordinary replay exports with the authenticated shadow winner."""

    if execution_report is None:
        return
    call_results = {
        item.call_id: item for item in execution_report.call_results
    }
    outputs: dict[str, Any] = {}
    for export_name, (step_id, return_name) in record.export_map.items():
        call_result = call_results.get(step_id)
        if call_result is None or call_result.status != "verified":
            return
        runtime_result = _runtime_result_for_public_return(
            call_result,
            return_name,
        )
        if runtime_result is None:
            raise MacroPlanMaterializationError(
                "planner.macro_winner_replay_drift",
                "verified generated step omitted a Macro winner export",
                details={
                    "macro_step_id": record.macro_step_id,
                    "generated_step_id": step_id,
                    "return_name": return_name,
                },
            )
        outputs[export_name] = macro_standard_output_payload(
            runtime_result.value
        )
    observed_signature = stable_hash(outputs)
    if observed_signature != record.winner_output_signature:
        raise MacroPlanMaterializationError(
            "planner.macro_winner_replay_drift",
            "ordinary Function replay differs from the shadow Macro winner",
            details={
                "macro_step_id": record.macro_step_id,
                "winner_candidate_id": record.winner_candidate_id,
                "expected_output_signature": record.winner_output_signature,
                "observed_output_signature": observed_signature,
            },
        )


def _runtime_result_for_public_return(
    result: Any,
    return_name: str,
) -> Any | None:
    writes = tuple(
        item for item in result.state_writes if item.return_name == return_name
    )
    if len(writes) == 1:
        write = writes[0]
        matches = tuple(
            item
            for item in result.runtime_results
            if item.output_key == write.output_key
            or item.produced_handle == write.produced_handle
        )
        if len(matches) == 1:
            return matches[0]
    matches = tuple(
        item
        for item in result.runtime_results
        if item.output_key == return_name
        or item.output_key.rsplit(".", 1)[-1] == return_name
    )
    return matches[0] if len(matches) == 1 else None


def rebase_macro_expansion_records(
    records: tuple[MacroExpansionRecord, ...],
    plan: ScopedFunctionalPlan,
) -> tuple[MacroExpansionRecord, ...]:
    """Keep provenance only for generated steps unchanged in this revision."""

    if not records:
        return ()
    steps = {step.step_id: step for step in plan.steps}
    plan_id = scoped_functional_plan_id(plan)
    retained: list[MacroExpansionRecord] = []
    for record in records:
        if any(
            step_id not in steps
            or stable_hash(steps[step_id].to_payload())
            != record.generated_step_signatures[step_id]
            for step_id in record.generated_step_ids
        ):
            continue
        if any(
            producer_step_id not in steps
            for producer_step_id, _return_name in record.export_map.values()
        ):
            continue
        retained.append(replace(record, materialized_plan_id=plan_id))
    return tuple(retained)


@dataclass(frozen=True)
class _MacroOccurrence:
    count: int = 0
    scope_id: str | None = None
    step: ScopedFunctionalStep | None = None


def _find_macro_occurrence(
    scope: ScopedFunctionalScope,
    macro_step_id: str,
) -> _MacroOccurrence:
    matches = tuple(
        step
        for step in (
            *scope.steps,
            *(step for goal in scope.goals for step in goal.steps),
        )
        if step.step_id == macro_step_id
    )
    result = _MacroOccurrence(
        count=len(matches),
        scope_id=scope.scope_ref if matches else None,
        step=matches[0] if len(matches) == 1 else None,
    )
    for child in scope.children:
        child_result = _find_macro_occurrence(child, macro_step_id)
        if child_result.count:
            result = _MacroOccurrence(
                count=result.count + child_result.count,
                scope_id=(
                    result.scope_id
                    if result.scope_id is not None
                    else child_result.scope_id
                ),
                step=result.step if result.step is not None else child_result.step,
            )
    return result


def _transfer_macro_return_contract(
    macro_step: ScopedFunctionalStep,
    *,
    fragment: FunctionalPlanFragment,
) -> tuple[ScopedFunctionalStep, ...]:
    steps = {
        step.step_id: _public_materialized_step(step)
        for step in fragment.steps
    }
    exports = dict(fragment.exports)
    required_exports = set(macro_step.return_bindings) | set(
        macro_step.return_expectations
    )
    missing = tuple(sorted(required_exports - set(exports)))
    if missing:
        raise MacroPlanMaterializationError(
            "planner.macro_contract_invalid",
            "Macro winner omitted a declared public return",
            details={
                "macro_step_id": macro_step.step_id,
                "missing_exports": list(missing),
            },
        )
    for macro_return, (producer_step_id, producer_return) in exports.items():
        producer = steps[producer_step_id]
        return_bindings = dict(producer.return_bindings)
        return_expectations = dict(producer.return_expectations)
        macro_binding = macro_step.return_bindings.get(macro_return)
        existing_binding = return_bindings.get(producer_return)
        if (
            macro_binding is not None
            and existing_binding is not None
            and existing_binding.to_payload() != macro_binding.to_payload()
        ):
            raise MacroPlanMaterializationError(
                "planner.macro_contract_invalid",
                "Macro export conflicts with its generated Function binding",
                details={
                    "macro_step_id": macro_step.step_id,
                    "macro_return": macro_return,
                    "producer_step_id": producer_step_id,
                    "producer_return": producer_return,
                },
            )
        if macro_binding is not None:
            return_bindings[producer_return] = macro_binding
        macro_expectation = macro_step.return_expectations.get(macro_return)
        existing_expectation = return_expectations.get(producer_return)
        if (
            macro_expectation is not None
            and existing_expectation is not None
            and existing_expectation != macro_expectation
        ):
            raise MacroPlanMaterializationError(
                "planner.macro_contract_invalid",
                "Macro export conflicts with its generated return expectation",
                details={
                    "macro_step_id": macro_step.step_id,
                    "macro_return": macro_return,
                    "producer_step_id": producer_step_id,
                    "producer_return": producer_return,
                },
            )
        if macro_expectation is not None:
            return_expectations[producer_return] = macro_expectation
        steps[producer_step_id] = replace(
            producer,
            return_bindings=return_bindings,
            return_expectations=return_expectations,
        )
    return tuple(steps[step.step_id] for step in fragment.steps)


def _public_materialized_step(
    step: ScopedFunctionalStep,
) -> ScopedFunctionalStep:
    """Drop candidate-only derived authority before canonical Plan assembly."""

    return replace(
        step,
        args={
            name: tuple(
                value.local_ref
                if isinstance(value, ScopedDerivedResultRef)
                else value
                for value in values
            )
            for name, values in step.args.items()
        },
    )


def _rewrite_scope(
    scope: ScopedFunctionalScope,
    *,
    macro_step_id: str,
    generated_steps: tuple[ScopedFunctionalStep, ...],
    export_map: Mapping[str, tuple[str, str]],
) -> tuple[ScopedFunctionalScope, int]:
    scope_steps, scope_count = _rewrite_step_sequence(
        scope.steps,
        macro_step_id=macro_step_id,
        generated_steps=generated_steps,
        export_map=export_map,
    )
    goals: list[ScopedFunctionalGoalPlan] = []
    replacement_count = scope_count
    for goal in scope.goals:
        steps, count = _rewrite_step_sequence(
            goal.steps,
            macro_step_id=macro_step_id,
            generated_steps=generated_steps,
            export_map=export_map,
        )
        replacement_count += count
        answer = goal.answer_from
        if answer.step_id == macro_step_id:
            producer = _require_export(
                export_map,
                answer.return_name,
                macro_step_id=macro_step_id,
            )
            answer = ScopedFunctionalAnswerSource(
                step_id=producer[0],
                return_name=producer[1],
            )
        goals.append(replace(goal, steps=steps, answer_from=answer))
    children: list[ScopedFunctionalScope] = []
    for child in scope.children:
        rewritten, count = _rewrite_scope(
            child,
            macro_step_id=macro_step_id,
            generated_steps=generated_steps,
            export_map=export_map,
        )
        replacement_count += count
        children.append(rewritten)
    return (
        replace(
            scope,
            steps=scope_steps,
            goals=tuple(goals),
            children=tuple(children),
        ),
        replacement_count,
    )


def _rewrite_step_sequence(
    steps: tuple[ScopedFunctionalStep, ...],
    *,
    macro_step_id: str,
    generated_steps: tuple[ScopedFunctionalStep, ...],
    export_map: Mapping[str, tuple[str, str]],
) -> tuple[tuple[ScopedFunctionalStep, ...], int]:
    result: list[ScopedFunctionalStep] = []
    replacement_count = 0
    for step in steps:
        if step.step_id == macro_step_id:
            result.extend(generated_steps)
            replacement_count += 1
            continue
        result.append(
            replace(
                step,
                args={
                    name: tuple(
                        _rewrite_ref(
                            value,
                            macro_step_id=macro_step_id,
                            export_map=export_map,
                        )
                        for value in values
                    )
                    for name, values in step.args.items()
                },
            )
        )
    return tuple(result), replacement_count


def _rewrite_ref(
    value: ScopedFunctionalRef,
    *,
    macro_step_id: str,
    export_map: Mapping[str, tuple[str, str]],
) -> ScopedFunctionalRef:
    if not isinstance(value, ScopedStepResultRef) or value.step_id != macro_step_id:
        return value
    producer = _require_export(
        export_map,
        value.return_name,
        macro_step_id=macro_step_id,
    )
    if isinstance(value, ScopedDerivedResultRef):
        return replace(value, step_id=producer[0], return_name=producer[1])
    if isinstance(value, ScopedPublishedGoalResultRef):
        return replace(value, step_id=producer[0], return_name=producer[1])
    return ScopedStepResultRef(step_id=producer[0], return_name=producer[1])


def _require_export(
    export_map: Mapping[str, tuple[str, str]],
    return_name: str,
    *,
    macro_step_id: str,
) -> tuple[str, str]:
    producer = export_map.get(return_name)
    if producer is None:
        raise MacroPlanMaterializationError(
            "planner.macro_contract_invalid",
            "Macro winner omitted a consumed public return",
            details={
                "macro_step_id": macro_step_id,
                "return_name": return_name,
            },
        )
    return producer


def _materialization_error(
    message: str,
    *,
    authority: MacroPreparationAuthority,
    **details: Any,
) -> MacroPlanMaterializationError:
    return MacroPlanMaterializationError(
        "planner.macro_contract_invalid",
        message,
        details={
            "macro_step_id": authority.call_id,
            "macro_id": authority.macro_id,
            **details,
        },
    )


def _macro_argument_ref(value: ScopedFunctionalRef) -> str:
    if isinstance(value, ScopedDerivedResultRef):
        return value.local_ref
    if isinstance(value, ScopedStepResultRef):
        return f"{value.step_id}.{value.return_name}"
    if isinstance(value, str):
        return value
    raise ValueError("Macro argument has no stable semantic ref")


def _required_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _required_mapping(
    payload: Mapping[str, Any],
    key: str,
) -> Mapping[str, Any]:
    return _required_mapping_value(payload.get(key), key)


def _required_mapping_value(value: Any, key: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{key} must be an object")
    return value


def _required_sequence(payload: Mapping[str, Any], key: str) -> tuple[Any, ...]:
    return _required_sequence_value(payload.get(key), key)


def _required_sequence_value(value: Any, key: str) -> tuple[Any, ...]:
    if not isinstance(value, (tuple, list)):
        raise ValueError(f"{key} must be an array")
    return tuple(value)
