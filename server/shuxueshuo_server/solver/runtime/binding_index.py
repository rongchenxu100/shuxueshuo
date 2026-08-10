"""Canonical handle 到 RuntimeContext path 的绑定索引。

本模块只维护 LLM canonical Entity/Fact/answer handle 与 runtime ContextPath
之间的映射，不负责 method selector 或 recipe 编译。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re
from typing import Any, Literal

from shuxueshuo_server.solver.problem_models import QuestionGoal
from shuxueshuo_server.solver.runtime.context import RuntimeContext
from shuxueshuo_server.solver.runtime.functional_compile_contract import (
    compile_input_handles,
)
from shuxueshuo_server.solver.runtime.models import (
    ContextDeclaration,
    ContextPath,
    TypedValue,
    runtime_type_matches,
)
from shuxueshuo_server.solver.runtime.runtime_type_compatibility import (
    runtime_type_compatible,
    split_runtime_types,
)
from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
    _handle_name,
    _handle_scope,
    _require_scoped_handle,
    _semantic_name,
)
from shuxueshuo_server.solver.runtime.state_identity import (
    MathObjectId,
    MathObjectRegistry,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    CreatedEntity,
    ProducedFact,
    ProjectedStateWrite,
    ProjectedStateDependency,
    FunctionalAppliedFill,
    FunctionalCompileStepView,
    StrategyDraftValidationError,
)

@dataclass(frozen=True)
class RuntimeHandleBinding:
    """canonical handle 到 RuntimeContext path 的绑定记录。"""

    handle: str
    path: str
    value_type: str
    source: str
    output_key: str | None = None

class CanonicalRuntimeBindingIndex:
    """把 LLM canonical handle 映射到 runtime ContextPath。

    binding rule 只读取 Entity/Fact/answer
    handle，不再记住某一道题的固定点名。若 LLM 创建辅助点或 method 产生新 fact，
    index 会把它们注册为后续 step 可读取的语义 alias。
    """

    def __init__(
        self,
        context: RuntimeContext,
        handle_registry: CanonicalHandleRegistry,
        question_goals: list[QuestionGoal] | tuple[QuestionGoal, ...],
        functional_consumer_identity_mode: Literal[
            "shadow",
            "authoritative",
        ]
        | None = None,
        problem_binding_authority: bool = False,
    ) -> None:
        self.context = context
        self.handle_registry = handle_registry
        self.bindings: dict[str, RuntimeHandleBinding] = {}
        self.fact_types = dict(handle_registry.fact_types)
        self.answer_value_types = dict(handle_registry.answer_value_types)
        self.question_goals = {f"answer:{goal.id}": goal for goal in question_goals}
        self.functional_consumer_identity_mode = (
            functional_consumer_identity_mode
        )
        self.problem_binding_authority = problem_binding_authority
        self.declarations: dict[str, Any] = {}
        self.applied_fills: list[FunctionalAppliedFill] = []
        # Accepted Function/Macro writes. Binding selectors use this ledger to
        # preserve Symbol/Object identity instead of inferring it from names.
        self.state_write_provenance: list[Any] = []
        self.projected_state_writes: tuple[ProjectedStateWrite, ...] = ()
        self.projected_state_dependencies: tuple[
            ProjectedStateDependency, ...
        ] = ()
        self.known_state_versions: tuple[Any, ...] = ()
        self.runtime_consumer_decisions: list[dict[str, Any]] = []
        self.runtime_consumer_mismatches: list[dict[str, Any]] = []
        self.legacy_runtime_identity_fallback_count = 0
        self._projected_write_by_handle: dict[str, ProjectedStateWrite] = {}
        self._projected_step_order: dict[str, int] = {}
        self._register_initial_handles()

    @classmethod
    def from_context(
        cls,
        context: RuntimeContext,
        *,
        handle_registry: CanonicalHandleRegistry,
        question_goals: list[QuestionGoal] | tuple[QuestionGoal, ...],
        functional_consumer_identity_mode: Literal[
            "shadow",
            "authoritative",
        ]
        | None = None,
        problem_binding_authority: bool = False,
    ) -> "CanonicalRuntimeBindingIndex":
        """构建 handle index。"""
        return cls(
            context,
            handle_registry,
            question_goals,
            functional_consumer_identity_mode=(
                functional_consumer_identity_mode
            ),
            problem_binding_authority=problem_binding_authority,
        )

    def register(self, handle: str, path: str, value_type: str, *, source: str) -> None:
        """注册或覆盖一个 handle -> ContextPath 绑定。"""
        self.bindings[handle] = RuntimeHandleBinding(handle, path, value_type, source)

    def register_projected_state_writes(
        self,
        writes: tuple[ProjectedStateWrite, ...],
        *,
        dependencies: tuple[ProjectedStateDependency, ...] = (),
        known_state_versions: tuple[Any, ...] = (),
    ) -> None:
        """Attach the typed Functional state ledger to runtime bindings."""
        self.projected_state_writes = tuple(writes)
        self.projected_state_dependencies = tuple(dependencies)
        self.known_state_versions = tuple(known_state_versions)
        self._projected_write_by_handle = {
            item.produced_handle: item for item in writes
        }
        self._projected_step_order = {}
        for item in writes:
            self._projected_step_order.setdefault(
                item.step_id,
                len(self._projected_step_order),
            )

    def functional_state_read_index(self) -> Any:
        if self.functional_consumer_identity_mode is None:
            raise StrategyDraftValidationError(
                "planner_configuration_error: "
                "planner.runtime_state_binding_drift: "
                "Functional typed read index requested in FunctionalCompileStepView mode"
            )
        from shuxueshuo_server.solver.runtime.functional_state_reads import (
            FunctionalStateReadIndex,
        )

        return FunctionalStateReadIndex.from_sources(
            handle_registry=self.handle_registry,
            mode=self.functional_consumer_identity_mode,
            projected_state_writes=self.projected_state_writes,
            projected_state_dependencies=(
                self.projected_state_dependencies
            ),
            state_write_provenance=tuple(self.state_write_provenance),
            runtime_bindings=self.bindings,
            known_state_versions=self.known_state_versions,
        )

    def runtime_path_for_state_version(
        self,
        version_id: Any,
        *,
        consumer_scope_id: str,
        consumer: str,
    ) -> str:
        read_index = self.functional_state_read_index()
        path = read_index.runtime_path_for_version(
            version_id,
            consumer_scope_id=consumer_scope_id,
            consumer=consumer,
        )
        self.capture_functional_read_audit(read_index)
        return path

    def runtime_path_for_condition_identity(
        self,
        condition_id: str,
        *,
        source_handle: str,
        expected_type: str,
        consumer_scope_id: str,
        consumer: str,
    ) -> str:
        """Project a typed condition identity to its physical runtime path."""

        if not condition_id:
            raise StrategyDraftValidationError(
                "planner_configuration_error: "
                "planner.state_identity_incomplete: "
                f"consumer={consumer}, condition_id={condition_id!r}"
            )
        return self._runtime_path_for_typed_value_identity(
            source_handle=source_handle,
            expected_type=expected_type,
            consumer_scope_id=consumer_scope_id,
            consumer=consumer,
            identity_kind="condition",
            identity_value=condition_id,
            source_call_id=None,
        )

    def runtime_path_for_call_result_identity(
        self,
        source_call_id: str,
        source_return_name: str,
        *,
        source_handle: str,
        expected_type: str,
        consumer_scope_id: str,
        consumer: str,
    ) -> str:
        """Project a typed public call result to its physical runtime path."""

        if not source_call_id or not source_return_name:
            raise StrategyDraftValidationError(
                "planner_configuration_error: "
                "planner.state_identity_incomplete: "
                f"consumer={consumer}, "
                f"call_result={source_call_id}.{source_return_name}"
            )
        return self._runtime_path_for_typed_value_identity(
            source_handle=source_handle,
            expected_type=expected_type,
            consumer_scope_id=consumer_scope_id,
            consumer=consumer,
            identity_kind="call_result",
            identity_value=f"{source_call_id}.{source_return_name}",
            source_call_id=source_call_id,
        )

    def _runtime_path_for_typed_value_identity(
        self,
        *,
        source_handle: str,
        expected_type: str,
        consumer_scope_id: str,
        consumer: str,
        identity_kind: Literal["condition", "call_result"],
        identity_value: str,
        source_call_id: str | None,
    ) -> str:
        """Validate a typed non-state identity at the physical binding edge."""

        binding = self.bindings.get(source_handle)
        if binding is None or not runtime_type_compatible(
            expected_type,
            binding.value_type,
        ):
            raise StrategyDraftValidationError(
                "planner_configuration_error: "
                "planner.runtime_state_binding_drift: "
                f"consumer={consumer}, {identity_kind}={identity_value}, "
                f"handle={source_handle}, expected_type={expected_type}"
            )
        if (
            identity_kind == "call_result"
            and binding.source != f"step:{source_call_id}"
        ):
            raise StrategyDraftValidationError(
                "planner_configuration_error: "
                "planner.runtime_state_binding_drift: "
                f"consumer={consumer}, call_result={identity_value}, "
                f"handle={source_handle}, binding_source={binding.source}"
            )
        try:
            path = ContextPath.parse(binding.path)
        except ValueError as exc:
            raise StrategyDraftValidationError(
                "planner_configuration_error: "
                "planner.runtime_state_binding_drift: "
                f"consumer={consumer}, {identity_kind}={identity_value}, "
                f"path={binding.path}"
            ) from exc
        if path.scope_type == "step":
            visible = (
                identity_kind == "call_result"
                and source_call_id == path.scope_id
            )
        else:
            visible = path.scope_id in self.handle_registry.ancestor_scopes(
                consumer_scope_id
            )
        if not visible:
            raise StrategyDraftValidationError(
                "planner_configuration_error: "
                "planner.runtime_state_visibility_drift: "
                f"consumer={consumer}, {identity_kind}={identity_value}, "
                f"path_scope={path.scope_id}"
            )
        decision = {
            "consumer": consumer,
            "action": f"typed_{identity_kind}_binding",
            f"{identity_kind}_id": identity_value,
            "runtime_path": binding.path,
            "reason_code": f"typed_{identity_kind}_identity",
        }
        if decision not in self.runtime_consumer_decisions:
            self.runtime_consumer_decisions.append(decision)
        return binding.path

    def runtime_path_for_object_identity(
        self,
        object_id: MathObjectId,
        *,
        expected_type: str,
        consumer_scope_id: str,
        consumer: str,
    ) -> str:
        """Project one typed object identity to its unique physical binding."""

        registry = MathObjectRegistry.from_sources(self.handle_registry)
        candidates: dict[str, tuple[RuntimeHandleBinding, str]] = {}
        expected_types = set(split_runtime_types(expected_type))
        canonical_binding = self.bindings.get(object_id.value)
        if (
            canonical_binding is not None
            and runtime_type_compatible(
                expected_type,
                canonical_binding.value_type,
            )
            and (
                registry.resolve(object_id.value) == object_id
                or canonical_binding.source
                in {
                    "created_entity",
                    "declaration",
                    "typed_return_identity",
                    "transactional_state_version",
                }
                or canonical_binding.source.startswith("step:")
            )
        ):
            try:
                canonical_scope = ContextPath.parse(
                    canonical_binding.path
                ).scope_id
            except ValueError:
                canonical_scope = object_id.origin_scope_id
            if canonical_scope in self.handle_registry.ancestor_scopes(
                consumer_scope_id
            ):
                runtime_path = canonical_binding.path
                if (
                    "PointRef" in expected_types
                    and canonical_binding.value_type == "Point"
                ):
                    runtime_path = self.immutable_point_identity_path_for(
                        object_id
                    )
                self._record_object_identity_decision(
                    consumer=consumer,
                    object_id=object_id,
                    binding=canonical_binding,
                    runtime_path=runtime_path,
                )
                return runtime_path
        for handle, binding in self.bindings.items():
            if not runtime_type_compatible(expected_type, binding.value_type):
                continue
            if registry.resolve(handle) != object_id:
                continue
            try:
                path_scope = ContextPath.parse(binding.path).scope_id
            except ValueError:
                path_scope = "problem"
            if path_scope not in self.handle_registry.ancestor_scopes(
                consumer_scope_id
            ):
                continue
            runtime_path = binding.path
            if (
                "PointRef" in expected_types
                and binding.value_type == "Point"
            ):
                try:
                    runtime_path = self.immutable_point_identity_path_for(
                        object_id
                    )
                except StrategyDraftValidationError:
                    continue
            candidates[runtime_path] = (binding, runtime_path)
        if len(candidates) != 1:
            raise StrategyDraftValidationError(
                "planner_configuration_error: "
                "planner.runtime_state_binding_drift: "
                f"consumer={consumer}, object={object_id.to_payload()}, "
                f"expected_type={expected_type}, "
                f"binding_count={len(candidates)}"
            )
        binding, runtime_path = next(iter(candidates.values()))
        self._record_object_identity_decision(
            consumer=consumer,
            object_id=object_id,
            binding=binding,
            runtime_path=runtime_path,
        )
        return runtime_path

    def runtime_path_for_return_object_identity(
        self,
        object_id: MathObjectId,
        *,
        expected_type: str,
        consumer_scope_id: str,
        consumer: str,
    ) -> str:
        """Project a return target identity, declaring a new PointRef if needed.

        Ordinary object inputs must already have a typed runtime binding.
        A Point return is different: reconciliation may allocate a new derived
        MathObject whose identity has to exist before the method can write its
        first coordinate state.
        """
        try:
            return self.runtime_path_for_object_identity(
                object_id,
                expected_type=expected_type,
                consumer_scope_id=consumer_scope_id,
                consumer=consumer,
            )
        except StrategyDraftValidationError as exc:
            if object_id.value in self.bindings:
                raise exc
        expected_types = set(split_runtime_types(expected_type))
        if object_id.kind != "point" or "PointRef" not in expected_types:
            raise StrategyDraftValidationError(
                "planner_configuration_error: "
                "planner.runtime_state_binding_drift: "
                f"consumer={consumer}, object={object_id.to_payload()}, "
                f"expected_type={expected_type}, binding_count=0"
            )
        try:
            kind, scope_id, name = _require_scoped_handle(object_id.value)
        except ValueError as exc:
            raise StrategyDraftValidationError(
                "planner_configuration_error: "
                "planner.state_identity_incomplete: "
                f"consumer={consumer}, object={object_id.to_payload()}"
            ) from exc
        if kind != "point" or scope_id != object_id.origin_scope_id:
            raise StrategyDraftValidationError(
                "planner_configuration_error: "
                "planner.state_identity_incomplete: "
                f"consumer={consumer}, object={object_id.to_payload()}"
            )
        if scope_id not in self.handle_registry.ancestor_scopes(
            consumer_scope_id
        ):
            raise StrategyDraftValidationError(
                "planner_configuration_error: "
                "planner.runtime_state_visibility_drift: "
                f"consumer={consumer}, object={object_id.to_payload()}"
            )
        path = _runtime_path_for_scope(
            self.context,
            scope_id,
            "points",
            name,
        )
        declaration = _point_declaration_for_path(
            self.context,
            path,
            definition="functional_derived_object",
        )
        self.declarations[declaration.path] = declaration
        binding = RuntimeHandleBinding(
            object_id.value,
            declaration.path,
            "PointRef",
            "typed_return_identity",
        )
        self.bindings[object_id.value] = binding
        self._record_object_identity_decision(
            consumer=consumer,
            object_id=object_id,
            binding=binding,
            runtime_path=path,
        )
        return path

    def _record_object_identity_decision(
        self,
        *,
        consumer: str,
        object_id: MathObjectId,
        binding: RuntimeHandleBinding,
        runtime_path: str,
    ) -> None:
        decision = {
            "consumer": consumer,
            "action": "identity_binding",
            "version_id": None,
            "math_object_id": object_id.to_payload(),
            "runtime_path": runtime_path,
            "reason_code": (
                "typed_object_identity_point_ref_projection"
                if runtime_path != binding.path
                else "typed_object_identity"
            ),
        }
        if decision not in self.runtime_consumer_decisions:
            self.runtime_consumer_decisions.append(decision)

    def record_legacy_runtime_identity_fallback(
        self,
        *,
        consumer: str,
        handle: str,
        reason: str,
    ) -> None:
        """Count every Functional string fallback and fail in authoritative mode."""

        mismatch = {
            "code": "legacy_runtime_identity_fallback",
            "consumer": consumer,
            "handle": handle,
            "reason": reason,
        }
        if mismatch not in self.runtime_consumer_mismatches:
            self.runtime_consumer_mismatches.append(mismatch)
            self.legacy_runtime_identity_fallback_count += 1
        if self.functional_consumer_identity_mode == "authoritative":
            raise StrategyDraftValidationError(
                "planner_configuration_error: "
                "planner.runtime_state_binding_drift: "
                f"consumer={consumer}, handle={handle}, reason={reason}"
            )

    def capture_functional_read_audit(self, read_index: Any) -> None:
        for item in read_index.decisions:
            payload = item.to_payload()
            if payload not in self.runtime_consumer_decisions:
                self.runtime_consumer_decisions.append(payload)
        for item in read_index.mismatches:
            payload = dict(item)
            if payload not in self.runtime_consumer_mismatches:
                self.runtime_consumer_mismatches.append(payload)
        self.legacy_runtime_identity_fallback_count = sum(
            1
            for item in self.runtime_consumer_mismatches
            if item.get("code") == "legacy_runtime_identity_fallback"
        )

    def projected_state_write_for_handle(
        self,
        handle: str,
    ) -> ProjectedStateWrite | None:
        return self._projected_write_by_handle.get(handle)

    def latest_projected_state_write(
        self,
        object_ref: str,
        *,
        before_step_id: str | None = None,
    ) -> ProjectedStateWrite | None:
        cutoff = self._projected_step_order.get(
            before_step_id,
            len(self._projected_step_order),
        )
        candidates = [
            item
            for item in self.projected_state_writes
            if item.object_ref == object_ref
            and self._projected_step_order.get(item.step_id, cutoff) < cutoff
        ]
        return candidates[-1] if candidates else None

    def latest_projected_state_write_in_handles(
        self,
        object_ref: str,
        handles: tuple[str, ...],
        *,
        before_step_id: str | None = None,
    ) -> ProjectedStateWrite | None:
        """Select the newest visible version by graph order, not read order."""
        handle_set = set(handles)
        cutoff = self._projected_step_order.get(
            before_step_id,
            len(self._projected_step_order),
        )
        candidates = [
            item
            for item in self.projected_state_writes
            if item.object_ref == object_ref
            and item.produced_handle in handle_set
            and self._projected_step_order.get(item.step_id, cutoff) < cutoff
        ]
        return candidates[-1] if candidates else None

    def record_applied_fill(
        self,
        *,
        step: FunctionalCompileStepView,
        input_handle: str,
        required_type: str,
        resolved_handle: str,
        reason: str,
    ) -> None:
        """记录一次 Entity/Facts 补位，供 execution diagnostic 使用。"""
        fill = FunctionalAppliedFill(
            step_id=step.step_id,
            scope_id=step.scope_id,
            input_handle=input_handle,
            required_type=required_type,
            resolved_handle=resolved_handle,
            reason=reason,
        )
        if fill not in self.applied_fills:
            self.applied_fills.append(fill)

    def path_for(self, handle: str, *, expected_type: str | None = None) -> str:
        """读取 handle 对应 ContextPath，并可选校验类型。"""
        try:
            binding = self.bindings[handle]
        except KeyError as exc:
            raise StrategyDraftValidationError(f"binding_not_found: {handle}") from exc
        if expected_type is not None and not runtime_type_matches(expected_type, binding.value_type):
            if not (expected_type == "Point" and binding.value_type == "PointRef"):
                if expected_type == "PointRef" and binding.value_type == "Point":
                    raise StrategyDraftValidationError(
                        "duplicate_point_coordinate_fact: "
                        f"handle={handle} is already a computed Point at {binding.path}; "
                        "do not call a construction/midpoint method with this point as an unresolved target. "
                        "Read the existing coordinate fact instead, or produce the broader reusable fact before "
                        "subquestion-specific substitutions."
                    )
                raise StrategyDraftValidationError(
                    f"binding_type_mismatch: {handle} expected {expected_type}, got {binding.value_type}"
                )
        return binding.path

    def point_ref_path_for(self, handle: str) -> str:
        """读取点实体的 PointRef path，兼容可解析 PointRef 的 Point 绑定。

        problem scope 中一些定义点（如 y 轴交点、平移点）在注册时会被标成
        ``Point``，方便普通 method 读取坐标。但当另一个 method 正在显式计算这个
        定义点时，仍需要把底层 ``PointRef`` 作为 target 传入。
        """
        binding = self.binding_for(handle)
        if binding.value_type == "PointRef":
            return binding.path
        value = None
        try:
            path = ContextPath.parse(binding.path)
            value = self.context.get_scope(path.scope_id).container(path.container)[path.key]
        except Exception:
            pass
        if value is not None and value.type == "PointRef":
            return binding.path
        # A computed coordinate may become the canonical binding for a point,
        # while the original object identity is still present in the scope's
        # points container. Object-oriented methods need that PointRef rather
        # than the latest coordinate StateSlot.
        try:
            kind, scope_id, name = _require_scoped_handle(handle)
            if kind != "point":
                raise ValueError(handle)
            original_path = _runtime_path_for_scope(
                self.context,
                scope_id,
                "points",
                name,
            )
            path = ContextPath.parse(original_path)
            original = self.context.get_scope(path.scope_id).container(
                path.container
            )[path.key]
            if original.type == "PointRef":
                return original_path
        except Exception:
            pass
        raise StrategyDraftValidationError(
            "duplicate_point_coordinate_fact: "
            f"handle={handle} is already a computed Point at {binding.path}; "
            "do not call a construction/midpoint method with this point as an unresolved target. "
            "Read the existing coordinate fact instead."
        )

    def immutable_problem_point_ref_path_for(self, handle: str) -> str:
        """Bind a ProblemIR point's original definition at an immutable path.

        Use this only for methods whose behavior depends on the target's
        structured ProblemIR definition. Ordinary construction targets retain
        ``point_ref_path_for`` duplicate-write semantics.
        """
        recovered = self._recover_problem_point_ref_path(handle)
        if recovered is not None:
            return recovered
        return self.point_ref_path_for(handle)

    def immutable_point_identity_path_for(
        self,
        object_id: MathObjectId,
    ) -> str:
        """Project typed Point identity without replacing its coordinate state."""

        recovered = self._recover_problem_point_ref_path(object_id.value)
        if recovered is not None:
            return recovered
        try:
            kind, scope_id, name = _require_scoped_handle(object_id.value)
        except ValueError as exc:
            raise StrategyDraftValidationError(
                "planner_configuration_error: "
                "planner.state_identity_incomplete: "
                f"object={object_id.to_payload()}"
            ) from exc
        if (
            kind != "point"
            or object_id.kind != "point"
            or scope_id != object_id.origin_scope_id
        ):
            raise StrategyDraftValidationError(
                "planner_configuration_error: "
                "planner.state_identity_incomplete: "
                f"object={object_id.to_payload()}"
            )
        raw_path = _runtime_path_for_scope(
            self.context,
            scope_id,
            "object_refs",
            name,
        )
        try:
            existing = self.context.read_path(
                raw_path,
                from_scope_id=scope_id,
                expected_type="PointRef",
            )
            if existing.type == "PointRef":
                return raw_path
        except (KeyError, PermissionError, TypeError, ValueError):
            pass
        self.declarations[raw_path] = ContextDeclaration(
            path=raw_path,
            type="PointRef",
            name=name,
            definition={"definition": "functional_typed_object_identity"},
            scope_id=scope_id,
            source="typed_object_identity",
        )
        return raw_path

    def _recover_problem_point_ref_path(self, handle: str) -> str | None:
        """Rebuild immutable object identity after its coordinate overwrote it.

        RuntimeContext intentionally stores the latest Point value at the
        canonical object path. Object-oriented methods may still need the
        original ProblemIR definition (translation vector, construction role,
        and so on), so keep that definition at a separate declaration path.
        """
        payload = self.handle_registry.entity_payloads.get(handle)
        if not isinstance(payload, Mapping):
            return None
        try:
            kind, scope_id, name = _require_scoped_handle(handle)
        except ValueError:
            return None
        if kind != "point":
            return None
        raw_path = _runtime_path_for_scope(
            self.context,
            scope_id,
            "object_refs",
            name,
        )
        definition = {
            key: value
            for key, value in payload.items()
            if key
            not in {
                "handle",
                "entity_type",
                "name",
                "scope_id",
                "description",
            }
        }
        declaration = ContextDeclaration(
            path=raw_path,
            type="PointRef",
            name=name,
            definition=definition,
            scope_id=scope_id,
            source="problem_identity",
        )
        self.declarations[declaration.path] = declaration
        return declaration.path

    def point_identity_path_for(self, handle: str) -> str:
        """Return a point object path without treating a coordinate as a target.

        Inputs typed as ``PointRef|Point`` and named ``*_ref`` are converted by
        InvocationExecutor from a points-container coordinate back to PointRef.
        This is appropriate for identity metadata such as an already known
        square side, but deliberately separate from construction targets where
        an existing Point must still trigger the duplicate-write guard.
        """
        binding = self.binding_for(handle)
        try:
            path = ContextPath.parse(binding.path)
        except Exception as exc:
            raise StrategyDraftValidationError(
                f"point_identity_path_not_found: {handle}"
            ) from exc
        if (
            binding.value_type in {"Point", "PointRef"}
            and path.container == "points"
        ):
            if binding.value_type == "Point":
                recovered = self._recover_problem_point_ref_path(handle)
                if recovered is not None:
                    return recovered
            return binding.path
        return self.point_ref_path_for(handle)

    def binding_for(self, handle: str) -> RuntimeHandleBinding:
        """返回绑定对象。"""
        try:
            return self.bindings[handle]
        except KeyError as exc:
            raise StrategyDraftValidationError(f"binding_not_found: {handle}") from exc

    def register_created_entity(self, item: CreatedEntity) -> RuntimeHandleBinding:
        """把 LLM creates[] 声明成 runtime PointRef。"""
        if item.entity_type != "point":
            raise StrategyDraftValidationError(
                f"recipe_trial_unsupported_created_entity: {item.handle}"
            )
        kind, scope_id, name = _require_scoped_handle(item.handle)
        if kind != "point":
            raise StrategyDraftValidationError(
                f"created_entity_handle_type_mismatch: {item.handle}"
            )
        path = _runtime_path_for_scope(self.context, scope_id, "points", name)
        declaration = _point_declaration_for_path(
            self.context,
            path,
            definition="straightening_auxiliary_point",
        )
        self.declarations[item.handle] = declaration
        binding = RuntimeHandleBinding(item.handle, path, "PointRef", "created_entity")
        self.bindings[item.handle] = binding
        return binding

    def ensure_point_declaration(self, handle: str, *, definition: str) -> Any | None:
        """确保某个 point handle 有 PointRef declaration。

        已存在于 RuntimeContext 的点不需要 declaration；尚未存在但后续 method 需要
        写入的目标点会在这里声明。
        """
        binding = self.binding_for(handle)
        if binding.value_type in {"Point", "PointRef"} and _context_path_exists(self.context, binding.path):
            return None
        kind, scope_id, name = _require_scoped_handle(handle)
        if kind != "point":
            raise StrategyDraftValidationError(f"declaration_requires_point_handle: {handle}")
        declaration = _point_declaration_for_path(
            self.context,
            binding.path,
            definition=definition,
        )
        self.declarations[declaration.path] = declaration
        self.bindings[handle] = RuntimeHandleBinding(handle, declaration.path, "PointRef", "declaration")
        return declaration

    def register_produced(
        self,
        produced: ProducedFact,
        *,
        output_path: str,
        output_type: str,
        source: str,
    ) -> None:
        """把 method 输出路径注册成 produced fact/answer 的后续可读 alias。"""
        self.register(produced.handle, output_path, output_type, source=source)

    def handles_by_fact_type(self, fact_type: str) -> list[str]:
        """按 fact type 返回 handle，保持字符串排序稳定。"""
        return sorted(
            handle for handle, current_type in self.fact_types.items()
            if current_type == fact_type
        )

    def entity_payload(self, handle: str) -> dict[str, Any]:
        """读取 canonical Entity 的结构化 payload。"""
        try:
            return self.handle_registry.entity_payloads[handle]
        except KeyError as exc:
            raise StrategyDraftValidationError(f"entity_payload_not_found: {handle}") from exc

    def entity_semantic_name(self, handle: str) -> str:
        """Return the source-visible name without treating a local id as identity.

        Direct ProblemIR authoring deliberately allows an arbitrary local id such
        as ``A_iii`` for a point whose printed name is ``A``. RuntimeContext stores
        source points and symbols by that printed name, while canonical handles
        retain the local id. Keep those two responsibilities separate here.
        """

        payload = self.handle_registry.entity_payloads.get(handle)
        if payload is None:
            # Runtime-created/declaration points do not originate in ProblemIR
            # and therefore have no source-visible ``name`` field. Their
            # producer-owned handle is the canonical name by construction.
            return _handle_name(handle)
        name = str(payload.get("name", "")).strip()
        return name or _handle_name(handle)

    def fact_payload(self, handle: str) -> dict[str, Any]:
        """读取 canonical Fact 的结构化 payload。"""
        try:
            return self.handle_registry.fact_payloads[handle]
        except KeyError as exc:
            raise StrategyDraftValidationError(f"fact_payload_not_found: {handle}") from exc

    def entity_handles(self, kind: str, *, step: FunctionalCompileStepView | None = None) -> list[str]:
        """按实体类型返回 handle；若提供 step，优先保留 step.reads 中出现的实体。"""
        handles = [
            handle for handle in self.bindings
            if handle.startswith(f"{kind}:")
        ]
        if step is None:
            return sorted(handles)
        input_handles = compile_input_handles(step)
        read_set = set(input_handles)
        return [
            handle for handle in input_handles if handle in handles
        ] + sorted(handle for handle in handles if handle not in read_set)

    def point_handle_by_name(self, name: str, *, step: FunctionalCompileStepView | None = None) -> str:
        """按点名查找 point handle，优先当前 step reads 和当前 scope。

        同一道综合题中，不同小问经常会复用同一个字母点名，例如
        ``point:i_2:G`` 与 ``point:ii:G``。binding 阶段必须按当前 step
        的可见性选择，不能因为注册顺序误读 sibling scope 的同名点。
        """
        candidates = [
            handle for handle in self.entity_handles("point")
            if self.entity_semantic_name(handle) == name
        ]
        # Old canonical payloads did not always carry ``name``. This fallback is
        # compatibility-only; a populated semantic name never gets overwritten
        # by the canonical handle suffix.
        if not candidates:
            candidates = [
                handle for handle in self.entity_handles("point")
                if _handle_name(handle) == name
            ]
        if step is not None:
            candidates = [
                handle for handle in candidates
                if self._handle_binding_visible(handle, step.scope_id)
            ]
            read_candidates = [
                handle for handle in compile_input_handles(step)
                if handle in candidates
            ]
            if read_candidates:
                if len(read_candidates) != 1:
                    raise StrategyDraftValidationError(
                        "point_semantic_name_ambiguous: "
                        f"name={name}, scope={step.scope_id}, "
                        f"candidates={sorted(read_candidates)}"
                    )
                return read_candidates[0]
            candidates = sorted(
                candidates,
                key=lambda handle: (
                    self._scope_distance(
                        step.scope_id,
                        _binding_scope(self.binding_for(handle).path),
                    ),
                    handle,
                ),
            )
        if not candidates:
            raise StrategyDraftValidationError(f"point_handle_not_found: {name}")
        if step is None:
            if len(candidates) != 1:
                raise StrategyDraftValidationError(
                    "point_semantic_name_ambiguous: "
                    f"name={name}, candidates={sorted(candidates)}"
                )
            return candidates[0]
        best_distance = self._scope_distance(
            step.scope_id,
            _binding_scope(self.binding_for(candidates[0]).path),
        )
        nearest = [
            handle
            for handle in candidates
            if self._scope_distance(
                step.scope_id,
                _binding_scope(self.binding_for(handle).path),
            )
            == best_distance
        ]
        if len(nearest) != 1:
            raise StrategyDraftValidationError(
                "point_semantic_name_ambiguous: "
                f"name={name}, scope={step.scope_id}, candidates={sorted(nearest)}"
            )
        return nearest[0]

    def fact_handle_by_type(
        self,
        fact_type: str,
        *,
        step: FunctionalCompileStepView | None = None,
        predicate: Any | None = None,
    ) -> str:
        """按 fact type 查找 handle，优先 step.reads 和当前 scope。"""
        handles = self.handles_by_fact_type(fact_type)
        if predicate is not None:
            handles = [handle for handle in handles if predicate(handle)]
        if step is not None:
            for handle in compile_input_handles(step):
                if handle in handles and self._handle_binding_visible(handle, step.scope_id):
                    return handle
            visible_handles = [
                handle for handle in handles
                if self._handle_binding_visible(handle, step.scope_id)
            ]
            if visible_handles:
                return sorted(
                    visible_handles,
                    key=lambda handle: (
                        self._scope_distance(
                            step.scope_id,
                            _binding_scope(self.binding_for(handle).path),
                        ),
                        handle,
                    ),
                )[0]
        if len(handles) == 1:
            return handles[0]
        if handles:
            return handles[0]
        raise StrategyDraftValidationError(f"fact_handle_not_found: {fact_type}")

    def _handle_binding_visible(self, handle: str, from_scope_id: str) -> bool:
        """判断 handle 对应 runtime path 是否从当前 step scope 可见。"""
        try:
            binding = self.binding_for(handle)
        except StrategyDraftValidationError:
            return False
        return self.context.is_visible(from_scope_id, _binding_scope(binding.path))

    def _scope_distance(self, from_scope_id: str, target_scope_id: str) -> int:
        """返回 target 在 from_scope 父链上的距离；不可见时排到最后。"""
        current: str | None = from_scope_id
        distance = 0
        while current is not None:
            if current == target_scope_id:
                return distance
            current = self.context.scopes[current].parent_id
            distance += 1
        return 10_000

    def parameter_symbol_path(self) -> str:
        """返回当前 step family 要求解的主参数符号路径。

        主参数不是“除去 x/a/b/c 后剩下的字母”。例如河西第（Ⅲ）问要求解
        的是系数 ``b``，而动点参数是 ``n``。这里优先读 QuestionGoal 和
        ProblemIR 的 ``symbol_roles``，只有旧数据缺少角色声明时才使用 runtime
        中的系数列表作保守兜底。
        """
        symbol_handle, _constraint_handle = self._primary_parameter_handles()
        return self.path_for(symbol_handle, expected_type="Symbol")

    def parameter_constraint_path(self) -> str:
        """返回当前主参数的范围约束路径。"""
        _symbol_handle, constraint_handle = self._primary_parameter_handles()
        return self.path_for(constraint_handle, expected_type="Constraint")

    def _primary_parameter_handles(self) -> tuple[str, str]:
        """返回 ``(symbol_handle, constraint_handle)`` 主参数候选。"""
        candidates = self._symbol_constraint_candidates()
        if not candidates:
            raise StrategyDraftValidationError("dynamic_parameter_symbol_not_found")

        # 若题面最终答案就是某个参数值，优先把这个符号作为主参数。河西第（Ⅲ）
        # 问的 ``answer_key=b`` 就属于这种情况，不能因为 b 是二次函数系数而排除。
        answer_parameter_names = {
            goal.answer_key
            for goal in self.question_goals.values()
            if goal.value_type == "ParameterValue"
        }
        for candidate in candidates:
            symbol = _handle_name(candidate[0])
            if symbol in answer_parameter_names:
                return candidate

        for candidate in candidates:
            symbol = _handle_name(candidate[0])
            if self._symbol_has_role(symbol, "primary_parameter"):
                return candidate

        for candidate in candidates:
            symbol = _handle_name(candidate[0])
            if self._symbol_has_role(symbol, "dynamic_parameter"):
                return candidate

        structural_symbols = self._structural_symbol_names()
        non_structural = [
            candidate for candidate in candidates
            if _handle_name(candidate[0]) not in structural_symbols
        ]
        if len(non_structural) == 1:
            return non_structural[0]
        if len(candidates) == 1:
            return candidates[0]
        raise StrategyDraftValidationError("dynamic_parameter_symbol_not_found")

    def _symbol_constraint_candidates(self) -> list[tuple[str, str]]:
        """返回所有带范围约束且存在 runtime symbol 的符号候选。"""
        candidates: list[tuple[str, str]] = []
        for constraint_handle in self.handles_by_fact_type("symbol_constraint"):
            payload = self.handle_registry.fact_payloads.get(constraint_handle, {})
            subject = payload.get("subject")
            symbol_handle = (
                subject
                if isinstance(subject, str) and subject.startswith("symbol:")
                else None
            )
            if symbol_handle is None:
                # Compatibility for old facts that encoded identity only in the
                # constraint handle. New typed ProblemIR must use ``subject``.
                symbol = _symbol_from_constraint_handle(constraint_handle)
                constraint_scope = self.handle_registry.handle_valid_scopes.get(
                    constraint_handle,
                    "problem",
                )
                symbol_handle = f"symbol:{constraint_scope}:{symbol}"
            if symbol_handle in self.bindings:
                candidates.append((symbol_handle, constraint_handle))
        return candidates

    def _symbol_has_role(self, symbol: str, role: str) -> bool:
        """判断 ProblemIR 是否给某个符号声明了指定角色。"""
        return self.context.problem.symbol_roles.get(symbol) == role

    def _structural_symbol_names(self) -> set[str]:
        """返回函数变量、二次函数系数等结构性符号名。

        这些符号通常不是“本问要求解的主参数”。首选 ProblemIR.symbol_roles；
        若旧 fixture 没有角色声明，则读取 ContextBuilder 已生成的
        ``quadratic_coefficients`` 列表，避免在 compiler 中写死 a/b/c。
        """
        names = {
            name
            for name, role in self.context.problem.symbol_roles.items()
            if role in {"function_variable", "quadratic_coefficient"}
        }
        if names:
            return names
        coefficients = self.context.problem_scope.container("symbol_lists").get(
            "quadratic_coefficients"
        )
        if coefficients is None:
            return set()
        return {str(symbol) for symbol in coefficients.value}

    def is_structural_symbol_value_fact(self, handle: str) -> bool:
        """判断某个 ``*_value`` fact 是否只是结构符号的已知值。

        Strategy binding 中经常需要从 reads 里找“前序 step 求出的参数值”。
        题设给出的二次函数系数值（如 a=2、c=-5）也是 ``symbol_value``，
        但它们不应被当作参数求解结果。这里复用 ProblemIR.symbol_roles /
        quadratic_coefficients，而不是写死 a/b/c。
        """
        if self.fact_types.get(handle) != "symbol_value":
            return False
        name = _semantic_name(handle)
        if not name.endswith("_value"):
            return False
        symbol = name[: -len("_value")]
        if symbol.startswith("parameter_"):
            symbol = symbol[len("parameter_") :]
        return symbol in self._structural_symbol_names()

    def dynamic_parameter_symbol_path(self, *, step: FunctionalCompileStepView | None = None) -> str:
        """返回动点参数符号路径。

        ``parameter_symbol_path`` 表示当前要求解的主参数，例如河西第（Ⅲ）问的
        ``b``。weighted path method 还需要动点自身的参数，例如 ``N(n,0)`` 中
        的 ``n``。这里从 ``symbol_constraint`` fact 中排除主参数，再按当前
        FunctionalCompileStepView.reads 消歧，避免把动点参数名写死为 ``n``。
        """
        symbol_handle, _constraint_handle = self._dynamic_parameter_handles(step=step)
        return self.path_for(symbol_handle, expected_type="Symbol")

    def dynamic_constraint_path(self, *, step: FunctionalCompileStepView | None = None) -> str:
        """返回动点参数范围约束路径。"""
        _symbol_handle, constraint_handle = self._dynamic_parameter_handles(step=step)
        return self.path_for(constraint_handle, expected_type="Constraint")

    def _dynamic_parameter_handles(
        self,
        *,
        step: FunctionalCompileStepView | None = None,
    ) -> tuple[str, str]:
        """返回 ``(symbol_handle, constraint_handle)`` 动点参数候选。"""
        primary_symbol = ContextPath.parse(self.parameter_symbol_path()).key
        candidates: list[tuple[str, str]] = []
        for symbol_handle, constraint_handle in self._symbol_constraint_candidates():
            symbol = _handle_name(symbol_handle)
            if symbol == primary_symbol:
                continue
            candidates.append((symbol_handle, constraint_handle))
        if step is not None:
            for read_handle in compile_input_handles(step):
                for candidate in candidates:
                    if read_handle in candidate:
                        return candidate
        role_candidates = [
            candidate for candidate in candidates
            if self._symbol_has_role(_handle_name(candidate[0]), "dynamic_parameter")
            or self._symbol_has_role(_handle_name(candidate[0]), "moving_point_parameter")
        ]
        if len(role_candidates) == 1:
            return role_candidates[0]
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            raise StrategyDraftValidationError("dynamic_parameter_symbol_not_found")
        raise StrategyDraftValidationError(
            "dynamic_parameter_symbol_ambiguous: "
            + ",".join(symbol for symbol, _constraint in candidates)
        )

    def _register_initial_handles(self) -> None:
        """注册题设已有 Entity/Fact/answer。"""
        for handle in sorted(self.handle_registry.entity_handles):
            self._register_entity_handle(handle)
        for handle in sorted(self.handle_registry.fact_handles):
            self._register_fact_handle(handle)
        for handle, goal in self.question_goals.items():
            self.register(handle, goal.target_path, goal.value_type, source="question_goal")
            if goal.value_type == "Point":
                self._register_answer_point_entity(handle, goal)

    def _register_entity_handle(self, handle: str) -> None:
        kind, scope_id, _local_id = _require_scoped_handle(handle)
        payload = self.entity_payload(handle)
        name = str(payload.get("name", "")).strip() or _local_id
        if kind == "point":
            path = self.context.find_visible_path("points", name, from_scope_id=scope_id)
            if path is None:
                path = _runtime_path_for_scope(self.context, scope_id, "points", name)
                value_type = "PointRef"
            else:
                parsed = ContextPath.parse(path)
                value_type = self.context.get_scope(parsed.scope_id).container(parsed.container)[parsed.key].type
                if value_type == "PointRef" and parsed.scope_id == "problem":
                    try:
                        self.context.read_path(path, from_scope_id=scope_id, expected_type="Point")
                        value_type = "Point"
                    except Exception:
                        pass
            self.register(handle, path, value_type, source="entity")
        elif kind == "symbol":
            path = self.context.find_visible_path("symbols", name, from_scope_id=scope_id)
            if path is not None:
                self.register(handle, path, "Symbol", source="entity")
        elif kind == "function" and str(payload.get("function_type", "")) == "quadratic":
            self.register(handle, "$problem.expressions.quadratic", "Expression", source="entity")

    def _register_fact_handle(self, handle: str) -> None:
        fact_type = self.fact_types.get(handle)
        scope_id = _handle_scope(handle)
        name = _semantic_name(handle)
        scope = self.context.get_scope(scope_id)
        canonical_condition = scope.container("conditions").get(name)
        if (
            self.problem_binding_authority
            and canonical_condition is not None
            and name != fact_type
        ):
            self.register(
                handle,
                _runtime_path_for_scope(
                    self.context,
                    scope_id,
                    "conditions",
                    name,
                ),
                canonical_condition.type,
                source="fact",
            )
            return
        if fact_type == "coefficient_relation":
            self.register(handle, "$problem.equations.coefficient_relation", "Equation", source="fact")
        elif fact_type == "symbol_constraint":
            payload = self.fact_payload(handle)
            symbol_handle = str(payload.get("subject", "")).strip()
            if not symbol_handle.startswith("symbol:") or symbol_handle not in self.bindings:
                raise StrategyDraftValidationError(
                    "symbol_constraint_subject_not_found: "
                    f"fact={handle}, subject={symbol_handle!r}"
                )
            symbol = self.entity_semantic_name(symbol_handle)
            self.register(handle, f"$problem.constraints.{symbol}", "Constraint", source="fact")
        elif fact_type == "path_minimum_target":
            self.register(handle, "$problem.conditions.path_minimum", "Condition", source="fact")
        elif fact_type == "segment_membership":
            point = _segment_membership_point(name)
            self.register(handle, f"$problem.conditions.segment_membership_{point}", "Condition", source="fact")
        elif fact_type == "segment_relation":
            left, right = _segment_relation_names(name)
            self.register(handle, f"$problem.conditions.segment_relation_{left}_{right}", "Condition", source="fact")
        elif fact_type == "orientation_constraint":
            payload = self.fact_payload(handle)
            point_handle = str(payload.get("subject", "")).strip()
            if not point_handle.startswith("point:") or point_handle not in self.bindings:
                raise StrategyDraftValidationError(
                    "orientation_subject_point_not_found: "
                    f"fact={handle}, subject={point_handle!r}"
                )
            point = self.entity_semantic_name(point_handle)
            point_scope = _binding_scope(self.binding_for(point_handle).path)
            self.register(
                handle,
                _runtime_path_for_scope(
                    self.context,
                    point_scope,
                    "constraints",
                    f"{point}_quadrant",
                ),
                "OrientationHint",
                source="fact",
            )
        elif fact_type == "length_squared":
            self.register(handle, _runtime_path_for_scope(self.context, scope_id, "conditions", "length_squared"), "Condition", source="fact")
        elif fact_type == "segment_length_relation":
            self.register(handle, _runtime_path_for_scope(self.context, scope_id, "conditions", "segment_length_relation"), "Condition", source="fact")
        elif fact_type == "minimum_value":
            self.register(handle, _runtime_path_for_scope(self.context, scope_id, "conditions", "minimum_value"), "Condition", source="fact")
        elif fact_type in {
            "angle_sum",
            "equal_length_ray_point",
            "point_on_segment",
            "point_on_ray",
            "equal_length_condition",
            "axis_membership",
            "point_on_curve",
            "square",
            "square_center",
            "midpoint_definition",
        }:
            self.register(handle, _runtime_path_for_scope(self.context, scope_id, "conditions", fact_type), "Condition", source="fact")
        elif fact_type == "point_coordinate":
            payload = self.fact_payload(handle)
            point_handle = str(payload.get("subject", "")).strip()
            if not point_handle.startswith("point:") or point_handle not in self.bindings:
                raise StrategyDraftValidationError(
                    "point_coordinate_subject_not_found: "
                    f"fact={handle}, subject={point_handle!r}"
                )
            point_name = self.entity_semantic_name(point_handle)
            path = _runtime_path_for_scope(
                self.context,
                scope_id,
                "points",
                point_name,
            )
            self.register(handle, path, "Point", source="fact")
        elif fact_type == "symbol_value":
            self._register_symbol_value_fact(handle, scope_id=scope_id)

    def _register_symbol_value_fact(self, handle: str, *, scope_id: str) -> None:
        """Expose one stated Symbol value without losing its aggregate view.

        ``coefficients.known`` remains the source for a ``Coefficients``
        aggregate input.  A semantic ref such as ``b_value`` denotes one
        Symbol state, however, so direct ``ParameterValue`` args need a scalar
        ContextPath instead of being pointed at the whole mapping.
        """
        payload = self.fact_payload(handle)
        subject = str(payload.get("subject", "")).strip()
        symbol_name = self.entity_semantic_name(subject) if subject else ""
        scope = self.context.get_scope(scope_id)
        known = scope.container("coefficients").get("known")
        value: Any | None = None
        symbol = self.context.symbols.get(symbol_name)
        if (
            known is not None
            and isinstance(known.value, Mapping)
            and symbol is not None
        ):
            value = known.value.get(symbol)
        if value is None and payload.get("value") is not None:
            value = self.context.kernel.expr(
                str(payload["value"]),
                self.context.symbols,
            )
        if value is None or not symbol_name:
            # Some schema/classification callers intentionally provide only a
            # fact type. Keep the historical aggregate view available there;
            # an executable Functional scalar read will later surface the
            # reconciled/runtime type drift as a configuration error.
            self.register(
                handle,
                _runtime_path_for_scope(
                    self.context,
                    scope_id,
                    "coefficients",
                    "known",
                ),
                "Coefficients",
                source="fact",
            )
            return
        scope.container("parameter_values")[symbol_name] = TypedValue(
            "ParameterValue",
            value,
            locked=True,
            source=f"fact:{handle}",
        )
        self.register(
            handle,
            _runtime_path_for_scope(
                self.context,
                scope_id,
                "parameter_values",
                symbol_name,
            ),
            "ParameterValue",
            source="fact",
        )

    def _register_answer_point_entity(self, answer_handle: str, goal: QuestionGoal) -> None:
        """若 answer 指向某个点，同时把同名 point entity 绑定到该 target path。"""
        parsed = ContextPath.parse(goal.target_path)
        if parsed.container != "points":
            return
        point_handle = f"point:{parsed.scope_id}:{parsed.key}"
        if point_handle in self.handle_registry.entity_handles:
            self.register(point_handle, goal.target_path, "PointRef", source="question_goal")

def _runtime_path_for_scope(
    context: RuntimeContext,
    scope_id: str,
    container: str,
    key: str,
) -> str:
    """按 RuntimeContext scope 类型生成 ContextPath。"""
    scope = context.get_scope(scope_id)
    if scope.scope_type == "problem":
        return f"$problem.{container}.{key}"
    if scope.scope_type == "question":
        return f"$question.{scope_id}.{container}.{key}"
    if scope.scope_type == "subquestion":
        return f"$subquestion.{scope_id}.{container}.{key}"
    if scope.scope_type == "step":
        return f"$step.{scope_id}.{container}.{key}"
    raise StrategyDraftValidationError(f"unknown_runtime_scope_type: {scope.scope_type}")

def _symbol_from_constraint_handle(handle: str) -> str:
    """从 ``fact:<scope>:m_gt_2`` 这类约束 handle 中读取符号名。"""
    return _semantic_name(handle).split("_", 1)[0]

def _context_path_exists(context: RuntimeContext, raw_path: str) -> bool:
    """判断某个 ContextPath 当前是否存在。"""
    try:
        path = ContextPath.parse(raw_path)
        return path.key in context.get_scope(path.scope_id).container(path.container)
    except Exception:
        return False

def _binding_scope(raw_path: str) -> str:
    """读取 runtime path 所在 scope。"""
    return ContextPath.parse(raw_path).scope_id

def _point_declaration_for_path(
    context: RuntimeContext,
    raw_path: str,
    *,
    definition: str,
) -> ContextDeclaration:
    """为任意 question/subquestion/problem scope 创建 PointRef declaration。"""
    path = ContextPath.parse(raw_path)
    if path.container != "points":
        raise StrategyDraftValidationError(f"point_declaration_requires_point_path: {raw_path}")
    return ContextDeclaration(
        path=raw_path,
        type="PointRef",
        name=path.key,
        definition={"definition": definition},
        scope_id=path.scope_id,
    )

def _segment_membership_point(name: str) -> str:
    """解析 ``segment_<point>_on_<segment>`` 的动点名。"""
    match = re.fullmatch(r"segment_(?P<point>[A-Za-z0-9_]+)_on_(?P<segment>[A-Za-z0-9_]+)", name)
    if match is None:
        raise StrategyDraftValidationError(f"invalid_segment_membership_name: {name}")
    return match.group("point")

def _segment_relation_names(name: str) -> tuple[str, str]:
    """解析 ``segment_DE_eq_sqrt2_NG`` 的两个线段名。"""
    match = re.fullmatch(
        r"segment_(?P<left>[A-Za-z0-9_]+)_eq_(?:[A-Za-z0-9]+_)?(?P<right>[A-Za-z0-9_]+)",
        name,
    )
    if match is None:
        raise StrategyDraftValidationError(f"invalid_segment_relation_name: {name}")
    return match.group("left"), match.group("right")
