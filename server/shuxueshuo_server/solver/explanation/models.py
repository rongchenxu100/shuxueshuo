"""ExplanationBuilder 的轻量数据模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterator, Mapping


EXPLANATION_SNAPSHOT_CONTRACT = "explanation-snapshot/v2"


@dataclass(frozen=True)
class TeachingTraceEntry:
    """一次 method invocation 的讲解级 trace。

    这里刻意不暴露 ContextPath。输入输出只保留槽位名，具体值通过 fact_index 或
    Lesson step 的已绑定文本展示。
    """

    trace_id: str
    source_step_id: str
    scope_id: str
    capability_id: str
    method_id: str
    input_slots: tuple[str, ...] = ()
    output_slots: tuple[str, ...] = ()
    checks: tuple[str, ...] = ()
    trace_fragments: tuple[dict[str, Any], ...] = ()
    hidden_reason: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["input_slots"] = list(self.input_slots)
        payload["output_slots"] = list(self.output_slots)
        payload["checks"] = list(self.checks)
        payload["trace_fragments"] = list(self.trace_fragments)
        return payload


@dataclass(frozen=True)
class SymbolicClosureTeachingTrace:
    """Student-safe projection of one committed runtime closure."""

    source_call_id: str
    target: str
    target_value: str | None
    equation_sources: tuple[str, ...] = ()
    known_substitutions: tuple[tuple[str, str], ...] = ()
    constraint_summary: str | None = None
    branch_count: int = 0
    residual_symbols: tuple[str, ...] = ()
    affected_returns: tuple[str, ...] = ()
    state_updates: tuple[dict[str, Any], ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "source_call_id": self.source_call_id,
            "target": self.target,
            "target_value": self.target_value,
            "equation_sources": list(self.equation_sources),
            "known_substitutions": [
                {"symbol": symbol, "value": value}
                for symbol, value in self.known_substitutions
            ],
            "constraint_summary": self.constraint_summary,
            "branch_count": self.branch_count,
            "residual_symbols": list(self.residual_symbols),
            "affected_returns": list(self.affected_returns),
            "state_updates": [dict(item) for item in self.state_updates],
        }


@dataclass(frozen=True)
class TeachingSource:
    """One verified Functional step, nested in its sole canonical owner."""

    source_step_id: str
    capability_id: str
    args: Mapping[str, Any]
    public_results: Mapping[str, Mapping[str, Any]]
    output_targets: Mapping[str, str] = field(default_factory=dict)
    return_expectations: Mapping[str, str] = field(default_factory=dict)
    intent: str | None = None
    checks: tuple[Mapping[str, Any], ...] = ()
    evidence_refs: tuple[str, ...] = ()
    closure_refs: tuple[str, ...] = ()

    def authored_step_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "step_id": self.source_step_id,
            "capability_id": self.capability_id,
            "args": _thaw(self.args),
        }
        if self.output_targets:
            payload["output_targets"] = dict(self.output_targets)
        if self.return_expectations:
            payload["return_expectations"] = dict(self.return_expectations)
        if self.intent:
            payload["intent"] = self.intent
        return payload

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "source_step_id": self.source_step_id,
            "capability_id": self.capability_id,
            "args": _thaw(self.args),
            "output_targets": dict(self.output_targets),
            "return_expectations": dict(self.return_expectations),
            "public_results": {
                name: _thaw(result)
                for name, result in self.public_results.items()
            },
            "checks": [_thaw(item) for item in self.checks],
            "evidence_refs": list(self.evidence_refs),
            "closure_refs": list(self.closure_refs),
        }
        if self.intent:
            payload["intent"] = self.intent
        return payload


@dataclass(frozen=True)
class TeachingGoal:
    """Canonical Goal body; its containing TeachingScope is the owner."""

    goal_ref: str
    steps: tuple[TeachingSource, ...]
    answer_from: Mapping[str, str]

    def to_payload(self) -> dict[str, Any]:
        return {
            "steps": [item.to_payload() for item in self.steps],
            "answer_from": dict(self.answer_from),
        }


@dataclass(frozen=True)
class TeachingScope:
    """Recursive, owner-preserving projection of one Canonical Plan Scope."""

    scope_ref: str
    scope_steps: tuple[TeachingSource, ...] = ()
    goals: tuple[TeachingGoal, ...] = ()
    children: tuple["TeachingScope", ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "scope_ref": self.scope_ref,
            "scope_steps": [item.to_payload() for item in self.scope_steps],
            "goals": {
                goal.goal_ref: goal.to_payload()
                for goal in self.goals
            },
            "children": [item.to_payload() for item in self.children],
        }


@dataclass(frozen=True)
class TeachingCrossScopeReference:
    """A dependency edge; it never moves or copies the producer source."""

    source_step_id: str
    target_step_id: str
    source_scope_ref: str
    target_scope_ref: str
    public_result_ref: Mapping[str, str]

    @property
    def source_scope_id(self) -> str:
        """Temporary read-only spelling used by the flat LessonIR builder."""

        return self.source_scope_ref

    @property
    def target_scope_id(self) -> str:
        """Temporary read-only spelling used by the flat LessonIR builder."""

        return self.target_scope_ref

    @property
    def semantic_roles(self) -> tuple[str, ...]:
        return (str(self.public_result_ref.get("return") or "result"),)

    def to_payload(self) -> dict[str, Any]:
        return {
            "source_step_id": self.source_step_id,
            "target_step_id": self.target_step_id,
            "source_scope_ref": self.source_scope_ref,
            "target_scope_ref": self.target_scope_ref,
            "public_result_ref": dict(self.public_result_ref),
        }


@dataclass(frozen=True)
class ExplanationSnapshot:
    """The verified, canonical-owner fact boundary for every teaching layer."""

    problem_id: str
    family_id: str
    problem_revision: str
    problem_semantic_hash: str
    canonical_plan_hash: str
    verified_execution_hash: str
    problem: dict[str, Any]
    root_scope: TeachingScope
    cross_scope_references: tuple[TeachingCrossScopeReference, ...] = ()
    evidence: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    answers: dict[str, Any] = field(default_factory=dict)
    schema_version: str = EXPLANATION_SNAPSHOT_CONTRACT

    def __post_init__(self) -> None:
        _validate_explanation_snapshot(self)

    @property
    def effective_steps(self) -> tuple[dict[str, Any], ...]:
        """Derived flat compatibility index; never serialized as authority."""

        owners = teaching_source_owners(self.root_scope)
        answer_handles = _answer_handles_by_result(self.root_scope)
        primary_handles = _primary_result_handles(self.root_scope)
        result: list[dict[str, Any]] = []
        for source in iter_teaching_sources(self.root_scope):
            scope_ref, _ = owners[source.source_step_id]
            produced: list[dict[str, Any]] = []
            creates: list[dict[str, Any]] = []
            for return_name, runtime_result in source.public_results.items():
                handles = _result_handles(
                    source,
                    return_name,
                    scope_ref=scope_ref,
                    answer_handles=answer_handles,
                )
                runtime_type = str(runtime_result.get("runtime_type") or "Unknown")
                for handle in handles:
                    produced.append(
                        {
                            "handle": handle,
                            "valid_scope": scope_ref,
                            "description": (
                                f"{source.capability_id} return {return_name}"
                            ),
                            "output_type": runtime_type,
                        }
                    )
                target = source.output_targets.get(return_name)
                if target:
                    public_target = _problem_handle_for_source_ref(
                        target,
                        problem=self.problem,
                        scope_ref=scope_ref,
                    ) or handles[0]
                    creates.append(
                        {
                            "handle": public_target,
                            "entity_type": runtime_type,
                            "valid_scope": scope_ref,
                            "description": f"Verified result {target}",
                        }
                    )
            target = next(iter(source.output_targets.values()), None)
            if target is not None:
                target = _problem_handle_for_source_ref(
                    target,
                    problem=self.problem,
                    scope_ref=scope_ref,
                ) or target
            if target is None and produced:
                target = str(produced[0]["handle"])
            result.append(
                {
                    "scope_id": scope_ref,
                    "step_id": source.source_step_id,
                    "recipe_hint": source.capability_id,
                    "goal_type": source.capability_id,
                    "target": target or source.capability_id,
                    "strategy": "",
                    "reads": _derived_reads(
                        source.args,
                        primary_handles,
                        problem=self.problem,
                        scope_ref=scope_ref,
                    ),
                    "creates": creates,
                    "produces": produced,
                    "reason": source.intent or "",
                }
            )
        return tuple(result)

    @property
    def teaching_trace(self) -> tuple[TeachingTraceEntry, ...]:
        """One deterministic trace per verified atomic Functional step."""

        owners = teaching_source_owners(self.root_scope)
        return tuple(
            TeachingTraceEntry(
                trace_id=(
                    f"trace:{source.source_step_id}:0:{source.capability_id}"
                ),
                source_step_id=source.source_step_id,
                scope_id=owners[source.source_step_id][0],
                capability_id=source.capability_id,
                method_id=source.capability_id,
                input_slots=tuple(source.args),
                output_slots=tuple(source.public_results),
                checks=tuple(
                    str(item.get("name") or "verified_check")
                    for item in source.checks
                ),
                trace_fragments=tuple(
                    {
                        "return": return_name,
                        **_thaw(runtime_result),
                    }
                    for return_name, runtime_result in source.public_results.items()
                ),
            )
            for source in iter_teaching_sources(self.root_scope)
        )

    @property
    def fact_index(self) -> dict[str, dict[str, Any]]:
        """Derived verified-result/problem-fact index for pre-F5-F5B consumers."""

        owners = teaching_source_owners(self.root_scope)
        answer_handles = _answer_handles_by_result(self.root_scope)
        answer_names = {
            handle: handle.removeprefix("answer:").rsplit(".", 1)[-1]
            for handles in answer_handles.values()
            for handle in handles
        }
        index = _problem_fact_index(self.problem)
        for source in iter_teaching_sources(self.root_scope):
            scope_ref, _ = owners[source.source_step_id]
            for return_name, runtime_result in source.public_results.items():
                base_fact = {
                    "scope_id": scope_ref,
                    "type": str(runtime_result.get("runtime_type") or "Unknown"),
                    "value": _thaw(runtime_result.get("value")),
                    "description": f"{source.capability_id} return {return_name}",
                    "source_step_id": source.source_step_id,
                    "source": source.capability_id,
                    "authority": "verified_execution",
                    "name": source.output_targets.get(return_name, return_name),
                }
                for handle in _result_handles(
                    source,
                    return_name,
                    scope_ref=scope_ref,
                    answer_handles=answer_handles,
                ):
                    fact = dict(base_fact)
                    if handle in answer_names:
                        fact["name"] = answer_names[handle]
                    index[handle] = {"handle": handle, **fact}
                step_result_handle = (
                    f"step-result:{source.source_step_id}:{return_name}"
                )
                index[step_result_handle] = {
                    "handle": step_result_handle,
                    **base_fact,
                }
        _add_verified_evidence_facts(
            index,
            evidence=self.evidence,
            owners=owners,
        )
        return index

    @property
    def macro_evidence(self) -> tuple[dict[str, Any], ...]:
        ordered_refs = tuple(
            ref
            for source in iter_teaching_sources(self.root_scope)
            for ref in source.evidence_refs
        )
        return tuple(
            _thaw(self.evidence[ref])
            for ref in dict.fromkeys(ordered_refs)
            if self.evidence.get(ref, {}).get("macro_id")
        )

    @property
    def planner_insights(self) -> tuple[dict[str, Any], ...]:
        """Failed-attempt Planner insights are intentionally outside v2."""

        return ()

    @property
    def checks(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            _thaw(check)
            for source in iter_teaching_sources(self.root_scope)
            for check in source.checks
        )

    @property
    def symbolic_closures(self) -> tuple[SymbolicClosureTeachingTrace, ...]:
        """Closure teaching awaits a verified public evidence projector."""

        return ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "problem_id": self.problem_id,
            "family_id": self.family_id,
            "problem_revision": self.problem_revision,
            "problem_semantic_hash": self.problem_semantic_hash,
            "canonical_plan_hash": self.canonical_plan_hash,
            "verified_execution_hash": self.verified_execution_hash,
            "problem": _thaw(self.problem),
            "root_scope": self.root_scope.to_payload(),
            "cross_scope_references": [
                item.to_payload() for item in self.cross_scope_references
            ],
            "evidence": {
                key: _thaw(value) for key, value in self.evidence.items()
            },
            "answers": _thaw(self.answers),
        }


def iter_teaching_scopes(root: TeachingScope) -> Iterator[TeachingScope]:
    yield root
    for child in root.children:
        yield from iter_teaching_scopes(child)


def iter_teaching_sources(root: TeachingScope) -> Iterator[TeachingSource]:
    for scope in iter_teaching_scopes(root):
        yield from scope.scope_steps
        for goal in scope.goals:
            yield from goal.steps


def teaching_source_owners(
    root: TeachingScope,
) -> dict[str, tuple[str, str | None]]:
    result: dict[str, tuple[str, str | None]] = {}
    for scope in iter_teaching_scopes(root):
        for source in scope.scope_steps:
            result[source.source_step_id] = (scope.scope_ref, None)
        for goal in scope.goals:
            for source in goal.steps:
                result[source.source_step_id] = (scope.scope_ref, goal.goal_ref)
    return result


def canonical_plan_hash_for_teaching_scope(root: TeachingScope) -> str:
    from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
        ScopedFunctionalPlanValidator,
        scoped_functional_plan_id,
    )

    plan, report = ScopedFunctionalPlanValidator().validate_payload_with_report(
        _canonical_plan_payload(root)
    )
    if plan is None or not report.ok:
        issue = report.first_issue
        detail = issue.message if issue is not None else "invalid canonical projection"
        raise ValueError(f"invalid TeachingScope canonical projection: {detail}")
    return scoped_functional_plan_id(plan)


def explanation_snapshot_from_payload(payload: Mapping[str, Any]) -> ExplanationSnapshot:
    expected = {
        "schema_version",
        "problem_id",
        "family_id",
        "problem_revision",
        "problem_semantic_hash",
        "canonical_plan_hash",
        "verified_execution_hash",
        "problem",
        "root_scope",
        "cross_scope_references",
        "evidence",
        "answers",
    }
    if set(payload) != expected:
        raise ValueError("ExplanationSnapshot payload fields do not match v2 contract")
    references = payload["cross_scope_references"]
    evidence = payload["evidence"]
    if not isinstance(references, list) or not isinstance(evidence, Mapping):
        raise ValueError("ExplanationSnapshot collections have invalid types")
    return ExplanationSnapshot(
        schema_version=str(payload["schema_version"]),
        problem_id=str(payload["problem_id"]),
        family_id=str(payload["family_id"]),
        problem_revision=str(payload["problem_revision"]),
        problem_semantic_hash=str(payload["problem_semantic_hash"]),
        canonical_plan_hash=str(payload["canonical_plan_hash"]),
        verified_execution_hash=str(payload["verified_execution_hash"]),
        problem=dict(_mapping(payload["problem"])),
        root_scope=_teaching_scope_from_payload(_mapping(payload["root_scope"])),
        cross_scope_references=tuple(
            _teaching_reference_from_payload(_mapping(item))
            for item in references
        ),
        evidence={str(key): dict(_mapping(value)) for key, value in evidence.items()},
        answers=dict(_mapping(payload["answers"])),
    )


def _teaching_scope_from_payload(payload: Mapping[str, Any]) -> TeachingScope:
    _require_exact_fields(
        payload,
        {"scope_ref", "scope_steps", "goals", "children"},
        label="TeachingScope",
    )
    goals = _mapping(payload.get("goals", {}))
    return TeachingScope(
        scope_ref=str(payload["scope_ref"]),
        scope_steps=tuple(
            _teaching_source_from_payload(_mapping(item))
            for item in _sequence(payload.get("scope_steps", []))
        ),
        goals=tuple(
            TeachingGoal(
                goal_ref=str(goal_ref),
                steps=tuple(
                    _teaching_source_from_payload(_mapping(item))
                    for item in _sequence(
                        _checked_goal_payload(_mapping(goal))["steps"]
                    )
                ),
                answer_from=dict(
                    _checked_answer_from(
                        _mapping(_checked_goal_payload(_mapping(goal))["answer_from"])
                    )
                ),
            )
            for goal_ref, goal in goals.items()
        ),
        children=tuple(
            _teaching_scope_from_payload(_mapping(item))
            for item in _sequence(payload.get("children", []))
        ),
    )


def _teaching_source_from_payload(payload: Mapping[str, Any]) -> TeachingSource:
    required = {
        "source_step_id",
        "capability_id",
        "args",
        "output_targets",
        "return_expectations",
        "public_results",
        "checks",
        "evidence_refs",
        "closure_refs",
    }
    _require_exact_fields(
        payload,
        required | ({"intent"} if "intent" in payload else set()),
        label="TeachingSource",
    )
    public_results = _mapping(payload["public_results"])
    for return_name, result in public_results.items():
        result_payload = _mapping(result)
        _require_exact_fields(
            result_payload,
            {"runtime_type", "value"},
            label=f"TeachingSource.public_results.{return_name}",
        )
        if not str(result_payload["runtime_type"]):
            raise ValueError("TeachingSource runtime_type must be non-empty")
    return TeachingSource(
        source_step_id=str(payload["source_step_id"]),
        capability_id=str(payload["capability_id"]),
        args=dict(_mapping(payload["args"])),
        output_targets={
            str(key): str(value)
            for key, value in _mapping(payload["output_targets"]).items()
        },
        return_expectations={
            str(key): str(value)
            for key, value in _mapping(payload["return_expectations"]).items()
        },
        intent=str(payload["intent"]) if payload.get("intent") else None,
        public_results={
            str(key): dict(_mapping(value))
            for key, value in public_results.items()
        },
        checks=tuple(
            dict(_mapping(item)) for item in _sequence(payload["checks"])
        ),
        evidence_refs=tuple(str(item) for item in _sequence(payload["evidence_refs"])),
        closure_refs=tuple(str(item) for item in _sequence(payload["closure_refs"])),
    )


def _teaching_reference_from_payload(
    payload: Mapping[str, Any],
) -> TeachingCrossScopeReference:
    _require_exact_fields(
        payload,
        {
            "source_step_id",
            "target_step_id",
            "source_scope_ref",
            "target_scope_ref",
            "public_result_ref",
        },
        label="TeachingCrossScopeReference",
    )
    public_result_ref = _checked_answer_from(
        _mapping(payload["public_result_ref"])
    )
    return TeachingCrossScopeReference(
        source_step_id=str(payload["source_step_id"]),
        target_step_id=str(payload["target_step_id"]),
        source_scope_ref=str(payload["source_scope_ref"]),
        target_scope_ref=str(payload["target_scope_ref"]),
        public_result_ref=dict(public_result_ref),
    )


def _checked_goal_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    _require_exact_fields(
        payload,
        {"steps", "answer_from"},
        label="TeachingGoal",
    )
    return payload


def _checked_answer_from(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    _require_exact_fields(
        payload,
        {"step_id", "return"},
        label="public result reference",
    )
    return payload


def _require_exact_fields(
    payload: Mapping[str, Any],
    expected: set[str],
    *,
    label: str,
) -> None:
    if set(payload) != expected:
        raise ValueError(f"{label} payload fields do not match v2 contract")


def _validate_explanation_snapshot(snapshot: ExplanationSnapshot) -> None:
    if snapshot.schema_version != EXPLANATION_SNAPSHOT_CONTRACT:
        raise ValueError("unsupported ExplanationSnapshot contract")
    for field_name in (
        "problem_id",
        "family_id",
        "problem_revision",
        "problem_semantic_hash",
        "canonical_plan_hash",
        "verified_execution_hash",
    ):
        if not str(getattr(snapshot, field_name, "")):
            raise ValueError(f"{field_name} must be non-empty")
    scopes = tuple(iter_teaching_scopes(snapshot.root_scope))
    scope_refs = tuple(item.scope_ref for item in scopes)
    if len(scope_refs) != len(set(scope_refs)):
        raise ValueError("TeachingScope refs must be globally unique")
    sources = tuple(iter_teaching_sources(snapshot.root_scope))
    step_ids = tuple(item.source_step_id for item in sources)
    if len(step_ids) != len(set(step_ids)):
        raise ValueError("TeachingSource ids must be globally unique")
    goal_refs = tuple(goal.goal_ref for scope in scopes for goal in scope.goals)
    if len(goal_refs) != len(set(goal_refs)):
        raise ValueError("TeachingGoal refs must be globally unique")
    for source in sources:
        for ref in (*source.evidence_refs, *source.closure_refs):
            if ref not in snapshot.evidence:
                raise ValueError(f"TeachingSource references unknown evidence: {ref}")
    computed_plan_hash = canonical_plan_hash_for_teaching_scope(snapshot.root_scope)
    if computed_plan_hash != snapshot.canonical_plan_hash:
        raise ValueError("ExplanationSnapshot canonical Plan hash drift")
    owners = teaching_source_owners(snapshot.root_scope)
    for reference in snapshot.cross_scope_references:
        if reference.source_step_id not in owners or reference.target_step_id not in owners:
            raise ValueError("cross-Scope reference contains an unknown step")
        if owners[reference.source_step_id][0] != reference.source_scope_ref:
            raise ValueError("cross-Scope reference source owner drift")
        if owners[reference.target_step_id][0] != reference.target_scope_ref:
            raise ValueError("cross-Scope reference target owner drift")
        if reference.source_scope_ref == reference.target_scope_ref:
            raise ValueError("cross-Scope reference must cross an owner boundary")
        if reference.public_result_ref.get("step_id") != reference.source_step_id:
            raise ValueError("cross-Scope public result producer drift")
        return_name = str(reference.public_result_ref.get("return") or "")
        source = next(
            item for item in sources if item.source_step_id == reference.source_step_id
        )
        if return_name not in source.public_results:
            raise ValueError("cross-Scope reference names an unknown public result")


def _canonical_plan_payload(root: TeachingScope) -> dict[str, Any]:
    def scope_payload(scope: TeachingScope) -> dict[str, Any]:
        payload: dict[str, Any] = {"scope_ref": scope.scope_ref}
        if scope.scope_steps:
            payload["steps"] = [
                item.authored_step_payload() for item in scope.scope_steps
            ]
        if scope.goals:
            payload["goals"] = [
                {
                    "goal_ref": goal.goal_ref,
                    **(
                        {"steps": [item.authored_step_payload() for item in goal.steps]}
                        if goal.steps
                        else {}
                    ),
                    "answer_from": dict(goal.answer_from),
                }
                for goal in scope.goals
            ]
        if scope.children:
            payload["children"] = [scope_payload(item) for item in scope.children]
        return payload

    return {"format": "functional_plan/v2", "root_scope": scope_payload(root)}


def _answer_handles_by_result(
    root: TeachingScope,
) -> dict[tuple[str, str], tuple[str, ...]]:
    result: dict[tuple[str, str], list[str]] = {}
    for scope in iter_teaching_scopes(root):
        for goal in scope.goals:
            key = (
                str(goal.answer_from.get("step_id") or ""),
                str(goal.answer_from.get("return") or ""),
            )
            result.setdefault(key, []).append(f"answer:{goal.goal_ref}")
    return {key: tuple(value) for key, value in result.items()}


def _result_handles(
    source: TeachingSource,
    return_name: str,
    *,
    scope_ref: str,
    answer_handles: Mapping[tuple[str, str], tuple[str, ...]],
) -> tuple[str, ...]:
    handles = [f"fact:{scope_ref}:{source.source_step_id}_{return_name}"]
    target = source.output_targets.get(return_name)
    if target:
        handles.append(
            target
            if target.startswith(("answer:", "fact:"))
            else f"fact:{scope_ref}:{target}_{return_name}"
        )
    handles.extend(answer_handles.get((source.source_step_id, return_name), ()))
    return tuple(dict.fromkeys(handles))


def _primary_result_handles(root: TeachingScope) -> dict[tuple[str, str], str]:
    owners = teaching_source_owners(root)
    answers = _answer_handles_by_result(root)
    return {
        (source.source_step_id, return_name): _result_handles(
            source,
            return_name,
            scope_ref=owners[source.source_step_id][0],
            answer_handles=answers,
        )[0]
        for source in iter_teaching_sources(root)
        for return_name in source.public_results
    }


def _derived_reads(
    value: Any,
    primary_handles: Mapping[tuple[str, str], str],
    *,
    problem: Mapping[str, Any],
    scope_ref: str,
) -> list[str]:
    result: list[str] = []

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            if set(item) == {"step_id", "return"}:
                key = (str(item["step_id"]), str(item["return"]))
                result.append(
                    primary_handles.get(
                        key,
                        f"step-result:{key[0]}:{key[1]}",
                    )
                )
                return
            for nested in item.values():
                visit(nested)
            return
        if isinstance(item, (list, tuple)):
            for nested in item:
                visit(nested)
            return
        if isinstance(item, str):
            result.append(
                _problem_handle_for_source_ref(
                    item,
                    problem=problem,
                    scope_ref=scope_ref,
                )
                or item
            )

    visit(value)
    return list(dict.fromkeys(result))


def _problem_handle_for_source_ref(
    source_ref: str,
    *,
    problem: Mapping[str, Any],
    scope_ref: str,
) -> str:
    if ":" in source_ref:
        return source_ref
    candidates: list[tuple[int, str]] = []
    for collection_name in ("entities", "facts"):
        values = problem.get(collection_name, ())
        if not isinstance(values, (list, tuple)):
            continue
        for raw in values:
            if not isinstance(raw, Mapping):
                continue
            handle = str(raw.get("handle") or "")
            if not handle:
                continue
            name = str(raw.get("name") or "")
            item_type = str(
                raw.get("type") or raw.get("entity_type") or ""
            )
            if source_ref == name:
                semantic_score = 100
            elif source_ref == item_type:
                semantic_score = 80
            elif item_type and source_ref.startswith(f"{item_type}_"):
                # Prefer the most specific matching public type.  For example,
                # ``point_on_ray_n_cd`` also starts with the generic entity
                # type ``point`` but must resolve to the unique fact type
                # ``point_on_ray``.
                semantic_score = 40 + len(item_type)
            else:
                continue
            item_scope = str(raw.get("scope_id") or "problem")
            if item_scope == scope_ref:
                scope_score = 4
            elif item_scope == "problem":
                scope_score = 2
            elif scope_ref.startswith(f"{item_scope}_"):
                scope_score = 1
            else:
                continue
            candidates.append((semantic_score + scope_score, handle))
    if not candidates:
        return ""
    candidates.sort(key=lambda item: (-item[0], item[1]))
    best_score = candidates[0][0]
    best = [handle for score, handle in candidates if score == best_score]
    return best[0] if len(best) == 1 else ""


def _problem_fact_index(problem: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for collection_name in ("entities", "facts"):
        values = problem.get(collection_name, ())
        if not isinstance(values, (list, tuple)):
            continue
        for raw in values:
            if not isinstance(raw, Mapping) or not raw.get("handle"):
                continue
            item = _thaw(raw)
            handle = str(item["handle"])
            index[handle] = {
                **item,
                "handle": handle,
                "scope_id": str(item.get("scope_id") or "problem"),
                "type": str(item.get("output_type") or item.get("entity_type") or item.get("type") or "Fact"),
                "source": str(item.get("source") or "ProblemIR"),
                "authority": "verified_problem",
            }
    return index


def _add_verified_evidence_facts(
    index: dict[str, dict[str, Any]],
    *,
    evidence: Mapping[str, Mapping[str, Any]],
    owners: Mapping[str, tuple[str, str | None]],
) -> None:
    for evidence_ref, payload in evidence.items():
        step_id = str(payload.get("step_id") or "")
        owner = owners.get(step_id)
        if owner is None:
            continue
        scope_ref = owner[0]
        point_values: list[tuple[str, Any, str]] = []
        for construction in payload.get("constructions", ()):
            if not isinstance(construction, Mapping):
                continue
            for label_key, value_key in (
                ("label", "coordinate"),
                ("reflected_point_name", "reflected_point"),
            ):
                label = str(construction.get(label_key) or "")
                value = construction.get(value_key)
                if label and isinstance(value, (list, tuple)) and len(value) == 2:
                    point_values.append((label, value, "construction"))
        moving_labels = {
            str(item.get("chosen_ref") or "").rsplit(".", 1)[-1]
            for item in payload.get("role_resolutions", ())
            if isinstance(item, Mapping)
            and item.get("role") == "moving_point"
            and item.get("chosen_ref")
        }
        minimizing = payload.get("minimizing_points")
        if len(moving_labels) == 1 and isinstance(minimizing, Mapping):
            moving_label = next(iter(moving_labels))
            value = minimizing.get(moving_label)
            if isinstance(value, (list, tuple)) and len(value) == 2:
                point_values.append((moving_label, value, "attainment"))
        for label, value, kind in point_values:
            handle = f"fact:{scope_ref}:{step_id}:evidence:{kind}:{label}"
            index[handle] = {
                "handle": handle,
                "scope_id": scope_ref,
                "name": label,
                "type": "Point",
                "value": _thaw(value),
                "description": f"verified Macro {kind} point {label}",
                "source_step_id": step_id,
                "source": str(payload.get("macro_id") or "verified_macro"),
                "authority": "verified_execution_evidence",
                "evidence_ref": evidence_ref,
            }


def _mapping(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("expected an object")
    return value


def _sequence(value: Any) -> list[Any] | tuple[Any, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError("expected an array")
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True)
class LessonCandidateGroup:
    """LessonIR LLM 可选择的讲解候选组。

    它连接 canonical Functional call、method invocation trace 和讲解层拆分后的认知子步骤。
    """

    step: dict[str, Any]
    traces: tuple[TeachingTraceEntry, ...]
    teaching_substep_id: str | None = None
    teaching_substep_title: str | None = None
    teaching_substep_nav_title: str | None = None
    teaching_substep_title_required_terms: tuple[str, ...] = ()
    teaching_substep_nav_title_required_terms: tuple[str, ...] = ()
    teaching_focus: str | None = None
    preferred_method_ids: tuple[str, ...] = ()
    forbid_merge_with_sibling_substeps: bool = True
    required_reference_lines: tuple[str, ...] = ()

    @property
    def step_id(self) -> str:
        return str(self.step["step_id"])

    @property
    def candidate_group_id(self) -> str:
        if not self.teaching_substep_id:
            return self.step_id
        return f"{self.step_id}.{self.teaching_substep_id}"

    @property
    def scope_id(self) -> str:
        return str(self.step["scope_id"])

    @property
    def capability_id(self) -> str:
        return str(self.step.get("recipe_hint") or self.step.get("goal_type") or "unknown")

    @property
    def method_ids(self) -> tuple[str, ...]:
        return tuple(entry.method_id for entry in self._visible_traces)

    @property
    def trace_refs(self) -> tuple[str, ...]:
        return tuple(entry.trace_id for entry in self._visible_traces)

    @property
    def _visible_traces(self) -> tuple[TeachingTraceEntry, ...]:
        traces = tuple(entry for entry in self.traces if entry.hidden_reason is None)
        if not self.preferred_method_ids:
            return traces
        preferred = set(self.preferred_method_ids)
        filtered = tuple(entry for entry in traces if entry.method_id in preferred)
        return filtered or traces


@dataclass(frozen=True)
class LessonStep:
    """面向学生讲解的一步。"""

    id: str
    scope_id: str
    source_step_ids: tuple[str, ...]
    capability_ids: tuple[str, ...]
    trace_refs: tuple[str, ...]
    title: str
    goal: str
    nav_title: str | None = None
    derive: tuple[tuple[str, str], ...] = ()
    box: tuple[str, ...] = ()
    gaps: tuple[str, ...] = ()
    teaching_substep_ids: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "id": self.id,
            "scope_id": self.scope_id,
            "source_step_ids": list(self.source_step_ids),
            "capability_ids": list(self.capability_ids),
            "trace_refs": list(self.trace_refs),
            "title": self.title,
            "goal": self.goal,
            "derive": [list(item) for item in self.derive],
            "box": list(self.box),
            "gaps": list(self.gaps),
            "teaching_substep_ids": list(self.teaching_substep_ids),
        }
        if self.nav_title:
            payload["nav_title"] = self.nav_title
        return payload


@dataclass(frozen=True)
class LessonSection:
    """一个 question/subquestion 的讲解 section。"""

    scope_id: str
    title: str
    steps: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "scope_id": self.scope_id,
            "title": self.title,
            "steps": list(self.steps),
        }


@dataclass(frozen=True)
class LessonIR:
    """文字版教学 IR。"""

    problem_id: str
    family_id: str
    sections: tuple[LessonSection, ...]
    steps: tuple[LessonStep, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "problem_id": self.problem_id,
            "family_id": self.family_id,
            "sections": [section.to_payload() for section in self.sections],
            "steps": [step.to_payload() for step in self.steps],
        }


def lesson_ir_from_payload(payload: dict[str, Any]) -> LessonIR:
    """Restore LessonIR from a JSON payload."""
    return LessonIR(
        problem_id=str(payload["problem_id"]),
        family_id=str(payload["family_id"]),
        sections=tuple(
            LessonSection(
                scope_id=str(item["scope_id"]),
                title=str(item["title"]),
                steps=tuple(str(step_id) for step_id in item.get("steps", ())),
            )
            for item in payload.get("sections", ())
            if isinstance(item, dict)
        ),
        steps=tuple(
            LessonStep(
                id=str(item["id"]),
                scope_id=str(item["scope_id"]),
                source_step_ids=tuple(str(value) for value in item.get("source_step_ids", ())),
                capability_ids=tuple(str(value) for value in item.get("capability_ids", ())),
                trace_refs=tuple(str(value) for value in item.get("trace_refs", ())),
                title=str(item.get("title") or ""),
                goal=str(item.get("goal") or ""),
                nav_title=str(item["nav_title"]) if item.get("nav_title") else None,
                derive=tuple(
                    (str(pair[0]), str(pair[1]))
                    for pair in item.get("derive", ())
                    if isinstance(pair, list | tuple) and len(pair) == 2
                ),
                box=tuple(str(value) for value in item.get("box", ()) if str(value)),
                gaps=tuple(str(value) for value in item.get("gaps", ()) if str(value)),
                teaching_substep_ids=tuple(
                    str(value) for value in item.get("teaching_substep_ids", ())
                ),
            )
            for item in payload.get("steps", ())
            if isinstance(item, dict)
        ),
    )
