"""FunctionalPlan mechanism few-shot assets and deterministic projection.

Complete FunctionalPlan fixtures are executable truth. Internal manifests only
declare extraction, neutralization, and selection metadata. Stored few-shot
assets may add prompt annotation; their plan projection remains a strict
``functional_plan/v1`` payload.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
import re
from typing import Any, Iterable, Literal, Mapping

from shuxueshuo_server.solver.runtime._paths import repo_root
from shuxueshuo_server.solver.runtime.handle_alias_index import (
    SEMANTIC_READ_KINDS,
    looks_like_canonical_ref,
)


FUNCTIONAL_PLAN_FORMAT = "functional_plan/v1"
_FORBIDDEN_PLAN_KEYS = frozenset(
    {
        "goal_type",
        "runtime_path",
        "binding_selector",
    }
)
_PROMPT_FORBIDDEN_KEYS = frozenset(
    {
        "example_id",
        "source_problem_id",
        "pack_ids",
        "capability_ids",
        "answer_value_types",
        "source_call_ids",
        "neutralization_map",
        "family_id",
        "problem_id",
        "expected",
        "expected_answers",
    }
)
_SOURCE_TEXT_NUMBER_RE = re.compile(r"\d")
_CALL_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


FunctionalFewShotSelectionRole = Literal["core", "supporting", "fallback"]
FunctionalFewShotSelectionMode = Literal["strict_test", "new_problem"]
FunctionalFewShotSelectionTier = Literal[
    "same_family",
    "cross_family",
    "fallback",
]


@dataclass(frozen=True)
class FunctionalFewShotSelectionRecord:
    """Internal record used to keep one solve session on one example."""

    example_id: str
    mode: FunctionalFewShotSelectionMode
    family_id: str | None
    source_problem_id: str
    selection_tier: FunctionalFewShotSelectionTier

    @classmethod
    def from_payload(
        cls,
        payload: object,
    ) -> "FunctionalFewShotSelectionRecord":
        if not isinstance(payload, dict):
            raise TypeError("functional few-shot selection must be an object")
        required = {
            "example_id",
            "mode",
            "family_id",
            "source_problem_id",
            "selection_tier",
        }
        if set(payload) != required:
            raise ValueError(
                "functional few-shot selection must contain exactly "
                + ", ".join(sorted(required))
            )
        family_id = payload.get("family_id")
        if family_id is not None and (
            not isinstance(family_id, str) or not family_id.strip()
        ):
            raise TypeError("functional few-shot selection family_id is invalid")
        return cls(
            example_id=_required_text(payload, "example_id"),
            mode=_selection_mode(payload.get("mode")),
            family_id=family_id.strip() if isinstance(family_id, str) else None,
            source_problem_id=_required_text(payload, "source_problem_id"),
            selection_tier=_selection_tier(payload.get("selection_tier")),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "example_id": self.example_id,
            "mode": self.mode,
            "family_id": self.family_id,
            "source_problem_id": self.source_problem_id,
            "selection_tier": self.selection_tier,
        }


@dataclass(frozen=True)
class FunctionalFewShotSelectionResult:
    """Prompt projections plus the non-prompt selection record."""

    examples: tuple[dict[str, Any], ...]
    selection: FunctionalFewShotSelectionRecord


@dataclass(frozen=True)
class FunctionalFewShotIndex:
    """Validated family/pack index over the stored mechanism examples."""

    entries: tuple["FunctionalFewShotEntry", ...]
    by_family: Mapping[str, tuple["FunctionalFewShotEntry", ...]]
    cross_family_entries: tuple["FunctionalFewShotEntry", ...]
    fallback_by_pack: Mapping[str, tuple["FunctionalFewShotEntry", ...]]

    @classmethod
    def from_entries(
        cls,
        entries: Iterable["FunctionalFewShotEntry"],
    ) -> "FunctionalFewShotIndex":
        ordered = tuple(entries)
        by_family: dict[str, list[FunctionalFewShotEntry]] = {}
        fallback_by_pack: dict[str, list[FunctionalFewShotEntry]] = {}
        family_by_source: dict[str, str] = {}
        normal: list[FunctionalFewShotEntry] = []
        for entry in ordered:
            if entry.selection_role == "fallback":
                if entry.family_id is not None:
                    raise ValueError(
                        "functional few-shot fallback must not declare family_id: "
                        f"{entry.example_id}"
                    )
                if not entry.pack_ids:
                    raise ValueError(
                        "functional few-shot fallback must declare pack_ids: "
                        f"{entry.example_id}"
                    )
                for pack_id in entry.pack_ids:
                    fallback_by_pack.setdefault(pack_id, []).append(entry)
                continue
            if entry.family_id is None:
                raise ValueError(
                    "functional few-shot must declare family_id: "
                    f"{entry.example_id}"
                )
            previous_family = family_by_source.setdefault(
                entry.source_problem_id,
                entry.family_id,
            )
            if previous_family != entry.family_id:
                raise ValueError(
                    "functional few-shot source has conflicting family ids: "
                    f"{entry.source_problem_id}"
                )
            by_family.setdefault(entry.family_id, []).append(entry)
            normal.append(entry)
        return cls(
            entries=ordered,
            by_family={
                family_id: tuple(items)
                for family_id, items in by_family.items()
            },
            cross_family_entries=tuple(normal),
            fallback_by_pack={
                pack_id: tuple(items)
                for pack_id, items in fallback_by_pack.items()
            },
        )


@dataclass(frozen=True)
class FunctionalFewShotAnnotation:
    """Prompt-facing mathematical guidance stored with a few-shot plan."""

    purpose: str
    use_when: str
    key_idea: str
    do_not_use_when: tuple[str, ...]

    @classmethod
    def from_payload(cls, payload: object) -> "FunctionalFewShotAnnotation":
        if not isinstance(payload, dict):
            raise TypeError("functional few-shot annotation must be an object")
        required = {"purpose", "use_when", "key_idea", "do_not_use_when"}
        missing = sorted(required - set(payload))
        extra = sorted(set(payload) - required)
        if missing:
            raise ValueError(
                "functional few-shot annotation missing required keys: "
                f"{missing}"
            )
        if extra:
            raise ValueError(
                "functional few-shot annotation contains unknown keys: "
                f"{extra}"
            )
        excluded = _string_tuple(payload, "do_not_use_when")
        if not excluded:
            raise ValueError(
                "functional few-shot do_not_use_when must be non-empty"
            )
        if len(excluded) != len(set(excluded)):
            raise ValueError(
                "functional few-shot do_not_use_when must be unique"
            )
        return cls(
            purpose=_required_text(payload, "purpose"),
            use_when=_required_text(payload, "use_when"),
            key_idea=_required_text(payload, "key_idea"),
            do_not_use_when=excluded,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "purpose": self.purpose,
            "use_when": self.use_when,
            "key_idea": self.key_idea,
            "do_not_use_when": list(self.do_not_use_when),
        }


@dataclass(frozen=True)
class FunctionalFewShotEntry:
    """A declarative extraction recipe for one neutral mechanism subgraph."""

    example_id: str
    source_problem_id: str
    pack_ids: tuple[str, ...]
    capability_ids: tuple[str, ...]
    answer_value_types: tuple[str, ...]
    source_call_ids: tuple[str, ...]
    conditions: tuple[dict[str, Any], ...]
    call_id_map: Mapping[str, str]
    semantic_ref_map: Mapping[str, str]
    text_replacements: Mapping[str, str]
    family_id: str | None = None
    selection_role: FunctionalFewShotSelectionRole = "supporting"
    annotation: FunctionalFewShotAnnotation | None = None
    neutralized: bool = True

    @classmethod
    def from_payload(cls, payload: object) -> "FunctionalFewShotEntry":
        if not isinstance(payload, dict):
            raise TypeError("functional few-shot manifest must be an object")
        required = {
            "example_id",
            "source_problem_id",
            "pack_ids",
            "capability_ids",
            "answer_value_types",
            "source_call_ids",
            "conditions",
            "neutralization_map",
            "neutralized",
        }
        missing = sorted(required - set(payload))
        extra = sorted(
            set(payload) - required - {"family_id", "selection_role"}
        )
        if missing:
            raise ValueError(
                f"functional few-shot manifest missing required keys: {missing}"
            )
        if extra:
            raise ValueError(
                "functional few-shot manifest contains unknown keys: "
                f"{extra}"
            )
        neutralization = payload.get("neutralization_map")
        if not isinstance(neutralization, dict):
            raise TypeError(
                "functional few-shot neutralization_map must be an object"
            )
        neutralization_keys = {
            "call_ids",
            "semantic_refs",
            "text_replacements",
        }
        if set(neutralization) != neutralization_keys:
            raise ValueError(
                "functional few-shot neutralization_map must contain exactly "
                "call_ids, semantic_refs, and text_replacements"
            )
        conditions = payload.get("conditions")
        if not isinstance(conditions, list):
            raise TypeError("functional few-shot conditions must be an array")
        entry = cls(
            example_id=_required_text(payload, "example_id"),
            source_problem_id=_required_text(payload, "source_problem_id"),
            pack_ids=_string_tuple(payload, "pack_ids"),
            capability_ids=_string_tuple(payload, "capability_ids"),
            answer_value_types=_string_tuple(payload, "answer_value_types"),
            source_call_ids=_string_tuple(payload, "source_call_ids"),
            conditions=tuple(_condition_payload(item) for item in conditions),
            call_id_map=_string_map(neutralization, "call_ids"),
            semantic_ref_map=_string_map(neutralization, "semantic_refs"),
            text_replacements=_string_map(
                neutralization,
                "text_replacements",
            ),
            family_id=(
                _required_text(payload, "family_id")
                if "family_id" in payload
                else None
            ),
            selection_role=_selection_role(payload.get("selection_role")),
            neutralized=payload.get("neutralized") is True,
        )
        if not 2 <= len(entry.source_call_ids) <= 5:
            raise ValueError(
                "functional few-shot source_call_ids must contain 2-5 calls"
            )
        if len(entry.source_call_ids) != len(set(entry.source_call_ids)):
            raise ValueError(
                "functional few-shot source_call_ids must be unique"
            )
        if not entry.neutralized:
            raise ValueError(
                "non-neutralized functional few-shot assets cannot be loaded"
            )
        return entry


def default_functional_plan_fixture_dir() -> Path:
    return repo_root(Path(__file__)) / "internal" / "functional-plan-fixtures"


def default_functional_few_shot_dir() -> Path:
    return repo_root(Path(__file__)) / "internal" / "functional-few-shots"


def default_functional_few_shot_manifest_dir() -> Path:
    return (
        repo_root(Path(__file__))
        / "internal"
        / "functional-few-shot-manifests"
    )


def functional_plan_fixture_path(
    problem_id: str,
    *,
    fixture_dir: Path | str | None = None,
) -> Path:
    root = (
        Path(fixture_dir)
        if fixture_dir is not None
        else default_functional_plan_fixture_dir()
    )
    return root / f"{problem_id}.functional-plan.json"


def load_functional_plan_fixture(
    problem_id: str,
    *,
    fixture_dir: Path | str | None = None,
) -> dict[str, Any]:
    path = functional_plan_fixture_path(problem_id, fixture_dir=fixture_dir)
    payload = json.loads(path.read_text(encoding="utf-8"))
    validate_functional_plan_fixture(payload)
    return payload


def validate_functional_plan_fixture(payload: object) -> None:
    """Validate prompt-independent invariants of a complete source plan."""
    if not isinstance(payload, dict):
        raise TypeError("functional plan fixture must be an object")
    if payload.get("format") != FUNCTIONAL_PLAN_FORMAT:
        raise ValueError(
            f"functional plan fixture format must be {FUNCTIONAL_PLAN_FORMAT}"
        )
    if set(payload) != {"format", "scopes"}:
        raise ValueError(
            "functional plan fixture must contain exactly format and scopes"
        )
    scopes = payload.get("scopes")
    if not isinstance(scopes, list) or not scopes:
        raise ValueError("functional plan fixture scopes must be non-empty")
    forbidden = sorted(_collect_keys(payload).intersection(_FORBIDDEN_PLAN_KEYS))
    if forbidden:
        raise ValueError(
            f"functional plan fixture contains forbidden keys: {forbidden}"
        )
    serialized = json.dumps(payload, ensure_ascii=False)
    if _contains_canonical_handle(serialized):
        raise ValueError(
            "functional plan fixture must not contain canonical handles"
        )
    seen_calls: set[str] = set()
    for scope in scopes:
        if not isinstance(scope, dict):
            raise TypeError("functional plan fixture scope must be an object")
        if set(scope) != {"scope_id", "label", "calls"}:
            raise ValueError(
                "functional plan fixture scope must contain exactly "
                "scope_id, label, calls"
            )
        calls = scope.get("calls")
        if not isinstance(calls, list) or not calls:
            raise ValueError(
                "functional plan fixture scope calls must be non-empty"
            )
        for call in calls:
            _validate_source_call(call, seen_calls)


def load_functional_few_shot_entries(
    *,
    few_shot_dir: Path | str | None = None,
    manifest_dir: Path | str | None = None,
    fixture_dir: Path | str | None = None,
) -> list[FunctionalFewShotEntry]:
    prompt_root = (
        Path(few_shot_dir)
        if few_shot_dir is not None
        else default_functional_few_shot_dir()
    )
    manifest_root = (
        Path(manifest_dir)
        if manifest_dir is not None
        else default_functional_few_shot_manifest_dir()
    )
    if (
        not prompt_root.exists()
        or not manifest_root.exists()
        or not any(prompt_root.glob("*.functional-few-shot.json"))
    ):
        return []
    entries: list[FunctionalFewShotEntry] = []
    strict_assets = few_shot_dir is None
    for path in sorted(manifest_root.glob("*.manifest.json")):
        entry = FunctionalFewShotEntry.from_payload(
            json.loads(path.read_text(encoding="utf-8"))
        )
        prompt_path = prompt_root / path.name.replace(
            ".manifest.json",
            ".functional-few-shot.json",
        )
        if not prompt_path.exists():
            if strict_assets:
                raise ValueError(
                    "functional few-shot plan asset missing: "
                    f"{prompt_path.name}"
                )
            continue
        source = load_functional_plan_fixture(
            entry.source_problem_id,
            fixture_dir=fixture_dir,
        )
        validate_functional_few_shot_entry(entry, source_plan=source)
        stored_asset = json.loads(prompt_path.read_text(encoding="utf-8"))
        annotation, stored_plan = split_functional_few_shot_asset(stored_asset)
        _validate_annotation_safety(annotation, entry=entry)
        validate_functional_few_shot_prompt_payload(stored_plan)
        projected_plan = project_functional_few_shot_example(
            entry,
            source_plan=source,
        )
        if stored_plan != projected_plan:
            raise ValueError(
                "functional few-shot plan differs from deterministic "
                f"projection: {prompt_path.name}"
            )
        entries.append(replace(entry, annotation=annotation))
    FunctionalFewShotIndex.from_entries(entries)
    return entries


def validate_functional_few_shot_entry(
    entry: FunctionalFewShotEntry,
    *,
    source_plan: Mapping[str, Any],
) -> None:
    selected = _selected_source_calls(source_plan, entry.source_call_ids)
    selected_ids = set(entry.source_call_ids)
    selected_capabilities = tuple(
        dict.fromkeys(str(call["capability_id"]) for _scope, call in selected)
    )
    if selected_capabilities != entry.capability_ids:
        raise ValueError(
            "functional few-shot capability_ids must equal the selected source "
            f"calls: expected {selected_capabilities}, got {entry.capability_ids}"
        )
    if set(entry.call_id_map) != selected_ids:
        raise ValueError(
            "functional few-shot call_ids map must cover every selected call"
        )
    neutral_call_ids = tuple(entry.call_id_map.values())
    if len(neutral_call_ids) != len(set(neutral_call_ids)):
        raise ValueError(
            "functional few-shot neutral call ids must be unique"
        )
    if any(_CALL_ID_RE.fullmatch(item) is None for item in neutral_call_ids):
        raise ValueError(
            "functional few-shot neutral call ids must be stable identifiers"
        )
    source_refs: set[str] = set()
    for _scope, call in selected:
        for ref in _functional_refs(call):
            if "from_call" in ref:
                dependency = str(ref["from_call"])
                if dependency not in selected_ids:
                    raise ValueError(
                        "functional few-shot dependency is not closed: "
                        f"{call['call_id']} -> {dependency}"
                    )
            else:
                source_refs.add(str(ref["ref"]))
    if set(entry.semantic_ref_map) != source_refs:
        raise ValueError(
            "functional few-shot semantic_refs map must cover every selected "
            f"SemanticRef: expected {sorted(source_refs)}, got "
            f"{sorted(entry.semantic_ref_map)}"
        )
    neutral_refs = tuple(entry.semantic_ref_map.values())
    if len(neutral_refs) != len(set(neutral_refs)):
        raise ValueError(
            "functional few-shot neutral semantic refs must be unique"
        )
    context_refs = tuple(str(item["ref"]) for item in entry.conditions)
    if len(context_refs) != len(set(context_refs)):
        raise ValueError(
            "functional few-shot condition refs must be unique"
        )
    if set(context_refs) != set(neutral_refs):
        raise ValueError(
            "functional few-shot conditions must describe every neutral "
            "SemanticRef exactly once"
        )
    prompt_payload = project_functional_few_shot_example(
        entry,
        source_plan=source_plan,
    )
    validate_functional_few_shot_prompt_payload(prompt_payload)


def project_functional_few_shot_example(
    entry: FunctionalFewShotEntry,
    *,
    source_plan: Mapping[str, Any],
) -> dict[str, Any]:
    """Extract and neutralize one closed mechanism subgraph."""
    selected = _selected_source_calls(source_plan, entry.source_call_ids)
    calls = [
        _neutralized_call(call, entry)
        for _scope, call in selected
    ]
    payload = {
        "format": FUNCTIONAL_PLAN_FORMAT,
        "scopes": [
            {
                "scope_id": "example",
                "label": "机制示例",
                "calls": calls,
            }
        ],
    }
    validate_functional_few_shot_prompt_payload(payload)
    return payload


def project_functional_few_shot_prompt_example(
    entry: FunctionalFewShotEntry,
    *,
    source_plan: Mapping[str, Any],
) -> dict[str, Any]:
    """Attach stored annotation to a deterministic strict plan projection."""
    plan = project_functional_few_shot_example(entry, source_plan=source_plan)
    if entry.annotation is None:
        return plan
    return {
        "format": plan["format"],
        "annotation": entry.annotation.to_payload(),
        "scopes": plan["scopes"],
    }


def split_functional_few_shot_asset(
    payload: object,
) -> tuple[FunctionalFewShotAnnotation | None, dict[str, Any]]:
    """Split optional stored annotation from the strict wire-shaped plan."""
    if not isinstance(payload, dict):
        raise TypeError("functional few-shot asset must be an object")
    allowed = {"format", "annotation", "scopes"}
    extra = sorted(set(payload) - allowed)
    if extra:
        raise ValueError(
            f"functional few-shot asset contains unknown keys: {extra}"
        )
    annotation_payload = payload.get("annotation")
    annotation = (
        FunctionalFewShotAnnotation.from_payload(annotation_payload)
        if annotation_payload is not None
        else None
    )
    plan = {
        "format": payload.get("format"),
        "scopes": payload.get("scopes"),
    }
    return annotation, plan


def validate_functional_few_shot_asset(payload: object) -> None:
    """Validate an annotated stored asset and its strict plan projection."""
    _annotation, plan = split_functional_few_shot_asset(payload)
    validate_functional_few_shot_prompt_payload(plan)


def validate_functional_few_shot_prompt_payload(payload: object) -> None:
    """Ensure the prompt projection is anonymous and wire-shaped."""
    validate_functional_plan_fixture(payload)
    forbidden = sorted(_collect_keys(payload).intersection(_PROMPT_FORBIDDEN_KEYS))
    if forbidden:
        raise ValueError(
            f"functional few-shot prompt contains metadata keys: {forbidden}"
        )
    serialized = json.dumps(payload, ensure_ascii=False)
    if _contains_canonical_handle(serialized):
        raise ValueError(
            "functional few-shot prompt must not contain canonical handles"
        )
    for text in _prompt_explanatory_text(payload):
        if _SOURCE_TEXT_NUMBER_RE.search(text):
            raise ValueError(
                "functional few-shot prompt text must not contain concrete numbers"
            )


def select_functional_few_shot_examples(
    *,
    capability_ids: Iterable[str],
    base_pack_ids: Iterable[str],
    mechanism_pack_ids: Iterable[str],
    answer_value_types: Iterable[str],
    family_id: str | None = None,
    problem_id: str | None = None,
    allow_same_problem: bool = True,
    mode: FunctionalFewShotSelectionMode | None = None,
    locked_selection: (
        FunctionalFewShotSelectionRecord | Mapping[str, Any] | None
    ) = None,
    top_k: int = 1,
    few_shot_dir: Path | str | None = None,
    manifest_dir: Path | str | None = None,
    fixture_dir: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Compatibility wrapper returning only prompt-facing examples."""
    if top_k <= 0:
        return []
    result = select_functional_few_shot(
        capability_ids=capability_ids,
        base_pack_ids=base_pack_ids,
        mechanism_pack_ids=mechanism_pack_ids,
        answer_value_types=answer_value_types,
        family_id=family_id,
        problem_id=problem_id,
        allow_same_problem=allow_same_problem,
        mode=mode,
        locked_selection=locked_selection,
        top_k=top_k,
        few_shot_dir=few_shot_dir,
        manifest_dir=manifest_dir,
        fixture_dir=fixture_dir,
    )
    return list(result.examples)


