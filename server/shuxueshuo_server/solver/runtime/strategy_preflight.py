"""StepIntent 执行前全量结构诊断。

Preflight 不执行 method，也不改变 draft。它只基于 canonical handle graph
和 family capability contract 发现“后续很可能会遇到的同源问题”，用于补足
prefix dry-run 只返回首个 blocker 的盲区。
"""

from __future__ import annotations

from shuxueshuo_server.solver.family.models import (
    CapabilityContractSpec,
    MethodBindingRuleSpec,
    SolverFamilySpec,
)
from shuxueshuo_server.solver.runtime.capability_contracts import explicit_contract_by_id
from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
from shuxueshuo_server.solver.runtime.strategy_models import (
    StepIntent,
    StepIntentDraft,
    StepIntentPreflightIssue,
)


class StepIntentPreflightAnalyzer:
    """对完整 effective draft 做非阻断式结构扫描。"""

    def analyze(
        self,
        draft: StepIntentDraft,
        *,
        family_spec: SolverFamilySpec,
        handle_registry: CanonicalHandleRegistry,
    ) -> tuple[StepIntentPreflightIssue, ...]:
        """返回完整 draft 的 preflight warnings。"""
        method_rules = {rule.method_id: rule for rule in family_spec.method_binding_rules}
        contracts = explicit_contract_by_id(family_spec)
        recipe_methods = {
            recipe.recipe_id: tuple(recipe.method_ids)
            for recipe in family_spec.step_recipes
        }
        readable_parabolas: list[tuple[str, str]] = []
        issues: list[StepIntentPreflightIssue] = []
        for step in draft.steps:
            if _step_needs_parabola(step, method_rules, recipe_methods, contracts):
                if (
                    not _has_readable_parabola(step, readable_parabolas, handle_registry)
                    and _has_quadratic_source_reads(step, handle_registry)
                ):
                    issues.append(
                        _missing_parabola_issue(
                            step,
                            code_fillable=_all_parabola_methods_have_prep(
                                step,
                                method_rules,
                                recipe_methods,
                                contracts,
                            ),
                        )
                    )
            for produced in step.produces:
                if produced.output_type == "Parabola" or _is_parabola_handle(
                    produced.handle,
                    handle_registry,
                ):
                    readable_parabolas.append((produced.handle, produced.valid_scope))
        return tuple(issues)


def _step_needs_parabola(
    step: StepIntent,
    method_rules: dict[str, MethodBindingRuleSpec],
    recipe_methods: dict[str, tuple[str, ...]],
    contracts: dict[str, CapabilityContractSpec],
) -> bool:
    """判断 step 的 hint 对应能力是否需要 Parabola 输入。"""
    if step.recipe_hint and _contract_needs_parabola(contracts.get(step.recipe_hint)):
        return True
    return any(
        _method_needs_parabola(method_id, method_rules, contracts)
        for method_id in _capability_method_ids(step, recipe_methods)
    )


def _all_parabola_methods_have_prep(
    step: StepIntent,
    method_rules: dict[str, MethodBindingRuleSpec],
    recipe_methods: dict[str, tuple[str, ...]],
    contracts: dict[str, CapabilityContractSpec],
) -> bool:
    """判断相关 Parabola method 是否都具备 missing Parabola prep。"""
    method_ids = [
        method_id
        for method_id in _capability_method_ids(step, recipe_methods)
        if _method_needs_parabola(method_id, method_rules, contracts)
    ]
    return bool(method_ids) and all(
        _method_has_missing_parabola_prep(method_id, method_rules)
        for method_id in method_ids
    )


def _capability_method_ids(
    step: StepIntent,
    recipe_methods: dict[str, tuple[str, ...]],
) -> tuple[str, ...]:
    """从 recipe_hint 反推出 method ids；空 hint 不做猜测。"""
    if not step.recipe_hint:
        return ()
    if step.recipe_hint in recipe_methods:
        return recipe_methods[step.recipe_hint]
    return (step.recipe_hint,)


