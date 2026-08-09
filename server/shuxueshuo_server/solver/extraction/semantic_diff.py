"""Deterministic semantic comparison for canonical ProblemIR inputs."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from typing import Any, Literal, Mapping, Sequence
import re
import sympy as sp
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


def compare_solver_projection_semantics(
    expected: Mapping[str, Any],
    actual: Mapping[str, Any],
) -> ProblemSemanticDiffReport:
    """Compare Solver projections without treating runtime ids as source semantics.

    Domain projection intentionally regenerates handles and materializes value objects.
    This audit therefore compares the mathematical records carried by those runtime
    nodes, while the domain semantic hash remains the authority for unexpected source
    nodes. The comparison is asymmetric only for support entities: an old fixture may
    reference a segment or square vertex without declaring it, whereas the typed
    projector must materialize that node before Context construction.
    """

    expected_input = _canonical_input(expected)
    actual_input = _canonical_input(actual)
    expected_snapshot = _solver_projection_snapshot(expected_input)
    actual_snapshot = _solver_projection_snapshot(actual_input)
    differences: list[ProblemSemanticDiff] = []

    for key in ("pattern", "problem_type"):
        _compare_values(
            differences,
            category="projection",
            identity=key,
            path=f"$.{key}",
            expected=expected_snapshot[key],
            actual=actual_snapshot[key],
        )

    expected_entities = set(expected_snapshot["entities"])
    actual_entities = set(actual_snapshot["entities"])
    for signature in sorted(expected_entities - actual_entities):
        differences.append(
            ProblemSemanticDiff(
                category="entities",
                identity=signature,
                path="$.entities",
                kind="missing",
                expected=1,
            )
        )

    # Legacy flat fixtures may repeat one ancestor-visible fact in multiple sibling
    # scopes. The nested domain graph stores that source authority once, so fact
    # multiplicity is not mathematical semantics here.
    expected_facts = set(expected_snapshot["facts"])
    actual_facts = set(actual_snapshot["facts"])
    for signature in sorted(expected_facts - actual_facts):
        differences.append(
            ProblemSemanticDiff(
                category="facts",
                identity=signature,
                path="$.facts",
                kind="missing",
                expected=1,
            )
        )

    expected_records = Counter(expected_snapshot["question_goals"])
    actual_records = Counter(actual_snapshot["question_goals"])
    for signature, count in sorted((expected_records - actual_records).items()):
        differences.append(
            ProblemSemanticDiff(
                category="question_goals",
                identity=signature,
                path="$.question_goals",
                kind="missing",
                expected=count,
            )
        )
    for signature, count in sorted((actual_records - expected_records).items()):
        differences.append(
            ProblemSemanticDiff(
                category="question_goals",
                identity=signature,
                path="$.question_goals",
                kind="unexpected",
                actual=count,
            )
        )

    ordered = tuple(
        sorted(
            differences,
            key=lambda item: (item.category, item.identity, item.path, item.kind),
        )
    )
    return ProblemSemanticDiffReport(ok=not ordered, differences=ordered)


def _solver_projection_snapshot(payload: Mapping[str, Any]) -> dict[str, Any]:
    entities = tuple(
        item for item in payload.get("entities", ()) if isinstance(item, Mapping)
    )
    entity_by_handle = {
        str(item.get("handle")): item for item in entities if item.get("handle")
    }
    parent_scope = {
        str(item.get("scope_id")): (
            str(item.get("parent", item.get("parent_scope")))
            if item.get("parent", item.get("parent_scope")) is not None
            else None
        )
        for item in payload.get("scopes", ())
        if isinstance(item, Mapping) and item.get("scope_id")
    }
    semantic_names = {
        str(item.get("handle")): _runtime_entity_semantic_name(item)
        for item in entities
        if item.get("handle")
    }

    def point_ref_for_label(scope_id: str, label: str) -> str:
        current: str | None = scope_id
        while current is not None:
            for entity in entities:
                if (
                    entity.get("entity_type") == "point"
                    and str(entity.get("scope_id")) == current
                    and str(entity.get("name")) == label
                ):
                    return f"point:{_projection_text(label)}"
            current = parent_scope.get(current)
        return f"point:{_projection_text(label)}"

    def entity_ref(value: Any) -> str:
        text = str(value)
        entity = entity_by_handle.get(text)
        if entity is None:
            segment_match = re.match(r"^segment:([^:]+):(.)(.)$", text)
            if segment_match:
                endpoints = sorted(
                    (
                        point_ref_for_label(segment_match.group(1), segment_match.group(2)),
                        point_ref_for_label(segment_match.group(1), segment_match.group(3)),
                    )
                )
                return "segment(" + ",".join(endpoints) + ")"
            match = re.match(r"^(function|symbol|point|line|ray):([^:]+):(.+)$", text)
            if match:
                return f"{match.group(1)}:{_projection_text(match.group(3))}"
            return _projection_text(text)
        kind = str(entity.get("entity_type", ""))
        if kind == "segment":
            endpoints = tuple(
                sorted(entity_ref(item) for item in entity.get("endpoints", ()))
            )
            return "segment(" + ",".join(endpoints) + ")"
        if kind == "ray":
            endpoints = entity.get("endpoints") or entity.get("of") or ()
            if isinstance(endpoints, Sequence) and not isinstance(endpoints, (str, bytes)):
                resolved = tuple(entity_ref(item) for item in endpoints)
                return "ray(" + ",".join(resolved) + ")"
        name = semantic_names.get(text, _projection_text(entity.get("name")))
        return f"{kind}:{name}"

    def expression(value: Any) -> str:
        text = str(value)
        for handle, entity in sorted(entity_by_handle.items(), key=lambda pair: -len(pair[0])):
            text = text.replace(handle, semantic_names.get(handle, str(entity.get("name", handle))))
        return _projection_text(text).replace("*", "")

    def segment(value: Any) -> str:
        if isinstance(value, Mapping):
            endpoints = (value.get("start"), value.get("end"))
            return "segment(" + ",".join(sorted(entity_ref(item) for item in endpoints)) + ")"
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return "segment(" + ",".join(sorted(entity_ref(item) for item in value)) + ")"
        resolved = entity_ref(value)
        if resolved.startswith("segment("):
            return resolved
        return "segment-name(" + expression(value) + ")"

    entity_snapshot = tuple(
        sorted(
            _runtime_entity_signature(
                item,
                entity_ref=entity_ref,
                expression=expression,
                semantic_name=semantic_names.get(
                    str(item.get("handle")),
                    _projection_text(item.get("name")),
                ),
            )
            for item in entities
            if str(item.get("entity_type")) not in {"segment", "polygon"}
        )
    )
    constructed_curve_points = {
        str(item.get("handle")): (
            str(item.get("of")) if item.get("of") is not None else None
        )
        for item in entities
        if item.get("definition")
        in {
            "vertex",
            "x_axis_intercept",
            "y_axis_intercept",
        }
        and item.get("handle")
    }
    fact_signatures = {
        _runtime_fact_signature(
            item,
            entity_ref=entity_ref,
            expression=expression,
            segment=segment,
        )
        for item in payload.get("facts", ())
        if isinstance(item, Mapping)
    }
    fact_signatures.update(
        _runtime_fact_signature(
            {
                "type": "point_on_curve",
                "point": point,
                "curve": curve,
            },
            entity_ref=entity_ref,
            expression=expression,
            segment=segment,
        )
        for point, curve in constructed_curve_points.items()
        if curve is not None
    )
    fact_snapshot = tuple(sorted(fact_signatures))
    goal_snapshot = tuple(
        sorted(
            _runtime_goal_signature(item, entity_ref=entity_ref)
            for item in payload.get("question_goals", ())
            if isinstance(item, Mapping)
        )
    )
    return {
        "pattern": _projection_text(payload.get("pattern")),
        "problem_type": _projection_text(payload.get("problem_type")),
        "entities": entity_snapshot,
        "facts": fact_snapshot,
        "question_goals": goal_snapshot,
    }


def _runtime_entity_signature(
    item: Mapping[str, Any],
    *,
    entity_ref: Any,
    expression: Any,
    semantic_name: str,
) -> str:
    kind = str(item.get("entity_type", ""))
    payload: dict[str, Any] = {
        "type": kind,
        "name": semantic_name,
    }
    if kind == "symbol":
        role = _projection_text(item.get("role"))
        payload["role"] = (
            "coefficient_or_parameter"
            if role in {"quadratic_coefficient", "primary_parameter", "parameter"}
            else role
        )
    elif kind == "function":
        payload.update(
            {
                "function_type": _projection_text(item.get("function_type")),
                "expression": expression(item.get("expression", "")),
                "coefficient_relation": expression(item.get("coefficient_relation", "")),
            }
        )
    elif kind in {"line", "ray"}:
        endpoints = item.get("endpoints") or item.get("of") or ()
        if isinstance(endpoints, Sequence) and not isinstance(endpoints, (str, bytes)):
            payload["endpoints"] = [entity_ref(value) for value in endpoints]
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _runtime_fact_signature(
    item: Mapping[str, Any],
    *,
    entity_ref: Any,
    expression: Any,
    segment: Any,
) -> str:
    kind = str(item.get("type", ""))
    if kind == "segment_membership":
        kind = "point_on_segment"
    payload: dict[str, Any] = {"type": kind}
    if kind in {"symbol_constraint", "symbol_value"}:
        payload.update(
            {
                "subject": entity_ref(item.get("subject")),
                "value": expression(item.get("value")),
            }
        )
        if kind == "symbol_constraint":
            payload["operator"] = _projection_text(item.get("operator"))
    elif kind == "coefficient_relation":
        payload.update(
            {
                "equation": expression(item.get("equation")),
                "subjects": sorted(entity_ref(value) for value in item.get("subjects", ())),
            }
        )
    elif kind == "point_coordinate":
        payload.update(
            {
                "subject": entity_ref(item.get("subject")),
                "value": [expression(value) for value in item.get("value", ())],
            }
        )
    elif kind == "point_on_curve":
        payload.update(
            {"point": entity_ref(item.get("point")), "curve": entity_ref(item.get("curve"))}
        )
    elif kind == "point_on_curve_with_x_coordinate":
        payload.update(
            {
                "point": entity_ref(item.get("point")),
                "curve": entity_ref(item.get("curve")),
                "x_symbol": entity_ref(item.get("x_symbol")),
                "x_range": [expression(value) for value in item.get("x_range", ())],
            }
        )
    elif kind == "axis_membership":
        payload.update(
            {"point": entity_ref(item.get("point")), "axis_of": entity_ref(item.get("axis_of"))}
        )
    elif kind == "point_on_segment":
        payload.update(
            {"point": entity_ref(item.get("point")), "segment": segment(item.get("segment"))}
        )
    elif kind == "point_on_ray":
        payload.update(
            {"point": entity_ref(item.get("point")), "ray": entity_ref(item.get("ray"))}
        )
    elif kind == "orientation_constraint":
        payload.update(
            {
                "subject": entity_ref(item.get("subject")),
                "quadrant": _projection_orientation(item.get("quadrant")),
            }
        )
    elif kind == "midpoint_definition":
        payload.update(
            {
                "point": entity_ref(item.get("point")),
                "of": sorted(entity_ref(value) for value in item.get("of", ())),
            }
        )
    elif kind == "right_angle_equal_length":
        payload.update(
            {
                "angle": [entity_ref(value) for value in item.get("angle", ())],
                "equal_segments": sorted(segment(value) for value in item.get("equal_segments", ())),
            }
        )
    elif kind == "equal_length_condition":
        payload.update(
            {
                "left": expression(item.get("left")),
                "right": expression(item.get("right")),
            }
        )
    elif kind == "angle_sum":
        payload.update(
            {
                "angles": [expression(value) for value in item.get("angle_terms", ())],
                "value": expression(item.get("value")),
            }
        )
    elif kind in {"length_squared", "segment_length"}:
        value = expression(item.get("value"))
        if kind == "segment_length":
            value = _squared_expression(value)
        payload.update(
            {
                "type": "length_squared",
                "segment": segment(item.get("segment")),
                "value": value,
            }
        )
    elif kind in {"segment_relation", "segment_length_relation"}:
        if kind == "segment_relation":
            left_term = item.get("left_term", {})
            right_term = item.get("right_term", {})
            payload = {
                "type": "length_relation",
                "left": segment(left_term.get("segment")),
                "left_scale": expression(left_term.get("scale", "1")),
                "right": segment(right_term.get("segment")),
                "right_scale": expression(right_term.get("scale", "1")),
            }
        else:
            payload = {
                "type": "length_relation",
                "left": segment(item.get("left_segment")),
                "left_scale": "1",
                "right": segment(item.get("right_segment")),
                "right_scale": expression(item.get("scale", "1")),
            }
    elif kind == "square":
        payload.update(
            {
                "vertices": [entity_ref(value) for value in item.get("vertices", ())],
                "side": segment(item.get("side")),
                "orientation": _projection_orientation(item.get("orientation")),
            }
        )
    elif kind == "square_center":
        payload["point"] = entity_ref(item.get("point"))
    elif kind == "path_minimum_target":
        payload["path"] = expression(item.get("path"))
    elif kind == "minimum_value":
        payload.update(
            {"path": expression(item.get("path")), "value": expression(item.get("value"))}
        )
    else:
        payload["fields"] = {
            str(key): _normalize_value(value)
            for key, value in sorted(item.items())
            if key not in {"handle", "description", "scope_id", "valid_scope", "type"}
        }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _runtime_goal_signature(item: Mapping[str, Any], *, entity_ref: Any) -> str:
    payload = {
        "value_type": _projection_text(item.get("value_type")),
        "target": (
            entity_ref(item.get("target_handle"))
            if item.get("target_handle") is not None
            else None
        ),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _runtime_entity_semantic_name(item: Mapping[str, Any]) -> str:
    kind = str(item.get("entity_type", ""))
    if kind == "function":
        return "quadratic_function"
    if kind == "symbol":
        return _projection_text(item.get("name"))
    if kind == "point" and str(item.get("definition", "")) == "vertex":
        return "vertex"
    runtime_name = str(item.get("name") or "")
    if kind == "point" and re.fullmatch(r"[A-Z](?:_[A-Za-z0-9]+)?", runtime_name):
        return runtime_name
    source = str(item.get("description") or item.get("name") or "")
    tokens = re.findall(
        r"[A-Za-z]+(?:_[A-Za-z0-9]+)?",
        unicodedata.normalize("NFKC", source),
    )
    if tokens:
        ignored = {"point", "line", "ray", "segment", "symbol"}
        suffix = runtime_name.rsplit("_", 1)[-1]
        if suffix in tokens:
            return suffix
        useful = [item for item in tokens if item.casefold() not in ignored]
        if useful:
            one_letter = [item for item in useful if len(item) == 1 and item.isupper()]
            return one_letter[-1] if one_letter else useful[-1]
    return _projection_text(item.get("name"))


def _squared_expression(value: str) -> str:
    try:
        return _projection_text(
            sp.sstr(sp.simplify(sp.sympify(value.replace("^", "**")) ** 2))
        ).replace("*", "")
    except (TypeError, ValueError, sp.SympifyError):
        return f"({value})^2"


def _projection_text(value: Any) -> str:
    return re.sub(
        r"\s+",
        "",
        unicodedata.normalize("NFKC", "" if value is None else str(value)).translate(
            _PUNCTUATION_TRANSLATION
        ),
    )


def _projection_orientation(value: Any) -> str:
    normalized = _projection_text(value).casefold()
    if "x轴下方" in normalized or normalized == "below_x_axis":
        return "below_x_axis"
    if "x轴上方" in normalized or normalized == "above_x_axis":
        return "above_x_axis"
    if "第四象限" in normalized or normalized in {
        "4",
        "fourth",
        "iv",
        "quadrant4",
        "quadrant_4",
    }:
        return "quadrant_4"
    return normalized


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