def select_functional_few_shot(
    *,
    capability_ids: Iterable[str],
    base_pack_ids: Iterable[str],
    mechanism_pack_ids: Iterable[str],
    answer_value_types: Iterable[str],
    family_id: str | None = None,
    problem_id: str | None = None,
    allow_same_problem: bool = True,
    mode: FunctionalFewShotSelectionMode | None = None,
    locked_selection: (
        FunctionalFewShotSelectionRecord | Mapping[str, Any] | None
    ) = None,
    top_k: int = 1,
    few_shot_dir: Path | str | None = None,
    manifest_dir: Path | str | None = None,
    fixture_dir: Path | str | None = None,
) -> FunctionalFewShotSelectionResult:
    """Select and record one stable prompt-safe mechanism example."""
    if top_k != 1:
        raise ValueError(
            "planner_configuration_error: functional few-shot top_k must be 1"
        )
    effective_mode = resolve_functional_few_shot_selection_mode(
        mode,
        allow_same_problem=allow_same_problem,
    )
    available_capabilities = set(capability_ids)
    current_packs = set(base_pack_ids) | set(mechanism_pack_ids)
    mechanism_packs = set(mechanism_pack_ids)
    answer_types = set(answer_value_types)
    entries = load_functional_few_shot_entries(
        few_shot_dir=few_shot_dir,
        manifest_dir=manifest_dir,
        fixture_dir=fixture_dir,
    )
    index = FunctionalFewShotIndex.from_entries(entries)
    if locked_selection is not None:
        record = (
            locked_selection
            if isinstance(locked_selection, FunctionalFewShotSelectionRecord)
            else FunctionalFewShotSelectionRecord.from_payload(locked_selection)
        )
        entry = _restore_locked_entry(
            index,
            record=record,
            mode=effective_mode,
            family_id=family_id,
            problem_id=problem_id,
            available_capabilities=available_capabilities,
            current_packs=current_packs,
        )
        return FunctionalFewShotSelectionResult(
            examples=(_prompt_projection(entry, fixture_dir=fixture_dir),),
            selection=record,
        )

    normal_entries = tuple(
        entry
        for entry in index.cross_family_entries
        if set(entry.capability_ids) <= available_capabilities
        and not (
            effective_mode == "strict_test"
            and problem_id == entry.source_problem_id
        )
    )
    same_family = tuple(
        entry for entry in normal_entries if entry.family_id == family_id
    )
    cross_family = tuple(
        entry
        for entry in normal_entries
        if entry.family_id != family_id
        and _normal_candidate_is_relevant(
            entry,
            current_packs=current_packs,
            answer_types=answer_types,
        )
    )
    tier: FunctionalFewShotSelectionTier
    candidates: tuple[FunctionalFewShotEntry, ...]
    if same_family:
        tier = "same_family"
        candidates = same_family
    elif cross_family:
        tier = "cross_family"
        candidates = cross_family
    else:
        tier = "fallback"
        candidates = tuple(
            entry
            for entry in index.entries
            if entry.selection_role == "fallback"
            and set(entry.capability_ids) <= available_capabilities
            and set(entry.pack_ids) <= current_packs
        )
    if not candidates:
        raise ValueError(
            "planner_configuration_error: no compatible functional few-shot "
            f"for family={family_id!r}, mode={effective_mode!r}"
        )

    selected = sorted(
        candidates,
        key=lambda entry: _candidate_sort_key(
            entry,
            mechanism_packs=mechanism_packs,
            answer_types=answer_types,
        ),
    )[0]
    record = FunctionalFewShotSelectionRecord(
        example_id=selected.example_id,
        mode=effective_mode,
        family_id=family_id,
        source_problem_id=selected.source_problem_id,
        selection_tier=tier,
    )
    return FunctionalFewShotSelectionResult(
        examples=(_prompt_projection(selected, fixture_dir=fixture_dir),),
        selection=record,
    )


