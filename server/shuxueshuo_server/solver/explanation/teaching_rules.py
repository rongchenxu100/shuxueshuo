"""Small opt-in registry for code-owned teaching composition.

No inequality business rule is registered by default. A rule-created overview
references an existing material; it never invents a canonical runtime call.
"""

from copy import deepcopy
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class RuleMaterial:
    material: object
    authority: dict
    source: object
    covers: tuple[str, ...]
    references: tuple[str, ...] = ()
    resolved_inputs: dict | None = None


class TeachingRuleRegistry:
    def __init__(self):
        self.rules = {}
        self.merge_units = {}

    def register(self, rule_id, composer, *, merge_unit_keys=()):
        if not rule_id or rule_id in self.rules:
            raise ValueError("teaching_rule_duplicate_or_empty")
        self.rules[rule_id] = composer
        self.merge_units[rule_id] = frozenset(merge_unit_keys)

    def apply(self, projection, snapshot):
        if not self.rules:
            return projection
        from .annotated_teaching import _assert_llm_safe, _stable_hash
        from .models import iter_teaching_sources

        verified_sources = {
            s.source_step_id: s for s in iter_teaching_sources(snapshot.root_scope)
        }
        authority = deepcopy(dict(projection.authority))
        audit = []

        def container(ref, steps):
            if not steps:
                return steps
            records = authority["containers"][ref]
            originals = []
            i = 0
            for source in steps:
                for material in source.teaching_materials:
                    record = records[i]
                    i += 1
                    key = record["source_step_id"] + "/" + record["unit_key"]
                    originals.append(
                        RuleMaterial(
                            material,
                            deepcopy(record),
                            source,
                            (key,),
                            resolved_inputs=verified_sources[source.step_id].inputs,
                        )
                    )
            current = tuple(originals)
            keys = tuple(k for row in originals for k in row.covers)
            owners = {
                row.covers[0]: row.authority["source_step_id"] for row in originals
            }
            for rule_id, composer in self.rules.items():
                candidate = tuple(
                    composer(
                        ref,
                        current,
                        deepcopy(
                            {
                                k: v
                                for k, v in snapshot.evidence.items()
                                if v.get("step_id") in set(owners.values())
                            }
                        ),
                    )
                )
                coverage = tuple(k for row in candidate for k in row.covers)
                mergeable = self.merge_units[rule_id]
                merged = {k for r in candidate if len(r.covers) > 1 for k in r.covers}
                if (
                    len(coverage) != len(keys)
                    or set(coverage) != set(keys)
                    or tuple(k for k in coverage if k not in merged)
                    != tuple(k for k in keys if k not in merged)
                ):
                    raise ValueError("teaching_rule_coverage_or_order_invalid")
                seen = set()
                for row in candidate:
                    if len(row.covers) > 1 and not any(r.covers == row.covers for r in current):
                        merged_originals = [
                            o for o in originals if o.covers[0] in row.covers
                        ]
                        if not all(
                            o.authority["unit_key"] in mergeable
                            for o in merged_originals
                        ):
                            raise ValueError("teaching_rule_merge_not_supported")
                    if len(row.covers) > 1 and not row.authority["requires_independent_lesson_step"]:
                        raise ValueError("teaching_rule_independent_boundary_removed")
                    if len(row.covers) == 1:
                        original = next(o for o in originals if o.covers == row.covers)
                        if (
                            original.authority["requires_independent_lesson_step"]
                            and not row.authority["requires_independent_lesson_step"]
                        ):
                            raise ValueError(
                                "teaching_rule_independent_boundary_removed"
                            )
                    refs = row.covers or row.references
                    if not refs or any(r not in owners for r in refs):
                        raise ValueError("teaching_rule_source_missing")
                    declared_sources = row.authority.get(
                        "source_step_ids", [row.authority["source_step_id"]]
                    )
                    if set(declared_sources) != {owners[r] for r in refs}:
                        raise ValueError("teaching_rule_source_coverage_invalid")
                    if row.authority["source_step_id"] not in {owners[r] for r in refs}:
                        raise ValueError("teaching_rule_owner_changed")
                    if (
                        row.source.step_id != row.authority["source_step_id"]
                        or row.source.capability_id != row.authority["capability_id"]
                    ):
                        raise ValueError("teaching_rule_capability_changed")
                    key = (row.authority["source_step_id"], row.authority["unit_key"])
                    if key in seen:
                        raise ValueError("teaching_rule_unit_duplicated")
                    seen.add(key)
                audit.append(
                    {
                        "rule_id": rule_id,
                        "container": ref,
                        "coverage": [
                            {
                                "unit_key": r.authority["unit_key"],
                                "covers": list(r.covers),
                                "references": list(r.references),
                            }
                            for r in candidate
                        ],
                    }
                )
                current = candidate
            new_records = []
            new_steps = []
            for position, row in enumerate(current):
                record = deepcopy(row.authority)
                record.update(
                    position=position,
                    teaching_step_ref=f"s{position + 1}",
                    suggestion_hash=_stable_hash(row.material.to_payload()),
                )
                new_records.append(record)
                new_steps.append(
                    replace(row.source, teaching_materials=(row.material,))
                )
            authority["containers"][ref] = new_records
            authority["independent_step_refs"][ref] = [
                r["teaching_step_ref"]
                for r in new_records
                if r["requires_independent_lesson_step"]
            ]
            return tuple(new_steps)

        def scope(node):
            return replace(
                node,
                steps=container("scope:" + node.scope_ref, node.steps),
                goals=tuple(
                    replace(g, steps=container("goal:" + g.goal_ref, g.steps))
                    for g in node.goals
                ),
                children=tuple(scope(c) for c in node.children),
            )

        plan = replace(projection.plan, root_scope=scope(projection.plan.root_scope))
        _assert_llm_safe(plan.to_payload(), path="$.rule_plan")
        authority["annotated_plan_hash"] = _stable_hash(plan.to_payload())
        authority["rule_composition"] = audit
        return replace(projection, plan=plan, authority=authority)
