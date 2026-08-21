"""Functional planner wire, reconciliation, and execution diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, Protocol

import sympy as sp
from sympy.parsing.sympy_parser import parse_expr

from shuxueshuo_server.solver.contracts import (
    FunctionalResultForm,
    MethodInputBindingSpec,
)
from shuxueshuo_server.solver.runtime.state_identity import (
    ComputationKey,
    LogicalStateKey,
    MathObjectId,
    RuntimeDestinationKey,
    StateAllocationAction,
    StateEffectKey,
    StateSlotId,
    StateVersionId,
)
from shuxueshuo_server.solver.runtime.problem_source_provenance import (
    ProblemCallSourceProvenance,
)
from shuxueshuo_server.solver.state_semantics import StateSemanticLineage


@dataclass(frozen=True)
class SymbolicClosureProvenance:
    """Runtime-grounded target solve and substitution evidence."""

    status: str
    target_object_id: MathObjectId | None = None
    target_value: str | None = None
    substitutions: tuple[tuple[MathObjectId, str], ...] = ()
    residual_symbol_ids: tuple[MathObjectId, ...] = ()
    branch_count: int = 0
    equation_builder: str | None = None
    representation_mapper: str | None = None
    constraint_filter: str | None = None
    target_binding: str | None = None
    equation_sources: tuple[str, ...] = ()
    known_substitution_sources: tuple[str, ...] = ()
    preserved_symbol_ids: tuple[MathObjectId, ...] = ()
    affected_returns: tuple[str, ...] = ()

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
    ) -> "SymbolicClosureProvenance":
        target_payload = payload.get("target_object_id")
        return cls(
            status=str(payload.get("status") or ""),
            target_object_id=(
                MathObjectId.from_payload(target_payload)
                if isinstance(target_payload, dict)
                else None
            ),
            target_value=(
                str(payload["target_value"])
                if payload.get("target_value") is not None
                else None
            ),
            substitutions=tuple(
                (
                    MathObjectId.from_payload(item["symbol_id"]),
                    str(item["value"]),
                )
                for item in payload.get("substitutions", ())
                if isinstance(item, dict)
                and isinstance(item.get("symbol_id"), dict)
                and item.get("value") is not None
            ),
            residual_symbol_ids=tuple(
                MathObjectId.from_payload(item)
                for item in payload.get("residual_symbol_ids", ())
                if isinstance(item, dict)
            ),
            branch_count=int(payload.get("branch_count") or 0),
            equation_builder=_optional_payload_string(
                payload.get("equation_builder")
            ),
            representation_mapper=_optional_payload_string(
                payload.get("representation_mapper")
            ),
            constraint_filter=_optional_payload_string(
                payload.get("constraint_filter")
            ),
            target_binding=_optional_payload_string(
                payload.get("target_binding")
            ),
            equation_sources=tuple(
                str(item) for item in payload.get("equation_sources", ())
            ),
            known_substitution_sources=tuple(
                str(item)
                for item in payload.get("known_substitution_sources", ())
            ),
            preserved_symbol_ids=tuple(
                MathObjectId.from_payload(item)
                for item in payload.get("preserved_symbol_ids", ())
                if isinstance(item, dict)
            ),
            affected_returns=tuple(
                str(item) for item in payload.get("affected_returns", ())
            ),
        )

    def semantic_signature(self) -> tuple[Any, ...]:
        """Stable closure identity independent of runtime projection paths."""
        return (
            self.status,
            self.target_object_id,
            canonical_symbolic_expression(self.target_value),
            tuple(
                sorted(
                    (
                        (
                            symbol_id,
                            canonical_symbolic_expression(value),
                        )
                        for symbol_id, value in self.substitutions
                    ),
                    key=lambda item: _math_object_signature(item[0]),
                )
            ),
            tuple(
                sorted(
                    self.residual_symbol_ids,
                    key=_math_object_signature,
                )
            ),
            self.branch_count,
            self.equation_builder,
            self.representation_mapper,
            self.constraint_filter,
            self.target_binding,
            tuple(sorted(self.equation_sources)),
            tuple(sorted(self.known_substitution_sources)),
            tuple(
                sorted(
                    self.preserved_symbol_ids,
                    key=_math_object_signature,
                )
            ),
            tuple(sorted(self.affected_returns)),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "target_object_id": (
                self.target_object_id.to_payload()
                if self.target_object_id is not None
                else None
            ),
            "target_value": self.target_value,
            "substitutions": [
                {
                    "symbol_id": symbol_id.to_payload(),
                    "value": value,
                }
                for symbol_id, value in self.substitutions
            ],
            "residual_symbol_ids": [
                item.to_payload() for item in self.residual_symbol_ids
            ],
            "branch_count": self.branch_count,
            "equation_builder": self.equation_builder,
            "representation_mapper": self.representation_mapper,
            "constraint_filter": self.constraint_filter,
            "target_binding": self.target_binding,
            "equation_sources": list(self.equation_sources),
            "known_substitution_sources": list(
                self.known_substitution_sources
            ),
            "preserved_symbol_ids": [
                item.to_payload() for item in self.preserved_symbol_ids
            ],
            "affected_returns": list(self.affected_returns),
        }


def _optional_payload_string(value: Any) -> str | None:
    return str(value) if value is not None else None


def canonical_symbolic_expression(value: str | None) -> str | None:
    """Canonicalize the supported algebraic subset without solving it.

    Closure checkpoints currently cover open middle-school algebraic
    expressions. Parsing with ``evaluate=False`` normalizes commutative term
    order while avoiding full simplification that could erase denominator or
    branch-domain distinctions. Piecewise, rational-domain and branch-sensitive
    closures require a richer contract before they can use this signature.
    """
    if value is None:
        return None
    try:
        return sp.sstr(parse_expr(value, evaluate=False)).replace(" ", "")
    except (TypeError, ValueError, sp.SympifyError):
        return value.strip()


def _math_object_signature(value: MathObjectId) -> tuple[str, str, str]:
    return (value.kind, value.origin_scope_id, value.value)


def answer_output_type_compatible(expected_type: str | None, actual_type: str | None) -> bool:
    """Return whether a compiled answer can satisfy a QuestionGoal type.

    题目解析阶段可能只知道“求点 E”，但不知道最后会有两个候选坐标。因此
    ``PointList`` 可以满足 ``Point`` 型答案目标；其它类型继续严格匹配。
    """
    if expected_type is None or actual_type is None:
        return True
    if expected_type == actual_type:
        return True
    return expected_type == "Point" and actual_type == "PointList"


def functional_answer_output_type_compatible(
    expected_type: str | None,
    actual_type: str | None,
) -> bool:
    """Use strict answer cardinality at the FunctionalPlan boundary.

    Functional returns declare their exact scalar/container type. A candidate
    collection must be narrowed by another call before it can bind a singular
    answer.
    """
    return (
        expected_type is None
        or actual_type is None
        or expected_type == actual_type
    )


def answer_value_type_requires_closed_scalar(value_type: str | None) -> bool:
    """Whether an answer type can never retain a symbolic independent variable.

    Function-like answers may legitimately contain their declared variable.
    Every other scalar answer is expected to be closed, allowing FunctionalPlan
    to infer ``closed_value`` without asking the LLM to repeat that fact.
    """
    return value_type not in {None, "Expression", "Equation", "Function", "Parabola"}


@dataclass(frozen=True)
class CreatedEntity:
    """A derived entity declaration used by capability compilation.

    这里的实体只表示“题设之外新出现的对象”，例如辅助点、辅助线。它不承载坐标、
    方程或答案值；这些数值性结论必须通过 ``ProducedFact`` 表达。
    """

    handle: str
    entity_type: str
    valid_scope: str
    description: str = ""

    def to_payload(self) -> dict[str, str]:
        """转成 JSON 友好的 dict。"""
        return {
            "handle": self.handle,
            "entity_type": self.entity_type,
            "valid_scope": self.valid_scope,
            "description": self.description,
        }


@dataclass(frozen=True)
class ProducedFact:
    """A public capability return projected to a fact or answer destination.

    ``handle`` 只能是 ``fact:<scope>:<semantic_name>`` 或
    ``answer:<QuestionGoal.id>``。后续 step 复用时直接在 ``reads`` 中引用该 handle，
    不再引入 ``@step`` 临时输出。
    """

    handle: str
    valid_scope: str
    description: str = ""
    output_type: str | None = None

    def to_payload(self) -> dict[str, str]:
        """转成 JSON 友好的 dict。"""
        payload = {
            "handle": self.handle,
            "valid_scope": self.valid_scope,
            "description": self.description,
        }
        if self.output_type is not None:
            payload["output_type"] = self.output_type
        return payload


class FunctionalCompileStepView(Protocol):
    """Read-only input contract consumed by Functional capability compilation."""

    scope_id: str
    step_id: str
    capability_id: str
    goal_type: str
    target_handle: str
    input_handles: tuple[str, ...]
    created_entities: tuple[Any, ...]
    return_outputs: tuple[Any, ...]


@dataclass(frozen=True)
class FunctionalCompileStep:
    """Test/debug compile view; never accepted as an LLM wire payload."""

    scope_id: str
    step_id: str
    recipe_hint: str | None
    goal_type: str
    target: str
    strategy: str
    reads: tuple[str, ...] = ()
    creates: tuple[CreatedEntity, ...] = ()
    produces: tuple[ProducedFact, ...] = ()
    reason: str = ""

    @property
    def capability_id(self) -> str:
        return self.recipe_hint or ""

    @property
    def target_handle(self) -> str:
        return self.target

    @property
    def input_handles(self) -> tuple[str, ...]:
        return self.reads

    @property
    def created_entities(self) -> tuple[CreatedEntity, ...]:
        return self.creates

    @property
    def return_outputs(self) -> tuple[ProducedFact, ...]:
        return self.produces


@dataclass(frozen=True)
class ProjectedStateWrite:
    """Typed state-write manifest entry produced by reconciliation."""

    step_id: str
    produced_handle: str
    state_slot_id: str
    write_mode: Literal["create", "transition", "value"]
    runtime_type: str | None = None
    object_ref: str | None = None
    source_state_slot_ids: tuple[str, ...] = ()
    dependency_object_refs: tuple[str, ...] = ()
    return_name: str | None = None
    expected_result_form: FunctionalResultForm | None = None
    transition_kind: Literal["direct", "dependency_refinement"] | None = None
    previous_write_step_id: str | None = None
    lineage: StateSemanticLineage = StateSemanticLineage()
    math_object_id: MathObjectId | None = None
    logical_state_key: LogicalStateKey | None = None
    typed_slot_id: StateSlotId | None = None
    selected_version_id: StateVersionId | None = None
    previous_version_id: StateVersionId | None = None
    computation_key: ComputationKey | None = None
    source_version_ids: tuple[StateVersionId, ...] = ()
    allocation_action: StateAllocationAction | None = None
    free_symbol_refs: tuple[str, ...] = ()
    free_symbol_ids: tuple[MathObjectId, ...] = ()
    canonical_producer_call_id: str | None = None
    valid_scope_id: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "step_id": self.step_id,
            "produced_handle": self.produced_handle,
            "state_slot_id": self.state_slot_id,
            "write_mode": self.write_mode,
            "source_state_slot_ids": list(self.source_state_slot_ids),
            "dependency_object_refs": list(self.dependency_object_refs),
        }
        if self.runtime_type is not None:
            payload["runtime_type"] = self.runtime_type
        if self.object_ref is not None:
            payload["object_ref"] = self.object_ref
        if self.return_name is not None:
            payload["return_name"] = self.return_name
        if self.expected_result_form is not None:
            payload["expected_result_form"] = self.expected_result_form
        if self.transition_kind is not None:
            payload["transition_kind"] = self.transition_kind
        if self.previous_write_step_id is not None:
            payload["previous_write_step_id"] = self.previous_write_step_id
        payload["lineage"] = self.lineage.to_payload()
        if self.math_object_id is not None:
            payload["math_object_id"] = self.math_object_id.to_payload()
        if self.logical_state_key is not None:
            payload["logical_state_key"] = self.logical_state_key.to_payload()
        if self.typed_slot_id is not None:
            payload["typed_slot_id"] = self.typed_slot_id.to_payload()
        if self.selected_version_id is not None:
            payload["selected_version_id"] = self.selected_version_id.to_payload()
        if self.previous_version_id is not None:
            payload["previous_version_id"] = self.previous_version_id.to_payload()
        if self.computation_key is not None:
            payload["computation_key"] = self.computation_key.to_payload()
        if self.source_version_ids:
            payload["source_version_ids"] = [
                item.to_payload() for item in self.source_version_ids
            ]
        if self.allocation_action is not None:
            payload["allocation_action"] = self.allocation_action
        if self.free_symbol_refs:
            payload["free_symbol_refs"] = list(self.free_symbol_refs)
        if self.free_symbol_ids:
            payload["free_symbol_ids"] = [
                item.to_payload() for item in self.free_symbol_ids
            ]
        if self.canonical_producer_call_id is not None:
            payload["canonical_producer_call_id"] = (
                self.canonical_producer_call_id
            )
        if self.valid_scope_id is not None:
            payload["valid_scope_id"] = self.valid_scope_id
        return payload


@dataclass(frozen=True)
class ProjectedStateDependency:
    """Exact StateSlot dependency selected during Functional reconciliation."""

    step_id: str
    state_slot_id: str
    produced_handle: str
    runtime_type: str | None = None
    object_ref: str | None = None
    arg_name: str | None = None
    source: Literal["wire", "resolver", "context"] = "wire"
    source_step_id: str | None = None
    source_return_name: str | None = None
    state_version_id: StateVersionId | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "step_id": self.step_id,
            "state_slot_id": self.state_slot_id,
            "produced_handle": self.produced_handle,
            "source": self.source,
        }
        if self.runtime_type is not None:
            payload["runtime_type"] = self.runtime_type
        if self.object_ref is not None:
            payload["object_ref"] = self.object_ref
        if self.arg_name is not None:
            payload["arg_name"] = self.arg_name
        if self.source_step_id is not None:
            payload["source_step_id"] = self.source_step_id
        if self.source_return_name is not None:
            payload["source_return_name"] = self.source_return_name
        if self.state_version_id is not None:
            payload["state_version_id"] = self.state_version_id.to_payload()
        return payload


@dataclass(frozen=True)
class ProjectedFunctionArgBinding:
    """Exact FunctionalPlan argument identity consumed by direct compilation."""

    step_id: str
    arg_name: str
    source_handle: str
    runtime_type: str | None = None
    state_slot_id: str | None = None
    object_ref: str | None = None
    math_object_id: MathObjectId | None = None
    state_version_id: StateVersionId | None = None
    condition_id: str | None = None
    source_call_id: str | None = None
    source_return_name: str | None = None
    binding_authority: Literal["wire", "resolver", "compiler"] = "wire"
    semantic_role: str | None = None
    cardinality: str = "one"
    item_index: int = 0
    selection_policy: Literal[
        "exact", "latest", "identity_only", "compiler"
    ] = "exact"
    consumption_mode: Literal[
        "runtime_input", "resolver_evidence", "compiler_selector", "typed_binding"
    ] = "runtime_input"
    compiler_selector_id: str | None = None
    compiler_selected_source_kind: Literal[
        "state_version",
        "condition",
        "math_object",
        "call_result",
    ] | None = None
    runtime_input_targets: tuple[str, ...] = ()
    runtime_input_required: bool = True
    input_binding: MethodInputBindingSpec | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "step_id": self.step_id,
            "arg_name": self.arg_name,
            "source_handle": self.source_handle,
            "binding_authority": self.binding_authority,
            "semantic_role": self.semantic_role or self.arg_name,
            "cardinality": self.cardinality,
            "item_index": self.item_index,
            "selection_policy": self.selection_policy,
            "consumption_mode": self.consumption_mode,
            "runtime_input_targets": list(self.runtime_input_targets),
            "runtime_input_required": self.runtime_input_required,
        }
        if self.runtime_type is not None:
            payload["runtime_type"] = self.runtime_type
        if self.state_slot_id is not None:
            payload["state_slot_id"] = self.state_slot_id
        if self.object_ref is not None:
            payload["object_ref"] = self.object_ref
        if self.math_object_id is not None:
            payload["math_object_id"] = self.math_object_id.to_payload()
        if self.state_version_id is not None:
            payload["state_version_id"] = self.state_version_id.to_payload()
        if self.condition_id is not None:
            payload["condition_id"] = self.condition_id
        if self.input_binding is not None:
            payload["input_binding"] = self.input_binding.to_payload()
        if self.source_call_id is not None:
            payload["source_call_id"] = self.source_call_id
        if self.source_return_name is not None:
            payload["source_return_name"] = self.source_return_name
        if self.compiler_selector_id is not None:
            payload["compiler_selector_id"] = self.compiler_selector_id
        if self.compiler_selected_source_kind is not None:
            payload["compiler_selected_source_kind"] = (
                self.compiler_selected_source_kind
            )
        payload["binding_authority"] = self.binding_authority
        return payload

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
    ) -> "ProjectedFunctionArgBinding":
        math_object = payload.get("math_object_id")
        state_version = payload.get("state_version_id")
        input_binding = payload.get("input_binding")
        return cls(
            step_id=str(payload["step_id"]),
            arg_name=str(payload["arg_name"]),
            source_handle=str(payload["source_handle"]),
            runtime_type=(
                str(payload["runtime_type"])
                if payload.get("runtime_type") is not None
                else None
            ),
            state_slot_id=(
                str(payload["state_slot_id"])
                if payload.get("state_slot_id") is not None
                else None
            ),
            object_ref=(
                str(payload["object_ref"])
                if payload.get("object_ref") is not None
                else None
            ),
            math_object_id=(
                MathObjectId.from_payload(math_object)
                if isinstance(math_object, Mapping)
                else None
            ),
            state_version_id=(
                StateVersionId.from_payload(state_version)
                if isinstance(state_version, Mapping)
                else None
            ),
            condition_id=(
                str(payload["condition_id"])
                if payload.get("condition_id") is not None
                else None
            ),
            source_call_id=(
                str(payload["source_call_id"])
                if payload.get("source_call_id") is not None
                else None
            ),
            source_return_name=(
                str(payload["source_return_name"])
                if payload.get("source_return_name") is not None
                else None
            ),
            binding_authority=str(payload.get("binding_authority", "wire")),  # type: ignore[arg-type]
            semantic_role=(
                str(payload["semantic_role"])
                if payload.get("semantic_role") is not None
                else None
            ),
            cardinality=str(payload.get("cardinality", "one")),
            item_index=int(payload.get("item_index", 0)),
            selection_policy=str(payload.get("selection_policy", "exact")),  # type: ignore[arg-type]
            consumption_mode=str(payload.get("consumption_mode", "runtime_input")),  # type: ignore[arg-type]
            compiler_selector_id=(
                str(payload["compiler_selector_id"])
                if payload.get("compiler_selector_id") is not None
                else None
            ),
            compiler_selected_source_kind=(
                str(payload["compiler_selected_source_kind"])  # type: ignore[arg-type]
                if payload.get("compiler_selected_source_kind") is not None
                else None
            ),
            runtime_input_targets=tuple(
                str(item) for item in payload.get("runtime_input_targets", ())
            ),
            runtime_input_required=bool(
                payload.get("runtime_input_required", True)
            ),
            input_binding=(
                MethodInputBindingSpec.from_payload(input_binding)
                if isinstance(input_binding, Mapping)
                else None
            ),
        )


@dataclass(frozen=True)
class SemanticRef:
    """LLM-facing semantic read reference.

    ``SemanticRef`` is accepted at the raw JSON boundary and resolved to typed
    object, condition, or StateVersion identity before execution.
    """

    ref: str
    kind: str
    value_type: str | None = None
    from_step: str | None = None

    def to_payload(self) -> dict[str, str]:
        """转成 JSON 友好的 dict。"""
        payload = {
            "ref": self.ref,
            "kind": self.kind,
        }
        if self.value_type is not None:
            payload["value_type"] = self.value_type
        if self.from_step is not None:
            payload["from_step"] = self.from_step
        return payload


@dataclass(frozen=True)
class StrategyPrompt:
    """Jinja 渲染后的 Chat messages。"""

    system: str
    user: str

    @property
    def messages(self) -> list[dict[str, str]]:
        """OpenAI-compatible Chat Completions 可直接消费的 messages。"""
        return [
            {"role": "system", "content": self.system},
            {"role": "user", "content": self.user},
        ]


@dataclass(frozen=True)
class RecipeAlignmentReport:
    """recipe_hint 与 family recipe/method 菜单的对齐报告。

    这份报告只用于 probe 质量判断和 prompt 调参，不参与执行裁决。后续真正求解时，
    recipe_hint 仍要经过 resolver/trial 的可验算结果确认。
    """

    matched_recipes: tuple[str, ...] = ()
    matched_methods: tuple[str, ...] = ()
    null_hint_steps: tuple[str, ...] = ()
    unknown_hint_steps: tuple[str, ...] = ()
    unknown_goal_type_steps: tuple[str, ...] = ()
    preferred_recipe_ids: tuple[str, ...] = ()
    covered_preferred_recipe_ids: tuple[str, ...] = ()
    missing_preferred_recipe_ids: tuple[str, ...] = ()
    avoid_pattern_hits: tuple[dict[str, str], ...] = ()
    capability_errors: tuple[dict[str, str], ...] = ()

    @property
    def non_empty_hint_count(self) -> int:
        """返回命中 recipe、method 或 unknown 的非空 hint 数量。"""
        return (
            len(self.matched_recipes)
            + len(self.matched_methods)
            + len(self.unknown_hint_steps)
        )

    @property
    def matched_hint_count(self) -> int:
        """返回命中已知 recipe/method 的 hint 数量。"""
        return len(self.matched_recipes) + len(self.matched_methods)

    def to_payload(self) -> dict[str, Any]:
        """转成 JSON 友好结构。"""
        return {
            "matched_recipes": list(self.matched_recipes),
            "matched_methods": list(self.matched_methods),
            "null_hint_steps": list(self.null_hint_steps),
            "unknown_hint_steps": list(self.unknown_hint_steps),
            "unknown_goal_type_steps": list(self.unknown_goal_type_steps),
            "preferred_recipe_ids": list(self.preferred_recipe_ids),
            "covered_preferred_recipe_ids": list(self.covered_preferred_recipe_ids),
            "missing_preferred_recipe_ids": list(self.missing_preferred_recipe_ids),
            "avoid_pattern_hits": list(self.avoid_pattern_hits),
            "capability_errors": list(self.capability_errors),
            "non_empty_hint_count": self.non_empty_hint_count,
            "matched_hint_count": self.matched_hint_count,
        }


@dataclass(frozen=True)
class HandleCorrection:
    """HandleResolver 对 LLM reads 做的一次保守修正。

    这类修正只处理 scope 前缀写错但语义名完全一致的情况。例如某一步在 ``ii_1``
    scope 中读取 ``fact:ii_1:path_minimum_target``，而题面真实 fact 是父级可见的
    ``fact:ii:path_minimum_target``。我们不修正 sibling scope，不修正 answer，也不
    根据自然语言猜测语义名。
    """

    step_id: str
    scope_id: str
    from_handle: str
    to_handle: str
    reason: str

    def to_payload(self) -> dict[str, str]:
        """转成 debug JSON。"""
        return {
            "step_id": self.step_id,
            "scope_id": self.scope_id,
            "from_handle": self.from_handle,
            "to_handle": self.to_handle,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class SemanticReadResolution:
    """一次 semantic read 到 canonical handle 的解析结果。"""

    step_id: str
    scope_id: str
    semantic_ref: SemanticRef
    handle: str
    candidate_count: int
    overrode_legacy_reads: bool = False
    inferred_from_step: str | None = None
    state_slot_id: str | None = None
    condition_id: str | None = None
    source_context_id: str | None = None
    math_object_id: MathObjectId | None = None
    state_version_id: StateVersionId | None = None

    def to_payload(self) -> dict[str, Any]:
        """转成 JSON 友好结构。"""
        payload: dict[str, Any] = {
            "step_id": self.step_id,
            "scope_id": self.scope_id,
            "semantic_ref": self.semantic_ref.to_payload(),
            "handle": self.handle,
            "candidate_count": self.candidate_count,
            "overrode_legacy_reads": self.overrode_legacy_reads,
        }
        if self.inferred_from_step is not None:
            payload["inferred_from_step"] = self.inferred_from_step
        if self.state_slot_id is not None:
            payload["state_slot_id"] = self.state_slot_id
        if self.condition_id is not None:
            payload["condition_id"] = self.condition_id
        if self.source_context_id is not None:
            payload["source_context_id"] = self.source_context_id
        if self.math_object_id is not None:
            payload["math_object_id"] = self.math_object_id.to_payload()
        if self.state_version_id is not None:
            payload["state_version_id"] = (
                self.state_version_id.to_payload()
            )
        return payload


@dataclass(frozen=True)
class SemanticReadResolutionError:
    """一次 semantic read 解析失败的结构化错误。"""

    step_id: str
    scope_id: str
    code: str
    message: str
    semantic_ref: SemanticRef | None = None

    def to_payload(self) -> dict[str, Any]:
        """转成 JSON 友好结构。"""
        payload: dict[str, Any] = {
            "step_id": self.step_id,
            "scope_id": self.scope_id,
            "code": self.code,
            "message": self.message,
        }
        if self.semantic_ref is not None:
            payload["semantic_ref"] = self.semantic_ref.to_payload()
        return payload


@dataclass(frozen=True)
class SemanticReadFallback:
    """Semantic read 失败后采用同 step legacy reads 的一次回退。"""

    step_id: str
    scope_id: str
    reason: str
    reads: tuple[str, ...]
    semantic_errors: tuple[SemanticReadResolutionError, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        """转成 JSON 友好结构。"""
        return {
            "step_id": self.step_id,
            "scope_id": self.scope_id,
            "reason": self.reason,
            "reads": list(self.reads),
            "semantic_errors": [
                error.to_payload()
                for error in self.semantic_errors
            ],
        }


@dataclass(frozen=True)
class SemanticReadResolutionReport:
    """SemanticReadResolver 的解析摘要。"""

    resolutions: tuple[SemanticReadResolution, ...] = ()
    errors: tuple[SemanticReadResolutionError, ...] = ()
    fallbacks: tuple[SemanticReadFallback, ...] = ()
    warnings: tuple[str, ...] = ()
    partially_resolved_payload: dict[str, Any] | None = None

    @property
    def changed(self) -> bool:
        """是否实际解析过任意 semantic read。"""
        return bool(self.resolutions or self.errors or self.fallbacks or self.warnings)

    @property
    def ok(self) -> bool:
        """是否没有 semantic read 解析错误。"""
        return not self.errors

    def to_payload(self) -> dict[str, Any]:
        """转成 JSON 友好结构。"""
        payload: dict[str, Any] = {
            "changed": self.changed,
            "ok": self.ok,
            "resolutions": [
                resolution.to_payload()
                for resolution in self.resolutions
            ],
            "errors": [
                error.to_payload()
                for error in self.errors
            ],
            "fallbacks": [
                fallback.to_payload()
                for fallback in self.fallbacks
            ],
            "warnings": list(self.warnings),
        }
        if self.partially_resolved_payload is not None:
            payload["partially_resolved_payload"] = self.partially_resolved_payload
        return payload


@dataclass(frozen=True)
class FunctionalAppliedFill:
    """A typed semantic input supplied during Functional call preparation.

    这类补位只记录 canonical handle 层面的事实，不暴露 RuntimeContext path。
    例如 LLM 只读取 ``point:problem:B``，而 method 需要 ``Point`` 时，代码可
    唯一补到前序已产生的 ``fact:i:B_coordinate``。
    """

    step_id: str
    scope_id: str
    input_handle: str
    required_type: str
    resolved_handle: str
    reason: str

    def to_payload(self) -> dict[str, str]:
        """转成可放入 previous_attempts 的安全 JSON。"""
        return {
            "step_id": self.step_id,
            "scope_id": self.scope_id,
            "input_handle": self.input_handle,
            "required_type": self.required_type,
            "resolved_handle": self.resolved_handle,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class FunctionalAcceptedStep:
    """A Functional call whose compiled StepPlans passed runtime checks."""

    step_id: str
    scope_id: str
    capability_id: str
    method_ids: tuple[str, ...] = ()
    produced_handles: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        """转成 debug JSON。"""
        return {
            "step_id": self.step_id,
            "scope_id": self.scope_id,
            "capability_id": self.capability_id,
            "method_ids": list(self.method_ids),
            "produced_handles": list(self.produced_handles),
        }


@dataclass(frozen=True)
class FunctionalPlannerInsight:
    """已执行前缀向下一轮 planner 暴露的语义 insight。

    insight 只来自 method/recipe 已执行产物，用于告诉 LLM 后续规划的关键角色。
    它不包含 RuntimePath、MethodInvocation、traceback 或 expected answer。
    """

    step_id: str
    scope_id: str
    produced_handle: str
    output_type: str
    facts: dict[str, Any]
    repair_note: str

    def to_payload(self) -> dict[str, Any]:
        """转成可放入 previous_attempts 的安全 JSON。"""
        return {
            "step_id": self.step_id,
            "scope_id": self.scope_id,
            "produced_handle": self.produced_handle,
            "output_type": self.output_type,
            "facts": self.facts,
            "repair_note": self.repair_note,
        }


@dataclass(frozen=True)
class FunctionalPreflightIssue:
    """A structural issue found before transactional call execution."""

    step_id: str
    scope_id: str
    category: str
    code: str
    message: str
    repair: str
    related_steps: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        """转成可放入 previous_attempts 的安全 JSON。"""
        return {
            "step_id": self.step_id,
            "scope_id": self.scope_id,
            "category": self.category,
            "code": self.code,
            "message": self.message,
            "repair": self.repair,
            "related_steps": list(self.related_steps),
        }


@dataclass(frozen=True)
class FunctionArgBindingRepair:
    """Analyzer-selected canonical sources for one Functional argument."""

    arg_name: str
    source_handles: tuple[str, ...]
    reason: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "arg_name": self.arg_name,
            "source_handles": list(self.source_handles),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class FunctionalFunctionBindingEvent:
    """FunctionSpec adapter binding result for one method attempt.

    The payload is debug-safe: it exposes function ids, method ids, status, and
    typed error codes, but never RuntimeContext paths.  ``failure`` means the
    migrated FunctionSpec adapter did not bind and execution stops at that
    structured error.
    """

    step_id: str
    scope_id: str
    method_id: str
    function_id: str
    status: Literal["success", "failure"]
    errors: tuple[str, ...] = ()
    arg_repairs: tuple[FunctionArgBindingRepair, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "step_id": self.step_id,
            "scope_id": self.scope_id,
            "method_id": self.method_id,
            "function_id": self.function_id,
            "status": self.status,
        }
        if self.errors:
            payload["errors"] = list(self.errors)
        if self.arg_repairs:
            payload["arg_repairs"] = [
                item.to_payload() for item in self.arg_repairs
            ]
        return payload


@dataclass(frozen=True)
class FunctionalMacroBindingEvent:
    """MacroSpec adapter validation result for one recipe attempt."""

    step_id: str
    scope_id: str
    recipe_id: str
    macro_id: str
    status: Literal["success", "failure"]
    errors: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "step_id": self.step_id,
            "scope_id": self.scope_id,
            "recipe_id": self.recipe_id,
            "macro_id": self.macro_id,
            "status": self.status,
        }
        if self.errors:
            payload["errors"] = list(self.errors)
        return payload


@dataclass(frozen=True)
class StateWriteProvenance:
    """Object/state identity carried by a FunctionSpec or MacroSpec write."""

    step_id: str
    scope_id: str
    capability_id: str
    produced_handle: str
    output_key: str
    runtime_type: str
    identity_policy: Literal[
        "preserve_input_object",
        "target_object",
        "derived_role",
        "value_only",
    ]
    identity_role: str
    evidence_roles: tuple[str, ...] = ()
    object_ref: str | None = None
    source_handles: tuple[str, ...] = ()
    source_step_id: str | None = None
    state_slot_id: str | None = None
    write_mode: Literal["create", "transition", "value"] = "value"
    previous_write_step_id: str | None = None
    free_symbol_names: tuple[str, ...] = ()
    free_symbol_ids: tuple[MathObjectId, ...] = ()
    closure_ignored_symbol_names: tuple[str, ...] = ()
    transition_kind: Literal["direct", "dependency_refinement"] | None = None
    dependency_object_refs: tuple[str, ...] = ()
    source_state_slot_ids: tuple[str, ...] = ()
    lineage: StateSemanticLineage = StateSemanticLineage()
    math_object_id: MathObjectId | None = None
    logical_state_key: LogicalStateKey | None = None
    typed_slot_id: StateSlotId | None = None
    selected_version_id: StateVersionId | None = None
    previous_version_id: StateVersionId | None = None
    computation_key: ComputationKey | None = None
    source_version_ids: tuple[StateVersionId, ...] = ()
    allocation_action: StateAllocationAction | None = None
    return_name: str | None = None
    runtime_destination_key: RuntimeDestinationKey | None = None
    state_effect_key: StateEffectKey | None = None
    canonical_producer_call_id: str | None = None
    valid_scope_id: str | None = None
    result_form: str | None = None
    symbolic_closure_provenance: SymbolicClosureProvenance | None = None
    problem_source_provenance: ProblemCallSourceProvenance | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "scope_id": self.scope_id,
            "capability_id": self.capability_id,
            "produced_handle": self.produced_handle,
            "output_key": self.output_key,
            "runtime_type": self.runtime_type,
            "identity_policy": self.identity_policy,
            "identity_role": self.identity_role,
            "evidence_roles": list(self.evidence_roles),
            "object_ref": self.object_ref,
            "source_handles": list(self.source_handles),
            "source_step_id": self.source_step_id,
            "state_slot_id": self.state_slot_id,
            "write_mode": self.write_mode,
            "previous_write_step_id": self.previous_write_step_id,
            "free_symbol_names": list(self.free_symbol_names),
            "free_symbol_ids": [
                item.to_payload() for item in self.free_symbol_ids
            ],
            "closure_ignored_symbol_names": list(
                self.closure_ignored_symbol_names
            ),
            "transition_kind": self.transition_kind,
            "dependency_object_refs": list(self.dependency_object_refs),
            "source_state_slot_ids": list(self.source_state_slot_ids),
            "lineage": self.lineage.to_payload(),
            "math_object_id": (
                self.math_object_id.to_payload()
                if self.math_object_id is not None
                else None
            ),
            "logical_state_key": (
                self.logical_state_key.to_payload()
                if self.logical_state_key is not None
                else None
            ),
            "typed_slot_id": (
                self.typed_slot_id.to_payload()
                if self.typed_slot_id is not None
                else None
            ),
            "selected_version_id": (
                self.selected_version_id.to_payload()
                if self.selected_version_id is not None
                else None
            ),
            "previous_version_id": (
                self.previous_version_id.to_payload()
                if self.previous_version_id is not None
                else None
            ),
            "computation_key": (
                self.computation_key.to_payload()
                if self.computation_key is not None
                else None
            ),
            "source_version_ids": [
                item.to_payload() for item in self.source_version_ids
            ],
            "allocation_action": self.allocation_action,
            "return_name": self.return_name,
            "runtime_destination_key": (
                self.runtime_destination_key.to_payload()
                if self.runtime_destination_key is not None
                else None
            ),
            "state_effect_key": (
                self.state_effect_key.to_payload()
                if self.state_effect_key is not None
                else None
            ),
            "canonical_producer_call_id": self.canonical_producer_call_id,
            "valid_scope_id": self.valid_scope_id,
            "result_form": self.result_form,
            "symbolic_closure_provenance": (
                self.symbolic_closure_provenance.to_payload()
                if self.symbolic_closure_provenance is not None
                else None
            ),
            "problem_source_provenance": (
                self.problem_source_provenance.to_payload()
                if self.problem_source_provenance is not None
                else None
            ),
        }


@dataclass(frozen=True)
class FunctionalRuntimeResult:
    """Prompt-safe value produced by one verified Functional call."""

    step_id: str
    scope_id: str
    capability_id: str
    produced_handle: str
    output_key: str
    runtime_type: str
    value: Any | None = None
    value_omitted_reason: str | None = None
    problem_source_provenance: ProblemCallSourceProvenance | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "step_id": self.step_id,
            "scope_id": self.scope_id,
            "capability_id": self.capability_id,
            "produced_handle": self.produced_handle,
            "output_key": self.output_key,
            "runtime_type": self.runtime_type,
        }
        if self.value is not None:
            payload["value"] = self.value
        if self.value_omitted_reason is not None:
            payload["value_omitted_reason"] = self.value_omitted_reason
        return payload

    def authority_payload(self) -> dict[str, Any]:
        """Return debug/checkpoint data without changing prompt-safe payloads."""

        payload = self.to_payload()
        payload["problem_source_provenance"] = (
            self.problem_source_provenance.to_payload()
            if self.problem_source_provenance is not None
            else None
        )
        return payload


@dataclass(frozen=True)
class FunctionalExecutionBlocker:
    """The root runtime blocker for a Functional call."""

    step_id: str
    scope_id: str
    stage: str
    code: str
    message: str
    capability_errors: tuple[str, ...] = ()
    capability_id: str | None = None
    missing_runtime_type: str | None = None
    details: dict[str, Any] | None = None
    retryable: bool = True

    def to_payload(self) -> dict[str, Any]:
        """转成可放入 previous_attempts 的安全 JSON。"""
        payload: dict[str, Any] = {
            "step_id": self.step_id,
            "scope_id": self.scope_id,
            "stage": self.stage,
            "code": self.code,
            "message": self.message,
            "capability_errors": list(self.capability_errors),
            "retryable": self.retryable,
        }
        if self.capability_id is not None:
            payload["capability_id"] = self.capability_id
        if self.missing_runtime_type is not None:
            payload["missing_runtime_type"] = self.missing_runtime_type
        if self.details is not None:
            payload["details"] = self.details
        return payload


@dataclass(frozen=True)
class FunctionalSkippedStep:
    """A call not executed because a typed dependency failed."""

    step_id: str
    scope_id: str
    reason: str

    def to_payload(self) -> dict[str, str]:
        """转成 debug JSON。"""
        return {
            "step_id": self.step_id,
            "scope_id": self.scope_id,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class FunctionalExecutionDiagnostic:
    """Prompt-safe diagnostic for one Functional transactional attempt.

    The report records verified calls, typed fills, root blockers, and skipped
    dependents. It is used by the repair loop and debug tooling; it is not a
    PlannerOutput and does not expose RuntimePath, expected answers, or traces.
    """

    ok: bool
    accepted_prefix: tuple[FunctionalAcceptedStep, ...] = ()
    applied_fills: tuple[FunctionalAppliedFill, ...] = ()
    planner_insights: tuple[FunctionalPlannerInsight, ...] = ()
    preflight_issues: tuple[FunctionalPreflightIssue, ...] = ()
    function_binding_events: tuple[FunctionalFunctionBindingEvent, ...] = ()
    macro_binding_events: tuple[FunctionalMacroBindingEvent, ...] = ()
    state_write_provenance: tuple[StateWriteProvenance, ...] = ()
    state_finalization_decisions: tuple[dict[str, Any], ...] = ()
    state_finalization_mismatches: tuple[dict[str, Any], ...] = ()
    runtime_destination_decisions: tuple[dict[str, Any], ...] = ()
    runtime_consumer_decisions: tuple[dict[str, Any], ...] = ()
    runtime_consumer_mismatches: tuple[dict[str, Any], ...] = ()
    legacy_runtime_identity_fallback_count: int = 0
    runtime_results: tuple[FunctionalRuntimeResult, ...] = ()
    blockers: tuple[FunctionalExecutionBlocker, ...] = ()
    skipped_steps: tuple[FunctionalSkippedStep, ...] = ()
    candidate_errors: tuple[str, ...] = ()

    @property
    def first_blocker(self) -> FunctionalExecutionBlocker | None:
        """返回第一个 runtime blocker。"""
        return self.blockers[0] if self.blockers else None

    def to_payload(self) -> dict[str, Any]:
        """转成 debug/repair JSON。"""
        return {
            "ok": self.ok,
            "accepted_prefix": [
                item.to_payload() for item in self.accepted_prefix
            ],
            "applied_fills": [
                item.to_payload() for item in self.applied_fills
            ],
            "planner_insights": [
                item.to_payload() for item in self.planner_insights
            ],
            "preflight_issues": [
                item.to_payload() for item in self.preflight_issues
            ],
            "function_binding_events": [
                item.to_payload() for item in self.function_binding_events
            ],
            "macro_binding_events": [
                item.to_payload() for item in self.macro_binding_events
            ],
            "state_write_provenance": [
                item.to_payload() for item in self.state_write_provenance
            ],
            "state_finalization_decisions": [
                dict(item) for item in self.state_finalization_decisions
            ],
            "state_finalization_mismatches": [
                dict(item) for item in self.state_finalization_mismatches
            ],
            "runtime_destination_decisions": [
                dict(item) for item in self.runtime_destination_decisions
            ],
            "runtime_consumer_decisions": [
                dict(item) for item in self.runtime_consumer_decisions
            ],
            "runtime_consumer_mismatches": [
                dict(item) for item in self.runtime_consumer_mismatches
            ],
            "legacy_runtime_identity_fallback_count": (
                self.legacy_runtime_identity_fallback_count
            ),
            "runtime_results": [
                item.to_payload() for item in self.runtime_results
            ],
            "blockers": [item.to_payload() for item in self.blockers],
            "skipped_steps": [item.to_payload() for item in self.skipped_steps],
            "candidate_errors": list(self.candidate_errors),
        }


PlannerRetryLayer = Literal[
    "replay",
    "functional_validation",
    "functional_elaboration",
    "functional_reconciliation",
    "semantic_reads",
    "handle_resolution",
    "validation",
    "normalization",
    "candidate_resolution",
    "trial_execution",
    "goal_verification",
    "answer_check",
]

PlannerRetryPreservePolicy = Literal[
    "preserve_all",
    "preserve_graph",
    "preserve_prefix",
    "preserve_step",
    "preserve_handles",
    "none",
]

PlannerReplayDepth = Literal[
    "functional_validation",
    "functional_elaboration",
    "functional_reconciliation",
    "semantic_reads",
    "handle_resolution",
    "validation",
    "normalization",
    "candidate_resolution",
    "trial_execution",
    "goal_verification",
    "answer_check",
]


@dataclass(frozen=True)
class PlannerRetryIssue:
    """LLM retry 的统一错误 envelope。"""

    layer: PlannerRetryLayer
    code: str
    step_id: str | None = None
    scope_id: str | None = None
    repair_target: str = "suffix"
    preserve_policy: PlannerRetryPreservePolicy = "preserve_prefix"
    message: str = ""
    hints: tuple[str, ...] = ()
    related_handles: tuple[str, ...] = ()
    details: dict[str, Any] | None = None
    diagnostic_authority: dict[str, Any] | None = None

    def to_authority_payload(self) -> dict[str, Any]:
        """Serialize internal retry authority; this payload is not prompt-safe."""
        payload: dict[str, Any] = {
            "layer": self.layer,
            "code": self.code,
            "step_id": self.step_id,
            "scope_id": self.scope_id,
            "repair_target": self.repair_target,
            "preserve_policy": self.preserve_policy,
            "message": self.message,
            "hints": list(self.hints),
            "related_handles": list(self.related_handles),
        }
        if self.details is not None:
            payload["details"] = self.details
        if self.diagnostic_authority is not None:
            payload["diagnostic_authority"] = self.diagnostic_authority
        return payload

    def to_payload(self) -> dict[str, Any]:
        """Compatibility alias for internal/debug serialization only."""

        return self.to_authority_payload()


@dataclass(frozen=True)
class PlannerRetryState:
    """Planner retry 的正式稳定状态。"""

    attempt: int
    repair_suffix_start: dict[str, str | None] | None = None
    issues: tuple[PlannerRetryIssue, ...] = ()
    recovered_issues: tuple[PlannerRetryIssue, ...] = ()
    preserve_policy: PlannerRetryPreservePolicy = "none"
    repair_instruction: str = ""
    replay_depth: PlannerReplayDepth | None = None
    selected_repair_layer: PlannerRetryLayer | None = None
    replay_timeline: tuple[dict[str, Any], ...] = ()
    replay_reports: dict[str, Any] | None = None
    source_context_id: str | None = None
    baseline_candidate: dict[str, Any] | None = None
    stable_candidate_calls: tuple[dict[str, Any], ...] = ()
    committed_candidate_calls: tuple[dict[str, Any], ...] = ()
    runtime_verified_calls: tuple[dict[str, Any], ...] = ()
    validated_call_ids: tuple[str, ...] = ()
    call_memory: tuple[dict[str, Any], ...] = ()
    repair_call_ids: tuple[str, ...] = ()
    functional_retry_graph_checkpoint: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        """转成 ``previous_attempts`` 和 prompt 可携带的安全 JSON。"""
        payload = {
            "attempt": self.attempt,
            "repair_suffix_start": self.repair_suffix_start,
            "issues": [issue.to_payload() for issue in self.issues],
            "recovered_issues": [
                issue.to_payload() for issue in self.recovered_issues
            ],
            "preserve_policy": self.preserve_policy,
            "repair_instruction": self.repair_instruction,
            "replay_depth": self.replay_depth,
            "selected_repair_layer": self.selected_repair_layer,
            "replay_timeline": list(self.replay_timeline),
            "replay_reports": self.replay_reports or {},
            "baseline_candidate": self.baseline_candidate,
            "stable_candidate_calls": list(self.stable_candidate_calls),
            "committed_candidate_calls": list(
                self.committed_candidate_calls
            ),
            "runtime_verified_calls": list(self.runtime_verified_calls),
            "validated_call_ids": list(self.validated_call_ids),
            "call_memory": list(self.call_memory),
            "repair_call_ids": list(self.repair_call_ids),
            "functional_retry_graph_checkpoint": (
                dict(self.functional_retry_graph_checkpoint)
                if self.functional_retry_graph_checkpoint is not None
                else None
            ),
        }
        if self.source_context_id is not None:
            payload["source"] = "planner_state_context"
            payload["source_context_id"] = self.source_context_id
        return payload


@dataclass(frozen=True)
class FunctionalRepairAttempt:
    """Prompt-safe FunctionalPlan retry envelope."""

    attempt: int
    repair_instruction: str
    planner_retry_state: PlannerRetryState | None = None
    errors: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "attempt": self.attempt,
            "planner_retry_state": (
                self.planner_retry_state.to_payload()
                if self.planner_retry_state is not None
                else None
            ),
            "repair_instruction": self.repair_instruction,
            "errors": list(self.errors),
            "planner_protocol": "functional_plan/v1",
        }


class StrategyDraftValidationError(ValueError):
    """LLM FunctionalPlan candidate violates the planner contract."""
