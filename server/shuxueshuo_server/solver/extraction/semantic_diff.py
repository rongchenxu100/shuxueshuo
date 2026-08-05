"""Deterministic semantic comparison for canonical ProblemIR inputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence
import re
import unicodedata


SemanticMismatchKind = Literal[
    "missing",
    "unexpected",
    "value_mismatch",
    "evidence_missing",
]

_TABLE_KEYS = (
    ("scopes", "scope_id"),
    ("entities", "handle"),
    ("facts", "handle"),
    ("question_goals", "handle"),
)
_IGNORED_RECORD_KEYS = frozenset({"description", "display", "source"})
_PUNCTUATION_TRANSLATION = str.maketrans(
    {
        "，": ",",
        "。": ".",
        "；": ";",
        "：": ":",
        "（": "(",
        "）": ")",
        "【": "[",
        "】": "]",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
    }
)


@dataclass(frozen=True)
class ProblemSemanticDiff:
    category: str
    identity: str
    path: str
    kind: SemanticMismatchKind
    expected: Any = None
    actual: Any = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "identity": self.identity,
            "path": self.path,
            "kind": self.kind,
            "expected": self.expected,
            "actual": self.actual,
        }


@dataclass(frozen=True)
class ProblemSemanticDiffReport:
    ok: bool
    differences: tuple[ProblemSemanticDiff, ...]

    @property
    def first_mismatch(self) -> ProblemSemanticDiff | None:
        return self.differences[0] if self.differences else None

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "first_mismatch": (
                self.first_mismatch.to_payload() if self.first_mismatch else None
            ),
            "differences": [item.to_payload() for item in self.differences],
        }


def compare_problem_semantics(
    expected: Mapping[str, Any],
    actual: Mapping[str, Any],
    *,
    actual_evidence: Mapping[str, Mapping[str, Sequence[str]]] | None = None,
) -> ProblemSemanticDiffReport:
    """Compare authored canonical inputs without consulting runtime projections."""

    expected_input = _canonical_input(expected)
    actual_input = _canonical_input(actual)
    differences: list[ProblemSemanticDiff] = []

    for key in ("pattern", "problem_type"):
        _compare_values(
            differences,
            category="problem",
            identity=key,
            path=f"$.{key}",
            expected=_normalize_value(expected_input.get(key)),
            actual=_normalize_value(actual_input.get(key)),
        )

    expected_text = _original_text_snapshot(expected_input)
    actual_text = _original_text_snapshot(actual_input)
    _compare_values(
        differences,
        category="original_text",
        identity="original_text",
        path="$.original_text",
        expected=expected_text,
        actual=actual_text,
    )

    for category, identity_key in _TABLE_KEYS:
        expected_records = _record_index(expected_input.get(category), identity_key)
        actual_records = _record_index(actual_input.get(category), identity_key)
        for identity in sorted(set(expected_records) | set(actual_records)):
            path = f"$.{category}[{identity}]"
            if identity not in actual_records:
                differences.append(
                    ProblemSemanticDiff(
                        category=category,
                        identity=identity,
                        path=path,
                        kind="missing",
                        expected=expected_records[identity],
                    )
                )
                continue
            if identity not in expected_records:
                differences.append(
                    ProblemSemanticDiff(
                        category=category,
                        identity=identity,
                        path=path,
                        kind="unexpected",
                        actual=actual_records[identity],
                    )
                )
                continue
            _compare_values(
                differences,
                category=category,
                identity=identity,
                path=path,
                expected=expected_records[identity],
                actual=actual_records[identity],
            )

    if actual_evidence is not None:
        _compare_evidence_coverage(differences, expected_input, actual_evidence)

    ordered = tuple(
        sorted(
            differences,
            key=lambda item: (item.category, item.identity, item.path, item.kind),
        )
    )
    return ProblemSemanticDiffReport(ok=not ordered, differences=ordered)


def _canonical_input(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    candidate = payload.get("input", payload)
    if not isinstance(candidate, Mapping):
        raise ValueError("canonical ProblemIR input must be an object")
    required = {
        "pattern",
        "problem_type",
        "original_text",
        "scopes",
        "entities",
        "facts",
        "question_goals",
    }
    missing = sorted(required - set(candidate))
    if missing:
        raise ValueError(
            "canonical ProblemIR input is missing: " + ", ".join(missing)
        )
    return candidate


def _original_text_snapshot(payload: Mapping[str, Any]) -> dict[str, Any]:
    original = payload.get("original_text")
    if not isinstance(original, Mapping):
        return {}
    return {
        "number": _normalize_value(original.get("number")),
        "score": _normalize_value(original.get("score")),
        "lines": _normalize_value(original.get("lines", [])),
    }


def _record_index(value: Any, identity_key: str) -> dict[str, Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return {}
    result: dict[str, Any] = {}
    for item in value:
        if not isinstance(item, Mapping):
            continue
        identity = str(item.get(identity_key, "")).strip()
        if not identity:
            continue
        result[identity] = _normalize_value(
            {
                key: child
                for key, child in item.items()
                if key not in _IGNORED_RECORD_KEYS
            }
        )
    return result


def _normalize_value(value: Any) -> Any:
    if isinstance(value, str):
        normalized = unicodedata.normalize("NFKC", value).translate(
            _PUNCTUATION_TRANSLATION
        )
        return re.sub(r"\s+", "", normalized)
    if isinstance(value, Mapping):
        return {
            str(key): _normalize_value(child)
            for key, child in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_normalize_value(item) for item in value]
    return value


def _compare_values(
    differences: list[ProblemSemanticDiff],
    *,
    category: str,
    identity: str,
    path: str,
    expected: Any,
    actual: Any,
) -> None:
    if isinstance(expected, Mapping) and isinstance(actual, Mapping):
        for key in sorted(set(expected) | set(actual), key=str):
            child_path = f"{path}.{key}"
            if key not in actual:
                differences.append(
                    ProblemSemanticDiff(
                        category=category,
                        identity=identity,
                        path=child_path,
                        kind="missing",
                        expected=expected[key],
                    )
                )
            elif key not in expected:
                differences.append(
                    ProblemSemanticDiff(
                        category=category,
                        identity=identity,
                        path=child_path,
                        kind="unexpected",
                        actual=actual[key],
                    )
                )
            else:
                _compare_values(
                    differences,
                    category=category,
                    identity=identity,
                    path=child_path,
                    expected=expected[key],
                    actual=actual[key],
                )
        return
    if isinstance(expected, list) and isinstance(actual, list):
        if expected != actual:
            differences.append(
                ProblemSemanticDiff(
                    category=category,
                    identity=identity,
                    path=path,
                    kind="value_mismatch",
                    expected=expected,
                    actual=actual,
                )
            )
        return
    if expected != actual:
        differences.append(
            ProblemSemanticDiff(
                category=category,
                identity=identity,
                path=path,
                kind="value_mismatch",
                expected=expected,
                actual=actual,
            )
        )


def _compare_evidence_coverage(
    differences: list[ProblemSemanticDiff],
    expected: Mapping[str, Any],
    evidence: Mapping[str, Mapping[str, Sequence[str]]],
) -> None:
    original = expected.get("original_text")
    lines = (
        original.get("lines", [])
        if isinstance(original, Mapping)
        else []
    )
    line_evidence = evidence.get("original_text_lines", {})
    for index, _ in enumerate(lines):
        identity = str(index)
        if not tuple(line_evidence.get(identity, ())):
            differences.append(
                ProblemSemanticDiff(
                    category="original_text_lines",
                    identity=identity,
                    path=f"$.semantic_evidence.original_text_lines.{identity}",
                    kind="evidence_missing",
                )
            )

    for category, identity_key in _TABLE_KEYS:
        records = _record_index(expected.get(category), identity_key)
        evidence_by_id = evidence.get(category, {})
        for identity in sorted(records):
            if not tuple(evidence_by_id.get(identity, ())):
                differences.append(
                    ProblemSemanticDiff(
                        category=category,
                        identity=identity,
                        path=f"$.semantic_evidence.{category}.{identity}",
                        kind="evidence_missing",
                    )
                )