def _method_needs_parabola(
    method_id: str,
    method_rules: dict[str, MethodBindingRuleSpec],
    contracts: dict[str, CapabilityContractSpec],
) -> bool:
    """method binding rule 是否声明了 read_type:Parabola 输入。"""
    if _contract_needs_parabola(contracts.get(method_id)):
        return True
    rule = method_rules.get(method_id)
    if rule is None:
        return False
    return any(binding.selector == "read_type:Parabola" for binding in rule.input_bindings)


def _contract_needs_parabola(contract: CapabilityContractSpec | None) -> bool:
    """Capability contract 是否声明需要 Parabola state。"""
    if contract is None:
        return False
    return any(slot.runtime_type == "Parabola" for slot in contract.slot_reads)


def _method_has_missing_parabola_prep(
    method_id: str,
    method_rules: dict[str, MethodBindingRuleSpec],
) -> bool:
    """method binding rule 是否声明了缺 Parabola 时的 prep。"""
    rule = method_rules.get(method_id)
    if rule is None:
        return False
    return any(
        prep.trigger_selector in {
            "missing_readable_type:Parabola",
            "missing_readable_type_with_quadratic_source:Parabola",
        }
        and _prep_exposes_output_type(prep.local_output_aliases, "Parabola")
        for prep in rule.prep_invocations
    )


def _prep_exposes_output_type(
    local_output_aliases: tuple[tuple[str, str], ...],
    value_type: str,
) -> bool:
    """prep 是否通过 local alias 暴露指定 runtime 类型。"""
    return any(alias == f"type:{value_type}" for alias, _output_name in local_output_aliases)


def _has_readable_parabola(
    step: StepIntent,
    produced_parabolas: list[tuple[str, str]],
    handle_registry: CanonicalHandleRegistry,
) -> bool:
    """step 是否显式读取或已可见一个 Parabola。"""
    if any(_is_parabola_handle(handle, handle_registry) for handle in step.reads):
        return True
    visible_scopes = set(handle_registry.ancestor_scopes(step.scope_id))
    return any(scope in visible_scopes for _handle, scope in produced_parabolas)


def _is_parabola_handle(
    handle: str,
    handle_registry: CanonicalHandleRegistry,
) -> bool:
    """判断 handle 是否结构化表示 Parabola。"""
    if handle_registry.answer_value_types.get(handle) == "Parabola":
        return True
    if handle_registry.fact_types.get(handle) == "parabola":
        return True
    if not handle.startswith("fact:"):
        return False
    semantic_name = handle.rsplit(":", 1)[-1]
    return semantic_name in {"parabola", "parabola_expression", "parabola_expr"}


def _has_quadratic_source_reads(
    step: StepIntent,
    handle_registry: CanonicalHandleRegistry,
) -> bool:
    """step 是否读取了题设函数和足以尝试构造抛物线的结构 fact。"""
    has_function = any(handle.startswith("function:") for handle in step.reads)
    if not has_function:
        return False
    source_fact_types = {
        "symbol_value",
        "coefficient_relation",
        "point_on_curve",
        "point_coordinate",
    }
    return any(handle_registry.fact_types.get(handle) in source_fact_types for handle in step.reads)


def _missing_parabola_issue(
    step: StepIntent,
    *,
    code_fillable: bool,
) -> StepIntentPreflightIssue:
    """构造缺 Parabola 状态的 preflight issue。"""
    category = "code_fillable" if code_fillable else "likely_downstream_issue"
    return StepIntentPreflightIssue(
        step_id=step.step_id,
        scope_id=step.scope_id,
        category=category,
        code="missing_explicit_parabola_state",
        message=(
            f"step {step.step_id} needs a Parabola input but reads the original "
            "function plus coefficient/constraint facts instead of a solved "
            "parabola handle."
        ),
        repair=(
            "Prefer producing a reusable fact:<scope>:parabola_expression with "
            "quadratic_from_constraints, then read that handle from later vertex, "
            "axis, intercept, and curve-condition steps."
        ),
    )


__all__ = ["StepIntentPreflightAnalyzer"]
