"""Capability-owned, prompt-safe enhancements for Functional retry issues."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Mapping, Protocol, Sequence

from shuxueshuo_server.solver.runtime.strategy_models import PlannerRetryIssue
from shuxueshuo_server.solver.utils import unique_ordered

if TYPE_CHECKING:
    from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
        FunctionalCapabilityCatalog,
    )


@dataclass(frozen=True)
class CapabilityRepairFeedbackContext:
    capability_id: str
    capability_kind: str
    issue: PlannerRetryIssue
    evidence_evaluation: Mapping[str, Any] | None = None
    compatible_refs: tuple[str, ...] = ()
    dependency_call_ids: tuple[str, ...] = ()
    repair_call_ids: tuple[str, ...] = ()
    locked_call_ids: tuple[str, ...] = ()
    actual_result_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class CapabilityRepairFeedbackContribution:
    explanation: str = ""
    expected: Mapping[str, Any] | None = None
    actual: Mapping[str, Any] | None = None
    hints: tuple[str, ...] = ()
    do_not: tuple[str, ...] = ()
    compatible_refs: tuple[str, ...] = ()
    additional_repair_call_ids: tuple[str, ...] = ()


class CapabilityRepairFeedbackProvider(Protocol):
    def build(
        self,
        context: CapabilityRepairFeedbackContext,
    ) -> CapabilityRepairFeedbackContribution | None: ...


class CapabilityRepairFeedbackProviderError(ValueError):
    """A capability references or executes an invalid feedback provider."""

    code = "planner.repair_feedback_provider_failed"


class LineIntersectionEvidenceFeedbackProvider:
    """Explain a failed declared evidence closure without choosing a route."""

    def build(
        self,
        context: CapabilityRepairFeedbackContext,
    ) -> CapabilityRepairFeedbackContribution | None:
        if context.issue.code != "functional.evidence_closure_unproven":
            return None
        gap = context.evidence_evaluation or {}
        missing = {
            "semantic_roles": _strings(gap.get("missing_roles")),
            "evidence_tags": _strings(gap.get("missing_evidence_tags")),
            "object_roles": _strings(gap.get("missing_object_roles")),
        }
        matched = tuple(
            (
                str(item.get("role"))
                if isinstance(item, Mapping)
                else str(item)
            )
            for item in gap.get("matched_roles", ())
            if (
                (isinstance(item, Mapping) and item.get("role"))
                or isinstance(item, str)
            )
        )
        return CapabilityRepairFeedbackContribution(
            explanation=(
                "交点计算本身可能可执行，但答案需要的结构化证据链尚未闭合。"
            ),
            expected={
                key: list(value)
                for key, value in missing.items()
                if value
            },
            actual={"matched_roles": list(unique_ordered(matched))},
            hints=(
                "让同一 witness 声明的成对端点分别进入对应直线；已有对象仅在 MathObject 身份唯一匹配时可复用。",
                "轨迹端点、目标对象和 witness 的 moving object 必须保持同一对象身份链。",
            ),
            do_not=(
                "不要用只有固定点、中点等其他角色的对象替代尚未证明的 witness 端点。",
                "不要用旁路计算代替答案 producer 自身的证据依赖。",
            ),
            compatible_refs=context.compatible_refs,
            additional_repair_call_ids=context.repair_call_ids,
        )


class ExpressionStateTransitionFeedbackProvider:
    """Explain expression substitution and state-version conflicts."""

    def build(
        self,
        context: CapabilityRepairFeedbackContext,
    ) -> CapabilityRepairFeedbackContribution | None:
        details = (
            context.issue.details
            if isinstance(context.issue.details, Mapping)
            else {}
        )
        error_code = details.get("error_code") or context.issue.code
        if error_code == "function.transition_previous_write_mismatch":
            value_type = details.get("state_value_type") or "value"
            expected_call = details.get("expected_previous_call_id")
            actual_call = details.get("actual_previous_call_id")
            consumer_call = details.get("consumer_call_id")
            return CapabilityRepairFeedbackContribution(
                explanation=(
                    f"当前存在两条互不一致的同一 {value_type} 状态链。"
                    "冲突调用必须继续其中一个可证明的状态版本，或删除、替换"
                    "未提交的分支。"
                ),
                expected={
                    "previous_call": expected_call,
                    "consumer_call": consumer_call,
                },
                actual={"previous_call": actual_call},
                hints=(
                    "可以删除、替换或重新连接所有未锁定调用，使同一对象只保留一条连续状态链。",
                    "已锁定的上游状态可作为上下文继续引用，不需要重新计算。",
                ),
                do_not=(
                    "不要让同一对象的两个互不依赖状态同时充当当前版本。",
                ),
                additional_repair_call_ids=context.repair_call_ids,
            )
        if error_code == "functional.duplicate_state_writer":
            previous_call = details.get("previous_writer_call_id")
            current_call = details.get("current_writer_call_id")
            return CapabilityRepairFeedbackContribution(
                explanation=(
                    "两个未证明前后依赖关系的调用正在写入同一对象状态。"
                    "它们必须形成明确的状态细化链，或只保留一条仍被答案图消费的分支。"
                ),
                expected={
                    "relationship": "single_writer_or_proven_transition"
                },
                actual={
                    "previous_writer": previous_call,
                    "current_writer": current_call,
                },
                hints=(
                    "若新调用是在旧状态上追加约束，请显式读取旧调用结果；否则删除或替换不再使用的分支。",
                ),
                do_not=(
                    "不要让两个互不依赖的调用同时创建同一对象的当前状态。",
                ),
                additional_repair_call_ids=context.repair_call_ids,
            )
        if error_code == "function.substitution_symbol_mismatch":
            free_symbols = _strings(details.get("free_symbol_names"))
            parameter_name = details.get("parameter_name")
            return CapabilityRepairFeedbackContribution(
                explanation=(
                    "当前 ParameterValue 的 Symbol 身份不属于输入表达式的"
                    "自由符号集合，因此该代入不能改变或关闭表达式状态。"
                ),
                expected={"free_symbols": list(free_symbols)},
                actual={"parameter": parameter_name},
                hints=(
                    "选择与表达式自由 Symbol 身份一致的 ParameterValue，或删除这次无效代入。",
                ),
                do_not=(
                    "不要因为某个参数值当前可见，就把它代入不依赖该参数的表达式。",
                ),
                compatible_refs=context.compatible_refs,
                additional_repair_call_ids=context.repair_call_ids,
            )
        return None


class CapabilityRepairFeedbackRegistry:
    """Closed registry for capability-declared dynamic feedback providers."""

    def __init__(
        self,
        providers: Mapping[str, CapabilityRepairFeedbackProvider],
    ) -> None:
        self._providers = dict(providers)

    @classmethod
    def default(cls) -> "CapabilityRepairFeedbackRegistry":
        return cls(
            {
                "line_intersection_evidence": (
                    LineIntersectionEvidenceFeedbackProvider()
                ),
                "expression_state_transition": (
                    ExpressionStateTransitionFeedbackProvider()
                ),
            }
        )

    def require(self, provider_id: str) -> CapabilityRepairFeedbackProvider:
        provider = self._providers.get(provider_id)
        if provider is None:
            raise CapabilityRepairFeedbackProviderError(
                f"{self.code}: unknown provider {provider_id}"
            )
        return provider

    @property
    def code(self) -> str:
        return CapabilityRepairFeedbackProviderError.code


def validate_capability_repair_feedback_provider_ids(
    provider_ids: Sequence[str | None],
) -> None:
    registry = CapabilityRepairFeedbackRegistry.default()
    for provider_id in unique_ordered(
        item for item in provider_ids if item is not None
    ):
        registry.require(provider_id)


def apply_capability_repair_feedback(
    issues: tuple[PlannerRetryIssue, ...],
    *,
    plan: Any,
    reconciliation: Any,
    catalog: "FunctionalCapabilityCatalog",
    locked_call_ids: Sequence[str],
) -> tuple[PlannerRetryIssue, ...]:
    """Attach bounded feedback contributions without changing issue authority."""

    registry = CapabilityRepairFeedbackRegistry.default()
    calls = {call.call_id: call for call in plan.calls}
    dependencies = {
        call_id: tuple(values)
        for call_id, values in reconciliation.dependency_graph.items()
    }
    locked = tuple(unique_ordered(locked_call_ids))
    result: list[PlannerRetryIssue] = []
    for issue in issues:
        call = calls.get(issue.step_id or "")
        capability = (
            catalog.get(call.capability_id) if call is not None else None
        )
        provider_id = (
            getattr(capability.source, "repair_feedback_provider_id", None)
            if capability is not None
            else None
        )
        if not provider_id:
            result.append(issue)
            continue
        details = dict(issue.details or {})
        context = CapabilityRepairFeedbackContext(
            capability_id=capability.capability_id,
            capability_kind=capability.kind,
            issue=issue,
            evidence_evaluation=(
                details.get("evidence_gap")
                if isinstance(details.get("evidence_gap"), Mapping)
                else None
            ),
            compatible_refs=_strings(details.get("compatible_refs"))[:4],
            dependency_call_ids=dependencies.get(call.call_id, ()),
            repair_call_ids=_strings(details.get("repair_call_ids")),
            locked_call_ids=locked,
            actual_result_refs=_strings(details.get("actual_result_refs")),
        )
        try:
            contribution = registry.require(provider_id).build(context)
            if contribution is None:
                result.append(issue)
                continue
            feedback = _validated_feedback(
                contribution,
                known_call_ids=set(calls),
                locked_call_ids=set(locked),
                allowed_compatible_refs=set(context.compatible_refs),
                allowed_repair_call_ids={
                    *context.repair_call_ids,
                    *context.dependency_call_ids,
                },
            )
        except CapabilityRepairFeedbackProviderError:
            raise
        except Exception as exc:
            raise CapabilityRepairFeedbackProviderError(
                f"{CapabilityRepairFeedbackProviderError.code}: "
                f"{provider_id}: {exc}"
            ) from exc
        details["repair_feedback"] = feedback
        additional = _strings(feedback.get("additional_repair_call_ids"))
        requested_repairs = unique_ordered(
            (
                *_strings(details.get("repair_call_ids")),
                *additional,
            )
        )
        locked_set = set(locked)
        locked_context = unique_ordered(
            (
                *(
                    call_id
                    for call_id in _strings(
                        details.get("locked_context_call_ids")
                    )
                    if call_id in locked_set
                ),
                *(
                    ref.rsplit(".", 1)[0]
                    for ref in _strings(details.get("locked_result_refs"))
                    if "." in ref
                    and ref.rsplit(".", 1)[0] in locked_set
                ),
                *(
                    call_id
                    for call_id in _strings(details.get("context_call_ids"))
                    if call_id in locked_set
                ),
                *(
                    call_id
                    for call_id in requested_repairs
                    if call_id in locked_set
                ),
                *(
                    ref.rsplit(".", 1)[0]
                    for ref in context.compatible_refs
                    if "." in ref
                    and ref.rsplit(".", 1)[0] in locked_set
                ),
            )
        )
        details["repair_call_ids"] = list(
            call_id
            for call_id in requested_repairs
            if call_id not in locked_set
        )
        if locked_context:
            details["locked_context_call_ids"] = list(locked_context)
        result.append(
            replace(
                issue,
                hints=tuple(
                    unique_ordered((*issue.hints, *_strings(feedback.get("hints"))))
                )[:2],
                details=details,
            )
        )
    return tuple(result)


def _validated_feedback(
    contribution: CapabilityRepairFeedbackContribution,
    *,
    known_call_ids: set[str],
    locked_call_ids: set[str],
    allowed_compatible_refs: set[str] | None = None,
    allowed_repair_call_ids: set[str] | None = None,
) -> dict[str, Any]:
    refs = tuple(
        ref
        for ref in unique_ordered(contribution.compatible_refs)
        if _is_public_result_ref(ref, known_call_ids)
        and (
            allowed_compatible_refs is None
            or ref in allowed_compatible_refs
        )
    )[:4]
    repair_ids = tuple(
        call_id
        for call_id in unique_ordered(
            contribution.additional_repair_call_ids
        )
        if call_id in known_call_ids
        and call_id not in locked_call_ids
        and (
            allowed_repair_call_ids is None
            or call_id in allowed_repair_call_ids
        )
    )
    payload: dict[str, Any] = {}
    if contribution.explanation.strip():
        payload["explanation"] = contribution.explanation.strip()
    if contribution.expected:
        payload["expected"] = dict(contribution.expected)
    if contribution.actual:
        payload["actual"] = dict(contribution.actual)
    hints = unique_ordered(item.strip() for item in contribution.hints if item.strip())
    do_not = unique_ordered(
        item.strip() for item in contribution.do_not if item.strip()
    )
    if hints:
        payload["hints"] = list(hints[:2])
    if do_not:
        payload["do_not"] = list(do_not[:2])
    if refs:
        payload["compatible_refs"] = list(refs)
    if repair_ids:
        payload["additional_repair_call_ids"] = list(repair_ids)
    _reject_internal_feedback(payload)
    return payload


def _is_public_result_ref(ref: str, known_call_ids: set[str]) -> bool:
    if "." not in ref:
        return False
    call_id, return_name = ref.rsplit(".", 1)
    return bool(return_name) and call_id in known_call_ids


def _reject_internal_feedback(payload: Mapping[str, Any]) -> None:
    text = repr(payload)
    forbidden = ("StateSlot", "runtime_path", "$question.", "expected_answer")
    if any(item in text for item in forbidden):
        raise CapabilityRepairFeedbackProviderError(
            f"{CapabilityRepairFeedbackProviderError.code}: "
            "provider returned internal or answer data"
        )


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)


__all__ = [
    "CapabilityRepairFeedbackContext",
    "CapabilityRepairFeedbackContribution",
    "CapabilityRepairFeedbackProvider",
    "CapabilityRepairFeedbackProviderError",
    "CapabilityRepairFeedbackRegistry",
    "ExpressionStateTransitionFeedbackProvider",
    "LineIntersectionEvidenceFeedbackProvider",
    "apply_capability_repair_feedback",
    "validate_capability_repair_feedback_provider_ids",
]
