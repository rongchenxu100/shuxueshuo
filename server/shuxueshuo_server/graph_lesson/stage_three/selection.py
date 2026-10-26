"""Contract-driven method selection, independent of execution availability."""

import json
from copy import deepcopy

from jsonschema import Draft202012Validator

from ..stage_two.recognition import DATA, load_nodes
from .fragments import build_fragments
from .premises import check_premise


def load_contract(primary):
    nodes = load_nodes()
    if nodes.get(primary, {}).get("status") == "planned":
        return None
    for rule in nodes.get(primary, {}).get("rules", []):
        path = DATA / "selection" / f"{rule}.json"
        if path.exists():
            contract = json.loads(path.read_text())
            schema = json.loads((DATA.parents[2] / "internal/schemas/graph-method-selection-v1.schema.json").read_text())
            Draft202012Validator(schema).validate(contract)
            if contract.get("schema_version") != "graph-method-selection/v1":
                raise ValueError("selection.unsupported_contract")
            expected = [(b["id"], b["target"]) for b in nodes[rule]["branches"]]
            actual = [(b["branch"], b["target"]) for b in contract["branches"]]
            if expected != actual or contract.get("rule") != rule:
                raise ValueError("selection.contract_node_mismatch")
            return contract
    return None


def _trigger(checks, indexed):
    states = []
    for check in checks:
        feature = indexed.get(check["feature"], {})
        if feature.get("status") != "known":
            states.append("unknown")
            continue
        actual = feature["value"]
        for key in check.get("path", []):
            actual = actual.get(key) if isinstance(actual, dict) else None
        choices = check.get("in", [check.get("equals")])
        holds = any(type(actual) is type(expected) and actual == expected for expected in choices)
        states.append("triggered" if holds else "not_triggered")
    return "not_triggered" if "not_triggered" in states else "unknown" if "unknown" in states else "triggered"


def _matches(condition, branches, indexed, case_split):
    if "all" in condition:
        return all(_matches(item, branches, indexed, case_split) for item in condition["all"])
    if "applicable" in condition:
        return branches[condition["applicable"]]["applicability"] == "applicable"
    if "feature" in condition:
        row = indexed.get(condition["feature"], {})
        expected = condition.get("in", [condition.get("equals")])
        return row.get("status") == "known" and any(
            type(row["value"]) is type(value) and row["value"] == value for value in expected
        )
    if "case_split" in condition:
        return case_split["status"] == condition["case_split"]
    if "applicable_count" in condition:
        return sum(b["applicability"] == "applicable" for b in branches.values()) == condition["applicable_count"]
    if condition == {"fallback": True}:
        return True
    raise ValueError("selection.unknown_recommendation_condition")


def _recommend(contract, branches, indexed):
    case_split = check_premise("interval_case_split", indexed)
    for rule in contract["recommendation"]["rules"]:
        if not _matches(rule["when"], branches, indexed, case_split):
            continue
        applicable = [b for b in contract["recommendation"]["priority"]
                      if branches[b]["applicability"] == "applicable"]
        preferred = rule.get("preferred", applicable[0] if applicable else None)
        if preferred not in applicable:
            continue
        for key in applicable:
            branches[key]["recommendation"] = (
                "preferred" if key == preferred else
                "superseded" if key in rule.get("superseded", []) else "optional"
            )
        return rule["id"], case_split
    return None, case_split


def evaluate_goal(candidate, target_ref, features, primary):
    """Evaluate one admitted stage-two target. Batch 1a executes no routes."""
    if isinstance(primary, dict):
        primary = primary.get("type_id")
    contract = load_contract(primary)
    if contract is None:
        return {"status": "unsupported_type", "selection": None, "d3": None, "d4": None,
                "diagnostics": [{"code": "selection.contract_missing", "type_id": primary}]}
    selected = [row for row in features if row.get("target_ref") == target_ref]
    indexed = {row["feature_id"]: row for row in selected}
    if len(indexed) != len(selected):
        raise ValueError("selection.duplicate_feature")
    branches = {}
    for entry in contract["branches"]:
        trigger = _trigger(entry["trigger"], indexed)
        checks = [check_premise(name, indexed) for name in entry["premises"]] if trigger == "triggered" else []
        statuses = [check["status"] for check in checks]
        applicability = (None if trigger == "not_triggered" else "unknown" if trigger == "unknown"
                         else "not_applicable" if "fails" in statuses else "unknown" if "unknown" in statuses
                         else "applicable")
        branches[entry["branch"]] = {
            "branch": entry["branch"], "target": entry["target"], "route_id": entry["route_id"],
            "trigger": trigger, "applicability": applicability, "recommendation": None,
            "route_plan": "not_planned", "checks": checks, "missing_capabilities": [],
        }
    rule, case_split = _recommend(contract, branches, indexed)
    for branch in branches.values():
        if branch["recommendation"] in ("preferred", "optional"):
            branch["route_plan"] = "capability_gap"
            branch["missing_capabilities"] = [f"execution:{branch['target']}"]
    selection = {"rule": contract["rule"], "branches": list(branches.values()),
                 "recommendation_rule": rule, "recommendation_checks": [case_split]}
    status = "no_verified_route" if rule else "no_applicable_method"
    d3, d4 = (build_fragments(contract, selection, indexed, primary,
                              candidate=candidate, target_ref=target_ref) if rule else (None, None))
    return {"status": status, "selection": deepcopy(selection), "d3": d3, "d4": d4, "diagnostics": []}
