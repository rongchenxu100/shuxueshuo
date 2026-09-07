"""Audit every Planner-public capability at the teaching/visual boundary.

The public set is derived from the expanded Family catalogs.  Method modules,
recorded plans and hand-maintained allowlists are deliberately not authority
for whether a capability is public.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from shuxueshuo_server.solver.explanation.models import (
    ExplanationSnapshot,
    iter_teaching_sources,
    teaching_source_owners,
)
from shuxueshuo_server.solver.extraction.source_identity import stable_hash
from shuxueshuo_server.solver.family import (
    DEFAULT_CAPABILITY_PACK_REGISTRY,
    DEFAULT_FAMILY_REGISTRY,
    expand_family_spec,
)
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.recipes import (
    ALL_RECIPE_SPEC_SOURCES,
    RecipeSpecRegistry,
)


LESSON_CAPABILITY_COVERAGE_SCHEMA = "lesson-capability-coverage/v1"


class LessonCapabilityCoverageError(ValueError):
    """The public lesson capability inventory is incomplete or ambiguous."""


@dataclass(frozen=True)
class PublicLessonCapability:
    capability_id: str
    kind: str
    source_id: str
    families: tuple[str, ...]
    public_contract: Mapping[str, Any]


def discover_public_lesson_capabilities(
    *,
    method_specs: MethodSpecRegistry | None = None,
) -> tuple[PublicLessonCapability, ...]:
    """Return the exact union of expanded, Planner-visible Family catalogs."""

    method_specs = method_specs or MethodSpecRegistry.load_from_code()
    observed: dict[str, dict[str, Any]] = {}
    for raw_family in DEFAULT_FAMILY_REGISTRY.families:
        family = expand_family_spec(
            raw_family,
            DEFAULT_CAPABILITY_PACK_REGISTRY,
        )
        catalog = FunctionalCapabilityCatalog.from_family_spec(
            family,
            method_specs,
        )
        for capability_id, capability in catalog.items.items():
            source_id = (
                capability.source.method_id
                if capability.kind == "function"
                else capability.source.recipe_id
            )
            contract = capability.to_prompt_payload()
            previous = observed.get(capability_id)
            if previous is None:
                observed[capability_id] = {
                    "kind": capability.kind,
                    "source_id": source_id,
                    "families": {family.family_id},
                    "public_contracts": {family.family_id: contract},
                }
                continue
            if (
                previous["kind"] != capability.kind
                or previous["source_id"] != source_id
            ):
                raise LessonCapabilityCoverageError(
                    "lesson_public_capability_contract_drift: "
                    f"{capability_id}"
                )
            previous["families"].add(family.family_id)
            previous["public_contracts"][family.family_id] = contract

    return tuple(
        PublicLessonCapability(
            capability_id=capability_id,
            kind=str(item["kind"]),
            source_id=str(item["source_id"]),
            families=tuple(sorted(item["families"])),
            public_contract={
                family_id: dict(contract)
                for family_id, contract in sorted(
                    item["public_contracts"].items()
                )
            },
        )
        for capability_id, item in sorted(observed.items())
    )


def build_lesson_capability_coverage(
    *,
    snapshots: Sequence[ExplanationSnapshot] = (),
    synthetic_scenarios: Mapping[str, Mapping[str, Any]] | None = None,
    require_complete: bool = True,
) -> dict[str, Any]:
    """Build the deterministic coverage report used by C0 tests and review."""

    method_registry = MethodSpecRegistry.load_from_code()
    recipe_registry = RecipeSpecRegistry.load_from_code()
    public = discover_public_lesson_capabilities(method_specs=method_registry)
    occurrences = _recorded_occurrences(snapshots)
    synthetic = {
        str(key): dict(value)
        for key, value in (synthetic_scenarios or {}).items()
    }

    cards: dict[str, dict[str, Any]] = {}
    for capability in public:
        if capability.kind == "function":
            card = _function_card(
                capability,
                method_registry=method_registry,
            )
        elif capability.kind == "macro":
            card = _macro_card(
                capability,
                recipe_registry=recipe_registry,
            )
        else:
            raise LessonCapabilityCoverageError(
                "lesson_public_capability_kind_invalid: "
                f"{capability.capability_id}:{capability.kind}"
            )
        card["recorded_occurrences"] = occurrences.get(
            capability.capability_id,
            [],
        )
        card["synthetic_scenario"] = synthetic.get(
            capability.capability_id
        )
        if not card["recorded_occurrences"] and card["synthetic_scenario"] is None:
            card["diagnostics"].append("lesson_capability_execution_coverage_missing")
        cards[capability.capability_id] = card

    unknown_occurrences = sorted(set(occurrences) - set(cards))
    unknown_synthetic = sorted(set(synthetic) - set(cards))
    if unknown_occurrences or unknown_synthetic:
        raise LessonCapabilityCoverageError(
            "lesson_capability_coverage_unknown_capability: "
            f"recorded={unknown_occurrences}, synthetic={unknown_synthetic}"
        )

    public_method_ids = {
        item.source_id for item in public if item.kind == "function"
    }
    internal = [
        {
            "method_id": method_id,
            "public": False,
            "teaching_source_allowed": False,
        }
        for method_id in sorted(set(method_registry.specs) - public_method_ids)
    ]
    diagnostics = [
        {"capability_id": capability_id, "code": code}
        for capability_id, card in cards.items()
        for code in card["diagnostics"]
    ]
    recorded_ids = {
        capability_id
        for capability_id, card in cards.items()
        if card["recorded_occurrences"]
    }
    synthetic_ids = {
        capability_id
        for capability_id, card in cards.items()
        if not card["recorded_occurrences"]
        and card["synthetic_scenario"] is not None
    }
    fingerprint_payload = {
        "public": [
            {
                "capability_id": item.capability_id,
                "kind": item.kind,
                "source_id": item.source_id,
                "families": list(item.families),
                "contract": dict(item.public_contract),
            }
            for item in public
        ],
        "methods": [source.to_payload() for source in _method_sources()],
        "recipes": [source.to_payload() for source in ALL_RECIPE_SPEC_SOURCES],
    }
    report = {
        "schema_version": LESSON_CAPABILITY_COVERAGE_SCHEMA,
        "registry_fingerprint": stable_hash(fingerprint_payload),
        "summary": {
            "public_capability_count": len(public),
            "public_function_count": sum(item.kind == "function" for item in public),
            "public_macro_count": sum(item.kind == "macro" for item in public),
            "recorded_coverage_count": len(recorded_ids),
            "synthetic_coverage_count": len(synthetic_ids),
            "complete_coverage_count": len(recorded_ids | synthetic_ids),
            "diagnostic_count": len(diagnostics),
        },
        "capabilities": cards,
        "internal_capabilities": internal,
        "diagnostics": diagnostics,
    }
    if require_complete and diagnostics:
        raise LessonCapabilityCoverageError(
            "lesson_capability_coverage_incomplete: "
            + ", ".join(
                f"{item['capability_id']}:{item['code']}"
                for item in diagnostics
            )
        )
    return report


def _function_card(
    capability: PublicLessonCapability,
    *,
    method_registry: MethodSpecRegistry,
) -> dict[str, Any]:
    spec = method_registry.require(capability.source_id)
    diagnostics: list[str] = []
    explicit_teaching = spec.teaching_unit is not None
    generic_teaching = spec.generic_teaching_reason is not None
    explicit_visual = spec.visual is not None
    no_new_visual = spec.no_new_visual_reason is not None
    if explicit_teaching == generic_teaching:
        diagnostics.append("lesson_function_teaching_disposition_invalid")
    if explicit_visual == no_new_visual:
        diagnostics.append("lesson_function_visual_disposition_invalid")
    return {
        "kind": capability.kind,
        "source_id": capability.source_id,
        "families": list(capability.families),
        "public_contract": dict(capability.public_contract),
        "teaching_disposition": (
            "explicit" if explicit_teaching else "approved_generic"
            if generic_teaching else "missing"
        ),
        "teaching_units": (
            [spec.teaching_unit.unit_key] if spec.teaching_unit is not None else []
        ),
        "generic_teaching_reason": spec.generic_teaching_reason,
        "visual_disposition": (
            "explicit" if explicit_visual else "no_new_visual"
            if no_new_visual else "missing"
        ),
        "visual_components": (
            [
                str(template.get("component") or "")
                for template in spec.visual.scene_templates
            ]
            if spec.visual is not None
            else []
        ),
        "no_new_visual_reason": spec.no_new_visual_reason,
        "diagnostics": diagnostics,
    }


def _macro_card(
    capability: PublicLessonCapability,
    *,
    recipe_registry: RecipeSpecRegistry,
) -> dict[str, Any]:
    recipe = recipe_registry.get(capability.source_id)
    diagnostics: list[str] = []
    units: list[str] = []
    components: dict[str, list[str]] = {}
    if recipe is None:
        diagnostics.append("lesson_macro_recipe_spec_missing")
    else:
        if recipe.teaching is None:
            diagnostics.append("lesson_macro_teaching_spec_missing")
        else:
            units = [
                unit.unit_key
                for unit in recipe.teaching.teaching_units
                or tuple(
                    unit
                    for variant in recipe.teaching.teaching_variants
                    for unit in variant.teaching_units
                )
            ]
        if recipe.visual is None:
            diagnostics.append("lesson_macro_visual_spec_missing")
        else:
            components = {
                key: [str(item.get("component") or "") for item in templates]
                for key, templates in sorted(
                    recipe.visual.teaching_substep_templates.items()
                )
            }
            expected = {unit.rsplit("/", 1)[-1] for unit in units}
            if expected != set(components):
                diagnostics.append("lesson_macro_visual_unit_coverage_mismatch")
    return {
        "kind": capability.kind,
        "source_id": capability.source_id,
        "families": list(capability.families),
        "public_contract": dict(capability.public_contract),
        "teaching_disposition": "explicit" if units else "missing",
        "teaching_units": units,
        "generic_teaching_reason": None,
        "visual_disposition": "explicit" if components else "missing",
        "visual_components": components,
        "no_new_visual_reason": None,
        "diagnostics": diagnostics,
    }


def _recorded_occurrences(
    snapshots: Sequence[ExplanationSnapshot],
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for snapshot in snapshots:
        owners = teaching_source_owners(snapshot.root_scope)
        seen_steps: set[str] = set()
        for source in iter_teaching_sources(snapshot.root_scope):
            if source.source_step_id in seen_steps:
                raise LessonCapabilityCoverageError(
                    "lesson_capability_occurrence_step_duplicate: "
                    f"{snapshot.problem_id}:{source.source_step_id}"
                )
            seen_steps.add(source.source_step_id)
            scope_ref, goal_ref = owners[source.source_step_id]
            result.setdefault(source.capability_id, []).append(
                {
                    "problem_id": snapshot.problem_id,
                    "step_id": source.source_step_id,
                    "scope_ref": scope_ref,
                    "goal_ref": goal_ref,
                }
            )
    for values in result.values():
        values.sort(
            key=lambda item: (
                str(item["problem_id"]),
                str(item["scope_ref"]),
                str(item["goal_ref"] or ""),
                str(item["step_id"]),
            )
        )
    return result


def _method_sources() -> tuple[Any, ...]:
    from shuxueshuo_server.solver.runtime.methods import ALL_METHOD_SPEC_SOURCES

    return tuple(ALL_METHOD_SPEC_SOURCES)


__all__ = [
    "LESSON_CAPABILITY_COVERAGE_SCHEMA",
    "LessonCapabilityCoverageError",
    "PublicLessonCapability",
    "build_lesson_capability_coverage",
    "discover_public_lesson_capabilities",
]
