"""Publish verified Boolean Method outputs as scope-local Conditions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from shuxueshuo_server.solver.contracts import (
    PredicatePublicationSpec,
    TypedValue,
    VerificationOutcome,
)
from shuxueshuo_server.solver.extraction.source_identity import stable_hash
from shuxueshuo_server.solver.runtime.functional_diagnostics import (
    StatelessMethodError,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    FunctionalCapability,
    FunctionalReturnAllocation,
    ResolvedFunctionalValue,
)
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.context import RuntimeContext
from shuxueshuo_server.solver.runtime.models import StepPlan
from shuxueshuo_server.solver.runtime.planner_state_context import Condition
from shuxueshuo_server.solver.runtime.runtime_value_signature import (
    runtime_value_signature,
)
from shuxueshuo_server.solver.utils import unique_ordered


@dataclass(frozen=True)
class PredicatePublicationAuthority:
    call_id: str
    method_id: str
    invocation_id: str
    method_output_name: str
    function_return_name: str
    condition_id: str
    condition_kind: str
    owner_scope: str
    canonical_handle: str
    object_roles: tuple[tuple[str, tuple[str, ...]], ...]
    result_roles: tuple[tuple[str, tuple[str, ...]], ...]
    attested_value_signatures: tuple[tuple[str, str], ...]
    runtime_path: str
    allocation_signature: str
    authority_signature: str
    schema_version: str = "predicate-publication-authority/v1"

    @classmethod
    def create(
        cls,
        *,
        call_id: str,
        method_id: str,
        invocation_id: str,
        publication: PredicatePublicationSpec,
        function_return_name: str,
        allocation: FunctionalReturnAllocation,
        object_roles: tuple[tuple[str, tuple[str, ...]], ...],
        result_roles: tuple[tuple[str, tuple[str, ...]], ...],
        attested_value_signatures: tuple[tuple[str, str], ...],
        runtime_path: str,
    ) -> "PredicatePublicationAuthority":
        condition_id = derived_condition_id(
            call_id=call_id,
            return_name=function_return_name,
            condition_kind=publication.condition_kind,
            scope_id=allocation.valid_scope,
        )
        payload = {
            "call_id": call_id,
            "method_id": method_id,
            "invocation_id": invocation_id,
            "method_output_name": publication.output_name,
            "function_return_name": function_return_name,
            "condition_id": condition_id,
            "condition_kind": publication.condition_kind,
            "owner_scope": allocation.valid_scope,
            "canonical_handle": allocation.state_handle or allocation.handle,
            "object_roles": {
                role: list(refs) for role, refs in object_roles
            },
            "result_roles": {
                role: list(refs) for role, refs in result_roles
            },
            "attested_value_signatures": dict(attested_value_signatures),
            "runtime_path": runtime_path,
            "allocation_signature": stable_hash(allocation.to_payload()),
        }
        return cls(
            call_id=call_id,
            method_id=method_id,
            invocation_id=invocation_id,
            method_output_name=publication.output_name,
            function_return_name=function_return_name,
            condition_id=condition_id,
            condition_kind=publication.condition_kind,
            owner_scope=allocation.valid_scope,
            canonical_handle=allocation.state_handle or allocation.handle,
            object_roles=object_roles,
            result_roles=result_roles,
            attested_value_signatures=attested_value_signatures,
            runtime_path=runtime_path,
            allocation_signature=payload["allocation_signature"],
            authority_signature=stable_hash(payload),
        )

    def authority_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "call_id": self.call_id,
            "method_id": self.method_id,
            "invocation_id": self.invocation_id,
            "method_output_name": self.method_output_name,
            "function_return_name": self.function_return_name,
            "condition_id": self.condition_id,
            "condition_kind": self.condition_kind,
            "owner_scope": self.owner_scope,
            "canonical_handle": self.canonical_handle,
            "object_roles": {
                role: list(refs) for role, refs in self.object_roles
            },
            "result_roles": {
                role: list(refs) for role, refs in self.result_roles
            },
            "attested_value_signatures": dict(
                self.attested_value_signatures
            ),
            "runtime_path": self.runtime_path,
            "allocation_signature": self.allocation_signature,
            "authority_signature": self.authority_signature,
        }


@dataclass(frozen=True)
class PredicatePublicationResult:
    outcomes: tuple[VerificationOutcome, ...]
    conditions: tuple[Condition, ...]
    authorities: tuple[PredicatePublicationAuthority, ...]


class PredicateConditionPublicationService:
    """Materialize predicates after Method execution and before commit."""

    def materialize(
        self,
        *,
        call_id: str,
        capability: FunctionalCapability,
        plans: Sequence[StepPlan],
        allocations: Sequence[FunctionalReturnAllocation],
        resolved_args: Mapping[str, Sequence[ResolvedFunctionalValue]],
        branch: RuntimeContext,
        method_specs: MethodSpecRegistry,
    ) -> PredicatePublicationResult:
        if capability.kind != "function":
            return PredicatePublicationResult((), (), ())
        function_returns = {
            item.output_key: item
            for item in capability.source.returns
            if item.output_key is not None
            and item.predicate_publication is not None
        }
        if not function_returns:
            return PredicatePublicationResult((), (), ())
        allocations_by_return = {item.return_name: item for item in allocations}
        outcomes: list[VerificationOutcome] = []
        conditions: list[Condition] = []
        authorities: list[PredicatePublicationAuthority] = []
        for plan in plans:
            for invocation in plan.invocations:
                method_spec = method_specs.require(invocation.method_id)
                for publication in method_spec.predicate_publications:
                    function_return = function_returns.get(publication.output_name)
                    if function_return is None:
                        continue
                    allocation = allocations_by_return.get(function_return.name)
                    if allocation is None:
                        raise _contract_error(
                            call_id,
                            invocation.method_id,
                            publication.output_name,
                            "predicate return allocation is missing",
                        )
                    source_path = invocation.outputs.get(publication.output_name)
                    runtime_path = plan.promote_outputs.get(source_path or "")
                    if source_path is None or runtime_path is None:
                        raise _contract_error(
                            call_id,
                            invocation.method_id,
                            publication.output_name,
                            "predicate runtime destination is missing",
                        )
                    typed = branch.read_path(
                        runtime_path,
                        from_scope_id=invocation.scope,
                        expected_type="Boolean",
                    )
                    passed = bool(typed.value)
                    outcome = VerificationOutcome(
                        passed=passed,
                        check_code=publication.condition_kind,
                        expected=True,
                        observed=passed,
                    )
                    outcomes.append(outcome)
                    if not passed:
                        raise StatelessMethodError(
                            "functional.predicate_false",
                            "mathematical predicate evaluated to false",
                            category="check",
                            retryability="planner_repairable",
                            method_id=invocation.method_id,
                            step_id=call_id,
                            expected={
                                "condition": publication.condition_kind,
                                "verified": True,
                            },
                            observed={"verified": False},
                            repair_action="choose_another_subplan_candidate",
                        )
                    roles = condition_roles_from_resolved_args(
                        publication,
                        resolved_args=resolved_args,
                    )
                    result_roles = condition_result_roles_from_resolved_args(
                        publication,
                        resolved_args=resolved_args,
                    )
                    attested_value_signatures = (
                        _attested_value_signatures(
                            publication,
                            invocation=invocation,
                            branch=branch,
                        )
                    )
                    authority = PredicatePublicationAuthority.create(
                        call_id=call_id,
                        method_id=invocation.method_id,
                        invocation_id=invocation.invocation_id,
                        publication=publication,
                        function_return_name=function_return.name,
                        allocation=allocation,
                        object_roles=roles,
                        result_roles=result_roles,
                        attested_value_signatures=(
                            attested_value_signatures
                        ),
                        runtime_path=runtime_path,
                    )
                    condition = Condition(
                        condition_id=authority.condition_id,
                        kind=authority.condition_kind,
                        scope_id=authority.owner_scope,
                        canonical_handle=authority.canonical_handle,
                        object_roles=authority.object_roles,
                        source_step_id=call_id,
                        valid_scope=authority.owner_scope,
                        result_roles=authority.result_roles,
                        attested_value_signatures=(
                            authority.attested_value_signatures
                        ),
                    )
                    branch.write_path(
                        runtime_path,
                        TypedValue(
                            "Condition",
                            condition.to_payload(),
                            source=invocation.method_id,
                        ),
                        from_scope_id=invocation.scope,
                        allow_overwrite=True,
                        allow_ancestor_write=True,
                    )
                    conditions.append(condition)
                    authorities.append(authority)
        return PredicatePublicationResult(
            tuple(outcomes),
            tuple(conditions),
            tuple(authorities),
        )


def derived_condition_id(
    *,
    call_id: str,
    return_name: str,
    condition_kind: str,
    scope_id: str,
) -> str:
    signature = stable_hash(
        {
            "call_id": call_id,
            "return_name": return_name,
            "condition_kind": condition_kind,
            "scope_id": scope_id,
        }
    )
    return f"condition:derived:{signature[:24]}"


def condition_roles_from_resolved_args(
    publication: PredicatePublicationSpec,
    *,
    resolved_args: Mapping[str, Sequence[ResolvedFunctionalValue]],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Project direct semantic objects, never a value's dependency closure."""

    roles: list[tuple[str, tuple[str, ...]]] = []
    for role in publication.related_input_roles:
        refs = tuple(
            unique_ordered(
                ref
                for value in resolved_args.get(role, ())
                for ref in _condition_role_object_refs(value)
                if isinstance(ref, str) and ref
            )
        )
        if refs:
            roles.append((role, refs))
    return tuple(roles)


