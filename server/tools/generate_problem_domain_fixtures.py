"""Generate reviewed problem-domain gold from the five canonical Solver fixtures.

This is an authoring migration tool, not a production extraction path.  Its
output is checked in and reviewed like any other gold fixture.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
from typing import Any, Mapping

from shuxueshuo_server.solver.extraction.problem_domain import ProblemDraft


ROOT = Path(__file__).resolve().parents[2]
CASES = (
    "tj-2026-nankai-yimo-25",
    "tj-2026-heping-ermo-25",
    "tj-2026-xiqing-yimo-25",
    "tj-2026-hexi-yimo-25",
    "tj-2026-heping-yimo-25",
)
SYNTHETIC_DISCUSSION_CASE = "synthetic-discussed-quadratic-minimum-25"
FAMILY_BY_TYPE = {
    "quadratic_path_minimum": "QuadraticPathMinimumSolver",
    "quadratic_square_reflection_path_minimum": "QuadraticSquareReflectionPathMinimumSolver",
    "quadratic_weighted_path_minimum": "QuadraticWeightedPathMinimumSolver",
    "quadratic_equal_length_ray_path_minimum": "QuadraticEqualLengthRayPathMinimumSolver",
}


class Converter:
    def __init__(self, canonical: Mapping[str, Any]) -> None:
        self.raw = canonical
        self.scopes = {str(item["scope_id"]): item for item in canonical["scopes"]}
        self.scope_order = [str(item["scope_id"]) for item in canonical["scopes"]]
        self.entities = {
            str(item["handle"]): item for item in canonical["entities"]
        }
        self.entities_by_scope: dict[str, list[Mapping[str, Any]]] = {}
        for item in canonical["entities"]:
            self.entities_by_scope.setdefault(str(item["scope_id"]), []).append(item)
        self.facts_by_scope: dict[str, list[Mapping[str, Any]]] = {}
        for item in canonical["facts"]:
            self.facts_by_scope.setdefault(str(item["scope_id"]), []).append(item)
        self.goals_by_scope: dict[str, list[Mapping[str, Any]]] = {}
        for item in canonical["question_goals"]:
            self.goals_by_scope.setdefault(str(item["scope_id"]), []).append(item)
        self._declare_square_vertices()
        self.local_ids: dict[str, str] = {}
        self.square_polygon_by_fact: dict[str, str] = {}
        self._assign_local_ids()

    def _declare_square_vertices(self) -> None:
        """Make source-named square vertices explicit in the authored domain gold.

        Older Solver fixtures allowed a square fact to mention a point handle that
        was absent from the entity table.  The domain contract intentionally does
        not: AEKG visibly names K, so the authored migration declares it as a point.
        """

        for fact in self.raw["facts"]:
            if fact["type"] != "square":
                continue
            scope_id = str(fact["scope_id"])
            for handle in fact["vertices"]:
                handle = str(handle)
                if handle in self.entities:
                    continue
                entity = {
                    "handle": handle,
                    "entity_type": "point",
                    "name": handle.rsplit(":", 1)[-1],
                    "scope_id": scope_id,
                    "description": "题面正方形命名的顶点",
                    "definition": "square_vertex",
                }
                self.entities[handle] = entity
                self.entities_by_scope.setdefault(scope_id, []).append(entity)
            side_handle = str(fact["side"])
            if side_handle not in self.entities:
                side_name = side_handle.rsplit(":", 1)[-1]
                vertices_by_name = {
                    str(handle).rsplit(":", 1)[-1]: str(handle)
                    for handle in fact["vertices"]
                }
                if len(side_name) != 2 or any(
                    label not in vertices_by_name for label in side_name
                ):
                    raise ValueError(f"cannot recover square side {side_handle!r}")
                entity = {
                    "handle": side_handle,
                    "entity_type": "segment",
                    "name": side_name,
                    "scope_id": scope_id,
                    "endpoints": [vertices_by_name[label] for label in side_name],
                    "description": "题面正方形命名的边",
                }
                self.entities[side_handle] = entity
                self.entities_by_scope.setdefault(scope_id, []).append(entity)

    def convert(self) -> dict[str, Any]:
        original = self.raw["original_text"]
        lines = list(original["lines"])
        if len(lines) != len(self.scope_order):
            raise ValueError("five-case migration expects one source line per scope")
        source_text = dict(zip(self.scope_order, lines, strict=True))
        children: dict[str, list[str]] = {scope_id: [] for scope_id in self.scope_order}
        for scope_id, item in self.scopes.items():
            parent = item.get("parent")
            if parent is not None:
                children[str(parent)].append(scope_id)

        def scope_payload(scope_id: str) -> dict[str, Any]:
            entities = self._domain_entities(scope_id)
            facts = self._domain_facts(scope_id)
            return {
                "id": scope_id,
                "label": str(self.scopes[scope_id]["label"]),
                "source_text": [source_text[scope_id]],
                "entities": entities,
                "facts": facts,
                "goals": self._domain_goals(scope_id, facts),
                "children": [scope_payload(child) for child in children[scope_id]],
            }

        payload = {
            "schema_version": "problem-domain/v1",
            "problem_id": str(self.raw["problem_id"]),
            "family_id": FAMILY_BY_TYPE[str(self.raw["problem_type"])],
            "source": {
                "question_number": str(original["number"]),
                "score": (
                    str(original["score"])
                    if original.get("score") is not None
                    else None
                ),
            },
            "root": scope_payload("problem"),
        }
        ProblemDraft.create(payload)
        return payload

    def _assign_local_ids(self) -> None:
        for scope_id in self.scope_order:
            ancestor_ids = {
                self.local_ids[handle]
                for handle, entity in self.entities.items()
                if handle in self.local_ids
                and self._is_ancestor(str(entity["scope_id"]), scope_id)
                and str(entity["scope_id"]) != scope_id
            }
            used: set[str] = set()
            for entity in self.entities_by_scope.get(scope_id, ()):
                if entity["entity_type"] == "segment":
                    continue
                handle = str(entity["handle"])
                base = _safe_id(str(entity.get("name") or handle.rsplit(":", 1)[-1]))
                local_id = base
                if local_id in ancestor_ids or local_id in used:
                    local_id = _safe_id(f"{base}_{scope_id}")
                used.add(local_id)
                self.local_ids[handle] = local_id
            for fact in self.facts_by_scope.get(scope_id, ()):
                if fact["type"] != "square":
                    continue
                labels = "".join(
                    str(self.entities[str(handle)].get("name", ""))
                    for handle in fact["vertices"]
                )
                local_id = _safe_id(f"square_{labels}")
                suffix = 2
                while local_id in ancestor_ids or local_id in used:
                    local_id = _safe_id(f"square_{labels}_{suffix}")
                    suffix += 1
                used.add(local_id)
                self.square_polygon_by_fact[str(fact["handle"])] = local_id

    def _domain_entities(self, scope_id: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for raw in self.entities_by_scope.get(scope_id, ()):
            kind = str(raw["entity_type"])
            if kind == "segment":
                continue
            entity: dict[str, Any] = {
                "id": self.local_ids[str(raw["handle"])],
                "kind": {
                    "function": "quadratic_function",
                    "ray": "named_ray",
                }.get(kind, kind),
                "label": str(raw.get("name") or raw["handle"].rsplit(":", 1)[-1]),
            }
            if kind == "symbol":
                entity["role"] = str(raw.get("role") or "parameter")
            elif kind == "ray":
                entity["origin"] = self._ref(scope_id, str(raw["origin"]))
                entity["through"] = self._ref(scope_id, str(raw["through"]))
            result.append(entity)
        for fact in self.facts_by_scope.get(scope_id, ()):
            if fact["type"] != "square":
                continue
            polygon_id = self.square_polygon_by_fact[str(fact["handle"])]
            result.append(
                {
                    "id": polygon_id,
                    "kind": "polygon",
                    "label": polygon_id.removeprefix("square_"),
                    "vertices": [
                        self._ref(scope_id, str(item)) for item in fact["vertices"]
                    ],
                }
            )
        return result

    def _domain_facts(self, scope_id: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        canonical_facts = list(self.facts_by_scope.get(scope_id, ()))
        canonical_types = {str(item["type"]) for item in canonical_facts}
        for raw in self.entities_by_scope.get(scope_id, ()):
            handle = str(raw["handle"])
            kind = str(raw["entity_type"])
            if kind == "function":
                result.append(
                    {
                        "kind": "function_expression",
                        "function": self._ref(scope_id, handle),
                        "variable": self._visible_symbol(scope_id, "x"),
                        "expression": str(raw["expression"]),
                    }
                )
                continue
            if kind != "point":
                continue
            matching = [
                fact
                for fact in self.raw["facts"]
                if str(fact.get("subject") or fact.get("point")) == handle
            ]
            if raw.get("coordinate") is not None and not any(
                fact["type"] == "point_coordinate" for fact in matching
            ):
                result.append(
                    {
                        "kind": "point_coordinate",
                        "point": self._ref(scope_id, handle),
                        "value": [self._expression_value(item) for item in raw["coordinate"]],
                    }
                )
            construction = str(raw.get("definition", ""))
            if construction in {"", "unknown", "point_on_segment", "point_on_ray", "point_on_curve_with_x_coordinate"}:
                continue
            if construction == "point_on_axis" and any(
                fact["type"] == "axis_membership" for fact in matching
            ):
                continue
            if construction == "midpoint" and any(
                fact["type"] == "midpoint_definition" for fact in matching
            ):
                continue
            if construction in {"square_adjacent_vertex", "square_vertex", "square_diagonal_intersection"}:
                continue
            mapped = {
                "coordinate_origin": "origin",
                "vertex": "vertex",
                "x_axis_intercept": "x_axis_intercept",
                "y_axis_intercept": "y_axis_intercept",
                "axis_x_intercept": "axis_x_intercept",
                "translated_point": "translated_point",
                "point_on_parabola_at_x": "curve_at_x",
            }.get(construction)
            if mapped is None:
                continue
            fact: dict[str, Any] = {
                "kind": "point_construction",
                "point": self._ref(scope_id, handle),
                "construction": mapped,
            }
            if raw.get("of") is not None:
                owner = raw["of"]
                if isinstance(owner, str) and owner in self.entities:
                    fact["owner"] = self._ref(scope_id, owner)
                elif isinstance(owner, str):
                    fact["owner"] = self._visible_point(scope_id, owner)
            elif mapped in {
                "vertex",
                "x_axis_intercept",
                "y_axis_intercept",
                "axis_x_intercept",
                "curve_at_x",
            }:
                # Older canonical point metadata sometimes omitted the obvious
                # parabola owner. The authored domain gold makes that visible
                # source relation explicit; production extraction must output it.
                fact["owner"] = self._visible_function(scope_id)
            if raw.get("exclude_point") is not None:
                fact["exclude_point"] = self._visible_point(
                    scope_id, str(raw["exclude_point"])
                )
            if raw.get("side") is not None:
                fact["side"] = str(raw["side"])
            if raw.get("vector") is not None:
                fact["vector"] = [self._expression_value(item) for item in raw["vector"]]
            if raw.get("x") is not None:
                fact["x_expression"] = str(raw["x"])
            result.append(fact)

        for raw in canonical_facts:
            result.extend(self._convert_fact(scope_id, raw))
        return _dedupe(result)

    def _convert_fact(
        self, scope_id: str, raw: Mapping[str, Any]
    ) -> list[dict[str, Any]]:
        kind = str(raw["type"])
        if kind == "symbol_constraint":
            return [{"kind": kind, "symbol": self._ref(scope_id, str(raw["subject"])), "operator": str(raw["operator"]), "value": str(raw["value"])}]
        if kind == "symbol_value":
            return [{"kind": kind, "symbol": self._ref(scope_id, str(raw["subject"])), "value": str(raw["value"])}]
        if kind == "coefficient_relation":
            return [{"kind": "equation", "expression": str(raw["equation"]), "symbols": [self._ref(scope_id, str(item)) for item in raw["subjects"]]}]
        if kind == "point_coordinate":
            return [{"kind": kind, "point": self._ref(scope_id, str(raw["subject"])), "value": [self._expression_value(item) for item in raw["value"]]}]
        if kind == "point_on_curve":
            return [{"kind": kind, "point": self._ref(scope_id, str(raw["point"])), "curve": self._ref(scope_id, str(raw["curve"]))}]
        if kind == "point_on_curve_with_x_coordinate":
            return [{"kind": "point_on_curve_with_x", "point": self._ref(scope_id, str(raw["point"])), "curve": self._ref(scope_id, str(raw["curve"])), "x_symbol": self._ref(scope_id, str(raw["x_symbol"])), "x_range": [str(item) for item in raw["x_range"]]}]
        if kind == "orientation_constraint":
            return [{"kind": "quadrant_membership", "point": self._ref(scope_id, str(raw["subject"])), "quadrant": str(raw["quadrant"])}]
        if kind == "right_angle_equal_length":
            angle = [self._ref(scope_id, str(item)) for item in raw["angle"]]
            return [
                {"kind": "right_angle", "angle": {"start": angle[0], "vertex": angle[1], "end": angle[2]}},
                {"kind": "equal_length", "left": self._segment_term(scope_id, str(raw["equal_segments"][0])), "right": self._segment_term(scope_id, str(raw["equal_segments"][1]))},
            ]
        if kind in {"segment_membership", "point_on_segment"}:
            return [{"kind": "point_on_segment", "point": self._ref(scope_id, str(raw["point"])), "segment": self._segment_term(scope_id, str(raw["segment"]))}]
        if kind == "point_on_ray":
            return [{"kind": kind, "point": self._ref(scope_id, str(raw["point"])), "ray": self._ref(scope_id, str(raw["ray"]))}]
        if kind == "segment_relation":
            return [{"kind": "length_relation", "left": self._scaled_term_from_raw(scope_id, raw["left_term"]), "right": self._scaled_term_from_raw(scope_id, raw["right_term"])}]
        if kind == "segment_length_relation":
            return [{"kind": "length_relation", "left": {"scale": "1", "segment": self._segment_term(scope_id, str(raw["left_segment"]))}, "right": {"scale": str(raw["scale"]), "segment": self._segment_term(scope_id, str(raw["right_segment"]))}}]
        if kind == "midpoint_definition":
            return [{"kind": "midpoint", "point": self._ref(scope_id, str(raw["point"])), "segment": {"start": self._ref(scope_id, str(raw["of"][0])), "end": self._ref(scope_id, str(raw["of"][1]))}}]
        if kind == "path_minimum_target":
            return [{"kind": "minimum_target", "expression": self._length_sum(scope_id, str(raw["path"]), raw.get("terms"))}]
        if kind == "minimum_value":
            return [{"kind": "minimum_value_given", "expression": self._length_sum(scope_id, str(raw["path"]), None), "value": str(raw["value"])}]
        if kind == "length_squared":
            return [{"kind": "length_value", "segment": self._segment_term(scope_id, str(raw["segment"])), "value": str(raw["value"]), "power": 2}]
        if kind == "axis_membership":
            return [{"kind": "point_on_axis", "point": self._ref(scope_id, str(raw["point"])), "axis": "symmetry", "curve": self._ref(scope_id, str(raw["axis_of"]))}]
        if kind == "square":
            return [{"kind": "square", "polygon": self.square_polygon_by_fact[str(raw["handle"])], "side": self._segment_term(scope_id, str(raw["side"])), "orientation": str(raw["orientation"])}]
        if kind == "square_center":
            return [{"kind": "square_center", "point": self._ref(scope_id, str(raw["point"])), "square": self.square_polygon_by_fact[str(raw["square"])]}]
        if kind == "angle_sum":
            return [{"kind": "angle_sum", "angles": [self._angle_term(scope_id, str(item)) for item in raw["angle_terms"]], "value": str(raw["value"])}]
        if kind == "equal_length_condition":
            return [{"kind": "equal_length", "left": self._segment_by_name(scope_id, str(raw["left"])), "right": self._segment_by_name(scope_id, str(raw["right"]))}]
        raise ValueError(f"unsupported canonical fact type {kind!r}")

    def _domain_goals(
        self,
        scope_id: str,
        local_facts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for raw in self.goals_by_scope.get(scope_id, ()):
            value_type = str(raw["value_type"])
            answer_key = str(raw["answer_key"])
            if value_type in {"Point", "PointList"}:
                result.append({"kind": "point_coordinate", "answer_key": answer_key, "target": self._ref(scope_id, str(raw["target_handle"]))})
            elif value_type == "Parabola":
                result.append({"kind": "quadratic_equation", "answer_key": answer_key, "target": self._visible_function(scope_id)})
            elif value_type == "ParameterValue":
                result.append({"kind": "parameter_value", "answer_key": answer_key, "target": self._visible_symbol(scope_id, answer_key)})
            elif value_type == "MinimumExpression":
                target = self._visible_minimum_target(scope_id)
                result.append({"kind": "minimum_value", "answer_key": answer_key, "expression": target})
            else:
                raise ValueError(value_type)
        return result

    def _visible_minimum_target(self, scope_id: str) -> Mapping[str, Any]:
        current: str | None = scope_id
        while current is not None:
            for fact in self._domain_facts(current):
                if fact["kind"] == "minimum_target":
                    return fact["expression"]
            parent = self.scopes[current].get("parent")
            current = str(parent) if parent is not None else None
        raise ValueError(f"minimum goal in {scope_id} has no visible target")

    def _segment_term(self, scope_id: str, handle: str) -> dict[str, str]:
        raw = self.entities[handle]
        return {
            "start": self._ref(scope_id, str(raw["endpoints"][0])),
            "end": self._ref(scope_id, str(raw["endpoints"][1])),
        }

    def _scaled_term_from_raw(self, scope_id: str, raw: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "scale": str(raw["scale"]),
            "segment": {
                "start": self._ref(scope_id, str(raw["segment"][0])),
                "end": self._ref(scope_id, str(raw["segment"][1])),
            },
        }

    def _length_sum(
        self,
        scope_id: str,
        path: str,
        raw_terms: Any,
    ) -> dict[str, Any]:
        if isinstance(raw_terms, list) and raw_terms:
            return {
                "terms": [
                    {
                        "scale": "1",
                        "segment": {
                            "start": self._ref(scope_id, str(item[0])),
                            "end": self._ref(scope_id, str(item[1])),
                        },
                    }
                    for item in raw_terms
                ]
            }
        compact = path.replace(" ", "")
        terms: list[dict[str, Any]] = []
        for raw_term in compact.split("+"):
            match = re.fullmatch(r"(?:(.+?)\*)?([A-Za-z]{2})", raw_term)
            if match is None:
                match = re.fullmatch(r"(\d+)([A-Za-z]{2})", raw_term)
            if match is None:
                raise ValueError(f"unsupported path term {raw_term!r}")
            scale = match.group(1) or "1"
            terms.append(
                {
                    "scale": scale,
                    "segment": self._segment_by_name(scope_id, match.group(2)),
                }
            )
        return {"terms": terms}

    def _segment_by_name(self, scope_id: str, name: str) -> dict[str, str]:
        current: str | None = scope_id
        while current is not None:
            for entity in self.entities_by_scope.get(current, ()):
                if entity["entity_type"] == "segment" and entity.get("name") == name:
                    return self._segment_term(scope_id, str(entity["handle"]))
            parent = self.scopes[current].get("parent")
            current = str(parent) if parent is not None else None
        if len(name) == 2:
            return {
                "start": self._visible_point(scope_id, name[0]),
                "end": self._visible_point(scope_id, name[1]),
            }
        raise ValueError(f"cannot resolve segment {name!r}")

    def _angle_term(self, scope_id: str, name: str) -> dict[str, str]:
        compact = name.replace("∠", "")
        if len(compact) != 3:
            raise ValueError(name)
        return {
            "start": self._visible_point(scope_id, compact[0]),
            "vertex": self._visible_point(scope_id, compact[1]),
            "end": self._visible_point(scope_id, compact[2]),
        }

    def _visible_point(self, scope_id: str, label: str) -> str:
        return self._visible_entity(scope_id, label, "point")

    def _visible_symbol(self, scope_id: str, label: str) -> str:
        return self._visible_entity(scope_id, label, "symbol")

    def _visible_function(self, scope_id: str) -> str:
        return self._visible_entity(scope_id, "parabola", "function")

    def _visible_entity(self, scope_id: str, label: str, kind: str) -> str:
        current: str | None = scope_id
        while current is not None:
            for entity in self.entities_by_scope.get(current, ()):
                if entity["entity_type"] == kind and str(entity.get("name")) == label:
                    return self.local_ids[str(entity["handle"])]
            parent = self.scopes[current].get("parent")
            current = str(parent) if parent is not None else None
        raise ValueError(f"cannot resolve {kind} {label!r} from {scope_id}")

    def _ref(self, scope_id: str, handle: str) -> str:
        if handle not in self.local_ids:
            raise ValueError(f"unknown non-value entity handle {handle!r}")
        target_scope = str(self.entities[handle]["scope_id"])
        if not self._is_ancestor(target_scope, scope_id):
            raise ValueError(f"sibling reference {handle!r} from {scope_id!r}")
        return self.local_ids[handle]

    def _is_ancestor(self, ancestor: str, scope_id: str) -> bool:
        current: str | None = scope_id
        while current is not None:
            if current == ancestor:
                return True
            parent = self.scopes[current].get("parent")
            current = str(parent) if parent is not None else None
        return False

    def _expression_value(self, value: Any) -> str:
        text = str(value)
        if text in self.local_ids:
            return str(self.entities[text].get("name") or self.local_ids[text])
        return text


def _safe_id(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9_]", "_", value)
    if not result or not result[0].isalpha():
        result = "u_" + result
    return result


def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    signatures: set[str] = set()
    for item in items:
        signature = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if signature in signatures:
            continue
        signatures.add(signature)
        result.append(item)
    return result


def main() -> None:
    destination = ROOT / "internal/problem-domain-fixtures"
    destination.mkdir(parents=True, exist_ok=True)
    generated: dict[str, dict[str, Any]] = {}
    for case in CASES:
        source = ROOT / "internal/solver-fixtures" / f"{case}.json"
        canonical = json.loads(source.read_text(encoding="utf-8"))["input"]
        payload = Converter(canonical).convert()
        generated[case] = payload
        (destination / f"{case}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(case)

    # The image discussed while designing problem-domain/v1 has the same source
    # structure as the Nankai case, but explicitly carries a 12-point score. Keep
    # it as a separate contract fixture rather than pretending it is another F0
    # corpus item.
    synthetic = deepcopy(generated["tj-2026-nankai-yimo-25"])
    synthetic["problem_id"] = SYNTHETIC_DISCUSSION_CASE
    synthetic["source"]["score"] = "12"
    ProblemDraft.create(synthetic)
    (destination / f"{SYNTHETIC_DISCUSSION_CASE}.json").write_text(
        json.dumps(synthetic, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(SYNTHETIC_DISCUSSION_CASE)


if __name__ == "__main__":
    main()