def resolve_functional_few_shot_selection_mode(
    mode: FunctionalFewShotSelectionMode | str | None,
    *,
    allow_same_problem: bool,
) -> FunctionalFewShotSelectionMode:
    """Resolve explicit mode before falling back to the legacy boolean."""
    if mode is None:
        return "new_problem" if allow_same_problem else "strict_test"
    return _selection_mode(mode)


def _normal_candidate_is_relevant(
    entry: FunctionalFewShotEntry,
    *,
    current_packs: set[str],
    answer_types: set[str],
) -> bool:
    return bool(
        set(entry.pack_ids).intersection(current_packs)
        or set(entry.answer_value_types).intersection(answer_types)
    )


def _candidate_sort_key(
    entry: FunctionalFewShotEntry,
    *,
    mechanism_packs: set[str],
    answer_types: set[str],
) -> tuple[int, int, int, int, str]:
    role_rank = 0 if entry.selection_role == "core" else 1
    mechanism_overlap = len(set(entry.pack_ids).intersection(mechanism_packs))
    answer_overlap = len(
        set(entry.answer_value_types).intersection(answer_types)
    )
    return (
        role_rank,
        -mechanism_overlap,
        -answer_overlap,
        -len(entry.capability_ids),
        entry.example_id,
    )


def _restore_locked_entry(
    index: FunctionalFewShotIndex,
    *,
    record: FunctionalFewShotSelectionRecord,
    mode: FunctionalFewShotSelectionMode,
    family_id: str | None,
    problem_id: str | None,
    available_capabilities: set[str],
    current_packs: set[str],
) -> FunctionalFewShotEntry:
    if record.mode != mode or record.family_id != family_id:
        raise ValueError(
            "planner_configuration_error: locked functional few-shot context "
            "does not match the current mode/family"
        )
    entry = next(
        (item for item in index.entries if item.example_id == record.example_id),
        None,
    )
    if entry is None or entry.source_problem_id != record.source_problem_id:
        raise ValueError(
            "planner_configuration_error: locked functional few-shot asset "
            f"is unavailable: {record.example_id}"
        )
    if not set(entry.capability_ids) <= available_capabilities:
        raise ValueError(
            "planner_configuration_error: locked functional few-shot is no "
            f"longer catalog-compatible: {record.example_id}"
        )
    if (
        entry.selection_role == "fallback"
        and not set(entry.pack_ids) <= current_packs
    ):
        raise ValueError(
            "planner_configuration_error: locked functional few-shot fallback "
            f"is no longer pack-compatible: {record.example_id}"
        )
    if mode == "strict_test" and problem_id == entry.source_problem_id:
        raise ValueError(
            "planner_configuration_error: strict_test cannot restore a "
            "same-problem functional few-shot"
        )
    return entry