def _condition_role_object_refs(
    value: ResolvedFunctionalValue,
) -> tuple[str, ...]:
    if value.object_ref is not None:
        return (value.object_ref,)
    if value.condition_id is not None:
        return unique_ordered(
            ref
            for _role, refs in value.object_roles
            for ref in refs
        )
    return unique_ordered(
        ref
        for binding in value.lineage.object_roles
        for ref in binding.object_refs
    )


def condition_result_roles_from_resolved_args(
    publication: PredicatePublicationSpec,
    *,
    resolved_args: Mapping[str, Sequence[ResolvedFunctionalValue]],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Project exact call-result identities separately from MathObject roles."""

    roles: list[tuple[str, tuple[str, ...]]] = []
    for role in publication.related_input_roles:
        result_ids = tuple(
            unique_ordered(
                f"{value.source_call_id}.{value.return_name}"
                for value in resolved_args.get(role, ())
                if value.source_call_id is not None
                and value.return_name is not None
                and value.object_ref is None
                and value.condition_id is None
            )
        )
        if result_ids:
            roles.append((role, result_ids))
    return tuple(roles)


def _attested_value_signatures(
    publication: PredicatePublicationSpec,
    *,
    invocation: Any,
    branch: RuntimeContext,
) -> tuple[tuple[str, str], ...]:
    signatures: list[tuple[str, str]] = []
    for role in publication.attested_input_roles:
        source = invocation.inputs.get(role)
        if source is None:
            raise _contract_error(
                invocation.invocation_id,
                invocation.method_id,
                publication.output_name,
                f"attested predicate input {role!r} is missing",
            )
        paths = source if isinstance(source, tuple) else (source,)
        values = tuple(
            branch.read_path(path, from_scope_id=invocation.scope).value
            for path in paths
        )
        value: Any = values[0] if len(values) == 1 else values
        signatures.append((role, runtime_value_signature(value)))
    return tuple(signatures)


def _contract_error(
    call_id: str,
    method_id: str,
    output_name: str,
    message: str,
) -> StatelessMethodError:
    return StatelessMethodError(
        "planner.predicate_publication_contract_invalid",
        message,
        category="configuration",
        retryability="configuration",
        method_id=method_id,
        step_id=call_id,
        expected={"output": output_name, "authority": "exact"},
        observed={"authority": "missing_or_drifted"},
        repair_action="fix_runtime_contract",
    )


__all__ = [
    "PredicateConditionPublicationService",
    "PredicatePublicationAuthority",
    "PredicatePublicationResult",
    "condition_roles_from_resolved_args",
    "derived_condition_id",
]
