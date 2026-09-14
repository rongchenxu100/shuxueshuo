"""Verified ExplanationSnapshot v3 teaching-source models."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
from typing import Any, Iterator, Mapping


EXPLANATION_SNAPSHOT_CONTRACT = "explanation-snapshot/v3"


def explanation_snapshot_content_hash(snapshot: "ExplanationSnapshot") -> str:
    """Hash the stable public teaching content of a Snapshot.

    ``verified_execution_hash`` authenticates one concrete runtime/checkpoint
    instance.  Equivalent recorded runs intentionally receive different
    values, so it cannot be part of the cross-process Lesson/Visual source
    identity.  Every public input, output, calculation, check and evidence
    remains covered by this content hash.
    """

    payload = snapshot.to_payload()
    payload.pop("verified_execution_hash", None)
    return sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


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
    inputs: Mapping[str, tuple[Mapping[str, Any], ...]]
    outputs: Mapping[str, Mapping[str, Any]]
    output_targets: Mapping[str, str] = field(default_factory=dict)
    intent: str | None = None
    calculations: tuple[Mapping[str, Any], ...] = ()
    checks: tuple[Mapping[str, Any], ...] = ()

    @property
    def args(self) -> dict[str, Any]:
        """Derived authored args for the pre-B4 Lesson/Visual compatibility path."""

        result: dict[str, Any] = {}
        for name, items in self.inputs.items():
            authored = [_authored_ref_value(item.get("ref")) for item in items]
            result[name] = authored[0] if len(authored) == 1 else authored
        return result

    @property
    def public_results(self) -> Mapping[str, Mapping[str, Any]]:
        """Pre-B4 spelling; v3 serializes this collection as ``outputs``."""

        return self.outputs

    @property
    def closure_refs(self) -> tuple[str, ...]:
        """Symbolic closures are ordinary evidence in v3."""

        return ()

    @property
    def method_id(self) -> str:
        """Compatibility spelling for the pre-B4 Lesson builder."""

        return self.capability_id

    @property
    def trace_id(self) -> str:
        """Stable derived reference; Snapshot v3 stores no replay trace."""

        return f"trace:{self.source_step_id}:0:{self.capability_id}"

    @property
    def trace_fragments(self) -> tuple[dict[str, Any], ...]:
        """Public-result-only compatibility view for legacy role binders."""

        return tuple(
            {
                "return": return_name,
                "runtime_type": result.get("runtime_type"),
                "value": _thaw(result.get("value")),
            }
            for return_name, result in self.public_results.items()
        )

    @property
    def input_slots(self) -> tuple[str, ...]:
        return tuple(self.inputs)

    @property
    def output_slots(self) -> tuple[str, ...]:
        return tuple(self.outputs)

    @property
    def hidden_reason(self) -> None:
        return None

    def authored_step_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "step_id": self.source_step_id,
            "capability_id": self.capability_id,
            "args": _thaw(self.args),
        }
        if self.output_targets:
            payload["output_targets"] = dict(self.output_targets)
        if self.intent:
            payload["intent"] = self.intent
        return payload

    def to_payload(self) -> dict[str, Any]:
        return {
            "step_id": self.source_step_id,
            "capability_id": self.capability_id,
            "intent": self.intent,
            "inputs": {
                name: [_thaw(item) for item in items]
                for name, items in self.inputs.items()
            },
            "output_targets": dict(self.output_targets),
            "outputs": {
                name: _thaw(result)
                for name, result in self.outputs.items()
            },
            "calculations": [_thaw(item) for item in self.calculations],
            "checks": [_thaw(item) for item in self.checks],
        }


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
    steps: tuple[TeachingSource, ...] = ()
    goals: tuple[TeachingGoal, ...] = ()
    children: tuple["TeachingScope", ...] = ()

    @property
    def scope_steps(self) -> tuple[TeachingSource, ...]:
        """Pre-B4 in-memory spelling; v3 has one recursive ``steps`` concept."""

        return self.steps

    def to_payload(self) -> dict[str, Any]:
        return {
            "scope_ref": self.scope_ref,
            "steps": [item.to_payload() for item in self.steps],
            "goals": {
                goal.goal_ref: goal.to_payload()
                for goal in self.goals
            },
            "children": [item.to_payload() for item in self.children],
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
        return tuple(
            _thaw(payload)
            for source in iter_teaching_sources(self.root_scope)
            for payload in self.evidence_for_step(source.source_step_id)
            if payload.get("macro_id")
        )

    def evidence_for_step(
        self,
        source_step_id: str,
    ) -> tuple[Mapping[str, Any], ...]:
        """Return verified evidence by its canonical owner, without public refs."""

        return tuple(
            payload
            for payload in self.evidence.values()
            if str(payload.get("step_id") or "") == source_step_id
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
        """Derived compatibility view over v3 symbolic-closure evidence."""

        return tuple(
            SymbolicClosureTeachingTrace(
                source_call_id=str(payload.get("step_id") or ""),
                target=str(payload.get("target") or ""),
                target_value=(
                    str(payload["target_value"])
                    if payload.get("target_value") is not None
                    else None
                ),
                equation_sources=tuple(payload.get("equation_sources") or ()),
                known_substitutions=tuple(
                    (
                        str(item.get("symbol") or ""),
                        str(item.get("value") or ""),
                    )
                    for item in payload.get("substitutions") or ()
                    if isinstance(item, Mapping)
                ),
                constraint_summary=(
                    str(payload["constraint_summary"])
                    if payload.get("constraint_summary") is not None
                    else None
                ),
                branch_count=int(payload.get("branch_count") or 0),
                residual_symbols=tuple(payload.get("residual_symbols") or ()),
                affected_returns=tuple(payload.get("affected_returns") or ()),
            )
            for payload in self.evidence.values()
            if payload.get("schema_version")
            == "symbolic-closure-teaching-evidence/v1"
        )

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
        yield from scope.steps
        for goal in scope.goals:
            yield from goal.steps


def teaching_source_owners(
    root: TeachingScope,
) -> dict[str, tuple[str, str | None]]:
    result: dict[str, tuple[str, str | None]] = {}
    for scope in iter_teaching_scopes(root):
        for source in scope.steps:
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
        "evidence",
        "answers",
    }
    if set(payload) != expected:
        raise ValueError("ExplanationSnapshot payload fields do not match v3 contract")
    evidence = payload["evidence"]
    if not isinstance(evidence, Mapping):
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
        evidence={str(key): dict(_mapping(value)) for key, value in evidence.items()},
        answers=dict(_mapping(payload["answers"])),
    )


def _teaching_scope_from_payload(payload: Mapping[str, Any]) -> TeachingScope:
    _require_exact_fields(
        payload,
        {"scope_ref", "steps", "goals", "children"},
        label="TeachingScope",
    )
    goals = _mapping(payload.get("goals", {}))
    return TeachingScope(
        scope_ref=str(payload["scope_ref"]),
        steps=tuple(
            _teaching_source_from_payload(_mapping(item))
            for item in _sequence(payload.get("steps", []))
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
        "step_id",
        "capability_id",
        "intent",
        "inputs",
        "output_targets",
        "outputs",
        "calculations",
        "checks",
    }
    _require_exact_fields(payload, required, label="TeachingSource")
    inputs = _mapping(payload["inputs"])
    checked_inputs: dict[str, tuple[dict[str, Any], ...]] = {}
    for arg_name, raw_items in inputs.items():
        items = tuple(_mapping(item) for item in _sequence(raw_items))
        if not items:
            raise ValueError("TeachingSource input arrays must be non-empty")
        checked_inputs[str(arg_name)] = tuple(
            _checked_teaching_input(item) for item in items
        )
    outputs = _mapping(payload["outputs"])
    for return_name, result in outputs.items():
        result_payload = _mapping(result)
        _require_exact_fields(
            result_payload,
            {"runtime_type", "value", "display"},
            label=f"TeachingSource.outputs.{return_name}",
        )
        if not str(result_payload["runtime_type"]) or not str(
            result_payload["display"]
        ):
            raise ValueError("TeachingSource output type/display must be non-empty")
    return TeachingSource(
        source_step_id=str(payload["step_id"]),
        capability_id=str(payload["capability_id"]),
        inputs=checked_inputs,
        output_targets={
            str(key): str(value)
            for key, value in _mapping(payload["output_targets"]).items()
        },
        intent=str(payload["intent"]) if payload.get("intent") else None,
        outputs={
            str(key): dict(_mapping(value))
            for key, value in outputs.items()
        },
        calculations=tuple(
            dict(_mapping(item)) for item in _sequence(payload["calculations"])
        ),
        checks=tuple(
            dict(_mapping(item)) for item in _sequence(payload["checks"])
        ),
    )


def _checked_teaching_input(payload: Mapping[str, Any]) -> dict[str, Any]:
    expected = {"ref", "runtime_type", "value", "display"}
    if "resolved_from" in payload:
        expected.add("resolved_from")
    _require_exact_fields(payload, expected, label="TeachingSource input")
    _checked_teaching_ref(_mapping(payload["ref"]), allow_source=True)
    if "resolved_from" in payload:
        _checked_teaching_ref(
            _mapping(payload["resolved_from"]),
            allow_source=False,
        )
    if not str(payload["runtime_type"]) or not str(payload["display"]):
        raise ValueError("TeachingSource input type/display must be non-empty")
    return dict(payload)


def _checked_teaching_ref(
    payload: Mapping[str, Any],
    *,
    allow_source: bool,
) -> None:
    kind = str(payload.get("kind") or "")
    if kind == "source" and allow_source:
        _require_exact_fields(payload, {"kind", "ref"}, label="SourceRef")
        if not str(payload.get("ref") or ""):
            raise ValueError("SourceRef ref must be non-empty")
        return
    if kind == "step_result":
        _require_exact_fields(
            payload,
            {"kind", "step_id", "return"},
            label="StepResultRef",
        )
        if not str(payload.get("step_id") or "") or not str(
            payload.get("return") or ""
        ):
            raise ValueError("StepResultRef fields must be non-empty")
        return
    raise ValueError("TeachingSource ref has an unsupported kind")


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
        raise ValueError(f"{label} payload fields do not match v3 contract")


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
    source_by_id = {source.source_step_id: source for source in sources}
    for evidence_id, payload in snapshot.evidence.items():
        evidence_step_id = str(payload.get("step_id") or "")
        if not evidence_step_id or evidence_step_id not in source_by_id:
            raise ValueError(
                "ExplanationSnapshot evidence has no canonical Step owner: "
                f"{evidence_id}"
            )
    for source in sources:
        calculation_ids = tuple(
            str(item.get("calculation_id") or "")
            for item in source.calculations
        )
        if any(not item for item in calculation_ids) or len(calculation_ids) != len(
            set(calculation_ids)
        ):
            raise ValueError("TeachingSource calculation ids must be non-empty and unique")
    # Snapshot v3 deliberately omits Plan-only controls such as
    # return_expectations, so the serialized teaching tree is not a reversible
    # Canonical Plan encoding.  The builder verifies the authoritative Plan
    # hash before projection; a parsed Snapshot preserves that verified hash.
    for consumer in sources:
        for items in consumer.inputs.values():
            for item in items:
                ref = item.get("resolved_from") or item.get("ref")
                if not isinstance(ref, Mapping) or ref.get("kind") != "step_result":
                    continue
                producer_id = str(ref.get("step_id") or "")
                return_name = str(ref.get("return") or "")
                producer = source_by_id.get(producer_id)
                if producer is None or return_name not in producer.outputs:
                    raise ValueError(
                        "TeachingSource input references an unknown public result"
                    )


def _canonical_plan_payload(root: TeachingScope) -> dict[str, Any]:
    def scope_payload(scope: TeachingScope) -> dict[str, Any]:
        payload: dict[str, Any] = {"scope_ref": scope.scope_ref}
        if scope.steps:
            payload["steps"] = [
                item.authored_step_payload() for item in scope.steps
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


def _authored_ref_value(value: Any) -> Any:
    if not isinstance(value, Mapping):
        raise ValueError("TeachingSource input ref must be an object")
    kind = str(value.get("kind") or "")
    if kind == "source":
        return str(value.get("ref") or "")
    if kind == "step_result":
        return {
            "step_id": str(value.get("step_id") or ""),
            "return": str(value.get("return") or ""),
        }
    raise ValueError("TeachingSource input ref has an unsupported kind")