def _prompt_projection(
    entry: FunctionalFewShotEntry,
    *,
    fixture_dir: Path | str | None,
) -> dict[str, Any]:
    return project_functional_few_shot_prompt_example(
        entry,
        source_plan=load_functional_plan_fixture(
            entry.source_problem_id,
            fixture_dir=fixture_dir,
        ),
    )


def _selected_source_calls(
    source_plan: Mapping[str, Any],
    source_call_ids: Iterable[str],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    wanted = set(source_call_ids)
    found: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for scope in source_plan.get("scopes", ()):
        for call in scope.get("calls", ()):
            if call.get("call_id") in wanted:
                found.append((scope, call))
    found_ids = {str(call["call_id"]) for _scope, call in found}
    missing = sorted(wanted - found_ids)
    if missing:
        raise ValueError(
            f"functional few-shot source calls not found: {missing}"
        )
    scope_ids = {str(scope["scope_id"]) for scope, _call in found}
    if len(scope_ids) != 1:
        raise ValueError(
            "functional few-shot mechanism subgraph must stay in one source scope"
        )
    return found


def _neutralized_call(
    call: Mapping[str, Any],
    entry: FunctionalFewShotEntry,
) -> dict[str, Any]:
    def rewrite(value: Any) -> Any:
        if isinstance(value, dict):
            if "from_call" in value:
                return {
                    "from_call": entry.call_id_map[str(value["from_call"])],
                    "return": value["return"],
                }
            if "ref" in value and "kind" in value:
                result = dict(value)
                result["ref"] = entry.semantic_ref_map[str(value["ref"])]
                return result
            return {key: rewrite(item) for key, item in value.items()}
        if isinstance(value, list):
            return [rewrite(item) for item in value]
        return value

    result = {
        "call_id": entry.call_id_map[str(call["call_id"])],
        "capability_id": call["capability_id"],
        "args": rewrite(call["args"]),
        "return_bindings": rewrite(call["return_bindings"]),
        "strategy": _neutralize_text(str(call["strategy"]), entry),
        "reason": _neutralize_text(str(call["reason"]), entry),
    }
    expectations = call.get("return_expectations")
    if isinstance(expectations, dict) and expectations:
        result["return_expectations"] = dict(expectations)
    return result


def _neutralize_text(text: str, entry: FunctionalFewShotEntry) -> str:
    replacements = {
        **entry.semantic_ref_map,
        **entry.text_replacements,
    }
    result = text
    for source, target in sorted(
        replacements.items(),
        key=lambda item: (-len(item[0]), item[0]),
    ):
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", source):
            result = re.sub(
                rf"(?<![A-Za-z0-9_]){re.escape(source)}(?![A-Za-z0-9_])",
                target,
                result,
            )
        else:
            result = result.replace(source, target)
    return result


def _functional_refs(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if (
            set(value).issuperset({"ref", "kind"})
            or set(value).issuperset({"from_call", "return"})
        ):
            result.append(value)
        else:
            for item in value.values():
                result.extend(_functional_refs(item))
    elif isinstance(value, list):
        for item in value:
            result.extend(_functional_refs(item))
    return result


def _validate_source_call(
    call: object,
    seen_calls: set[str],
) -> None:
    if not isinstance(call, dict):
        raise TypeError("functional plan fixture call must be an object")
    required = {
        "call_id",
        "capability_id",
        "args",
        "return_bindings",
        "strategy",
        "reason",
    }
    allowed = {*required, "return_expectations"}
    if not required <= set(call) or not set(call) <= allowed:
        raise ValueError(
            "functional plan fixture call must contain required fields and only "
            "optional return_expectations"
        )
    call_id = _required_text(call, "call_id")
    if _CALL_ID_RE.fullmatch(call_id) is None:
        raise ValueError(f"invalid functional call id: {call_id}")
    if call_id in seen_calls:
        raise ValueError(f"duplicate functional call id: {call_id}")
    seen_calls.add(call_id)
    _required_text(call, "capability_id")
    _required_text(call, "strategy")
    _required_text(call, "reason")
    if not isinstance(call.get("args"), dict):
        raise TypeError("functional plan fixture args must be an object")
    if not isinstance(call.get("return_bindings"), dict):
        raise TypeError(
            "functional plan fixture return_bindings must be an object"
        )
    expectations = call.get("return_expectations", {})
    if not isinstance(expectations, dict):
        raise TypeError(
            "functional plan fixture return_expectations must be an object"
        )
    for name, form in expectations.items():
        if not isinstance(name, str) or not name:
            raise ValueError("functional return expectation name must be non-empty")
        if form not in {"open_expression", "closed_value"}:
            raise ValueError(f"unknown functional return expectation: {form}")
    for ref in _functional_refs(call):
        if "from_call" in ref:
            if set(ref) != {"from_call", "return"}:
                raise ValueError(
                    "CallResultRef must contain from_call and return"
                )
            continue
        allowed = {"ref", "kind", "value_type"}
        if not {"ref", "kind"} <= set(ref) or not set(ref) <= allowed:
            raise ValueError(
                "SemanticRef must contain ref, kind, and optional value_type"
            )
        if ref["kind"] not in SEMANTIC_READ_KINDS:
            raise ValueError(f"unknown SemanticRef kind: {ref['kind']}")
        if looks_like_canonical_ref(
            str(ref["ref"]),
            allowed_kinds=SEMANTIC_READ_KINDS,
        ):
            raise ValueError(
                "functional plan fixture SemanticRef must be short"
            )


def _condition_payload(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError("functional few-shot condition must be an object")
    allowed = {"ref", "kind", "description", "value_type"}
    if not {"ref", "kind", "description"} <= set(value) or not set(value) <= allowed:
        raise ValueError(
            "functional few-shot condition must contain ref, kind, "
            "description, and optional value_type"
        )
    result = {
        "ref": _required_text(value, "ref"),
        "kind": _required_text(value, "kind"),
        "description": _required_text(value, "description"),
    }
    if result["kind"] not in SEMANTIC_READ_KINDS:
        raise ValueError(
            f"unknown functional few-shot condition kind: {result['kind']}"
        )
    if "value_type" in value:
        result["value_type"] = _required_text(value, "value_type")
    return result


def _selection_role(value: object) -> FunctionalFewShotSelectionRole:
    if value is None:
        return "supporting"
    if value == "core":
        return "core"
    if value == "supporting":
        return "supporting"
    if value == "fallback":
        return "fallback"
    raise ValueError(
        "functional few-shot selection_role must be core, supporting, or "
        "fallback"
    )


def _selection_mode(value: object) -> FunctionalFewShotSelectionMode:
    if value == "strict_test":
        return "strict_test"
    if value == "new_problem":
        return "new_problem"
    raise ValueError(
        "functional few-shot mode must be strict_test or new_problem"
    )


def _selection_tier(value: object) -> FunctionalFewShotSelectionTier:
    if value == "same_family":
        return "same_family"
    if value == "cross_family":
        return "cross_family"
    if value == "fallback":
        return "fallback"
    raise ValueError(
        "functional few-shot selection_tier must be same_family, "
        "cross_family, or fallback"
    )


def _validate_annotation_safety(
    annotation: FunctionalFewShotAnnotation | None,
    *,
    entry: FunctionalFewShotEntry,
) -> None:
    if annotation is None:
        return
    payload = annotation.to_payload()
    serialized = json.dumps(payload, ensure_ascii=False)
    if entry.source_problem_id in serialized:
        raise ValueError(
            "functional few-shot annotation must not expose source problem id"
        )
    if _contains_canonical_handle(serialized):
        raise ValueError(
            "functional few-shot annotation must not contain canonical handles"
        )
    if _SOURCE_TEXT_NUMBER_RE.search(serialized):
        raise ValueError(
            "functional few-shot annotation must not contain concrete numbers"
        )
    for source_ref, neutral_ref in entry.semantic_ref_map.items():
        if source_ref == neutral_ref or not re.fullmatch(
            r"[A-Za-z][A-Za-z0-9_]*",
            source_ref,
        ):
            continue
        if re.search(
            rf"(?<![A-Za-z0-9_]){re.escape(source_ref)}(?![A-Za-z0-9_])",
            serialized,
        ):
            raise ValueError(
                "functional few-shot annotation contains source-specific ref: "
                f"{source_ref}"
            )


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{key} must be a non-empty string")
    return value.strip()


def _string_tuple(payload: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise TypeError(f"{key} must be an array")
    items = tuple(
        item.strip()
        for item in value
        if isinstance(item, str) and item.strip()
    )
    if len(items) != len(value):
        raise TypeError(f"{key} must contain non-empty strings")
    return items


def _string_map(payload: Mapping[str, Any], key: str) -> dict[str, str]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise TypeError(f"{key} must be an object")
    result: dict[str, str] = {}
    for source, target in value.items():
        if (
            not isinstance(source, str)
            or not source
            or not isinstance(target, str)
            or not target
        ):
            raise TypeError(f"{key} must map non-empty strings to strings")
        result[source] = target
    return result


def _collect_keys(value: Any) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            result.add(str(key))
            result.update(_collect_keys(item))
    elif isinstance(value, list):
        for item in value:
            result.update(_collect_keys(item))
    return result


def _contains_canonical_handle(serialized: str) -> bool:
    return any(
        f'"{kind}:' in serialized
        for kind in SEMANTIC_READ_KINDS
    )


def _prompt_explanatory_text(payload: Mapping[str, Any]) -> Iterable[str]:
    for scope in payload.get("scopes", ()):
        for call in scope.get("calls", ()):
            for key in ("strategy", "reason"):
                value = call.get(key)
                if isinstance(value, str):
                    yield value
