"""Transient Function fragments used only for isolated Macro candidate search."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, Literal, Mapping, Sequence

import sympy as sp

from shuxueshuo_server.solver.contracts import (
    PointRef,
    TypedValue,
    VerificationOutcome,
)
from shuxueshuo_server.solver.extraction.source_identity import stable_hash
from shuxueshuo_server.solver.math_kernel import SympyKernel
from shuxueshuo_server.solver.runtime.function_specs import FunctionSpecRegistry
from shuxueshuo_server.solver.runtime.context import RuntimeContext
from shuxueshuo_server.solver.runtime.executor import InvocationExecutor
from shuxueshuo_server.solver.runtime.macro_blueprints import (
    MacroSemanticBlueprint,
)
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedDerivedResultRef,
    ScopedFunctionalStep,
    ScopedStepResultRef,
    scoped_functional_step_from_payload,
)
from shuxueshuo_server.solver.runtime.methods import (
    StatelessMethodRegistry,
    default_stateless_registry,
)
from shuxueshuo_server.solver.runtime.method_input_read_authority import (
    EntityIdentityReadSource,
    InvocationResultReadSource,
    MethodInputReadAuthority,
    MethodInputReadSource,
)
from shuxueshuo_server.solver.runtime.models import (
    MethodInvocation,
    StepGoal,
    StepPlan,
)


CandidateSelectionMode = Literal["equivalent", "minimize", "maximize"]


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {
                str(key): _freeze_json(child)
                for key, child in sorted(value.items(), key=lambda item: str(item[0]))
            }
        )
    if isinstance(value, (tuple, list)):
        return tuple(_freeze_json(item) for item in value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise ValueError("verified subplan values must be JSON-compatible")


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [_thaw_json(item) for item in value]
    return value


def _canonical_runtime_payload(value: Any) -> Any:
    if isinstance(value, sp.Basic):
        return {"sympy": sp.srepr(value)}
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_runtime_payload(child)
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_canonical_runtime_payload(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    to_payload = getattr(value, "to_payload", None)
    if callable(to_payload):
        return _canonical_runtime_payload(to_payload())
    raise ValueError(
        "fragment runtime value has no canonical serialization: "
        f"{type(value).__name__}"
    )


def _fragment_argument_ref(value: Any) -> str:
    if isinstance(value, ScopedDerivedResultRef):
        return value.local_ref
    if isinstance(value, ScopedStepResultRef):
        return f"{value.step_id}.{value.return_name}"
    if isinstance(value, str):
        return value
    raise ValueError("fragment argument has no semantic identity")


@dataclass(frozen=True)
class FunctionalPlanFragment:
    """A transient Function subgraph generated for one Macro shadow candidate."""

    scope_id: str
    steps: tuple[ScopedFunctionalStep, ...]
    exports: Mapping[str, tuple[str, str]]
    dependency_envelope: tuple[str, ...] = ()
    blueprint_id: str | None = None
    fragment_signature: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.scope_id or not self.steps:
            raise ValueError("FunctionalPlan fragment requires scope and steps")
        step_ids = tuple(item.step_id for item in self.steps)
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("FunctionalPlan fragment step ids must be unique")
        exports = dict(sorted(self.exports.items()))
        for export_name, producer in exports.items():
            if not export_name or len(producer) != 2 or producer[0] not in step_ids:
                raise ValueError("FunctionalPlan fragment export is invalid")
        object.__setattr__(self, "exports", MappingProxyType(exports))
        object.__setattr__(
            self,
            "dependency_envelope",
            tuple(sorted(set(self.dependency_envelope))),
        )
        object.__setattr__(
            self,
            "fragment_signature",
            stable_hash(self.alpha_normalized_payload()),
        )

    def alpha_normalized_payload(self) -> dict[str, Any]:
        """Ignore authored step/derived names while retaining graph semantics."""

        step_tokens = {
            step.step_id: f"step:{index}"
            for index, step in enumerate(self.steps)
        }
        derived_tokens = {
            binding.ref: f"{step_tokens[step.step_id]}:return:{return_name}"
            for step in self.steps
            for return_name, binding in step.return_bindings.items()
            if binding.kind == "derived"
        }

        def normalize_ref(value: Any) -> Any:
            if isinstance(value, ScopedDerivedResultRef):
                return {
                    "from": step_tokens.get(value.step_id, value.step_id),
                    "return": value.return_name,
                    "named": True,
                }
            if isinstance(value, ScopedStepResultRef):
                return {
                    "from": step_tokens.get(value.step_id, value.step_id),
                    "return": value.return_name,
                }
            if isinstance(value, str):
                return derived_tokens.get(value, value)
            return value

        steps_payload = []
        for step in self.steps:
            steps_payload.append(
                {
                    "step": step_tokens[step.step_id],
                    "capability_id": step.capability_id,
                    "args": {
                        name: [normalize_ref(value) for value in values]
                        for name, values in step.args.items()
                    },
                    "return_bindings": {
                        name: (
                            {
                                "kind": "derived",
                                "ref": derived_tokens[binding.ref],
                            }
                            if binding.kind == "derived"
                            else {"kind": "existing", "ref": binding.ref}
                        )
                        for name, binding in step.return_bindings.items()
                    },
                    "return_expectations": dict(step.return_expectations),
                }
            )
        return {
            "scope_id": self.scope_id,
            "steps": steps_payload,
            "exports": {
                name: {
                    "from": step_tokens[producer],
                    "return": return_name,
                }
                for name, (producer, return_name) in self.exports.items()
            },
            "dependency_envelope": list(self.dependency_envelope),
            "blueprint_id": self.blueprint_id,
        }

    @property
    def function_step_count(self) -> int:
        return len(self.steps)

    def to_payload(self) -> dict[str, Any]:
        return {
            "scope_id": self.scope_id,
            "steps": [_fragment_step_payload(item) for item in self.steps],
            "exports": {
                key: {"step_id": value[0], "return": value[1]}
                for key, value in self.exports.items()
            },
            "dependency_envelope": list(self.dependency_envelope),
            "blueprint_id": self.blueprint_id,
            "fragment_signature": self.fragment_signature,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "FunctionalPlanFragment":
        exports_payload = _required_mapping(payload.get("exports"), "exports")
        fragment = cls(
            scope_id=_required_string(payload, "scope_id"),
            steps=tuple(
                scoped_functional_step_from_payload(
                    _required_mapping(item, "steps[]")
                )
                for item in _required_sequence(payload.get("steps"), "steps")
            ),
            exports={
                str(name): (
                    _required_string(
                        _required_mapping(value, f"exports.{name}"),
                        "step_id",
                    ),
                    _required_string(
                        _required_mapping(value, f"exports.{name}"),
                        "return",
                    ),
                )
                for name, value in exports_payload.items()
            },
            dependency_envelope=tuple(
                str(item)
                for item in _required_sequence(
                    payload.get("dependency_envelope", ()),
                    "dependency_envelope",
                )
            ),
            blueprint_id=(
                str(payload["blueprint_id"])
                if payload.get("blueprint_id") is not None
                else None
            ),
        )
        if payload.get("fragment_signature") != fragment.fragment_signature:
            raise ValueError("FunctionalPlan fragment signature drift")
        return fragment


def _fragment_step_payload(step: ScopedFunctionalStep) -> dict[str, Any]:
    """Serialize internal ref authority without changing the public v3 wire."""

    payload = step.to_payload()
    payload["args"] = {
        name: (
            encoded[0]
            if len(encoded) == 1
            else encoded
        )
        for name, values in step.args.items()
        for encoded in (
            [
                value.authority_payload()
                if isinstance(value, ScopedDerivedResultRef)
                else value.to_payload()
                if isinstance(value, ScopedStepResultRef)
                else value
                for value in values
            ],
        )
    }
    return payload


@dataclass(frozen=True)
class SearchCandidate:
    candidate_id: str
    fragment: FunctionalPlanFragment
    role_bindings: Mapping[str, str]
    strategy_id: str
    symbolic_complexity: int = 0

    def __post_init__(self) -> None:
        if not self.candidate_id or not self.strategy_id:
            raise ValueError("search candidate ids must be non-empty")
        if self.symbolic_complexity < 0:
            raise ValueError("symbolic complexity must be non-negative")
        object.__setattr__(
            self,
            "role_bindings",
            MappingProxyType(dict(sorted(self.role_bindings.items()))),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "strategy_id": self.strategy_id,
            "role_bindings": dict(self.role_bindings),
            "symbolic_complexity": self.symbolic_complexity,
            "fragment": self.fragment.to_payload(),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "SearchCandidate":
        return cls(
            candidate_id=_required_string(payload, "candidate_id"),
            fragment=FunctionalPlanFragment.from_payload(
                _required_mapping(payload.get("fragment"), "fragment")
            ),
            role_bindings={
                str(key): str(value)
                for key, value in _required_mapping(
                    payload.get("role_bindings"), "role_bindings"
                ).items()
            },
            strategy_id=_required_string(payload, "strategy_id"),
            symbolic_complexity=int(payload.get("symbolic_complexity", 0)),
        )

    @property
    def dependency_envelope(self) -> tuple[str, ...]:
        return self.fragment.dependency_envelope


@dataclass(frozen=True)
class CandidateEvaluation:
    candidate_id: str
    passed: bool
    standard_outputs: Mapping[str, Any] = field(default_factory=dict)
    verification: tuple[VerificationOutcome, ...] = ()
    failure_code: str | None = None
    shadow_execution_signature: str | None = None
    output_signature: str | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        outputs = _freeze_json(self.standard_outputs)
        object.__setattr__(self, "standard_outputs", outputs)
        object.__setattr__(self, "verification", tuple(self.verification))
        if self.passed and any(not item.passed for item in self.verification):
            raise ValueError("passed candidate contains a failed verification")
        if not self.passed and self.failure_code is None:
            raise ValueError("failed candidate requires failure_code")
        if not self.passed and self.shadow_execution_signature is not None:
            raise ValueError("failed candidate cannot carry a shadow signature")
        if self.passed:
            object.__setattr__(
                self,
                "output_signature",
                stable_hash(_thaw_json(outputs)),
            )

    def to_payload(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "passed": self.passed,
            "standard_outputs": _thaw_json(self.standard_outputs),
            "verification": [item.to_payload() for item in self.verification],
            "failure_code": self.failure_code,
            "shadow_execution_signature": self.shadow_execution_signature,
            "output_signature": self.output_signature,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "CandidateEvaluation":
        verification = tuple(
            VerificationOutcome(
                passed=bool(item["passed"]),
                check_code=_required_string(item, "check_code"),
                expected=item.get("expected"),
                observed=item.get("observed"),
                evidence=tuple(
                    str(value)
                    for value in _required_sequence(
                        item.get("evidence", ()),
                        "verification.evidence",
                    )
                ),
            )
            for item in (
                _required_mapping(value, "verification[]")
                for value in _required_sequence(
                    payload.get("verification", ()),
                    "verification",
                )
            )
        )
        evaluation = cls(
            candidate_id=_required_string(payload, "candidate_id"),
            passed=bool(payload.get("passed")),
            standard_outputs=_required_mapping(
                payload.get("standard_outputs", {}),
                "standard_outputs",
            ),
            verification=verification,
            failure_code=(
                str(payload["failure_code"])
                if payload.get("failure_code") is not None
                else None
            ),
            shadow_execution_signature=(
                str(payload["shadow_execution_signature"])
                if payload.get("shadow_execution_signature") is not None
                else None
            ),
        )
        if payload.get("output_signature") != evaluation.output_signature:
            raise ValueError("candidate evaluation output signature drift")
        return evaluation


@dataclass(frozen=True)
class FragmentRuntimeSource:
    """One exact, externally-owned value consumed by a fragment Function."""

    semantic_ref: str
    runtime_type: str
    value: Any
    authority_signature: str
    runtime_path: str | None = None
    read_source: MethodInputReadSource | None = None

    def __post_init__(self) -> None:
        if not all(
            (
                self.semantic_ref,
                self.runtime_type,
                self.authority_signature,
            )
        ):
            raise ValueError("fragment runtime source authority is incomplete")


@dataclass(frozen=True)
class FragmentStepExecution:
    step_id: str
    capability_id: str
    method_id: str
    outputs: Mapping[str, Any]
    source_authority_signatures: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "outputs", MappingProxyType(dict(self.outputs)))
        object.__setattr__(
            self,
            "source_authority_signatures",
            tuple(self.source_authority_signatures),
        )


@dataclass(frozen=True)
class FunctionalPlanFragmentExecution:
    """Pure execution result for one ordinary-Function fragment."""

    fragment_signature: str
    passed: bool
    step_executions: tuple[FragmentStepExecution, ...]
    standard_outputs: Mapping[str, Any]
    verification: tuple[VerificationOutcome, ...]
    failure_code: str | None = None
    execution_signature: str = field(init=False)

    def __post_init__(self) -> None:
        if self.passed == (self.failure_code is not None):
            raise ValueError("fragment execution pass/failure contract is invalid")
        object.__setattr__(
            self,
            "step_executions",
            tuple(self.step_executions),
        )
        object.__setattr__(
            self,
            "standard_outputs",
            MappingProxyType(dict(self.standard_outputs)),
        )
        object.__setattr__(self, "verification", tuple(self.verification))
        object.__setattr__(
            self,
            "execution_signature",
            stable_hash(self.authority_payload()),
        )

    def authority_payload(self) -> dict[str, Any]:
        return {
            "fragment_signature": self.fragment_signature,
            "passed": self.passed,
            "steps": [
                {
                    "step_id": item.step_id,
                    "capability_id": item.capability_id,
                    "method_id": item.method_id,
                    "outputs": _canonical_runtime_payload(item.outputs),
                    "source_authority_signatures": list(
                        item.source_authority_signatures
                    ),
                }
                for item in self.step_executions
            ],
            "standard_outputs": _canonical_runtime_payload(
                self.standard_outputs
            ),
            "verification": [item.to_payload() for item in self.verification],
            "failure_code": self.failure_code,
        }

    def output_for_capability(
        self,
        capability_id: str,
        return_name: str,
    ) -> Any | None:
        matches = [
            item.outputs[return_name]
            for item in self.step_executions
            if item.capability_id == capability_id
            and return_name in item.outputs
        ]
        if len(matches) > 1:
            raise ValueError(
                "fragment capability output is not unique: "
                f"{capability_id}.{return_name}"
            )
        return matches[0] if matches else None


def _fragment_execution_result(
    fragment: FunctionalPlanFragment,
    *,
    passed: bool,
    executions: Sequence[FragmentStepExecution],
    verification: Sequence[VerificationOutcome],
    standard_outputs: Mapping[str, Any] = MappingProxyType({}),
    failure_code: str | None = None,
) -> FunctionalPlanFragmentExecution:
    return FunctionalPlanFragmentExecution(
        fragment_signature=fragment.fragment_signature,
        passed=passed,
        step_executions=tuple(executions),
        standard_outputs=standard_outputs,
        verification=tuple(verification),
        failure_code=failure_code,
    )


def fragment_published_condition_refs(
    fragment: FunctionalPlanFragment,
    execution: FunctionalPlanFragmentExecution,
) -> Mapping[str, str]:
    """Project verified predicate publications with the LLM witness naming rule."""

    if (
        not execution.passed
        or execution.fragment_signature != fragment.fragment_signature
    ):
        raise ValueError(
            "planner.verified_subplan_contract_invalid: fragment execution "
            "cannot publish Condition witness entries"
        )
    executed_by_step = {item.step_id: item for item in execution.step_executions}
    verified_predicates = {
        (step_id, item.check_code)
        for item in execution.verification
        if item.passed and item.expected is True and item.observed is True
        for step_id in item.evidence
    }
    records: list[tuple[str, str, str]] = []
    return_name_counts: dict[str, int] = {}
    for step in fragment.steps:
        executed = executed_by_step.get(step.step_id)
        if executed is None:
            continue
        for return_name, binding in step.return_bindings.items():
            value = executed.outputs.get(return_name)
            if not isinstance(value, Mapping):
                continue
            condition_kind = value.get("kind")
            published_ref = value.get("ref")
            if (
                not isinstance(condition_kind, str)
                or not isinstance(published_ref, str)
                or value.get("producer_step_id") != step.step_id
                or not isinstance(value.get("related_refs"), Mapping)
                or (step.step_id, condition_kind) not in verified_predicates
            ):
                continue
            if published_ref != binding.ref:
                raise ValueError(
                    "planner.verified_subplan_contract_invalid: predicate "
                    f"publication changed its declared ref: {step.step_id}."
                    f"{return_name}"
                )
            records.append((step.step_id, return_name, published_ref))
            return_name_counts[return_name] = (
                return_name_counts.get(return_name, 0) + 1
            )
    return MappingProxyType(
        {
            (
                return_name
                if return_name_counts[return_name] == 1
                else f"{step_id}.{return_name}"
            ): published_ref
            for step_id, return_name, published_ref in records
        }
    )


class MacroCandidateShadowRunner:
    """Execute one Macro candidate in an isolated shadow runtime branch."""

    def __init__(
        self,
        function_specs: FunctionSpecRegistry,
        method_specs: Any,
        *,
        methods: StatelessMethodRegistry | None = None,
        kernel: SympyKernel | None = None,
    ) -> None:
        self._function_specs = function_specs
        self._method_specs = method_specs
        self._methods = methods or default_stateless_registry()
        self._kernel = kernel or SympyKernel()

    def execute(
        self,
        fragment: FunctionalPlanFragment,
        *,
        context: RuntimeContext,
        source_resolver: Callable[[str, str, str], FragmentRuntimeSource],
    ) -> FunctionalPlanFragmentExecution:
        result_paths: dict[tuple[str, str], str] = {}
        result_values: dict[tuple[str, str], Any] = {}
        derived_refs = {
            binding.ref: (step.step_id, return_name)
            for step in fragment.steps
            for return_name, binding in step.return_bindings.items()
            if binding.kind == "derived"
        }
        referenced_results: set[tuple[str, str]] = set(fragment.exports.values())
        for consumer in fragment.steps:
            for values in consumer.args.values():
                for value in values:
                    if isinstance(value, (ScopedDerivedResultRef, ScopedStepResultRef)):
                        referenced_results.add((value.step_id, value.return_name))
                    elif isinstance(value, str) and value in derived_refs:
                        referenced_results.add(derived_refs[value])
        derived_identities: dict[tuple[str, str], tuple[str, str]] = {}
        source_cache: dict[tuple[str, str, str], FragmentRuntimeSource] = {}
        executions: list[FragmentStepExecution] = []
        verification: list[VerificationOutcome] = []
        executor = InvocationExecutor(
            self._method_specs,
            methods=self._methods,
            kernel=self._kernel,
            require_input_read_authority=True,
        )

        def internal_key(value: Any) -> tuple[str, str] | None:
            if isinstance(value, ScopedDerivedResultRef):
                return value.step_id, value.return_name
            if isinstance(value, ScopedStepResultRef):
                return value.step_id, value.return_name
            if isinstance(value, str):
                return derived_refs.get(value)
            return None

        for step_index, step in enumerate(fragment.steps):
            function = self._function_specs.require(step.capability_id)
            method_spec = self._method_specs.require(function.method_id)
            active_returns = tuple(
                returned
                for returned in function.returns
                if (
                    returned.required
                    or returned.materialization_policy == "always"
                    or returned.name in step.return_bindings
                    or (step.step_id, returned.name) in referenced_results
                )
            )
            function_args = {item.name: item for item in function.args}
            unknown = set(step.args) - set(function_args)
            if unknown:
                raise ValueError(
                    "fragment Function has unknown args: "
                    f"{step.capability_id}={sorted(unknown)}"
                )
            invocation_id = step.step_id
            context.ensure_step_scope(step.step_id, fragment.scope_id)
            invocation_inputs: dict[str, str | tuple[str, ...]] = {}
            input_authorities: dict[str, tuple[MethodInputReadAuthority, ...]] = {}
            argument_refs: dict[str, str] = {}
            source_signatures: list[str] = []

            for arg_name, values in step.args.items():
                arg_spec = function_args[arg_name]
                if len(values) != 1 or arg_spec.cardinality != "one":
                    raise ValueError(
                        "Macro candidate shadow only accepts scalar Function args: "
                        f"{step.capability_id}.{arg_name}"
                    )
                method_input_name = arg_spec.method_input or arg_name
                input_spec = method_spec.inputs[method_input_name]
                value = values[0]
                key = internal_key(value)
                if key is not None:
                    if key not in result_paths:
                        raise ValueError(
                            "fragment result is unavailable or forward-referenced: "
                            f"{key[0]}.{key[1]}"
                        )
                    if input_spec.view.mode == "identity":
                        identity = derived_identities.get(key)
                        if identity is None:
                            raise ValueError(
                                "fragment derived object has no identity authority: "
                                f"{key[0]}.{key[1]}"
                            )
                        path, entity_handle = identity
                        read_source: MethodInputReadSource = EntityIdentityReadSource(
                            entity_handle=entity_handle,
                            runtime_path=path,
                        )
                    else:
                        path = result_paths[key]
                        read_source = InvocationResultReadSource(
                            invocation_id=key[0],
                            return_name=key[1],
                            runtime_path=path,
                        )
                    authority = MethodInputReadAuthority(
                        method_id=function.method_id,
                        invocation_id=invocation_id,
                        input_name=method_input_name,
                        item_index=0,
                        view_mode=input_spec.view.mode,
                        domain_type=input_spec.domain_type,
                        runtime_type=input_spec.runtime_type,
                        scope_id=step.step_id,
                        source=read_source,
                    )
                else:
                    if not isinstance(value, str):
                        raise ValueError("fragment Function args must be typed refs")
                    cache_key = (value, input_spec.view.mode, input_spec.runtime_type)
                    source = source_cache.get(cache_key)
                    if source is None:
                        source = source_resolver(
                            value,
                            input_spec.view.mode,
                            input_spec.runtime_type,
                        )
                        if source.semantic_ref != value:
                            raise ValueError(
                                "fragment source resolver changed SemanticRef"
                            )
                        source_cache[cache_key] = source
                    if source.runtime_path is None or source.read_source is None:
                        raise ValueError(
                            "planner.method_input_view_authority_missing: "
                            f"fragment source {value} is not shadow-ready"
                        )
                    path = source.runtime_path
                    authority = MethodInputReadAuthority(
                        method_id=function.method_id,
                        invocation_id=invocation_id,
                        input_name=method_input_name,
                        item_index=0,
                        view_mode=input_spec.view.mode,
                        domain_type=input_spec.domain_type,
                        runtime_type=input_spec.runtime_type,
                        scope_id=step.step_id,
                        source=source.read_source,
                    )
                    source_signatures.append(source.authority_signature)
                invocation_inputs[method_input_name] = path
                input_authorities[method_input_name] = (authority,)
                argument_refs[arg_name] = _fragment_argument_ref(value)

            for returned in active_returns:
                identity_arg = returned.identity_arg
                if identity_arg is None or identity_arg in invocation_inputs:
                    continue
                binding = step.return_bindings.get(returned.name)
                if binding is None:
                    raise ValueError(
                        "fragment object return requires a declared identity: "
                        f"{step.capability_id}.{returned.name}"
                    )
                identity_path = _fragment_runtime_path(
                    context,
                    fragment,
                    step,
                    f"identity_{returned.name}",
                    promoted=True,
                )
                entity_handle = (
                    f"fragment:{fragment.fragment_signature}:"
                    f"{step.step_id}:{returned.name}"
                )
                context.write_path(
                    identity_path,
                    TypedValue(
                        "PointRef",
                        PointRef(
                            name=binding.ref,
                            path=identity_path,
                            definition={
                                "definition": "fragment_derived",
                                "semantic_role": returned.semantic_role,
                            },
                            scope_id=fragment.scope_id,
                        ),
                        source="fragment_return_allocation",
                    ),
                    from_scope_id=fragment.scope_id,
                )
                input_spec = method_spec.inputs[identity_arg]
                authority = MethodInputReadAuthority(
                    method_id=function.method_id,
                    invocation_id=invocation_id,
                    input_name=identity_arg,
                    item_index=0,
                    view_mode=input_spec.view.mode,
                    domain_type=input_spec.domain_type,
                        runtime_type=input_spec.runtime_type,
                        scope_id=step.step_id,
                        source=EntityIdentityReadSource(
                        entity_handle=entity_handle,
                        runtime_path=identity_path,
                    ),
                )
                invocation_inputs[identity_arg] = identity_path
                input_authorities[identity_arg] = (authority,)
                derived_identities[(step.step_id, returned.name)] = (
                    identity_path,
                    entity_handle,
                )

            invocation_outputs = {
                returned.output_key or returned.name: _fragment_runtime_path(
                    context,
                    fragment,
                    step,
                    returned.output_key or returned.name,
                )
                for returned in active_returns
            }
            promoted_outputs = {
                output_path: _fragment_runtime_path(
                    context,
                    fragment,
                    step,
                    output_name,
                    promoted=True,
                )
                for output_name, output_path in invocation_outputs.items()
            }
            invocation = MethodInvocation(
                invocation_id=invocation_id,
                method_id=function.method_id,
                scope=step.step_id,
                inputs=invocation_inputs,
                outputs=invocation_outputs,
                input_read_authorities=input_authorities,
            )
            plan = StepPlan(
                step_id=step.step_id,
                goal=StepGoal(
                    goal_id=f"fragment:{fragment.fragment_signature}:{step.step_id}",
                    type="verified_subplan_step",
                    target_path=next(iter(invocation_outputs.values())),
                    scope_id=fragment.scope_id,
                ),
                scope=fragment.scope_id,
                invocations=[invocation],
                expected_outputs=list(invocation_outputs.values()),
                promote_outputs=promoted_outputs,
            )
            step_result = executor.execute_step(context, plan)
            method_result = step_result.method_results[0]
            failed_checks = tuple(
                item for item in method_result.checks if not bool(getattr(item, "ok", False))
            )
            if failed_checks:
                verification.extend(
                    VerificationOutcome(
                        passed=False,
                        check_code=str(getattr(item, "name", "method_check")),
                        observed=str(getattr(item, "details", "")),
                    )
                    for item in failed_checks
                )
                return _fragment_execution_result(
                    fragment,
                    passed=False,
                    executions=executions,
                    verification=verification,
                    failure_code="functional.fragment_method_check_failed",
                )

            public_outputs: dict[str, Any] = {}
            for returned in active_returns:
                output_key = returned.output_key or returned.name
                output_path = promoted_outputs[invocation_outputs[output_key]]
                typed_output = context.read_path(
                    output_path,
                    from_scope_id=fragment.scope_id,
                )
                raw_output = typed_output.value
                publication = returned.predicate_publication
                if publication is not None:
                    predicate_passed = bool(raw_output)
                    verification.append(
                        VerificationOutcome(
                            passed=predicate_passed,
                            check_code=publication.condition_kind,
                            expected=True,
                            observed=predicate_passed,
                            evidence=(step.step_id,),
                        )
                    )
                    if not predicate_passed:
                        return _fragment_execution_result(
                            fragment,
                            passed=False,
                            executions=executions,
                            verification=verification,
                            failure_code="functional.predicate_false",
                        )
                    binding = step.return_bindings.get(returned.name)
                    raw_output = {
                        "kind": publication.condition_kind,
                        "ref": binding.ref if binding is not None else None,
                        "producer_step_id": step.step_id,
                        "related_refs": {
                            role: argument_refs[role]
                            for role in publication.related_input_roles
                        },
                    }
                    condition_path = _fragment_runtime_path(
                        context,
                        fragment,
                        step,
                        f"condition_{returned.name}",
                        promoted=True,
                    )
                    context.write_path(
                        condition_path,
                        TypedValue(
                            "Condition",
                            raw_output,
                            source="fragment_predicate_publication",
                        ),
                        from_scope_id=fragment.scope_id,
                        allow_overwrite=True,
                    )
                    output_path = condition_path
                public_outputs[returned.name] = raw_output
                result_values[(step.step_id, returned.name)] = raw_output
                result_paths[(step.step_id, returned.name)] = output_path
            executions.append(
                FragmentStepExecution(
                    step_id=step.step_id,
                    capability_id=step.capability_id,
                    method_id=function.method_id,
                    outputs=public_outputs,
                    source_authority_signatures=tuple(source_signatures),
                )
            )

        return _fragment_execution_result(
            fragment,
            passed=True,
            executions=executions,
            verification=verification,
            standard_outputs={
                export_name: result_values[producer]
                for export_name, producer in fragment.exports.items()
            },
        )


def _fragment_runtime_path(
    context: RuntimeContext,
    fragment: FunctionalPlanFragment,
    step: FunctionalPlanFragmentStep,
    output_name: str,
    *,
    promoted: bool = False,
) -> str:
    token = stable_hash(
        {
            "fragment": fragment.fragment_signature,
            "step_id": step.step_id,
            "output": output_name,
        }
    )[:20]
    if promoted:
        scope = context.get_scope(fragment.scope_id)
        if scope.scope_type == "problem":
            return f"$problem.outputs.fragment_{token}"
        return (
            f"${scope.scope_type}.{scope.scope_id}.outputs.fragment_{token}"
        )
    return f"$step.{step.step_id}.temp.fragment_{token}"


@dataclass(frozen=True)
class CandidateSearchReport:
    macro_id: str
    winner_candidate_id: str
    evaluations: tuple[CandidateEvaluation, ...]
    equivalent_candidate_ids: tuple[str, ...]
    report_signature: str = field(init=False)
    schema_version: str = "candidate-search-report/v1"

    def __post_init__(self) -> None:
        winner = [
            item
            for item in self.evaluations
            if item.candidate_id == self.winner_candidate_id and item.passed
        ]
        if len(winner) != 1:
            raise ValueError("search report winner must be uniquely successful")
        object.__setattr__(
            self,
            "equivalent_candidate_ids",
            tuple(sorted(set(self.equivalent_candidate_ids))),
        )
        object.__setattr__(
            self,
            "report_signature",
            stable_hash(self._payload(include_signature=False)),
        )

    def _payload(self, *, include_signature: bool) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "macro_id": self.macro_id,
            "winner_candidate_id": self.winner_candidate_id,
            "equivalent_candidate_ids": list(self.equivalent_candidate_ids),
            "evaluations": [item.to_payload() for item in self.evaluations],
        }
        if include_signature:
            payload["report_signature"] = self.report_signature
        return payload

    def to_payload(self) -> dict[str, Any]:
        return self._payload(include_signature=True)

    @property
    def search_signature(self) -> str:
        """Compatibility name used by the existing F5-C provenance payload."""

        return self.report_signature

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "CandidateSearchReport":
        report = cls(
            macro_id=_required_string(payload, "macro_id"),
            winner_candidate_id=_required_string(
                payload,
                "winner_candidate_id",
            ),
            evaluations=tuple(
                CandidateEvaluation.from_payload(
                    _required_mapping(item, "evaluations[]")
                )
                for item in _required_sequence(
                    payload.get("evaluations"),
                    "evaluations",
                )
            ),
            equivalent_candidate_ids=tuple(
                str(item)
                for item in _required_sequence(
                    payload.get("equivalent_candidate_ids", ()),
                    "equivalent_candidate_ids",
                )
            ),
            schema_version=_required_string(payload, "schema_version"),
        )
        if payload.get("report_signature") != report.report_signature:
            raise ValueError("candidate search report signature drift")
        return report


@dataclass(frozen=True)
class CandidateSelectionSpec:
    """Declare how successful fragment exports are compared."""

    mode: CandidateSelectionMode
    output_name: str | None = None

    def __post_init__(self) -> None:
        if self.mode == "equivalent":
            if self.output_name is not None:
                raise ValueError(
                    "equivalent candidate selection cannot name one output"
                )
            return
        if not self.output_name:
            raise ValueError(
                f"{self.mode} candidate selection requires output_name"
            )

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"mode": self.mode}
        if self.output_name is not None:
            payload["output_name"] = self.output_name
        return payload


class VerifiedSubplanSearchError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.retryable = retryable
        self.details = MappingProxyType(dict(details or {}))
        super().__init__(f"{code}: {message}")


class GenericCandidateSearchService:
    """Select one runtime-verified fragment without classifying bugs as math."""

    def search(
        self,
        *,
        macro_id: str,
        candidates: Sequence[SearchCandidate],
        evaluator: Callable[[SearchCandidate], CandidateEvaluation],
        max_candidates: int,
        selection: CandidateSelectionSpec = CandidateSelectionSpec("equivalent"),
        authored_roles: Mapping[str, str] = MappingProxyType({}),
    ) -> tuple[SearchCandidate, CandidateSearchReport, CandidateEvaluation]:
        if not candidates:
            raise VerifiedSubplanSearchError(
                "functional.macro_search_no_candidates",
                "Macro expansion produced no structurally legal fragments",
                retryable=True,
            )
        if len(candidates) > max_candidates:
            raise VerifiedSubplanSearchError(
                "functional.macro_search_budget_exceeded",
                f"candidate count {len(candidates)} exceeds {max_candidates}",
                retryable=False,
            )
        ids = [item.candidate_id for item in candidates]
        if len(ids) != len(set(ids)):
            raise VerifiedSubplanSearchError(
                "planner.macro_contract_invalid",
                "candidate ids are not unique",
                retryable=False,
            )

        unknown_roles = set(authored_roles) - {
            role for item in candidates for role in item.role_bindings
        }
        if unknown_roles:
            raise VerifiedSubplanSearchError(
                "planner.macro_contract_invalid",
                f"authored roles are outside the expansion contract: {sorted(unknown_roles)}",
                retryable=False,
            )
        ordered_candidates = sorted(
            candidates,
            key=lambda item: (
                0
                if all(
                    item.role_bindings.get(role) == ref
                    for role, ref in authored_roles.items()
                )
                else 1,
                item.candidate_id,
            ),
        )
        evaluations: list[CandidateEvaluation] = []
        for candidate in ordered_candidates:
            try:
                evaluation = evaluator(candidate)
            except VerifiedSubplanSearchError:
                raise
            except Exception as exc:
                raise VerifiedSubplanSearchError(
                    "planner.macro_candidate_configuration_error",
                    f"{candidate.candidate_id}: {type(exc).__name__}: {exc}",
                    retryable=False,
                    details={
                        "candidate_id": candidate.candidate_id,
                        "strategy_id": candidate.strategy_id,
                        "role_bindings": dict(candidate.role_bindings),
                        "exception_type": type(exc).__name__,
                        "exception_code": getattr(exc, "code", None),
                        "exception_message": str(exc),
                        "exception_details": dict(
                            getattr(exc, "details", {}) or {}
                        ),
                    },
                ) from exc
            if evaluation.candidate_id != candidate.candidate_id:
                raise VerifiedSubplanSearchError(
                    "planner.macro_contract_invalid",
                    "candidate evaluator changed candidate identity",
                    retryable=False,
                )
            evaluations.append(evaluation)

        by_id = {item.candidate_id: item for item in candidates}
        passed = [item for item in evaluations if item.passed]
        if not passed:
            raise VerifiedSubplanSearchError(
                "functional.macro_search_no_valid_candidate",
                "every candidate failed a mathematical verification",
                retryable=True,
                details={
                    "evaluations": [
                        {
                            **item.to_payload(),
                            "strategy_id": by_id[item.candidate_id].strategy_id,
                            "role_bindings": dict(
                                by_id[item.candidate_id].role_bindings
                            ),
                        }
                        for item in evaluations
                    ]
                },
            )
        try:
            winners, equivalent = _select_candidate_evaluations(
                passed,
                selection=selection,
            )
        except VerifiedSubplanSearchError as exc:
            if exc.code != "functional.macro_search_ambiguous":
                raise
            raise VerifiedSubplanSearchError(
                exc.code,
                str(exc).split(": ", 1)[-1],
                retryable=exc.retryable,
                details={
                    "evaluations": [
                        {
                            **item.to_payload(),
                            "strategy_id": by_id[item.candidate_id].strategy_id,
                        }
                        for item in evaluations
                    ]
                },
            ) from exc
        winner_evaluation = min(
            winners,
            key=lambda item: (
                by_id[item.candidate_id].fragment.function_step_count,
                by_id[item.candidate_id].symbolic_complexity,
                by_id[item.candidate_id].fragment.fragment_signature,
                item.candidate_id,
            ),
        )
        winner = by_id[winner_evaluation.candidate_id]
        report = CandidateSearchReport(
            macro_id=macro_id,
            winner_candidate_id=winner.candidate_id,
            evaluations=tuple(evaluations),
            equivalent_candidate_ids=tuple(
                item.candidate_id for item in equivalent
            ),
        )
        return winner, report, winner_evaluation


def _select_candidate_evaluations(
    passed: Sequence[CandidateEvaluation],
    *,
    selection: CandidateSelectionSpec,
) -> tuple[tuple[CandidateEvaluation, ...], tuple[CandidateEvaluation, ...]]:
    if selection.mode == "equivalent":
        signatures = {item.output_signature for item in passed}
        if len(signatures) != 1:
            raise _candidate_ambiguity(passed)
        values = tuple(passed)
        return values, values

    assert selection.output_name is not None
    values: dict[str, sp.Expr] = {}
    for item in passed:
        raw = item.standard_outputs.get(selection.output_name)
        if raw is None:
            raise VerifiedSubplanSearchError(
                "planner.macro_contract_invalid",
                "candidate omitted the declared selection export",
                retryable=False,
                details={
                    "candidate_id": item.candidate_id,
                    "output_name": selection.output_name,
                },
            )
        try:
            values[item.candidate_id] = sp.simplify(sp.sympify(raw))
        except (TypeError, ValueError, sp.SympifyError) as exc:
            raise VerifiedSubplanSearchError(
                "planner.macro_contract_invalid",
                "candidate selection export is not symbolically comparable",
                retryable=False,
                details={
                    "candidate_id": item.candidate_id,
                    "output_name": selection.output_name,
                    "value": raw,
                },
            ) from exc

    winners: list[CandidateEvaluation] = []
    for candidate in passed:
        comparisons = []
        for other in passed:
            comparison = _compare_symbolic_values(
                values[candidate.candidate_id],
                values[other.candidate_id],
            )
            if comparison is None:
                raise _candidate_ambiguity(passed)
            comparisons.append(comparison)
        if selection.mode == "minimize" and all(item <= 0 for item in comparisons):
            winners.append(candidate)
        if selection.mode == "maximize" and all(item >= 0 for item in comparisons):
            winners.append(candidate)
    if not winners:
        raise _candidate_ambiguity(passed)
    winner_values = {sp.srepr(values[item.candidate_id]) for item in winners}
    if len(winner_values) != 1:
        raise _candidate_ambiguity(winners)
    return tuple(winners), tuple(winners)


def _compare_symbolic_values(left: sp.Expr, right: sp.Expr) -> int | None:
    difference = sp.simplify(left - right)
    if difference == 0:
        return 0
    if difference.is_negative is True:
        return -1
    if difference.is_positive is True:
        return 1
    negative = sp.ask(sp.Q.negative(difference))
    if negative is True:
        return -1
    positive = sp.ask(sp.Q.positive(difference))
    if positive is True:
        return 1
    return None


def _candidate_ambiguity(
    candidates: Sequence[CandidateEvaluation],
) -> VerifiedSubplanSearchError:
    return VerifiedSubplanSearchError(
        "functional.macro_search_ambiguous",
        "multiple non-equivalent or incomparable runtime-valid fragments remain",
        retryable=True,
        details={
            "successful_candidates": [item.to_payload() for item in candidates]
        },
    )


def _verification_outcome_from_payload(
    payload: Mapping[str, Any],
) -> VerificationOutcome:
    return VerificationOutcome(
        passed=bool(payload["passed"]),
        check_code=_required_string(payload, "check_code"),
        expected=payload.get("expected"),
        observed=payload.get("observed"),
        evidence=tuple(
            str(item)
            for item in _required_sequence(
                payload.get("evidence", ()),
                "evidence",
            )
        ),
    )


def _required_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    return value


def _required_sequence(value: Any, field_name: str) -> tuple[Any, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{field_name} must be an array")
    return tuple(value)


def _required_string(payload: Mapping[str, Any], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


__all__ = [
    "CandidateEvaluation",
    "CandidateSelectionSpec",
    "CandidateSearchReport",
    "FunctionalPlanFragment",
    "MacroCandidateShadowRunner",
    "fragment_published_condition_refs",
    "GenericCandidateSearchService",
    "MacroSemanticBlueprint",
    "SearchCandidate",
    "VerifiedSubplanSearchError",
]
